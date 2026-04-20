# ADR-007: User Feedback Collection Design

**Status:** Accepted  
**Date:** 2024-01-15  
**Deciders:** SpanForge Core Team

---

## Context

LLM response quality cannot be assessed fully through automated metrics alone.
Explicit user feedback — whether a thumbs-up, a star rating, or a free-text
comment — is a primary signal for alignment and trust evaluation.

SpanForge needs a standard way to:

1. Collect multi-modal user feedback (binary, ordinal, free-text).
2. Correlate feedback records with specific LLM traces and sessions.
3. Optionally link feedback to T.R.U.S.T. dimensions for scoring.
4. Provide privacy guarantees over free-text content and user identifiers.
5. Aggregate feedback into session summaries for monitoring dashboards.

The user feedback feature (Phase 13, F-21) must follow SpanForge conventions
for local-first operation (ADR-004), singleton clients (ADR-002), and the `llm.*`
event namespace.

---

## Decision

### Namespace

Introduce a new `llm.feedback.*` namespace under `spanforge.namespaces.feedback`:

| Event | Payload class | Trigger |
|-------|---------------|---------|
| `llm.feedback.submitted` | `FeedbackSubmittedPayload` | `sf_feedback.submit()` |
| `llm.feedback.summary` | `FeedbackSummaryPayload` | `sf_feedback.get_summary()` |
| `llm.feedback.trust_linked` | *(event dict)* | `sf_feedback.link_to_trust()` |

### Rating modalities

A `FeedbackRating` enum models all supported modalities:

| Modality | Values | Use case |
|----------|--------|----------|
| Thumbs | `THUMBS_UP`, `THUMBS_DOWN` | Binary quick feedback |
| Star | `STAR_1` – `STAR_5` | 1–5 scale quality rating |
| Likert | `LIKERT_1` – `LIKERT_5` | Agreement / satisfaction scale |
| Free-text | `FREE_TEXT` | Open-ended qualitative comment |

All ordinal ratings expose `numeric_value() → float | None` normalised to `[0.0, 1.0]`
for uniform aggregation. `FREE_TEXT` returns `None`.

### SDK client

A new `SFFeedbackClient` follows the `SFServiceClient` base class pattern (ADR-002)
and is registered as the `sf_feedback` module-level singleton.

### Privacy

Free-text comments and user identifiers are privacy-sensitive. The decision is:

- **Comment text:** SHA-256 hashed before storage; raw text is never persisted. Field name is `comment_hash` to make this explicit in the event schema.
- **User ID:** SHA-256 hashed before storage; field name is `user_id_hash`.
- **Session ID / Trace ID:** Stored as-is. Callers must not embed PII in these identifiers.

SHA-256 is non-reversible and sufficient for event correlation without exposing
identifiable content, consistent with the RAG tracing privacy model (ADR-006).

### T.R.U.S.T. linkage

The five T.R.U.S.T. dimensions (`transparency`, `reliability`, `user_trust`,
`security`, `traceability`) can be enriched with direct user feedback signals.
The `linked_trust_dimension` field on `FeedbackSubmittedPayload` and the
`link_to_trust()` method on `SFFeedbackClient` emit a `llm.feedback.trust_linked`
event that the T.R.U.S.T. scorecard can consume.

---

## Alternatives considered

### A. Generic key-value feedback schema

Rejected. A free-form schema cannot provide typed `numeric_value()` aggregation
or validated T.R.U.S.T. dimension references. The enum-based approach enables
`positive_rate` and average score computation without post-hoc parsing.

### B. Store raw comments with encryption at rest

Rejected. Encryption introduces key management complexity and does not eliminate
the GDPR right-to-erasure obligation. Hashing is simpler, fully irreversible,
and still enables deduplication and volume counting.

### C. Separate feedback store independent of the SpanForge event bus

Rejected. Routing feedback through the standard SpanForge event pipeline (`_emit_local`)
ensures that all feedback records participate in existing export, audit, and
compliance pipelines. Bespoke storage would fragment observability data.

---

## Consequences

**Positive:**
- Unified feedback collection with privacy-by-design.
- Numeric aggregation across all modalities via `FeedbackRating.numeric_value()`.
- Direct T.R.U.S.T. integration enables feedback-driven trust scoring.
- Session summaries (`get_summary()`) provide real-time positive_rate metrics.

**Negative:**
- Free-text comments are not retrievable after submission — only the hash survives.
- `get_summary()` computes aggregates in-process from the in-memory store; it does
  not query a remote backend. Production deployments should configure an export
  backend to persist feedback events.
- Valid `linked_trust_dimension` values are validated at SDK level; invalid values
  raise `ValueError` at runtime.

---

## References

- [ADR-002 Singleton Service Clients](ADR-002-singleton-service-clients.md)
- [ADR-004 Local-First Architecture](ADR-004-local-first-architecture.md)
- [ADR-006 RAG Tracing Design](ADR-006-rag-tracing.md)
- [`spanforge.sdk.feedback` API reference](../api/feedback.md)
- [`spanforge.namespaces.feedback`](../namespaces/feedback.md)
