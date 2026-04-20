"""tests/test_batch_exporter.py — Unit tests for spanforge._batch_exporter (F-45).

Covers BatchExporter lifecycle, circuit breaker, queue-full drop, flush,
shutdown, get_health, and the module-level get_aggregate_health helper.
All tests use stdlib mocks only — no external I/O.
"""

from __future__ import annotations

import threading
import time
import unittest
from typing import Any
from unittest.mock import MagicMock

from spanforge._batch_exporter import (
    BatchExporter,
    _CIRCUIT_BREAKER_THRESHOLD,
    get_aggregate_health,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(tag: str = "test") -> dict[str, Any]:
    """Return a minimal event-like dict."""
    return {"event_type": tag, "payload": {}}


def _make_exporter(export_fn=None, **kw) -> BatchExporter:
    if export_fn is None:
        export_fn = MagicMock()
    kw.setdefault("flush_interval_seconds", 0.1)
    return BatchExporter(export_fn, **kw)


# ===========================================================================
# Section 1 — put() + flush()
# ===========================================================================

class TestBatchExporterPutFlush(unittest.TestCase):

    def test_put_returns_true_on_success(self):
        fn = MagicMock()
        bexp = _make_exporter(fn)
        result = bexp.put(_make_event())
        self.assertTrue(result)
        bexp.shutdown()

    def test_exported_count_increments(self):
        fn = MagicMock()
        bexp = _make_exporter(fn, batch_size=1, flush_interval_seconds=0.05)
        bexp.put(_make_event())
        bexp.flush(timeout_seconds=2.0)
        self.assertGreaterEqual(bexp.exported_count, 1)
        bexp.shutdown()

    def test_flush_returns_true(self):
        fn = MagicMock()
        bexp = _make_exporter(fn, batch_size=1)
        bexp.put(_make_event())
        success = bexp.flush(timeout_seconds=2.0)
        self.assertTrue(success)
        bexp.shutdown()

    def test_flush_on_idle_exporter_returns_true(self):
        bexp = _make_exporter(batch_size=512)
        result = bexp.flush(timeout_seconds=1.0)
        self.assertTrue(result)
        bexp.shutdown()


# ===========================================================================
# Section 2 — shutdown()
# ===========================================================================

class TestBatchExporterShutdown(unittest.TestCase):

    def test_shutdown_stops_worker(self):
        fn = MagicMock()
        bexp = _make_exporter(fn)
        bexp.shutdown(timeout_seconds=2.0)
        self.assertFalse(bexp._thread.is_alive())

    def test_shutdown_is_idempotent(self):
        fn = MagicMock()
        bexp = _make_exporter(fn)
        bexp.shutdown()
        # Second call must not raise.
        bexp.shutdown()

    def test_put_after_shutdown_drops_event(self):
        fn = MagicMock()
        bexp = _make_exporter(fn, batch_size=512)
        bexp.shutdown(timeout_seconds=2.0)
        result = bexp.put(_make_event())
        self.assertFalse(result)


# ===========================================================================
# Section 3 — queue-full drop
# ===========================================================================

class TestBatchExporterQueueFull(unittest.TestCase):

    def test_queue_full_drops_event(self):
        # Use a queue of size 1 and make the export function block so the
        # queue fills up.
        barrier = threading.Event()

        def _blocking_export(evt):
            barrier.wait(timeout=5.0)

        bexp = BatchExporter(
            _blocking_export,
            max_queue_size=1,
            batch_size=1,
            flush_interval_seconds=60.0,
        )
        # Fill the queue.
        bexp.put(_make_event("first"))
        # This second put should be dropped (queue full).
        result = bexp.put(_make_event("second"))
        # Allow the blocking export to finish so shutdown completes cleanly.
        barrier.set()
        bexp.shutdown(timeout_seconds=2.0)
        # At least one event was dropped.
        self.assertGreaterEqual(bexp.dropped_count, 1)


# ===========================================================================
# Section 4 — circuit breaker
# ===========================================================================

class TestBatchExporterCircuitBreaker(unittest.TestCase):

    def test_circuit_trips_after_threshold_failures(self):
        def _always_fail(evt):
            raise RuntimeError("export error")

        bexp = BatchExporter(
            _always_fail,
            batch_size=1,
            flush_interval_seconds=0.05,
            circuit_breaker_reset_seconds=60.0,
        )
        # Feed enough events to trip the circuit.
        for _ in range(_CIRCUIT_BREAKER_THRESHOLD + 5):
            bexp.put(_make_event())
        bexp.flush(timeout_seconds=3.0)

        with bexp._cb_lock:
            circuit_open = bexp._cb_open
        self.assertTrue(circuit_open, "Circuit breaker should be open after repeated failures")
        bexp.shutdown(timeout_seconds=2.0)

    def test_put_returns_false_when_circuit_open(self):
        fn = MagicMock()
        bexp = _make_exporter(fn)
        # Force the circuit open.
        with bexp._cb_lock:
            bexp._cb_open = True
            bexp._cb_tripped_at = time.monotonic()
        result = bexp.put(_make_event())
        self.assertFalse(result)
        bexp.shutdown()

    def test_export_error_count_increments(self):
        def _always_fail(evt):
            raise RuntimeError("err")

        bexp = BatchExporter(
            _always_fail,
            batch_size=1,
            flush_interval_seconds=0.05,
            circuit_breaker_reset_seconds=60.0,
        )
        bexp.put(_make_event())
        bexp.flush(timeout_seconds=2.0)
        self.assertGreaterEqual(bexp.export_error_count, 1)
        bexp.shutdown(timeout_seconds=2.0)


# ===========================================================================
# Section 5 — get_health()
# ===========================================================================

class TestBatchExporterGetHealth(unittest.TestCase):

    def test_get_health_keys(self):
        bexp = _make_exporter()
        health = bexp.get_health()
        for key in (
            "queue_size",
            "dropped_count",
            "export_error_count",
            "exported_count",
            "circuit_open",
            "worker_alive",
        ):
            self.assertIn(key, health, f"Missing key: {key}")
        bexp.shutdown()

    def test_worker_alive_true_before_shutdown(self):
        bexp = _make_exporter()
        self.assertTrue(bexp.get_health()["worker_alive"])
        bexp.shutdown()

    def test_worker_alive_false_after_shutdown(self):
        bexp = _make_exporter()
        bexp.shutdown(timeout_seconds=2.0)
        self.assertFalse(bexp.get_health()["worker_alive"])


# ===========================================================================
# Section 6 — get_aggregate_health()
# ===========================================================================

class TestGetAggregateHealth(unittest.TestCase):

    def test_aggregate_includes_active_exporters(self):
        fn = MagicMock()
        bexp = BatchExporter(fn, batch_size=512)
        health = get_aggregate_health()
        self.assertGreaterEqual(health["exporter_count"], 1)
        self.assertIn("total_dropped", health)
        self.assertIn("total_exported", health)
        self.assertIn("total_errors", health)
        self.assertIn("any_circuit_open", health)
        self.assertIn("exporters", health)
        bexp.shutdown()

    def test_aggregate_any_circuit_open_false_by_default(self):
        fn = MagicMock()
        bexp = BatchExporter(fn, batch_size=512)
        health = get_aggregate_health()
        self.assertFalse(health["any_circuit_open"])
        bexp.shutdown()


if __name__ == "__main__":
    unittest.main()
