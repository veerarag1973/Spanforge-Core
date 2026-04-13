"""Shared pytest fixtures and helpers for the llm-toolkit-schema test suite."""

from __future__ import annotations

import datetime
import json
from typing import Any

import pytest

from spanforge import Event, EventType, Tags
from spanforge.ulid import generate as gen_ulid

# ---------------------------------------------------------------------------
# Timestamp helpers
# ---------------------------------------------------------------------------


def make_timestamp(  # noqa: PLR0913
    year: int = 2026,
    month: int = 3,
    day: int = 1,
    hour: int = 12,
    minute: int = 0,
    second: int = 0,
    microsecond: int = 0,
) -> str:
    """Return a deterministic UTC ISO-8601 timestamp string for tests."""
    dt = datetime.datetime(
        year, month, day, hour, minute, second, microsecond,
        tzinfo=datetime.timezone.utc,
    )
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


FIXED_TIMESTAMP = make_timestamp()
FIXED_TRACE_ID  = "a" * 32  # 32 lowercase hex chars
FIXED_SPAN_ID   = "b" * 16  # 16 lowercase hex chars


# ---------------------------------------------------------------------------
# Minimal valid event kwargs — reused across many tests
# ---------------------------------------------------------------------------


@pytest.fixture()
def minimal_event_kwargs() -> dict[str, Any]:
    """Return the minimum set of kwargs required to build a valid Event."""
    return {
        "event_type": EventType.TRACE_SPAN_COMPLETED,
        "source": "llm-trace@0.3.1",
        "payload": {"span_name": "test", "status": "ok"},
        "event_id": gen_ulid(),
        "timestamp": FIXED_TIMESTAMP,
    }


@pytest.fixture()
def minimal_event(minimal_event_kwargs: dict[str, Any]) -> Event:
    """A fully valid minimal Event."""
    return Event(**minimal_event_kwargs)


@pytest.fixture()
def full_event(minimal_event_kwargs: dict[str, Any]) -> Event:
    """An Event with all optional fields populated."""
    return Event(
        **minimal_event_kwargs,
        trace_id=FIXED_TRACE_ID,
        span_id=FIXED_SPAN_ID,
        parent_span_id=FIXED_SPAN_ID,
        org_id="org_01HX",
        team_id="team_01HX",
        actor_id="usr_01HX",
        session_id="sess_01HX",
        tags=Tags(env="production", model="gpt-4o"),
        checksum="sha256:abc123",
        prev_id=gen_ulid(),
    )


@pytest.fixture()
def event_dict(minimal_event: Event) -> dict[str, Any]:
    """A dict representation of a valid event (round-trip source)."""
    return json.loads(minimal_event.to_json())


# ---------------------------------------------------------------------------
# Well-known ULID fixtures
# ---------------------------------------------------------------------------

VALID_ULID = "01ARYZ3NDEKTSV4RRFFQ69G5FA"  # note: 26 chars


@pytest.fixture()
def valid_ulid() -> str:
    return gen_ulid()
