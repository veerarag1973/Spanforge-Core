"""Direct unit tests for the extracted compliance CLI module."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import spanforge._cli_compliance as cli_compliance


def _ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


@dataclass
class _FakeStatus:
    value: str


@dataclass
class _FakeEvidenceRecord:
    clause_id: str
    status: _FakeStatus
    evidence_count: int


@dataclass
class _FakeGapReport:
    has_gaps: bool
    gap_clause_ids: list[str]
    partial_clause_ids: list[str]
    model_id: str = "model-1"
    framework: str = "EU AI Act"
    period_from: str = "2024-01-01"
    period_to: str = "2024-12-31"
    generated_at: str = "2025-01-01T00:00:00Z"


@dataclass
class _FakeAttestation:
    overall_status: _FakeStatus
    clauses: list[_FakeEvidenceRecord]

    def to_json(self) -> str:
        return json.dumps({"model_id": "model-1", "overall_status": self.overall_status.value})


@dataclass
class _FakePackage:
    attestation: _FakeAttestation
    gap_report: _FakeGapReport
    report_text: str = "report"
    audit_exports: dict[str, list[dict]] | None = None

    def to_json(self) -> str:
        return json.dumps({"attestation": {"overall_status": self.attestation.overall_status.value}})

    def to_pdf(self, path: str) -> None:
        Path(path).write_text("pdf", encoding="utf-8")


def test_add_compliance_subcommands_registers_report() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    compliance_parser = cli_compliance.add_compliance_subcommands(sub)
    args = parser.parse_args(["compliance", "report", "--model-id", "m1", "--framework", "gdpr", "--from", "2024-01-01", "--to", "2024-12-31"])

    assert args.command == "compliance"
    assert args.compliance_command == "report"
    assert isinstance(compliance_parser, argparse.ArgumentParser)


def test_dispatch_routes_and_help(capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    parser = argparse.ArgumentParser(prog="spanforge compliance")
    monkeypatch.setattr(cli_compliance, "cmd_check", lambda _args: 7)

    result = cli_compliance.dispatch_compliance_command(_ns(compliance_command="check"), parser)
    assert result == 7

    result = cli_compliance.dispatch_compliance_command(_ns(compliance_command=None), parser)
    assert result == 2
    assert "usage:" in capsys.readouterr().out


def test_resolve_framework_accepts_slug_and_rejects_unknown(capsys: pytest.CaptureFixture[str]) -> None:
    key, framework = cli_compliance._resolve_framework("gdpr")
    assert key == "gdpr"
    assert framework is not None

    key, framework = cli_compliance._resolve_framework("unknown-fw")
    assert key == "unknown-fw"
    assert framework is None
    assert "unknown framework" in capsys.readouterr().err


def test_load_audit_events_variants(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    status, events = cli_compliance._load_audit_events(None)
    assert status == 0
    assert events is None

    missing = tmp_path / "missing.jsonl"
    status, events = cli_compliance._load_audit_events(str(missing))
    assert status == 2
    assert events is None
    assert "events file not found" in capsys.readouterr().err

    events_file = tmp_path / "events.jsonl"
    events_file.write_text('{"ok": 1}\n{bad json\n\n{"ok": 2}\n', encoding="utf-8")
    status, events = cli_compliance._load_audit_events(str(events_file))
    assert status == 0
    assert events == [{"ok": 1}, {"ok": 2}]
    assert "skipping invalid JSON line" in capsys.readouterr().err


def test_attestation_from_dict_reconstructs_structure() -> None:
    data = {
        "model_id": "model-1",
        "framework": "GDPR",
        "period": {"from": "2024-01-01", "to": "2024-12-31"},
        "generated_at": "2025-01-01T00:00:00Z",
        "generated_by": "tester",
        "overall_status": "pass",
        "hmac_sig": "sig",
        "clauses": [
            {
                "clause_id": "1.1",
                "status": "pass",
                "evidence_count": 2,
                "audit_ids": ["a1"],
                "summary": "ok",
            }
        ],
    }

    attestation = cli_compliance._attestation_from_dict(data)

    assert getattr(attestation, "model_id") == "model-1"
    assert getattr(attestation, "period_from") == "2024-01-01"


def test_cmd_generate_writes_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import spanforge.core.compliance_mapping as mapping

    package = _FakePackage(
        attestation=_FakeAttestation(overall_status=_FakeStatus("pass"), clauses=[]),
        gap_report=_FakeGapReport(has_gaps=True, gap_clause_ids=["1.1"], partial_clause_ids=["2.1"]),
        audit_exports={"1.1": [{"event_id": "e1"}]},
    )

    monkeypatch.setattr(
        mapping.ComplianceMappingEngine,
        "generate_evidence_package",
        lambda self, **_kwargs: package,
    )

    result = cli_compliance.cmd_generate(
        _ns(
            model_id="model/1",
            framework="gdpr",
            from_date="2024-01-01",
            to_date="2024-12-31",
            output=str(tmp_path),
            events_file=None,
        )
    )

    assert result == 0
    out = capsys.readouterr().out
    assert "Attestation" in out
    assert any(path.name.endswith("_attestation.json") for path in tmp_path.iterdir())
    assert (tmp_path / "exports").exists()


def test_cmd_generate_reports_framework_or_engine_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = cli_compliance.cmd_generate(
        _ns(
            model_id="model-1",
            framework="bad",
            from_date="2024-01-01",
            to_date="2024-12-31",
            output=str(tmp_path),
            events_file=None,
        )
    )
    assert result == 2

    import spanforge.core.compliance_mapping as mapping

    monkeypatch.setattr(
        mapping.ComplianceMappingEngine,
        "generate_evidence_package",
        lambda self, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    result = cli_compliance.cmd_generate(
        _ns(
            model_id="model-1",
            framework="gdpr",
            from_date="2024-01-01",
            to_date="2024-12-31",
            output=str(tmp_path),
            events_file=None,
        )
    )
    assert result == 1
    assert "evidence package generation failed" in capsys.readouterr().err


def test_cmd_validate_attestation_variants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    attestation_path = tmp_path / "attestation.json"

    result = cli_compliance.cmd_validate_attestation(_ns(attestation_file=str(attestation_path)))
    assert result == 2

    attestation_path.write_text("{bad", encoding="utf-8")
    result = cli_compliance.cmd_validate_attestation(_ns(attestation_file=str(attestation_path)))
    assert result == 2

    attestation_path.write_text(json.dumps({"model_id": "m1"}), encoding="utf-8")
    result = cli_compliance.cmd_validate_attestation(_ns(attestation_file=str(attestation_path)))
    assert result == 2

    from spanforge.core.compliance_mapping import ClauseStatus, ComplianceAttestation

    monkeypatch.setattr(
        cli_compliance,
        "_attestation_from_dict",
        lambda _data: ComplianceAttestation(
            model_id="m1",
            framework="GDPR",
            period_from="2024-01-01",
            period_to="2024-12-31",
            generated_at="2025-01-01T00:00:00Z",
            generated_by="tester",
            clauses=[],
            overall_status=ClauseStatus("pass"),
            hmac_sig="sig",
        ),
    )
    import spanforge.compliance as compliance

    monkeypatch.setattr(compliance, "verify_attestation_signature", lambda _att: True)
    result = cli_compliance.cmd_validate_attestation(_ns(attestation_file=str(attestation_path)))
    assert result == 0

    monkeypatch.setattr(compliance, "verify_attestation_signature", lambda _att: False)
    result = cli_compliance.cmd_validate_attestation(_ns(attestation_file=str(attestation_path)))
    assert result == 1
    assert "INVALID" in capsys.readouterr().err


def test_cmd_report_variants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.core.compliance_mapping as mapping

    package = _FakePackage(
        attestation=_FakeAttestation(overall_status=_FakeStatus("pass"), clauses=[]),
        gap_report=_FakeGapReport(has_gaps=False, gap_clause_ids=[], partial_clause_ids=[]),
    )
    monkeypatch.setattr(
        mapping.ComplianceMappingEngine,
        "generate_evidence_package",
        lambda self, **_kwargs: package,
    )

    result = cli_compliance.cmd_report(
        _ns(
            model_id="m1",
            framework="gdpr",
            from_date="2024-01-01",
            to_date="2024-12-31",
            output=str(tmp_path),
            report_format="both",
            events_file=None,
            sign=False,
        )
    )
    assert result == 0
    assert any(path.suffix == ".json" for path in tmp_path.iterdir())
    assert any(path.suffix == ".pdf" for path in tmp_path.iterdir())

    monkeypatch.setattr(package, "to_pdf", lambda _path: (_ for _ in ()).throw(ImportError()))
    result = cli_compliance.cmd_report(
        _ns(
            model_id="m1",
            framework="gdpr",
            from_date="2024-01-01",
            to_date="2024-12-31",
            output=str(tmp_path),
            report_format="pdf",
            events_file=None,
            sign=False,
        )
    )
    assert result == 1
    assert "reportlab" in capsys.readouterr().err

    monkeypatch.setattr(
        mapping.ComplianceMappingEngine,
        "generate_evidence_package",
        lambda self, **_kwargs: (_ for _ in ()).throw(RuntimeError("fail")),
    )
    result = cli_compliance.cmd_report(
        _ns(
            model_id="m1",
            framework="gdpr",
            from_date="2024-01-01",
            to_date="2024-12-31",
            output=str(tmp_path),
            report_format="json",
            events_file=None,
            sign=False,
        )
    )
    assert result == 1


def test_cmd_check_variants(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    import spanforge.core.compliance_mapping as mapping

    pass_package = _FakePackage(
        attestation=_FakeAttestation(
            overall_status=_FakeStatus("pass"),
            clauses=[_FakeEvidenceRecord("1.1", _FakeStatus("pass"), 2)],
        ),
        gap_report=_FakeGapReport(has_gaps=False, gap_clause_ids=[], partial_clause_ids=[]),
    )
    monkeypatch.setattr(
        mapping.ComplianceMappingEngine,
        "generate_evidence_package",
        lambda self, **_kwargs: pass_package,
    )
    result = cli_compliance.cmd_check(
        _ns(
            model_id="*",
            framework="gdpr",
            from_date="2024-01-01",
            to_date="2024-12-31",
            events_file=None,
            allow_partial=False,
        )
    )
    assert result == 0
    assert "[PASS]" in capsys.readouterr().out

    fail_package = _FakePackage(
        attestation=_FakeAttestation(
            overall_status=_FakeStatus("fail"),
            clauses=[_FakeEvidenceRecord("2.1", _FakeStatus("fail"), 0)],
        ),
        gap_report=_FakeGapReport(has_gaps=True, gap_clause_ids=["2.1"], partial_clause_ids=[]),
    )
    monkeypatch.setattr(
        mapping.ComplianceMappingEngine,
        "generate_evidence_package",
        lambda self, **_kwargs: fail_package,
    )
    result = cli_compliance.cmd_check(
        _ns(
            model_id="*",
            framework="gdpr",
            from_date="2024-01-01",
            to_date="2024-12-31",
            events_file=None,
            allow_partial=False,
        )
    )
    assert result == 1
    assert "Compliance check failed" in capsys.readouterr().err

    partial_package = _FakePackage(
        attestation=_FakeAttestation(
            overall_status=_FakeStatus("partial"),
            clauses=[_FakeEvidenceRecord("3.1", _FakeStatus("partial"), 1)],
        ),
        gap_report=_FakeGapReport(has_gaps=True, gap_clause_ids=[], partial_clause_ids=["3.1"]),
    )
    monkeypatch.setattr(
        mapping.ComplianceMappingEngine,
        "generate_evidence_package",
        lambda self, **_kwargs: partial_package,
    )
    result = cli_compliance.cmd_check(
        _ns(
            model_id="*",
            framework="gdpr",
            from_date="2024-01-01",
            to_date="2024-12-31",
            events_file=None,
            allow_partial=True,
        )
    )
    assert result == 0

    monkeypatch.setattr(
        mapping.ComplianceMappingEngine,
        "generate_evidence_package",
        lambda self, **_kwargs: (_ for _ in ()).throw(ValueError("bad framework")),
    )
    result = cli_compliance.cmd_check(
        _ns(
            model_id="*",
            framework="gdpr",
            from_date="2024-01-01",
            to_date="2024-12-31",
            events_file=None,
            allow_partial=False,
        )
    )
    assert result == 2


def test_cmd_status_variants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing = tmp_path / "missing.jsonl"
    result = cli_compliance.cmd_status(_ns(events_file=str(missing), framework="gdpr"))
    assert result == 2

    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    result = cli_compliance.cmd_status(_ns(events_file=str(empty), framework="gdpr"))
    assert result == 1

    events_file = tmp_path / "events.jsonl"
    events_file.write_text(
        "\n".join(
            [
                json.dumps({"event_type": "llm.trace.completed", "payload": {"x": 1}, "timestamp": "2025-01-01T00:00:00Z"}),
                "{bad json",
                json.dumps({"event_type": "compliance.attestation.created", "payload": {}, "timestamp": "2025-01-02T00:00:00Z"}),
            ]
        ),
        encoding="utf-8",
    )

    import spanforge.signing as signing
    import spanforge.redact as redact
    import spanforge.core.compliance_mapping as mapping

    monkeypatch.setenv("SPANFORGE_SIGNING_KEY", "secret")
    monkeypatch.setattr(signing, "verify_chain", lambda _events, _key: SimpleNamespace(valid=False, first_tampered=2))
    monkeypatch.setattr(
        redact,
        "scan_payload",
        lambda payload: SimpleNamespace(clean=(payload == {}), hits=[1] if payload else []),
    )
    monkeypatch.setattr(
        mapping.ComplianceMappingEngine,
        "generate_evidence_package",
        lambda self, **_kwargs: _FakePackage(
            attestation=_FakeAttestation(
                overall_status=_FakeStatus("pass"),
                clauses=[_FakeEvidenceRecord("1.1", _FakeStatus("pass"), 1)],
            ),
            gap_report=_FakeGapReport(has_gaps=False, gap_clause_ids=[], partial_clause_ids=[]),
        ),
    )

    result = cli_compliance.cmd_status(_ns(events_file=str(events_file), framework="gdpr"))
    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["chain_integrity"]["valid"] is False
    assert payload["pii_scan"]["hit_count"] == 1
    assert payload["last_attestation_timestamp"] == "2025-01-02T00:00:00Z"

    monkeypatch.setattr(signing, "verify_chain", lambda _events, _key: (_ for _ in ()).throw(RuntimeError("bad chain")))
    monkeypatch.setattr(
        mapping.ComplianceMappingEngine,
        "generate_evidence_package",
        lambda self, **_kwargs: (_ for _ in ()).throw(RuntimeError("bad package")),
    )
    result = cli_compliance.cmd_status(_ns(events_file=str(events_file), framework="gdpr"))
    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["chain_integrity"]["message"].startswith("error:")
    assert payload["clause_coverage"]["error"] == "could not evaluate clause coverage"
