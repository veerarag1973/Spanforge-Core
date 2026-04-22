"""Tests for spanforge.sdk.policy - Phase 2 runtime policy engine."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from spanforge.runtime_policy import RuntimePolicyBundle, RuntimePolicyRule
from spanforge.sdk._base import SFClientConfig
from spanforge.sdk.policy import RuntimePolicyStatusInfo, SFPolicyClient


def _make_client() -> SFPolicyClient:
    return SFPolicyClient(SFClientConfig(project_id="test-proj"))


def _bundle(environment: str = "prod", version: str = "v1") -> RuntimePolicyBundle:
    return RuntimePolicyBundle(
        policy_id="policy-ga",
        version=version,
        environment=environment,
        owner="platform-security",
        effective_at="2026-04-22T13:00:00Z",
        rules=[
            RuntimePolicyRule(
                rule_id="rag-threshold",
                service="sf_rag",
                control="grounding_threshold",
                action="block",
                threshold=0.75,
                rationale="Block ungrounded answers in production.",
                metadata={"comparator": "lt"},
            ),
            RuntimePolicyRule(
                rule_id="scope-enforcement",
                service="sf_scope",
                control="capability_enforcement",
                action="human_review",
                threshold=1.0,
                metadata={"comparator": "lt"},
            ),
        ],
    )


class TestSFPolicyClient:
    def test_load_and_activate_bundle(self) -> None:
        client = _make_client()
        bundle = _bundle()

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            loaded = client.load_bundle(bundle)
            active = client.activate(
                environment="prod",
                policy_id="policy-ga",
                version="v1",
                activated_at="2026-04-22T13:05:00Z",
            )

        assert loaded == bundle
        assert active == bundle
        assert client.get_active_bundle("prod") == bundle

    def test_evaluate_returns_block_for_triggered_threshold_rule(self) -> None:
        client = _make_client()
        client.load_bundle(_bundle())

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            client.activate(
                environment="prod",
                policy_id="policy-ga",
                version="v1",
                activated_at="2026-04-22T13:05:00Z",
            )
            decision = client.evaluate(
                environment="prod",
                trace_id="trace-001",
                service="sf_rag",
                control="grounding_threshold",
                evaluated_at="2026-04-22T13:10:00Z",
                observed_value=0.42,
            )

        assert decision.action == "block"
        assert decision.allowed is False
        assert client.get_decision(decision.decision_id) == decision
        assert client.list_decisions_for_trace("trace-001") == [decision]

    def test_evaluate_returns_allow_when_rule_does_not_trigger(self) -> None:
        client = _make_client()
        client.load_bundle(_bundle())

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            client.activate(
                environment="prod",
                policy_id="policy-ga",
                version="v1",
                activated_at="2026-04-22T13:05:00Z",
            )
            decision = client.evaluate(
                environment="prod",
                trace_id="trace-002",
                service="sf_rag",
                control="grounding_threshold",
                evaluated_at="2026-04-22T13:10:00Z",
                observed_value=0.95,
            )

        assert decision.action == "allow"
        assert decision.allowed is True

    def test_promote_copies_bundle_to_new_environment(self) -> None:
        client = _make_client()
        client.load_bundle(_bundle(environment="staging", version="v1"))

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            promoted = client.promote(
                policy_id="policy-ga",
                from_environment="staging",
                to_environment="prod",
                version="v1",
                new_version="v2",
                owner="platform-security",
                effective_at="2026-04-22T13:20:00Z",
            )

        assert promoted.environment == "prod"
        assert promoted.version == "v2"
        assert client.list_versions(environment="prod", policy_id="policy-ga") == [promoted]

    def test_deactivate_clears_active_bundle(self) -> None:
        client = _make_client()
        client.load_bundle(_bundle())

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            client.activate(
                environment="prod",
                policy_id="policy-ga",
                version="v1",
                activated_at="2026-04-22T13:05:00Z",
            )
            client.deactivate(environment="prod", deactivated_at="2026-04-22T13:15:00Z")

        assert client.get_active_bundle("prod") is None

    def test_status_reflects_loaded_bundles_and_decisions(self) -> None:
        client = _make_client()
        client.load_bundle(_bundle())

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            client.activate(
                environment="prod",
                policy_id="policy-ga",
                version="v1",
                activated_at="2026-04-22T13:05:00Z",
            )
            client.evaluate(
                environment="prod",
                trace_id="trace-003",
                service="sf_scope",
                control="capability_enforcement",
                evaluated_at="2026-04-22T13:10:00Z",
                observed_value=0.0,
            )

        status = client.get_status()
        assert isinstance(status, RuntimePolicyStatusInfo)
        assert status.loaded_bundles == 1
        assert status.active_environments == 1
        assert status.decisions_emitted == 1
