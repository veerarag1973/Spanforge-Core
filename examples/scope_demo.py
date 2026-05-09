"""examples/scope_demo.py — CARD 1B-2 sf_scope production hardening demo.

Demonstrates all hardened features of ``SFScopeClient``:

1. Loading a capability manifest from YAML (``scope_manifest.yaml``).
2. All five action category paths (read / write / execute / admin / stream).
3. Audit chain — every check (allow *and* deny) is appended to sf_audit.
4. Fail-secure circuit breaker — opens after emit failures, denies all.
5. Wildcard resource fallback from ``allowed_actions``.

Run:
    python examples/scope_demo.py
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from spanforge.sdk._base import SFClientConfig
from spanforge.sdk.scope import ACTION_CATEGORIES, SFScopeClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MANIFEST_PATH = Path(__file__).parent / "scope_manifest.yaml"


def _make_client() -> SFScopeClient:
    return SFScopeClient(SFClientConfig(project_id="demo-proj"))


def _print_payload(payload: object, label: str) -> None:
    allowed = getattr(payload, "allowed", "?")
    outcome = getattr(payload, "outcome", "?")
    reason = getattr(payload, "reason", "")
    mark = "✓" if allowed else "✗"
    print(f"  [{mark}] {label:<36}  outcome={outcome!r:<12}  {reason[:60]}")


# ---------------------------------------------------------------------------
# 1. YAML manifest loader
# ---------------------------------------------------------------------------


def demo_yaml_loader() -> SFScopeClient:
    print("\n=== 1. Load manifest from YAML ===")
    client = _make_client()
    with patch("spanforge.sdk.sf_audit") as mock_audit:
        mock_audit.append = MagicMock()
        manifest = client.load_manifest_from_yaml(_MANIFEST_PATH)
    print(f"  agent_id        : {manifest.agent_id}")
    print(f"  capabilities    : {manifest.capabilities}")
    print(f"  resource_actions: {list(manifest.resource_actions.keys())}")
    print(f"  allowed_actions : {manifest.resource_actions.get('*')}")
    return client


# ---------------------------------------------------------------------------
# 2. Five action category paths
# ---------------------------------------------------------------------------


def demo_action_categories(client: SFScopeClient) -> None:
    print("\n=== 2. Five action category paths ===")
    agent_id = "demo-agent"
    base_kw: dict = dict(trace_id="demo-trace-001", checked_at="2026-05-09T12:00:00Z")

    tests = [
        # (label, resource, action, capability, policy_action)
        ("read — allowed",                    "files",       "read",    None,           None),
        ("write — blocked (not in manifest)", "files",       "write",   None,           "block"),
        ("external API — allowed (execute)",  "external.api","execute", "tool.execute", None),
        ("internal API — escalate (admin)",   "internal.api","admin",   None,           None),
        ("user-facing output — allowed",      "output",      "stream",  None,           None),
    ]

    for label, resource, action, capability, policy_action in tests:
        kwargs = dict(
            agent_id=agent_id,
            resource=resource,
            action_name=action,
            **base_kw,
        )
        if capability:
            kwargs["capability"] = capability
        if policy_action:
            kwargs["policy_action"] = policy_action

        with patch("spanforge.sdk.sf_audit") as mock_audit:
            mock_audit.append = MagicMock()
            payload = client.evaluate(**kwargs)

        _print_payload(payload, label)

    print(f"\n  ACTION_CATEGORIES keys: {sorted(ACTION_CATEGORIES)}")


# ---------------------------------------------------------------------------
# 3. Audit chain — pass AND fail both append to sf_audit
# ---------------------------------------------------------------------------


def demo_audit_chain(client: SFScopeClient) -> None:
    print("\n=== 3. Audit chain (pass & fail) ===")
    calls: list[str] = []

    def _record(payload: dict, schema: str) -> None:  # type: ignore[misc]
        calls.append(f"{schema} allowed={payload.get('allowed')}")

    with patch("spanforge.sdk.sf_audit") as mock_audit:
        mock_audit.append = MagicMock(side_effect=_record)

        client.evaluate(
            trace_id="audit-demo", agent_id="demo-agent",
            resource="files", action_name="read",
            checked_at="2026-05-09T12:00:00Z",
        )
        client.evaluate(
            trace_id="audit-demo", agent_id="demo-agent",
            resource="files", action_name="delete",  # not in manifest → denied
            checked_at="2026-05-09T12:01:00Z",
        )

    for c in calls:
        print(f"  audit record: {c}")


# ---------------------------------------------------------------------------
# 4. Fail-secure circuit breaker
# ---------------------------------------------------------------------------


def demo_circuit_breaker() -> None:
    print("\n=== 4. Fail-secure circuit breaker ===")
    client = SFScopeClient(SFClientConfig(), cb_threshold=3, cb_reset_seconds=60.0)
    client.register_agent(
        agent_id="cb-agent",
        resource_actions={"res": ["read"]},
    )

    print("  Simulating 3 consecutive emit failures …")
    with patch("spanforge.sdk.sf_audit") as mock_audit:
        mock_audit.append = MagicMock(side_effect=RuntimeError("audit unavailable"))
        for i in range(3):
            client.evaluate(
                trace_id=f"cb-trace-{i}", agent_id="cb-agent",
                resource="res", action_name="read",
                checked_at="2026-05-09T12:00:00Z",
            )

    print(f"  circuit state   : {client._circuit_breaker.state!r}")

    with patch("spanforge.sdk.sf_audit") as mock_audit, \
         patch("spanforge.sdk.sf_alert") as mock_alert:
        mock_audit.append = MagicMock()
        mock_alert.publish = MagicMock()
        payload = client.evaluate(
            trace_id="cb-open", agent_id="cb-agent",
            resource="res", action_name="read",
            checked_at="2026-05-09T12:01:00Z",
        )
    _print_payload(payload, "evaluate() while circuit OPEN")
    print(f"  sf_alert.publish called: {mock_alert.publish.called}")


# ---------------------------------------------------------------------------
# 5. Wildcard resource fallback
# ---------------------------------------------------------------------------


def demo_wildcard_resource(client: SFScopeClient) -> None:
    print("\n=== 5. Wildcard resource fallback ===")
    # 'mystery.resource' is not in resource_actions explicitly,
    # so falls back to the '*' wildcard from allowed_actions.
    with patch("spanforge.sdk.sf_audit") as mock_audit:
        mock_audit.append = MagicMock()
        payload = client.evaluate(
            trace_id="wildcard-demo", agent_id="demo-agent",
            resource="mystery.resource", action_name="stream",
            checked_at="2026-05-09T12:00:00Z",
        )
    _print_payload(payload, "stream on unknown resource → wildcard *")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("SpanForge sf-scope production hardening demo (CARD 1B-2)")
    print("=" * 60)

    client = demo_yaml_loader()
    demo_action_categories(client)
    demo_audit_chain(client)
    demo_circuit_breaker()
    demo_wildcard_resource(client)

    print("\n✓ Demo complete.")


if __name__ == "__main__":
    main()
