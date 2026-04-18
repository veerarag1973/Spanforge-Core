"""Tests for spanforge.sampling — coverage for all sampler classes including ComplianceSampler (SF-16)."""

from __future__ import annotations

import types

import pytest

from spanforge.sampling import (
    AlwaysOffSampler,
    AlwaysOnSampler,
    ComplianceSampler,
    ParentBasedSampler,
    RatioSampler,
    RuleBasedSampler,
    TailBasedSampler,
    bypass_sampling,
)

# ---------------------------------------------------------------------------
# Helpers — lightweight stand-ins for Span / Event
# ---------------------------------------------------------------------------


def _make_span(
    trace_id: str | None = "abc123",
    parent_span_id: str | None = None,
    traceparent: str | None = None,
    status: str = "ok",
    duration_ms: float = 50.0,
    event_type: str | None = None,
    **attrs: object,
) -> types.SimpleNamespace:
    ns = types.SimpleNamespace(
        trace_id=trace_id,
        parent_span_id=parent_span_id,
        traceparent=traceparent,
        status=status,
        duration_ms=duration_ms,
        event_type=event_type,
    )
    for k, v in attrs.items():
        setattr(ns, k, v)
    return ns


CFG = None  # most samplers ignore cfg


# ---------------------------------------------------------------------------
# AlwaysOnSampler
# ---------------------------------------------------------------------------


class TestAlwaysOnSampler:
    def test_always_true(self) -> None:
        s = AlwaysOnSampler()
        assert s.should_sample(_make_span(), CFG) is True

    def test_repr(self) -> None:
        assert "AlwaysOnSampler" in repr(AlwaysOnSampler())


# ---------------------------------------------------------------------------
# AlwaysOffSampler
# ---------------------------------------------------------------------------


class TestAlwaysOffSampler:
    def test_always_false(self) -> None:
        s = AlwaysOffSampler()
        assert s.should_sample(_make_span(), CFG) is False

    def test_repr(self) -> None:
        assert "AlwaysOffSampler" in repr(AlwaysOffSampler())


# ---------------------------------------------------------------------------
# RatioSampler
# ---------------------------------------------------------------------------


class TestRatioSampler:
    def test_rate_property(self) -> None:
        assert RatioSampler(0.5).rate == 0.5

    def test_invalid_rate_raises(self) -> None:
        with pytest.raises(ValueError, match="must be in"):
            RatioSampler(-0.1)
        with pytest.raises(ValueError, match="must be in"):
            RatioSampler(1.1)

    def test_rate_1_always_exports(self) -> None:
        s = RatioSampler(1.0)
        for i in range(20):
            assert s.should_sample(_make_span(trace_id=f"trace-{i}"), CFG) is True

    def test_rate_0_never_exports(self) -> None:
        s = RatioSampler(0.0)
        for i in range(20):
            assert s.should_sample(_make_span(trace_id=f"trace-{i}"), CFG) is False

    def test_deterministic_on_same_trace_id(self) -> None:
        s = RatioSampler(0.5)
        span = _make_span(trace_id="deterministic-id")
        results = {s.should_sample(span, CFG) for _ in range(10)}
        assert len(results) == 1  # always same decision

    def test_no_trace_id_falls_through(self) -> None:
        s = RatioSampler(0.5)
        assert s.should_sample(_make_span(trace_id=None), CFG) is True

    def test_repr(self) -> None:
        assert "0.5" in repr(RatioSampler(0.5))


# ---------------------------------------------------------------------------
# ParentBasedSampler
# ---------------------------------------------------------------------------


class TestParentBasedSampler:
    def test_root_span_delegates_to_root_sampler(self) -> None:
        s = ParentBasedSampler(root_sampler=AlwaysOffSampler())
        span = _make_span(parent_span_id=None, traceparent=None)
        assert s.should_sample(span, CFG) is False

    def test_root_default_is_always_on(self) -> None:
        s = ParentBasedSampler()
        span = _make_span(parent_span_id=None, traceparent=None)
        assert s.should_sample(span, CFG) is True

    def test_local_parent_always_sampled(self) -> None:
        s = ParentBasedSampler(root_sampler=AlwaysOffSampler())
        span = _make_span(parent_span_id="parent-123")
        assert s.should_sample(span, CFG) is True

    def test_remote_parent_sampled(self) -> None:
        s = ParentBasedSampler()
        # W3C traceparent with sampled flag = 01
        span = _make_span(traceparent="00-abcdef-123456-01")
        assert s.should_sample(span, CFG) is True

    def test_remote_parent_not_sampled(self) -> None:
        s = ParentBasedSampler()
        # W3C traceparent with sampled flag = 00
        span = _make_span(traceparent="00-abcdef-123456-00")
        assert s.should_sample(span, CFG) is False

    def test_remote_parent_corrupt_flags(self) -> None:
        s = ParentBasedSampler()
        span = _make_span(traceparent="corrupt-data")
        # "corrupt-data".rsplit("-", 1) → ["corrupt", "data"], int("data", 16) raises ValueError
        # → sampled_flag = False → returns remote_parent_not_sampled = False
        assert s.should_sample(span, CFG) is False

    def test_custom_remote_decisions(self) -> None:
        s = ParentBasedSampler(
            remote_parent_sampled=False,
            remote_parent_not_sampled=True,
        )
        span_sampled = _make_span(traceparent="00-abc-def-01")
        span_not_sampled = _make_span(traceparent="00-abc-def-00")
        assert s.should_sample(span_sampled, CFG) is False
        assert s.should_sample(span_not_sampled, CFG) is True

    def test_repr(self) -> None:
        r = repr(ParentBasedSampler())
        assert "ParentBasedSampler" in r
        assert "AlwaysOnSampler" in r


# ---------------------------------------------------------------------------
# RuleBasedSampler
# ---------------------------------------------------------------------------


class TestRuleBasedSampler:
    def test_matching_rule_returns_decision(self) -> None:
        s = RuleBasedSampler(
            rules=[{"match": {"status": "ok"}, "sample": False}],
            default=True,
        )
        assert s.should_sample(_make_span(status="ok"), CFG) is False

    def test_no_match_returns_default(self) -> None:
        s = RuleBasedSampler(
            rules=[{"match": {"status": "error"}, "sample": False}],
            default=True,
        )
        assert s.should_sample(_make_span(status="ok"), CFG) is True

    def test_dotted_attribute_path(self) -> None:
        obj = _make_span()
        obj.model = types.SimpleNamespace(name="gpt-4o")
        s = RuleBasedSampler(
            rules=[{"match": {"model.name": "gpt-4o"}, "sample": True}],
            default=False,
        )
        assert s.should_sample(obj, CFG) is True

    def test_dotted_path_missing_attr(self) -> None:
        obj = _make_span()
        s = RuleBasedSampler(
            rules=[{"match": {"model.name": "gpt-4o"}, "sample": True}],
            default=False,
        )
        # model attr doesn't exist → val = None → "gpt-4o" != None → no match → default
        assert s.should_sample(obj, CFG) is False

    def test_first_matching_rule_wins(self) -> None:
        s = RuleBasedSampler(
            rules=[
                {"match": {"status": "ok"}, "sample": True},
                {"match": {"status": "ok"}, "sample": False},
            ],
        )
        assert s.should_sample(_make_span(status="ok"), CFG) is True

    def test_empty_rules_returns_default(self) -> None:
        assert RuleBasedSampler(default=False).should_sample(_make_span(), CFG) is False

    def test_rule_missing_sample_key_uses_default(self) -> None:
        s = RuleBasedSampler(
            rules=[{"match": {"status": "ok"}}],
            default=True,
        )
        assert s.should_sample(_make_span(status="ok"), CFG) is True

    def test_repr(self) -> None:
        assert "RuleBasedSampler" in repr(RuleBasedSampler())


# ---------------------------------------------------------------------------
# TailBasedSampler
# ---------------------------------------------------------------------------


class TestTailBasedSampler:
    def test_error_always_sampled(self) -> None:
        s = TailBasedSampler(fallback_sampler=AlwaysOffSampler())
        assert s.should_sample(_make_span(status="error"), CFG) is True

    def test_error_sampling_disabled(self) -> None:
        s = TailBasedSampler(
            always_sample_errors=False,
            fallback_sampler=AlwaysOffSampler(),
        )
        assert s.should_sample(_make_span(status="error"), CFG) is False

    def test_slow_span_always_sampled(self) -> None:
        s = TailBasedSampler(
            always_sample_slow_ms=100.0,
            fallback_sampler=AlwaysOffSampler(),
        )
        assert s.should_sample(_make_span(duration_ms=150.0), CFG) is True

    def test_fast_span_uses_fallback(self) -> None:
        s = TailBasedSampler(
            always_sample_slow_ms=100.0,
            fallback_sampler=AlwaysOffSampler(),
        )
        assert s.should_sample(_make_span(duration_ms=50.0, status="ok"), CFG) is False

    def test_slow_threshold_exact(self) -> None:
        s = TailBasedSampler(
            always_sample_slow_ms=100.0,
            fallback_sampler=AlwaysOffSampler(),
        )
        assert s.should_sample(_make_span(duration_ms=100.0, status="ok"), CFG) is True

    def test_default_fallback_is_always_on(self) -> None:
        s = TailBasedSampler(always_sample_errors=False)
        assert s.should_sample(_make_span(status="ok"), CFG) is True

    def test_repr(self) -> None:
        r = repr(TailBasedSampler(always_sample_slow_ms=200.0))
        assert "TailBasedSampler" in r
        assert "200.0" in r


# ---------------------------------------------------------------------------
# ComplianceSampler (SF-16)
# ---------------------------------------------------------------------------


class TestComplianceSampler:
    def test_invalid_base_rate_raises(self) -> None:
        with pytest.raises(ValueError, match="must be in"):
            ComplianceSampler(base_rate=-0.1)
        with pytest.raises(ValueError, match="must be in"):
            ComplianceSampler(base_rate=1.1)

    def test_base_rate_property(self) -> None:
        assert ComplianceSampler(base_rate=0.5).base_rate == 0.5

    def test_always_record_property(self) -> None:
        s = ComplianceSampler()
        assert "llm.audit." in s.always_record
        assert "llm.redact." in s.always_record

    def test_compliance_event_always_recorded(self) -> None:
        s = ComplianceSampler(base_rate=0.0)
        for et in ["llm.audit.event", "llm.redact.pii", "llm.guard.block", "llm.cost.track"]:
            span = _make_span(event_type=et)
            assert s.should_sample(span, CFG) is True, f"{et} should always be recorded"

    def test_non_compliance_event_at_rate_0_dropped(self) -> None:
        s = ComplianceSampler(base_rate=0.0)
        span = _make_span(event_type="llm.trace.span", trace_id="some-trace")
        assert s.should_sample(span, CFG) is False

    def test_non_compliance_event_at_rate_1_exported(self) -> None:
        s = ComplianceSampler(base_rate=1.0)
        span = _make_span(event_type="llm.trace.span", trace_id="some-trace")
        assert s.should_sample(span, CFG) is True

    def test_deterministic_trace_id_hashing(self) -> None:
        s = ComplianceSampler(base_rate=0.5)
        span = _make_span(event_type="llm.trace.span", trace_id="stable-id")
        results = {s.should_sample(span, CFG) for _ in range(20)}
        assert len(results) == 1  # deterministic

    def test_no_trace_id_falls_back_to_random(self) -> None:
        s = ComplianceSampler(base_rate=0.5)
        span = _make_span(event_type="llm.trace.span", trace_id=None)
        # With rate 0.5, random should produce both True and False over many trials
        results = {s.should_sample(span, CFG) for _ in range(200)}
        assert len(results) == 2

    def test_no_event_type_uses_trace_sampling(self) -> None:
        s = ComplianceSampler(base_rate=0.0)
        span = _make_span(event_type=None, trace_id="tid")
        assert s.should_sample(span, CFG) is False

    def test_custom_always_record(self) -> None:
        s = ComplianceSampler(base_rate=0.0, always_record=frozenset({"custom."}))
        assert s.should_sample(_make_span(event_type="custom.event"), CFG) is True
        assert s.should_sample(_make_span(event_type="llm.audit.x", trace_id="t"), CFG) is False

    def test_repr(self) -> None:
        assert "0.1" in repr(ComplianceSampler(base_rate=0.1))


# ---------------------------------------------------------------------------
# bypass_sampling() context manager
# ---------------------------------------------------------------------------


class TestBypassSampling:
    def test_bypass_forces_true(self) -> None:
        s = ComplianceSampler(base_rate=0.0)
        span = _make_span(event_type="llm.trace.span", trace_id="tid")
        assert s.should_sample(span, CFG) is False
        with bypass_sampling():
            assert s.should_sample(span, CFG) is True
        assert s.should_sample(span, CFG) is False

    def test_bypass_nesting(self) -> None:
        s = ComplianceSampler(base_rate=0.0)
        span = _make_span(event_type="llm.trace.span", trace_id="tid")
        with bypass_sampling():
            assert s.should_sample(span, CFG) is True
            with bypass_sampling():
                assert s.should_sample(span, CFG) is True
            # Still true — outer bypass still active
            assert s.should_sample(span, CFG) is True
        assert s.should_sample(span, CFG) is False

    def test_bypass_restores_after_exception(self) -> None:
        s = ComplianceSampler(base_rate=0.0)
        span = _make_span(event_type="llm.trace.span", trace_id="tid")
        with pytest.raises(RuntimeError), bypass_sampling():
            raise RuntimeError("boom")
        assert s.should_sample(span, CFG) is False
