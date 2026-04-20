"""spanforge.export.siem_syslog — Syslog / CEF exporter.

Forwards spanforge events to a remote syslog receiver (RFC 5424) optionally
encoded as ArcSight Common Event Format (CEF).

Configuration
-------------
``SPANFORGE_SYSLOG_HOST``
    Required.  Syslog receiver hostname or IP.

``SPANFORGE_SYSLOG_PORT``
    Optional integer.  UDP or TCP port.  Default: ``514``.

``SPANFORGE_SYSLOG_TRANSPORT``
    Optional.  ``"udp"`` (default) or ``"tcp"``.

``SPANFORGE_SYSLOG_FORMAT``
    Optional.  ``"rfc5424"`` (default) or ``"cef"``.

``SPANFORGE_SYSLOG_APP_NAME``
    Optional.  Syslog APP-NAME field.  Default: ``"spanforge"``.

``SPANFORGE_SYSLOG_FACILITY``
    Optional integer (0-23).  Syslog facility code.  Default: ``16`` (local0).

Example::

    import os
    os.environ["SPANFORGE_SYSLOG_HOST"] = "siem.example.com"
    os.environ["SPANFORGE_SYSLOG_PORT"] = "6514"
    os.environ["SPANFORGE_SYSLOG_FORMAT"] = "cef"

    from spanforge.export.siem_syslog import SyslogExporter
    exporter = SyslogExporter()
    exporter.export(event)
"""

from __future__ import annotations

import json
import logging
import os
import re
import socket
import threading
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from spanforge.event import Event

__all__ = ["SyslogExporter", "SyslogExporterError"]

_log = logging.getLogger("spanforge.export.siem_syslog")

_DEFAULT_PORT = 514
_DEFAULT_TRANSPORT = "udp"
_DEFAULT_FORMAT = "rfc5424"
_DEFAULT_APP_NAME = "spanforge"
_DEFAULT_FACILITY = 16  # local0

# Syslog severity mapping (spanforge event_type prefix → syslog severity)
_SEVERITY_MAP: dict[str, int] = {
    "alert": 1,  # Alert — action must be taken immediately
    "error": 3,  # Error
    "warn": 4,  # Warning
    "warning": 4,  # Warning
    "info": 6,  # Informational
    "debug": 7,  # Debug
    "trace": 7,  # Debug
}

# CEF vendor / device fields
_CEF_VENDOR = "SpanForge"
_CEF_PRODUCT = "SpanForge"
_CEF_VERSION = "1.0"

# Characters that must be escaped in CEF extension values
_CEF_ESCAPE_RE = re.compile(r"([\\|=])")


class SyslogExporterError(RuntimeError):
    """Raised when a syslog delivery attempt fails permanently."""


class SyslogExporter:
    """Export spanforge events to a remote syslog receiver.

    Supports RFC 5424 syslog and ArcSight Common Event Format (CEF).

    Args:
        host:       Syslog receiver hostname.  Falls back to
                    ``SPANFORGE_SYSLOG_HOST``.
        port:       Receiver port.  Falls back to ``SPANFORGE_SYSLOG_PORT``
                    (default 514).
        transport:  ``"udp"`` or ``"tcp"``.  Falls back to
                    ``SPANFORGE_SYSLOG_TRANSPORT`` (default ``"udp"``).
        format:     ``"rfc5424"`` or ``"cef"``.  Falls back to
                    ``SPANFORGE_SYSLOG_FORMAT`` (default ``"rfc5424"``).
        app_name:   Syslog APP-NAME.  Falls back to ``SPANFORGE_SYSLOG_APP_NAME``
                    (default ``"spanforge"``).
        facility:   Syslog facility code (0–23).  Falls back to
                    ``SPANFORGE_SYSLOG_FACILITY`` (default 16 = local0).
    """

    def __init__(
        self,
        *,
        host: str = "",
        port: int = 0,
        transport: str = "",
        format: str = "",
        app_name: str = "",
        facility: int = -1,
    ) -> None:
        self._host: str = host or os.environ.get("SPANFORGE_SYSLOG_HOST", "")
        self._port: int = port or int(os.environ.get("SPANFORGE_SYSLOG_PORT", _DEFAULT_PORT))
        self._transport: str = (
            transport or os.environ.get("SPANFORGE_SYSLOG_TRANSPORT", _DEFAULT_TRANSPORT)
        ).lower()
        self._format: str = (
            format or os.environ.get("SPANFORGE_SYSLOG_FORMAT", _DEFAULT_FORMAT)
        ).lower()
        self._app_name: str = app_name or os.environ.get(
            "SPANFORGE_SYSLOG_APP_NAME", _DEFAULT_APP_NAME
        )
        _fac: int = (
            facility
            if facility >= 0
            else int(os.environ.get("SPANFORGE_SYSLOG_FACILITY", _DEFAULT_FACILITY))
        )
        self._facility: int = _fac
        self._lock: threading.Lock = threading.Lock()
        self._sent_count: int = 0
        self._error_count: int = 0

        if not self._host:
            raise ValueError(
                "Syslog host must be provided via host argument or "
                "SPANFORGE_SYSLOG_HOST environment variable"
            )
        if self._transport not in ("udp", "tcp"):
            raise ValueError(f"transport must be 'udp' or 'tcp', got {self._transport!r}")
        if self._format not in ("rfc5424", "cef"):
            raise ValueError(f"format must be 'rfc5424' or 'cef', got {self._format!r}")
        if not (0 <= self._facility <= 23):
            raise ValueError(f"facility must be in range 0–23, got {self._facility}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export(self, event: Event) -> None:
        """Encode *event* and send it to the syslog receiver."""
        message = self._format_cef(event) if self._format == "cef" else self._format_rfc5424(event)

        try:
            self._send(message)
            with self._lock:
                self._sent_count += 1
        except Exception as exc:
            with self._lock:
                self._error_count += 1
            _log.error("SyslogExporter: failed to send event — %s", exc)

    def close(self) -> None:
        """No persistent connection; this is a no-op for UDP mode."""

    @property
    def sent_count(self) -> int:
        """Total events successfully delivered."""
        return self._sent_count

    @property
    def error_count(self) -> int:
        """Total delivery failures."""
        return self._error_count

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    def __enter__(self) -> SyslogExporter:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Formatters
    # ------------------------------------------------------------------

    def _severity_from_event(self, event: Event) -> int:
        """Map event_type prefix to a syslog severity (0–7)."""
        prefix = event.event_type.split(".")[0].lower()
        return _SEVERITY_MAP.get(prefix, 6)  # default: informational

    def _priority(self, severity: int) -> int:
        """Compute syslog PRI value from facility and severity."""
        return self._facility * 8 + severity

    def _format_rfc5424(self, event: Event) -> str:
        """Format event as an RFC 5424 syslog message."""
        severity = self._severity_from_event(event)
        pri = self._priority(severity)
        timestamp = (
            datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        )
        hostname = socket.gethostname()
        proc_id = "-"
        msg_id = event.event_type.replace(" ", "_")
        structured_data = "-"

        payload_json = json.dumps(event.payload if hasattr(event, "payload") else {})
        msg = f"spanforge event_id={getattr(event, 'event_id', '-')} payload={payload_json}"

        return (
            f"<{pri}>1 {timestamp} {hostname} {self._app_name} "
            f"{proc_id} {msg_id} {structured_data} {msg}"
        )

    def _format_cef(self, event: Event) -> str:
        """Format event as a CEF (ArcSight Common Event Format) message."""
        severity = self._severity_from_event(event)
        pri = self._priority(severity)
        timestamp = (
            datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        )
        hostname = socket.gethostname()

        # CEF header
        event_type_escaped = _CEF_ESCAPE_RE.sub(r"\\\1", event.event_type)
        cef_header = (
            f"CEF:0|{_CEF_VENDOR}|{_CEF_PRODUCT}|{_CEF_VERSION}|"
            f"{event_type_escaped}|{event_type_escaped}|{severity}|"
        )

        # CEF extension key=value pairs
        extensions: dict[str, str] = {
            "rt": timestamp,
            "deviceExternalId": str(getattr(event, "event_id", "")),
            "app": self._app_name,
        }
        payload = event.payload if hasattr(event, "payload") else {}
        for k, v in payload.items():
            safe_k = re.sub(r"[^A-Za-z0-9_]", "_", str(k))
            safe_v = _CEF_ESCAPE_RE.sub(r"\\\1", str(v))
            extensions[safe_k] = safe_v

        ext_str = " ".join(f"{k}={v}" for k, v in extensions.items())
        syslog_prefix = f"<{pri}>1 {timestamp} {hostname} {self._app_name} - - - "
        return syslog_prefix + cef_header + ext_str

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _send(self, message: str) -> None:
        """Deliver *message* via UDP or TCP syslog.

        Raises:
            SyslogExporterError: If the message cannot be delivered.
        """
        data = (message + "\n").encode("utf-8", errors="replace")
        try:
            if self._transport == "udp":
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.sendto(data, (self._host, self._port))
            else:
                with socket.create_connection((self._host, self._port), timeout=5.0) as sock:
                    sock.sendall(data)
        except OSError as exc:
            raise SyslogExporterError(
                f"Syslog delivery failed to {self._host}:{self._port} ({self._transport}): {exc}"
            ) from exc

    def __repr__(self) -> str:
        return (
            f"SyslogExporter(host={self._host!r}, port={self._port}, "
            f"transport={self._transport!r}, format={self._format!r}, "
            f"sent={self._sent_count}, errors={self._error_count})"
        )
