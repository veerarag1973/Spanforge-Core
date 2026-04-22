"""Tests for spanforge.sdk.rbac - Phase 1 sf-rbac client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spanforge.sdk._base import SFClientConfig
from spanforge.sdk.rbac import RBACManifest, RBACStatusInfo, SFRBACClient


def _make_client() -> SFRBACClient:
    return SFRBACClient(SFClientConfig(project_id="test-proj"))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class TestSFRBACClient:
    def test_register_actor_stores_manifest(self) -> None:
        client = _make_client()

        manifest = client.register_actor(
            actor_id="user-001",
            roles=["operator", "operator"],
            resource_roles={"prod.db": ["admin", "admin"]},
            metadata={"team": "platform"},
        )

        stored = client.get_manifest("user-001")
        assert isinstance(manifest, RBACManifest)
        assert stored == manifest
        assert manifest.roles == ["operator"]
        assert manifest.resource_roles["prod.db"] == ["admin"]

    def test_authorize_allows_when_required_roles_are_present(self) -> None:
        client = _make_client()
        client.register_actor(
            actor_id="user-001",
            roles=["operator"],
            resource_roles={"prod.db": ["admin"]},
        )

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = client.authorize(
                trace_id="trace-001",
                actor_id="user-001",
                resource="prod.db",
                action_name="rotate-key",
                checked_at="2026-04-22T11:15:00Z",
                required_roles=["admin"],
                policy_action="allow+log",
            )

        assert payload.allowed is True
        assert payload.outcome == "allow"
        assert payload.effective_roles == ["admin", "operator"]
        assert client.get(payload.check_id) == payload
        assert client.list_for_trace("trace-001") == [payload]

    def test_authorize_blocks_when_required_role_is_missing(self) -> None:
        client = _make_client()
        client.register_actor(
            actor_id="user-001",
            roles=["operator"],
            resource_roles={"prod.db": ["reader"]},
        )

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = client.authorize(
                trace_id="trace-001",
                actor_id="user-001",
                resource="prod.db",
                action_name="rotate-key",
                checked_at="2026-04-22T11:15:00Z",
                required_roles=["admin"],
                policy_action="block",
            )

        assert payload.allowed is False
        assert payload.outcome == "block"
        assert "missing required roles" in payload.reason

    def test_authorize_escalates_when_actor_is_unknown(self) -> None:
        client = _make_client()

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = client.authorize(
                trace_id="trace-001",
                actor_id="user-001",
                resource="prod.db",
                action_name="rotate-key",
                checked_at="2026-04-22T11:15:00Z",
                required_roles=["admin"],
            )

        assert payload.allowed is False
        assert payload.outcome == "escalate"
        assert "no registered RBAC manifest" in payload.reason

    def test_authorize_without_required_roles_allows(self) -> None:
        client = _make_client()
        client.register_actor(
            actor_id="user-001",
            roles=["operator"],
        )

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = client.authorize(
                trace_id="trace-001",
                actor_id="user-001",
                resource="prod.db",
                action_name="view",
                checked_at="2026-04-22T11:15:00Z",
            )

        assert payload.allowed is True
        assert payload.required_roles == []

    def test_status_reflects_registered_actors_and_denials(self) -> None:
        client = _make_client()
        client.register_actor(
            actor_id="user-001",
            roles=["operator"],
        )

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            client.authorize(
                trace_id="trace-001",
                actor_id="user-001",
                resource="prod.db",
                action_name="view",
                checked_at="2026-04-22T11:15:00Z",
            )
            client.authorize(
                trace_id="trace-001",
                actor_id="user-001",
                resource="prod.db",
                action_name="delete",
                checked_at="2026-04-22T11:16:00Z",
                required_roles=["admin"],
                policy_action="human_review",
            )

        status = client.get_status()
        assert isinstance(status, RBACStatusInfo)
        assert status.registered_actors == 1
        assert status.total_checks == 2
        assert status.denied_checks == 1

    def test_authorize_writes_to_sf_audit(self) -> None:
        client = _make_client()
        client.register_actor(
            actor_id="user-001",
            roles=["operator"],
            resource_roles={"prod.db": ["admin"]},
        )

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = client.authorize(
                trace_id="trace-001",
                actor_id="user-001",
                resource="prod.db",
                action_name="rotate-key",
                checked_at="2026-04-22T11:15:00Z",
                required_roles=["admin"],
            )

        mock_audit_module.append.assert_called_once_with(
            payload.to_dict(),
            "spanforge.rbac.v1",
        )

    @pytest.mark.anyio
    async def test_authorize_async(self) -> None:
        client = _make_client()
        client.register_actor(
            actor_id="user-001",
            roles=["operator"],
            resource_roles={"prod.db": ["admin"]},
        )

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = await client.authorize_async(
                trace_id="trace-001",
                actor_id="user-001",
                resource="prod.db",
                action_name="rotate-key",
                checked_at="2026-04-22T11:15:00Z",
                required_roles=["admin"],
            )

        assert payload.actor_id == "user-001"
        assert payload.allowed is True
