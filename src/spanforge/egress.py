"""Egress enforcement for SpanForge export pipeline.

Provides a centralized guard that blocks network exports when the SDK is
configured in no-egress (air-gapped) mode.  Exporters call
:func:`check_egress` before making any HTTP request.

Configuration
-------------
* ``no_egress=True`` on :class:`~spanforge.config.SpanForgeConfig` blocks
  **all** outbound network traffic from SpanForge exporters.
* ``egress_allowlist`` is a ``frozenset[str]`` of URL **prefixes** that are
  permitted even when ``no_egress`` is ``True``.  For example::

      configure(no_egress=True, egress_allowlist=frozenset(["https://internal-collector.corp.local/"]))

Raises :class:`~spanforge.exceptions.EgressViolationError` when a blocked
export is attempted.

Example::

    from spanforge.egress import check_egress
    check_egress("https://example.com/v1/traces", backend="otlp")
"""

from __future__ import annotations

from spanforge.exceptions import EgressViolationError

__all__ = ["check_egress"]


def check_egress(endpoint: str, backend: str = "unknown") -> None:
    """Raise :class:`EgressViolationError` if egress to *endpoint* is blocked.

    This function is a no-op when ``no_egress`` is ``False``.

    Args:
        endpoint: The URL being accessed.
        backend:  Exporter name for the error message (e.g. ``"otlp"``).

    Raises:
        EgressViolationError: If the endpoint is blocked by the egress policy.
    """
    from spanforge.config import get_config

    cfg = get_config()

    if not cfg.no_egress:
        return

    # Check allowlist
    allowlist = cfg.egress_allowlist
    if allowlist:
        for prefix in allowlist:
            if endpoint.startswith(prefix):
                return

    raise EgressViolationError(backend=backend, endpoint=endpoint)
