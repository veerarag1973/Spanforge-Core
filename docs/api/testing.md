# spanforge.testing

First-class test utilities for writing unit tests against your AI pipeline
without connecting to real exporters or an external compliance backend.

---

## `MockExporter`

```python
class MockExporter:
    events: list[Event]
    export_count: int
    ...
```

A synchronous exporter that collects every exported event in memory.
Optionally raises on export to test error-handling paths.

```python
from spanforge.testing import MockExporter
from spanforge import configure

exporter = MockExporter()
configure(exporter=exporter)

# run your agent code here ...

assert exporter.export_count == 3
assert exporter.events[0].event_type == "llm.trace.span.completed"
```

### Constructor

```python
MockExporter(
    raise_on_export: type[Exception] | None = None,
    max_events: int | None = None,
)
```

| Parameter | Description |
|-----------|-------------|
| `raise_on_export` | If set to an `Exception` subclass, `export()` raises that type on every call. |
| `max_events` | If set, raises `RuntimeError` after more than `max_events` calls. |

### Methods

| Method | Description |
|--------|-------------|
| `export(event)` | Store `event`; raise if `raise_on_export` is set. |
| `export_batch(events)` | Async batch export (stores all events). |
| `clear()` | Reset `events` list and `export_count` counter. |
| `filter_by_type(event_type)` | Return only events matching `event_type`. |
| `installed()` | Context manager: install this exporter as the active exporter for the duration of the `with` block; restore previous exporter on exit. |

### `MockExporter.installed()` context manager

```python
with MockExporter().installed() as mock:
    run_my_agent()
    span_events = mock.filter_by_type("llm.trace.span.completed")
    assert len(span_events) == 1
```

---

## `capture_events()`

```python
@contextmanager
def capture_events() -> Generator[list[Event], None, None]:
```

Context manager that installs a fresh `MockExporter` and yields the live
event list. Restores the previous exporter on exit.

```python
from spanforge.testing import capture_events

with capture_events() as events:
    run_my_agent()

assert any(e.event_type == "llm.trace.span.completed" for e in events)
```

---

## `assert_event_schema_valid()`

```python
def assert_event_schema_valid(event: Event) -> None:
```

Assert that `event` passes JSON Schema validation against the published
spanforge v2.0 schema. Raises `AssertionError` with a descriptive message
on failure.

```python
from spanforge.testing import assert_event_schema_valid
from spanforge import Event, EventType

event = Event(
    event_type=EventType.TRACE_SPAN_COMPLETED,
    source="test@1.0.0",
    payload={"span_name": "test", "status": "ok"},
)
assert_event_schema_valid(event)   # passes silently
```

---

## `trace_store()`

```python
@contextmanager
def trace_store(max_traces: int = 100) -> Generator[TraceStore, None, None]:
```

Context manager that installs a fresh, isolated `TraceStore` for the duration
of a `with` block and restores the previous singleton on exit. Useful for
isolating trace storage between test cases.

```python
from spanforge.testing import trace_store

def test_trace_recorded():
    with trace_store() as store:
        run_my_agent(trace_id="abc123")
        trace_events = store.get_trace("abc123")
        assert trace_events is not None
```

---

## Re-exports

```python
import spanforge.testing as testing

testing.MockExporter
testing.capture_events
testing.assert_event_schema_valid
testing.trace_store
```

---

# `spanforge.testing_mocks` — Mock Service Clients (Phase 12)

> **DX-003** · Added in v2.0.11

The `spanforge.testing_mocks` module provides **11 pre-built mock clients**
that mirror the full SDK surface. Every mock records calls, supports
`configure_response()` for custom return values, and requires **zero network
access**.

## Quick Start

```python
from spanforge.testing_mocks import mock_all_services

def test_my_pipeline():
    with mock_all_services() as mocks:
        # Run your code that uses sf_pii, sf_audit, etc.
        run_pipeline()

        # Assert calls were made
        mocks["sf_pii"].assert_called("scan")
        mocks["sf_audit"].assert_called("append")
        assert mocks["sf_observe"].call_count("emit_span") >= 1
```

---

## `mock_all_services()`

```python
@contextmanager
def mock_all_services() -> Generator[dict[str, _MockBase], None, None]:
```

Context manager that patches all 11 singleton service clients in
`spanforge.sdk` with mock instances. On exit, the original clients are
restored.

**Returns:** A `dict` mapping client names to mock instances:

| Key | Mock Class | Replaces |
|-----|-----------|----------|
| `sf_identity` | `MockIdentityClient` | `SFIdentityClient` |
| `sf_pii` | `MockPIIClient` | `SFPIIClient` |
| `sf_secrets` | `MockSecretsClient` | `SFSecretsClient` |
| `sf_audit` | `MockAuditClient` | `SFAuditClient` |
| `sf_cec` | `MockCECClient` | `SFCECClient` |
| `sf_observe` | `MockObserveClient` | `SFObserveClient` |
| `sf_alert` | `MockAlertClient` | `SFAlertClient` |
| `sf_gate` | `MockGateClient` | `SFGateClient` |
| `sf_config` | `MockConfigClient` | `SFConfigClient` |
| `sf_trust` | `MockTrustClient` | `SFTrustClient` |
| `sf_security` | `MockSecurityClient` | `SFSecurityClient` |

---

## `_MockBase`

Base class for all mock clients. Provides:

### `.calls`

```python
@property
def calls(self) -> dict[str, list[tuple]]:
```

Dictionary mapping method names to lists of call argument tuples.

### `.call_count(method: str) -> int`

Returns the number of times `method` was called.

### `.assert_called(method: str)`

Raises `AssertionError` if `method` was never called.

### `.assert_not_called(method: str)`

Raises `AssertionError` if `method` **was** called.

### `.configure_response(method: str, response: Any)`

Set a custom return value for `method`. All subsequent calls to that
method will return `response`.

### `.reset()`

Clear all recorded calls and configured responses.

---

## Individual Mock Classes

Each mock client mirrors its real counterpart's public methods. All methods
are no-ops by default (return safe dummy values) and record their arguments
for assertion.

| Mock Class | Key Methods |
|-----------|------------|
| `MockIdentityClient` | `issue_token()`, `validate_token()`, `revoke_token()`, `rotate_keys()` |
| `MockPIIClient` | `scan()`, `scan_text()`, `redact()`, `get_entity_types()` |
| `MockSecretsClient` | `get()`, `put()`, `delete()`, `list_keys()` |
| `MockAuditClient` | `append()`, `verify_chain()`, `get_record()` |
| `MockCECClient` | `build_bundle()`, `generate_dpa()`, `validate_attestation()` |
| `MockObserveClient` | `emit_span()`, `add_annotation()`, `get_annotations()`, `export_spans()` |
| `MockAlertClient` | `send()`, `send_batch()` |
| `MockGateClient` | `evaluate()`, `evaluate_batch()` |
| `MockConfigClient` | `validate()`, `get()`, `set()` |
| `MockTrustClient` | `get_scorecard()`, `get_badge()`, `get_scores()` |
| `MockSecurityClient` | `owasp_audit()`, `threat_model()`, `dependency_scan()`, `scan_logs()` |

---

## Example — Custom Responses

```python
from spanforge.testing_mocks import mock_all_services

def test_gate_failure():
    with mock_all_services() as mocks:
        # Configure the gate mock to return FAIL
        mocks["sf_gate"].configure_response("evaluate", {
            "verdict": "FAIL",
            "message": "Budget exceeded",
        })

        result = run_pipeline()  # your code calls sf_gate.evaluate()
        assert result.blocked is True
        mocks["sf_gate"].assert_called("evaluate")
```

---

## See Also

- [testing](testing.md) — `MockExporter`, `capture_events()`, `trace_store()`
- [sdk-reference](sdk-reference.md) — Full SDK client reference (Phase 12)
