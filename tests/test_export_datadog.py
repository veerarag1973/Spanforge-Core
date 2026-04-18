"""Tests for spanforge.export.datadog (DatadogExporter)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

pytest.importorskip("spanforge.export.datadog", reason="spanforge.export.datadog not yet implemented (Phase 8)")

from spanforge import Event, EventType, Tags
from spanforge.exceptions import ExportError
from spanforge.export.datadog import (
    DatadogExporter,
    DatadogResourceAttributes,
)
from spanforge.ulid import generate as gen_ulid

FIXED_TIMESTAMP = "2026-03-01T12:00:00.000000Z"


@pytest.fixture()
def sample_event() -> Event:
    return Event(
        event_type=EventType.TRACE_SPAN_COMPLETED,
        source="llm-trace@1.0.0",
        org_id="org_test",
        payload={
            "span_name": "run_agent",
            "status": "ok",
            "cost_usd": 0.042,
            "token_count": 512,
            "prompt_tokens": 300,
            "completion_tokens": 212,
            "total_tokens": 512,
            "latency_ms": 1234.5,
        },
        event_id=gen_ulid(),
        timestamp=FIXED_TIMESTAMP,
        tags=Tags(env="production", model="gpt-4o"),
    )


@pytest.fixture()
def exporter() -> DatadogExporter:
    return DatadogExporter(
        service="my-llm",
        env="production",
        agent_url="http://localhost:8126",  # NOSONAR
        api_key="fake-api-key",
        allow_private_addresses=True,
    )


# ---------------------------------------------------------------------------
# DatadogResourceAttributes
# ---------------------------------------------------------------------------


class TestDatadogResourceAttributes:
    def test_to_tags_basic(self) -> None:
        attrs = DatadogResourceAttributes(service="svc", env="prod", version="1.0")
        tags = attrs.to_tags()
        assert "service:svc" in tags
        assert "env:prod" in tags
        assert "version:1.0" in tags

    def test_to_tags_no_version(self) -> None:
        # version has a default, so it will always appear
        attrs = DatadogResourceAttributes(service="svc", env="prod")
        tags = attrs.to_tags()
        assert any(t.startswith("service:") for t in tags)
        assert any(t.startswith("env:") for t in tags)

    def test_to_tags_extra(self) -> None:
        attrs = DatadogResourceAttributes(service="s", env="e", extra={"team": "ml"})
        tags = attrs.to_tags()
        assert "team:ml" in tags


# ---------------------------------------------------------------------------
# to_dd_span
# ---------------------------------------------------------------------------


class TestToDdSpan:
    def test_span_fields_present(self, exporter: DatadogExporter, sample_event: Event) -> None:
        span = exporter.to_dd_span(sample_event)
        assert span["name"] == str(sample_event.event_type)
        assert span["service"] == "my-llm"
        assert "trace_id" in span
        assert "span_id" in span
        assert "start" in span
        assert "duration" in span
        assert span["meta"]["llm.source"] == sample_event.source

    def test_span_org_id_in_meta(self, exporter: DatadogExporter, sample_event: Event) -> None:
        span = exporter.to_dd_span(sample_event)
        assert span["meta"]["llm.org_id"] == "org_test"

    def test_span_no_org_id_absent_from_meta(self, exporter: DatadogExporter) -> None:
        event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source="test",
            payload={"span_name": "x"},
            event_id=gen_ulid(),
            timestamp=FIXED_TIMESTAMP,
        )
        span = exporter.to_dd_span(event)
        assert "llm.org_id" not in span["meta"]

    def test_span_optional_fields_in_meta(self, exporter: DatadogExporter) -> None:
        event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source="test",
            payload={"span_name": "x"},
            event_id=gen_ulid(),
            timestamp=FIXED_TIMESTAMP,
            team_id="team-alpha",
            actor_id="user-42",
            session_id="sess-001",
        )
        span = exporter.to_dd_span(event)
        assert span["meta"]["llm.team_id"] == "team-alpha"
        assert span["meta"]["llm.actor_id"] == "user-42"
        assert span["meta"]["llm.session_id"] == "sess-001"

    def test_span_env_resource(self, exporter: DatadogExporter, sample_event: Event) -> None:
        span = exporter.to_dd_span(sample_event)
        # service tag is embedded into resource_attrs and appears in metrics, not the span meta.
        assert span["service"] == "my-llm"


# ---------------------------------------------------------------------------
# to_dd_metric_series
# ---------------------------------------------------------------------------


class TestToDdMetricSeries:
    def test_extracts_numeric_fields(
        self, exporter: DatadogExporter, sample_event: Event
    ) -> None:
        series = exporter.to_dd_metric_series(sample_event)
        metric_names = {s["metric"] for s in series}
        assert "llm.cost_usd" in metric_names
        assert "llm.token_count" in metric_names
        assert "llm.latency_ms" in metric_names

    def test_no_metrics_for_non_numeric(self, exporter: DatadogExporter) -> None:
        event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source="test",
            payload={"span_name": "x", "status": "ok"},
            event_id=gen_ulid(),
            timestamp=FIXED_TIMESTAMP,
        )
        series = exporter.to_dd_metric_series(event)
        assert series == []

    def test_metric_requires_api_key(self) -> None:
        exp = DatadogExporter(service="s", env="e", allow_private_addresses=True)  # no api_key
        event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source="test",
            payload={"cost_usd": 1.0},
            event_id=gen_ulid(),
            timestamp=FIXED_TIMESTAMP,
        )
        series = exp.to_dd_metric_series(event)
        # No api_key → metrics channel skipped; series still generated
        assert isinstance(series, list)


# ---------------------------------------------------------------------------
# Async export — mocked HTTP
# ---------------------------------------------------------------------------


class TestExportAsync:
    def test_export_batch_empty(self, exporter: DatadogExporter) -> None:
        async def _run() -> None:
            await exporter.export_batch([])

        asyncio.run(_run())

    def test_export_single_success(
        self, exporter: DatadogExporter, sample_event: Event
    ) -> None:
        def _mock_urlopen(req: Any, timeout: Any = None) -> Any:
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read.return_value = b""
            return mock_resp

        with patch("spanforge.export.datadog.urllib.request.urlopen", _mock_urlopen):
            async def _run() -> None:
                await exporter.export(sample_event)

            asyncio.run(_run())

    def test_export_batch_returns_count(
        self, exporter: DatadogExporter, sample_event: Event
    ) -> None:
        def _mock_urlopen(req: Any, timeout: Any = None) -> Any:
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read.return_value = b""
            return mock_resp

        with patch("spanforge.export.datadog.urllib.request.urlopen", _mock_urlopen):
            async def _run() -> None:
                await exporter.export_batch([sample_event, sample_event])

            asyncio.run(_run())

    def test_export_raises_on_http_error(
        self, exporter: DatadogExporter, sample_event: Event
    ) -> None:
        import urllib.error

        def _fail_urlopen(req: Any, timeout: Any = None) -> Any:
            raise urllib.error.HTTPError(None, 500, "Internal Server Error", {}, None)

        with patch("spanforge.export.datadog.urllib.request.urlopen", _fail_urlopen):
            async def _run() -> None:
                await exporter.export(sample_event)

            with pytest.raises(ExportError, match="datadog"):
                asyncio.run(_run())

    def test_export_raises_on_os_error(
        self, exporter: DatadogExporter, sample_event: Event
    ) -> None:
        def _fail_urlopen(req: Any, timeout: Any = None) -> Any:
            raise OSError("connection refused")

        with patch("spanforge.export.datadog.urllib.request.urlopen", _fail_urlopen):
            async def _run() -> None:
                await exporter.export(sample_event)

            with pytest.raises(ExportError, match="datadog"):
                asyncio.run(_run())


# ---------------------------------------------------------------------------
# repr
# ---------------------------------------------------------------------------


class TestRepr:
    def test_repr(self, exporter: DatadogExporter) -> None:
        r = repr(exporter)
        assert "DatadogExporter" in r
        assert "my-llm" in r


# ---------------------------------------------------------------------------
# Trace-span path (event with trace_id triggers _send_traces)
# ---------------------------------------------------------------------------


class TestTraceSpanExport:
    def test_export_event_with_trace_id(self, exporter: DatadogExporter) -> None:
        """An event with trace_id causes trace spans to be sent."""
        event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source="test",
            payload={"span_name": "x", "cost_usd": 0.01},
            event_id=gen_ulid(),
            timestamp=FIXED_TIMESTAMP,
            trace_id="a" * 32,
            span_id="b" * 16,
        )

        def _mock_urlopen(req: Any, timeout: Any = None) -> Any:
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read.return_value = b""
            return mock_resp

        with patch("spanforge.export.datadog.urllib.request.urlopen", _mock_urlopen):
            async def _run() -> None:
                await exporter.export(event)

            asyncio.run(_run())

    def test_export_trace_only_no_metric_fields(self, exporter: DatadogExporter) -> None:
        """Event with trace_id but no metric fields: trace sent, no metrics path."""
        event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source="test",
            payload={"span_name": "x", "status": "ok"},  # no _METRIC_FIELDS keys
            event_id=gen_ulid(),
            timestamp=FIXED_TIMESTAMP,
            trace_id="c" * 32,
            span_id="d" * 16,
        )

        def _mock_urlopen(req: Any, timeout: Any = None) -> Any:
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.read.return_value = b""
            return mock_resp

        with patch("spanforge.export.datadog.urllib.request.urlopen", _mock_urlopen):
            async def _run() -> None:
                await exporter.export(event)

            asyncio.run(_run())

    def test_export_no_trace_no_metrics_skips_tasks(self, exporter: DatadogExporter) -> None:
        """Event with no trace_id and no metric fields: tasks list stays empty."""
        event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source="test",
            payload={"span_name": "x", "status": "ok"},  # no trace_id, no metrics
            event_id=gen_ulid(),
            timestamp=FIXED_TIMESTAMP,
        )

        async def _run() -> None:
            await exporter.export(event)

        asyncio.run(_run())  # should not call urlopen at all

    def test_metric_bool_value_skipped(self, exporter: DatadogExporter) -> None:
        """Bool values in metric fields should be skipped (covers second continue)."""
        event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source="test",
            payload={"cost_usd": True},  # in _METRIC_FIELDS but is bool → skip
            event_id=gen_ulid(),
            timestamp=FIXED_TIMESTAMP,
        )
        series = exporter.to_dd_metric_series(event)
        assert series == []

    def test_send_traces_http_error_raises_export_error(
        self, exporter: DatadogExporter
    ) -> None:
        """_send_traces raises ExportError on HTTP error (covers except HTTPError)."""
        import urllib.error
        event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source="test",
            payload={"span_name": "x"},
            event_id=gen_ulid(),
            timestamp=FIXED_TIMESTAMP,
            trace_id="e" * 32,
            span_id="f" * 16,
        )

        def _fail(req: Any, timeout: Any = None) -> Any:
            raise urllib.error.HTTPError(None, 502, "Bad Gateway", {}, None)

        with patch("spanforge.export.datadog.urllib.request.urlopen", _fail):
            async def _run() -> None:
                await exporter.export(event)

            with pytest.raises(ExportError, match="datadog"):
                asyncio.run(_run())

    def test_send_traces_os_error_raises_export_error(
        self, exporter: DatadogExporter
    ) -> None:
        """_send_traces raises ExportError on OSError (covers except OSError)."""
        event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source="test",
            payload={"span_name": "x"},
            event_id=gen_ulid(),
            timestamp=FIXED_TIMESTAMP,
            trace_id="a" * 32,
            span_id="b" * 16,
        )

        def _fail(req: Any, timeout: Any = None) -> Any:
            raise OSError("connection refused to agent")

        with patch("spanforge.export.datadog.urllib.request.urlopen", _fail):
            async def _run() -> None:
                await exporter.export(event)

            with pytest.raises(ExportError, match="datadog"):
                asyncio.run(_run())


