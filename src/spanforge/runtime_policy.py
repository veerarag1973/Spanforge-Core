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


def _require_mapping(data: Any, type_name: str) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise ValueError(f"{type_name} input must be a dict")
    return data


def _require_fields(data: dict[str, Any], type_name: str, fields: tuple[str, ...]) -> None:
    missing = [field for field in fields if field not in data]
    if missing:
        raise ValueError(f"{type_name} is missing required fields: {', '.join(missing)}")


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
        parsed = _require_mapping(data, "RuntimePolicyRule")
        _require_fields(
            parsed,
            "RuntimePolicyRule",
            ("rule_id", "service", "control", "action"),
        )
        return cls(
            rule_id=parsed["rule_id"],
            service=parsed["service"],
            control=parsed["control"],
            action=parsed["action"],
            enabled=bool(parsed.get("enabled", True)),
            threshold=float(parsed["threshold"]) if "threshold" in parsed else None,
            rationale=parsed.get("rationale", ""),
            metadata=dict(parsed.get("metadata", {})),
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
        parsed = _require_mapping(data, "RuntimePolicyBundle")
        _require_fields(
            parsed,
            "RuntimePolicyBundle",
            ("policy_id", "version", "environment", "owner", "effective_at"),
        )
        return cls(
            policy_id=parsed["policy_id"],
            version=parsed["version"],
            environment=parsed["environment"],
            owner=parsed["owner"],
            effective_at=parsed["effective_at"],
            rules=[RuntimePolicyRule.from_dict(item) for item in parsed.get("rules", [])],
            rationale=parsed.get("rationale", ""),
            metadata=dict(parsed.get("metadata", {})),
        )
