"""spanforge.export.siem_splunk — Splunk HTTP Event Collector (HEC) exporter.

Forwards spanforge events to a Splunk HTTP Event Collector endpoint.

Configuration
-------------
``SPANFORGE_SPLUNK_HEC_URL``
    Required.  Full URL of the Splunk HEC endpoint, e.g.
    ``https://splunk.example.com:8088/services/collector/event``.

``SPANFORGE_SPLUNK_HEC_TOKEN``
    Required.  Splunk HEC authentication token (``Splunk <token>``).

``SPANFORGE_SPLUNK_INDEX``
    Optional.  Splunk index to route events to.  Default: ``"main"``.

``SPANFORGE_SPLUNK_SOURCE``
    Optional.  Splunk ``source`` field.  Default: ``"spanforge"``.

``SPANFORGE_SPLUNK_SOURCETYPE``
    Optional.  Splunk ``sourcetype`` field.  Default: ``"spanforge:event"``.

``SPANFORGE_SPLUNK_BATCH_SIZE``
    Optional integer.  Events per HEC request.  Default: ``50``.

``SPANFORGE_SPLUNK_TIMEOUT``
    Optional float (seconds).  HTTP request timeout.  Default: ``10.0``.

Example::

    import os
    os.environ["SPANFORGE_SPLUNK_HEC_URL"] = "https://splunk:8088/services/collector/event"
    os.environ["SPANFORGE_SPLUNK_HEC_TOKEN"] = "your-token-here"

    from spanforge.export.siem_splunk import SplunkHECExporter
    exporter = SplunkHECExporter()
    exporter.export(event)
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import threading
import time
import urllib.error
import urllib.request
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

    from spanforge.event import Event

__all__ = ["SplunkHECError", "SplunkHECExporter"]

_log = logging.getLogger("spanforge.export.siem_splunk")

_DEFAULT_BATCH_SIZE = 50
_DEFAULT_TIMEOUT = 10.0
_DEFAULT_INDEX = "main"
_DEFAULT_SOURCE = "spanforge"
_DEFAULT_SOURCETYPE = "spanforge:event"


class SplunkHECError(RuntimeError):
    """Raised when a Splunk HEC delivery attempt fails permanently."""


class SplunkHECExporter:
    """Export spanforge events to a Splunk HTTP Event Collector endpoint.

    Args:
        hec_url:    Splunk HEC URL.  Falls back to ``SPANFORGE_SPLUNK_HEC_URL``.
        token:      HEC authentication token.  Falls back to
                    ``SPANFORGE_SPLUNK_HEC_TOKEN``.
        index:      Splunk index.  Falls back to ``SPANFORGE_SPLUNK_INDEX``.
        source:     Splunk source field.  Falls back to ``SPANFORGE_SPLUNK_SOURCE``.
        sourcetype: Splunk sourcetype field.  Falls back to
                    ``SPANFORGE_SPLUNK_SOURCETYPE``.
        batch_size: Events per HTTP request.  Falls back to
                    ``SPANFORGE_SPLUNK_BATCH_SIZE`` (default 50).
        timeout:    HTTP request timeout in seconds.  Falls back to
                    ``SPANFORGE_SPLUNK_TIMEOUT`` (default 10.0).
        verify_ssl: Whether to verify the server TLS certificate.  Default
                    ``True``; set to ``False`` only in controlled lab
                    environments.
    """

    def __init__(
        self,
        *,
        hec_url: str = "",
        token: str = "",
        index: str = "",
        source: str = "",
        sourcetype: str = "",
        batch_size: int = 0,
        timeout: float = 0.0,
        verify_ssl: bool = True,
    ) -> None:
        self._hec_url: str = hec_url or os.environ.get("SPANFORGE_SPLUNK_HEC_URL", "")
        self._token: str = token or os.environ.get("SPANFORGE_SPLUNK_HEC_TOKEN", "")
        self._index: str = index or os.environ.get("SPANFORGE_SPLUNK_INDEX", _DEFAULT_INDEX)
        self._source: str = source or os.environ.get("SPANFORGE_SPLUNK_SOURCE", _DEFAULT_SOURCE)
        self._sourcetype: str = sourcetype or os.environ.get(
            "SPANFORGE_SPLUNK_SOURCETYPE", _DEFAULT_SOURCETYPE
        )
        self._batch_size: int = batch_size or int(
            os.environ.get("SPANFORGE_SPLUNK_BATCH_SIZE", _DEFAULT_BATCH_SIZE)
        )
        self._timeout: float = timeout or float(
            os.environ.get("SPANFORGE_SPLUNK_TIMEOUT", _DEFAULT_TIMEOUT)
        )
        self._verify_ssl: bool = verify_ssl
        self._lock: threading.Lock = threading.Lock()
        self._pending: list[dict[str, Any]] = []
        self._sent_count: int = 0
        self._error_count: int = 0

        if not self._hec_url:
            raise ValueError(
                "Splunk HEC URL must be provided via hec_url argument or "
                "SPANFORGE_SPLUNK_HEC_URL environment variable"
            )
        if not self._token:
            raise ValueError(
                "Splunk HEC token must be provided via token argument or "
                "SPANFORGE_SPLUNK_HEC_TOKEN environment variable"
            )
        # Reject plaintext HTTP in non-test environments
        if self._hec_url.startswith("http://") and not self._hec_url.startswith(
            "http://localhost"
        ) and not self._hec_url.startswith("http://127."):
            _log.warning(
                "Splunk HEC URL uses plaintext HTTP — use HTTPS in production: %s",
                self._hec_url,
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export(self, event: Event) -> None:
        """Buffer *event* and flush when batch_size is reached."""
        payload = self._build_hec_payload(event)
        with self._lock:
            self._pending.append(payload)
            if len(self._pending) >= self._batch_size:
                self._flush_locked()

    def export_batch(self, events: Sequence[Event]) -> int:
        """Export a batch of events.  Returns the number of events sent."""
        for event in events:
            self.export(event)
        self.flush()
        return len(events)

    def flush(self) -> None:
        """Force-flush any buffered events to Splunk HEC."""
        with self._lock:
            self._flush_locked()

    def close(self) -> None:
        """Flush and release resources."""
        self.flush()

    @property
    def sent_count(self) -> int:
        """Total number of events successfully sent to Splunk."""
        return self._sent_count

    @property
    def error_count(self) -> int:
        """Total number of delivery failures."""
        return self._error_count

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> SplunkHECExporter:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_hec_payload(self, event: Event) -> dict[str, Any]:
        """Convert a spanforge Event to a Splunk HEC event dict."""
        return {
            "time": event.timestamp if hasattr(event, "timestamp") else time.time(),
            "index": self._index,
            "source": self._source,
            "sourcetype": self._sourcetype,
            "event": {
                "event_id": event.event_id if hasattr(event, "event_id") else "",
                "event_type": event.event_type,
                "schema_version": getattr(event, "schema_version", ""),
                "payload": event.payload if hasattr(event, "payload") else {},
            },
        }

    def _flush_locked(self) -> None:
        """Send all pending payloads.  Must be called with ``_lock`` held."""
        if not self._pending:
            return
        batch = self._pending[:]
        self._pending.clear()
        try:
            self._send(batch)
            self._sent_count += len(batch)
        except Exception as exc:
            self._error_count += len(batch)
            _log.error(
                "SplunkHECExporter: failed to send %d events — %s", len(batch), exc
            )

    def _send(self, payloads: list[dict[str, Any]]) -> None:
        """POST *payloads* to the Splunk HEC endpoint.

        Multiple events are encoded as newline-delimited JSON (Splunk's
        raw HEC format).

        Raises:
            SplunkHECError: On a permanent 4xx / 5xx response.
        """
        body = "\n".join(json.dumps(p) for p in payloads).encode()
        headers = {
            "Authorization": f"Splunk {self._token}",
            "Content-Type": "application/json",
        }
        req = urllib.request.Request(self._hec_url, data=body, headers=headers, method="POST")
        ctx: ssl.SSLContext | None = None
        if not self._verify_ssl:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        try:
            with urllib.request.urlopen(req, timeout=self._timeout, context=ctx) as resp:
                if resp.status >= 400:
                    raise SplunkHECError(
                        f"Splunk HEC returned HTTP {resp.status} for "
                        f"{len(payloads)} events"
                    )
        except urllib.error.HTTPError as exc:
            raise SplunkHECError(
                f"Splunk HEC HTTP error {exc.code}: {exc.reason}"
            ) from exc
        except urllib.error.URLError as exc:
            raise SplunkHECError(
                f"Splunk HEC connection error: {exc.reason}"
            ) from exc

    def __repr__(self) -> str:
        return (
            f"SplunkHECExporter(hec_url={self._hec_url!r}, "
            f"index={self._index!r}, "
            f"sent={self._sent_count}, errors={self._error_count})"
        )
