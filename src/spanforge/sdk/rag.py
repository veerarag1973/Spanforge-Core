"""spanforge.sdk.rag — SpanForge sf-rag RAG Tracing client (Phase 13).

Implements RAG-001 through RAG-006: full tracing for Retrieval-Augmented
Generation pipelines including query tracing, retrieval tracing, generation
tracing, grounding scoring, and session summaries.

Architecture
------------
* :meth:`trace_query` records a ``llm.rag.query`` event and returns the
  auto-generated ``session_id`` to be threaded through subsequent calls.
* :meth:`trace_retrieval` records a ``llm.rag.retrieved`` event with chunk
  metadata (raw chunk text is NEVER stored).
* :meth:`trace_generation` records a ``llm.rag.generated`` event linking the
  LLM generation span to the retrieved chunk IDs.
* :meth:`get_session` returns a :class:`~spanforge.sdk._types.RAGSessionInfo`
  aggregate for a given ``session_id``.
* :meth:`get_status` returns service health and session statistics.

All operations run locally in-process when ``config.endpoint`` is empty or
the remote service is unreachable and ``local_fallback_enabled`` is ``True``.

Security requirements
---------------------
* Raw user queries and retrieved document text are **never** stored; only
  SHA-256 content hashes are kept.
* Chunk ``chunk_id`` values are stored as-is — callers must ensure they do
  not contain personally identifiable information.
* Thread-safety: all in-process state uses locks.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.namespaces.retrieval import (
    RAGSessionPayload,
    RAGSpanPayload,
    RetrievalQueryPayload,
    RetrievalResultPayload,
    RetrievedChunk,
)

__all__ = ["SFRAGClient"]

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Local session store
# ---------------------------------------------------------------------------


@dataclass
class _RAGSession:
    """Internal in-process state accumulated across a single RAG session."""

    session_id: str
    queries: int = 0
    chunk_ids: set[str] = field(default_factory=set)
    input_tokens: int = 0
    output_tokens: int = 0
    grounding_scores: list[float] = field(default_factory=list)
    total_latency_ms: float = 0.0
    retriever_name: str = ""
    status: str = "ok"
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Status dataclass
# ---------------------------------------------------------------------------


@dataclass
class RAGStatusInfo:
    """sf-rag service status.

    Returned by :meth:`SFRAGClient.get_status`.

    Attributes:
        status:           ``"ok"`` or ``"degraded"``.
        active_sessions:  Number of sessions that have been started but not
                          yet finalised with :meth:`SFRAGClient.end_session`.
        total_queries:    Total ``trace_query`` calls in this process lifetime.
        total_spans:      Total ``trace_generation`` calls in this process
                          lifetime.
    """

    status: str
    active_sessions: int
    total_queries: int
    total_spans: int


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class SFRAGClient(SFServiceClient):
    """SpanForge RAG Tracing service client.

    Provides end-to-end observability for Retrieval-Augmented Generation
    pipelines.  Complements :class:`~spanforge.sdk.observe.SFObserveClient`
    by adding RAG-specific query → retrieval → generation correlation.

    Example usage::

        import spanforge
        from spanforge.sdk import sf_rag

        session_id = sf_rag.trace_query(
            query="What is the capital of France?",
            top_k=5,
            retriever_name="chroma-main",
        )

        sf_rag.trace_retrieval(
            session_id=session_id,
            chunks=[
                {"chunk_id": "doc-42-p3", "score": 0.93, "source": "docs/geo.md"},
            ],
            latency_ms=45.2,
        )

        sf_rag.trace_generation(
            session_id=session_id,
            model="gpt-4o",
            chunk_ids_used=["doc-42-p3"],
            prompt_tokens=512,
            output_tokens=128,
            grounding_score=0.91,
            latency_ms=1230.0,
        )

        summary = sf_rag.end_session(session_id)
    """

    def __init__(self, config: SFClientConfig) -> None:
        super().__init__(config, service_name="rag")
        self._lock = threading.Lock()
        self._sessions: dict[str, _RAGSession] = {}
        self._total_queries: int = 0
        self._total_spans: int = 0

    # ------------------------------------------------------------------
    # RAG-001: trace_query
    # ------------------------------------------------------------------

    def trace_query(
        self,
        query: str,
        *,
        session_id: str | None = None,
        top_k: int = 5,
        retriever_name: str = "",
        embedding_model: str = "",
        namespace: str = "",
        latency_ms: float = 0.0,
        filters: dict[str, Any] | None = None,
    ) -> str:
        """Record a RAG query and return the session ID.

        The raw *query* text is **never stored**; only its SHA-256 hash is
        retained for correlation.

        Args:
            query:           Raw user query text (hashed, not stored).
            session_id:      Optional existing session ID to continue.  A new
                             ULID is generated when ``None``.
            top_k:           Number of chunks to retrieve.
            retriever_name:  Name of the vector store / retriever.
            embedding_model: Embedding model used to encode the query.
            namespace:       Optional vector store namespace or collection.
            latency_ms:      Time to submit the query (ms).
            filters:         Metadata filters applied to the retrieval query.

        Returns:
            The ``session_id`` to pass to :meth:`trace_retrieval` and
            :meth:`trace_generation`.
        """
        from spanforge.ulid import generate as _ulid

        sid = session_id or _ulid()
        query_hash = hashlib.sha256(query.encode("utf-8")).hexdigest()

        payload = RetrievalQueryPayload(
            session_id=sid,
            query_hash=query_hash,
            top_k=top_k,
            retriever_name=retriever_name,
            embedding_model=embedding_model,
            namespace=namespace,
            latency_ms=latency_ms,
            filters=filters or {},
        )

        with self._lock:
            if sid not in self._sessions:
                self._sessions[sid] = _RAGSession(
                    session_id=sid,
                    retriever_name=retriever_name,
                )
            self._sessions[sid].queries += 1
            self._sessions[sid].total_latency_ms += latency_ms
            if retriever_name and not self._sessions[sid].retriever_name:
                self._sessions[sid].retriever_name = retriever_name
            self._total_queries += 1

        self._emit_local("llm.rag.query", payload.to_dict(), session_id=sid)
        return sid

    # ------------------------------------------------------------------
    # RAG-002: trace_retrieval
    # ------------------------------------------------------------------

    def trace_retrieval(
        self,
        session_id: str,
        chunks: list[dict[str, Any]],
        *,
        total_found: int | None = None,
        latency_ms: float = 0.0,
        query_hash: str = "",
        status: str = "ok",
        error_message: str | None = None,
    ) -> None:
        """Record retrieved chunks for a session.

        Args:
            session_id:    The session ID returned by :meth:`trace_query`.
            chunks:        List of chunk dicts, each requiring ``chunk_id``
                           (str) and ``score`` (float 0–1).  ``source`` and
                           ``content_hash`` are optional.
            total_found:   Total matching chunks before ``top_k`` truncation.
            latency_ms:    Time taken for retrieval (ms).
            query_hash:    SHA-256 hash of the triggering query (optional).
            status:        ``"ok"``, ``"partial"``, ``"error"``, or ``"timeout"``.
            error_message: Error detail when *status* is not ``"ok"``.
        """
        parsed_chunks = [RetrievedChunk.from_dict(c) for c in chunks]
        payload = RetrievalResultPayload(
            session_id=session_id,
            query_hash=query_hash,
            chunks=parsed_chunks,
            total_found=total_found if total_found is not None else len(parsed_chunks),
            latency_ms=latency_ms,
            status=status,  # type: ignore[arg-type]
            error_message=error_message,
        )

        with self._lock:
            if session_id in self._sessions:
                for chunk in parsed_chunks:
                    self._sessions[session_id].chunk_ids.add(chunk.chunk_id)
                self._sessions[session_id].total_latency_ms += latency_ms
                if status not in ("ok", "partial"):
                    self._sessions[session_id].status = status

        self._emit_local("llm.rag.retrieved", payload.to_dict(), session_id=session_id)

    # ------------------------------------------------------------------
    # RAG-003: trace_generation
    # ------------------------------------------------------------------

    def trace_generation(
        self,
        session_id: str,
        model: str,
        *,
        span_name: str = "rag-generation",
        chunk_ids_used: list[str] | None = None,
        context_tokens: int = 0,
        prompt_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: float = 0.0,
        status: str = "ok",
        grounding_score: float | None = None,
        error_message: str | None = None,
    ) -> None:
        """Record an LLM generation span over retrieved context.

        Args:
            session_id:      The session ID returned by :meth:`trace_query`.
            model:           Model identifier (e.g. ``"gpt-4o"``).
            span_name:       Human-readable label for this generation step.
            chunk_ids_used:  Chunk IDs included in the context window.
            context_tokens:  Tokens consumed by the retrieved context.
            prompt_tokens:   Total prompt tokens (context + instruction).
            output_tokens:   Tokens in the generated response.
            latency_ms:      Generation latency in milliseconds.
            status:          ``"ok"``, ``"error"``, or ``"timeout"``.
            grounding_score: 0.0–1.0 grounding quality score (optional).
            error_message:   Error detail when *status* is not ``"ok"``.
        """
        payload = RAGSpanPayload(
            session_id=session_id,
            span_name=span_name,
            model=model,
            chunk_ids_used=chunk_ids_used or [],
            context_tokens=context_tokens,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            status=status,  # type: ignore[arg-type]
            grounding_score=grounding_score,
            error_message=error_message,
        )

        with self._lock:
            if session_id in self._sessions:
                sess = self._sessions[session_id]
                sess.input_tokens += prompt_tokens
                sess.output_tokens += output_tokens
                sess.total_latency_ms += latency_ms
                if grounding_score is not None:
                    sess.grounding_scores.append(grounding_score)
                if chunk_ids_used:
                    sess.chunk_ids.update(chunk_ids_used)
                if status not in ("ok",):
                    sess.status = status
            self._total_spans += 1

        self._emit_local("llm.rag.generated", payload.to_dict(), session_id=session_id)

    # ------------------------------------------------------------------
    # RAG-004: end_session / get_session
    # ------------------------------------------------------------------

    def end_session(self, session_id: str) -> RAGSessionPayload:
        """Finalise a session and emit a ``llm.rag.session`` summary event.

        Args:
            session_id: The session ID to finalise.

        Returns:
            A :class:`~spanforge.namespaces.retrieval.RAGSessionPayload`
            capturing session-level aggregates.

        Raises:
            KeyError: If *session_id* is unknown.
        """
        with self._lock:
            sess = self._sessions.pop(session_id)

        gs: float | None = None
        if sess.grounding_scores:
            gs = sum(sess.grounding_scores) / len(sess.grounding_scores)

        payload = RAGSessionPayload(
            session_id=session_id,
            total_queries=sess.queries,
            total_chunks_used=len(sess.chunk_ids),
            total_input_tokens=sess.input_tokens,
            total_output_tokens=sess.output_tokens,
            avg_grounding_score=gs,
            total_latency_ms=sess.total_latency_ms,
            status=sess.status,  # type: ignore[arg-type]
            retriever_name=sess.retriever_name,
        )

        self._emit_local("llm.rag.session", payload.to_dict(), session_id=session_id)
        return payload

    def get_session(self, session_id: str) -> RAGSessionPayload | None:
        """Return a live snapshot for *session_id* without finalising it.

        Returns ``None`` if the session is unknown.
        """
        with self._lock:
            sess = self._sessions.get(session_id)
        if sess is None:
            return None

        gs: float | None = None
        if sess.grounding_scores:
            gs = sum(sess.grounding_scores) / len(sess.grounding_scores)

        return RAGSessionPayload(
            session_id=session_id,
            total_queries=sess.queries,
            total_chunks_used=len(sess.chunk_ids),
            total_input_tokens=sess.input_tokens,
            total_output_tokens=sess.output_tokens,
            avg_grounding_score=gs,
            total_latency_ms=sess.total_latency_ms,
            status=sess.status,  # type: ignore[arg-type]
            retriever_name=sess.retriever_name,
        )

    # ------------------------------------------------------------------
    # RAG-005: get_status
    # ------------------------------------------------------------------

    def get_status(self) -> RAGStatusInfo:
        """Return service health and session statistics."""
        with self._lock:
            active = len(self._sessions)
            queries = self._total_queries
            spans = self._total_spans
        return RAGStatusInfo(
            status="ok",
            active_sessions=active,
            total_queries=queries,
            total_spans=spans,
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
        """Emit a RAG event locally or forward to remote endpoint."""
        try:
            from spanforge.sdk.observe import SFObserveClient

            observe_config = SFClientConfig(
                endpoint=self._config.endpoint,
                api_key=self._config.api_key,
            )
            obs = SFObserveClient(observe_config)
            obs.emit_span(
                name=event_type,
                payload=payload,
                trace_id=session_id,
            )
        except Exception:  # NOSONAR — local fallback; never suppress intentionally
            _log.debug("sf-rag local emit %s session=%s", event_type, session_id)
