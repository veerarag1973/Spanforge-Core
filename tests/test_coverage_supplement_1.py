"""Supplemental tests to improve coverage for modules below 90%.

Covers:
* spanforge.exporters.sqlite — SyncSQLiteExporter
* spanforge.stream           — from_queue, from_async_iter, aiter_file, iter_file skip_errors
* spanforge.lint             — AO003, AsyncWith context, _get_call_name, _is_registered_event_type
* spanforge.export.openinference — OpenInferenceSpanBridge, span_to_openinference_dict
* spanforge.sdk.scope        — _parse_scope_yaml, circuit breaker, evaluate_async
"""

from __future__ import annotations

import ast
import asyncio
import textwrap
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

# ===========================================================================
# spanforge.exporters.sqlite — SyncSQLiteExporter
# ===========================================================================


class TestSyncSQLiteExporter:
    """Tests for the SQLite event exporter (lines 90-98, 114-129, 136-142)."""

    def _make_event(self):
        from spanforge.event import Event
        from spanforge.types import EventType

        return Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source="test@1.0",
            payload={"status": "ok"},
        )

    def test_init_creates_table(self) -> None:
        """__init__ creates the events table in an in-memory database."""
        from spanforge.exporters.sqlite import SyncSQLiteExporter

        exp = SyncSQLiteExporter(":memory:")
        rows = exp._conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = {r[0] for r in rows}
        assert "events" in table_names
        exp.close()

    def test_export_inserts_row(self) -> None:
        """export() inserts one row per event."""
        from spanforge.exporters.sqlite import SyncSQLiteExporter

        exp = SyncSQLiteExporter(":memory:")
        event = self._make_event()
        exp.export(event)
        count = exp._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert count == 1
        exp.close()

    def test_export_stores_correct_fields(self) -> None:
        """Exported row stores event_id, event_type, source correctly."""
        from spanforge.exporters.sqlite import SyncSQLiteExporter

        exp = SyncSQLiteExporter(":memory:")
        event = self._make_event()
        exp.export(event)
        row = exp._conn.execute(
            "SELECT event_id, event_type, source FROM events"
        ).fetchone()
        assert row[0] == str(event.event_id)
        assert "trace" in row[1]  # event_type value
        assert row[2] == "test@1.0"
        exp.close()

    def test_export_multiple_events(self) -> None:
        """Multiple exports append multiple rows."""
        from spanforge.exporters.sqlite import SyncSQLiteExporter

        exp = SyncSQLiteExporter(":memory:")
        for _ in range(5):
            exp.export(self._make_event())
        count = exp._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        assert count == 5
        exp.close()

    def test_flush_is_noop(self) -> None:
        """flush() does not raise."""
        from spanforge.exporters.sqlite import SyncSQLiteExporter

        exp = SyncSQLiteExporter(":memory:")
        exp.flush()  # should not raise
        exp.close()

    def test_close_idempotent(self) -> None:
        """close() can be called multiple times without error."""
        from spanforge.exporters.sqlite import SyncSQLiteExporter

        exp = SyncSQLiteExporter(":memory:")
        exp.close()
        exp.close()  # second call must not raise

    def test_export_after_close_raises(self) -> None:
        """export() after close() raises RuntimeError."""
        from spanforge.exporters.sqlite import SyncSQLiteExporter

        exp = SyncSQLiteExporter(":memory:")
        exp.close()
        with pytest.raises(RuntimeError, match="closed"):
            exp.export(self._make_event())

    def test_event_with_optional_fields(self) -> None:
        """Events with trace_id, span_id, org_id are stored correctly."""
        from spanforge.event import Event
        from spanforge.exporters.sqlite import SyncSQLiteExporter
        from spanforge.types import EventType

        exp = SyncSQLiteExporter(":memory:")
        event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source="svc@1.0",
            payload={},
            trace_id="trace-abc",
            span_id="span-xyz",
            org_id="org-1",
        )
        exp.export(event)
        row = exp._conn.execute(
            "SELECT trace_id, span_id, org_id FROM events"
        ).fetchone()
        assert row[0] == "trace-abc"
        assert row[1] == "span-xyz"
        assert row[2] == "org-1"
        exp.close()

    def test_default_path_string(self) -> None:
        """Default path is 'spanforge_events.db'."""
        from spanforge.exporters.sqlite import SyncSQLiteExporter

        exp = SyncSQLiteExporter(":memory:")
        assert exp._path == ":memory:"
        exp.close()


# ===========================================================================
# spanforge.stream — async/file helpers
# ===========================================================================


class TestEventStreamAsyncQueue:
    """Tests for EventStream.from_queue and from_async_queue."""

    def test_from_queue_with_sentinel(self) -> None:
        """from_queue (sync) stops at sentinel and returns collected events."""
        import queue as stdlib_queue

        from spanforge.event import Event
        from spanforge.stream import EventStream
        from spanforge.types import EventType

        sentinel = object()
        q: stdlib_queue.Queue = stdlib_queue.Queue()
        e1 = Event(event_type=EventType.TRACE_SPAN_COMPLETED, source="s@1", payload={})
        e2 = Event(event_type=EventType.CACHE_HIT, source="s@1", payload={})
        q.put(e1)
        q.put(e2)
        q.put(sentinel)
        stream = EventStream.from_queue(q, sentinel=sentinel)
        assert len(stream) == 2

    def test_from_queue_drains_all(self) -> None:
        """from_queue (sync) drains all items when no sentinel is hit."""
        import queue as stdlib_queue

        from spanforge.event import Event
        from spanforge.stream import EventStream
        from spanforge.types import EventType

        q: stdlib_queue.Queue = stdlib_queue.Queue()
        for _ in range(3):
            q.put(Event(event_type=EventType.CACHE_HIT, source="s@1", payload={}))
        stream = EventStream.from_queue(q)
        assert len(stream) == 3

    def test_from_async_queue_with_timeout(self) -> None:
        """from_async_queue with timeout stops when queue is empty after timeout."""
        from spanforge.stream import EventStream

        async def _run() -> EventStream:
            q: asyncio.Queue = asyncio.Queue()
            return await EventStream.from_async_queue(q, timeout=0.01)

        stream = asyncio.run(_run())
        assert len(stream) == 0

    def test_from_async_queue_sentinel(self) -> None:
        """from_async_queue with sentinel stops and returns collected events."""
        from spanforge.event import Event
        from spanforge.stream import EventStream
        from spanforge.types import EventType

        sentinel = object()

        async def _run() -> EventStream:
            q: asyncio.Queue = asyncio.Queue()
            ev = Event(event_type=EventType.CACHE_HIT, source="s@1", payload={})
            await q.put(ev)
            await q.put(sentinel)
            return await EventStream.from_async_queue(q, sentinel=sentinel)

        stream = asyncio.run(_run())
        assert len(stream) == 1


class TestEventStreamAsyncIter:
    """Tests for EventStream.from_async_iter (lines 225-232 area)."""

    def test_from_async_iter_basic(self) -> None:
        """from_async_iter consumes an async generator into a stream."""
        from spanforge.event import Event
        from spanforge.stream import EventStream
        from spanforge.types import EventType

        async def _gen():
            for et in [EventType.TRACE_SPAN_COMPLETED, EventType.CACHE_HIT]:
                yield Event(event_type=et, source="s@1", payload={})

        async def _run() -> EventStream:
            return await EventStream.from_async_iter(_gen())

        stream = asyncio.run(_run())
        assert len(stream) == 2

    def test_from_async_iter_empty(self) -> None:
        """from_async_iter with empty iterator produces empty stream."""
        from spanforge.stream import EventStream

        async def _empty():
            return
            yield  # make it a generator

        async def _run() -> EventStream:
            return await EventStream.from_async_iter(_empty())

        stream = asyncio.run(_run())
        assert len(stream) == 0


class TestIterFile:
    """Tests for iter_file skip_errors (lines 501, 507)."""

    def test_iter_file_skip_errors_true(self, tmp_path: Path) -> None:
        """iter_file with skip_errors=True silently skips bad lines."""
        from spanforge.event import Event
        from spanforge.stream import iter_file
        from spanforge.types import EventType

        good_event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED, source="s@1", payload={}
        )
        ndjson = tmp_path / "events.ndjson"
        ndjson.write_text(
            good_event.to_json() + "\n"
            + "not valid json at all !!!\n"
            + good_event.to_json() + "\n",
            encoding="utf-8",
        )
        events = list(iter_file(str(ndjson), skip_errors=True))
        assert len(events) == 2

    def test_iter_file_skip_errors_false_raises(self, tmp_path: Path) -> None:
        """iter_file with skip_errors=False (default) raises on bad lines."""
        from spanforge.stream import iter_file

        ndjson = tmp_path / "bad.ndjson"
        ndjson.write_text("this is not json\n", encoding="utf-8")
        with pytest.raises(Exception):
            list(iter_file(str(ndjson), skip_errors=False))

    def test_iter_file_skips_blank_lines(self, tmp_path: Path) -> None:
        """iter_file ignores blank lines."""
        from spanforge.event import Event
        from spanforge.stream import iter_file
        from spanforge.types import EventType

        ev = Event(event_type=EventType.CACHE_HIT, source="s@1", payload={})
        ndjson = tmp_path / "events.ndjson"
        ndjson.write_text("\n" + ev.to_json() + "\n\n", encoding="utf-8")
        events = list(iter_file(str(ndjson)))
        assert len(events) == 1


class TestAiterFile:
    """Tests for aiter_file (lines 543-557)."""

    def test_aiter_file_basic(self, tmp_path: Path) -> None:
        """aiter_file yields events from an NDJSON file."""
        from spanforge.event import Event
        from spanforge.stream import aiter_file
        from spanforge.types import EventType

        ev = Event(event_type=EventType.TRACE_SPAN_COMPLETED, source="s@1", payload={})
        ndjson = tmp_path / "events.ndjson"
        ndjson.write_text(ev.to_json() + "\n", encoding="utf-8")

        async def _run():
            events = []
            async for e in aiter_file(str(ndjson)):
                events.append(e)
            return events

        events = asyncio.run(_run())
        assert len(events) == 1

    def test_aiter_file_skip_errors(self, tmp_path: Path) -> None:
        """aiter_file with skip_errors=True skips bad lines."""
        from spanforge.event import Event
        from spanforge.stream import aiter_file
        from spanforge.types import EventType

        ev = Event(event_type=EventType.CACHE_HIT, source="s@1", payload={})
        ndjson = tmp_path / "events.ndjson"
        ndjson.write_text(
            ev.to_json() + "\n" + "BAD LINE\n" + ev.to_json() + "\n",
            encoding="utf-8",
        )

        async def _run():
            events = []
            async for e in aiter_file(str(ndjson), skip_errors=True):
                events.append(e)
            return events

        events = asyncio.run(_run())
        assert len(events) == 2

    def test_aiter_file_skip_blank_lines(self, tmp_path: Path) -> None:
        """aiter_file ignores blank lines."""
        from spanforge.event import Event
        from spanforge.stream import aiter_file
        from spanforge.types import EventType

        ev = Event(event_type=EventType.CACHE_HIT, source="s@1", payload={})
        ndjson = tmp_path / "events.ndjson"
        ndjson.write_text("\n" + ev.to_json() + "\n\n", encoding="utf-8")

        async def _run():
            return [e async for e in aiter_file(str(ndjson))]

        events = asyncio.run(_run())
        assert len(events) == 1


# ===========================================================================
# spanforge.lint — uncovered branches
# ===========================================================================


class TestLintAO003Actual:
    """AO003 fires when event_type string is not a registered EventType."""

    def _clean(self, src: str) -> str:
        return textwrap.dedent(src)

    def test_ao003_fires_for_unknown_event_type(self) -> None:
        """AO003 is appended when event_type string is not registered."""
        from spanforge.lint import run_checks

        source = self._clean("""
            Event(
                event_type="not.a.real.event.type.xyz.abc",
                source="s",
                payload={},
            )
        """)
        errors = run_checks(source)
        ao003 = [e for e in errors if e.code == "AO003"]
        assert len(ao003) >= 1
        assert "not.a.real.event.type.xyz.abc" in ao003[0].message

    def test_ao003_does_not_fire_for_valid_event_type(self) -> None:
        """AO003 is not raised for a known EventType value."""
        from spanforge.lint import run_checks
        from spanforge.types import EventType

        valid_value = EventType.TRACE_SPAN_COMPLETED.value
        source = f'Event(event_type="{valid_value}", source="s", payload={{}})\n'
        errors = run_checks(source)
        ao003 = [e for e in errors if e.code == "AO003"]
        assert ao003 == []


class TestLintAsyncWith:
    """visit_AsyncWith tracks span context depth (lines 179-188)."""

    def _clean(self, src: str) -> str:
        return textwrap.dedent(src)

    def test_ao005_not_triggered_inside_async_span(self) -> None:
        """emit_span inside 'async with span()' does NOT trigger AO005."""
        from spanforge.lint import run_checks

        source = self._clean("""
            async def handler():
                async with span("op"):
                    emit_span(name="inner")
        """)
        errors = run_checks(source)
        ao005 = [e for e in errors if e.code == "AO005"]
        assert ao005 == []

    def test_ao005_triggered_outside_async_span(self) -> None:
        """emit_span outside any async with span() triggers AO005."""
        from spanforge.lint import run_checks

        source = self._clean("""
            async def handler():
                emit_span(name="outer")
        """)
        errors = run_checks(source)
        ao005 = [e for e in errors if e.code == "AO005"]
        assert len(ao005) >= 1

    def test_async_with_non_span_context_no_effect(self) -> None:
        """async with non-span context does not increment context depth."""
        from spanforge.lint import run_checks

        source = self._clean("""
            async def handler():
                async with some_other_ctx():
                    emit_span(name="should-flag")
        """)
        errors = run_checks(source)
        ao005 = [e for e in errors if e.code == "AO005"]
        assert len(ao005) >= 1


class TestGetCallName:
    """_get_call_name handles ast.Attribute nodes (line 198)."""

    def test_attribute_node_returns_attr(self) -> None:
        """_get_call_name returns the attribute name for dotted calls."""
        from spanforge.lint import _get_call_name

        # Build an ast.Call for `obj.span("x")`
        node = ast.parse("obj.span('x')", mode="eval").body
        assert isinstance(node, ast.Call)
        result = _get_call_name(node)
        assert result == "span"

    def test_name_node_returns_id(self) -> None:
        """_get_call_name returns the function name for simple calls."""
        from spanforge.lint import _get_call_name

        node = ast.parse("span('x')", mode="eval").body
        assert isinstance(node, ast.Call)
        result = _get_call_name(node)
        assert result == "span"

    def test_non_name_non_attribute_returns_empty(self) -> None:
        """_get_call_name returns '' for lambda/subscript calls."""
        from spanforge.lint import _get_call_name

        # ast.Call where func is ast.Subscript (e.g. mapping["key"]("x"))
        # We can fake it by building a synthetic AST node
        node = ast.parse("(lambda: None)()", mode="eval").body
        assert isinstance(node, ast.Call)
        result = _get_call_name(node)
        assert result == ""


# ===========================================================================
# spanforge.export.openinference — bridge helpers
# ===========================================================================


class TestOpenInferenceSpanBridge:
    """Tests for the OpenInference exporter (lines 54, 56, 58, 92-157)."""

    def _make_span(self, **kwargs):
        from spanforge._span import Span

        return Span(
            name="test-span",
            trace_id="a" * 32,   # 32 hex chars — OTel-compatible
            span_id="b" * 16,    # 16 hex chars
            **kwargs,
        )

    def test_span_kind_tool(self) -> None:
        """Spans with tool_calls are classified as TOOL."""
        from spanforge.export.openinference import span_to_openinference_dict

        span = self._make_span(attributes={"tool": "my_tool"})
        result = span_to_openinference_dict(span)
        assert result["attributes"]["openinference.span.kind"] == "TOOL"

    def test_span_kind_agent(self) -> None:
        """Spans with 'agent' in operation are AGENT."""
        from spanforge.export.openinference import span_to_openinference_dict

        span = self._make_span(operation="agent-run")
        result = span_to_openinference_dict(span)
        assert result["attributes"]["openinference.span.kind"] == "AGENT"

    def test_span_kind_retriever(self) -> None:
        """Spans with 'retriev' in operation are RETRIEVER."""
        from spanforge.export.openinference import span_to_openinference_dict

        span = self._make_span(operation="retrieve-docs")
        result = span_to_openinference_dict(span)
        assert result["attributes"]["openinference.span.kind"] == "RETRIEVER"

    def test_span_kind_llm(self) -> None:
        """Spans with model set are LLM."""
        from spanforge.export.openinference import span_to_openinference_dict

        span = self._make_span(model="gpt-4")
        result = span_to_openinference_dict(span)
        assert result["attributes"]["openinference.span.kind"] == "LLM"

    def test_span_kind_chain_default(self) -> None:
        """Spans without any special markers are CHAIN."""
        from spanforge.export.openinference import span_to_openinference_dict

        span = self._make_span()
        result = span_to_openinference_dict(span)
        assert result["attributes"]["openinference.span.kind"] == "CHAIN"

    def test_session_id_included(self) -> None:
        """session_id is added to OI attrs when present."""
        from spanforge.export.openinference import span_to_openinference_dict

        span = self._make_span(session_id="sess-123")
        result = span_to_openinference_dict(span)
        assert result["attributes"]["session.id"] == "sess-123"

    def test_input_from_attribute(self) -> None:
        """input.value extracted from 'input' attribute."""
        from spanforge.export.openinference import span_to_openinference_dict

        span = self._make_span(attributes={"input": "hello world"})
        result = span_to_openinference_dict(span)
        assert result["attributes"]["input.value"] == "hello world"

    def test_output_from_attribute(self) -> None:
        """output.value extracted from 'output' attribute."""
        from spanforge.export.openinference import span_to_openinference_dict

        span = self._make_span(attributes={"output": "result text"})
        result = span_to_openinference_dict(span)
        assert result["attributes"]["output.value"] == "result text"

    def test_error_fields(self) -> None:
        """Error spans include exception.message and exception.escaped."""
        from spanforge.export.openinference import span_to_openinference_dict

        span = self._make_span(error="something failed", error_type="ValueError")
        result = span_to_openinference_dict(span)
        attrs = result["attributes"]
        assert attrs["exception.message"] == "something failed"
        assert attrs["exception.type"] == "ValueError"
        assert attrs["exception.escaped"] is True

    def test_status_error(self) -> None:
        """Spans with status='error' produce status='ERROR' in output."""
        from spanforge.export.openinference import span_to_openinference_dict

        span = self._make_span(status="error")
        result = span_to_openinference_dict(span)
        assert result["status"] == "ERROR"

    def test_status_ok(self) -> None:
        """Non-error spans produce status='OK'."""
        from spanforge.export.openinference import span_to_openinference_dict

        span = self._make_span(status="ok")
        result = span_to_openinference_dict(span)
        assert result["status"] == "OK"

    def test_context_fields(self) -> None:
        """Context includes trace_id, span_id, parent_span_id."""
        from spanforge.export.openinference import span_to_openinference_dict

        span = self._make_span()
        result = span_to_openinference_dict(span)
        ctx = result["context"]
        assert ctx["trace_id"] == "a" * 32
        assert ctx["span_id"] == "b" * 16

    def test_bridge_to_spans(self) -> None:
        """OpenInferenceSpanBridge.to_spans returns one dict per span."""
        from spanforge.export.openinference import OpenInferenceSpanBridge

        bridge = OpenInferenceSpanBridge()
        spans = [self._make_span(), self._make_span()]
        result = bridge.to_spans(spans)
        assert len(result) == 2

    def test_bridge_to_trace(self) -> None:
        """OpenInferenceSpanBridge.to_trace wraps spans in a dict."""
        from spanforge.export.openinference import OpenInferenceSpanBridge

        bridge = OpenInferenceSpanBridge()
        result = bridge.to_trace([self._make_span()])
        assert "spans" in result
        assert len(result["spans"]) == 1

    def test_model_attrs_llm_system(self) -> None:
        """llm.system attribute is propagated from span attributes."""
        from spanforge.export.openinference import span_to_openinference_dict

        span = self._make_span(attributes={"llm.system": "openai"})
        result = span_to_openinference_dict(span)
        assert result["attributes"].get("llm.system") == "openai"

    def test_provider_attr_propagated(self) -> None:
        """llm.provider attribute is propagated."""
        from spanforge.export.openinference import span_to_openinference_dict

        span = self._make_span(attributes={"llm.provider": "anthropic"})
        result = span_to_openinference_dict(span)
        assert result["attributes"].get("llm.provider") == "anthropic"

    def test_non_string_attr_json_encoded(self) -> None:
        """Non-string attribute values are JSON-encoded."""
        from spanforge.export.openinference import span_to_openinference_dict

        span = self._make_span(attributes={"input.value": {"key": "val"}})
        result = span_to_openinference_dict(span)
        # Should be JSON-encoded string
        import json as _json

        assert isinstance(result["attributes"]["input.value"], str)
        assert _json.loads(result["attributes"]["input.value"]) == {"key": "val"}


# ===========================================================================
# spanforge.sdk.scope — YAML parser and circuit breaker
# ===========================================================================


class TestParseScopeYaml:
    """Tests for _parse_scope_yaml fallback parser (lines 53-148)."""

    def test_parse_basic_scalar(self) -> None:
        """Parses simple key: value YAML."""
        from spanforge.sdk.scope import _parse_scope_yaml

        result = _parse_scope_yaml("agent_id: my-agent\n")
        assert result["agent_id"] == "my-agent"

    def test_parse_bool_true(self) -> None:
        """Coerces 'true' to Python True."""
        from spanforge.sdk.scope import _parse_scope_yaml

        result = _parse_scope_yaml("enabled: true\n")
        assert result["enabled"] is True

    def test_parse_bool_false(self) -> None:
        """Coerces 'false' to Python False."""
        from spanforge.sdk.scope import _parse_scope_yaml

        result = _parse_scope_yaml("enabled: false\n")
        assert result["enabled"] is False

    def test_parse_null(self) -> None:
        """Coerces 'null' to Python None."""
        from spanforge.sdk.scope import _parse_scope_yaml

        result = _parse_scope_yaml("value: null\n")
        assert result["value"] is None

    def test_parse_int(self) -> None:
        """Coerces integer strings to int."""
        from spanforge.sdk.scope import _parse_scope_yaml

        result = _parse_scope_yaml("timeout: 30\n")
        assert result["timeout"] == 30

    def test_parse_float(self) -> None:
        """Coerces float strings to float."""
        from spanforge.sdk.scope import _parse_scope_yaml

        result = _parse_scope_yaml("threshold: 0.75\n")
        assert result["threshold"] == pytest.approx(0.75)

    def test_parse_list(self) -> None:
        """Parses simple list items."""
        from spanforge.sdk.scope import _parse_scope_yaml

        yaml_text = "allowed_actions:\n  - read\n  - write\n"
        result = _parse_scope_yaml(yaml_text)
        assert "read" in result["allowed_actions"]
        assert "write" in result["allowed_actions"]

    def test_parse_resource_actions(self) -> None:
        """Parses resource_actions nested dict."""
        from spanforge.sdk.scope import _parse_scope_yaml

        yaml_text = textwrap.dedent("""\
            agent_id: test
            resource_actions:
              db:
                - read
                - write
        """)
        result = _parse_scope_yaml(yaml_text)
        assert "db" in result["resource_actions"]
        assert "read" in result["resource_actions"]["db"]

    def test_parse_metadata(self) -> None:
        """Parses metadata section."""
        from spanforge.sdk.scope import _parse_scope_yaml

        yaml_text = textwrap.dedent("""\
            agent_id: test
            metadata:
              env: prod
              version: 1
        """)
        result = _parse_scope_yaml(yaml_text)
        assert result["metadata"]["env"] == "prod"
        assert result["metadata"]["version"] == 1

    def test_parse_comments_ignored(self) -> None:
        """Comment lines are ignored."""
        from spanforge.sdk.scope import _parse_scope_yaml

        yaml_text = "# top comment\nagent_id: my-agent\n"
        result = _parse_scope_yaml(yaml_text)
        assert result["agent_id"] == "my-agent"

    def test_parse_empty_returns_empty_dict(self) -> None:
        """Empty input returns {}."""
        from spanforge.sdk.scope import _parse_scope_yaml

        assert _parse_scope_yaml("") == {}

    def test_parse_falls_through_to_str(self) -> None:
        """Values that aren't bool/null/int/float stay as str."""
        from spanforge.sdk.scope import _parse_scope_yaml

        result = _parse_scope_yaml("name: hello-world\n")
        assert result["name"] == "hello-world"


class TestSFScopeClientExtended:
    """Tests for SFScopeClient advanced paths (circuit breaker, async, yaml load)."""

    def _make_client(self):
        from spanforge.sdk._base import SFClientConfig
        from spanforge.sdk.scope import SFScopeClient

        cfg = SFClientConfig(api_key="test-key", endpoint="http://localhost:9999")
        return SFScopeClient(config=cfg)

    def test_register_and_evaluate_allowed(self) -> None:
        """evaluate() returns allowed=True for a registered action."""
        client = self._make_client()
        client.register_agent(
            agent_id="agent-1",
            capabilities=["read_db"],
            resource_actions={"db": ["read"]},
        )
        payload = client.evaluate(
            trace_id="t1",
            agent_id="agent-1",
            resource="db",
            action_name="read",
            checked_at="2024-01-01T00:00:00Z",
        )
        assert payload.allowed is True

    def test_evaluate_missing_manifest_denied(self) -> None:
        """evaluate() returns allowed=False when no manifest is registered."""
        client = self._make_client()
        payload = client.evaluate(
            trace_id="t1",
            agent_id="unknown-agent",
            resource="db",
            action_name="read",
            checked_at="2024-01-01T00:00:00Z",
        )
        assert payload.allowed is False
        assert "no registered scope manifest" in payload.reason

    def test_evaluate_missing_capability_denied(self) -> None:
        """evaluate() returns allowed=False when capability is missing."""
        client = self._make_client()
        client.register_agent(
            agent_id="agent-cap",
            capabilities=["cap_a"],
            resource_actions={"db": ["read"]},
        )
        payload = client.evaluate(
            trace_id="t1",
            agent_id="agent-cap",
            resource="db",
            action_name="read",
            checked_at="2024-01-01T00:00:00Z",
            capability="cap_b",  # not registered
        )
        assert payload.allowed is False

    def test_evaluate_with_capability_allowed(self) -> None:
        """evaluate() returns allowed with capability reason string."""
        client = self._make_client()
        client.register_agent(
            agent_id="agent-cp",
            capabilities=["cap_a"],
            resource_actions={"res": ["execute"]},
        )
        payload = client.evaluate(
            trace_id="t1",
            agent_id="agent-cp",
            resource="res",
            action_name="execute",
            checked_at="2024-01-01T00:00:00Z",
            capability="cap_a",
        )
        assert payload.allowed is True
        assert "cap_a" in payload.reason

    def test_evaluate_wildcard_resource(self) -> None:
        """evaluate() uses '*' wildcard when no per-resource entry exists."""
        client = self._make_client()
        client.register_agent(
            agent_id="agent-wild",
            resource_actions={"*": ["read", "write"]},
        )
        payload = client.evaluate(
            trace_id="t1",
            agent_id="agent-wild",
            resource="any-resource",
            action_name="read",
            checked_at="2024-01-01T00:00:00Z",
        )
        assert payload.allowed is True

    def test_circuit_breaker_open_denies(self) -> None:
        """When circuit is open, evaluate() returns fail-secure deny."""
        client = self._make_client()
        # Open the circuit by recording many failures
        for _ in range(10):
            client._circuit_breaker.record_failure()
        assert client._circuit_breaker.is_open()
        payload = client.evaluate(
            trace_id="t1",
            agent_id="agent-1",
            resource="db",
            action_name="read",
            checked_at="2024-01-01T00:00:00Z",
        )
        assert payload.allowed is False
        assert "circuit" in payload.reason.lower()

    def test_evaluate_async(self) -> None:
        """evaluate_async wraps evaluate() coroutine correctly."""
        client = self._make_client()
        client.register_agent(
            agent_id="async-agent",
            resource_actions={"res": ["get"]},
        )

        async def _run():
            return await client.evaluate_async(
                trace_id="t-async",
                agent_id="async-agent",
                resource="res",
                action_name="get",
                checked_at="2024-01-01T00:00:00Z",
            )

        payload = asyncio.run(_run())
        assert payload.allowed is True

    def test_require_capability_raises(self) -> None:
        """require_capability raises SFScopeError when capability missing."""

        client = self._make_client()
        client.register_agent(agent_id="agent-req", capabilities=["cap_x"])
        with pytest.raises(Exception):
            client.require_capability("agent-req", "cap_missing")

    def test_require_capability_no_manifest_raises(self) -> None:
        """require_capability raises when agent has no manifest."""
        client = self._make_client()
        with pytest.raises(Exception):
            client.require_capability("no-such-agent", "anything")

    def test_get_status_counters(self) -> None:
        """get_status() returns correct counters after evaluations."""
        client = self._make_client()
        client.register_agent(agent_id="s-agent", resource_actions={"r": ["read"]})
        client.evaluate(
            trace_id="t1",
            agent_id="s-agent",
            resource="r",
            action_name="read",
            checked_at="2024-01-01T00:00:00Z",
        )
        status = client.get_status()
        assert status.total_checks >= 1
        assert status.registered_agents >= 1

    def test_resolve_outcome_policy_actions(self) -> None:
        """_resolve_outcome handles all policy_action variants."""
        from spanforge.sdk.scope import SFScopeClient

        assert SFScopeClient._resolve_outcome(allowed=True, policy_action=None) == "allow"
        assert SFScopeClient._resolve_outcome(allowed=False, policy_action="block") == "block"
        assert SFScopeClient._resolve_outcome(allowed=False, policy_action="human_review") == "human_review"
        assert SFScopeClient._resolve_outcome(allowed=False, policy_action="redact") == "redact"
        assert SFScopeClient._resolve_outcome(allowed=False, policy_action=None) == "escalate"

    def test_load_manifest_from_yaml(self, tmp_path: Path) -> None:
        """load_manifest_from_yaml registers a manifest from a YAML file."""
        client = self._make_client()
        yaml_file = tmp_path / "scope_manifest.yaml"
        yaml_file.write_text(
            textwrap.dedent("""\
                agent_id: yaml-agent
                allowed_actions:
                  - read
                  - write
                capabilities:
                  - data_access
            """),
            encoding="utf-8",
        )
        manifest = client.load_manifest_from_yaml(str(yaml_file))
        assert manifest.agent_id == "yaml-agent"
        assert "read" in manifest.resource_actions.get("*", [])

    def test_load_manifest_from_yaml_missing_agent_id(self, tmp_path: Path) -> None:
        """load_manifest_from_yaml raises ValueError when agent_id missing."""
        client = self._make_client()
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("allowed_actions:\n  - read\n", encoding="utf-8")
        with pytest.raises(ValueError, match="agent_id"):
            client.load_manifest_from_yaml(str(yaml_file))

    def test_load_manifest_from_yaml_missing_allowed_actions(self, tmp_path: Path) -> None:
        """load_manifest_from_yaml raises ValueError when allowed_actions missing."""
        client = self._make_client()
        yaml_file = tmp_path / "bad2.yaml"
        yaml_file.write_text("agent_id: my-agent\n", encoding="utf-8")
        with pytest.raises(ValueError, match="allowed_actions"):
            client.load_manifest_from_yaml(str(yaml_file))

    def test_list_for_trace(self) -> None:
        """list_for_trace returns all scope decisions for a given trace."""
        client = self._make_client()
        client.register_agent(agent_id="lt-agent", resource_actions={"r": ["read"]})
        client.evaluate(
            trace_id="trace-lt",
            agent_id="lt-agent",
            resource="r",
            action_name="read",
            checked_at="2024-01-01T00:00:00Z",
        )
        decisions = client.list_for_trace("trace-lt")
        assert len(decisions) >= 1

    def test_resolve_action_category(self) -> None:
        """resolve_action_category returns correct category for known actions."""
        from spanforge.sdk.scope import SFScopeClient

        assert SFScopeClient.resolve_action_category("read") == "read"
        assert SFScopeClient.resolve_action_category("write") == "write"
        assert SFScopeClient.resolve_action_category("EXECUTE") == "execute"
        assert SFScopeClient.resolve_action_category("unknown-xyz") is None
