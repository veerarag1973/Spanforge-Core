"""Consumer registration API for spanforge.

Provides a lightweight registry that downstream tools, services, and libraries
can use to declare which event namespaces and schema versions they depend on.
This enables proactive compatibility checking between producers and consumers
before runtime failures occur.

Typical usage::

    from spanforge.consumer import register_consumer, assert_compatible

    # Register your tool's schema requirements.
    register_consumer(
        tool_name="my-analytics-pipeline",
        namespaces=["trace", "eval"],
        schema_version="1.0",
    )

    # Later — verify all registered consumers are compatible with the current schema.
    assert_compatible()   # raises IncompatibleSchemaError if any consumer is incompatible

See :class:`ConsumerRegistry` for the full registry API.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "ConsumerRecord",
    "ConsumerRegistry",
    "IncompatibleSchemaError",
    "assert_compatible",
    "get_registry",
    "register_consumer",
]

# ---------------------------------------------------------------------------
# Sentinel — current schema version understood by the library
# ---------------------------------------------------------------------------

_CURRENT_SCHEMA_VERSION = "2.0"

# Accepted schema version patterns (semver-like, e.g. "1.0", "1.1", "2.0")
_VERSION_RE = re.compile(r"^\d+\.\d+$")


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IncompatibleSchemaError(Exception):
    """Raised when a consumer requires a schema version incompatible with the installed one.

    Not compatible with the currently installed library version.

    Attributes:
        incompatible:  List of ``(tool_name, required_version)`` pairs that
                       are incompatible with the installed schema version.
    """

    def __init__(self, incompatible: Sequence[tuple[str, str]]) -> None:
        self.incompatible = list(incompatible)
        pairs = ", ".join(f"{t!r} ({v})" for t, v in self.incompatible)
        super().__init__(
            f"Incompatible schema consumers: {pairs}. "
            f"Installed schema version: {_CURRENT_SCHEMA_VERSION}"
        )


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConsumerRecord:
    """A record of a registered consumer's schema requirements.

    Attributes:
        tool_name:       Human-readable name of the consuming tool or service.
        namespaces:      Event namespaces the consumer depends on, e.g.
                         ``["trace", "eval"]``.
        schema_version:  Minimum schema version required.  Must be in
                         ``MAJOR.MINOR`` format (e.g. ``"1.0"``).
        contact:         Optional contact info (e.g. email, team name, Slack
                         channel) for compatibility issue escalation.
        metadata:        Optional freeform metadata for tooling.
    """

    tool_name: str
    namespaces: tuple[str, ...]
    schema_version: str
    contact: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"ConsumerRecord(tool_name={self.tool_name!r}, "
            f"namespaces={list(self.namespaces)!r}, "
            f"schema_version={self.schema_version!r})"
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class ConsumerRegistry:
    """Thread-safe registry of downstream consumer schema requirements.

    Consumers register themselves with :meth:`register` declaring which
    namespaces and schema version they depend on.  Operators can then call
    :meth:`assert_compatible` to validate all consumers before deploying a
    new schema version.

    Example::

        registry = ConsumerRegistry()
        registry.register("my-tool", namespaces=["trace"], schema_version="1.0")
        registry.assert_compatible()
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[ConsumerRecord] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        tool_name: str,
        *,
        namespaces: Sequence[str],
        schema_version: str,
        contact: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> ConsumerRecord:
        """Register a consumer's schema requirements.

        Args:
            tool_name:       Name of the consuming tool or service.
            namespaces:      Event namespaces required (e.g. ``["trace", "eval"]``).
            schema_version:  Minimum schema version required (``"MAJOR.MINOR"``).
            contact:         Optional contact info for compatibility escalations.
            metadata:        Optional freeform metadata dict.

        Returns:
            The created :class:`ConsumerRecord`.

        Raises:
            ValueError: If *tool_name* is empty, *namespaces* is empty, or
                        *schema_version* is not in ``MAJOR.MINOR`` format.
        """
        if not tool_name or not tool_name.strip():
            raise ValueError("tool_name must be a non-empty string")
        if not namespaces:
            raise ValueError("namespaces must contain at least one entry")
        if not _VERSION_RE.match(schema_version):
            raise ValueError(
                f"schema_version must be in MAJOR.MINOR format (got {schema_version!r})"
            )

        record = ConsumerRecord(
            tool_name=tool_name.strip(),
            namespaces=tuple(str(ns).strip() for ns in namespaces),
            schema_version=schema_version,
            contact=contact,
            metadata=dict(metadata) if metadata else {},
        )
        with self._lock:
            self._records.append(record)
        return record

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def all(self) -> list[ConsumerRecord]:
        """Return a snapshot of all registered consumer records.

        Returns:
            List of all :class:`ConsumerRecord` instances.
        """
        with self._lock:
            return list(self._records)

    def by_namespace(self, namespace: str) -> list[ConsumerRecord]:
        """Return all consumers that depend on *namespace*.

        Args:
            namespace: The namespace string to filter by (e.g. ``"trace"``).

        Returns:
            Filtered list of :class:`ConsumerRecord` instances.
        """
        with self._lock:
            return [r for r in self._records if namespace in r.namespaces]

    def by_tool(self, tool_name: str) -> ConsumerRecord | None:
        """Return the first record registered under *tool_name*, or ``None``.

        Args:
            tool_name: The tool name to look up.

        Returns:
            The :class:`ConsumerRecord` or ``None`` if not found.
        """
        with self._lock:
            for r in self._records:
                if r.tool_name == tool_name:
                    return r
        return None

    # ------------------------------------------------------------------
    # Compatibility checking
    # ------------------------------------------------------------------

    def check_compatible(
        self,
        installed_version: str = _CURRENT_SCHEMA_VERSION,
    ) -> list[tuple[str, str]]:
        """Check all consumers against *installed_version*.

        A consumer is *compatible* if its ``schema_version`` major matches and
        minor is less than or equal to the installed minor version.  That is:

        * Major version bump → always incompatible (breaking changes).
        * Minor version bump → backwards-compatible (new events only).

        Args:
            installed_version: Schema version to check against.  Defaults to
                                the current library schema version.

        Returns:
            List of ``(tool_name, required_version)`` pairs that are
            incompatible.  Empty list means everything is compatible.
        """
        try:
            inst_major, inst_minor = _parse_version(installed_version)
        except ValueError as exc:
            raise ValueError(
                f"installed_version must be MAJOR.MINOR format: {exc}"
            ) from exc

        incompatible: list[tuple[str, str]] = []
        with self._lock:
            for record in self._records:
                req_major, req_minor = _parse_version(record.schema_version)
                if req_major != inst_major or req_minor > inst_minor:
                    incompatible.append((record.tool_name, record.schema_version))
        return incompatible

    def assert_compatible(
        self,
        installed_version: str = _CURRENT_SCHEMA_VERSION,
    ) -> None:
        """Assert that all consumers are compatible with *installed_version*.

        Args:
            installed_version: Schema version to check against.  Defaults to
                                the current library schema version.

        Raises:
            IncompatibleSchemaError: If any registered consumer is incompatible.
        """
        incompatible = self.check_compatible(installed_version)
        if incompatible:
            raise IncompatibleSchemaError(incompatible)

    def clear(self) -> None:
        """Remove all records from the registry (useful in tests).

        .. warning::
            Not safe to call from production code while other threads may be
            registering consumers.
        """
        with self._lock:
            self._records.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._records)

    def __repr__(self) -> str:  # pragma: no cover
        return f"ConsumerRegistry(consumers={len(self)})"


# ---------------------------------------------------------------------------
# Module-level singleton and helpers
# ---------------------------------------------------------------------------

_GLOBAL_REGISTRY = ConsumerRegistry()


def get_registry() -> ConsumerRegistry:
    """Return the module-level :class:`ConsumerRegistry` singleton.

    Returns:
        The global :class:`ConsumerRegistry` instance.
    """
    return _GLOBAL_REGISTRY


def register_consumer(
    tool_name: str,
    *,
    namespaces: Sequence[str],
    schema_version: str,
    contact: str | None = None,
    metadata: dict[str, str] | None = None,
) -> ConsumerRecord:
    """Register a consumer in the global registry.

    Convenience wrapper around :meth:`ConsumerRegistry.register` that operates
    on the global singleton registry.

    Args:
        tool_name:       Name of the consuming tool or service.
        namespaces:      Event namespaces required (e.g. ``["trace", "eval"]``).
        schema_version:  Minimum schema version required (``"MAJOR.MINOR"``).
        contact:         Optional contact info for compatibility escalations.
        metadata:        Optional freeform metadata dict.

    Returns:
        The created :class:`ConsumerRecord`.

    Raises:
        ValueError: See :meth:`ConsumerRegistry.register`.
    """
    return _GLOBAL_REGISTRY.register(
        tool_name,
        namespaces=namespaces,
        schema_version=schema_version,
        contact=contact,
        metadata=metadata,
    )


def assert_compatible(
    installed_version: str = _CURRENT_SCHEMA_VERSION,
) -> None:
    """Assert all globally registered consumers are compatible with *installed_version*.

    Convenience wrapper around :meth:`ConsumerRegistry.assert_compatible` that
    operates on the global singleton registry.

    Args:
        installed_version: Schema version to check against.  Defaults to the
                           current library schema version.

    Raises:
        IncompatibleSchemaError: If any registered consumer is incompatible.
    """
    _GLOBAL_REGISTRY.assert_compatible(installed_version)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_version(version: str) -> tuple[int, int]:
    """Parse a ``"MAJOR.MINOR"`` version string into ``(int, int)``."""
    parts = version.split(".", 1)
    try:
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError) as exc:
        raise ValueError(f"Not a valid MAJOR.MINOR version: {version!r}") from exc
