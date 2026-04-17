"""spanforge.sdk._exceptions — Error hierarchy for the SpanForge service SDK.

All SDK errors inherit from :class:`SFError`.  Callers can catch the whole
family with ``except SFError`` or target specific subtypes for fine-grained
handling.

Security requirements
---------------------
*  Error messages **never** include API key values, HMAC secrets, JWT private
   keys, TOTP secrets, or raw PII.
*  IP addresses in :class:`SFIPDeniedError` are reported as-is (they are not
   secret) to aid diagnosability without leaking private material.
"""

from __future__ import annotations

__all__ = [
    "SFAuthError",
    "SFBruteForceLockedError",
    "SFError",
    "SFIPDeniedError",
    "SFKeyFormatError",
    "SFMFARequiredError",
    "SFQuotaExceededError",
    "SFRateLimitError",
    "SFScopeError",
    "SFServiceUnavailableError",
    "SFStartupError",
    "SFTokenInvalidError",
]


class SFError(Exception):
    """Base class for all SpanForge SDK errors.

    All public-facing SDK exceptions derive from this class, enabling callers
    to write a single broad ``except SFError`` guard as a safety net while
    still being able to catch specific sub-types for targeted handling.
    """


# ---------------------------------------------------------------------------
# Authentication errors
# ---------------------------------------------------------------------------


class SFAuthError(SFError):
    """Authentication failed.

    Raised when credentials are missing, malformed, or rejected by the
    sf-identity service.
    """


class SFKeyFormatError(SFAuthError):
    """API key does not match the ``sf_(live|test)_<48-base62>`` format.

    Args:
        detail: Human-readable description of the format violation.

    Example::

        try:
            KeyFormat.validate("not-a-key")
        except SFKeyFormatError as exc:
            print(exc.detail)   # "Key must match sf_(live|test)_<48 base62 chars>; ..."
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"API key format error: {detail}")


class SFTokenInvalidError(SFAuthError):
    """JWT validation failed (expired, bad signature, or revoked).

    Args:
        reason: Short description of why validation failed.  Must not contain
            secret material.

    Example::

        try:
            claims = identity.verify_token(jwt)
        except SFTokenInvalidError as exc:
            print(exc.reason)   # "JWT has expired"
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Token invalid: {reason}")


class SFIPDeniedError(SFAuthError):
    """Request IP address is not in the key's ``ip_allowlist``.

    Args:
        ip: The IP address that was denied.

    Example::

        try:
            identity.check_ip_allowlist("key_abc123", "10.0.0.5")
        except SFIPDeniedError as exc:
            print(exc.ip)   # "10.0.0.5"
    """

    def __init__(self, ip: str) -> None:
        self.ip = ip
        super().__init__(f"IP address {ip!r} is not in the key's allowlist")


class SFMFARequiredError(SFAuthError):
    """MFA factor must be provided before a session token can be issued.

    Args:
        challenge_id: Opaque identifier the caller must return when
            submitting the OTP.

    Example::

        try:
            bundle = identity.exchange_magic_link(token)
        except SFMFARequiredError as exc:
            otp = input("Enter your TOTP code: ")
            bundle = identity.exchange_magic_link(token, mfa_challenge=exc.challenge_id, otp=otp)
    """

    def __init__(self, challenge_id: str) -> None:
        self.challenge_id = challenge_id
        super().__init__(
            f"MFA is required; challenge_id={challenge_id!r}. "
            "Submit TOTP code via exchange_magic_link(mfa_challenge=..., otp=...)."
        )


class SFBruteForceLockedError(SFAuthError):
    """Account is temporarily locked due to repeated authentication failures.

    Args:
        unlock_at: ISO-8601 timestamp when the lockout expires.
        resource: What was locked — e.g. ``"magic_link:user@example.com"``
            or ``"totp:key_abc"``.
    """

    def __init__(self, unlock_at: str, resource: str = "") -> None:
        self.unlock_at = unlock_at
        self.resource = resource
        super().__init__(
            f"Locked until {unlock_at}"
            + (f" (resource={resource!r})" if resource else "")
        )


# ---------------------------------------------------------------------------
# Service availability errors
# ---------------------------------------------------------------------------


class SFServiceUnavailableError(SFError):
    """Service is unreachable and ``local_fallback`` is disabled.

    Args:
        service: Short name of the unavailable service (e.g. ``"identity"``).
    """

    def __init__(self, service: str) -> None:
        self.service = service
        super().__init__(
            f"sf-{service} is unavailable and local_fallback is disabled. "
            "Set local_fallback_enabled=True or restore service connectivity."
        )


class SFStartupError(SFError):
    """A required service was unreachable at startup and fallback is disabled.

    Args:
        services: List of service names that failed their startup health check.
    """

    def __init__(self, services: list[str]) -> None:
        self.services = services
        super().__init__(
            f"Required services unreachable at startup: {services}. "
            "Set local_fallback_enabled=True or restore connectivity before starting."
        )


# ---------------------------------------------------------------------------
# Quota and scope errors
# ---------------------------------------------------------------------------


class SFRateLimitError(SFError):
    """Rate limit or daily quota exceeded.

    Args:
        retry_after: Seconds to wait before retrying (from ``Retry-After``
            response header or estimated reset window).
    """

    def __init__(self, retry_after: int = 60) -> None:
        self.retry_after = retry_after
        super().__init__(
            f"Rate limit exceeded. Retry after {retry_after} second(s). "
            "See X-SF-RateLimit-Reset header for precise reset time."
        )


class SFQuotaExceededError(SFRateLimitError):
    """Daily scored-record quota for the current tier has been exhausted.

    Args:
        tier: Pricing tier name (e.g. ``"api"``).
        daily_limit: Maximum records allowed per day on this tier.
        retry_after: Seconds until quota resets (midnight UTC).
    """

    def __init__(self, tier: str, daily_limit: int, retry_after: int) -> None:
        self.tier = tier
        self.daily_limit = daily_limit
        super().__init__(retry_after=retry_after)
        self.args = (
            f"Daily quota of {daily_limit} records exceeded for tier '{tier}'. "
            f"Quota resets in {retry_after}s (midnight UTC). "
            "Upgrade to a higher tier for more capacity.",
        )


class SFScopeError(SFAuthError):
    """The API key does not have the required scope for this operation.

    Args:
        required_scope: The scope that was needed.
        key_scopes: The scopes the key actually has.
    """

    def __init__(self, required_scope: str, key_scopes: list[str]) -> None:
        self.required_scope = required_scope
        self.key_scopes = key_scopes
        super().__init__(
            f"Key lacks required scope {required_scope!r}. "
            f"Key has scopes: {key_scopes}."
        )
