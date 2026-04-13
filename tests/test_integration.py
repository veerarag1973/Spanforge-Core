"""Integration tests — cross-module end-to-end scenarios.

These tests exercise the full stack: ULID → EventType → Event → JSON → re-parse.
"""

from __future__ import annotations

import json

import pytest

import spanforge
from tests.conftest import FIXED_TIMESTAMP
from spanforge import Event, EventType, Tags, generate_ulid, validate_ulid
from spanforge.exceptions import LLMSchemaError


@pytest.mark.integration
class TestFullRoundTrip:
    def test_create_validate_serialise_deserialise(self) -> None:
        """Complete happy path: build → validate → JSON → restore → validate."""
        event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source="llm-trace@0.3.1",
            payload={
                "span_name": "run_customer_support_agent",
                "span_kind": "agent",
                "status": "ok",
                "duration_ms": 2721,
                "model": {"name": "gpt-4o", "provider": "openai"},
                "usage": {
                    "prompt_tokens": 312,
                    "completion_tokens": 189,
                    "cost_usd": 0.00412,
                },
            },
            tags=Tags(env="production", model="gpt-4o"),
            trace_id="a" * 32,
            span_id="b" * 16,
            org_id="org_acme",
            actor_id="usr_priya",
        )

        # Validate
        event.validate()

        # Serialise to JSON
        json_str = event.to_json()
        assert len(json_str) > 100

        # Verify it is parseable and sorted
        data = json.loads(json_str)
        assert list(data.keys()) == sorted(data.keys())

        # Restore from JSON
        restored = Event.from_json(json_str)
        restored.validate()
        assert restored.event_id == event.event_id
        assert restored.payload["span_name"] == "run_customer_support_agent"
        assert restored.tags is not None
        assert restored.tags["env"] == "production"

    def test_checksum_stability(self) -> None:
        """Same payload → same checksum regardless of event_id/timestamp."""
        payload = {"key": "value", "number": 42}
        e1 = Event(
            event_type=EventType.COST_TOKEN_RECORDED,
            source="llm-cost@0.2.0",
            payload=payload,
            timestamp=FIXED_TIMESTAMP,
        )
        e2 = Event(
            event_type=EventType.COST_TOKEN_RECORDED,
            source="llm-cost@0.2.0",
            payload=payload,
            timestamp=FIXED_TIMESTAMP,
        )
        assert e1.payload_checksum() == e2.payload_checksum()

    def test_ulid_in_event_is_valid(self) -> None:
        event = Event(
            event_type=EventType.GUARD_INPUT_BLOCKED,
            source="promptguard@0.1.0",
            payload={"rule_id": "r1", "risk_score": 0.9},
            timestamp=FIXED_TIMESTAMP,
        )
        assert validate_ulid(event.event_id)

    def test_all_event_types_constructable(self) -> None:
        """Every EventType member can be used to create and validate an Event."""
        for et in EventType:
            event = Event(
                event_type=et,
                source="test-service@0.1.0",
                payload={"test": True},
                timestamp=FIXED_TIMESTAMP,
            )
            event.validate()  # must not raise


@pytest.mark.integration
class TestPublicApiExports:
    def test_version_present(self) -> None:
        assert hasattr(spanforge, "__version__")
        assert spanforge.__version__  # non-empty string is sufficient

    def test_schema_version_constant(self) -> None:
        assert spanforge.SCHEMA_VERSION == "2.0"

    def test_all_exceptions_exported(self) -> None:
        assert issubclass(spanforge.SchemaValidationError, spanforge.LLMSchemaError)
        assert issubclass(spanforge.ULIDError, spanforge.LLMSchemaError)
        assert issubclass(spanforge.SerializationError, spanforge.LLMSchemaError)

    def test_generate_ulid_public(self) -> None:
        ulid = generate_ulid()
        assert validate_ulid(ulid)


@pytest.mark.integration
class TestErrorPropagation:
    def test_all_errors_catchable_as_spanforge_error(self) -> None:
        """The unified catch pattern must work for all spanforge exceptions."""
        bad_event = Event(
            event_type="bad-event-type",
            source="bad-source",
            payload={},
            timestamp="bad-timestamp",
            event_id="bad-id",
        )
        with pytest.raises(LLMSchemaError):
            bad_event.validate()
