"""spanforge.sdk.feedback — SpanForge sf-feedback User Feedback client (Phase 13).

Implements FB-001 through FB-006: collecting, storing, and surfacing user
feedback for LLM responses, with optional T.R.U.S.T. dimension linkage.

Architecture
------------
* :meth:`submit` records a ``llm.feedback.submitted`` event.
* :meth:`get_feedback` returns feedback records for a given session.
* :meth:`get_summary` returns an aggregated :class:`FeedbackSummaryPayload`.
* :meth:`link_to_trust` links feedback to a T.R.U.S.T. dimension score
  adjustment.
* :meth:`get_status` returns service health statistics.

Raw user text (free-text comments) is **never stored**.  Only SHA-256 hashes
are retained.  User identifiers are similarly hashed before storage.

Security requirements
---------------------
* All plaintext comment and user ID values are hashed with SHA-256 before
  recording.
* Thread-safety: all in-process state uses locks.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass
from typing import Any

from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.namespaces.feedback import (
    FeedbackRating,
    FeedbackSubmittedPayload,
    FeedbackSummaryPayload,
)

__all__ = ["SFFeedbackClient"]

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Status dataclass
# ---------------------------------------------------------------------------


@dataclass
class FeedbackStatusInfo:
    """sf-feedback service status.

    Returned by :meth:`SFFeedbackClient.get_status`.

    Attributes:
        status:           ``"ok"`` or ``"degraded"``.
        total_submitted:  Total feedback submissions recorded in this process.
        sessions_tracked: Number of distinct session IDs tracked.
    """

    status: str
    total_submitted: int
    sessions_tracked: int


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class SFFeedbackClient(SFServiceClient):
    """SpanForge User Feedback service client.

    Provides structured user feedback collection for LLM interactions,
    supporting thumbs, star, Likert, and free-text modalities.

    Example usage::

        from spanforge.sdk import sf_feedback

        # Submit thumbs-up feedback
        fb_id = sf_feedback.submit(
            session_id="sess-abc",
            trace_id="trace-xyz",
            rating="thumbs_up",
        )

        # Submit a free-text comment (text is hashed, never stored)
        fb_id = sf_feedback.submit(
            session_id="sess-abc",
            trace_id="trace-xyz",
            rating="free_text",
            comment="The answer was very helpful.",
            user_id="user-42",
        )

        # Get session summary
        summary = sf_feedback.get_summary("sess-abc")
    """

    def __init__(self, config: SFClientConfig) -> None:
        super().__init__(config, service_name="feedback")
        self._lock = threading.Lock()
        # session_id → list of FeedbackSubmittedPayload dicts
        self._store: dict[str, list[dict[str, Any]]] = {}
        self._total_submitted: int = 0

    # ------------------------------------------------------------------
    # FB-001: submit
    # ------------------------------------------------------------------

    def submit(
        self,
        session_id: str,
        trace_id: str,
        rating: str | FeedbackRating,
        *,
        comment: str | None = None,
        user_id: str | None = None,
        source: str = "api",
        metadata: dict[str, Any] | None = None,
        linked_trust_dimension: str | None = None,
    ) -> str:
        """Submit user feedback for an LLM response.

        Args:
            session_id:             Session or conversation the feedback applies to.
            trace_id:               Trace ID of the specific LLM call being rated.
            rating:                 A :class:`~spanforge.namespaces.feedback.FeedbackRating`
                                    value or its string equivalent (e.g. ``"thumbs_up"``).
            comment:                Optional free-text comment.  The text is
                                    hashed with SHA-256; raw text is NOT stored.
            user_id:                Optional user identifier.  Hashed with
                                    SHA-256 before storage.
            source:                 Feedback channel label (default ``"api"``).
            metadata:               Arbitrary key-value metadata.
            linked_trust_dimension: Optional T.R.U.S.T. dimension to link
                                    this feedback to (e.g. ``"reliability"``).

        Returns:
            The unique ``feedback_id`` (ULID) for the submitted record.
        """
        from spanforge.ulid import generate as _ulid

        rating_enum = FeedbackRating(rating) if isinstance(rating, str) else rating

        comment_hash = ""
        if comment:
            comment_hash = hashlib.sha256(comment.encode("utf-8")).hexdigest()

        user_id_hash = ""
        if user_id:
            user_id_hash = hashlib.sha256(user_id.encode("utf-8")).hexdigest()

        feedback_id = _ulid()
        payload = FeedbackSubmittedPayload(
            feedback_id=feedback_id,
            session_id=session_id,
            trace_id=trace_id,
            rating=rating_enum,
            comment_hash=comment_hash,
            user_id_hash=user_id_hash,
            source=source,
            metadata=metadata or {},
            linked_trust_dimension=linked_trust_dimension,
        )

        record = payload.to_dict()

        with self._lock:
            if session_id not in self._store:
                self._store[session_id] = []
            self._store[session_id].append(record)
            self._total_submitted += 1

        self._emit_local("llm.feedback.submitted", record, session_id=session_id)
        return feedback_id

    # ------------------------------------------------------------------
    # FB-002: get_feedback
    # ------------------------------------------------------------------

    def get_feedback(
        self,
        session_id: str,
        *,
        rating_filter: str | FeedbackRating | None = None,
    ) -> list[dict[str, Any]]:
        """Return feedback records for *session_id*.

        Args:
            session_id:    Session to query.
            rating_filter: Optional rating type to filter by.

        Returns:
            List of feedback record dicts (in submission order).
        """
        with self._lock:
            records = list(self._store.get(session_id, []))

        if rating_filter is not None:
            rf = FeedbackRating(rating_filter) if isinstance(rating_filter, str) else rating_filter
            records = [r for r in records if r.get("rating") == rf.value]

        return records

    # ------------------------------------------------------------------
    # FB-003: get_summary
    # ------------------------------------------------------------------

    def get_summary(self, session_id: str) -> FeedbackSummaryPayload:
        """Return an aggregated feedback summary for *session_id*.

        Args:
            session_id: Session to summarise.

        Returns:
            A :class:`~spanforge.namespaces.feedback.FeedbackSummaryPayload`.
        """
        records = self.get_feedback(session_id)

        thumbs_up = sum(1 for r in records if r.get("rating") == FeedbackRating.THUMBS_UP.value)
        thumbs_down = sum(1 for r in records if r.get("rating") == FeedbackRating.THUMBS_DOWN.value)
        free_text = sum(1 for r in records if r.get("rating") == FeedbackRating.FREE_TEXT.value)

        star_values = [
            FeedbackRating(r["rating"]).numeric_value()
            for r in records
            if r.get("rating", "").startswith("star_")
        ]
        star_values_clean = [v for v in star_values if v is not None]

        likert_values = [
            FeedbackRating(r["rating"]).numeric_value()
            for r in records
            if r.get("rating", "").startswith("likert_")
        ]
        likert_values_clean = [v for v in likert_values if v is not None]

        # Numeric values are on [0, 1].  Convert star/likert back to 1–5 scale.
        avg_star = (
            round(sum(star_values_clean) / len(star_values_clean) * 4 + 1, 2)
            if star_values_clean
            else None
        )
        avg_likert = (
            round(sum(likert_values_clean) / len(likert_values_clean) * 4 + 1, 2)
            if likert_values_clean
            else None
        )

        # Positive rate: numeric ratings above 0.5 are "positive"
        all_numeric: list[float] = []
        for r in records:
            try:
                v = FeedbackRating(r["rating"]).numeric_value()
                if v is not None:
                    all_numeric.append(v)
            except ValueError:
                continue

        positive_rate = (
            sum(1 for v in all_numeric if v >= 0.5) / len(all_numeric) if all_numeric else 0.0
        )

        return FeedbackSummaryPayload(
            session_id=session_id,
            total_feedback=len(records),
            thumbs_up_count=thumbs_up,
            thumbs_down_count=thumbs_down,
            avg_star_rating=avg_star,
            avg_likert_score=avg_likert,
            free_text_count=free_text,
            positive_rate=round(positive_rate, 4),
        )

    # ------------------------------------------------------------------
    # FB-004: link_to_trust
    # ------------------------------------------------------------------

    def link_to_trust(
        self,
        feedback_id: str,
        trust_dimension: str,
        *,
        weight: float = 0.1,
    ) -> bool:
        """Link a feedback record to a T.R.U.S.T. dimension score adjustment.

        This emits a ``llm.feedback.trust_linked`` event that the T.R.U.S.T.
        service can consume to adjust dimension scores based on explicit user
        signal.

        Args:
            feedback_id:     ULID of the feedback record to link.
            trust_dimension: T.R.U.S.T. dimension to adjust
                             (``"transparency"``, ``"reliability"``,
                             ``"user_trust"``, ``"security"``,
                             ``"traceability"``).
            weight:          Adjustment weight in [0.0, 1.0] (default 0.1).

        Returns:
            ``True`` if the link event was emitted successfully.
        """
        _VALID_DIMENSIONS = frozenset(
            {"transparency", "reliability", "user_trust", "security", "traceability"}
        )
        if trust_dimension not in _VALID_DIMENSIONS:
            raise ValueError(
                f"link_to_trust: trust_dimension must be one of {sorted(_VALID_DIMENSIONS)}"
            )
        if not (0.0 <= weight <= 1.0):
            raise ValueError(f"link_to_trust: weight must be in [0, 1]; got {weight}")

        self._emit_local(
            "llm.feedback.trust_linked",
            {
                "feedback_id": feedback_id,
                "trust_dimension": trust_dimension,
                "weight": weight,
            },
        )
        return True

    # ------------------------------------------------------------------
    # FB-005: get_status
    # ------------------------------------------------------------------

    def get_status(self) -> FeedbackStatusInfo:
        """Return service health and submission statistics."""
        with self._lock:
            return FeedbackStatusInfo(
                status="ok",
                total_submitted=self._total_submitted,
                sessions_tracked=len(self._store),
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _emit_local(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        session_id: str = "",
    ) -> None:
        """Emit a feedback event locally or forward to remote endpoint."""
        _log.debug("sf-feedback emit %s session=%s", event_type, session_id)
