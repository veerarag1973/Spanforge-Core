# llm.fence — Perimeter / Schema Validation

> **Auto-documented module:** `spanforge.namespaces.fence`

The `llm.fence.*` namespace records the outcome of structured-output
validation, retry attempts, and hard failures when a schema fence rejects
model output (RFC-0001 §4).

## Payload classes

| Class | Event type | Description |
|-------|-----------|-------------|
| `FenceValidatedPayload` | `llm.fence.validated` | An output passed schema validation |
| `FenceRetryTriggeredPayload` | `llm.fence.retry.triggered` | Validation failed and a retry was issued |
| `FenceMaxRetriesExceededPayload` | `llm.fence.max_retries.exceeded` | Max retry limit was reached |

---

## `FenceValidatedPayload` — key fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `fence_id` | `str` | ✓ | Identifier of the fence rule or schema |
| `schema_name` | `str` | ✓ | Name of the JSON Schema / Pydantic model validated against |
| `attempt` | `int` | ✓ | 1-based attempt number (1 = first try, no retry) |
| `output_type` | `str \| None` | — | One of `"json_schema"`, `"pydantic"`, `"regex"`, `"xml"`, `"custom"` |
| `span_id` | `str \| None` | — | Parent span identifier |
| `validation_duration_ms` | `float \| None` | — | Validation latency in milliseconds |

---

## Example

```python
from spanforge import Event, EventType
from spanforge.namespaces.fence import FenceValidatedPayload

payload = FenceValidatedPayload(
    fence_id="customer-reply-schema-v2",
    schema_name="CustomerReplyResponse",
    attempt=1,
    output_type="pydantic",
    validation_duration_ms=1.8,
)

event = Event(
    event_type=EventType.FENCE_VALIDATED,
    source="my-app@1.0.0",
    org_id="org_01HX",
    payload=payload.to_dict(),
)
```
