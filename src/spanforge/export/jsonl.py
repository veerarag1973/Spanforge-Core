"""JSONL (newline-delimited JSON) file exporter for spanforge events.

Ideal for local development, integration tests, and building tamper-evident
audit trails that can be loaded back via
:meth:`~spanforge.stream.EventStream.from_file`.

Features
--------
* Appends one JSON line per event — safe for append-only audit storage.
* ``path="-"`` writes to *stdout* (useful for log pipelines).
* Async-safe: an :class:`asyncio.Lock` serialises concurrent appends so the
  file is never corrupted even when multiple coroutines share one exporter.
* Acts as an async context manager: ``async with JSONLExporter(...) as e:``.
* :meth:`flush` and :meth:`close` are safe to call multiple times.

Example::

    async with JSONLExporter("events.jsonl") as exporter:
        for event in events:
            await exporter.export(event)

    # Read back with EventStream
    from spanforge.stream import EventStream
    stream = EventStream.from_file("events.jsonl")
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import IO, TYPE_CHECKING, Union

if TYPE_CHECKING:
    from collections.abc import Sequence

    from spanforge.event import Event

__all__ = ["JSONLExporter"]

_PathLike = Union[str, Path]


class JSONLExporter:
    """Async exporter that appends events as newline-delimited JSON.

    Args:
        path:     File path, :class:`pathlib.Path`, or ``"-"`` for stdout.
        mode:     File open mode — ``"a"`` (append, default) or ``"w"``
                  (overwrite / truncate).
        encoding: File encoding (default ``"utf-8"``).

    Thread / coroutine safety:
        Concurrent calls to :meth:`export` or :meth:`export_batch` are
        serialised with an :class:`asyncio.Lock`; the output file is never
        written by more than one coroutine at a time.

    Raises:
        OSError: If the file cannot be opened or written.

    Example::

        exporter = JSONLExporter("audit.jsonl")
        await exporter.export(event)
        await exporter.close()
    """

    def __init__(
        self,
        path: _PathLike | str,
        mode: str = "a",
        encoding: str = "utf-8",
    ) -> None:
        if mode not in ("a", "w"):
            raise ValueError("mode must be 'a' or 'w'")
        self._path_str = str(path)
        self._mode = mode
        self._encoding = encoding
        self._file: IO[str] | None = None
        self._lock: asyncio.Lock = asyncio.Lock()
        self._closed: bool = False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_open(self) -> IO[str]:
        """Open the file handle if not already open.

        Returns:
            The open file handle.

        Raises:
            RuntimeError: If the exporter has been closed.
        """
        if self._closed:
            raise RuntimeError("JSONLExporter has been closed")
        if self._file is None:
            if self._path_str == "-":
                self._file = sys.stdout
            else:
                self._file = Path(self._path_str).open(  # noqa: SIM115
                    mode=self._mode,
                    encoding=self._encoding,
                )
        return self._file

    # ------------------------------------------------------------------
    # Async export API
    # ------------------------------------------------------------------

    async def export(self, event: Event) -> None:
        """Append a single event as one JSON line.

        Args:
            event: The event to write.

        Raises:
            RuntimeError: If the exporter has been closed.
            OSError:       If the write fails.
        """
        async with self._lock:
            fh = self._ensure_open()
            fh.write(event.to_json())
            fh.write("\n")

    async def export_batch(self, events: Sequence[Event]) -> int:
        """Append multiple events, one JSON line each.

        Args:
            events: Sequence of events to write.

        Returns:
            Number of events written.

        Raises:
            RuntimeError: If the exporter has been closed.
            OSError:       If the write fails.
        """
        if not events:
            return 0
        async with self._lock:
            fh = self._ensure_open()
            for event in events:
                fh.write(event.to_json())
                fh.write("\n")
        return len(events)

    # ------------------------------------------------------------------
    # Flush / close
    # ------------------------------------------------------------------

    def flush(self) -> None:
        """Flush internal write buffers to the OS.

        Safe to call when no file is open yet.  Does nothing if writing to
        stdout (which is managed externally).
        """
        if self._file is not None and self._file is not sys.stdout:
            self._file.flush()

    def close(self) -> None:
        """Flush and close the underlying file handle.

        Idempotent — safe to call multiple times.  Does not close stdout even
        when ``path="-"`` was used.
        """
        if self._closed:
            return
        self._closed = True
        if self._file is not None and self._file is not sys.stdout:
            try:
                self._file.flush()
            finally:
                self._file.close()
        self._file = None

    # ------------------------------------------------------------------
    # Async context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> JSONLExporter:
        """Enter the async context manager — opens the file lazily."""
        return self

    async def __aexit__(self, *_: object) -> None:
        """Exit the async context manager — flushes and closes the file."""
        self.close()

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"JSONLExporter(path={self._path_str!r}, "
            f"mode={self._mode!r})"
        )
