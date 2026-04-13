# Migrating from Langfuse to spanforge

Langfuse provides LLM observability with a self-hostable open-source backend. spanforge offers equivalent tracing as a pure Python library — no separate backend service, no Docker Compose stacks, no PostgreSQL.

## Key differences

| Feature | Langfuse | spanforge |
|---|---|---|
| Deployment | Separate backend service (Docker / cloud) | In-process — just `pip install spanforge` |
| Data storage | PostgreSQL / ClickHouse | Your choice: JSONL file, OTLP endpoint, Datadog, etc. |
| Pricing | Free OSS / paid cloud | Free (MIT) |
| HMAC signing | No | Yes |
| PII redaction | No | Yes |
| OTel export | Via LangfuseExporter | Native OTLP |

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
