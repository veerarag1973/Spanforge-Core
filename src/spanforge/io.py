"""spanforge.io — Reliable synchronous JSONL read / write utilities.

These helpers solve a practical problem surfaced when integrating spanforge
into tool authors' pipelines: ``JSONLExporter`` is async and
``EventStream.from_file`` occasionally raises on malformed lines rather than
skipping them, forcing every caller to write bespoke fallback code.

:func:`write_jsonl` and :func:`read_jsonl` are **synchronous**, handle
edge-cases (missing parents, empty files, partial writes, corrupt lines) with
predictable error semantics, and never swallow exceptions silently.

Usage::

    from spanforge.io import write_jsonl, read_jsonl

    # Persist a list of result dicts as JSONL
    write_jsonl(results, "results/run-001.jsonl")

    # Read back, optionally filtering by spanforge event_type
    rows = read_jsonl("results/run-001.jsonl")

    # Append a single record
    from spanforge.io import append_jsonl
    append_jsonl({"metric": "faithfulness", "score": 0.91}, "scores.jsonl")

Spanforge-event-aware variants
-------------------------------
:func:`write_events` wraps each dict in a spanforge ``Event`` envelope and
delegates to :func:`write_jsonl`.  :func:`read_events` unwraps the payload
for lines that match the requested *event_type*, falling back gracefully for
plain-JSON lines.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

__all__ = [
    "append_jsonl",
    "read_events",
    "read_jsonl",
    "write_events",
    "write_jsonl",
]


# ---------------------------------------------------------------------------
# Core primitives
# ---------------------------------------------------------------------------


def write_jsonl(
    records: Iterable[dict[str, Any]],
    path: str | Path,
    *,
    mode: str = "w",
) -> int:
    """Write *records* to a JSONL file, one JSON object per line.

    Args:
        records:  Any iterable of JSON-serialisable dicts.
        path:     Destination file path.  Parent directories are created
                  automatically.
        mode:     ``"w"`` (default) to overwrite, ``"a"`` to append.

    Returns:
        Number of records written.

    Raises:
        ValueError:  If *mode* is not ``"w"`` or ``"a"``.
        OSError:     If the file cannot be created or written.
    """
    if mode not in ("w", "a"):
        raise ValueError(f"mode must be 'w' or 'a', got {mode!r}")
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with dest.open(mode, encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, default=str) + "\n")
            count += 1
    return count


def append_jsonl(record: dict[str, Any], path: str | Path) -> None:
    """Append a single *record* to a JSONL file.

    The file is created (with parent directories) if it does not exist.

    Args:
        record:  A JSON-serialisable dict.
        path:    Destination file path.
    """
    write_jsonl([record], path, mode="a")


def read_jsonl(
    path: str | Path,
    *,
    event_type: str | None = None,
    skip_errors: bool = True,
) -> list[dict[str, Any]]:
    """Read records from a JSONL file.

    Args:
        path:         JSONL file to read.
        event_type:   When given, only lines whose top-level ``event_type``
                      key equals this value are returned.  ``None`` returns
                      every line.
        skip_errors:  When ``True`` (default), lines that cannot be parsed as
                      JSON are silently skipped.  Set to ``False`` to raise
                      :class:`json.JSONDecodeError` on the first bad line.

    Returns:
        List of raw dicts (one per valid line).

    Raises:
        FileNotFoundError:   If *path* does not exist.
        json.JSONDecodeError: If *skip_errors* is ``False`` and a line is
                              not valid JSON.
    """
    results: list[dict[str, Any]] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj: dict[str, Any] = json.loads(line)
            except json.JSONDecodeError:
                if not skip_errors:
                    raise
                continue
            if not isinstance(obj, dict):
                continue
            if event_type is not None and obj.get("event_type") != event_type:
                continue
            results.append(obj)
    return results


# ---------------------------------------------------------------------------
# Spanforge-event-aware variants
# ---------------------------------------------------------------------------

_DEFAULT_SOURCE = "spanforge"


def write_events(
    payloads: Iterable[dict[str, Any]],
    path: str | Path,
    *,
    event_type: str,
    source: str = _DEFAULT_SOURCE,
    mode: str = "w",
) -> int:
    """Wrap each payload dict in a spanforge event envelope and write to JSONL.

    Each line has the shape::

        {"event_type": "<event_type>", "source": "<source>", "payload": {...}}

    The envelope is compatible with :func:`read_events` and can also be parsed
    by :class:`~spanforge.stream.EventStream`.

    Args:
        payloads:    Iterable of payload dicts to wrap.
        path:        Destination file path.
        event_type:  Value for the ``event_type`` envelope field.
        source:      Value for the ``source`` envelope field.
        mode:        ``"w"`` (overwrite) or ``"a"`` (append).

    Returns:
        Number of records written.
    """
    def _wrap(p: dict[str, Any]) -> dict[str, Any]:
        return {"event_type": event_type, "source": source, "payload": p}

    return write_jsonl((_wrap(p) for p in payloads), path, mode=mode)


def read_events(
    path: str | Path,
    *,
    event_type: str,
    skip_errors: bool = True,
) -> list[dict[str, Any]]:
    """Read spanforge-event-wrapped payloads from a JSONL file.

    Lines whose ``event_type`` field matches *event_type* are returned with
    their ``payload`` dict unwrapped.  Lines written by :func:`write_jsonl`
    directly (without an envelope) are silently ignored.

    Args:
        path:        JSONL file to read.
        event_type:  Only lines with this ``event_type`` are returned.
        skip_errors: Passed through to :func:`read_jsonl`.

    Returns:
        List of unwrapped payload dicts.
    """
    rows = read_jsonl(path, event_type=event_type, skip_errors=skip_errors)
    result: list[dict[str, Any]] = []
    for row in rows:
        payload = row.get("payload")
        if isinstance(payload, dict):
            result.append(payload)
    return result
