"""spanforge.sdk.scope - SpanForge sf-scope client.

Phase 1 implementation for GA runtime scope enforcement. The client stores
local capability manifests per agent, evaluates requested actions against
those manifests, and emits signed scope decision records via sf-audit.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from spanforge.namespaces.runtime_governance import ScopeDecisionPayload
from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.sdk._exceptions import SFScopeError

__all__ = ["SFScopeClient", "ScopeManifest", "ScopeStatusInfo"]


@dataclass
class ScopeManifest:
    """Registered scope manifest for one agent."""

    agent_id: str
    capabilities: list[str] = field(default_factory=list)
    resource_actions: dict[str, list[str]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.agent_id:
            raise ValueError("ScopeManifest.agent_id must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "capabilities": list(self.capabilities),
            "resource_actions": {key: list(value) for key, value in self.resource_actions.items()},
            "metadata": dict(self.metadata),
        }


@dataclass
class ScopeStatusInfo:
    """sf-scope service status."""

    status: str
    registered_agents: int
    total_checks: int
    blocked_checks: int


class SFScopeClient(SFServiceClient):
    """SpanForge runtime scope enforcement service client."""

    def __init__(self, config: SFClientConfig) -> None:
        super().__init__(config, service_name="scope")
        self._lock = threading.Lock()
        self._manifests: dict[str, ScopeManifest] = {}
        self._records: dict[str, ScopeDecisionPayload] = {}
        self._by_trace: dict[str, list[str]] = {}
        self._total_checks = 0
        self._blocked_checks = 0

    def register_agent(
        self,
        *,
        agent_id: str,
        capabilities: list[str] | None = None,
        resource_actions: dict[str, list[str]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ScopeManifest:
        """Register or replace the allowed capability manifest for an agent."""
        normalized_resource_actions = {
            resource: sorted({action for action in actions if action})
            for resource, actions in (resource_actions or {}).items()
            if resource
        }
        manifest = ScopeManifest(
            agent_id=agent_id,
            capabilities=sorted({item for item in (capabilities or []) if item}),
            resource_actions=normalized_resource_actions,
            metadata=metadata or {},
        )
        with self._lock:
            self._manifests[agent_id] = manifest
        return manifest

    def get_manifest(self, agent_id: str) -> ScopeManifest | None:
        """Return the registered manifest for *agent_id*."""
        with self._lock:
            return self._manifests.get(agent_id)

    def evaluate(
        self,
        *,
        trace_id: str,
        agent_id: str,
        resource: str,
        action_name: str,
        checked_at: str,
        capability: str | None = None,
        scope_id: str | None = None,
        policy_id: str | None = None,
        policy_action: str | None = None,
    ) -> ScopeDecisionPayload:
        """Evaluate a runtime action against the agent scope manifest."""
        from spanforge.ulid import generate as _ulid

        manifest = self.get_manifest(agent_id)
        allowed, reason = self._evaluate_manifest(
            manifest=manifest,
            agent_id=agent_id,
            resource=resource,
            action_name=action_name,
            capability=capability,
        )
        payload = ScopeDecisionPayload(
            scope_id=scope_id or _ulid(),
            trace_id=trace_id,
            agent_id=agent_id,
            resource=resource,
            action_name=action_name,
            allowed=allowed,
            outcome=self._resolve_outcome(allowed=allowed, policy_action=policy_action),
            reason=reason,
            checked_at=checked_at,
            capability=capability,
            policy_id=policy_id,
            policy_action=policy_action,
        )

        with self._lock:
            self._records[payload.scope_id] = payload
            self._by_trace.setdefault(trace_id, []).append(payload.scope_id)
            self._total_checks += 1
            if not payload.allowed:
                self._blocked_checks += 1

        self._emit_signed_record(payload)
        return payload

    def evaluate_with_policy(
        self,
        *,
        environment: str,
        trace_id: str,
        agent_id: str,
        resource: str,
        action_name: str,
        checked_at: str,
        capability: str | None = None,
        policy_client: Any | None = None,
        control: str = "capability_enforcement",
    ) -> ScopeDecisionPayload:
        """Evaluate scope and attach the active runtime policy decision."""
        manifest = self.get_manifest(agent_id)
        allowed, _reason = self._evaluate_manifest(
            manifest=manifest,
            agent_id=agent_id,
            resource=resource,
            action_name=action_name,
            capability=capability,
        )
        engine = policy_client or self._default_policy_client()
        decision = engine.evaluate(
            environment=environment,
            trace_id=trace_id,
            service="sf_scope",
            control=control,
            evaluated_at=checked_at,
            observed_value=1.0 if allowed else 0.0,
            metadata={"agent_id": agent_id, "resource": resource, "action_name": action_name},
        )
        return self.evaluate(
            trace_id=trace_id,
            agent_id=agent_id,
            resource=resource,
            action_name=action_name,
            checked_at=checked_at,
            capability=capability,
            policy_id=decision.policy_id,
            policy_action=decision.action,
        )

    async def evaluate_async(self, **kwargs: Any) -> ScopeDecisionPayload:
        """Async wrapper around :meth:`evaluate`."""
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.evaluate(**kwargs))

    def require_capability(self, agent_id: str, capability: str) -> None:
        """Raise when an agent is missing a required capability."""
        manifest = self.get_manifest(agent_id)
        key_scopes = manifest.capabilities if manifest is not None else []
        if capability not in key_scopes:
            raise SFScopeError(required_scope=capability, key_scopes=key_scopes)

    def get(self, scope_id: str) -> ScopeDecisionPayload | None:
        """Return a previously emitted scope decision."""
        with self._lock:
            return self._records.get(scope_id)

    def list_for_trace(self, trace_id: str) -> list[ScopeDecisionPayload]:
        """Return all scope decisions emitted for a trace."""
        with self._lock:
            ids = list(self._by_trace.get(trace_id, []))
            return [self._records[item] for item in ids if item in self._records]

    def get_status(self) -> ScopeStatusInfo:
        """Return service health and scope-evaluation counters."""
        with self._lock:
            return ScopeStatusInfo(
                status="ok",
                registered_agents=len(self._manifests),
                total_checks=self._total_checks,
                blocked_checks=self._blocked_checks,
            )

    def _evaluate_manifest(
        self,
        *,
        manifest: ScopeManifest | None,
        agent_id: str,
        resource: str,
        action_name: str,
        capability: str | None,
    ) -> tuple[bool, str]:
        if manifest is None:
            return False, f"agent '{agent_id}' has no registered scope manifest"
        if capability is not None and capability not in manifest.capabilities:
            return (
                False,
                f"agent '{agent_id}' is missing required capability '{capability}'",
            )

        allowed_actions = manifest.resource_actions.get(resource)
        if allowed_actions is None:
            return (
                False,
                f"agent '{agent_id}' is not permitted to access resource '{resource}'",
            )
        if action_name not in allowed_actions:
            return (
                False,
                f"agent '{agent_id}' cannot perform action '{action_name}' on resource '{resource}'",
            )

        if capability is not None:
            return (
                True,
                f"agent '{agent_id}' is permitted for capability '{capability}' on {resource}:{action_name}",
            )
        return True, f"agent '{agent_id}' is permitted on {resource}:{action_name}"

    @staticmethod
    def _resolve_outcome(*, allowed: bool, policy_action: str | None) -> str:
        if allowed:
            return "allow"
        if policy_action == "block":
            return "block"
        if policy_action == "human_review":
            return "human_review"
        if policy_action == "redact":
            return "redact"
        return "escalate"

    def _emit_signed_record(self, payload: ScopeDecisionPayload) -> None:
        """Write the scope decision payload into sf-audit."""
        from spanforge.sdk import sf_audit

        sf_audit.append(payload.to_dict(), "spanforge.scope.v1")

    @staticmethod
    def _default_policy_client() -> Any:
        from spanforge.sdk import sf_policy

        return sf_policy
