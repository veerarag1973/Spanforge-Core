"""spanforge.namespaces.cost — Cost payload types (RFC-0001 §9).

Classes
-------
CostTokenRecordedPayload
    RFC §9.1 — cost recorded for a single model call.
CostSessionRecordedPayload
    RFC §9.2 — aggregate cost across a session.
CostAttributedPayload
    RFC §9.3 — cost attributed to a specific target.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spanforge.namespaces.trace import (
    CostBreakdown,
    ModelInfo,
    PricingTier,
    TokenUsage,
)

__all__ = [
    "CostAttributedPayload",
    "CostSessionRecordedPayload",
    "CostTokenRecordedPayload",
]

_VALID_ATTRIBUTION_TYPES = frozenset({"direct", "proportional", "estimated", "manual"})


@dataclass
class CostTokenRecordedPayload:
    """RFC-0001 §9.1 — Cost recorded for a single model call (one span).

    Used with event type: ``llm.cost.token.recorded``.
    """

    cost: CostBreakdown
    token_usage: TokenUsage
    model: ModelInfo
    pricing_tier: PricingTier | None = None
    span_id: str | None = None
    agent_run_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.cost, CostBreakdown):
            raise TypeError("CostTokenRecordedPayload.cost must be a CostBreakdown")
        if not isinstance(self.token_usage, TokenUsage):
            raise TypeError("CostTokenRecordedPayload.token_usage must be a TokenUsage")
        if not isinstance(self.model, ModelInfo):
            raise TypeError("CostTokenRecordedPayload.model must be a ModelInfo")

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "cost": self.cost.to_dict(),
            "token_usage": self.token_usage.to_dict(),
            "model": self.model.to_dict(),
        }
        if self.pricing_tier is not None:
            d["pricing_tier"] = self.pricing_tier.to_dict()
        if self.span_id is not None:
            d["span_id"] = self.span_id
        if self.agent_run_id is not None:
            d["agent_run_id"] = self.agent_run_id
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CostTokenRecordedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            cost=CostBreakdown.from_dict(data["cost"]),
            token_usage=TokenUsage.from_dict(data["token_usage"]),
            model=ModelInfo.from_dict(data["model"]),
            pricing_tier=PricingTier.from_dict(data["pricing_tier"]) if "pricing_tier" in data else None,  # noqa: E501
            span_id=data.get("span_id"),
            agent_run_id=data.get("agent_run_id"),
        )


@dataclass
class CostSessionRecordedPayload:
    """RFC-0001 §9.2 — Aggregate cost across a session.

    Used with event type: ``llm.cost.session.recorded``.
    A session is any arbitrary grouping (user session, request batch, experiment run).
    """

    total_cost: CostBreakdown
    total_token_usage: TokenUsage
    call_count: int
    session_duration_ms: float | None = None
    models_used: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.total_cost, CostBreakdown):
            raise TypeError("CostSessionRecordedPayload.total_cost must be a CostBreakdown")
        if not isinstance(self.total_token_usage, TokenUsage):
            raise TypeError("CostSessionRecordedPayload.total_token_usage must be a TokenUsage")
        if not isinstance(self.call_count, int) or self.call_count < 0:
            raise ValueError("CostSessionRecordedPayload.call_count must be a non-negative int")
        if self.session_duration_ms is not None and self.session_duration_ms < 0:
            raise ValueError("CostSessionRecordedPayload.session_duration_ms must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "total_cost": self.total_cost.to_dict(),
            "total_token_usage": self.total_token_usage.to_dict(),
            "call_count": self.call_count,
        }
        if self.session_duration_ms is not None:
            d["session_duration_ms"] = self.session_duration_ms
        if self.models_used:
            d["models_used"] = list(self.models_used)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CostSessionRecordedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            total_cost=CostBreakdown.from_dict(data["total_cost"]),
            total_token_usage=TokenUsage.from_dict(data["total_token_usage"]),
            call_count=int(data["call_count"]),
            session_duration_ms=float(data["session_duration_ms"]) if "session_duration_ms" in data else None,  # noqa: E501
            models_used=list(data.get("models_used", [])),
        )


@dataclass
class CostAttributedPayload:
    """RFC-0001 §9.3 — Cost attributed to a specific target.

    Used with event type: ``llm.cost.attributed``.
    ``attribution_type`` describes how the cost share was computed.
    """

    cost: CostBreakdown
    attribution_target: str
    attribution_type: str  # "direct"|"proportional"|"estimated"|"manual"
    source_event_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.cost, CostBreakdown):
            raise TypeError("CostAttributedPayload.cost must be a CostBreakdown")
        if not isinstance(self.attribution_target, str) or not self.attribution_target:
            raise ValueError("CostAttributedPayload.attribution_target must be a non-empty string")
        if self.attribution_type not in _VALID_ATTRIBUTION_TYPES:
            raise ValueError(
                f"CostAttributedPayload.attribution_type must be one of {sorted(_VALID_ATTRIBUTION_TYPES)}"  # noqa: E501
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "cost": self.cost.to_dict(),
            "attribution_target": self.attribution_target,
            "attribution_type": self.attribution_type,
        }
        if self.source_event_ids:
            d["source_event_ids"] = list(self.source_event_ids)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CostAttributedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            cost=CostBreakdown.from_dict(data["cost"]),
            attribution_target=data["attribution_target"],
            attribution_type=data["attribution_type"],
            source_event_ids=list(data.get("source_event_ids", [])),
        )
