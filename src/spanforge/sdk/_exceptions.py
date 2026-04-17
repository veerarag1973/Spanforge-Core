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

import hashlib

__all__ = [
    # Base
    "SFAuthError",
    "SFBruteForceLockedError",
    "SFError",
    "SFIPDeniedError",
    "SFKeyFormatError",
    "SFMFARequiredError",
    # Phase 2 — PII
    "SFPIIError",
    "SFPIINotRedactedError",
    "SFPIIPolicyError",
    "SFPIIScanError",
    "SFQuotaExceededError",
    "SFRateLimitError",
    "SFScopeError",
    "SFSecretsBlockedError",
    "SFSecretsError",
    "SFSecretsScanError",
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
            f"Locked until {unlock_at}" + (f" (resource={resource!r})" if resource else "")
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
            f"Key lacks required scope {required_scope!r}. Key has scopes: {key_scopes}."
        )


# ---------------------------------------------------------------------------
# Phase 2 — PII redaction service errors
# ---------------------------------------------------------------------------


class SFPIIError(SFError):
    """Base class for all PII redaction service errors.

    Callers can write ``except SFPIIError`` to handle any PII-related failure.
    """


class SFPIINotRedactedError(SFPIIError):
    """Unredacted PII detected in an event payload.

    Raised by :meth:`~spanforge.sdk.pii.SFPIIClient.assert_redacted` when
    :class:`~spanforge.redact.Redactable` instances or raw-string PII remain
    in an event after a :class:`~spanforge.redact.RedactionPolicy` should
    have been applied.

    Security: the error message never contains PII values.  The optional
    *context* string is SHA-256-hashed before inclusion so identifiers are
    preserved for correlation without disclosing content.

    Args:
        count:   Number of unredacted PII fields detected.
        context: Optional call-site label (hashed before inclusion).

    Attributes:
        count: Number of outstanding unredacted fields.
    """

    count: int

    def __init__(self, count: int, context: str = "") -> None:
        self.count = count
        ctx = ""
        if context:
            ctx_hash = hashlib.sha256(context.encode()).hexdigest()[:8]
            ctx = f" [context-hash:{ctx_hash}]"
        super().__init__(
            f"Found {count} unredacted PII field(s){ctx}. "
            "Apply a RedactionPolicy before serialising or exporting this event."
        )


class SFPIIScanError(SFPIIError):
    """Scan or anonymize operation failed.

    Raised when :meth:`~spanforge.sdk.pii.SFPIIClient.scan` or
    :meth:`~spanforge.sdk.pii.SFPIIClient.anonymize` encounters a structural
    error (e.g. non-dict payload, maximum nesting depth exceeded).
    """


class SFPIIPolicyError(SFPIIError):
    """Invalid PII policy configuration.

    Raised when :meth:`~spanforge.sdk.pii.SFPIIClient.make_policy` or
    :meth:`~spanforge.sdk.pii.SFPIIClient.wrap` is called with an invalid
    ``min_sensitivity`` level or a malformed replacement template.

    Args:
        detail: Human-readable description of the configuration problem.

    Attributes:
        detail: The detail message passed at construction time.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"PII policy configuration error: {detail}")


# ---------------------------------------------------------------------------
# Phase 2 — Secrets scanning service errors
# ---------------------------------------------------------------------------


class SFSecretsError(SFError):
    """Base class for all secrets scanning service errors.

    Callers can write ``except SFSecretsError`` to handle any secrets-related
    failure.
    """


class SFSecretsBlockedError(SFSecretsError):
    """One or more secrets were detected and the auto-block policy fired.

    Raised when the caller's policy requires that processing be halted after
    a high-confidence or zero-tolerance secret is detected.

    Args:
        secret_types: List of detected secret type labels (e.g.
            ``["aws_access_key", "stripe_live_key"]``).
        count:        Number of blocking hits.

    Attributes:
        secret_types: Labels of the detected secret types.
        count:        Number of hits that triggered the block.

    Example::

        result = sf_secrets.scan(text)
        if result.auto_blocked:
            raise SFSecretsBlockedError(
                secret_types=result.secret_types,
                count=len(result.hits),
            )
    """

    def __init__(self, secret_types: list[str], count: int = 1) -> None:
        self.secret_types = secret_types
        self.count = count
        types_str = ", ".join(repr(t) for t in secret_types) if secret_types else "(unknown)"
        super().__init__(
            f"Secrets scan blocked: {count} secret(s) detected of type(s) {types_str}. "
            "Remove the secret and rotate credentials before continuing."
        )


class SFSecretsScanError(SFSecretsError):
    """Secrets scan operation failed.

    Raised when :meth:`~spanforge.sdk.secrets.SFSecretsClient.scan` or
    :meth:`~spanforge.sdk.secrets.SFSecretsClient.scan_batch` encounters a
    structural error (e.g. non-str input, invalid configuration).
    """
