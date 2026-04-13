"""Tests for spanforge.export.redis_backend — RedisExporter and RedisEventReader.

Redis is mocked throughout; no real Redis server is needed.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from spanforge.event import Event


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(namespace: str = "llm.trace.span.completed") -> Event:
    return Event(
        event_type=namespace,
        source="test-service@1.0.0",
        payload={"status": "ok", "span_name": "test"},
    )


def _make_redis_mock() -> MagicMock:
    """Return a mock redis.asyncio module with a usable client factory."""
    client = MagicMock()
    client.xadd = AsyncMock(return_value=b"1234-0")
    client.expire = AsyncMock(return_value=True)
    client.aclose = AsyncMock()

    # pipeline mock
    pipe = MagicMock()
    pipe.xadd = MagicMock()
    pipe.expire = MagicMock()
    pipe.execute = AsyncMock(return_value=[])
    client.pipeline = MagicMock(return_value=pipe)

    redis_mod = MagicMock()
    redis_mod.from_url = MagicMock(return_value=client)
    return redis_mod, client, pipe


# ---------------------------------------------------------------------------
# _require_redis
# ---------------------------------------------------------------------------


class TestRequireRedis:
    def test_raises_import_error_when_redis_missing(self) -> None:
        from spanforge.export.redis_backend import _require_redis  # noqa: PLC0415

        redis_keys = [k for k in sys.modules if k == "redis" or k.startswith("redis.")]
        saved = {k: sys.modules.pop(k) for k in redis_keys}
        sys.modules["redis"] = None  # type: ignore[assignment]
        sys.modules["redis.asyncio"] = None  # type: ignore[assignment]
        try:
            with pytest.raises(ImportError, match="redis"):
                _require_redis()
        finally:
            for k, v in saved.items():
                sys.modules[k] = v
            sys.modules.pop("redis", None)
            sys.modules.pop("redis.asyncio", None)

    def test_returns_redis_asyncio_when_present(self) -> None:
        from spanforge.export.redis_backend import _require_redis  # noqa: PLC0415

        # redis may or may not be installed; just confirm it either succeeds or
        # raises ImportError with the right message.
        try:
            result = _require_redis()
            assert result is not None
        except ImportError as exc:
            assert "redis" in str(exc).lower()


# ---------------------------------------------------------------------------
# RedisExporter.__init__
# ---------------------------------------------------------------------------


class TestRedisExporterInit:
    def test_defaults(self) -> None:
        from spanforge.export.redis_backend import RedisExporter  # noqa: PLC0415

        exp = RedisExporter()
        assert exp._stream_key == "spanforge:events"
        assert exp._max_len == 100_000
        assert exp._ttl == 0

    def test_custom_params(self) -> None:
        from spanforge.export.redis_backend import RedisExporter  # noqa: PLC0415

        exp = RedisExporter(
            url="redis://myhost:6379",
            stream_key="myapp:events",
            max_len=500,
            ttl_seconds=60,
        )
        assert exp._url == "redis://myhost:6379"
        assert exp._stream_key == "myapp:events"
        assert exp._max_len == 500
        assert exp._ttl == 60

    def test_env_var_stream_key_via_empty_arg(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spanforge.export.redis_backend import RedisExporter  # noqa: PLC0415

        # The stream_key env var is only picked up when stream_key=="" (falsy),
        # because the logic is: self._stream_key = stream_key or env_var.
        monkeypatch.setenv("SPANFORGE_REDIS_STREAM_KEY", "env:stream")
        exp = RedisExporter(stream_key="")
        assert exp._stream_key == "env:stream"

    def test_env_var_max_len(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spanforge.export.redis_backend import RedisExporter  # noqa: PLC0415

        monkeypatch.setenv("SPANFORGE_REDIS_MAX_LEN", "9999")
        exp = RedisExporter()
        assert exp._max_len == 9999

    def test_env_var_ttl(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spanforge.export.redis_backend import RedisExporter  # noqa: PLC0415

        monkeypatch.setenv("SPANFORGE_REDIS_TTL_SECONDS", "120")
        exp = RedisExporter()
        assert exp._ttl == 120


# ---------------------------------------------------------------------------
# RedisExporter.export
# ---------------------------------------------------------------------------


class TestRedisExporterExport:
    def test_export_calls_xadd(self) -> None:
        from spanforge.export.redis_backend import RedisExporter  # noqa: PLC0415

        redis_mod, client, _ = _make_redis_mock()
        event = _make_event()

        async def _run() -> None:
            exp = RedisExporter(stream_key="test:stream")
            with patch(
                "spanforge.export.redis_backend._require_redis",
                return_value=redis_mod,
            ):
                await exp._connect()
                await exp.export(event)

        asyncio.run(_run())
        client.xadd.assert_called_once()
        call_args = client.xadd.call_args
        assert call_args[0][0] == "test:stream"

    def test_export_sets_ttl_when_configured(self) -> None:
        from spanforge.export.redis_backend import RedisExporter  # noqa: PLC0415

        redis_mod, client, _ = _make_redis_mock()
        event = _make_event()

        async def _run() -> None:
            exp = RedisExporter(ttl_seconds=30)
            with patch(
                "spanforge.export.redis_backend._require_redis",
                return_value=redis_mod,
            ):
                await exp._connect()
                await exp.export(event)

        asyncio.run(_run())
        client.expire.assert_called_once()

    def test_export_no_ttl_call_when_zero(self) -> None:
        from spanforge.export.redis_backend import RedisExporter  # noqa: PLC0415

        redis_mod, client, _ = _make_redis_mock()
        event = _make_event()

        async def _run() -> None:
            exp = RedisExporter(ttl_seconds=0)
            with patch(
                "spanforge.export.redis_backend._require_redis",
                return_value=redis_mod,
            ):
                await exp._connect()
                await exp.export(event)

        asyncio.run(_run())
        client.expire.assert_not_called()

    def test_export_auto_connects_when_no_client(self) -> None:
        from spanforge.export.redis_backend import RedisExporter  # noqa: PLC0415

        redis_mod, client, _ = _make_redis_mock()
        event = _make_event()

        async def _run() -> None:
            exp = RedisExporter()
            # _client is None at construction
            assert exp._client is None
            with patch(
                "spanforge.export.redis_backend._require_redis",
                return_value=redis_mod,
            ):
                await exp.export(event)
            # After export, client is connected
            assert exp._client is not None

        asyncio.run(_run())

    def test_export_payload_is_valid_json(self) -> None:
        from spanforge.export.redis_backend import RedisExporter  # noqa: PLC0415

        redis_mod, client, _ = _make_redis_mock()
        event = _make_event()

        async def _run() -> None:
            exp = RedisExporter()
            with patch(
                "spanforge.export.redis_backend._require_redis",
                return_value=redis_mod,
            ):
                await exp._connect()
                await exp.export(event)

        asyncio.run(_run())
        fields_arg = client.xadd.call_args[0][1]
        data_bytes = fields_arg.get(b"data") or fields_arg.get("data")
        if isinstance(data_bytes, bytes):
            data_bytes = data_bytes.decode()
        parsed = json.loads(data_bytes)
        assert "event_id" in parsed


# ---------------------------------------------------------------------------
# RedisExporter.export_batch
# ---------------------------------------------------------------------------


class TestRedisExporterExportBatch:
    def test_export_batch_empty_list_noop(self) -> None:
        from spanforge.export.redis_backend import RedisExporter  # noqa: PLC0415

        redis_mod, client, _ = _make_redis_mock()

        async def _run() -> None:
            exp = RedisExporter()
            with patch(
                "spanforge.export.redis_backend._require_redis",
                return_value=redis_mod,
            ):
                await exp._connect()
                await exp.export_batch([])

        asyncio.run(_run())
        client.pipeline.assert_not_called()

    def test_export_batch_multiple_events(self) -> None:
        from spanforge.export.redis_backend import RedisExporter  # noqa: PLC0415

        redis_mod, client, pipe = _make_redis_mock()
        events = [_make_event() for _ in range(3)]

        async def _run() -> None:
            exp = RedisExporter()
            with patch(
                "spanforge.export.redis_backend._require_redis",
                return_value=redis_mod,
            ):
                await exp._connect()
                await exp.export_batch(events)

        asyncio.run(_run())
        assert pipe.xadd.call_count == 3
        pipe.execute.assert_called_once()

    def test_export_batch_sets_ttl_when_configured(self) -> None:
        from spanforge.export.redis_backend import RedisExporter  # noqa: PLC0415

        redis_mod, client, pipe = _make_redis_mock()
        events = [_make_event()]

        async def _run() -> None:
            exp = RedisExporter(ttl_seconds=60)
            with patch(
                "spanforge.export.redis_backend._require_redis",
                return_value=redis_mod,
            ):
                await exp._connect()
                await exp.export_batch(events)

        asyncio.run(_run())
        pipe.expire.assert_called_once()


# ---------------------------------------------------------------------------
# RedisExporter.close / flush / context manager
# ---------------------------------------------------------------------------


class TestRedisExporterClose:
    def test_close_calls_aclose(self) -> None:
        from spanforge.export.redis_backend import RedisExporter  # noqa: PLC0415

        redis_mod, client, _ = _make_redis_mock()

        async def _run() -> None:
            exp = RedisExporter()
            with patch(
                "spanforge.export.redis_backend._require_redis",
                return_value=redis_mod,
            ):
                await exp._connect()
                await exp.close()
            assert exp._client is None

        asyncio.run(_run())
        client.aclose.assert_called_once()

    def test_close_noop_when_not_connected(self) -> None:
        from spanforge.export.redis_backend import RedisExporter  # noqa: PLC0415

        async def _run() -> None:
            exp = RedisExporter()
            await exp.close()  # must not raise

        asyncio.run(_run())

    def test_close_swallows_exception(self) -> None:
        from spanforge.export.redis_backend import RedisExporter  # noqa: PLC0415

        redis_mod, client, _ = _make_redis_mock()
        client.aclose = AsyncMock(side_effect=RuntimeError("conn lost"))

        async def _run() -> None:
            exp = RedisExporter()
            with patch(
                "spanforge.export.redis_backend._require_redis",
                return_value=redis_mod,
            ):
                await exp._connect()
                await exp.close()  # must not propagate

        asyncio.run(_run())

    def test_flush_is_noop(self) -> None:
        from spanforge.export.redis_backend import RedisExporter  # noqa: PLC0415

        async def _run() -> None:
            exp = RedisExporter()
            await exp.flush()  # must not raise

        asyncio.run(_run())

    def test_context_manager(self) -> None:
        from spanforge.export.redis_backend import RedisExporter  # noqa: PLC0415

        redis_mod, client, _ = _make_redis_mock()

        async def _run() -> None:
            with patch(
                "spanforge.export.redis_backend._require_redis",
                return_value=redis_mod,
            ):
                async with RedisExporter() as exp:
                    assert exp._client is not None
            assert exp._client is None

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# RedisEventReader
# ---------------------------------------------------------------------------


class TestRedisEventReader:
    def test_read_yields_parsed_events(self) -> None:
        from spanforge.export.redis_backend import RedisEventReader  # noqa: PLC0415

        event = _make_event()
        payload = json.dumps(event.to_dict(), separators=(",", ":"), default=str).encode()
        raw_entries = [
            ("spanforge:events", [("1234-0", {b"data": payload})])
        ]

        client = MagicMock()
        client.xread = AsyncMock(return_value=raw_entries)
        client.aclose = AsyncMock()

        redis_mod = MagicMock()
        redis_mod.from_url = MagicMock(return_value=client)

        async def _run() -> list[dict]:
            results = []
            with patch(
                "spanforge.export.redis_backend._require_redis",
                return_value=redis_mod,
            ):
                async with RedisEventReader(stream_key="spanforge:events") as reader:
                    async for item in reader.read(count=10):
                        results.append(item)
            return results

        results = asyncio.run(_run())
        assert len(results) == 1
        assert "event_id" in results[0]

    def test_read_empty_stream_returns_nothing(self) -> None:
        from spanforge.export.redis_backend import RedisEventReader  # noqa: PLC0415

        client = MagicMock()
        client.xread = AsyncMock(return_value=[])
        client.aclose = AsyncMock()
        redis_mod = MagicMock()
        redis_mod.from_url = MagicMock(return_value=client)

        async def _run() -> list[dict]:
            results = []
            with patch(
                "spanforge.export.redis_backend._require_redis",
                return_value=redis_mod,
            ):
                async with RedisEventReader() as reader:
                    async for item in reader.read():
                        results.append(item)
            return results

        assert asyncio.run(_run()) == []

    def test_read_skips_invalid_json(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        from spanforge.export.redis_backend import RedisEventReader  # noqa: PLC0415

        raw_entries = [
            ("spanforge:events", [("1234-0", {b"data": b"NOT_JSON"})])
        ]
        client = MagicMock()
        client.xread = AsyncMock(return_value=raw_entries)
        client.aclose = AsyncMock()
        redis_mod = MagicMock()
        redis_mod.from_url = MagicMock(return_value=client)

        import logging

        async def _run() -> list[dict]:
            results = []
            with patch(
                "spanforge.export.redis_backend._require_redis",
                return_value=redis_mod,
            ):
                async with RedisEventReader() as reader:
                    with caplog.at_level(logging.WARNING, logger="spanforge.export.redis_backend"):
                        async for item in reader.read():
                            results.append(item)
            return results

        results = asyncio.run(_run())
        assert results == []
        assert any("deserialise" in r.message for r in caplog.records)

    def test_read_raises_when_not_context_managed(self) -> None:
        from spanforge.export.redis_backend import RedisEventReader  # noqa: PLC0415

        async def _run() -> None:
            reader = RedisEventReader()
            with pytest.raises(RuntimeError, match="async with"):
                async for _ in reader.read():
                    pass

        asyncio.run(_run())

    def test_read_handles_string_data_field(self) -> None:
        from spanforge.export.redis_backend import RedisEventReader  # noqa: PLC0415

        event = _make_event()
        payload_str = json.dumps(event.to_dict(), separators=(",", ":"), default=str)
        raw_entries = [
            ("spanforge:events", [("1234-0", {"data": payload_str})])
        ]
        client = MagicMock()
        client.xread = AsyncMock(return_value=raw_entries)
        client.aclose = AsyncMock()
        redis_mod = MagicMock()
        redis_mod.from_url = MagicMock(return_value=client)

        async def _run() -> list[dict]:
            results = []
            with patch(
                "spanforge.export.redis_backend._require_redis",
                return_value=redis_mod,
            ):
                async with RedisEventReader() as reader:
                    async for item in reader.read():
                        results.append(item)
            return results

        results = asyncio.run(_run())
        assert len(results) == 1
