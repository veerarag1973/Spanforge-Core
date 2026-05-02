"""Schema migration utilities for spanforge events.

Provides forward-only migration functions to convert events from older schema
versions to the current version.  Migrations are idempotent — migrating an
event that is already at the target version returns it unchanged.

Usage
-----
::

    from spanforge.migrate import v1_to_v2, migrate_file

    # Single event
    v2_event = v1_to_v2(v1_event)

    # Bulk file migration
    stats = migrate_file("audit.jsonl", output="audit_v2.jsonl")
    print(f"Migrated {stats.migrated} events")
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = [
    "MigrationRecord",
    "MigrationStats",
    "migrate_file",
    "migrate_from_langsmith",
    "v1_to_v2",
    "v2_migration_roadmap",
]


@dataclass(frozen=True)
class MigrationStats:
    """Result of a bulk migration operation.

    Attributes:
        total:              Total events processed.
        migrated:           Events that were upgraded to a new schema version.
        skipped:            Events already at the target version (not modified).
        errors:             Events that could not be parsed or migrated.
        warnings:           Non-fatal warnings encountered during migration.
        output_path:        Path where the migrated events were written.
        transformed_fields: Mapping of field names to the count of events
                            where that field was transformed.
    """

    total: int
    migrated: int
    skipped: int
    errors: int
    warnings: list[str] = field(default_factory=list)
    output_path: str = ""
    transformed_fields: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Migration roadmap data structures
# ---------------------------------------------------------------------------


class _SunsetPolicyEnum:
    """Minimal sunset-policy enum shim for migration records."""

    def __init__(self, value: str) -> None:
        self.value = value

    def __repr__(self) -> str:
        return f"SunsetPolicy({self.value!r})"


@dataclass(frozen=True)
class MigrationRecord:
    """One entry in the v1→v2 migration roadmap.

    Attributes:
        event_type:       Deprecated event type (v1 name).
        since:            Version when the deprecation was introduced.
        sunset:           Version when the type will be removed.
        sunset_policy:    Policy object with a ``.value`` attribute
                          (one of ``"hard"``, ``"soft"``, ``"extended"``).
        replacement:      Replacement event type in v2, or ``None`` if removed.
        migration_notes:  Human-readable migration guidance.
        field_renames:    Mapping of ``{old_field: new_field}`` for structural changes.
        effort:           Estimated migration effort: ``"low"``, ``"medium"``, or ``"high"``.
    """

    event_type: str
    since: str
    sunset: str
    sunset_policy: Any
    replacement: str | None
    migration_notes: str
    field_renames: dict[str, str] = field(default_factory=dict)
    effort: str = "medium"


# ---------------------------------------------------------------------------
# Built-in v1→v2 migration catalog
# ---------------------------------------------------------------------------

_MIGRATION_CATALOG: list[dict[str, Any]] = [
    {
        "event_type": "llm.legacy.trace",
        "since": "1.0",
        "sunset": "2.0",
        "sunset_policy": "hard",
        "replacement": "llm.trace.span.completed",
        "migration_notes": (
            "Replace 'llm.legacy.trace' with 'llm.trace.span.completed'. "
            "The new type requires a 'span_id' field in the payload and uses "
            "structured 'input'/'output' keys instead of 'prompt'/'completion'."
        ),
        "field_renames": {"prompt": "input", "completion": "output"},
        "effort": "medium",
    },
    {
        "event_type": "llm.v0.request",
        "since": "1.0",
        "sunset": "2.0",
        "sunset_policy": "hard",
        "replacement": "llm.request.created",
        "migration_notes": (
            "Use 'llm.request.created' with the new v2 payload schema. "
            "The 'model' field is renamed to 'model_id'. "
            "Add required fields: 'schema_version', 'org_id', 'team_id'."
        ),
        "field_renames": {"model": "model_id"},
        "effort": "low",
    },
    {
        "event_type": "llm.v0.response",
        "since": "1.0",
        "sunset": "2.0",
        "sunset_policy": "hard",
        "replacement": "llm.response.completed",
        "migration_notes": (
            "Use 'llm.response.completed' with the v2 payload schema. "
            "Move token counts to the 'usage' sub-dict: "
            "{'prompt_tokens': N, 'completion_tokens': N, 'total_tokens': N}."
        ),
        "field_renames": {"prompt_tokens": "usage.prompt_tokens", "completion_tokens": "usage.completion_tokens"},
        "effort": "medium",
    },
    {
        "event_type": "hallucination.check.v0",
        "since": "1.1",
        "sunset": "2.0",
        "sunset_policy": "soft",
        "replacement": "hallucination.check.completed",
        "migration_notes": (
            "Replace 'hallucination.check.v0' with 'hallucination.check.completed'. "
            "The 'score' field is now 'hallucination_score' (float 0–1). "
            "The 'is_hallucinated' boolean field is now 'verdict' (string: pass/fail/review)."
        ),
        "field_renames": {"score": "hallucination_score", "is_hallucinated": "verdict"},
        "effort": "medium",
    },
    {
        "event_type": "audit.v0.log",
        "since": "1.1",
        "sunset": "2.0",
        "sunset_policy": "hard",
        "replacement": "audit.log.written",
        "migration_notes": (
            "Replace 'audit.v0.log' with 'audit.log.written'. "
            "The 'user' field is renamed to 'actor_id' and must be a ULID or UUIDv4. "
            "Add the required 'action' field describing what was performed."
        ),
        "field_renames": {"user": "actor_id", "action_type": "action"},
        "effort": "high",
    },
    {
        "event_type": "rag.v0.query",
        "since": "1.2",
        "sunset": "2.0",
        "sunset_policy": "soft",
        "replacement": "rag.retrieval.completed",
        "migration_notes": (
            "Replace 'rag.v0.query' with 'rag.retrieval.completed'. "
            "Rename 'query' to 'query_text' and 'results' to 'retrieved_chunks'. "
            "Add 'retriever_id' identifying the retrieval pipeline."
        ),
        "field_renames": {"query": "query_text", "results": "retrieved_chunks"},
        "effort": "medium",
    },
]


def v2_migration_roadmap() -> list[MigrationRecord]:
    """Return the v1→v2 migration roadmap.

    First checks the global deprecation registry for additional notices, then
    merges them with the built-in catalog.  Registry entries take precedence
    when their ``event_type`` already appears in the catalog.

    Returns:
        Sorted list of :class:`MigrationRecord` objects.
    """
    # Start with the built-in catalog
    records: dict[str, MigrationRecord] = {}
    for entry in _MIGRATION_CATALOG:
        sp = _SunsetPolicyEnum(entry.get("sunset_policy", "hard"))
        fr: dict[str, str] = dict(entry.get("field_renames", {}))
        effort: str = str(entry.get("effort", "medium"))
        rec = MigrationRecord(
            event_type=entry["event_type"],
            since=str(entry["since"]),
            sunset=str(entry["sunset"]),
            sunset_policy=sp,
            replacement=entry.get("replacement"),
            migration_notes=str(entry.get("migration_notes", "")),
            field_renames=fr,
            effort=effort,
        )
        records[rec.event_type] = rec

    # Overlay with live deprecation registry
    try:
        from spanforge.deprecations import get_registry as _get_dep_registry

        for notice in _get_dep_registry().list_all():
            if notice.event_type not in records:
                # Estimate effort from notes length and replacement presence
                if not notice.replacement:
                    effort = "high"
                elif notice.notes and len(notice.notes) > 120:
                    effort = "medium"
                else:
                    effort = "low"
                records[notice.event_type] = MigrationRecord(
                    event_type=notice.event_type,
                    since=notice.since,
                    sunset=notice.sunset or "TBD",
                    sunset_policy=_SunsetPolicyEnum("soft"),
                    replacement=notice.replacement,
                    migration_notes=notice.notes or "",
                    field_renames={},
                    effort=effort,
                )
    except Exception:
        pass

    return sorted(records.values(), key=lambda r: (r.since, r.event_type))


def _rehash_md5_to_sha256(checksum: str | None, payload: dict[str, Any]) -> str | None:
    """If *checksum* starts with ``md5:``, recompute as ``sha256:``."""
    if checksum and checksum.startswith("md5:"):
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return f"sha256:{hashlib.sha256(canonical).hexdigest()}"
    return checksum


def _coerce_tag_values(tags: Any) -> dict[str, str]:
    """Ensure all tag values are strings."""
    from spanforge.event import Tags as _Tags

    if isinstance(tags, _Tags):
        return tags.to_dict()
    if not isinstance(tags, dict):
        return {}
    return {str(k): str(v) for k, v in tags.items()}


def v1_to_v2(event: Any) -> Any:
    """Migrate a single event from schema version 1.0 to 2.0.

    Changes applied:
    * ``schema_version`` is set to ``"2.0"``.
    * Missing ``org_id`` is set to ``None`` (was not required in v1).
    * Missing ``team_id`` is set to ``None``.
    * Payload key ``model`` is normalised to ``model_id`` if present.
    * ``tags`` is initialised to an empty dict if missing; all values
      are coerced to strings.
    * ``checksum`` is re-hashed from md5 to sha256 if applicable.

    If the event is already at version ``"2.0"`` or later, it is returned
    unchanged (idempotent).

    Args:
        event: Either an :class:`~spanforge.event.Event` instance or a plain
               ``dict`` (as loaded from JSONL).

    Returns:
        The migrated event (same type as input).
    """
    from spanforge.event import Event, Tags

    if isinstance(event, Event):
        if event.schema_version == "2.0":
            return event
        payload = dict(event.payload)
        # Normalise model → model_id
        if "model" in payload and "model_id" not in payload:
            payload["model_id"] = payload.pop("model")
        # Re-hash md5 checksum
        checksum = _rehash_md5_to_sha256(event.checksum, payload)
        # Coerce tag values to strings
        raw_tags = _coerce_tag_values(event.tags) if event.tags else {}
        tags = Tags(**raw_tags)
        return Event(
            schema_version="2.0",
            event_id=event.event_id,
            event_type=event.event_type,
            timestamp=event.timestamp,
            source=event.source,
            payload=payload,
            trace_id=event.trace_id,
            span_id=event.span_id,
            parent_span_id=event.parent_span_id,
            org_id=event.org_id,
            team_id=event.team_id,
            actor_id=event.actor_id,
            session_id=event.session_id,
            tags=tags,
            checksum=checksum,
            signature=event.signature,
            prev_id=event.prev_id,
        )

    # Dict-based migration  (e.g. raw JSONL parsing)
    if isinstance(event, dict):
        if event.get("schema_version") == "2.0":
            return event
        d = dict(event)
        d["schema_version"] = "2.0"
        d.setdefault("org_id", None)
        d.setdefault("team_id", None)
        # Coerce tag values
        dict_tags: Any = d.get("tags")
        if isinstance(dict_tags, dict):
            d["tags"] = {str(k): str(v) for k, v in dict_tags.items()}
        else:
            d["tags"] = {}
        payload = d.get("payload", {})
        if isinstance(payload, dict) and "model" in payload and "model_id" not in payload:
            payload["model_id"] = payload.pop("model")
        # Re-hash md5 checksum
        if d.get("checksum", "").startswith("md5:") and isinstance(payload, dict):
            canonical = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            ).encode("utf-8")
            d["checksum"] = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
        return d

    raise TypeError(f"Cannot migrate object of type {type(event).__name__}")


def migrate_file(
    input_path: str | Path,
    *,
    output: str | Path | None = None,
    org_secret: str | None = None,
    target_version: str = "2.0",
    dry_run: bool = False,
) -> MigrationStats:
    """Migrate all events in a JSONL file from v1 to v2.

    Reads line-by-line, applies :func:`v1_to_v2` to each JSON object, and
    writes the result to *output* (defaults to ``<input>_v2.jsonl``).

    Args:
        input_path:     Path to the source JSONL file.
        output:         Output file path (default: ``<stem>_v2.jsonl``).
        org_secret:     When provided, re-signs the migrated chain using HMAC.
        target_version: Target schema version (default ``"2.0"``).
        dry_run:        When ``True``, report stats without writing output.

    Returns:
        A :class:`MigrationStats` summarising the operation.
    """
    src = Path(input_path)
    dst = src.with_name(f"{src.stem}_v2{src.suffix}") if output is None else Path(output)

    total = 0
    migrated = 0
    skipped = 0
    errors = 0
    warnings: list[str] = []
    transformed_fields: dict[str, int] = {}

    migrated_dicts: list[str] = []

    with src.open("r", encoding="utf-8") as fin:
        for line_no, line in enumerate(fin, 1):
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                errors += 1
                migrated_dicts.append(line + "\n")
                continue

            # Source format validation
            if not isinstance(data, dict):
                errors += 1
                warnings.append(f"line {line_no}: not a JSON object")
                migrated_dicts.append(line + "\n")
                continue

            if data.get("schema_version") == target_version:
                skipped += 1
                migrated_dicts.append(line + "\n")
                continue

            try:
                # Track which fields get transformed
                payload = data.get("payload", {})
                if isinstance(payload, dict) and "model" in payload and "model_id" not in payload:
                    transformed_fields["payload.model→model_id"] = (
                        transformed_fields.get("payload.model→model_id", 0) + 1
                    )
                if data.get("checksum", "").startswith("md5:"):
                    transformed_fields["checksum.md5→sha256"] = (
                        transformed_fields.get("checksum.md5→sha256", 0) + 1
                    )
                raw_tags = data.get("tags", {})
                if isinstance(raw_tags, dict) and any(
                    not isinstance(v, str) for v in raw_tags.values()
                ):
                    transformed_fields["tags.value_coercion"] = (
                        transformed_fields.get("tags.value_coercion", 0) + 1
                    )

                migrated_data = v1_to_v2(data)
                migrated_dicts.append(
                    json.dumps(migrated_data, separators=(",", ":"), ensure_ascii=False) + "\n"
                )
                migrated += 1
            except Exception:  # NOSONAR
                errors += 1
                migrated_dicts.append(line + "\n")

    # Re-sign if org_secret provided
    if org_secret and not dry_run:
        from spanforge.event import Event
        from spanforge.signing import sign as _sign

        signed_lines: list[str] = []
        prev_event = None
        for raw_line in migrated_dicts:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                data = json.loads(raw_line)
                evt = Event.from_dict(data)
                signed_evt = _sign(evt, org_secret, prev_event=prev_event)
                prev_event = signed_evt
                signed_lines.append(signed_evt.to_json() + "\n")
            except Exception:
                signed_lines.append(raw_line + "\n")
        migrated_dicts = signed_lines

    if not dry_run:
        with dst.open("w", encoding="utf-8") as fout:
            for out_line in migrated_dicts:
                fout.write(out_line)

    return MigrationStats(
        total=total,
        migrated=migrated,
        skipped=skipped,
        errors=errors,
        warnings=warnings,
        output_path=str(dst),
        transformed_fields=transformed_fields,
    )


# ---------------------------------------------------------------------------
# LangSmith migration (F-27)
# ---------------------------------------------------------------------------

_LANGSMITH_RUN_TYPE_MAP: dict[str, str] = {
    "llm": "llm.trace.span.completed",
    "tool": "llm.tool.call.completed",
    "retriever": "llm.tool.call.completed",
    "chain": "llm.chain.completed",
}


def migrate_from_langsmith(
    runs: list[dict[str, Any]],
    *,
    source: str = "langsmith-import",
) -> list[dict[str, Any]]:
    """Convert a list of LangSmith run dicts to SpanForge v2 event dicts.

    Supports both the *JSON array* and *JSONL* line shapes that LangSmith
    produces when you export a project.  The function performs the run-type →
    ``event_type`` mapping documented in ADR-006 and returns a ready-to-use
    list of SpanForge v2 event dicts suitable for writing as JSONL or passing
    directly to :class:`~spanforge.sdk.audit.SFAuditClient`.

    Args:
        runs:   List of LangSmith run dicts (as loaded from a ``.json`` or
                ``.jsonl`` export).
        source: ``source`` label stamped on every output event.  Defaults to
                ``"langsmith-import"``.

    Returns:
        A list of SpanForge v2 event dicts (one per input run).

    Example::

        import json
        from spanforge.migrate import migrate_from_langsmith

        with open("project_export.json") as fh:
            runs = json.load(fh)

        events = migrate_from_langsmith(runs, source="my-project")
    """
    import time as _time

    from spanforge.ulid import generate as _ulid_generate

    events: list[dict[str, Any]] = []
    for run in runs:
        run_type = run.get("run_type", "chain")
        run_name = run.get("name", "unknown")
        run_id = run.get("id", _ulid_generate())

        event_type = _LANGSMITH_RUN_TYPE_MAP.get(run_type, "llm.trace.span.completed")

        payload: dict[str, Any] = {
            "span_name": run_name,
            "run_type": run_type,
            "status": run.get("status", "ok"),
        }

        # Token usage
        total_tok = run.get("total_tokens") or 0
        prompt_tok = run.get("prompt_tokens") or 0
        completion_tok = run.get("completion_tokens") or 0
        if total_tok or prompt_tok or completion_tok:
            payload["token_usage"] = {
                "input_tokens": prompt_tok,
                "output_tokens": completion_tok,
                "total_tokens": total_tok or (prompt_tok + completion_tok),
            }

        # Timing
        if run.get("start_time"):
            payload["start_time"] = run["start_time"]
        if run.get("end_time"):
            payload["end_time"] = run["end_time"]

        # Inputs / outputs (key names only — no raw content stored)
        if run.get("inputs"):
            payload["input_keys"] = (
                list(run["inputs"].keys()) if isinstance(run["inputs"], dict) else ["input"]
            )
        if run.get("outputs"):
            payload["output_keys"] = (
                list(run["outputs"].keys()) if isinstance(run["outputs"], dict) else ["output"]
            )

        # Error info (truncated to 500 chars for safety)
        if run.get("error"):
            payload["error"] = str(run["error"])[:500]

        trace_id = run.get("trace_id") or run.get("session_id") or ""
        parent_id = run.get("parent_run_id") or ""

        event: dict[str, Any] = {
            "event_id": _ulid_generate(),
            "event_type": event_type,
            "source": source,
            "schema_version": "2.0",
            "timestamp": run.get("start_time") or _time.time(),
            "payload": payload,
            "tags": {
                "langsmith_run_id": str(run_id),
                "langsmith_trace_id": str(trace_id) if trace_id else "",
                "langsmith_parent_id": str(parent_id) if parent_id else "",
            },
        }
        events.append(event)

    return events
