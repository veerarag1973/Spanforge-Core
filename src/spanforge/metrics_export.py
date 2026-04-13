"""spanforge.metrics_export — Prometheus-compatible metrics export.

This module provides a zero-dependency Prometheus text-format metrics
endpoint for SpanForge.  It exposes key observability indicators as gauges
and counters compatible with any Prometheus scraper.

Exported metrics
----------------

=========================================  =====================================
Metric name                                Description
=========================================  =====================================
``spanforge_spans_total``                  Total spans emitted (counter).
``spanforge_spans_error_total``            Total error spans (counter).
``spanforge_export_errors_total``          Total export backend errors (counter).
``spanforge_events_dropped_total``         Total events dropped (counter).
``spanforge_token_usage_total``            Total tokens used (counter by type).
``spanforge_span_duration_ms``             Span duration histogram buckets (gauge).
``spanforge_drift_alerts_total``           Total drift alerts emitted (counter).
=========================================  =====================================

Usage
-----
Standalone HTTP server::

    from spanforge.metrics_export import serve_metrics
    serve_metrics(port=9090)   # starts a background thread

Single scrape (e.g. push-gateway integration)::

    from spanforge.metrics_export import PrometheusMetricsExporter, MetricsSummary

    exporter = PrometheusMetricsExporter()
    text = exporter.export(MetricsSummary(spans_total=1000, error_spans=12, ...))
    print(text)
"""

from __future__ import annotations

import http.server
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "MetricsSummary",
    "PrometheusMetricsExporter",
    "serve_metrics",
]

_log = logging.getLogger("spanforge.metrics_export")


# ---------------------------------------------------------------------------
# MetricsSummary
# ---------------------------------------------------------------------------


@dataclass
class MetricsSummary:
    """Snapshot of SpanForge observability counters.

    Instances of this class are passed to
    :meth:`PrometheusMetricsExporter.export` to generate the Prometheus text
    payload.  All fields default to zero so callers can omit unknown values.

    Args:
        spans_total:        Cumulative number of spans started.
        error_spans:        Cumulative number of spans with status ``"error"``.
        export_errors:      Cumulative export backend errors.
        events_dropped:     Events silently dropped (queue full / circuit open).
        prompt_tokens:      Cumulative prompt token count.
        completion_tokens:  Cumulative completion token count.
        total_tokens:       Cumulative total token count.
        total_cost_usd:     Cumulative estimated cost in USD.
        drift_alerts:       Cumulative drift alert events emitted.
        active_spans:       Gauge — currently open spans.
        duration_buckets:   Histogram bucket counts ``{le_ms: count}``.
        labels:             Optional extra label key/value pairs applied to
                            every metric (e.g. ``{"service": "my-service"}``).
        timestamp_ms:       Unix timestamp (milliseconds) of the snapshot.
    """

    spans_total: int = 0
    error_spans: int = 0
    export_errors: int = 0
    events_dropped: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    drift_alerts: int = 0
    active_spans: int = 0
    duration_buckets: dict[float, int] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))


# ---------------------------------------------------------------------------
# PrometheusMetricsExporter
# ---------------------------------------------------------------------------

_DEFAULT_DURATION_BUCKETS = (5.0, 10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0, 5000.0)


class PrometheusMetricsExporter:
    """Render a :class:`MetricsSummary` as Prometheus text format (0.0.4).

    The output is compatible with Prometheus scraping and the OpenMetrics
    exposition format.

    Args:
        namespace: Optional metric name prefix.  Defaults to ``"spanforge"``.

    Example::

        exporter = PrometheusMetricsExporter()
        summary = MetricsSummary(spans_total=500, error_spans=3)
        print(exporter.export(summary))
    """

    def __init__(self, namespace: str = "spanforge") -> None:
        self._ns = namespace.rstrip("_")

    def export(self, summary: MetricsSummary) -> str:
        """Return Prometheus text exposition for *summary*.

        Args:
            summary: Populated :class:`MetricsSummary` snapshot.

        Returns:
            Multi-line string in Prometheus text format 0.0.4.
        """
        ns = self._ns
        lines: list[str] = []
        ts = summary.timestamp_ms
        base_labels = self._format_labels(summary.labels)

        def counter(name: str, help_text: str, value: int | float) -> None:
            full = f"{ns}_{name}"
            lines.append(f"# HELP {full} {help_text}")
            lines.append(f"# TYPE {full} counter")
            lines.append(f"{full}{base_labels} {value} {ts}")

        def gauge(name: str, help_text: str, value: int | float) -> None:
            full = f"{ns}_{name}"
            lines.append(f"# HELP {full} {help_text}")
            lines.append(f"# TYPE {full} gauge")
            lines.append(f"{full}{base_labels} {value} {ts}")

        # Span counters
        counter("spans_total", "Total number of spans emitted.", summary.spans_total)
        counter("spans_error_total", "Total number of error spans.", summary.error_spans)
        counter("export_errors_total", "Total export backend errors.", summary.export_errors)
        counter("events_dropped_total", "Total events dropped.", summary.events_dropped)
        counter("drift_alerts_total", "Total drift alerts emitted.", summary.drift_alerts)

        # Token usage (with token_type label)
        tok_name = f"{ns}_token_usage_total"
        lines.append(f"# HELP {tok_name} Total token usage by token type.")
        lines.append(f"# TYPE {tok_name} counter")
        for ttype, count in [
            ("prompt", summary.prompt_tokens),
            ("completion", summary.completion_tokens),
            ("total", summary.total_tokens),
        ]:
            label_str = self._format_labels({**summary.labels, "token_type": ttype})
            lines.append(f"{tok_name}{label_str} {count} {ts}")

        # Cost
        counter("cost_usd_total", "Total estimated cost in USD.", summary.total_cost_usd)

        # Active spans (gauge)
        gauge("active_spans", "Currently open (in-flight) spans.", summary.active_spans)

        # Duration histogram
        if summary.duration_buckets:
            hist_name = f"{ns}_span_duration_ms"
            lines.append(f"# HELP {hist_name} Span duration distribution in milliseconds.")
            lines.append(f"# TYPE {hist_name} histogram")
            cumulative = 0
            sorted_buckets = sorted(summary.duration_buckets.items())
            for le, count in sorted_buckets:
                cumulative += count
                le_label = self._format_labels({**summary.labels, "le": str(le)})
                lines.append(f"{hist_name}_bucket{le_label} {cumulative} {ts}")
            # +Inf bucket
            inf_label = self._format_labels({**summary.labels, "le": "+Inf"})
            lines.append(f"{hist_name}_bucket{inf_label} {cumulative} {ts}")
        else:
            # Emit default zero buckets so scrapers don't see missing series.
            hist_name = f"{ns}_span_duration_ms"
            lines.append(f"# HELP {hist_name} Span duration distribution in milliseconds.")
            lines.append(f"# TYPE {hist_name} histogram")
            for le in _DEFAULT_DURATION_BUCKETS:
                le_label = self._format_labels({**summary.labels, "le": str(le)})
                lines.append(f"{hist_name}_bucket{le_label} 0 {ts}")
            inf_label = self._format_labels({**summary.labels, "le": "+Inf"})
            lines.append(f"{hist_name}_bucket{inf_label} 0 {ts}")

        lines.append("")  # trailing newline
        return "\n".join(lines)

    # ------------------------------------------------------------------

    @staticmethod
    def _format_labels(labels: dict[str, str]) -> str:
        if not labels:
            return ""
        # Drop any label keys that don't conform to the Prometheus data model.
        valid_labels = {
            k: v for k, v in labels.items() if _PROM_LABEL_NAME_RE.match(k)
        }
        if not valid_labels:
            return ""
        pairs = ",".join(
            f'{k}="{_escape_label_value(v)}"' for k, v in sorted(valid_labels.items())
        )
        return "{" + pairs + "}"


# M6: Prometheus label names must match [a-zA-Z_:][a-zA-Z0-9_:]* (Prometheus data model).
_PROM_LABEL_NAME_RE: re.Pattern[str] = re.compile(r"^[a-zA-Z_:][a-zA-Z0-9_:]*$")


def _escape_label_value(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


# ---------------------------------------------------------------------------
# Live metrics collector — reads from _stream internals
# ---------------------------------------------------------------------------


def _collect_live_summary() -> MetricsSummary:
    """Build a :class:`MetricsSummary` from live SpanForge stream counters."""
    summary = MetricsSummary()
    try:
        from spanforge._stream import _export_error_count  # noqa: PLC0415
        summary.export_errors = _export_error_count
    except Exception:  # NOSONAR
        pass
    try:
        from spanforge._span import _SPAN_STACK  # noqa: PLC0415
        # _SPAN_STACK is a ContextVar[list]; counting open spans is tricky
        # without a global registry.  Use 0 as a safe default.
        _ = _SPAN_STACK
    except Exception:  # NOSONAR
        pass
    return summary


# ---------------------------------------------------------------------------
# HTTP handler + server
# ---------------------------------------------------------------------------


class _MetricsHTTPHandler(http.server.BaseHTTPRequestHandler):
    """Minimal HTTP handler serving /metrics in Prometheus text format."""

    _exporter: PrometheusMetricsExporter
    _collector: Any  # callable: () -> MetricsSummary

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found\n")
            return

        try:
            summary = self._collector()
            body = self._exporter.export(summary).encode("utf-8")
        except Exception as exc:  # NOSONAR
            _log.error("metrics handler error: %s", exc)
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"Internal Server Error\n")
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:  # pragma: no cover
        # Suppress default access log to stderr.
        pass


def serve_metrics(
    port: int = 9090,
    *,
    host: str = "127.0.0.1",
    collector: Any | None = None,
    namespace: str = "spanforge",
) -> http.server.HTTPServer:
    """Start a background HTTP server exposing ``/metrics`` in Prometheus format.

    The server runs in a daemon thread so it stops automatically when the main
    process exits.

    Args:
        port:      TCP port to bind.  Defaults to ``9090``.
        host:      Interface to bind.  Defaults to ``"127.0.0.1"`` (localhost
                   only).  Set to ``"0.0.0.0"`` to expose on all interfaces
                   (ensure firewall rules are in place).
        collector: Optional callable ``() -> MetricsSummary``.  Defaults to
                   :func:`_collect_live_summary` which reads from SpanForge
                   internals.
        namespace: Metric name prefix (default ``"spanforge"``).

    Returns:
        The running :class:`http.server.HTTPServer` instance.

    Example::

        serve_metrics(port=9090)
        # Scrape at http://localhost:9090/metrics
    """
    exporter = PrometheusMetricsExporter(namespace=namespace)
    _collector = collector if collector is not None else _collect_live_summary

    class _Handler(_MetricsHTTPHandler):
        pass

    _Handler._exporter = exporter  # type: ignore[attr-defined]
    _Handler._collector = staticmethod(_collector)  # type: ignore[attr-defined]

    server = http.server.HTTPServer((host, port), _Handler)
    thread = threading.Thread(
        target=server.serve_forever,
        name=f"spanforge-metrics-{port}",
        daemon=True,
    )
    thread.start()
    _log.info("spanforge metrics server listening on http://%s:%d/metrics", host, port)
    return server
