"""spanforge.namespaces.fence — Fence payload types (RFC-0001).

Classes
-------
FenceValidatedPayload           llm.fence.validated
FenceRetryTriggeredPayload      llm.fence.retry.triggered
FenceMaxRetriesExceededPayload  llm.fence.max_retries.exceeded
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from spanforge.namespaces.trace import CostBreakdown

__all__ = [
    "FenceMaxRetriesExceededPayload",
    "FenceRetryTriggeredPayload",
    "FenceValidatedPayload",
]

_VALID_OUTPUT_TYPES = frozenset({"json_schema", "pydantic", "regex", "xml", "custom"})


@dataclass
class FenceValidatedPayload:
    """RFC-0001 — Structured output passed validation on a given attempt."""

    fence_id: str
    schema_name: str
    attempt: int
    output_type: str | None = None  # "json_schema"|"pydantic"|"regex"|"xml"|"custom"
    span_id: str | None = None
    validation_duration_ms: float | None = None

    def __post_init__(self) -> None:
        if not self.fence_id:
            raise ValueError("FenceValidatedPayload.fence_id must be non-empty")
        if not self.schema_name:
            raise ValueError("FenceValidatedPayload.schema_name must be non-empty")
        if not isinstance(self.attempt, int) or self.attempt < 1:
            raise ValueError("FenceValidatedPayload.attempt must be a positive int")
        if self.output_type is not None and self.output_type not in _VALID_OUTPUT_TYPES:
            raise ValueError(
                f"FenceValidatedPayload.output_type must be one of {sorted(_VALID_OUTPUT_TYPES)}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "fence_id": self.fence_id,
            "schema_name": self.schema_name,
            "attempt": self.attempt,
        }
        if self.output_type is not None:
            d["output_type"] = self.output_type
        if self.span_id is not None:
            d["span_id"] = self.span_id
        if self.validation_duration_ms is not None:
            d["validation_duration_ms"] = self.validation_duration_ms
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FenceValidatedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            fence_id=data["fence_id"],
            schema_name=data["schema_name"],
            attempt=int(data["attempt"]),
            output_type=data.get("output_type"),
            span_id=data.get("span_id"),
            validation_duration_ms=float(data["validation_duration_ms"])
            if "validation_duration_ms" in data
            else None,
        )


@dataclass
class FenceRetryTriggeredPayload:
    """RFC-0001 — A validation failure triggered a retry."""

    fence_id: str
    schema_name: str
    attempt: int
    max_attempts: int
    violation_summary: str
    output_type: str | None = None
    span_id: str | None = None

    def __post_init__(self) -> None:
        if not self.fence_id:
            raise ValueError("FenceRetryTriggeredPayload.fence_id must be non-empty")
        if not self.schema_name:
            raise ValueError("FenceRetryTriggeredPayload.schema_name must be non-empty")
        if not isinstance(self.attempt, int) or self.attempt < 1:
            raise ValueError("FenceRetryTriggeredPayload.attempt must be a positive int")
        if not isinstance(self.max_attempts, int) or self.max_attempts < 1:
            raise ValueError("FenceRetryTriggeredPayload.max_attempts must be a positive int")
        if not self.violation_summary:
            raise ValueError("FenceRetryTriggeredPayload.violation_summary must be non-empty")
        if self.output_type is not None and self.output_type not in _VALID_OUTPUT_TYPES:
            raise ValueError(
                f"FenceRetryTriggeredPayload.output_type must be one of {sorted(_VALID_OUTPUT_TYPES)}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "fence_id": self.fence_id,
            "schema_name": self.schema_name,
            "attempt": self.attempt,
            "max_attempts": self.max_attempts,
            "violation_summary": self.violation_summary,
        }
        if self.output_type is not None:
            d["output_type"] = self.output_type
        if self.span_id is not None:
            d["span_id"] = self.span_id
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FenceRetryTriggeredPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            fence_id=data["fence_id"],
            schema_name=data["schema_name"],
            attempt=int(data["attempt"]),
            max_attempts=int(data["max_attempts"]),
            violation_summary=data["violation_summary"],
            output_type=data.get("output_type"),
            span_id=data.get("span_id"),
        )


@dataclass
class FenceMaxRetriesExceededPayload:
    """RFC-0001 — All retry attempts exhausted; output remains invalid."""

    fence_id: str
    schema_name: str
    attempts_made: int
    final_violation_summary: str
    output_type: str | None = None
    span_id: str | None = None
    total_extra_cost: CostBreakdown | None = None

    def __post_init__(self) -> None:
        if not self.fence_id:
            raise ValueError("FenceMaxRetriesExceededPayload.fence_id must be non-empty")
        if not self.schema_name:
            raise ValueError("FenceMaxRetriesExceededPayload.schema_name must be non-empty")
        if not isinstance(self.attempts_made, int) or self.attempts_made < 1:
            raise ValueError("FenceMaxRetriesExceededPayload.attempts_made must be a positive int")
        if not self.final_violation_summary:
            raise ValueError(
                "FenceMaxRetriesExceededPayload.final_violation_summary must be non-empty"
            )
        if self.output_type is not None and self.output_type not in _VALID_OUTPUT_TYPES:
            raise ValueError(
                f"FenceMaxRetriesExceededPayload.output_type must be one of {sorted(_VALID_OUTPUT_TYPES)}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "fence_id": self.fence_id,
            "schema_name": self.schema_name,
            "attempts_made": self.attempts_made,
            "final_violation_summary": self.final_violation_summary,
        }
        if self.output_type is not None:
            d["output_type"] = self.output_type
        if self.span_id is not None:
            d["span_id"] = self.span_id
        if self.total_extra_cost is not None:
            d["total_extra_cost"] = self.total_extra_cost.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FenceMaxRetriesExceededPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            fence_id=data["fence_id"],
            schema_name=data["schema_name"],
            attempts_made=int(data["attempts_made"]),
            final_violation_summary=data["final_violation_summary"],
            output_type=data.get("output_type"),
            span_id=data.get("span_id"),
            total_extra_cost=CostBreakdown.from_dict(data["total_extra_cost"])
            if "total_extra_cost" in data
            else None,
        )
