"""spanforge.export.siem_syslog - Syslog / CEF exporter.

Forwards spanforge events to a remote syslog receiver (RFC 5424) optionally
encoded as ArcSight Common Event Format (CEF).
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

from spanforge.export.siem_schema import event_to_siem_record, severity_from_event

if TYPE_CHECKING:
    from spanforge.event import Event

__all__ = ["SyslogExporter", "SyslogExporterError"]

_log = logging.getLogger("spanforge.export.siem_syslog")

_DEFAULT_PORT = 514
_DEFAULT_TRANSPORT = "udp"
_DEFAULT_FORMAT = "rfc5424"
_DEFAULT_APP_NAME = "spanforge"
_DEFAULT_FACILITY = 16  # local0
_SEVERITY_MAP: dict[str, int] = {
    "alert": 1,
    "error": 3,
    "warn": 4,
    "warning": 4,
    "info": 6,
    "debug": 7,
    "trace": 7,
}

_CEF_VENDOR = "SpanForge"
_CEF_PRODUCT = "SpanForge"
_CEF_VERSION = "1.0"
_CEF_ESCAPE_RE = re.compile(r"([\\|=])")


class SyslogExporterError(RuntimeError):
    """Raised when a syslog delivery attempt fails permanently."""


class SyslogExporter:
    """Export spanforge events to a remote syslog receiver."""

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
        self._facility: int = (
            facility
            if facility >= 0
            else int(os.environ.get("SPANFORGE_SYSLOG_FACILITY", _DEFAULT_FACILITY))
        )
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
            raise ValueError(f"facility must be in range 0-23, got {self._facility}")

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
            _log.error("SyslogExporter: failed to send event - %s", exc)

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

    def __enter__(self) -> SyslogExporter:
        return self

    def __exit__(self, *_: Any) -> None:
        self.close()

    def _severity_from_event(self, event: Event) -> int:
        """Map event_type prefix to a syslog severity (0-7)."""
        return severity_from_event(event)

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
        record_json = json.dumps(event_to_siem_record(event), sort_keys=True)
        msg = f"spanforge event_id={event.event_id} payload={record_json}"
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
        event_type_escaped = _CEF_ESCAPE_RE.sub(r"\\\1", event.event_type)
        cef_header = (
            f"CEF:0|{_CEF_VENDOR}|{_CEF_PRODUCT}|{_CEF_VERSION}|"
            f"{event_type_escaped}|{event_type_escaped}|{severity}|"
        )
        extensions: dict[str, str] = {
            "rt": timestamp,
            "deviceExternalId": event.event_id,
            "app": self._app_name,
            "event_type": event.event_type,
        }
        siem_record = event_to_siem_record(event)
        for key, value in siem_record.items():
            if key == "payload":
                continue
            safe_key = re.sub(r"[^A-Za-z0-9_]", "_", str(key))
            safe_value = (
                json.dumps(value, sort_keys=True) if isinstance(value, (dict, list)) else str(value)
            )
            extensions[safe_key] = _CEF_ESCAPE_RE.sub(r"\\\1", safe_value)
        payload = getattr(event, "payload", {}) or {}
        if isinstance(payload, dict):
            for key, value in payload.items():
                safe_key = re.sub(r"[^A-Za-z0-9_]", "_", str(key))
                safe_value = _CEF_ESCAPE_RE.sub(r"\\\1", str(value))
                extensions[safe_key] = safe_value
        ext_str = " ".join(f"{key}={value}" for key, value in extensions.items())
        syslog_prefix = f"<{pri}>1 {timestamp} {hostname} {self._app_name} - - - "
        return syslog_prefix + cef_header + ext_str

    def _send(self, message: str) -> None:
        """Deliver *message* via UDP or TCP syslog."""
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
