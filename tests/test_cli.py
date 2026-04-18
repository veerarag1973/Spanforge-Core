"""Tests for the Phase 10 CLI commands.

Covers: validate, audit-chain, inspect, stats (and the existing dispatch
fallthrough).  The _cli module is excluded from coverage measurement
(see pyproject.toml ``omit``), but the logic is exercised here to
ensure correctness.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

from spanforge._cli import main
from spanforge.event import Event
from spanforge.signing import sign
from spanforge.types import EventType

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SOURCE = "cli-test@1.0.0"


def _make_event(
    event_type: EventType = EventType.TRACE_SPAN_STARTED,
    payload: dict | None = None,
    **kwargs,
) -> Event:
    return Event(
        event_type=event_type,
        source=_SOURCE,
        payload=payload or {"span_name": "test_span"},
        **kwargs,
    )


def _write_jsonl(path: Path, events: list[Event]) -> None:
    lines = [json.dumps(e.to_dict()) for e in events]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_raw_jsonl(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _run(argv: list[str]) -> pytest.ExceptionInfo:
    with pytest.raises(SystemExit) as exc_info:
        main(argv)
    return exc_info


# ---------------------------------------------------------------------------
# Fallthrough — no subcommand
# ---------------------------------------------------------------------------


class TestMainFallthrough:
    def test_no_command_exits_2(self, capsys):
        exc = _run([])
        assert exc.value.code == 2


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


class TestValidateCommand:
    def test_valid_events_exits_0(self, tmp_path, capsys):
        f = tmp_path / "events.jsonl"
        _write_jsonl(f, [_make_event(), _make_event(EventType.TRACE_SPAN_COMPLETED)])
        exc = _run(["validate", str(f)])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "OK" in out
        assert "2" in out

    def test_missing_file_exits_2(self, tmp_path, capsys):
        exc = _run(["validate", str(tmp_path / "no_such_file.jsonl")])
        assert exc.value.code == 2
        assert "not found" in capsys.readouterr().err

    def test_empty_file_exits_0(self, tmp_path, capsys):
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        exc = _run(["validate", str(f)])
        assert exc.value.code == 0
        assert "No events" in capsys.readouterr().out

    def test_blank_lines_only_exits_0(self, tmp_path, capsys):
        f = tmp_path / "blanks.jsonl"
        f.write_text("   \n\n   \n", encoding="utf-8")
        exc = _run(["validate", str(f)])
        assert exc.value.code == 0

    def test_bad_json_line_exits_1(self, tmp_path, capsys):
        f = tmp_path / "bad.jsonl"
        good = json.dumps(_make_event().to_dict())
        f.write_text(good + "\n{broken json\n", encoding="utf-8")
        exc = _run(["validate", str(f)])
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "FAIL" in out
        assert "parse error" in out

    def test_schema_validation_failure_exits_1(self, tmp_path, capsys):
        """Patch validate_event to raise SchemaValidationError for one event."""
        from spanforge.exceptions import SchemaValidationError

        f = tmp_path / "events.jsonl"
        ev = _make_event()
        _write_jsonl(f, [ev])

        with patch("spanforge.validate.validate_event", side_effect=SchemaValidationError(field="source", received="bad", reason="bad value")):
            exc = _run(["validate", str(f)])

        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "FAIL" in out

    def test_single_valid_event_ok(self, tmp_path, capsys):
        f = tmp_path / "one.jsonl"
        _write_jsonl(f, [_make_event()])
        exc = _run(["validate", str(f)])
        assert exc.value.code == 0


# ---------------------------------------------------------------------------
# audit-chain
# ---------------------------------------------------------------------------


class TestAuditChainCommand:
    _SECRET = "test-signing-key-abc123"

    def _signed_chain(self, n: int = 2) -> list[Event]:
        events: list[Event] = []
        prev: Event | None = None
        for i in range(n):
            raw = _make_event(payload={"step": i})
            signed = sign(raw, org_secret=self._SECRET, prev_event=prev)
            events.append(signed)
            prev = signed
        return events

    def test_missing_env_var_exits_2(self, tmp_path, capsys, monkeypatch):
        monkeypatch.delenv("SPANFORGE_SIGNING_KEY", raising=False)
        f = tmp_path / "chain.jsonl"
        _write_jsonl(f, [_make_event()])
        exc = _run(["audit-chain", str(f)])
        assert exc.value.code == 2
        assert "SPANFORGE_SIGNING_KEY" in capsys.readouterr().err

    def test_missing_file_exits_2(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("SPANFORGE_SIGNING_KEY", self._SECRET)
        exc = _run(["audit-chain", str(tmp_path / "ghost.jsonl")])
        assert exc.value.code == 2

    def test_empty_file_exits_0(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("SPANFORGE_SIGNING_KEY", self._SECRET)
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        exc = _run(["audit-chain", str(f)])
        assert exc.value.code == 0
        assert "No events" in capsys.readouterr().out

    def test_valid_chain_exits_0(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("SPANFORGE_SIGNING_KEY", self._SECRET)
        f = tmp_path / "chain.jsonl"
        _write_jsonl(f, self._signed_chain(3))
        exc = _run(["audit-chain", str(f)])
        assert exc.value.code == 0
        assert "OK" in capsys.readouterr().out

    def test_tampered_chain_exits_1(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("SPANFORGE_SIGNING_KEY", self._SECRET)
        f = tmp_path / "chain.jsonl"
        events = self._signed_chain(3)
        # Tamper: overwrite the signature of the second event
        raw_dicts = [e.to_dict() for e in events]
        raw_dicts[1]["signature"] = "hmac-sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        f.write_text("\n".join(json.dumps(d) for d in raw_dicts) + "\n", encoding="utf-8")
        exc = _run(["audit-chain", str(f)])
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "FAIL" in out
        assert "tampered" in out

    def test_bad_json_in_chain_file_exits_2(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("SPANFORGE_SIGNING_KEY", self._SECRET)
        f = tmp_path / "bad_chain.jsonl"
        good = json.dumps(self._signed_chain(1)[0].to_dict())
        f.write_text(good + "\n{bad json\n", encoding="utf-8")
        exc = _run(["audit-chain", str(f)])
        assert exc.value.code == 2
        assert "could not be parsed" in capsys.readouterr().err

    def test_chain_with_gaps_exits_1(self, tmp_path, capsys, monkeypatch):
        monkeypatch.setenv("SPANFORGE_SIGNING_KEY", self._SECRET)
        f = tmp_path / "gapped.jsonl"
        # Create chain of 3, remove middle event → gap at position 1
        events = self._signed_chain(3)
        _write_jsonl(f, [events[0], events[2]])  # skip events[1]
        exc = _run(["audit-chain", str(f)])
        assert exc.value.code == 1
        out = capsys.readouterr().out
        assert "FAIL" in out


# ---------------------------------------------------------------------------
# inspect
# ---------------------------------------------------------------------------


class TestInspectCommand:
    def test_found_event_exits_0(self, tmp_path, capsys):
        ev = _make_event()
        f = tmp_path / "events.jsonl"
        _write_jsonl(f, [ev, _make_event(EventType.TRACE_SPAN_COMPLETED)])
        exc = _run(["inspect", ev.event_id, str(f)])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["event_id"] == ev.event_id

    def test_not_found_exits_1(self, tmp_path, capsys):
        f = tmp_path / "events.jsonl"
        _write_jsonl(f, [_make_event()])
        exc = _run(["inspect", "NONEXISTENT_ID", str(f)])
        assert exc.value.code == 1
        assert "not found" in capsys.readouterr().err

    def test_missing_file_exits_2(self, tmp_path, capsys):
        exc = _run(["inspect", "some_id", str(tmp_path / "nope.jsonl")])
        assert exc.value.code == 2

    def test_skips_bad_json_lines(self, tmp_path, capsys):
        ev = _make_event()
        f = tmp_path / "mixed.jsonl"
        _write_raw_jsonl(f, ["{bad json", json.dumps(ev.to_dict())])
        exc = _run(["inspect", ev.event_id, str(f)])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert json.loads(out)["event_id"] == ev.event_id

    def test_output_is_valid_json(self, tmp_path, capsys):
        ev = _make_event(payload={"prompt_tokens": 10, "cost_usd": 0.002})
        f = tmp_path / "events.jsonl"
        _write_jsonl(f, [ev])
        _run(["inspect", ev.event_id, str(f)])
        out = capsys.readouterr().out
        parsed = json.loads(out)
        assert parsed["source"] == _SOURCE


# ---------------------------------------------------------------------------
# stats
# ---------------------------------------------------------------------------


class TestStatsCommand:
    def test_missing_file_exits_2(self, tmp_path, capsys):
        exc = _run(["stats", str(tmp_path / "ghost.jsonl")])
        assert exc.value.code == 2

    def test_empty_file_exits_0(self, tmp_path, capsys):
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        exc = _run(["stats", str(f)])
        assert exc.value.code == 0
        assert "No events" in capsys.readouterr().out

    def test_basic_stats_exits_0(self, tmp_path, capsys):
        f = tmp_path / "events.jsonl"
        _write_jsonl(f, [_make_event(), _make_event(EventType.TRACE_SPAN_COMPLETED)])
        exc = _run(["stats", str(f)])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "Events: 2" in out
        assert "Total tokens" in out
        assert "Cost (USD)" in out

    def test_token_and_cost_aggregation(self, tmp_path, capsys):
        f = tmp_path / "rich.jsonl"
        events = [
            _make_event(payload={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150, "cost_usd": 0.003}),
            _make_event(payload={"prompt_tokens": 200, "completion_tokens": 75, "total_tokens": 275, "cost_usd": 0.005}),
        ]
        _write_jsonl(f, events)
        _run(["stats", str(f)])
        out = capsys.readouterr().out
        assert "300" in out   # prompt_tokens sum
        assert "125" in out   # completion_tokens sum
        assert "425" in out   # total_tokens sum
        assert "0.008000" in out  # cost_usd sum

    def test_parse_errors_are_counted(self, tmp_path, capsys):
        f = tmp_path / "mixed.jsonl"
        good = json.dumps(_make_event().to_dict())
        f.write_text(good + "\n{bad json\n", encoding="utf-8")
        exc = _run(["stats", str(f)])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "parse error" in out

    def test_event_type_breakdown(self, tmp_path, capsys):
        f = tmp_path / "typed.jsonl"
        events = [
            _make_event(EventType.TRACE_SPAN_STARTED),
            _make_event(EventType.TRACE_SPAN_STARTED),
            _make_event(EventType.TRACE_SPAN_COMPLETED),
        ]
        _write_jsonl(f, events)
        _run(["stats", str(f)])
        out = capsys.readouterr().out
        # STARTED appears twice — should have count 2 in table
        assert "2" in out

    def test_timestamp_range_displayed(self, tmp_path, capsys):
        f = tmp_path / "ts.jsonl"
        _write_jsonl(f, [_make_event(), _make_event()])
        _run(["stats", str(f)])
        out = capsys.readouterr().out
        assert "Earliest" in out
        assert "Latest" in out

    def test_no_tokens_in_payload(self, tmp_path, capsys):
        """Events with no token fields should aggregate to zero without errors."""
        f = tmp_path / "notokens.jsonl"
        _write_jsonl(f, [_make_event(payload={}), _make_event(payload={})])
        exc = _run(["stats", str(f)])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "0" in out
