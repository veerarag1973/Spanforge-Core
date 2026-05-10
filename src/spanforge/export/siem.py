r"""spanforge.export.siem — CEF / LEEF string formatter.

Provides :class:`SIEMExporter`, a lightweight, network-free formatter that
converts SpanForge events to ArcSight Common Event Format (CEF) or IBM
QRadar Log Event Extended Format (LEEF) strings suitable for forwarding to
any SIEM via syslog, file ingestion, or the ``spanforge export siem`` CLI.

Formats
-------
``cef``
    ArcSight Common Event Format v0::

        CEF:0|SpanForge|SDK|<version>|<event_type>|<name>|<severity>|<extensions>

``leef``
    IBM LEEF 2.0::

        LEEF:2.0|SpanForge|SDK|<version>|<event_type>\\t<tab-separated KV pairs>

Usage::

    from spanforge.export.siem import SIEMExporter
    from spanforge.event import Event

    exporter = SIEMExporter(format="cef")
    line = exporter.export(event)
    print(line)

    for line in exporter.export_batch(events):
        print(line)
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

from spanforge.export.siem_schema import event_to_siem_record, severity_from_event

if TYPE_CHECKING:
    from spanforge.event import Event

__all__ = ["SIEMExporter"]

_VENDOR = "SpanForge"
_PRODUCT = "SDK"
_CEF_ESCAPE_RE = re.compile(r"([\\|=])")
_LEEF_ESCAPE_RE = re.compile(r"[\t\n\r]")


def _pkg_version() -> str:
    """Return the installed spanforge version string."""
    try:
        from importlib.metadata import version

        return version("spanforge")
    except Exception:  # pragma: no cover
        return "0.0.0"


def _cef_escape(value: str) -> str:
    """Escape special characters for CEF extension values."""
    return _CEF_ESCAPE_RE.sub(r"\\\1", value)


def _leef_escape(value: str) -> str:
    """Escape tab / newline characters for LEEF values."""
    return _LEEF_ESCAPE_RE.sub(" ", value)


def _to_str(value: object) -> str:
    """Serialize a value to a plain string for SIEM output."""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True)
    return str(value)


class SIEMExporter:
    """Convert SpanForge events to CEF or LEEF strings.

    Args:
        format: Output format — ``"cef"`` (default) or ``"leef"``.
        version: Override the SDK version embedded in each record.  When
                 omitted the installed ``spanforge`` package version is used.

    Attributes:
        format: The active output format.
    """

    def __init__(
        self,
        *,
        format: Literal["cef", "leef"] = "cef",
        version: str = "",
    ) -> None:
        if format not in ("cef", "leef"):
            raise ValueError(f"format must be 'cef' or 'leef', got {format!r}")
        self.format: Literal["cef", "leef"] = format
        self._version = version or _pkg_version()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def export(self, event: Event) -> str:
        """Format *event* as a single SIEM string.

        Args:
            event: The SpanForge event to format.

        Returns:
            A CEF or LEEF formatted string (no trailing newline).
        """
        if self.format == "leef":
            return self._format_leef(event)
        return self._format_cef(event)

    def export_batch(self, events: Iterable[Event]) -> Iterator[str]:
        """Yield one SIEM-formatted string per event.

        Args:
            events: Iterable of SpanForge events.

        Yields:
            Formatted strings in the configured format.
        """
        for event in events:
            yield self.export(event)

    # ------------------------------------------------------------------
    # Format internals
    # ------------------------------------------------------------------

    def _format_cef(self, event: Event) -> str:
        """Render *event* as a CEF v0 string."""
        severity = severity_from_event(event)
        event_type = str(getattr(event, "event_type", ""))
        event_type_escaped = _cef_escape(event_type)

        header = (
            f"CEF:0|{_VENDOR}|{_PRODUCT}|{self._version}"
            f"|{event_type_escaped}|{event_type_escaped}|{severity}|"
        )

        extensions = self._build_extensions(event)
        ext_str = " ".join(f"{k}={v}" for k, v in extensions.items())
        return header + ext_str

    def _format_leef(self, event: Event) -> str:
        """Render *event* as a LEEF 2.0 string."""
        event_type = str(getattr(event, "event_type", ""))

        header = (
            f"LEEF:2.0|{_VENDOR}|{_PRODUCT}|{self._version}|{event_type}"
        )

        extensions = self._build_extensions(event)
        ext_str = "\t".join(f"{k}={v}" for k, v in extensions.items())
        return header + "\t" + ext_str

    def _escape(self, value: str) -> str:
        """Escape *value* for the active format."""
        if self.format == "leef":
            return _leef_escape(value)
        return _cef_escape(value)

    def _build_extensions(self, event: Event) -> dict[str, str]:
        """Build an ordered dict of extension key/value pairs for *event*."""
        record = event_to_siem_record(event)
        extensions: dict[str, str] = {}

        # Standard envelope fields first
        for field in (
            "event_id",
            "event_type",
            "schema_version",
            "timestamp",
            "source",
            "trace_id",
            "span_id",
            "parent_span_id",
            "org_id",
            "team_id",
            "actor_id",
            "session_id",
        ):
            value = record.get(field)
            if value is not None:
                safe_key = re.sub(r"[^A-Za-z0-9_]", "_", field)
                extensions[safe_key] = self._escape(_to_str(value))

        # SIEM meta fields
        siem_meta = record.get("siem", {})
        if isinstance(siem_meta, dict):
            for k, v in siem_meta.items():
                safe_key = "siem_" + re.sub(r"[^A-Za-z0-9_]", "_", str(k))
                extensions[safe_key] = self._escape(_to_str(v))

        # Flatten payload fields (one level)
        payload = getattr(event, "payload", None)
        if payload is not None:
            try:
                payload_dict = dict(payload)
            except (TypeError, ValueError):
                payload_dict = {}
            for k, v in payload_dict.items():
                safe_key = "payload_" + re.sub(r"[^A-Za-z0-9_]", "_", str(k))
                extensions[safe_key] = self._escape(_to_str(v))

        return extensions
