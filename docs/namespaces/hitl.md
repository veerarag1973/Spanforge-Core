# hitl — Human-in-the-Loop Events

> **Auto-documented module:** `spanforge.namespaces.hitl`

The `hitl.*` namespace captures human oversight of AI decisions — a mandatory
requirement for high-risk AI systems under EU AI Act Art. 14. Four canonical event types:

- `hitl.queued`
- `hitl.reviewed`
- `hitl.escalated`
- `hitl.timeout`

## Regulatory mapping

| Framework | Clause | Role of `hitl.*` events |
|-----------|--------|-------------------------|
| **GDPR** | Art. 22 | Proves human involvement in automated decisions |
| **EU AI Act** | Art. 14 | Mandatory human oversight for high-risk AI |
| **EU AI Act** | Annex IV.5 | Technical documentation — oversight measures |

## Payload class

### `HITLPayload`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `decision_id` | `str` | ✓ | Identifier of the AI decision under review |
| `agent_id` | `str` | ✓ | Agent that produced the decision |
| `risk_tier` | `str` | ✓ | One of `"low"`, `"medium"`, `"high"`, `"critical"` |
| `status` | `str` | ✓ | One of `"queued"`, `"approved"`, `"rejected"`, `"escalated"`, `"timeout"` |
| `reason` | `str` | ✓ | Reason for the review outcome |
| `reviewer` | `str \| None` | — | Identity of the human reviewer |
| `sla_seconds` | `int` | — | Review SLA in seconds. Default `3600` |
| `queued_at` | `str \| None` | — | ISO 8601 timestamp — when queued |
| `resolved_at` | `str \| None` | — | ISO 8601 timestamp — when resolved |
| `escalation_tier` | `int` | — | Escalation level. Default `0` |
| `confidence` | `float \| None` | — | Agent confidence score in `[0.0, 1.0]` |

## Example

```python
from spanforge.namespaces.hitl import HITLPayload

payload = HITLPayload(
    decision_id="dec_01HX...",
    agent_id="loan-agent@1.0.0",
    risk_tier="high",
    status="queued",
    reason="Low confidence on credit decision",
    confidence=0.42,
)

event = Event(
    event_type="hitl.queued",
    source="hitl-service@1.0.0",
    org_id="org_01HX",
    payload=payload.to_dict(),
)
```

## Convenience functions

The `spanforge.hitl` module provides a `HITLQueue` class and module-level helpers:

```python
from spanforge.hitl import queue_for_review, review_item, list_pending

queue_for_review(
    decision_id="dec_01HX...",
    agent_id="loan-agent@1.0.0",
    risk_tier="high",
    reason="Low confidence",
)

review_item(decision_id="dec_01HX...", reviewer="alice", approved=True)
pending = list_pending()
```
