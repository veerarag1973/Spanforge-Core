"""Tests for spanforge.cache — SemanticCache, backends, @cached decorator."""

from __future__ import annotations

import asyncio
import tempfile
import time
from typing import Any

import pytest

from spanforge.cache import (
    CacheBackendError,
    CacheEntry,
    InMemoryBackend,
    SQLiteBackend,
    SemanticCache,
    cached,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry(
    key_hash: str = "abc123",
    value: str = "response",
    namespace: str = "test",
    embedding: list[float] | None = None,
    ttl_seconds: int = 3600,
    created_at: float | None = None,
    tags: list[str] | None = None,
) -> CacheEntry:
    return CacheEntry(
        key_hash=key_hash,
        value=value,
        embedding=embedding or [0.1, 0.2, 0.3],
        created_at=created_at if created_at is not None else time.time(),
        ttl_seconds=ttl_seconds,
        namespace=namespace,
        tags=tags or [],
    )


def _unit_embedder(text: str) -> list[float]:
    """Always returns the same unit vector — everything is a perfect match."""
    return [1.0, 0.0, 0.0]


def _zero_embedder(text: str) -> list[float]:
    """Returns the zero vector — cosine similarity with anything is 0."""
    return [0.0, 0.0, 0.0]


# ---------------------------------------------------------------------------
# CacheBackendError
# ---------------------------------------------------------------------------


class TestCacheBackendError:
    def test_attributes(self) -> None:
        err = CacheBackendError("SQLiteBackend", "disk full")
        assert err.backend == "SQLiteBackend"
        assert err.reason == "disk full"

    def test_str_contains_backend_and_reason(self) -> None:
        err = CacheBackendError("InMemoryBackend", "overflow")
        assert "InMemoryBackend" in str(err)
        assert "overflow" in str(err)


# ---------------------------------------------------------------------------
# CacheEntry
# ---------------------------------------------------------------------------


class TestCacheEntry:
    def test_required_fields(self) -> None:
        e = _entry()
        assert e.key_hash == "abc123"
        assert e.value == "response"
        assert e.namespace == "test"
        assert isinstance(e.embedding, list)
        assert isinstance(e.created_at, float)
        assert e.ttl_seconds == 3600

    def test_optional_tags_default_empty(self) -> None:
        e = _entry()
        assert e.tags == []

    def test_optional_similarity_score_default(self) -> None:
        e = _entry()
        assert e.similarity_score == 1.0

    def test_tags_provided(self) -> None:
        e = _entry(tags=["model:gpt-4", "lang:en"])
        assert "model:gpt-4" in e.tags


# ---------------------------------------------------------------------------
# InMemoryBackend
# ---------------------------------------------------------------------------


class TestInMemoryBackend:
    def test_put_and_get_all(self) -> None:
        backend = InMemoryBackend()
        e = _entry(key_hash="k1", namespace="ns1")
        backend.put("k1", e)
        results = backend.get_all("ns1")
        assert len(results) == 1
        assert results[0].key_hash == "k1"

    def test_get_all_empty_namespace(self) -> None:
        backend = InMemoryBackend()
        assert backend.get_all("no-such-ns") == []

    def test_namespace_isolation(self) -> None:
        backend = InMemoryBackend()
        backend.put("k1", _entry(key_hash="k1", namespace="ns_a"))
        backend.put("k2", _entry(key_hash="k2", namespace="ns_b"))
        assert len(backend.get_all("ns_a")) == 1
        assert len(backend.get_all("ns_b")) == 1
        assert backend.get_all("ns_a")[0].key_hash == "k1"

    def test_remove_existing_key(self) -> None:
        backend = InMemoryBackend()
        backend.put("k1", _entry(key_hash="k1", namespace="ns"))
        result = backend.remove("k1", "ns")
        assert result is True
        assert backend.get_all("ns") == []

    def test_remove_nonexistent_key_returns_false(self) -> None:
        backend = InMemoryBackend()
        assert backend.remove("no-key", "ns") is False

    def test_remove_by_tag_removes_matching(self) -> None:
        backend = InMemoryBackend()
        backend.put("k1", _entry(key_hash="k1", namespace="ns", tags=["v1"]))
        backend.put("k2", _entry(key_hash="k2", namespace="ns", tags=["v2"]))
        removed = backend.remove_by_tag("v1", "ns")
        assert removed == ["k1"]
        remaining = backend.get_all("ns")
        assert len(remaining) == 1
        assert remaining[0].key_hash == "k2"

    def test_remove_by_tag_no_match(self) -> None:
        backend = InMemoryBackend()
        backend.put("k1", _entry(key_hash="k1", namespace="ns"))
        removed = backend.remove_by_tag("nonexistent-tag", "ns")
        assert removed == []

    def test_clear_namespace(self) -> None:
        backend = InMemoryBackend()
        backend.put("k1", _entry(key_hash="k1", namespace="ns"))
        backend.put("k2", _entry(key_hash="k2", namespace="ns"))
        removed = backend.clear_namespace("ns")
        assert set(removed) == {"k1", "k2"}
        assert backend.get_all("ns") == []

    def test_clear_namespace_does_not_affect_other_ns(self) -> None:
        backend = InMemoryBackend()
        backend.put("k1", _entry(key_hash="k1", namespace="ns1"))
        backend.put("k2", _entry(key_hash="k2", namespace="ns2"))
        backend.clear_namespace("ns1")
        assert len(backend.get_all("ns2")) == 1

    def test_lru_eviction_at_max_size(self) -> None:
        backend = InMemoryBackend(max_size=2)
        backend.put("k1", _entry(key_hash="k1", namespace="ns"))
        backend.put("k2", _entry(key_hash="k2", namespace="ns"))
        backend.put("k3", _entry(key_hash="k3", namespace="ns"))  # evicts k1
        keys = {e.key_hash for e in backend.get_all("ns")}
        assert "k1" not in keys
        assert "k3" in keys

    def test_put_updates_existing_key(self) -> None:
        backend = InMemoryBackend()
        backend.put("k1", _entry(key_hash="k1", value="old", namespace="ns"))
        backend.put("k1", _entry(key_hash="k1", value="new", namespace="ns"))
        results = backend.get_all("ns")
        assert len(results) == 1
        assert results[0].value == "new"


# ---------------------------------------------------------------------------
# SQLiteBackend
# ---------------------------------------------------------------------------


class TestSQLiteBackend:
    def test_put_and_get_all(self, tmp_path: Any) -> None:
        db = str(tmp_path / "cache.db")
        backend = SQLiteBackend(db_path=db)
        e = _entry(key_hash="k1", namespace="sql_ns")
        backend.put("k1", e)
        results = backend.get_all("sql_ns")
        assert len(results) == 1
        assert results[0].key_hash == "k1"
        assert results[0].value == "response"

    def test_remove_existing(self, tmp_path: Any) -> None:
        db = str(tmp_path / "cache.db")
        backend = SQLiteBackend(db_path=db)
        backend.put("k1", _entry(key_hash="k1", namespace="ns"))
        assert backend.remove("k1", "ns") is True
        assert backend.get_all("ns") == []

    def test_remove_nonexistent(self, tmp_path: Any) -> None:
        db = str(tmp_path / "cache.db")
        backend = SQLiteBackend(db_path=db)
        assert backend.remove("no-key", "ns") is False

    def test_clear_namespace(self, tmp_path: Any) -> None:
        db = str(tmp_path / "cache.db")
        backend = SQLiteBackend(db_path=db)
        backend.put("k1", _entry(key_hash="k1", namespace="ns"))
        backend.put("k2", _entry(key_hash="k2", namespace="ns"))
        removed = backend.clear_namespace("ns")
        assert set(removed) == {"k1", "k2"}
        assert backend.get_all("ns") == []

    def test_tags_roundtrip(self, tmp_path: Any) -> None:
        db = str(tmp_path / "cache.db")
        backend = SQLiteBackend(db_path=db)
        backend.put("k1", _entry(key_hash="k1", namespace="ns", tags=["a", "b"]))
        results = backend.get_all("ns")
        assert "a" in results[0].tags
        assert "b" in results[0].tags

    def test_remove_by_tag(self, tmp_path: Any) -> None:
        db = str(tmp_path / "cache.db")
        backend = SQLiteBackend(db_path=db)
        backend.put("k1", _entry(key_hash="k1", namespace="ns", tags=["v1"]))
        backend.put("k2", _entry(key_hash="k2", namespace="ns", tags=["v2"]))
        removed = backend.remove_by_tag("v1", "ns")
        assert "k1" in removed
        assert len(backend.get_all("ns")) == 1

    def test_in_memory_db(self) -> None:
        backend = SQLiteBackend(db_path=":memory:")
        backend.put("k1", _entry(key_hash="k1", namespace="ns"))
        assert len(backend.get_all("ns")) == 1

    def test_replace_existing_key(self, tmp_path: Any) -> None:
        db = str(tmp_path / "cache.db")
        backend = SQLiteBackend(db_path=db)
        backend.put("k1", _entry(key_hash="k1", value="old", namespace="ns"))
        backend.put("k1", _entry(key_hash="k1", value="new", namespace="ns"))
        results = backend.get_all("ns")
        assert len(results) == 1
        assert results[0].value == "new"


# ---------------------------------------------------------------------------
# SemanticCache
# ---------------------------------------------------------------------------


class TestSemanticCache:
    def test_miss_on_empty_cache(self) -> None:
        cache = SemanticCache(emit_events=False)
        assert cache.get("any prompt") is None

    def test_set_and_exact_hit(self) -> None:
        cache = SemanticCache(embedder=_unit_embedder, emit_events=False)
        cache.set("hello", "world")
        result = cache.get("hello")
        assert result == "world"

    def test_miss_below_threshold(self) -> None:
        """Zero embedder makes cosine similarity 0 — always a miss."""
        cache = SemanticCache(
            embedder=_zero_embedder,
            similarity_threshold=0.9,
            emit_events=False,
        )
        cache.set("hello", "world")
        result = cache.get("something")
        assert result is None

    def test_ttl_expiry_returns_none(self) -> None:
        backend = InMemoryBackend()
        # Put an entry with ttl=1 and created_at far in the past
        expired = _entry(
            key_hash="k1",
            value="stale",
            namespace="default",
            embedding=[1.0, 0.0, 0.0],
            ttl_seconds=1,
            created_at=time.time() - 100,  # 100 seconds ago
        )
        backend.put("k1", expired)
        cache = SemanticCache(
            backend=backend,
            embedder=_unit_embedder,
            similarity_threshold=0.0,
            emit_events=False,
        )
        assert cache.get("any") is None

    def test_namespace_isolation(self) -> None:
        cache_a = SemanticCache(namespace="ns_a", embedder=_unit_embedder, emit_events=False)
        cache_b = SemanticCache(namespace="ns_b", embedder=_unit_embedder, emit_events=False)
        cache_a.set("prompt", "answer_a")
        assert cache_b.get("prompt") is None

    def test_invalidate_by_tag(self) -> None:
        cache = SemanticCache(embedder=_unit_embedder, emit_events=False)
        cache.set("prompt1", "response1", tags=["v1"])
        cache.set("prompt2", "response2", tags=["v2"])
        removed = cache.invalidate_by_tag("v1")
        assert removed == 1

    def test_invalidate_all(self) -> None:
        cache = SemanticCache(embedder=_unit_embedder, emit_events=False)
        cache.set("p1", "r1")
        cache.set("p2", "r2")
        removed = cache.invalidate_all()
        assert removed == 2
        assert cache.get("p1") is None

    def test_set_with_tags(self) -> None:
        backend = InMemoryBackend()
        cache = SemanticCache(backend=backend, emit_events=False)
        cache.set("prompt", "response", tags=["tag1", "tag2"])
        entries = backend.get_all("default")
        assert len(entries) == 1
        assert "tag1" in entries[0].tags

    def test_custom_namespace_stored_in_entry(self) -> None:
        backend = InMemoryBackend()
        cache = SemanticCache(backend=backend, namespace="my-ns", emit_events=False)
        cache.set("p", "r")
        entries = backend.get_all("my-ns")
        assert len(entries) == 1

    def test_emit_events_does_not_crash_on_no_emitter(self) -> None:
        """When emit_events=True but no emitter available, cache still works."""
        cache = SemanticCache(embedder=_unit_embedder, emit_events=True)
        cache.set("p", "r")
        result = cache.get("p")
        assert result == "r"


# ---------------------------------------------------------------------------
# RedisBackend — import error path (no real Redis required)
# ---------------------------------------------------------------------------


class TestRedisBackendImportError:
    def test_raises_cache_backend_error_when_redis_missing(self) -> None:
        import sys
        from unittest.mock import patch

        # Simulate redis not being installed
        with patch.dict(sys.modules, {"redis": None}):
            from spanforge.cache import RedisBackend  # re-import in patched env

            with pytest.raises(CacheBackendError, match="redis"):
                RedisBackend()


# ---------------------------------------------------------------------------
# @cached decorator
# ---------------------------------------------------------------------------


class TestCachedDecoratorSync:
    def test_sync_function_cached(self) -> None:
        call_count = 0

        @cached(threshold=0.99, emit_events=False)
        def respond(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"response to: {prompt}"

        r1 = respond("same prompt")
        r2 = respond("same prompt")
        assert r1 == r2
        assert call_count == 1  # second call should be served from cache

    def test_sync_different_prompts_call_function(self) -> None:
        call_count = 0

        @cached(threshold=0.9999, emit_events=False)
        def respond(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"response_{call_count}"

        respond("alpha prompt")
        respond("totally different")
        assert call_count == 2

    def test_sync_uses_prompt_kwarg(self) -> None:
        call_count = 0

        @cached(threshold=0.99, emit_events=False)
        def respond(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return "ok"

        respond(prompt="kwarg prompt")
        respond(prompt="kwarg prompt")
        assert call_count == 1

    def test_sync_bare_decorator(self) -> None:
        @cached
        def fn(prompt: str) -> str:
            return "bare"

        assert fn("x") == "bare"


class TestCachedDecoratorAsync:
    def test_async_function_cached(self) -> None:
        call_count = 0

        @cached(threshold=0.99, emit_events=False)
        async def respond(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"async: {prompt}"

        r1 = asyncio.run(respond("async prompt"))
        r2 = asyncio.run(respond("async prompt"))
        assert r1 == r2
        assert call_count == 1

    def test_async_different_prompts_call_function(self) -> None:
        call_count = 0

        @cached(threshold=0.9999, emit_events=False)
        async def respond(prompt: str) -> str:
            nonlocal call_count
            call_count += 1
            return f"r{call_count}"

        asyncio.run(respond("prompt one"))
        asyncio.run(respond("prompt two different"))
        assert call_count == 2


class TestExtractPrompt:
    def test_extract_from_query_kwarg(self) -> None:
        from spanforge.cache import _extract_prompt

        result = _extract_prompt((), {"query": "my query"})
        assert result == "my query"

    def test_extract_from_positional_str(self) -> None:
        from spanforge.cache import _extract_prompt

        result = _extract_prompt(("hello",), {})
        assert result == "hello"

    def test_fallback_to_repr(self) -> None:
        from spanforge.cache import _extract_prompt

        result = _extract_prompt((42,), {})
        # Should return repr of (args, kwargs)
        assert "42" in result
