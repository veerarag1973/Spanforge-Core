"""spanforge.sdk.rbac - SpanForge sf-rbac client.

Phase 1 implementation for GA runtime RBAC enforcement. The client stores
local role manifests per actor, evaluates requested actions against required
roles, and emits signed RBAC decision records via sf-audit.

Production-hardening (1C-2):
* :data:`STANDARD_ROLE_MATRIX` — 10 canonical role configurations covering
  the most common enterprise actor types (viewer, editor, admin, operator,
  auditor, developer, deployer, reviewer, service_account, superadmin).
* :meth:`SFRBACClient.register_actor_from_yaml` — parse a YAML snippet to
  register an actor without hand-constructing the dict.  Uses the stdlib
  ``email.parser`` / ``re`` approach so that :mod:`yaml` (PyYAML) is an
  **optional** dependency; falls back to a minimal key:value parser for
  simple manifests when PyYAML is absent.
* :meth:`SFRBACClient.register_actor_from_jwt` — decode a JWT payload section
  (Base64url, no signature verification by default) and extract the ``sub``
  claim as the actor ID and the ``roles`` claim as the role list.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import threading
from dataclasses import dataclass, field
from typing import Any

from spanforge.namespaces.runtime_governance import RBACDecisionPayload
from spanforge.sdk._base import SFClientConfig, SFServiceClient

__all__ = [
    "RBACManifest",
    "RBACStatusInfo",
    "STANDARD_ROLE_MATRIX",
    "SFRBACClient",
]

_rbac_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 1C-2: Standard role matrix (10 configurations)
# ---------------------------------------------------------------------------

#: Canonical role configurations for enterprise actor types.
#:
#: Each key is an actor-type label; the value is a dict with:
#: * ``"roles"`` — global roles granted to this actor type.
#: * ``"resource_roles"`` — optional per-resource role grants.
#: * ``"description"`` — human-readable summary.
STANDARD_ROLE_MATRIX: dict[str, dict[str, Any]] = {
    "viewer": {
        "roles": ["viewer"],
        "resource_roles": {},
        "description": "Read-only access to all resources.",
    },
    "editor": {
        "roles": ["viewer", "editor"],
        "resource_roles": {},
        "description": "Read and write access; cannot delete or configure.",
    },
    "admin": {
        "roles": ["viewer", "editor", "admin"],
        "resource_roles": {},
        "description": "Full access including configuration and deletion.",
    },
    "operator": {
        "roles": ["viewer", "operator"],
        "resource_roles": {},
        "description": "Operational access: monitor, restart, scale.",
    },
    "auditor": {
        "roles": ["viewer", "auditor"],
        "resource_roles": {},
        "description": "Read-only plus audit-log access.",
    },
    "developer": {
        "roles": ["viewer", "editor", "developer"],
        "resource_roles": {},
        "description": "Developer access: write + test, no prod deployments.",
    },
    "deployer": {
        "roles": ["viewer", "deployer"],
        "resource_roles": {},
        "description": "Deploy-only: push artefacts and trigger rollouts.",
    },
    "reviewer": {
        "roles": ["viewer", "reviewer"],
        "resource_roles": {},
        "description": "Review and approve changes without write access.",
    },
    "service_account": {
        "roles": ["service_account"],
        "resource_roles": {},
        "description": "Machine identity with least-privilege service access.",
    },
    "superadmin": {
        "roles": ["viewer", "editor", "admin", "superadmin"],
        "resource_roles": {},
        "description": "Unrestricted access; reserved for break-glass scenarios.",
    },
}


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

    def register_actor_from_yaml(self, yaml_str: str) -> RBACManifest:
        """Parse a YAML manifest snippet and register the actor.

        The YAML document must contain at least an ``actor_id`` key.
        Optional keys: ``roles`` (list), ``resource_roles`` (mapping),
        ``metadata`` (mapping).

        PyYAML is used when available; otherwise a minimal key:value parser
        handles simple flat documents (no nested mappings or inline lists).

        Args:
            yaml_str: YAML content as a string.

        Returns:
            The newly registered :class:`RBACManifest`.

        Raises:
            ValueError: If the YAML is missing ``actor_id`` or is malformed.
        """
        data = _parse_yaml_safe(yaml_str)
        if not isinstance(data, dict):
            raise ValueError("register_actor_from_yaml: YAML root must be a mapping")
        actor_id = data.get("actor_id")
        if not actor_id or not isinstance(actor_id, str):
            raise ValueError("register_actor_from_yaml: 'actor_id' key is required and must be a string")
        roles = data.get("roles") or []
        if not isinstance(roles, list):
            raise ValueError("register_actor_from_yaml: 'roles' must be a list")
        resource_roles = data.get("resource_roles") or {}
        if not isinstance(resource_roles, dict):
            raise ValueError("register_actor_from_yaml: 'resource_roles' must be a mapping")
        metadata = data.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise ValueError("register_actor_from_yaml: 'metadata' must be a mapping")
        return self.register_actor(
            actor_id=actor_id,
            roles=[str(r) for r in roles],
            resource_roles={k: [str(v) for v in vs] for k, vs in resource_roles.items()},
            metadata=metadata,
        )

    def register_actor_from_jwt(
        self,
        token: str,
        *,
        verify: bool = False,  # noqa: ARG002  — reserved for future sig verification
        secret: str | None = None,  # noqa: ARG002  — reserved for future sig verification
    ) -> RBACManifest:
        """Decode a JWT and register the actor from its claims.

        Extracts:
        * ``sub`` → ``actor_id``
        * ``roles`` → role list (list of strings expected; missing → ``[]``)
        * ``resource_roles`` → per-resource mapping (optional)
        * All remaining claims are stored in ``metadata``.

        Only the *payload* section is decoded (no signature verification
        unless ``verify=True`` with a matching ``secret`` — reserved for a
        future release).

        Args:
            token: JWT string (header.payload.signature).
            verify: Reserved; currently ignored.
            secret: Reserved; currently ignored.

        Returns:
            The newly registered :class:`RBACManifest`.

        Raises:
            ValueError: If the token format is invalid or ``sub`` is absent.
        """
        parts = token.split(".")
        if len(parts) != 3:  # noqa: PLR2004
            raise ValueError("register_actor_from_jwt: token must have 3 dot-separated parts")
        payload_b64 = parts[1]
        # Add padding if necessary
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        try:
            payload_bytes = base64.urlsafe_b64decode(payload_b64)
            claims: dict[str, Any] = json.loads(payload_bytes)
        except Exception as exc:
            raise ValueError(f"register_actor_from_jwt: cannot decode payload — {exc}") from exc

        actor_id = claims.get("sub")
        if not actor_id or not isinstance(actor_id, str):
            raise ValueError("register_actor_from_jwt: 'sub' claim is required and must be a string")

        raw_roles = claims.get("roles", [])
        roles = [str(r) for r in raw_roles] if isinstance(raw_roles, list) else []

        resource_roles_raw = claims.get("resource_roles", {})
        resource_roles: dict[str, list[str]] = {}
        if isinstance(resource_roles_raw, dict):
            for res, rrs in resource_roles_raw.items():
                if isinstance(rrs, list):
                    resource_roles[str(res)] = [str(r) for r in rrs]

        # Store all remaining claims in metadata
        skip_keys = {"sub", "roles", "resource_roles", "iat", "exp", "iss", "aud", "jti"}
        metadata = {k: v for k, v in claims.items() if k not in skip_keys}

        return self.register_actor(
            actor_id=actor_id,
            roles=roles,
            resource_roles=resource_roles,
            metadata=metadata,
        )

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


# ---------------------------------------------------------------------------
# 1C-2: Minimal YAML parser (stdlib fallback when PyYAML is absent)
# ---------------------------------------------------------------------------

def _parse_yaml_safe(yaml_str: str) -> Any:
    """Parse *yaml_str* using PyYAML when available, otherwise use a minimal
    key:value line parser that handles flat mappings and inline lists.

    The minimal parser supports:
    * ``key: scalar_value``
    * ``key: [item1, item2]`` (inline list, single-line)
    * ``key:`` with indented list items (``  - item``)

    Raises:
        ValueError: If the minimal parser cannot handle the input when PyYAML
            is not installed.
    """
    try:
        import yaml  # type: ignore[import-untyped]

        return yaml.safe_load(yaml_str)
    except ImportError:
        pass

    # Minimal stdlib fallback
    return _minimal_yaml_parse(yaml_str)


_LIST_ITEM_RE = re.compile(r"^\s*-\s+(.+)$")
_KEY_VALUE_RE = re.compile(r"^([a-zA-Z_][a-zA-Z0-9_]*):\s*(.*)$")
_INLINE_LIST_RE = re.compile(r"^\[(.+)\]$")


def _minimal_yaml_parse(text: str) -> dict[str, Any]:
    """Very small YAML subset parser (no PyYAML dependency)."""
    result: dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        m = _KEY_VALUE_RE.match(line)
        if m:
            key = m.group(1)
            value_str = m.group(2).strip()
            if not value_str:
                # Check for indented list on subsequent lines
                list_items: list[str] = []
                j = i + 1
                while j < len(lines):
                    lm = _LIST_ITEM_RE.match(lines[j])
                    if lm:
                        list_items.append(lm.group(1).strip().strip("'\""))
                        j += 1
                    else:
                        break
                if list_items:
                    result[key] = list_items
                    i = j
                    continue
                else:
                    result[key] = None
            else:
                # inline list?
                il = _INLINE_LIST_RE.match(value_str)
                if il:
                    items = [v.strip().strip("'\"") for v in il.group(1).split(",")]
                    result[key] = items
                else:
                    result[key] = value_str.strip("'\"")
        i += 1
    return result
