"""Tests for spanforge.sdk.policy - Phase 3 replay and calibration flows."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from spanforge.runtime_policy import RuntimePolicyBundle, RuntimePolicyRule
from spanforge.sdk._base import SFClientConfig
from spanforge.sdk.policy import (
    RuntimePolicyComparisonResult,
    RuntimePolicyReplayResult,
    RuntimePolicyReviewRecord,
    RuntimePolicySimulationResult,
    RuntimePolicyStatusInfo,
    SFPolicyClient,
)


def _make_client() -> SFPolicyClient:
    return SFPolicyClient(SFClientConfig(project_id="test-proj"))


def _bundle(
    *,
    policy_id: str = "policy-ga",
    version: str = "v1",
    threshold: float = 0.75,
    action: str = "block",
) -> RuntimePolicyBundle:
    return RuntimePolicyBundle(
        policy_id=policy_id,
        version=version,
        environment="prod",
        owner="platform-security",
        effective_at="2026-04-22T15:00:00Z",
        rules=[
            RuntimePolicyRule(
                rule_id="rag-threshold",
                service="sf_rag",
                control="grounding_threshold",
                action=action,
                threshold=threshold,
                rationale="Protect production from weak grounding.",
                metadata={"comparator": "lt"},
            ),
        ],
    )


class TestSFPolicyPhase3:
    def test_simulate_candidate_policy_without_mutating_live_bundle(self) -> None:
        client = _make_client()
        live_bundle = _bundle(version="v1", threshold=0.75, action="block")
        candidate_bundle = _bundle(policy_id="policy-candidate", version="v2", threshold=0.9, action="human_review")
        client.load_bundle(live_bundle)

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            client.activate(
                environment="prod",
                policy_id="policy-ga",
                version="v1",
                activated_at="2026-04-22T15:05:00Z",
            )
            production = client.evaluate(
                environment="prod",
                trace_id="trace-sim-001",
                service="sf_rag",
                control="grounding_threshold",
                evaluated_at="2026-04-22T15:10:00Z",
                observed_value=0.82,
            )
            result = client.simulate(
                environment="prod",
                trace_id="trace-sim-001",
                service="sf_rag",
                control="grounding_threshold",
                simulated_at="2026-04-22T15:11:00Z",
                candidate_bundle=candidate_bundle,
                observed_value=0.82,
                production_decision=production,
            )

        assert isinstance(result, RuntimePolicySimulationResult)
        assert result.candidate_decision.action == "human_review"
        assert result.changed is True
        assert client.get_active_bundle("prod") == live_bundle
        assert client.list_simulations_for_trace("trace-sim-001") == [result]

    def test_replay_summarizes_candidate_outcomes(self) -> None:
        client = _make_client()
        candidate_bundle = _bundle(policy_id="policy-candidate", version="v2", threshold=0.8, action="block")

        events = [
            {
                "trace_id": "trace-replay-001",
                "environment": "prod",
                "service": "sf_rag",
                "control": "grounding_threshold",
                "observed_value": 0.55,
                "production_action": "allow",
                "production_policy_id": "policy-ga",
                "production_policy_version": "v1",
                "evaluated_at": "2026-04-22T15:12:00Z",
            },
            {
                "trace_id": "trace-replay-002",
                "environment": "prod",
                "service": "sf_rag",
                "control": "grounding_threshold",
                "observed_value": 0.92,
                "production_action": "allow",
                "production_policy_id": "policy-ga",
                "production_policy_version": "v1",
                "evaluated_at": "2026-04-22T15:13:00Z",
            },
        ]

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            result = client.replay(
                environment="prod",
                replayed_at="2026-04-22T15:14:00Z",
                events=events,
                candidate_bundle=candidate_bundle,
            )

        assert isinstance(result, RuntimePolicyReplayResult)
        assert result.event_count == 2
        assert result.changed_count == 1
        assert result.blocked_count == 1
        assert client.get_replay(result.replay_id) == result

    def test_compare_policies_counts_action_changes(self) -> None:
        client = _make_client()
        baseline = _bundle(policy_id="policy-ga", version="v1", threshold=0.7, action="allow+log")
        candidate = _bundle(policy_id="policy-ga", version="v2", threshold=0.9, action="block")
        events = [
            {
                "trace_id": "trace-compare-001",
                "environment": "prod",
                "service": "sf_rag",
                "control": "grounding_threshold",
                "observed_value": 0.8,
            }
        ]

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            result = client.compare_policies(
                environment="prod",
                compared_at="2026-04-22T15:15:00Z",
                events=events,
                baseline_bundle=baseline,
                candidate_bundle=candidate,
            )

        assert isinstance(result, RuntimePolicyComparisonResult)
        assert result.changed_count == 1
        assert result.action_changes == {"allow->block": 1}

    def test_review_loop_supports_threshold_suggestion(self) -> None:
        client = _make_client()
        live_bundle = _bundle(version="v1", threshold=0.75, action="block")
        client.load_bundle(live_bundle)

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            client.activate(
                environment="prod",
                policy_id="policy-ga",
                version="v1",
                activated_at="2026-04-22T15:05:00Z",
            )
            decision = client.evaluate(
                environment="prod",
                trace_id="trace-review-001",
                service="sf_rag",
                control="grounding_threshold",
                evaluated_at="2026-04-22T15:16:00Z",
                observed_value=0.72,
            )
            review = client.record_review(
                decision_id=decision.decision_id,
                trace_id="trace-review-001",
                classification="false_positive",
                recorded_at="2026-04-22T15:17:00Z",
                notes="This answer was acceptable and should not have been blocked.",
            )

        assert isinstance(review, RuntimePolicyReviewRecord)
        assert client.list_reviews_for_trace("trace-review-001") == [review]
        assert client.suggest_threshold(
            service="sf_rag",
            control="grounding_threshold",
            classification="false_positive",
        ) == 0.72

    def test_status_includes_phase3_counters(self) -> None:
        client = _make_client()
        candidate_bundle = _bundle(policy_id="policy-candidate", version="v2", threshold=0.8, action="block")

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            client.replay(
                environment="prod",
                replayed_at="2026-04-22T15:18:00Z",
                events=[
                    {
                        "trace_id": "trace-status-001",
                        "environment": "prod",
                        "service": "sf_rag",
                        "control": "grounding_threshold",
                        "observed_value": 0.5,
                        "production_action": "allow",
                        "production_policy_id": "policy-ga",
                        "production_policy_version": "v1",
                        "evaluated_at": "2026-04-22T15:18:00Z",
                    }
                ],
                candidate_bundle=candidate_bundle,
            )

        status = client.get_status()
        assert isinstance(status, RuntimePolicyStatusInfo)
        assert status.simulations_emitted == 1
        assert status.replays_emitted == 1
