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


# ---------------------------------------------------------------------------
# Global state isolation — reset all singletons between tests
# ---------------------------------------------------------------------------


def _reset_global_state() -> None:
    """Reset every known mutable singleton in the spanforge package."""
    import dataclasses
    import spanforge._stream as _stream
    import spanforge._store as _store
    import spanforge._hooks as _hooks
    import spanforge.config as _cfg
    import spanforge.cost as _cost
    import spanforge.consumer as _consumer
    import spanforge.prompt_registry as _prompt_reg
    import spanforge.auto as _auto

    # 1. Config singleton → fresh defaults
    fresh = _cfg.SpanForgeConfig()
    with _cfg._config_lock:
        for f in dataclasses.fields(fresh):
            setattr(_cfg._config, f.name, getattr(fresh, f.name))

    # 2. Stream globals
    with _stream._exporter_lock:
        exp = _stream._cached_exporter
        if exp is not None:
            close = getattr(exp, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
            _stream._cached_exporter = None
    with _stream._sign_lock:
        _stream._prev_signed_event = None
    with _stream._export_error_lock:
        _stream._export_error_count = 0
    with _stream._shutdown_lock:
        _stream._shutdown_called = False

    # 3. Trace store
    _store._reset_store()

    # 4. Hook registry
    _hooks.hooks.clear()

    # 5. Cost tracker
    with _cost._global_tracker_lock:
        _cost._global_tracker = None

    # 6. Consumer registry
    _consumer._GLOBAL_REGISTRY.clear()

    # 7. Prompt registry
    _prompt_reg._DEFAULT_REGISTRY = _prompt_reg.PromptRegistry()

    # 8. Auto-patching state
    with _auto._PATCHED_LOCK:
        _auto._PATCHED.clear()


@pytest.fixture(autouse=True)
def _isolate_global_state() -> Any:
    """Ensure every test starts and ends with a clean global state."""
    _reset_global_state()
    yield
    _reset_global_state()
