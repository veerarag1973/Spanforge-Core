"""spanforge._batch_exporter — Background batched export pipeline (RFC-0001 §19).

This module provides a bounded, thread-safe batch exporter that wraps any
synchronous exporter (a callable taking a single :class:`~spanforge.event.Event`)
and ships events asynchronously from a background daemon thread.

Architecture
------------
::

    put(event)
       │
       ▼
    queue.Queue[Event | None]  (bounded by config.max_queue_size)
       │
       ▼
    _WorkerThread              — background daemon thread
       │
       ├─ accumulates events until batch_size reached
       ├─ or flush_interval_seconds elapsed (whichever comes first)
       └─ calls exporter.export(event) for each event in the batch

Circuit breaker
~~~~~~~~~~~~~~~
After ``_CIRCUIT_BREAKER_THRESHOLD`` consecutive export failures the circuit
trips **open**: new ``put()`` calls are silently dropped (not queued) and the
exporter is not called.  The circuit resets to **closed** after
``circuit_breaker_reset_seconds`` with the next successful export.

Signals
~~~~~~~
``flush(timeout)`` — drain the queue; returns ``True`` on success.
``shutdown(timeout)`` — drain + stop the worker thread.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any, Callable

__all__ = [
    "BatchExporter",
]

_log = logging.getLogger("spanforge.batch_exporter")

_CIRCUIT_BREAKER_THRESHOLD = 5  # consecutive failures before tripping open
_SENTINEL = None  # sent down the queue to tell the worker to stop

# _DROP_SENTINEL distinguishes a flush-wait sentinel from a stop sentinel.
_FLUSH_TAG = object()


class BatchExporter:
    """Wraps a synchronous exporter with a background batching pipeline.

    Args:
        export_fn: Callable that receives a single
            :class:`~spanforge.event.Event` and performs the actual export.
        batch_size: Maximum number of events to accumulate before forcibly
            flushing.  Defaults to ``config.batch_size`` (512).
        flush_interval_seconds: Maximum time (seconds) to wait before
            flushing a partial batch.  Defaults to
            ``config.flush_interval_seconds`` (5.0).
        max_queue_size: Maximum depth of the internal queue.  Events that
            arrive when the queue is full are **dropped** (counted in
            :attr:`dropped_count`).
        circuit_breaker_reset_seconds: How long (seconds) the circuit stays
            open after tripping.  Defaults to 30.

    Example::

        from spanforge._batch_exporter import BatchExporter
        from spanforge.exporters.jsonl import SyncJSONLExporter

        inner = SyncJSONLExporter("trace.jsonl")
        bexp = BatchExporter(inner.export, batch_size=64, flush_interval_seconds=2.0)
        bexp.put(event)
        # ... later ...
        bexp.shutdown()
    """

    def __init__(
        self,
        export_fn: Callable[[Any], None],
        *,
        batch_size: int = 512,
        flush_interval_seconds: float = 5.0,
        max_queue_size: int = 10_000,
        circuit_breaker_reset_seconds: float = 30.0,
    ) -> None:
        self._export_fn = export_fn
        self._batch_size = max(1, batch_size)
        self._flush_interval = max(0.01, flush_interval_seconds)
        self._cb_reset_seconds = circuit_breaker_reset_seconds

        # Stats (read outside the lock for approximate values — accuracy is
        # not required; correctness of the exporter is).
        self.dropped_count: int = 0
        self.export_error_count: int = 0
        self.exported_count: int = 0

        # Circuit breaker state.
        self._cb_lock = threading.Lock()
        self._cb_consecutive_failures: int = 0
        self._cb_open: bool = False
        self._cb_tripped_at: float = 0.0

        # Queue.
        self._queue: queue.Queue[Any] = queue.Queue(maxsize=max_queue_size)

        # Worker.
        self._stop_event = threading.Event()
        self._thread = threading.Thread(
            target=self._worker,
            name="spanforge-batch-exporter",
            daemon=True,
        )
        self._thread.start()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def put(self, event: Any) -> bool:
        """Enqueue *event* for export.

        Returns ``True`` if the event was enqueued, ``False`` if it was
        dropped (queue full, circuit open, or exporter shut down).
        """
        # Check circuit breaker first — cheaper than queue operations and
        # prevents work from piling up behind an open circuit.
        if self._circuit_is_open():
            self.dropped_count += 1
            return False

        # Refuse new work after shutdown.  Checked AFTER circuit so that the
        # circuit-open drop is counted even during shutdown sequencing.
        if self._stop_event.is_set():
            self.dropped_count += 1
            return False

        try:
            self._queue.put_nowait(event)
            return True
        except queue.Full:
            self.dropped_count += 1
            _log.warning(
                "spanforge batch exporter: queue full (%d items dropped so far)",
                self.dropped_count,
            )
            return False

    def flush(self, timeout_seconds: float = 5.0) -> bool:
        """Block until all currently queued events have been exported.

        Returns ``True`` if the flush completed within *timeout_seconds*,
        ``False`` on timeout.

        Each call uses an independent :class:`threading.Event` so concurrent
        flush() calls do not accidentally release each other's barrier.
        """
        if not self._thread.is_alive():
            return True

        # Per-call done event avoids the race between _flush_done.clear() and
        # the worker setting _flush_done for a *previous* flush request.
        done_event = threading.Event()
        try:
            self._queue.put_nowait((_FLUSH_TAG, done_event))
        except queue.Full:
            return False
        return done_event.wait(timeout=timeout_seconds)

    def shutdown(self, timeout_seconds: float = 5.0) -> None:
        """Flush remaining events and stop the background thread.

        Safe to call multiple times.
        """
        if not self._thread.is_alive():
            return
        self._stop_event.set()
        # Send sentinel to wake the worker.
        try:
            self._queue.put_nowait(_SENTINEL)
        except queue.Full:
            pass
        self._thread.join(timeout=timeout_seconds)

    # ------------------------------------------------------------------
    # Circuit breaker helpers
    # ------------------------------------------------------------------

    def _circuit_is_open(self) -> bool:
        with self._cb_lock:
            if not self._cb_open:
                return False
            # Auto-reset after timeout.
            if time.monotonic() - self._cb_tripped_at > self._cb_reset_seconds:
                _log.info("spanforge batch exporter: circuit breaker reset to closed")
                self._cb_open = False
                self._cb_consecutive_failures = 0
                return False
            return True

    def _record_success(self) -> None:
        with self._cb_lock:
            self._cb_consecutive_failures = 0
            if self._cb_open:
                self._cb_open = False

    def _record_failure(self) -> None:
        with self._cb_lock:
            self._cb_consecutive_failures += 1
            if (
                not self._cb_open
                and self._cb_consecutive_failures >= _CIRCUIT_BREAKER_THRESHOLD
            ):
                self._cb_open = True
                self._cb_tripped_at = time.monotonic()
                _log.error(
                    "spanforge batch exporter: circuit breaker OPEN after %d "
                    "consecutive failures; new events will be dropped for %.0fs",
                    self._cb_consecutive_failures,
                    self._cb_reset_seconds,
                )

    # ------------------------------------------------------------------
    # Worker thread
    # ------------------------------------------------------------------

    def _worker(self) -> None:
        """Background thread: accumulate + export batches."""
        batch: list[Any] = []
        deadline = time.monotonic() + self._flush_interval

        while True:
            now = time.monotonic()
            remaining = max(0.0, deadline - now)

            # Wait for the next item or timeout.
            try:
                item = self._queue.get(timeout=remaining)
            except queue.Empty:
                item = None  # timeout — force a flush of whatever we have

            if item is _SENTINEL or self._stop_event.is_set():
                # Drain remaining items in the queue before stopping.
                self._drain_queue(batch)
                self._export_batch(batch)
                batch = []
                break

            if isinstance(item, tuple) and len(item) == 2 and item[0] is _FLUSH_TAG:
                # Flush requested externally — item is (_FLUSH_TAG, done_event).
                _, done_event = item
                self._drain_queue(batch)
                self._export_batch(batch)
                batch = []
                deadline = time.monotonic() + self._flush_interval
                done_event.set()  # Signal this specific flush caller.
                continue

            if item is not None:
                batch.append(item)

            time_expired = time.monotonic() >= deadline
            batch_full = len(batch) >= self._batch_size

            if time_expired or batch_full:
                self._export_batch(batch)
                batch = []
                deadline = time.monotonic() + self._flush_interval

    def _drain_queue(self, batch: list[Any]) -> None:
        """Drain remaining items from the queue into *batch* without blocking."""
        while True:
            try:
                item = self._queue.get_nowait()
                if item is _SENTINEL:
                    continue
                # Flush tuples: signal done and skip — already mid-flush.
                if isinstance(item, tuple) and len(item) == 2 and item[0] is _FLUSH_TAG:
                    _, done_event = item
                    done_event.set()
                    continue
                if item is not None:
                    batch.append(item)
            except queue.Empty:
                break

    def _export_batch(self, batch: list[Any]) -> None:
        """Export all events in *batch* via the wrapped exporter."""
        if not batch:
            return
        for event in batch:
            try:
                self._export_fn(event)
            except Exception as exc:  # NOSONAR
                # Increment error counter ONLY on failure (C2 fix: counter was
                # incremented inside the same try block as success, causing
                # both counters to be set on partial failures).
                self.export_error_count += 1
                self._record_failure()
                _log.warning(
                    "spanforge batch exporter: export error (%s): %s",
                    type(exc).__name__,
                    exc,
                )
                # Propagate to the configured error handler without blocking.
                try:
                    from spanforge._stream import _handle_export_error  # noqa: PLC0415
                    _handle_export_error(exc)
                except Exception:  # NOSONAR
                    pass
            else:
                # Success path: increment only on confirmed success (C2 fix).
                self.exported_count += 1
                self._record_success()
