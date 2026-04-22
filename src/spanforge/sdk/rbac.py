"""spanforge.sdk.rbac - SpanForge sf-rbac client.

Phase 1 implementation for GA runtime RBAC enforcement. The client stores
local role manifests per actor, evaluates requested actions against required
roles, and emits signed RBAC decision records via sf-audit.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from spanforge.namespaces.runtime_governance import RBACDecisionPayload
from spanforge.sdk._base import SFClientConfig, SFServiceClient

__all__ = ["RBACManifest", "RBACStatusInfo", "SFRBACClient"]


@dataclass
class RBACManifest:
    """Registered RBAC manifest for one actor."""

    actor_id: str
    roles: list[str] = field(default_factory=list)
    resource_roles: dict[str, list[str]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.actor_id:
            raise ValueError("RBACManifest.actor_id must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        return {
            "actor_id": self.actor_id,
            "roles": list(self.roles),
            "resource_roles": {key: list(value) for key, value in self.resource_roles.items()},
            "metadata": dict(self.metadata),
        }


@dataclass
class RBACStatusInfo:
    """sf-rbac service status."""

    status: str
    registered_actors: int
    total_checks: int
    denied_checks: int


class SFRBACClient(SFServiceClient):
    """SpanForge runtime RBAC authorization service client."""

    def __init__(self, config: SFClientConfig) -> None:
        super().__init__(config, service_name="rbac")
        self._lock = threading.Lock()
        self._manifests: dict[str, RBACManifest] = {}
        self._records: dict[str, RBACDecisionPayload] = {}
        self._by_trace: dict[str, list[str]] = {}
        self._total_checks = 0
        self._denied_checks = 0

    def register_actor(
        self,
        *,
        actor_id: str,
        roles: list[str] | None = None,
        resource_roles: dict[str, list[str]] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RBACManifest:
        """Register or replace the effective role manifest for an actor."""
        normalized_resource_roles = {
            resource: sorted({role for role in entries if role})
            for resource, entries in (resource_roles or {}).items()
            if resource
        }
        manifest = RBACManifest(
            actor_id=actor_id,
            roles=sorted({role for role in (roles or []) if role}),
            resource_roles=normalized_resource_roles,
            metadata=metadata or {},
        )
        with self._lock:
            self._manifests[actor_id] = manifest
        return manifest

    def get_manifest(self, actor_id: str) -> RBACManifest | None:
        """Return the registered RBAC manifest for *actor_id*."""
        with self._lock:
            return self._manifests.get(actor_id)

    def authorize(
        self,
        *,
        trace_id: str,
        actor_id: str,
        resource: str,
        action_name: str,
        checked_at: str,
        required_roles: list[str] | None = None,
        check_id: str | None = None,
        policy_id: str | None = None,
        policy_action: str | None = None,
    ) -> RBACDecisionPayload:
        """Evaluate a runtime action against the actor's effective roles."""
        from spanforge.ulid import generate as _ulid

        normalized_required_roles = sorted({role for role in (required_roles or []) if role})
        manifest = self.get_manifest(actor_id)
        effective_roles = self._effective_roles_for_resource(manifest, resource)
        allowed, reason = self._evaluate_roles(
            manifest=manifest,
            actor_id=actor_id,
            resource=resource,
            action_name=action_name,
            required_roles=normalized_required_roles,
            effective_roles=effective_roles,
        )

        payload = RBACDecisionPayload(
            check_id=check_id or _ulid(),
            trace_id=trace_id,
            actor_id=actor_id,
            resource=resource,
            action_name=action_name,
            allowed=allowed,
            outcome=self._resolve_outcome(allowed=allowed, policy_action=policy_action),
            reason=reason,
            checked_at=checked_at,
            required_roles=normalized_required_roles,
            effective_roles=effective_roles,
            policy_id=policy_id,
            policy_action=policy_action,
        )

        with self._lock:
            self._records[payload.check_id] = payload
            self._by_trace.setdefault(trace_id, []).append(payload.check_id)
            self._total_checks += 1
            if not payload.allowed:
                self._denied_checks += 1

        self._emit_signed_record(payload)
        return payload

    def authorize_with_policy(
        self,
        *,
        environment: str,
        trace_id: str,
        actor_id: str,
        resource: str,
        action_name: str,
        checked_at: str,
        required_roles: list[str] | None = None,
        policy_client: Any | None = None,
        control: str = "role_enforcement",
    ) -> RBACDecisionPayload:
        """Authorize an RBAC action and attach the active runtime policy decision."""
        normalized_required_roles = sorted({role for role in (required_roles or []) if role})
        manifest = self.get_manifest(actor_id)
        effective_roles = self._effective_roles_for_resource(manifest, resource)
        allowed, _reason = self._evaluate_roles(
            manifest=manifest,
            actor_id=actor_id,
            resource=resource,
            action_name=action_name,
            required_roles=normalized_required_roles,
            effective_roles=effective_roles,
        )
        engine = policy_client or self._default_policy_client()
        decision = engine.evaluate(
            environment=environment,
            trace_id=trace_id,
            service="sf_rbac",
            control=control,
            evaluated_at=checked_at,
            observed_value=1.0 if allowed else 0.0,
            metadata={"actor_id": actor_id, "resource": resource, "action_name": action_name},
        )
        return self.authorize(
            trace_id=trace_id,
            actor_id=actor_id,
            resource=resource,
            action_name=action_name,
            checked_at=checked_at,
            required_roles=normalized_required_roles,
            policy_id=decision.policy_id,
            policy_action=decision.action,
        )

    async def authorize_async(self, **kwargs: Any) -> RBACDecisionPayload:
        """Async wrapper around :meth:`authorize`."""
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.authorize(**kwargs))

    def get(self, check_id: str) -> RBACDecisionPayload | None:
        """Return a previously emitted RBAC decision."""
        with self._lock:
            return self._records.get(check_id)

    def list_for_trace(self, trace_id: str) -> list[RBACDecisionPayload]:
        """Return all RBAC decisions emitted for a trace."""
        with self._lock:
            ids = list(self._by_trace.get(trace_id, []))
            return [self._records[item] for item in ids if item in self._records]

    def get_status(self) -> RBACStatusInfo:
        """Return service health and RBAC counters."""
        with self._lock:
            return RBACStatusInfo(
                status="ok",
                registered_actors=len(self._manifests),
                total_checks=self._total_checks,
                denied_checks=self._denied_checks,
            )

    @staticmethod
    def _effective_roles_for_resource(
        manifest: RBACManifest | None,
        resource: str,
    ) -> list[str]:
        if manifest is None:
            return []
        effective = set(manifest.roles)
        effective.update(manifest.resource_roles.get(resource, []))
        return sorted(effective)

    def _evaluate_roles(
        self,
        *,
        manifest: RBACManifest | None,
        actor_id: str,
        resource: str,
        action_name: str,
        required_roles: list[str],
        effective_roles: list[str],
    ) -> tuple[bool, str]:
        if manifest is None:
            return False, f"actor '{actor_id}' has no registered RBAC manifest"
        if not required_roles:
            return True, f"actor '{actor_id}' is authorized for {resource}:{action_name}"

        missing_roles = [role for role in required_roles if role not in effective_roles]
        if missing_roles:
            return (
                False,
                f"actor '{actor_id}' is missing required roles {missing_roles} for {resource}:{action_name}",
            )
        return (
            True,
            f"actor '{actor_id}' is authorized with roles {required_roles} for {resource}:{action_name}",
        )

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

    def _emit_signed_record(self, payload: RBACDecisionPayload) -> None:
        """Write the RBAC decision payload into sf-audit."""
        from spanforge.sdk import sf_audit

        sf_audit.append(payload.to_dict(), "spanforge.rbac.v1")

    @staticmethod
    def _default_policy_client() -> Any:
        from spanforge.sdk import sf_policy

        return sf_policy
