"""spanforge.namespaces.tool_call \u2014 Tool call namespace payload types (RFC-0001 SPANFORGE).

Classes
-------
ToolCallPayload     tool_call.invoked / tool_call.completed / tool_call.failed
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = ["ToolCallPayload"]

_VALID_STATUSES = frozenset({"success", "failure", "timeout"})


@dataclass
class ToolCallPayload:
    """RFC-0001 SPANFORGE \u2014 payload for tool_call.* events.

    Captures all external tool invocations with inputs, outputs, latency, and
    consent-check status (U \u2014 User Rights).
    """

    call_id: str
    tool_name: str
    latency_ms: float
    status: Literal["success", "failure", "timeout"]
    consent_checked: bool
    tool_version: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not self.call_id:
            raise ValueError("ToolCallPayload.call_id must be non-empty")
        if not self.tool_name:
            raise ValueError("ToolCallPayload.tool_name must be non-empty")
        if self.status not in _VALID_STATUSES:
            raise ValueError(
                f"ToolCallPayload.status must be one of {sorted(_VALID_STATUSES)}"
            )
        if self.latency_ms < 0:
            raise ValueError("ToolCallPayload.latency_ms must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "latency_ms": self.latency_ms,
            "status": self.status,
            "consent_checked": self.consent_checked,
            "inputs": self.inputs,
        }
        if self.tool_version is not None:
            d["tool_version"] = self.tool_version
        if self.outputs is not None:
            d["outputs"] = self.outputs
        if self.error_message is not None:
            d["error_message"] = self.error_message
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ToolCallPayload:
        return cls(
            call_id=data["call_id"],
            tool_name=data["tool_name"],
            latency_ms=float(data["latency_ms"]),
            status=data["status"],
            consent_checked=bool(data["consent_checked"]),
            tool_version=data.get("tool_version"),
            inputs=dict(data.get("inputs", {})),
            outputs=data.get("outputs"),
            error_message=data.get("error_message"),
        )
