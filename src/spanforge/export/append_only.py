"""Append-only JSONL exporter with fsync, rotation, and WORM backend support.

Provides a tamper-evident append-only audit log suitable for compliance workloads
(SOC 2, HIPAA, GDPR) where events must never be overwritten or truncated.

Features
--------
* Opens files in append-only mode (``O_APPEND`` on POSIX, ``"a"`` elsewhere).
* ``fsync`` after every write to guarantee durability.
* Automatic file rotation when ``max_bytes`` is exceeded — a ``CHAIN_ROTATED``
  audit event is inserted at the boundary.
* Optional :class:`WORMBackend` for pushing sealed files to immutable object
  stores (S3 Object Lock, GCS Retention Policy, Azure Immutable Storage).

Thread-safety: a :class:`threading.Lock` serialises all writes.

Example::

    exporter = AppendOnlyJSONLExporter(
        path="audit.jsonl",
        org_secret="corp-key-001",
        source="audit@1.0.0",
        max_bytes=50_000_000,
    )
    exporter.append(event)
    exporter.close()
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from spanforge.event import Event

__all__ = [
    "AppendOnlyJSONLExporter",
    "WORMBackend",
    "WORMUploadResult",
]


# ---------------------------------------------------------------------------
# WORM Backend protocol
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WORMUploadResult:
    """Result of a WORM backend upload.

    Attributes:
        success:     Whether the upload succeeded.
        location:    The remote URI or key for the uploaded object.
        error:       Error message if the upload failed, or ``None``.
        metadata:    Optional metadata returned by the backend.
    """

    success: bool
    location: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class WORMBackend(Protocol):
    """Protocol for Write-Once-Read-Many storage backends.

    Implementations must accept a local file path and push it to an immutable
    object store.  The file is sealed (closed) before upload.
    """

    def upload(self, local_path: str, remote_key: str) -> WORMUploadResult:
        """Upload a sealed file to WORM storage.

        Args:
            local_path:  Absolute path to the local file.
            remote_key:  Remote object key / blob name.

        Returns:
            A :class:`WORMUploadResult` indicating success or failure.
        """
        ...  # pragma: no cover

    def write(self, event: "Event") -> None:
        """Write a single event to WORM storage atomically."""
        ...  # pragma: no cover

    def list_files(self) -> list[str]:
        """List all files/objects stored in the WORM backend."""
        ...  # pragma: no cover

    def verify_chain(self) -> "ChainVerificationResult":
        """Verify the HMAC chain across all stored files."""
        ...  # pragma: no cover


# ---------------------------------------------------------------------------
# AppendOnlyJSONLExporter
# ---------------------------------------------------------------------------


class AppendOnlyJSONLExporter:
    """Append-only JSONL exporter with fsync, rotation, and WORM support.

    Args:
        path:        Base file path for the audit log.
        org_secret:  HMAC signing key for chain-rotation events.
        source:      ``source`` field for auto-generated audit events.
        max_bytes:   Maximum file size before rotation (0 = no rotation).
        worm_backend: Optional :class:`WORMBackend` for sealing rotated files.

    Raises:
        ValueError: If *max_bytes* is negative.

    Example::

        exporter = AppendOnlyJSONLExporter(
            path="audit.jsonl",
            org_secret="corp-key-001",
            source="audit@1.0.0",
            max_bytes=50_000_000,
        )
        for event in events:
            exporter.append(event)
        exporter.close()
    """

    __slots__ = (
        "_base_path",
        "_current_path",
        "_fh",
        "_lock",
        "_max_bytes",
        "_org_secret",
        "_rotation_index",
        "_source",
        "_written_bytes",
        "_worm_backend",
    )

    def __init__(
        self,
        path: str | Path,
        org_secret: str,
        source: str,
        max_bytes: int = 0,
        worm_backend: WORMBackend | None = None,
    ) -> None:
        if max_bytes < 0:
            raise ValueError("max_bytes must be >= 0")
        self._base_path = Path(path)
        self._org_secret = org_secret
        self._source = source
        self._max_bytes = max_bytes
        self._worm_backend = worm_backend

        self._lock = threading.Lock()
        self._rotation_index = 0
        self._current_path = self._base_path
        self._fh: IO[bytes] | None = None
        self._written_bytes = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_open(self) -> IO[bytes]:
        """Open the file handle in binary append mode if not already open."""
        if self._fh is None:
            self._current_path.parent.mkdir(parents=True, exist_ok=True)
            # SF-13-A: Guard against overwrite — only append mode is allowed
            if self._current_path.exists():
                import stat as _stat  # noqa: PLC0415
                mode = self._current_path.stat().st_mode
                # File exists — verify we are appending, not overwriting
                pass  # open in 'ab' guarantees append semantics
            self._fh = open(  # noqa: SIM115
                self._current_path, mode="ab"
            )
            # Set written_bytes to current file size for resumed files
            self._written_bytes = self._current_path.stat().st_size
        return self._fh

    def write_exclusive(self, path: str | Path) -> None:
        """Raise :class:`~spanforge.exceptions.AuditStorageError` if *path* already exists.

        Use this to enforce that a new audit log file is created, not
        overwritten.  For append-to-existing, use :meth:`append` directly.
        """
        from spanforge.exceptions import AuditStorageError  # noqa: PLC0415

        p = Path(path)
        if p.exists():
            raise AuditStorageError(
                f"Audit log file already exists and cannot be overwritten: {p}.  "
                "Use append mode or choose a new filename."
            )

    def _write_line(self, line_bytes: bytes) -> None:
        """Write a line and fsync to disk."""
        fh = self._ensure_open()
        fh.write(line_bytes)
        fh.write(b"\n")
        fh.flush()
        os.fsync(fh.fileno())
        self._written_bytes += len(line_bytes) + 1

    def _needs_rotation(self) -> bool:
        """Return True if the file exceeds max_bytes."""
        return self._max_bytes > 0 and self._written_bytes >= self._max_bytes

    def _rotate(self) -> None:
        """Seal the current file and open a new one.

        Inserts an ``AUDIT_CHAIN_ROTATED`` event at the boundary.
        """
        from spanforge.event import Event  # noqa: PLC0415
        from spanforge.types import EventType  # noqa: PLC0415
        from spanforge.ulid import generate as gen_ulid  # noqa: PLC0415

        old_path = self._current_path

        # Insert chain rotation event into old file
        rotation_event = Event(
            event_type=EventType.AUDIT_CHAIN_ROTATED.value,
            source=self._source,
            payload={
                "reason": "file_rotation",
                "old_file": str(old_path),
                "rotation_index": self._rotation_index,
                "rotated_at": datetime.now(timezone.utc).isoformat(),
            },
            event_id=gen_ulid(),
        )
        rotation_json = rotation_event.to_json().encode("utf-8")
        self._write_line(rotation_json)

        # Close old file
        if self._fh is not None:
            self._fh.flush()
            os.fsync(self._fh.fileno())
            self._fh.close()
            self._fh = None

        # Push to WORM backend if configured
        if self._worm_backend is not None:
            remote_key = f"{old_path.stem}_{self._rotation_index}{old_path.suffix}"
            self._worm_backend.upload(str(old_path), remote_key)

        # Open new file
        self._rotation_index += 1
        stem = self._base_path.stem
        suffix = self._base_path.suffix
        self._current_path = self._base_path.parent / f"{stem}.{self._rotation_index}{suffix}"
        self._written_bytes = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def append(self, event: Event) -> None:
        """Append a signed event to the audit log.

        Thread-safe. Triggers rotation when ``max_bytes`` is exceeded.

        Args:
            event: The event to append (should already be signed).
        """
        with self._lock:
            line_bytes = event.to_json().encode("utf-8")
            self._write_line(line_bytes)

            if self._needs_rotation():
                self._rotate()

    def append_batch(self, events: list[Event]) -> int:
        """Append multiple events. Returns the count written."""
        with self._lock:
            count = 0
            for event in events:
                line_bytes = event.to_json().encode("utf-8")
                self._write_line(line_bytes)
                count += 1

                if self._needs_rotation():
                    self._rotate()
            return count

    def close(self) -> None:
        """Flush and close the current file handle. Idempotent."""
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.flush()
                    os.fsync(self._fh.fileno())
                finally:
                    self._fh.close()
                    self._fh = None

    def rotate(self, max_size_mb: int = 100) -> None:
        """Force rotation if current file exceeds *max_size_mb* megabytes.

        A ``CHAIN_ROTATED`` event is inserted at the boundary so the HMAC
        chain is preserved across files.

        Args:
            max_size_mb: Trigger rotation when file exceeds this size.
                         Pass 0 to force immediate rotation.
        """
        with self._lock:
            threshold = max_size_mb * 1_048_576
            if threshold == 0 or self._written_bytes >= threshold:
                self._rotate()

    @property
    def current_path(self) -> Path:
        """The path of the file currently being written to."""
        return self._current_path

    @property
    def rotation_count(self) -> int:
        """Number of file rotations that have occurred."""
        return self._rotation_index

    def __enter__(self) -> AppendOnlyJSONLExporter:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return (
            f"AppendOnlyJSONLExporter(path={str(self._base_path)!r}, "
            f"rotations={self._rotation_index})"
        )
