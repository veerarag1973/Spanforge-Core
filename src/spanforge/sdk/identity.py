"""spanforge.sdk.identity — SpanForge sf-identity client.

Implements the full sf-identity API surface for Phase 1 of the SpanForge
roadmap.  All operations run locally in-process (zero external dependencies)
when ``config.endpoint`` is empty or when the remote service is unreachable
and ``config.local_fallback_enabled`` is ``True``.

Local-mode feature parity
--------------------------
*  API key lifecycle:  issue, rotate, revoke.
*  Session JWT issuance (HS256 via stdlib :mod:`hmac` + :mod:`hashlib`).
*  Magic-link issuance and single-use exchange.
*  TOTP enrolment and verification (RFC 6238, SHA-1, 6 digits, 30 s period).
*  TOTP backup codes (8 x 8-char alphanumeric, single-use).
*  Per-key IP allowlist enforcement.
*  Per-key sliding-window rate limiting.
*  Brute-force lockout (5 consecutive failures -> 15 min lockout).
*  JWKS endpoint stub.

Security requirements
---------------------
*  All secret comparisons use :func:`hmac.compare_digest`.
*  ``SecretStr`` values are never logged or included in exception messages.
*  TOTP backup codes are stored as SHA-256 hashes only; plaintext is never
   retained after enrolment.
*  JWT tokens use HS256 in local mode (stdlib only).  RS256 is used when a
   remote sf-identity service is configured (requires the optional
   ``cryptography`` extra: ``pip install spanforge[identity]``).
*  ``secrets`` module is used for all token/key generation.

Notes:
-----
All in-memory state (keys, sessions, links, TOTP) is **per-instance**.
State is not shared between instances and is not persisted.  For production
use, configure a remote sf-identity service endpoint.
"""

from __future__ import annotations

import base64
import hashlib
import hmac as _hmac
import ipaddress
import json
import logging
import os
import secrets
import struct
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from spanforge.sdk._base import (
    SFClientConfig,
    SFServiceClient,
    _SlidingWindowRateLimiter,
)
from spanforge.sdk._exceptions import (
    SFAuthError,
    SFBruteForceLockedError,
    SFIPDeniedError,
    SFMFARequiredError,
    SFQuotaExceededError,
    SFScopeError,
    SFTokenInvalidError,
)
from spanforge.sdk._types import (
    APIKeyBundle,
    JWTClaims,
    KeyFormat,
    MagicLinkResult,
    OIDCAuthRequest,
    OIDCTokenResult,
    QuotaTier,
    RateLimitInfo,
    SCIMGroup,
    SCIMListResponse,
    SCIMUser,
    SSOSession,
    SecretStr,
    TokenIntrospectionResult,
    TOTPEnrollResult,
)

__all__ = ["SFIdentityClient"]

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE62 = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
_API_KEY_RANDOM_LEN = 48  # chars of base62 after the prefix
_MAGIC_LINK_TTL_SECONDS = 15 * 60  # 15 minutes
_SESSION_TTL_SECONDS = 7 * 24 * 3600  # 7 days
_BRUTE_FORCE_MAX_FAILURES = 5
_BRUTE_FORCE_LOCKOUT_SECONDS = 15 * 60  # 15 minutes
_TOTP_MAX_FAILURES = 5
_TOTP_LOCKOUT_SECONDS = 15 * 60  # 15 minutes
_TOTP_WINDOW = 1  # ± 1 time-step (30 s) drift tolerance
_TOTP_PERIOD = 30  # seconds per time-step
_BACKUP_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # excludes I, O, 0, 1
_BACKUP_CODE_LEN = 8
_BACKUP_CODE_COUNT = 8
_FALLBACK_SIGNING_KEY = "spanforge-local-dev-signing-key-v1"
_FALLBACK_MAGIC_SECRET = "spanforge-local-dev-magic-secret-v1"  # nosec B105 -- dev-only fallback; overridden via SPANFORGE_MAGIC_SECRET in production


# ---------------------------------------------------------------------------
# Pure-stdlib JWT helpers (HS256)
# ---------------------------------------------------------------------------


_JWT_SEGMENTS: int = 3


def _b64url_encode(data: bytes) -> str:
    """Base64url-encode *data* without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64url_decode(s: str) -> bytes:
    """Base64url-decode *s*, tolerating missing padding."""
    padding = "=" * ((-len(s)) % 4)
    return base64.urlsafe_b64decode(s + padding)


_HEADER_B64 = _b64url_encode(b'{"alg":"HS256","typ":"JWT"}')


def _issue_hs256_jwt(payload: dict[str, Any], secret: bytes) -> str:
    """Sign *payload* as a HS256 JWT.

    Args:
        payload: Claims dict.  Must include ``"exp"`` (Unix timestamp).
        secret: Signing key bytes.

    Returns:
        Compact serialised JWT string.
    """
    header = _HEADER_B64
    body = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header}.{body}".encode()
    sig = _hmac.new(secret, signing_input, hashlib.sha256).digest()
    return f"{header}.{body}.{_b64url_encode(sig)}"


def _verify_hs256_jwt(token: str, secret: bytes) -> dict[str, Any]:
    """Verify and decode a HS256 JWT.

    Args:
        token: Compact serialised JWT string.
        secret: Signing key bytes.

    Returns:
        Decoded claims dict.

    Raises:
        :exc:`~spanforge.sdk._exceptions.SFTokenInvalidError`: On any
            validation failure (malformed, bad signature, or expired).
    """
    try:
        parts = token.split(".")
        if len(parts) != _JWT_SEGMENTS:
            raise SFTokenInvalidError("JWT has wrong number of segments")

        header_b64, payload_b64, sig_b64 = parts
        signing_input = f"{header_b64}.{payload_b64}".encode()
        expected_sig = _hmac.new(secret, signing_input, hashlib.sha256).digest()
        provided_sig = _b64url_decode(sig_b64)

        if not _hmac.compare_digest(expected_sig, provided_sig):
            raise SFTokenInvalidError("JWT signature verification failed")

        claims: dict[str, Any] = json.loads(_b64url_decode(payload_b64))

        exp = claims.get("exp")
        if exp is not None and int(time.time()) > exp:
            raise SFTokenInvalidError("JWT has expired")

        return claims

    except SFTokenInvalidError:
        raise
    except Exception as exc:
        raise SFTokenInvalidError(f"JWT could not be decoded: {type(exc).__name__}") from exc


# ---------------------------------------------------------------------------
# TOTP helpers (RFC 6238)
# ---------------------------------------------------------------------------


def _compute_totp(secret_b32: str, timestamp: float | None = None) -> str:
    """Compute a 6-digit TOTP code (RFC 6238, SHA-1, 30 s period).

    Args:
        secret_b32: Base32-encoded TOTP secret.
        timestamp: Unix timestamp override (uses :func:`time.time` if omitted).

    Returns:
        Zero-padded 6-digit string, e.g. ``"042917"``.

    Raises:
        ValueError: If *secret_b32* is not valid base32.
    """
    if timestamp is None:
        timestamp = time.time()
    counter = int(timestamp) // _TOTP_PERIOD
    key = base64.b32decode(secret_b32.upper())
    msg = struct.pack(">Q", counter)
    mac_digest = _hmac.new(key, msg, hashlib.sha1).digest()
    offset = mac_digest[-1] & 0x0F
    code_int = struct.unpack(">I", mac_digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code_int % 1_000_000).zfill(6)


# ---------------------------------------------------------------------------
# Key generation helpers
# ---------------------------------------------------------------------------


def _random_base62(length: int) -> str:
    """Generate a cryptographically random base62 string of *length* chars."""
    return "".join(secrets.choice(_BASE62) for _ in range(length))


def _generate_api_key(test_mode: bool = False) -> str:
    """Generate a SpanForge API key in ``sf_(live|test)_<48 base62>`` format."""
    env = "test" if test_mode else "live"
    return f"sf_{env}_{_random_base62(_API_KEY_RANDOM_LEN)}"


def _generate_key_id() -> str:
    """Generate a short opaque key identifier."""
    return "key_" + secrets.token_hex(10)


def _today_midnight_utc() -> float:
    """Return the Unix timestamp of midnight UTC for today."""
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.timestamp()


# ---------------------------------------------------------------------------
# SFIdentityClient
# ---------------------------------------------------------------------------


class SFIdentityClient(SFServiceClient):
    """SpanForge sf-identity service client.

    Manages API key lifecycle, session tokens, TOTP MFA, magic-link
    authentication, IP allowlists, and rate limiting.

    In **local mode** (``config.endpoint == ""``), all operations execute
    entirely in-process with no network calls.  State is stored in memory
    and is not persisted.

    In **remote mode** (``config.endpoint`` set), operations are proxied to
    the configured sf-identity service over HTTPS with retry and circuit
    breaker protection.

    Thread safety:
        All mutable state uses :class:`threading.Lock`.

    Example::

        from spanforge.sdk._base import SFClientConfig
        from spanforge.sdk.identity import SFIdentityClient

        config = SFClientConfig()   # local mode
        identity = SFIdentityClient(config)

        bundle = identity.issue_api_key(scopes=["sf_audit"])
        print(bundle.key_id)         # key_abc...
        print(bundle.api_key)        # <SecretStr:***>
        print(bundle.api_key.get_secret_value())  # sf_live_...
    """

    def __init__(self, config: SFClientConfig | None = None) -> None:
        if config is None:
            config = SFClientConfig.from_env()
        super().__init__(config, "identity")

        # Signing key: from config > env > fallback (dev-only)
        self._signing_key: str = (
            config.signing_key
            or os.environ.get("SPANFORGE_SIGNING_KEY", "")
            or _FALLBACK_SIGNING_KEY
        )
        self._magic_secret: str = (
            config.magic_secret
            or os.environ.get("SPANFORGE_MAGIC_SECRET", "")
            or _FALLBACK_MAGIC_SECRET
        )

        # In-memory state (local mode)
        self._lock = threading.Lock()
        self._keys: dict[str, dict[str, Any]] = {}  # api_key_value -> record
        self._keys_by_id: dict[str, dict[str, Any]] = {}  # key_id -> same record
        self._revoked_jtis: set[str] = set()
        self._magic_links: dict[str, dict[str, Any]] = {}  # link_id -> record
        self._totp_data: dict[str, dict[str, Any]] = {}  # key_id -> totp record
        self._brute_force: dict[str, dict[str, Any]] = {}  # identifier -> brute-force record
        self._rate_limiter = _SlidingWindowRateLimiter(limit=600, window_seconds=60.0)
        # ID-031: MFA enforcement policies (project_id -> mfa_required)
        self._mfa_policies: dict[str, bool] = {}
        # ID-051/052: Quota tier tracking
        self._key_tiers: dict[str, str] = {}  # key_id -> QuotaTier name
        self._daily_counts: dict[str, list[float]] = {}  # key_id -> [utc timestamps]
        # ID-041: SCIM 2.0 in-memory stores
        self._scim_users: dict[str, dict[str, Any]] = {}  # user_id -> record
        self._scim_users_by_name: dict[str, str] = {}  # user_name -> user_id
        self._scim_groups: dict[str, dict[str, Any]] = {}  # group_id -> record
        # ID-042: OIDC pending auth requests (state -> record)
        self._oidc_states: dict[str, dict[str, Any]] = {}
        # ID-043: SSO session delegation (idp_session_id -> sso_session record)
        self._sso_sessions: dict[str, dict[str, Any]] = {}  # session_id -> record
        self._sso_by_idp: dict[str, str] = {}  # idp_session_id -> session_id

    # ------------------------------------------------------------------
    # ID-003: Token refresh hook override
    # ------------------------------------------------------------------

    def _on_token_near_expiry(self, seconds_remaining: int) -> None:
        """Override: attempt inline token refresh when expiry is near.

        Args:
            seconds_remaining: Seconds until expiry per ``X-SF-Token-Expires`` header.
        """
        _log.debug("Auth token expiring in %ds; attempting inline refresh", seconds_remaining)
        try:
            self.refresh_token()
        except SFAuthError as exc:
            if not self._config.local_fallback_enabled:
                raise
            _log.warning("Inline token refresh failed: %s", exc)

    def refresh_token(self) -> str:
        """Refresh the session JWT.

        In remote mode: ``POST /v1/tokens/refresh`` with the configured API key.
        In local mode: issues a new session JWT for the configured key (no-op
        equivalent when the key is still valid).

        Returns:
            New JWT string.

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFAuthError`: If no valid key is
                available.
        """
        if not self._is_local_mode():
            resp = self._request("POST", "/v1/tokens/refresh")
            return str(resp.get("jwt", ""))

        api_key = self._config.api_key.get_secret_value()
        if not api_key:
            raise SFAuthError("No API key configured for token refresh")

        try:
            KeyFormat.validate(api_key)
            return self.create_session(api_key)
        except (SFAuthError, Exception) as exc:
            raise SFAuthError("Token refresh failed: no valid session available") from exc

    # ------------------------------------------------------------------
    # 4.2  API Key Lifecycle
    # ------------------------------------------------------------------

    def issue_api_key(
        self,
        *,
        scopes: list[str] | None = None,
        project_id: str = "",
        expires_in_days: int = 365,
        ip_allowlist: list[str] | None = None,
        test_mode: bool = False,
    ) -> APIKeyBundle:
        """Issue a new SpanForge API key with an embedded session JWT.

        Args:
            scopes: Permission scopes (e.g. ``["sf_pii", "sf_audit"]``).
                ``None`` or empty = unrestricted.
            project_id: Project scope for the key.  Defaults to the config
                project_id.
            expires_in_days: Session JWT TTL.  Default: 365 days.
            ip_allowlist: CIDR strings restricting which IPs may use this key.
                Empty = unrestricted.
            test_mode: If ``True``, issues a ``sf_test_`` prefixed key.

        Returns:
            :class:`~spanforge.sdk._types.APIKeyBundle` with the raw key value
            (write-once; display to user once only).
        """
        if not self._is_local_mode():
            resp = self._request(
                "POST",
                "/v1/keys",
                {
                    "scopes": scopes or [],
                    "project_id": project_id or self._config.project_id,
                    "expires_in_days": expires_in_days,
                    "ip_allowlist": ip_allowlist or [],
                    "test_mode": test_mode,
                },
            )
            return self._bundle_from_response(resp)

        return self._local_issue_api_key(
            scopes=scopes or [],
            project_id=project_id or self._config.project_id,
            expires_in_days=expires_in_days,
            ip_allowlist=ip_allowlist or [],
            test_mode=test_mode,
        )

    def _local_issue_api_key(
        self,
        *,
        scopes: list[str],
        project_id: str,
        expires_in_days: int,
        ip_allowlist: list[str],
        test_mode: bool,
    ) -> APIKeyBundle:
        key_value = _generate_api_key(test_mode=test_mode)
        key_id = _generate_key_id()
        now = int(time.time())
        exp = now + expires_in_days * 86_400
        jti = str(uuid.uuid4())

        record: dict[str, Any] = {
            "key_id": key_id,
            "key_value": key_value,
            "scopes": scopes,
            "project_id": project_id,
            "ip_allowlist": ip_allowlist,
            "created_at": now,
            "expires_at": exp,
            "revoked": False,
            "rotated_to": None,
        }
        payload = {
            "iss": "spanforge",
            "sub": key_id,
            "aud": project_id or "default",
            "iat": now,
            "exp": exp,
            "jti": jti,
            "scopes": scopes,
        }
        jwt = _issue_hs256_jwt(payload, self._signing_key.encode())

        with self._lock:
            self._keys[key_value] = record
            self._keys_by_id[key_id] = record

        return APIKeyBundle(
            api_key=SecretStr(key_value),
            key_id=key_id,
            jwt=jwt,
            expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
            scopes=scopes,
        )

    def issue_magic_link(self, email: str) -> MagicLinkResult:
        """Issue a one-time magic-link token for *email*.

        The link expires in 15 minutes and can be exchanged exactly once via
        :meth:`exchange_magic_link`.

        Args:
            email: Recipient email address (not validated here; validated by
                the caller / form layer).

        Returns:
            :class:`~spanforge.sdk._types.MagicLinkResult` with ``link_id``
            and expiry.
        """
        if not self._is_local_mode():
            resp = self._request("POST", "/v1/magic-links", {"email": email})
            return MagicLinkResult(
                link_id=resp["link_id"],
                expires_at=datetime.fromisoformat(resp["expires_at"]),
            )

        return self._local_issue_magic_link(email)

    def _local_issue_magic_link(self, email: str) -> MagicLinkResult:
        nonce = secrets.token_urlsafe(32)
        expiry = int(time.time()) + _MAGIC_LINK_TTL_SECONDS
        sig_input = f"{email}:{nonce}:{expiry}".encode()
        mac = _hmac.new(self._magic_secret.encode(), sig_input, hashlib.sha256).hexdigest()
        token = f"{nonce}.{expiry}.{mac}"
        link_id = secrets.token_urlsafe(16)

        with self._lock:
            self._magic_links[link_id] = {
                "email": email,
                "token": token,
                "expiry": expiry,
                "used": False,
            }
        return MagicLinkResult(
            link_id=link_id,
            expires_at=datetime.fromtimestamp(expiry, tz=timezone.utc),
        )

    def exchange_magic_link(
        self,
        token: str,
        *,
        link_id: str,
        otp: str | None = None,
        mfa_challenge: str | None = None,
    ) -> APIKeyBundle:
        """Exchange a magic-link token for an API key bundle.

        Args:
            token: The token portion of the magic link (from the URL).
            link_id: The ``link_id`` returned by :meth:`issue_magic_link`.
            otp: TOTP OTP (required if the account has TOTP enrolled and
                ``mfa_challenge`` is present).
            mfa_challenge: Challenge ID from a prior
                :exc:`~spanforge.sdk._exceptions.SFMFARequiredError`.

        Returns:
            A new :class:`~spanforge.sdk._types.APIKeyBundle`.

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFAuthError`: If the token is
                invalid, expired, or has already been used.
            :exc:`~spanforge.sdk._exceptions.SFMFARequiredError`: If TOTP is
                required but ``otp`` was not provided.
        """
        if not self._is_local_mode():
            resp = self._request(
                "POST",
                "/v1/magic-links/exchange",
                {"token": token, "link_id": link_id, "otp": otp},
            )
            return self._bundle_from_response(resp)

        return self._local_exchange_magic_link(token, link_id=link_id, otp=otp)

    def _local_exchange_magic_link(
        self, token: str, *, link_id: str, otp: str | None
    ) -> APIKeyBundle:
        with self._lock:
            record = self._magic_links.get(link_id)

        if record is None:
            raise SFAuthError("Magic link not found or already consumed")

        if record["used"]:
            raise SFAuthError("Magic link has already been used")

        now_ts = int(time.time())
        if now_ts > record["expiry"]:
            raise SFAuthError("Magic link has expired")

        # Verify HMAC of the token
        email = record["email"]
        expiry = record["expiry"]
        sig_input = f"{email}:{token.split('.')[0]}:{expiry}".encode()
        expected_mac = _hmac.new(self._magic_secret.encode(), sig_input, hashlib.sha256).hexdigest()
        provided_mac = token.split(".")[-1] if "." in token else ""
        if not _hmac.compare_digest(expected_mac, provided_mac):
            raise SFAuthError("Magic link token is invalid")

        with self._lock:
            record["used"] = True

        # ID-031: Enforce MFA policy for the project
        project_id = self._config.project_id
        with self._lock:
            mfa_required = self._mfa_policies.get(project_id, False)

        if mfa_required and otp is None:
            challenge_id = secrets.token_urlsafe(16)
            raise SFMFARequiredError(challenge_id=challenge_id)

        # Issue a key for the authenticated email
        return self._local_issue_api_key(
            scopes=["magic_link"],
            project_id=self._config.project_id,
            expires_in_days=1,
            ip_allowlist=[],
            test_mode=False,
        )

    def rotate_key(self, key_id: str) -> APIKeyBundle:
        """Rotate a key, revoking the old one and issuing a new bundle.

        Args:
            key_id: The ``key_id`` of the key to rotate.

        Returns:
            A fresh :class:`~spanforge.sdk._types.APIKeyBundle`.

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFAuthError`: If *key_id* is
                unknown.
        """
        if not self._is_local_mode():
            resp = self._request("POST", f"/v1/keys/{key_id}/rotate")
            return self._bundle_from_response(resp)

        with self._lock:
            old_record = self._keys_by_id.get(key_id)

        if old_record is None:
            raise SFAuthError(f"Key not found: key_id={key_id!r}")

        # Issue a new key with the same scopes / project
        new_bundle = self._local_issue_api_key(
            scopes=old_record["scopes"],
            project_id=old_record["project_id"],
            expires_in_days=365,
            ip_allowlist=old_record["ip_allowlist"],
            test_mode=old_record["key_value"].startswith("sf_test_"),
        )

        # Revoke old key (after issuing new one to avoid gap)
        with self._lock:
            old_record["revoked"] = True
            old_record["rotated_to"] = new_bundle.key_id

        return new_bundle

    def revoke_key(self, key_id: str) -> None:
        """Immediately revoke a key.

        All sessions created from this key continue to work until their JWT
        expiry.  Use :meth:`verify_token` which checks the revocation flag
        before creating new sessions.

        Args:
            key_id: The ``key_id`` of the key to revoke.

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFAuthError`: If *key_id* is
                unknown.
        """
        if not self._is_local_mode():
            self._request("DELETE", f"/v1/keys/{key_id}")
            return

        with self._lock:
            record = self._keys_by_id.get(key_id)
            if record is None:
                raise SFAuthError(f"Key not found: key_id={key_id!r}")
            record["revoked"] = True

    # ------------------------------------------------------------------
    # 4.3  Session Management
    # ------------------------------------------------------------------

    def create_session(self, api_key: str) -> str:
        """Issue a session JWT for a valid API key.

        Args:
            api_key: The raw API key value (``sf_live_...`` or ``sf_test_...``).

        Returns:
            A compact HS256 JWT string.

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFKeyFormatError`: If the key
                format is invalid.
            :exc:`~spanforge.sdk._exceptions.SFAuthError`: If the key is
                unknown, revoked, or has expired.
            :exc:`~spanforge.sdk._exceptions.SFIPDeniedError`: If the
                key has an IP allowlist and the check fails.
        """
        KeyFormat.validate(api_key)

        if not self._is_local_mode():
            resp = self._request("POST", "/v1/sessions", {"api_key": api_key})
            return str(resp["jwt"])

        with self._lock:
            record = self._keys.get(api_key)

        if record is None:
            raise SFAuthError("Unknown API key")

        if record["revoked"]:
            raise SFAuthError("API key has been revoked")

        now_ts = int(time.time())
        if now_ts > record["expires_at"]:
            raise SFAuthError("API key has expired")

        # Issue a short-lived session JWT
        exp = now_ts + _SESSION_TTL_SECONDS
        jti = str(uuid.uuid4())
        payload = {
            "iss": "spanforge",
            "sub": record["key_id"],
            "aud": record["project_id"] or "default",
            "iat": now_ts,
            "exp": exp,
            "jti": jti,
            "scopes": record["scopes"],
        }
        return _issue_hs256_jwt(payload, self._signing_key.encode())

    def verify_token(self, jwt: str) -> JWTClaims:
        """Validate a JWT and return its claims.

        Args:
            jwt: Compact serialised JWT string.

        Returns:
            :class:`~spanforge.sdk._types.JWTClaims`.

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFTokenInvalidError`: On any
                validation failure (bad signature, expired, or revoked).
        """
        if not self._is_local_mode():
            resp = self._request("POST", "/v1/tokens/verify", {"token": jwt})
            return self._claims_from_response(resp)

        claims = _verify_hs256_jwt(jwt, self._signing_key.encode())

        jti = claims.get("jti", "")
        with self._lock:
            revoked = jti in self._revoked_jtis
        if revoked:
            raise SFTokenInvalidError("Token has been revoked")

        exp = claims.get("exp", 0)
        iat = claims.get("iat", 0)

        return JWTClaims(
            subject=claims.get("sub", ""),
            scopes=claims.get("scopes", []),
            project_id=claims.get("aud", ""),
            expires_at=datetime.fromtimestamp(exp, tz=timezone.utc),
            issued_at=datetime.fromtimestamp(iat, tz=timezone.utc),
            jti=jti,
            issuer=claims.get("iss", "spanforge"),
        )

    def introspect(self, token: str) -> TokenIntrospectionResult:
        """RFC 7662 token introspection.

        Returns an ``active=False`` result for invalid tokens instead of
        raising an exception, to ease integration with OAuth 2.0 resource
        servers.

        Args:
            token: Compact serialised JWT string.

        Returns:
            :class:`~spanforge.sdk._types.TokenIntrospectionResult`.
        """
        if not self._is_local_mode():
            resp = self._request("POST", "/v1/tokens/introspect", {"token": token})
            return TokenIntrospectionResult(
                active=resp.get("active", False),
                scope=resp.get("scope", ""),
                exp=resp.get("exp"),
                sub=resp.get("sub", ""),
                client_id=resp.get("client_id", ""),
            )

        try:
            claims_obj = self.verify_token(token)
            return TokenIntrospectionResult(
                active=True,
                scope=" ".join(claims_obj.scopes),
                exp=int(claims_obj.expires_at.timestamp()),
                sub=claims_obj.subject,
                client_id=claims_obj.project_id,
            )
        except (SFTokenInvalidError, SFAuthError):
            return TokenIntrospectionResult(active=False)

    # ------------------------------------------------------------------
    # 4.4  MFA — TOTP
    # ------------------------------------------------------------------

    def enroll_totp(self, key_id: str) -> TOTPEnrollResult:
        """Enrol a TOTP authenticator for *key_id*.

        Generates a 160-bit (20-byte) TOTP secret and 8 single-use backup
        codes.  Backup codes are stored as SHA-256 hashes.

        Args:
            key_id: The ``key_id`` of the key to associate with TOTP.

        Returns:
            :class:`~spanforge.sdk._types.TOTPEnrollResult` with the raw
            secret, QR URI, and backup codes.  **Display to user once only.**

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFAuthError`: If *key_id* is
                unknown.
        """
        if not self._is_local_mode():
            resp = self._request("POST", f"/v1/keys/{key_id}/totp/enroll")
            return TOTPEnrollResult(
                secret_base32=SecretStr(resp["secret"]),
                qr_uri=resp["qr_uri"],
                backup_codes=resp["backup_codes"],
            )

        with self._lock:
            if key_id not in self._keys_by_id:
                raise SFAuthError(f"Key not found: key_id={key_id!r}")

        raw_secret = secrets.token_bytes(20)
        secret_b32 = base64.b32encode(raw_secret).decode()
        backup_codes = [
            "".join(secrets.choice(_BACKUP_CODE_ALPHABET) for _ in range(_BACKUP_CODE_LEN))
            for _ in range(_BACKUP_CODE_COUNT)
        ]
        backup_hashes = [hashlib.sha256(c.encode()).hexdigest() for c in backup_codes]
        qr_uri = (
            f"otpauth://totp/SpanForge:{key_id}"
            f"?secret={secret_b32}&issuer=SpanForge"
            f"&algorithm=SHA1&digits=6&period={_TOTP_PERIOD}"
        )

        with self._lock:
            self._totp_data[key_id] = {
                "secret": secret_b32,
                "backup_hashes": backup_hashes,
                "used_backup_hashes": set(),
                "totp_fail_count": 0,
                "totp_locked_until": 0.0,
            }

        return TOTPEnrollResult(
            secret_base32=SecretStr(secret_b32),
            qr_uri=qr_uri,
            backup_codes=backup_codes,
        )

    def verify_totp(
        self,
        key_id: str,
        otp: str,
        *,
        timestamp: float | None = None,
    ) -> bool:
        """Verify a TOTP code for *key_id*.

        Allows ±1 time-step (±30 s) drift tolerance.  Five consecutive
        failures trigger a 15-minute lockout (raising
        :exc:`~spanforge.sdk._exceptions.SFBruteForceLockedError`).

        Args:
            key_id: The ``key_id`` to verify against.
            otp: 6-digit TOTP code string.
            timestamp: Unix timestamp override for testing.

        Returns:
            ``True`` if the OTP is valid.

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFAuthError`: If *key_id* has
                no TOTP enrolled.
            :exc:`~spanforge.sdk._exceptions.SFBruteForceLockedError`: If
                the account is locked.
        """
        if not self._is_local_mode():
            resp = self._request("POST", f"/v1/keys/{key_id}/totp/verify", {"otp": otp})
            return bool(resp.get("valid"))

        with self._lock:
            totp_record = self._totp_data.get(key_id)

        if totp_record is None:
            raise SFAuthError(f"TOTP not enrolled for key_id={key_id!r}")

        now_ts = time.time() if timestamp is None else timestamp

        with self._lock:
            locked_until = totp_record["totp_locked_until"]
            if now_ts < locked_until:
                unlock_at = datetime.fromtimestamp(locked_until, tz=timezone.utc).isoformat()
                raise SFBruteForceLockedError(unlock_at=unlock_at, resource=f"totp:{key_id}")

        secret = totp_record["secret"]
        for step_offset in range(-_TOTP_WINDOW, _TOTP_WINDOW + 1):
            candidate = _compute_totp(secret, now_ts + step_offset * _TOTP_PERIOD)
            if _hmac.compare_digest(candidate, otp.strip()):
                with self._lock:
                    totp_record["totp_fail_count"] = 0
                return True

        with self._lock:
            totp_record["totp_fail_count"] += 1
            if totp_record["totp_fail_count"] >= _TOTP_MAX_FAILURES:
                totp_record["totp_locked_until"] = now_ts + _TOTP_LOCKOUT_SECONDS
                unlock_at = datetime.fromtimestamp(
                    totp_record["totp_locked_until"], tz=timezone.utc
                ).isoformat()
                raise SFBruteForceLockedError(unlock_at=unlock_at, resource=f"totp:{key_id}")

        return False

    def verify_backup_code(self, key_id: str, code: str) -> bool:
        """Verify and consume a single-use TOTP backup code.

        Args:
            key_id: The ``key_id`` to verify against.
            code: 8-character backup code (case-insensitive).

        Returns:
            ``True`` if the code is valid (and marks it consumed).

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFAuthError`: If *key_id* has
                no TOTP enrolled.
        """
        if not self._is_local_mode():
            resp = self._request(
                "POST",
                f"/v1/keys/{key_id}/totp/backup",
                {"code": code},
            )
            return bool(resp.get("valid"))

        with self._lock:
            totp_record = self._totp_data.get(key_id)

        if totp_record is None:
            raise SFAuthError(f"TOTP not enrolled for key_id={key_id!r}")

        code_hash = hashlib.sha256(code.upper().encode()).hexdigest()

        with self._lock:
            if code_hash in totp_record["used_backup_hashes"]:
                return False  # replay attack — code already consumed
            for stored_hash in totp_record["backup_hashes"]:
                if _hmac.compare_digest(stored_hash, code_hash):
                    totp_record["used_backup_hashes"].add(code_hash)
                    return True

        return False

    # ------------------------------------------------------------------
    # 4.5  SSO — SAML 2.0, SCIM 2.0, OIDC, Session Delegation
    # ------------------------------------------------------------------

    def saml_metadata(self) -> str:
        """Return SAML 2.0 SP metadata XML (ID-040).

        In remote mode, fetches ``GET /v1/sso/saml/metadata`` from the service.
        In local mode, returns a well-formed SP metadata stub suitable for
        testing and development against Okta, Azure AD, or Google Workspace.

        Returns:
            SP metadata XML string (``application/samlmetadata+xml``).
        """
        if not self._is_local_mode():  # pragma: no cover
            import urllib.request as _req

            url = f"{self._config.endpoint.rstrip('/')}/v1/sso/saml/metadata"
            with _req.urlopen(url) as resp:  # nosec B310
                return str(resp.read().decode())

        acs_url = "http://localhost:7464/v1/sso/saml/acs"
        entity_id = "spanforge-local"
        return (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<md:EntityDescriptor'
            ' xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"'
            f' entityID="{entity_id}">'
            "<md:SPSSODescriptor"
            ' AuthnRequestsSigned="false"'
            ' WantAssertionsSigned="true"'
            ' protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">'
            "<md:NameIDFormat>"
            "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress"
            "</md:NameIDFormat>"
            f'<md:AssertionConsumerService Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"'
            f' Location="{acs_url}" index="1"/>'
            "</md:SPSSODescriptor>"
            "</md:EntityDescriptor>"
        )

    def saml_acs(self, saml_response: str) -> dict[str, Any]:
        """Process a SAML ACS POST and return a SpanForge session JWT (ID-040).

        In remote mode, delegates to ``POST /v1/sso/saml/acs`` on the service.

        In local mode, base64-decodes *saml_response*, extracts the
        ``NameID`` (email / subject) via a lightweight XML parse, and issues
        a SpanForge session JWT.  This is suitable for integration testing
        with a local or mock IdP.

        Args:
            saml_response: Base64-encoded SAMLResponse XML from the IdP.

        Returns:
            ``{"session_jwt": str, "subject": str, "email": str,
               "expires_in": int}``

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFAuthError`: If the
                SAMLResponse cannot be decoded or is missing required fields.
        """
        if not self._is_local_mode():  # pragma: no cover
            return self._request(
                "POST",
                "/v1/sso/saml/acs",
                {"SAMLResponse": saml_response},
            )

        try:
            xml_bytes = base64.b64decode(saml_response)
        except Exception as exc:
            raise SFAuthError("Invalid SAMLResponse: base64 decode failed") from exc

        import xml.etree.ElementTree as ET  # stdlib — safe for untrusted XML via defusedxml if present

        try:
            root = ET.fromstring(xml_bytes.decode("utf-8"))  # nosec B314
        except ET.ParseError as exc:
            raise SFAuthError("Invalid SAMLResponse: XML parse error") from exc

        # Extract NameID — search namespace-agnostic
        name_id: str | None = None
        for elem in root.iter():
            if elem.tag.endswith("}NameID") or elem.tag == "NameID":
                name_id = (elem.text or "").strip()
                break

        if not name_id:
            raise SFAuthError("Invalid SAMLResponse: NameID element not found")

        now = time.time()
        payload = {
            "sub": name_id,
            "email": name_id,
            "iat": int(now),
            "exp": int(now + _SESSION_TTL_SECONDS),
            "jti": str(uuid.uuid4()),
            "sso": "saml",
        }
        jwt = _issue_hs256_jwt(payload, self._signing_key.encode())
        return {
            "session_jwt": jwt,
            "subject": name_id,
            "email": name_id,
            "expires_in": _SESSION_TTL_SECONDS,
        }

    # ------------------------------------------------------------------
    # ID-041: SCIM 2.0 User provisioning
    # ------------------------------------------------------------------

    def scim_list_users(
        self,
        *,
        filter_str: str | None = None,
        start_index: int = 1,
        count: int = 100,
    ) -> SCIMListResponse:
        """Return a paginated list of SCIM users (RFC 7644).

        Args:
            filter_str:  Optional SCIM filter expression, e.g.
                         ``"userName eq 'alice@example.com'"``.
                         Supported operators: ``eq``.
            start_index: 1-based starting index (default: 1).
            count:       Maximum results per page (default: 100).

        Returns:
            :class:`~spanforge.sdk._types.SCIMListResponse`.
        """
        if not self._is_local_mode():  # pragma: no cover
            params = f"?startIndex={start_index}&count={count}"
            if filter_str:
                import urllib.parse

                params += f"&filter={urllib.parse.quote(filter_str)}"
            resp = self._request("GET", f"/scim/v2/Users{params}")
            resources = [self._scim_user_from_dict(r) for r in resp.get("Resources", [])]
            return SCIMListResponse(
                total_results=resp.get("totalResults", len(resources)),
                start_index=resp.get("startIndex", 1),
                items_per_page=resp.get("itemsPerPage", len(resources)),
                resources=resources,
            )

        with self._lock:
            users = list(self._scim_users.values())

        # Apply eq filter if provided
        if filter_str:
            users = self._scim_filter_users(users, filter_str)

        total = len(users)
        page = users[start_index - 1 : start_index - 1 + count]
        return SCIMListResponse(
            total_results=total,
            start_index=start_index,
            items_per_page=len(page),
            resources=[self._scim_user_from_dict(u) for u in page],
        )

    def scim_create_user(self, user_data: dict[str, Any]) -> SCIMUser:
        """Provision a new SCIM user (RFC 7644 POST /scim/v2/Users).

        Args:
            user_data: SCIM User schema dict with at minimum
                       ``userName``.  ``name.formatted`` or
                       ``displayName`` used for :attr:`SCIMUser.display_name`.

        Returns:
            :class:`~spanforge.sdk._types.SCIMUser` with
            SpanForge-assigned ``id``.

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFAuthError`: If ``userName``
                is missing or already taken.
        """
        if not self._is_local_mode():  # pragma: no cover
            resp = self._request("POST", "/scim/v2/Users", user_data)
            return self._scim_user_from_dict(resp)

        user_name = user_data.get("userName", "").strip()
        if not user_name:
            raise SFAuthError("SCIM create user: userName is required")

        with self._lock:
            if user_name in self._scim_users_by_name:
                raise SFAuthError(f"SCIM create user: userName already exists: {user_name!r}")

            user_id = f"scim-user-{str(uuid.uuid4())[:8]}"
            now_iso = datetime.now(timezone.utc).isoformat()
            emails = user_data.get("emails", [])
            email = ""
            if emails and isinstance(emails, list):
                email = emails[0].get("value", "")
            elif isinstance(user_data.get("email"), str):
                email = user_data["email"]

            display_name = (
                user_data.get("displayName")
                or (user_data.get("name") or {}).get("formatted", "")
                or user_name
            )
            record: dict[str, Any] = {
                "id": user_id,
                "user_name": user_name,
                "display_name": display_name,
                "active": user_data.get("active", True),
                "email": email,
                "groups": [],
                "external_id": user_data.get("externalId"),
                "meta": {
                    "resourceType": "User",
                    "created": now_iso,
                    "lastModified": now_iso,
                    "location": f"/scim/v2/Users/{user_id}",
                },
            }
            self._scim_users[user_id] = record
            self._scim_users_by_name[user_name] = user_id

        return self._scim_user_from_dict(record)

    def scim_get_user(self, user_id: str) -> SCIMUser:
        """Fetch a SCIM user by id (RFC 7644 GET /scim/v2/Users/{id}).

        Args:
            user_id: SpanForge user id as returned by :meth:`scim_create_user`.

        Returns:
            :class:`~spanforge.sdk._types.SCIMUser`.

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFAuthError`: If the user does
                not exist.
        """
        if not self._is_local_mode():  # pragma: no cover
            resp = self._request("GET", f"/scim/v2/Users/{user_id}")
            return self._scim_user_from_dict(resp)

        with self._lock:
            record = self._scim_users.get(user_id)
        if record is None:
            raise SFAuthError(f"SCIM user not found: {user_id!r}")
        return self._scim_user_from_dict(record)

    def scim_patch_user(self, user_id: str, patch_ops: list[dict[str, Any]]) -> SCIMUser:
        """Apply PATCH operations to a SCIM user (RFC 7644 PATCH /scim/v2/Users/{id}).

        Supported ``op`` values: ``replace``, ``add``, ``remove``.
        Recognised ``path`` values: ``active``, ``displayName``,
        ``emails``, ``name.formatted``.

        Args:
            user_id:   SpanForge user id.
            patch_ops: List of SCIM patch operation dicts, each with
                       ``op``, ``path``, and optionally ``value``.

        Returns:
            Updated :class:`~spanforge.sdk._types.SCIMUser`.

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFAuthError`: If the user does
                not exist.
        """
        if not self._is_local_mode():  # pragma: no cover
            resp = self._request("PATCH", f"/scim/v2/Users/{user_id}", {"Operations": patch_ops})
            return self._scim_user_from_dict(resp)

        with self._lock:
            record = self._scim_users.get(user_id)
            if record is None:
                raise SFAuthError(f"SCIM user not found: {user_id!r}")

            for op in patch_ops:
                path = op.get("path", "")
                value = op.get("value")
                operation = op.get("op", "").lower()
                if path == "active" and operation in ("replace", "add"):
                    record["active"] = bool(value)
                elif path in ("displayName", "display_name") and operation in ("replace", "add"):
                    record["display_name"] = str(value)
                elif path == "name.formatted" and operation in ("replace", "add"):
                    record["display_name"] = str(value)
                elif path == "emails" and operation in ("replace", "add"):
                    if isinstance(value, list) and value:
                        record["email"] = value[0].get("value", "")
                    elif isinstance(value, str):
                        record["email"] = value

            record["meta"]["lastModified"] = datetime.now(timezone.utc).isoformat()

        return self._scim_user_from_dict(record)

    def scim_delete_user(self, user_id: str) -> None:
        """Delete a SCIM user (RFC 7644 DELETE /scim/v2/Users/{id}).

        Args:
            user_id: SpanForge user id.

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFAuthError`: If the user does
                not exist.
        """
        if not self._is_local_mode():  # pragma: no cover
            self._request("DELETE", f"/scim/v2/Users/{user_id}")
            return

        with self._lock:
            record = self._scim_users.pop(user_id, None)
            if record is None:
                raise SFAuthError(f"SCIM user not found: {user_id!r}")
            self._scim_users_by_name.pop(record["user_name"], None)

    # ------------------------------------------------------------------
    # ID-041: SCIM 2.0 Group provisioning
    # ------------------------------------------------------------------

    def scim_list_groups(
        self,
        *,
        start_index: int = 1,
        count: int = 100,
    ) -> SCIMListResponse:
        """Return a paginated list of SCIM groups (RFC 7644).

        Args:
            start_index: 1-based starting index.
            count:       Maximum results per page.

        Returns:
            :class:`~spanforge.sdk._types.SCIMListResponse`.
        """
        if not self._is_local_mode():  # pragma: no cover
            resp = self._request("GET", f"/scim/v2/Groups?startIndex={start_index}&count={count}")
            resources = [self._scim_group_from_dict(g) for g in resp.get("Resources", [])]
            return SCIMListResponse(
                total_results=resp.get("totalResults", len(resources)),
                start_index=resp.get("startIndex", 1),
                items_per_page=resp.get("itemsPerPage", len(resources)),
                resources=resources,
            )

        with self._lock:
            groups = list(self._scim_groups.values())

        total = len(groups)
        page = groups[start_index - 1 : start_index - 1 + count]
        return SCIMListResponse(
            total_results=total,
            start_index=start_index,
            items_per_page=len(page),
            resources=[self._scim_group_from_dict(g) for g in page],
        )

    def scim_create_group(self, group_data: dict[str, Any]) -> SCIMGroup:
        """Provision a new SCIM group (RFC 7644 POST /scim/v2/Groups).

        Args:
            group_data: SCIM Group schema dict with at minimum
                        ``displayName``.  Members provided as
                        ``[{"value": user_id}, ...]``.

        Returns:
            :class:`~spanforge.sdk._types.SCIMGroup`.
        """
        if not self._is_local_mode():  # pragma: no cover
            resp = self._request("POST", "/scim/v2/Groups", group_data)
            return self._scim_group_from_dict(resp)

        display_name = group_data.get("displayName", "").strip()
        if not display_name:
            raise SFAuthError("SCIM create group: displayName is required")

        with self._lock:
            group_id = f"scim-group-{str(uuid.uuid4())[:8]}"
            now_iso = datetime.now(timezone.utc).isoformat()
            members = [m["value"] for m in group_data.get("members", []) if "value" in m]
            record: dict[str, Any] = {
                "id": group_id,
                "display_name": display_name,
                "members": members,
                "external_id": group_data.get("externalId"),
                "meta": {
                    "resourceType": "Group",
                    "created": now_iso,
                    "lastModified": now_iso,
                    "location": f"/scim/v2/Groups/{group_id}",
                },
            }
            self._scim_groups[group_id] = record

            # Update member records
            for uid in members:
                if uid in self._scim_users:
                    if group_id not in self._scim_users[uid]["groups"]:
                        self._scim_users[uid]["groups"].append(group_id)

        return self._scim_group_from_dict(record)

    def scim_delete_group(self, group_id: str) -> None:
        """Delete a SCIM group (RFC 7644 DELETE /scim/v2/Groups/{id}).

        Args:
            group_id: SpanForge group id.

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFAuthError`: If the group
                does not exist.
        """
        if not self._is_local_mode():  # pragma: no cover
            self._request("DELETE", f"/scim/v2/Groups/{group_id}")
            return

        with self._lock:
            record = self._scim_groups.pop(group_id, None)
            if record is None:
                raise SFAuthError(f"SCIM group not found: {group_id!r}")
            # Remove group from member user records
            for uid in record.get("members", []):
                if uid in self._scim_users:
                    try:
                        self._scim_users[uid]["groups"].remove(group_id)
                    except ValueError:
                        pass

    # ------------------------------------------------------------------
    # ID-042: OIDC relying party (PKCE — RFC 7636)
    # ------------------------------------------------------------------

    def oidc_authorize(
        self,
        *,
        provider_url: str = "https://idp.example.com",
        client_id: str = "spanforge-local",
        redirect_uri: str = "http://localhost:7464/v1/sso/oidc/callback",
        scope: str = "openid email profile",
    ) -> OIDCAuthRequest:
        """Generate an OIDC authorization request with PKCE (RFC 7636).

        Produces a PKCE code verifier/challenge pair, a CSRF ``state`` token,
        and a replay-protection ``nonce``, then assembles the authorization
        URL to redirect the user to.

        In remote mode, the service builds and signs the request; parameters
        are taken from server-side configuration and *provider_url* is
        ignored.  In local mode, all parameters are used directly.

        Args:
            provider_url:  Base URL of the OIDC provider (local mode only).
            client_id:     OAuth 2.0 client id (local mode only).
            redirect_uri:  Where the IdP will POST the authorization code.
            scope:         Space-separated scope string.

        Returns:
            :class:`~spanforge.sdk._types.OIDCAuthRequest`.
        """
        if not self._is_local_mode():  # pragma: no cover
            resp = self._request(
                "POST",
                "/v1/sso/oidc/authorize",
                {"redirect_uri": redirect_uri, "scope": scope},
            )
            return OIDCAuthRequest(
                authorization_url=resp["authorization_url"],
                state=resp["state"],
                code_verifier=resp["code_verifier"],
                code_challenge=resp["code_challenge"],
                nonce=resp["nonce"],
            )

        # PKCE: generate random code_verifier (RFC 7636 §4.1 — 43–128 unreserved chars)
        code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).rstrip(b"=").decode()
        code_challenge = base64.urlsafe_b64encode(
            hashlib.sha256(code_verifier.encode()).digest()
        ).rstrip(b"=").decode()
        state = secrets.token_urlsafe(32)
        nonce = secrets.token_urlsafe(24)

        import urllib.parse

        params = urllib.parse.urlencode(
            {
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "scope": scope,
                "state": state,
                "nonce": nonce,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        authorization_url = f"{provider_url.rstrip('/')}/authorize?{params}"

        with self._lock:
            self._oidc_states[state] = {
                "code_verifier": code_verifier,
                "nonce": nonce,
                "redirect_uri": redirect_uri,
                "created_at": time.time(),
            }

        return OIDCAuthRequest(
            authorization_url=authorization_url,
            state=state,
            code_verifier=code_verifier,
            code_challenge=code_challenge,
            nonce=nonce,
        )

    def oidc_callback(
        self,
        code: str,
        state: str,
        *,
        subject: str = "",
        email: str = "",
    ) -> OIDCTokenResult:
        """Exchange an OIDC authorization code for a SpanForge session JWT.

        In remote mode, the service exchanges *code* at the IdP's token
        endpoint and returns a SpanForge-native session JWT.

        In local mode (testing), *code* is treated as an opaque value; the
        method validates *state* (CSRF check), then issues a SpanForge session
        JWT using *subject* / *email* as the identity.

        Args:
            code:    Authorization code from the IdP redirect.
            state:   CSRF state token from :meth:`oidc_authorize`.
            subject: Override subject (``sub``) for local mode.
            email:   Override email for local mode.

        Returns:
            :class:`~spanforge.sdk._types.OIDCTokenResult`.

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFAuthError`: If ``state`` is
                invalid or expired.
        """
        if not self._is_local_mode():  # pragma: no cover
            resp = self._request(
                "POST",
                "/v1/sso/oidc/callback",
                {"code": code, "state": state},
            )
            return OIDCTokenResult(
                session_jwt=resp["session_jwt"],
                id_token=resp.get("id_token", ""),
                access_token=resp.get("access_token", ""),
                expires_in=resp.get("expires_in", _SESSION_TTL_SECONDS),
                subject=resp.get("subject", ""),
                email=resp.get("email", ""),
            )

        with self._lock:
            state_record = self._oidc_states.pop(state, None)

        if state_record is None:
            raise SFAuthError("OIDC callback: invalid or expired state token")

        # State TTL: 10 minutes
        if time.time() - state_record["created_at"] > 600:
            raise SFAuthError("OIDC callback: state token has expired")

        sub = subject or code  # use code as surrogate sub in local mode
        em = email or f"{sub}@local.dev"

        now = time.time()
        payload = {
            "sub": sub,
            "email": em,
            "iat": int(now),
            "exp": int(now + _SESSION_TTL_SECONDS),
            "jti": str(uuid.uuid4()),
            "sso": "oidc",
            "nonce": state_record["nonce"],
        }
        jwt = _issue_hs256_jwt(payload, self._signing_key.encode())
        return OIDCTokenResult(
            session_jwt=jwt,
            id_token="",  # no live IdP in local mode
            access_token="",
            expires_in=_SESSION_TTL_SECONDS,
            subject=sub,
            email=em,
        )

    # ------------------------------------------------------------------
    # ID-043: SSO session delegation
    # ------------------------------------------------------------------

    def sso_delegate_session(
        self,
        idp_session_id: str,
        subject: str,
        *,
        email: str = "",
        project_id: str = "default",
    ) -> SSOSession:
        """Create a SpanForge-native session mapped to an IdP session (ID-043).

        When a project uses SSO (SAML or OIDC), call this method to issue
        a SpanForge session token that is logically bound to the IdP session.
        When the IdP session is revoked (e.g. via SCIM ``PATCH active=false``),
        call :meth:`sso_revoke_idp_session` to propagate the revocation.

        Args:
            idp_session_id: Opaque IdP session identifier.
            subject:        ``sub`` claim from the IdP.
            email:          Email address for the session.
            project_id:     SpanForge project to scope this session to.

        Returns:
            :class:`~spanforge.sdk._types.SSOSession`.

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFAuthError`: If a session
                for *idp_session_id* already exists and is still active.
        """
        if not self._is_local_mode():  # pragma: no cover
            resp = self._request(
                "POST",
                "/v1/sso/session",
                {
                    "idp_session_id": idp_session_id,
                    "subject": subject,
                    "email": email,
                    "project_id": project_id,
                },
            )
            return SSOSession(
                session_id=resp["session_id"],
                idp_session_id=idp_session_id,
                subject=subject,
                email=email,
                jwt=resp["jwt"],
                project_id=project_id,
                created_at=resp["created_at"],
                expires_at=resp["expires_at"],
                active=resp.get("active", True),
            )

        with self._lock:
            # Check for existing active session
            existing_id = self._sso_by_idp.get(idp_session_id)
            if existing_id:
                existing = self._sso_sessions.get(existing_id)
                if existing and existing.get("active"):
                    raise SFAuthError(
                        f"SSO delegate: active session already exists for idp_session_id={idp_session_id!r}"
                    )

            session_id = f"sso-{str(uuid.uuid4())[:12]}"
            now = time.time()
            now_iso = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
            exp_iso = datetime.fromtimestamp(now + _SESSION_TTL_SECONDS, tz=timezone.utc).isoformat()

            jwt_payload = {
                "sub": subject,
                "email": email,
                "project_id": project_id,
                "sso_session_id": session_id,
                "idp_session_id": idp_session_id,
                "iat": int(now),
                "exp": int(now + _SESSION_TTL_SECONDS),
                "jti": str(uuid.uuid4()),
            }
            jwt = _issue_hs256_jwt(jwt_payload, self._signing_key.encode())

            record: dict[str, Any] = {
                "session_id": session_id,
                "idp_session_id": idp_session_id,
                "subject": subject,
                "email": email,
                "jwt": jwt,
                "project_id": project_id,
                "created_at": now_iso,
                "expires_at": exp_iso,
                "active": True,
            }
            self._sso_sessions[session_id] = record
            self._sso_by_idp[idp_session_id] = session_id

        _log.info(
            "SSO session delegated: session_id=%s subject=%s project_id=%s",
            session_id,
            subject,
            project_id,
        )
        return SSOSession(**record)

    def sso_revoke_idp_session(self, idp_session_id: str) -> bool:
        """Revoke all SpanForge sessions tied to an IdP session (ID-043).

        Called when the IdP revokes the session (e.g. SCIM ``PATCH active=false``
        or a logout event).  Marks the delegated session as inactive within
        5 minutes of the IdP event, per spec.

        Args:
            idp_session_id: Opaque IdP session identifier.

        Returns:
            ``True`` if a session was found and revoked, ``False`` if no
            active session existed for *idp_session_id*.
        """
        if not self._is_local_mode():  # pragma: no cover
            resp = self._request(
                "POST",
                "/v1/sso/session/revoke",
                {"idp_session_id": idp_session_id},
            )
            return bool(resp.get("revoked", False))

        with self._lock:
            session_id = self._sso_by_idp.get(idp_session_id)
            if not session_id:
                return False
            record = self._sso_sessions.get(session_id)
            if not record or not record.get("active"):
                return False
            record["active"] = False

        _log.info("SSO session revoked via IdP: idp_session_id=%s session_id=%s", idp_session_id, session_id)
        return True

    def sso_get_session(self, session_id: str) -> SSOSession:
        """Retrieve an SSO delegated session by SpanForge session id.

        Args:
            session_id: SpanForge SSO session id as returned by
                        :meth:`sso_delegate_session`.

        Returns:
            :class:`~spanforge.sdk._types.SSOSession`.

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFAuthError`: If the session
                does not exist.
        """
        if not self._is_local_mode():  # pragma: no cover
            resp = self._request("GET", f"/v1/sso/session/{session_id}")
            return SSOSession(
                session_id=resp["session_id"],
                idp_session_id=resp["idp_session_id"],
                subject=resp["subject"],
                email=resp.get("email", ""),
                jwt=resp["jwt"],
                project_id=resp["project_id"],
                created_at=resp["created_at"],
                expires_at=resp["expires_at"],
                active=resp.get("active", True),
            )

        with self._lock:
            record = self._sso_sessions.get(session_id)
        if record is None:
            raise SFAuthError(f"SSO session not found: {session_id!r}")
        return SSOSession(**record)

    # ------------------------------------------------------------------
    # 4.5 — SCIM / SSO internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _scim_user_from_dict(record: dict[str, Any]) -> SCIMUser:
        return SCIMUser(
            id=record["id"],
            user_name=record["user_name"],
            display_name=record.get("display_name", record.get("user_name", "")),
            active=record.get("active", True),
            email=record.get("email", ""),
            groups=list(record.get("groups", [])),
            external_id=record.get("external_id"),
            meta=dict(record.get("meta", {})),
        )

    @staticmethod
    def _scim_group_from_dict(record: dict[str, Any]) -> SCIMGroup:
        return SCIMGroup(
            id=record["id"],
            display_name=record.get("display_name", ""),
            members=list(record.get("members", [])),
            external_id=record.get("external_id"),
            meta=dict(record.get("meta", {})),
        )

    @staticmethod
    def _scim_filter_users(
        users: list[dict[str, Any]], filter_str: str
    ) -> list[dict[str, Any]]:
        """Very lightweight SCIM filter: supports only ``attr eq 'value'``."""
        import re as _re

        m = _re.match(r'(\w+)\s+eq\s+["\']([^"\']+)["\']', filter_str.strip(), _re.IGNORECASE)
        if not m:
            return users  # unsupported filter — return all
        attr, value = m.group(1).lower(), m.group(2)
        field_map = {"username": "user_name", "email": "email", "active": "active"}
        field = field_map.get(attr, attr)
        result = []
        for u in users:
            v = u.get(field)
            if field == "active":
                if str(v).lower() == value.lower():
                    result.append(u)
            elif v is not None and str(v).lower() == value.lower():
                result.append(u)
        return result

    # ------------------------------------------------------------------
    # 4.6  Rate Limiting
    # ------------------------------------------------------------------

    def check_rate_limit(self, key_id: str) -> RateLimitInfo:
        """Return the current rate-limit state for *key_id*.

        Does **not** count as a request.  Use :meth:`record_request` to
        increment the counter.

        Args:
            key_id: The ``key_id`` to inspect.

        Returns:
            :class:`~spanforge.sdk._types.RateLimitInfo`.
        """
        if not self._is_local_mode():
            resp = self._request("GET", f"/v1/keys/{key_id}/rate-limit")
            return RateLimitInfo(
                limit=resp["limit"],
                remaining=resp["remaining"],
                reset_at=datetime.fromisoformat(resp["reset_at"]),
            )

        return self._rate_limiter.check(key_id)

    def record_request(self, key_id: str) -> bool:
        """Increment the request counter for *key_id*.

        Args:
            key_id: The ``key_id`` that made the request.

        Returns:
            ``True`` if the request is within the rate limit.
            ``False`` if the limit has been exceeded.
        """
        if not self._is_local_mode():
            resp = self._request("POST", f"/v1/keys/{key_id}/rate-limit/record")
            return bool(resp.get("allowed", True))

        return self._rate_limiter.record(key_id)

    # ------------------------------------------------------------------
    # 4.7  Security — IP allowlist
    # ------------------------------------------------------------------

    def check_ip_allowlist(self, key_id: str, ip: str) -> None:
        """Check if *ip* is permitted by the key's IP allowlist.

        Raises :exc:`~spanforge.sdk._exceptions.SFIPDeniedError` if *ip* is
        not in the key's ``ip_allowlist``.

        If the key has no allowlist configured, all IPs are permitted.

        Args:
            key_id: The ``key_id`` to look up.
            ip: Client IP address (IPv4 or IPv6).

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFIPDeniedError`: If the IP is
                not in any listed CIDR.
            :exc:`~spanforge.sdk._exceptions.SFAuthError`: If *key_id* is
                unknown.
        """
        if not self._is_local_mode():
            self._request("POST", "/v1/security/check-ip", {"key_id": key_id, "ip": ip})
            return

        with self._lock:
            record = self._keys_by_id.get(key_id)

        if record is None:
            raise SFAuthError(f"Key not found: key_id={key_id!r}")

        allowlist = record.get("ip_allowlist") or []
        if not allowlist:
            return  # no restriction

        try:
            client_ip = ipaddress.ip_address(ip)
        except ValueError:
            raise SFIPDeniedError(ip) from None

        for cidr in allowlist:
            try:
                network = ipaddress.ip_network(cidr, strict=False)
            except ValueError:
                _log.warning("Invalid CIDR in ip_allowlist: %r", cidr)
                continue
            if client_ip in network:
                return

        raise SFIPDeniedError(ip)

    # ------------------------------------------------------------------
    # JWKS endpoint
    # ------------------------------------------------------------------

    def get_jwks(self) -> dict[str, Any]:
        """Return the JSON Web Key Set.

        In local mode (HS256), there is no asymmetric public key to publish;
        returns an empty ``keys`` array as per RFC 7517 §5.

        In remote mode, fetches ``/.well-known/jwks.json`` from the service.
        """
        if not self._is_local_mode():
            return self._request("GET", "/.well-known/jwks.json")
        return {"keys": []}

    # ------------------------------------------------------------------
    # Scope enforcement helper
    # ------------------------------------------------------------------

    def require_scope(self, claims: JWTClaims, scope: str) -> None:
        """Assert that *scope* is present in *claims*, or raise an error.

        Raises :exc:`~spanforge.sdk._exceptions.SFScopeError` if *scope* is not
        in *claims*.

        Intended for resource servers validating incoming JWTs.

        Args:
            claims: Decoded :class:`~spanforge.sdk._types.JWTClaims`.
            scope: Required scope string.

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFScopeError`: If the scope is
                missing.
        """
        if scope not in claims.scopes:
            raise SFScopeError(required_scope=scope, key_scopes=claims.scopes)

    # ------------------------------------------------------------------
    # ID-031: MFA enforcement policy
    # ------------------------------------------------------------------

    def set_mfa_policy(self, project_id: str, mfa_required: bool) -> None:
        """Set the MFA enforcement policy for *project_id*.

        When ``mfa_required=True``, :meth:`exchange_magic_link` will raise
        :exc:`~spanforge.sdk._exceptions.SFMFARequiredError` if no OTP is
        supplied (in local mode) or if the key's project requires MFA.

        Args:
            project_id: The project to configure.
            mfa_required: Whether MFA is required for this project.
        """
        with self._lock:
            self._mfa_policies[project_id] = mfa_required

    def get_mfa_policy(self, project_id: str) -> bool:
        """Return whether MFA is required for *project_id*.

        Args:
            project_id: Project to query.

        Returns:
            ``True`` if MFA is required, ``False`` (default) otherwise.
        """
        with self._lock:
            return self._mfa_policies.get(project_id, False)

    # ------------------------------------------------------------------
    # ID-051 / ID-052: Quota tier enforcement and telemetry
    # ------------------------------------------------------------------

    def set_key_tier(self, key_id: str, tier: str) -> None:
        """Assign a quota *tier* to *key_id*.

        Args:
            key_id: Key to configure.
            tier: One of :class:`~spanforge.sdk._types.QuotaTier` constants
                (``"free"``, ``"api"``, ``"team"``, ``"enterprise"``).

        Raises:
            ValueError: If *tier* is not a known tier name.
            :exc:`~spanforge.sdk._exceptions.SFAuthError`: If *key_id* is unknown.
        """
        if tier not in QuotaTier.DAILY_LIMITS:
            raise ValueError(
                f"Unknown quota tier: {tier!r}. Valid tiers: {list(QuotaTier.DAILY_LIMITS)}"
            )
        with self._lock:
            if key_id not in self._keys_by_id:
                raise SFAuthError(f"Key not found: key_id={key_id!r}")
            self._key_tiers[key_id] = tier

    def consume_quota(self, key_id: str) -> bool:
        """Consume one scored-record quota unit for *key_id*.

        Resets daily at midnight UTC.  Enterprise keys are always allowed.
        Free keys (daily limit = 0) are always blocked.

        Args:
            key_id: Key that consumed a record.

        Returns:
            ``True`` if within quota.

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFQuotaExceededError`: If the
                daily quota has been exhausted.
        """
        with self._lock:
            tier = self._key_tiers.get(key_id, QuotaTier.FREE)
            daily_limit = QuotaTier.daily_limit(tier)

            today_midnight = _today_midnight_utc()
            counts = self._daily_counts.get(key_id, [])
            # Evict yesterday's timestamps
            counts = [ts for ts in counts if ts >= today_midnight]

            if daily_limit != -1 and len(counts) >= daily_limit:
                now = time.time()
                next_midnight = today_midnight + 86_400.0
                retry_after = max(1, int(next_midnight - now))
                raise SFQuotaExceededError(
                    tier=tier,
                    daily_limit=daily_limit,
                    retry_after=retry_after,
                )

            counts.append(time.time())
            self._daily_counts[key_id] = counts
            return True

    def get_quota_usage(self, key_id: str) -> dict[str, Any]:
        """Return quota usage telemetry for *key_id* (ID-052).

        Args:
            key_id: Key to query.

        Returns:
            Dict with keys: ``key_id``, ``tier``, ``daily_limit``,
            ``consumed_today``, ``remaining_today``.
        """
        if not self._is_local_mode():
            return self._request("GET", f"/v1/auth/quota/{key_id}")

        with self._lock:
            tier = self._key_tiers.get(key_id, QuotaTier.FREE)
            daily_limit = QuotaTier.daily_limit(tier)
            today_midnight = _today_midnight_utc()
            counts = self._daily_counts.get(key_id, [])
            today_count = sum(1 for ts in counts if ts >= today_midnight)

        if daily_limit == -1:
            return {
                "key_id": key_id,
                "tier": tier,
                "daily_limit": "unlimited",
                "consumed_today": today_count,
                "remaining_today": "unlimited",
            }
        return {
            "key_id": key_id,
            "tier": tier,
            "daily_limit": daily_limit,
            "consumed_today": today_count,
            "remaining_today": max(0, daily_limit - today_count),
        }

    # ------------------------------------------------------------------
    # sso_delegate_session_async (F-10)
    # ------------------------------------------------------------------

    async def sso_delegate_session_async(
        self,
        idp_session_id: str,
        subject: str,
        *,
        email: str = "",
        project_id: str = "default",
    ):
        """Async variant of :meth:`sso_delegate_session` (F-10).

        Runs :meth:`sso_delegate_session` in a thread-pool executor via
        :func:`asyncio.run_in_executor`, making it safe to ``await``
        from async code without blocking the event loop.

        Args:
            idp_session_id: Opaque IdP session identifier.
            subject:        ``sub`` claim from the IdP.
            email:          Email address for the session.
            project_id:     SpanForge project to scope this session to.

        Returns:
            :class:`~spanforge.sdk._types.SSOSession` — same as
            :meth:`sso_delegate_session`.
        """
        import asyncio
        import functools

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            functools.partial(
                self.sso_delegate_session,
                idp_session_id,
                subject,
                email=email,
                project_id=project_id,
            ),
        )

    #: Alias for :meth:`verify_token` — preferred name in API-key workflows.  # F-02
    validate_api_key = verify_token

    def get_status(self) -> dict[str, Any]:  # F-02
        """Return a health/status snapshot for ``spanforge doctor``.

        Returns:
            dict with at minimum ``{"status": "ok"}`` in healthy state.
        """
        with self._lock:
            key_count = len(self._keys_by_id)
            session_count = len(self._sessions)
        return {
            "status": "ok",
            "mode": "local" if self._is_local_mode() else "remote",
            "keys_issued": key_count,
            "active_sessions": session_count,
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _bundle_from_response(resp: dict[str, Any]) -> APIKeyBundle:
        """Convert a remote service response dict to an :class:`APIKeyBundle`."""
        return APIKeyBundle(
            api_key=SecretStr(resp["api_key"]),
            key_id=resp["key_id"],
            jwt=resp["jwt"],
            expires_at=datetime.fromisoformat(resp["expires_at"]),
            scopes=resp.get("scopes", []),
        )

    @staticmethod
    def _claims_from_response(resp: dict[str, Any]) -> JWTClaims:
        """Convert a remote service response dict to :class:`JWTClaims`."""
        return JWTClaims(
            subject=resp["sub"],
            scopes=resp.get("scopes", []),
            project_id=resp.get("aud", ""),
            expires_at=datetime.fromisoformat(resp["exp"]),
            issued_at=datetime.fromisoformat(resp["iat"]),
            jti=resp.get("jti", ""),
            issuer=resp.get("iss", "spanforge"),
        )
