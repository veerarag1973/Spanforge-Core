# Namespace: `llm.rag.*` — RAG Retrieval Payloads

> **Module:** `spanforge.namespaces.retrieval`  
> **Added in:** 2.0.12 (Phase 13)  
> **Events covered:** `llm.rag.query`, `llm.rag.retrieved`, `llm.rag.generated`, `llm.rag.session`

This namespace covers all payload types emitted during a Retrieval-Augmented
Generation (RAG) pipeline trace. Use [`spanforge.sdk.rag`](../api/rag.md) to emit these
events without constructing the dataclasses directly.

---

## Classes

| Class | Event | Description |
|-------|-------|-------------|
| `RetrievedChunk` | *(value object)* | A single retrieved document chunk with relevance score |
| `RetrievalQueryPayload` | `llm.rag.query` | User query + retriever configuration |
| `RetrievalResultPayload` | `llm.rag.retrieved` | List of retrieved chunks from the vector store |
| `RAGSpanPayload` | `llm.rag.generated` | LLM generation span over retrieved context |
| `RAGSessionPayload` | `llm.rag.session` | End-to-end RAG session summary |

---

## `RetrievedChunk`

A value object representing one retrieved document chunk. Used inside `RetrievalResultPayload.chunks`.

```python
@dataclass
class RetrievedChunk:
    chunk_id: str
    content_hash: str
    score: float
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
```

| Field | Type | Validation | Description |
|-------|------|-----------|-------------|
| `chunk_id` | `str` | non-empty | Unique identifier for the chunk within the document store |
| `content_hash` | `str` | — | SHA-256 hex digest of the chunk text (raw text is **never** stored) |
| `score` | `float` | `[0.0, 1.0]` | Relevance / similarity score |
| `source` | `str` | — | Document source (e.g. URI, filename, database key) |
| `metadata` | `dict` | — | Arbitrary key-value metadata attached to the chunk |

**Methods:** `to_dict() -> dict`, `from_dict(data: dict) -> RetrievedChunk`

---

## `RetrievalQueryPayload`

Payload for `llm.rag.query` events. Captures the user query and retriever
configuration without storing raw query text.

```python
@dataclass
class RetrievalQueryPayload:
    session_id: str
    query_hash: str
    top_k: int = 5
    retriever_name: str = ""
    embedding_model: str = ""
    namespace: str = ""
    latency_ms: float = 0.0
    filters: dict[str, Any] = field(default_factory=dict)
```

| Field | Type | Validation | Description |
|-------|------|-----------|-------------|
| `session_id` | `str` | non-empty | RAG session this query belongs to |
| `query_hash` | `str` | — | SHA-256 hex digest of the query text (raw text NOT stored) |
| `top_k` | `int` | `>= 1` | Number of chunks requested from the retriever |
| `retriever_name` | `str` | — | Name / identifier of the vector store or retriever |
| `embedding_model` | `str` | — | Embedding model used to encode the query |
| `namespace` | `str` | — | Optional vector store namespace / collection |
| `latency_ms` | `float` | `>= 0` | Time taken to submit the query (ms) |
| `filters` | `dict` | — | Metadata filters applied to the retrieval query |

**Methods:** `to_dict() -> dict`, `from_dict(data: dict) -> RetrievalQueryPayload`

---

## `RetrievalResultPayload`

Payload for `llm.rag.retrieved` events. Contains the ordered list of chunks
returned from the retriever.

```python
@dataclass
class RetrievalResultPayload:
    session_id: str
    query_hash: str
    chunks: list[RetrievedChunk] = field(default_factory=list)
    total_found: int = 0
    latency_ms: float = 0.0
    status: Literal["ok", "partial", "error", "timeout"] = "ok"
    error_message: str | None = None
```

| Field | Type | Validation | Description |
|-------|------|-----------|-------------|
| `session_id` | `str` | non-empty | RAG session this result belongs to |
| `query_hash` | `str` | — | SHA-256 digest of the triggering query |
| `chunks` | `list[RetrievedChunk]` | — | Ordered list of retrieved chunks (top-k) |
| `total_found` | `int` | — | Total matching chunks before `top_k` truncation |
| `latency_ms` | `float` | `>= 0` | Retrieval latency in milliseconds |
| `status` | `str` | enum | `"ok"`, `"partial"`, `"error"`, or `"timeout"` |
| `error_message` | `str \| None` | — | Error detail when `status` is `"error"` or `"timeout"` |

**Methods:** `to_dict() -> dict`, `from_dict(data: dict) -> RetrievalResultPayload`

---

## `RAGSpanPayload`

Payload for `llm.rag.generated` events. Represents the LLM generation step
that consumes retrieved context.

```python
@dataclass
class RAGSpanPayload:
    session_id: str
    span_name: str
    model: str
    chunk_ids_used: list[str] = field(default_factory=list)
    context_tokens: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    status: Literal["ok", "error", "timeout"] = "ok"
    grounding_score: float | None = None
    error_message: str | None = None
```

| Field | Type | Validation | Description |
|-------|------|-----------|-------------|
| `session_id` | `str` | non-empty | RAG session this span belongs to |
| `span_name` | `str` | — | Human-readable label for this generation step |
| `model` | `str` | non-empty | Model identifier (e.g. `"gpt-4o"`) |
| `chunk_ids_used` | `list[str]` | — | Chunk IDs whose content was passed to the LLM |
| `context_tokens` | `int` | — | Tokens consumed by the retrieved context |
| `prompt_tokens` | `int` | — | Total prompt tokens (context + instruction) |
| `output_tokens` | `int` | — | Tokens in the generated response |
| `latency_ms` | `float` | `>= 0` | Total generation latency in milliseconds |
| `status` | `str` | enum | `"ok"`, `"error"`, or `"timeout"` |
| `grounding_score` | `float \| None` | `[0.0, 1.0]` | How well the output is grounded in retrieved content |
| `error_message` | `str \| None` | — | Present when `status` is not `"ok"` |

**Methods:** `to_dict() -> dict`, `from_dict(data: dict) -> RAGSpanPayload`

---

## `RAGSessionPayload`

Payload for `llm.rag.session` events. An aggregated summary of a complete
RAG session, emitted when `sf_rag.end_session()` is called.

```python
@dataclass
class RAGSessionPayload:
    session_id: str
    retriever_name: str
    total_queries: int = 0
    total_chunks_retrieved: int = 0
    unique_chunk_ids: list[str] = field(default_factory=list)
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    avg_grounding_score: float | None = None
    total_latency_ms: float = 0.0
    started_at: str = ""
    status: str = "ok"
```

| Field | Type | Description |
|-------|------|-------------|
| `session_id` | `str` | The session identifier |
| `retriever_name` | `str` | Primary retriever used in this session |
| `total_queries` | `int` | Number of `trace_query()` calls in the session |
| `total_chunks_retrieved` | `int` | Total chunks retrieved across all retrievals |
| `unique_chunk_ids` | `list[str]` | Deduplicated list of all chunk IDs referenced |
| `total_input_tokens` | `int` | Sum of all `prompt_tokens` across generation spans |
| `total_output_tokens` | `int` | Sum of all `output_tokens` across generation spans |
| `avg_grounding_score` | `float \| None` | Mean grounding score; `None` if no scores recorded |
| `total_latency_ms` | `float` | Combined latency across all spans in ms |
| `started_at` | `str` | ISO 8601 timestamp when the session was started |
| `status` | `str` | Overall session status (`"ok"` or `"error"`) |

**Methods:** `to_dict() -> dict`, `from_dict(data: dict) -> RAGSessionPayload`

---

## Usage example

```python
from spanforge.namespaces.retrieval import (
    RetrievedChunk,
    RetrievalQueryPayload,
    RetrievalResultPayload,
    RAGSpanPayload,
    RAGSessionPayload,
)

# Prefer the high-level client instead:
from spanforge.sdk import sf_rag
session_id = sf_rag.trace_query("What is entropy?", top_k=3)
```

---

## Related

- [sf-rag SDK client](../api/rag.md)
- [User Guide — RAG Tracing](../user_guide/rag.md)
- [Feedback namespace](feedback.md)
