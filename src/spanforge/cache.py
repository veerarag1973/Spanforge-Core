"""spanforge.cache — Semantic cache engine for LLM prompt deduplication.

Deduplicates LLM calls by comparing the cosine similarity of incoming prompts
to previously cached prompts.  When a prompt is *similar enough* (controlled
by ``similarity_threshold``) the cached response is returned immediately.

Public API
----------
SemanticCache       Main cache class.
InMemoryBackend     LRU in-process backend (default).
SQLiteBackend       Persistent stdlib sqlite3 backend.
RedisBackend        Distributed Redis backend (requires ``pip install redis``).
CacheEntry          Dataclass returned by backend inspection.
CacheBackendError   Base exception for backend failures.
cached              ``@cached`` decorator for async and sync functions.

All payload event classes (``CacheHitPayload``, ``CacheMissPayload``, etc.)
are re-exported from ``spanforge.namespaces.cache``.
"""

from __future__ import annotations

import functools
import hashlib
import math
import sqlite3
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from spanforge.exceptions import LLMSchemaError as SpanForgeError

__all__ = [
    "CacheBackendError",
    "CacheEntry",
    "InMemoryBackend",
    "RedisBackend",
    "SQLiteBackend",
    "SemanticCache",
    "cached",
]

_F = TypeVar("_F", bound=Callable[..., Any])

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class CacheBackendError(SpanForgeError):
    """Raised when a backend operation fails.

    Attributes:
        backend: Name of the failing backend class, e.g. ``"SQLiteBackend"``.
        reason:  Human-readable failure description.
    """

    def __init__(self, backend: str, reason: str) -> None:
        super().__init__(f"{backend}: {reason}")
        self.backend = backend
        self.reason = reason


# ---------------------------------------------------------------------------
# CacheEntry
# ---------------------------------------------------------------------------


@dataclass
class CacheEntry:
    """A single cached record returned by backend inspection methods."""

    key_hash: str
    value: str
    embedding: list[float]
    created_at: float  # Unix timestamp
    ttl_seconds: int
    namespace: str
    tags: list[str] = field(default_factory=list)
    similarity_score: float = 1.0  # 1.0 for direct hit, <1 for semantic match


# ---------------------------------------------------------------------------
# Abstract CacheBackend protocol (duck-typed — no ABC required)
# ---------------------------------------------------------------------------


class _CacheBackendBase:
    """Shared base for all backend implementations."""

    def put(self, key_hash: str, entry: CacheEntry) -> None:
        raise NotImplementedError

    def get_all(self, namespace: str) -> list[CacheEntry]:
        raise NotImplementedError

    def remove(self, key_hash: str, namespace: str) -> bool:
        raise NotImplementedError

    def remove_by_tag(self, tag: str, namespace: str) -> list[str]:
        """Return key_hashes removed."""
        raise NotImplementedError

    def clear_namespace(self, namespace: str) -> list[str]:
        """Remove all entries in *namespace*.  Return removed key_hashes."""
        raise NotImplementedError


# ---------------------------------------------------------------------------
# InMemoryBackend
# ---------------------------------------------------------------------------


class InMemoryBackend(_CacheBackendBase):
    """LRU in-process cache backend.  Thread-safe.  Data lost when process exits."""

    def __init__(self, max_size: int = 1024) -> None:
        self._max_size = max_size
        self._lock = threading.Lock()
        # key = (namespace, key_hash)
        self._store: OrderedDict[tuple[str, str], CacheEntry] = OrderedDict()

    def put(self, key_hash: str, entry: CacheEntry) -> None:
        k = (entry.namespace, key_hash)
        with self._lock:
            if k in self._store:
                self._store.move_to_end(k)
            self._store[k] = entry
            while len(self._store) > self._max_size:
                self._store.popitem(last=False)

    def get_all(self, namespace: str) -> list[CacheEntry]:
        with self._lock:
            return [v for (ns, _), v in self._store.items() if ns == namespace]

    def remove(self, key_hash: str, namespace: str) -> bool:
        k = (namespace, key_hash)
        with self._lock:
            return self._store.pop(k, None) is not None

    def remove_by_tag(self, tag: str, namespace: str) -> list[str]:
        with self._lock:
            to_remove = [
                kh for (ns, kh), entry in self._store.items()
                if ns == namespace and tag in entry.tags
            ]
            for kh in to_remove:
                self._store.pop((namespace, kh), None)
        return to_remove

    def clear_namespace(self, namespace: str) -> list[str]:
        with self._lock:
            keys = [(ns, kh) for (ns, kh) in list(self._store.keys()) if ns == namespace]
            for k in keys:
                self._store.pop(k, None)
        return [kh for _, kh in keys]


# ---------------------------------------------------------------------------
# SQLiteBackend
# ---------------------------------------------------------------------------


class SQLiteBackend(_CacheBackendBase):
    """Persistent backend using stdlib ``sqlite3``.  No extra dependencies."""

    _CREATE_SQL = """
        CREATE TABLE IF NOT EXISTS sf_cache (
            namespace TEXT NOT NULL,
            key_hash  TEXT NOT NULL,
            value     TEXT NOT NULL,
            embedding TEXT NOT NULL,
            created_at REAL NOT NULL,
            ttl_seconds INTEGER NOT NULL,
            tags      TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (namespace, key_hash)
        )
    """

    def __init__(self, db_path: str = "spanforge_cache.db") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        try:
            self._conn = sqlite3.connect(db_path, check_same_thread=False)
            self._conn.execute(self._CREATE_SQL)
            self._conn.commit()
        except sqlite3.Error as exc:
            raise CacheBackendError("SQLiteBackend", str(exc)) from exc

    def put(self, key_hash: str, entry: CacheEntry) -> None:
        import json as _json

        try:
            with self._lock:
                self._conn.execute(
                    "INSERT OR REPLACE INTO sf_cache VALUES (?,?,?,?,?,?,?)",
                    (
                        entry.namespace,
                        key_hash,
                        entry.value,
                        _json.dumps(entry.embedding),
                        entry.created_at,
                        entry.ttl_seconds,
                        ",".join(entry.tags),
                    ),
                )
                self._conn.commit()
        except sqlite3.Error as exc:
            raise CacheBackendError("SQLiteBackend", str(exc)) from exc

    def get_all(self, namespace: str) -> list[CacheEntry]:
        import json as _json

        try:
            with self._lock:
                rows = self._conn.execute(
                    "SELECT key_hash,value,embedding,created_at,ttl_seconds,tags "
                    "FROM sf_cache WHERE namespace=?",
                    (namespace,),
                ).fetchall()
        except sqlite3.Error as exc:
            raise CacheBackendError("SQLiteBackend", str(exc)) from exc

        return [
            CacheEntry(
                key_hash=r[0],
                value=r[1],
                embedding=_json.loads(r[2]),
                created_at=r[3],
                ttl_seconds=r[4],
                namespace=namespace,
                tags=[t for t in r[5].split(",") if t],
            )
            for r in rows
        ]

    def remove(self, key_hash: str, namespace: str) -> bool:
        try:
            with self._lock:
                cur = self._conn.execute(
                    "DELETE FROM sf_cache WHERE namespace=? AND key_hash=?",
                    (namespace, key_hash),
                )
                self._conn.commit()
        except sqlite3.Error as exc:
            raise CacheBackendError("SQLiteBackend", str(exc)) from exc
        return cur.rowcount > 0

    def remove_by_tag(self, tag: str, namespace: str) -> list[str]:
        entries = self.get_all(namespace)
        removed: list[str] = []
        for entry in entries:
            if tag in entry.tags:
                self.remove(entry.key_hash, namespace)
                removed.append(entry.key_hash)
        return removed

    def clear_namespace(self, namespace: str) -> list[str]:
        entries = self.get_all(namespace)
        key_hashes = [e.key_hash for e in entries]
        try:
            with self._lock:
                self._conn.execute("DELETE FROM sf_cache WHERE namespace=?", (namespace,))
                self._conn.commit()
        except sqlite3.Error as exc:
            raise CacheBackendError("SQLiteBackend", str(exc)) from exc
        return key_hashes


# ---------------------------------------------------------------------------
# RedisBackend
# ---------------------------------------------------------------------------


class RedisBackend(_CacheBackendBase):
    """Distributed backend via the optional ``redis`` package.

    Requires: ``pip install redis``
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        prefix: str = "spanforge:",
    ) -> None:
        try:
            import redis as _redis  # type: ignore[import-untyped]
        except ImportError as exc:
            raise CacheBackendError(
                "RedisBackend",
                "redis package not installed — run: pip install redis",
            ) from exc
        self._prefix = prefix
        self._client = _redis.Redis(host=host, port=port, db=db, decode_responses=True)

    def _key(self, namespace: str, key_hash: str) -> str:
        return f"{self._prefix}{namespace}:{key_hash}"

    def put(self, key_hash: str, entry: CacheEntry) -> None:
        import json as _json

        try:
            k = self._key(entry.namespace, key_hash)
            data = _json.dumps({
                "value": entry.value,
                "embedding": entry.embedding,
                "created_at": entry.created_at,
                "ttl_seconds": entry.ttl_seconds,
                "namespace": entry.namespace,
                "tags": entry.tags,
            })
            self._client.set(k, data, ex=entry.ttl_seconds)
        except Exception as exc:
            raise CacheBackendError("RedisBackend", str(exc)) from exc

    def get_all(self, namespace: str) -> list[CacheEntry]:
        import json as _json

        try:
            pattern = f"{self._prefix}{namespace}:*"
            keys = self._client.keys(pattern)
            entries: list[CacheEntry] = []
            for k in keys:
                raw = self._client.get(k)
                if raw:
                    d = _json.loads(raw)
                    key_hash = k.split(":")[-1]
                    entries.append(CacheEntry(
                        key_hash=key_hash,
                        value=d["value"],
                        embedding=d["embedding"],
                        created_at=d["created_at"],
                        ttl_seconds=d["ttl_seconds"],
                        namespace=namespace,
                        tags=d.get("tags", []),
                    ))
            return entries
        except Exception as exc:
            raise CacheBackendError("RedisBackend", str(exc)) from exc

    def remove(self, key_hash: str, namespace: str) -> bool:
        try:
            return bool(self._client.delete(self._key(namespace, key_hash)))
        except Exception as exc:
            raise CacheBackendError("RedisBackend", str(exc)) from exc

    def remove_by_tag(self, tag: str, namespace: str) -> list[str]:
        entries = self.get_all(namespace)
        removed: list[str] = []
        for entry in entries:
            if tag in entry.tags:
                self.remove(entry.key_hash, namespace)
                removed.append(entry.key_hash)
        return removed

    def clear_namespace(self, namespace: str) -> list[str]:
        entries = self.get_all(namespace)
        for entry in entries:
            self.remove(entry.key_hash, namespace)
        return [e.key_hash for e in entries]


# ---------------------------------------------------------------------------
# Embedding helper (built-in lightweight TF-IDF encoder)
# ---------------------------------------------------------------------------


def _default_embedder(text: str) -> list[float]:
    """Lightweight character n-gram embedding for local/test use.

    Not suitable for production semantic search.  Replace with a real
    embedding model via ``SemanticCache(embedder=my_model.encode)``.
    """
    # Use 2-char n-gram frequency vector (hash into 128-d space)
    size = 128
    vec = [0.0] * size
    text_lower = text.lower()
    for i in range(len(text_lower) - 1):
        bigram = text_lower[i : i + 2]
        idx = int(hashlib.md5(bigram.encode(), usedforsecurity=False).hexdigest(), 16) % size
        vec[idx] += 1.0
    # L2 normalise
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Return cosine similarity between two unit-normalised vectors."""
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    mag_a = math.sqrt(sum(x * x for x in a)) or 1.0
    mag_b = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (mag_a * mag_b)


# ---------------------------------------------------------------------------
# SemanticCache
# ---------------------------------------------------------------------------


class SemanticCache:
    """Semantic LLM prompt cache.

    Args:
        backend:             Storage backend; defaults to ``InMemoryBackend(max_size)``.
        similarity_threshold: Minimum cosine similarity for a hit (0.0–1.0).
        ttl_seconds:         Seconds before an entry is stale.
        namespace:           Logical partition; entries from different namespaces
                             never collide.
        embedder:            Custom embedding function ``(str) -> list[float]``.
                             Defaults to the built-in n-gram encoder.
        max_size:            Capacity for the auto-created ``InMemoryBackend``.
        emit_events:         Emit ``llm.cache.*`` events on hit/miss/write/eviction.
    """

    def __init__(
        self,
        backend: _CacheBackendBase | None = None,
        similarity_threshold: float = 0.92,
        ttl_seconds: int = 3600,
        namespace: str = "default",
        embedder: Callable[[str], list[float]] | None = None,
        max_size: int = 1024,
        emit_events: bool = True,
    ) -> None:
        self._backend = backend or InMemoryBackend(max_size=max_size)
        self._threshold = similarity_threshold
        self._ttl = ttl_seconds
        self._namespace = namespace
        self._embedder = embedder or _default_embedder
        self._emit_events = emit_events

    def _hash(self, prompt: str) -> str:
        return hashlib.sha256(prompt.encode()).hexdigest()[:32]

    def _emit(self, event_type: str, payload_dict: dict[str, Any]) -> None:
        if not self._emit_events:
            return
        try:
            from spanforge import emit_event  # type: ignore[attr-defined]

            emit_event(event_type, payload_dict)
        except Exception:  # nosec B110
            pass  # Never let event emission crash the cache path

    def get(self, prompt: str) -> str | None:
        """Return the cached response for *prompt*, or ``None`` on miss.

        Emits ``llm.cache.hit`` or ``llm.cache.miss`` when ``emit_events=True``.
        """
        embedding = self._embedder(prompt)
        now = time.time()
        best_score = 0.0
        best_entry: CacheEntry | None = None

        for entry in self._backend.get_all(self._namespace):
            # TTL check
            if now - entry.created_at > entry.ttl_seconds:
                continue
            score = _cosine_similarity(embedding, entry.embedding)
            if score > best_score:
                best_score = score
                best_entry = entry

        if best_entry is not None and best_score >= self._threshold:
            self._emit("llm.cache.hit", {
                "key_hash": best_entry.key_hash,
                "namespace": self._namespace,
                "similarity_score": best_score,
            })
            return best_entry.value

        self._emit("llm.cache.miss", {
            "namespace": self._namespace,
            "similarity_score": best_score,
        })
        return None

    def set(self, prompt: str, value: str, tags: list[str] | None = None) -> None:
        """Store *value* keyed by the embedding of *prompt*.

        Emits ``llm.cache.written`` when ``emit_events=True``.
        """
        key_hash = self._hash(prompt)
        embedding = self._embedder(prompt)
        entry = CacheEntry(
            key_hash=key_hash,
            value=value,
            embedding=embedding,
            created_at=time.time(),
            ttl_seconds=self._ttl,
            namespace=self._namespace,
            tags=tags or [],
        )
        self._backend.put(key_hash, entry)
        self._emit("llm.cache.written", {
            "key_hash": key_hash,
            "namespace": self._namespace,
        })

    def invalidate_by_tag(self, tag: str) -> int:
        """Remove all entries tagged with *tag*.  Returns number removed."""
        removed = self._backend.remove_by_tag(tag, self._namespace)
        for kh in removed:
            self._emit("llm.cache.evicted", {
                "key_hash": kh,
                "namespace": self._namespace,
                "eviction_reason": "manual_invalidation",
            })
        return len(removed)

    def invalidate_all(self) -> int:
        """Flush the entire namespace.  Returns number removed."""
        removed = self._backend.clear_namespace(self._namespace)
        for kh in removed:
            self._emit("llm.cache.evicted", {
                "key_hash": kh,
                "namespace": self._namespace,
                "eviction_reason": "manual_invalidation",
            })
        return len(removed)


# ---------------------------------------------------------------------------
# @cached decorator
# ---------------------------------------------------------------------------

_PROMPT_ARG_NAMES = frozenset({"prompt", "query", "text", "message"})


def _extract_prompt(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    """Extract the cache key from function arguments."""
    # Prefer known keyword names
    for name in _PROMPT_ARG_NAMES:
        if name in kwargs:
            val = kwargs[name]
            if isinstance(val, str):
                return val
    # First positional str arg
    for arg in args:
        if isinstance(arg, str):
            return arg
    # Fallback to full repr
    return repr((args, kwargs))


def cached(
    _func: _F | None = None,
    *,
    threshold: float = 0.92,
    ttl: int = 3600,
    namespace: str = "default",
    backend: _CacheBackendBase | None = None,
    tags: list[str] | None = None,
    emit_events: bool = True,
) -> Any:
    """Decorator that wraps an async or sync function with semantic caching.

    Can be used in bare form or with arguments::

        @cached
        async def ask(prompt: str) -> str: ...

        @cached(threshold=0.95, ttl=7200)
        async def ask(prompt: str) -> str: ...
    """
    _cache = SemanticCache(
        backend=backend,
        similarity_threshold=threshold,
        ttl_seconds=ttl,
        namespace=namespace,
        emit_events=emit_events,
    )

    def decorator(fn: _F) -> _F:
        import asyncio

        if asyncio.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                key = _extract_prompt(args, kwargs)
                hit = _cache.get(key)
                if hit is not None:
                    return hit
                result = await fn(*args, **kwargs)
                if isinstance(result, str):
                    _cache.set(key, result, tags=tags)
                return result

            return async_wrapper  # type: ignore[return-value]
        else:
            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                key = _extract_prompt(args, kwargs)
                hit = _cache.get(key)
                if hit is not None:
                    return hit
                result = fn(*args, **kwargs)
                if isinstance(result, str):
                    _cache.set(key, result, tags=tags)
                return result

            return sync_wrapper  # type: ignore[return-value]

    if _func is not None:
        # Bare @cached usage
        return decorator(_func)
    return decorator
