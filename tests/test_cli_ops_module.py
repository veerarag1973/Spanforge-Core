"""Direct unit tests for the extracted ops CLI module."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import spanforge._cli_ops as cli_ops


def _ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def test_add_ops_subcommands_registers_gate_and_trust() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    config_parser, trust_parser, gate_parser, operator_parser = cli_ops.add_ops_subcommands(sub)
    parsed = parser.parse_args(["gate", "run", "pipeline.yaml"])

    assert parsed.command == "gate"
    assert parsed.gate_command == "run"
    assert isinstance(config_parser, argparse.ArgumentParser)
    assert isinstance(trust_parser, argparse.ArgumentParser)
    assert isinstance(gate_parser, argparse.ArgumentParser)
    assert isinstance(operator_parser, argparse.ArgumentParser)


def test_dispatch_returns_none_for_other_commands() -> None:
    parser = argparse.ArgumentParser()

    result = cli_ops.dispatch_ops_command(
        _ns(command="stats"),
        parser,
        parser,
        parser,
        parser,
    )

    assert result is None


def test_dispatch_config_without_action_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    parser = argparse.ArgumentParser(prog="spanforge config")

    result = cli_ops.dispatch_ops_command(
        _ns(command="config", config_command=None),
        parser,
        parser,
        parser,
        parser,
    )

    assert result == 2
    assert "usage:" in capsys.readouterr().out


def test_dispatch_trust_without_action_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    trust_parser = argparse.ArgumentParser(prog="spanforge trust")

    result = cli_ops.dispatch_ops_command(
        _ns(command="trust", trust_command=None),
        argparse.ArgumentParser(),
        trust_parser,
        argparse.ArgumentParser(),
        argparse.ArgumentParser(),
    )

    assert result == 2
    assert "usage:" in capsys.readouterr().out


def test_dispatch_routes_doctor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli_ops, "_cmd_doctor", lambda *_args: 9)

    result = cli_ops.dispatch_ops_command(
        _ns(command="doctor"),
        argparse.ArgumentParser(),
        argparse.ArgumentParser(),
        argparse.ArgumentParser(),
        argparse.ArgumentParser(),
    )

    assert result == 9


def test_gate_run_rejects_bad_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = cli_ops._cmd_gate_run(
        _ns(gate_yaml="pipeline.yaml", context=["not-a-pair"], artifact_dir=None, format="text"),
    )

    assert result == 2
    assert "KEY=VALUE" in capsys.readouterr().err


def test_gate_run_reports_missing_yaml(capsys: pytest.CaptureFixture[str]) -> None:
    result = cli_ops._cmd_gate_run(
        _ns(gate_yaml="missing.yaml", context=[], artifact_dir=None, format="text"),
    )

    assert result == 2
    assert "gate YAML not found" in capsys.readouterr().err


def test_gate_run_reports_json_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.gate as gate

    monkeypatch.setattr(
        gate,
        "GateRunner",
        lambda: SimpleNamespace(
            run=lambda *_args, **_kwargs: SimpleNamespace(
                to_dict=lambda: {"overall_pass": True, "exit_code": 0},
            )
        ),
    )

    result = cli_ops._cmd_gate_run(
        _ns(gate_yaml="pipeline.yaml", context=["A=B"], artifact_dir="artifacts", format="json"),
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["overall_pass"] is True


def test_gate_run_reports_text_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.gate as gate

    monkeypatch.setattr(
        gate,
        "GateRunner",
        lambda: SimpleNamespace(
            run=lambda *_args, **_kwargs: SimpleNamespace(
                gates=[
                    SimpleNamespace(
                        gate_id="g1",
                        name="Gate 1",
                        verdict=SimpleNamespace(value="PASS"),
                        duration_ms=12,
                        detail="ok",
                    ),
                    SimpleNamespace(
                        gate_id="g2",
                        name="Gate 2",
                        verdict=SimpleNamespace(value="WARN"),
                        duration_ms=8,
                        detail="warn",
                    ),
                ],
                exit_code=0,
            )
        ),
    )

    result = cli_ops._cmd_gate_run(
        _ns(gate_yaml="pipeline.yaml", context=[], artifact_dir=None, format="text"),
    )

    assert result == 0
    out = capsys.readouterr().out
    assert "Running gate pipeline" in out
    assert "Result: 1 passed, 0 failed, 1 warned" in out


def test_gate_run_reports_generic_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.gate as gate

    monkeypatch.setattr(
        gate,
        "GateRunner",
        lambda: SimpleNamespace(run=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))),
    )

    result = cli_ops._cmd_gate_run(
        _ns(gate_yaml="pipeline.yaml", context=[], artifact_dir=None, format="text"),
    )

    assert result == 2
    assert "boom" in capsys.readouterr().err


def test_gate_evaluate_reports_bad_payload_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload_file = tmp_path / "payload.json"
    payload_file.write_text("{broken", encoding="utf-8")

    result = cli_ops._cmd_gate_evaluate(
        _ns(gate_id="gate-1", payload=str(payload_file), project_id="", format="text"),
    )

    assert result == 2
    assert "error reading payload" in capsys.readouterr().err


def test_gate_evaluate_reports_json_output(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli_ops.sys.stdin, "isatty", lambda: True)
    import spanforge.sdk as sdk

    monkeypatch.setattr(
        sdk.sf_gate,
        "evaluate",
        lambda *_args, **_kwargs: SimpleNamespace(
            gate_id="gate-1",
            verdict=SimpleNamespace(value="PASS"),
            metrics={"score": 1.0},
            artifact_url="artifact.json",
            duration_ms=12.5,
        ),
    )

    result = cli_ops._cmd_gate_evaluate(
        _ns(gate_id="gate-1", payload=None, project_id="", format="json"),
    )

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "PASS"


def test_gate_evaluate_reports_invalid_json_on_stdin(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli_ops.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(cli_ops.sys.stdin, "read", lambda: "{broken")

    result = cli_ops._cmd_gate_evaluate(
        _ns(gate_id="gate-1", payload=None, project_id="", format="text"),
    )

    assert result == 2
    assert "invalid JSON on stdin" in capsys.readouterr().err


def test_gate_evaluate_reports_sdk_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli_ops.sys.stdin, "isatty", lambda: True)
    import spanforge.sdk as sdk

    monkeypatch.setattr(sdk.sf_gate, "evaluate", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("bad gate")))

    result = cli_ops._cmd_gate_evaluate(
        _ns(gate_id="gate-1", payload=None, project_id="", format="text"),
    )

    assert result == 2
    assert "bad gate" in capsys.readouterr().err


def test_gate_evaluate_reports_text_fail(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli_ops.sys.stdin, "isatty", lambda: True)
    import spanforge.sdk as sdk

    monkeypatch.setattr(
        sdk.sf_gate,
        "evaluate",
        lambda *_args, **_kwargs: SimpleNamespace(
            gate_id="gate-1",
            verdict=SimpleNamespace(value="FAIL"),
            metrics={},
            artifact_url="artifact",
            duration_ms=3.2,
        ),
    )

    result = cli_ops._cmd_gate_evaluate(
        _ns(gate_id="gate-1", payload=None, project_id="", format="text"),
    )

    assert result == 1
    assert "[FAIL] gate-1" in capsys.readouterr().out


def test_trust_badge_writes_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    out_file = tmp_path / "badge.svg"
    monkeypatch.setattr(
        sdk.sf_trust,
        "get_badge",
        lambda **_kwargs: SimpleNamespace(svg="<svg />", overall=88.0, colour_band="green"),
    )

    result = cli_ops._cmd_trust_badge(_ns(project_id="p1", output=str(out_file)))

    assert result == 0
    assert out_file.read_text(encoding="utf-8") == "<svg />"
    assert "Badge written" in capsys.readouterr().out


def test_trust_badge_prints_svg_to_stdout(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(
        sdk.sf_trust,
        "get_badge",
        lambda **_kwargs: SimpleNamespace(svg="<svg />", overall=88.0, colour_band="green"),
    )

    result = cli_ops._cmd_trust_badge(_ns(project_id="p1", output=None))

    assert result == 0
    assert capsys.readouterr().out.strip() == "<svg />"


def test_trust_badge_reports_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(sdk.sf_trust, "get_badge", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("no badge")))

    result = cli_ops._cmd_trust_badge(_ns(project_id="p1", output=None))

    assert result == 1
    assert "no badge" in capsys.readouterr().err


def test_trust_gate_json_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(
        sdk.sf_trust,
        "get_scorecard",
        lambda **_kwargs: SimpleNamespace(overall_score=50.0, colour_band="amber"),
    )
    monkeypatch.setattr(
        sdk.sf_gate,
        "run_trust_gate",
        lambda **_kwargs: SimpleNamespace(pass_=False, failures=["pii detected"]),
    )

    result = cli_ops._cmd_trust_gate(_ns(project_id="p1", min_score=60.0, format="json"))

    assert result == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["verdict"] == "FAIL"
    assert payload["failures"]


def test_trust_gate_text_success(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(
        sdk.sf_trust,
        "get_scorecard",
        lambda **_kwargs: SimpleNamespace(overall_score=90.0, colour_band="green"),
    )
    monkeypatch.setattr(
        sdk.sf_gate,
        "run_trust_gate",
        lambda **_kwargs: SimpleNamespace(pass_=True, failures=[]),
    )

    result = cli_ops._cmd_trust_gate(_ns(project_id="p1", min_score=60.0, format="text"))

    assert result == 0
    assert "All checks passed." in capsys.readouterr().out


def test_trust_gate_reports_scorecard_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(sdk.sf_trust, "get_scorecard", lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("missing scorecard")))

    result = cli_ops._cmd_trust_gate(_ns(project_id="p1", min_score=60.0, format="text"))

    assert result == 1
    assert "missing scorecard" in capsys.readouterr().err


def test_doctor_covers_warning_and_failure_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk
    import spanforge.sdk.config as config

    monkeypatch.setattr(config, "load_config_file", lambda: (_ for _ in ()).throw(FileNotFoundError()))
    monkeypatch.setattr(config, "validate_config", lambda _cfg: [])
    monkeypatch.setattr(sdk.sf_identity, "get_status", lambda: {"status": "degraded"})
    monkeypatch.setattr(sdk.sf_pii, "get_status", lambda: SimpleNamespace(entity_types_loaded=[]))
    monkeypatch.setattr(sdk.sf_secrets, "get_status", lambda: (_ for _ in ()).throw(RuntimeError("secrets down")))
    for svc in (
        sdk.sf_audit,
        sdk.sf_observe,
        sdk.sf_gate,
        sdk.sf_cec,
        sdk.sf_alert,
        sdk.sf_trust,
        sdk.sf_enterprise,
        sdk.sf_security,
    ):
        monkeypatch.setattr(svc, "get_status", lambda: {"status": "ok"})

    result = cli_ops._cmd_doctor(_ns())

    assert result == 1
    out = capsys.readouterr().out
    assert "No spanforge.toml found" in out
    assert "sf_identity: degraded" in out
    assert "secrets down" in out
    assert "No PII entity types loaded" in out


def test_dispatch_routes_operator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_ops, "_cmd_operator", lambda *_args: 11)

    result = cli_ops.dispatch_ops_command(
        _ns(command="operator", operator_command="inspect"),
        argparse.ArgumentParser(),
        argparse.ArgumentParser(),
        argparse.ArgumentParser(),
        argparse.ArgumentParser(),
    )

    assert result == 11


def test_operator_inspect_reports_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(
        sdk.sf_operator,
        "inspect_trace",
        lambda trace_id: SimpleNamespace(
            to_dict=lambda: {"trace_id": trace_id, "outcome": "block"},
            trace_id=trace_id,
            outcome="block",
            summary="blocked",
            policy_decisions=[1],
            grounding_results=[1],
            scope_decisions=[1],
            rbac_decisions=[1],
            lineage_records=[1],
            audit_records=[1],
        ),
    )

    result = cli_ops._cmd_operator_inspect(_ns(trace_id="trace-001", format="json"))

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["trace_id"] == "trace-001"
    assert payload["outcome"] == "block"


def test_operator_export_writes_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    out_file = tmp_path / "package.json"
    monkeypatch.setattr(
        sdk.sf_operator,
        "export_package",
        lambda trace_id, output_path=None: SimpleNamespace(
            to_dict=lambda: {"trace_id": trace_id},
            package_id="pkg-001",
            trace_id=trace_id,
            outcome="block",
            exported_records=4,
            signature="hmac-sha256:test",
            output_path=output_path,
        ),
    )

    result = cli_ops._cmd_operator_export(
        _ns(trace_id="trace-002", output=str(out_file), format="text"),
    )

    assert result == 0
    assert "Evidence package written" in capsys.readouterr().out
