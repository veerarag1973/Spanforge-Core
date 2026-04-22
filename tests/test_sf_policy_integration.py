"""Integration tests for policy-aware Phase 1 service wrappers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from spanforge.namespaces.runtime_governance import GroundingClaim
from spanforge.runtime_policy import RuntimePolicyBundle, RuntimePolicyRule
from spanforge.sdk._base import SFClientConfig
from spanforge.sdk.explain import SFExplainClient
from spanforge.sdk.lineage import SFLineageClient
from spanforge.sdk.policy import SFPolicyClient
from spanforge.sdk.rag import SFRAGClient
from spanforge.sdk.rbac import SFRBACClient
from spanforge.sdk.scope import SFScopeClient
from spanforge.sdk._types import SecretStr


def _policy_client() -> SFPolicyClient:
    client = SFPolicyClient(SFClientConfig(project_id="test-proj", api_key=SecretStr("test")))
    client.load_bundle(
        RuntimePolicyBundle(
            policy_id="policy-ga",
            version="v1",
            environment="prod",
            owner="platform-security",
            effective_at="2026-04-22T14:00:00Z",
            rules=[
                RuntimePolicyRule(
                    rule_id="scope-enforcement",
                    service="sf_scope",
                    control="capability_enforcement",
                    action="human_review",
                    threshold=1.0,
                    metadata={"comparator": "lt"},
                ),
                RuntimePolicyRule(
                    rule_id="rbac-enforcement",
                    service="sf_rbac",
                    control="role_enforcement",
                    action="block",
                    threshold=1.0,
                    metadata={"comparator": "lt"},
                ),
                RuntimePolicyRule(
                    rule_id="rag-grounding",
                    service="sf_rag",
                    control="grounding_threshold",
                    action="block",
                    threshold=0.75,
                    metadata={"comparator": "lt"},
                ),
                RuntimePolicyRule(
                    rule_id="explain-generation",
                    service="sf_explain",
                    control="explanation_generation",
                    action="allow+log",
                ),
                RuntimePolicyRule(
                    rule_id="lineage-capture",
                    service="sf_lineage",
                    control="lineage_capture",
                    action="allow+log",
                ),
            ],
        )
    )
    client.activate(
        environment="prod",
        policy_id="policy-ga",
        version="v1",
        activated_at="2026-04-22T14:05:00Z",
    )
    return client


class TestPolicyAwareServices:
    def test_scope_wrapper_uses_policy_action(self) -> None:
        scope = SFScopeClient(SFClientConfig(project_id="test-proj"))
        scope.register_agent(
            agent_id="agent-001",
            capabilities=["tool.read"],
            resource_actions={"repo.file": ["read"]},
        )
        policy = _policy_client()

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = scope.evaluate_with_policy(
                environment="prod",
                trace_id="trace-001",
                agent_id="agent-001",
                resource="repo.file",
                action_name="write",
                checked_at="2026-04-22T14:10:00Z",
                policy_client=policy,
            )

        assert payload.policy_action == "human_review"
        assert payload.outcome == "human_review"

    def test_rbac_wrapper_uses_policy_action(self) -> None:
        rbac = SFRBACClient(SFClientConfig(project_id="test-proj"))
        rbac.register_actor(actor_id="user-001", roles=["operator"])
        policy = _policy_client()

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = rbac.authorize_with_policy(
                environment="prod",
                trace_id="trace-002",
                actor_id="user-001",
                resource="prod.db",
                action_name="delete",
                checked_at="2026-04-22T14:10:00Z",
                required_roles=["admin"],
                policy_client=policy,
            )

        assert payload.policy_action == "block"
        assert payload.outcome == "block"

    def test_rag_wrapper_uses_policy_threshold(self) -> None:
        rag = SFRAGClient(SFClientConfig(project_id="test-proj", api_key=SecretStr("test")))
        session_id = rag.trace_query("What is AI?", top_k=2, retriever_name="chroma-main")
        policy = _policy_client()

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = rag.assess_grounding_with_policy(
                environment="prod",
                trace_id="trace-003",
                decision_id="decision-003",
                session_id=session_id,
                assessed_at="2026-04-22T14:10:00Z",
                claims=[
                    GroundingClaim(
                        claim_id="claim-001",
                        claim_text="Weak claim",
                        grounded=False,
                        score=0.4,
                        source_ids=[],
                    )
                ],
                policy_client=policy,
            )

        assert payload.threshold == 0.75
        assert payload.policy_action == "block"
        assert payload.status == "ungrounded"

    def test_explain_wrapper_uses_policy_decision(self) -> None:
        explain = SFExplainClient(SFClientConfig(project_id="test-proj"))
        policy = _policy_client()

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = explain.generate_with_policy(
                environment="prod",
                trace_id="trace-004",
                agent_id="agent-001",
                decision_id="decision-004",
                summary="The request passed.",
                generated_at="2026-04-22T14:10:00Z",
                policy_client=policy,
            )

        assert payload.policy_action == "allow+log"
        assert payload.policy_id == "policy-ga"

    def test_lineage_wrapper_attaches_policy_metadata(self) -> None:
        lineage = SFLineageClient(SFClientConfig(project_id="test-proj"))
        policy = _policy_client()

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = lineage.record_with_policy(
                environment="prod",
                trace_id="trace-005",
                decision_id="decision-005",
                subject_type="document",
                subject_id="doc-005",
                operation="index",
                recorded_at="2026-04-22T14:10:00Z",
                policy_client=policy,
            )

        assert payload.metadata["policy_id"] == "policy-ga"
        assert payload.metadata["policy_action"] == "allow+log"
