"""spanforge.namespaces.confidence \u2014 Confidence namespace payload types (RFC-0001 SPANFORGE).

Classes
-------
ConfidencePayload   confidence.sample / confidence.threshold_breach
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["ConfidencePayload"]


@dataclass
class ConfidencePayload:
    """RFC-0001 SPANFORGE \u2014 payload for confidence.* events.

    Tracks output confidence score distributions per decision type and model,
    measured against the deployment baseline (T \u2014 Traceability).
    """

    model_id: str
    decision_type: str
    score: float  # 0.0\u20131.0
    threshold_breached: bool
    sampled_at: str  # ISO 8601 timestamp
    baseline_mean: float | None = None
    baseline_stddev: float | None = None
    z_score: float | None = None

    def __post_init__(self) -> None:
        if not self.model_id:
            raise ValueError("ConfidencePayload.model_id must be non-empty")
        if not self.decision_type:
            raise ValueError("ConfidencePayload.decision_type must be non-empty")
        if not (0.0 <= self.score <= 1.0):
            raise ValueError("ConfidencePayload.score must be in [0.0, 1.0]")
        if not self.sampled_at:
            raise ValueError("ConfidencePayload.sampled_at must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        d: dict[str, Any] = {
            "model_id": self.model_id,
            "decision_type": self.decision_type,
            "score": self.score,
            "threshold_breached": self.threshold_breached,
            "sampled_at": self.sampled_at,
        }
        if self.baseline_mean is not None:
            d["baseline_mean"] = self.baseline_mean
        if self.baseline_stddev is not None:
            d["baseline_stddev"] = self.baseline_stddev
        if self.z_score is not None:
            d["z_score"] = self.z_score
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConfidencePayload:
        """Deserialise from a plain dict."""
        return cls(
            model_id=data["model_id"],
            decision_type=data["decision_type"],
            score=float(data["score"]),
            threshold_breached=bool(data["threshold_breached"]),
            sampled_at=data["sampled_at"],
            baseline_mean=data.get("baseline_mean"),
            baseline_stddev=data.get("baseline_stddev"),
            z_score=data.get("z_score"),
        )
