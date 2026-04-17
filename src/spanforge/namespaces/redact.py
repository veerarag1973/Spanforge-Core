"""spanforge.namespaces.redact — Redaction payload types (RFC-0001).

Classes
-------
RedactPiiDetectedPayload    llm.redact.pii.detected
RedactPhiDetectedPayload    llm.redact.phi.detected
RedactAppliedPayload        llm.redact.applied
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "RedactAppliedPayload",
    "RedactPhiDetectedPayload",
    "RedactPiiDetectedPayload",
]

_VALID_SENSITIVITY_LEVELS = frozenset({"LOW", "MEDIUM", "HIGH", "PII", "PHI"})


@dataclass
class RedactPiiDetectedPayload:
    """RFC-0001 — PII was detected in an LLM input or output field."""

    detected_categories: list[str]  # minItems=1 — e.g. ["email", "phone"]
    field_names: list[str]  # minItems=1 — field paths where PII found
    sensitivity_level: str  # "LOW"|"MEDIUM"|"HIGH"|"PII"|"PHI"
    detection_count: int | None = None
    detector: str | None = None
    subject_event_id: str | None = None

    def __post_init__(self) -> None:
        if not self.detected_categories:
            raise ValueError("RedactPiiDetectedPayload.detected_categories must be non-empty")
        if not self.field_names:
            raise ValueError("RedactPiiDetectedPayload.field_names must be non-empty")
        if self.sensitivity_level not in _VALID_SENSITIVITY_LEVELS:
            raise ValueError(
                f"RedactPiiDetectedPayload.sensitivity_level must be one of {sorted(_VALID_SENSITIVITY_LEVELS)}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "detected_categories": list(self.detected_categories),
            "field_names": list(self.field_names),
            "sensitivity_level": self.sensitivity_level,
        }
        if self.detection_count is not None:
            d["detection_count"] = self.detection_count
        if self.detector is not None:
            d["detector"] = self.detector
        if self.subject_event_id is not None:
            d["subject_event_id"] = self.subject_event_id
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RedactPiiDetectedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            detected_categories=list(data["detected_categories"]),
            field_names=list(data["field_names"]),
            sensitivity_level=data["sensitivity_level"],
            detection_count=int(data["detection_count"]) if "detection_count" in data else None,
            detector=data.get("detector"),
            subject_event_id=data.get("subject_event_id"),
        )


@dataclass
class RedactPhiDetectedPayload:
    """RFC-0001 — PHI was detected (HIPAA-covered health information).

    ``sensitivity_level`` MUST always be ``"PHI"`` for this payload type.
    """

    detected_categories: list[str]
    field_names: list[str]
    sensitivity_level: str = "PHI"  # MUST be "PHI"
    detection_count: int | None = None
    detector: str | None = None
    subject_event_id: str | None = None
    hipaa_covered: bool | None = None

    def __post_init__(self) -> None:
        if not self.detected_categories:
            raise ValueError("RedactPhiDetectedPayload.detected_categories must be non-empty")
        if not self.field_names:
            raise ValueError("RedactPhiDetectedPayload.field_names must be non-empty")
        if self.sensitivity_level != "PHI":
            raise ValueError("RedactPhiDetectedPayload.sensitivity_level MUST be 'PHI'")

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "detected_categories": list(self.detected_categories),
            "field_names": list(self.field_names),
            "sensitivity_level": self.sensitivity_level,
        }
        if self.detection_count is not None:
            d["detection_count"] = self.detection_count
        if self.detector is not None:
            d["detector"] = self.detector
        if self.subject_event_id is not None:
            d["subject_event_id"] = self.subject_event_id
        if self.hipaa_covered is not None:
            d["hipaa_covered"] = self.hipaa_covered
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RedactPhiDetectedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            detected_categories=list(data["detected_categories"]),
            field_names=list(data["field_names"]),
            sensitivity_level=data.get("sensitivity_level", "PHI"),
            detection_count=int(data["detection_count"]) if "detection_count" in data else None,
            detector=data.get("detector"),
            subject_event_id=data.get("subject_event_id"),
            hipaa_covered=bool(data["hipaa_covered"]) if "hipaa_covered" in data else None,
        )


@dataclass
class RedactAppliedPayload:
    """RFC-0001 — A redaction policy was applied to one or more fields."""

    policy_min_sensitivity: str  # "LOW"|"MEDIUM"|"HIGH"|"PII"|"PHI"
    redacted_by: str
    redacted_count: int
    redacted_field_names: list[str] = field(default_factory=list)
    subject_event_id: str | None = None
    verified: bool | None = None

    def __post_init__(self) -> None:
        if self.policy_min_sensitivity not in _VALID_SENSITIVITY_LEVELS:
            raise ValueError(
                f"RedactAppliedPayload.policy_min_sensitivity must be one of {sorted(_VALID_SENSITIVITY_LEVELS)}"
            )
        if not isinstance(self.redacted_by, str) or not self.redacted_by:
            raise ValueError("RedactAppliedPayload.redacted_by must be non-empty")
        if not isinstance(self.redacted_count, int) or self.redacted_count < 0:
            raise ValueError("RedactAppliedPayload.redacted_count must be a non-negative int")

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "policy_min_sensitivity": self.policy_min_sensitivity,
            "redacted_by": self.redacted_by,
            "redacted_count": self.redacted_count,
        }
        if self.redacted_field_names:
            d["redacted_field_names"] = list(self.redacted_field_names)
        if self.subject_event_id is not None:
            d["subject_event_id"] = self.subject_event_id
        if self.verified is not None:
            d["verified"] = self.verified
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RedactAppliedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            policy_min_sensitivity=data["policy_min_sensitivity"],
            redacted_by=data["redacted_by"],
            redacted_count=int(data["redacted_count"]),
            redacted_field_names=list(data.get("redacted_field_names", [])),
            subject_event_id=data.get("subject_event_id"),
            verified=bool(data["verified"]) if "verified" in data else None,
        )
