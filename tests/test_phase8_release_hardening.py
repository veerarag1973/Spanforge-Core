"""Phase 8 release-hardening tests for the GA runtime-governance spine."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from spanforge.namespaces.runtime_governance import GroundingClaim
from spanforge.runtime_policy import RuntimePolicyBundle, RuntimePolicyRule
from spanforge.sdk._base import SFClientConfig
from spanforge.sdk.audit import SFAuditClient
from spanforge.sdk.enterprise import SFEnterpriseClient
from spanforge.sdk.explain import SFExplainClient
from spanforge.sdk.lineage import SFLineageClient
from spanforge.sdk.operator import SFOperatorClient
from spanforge.sdk.policy import SFPolicyClient
from spanforge.sdk.rag import SFRAGClient
from spanforge.sdk.rbac import SFRBACClient
from spanforge.sdk.scope import SFScopeClient


def _config() -> SFClientConfig:
    return SFClientConfig(project_id="phase8-proj", signing_key="phase8-signing-key")


def _bundle(*, version: str = "v1", action: str = "block", threshold: float = 0.75) -> RuntimePolicyBundle:
    return RuntimePolicyBundle(
        policy_id="policy-ga",
        version=version,
        environment="prod",
        owner="platform-security",
        effective_at="2026-04-23T12:00:00Z",
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
                action=action,
                threshold=threshold,
                rationale="Harden production against weak grounding.",
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


def _seed_trace(trace_id: str, out_dir: Path) -> tuple[dict[str, object], Path]:
    config = _config()
    audit = SFAuditClient(config)
    policy = SFPolicyClient(config)
    explain = SFExplainClient(config)
    rag = SFRAGClient(config)
    rbac = SFRBACClient(config)
    scope = SFScopeClient(config)
    lineage = SFLineageClient(config)
    operator = SFOperatorClient(config)
    enterprise = SFEnterpriseClient(config)

    policy.load_bundle(_bundle())
    policy.activate(
        environment="prod",
        policy_id="policy-ga",
        version="v1",
        activated_at="2026-04-23T12:01:00Z",
    )
    scope.register_agent(
        agent_id="agent-001",
        capabilities=["repo.read"],
        resource_actions={"repo.file": ["read"]},
    )
    rbac.register_actor(actor_id="user-001", roles=["operator"])
    enterprise.register_tenant(project_id="phase8-proj", org_id="org-001", data_residency="us")
    enterprise.configure_retention_export(
        retention_days=365,
        export_formats=["json"],
        require_encryption_for_export=False,
    )
    session_id = rag.trace_query("What changed?", top_k=2, retriever_name="docs-index")

    with patch("spanforge.sdk.sf_audit", audit):
        scope.evaluate_with_policy(
            environment="prod",
            trace_id=trace_id,
            agent_id="agent-001",
            resource="repo.file",
            action_name="write",
            checked_at="2026-04-23T12:02:00Z",
            policy_client=policy,
        )
        rbac.authorize_with_policy(
            environment="prod",
            trace_id=trace_id,
            actor_id="user-001",
            resource="prod.db",
            action_name="delete",
            checked_at="2026-04-23T12:03:00Z",
            required_roles=["admin"],
            policy_client=policy,
        )
        rag.assess_grounding_with_policy(
            environment="prod",
            trace_id=trace_id,
            decision_id="decision-001",
            session_id=session_id,
            assessed_at="2026-04-23T12:04:00Z",
            claims=[
                GroundingClaim(
                    claim_id="claim-001",
                    claim_text="Weak claim",
                    grounded=False,
                    score=0.35,
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
            summary="Denied because the actor lacked admin rights and grounding was weak.",
            generated_at="2026-04-23T12:05:00Z",
            policy_client=policy,
        )
        lineage.record_with_policy(
            environment="prod",
            trace_id=trace_id,
            decision_id="decision-001",
            subject_type="document",
            subject_id="doc-001",
            operation="delete_attempt",
            recorded_at="2026-04-23T12:06:00Z",
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
        "enterprise": enterprise,
    }, out_dir / "enterprise-package.json"


class TestPhase8ReleaseHardening:
    def test_end_to_end_trace_to_enterprise_evidence_package(self) -> None:
        trace_id = "trace-phase8-001"
        output_path = Path("tests") / "phase8-enterprise-package.json"
        output_path.unlink(missing_ok=True)
        services, _ = _seed_trace(trace_id, output_path.parent)

        try:
            with patch("spanforge.sdk.sf_audit", services["audit"]), patch(
                "spanforge.sdk.sf_policy", services["policy"]
            ), patch("spanforge.sdk.sf_explain", services["explain"]), patch(
                "spanforge.sdk.sf_rag", services["rag"]
            ), patch("spanforge.sdk.sf_rbac", services["rbac"]), patch(
                "spanforge.sdk.sf_scope", services["scope"]
            ), patch("spanforge.sdk.sf_lineage", services["lineage"]), patch(
                "spanforge.sdk.sf_operator", services["operator"]
            ):
                package = services["enterprise"].generate_evidence_package(  # type: ignore[union-attr]
                    trace_id,
                    output_path=str(output_path),
                )

            assert package.trace_id == trace_id
            assert package.operator_package["chain_verification"]["valid"] is True
            assert package.enterprise_status.status == "ok"
            assert output_path.exists()
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            assert payload["operator_package"]["workflow"]["outcome"] == "block"
            assert payload["signature"].startswith("hmac-sha256:")
        finally:
            output_path.unlink(missing_ok=True)

    @pytest.mark.parametrize(
        ("action", "observed_value", "expected_action", "expected_allowed"),
        [
            ("allow", 0.20, "allow", True),
            ("allow+log", 0.20, "allow+log", True),
            ("redact", 0.20, "redact", False),
            ("block", 0.20, "block", False),
            ("human_review", 0.20, "human_review", False),
        ],
    )
    def test_policy_actions_are_enforceable(
        self,
        action: str,
        observed_value: float,
        expected_action: str,
        expected_allowed: bool,
    ) -> None:
        client = SFPolicyClient(_config())
        client.load_bundle(_bundle(action=action, threshold=0.75))

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            client.activate(
                environment="prod",
                policy_id="policy-ga",
                version="v1",
                activated_at="2026-04-23T12:10:00Z",
            )
            decision = client.evaluate(
                environment="prod",
                trace_id="trace-actions",
                service="sf_rag",
                control="grounding_threshold",
                evaluated_at="2026-04-23T12:11:00Z",
                observed_value=observed_value,
            )

        assert decision.action == expected_action
        assert decision.allowed is expected_allowed

    def test_runtime_policy_from_dict_rejects_incomplete_payload(self) -> None:
        with pytest.raises(ValueError, match="missing required fields: effective_at"):
            RuntimePolicyBundle.from_dict(
                {
                    "policy_id": "policy-ga",
                    "version": "v1",
                    "environment": "prod",
                    "owner": "platform-security",
                }
            )

        with pytest.raises(ValueError, match="missing required fields: action"):
            RuntimePolicyRule.from_dict(
                {
                    "rule_id": "rule-001",
                    "service": "sf_rag",
                    "control": "grounding_threshold",
                }
            )

    def test_replay_rejects_incomplete_event_payloads(self) -> None:
        client = SFPolicyClient(_config())

        with pytest.raises(ValueError, match="missing required fields: trace_id"):
            client.replay(
                environment="prod",
                replayed_at="2026-04-23T12:12:00Z",
                events=[
                    {
                        "environment": "prod",
                        "service": "sf_rag",
                        "control": "grounding_threshold",
                    }
                ],
                candidate_bundle=_bundle(),
            )

    def test_compare_rejects_bad_historical_event_environment(self) -> None:
        client = SFPolicyClient(_config())

        with pytest.raises(ValueError, match="environment must match requested environment"):
            client.compare_policies(
                environment="prod",
                compared_at="2026-04-23T12:13:00Z",
                events=[
                    {
                        "trace_id": "trace-001",
                        "environment": "staging",
                        "service": "sf_rag",
                        "control": "grounding_threshold",
                        "observed_value": 0.4,
                    }
                ],
                baseline_bundle=_bundle(version="v1"),
                candidate_bundle=_bundle(version="v2", action="human_review"),
            )

    def test_rag_local_emit_survives_upstream_outage(self) -> None:
        client = SFRAGClient(_config())

        with patch("spanforge.sdk.observe.SFObserveClient.emit_span", side_effect=TimeoutError("upstream timeout")):
            session_id = client.trace_query("hello", top_k=1, retriever_name="docs-index")
            client.trace_generation(
                session_id,
                model="gpt-4o",
                chunk_ids_used=["chunk-1"],
                prompt_tokens=10,
                output_tokens=5,
                grounding_score=0.9,
                status="timeout",
                error_message="upstream timeout",
            )

        snapshot = client.get_session(session_id)
        assert snapshot is not None
        assert snapshot.status == "error"
