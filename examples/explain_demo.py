"""examples/explain_demo.py — CARD 1B-1 sf_explain production demo.

Demonstrates all five model output types using ``SFExplainClient.explain()``,
showing EU AI Act Article 13/14 clause mapping and the HMAC-signed audit
record returned for each call.

Run:
    python examples/explain_demo.py
"""

from __future__ import annotations

from spanforge.sdk._base import SFClientConfig
from spanforge.sdk.explain import ExplainRecord, ModelOutputType, SFExplainClient


def _print_record(record: ExplainRecord) -> None:
    print(f"\n  explanation_id   : {record.explanation_id}")
    print(f"  model_output_type: {record.model_output_type}")
    print(f"  confidence_score : {record.confidence_score:.2f}")
    print(f"  model_version    : {record.model_version or '(none)'}")
    print(f"  hmac_signature   : {record.hmac_signature[:24]}…" if record.hmac_signature else "  hmac_signature   : (none)")
    print(f"  human_oversight  : {record.human_oversight_required}")
    print("  EU AI Act clauses:")
    for clause in record.eu_ai_act_clauses:
        status = "✓" if clause.satisfied else "✗"
        print(f"    [{status}] {clause.article} → {clause.mapped_field}  — {clause.notes}")
    print("  Decision drivers:")
    for d in record.decision_drivers:
        print(f"    • {d.get('name')}: {str(d.get('value', ''))[:80]}")


def demo_classification(client: SFExplainClient) -> None:
    print("\n=== 1. Classification output ===")
    record = client.explain(
        "billing_inquiry",
        {
            "trace_id": "demo-cls-001",
            "agent_id": "intent-classifier-v3",
            "model_output_type": ModelOutputType.CLASSIFICATION.value,
            "confidence_score": 0.93,
            "model_version": "bert-intent-v2",
        },
    )
    _print_record(record)


def demo_generation(client: SFExplainClient) -> None:
    print("\n=== 2. Generation output ===")
    record = client.explain(
        "Based on your account history, I recommend upgrading to the Pro plan "
        "to unlock unlimited API calls and priority support.",
        {
            "trace_id": "demo-gen-001",
            "agent_id": "support-agent",
            "model_output_type": ModelOutputType.GENERATION.value,
            "confidence_score": 0.78,
            "model_version": "gpt-4o-2025-04",
        },
    )
    _print_record(record)


def demo_structured(client: SFExplainClient) -> None:
    print("\n=== 3. Structured (JSON) output ===")
    record = client.explain(
        {"intent": "order_status", "entities": {"order_id": "ORD-12345"}, "confidence": 0.91},
        {
            "trace_id": "demo-str-001",
            "agent_id": "nlu-agent",
            "model_output_type": ModelOutputType.STRUCTURED.value,
            "confidence_score": 0.91,
        },
    )
    _print_record(record)


def demo_rejection(client: SFExplainClient) -> None:
    print("\n=== 4. Rejection output ===")
    record = client.explain(
        {"refusal": "Content policy violation: request contains disallowed content."},
        {
            "trace_id": "demo-rej-001",
            "agent_id": "safety-guardrail",
            "model_output_type": ModelOutputType.REJECTION.value,
            "confidence_score": 0.99,
        },
    )
    _print_record(record)


def demo_tool_call(client: SFExplainClient) -> None:
    print("\n=== 5. Tool call output ===")
    record = client.explain(
        {
            "tool_calls": [
                {
                    "id": "call_abc123",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city": "London"}'},
                }
            ]
        },
        {
            "trace_id": "demo-tc-001",
            "agent_id": "orchestrator-agent",
            "model_output_type": ModelOutputType.TOOL_CALL.value,
            "confidence_score": 0.88,
            "model_version": "gpt-4o-2025-04",
        },
    )
    _print_record(record)


def main() -> None:
    config = SFClientConfig(project_id="explain-demo")
    client = SFExplainClient(config)

    print("SpanForge sf_explain — CARD 1B-1 demo")
    print("All 5 model output types with EU AI Act Article 13/14 mapping")
    print("=" * 60)

    demo_classification(client)
    demo_generation(client)
    demo_structured(client)
    demo_rejection(client)
    demo_tool_call(client)

    print("\n\nAll 5 output types explained and HMAC-signed via sf_audit.")


if __name__ == "__main__":
    main()
