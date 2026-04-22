"""spanforge.runtime_policy - Phase 0 runtime policy schema contracts.

This module freezes the policy object model used by the GA runtime governance
control plane. Enforcement engines can evolve behind these contracts without
changing the configuration shape exposed to users.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "RuntimePolicyBundle",
    "RuntimePolicyRule",
]

_VALID_ENVIRONMENTS = frozenset({"dev", "staging", "prod"})
_VALID_POLICY_ACTIONS = frozenset({"allow", "allow+log", "redact", "block", "human_review"})
_VALID_SERVICES = frozenset({"sf_explain", "sf_scope", "sf_rbac", "sf_rag", "sf_lineage"})


@dataclass
class RuntimePolicyRule:
    """One runtime governance rule bound to a service and control."""

    rule_id: str
    service: str
    control: str
    action: str
    enabled: bool = True
    threshold: float | None = None
    rationale: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise ValueError("RuntimePolicyRule.rule_id must be non-empty")
        if self.service not in _VALID_SERVICES:
            raise ValueError(
                f"RuntimePolicyRule.service must be one of {sorted(_VALID_SERVICES)}"
            )
        if not self.control:
            raise ValueError("RuntimePolicyRule.control must be non-empty")
        if self.action not in _VALID_POLICY_ACTIONS:
            raise ValueError(
                f"RuntimePolicyRule.action must be one of {sorted(_VALID_POLICY_ACTIONS)}"
            )
        if self.threshold is not None and not (0.0 <= self.threshold <= 1.0):
            raise ValueError("RuntimePolicyRule.threshold must be in [0.0, 1.0]")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "rule_id": self.rule_id,
            "service": self.service,
            "control": self.control,
            "action": self.action,
            "enabled": self.enabled,
        }
        if self.threshold is not None:
            data["threshold"] = self.threshold
        if self.rationale:
            data["rationale"] = self.rationale
        if self.metadata:
            data["metadata"] = self.metadata
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuntimePolicyRule":
        return cls(
            rule_id=data["rule_id"],
            service=data["service"],
            control=data["control"],
            action=data["action"],
            enabled=bool(data.get("enabled", True)),
            threshold=float(data["threshold"]) if "threshold" in data else None,
            rationale=data.get("rationale", ""),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass
class RuntimePolicyBundle:
    """Versioned runtime policy bundle for one deployment environment."""

    policy_id: str
    version: str
    environment: str
    owner: str
    effective_at: str
    rules: list[RuntimePolicyRule] = field(default_factory=list)
    rationale: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.policy_id:
            raise ValueError("RuntimePolicyBundle.policy_id must be non-empty")
        if not self.version:
            raise ValueError("RuntimePolicyBundle.version must be non-empty")
        if self.environment not in _VALID_ENVIRONMENTS:
            raise ValueError(
                f"RuntimePolicyBundle.environment must be one of {sorted(_VALID_ENVIRONMENTS)}"
            )
        if not self.owner:
            raise ValueError("RuntimePolicyBundle.owner must be non-empty")
        if not self.effective_at:
            raise ValueError("RuntimePolicyBundle.effective_at must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "policy_id": self.policy_id,
            "version": self.version,
            "environment": self.environment,
            "owner": self.owner,
            "effective_at": self.effective_at,
            "rules": [rule.to_dict() for rule in self.rules],
        }
        if self.rationale:
            data["rationale"] = self.rationale
        if self.metadata:
            data["metadata"] = self.metadata
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuntimePolicyBundle":
        return cls(
            policy_id=data["policy_id"],
            version=data["version"],
            environment=data["environment"],
            owner=data["owner"],
            effective_at=data["effective_at"],
            rules=[RuntimePolicyRule.from_dict(item) for item in data.get("rules", [])],
            rationale=data.get("rationale", ""),
            metadata=dict(data.get("metadata", {})),
        )
