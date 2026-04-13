"""Tests for spanforge.models — Pydantic v2 model layer.

100% branch coverage target.
"""

from __future__ import annotations

import pytest

from tests.conftest import (
    FIXED_SPAN_ID,
    FIXED_TIMESTAMP,
    FIXED_TRACE_ID,
)
from spanforge import Event, EventType, Tags
from spanforge.event import SCHEMA_VERSION
from spanforge.ulid import generate as gen_ulid

# Guard: skip entire module if pydantic is not installed
pytest.importorskip("pydantic")

from pydantic import ValidationError

from spanforge.models import EventModel, TagsModel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SOURCE = "llm-trace@0.3.1"
_EVENT_TYPE = EventType.TRACE_SPAN_COMPLETED
_PAYLOAD: dict = {"span_name": "test", "status": "ok"}


def _valid_model_kwargs(**overrides) -> dict:
    """Return a minimal valid set of kwargs for EventModel construction."""
    return {
        "event_id": gen_ulid(),
        "event_type": _EVENT_TYPE,
        "timestamp": FIXED_TIMESTAMP,
        "source": _SOURCE,
        "payload": dict(_PAYLOAD),
        **overrides,
    }


# ===========================================================================
# TagsModel
# ===========================================================================


@pytest.mark.unit
class TestTagsModel:
    def test_construction_with_extra_fields(self) -> None:
        tags = TagsModel(env="prod", model="gpt-4o")
        assert tags.model_extra == {"env": "prod", "model": "gpt-4o"}

    def test_from_tags_roundtrip(self) -> None:
        original = Tags(env="production", region="us-east-1")
        model = TagsModel.from_tags(original)
        assert model.model_extra["env"] == "production"
        assert model.model_extra["region"] == "us-east-1"

    def test_to_tags_produces_tags_instance(self) -> None:
        model = TagsModel(env="staging")
        result = model.to_tags()
        assert isinstance(result, Tags)
        assert result["env"] == "staging"

    def test_to_tags_roundtrip(self) -> None:
        original = Tags(x="1", y="2")
        model = TagsModel.from_tags(original)
        restored = model.to_tags()
        assert dict(restored) == {"x": "1", "y": "2"}

    def test_model_dump(self) -> None:
        model = TagsModel(k="v")
        dumped = model.model_dump()
        assert dumped == {"k": "v"}

    def test_frozen_immutability(self) -> None:
        """Frozen Pydantic v2 models raise PydanticFrozenInstanceError (a ValueError)."""
        model = TagsModel(env="prod")
        with pytest.raises((ValidationError, ValueError)):
            model.env = "staging"  # type: ignore[misc]


# ===========================================================================
# EventModel — construction
# ===========================================================================


@pytest.mark.unit
class TestEventModelConstruction:
    def test_minimal_event_model(self) -> None:
        m = EventModel(**_valid_model_kwargs())
        assert m.event_type == str(_EVENT_TYPE)
        assert m.source == _SOURCE
        assert m.payload == _PAYLOAD
        assert m.schema_version == SCHEMA_VERSION

    def test_default_schema_version(self) -> None:
        m = EventModel(**_valid_model_kwargs())
        assert m.schema_version == SCHEMA_VERSION

    def test_all_optional_fields_default_none(self) -> None:
        m = EventModel(**_valid_model_kwargs())
        assert m.trace_id is None
        assert m.span_id is None
        assert m.parent_span_id is None
        assert m.org_id is None
        assert m.team_id is None
        assert m.actor_id is None
        assert m.session_id is None
        assert m.tags is None
        assert m.checksum is None
        assert m.signature is None
        assert m.prev_id is None

    def test_all_optional_fields_populated(self) -> None:
        prev = gen_ulid()
        m = EventModel(
            **_valid_model_kwargs(
                trace_id=FIXED_TRACE_ID,
                span_id=FIXED_SPAN_ID,
                parent_span_id=FIXED_SPAN_ID,
                org_id="org_acme",
                team_id="team_eng",
                actor_id="usr_alice",
                session_id="sess_001",
                tags=TagsModel(env="prod"),
                checksum="sha256:abc123",
                signature="sig:xyz",
                prev_id=prev,
            )
        )
        assert m.trace_id == FIXED_TRACE_ID
        assert m.span_id == FIXED_SPAN_ID
        assert m.parent_span_id == FIXED_SPAN_ID
        assert m.org_id == "org_acme"
        assert m.team_id == "team_eng"
        assert m.actor_id == "usr_alice"
        assert m.session_id == "sess_001"
        assert isinstance(m.tags, TagsModel)
        assert m.checksum == "sha256:abc123"
        assert m.signature == "sig:xyz"
        assert m.prev_id == prev

    def test_immutable_frozen_model(self) -> None:
        m = EventModel(**_valid_model_kwargs())
        with pytest.raises(ValidationError):
            m.source = "other@1.0.0"  # type: ignore[misc]


# ===========================================================================
# EventModel.from_event()  # noqa: ERA001
# ===========================================================================


@pytest.mark.unit
class TestEventModelFromEvent:
    def test_from_minimal_event(self) -> None:
        event = Event(
            event_type=_EVENT_TYPE,
            source=_SOURCE,
            payload=dict(_PAYLOAD),
            timestamp=FIXED_TIMESTAMP,
        )
        model = EventModel.from_event(event)
        assert model.event_id == event.event_id
        assert model.event_type == event.event_type
        assert model.source == event.source
        assert model.timestamp == event.timestamp
        assert model.payload == dict(event.payload)
        assert model.tags is None

    def test_from_full_event_with_tags(self) -> None:
        event = Event(
            event_type=_EVENT_TYPE,
            source=_SOURCE,
            payload=dict(_PAYLOAD),
            timestamp=FIXED_TIMESTAMP,
            tags=Tags(env="prod", region="us"),
            trace_id=FIXED_TRACE_ID,
            span_id=FIXED_SPAN_ID,
            org_id="org_1",
            actor_id="usr_1",
        )
        model = EventModel.from_event(event)
        assert isinstance(model.tags, TagsModel)
        assert model.tags.to_tags()["env"] == "prod"
        assert model.trace_id == FIXED_TRACE_ID
        assert model.span_id == FIXED_SPAN_ID
        assert model.org_id == "org_1"
        assert model.actor_id == "usr_1"

    def test_from_event_with_prev_id(self) -> None:
        prev = gen_ulid()
        event = Event(
            event_type=_EVENT_TYPE,
            source=_SOURCE,
            payload=dict(_PAYLOAD),
            timestamp=FIXED_TIMESTAMP,
            prev_id=prev,
        )
        model = EventModel.from_event(event)
        assert model.prev_id == prev


# ===========================================================================
# EventModel.to_event()  # noqa: ERA001
# ===========================================================================


@pytest.mark.unit
class TestEventModelToEvent:
    def test_to_event_returns_event_instance(self) -> None:
        m = EventModel(**_valid_model_kwargs())
        event = m.to_event()
        assert isinstance(event, Event)

    def test_to_event_preserves_required_fields(self) -> None:
        kwargs = _valid_model_kwargs()
        m = EventModel(**kwargs)
        event = m.to_event()
        assert event.event_id == m.event_id
        assert event.event_type == m.event_type
        assert event.source == m.source
        assert event.timestamp == m.timestamp
        assert event.payload == m.payload

    def test_to_event_skips_none_optional_fields(self) -> None:
        m = EventModel(**_valid_model_kwargs())
        event = m.to_event()
        # None fields should NOT be set on the resulting Event
        assert event.trace_id is None
        assert event.org_id is None
        assert event.tags is None

    def test_to_event_with_tags(self) -> None:
        m = EventModel(**_valid_model_kwargs(tags=TagsModel(env="staging")))
        event = m.to_event()
        assert event.tags is not None
        assert event.tags["env"] == "staging"

    def test_to_event_without_tags(self) -> None:
        """Explicit None → tags branch returns None."""
        m = EventModel(**_valid_model_kwargs(tags=None))
        event = m.to_event()
        assert event.tags is None

    def test_to_event_with_all_optional_set(self) -> None:
        prev = gen_ulid()
        m = EventModel(
            **_valid_model_kwargs(
                trace_id=FIXED_TRACE_ID,
                span_id=FIXED_SPAN_ID,
                parent_span_id=FIXED_SPAN_ID,
                org_id="org_x",
                team_id="team_y",
                actor_id="usr_z",
                session_id="sess_w",
                prev_id=prev,
                checksum="sha256:abc",
                signature="sig:def",
            )
        )
        event = m.to_event()
        assert event.trace_id == FIXED_TRACE_ID
        assert event.span_id == FIXED_SPAN_ID
        assert event.parent_span_id == FIXED_SPAN_ID
        assert event.org_id == "org_x"
        assert event.team_id == "team_y"
        assert event.actor_id == "usr_z"
        assert event.session_id == "sess_w"
        assert event.prev_id == prev

    def test_roundtrip_from_event_to_event(self) -> None:
        original = Event(
            event_type=_EVENT_TYPE,
            source=_SOURCE,
            payload=dict(_PAYLOAD),
            timestamp=FIXED_TIMESTAMP,
            tags=Tags(env="prod"),
            trace_id=FIXED_TRACE_ID,
            span_id=FIXED_SPAN_ID,
        )
        model = EventModel.from_event(original)
        restored = model.to_event()
        assert restored.event_id == original.event_id
        assert restored.event_type == original.event_type
        assert restored.source == original.source
        assert restored.timestamp == original.timestamp
        assert dict(restored.payload) == dict(original.payload)
        assert restored.trace_id == original.trace_id
        assert restored.span_id == original.span_id
        assert restored.tags is not None
        assert restored.tags["env"] == "prod"


# ===========================================================================
# EventModel field validators — happy paths
# ===========================================================================


@pytest.mark.unit
class TestEventModelValidatorsHappy:
    def test_schema_version_two_part(self) -> None:
        m = EventModel(**_valid_model_kwargs(schema_version="1.0"))
        assert m.schema_version == "1.0"

    def test_schema_version_three_part(self) -> None:
        m = EventModel(**_valid_model_kwargs(schema_version="1.0.1"))
        assert m.schema_version == "1.0.1"

    def test_event_id_valid_ulid(self) -> None:
        ulid = gen_ulid()
        m = EventModel(**_valid_model_kwargs(event_id=ulid))
        assert m.event_id == ulid

    def test_event_type_valid_pattern(self) -> None:
        m = EventModel(**_valid_model_kwargs(event_type="llm.trace.span.completed"))
        assert m.event_type == "llm.trace.span.completed"

    def test_event_type_extension_prefix(self) -> None:
        m = EventModel(**_valid_model_kwargs(event_type="x.myco.widget.created"))
        assert m.event_type == "x.myco.widget.created"

    def test_timestamp_valid(self) -> None:
        m = EventModel(**_valid_model_kwargs(timestamp=FIXED_TIMESTAMP))
        assert m.timestamp == FIXED_TIMESTAMP

    def test_source_valid(self) -> None:
        m = EventModel(**_valid_model_kwargs(source="llm-trace@0.3.1"))
        assert m.source == "llm-trace@0.3.1"

    def test_trace_id_valid(self) -> None:
        m = EventModel(**_valid_model_kwargs(trace_id=FIXED_TRACE_ID))
        assert m.trace_id == FIXED_TRACE_ID

    def test_trace_id_none_valid(self) -> None:
        m = EventModel(**_valid_model_kwargs(trace_id=None))
        assert m.trace_id is None

    def test_span_id_valid(self) -> None:
        m = EventModel(**_valid_model_kwargs(span_id=FIXED_SPAN_ID))
        assert m.span_id == FIXED_SPAN_ID

    def test_parent_span_id_valid(self) -> None:
        m = EventModel(**_valid_model_kwargs(parent_span_id=FIXED_SPAN_ID))
        assert m.parent_span_id == FIXED_SPAN_ID

    def test_optional_ids_non_empty(self) -> None:
        m = EventModel(**_valid_model_kwargs(org_id="org_1", team_id="team_1", actor_id="u", session_id="s"))  # noqa: E501
        assert m.org_id == "org_1"

    def test_prev_id_valid_ulid(self) -> None:
        prev = gen_ulid()
        m = EventModel(**_valid_model_kwargs(prev_id=prev))
        assert m.prev_id == prev

    def test_prev_id_none_valid(self) -> None:
        m = EventModel(**_valid_model_kwargs(prev_id=None))
        assert m.prev_id is None


# ===========================================================================
# EventModel field validators — error paths
# ===========================================================================


@pytest.mark.unit
class TestEventModelValidatorsErrors:
    def test_bad_schema_version_raises(self) -> None:
        with pytest.raises(ValidationError, match="schema_version"):
            EventModel(**_valid_model_kwargs(schema_version="not-semver"))

    def test_schema_version_letters_only_raises(self) -> None:
        with pytest.raises(ValidationError):
            EventModel(**_valid_model_kwargs(schema_version="abc.def"))

    def test_bad_event_id_raises(self) -> None:
        with pytest.raises(ValidationError, match="event_id"):
            EventModel(**_valid_model_kwargs(event_id="not-a-ulid-123456789"))

    def test_bad_event_type_raises(self) -> None:
        with pytest.raises(ValidationError, match="event_type"):
            EventModel(**_valid_model_kwargs(event_type="bad_type"))

    def test_event_type_no_dots_raises(self) -> None:
        with pytest.raises(ValidationError):
            EventModel(**_valid_model_kwargs(event_type="nodots"))

    def test_bad_timestamp_raises(self) -> None:
        with pytest.raises(ValidationError, match="timestamp"):
            EventModel(**_valid_model_kwargs(timestamp="2026-03-01 12:00:00"))

    def test_timestamp_without_z_raises(self) -> None:
        with pytest.raises(ValidationError):
            EventModel(**_valid_model_kwargs(timestamp="2026-03-01T12:00:00.000000"))

    def test_source_two_part_semver_raises(self) -> None:
        """EventModel.source requires 3-part semver (unlike Event.validate which allows 2-part)."""
        with pytest.raises(ValidationError, match="source"):
            EventModel(**_valid_model_kwargs(source="tool@0.1"))

    def test_source_invalid_pattern_raises(self) -> None:
        with pytest.raises(ValidationError):
            EventModel(**_valid_model_kwargs(source="InvalidTool@1.0.0"))

    def test_source_missing_version_raises(self) -> None:
        with pytest.raises(ValidationError):
            EventModel(**_valid_model_kwargs(source="toolname"))

    def test_empty_payload_raises(self) -> None:
        with pytest.raises(ValidationError, match="payload"):
            EventModel(**_valid_model_kwargs(payload={}))

    def test_bad_trace_id_wrong_length_raises(self) -> None:
        with pytest.raises(ValidationError, match="trace_id"):
            EventModel(**_valid_model_kwargs(trace_id="abc"))

    def test_bad_trace_id_uppercase_raises(self) -> None:
        with pytest.raises(ValidationError):
            EventModel(**_valid_model_kwargs(trace_id="A" * 32))

    def test_bad_span_id_wrong_length_raises(self) -> None:
        with pytest.raises(ValidationError, match="span_id"):
            EventModel(**_valid_model_kwargs(span_id="abc"))

    def test_bad_parent_span_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            EventModel(**_valid_model_kwargs(parent_span_id="ZZZZZZZZZZZZZZZZ"))

    def test_empty_org_id_raises(self) -> None:
        with pytest.raises(ValidationError, match="org_id"):
            EventModel(**_valid_model_kwargs(org_id="   "))

    def test_empty_team_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            EventModel(**_valid_model_kwargs(team_id=""))

    def test_empty_actor_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            EventModel(**_valid_model_kwargs(actor_id=""))

    def test_empty_session_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            EventModel(**_valid_model_kwargs(session_id="   "))

    def test_bad_prev_id_raises(self) -> None:
        with pytest.raises(ValidationError, match="prev_id"):
            EventModel(**_valid_model_kwargs(prev_id="not-a-ulid-00000"))


# ===========================================================================
# JSON Schema
# ===========================================================================


@pytest.mark.unit
class TestEventModelJsonSchema:
    def test_model_json_schema_returns_dict(self) -> None:
        schema = EventModel.model_json_schema()
        assert isinstance(schema, dict)

    def test_schema_contains_required_fields(self) -> None:
        schema = EventModel.model_json_schema()
        props = schema.get("properties", {})
        for field in ("event_id", "event_type", "timestamp", "source", "payload"):
            assert field in props, f"Missing field '{field}' in JSON schema"

    def test_schema_contains_optional_fields(self) -> None:
        schema = EventModel.model_json_schema()
        props = schema.get("properties", {})
        for field in ("trace_id", "span_id", "org_id", "team_id", "actor_id", "tags"):
            assert field in props, f"Missing optional field '{field}' in JSON schema"

    def test_schema_title_present(self) -> None:
        schema = EventModel.model_json_schema()
        assert "title" in schema or "properties" in schema
