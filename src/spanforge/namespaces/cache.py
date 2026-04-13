"""spanforge.namespaces.cache — Cache payload types (RFC-0001).

Classes
-------
CacheHitPayload     llm.cache.hit
CacheMissPayload    llm.cache.miss
CacheEvictedPayload llm.cache.evicted
CacheWrittenPayload llm.cache.written
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from spanforge.namespaces.trace import CostBreakdown, ModelInfo, TokenUsage

__all__ = [
    "CacheEvictedPayload",
    "CacheHitPayload",
    "CacheMissPayload",
    "CacheWrittenPayload",
]

_VALID_EVICTION_REASONS = frozenset({
    "ttl_expired", "lru_eviction", "manual_invalidation",
    "capacity_exceeded", "schema_upgrade",
})


@dataclass
class CacheHitPayload:
    """Payload for llm.cache.hit — semantic cache lookup succeeded."""

    key_hash: str
    namespace: str
    similarity_score: float
    ttl_remaining_seconds: int | None = None
    cached_model: ModelInfo | None = None
    cost_saved: CostBreakdown | None = None
    tokens_saved: TokenUsage | None = None
    lookup_duration_ms: float | None = None

    def __post_init__(self) -> None:
        if not self.key_hash:
            raise ValueError("CacheHitPayload.key_hash must be non-empty")
        if not self.namespace:
            raise ValueError("CacheHitPayload.namespace must be non-empty")
        if not (0.0 <= self.similarity_score <= 1.0):
            raise ValueError("CacheHitPayload.similarity_score must be in [0,1]")

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "key_hash": self.key_hash,
            "namespace": self.namespace,
            "similarity_score": self.similarity_score,
        }
        if self.ttl_remaining_seconds is not None:
            d["ttl_remaining_seconds"] = self.ttl_remaining_seconds
        if self.cached_model is not None:
            d["cached_model"] = self.cached_model.to_dict()
        if self.cost_saved is not None:
            d["cost_saved"] = self.cost_saved.to_dict()
        if self.tokens_saved is not None:
            d["tokens_saved"] = self.tokens_saved.to_dict()
        if self.lookup_duration_ms is not None:
            d["lookup_duration_ms"] = self.lookup_duration_ms
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CacheHitPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            key_hash=data["key_hash"],
            namespace=data["namespace"],
            similarity_score=float(data["similarity_score"]),
            ttl_remaining_seconds=int(data["ttl_remaining_seconds"]) if "ttl_remaining_seconds" in data else None,  # noqa: E501
            cached_model=ModelInfo.from_dict(data["cached_model"]) if "cached_model" in data else None,  # noqa: E501
            cost_saved=CostBreakdown.from_dict(data["cost_saved"]) if "cost_saved" in data else None,  # noqa: E501
            tokens_saved=TokenUsage.from_dict(data["tokens_saved"]) if "tokens_saved" in data else None,  # noqa: E501
            lookup_duration_ms=float(data["lookup_duration_ms"]) if "lookup_duration_ms" in data else None,  # noqa: E501
        )


@dataclass
class CacheMissPayload:
    """Payload for llm.cache.miss — semantic cache lookup failed."""

    key_hash: str
    namespace: str
    best_similarity_score: float | None = None
    similarity_threshold: float | None = None
    lookup_duration_ms: float | None = None

    def __post_init__(self) -> None:
        if not self.key_hash:
            raise ValueError("CacheMissPayload.key_hash must be non-empty")
        if not self.namespace:
            raise ValueError("CacheMissPayload.namespace must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {"key_hash": self.key_hash, "namespace": self.namespace}
        if self.best_similarity_score is not None:
            d["best_similarity_score"] = self.best_similarity_score
        if self.similarity_threshold is not None:
            d["similarity_threshold"] = self.similarity_threshold
        if self.lookup_duration_ms is not None:
            d["lookup_duration_ms"] = self.lookup_duration_ms
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CacheMissPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            key_hash=data["key_hash"],
            namespace=data["namespace"],
            best_similarity_score=float(data["best_similarity_score"]) if "best_similarity_score" in data else None,  # noqa: E501
            similarity_threshold=float(data["similarity_threshold"]) if "similarity_threshold" in data else None,  # noqa: E501
            lookup_duration_ms=float(data["lookup_duration_ms"]) if "lookup_duration_ms" in data else None,  # noqa: E501
        )


@dataclass
class CacheEvictedPayload:
    """Payload for llm.cache.evicted — a cache entry was removed."""

    key_hash: str
    namespace: str
    eviction_reason: str
    entry_age_seconds: int | None = None

    def __post_init__(self) -> None:
        if not self.key_hash:
            raise ValueError("CacheEvictedPayload.key_hash must be non-empty")
        if not self.namespace:
            raise ValueError("CacheEvictedPayload.namespace must be non-empty")
        if self.eviction_reason not in _VALID_EVICTION_REASONS:
            raise ValueError(
                f"CacheEvictedPayload.eviction_reason must be one of {sorted(_VALID_EVICTION_REASONS)}"  # noqa: E501
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "key_hash": self.key_hash,
            "namespace": self.namespace,
            "eviction_reason": self.eviction_reason,
        }
        if self.entry_age_seconds is not None:
            d["entry_age_seconds"] = self.entry_age_seconds
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CacheEvictedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            key_hash=data["key_hash"],
            namespace=data["namespace"],
            eviction_reason=data["eviction_reason"],
            entry_age_seconds=int(data["entry_age_seconds"]) if "entry_age_seconds" in data else None,  # noqa: E501
        )


@dataclass
class CacheWrittenPayload:
    """Payload for llm.cache.written — a response was written to cache."""

    key_hash: str
    namespace: str
    ttl_seconds: int
    model: ModelInfo | None = None
    response_token_count: int | None = None
    write_duration_ms: float | None = None

    def __post_init__(self) -> None:
        if not self.key_hash:
            raise ValueError("CacheWrittenPayload.key_hash must be non-empty")
        if not self.namespace:
            raise ValueError("CacheWrittenPayload.namespace must be non-empty")
        if not isinstance(self.ttl_seconds, int) or self.ttl_seconds < 0:
            raise ValueError("CacheWrittenPayload.ttl_seconds must be a non-negative int")

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "key_hash": self.key_hash,
            "namespace": self.namespace,
            "ttl_seconds": self.ttl_seconds,
        }
        if self.model is not None:
            d["model"] = self.model.to_dict()
        if self.response_token_count is not None:
            d["response_token_count"] = self.response_token_count
        if self.write_duration_ms is not None:
            d["write_duration_ms"] = self.write_duration_ms
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CacheWrittenPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            key_hash=data["key_hash"],
            namespace=data["namespace"],
            ttl_seconds=int(data["ttl_seconds"]),
            model=ModelInfo.from_dict(data["model"]) if "model" in data else None,
            response_token_count=int(data["response_token_count"]) if "response_token_count" in data else None,  # noqa: E501
            write_duration_ms=float(data["write_duration_ms"]) if "write_duration_ms" in data else None,  # noqa: E501
        )
