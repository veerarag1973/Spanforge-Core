# spanforge.sdk.explain

Runtime explainability service for the GA governance flow.

## `SFExplainClient`

```python
from spanforge.sdk import sf_explain
```

Use `sf_explain` to generate signed explanation records for runtime decisions.

## `ExplainModelType`

```python
from spanforge.sdk.explain import ExplainModelType
```

Five typed model classifications:

| Value | String | Use when |
|-------|--------|----------|
| `ExplainModelType.LLM` | `"llm"` | Generative language models |
| `ExplainModelType.RAG` | `"rag"` | Retrieval-augmented generation pipelines |
| `ExplainModelType.MULTI_AGENT` | `"multi_agent"` | Multi-agent orchestration |
| `ExplainModelType.CLASSIFIER` | `"classifier"` | Classification models |
| `ExplainModelType.EMBEDDING` | `"embedding"` | Embedding / vector search models |

Pass the enum (or a raw string) as the `model_type` parameter on `generate()`. The value is stored under `metadata["model_type"]` in the signed audit record.

### `generate(...)`

Create and persist a canonical explanation payload.

```python
from spanforge.sdk import sf_explain
from spanforge.sdk.explain import ExplainModelType

record = sf_explain.generate(
    trace_id="trace-123",
    agent_id="claims-agent",
    decision_id="decision-123",
    summary="Escalated because grounding confidence fell below threshold.",
    policy_action="human_review",
    generated_at="2026-04-23T10:00:00Z",
    model_type=ExplainModelType.RAG,          # NEW in 1.0.1
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

**Parameters added in 1.0.1:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `model_type` | `ExplainModelType \| str \| None` | `None` | Model classification stored in `metadata["model_type"]`. |

**Constructor parameters added in 1.0.1:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_retries` | `int` | `3` | Retry attempts for `_emit_signed_record`. |
| `emit_timeout_sec` | `float` | `5.0` | Hard deadline for the entire emit sequence. |

Emit failures are logged at `WARNING` level and never propagate — a fail-safe guarantee that explainability tracking cannot break the request path.

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
