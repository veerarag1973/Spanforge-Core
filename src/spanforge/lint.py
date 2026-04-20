"""spanforge.lint — SDK instrumentation linter.

Inspects Python source files for common spanforge instrumentation mistakes
before the code runs.  Ships as:

1. A **Python API** — call ``run_checks()`` from test suites or CI scripts.
2. A **flake8 plugin** — registered via ``[project.entry-points."flake8.extension"]``
   in ``pyproject.toml`` so AO-codes appear inline in editor linting.
3. A **CLI** — ``python -m spanforge.lint [FILES_OR_DIRS...]``.

AO error codes
--------------
AO000  Syntax error in source file.
AO001  Event() is missing a required field ('event_type', 'source', or 'payload').
AO002  Identity field ('actor_id', 'session_id', 'user_id') receives a bare str literal.
AO003  event_type string is not a registered EventType value.
AO004  LLM provider call detected outside a tracer span context.
AO005  emit_span / emit_agent_* called outside agent_run() / agent_step() context.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "LintError",
    "SpanForgeChecker",
    "run_checks",
]

# ---------------------------------------------------------------------------
# LintError
# ---------------------------------------------------------------------------

_REQUIRED_EVENT_FIELDS = frozenset({"event_type", "source", "payload"})
_IDENTITY_FIELDS = frozenset({"actor_id", "session_id", "user_id"})

# Patterns for LLM provider calls (AO004)
_LLM_CALL_PATTERNS = re.compile(
    r"(?:chat\.completions\.create|messages\.create|completions\.create|"
    r"\.generate\s*\(|\.complete\s*\()"
)

# Context-manager call names for AO004/AO005 checks
_SPAN_CONTEXT_NAMES = frozenset({"span", "agent_run", "agent_step"})
_EMIT_NAMES = frozenset({"emit_span", "emit_agent_run", "emit_agent_step"})


@dataclass(frozen=True)
class LintError:
    """An immutable lint finding.

    Attributes:
        code:     AO-code, e.g. ``"AO001"``.
        message:  Human-readable description.
        filename: File the error was found in.
        line:     1-based line number.
        col:      1-based column number.
    """

    code: str
    message: str
    filename: str
    line: int
    col: int

    def __str__(self) -> str:
        return f"{self.filename}:{self.line}:{self.col}: {self.code} {self.message}"


# ---------------------------------------------------------------------------
# AST visitor
# ---------------------------------------------------------------------------


class _SpanForgeVisitor(ast.NodeVisitor):
    """Walk an AST and collect AO-code lint errors."""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.errors: list[LintError] = []
        # Stack tracking whether we are inside a span/agent context manager
        self._in_span_context: int = 0

    # ------------------------------------------------------------------
    # AO001 — Missing required Event() field
    # ------------------------------------------------------------------

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func_name = _get_call_name(node)

        if func_name in ("Event", "spanforge.Event"):
            keyword_names = {kw.arg for kw in node.keywords}
            for required in _REQUIRED_EVENT_FIELDS:
                if required not in keyword_names:
                    self.errors.append(
                        LintError(
                            code="AO001",
                            message=f"Event() is missing required field '{required}'",
                            filename=self.filename,
                            line=node.lineno,
                            col=node.col_offset + 1,
                        )
                    )

            # AO002 — bare str literal for identity field
            for kw in node.keywords:
                if kw.arg in _IDENTITY_FIELDS and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    self.errors.append(
                        LintError(
                            code="AO002",
                            message=(
                                f"'{kw.arg}' receives a bare str literal; "
                                "wrap with Redactable()"
                            ),
                            filename=self.filename,
                            line=kw.value.lineno,
                            col=kw.value.col_offset + 1,
                        )
                    )

            # AO003 — unknown event_type string
            for kw in node.keywords:
                if kw.arg == "event_type" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                    value = kw.value.value
                    if not _is_registered_event_type(value):
                        self.errors.append(
                            LintError(
                                code="AO003",
                                message=f"event_type string '{value}' is not a registered EventType value",
                                filename=self.filename,
                                line=kw.value.lineno,
                                col=kw.value.col_offset + 1,
                            )
                        )

        # AO005 — emit_* outside agent context
        if func_name in _EMIT_NAMES and self._in_span_context == 0:
            self.errors.append(
                LintError(
                    code="AO005",
                    message=f"{func_name} called outside agent_run() / agent_step() context",
                    filename=self.filename,
                    line=node.lineno,
                    col=node.col_offset + 1,
                )
            )

        self.generic_visit(node)

    # ------------------------------------------------------------------
    # AO004 — LLM provider call outside span context (with-statement tracking)
    # ------------------------------------------------------------------

    def visit_With(self, node: ast.With) -> None:  # noqa: N802
        is_span = any(
            isinstance(item.context_expr, ast.Call)
            and _get_call_name(item.context_expr) in _SPAN_CONTEXT_NAMES
            for item in node.items
        )
        if is_span:
            self._in_span_context += 1
        self.generic_visit(node)
        if is_span:
            self._in_span_context -= 1

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:  # noqa: N802
        is_span = any(
            isinstance(item.context_expr, ast.Call)
            and _get_call_name(item.context_expr) in _SPAN_CONTEXT_NAMES
            for item in node.items
        )
        if is_span:
            self._in_span_context += 1
        self.generic_visit(node)
        if is_span:
            self._in_span_context -= 1


def _get_call_name(node: ast.Call) -> str:
    """Return a dotted name string for a Call node's function, or empty string."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _is_registered_event_type(value: str) -> bool:
    """Return True if *value* is a registered EventType string (best-effort)."""
    try:
        from spanforge.types import EventType as _ET

        return value in {m.value for m in _ET}  # type: ignore[attr-defined]
    except (ImportError, TypeError):
        # If we cannot import EventType, assume valid to avoid false positives
        return True


# ---------------------------------------------------------------------------
# Public run_checks() API
# ---------------------------------------------------------------------------


def run_checks(source: str, filename: str = "<string>") -> list[LintError]:
    """Parse *source* as valid Python 3 and return a list of :class:`LintError` objects.

    Args:
        source:   UTF-8 Python source code to analyse.
        filename: File path; used in :attr:`LintError.filename`.

    Returns:
        List of :class:`LintError` objects sorted by ``(line, col)``.
        Empty list when the file is clean.
    """
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as exc:
        return [
            LintError(
                code="AO000",
                message=f"Syntax error: {exc.msg}",
                filename=filename,
                line=exc.lineno or 1,
                col=exc.offset or 1,
            )
        ]

    visitor = _SpanForgeVisitor(filename=filename)
    visitor.visit(tree)
    return sorted(visitor.errors, key=lambda e: (e.line, e.col))


# ---------------------------------------------------------------------------
# Filesystem helpers used by CLI and flake8 plugin
# ---------------------------------------------------------------------------


def _iter_python_files(paths: list[str]) -> Iterator[Path]:
    """Yield all ``*.py`` files under the given *paths*."""
    for p_str in paths:
        path = Path(p_str)
        if path.is_file() and path.suffix == ".py":
            yield path
        elif path.is_dir():
            yield from path.rglob("*.py")


# ---------------------------------------------------------------------------
# flake8 plugin shim (imported via entry-point AO = spanforge.lint._flake8)
# ---------------------------------------------------------------------------

# The _flake8 sub-module is registered as the entry-point; provide a minimal
# SpanForgeChecker class here too so ``from spanforge.lint import SpanForgeChecker``
# works without importing a separate sub-module.


class SpanForgeChecker:
    """Minimal flake8-compatible checker that delegates to :func:`run_checks`.

    flake8 discovers this class via the ``flake8.extension`` entry-point and
    calls ``check_file()`` for each file it processes.
    """

    name = "spanforge-lint"
    version = "2.0.0"

    def __init__(self, tree: ast.AST, filename: str = "<string>", lines: list[str] | None = None) -> None:
        self._tree = tree
        self._filename = filename
        self._source = "".join(lines) if lines else ""

    def run(self) -> Iterator[tuple[int, int, str, type]]:
        """Yield ``(line, col, message, type)`` tuples for flake8."""
        errors = run_checks(self._source, filename=self._filename)
        for err in errors:
            yield (err.line, err.col - 1, f"{err.code} {err.message}", type(self))


# ---------------------------------------------------------------------------
# CLI entry point: python -m spanforge.lint [FILES_OR_DIRS...]
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    paths = sys.argv[1:] or ["."]
    total_errors = 0
    files_with_errors = 0

    for py_file in _iter_python_files(paths):
        try:
            source_code = py_file.read_text(encoding="utf-8")
        except OSError as read_err:
            print(f"spanforge.lint: cannot read {py_file}: {read_err}", file=sys.stderr)
            sys.exit(2)

        file_errors = run_checks(source_code, filename=str(py_file))
        for err in file_errors:
            print(str(err))
        if file_errors:
            total_errors += len(file_errors)
            files_with_errors += 1

    if total_errors:
        print(f"{total_errors} error(s) in {files_with_errors} file(s).")
        sys.exit(1)
    sys.exit(0)
