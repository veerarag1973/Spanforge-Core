"""spanforge.namespaces.runtime_governance - GA runtime governance payloads.

These payloads freeze the canonical event contracts for the May 2, 2026 GA
runtime-governance feature set:

- explanation
- grounding
- lineage
- scope
- rbac

They intentionally model runtime control decisions rather than generic
observability spans so Phase 1 service clients can build on stable contracts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ExplanationFactor",
    "ExplanationPayload",
    "GroundingClaim",
    "GroundingPayload",
    "LineagePayload",
    "RBACDecisionPayload",
    "ScopeDecisionPayload",
]

_VALID_POLICY_ACTIONS = frozenset({"allow", "allow+log", "redact", "block", "human_review"})
_VALID_DECISION_ACTIONS = frozenset({"allow", "block", "escalate", "human_review", "redact"})


@dataclass
class ExplanationFactor:
    """One contributing factor for a runtime explanation record."""

    factor_name: str
    weight: float
    contribution: float
    evidence: str
    confidence: float | None = None

    def __post_init__(self) -> None:
        if not self.factor_name:
            raise ValueError("ExplanationFactor.factor_name must be non-empty")
        if not (0.0 <= self.weight <= 1.0):
            raise ValueError("ExplanationFactor.weight must be in [0.0, 1.0]")
        if not (-1.0 <= self.contribution <= 1.0):
            raise ValueError("ExplanationFactor.contribution must be in [-1.0, 1.0]")
        if not self.evidence:
            raise ValueError("ExplanationFactor.evidence must be non-empty")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError("ExplanationFactor.confidence must be in [0.0, 1.0]")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "factor_name": self.factor_name,
            "weight": self.weight,
            "contribution": self.contribution,
            "evidence": self.evidence,
        }
        if self.confidence is not None:
            data["confidence"] = self.confidence
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExplanationFactor":
        return cls(
            factor_name=data["factor_name"],
            weight=float(data["weight"]),
            contribution=float(data["contribution"]),
            evidence=data["evidence"],
            confidence=float(data["confidence"]) if "confidence" in data else None,
        )


@dataclass
class ExplanationPayload:
    """Canonical explanation event payload for runtime decisions."""

    explanation_id: str
    trace_id: str
    decision_id: str
    agent_id: str
    summary: str
    policy_action: str
    generated_at: str
    factors: list[ExplanationFactor] = field(default_factory=list)
    model_id: str | None = None
    confidence: float | None = None
    policy_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.explanation_id:
            raise ValueError("ExplanationPayload.explanation_id must be non-empty")
        if not self.trace_id:
            raise ValueError("ExplanationPayload.trace_id must be non-empty")
        if not self.decision_id:
            raise ValueError("ExplanationPayload.decision_id must be non-empty")
        if not self.agent_id:
            raise ValueError("ExplanationPayload.agent_id must be non-empty")
        if not self.summary:
            raise ValueError("ExplanationPayload.summary must be non-empty")
        if self.policy_action not in _VALID_POLICY_ACTIONS:
            raise ValueError(
                f"ExplanationPayload.policy_action must be one of {sorted(_VALID_POLICY_ACTIONS)}"
            )
        if not self.generated_at:
            raise ValueError("ExplanationPayload.generated_at must be non-empty")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError("ExplanationPayload.confidence must be in [0.0, 1.0]")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "explanation_id": self.explanation_id,
            "trace_id": self.trace_id,
            "decision_id": self.decision_id,
            "agent_id": self.agent_id,
            "summary": self.summary,
            "policy_action": self.policy_action,
            "generated_at": self.generated_at,
            "factors": [factor.to_dict() for factor in self.factors],
        }
        if self.model_id is not None:
            data["model_id"] = self.model_id
        if self.confidence is not None:
            data["confidence"] = self.confidence
        if self.policy_id is not None:
            data["policy_id"] = self.policy_id
        if self.metadata:
            data["metadata"] = self.metadata
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ExplanationPayload":
        return cls(
            explanation_id=data["explanation_id"],
            trace_id=data["trace_id"],
            decision_id=data["decision_id"],
            agent_id=data["agent_id"],
            summary=data["summary"],
            policy_action=data["policy_action"],
            generated_at=data["generated_at"],
            factors=[ExplanationFactor.from_dict(item) for item in data.get("factors", [])],
            model_id=data.get("model_id"),
            confidence=float(data["confidence"]) if "confidence" in data else None,
            policy_id=data.get("policy_id"),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class GroundingClaim:
    """One claim-level grounding assessment."""

    claim_id: str
    claim_text: str
    grounded: bool
    score: float
    source_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.claim_id:
            raise ValueError("GroundingClaim.claim_id must be non-empty")
        if not self.claim_text:
            raise ValueError("GroundingClaim.claim_text must be non-empty")
        if not (0.0 <= self.score <= 1.0):
            raise ValueError("GroundingClaim.score must be in [0.0, 1.0]")

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "claim_text": self.claim_text,
            "grounded": self.grounded,
            "score": self.score,
            "source_ids": list(self.source_ids),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GroundingClaim":
        return cls(
            claim_id=data["claim_id"],
            claim_text=data["claim_text"],
            grounded=bool(data["grounded"]),
            score=float(data["score"]),
            source_ids=list(data.get("source_ids", [])),
        )


@dataclass
class GroundingPayload:
    """Canonical grounding event payload for RAG reliability controls."""

    grounding_id: str
    trace_id: str
    decision_id: str
    session_id: str
    status: str
    average_score: float
    threshold: float
    policy_action: str
    assessed_at: str
    claims: list[GroundingClaim] = field(default_factory=list)
    model_id: str | None = None
    retriever_name: str | None = None

    def __post_init__(self) -> None:
        if not self.grounding_id:
            raise ValueError("GroundingPayload.grounding_id must be non-empty")
        if not self.trace_id:
            raise ValueError("GroundingPayload.trace_id must be non-empty")
        if not self.decision_id:
            raise ValueError("GroundingPayload.decision_id must be non-empty")
        if not self.session_id:
            raise ValueError("GroundingPayload.session_id must be non-empty")
        if self.status not in {"grounded", "partially_grounded", "ungrounded"}:
            raise ValueError(
                "GroundingPayload.status must be 'grounded', 'partially_grounded', or 'ungrounded'"
            )
        if not (0.0 <= self.average_score <= 1.0):
            raise ValueError("GroundingPayload.average_score must be in [0.0, 1.0]")
        if not (0.0 <= self.threshold <= 1.0):
            raise ValueError("GroundingPayload.threshold must be in [0.0, 1.0]")
        if self.policy_action not in _VALID_POLICY_ACTIONS:
            raise ValueError(
                f"GroundingPayload.policy_action must be one of {sorted(_VALID_POLICY_ACTIONS)}"
            )
        if not self.assessed_at:
            raise ValueError("GroundingPayload.assessed_at must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "grounding_id": self.grounding_id,
            "trace_id": self.trace_id,
            "decision_id": self.decision_id,
            "session_id": self.session_id,
            "status": self.status,
            "average_score": self.average_score,
            "threshold": self.threshold,
            "policy_action": self.policy_action,
            "assessed_at": self.assessed_at,
            "claims": [claim.to_dict() for claim in self.claims],
        }
        if self.model_id is not None:
            data["model_id"] = self.model_id
        if self.retriever_name is not None:
            data["retriever_name"] = self.retriever_name
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GroundingPayload":
        return cls(
            grounding_id=data["grounding_id"],
            trace_id=data["trace_id"],
            decision_id=data["decision_id"],
            session_id=data["session_id"],
            status=data["status"],
            average_score=float(data["average_score"]),
            threshold=float(data["threshold"]),
            policy_action=data["policy_action"],
            assessed_at=data["assessed_at"],
            claims=[GroundingClaim.from_dict(item) for item in data.get("claims", [])],
            model_id=data.get("model_id"),
            retriever_name=data.get("retriever_name"),
        )


@dataclass
class LineagePayload:
    """Canonical provenance payload for data and decision lineage."""

    lineage_id: str
    trace_id: str
    decision_id: str
    subject_type: str
    subject_id: str
    operation: str
    recorded_at: str
    input_refs: list[str] = field(default_factory=list)
    output_refs: list[str] = field(default_factory=list)
    parent_lineage_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.lineage_id:
            raise ValueError("LineagePayload.lineage_id must be non-empty")
        if not self.trace_id:
            raise ValueError("LineagePayload.trace_id must be non-empty")
        if not self.decision_id:
            raise ValueError("LineagePayload.decision_id must be non-empty")
        if not self.subject_type:
            raise ValueError("LineagePayload.subject_type must be non-empty")
        if not self.subject_id:
            raise ValueError("LineagePayload.subject_id must be non-empty")
        if not self.operation:
            raise ValueError("LineagePayload.operation must be non-empty")
        if not self.recorded_at:
            raise ValueError("LineagePayload.recorded_at must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "lineage_id": self.lineage_id,
            "trace_id": self.trace_id,
            "decision_id": self.decision_id,
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "operation": self.operation,
            "recorded_at": self.recorded_at,
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
            "parent_lineage_ids": list(self.parent_lineage_ids),
        }
        if self.metadata:
            data["metadata"] = self.metadata
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LineagePayload":
        return cls(
            lineage_id=data["lineage_id"],
            trace_id=data["trace_id"],
            decision_id=data["decision_id"],
            subject_type=data["subject_type"],
            subject_id=data["subject_id"],
            operation=data["operation"],
            recorded_at=data["recorded_at"],
            input_refs=list(data.get("input_refs", [])),
            output_refs=list(data.get("output_refs", [])),
            parent_lineage_ids=list(data.get("parent_lineage_ids", [])),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class ScopeDecisionPayload:
    """Canonical runtime payload for agent scope checks."""

    scope_id: str
    trace_id: str
    agent_id: str
    resource: str
    action_name: str
    allowed: bool
    outcome: str
    reason: str
    checked_at: str
    capability: str | None = None
    policy_id: str | None = None
    policy_action: str | None = None

    def __post_init__(self) -> None:
        if not self.scope_id:
            raise ValueError("ScopeDecisionPayload.scope_id must be non-empty")
        if not self.trace_id:
            raise ValueError("ScopeDecisionPayload.trace_id must be non-empty")
        if not self.agent_id:
            raise ValueError("ScopeDecisionPayload.agent_id must be non-empty")
        if not self.resource:
            raise ValueError("ScopeDecisionPayload.resource must be non-empty")
        if not self.action_name:
            raise ValueError("ScopeDecisionPayload.action_name must be non-empty")
        if self.outcome not in _VALID_DECISION_ACTIONS:
            raise ValueError(
                f"ScopeDecisionPayload.outcome must be one of {sorted(_VALID_DECISION_ACTIONS)}"
            )
        if not self.reason:
            raise ValueError("ScopeDecisionPayload.reason must be non-empty")
        if not self.checked_at:
            raise ValueError("ScopeDecisionPayload.checked_at must be non-empty")
        if self.policy_action is not None and self.policy_action not in _VALID_POLICY_ACTIONS:
            raise ValueError(
                f"ScopeDecisionPayload.policy_action must be one of {sorted(_VALID_POLICY_ACTIONS)}"
            )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "scope_id": self.scope_id,
            "trace_id": self.trace_id,
            "agent_id": self.agent_id,
            "resource": self.resource,
            "action_name": self.action_name,
            "allowed": self.allowed,
            "outcome": self.outcome,
            "reason": self.reason,
            "checked_at": self.checked_at,
        }
        if self.capability is not None:
            data["capability"] = self.capability
        if self.policy_id is not None:
            data["policy_id"] = self.policy_id
        if self.policy_action is not None:
            data["policy_action"] = self.policy_action
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScopeDecisionPayload":
        return cls(
            scope_id=data["scope_id"],
            trace_id=data["trace_id"],
            agent_id=data["agent_id"],
            resource=data["resource"],
            action_name=data["action_name"],
            allowed=bool(data["allowed"]),
            outcome=data["outcome"],
            reason=data["reason"],
            checked_at=data["checked_at"],
            capability=data.get("capability"),
            policy_id=data.get("policy_id"),
            policy_action=data.get("policy_action"),
        )


@dataclass
class RBACDecisionPayload:
    """Canonical runtime payload for RBAC authorization checks."""

    check_id: str
    trace_id: str
    actor_id: str
    resource: str
    action_name: str
    allowed: bool
    outcome: str
    reason: str
    checked_at: str
    required_roles: list[str] = field(default_factory=list)
    effective_roles: list[str] = field(default_factory=list)
    policy_id: str | None = None
    policy_action: str | None = None

    def __post_init__(self) -> None:
        if not self.check_id:
            raise ValueError("RBACDecisionPayload.check_id must be non-empty")
        if not self.trace_id:
            raise ValueError("RBACDecisionPayload.trace_id must be non-empty")
        if not self.actor_id:
            raise ValueError("RBACDecisionPayload.actor_id must be non-empty")
        if not self.resource:
            raise ValueError("RBACDecisionPayload.resource must be non-empty")
        if not self.action_name:
            raise ValueError("RBACDecisionPayload.action_name must be non-empty")
        if self.outcome not in _VALID_DECISION_ACTIONS:
            raise ValueError(
                f"RBACDecisionPayload.outcome must be one of {sorted(_VALID_DECISION_ACTIONS)}"
            )
        if not self.reason:
            raise ValueError("RBACDecisionPayload.reason must be non-empty")
        if not self.checked_at:
            raise ValueError("RBACDecisionPayload.checked_at must be non-empty")
        if self.policy_action is not None and self.policy_action not in _VALID_POLICY_ACTIONS:
            raise ValueError(
                f"RBACDecisionPayload.policy_action must be one of {sorted(_VALID_POLICY_ACTIONS)}"
            )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "check_id": self.check_id,
            "trace_id": self.trace_id,
            "actor_id": self.actor_id,
            "resource": self.resource,
            "action_name": self.action_name,
            "allowed": self.allowed,
            "outcome": self.outcome,
            "reason": self.reason,
            "checked_at": self.checked_at,
            "required_roles": list(self.required_roles),
            "effective_roles": list(self.effective_roles),
        }
        if self.policy_id is not None:
            data["policy_id"] = self.policy_id
        if self.policy_action is not None:
            data["policy_action"] = self.policy_action
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RBACDecisionPayload":
        return cls(
            check_id=data["check_id"],
            trace_id=data["trace_id"],
            actor_id=data["actor_id"],
            resource=data["resource"],
            action_name=data["action_name"],
            allowed=bool(data["allowed"]),
            outcome=data["outcome"],
            reason=data["reason"],
            checked_at=data["checked_at"],
            required_roles=list(data.get("required_roles", [])),
            effective_roles=list(data.get("effective_roles", [])),
            policy_id=data.get("policy_id"),
            policy_action=data.get("policy_action"),
        )
