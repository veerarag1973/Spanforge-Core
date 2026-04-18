"""spanforge.sdk — SpanForge service SDK.

Provides pre-built client singletons for all SpanForge platform services.
Phase 1 implements :data:`sf_identity` (key lifecycle, JWT, TOTP, MFA).
Phase 2 implements :data:`sf_pii` (scan, redact, anonymize).
Phase 3 adds sf-secrets scanning.
Phase 4 implements :data:`sf_audit` (append, sign, verify_chain, export,
    T.R.U.S.T. scorecard, GDPR Article 30 record generation).
All other singletons are stubs completed in subsequent phases.

Quick start::

    from spanforge.sdk import sf_identity, sf_pii, sf_audit

    bundle = sf_identity.issue_api_key(scopes=["sf_audit"])
    token  = sf_identity.create_session(bundle.api_key.get_secret_value())
    claims = sf_identity.verify_token(token)

    result = sf_pii.scan({"message": "Call 555-867-5309"})
    if not result.clean:
        anon = sf_pii.anonymize("My SSN is 123-45-6789")

    audit_result = sf_audit.append(
        {"model": "gpt-4o", "verdict": "PASS", "score": 0.91},
        schema_key="halluccheck.score.v1",
    )
    print(audit_result.record_id)

Configuration is loaded automatically from environment variables.
See :class:`~spanforge.sdk._base.SFClientConfig` for the full list.

Singletons
----------
Each singleton is created lazily on first import using
:func:`~spanforge.sdk._base.SFClientConfig.from_env`.  Call
:func:`configure` to replace with a custom configuration before first use.
"""

from __future__ import annotations

from spanforge.sdk._base import SFClientConfig
from spanforge.sdk._exceptions import (
    # Phase 11 — Enterprise Hardening & Supply Chain Security
    SFAirGapError,
    SFAlertError,
    SFAlertPublishError,
    SFAlertQueueFullError,
    SFAlertRateLimitedError,
    SFAuditAppendError,
    SFAuditError,
    SFAuditQueryError,
    SFAuditSchemaError,
    SFAuthError,
    SFBruteForceLockedError,
    SFCECBuildError,
    SFCECError,
    SFCECExportError,
    SFCECVerifyError,
    SFConfigError,
    SFConfigValidationError,
    SFDataResidencyError,
    SFEncryptionError,
    SFEnterpriseError,
    SFError,
    SFFIPSError,
    SFGateError,
    SFGateEvaluationError,
    SFGatePipelineError,
    SFGateSchemaError,
    SFGateTrustFailedError,
    SFIPDeniedError,
    SFIsolationError,
    SFKeyFormatError,
    SFMFARequiredError,
    SFObserveAnnotationError,
    SFObserveEmitError,
    SFObserveError,
    SFObserveExportError,
    SFPIIBlockedError,
    SFPIIDPDPConsentMissingError,
    SFPIIError,
    SFPIINotRedactedError,
    SFPIIPolicyError,
    SFPIIScanError,
    SFPipelineError,
    SFQuotaExceededError,
    SFRateLimitError,
    SFScopeError,
    SFSecretsBlockedError,
    SFSecretsError,
    SFSecretsInLogsError,
    SFSecretsScanError,
    SFSecurityScanError,
    SFServiceUnavailableError,
    SFStartupError,
    SFTokenInvalidError,
    SFTrustComputeError,
    SFTrustError,
    SFTrustGateFailedError,
)
from spanforge.sdk._types import (
    # Phase 11 — Enterprise Hardening & Supply Chain Security
    AirGapConfig,
    AlertRecord,
    AlertSeverity,
    AlertStatusInfo,
    Annotation,
    APIKeyBundle,
    Article30Record,
    AuditAppendResult,
    AuditStatusInfo,
    BundleResult,
    BundleVerificationResult,
    CECStatusInfo,
    ClauseMapEntry,
    ClauseSatisfaction,
    CompositeGateInput,
    CompositeGateResult,
    DataResidency,
    DependencyVulnerability,
    DPADocument,
    DSARExport,
    DSARResult,
    EncryptionConfig,
    EnterpriseStatusInfo,
    ErasureReceipt,
    ExportResult,
    GateArtifact,
    GateEvaluationResult,
    GateStatusInfo,
    GateVerdict,
    HealthEndpointResult,
    IsolationScope,
    JWTClaims,
    KeyFormat,
    KeyScope,
    MagicLinkResult,
    MaintenanceWindow,
    ObserveStatusInfo,
    PIIAnonymisedResult,
    PIIEntity,
    PIIHeatMapEntry,
    PIIPipelineResult,
    PIIRedactionManifestEntry,
    PIIStatusInfo,
    PIITextScanResult,
    PipelineResult,
    PRRIResult,
    PRRIVerdict,
    PublishResult,
    QuotaTier,
    RateLimitInfo,
    ReceiverConfig,
    SafeHarborResult,
    SamplerStrategy,
    SecretStr,
    SecurityAuditResult,
    SecurityScanResult,
    SFPIIAnonymizeResult,
    SFPIIHit,
    SFPIIRedactResult,
    SFPIIScanResult,
    SignedRecord,
    StaticAnalysisFinding,
    TenantConfig,
    ThreatModelEntry,
    TokenIntrospectionResult,
    TopicRegistration,
    TOTPEnrollResult,
    TrainingDataPIIReport,
    TrustBadgeResult,
    TrustDimension,
    TrustDimensionWeights,
    TrustGateResult,
    TrustHistoryEntry,
    TrustScorecard,
    TrustScorecardResponse,
    TrustStatusInfo,
)
from spanforge.sdk.alert import SFAlertClient
from spanforge.sdk.audit import SFAuditClient
from spanforge.sdk.cec import SFCECClient
from spanforge.sdk.config import (
    SFConfigBlock,
    SFLocalFallbackConfig,
    SFPIIConfig,
    SFSecretsConfig,
    SFServiceToggles,
    load_config_file,
    validate_config,
    validate_config_strict,
)
from spanforge.sdk.enterprise import SFEnterpriseClient
from spanforge.sdk.fallback import (
    alert_fallback,
    audit_fallback,
    cec_fallback,
    gate_fallback,
    identity_fallback,
    observe_fallback,
    pii_fallback,
    secrets_fallback,
)
from spanforge.sdk.gate import SFGateClient
from spanforge.sdk.identity import SFIdentityClient
from spanforge.sdk.observe import SFObserveClient
from spanforge.sdk.pii import SFPIIClient
from spanforge.sdk.pipelines import (
    benchmark_pipeline,
    bias_pipeline,
    monitor_pipeline,
    risk_pipeline,
    score_pipeline,
)
from spanforge.sdk.registry import ServiceHealth, ServiceRegistry, ServiceStatus
from spanforge.sdk.secrets import SFSecretsClient
from spanforge.sdk.security import SFSecurityClient
from spanforge.sdk.trust import SFTrustClient
from spanforge.secrets import SecretHit, SecretsScanResult

__all__ = [
    "APIKeyBundle",
    "AirGapConfig",
    "AlertRecord",
    "AlertSeverity",
    "AlertStatusInfo",
    "Annotation",
    "Article30Record",
    "AuditAppendResult",
    "AuditStatusInfo",
    "BundleResult",
    "BundleVerificationResult",
    "CECStatusInfo",
    "ClauseMapEntry",
    "ClauseSatisfaction",
    "CompositeGateInput",
    "CompositeGateResult",
    "DPADocument",
    "DSARExport",
    "DSARResult",
    "DataResidency",
    "DependencyVulnerability",
    "EncryptionConfig",
    "EnterpriseStatusInfo",
    "ErasureReceipt",
    "ExportResult",
    # Phase 8 — CI/CD Gate Pipeline types & exceptions
    "GateArtifact",
    "GateEvaluationResult",
    "GateStatusInfo",
    "GateVerdict",
    "HealthEndpointResult",
    "IsolationScope",
    "JWTClaims",
    "KeyFormat",
    "KeyScope",
    "MagicLinkResult",
    "MaintenanceWindow",
    "ObserveStatusInfo",
    "PIIAnonymisedResult",
    "PIIEntity",
    "PIIHeatMapEntry",
    "PIIPipelineResult",
    "PIIRedactionManifestEntry",
    "PIIStatusInfo",
    "PIITextScanResult",
    "PRRIResult",
    "PRRIVerdict",
    "PipelineResult",
    "PublishResult",
    "QuotaTier",
    "RateLimitInfo",
    "ReceiverConfig",
    # Phase 11 — Enterprise Hardening & Supply Chain Security
    "SFAirGapError",
    "SFAlertClient",
    "SFAlertError",
    "SFAlertPublishError",
    "SFAlertQueueFullError",
    "SFAlertRateLimitedError",
    "SFAuditAppendError",
    "SFAuditClient",
    "SFAuditError",
    "SFAuditQueryError",
    "SFAuditSchemaError",
    "SFAuthError",
    "SFBruteForceLockedError",
    "SFCECBuildError",
    "SFCECClient",
    "SFCECError",
    "SFCECExportError",
    "SFCECVerifyError",
    "SFClientConfig",
    # Phase 9 — Integration Config & Local Fallback
    "SFConfigBlock",
    "SFConfigError",
    "SFConfigValidationError",
    "SFDataResidencyError",
    "SFEncryptionError",
    "SFEnterpriseClient",
    "SFEnterpriseError",
    "SFError",
    "SFFIPSError",
    "SFGateClient",
    "SFGateError",
    "SFGateEvaluationError",
    "SFGatePipelineError",
    "SFGateSchemaError",
    "SFGateTrustFailedError",
    "SFIPDeniedError",
    "SFIdentityClient",
    "SFIsolationError",
    "SFKeyFormatError",
    "SFLocalFallbackConfig",
    "SFMFARequiredError",
    "SFObserveAnnotationError",
    "SFObserveClient",
    "SFObserveEmitError",
    "SFObserveError",
    "SFObserveExportError",
    "SFPIIAnonymizeResult",
    "SFPIIBlockedError",
    "SFPIIClient",
    "SFPIIConfig",
    "SFPIIDPDPConsentMissingError",
    "SFPIIError",
    "SFPIIHit",
    "SFPIINotRedactedError",
    "SFPIIPolicyError",
    "SFPIIRedactResult",
    "SFPIIScanError",
    "SFPIIScanResult",
    # Phase 10 — T.R.U.S.T. Scorecard & HallucCheck Contract
    "SFPipelineError",
    "SFQuotaExceededError",
    "SFRateLimitError",
    "SFScopeError",
    "SFSecretsBlockedError",
    "SFSecretsClient",
    "SFSecretsConfig",
    "SFSecretsError",
    "SFSecretsInLogsError",
    "SFSecretsScanError",
    "SFSecurityClient",
    "SFSecurityScanError",
    "SFServiceToggles",
    "SFServiceUnavailableError",
    "SFStartupError",
    "SFTokenInvalidError",
    "SFTrustClient",
    "SFTrustComputeError",
    "SFTrustError",
    "SFTrustGateFailedError",
    "SafeHarborResult",
    "SafeHarborResult",
    "SamplerStrategy",
    "SecretHit",
    "SecretStr",
    "SecretsScanResult",
    "SecurityAuditResult",
    "SecurityScanResult",
    "ServiceHealth",
    "ServiceRegistry",
    "ServiceStatus",
    "SignedRecord",
    "StaticAnalysisFinding",
    "TOTPEnrollResult",
    "TenantConfig",
    "ThreatModelEntry",
    "TokenIntrospectionResult",
    "TopicRegistration",
    "TrainingDataPIIReport",
    "TrustBadgeResult",
    "TrustDimension",
    "TrustDimensionWeights",
    "TrustGateResult",
    "TrustHistoryEntry",
    "TrustScorecard",
    "TrustScorecardResponse",
    "TrustStatusInfo",
    "alert_fallback",
    "audit_fallback",
    "benchmark_pipeline",
    "bias_pipeline",
    "cec_fallback",
    "configure",
    "gate_fallback",
    "identity_fallback",
    "load_config_file",
    "monitor_pipeline",
    "observe_fallback",
    "pii_fallback",
    "risk_pipeline",
    "score_pipeline",
    "secrets_fallback",
    "sf_alert",
    "sf_audit",
    "sf_cec",
    "sf_enterprise",
    "sf_gate",
    "sf_identity",
    "sf_observe",
    "sf_pii",
    "sf_secrets",
    "sf_security",
    "sf_trust",
    "validate_config",
    "validate_config_strict",
]

# ---------------------------------------------------------------------------
# Singletons — created lazily from environment variables
# ---------------------------------------------------------------------------

_default_config: SFClientConfig | None = None


def _get_config() -> SFClientConfig:
    global _default_config
    if _default_config is None:
        _default_config = SFClientConfig.from_env()
    return _default_config


#: Phase 1 — fully implemented.
sf_identity: SFIdentityClient = SFIdentityClient(_get_config())

#: Phase 2 — fully implemented.
sf_pii: SFPIIClient = SFPIIClient(_get_config())

#: Phase 2 — secrets scanning, fully implemented.
sf_secrets: SFSecretsClient = SFSecretsClient(_get_config())

#: Phase 4 — audit log service, fully implemented.
sf_audit: SFAuditClient = SFAuditClient(_get_config())

# ---------------------------------------------------------------------------
# Phase 5+ stubs — replaced by full clients in subsequent phases
# ---------------------------------------------------------------------------


class _UnimplementedClient:
    """Placeholder for services not yet implemented.

    Raises :exc:`NotImplementedError` on any attribute access, guiding the
    caller to check the phase roadmap.
    """

    def __init__(self, name: str) -> None:
        object.__setattr__(self, "_name", name)

    def __getattr__(self, item: str) -> None:
        name = object.__getattribute__(self, "_name")
        msg = (
            f"sf_{name} is not yet available.  "
            f"It will be implemented in a future phase.  "
            f"See the SpanForge ROADMAP.md for the implementation schedule."
        )
        raise NotImplementedError(msg)


#: Phase 5 — Observability service (Phase 6).
sf_observe: SFObserveClient = SFObserveClient(_get_config())

#: Phase 6 — Feature gate / policy service.
sf_gate: SFGateClient = SFGateClient(_get_config())

#: Phase 5 — Compliance Evidence Chain service.
sf_cec: SFCECClient = SFCECClient(_get_config())

#: Phase 7 — Alert Routing Service, fully implemented.
sf_alert: SFAlertClient = SFAlertClient(_get_config())

#: Phase 10 — T.R.U.S.T. Scorecard service, fully implemented.
sf_trust: SFTrustClient = SFTrustClient(_get_config())

#: Phase 11 — Enterprise Hardening & Multi-Tenancy.
sf_enterprise: SFEnterpriseClient = SFEnterpriseClient(_get_config())

#: Phase 11 — Security Review & Supply Chain Scanning.
sf_security: SFSecurityClient = SFSecurityClient(_get_config())


# ---------------------------------------------------------------------------
# Configuration helper
# ---------------------------------------------------------------------------


def configure(config: SFClientConfig) -> None:
    """Replace the default configuration and recreate all singletons.

    Call this **before** any other SDK call if you need to supply a custom
    endpoint, API key, or signing key at runtime rather than via environment
    variables.

    Args:
        config: A fully populated :class:`~spanforge.sdk._base.SFClientConfig`.

    Example::

        from spanforge.sdk import configure, SFClientConfig, SecretStr

        configure(SFClientConfig(
            endpoint="https://api.spanforge.dev",
            api_key=SecretStr("sf_live_..."),
            signing_key="my-org-signing-key",
        ))
    """
    global _default_config
    global sf_identity, sf_pii, sf_secrets, sf_audit, sf_cec, sf_observe, sf_alert, sf_gate, sf_trust, sf_enterprise, sf_security
    _default_config = config
    sf_identity = SFIdentityClient(config)
    sf_pii = SFPIIClient(config)
    sf_secrets = SFSecretsClient(config)
    sf_audit = SFAuditClient(config)
    sf_cec = SFCECClient(config)
    sf_observe = SFObserveClient(config)
    sf_alert = SFAlertClient(config)
    sf_gate = SFGateClient(config)
    sf_trust = SFTrustClient(config)
    sf_enterprise = SFEnterpriseClient(config)
    sf_security = SFSecurityClient(config)
