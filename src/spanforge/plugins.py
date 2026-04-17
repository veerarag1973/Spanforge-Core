"""spanforge.plugins — Entry-point plugin discovery.

Provides a single function :func:`discover` that loads objects registered via
Python packaging entry points.  Handles the ``importlib.metadata`` API split
between Python 3.9 (returns a ``dict``) and Python 3.10+ (returns a
``SelectableGroups`` object with ``.select()``), so callers never need to
write the version-gate themselves.

Usage::

    from spanforge.plugins import discover

    # Load all scorers registered under the "spanforge.scorers" group
    scorers = discover("spanforge.scorers")

    # Typical pattern: build a name → instance registry
    registry = {}
    for obj in discover("my_tool.plugins"):
        if callable(obj):
            instance = obj()
            registry[getattr(instance, "name", type(instance).__name__)] = instance

Entry-point registration example (``pyproject.toml``)::

    [project.entry-points."spanforge.scorers"]
    my_scorer = "my_package.scorers:MyScorer"
"""

from __future__ import annotations

import sys
from typing import Any

__all__ = ["discover"]


def discover(group: str) -> list[Any]:
    """Discover and load all entry points registered under *group*.

    Each registered entry point is loaded (its object is imported and
    returned).  Entry points that fail to load are silently skipped so that
    a broken third-party plugin cannot crash the host application.

    Args:
        group:  The entry-point group name (e.g. ``"spanforge.scorers"``).

    Returns:
        A list of loaded objects (classes, instances, functions — whatever the
        entry point points at).  Order matches the order returned by
        ``importlib.metadata``, which is typically installation order.

    Example::

        for scorer_cls in discover("spanforge.scorers"):
            print(scorer_cls.__name__)
    """
    try:
        if sys.version_info >= (3, 12):
            from importlib.metadata import entry_points

            eps = entry_points(group=group)
        elif sys.version_info >= (3, 10):
            from importlib.metadata import entry_points

            eps = entry_points().select(group=group)  # type: ignore[union-attr]
        else:
            # Python 3.9: entry_points() returns a plain dict
            from importlib.metadata import entry_points

            all_eps = entry_points()
            eps = all_eps.get(group, []) if isinstance(all_eps, dict) else []  # type: ignore[assignment]
    except Exception:
        return []

    loaded: list[Any] = []
    for ep in eps:
        try:
            obj = ep.load()
            loaded.append(obj)
        except Exception:
            pass
