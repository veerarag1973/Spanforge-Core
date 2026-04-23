"""Tests for the Phase 4 operator workflow client."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from spanforge.namespaces.runtime_governance import GroundingClaim
from spanforge.runtime_policy import RuntimePolicyBundle, RuntimePolicyRule
from spanforge.sdk._base import SFClientConfig
from spanforge.sdk.audit import SFAuditClient
from spanforge.sdk.explain import SFExplainClient
from spanforge.sdk.lineage import SFLineageClient
from spanforge.sdk.operator import OperatorEvidencePackage, OperatorWorkflowView, SFOperatorClient
from spanforge.sdk.policy import SFPolicyClient
from spanforge.sdk.rag import SFRAGClient
from spanforge.sdk.rbac import SFRBACClient
from spanforge.sdk.scope import SFScopeClient


def _bundle() -> RuntimePolicyBundle:
    return RuntimePolicyBundle(
        policy_id="policy-ga",
        version="v1",
        environment="prod",
        owner="platform-security",
        effective_at="2026-04-23T08:00:00Z",
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
                threshold=0.8,
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


def _seed_trace(trace_id: str) -> dict[str, object]:
    config = SFClientConfig(project_id="test-proj", signing_key="test-signing-key")
    audit = SFAuditClient(config)
    policy = SFPolicyClient(config)
    explain = SFExplainClient(config)
    rag = SFRAGClient(config)
    rbac = SFRBACClient(config)
    scope = SFScopeClient(config)
    lineage = SFLineageClient(config)
    operator = SFOperatorClient(config)

    policy.load_bundle(_bundle())
    policy.activate(
        environment="prod",
        policy_id="policy-ga",
        version="v1",
        activated_at="2026-04-23T08:05:00Z",
    )
    scope.register_agent(
        agent_id="agent-001",
        capabilities=["repo.read"],
        resource_actions={"repo.file": ["read"]},
    )
    rbac.register_actor(actor_id="user-001", roles=["operator"])
    session_id = rag.trace_query("What changed?", top_k=2, retriever_name="docs-index")

    with patch("spanforge.sdk.sf_audit", audit):
        scope.evaluate_with_policy(
            environment="prod",
            trace_id=trace_id,
            agent_id="agent-001",
            resource="repo.file",
            action_name="write",
            checked_at="2026-04-23T08:10:00Z",
            policy_client=policy,
        )
        rbac.authorize_with_policy(
            environment="prod",
            trace_id=trace_id,
            actor_id="user-001",
            resource="prod.db",
            action_name="delete",
            checked_at="2026-04-23T08:11:00Z",
            required_roles=["admin"],
            policy_client=policy,
        )
        rag.assess_grounding_with_policy(
            environment="prod",
            trace_id=trace_id,
            decision_id="decision-001",
            session_id=session_id,
            assessed_at="2026-04-23T08:12:00Z",
            claims=[
                GroundingClaim(
                    claim_id="claim-001",
                    claim_text="The source is weak.",
                    grounded=False,
                    score=0.4,
                    source_ids=[],
                )
            ],
            policy_client=policy,
        )
        explain.generate_with_policy(
            environment="prod",
            trace_id=trace_id,
            agent_id="agent-001",
            decision_id="decision-001",
            summary="The request was denied because the actor lacked admin rights.",
            generated_at="2026-04-23T08:13:00Z",
            policy_client=policy,
        )
        lineage.record_with_policy(
            environment="prod",
            trace_id=trace_id,
            decision_id="decision-001",
            subject_type="document",
            subject_id="doc-123",
            operation="delete_attempt",
            recorded_at="2026-04-23T08:14:00Z",
            policy_client=policy,
        )
    return {
        "audit": audit,
        "policy": policy,
        "explain": explain,
        "rag": rag,
        "rbac": rbac,
        "scope": scope,
        "lineage": lineage,
        "operator": operator,
    }


class TestSFOperatorClient:
    def test_inspect_trace_aggregates_phase4_workflow(self) -> None:
        trace_id = "trace-op-001"
        services = _seed_trace(trace_id)

        with patch("spanforge.sdk.sf_audit", services["audit"]), patch(
            "spanforge.sdk.sf_policy", services["policy"]
        ), patch("spanforge.sdk.sf_explain", services["explain"]), patch(
            "spanforge.sdk.sf_rag", services["rag"]
        ), patch("spanforge.sdk.sf_rbac", services["rbac"]), patch(
            "spanforge.sdk.sf_scope", services["scope"]
        ), patch("spanforge.sdk.sf_lineage", services["lineage"]):
            workflow = services["operator"].inspect_trace(trace_id)  # type: ignore[union-attr]

        assert isinstance(workflow, OperatorWorkflowView)
        assert workflow.trace_id == trace_id
        assert workflow.outcome == "block"
        assert len(workflow.policy_decisions) == 5
        assert len(workflow.scope_decisions) == 1
        assert len(workflow.rbac_decisions) == 1
        assert len(workflow.grounding_results) == 1
        assert len(workflow.explanations) == 1
        assert len(workflow.lineage_records) == 1
        assert len(workflow.audit_records) >= 5
        assert "missing required roles" in workflow.summary
        assert "Grounding ungrounded" in workflow.summary

    def test_export_package_writes_signed_json(self, tmp_path: Path) -> None:
        trace_id = "trace-op-002"
        services = _seed_trace(trace_id)
        out_file = tmp_path / "operator-package.json"

        with patch("spanforge.sdk.sf_audit", services["audit"]), patch(
            "spanforge.sdk.sf_policy", services["policy"]
        ), patch("spanforge.sdk.sf_explain", services["explain"]), patch(
            "spanforge.sdk.sf_rag", services["rag"]
        ), patch("spanforge.sdk.sf_rbac", services["rbac"]), patch(
            "spanforge.sdk.sf_scope", services["scope"]
        ), patch("spanforge.sdk.sf_lineage", services["lineage"]):
            package = services["operator"].export_package(  # type: ignore[union-attr]
                trace_id,
                output_path=str(out_file),
            )

        assert isinstance(package, OperatorEvidencePackage)
        assert package.trace_id == trace_id
        assert package.chain_verification["valid"] is True
        assert package.output_path == str(out_file)
        assert out_file.exists()
        payload = json.loads(out_file.read_text(encoding="utf-8"))
        assert payload["trace_id"] == trace_id
        assert payload["workflow"]["outcome"] == "block"
        assert payload["signature"].startswith("hmac-sha256:")
