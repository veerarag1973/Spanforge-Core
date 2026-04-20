# spanforge.auto

Integration auto-discovery. Detects and patches every installed LLM
integration in one call — no per-library import required.  Also provides
automatic RAG instrumentation for LlamaIndex and LangChain, and a
decorator-based `@trace_rag` helper for custom retrieval functions.

---

## Overview

`spanforge.auto` inspects `sys.modules` and the installed package set to find
all LLM client libraries supported by spanforge integrations, then calls
`patch()` on each one that is present.  In the same `setup()` call, it
auto-patches LlamaIndex `VectorIndexRetriever.retrieve` and LangChain
`BaseRetriever.invoke` to emit RAG tracing spans via `sf_rag` without any
app-level changes.

> **Important:** `import spanforge.auto` alone does **not** patch anything.
> You must call `spanforge.auto.setup()` explicitly.

---

## `setup()`

```python
def setup(*, verbose: bool = False) -> set[str]:
```

Auto-patch every installed and importable LLM integration.

Currently supports: `openai`, `anthropic`, `groq`, `ollama`, `together`.
Additionally, when `llama_index` or `langchain_core` are installed, their
retriever methods are monkey-patched to emit RAG tracing spans (see
[RAG auto-patches](#rag-auto-patches-f-20) below).

Returns the set of integration names that were successfully patched.  RAG
patches are reported with a `:rag` suffix, e.g. `"llama_index:rag"`.

```python
import spanforge
import spanforge.auto

spanforge.configure(exporter="console", service_name="my-agent")
patched = spanforge.auto.setup()
# patched == {"openai", "anthropic"}  (whichever are installed)
```

**Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `verbose` | `bool` | `False` | If `True`, logs each patched integration to `logging.getLogger("spanforge.auto")` at `INFO` level. |

**Returns:** `set[str]` — names of successfully patched integrations.

---

## `teardown()`

```python
def teardown(*, verbose: bool = False) -> set[str]:
```

Unpatch all integrations that were patched by `setup()`. Safe to call even
if `setup()` was not called.

Returns the set of integration names that were successfully unpatched.

```python
spanforge.auto.teardown()
# All patched integrations restored to their original state
```

**Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `verbose` | `bool` | `False` | If `True`, logs each unpatched integration at `INFO` level. |

**Returns:** `set[str]` — names of successfully unpatched integrations.

---

## Typical usage pattern

```python
import spanforge
import spanforge.auto

# --- application startup ---
spanforge.configure(
    exporter="console",
    service_name="my-agent",
    schema_version="2.0",
)
spanforge.auto.setup(verbose=True)

# All LLM calls from this point forward are automatically instrumented

# --- application shutdown (optional) ---
spanforge.auto.teardown()
```

### Test isolation

```python
import spanforge.auto

def setup_method(self):
    spanforge.auto.setup()

def teardown_method(self):
    spanforge.auto.teardown()
```

---

## Re-exports

```python
import spanforge.auto

spanforge.auto.setup
spanforge.auto.teardown
spanforge.auto.trace_rag
```

---

## RAG auto-patches (F-20)

> **Added in:** 2.0.13

When `llama_index` or `langchain_core` are installed, `setup()` monkey-patches
their retriever entry-points to record RAG tracing spans automatically:

| Library | Patched symbol |
|---------|---------------|
| `llama_index` | `llama_index.core.retrievers.VectorIndexRetriever.retrieve` |
| `langchain_core` | `langchain_core.retrievers.BaseRetriever.invoke` |

Each patched call:
1. Calls `sf_rag.trace_query()` before invoking the original method.
2. Calls `sf_rag.trace_retrieval()` after, passing latency and chunk count.
3. Restores the original method cleanly when `teardown()` is called.

All RAG instrumentation is **best-effort** — any error inside the wrapper is
silently swallowed so it can never break application code.

The patched set is tracked in `_RAG_PATCHED` and the original methods are
stored in `_RAG_ORIGINALS` for safe restoration.

---

## `@trace_rag` decorator (F-20)

> **Added in:** 2.0.13

```python
from spanforge.auto import trace_rag

@trace_rag
def my_retriever(query: str) -> list[dict]:
    ...
```

Decorates **any** callable retrieval function with RAG tracing.  On each
call the decorator:

1. Calls `sf_rag.trace_query(query=...)` to open a session.
2. Invokes the wrapped function.
3. Calls `sf_rag.trace_retrieval(session_id, chunks=[...], latency_ms=...)`
   with the returned results and wall-clock latency.

The function signature is preserved.  All instrumentation is best-effort —
exceptions inside `sf_rag` calls are caught so your retrieval function always
runs normally.

```python
from spanforge.auto import trace_rag
from spanforge.sdk import sf_rag

@trace_rag
def search(query: str) -> list[dict]:
    return vector_db.search(query, top_k=5)

# RAG spans emitted automatically with every call
results = search("What is the T.R.U.S.T. score threshold?")
```
