"""Tests for spanforge.exceptions — exception hierarchy and message quality.

100% coverage target.
"""

from __future__ import annotations

import pytest

from spanforge.exceptions import (
    DeserializationError,
    EventTypeError,
    LLMSchemaError,
    SchemaValidationError,
    SerializationError,
    ULIDError,
)


@pytest.mark.unit
class TestLLMSchemaError:
    def test_is_exception(self) -> None:
        assert issubclass(LLMSchemaError, Exception)

    def test_can_raise(self) -> None:
        with pytest.raises(LLMSchemaError):
            raise LLMSchemaError("base error")

    def test_hierarchy_catchable(self) -> None:
        """All subclasses must be catchable via LLMSchemaError."""
        errors = [
            SchemaValidationError("field", "val", "reason"),
            ULIDError("detail"),
            SerializationError("id-001", "reason"),
            DeserializationError("reason"),
            EventTypeError("type", "reason"),
        ]
        for err in errors:
            with pytest.raises(LLMSchemaError):
                raise err


@pytest.mark.unit
class TestSchemaValidationError:
    def test_attributes(self) -> None:
        exc = SchemaValidationError("event_id", "bad-value", "must be a ULID")
        assert exc.field == "event_id"
        assert exc.received == "bad-value"
        assert exc.reason == "must be a ULID"

    def test_message_contains_field(self) -> None:
        exc = SchemaValidationError("payload", None, "must be a dict")
        assert "payload" in str(exc)

    def test_message_contains_type_name(self) -> None:
        exc = SchemaValidationError("payload", None, "must be a dict")
        assert "NoneType" in str(exc)

    def test_message_does_not_contain_received_value(self) -> None:
        """Received value (potential PII) must NOT appear in the message."""
        pii = "secret-api-key-12345"
        exc = SchemaValidationError("source", pii, "wrong format")
        # only type name (str) should appear, not the value itself
        assert pii not in str(exc)

    def test_is_spanforge_error(self) -> None:
        assert isinstance(SchemaValidationError("f", "v", "r"), LLMSchemaError)


@pytest.mark.unit
class TestULIDError:
    def test_attributes(self) -> None:
        exc = ULIDError("generation failed")
        assert exc.detail == "generation failed"

    def test_message_format(self) -> None:
        exc = ULIDError("overflow")
        assert "ULID error" in str(exc)
        assert "overflow" in str(exc)

    def test_is_spanforge_error(self) -> None:
        assert isinstance(ULIDError("d"), LLMSchemaError)


@pytest.mark.unit
class TestSerializationError:
    def test_attributes(self) -> None:
        exc = SerializationError("01ARYZ", "bad type")
        assert exc.event_id == "01ARYZ"
        assert exc.reason == "bad type"

    def test_message_format(self) -> None:
        exc = SerializationError("01ARYZ", "bad type")
        assert "01ARYZ" in str(exc)
        assert "bad type" in str(exc)

    def test_is_spanforge_error(self) -> None:
        assert isinstance(SerializationError("id", "r"), LLMSchemaError)


@pytest.mark.unit
class TestDeserializationError:
    def test_attributes_with_hint(self) -> None:
        exc = DeserializationError("field missing", "events.jsonl")
        assert exc.reason == "field missing"
        assert exc.source_hint == "events.jsonl"

    def test_attributes_default_hint(self) -> None:
        exc = DeserializationError("field missing")
        assert exc.source_hint == "<unknown>"

    def test_message_format(self) -> None:
        exc = DeserializationError("bad schema", "data.json")
        assert "bad schema" in str(exc)
        assert "data.json" in str(exc)

    def test_is_spanforge_error(self) -> None:
        assert isinstance(DeserializationError("r"), LLMSchemaError)


@pytest.mark.unit
class TestEventTypeError:
    def test_attributes(self) -> None:
        exc = EventTypeError("llm.bad.type", "not registered")
        assert exc.event_type == "llm.bad.type"
        assert exc.reason == "not registered"

    def test_message_format(self) -> None:
        exc = EventTypeError("llm.bad.type", "reserved namespace")
        assert "llm.bad.type" in str(exc)
        assert "reserved namespace" in str(exc)

    def test_is_spanforge_error(self) -> None:
        assert isinstance(EventTypeError("t", "r"), LLMSchemaError)
