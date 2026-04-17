"""spanforge.namespaces.latency \u2014 Latency namespace payload types (RFC-0001 SPANFORGE).

Classes
-------
LatencyPayload  latency.sample / latency.sla_breach
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["LatencyPayload"]


@dataclass
class LatencyPayload:
    """RFC-0001 SPANFORGE \u2014 payload for latency.* events.

    Captures end-to-end response time, per-step breakdown, and SLA compliance
    tracking (T \u2014 Traceability / S \u2014 Safety Guardrails).
    """

    agent_id: str
    operation: str
    latency_ms: float
    sla_target_ms: float
    sla_met: bool
    p50_ms: float | None = None
    p95_ms: float | None = None
    p99_ms: float | None = None

    def __post_init__(self) -> None:
        if not self.agent_id:
            raise ValueError("LatencyPayload.agent_id must be non-empty")
        if not self.operation:
            raise ValueError("LatencyPayload.operation must be non-empty")
        if self.latency_ms < 0:
            raise ValueError("LatencyPayload.latency_ms must be >= 0")
        if self.sla_target_ms <= 0:
            raise ValueError("LatencyPayload.sla_target_ms must be > 0")

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        d: dict[str, Any] = {
            "agent_id": self.agent_id,
            "operation": self.operation,
            "latency_ms": self.latency_ms,
            "sla_target_ms": self.sla_target_ms,
            "sla_met": self.sla_met,
        }
        if self.p50_ms is not None:
            d["p50_ms"] = self.p50_ms
        if self.p95_ms is not None:
            d["p95_ms"] = self.p95_ms
        if self.p99_ms is not None:
            d["p99_ms"] = self.p99_ms
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> LatencyPayload:
        """Deserialise from a plain dict."""
        return cls(
            agent_id=data["agent_id"],
            operation=data["operation"],
            latency_ms=float(data["latency_ms"]),
            sla_target_ms=float(data["sla_target_ms"]),
            sla_met=bool(data["sla_met"]),
            p50_ms=data.get("p50_ms"),
            p95_ms=data.get("p95_ms"),
            p99_ms=data.get("p99_ms"),
        )
