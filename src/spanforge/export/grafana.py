"""spanforge.export.grafana — Grafana Loki log exporter.

Pushes SpanForge events to a **Grafana Loki** instance through the
``/loki/api/v1/push`` endpoint.

Transport
---------
Uses :func:`urllib.request.urlopen` in a thread-pool executor so the async
event loop is never blocked.  The request body is JSON-encoded following the
Loki push API v1.  No external dependencies are required.

Stream labels
-------------
By default each entry is tagged with:

* ``event_type``   — the dot-separated event type, with dots replaced by
  underscores so the value is a legal Prometheus label value.
* ``org_id``       — ``event.org_id`` (if present).
* any user-supplied global *labels* passed to the constructor.

Set ``include_envelope_labels=False`` to suppress the ``event_type`` and
``org_id`` fields from the stream labels.

Usage::

    from spanforge.export.grafana import GrafanaLokiExporter

    exporter = GrafanaLokiExporter(
        url="http://localhost:3100",  # NOSONAR
        labels={"app": "my-llm-service"},
        tenant_id="my-org",
    )
    await exporter.export(event)
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from spanforge.exceptions import ExportError

if TYPE_CHECKING:
    from collections.abc import Sequence

    from spanforge.event import Event

__all__ = [
    "GrafanaLokiExporter",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_private_ip_literal(host: str) -> bool:
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
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            f"{param_name} must be a valid http:// or https:// URL; got {url!r}"
        )
    if not allow_private_addresses:
        host = parsed.hostname or ""
        if _is_private_ip_literal(host):
            raise ValueError(
                f"{param_name} resolves to a private/loopback/link-local IP address "
                f"({host!r}).  Set allow_private_addresses=True to permit this."
            )
        # DNS-based SSRF check — best-effort; DNS failure is non-fatal.
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
            except OSError:  # DNS failure — allow through
                pass


# ---------------------------------------------------------------------------
# Main exporter
# ---------------------------------------------------------------------------


class GrafanaLokiExporter:
    """Async exporter that ships SpanForge events to Grafana Loki.

    Args:
        url:                     Loki base URL (e.g. ``"http://localhost:3100"``).
        labels:                  Global stream labels applied to every entry.
        timeout:                 Per-request timeout in seconds (default 10.0).
        tenant_id:               When set, included in ``X-Scope-OrgID`` header.
        include_envelope_labels: Whether to add ``event_type`` and ``org_id``
                                 from the event envelope to the stream labels
                                 (default ``True``).

    Raises:
        ValueError: If *url* is not a valid HTTP/HTTPS URL or *timeout* is not
                    positive.
    """

    def __init__(  # noqa: PLR0913
        self,
        url: str,
        *,
        labels: dict[str, str] | None = None,
        timeout: float = 10.0,
        tenant_id: str | None = None,
        include_envelope_labels: bool = True,
        allow_private_addresses: bool = False,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        _validate_http_url(url, "url", allow_private_addresses=allow_private_addresses)

        self._base_url = url.rstrip("/")
        self._global_labels: dict[str, str] = dict(labels or {})
        self._timeout = timeout
        self._tenant_id: str | None = tenant_id
        self._include_envelope_labels = include_envelope_labels

    # ------------------------------------------------------------------
    # Public conversion API
    # ------------------------------------------------------------------

    def event_to_loki_entry(self, event: Event) -> dict[str, Any]:
        """Convert a SpanForge :class:`~spanforge.event.Event` to a Loki log entry dict.

        The returned dict has shape::

            {
                "stream": {"key": "value", ...},
                "values": [["<nanoseconds>", "<json payload>"]],
            }

        Args:
            event: The event to convert.

        Returns:
            A dict ready to be included in a Loki push request.
        """
        # Build stream labels
        stream: dict[str, str] = {}

        if self._include_envelope_labels:
            # Replace dots with underscores — Loki label values are Prometheus labels
            event_type_label = str(event.event_type).replace(".", "_")
            stream["event_type"] = event_type_label
            if event.org_id:
                stream["org_id"] = event.org_id

        # User-supplied global labels come last (may override envelope labels)
        stream.update(self._global_labels)

        # Build the log line (JSON)
        try:
            line = event.to_json()
        except Exception:  # NOSONAR
            line = json.dumps(
                {
                    "event_id": str(getattr(event, "event_id", "")),
                    "event_type": str(event.event_type),
                    "timestamp": event.timestamp,
                }
            )

        # Timestamp in nanoseconds as string
        ns_str = str(self._iso_to_ns(event.timestamp))

        return {
            "stream": stream,
            "values": [[ns_str, line]],
        }

    @staticmethod
    def _iso_to_ns(ts: str) -> int:
        """Convert an ISO-8601 timestamp string to nanoseconds since Unix epoch.

        Args:
            ts: ISO-8601 datetime string (e.g. ``"2024-01-15T12:00:00.000000Z"``).

        Returns:
            Integer nanoseconds since the Unix epoch.
        """
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp() * 1_000_000_000)
        except ValueError as exc:
            raise ExportError(
                "grafana_loki",
                f"cannot parse event timestamp {ts!r}: {exc}",
            ) from exc

    # ------------------------------------------------------------------
    # Async export API
    # ------------------------------------------------------------------

    async def export(self, event: Event) -> None:
        """Export a single event to Grafana Loki.

        Args:
            event: The event to export.

        Raises:
            ExportError: On HTTP or network errors.
        """
        await self.export_batch([event])

    async def export_batch(self, events: Sequence[Event]) -> int:
        """Export multiple events to Grafana Loki.

        Events that share identical stream labels are grouped into the same
        Loki stream to reduce push requests.

        Args:
            events: Sequence of events to deliver.

        Returns:
            Number of events successfully submitted.

        Raises:
            ExportError: On HTTP or network errors.
        """
        if not events:
            return 0

        # Group by frozenset of stream label items
        groups: dict[Any, tuple[dict[str, str], list[list[str]]]] = {}
        for event in events:
            entry = self.event_to_loki_entry(event)
            stream = entry["stream"]
            key = frozenset(stream.items())
            if key not in groups:
                groups[key] = (stream, [])
            groups[key][1].extend(entry["values"])

        streams: list[dict[str, Any]] = [
            {"stream": stream_labels, "values": values}
            for (stream_labels, values) in groups.values()
        ]

        payload = json.dumps({"streams": streams}).encode("utf-8")
        await self._push(payload)
        return len(events)

    # ------------------------------------------------------------------
    # Internal HTTP helpers
    # ------------------------------------------------------------------

    async def _push(self, payload: bytes) -> None:
        """Push a serialised Loki request body to the ingest endpoint.

        Args:
            payload: JSON-encoded bytes to POST.

        Raises:
            ExportError: On HTTP or network failure.
        """
        await asyncio.get_event_loop().run_in_executor(
            None, lambda: self._do_push(payload)
        )

    def _do_push(self, body: bytes) -> None:
        """Perform a synchronous HTTP POST to ``/loki/api/v1/push`` (called from executor).

        Args:
            body: Request body bytes.

        Raises:
            ExportError: On HTTP or network failure.
            EgressViolationError: If the endpoint is blocked by egress policy.
        """
        from spanforge.egress import check_egress  # noqa: PLC0415

        url = f"{self._base_url}/loki/api/v1/push"
        check_egress(url, backend="grafana-loki")
        headers: dict[str, str] = {
            "Content-Type": "application/json",
        }
        if self._tenant_id:
            headers["X-Scope-OrgID"] = self._tenant_id

        req = urllib.request.Request(url=url, data=body, headers=headers, method="POST")  # noqa: S310  # NOSONAR
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # noqa: S310  # NOSONAR
                resp.read()
        except urllib.error.HTTPError as exc:
            raise ExportError(
                "grafana-loki", f"HTTP {exc.code} from {url}: {exc.reason}"
            ) from exc
        except OSError as exc:
            raise ExportError(
                "grafana-loki", f"network error posting to {url}: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"GrafanaLokiExporter(url={self._base_url!r}, "
            f"tenant_id={self._tenant_id!r})"
        )
