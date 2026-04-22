"""Direct unit tests for the extracted cost CLI module."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

import spanforge._cli_cost as cli_cost


def _ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def test_add_cost_subcommands_registers_run_parser() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    cost_parser = cli_cost.add_cost_subcommands(sub)
    parsed = parser.parse_args(["cost", "run", "--run-id", "run-1", "--input", "events.jsonl"])

    assert parsed.command == "cost"
    assert parsed.cost_command == "run"
    assert parsed.run_id == "run-1"
    assert isinstance(cost_parser, argparse.ArgumentParser)


def test_dispatch_returns_none_for_unrelated_command() -> None:
    parser = argparse.ArgumentParser()

    result = cli_cost.dispatch_cost_command(_ns(command="stats"), parser)

    assert result is None


def test_dispatch_prints_help_for_unknown_cost_action(capsys: pytest.CaptureFixture[str]) -> None:
    parser = argparse.ArgumentParser(prog="spanforge cost")

    result = cli_cost.dispatch_cost_command(
        _ns(command="cost", cost_command=None, brief_command=None),
        parser,
    )

    assert result == 2
    assert "usage:" in capsys.readouterr().out


def test_dispatch_routes_brief_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = argparse.ArgumentParser()
    monkeypatch.setattr(cli_cost, "_cmd_cost_brief_submit", lambda *_args: 11)

    result = cli_cost.dispatch_cost_command(
        _ns(command="cost", cost_command="brief", brief_command="submit"),
        parser,
    )

    assert result == 11


def test_load_cost_brief_store_json_returns_empty_for_invalid_json(tmp_path: Path) -> None:
    store_path = tmp_path / "store.json"
    store_path.write_text("{not valid json", encoding="utf-8")

    assert cli_cost._load_cost_brief_store_json(store_path) == {}


def test_cost_brief_submit_missing_file_exits_2(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = cli_cost._cmd_cost_brief_submit(
        _ns(file=str(tmp_path / "missing.json"), store=str(tmp_path / "store.json")),
    )

    assert result == 2
    assert "file not found" in capsys.readouterr().err


def test_cost_brief_submit_invalid_json_exits_2(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    brief_path = tmp_path / "brief.json"
    brief_path.write_text("{broken", encoding="utf-8")

    result = cli_cost._cmd_cost_brief_submit(
        _ns(file=str(brief_path), store=str(tmp_path / "store.json")),
    )

    assert result == 2
    assert "invalid JSON" in capsys.readouterr().err


def test_cost_brief_submit_missing_fields_exits_2(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    brief_path = tmp_path / "brief.json"
    brief_path.write_text(json.dumps({"model_id": "model-1"}), encoding="utf-8")

    result = cli_cost._cmd_cost_brief_submit(
        _ns(file=str(brief_path), store=str(tmp_path / "store.json")),
    )

    assert result == 2
    assert "missing required fields" in capsys.readouterr().err


def test_cost_brief_submit_writes_store(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    brief_path = tmp_path / "brief.json"
    store_path = tmp_path / "store" / "briefs.json"
    brief_path.write_text(
        json.dumps(
            {
                "model_id": "model-1",
                "submitted_by": "alice",
                "resource_config": {"cpu": 2},
                "scenarios": [{"name": "default"}],
            }
        ),
        encoding="utf-8",
    )

    result = cli_cost._cmd_cost_brief_submit(
        _ns(file=str(brief_path), store=str(store_path)),
    )

    assert result == 0
    stored = json.loads(store_path.read_text(encoding="utf-8"))
    assert stored["model-1"]["submitted_by"] == "alice"
    assert "stored_at" in stored["model-1"]
    assert "Cost brief submitted" in capsys.readouterr().out
