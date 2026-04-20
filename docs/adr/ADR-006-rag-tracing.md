# ADR-006: RAG Tracing Namespace and SDK Design

**Status:** Accepted  
**Date:** 2024-01-15  
**Deciders:** SpanForge Core Team

---

## Context

As Retrieval-Augmented Generation (RAG) pipelines become central to LLM deployments,
SpanForge needs first-class observability for the query → retrieval → generation flow.
Existing `sf_observe` provides generic LLM span tracing, but lacks:

1. Correlation of retrieval results with the generation that consumed them.
2. Grounding score tracking (are responses anchored in retrieved content?).
3. Session-level aggregates (total tokens, chunks, latency) across all pipeline phases.
4. Privacy controls over raw query text and document content.

The RAG tracing feature (Phase 13, F-20) must integrate with existing SpanForge
conventions for local-first architecture (ADR-004), singleton clients (ADR-002),
and the `llm.*` event namespace hierarchy.

---

## Decision

### Namespace

Introduce a new `llm.rag.*` namespace under `spanforge.namespaces.retrieval`:

| Event | Payload class | Trigger |
|-------|---------------|---------|
| `llm.rag.query` | `RetrievalQueryPayload` | `sf_rag.trace_query()` |
| `llm.rag.retrieved` | `RetrievalResultPayload` | `sf_rag.trace_retrieval()` |
| `llm.rag.generated` | `RAGSpanPayload` | `sf_rag.trace_generation()` |
| `llm.rag.session` | `RAGSessionPayload` | `sf_rag.end_session()` |

### SDK client

A new `SFRAGClient` follows the established `SFServiceClient` base class pattern
(ADR-002) and is registered as the `sf_rag` module-level singleton.

### Session model

A session is an in-process accumulator keyed by `session_id` (auto-ULID or caller-supplied).
Sessions are stored in a `dict` protected by a `threading.Lock`, consistent with
the local-first architecture (ADR-004). Sessions are removed from the active map
when `end_session()` is called.

Unknown `session_id` values passed to `trace_retrieval()` or `trace_generation()`
are silently ignored (no exception raised) to allow fire-and-forget usage patterns
without crashing on session mismatches.

### Privacy

- Raw query text is **never stored**; only `SHA-256(query.encode("utf-8"))` is recorded as `query_hash`.
- Retrieved document content is **never passed to SpanForge**; callers supply only `chunk_id`, `score`, `content_hash`, and `source`.
- `chunk_id` values are stored as-is — callers are responsible for ensuring they do not contain PII.

---

## Alternatives considered

### A. Extend `sf_observe` with RAG-specific keyword args

Rejected. Adding RAG-specific parameters to `SFObserveClient` would bloat the
interface with domain-specific concepts and couple the generic span model to
retrieval semantics. A separate client keeps concerns isolated.

### B. Record raw query text with access-controlled storage

Rejected. Storing raw queries in any form creates a GDPR Article 17 (Right to Erasure)
surface area. Hashing is irreversible and eliminates this risk at the cost of query
re-identifiability (which is acceptable for observability purposes).

### C. Session correlation via span parent IDs only

Rejected. Relying on `parent_span_id` for cross-phase correlation requires callers
to thread span IDs through retrieval and generation calls, which is cumbersome.
Explicit `session_id` threading is simpler and matches common RAG framework patterns
(e.g. LangChain `run_id`, LlamaIndex `query_id`).

---

## Consequences

**Positive:**
- Complete RAG pipeline observability without raw data retention.
- Compatible with existing `sf_observe` for full LLM traces.
- `avg_grounding_score` in session summaries provides a built-in hallucination proxy metric.
- Thread-safe by construction.

**Negative:**
- Callers must explicitly call `end_session()` to emit the `llm.rag.session` summary event; forgetting this omits the session aggregate.
- `query_hash` prevents log-level query analysis without a separate retrieval of query IDs.
- In-process session state is lost on process restart (consistent with ADR-004 local-first).

---

## References

- [ADR-004 Local-First Architecture](ADR-004-local-first-architecture.md)
- [ADR-002 Singleton Service Clients](ADR-002-singleton-service-clients.md)
- [`spanforge.sdk.rag` API reference](../api/rag.md)
- [`spanforge.namespaces.retrieval`](../namespaces/retrieval.md)
