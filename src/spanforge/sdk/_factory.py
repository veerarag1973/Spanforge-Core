"""spanforge.sdk._factory — SFClientFactory: single config vends all clients.

Usage::

    from spanforge.sdk import SFClientFactory

    factory = SFClientFactory.from_env()
    result = factory.pii.scan("Hello, my name is Alice.")
    evidence = factory.cec.build_evidence_package(project_id="demo")
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from spanforge.sdk._base import SFClientConfig

if TYPE_CHECKING:
    from spanforge.sdk.alert import SFAlertClient
    from spanforge.sdk.audit import SFAuditClient
    from spanforge.sdk.cec import SFCECClient
    from spanforge.sdk.gate import SFGateClient
    from spanforge.sdk.identity import SFIdentityClient
    from spanforge.sdk.observe import SFObserveClient
    from spanforge.sdk.pii import SFPIIClient
    from spanforge.sdk.secrets import SFSecretsClient

__all__ = ["SFClientFactory"]


class SFClientFactory:
    """Single factory that vends all SpanForge service clients from one config.

    All clients are constructed **lazily** on first property access and cached
    for the lifetime of the factory.  This prevents unnecessary TCP connections
    and avoids circular-import issues at module load time.

    Args:
        config: Shared :class:`~spanforge.sdk._base.SFClientConfig` applied to
                every client.  If omitted, :meth:`from_env` may be used to
                construct one from environment variables.

    Example::

        from spanforge.sdk import SFClientFactory

        factory = SFClientFactory.from_env()
        pii_result = factory.pii.scan("Call me at 555-867-5309")
        audit_result = factory.audit.append(
            {"score": 0.95, "model": "gpt-4"},
            schema_key="halluccheck.score.v1",
        )
    """

    def __init__(self, config: SFClientConfig) -> None:
        self._config = config
        # Lazy-init cache — all start as None
        self._pii: SFPIIClient | None = None
        self._secrets: SFSecretsClient | None = None
        self._audit: SFAuditClient | None = None
        self._cec: SFCECClient | None = None
        self._gate: SFGateClient | None = None
        self._observe: SFObserveClient | None = None
        self._alert: SFAlertClient | None = None
        self._identity: SFIdentityClient | None = None

    # ------------------------------------------------------------------
    # Alternative constructor
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> SFClientFactory:
        """Build a factory from environment variables via :meth:`SFClientConfig.from_env`."""
        return cls(SFClientConfig.from_env())

    # ------------------------------------------------------------------
    # Lazy client properties
    # ------------------------------------------------------------------

    @property
    def pii(self) -> SFPIIClient:
        """Lazily-initialised :class:`~spanforge.sdk.pii.SFPIIClient`."""
        if self._pii is None:
            from spanforge.sdk.pii import SFPIIClient

            self._pii = SFPIIClient(self._config)
        return self._pii

    @property
    def secrets(self) -> SFSecretsClient:
        """Lazily-initialised :class:`~spanforge.sdk.secrets.SFSecretsClient`."""
        if self._secrets is None:
            from spanforge.sdk.secrets import SFSecretsClient

            self._secrets = SFSecretsClient(self._config)
        return self._secrets

    @property
    def audit(self) -> SFAuditClient:
        """Lazily-initialised :class:`~spanforge.sdk.audit.SFAuditClient`."""
        if self._audit is None:
            from spanforge.sdk.audit import SFAuditClient

            self._audit = SFAuditClient(self._config)
        return self._audit

    @property
    def cec(self) -> SFCECClient:
        """Lazily-initialised :class:`~spanforge.sdk.cec.SFCECClient`."""
        if self._cec is None:
            from spanforge.sdk.cec import SFCECClient

            self._cec = SFCECClient(self._config)
        return self._cec

    @property
    def gate(self) -> SFGateClient:
        """Lazily-initialised :class:`~spanforge.sdk.gate.SFGateClient`."""
        if self._gate is None:
            from spanforge.sdk.gate import SFGateClient

            self._gate = SFGateClient(self._config)
        return self._gate

    @property
    def observe(self) -> SFObserveClient:
        """Lazily-initialised :class:`~spanforge.sdk.observe.SFObserveClient`."""
        if self._observe is None:
            from spanforge.sdk.observe import SFObserveClient

            self._observe = SFObserveClient(self._config)
        return self._observe

    @property
    def alert(self) -> SFAlertClient:
        """Lazily-initialised :class:`~spanforge.sdk.alert.SFAlertClient`."""
        if self._alert is None:
            from spanforge.sdk.alert import SFAlertClient

            self._alert = SFAlertClient(self._config)
        return self._alert

    @property
    def identity(self) -> SFIdentityClient:
        """Lazily-initialised :class:`~spanforge.sdk.identity.SFIdentityClient`."""
        if self._identity is None:
            from spanforge.sdk.identity import SFIdentityClient

            self._identity = SFIdentityClient(self._config)
        return self._identity
