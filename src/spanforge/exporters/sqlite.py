"""spanforge.exporters.sqlite — Synchronous SQLite exporter.

Persists events to a local SQLite database.  Zero external dependencies
(stdlib ``sqlite3`` only).  Suitable for development, staging, and solo
deployments where durable single-file storage is needed without standing up
Redis, Kafka, or a cloud collector.

Usage::

    from spanforge import configure
    configure(exporter="sqlite", endpoint="./spanforge.db")

    # Events are now durable across process restarts.
    # Query them with any SQLite client:
    #   sqlite3 spanforge.db "SELECT event_type, source, ts FROM events ORDER BY ts DESC LIMIT 10;"

You can also instantiate directly::

    from spanforge.exporters.sqlite import SyncSQLiteExporter
    exporter = SyncSQLiteExporter("./spanforge.db")
    exporter.export(my_event)
    exporter.close()

Schema
------
Table ``events``:

* ``id``         INTEGER PRIMARY KEY AUTOINCREMENT
* ``event_id``   TEXT NOT NULL — ULID from :attr:`~spanforge.event.Event.event_id`
* ``event_type`` TEXT NOT NULL — e.g. ``"trace.span.completed"``
* ``source``     TEXT NOT NULL
* ``org_id``     TEXT
* ``trace_id``   TEXT
* ``span_id``    TEXT
* ``ts``         TEXT NOT NULL — ISO-8601 UTC timestamp
* ``payload``    TEXT NOT NULL — full canonical JSON of the event
"""

from __future__ import annotations

import sqlite3
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    from spanforge.event import Event

__all__ = ["SyncSQLiteExporter"]

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id   TEXT NOT NULL,
    event_type TEXT NOT NULL,
    source     TEXT NOT NULL,
    org_id     TEXT,
    trace_id   TEXT,
    span_id    TEXT,
    ts         TEXT NOT NULL,
    payload    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_trace_id  ON events (trace_id);
CREATE INDEX IF NOT EXISTS idx_events_event_type ON events (event_type);
CREATE INDEX IF NOT EXISTS idx_events_ts         ON events (ts);
"""

_INSERT = """
INSERT INTO events (event_id, event_type, source, org_id, trace_id, span_id, ts, payload)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
"""


class SyncSQLiteExporter:
    """Synchronous exporter that writes events to a SQLite database.

    Thread-safe: a :class:`threading.Lock` serialises all writes.

    Args:
        path: Filesystem path for the SQLite database file.  Defaults to
              ``"spanforge_events.db"``.  Use ``":memory:"`` for tests.

    Raises:
        sqlite3.Error: If the database cannot be opened or the schema
                       cannot be initialised.
    """

    def __init__(self, path: str | Path = "spanforge_events.db") -> None:
        self._path = str(path)
        self._lock = threading.Lock()
        self._closed = False
        self._conn: sqlite3.Connection = sqlite3.connect(
            self._path,
            check_same_thread=False,
        )
        self._conn.executescript(_CREATE_TABLE)
        self._conn.commit()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def export(self, event: Event) -> None:
        """Persist *event* to the SQLite database.

        Args:
            event: A fully-formed :class:`~spanforge.event.Event` instance.

        Raises:
            RuntimeError:  If :meth:`close` has already been called.
            sqlite3.Error: If the INSERT fails.
        """
        if self._closed:
            raise RuntimeError("SyncSQLiteExporter is closed")
        ts = str(getattr(event, "timestamp", "") or "")
        row = (
            str(event.event_id),
            str(event.event_type.value if hasattr(event.event_type, "value") else event.event_type),
            str(getattr(event, "source", "") or ""),
            str(getattr(event, "org_id", "") or "") or None,
            str(getattr(event, "trace_id", "") or "") or None,
            str(getattr(event, "span_id", "") or "") or None,
            ts,
            event.to_json(),
        )
        with self._lock:
            self._conn.execute(_INSERT, row)
            self._conn.commit()

    def flush(self) -> None:
        """Flush — commits are immediate per-write, so this is a no-op."""

    def close(self) -> None:
        """Close the database connection.  Safe to call multiple times."""
        with self._lock:
            if not self._closed:
                self._closed = True
                try:
                    self._conn.close()
                except sqlite3.Error:
                    pass
