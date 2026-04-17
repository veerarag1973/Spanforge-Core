"""spanforge.sdk — SpanForge service SDK.

Provides pre-built client singletons for all SpanForge platform services.
Phase 1 implements :data:`sf_identity` (key lifecycle, JWT, TOTP, MFA).
Phase 2 implements :data:`sf_pii` (scan, redact, anonymize).
All other singletons are stubs completed in subsequent phases.

Quick start::

    from spanforge.sdk import sf_identity, sf_pii

    bundle = sf_identity.issue_api_key(scopes=["sf_audit"])
    token  = sf_identity.create_session(bundle.api_key.get_secret_value())
    claims = sf_identity.verify_token(token)

    result = sf_pii.scan({"message": "Call 555-867-5309"})
    if not result.clean:
        anon = sf_pii.anonymize("My SSN is 123-45-6789")

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
    SFAuthError,
    SFBruteForceLockedError,
    SFError,
    SFIPDeniedError,
    SFKeyFormatError,
    SFMFARequiredError,
    SFPIIBlockedError,
    SFPIIDPDPConsentMissingError,
    SFPIIError,
    SFPIINotRedactedError,
    SFPIIPolicyError,
    SFPIIScanError,
    SFQuotaExceededError,
    SFRateLimitError,
    SFScopeError,
    SFSecretsBlockedError,
    SFSecretsError,
    SFSecretsScanError,
    SFServiceUnavailableError,
    SFStartupError,
    SFTokenInvalidError,
)
from spanforge.sdk._types import (
    APIKeyBundle,
    DSARExport,
    ErasureReceipt,
    JWTClaims,
    KeyFormat,
    KeyScope,
    MagicLinkResult,
    PIIAnonymisedResult,
    PIIEntity,
    PIIHeatMapEntry,
    PIIPipelineResult,
    PIIRedactionManifestEntry,
    PIIStatusInfo,
    PIITextScanResult,
    QuotaTier,
    RateLimitInfo,
    SafeHarborResult,
    SecretStr,
    SFPIIAnonymizeResult,
    SFPIIHit,
    SFPIIRedactResult,
    SFPIIScanResult,
    TokenIntrospectionResult,
    TOTPEnrollResult,
    TrainingDataPIIReport,
)
from spanforge.sdk.identity import SFIdentityClient
from spanforge.sdk.pii import SFPIIClient
from spanforge.sdk.secrets import SFSecretsClient
from spanforge.secrets import SecretHit, SecretsScanResult

__all__ = [
    "APIKeyBundle",
    "JWTClaims",
    "KeyFormat",
    "KeyScope",
    "DSARExport",
    "ErasureReceipt",
    "MagicLinkResult",
    "PIIAnonymisedResult",
    "PIIEntity",
    "PIIHeatMapEntry",
    "PIIPipelineResult",
    "PIIRedactionManifestEntry",
    "PIIStatusInfo",
    "PIITextScanResult",
    "QuotaTier",
    "RateLimitInfo",
    "SafeHarborResult",
    "SFAuthError",
    "SFBruteForceLockedError",
    "SFClientConfig",
    "SFError",
    "SFIPDeniedError",
    "SFIdentityClient",
    "SFKeyFormatError",
    "SFMFARequiredError",
    "SFPIIAnonymizeResult",
    "SFPIIBlockedError",
    "SFPIIClient",
    "SFPIIDPDPConsentMissingError",
    "SFPIIError",
    "SFPIIHit",
    "SFPIINotRedactedError",
    "SFPIIPolicyError",
    "SFPIIRedactResult",
    "SFPIIScanError",
    "SFPIIScanResult",
    "SFQuotaExceededError",
    "SFRateLimitError",
    "SFScopeError",
    "SFSecretsBlockedError",
    "SFSecretsClient",
    "SFSecretsError",
    "SFSecretsScanError",
    "SFServiceUnavailableError",
    "SFStartupError",
    "SFTokenInvalidError",
    "SecretHit",
    "SecretStr",
    "SecretsScanResult",
    "TOTPEnrollResult",
    "TokenIntrospectionResult",
    "TrainingDataPIIReport",
    "configure",
    "sf_identity",
    "sf_pii",
    "sf_secrets",
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

# ---------------------------------------------------------------------------
# Phase 3+ stubs — replaced by full clients in subsequent phases
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


#: Phase 4 — Audit log service.
sf_audit: _UnimplementedClient = _UnimplementedClient("audit")

#: Phase 5 — Observability service.
sf_observe: _UnimplementedClient = _UnimplementedClient("observe")

#: Phase 6 — Feature gate / policy service.
sf_gate: _UnimplementedClient = _UnimplementedClient("gate")

#: Phase 7 — Compliance and evidence collection service.
sf_cec: _UnimplementedClient = _UnimplementedClient("cec")

#: Phase 8 — Alerting service.
sf_alert: _UnimplementedClient = _UnimplementedClient("alert")


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
    global _default_config, sf_identity, sf_pii, sf_secrets
    _default_config = config
    sf_identity = SFIdentityClient(config)
    sf_pii = SFPIIClient(config)
    sf_secrets = SFSecretsClient(config)
