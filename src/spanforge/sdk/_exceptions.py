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
    # Phase 11 — Enterprise Hardening & Supply Chain Security
    "SFAirGapError",
    # Phase 7 — Alert Routing Service
    "SFAlertError",
    "SFAlertPublishError",
    "SFAlertQueueFullError",
    "SFAlertRateLimitedError",
    # Phase 4 — Audit service
    "SFAuditAppendError",
    "SFAuditError",
    "SFAuditQueryError",
    "SFAuditSchemaError",
    # Base
    "SFAuthError",
    "SFBruteForceLockedError",
    # Phase 5 — Compliance Evidence Chain
    "SFCECBuildError",
    "SFCECError",
    "SFCECExportError",
    "SFCECVerifyError",
    # Phase 9 — Integration Config & Local Fallback
    "SFConfigError",
    "SFConfigValidationError",
    "SFDataResidencyError",
    "SFEncryptionError",
    "SFEnterpriseError",
    "SFError",
    "SFFIPSError",
    "SFIPDeniedError",
    "SFIsolationError",
    "SFKeyFormatError",
    "SFMFARequiredError",
    # Phase 6 — Observability Named SDK
    "SFObserveAnnotationError",
    "SFObserveEmitError",
    "SFObserveError",
    "SFObserveExportError",
    # Phase 3 — PII hardening
    "SFPIIBlockedError",
    "SFPIIDPDPConsentMissingError",
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
    "SFSecretsInLogsError",
    "SFSecretsScanError",
    "SFSecurityScanError",
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


# ---------------------------------------------------------------------------
# Phase 3 — PII hardening errors
# ---------------------------------------------------------------------------


class SFPIIBlockedError(SFPIIError):
    """PII was detected and the pipeline action is ``"block"``.

    Raised by
    :meth:`~spanforge.sdk.pii.SFPIIClient.apply_pipeline_action` when PII is
    detected above the confidence threshold and *action* is ``"block"``.
    Callers should return HTTP 422 with error code ``PII_DETECTED``.

    Args:
        entity_types: List of entity type labels that triggered the block.
        count:        Number of above-threshold entities detected.

    Attributes:
        entity_types: Labels of the entity types that triggered the block.
        count:        Number of blocking hits.
    """

    def __init__(self, entity_types: list[str], count: int = 1) -> None:
        self.entity_types = entity_types
        self.count = count
        types_str = ", ".join(repr(t) for t in entity_types) if entity_types else "(unknown)"
        super().__init__(
            f"PII detected ({count} entity/entities of type(s) {types_str}) — "
            "pipeline action 'block' prevents scoring. "
            "Remove PII from the input or change the pipeline pii_action to 'flag' or 'redact'."
        )


class SFPIIDPDPConsentMissingError(SFPIIError):
    """DPDP scope enforcement: consent record absent for the current purpose.

    Raised by :meth:`~spanforge.sdk.pii.SFPIIClient.scan_text` when the
    scanned text contains a DPDP-regulated entity type AND no valid consent
    record exists for the current processing purpose in sf-audit schema
    ``spanforge.consent.v1``.

    Args:
        subject_id:  Opaque subject identifier (hashed before inclusion).
        purpose:     The processing purpose that lacks consent.
        entity_type: The DPDP entity type that triggered the check.

    Attributes:
        purpose:     Processing purpose string.
        entity_type: The entity type that triggered the error.
    """

    def __init__(self, subject_id: str, purpose: str, entity_type: str) -> None:
        self.purpose = purpose
        self.entity_type = entity_type
        # Hash subject_id to avoid leaking PII in the exception message.
        sid_hash = hashlib.sha256(subject_id.encode()).hexdigest()[:12]
        super().__init__(
            f"DPDP_CONSENT_MISSING: No valid consent for purpose={purpose!r} "
            f"covering entity_type={entity_type!r} "
            f"(subject-hash:{sid_hash}). "
            "Obtain explicit consent before processing this data."
        )


# ---------------------------------------------------------------------------
# Phase 4 — Audit service errors
# ---------------------------------------------------------------------------


class SFAuditError(SFError):
    """Base class for all audit service errors.

    Callers can write ``except SFAuditError`` to handle any audit-related
    failure.
    """


class SFAuditSchemaError(SFAuditError):
    """Unknown or invalid audit schema key.

    Raised by :meth:`~spanforge.sdk.audit.SFAuditClient.append` when
    *schema_key* is not in the known registry and ``strict_schema=True``
    (the default).

    Args:
        schema_key: The schema key that was rejected.
        known_keys: The set of accepted schema keys.

    Attributes:
        schema_key: The rejected schema key.
    """

    def __init__(self, schema_key: str, known_keys: frozenset[str]) -> None:
        self.schema_key = schema_key
        keys_sample = ", ".join(sorted(known_keys)[:5])
        more = len(known_keys) - 5
        hint = f"{keys_sample}" + (f", … (+{more} more)" if more > 0 else "")
        super().__init__(
            f"Unknown audit schema key {schema_key!r}.  "
            f"Known keys include: {hint}.  "
            "Pass strict_schema=False to allow unknown keys."
        )


class SFAuditAppendError(SFAuditError):
    """An append operation to the audit store failed.

    Args:
        detail: Human-readable description of the failure.

    Attributes:
        detail: The detail message passed at construction time.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"Audit append failed: {detail}")


class SFAuditQueryError(SFAuditError):
    """An audit store query operation failed.

    Args:
        detail: Human-readable description of the failure.

    Attributes:
        detail: The detail message passed at construction time.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"Audit query failed: {detail}")


# ---------------------------------------------------------------------------
# Phase 5 — Compliance Evidence Chain errors
# ---------------------------------------------------------------------------


class SFCECError(SFError):
    """Base class for all Compliance Evidence Chain service errors.

    Callers can write ``except SFCECError`` to handle any CEC-related failure.
    """


class SFCECBuildError(SFCECError):
    """Bundle assembly failed.

    Raised by :meth:`~spanforge.sdk.cec.SFCECClient.build_bundle` when the
    ZIP assembly, HMAC signing, or evidence collection fails.

    Args:
        detail: Human-readable description of the failure.

    Attributes:
        detail: The detail message passed at construction time.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"CEC bundle build failed: {detail}")


class SFCECVerifyError(SFCECError):
    """Bundle verification failed.

    Raised by :meth:`~spanforge.sdk.cec.SFCECClient.verify_bundle` when HMAC
    verification, chain proof validation, or timestamp verification fails.

    Args:
        detail: Human-readable description of the failure.

    Attributes:
        detail: The detail message passed at construction time.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"CEC bundle verification failed: {detail}")


class SFCECExportError(SFCECError):
    """Evidence record export failed.

    Raised when audit record export or DPA generation encounters an error.

    Args:
        detail: Human-readable description of the failure.

    Attributes:
        detail: The detail message passed at construction time.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"CEC export failed: {detail}")


# ---------------------------------------------------------------------------
# Phase 6 — Observability Named SDK errors
# ---------------------------------------------------------------------------


class SFObserveError(SFError):
    """Base class for all observability service errors.

    Callers can write ``except SFObserveError`` to handle any sf-observe
    failure.
    """


class SFObserveExportError(SFObserveError):
    """Span export failed.

    Raised by :meth:`~spanforge.sdk.observe.SFObserveClient.export_spans`
    when the export operation encounters an unrecoverable error.

    Args:
        detail: Human-readable description of the failure.

    Attributes:
        detail: The detail message passed at construction time.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"Observe export failed: {detail}")


class SFObserveEmitError(SFObserveError):
    """Span emit failed.

    Raised by :meth:`~spanforge.sdk.observe.SFObserveClient.emit_span`
    when the span cannot be created or routed to the exporter.

    Args:
        detail: Human-readable description of the failure.

    Attributes:
        detail: The detail message passed at construction time.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"Observe emit failed: {detail}")


class SFObserveAnnotationError(SFObserveError):
    """Annotation operation failed.

    Raised by :meth:`~spanforge.sdk.observe.SFObserveClient.add_annotation`
    or :meth:`~spanforge.sdk.observe.SFObserveClient.get_annotations` when
    the annotation store encounters an error.

    Args:
        detail: Human-readable description of the failure.

    Attributes:
        detail: The detail message passed at construction time.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"Observe annotation error: {detail}")


# ---------------------------------------------------------------------------
# Phase 7 — Alert Routing Service errors
# ---------------------------------------------------------------------------


class SFAlertError(SFError):
    """Base class for all alert routing service errors.

    Callers can write ``except SFAlertError`` to handle any sf-alert
    failure.
    """


class SFAlertPublishError(SFAlertError):
    """Alert publish failed due to an unrecoverable sink error.

    Raised by :meth:`~spanforge.sdk.alert.SFAlertClient.publish` when all
    configured sinks have open circuit breakers.

    Args:
        topic: The topic that could not be published.
        detail: Human-readable description of the failure.
    """

    def __init__(self, topic: str, detail: str) -> None:
        self.topic = topic
        self.detail = detail
        super().__init__(f"Alert publish failed for topic {topic!r}: {detail}")


class SFAlertRateLimitedError(SFAlertError):
    """Alert publish blocked by per-project rate limit.

    Raised when a project exceeds ``max_alerts_per_minute`` (default: 60).

    Args:
        project_id: The rate-limited project.
        limit: The configured alerts-per-minute limit.
    """

    def __init__(self, project_id: str, limit: int) -> None:
        self.project_id = project_id
        self.limit = limit
        super().__init__(
            f"Alert rate limit of {limit}/min exceeded for project {project_id!r}"
        )


class SFAlertQueueFullError(SFAlertError):
    """Alert publish blocked because the dispatch queue is full.

    Raised when the in-process async queue has reached its maximum depth
    of 1 000 items and the oldest item has been dropped.

    Args:
        depth: Current queue depth at the time of the overflow.
    """

    def __init__(self, depth: int) -> None:
        self.depth = depth
        super().__init__(f"Alert dispatch queue full (depth={depth}); oldest item dropped")


# ---------------------------------------------------------------------------
# Phase 8 — CI/CD Gate Pipeline errors
# ---------------------------------------------------------------------------


class SFGateError(SFError):
    """Base class for all CI/CD Gate Pipeline service errors.

    Callers can write ``except SFGateError`` to handle any sf-gate failure.
    """


class SFGateEvaluationError(SFGateError):
    """A gate evaluate() call failed.

    Raised by :meth:`~spanforge.sdk.gate.SFGateClient.evaluate` when
    gate evaluation encounters a fatal error (e.g. invalid gate_id, executor
    crash, or artifact write failure).

    Args:
        detail: Human-readable description of the failure.

    Attributes:
        detail: The detail message passed at construction time.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"Gate evaluation failed: {detail}")


class SFGatePipelineError(SFGateError):
    """A gate pipeline run failed with one or more blocking gate failures.

    Raised by :class:`~spanforge.gate.GateRunner` when the pipeline exits
    with a non-zero exit code.

    Args:
        failed_gates: List of gate IDs that produced FAIL verdicts.
        detail:       Optional additional context.

    Attributes:
        failed_gates: Gate identifiers of the blocking failures.
    """

    def __init__(self, failed_gates: list[str], detail: str = "") -> None:
        self.failed_gates = failed_gates
        super().__init__(
            f"Gate pipeline failed — blocking gates: {failed_gates}"
            + (f". {detail}" if detail else "")
        )


class SFGateTrustFailedError(SFGateError):
    """Trust gate checks failed (GAT-021).

    Raised when the trust gate fails AND the caller requests strict mode.
    The standard behaviour is to return a
    :class:`~spanforge.sdk._types.TrustGateResult` with ``pass_=False``
    rather than raising this exception.

    Args:
        failures: List of human-readable failure reasons.

    Attributes:
        failures: The failure reasons passed at construction time.
    """

    def __init__(self, failures: list[str]) -> None:
        self.failures = failures
        super().__init__(
            "Trust gate failed: " + "; ".join(failures)
        )


class SFGateSchemaError(SFGateError):
    """Gate YAML configuration is invalid or contains an unknown gate type.

    Raised by :class:`~spanforge.gate.GateRunner` when the YAML config file
    is malformed, missing required fields, or references an unknown gate type.

    Args:
        detail: Human-readable description of the schema violation.

    Attributes:
        detail: The detail message passed at construction time.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"Gate YAML schema error: {detail}")


# ---------------------------------------------------------------------------
# Phase 9 — Integration Config & Local Fallback errors
# ---------------------------------------------------------------------------


class SFConfigError(SFError):
    """Configuration error — invalid, missing, or unparseable config file.

    Raised by :func:`~spanforge.sdk.config.load_config_file` when the
    ``.halluccheck.toml`` file cannot be read or parsed.

    Args:
        detail: Human-readable description of the problem.

    Attributes:
        detail: The detail message passed at construction time.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"SpanForge config error: {detail}")


class SFConfigValidationError(SFConfigError):
    """One or more config schema validation errors were found (CFG-007).

    Raised by :func:`~spanforge.sdk.config.validate_config_strict` when any
    field in the ``.halluccheck.toml`` fails schema validation.

    Args:
        errors: List of human-readable error descriptions.

    Attributes:
        errors: The list of validation errors.

    Example::

        errors = validate_config(block)
        if errors:
            raise SFConfigValidationError(errors)
    """

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        bullet_list = "\n".join(f"  - {e}" for e in errors)
        super().__init__(f"Config validation failed ({len(errors)} error(s)):\n{bullet_list}")


# ---------------------------------------------------------------------------
# Phase 10 — T.R.U.S.T. Scorecard & HallucCheck Contract errors
# ---------------------------------------------------------------------------


class SFTrustError(SFError):
    """Base class for all T.R.U.S.T. scorecard errors.

    Callers can write ``except SFTrustError`` to handle any T.R.U.S.T.
    scoring failure.
    """


class SFTrustComputeError(SFTrustError):
    """T.R.U.S.T. scorecard computation failed.

    Raised when dimension score calculation fails due to insufficient data
    or an internal error.

    Args:
        detail: Human-readable description of the failure.

    Attributes:
        detail: The detail message passed at construction time.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"Trust scorecard compute failed: {detail}")


class SFTrustGateFailedError(SFTrustError):
    """Composite trust gate evaluation failed (TRS-020).

    Raised when the composite trust gate fails in strict mode.

    Args:
        failures: List of human-readable failure reasons.

    Attributes:
        failures: The failure reasons.
    """

    def __init__(self, failures: list[str]) -> None:
        self.failures = failures
        super().__init__("Composite trust gate failed: " + "; ".join(failures))


class SFPipelineError(SFTrustError):
    """A pipeline integration call failed (TRS-010 through TRS-014).

    Args:
        pipeline: Pipeline name that failed.
        detail:   Human-readable description.

    Attributes:
        pipeline: The pipeline name.
        detail:   The detail message.
    """

    def __init__(self, pipeline: str, detail: str) -> None:
        self.pipeline = pipeline
        self.detail = detail
        super().__init__(f"Pipeline {pipeline!r} failed: {detail}")


# ---------------------------------------------------------------------------
# Phase 11 — Enterprise Hardening & Supply Chain Security errors
# ---------------------------------------------------------------------------


class SFEnterpriseError(SFError):
    """Base class for all enterprise hardening errors.

    Callers can write ``except SFEnterpriseError`` to handle any enterprise
    or supply-chain security failure.
    """


class SFIsolationError(SFEnterpriseError):
    """Cross-project data isolation violation (ENT-001 / ENT-002).

    Raised when a query attempts to access data outside its project scope
    without the ``cross_project_read`` permission.

    Args:
        project_id: The project that was accessed.
        detail:     Human-readable description.

    Attributes:
        project_id: The project referenced.
        detail:     The detail message.
    """

    def __init__(self, project_id: str, detail: str) -> None:
        self.project_id = project_id
        self.detail = detail
        super().__init__(
            f"Isolation violation for project {project_id!r}: {detail}"
        )


class SFDataResidencyError(SFEnterpriseError):
    """Data residency constraint violation (ENT-004 / ENT-005).

    Raised when an operation would route data outside the configured
    residency region.

    Args:
        region:     Required residency region.
        attempted:  The region the data would have been routed to.

    Attributes:
        region:     Required residency region.
        attempted:  The attempted target region.
    """

    def __init__(self, region: str, attempted: str) -> None:
        self.region = region
        self.attempted = attempted
        super().__init__(
            f"Data residency violation: project requires {region!r} "
            f"but data would route to {attempted!r}"
        )


class SFEncryptionError(SFEnterpriseError):
    """Encryption or KMS operation failed (ENT-010 through ENT-013).

    Args:
        detail: Human-readable description of the failure.

    Attributes:
        detail: The detail message.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"Encryption error: {detail}")


class SFFIPSError(SFEnterpriseError):
    """FIPS 140-2 mode violation (ENT-013).

    Raised at startup or during operation when a non-FIPS-approved algorithm
    or cipher is detected.

    Args:
        detail: Description of the violation.

    Attributes:
        detail: The detail message.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"FIPS 140-2 violation: {detail}")


class SFAirGapError(SFEnterpriseError):
    """Air-gap or offline mode error (ENT-020 / ENT-021).

    Raised when a network operation is attempted in offline mode.

    Args:
        detail: Human-readable description.

    Attributes:
        detail: The detail message.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"Air-gap mode error: {detail}")


class SFSecurityScanError(SFEnterpriseError):
    """Security scan (vulnerability or static analysis) failed (ENT-033 / ENT-034).

    Args:
        detail: Human-readable description of the failure.

    Attributes:
        detail: The detail message.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"Security scan error: {detail}")


class SFSecretsInLogsError(SFEnterpriseError):
    """Secrets detected in log output (ENT-035).

    Raised when the automated secrets-in-logs audit detects API keys,
    JWTs, or HMAC secrets in logged WARNING/ERROR lines.

    Args:
        count: Number of secrets detected.

    Attributes:
        count: Number of secrets found.
    """

    def __init__(self, count: int) -> None:
        self.count = count
        super().__init__(
            f"Secrets detected in log output: {count} secret(s) found. "
            "Remediate before merge."
        )

