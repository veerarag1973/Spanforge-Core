"""Phase 0 contract tests for GA runtime governance payloads and policy schema."""

from __future__ import annotations

import pytest

from spanforge.namespaces.runtime_governance import (
    ExplanationFactor,
    ExplanationPayload,
    GroundingClaim,
    GroundingPayload,
    LineagePayload,
    RBACDecisionPayload,
    ScopeDecisionPayload,
)
from spanforge.runtime_policy import RuntimePolicyBundle, RuntimePolicyRule


class TestExplanationContracts:
    def test_explanation_factor_round_trip(self) -> None:
        factor = ExplanationFactor(
            factor_name="grounding_score",
            weight=0.7,
            contribution=0.5,
            evidence="retrieval confidence above threshold",
            confidence=0.92,
        )
        assert ExplanationFactor.from_dict(factor.to_dict()) == factor

    def test_explanation_payload_round_trip(self) -> None:
        payload = ExplanationPayload(
            explanation_id="exp-001",
            trace_id="trace-001",
            decision_id="decision-001",
            agent_id="agent-001",
            summary="The request was allowed because grounding passed the reliability gate.",
            policy_action="allow+log",
            generated_at="2026-04-22T10:00:00Z",
            factors=[
                ExplanationFactor(
                    factor_name="grounding_score",
                    weight=0.7,
                    contribution=0.5,
                    evidence="retrieval confidence above threshold",
                )
            ],
            model_id="gpt-4o",
            confidence=0.88,
            policy_id="policy-ga-v1",
        )
        restored = ExplanationPayload.from_dict(payload.to_dict())
        assert restored.policy_action == "allow+log"
        assert restored.factors[0].factor_name == "grounding_score"

    def test_explanation_payload_rejects_bad_policy_action(self) -> None:
        with pytest.raises(ValueError, match="policy_action"):
            ExplanationPayload(
                explanation_id="exp-001",
                trace_id="trace-001",
                decision_id="decision-001",
                agent_id="agent-001",
                summary="bad",
                policy_action="escalate",
                generated_at="2026-04-22T10:00:00Z",
            )


class TestGroundingContracts:
    def test_grounding_payload_round_trip(self) -> None:
        payload = GroundingPayload(
            grounding_id="gr-001",
            trace_id="trace-001",
            decision_id="decision-001",
            session_id="session-001",
            status="grounded",
            average_score=0.91,
            threshold=0.75,
            policy_action="allow",
            assessed_at="2026-04-22T10:00:00Z",
            claims=[
                GroundingClaim(
                    claim_id="claim-001",
                    claim_text="Paris is the capital of France.",
                    grounded=True,
                    score=0.97,
                    source_ids=["doc-1"],
                )
            ],
        )
        restored = GroundingPayload.from_dict(payload.to_dict())
        assert restored.status == "grounded"
        assert restored.claims[0].source_ids == ["doc-1"]

    def test_grounding_claim_rejects_score_out_of_range(self) -> None:
        with pytest.raises(ValueError, match="score"):
            GroundingClaim(
                claim_id="claim-001",
                claim_text="x",
                grounded=False,
                score=1.1,
            )


class TestLineageContracts:
    def test_lineage_payload_round_trip(self) -> None:
        payload = LineagePayload(
            lineage_id="lin-001",
            trace_id="trace-001",
            decision_id="decision-001",
            subject_type="retrieval_context",
            subject_id="ctx-001",
            operation="merge_context",
            recorded_at="2026-04-22T10:00:00Z",
            input_refs=["doc-1", "doc-2"],
            output_refs=["ctx-001"],
            parent_lineage_ids=["lin-parent"],
        )
        assert LineagePayload.from_dict(payload.to_dict()) == payload


class TestScopeContracts:
    def test_scope_payload_round_trip(self) -> None:
        payload = ScopeDecisionPayload(
            scope_id="scope-001",
            trace_id="trace-001",
            agent_id="agent-001",
            resource="ticket:123",
            action_name="write_comment",
            allowed=False,
            outcome="human_review",
            reason="The agent lacks write capability for this queue.",
            checked_at="2026-04-22T10:00:00Z",
            capability="support.comment.write",
            policy_id="policy-ga-v1",
            policy_action="human_review",
        )
        restored = ScopeDecisionPayload.from_dict(payload.to_dict())
        assert restored.outcome == "human_review"
        assert restored.policy_action == "human_review"

    def test_scope_payload_rejects_invalid_outcome(self) -> None:
        with pytest.raises(ValueError, match="outcome"):
            ScopeDecisionPayload(
                scope_id="scope-001",
                trace_id="trace-001",
                agent_id="agent-001",
                resource="ticket:123",
                action_name="write_comment",
                allowed=False,
                outcome="deny",
                reason="x",
                checked_at="2026-04-22T10:00:00Z",
            )


class TestRBACContracts:
    def test_rbac_payload_round_trip(self) -> None:
        payload = RBACDecisionPayload(
            check_id="rbac-001",
            trace_id="trace-001",
            actor_id="user-001",
            resource="customer_record:42",
            action_name="read_sensitive_fields",
            allowed=False,
            outcome="block",
            reason="The actor does not hold the required reviewer role.",
            checked_at="2026-04-22T10:00:00Z",
            required_roles=["reviewer"],
            effective_roles=["analyst"],
            policy_id="policy-ga-v1",
            policy_action="block",
        )
        restored = RBACDecisionPayload.from_dict(payload.to_dict())
        assert restored.required_roles == ["reviewer"]
        assert restored.policy_action == "block"


class TestRuntimePolicyContracts:
    def test_runtime_policy_rule_round_trip(self) -> None:
        rule = RuntimePolicyRule(
            rule_id="rule-001",
            service="sf_rag",
            control="grounding_threshold",
            action="block",
            threshold=0.75,
            rationale="Block ungrounded answers in production.",
        )
        assert RuntimePolicyRule.from_dict(rule.to_dict()) == rule

    def test_runtime_policy_bundle_round_trip(self) -> None:
        bundle = RuntimePolicyBundle(
            policy_id="policy-ga",
            version="v1",
            environment="prod",
            owner="platform-security",
            effective_at="2026-04-22T10:00:00Z",
            rules=[
                RuntimePolicyRule(
                    rule_id="rule-001",
                    service="sf_rag",
                    control="grounding_threshold",
                    action="block",
                    threshold=0.75,
                )
            ],
            rationale="GA baseline runtime control policy.",
        )
        restored = RuntimePolicyBundle.from_dict(bundle.to_dict())
        assert restored.environment == "prod"
        assert restored.rules[0].service == "sf_rag"

    def test_runtime_policy_bundle_rejects_bad_environment(self) -> None:
        with pytest.raises(ValueError, match="environment"):
            RuntimePolicyBundle(
                policy_id="policy-ga",
                version="v1",
                environment="qa",
                owner="platform-security",
                effective_at="2026-04-22T10:00:00Z",
            )
