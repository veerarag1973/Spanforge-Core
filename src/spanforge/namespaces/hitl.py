"""spanforge.namespaces.hitl — Human-in-the-Loop namespace payload types (RFC-0001 SPANFORGE).

Classes
-------
HITLPayload    hitl.queued / hitl.reviewed / hitl.escalated / hitl.timeout
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

__all__ = ["HITLPayload"]

_VALID_STATUSES = frozenset({"queued", "approved", "rejected", "escalated", "timeout"})
_VALID_RISK_TIERS = frozenset({"low", "medium", "high", "critical"})


@dataclass
class HITLPayload:
    """RFC-0001 SPANFORGE — payload for hitl.* events.

    Captures human-in-the-loop review decisions for EU AI Act mandatory
    human oversight on high-risk AI systems (R — Responsibility).
    """

    decision_id: str
    agent_id: str
    risk_tier: Literal["low", "medium", "high", "critical"]
    status: Literal["queued", "approved", "rejected", "escalated", "timeout"]
    reason: str
    reviewer: str | None = None
    sla_seconds: int = 3600
    queued_at: str | None = None  # ISO 8601
    resolved_at: str | None = None  # ISO 8601
    escalation_tier: int = 0
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.decision_id:
            raise ValueError("HITLPayload.decision_id must be non-empty")
        if not self.agent_id:
            raise ValueError("HITLPayload.agent_id must be non-empty")
        if self.risk_tier not in _VALID_RISK_TIERS:
            raise ValueError(f"HITLPayload.risk_tier must be one of {sorted(_VALID_RISK_TIERS)}")
        if self.status not in _VALID_STATUSES:
            raise ValueError(f"HITLPayload.status must be one of {sorted(_VALID_STATUSES)}")
        if not self.reason:
            raise ValueError("HITLPayload.reason must be non-empty")
        if self.sla_seconds <= 0:
            raise ValueError("HITLPayload.sla_seconds must be > 0")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError("HITLPayload.confidence must be in [0.0, 1.0]")

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        d: dict[str, Any] = {
            "decision_id": self.decision_id,
            "agent_id": self.agent_id,
            "risk_tier": self.risk_tier,
            "status": self.status,
            "reason": self.reason,
            "sla_seconds": self.sla_seconds,
            "escalation_tier": self.escalation_tier,
        }
        if self.reviewer is not None:
            d["reviewer"] = self.reviewer
        if self.queued_at is not None:
            d["queued_at"] = self.queued_at
        if self.resolved_at is not None:
            d["resolved_at"] = self.resolved_at
        if self.confidence is not None:
            d["confidence"] = self.confidence
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HITLPayload:
        """Deserialise from a plain dict."""
        return cls(
            decision_id=data["decision_id"],
            agent_id=data["agent_id"],
            risk_tier=data["risk_tier"],
            status=data["status"],
            reason=data["reason"],
            reviewer=data.get("reviewer"),
            sla_seconds=int(data.get("sla_seconds", 3600)),
            queued_at=data.get("queued_at"),
            resolved_at=data.get("resolved_at"),
            escalation_tier=int(data.get("escalation_tier", 0)),
            confidence=data.get("confidence"),
        )
