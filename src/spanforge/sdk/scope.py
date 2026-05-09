"""spanforge.sdk.scope - SpanForge sf-scope client.

Phase 1 implementation for GA runtime scope enforcement. The client stores
local capability manifests per agent, evaluates requested actions against
those manifests, and emits signed scope decision records via sf-audit.

Production-hardening (1B-2):
* **YAML manifest loader** — :meth:`~SFScopeClient.load_manifest_from_yaml`
  reads a ``scope_manifest.yaml`` file (required fields: ``agent_id``,
  ``allowed_actions``).  Uses PyYAML when available; falls back to a
  zero-dependency line parser for the supported subset.
* **Wildcard resource** — ``allowed_actions`` from YAML is stored under the
  ``"*"`` key in ``resource_actions`` so it acts as a catch-all for any
  resource not explicitly listed.
* **Audit chain** — every ``evaluate()`` call (allow *and* deny) appends a
  signed ``ScopeDecisionPayload`` to ``sf_audit``.
* **Circuit breaker** — backed by :class:`~spanforge.sdk._base._CircuitBreaker`.
  After ``cb_threshold`` (default: 5) consecutive emit failures the circuit
  opens.  Subsequent evaluations immediately return a *fail-secure* deny
  decision and emit an ``sf_alert`` warning until the reset window
  (default: 30 s) has elapsed.
* **Fail-secure default** — ``_evaluate_manifest`` returns ``(False, reason)``
  for unregistered agents.  The circuit breaker extends this to cover infra
  failures.
* **Action categories** — :data:`ACTION_CATEGORIES` maps five canonical
  categories (``read``, ``write``, ``execute``, ``admin``, ``stream``) to
  their member action strings.  Callers may look up a category for any
  requested action via :meth:`~SFScopeClient.resolve_action_category`.
"""

from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spanforge.namespaces.runtime_governance import ScopeDecisionPayload
from spanforge.sdk._base import SFClientConfig, SFServiceClient, _CircuitBreaker
from spanforge.sdk._exceptions import SFScopeError

# ---------------------------------------------------------------------------
# Minimal YAML helpers (zero-dep fallback)
# ---------------------------------------------------------------------------

_RE_KV = re.compile(r"^(\w[\w.-]*)\s*:\s*(.*)")


def _coerce_yaml_scalar(value: str) -> Any:
    """Coerce a YAML scalar string to Python bool / int / float / str."""
    v = value.strip().strip('"').strip("'")
    if v.lower() == "true":
        return True
    if v.lower() == "false":
        return False
    if v.lower() in ("null", "~", ""):
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def _parse_scope_yaml(yaml_text: str) -> dict[str, Any]:
    """Parse a scope manifest YAML without requiring PyYAML.

    Supports PyYAML when installed (preferred); falls back to a minimal
    line-by-line parser that handles the subset used in ``scope_manifest.yaml``:
    top-level scalars, simple lists, ``resource_actions`` nested dicts, and
    ``metadata`` key/value pairs.
    """
    try:
        import yaml  # type: ignore[import-untyped]

        data = yaml.safe_load(yaml_text)
        return data if isinstance(data, dict) else {}
    except ImportError:
        pass

    result: dict[str, Any] = {}
    current_key: str | None = None
    current_resource: str | None = None

    for raw in yaml_text.splitlines():
        line = raw.rstrip()
        stripped = line.lstrip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())

        # Top-level key (no indent, not a list item)
        if indent == 0 and not stripped.startswith("-"):
            m = _RE_KV.match(stripped)
            if m:
                key, val = m.group(1), m.group(2).strip()
                current_key = key
                current_resource = None
                if val:
                    result[key] = _coerce_yaml_scalar(val)
                else:
                    result[key] = {} if key in ("resource_actions", "metadata") else []
            continue

        if current_key is None:
            continue

        # resource_actions: sub-key (indent == 2, not a list)
        if current_key == "resource_actions" and indent == 2 and not stripped.startswith("-"):
            m = re.match(r"^([\w.*-]+)\s*:", stripped)
            if m:
                current_resource = m.group(1)
                result["resource_actions"].setdefault(current_resource, [])
            continue

        # resource_actions list items (indent >= 4)
        if (
            current_key == "resource_actions"
            and current_resource is not None
            and stripped.startswith("-")
        ):
            val = stripped[1:].strip().strip('"').strip("'")
            if val:
                result["resource_actions"].setdefault(current_resource, []).append(val)
            continue

        # metadata key-value pairs
        if current_key == "metadata" and indent >= 2 and not stripped.startswith("-"):
            m = _RE_KV.match(stripped)
            if m:
                result["metadata"][m.group(1)] = _coerce_yaml_scalar(m.group(2).strip())
            continue

        # Simple list items (allowed_actions, capabilities, …)
        if stripped.startswith("-"):
            val = stripped[1:].strip().strip('"').strip("'")
            if val and current_key:
                result.setdefault(current_key, [])
                if isinstance(result[current_key], list):
                    result[current_key].append(val)

    return result

__all__ = [
    "ACTION_CATEGORIES",
    "SFScopeClient",
    "ScopeManifest",
    "ScopeStatusInfo",
    "_parse_scope_yaml",
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

    def load_manifest_from_yaml(
        self, path: str | os.PathLike[str]
    ) -> ScopeManifest:
        """Load and register a scope manifest from a YAML file.

        The YAML file must contain:

        * ``agent_id`` *(str, required)* — unique agent identifier.
        * ``allowed_actions`` *(list[str], required)* — action strings the
          agent is permitted to perform on any resource.  These are stored
          under the ``"*"`` wildcard key in ``resource_actions`` so they act
          as a catch-all when no per-resource entry is registered.

        Optional fields:

        * ``resource_actions`` *(dict[str, list[str]])* — per-resource
          action allowlists that take precedence over the wildcard.
        * ``capabilities`` *(list[str])* — capability scope strings required
          for capability-gated evaluations.
        * ``metadata`` *(dict)* — arbitrary free-form metadata.

        Args:
            path: File system path to the ``scope_manifest.yaml`` file.

        Returns:
            The newly registered :class:`ScopeManifest`.

        Raises:
            ValueError: If ``agent_id`` or ``allowed_actions`` are absent.
            OSError: If the file cannot be read.
        """
        text = Path(path).read_text(encoding="utf-8")
        data = _parse_scope_yaml(text)

        if not data.get("agent_id"):
            raise ValueError(
                "scope_manifest.yaml: missing required field 'agent_id'"
            )
        allowed_actions = data.get("allowed_actions")
        if not allowed_actions or not isinstance(allowed_actions, list):
            raise ValueError(
                "scope_manifest.yaml: missing required field 'allowed_actions' "
                "(must be a non-empty list)"
            )

        # Merge allowed_actions into resource_actions["*"] as a catch-all.
        # Explicit per-resource entries in the YAML take precedence.
        resource_actions: dict[str, list[str]] = dict(data.get("resource_actions") or {})
        if "*" not in resource_actions:
            resource_actions["*"] = list(allowed_actions)

        return self.register_agent(
            agent_id=str(data["agent_id"]),
            capabilities=list(data.get("capabilities") or []),
            resource_actions=resource_actions,
            metadata=dict(data.get("metadata") or {}),
        )

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
            self._emit_circuit_open_alert(agent_id=agent_id, trace_id=trace_id)
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

        allowed_actions = (
            manifest.resource_actions.get(resource)
            if resource in manifest.resource_actions
            else manifest.resource_actions.get("*")
        )
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

    def _emit_circuit_open_alert(self, *, agent_id: str, trace_id: str) -> None:
        """Publish a high-severity alert when the circuit breaker is open.

        Called on every fail-secure deny so operators are notified that
        sf-scope is unavailable.  Failures are silently swallowed so the
        alert path never interferes with the evaluation fast-path.
        """
        try:
            from spanforge.sdk import sf_alert

            sf_alert.publish(
                "sf.scope.circuit_open",
                {
                    "service": "sf_scope",
                    "agent_id": agent_id,
                    "trace_id": trace_id,
                    "reason": "circuit breaker open; all agent actions denied (fail-secure)",
                },
                severity="high",
            )
        except Exception:  # noqa: BLE001
            pass

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
