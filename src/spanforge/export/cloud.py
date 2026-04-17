"""spanforge.export.cloud — Cloud telemetry exporter.

Batches spanforge events and ships them to the spanforge Cloud API (or any
compatible self-hosted endpoint) over HTTPS using only stdlib ``urllib``.

Configuration
-------------
All settings are read from environment variables so no secrets end up in
source code:

``SPANFORGE_CLOUD_API_KEY``
    Required.  Your spanforge Cloud API key.

``SPANFORGE_CLOUD_ENDPOINT``
    Optional.  Override the ingestion URL.  Defaults to
    ``https://ingest.getspanforge.com/v1/events``.

``SPANFORGE_CLOUD_BATCH_SIZE``
    Optional integer.  Events per HTTP request.  Default ``100``.

``SPANFORGE_CLOUD_TIMEOUT``
    Optional seconds (float).  HTTP request timeout.  Default ``10``.

Example::

    import os
    os.environ["SPANFORGE_CLOUD_API_KEY"] = "sf_live_..."

    from spanforge.export.cloud import CloudExporter
    from spanforge import configure
    configure(exporter="cloud")

    # Events are now shipped automatically via the default TraceStore flush.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import os
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from spanforge.event import Event

__all__ = ["CloudExporter", "CloudExporterError"]

_log = logging.getLogger("spanforge.export.cloud")


def _is_private_ip_literal(host: str) -> bool:
    """Return True if *host* is a private/loopback/link-local IP literal."""
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast


def _validate_http_url(
    url: str,
    param_name: str = "url",
    *,
    allow_private_addresses: bool = False,
) -> None:
    """Raise ValueError if *url* is not a valid http(s):// URL.

    When *allow_private_addresses* is False (default), also rejects literal
    private/loopback IP addresses and hostnames that resolve to them.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{param_name} must be a valid http:// or https:// URL; got {url!r}")
    if not allow_private_addresses:
        host = parsed.hostname or ""
        if _is_private_ip_literal(host):
            raise ValueError(
                f"{param_name} resolves to a private/loopback/link-local IP address "
                f"({host!r}).  Set allow_private_addresses=True to permit this in "
                "non-production environments."
            )
        if host and not _is_private_ip_literal(host):
            try:
                resolved = socket.gethostbyname(host)
                addr = ipaddress.ip_address(resolved)
                if addr.is_private or addr.is_loopback or addr.is_link_local:
                    raise ValueError(
                        f"{param_name} hostname {host!r} resolves to a private/loopback/"
                        f"link-local address ({resolved}).  "
                        "Set allow_private_addresses=True to permit this."
                    )
            except OSError:
                pass  # DNS failure — allow through


_DEFAULT_ENDPOINT = "https://ingest.getspanforge.com/v1/events"
_DEFAULT_BATCH_SIZE = 100
_DEFAULT_TIMEOUT = 10.0
_DEFAULT_FLUSH_INTERVAL = 5.0  # seconds
_MAX_QUEUE_SIZE = 10_000  # prevent unbounded growth when endpoint is unreachable


class CloudExporterError(RuntimeError):
    """Raised when a cloud export request fails permanently."""


class CloudExporter:
    """Async-compatible batch exporter that ships events to spanforge Cloud.

    The exporter maintains an internal queue and flushes in batches either
    on a timed interval or when the queue reaches *batch_size*.  HTTP
    bodies are newline-delimited JSON (one event per line) to minimise
    memory overhead.

    Args:
        api_key:
            spanforge Cloud API key.  Falls back to the
            ``SPANFORGE_CLOUD_API_KEY`` environment variable.
        endpoint:
            HTTP(S) ingestion URL.  Falls back to
            ``SPANFORGE_CLOUD_ENDPOINT`` env var, then the default.
        batch_size:
            Maximum events per HTTP POST.
        flush_interval:
            Seconds between automatic flushes.
        timeout:
            HTTP request timeout in seconds.
        max_retries:
            Number of retries on transient errors (5xx, timeout).

    Raises:
        CloudExporterError:
            If ``api_key`` is not set via argument or environment variable.

    Example::

        async with CloudExporter(api_key="sf_live_...") as exporter:
            await exporter.export(event)
    """

    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str | None = None,
        batch_size: int | None = None,
        flush_interval: float | None = None,
        timeout: float | None = None,
        max_retries: int = 3,
        allow_private_addresses: bool = False,
    ) -> None:
        resolved_key = api_key or os.environ.get("SPANFORGE_CLOUD_API_KEY", "")
        if not resolved_key:
            raise CloudExporterError(
                "No API key provided.  Set SPANFORGE_CLOUD_API_KEY or pass api_key=."
            )
        self._api_key = resolved_key
        self._endpoint = (
            endpoint or os.environ.get("SPANFORGE_CLOUD_ENDPOINT", "") or _DEFAULT_ENDPOINT
        )
        _validate_http_url(
            self._endpoint, "endpoint", allow_private_addresses=allow_private_addresses
        )
        self._batch_size = int(
            batch_size
            if batch_size is not None
            else int(os.environ.get("SPANFORGE_CLOUD_BATCH_SIZE", _DEFAULT_BATCH_SIZE))
        )
        self._flush_interval = (
            flush_interval if flush_interval is not None else _DEFAULT_FLUSH_INTERVAL
        )
        self._timeout = float(
            timeout
            if timeout is not None
            else float(os.environ.get("SPANFORGE_CLOUD_TIMEOUT", _DEFAULT_TIMEOUT))
        )
        self._max_retries = max_retries

        self._queue: deque[dict[str, Any]] = deque()
        # threading.Lock guards the queue so both the async flush() coroutine
        # and the background _flush_loop() thread can access it safely.
        self._queue_lock = threading.Lock()
        self._closed = False

        # Background flush thread (started lazily on first export)
        self._flush_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def export(self, event: Event) -> None:
        """Queue a single event for batched delivery."""
        if self._closed:
            raise CloudExporterError("CloudExporter is closed.")
        with self._queue_lock:
            if len(self._queue) >= _MAX_QUEUE_SIZE:
                raise CloudExporterError(
                    f"Export queue is full ({_MAX_QUEUE_SIZE} events). "
                    "Cloud endpoint may be unreachable."
                )
            self._queue.append(self._serialise(event))
            should_flush = len(self._queue) >= self._batch_size
        self._ensure_flush_thread()
        if should_flush:
            await self.flush()

    async def export_batch(self, events: list[Event]) -> None:
        """Queue multiple events for batched delivery."""
        for event in events:
            await self.export(event)

    async def flush(self) -> int:
        """Drain the queue and send all pending events.  Returns sent count."""
        if self._closed:
            return 0
        with self._queue_lock:
            batch = []
            while self._queue and len(batch) < self._batch_size:
                batch.append(self._queue.popleft())
        if not batch:
            return 0
        loop = asyncio.get_running_loop()
        sent = await loop.run_in_executor(None, self._send_batch, batch)
        return sent

    async def close(self) -> None:
        """Flush remaining events and shut down the background thread."""
        self._stop_event.set()
        if self._flush_thread and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=self._timeout + 2)
        # Final flush
        await self.flush()
        self._closed = True

    # Async context manager support
    async def __aenter__(self) -> CloudExporter:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_flush_thread(self) -> None:
        if self._flush_thread is None or not self._flush_thread.is_alive():
            t = threading.Thread(
                target=self._flush_loop,
                name="spanforge-cloud-flush",
                daemon=True,
            )
            t.start()
            self._flush_thread = t

    def _flush_loop(self) -> None:
        """Background thread: flush on interval until stopped."""
        while not self._stop_event.wait(timeout=self._flush_interval):
            with self._queue_lock:
                batch = []
                while self._queue and len(batch) < self._batch_size:
                    batch.append(self._queue.popleft())
            if batch:
                try:
                    self._send_batch(batch)
                except Exception as exc:
                    _log.warning("Background flush failed: %s", exc)

    def _send_batch(self, batch: list[dict[str, Any]]) -> int:
        """HTTP POST a batch of serialised events.  Returns number sent."""
        body = "\n".join(json.dumps(ev, default=str) for ev in batch).encode("utf-8")
        headers = {
            "Content-Type": "application/x-ndjson; charset=utf-8",
            "Authorization": f"Bearer {self._api_key}",
            "X-Spanforge-SDK": "python",
            "User-Agent": "spanforge-python/2.0",
        }
        req = urllib.request.Request(
            self._endpoint,
            data=body,
            headers=headers,
            method="POST",
        )

        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                ctx = ssl.create_default_context()
                with urllib.request.urlopen(req, timeout=self._timeout, context=ctx) as resp:
                    status = resp.status
                    if 200 <= status < 300:
                        _log.debug(
                            "Shipped %d events → %s (%s)", len(batch), self._endpoint, status
                        )
                        return len(batch)
                    # Non-retryable client error
                    if 400 <= status < 500:
                        raise CloudExporterError(
                            f"Cloud API rejected batch: HTTP {status} (check API key and payload)"
                        )
                    # 5xx — retryable
                    _log.warning(
                        "Server error %s on attempt %d/%d", status, attempt, self._max_retries
                    )

            except urllib.error.HTTPError as exc:
                if 400 <= exc.code < 500:
                    raise CloudExporterError(f"Cloud API rejected batch: HTTP {exc.code}") from exc
                last_exc = exc
                _log.warning("HTTP %s on attempt %d/%d", exc.code, attempt, self._max_retries)
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                last_exc = exc
                _log.warning("Network error on attempt %d/%d: %s", attempt, self._max_retries, exc)

            if attempt < self._max_retries:
                time.sleep(min(2**attempt, 30))  # exponential back-off

        # Re-enqueue failed batch at the front for next flush cycle
        with self._queue_lock:
            self._queue.extendleft(reversed(batch))
        _log.error("Failed to ship batch after %d attempts: %s", self._max_retries, last_exc)
        return 0

    @staticmethod
    def _serialise(event: Event) -> dict[str, Any]:
        """Convert an Event to a plain dict for JSON serialisation."""
        if hasattr(event, "to_dict"):
            return event.to_dict()
        # Fallback for duck-typed event objects
        return {
            k: getattr(event, k, None)
            for k in (
                "event_id",
                "event_type",
                "payload",
                "schema_version",
                "source",
                "span_id",
                "trace_id",
                "timestamp",
                "tags",
                "signature",
                "checksum",
                "prev_id",
            )
        }
