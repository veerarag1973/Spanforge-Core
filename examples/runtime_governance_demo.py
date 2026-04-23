"""Phase 7 demo: runtime governance trace to operator evidence package."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from spanforge.runtime_policy import RuntimePolicyBundle, RuntimePolicyRule
from spanforge.sdk import SFClientConfig, configure
import spanforge.sdk as sdk


TRACE_ID = "trace-phase7-runtime"
AGENT_ID = "claims-agent"
ACTOR_ID = "case-worker-7"
DECISION_ID = "decision-phase7-runtime"
ARTIFACT_DIR = Path(__file__).resolve().parent / "artifacts"
OUTPUT_PATH = ARTIFACT_DIR / "runtime_governance_operator_package.json"


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def setup_runtime_policy(now: str) -> None:
    bundle = RuntimePolicyBundle(
        policy_id="ga-runtime-governance",
        version="2026.04.23",
        environment="prod",
        owner="platform-security",
        effective_at=now,
        rationale="Phase 7 demo policy for runtime-governance controls.",
        rules=[
            RuntimePolicyRule(
                rule_id="rag-grounding-threshold",
                service="sf_rag",
                control="grounding_threshold",
                action="human_review",
                threshold=0.85,
                rationale="Escalate low-grounding responses for operator review.",
                metadata={"comparator": "lt"},
            ),
            RuntimePolicyRule(
                rule_id="scope-enforcement",
                service="sf_scope",
                control="capability_enforcement",
                action="block",
                threshold=0.5,
                rationale="Block agents that exceed their registered scope.",
                metadata={"comparator": "lt"},
            ),
            RuntimePolicyRule(
                rule_id="rbac-enforcement",
                service="sf_rbac",
                control="role_enforcement",
                action="block",
                threshold=0.5,
                rationale="Block actors without the required role alignment.",
                metadata={"comparator": "lt"},
            ),
            RuntimePolicyRule(
                rule_id="explain-coverage",
                service="sf_explain",
                control="explanation_generation",
                action="allow+log",
                threshold=0.95,
                rationale="Persist explanations even when coverage checks pass.",
                metadata={"comparator": "lt"},
            ),
            RuntimePolicyRule(
                rule_id="lineage-capture",
                service="sf_lineage",
                control="lineage_capture",
                action="allow+log",
                rationale="Always log lineage evidence for runtime decisions.",
            ),
        ],
    )
    sdk.sf_policy.load_bundle(bundle)
    sdk.sf_policy.activate(
        environment="prod",
        policy_id=bundle.policy_id,
        version=bundle.version,
        activated_at=now,
    )


def emit_runtime_records(now: str) -> None:
    sdk.sf_scope.register_agent(
        agent_id=AGENT_ID,
        capabilities=["claim.read", "decision.write"],
        resource_actions={"claims": ["read"], "decisions": ["write"]},
    )
    sdk.sf_rbac.register_actor(
        actor_id=ACTOR_ID,
        roles=["claims_reviewer", "decision_writer"],
        resource_roles={"decisions": ["decision_writer"]},
    )

    scope_result = sdk.sf_scope.evaluate_with_policy(
        environment="prod",
        trace_id=TRACE_ID,
        agent_id=AGENT_ID,
        resource="claims",
        action_name="read",
        checked_at=now,
        capability="claim.read",
    )
    rbac_result = sdk.sf_rbac.authorize_with_policy(
        environment="prod",
        trace_id=TRACE_ID,
        actor_id=ACTOR_ID,
        resource="decisions",
        action_name="write",
        checked_at=now,
        required_roles=["decision_writer"],
    )

    session_id = sdk.sf_rag.trace_query(
        "Should this claim be approved?",
        session_id="session-phase7-runtime",
        retriever_name="claims-kb",
        top_k=3,
    )
    sdk.sf_rag.trace_retrieval(
        session_id=session_id,
        chunks=[
            {"chunk_id": "claim-doc-1", "score": 0.61, "source": "claims/policy.md"},
            {"chunk_id": "claim-doc-2", "score": 0.58, "source": "claims/exceptions.md"},
        ],
        total_found=2,
        latency_ms=14.0,
    )
    sdk.sf_rag.trace_generation(
        session_id=session_id,
        model="gpt-4o",
        chunk_ids_used=["claim-doc-1", "claim-doc-2"],
        prompt_tokens=220,
        output_tokens=88,
        grounding_score=0.595,
        latency_ms=142.0,
    )
    grounding = sdk.sf_rag.assess_grounding_with_policy(
        environment="prod",
        trace_id=TRACE_ID,
        decision_id=DECISION_ID,
        session_id=session_id,
        assessed_at=now,
        claims=[
            {
                "claim_id": "claim-1",
                "claim_text": "The claim qualifies for auto approval.",
                "grounded": False,
                "score": 0.52,
                "source_ids": ["claim-doc-1"],
            },
            {
                "claim_id": "claim-2",
                "claim_text": "Manual review is required for missing documentation.",
                "grounded": True,
                "score": 0.67,
                "source_ids": ["claim-doc-2"],
            },
        ],
        retriever_name="claims-kb",
        model_id="gpt-4o",
    )

    sdk.sf_explain.generate_with_policy(
        environment="prod",
        trace_id=TRACE_ID,
        agent_id=AGENT_ID,
        decision_id=DECISION_ID,
        summary=(
            "Escalated because grounding evidence was mixed and the average "
            "grounding score fell below the production threshold."
        ),
        generated_at=now,
        coverage_score=0.92,
        factors=[
            {
                "factor_name": "grounding_average",
                "weight": 0.8,
                "contribution": -0.7,
                "evidence": f"Average grounding score {grounding.average_score:.3f} below threshold.",
                "confidence": 0.96,
            },
            {
                "factor_name": "scope_and_rbac",
                "weight": 0.2,
                "contribution": 0.4,
                "evidence": (
                    f"Scope outcome={scope_result.outcome}; RBAC outcome={rbac_result.outcome}."
                ),
                "confidence": 0.93,
            },
        ],
        model_id="gpt-4o",
        confidence=0.94,
    )

    sdk.sf_lineage.record_with_policy(
        environment="prod",
        trace_id=TRACE_ID,
        decision_id=DECISION_ID,
        subject_type="decision",
        subject_id="claim-2042",
        operation="claims.adjudicate",
        recorded_at=now,
        input_refs=["retrieval:claim-doc-1", "retrieval:claim-doc-2"],
        output_refs=["decision:claim-2042"],
        metadata={"session_id": session_id},
    )


def main() -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    configure(
        SFClientConfig(
            project_id="phase7-demo",
            signing_key="phase7-demo-signing-key",
        )
    )
    now = utc_now()
    setup_runtime_policy(now)
    emit_runtime_records(now)

    workflow = sdk.sf_operator.inspect_trace(TRACE_ID)
    package = sdk.sf_operator.export_package(TRACE_ID, output_path=str(OUTPUT_PATH))

    print("Runtime governance demo complete.")
    print(f"Trace: {workflow.trace_id}")
    print(f"Outcome: {workflow.outcome}")
    print(f"Summary: {workflow.summary}")
    print(f"Operator package: {OUTPUT_PATH}")
    print(json.dumps(package.to_dict(), indent=2))


if __name__ == "__main__":
    main()
