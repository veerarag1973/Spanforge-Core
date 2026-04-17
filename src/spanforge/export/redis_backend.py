"""spanforge.export.redis_backend — Redis-backed event cache and exporter.

Stores serialised spanforge events in a Redis stream (``XADD``) or a capped
list, making exported events available to multiple consumers and providing a
persistent replay buffer.

**Optional dependency**: requires ``redis >= 4.0``.  Install via::

    pip install "spanforge[redis]"

Usage::

    import asyncio
    import spanforge
    from spanforge.export.redis_backend import RedisExporter

    async def main():
        exporter = RedisExporter(url="redis://localhost:6379", stream_key="spanforge:events")
        spanforge.configure(exporter="redis", endpoint="redis://localhost:6379")

        async with exporter:
            with spanforge.span("my-llm-call") as span:
                span.set_model(model="gpt-4o", system="openai")
                span.set_status("ok")

    asyncio.run(main())

Reading events back::

    from spanforge.export.redis_backend import RedisEventReader
    reader = RedisEventReader(url="redis://localhost:6379", stream_key="spanforge:events")
    async for event_dict in reader.read(count=100):
        print(event_dict)

Environment variables::

    SPANFORGE_REDIS_URL          Redis connection URL (default: redis://localhost:6379)
    SPANFORGE_REDIS_STREAM_KEY   Stream key name (default: spanforge:events)
    SPANFORGE_REDIS_MAX_LEN      Max stream length / MAXLEN trim (default: 100000)
    SPANFORGE_REDIS_TTL_SECONDS  Per-entry TTL; 0 = no TTL (default: 0)
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from spanforge.event import Event

__all__ = ["RedisEventReader", "RedisExporter"]

logger = logging.getLogger(__name__)

_DEFAULT_URL = "redis://localhost:6379"
_DEFAULT_STREAM_KEY = "spanforge:events"
_DEFAULT_MAX_LEN = 100_000


def _require_redis():
    """Import and return the redis.asyncio module, raising ImportError with hint if absent."""
    try:
        import redis.asyncio as aioredis  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "The Redis exporter requires the 'redis' package. "
            'Install it with: pip install "spanforge[redis]"'
        ) from exc
    else:
        return aioredis


class RedisExporter:
    """Async exporter that writes spanforge events into a Redis Stream.

    Uses Redis Streams (``XADD``) with approximate ``MAXLEN`` trimming to
    provide a durable, multi-consumer event buffer.

    Args:
        url:           Redis connection URL (``redis://``, ``rediss://``, or
                       ``unix://`` socket path).
        stream_key:    Redis stream key name.
        max_len:       Approximate maximum number of entries retained in the stream.
                       Older entries are trimmed automatically.
        ttl_seconds:   When > 0, the Redis key TTL is refreshed on every write
                       (sliding expiry).  ``0`` disables TTL management.
        decode_responses: Whether to decode Redis responses to Python strings
                       (default: False — bytes are returned for payloads).

    Thread / coroutine safety:
        The underlying ``redis.asyncio`` client is coroutine-safe.  Concurrent
        calls to :meth:`export` are safe without external locking.
    """

    def __init__(
        self,
        url: str = _DEFAULT_URL,
        stream_key: str = _DEFAULT_STREAM_KEY,
        max_len: int = _DEFAULT_MAX_LEN,
        ttl_seconds: int = 0,
        *,
        decode_responses: bool = False,
    ) -> None:
        self._url = url or os.environ.get("SPANFORGE_REDIS_URL", _DEFAULT_URL)
        self._stream_key = stream_key or os.environ.get(
            "SPANFORGE_REDIS_STREAM_KEY", _DEFAULT_STREAM_KEY
        )
        max_len_env = int(os.environ.get("SPANFORGE_REDIS_MAX_LEN", str(_DEFAULT_MAX_LEN)))
        self._max_len = max_len if max_len != _DEFAULT_MAX_LEN else max_len_env
        ttl_env = int(os.environ.get("SPANFORGE_REDIS_TTL_SECONDS", "0"))
        self._ttl = ttl_seconds if ttl_seconds != 0 else ttl_env
        self._decode = decode_responses
        self._client: object | None = None

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> RedisExporter:
        await self._connect()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _connect(self) -> None:
        if self._client is not None:
            return
        aioredis = _require_redis()
        self._client = aioredis.from_url(self._url, decode_responses=self._decode)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def export(self, event: Event) -> None:
        """Serialize *event* and write it to the Redis stream.

        Args:
            event: spanforge :class:`~spanforge.event.Event` instance.

        Raises:
            ImportError: If the ``redis`` package is not installed.
            redis.RedisError: On connection or write failure.
        """
        if self._client is None:
            await self._connect()

        payload = json.dumps(event.to_dict(), separators=(",", ":"), default=str)
        fields = {
            b"data" if not self._decode else "data": (
                payload.encode() if not self._decode else payload
            ),
            b"event_id" if not self._decode else "event_id": (
                event.event_id.encode() if not self._decode else event.event_id
            ),
            b"event_type" if not self._decode else "event_type": (
                event.event_type.encode() if not self._decode else event.event_type
            ),
        }
        assert self._client is not None
        await self._client.xadd(  # type: ignore[attr-defined]
            self._stream_key,
            fields,
            maxlen=self._max_len,
            approximate=True,
        )
        if self._ttl > 0:
            await self._client.expire(self._stream_key, self._ttl)  # type: ignore[attr-defined]

    async def export_batch(self, events: list[Event]) -> None:
        """Write multiple events in a single pipeline round-trip."""
        if not events:
            return
        if self._client is None:
            await self._connect()

        assert self._client is not None
        pipe = self._client.pipeline(transaction=False)  # type: ignore[attr-defined]
        for event in events:
            payload = json.dumps(event.to_dict(), separators=(",", ":"), default=str)
            fields = {
                b"data" if not self._decode else "data": (
                    payload.encode() if not self._decode else payload
                ),
                b"event_id" if not self._decode else "event_id": (
                    event.event_id.encode() if not self._decode else event.event_id
                ),
            }
            pipe.xadd(self._stream_key, fields, maxlen=self._max_len, approximate=True)
        if self._ttl > 0:
            pipe.expire(self._stream_key, self._ttl)
        await pipe.execute()

    async def close(self) -> None:
        """Close the underlying Redis connection."""
        if self._client is not None:
            try:
                await self._client.aclose()  # type: ignore[attr-defined]
            except Exception as _err:
                logger.debug("Redis close error: %s", _err)
            finally:
                self._client = None

    async def flush(self) -> None:
        """No-op — Redis writes are immediately durable."""


class RedisEventReader:
    """Read spanforge events back from a Redis Stream.

    Args:
        url:        Redis connection URL.
        stream_key: Redis stream key name.

    Example::

        reader = RedisEventReader(url="redis://localhost:6379")
        async for raw in reader.read(count=50, last_id="0"):
            print(raw)
    """

    def __init__(
        self,
        url: str = _DEFAULT_URL,
        stream_key: str = _DEFAULT_STREAM_KEY,
    ) -> None:
        self._url = url
        self._stream_key = stream_key
        self._client: object | None = None

    async def __aenter__(self) -> RedisEventReader:
        aioredis = _require_redis()
        self._client = aioredis.from_url(self._url, decode_responses=True)
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._client is not None:
            await self._client.aclose()  # type: ignore[attr-defined]

    async def read(
        self,
        count: int = 100,
        last_id: str = "0",
    ) -> AsyncIterator[dict]:
        """Yield event dicts from the stream starting after *last_id*.

        Args:
            count:   Maximum number of entries to fetch per call.
            last_id: Stream entry ID to start reading from (exclusive).
                     ``"0"`` reads from the beginning.
                     ``"$"`` reads only new entries.

        Yields:
            Raw event dicts (deserialised from the ``data`` field).
        """
        if self._client is None:
            raise RuntimeError("Use 'async with RedisEventReader(...) as reader:' first")

        entries = await self._client.xread(  # type: ignore[attr-defined]
            {self._stream_key: last_id}, count=count
        )
        if not entries:
            return
        for _stream_name, records in entries:
            for _entry_id, fields in records:
                raw = fields.get("data") or fields.get(b"data", b"{}")
                if isinstance(raw, bytes):
                    raw = raw.decode()
                try:
                    yield json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("RedisEventReader: could not deserialise entry")
                    continue
