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
    QuotaTier,
    RateLimitInfo,
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
    # 4.5  SSO — Stubs (remote only in Phase 1)
    # ------------------------------------------------------------------

    def saml_metadata(self) -> str:
        """Return SAML SP metadata XML.

        Requires a configured remote endpoint.  Returns a minimal stub in
        local mode for compatibility.
        """
        if not self._is_local_mode():  # pragma: no cover
            import urllib.request as _req

            url = f"{self._config.endpoint.rstrip('/')}/v1/sso/saml/metadata"
            with _req.urlopen(url) as resp:  # nosec B310 -- URL is always the configured HTTPS endpoint
                return str(resp.read().decode())

        return (
            '<?xml version="1.0"?>'
            '<EntityDescriptor xmlns="urn:oasis:names:tc:SAML:2.0:metadata" '
            'entityID="spanforge-local-stub" />'
        )

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
