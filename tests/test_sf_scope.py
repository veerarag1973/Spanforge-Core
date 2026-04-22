"""Tests for spanforge.sdk.scope - Phase 1 sf-scope client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spanforge.sdk._base import SFClientConfig
from spanforge.sdk._exceptions import SFScopeError
from spanforge.sdk.scope import ScopeManifest, ScopeStatusInfo, SFScopeClient


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
