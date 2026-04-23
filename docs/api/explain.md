# spanforge.sdk.explain

Runtime explainability service for the GA governance flow.

## `SFExplainClient`

```python
from spanforge.sdk import sf_explain
```

Use `sf_explain` to generate signed explanation records for runtime decisions.

### `generate(...)`

Create and persist a canonical explanation payload.

```python
from spanforge.sdk import sf_explain

record = sf_explain.generate(
    trace_id="trace-123",
    agent_id="claims-agent",
    decision_id="decision-123",
    summary="Escalated because grounding confidence fell below threshold.",
    policy_action="human_review",
    generated_at="2026-04-23T10:00:00Z",
    factors=[
        {
            "factor_name": "grounding_score",
            "weight": 0.8,
            "contribution": -0.7,
            "evidence": "Average grounding score 0.62 < threshold 0.85",
            "confidence": 0.94,
        }
    ],
)
```

### `generate_with_policy(...)`

Evaluate the active runtime policy for explainability coverage, then emit the explanation with the resulting action and policy metadata attached.

### `list_for_trace(trace_id)`

Return all explanation records for a trace.

### `get_status()`

Returns:

- `status`
- `total_generated`
- `traces_tracked`

## Signed Evidence

Every explanation record is emitted into `sf_audit` under schema key:

`spanforge.explanation.v1`
