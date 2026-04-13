"""Pydantic v2 model layer for spanforge events.

This module provides Pydantic v2 models that mirror the :class:`~spanforge.event.Event`
envelope with strict field-level validation and bidirectional conversion.

The model layer is **optional** — it requires ``pydantic>=2.7`` which is not a
core dependency.  Install it with::

    pip install "spanforge[pydantic]"

Design goals
------------
* All field validation is equivalent to :meth:`~spanforge.event.Event.validate`,
  giving callers a familiar API while leveraging Pydantic's declarative style.
* :class:`EventModel` is immutable (``frozen=True``).
* :meth:`EventModel.from_event` and :meth:`EventModel.to_event` provide lossless
  round-trips.
* :meth:`EventModel.model_json_schema` exports a full JSON Schema (for Phase 5
  schema publication).

Example::

    from spanforge import Event, EventType
    from spanforge.models import EventModel

    event = Event(
        event_type=EventType.TRACE_SPAN_COMPLETED,
        source="llm-trace@0.3.1",
        payload={"status": "ok"},
    )
    model = EventModel.from_event(event)
    print(model.model_json_schema())
    restored = model.to_event()
    assert restored.event_id == event.event_id
"""

from __future__ import annotations

import re
from typing import Any

try:
    from pydantic import BaseModel, ConfigDict, Field, field_validator
    from pydantic import ValidationError as _PydanticValidationError  # noqa: F401
except ImportError as _import_err:  # pragma: no cover
    raise ImportError(
        "pydantic>=2.7 is required for spanforge.models. "
        "Install it: pip install \"spanforge[pydantic]\""
    ) from _import_err

from spanforge.event import SCHEMA_VERSION, Event, Tags
from spanforge.types import EVENT_TYPE_PATTERN
from spanforge.ulid import validate as _validate_ulid

__all__ = ["EventModel", "TagsModel"]

# ---------------------------------------------------------------------------
# Validation patterns (must stay in sync with spanforge/event.py)
# ---------------------------------------------------------------------------

_SEMVER_RE: re.Pattern[str] = re.compile(
    r"^\d+\.\d+(?:\.\d+)?(?:[.-][a-zA-Z0-9.]+)?$"
)
_SOURCE_RE: re.Pattern[str] = re.compile(
    r"^[a-z][a-z0-9\-]*@\d+\.\d+\.\d+$"
)
_TIMESTAMP_RE: re.Pattern[str] = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
_TRACE_ID_RE: re.Pattern[str] = re.compile(r"^[0-9a-f]{32}$")
_SPAN_ID_RE: re.Pattern[str] = re.compile(r"^[0-9a-f]{16}$")
_EVENT_TYPE_RE: re.Pattern[str] = re.compile(EVENT_TYPE_PATTERN)


# ---------------------------------------------------------------------------
# TagsModel
# ---------------------------------------------------------------------------


class TagsModel(BaseModel):
    """Pydantic model for event tags.

    Allows arbitrary ``str → str`` key-value pairs as extra fields.  All
    values must be strings; non-string values are rejected by Pydantic.

    Example::

        tags = TagsModel(env="production", model="gpt-4o")
        tags.model_dump()  # {"env": "production", "model": "gpt-4o"}
    """

    model_config = ConfigDict(frozen=True, extra="allow")

    @classmethod
    def from_tags(cls, tags: Tags) -> TagsModel:
        """Construct from a :class:`~spanforge.event.Tags` instance.

        Args:
            tags: A :class:`~spanforge.event.Tags` instance.

        Returns:
            A corresponding :class:`TagsModel`.
        """
        return cls(**dict(tags))

    def to_tags(self) -> Tags:
        """Convert back to a :class:`~spanforge.event.Tags` instance.

        Returns:
            A new :class:`~spanforge.event.Tags` with the same key-value pairs.
        """
        return Tags(**self.model_dump())


# ---------------------------------------------------------------------------
# EventModel
# ---------------------------------------------------------------------------


class EventModel(BaseModel):
    """Pydantic v2 model for the spanforge event envelope.

    Each field carries a Pydantic ``Field`` description and is validated by a
    ``@field_validator``.  The model is frozen (immutable after construction).

    Validation rules are equivalent to those enforced by
    :meth:`~spanforge.event.Event.validate`, so ``EventModel.from_event(event)``
    succeeds for any event that passes :meth:`~spanforge.event.Event.validate`.

    Args:
        schema_version: Schema version string (e.g. ``"1.0"``).
        event_id:       26-character ULID.
        event_type:     Namespaced event type (e.g. ``"llm.trace.span.completed"``).
        timestamp:      UTC ISO-8601 timestamp (e.g. ``"2026-03-01T12:00:00.000000Z"``).
        source:         Tool name + version (e.g. ``"llm-trace@0.3.1"``).
        payload:        Non-empty dict of event-type-specific data.
        trace_id:       Optional 32-char hex OpenTelemetry trace ID.
        span_id:        Optional 16-char hex OpenTelemetry span ID.
        parent_span_id: Optional 16-char hex parent span ID.
        org_id:         Optional organisation identifier.
        team_id:        Optional team identifier.
        actor_id:       Optional user/service identifier.
        session_id:     Optional session/conversation identifier.
        tags:           Optional :class:`TagsModel` with arbitrary metadata.
        checksum:       Optional SHA-256 payload checksum.
        signature:      Optional HMAC-SHA256 audit chain signature.
        prev_id:        Optional ULID of preceding event in audit chain.

    Example::

        from spanforge.models import EventModel

        model = EventModel(
            event_id="01ARYZ3NDEKTSV4RRFFQ69G5FAV",
            event_type="llm.trace.span.completed",
            timestamp="2026-03-01T12:00:00.000000Z",
            source="llm-trace@0.3.1",
            payload={"status": "ok"},
        )
    """

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    schema_version: str = Field(
        default=SCHEMA_VERSION,
        description="Schema version string, e.g. '1.0'.",
    )
    event_id: str = Field(
        description="26-character Crockford Base32 ULID event identifier.",
    )
    event_type: str = Field(
        description="Namespaced event type, e.g. 'llm.trace.span.completed'.",
    )
    timestamp: str = Field(
        description="UTC ISO-8601 timestamp, e.g. '2026-03-01T12:00:00.000000Z'.",
    )
    source: str = Field(
        description="Source tool and version, e.g. 'llm-trace@0.3.1'.",
    )
    payload: dict[str, Any] = Field(
        description="Non-empty dict of event-type-specific data.",
    )
    trace_id: str | None = Field(
        default=None,
        description="OpenTelemetry trace ID — 32 lowercase hex characters.",
    )
    span_id: str | None = Field(
        default=None,
        description="OpenTelemetry span ID — 16 lowercase hex characters.",
    )
    parent_span_id: str | None = Field(
        default=None,
        description="Parent span ID — 16 lowercase hex characters.",
    )
    org_id: str | None = Field(
        default=None,
        description="Organisation identifier (non-empty string).",
    )
    team_id: str | None = Field(
        default=None,
        description="Team identifier within the organisation (non-empty string).",
    )
    actor_id: str | None = Field(
        default=None,
        description="User or service actor identifier (non-empty string).",
    )
    session_id: str | None = Field(
        default=None,
        description="Session or conversation identifier (non-empty string).",
    )
    tags: TagsModel | None = Field(
        default=None,
        description="Arbitrary string key-value metadata tags.",
    )
    checksum: str | None = Field(
        default=None,
        description="SHA-256 payload checksum (prefixed 'sha256:').",
    )
    signature: str | None = Field(
        default=None,
        description="HMAC-SHA256 audit chain signature (set by spanforge.signing).",
    )
    prev_id: str | None = Field(
        default=None,
        description="ULID of the preceding event in the tamper-evident audit chain.",
    )

    # ------------------------------------------------------------------
    # Field validators
    # ------------------------------------------------------------------

    @field_validator("schema_version")
    @classmethod
    def _check_schema_version(cls, v: str) -> str:
        if not _SEMVER_RE.match(v):
            raise ValueError(
                f"schema_version must match SemVer pattern (e.g. '1.0'), got {v!r}"
            )
        return v

    @field_validator("event_id")
    @classmethod
    def _check_event_id(cls, v: str) -> str:
        if not _validate_ulid(v):
            raise ValueError(
                "event_id must be a valid 26-character ULID (Crockford Base32)"
            )
        return v

    @field_validator("event_type")
    @classmethod
    def _check_event_type(cls, v: str) -> str:
        if not _EVENT_TYPE_RE.match(v):
            raise ValueError(
                "event_type must follow 'llm.<namespace>.<entity>.<action>' "
                "or 'x.<company>.<…>' pattern"
            )
        return v

    @field_validator("timestamp")
    @classmethod
    def _check_timestamp(cls, v: str) -> str:
        if not _TIMESTAMP_RE.match(v):
            raise ValueError(
                "timestamp must be a UTC ISO-8601 string ending in 'Z', "
                f"e.g. '2026-03-01T12:00:00.000000Z', got {v!r}"
            )
        return v

    @field_validator("source")
    @classmethod
    def _check_source(cls, v: str) -> str:
        if not _SOURCE_RE.match(v):
            raise ValueError(
                "source must match 'tool-name@semver' pattern (full 3-part semver), "
                f"e.g. 'llm-trace@0.3.1', got {v!r}"
            )
        return v

    @field_validator("payload")
    @classmethod
    def _check_payload(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not v:
            raise ValueError("payload must be a non-empty dict")
        return v

    @field_validator("trace_id")
    @classmethod
    def _check_trace_id(cls, v: str | None) -> str | None:
        if v is not None and not _TRACE_ID_RE.match(v):
            raise ValueError(
                "trace_id must be exactly 32 lowercase hex characters"
            )
        return v

    @field_validator("span_id", "parent_span_id")
    @classmethod
    def _check_span_id(cls, v: str | None) -> str | None:
        if v is not None and not _SPAN_ID_RE.match(v):
            raise ValueError(
                "span_id / parent_span_id must be exactly 16 lowercase hex characters"
            )
        return v

    @field_validator("org_id", "team_id", "actor_id", "session_id")
    @classmethod
    def _check_string_id(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("org_id / team_id / actor_id / session_id must be non-empty")
        return v

    @field_validator("prev_id")
    @classmethod
    def _check_prev_id(cls, v: str | None) -> str | None:
        if v is not None and not _validate_ulid(v):
            raise ValueError(
                "prev_id must be a valid 26-character ULID (Crockford Base32)"
            )
        return v

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    @classmethod
    def from_event(cls, event: Event) -> EventModel:
        """Construct an :class:`EventModel` from an :class:`~spanforge.event.Event`.

        Args:
            event: A validated or unvalidated :class:`~spanforge.event.Event`.

        Returns:
            A new :class:`EventModel` with all fields populated.

        Raises:
            pydantic.ValidationError: If the event contains invalid field values.

        Example::

            model = EventModel.from_event(event)
        """
        tags_model: TagsModel | None = (
            TagsModel.from_tags(event.tags) if event.tags is not None else None
        )
        return cls(
            schema_version=event.schema_version,
            event_id=event.event_id,
            event_type=event.event_type,
            timestamp=event.timestamp,
            source=event.source,
            payload=dict(event.payload),
            trace_id=event.trace_id,
            span_id=event.span_id,
            parent_span_id=event.parent_span_id,
            org_id=event.org_id,
            team_id=event.team_id,
            actor_id=event.actor_id,
            session_id=event.session_id,
            tags=tags_model,
            checksum=event.checksum,
            signature=event.signature,
            prev_id=event.prev_id,
        )

    def to_event(self) -> Event:
        """Convert this model back to an :class:`~spanforge.event.Event`.

        The returned event has the same field values as this model.  Call
        :meth:`~spanforge.event.Event.validate` if you want to re-run all
        built-in validators (they are equivalent to those already applied by
        Pydantic during construction of this model).

        Returns:
            A new :class:`~spanforge.event.Event` instance.

        Example::

            event = model.to_event()
            assert event.event_id == model.event_id
        """
        tags: Tags | None = (
            self.tags.to_tags() if self.tags is not None else None
        )
        kwargs: dict[str, Any] = {
            k: v
            for k, v in {
                "schema_version": self.schema_version,
                "event_id": self.event_id,
                "event_type": self.event_type,
                "timestamp": self.timestamp,
                "source": self.source,
                "payload": dict(self.payload),
                "trace_id": self.trace_id,
                "span_id": self.span_id,
                "parent_span_id": self.parent_span_id,
                "org_id": self.org_id,
                "team_id": self.team_id,
                "actor_id": self.actor_id,
                "session_id": self.session_id,
                "tags": tags,
                "checksum": self.checksum,
                "signature": self.signature,
                "prev_id": self.prev_id,
            }.items()
            if v is not None
        }
        return Event(**kwargs)
