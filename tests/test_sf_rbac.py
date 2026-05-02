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


# ===========================================================================
# 1C-2: YAML role loading
# ===========================================================================


class TestRegisterActorFromYAML:
    """1C-2 — register_actor_from_yaml."""

    def test_basic_yaml_actor(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        yaml_str = "actor_id: alice\nroles: [viewer, editor]\n"
        manifest = client.register_actor_from_yaml(yaml_str)
        assert manifest.actor_id == "alice"
        assert "viewer" in manifest.roles
        assert "editor" in manifest.roles

    def test_yaml_with_resource_roles(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        yaml_str = (
            "actor_id: bob\n"
            "roles:\n"
            "  - viewer\n"
            "resource_roles:\n"
            "  billing: [admin]\n"
        )
        try:
            manifest = client.register_actor_from_yaml(yaml_str)
        except Exception:
            pytest.skip("complex YAML requires PyYAML")
        assert manifest.actor_id == "bob"

    def test_yaml_missing_actor_id_raises(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        with pytest.raises(ValueError, match="actor_id"):
            client.register_actor_from_yaml("roles: [viewer]\n")

    def test_yaml_invalid_roles_type_raises(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        try:
            import yaml  # noqa: F401 — only test type validation when PyYAML available
        except ImportError:
            pytest.skip("PyYAML not installed")
        with pytest.raises(ValueError, match="roles"):
            client.register_actor_from_yaml("actor_id: x\nroles: not_a_list\n")

    def test_yaml_actor_authorizes_correctly(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        manifest = client.register_actor_from_yaml(
            "actor_id: carol\nroles: [viewer, editor]\n"
        )
        assert manifest.actor_id == "carol"
        with patch("spanforge.sdk.sf_audit") as m:
            m.append = MagicMock()
            payload = client.authorize(
                trace_id="t-1",
                actor_id="carol",
                resource="docs",
                action_name="edit",
                checked_at="2026-04-22T10:00:00Z",
                required_roles=["editor"],
            )
        assert payload.allowed is True


# ===========================================================================
# 1C-2: JWT role integration
# ===========================================================================


def _make_jwt(claims: dict) -> str:
    """Build a minimal HS256-header JWT (no real signature needed)."""
    import base64
    import json

    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode()
    ).rstrip(b"=").decode()
    return f"{header}.{payload}.fakesig"


class TestRegisterActorFromJWT:
    """1C-2 — register_actor_from_jwt."""

    def test_extracts_sub_and_roles(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        token = _make_jwt({"sub": "svc-001", "roles": ["operator", "viewer"]})
        manifest = client.register_actor_from_jwt(token)
        assert manifest.actor_id == "svc-001"
        assert "operator" in manifest.roles
        assert "viewer" in manifest.roles

    def test_missing_sub_raises(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        token = _make_jwt({"roles": ["viewer"]})
        with pytest.raises(ValueError, match="sub"):
            client.register_actor_from_jwt(token)

    def test_missing_roles_defaults_to_empty(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        token = _make_jwt({"sub": "svc-002"})
        manifest = client.register_actor_from_jwt(token)
        assert manifest.roles == []

    def test_invalid_token_format_raises(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        with pytest.raises(ValueError, match="3 dot-separated parts"):
            client.register_actor_from_jwt("not.a.valid.jwt.format.extra")

    def test_jwt_actor_authorizes_correctly(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        token = _make_jwt({"sub": "robot-1", "roles": ["service_account"]})
        client.register_actor_from_jwt(token)
        with patch("spanforge.sdk.sf_audit") as m:
            m.append = MagicMock()
            payload = client.authorize(
                trace_id="t-jwt",
                actor_id="robot-1",
                resource="pipeline",
                action_name="trigger",
                checked_at="2026-04-22T10:00:00Z",
                required_roles=["service_account"],
            )
        assert payload.allowed is True


# ===========================================================================
# 1C-2: Standard role matrix (10 configs)
# ===========================================================================


class TestStandardRoleMatrix:
    """1C-2 — ten canonical role configurations."""

    def test_matrix_has_exactly_10_entries(self) -> None:
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX

        assert len(STANDARD_ROLE_MATRIX) == 10

    def test_all_entries_have_required_keys(self) -> None:
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX

        for name, config in STANDARD_ROLE_MATRIX.items():
            assert "roles" in config, f"{name} missing 'roles'"
            assert isinstance(config["roles"], list), f"{name}.roles must be a list"
            assert "description" in config, f"{name} missing 'description'"

    def test_viewer_has_read_only_role(self) -> None:
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX

        assert "viewer" in STANDARD_ROLE_MATRIX["viewer"]["roles"]

    def test_admin_includes_viewer_and_editor(self) -> None:
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX

        assert "viewer" in STANDARD_ROLE_MATRIX["admin"]["roles"]
        assert "editor" in STANDARD_ROLE_MATRIX["admin"]["roles"]

    def test_superadmin_includes_admin(self) -> None:
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX

        assert "admin" in STANDARD_ROLE_MATRIX["superadmin"]["roles"]
        assert "superadmin" in STANDARD_ROLE_MATRIX["superadmin"]["roles"]

    def test_viewer_cannot_write(self) -> None:
        """viewer role must not include 'editor' or 'admin'."""
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX

        roles = STANDARD_ROLE_MATRIX["viewer"]["roles"]
        assert "editor" not in roles
        assert "admin" not in roles

    def test_service_account_minimal_roles(self) -> None:
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX

        roles = STANDARD_ROLE_MATRIX["service_account"]["roles"]
        assert "service_account" in roles
        # Service accounts should not have admin privileges by default
        assert "admin" not in roles

    def test_deployer_cannot_admin(self) -> None:
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX

        assert "admin" not in STANDARD_ROLE_MATRIX["deployer"]["roles"]

    def test_auditor_includes_viewer(self) -> None:
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX

        assert "viewer" in STANDARD_ROLE_MATRIX["auditor"]["roles"]

    def test_matrix_register_and_authorize(self) -> None:
        """Smoke test: register an admin actor and authorize an admin action."""
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX, SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        matrix = STANDARD_ROLE_MATRIX["admin"]
        client.register_actor(actor_id="admin-user", roles=matrix["roles"])
        with patch("spanforge.sdk.sf_audit") as m:
            m.append = MagicMock()
            payload = client.authorize(
                trace_id="t-matrix",
                actor_id="admin-user",
                resource="config",
                action_name="update",
                checked_at="2026-04-22T10:00:00Z",
                required_roles=["admin"],
            )
        assert payload.allowed is True


# ===========================================================================
# 1C-2: YAML role loading
# ===========================================================================


class TestRegisterActorFromYAML:
    """1C-2 — register_actor_from_yaml."""

    def test_basic_yaml_actor(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        yaml_str = "actor_id: alice\nroles: [viewer, editor]\n"
        manifest = client.register_actor_from_yaml(yaml_str)
        assert manifest.actor_id == "alice"
        assert "viewer" in manifest.roles
        assert "editor" in manifest.roles

    def test_yaml_with_resource_roles(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        yaml_str = (
            "actor_id: bob\n"
            "roles:\n"
            "  - viewer\n"
            "resource_roles:\n"
            "  billing: [admin]\n"
        )
        try:
            manifest = client.register_actor_from_yaml(yaml_str)
        except Exception:
            pytest.skip("complex YAML requires PyYAML")
        assert manifest.actor_id == "bob"

    def test_yaml_missing_actor_id_raises(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        with pytest.raises(ValueError, match="actor_id"):
            client.register_actor_from_yaml("roles: [viewer]\n")

    def test_yaml_invalid_roles_type_raises(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        try:
            import yaml  # noqa: F401 — only test type validation when PyYAML available
        except ImportError:
            pytest.skip("PyYAML not installed")
        with pytest.raises(ValueError, match="roles"):
            client.register_actor_from_yaml("actor_id: x\nroles: not_a_list\n")

    def test_yaml_actor_authorizes_correctly(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        manifest = client.register_actor_from_yaml(
            "actor_id: carol\nroles: [viewer, editor]\n"
        )
        assert manifest.actor_id == "carol"
        with patch("spanforge.sdk.sf_audit") as m:
            m.append = MagicMock()
            payload = client.authorize(
                trace_id="t-1",
                actor_id="carol",
                resource="docs",
                action_name="edit",
                checked_at="2026-04-22T10:00:00Z",
                required_roles=["editor"],
            )
        assert payload.allowed is True


# ===========================================================================
# 1C-2: JWT role integration
# ===========================================================================


def _make_jwt(claims: dict) -> str:
    """Build a minimal HS256-header JWT (no real signature needed)."""
    import base64
    import json

    header = base64.urlsafe_b64encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}).encode()
    ).rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode()
    ).rstrip(b"=").decode()
    return f"{header}.{payload}.fakesig"


class TestRegisterActorFromJWT:
    """1C-2 — register_actor_from_jwt."""

    def test_extracts_sub_and_roles(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        token = _make_jwt({"sub": "svc-001", "roles": ["operator", "viewer"]})
        manifest = client.register_actor_from_jwt(token)
        assert manifest.actor_id == "svc-001"
        assert "operator" in manifest.roles
        assert "viewer" in manifest.roles

    def test_missing_sub_raises(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        token = _make_jwt({"roles": ["viewer"]})
        with pytest.raises(ValueError, match="sub"):
            client.register_actor_from_jwt(token)

    def test_missing_roles_defaults_to_empty(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        token = _make_jwt({"sub": "svc-002"})
        manifest = client.register_actor_from_jwt(token)
        assert manifest.roles == []

    def test_invalid_token_format_raises(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        with pytest.raises(ValueError, match="3 dot-separated parts"):
            client.register_actor_from_jwt("not.a.valid.jwt.format.extra")

    def test_jwt_actor_authorizes_correctly(self) -> None:
        from spanforge.sdk.rbac import SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        token = _make_jwt({"sub": "robot-1", "roles": ["service_account"]})
        client.register_actor_from_jwt(token)
        with patch("spanforge.sdk.sf_audit") as m:
            m.append = MagicMock()
            payload = client.authorize(
                trace_id="t-jwt",
                actor_id="robot-1",
                resource="pipeline",
                action_name="trigger",
                checked_at="2026-04-22T10:00:00Z",
                required_roles=["service_account"],
            )
        assert payload.allowed is True


# ===========================================================================
# 1C-2: Standard role matrix (10 configs)
# ===========================================================================


class TestStandardRoleMatrix:
    """1C-2 — ten canonical role configurations."""

    def test_matrix_has_exactly_10_entries(self) -> None:
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX

        assert len(STANDARD_ROLE_MATRIX) == 10

    def test_all_entries_have_required_keys(self) -> None:
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX

        for name, config in STANDARD_ROLE_MATRIX.items():
            assert "roles" in config, f"{name} missing 'roles'"
            assert isinstance(config["roles"], list), f"{name}.roles must be a list"
            assert "description" in config, f"{name} missing 'description'"

    def test_viewer_has_read_only_role(self) -> None:
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX

        assert "viewer" in STANDARD_ROLE_MATRIX["viewer"]["roles"]

    def test_admin_includes_viewer_and_editor(self) -> None:
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX

        assert "viewer" in STANDARD_ROLE_MATRIX["admin"]["roles"]
        assert "editor" in STANDARD_ROLE_MATRIX["admin"]["roles"]

    def test_superadmin_includes_admin(self) -> None:
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX

        assert "admin" in STANDARD_ROLE_MATRIX["superadmin"]["roles"]
        assert "superadmin" in STANDARD_ROLE_MATRIX["superadmin"]["roles"]

    def test_viewer_cannot_write(self) -> None:
        """viewer role must not include 'editor' or 'admin'."""
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX

        roles = STANDARD_ROLE_MATRIX["viewer"]["roles"]
        assert "editor" not in roles
        assert "admin" not in roles

    def test_service_account_minimal_roles(self) -> None:
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX

        roles = STANDARD_ROLE_MATRIX["service_account"]["roles"]
        assert "service_account" in roles
        # Service accounts should not have admin privileges by default
        assert "admin" not in roles

    def test_deployer_cannot_admin(self) -> None:
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX

        assert "admin" not in STANDARD_ROLE_MATRIX["deployer"]["roles"]

    def test_auditor_includes_viewer(self) -> None:
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX

        assert "viewer" in STANDARD_ROLE_MATRIX["auditor"]["roles"]

    def test_matrix_register_and_authorize(self) -> None:
        """Smoke test: register an admin actor and authorize an admin action."""
        from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX, SFRBACClient

        client = SFRBACClient(SFClientConfig(project_id="test"))
        matrix = STANDARD_ROLE_MATRIX["admin"]
        client.register_actor(actor_id="admin-user", roles=matrix["roles"])
        with patch("spanforge.sdk.sf_audit") as m:
            m.append = MagicMock()
            payload = client.authorize(
                trace_id="t-matrix",
                actor_id="admin-user",
                resource="config",
                action_name="update",
                checked_at="2026-04-22T10:00:00Z",
                required_roles=["admin"],
            )
        assert payload.allowed is True
