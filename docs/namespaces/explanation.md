# explanation — Explainability Events

> **Auto-documented module:** `spanforge.explain`

The `explanation.*` namespace captures explainability records for AI decisions.
One canonical event type:

- `explanation.generated`

## Regulatory mapping

| Framework | Clause | Role of `explanation.*` events |
|-----------|--------|--------------------------------|
| **EU AI Act** | Art. 13 | Transparency — AI decisions must be explainable |
| **NIST AI RMF** | MAP 1.1 | Risk identification — explainability as a risk control |

## Payload fields

`ExplainabilityRecord` is emitted as the event payload.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `trace_id` | `str` | ✓ | Trace ID linking the explanation to the AI decision |
| `agent_id` | `str` | ✓ | Agent that produced the decision |
| `decision_id` | `str` | ✓ | Identifier of the decision being explained |
| `factors` | `list[dict]` | ✓ | Contributing factors, each with `factor_name`, `weight`, `contribution`, `evidence`, `confidence` |
| `summary` | `str` | ✓ | Human-readable explanation of the decision |
| `model_id` | `str \| None` | — | Model used for the decision |
| `confidence` | `float \| None` | — | Overall confidence score in `[0.0, 1.0]` |
| `risk_tier` | `str \| None` | — | Risk tier of the decision |
| `metadata` | `dict` | — | Arbitrary additional metadata |

## Example

```python
from spanforge.explain import generate_explanation

explanation = generate_explanation(
    trace_id="01HQZF...",
    agent_id="loan-agent@1.0.0",
    decision_id="dec_01HX...",
    factors=[
        {
            "factor_name": "credit_score",
            "weight": 0.42,
            "contribution": 0.35,
            "evidence": "Score 720 exceeds threshold 650",
            "confidence": 0.95,
        },
        {
            "factor_name": "income_ratio",
            "weight": 0.31,
            "contribution": 0.28,
            "evidence": "DTI ratio 0.32 within limit",
            "confidence": 0.88,
        },
    ],
    summary="Loan approved: credit score and income ratio within policy limits.",
    model_id="gpt-4o",
    confidence=0.91,
    risk_tier="high",
)

print(explanation.to_text())
```

## Integration with compliance attestations

The `ComplianceMappingEngine` tracks the ratio of explained vs. total AI decisions
as `explanation_coverage_pct` in evidence-package attestations. A coverage below
100% appears in the gap report.

## Serialisation

```python
record.to_dict()   # plain dict for Event.payload
record.to_json()   # JSON string
record.to_text()   # human-readable multi-line text for audit docs
```
