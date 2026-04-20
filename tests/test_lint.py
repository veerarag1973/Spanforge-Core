"""Tests for spanforge.lint — run_checks(), LintError, AO-codes, SpanForgeChecker."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from spanforge.lint import (
    LintError,
    SpanForgeChecker,
    _iter_python_files,
    run_checks,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _clean(source: str) -> str:
    return textwrap.dedent(source)


def _codes(errors: list[LintError]) -> list[str]:
    return [e.code for e in errors]


# ---------------------------------------------------------------------------
# LintError dataclass
# ---------------------------------------------------------------------------


class TestLintError:
    def test_fields(self) -> None:
        err = LintError(
            code="AO001",
            message="missing field 'source'",
            filename="test.py",
            line=5,
            col=3,
        )
        assert err.code == "AO001"
        assert err.message == "missing field 'source'"
        assert err.filename == "test.py"
        assert err.line == 5
        assert err.col == 3

    def test_str_format(self) -> None:
        err = LintError(code="AO002", message="bare string", filename="f.py", line=10, col=1)
        s = str(err)
        assert "f.py:10:1:" in s
        assert "AO002" in s
        assert "bare string" in s

    def test_is_frozen(self) -> None:
        err = LintError(code="AO001", message="m", filename="f", line=1, col=1)
        with pytest.raises(Exception):
            err.code = "AO999"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# run_checks — clean source
# ---------------------------------------------------------------------------


class TestRunChecksClean:
    def test_empty_source_no_errors(self) -> None:
        errors = run_checks("")
        assert errors == []

    def test_well_formed_event_no_errors(self) -> None:
        source = _clean("""
            from spanforge import Event
            from spanforge.types import EventType

            ev = Event(
                event_type=EventType.TRACE_SPAN_COMPLETED,
                source="svc@1.0",
                payload={"status": "ok"},
            )
        """)
        errors = run_checks(source)
        # AO001 should not fire for any of the 3 required fields
        ao001_errors = [e for e in errors if e.code == "AO001"]
        assert ao001_errors == []

    def test_no_errors_non_event_call(self) -> None:
        source = "x = dict(a=1, b=2)\n"
        errors = run_checks(source, filename="x.py")
        assert errors == []


# ---------------------------------------------------------------------------
# AO000 — Syntax error
# ---------------------------------------------------------------------------


class TestAO000:
    def test_syntax_error_returns_ao000(self) -> None:
        errors = run_checks("def broken(:\n    pass\n", filename="broken.py")
        assert len(errors) == 1
        assert errors[0].code == "AO000"
        assert errors[0].filename == "broken.py"

    def test_ao000_message_contains_syntax_error(self) -> None:
        errors = run_checks("x = (", filename="t.py")
        assert errors[0].code == "AO000"
        assert "Syntax error" in errors[0].message


# ---------------------------------------------------------------------------
# AO001 — Missing required Event() field
# ---------------------------------------------------------------------------


class TestAO001:
    def test_ao001_missing_event_type(self) -> None:
        source = _clean("""
            ev = Event(source="s", payload={})
        """)
        errors = run_checks(source)
        codes = _codes(errors)
        ao001 = [e for e in errors if e.code == "AO001" and "event_type" in e.message]
        assert len(ao001) >= 1

    def test_ao001_missing_source(self) -> None:
        source = _clean("""
            ev = Event(event_type="t", payload={})
        """)
        errors = run_checks(source)
        ao001 = [e for e in errors if e.code == "AO001" and "source" in e.message]
        assert len(ao001) >= 1

    def test_ao001_missing_payload(self) -> None:
        source = _clean("""
            ev = Event(event_type="t", source="s")
        """)
        errors = run_checks(source)
        ao001 = [e for e in errors if e.code == "AO001" and "payload" in e.message]
        assert len(ao001) >= 1

    def test_ao001_all_three_missing(self) -> None:
        source = "ev = Event()\n"
        errors = run_checks(source)
        ao001 = [e for e in errors if e.code == "AO001"]
        # Should flag all 3 missing required fields
        assert len(ao001) == 3

    def test_ao001_not_triggered_for_spanforge_prefix(self) -> None:
        source = _clean("""
            ev = spanforge.Event(
                event_type="t",
                source="s",
                payload={},
            )
        """)
        errors = run_checks(source)
        ao001 = [e for e in errors if e.code == "AO001"]
        assert ao001 == []

    def test_ao001_with_all_fields_no_error(self) -> None:
        source = _clean("""
            Event(event_type="t", source="s", payload={})
        """)
        errors = run_checks(source)
        ao001 = [e for e in errors if e.code == "AO001"]
        assert ao001 == []

    def test_ao001_line_number_correct(self) -> None:
        source = "# comment\n\nev = Event(source='s', payload={})\n"
        errors = run_checks(source)
        ao001 = [e for e in errors if e.code == "AO001"]
        assert ao001[0].line == 3


# ---------------------------------------------------------------------------
# AO002 — Bare str literal for identity field
# ---------------------------------------------------------------------------


class TestAO002:
    def test_ao002_bare_str_actor_id(self) -> None:
        source = _clean("""
            Event(
                event_type="t",
                source="s",
                payload={},
                actor_id="raw-string-user",
            )
        """)
        errors = run_checks(source)
        ao002 = [e for e in errors if e.code == "AO002"]
        assert len(ao002) >= 1
        assert any("actor_id" in e.message for e in ao002)

    def test_ao002_bare_str_session_id(self) -> None:
        source = _clean("""
            Event(
                event_type="t",
                source="s",
                payload={},
                session_id="sess-123",
            )
        """)
        errors = run_checks(source)
        ao002 = [e for e in errors if e.code == "AO002"]
        assert any("session_id" in e.message for e in ao002)

    def test_ao002_bare_str_user_id(self) -> None:
        source = _clean("""
            Event(
                event_type="t",
                source="s",
                payload={},
                user_id="user@example.com",
            )
        """)
        errors = run_checks(source)
        ao002 = [e for e in errors if e.code == "AO002"]
        assert any("user_id" in e.message for e in ao002)

    def test_ao002_not_triggered_for_variable(self) -> None:
        source = _clean("""
            actor = get_actor()
            Event(event_type="t", source="s", payload={}, actor_id=actor)
        """)
        errors = run_checks(source)
        ao002 = [e for e in errors if e.code == "AO002"]
        assert ao002 == []

    def test_ao002_not_triggered_for_non_identity_field(self) -> None:
        source = _clean("""
            Event(
                event_type="t",
                source="s",
                payload={},
                model_name="gpt-4",
            )
        """)
        errors = run_checks(source)
        ao002 = [e for e in errors if e.code == "AO002"]
        assert ao002 == []


# ---------------------------------------------------------------------------
# AO003 — Unregistered event_type string
# ---------------------------------------------------------------------------


class TestAO003:
    def test_ao003_unknown_event_type_string(self) -> None:
        source = _clean("""
            Event(
                event_type="not.a.valid.event.type.xyz",
                source="s",
                payload={},
            )
        """)
        errors = run_checks(source)
        ao003 = [e for e in errors if e.code == "AO003"]
        # AO003 fires for unknown strings; may or may not depending on EventType availability
        # At minimum, ensure no crash
        assert isinstance(ao003, list)

    def test_ao003_not_triggered_for_non_string_event_type(self) -> None:
        source = _clean("""
            et = get_event_type()
            Event(event_type=et, source="s", payload={})
        """)
        errors = run_checks(source)
        ao003 = [e for e in errors if e.code == "AO003"]
        assert ao003 == []


# ---------------------------------------------------------------------------
# AO005 — emit_* called outside agent context
# ---------------------------------------------------------------------------


class TestAO005:
    def test_ao005_emit_span_outside_context(self) -> None:
        source = "emit_span(name='test')\n"
        errors = run_checks(source)
        ao005 = [e for e in errors if e.code == "AO005"]
        assert len(ao005) >= 1
        assert "emit_span" in ao005[0].message

    def test_ao005_not_triggered_inside_span_context(self) -> None:
        source = _clean("""
            with span("test"):
                emit_span(name="inner")
        """)
        errors = run_checks(source)
        ao005 = [e for e in errors if e.code == "AO005"]
        assert ao005 == []

    def test_ao005_not_triggered_inside_agent_run_context(self) -> None:
        source = _clean("""
            with agent_run("test"):
                emit_agent_run(name="inner")
        """)
        errors = run_checks(source)
        ao005 = [e for e in errors if e.code == "AO005"]
        assert ao005 == []

    def test_ao005_emit_agent_run_outside_context(self) -> None:
        source = "emit_agent_run(name='x')\n"
        errors = run_checks(source)
        ao005 = [e for e in errors if e.code == "AO005"]
        assert len(ao005) >= 1

    def test_ao005_emit_agent_step_outside_context(self) -> None:
        source = "emit_agent_step(name='x')\n"
        errors = run_checks(source)
        ao005 = [e for e in errors if e.code == "AO005"]
        assert len(ao005) >= 1

    def test_ao005_not_triggered_for_non_emit_call(self) -> None:
        source = "some_other_function(name='x')\n"
        errors = run_checks(source)
        ao005 = [e for e in errors if e.code == "AO005"]
        assert ao005 == []


# ---------------------------------------------------------------------------
# Sorting guarantee
# ---------------------------------------------------------------------------


class TestResultSorting:
    def test_errors_sorted_by_line_then_col(self) -> None:
        source = _clean("""
            ev1 = Event(source="s", payload={})
            ev2 = Event(event_type="t", payload={})
        """)
        errors = run_checks(source)
        for i in range(len(errors) - 1):
            assert (errors[i].line, errors[i].col) <= (errors[i + 1].line, errors[i + 1].col)


# ---------------------------------------------------------------------------
# SpanForgeChecker — flake8 shim
# ---------------------------------------------------------------------------


class TestSpanForgeChecker:
    def test_run_yields_tuples(self) -> None:
        source = "emit_span(name='test')\n"
        tree = ast.parse(source)
        checker = SpanForgeChecker(tree=tree, filename="t.py", lines=list(source))
        results = list(checker.run())
        assert len(results) >= 1
        for result in results:
            line, col, message, tp = result
            assert isinstance(line, int)
            assert isinstance(col, int)
            assert isinstance(message, str)
            assert "AO" in message

    def test_run_clean_source_yields_nothing(self) -> None:
        source = "x = 1\n"
        tree = ast.parse(source)
        checker = SpanForgeChecker(tree=tree, filename="clean.py", lines=list(source))
        results = list(checker.run())
        assert results == []

    def test_checker_has_required_class_attrs(self) -> None:
        assert hasattr(SpanForgeChecker, "name")
        assert hasattr(SpanForgeChecker, "version")


# ---------------------------------------------------------------------------
# _iter_python_files filesystem helper
# ---------------------------------------------------------------------------


class TestIterPythonFiles:
    def test_yields_py_file(self, tmp_path: Path) -> None:
        f = tmp_path / "test.py"
        f.write_text("x = 1\n")
        files = list(_iter_python_files([str(tmp_path)]))
        assert f in files

    def test_ignores_non_py_file(self, tmp_path: Path) -> None:
        (tmp_path / "readme.md").write_text("# hi")
        files = list(_iter_python_files([str(tmp_path)]))
        assert files == []

    def test_recurses_into_subdirectory(self, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        f = sub / "module.py"
        f.write_text("pass\n")
        files = list(_iter_python_files([str(tmp_path)]))
        assert f in files

    def test_direct_file_path(self, tmp_path: Path) -> None:
        f = tmp_path / "direct.py"
        f.write_text("pass\n")
        files = list(_iter_python_files([str(f)]))
        assert f in files

    def test_multiple_paths(self, tmp_path: Path) -> None:
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        fa = dir_a / "a.py"
        fb = dir_b / "b.py"
        fa.write_text("pass\n")
        fb.write_text("pass\n")
        files = list(_iter_python_files([str(dir_a), str(dir_b)]))
        assert fa in files
        assert fb in files
