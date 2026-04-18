"""Tests for spanforge Phase 6 — sf-observe Observability Named SDK.

Coverage targets: ≥ 90 % on spanforge/sdk/observe.py, Phase 6 additions to
spanforge/sdk/_exceptions.py and spanforge/sdk/_types.py.

Test structure
--------------
* Exception hierarchy — SFObserveError, SFObserveExportError,
  SFObserveEmitError, SFObserveAnnotationError all subclass SFError.
* Type shapes — ExportResult, Annotation, ObserveStatusInfo, ReceiverConfig,
  SamplerStrategy are importable and have expected fields.
* export_spans — happy path (empty + non-empty), local buffer, local fallback,
  ExportResult shape, invalid input raises SFObserveExportError.
* add_annotation — happy path, UUID format, annotation_count increments,
  empty event_type raises SFObserveAnnotationError, non-dict payload raises.
* get_annotations — filters by event_type, by time range, by project_id,
  wildcard event_type returns all, bad datetime raises SFObserveAnnotationError.
* emit_span — happy path returns 16-hex SpanId, span_count increments,
  OTel resource attributes, gen_ai.* keys forwarded, error status handling,
  W3C traceparent inherited from parent, empty name raises SFObserveEmitError,
  non-dict attributes raises SFObserveEmitError.
* get_status — returns ObserveStatusInfo, healthy starts True.
* Sampling strategies — ALWAYS_OFF skips export, ALWAYS_ON exports,
  TRACE_ID_RATIO 0.0 vs 1.0, PARENT_BASED with/without parent.
* W3C helpers — make_traceparent valid, extract_traceparent round-trip,
  invalid traceparent raises ValueError.
* Thread safety — 50 concurrent emit_span calls, span_count is exactly 50.
* SDK singleton — ``from spanforge.sdk import sf_observe`` is SFObserveClient.
* configure() — sf_observe is recreated.
* healthy / last_export_at properties.
* _generate_trace_id / _generate_span_id format validation.
* SamplerStrategy enum values.
* SUPPORTED_BACKENDS constant.
* _build_otel_span — traceparent embedded, status code handling.
* _should_sample — all four strategies.
* Backend-specific helpers — _span_to_dd, _span_to_ecs.
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from spanforge.sdk._base import SFClientConfig
from spanforge.sdk._exceptions import (
    SFError,
    SFObserveAnnotationError,
    SFObserveEmitError,
    SFObserveError,
    SFObserveExportError,
)
from spanforge.sdk._types import (
    Annotation,
    ExportResult,
    ObserveStatusInfo,
    ReceiverConfig,
    SamplerStrategy,
)
from spanforge.sdk.observe import (
    SUPPORTED_BACKENDS,
    SFObserveClient,
    _build_otel_span,
    _generate_span_id,
    _generate_trace_id,
    _should_sample,
    _span_to_dd,
    _span_to_ecs,
    extract_traceparent,
    make_traceparent,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PROJECT = "test-project"


def _make_client(**kwargs: object) -> SFObserveClient:
    config = SFClientConfig(**kwargs)  # type: ignore[arg-type]
    return SFObserveClient(config)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dt_offset(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


# ---------------------------------------------------------------------------
# Exception hierarchy (Phase 6)
# ---------------------------------------------------------------------------


class TestObserveExceptionHierarchy:
    def test_sfobserveerror_is_sferror(self) -> None:
        assert issubclass(SFObserveError, SFError)

    def test_sfobserveexporterror_is_sfobserveerror(self) -> None:
        assert issubclass(SFObserveExportError, SFObserveError)

    def test_sfobserveemiterror_is_sfobserveerror(self) -> None:
        assert issubclass(SFObserveEmitError, SFObserveError)

    def test_sfobserveannotationerror_is_sfobserveerror(self) -> None:
        assert issubclass(SFObserveAnnotationError, SFObserveError)

    def test_sfobserveexporterror_message(self) -> None:
        exc = SFObserveExportError("timeout")
        assert "timeout" in str(exc)
        assert exc.detail == "timeout"

    def test_sfobserveemiterror_message(self) -> None:
        exc = SFObserveEmitError("bad span")
        assert "bad span" in str(exc)
        assert exc.detail == "bad span"

    def test_sfobserveannotationerror_message(self) -> None:
        exc = SFObserveAnnotationError("store full")
        assert "store full" in str(exc)
        assert exc.detail == "store full"


# ---------------------------------------------------------------------------
# Type shapes (Phase 6)
# ---------------------------------------------------------------------------


class TestObserveTypeShapes:
    def test_export_result_fields(self) -> None:
        r = ExportResult(exported_count=5, failed_count=0, backend="local", exported_at=_now_iso())
        assert r.exported_count == 5
        assert r.failed_count == 0
        assert r.backend == "local"
        assert "T" in r.exported_at or "+" in r.exported_at

    def test_export_result_is_frozen(self) -> None:
        r = ExportResult(exported_count=1, failed_count=0, backend="otlp", exported_at=_now_iso())
        with pytest.raises((AttributeError, TypeError)):
            r.exported_count = 99  # type: ignore[misc]

    def test_annotation_fields(self) -> None:
        ann = Annotation(
            annotation_id=str(uuid.uuid4()),
            event_type="model_deployed",
            payload={"model": "gpt-4o"},
            project_id=_PROJECT,
            created_at=_now_iso(),
        )
        assert ann.event_type == "model_deployed"
        assert ann.payload == {"model": "gpt-4o"}
        assert ann.project_id == _PROJECT

    def test_annotation_is_frozen(self) -> None:
        ann = Annotation(
            annotation_id="x",
            event_type="ev",
            payload={},
            project_id="p",
            created_at=_now_iso(),
        )
        with pytest.raises((AttributeError, TypeError)):
            ann.event_type = "other"  # type: ignore[misc]

    def test_observe_status_info_fields(self) -> None:
        s = ObserveStatusInfo(
            status="ok",
            backend="local",
            sampler_strategy="always_on",
            span_count=0,
            annotation_count=0,
            export_count=0,
            last_export_at=None,
            healthy=True,
        )
        assert s.status == "ok"
        assert s.healthy is True

    def test_receiver_config_fields(self) -> None:
        rc = ReceiverConfig(endpoint="https://collector.example.com/v1/traces")
        assert rc.endpoint == "https://collector.example.com/v1/traces"
        assert rc.headers == {}
        assert rc.timeout_seconds == 30.0

    def test_receiver_config_with_headers(self) -> None:
        rc = ReceiverConfig(
            endpoint="https://otel.example.com",
            headers={"Authorization": "Bearer tok"},
            timeout_seconds=10.0,
        )
        assert rc.headers["Authorization"] == "Bearer tok"
        assert rc.timeout_seconds == 10.0

    def test_sampler_strategy_values(self) -> None:
        assert SamplerStrategy.ALWAYS_ON.value == "always_on"
        assert SamplerStrategy.ALWAYS_OFF.value == "always_off"
        assert SamplerStrategy.PARENT_BASED.value == "parent_based"
        assert SamplerStrategy.TRACE_ID_RATIO.value == "trace_id_ratio"

    def test_sampler_strategy_from_value(self) -> None:
        assert SamplerStrategy("always_on") is SamplerStrategy.ALWAYS_ON


# ---------------------------------------------------------------------------
# W3C TraceContext helpers
# ---------------------------------------------------------------------------


class TestW3CTraceContext:
    def test_make_traceparent_sampled(self) -> None:
        trace_id = "a" * 32
        span_id = "b" * 16
        tp = make_traceparent(trace_id, span_id, sampled=True)
        assert tp == f"00-{'a' * 32}-{'b' * 16}-01"

    def test_make_traceparent_not_sampled(self) -> None:
        trace_id = "c" * 32
        span_id = "d" * 16
        tp = make_traceparent(trace_id, span_id, sampled=False)
        assert tp.endswith("-00")

    def test_make_traceparent_invalid_trace_id_length(self) -> None:
        with pytest.raises(ValueError, match="32"):
            make_traceparent("abc", "1234567890abcdef")

    def test_make_traceparent_invalid_span_id_length(self) -> None:
        with pytest.raises(ValueError, match="16"):
            make_traceparent("a" * 32, "short")

    def test_make_traceparent_invalid_hex(self) -> None:
        with pytest.raises(ValueError):
            make_traceparent("g" * 32, "h" * 16)

    def test_extract_traceparent_round_trip(self) -> None:
        trace_id = _generate_trace_id()
        span_id = _generate_span_id()
        tp = make_traceparent(trace_id, span_id, sampled=True)
        ext_trace, ext_span, sampled = extract_traceparent(tp)
        assert ext_trace == trace_id
        assert ext_span == span_id
        assert sampled is True

    def test_extract_traceparent_not_sampled(self) -> None:
        trace_id = _generate_trace_id()
        span_id = _generate_span_id()
        tp = make_traceparent(trace_id, span_id, sampled=False)
        _, _, sampled = extract_traceparent(tp)
        assert sampled is False

    def test_extract_traceparent_invalid_format(self) -> None:
        with pytest.raises(ValueError, match="4"):
            extract_traceparent("bad-format")

    def test_extract_traceparent_short_trace_id(self) -> None:
        with pytest.raises(ValueError, match="32"):
            extract_traceparent("00-aabb-1234567890abcdef-01")

    def test_extract_traceparent_short_span_id(self) -> None:
        with pytest.raises(ValueError, match="16"):
            extract_traceparent(f"00-{'a' * 32}-short-01")

    def test_generate_trace_id_length(self) -> None:
        tid = _generate_trace_id()
        assert len(tid) == 32  # noqa: PLR2004
        int(tid, 16)  # must be valid hex

    def test_generate_span_id_length(self) -> None:
        sid = _generate_span_id()
        assert len(sid) == 16  # noqa: PLR2004
        int(sid, 16)  # must be valid hex


# ---------------------------------------------------------------------------
# _build_otel_span
# ---------------------------------------------------------------------------


class TestBuildOtelSpan:
    def test_basic_span_structure(self) -> None:
        trace_id = _generate_trace_id()
        span_id = _generate_span_id()
        span = _build_otel_span("chat.completion", {}, trace_id, span_id)
        assert span["name"] == "chat.completion"
        assert span["traceId"] == trace_id
        assert span["spanId"] == span_id
        assert "traceparent" in span
        assert "resource" in span
        assert "attributes" in span

    def test_otel_resource_attributes(self) -> None:
        span = _build_otel_span("test", {}, _generate_trace_id(), _generate_span_id())
        resource_attrs = span["resource"]["attributes"]
        assert resource_attrs["service.name"] == "spanforge"
        assert "service.version" in resource_attrs
        assert resource_attrs["telemetry.sdk.language"] == "python"

    def test_gen_ai_attributes_forwarded(self) -> None:
        attrs = {
            "gen_ai.system": "openai",
            "gen_ai.request.model": "gpt-4o",
            "gen_ai.usage.input_tokens": 512,
        }
        span = _build_otel_span("chat", attrs, _generate_trace_id(), _generate_span_id())
        span_attrs = span["attributes"]
        assert span_attrs["gen_ai.system"] == "openai"
        assert span_attrs["gen_ai.request.model"] == "gpt-4o"
        assert span_attrs["gen_ai.usage.input_tokens"] == 512  # noqa: PLR2004

    def test_ok_status(self) -> None:
        span = _build_otel_span("test", {"status": "ok"}, _generate_trace_id(), _generate_span_id())
        assert span["status"]["code"] == "STATUS_CODE_OK"

    def test_error_status_via_status_key(self) -> None:
        span = _build_otel_span(
            "test",
            {"status": "error", "exception.message": "timeout"},
            _generate_trace_id(),
            _generate_span_id(),
        )
        assert span["status"]["code"] == "STATUS_CODE_ERROR"
        assert span["attributes"]["otel.status_code"] == "ERROR"
        assert "timeout" in span["status"]["message"]

    def test_error_status_via_otel_key(self) -> None:
        span = _build_otel_span(
            "test",
            {"otel.status_code": "ERROR"},
            _generate_trace_id(),
            _generate_span_id(),
        )
        assert span["status"]["code"] == "STATUS_CODE_ERROR"

    def test_traceparent_embedded_in_attributes(self) -> None:
        span = _build_otel_span("test", {}, _generate_trace_id(), _generate_span_id())
        assert span["attributes"]["traceparent"].startswith("00-")

    def test_baggage_injected_when_keys_present(self) -> None:
        attrs = {"project_id": "proj-123", "domain": "llm", "tier": "enterprise"}
        span = _build_otel_span("test", attrs, _generate_trace_id(), _generate_span_id())
        assert "baggage" in span["attributes"]
        assert "project_id=proj-123" in span["attributes"]["baggage"]

    def test_no_baggage_without_keys(self) -> None:
        span = _build_otel_span("test", {"other": "val"}, _generate_trace_id(), _generate_span_id())
        assert "baggage" not in span["attributes"]

    def test_sampled_flag_in_traceparent(self) -> None:
        span = _build_otel_span("test", {}, _generate_trace_id(), _generate_span_id(), sampled=True)
        assert span["traceparent"].endswith("-01")

    def test_not_sampled_flag(self) -> None:
        span = _build_otel_span("test", {}, _generate_trace_id(), _generate_span_id(), sampled=False)
        assert span["traceparent"].endswith("-00")


# ---------------------------------------------------------------------------
# _should_sample
# ---------------------------------------------------------------------------


class TestShouldSample:
    def test_always_on(self) -> None:
        assert _should_sample(SamplerStrategy.ALWAYS_ON, 1.0, _generate_trace_id(), None) is True

    def test_always_off(self) -> None:
        assert _should_sample(SamplerStrategy.ALWAYS_OFF, 1.0, _generate_trace_id(), None) is False

    def test_parent_based_no_parent(self) -> None:
        # No parent → sample by default
        assert _should_sample(SamplerStrategy.PARENT_BASED, 1.0, _generate_trace_id(), None) is True

    def test_parent_based_parent_sampled(self) -> None:
        assert _should_sample(SamplerStrategy.PARENT_BASED, 1.0, _generate_trace_id(), True) is True

    def test_parent_based_parent_not_sampled(self) -> None:
        assert (
            _should_sample(SamplerStrategy.PARENT_BASED, 1.0, _generate_trace_id(), False) is False
        )

    def test_trace_id_ratio_zero(self) -> None:
        # At 0.0 nothing is sampled
        assert _should_sample(SamplerStrategy.TRACE_ID_RATIO, 0.0, _generate_trace_id(), None) is False

    def test_trace_id_ratio_one(self) -> None:
        # At 1.0 everything is sampled
        assert _should_sample(SamplerStrategy.TRACE_ID_RATIO, 1.0, _generate_trace_id(), None) is True

    def test_trace_id_ratio_deterministic(self) -> None:
        # Same trace_id → same decision
        tid = _generate_trace_id()
        r1 = _should_sample(SamplerStrategy.TRACE_ID_RATIO, 0.5, tid, None)
        r2 = _should_sample(SamplerStrategy.TRACE_ID_RATIO, 0.5, tid, None)
        assert r1 == r2


# ---------------------------------------------------------------------------
# export_spans
# ---------------------------------------------------------------------------


class TestExportSpans:
    def test_empty_spans_returns_zero_counts(self) -> None:
        client = _make_client()
        result = client.export_spans([])
        assert result.exported_count == 0
        assert result.failed_count == 0
        assert result.backend == "local"
        assert result.exported_at  # non-empty

    def test_non_empty_spans_local_backend(self) -> None:
        client = _make_client()
        spans = [
            {"name": "test", "traceId": _generate_trace_id(), "spanId": _generate_span_id()},
            {"name": "test2", "traceId": _generate_trace_id(), "spanId": _generate_span_id()},
        ]
        result = client.export_spans(spans)
        assert result.exported_count == 2
        assert result.failed_count == 0

    def test_export_result_is_export_result_instance(self) -> None:
        client = _make_client()
        result = client.export_spans([])
        assert isinstance(result, ExportResult)

    def test_invalid_spans_type_raises(self) -> None:
        client = _make_client()
        with pytest.raises(SFObserveExportError, match="list"):
            client.export_spans("not a list")  # type: ignore[arg-type]

    def test_export_increments_export_count(self) -> None:
        client = _make_client()
        client.export_spans([])
        client.export_spans([])
        assert client.get_status().export_count == 2

    def test_last_export_at_updated(self) -> None:
        client = _make_client()
        client.export_spans([])
        assert client.last_export_at is not None

    def test_healthy_after_successful_export(self) -> None:
        client = _make_client()
        client.export_spans([])
        assert client.healthy is True

    def test_receiver_config_endpoint_validation(self) -> None:
        client = _make_client()
        rc = ReceiverConfig(endpoint="ftp://invalid-scheme.com")
        with pytest.raises((SFObserveExportError, ValueError)):
            client.export_spans([{"name": "test"}], receiver_config=rc)

    def test_receiver_config_posts_to_endpoint(self) -> None:
        client = _make_client()
        rc = ReceiverConfig(endpoint="https://otel.example.com/v1/traces")
        spans = [{"name": "test", "traceId": "a" * 32, "spanId": "b" * 16, "attributes": {}}]
        with patch("spanforge.sdk.observe._post_json") as mock_post:
            result = client.export_spans(spans, receiver_config=rc)
        assert result.exported_count == 1
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert call_url == "https://otel.example.com/v1/traces"

    def test_receiver_config_includes_custom_headers(self) -> None:
        client = _make_client()
        rc = ReceiverConfig(
            endpoint="https://otel.example.com/v1/traces",
            headers={"X-Custom": "value"},
        )
        with patch("spanforge.sdk.observe._post_json") as mock_post:
            client.export_spans([{"name": "x"}], receiver_config=rc)
        headers_passed = mock_post.call_args[0][2]
        assert headers_passed["X-Custom"] == "value"

    def test_local_fallback_on_export_error(self) -> None:
        client = _make_client(endpoint="https://otel.example.com", local_fallback_enabled=True)
        # Force backend to "otlp" by patching the client's backend field
        client._backend = "otlp"
        with patch("spanforge.sdk.observe._post_json", side_effect=SFObserveExportError("timeout")):
            result = client.export_spans([{"name": "x"}])
        # Fallback: spans buffered locally, exported_count still reported
        assert result.exported_count == 1

    def test_no_fallback_raises_on_export_error(self) -> None:
        client = _make_client(
            endpoint="https://otel.example.com", local_fallback_enabled=False
        )
        client._backend = "otlp"
        with patch("spanforge.sdk.observe._post_json", side_effect=SFObserveExportError("down")):
            with pytest.raises(SFObserveExportError):
                client.export_spans([{"name": "x"}])


# ---------------------------------------------------------------------------
# emit_span
# ---------------------------------------------------------------------------


class TestEmitSpan:
    def test_returns_span_id_hex(self) -> None:
        client = _make_client()
        span_id = client.emit_span("test.op", {})
        assert len(span_id) == 16  # noqa: PLR2004
        int(span_id, 16)  # must be valid hex

    def test_span_count_increments(self) -> None:
        client = _make_client()
        client.emit_span("op1", {})
        client.emit_span("op2", {})
        assert client.get_status().span_count == 2

    def test_gen_ai_attributes_forwarded(self) -> None:
        client = _make_client()
        exported_spans: list[list[object]] = []

        def capture(spans: list[object], receiver_config: object) -> tuple[int, int]:
            exported_spans.extend([spans])
            return len(spans), 0

        with patch.object(client, "_do_export", side_effect=capture):
            client.emit_span(
                "chat.completion",
                {
                    "gen_ai.system": "openai",
                    "gen_ai.request.model": "gpt-4o",
                    "gen_ai.usage.input_tokens": 128,
                },
            )

        assert exported_spans
        span = exported_spans[0][0]  # type: ignore[index]
        assert span["attributes"]["gen_ai.system"] == "openai"  # type: ignore[index]

    def test_otel_resource_attributes_present(self) -> None:
        client = _make_client()
        captured: list[dict[str, object]] = []

        def capture(spans: list[object], receiver_config: object) -> tuple[int, int]:
            captured.extend(spans)  # type: ignore[arg-type]
            return len(spans), 0

        with patch.object(client, "_do_export", side_effect=capture):
            client.emit_span("test", {})

        assert captured
        resource = captured[0].get("resource", {})  # type: ignore[union-attr]
        assert resource.get("attributes", {}).get("service.name") == "spanforge"  # type: ignore[union-attr]

    def test_error_span_status_code(self) -> None:
        client = _make_client()
        captured: list[dict[str, object]] = []

        def capture(spans: list[object], receiver_config: object) -> tuple[int, int]:
            captured.extend(spans)  # type: ignore[arg-type]
            return len(spans), 0

        with patch.object(client, "_do_export", side_effect=capture):
            client.emit_span("failing.op", {"status": "error", "exception.message": "boom"})

        assert captured
        assert captured[0]["status"]["code"] == "STATUS_CODE_ERROR"  # type: ignore[index]

    def test_parent_traceparent_reuses_trace_id(self) -> None:
        client = _make_client()
        parent_trace_id = _generate_trace_id()
        parent_span_id = _generate_span_id()
        parent_tp = make_traceparent(parent_trace_id, parent_span_id, sampled=True)
        captured: list[dict[str, object]] = []

        def capture(spans: list[object], receiver_config: object) -> tuple[int, int]:
            captured.extend(spans)  # type: ignore[arg-type]
            return len(spans), 0

        with patch.object(client, "_do_export", side_effect=capture):
            client.emit_span("child.op", {"traceparent": parent_tp})

        assert captured
        assert captured[0]["traceId"] == parent_trace_id  # type: ignore[index]

    def test_empty_name_raises(self) -> None:
        client = _make_client()
        with pytest.raises(SFObserveEmitError, match="name"):
            client.emit_span("", {})

    def test_non_dict_attributes_raises(self) -> None:
        client = _make_client()
        with pytest.raises(SFObserveEmitError, match="dict"):
            client.emit_span("test", "not-a-dict")  # type: ignore[arg-type]

    def test_invalid_traceparent_is_ignored(self) -> None:
        client = _make_client()
        # Should not raise; invalid traceparent is silently ignored
        span_id = client.emit_span("test", {"traceparent": "bad-value"})
        assert len(span_id) == 16  # noqa: PLR2004

    def test_always_off_sampler_still_returns_span_id(self) -> None:
        client = _make_client()
        client._sampler_strategy = SamplerStrategy.ALWAYS_OFF
        span_id = client.emit_span("skipped", {})
        assert len(span_id) == 16  # noqa: PLR2004

    def test_always_off_sampler_does_not_export(self) -> None:
        client = _make_client()
        client._sampler_strategy = SamplerStrategy.ALWAYS_OFF
        with patch.object(client, "export_spans") as mock_export:
            client.emit_span("skipped", {})
        mock_export.assert_not_called()

    def test_emit_raises_observe_emit_error_on_export_failure(self) -> None:
        client = _make_client(local_fallback_enabled=False)
        client._backend = "otlp"
        client._config.endpoint = "https://dead.example.com"  # type: ignore[misc]
        with patch.object(
            client,
            "_do_export",
            side_effect=SFObserveExportError("connection refused"),
        ):
            with pytest.raises(SFObserveEmitError):
                client.emit_span("test", {})


# ---------------------------------------------------------------------------
# add_annotation
# ---------------------------------------------------------------------------


class TestAddAnnotation:
    def test_returns_uuid_string(self) -> None:
        client = _make_client()
        aid = client.add_annotation("model_deployed", {"v": "1"}, project_id=_PROJECT)
        uuid.UUID(aid)  # raises if not a valid UUID

    def test_annotation_count_increments(self) -> None:
        client = _make_client()
        client.add_annotation("ev", {}, project_id=_PROJECT)
        client.add_annotation("ev", {}, project_id=_PROJECT)
        assert client.get_status().annotation_count == 2

    def test_empty_event_type_raises(self) -> None:
        client = _make_client()
        with pytest.raises(SFObserveAnnotationError, match="event_type"):
            client.add_annotation("", {}, project_id=_PROJECT)

    def test_non_dict_payload_raises(self) -> None:
        client = _make_client()
        with pytest.raises(SFObserveAnnotationError, match="dict"):
            client.add_annotation("ev", "bad-payload", project_id=_PROJECT)  # type: ignore[arg-type]

    def test_annotation_id_is_unique(self) -> None:
        client = _make_client()
        id1 = client.add_annotation("ev", {}, project_id=_PROJECT)
        id2 = client.add_annotation("ev", {}, project_id=_PROJECT)
        assert id1 != id2


# ---------------------------------------------------------------------------
# get_annotations
# ---------------------------------------------------------------------------


class TestGetAnnotations:
    def _seed_annotations(self, client: SFObserveClient) -> None:
        client.add_annotation("deploy", {"model": "gpt-4o"}, project_id="proj-a")
        client.add_annotation("alert", {"severity": "high"}, project_id="proj-b")
        client.add_annotation("deploy", {"model": "claude"}, project_id="proj-a")

    def test_filter_by_event_type(self) -> None:
        client = _make_client()
        self._seed_annotations(client)
        results = client.get_annotations(
            "deploy",
            _dt_offset(-60),
            _dt_offset(60),
        )
        assert len(results) == 2
        assert all(a.event_type == "deploy" for a in results)

    def test_wildcard_event_type_returns_all(self) -> None:
        client = _make_client()
        self._seed_annotations(client)
        results = client.get_annotations("*", _dt_offset(-60), _dt_offset(60))
        assert len(results) == 3

    def test_filter_by_project_id(self) -> None:
        client = _make_client()
        self._seed_annotations(client)
        results = client.get_annotations("*", _dt_offset(-60), _dt_offset(60), project_id="proj-a")
        assert len(results) == 2
        assert all(a.project_id == "proj-a" for a in results)

    def test_empty_store_returns_empty_list(self) -> None:
        client = _make_client()
        results = client.get_annotations("anything", _dt_offset(-60), _dt_offset(60))
        assert results == []

    def test_time_range_excludes_future_annotations(self) -> None:
        client = _make_client()
        client.add_annotation("ev", {}, project_id=_PROJECT)
        # Search only in the past — should find none because annotation is "now"
        results = client.get_annotations(
            "ev",
            _dt_offset(-120),
            _dt_offset(-1),  # ended 1 second ago
        )
        assert results == []

    def test_invalid_from_dt_raises(self) -> None:
        client = _make_client()
        with pytest.raises(SFObserveAnnotationError, match="datetime"):
            client.get_annotations("ev", "not-a-date", _now_iso())

    def test_invalid_to_dt_raises(self) -> None:
        client = _make_client()
        with pytest.raises(SFObserveAnnotationError, match="datetime"):
            client.get_annotations("ev", _now_iso(), "bad")

    def test_annotation_fields_populated(self) -> None:
        client = _make_client()
        client.add_annotation("deploy", {"model": "gpt-4o"}, project_id=_PROJECT)
        results = client.get_annotations("deploy", _dt_offset(-60), _dt_offset(60))
        assert len(results) == 1
        ann = results[0]
        assert ann.event_type == "deploy"
        assert ann.payload == {"model": "gpt-4o"}
        assert ann.project_id == _PROJECT
        uuid.UUID(ann.annotation_id)


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_initial_status_is_ok(self) -> None:
        client = _make_client()
        status = client.get_status()
        assert status.status == "ok"
        assert status.healthy is True
        assert status.span_count == 0
        assert status.annotation_count == 0
        assert status.export_count == 0
        assert status.last_export_at is None

    def test_status_returns_observe_status_info(self) -> None:
        client = _make_client()
        status = client.get_status()
        assert isinstance(status, ObserveStatusInfo)

    def test_backend_reflected_in_status(self) -> None:
        client = _make_client()
        assert client.get_status().backend == "local"

    def test_sampler_strategy_reflected(self) -> None:
        client = _make_client()
        assert client.get_status().sampler_strategy == "always_on"

    def test_span_count_increments_after_emit(self) -> None:
        client = _make_client()
        client.emit_span("op", {})
        assert client.get_status().span_count == 1

    def test_annotation_count_increments_after_add(self) -> None:
        client = _make_client()
        client.add_annotation("ev", {}, project_id=_PROJECT)
        assert client.get_status().annotation_count == 1

    def test_export_count_increments_after_export(self) -> None:
        client = _make_client()
        client.export_spans([])
        assert client.get_status().export_count == 1

    def test_last_export_at_updated(self) -> None:
        client = _make_client()
        before = datetime.now(timezone.utc)
        client.export_spans([])
        last = client.get_status().last_export_at
        assert last is not None
        last_dt = datetime.fromisoformat(last)
        assert last_dt >= before


# ---------------------------------------------------------------------------
# OBS-043: health probes
# ---------------------------------------------------------------------------


class TestHealthProbes:
    def test_healthy_starts_true(self) -> None:
        client = _make_client()
        assert client.healthy is True

    def test_last_export_at_starts_none(self) -> None:
        client = _make_client()
        assert client.last_export_at is None

    def test_healthy_true_after_successful_export(self) -> None:
        client = _make_client()
        client.export_spans([])
        assert client.healthy is True

    def test_healthy_false_after_failed_export_no_fallback(self) -> None:
        client = _make_client(
            endpoint="https://dead.example.com", local_fallback_enabled=False
        )
        client._backend = "otlp"
        with patch("spanforge.sdk.observe._post_json", side_effect=SFObserveExportError("down")):
            with pytest.raises(SFObserveExportError):
                client.export_spans([{"name": "x"}])
        assert client.healthy is False


# ---------------------------------------------------------------------------
# Sampling strategies via emit_span
# ---------------------------------------------------------------------------


class TestSamplingStrategies:
    def test_always_off_suppresses_export(self) -> None:
        client = _make_client()
        client._sampler_strategy = SamplerStrategy.ALWAYS_OFF
        with patch.object(client, "export_spans") as mock_export:
            for _ in range(5):
                client.emit_span("op", {})
        mock_export.assert_not_called()

    def test_always_on_exports_every_span(self) -> None:
        client = _make_client()
        client._sampler_strategy = SamplerStrategy.ALWAYS_ON
        with patch.object(client, "export_spans", return_value=ExportResult(1, 0, "local", _now_iso())) as mock_export:
            for _ in range(3):
                client.emit_span("op", {})
        assert mock_export.call_count == 3

    def test_trace_id_ratio_zero_suppresses(self) -> None:
        client = _make_client()
        client._sampler_strategy = SamplerStrategy.TRACE_ID_RATIO
        client._sample_rate = 0.0
        with patch.object(client, "export_spans") as mock_export:
            client.emit_span("op", {})
        mock_export.assert_not_called()

    def test_trace_id_ratio_one_exports(self) -> None:
        client = _make_client()
        client._sampler_strategy = SamplerStrategy.TRACE_ID_RATIO
        client._sample_rate = 1.0
        with patch.object(
            client, "export_spans", return_value=ExportResult(1, 0, "local", _now_iso())
        ) as mock_export:
            client.emit_span("op", {})
        mock_export.assert_called_once()

    def test_parent_based_no_parent_samples(self) -> None:
        client = _make_client()
        client._sampler_strategy = SamplerStrategy.PARENT_BASED
        with patch.object(
            client, "export_spans", return_value=ExportResult(1, 0, "local", _now_iso())
        ) as mock_export:
            client.emit_span("op", {})  # no traceparent
        mock_export.assert_called_once()

    def test_parent_based_not_sampled_parent(self) -> None:
        client = _make_client()
        client._sampler_strategy = SamplerStrategy.PARENT_BASED
        parent_tp = make_traceparent(_generate_trace_id(), _generate_span_id(), sampled=False)
        with patch.object(client, "export_spans") as mock_export:
            client.emit_span("op", {"traceparent": parent_tp})
        mock_export.assert_not_called()


# ---------------------------------------------------------------------------
# Backend serialisation helpers
# ---------------------------------------------------------------------------


class TestBackendHelpers:
    def _sample_span(self) -> dict[str, object]:
        return {
            "name": "test.op",
            "traceId": _generate_trace_id(),
            "spanId": _generate_span_id(),
            "startTimeUnixNano": 1_000_000_000,
            "endTimeUnixNano": 1_001_000_000,
            "status": {"code": "STATUS_CODE_OK", "message": ""},
            "attributes": {"gen_ai.system": "openai"},
            "resource": {"attributes": {"service.name": "spanforge"}},
        }

    def test_span_to_dd_has_trace_id(self) -> None:
        dd = _span_to_dd(self._sample_span())
        assert "trace_id" in dd
        assert "span_id" in dd
        assert dd["name"] == "test.op"

    def test_span_to_dd_error_flag(self) -> None:
        span = self._sample_span()
        span["status"] = {"code": "STATUS_CODE_ERROR", "message": ""}  # type: ignore[assignment]
        dd = _span_to_dd(span)
        assert dd["error"] == 1

    def test_span_to_dd_success_flag(self) -> None:
        dd = _span_to_dd(self._sample_span())
        assert dd["error"] == 0

    def test_span_to_ecs_has_trace_id(self) -> None:
        ecs = _span_to_ecs(self._sample_span())
        assert "trace.id" in ecs
        assert "transaction.id" in ecs
        assert ecs["span.name"] == "test.op"

    def test_span_to_ecs_success_outcome(self) -> None:
        ecs = _span_to_ecs(self._sample_span())
        assert ecs["event.outcome"] == "success"

    def test_span_to_ecs_failure_outcome(self) -> None:
        span = self._sample_span()
        span["status"] = {"code": "STATUS_CODE_ERROR", "message": ""}  # type: ignore[assignment]
        ecs = _span_to_ecs(span)
        assert ecs["event.outcome"] == "failure"

    def test_span_to_ecs_timestamp_present(self) -> None:
        ecs = _span_to_ecs(self._sample_span())
        assert "@timestamp" in ecs


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_emit_span(self) -> None:
        client = _make_client()
        errors: list[Exception] = []

        def emit(_: int) -> None:
            try:
                client.emit_span("concurrent.op", {"gen_ai.system": "openai"})
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=emit, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []
        assert client.get_status().span_count == 50

    def test_concurrent_add_annotation(self) -> None:
        client = _make_client()
        ids: list[str] = []
        lock = threading.Lock()

        def add(_: int) -> None:
            aid = client.add_annotation("ev", {}, project_id=_PROJECT)
            with lock:
                ids.append(aid)

        threads = [threading.Thread(target=add, args=(i,)) for i in range(30)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert client.get_status().annotation_count == 30
        # All IDs must be unique
        assert len(set(ids)) == 30


# ---------------------------------------------------------------------------
# SDK singleton
# ---------------------------------------------------------------------------


class TestSDKSingleton:
    def test_sf_observe_is_sfobserveclient(self) -> None:
        from spanforge.sdk import sf_observe

        assert isinstance(sf_observe, SFObserveClient)

    def test_sf_observe_exported_in_all(self) -> None:
        import spanforge.sdk as sdk

        assert "sf_observe" in sdk.__all__

    def test_sfobserveclient_in_all(self) -> None:
        import spanforge.sdk as sdk

        assert "SFObserveClient" in sdk.__all__

    def test_phase6_exceptions_in_sdk_all(self) -> None:
        import spanforge.sdk as sdk

        for name in (
            "SFObserveError",
            "SFObserveExportError",
            "SFObserveEmitError",
            "SFObserveAnnotationError",
        ):
            assert name in sdk.__all__, f"{name} missing from spanforge.sdk.__all__"

    def test_phase6_types_in_sdk_all(self) -> None:
        import spanforge.sdk as sdk

        for name in ("ExportResult", "Annotation", "ObserveStatusInfo", "ReceiverConfig", "SamplerStrategy"):
            assert name in sdk.__all__, f"{name} missing from spanforge.sdk.__all__"


# ---------------------------------------------------------------------------
# configure() recreates sf_observe
# ---------------------------------------------------------------------------


class TestConfigure:
    def test_configure_recreates_sf_observe(self) -> None:
        import spanforge.sdk as sdk
        from spanforge.sdk import configure

        original = sdk.sf_observe
        configure(SFClientConfig(signing_key="new-key"))
        assert sdk.sf_observe is not original
        assert isinstance(sdk.sf_observe, SFObserveClient)
        # Restore
        configure(SFClientConfig())

    def test_configure_sf_observe_uses_new_config(self) -> None:
        import spanforge.sdk as sdk
        from spanforge.sdk import configure

        cfg = SFClientConfig(project_id="new-project-id")
        configure(cfg)
        assert sdk.sf_observe._config.project_id == "new-project-id"
        configure(SFClientConfig())


# ---------------------------------------------------------------------------
# SUPPORTED_BACKENDS constant
# ---------------------------------------------------------------------------


class TestSupportedBackends:
    def test_contains_expected_backends(self) -> None:
        expected = {"local", "otlp", "datadog", "grafana", "splunk", "elastic"}
        assert SUPPORTED_BACKENDS >= expected

    def test_is_frozenset(self) -> None:
        assert isinstance(SUPPORTED_BACKENDS, frozenset)


# ---------------------------------------------------------------------------
# _validate_http_url edge cases (lines 182, 202, 204)
# ---------------------------------------------------------------------------


class TestValidateHttpUrl:
    def test_valid_https_url_passes(self) -> None:
        from spanforge.sdk.observe import _validate_http_url

        _validate_http_url("https://collector.example.com/v1/traces")  # no error

    def test_non_private_ip_passes(self) -> None:
        from spanforge.sdk.observe import _validate_http_url, _is_private_ip_literal

        # Public IP is not private
        assert _is_private_ip_literal("8.8.8.8") is False
        _validate_http_url("https://8.8.8.8/v1/traces")  # no error

    def test_no_host_raises(self) -> None:
        from spanforge.sdk.observe import _validate_http_url

        with pytest.raises(ValueError, match="no host"):
            _validate_http_url("https:///no-host")

    def test_private_ip_blocked_by_default(self) -> None:
        from spanforge.sdk.observe import _validate_http_url

        with pytest.raises(ValueError, match="private"):
            _validate_http_url("https://192.168.1.1/v1/traces")

    def test_private_ip_allowed_when_flag_set(self) -> None:
        from spanforge.sdk.observe import _validate_http_url

        _validate_http_url("https://192.168.1.1/v1/traces", allow_private_addresses=True)


# ---------------------------------------------------------------------------
# _post_json error branches (lines 428-441)
# ---------------------------------------------------------------------------


class TestPostJson:
    def test_http_error_raises_export_error(self) -> None:
        import urllib.error
        from spanforge.sdk.observe import _post_json

        with patch("spanforge.sdk.observe.urllib.request.urlopen") as mock_open:
            mock_open.side_effect = urllib.error.HTTPError(
                url="https://x.com", code=503, msg="Service Unavailable", hdrs=None, fp=None  # type: ignore[arg-type]
            )
            with pytest.raises(SFObserveExportError, match="503"):
                _post_json("https://x.com/v1/traces", {}, {})

    def test_os_error_raises_export_error(self) -> None:
        from spanforge.sdk.observe import _post_json

        with patch("spanforge.sdk.observe.urllib.request.urlopen") as mock_open:
            mock_open.side_effect = OSError("connection refused")
            with pytest.raises(SFObserveExportError, match="Network"):
                _post_json("https://x.com/v1/traces", {}, {})


# ---------------------------------------------------------------------------
# Non-local backends routing (lines 687, 694-726)
# ---------------------------------------------------------------------------


class TestBackendRouting:
    def _make_networked_client(self, backend: str) -> SFObserveClient:
        client = _make_client(endpoint="https://apm.example.com", local_fallback_enabled=False)
        client._backend = backend
        return client

    def test_otlp_backend_calls_v1_traces(self) -> None:
        client = self._make_networked_client("otlp")
        with patch("spanforge.sdk.observe._post_json") as mock_post:
            client.export_spans([{"name": "x"}])
        url = mock_post.call_args[0][0]
        assert url.endswith("/v1/traces")

    def test_datadog_backend_calls_dd_endpoint(self) -> None:
        client = self._make_networked_client("datadog")
        with patch("spanforge.sdk.observe._post_json") as mock_post:
            client.export_spans([{"name": "x", "traceId": "a" * 32, "spanId": "b" * 16}])
        url = mock_post.call_args[0][0]
        assert "/api/v0.2/traces" in url

    def test_grafana_backend_calls_push_endpoint(self) -> None:
        client = self._make_networked_client("grafana")
        with patch("spanforge.sdk.observe._post_json") as mock_post:
            client.export_spans([{"name": "x"}])
        url = mock_post.call_args[0][0]
        assert "/api/v1/push" in url

    def test_splunk_backend_calls_hec_endpoint(self) -> None:
        client = self._make_networked_client("splunk")
        with patch("spanforge.sdk.observe._post_json") as mock_post:
            client.export_spans([{"name": "x"}])
        url = mock_post.call_args[0][0]
        assert "/services/collector" in url

    def test_elastic_backend_calls_bulk_endpoint(self) -> None:
        client = self._make_networked_client("elastic")
        span = _build_otel_span("test", {}, _generate_trace_id(), _generate_span_id())
        with patch("spanforge.sdk.observe._post_json") as mock_post:
            client.export_spans([span])
        url = mock_post.call_args[0][0]
        assert "/_bulk" in url

    def test_unknown_backend_in_do_export_falls_back_to_buffer(self) -> None:
        client = _make_client()
        client._backend = "unknown_runtime_backend"
        # Should not raise; falls back to local buffer
        result = client.export_spans([{"name": "x"}])
        assert result.exported_count == 1


# ---------------------------------------------------------------------------
# get_annotations: corrupt created_at branch (lines 899-900)
# ---------------------------------------------------------------------------


class TestGetAnnotationsEdgeCases:
    def test_annotation_with_invalid_created_at_skipped(self) -> None:
        from spanforge.sdk._types import Annotation

        client = _make_client()
        # Directly inject a corrupt annotation
        bad_ann = Annotation(
            annotation_id="x",
            event_type="ev",
            payload={},
            project_id=_PROJECT,
            created_at="not-a-datetime",
        )
        with client._annotations_lock:
            client._annotations.append(bad_ann)

        # Should not raise; the bad annotation is skipped
        results = client.get_annotations("ev", _dt_offset(-60), _dt_offset(60))
        assert all(a.annotation_id != "x" for a in results)


# ---------------------------------------------------------------------------
# Unknown backend falls back to local
# ---------------------------------------------------------------------------


class TestUnknownBackend:
    def test_unknown_env_backend_defaults_to_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_OBSERVE_BACKEND", "unknown_backend")
        client = _make_client()
        assert client._backend == "local"

    def test_unknown_sampler_defaults_to_always_on(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_OBSERVE_SAMPLER", "bogus_strategy")
        client = _make_client()
        assert client._sampler_strategy == SamplerStrategy.ALWAYS_ON

    def test_invalid_sample_rate_defaults_to_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_OBSERVE_SAMPLE_RATE", "not-a-float")
        client = _make_client()
        assert client._sample_rate == 1.0

    def test_sample_rate_clamped_to_range(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_OBSERVE_SAMPLE_RATE", "2.5")
        client = _make_client()
        assert client._sample_rate == 1.0

    def test_negative_sample_rate_clamped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_OBSERVE_SAMPLE_RATE", "-0.5")
        client = _make_client()
        assert client._sample_rate == 0.0
