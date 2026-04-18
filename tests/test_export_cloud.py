"""Tests for spanforge.export.cloud — CloudExporter."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from spanforge.export.cloud import CloudExporter, CloudExporterError

# ─── Fixtures ────────────────────────────────────────────────────────────────

def _make_event(event_type: str = "llm.trace.span.completed") -> MagicMock:
    ev = MagicMock()
    ev.event_id = "eid_001"
    ev.event_type = event_type
    ev.trace_id = "trace_abc"
    ev.span_id = "span_001"
    ev.source = "test@1.0"
    ev.timestamp = "2025-01-15T10:00:00Z"
    ev.schema_version = "2.0"
    ev.payload = {"span_name": "test", "duration_ms": 5.0}
    ev.tags = {"env": "test"}
    ev.signature = None
    ev.checksum = None
    ev.prev_id = None
    # No to_dict — will use fallback serialisation
    del ev.to_dict
    return ev


def _make_event_with_to_dict() -> MagicMock:
    ev = MagicMock()
    ev.to_dict.return_value = {
        "event_id": "eid_002",
        "event_type": "llm.cost.token_usage",
        "payload": {"cost_usd": 0.001},
    }
    return ev


# ─── CloudExporterError ───────────────────────────────────────────────────────

def test_cloud_exporter_error_is_runtime_error():
    err = CloudExporterError("test")
    assert isinstance(err, RuntimeError)
    assert str(err) == "test"


# ─── Initialization ──────────────────────────────────────────────────────────

class TestCloudExporterInit:
    def test_init_with_api_key(self):
        exp = CloudExporter(api_key="sf_live_test123")
        assert exp._api_key == "sf_live_test123"

    def test_init_from_env_var(self, monkeypatch):
        monkeypatch.setenv("SPANFORGE_CLOUD_API_KEY", "sf_env_key")
        exp = CloudExporter()
        assert exp._api_key == "sf_env_key"

    def test_init_no_key_raises(self, monkeypatch):
        monkeypatch.delenv("SPANFORGE_CLOUD_API_KEY", raising=False)
        with pytest.raises(CloudExporterError, match="No API key"):
            CloudExporter()

    def test_default_endpoint(self, monkeypatch):
        monkeypatch.delenv("SPANFORGE_CLOUD_ENDPOINT", raising=False)
        exp = CloudExporter(api_key="test")
        assert "getspanforge.com" in exp._endpoint

    def test_custom_endpoint_from_arg(self):
        exp = CloudExporter(api_key="test", endpoint="https://custom.example.com/v1/events")
        assert exp._endpoint == "https://custom.example.com/v1/events"

    def test_custom_endpoint_from_env(self, monkeypatch):
        monkeypatch.setenv("SPANFORGE_CLOUD_ENDPOINT", "https://myhost/v1/events")
        exp = CloudExporter(api_key="test")
        assert exp._endpoint == "https://myhost/v1/events"

    def test_default_batch_size(self):
        exp = CloudExporter(api_key="test")
        assert exp._batch_size == 100

    def test_custom_batch_size(self):
        exp = CloudExporter(api_key="test", batch_size=25)
        assert exp._batch_size == 25

    def test_default_timeout(self):
        exp = CloudExporter(api_key="test")
        assert exp._timeout == 10.0

    def test_custom_timeout(self):
        exp = CloudExporter(api_key="test", timeout=30.0)
        assert exp._timeout == 30.0

    def test_max_retries_default(self):
        exp = CloudExporter(api_key="test")
        assert exp._max_retries == 3

    def test_custom_max_retries(self):
        exp = CloudExporter(api_key="test", max_retries=1)
        assert exp._max_retries == 1


# ─── Serialisation ───────────────────────────────────────────────────────────

class TestSerialise:
    def test_fallback_serialisation(self):
        ev = _make_event()
        result = CloudExporter._serialise(ev)
        assert result["event_id"] == "eid_001"
        assert result["event_type"] == "llm.trace.span.completed"
        assert result["source"] == "test@1.0"

    def test_uses_to_dict_when_available(self):
        ev = _make_event_with_to_dict()
        result = CloudExporter._serialise(ev)
        assert result["event_id"] == "eid_002"
        assert result["event_type"] == "llm.cost.token_usage"


# ─── Export / Flush ──────────────────────────────────────────────────────────

class TestExportAndFlush:
    def setup_method(self):
        self.exp = CloudExporter(api_key="test_key", flush_interval=999)

    def test_export_queues_event(self):
        async def _run():
            ev = _make_event()
            with patch.object(self.exp, "flush", return_value=0):
                await self.exp.export(ev)
            assert len(self.exp._queue) == 1

        asyncio.run(_run())

    def test_export_batch_queues_all(self):
        async def _run():
            events = [_make_event() for _ in range(5)]
            with patch.object(self.exp, "flush", return_value=0):
                await self.exp.export_batch(events)
            assert len(self.exp._queue) == 5

        asyncio.run(_run())

    def test_flush_empty_queue_returns_zero(self):
        async def _run():
            result = await self.exp.flush()
            assert result == 0

        asyncio.run(_run())

    def test_flush_calls_send_batch(self):
        async def _run():
            ev = _make_event()
            # Manually add to queue
            self.exp._queue.append(CloudExporter._serialise(ev))
            with patch.object(self.exp, "_send_batch", return_value=1) as mock_send:
                result = await self.exp.flush()
            mock_send.assert_called_once()
            assert result == 1

        asyncio.run(_run())

    def test_export_triggers_flush_at_batch_boundary(self):
        async def _run():
            small_exp = CloudExporter(api_key="test", batch_size=2, flush_interval=999)
            events = [_make_event() for _ in range(2)]
            with patch.object(small_exp, "_send_batch", return_value=2):
                for ev in events:
                    await small_exp.export(ev)
            # Queue should be drained after hitting batch size
            assert len(small_exp._queue) == 0

        asyncio.run(_run())

    def test_export_raises_when_closed(self):
        async def _run():
            self.exp._closed = True
            with pytest.raises(CloudExporterError, match="closed"):
                await self.exp.export(_make_event())

        asyncio.run(_run())

    def test_flush_returns_zero_when_closed(self):
        async def _run():
            self.exp._closed = True
            result = await self.exp.flush()
            assert result == 0

        asyncio.run(_run())


# ─── Close ───────────────────────────────────────────────────────────────────

class TestClose:
    def test_close_sets_closed_flag(self):
        async def _run():
            exp = CloudExporter(api_key="test", flush_interval=999)
            with patch.object(exp, "_send_batch", return_value=0):
                await exp.close()
            assert exp._closed is True

        asyncio.run(_run())

    def test_close_flushes_remaining(self):
        async def _run():
            exp = CloudExporter(api_key="test", flush_interval=999)
            ev = _make_event()
            exp._queue.append(CloudExporter._serialise(ev))
            with patch.object(exp, "_send_batch", return_value=1) as mock_send:
                await exp.close()
            mock_send.assert_called()

        asyncio.run(_run())


# ─── Async context manager ────────────────────────────────────────────────────

class TestAsyncContextManager:
    def test_aenter_returns_self(self):
        async def _run():
            exp = CloudExporter(api_key="test")
            with patch.object(exp, "_send_batch", return_value=0):
                async with exp as ctx:
                    assert ctx is exp

        asyncio.run(_run())

    def test_aexit_closes(self):
        async def _run():
            exp = CloudExporter(api_key="test")
            with patch.object(exp, "_send_batch", return_value=0):
                async with exp:
                    pass
            assert exp._closed is True

        asyncio.run(_run())


# ─── Background flush thread ─────────────────────────────────────────────────

class TestFlushThread:
    def test_flush_thread_started_on_export(self):
        async def _run():
            exp = CloudExporter(api_key="test", flush_interval=999)
            ev = _make_event()
            with patch.object(exp, "flush", return_value=0):
                await exp.export(ev)
            assert exp._flush_thread is not None
            assert exp._flush_thread.is_alive()
            exp._stop_event.set()

        asyncio.run(_run())

    def test_flush_loop_sends_queued_events(self):
        import time
        exp = CloudExporter(api_key="test", flush_interval=0.05)  # very fast flush
        ev_data = CloudExporter._serialise(_make_event())
        exp._queue.append(ev_data)
        with patch.object(exp, "_send_batch", return_value=1) as mock_send:
            exp._ensure_flush_thread()
            time.sleep(0.15)  # wait for flush
            exp._stop_event.set()
        mock_send.assert_called()


# ─── Send batch error handling ────────────────────────────────────────────────

class TestSendBatchErrors:
    def test_client_error_raises(self):
        import urllib.error
        exp = CloudExporter(api_key="test", max_retries=1)
        batch = [{"event_id": "1", "event_type": "llm.trace"}]
        with patch("urllib.request.urlopen") as mock_open:
            mock_open.side_effect = urllib.error.HTTPError(
                url="", code=401, msg="Unauthorized", hdrs=None, fp=None
            )
            with pytest.raises(CloudExporterError, match="401"):
                exp._send_batch(batch)

    def test_network_error_requeues_batch(self):
        import urllib.error
        exp = CloudExporter(api_key="test", max_retries=2, flush_interval=999)
        batch = [{"event_id": "1", "event_type": "llm.trace"}]
        # Patch sleep to avoid actual waits
        with patch("time.sleep"), \
             patch("urllib.request.urlopen") as mock_open:
            mock_open.side_effect = urllib.error.URLError("connection refused")
            result = exp._send_batch(batch)
        assert result == 0
        # Batch should be requeued
        assert len(exp._queue) == len(batch)

    def test_server_5xx_retried(self):
        exp = CloudExporter(api_key="test", max_retries=2, flush_interval=999)
        batch = [{"event_id": "1"}]
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 503
        with patch("time.sleep"), \
             patch("urllib.request.urlopen", return_value=mock_resp):
            result = exp._send_batch(batch)
        assert result == 0  # all retries exhausted

    def test_successful_200_returns_count(self):
        exp = CloudExporter(api_key="test", max_retries=1)
        batch = [{"event_id": "1"}, {"event_id": "2"}]
        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.status = 200
        with patch("urllib.request.urlopen", return_value=mock_resp):
            result = exp._send_batch(batch)
        assert result == 2


# ─── Queue max size ───────────────────────────────────────────────────────────

class TestQueueMaxSize:
    def test_export_raises_when_queue_full(self):
        from spanforge.export.cloud import _MAX_QUEUE_SIZE
        exp = CloudExporter(api_key="test", flush_interval=9999)
        # Fill the queue to max manually (avoid network calls)
        for _ in range(_MAX_QUEUE_SIZE):
            exp._queue.append({"event_id": "x"})
        with pytest.raises(CloudExporterError, match="queue is full"):
            asyncio.run(exp.export(_make_event()))

    def test_export_succeeds_when_queue_has_room(self):
        from spanforge.export.cloud import _MAX_QUEUE_SIZE
        exp = CloudExporter(api_key="test", flush_interval=9999)
        for _ in range(_MAX_QUEUE_SIZE - 1):
            exp._queue.append({"event_id": "x"})
        # Should not raise — one slot available
        with patch.object(exp, "_send_batch", return_value=0):
            asyncio.run(exp.export(_make_event()))


# ─── Requeue on failure ───────────────────────────────────────────────────────

class TestRequeueOnFailure:
    def test_failed_batch_is_requeued(self):
        import urllib
        exp = CloudExporter(api_key="test", max_retries=1, flush_interval=9999)
        batch = [{"event_id": "1"}, {"event_id": "2"}]
        with patch("time.sleep"), \
             patch("urllib.request.urlopen") as mock_open:
            mock_open.side_effect = urllib.error.URLError("down")
            exp._send_batch(batch)
        # Events should be back at the front of the queue
        assert len(exp._queue) == 2
        assert next(iter(exp._queue))["event_id"] == "1"
        assert list(exp._queue)[1]["event_id"] == "2"


# ─── SSRF protection ──────────────────────────────────────────────────────────

class TestSsrfProtection:
    def test_private_ip_endpoint_rejected(self):
        with pytest.raises(ValueError, match="private/loopback"):
            CloudExporter(api_key="test", endpoint="http://192.168.1.100/ingest")

    def test_loopback_endpoint_rejected(self):
        with pytest.raises(ValueError, match="private/loopback"):
            CloudExporter(api_key="test", endpoint="http://127.0.0.1/ingest")

    def test_allow_private_addresses_overrides(self):
        exp = CloudExporter(
            api_key="test",
            endpoint="http://192.168.1.100/ingest",
            allow_private_addresses=True,
        )
        assert "192.168.1.100" in exp._endpoint

    def test_invalid_scheme_rejected(self):
        with pytest.raises(ValueError, match="valid http"):
            CloudExporter(api_key="test", endpoint="ftp://example.com/ingest")

    def test_public_https_endpoint_accepted(self):
        # DNS failure on fake hostname is treated as safe (allowed through)
        exp = CloudExporter(api_key="test", endpoint="https://ingest.example-corp.com/v1/events")
        assert exp._endpoint == "https://ingest.example-corp.com/v1/events"


# ─── Atomic export() ──────────────────────────────────────────────────────────

class TestAtomicExport:
    def test_queue_cap_is_respected_under_atomic_lock(self):
        """export() checks and appends inside the lock — queue must never exceed cap."""
        from spanforge.export.cloud import _MAX_QUEUE_SIZE
        exp = CloudExporter(api_key="test", flush_interval=9999)
        exp._queue.extend({"event_id": str(i)} for i in range(_MAX_QUEUE_SIZE - 1))

        # One more should succeed (fills to cap then flushes a batch)
        with patch.object(exp, "_send_batch", return_value=_MAX_QUEUE_SIZE):
            asyncio.run(exp.export(_make_event()))
        # flush() popped one batch; remaining = MAX - batch_size
        assert len(exp._queue) == _MAX_QUEUE_SIZE - exp._batch_size

    def test_export_raises_when_exactly_at_cap(self):
        """When queue is at exactly _MAX_QUEUE_SIZE, the next export must raise."""
        from spanforge.export.cloud import _MAX_QUEUE_SIZE
        exp = CloudExporter(api_key="test", flush_interval=9999)
        exp._queue.extend({"event_id": str(i)} for i in range(_MAX_QUEUE_SIZE))

        with pytest.raises(CloudExporterError, match="queue is full"):
            asyncio.run(exp.export(_make_event()))

