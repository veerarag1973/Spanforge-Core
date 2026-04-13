# Migrating from OpenLLMetry to spanforge

OpenLLMetry (by Traceloop) is an OpenTelemetry-based auto-instrumentation library for LLMs. spanforge is an **AI compliance platform** — it provides a superset of OpenLLMetry's tracing with a richer event schema, built-in HMAC signing, PII redaction, and a full compliance layer including regulatory mapping, consent tracking, human-in-the-loop governance, model registry, and explainability coverage — all without requiring an OTel SDK at runtime.

## Why migrate?

OpenLLMetry helps you **trace** your AI. spanforge helps you **govern** it. If your team needs to demonstrate compliance with the EU AI Act, GDPR, SOC 2, HIPAA, or ISO 42001, spanforge provides the compliance infrastructure — evidence packages, audit chains, regulatory clause mappings — that OpenLLMetry cannot.

## Key differences

| Feature | OpenLLMetry | spanforge |
|---|---|---|
| **Focus** | OTel-based LLM tracing | AI compliance platform |
| Approach | OTel auto-instrumentation patches | Explicit + auto instrumentation |
| Schema | OTel GenAI semantic conventions | RFC-0001 spanforge (richer, AI-native) |
| Zero dependencies | No (requires `opentelemetry-sdk`) | Yes (OTel is an optional extra) |
| PII redaction | No | Yes |
| HMAC signing | No | Yes |
| Cost tracking | Limited | Full CostTracker + budget alerts |
| Offline operation | With file exporter | Yes (native) |
| Regulatory framework mapping | No | EU AI Act, GDPR, SOC 2, HIPAA, ISO 42001, NIST AI RMF |
| Consent boundary tracking | No | `consent.*` events |
| Human-in-the-loop compliance | No | `hitl.*` events |
| Model registry governance | No | `model_registry.*` events |
| Explainability coverage metrics | No | `explanation.*` events |
| Evidence packages + attestations | No | HMAC-signed, auditor-ready |

---

## Step 1: Remove OpenLLMetry initialisation

```python
# Before (OpenLLMetry)
from traceloop.sdk import Traceloop

Traceloop.init(
    app_name="my-app",
    api_endpoint="https://api.traceloop.com",
    headers={"Authorization": "Bearer <key>"},
)
```

```python
# After (spanforge)
import spanforge
spanforge.configure(exporter="otlp", endpoint="http://collector:4318/v1/traces",
                    service_name="my-app")
```

---

## Step 2: Replace `@workflow` / `@task` decorators

```python
# Before (OpenLLMetry)
from traceloop.sdk.decorators import workflow, task

@workflow(name="rag-pipeline")
def run_pipeline(query: str) -> str:
    return retrieve_and_generate(query)

@task(name="generate")
def retrieve_and_generate(query: str) -> str:
    return call_llm(query)

# After (spanforge)
import spanforge

def run_pipeline(query: str) -> str:
    with spanforge.start_trace("rag-pipeline") as trace:
        return retrieve_and_generate(trace, query)

def retrieve_and_generate(trace, query: str) -> str:
    with trace.llm_call("gpt-4o") as span:
        result = call_llm(query)
        span.set_status("ok")
        return result
```

---

## Step 3: Auto-instrumentation

OpenLLMetry patches `openai`, `anthropic`, etc. automatically. spanforge provides the same via:

```python
# After (spanforge auto-instrumentation)
import spanforge
from spanforge.auto import patch_all

spanforge.configure(exporter="otlp", endpoint="http://collector:4318/v1/traces")
patch_all()   # patches openai, anthropic, langchain, etc.

# Now all LLM calls are automatically traced
import openai
response = openai.chat.completions.create(model="gpt-4o", messages=[...])
```

Or patch individual providers:

```python
from spanforge.auto import patch_openai, patch_anthropic
patch_openai()
patch_anthropic()
```

---

## Step 4: Association properties

OpenLLMetry's `Traceloop.set_association_properties()` maps to spanforge span attributes:

```python
# Before
Traceloop.set_association_properties({"user_id": "u123", "chat_id": "c456"})

# After (spanforge)
with spanforge.span("my-op") as span:
    span.set_attribute("user_id", "u123")
    span.set_attribute("chat_id", "c456")
```

---

## Step 5: OTLP export (keep your existing backend)

If you already have an OTel-compatible backend (Jaeger, Grafana Tempo, Honeycomb, etc.):

```python
import spanforge
spanforge.configure(
    exporter="otlp",
    endpoint="http://your-collector:4318/v1/traces",
    service_name="my-app",
)
```

Your existing dashboards continue to work — spanforge events are OTLP-compatible.

---

## Environment variable mapping

| OpenLLMetry / Traceloop | spanforge equivalent |
|---|---|
| `TRACELOOP_API_KEY` | (not needed — no cloud API) |
| `TRACELOOP_BASE_URL` | `SPANFORGE_ENDPOINT` |
| `TRACELOOP_APP_NAME` | `SPANFORGE_SERVICE_NAME` |
| `TRACELOOP_DISABLE_BATCH` | `SPANFORGE_EXPORTER=console` |

---

## See also

- [spanforge quickstart](../quickstart.md)
- [Auto-instrumentation](../integrations/)
- [OTLP export](../integrations/)
- [Configuration reference](../configuration.md)
