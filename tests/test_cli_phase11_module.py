"""Direct unit tests for the extracted Phase 11 CLI module."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

import pytest

import spanforge._cli_phase11 as cli_phase11


def _ns(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


@dataclass
class _EnterpriseStatus:
    status: str = "ok"
    multi_tenancy_enabled: bool = True
    encryption_at_rest: bool = True
    fips_mode: bool = False
    offline_mode: bool = False
    data_residency: str = "eu"
    tenant_count: int = 2
    last_security_scan: str | None = None


@dataclass
class _Tenant:
    project_id: str
    org_id: str
    data_residency: str


@dataclass
class _EncryptionConfig:
    encrypt_at_rest: bool = True
    kms_provider: str | None = "azure"
    mtls_enabled: bool = False
    fips_mode: bool = False


@dataclass
class _HealthResult:
    service: str
    endpoint: str
    status: int
    ok: bool
    latency_ms: float
    checked_at: str = "2025-01-01T00:00:00Z"


@dataclass
class _ThreatEntry:
    service: str
    category: str
    threat: str
    mitigation: str
    risk_level: str
    reviewed_at: str = "2025-01-01T00:00:00Z"


@dataclass
class _SecurityScanResult:
    vulnerabilities: list[dict]
    static_findings: list[dict]
    secrets_in_logs: int
    pass_: bool
    scanned_at: str = "2025-01-01T00:00:00Z"


@dataclass
class _SecurityAuditResult:
    categories: dict[str, dict[str, str]]
    pass_: bool
    audited_at: str = "2025-01-01T00:00:00Z"
    threat_model: list[dict] | None = None


def test_add_phase11_subcommands_registers_enterprise_and_security() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    enterprise_parser, security_parser = cli_phase11.add_phase11_subcommands(sub)
    enterprise_args = parser.parse_args(["enterprise", "status"])
    security_args = parser.parse_args(["security", "scan"])

    assert enterprise_args.command == "enterprise"
    assert enterprise_args.enterprise_command == "status"
    assert security_args.command == "security"
    assert security_args.security_command == "scan"
    assert isinstance(enterprise_parser, argparse.ArgumentParser)
    assert isinstance(security_parser, argparse.ArgumentParser)


def test_dispatch_returns_none_for_other_commands() -> None:
    result = cli_phase11.dispatch_phase11_command(
        _ns(command="stats"),
        argparse.ArgumentParser(),
        argparse.ArgumentParser(),
    )

    assert result is None


def test_dispatch_enterprise_without_action_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    parser = argparse.ArgumentParser(prog="spanforge enterprise")

    result = cli_phase11.dispatch_phase11_command(
        _ns(command="enterprise", enterprise_command=None),
        parser,
        argparse.ArgumentParser(),
    )

    assert result == 2
    assert "usage:" in capsys.readouterr().out


def test_dispatch_security_without_action_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    parser = argparse.ArgumentParser(prog="spanforge security")

    result = cli_phase11.dispatch_phase11_command(
        _ns(command="security", security_command=None),
        argparse.ArgumentParser(),
        parser,
    )

    assert result == 2
    assert "usage:" in capsys.readouterr().out


def test_enterprise_status_prints_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(sdk.sf_enterprise, "get_status", lambda: _EnterpriseStatus())

    result = cli_phase11._cmd_enterprise_status(_ns(format="text"))

    assert result == 0
    out = capsys.readouterr().out
    assert "Enterprise Hardening Status" in out
    assert "Multi-Tenancy: enabled" in out


def test_enterprise_status_prints_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(sdk.sf_enterprise, "get_status", lambda: _EnterpriseStatus())

    result = cli_phase11._cmd_enterprise_status(_ns(format="json"))

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["tenant_count"] == 2


def test_enterprise_register_tenant_prints_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(
        sdk.sf_enterprise,
        "register_tenant",
        lambda **kwargs: _Tenant(
            project_id=kwargs["project_id"],
            org_id=kwargs["org_id"],
            data_residency=kwargs["data_residency"],
        ),
    )

    result = cli_phase11._cmd_enterprise_register_tenant(
        _ns(project_id="proj-1", org_id="org-1", residency="in"),
    )

    assert result == 0
    out = capsys.readouterr().out
    assert "Tenant registered" in out
    assert "Residency: in" in out


def test_enterprise_list_tenants_handles_empty_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(sdk.sf_enterprise, "list_tenants", lambda: [])

    result = cli_phase11._cmd_enterprise_list_tenants(_ns(format="text"))

    assert result == 0
    assert "No tenants registered." in capsys.readouterr().out


def test_enterprise_list_tenants_prints_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(
        sdk.sf_enterprise,
        "list_tenants",
        lambda: [_Tenant(project_id="proj-1", org_id="org-1", data_residency="us")],
    )

    result = cli_phase11._cmd_enterprise_list_tenants(_ns(format="json"))

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["project_id"] == "proj-1"


def test_enterprise_encrypt_config_prints_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(sdk.sf_enterprise, "get_encryption_config", lambda: _EncryptionConfig())

    result = cli_phase11._cmd_enterprise_encrypt_config(_ns())

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["encrypt_at_rest"] is True


def test_enterprise_health_prints_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(
        sdk.sf_enterprise,
        "check_all_services_health",
        lambda: [
            _HealthResult(service="sf-api", endpoint="/healthz", status=200, ok=True, latency_ms=1.2),
            _HealthResult(service="sf-pii", endpoint="/readyz", status=503, ok=False, latency_ms=5.4),
        ],
    )

    result = cli_phase11._cmd_enterprise_health(_ns(format="text"))

    assert result == 0
    out = capsys.readouterr().out
    assert "DEGRADED" in out
    assert "sf-api/healthz - 200" in out


def test_enterprise_health_prints_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(
        sdk.sf_enterprise,
        "check_all_services_health",
        lambda: [_HealthResult(service="sf-api", endpoint="/healthz", status=200, ok=True, latency_ms=1.2)],
    )

    result = cli_phase11._cmd_enterprise_health(_ns(format="json"))

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["service"] == "sf-api"


def test_security_owasp_prints_text_and_returns_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(
        sdk.sf_security,
        "run_owasp_audit",
        lambda: _SecurityAuditResult(
            categories={"API1": {"name": "BOLA", "status": "fail", "detail": "missing authz"}},
            pass_=False,
        ),
    )

    result = cli_phase11._cmd_security_owasp(_ns(format="text"))

    assert result == 1
    out = capsys.readouterr().out
    assert "OWASP API Security Top 10 Audit: FAIL" in out
    assert "missing authz" in out


def test_security_owasp_prints_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(
        sdk.sf_security,
        "run_owasp_audit",
        lambda: _SecurityAuditResult(
            categories={"API1": {"name": "BOLA", "status": "pass", "detail": "ok"}},
            pass_=True,
        ),
    )

    result = cli_phase11._cmd_security_owasp(_ns(format="json"))

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["pass_"] is True


def test_security_threat_model_prints_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(
        sdk.sf_security,
        "generate_default_threat_model",
        lambda: [
            _ThreatEntry(
                service="sf-api",
                category="spoofing",
                threat="credential theft",
                mitigation="MFA",
                risk_level="high",
            )
        ],
    )

    result = cli_phase11._cmd_security_threat_model(_ns(format="text"))

    assert result == 0
    out = capsys.readouterr().out
    assert "STRIDE Threat Model" in out
    assert "credential theft" in out


def test_security_threat_model_prints_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(
        sdk.sf_security,
        "generate_default_threat_model",
        lambda: [
            _ThreatEntry(
                service="sf-api",
                category="spoofing",
                threat="credential theft",
                mitigation="MFA",
                risk_level="high",
            )
        ],
    )

    result = cli_phase11._cmd_security_threat_model(_ns(format="json"))

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["category"] == "spoofing"


def test_security_scan_prints_text_and_returns_failure(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(
        sdk.sf_security,
        "run_full_scan",
        lambda: _SecurityScanResult(
            vulnerabilities=[{"id": "CVE-1"}],
            static_findings=[{"id": "B101"}],
            secrets_in_logs=2,
            pass_=False,
        ),
    )

    result = cli_phase11._cmd_security_scan(_ns(format="text"))

    assert result == 1
    out = capsys.readouterr().out
    assert "Security Scan: FAIL" in out
    assert "Vulnerabilities:     1" in out


def test_security_scan_prints_json(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    monkeypatch.setattr(
        sdk.sf_security,
        "run_full_scan",
        lambda: _SecurityScanResult(
            vulnerabilities=[],
            static_findings=[],
            secrets_in_logs=0,
            pass_=True,
        ),
    )

    result = cli_phase11._cmd_security_scan(_ns(format="json"))

    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["pass_"] is True


def test_security_audit_logs_without_file_is_clean(capsys: pytest.CaptureFixture[str]) -> None:
    result = cli_phase11._cmd_security_audit_logs(_ns(file=None))

    assert result == 0
    assert "clean" in capsys.readouterr().out


def test_security_audit_logs_reports_open_error(
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = cli_phase11._cmd_security_audit_logs(_ns(file=str(tmp_path / "missing.log")))

    assert result == 2
    assert "error:" in capsys.readouterr().err


def test_security_audit_logs_reports_findings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    log_file = tmp_path / "app.log"
    log_file.write_text("secret=abc\n", encoding="utf-8")
    monkeypatch.setattr(sdk.sf_security, "audit_logs_for_secrets_safe", lambda lines: len(lines))

    result = cli_phase11._cmd_security_audit_logs(_ns(file=str(log_file)))

    assert result == 1
    assert "Found 1 secret" in capsys.readouterr().out


def test_security_audit_logs_reports_clean_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    import spanforge.sdk as sdk

    log_file = tmp_path / "app.log"
    log_file.write_text("all good\n", encoding="utf-8")
    monkeypatch.setattr(sdk.sf_security, "audit_logs_for_secrets_safe", lambda _lines: 0)

    result = cli_phase11._cmd_security_audit_logs(_ns(file=str(log_file)))

    assert result == 0
    assert "No secrets detected" in capsys.readouterr().out
