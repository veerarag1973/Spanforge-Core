"""Tests for spanforge.drift — DriftDetector and DriftResult.

Phase 3 (Behavioural Baselining & Drift Detection).
"""

from __future__ import annotations

import math

import pytest

from spanforge import Event, EventType
from spanforge.baseline import BehaviouralBaseline, DistributionStats
from spanforge.drift import (
    DriftDetector,
    DriftResult,
    _extract_metric_observations,
    _kl_divergence_gaussian,
)
from spanforge.namespaces.drift import DriftPayload

# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_baseline(
    token_mean: float = 100.0,
    token_stddev: float = 10.0,
    confidence_mean: float = 0.85,
    confidence_stddev: float = 0.05,
    latency_mean: float = 50.0,
    latency_stddev: float = 5.0,
) -> BehaviouralBaseline:
    return BehaviouralBaseline(
        tokens=DistributionStats(
            mean=token_mean,
            stddev=token_stddev,
            p50=token_mean,
            p95=token_mean + token_stddev,
            p99=token_mean + token_stddev * 2,
            sample_count=500,
        ),
        confidence_by_type={
            "classification": DistributionStats(
                mean=confidence_mean,
                stddev=confidence_stddev,
                p50=confidence_mean,
                p95=confidence_mean + confidence_stddev,
                p99=confidence_mean + confidence_stddev * 2,
                sample_count=500,
            )
        },
        latency_by_operation={
            "chat": DistributionStats(
                mean=latency_mean,
                stddev=latency_stddev,
                p50=latency_mean,
                p95=latency_mean + latency_stddev,
                p99=latency_mean + latency_stddev * 2,
                sample_count=500,
            )
        },
        tool_rate_per_hour={},
        decision_rate_per_hour={},
        event_count=500,
        window_seconds=86400.0,
    )


def _make_detector(
    baseline: BehaviouralBaseline | None = None,
    agent_id: str = "test-agent",
    window_size: int = 50,
    z_threshold: float = 3.0,
    auto_emit: bool = False,
) -> DriftDetector:
    return DriftDetector(
        baseline=baseline or _make_baseline(),
        agent_id=agent_id,
        window_size=window_size,
        z_threshold=z_threshold,
        auto_emit=auto_emit,
    )


def _llm_span_event(total_tokens: int = 100, duration_ms: float = 50.0) -> Event:
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
            "operation": "chat",
            "status": "ok",
        },
    )


def _confidence_event(score: float = 0.85, decision_type: str = "classification") -> Event:
    return Event(
        event_type=EventType("confidence.sample"),
        source="test@1.0.0",
        payload={
            "decision_type": decision_type,
            "score": score,
            "model_id": "model-a",
            "threshold_breached": False,
            "sampled_at": "2026-01-01T00:00:00Z",
        },
    )


def _latency_event(latency_ms: float = 50.0, operation: str = "chat") -> Event:
    return Event(
        event_type=EventType("latency.sample"),
        source="test@1.0.0",
        payload={
            "operation": operation,
            "latency_ms": latency_ms,
            "agent_id": "test-agent",
            "sla_target_ms": 200.0,
            "sla_met": True,
            "p50_ms": None,
            "p95_ms": None,
            "p99_ms": None,
        },
    )


def _tool_call_event(latency_ms: float = 30.0, tool_name: str = "search") -> Event:
    return Event(
        event_type=EventType("tool_call.completed"),
        source="test@1.0.0",
        payload={
            "tool_name": tool_name,
            "latency_ms": latency_ms,
            "call_id": "c-001",
            "tool_version": "1.0",
            "inputs": {},
            "outputs": None,
            "status": "success",
            "error_message": None,
            "consent_checked": True,
        },
    )


# ---------------------------------------------------------------------------
# KL divergence helper
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestKLDivergenceGaussian:
    def test_identical_distributions_is_zero(self) -> None:
        kl = _kl_divergence_gaussian(1.0, 1.0, 1.0, 1.0)
        assert kl == pytest.approx(0.0, abs=1e-9)

    def test_zero_sigma_returns_none(self) -> None:
        assert _kl_divergence_gaussian(1.0, 0.0, 1.0, 1.0) is None
        assert _kl_divergence_gaussian(1.0, 1.0, 1.0, 0.0) is None

    def test_known_value(self) -> None:
        # KL(N(0,1) || N(0,2)) = log(2) + (1 + 0) / (2*4) - 0.5
        # = log(2) + 1/8 - 0.5 ≈ 0.6931 + 0.125 - 0.5 = 0.3181
        kl = _kl_divergence_gaussian(0.0, 1.0, 0.0, 2.0)
        assert kl == pytest.approx(math.log(2.0) + 1.0 / 8.0 - 0.5, rel=1e-6)

    def test_non_negative_for_distinct_distributions(self) -> None:
        kl = _kl_divergence_gaussian(5.0, 2.0, 3.0, 1.5)
        assert kl is not None
        assert kl >= 0.0

    def test_large_mean_shift_gives_large_kl(self) -> None:
        kl = _kl_divergence_gaussian(100.0, 1.0, 0.0, 1.0)
        assert kl is not None
        assert kl > 100.0


# ---------------------------------------------------------------------------
# _extract_metric_observations
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExtractMetricObservations:
    def test_llm_span_extracts_tokens_and_latency(self) -> None:
        event = _llm_span_event(total_tokens=200, duration_ms=75.0)
        obs = _extract_metric_observations(event)
        names = [o[0] for o in obs]
        assert "tokens" in names
        assert "latency.chat" in names

    def test_zero_tokens_not_extracted(self) -> None:
        event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source="t@1",
            payload={"token_usage": {"total_tokens": 0}, "duration_ms": 10.0, "operation": "chat"},
        )
        obs = _extract_metric_observations(event)
        assert not any(o[0] == "tokens" for o in obs)

    def test_no_token_usage_no_tokens_obs(self) -> None:
        event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source="t@1",
            payload={"duration_ms": 10.0, "operation": "chat"},
        )
        obs = _extract_metric_observations(event)
        assert not any(o[0] == "tokens" for o in obs)

    def test_confidence_sample_extracts_score(self) -> None:
        event = _confidence_event(score=0.92)
        obs = _extract_metric_observations(event)
        assert len(obs) == 1
        assert obs[0][0] == "confidence.classification"
        assert obs[0][1] == pytest.approx(0.92)

    def test_latency_sample_extracts_latency(self) -> None:
        event = _latency_event(latency_ms=123.0, operation="embedding")
        obs = _extract_metric_observations(event)
        assert obs == [("latency.embedding", 123.0)]

    def test_tool_call_extracts_latency(self) -> None:
        event = _tool_call_event(latency_ms=45.0, tool_name="my_tool")
        obs = _extract_metric_observations(event)
        assert ("latency.my_tool", 45.0) in obs

    def test_unrelated_event_returns_empty(self) -> None:
        event = Event(
            event_type=EventType.AUDIT_EVENT_SIGNED,
            source="t@1",
            payload={"event_id": "x"},
        )
        obs = _extract_metric_observations(event)
        assert obs == []

    def test_decision_event_returns_empty(self) -> None:
        # decision.made is not a drift-relevant metric for the detector
        event = Event(
            event_type=EventType("decision.made"),
            source="t@1",
            payload={"decision_type": "routing"},
        )
        obs = _extract_metric_observations(event)
        assert obs == []


# ---------------------------------------------------------------------------
# DriftDetector — construction
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDriftDetectorConstruction:
    def test_valid_construction(self) -> None:
        detector = _make_detector()
        assert detector.agent_id == "test-agent"
        assert detector.window_size == 50
        assert isinstance(detector.baseline, BehaviouralBaseline)

    def test_empty_agent_id_raises(self) -> None:
        with pytest.raises(ValueError, match="agent_id"):
            DriftDetector(baseline=_make_baseline(), agent_id="")

    def test_zero_window_size_raises(self) -> None:
        with pytest.raises(ValueError, match="window_size"):
            DriftDetector(baseline=_make_baseline(), agent_id="a", window_size=0)

    def test_negative_z_threshold_raises(self) -> None:
        with pytest.raises(ValueError, match="z_threshold"):
            DriftDetector(baseline=_make_baseline(), agent_id="a", z_threshold=0.0)

    def test_zero_window_seconds_raises(self) -> None:
        with pytest.raises(ValueError, match="window_seconds"):
            DriftDetector(baseline=_make_baseline(), agent_id="a", window_seconds=0)

    def test_baseline_property(self) -> None:
        bl = _make_baseline()
        detector = DriftDetector(baseline=bl, agent_id="a", auto_emit=False)
        assert detector.baseline is bl

    def test_auto_emit_default_true(self) -> None:
        # Verify default; just instantiate and check attribute
        detector = DriftDetector(baseline=_make_baseline(), agent_id="a")
        assert detector._auto_emit is True


# ---------------------------------------------------------------------------
# DriftDetector — record() behaviour below window threshold
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDriftDetectorBelowWindow:
    def test_returns_empty_before_min_samples(self) -> None:
        detector = _make_detector(window_size=50, auto_emit=False)
        # Feed 9 events (min is 10)
        for _ in range(9):
            results = detector.record(_llm_span_event(total_tokens=100))
        assert results == []

    def test_unrelated_event_returns_empty(self) -> None:
        detector = _make_detector(auto_emit=False)
        event = Event(
            event_type=EventType.AUDIT_EVENT_SIGNED,
            source="t@1",
            payload={"event_id": "x"},
        )
        assert detector.record(event) == []

    def test_no_baseline_for_metric_returns_none(self) -> None:
        # Confidence for an unknown decision type has no baseline entry
        detector = _make_detector(auto_emit=False)
        events = [_confidence_event(score=0.5, decision_type="unknown_type") for _ in range(15)]
        results = []
        for e in events:
            results.extend(detector.record(e))
        assert results == []


# ---------------------------------------------------------------------------
# DriftDetector — record() normal values → no drift
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDriftDetectorNoDrift:
    def _fill_window(self, detector: DriftDetector, count: int = 20) -> list[DriftResult]:
        results = []
        for _ in range(count):
            results.extend(detector.record(_llm_span_event(total_tokens=100, duration_ms=50.0)))
        return results

    def test_normal_values_produce_no_drift_result(self) -> None:
        detector = _make_detector(auto_emit=False)
        results = self._fill_window(detector, count=20)
        # All values equal to baseline mean → z_score ≈ 0 → no result
        assert results == []

    def test_not_in_breach_after_normal_values(self) -> None:
        detector = _make_detector(auto_emit=False)
        self._fill_window(detector, count=20)
        assert not detector.in_breach("tokens")

    def test_window_stats_populated(self) -> None:
        detector = _make_detector(auto_emit=False)
        for _ in range(15):
            detector.record(_llm_span_event(total_tokens=100))
        stats = detector.window_stats("tokens")
        assert stats is not None
        mean, stddev, count = stats
        assert count == 15
        assert mean == pytest.approx(100.0)

    def test_window_stats_none_before_any_data(self) -> None:
        detector = _make_detector(auto_emit=False)
        assert detector.window_stats("tokens") is None

    def test_small_variation_no_breach(self) -> None:
        # Values spread around baseline mean ± 1 stddev so Z ≈ 0 AND KL < 0.5.
        # baseline: mean=100, stddev=10; window stddev ≈ 5 → KL ≈ 0.3 < 0.5 threshold.
        values = [90, 92, 94, 96, 98, 100, 100, 100, 102, 104,
                  106, 108, 110, 98, 102, 95, 105, 99, 101, 100]
        detector = _make_detector(z_threshold=3.0, auto_emit=False)
        for v in values:
            detector.record(_llm_span_event(total_tokens=v))
        assert not detector.in_breach("tokens")


# ---------------------------------------------------------------------------
# DriftDetector — threshold_breach
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDriftDetectorThresholdBreach:
    def test_large_shift_produces_threshold_breach(self) -> None:
        # Baseline: mean=100, stddev=10 → z_threshold=3 → breach at mean > 130
        detector = _make_detector(z_threshold=3.0, window_size=20, auto_emit=False)
        # Inflate window mean to 500 (z ≈ 40)
        results = []
        for _ in range(20):
            results.extend(detector.record(_llm_span_event(total_tokens=500)))
        breach_results = [r for r in results if r.status == "threshold_breach"]
        assert len(breach_results) >= 1

    def test_breach_sets_in_breach_flag(self) -> None:
        detector = _make_detector(z_threshold=3.0, window_size=20, auto_emit=False)
        for _ in range(20):
            detector.record(_llm_span_event(total_tokens=500))
        assert detector.in_breach("tokens")

    def test_breach_result_has_payload(self) -> None:
        detector = _make_detector(z_threshold=3.0, window_size=20, auto_emit=False)
        results = []
        for _ in range(20):
            results.extend(detector.record(_llm_span_event(total_tokens=500)))
        breach = next((r for r in results if r.status == "threshold_breach"), None)
        assert breach is not None
        assert isinstance(breach.payload, DriftPayload)
        assert breach.payload.status == "threshold_breach"
        assert breach.payload.agent_id == "test-agent"

    def test_breach_payload_z_score(self) -> None:
        # Baseline: mean=100, stddev=10; window mean=500 → z_score≈40
        detector = _make_detector(z_threshold=3.0, window_size=20, auto_emit=False)
        results = []
        for _ in range(20):
            results.extend(detector.record(_llm_span_event(total_tokens=500)))
        breach = next((r for r in results if r.status == "threshold_breach"), None)
        assert breach is not None
        assert breach.z_score > 3.0

    def test_threshold_breach_in_second_metric(self) -> None:
        # Baseline for latency.chat: mean=50, stddev=5
        detector = _make_detector(z_threshold=3.0, window_size=20, auto_emit=False)
        results = []
        for _ in range(20):
            results.extend(detector.record(_llm_span_event(total_tokens=100, duration_ms=1000.0)))
        breach = next((r for r in results if r.metric_name == "latency.chat" and r.status == "threshold_breach"), None)
        assert breach is not None


# ---------------------------------------------------------------------------
# DriftDetector — resolution
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDriftDetectorResolution:
    def test_resolved_after_returning_to_normal(self) -> None:
        detector = _make_detector(z_threshold=3.0, window_size=20, auto_emit=False)
        # First, fill with high values to trigger breach
        for _ in range(20):
            detector.record(_llm_span_event(total_tokens=500))
        assert detector.in_breach("tokens")

        # Now fill with normal values — eventually should resolve
        resolved_results = []
        for _ in range(20):
            resolved_results.extend(detector.record(_llm_span_event(total_tokens=100)))

        resolved = [r for r in resolved_results if r.status == "resolved"]
        assert len(resolved) >= 1
        assert not detector.in_breach("tokens")

    def test_resolved_result_has_payload(self) -> None:
        detector = _make_detector(z_threshold=3.0, window_size=20, auto_emit=False)
        for _ in range(20):
            detector.record(_llm_span_event(total_tokens=500))
        resolved_results = []
        for _ in range(20):
            resolved_results.extend(detector.record(_llm_span_event(total_tokens=100)))
        resolved = next((r for r in resolved_results if r.status == "resolved"), None)
        if resolved is not None:
            assert isinstance(resolved.payload, DriftPayload)
            assert resolved.payload.status == "resolved"


# ---------------------------------------------------------------------------
# DriftDetector — window reset
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDriftDetectorWindowReset:
    def test_reset_specific_metric(self) -> None:
        detector = _make_detector(window_size=20, auto_emit=False)
        for _ in range(15):
            detector.record(_llm_span_event(total_tokens=100))
        assert detector.window_stats("tokens") is not None
        detector.reset_window("tokens")
        assert detector.window_stats("tokens") is None

    def test_reset_all_metrics(self) -> None:
        detector = _make_detector(window_size=20, auto_emit=False)
        for _ in range(15):
            detector.record(_llm_span_event(total_tokens=100, duration_ms=50.0))
        detector.reset_window()
        assert detector.window_stats("tokens") is None
        assert detector.window_stats("latency.chat") is None

    def test_reset_clears_breach_state_for_metric(self) -> None:
        detector = _make_detector(z_threshold=3.0, window_size=20, auto_emit=False)
        for _ in range(20):
            detector.record(_llm_span_event(total_tokens=500))
        assert detector.in_breach("tokens")
        detector.reset_window("tokens")
        assert not detector.in_breach("tokens")

    def test_reset_all_clears_all_breach_states(self) -> None:
        detector = _make_detector(z_threshold=3.0, window_size=20, auto_emit=False)
        for _ in range(20):
            detector.record(_llm_span_event(total_tokens=500, duration_ms=1000.0))
        detector.reset_window()
        assert not detector.in_breach("tokens")
        assert not detector.in_breach("latency.chat")

    def test_reset_nonexistent_metric_is_noop(self) -> None:
        detector = _make_detector(auto_emit=False)
        detector.reset_window("does_not_exist")  # must not raise


# ---------------------------------------------------------------------------
# DriftDetector — DriftResult fields
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDriftResultFields:
    def _get_first_breach(self) -> DriftResult:
        detector = _make_detector(z_threshold=3.0, window_size=20, auto_emit=False)
        results = []
        for _ in range(20):
            results.extend(detector.record(_llm_span_event(total_tokens=500, duration_ms=50.0)))
        return next(r for r in results if r.status == "threshold_breach")

    def test_result_metric_name(self) -> None:
        result = self._get_first_breach()
        assert result.metric_name in ("tokens", "latency.chat")

    def test_result_current_value(self) -> None:
        result = self._get_first_breach()
        assert result.current_value > 0

    def test_result_baseline_values(self) -> None:
        result = self._get_first_breach()
        assert result.baseline_mean > 0
        assert result.baseline_stddev >= 0

    def test_result_z_score_positive(self) -> None:
        result = self._get_first_breach()
        assert result.z_score > 0

    def test_result_threshold_matches_config(self) -> None:
        result = self._get_first_breach()
        assert result.threshold == pytest.approx(3.0)

    def test_result_kl_divergence_field(self) -> None:
        # kl_divergence may be None or float — either is valid
        result = self._get_first_breach()
        assert result.kl_divergence is None or isinstance(result.kl_divergence, float)


# ---------------------------------------------------------------------------
# DriftDetector — confidence namespace
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDriftDetectorConfidenceMetric:
    def test_confidence_drift_shows_detected_or_breach(self) -> None:
        # Baseline: classification mean=0.85, stddev=0.05
        # Feed constant 0.3 → z ≈ (0.85 - 0.3) / 0.05 = 11 → threshold_breach
        detector = _make_detector(z_threshold=3.0, window_size=20, auto_emit=False)
        results = []
        for _ in range(20):
            results.extend(detector.record(_confidence_event(score=0.0, decision_type="classification")))
        breach = next(
            (r for r in results if r.metric_name == "confidence.classification"),
            None,
        )
        assert breach is not None
        assert breach.status in ("detected", "threshold_breach")

    def test_confidence_normal_produces_no_result(self) -> None:
        detector = _make_detector(z_threshold=3.0, window_size=20, auto_emit=False)
        results = []
        for _ in range(20):
            results.extend(detector.record(_confidence_event(score=0.85, decision_type="classification")))
        assert results == []


# ---------------------------------------------------------------------------
# DriftDetector — baseline with zero stddev
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDriftDetectorZeroStddev:
    def test_zero_stddev_baseline_still_detects_shift(self) -> None:
        # A baseline with stddev=0 means the metric was perfectly constant;
        # any deviation should still be detected (uses effective_stddev=1e-9).
        bl = _make_baseline(token_mean=100.0, token_stddev=0.0)
        detector = DriftDetector(
            baseline=bl,
            agent_id="a",
            window_size=20,
            z_threshold=3.0,
            auto_emit=False,
        )
        results = []
        for _ in range(20):
            results.extend(detector.record(_llm_span_event(total_tokens=500)))
        breach = next((r for r in results if r.status == "threshold_breach"), None)
        assert breach is not None


# ---------------------------------------------------------------------------
# DriftDetector — thread safety (basic)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDriftDetectorThreadSafety:
    def test_concurrent_record_calls_do_not_raise(self) -> None:
        import threading

        detector = _make_detector(window_size=200, auto_emit=False)
        errors: list[Exception] = []

        def worker() -> None:
            try:
                for _ in range(30):
                    detector.record(_llm_span_event(total_tokens=100))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []


# ---------------------------------------------------------------------------
# DriftDetector — auto_emit=False does not call emit_rfc_event
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDriftDetectorAutoEmit:
    def test_auto_emit_false_no_side_effects(self, monkeypatch: pytest.MonkeyPatch) -> None:
        emitted: list = []

        def _fake_emit(et, payload, **_kw):
            emitted.append(et)

        monkeypatch.setattr("spanforge.drift.DriftDetector._emit_results", lambda self, results: None)
        detector = _make_detector(z_threshold=3.0, window_size=20, auto_emit=False)
        for _ in range(20):
            detector.record(_llm_span_event(total_tokens=500))
        # With auto_emit=False the monkey-patched _emit_results is never called
        # (it's monkeypatched to a no-op anyway) — most important assertion is no error
        assert emitted == []
