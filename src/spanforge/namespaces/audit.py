"""spanforge.namespaces.audit — Audit chain payload types (RFC-0001 §11 + RFC-0001 SPANFORGE).

Classes
-------
AuditKeyRotatedPayload      llm.audit.key.rotated
AuditChainVerifiedPayload   llm.audit.chain.verified
AuditChainTamperedPayload   llm.audit.chain.tampered
AuditChainPayload           audit.event_signed / audit.chain_verified / audit.tamper_detected
                            RFC-0001 SPANFORGE tamper-evident cross-reference chain
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "AuditChainPayload",
    "AuditChainTamperedPayload",
    "AuditChainVerifiedPayload",
    "AuditKeyRotatedPayload",
]

_VALID_ROTATION_REASONS = frozenset({
    "scheduled", "suspected_compromise", "policy_update", "key_expiry", "manual"
})
_VALID_SEVERITIES = frozenset({"low", "medium", "high", "critical"})


@dataclass
class AuditKeyRotatedPayload:
    """RFC-0001 §11.5 — An HMAC signing key was rotated.

    ``key_algorithm`` defaults to ``"HMAC-SHA256"`` (the only algorithm
    mandated by the RFC).  ``effective_from_event_id`` is the ULID of the
    first event signed with the new key.
    """

    key_id: str
    previous_key_id: str
    rotated_at: str   # ISO 8601 timestamp with exactly 6 decimal places
    rotated_by: str
    rotation_reason: str | None = None
    key_algorithm: str = "HMAC-SHA256"
    effective_from_event_id: str | None = None  # ULID

    def __post_init__(self) -> None:
        if not self.key_id:
            raise ValueError("AuditKeyRotatedPayload.key_id must be non-empty")
        if not self.previous_key_id:
            raise ValueError("AuditKeyRotatedPayload.previous_key_id must be non-empty")
        if not self.rotated_at:
            raise ValueError("AuditKeyRotatedPayload.rotated_at must be non-empty")
        if not self.rotated_by:
            raise ValueError("AuditKeyRotatedPayload.rotated_by must be non-empty")
        if self.rotation_reason is not None and self.rotation_reason not in _VALID_ROTATION_REASONS:
            raise ValueError(
                f"AuditKeyRotatedPayload.rotation_reason must be one of {sorted(_VALID_ROTATION_REASONS)}"  # noqa: E501
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "key_id": self.key_id,
            "previous_key_id": self.previous_key_id,
            "rotated_at": self.rotated_at,
            "rotated_by": self.rotated_by,
            "key_algorithm": self.key_algorithm,
        }
        if self.rotation_reason is not None:
            d["rotation_reason"] = self.rotation_reason
        if self.effective_from_event_id is not None:
            d["effective_from_event_id"] = self.effective_from_event_id
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditKeyRotatedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            key_id=data["key_id"],
            previous_key_id=data["previous_key_id"],
            rotated_at=data["rotated_at"],
            rotated_by=data["rotated_by"],
            rotation_reason=data.get("rotation_reason"),
            key_algorithm=data.get("key_algorithm", "HMAC-SHA256"),
            effective_from_event_id=data.get("effective_from_event_id"),
        )


@dataclass
class AuditChainVerifiedPayload:
    """RFC-0001 §11 — An audit chain segment was verified intact."""

    verified_from_event_id: str
    verified_to_event_id: str
    event_count: int
    verified_at: str
    verified_by: str

    def __post_init__(self) -> None:
        if not self.verified_from_event_id:
            raise ValueError("AuditChainVerifiedPayload.verified_from_event_id must be non-empty")
        if not self.verified_to_event_id:
            raise ValueError("AuditChainVerifiedPayload.verified_to_event_id must be non-empty")
        if not isinstance(self.event_count, int) or self.event_count < 0:
            raise ValueError("AuditChainVerifiedPayload.event_count must be a non-negative int")
        if not self.verified_at:
            raise ValueError("AuditChainVerifiedPayload.verified_at must be non-empty")
        if not self.verified_by:
            raise ValueError("AuditChainVerifiedPayload.verified_by must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        return {
            "verified_from_event_id": self.verified_from_event_id,
            "verified_to_event_id": self.verified_to_event_id,
            "event_count": self.event_count,
            "verified_at": self.verified_at,
            "verified_by": self.verified_by,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditChainVerifiedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            verified_from_event_id=data["verified_from_event_id"],
            verified_to_event_id=data["verified_to_event_id"],
            event_count=int(data["event_count"]),
            verified_at=data["verified_at"],
            verified_by=data["verified_by"],
        )


@dataclass
class AuditChainTamperedPayload:
    """RFC-0001 §11 — Tampering or a gap was detected in the audit chain."""

    first_tampered_event_id: str
    tampered_count: int
    detected_at: str
    detected_by: str
    gap_count: int | None = None
    gap_prev_ids: list[str] = field(default_factory=list)
    severity: str | None = None  # "low"|"medium"|"high"|"critical"

    def __post_init__(self) -> None:
        if not self.first_tampered_event_id:
            raise ValueError("AuditChainTamperedPayload.first_tampered_event_id must be non-empty")
        if not isinstance(self.tampered_count, int) or self.tampered_count < 0:
            raise ValueError("AuditChainTamperedPayload.tampered_count must be a non-negative int")
        if not self.detected_at:
            raise ValueError("AuditChainTamperedPayload.detected_at must be non-empty")
        if not self.detected_by:
            raise ValueError("AuditChainTamperedPayload.detected_by must be non-empty")
        if self.severity is not None and self.severity not in _VALID_SEVERITIES:
            raise ValueError(f"AuditChainTamperedPayload.severity must be one of {sorted(_VALID_SEVERITIES)}")  # noqa: E501

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "first_tampered_event_id": self.first_tampered_event_id,
            "tampered_count": self.tampered_count,
            "detected_at": self.detected_at,
            "detected_by": self.detected_by,
        }
        if self.gap_count is not None:
            d["gap_count"] = self.gap_count
        if self.gap_prev_ids:
            d["gap_prev_ids"] = list(self.gap_prev_ids)
        if self.severity is not None:
            d["severity"] = self.severity
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditChainTamperedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            first_tampered_event_id=data["first_tampered_event_id"],
            tampered_count=int(data["tampered_count"]),
            detected_at=data["detected_at"],
            detected_by=data["detected_by"],
            gap_count=int(data["gap_count"]) if "gap_count" in data else None,
            gap_prev_ids=list(data.get("gap_prev_ids", [])),
            severity=data.get("severity"),
        )


@dataclass
class AuditChainPayload:
    """RFC-0001 SPANFORGE — tamper-evident cross-reference audit chain event.

    Every event emitted in the 10 RFC-0001 SPANFORGE namespaces is cross-
    referenced into this immutable audit chain.  Each entry holds the HMAC
    of the referenced event and the chained HMAC of all prior chain entries,
    making any post-emission mutation detectable.

    Events:
        audit.event_signed      — a new event was appended to the chain
        audit.chain_verified    — a chain segment was verified intact
        audit.tamper_detected   — a break in the HMAC sequence was detected
    """

    event_id: str           # ULID of the referenced event
    event_type: str         # wire event type string of the referenced event
    event_hmac: str         # HMAC-SHA256 of the referenced event canonical JSON
    chain_position: int     # monotonically increasing position in the chain
    signer_id: str          # identity of the signing service / key ID
    signed_at: str          # ISO 8601 timestamp with 6 decimal places
    prev_chain_hmac: str | None = None  # HMAC of the previous chain entry; None for entry 0

    def __post_init__(self) -> None:
        if not self.event_id:
            raise ValueError("AuditChainPayload.event_id must be non-empty")
        if not self.event_type:
            raise ValueError("AuditChainPayload.event_type must be non-empty")
        if not self.event_hmac:
            raise ValueError("AuditChainPayload.event_hmac must be non-empty")
        if not isinstance(self.chain_position, int) or self.chain_position < 0:
            raise ValueError("AuditChainPayload.chain_position must be a non-negative int")
        if not self.signer_id:
            raise ValueError("AuditChainPayload.signer_id must be non-empty")
        if not self.signed_at:
            raise ValueError("AuditChainPayload.signed_at must be non-empty")
        if self.chain_position > 0 and not self.prev_chain_hmac:
            raise ValueError(
                "AuditChainPayload.prev_chain_hmac is required when chain_position > 0"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event_hmac": self.event_hmac,
            "chain_position": self.chain_position,
            "signer_id": self.signer_id,
            "signed_at": self.signed_at,
        }
        if self.prev_chain_hmac is not None:
            d["prev_chain_hmac"] = self.prev_chain_hmac
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AuditChainPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            event_id=data["event_id"],
            event_type=data["event_type"],
            event_hmac=data["event_hmac"],
            chain_position=int(data["chain_position"]),
            signer_id=data["signer_id"],
            signed_at=data["signed_at"],
            prev_chain_hmac=data.get("prev_chain_hmac"),
        )
