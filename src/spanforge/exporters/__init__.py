"""spanforge.exporters — Synchronous export backends for the SpanForge SDK.

This package provides the sync exporter implementations used by the internal
:mod:`spanforge._stream` module.  All exporters expose the same minimal
interface::

    class SomeExporter:
        def export(self, event: Event) -> None: ...
        def flush(self) -> None: ...
        def close(self) -> None: ...

Available exporters
-------------------
* :class:`~spanforge.exporters.jsonl.SyncJSONLExporter` — append events as
  newline-delimited JSON to a file.
* :class:`~spanforge.exporters.console.SyncConsoleExporter` — pretty-print
  events to stdout during development.

Additional backends (OTLP, Webhook, Datadog, Grafana Loki) are implemented in
later phases; they live in :mod:`spanforge.export` (the async-based backends) until
synchronous wrappers are added here.
"""

from __future__ import annotations

from spanforge.exporters.console import SyncConsoleExporter
from spanforge.exporters.jsonl import SyncJSONLExporter

__all__ = ["SyncConsoleExporter", "SyncJSONLExporter"]
