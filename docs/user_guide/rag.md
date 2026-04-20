# RAG Tracing

SpanForge `sf_rag` provides end-to-end observability for Retrieval-Augmented
Generation (RAG) pipelines. Each pipeline run is grouped into a **session**
that ties together the query, retrieval, and generation phases.

## Overview

A RAG trace has three phases:

```
User query ──► trace_query()      → session_id + llm.rag.query event
               trace_retrieval()  → llm.rag.retrieved event
               trace_generation() → llm.rag.generated event
               end_session()      → llm.rag.session summary event
```

All phases are correlated by a single `session_id`.

## Installation / import

`sf_rag` is available as a built-in singleton:

```python
from spanforge.sdk import sf_rag
```

No additional installation is required.

---

## Basic usage

```python
from spanforge.sdk import sf_rag

# 1. Start the session — trace the query
session_id = sf_rag.trace_query(
    query="What were the key outcomes of the 2024 summit?",
    top_k=5,
    retriever_name="pinecone-prod",
    embedding_model="text-embedding-3-large",
)

# 2. Record what the retriever returned
sf_rag.trace_retrieval(
    session_id,
    chunks=[
        {
            "chunk_id": "doc-summit-p1",
            "score": 0.94,
            "content_hash": "abc123...",
            "source": "docs/summit-2024.pdf",
        },
        {
            "chunk_id": "doc-summit-p7",
            "score": 0.87,
            "content_hash": "def456...",
            "source": "docs/summit-2024.pdf",
        },
    ],
    total_found=23,
    latency_ms=62.4,
)

# 3. Record the LLM generation
sf_rag.trace_generation(
    session_id,
    model="gpt-4o",
    chunk_ids_used=["doc-summit-p1", "doc-summit-p7"],
    prompt_tokens=1024,
    output_tokens=256,
    grounding_score=0.88,
    latency_ms=1850.0,
)

# 4. Finish the session and get a summary
summary = sf_rag.end_session(session_id)
print(f"Grounding: {summary.avg_grounding_score:.2f}")  # Grounding: 0.88
print(f"Tokens: {summary.total_input_tokens + summary.total_output_tokens}")
```

---

## Privacy guarantees

SpanForge RAG tracing is designed to avoid storing sensitive content:

| What you provide | What SpanForge stores |
|------------------|-----------------------|
| `query` text | SHA-256 hash only |
| Retrieved document content | Never stored |
| `chunk_id` values | Stored as-is — keep these PII-free |
| Grounding scores, token counts | Stored as numbers |

---

## Using an explicit session ID

By default `trace_query` generates a ULID for `session_id`. You can supply
your own to align RAG sessions with your application's own conversation IDs:

```python
session_id = sf_rag.trace_query(
    query="...",
    session_id="conv-" + user_conversation_id,
)
```

---

## Inspecting a live session

Use `get_session()` to read session state without ending it:

```python
live = sf_rag.get_session(session_id)
if live:
    print(f"Queries so far: {live.total_queries}")
    print(f"Chunks retrieved: {live.total_chunks_retrieved}")
```

---

## Handling retrieval errors

Pass `status="error"` or `status="timeout"` if the retriever fails:

```python
try:
    chunks = my_retriever.search(query)
    sf_rag.trace_retrieval(session_id, chunks=chunks, latency_ms=45.0)
except TimeoutError:
    sf_rag.trace_retrieval(
        session_id,
        chunks=[],
        status="timeout",
        error_message="Retriever timed out after 5s",
        latency_ms=5000.0,
    )
```

---

## Grounding scores

`grounding_score` is an optional `0.0–1.0` float that measures how well the
LLM's answer is supported by the retrieved chunks. This can come from a
hallucination detection model, a retrieval re-ranker, or a custom heuristic.

```python
sf_rag.trace_generation(
    session_id,
    model="gpt-4o",
    chunk_ids_used=chunk_ids,
    grounding_score=0.92,     # 92% of claims are grounded
    ...
)
```

The session summary (`RAGSessionPayload.avg_grounding_score`) averages all
grounding scores across generation spans.

---

## Service health

```python
status = sf_rag.get_status()
print(status.status)           # "ok"
print(status.active_sessions)  # number of open sessions
print(status.total_queries)    # cumulative query count
```

---

## Integration with `sf_observe`

RAG tracing is complementary to `sf_observe`. For complete LLM visibility,
use both:

```python
from spanforge.sdk import sf_rag, sf_observe

# Start a trace span
with sf_observe.span("rag-pipeline") as span:
    session_id = sf_rag.trace_query(query, top_k=5)
    sf_rag.trace_retrieval(session_id, chunks=...)
    sf_rag.trace_generation(session_id, model="gpt-4o", ...)
    summary = sf_rag.end_session(session_id)
```

---

## Thread safety

`SFRAGClient` is thread-safe. Session state is protected by a `threading.Lock`.
You may call `trace_query`, `trace_retrieval`, and `trace_generation` concurrently
from multiple threads, each with a different `session_id`.

---

## API reference

- [`spanforge.sdk.rag.SFRAGClient`](../api/rag.md)
- [`spanforge.namespaces.retrieval`](../namespaces/retrieval.md)
