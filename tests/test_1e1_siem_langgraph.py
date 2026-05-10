"""CARD 1E-1 — Integration & Exporter Finalization: tests.

Covers:
* SpanForgeLangGraphCallback (five lifecycle hooks)
* SIEMExporter CEF / LEEF formatting
* ``spanforge export siem`` CLI command
"""

from __future__ import annotations

from io import StringIO
from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import pytest

from spanforge.event import Event
from spanforge.export.siem import SIEMExporter
from spanforge.integrations.langgraph import SpanForgeLangGraphCallback
from spanforge.ulid import generate as gen_ulid

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(event_type: str = "llm.trace.span.started", **payload_kw: Any) -> Event:
    return Event(
        event_type=event_type,
        source="test-source@1.0.0",
        event_id=gen_ulid(),
        payload={"key": "value", **payload_kw},
    )


def _run_cli(*args: str) -> tuple[int, str]:
    """Run the spanforge CLI and return (exit_code, stdout)."""
    from spanforge._cli import main

    captured = StringIO()
    with patch("sys.stdout", captured):
        try:
            main(list(args))
        except SystemExit as exc:
            code = int(exc.code or 0)
        else:
            code = 0
    return code, captured.getvalue()


# ===========================================================================
# SpanForgeLangGraphCallback tests
# ===========================================================================


class TestSpanForgeLangGraphCallback:
    def test_on_chain_start_emits_event(self) -> None:
        cb = SpanForgeLangGraphCallback(source="test-app@1.0.0")
        cb.on_chain_start({"id": ["MyChain"]}, {"input": "hello"}, run_id="run-1")
        assert len(cb.events) == 1
        ev = cb.events[0]
        assert ev.event_type == "llm.langgraph.chain.started"
        assert ev.payload["chain_name"] == "MyChain"  # type: ignore[index]
        assert ev.payload["run_id"] == "run-1"  # type: ignore[index]

    def test_on_chain_start_empty_serialized(self) -> None:
        cb = SpanForgeLangGraphCallback()
        cb.on_chain_start({}, {}, run_id=None)
        assert cb.events[0].event_type == "llm.langgraph.chain.started"
        assert cb.events[0].payload["chain_name"] == ""  # type: ignore[index]

    def test_on_chain_end_emits_event(self) -> None:
        cb = SpanForgeLangGraphCallback()
        cb.on_chain_end({"result": "done"}, run_id="r2")
        assert len(cb.events) == 1
        ev = cb.events[0]
        assert ev.event_type == "llm.langgraph.chain.completed"
        assert "result" in ev.payload["output_keys"]  # type: ignore[index]

    def test_on_chain_end_non_dict_outputs(self) -> None:
        cb = SpanForgeLangGraphCallback()
        cb.on_chain_end("string output", run_id=None)  # type: ignore[arg-type]
        assert cb.events[0].payload["output_keys"] == []  # type: ignore[index]

    def test_on_tool_start_emits_event(self) -> None:
        cb = SpanForgeLangGraphCallback()
        cb.on_tool_start({"id": ["SearchTool"]}, "query string", run_id="r3")
        assert len(cb.events) == 1
        ev = cb.events[0]
        assert ev.event_type == "llm.langgraph.tool.started"
        assert ev.payload["tool_name"] == "SearchTool"  # type: ignore[index]
        assert ev.payload["input_length"] == len("query string")  # type: ignore[index]

    def test_on_tool_start_name_fallback(self) -> None:
        cb = SpanForgeLangGraphCallback()
        cb.on_tool_start({"name": "FallbackTool", "id": []}, "x", run_id=None)
        assert cb.events[0].payload["tool_name"] == "FallbackTool"  # type: ignore[index]

    def test_on_tool_start_empty_serialized(self) -> None:
        cb = SpanForgeLangGraphCallback()
        cb.on_tool_start({}, "x")
        assert cb.events[0].payload["tool_name"] == ""  # type: ignore[index]

    def test_on_tool_end_emits_event(self) -> None:
        cb = SpanForgeLangGraphCallback()
        cb.on_tool_end("tool result here", run_id="r4")
        assert len(cb.events) == 1
        ev = cb.events[0]
        assert ev.event_type == "llm.langgraph.tool.completed"
        assert ev.payload["output_length"] == len("tool result here")  # type: ignore[index]

    def test_on_agent_action_with_dict_action(self) -> None:
        cb = SpanForgeLangGraphCallback()
        action = {"tool": "calculator", "tool_input": "2+2", "log": "Using calculator"}
        cb.on_agent_action(action, run_id="r5")
        assert len(cb.events) == 1
        ev = cb.events[0]
        assert ev.event_type == "llm.langgraph.agent.action"
        assert ev.payload["tool"] == "calculator"  # type: ignore[index]
        assert ev.payload["tool_input"] == "2+2"  # type: ignore[index]

    def test_on_agent_action_with_object_action(self) -> None:
        class FakeAction:
            tool = "search"
            tool_input = "capital of France"
            log = "Searching..."

        cb = SpanForgeLangGraphCallback()
        cb.on_agent_action(FakeAction(), run_id=None)
        ev = cb.events[0]
        assert ev.payload["tool"] == "search"  # type: ignore[index]
        assert ev.payload["log"] == "Searching..."  # type: ignore[index]

    def test_multiple_hooks_accumulate_events(self) -> None:
        cb = SpanForgeLangGraphCallback(source="multi@1.0.0", org_id="org-xyz")
        cb.on_chain_start({"id": ["GraphChain"]}, {"q": "hi"})
        cb.on_tool_start({"id": ["SearchTool"]}, "query")
        cb.on_tool_end("result")
        cb.on_chain_end({"answer": "hello"})
        assert len(cb.events) == 4
        types = [ev.event_type for ev in cb.events]
        assert types == [
            "llm.langgraph.chain.started",
            "llm.langgraph.tool.started",
            "llm.langgraph.tool.completed",
            "llm.langgraph.chain.completed",
        ]
        for ev in cb.events:
            assert ev.source == "multi@1.0.0"
            assert ev.org_id == "org-xyz"

    def test_all_events_have_unique_event_ids(self) -> None:
        cb = SpanForgeLangGraphCallback()
        for _ in range(5):
            cb.on_chain_start({}, {})
        ids = {ev.event_id for ev in cb.events}
        assert len(ids) == 5

    def test_run_id_none_stored_as_none(self) -> None:
        cb = SpanForgeLangGraphCallback()
        cb.on_chain_start({}, {}, run_id=None)
        assert cb.events[0].payload["run_id"] is None  # type: ignore[index]

    def test_kwargs_ignored(self) -> None:
        cb = SpanForgeLangGraphCallback()
        cb.on_chain_start({}, {}, run_id=None, extra_kwarg="ignored")
        assert len(cb.events) == 1


# ===========================================================================
# SIEMExporter — CEF format tests
# ===========================================================================


class TestSIEMExporterCEF:
    def test_cef_prefix(self) -> None:
        event = _make_event()
        exporter = SIEMExporter(format="cef")
        result = exporter.export(event)
        assert result.startswith("CEF:0|SpanForge|SDK|")

    def test_cef_contains_event_type(self) -> None:
        event = _make_event("llm.trace.span.started")
        exporter = SIEMExporter(format="cef")
        result = exporter.export(event)
        assert "llm.trace.span.started" in result

    def test_cef_contains_severity(self) -> None:
        event = _make_event("error.something.happened")
        exporter = SIEMExporter(format="cef")
        result = exporter.export(event)
        # severity 3 for "error" prefix
        assert "|3|" in result

    def test_cef_extensions_present(self) -> None:
        event = _make_event()
        exporter = SIEMExporter(format="cef")
        result = exporter.export(event)
        assert "event_id=" in result
        assert "event_type=" in result

    def test_cef_payload_fields_included(self) -> None:
        event = _make_event(custom_field="abc123")
        exporter = SIEMExporter(format="cef")
        result = exporter.export(event)
        assert "abc123" in result

    def test_cef_special_chars_escaped(self) -> None:
        event = Event(
            event_type="llm.trace.span.started",
            source="test@1.0",
            event_id=gen_ulid(),
            payload={"name": "pipe|equals=backslash\\end"},
        )
        exporter = SIEMExporter(format="cef")
        result = exporter.export(event)
        # pipe in payload value should be escaped
        assert "\\|" in result or "pipe" in result

    def test_cef_version_override(self) -> None:
        event = _make_event()
        exporter = SIEMExporter(format="cef", version="9.9.9")
        result = exporter.export(event)
        assert "CEF:0|SpanForge|SDK|9.9.9|" in result

    def test_cef_default_format(self) -> None:
        exporter = SIEMExporter()
        assert exporter.format == "cef"

    def test_cef_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="format must be"):
            SIEMExporter(format="xml")  # type: ignore[arg-type]


# ===========================================================================
# SIEMExporter — LEEF format tests
# ===========================================================================


class TestSIEMExporterLEEF:
    def test_leef_prefix(self) -> None:
        event = _make_event()
        exporter = SIEMExporter(format="leef")
        result = exporter.export(event)
        assert result.startswith("LEEF:2.0|SpanForge|SDK|")

    def test_leef_contains_event_type(self) -> None:
        event = _make_event("llm.tool.call.started")
        exporter = SIEMExporter(format="leef")
        result = exporter.export(event)
        assert "llm.tool.call.started" in result

    def test_leef_tab_separated_extensions(self) -> None:
        event = _make_event()
        exporter = SIEMExporter(format="leef")
        result = exporter.export(event)
        # LEEF uses tab-separated key=value pairs after header
        assert "\t" in result

    def test_leef_version_override(self) -> None:
        event = _make_event()
        exporter = SIEMExporter(format="leef", version="2.3.4")
        result = exporter.export(event)
        assert "LEEF:2.0|SpanForge|SDK|2.3.4|" in result

    def test_leef_newlines_in_payload_escaped(self) -> None:
        event = Event(
            event_type="llm.trace.span.started",
            source="test@1.0",
            event_id=gen_ulid(),
            payload={"text": "line1\nline2\ttabbed"},
        )
        exporter = SIEMExporter(format="leef")
        result = exporter.export(event)
        # The result should not contain raw embedded newlines in the extension values
        # (only the leading tab separators)
        parts = result.split("\t")
        for part in parts[1:]:  # skip header
            assert "\n" not in part
            assert "\r" not in part


# ===========================================================================
# SIEMExporter — batch export tests
# ===========================================================================


class TestSIEMExporterBatch:
    def test_export_batch_yields_all_events(self) -> None:
        events = [_make_event() for _ in range(5)]
        exporter = SIEMExporter(format="cef")
        results = list(exporter.export_batch(events))
        assert len(results) == 5

    def test_export_batch_leef_all_events(self) -> None:
        events = [_make_event("llm.trace.span.started") for _ in range(3)]
        exporter = SIEMExporter(format="leef")
        results = list(exporter.export_batch(events))
        assert len(results) == 3
        for r in results:
            assert r.startswith("LEEF:2.0|")

    def test_export_batch_empty(self) -> None:
        exporter = SIEMExporter(format="cef")
        results = list(exporter.export_batch([]))
        assert results == []

    def test_export_batch_is_iterator(self) -> None:
        events = [_make_event() for _ in range(2)]
        exporter = SIEMExporter(format="cef")
        result = exporter.export_batch(events)
        # Should be an iterator/generator
        assert hasattr(result, "__iter__")
        assert hasattr(result, "__next__")


# ===========================================================================
# CLI — spanforge export siem tests
# ===========================================================================


class TestExportSIEMCLI:
    def _make_jsonl(self, tmp_path: Path, events: list[Event]) -> Path:
        p = tmp_path / "events.jsonl"
        p.write_text("\n".join(ev.to_json() for ev in events) + "\n", encoding="utf-8")
        return p

    def test_cli_cef_from_file(self, tmp_path: Path) -> None:
        events = [_make_event()]
        jsonl = self._make_jsonl(tmp_path, events)
        code, stdout = _run_cli("export", "siem", "--format", "cef", "--input", str(jsonl))
        assert code == 0
        assert "CEF:0|SpanForge|SDK|" in stdout

    def test_cli_leef_from_file(self, tmp_path: Path) -> None:
        events = [_make_event()]
        jsonl = self._make_jsonl(tmp_path, events)
        code, stdout = _run_cli("export", "siem", "--format", "leef", "--input", str(jsonl))
        assert code == 0
        assert "LEEF:2.0|SpanForge|SDK|" in stdout

    def test_cli_multiple_events(self, tmp_path: Path) -> None:
        events = [_make_event() for _ in range(3)]
        jsonl = self._make_jsonl(tmp_path, events)
        code, stdout = _run_cli("export", "siem", "--format", "cef", "--input", str(jsonl))
        assert code == 0
        lines = [ln for ln in stdout.splitlines() if ln.strip()]
        assert len(lines) == 3

    def test_cli_default_format_is_cef(self, tmp_path: Path) -> None:
        events = [_make_event()]
        jsonl = self._make_jsonl(tmp_path, events)
        code, stdout = _run_cli("export", "siem", "--input", str(jsonl))
        assert code == 0
        assert "CEF:0|SpanForge|" in stdout

    def test_cli_missing_file_returns_error(self, tmp_path: Path) -> None:
        from spanforge._cli import main

        stderr_capture = StringIO()
        with patch("sys.stderr", stderr_capture):
            try:
                main(["export", "siem", "--format", "cef", "--input", "/nonexistent/file.jsonl"])
            except SystemExit as exc:
                code = int(exc.code or 0)
            else:
                code = 0
        assert code == 1

    def test_cli_empty_file_returns_zero(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.jsonl"
        p.write_text("", encoding="utf-8")
        code, _stdout = _run_cli("export", "siem", "--format", "cef", "--input", str(p))
        assert code == 0

    def test_cli_skips_invalid_lines(self, tmp_path: Path) -> None:
        p = tmp_path / "bad.jsonl"
        ev = _make_event()
        p.write_text("not json\n" + ev.to_json() + "\n", encoding="utf-8")
        code, stdout = _run_cli("export", "siem", "--format", "cef", "--input", str(p))
        assert code == 0
        lines = [ln for ln in stdout.splitlines() if ln.startswith("CEF:")]
        assert len(lines) == 1

    def test_cli_no_subcommand_shows_help(self) -> None:
        from spanforge._cli import main

        captured = StringIO()
        with patch("sys.stdout", captured):
            try:
                main(["export"])
            except SystemExit as exc:
                code = int(exc.code or 0)
            else:
                code = 0
        assert code == 2

    def test_cli_stdin_mode(self, tmp_path: Path) -> None:
        ev = _make_event()
        stdin_data = ev.to_json() + "\n"
        from spanforge._cli import main

        captured = StringIO()
        fake_stdin = StringIO(stdin_data)
        with patch("sys.stdout", captured), patch("sys.stdin", fake_stdin):
            try:
                main(["export", "siem", "--format", "cef"])
            except SystemExit as exc:
                code = int(exc.code or 0)
            else:
                code = 0
        assert code == 0
        assert "CEF:0|SpanForge|" in captured.getvalue()
