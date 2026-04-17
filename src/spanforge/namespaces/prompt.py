"""spanforge.namespaces.prompt — Prompt payload types (RFC-0001).

Classes
-------
PromptRenderedPayload       llm.prompt.rendered
PromptTemplateLoadedPayload llm.prompt.template.loaded
PromptVersionChangedPayload llm.prompt.version.changed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "PromptRenderedPayload",
    "PromptTemplateLoadedPayload",
    "PromptVersionChangedPayload",
]

_VALID_SOURCES = frozenset({"registry", "file", "database", "remote_url", "inline"})
_SHA256_HEX_LEN = 64  # SHA-256 hex digest length (characters)


@dataclass
class PromptRenderedPayload:
    """RFC-0001 — A prompt template was rendered with variables.

    ``rendered_hash`` is the SHA-256 of the fully-rendered prompt text.
    The rendered text MUST NOT be stored.
    """

    template_id: str
    version: str
    rendered_hash: str  # 64 lowercase hex chars, SHA-256 of rendered text
    variable_count: int | None = None
    variable_names: list[str] = field(default_factory=list)
    char_count: int | None = None
    token_estimate: int | None = None
    language: str | None = None
    span_id: str | None = None

    def __post_init__(self) -> None:
        if not self.template_id:
            raise ValueError("PromptRenderedPayload.template_id must be non-empty")
        if not self.version:
            raise ValueError("PromptRenderedPayload.version must be non-empty")
        if not self.rendered_hash or len(self.rendered_hash) != _SHA256_HEX_LEN:
            raise ValueError("PromptRenderedPayload.rendered_hash must be 64 hex chars (SHA-256)")

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "template_id": self.template_id,
            "version": self.version,
            "rendered_hash": self.rendered_hash,
        }
        if self.variable_count is not None:
            d["variable_count"] = self.variable_count
        if self.variable_names:
            d["variable_names"] = list(self.variable_names)
        if self.char_count is not None:
            d["char_count"] = self.char_count
        if self.token_estimate is not None:
            d["token_estimate"] = self.token_estimate
        if self.language is not None:
            d["language"] = self.language
        if self.span_id is not None:
            d["span_id"] = self.span_id
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PromptRenderedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            template_id=data["template_id"],
            version=data["version"],
            rendered_hash=data["rendered_hash"],
            variable_count=int(data["variable_count"]) if "variable_count" in data else None,
            variable_names=list(data.get("variable_names", [])),
            char_count=int(data["char_count"]) if "char_count" in data else None,
            token_estimate=int(data["token_estimate"]) if "token_estimate" in data else None,
            language=data.get("language"),
            span_id=data.get("span_id"),
        )


@dataclass
class PromptTemplateLoadedPayload:
    """RFC-0001 — A prompt template was loaded from a source."""

    template_id: str
    version: str
    source: str  # "registry"|"file"|"database"|"remote_url"|"inline"
    template_hash: str | None = None  # 64 hex chars
    load_duration_ms: float | None = None
    cache_hit: bool | None = None

    def __post_init__(self) -> None:
        if not self.template_id:
            raise ValueError("PromptTemplateLoadedPayload.template_id must be non-empty")
        if not self.version:
            raise ValueError("PromptTemplateLoadedPayload.version must be non-empty")
        if self.source not in _VALID_SOURCES:
            raise ValueError(
                f"PromptTemplateLoadedPayload.source must be one of {sorted(_VALID_SOURCES)}"
            )
        if self.template_hash is not None and len(self.template_hash) != _SHA256_HEX_LEN:
            raise ValueError("PromptTemplateLoadedPayload.template_hash must be 64 hex chars")

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "template_id": self.template_id,
            "version": self.version,
            "source": self.source,
        }
        if self.template_hash is not None:
            d["template_hash"] = self.template_hash
        if self.load_duration_ms is not None:
            d["load_duration_ms"] = self.load_duration_ms
        if self.cache_hit is not None:
            d["cache_hit"] = self.cache_hit
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PromptTemplateLoadedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            template_id=data["template_id"],
            version=data["version"],
            source=data["source"],
            template_hash=data.get("template_hash"),
            load_duration_ms=float(data["load_duration_ms"])
            if "load_duration_ms" in data
            else None,
            cache_hit=bool(data["cache_hit"]) if "cache_hit" in data else None,
        )


@dataclass
class PromptVersionChangedPayload:
    """RFC-0001 — A prompt template was promoted to a new version."""

    template_id: str
    previous_version: str
    new_version: str
    change_reason: str
    changed_by: str | None = None
    previous_hash: str | None = None  # 64 hex chars
    new_hash: str | None = None  # 64 hex chars

    def __post_init__(self) -> None:
        if not self.template_id:
            raise ValueError("PromptVersionChangedPayload.template_id must be non-empty")
        if not self.previous_version:
            raise ValueError("PromptVersionChangedPayload.previous_version must be non-empty")
        if not self.new_version:
            raise ValueError("PromptVersionChangedPayload.new_version must be non-empty")
        if not self.change_reason:
            raise ValueError("PromptVersionChangedPayload.change_reason must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "template_id": self.template_id,
            "previous_version": self.previous_version,
            "new_version": self.new_version,
            "change_reason": self.change_reason,
        }
        if self.changed_by is not None:
            d["changed_by"] = self.changed_by
        if self.previous_hash is not None:
            d["previous_hash"] = self.previous_hash
        if self.new_hash is not None:
            d["new_hash"] = self.new_hash
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PromptVersionChangedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            template_id=data["template_id"],
            previous_version=data["previous_version"],
            new_version=data["new_version"],
            change_reason=data["change_reason"],
            changed_by=data.get("changed_by"),
            previous_hash=data.get("previous_hash"),
            new_hash=data.get("new_hash"),
        )
