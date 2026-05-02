"""spanforge.core.dx — Developer experience (DX) helpers.

Provides :class:`DevCLI` for managing an in-process dev environment and
:class:`ModuleCLI` for scaffolding new spanforge plug-in modules.
"""

from __future__ import annotations

import textwrap
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# DevCLI — lightweight local dev environment
# ---------------------------------------------------------------------------

class DevCLI:
    """Thin manager for a local spanforge dev environment.

    The dev environment is entirely in-process: a simple key/value store
    that tracks whether a "service" is running plus a circular log buffer.
    No real Docker or network services are required.
    """

    _MAX_LOG_LINES: int = 1000

    def __init__(self) -> None:
        self._running: str | None = None
        self._log: list[str] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self, service: str = "spanforge-dev") -> None:
        """Start the named dev service."""
        self._running = service
        self._append_log(f"[start] service={service!r} started")

    def stop(self) -> None:
        """Stop the current dev service."""
        if self._running:
            self._append_log(f"[stop] service={self._running!r} stopped")
        self._running = None

    def reset(self) -> None:
        """Reset the dev environment (stop + clear logs)."""
        self.stop()
        self._log.clear()
        self._append_log("[reset] dev environment cleared")

    def logs(self) -> list[str]:
        """Return accumulated log lines."""
        return list(self._log)

    def status(self) -> dict[str, object]:
        """Return a JSON-serialisable status dict."""
        return {
            "running": self._running is not None,
            "service": self._running,
            "log_lines": len(self._log),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _append_log(self, line: str) -> None:
        if len(self._log) >= self._MAX_LOG_LINES:
            self._log.pop(0)
        self._log.append(line)


# ---------------------------------------------------------------------------
# ModuleCLI — plug-in module scaffolding
# ---------------------------------------------------------------------------

@dataclass
class ScaffoldResult:
    """Result of a :meth:`ModuleCLI.scaffold` call."""

    root_dir: Path
    files: dict[str, str] = field(default_factory=dict)


class ModuleCLI:
    """Scaffold new spanforge plug-in modules."""

    def scaffold(
        self,
        module_name: str,
        trust_level: str = "UNTRUSTED",
        author: str = "unknown",
        base_dir: Path | None = None,
    ) -> ScaffoldResult:
        """Generate a minimal spanforge module directory structure.

        Parameters
        ----------
        module_name:
            Python-identifier name for the module (e.g. ``my_plugin``).
        trust_level:
            One of ``UNTRUSTED``, ``VERIFIED``, ``TRUSTED``.
        author:
            Author name or team slug written into generated metadata.
        base_dir:
            Parent directory under which the module folder is created.
            Defaults to the current working directory.

        Returns
        -------
        ScaffoldResult
            Contains the root directory path and a mapping of
            relative-path → file-content for all generated files.
        """
        if not module_name.isidentifier():
            raise ValueError(
                f"module_name must be a valid Python identifier, got {module_name!r}"
            )

        root = (base_dir or Path(".")) / module_name
        files: dict[str, str] = {
            "__init__.py": self._render_init(module_name, trust_level, author),
            "plugin.py": self._render_plugin(module_name),
            "README.md": self._render_readme(module_name, trust_level, author),
            "pyproject.toml": self._render_pyproject(module_name, author),
        }
        return ScaffoldResult(root_dir=root, files=files)

    # ------------------------------------------------------------------
    # Template renderers
    # ------------------------------------------------------------------

    @staticmethod
    def _render_init(name: str, trust_level: str, author: str) -> str:
        return textwrap.dedent(f'''\
            """spanforge plug-in module: {name}.

            Trust level : {trust_level}
            Author      : {author}
            """

            from __future__ import annotations

            from .plugin import Plugin

            __all__ = ["Plugin"]
        ''')

    @staticmethod
    def _render_plugin(name: str) -> str:
        return textwrap.dedent(f'''\
            """Core plugin implementation for {name}."""

            from __future__ import annotations

            from spanforge.sdk.operator import BaseOperator


            class Plugin(BaseOperator):
                """Entry-point for the {name} plug-in."""

                name: str = {name!r}

                def handle(self, event: dict) -> dict:  # type: ignore[override]
                    """Process a single span event."""
                    # TODO: implement plugin logic here
                    return event
        ''')

    @staticmethod
    def _render_readme(name: str, trust_level: str, author: str) -> str:
        return textwrap.dedent(f'''\
            # {name}

            A spanforge plug-in module.

            | Field        | Value          |
            |--------------|----------------|
            | Trust level  | {trust_level}  |
            | Author       | {author}       |

            ## Installation

            ```bash
            pip install .
            ```

            ## Usage

            ```python
            from {name} import Plugin
            plugin = Plugin()
            result = plugin.handle(event)
            ```
        ''')

    @staticmethod
    def _render_pyproject(name: str, author: str) -> str:
        return textwrap.dedent(f'''\
            [build-system]
            requires = ["setuptools>=68"]
            build-backend = "setuptools.backends.legacy:build"

            [project]
            name = "{name}"
            version = "0.1.0"
            authors = [{{name = "{author}"}}]
            dependencies = ["spanforge>=1.0.0"]

            [project.entry-points."spanforge.plugins"]
            {name} = "{name}:Plugin"
        ''')
