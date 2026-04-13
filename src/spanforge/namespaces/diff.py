"""spanforge.namespaces.diff — Diff payload types (RFC-0001).

Classes
-------
DiffComputedPayload         llm.diff.computed
DiffRegressionFlaggedPayload llm.diff.regression.flagged
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "DiffComputedPayload",
    "DiffRegressionFlaggedPayload",
]

_VALID_DIFF_TYPES = frozenset({"prompt", "response", "template", "token_usage", "cost"})
_VALID_ALGORITHMS = frozenset({
    "embedding_cosine", "levenshtein", "token_edit", "lcs", "semantic_embedding"
})
_VALID_SEVERITIES = frozenset({"low", "medium", "high", "critical"})


@dataclass
class DiffComputedPayload:
    """RFC-0001 — A diff was computed between two events."""

    ref_event_id: str
    target_event_id: str
    diff_type: str        # "prompt"|"response"|"template"|"token_usage"|"cost"
    similarity_score: float
    added_tokens: int | None = None
    removed_tokens: int | None = None
    diff_algorithm: str | None = None
    ref_content_hash: str | None = None    # 64 hex chars
    target_content_hash: str | None = None # 64 hex chars
    computation_duration_ms: float | None = None

    def __post_init__(self) -> None:
        if not self.ref_event_id:
            raise ValueError("DiffComputedPayload.ref_event_id must be non-empty")
        if not self.target_event_id:
            raise ValueError("DiffComputedPayload.target_event_id must be non-empty")
        if self.diff_type not in _VALID_DIFF_TYPES:
            raise ValueError(f"DiffComputedPayload.diff_type must be one of {sorted(_VALID_DIFF_TYPES)}")  # noqa: E501
        if not (0.0 <= self.similarity_score <= 1.0):
            raise ValueError("DiffComputedPayload.similarity_score must be in [0,1]")
        if self.diff_algorithm is not None and self.diff_algorithm not in _VALID_ALGORITHMS:
            raise ValueError(f"DiffComputedPayload.diff_algorithm must be one of {sorted(_VALID_ALGORITHMS)}")  # noqa: E501

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "ref_event_id": self.ref_event_id,
            "target_event_id": self.target_event_id,
            "diff_type": self.diff_type,
            "similarity_score": self.similarity_score,
        }
        if self.added_tokens is not None:
            d["added_tokens"] = self.added_tokens
        if self.removed_tokens is not None:
            d["removed_tokens"] = self.removed_tokens
        if self.diff_algorithm is not None:
            d["diff_algorithm"] = self.diff_algorithm
        if self.ref_content_hash is not None:
            d["ref_content_hash"] = self.ref_content_hash
        if self.target_content_hash is not None:
            d["target_content_hash"] = self.target_content_hash
        if self.computation_duration_ms is not None:
            d["computation_duration_ms"] = self.computation_duration_ms
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiffComputedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            ref_event_id=data["ref_event_id"],
            target_event_id=data["target_event_id"],
            diff_type=data["diff_type"],
            similarity_score=float(data["similarity_score"]),
            added_tokens=int(data["added_tokens"]) if "added_tokens" in data else None,
            removed_tokens=int(data["removed_tokens"]) if "removed_tokens" in data else None,
            diff_algorithm=data.get("diff_algorithm"),
            ref_content_hash=data.get("ref_content_hash"),
            target_content_hash=data.get("target_content_hash"),
            computation_duration_ms=float(data["computation_duration_ms"]) if "computation_duration_ms" in data else None,  # noqa: E501
        )


@dataclass
class DiffRegressionFlaggedPayload:
    """RFC-0001 — A diff score fell below the similarity threshold."""

    ref_event_id: str
    target_event_id: str
    diff_type: str
    similarity_score: float
    threshold: float
    severity: str  # "low"|"medium"|"high"|"critical"
    diff_event_id: str | None = None
    alert_target: str | None = None

    def __post_init__(self) -> None:
        if not self.ref_event_id:
            raise ValueError("DiffRegressionFlaggedPayload.ref_event_id must be non-empty")
        if not self.target_event_id:
            raise ValueError("DiffRegressionFlaggedPayload.target_event_id must be non-empty")
        if self.diff_type not in _VALID_DIFF_TYPES:
            raise ValueError(f"DiffRegressionFlaggedPayload.diff_type must be one of {sorted(_VALID_DIFF_TYPES)}")  # noqa: E501
        if not (0.0 <= self.similarity_score <= 1.0):
            raise ValueError("DiffRegressionFlaggedPayload.similarity_score must be in [0,1]")
        if not (0.0 <= self.threshold <= 1.0):
            raise ValueError("DiffRegressionFlaggedPayload.threshold must be in [0,1]")
        if self.severity not in _VALID_SEVERITIES:
            raise ValueError(f"DiffRegressionFlaggedPayload.severity must be one of {sorted(_VALID_SEVERITIES)}")  # noqa: E501

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "ref_event_id": self.ref_event_id,
            "target_event_id": self.target_event_id,
            "diff_type": self.diff_type,
            "similarity_score": self.similarity_score,
            "threshold": self.threshold,
            "severity": self.severity,
        }
        if self.diff_event_id is not None:
            d["diff_event_id"] = self.diff_event_id
        if self.alert_target is not None:
            d["alert_target"] = self.alert_target
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DiffRegressionFlaggedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            ref_event_id=data["ref_event_id"],
            target_event_id=data["target_event_id"],
            diff_type=data["diff_type"],
            similarity_score=float(data["similarity_score"]),
            threshold=float(data["threshold"]),
            severity=data["severity"],
            diff_event_id=data.get("diff_event_id"),
            alert_target=data.get("alert_target"),
        )
