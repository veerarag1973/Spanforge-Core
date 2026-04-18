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
| `identity` | `pip install "spanforge[identity]"` | `SFIdentityClient` RS256 JWT support via `cryptography`; required only when connecting to a remote sf-identity service (local mode uses stdlib HS256 with no extra) |
| `openai` | `pip install "spanforge[openai]"` | `spanforge.integrations.openai` — auto-instruments the OpenAI Python SDK via `patch()` / `unpatch()`; includes `_pricing` module (unified USD/1M-token table covering OpenAI, Anthropic, Groq, and Together AI models) |
| `http` | `pip install "spanforge[http]"` | `OTLPExporter` and `WebhookExporter` (stdlib transport; reserved for future `httpx` upgrade) |
| `pydantic` | `pip install "spanforge[pydantic]"` | `spanforge.models` — Pydantic v2 model layer, `model_json_schema()` |
| `otel` | `pip install "spanforge[otel]"` | `OTelBridgeExporter` — emits events through any configured `TracerProvider` (`opentelemetry-sdk>=1.24`) |
| `kafka` | `pip install "spanforge[kafka]"` | `EventStream.from_kafka()` via `kafka-python>=2.0` |
| `langchain` | `pip install "spanforge[langchain]"` | `LLMSchemaCallbackHandler` via `langchain-core>=0.2` |
| `llamaindex` | `pip install "spanforge[llamaindex]"` | `LLMSchemaEventHandler` via `llama-index-core>=0.10` |
| `crewai` | `pip install "spanforge[crewai]"` | `SpanForgeCrewAIHandler` and `patch()` via `crewai>=0.28` |
| `anthropic` | `pip install "spanforge[anthropic]"` | `spanforge.integrations.anthropic` — Anthropic Claude SDK integration |
| `gemini` | `pip install "spanforge[gemini]"` | `spanforge.integrations.gemini` — Google Gemini SDK integration |
| `bedrock` | `pip install "spanforge[bedrock]"` | `spanforge.integrations.bedrock` — AWS Bedrock integration |
| `ollama` | `pip install "spanforge[ollama]"` | `spanforge.integrations.ollama` — Ollama local model integration |
| `groq` | `pip install "spanforge[groq]"` | `spanforge.integrations.groq` — Groq inference integration |
| `together` | `pip install "spanforge[together]"` | `spanforge.integrations.together` — Together AI integration |
| `presidio` | `pip install "spanforge[presidio]"` | Presidio-based PII detection backend |
| `redis` | `pip install "spanforge[redis]"` | `RedisExporter` and `RedisBackend` for semantic cache |
| `compliance` | `pip install "spanforge[compliance]"` | Extended compliance mapping dependencies |
| `worm-s3` | `pip install "spanforge[worm-s3]"` | Append-only S3 export backend (WORM) |
| `worm-gcs` | `pip install "spanforge[worm-gcs]"` | Append-only GCS export backend (WORM) |
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
print(spanforge.__version__)   # 2.0.10
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
