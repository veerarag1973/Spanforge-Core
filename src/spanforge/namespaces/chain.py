"""spanforge.namespaces.chain \u2014 Chain namespace payload types (RFC-0001 SPANFORGE).

Classes
-------
ChainPayload    chain.started / chain.step_completed / chain.completed / chain.failed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["ChainPayload"]


@dataclass
class ChainPayload:
    """RFC-0001 SPANFORGE \u2014 payload for chain.* events.

    Captures multi-step prompt chain state: step sequence, inter-step data
    flow references, and cumulative error/cost/latency propagation.
    """

    chain_id: str
    step_index: int
    step_name: str
    cumulative_latency_ms: float
    cumulative_token_cost: float
    error_propagated: bool
    total_steps: int | None = None
    input_refs: list[str] = field(default_factory=list)  # event ULIDs of inputs
    output_refs: list[str] = field(default_factory=list)  # event ULIDs of outputs

    def __post_init__(self) -> None:
        if not self.chain_id:
            raise ValueError("ChainPayload.chain_id must be non-empty")
        if self.step_index < 0:
            raise ValueError("ChainPayload.step_index must be >= 0")
        if not self.step_name:
            raise ValueError("ChainPayload.step_name must be non-empty")
        if self.cumulative_latency_ms < 0:
            raise ValueError("ChainPayload.cumulative_latency_ms must be >= 0")
        if self.cumulative_token_cost < 0:
            raise ValueError("ChainPayload.cumulative_token_cost must be >= 0")
        if self.total_steps is not None and self.total_steps < 1:
            raise ValueError("ChainPayload.total_steps must be >= 1")

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        d: dict[str, Any] = {
            "chain_id": self.chain_id,
            "step_index": self.step_index,
            "step_name": self.step_name,
            "cumulative_latency_ms": self.cumulative_latency_ms,
            "cumulative_token_cost": self.cumulative_token_cost,
            "error_propagated": self.error_propagated,
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
        }
        if self.total_steps is not None:
            d["total_steps"] = self.total_steps
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChainPayload:
        """Deserialise from a plain dict."""
        return cls(
            chain_id=data["chain_id"],
            step_index=int(data["step_index"]),
            step_name=data["step_name"],
            cumulative_latency_ms=float(data["cumulative_latency_ms"]),
            cumulative_token_cost=float(data["cumulative_token_cost"]),
            error_propagated=bool(data["error_propagated"]),
            total_steps=data.get("total_steps"),
            input_refs=list(data.get("input_refs", [])),
            output_refs=list(data.get("output_refs", [])),
        )
