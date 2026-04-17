"""spanforge.sdk — SpanForge service SDK.

Provides pre-built client singletons for all SpanForge platform services.
In Phase 1, only :data:`sf_identity` is fully implemented.  All other
singletons are stubs that will be completed in subsequent phases.

Quick start::

    from spanforge.sdk import sf_identity

    bundle = sf_identity.issue_api_key(scopes=["sf_audit"])
    token  = sf_identity.create_session(bundle.api_key.get_secret_value())
    claims = sf_identity.verify_token(token)

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
    SFQuotaExceededError,
    SFRateLimitError,
    SFScopeError,
    SFServiceUnavailableError,
    SFStartupError,
    SFTokenInvalidError,
)
from spanforge.sdk._types import (
    APIKeyBundle,
    JWTClaims,
    KeyFormat,
    KeyScope,
    MagicLinkResult,
    QuotaTier,
    RateLimitInfo,
    SecretStr,
    TokenIntrospectionResult,
    TOTPEnrollResult,
)
from spanforge.sdk.identity import SFIdentityClient

__all__ = [
    "APIKeyBundle",
    "JWTClaims",
    "KeyFormat",
    "KeyScope",
    "MagicLinkResult",
    "QuotaTier",
    "RateLimitInfo",
    "SFAuthError",
    "SFBruteForceLockedError",
    # Types
    "SFClientConfig",
    # Exceptions
    "SFError",
    "SFIPDeniedError",
    # Phase 1 client
    "SFIdentityClient",
    "SFKeyFormatError",
    "SFMFARequiredError",
    "SFQuotaExceededError",
    "SFRateLimitError",
    "SFScopeError",
    "SFServiceUnavailableError",
    "SFStartupError",
    "SFTokenInvalidError",
    "SecretStr",
    "TOTPEnrollResult",
    "TokenIntrospectionResult",
    # Configuration
    "configure",
    # Singletons
    "sf_identity",
]

# ---------------------------------------------------------------------------
# Singletons — created lazily from environment variables
# ---------------------------------------------------------------------------

_default_config: SFClientConfig | None = None


def _get_config() -> SFClientConfig:
    global _default_config  # noqa: PLW0603
    if _default_config is None:
        _default_config = SFClientConfig.from_env()
    return _default_config


#: Phase 1 — fully implemented.
sf_identity: SFIdentityClient = SFIdentityClient(_get_config())

# ---------------------------------------------------------------------------
# Phase 2+ stubs — replaced by full clients in subsequent phases
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
        raise NotImplementedError(
            f"sf_{name} is not available in Phase 1.  "
            f"It will be implemented in a future phase.  "
            f"See the SpanForge ROADMAP.md for the implementation schedule."
        )


#: Phase 2 — PII redaction service.
sf_pii: _UnimplementedClient = _UnimplementedClient("pii")

#: Phase 3 — Secrets management service.
sf_secrets: _UnimplementedClient = _UnimplementedClient("secrets")

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
    global _default_config, sf_identity  # noqa: PLW0603
    _default_config = config
    sf_identity = SFIdentityClient(config)
