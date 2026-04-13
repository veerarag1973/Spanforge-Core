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

## Multi-agent cost rollup

In multi-agent workflows, child agent runs automatically propagate their
costs to the parent `AgentRunContext`. When the inner
`AgentRunContextManager` exits, it calls
`parent_run.record_child_run_cost(total_cost)` to register a
`CostBreakdown` on the parent. The parent's final `AgentRunPayload`
includes both its own step costs **and** all child run costs in
`total_cost`.

### How it works

1. `AgentRunContext` maintains a `_child_run_costs: list[CostBreakdown]`
   accumulator (not exported — internal bookkeeping only).
2. On `AgentRunContextManager.__exit__`, after the inner run's
   `to_agent_run_payload()` is computed, the child's `total_cost` is
   recorded on the parent via `record_child_run_cost()`.
3. When the parent calls `to_agent_run_payload()`, child costs are summed
   into `total_in_cost` and `total_out_cost` alongside step-level costs.

### Example — nested agent cost rollup

```python
import spanforge

spanforge.configure(exporter="jsonl", service_name="orchestrator")

with spanforge.tracer.agent_run("parent-agent") as parent:
    with parent.step("research") as step:
        # Direct LLM call on the parent
        step.set_token_usage(input=200, output=100, total=300)
        step.set_cost(input_usd=0.0005, output_usd=0.001)

    # Nested child agent run — costs bubble to parent automatically
    with spanforge.tracer.agent_run("child-summariser") as child:
        with child.step("summarise") as step:
            step.set_token_usage(input=500, output=250, total=750)
            step.set_cost(input_usd=0.00125, output_usd=0.0025)

# parent's AgentRunPayload.total_cost now includes:
#   own steps : $0.0015
#   child run : $0.00375
#   total     : $0.00525
```

### Extracting per-run costs from the CLI

Use `spanforge cost run` to view the per-model breakdown for any run:

```bash
spanforge cost run --run-id 01JPXXXXXXXX --input events.jsonl
```

See [CLI reference — `cost run`](../cli.md#cost-run) for full options and
example output.

---

## Unified pricing lookup

Cost calculation uses `spanforge.integrations._pricing.get_pricing()` which
searches **all** provider pricing tables (OpenAI, Anthropic, Groq,
Together AI) automatically. No configuration is required — any model name
returned by a supported provider is resolved to its per-million-token rates.

See [API — Unified Provider Pricing Table](../api/integrations.md#spanforgeintegrations_pricing--unified-provider-pricing-table)
for the full model list.

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
