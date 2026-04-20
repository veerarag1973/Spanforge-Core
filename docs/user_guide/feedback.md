# User Feedback

SpanForge `sf_feedback` collects structured user feedback on LLM responses.
It supports four rating modalities — thumbs, star, Likert, and free-text — and
optionally links feedback to specific T.R.U.S.T. dimensions.

## Privacy by design

All user-identifiable data is hashed before storage:

| What you provide | What SpanForge stores |
|------------------|-----------------------|
| `comment` text | SHA-256 hash only — raw text is **never** stored |
| `user_id` | SHA-256 hash only |
| `session_id`, `trace_id` | Stored as-is — keep these PII-free |
| `rating` enum value | Stored as string |

---

## Import

```python
from spanforge.sdk import sf_feedback
```

---

## Submitting feedback

### Thumbs up / down

```python
# Thumbs-up
feedback_id = sf_feedback.submit(
    session_id="sess-abc",
    trace_id="trace-001",
    rating="thumbs_up",
)

# Thumbs-down with context
feedback_id = sf_feedback.submit(
    session_id="sess-abc",
    trace_id="trace-001",
    rating="thumbs_down",
    source="chat-ui",
    metadata={"page": "/assistant", "variant": "A"},
)
```

### Star rating

```python
feedback_id = sf_feedback.submit(
    session_id="sess-abc",
    trace_id="trace-001",
    rating="star_4",   # 1–5: star_1 to star_5
)
```

### Likert scale

```python
feedback_id = sf_feedback.submit(
    session_id="sess-abc",
    trace_id="trace-001",
    rating="likert_5",   # 1–5: likert_1 to likert_5
)
```

### Free-text comment

Raw comment text is SHA-256 hashed before storage — the original text cannot be recovered.

```python
feedback_id = sf_feedback.submit(
    session_id="sess-abc",
    trace_id="trace-001",
    rating="free_text",
    comment="The answer was concise and accurate.",
    user_id="user-42",   # also hashed
)
```

---

## Reading feedback

### All records for a session

```python
records = sf_feedback.get_feedback("sess-abc")
# Returns list of dict — one per submitted feedback
for r in records:
    print(r["rating"], r["comment_hash"])
```

### Filter by rating type

```python
thumbs = sf_feedback.get_feedback("sess-abc", rating_filter="thumbs_up")
```

---

## Session summary

```python
summary = sf_feedback.get_summary("sess-abc")
print(summary.total_feedback)    # 5
print(summary.thumbs_up_count)   # 3
print(summary.thumbs_down_count) # 1
print(summary.free_text_count)   # 1
print(summary.positive_rate)     # 0.75
print(summary.avg_star_rating)   # None (no star ratings this session)
```

`positive_rate` is computed from all numeric ratings above the neutral threshold.

---

## T.R.U.S.T. integration

Link feedback to a T.R.U.S.T. dimension at submission time:

```python
feedback_id = sf_feedback.submit(
    session_id="sess-abc",
    trace_id="trace-001",
    rating="thumbs_down",
    linked_trust_dimension="reliability",  # affects T.R.U.S.T. reliability score
)
```

Valid dimensions: `"transparency"`, `"reliability"`, `"user_trust"`, `"security"`, `"traceability"`.

Or link after the fact with `link_to_trust()`:

```python
success = sf_feedback.link_to_trust(
    feedback_id=feedback_id,
    trust_dimension="user_trust",
    session_id="sess-abc",
)
```

---

## Using `FeedbackRating` enum directly

```python
from spanforge.namespaces.feedback import FeedbackRating

# All rating values:
print(list(FeedbackRating))

# Get numeric score (0.0–1.0)
print(FeedbackRating.STAR_4.numeric_value())   # 0.75
print(FeedbackRating.LIKERT_3.numeric_value()) # 0.5
print(FeedbackRating.FREE_TEXT.numeric_value()) # None

# Pass enum to submit()
sf_feedback.submit("sess-abc", "trace-001", rating=FeedbackRating.THUMBS_UP)
```

---

## Service health

```python
status = sf_feedback.get_status()
print(status.status)            # "ok"
print(status.total_submitted)   # total count since process start
print(status.sessions_tracked)  # number of distinct sessions
```

---

## Thread safety

`SFFeedbackClient` is thread-safe. Session stores and counters are protected
by a `threading.Lock`.

---

## API reference

- [`spanforge.sdk.feedback.SFFeedbackClient`](../api/feedback.md)
- [`spanforge.namespaces.feedback`](../namespaces/feedback.md)
- [T.R.U.S.T. Scorecard](../api/trust.md)
