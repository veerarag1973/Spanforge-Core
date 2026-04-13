"""Tests for spanforge.explain — Explainability record generation."""

from __future__ import annotations

import json

import pytest

from spanforge.explain import ExplainabilityRecord, generate_explanation


# ---------------------------------------------------------------------------
# ExplainabilityRecord tests
# ---------------------------------------------------------------------------


class TestExplainabilityRecord:
    """ExplainabilityRecord dataclass validation and serialization."""

    @pytest.mark.unit
    def test_valid_creation(self):
        r = ExplainabilityRecord(
            trace_id="trace-1",
            agent_id="agent-1",
            decision_id="dec-1",
            factors=[
                {"factor_name": "intent", "weight": 0.6, "contribution": 0.42,
                 "evidence": "keyword match", "confidence": 0.85},
            ],
            summary="Routed to billing.",
        )
        assert r.trace_id == "trace-1"
        assert len(r.factors) == 1

    @pytest.mark.unit
    def test_round_trip_dict(self):
        r = ExplainabilityRecord(
            trace_id="t1",
            agent_id="a1",
            decision_id="d1",
            factors=[{"factor_name": "f1", "weight": 0.5, "contribution": 0.3,
                       "evidence": "test", "confidence": 0.9}],
            summary="Test summary",
            model_id="gpt-4o",
            confidence=0.85,
            risk_tier="high",
            metadata={"key": "val"},
        )
        d = r.to_dict()
        r2 = ExplainabilityRecord.from_dict(d)
        assert r2.trace_id == r.trace_id
        assert r2.model_id == "gpt-4o"
        assert r2.confidence == 0.85
        assert r2.risk_tier == "high"
        assert r2.metadata == {"key": "val"}

    @pytest.mark.unit
    def test_round_trip_json(self):
        r = ExplainabilityRecord(
            trace_id="t1",
            agent_id="a1",
            decision_id="d1",
            factors=[],
            summary="Empty factors test",
        )
        j = r.to_json()
        d = json.loads(j)
        r2 = ExplainabilityRecord.from_dict(d)
        assert r2.summary == "Empty factors test"

    @pytest.mark.unit
    def test_to_text(self):
        r = ExplainabilityRecord(
            trace_id="t1",
            agent_id="a1",
            decision_id="d1",
            factors=[
                {"factor_name": "intent", "weight": 0.6, "evidence": "keyword"},
                {"factor_name": "history", "weight": 0.4, "evidence": "prior tickets"},
            ],
            summary="Routed to billing team.",
            model_id="gpt-4o",
            confidence=0.92,
            risk_tier="high",
        )
        text = r.to_text()
        assert "d1" in text
        assert "a1" in text
        assert "gpt-4o" in text
        assert "92.00%" in text
        assert "high" in text
        assert "Routed to billing team." in text
        assert "intent" in text
        assert "history" in text

    @pytest.mark.unit
    def test_to_text_minimal(self):
        r = ExplainabilityRecord(
            trace_id="t1",
            agent_id="a1",
            decision_id="d1",
            factors=[],
            summary="Simple decision.",
        )
        text = r.to_text()
        assert "Simple decision." in text
        assert "Contributing factors" not in text

    @pytest.mark.unit
    def test_empty_trace_id_raises(self):
        with pytest.raises(ValueError, match="trace_id"):
            ExplainabilityRecord(
                trace_id="",
                agent_id="a1",
                decision_id="d1",
                factors=[],
                summary="s",
            )

    @pytest.mark.unit
    def test_empty_agent_id_raises(self):
        with pytest.raises(ValueError, match="agent_id"):
            ExplainabilityRecord(
                trace_id="t1",
                agent_id="",
                decision_id="d1",
                factors=[],
                summary="s",
            )

    @pytest.mark.unit
    def test_empty_decision_id_raises(self):
        with pytest.raises(ValueError, match="decision_id"):
            ExplainabilityRecord(
                trace_id="t1",
                agent_id="a1",
                decision_id="",
                factors=[],
                summary="s",
            )

    @pytest.mark.unit
    def test_empty_summary_raises(self):
        with pytest.raises(ValueError, match="summary"):
            ExplainabilityRecord(
                trace_id="t1",
                agent_id="a1",
                decision_id="d1",
                factors=[],
                summary="",
            )

    @pytest.mark.unit
    def test_invalid_confidence_raises(self):
        with pytest.raises(ValueError, match="confidence"):
            ExplainabilityRecord(
                trace_id="t1",
                agent_id="a1",
                decision_id="d1",
                factors=[],
                summary="s",
                confidence=1.5,
            )

    @pytest.mark.unit
    def test_optional_fields_excluded_from_dict(self):
        """Fields that are None should not appear in to_dict."""
        r = ExplainabilityRecord(
            trace_id="t1",
            agent_id="a1",
            decision_id="d1",
            factors=[],
            summary="s",
        )
        d = r.to_dict()
        assert "model_id" not in d
        assert "confidence" not in d
        assert "risk_tier" not in d
        assert "metadata" not in d


# ---------------------------------------------------------------------------
# generate_explanation convenience function tests
# ---------------------------------------------------------------------------


class TestGenerateExplanation:
    """generate_explanation() convenience function."""

    @pytest.mark.unit
    def test_generate_returns_record(self):
        r = generate_explanation(
            trace_id="t1",
            agent_id="a1",
            decision_id="d1",
            factors=[{"factor_name": "f", "weight": 1.0, "contribution": 0.5,
                       "evidence": "e", "confidence": 0.9}],
            summary="Test",
            auto_emit=False,
        )
        assert isinstance(r, ExplainabilityRecord)
        assert r.decision_id == "d1"

    @pytest.mark.unit
    def test_generate_with_all_options(self):
        r = generate_explanation(
            trace_id="t2",
            agent_id="a2",
            decision_id="d2",
            factors=[],
            summary="Full options",
            model_id="claude-3",
            confidence=0.75,
            risk_tier="medium",
            metadata={"source": "test"},
            auto_emit=False,
        )
        assert r.model_id == "claude-3"
        assert r.confidence == 0.75
        assert r.metadata == {"source": "test"}
