# Installation

[![PyPI](https://img.shields.io/pypi/v/spanforge?color=4c8cbf&logo=pypi&logoColor=white)](https://pypi.org/project/spanforge/)

## Requirements

- Python **3.9** or later
- No required third-party dependencies for core event creation

## Install from PyPI

```bash
pip install spanforge
```

> The PyPI distribution is named **`spanforge`**. The Python import name remains `spanforge`.

## Optional extras

| Extra | Install command | What it enables |
|-------|-----------------|----------------|
| `jsonschema` | `pip install "spanforge[jsonschema]"` | `validate_event` with full JSON Schema validation |
| `openai` | `pip install "spanforge[openai]"` | `spanforge.integrations.openai` — auto-instruments the OpenAI Python SDK via `patch()` / `unpatch()`; includes `_pricing` module (USD/1M-token table for all current OpenAI models) |
| `http` | `pip install "spanforge[http]"` | `OTLPExporter` and `WebhookExporter` (stdlib transport; reserved for future `httpx` upgrade) |
| `pydantic` | `pip install "spanforge[pydantic]"` | `spanforge.models` — Pydantic v2 model layer, `model_json_schema()` |
| `otel` | `pip install "spanforge[otel]"` | `OTelBridgeExporter` — emits events through any configured `TracerProvider` (`opentelemetry-sdk>=1.24`) |
| `kafka` | `pip install "spanforge[kafka]"` | `EventStream.from_kafka()` via `kafka-python>=2.0` |
| `langchain` | `pip install "spanforge[langchain]"` | `LLMSchemaCallbackHandler` via `langchain-core>=0.2` |
| `llamaindex` | `pip install "spanforge[llamaindex]"` | `LLMSchemaEventHandler` via `llama-index-core>=0.10` |
| `crewai` | `pip install "spanforge[crewai]"` | `SpanForgeCrewAIHandler` and `patch()` via `crewai>=0.28` |
| `datadog` | `pip install "spanforge[datadog]"` | `DatadogExporter` (stdlib transport; reserved for future `ddtrace` integration) |
| `all` | `pip install "spanforge[all]"` | All optional extras |

> **Note:** `CloudExporter` uses stdlib-only HTTP transport and requires no extra install.

Install all optional extras at once:

```bash
pip install "spanforge[all]"
```

## Development installation

```bash
git clone https://github.com/veerarag1973/spanforge.git
cd spanforge
python -m venv .venv
.venv/Scripts/activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -e ".[dev]"   # or: pip install spanforge[all] for end-users
```

This installs all development dependencies including pytest, ruff, mypy, and
all optional extras.

## Verify the installation

```python
import spanforge  # pip install spanforge  →  import spanforge
print(spanforge.__version__)   # 1.0.8
print(spanforge.SCHEMA_VERSION)  # 2.0

from spanforge import Event, EventType
evt = Event(
    event_type=EventType.TRACE_SPAN_COMPLETED,
    source="smoke-test@1.0.0",
    payload={"ok": True},
)
evt.validate()
print("Installation OK")
```
