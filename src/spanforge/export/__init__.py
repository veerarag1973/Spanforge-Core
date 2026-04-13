"""RFC-0001 export backends for spanforge SDK events.

All exporters are **opt-in** — importing this package does not open any network
connections or file handles.  Instantiate an exporter explicitly to activate it.

Core exporters (RFC-0001 §14)
------------------------------
* :class:`~spanforge.export.otlp.OTLPExporter` — OTLP/JSON HTTP exporter
  (zero dependencies; builds OTLP wire format from stdlib).
* :class:`~spanforge.export.otel_bridge.OTelBridgeExporter` — OTel SDK bridge
  that emits real OTel spans via a configured ``TracerProvider``.
  Requires ``pip install "spanforge[otel]"``.
* :class:`~spanforge.export.webhook.WebhookExporter` — HTTP webhook with
  HMAC-SHA256 request signing.
* :class:`~spanforge.export.jsonl.JSONLExporter` — NDJSON for local development
  and audit trail persistence.
"""

from __future__ import annotations

from spanforge.export.append_only import (
    AppendOnlyJSONLExporter,
    WORMBackend,
    WORMUploadResult,
)
from spanforge.export.datadog import DatadogExporter, DatadogResourceAttributes
from spanforge.export.grafana import GrafanaLokiExporter
from spanforge.export.jsonl import JSONLExporter
from spanforge.export.otlp import OTLPExporter, ResourceAttributes
from spanforge.export.webhook import WebhookExporter

# OTelBridgeExporter is an optional import — requires opentelemetry-sdk
try:
    from spanforge.export.otel_bridge import OTelBridgeExporter
except ImportError:
    OTelBridgeExporter = None  # type: ignore[assignment,misc]

__all__ = [
    "AppendOnlyJSONLExporter",
    "DatadogExporter",
    "DatadogResourceAttributes",
    "GrafanaLokiExporter",
    "JSONLExporter",
    "OTLPExporter",
    "OTelBridgeExporter",
    "ResourceAttributes",
    "WORMBackend",
    "WORMUploadResult",
    "WebhookExporter",
]
