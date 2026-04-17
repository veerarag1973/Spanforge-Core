"""spanforge.processor — Span processor pipeline (RFC-0001 §18).

Span processors let users hook into the span lifecycle **before** and
**after** a span is exported.  Common uses:

* Attribute enrichment (e.g. add ``k8s.pod_name`` to every span)
* Redaction of sensitive fields (complementing built-in :class:`~spanforge.redact.RedactionPolicy`)
* Custom metrics counters / latency histograms
* Distributed context propagation helpers

Usage::

    from spanforge import configure
    from spanforge.processor import SpanProcessor, ProcessorChain

    class EnrichProcessor(SpanProcessor):
        def on_start(self, span) -> None:
            span.set_attribute("service.region", "us-east-1")

        def on_end(self, span) -> None:
            # span is already finalised with status / duration
            if span.status == "error":
                span.set_attribute("alert.triggered", True)

    configure(span_processors=[EnrichProcessor()])

Processors receive the *live* :class:`~spanforge._span.Span` object.
Mutations made in ``on_start`` are visible to user code inside the ``with``
block.  Mutations made in ``on_end`` appear in the exported payload.

Thread-safety
-------------
Processors are called from the thread that owns the span context manager, so
they run in the same thread/task as the user code.  Processors MUST NOT
block the event loop; long-running work should be dispatched to a background
thread or asyncio task.

Error handling
--------------
Exceptions propagating from a processor are silently caught so that a buggy
processor never aborts user code.  Errors are logged at ``WARNING`` level.
"""

from __future__ import annotations

import contextlib
import logging
import threading
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from spanforge._span import Span

__all__ = [
    "NoopSpanProcessor",
    "ProcessorChain",
    "SpanProcessor",
    "add_processor",
    "clear_processors",
]

_proc_logger = logging.getLogger("spanforge.processor")


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class SpanProcessor(Protocol):
    """Protocol implemented by all span processors.

    Both methods are optional — a processor that only enriches on start can
    omit ``on_end``, and vice-versa.  The default no-op implementations
    defined in this protocol mean partial implementations work correctly.
    """

    def on_start(self, span: Span) -> None:
        """Called synchronously immediately after the span is created.

        The span has been pushed onto the context stack and its start time
        recorded.  Attributes may be freely added or mutated here.

        Args:
            span: The newly created :class:`~spanforge._span.Span` (mutable).
        """
        ...

    def on_end(self, span: Span) -> None:
        """Called synchronously after the span is finalised but before export.

        ``span.end_ns``, ``span.duration_ms``, and ``span.status`` are all
        set by the time this method runs.  Attributes may still be mutated
        and will appear in the exported :class:`~spanforge.namespaces.trace.SpanPayload`.

        Args:
            span: The finalised :class:`~spanforge._span.Span` (still mutable).
        """
        ...


# ---------------------------------------------------------------------------
# No-op implementation (default)
# ---------------------------------------------------------------------------


class NoopSpanProcessor:
    """Span processor that does nothing.  Used as the default."""

    def on_start(self, span: Span) -> None:
        """No-op span start hook."""
        pass

    def on_end(self, span: Span) -> None:
        """No-op span end hook."""
        pass


# ---------------------------------------------------------------------------
# Processor chain
# ---------------------------------------------------------------------------


class ProcessorChain:
    """An ordered chain of :class:`SpanProcessor` implementations.

    Processors are called in insertion order for ``on_start`` and in the
    **same** order for ``on_end``.  Errors are caught per-processor so a
    bug in one processor does not prevent subsequent processors from running.

    Args:
        processors: Initial list of processors.

    Example::

        chain = ProcessorChain([EnrichProcessor(), RedactProcessor()])
        chain.on_start(span)
        # ... later ...
        chain.on_end(span)
    """

    def __init__(self, processors: list[Any] | None = None) -> None:
        self._processors: list[Any] = list(processors or [])
        self._lock = threading.Lock()

    def add(self, processor: Any) -> None:
        """Append *processor* to the chain."""
        with self._lock:
            self._processors.append(processor)

    def remove(self, processor: Any) -> None:
        """Remove *processor* from the chain (no-op if not present)."""
        with self._lock, contextlib.suppress(ValueError):
            self._processors.remove(processor)

    def clear(self) -> None:
        """Remove all processors from the chain."""
        with self._lock:
            self._processors.clear()

    def on_start(self, span: Span) -> None:
        """Fire ``on_start`` on all processors in order."""
        with self._lock:
            procs = list(self._processors)  # snapshot to avoid holding lock during callbacks
        for proc in procs:
            try:
                proc.on_start(span)
            except Exception as exc:  # NOSONAR
                _proc_logger.warning(
                    "SpanProcessor.on_start error in %r: %s", type(proc).__name__, exc
                )

    def on_end(self, span: Span) -> None:
        """Fire ``on_end`` on all processors in order."""
        with self._lock:
            procs = list(self._processors)  # snapshot to avoid holding lock during callbacks
        for proc in procs:
            try:
                proc.on_end(span)
            except Exception as exc:  # NOSONAR
                _proc_logger.warning(
                    "SpanProcessor.on_end error in %r: %s", type(proc).__name__, exc
                )

    def __len__(self) -> int:
        with self._lock:
            return len(self._processors)

    def __repr__(self) -> str:
        with self._lock:
            names = [type(p).__name__ for p in self._processors]
        return f"ProcessorChain({names!r})"


# ---------------------------------------------------------------------------
# Module-level helpers — called from _span.py
# ---------------------------------------------------------------------------


def _run_on_start(span: Span) -> None:
    """Fire ``on_start`` on all processors registered in the active config."""
    try:
        from spanforge.config import get_config

        processors = get_config().span_processors
    except Exception:  # NOSONAR
        return
    for proc in processors:
        try:
            proc.on_start(span)
        except Exception as exc:  # NOSONAR
            _proc_logger.warning("SpanProcessor.on_start error in %r: %s", type(proc).__name__, exc)


def _run_on_end(span: Span) -> None:
    """Fire ``on_end`` on all processors registered in the active config."""
    try:
        from spanforge.config import get_config

        processors = get_config().span_processors
    except Exception:  # NOSONAR
        return
    for proc in processors:
        try:
            proc.on_end(span)
        except Exception as exc:  # NOSONAR
            _proc_logger.warning("SpanProcessor.on_end error in %r: %s", type(proc).__name__, exc)


def add_processor(processor: Any) -> None:
    """Append *processor* to the global span processor list in the active config.

    Convenience wrapper around ``configure(span_processors=[...])``.

    Args:
        processor: Any object implementing :class:`SpanProcessor` protocol.

    Example::

        from spanforge.processor import add_processor, SpanProcessor

        class Enricher(SpanProcessor):
            def on_start(self, span): span.set_attribute("region", "eu-west-1")
            def on_end(self, span): pass

        add_processor(Enricher())
    """
    from spanforge.config import get_config

    get_config().span_processors.append(processor)


def clear_processors() -> None:
    """Remove all span processors from the active config."""
    from spanforge.config import get_config

    get_config().span_processors.clear()
