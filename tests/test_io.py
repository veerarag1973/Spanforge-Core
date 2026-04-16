"""Tests for spanforge.io — synchronous JSONL read/write utilities."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spanforge.io import (
    append_jsonl,
    read_events,
    read_jsonl,
    write_events,
    write_jsonl,
)


# ---------------------------------------------------------------------------
# write_jsonl
# ---------------------------------------------------------------------------

class TestWriteJsonl:
    def test_creates_file_with_records(self, tmp_path):
        dest = tmp_path / "out.jsonl"
        n = write_jsonl([{"a": 1}, {"b": 2}], dest)
        assert n == 2
        lines = dest.read_text().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"a": 1}
        assert json.loads(lines[1]) == {"b": 2}

    def test_creates_parent_dirs(self, tmp_path):
        dest = tmp_path / "a" / "b" / "c.jsonl"
        write_jsonl([{"x": 1}], dest)
        assert dest.exists()

    def test_overwrites_by_default(self, tmp_path):
        dest = tmp_path / "out.jsonl"
        write_jsonl([{"a": 1}], dest)
        write_jsonl([{"b": 2}], dest)
        lines = dest.read_text().splitlines()
        assert len(lines) == 1
        assert json.loads(lines[0]) == {"b": 2}

    def test_append_mode(self, tmp_path):
        dest = tmp_path / "out.jsonl"
        write_jsonl([{"a": 1}], dest, mode="w")
        write_jsonl([{"b": 2}], dest, mode="a")
        lines = dest.read_text().splitlines()
        assert len(lines) == 2

    def test_invalid_mode_raises(self, tmp_path):
        with pytest.raises(ValueError, match="mode"):
            write_jsonl([], tmp_path / "x.jsonl", mode="r")

    def test_empty_iterable_creates_empty_file(self, tmp_path):
        dest = tmp_path / "empty.jsonl"
        n = write_jsonl([], dest)
        assert n == 0
        assert dest.exists()
        assert dest.read_text() == ""

    def test_returns_correct_count(self, tmp_path):
        dest = tmp_path / "out.jsonl"
        n = write_jsonl([{"i": i} for i in range(7)], dest)
        assert n == 7

    def test_accepts_generator(self, tmp_path):
        dest = tmp_path / "gen.jsonl"
        # iterators / generators must be accepted as the records argument
        write_jsonl(iter([{"x": 1}, {"y": 2}]), dest)
        lines = dest.read_text().splitlines()
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# append_jsonl
# ---------------------------------------------------------------------------

class TestAppendJsonl:
    def test_creates_file_on_first_call(self, tmp_path):
        dest = tmp_path / "out.jsonl"
        append_jsonl({"msg": "hello"}, dest)
        assert dest.exists()
        assert json.loads(dest.read_text()) == {"msg": "hello"}

    def test_appends_successive_calls(self, tmp_path):
        dest = tmp_path / "out.jsonl"
        for i in range(5):
            append_jsonl({"i": i}, dest)
        lines = dest.read_text().splitlines()
        assert len(lines) == 5
        assert json.loads(lines[4]) == {"i": 4}


# ---------------------------------------------------------------------------
# read_jsonl
# ---------------------------------------------------------------------------

class TestReadJsonl:
    def test_reads_all_records(self, tmp_path):
        dest = tmp_path / "data.jsonl"
        write_jsonl([{"a": 1}, {"b": 2}, {"c": 3}], dest)
        records = read_jsonl(dest)
        assert len(records) == 3

    def test_filters_by_event_type(self, tmp_path):
        dest = tmp_path / "events.jsonl"
        lines = [
            '{"event_type": "foo", "x": 1}',
            '{"event_type": "bar", "x": 2}',
            '{"event_type": "foo", "x": 3}',
        ]
        dest.write_text("\n".join(lines) + "\n")
        records = read_jsonl(dest, event_type="foo")
        assert len(records) == 2
        assert all(r["event_type"] == "foo" for r in records)

    def test_skips_empty_lines(self, tmp_path):
        dest = tmp_path / "data.jsonl"
        dest.write_text('{"a": 1}\n\n{"b": 2}\n\n')
        records = read_jsonl(dest)
        assert len(records) == 2

    def test_skips_bad_json_by_default(self, tmp_path):
        dest = tmp_path / "data.jsonl"
        dest.write_text('{"a": 1}\nnot json\n{"b": 2}\n')
        records = read_jsonl(dest)
        assert len(records) == 2

    def test_raises_on_bad_json_when_skip_errors_false(self, tmp_path):
        dest = tmp_path / "data.jsonl"
        dest.write_text('{"a": 1}\nnot json\n')
        with pytest.raises(json.JSONDecodeError):
            read_jsonl(dest, skip_errors=False)

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            read_jsonl(tmp_path / "nonexistent.jsonl")

    def test_skips_non_dict_lines(self, tmp_path):
        dest = tmp_path / "data.jsonl"
        dest.write_text('{"a": 1}\n[1, 2, 3]\n{"b": 2}\n')
        records = read_jsonl(dest)
        assert len(records) == 2

    def test_returns_empty_list_for_empty_file(self, tmp_path):
        dest = tmp_path / "empty.jsonl"
        dest.write_text("")
        records = read_jsonl(dest)
        assert records == []


# ---------------------------------------------------------------------------
# write_events / read_events
# ---------------------------------------------------------------------------

class TestWriteReadEvents:
    def test_round_trip(self, tmp_path):
        dest = tmp_path / "events.jsonl"
        payloads = [{"score": 0.9, "case_id": "tc-001"}, {"score": 0.5, "case_id": "tc-002"}]
        write_events(payloads, dest, event_type="llm.eval.done")
        result = read_events(dest, event_type="llm.eval.done")
        assert result == payloads

    def test_event_type_filter(self, tmp_path):
        dest = tmp_path / "events.jsonl"
        write_events([{"x": 1}], dest, event_type="type.a")
        write_events([{"y": 2}], dest, event_type="type.b", mode="a")
        a = read_events(dest, event_type="type.a")
        b = read_events(dest, event_type="type.b")
        assert a == [{"x": 1}]
        assert b == [{"y": 2}]

    def test_source_field_written(self, tmp_path):
        dest = tmp_path / "events.jsonl"
        write_events([{"k": "v"}], dest, event_type="t", source="my-tool@1.0")
        raw = read_jsonl(dest)
        assert raw[0]["source"] == "my-tool@1.0"

    def test_default_source(self, tmp_path):
        dest = tmp_path / "events.jsonl"
        write_events([{"k": "v"}], dest, event_type="t")
        raw = read_jsonl(dest)
        assert raw[0]["source"] == "spanforge"

    def test_read_events_ignores_plain_json_lines(self, tmp_path):
        dest = tmp_path / "events.jsonl"
        # Write mixed: envelope line + plain line
        dest.write_text(
            '{"event_type": "foo", "source": "s", "payload": {"x": 1}}\n'
            '{"no_payload": true}\n'
        )
        result = read_events(dest, event_type="foo")
        assert result == [{"x": 1}]

    def test_write_events_returns_count(self, tmp_path):
        dest = tmp_path / "events.jsonl"
        n = write_events([{"a": 1}, {"b": 2}, {"c": 3}], dest, event_type="t")
        assert n == 3

    def test_append_mode(self, tmp_path):
        dest = tmp_path / "events.jsonl"
        write_events([{"a": 1}], dest, event_type="t", mode="w")
        write_events([{"b": 2}], dest, event_type="t", mode="a")
        result = read_events(dest, event_type="t")
        assert len(result) == 2
