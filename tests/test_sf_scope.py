"""Tests for spanforge.sdk.scope - Phase 1 sf-scope client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spanforge.sdk._base import SFClientConfig
from spanforge.sdk._exceptions import SFScopeError
from spanforge.sdk.scope import ACTION_CATEGORIES, ScopeManifest, ScopeStatusInfo, SFScopeClient


def _make_client() -> SFScopeClient:
    return SFScopeClient(SFClientConfig(project_id="test-proj"))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class TestSFScopeClient:
    def test_register_agent_stores_manifest(self) -> None:
        client = _make_client()

        manifest = client.register_agent(
            agent_id="agent-001",
            capabilities=["tool.read", "tool.read"],
            resource_actions={"repo.file": ["read", "read"], "repo.issue": ["comment"]},
            metadata={"team": "governance"},
        )

        stored = client.get_manifest("agent-001")
        assert isinstance(manifest, ScopeManifest)
        assert stored == manifest
        assert manifest.capabilities == ["tool.read"]
        assert manifest.resource_actions["repo.file"] == ["read"]

    def test_evaluate_allows_registered_scope(self) -> None:
        client = _make_client()
        client.register_agent(
            agent_id="agent-001",
            capabilities=["tool.read"],
            resource_actions={"repo.file": ["read"]},
        )

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = client.evaluate(
                trace_id="trace-001",
                agent_id="agent-001",
                resource="repo.file",
                action_name="read",
                capability="tool.read",
                checked_at="2026-04-22T10:30:00Z",
                policy_action="allow+log",
            )

        assert payload.allowed is True
        assert payload.outcome == "allow"
        assert client.get(payload.scope_id) == payload
        assert client.list_for_trace("trace-001") == [payload]

    def test_evaluate_blocks_missing_capability(self) -> None:
        client = _make_client()
        client.register_agent(
            agent_id="agent-001",
            capabilities=["tool.read"],
            resource_actions={"repo.file": ["read"]},
        )

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = client.evaluate(
                trace_id="trace-001",
                agent_id="agent-001",
                resource="repo.file",
                action_name="read",
                capability="tool.write",
                checked_at="2026-04-22T10:30:00Z",
                policy_action="block",
            )

        assert payload.allowed is False
        assert payload.outcome == "block"
        assert "missing required capability" in payload.reason

    def test_evaluate_escalates_when_resource_not_registered(self) -> None:
        client = _make_client()
        client.register_agent(
            agent_id="agent-001",
            capabilities=["tool.read"],
            resource_actions={"repo.file": ["read"]},
        )

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = client.evaluate(
                trace_id="trace-001",
                agent_id="agent-001",
                resource="repo.secret",
                action_name="read",
                checked_at="2026-04-22T10:30:00Z",
            )

        assert payload.allowed is False
        assert payload.outcome == "escalate"
        assert "not permitted to access resource" in payload.reason

    def test_require_capability_raises_scope_error(self) -> None:
        client = _make_client()
        client.register_agent(
            agent_id="agent-001",
            capabilities=["tool.read"],
            resource_actions={"repo.file": ["read"]},
        )

        with pytest.raises(SFScopeError) as excinfo:
            client.require_capability("agent-001", "tool.write")

        assert excinfo.value.required_scope == "tool.write"
        assert excinfo.value.key_scopes == ["tool.read"]

    def test_status_reflects_registered_agents_and_blocks(self) -> None:
        client = _make_client()
        client.register_agent(
            agent_id="agent-001",
            capabilities=["tool.read"],
            resource_actions={"repo.file": ["read"]},
        )

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            client.evaluate(
                trace_id="trace-001",
                agent_id="agent-001",
                resource="repo.file",
                action_name="read",
                checked_at="2026-04-22T10:30:00Z",
            )
            client.evaluate(
                trace_id="trace-001",
                agent_id="agent-001",
                resource="repo.file",
                action_name="write",
                checked_at="2026-04-22T10:31:00Z",
                policy_action="human_review",
            )

        status = client.get_status()
        assert isinstance(status, ScopeStatusInfo)
        assert status.registered_agents == 1
        assert status.total_checks == 2
        assert status.blocked_checks == 1

    def test_evaluate_writes_to_sf_audit(self) -> None:
        client = _make_client()
        client.register_agent(
            agent_id="agent-001",
            capabilities=["tool.read"],
            resource_actions={"repo.file": ["read"]},
        )

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = client.evaluate(
                trace_id="trace-001",
                agent_id="agent-001",
                resource="repo.file",
                action_name="read",
                checked_at="2026-04-22T10:30:00Z",
            )

        mock_audit_module.append.assert_called_once_with(
            payload.to_dict(),
            "spanforge.scope.v1",
        )

    @pytest.mark.anyio
    async def test_evaluate_async(self) -> None:
        client = _make_client()
        client.register_agent(
            agent_id="agent-001",
            capabilities=["tool.read"],
            resource_actions={"repo.file": ["read"]},
        )

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = await client.evaluate_async(
                trace_id="trace-001",
                agent_id="agent-001",
                resource="repo.file",
                action_name="read",
                checked_at="2026-04-22T10:30:00Z",
            )

        assert payload.agent_id == "agent-001"
        assert payload.allowed is True


# ---------------------------------------------------------------------------
# 1B-2: Circuit breaker tests
# ---------------------------------------------------------------------------


def _eval(client: SFScopeClient, *, action: str = "read") -> object:
    """Helper: evaluate with patched audit; manifest must already be registered."""
    with patch("spanforge.sdk.sf_audit") as m:
        m.append = MagicMock()
        return client.evaluate(
            trace_id="trace-cb",
            agent_id="agent-cb",
            resource="res",
            action_name=action,
            checked_at="2026-04-22T10:00:00Z",
        )


class TestCircuitBreaker:
    """1B-2 — circuit breaker integration."""

    def _make_client_with_agent(self) -> SFScopeClient:
        c = SFScopeClient(SFClientConfig(), cb_threshold=3, cb_reset_seconds=60.0)
        c.register_agent(
            agent_id="agent-cb",
            capabilities=["tool.read"],
            resource_actions={"res": ["read", "write"]},
        )
        return c

    def test_circuit_opens_after_threshold_emit_failures(self) -> None:
        client = self._make_client_with_agent()
        with patch("spanforge.sdk.sf_audit") as m:
            m.append = MagicMock(side_effect=RuntimeError("audit down"))
            for _ in range(3):  # threshold = 3
                client.evaluate(
                    trace_id="trace-cb",
                    agent_id="agent-cb",
                    resource="res",
                    action_name="read",
                    checked_at="2026-04-22T10:00:00Z",
                )
        assert client._circuit_breaker.is_open()

    def test_circuit_fail_secure_when_open(self) -> None:
        """Once open the circuit returns denied immediately without consulting the manifest."""
        client = self._make_client_with_agent()
        # Force the circuit open
        client._circuit_breaker.record_failure()
        client._circuit_breaker.record_failure()
        client._circuit_breaker.record_failure()  # threshold = 3
        assert client._circuit_breaker.is_open()

        # evaluate must return a denied result, not a normal allow
        payload = _eval(client)
        assert payload.allowed is False
        assert payload.outcome == "block"
        assert "circuit" in payload.reason.lower()

    def test_circuit_closed_by_default(self) -> None:
        client = self._make_client_with_agent()
        assert not client._circuit_breaker.is_open()

    def test_successful_eval_keeps_circuit_closed(self) -> None:
        client = self._make_client_with_agent()
        _eval(client)
        assert not client._circuit_breaker.is_open()

    def test_circuit_can_be_reset_manually(self) -> None:
        client = self._make_client_with_agent()
        client._circuit_breaker.record_failure()
        client._circuit_breaker.record_failure()
        client._circuit_breaker.record_failure()
        assert client._circuit_breaker.is_open()
        client._circuit_breaker.reset()
        assert not client._circuit_breaker.is_open()


# ---------------------------------------------------------------------------
# 1B-2: Action category tests
# ---------------------------------------------------------------------------


class TestActionCategories:
    """1B-2 — five action category paths through sf-scope."""

    def _make_client_with_all_actions(self) -> SFScopeClient:
        c = SFScopeClient(SFClientConfig())
        c.register_agent(
            agent_id="agent-cat",
            resource_actions={
                "db": ["read", "write", "delete"],
                "service": ["execute", "invoke"],
                "infra": ["admin", "configure"],
                "bus": ["stream", "subscribe"],
            },
        )
        return c

    def _evaluate_action(
        self, client: SFScopeClient, *, resource: str, action: str
    ) -> object:
        with patch("spanforge.sdk.sf_audit") as m:
            m.append = MagicMock()
            return client.evaluate(
                trace_id="trace-cat",
                agent_id="agent-cat",
                resource=resource,
                action_name=action,
                checked_at="2026-04-22T10:00:00Z",
            )

    def test_action_category_read_allowed(self) -> None:
        client = self._make_client_with_all_actions()
        payload = self._evaluate_action(client, resource="db", action="read")
        assert payload.allowed is True
        assert SFScopeClient.resolve_action_category("read") == "read"

    def test_action_category_write_allowed(self) -> None:
        client = self._make_client_with_all_actions()
        payload = self._evaluate_action(client, resource="db", action="write")
        assert payload.allowed is True
        assert SFScopeClient.resolve_action_category("write") == "write"

    def test_action_category_execute_allowed(self) -> None:
        client = self._make_client_with_all_actions()
        payload = self._evaluate_action(client, resource="service", action="execute")
        assert payload.allowed is True
        assert SFScopeClient.resolve_action_category("execute") == "execute"

    def test_action_category_admin_denied_without_explicit_registration(self) -> None:
        """Admin actions on resources where only read+write are registered → denied."""
        c = SFScopeClient(SFClientConfig())
        c.register_agent(
            agent_id="agent-cat",
            resource_actions={"db": ["read", "write"]},
        )
        payload = self._evaluate_action(c, resource="db", action="admin")
        assert payload.allowed is False
        assert SFScopeClient.resolve_action_category("admin") == "admin"

    def test_action_category_stream_allowed(self) -> None:
        client = self._make_client_with_all_actions()
        payload = self._evaluate_action(client, resource="bus", action="stream")
        assert payload.allowed is True
        assert SFScopeClient.resolve_action_category("stream") == "stream"

    def test_action_categories_have_five_keys(self) -> None:
        assert set(ACTION_CATEGORIES.keys()) == {"read", "write", "execute", "admin", "stream"}

    def test_resolve_unknown_action_returns_none(self) -> None:
        assert SFScopeClient.resolve_action_category("xyzzy") is None
