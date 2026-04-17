"""spanforge.namespaces.guard — Guard payload types (RFC-0001).

A single ``GuardPayload`` class is used for all four guard event types.

Classes
-------
GuardPayload    llm.guard.input.blocked, llm.guard.input.passed,
                llm.guard.output.blocked, llm.guard.output.passed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["GuardPayload"]

_VALID_DIRECTIONS = frozenset({"input", "output"})
_VALID_ACTIONS = frozenset({"blocked", "passed", "flagged", "modified", "escalated"})


@dataclass
class GuardPayload:
    """RFC-0001 — Result of a guard classifier applied to LLM input or output.

    Used with all four guard event types:
    ``llm.guard.input.blocked``, ``llm.guard.input.passed``,
    ``llm.guard.output.blocked``, ``llm.guard.output.passed``.

    ``content_hash`` stores a SHA-256 hash of the content that was classified.
    Raw content MUST NOT be stored.
    """

    classifier: str
    direction: str  # "input" | "output"
    action: str  # "blocked"|"passed"|"flagged"|"modified"|"escalated"
    score: float
    score_min: float | None = None
    score_max: float | None = None
    threshold: float | None = None
    categories: list[str] = field(default_factory=list)
    triggered_categories: list[str] = field(default_factory=list)
    span_id: str | None = None
    latency_ms: float | None = None
    policy_id: str | None = None
    content_hash: str | None = None  # 64 lowercase hex chars, SHA-256

    def __post_init__(self) -> None:
        if not isinstance(self.classifier, str) or not self.classifier:
            raise ValueError("GuardPayload.classifier must be non-empty")
        if self.direction not in _VALID_DIRECTIONS:
            raise ValueError(f"GuardPayload.direction must be one of {sorted(_VALID_DIRECTIONS)}")
        if self.action not in _VALID_ACTIONS:
            raise ValueError(f"GuardPayload.action must be one of {sorted(_VALID_ACTIONS)}")
        if not isinstance(self.score, (int, float)):
            raise ValueError("GuardPayload.score must be a number")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValueError("GuardPayload.latency_ms must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "classifier": self.classifier,
            "direction": self.direction,
            "action": self.action,
            "score": self.score,
        }
        if self.score_min is not None:
            d["score_min"] = self.score_min
        if self.score_max is not None:
            d["score_max"] = self.score_max
        if self.threshold is not None:
            d["threshold"] = self.threshold
        if self.categories:
            d["categories"] = list(self.categories)
        if self.triggered_categories:
            d["triggered_categories"] = list(self.triggered_categories)
        if self.span_id is not None:
            d["span_id"] = self.span_id
        if self.latency_ms is not None:
            d["latency_ms"] = self.latency_ms
        if self.policy_id is not None:
            d["policy_id"] = self.policy_id
        if self.content_hash is not None:
            d["content_hash"] = self.content_hash
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GuardPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            classifier=data["classifier"],
            direction=data["direction"],
            action=data["action"],
            score=float(data["score"]),
            score_min=float(data["score_min"]) if "score_min" in data else None,
            score_max=float(data["score_max"]) if "score_max" in data else None,
            threshold=float(data["threshold"]) if "threshold" in data else None,
            categories=list(data.get("categories", [])),
            triggered_categories=list(data.get("triggered_categories", [])),
            span_id=data.get("span_id"),
            latency_ms=float(data["latency_ms"]) if "latency_ms" in data else None,
            policy_id=data.get("policy_id"),
            content_hash=data.get("content_hash"),
        )
