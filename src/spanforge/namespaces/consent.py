"""spanforge.namespaces.consent — Consent namespace payload types (RFC-0001 SPANFORGE).

Classes
-------
ConsentPayload    consent.granted / consent.revoked / consent.violation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = ["ConsentPayload"]

_VALID_STATUSES = frozenset({"granted", "revoked", "violation"})
_VALID_LEGAL_BASES = frozenset(
    {
        "consent",
        "contract",
        "legal_obligation",
        "vital_interest",
        "public_task",
        "legitimate_interest",
    }
)


@dataclass
class ConsentPayload:
    """RFC-0001 SPANFORGE — payload for consent.* events.

    Tracks data-subject consent grants, revocations, and boundary violations
    for GDPR Art. 6/7 and EU AI Act compliance (U — User Rights).
    """

    subject_id: str
    scope: str
    purpose: str
    status: Literal["granted", "revoked", "violation"]
    legal_basis: str = "consent"
    expiry: str | None = None  # ISO 8601 timestamp
    agent_id: str | None = None
    violation_detail: str | None = None
    data_categories: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.subject_id:
            raise ValueError("ConsentPayload.subject_id must be non-empty")
        if not self.scope:
            raise ValueError("ConsentPayload.scope must be non-empty")
        if not self.purpose:
            raise ValueError("ConsentPayload.purpose must be non-empty")
        if self.status not in _VALID_STATUSES:
            raise ValueError(f"ConsentPayload.status must be one of {sorted(_VALID_STATUSES)}")
        if self.legal_basis not in _VALID_LEGAL_BASES:
            raise ValueError(
                f"ConsentPayload.legal_basis must be one of {sorted(_VALID_LEGAL_BASES)}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        d: dict[str, Any] = {
            "subject_id": self.subject_id,
            "scope": self.scope,
            "purpose": self.purpose,
            "status": self.status,
            "legal_basis": self.legal_basis,
        }
        if self.expiry is not None:
            d["expiry"] = self.expiry
        if self.agent_id is not None:
            d["agent_id"] = self.agent_id
        if self.violation_detail is not None:
            d["violation_detail"] = self.violation_detail
        if self.data_categories:
            d["data_categories"] = list(self.data_categories)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConsentPayload:
        """Deserialise from a plain dict."""
        return cls(
            subject_id=data["subject_id"],
            scope=data["scope"],
            purpose=data["purpose"],
            status=data["status"],
            legal_basis=data.get("legal_basis", "consent"),
            expiry=data.get("expiry"),
            agent_id=data.get("agent_id"),
            violation_detail=data.get("violation_detail"),
            data_categories=list(data.get("data_categories", [])),
        )
