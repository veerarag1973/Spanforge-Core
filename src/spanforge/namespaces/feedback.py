"""spanforge.namespaces.feedback — User feedback namespace payload types.

Provides dataclasses for the ``llm.feedback.*`` event namespace, covering
all supported feedback rating modalities:

1. **Thumbs** — binary thumbs-up / thumbs-down feedback.
2. **Star** — 1–5 star rating.
3. **Likert** — 1–5 Likert scale response.
4. **Free-text** — open-ended qualitative comment (stored hashed, not raw).

Classes
-------
FeedbackRating
    Enum of supported rating types.
FeedbackSubmittedPayload
    ``llm.feedback.submitted`` events — the primary payload for any feedback.
FeedbackSummaryPayload
    ``llm.feedback.summary`` events — aggregated feedback for a session /
    trace / response.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "FeedbackRating",
    "FeedbackSubmittedPayload",
    "FeedbackSummaryPayload",
]


# ---------------------------------------------------------------------------
# Rating type enum
# ---------------------------------------------------------------------------


class FeedbackRating(str, Enum):
    """Supported feedback rating modalities.

    Attributes:
        THUMBS_UP:   Binary positive feedback.
        THUMBS_DOWN: Binary negative feedback.
        STAR_1:      1 out of 5 stars.
        STAR_2:      2 out of 5 stars.
        STAR_3:      3 out of 5 stars.
        STAR_4:      4 out of 5 stars.
        STAR_5:      5 out of 5 stars.
        LIKERT_1:    Strongly disagree (Likert 1/5).
        LIKERT_2:    Disagree (Likert 2/5).
        LIKERT_3:    Neutral (Likert 3/5).
        LIKERT_4:    Agree (Likert 4/5).
        LIKERT_5:    Strongly agree (Likert 5/5).
        FREE_TEXT:   Open-ended qualitative comment.
    """

    THUMBS_UP = "thumbs_up"
    THUMBS_DOWN = "thumbs_down"
    STAR_1 = "star_1"
    STAR_2 = "star_2"
    STAR_3 = "star_3"
    STAR_4 = "star_4"
    STAR_5 = "star_5"
    LIKERT_1 = "likert_1"
    LIKERT_2 = "likert_2"
    LIKERT_3 = "likert_3"
    LIKERT_4 = "likert_4"
    LIKERT_5 = "likert_5"
    FREE_TEXT = "free_text"

    def numeric_value(self) -> float | None:
        """Return a 0.0–1.0 normalised numeric value for ratings that have one.

        Returns ``None`` for :attr:`FREE_TEXT` (non-numeric).  Thumbs are
        mapped to ``0.0`` / ``1.0``; Star and Likert scales are mapped to
        their (value - 1) / 4 position on a 0–1 scale.
        """
        _map: dict[str, float] = {
            "thumbs_up": 1.0,
            "thumbs_down": 0.0,
            "star_1": 0.0,
            "star_2": 0.25,
            "star_3": 0.5,
            "star_4": 0.75,
            "star_5": 1.0,
            "likert_1": 0.0,
            "likert_2": 0.25,
            "likert_3": 0.5,
            "likert_4": 0.75,
            "likert_5": 1.0,
        }
        return _map.get(self.value)


# ---------------------------------------------------------------------------
# Payload dataclasses
# ---------------------------------------------------------------------------


@dataclass
class FeedbackSubmittedPayload:
    """Payload for ``llm.feedback.submitted`` events.

    Raw free-text comments are **never stored**; when *rating* is
    ``FeedbackRating.FREE_TEXT`` the *comment_hash* field holds the SHA-256
    digest of the comment text.

    Attributes:
        feedback_id:   Unique identifier for this feedback record (ULID).
        session_id:    Session or conversation this feedback applies to.
        trace_id:      Trace ID of the specific LLM call being rated.
        rating:        The :class:`FeedbackRating` value.
        comment_hash:  SHA-256 hex digest of the free-text comment, or ``""``
                       when *rating* is not ``FREE_TEXT``.
        user_id_hash:  SHA-256 hex digest of the user identifier, or ``""``
                       when the submission is anonymous.
        source:        Feedback collection channel (e.g. ``"widget"``,
                       ``"api"``, ``"email"``).
        metadata:      Arbitrary key-value metadata (e.g. page URL, A/B variant).
        linked_trust_dimension:
                       Optional T.R.U.S.T. dimension this feedback should
                       influence (e.g. ``"reliability"``).
    """

    feedback_id: str
    session_id: str
    trace_id: str
    rating: FeedbackRating
    comment_hash: str = ""
    user_id_hash: str = ""
    source: str = "api"
    metadata: dict[str, Any] = field(default_factory=dict)
    linked_trust_dimension: str | None = None

    def __post_init__(self) -> None:
        if not self.feedback_id:
            raise ValueError("FeedbackSubmittedPayload.feedback_id must be non-empty")
        if not self.session_id:
            raise ValueError("FeedbackSubmittedPayload.session_id must be non-empty")
        if not isinstance(self.rating, FeedbackRating):
            # Accept raw string values for convenience.
            self.rating = FeedbackRating(self.rating)

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        d: dict[str, Any] = {
            "feedback_id": self.feedback_id,
            "session_id": self.session_id,
            "trace_id": self.trace_id,
            "rating": self.rating.value,
            "comment_hash": self.comment_hash,
            "user_id_hash": self.user_id_hash,
            "source": self.source,
            "metadata": self.metadata,
        }
        if self.linked_trust_dimension is not None:
            d["linked_trust_dimension"] = self.linked_trust_dimension
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FeedbackSubmittedPayload":
        """Deserialise from a plain dict."""
        return cls(
            feedback_id=str(data["feedback_id"]),
            session_id=str(data["session_id"]),
            trace_id=str(data.get("trace_id", "")),
            rating=FeedbackRating(data["rating"]),
            comment_hash=str(data.get("comment_hash", "")),
            user_id_hash=str(data.get("user_id_hash", "")),
            source=str(data.get("source", "api")),
            metadata=dict(data.get("metadata", {})),
            linked_trust_dimension=data.get("linked_trust_dimension"),
        )


@dataclass
class FeedbackSummaryPayload:
    """Payload for ``llm.feedback.summary`` events.

    Aggregated feedback statistics over a session or time window.

    Attributes:
        session_id:       Session or aggregation window identifier.
        total_feedback:   Total number of feedback events in the window.
        thumbs_up_count:  Count of ``THUMBS_UP`` ratings.
        thumbs_down_count: Count of ``THUMBS_DOWN`` ratings.
        avg_star_rating:  Mean star rating (1–5); ``None`` if no star ratings.
        avg_likert_score: Mean Likert score (1–5); ``None`` if no Likert ratings.
        free_text_count:  Number of free-text comments submitted.
        positive_rate:    Fraction of positive feedback (0.0–1.0) — computed
                          from all numeric ratings above the neutral threshold.
    """

    session_id: str
    total_feedback: int = 0
    thumbs_up_count: int = 0
    thumbs_down_count: int = 0
    avg_star_rating: float | None = None
    avg_likert_score: float | None = None
    free_text_count: int = 0
    positive_rate: float = 0.0

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("FeedbackSummaryPayload.session_id must be non-empty")
        if not (0.0 <= self.positive_rate <= 1.0):
            raise ValueError(
                f"FeedbackSummaryPayload.positive_rate must be in [0, 1]; got {self.positive_rate}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        d: dict[str, Any] = {
            "session_id": self.session_id,
            "total_feedback": self.total_feedback,
            "thumbs_up_count": self.thumbs_up_count,
            "thumbs_down_count": self.thumbs_down_count,
            "free_text_count": self.free_text_count,
            "positive_rate": self.positive_rate,
        }
        if self.avg_star_rating is not None:
            d["avg_star_rating"] = self.avg_star_rating
        if self.avg_likert_score is not None:
            d["avg_likert_score"] = self.avg_likert_score
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FeedbackSummaryPayload":
        """Deserialise from a plain dict."""
        return cls(
            session_id=str(data["session_id"]),
            total_feedback=int(data.get("total_feedback", 0)),
            thumbs_up_count=int(data.get("thumbs_up_count", 0)),
            thumbs_down_count=int(data.get("thumbs_down_count", 0)),
            avg_star_rating=data.get("avg_star_rating"),
            avg_likert_score=data.get("avg_likert_score"),
            free_text_count=int(data.get("free_text_count", 0)),
            positive_rate=float(data.get("positive_rate", 0.0)),
        )
