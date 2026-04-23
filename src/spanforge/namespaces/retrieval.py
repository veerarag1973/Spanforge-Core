"""spanforge.namespaces.retrieval — RAG retrieval namespace payload types.

Provides dataclasses for the ``llm.rag.*`` event namespace, covering all
phases of a Retrieval-Augmented Generation pipeline:

1. **Query** — the user query forwarded to the retriever.
2. **Retrieval** — the documents / chunks fetched from the vector store.
3. **Generation** — the LLM generation that consumes retrieved context.
4. **Session** — end-to-end RAG session summary.

Classes
-------
RetrievalQueryPayload
    ``llm.rag.query`` events — user query + retriever config.
RetrievalResultPayload
    ``llm.rag.retrieved`` events — retrieved chunks with scores.
RAGSpanPayload
    ``llm.rag.generated`` events — LLM generation span over retrieved context.
RAGSessionPayload
    ``llm.rag.session`` events — root summary for a complete RAG interaction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = [
    "RAGSessionPayload",
    "RAGSpanPayload",
    "RetrievalQueryPayload",
    "RetrievalResultPayload",
    "RetrievedChunk",
]

_VALID_STATUSES: frozenset[str] = frozenset({"ok", "error", "timeout", "partial"})


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass
class RetrievedChunk:
    """A single retrieved document chunk with its relevance score.

    Attributes:
        chunk_id:     Unique identifier for the chunk within the document store.
        content_hash: SHA-256 hex digest of the chunk text (raw text NOT stored).
        score:        Relevance / similarity score in [0.0, 1.0].
        source:       Document source identifier (e.g. URI, filename, database key).
        metadata:     Arbitrary key-value metadata attached to the chunk.
    """

    chunk_id: str
    content_hash: str
    score: float
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.chunk_id:
            raise ValueError("RetrievedChunk.chunk_id must be non-empty")
        if not (0.0 <= self.score <= 1.0):
            raise ValueError(f"RetrievedChunk.score must be in [0, 1]; got {self.score}")

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "chunk_id": self.chunk_id,
            "content_hash": self.content_hash,
            "score": self.score,
            "source": self.source,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetrievedChunk:
        """Deserialise from a plain dict."""
        return cls(
            chunk_id=str(data["chunk_id"]),
            content_hash=str(data.get("content_hash", "")),
            score=float(data["score"]),
            source=str(data.get("source", "")),
            metadata=dict(data.get("metadata", {})),
        )


# ---------------------------------------------------------------------------
# Payload dataclasses
# ---------------------------------------------------------------------------


@dataclass
class RetrievalQueryPayload:
    """Payload for ``llm.rag.query`` events.

    Captures the user query and the retriever configuration at the time of
    the query without storing raw query text.

    Attributes:
        session_id:        RAG session this query belongs to.
        query_hash:        SHA-256 hex digest of the query text (text NOT stored).
        top_k:             Number of chunks requested from the retriever.
        retriever_name:    Name / identifier of the vector store or retriever.
        embedding_model:   Embedding model used to encode the query.
        namespace:         Optional vector store namespace / collection.
        latency_ms:        Time taken to submit the query (ms).
        filters:           Metadata filters applied to the retrieval query.
    """

    session_id: str
    query_hash: str
    top_k: int = 5
    retriever_name: str = ""
    embedding_model: str = ""
    namespace: str = ""
    latency_ms: float = 0.0
    filters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("RetrievalQueryPayload.session_id must be non-empty")
        if self.top_k < 1:
            raise ValueError(f"RetrievalQueryPayload.top_k must be >= 1; got {self.top_k}")
        if self.latency_ms < 0:
            raise ValueError("RetrievalQueryPayload.latency_ms must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "session_id": self.session_id,
            "query_hash": self.query_hash,
            "top_k": self.top_k,
            "retriever_name": self.retriever_name,
            "embedding_model": self.embedding_model,
            "namespace": self.namespace,
            "latency_ms": self.latency_ms,
            "filters": self.filters,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetrievalQueryPayload:
        """Deserialise from a plain dict."""
        return cls(
            session_id=str(data["session_id"]),
            query_hash=str(data.get("query_hash", "")),
            top_k=int(data.get("top_k", 5)),
            retriever_name=str(data.get("retriever_name", "")),
            embedding_model=str(data.get("embedding_model", "")),
            namespace=str(data.get("namespace", "")),
            latency_ms=float(data.get("latency_ms", 0.0)),
            filters=dict(data.get("filters", {})),
        )


@dataclass
class RetrievalResultPayload:
    """Payload for ``llm.rag.retrieved`` events.

    Attributes:
        session_id:    RAG session this result belongs to.
        query_hash:    SHA-256 hex digest of the triggering query.
        chunks:        Ordered list of retrieved chunks.
        total_found:   Total number of matching chunks before ``top_k`` truncation.
        latency_ms:    Time taken for the retrieval (ms).
        status:        Retrieval status: ``"ok"``, ``"partial"``, ``"error"``,
                       or ``"timeout"``.
        error_message: Present when *status* is ``"error"`` or ``"timeout"``.
    """

    session_id: str
    query_hash: str
    chunks: list[RetrievedChunk] = field(default_factory=list)
    total_found: int = 0
    latency_ms: float = 0.0
    status: Literal["ok", "partial", "error", "timeout"] = "ok"
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("RetrievalResultPayload.session_id must be non-empty")
        if self.status not in _VALID_STATUSES:
            raise ValueError(
                f"RetrievalResultPayload.status must be one of {sorted(_VALID_STATUSES)}"
            )
        if self.latency_ms < 0:
            raise ValueError("RetrievalResultPayload.latency_ms must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        d: dict[str, Any] = {
            "session_id": self.session_id,
            "query_hash": self.query_hash,
            "chunks": [c.to_dict() for c in self.chunks],
            "total_found": self.total_found,
            "latency_ms": self.latency_ms,
            "status": self.status,
        }
        if self.error_message is not None:
            d["error_message"] = self.error_message
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RetrievalResultPayload:
        """Deserialise from a plain dict."""
        return cls(
            session_id=str(data["session_id"]),
            query_hash=str(data.get("query_hash", "")),
            chunks=[RetrievedChunk.from_dict(c) for c in data.get("chunks", [])],
            total_found=int(data.get("total_found", 0)),
            latency_ms=float(data.get("latency_ms", 0.0)),
            status=data.get("status", "ok"),
            error_message=data.get("error_message"),
        )


@dataclass
class RAGSpanPayload:
    """Payload for ``llm.rag.generated`` events.

    Represents the LLM generation step that consumes retrieved context.

    Attributes:
        session_id:       RAG session this span belongs to.
        span_name:        Human-readable label for the generation step.
        model:            Model identifier (e.g. ``"gpt-4o"``).
        chunk_ids_used:   Identifiers of the chunks included in the context window.
        context_tokens:   Number of tokens consumed by the retrieved context.
        prompt_tokens:    Number of tokens in the full prompt (context + instruction).
        output_tokens:    Number of tokens in the generated response.
        latency_ms:       Total generation latency in milliseconds.
        status:           Generation status.
        grounding_score:  Optional 0.0–1.0 score measuring how well the output
                          is grounded in the retrieved context.
        error_message:    Present when *status* is not ``"ok"``.
    """

    session_id: str
    span_name: str
    model: str
    chunk_ids_used: list[str] = field(default_factory=list)
    context_tokens: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    status: Literal["ok", "error", "timeout"] = "ok"
    grounding_score: float | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("RAGSpanPayload.session_id must be non-empty")
        if not self.model:
            raise ValueError("RAGSpanPayload.model must be non-empty")
        if self.status not in {"ok", "error", "timeout"}:
            raise ValueError(
                f"RAGSpanPayload.status must be 'ok', 'error', or 'timeout'; got {self.status!r}"
            )
        if self.latency_ms < 0:
            raise ValueError("RAGSpanPayload.latency_ms must be >= 0")
        if self.grounding_score is not None and not (0.0 <= self.grounding_score <= 1.0):
            raise ValueError(
                f"RAGSpanPayload.grounding_score must be in [0, 1]; got {self.grounding_score}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        d: dict[str, Any] = {
            "session_id": self.session_id,
            "span_name": self.span_name,
            "model": self.model,
            "chunk_ids_used": self.chunk_ids_used,
            "context_tokens": self.context_tokens,
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.output_tokens,
            "latency_ms": self.latency_ms,
            "status": self.status,
        }
        if self.grounding_score is not None:
            d["grounding_score"] = self.grounding_score
        if self.error_message is not None:
            d["error_message"] = self.error_message
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RAGSpanPayload:
        """Deserialise from a plain dict."""
        gs = data.get("grounding_score")
        return cls(
            session_id=str(data["session_id"]),
            span_name=str(data.get("span_name", "")),
            model=str(data["model"]),
            chunk_ids_used=list(data.get("chunk_ids_used", [])),
            context_tokens=int(data.get("context_tokens", 0)),
            prompt_tokens=int(data.get("prompt_tokens", 0)),
            output_tokens=int(data.get("output_tokens", 0)),
            latency_ms=float(data.get("latency_ms", 0.0)),
            status=data.get("status", "ok"),
            grounding_score=float(gs) if gs is not None else None,
            error_message=data.get("error_message"),
        )


@dataclass
class RAGSessionPayload:
    """Payload for ``llm.rag.session`` events.

    Root summary for a complete Retrieval-Augmented Generation interaction
    from initial user query through to final generated response.

    Attributes:
        session_id:         Unique identifier for this RAG session.
        total_queries:      Number of retrieval queries issued in the session.
        total_chunks_used:  Total distinct chunk IDs consumed across all generations.
        total_input_tokens: Sum of all prompt tokens across generation spans.
        total_output_tokens: Sum of all output tokens across generation spans.
        avg_grounding_score: Mean grounding score across all ``llm.rag.generated``
                             spans; ``None`` if no grounding scores were recorded.
        total_latency_ms:   Total wall-clock time for the session (ms).
        status:             Overall session status.
        retriever_name:     Name of the primary retriever used in this session.
    """

    session_id: str
    total_queries: int = 0
    total_chunks_used: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    avg_grounding_score: float | None = None
    total_latency_ms: float = 0.0
    status: Literal["ok", "partial", "error"] = "ok"
    retriever_name: str = ""

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("RAGSessionPayload.session_id must be non-empty")
        if self.status not in {"ok", "partial", "error"}:
            raise ValueError(
                f"RAGSessionPayload.status must be 'ok', 'partial', or 'error'; got {self.status!r}"
            )
        if self.avg_grounding_score is not None and not (0.0 <= self.avg_grounding_score <= 1.0):
            raise ValueError(
                f"RAGSessionPayload.avg_grounding_score must be in [0, 1]; "
                f"got {self.avg_grounding_score}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        d: dict[str, Any] = {
            "session_id": self.session_id,
            "total_queries": self.total_queries,
            "total_chunks_used": self.total_chunks_used,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_latency_ms": self.total_latency_ms,
            "status": self.status,
            "retriever_name": self.retriever_name,
        }
        if self.avg_grounding_score is not None:
            d["avg_grounding_score"] = self.avg_grounding_score
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RAGSessionPayload:
        """Deserialise from a plain dict."""
        ags = data.get("avg_grounding_score")
        return cls(
            session_id=str(data["session_id"]),
            total_queries=int(data.get("total_queries", 0)),
            total_chunks_used=int(data.get("total_chunks_used", 0)),
            total_input_tokens=int(data.get("total_input_tokens", 0)),
            total_output_tokens=int(data.get("total_output_tokens", 0)),
            avg_grounding_score=float(ags) if ags is not None else None,
            total_latency_ms=float(data.get("total_latency_ms", 0.0)),
            status=data.get("status", "ok"),
            retriever_name=str(data.get("retriever_name", "")),
        )
