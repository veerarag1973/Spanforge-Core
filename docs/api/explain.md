# spanforge.sdk.explain

Runtime explainability service for the GA governance flow.

## `SFExplainClient`

```python
from spanforge.sdk import sf_explain
```

Use `sf_explain` to generate signed explanation records for runtime decisions.

---

## `ModelOutputType`

```python
from spanforge.sdk.explain import ModelOutputType
```

Five typed output classifications that describe *what a model returned* on the hot path.

| Value | String | Use when |
|-------|--------|----------|
| `ModelOutputType.CLASSIFICATION` | `"classification"` | Discrete label / category decision |
| `ModelOutputType.GENERATION` | `"generation"` | Free-text generative output |
| `ModelOutputType.STRUCTURED` | `"structured"` | JSON / dict structured response |
| `ModelOutputType.REJECTION` | `"rejection"` | Refusal or safety block |
| `ModelOutputType.TOOL_CALL` | `"tool_call"` | Tool-use / function-call response |

Pass as `context["model_output_type"]` on `sf_explain.explain()`. When omitted, the type is inferred from the response shape.

---

## `EUAIActClause`

```python
from spanforge.sdk.explain import EUAIActClause
```

Lightweight regulatory clause record emitted on every `ExplainRecord`.

| Field | Type | Description |
|-------|------|-------------|
| `article` | `str` | Clause identifier, e.g. `"Article 13"`. |
| `title` | `str` | Short description of the regulatory requirement. |
| `satisfied` | `bool` | Whether the explanation satisfies this clause. |
| `evidence` | `str` | Free-text evidence written into the signed record. |

---

## `ExplainRecord`

```python
from spanforge.sdk.explain import ExplainRecord
```

Canonical structured return value from `sf_explain.explain()`.

| Field | Type | Description |
|-------|------|-------------|
| `explanation_id` | `str` | ULID-style unique identifier. |
| `trace_id` | `str` | OpenTelemetry trace ID (32-char hex). |
| `agent_id` | `str` | Agent that produced the decision. |
| `decision_id` | `str` | Unique identifier for the decision being explained. |
| `model_output_type` | `str` | Output classification string (see `ModelOutputType`). |
| `decision_drivers` | `list[dict]` | Extracted contributing factors; each dict has `factor_name`, `weight`, `contribution`, `evidence`, `confidence`. |
| `confidence_score` | `float` | 0–1 confidence score from context. |
| `model_version` | `str \| None` | Optional model identifier from context. |
| `eu_ai_act_clauses` | `list[EUAIActClause]` | Article 13 + Article 14 clauses; always populated. |
| `hmac_signature` | `str` | HMAC-SHA256 signature from `sf_audit.append()`. |
| `generated_at` | `str` | ISO 8601 UTC timestamp. |
| `human_oversight_required` | `bool` | `True` when `confidence_score < 0.7` (Article 14 flag). Computed in `__post_init__`. |
| `audit_record_id` | `str` | Record ID of the appended audit entry (`""` when audit not available). |

---

## `SFExplainClient.explain()`

Production hot-path method. Returns a fully signed `ExplainRecord`.

```python
from spanforge.sdk import sf_explain
from spanforge.sdk.explain import ModelOutputType

record = sf_explain.explain(
    "billing_inquiry",          # model response (any type)
    {
        "trace_id": "trace-123",
        "agent_id": "billing-agent",
        "model_output_type": ModelOutputType.CLASSIFICATION.value,
        "confidence_score": 0.91,
        "model_version": "gpt-4o-mini",
    },
)

assert record.eu_ai_act_clauses  # always present
assert record.hmac_signature     # always signed
```

**Pipeline (in order):**

1. Infer `ModelOutputType` from `context["model_output_type"]` or auto-detect from `response` shape.
2. Extract `decision_drivers` per output type:
   - `CLASSIFICATION` → predicted class string.
   - `GENERATION` → first 80 characters of generated text.
   - `STRUCTURED` → comma-joined top-level keys.
   - `REJECTION` → rejection signal string.
   - `TOOL_CALL` → tool name from `response["tool_calls"][0]`.
3. Build EU AI Act Article 13 (transparency) and Article 14 (human oversight) clauses. Article 14 `satisfied = confidence_score >= 0.7` (default threshold).
4. HMAC-sign the full record via `sf_audit.append()`; store `hmac_signature` and `record_id` on the returned record.

Emit failures are caught and logged at `WARNING` — the method **never raises** on audit failures; the original record is returned unchanged.

---

## `ExplainModelType` *(1B-1 · 2026-05-02)*

```python
from spanforge.sdk.explain import ExplainModelType
```

Five typed model classifications for `generate()`:

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
    model_type=ExplainModelType.RAG,
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

### `get_status() -> ExplainStatusInfo`

Returns an `ExplainStatusInfo` snapshot.

| Field | Type | Description |
|-------|------|-------------|
| `status` | `str` | `"ok"` when the service is healthy. |
| `total_generated` | `int` | Total explanation records emitted since startup. |
| `traces_tracked` | `int` | Number of distinct trace IDs with at least one record. |

## Signed Evidence

Every explanation record is emitted into `sf_audit` under schema key:

`spanforge.explanation.v1`
