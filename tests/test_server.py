"""Tests for spanforge._server — TraceViewerServer HTTP handlers.

Covers:
* /api/stats — event/trace counts, cost aggregation, signed counts
* CORS header behaviour — no header by default, sent when cors_origins is set
* TraceViewerServer defaults
* Regression: _handle_api_stats no longer crashes with AttributeError
"""

from __future__ import annotations

import json
import threading
from collections import OrderedDict
from io import BytesIO
from unittest.mock import MagicMock

import pytest

from spanforge._server import TraceViewerServer, _TraceAPIHandler


# ─── Helpers ──────────────────────────────────────────────────────────────────

class _MockStore:
    """Minimal TraceStore stand-in with only the attributes the handlers use."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._traces: dict = OrderedDict()

    def get_trace(self, trace_id: str):
        return self._traces.get(trace_id)


def _make_event(
    event_type: str = "llm.trace.span.completed",
    trace_id: str = "trace01",
    signature: str | None = None,
    cost_usd: float = 0.0,
) -> MagicMock:
    ev = MagicMock(spec=[
        "event_type", "trace_id", "timestamp", "payload", "signature",
        "span_id", "to_dict",
    ])
    ev.event_type = event_type
    ev.trace_id = trace_id
    ev.timestamp = "2025-01-15T10:00:00Z"
    ev.payload = {"cost_usd": cost_usd} if cost_usd else {}
    ev.signature = signature
    ev.span_id = "span01"
    ev.to_dict.return_value = {
        "event_type": event_type,
        "trace_id": trace_id,
        "timestamp": "2025-01-15T10:00:00Z",
        "payload": ev.payload,
        "signature": signature,
        "span_id": "span01",
    }
    return ev


def _make_handler(store: _MockStore, cors_origins: str = "") -> tuple[_TraceAPIHandler, BytesIO]:
    """Create a handler instance with mocked HTTP machinery."""
    h = object.__new__(_TraceAPIHandler)
    h._get_store = lambda: store
    h._cors_origins = cors_origins
    h.path = "/"
    buf = BytesIO()
    h.wfile = buf
    h.send_response = MagicMock()
    h.send_header = MagicMock()
    h.end_headers = MagicMock()
    return h, buf


def _json_body(buf: BytesIO) -> dict:
    return json.loads(buf.getvalue().decode("utf-8"))


# ─── /api/stats ───────────────────────────────────────────────────────────────

class TestHandleApiStats:
    def test_empty_store_returns_zeros(self):
        store = _MockStore()
        h, buf = _make_handler(store)
        h._handle_api_stats()

        data = _json_body(buf)
        assert data["events"] == 0
        assert data["traces"] == 0
        assert data["signed_count"] == 0
        assert data["unsigned_count"] == 0
        assert data["total_cost_usd"] == 0.0

    def test_counts_events_and_traces(self):
        store = _MockStore()
        store._traces["t1"] = [_make_event(), _make_event("llm.cost.token_usage")]
        store._traces["t2"] = [_make_event(trace_id="t2")]

        h, buf = _make_handler(store)
        h._handle_api_stats()

        data = _json_body(buf)
        assert data["events"] == 3
        assert data["traces"] == 2

    def test_counts_signed_events(self):
        store = _MockStore()
        store._traces["t1"] = [
            _make_event(signature="sig_abc"),
            _make_event(signature=None),
        ]

        h, buf = _make_handler(store)
        h._handle_api_stats()

        data = _json_body(buf)
        assert data["signed_count"] == 1
        assert data["unsigned_count"] == 1

    def test_sums_cost(self):
        store = _MockStore()
        store._traces["t1"] = [
            _make_event(cost_usd=0.001),
            _make_event(cost_usd=0.002),
        ]

        h, buf = _make_handler(store)
        h._handle_api_stats()

        data = _json_body(buf)
        assert abs(data["total_cost_usd"] - 0.003) < 1e-9

    def test_regression_no_events_attribute_crash(self):
        """Regression: handler previously crashed with AttributeError on store._events.

        TraceStore only has _traces; there is no _events dict.
        """
        store = _MockStore()
        for i in range(5):
            store._traces[f"t{i}"] = [_make_event(trace_id=f"t{i}")]

        # Must not raise AttributeError
        h, buf = _make_handler(store)
        h._handle_api_stats()

        data = _json_body(buf)
        assert data["events"] == 5
        assert data["traces"] == 5


# ─── /traces ──────────────────────────────────────────────────────────────────

class TestHandleListTraces:
    def test_returns_all_trace_ids(self):
        store = _MockStore()
        store._traces["abc"] = [_make_event()]
        store._traces["def"] = [_make_event()]

        h, buf = _make_handler(store)
        h._handle_list_traces()

        data = _json_body(buf)
        assert set(data["trace_ids"]) == {"abc", "def"}
        assert data["count"] == 2

    def test_empty_store(self):
        store = _MockStore()
        h, buf = _make_handler(store)
        h._handle_list_traces()

        data = _json_body(buf)
        assert data["trace_ids"] == []
        assert data["count"] == 0


# ─── CORS header behaviour ────────────────────────────────────────────────────

class TestCorsHeaders:
    def test_no_cors_header_when_cors_origins_empty(self):
        store = _MockStore()
        h, _ = _make_handler(store, cors_origins="")
        h._json_response({"ok": True})

        header_names = [c.args[0] for c in h.send_header.call_args_list]
        assert "Access-Control-Allow-Origin" not in header_names

    def test_cors_header_sent_when_set(self):
        store = _MockStore()
        h, _ = _make_handler(store, cors_origins="https://app.example.com")
        h._json_response({"ok": True})

        headers = {c.args[0]: c.args[1] for c in h.send_header.call_args_list}
        assert headers.get("Access-Control-Allow-Origin") == "https://app.example.com"

    def test_wildcard_cors_is_sent_when_explicitly_set(self):
        store = _MockStore()
        h, _ = _make_handler(store, cors_origins="*")
        h._json_response({"ok": True})

        headers = {c.args[0]: c.args[1] for c in h.send_header.call_args_list}
        assert headers.get("Access-Control-Allow-Origin") == "*"


# ─── TraceViewerServer defaults ───────────────────────────────────────────────

class TestTraceViewerServerDefaults:
    def test_cors_default_is_empty_string(self):
        """Default should not send CORS headers — prevents data leakage to other origins."""
        server = TraceViewerServer(port=9001)
        assert server._cors_origins == ""

    def test_cors_can_be_configured_explicitly(self):
        server = TraceViewerServer(port=9002, cors_origins="*")
        assert server._cors_origins == "*"

    def test_default_host_is_loopback(self):
        server = TraceViewerServer(port=9003)
        assert server._host == "127.0.0.1"
