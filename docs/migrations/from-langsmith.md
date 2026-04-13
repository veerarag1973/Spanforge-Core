# Migrating from LangSmith to spanforge

LangSmith is a hosted observability service for LangChain applications. spanforge provides equivalent tracing with zero vendor lock-in, no call-home, and MIT licensing.

## Key differences

| Feature | LangSmith | spanforge |
|---|---|---|
| Data storage | LangSmith cloud (or self-hosted) | Your infrastructure — files, OTLP, Datadog, etc. |
| Pricing | Per-trace $$ | Free (MIT) |
| Dependencies | `langsmith` package + API key | Zero required deps |
| Offline/air-gapped | No | Yes |
| HMAC audit chain | No | Yes |
| PII redaction | No | Yes (built-in) |
| OTel compatible | Partial | Full OTLP export |

---

## Step 1: Remove LangSmith tracer

```python
# Before (LangSmith)
from langsmith import traceable
from langchain.callbacks import LangChainTracer

tracer = LangChainTracer(project_name="my-project")
# ... chain.invoke(input, config={"callbacks": [tracer]})
```

```python
# After (spanforge)
import spanforge
spanforge.configure(exporter="console", service_name="my-project")
```

---

## Step 2: Replace `@traceable` decorator

LangSmith's `@traceable` records function calls. In spanforge, use the span context manager:

```python
# Before (LangSmith)
from langsmith import traceable

@traceable(name="call-llm")
def call_llm(prompt: str) -> str:
    return openai_client.chat.completions.create(...)

# After (spanforge)
import spanforge

def call_llm(prompt: str) -> str:
    with spanforge.span("call-llm") as span:
        span.set_model(model="gpt-4o", system="openai")
        result = openai_client.chat.completions.create(...)
        span.set_token_usage(
            input=result.usage.prompt_tokens,
            output=result.usage.completion_tokens,
            total=result.usage.total_tokens,
        )
        span.set_status("ok")
        return result.choices[0].message.content
```

---

## Step 3: Replace LangChain callback handler

If you use the spanforge LangChain integration, the callback handler replaces `LangChainTracer` entirely:

```python
# Before (LangSmith)
from langsmith import LangChainTracer
tracer = LangChainTracer(project_name="my-project")
chain.invoke(input, config={"callbacks": [tracer]})

# After (spanforge)
import spanforge
from spanforge.integrations.langchain import SpanForgeCallbackHandler

spanforge.configure(exporter="jsonl", endpoint="events.jsonl", service_name="my-project")
handler = SpanForgeCallbackHandler()
chain.invoke(input, config={"callbacks": [handler]})
```

---

## Step 4: Replace run/trace IDs

LangSmith uses `run_id` / `trace_id` UUIDs. spanforge uses standard `trace_id` / `span_id` fields:

```python
# Accessing the current trace ID
import spanforge
with spanforge.span("my-op") as span:
    print(span.trace_id)   # replaces run_id
    print(span.span_id)    # replaces span_id
```

---

## Step 5: Export your historical data (optional)

If you want to export LangSmith runs to JSONL for replay or archival:

```python
from langsmith import Client
import json

client = Client()
with open("langsmith-export.jsonl", "w") as fh:
    for run in client.list_runs(project_name="my-project"):
        fh.write(json.dumps(run.dict()) + "\n")
```

Then use `spanforge stats langsmith-export.jsonl` for a summary.

---

## Environment variable mapping

| LangSmith | spanforge equivalent |
|---|---|
| `LANGSMITH_API_KEY` | (not needed — no cloud API) |
| `LANGCHAIN_PROJECT` | `SPANFORGE_SERVICE_NAME` |
| `LANGCHAIN_TRACING_V2=true` | `SPANFORGE_ENABLE_TRACE_STORE=1` |
| `LANGCHAIN_ENDPOINT` | `SPANFORGE_ENDPOINT` |

---

## See also

- [spanforge quickstart](../quickstart.md)
- [LangChain integration](../integrations/)
- [CLI reference](../cli.md)
