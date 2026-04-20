# spanforge.sdk.rag — RAG Tracing Client

> **Module:** `spanforge.sdk.rag`  
> **Added in:** 2.0.12 (Phase 13 — RAG Tracing & User Feedback)  
> **Import:** `from spanforge.sdk import sf_rag` or `from spanforge.sdk.rag import SFRAGClient`

`spanforge.sdk.rag` provides end-to-end tracing for Retrieval-Augmented Generation
pipelines. It records query, retrieval, and generation spans with correlation across
an entire RAG session, without storing raw query text or retrieved document content.

---

## Quick example

```python
from spanforge.sdk import sf_rag

# 1. Start a RAG session (returns a session_id to thread through)
session_id = sf_rag.trace_query(
    query="What is the capital of France?",
    top_k=5,
    retriever_name="chroma-main",
)

# 2. Record retrieval results
sf_rag.trace_retrieval(
    session_id,
    chunks=[
        {"chunk_id": "doc-42-p3", "score": 0.93, "content_hash": "abc", "source": "docs/geo.md"},
    ],
    total_found=12,
    latency_ms=45.2,
)

# 3. Record the generation span
sf_rag.trace_generation(
    session_id,
    "gpt-4o",
    chunk_ids_used=["doc-42-p3"],
    prompt_tokens=512,
    output_tokens=128,
    grounding_score=0.91,
    latency_ms=1230.0,
)

# 4. Finalise the session and get an aggregated summary
summary = sf_rag.end_session(session_id)
print(summary.total_queries)        # 1
print(summary.avg_grounding_score)  # 0.91
print(summary.status)               # "ok"
```

---

## Singleton

`spanforge.sdk.sf_rag` is a module-level `SFRAGClient` instance. Import and use
it directly for most use-cases:

```python
from spanforge.sdk import sf_rag
```

To construct a custom instance:

```python
from spanforge.sdk.rag import SFRAGClient
from spanforge.sdk._base import SFClientConfig

client = SFRAGClient(SFClientConfig(api_key="..."))
```

---

## Security model

| Data | Stored as |
|------|-----------|
| Raw query text | **Never stored** — SHA-256 hash only |
| Retrieved document text | **Never stored** |
| Chunk IDs (`chunk_id`) | Stored as-is — callers must not include PII |
| Grounding scores | Stored as floats |
| Token counts | Stored as integers |

---

## `RAGStatusInfo`

```python
@dataclass
class RAGStatusInfo:
    status: str
    active_sessions: int
    total_queries: int
    total_spans: int
```

Returned by `SFRAGClient.get_status()`.

| Field | Description |
|-------|-------------|
| `status` | `"ok"` or `"degraded"` |
| `active_sessions` | Number of sessions started but not yet finalised with `end_session()` |
| `total_queries` | Total `trace_query()` calls in this process lifetime |
| `total_spans` | Total `trace_generation()` calls in this process lifetime |

---

## `SFRAGClient`

```python
class SFRAGClient(SFServiceClient)
```

Thread-safe RAG tracing service client.

### Constructor

```python
SFRAGClient(config: SFClientConfig)
```

---

### `trace_query(query, *, session_id=None, top_k=5, retriever_name="", embedding_model="", namespace="", filters=None) -> str`

Record a RAG query event and start a new session.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | *(required)* | The user query text. SHA-256 hashed — raw text is NOT stored. |
| `session_id` | `str \| None` | `None` | Caller-supplied session ID. Auto-generated (ULID) if omitted. |
| `top_k` | `int` | `5` | Number of chunks requested from the retriever. |
| `retriever_name` | `str` | `""` | Name/identifier of the vector store or retriever. |
| `embedding_model` | `str` | `""` | Embedding model used to encode the query. |
| `namespace` | `str` | `""` | Optional vector store namespace / collection. |
| `filters` | `dict \| None` | `None` | Metadata filters applied to the retrieval query. |

**Returns:** `str` — the `session_id` to pass to subsequent calls.

---

### `trace_retrieval(session_id, *, chunks, total_found=0, latency_ms=0.0, status="ok", error_message=None) -> None`

Record retrieval results for an active session.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | `str` | *(required)* | Session ID returned by `trace_query()`. |
| `chunks` | `list[dict]` | *(required)* | List of chunk dicts, each with `chunk_id`, `score`, `content_hash`, and `source`. |
| `total_found` | `int` | `0` | Total matching chunks before `top_k` truncation. |
| `latency_ms` | `float` | `0.0` | Retrieval latency in milliseconds. |
| `status` | `str` | `"ok"` | `"ok"`, `"partial"`, `"error"`, or `"timeout"`. |
| `error_message` | `str \| None` | `None` | Error detail when `status` is `"error"` or `"timeout"`. |

> **Note:** Unknown `session_id` values are silently ignored (no error raised).

---

### `trace_generation(session_id, model, *, chunk_ids_used, prompt_tokens=0, output_tokens=0, context_tokens=0, grounding_score=None, latency_ms=0.0, status="ok", error_message=None, span_name="generation") -> None`

Record a generation span linked to retrieved chunks.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | `str` | *(required)* | Session ID returned by `trace_query()`. |
| `model` | `str` | *(required)* | LLM model identifier (e.g. `"gpt-4o"`). |
| `chunk_ids_used` | `list[str]` | *(required)* | Chunk IDs whose content was passed to the LLM. |
| `prompt_tokens` | `int` | `0` | Number of input tokens. |
| `output_tokens` | `int` | `0` | Number of output tokens. |
| `context_tokens` | `int` | `0` | Total context tokens (retrieved chunk content). |
| `grounding_score` | `float \| None` | `None` | Grounding score in `[0.0, 1.0]`. Measures how well the answer is grounded in retrieved content. |
| `latency_ms` | `float` | `0.0` | Generation latency in milliseconds. |
| `status` | `str` | `"ok"` | `"ok"`, `"error"`, or `"timeout"`. |
| `error_message` | `str \| None` | `None` | Error detail when `status` is not `"ok"`. |
| `span_name` | `str` | `"generation"` | Label for this generation span. |

> **Note:** Unknown `session_id` values are silently ignored.

---

### `end_session(session_id) -> RAGSessionPayload`

Finalise a RAG session and return an aggregated summary.

| Parameter | Type | Description |
|-----------|------|-------------|
| `session_id` | `str` | Active session to close. |

**Returns:** [`RAGSessionPayload`](../namespaces/retrieval.md#ragsessionpayload) — summary of all queries, chunks used, token counts, and average grounding score.

**Raises:** `KeyError` — if `session_id` has not been started or was already ended.

---

### `get_session(session_id) -> RAGSessionPayload | None`

Return an in-progress session summary without ending it.

**Returns:** `RAGSessionPayload` if the session exists, `None` otherwise.

---

### `get_status() -> RAGStatusInfo`

Return service health and session statistics.

```python
status = sf_rag.get_status()
print(status.status)           # "ok"
print(status.active_sessions)  # 3
print(status.total_queries)    # 47
```

---

## `@trace_rag` decorator (F-20)

> **Added in:** 2.0.14 — lives in `spanforge.auto`; documented here for discoverability.

```python
from spanforge.auto import trace_rag

@trace_rag
def my_retriever(query: str) -> list[dict]:
    ...
```

The `@trace_rag` decorator wraps any callable retrieval function and emits
the same RAG tracing spans (`trace_query` + `trace_retrieval`) that the
auto-instrumentation patch emits for LlamaIndex and LangChain.

Use this decorator when:
- You have a custom retrieval function (not backed by LlamaIndex or LangChain).
- You want explicit, per-function instrumentation rather than global
  monkey-patching via `spanforge.auto.setup()`.

```python
from spanforge.auto import trace_rag

@trace_rag
def search(query: str) -> list[dict]:
    return vector_db.search(query, top_k=5)

results = search("What is the T.R.U.S.T. score threshold?")
# RAG query + retrieval spans emitted automatically
```

All tracing is best-effort — any failure inside `sf_rag` is silently
swallowed so the decorated function always runs normally.

For the full decorator reference, see [`spanforge.auto`](auto.md#trace_rag-decorator-f-20).

---

## Related

- [Namespace payloads — `spanforge.namespaces.retrieval`](../namespaces/retrieval.md)
- [User Feedback — `spanforge.sdk.feedback`](feedback.md)
- [Observability — `spanforge.sdk.observe`](observe.md)
- [`@trace_rag` decorator — `spanforge.auto`](auto.md#trace_rag-decorator-f-20)
- [User Guide — RAG Tracing](../user_guide/rag.md)
