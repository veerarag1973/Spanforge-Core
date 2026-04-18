"""Tests for spanforge.baseline — BehaviouralBaseline and DistributionStats.

Phase 3 (Behavioural Baselining & Drift Detection).
"""

from __future__ import annotations

import json
import statistics
from typing import TYPE_CHECKING

import pytest

from spanforge import Event, EventType
from spanforge.baseline import BehaviouralBaseline, DistributionStats, _percentile

if TYPE_CHECKING:
    import pathlib

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _llm_span_event(
    total_tokens: int = 100,
    duration_ms: float = 50.0,
    operation: str = "chat",
) -> Event:
    return Event(
        event_type=EventType.TRACE_SPAN_COMPLETED,
        source="test@1.0.0",
        payload={
            "token_usage": {
                "input_tokens": total_tokens // 2,
                "output_tokens": total_tokens // 2,
                "total_tokens": total_tokens,
            },
            "duration_ms": duration_ms,
            "operation": operation,
            "status": "ok",
        },
    )


def _confidence_event(decision_type: str = "classification", score: float = 0.9) -> Event:
    return Event(
        event_type=EventType("confidence.sample"),
        source="test@1.0.0",
        payload={
            "decision_type": decision_type,
            "score": score,
            "model_id": "model-a",
            "baseline_mean": None,
            "baseline_stddev": None,
            "z_score": None,
            "threshold_breached": False,
            "sampled_at": "2026-01-01T00:00:00Z",
        },
    )


def _tool_call_event(tool_name: str = "search", latency_ms: float = 30.0) -> Event:
    return Event(
        event_type=EventType("tool_call.completed"),
        source="test@1.0.0",
        payload={
            "tool_name": tool_name,
            "latency_ms": latency_ms,
            "call_id": "call-001",
            "tool_version": "1.0",
            "inputs": {},
            "outputs": None,
            "status": "success",
            "error_message": None,
            "consent_checked": True,
        },
    )


def _decision_event(decision_type: str = "routing") -> Event:
    return Event(
        event_type=EventType("decision.made"),
        source="test@1.0.0",
        payload={
            "decision_type": decision_type,
            "decision_id": "dec-001",
            "agent_id": "agent-x",
            "input_summary": "input",
            "output_summary": "output",
            "confidence": 0.85,
            "latency_ms": 20.0,
            "decision_drivers": [],
            "rationale_hash": "abc123",
            "actor": None,
        },
    )


def _latency_event(operation: str = "embedding", latency_ms: float = 15.0) -> Event:
    return Event(
        event_type=EventType("latency.sample"),
        source="test@1.0.0",
        payload={
            "operation": operation,
            "latency_ms": latency_ms,
            "agent_id": "agent-x",
            "sla_target_ms": 100.0,
            "sla_met": True,
            "p50_ms": None,
            "p95_ms": None,
            "p99_ms": None,
        },
    )


# ---------------------------------------------------------------------------
# _percentile helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPercentileHelper:
    def test_empty(self) -> None:
        assert _percentile([], 50) == 0.0

    def test_single(self) -> None:
        assert _percentile([5.0], 50) == 5.0
        assert _percentile([5.0], 99) == 5.0

    def test_two_values_median(self) -> None:
        assert _percentile([1.0, 3.0], 50) == pytest.approx(2.0)

    def test_p50_matches_median(self) -> None:
        data = sorted([10.0, 20.0, 30.0, 40.0, 50.0])
        assert _percentile(data, 50) == pytest.approx(30.0)

    def test_p100_is_max(self) -> None:
        data = sorted([1.0, 2.0, 3.0])
        assert _percentile(data, 100) == 3.0


# ---------------------------------------------------------------------------
# DistributionStats
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDistributionStats:
    def test_from_samples_empty(self) -> None:
        d = DistributionStats.from_samples([])
        assert d.mean == 0.0
        assert d.stddev == 0.0
        assert d.p50 == 0.0
        assert d.p95 == 0.0
        assert d.p99 == 0.0
        assert d.sample_count == 0

    def test_from_samples_single(self) -> None:
        d = DistributionStats.from_samples([42.0])
        assert d.mean == 42.0
        assert d.stddev == 0.0
        assert d.p50 == 42.0
        assert d.sample_count == 1

    def test_from_samples_multi(self) -> None:
        samples = [10.0, 20.0, 30.0, 40.0, 50.0]
        d = DistributionStats.from_samples(samples)
        assert d.mean == pytest.approx(30.0)
        assert d.stddev == pytest.approx(statistics.stdev(samples))
        assert d.sample_count == 5
        assert d.p50 == pytest.approx(30.0)
        assert d.p95 > d.p50

    def test_stddev_zero_for_single_sample(self) -> None:
        d = DistributionStats.from_samples([100.0])
        assert d.stddev == 0.0

    def test_percentiles_ordered(self) -> None:
        samples = list(range(1, 101))
        d = DistributionStats.from_samples([float(x) for x in samples])
        assert d.p50 <= d.p95 <= d.p99

    def test_to_dict_from_dict_round_trip(self) -> None:
        d = DistributionStats.from_samples([1.0, 2.0, 3.0, 4.0, 5.0])
        restored = DistributionStats.from_dict(d.to_dict())
        assert restored == d

    def test_to_dict_keys(self) -> None:
        d = DistributionStats.from_samples([1.0, 2.0])
        keys = set(d.to_dict())
        assert keys == {"mean", "stddev", "p50", "p95", "p99", "sample_count"}

    def test_from_dict_type_coercions(self) -> None:
        raw = {"mean": "5.5", "stddev": "1.0", "p50": "5.0", "p95": "7.0", "p99": "9.0", "sample_count": "10"}
        d = DistributionStats.from_dict(raw)
        assert isinstance(d.mean, float)
        assert isinstance(d.sample_count, int)


# ---------------------------------------------------------------------------
# BehaviouralBaseline.from_events — empty / minimal
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBehaviouralBaselineFromEventsEmpty:
    def test_empty_iterable_returns_default_baseline(self) -> None:
        bl = BehaviouralBaseline.from_events([])
        assert bl.event_count == 0
        assert bl.tokens.sample_count == 0
        assert bl.confidence_by_type == {}
        assert bl.latency_by_operation == {}
        assert bl.tool_rate_per_hour == {}
        assert bl.decision_rate_per_hour == {}

    def test_recorded_at_is_set(self) -> None:
        bl = BehaviouralBaseline.from_events([])
        assert bl.recorded_at.endswith("Z")
        assert "T" in bl.recorded_at

    def test_window_seconds_stored(self) -> None:
        bl = BehaviouralBaseline.from_events([], window_seconds=7200.0)
        assert bl.window_seconds == 7200.0

    def test_unrelated_events_are_skipped(self) -> None:
        # Events that don't carry drift-relevant metrics should be silently ignored
        events = [
            Event(event_type=EventType.TRACE_AGENT_COMPLETED, source="s@1", payload={"duration_ms": 100.0}),
            Event(event_type=EventType.AUDIT_EVENT_SIGNED, source="s@1", payload={"event_id": "x", "signer_id": "y"}),
        ]
        bl = BehaviouralBaseline.from_events(events)
        assert bl.event_count == 2
        assert bl.tokens.sample_count == 0


# ---------------------------------------------------------------------------
# BehaviouralBaseline.from_events — token events
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBehaviouralBaselineTokens:
    def test_single_token_event(self) -> None:
        events = [_llm_span_event(total_tokens=200)]
        bl = BehaviouralBaseline.from_events(events)
        assert bl.tokens.sample_count == 1
        assert bl.tokens.mean == 200.0

    def test_multiple_token_events(self) -> None:
        events = [_llm_span_event(total_tokens=t) for t in [100, 200, 300, 400, 500]]
        bl = BehaviouralBaseline.from_events(events)
        assert bl.tokens.sample_count == 5
        assert bl.tokens.mean == pytest.approx(300.0)

    def test_zero_tokens_excluded(self) -> None:
        event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source="t@1",
            payload={"token_usage": {"total_tokens": 0}, "duration_ms": 10.0, "operation": "chat", "status": "ok"},
        )
        bl = BehaviouralBaseline.from_events([event])
        assert bl.tokens.sample_count == 0

    def test_no_token_usage_field(self) -> None:
        event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source="t@1",
            payload={"duration_ms": 10.0, "operation": "chat", "status": "ok"},
        )
        bl = BehaviouralBaseline.from_events([event])
        assert bl.tokens.sample_count == 0

    def test_span_failed_also_counted(self) -> None:
        event = Event(
            event_type=EventType.TRACE_SPAN_FAILED,
            source="t@1",
            payload={"token_usage": {"total_tokens": 50}, "duration_ms": 5.0, "operation": "chat", "status": "error"},
        )
        bl = BehaviouralBaseline.from_events([event])
        assert bl.tokens.sample_count == 1

    def test_max_events_respected(self) -> None:
        events = [_llm_span_event(total_tokens=100) for _ in range(20)]
        bl = BehaviouralBaseline.from_events(events, max_events=10)
        assert bl.event_count == 10
        assert bl.tokens.sample_count == 10


# ---------------------------------------------------------------------------
# BehaviouralBaseline.from_events — latency
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBehaviouralBaselineLatency:
    def test_llm_span_latency_by_operation(self) -> None:
        events = [
            _llm_span_event(duration_ms=50.0, operation="chat"),
            _llm_span_event(duration_ms=80.0, operation="chat"),
            _llm_span_event(duration_ms=30.0, operation="embedding"),
        ]
        bl = BehaviouralBaseline.from_events(events)
        assert "chat" in bl.latency_by_operation
        assert bl.latency_by_operation["chat"].sample_count == 2
        assert bl.latency_by_operation["chat"].mean == pytest.approx(65.0)
        assert "embedding" in bl.latency_by_operation

    def test_tool_call_latency(self) -> None:
        events = [_tool_call_event(tool_name="search", latency_ms=30.0)]
        bl = BehaviouralBaseline.from_events(events)
        assert "search" in bl.latency_by_operation

    def test_latency_sample_event(self) -> None:
        events = [_latency_event(operation="embedding", latency_ms=15.0)]
        bl = BehaviouralBaseline.from_events(events)
        assert "embedding" in bl.latency_by_operation
        assert bl.latency_by_operation["embedding"].mean == 15.0


# ---------------------------------------------------------------------------
# BehaviouralBaseline.from_events — confidence
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBehaviouralBaselineConfidence:
    def test_confidence_grouped_by_type(self) -> None:
        events = [
            _confidence_event("classification", 0.9),
            _confidence_event("classification", 0.8),
            _confidence_event("routing", 0.7),
        ]
        bl = BehaviouralBaseline.from_events(events)
        assert "classification" in bl.confidence_by_type
        assert "routing" in bl.confidence_by_type
        assert bl.confidence_by_type["classification"].sample_count == 2
        assert bl.confidence_by_type["classification"].mean == pytest.approx(0.85)

    def test_missing_score_field_skipped(self) -> None:
        event = Event(
            event_type=EventType("confidence.sample"),
            source="t@1",
            payload={"decision_type": "routing"},  # no score
        )
        bl = BehaviouralBaseline.from_events([event])
        assert bl.confidence_by_type == {}


# ---------------------------------------------------------------------------
# BehaviouralBaseline.from_events — tool & decision rates
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBehaviouralBaselineRates:
    def test_tool_rate_per_hour(self) -> None:
        events = [_tool_call_event("search") for _ in range(5)]
        bl = BehaviouralBaseline.from_events(events, window_seconds=3600.0)
        # 5 calls in 1 hour window → 5.0 calls/h
        assert bl.tool_rate_per_hour["search"] == pytest.approx(5.0)

    def test_tool_rate_per_hour_half_window(self) -> None:
        events = [_tool_call_event("search") for _ in range(10)]
        bl = BehaviouralBaseline.from_events(events, window_seconds=1800.0)
        # 10 calls in 0.5 h → 20 calls/h
        assert bl.tool_rate_per_hour["search"] == pytest.approx(20.0)

    def test_decision_rate(self) -> None:
        events = [_decision_event("routing") for _ in range(3)]
        bl = BehaviouralBaseline.from_events(events, window_seconds=3600.0)
        assert bl.decision_rate_per_hour["routing"] == pytest.approx(3.0)

    def test_zero_window_seconds_no_division_error(self) -> None:
        # window_seconds=0 falls back to 1.0-hour denominator internally
        events = [_tool_call_event("search")]
        bl = BehaviouralBaseline.from_events(events, window_seconds=0.0)
        assert bl.tool_rate_per_hour["search"] > 0


# ---------------------------------------------------------------------------
# BehaviouralBaseline serialisation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBehaviouralBaselineSerialisation:
    def _make_baseline(self) -> BehaviouralBaseline:
        events = (
            [_llm_span_event(total_tokens=t, duration_ms=float(t)) for t in range(50, 200, 10)]
            + [_confidence_event("cls", float(s) / 10) for s in range(5, 10)]
            + [_tool_call_event("search", latency_ms=20.0)]
        )
        return BehaviouralBaseline.from_events(events)

    def test_to_json_produces_valid_json(self) -> None:
        bl = self._make_baseline()
        js = bl.to_json()
        parsed = json.loads(js)
        assert "tokens" in parsed

    def test_from_json_round_trip(self) -> None:
        bl = self._make_baseline()
        restored = BehaviouralBaseline.from_json(bl.to_json())
        assert restored.event_count == bl.event_count
        assert restored.tokens.mean == pytest.approx(bl.tokens.mean)
        assert restored.window_seconds == bl.window_seconds
        assert restored.recorded_at == bl.recorded_at

    def test_from_dict_confidence_and_latency(self) -> None:
        bl = self._make_baseline()
        d = bl.to_dict()
        restored = BehaviouralBaseline.from_dict(d)
        assert set(restored.confidence_by_type.keys()) == set(bl.confidence_by_type.keys())
        assert set(restored.latency_by_operation.keys()) == set(bl.latency_by_operation.keys())

    def test_save_and_load(self, tmp_path: pathlib.Path) -> None:
        bl = self._make_baseline()
        path = tmp_path / "baseline.json"
        bl.save(path)
        loaded = BehaviouralBaseline.load(path)
        assert loaded.event_count == bl.event_count
        assert loaded.tokens.mean == pytest.approx(bl.tokens.mean)

    def test_save_file_is_utf8_json(self, tmp_path: pathlib.Path) -> None:
        bl = BehaviouralBaseline.from_events([_llm_span_event()])
        path = tmp_path / "bl.json"
        bl.save(path)
        content = path.read_text(encoding="utf-8")
        parsed = json.loads(content)
        assert "tokens" in parsed

    def test_from_dict_missing_optional_keys(self) -> None:
        # Ensure from_dict is tolerant when optional keys are absent
        minimal = {"tokens": {"mean": 0.0, "stddev": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "sample_count": 0}}
        bl = BehaviouralBaseline.from_dict(minimal)
        assert bl.confidence_by_type == {}
        assert bl.tool_rate_per_hour == {}
        assert bl.event_count == 0
        assert bl.window_seconds == pytest.approx(86400.0)

    def test_to_dict_keys_complete(self) -> None:
        bl = BehaviouralBaseline.from_events([])
        d = bl.to_dict()
        expected = {
            "tokens", "confidence_by_type", "latency_by_operation",
            "tool_rate_per_hour", "decision_rate_per_hour",
            "event_count", "window_seconds", "recorded_at",
        }
        assert set(d.keys()) == expected


# ---------------------------------------------------------------------------
# Metrics aggregate() — drift fields
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMetricsAggregateDriftFields:
    def test_drift_incidents_zero_when_no_drift_events(self) -> None:
        from spanforge.metrics import aggregate

        events = [_llm_span_event(total_tokens=100) for _ in range(5)]
        summary = aggregate(events)
        assert summary.drift_incidents == 0

    def test_drift_incidents_counted(self) -> None:
        from spanforge.metrics import aggregate

        breach_event = Event(
            event_type=EventType("drift.threshold_breach"),
            source="t@1",
            payload={
                "metric_name": "tokens",
                "agent_id": "a",
                "current_value": 500.0,
                "baseline_mean": 100.0,
                "baseline_stddev": 10.0,
                "z_score": 40.0,
                "threshold": 3.0,
                "window_seconds": 3600,
                "status": "threshold_breach",
            },
        )
        summary = aggregate([breach_event, breach_event])
        assert summary.drift_incidents == 2

    def test_confidence_trend_empty_when_no_confidence_events(self) -> None:
        from spanforge.metrics import aggregate

        summary = aggregate([_llm_span_event()])
        assert summary.confidence_trend == []

    def test_confidence_trend_single_window(self) -> None:
        from spanforge.metrics import aggregate

        events = [_confidence_event("cls", 0.9) for _ in range(10)]
        summary = aggregate(events)
        assert len(summary.confidence_trend) == 1
        assert summary.confidence_trend[0] == pytest.approx(0.9)

    def test_confidence_trend_multiple_windows(self) -> None:
        from spanforge.metrics import aggregate

        events = [_confidence_event("cls", float(i) / 100) for i in range(150)]
        summary = aggregate(events)
        # 150 events / 50 per window = 3 windows
        assert len(summary.confidence_trend) == 3

    def test_baseline_deviation_pct_zero_without_confidence(self) -> None:
        from spanforge.metrics import aggregate

        summary = aggregate([_llm_span_event()])
        assert summary.baseline_deviation_pct == pytest.approx(0.0)

    def test_baseline_deviation_pct_computed(self) -> None:
        from spanforge.metrics import aggregate

        # Spread of 0.0 to 1.0 should give nonzero deviation
        events = [_confidence_event("cls", float(i) / 10) for i in range(2, 10)]
        summary = aggregate(events)
        assert summary.baseline_deviation_pct > 0.0

    def test_baseline_deviation_pct_zero_when_mean_is_zero(self) -> None:
        from spanforge.metrics import aggregate

        events = [
            Event(
                event_type=EventType("confidence.sample"),
                source="t@1",
                payload={"decision_type": "cls", "score": 0.0, "model_id": "m", "threshold_breached": False, "sampled_at": "2026-01-01T00:00:00Z"},
            )
            for _ in range(5)
        ]
        summary = aggregate(events)
        # mean is 0, so deviation_pct stays 0
        assert summary.baseline_deviation_pct == pytest.approx(0.0)
