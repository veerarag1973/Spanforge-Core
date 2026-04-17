"""spanforge.testing — Test utilities for SpanForge SDK consumers.

Provides helpers for writing unit and integration tests that involve
SpanForge events, exporters, and the trace store.  Designed to be imported
only in test code (not in production).

Usage::

    from spanforge.testing import capture_events, MockExporter, assert_event_schema_valid

    # Capture all events emitted during a block
    with capture_events() as captured:
        # code that emits events
        ...

    assert len(captured) == 1
    assert captured[0].event_type == "llm.trace.span.completed"
    assert_event_schema_valid(captured[0])

    # Inject a mock exporter
    mock = MockExporter()
    with mock.installed():
        # code that emits events
        ...
    assert len(mock.events) == 1

    # Isolated TraceStore for one test
    from spanforge.testing import trace_store
    with trace_store() as store:
        configure(enable_trace_store=True)
        # ... emit events ...
        events = store.get_trace(trace_id)
"""

from __future__ import annotations

import contextlib
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Generator

    from spanforge._span import Span
    from spanforge._store import TraceStore
    from spanforge.event import Event

__all__ = [
    "MockExporter",
    "assert_event_schema_valid",
    "assert_span_emitted",
    "capture_events",
    "captured_spans",
    "trace_store",
]


# ---------------------------------------------------------------------------
# MockExporter
# ---------------------------------------------------------------------------


class MockExporter:
    """A synchronous in-memory exporter for testing.

    Records every event passed to :meth:`export` into :attr:`events`.
    Supports optional filtering, ordered access, and a context manager
    that temporarily replaces the global exporter.

    Args:
        raise_on_export: When set to an :class:`Exception` subclass or
                         instance, :meth:`export` raises it to simulate
                         export failures.

    Attributes:
        events: List of all :class:`~spanforge.event.Event` objects exported
                in chronological order.

    Example::

        mock = MockExporter()
        with mock.installed():
            tracer.span("test").__enter__().__exit__(None, None, None)

        assert mock.events[0].event_type == "llm.trace.span.completed"
    """

    def __init__(
        self,
        raise_on_export: type[Exception] | Exception | None = None,
    ) -> None:
        self.events: list[Event] = []
        self._lock = threading.Lock()
        self._raise_on_export = raise_on_export

    def export(self, event: Event) -> None:
        """Record *event*.  Raises configured exception if one is set.

        Args:
            event: The event to record.

        Raises:
            Exception: The configured ``raise_on_export`` exception, if set.
        """
        if self._raise_on_export is not None:
            if isinstance(self._raise_on_export, type):
                raise self._raise_on_export("MockExporter.raise_on_export triggered")
            raise self._raise_on_export
        with self._lock:
            self.events.append(event)

    async def export_batch(self, events: Any) -> None:  # NOSONAR
        """Async batch export — records all events in *events*.

        Args:
            events: Iterable of :class:`~spanforge.event.Event` objects.
        """
        for event in events:
            self.export(event)

    def clear(self) -> None:
        """Remove all recorded events."""
        with self._lock:
            self.events.clear()

    def filter_by_type(self, event_type: str) -> list[Event]:
        """Return all recorded events matching *event_type*.

        Args:
            event_type: Dotted event type string, e.g.
                        ``"llm.trace.span.completed"``.

        Returns:
            Filtered, ordered list of matching events.
        """
        et = str(event_type)
        with self._lock:
            return [
                e
                for e in self.events
                if (e.event_type.value if hasattr(e.event_type, "value") else str(e.event_type))
                == et
            ]

    @contextlib.contextmanager
    def installed(self) -> Generator[MockExporter, None, None]:
        """Context manager that installs this exporter as the global exporter.

        Replaces the SDK's active exporter for the duration of the block,
        then restores the original state::

            mock = MockExporter()
            with mock.installed():
                ...  # all events go to mock.events

        Yields:
            This :class:`MockExporter` instance.
        """
        from spanforge import _stream
        from spanforge._stream import _exporter_lock

        # Save state
        with _exporter_lock:
            original = _stream._cached_exporter
            _stream._cached_exporter = self
        try:
            yield self
        finally:
            with _exporter_lock:
                _stream._cached_exporter = original

    def __repr__(self) -> str:
        return f"MockExporter(events={len(self.events)})"


# ---------------------------------------------------------------------------
# capture_events()
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def capture_events() -> Generator[list[Event], None, None]:
    """Context manager that captures all events emitted during the block.

    Events are collected into a list that is yielded and grows in real-time
    as events are emitted.  The original exporter is restored on exit.

    Example::

        with capture_events() as events:
            with tracer.span("test"):
                pass

        assert events[0].payload["span_name"] == "test"

    Yields:
        A live ``list[Event]`` that is populated as events are emitted.
    """
    mock = MockExporter()
    with mock.installed():
        yield mock.events


# ---------------------------------------------------------------------------
# assert_event_schema_valid()
# ---------------------------------------------------------------------------


def assert_event_schema_valid(event: Event) -> None:
    """Assert that *event* passes SDK schema validation.

    Calls :func:`~spanforge.validate.validate_event` and re-raises any
    :class:`~spanforge.exceptions.SchemaValidationError` as an
    :class:`AssertionError` with the original message — so failures
    surface cleanly in :func:`pytest.raises` and ``assert`` blocks.

    Args:
        event: The event to validate.

    Raises:
        AssertionError: If *event* fails schema validation.

    Example::

        from spanforge.testing import assert_event_schema_valid
        assert_event_schema_valid(my_event)
    """
    from spanforge.exceptions import SchemaValidationError
    from spanforge.validate import validate_event

    try:
        validate_event(event)
    except SchemaValidationError as exc:
        raise AssertionError(f"Event failed schema validation: {exc}") from exc


# ---------------------------------------------------------------------------
# trace_store() context manager
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def trace_store(max_traces: int = 100) -> Generator[TraceStore, None, None]:
    """Context manager that provides an isolated :class:`~spanforge._store.TraceStore`.

    Creates a fresh ``TraceStore`` scoped to the block and temporarily
    installs it as the global store.  The original store is restored on
    exit, making this safe to use in parallel tests.

    Args:
        max_traces: Maximum number of traces to retain in the isolated store.

    Yields:
        A new :class:`~spanforge._store.TraceStore` instance scoped to the
        ``with`` block.

    Example::

        from spanforge import configure
        from spanforge.testing import trace_store

        with trace_store() as store:
            configure(enable_trace_store=True)
            with tracer.span("test") as s:
                pass
            events = store.get_trace(s.trace_id)
            assert events is not None
    """
    from spanforge._store import trace_store as _store_trace_store

    with _store_trace_store(max_traces=max_traces) as store:
        yield store


# ---------------------------------------------------------------------------
# captured_spans() pytest fixture
# ---------------------------------------------------------------------------

try:
    import pytest as _pytest

    @_pytest.fixture
    def captured_spans() -> Generator[list[Span], None, None]:
        """Pytest fixture that captures all Span objects completed during a test.

        Captures :class:`~spanforge._span.Span` instances regardless of operation type.

        Import this fixture in your test module (or ``conftest.py``) to make it
        available::

            from spanforge.testing import captured_spans  # re-export for pytest

            def test_my_fn(captured_spans):
                call_my_function()
                assert any(s.name == "my-step" for s in captured_spans)

        Each test gets an empty list; spans accumulate as the test runs.

        Yields:
            A live ``list[Span]`` populated as spans are completed.
        """
        from spanforge._hooks import hooks

        spans: list[Any] = []

        def _cb(span: Any) -> None:
            spans.append(span)

        hooks.on_span_end(_cb)
        try:
            yield spans  # type: ignore[misc]
        finally:
            with hooks._lock, contextlib.suppress(ValueError):
                hooks._all_end_hooks.remove(_cb)

except ImportError:
    # pytest not installed — skip fixture definition (production environments).
    pass


# ---------------------------------------------------------------------------
# assert_span_emitted()
# ---------------------------------------------------------------------------


def assert_span_emitted(
    spans: list[Any],
    *,
    name: str,
    model: str | None = None,
    status: str | None = None,
    operation: str | None = None,
) -> Any:
    """Assert that a span matching the given criteria appears in *spans*.

    Typically used with the :func:`captured_spans` fixture.

    Args:
        spans:     List of :class:`~spanforge._span.Span` objects (from fixture).
        name:      Required span name to match.
        model:     When provided, also checks ``span.model == model``.
        status:    When provided, also checks ``span.status == status``.
        operation: When provided, also checks ``span.operation == operation``.

    Returns:
        The first matching :class:`~spanforge._span.Span`.

    Raises:
        AssertionError: If no span matches all criteria.

    Example::

        def test_llm_call(captured_spans):
            run_agent()
            assert_span_emitted(captured_spans, name="llm-call", model="gpt-4o")
    """
    for span in spans:
        if span.name != name:
            continue
        if model is not None and span.model != model:
            continue
        if status is not None and span.status != status:
            continue
        if operation is not None and str(span.operation) != operation:
            continue
        return span

    criteria = f"name={name!r}"
    if model is not None:
        criteria += f", model={model!r}"
    if status is not None:
        criteria += f", status={status!r}"
    if operation is not None:
        criteria += f", operation={operation!r}"
    raise AssertionError(
        f"No span matching {criteria} found in {len(spans)} captured span(s). "
        f"Got: {[s.name for s in spans]}"
    )
