"""Tests for namespaces/retrieval.py and sdk/rag.py (F-40/F-41)."""

from __future__ import annotations

import pytest

from spanforge.namespaces.retrieval import (
    RAGSessionPayload,
    RAGSpanPayload,
    RetrievalQueryPayload,
    RetrievalResultPayload,
    RetrievedChunk,
)
from spanforge.sdk import sf_rag
from spanforge.sdk.rag import RAGStatusInfo, SFRAGClient
from spanforge.sdk._base import SFClientConfig
from spanforge.sdk._types import SecretStr


# ---------------------------------------------------------------------------
# RetrievedChunk
# ---------------------------------------------------------------------------


class TestRetrievedChunk:
    def test_defaults(self):
        c = RetrievedChunk(chunk_id="c1", score=0.9, content_hash="abc", source="doc.md")
        assert c.chunk_id == "c1"
        assert c.score == 0.9
        assert c.metadata == {}

    def test_to_dict(self):
        c = RetrievedChunk(chunk_id="c1", score=0.5, content_hash="h", source="x")
        d = c.to_dict()
        assert d["chunk_id"] == "c1"
        assert d["score"] == 0.5

    def test_from_dict_roundtrip(self):
        c = RetrievedChunk(chunk_id="c2", score=0.7, content_hash="h2", source="y")
        c2 = RetrievedChunk.from_dict(c.to_dict())
        assert c2.chunk_id == "c2"
        assert c2.score == 0.7

    def test_invalid_score_low(self):
        with pytest.raises(ValueError, match="score"):
            RetrievedChunk(chunk_id="c", score=-0.1, content_hash="h", source="s")

    def test_invalid_score_high(self):
        with pytest.raises(ValueError, match="score"):
            RetrievedChunk(chunk_id="c", score=1.1, content_hash="h", source="s")

    def test_empty_chunk_id(self):
        with pytest.raises(ValueError, match="chunk_id"):
            RetrievedChunk(chunk_id="", score=0.5, content_hash="h", source="s")


# ---------------------------------------------------------------------------
# RetrievalQueryPayload
# ---------------------------------------------------------------------------


class TestRetrievalQueryPayload:
    def test_create(self):
        p = RetrievalQueryPayload(
            session_id="s1",
            query_hash="abc123",
            top_k=5,
            retriever_name="chroma",
        )
        assert p.top_k == 5
        assert p.filters == {}

    def test_to_dict_from_dict(self):
        p = RetrievalQueryPayload(
            session_id="s1",
            query_hash="abc123",
            top_k=3,
            retriever_name="qdrant",
        )
        d = p.to_dict()
        p2 = RetrievalQueryPayload.from_dict(d)
        assert p2.retriever_name == "qdrant"
        assert p2.top_k == 3

    def test_invalid_top_k(self):
        with pytest.raises(ValueError, match="top_k"):
            RetrievalQueryPayload(
                session_id="s1",
                query_hash="h",
                top_k=0,
                retriever_name="chroma",
            )

    def test_empty_session_id(self):
        with pytest.raises(ValueError, match="session_id"):
            RetrievalQueryPayload(session_id="", query_hash="h", retriever_name="chroma")

    def test_negative_latency_ms(self):
        with pytest.raises(ValueError, match="latency_ms"):
            RetrievalQueryPayload(
                session_id="s1",
                query_hash="h",
                retriever_name="chroma",
                latency_ms=-1.0,
            )


# ---------------------------------------------------------------------------
# RetrievalResultPayload
# ---------------------------------------------------------------------------


class TestRetrievalResultPayload:
    def test_create_with_chunks(self):
        chunks = [RetrievedChunk(chunk_id="c1", score=0.8, content_hash="h", source="d")]
        r = RetrievalResultPayload(
            session_id="s1",
            query_hash="h",
            chunks=chunks,
            total_found=1,
        )
        assert r.total_found == 1
        assert r.status == "ok"

    def test_to_dict_from_dict(self):
        r = RetrievalResultPayload(
            session_id="s1",
            query_hash="h",
            chunks=[],
            total_found=0,
        )
        d = r.to_dict()
        r2 = RetrievalResultPayload.from_dict(d)
        assert r2.session_id == "s1"
        assert r2.chunks == []

    def test_empty_session_id(self):
        with pytest.raises(ValueError, match="session_id"):
            RetrievalResultPayload(session_id="", query_hash="h")

    def test_invalid_status(self):
        with pytest.raises(ValueError, match="status"):
            RetrievalResultPayload(session_id="s1", query_hash="h", status="bad")  # type: ignore[arg-type]

    def test_negative_latency_ms(self):
        with pytest.raises(ValueError, match="latency_ms"):
            RetrievalResultPayload(session_id="s1", query_hash="h", latency_ms=-5.0)

    def test_error_message_in_to_dict(self):
        r = RetrievalResultPayload(
            session_id="s1",
            query_hash="h",
            status="error",
            error_message="timeout during retrieval",
        )
        d = r.to_dict()
        assert d["error_message"] == "timeout during retrieval"


# ---------------------------------------------------------------------------
# RAGSpanPayload
# ---------------------------------------------------------------------------


class TestRAGSpanPayload:
    def test_create(self):
        p = RAGSpanPayload(
            session_id="s1",
            span_name="gen",
            model="gpt-4o",
            chunk_ids_used=["c1"],
            context_tokens=500,
            prompt_tokens=100,
            output_tokens=50,
        )
        assert p.model == "gpt-4o"
        assert p.grounding_score is None

    def test_to_dict_from_dict(self):
        p = RAGSpanPayload(
            session_id="s1",
            span_name="gen",
            model="claude",
            chunk_ids_used=[],
            context_tokens=0,
            prompt_tokens=10,
            output_tokens=5,
            grounding_score=0.95,
        )
        d = p.to_dict()
        p2 = RAGSpanPayload.from_dict(d)
        assert p2.grounding_score == 0.95

    def test_invalid_grounding_score(self):
        with pytest.raises(ValueError, match="grounding_score"):
            RAGSpanPayload(
                session_id="s1",
                span_name="gen",
                model="m",
                chunk_ids_used=[],
                context_tokens=0,
                prompt_tokens=0,
                output_tokens=0,
                grounding_score=1.5,
            )

    def test_negative_latency_ms(self):
        with pytest.raises(ValueError, match="latency_ms"):
            RAGSpanPayload(
                session_id="s1",
                span_name="gen",
                model="m",
                chunk_ids_used=[],
                context_tokens=0,
                prompt_tokens=0,
                output_tokens=0,
                latency_ms=-1.0,
            )

    def test_invalid_status(self):
        with pytest.raises(ValueError, match="status"):
            RAGSpanPayload(
                session_id="s1",
                span_name="gen",
                model="m",
                chunk_ids_used=[],
                context_tokens=0,
                prompt_tokens=0,
                output_tokens=0,
                status="bad",  # type: ignore[arg-type]
            )

    def test_error_message_in_to_dict(self):
        p = RAGSpanPayload(
            session_id="s1",
            span_name="gen",
            model="m",
            chunk_ids_used=[],
            context_tokens=0,
            prompt_tokens=0,
            output_tokens=0,
            status="error",
            error_message="generation failed",
        )
        d = p.to_dict()
        assert d["error_message"] == "generation failed"


# ---------------------------------------------------------------------------
# RAGSessionPayload
# ---------------------------------------------------------------------------


class TestRAGSessionPayload:
    def test_create(self):
        p = RAGSessionPayload(session_id="s1", total_queries=2)
        assert p.total_queries == 2
        assert p.status == "ok"

    def test_to_dict_from_dict(self):
        p = RAGSessionPayload(
            session_id="s1",
            total_queries=3,
            avg_grounding_score=0.9,
            retriever_name="chroma",
        )
        d = p.to_dict()
        p2 = RAGSessionPayload.from_dict(d)
        assert p2.avg_grounding_score == 0.9

    def test_invalid_status(self):
        with pytest.raises(ValueError, match="status"):
            RAGSessionPayload(session_id="s1", status="unknown")  # type: ignore[arg-type]

    def test_invalid_avg_grounding_score(self):
        with pytest.raises(ValueError, match="avg_grounding_score"):
            RAGSessionPayload(session_id="s1", avg_grounding_score=1.5)


# ---------------------------------------------------------------------------
# SFRAGClient
# ---------------------------------------------------------------------------


@pytest.fixture
def rag_client():
    cfg = SFClientConfig(api_key=SecretStr("test"))
    return SFRAGClient(cfg)


class TestSFRAGClient:
    def test_trace_query_returns_session_id(self, rag_client):
        sid = rag_client.trace_query("What is AI?", top_k=3, retriever_name="chroma")
        assert isinstance(sid, str) and len(sid) > 0

    def test_trace_retrieval(self, rag_client):
        sid = rag_client.trace_query("test", top_k=1, retriever_name="test")
        rag_client.trace_retrieval(
            sid,
            chunks=[{"chunk_id": "c1", "score": 0.8, "content_hash": "h", "source": "s"}],
            latency_ms=10.0,
        )
        sess = rag_client.get_session(sid)
        assert sess is not None
        assert sess.total_chunks_used == 1

    def test_trace_generation(self, rag_client):
        sid = rag_client.trace_query("q", top_k=1, retriever_name="t")
        rag_client.trace_generation(
            sid,
            "gpt-4o",
            chunk_ids_used=["c1"],
            prompt_tokens=100,
            output_tokens=50,
            grounding_score=0.88,
        )
        sess = rag_client.get_session(sid)
        assert sess is not None
        assert sess.total_input_tokens == 100

    def test_end_session_returns_summary(self, rag_client):
        sid = rag_client.trace_query("q", top_k=1, retriever_name="t")
        result = rag_client.end_session(sid)
        assert isinstance(result, RAGSessionPayload)
        assert result.session_id == sid

    def test_end_session_unknown(self, rag_client):
        with pytest.raises(KeyError):
            rag_client.end_session("nonexistent-session-id")

    def test_get_session_unknown(self, rag_client):
        result = rag_client.get_session("nonexistent")
        assert result is None

    def test_get_status(self, rag_client):
        status = rag_client.get_status()
        assert isinstance(status, RAGStatusInfo)
        assert status.status == "ok"

    def test_trace_retrieval_unknown_session(self, rag_client):
        # Unknown session — call is ignored (no session created)
        rag_client.trace_retrieval("bad-session", chunks=[], latency_ms=0.0)
        assert rag_client.get_session("bad-session") is None

    def test_trace_generation_unknown_session(self, rag_client):
        # Unknown session — call is ignored
        rag_client.trace_generation(
            "bad-session",
            "gpt-4o",
            chunk_ids_used=[],
            prompt_tokens=0,
            output_tokens=0,
        )
        assert rag_client.get_session("bad-session") is None

    def test_full_pipeline(self, rag_client):
        sid = rag_client.trace_query("What?", top_k=5, retriever_name="weaviate")
        rag_client.trace_retrieval(
            sid,
            chunks=[
                {"chunk_id": f"c{i}", "score": 0.7, "content_hash": f"h{i}", "source": "doc"}
                for i in range(3)
            ],
            total_found=10,
            latency_ms=20.0,
        )
        rag_client.trace_generation(
            sid,
            "gpt-4o",
            chunk_ids_used=["c0", "c1", "c2"],
            prompt_tokens=200,
            output_tokens=100,
            grounding_score=0.9,
        )
        result = rag_client.end_session(sid)
        assert result.total_queries == 1
        assert result.total_chunks_used == 3
        assert result.total_input_tokens == 200
        assert result.total_output_tokens == 100
        assert result.avg_grounding_score == pytest.approx(0.9)

    def test_get_status_with_active_sessions(self, rag_client):
        sid1 = rag_client.trace_query("q1", top_k=1, retriever_name="t")
        sid2 = rag_client.trace_query("q2", top_k=1, retriever_name="t")
        status = rag_client.get_status()
        assert status.active_sessions == 2
        rag_client.end_session(sid1)
        rag_client.end_session(sid2)
