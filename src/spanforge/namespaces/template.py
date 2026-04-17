"""spanforge.namespaces.template — Template payload types (RFC-0001).

Classes
-------
TemplateRegisteredPayload       llm.template.registered
TemplateVariableBoundPayload    llm.template.variable.bound
TemplateValidationFailedPayload llm.template.validation.failed
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "TemplateRegisteredPayload",
    "TemplateValidationFailedPayload",
    "TemplateVariableBoundPayload",
]

_VALID_VALUE_TYPES = frozenset({"string", "integer", "float", "boolean", "array", "object", "null"})
_VALID_FAILURE_TYPES = frozenset(
    {
        "missing_variable",
        "type_mismatch",
        "hash_mismatch",
        "version_not_found",
        "syntax_error",
        "schema_violation",
    }
)

_SHA256_HEX_LEN = 64  # SHA-256 hex digest length (characters)


@dataclass
class TemplateRegisteredPayload:
    """RFC-0001 — A prompt template was registered in the registry."""

    template_id: str
    version: str
    template_hash: str  # 64 lowercase hex chars, SHA-256 of template source
    variable_names: list[str] = field(default_factory=list)
    variable_count: int | None = None
    language: str | None = None
    char_count: int | None = None
    registered_by: str | None = None
    is_active: bool | None = None
    tags: dict[str, str] | None = None

    def __post_init__(self) -> None:
        if not self.template_id:
            raise ValueError("TemplateRegisteredPayload.template_id must be non-empty")
        if not self.version:
            raise ValueError("TemplateRegisteredPayload.version must be non-empty")
        if not self.template_hash or len(self.template_hash) != _SHA256_HEX_LEN:
            raise ValueError(
                "TemplateRegisteredPayload.template_hash must be 64 hex chars (SHA-256)"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "template_id": self.template_id,
            "version": self.version,
            "template_hash": self.template_hash,
        }
        if self.variable_names:
            d["variable_names"] = list(self.variable_names)
        if self.variable_count is not None:
            d["variable_count"] = self.variable_count
        if self.language is not None:
            d["language"] = self.language
        if self.char_count is not None:
            d["char_count"] = self.char_count
        if self.registered_by is not None:
            d["registered_by"] = self.registered_by
        if self.is_active is not None:
            d["is_active"] = self.is_active
        if self.tags is not None:
            d["tags"] = dict(self.tags)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TemplateRegisteredPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            template_id=data["template_id"],
            version=data["version"],
            template_hash=data["template_hash"],
            variable_names=list(data.get("variable_names", [])),
            variable_count=int(data["variable_count"]) if "variable_count" in data else None,
            language=data.get("language"),
            char_count=int(data["char_count"]) if "char_count" in data else None,
            registered_by=data.get("registered_by"),
            is_active=bool(data["is_active"]) if "is_active" in data else None,
            tags=dict(data["tags"]) if "tags" in data else None,
        )


@dataclass
class TemplateVariableBoundPayload:
    """RFC-0001 — A variable was bound to a value for template rendering.

    ``value_hash`` stores a SHA-256 hash of the value. For sensitive variables,
    the raw value MUST NOT be stored.
    """

    template_id: str
    version: str
    variable_name: str
    value_type: str | None = None  # "string"|"integer"|"float"|"boolean"|"array"|"object"|"null"
    value_length: int | None = None
    value_hash: str | None = None  # 64 hex chars, SHA-256
    is_sensitive: bool | None = None
    span_id: str | None = None

    def __post_init__(self) -> None:
        if not self.template_id:
            raise ValueError("TemplateVariableBoundPayload.template_id must be non-empty")
        if not self.version:
            raise ValueError("TemplateVariableBoundPayload.version must be non-empty")
        if not self.variable_name:
            raise ValueError("TemplateVariableBoundPayload.variable_name must be non-empty")
        if self.value_type is not None and self.value_type not in _VALID_VALUE_TYPES:
            raise ValueError(
                f"TemplateVariableBoundPayload.value_type must be one of {sorted(_VALID_VALUE_TYPES)}"
            )
        if self.value_hash is not None and len(self.value_hash) != _SHA256_HEX_LEN:
            raise ValueError(
                "TemplateVariableBoundPayload.value_hash must be 64 hex chars (SHA-256)"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "template_id": self.template_id,
            "version": self.version,
            "variable_name": self.variable_name,
        }
        if self.value_type is not None:
            d["value_type"] = self.value_type
        if self.value_length is not None:
            d["value_length"] = self.value_length
        if self.value_hash is not None:
            d["value_hash"] = self.value_hash
        if self.is_sensitive is not None:
            d["is_sensitive"] = self.is_sensitive
        if self.span_id is not None:
            d["span_id"] = self.span_id
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TemplateVariableBoundPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            template_id=data["template_id"],
            version=data["version"],
            variable_name=data["variable_name"],
            value_type=data.get("value_type"),
            value_length=int(data["value_length"]) if "value_length" in data else None,
            value_hash=data.get("value_hash"),
            is_sensitive=bool(data["is_sensitive"]) if "is_sensitive" in data else None,
            span_id=data.get("span_id"),
        )


@dataclass
class TemplateValidationFailedPayload:
    """RFC-0001 — Template validation failed during rendering or registration."""

    template_id: str
    version: str
    failure_reason: str
    failure_type: str | None = None

    def __post_init__(self) -> None:
        if not self.template_id:
            raise ValueError("TemplateValidationFailedPayload.template_id must be non-empty")
        if not self.version:
            raise ValueError("TemplateValidationFailedPayload.version must be non-empty")
        if not self.failure_reason:
            raise ValueError("TemplateValidationFailedPayload.failure_reason must be non-empty")
        if self.failure_type is not None and self.failure_type not in _VALID_FAILURE_TYPES:
            raise ValueError(
                f"TemplateValidationFailedPayload.failure_type must be one of {sorted(_VALID_FAILURE_TYPES)}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "template_id": self.template_id,
            "version": self.version,
            "failure_reason": self.failure_reason,
        }
        if self.failure_type is not None:
            d["failure_type"] = self.failure_type
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TemplateValidationFailedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            template_id=data["template_id"],
            version=data["version"],
            failure_reason=data["failure_reason"],
            failure_type=data.get("failure_type"),
        )
