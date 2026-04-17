"""spanforge.explain — Explainability record generation for AI compliance.

Aggregates decision drivers from span payloads into human-readable
explanations compliant with EU AI Act transparency requirements
(Articles 13-14) and the T.R.U.S.T. Framework Transparency pillar.

Emits ``explanation.generated`` events into the HMAC audit chain.

Usage::

    from spanforge.explain import ExplainabilityRecord

    record = ExplainabilityRecord(
        trace_id="01HQZF...",
        agent_id="support-agent@1.0",
        decision_id="01HQZF...",
        factors=[
            {"factor_name": "user_intent", "weight": 0.6,
             "contribution": 0.42, "evidence": "keyword match",
             "confidence": 0.85},
        ],
        summary="Routed to billing team based on keyword match.",
    )
    print(record.to_text())
"""

from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ExplainabilityRecord",
    "generate_explanation",
]


@dataclass
class ExplainabilityRecord:
    """A human-readable explanation of one or more AI decisions.

    Designed to satisfy EU AI Act Art. 13 transparency obligations.
    Each record can be serialised to plain text, JSON, or dict for
    audit trail inclusion.
    """

    trace_id: str
    agent_id: str
    decision_id: str
    factors: list[dict[str, Any]]
    summary: str
    model_id: str | None = None
    confidence: float | None = None
    risk_tier: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.trace_id:
            raise ValueError("ExplainabilityRecord.trace_id must be non-empty")
        if not self.agent_id:
            raise ValueError("ExplainabilityRecord.agent_id must be non-empty")
        if not self.decision_id:
            raise ValueError("ExplainabilityRecord.decision_id must be non-empty")
        if not self.summary:
            raise ValueError("ExplainabilityRecord.summary must be non-empty")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError("ExplainabilityRecord.confidence must be in [0.0, 1.0]")

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        d: dict[str, Any] = {
            "trace_id": self.trace_id,
            "agent_id": self.agent_id,
            "decision_id": self.decision_id,
            "factors": self.factors,
            "summary": self.summary,
        }
        if self.model_id is not None:
            d["model_id"] = self.model_id
        if self.confidence is not None:
            d["confidence"] = self.confidence
        if self.risk_tier is not None:
            d["risk_tier"] = self.risk_tier
        if self.metadata:
            d["metadata"] = self.metadata
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExplainabilityRecord:
        """Reconstruct from a plain dict."""
        return cls(
            trace_id=data["trace_id"],
            agent_id=data["agent_id"],
            decision_id=data["decision_id"],
            factors=data.get("factors", []),
            summary=data["summary"],
            model_id=data.get("model_id"),
            confidence=data.get("confidence"),
            risk_tier=data.get("risk_tier"),
            metadata=data.get("metadata", {}),
        )

    def to_json(self) -> str:
        """Serialise to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    def to_text(self) -> str:
        """Generate a human-readable explanation text.

        Returns a multi-line string suitable for end-user display or
        compliance documentation.
        """
        lines: list[str] = []
        lines.append(f"Explanation for decision {self.decision_id}")
        lines.append(f"  Agent: {self.agent_id}")
        lines.append(f"  Trace: {self.trace_id}")
        if self.model_id:
            lines.append(f"  Model: {self.model_id}")
        if self.confidence is not None:
            lines.append(f"  Confidence: {self.confidence:.2%}")
        if self.risk_tier:
            lines.append(f"  Risk tier: {self.risk_tier}")
        lines.append(f"  Summary: {self.summary}")
        if self.factors:
            lines.append("  Contributing factors:")
            for f in self.factors:
                name = f.get("factor_name", "unknown")
                weight = f.get("weight", 0)
                evidence = f.get("evidence", "")
                lines.append(f"    - {name} (weight={weight:.2f}): {evidence}")
        return "\n".join(lines)


def generate_explanation(
    trace_id: str,
    agent_id: str,
    decision_id: str,
    factors: list[dict[str, Any]],
    summary: str,
    *,
    model_id: str | None = None,
    confidence: float | None = None,
    risk_tier: str | None = None,
    auto_emit: bool = True,
    metadata: dict[str, Any] | None = None,
) -> ExplainabilityRecord:
    """Create an :class:`ExplainabilityRecord` and optionally emit an event.

    This is the primary convenience function for the explainability module.
    """
    record = ExplainabilityRecord(
        trace_id=trace_id,
        agent_id=agent_id,
        decision_id=decision_id,
        factors=factors,
        summary=summary,
        model_id=model_id,
        confidence=confidence,
        risk_tier=risk_tier,
        metadata=metadata or {},
    )
    if auto_emit:
        _emit_explanation(record)
    return record


def _emit_explanation(record: ExplainabilityRecord) -> None:
    """Emit an explanation.generated event into the HMAC audit chain."""
    try:
        from spanforge._stream import emit_rfc_event
        from spanforge.types import EventType

        with contextlib.suppress(Exception):
            emit_rfc_event(EventType.EXPLANATION_GENERATED, record.to_dict())
    except ImportError:
        pass
