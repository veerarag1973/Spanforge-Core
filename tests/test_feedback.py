"""Tests for namespaces/feedback.py and sdk/feedback.py (F-42/F-43)."""

from __future__ import annotations

import pytest

from spanforge.namespaces.feedback import (
    FeedbackRating,
    FeedbackSubmittedPayload,
    FeedbackSummaryPayload,
)
from spanforge.sdk.feedback import FeedbackStatusInfo, SFFeedbackClient
from spanforge.sdk._base import SFClientConfig
from spanforge.sdk._types import SecretStr


# ---------------------------------------------------------------------------
# FeedbackRating
# ---------------------------------------------------------------------------


class TestFeedbackRating:
    def test_thumbs_numeric_values(self):
        assert FeedbackRating.THUMBS_UP.numeric_value() == 1.0
        assert FeedbackRating.THUMBS_DOWN.numeric_value() == 0.0

    def test_star_numeric_values(self):
        assert FeedbackRating.STAR_1.numeric_value() == 0.0
        assert FeedbackRating.STAR_3.numeric_value() == 0.5
        assert FeedbackRating.STAR_5.numeric_value() == 1.0

    def test_likert_numeric_values(self):
        assert FeedbackRating.LIKERT_1.numeric_value() == 0.0
        assert FeedbackRating.LIKERT_5.numeric_value() == 1.0

    def test_free_text_no_numeric(self):
        assert FeedbackRating.FREE_TEXT.numeric_value() is None

    def test_string_construction(self):
        r = FeedbackRating("thumbs_up")
        assert r == FeedbackRating.THUMBS_UP


# ---------------------------------------------------------------------------
# FeedbackSubmittedPayload
# ---------------------------------------------------------------------------


class TestFeedbackSubmittedPayload:
    def test_create(self):
        p = FeedbackSubmittedPayload(
            feedback_id="f1",
            session_id="s1",
            trace_id="t1",
            rating=FeedbackRating.THUMBS_UP,
        )
        assert p.feedback_id == "f1"
        assert p.comment_hash == ""

    def test_string_rating_coerced(self):
        p = FeedbackSubmittedPayload(
            feedback_id="f1", session_id="s1", trace_id="t1", rating="star_4"
        )
        assert p.rating == FeedbackRating.STAR_4

    def test_empty_feedback_id_raises(self):
        with pytest.raises(ValueError, match="feedback_id"):
            FeedbackSubmittedPayload(
                feedback_id="", session_id="s1", trace_id="t1", rating="thumbs_up"
            )

    def test_empty_session_id_raises(self):
        with pytest.raises(ValueError, match="session_id"):
            FeedbackSubmittedPayload(
                feedback_id="f1", session_id="", trace_id="t1", rating="thumbs_up"
            )

    def test_to_dict(self):
        p = FeedbackSubmittedPayload(
            feedback_id="f1",
            session_id="s1",
            trace_id="t1",
            rating=FeedbackRating.LIKERT_3,
            linked_trust_dimension="reliability",
        )
        d = p.to_dict()
        assert d["rating"] == "likert_3"
        assert d["linked_trust_dimension"] == "reliability"

    def test_from_dict_roundtrip(self):
        p = FeedbackSubmittedPayload(
            feedback_id="f1",
            session_id="s1",
            trace_id="t1",
            rating=FeedbackRating.STAR_5,
            comment_hash="abcdef",
            user_id_hash="112233",
        )
        p2 = FeedbackSubmittedPayload.from_dict(p.to_dict())
        assert p2.rating == FeedbackRating.STAR_5
        assert p2.comment_hash == "abcdef"

    def test_to_dict_no_trust_dimension(self):
        p = FeedbackSubmittedPayload(
            feedback_id="f1", session_id="s1", trace_id="t1", rating="thumbs_up"
        )
        d = p.to_dict()
        assert "linked_trust_dimension" not in d


# ---------------------------------------------------------------------------
# FeedbackSummaryPayload
# ---------------------------------------------------------------------------


class TestFeedbackSummaryPayload:
    def test_create(self):
        s = FeedbackSummaryPayload(session_id="s1", total_feedback=5, positive_rate=0.8)
        assert s.total_feedback == 5
        assert s.positive_rate == 0.8

    def test_empty_session_id_raises(self):
        with pytest.raises(ValueError, match="session_id"):
            FeedbackSummaryPayload(session_id="")

    def test_invalid_positive_rate_high(self):
        with pytest.raises(ValueError, match="positive_rate"):
            FeedbackSummaryPayload(session_id="s1", positive_rate=1.1)

    def test_invalid_positive_rate_low(self):
        with pytest.raises(ValueError, match="positive_rate"):
            FeedbackSummaryPayload(session_id="s1", positive_rate=-0.1)

    def test_to_dict_from_dict(self):
        s = FeedbackSummaryPayload(
            session_id="s1",
            total_feedback=3,
            avg_star_rating=4.2,
            avg_likert_score=3.8,
            positive_rate=0.75,
        )
        d = s.to_dict()
        s2 = FeedbackSummaryPayload.from_dict(d)
        assert s2.avg_star_rating == pytest.approx(4.2)
        assert s2.avg_likert_score == pytest.approx(3.8)

    def test_to_dict_no_optional_fields(self):
        s = FeedbackSummaryPayload(session_id="s1")
        d = s.to_dict()
        assert "avg_star_rating" not in d
        assert "avg_likert_score" not in d


# ---------------------------------------------------------------------------
# SFFeedbackClient
# ---------------------------------------------------------------------------


@pytest.fixture
def feedback_client():
    cfg = SFClientConfig(api_key=SecretStr("test"))
    return SFFeedbackClient(cfg)


class TestSFFeedbackClient:
    def test_submit_thumbs_up(self, feedback_client):
        fb_id = feedback_client.submit("sess-1", "trace-1", "thumbs_up")
        assert isinstance(fb_id, str) and len(fb_id) > 0

    def test_submit_with_comment(self, feedback_client):
        fb_id = feedback_client.submit(
            "sess-1", "trace-2", "free_text", comment="Very helpful!"
        )
        records = feedback_client.get_feedback("sess-1")
        # Comment should be hashed, not stored as plaintext
        for r in records:
            if r.get("feedback_id") == fb_id:
                assert "Very helpful!" not in str(r)
                assert len(r.get("comment_hash", "")) == 64  # SHA-256 hex

    def test_submit_with_user_id(self, feedback_client):
        fb_id = feedback_client.submit("sess-u", "trace-1", "star_5", user_id="user-42")
        records = feedback_client.get_feedback("sess-u")
        for r in records:
            if r.get("feedback_id") == fb_id:
                assert "user-42" not in str(r)
                assert len(r.get("user_id_hash", "")) == 64

    def test_submit_rating_enum(self, feedback_client):
        fb_id = feedback_client.submit("sess-e", "trace-1", FeedbackRating.LIKERT_4)
        assert fb_id

    def test_get_feedback_empty_session(self, feedback_client):
        assert feedback_client.get_feedback("nonexistent") == []

    def test_get_feedback_with_filter(self, feedback_client):
        feedback_client.submit("sess-f", "t1", "thumbs_up")
        feedback_client.submit("sess-f", "t2", "thumbs_down")
        thumbs_up = feedback_client.get_feedback("sess-f", rating_filter="thumbs_up")
        assert all(r["rating"] == "thumbs_up" for r in thumbs_up)
        assert len(thumbs_up) == 1

    def test_get_summary_all_types(self, feedback_client):
        feedback_client.submit("sess-sum", "t1", "thumbs_up")
        feedback_client.submit("sess-sum", "t2", "thumbs_down")
        feedback_client.submit("sess-sum", "t3", "star_4")
        feedback_client.submit("sess-sum", "t4", "likert_5")
        feedback_client.submit("sess-sum", "t5", "free_text", comment="test comment")

        summary = feedback_client.get_summary("sess-sum")
        assert summary.total_feedback == 5
        assert summary.thumbs_up_count == 1
        assert summary.thumbs_down_count == 1
        assert summary.free_text_count == 1
        assert summary.avg_star_rating == pytest.approx(4.0)
        assert summary.avg_likert_score == pytest.approx(5.0)
        assert 0.0 <= summary.positive_rate <= 1.0

    def test_get_summary_empty(self, feedback_client):
        summary = feedback_client.get_summary("empty-sess")
        assert summary.total_feedback == 0
        assert summary.positive_rate == 0.0

    def test_link_to_trust_valid(self, feedback_client):
        fb_id = feedback_client.submit("sess-t", "trace-1", "thumbs_up")
        assert feedback_client.link_to_trust(fb_id, "reliability", weight=0.2) is True

    def test_link_to_trust_invalid_dimension(self, feedback_client):
        with pytest.raises(ValueError, match="trust_dimension"):
            feedback_client.link_to_trust("any_id", "invalid_dimension")

    def test_link_to_trust_invalid_weight(self, feedback_client):
        with pytest.raises(ValueError, match="weight"):
            feedback_client.link_to_trust("any_id", "reliability", weight=1.5)

    def test_link_to_trust_all_dimensions(self, feedback_client):
        for dim in ("transparency", "reliability", "user_trust", "security", "traceability"):
            assert feedback_client.link_to_trust("fid", dim) is True

    def test_get_status(self, feedback_client):
        feedback_client.submit("sess-st", "trace-1", "star_3")
        status = feedback_client.get_status()
        assert isinstance(status, FeedbackStatusInfo)
        assert status.status == "ok"
        assert status.total_submitted >= 1
        assert status.sessions_tracked >= 1

    def test_multiple_sessions(self, feedback_client):
        feedback_client.submit("sess-a", "t1", "thumbs_up")
        feedback_client.submit("sess-b", "t2", "thumbs_down")
        status = feedback_client.get_status()
        assert status.sessions_tracked >= 2
