"""spanforge.prompt_registry — Prompt registry with versioning and W3C-event emission.

The prompt registry provides a centralised store for prompt templates so that
every rendered prompt is linked to the exact version that produced it.  This
enables:

* **Reproducibility** — re-run any historical span with the same prompt.
* **A/B testing** — route traffic between prompt versions and compare results.
* **Audit trail** — the RFC-0001 ``llm.prompt.*`` events capture template
  load, version change, and render events.

Quick start
-----------
::

    from spanforge.prompt_registry import PromptRegistry

    registry = PromptRegistry()
    registry.register(
        name="rag_system",
        template="You are {role}.  Answer only from: {context}",
        version="1.0.0",
    )

    rendered = registry.render("rag_system", {"role": "expert", "context": "...docs..."})
    print(rendered)
    # You are expert.  Answer only from: ...docs...

    # Later, update the template — version change event is emitted automatically.
    registry.register(
        name="rag_system",
        template="You are {role}.  Use ONLY these documents: {context}",
        version="1.1.0",
    )

Module-level singleton
----------------------
A module-level ``_DEFAULT_REGISTRY`` is provided.  Helper functions
:func:`register_prompt`, :func:`get_prompt_version`, and :func:`render_prompt`
delegate to it for convenience::

    from spanforge.prompt_registry import register_prompt, render_prompt

    register_prompt("greet", "Hello, {name}!", version="1.0.0")
    text = render_prompt("greet", {"name": "world"})
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "PromptRegistry",
    "PromptVersion",
    "get_prompt_version",
    "register_prompt",
    "render_prompt",
]

_log = logging.getLogger("spanforge.prompt_registry")

# Simple {placeholder} pattern (not Jinja — zero runtime dependencies).
_PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


# ---------------------------------------------------------------------------
# PromptVersion dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PromptVersion:
    """An immutable snapshot of a versioned prompt template.

    Args:
        name:       Registry name (e.g. ``"rag_system"``).
        template:   Raw template string with ``{variable}`` placeholders.
        version:    Semantic version string (e.g. ``"1.0.0"``).
        variables:  List of placeholder names extracted from *template*.
        created_at: Unix timestamp when this version was registered.
        metadata:   Free-form metadata dict (author, model hint, etc.).
    """

    name: str
    template: str
    version: str
    variables: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] | None = None

    def render(self, variables: dict[str, Any]) -> str:
        """Render the template by substituting *variables*.

        Args:
            variables: Dict of ``{placeholder: value}`` pairs.

        Returns:
            The rendered string.

        Raises:
            KeyError: If a required placeholder is missing from *variables*.

        Example::

            pv = PromptVersion("greet", "Hello, {name}!", "1.0.0", ["name"])
            pv.render({"name": "Alice"})
            # "Hello, Alice!"
        """
        missing = [v for v in self.variables if v not in variables]
        if missing:
            raise KeyError(
                f"PromptVersion '{self.name}@{self.version}' requires variables "
                f"{missing!r} but they were not supplied."
            )
        return self.template.format(**variables)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "template": self.template,
            "version": self.version,
            "variables": self.variables,
            "created_at": self.created_at,
        }
        if self.metadata is not None:
            d["metadata"] = self.metadata
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PromptVersion":
        return cls(
            name=data["name"],
            template=data["template"],
            version=data["version"],
            variables=list(data.get("variables", [])),
            created_at=float(data.get("created_at", time.time())),
            metadata=data.get("metadata"),
        )


# ---------------------------------------------------------------------------
# PromptRegistry
# ---------------------------------------------------------------------------


class PromptRegistry:
    """Thread-safe registry of versioned prompt templates.

    Multiple versions of the same template name are stored independently.
    The *latest* version (most recently registered) is used by default when
    calling :meth:`render`.

    Example::

        registry = PromptRegistry()
        registry.register("system", "You are {role}.", version="1.0.0")
        registry.register("system", "You are a helpful {role}.", version="2.0.0")

        # Uses version 2.0.0 (latest).
        registry.render("system", {"role": "assistant"})
    """

    def __init__(self) -> None:
        import threading  # noqa: PLC0415
        self._lock = threading.RLock()
        # {name: {version: PromptVersion}}
        self._store: dict[str, dict[str, PromptVersion]] = {}
        # {name: version_string}  — last registered version = default
        self._latest: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        template: str,
        *,
        version: str = "1.0.0",
        metadata: dict[str, Any] | None = None,
    ) -> PromptVersion:
        """Register (or update) a prompt template.

        Emits:
        * ``llm.prompt.template.loaded`` on first registration.
        * ``llm.prompt.version.changed`` when a *name* already exists
          (even if the version string is the same).

        Args:
            name:     Unique prompt name within this registry.
            template: Template string with ``{variable}`` placeholders.
            version:  Semantic version string.
            metadata: Optional free-form metadata.

        Returns:
            The newly created :class:`PromptVersion`.
        """
        variables = _PLACEHOLDER_RE.findall(template)
        pv = PromptVersion(
            name=name,
            template=template,
            version=version,
            variables=variables,
            metadata=metadata,
        )
        with self._lock:
            existing = self._store.get(name)
            is_new = existing is None
            self._store.setdefault(name, {})[version] = pv
            previous_version = self._latest.get(name)
            self._latest[name] = version

        # Emit RFC-0001 events outside the lock.
        self._emit_register_events(pv, is_new=is_new, previous_version=previous_version)
        return pv

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get(self, name: str, version: str | None = None) -> PromptVersion:
        """Return the :class:`PromptVersion` for *name*.

        Args:
            name:    Prompt name.
            version: Explicit version string, or ``None`` for the latest.

        Raises:
            KeyError: If *name* or *version* is not found.
        """
        with self._lock:
            versions = self._store.get(name)
            if versions is None:
                raise KeyError(f"No prompt registered with name={name!r}")
            if version is None:
                version = self._latest[name]
            pv = versions.get(version)
            if pv is None:
                raise KeyError(
                    f"Prompt {name!r} has no version {version!r}. "
                    f"Available: {sorted(versions)!r}"
                )
            return pv

    def list_versions(self, name: str) -> list[str]:
        """Return all registered version strings for *name*, sorted ascending."""
        with self._lock:
            versions = self._store.get(name)
            if versions is None:
                raise KeyError(f"No prompt registered with name={name!r}")
            return sorted(versions.keys())

    def list_names(self) -> list[str]:
        """Return all registered prompt names, sorted."""
        with self._lock:
            return sorted(self._store.keys())

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def render(
        self,
        name: str,
        variables: dict[str, Any],
        *,
        version: str | None = None,
        span_id: str | None = None,
        trace_id: str | None = None,
    ) -> str:
        """Render a prompt template, emitting a ``llm.prompt.rendered`` event.

        Args:
            name:      Prompt name.
            variables: Substitution variables.
            version:   Optional version string; defaults to latest.
            span_id:   Optional parent span ID for event correlation.
            trace_id:  Optional trace ID for event correlation.

        Returns:
            The rendered template string.

        Raises:
            KeyError: If the prompt name or version is not found, or if a
                      required variable is missing.
        """
        pv = self.get(name, version)
        rendered = pv.render(variables)
        self._emit_rendered_event(pv, rendered, span_id=span_id, trace_id=trace_id)
        return rendered

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def export_all(self) -> list[dict[str, Any]]:
        """Return a list of ``to_dict()`` dicts for all registered prompt versions."""
        with self._lock:
            result = []
            for versions in self._store.values():
                for pv in versions.values():
                    result.append(pv.to_dict())
            return result

    def import_all(self, records: list[dict[str, Any]]) -> None:
        """Bulk-import prompt versions from a list of dicts (no events emitted)."""
        with self._lock:
            for rec in records:
                pv = PromptVersion.from_dict(rec)
                self._store.setdefault(pv.name, {})[pv.version] = pv
                self._latest[pv.name] = pv.version

    # ------------------------------------------------------------------
    # Internal event helpers
    # ------------------------------------------------------------------

    def _emit_register_events(
        self,
        pv: PromptVersion,
        *,
        is_new: bool,
        previous_version: str | None,
    ) -> None:
        try:
            from spanforge._stream import emit_rfc_event  # noqa: PLC0415
            from spanforge.types import EventType  # noqa: PLC0415
            if is_new:
                emit_rfc_event(
                    EventType.PROMPT_TEMPLATE_LOADED,
                    payload=pv.to_dict(),
                )
            else:
                emit_rfc_event(
                    EventType.PROMPT_VERSION_CHANGED,
                    payload={
                        **pv.to_dict(),
                        "previous_version": previous_version,
                    },
                )
        except Exception as exc:  # NOSONAR
            _log.debug("prompt_registry: failed to emit register event: %s", exc)

    def _emit_rendered_event(
        self,
        pv: PromptVersion,
        rendered: str,
        *,
        span_id: str | None,
        trace_id: str | None,
    ) -> None:
        try:
            from spanforge._stream import emit_rfc_event  # noqa: PLC0415
            from spanforge.types import EventType  # noqa: PLC0415
            emit_rfc_event(
                EventType.PROMPT_RENDERED,
                payload={
                    "name": pv.name,
                    "version": pv.version,
                    # Omit the rendered text to avoid leaking PII; include
                    # only the prompt name/version for correlation.
                    "rendered_length": len(rendered),
                },
                span_id=span_id,
                trace_id=trace_id,
            )
        except Exception as exc:  # NOSONAR
            _log.debug("prompt_registry: failed to emit rendered event: %s", exc)


# ---------------------------------------------------------------------------
# Module-level singleton + helpers
# ---------------------------------------------------------------------------

_DEFAULT_REGISTRY = PromptRegistry()


def register_prompt(
    name: str,
    template: str,
    *,
    version: str = "1.0.0",
    metadata: dict[str, Any] | None = None,
) -> PromptVersion:
    """Register a prompt in the module-level default registry.

    Convenience wrapper around :meth:`PromptRegistry.register`.
    """
    return _DEFAULT_REGISTRY.register(name, template, version=version, metadata=metadata)


def get_prompt_version(name: str, version: str | None = None) -> PromptVersion:
    """Get a :class:`PromptVersion` from the module-level default registry."""
    return _DEFAULT_REGISTRY.get(name, version)


def render_prompt(
    name: str,
    variables: dict[str, Any],
    *,
    version: str | None = None,
    span_id: str | None = None,
    trace_id: str | None = None,
) -> str:
    """Render a prompt from the module-level default registry.

    Convenience wrapper around :meth:`PromptRegistry.render`.
    """
    return _DEFAULT_REGISTRY.render(
        name, variables, version=version, span_id=span_id, trace_id=trace_id
    )
