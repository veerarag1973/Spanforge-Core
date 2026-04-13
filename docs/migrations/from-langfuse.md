# Migrating from Langfuse to spanforge

Langfuse provides LLM observability with a self-hostable open-source backend. spanforge is an **AI compliance platform** — it offers tracing as a pure Python library with no separate backend, plus regulatory mapping, HMAC-signed evidence packages, consent tracking, human-in-the-loop governance, model registry, and explainability coverage that Langfuse does not provide.

## Why migrate?

Langfuse helps you **monitor** your AI. spanforge helps you **govern** it. If your team needs to prove compliance with the EU AI Act, GDPR, SOC 2, HIPAA, or ISO 42001, spanforge provides the compliance infrastructure — evidence packages, audit chains, regulatory clause mappings — that Langfuse cannot.

## Key differences

| Feature | Langfuse | spanforge |
|---|---|---|
| **Focus** | LLM observability | AI compliance platform |
| Deployment | Separate backend service (Docker / cloud) | In-process — just `pip install spanforge` |
| Data storage | PostgreSQL / ClickHouse | Your choice: JSONL file, OTLP endpoint, Datadog, etc. |
| Pricing | Free OSS / paid cloud | Free (MIT) |
| HMAC signing | No | Yes |
| PII redaction | No | Yes |
| OTel export | Via LangfuseExporter | Native OTLP |
| Regulatory framework mapping | No | EU AI Act, GDPR, SOC 2, HIPAA, ISO 42001, NIST AI RMF |
| Consent boundary tracking | No | `consent.*` events |
| Human-in-the-loop compliance | No | `hitl.*` events |
| Model registry governance | No | `model_registry.*` events |
| Explainability coverage metrics | No | `explanation.*` events |
| Evidence packages + attestations | No | HMAC-signed, auditor-ready |

---

## Step 1: Remove the Langfuse client

```python
# Before (Langfuse)
from langfuse import Langfuse
from langfuse.decorators import observe

lf = Langfuse(public_key="...", secret_key="...", host="...")
```

```python
# After (spanforge)
import spanforge
spanforge.configure(exporter="console", service_name="my-app")
```

---

## Step 2: Replace `@observe` decorator

Langfuse's `@observe` wraps functions as traces/observations. In spanforge:

```python
# Before (Langfuse)
from langfuse.decorators import observe

@observe()
def process_document(text: str) -> str:
    return llm_call(text)

# After (spanforge)
import spanforge

def process_document(text: str) -> str:
    with spanforge.span("process-document") as span:
        result = llm_call(text)
        span.set_status("ok")
        return result
```

---

## Step 3: Replace trace / generation / span hierarchy

Langfuse has `trace → generation / span / event`. spanforge maps cleanly:

| Langfuse concept | spanforge equivalent |
|---|---|
| `Trace` | `spanforge.start_trace()` |
| `Generation` | `trace.llm_call()` or `spanforge.span()` |
| `Span` | `spanforge.span()` |
| `Event` | `span.add_event()` |
| `Score` | `span.set_attribute("score", ...)` |

```python
# Before (Langfuse)
trace = lf.trace(name="rag-pipeline", user_id="user-123")
gen = trace.generation(name="generate", model="gpt-4o", input="...")
gen.end(output="...", usage={"input": 100, "output": 50})

# After (spanforge)
import spanforge

with spanforge.start_trace("rag-pipeline", user_id="user-123") as trace:
    with trace.llm_call("gpt-4o") as span:
        result = llm_call(...)
        span.set_token_usage(input=100, output=50, total=150)
        span.set_status("ok")
```

---

## Step 4: Replace dataset evaluations

Langfuse datasets + evaluations → spanforge baseline testing:

```python
# spanforge baseline testing (replaces Langfuse datasets)
from spanforge.baseline import BaselineRunner

runner = BaselineRunner(dataset="my_dataset.jsonl")
results = runner.run(my_pipeline)
runner.report(results)
```

---

## Environment variable mapping

| Langfuse | spanforge equivalent |
|---|---|
| `LANGFUSE_PUBLIC_KEY` | (not needed) |
| `LANGFUSE_SECRET_KEY` | `SPANFORGE_SIGNING_KEY` (HMAC key — different purpose) |
| `LANGFUSE_HOST` | `SPANFORGE_ENDPOINT` |
| `LANGFUSE_ENABLED` | (always on; use `SPANFORGE_SAMPLE_RATE=0` to disable) |

---

## Exporting Langfuse data to JSONL (optional)

```python
import requests, json

headers = {"Authorization": f"Basic <base64(pk:sk)>"}
resp = requests.get("https://<host>/api/public/traces", headers=headers)
with open("langfuse-export.jsonl", "w") as fh:
    for trace in resp.json()["data"]:
        fh.write(json.dumps(trace) + "\n")
```

---

## See also

- [spanforge quickstart](../quickstart.md)
- [Trace API](../api/)
- [CLI: stats, validate, report](../cli.md)
