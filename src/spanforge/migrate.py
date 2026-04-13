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
    "MigrationStats",
    "migrate_file",
    "v1_to_v2",
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
    if not isinstance(tags, dict):
        return {}
    return {str(k): str(v) for k, v in tags.items()}


def v1_to_v2(event: Any) -> Any:  # noqa: ANN401
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
    from spanforge.event import Event  # noqa: PLC0415

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
        tags = _coerce_tag_values(event.tags) if event.tags else {}
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
        raw_tags = d.get("tags")
        if isinstance(raw_tags, dict):
            d["tags"] = {str(k): str(v) for k, v in raw_tags.items()}
        else:
            d["tags"] = {}
        payload = d.get("payload", {})
        if isinstance(payload, dict):
            if "model" in payload and "model_id" not in payload:
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
    if output is None:
        dst = src.with_name(f"{src.stem}_v2{src.suffix}")
    else:
        dst = Path(output)

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
                    transformed_fields["payload.model→model_id"] = transformed_fields.get("payload.model→model_id", 0) + 1
                if data.get("checksum", "").startswith("md5:"):
                    transformed_fields["checksum.md5→sha256"] = transformed_fields.get("checksum.md5→sha256", 0) + 1
                raw_tags = data.get("tags", {})
                if isinstance(raw_tags, dict) and any(not isinstance(v, str) for v in raw_tags.values()):
                    transformed_fields["tags.value_coercion"] = transformed_fields.get("tags.value_coercion", 0) + 1

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
        from spanforge.event import Event  # noqa: PLC0415
        from spanforge.signing import sign as _sign  # noqa: PLC0415

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
            except Exception:  # noqa: BLE001
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
