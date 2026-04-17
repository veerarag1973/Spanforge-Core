"""spanforge.sdk._types — Value objects for the SpanForge service SDK.

All types here are immutable or clearly documented as mutable where needed.

Security requirements
---------------------
*  :class:`SecretStr` **never** exposes its value via ``__repr__``,
   ``__str__``, or Python's pickle protocol.
*  :class:`APIKeyBundle` redacts its ``api_key`` field in ``__repr__``.
*  Equality on :class:`SecretStr` uses :func:`hmac.compare_digest` to
   resist timing-based side-channel attacks.
"""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import ClassVar

__all__ = [
    "APIKeyBundle",
    "JWTClaims",
    "KeyFormat",
    "KeyScope",
    "MagicLinkResult",
    "QuotaTier",
    "RateLimitInfo",
    "SecretStr",
    "TOTPEnrollResult",
    "TokenIntrospectionResult",
]

# ---------------------------------------------------------------------------
# API key format constant
# ---------------------------------------------------------------------------

#: Regex for valid SpanForge API keys: ``sf_(live|test)_<48 base62 chars>``
_KEY_PATTERN: re.Pattern[str] = re.compile(
    r"^sf_(?:live|test)_[0-9A-Za-z]{48}$"
)

# ---------------------------------------------------------------------------
# SecretStr — a string that hides its value
# ---------------------------------------------------------------------------


class SecretStr:
    """A string whose value is never exposed by ``__repr__`` or ``__str__``.

    Use :meth:`get_secret_value` to retrieve the underlying string for
    cryptographic operations.  All other operations (repr, str, pickle)
    deliberately conceal the value to prevent accidental leakage into logs,
    error messages, or serialised state.

    Equality comparisons use :func:`hmac.compare_digest` to resist
    timing-based side-channel attacks.

    Example::

        key = SecretStr("sf_live_abc...")
        print(key)               # <SecretStr:***>
        print(repr(key))         # <SecretStr:***>
        print(key.get_secret_value())  # sf_live_abc...
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        object.__setattr__(self, "_value", value)

    # ------------------------------------------------------------------
    # Prevent accidental exposure
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return "<SecretStr:***>"

    def __str__(self) -> str:
        return "<SecretStr:***>"

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("SecretStr is immutable")

    def __reduce__(self) -> None:  # type: ignore[override]
        """Prevent pickling to avoid secret leakage via serialised objects."""
        raise TypeError(
            "SecretStr cannot be pickled. "
            "Extract the secret value with get_secret_value() before serialising."
        )

    # ------------------------------------------------------------------
    # Timing-safe equality
    # ------------------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SecretStr):
            a = object.__getattribute__(self, "_value")
            b = object.__getattribute__(other, "_value")
            return hmac.compare_digest(a, b)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(object.__getattribute__(self, "_value"))

    # ------------------------------------------------------------------
    # Intentional access
    # ------------------------------------------------------------------

    def get_secret_value(self) -> str:
        """Return the underlying secret string.

        Call this explicitly and only where the raw value is needed (e.g.
        to set an HTTP header or perform a cryptographic operation).  Do not
        pass the result to logging calls.
        """
        return str(object.__getattribute__(self, "_value"))

    def __len__(self) -> int:
        """Return length without exposing value — safe for format checks."""
        return len(object.__getattribute__(self, "_value"))


# ---------------------------------------------------------------------------
# KeyFormat — API key validation helpers
# ---------------------------------------------------------------------------


class KeyFormat:
    """Validate and inspect SpanForge API key format.

    Valid format: ``sf_live_<48 base62 chars>`` or ``sf_test_<48 base62 chars>``.

    Example::

        KeyFormat.validate("sf_live_" + "A" * 48)   # OK
        KeyFormat.validate("bad-key")                 # raises SFKeyFormatError
    """

    PATTERN: re.Pattern[str] = _KEY_PATTERN

    @classmethod
    def validate(cls, key: str) -> None:
        """Raise :exc:`~spanforge.sdk._exceptions.SFKeyFormatError` if invalid."""
        from spanforge.sdk._exceptions import SFKeyFormatError  # noqa: PLC0415

        if not isinstance(key, str) or not cls.PATTERN.match(key):
            raise SFKeyFormatError(
                f"Key must match sf_(live|test)_<48 base62 chars>. "
                f"Received length={len(key) if isinstance(key, str) else 'non-string'}."
            )

    @classmethod
    def is_test_key(cls, key: str) -> bool:
        """Return ``True`` if *key* is a test-mode key."""
        return isinstance(key, str) and key.startswith("sf_test_")

    @classmethod
    def is_live_key(cls, key: str) -> bool:
        """Return ``True`` if *key* is a live-mode key."""
        return isinstance(key, str) and key.startswith("sf_live_")

    @classmethod
    def is_valid(cls, key: str) -> bool:
        """Return ``True`` without raising if *key* matches the format."""
        return isinstance(key, str) and bool(cls.PATTERN.match(key))


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass
class KeyScope:
    """Scoping constraints attached to an API key.

    All fields default to *empty / unrestricted*.  Non-empty lists restrict
    access to the listed values only.

    Attributes:
        pillar_whitelist: SpanForge service names the key may call (e.g.
            ``["sf_pii", "sf_audit"]``).  Empty = unrestricted.
        project_scope: Project IDs the key may act on.  Empty = unrestricted.
        ip_allowlist: CIDR strings (e.g. ``["192.168.1.0/24", "10.0.0.1/32"]``).
            Empty = unrestricted.
        expires_at: Optional hard expiry.  ``None`` = no expiry.
    """

    pillar_whitelist: list[str] = field(default_factory=list)
    project_scope: list[str] = field(default_factory=list)
    ip_allowlist: list[str] = field(default_factory=list)
    expires_at: datetime | None = None

    def is_expired(self) -> bool:
        """Return ``True`` if the key has passed its hard expiry."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= self.expires_at

    def allows_service(self, service_name: str) -> bool:
        """Return ``True`` if this scope permits calls to *service_name*."""
        if not self.pillar_whitelist:
            return True
        return service_name in self.pillar_whitelist

    def allows_project(self, project_id: str) -> bool:
        """Return ``True`` if this scope permits acting on *project_id*."""
        if not self.project_scope:
            return True
        return project_id in self.project_scope


@dataclass
class APIKeyBundle:
    """Result of issuing or rotating a SpanForge API key.

    The ``api_key`` field is a :class:`SecretStr` and must be presented to
    the user **once** at issuance time only.  SpanForge never returns it
    again after the initial issuance response.

    Attributes:
        api_key: The raw key value (write-once; never log).
        key_id: Opaque identifier used for ``rotate_key`` / ``revoke_key``.
        jwt: RS256 (or HS256 in local mode) session JWT.
        expires_at: When the session JWT expires.
        scopes: Permission scopes granted to this key.
    """

    api_key: SecretStr
    key_id: str
    jwt: str
    expires_at: datetime
    scopes: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"APIKeyBundle("
            f"key_id={self.key_id!r}, "
            f"expires_at={self.expires_at.isoformat()!r}, "
            f"scopes={self.scopes!r}, "
            f"api_key=<redacted>)"
        )


@dataclass
class JWTClaims:
    """Decoded and validated JWT payload.

    Attributes:
        subject: The ``sub`` claim — typically the ``key_id``.
        scopes: Permission scopes extracted from the JWT.
        project_id: The ``aud`` claim.
        expires_at: Token expiry (UTC).
        issued_at: Token issuance time (UTC).
        jti: Unique JWT ID used for revocation checks.
        issuer: The ``iss`` claim.
    """

    subject: str
    scopes: list[str]
    project_id: str
    expires_at: datetime
    issued_at: datetime
    jti: str
    issuer: str = "spanforge"

    def is_expired(self) -> bool:
        """Return ``True`` if the JWT has passed its expiry."""
        return datetime.now(timezone.utc) >= self.expires_at


@dataclass
class RateLimitInfo:
    """Current rate-limit state for a key.

    Attributes:
        limit: Total requests allowed per window.
        remaining: Requests remaining in the current window.
        reset_at: When the window resets (UTC).
    """

    limit: int
    remaining: int
    reset_at: datetime


@dataclass
class TokenIntrospectionResult:
    """RFC 7662 token introspection response.

    Attributes:
        active: ``True`` if the token is currently valid.
        scope: Space-separated list of scopes.
        exp: Unix timestamp of expiry, or ``None``.
        sub: Subject claim.
        client_id: Client identifier.
    """

    active: bool
    scope: str = ""
    exp: int | None = None
    sub: str = ""
    client_id: str = ""


@dataclass
class MagicLinkResult:
    """Result of :meth:`~spanforge.sdk.identity.SFIdentityClient.issue_magic_link`.

    Attributes:
        link_id: Opaque ID used to look up the link record.
        expires_at: When the one-time link expires (15 min from issuance, UTC).
    """

    link_id: str
    expires_at: datetime


@dataclass
class TOTPEnrollResult:
    """Result of :meth:`~spanforge.sdk.identity.SFIdentityClient.enroll_totp`.

    Attributes:
        secret_base32: Base32-encoded TOTP secret.  **Display once then
            discard** — never store this in logs or database plaintext.
        qr_uri: ``otpauth://`` URI suitable for encoding as a QR code.
        backup_codes: 8 single-use, 8-character alphanumeric codes.
            Store hashed (already done server-side); present plaintext to
            user exactly once.
    """

    secret_base32: SecretStr
    qr_uri: str
    backup_codes: list[str]  # plaintext; user must save these

    def __repr__(self) -> str:
        return (
            f"TOTPEnrollResult("
            f"qr_uri={self.qr_uri!r}, "
            f"backup_codes=<{len(self.backup_codes)} codes redacted>, "
            f"secret_base32=<redacted>)"
        )


# ---------------------------------------------------------------------------
# Quota tier constants
# ---------------------------------------------------------------------------


class QuotaTier:
    """Named quota tier constants.

    Attributes:
        FREE:       Local CLI only (no network calls allowed).
        API:        $99 / month — 10 000 scored records / day.
        TEAM:       $499 / month — 100 000 scored records / day.
        ENTERPRISE: Unlimited.
    """

    FREE = "free"
    API = "api"
    TEAM = "team"
    ENTERPRISE = "enterprise"

    #: Mapping from tier name to daily quota (-1 = unlimited).
    DAILY_LIMITS: ClassVar[dict[str, int]] = {
        FREE: 0,
        API: 10_000,
        TEAM: 100_000,
        ENTERPRISE: -1,
    }

    @classmethod
    def daily_limit(cls, tier: str) -> int:
        """Return daily record limit for *tier* (``-1`` = unlimited)."""
        return cls.DAILY_LIMITS.get(tier, 0)
