# spanforge._trace

High-level tracing entry point: the `Trace` class and the `start_trace()`
factory function.

---

## `start_trace`

```python
def start_trace(agent_name: str, **attributes: Any) -> Trace
```

Open a new trace for a single agent run. Pushes a root
`AgentRunContextManager` onto the `contextvars` span stack so all child
spans created within the context inherit the `trace_id` automatically.

**Parameters**

| Parameter | Type | Description |
|---|---|---|
| `agent_name` | `str` | Non-empty name for the agent (e.g. `"research-agent"`) |
| `**attributes` | `Any` | Extra key-value pairs stored in the root span's `attributes` dict |

**Returns** — a `Trace` object.

**Context manager** (both sync and async):

```python
# Sync
with spanforge.start_trace("my-agent") as trace:
    ...

# Async
async with spanforge.start_trace("my-agent") as trace:
    ...

# Imperative
trace = spanforge.start_trace("my-agent")
try:
    ...
finally:
    trace.end()
```

---

## `Trace`

```python
@dataclass
class Trace:
    trace_id: str
    agent_name: str
    service_name: str
    start_time: float           # Unix epoch seconds
    spans: list[Span]
```

Created by `start_trace()`. Do not construct directly.

### Methods

#### `llm_call(model, *, operation="chat", temperature=None, top_p=None, max_tokens=None, attributes=None) -> SpanContextManager`

Open a child span of type `llm_call`. All keyword arguments map directly to
`SpanPayload` fields.

#### `tool_call(tool_name, *, attributes=None) -> SpanContextManager`

Open a child span of type `tool_call`.

#### `end() -> None`

Mark the trace as complete and flush any pending spans. Called automatically
when exiting the context manager.

#### `to_json(*, indent=None) -> str`

Serialise the full trace (all accumulated spans) to JSON.

#### `save(path: str) -> None`

Write the trace as NDJSON (one JSON object per line) to `path`.

#### `print_tree(*, file=None) -> None`

Pretty-print the span tree. Delegates to `spanforge.debug.print_tree()`.

#### `summary() -> dict`

Return aggregated statistics. Delegates to `spanforge.debug.summary()`.

---

## Multi-agent cost rollup

When nested `start_trace()` / `tracer.agent_run()` contexts are used, child
run costs automatically bubble to the parent. The `Trace.summary()` output
and the `llm.trace.agent.completed` event include the rolled-up total:

```python
import spanforge

spanforge.configure(exporter="jsonl", service_name="orchestrator")

with spanforge.start_trace("coordinator") as parent:
    with parent.llm_call("gpt-4o") as span:
        span.set_token_usage(input=100, output=50, total=150)
        span.set_status("ok")

    # Sub-agent — its cost is added to the coordinator automatically
    with spanforge.start_trace("researcher") as child:
        with child.llm_call("claude-3-5-sonnet-20241022") as span:
            span.set_token_usage(input=800, output=400, total=1200)
            span.set_status("ok")

parent.print_tree()
# — Agent Run: coordinator  [2.1s]
#  ├─ LLM Call: gpt-4o  [0.3s]  in=100 out=50  $0.0008
#  └─ Agent Run: researcher  [1.8s]
#      └─ LLM Call: claude-3-5-sonnet  [1.6s]  in=800 out=400  $0.0084
#  Total (with children): $0.0092
```

See [llm.cost — Multi-agent cost rollup](../namespaces/cost.md#multi-agent-cost-rollup)
for implementation details.

---

## Re-exports

`Trace` and `start_trace` are re-exported at the top-level `spanforge` package:

```python
from spanforge import Trace, start_trace
```
