"""spanforge.namespaces.drift \u2014 Drift namespace payload types (RFC-0001 SPANFORGE).

Classes
-------
DriftPayload    drift.detected / drift.threshold_breach / drift.resolved
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

__all__ = ["DriftPayload"]

_VALID_STATUSES = frozenset({"detected", "threshold_breach", "resolved"})


@dataclass
class DriftPayload:
    """RFC-0001 SPANFORGE \u2014 payload for drift.* events.

    Captures Z-score and KL-divergence statistical drift signals against the
    deployment baseline (T \u2014 Traceability).
    """

    metric_name: str
    agent_id: str
    current_value: float
    baseline_mean: float
    baseline_stddev: float
    z_score: float
    threshold: float
    window_seconds: int
    status: Literal["detected", "threshold_breach", "resolved"]
    kl_divergence: float | None = None

    def __post_init__(self) -> None:
        if not self.metric_name:
            raise ValueError("DriftPayload.metric_name must be non-empty")
        if not self.agent_id:
            raise ValueError("DriftPayload.agent_id must be non-empty")
        if self.status not in _VALID_STATUSES:
            raise ValueError(
                f"DriftPayload.status must be one of {sorted(_VALID_STATUSES)}"
            )
        if self.window_seconds <= 0:
            raise ValueError("DriftPayload.window_seconds must be > 0")
        if self.baseline_stddev < 0:
            raise ValueError("DriftPayload.baseline_stddev must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "metric_name": self.metric_name,
            "agent_id": self.agent_id,
            "current_value": self.current_value,
            "baseline_mean": self.baseline_mean,
            "baseline_stddev": self.baseline_stddev,
            "z_score": self.z_score,
            "threshold": self.threshold,
            "window_seconds": self.window_seconds,
            "status": self.status,
        }
        if self.kl_divergence is not None:
            d["kl_divergence"] = self.kl_divergence
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DriftPayload:
        return cls(
            metric_name=data["metric_name"],
            agent_id=data["agent_id"],
            current_value=float(data["current_value"]),
            baseline_mean=float(data["baseline_mean"]),
            baseline_stddev=float(data["baseline_stddev"]),
            z_score=float(data["z_score"]),
            threshold=float(data["threshold"]),
            window_seconds=int(data["window_seconds"]),
            status=data["status"],
            kl_divergence=data.get("kl_divergence"),
        )
