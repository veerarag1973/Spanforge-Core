# llm.cost — Cost Tracking

> **Auto-documented module:** `spanforge.namespaces.cost`

The `llm.cost.*` namespace records token-level cost estimates, per-session
budget summaries, and cost attribution records (RFC-0001 §9).

## Payload classes

| Class | Event type | Description |
|-------|-----------|-------------|
| `CostTokenRecordedPayload` | `llm.cost.token.recorded` | Cost for a single model call (one span) |
| `CostSessionRecordedPayload` | `llm.cost.session.recorded` | Aggregate cost across an agent session |
| `CostAttributedPayload` | `llm.cost.attributed` | Cost attributed to a specific user, team, or tag |

---

## `CostTokenRecordedPayload`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `cost` | `CostBreakdown` | ✓ | Serialised cost breakdown (`input_cost_usd`/`output_cost_usd`/`total_cost_usd`) |
| `token_usage` | `TokenUsage` | ✓ | Token counts for this span |
| `model` | `ModelInfo` | ✓ | Model that generated the response |
| `pricing_tier` | `PricingTier \| None` | — | Pricing snapshot for cost reproduction |
| `span_id` | `str \| None` | — | Parent span identifier |
| `agent_run_id` | `str \| None` | — | Agent run this span belongs to |

---

## Example

```python
from spanforge import Event, EventType
from spanforge.namespaces.cost import CostTokenRecordedPayload
from spanforge.namespaces.trace import (
    CostBreakdown, TokenUsage, ModelInfo, GenAISystem
)

cost       = CostBreakdown(input_cost_usd=0.0015, output_cost_usd=0.0006, total_cost_usd=0.0021)
token_usage = TokenUsage(input_tokens=500, output_tokens=200, total_tokens=700)
model      = ModelInfo(system=GenAISystem.OPENAI, name="gpt-4o")

payload = CostTokenRecordedPayload(
    cost=cost,
    token_usage=token_usage,
    model=model,
)

event = Event(
    event_type=EventType.COST_TOKEN_RECORDED,
    source="my-app@1.0.0",
    org_id="org_01HX",
    payload=payload.to_dict(),
)
```
