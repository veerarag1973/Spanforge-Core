"""Deep branch coverage for spanforge.gate runner/parser internals."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from spanforge.gate import (
    GateConfig,
    GateResult,
    GateRunner,
    GateVerdict,
    _coerce_scalar,
    _dict_to_gate_config,
    _parse_yaml_gates,
)


def test_parse_yaml_gates_fallback_parser_without_pyyaml(monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_text = """
gates:
  - id: gate_one
    name: Gate One
    type: schema_validation
    timeout_seconds: 45
    skip_on:
      - refs/heads/main
      - refs/heads/release/*
    parallel: true
    skip_on_draft: false
"""

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "yaml":
            raise ImportError("PyYAML not installed")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    parsed = _parse_yaml_gates(yaml_text)

    assert len(parsed) == 1
    assert parsed[0]["id"] == "gate_one"
    assert parsed[0]["timeout_seconds"] == 45
    assert parsed[0]["skip_on"] == ["refs/heads/main", "refs/heads/release/*"]
    assert parsed[0]["parallel"] is True


def test_parse_yaml_gates_handles_pyyaml_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _YamlError(Exception):
        pass

    class _YamlModule:
        YAMLError = _YamlError

        @staticmethod
        def safe_load(_text):
            raise _YamlError("bad yaml")

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name == "yaml":
            return _YamlModule
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    assert _parse_yaml_gates("gates:\n  - id: bad") == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("true", True),
        ("FALSE", False),
        ("null", None),
        ("~", None),
        ("42", 42),
        ("3.5", 3.5),
        ("literal", "literal"),
    ],
)
def test_coerce_scalar_variants(raw: str, expected) -> None:
    assert _coerce_scalar(raw) == expected


def test_dict_to_gate_config_normalizes_fields() -> None:
    cfg = _dict_to_gate_config(
        {
            "id": "g1",
            "type": "schema_validation",
            "pass_condition": "bad-shape",
            "skip_on": "refs/heads/main",
            "skip_on_draft": 1,
            "parallel": 1,
            "custom_threshold": 7,
        }
    )

    assert cfg.name == "g1"
    assert cfg.pass_condition == {}
    assert cfg.skip_on == ["refs/heads/main"]
    assert cfg.skip_on_draft is True
    assert cfg.parallel is True
    assert cfg.extra["custom_threshold"] == 7


def test_gate_runner_execute_gate_unknown_executor_and_executor_exception(tmp_path: Path) -> None:
    runner = GateRunner(base_dir=tmp_path)

    unknown_cfg = GateConfig(id="g-unknown", name="Unknown", type="unknown")
    result = runner._execute_gate(unknown_cfg, {"branch": ""})
    assert result.verdict == GateVerdict.ERROR
    assert "Unknown gate type" in result.detail
    assert result.artifact_path is None

    error_cfg = GateConfig(id="g-error", name="Error", type="custom-error")

    def boom(*_args):
        raise RuntimeError("executor blew up")

    with patch.dict("spanforge.gate._EXECUTOR_REGISTRY", {"custom-error": boom}, clear=False):
        result = runner._execute_gate(error_cfg, {"branch": ""})

    assert result.verdict == GateVerdict.ERROR
    assert "Executor raised" in result.detail
    assert result.artifact_path is not None


def test_gate_runner_execute_gate_warn_policy_and_pass_condition_override(tmp_path: Path) -> None:
    runner = GateRunner(base_dir=tmp_path)
    cfg = GateConfig(
        id="g1",
        name="Warn Gate",
        type="custom-warn",
        on_fail="warn",
        pass_condition={"score": ">= 10"},
    )

    def fail_exec(*_args):
        return GateVerdict.FAIL, {"score": 1}, "failed"

    with patch.dict("spanforge.gate._EXECUTOR_REGISTRY", {"custom-warn": fail_exec}, clear=False):
        result = runner._execute_gate(cfg, {"branch": ""})

    assert result.verdict == GateVerdict.WARN
    assert result.artifact_path is not None

    cfg2 = GateConfig(
        id="g2",
        name="Condition Gate",
        type="custom-pass",
        on_fail="block",
        pass_condition={"score": ">= 10"},
    )

    def pass_exec(*_args):
        return GateVerdict.PASS, {"score": 5}, "ok"

    with patch.dict("spanforge.gate._EXECUTOR_REGISTRY", {"custom-pass": pass_exec}, clear=False):
        result = runner._execute_gate(cfg2, {"branch": ""})

    assert result.verdict == GateVerdict.FAIL


def test_gate_runner_write_artifact_falls_back_on_oserror(tmp_path: Path) -> None:
    runner = GateRunner(base_dir=tmp_path)
    result = GateResult(
        gate_id="g1",
        name="Gate 1",
        verdict=GateVerdict.PASS,
        metrics={},
        timestamp="2025-01-01T00:00:00Z",
        duration_ms=0,
    )
    cfg = GateConfig(id="g1", name="Gate 1", type="schema_validation")

    with patch.object(runner._store, "write", side_effect=OSError("disk full")):
        artifact_path = runner._write_artifact(result, cfg)

    assert artifact_path.name == "g1_result.json"


def test_gate_runner_run_handles_parallel_and_blocking_result(tmp_path: Path) -> None:
    yaml_path = tmp_path / "sf-gate.yaml"
    yaml_path.write_text(
        """
gates:
  - id: p1
    name: Parallel 1
    type: custom_parallel
    parallel: true
  - id: p2
    name: Parallel 2
    type: custom_parallel
    parallel: true
  - id: s1
    name: Sequential 1
    type: custom_seq
""",
        encoding="utf-8",
    )

    runner = GateRunner(base_dir=tmp_path, max_workers=1)

    def execute_gate(cfg: GateConfig, _context: dict[str, str]) -> GateResult:
        verdict = GateVerdict.FAIL if cfg.id == "s1" else GateVerdict.PASS
        return GateResult(
            gate_id=cfg.id,
            name=cfg.name,
            verdict=verdict,
            metrics={},
            timestamp="2025-01-01T00:00:00Z",
            duration_ms=1,
            artifact_path=str(tmp_path / f"{cfg.id}.json"),
        )

    with patch.object(runner, "_execute_gate", side_effect=execute_gate):
        result = runner.run(yaml_path, {"project": "proj"})

    assert result.exit_code == 1
    assert result.overall_pass is False
    assert [gate.gate_id for gate in result.gates] == ["p1", "s1"]
