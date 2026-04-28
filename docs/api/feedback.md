# spanforge.sdk.feedback — User Feedback Client

> **Module:** `spanforge.sdk.feedback`  
> **Added in:** 2.0.12 (Phase 13 — RAG Tracing & User Feedback)  
> **Import:** `from spanforge.sdk import sf_feedback` or `from spanforge.sdk.feedback import SFFeedbackClient`

`spanforge.sdk.feedback` provides structured collection of user feedback for LLM
responses. It supports thumbs, star rating, Likert scale, and free-text modalities.
Raw comment text and user identifiers are **never stored**; only SHA-256 hashes
are retained.

---

## Quick example

```python
from spanforge.sdk import sf_feedback

# Thumbs-up feedback
feedback_id = sf_feedback.submit(
    session_id="sess-abc",
    trace_id="trace-xyz",
    rating="thumbs_up",
)

# Free-text feedback (raw text is hashed, not stored)
feedback_id = sf_feedback.submit(
    session_id="sess-abc",
    trace_id="trace-xyz",
    rating="free_text",
    comment="The answer was very helpful.",
    user_id="user-42",
)

# Get all feedback for a session
records = sf_feedback.get_feedback("sess-abc")

# Aggregate summary
summary = sf_feedback.get_summary("sess-abc")
print(summary.total_feedback)   # 2
print(summary.positive_count)   # 1
```

---

## Singleton

`spanforge.sdk.sf_feedback` is a module-level `SFFeedbackClient` instance:

```python
from spanforge.sdk import sf_feedback
```

To construct a custom instance:

```python
from spanforge.sdk.feedback import SFFeedbackClient
from spanforge.sdk._base import SFClientConfig

client = SFFeedbackClient(SFClientConfig(api_key="..."))
```

---

## Security model

| Data | Stored as |
|------|-----------|
| Free-text comment | **Never stored** — SHA-256 hash only (`comment_hash`) |
| `user_id` | **Never stored** — SHA-256 hash only (`user_id_hash`) |
| `rating` | Stored as a `FeedbackRating` enum value string |
| `session_id` / `trace_id` | Stored as-is — should not contain PII |

---

## `FeedbackStatusInfo`

```python
@dataclass
class FeedbackStatusInfo:
    status: str
    total_submitted: int
    sessions_tracked: int
```

Returned by `SFFeedbackClient.get_status()`.

| Field | Description |
|-------|-------------|
| `status` | `"ok"` or `"degraded"` |
| `total_submitted` | Total feedback records submitted in this process lifetime |
| `sessions_tracked` | Number of distinct session IDs that have feedback |

---

## `SFFeedbackClient`

```python
class SFFeedbackClient(SFServiceClient)
```

Thread-safe user feedback service client.

### Constructor

```python
SFFeedbackClient(config: SFClientConfig)
```

---

### `submit(session_id, trace_id, rating, *, comment=None, user_id=None, source="api", metadata=None, linked_trust_dimension=None) -> str`

Submit user feedback for an LLM response.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | `str` | *(required)* | Session or conversation the feedback belongs to. |
| `trace_id` | `str` | *(required)* | Trace ID of the specific LLM call being rated. |
| `rating` | `str \| FeedbackRating` | *(required)* | A `FeedbackRating` value or its string equivalent (e.g. `"thumbs_up"`, `"star_4"`, `"likert_3"`). |
| `comment` | `str \| None` | `None` | Optional free-text comment. SHA-256 hashed — raw text is NOT stored. |
| `user_id` | `str \| None` | `None` | Optional user identifier. SHA-256 hashed before storage. |
| `source` | `str` | `"api"` | Feedback channel label (e.g. `"api"`, `"ui"`, `"email"`). |
| `metadata` | `dict \| None` | `None` | Arbitrary key-value metadata. |
| `linked_trust_dimension` | `str \| None` | `None` | Optional T.R.U.S.T. dimension to link this feedback to. Valid values: `"transparency"`, `"reliability"`, `"user_trust"`, `"security"`, `"traceability"`. |

**Returns:** `str` — the unique `feedback_id` (ULID) for the submitted record.

**Emits:** `llm.feedback.submitted` event.

---

### `get_feedback(session_id, *, rating_filter=None) -> list[dict]`

Return feedback records for a session.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `session_id` | `str` | *(required)* | Session to query. |
| `rating_filter` | `str \| FeedbackRating \| None` | `None` | Filter by rating type (e.g. `"thumbs_up"`). Returns all records when omitted. |

**Returns:** `list[dict]` — feedback records in submission order (the dict form of `FeedbackSubmittedPayload`).

---

### `get_summary(session_id) -> FeedbackSummaryPayload`

Return an aggregated feedback summary for a session.

**Returns:** [`FeedbackSummaryPayload`](../namespaces/feedback.md#feedbacksummarypayload) with
`total_feedback`, `positive_count`, `negative_count`, `neutral_count`,
`avg_numeric_score`, and `free_text_count`.

---

### `link_to_trust(feedback_id, trust_dimension, *, session_id="") -> bool`

Link an existing feedback record to a T.R.U.S.T. dimension.

| Parameter | Type | Description |
|-----------|------|-------------|
| `feedback_id` | `str` | The `feedback_id` returned by `submit()`. |
| `trust_dimension` | `str` | T.R.U.S.T. dimension key: `"transparency"`, `"reliability"`, `"user_trust"`, `"security"`, or `"traceability"`. |
| `session_id` | `str` | Session scope for event routing. |

**Returns:** `True` if the link event was emitted successfully, `False` otherwise.

**Raises:** `ValueError` — if `trust_dimension` is not a valid T.R.U.S.T. dimension.

---

### `get_status() -> FeedbackStatusInfo`

Return service health and feedback statistics.

```python
status = sf_feedback.get_status()
print(status.status)            # "ok"
print(status.total_submitted)   # 27
print(status.sessions_tracked)  # 5
```

---

## T.R.U.S.T. integration

Feedback can be linked to any of the five T.R.U.S.T. dimensions using `linked_trust_dimension`
at submission time, or by calling `link_to_trust()` after the fact:

```python
# At submission time
sf_feedback.submit(
    session_id="sess-abc",
    trace_id="trace-xyz",
    rating="thumbs_down",
    linked_trust_dimension="reliability",
)

# Post-submission linkage
sf_feedback.link_to_trust(
    feedback_id=fb_id,
    trust_dimension="user_trust",
    session_id="sess-abc",
)
```

---

## HTTP endpoint — `POST /v1/feedback`

> **Added in:** 1.0.0 (F-21)

When the embedded spanforge HTTP server is running (`spanforge serve`), user
feedback can be submitted directly via REST without importing the SDK.

### Request

```
POST /v1/feedback
Content-Type: application/json
```

**Body fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `session_id` | `str` | ✅ | Session / conversation identifier. |
| `trace_id` | `str` | ✅ | Trace ID of the specific LLM call being rated. |
| `rating` | `int` \| `str` | ✅ | Numeric rating `1`–`5`, or a `FeedbackRating` string. |
| `comment` | `str` | — | Free-text comment. Hashed before storage. |
| `user_id` | `str` | — | User identifier. Hashed before storage. |
| `source` | `str` | — | Feedback source label (default `"api"`). |
| `metadata` | `dict` | — | Arbitrary key-value metadata. |
| `linked_trust_dimension` | `str` | — | T.R.U.S.T. dimension link (`"reliability"`, etc.). |

### Response

**HTTP 201 Created**

```json
{
  "feedback_id": "01JXXXXXXXXXXXXXXXXXX",
  "accepted": true
}
```

### Example

```bash
curl -X POST http://localhost:7654/v1/feedback \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "sess-abc",
    "trace_id": "trace-xyz",
    "rating": 4,
    "comment": "Very helpful response.",
    "user_id": "user-42",
    "linked_trust_dimension": "reliability"
  }'
# → {"feedback_id": "01JXXXXXXXXXXXXXXXXXX", "accepted": true}
```

---

## Related

- [Namespace payloads — `spanforge.namespaces.feedback`](../namespaces/feedback.md)
- [RAG Tracing — `spanforge.sdk.rag`](rag.md)
- [T.R.U.S.T. Scorecard — `spanforge.sdk.trust`](trust.md)
- [User Guide — User Feedback](../user_guide/feedback.md)
