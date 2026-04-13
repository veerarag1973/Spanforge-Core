# llm.trace — Span and Agent Trace

> **Auto-documented module:** `spanforge.namespaces.trace`

The `llm.trace.*` namespace contains payload dataclasses for recording
individual LLM calls, agent steps, and full agent runs (RFC-0001 §8).

## Payload classes

| Class | Event type | Description |
|-------|-----------|-------------|
| `SpanPayload` | `llm.trace.span.completed` | Single unit of LLM work — model call, tool invocation, or sub-agent call |
| `AgentStepPayload` | `llm.trace.agent.step` | One iteration of a multi-step agent loop |
| `AgentRunPayload` | `llm.trace.agent.completed` | Root summary for a complete agent run |

## SpanPayload — key fields

| Field | Type | Description |
|-------|------|-------------|
| `span_name` | `str` | Human-readable name for the span |
| `status` | `str` | `"ok"`, `"error"`, or `"timeout"` |
| `duration_ms` | `float` | End-to-end latency in milliseconds |
| `token_usage` | `dict \| None` | Serialised `TokenUsage` (fields: `input_tokens`, `output_tokens`, `total_tokens`) |
| `model_info` | `dict \| None` | Serialised `ModelInfo` (fields: `system`, `name`) |
| `finish_reason` | `str \| None` | Provider finish reason (`"stop"`, `"length"`, `"tool_calls"`…) |
| `stream` | `bool` | Whether the response was streamed |

## Value objects

**`TokenUsage`** — token counts aligned with OTel `gen_ai.usage.*` semconv:

| Field | Type | Description |
|-------|------|-------------|
| `input_tokens` | `int` | Tokens consumed by the prompt |
| `output_tokens` | `int` | Tokens produced in the completion |
| `total_tokens` | `int \| None` | Sum (or provider-reported total) |

**`ModelInfo`** — model identity:

| Field | Type | Description |
|-------|------|-------------|
| `system` | `GenAISystem` | Provider enum value (e.g. `GenAISystem.OPENAI`) |
| `name` | `str` | Model identifier (e.g. `"gpt-4o"`) |

## Example

```python
from spanforge import Event, EventType
from spanforge.namespaces.trace import (
    SpanPayload, TokenUsage, ModelInfo, GenAISystem
)

token_usage = TokenUsage(input_tokens=512, output_tokens=128, total_tokens=640)
model_info  = ModelInfo(system=GenAISystem.OPENAI, name="gpt-4o")

payload = SpanPayload(
    span_name="chat_completion",
    status="ok",
    duration_ms=340.5,
    token_usage=token_usage.to_dict(),
    model_info=model_info.to_dict(),
    finish_reason="stop",
    stream=False,
)

event = Event(
    event_type=EventType.TRACE_SPAN_COMPLETED,
    source="my-app@1.0.0",
    org_id="org_01HX",
    payload=payload.to_dict(),
)
```

---

## AgentRunPayload — key fields

`AgentRunPayload` is the root summary emitted as
`llm.trace.agent.completed` when an agent run finishes.

| Field | Type | Description |
|-------|------|-------------|
| `agent_run_id` | `str` | Unique run identifier |
| `agent_name` | `str` | Name passed to `tracer.agent_run()` or `start_trace()` |
| `trace_id` | `str` | Parent trace identifier |
| `root_span_id` | `str` | Root span for this run |
| `total_steps` | `int` | Number of steps completed |
| `total_model_calls` | `int` | Number of LLM calls across all steps |
| `total_tool_calls` | `int` | Number of tool invocations across all steps |
| `total_token_usage` | `TokenUsage` | Aggregated input/output/total tokens |
| `total_cost` | `CostBreakdown` | Aggregated cost — includes both own steps **and** child run costs |
| `status` | `str` | `"ok"` or `"error"` |
| `start_time_unix_nano` | `int` | Start time (nanoseconds since epoch) |
| `end_time_unix_nano` | `int` | End time (nanoseconds since epoch) |
| `duration_ms` | `float` | Wall-clock duration in milliseconds |
| `termination_reason` | `str \| None` | Why the run ended (e.g. `"max_steps"`, `"budget_exceeded"`) |

### Child run cost rollup

In multi-agent workflows the `total_cost` field includes costs from nested
child agent runs. When a child `AgentRunContextManager` exits, it
automatically calls `parent_run.record_child_run_cost(child_total_cost)`.
The parent's `to_agent_run_payload()` sums child costs into
`total_cost.input_cost_usd` and `total_cost.output_cost_usd`.

See [llm.cost — Multi-agent cost rollup](cost.md#multi-agent-cost-rollup)
for a worked example.
