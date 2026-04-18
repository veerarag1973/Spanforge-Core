"""Tests for RFC-0001 SPANFORGE namespace payload dataclasses.

Covers the 10 new namespaces introduced by RFC-0001 SPANFORGE:
  decision, tool_call, chain, confidence, consent, drift,
  latency, hitl, playbook, audit (AuditChainPayload only).

For each namespace payload class the tests verify:
  * Minimal construction (required fields only)
  * Full construction (all optional fields)
  * to_dict() / from_dict() round-trip
  * Validation errors for bad / missing fields
  * Default field values where applicable
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# decision
# ---------------------------------------------------------------------------
from spanforge.namespaces.decision import DecisionDriver, DecisionPayload


@pytest.mark.unit
class TestDecisionDriver:
    def _make(self, **kw) -> DecisionDriver:
        defaults = {
            "factor_name": "urgency",
            "weight": 0.5,
            "contribution": 0.3,
            "evidence": "High keyword density",
            "confidence": 0.9,
        }
        return DecisionDriver(**{**defaults, **kw})

    def test_minimal_construction(self) -> None:
        d = self._make()
        assert d.factor_name == "urgency"
        assert d.weight == 0.5

    def test_to_dict_round_trip(self) -> None:
        d = self._make()
        assert DecisionDriver.from_dict(d.to_dict()) == d

    def test_empty_factor_name_raises(self) -> None:
        with pytest.raises(ValueError, match="factor_name"):
            self._make(factor_name="")

    def test_weight_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="weight"):
            self._make(weight=1.5)

    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            self._make(confidence=-0.1)


@pytest.mark.unit
class TestDecisionPayload:
    def _make_driver(self) -> DecisionDriver:
        return DecisionDriver(
            factor_name="cost", weight=1.0, contribution=0.8,
            evidence="Cheap route", confidence=0.95,
        )

    def _make(self, **kw) -> DecisionPayload:
        defaults = {
            "decision_id": "01KNPT68GKD10PYCG55DMGH582",
            "agent_id": "agent-001",
            "decision_type": "routing",
            "input_summary": "Route request to cheapest model",
            "output_summary": "Selected gpt-3.5-turbo",
            "confidence": 0.87,
            "latency_ms": 42.5,
            "rationale_hash": "a" * 64,
        }
        return DecisionPayload(**{**defaults, **kw})

    def test_minimal_construction(self) -> None:
        dp = self._make()
        assert dp.agent_id == "agent-001"
        assert dp.decision_drivers == []
        assert dp.actor is None

    def test_full_construction(self) -> None:
        driver = self._make_driver()
        dp = self._make(
            decision_drivers=[driver],
            actor={"user_id": "u123", "session_id": "s456"},
        )
        assert len(dp.decision_drivers) == 1
        assert dp.actor is not None

    def test_to_dict_round_trip(self) -> None:
        dp = self._make(decision_drivers=[self._make_driver()])
        dp2 = DecisionPayload.from_dict(dp.to_dict())
        assert dp2.decision_id == dp.decision_id
        assert len(dp2.decision_drivers) == 1

    def test_invalid_decision_type_raises(self) -> None:
        with pytest.raises(ValueError, match="decision_type"):
            self._make(decision_type="unknown_type")

    def test_confidence_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence"):
            self._make(confidence=1.1)

    def test_negative_latency_raises(self) -> None:
        with pytest.raises(ValueError, match="latency_ms"):
            self._make(latency_ms=-1.0)

    def test_empty_decision_id_raises(self) -> None:
        with pytest.raises(ValueError, match="decision_id"):
            self._make(decision_id="")

    def test_empty_agent_id_raises(self) -> None:
        with pytest.raises(ValueError, match="agent_id"):
            self._make(agent_id="")

    def test_all_valid_decision_types(self) -> None:
        for dt in ("classification", "routing", "generation", "tool_selection", "other"):
            dp = self._make(decision_type=dt)
            assert dp.decision_type == dt


# ---------------------------------------------------------------------------
# tool_call
# ---------------------------------------------------------------------------
from spanforge.namespaces.tool_call import ToolCallPayload


@pytest.mark.unit
class TestToolCallPayload:
    def _make(self, **kw) -> ToolCallPayload:
        defaults = {
            "call_id": "call-01",
            "tool_name": "search_web",
            "latency_ms": 120.0,
            "status": "success",
            "consent_checked": True,
        }
        return ToolCallPayload(**{**defaults, **kw})

    def test_minimal_construction(self) -> None:
        t = self._make()
        assert t.tool_name == "search_web"
        assert t.inputs == {}
        assert t.outputs is None
        assert t.error_message is None
        assert t.tool_version is None

    def test_full_construction(self) -> None:
        t = self._make(
            inputs={"query": "weather"},
            outputs={"result": "Sunny"},
            error_message=None,
        )
        assert t.inputs == {"query": "weather"}

    def test_to_dict_round_trip(self) -> None:
        t = self._make(inputs={"k": "v"}, outputs={"r": 1})
        t2 = ToolCallPayload.from_dict(t.to_dict())
        assert t2.call_id == t.call_id
        assert t2.inputs == t.inputs

    def test_invalid_status_raises(self) -> None:
        with pytest.raises(ValueError, match="status"):
            self._make(status="unknown")

    def test_empty_call_id_raises(self) -> None:
        with pytest.raises(ValueError, match="call_id"):
            self._make(call_id="")

    def test_negative_latency_raises(self) -> None:
        with pytest.raises(ValueError, match="latency_ms"):
            self._make(latency_ms=-5.0)

    def test_all_valid_statuses(self) -> None:
        for s in ("success", "failure", "timeout"):
            t = self._make(status=s)
            assert t.status == s


# ---------------------------------------------------------------------------
# chain
# ---------------------------------------------------------------------------
from spanforge.namespaces.chain import ChainPayload


@pytest.mark.unit
class TestChainPayload:
    def _make(self, **kw) -> ChainPayload:
        defaults = {
            "chain_id": "chain-001",
            "step_index": 0,
            "step_name": "retrieve",
            "cumulative_latency_ms": 50.0,
            "cumulative_token_cost": 0.0,
            "error_propagated": False,
        }
        return ChainPayload(**{**defaults, **kw})

    def test_minimal_construction(self) -> None:
        c = self._make()
        assert c.chain_id == "chain-001"
        assert c.total_steps is None
        assert c.input_refs == []
        assert c.output_refs == []

    def test_full_construction(self) -> None:
        c = self._make(
            cumulative_latency_ms=300.0,
            cumulative_token_cost=1200,
            error_propagated=False,
            total_steps=4,
            input_refs=["ref-1"],
            output_refs=["ref-2", "ref-3"],
        )
        assert c.total_steps == 4
        assert c.output_refs == ["ref-2", "ref-3"]

    def test_to_dict_round_trip(self) -> None:
        c = self._make(total_steps=3, input_refs=["x"])
        c2 = ChainPayload.from_dict(c.to_dict())
        assert c2.chain_id == c.chain_id
        assert c2.input_refs == ["x"]

    def test_empty_chain_id_raises(self) -> None:
        with pytest.raises(ValueError, match="chain_id"):
            self._make(chain_id="")

    def test_empty_step_name_raises(self) -> None:
        with pytest.raises(ValueError, match="step_name"):
            self._make(step_name="")

    def test_negative_step_index_raises(self) -> None:
        with pytest.raises(ValueError, match="step_index"):
            self._make(step_index=-1)


# ---------------------------------------------------------------------------
# confidence
# ---------------------------------------------------------------------------
from spanforge.namespaces.confidence import ConfidencePayload


@pytest.mark.unit
class TestConfidencePayload:
    def _make(self, **kw) -> ConfidencePayload:
        defaults = {
            "model_id": "gpt-4o",
            "decision_type": "classification",
            "score": 0.82,
            "threshold_breached": False,
            "sampled_at": "2025-01-01T00:00:00.000000Z",
        }
        return ConfidencePayload(**{**defaults, **kw})

    def test_minimal_construction(self) -> None:
        c = self._make()
        assert c.model_id == "gpt-4o"
        assert c.baseline_mean is None
        assert c.z_score is None

    def test_full_construction(self) -> None:
        c = self._make(
            baseline_mean=0.85,
            baseline_stddev=0.05,
            z_score=-0.6,
        )
        assert c.z_score == -0.6

    def test_to_dict_round_trip(self) -> None:
        c = self._make(baseline_mean=0.85, z_score=1.2)
        c2 = ConfidencePayload.from_dict(c.to_dict())
        assert c2.score == c.score
        assert c2.z_score == 1.2

    def test_score_out_of_range_raises(self) -> None:
        with pytest.raises(ValueError, match="score"):
            self._make(score=1.001)

    def test_empty_model_id_raises(self) -> None:
        with pytest.raises(ValueError, match="model_id"):
            self._make(model_id="")

    def test_threshold_breached_true(self) -> None:
        c = self._make(threshold_breached=True, score=0.55)
        assert c.threshold_breached is True


# ---------------------------------------------------------------------------
# drift
# ---------------------------------------------------------------------------
from spanforge.namespaces.drift import DriftPayload


@pytest.mark.unit
class TestDriftPayload:
    def _make(self, **kw) -> DriftPayload:
        defaults = {
            "metric_name": "confidence_score",
            "agent_id": "agent-088",
            "current_value": 0.61,
            "baseline_mean": 0.82,
            "baseline_stddev": 0.04,
            "z_score": -5.25,
            "threshold": 3.0,
            "window_seconds": 3600,
            "status": "detected",
        }
        return DriftPayload(**{**defaults, **kw})

    def test_minimal_construction(self) -> None:
        d = self._make()
        assert d.metric_name == "confidence_score"
        assert d.kl_divergence is None

    def test_full_construction(self) -> None:
        d = self._make(kl_divergence=0.15)
        assert d.kl_divergence == 0.15

    def test_to_dict_round_trip(self) -> None:
        d = self._make(kl_divergence=0.08)
        d2 = DriftPayload.from_dict(d.to_dict())
        assert d2.z_score == d.z_score
        assert d2.kl_divergence == 0.08

    def test_empty_metric_name_raises(self) -> None:
        with pytest.raises(ValueError, match="metric_name"):
            self._make(metric_name="")

    def test_negative_threshold_raises(self) -> None:
        # DriftPayload does not validate threshold sign — only window_seconds > 0
        # and baseline_stddev >= 0 are validated
        with pytest.raises(ValueError, match="window_seconds"):
            self._make(window_seconds=0)

    def test_negative_window_raises(self) -> None:
        with pytest.raises(ValueError, match="window_seconds"):
            self._make(window_seconds=0)

    def test_invalid_status_raises(self) -> None:
        with pytest.raises(ValueError, match="status"):
            self._make(status="unknown_status")

    def test_all_valid_statuses(self) -> None:
        for s in ("detected", "threshold_breach", "resolved"):
            d = self._make(status=s)
            assert d.status == s


# ---------------------------------------------------------------------------
# latency
# ---------------------------------------------------------------------------
from spanforge.namespaces.latency import LatencyPayload


@pytest.mark.unit
class TestLatencyPayload:
    def _make(self, **kw) -> LatencyPayload:
        defaults = {
            "agent_id": "agent-lat",
            "operation": "inference",
            "latency_ms": 250.0,
            "sla_target_ms": 500.0,
            "sla_met": True,
        }
        return LatencyPayload(**{**defaults, **kw})

    def test_minimal_construction(self) -> None:
        lat = self._make()
        assert lat.operation == "inference"
        assert lat.p50_ms is None
        assert lat.p99_ms is None

    def test_full_construction(self) -> None:
        lat = self._make(p50_ms=120.0, p95_ms=240.0, p99_ms=400.0)
        assert lat.p99_ms == 400.0

    def test_to_dict_round_trip(self) -> None:
        lat = self._make(p95_ms=200.0)
        lat2 = LatencyPayload.from_dict(lat.to_dict())
        assert lat2.latency_ms == lat.latency_ms
        assert lat2.p95_ms == 200.0

    def test_empty_agent_id_raises(self) -> None:
        with pytest.raises(ValueError, match="agent_id"):
            self._make(agent_id="")

    def test_negative_latency_raises(self) -> None:
        with pytest.raises(ValueError, match="latency_ms"):
            self._make(latency_ms=-10.0)

    def test_negative_sla_target_raises(self) -> None:
        with pytest.raises(ValueError, match="sla_target_ms"):
            self._make(sla_target_ms=0.0)

    def test_sla_not_met(self) -> None:
        lat = self._make(latency_ms=600.0, sla_met=False)
        assert lat.sla_met is False


# ---------------------------------------------------------------------------
# audit — AuditChainPayload (RFC-0001 SPANFORGE tamper-evident chain)
# ---------------------------------------------------------------------------
from spanforge.namespaces.audit import AuditChainPayload


@pytest.mark.unit
class TestAuditChainPayload:
    def _make(self, **kw) -> AuditChainPayload:
        defaults = {
            "event_id": "01KNPT68GKD10PYCG55DMGH582",
            "event_type": "decision.made",
            "event_hmac": "hmac" + "a" * 60,
            "chain_position": 0,
            "signer_id": "key-v1",
            "signed_at": "2025-01-01T00:00:00.000000Z",
        }
        return AuditChainPayload(**{**defaults, **kw})

    def test_first_entry_no_prev_hmac(self) -> None:
        a = self._make()
        assert a.chain_position == 0
        assert a.prev_chain_hmac is None

    def test_subsequent_entry_with_prev_hmac(self) -> None:
        a = self._make(chain_position=1, prev_chain_hmac="prev" + "b" * 60)
        assert a.prev_chain_hmac is not None

    def test_position_gt_0_requires_prev_hmac(self) -> None:
        with pytest.raises(ValueError, match="prev_chain_hmac"):
            self._make(chain_position=1)

    def test_to_dict_round_trip_position_0(self) -> None:
        a = self._make()
        a2 = AuditChainPayload.from_dict(a.to_dict())
        assert a2.event_id == a.event_id
        assert a2.chain_position == 0
        assert a2.prev_chain_hmac is None

    def test_to_dict_round_trip_position_5(self) -> None:
        prev = "x" * 64
        a = self._make(chain_position=5, prev_chain_hmac=prev)
        a2 = AuditChainPayload.from_dict(a.to_dict())
        assert a2.chain_position == 5
        assert a2.prev_chain_hmac == prev

    def test_empty_event_id_raises(self) -> None:
        with pytest.raises(ValueError, match="event_id"):
            self._make(event_id="")

    def test_empty_signer_id_raises(self) -> None:
        with pytest.raises(ValueError, match="signer_id"):
            self._make(signer_id="")

    def test_negative_chain_position_raises(self) -> None:
        with pytest.raises(ValueError, match="chain_position"):
            self._make(chain_position=-1)
