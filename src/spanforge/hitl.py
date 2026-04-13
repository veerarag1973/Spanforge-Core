"""Human-in-the-Loop (HITL) review queue for SpanForge compliance pipeline.

Provides a runtime mechanism to intercept low-confidence or high-risk
agent decisions, queue them for human review, and track approval/rejection
outcomes in the HMAC audit chain.

Required for EU AI Act high-risk mandatory human oversight (Art. 14).

Configuration
-------------
* ``hitl_enabled=True`` activates the HITL queue.
* ``hitl_confidence_threshold`` — decisions below this confidence are auto-queued.
* ``hitl_risk_tiers`` — set of risk tiers that always require review.
* ``hitl_sla_seconds`` — SLA timeout for pending reviews.

Emits ``hitl.queued``, ``hitl.reviewed``, ``hitl.escalated``, ``hitl.timeout``
events into the HMAC audit chain via :func:`emit_rfc_event`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Literal

from spanforge.namespaces.hitl import HITLPayload

__all__ = [
    "HITLQueue",
    "HITLItem",
    "queue_for_review",
    "review_item",
    "list_pending",
]


@dataclass
class HITLItem:
    """A single item pending human review."""

    decision_id: str
    agent_id: str
    risk_tier: Literal["low", "medium", "high", "critical"]
    reason: str
    confidence: float | None = None
    sla_seconds: int = 3600
    queued_at: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)
    status: Literal["queued", "approved", "rejected", "escalated", "timeout"] = "queued"
    reviewer: str | None = None
    resolved_at: str | None = None
    escalation_tier: int = 0


class HITLQueue:
    """Thread-safe human-in-the-loop review queue.

    Intercepts agent decisions matching configurable risk criteria
    (confidence below threshold, high-risk event type) and holds them
    pending a named reviewer's approval.
    """

    def __init__(
        self,
        *,
        confidence_threshold: float = 0.7,
        risk_tiers: frozenset[str] | None = None,
        sla_seconds: int = 3600,
        auto_emit: bool = True,
    ) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, HITLItem] = {}
        self._confidence_threshold = confidence_threshold
        self._risk_tiers: frozenset[str] = risk_tiers or frozenset({"high", "critical"})
        self._sla_seconds = sla_seconds
        self._auto_emit = auto_emit

    @property
    def confidence_threshold(self) -> float:
        return self._confidence_threshold

    @property
    def sla_seconds(self) -> int:
        return self._sla_seconds

    def should_review(
        self,
        *,
        confidence: float | None = None,
        risk_tier: str = "low",
    ) -> bool:
        """Determine if a decision should be queued for human review."""
        if risk_tier in self._risk_tiers:
            return True
        if confidence is not None and confidence < self._confidence_threshold:
            return True
        return False

    def enqueue(
        self,
        decision_id: str,
        agent_id: str,
        risk_tier: Literal["low", "medium", "high", "critical"],
        reason: str,
        *,
        confidence: float | None = None,
        queued_at: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> HITLItem:
        """Add a decision to the review queue and emit ``hitl.queued``."""
        if not decision_id:
            raise ValueError("decision_id must be non-empty")
        if not agent_id:
            raise ValueError("agent_id must be non-empty")
        if not reason:
            raise ValueError("reason must be non-empty")

        if queued_at is None:
            import datetime  # noqa: PLC0415
            queued_at = datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%fZ"
            )

        item = HITLItem(
            decision_id=decision_id,
            agent_id=agent_id,
            risk_tier=risk_tier,
            reason=reason,
            confidence=confidence,
            sla_seconds=self._sla_seconds,
            queued_at=queued_at,
            payload=payload or {},
            status="queued",
        )
        with self._lock:
            self._items[decision_id] = item

        if self._auto_emit:
            self._emit_event(item, "queued")
        return item

    def review(
        self,
        decision_id: str,
        reviewer: str,
        outcome: Literal["approved", "rejected"],
        *,
        reason: str | None = None,
    ) -> HITLItem | None:
        """Record a reviewer's decision and emit ``hitl.reviewed``."""
        if not reviewer:
            raise ValueError("reviewer must be non-empty")

        import datetime  # noqa: PLC0415
        now = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )

        with self._lock:
            item = self._items.get(decision_id)
            if item is None:
                return None
            item.status = outcome
            item.reviewer = reviewer
            item.resolved_at = now
            if reason:
                item.reason = reason

        if self._auto_emit:
            self._emit_event(item, "reviewed")
        return item

    def escalate(
        self,
        decision_id: str,
        *,
        reason: str = "SLA breach or reviewer escalation",
    ) -> HITLItem | None:
        """Escalate an item to the next reviewer tier."""
        with self._lock:
            item = self._items.get(decision_id)
            if item is None:
                return None
            item.status = "escalated"
            item.escalation_tier += 1
            item.reason = reason

        if self._auto_emit:
            self._emit_event(item, "escalated")
        return item

    def timeout(self, decision_id: str) -> HITLItem | None:
        """Mark an item as timed out (SLA expired)."""
        import datetime  # noqa: PLC0415
        now = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )

        with self._lock:
            item = self._items.get(decision_id)
            if item is None:
                return None
            item.status = "timeout"
            item.resolved_at = now

        if self._auto_emit:
            self._emit_event(item, "timeout")
        return item

    def get(self, decision_id: str) -> HITLItem | None:
        """Look up an item by decision_id."""
        with self._lock:
            return self._items.get(decision_id)

    def list_pending(self) -> list[HITLItem]:
        """Return all items still in ``queued`` status."""
        with self._lock:
            return [i for i in self._items.values() if i.status == "queued"]

    def list_all(self) -> list[HITLItem]:
        """Return all items regardless of status."""
        with self._lock:
            return list(self._items.values())

    def clear(self) -> None:
        """Remove all items (for testing)."""
        with self._lock:
            self._items.clear()

    @staticmethod
    def _emit_event(item: HITLItem, action: str) -> None:
        """Emit an HITL event into the HMAC audit chain."""
        try:
            from spanforge._stream import emit_rfc_event  # noqa: PLC0415
            from spanforge.types import EventType  # noqa: PLC0415

            _action_to_event = {
                "queued": EventType.HITL_QUEUED,
                "reviewed": EventType.HITL_REVIEWED,
                "escalated": EventType.HITL_ESCALATED,
                "timeout": EventType.HITL_TIMEOUT,
            }
            et = _action_to_event.get(action)
            if et is None:
                return
            payload = HITLPayload(
                decision_id=item.decision_id,
                agent_id=item.agent_id,
                risk_tier=item.risk_tier,
                status=item.status,
                reason=item.reason,
                reviewer=item.reviewer,
                sla_seconds=item.sla_seconds,
                queued_at=item.queued_at,
                resolved_at=item.resolved_at,
                escalation_tier=item.escalation_tier,
                confidence=item.confidence,
            )
            try:
                emit_rfc_event(et, payload.to_dict())
            except Exception:  # noqa: BLE001
                pass
        except ImportError:
            pass


# ---------------------------------------------------------------------------
# Module-level singleton & convenience functions
# ---------------------------------------------------------------------------

_queue = HITLQueue()


def queue_for_review(
    decision_id: str,
    agent_id: str,
    risk_tier: Literal["low", "medium", "high", "critical"],
    reason: str,
    **kwargs: Any,
) -> HITLItem:
    """Enqueue a decision via the module-level :class:`HITLQueue`."""
    return _queue.enqueue(decision_id, agent_id, risk_tier, reason, **kwargs)


def review_item(
    decision_id: str,
    reviewer: str,
    outcome: Literal["approved", "rejected"],
    **kwargs: Any,
) -> HITLItem | None:
    """Record a review via the module-level :class:`HITLQueue`."""
    return _queue.review(decision_id, reviewer, outcome, **kwargs)


def list_pending() -> list[HITLItem]:
    """List pending items via the module-level :class:`HITLQueue`."""
    return _queue.list_pending()
