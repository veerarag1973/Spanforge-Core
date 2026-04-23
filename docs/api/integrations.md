# spanforge.integrations

Lightweight adapters for third-party LLM orchestration frameworks and providers.

Each integration is a **soft dependency** — the framework/provider package is
only required when you actually call `patch()` or instantiate the handler.
All adapters are importable lazily via the `spanforge.integrations` package
without triggering an import error if the underlying package is not installed.

---

## `spanforge.integrations.openai` — OpenAI Auto-Instrumentation

### Installation

```bash
pip install "spanforge[openai]"
# or
pip install openai
```

### Overview

This module monkey-patches the OpenAI Python SDK so every
`client.chat.completions.create(...)` call (sync and async) automatically
populates the active `spanforge` span with:

- **`TokenUsage`** — `input_tokens`, `output_tokens`, `total_tokens`,
  `cached_tokens`, `reasoning_tokens`
- **`ModelInfo`** — `system=GenAISystem.OPENAI`, `name` from
  `response.model`
- **`CostBreakdown`** — USD cost computed from the static pricing table in
  `spanforge.integrations._pricing`

### `patch()`

```python
def patch() -> None
```

Wraps `Completions.create` (sync) and `AsyncCompletions.create` (async).
Idempotent — calling it multiple times has no effect.

**Raises:** `ImportError` if the `openai` package is not installed.

### `unpatch()`

```python
def unpatch() -> None
```

Restores the original OpenAI methods. Safe to call even if `patch()` was
never called.

**Raises:** `ImportError` if the `openai` package is not installed.

### `is_patched()`

```python
def is_patched() -> bool
```

Returns `True` if `patch()` has been called and not yet reverted.
Returns `False` if `openai` is not installed.

### `normalize_response(response)`

```python
def normalize_response(response: Any) -> tuple[TokenUsage, ModelInfo, CostBreakdown]
```

Extracts structured compliance telemetry from an OpenAI `ChatCompletion`
response object (or any duck-typed mock with the same attribute structure).

| OpenAI field | spanforge field |
|---|---|
| `response.model` | `ModelInfo.name` |
| `usage.prompt_tokens` | `TokenUsage.input_tokens` |
| `usage.completion_tokens` | `TokenUsage.output_tokens` |
| `usage.total_tokens` | `TokenUsage.total_tokens` |
| `usage.prompt_tokens_details.cached_tokens` | `TokenUsage.cached_tokens` |
| `usage.completion_tokens_details.reasoning_tokens` | `TokenUsage.reasoning_tokens` |

Returns a 3-tuple `(TokenUsage, ModelInfo, CostBreakdown)`.

### Example

```python
from spanforge.integrations import openai as openai_integration
import openai, spanforge

# One-time global setup
openai_integration.patch()

spanforge.configure(exporter="console", service_name="my-agent")
client = openai.OpenAI()

with spanforge.tracer.span("llm-call") as span:
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Hello"}],
    )
    # span.token_usage, span.cost, span.model auto-populated

# Restore original methods
openai_integration.unpatch()
```

### Async example

```python
import asyncio, openai, spanforge
from spanforge.integrations import openai as openai_integration

openai_integration.patch()
spanforge.configure(exporter="console", service_name="my-async-agent")

async def main():
    client = openai.AsyncOpenAI()
    with spanforge.tracer.span("async-llm-call") as span:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "Hi"}],
        )
        # span auto-populated

asyncio.run(main())
openai_integration.unpatch()
```

### Auto-populate behaviour

`_auto_populate_span()` is called internally after every patched `create()`.
It silently skips population if:

- No span is currently active on this thread / task.
- `span.token_usage` is already set (manual data is not overwritten).
- `normalize_response()` raises for any reason (e.g. malformed response).
  Instrumentation errors are **never propagated** to user code.

Model name is set on the span only if `span.model is None`.

---

## `spanforge.integrations._pricing` — Unified Provider Pricing Table

Static pricing tables (USD / 1 M tokens) aggregating models from **OpenAI**,
**Anthropic**, **Groq**, and **Together AI**.  Prices reflect each provider's
published rates as of **2026-03-04**.

The `get_pricing()` function is the **canonical cross-provider entry point** —
it searches all provider tables automatically so callers (e.g.
`spanforge.cost._calculate_cost()`) do not need to know which provider a model
belongs to.

### `PRICING_DATE`

```python
PRICING_DATE: str = "2026-03-04"
```

Snapshot date attached to every `CostBreakdown` for auditability.

### `get_pricing(model)`

```python
def get_pricing(model: str) -> dict[str, float] | None
```

Returns the pricing entry for `model`, searching across **all** supported
provider tables in order: OpenAI → Anthropic → Groq → Together AI.
Returns `None` if the model is not found in any table.

Performs an exact lookup first, then strips trailing date suffixes
(e.g. `"gpt-4o-2024-11-20"` → `"gpt-4o"`) to handle version-pinned names.
For Together AI models, also handles `org/model` key formats.

Returned dict has at minimum `"input"` and `"output"` (USD/1M tokens); may
also include provider-specific keys like `"cached_input"` and `"reasoning"`
(OpenAI).

Provider tables are lazy-imported — missing provider packages do not cause
import errors.

### `list_models()`

```python
def list_models() -> list[str]
```

Returns a sorted list of all model names across all supported provider
pricing tables (OpenAI, Anthropic, Groq, Together AI).

### Supported models

#### OpenAI

| Model family | Models |
|---|---|
| GPT-4o | `gpt-4o`, `gpt-4o-2024-11-20`, `gpt-4o-2024-08-06`, `gpt-4o-2024-05-13` |
| GPT-4o mini | `gpt-4o-mini`, `gpt-4o-mini-2024-07-18` |
| GPT-4 Turbo | `gpt-4-turbo`, `gpt-4-turbo-2024-04-09`, `gpt-4-0125-preview`, `gpt-4-1106-preview` |
| GPT-4 base | `gpt-4`, `gpt-4-0613` |
| GPT-3.5 Turbo | `gpt-3.5-turbo`, `gpt-3.5-turbo-0125`, `gpt-3.5-turbo-1106` |
| o1 family | `o1`, `o1-2024-12-17`, `o1-mini`, `o1-mini-2024-09-12`, `o1-preview` |
| o3 family | `o3-mini`, `o3-mini-2025-01-31`, `o3` |
| Embeddings | `text-embedding-3-small`, `text-embedding-3-large`, `text-embedding-ada-002` |

#### Anthropic

| Model family | Models |
|---|---|
| Claude 3.5 | `claude-3-5-sonnet-20241022`, `claude-3-5-sonnet-20240620`, `claude-3-5-haiku-20241022` |
| Claude 3 | `claude-3-opus-20240229`, `claude-3-sonnet-20240229`, `claude-3-haiku-20240307` |
| Claude 2 | `claude-2.1`, `claude-2.0` |
| Claude Instant | `claude-instant-1.2` |

#### Groq

| Model family | Models |
|---|---|
| LLaMA 3.3 | `llama-3.3-70b-versatile`, `llama-3.3-70b-specdec` |
| LLaMA 3.2 | `llama-3.2-1b-preview`, `llama-3.2-3b-preview`, `llama-3.2-11b-vision-preview`, `llama-3.2-90b-vision-preview` |
| LLaMA 3.1 | `llama-3.1-70b-versatile`, `llama-3.1-8b-instant`, `llama-3.1-405b-reasoning` |
| LLaMA 3 | `llama3-70b-8192`, `llama3-8b-8192`, `llama3-groq-70b-8192-tool-use-preview`, `llama3-groq-8b-8192-tool-use-preview` |
| Mixtral | `mixtral-8x7b-32768` |
| Gemma | `gemma-7b-it`, `gemma2-9b-it` |

#### Together AI

| Model family | Models |
|---|---|
| Meta LLaMA 3.3 | `meta-llama/Llama-3.3-70B-Instruct-Turbo`, `meta-llama/Llama-3.3-70B-Instruct-Turbo-Free` |
| Meta LLaMA 3.2 | `meta-llama/Llama-3.2-90B-Vision-Instruct-Turbo`, `meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo`, `meta-llama/Llama-3.2-3B-Instruct-Turbo`, `meta-llama/Llama-3.2-1B-Instruct-Turbo` |
| Meta LLaMA 3.1 | `meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo`, `meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo`, `meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo` |
| Meta LLaMA 3 | `meta-llama/Meta-Llama-3-70B-Instruct-Turbo`, `meta-llama/Meta-Llama-3-8B-Instruct-Turbo` |
| Qwen | `Qwen/Qwen2.5-72B-Instruct-Turbo`, `Qwen/Qwen2.5-7B-Instruct-Turbo`, `Qwen/QwQ-32B-Preview` |
| Mistral / Mixtral | `mistralai/Mixtral-8x7B-Instruct-v0.1`, `mistralai/Mixtral-8x22B-Instruct-v0.1`, `mistralai/Mistral-7B-Instruct-v0.3` |
| DeepSeek | `deepseek-ai/DeepSeek-V3`, `deepseek-ai/DeepSeek-R1`, `deepseek-ai/DeepSeek-R1-Distill-Llama-70B`, `deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B` |
| Google Gemma | `google/gemma-2-27b-it`, `google/gemma-2-9b-it` |

---

## `spanforge.integrations.langchain` — LangChain

### Installation

```bash
pip install "spanforge[langchain]"
# or
pip install langchain-core
```

### `LLMSchemaCallbackHandler`

```python
class LLMSchemaCallbackHandler(BaseCallbackHandler):
    def __init__(
        self,
        source: str = "langchain",
        org_id: str = "",
        exporter: Optional[Exporter] = None,
    )
```

LangChain callback handler that emits `spanforge` events as LangChain
operations occur. Subclasses `langchain_core.callbacks.BaseCallbackHandler`
(or `langchain.callbacks.BaseCallbackHandler` for older LangChain versions).

Importing or instantiating this class raises `ImportError` if neither
`langchain_core` nor `langchain` is installed.

**Args:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | `str` | `"langchain"` | Event source string attached to every emitted event. |
| `org_id` | `str` | `""` | Organisation ID propagated into event payloads. |
| `exporter` | `Exporter \| None` | `None` | Optional exporter. When set, each event is fire-and-forget exported via `loop.create_task()`. |

**Example:**

```python
from spanforge.integrations.langchain import LLMSchemaCallbackHandler

handler = LLMSchemaCallbackHandler(source="my-app@1.0.0", org_id="acme")

# Attach to any LangChain chain / agent
chain = my_chain.with_config({"callbacks": [handler]})
chain.invoke({"input": "Hello"})

# Inspect captured events
for event in handler.events:
    print(event.event_type, event.payload)
```

### Emitted event types

| LangChain callback | Event type emitted |
|-------------------|--------------------|
| `on_llm_start` | `llm.trace.span.started` |
| `on_llm_end` | `llm.trace.span.completed` |
| `on_llm_error` | `llm.trace.span.error` |
| `on_tool_start` | `llm.trace.tool_call.started` |
| `on_tool_end` | `llm.trace.tool_call.completed` |
| `on_tool_error` | `llm.trace.tool_call.error` |

### Methods

#### `events -> List[Event]` *(property)*

All events captured since the handler was created or last cleared.

#### `clear_events() -> None`

Clear the internal event list.

---

## `spanforge.integrations.llamaindex` — LlamaIndex

### Installation

```bash
pip install "spanforge[llamaindex]"
# or
pip install llama-index-core
```

### `LLMSchemaEventHandler`

```python
class LLMSchemaEventHandler:
    def __init__(
        self,
        source: str = "llamaindex",
        org_id: str = "",
        exporter: Optional[Exporter] = None,
    )
```

LlamaIndex callback event handler that converts LlamaIndex callback events to
`spanforge` events.

Importing or instantiating this class raises `ImportError` if neither
`llama_index.core` nor `llama_index` is installed.

**Args:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `source` | `str` | `"llamaindex"` | Event source string attached to every emitted event. |
| `org_id` | `str` | `""` | Organisation ID propagated into event payloads. |
| `exporter` | `Exporter \| None` | `None` | Optional exporter for fire-and-forget event delivery. |

**Example:**

```python
from llama_index.core import Settings
from spanforge.integrations.llamaindex import LLMSchemaEventHandler

handler = LLMSchemaEventHandler(source="my-app@1.0.0", org_id="acme")
Settings.callback_manager.add_handler(handler)
```

### Handled event types

| LlamaIndex event category | Event type emitted |
|--------------------------|-------------------|
| LLM events (`LLM`, `llm`) | `llm.trace.span.started` / `llm.trace.span.completed` |
| Function call events (`FUNCTION_CALL`) | `llm.trace.tool_call.started` / `llm.trace.tool_call.completed` |
| Query events (`QUERY`) | `llm.trace.query.started` / `llm.trace.query.completed` |

### Methods

#### `on_event_start(event_type, payload=None, event_id=None, parent_id=None) -> str`

Called by LlamaIndex at the start of a tracked operation. Returns the `event_id`.

#### `on_event_end(event_type, payload=None, event_id=None) -> None`

Called by LlamaIndex at the end of a tracked operation. Computes `duration_ms`
from the paired `on_event_start` call.

#### `start_trace(trace_id=None) -> None`

No-op — provided for LlamaIndex callback manager protocol compliance.

#### `end_trace(...) -> None`

No-op — provided for LlamaIndex callback manager protocol compliance.

---

## Lazy top-level imports

All handlers and the OpenAI integration helpers are accessible via module
attribute access on `spanforge.integrations` without importing the sub-module
explicitly:

```python
import spanforge.integrations as integrations

# OpenAI integration
integrations.patch()       # spanforge.integrations.openai.patch()
integrations.unpatch()
integrations.is_patched()
integrations.normalize_response(response)

# LangChain
Handler = integrations.LLMSchemaCallbackHandler

# LlamaIndex
Handler = integrations.LLMSchemaEventHandler

# CrewAI
integrations.crewai.patch()
Handler = integrations.crewai.SpanForgeCrewAIHandler
```

---

## `spanforge.integrations.crewai` — CrewAI

See [docs/integrations/crewai.md](../integrations/crewai.md) for the full
integration guide.

### Installation

```bash
pip install "spanforge[crewai]"
```

### `SpanForgeCrewAIHandler`

```python
class SpanForgeCrewAIHandler:
    ...
```

CrewAI callback handler that emits `llm.trace.*` events for agent actions,
task lifecycle, and tool calls.  Follow the same pattern as
`LLMSchemaCallbackHandler`:

```python
from spanforge.integrations.crewai import SpanForgeCrewAIHandler
from crewai import Crew

handler = SpanForgeCrewAIHandler()
crew = Crew(agents=[...], tasks=[...], callbacks=[handler])
crew.kickoff()
```

### `patch()`

```python
def patch() -> None
```

Register `SpanForgeCrewAIHandler` globally into CrewAI's callback system.
Guards with `importlib.util.find_spec("crewai")` so the module imports
cleanly when CrewAI is not installed.

---

## `spanforge.integrations.azure_openai` — Azure OpenAI Instance Instrumentation

This module instruments Azure-hosted OpenAI client instances one client at a
time. That matches the usual Azure OpenAI deployment pattern, where the client
is bound to an Azure endpoint, deployment name, and API version.

### Installation

```bash
pip install "spanforge[openai]"
```

### `instrument_client(client)`

```python
def instrument_client(client: Any) -> Any
```

Wraps `client.chat.completions.create(...)` in-place for one sync client
instance. Safe to call repeatedly on the same client.

When a span is active, the wrapper populates:

- token usage
- model information
- cost data
- Azure-specific attributes such as endpoint, API version, and deployment

### `instrument_async_client(client)`

```python
def instrument_async_client(client: Any) -> Any
```

Async equivalent for one async Azure OpenAI client instance.

### `uninstrument_client(client)`

```python
def uninstrument_client(client: Any) -> Any
```

Restores the original `create()` method for the given client instance.

### `is_instrumented(client)`

```python
def is_instrumented(client: Any) -> bool
```

Returns `True` when the target client instance is currently instrumented.

### `normalize_response(response)`

```python
def normalize_response(response: Any) -> tuple[Any, ModelInfo, Any]
```

Normalizes an Azure OpenAI response into SpanForge token usage, model, and
cost objects using the existing OpenAI response normalizer.

### Example

```python
from openai import AzureOpenAI
import spanforge
from spanforge.integrations.azure_openai import instrument_client

spanforge.configure(exporter="console", service_name="azure-agent")

client = AzureOpenAI(
    azure_endpoint="https://example.openai.azure.com",
    api_version="2024-10-21",
    api_key="test-key",
)
instrument_client(client)

with spanforge.tracer.span("azure-chat") as span:
    client.chat.completions.create(
        model="gpt-4o-prod",
        messages=[{"role": "user", "content": "hello"}],
    )
```

---

## `spanforge.integrations.langgraph` — LangGraph Governance Handler

This integration is intentionally narrow: it is a governance-aware LangGraph
handler for the GA demo path, not a broad auto-patching layer.

### Installation

```bash
pip install "spanforge[langgraph]"
```

### `is_available()`

```python
def is_available() -> bool
```

Returns `True` when `langgraph` can be imported.

### `LangGraphGovernanceHandler`

```python
class LangGraphGovernanceHandler:
    def __init__(
        self,
        *,
        source: str = "spanforge.langgraph@1.0.0",
        environment: str = "prod",
        policy_client: Any | None = None,
        scope_client: Any | None = None,
        rbac_client: Any | None = None,
        lineage_client: Any | None = None,
    ) -> None
```

Records LangGraph runs and nodes while optionally invoking:

- `sf_policy`
- `sf_scope`
- `sf_rbac`
- `sf_lineage`

### Core methods

| Method | Purpose |
|--------|---------|
| `on_graph_start(...)` | start one governed graph run |
| `on_node_start(...)` | record a node and optionally run scope/RBAC checks |
| `on_node_end(...)` | complete a node and optionally capture lineage |
| `on_node_error(...)` | record node failure |
| `on_graph_end(...)` | complete the graph run |

### Emitted event types

- `llm.langgraph.run.started`
- `llm.langgraph.node.started`
- `llm.langgraph.node.completed`
- `llm.langgraph.node.error`
- `llm.langgraph.run.completed`
