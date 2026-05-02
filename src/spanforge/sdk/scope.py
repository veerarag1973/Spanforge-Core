"""spanforge.sdk.scope - SpanForge sf-scope client.

Phase 1 implementation for GA runtime scope enforcement. The client stores
local capability manifests per agent, evaluates requested actions against
those manifests, and emits signed scope decision records via sf-audit.

Production-hardening (1B-2):
* **Circuit breaker** — backed by :class:`~spanforge.sdk._base._CircuitBreaker`.
  After ``cb_threshold`` (default: 5) consecutive emit failures the circuit
  opens.  Subsequent evaluations immediately return a *fail-secure* deny
  decision and record an ``"open_circuit"`` outcome until the reset window
  (default: 30 s) has elapsed.
* **Fail-secure default** — ``_evaluate_manifest`` already returned
  ``(False, reason)`` for unregistered agents.  The circuit breaker extends
  this guarantee to cover infra failures as well.
* **Action categories** — :data:`ACTION_CATEGORIES` maps five canonical
  categories (``read``, ``write``, ``execute``, ``admin``, ``stream``) to
  their member action strings.  Callers may look up a category for any
  requested action via :meth:`~SFScopeClient.resolve_action_category`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from spanforge.namespaces.runtime_governance import ScopeDecisionPayload
from spanforge.sdk._base import SFClientConfig, SFServiceClient, _CircuitBreaker
from spanforge.sdk._exceptions import SFScopeError

__all__ = [
    "ACTION_CATEGORIES",
    "SFScopeClient",
    "ScopeManifest",
    "ScopeStatusInfo",
]

# ---------------------------------------------------------------------------
# Action category registry (1B-2)
# ---------------------------------------------------------------------------

#: Canonical action categories for scope evaluation.
#:
#: Each key is a category name; the value is the frozenset of action strings
#: that belong to that category.  An action may belong to only one category.
ACTION_CATEGORIES: dict[str, frozenset[str]] = {
    "read": frozenset({"read", "get", "fetch", "list", "view", "describe", "head"}),
    "write": frozenset({"write", "create", "update", "put", "post", "patch", "upsert"}),
    "execute": frozenset({"execute", "run", "exec", "invoke", "call", "trigger", "start"}),
    "admin": frozenset(
        {"admin", "configure", "provision", "delete", "remove", "purge", "destroy", "rotate"}
    ),
    "stream": frozenset({"stream", "subscribe", "publish", "emit", "pipe", "consume"}),
}

#: Reverse lookup: action string → category name.
_ACTION_TO_CATEGORY: dict[str, str] = {
    action: category
    for category, actions in ACTION_CATEGORIES.items()
    for action in actions
}


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
    """SpanForge runtime scope enforcement service client.

    Args:
        config: Client configuration.
        cb_threshold: Number of consecutive emit failures before the circuit
            opens (default: 5).
        cb_reset_seconds: Seconds after which an open circuit is automatically
            reset to closed (default: 30).
    """

    def __init__(
        self,
        config: SFClientConfig,
        *,
        cb_threshold: int = 5,
        cb_reset_seconds: float = 30.0,
    ) -> None:
        super().__init__(config, service_name="scope")
        self._lock = threading.Lock()
        self._manifests: dict[str, ScopeManifest] = {}
        self._records: dict[str, ScopeDecisionPayload] = {}
        self._by_trace: dict[str, list[str]] = {}
        self._total_checks = 0
        self._blocked_checks = 0
        self._circuit_breaker = _CircuitBreaker(
            threshold=cb_threshold,
            reset_seconds=cb_reset_seconds,
        )

    @staticmethod
    def resolve_action_category(action: str) -> str | None:
        """Return the canonical category for *action*, or ``None`` if unknown."""
        return _ACTION_TO_CATEGORY.get(action.lower())

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
        """Evaluate a runtime action against the agent scope manifest.

        **Fail-secure circuit breaker (1B-2)**: if the circuit is open the
        method immediately returns a *deny* payload with ``outcome="open_circuit"``
        without consulting the manifest or emitting to sf-audit.
        """
        from spanforge.ulid import generate as _ulid

        # --- circuit-breaker fast-path (fail-secure) ---
        if self._circuit_breaker.is_open():
            with self._lock:
                self._total_checks += 1
                self._blocked_checks += 1
            return ScopeDecisionPayload(
                scope_id=scope_id or _ulid(),
                trace_id=trace_id,
                agent_id=agent_id,
                resource=resource,
                action_name=action_name,
                allowed=False,
                outcome="block",
                reason="circuit breaker is open; failing secure",
                checked_at=checked_at,
                capability=capability,
                policy_id=policy_id,
                policy_action=policy_action,
            )

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
        """Write the scope decision payload into sf-audit.

        A successful emit calls :meth:`_CircuitBreaker.record_success`; any
        exception calls :meth:`_CircuitBreaker.record_failure` so that
        repeated infra failures eventually open the circuit.
        """
        from spanforge.sdk import sf_audit

        try:
            sf_audit.append(payload.to_dict(), "spanforge.scope.v1")
            self._circuit_breaker.record_success()
        except Exception:  # noqa: BLE001
            self._circuit_breaker.record_failure()

    @staticmethod
    def _default_policy_client() -> Any:
        from spanforge.sdk import sf_policy

        return sf_policy
