"""spanforge.deprecations — Per-event-type deprecation tracking.

Provides a thread-safe registry for deprecation notices that can be queried at
runtime, used by the CLI ``spanforge deprecations`` command, and populated from
migration roadmaps.

Public API
----------
DeprecationNotice         Frozen dataclass describing a single deprecation.
DeprecationRegistry       Thread-safe registry (use module-level helpers instead
                          of instantiating this directly in most cases).
get_registry()            Return the global singleton registry.
mark_deprecated(...)      Register a notice in the global registry.
get_deprecation_notice()  Look up a notice by event type.
warn_if_deprecated()      Issue DeprecationWarning if the type is registered.
list_deprecated()         Return all registered notices sorted by event_type.
"""

from __future__ import annotations

import threading
import warnings
from dataclasses import dataclass
from typing import Optional

__all__ = [
    "DeprecationNotice",
    "DeprecationRegistry",
    "get_deprecation_notice",
    "get_registry",
    "list_deprecated",
    "mark_deprecated",
    "warn_if_deprecated",
]


# ---------------------------------------------------------------------------
# DeprecationNotice
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DeprecationNotice:
    """Immutable record describing the deprecation of a single event type."""

    event_type: str
    since: str
    sunset: str
    replacement: Optional[str] = None
    notes: Optional[str] = None

    def format_message(self) -> str:
        """Return a human-readable deprecation message.

        Example::

            'llm.legacy.trace' is deprecated since 1.0.0 and will be removed
            in 2.0.0. Use 'llm.trace.span.completed' instead.
            Use the trace namespace instead.
        """
        msg = (
            f"'{self.event_type}' is deprecated since {self.since} "
            f"and will be removed in {self.sunset}."
        )
        if self.replacement:
            msg += f" Use '{self.replacement}' instead."
        if self.notes:
            msg += f" {self.notes}"
        return msg


# ---------------------------------------------------------------------------
# DeprecationRegistry
# ---------------------------------------------------------------------------


class DeprecationRegistry:
    """Thread-safe registry mapping event type strings to :class:`DeprecationNotice` objects."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._notices: dict[str, DeprecationNotice] = {}

    def mark_deprecated(
        self,
        event_type: str,
        *,
        since: str,
        sunset: str,
        replacement: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> DeprecationNotice:
        """Register a deprecation notice and return it.

        Args:
            event_type: The event type string being deprecated.
            since: Version when the deprecation was introduced.
            sunset: Version when the type will be removed.
            replacement: Optional suggested replacement event type.
            notes: Optional migration guidance.

        Returns:
            The newly registered :class:`DeprecationNotice`.
        """
        notice = DeprecationNotice(
            event_type=event_type,
            since=since,
            sunset=sunset,
            replacement=replacement,
            notes=notes,
        )
        with self._lock:
            self._notices[event_type] = notice
        return notice

    def get(self, event_type: str) -> Optional[DeprecationNotice]:
        """Return the notice for *event_type*, or ``None`` if not deprecated."""
        with self._lock:
            return self._notices.get(event_type)

    def is_deprecated(self, event_type: str) -> bool:
        """Return ``True`` if *event_type* has a registered deprecation notice."""
        with self._lock:
            return event_type in self._notices

    def warn_if_deprecated(self, event_type: str) -> None:
        """Issue a stdlib :class:`DeprecationWarning` if *event_type* is deprecated.

        Uses ``warnings.warn(..., DeprecationWarning, stacklevel=2)``.  No-op
        if the type is not registered.
        """
        notice = self.get(event_type)
        if notice is not None:
            warnings.warn(notice.format_message(), DeprecationWarning, stacklevel=2)

    def list_all(self) -> list[DeprecationNotice]:
        """Return all registered notices sorted by ``event_type``."""
        with self._lock:
            return sorted(self._notices.values(), key=lambda n: n.event_type)

    def remove(self, event_type: str) -> bool:
        """Remove the notice for *event_type*.

        Returns:
            ``True`` if a notice was removed, ``False`` if not found.
        """
        with self._lock:
            return self._notices.pop(event_type, None) is not None

    def clear(self) -> None:
        """Remove all registered notices.  Useful in tests."""
        with self._lock:
            self._notices.clear()


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_global_registry = DeprecationRegistry()


def get_registry() -> DeprecationRegistry:
    """Return the global :class:`DeprecationRegistry` singleton."""
    return _global_registry


# ---------------------------------------------------------------------------
# Module-level convenience helpers (operate on the global registry)
# ---------------------------------------------------------------------------


def mark_deprecated(
    event_type: str,
    *,
    since: str,
    sunset: str,
    replacement: Optional[str] = None,
    notes: Optional[str] = None,
) -> DeprecationNotice:
    """Register a deprecation notice in the global registry."""
    return _global_registry.mark_deprecated(
        event_type,
        since=since,
        sunset=sunset,
        replacement=replacement,
        notes=notes,
    )


def get_deprecation_notice(event_type: str) -> Optional[DeprecationNotice]:
    """Return the notice for *event_type* from the global registry, or ``None``."""
    return _global_registry.get(event_type)


def warn_if_deprecated(event_type: str) -> None:
    """Issue :class:`DeprecationWarning` if *event_type* is in the global registry."""
    notice = _global_registry.get(event_type)
    if notice is not None:
        warnings.warn(notice.format_message(), DeprecationWarning, stacklevel=2)


def list_deprecated() -> list[DeprecationNotice]:
    """Return all notices from the global registry sorted by ``event_type``."""
    return _global_registry.list_all()
