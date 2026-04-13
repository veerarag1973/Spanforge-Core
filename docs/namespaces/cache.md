# llm.cache — Semantic Cache Events

> **Auto-documented module:** `spanforge.namespaces.cache`

The `llm.cache.*` namespace records the outcome of semantic cache lookups,
writes, and evictions (RFC-0001 §7).

## Payload classes

| Class | Event type | Description |
|-------|-----------|-------------|
| `CacheHitPayload` | `llm.cache.hit` | A cache lookup succeeded |
| `CacheMissPayload` | `llm.cache.miss` | A cache lookup failed |
| `CacheEvictedPayload` | `llm.cache.evicted` | A cache entry was removed |
| `CacheWrittenPayload` | `llm.cache.written` | A response was written to cache |

---

## `CacheHitPayload`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `key_hash` | `str` | ✓ | Opaque hash of the cache lookup key |
| `namespace` | `str` | ✓ | Cache namespace (e.g. `"prompts"`, `"responses"`) |
| `similarity_score` | `float` | ✓ | Semantic similarity score in `[0.0, 1.0]` |
| `ttl_remaining_seconds` | `int \| None` | — | Seconds until the entry expires |
| `cached_model` | `ModelInfo \| None` | — | Model that produced the cached response |
| `cost_saved` | `CostBreakdown \| None` | — | Estimated cost avoided by the cache hit |
| `tokens_saved` | `TokenUsage \| None` | — | Tokens avoided by the cache hit |
| `lookup_duration_ms` | `float \| None` | — | Cache lookup latency in milliseconds |

## `CacheMissPayload`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `key_hash` | `str` | ✓ | Opaque hash of the cache lookup key |
| `namespace` | `str` | ✓ | Cache namespace |
| `best_similarity_score` | `float \| None` | — | Nearest-neighbour score found (if any) |
| `similarity_threshold` | `float \| None` | — | Minimum score required for a hit |
| `lookup_duration_ms` | `float \| None` | — | Cache lookup latency in milliseconds |

## `CacheEvictedPayload`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `key_hash` | `str` | ✓ | Hash of the evicted cache key |
| `namespace` | `str` | ✓ | Cache namespace |
| `eviction_reason` | `str` | ✓ | One of `"ttl_expired"`, `"lru_eviction"`, `"manual_invalidation"`, `"capacity_exceeded"`, `"schema_upgrade"` |
| `entry_age_seconds` | `int \| None` | — | Age of the entry at eviction time |

## `CacheWrittenPayload`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `key_hash` | `str` | ✓ | Hash of the written cache key |
| `namespace` | `str` | ✓ | Cache namespace |
| `ttl_seconds` | `int` | ✓ | TTL assigned to the cache entry |
| `model` | `ModelInfo \| None` | — | Model that produced the cached response |
| `response_token_count` | `int \| None` | — | Token count of the cached response |
| `write_duration_ms` | `float \| None` | — | Cache write latency in milliseconds |

---

## Example

```python
from spanforge import Event, EventType
from spanforge.namespaces.cache import CacheHitPayload
from spanforge.namespaces.trace import ModelInfo, GenAISystem, TokenUsage

tokens_saved = TokenUsage(input_tokens=512, output_tokens=128, total_tokens=640)

payload = CacheHitPayload(
    key_hash="sha256:abc123def456",
    namespace="responses",
    similarity_score=0.97,
    ttl_remaining_seconds=1800,
    tokens_saved=tokens_saved,
    lookup_duration_ms=2.1,
)

event = Event(
    event_type=EventType.CACHE_HIT,
    source="my-app@1.0.0",
    org_id="org_01HX",
    payload=payload.to_dict(),
)
```
