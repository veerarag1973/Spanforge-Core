# CrewAI Integration

spanforge 2.0 ships a native CrewAI handler that emits `llm.trace.*` events
for every agent action, task, and tool call executed by a CrewAI crew.

---

## Installation

```bash
pip install "spanforge[crewai]"
# or
pip install spanforge crewai
```

---

## Quickstart

### Option 1 — global patch (recommended)

```python
from spanforge.integrations.crewai import patch
import spanforge

spanforge.configure(exporter="console", service_name="my-crew")
patch()   # registers SpanForgeCrewAIHandler with CrewAI globally

# ... define and run your crew as normal ...
crew.kickoff()
```

`patch()` is a no-op (with a warning) if CrewAI is not installed.

### Option 2 — attach to a specific crew

```python
from spanforge.integrations.crewai import SpanForgeCrewAIHandler
from crewai import Crew, Agent, Task
import spanforge

spanforge.configure(exporter="console", service_name="my-crew")

handler = SpanForgeCrewAIHandler()

crew = Crew(
    agents=[...],
    tasks=[...],
    callbacks=[handler],
)
crew.kickoff()
```

---

## `SpanForgeCrewAIHandler`

```python
class SpanForgeCrewAIHandler:
    ...
```

A CrewAI callback handler that emits spanforge span events for:

| Callback | spanforge event |
|---|---|
| `on_agent_action(agent, task, tool, tool_input)` | Opens a `tool_call` span |
| `on_agent_finish(agent, output)` | Closes the agent span |
| `on_tool_start(tool, input)` | Opens a `tool_call` span |
| `on_tool_end(tool, output)` | Closes the tool span with `status="ok"` |
| `on_task_start(task)` | Opens an `agent_step` span |
| `on_task_end(task, output)` | Closes the task span |

All hook errors are silently swallowed so that instrumentation failures
never abort crew execution.

---

## `patch()`

```python
def patch() -> None
```

Convenience function that instantiates `SpanForgeCrewAIHandler` and
registers it into CrewAI's global callback list.

Guards with `importlib.util.find_spec("crewai")` so the module can be
imported even when CrewAI is not installed.

---

## Combining with `start_trace()`

For richer context, wrap your crew execution in a `start_trace()` block:

```python
import spanforge
from spanforge.integrations.crewai import patch

spanforge.configure(exporter="jsonl", jsonl_path="crew_trace.jsonl")
patch()

with spanforge.start_trace("my-crew") as trace:
    crew.kickoff()

trace.print_tree()
```

---

## What data is recorded

- **Agent name** and **role** (via `getattr(agent, "role", ...)`)
- **Tool name** and **input** (truncated to 2 048 chars)
- **Task description** (when available)
- **Status** (`"ok"` / `"error"`) and exception message on failures
- **Token usage** and **cost** when available from CrewAI output objects
