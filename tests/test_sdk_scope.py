"""tests/test_sdk_scope.py — CARD 1B-2 sf_scope production hardening tests.

Covers:
* YAML manifest loader (load_manifest_from_yaml)
* Five action category paths (read / write / external-API / internal-API / user-output)
* Audit chain — every check (allow AND deny) appended to sf_audit
* Fail-secure circuit breaker — opens after 5 consecutive emit failures
* Alert emission when circuit is open
* Wildcard resource fallback from allowed_actions
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from spanforge.sdk._base import SFClientConfig
from spanforge.sdk.scope import _parse_scope_yaml, ScopeManifest, SFScopeClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client(**kwargs: object) -> SFScopeClient:
    return SFScopeClient(SFClientConfig(project_id="test-1b2"), **kwargs)  # type: ignore[arg-type]


_BASE_YAML = """\
agent_id: agent-test
allowed_actions:
  - read
  - execute
  - stream
capabilities:
  - tool.read
  - tool.execute
  - tool.stream
metadata:
  team: test
"""

_YAML_WITH_RESOURCE_ACTIONS = """\
agent_id: agent-res
allowed_actions:
  - read
  - execute
  - stream
resource_actions:
  files:
    - read
    - list
  external.api:
    - execute
    - invoke
  output:
    - stream
    - emit
capabilities:
  - tool.execute
"""


def _write_manifest(tmp_path: Path, content: str) -> Path:
    p = tmp_path / "scope_manifest.yaml"
    p.write_text(content, encoding="utf-8")
    return p


def _evaluate(
    client: SFScopeClient,
    *,
    agent_id: str,
    resource: str,
    action: str,
    capability: str | None = None,
    policy_action: str | None = None,
    trace_id: str = "trace-1b2",
) -> object:
    kwargs: dict = dict(
        trace_id=trace_id,
        agent_id=agent_id,
        resource=resource,
        action_name=action,
        checked_at="2026-05-09T10:00:00Z",
    )
    if capability is not None:
        kwargs["capability"] = capability
    if policy_action is not None:
        kwargs["policy_action"] = policy_action
    with patch("spanforge.sdk.sf_audit") as m:
        m.append = MagicMock()
        return client.evaluate(**kwargs)


# ---------------------------------------------------------------------------
# _parse_scope_yaml unit tests
# ---------------------------------------------------------------------------


class TestParseScopeYaml:
    """Zero-dep YAML parser for scope manifests."""

    def test_parses_agent_id_and_allowed_actions(self) -> None:
        data = _parse_scope_yaml(_BASE_YAML)
        assert data["agent_id"] == "agent-test"
        assert data["allowed_actions"] == ["read", "execute", "stream"]

    def test_parses_capabilities(self) -> None:
        data = _parse_scope_yaml(_BASE_YAML)
        assert data["capabilities"] == ["tool.read", "tool.execute", "tool.stream"]

    def test_parses_metadata(self) -> None:
        data = _parse_scope_yaml(_BASE_YAML)
        assert data.get("metadata", {}).get("team") == "test"

    def test_parses_resource_actions(self) -> None:
        data = _parse_scope_yaml(_YAML_WITH_RESOURCE_ACTIONS)
        ra = data.get("resource_actions", {})
        assert "files" in ra
        assert "read" in ra["files"]
        assert "external.api" in ra
        assert "execute" in ra["external.api"]

    def test_ignores_comments_and_blank_lines(self) -> None:
        yaml = "# comment\n\nagent_id: my-agent\n\n# another\nallowed_actions:\n  - read\n"
        data = _parse_scope_yaml(yaml)
        assert data["agent_id"] == "my-agent"
        assert data["allowed_actions"] == ["read"]

    def test_empty_string_returns_empty_dict(self) -> None:
        assert _parse_scope_yaml("") == {}


# ---------------------------------------------------------------------------
# YAML manifest loader
# ---------------------------------------------------------------------------


class TestLoadManifestFromYaml:
    """load_manifest_from_yaml() parses and registers agent manifests."""

    def test_registers_agent_from_yaml(self, tmp_path: Path) -> None:
        p = _write_manifest(tmp_path, _BASE_YAML)
        client = _make_client()
        manifest = client.load_manifest_from_yaml(p)

        assert isinstance(manifest, ScopeManifest)
        assert manifest.agent_id == "agent-test"
        assert "tool.read" in manifest.capabilities
        assert client.get_manifest("agent-test") is manifest

    def test_allowed_actions_stored_as_wildcard_resource(self, tmp_path: Path) -> None:
        p = _write_manifest(tmp_path, _BASE_YAML)
        client = _make_client()
        manifest = client.load_manifest_from_yaml(p)

        wildcard = manifest.resource_actions.get("*")
        assert wildcard is not None
        assert "read" in wildcard
        assert "execute" in wildcard
        assert "stream" in wildcard

    def test_explicit_resource_actions_preserved(self, tmp_path: Path) -> None:
        p = _write_manifest(tmp_path, _YAML_WITH_RESOURCE_ACTIONS)
        client = _make_client()
        manifest = client.load_manifest_from_yaml(p)

        assert "files" in manifest.resource_actions
        assert "read" in manifest.resource_actions["files"]
        assert "external.api" in manifest.resource_actions

    def test_missing_agent_id_raises_value_error(self, tmp_path: Path) -> None:
        p = _write_manifest(tmp_path, "allowed_actions:\n  - read\n")
        client = _make_client()
        with pytest.raises(ValueError, match="agent_id"):
            client.load_manifest_from_yaml(p)

    def test_missing_allowed_actions_raises_value_error(self, tmp_path: Path) -> None:
        p = _write_manifest(tmp_path, "agent_id: my-agent\n")
        client = _make_client()
        with pytest.raises(ValueError, match="allowed_actions"):
            client.load_manifest_from_yaml(p)

    def test_empty_allowed_actions_raises_value_error(self, tmp_path: Path) -> None:
        p = _write_manifest(tmp_path, "agent_id: my-agent\nallowed_actions: []\n")
        client = _make_client()
        with pytest.raises(ValueError, match="allowed_actions"):
            client.load_manifest_from_yaml(p)

    def test_file_not_found_raises_os_error(self, tmp_path: Path) -> None:
        client = _make_client()
        with pytest.raises(OSError):
            client.load_manifest_from_yaml(tmp_path / "missing.yaml")

    def test_load_manifest_parses_correctly_from_example_file(self) -> None:
        """The checked-in examples/scope_manifest.yaml must be parseable."""
        example = Path(__file__).parents[1] / "examples" / "scope_manifest.yaml"
        client = _make_client()
        manifest = client.load_manifest_from_yaml(example)
        assert manifest.agent_id == "demo-agent"
        assert "*" in manifest.resource_actions


# ---------------------------------------------------------------------------
# CARD 1B-2: five action category tests
# ---------------------------------------------------------------------------


class TestActionCategoryRead:
    """CARD 1B-2 — read action: allowed."""

    def test_read_action_allowed(self, tmp_path: Path) -> None:
        p = _write_manifest(tmp_path, _BASE_YAML)
        client = _make_client()
        client.load_manifest_from_yaml(p)

        with patch("spanforge.sdk.sf_audit") as mock_audit:
            mock_audit.append = MagicMock()
            payload = client.evaluate(
                trace_id="trace-read",
                agent_id="agent-test",
                resource="any.resource",
                action_name="read",
                checked_at="2026-05-09T10:00:00Z",
            )

        assert payload.allowed is True
        assert payload.outcome == "allow"
        # Audit record emitted for PASS case
        mock_audit.append.assert_called_once()


class TestActionCategoryWrite:
    """CARD 1B-2 — write action: blocked (not in manifest)."""

    def test_write_action_blocked_not_in_manifest(self, tmp_path: Path) -> None:
        # _BASE_YAML allowed_actions = [read, execute, stream] — no "write"
        p = _write_manifest(tmp_path, _BASE_YAML)
        client = _make_client()
        client.load_manifest_from_yaml(p)

        with patch("spanforge.sdk.sf_audit") as mock_audit:
            mock_audit.append = MagicMock()
            payload = client.evaluate(
                trace_id="trace-write",
                agent_id="agent-test",
                resource="any.resource",
                action_name="write",
                checked_at="2026-05-09T10:00:00Z",
                policy_action="block",
            )

        assert payload.allowed is False
        assert payload.outcome == "block"
        # Audit record emitted for FAIL case too
        mock_audit.append.assert_called_once()


class TestActionCategoryExternalAPI:
    """CARD 1B-2 — external API call: allowed with condition (capability required)."""

    def test_external_api_call_allowed_with_condition(self, tmp_path: Path) -> None:
        p = _write_manifest(tmp_path, _BASE_YAML)
        client = _make_client()
        client.load_manifest_from_yaml(p)

        with patch("spanforge.sdk.sf_audit") as mock_audit:
            mock_audit.append = MagicMock()
            payload = client.evaluate(
                trace_id="trace-ext",
                agent_id="agent-test",
                resource="external.api",
                action_name="execute",
                # Condition: must hold tool.execute capability
                capability="tool.execute",
                checked_at="2026-05-09T10:00:00Z",
            )

        assert payload.allowed is True
        assert payload.outcome == "allow"
        mock_audit.append.assert_called_once()

    def test_external_api_call_denied_when_capability_missing(self, tmp_path: Path) -> None:
        p = _write_manifest(tmp_path, _BASE_YAML)
        client = _make_client()
        client.load_manifest_from_yaml(p)

        with patch("spanforge.sdk.sf_audit") as mock_audit:
            mock_audit.append = MagicMock()
            payload = client.evaluate(
                trace_id="trace-ext-deny",
                agent_id="agent-test",
                resource="external.api",
                action_name="execute",
                capability="tool.admin",  # NOT in manifest capabilities
                checked_at="2026-05-09T10:00:00Z",
                policy_action="block",
            )

        assert payload.allowed is False


class TestActionCategoryInternalAPI:
    """CARD 1B-2 — internal API call: escalate (action not in manifest, no policy_action)."""

    def test_internal_api_call_escalates(self, tmp_path: Path) -> None:
        # "admin" is not in allowed_actions → blocked; no policy_action → escalate
        p = _write_manifest(tmp_path, _BASE_YAML)
        client = _make_client()
        client.load_manifest_from_yaml(p)

        with patch("spanforge.sdk.sf_audit") as mock_audit:
            mock_audit.append = MagicMock()
            payload = client.evaluate(
                trace_id="trace-int",
                agent_id="agent-test",
                resource="internal.api",
                action_name="admin",
                checked_at="2026-05-09T10:00:00Z",
                # No policy_action → _resolve_outcome returns "escalate"
            )

        assert payload.allowed is False
        assert payload.outcome == "escalate"
        mock_audit.append.assert_called_once()


class TestActionCategoryUserOutput:
    """CARD 1B-2 — user-facing output: allowed."""

    def test_user_facing_output_allowed(self, tmp_path: Path) -> None:
        p = _write_manifest(tmp_path, _BASE_YAML)
        client = _make_client()
        client.load_manifest_from_yaml(p)

        with patch("spanforge.sdk.sf_audit") as mock_audit:
            mock_audit.append = MagicMock()
            payload = client.evaluate(
                trace_id="trace-out",
                agent_id="agent-test",
                resource="output.channel",
                action_name="stream",
                checked_at="2026-05-09T10:00:00Z",
            )

        assert payload.allowed is True
        assert payload.outcome == "allow"
        mock_audit.append.assert_called_once()


# ---------------------------------------------------------------------------
# Audit chain — every check (pass AND fail) appends to sf_audit
# ---------------------------------------------------------------------------


class TestAuditChain:
    """Every scope check, whether allowed or denied, must append to sf_audit."""

    def test_allowed_check_appends_to_audit(self) -> None:
        client = _make_client()
        client.register_agent(
            agent_id="aud-agent",
            resource_actions={"res": ["read"]},
        )
        with patch("spanforge.sdk.sf_audit") as m:
            m.append = MagicMock()
            client.evaluate(
                trace_id="t1", agent_id="aud-agent",
                resource="res", action_name="read",
                checked_at="2026-05-09T10:00:00Z",
            )
        m.append.assert_called_once()
        args = m.append.call_args
        assert args[0][1] == "spanforge.scope.v1"
        assert args[0][0]["allowed"] is True

    def test_denied_check_appends_to_audit(self) -> None:
        client = _make_client()
        client.register_agent(
            agent_id="aud-agent",
            resource_actions={"res": ["read"]},
        )
        with patch("spanforge.sdk.sf_audit") as m:
            m.append = MagicMock()
            client.evaluate(
                trace_id="t2", agent_id="aud-agent",
                resource="res", action_name="delete",
                checked_at="2026-05-09T10:00:00Z",
            )
        m.append.assert_called_once()
        args = m.append.call_args
        assert args[0][0]["allowed"] is False

    def test_every_check_uses_scope_schema_key(self) -> None:
        client = _make_client()
        client.register_agent(
            agent_id="aud-agent",
            resource_actions={"res": ["read"]},
        )
        with patch("spanforge.sdk.sf_audit") as m:
            m.append = MagicMock()
            for action in ("read", "write", "delete"):
                client.evaluate(
                    trace_id="t3", agent_id="aud-agent",
                    resource="res", action_name=action,
                    checked_at="2026-05-09T10:00:00Z",
                )
        assert m.append.call_count == 3
        for c in m.append.call_args_list:
            assert c[0][1] == "spanforge.scope.v1"

    def test_unregistered_agent_check_appends_to_audit(self) -> None:
        """Even a denied check for an unregistered agent must reach sf_audit."""
        client = _make_client()
        with patch("spanforge.sdk.sf_audit") as m:
            m.append = MagicMock()
            payload = client.evaluate(
                trace_id="t4", agent_id="no-such-agent",
                resource="res", action_name="read",
                checked_at="2026-05-09T10:00:00Z",
            )
        assert payload.allowed is False
        m.append.assert_called_once()


# ---------------------------------------------------------------------------
# Fail-secure circuit breaker
# ---------------------------------------------------------------------------


class TestCircuitBreakerFailSecure:
    """Circuit breaker opens after 5 consecutive emit failures and fails-secure."""

    def _make_with_agent(self, **cb_kwargs: object) -> SFScopeClient:
        c = SFScopeClient(SFClientConfig(), **cb_kwargs)  # type: ignore[arg-type]
        c.register_agent(
            agent_id="cb-agent",
            resource_actions={"res": ["read"]},
        )
        return c

    def test_circuit_opens_after_5_consecutive_failures(self) -> None:
        client = self._make_with_agent(cb_threshold=5, cb_reset_seconds=60.0)
        with patch("spanforge.sdk.sf_audit") as m:
            m.append = MagicMock(side_effect=RuntimeError("audit down"))
            for _ in range(5):
                client.evaluate(
                    trace_id="cb-t", agent_id="cb-agent",
                    resource="res", action_name="read",
                    checked_at="2026-05-09T10:00:00Z",
                )
        assert client._circuit_breaker.is_open()

    def test_circuit_not_open_after_4_failures(self) -> None:
        client = self._make_with_agent(cb_threshold=5, cb_reset_seconds=60.0)
        with patch("spanforge.sdk.sf_audit") as m:
            m.append = MagicMock(side_effect=RuntimeError("audit down"))
            for _ in range(4):
                client.evaluate(
                    trace_id="cb-t", agent_id="cb-agent",
                    resource="res", action_name="read",
                    checked_at="2026-05-09T10:00:00Z",
                )
        assert not client._circuit_breaker.is_open()

    def test_open_circuit_denies_all_actions(self) -> None:
        client = self._make_with_agent(cb_threshold=3, cb_reset_seconds=60.0)
        # Force circuit open
        for _ in range(3):
            client._circuit_breaker.record_failure()
        assert client._circuit_breaker.is_open()

        with patch("spanforge.sdk.sf_audit") as m, \
             patch("spanforge.sdk.sf_alert") as ma:
            m.append = MagicMock()
            ma.publish = MagicMock()
            payload = client.evaluate(
                trace_id="open-t", agent_id="cb-agent",
                resource="res", action_name="read",
                checked_at="2026-05-09T10:00:00Z",
            )
        assert payload.allowed is False
        assert payload.outcome == "block"
        assert "circuit" in payload.reason.lower()

    def test_open_circuit_emits_sf_alert(self) -> None:
        client = self._make_with_agent(cb_threshold=3, cb_reset_seconds=60.0)
        for _ in range(3):
            client._circuit_breaker.record_failure()

        with patch("spanforge.sdk.sf_audit") as m, \
             patch("spanforge.sdk.sf_alert") as ma:
            m.append = MagicMock()
            ma.publish = MagicMock()
            client.evaluate(
                trace_id="alert-t", agent_id="cb-agent",
                resource="res", action_name="read",
                checked_at="2026-05-09T10:00:00Z",
            )
        ma.publish.assert_called_once()
        call_kwargs = ma.publish.call_args
        topic = call_kwargs[0][0]
        assert "scope" in topic or "circuit" in topic

    def test_open_circuit_increments_blocked_checks(self) -> None:
        client = self._make_with_agent(cb_threshold=3, cb_reset_seconds=60.0)
        for _ in range(3):
            client._circuit_breaker.record_failure()

        with patch("spanforge.sdk.sf_audit") as m, \
             patch("spanforge.sdk.sf_alert") as ma:
            m.append = MagicMock()
            ma.publish = MagicMock()
            client.evaluate(
                trace_id="cnt-t", agent_id="cb-agent",
                resource="res", action_name="read",
                checked_at="2026-05-09T10:00:00Z",
            )
        status = client.get_status()
        assert status.blocked_checks >= 1

    def test_circuit_reset_resumes_normal_evaluation(self) -> None:
        client = self._make_with_agent(cb_threshold=3, cb_reset_seconds=60.0)
        for _ in range(3):
            client._circuit_breaker.record_failure()
        assert client._circuit_breaker.is_open()

        client._circuit_breaker.reset()
        assert not client._circuit_breaker.is_open()

        with patch("spanforge.sdk.sf_audit") as m:
            m.append = MagicMock()
            payload = client.evaluate(
                trace_id="reset-t", agent_id="cb-agent",
                resource="res", action_name="read",
                checked_at="2026-05-09T10:00:00Z",
            )
        assert payload.allowed is True

    def test_success_after_failures_closes_circuit(self) -> None:
        client = self._make_with_agent(cb_threshold=3, cb_reset_seconds=60.0)
        # Two failures (below threshold)
        for _ in range(2):
            client._circuit_breaker.record_failure()
        # One success — resets counter
        with patch("spanforge.sdk.sf_audit") as m:
            m.append = MagicMock()
            client.evaluate(
                trace_id="suc-t", agent_id="cb-agent",
                resource="res", action_name="read",
                checked_at="2026-05-09T10:00:00Z",
            )
        assert not client._circuit_breaker.is_open()


# ---------------------------------------------------------------------------
# Wildcard resource fallback
# ---------------------------------------------------------------------------


class TestWildcardResourceFallback:
    """'*' resource acts as catch-all when a specific resource is not registered."""

    def test_wildcard_allows_listed_action_on_unknown_resource(self, tmp_path: Path) -> None:
        p = _write_manifest(tmp_path, _BASE_YAML)
        client = _make_client()
        client.load_manifest_from_yaml(p)

        payload = _evaluate(client, agent_id="agent-test", resource="mystery", action="read")
        assert payload.allowed is True

    def test_wildcard_blocks_unlisted_action_on_unknown_resource(self, tmp_path: Path) -> None:
        p = _write_manifest(tmp_path, _BASE_YAML)
        client = _make_client()
        client.load_manifest_from_yaml(p)

        payload = _evaluate(client, agent_id="agent-test", resource="mystery", action="admin")
        assert payload.allowed is False

    def test_explicit_resource_takes_precedence_over_wildcard(self, tmp_path: Path) -> None:
        p = _write_manifest(tmp_path, _YAML_WITH_RESOURCE_ACTIONS)
        client = _make_client()
        client.load_manifest_from_yaml(p)

        # "files" resource only has read and list, not "stream"
        payload = _evaluate(
            client, agent_id="agent-res", resource="files", action="stream"
        )
        assert payload.allowed is False

    def test_no_wildcard_without_yaml_loader(self) -> None:
        """register_agent() without '*' entry preserves existing blocking behaviour."""
        client = _make_client()
        client.register_agent(
            agent_id="plain-agent",
            resource_actions={"db": ["read"]},
        )
        payload = _evaluate(client, agent_id="plain-agent", resource="other", action="read")
        assert payload.allowed is False
        assert "not permitted to access resource" in payload.reason
