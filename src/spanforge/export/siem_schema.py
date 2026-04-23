"""SIEM-friendly schema normalization for SpanForge events.

Provides one canonical event mapping that downstream SIEM exporters can reuse
so Splunk, syslog/CEF, and JSON-based audit sinks see the same core fields.
"""

from __future__ import annotations

import json
from typing import Any

from spanforge.event import Event

__all__ = ["event_to_siem_record", "severity_from_event"]

_SEVERITY_MAP: dict[str, int] = {
    "alert": 1,
    "error": 3,
    "warn": 4,
    "warning": 4,
    "info": 6,
    "debug": 7,
    "trace": 7,
}


def severity_from_event(event: Event) -> int:
    """Map the event_type prefix to a syslog-style severity."""
    prefix = event.event_type.split(".")[0].lower()
    return _SEVERITY_MAP.get(prefix, 6)


def event_to_siem_record(event: Event) -> dict[str, Any]:
    """Return a normalized SIEM record for one SpanForge event."""
    payload = _safe_payload(getattr(event, "payload", {}))
    tags = _safe_tags(getattr(event, "tags", None))
    record = {
        "event_id": getattr(event, "event_id", None),
        "event_type": getattr(event, "event_type", None),
        "schema_version": getattr(event, "schema_version", None),
        "timestamp": getattr(event, "timestamp", None),
        "source": getattr(event, "source", None),
        "trace_id": getattr(event, "trace_id", None),
        "span_id": getattr(event, "span_id", None),
        "parent_span_id": getattr(event, "parent_span_id", None),
        "org_id": getattr(event, "org_id", None),
        "team_id": getattr(event, "team_id", None),
        "actor_id": getattr(event, "actor_id", None),
        "session_id": getattr(event, "session_id", None),
        "siem": {
            "schema": "spanforge.event.v1",
            "category": _category_for_event_type(str(getattr(event, "event_type", ""))),
            "severity": severity_from_event(event),
        },
        "payload": payload,
        "tags": tags,
    }
    normalized = json.loads(json.dumps(record, sort_keys=True, default=str))
    return {key: value for key, value in normalized.items() if value not in (None, {})}


def _category_for_event_type(event_type: str) -> str:
    if ".policy." in event_type:
        return "policy"
    if ".audit." in event_type:
        return "audit"
    if ".scope." in event_type:
        return "scope"
    if ".rbac." in event_type:
        return "rbac"
    if ".rag." in event_type or ".ground" in event_type:
        return "grounding"
    if ".lineage." in event_type:
        return "lineage"
    if ".tool" in event_type:
        return "tool"
    if ".trace." in event_type or event_type.startswith("trace."):
        return "trace"
    return "application"


def _safe_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    try:
        return dict(payload)
    except Exception:
        return {"value": payload}


def _safe_tags(tags: Any) -> dict[str, Any]:
    if tags is None:
        return {}
    try:
        value = tags.to_dict() if hasattr(tags, "to_dict") else dict(tags)
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}
