"""Tests for spanforge.hitl — Human-in-the-Loop review queue."""

from __future__ import annotations

import pytest

from spanforge.hitl import HITLQueue, list_pending, queue_for_review, review_item
from spanforge.namespaces.hitl import HITLPayload

# ---------------------------------------------------------------------------
# HITLPayload tests
# ---------------------------------------------------------------------------


class TestHITLPayload:
    """HITLPayload dataclass validation and serialization."""

    @pytest.mark.unit
    def test_valid_payload_creation(self):
        p = HITLPayload(
            decision_id="dec-1",
            agent_id="agent-1",
            risk_tier="high",
            status="queued",
            reason="low confidence",
        )
        assert p.decision_id == "dec-1"
        assert p.risk_tier == "high"

    @pytest.mark.unit
    def test_round_trip(self):
        p = HITLPayload(
            decision_id="dec-2",
            agent_id="agent-2",
            risk_tier="critical",
            status="approved",
            reason="reviewed ok",
            reviewer="admin",
            sla_seconds=1800,
            confidence=0.3,
        )
        d = p.to_dict()
        p2 = HITLPayload.from_dict(d)
        assert p2.decision_id == p.decision_id
        assert p2.reviewer == "admin"
        assert p2.confidence == 0.3

    @pytest.mark.unit
    def test_empty_decision_id_raises(self):
        with pytest.raises(ValueError, match="decision_id"):
            HITLPayload(
                decision_id="",
                agent_id="a",
                risk_tier="low",
                status="queued",
                reason="r",
            )

    @pytest.mark.unit
    def test_invalid_risk_tier_raises(self):
        with pytest.raises(ValueError, match="risk_tier"):
            HITLPayload(
                decision_id="d1",
                agent_id="a1",
                risk_tier="extreme",
                status="queued",
                reason="r",
            )

    @pytest.mark.unit
    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="status"):
            HITLPayload(
                decision_id="d1",
                agent_id="a1",
                risk_tier="low",
                status="pending",
                reason="r",
            )

    @pytest.mark.unit
    def test_confidence_out_of_range_raises(self):
        with pytest.raises(ValueError, match="confidence"):
            HITLPayload(
                decision_id="d1",
                agent_id="a1",
                risk_tier="low",
                status="queued",
                reason="r",
                confidence=1.5,
            )


# ---------------------------------------------------------------------------
# HITLQueue tests
# ---------------------------------------------------------------------------


class TestHITLQueue:
    """HITLQueue thread-safe runtime class."""

    def setup_method(self):
        self.queue = HITLQueue(auto_emit=False)

    @pytest.mark.unit
    def test_enqueue_and_list(self):
        item = self.queue.enqueue("dec-1", "agent-1", "high", "low confidence")
        assert item.status == "queued"
        assert item.decision_id == "dec-1"

        pending = self.queue.list_pending()
        assert len(pending) == 1
        assert pending[0].decision_id == "dec-1"

    @pytest.mark.unit
    def test_review_approved(self):
        self.queue.enqueue("dec-1", "agent-1", "medium", "uncertain")
        item = self.queue.review("dec-1", "alice", "approved")
        assert item is not None
        assert item.status == "approved"
        assert item.reviewer == "alice"
        assert item.resolved_at is not None

    @pytest.mark.unit
    def test_review_rejected(self):
        self.queue.enqueue("dec-1", "agent-1", "medium", "uncertain")
        item = self.queue.review("dec-1", "bob", "rejected")
        assert item is not None
        assert item.status == "rejected"

    @pytest.mark.unit
    def test_review_nonexistent_returns_none(self):
        assert self.queue.review("ghost", "alice", "approved") is None

    @pytest.mark.unit
    def test_escalate(self):
        self.queue.enqueue("dec-1", "agent-1", "critical", "needs review")
        item = self.queue.escalate("dec-1")
        assert item is not None
        assert item.status == "escalated"
        assert item.escalation_tier == 1

    @pytest.mark.unit
    def test_escalate_increments_tier(self):
        self.queue.enqueue("dec-1", "agent-1", "critical", "needs review")
        self.queue.escalate("dec-1")
        item = self.queue.escalate("dec-1")
        assert item.escalation_tier == 2

    @pytest.mark.unit
    def test_escalate_nonexistent_returns_none(self):
        assert self.queue.escalate("ghost") is None

    @pytest.mark.unit
    def test_timeout(self):
        self.queue.enqueue("dec-1", "agent-1", "high", "timed out")
        item = self.queue.timeout("dec-1")
        assert item is not None
        assert item.status == "timeout"
        assert item.resolved_at is not None

    @pytest.mark.unit
    def test_timeout_nonexistent_returns_none(self):
        assert self.queue.timeout("ghost") is None

    @pytest.mark.unit
    def test_get(self):
        self.queue.enqueue("dec-1", "agent-1", "low", "reason")
        item = self.queue.get("dec-1")
        assert item is not None
        assert item.decision_id == "dec-1"

    @pytest.mark.unit
    def test_get_nonexistent_returns_none(self):
        assert self.queue.get("ghost") is None

    @pytest.mark.unit
    def test_list_all(self):
        self.queue.enqueue("dec-1", "a1", "low", "r1")
        self.queue.enqueue("dec-2", "a2", "high", "r2")
        self.queue.review("dec-1", "admin", "approved")
        all_items = self.queue.list_all()
        assert len(all_items) == 2

    @pytest.mark.unit
    def test_list_pending_filters(self):
        self.queue.enqueue("dec-1", "a1", "low", "r1")
        self.queue.enqueue("dec-2", "a2", "high", "r2")
        self.queue.review("dec-1", "admin", "approved")
        pending = self.queue.list_pending()
        assert len(pending) == 1
        assert pending[0].decision_id == "dec-2"

    @pytest.mark.unit
    def test_clear(self):
        self.queue.enqueue("dec-1", "a1", "low", "r1")
        self.queue.clear()
        assert self.queue.list_all() == []

    @pytest.mark.unit
    def test_should_review_by_risk_tier(self):
        assert self.queue.should_review(risk_tier="high") is True
        assert self.queue.should_review(risk_tier="critical") is True
        assert self.queue.should_review(risk_tier="low") is False

    @pytest.mark.unit
    def test_should_review_by_confidence(self):
        assert self.queue.should_review(confidence=0.3) is True
        assert self.queue.should_review(confidence=0.9) is False

    @pytest.mark.unit
    def test_enqueue_empty_decision_id_raises(self):
        with pytest.raises(ValueError, match="decision_id"):
            self.queue.enqueue("", "a1", "low", "r")

    @pytest.mark.unit
    def test_enqueue_empty_agent_id_raises(self):
        with pytest.raises(ValueError, match="agent_id"):
            self.queue.enqueue("d1", "", "low", "r")

    @pytest.mark.unit
    def test_enqueue_empty_reason_raises(self):
        with pytest.raises(ValueError, match="reason"):
            self.queue.enqueue("d1", "a1", "low", "")

    @pytest.mark.unit
    def test_review_empty_reviewer_raises(self):
        self.queue.enqueue("dec-1", "a1", "low", "r")
        with pytest.raises(ValueError, match="reviewer"):
            self.queue.review("dec-1", "", "approved")


# ---------------------------------------------------------------------------
# Module-level convenience function tests
# ---------------------------------------------------------------------------


class TestHITLConvenienceFunctions:
    """Module-level queue_for_review / review_item / list_pending."""

    @pytest.mark.unit
    def test_queue_review_cycle(self):
        from spanforge.hitl import _queue
        _queue.clear()

        queue_for_review("d1", "a1", "high", "test review")
        pending = list_pending()
        assert len(pending) == 1

        result = review_item("d1", "admin", "approved")
        assert result is not None
        assert result.status == "approved"

        assert list_pending() == []
