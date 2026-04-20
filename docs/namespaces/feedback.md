# Namespace: `llm.feedback.*` — User Feedback Payloads

> **Module:** `spanforge.namespaces.feedback`  
> **Added in:** 2.0.12 (Phase 13)  
> **Events covered:** `llm.feedback.submitted`, `llm.feedback.summary`

This namespace covers payload types for collecting and aggregating user feedback
on LLM responses. Use [`spanforge.sdk.feedback`](../api/feedback.md) to emit these
events without constructing the dataclasses directly.

---

## Classes

| Class | Event | Description |
|-------|-------|-------------|
| `FeedbackRating` | *(enum)* | Supported rating modalities |
| `FeedbackSubmittedPayload` | `llm.feedback.submitted` | A single feedback submission |
| `FeedbackSummaryPayload` | `llm.feedback.summary` | Aggregated feedback for a session or window |

---

## `FeedbackRating`

```python
class FeedbackRating(str, Enum)
```

Supported user feedback rating modalities. All values are also valid as plain strings
when passed to `sf_feedback.submit()`.

| Value | String | Numeric value (`numeric_value()`) | Description |
|-------|--------|----------------------------------|-------------|
| `THUMBS_UP` | `"thumbs_up"` | `1.0` | Binary positive feedback |
| `THUMBS_DOWN` | `"thumbs_down"` | `0.0` | Binary negative feedback |
| `STAR_1` | `"star_1"` | `0.0` | 1 out of 5 stars |
| `STAR_2` | `"star_2"` | `0.25` | 2 out of 5 stars |
| `STAR_3` | `"star_3"` | `0.5` | 3 out of 5 stars |
| `STAR_4` | `"star_4"` | `0.75` | 4 out of 5 stars |
| `STAR_5` | `"star_5"` | `1.0` | 5 out of 5 stars |
| `LIKERT_1` | `"likert_1"` | `0.0` | Strongly disagree |
| `LIKERT_2` | `"likert_2"` | `0.25` | Disagree |
| `LIKERT_3` | `"likert_3"` | `0.5` | Neutral |
| `LIKERT_4` | `"likert_4"` | `0.75` | Agree |
| `LIKERT_5` | `"likert_5"` | `1.0` | Strongly agree |
| `FREE_TEXT` | `"free_text"` | `None` | Open-ended qualitative comment |

### `numeric_value() -> float | None`

Returns a normalised `0.0–1.0` value for ratings that have one, or `None` for
`FREE_TEXT`.

- Thumbs: `THUMBS_UP → 1.0`, `THUMBS_DOWN → 0.0`
- Star / Likert: `(value - 1) / 4` mapped to `[0.0, 1.0]`

```python
from spanforge.namespaces.feedback import FeedbackRating

FeedbackRating.STAR_4.numeric_value()   # 0.75
FeedbackRating.LIKERT_3.numeric_value() # 0.5
FeedbackRating.THUMBS_UP.numeric_value() # 1.0
FeedbackRating.FREE_TEXT.numeric_value() # None
```

---

## `FeedbackSubmittedPayload`

Payload for `llm.feedback.submitted` events.

```python
@dataclass
class FeedbackSubmittedPayload:
    feedback_id: str
    session_id: str
    trace_id: str
    rating: FeedbackRating
    comment_hash: str = ""
    user_id_hash: str = ""
    source: str = "api"
    metadata: dict[str, Any] = field(default_factory=dict)
    linked_trust_dimension: str | None = None
```

| Field | Type | Validation | Description |
|-------|------|-----------|-------------|
| `feedback_id` | `str` | non-empty | Unique feedback record identifier (ULID) |
| `session_id` | `str` | non-empty | Session or conversation this feedback belongs to |
| `trace_id` | `str` | — | Trace ID of the specific LLM call being rated |
| `rating` | `FeedbackRating` | valid enum | The feedback rating type |
| `comment_hash` | `str` | — | SHA-256 hex digest of free-text comment; `""` when no comment |
| `user_id_hash` | `str` | — | SHA-256 hex digest of the user identifier; `""` for anonymous submissions |
| `source` | `str` | — | Feedback channel (e.g. `"api"`, `"ui"`, `"email"`) |
| `metadata` | `dict` | — | Arbitrary key-value metadata |
| `linked_trust_dimension` | `str \| None` | — | T.R.U.S.T. dimension (`"transparency"`, `"reliability"`, `"user_trust"`, `"security"`, `"traceability"`) |

> **Privacy:** Raw comment text and user IDs are **never stored**. Only their SHA-256
> hashes are persisted, making it impossible to recover the original values.

**Methods:** `to_dict() -> dict`, `from_dict(data: dict) -> FeedbackSubmittedPayload`

---

## `FeedbackSummaryPayload`

Payload for `llm.feedback.summary` events. Aggregated feedback statistics over
a session or time window.

```python
@dataclass
class FeedbackSummaryPayload:
    session_id: str
    total_feedback: int = 0
    thumbs_up_count: int = 0
    thumbs_down_count: int = 0
    avg_star_rating: float | None = None
    avg_likert_score: float | None = None
    free_text_count: int = 0
    positive_rate: float = 0.0
```

| Field | Type | Validation | Description |
|-------|------|-----------|-------------|
| `session_id` | `str` | non-empty | Session or aggregation window identifier |
| `total_feedback` | `int` | — | Total feedback events in the window |
| `thumbs_up_count` | `int` | — | Count of `THUMBS_UP` ratings |
| `thumbs_down_count` | `int` | — | Count of `THUMBS_DOWN` ratings |
| `avg_star_rating` | `float \| None` | — | Mean star rating (1–5); `None` if no star ratings |
| `avg_likert_score` | `float \| None` | — | Mean Likert score (1–5); `None` if no Likert ratings |
| `free_text_count` | `int` | — | Number of free-text comments submitted |
| `positive_rate` | `float` | `[0.0, 1.0]` | Fraction of positive feedback across all numeric ratings |

**Methods:** `to_dict() -> dict`, `from_dict(data: dict) -> FeedbackSummaryPayload`

---

## Usage example

```python
from spanforge.namespaces.feedback import FeedbackRating

# Prefer the high-level client:
from spanforge.sdk import sf_feedback

fb_id = sf_feedback.submit(
    session_id="sess-abc",
    trace_id="trace-xyz",
    rating=FeedbackRating.STAR_4,
)
summary = sf_feedback.get_summary("sess-abc")
print(summary.avg_star_rating)   # 4.0
print(summary.positive_rate)     # 0.75
```

---

## Related

- [sf-feedback SDK client](../api/feedback.md)
- [User Guide — User Feedback](../user_guide/feedback.md)
- [Retrieval namespace](retrieval.md)
