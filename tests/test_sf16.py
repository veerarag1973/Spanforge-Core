"""SF-16 — Compliance-Aware Sampling acceptance tests."""

from __future__ import annotations

from typing import Generator

import pytest

from spanforge import Event, EventType, configure, get_config
from spanforge.sampling import ComplianceSampler, bypass_sampling


_SOURCE = "test-sf16@1.0.0"


def _make_event(**kw):
    defaults = {
        "event_type": EventType.TRACE_SPAN_COMPLETED,
        "source": _SOURCE,
        "payload": {"span_name": "run", "status": "ok"},
    }
    defaults.update(kw)
    return Event(**defaults)


# ---- SF-16-A: ComplianceSampler defaults ----

class TestSF16A:
    """SF-16-A: ``ComplianceSampler`` with correct defaults."""

    @pytest.mark.unit
    def test_default_always_record_prefixes(self):
        sampler = ComplianceSampler(base_rate=0.1)
        ar = sampler.always_record
        assert "llm.audit." in ar
        assert "llm.redact." in ar
        assert "llm.guard." in ar
        assert "llm.cost." in ar

    @pytest.mark.unit
    def test_base_rate_stored(self):
        sampler = ComplianceSampler(base_rate=0.5)
        assert sampler.base_rate == 0.5

    @pytest.mark.unit
    def test_invalid_base_rate_raises(self):
        with pytest.raises(ValueError):
            ComplianceSampler(base_rate=1.5)
        with pytest.raises(ValueError):
            ComplianceSampler(base_rate=-0.1)


# ---- SF-16-B: Deterministic sampling ----

class TestSF16B:
    """SF-16-B: Deterministic trace-ID-based sampling."""

    @pytest.mark.unit
    def test_compliance_events_always_sampled(self):
        sampler = ComplianceSampler(base_rate=0.01)
        audit_event = _make_event(event_type=EventType.AUDIT_KEY_ROTATED)
        # Compliance events should always pass
        assert sampler.should_sample(audit_event, None) is True

    @pytest.mark.unit
    def test_regular_events_can_be_dropped(self):
        """At 0% base rate, non-compliance events should be dropped."""
        sampler = ComplianceSampler(base_rate=0.0)
        regular_event = _make_event(event_type=EventType.TRACE_SPAN_COMPLETED)
        assert sampler.should_sample(regular_event, None) is False


# ---- SF-16-C: Auto-wired in configure() ----

class TestSF16C:
    """SF-16-C: ``configure()`` auto-wires ``ComplianceSampler``."""

    @pytest.fixture(autouse=True)
    def _restore_config(self) -> Generator[None, None, None]:
        cfg = get_config()
        saved = {k: getattr(cfg, k) for k in vars(cfg)}
        yield
        for k, v in saved.items():
            setattr(cfg, k, v)

    @pytest.mark.unit
    def test_configure_wires_compliance_sampler(self):
        configure(compliance_sampling=True, sample_rate=0.5, sampler=None)
        cfg = get_config()
        assert isinstance(cfg.sampler, ComplianceSampler)
        assert cfg.sampler.base_rate == 0.5

    @pytest.mark.unit
    def test_configure_does_not_override_explicit_sampler(self):
        """If the user already set a sampler, don't replace it."""
        custom = ComplianceSampler(base_rate=0.99)
        configure(compliance_sampling=True, sample_rate=0.5, sampler=custom)
        cfg = get_config()
        assert cfg.sampler is custom

    @pytest.mark.unit
    def test_configure_no_sampler_at_full_rate(self):
        """At sample_rate=1.0, no sampler should be wired."""
        configure(compliance_sampling=True, sample_rate=1.0, sampler=None)
        cfg = get_config()
        assert cfg.sampler is None


# ---- SF-16-D: bypass_sampling() context manager ----

class TestSF16D:
    """SF-16-D: ``bypass_sampling()`` context manager."""

    @pytest.mark.unit
    def test_bypass_sampling_forces_record(self):
        sampler = ComplianceSampler(base_rate=0.0)
        regular_event = _make_event(event_type=EventType.TRACE_SPAN_COMPLETED)

        # Without bypass, should be dropped
        assert sampler.should_sample(regular_event, None) is False

        # With bypass, should be recorded
        with bypass_sampling():
            assert sampler.should_sample(regular_event, None) is True

        # After bypass, back to normal
        assert sampler.should_sample(regular_event, None) is False
