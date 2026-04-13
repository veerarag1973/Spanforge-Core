"""spanforge.namespaces.decision — Decision namespace payload types (RFC-0001 SPANFORGE).

Classes
-------
DecisionDriver          Factor contributing to a decision (T \u2014 Transparency)
DecisionPayload         decision.made / decision.revised / decision.rejected
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "DecisionDriver",
    "DecisionPayload",
]

_VALID_DECISION_TYPES = frozenset({
    "classification", "routing", "generation", "tool_selection", "other",
})


@dataclass
class DecisionDriver:
    """A single factor that contributed to an agent decision (T \u2014 Transparency).

    ``weight`` and ``confidence`` must be in the range [0.0, 1.0].
    The sum of all ``weight`` values in a list should equal 1.0 but is
    not enforced here (enforcement is the caller's responsibility).
    """

    factor_name: str
    weight: float       # 0.0\u20131.0; fractional contribution to the overall decision
    contribution: float  # signed contribution to the final decision score
    evidence: str       # human-readable evidence string
    confidence: float   # 0.0\u20131.0

    def __post_init__(self) -> None:
        if not self.factor_name:
            raise ValueError("DecisionDriver.factor_name must be non-empty")
        if not (0.0 <= self.weight <= 1.0):
            raise ValueError("DecisionDriver.weight must be in [0.0, 1.0]")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("DecisionDriver.confidence must be in [0.0, 1.0]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "factor_name": self.factor_name,
            "weight": self.weight,
            "contribution": self.contribution,
            "evidence": self.evidence,
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionDriver:
        return cls(
            factor_name=data["factor_name"],
            weight=float(data["weight"]),
            contribution=float(data["contribution"]),
            evidence=data["evidence"],
            confidence=float(data["confidence"]),
        )


@dataclass
class DecisionPayload:
    """RFC-0001 SPANFORGE \u2014 payload for decision.* events.

    Captures every individual agent decision at inference time, including
    the full set of contributing decision drivers for T \u2014 Transparency.

    ``actor`` is an optional dict representation of an ActorContext and is
    intentionally typed as ``dict | None`` to avoid a circular import.
    """

    decision_id: str        # ULID
    agent_id: str
    decision_type: str      # classification | routing | generation | tool_selection | other
    input_summary: str
    output_summary: str
    confidence: float       # 0.0\u20131.0
    latency_ms: float
    rationale_hash: str     # SHA-256 of the full rationale text
    decision_drivers: list[DecisionDriver] = field(default_factory=list)
    actor: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.decision_id:
            raise ValueError("DecisionPayload.decision_id must be non-empty")
        if not self.agent_id:
            raise ValueError("DecisionPayload.agent_id must be non-empty")
        if self.decision_type not in _VALID_DECISION_TYPES:
            raise ValueError(
                f"DecisionPayload.decision_type must be one of {sorted(_VALID_DECISION_TYPES)}"
            )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("DecisionPayload.confidence must be in [0.0, 1.0]")
        if self.latency_ms < 0:
            raise ValueError("DecisionPayload.latency_ms must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "decision_id": self.decision_id,
            "agent_id": self.agent_id,
            "decision_type": self.decision_type,
            "input_summary": self.input_summary,
            "output_summary": self.output_summary,
            "confidence": self.confidence,
            "latency_ms": self.latency_ms,
            "rationale_hash": self.rationale_hash,
            "decision_drivers": [d.to_dict() for d in self.decision_drivers],
        }
        if self.actor is not None:
            d["actor"] = self.actor
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionPayload:
        drivers = [
            DecisionDriver.from_dict(dd)
            for dd in data.get("decision_drivers", [])
        ]
        return cls(
            decision_id=data["decision_id"],
            agent_id=data["agent_id"],
            decision_type=data["decision_type"],
            input_summary=data["input_summary"],
            output_summary=data["output_summary"],
            confidence=float(data["confidence"]),
            latency_ms=float(data["latency_ms"]),
            rationale_hash=data["rationale_hash"],
            decision_drivers=drivers,
            actor=data.get("actor"),
        )
