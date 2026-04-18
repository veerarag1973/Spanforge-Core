"""Tests for Phase 11 — Enterprise Hardening & Supply Chain Security.

Covers: enterprise.py, security.py, _types.py (Phase 11 types),
_exceptions.py (Phase 11 errors), CLI enterprise/security subcommands,
and server /healthz, /readyz, enterprise, security endpoints.
"""

from __future__ import annotations

import json
import secrets
import sys
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from spanforge.sdk._base import SFClientConfig
from spanforge.sdk._types import SecretStr


def _make_config() -> SFClientConfig:
    """Return a minimal config for testing."""
    return SFClientConfig(
        endpoint="http://localhost:8340",
        api_key=SecretStr("sf_test_key"),
        signing_key="test-signing-key",
    )


# ===========================================================================
# Phase 11 Types — _types.py
# ===========================================================================


@pytest.mark.unit
class TestPhase11Types:
    """Frozen dataclass tests for all Phase 11 types."""

    def test_data_residency_is_valid(self) -> None:
        from spanforge.sdk._types import DataResidency

        assert DataResidency.is_valid("eu") is True
        assert DataResidency.is_valid("US") is True
        assert DataResidency.is_valid("ap") is True
        assert DataResidency.is_valid("in") is True
        assert DataResidency.is_valid("global") is True
        assert DataResidency.is_valid("mars") is False

    def test_data_residency_constants(self) -> None:
        from spanforge.sdk._types import DataResidency

        assert DataResidency.EU == "eu"
        assert DataResidency.US == "us"
        assert DataResidency.AP == "ap"
        assert DataResidency.IN == "in"
        assert DataResidency.GLOBAL == "global"

    def test_isolation_scope_composite_key(self) -> None:
        from spanforge.sdk._types import IsolationScope

        scope = IsolationScope(org_id="org-1", project_id="proj-1")
        assert f"{scope.org_id}:{scope.project_id}" == "org-1:proj-1"

    def test_isolation_scope_frozen(self) -> None:
        from spanforge.sdk._types import IsolationScope

        scope = IsolationScope(org_id="org-1", project_id="proj-1")
        with pytest.raises(AttributeError):
            scope.org_id = "changed"  # type: ignore[misc]

    def test_tenant_config_defaults(self) -> None:
        from spanforge.sdk._types import TenantConfig

        tc = TenantConfig(
            project_id="p1",
            org_id="o1",
            data_residency="eu",
            org_secret="abc",
        )
        assert tc.cross_project_read is False
        assert tc.allowed_project_ids == []

    def test_tenant_config_with_cross_project(self) -> None:
        from spanforge.sdk._types import TenantConfig

        tc = TenantConfig(
            project_id="p1",
            org_id="o1",
            data_residency="us",
            org_secret="abc",
            cross_project_read=True,
            allowed_project_ids=["p2", "p3"],
        )
        assert tc.cross_project_read is True
        assert tc.allowed_project_ids == ["p2", "p3"]

    def test_encryption_config_defaults(self) -> None:
        from spanforge.sdk._types import EncryptionConfig

        ec = EncryptionConfig()
        assert ec.encrypt_at_rest is False
        assert ec.kms_provider is None
        assert ec.mtls_enabled is False
        assert ec.fips_mode is False

    def test_encryption_config_custom(self) -> None:
        from spanforge.sdk._types import EncryptionConfig

        ec = EncryptionConfig(
            encrypt_at_rest=True,
            kms_provider="aws",
            mtls_enabled=True,
            fips_mode=True,
        )
        assert ec.encrypt_at_rest is True
        assert ec.kms_provider == "aws"

    def test_airgap_config_defaults(self) -> None:
        from spanforge.sdk._types import AirGapConfig

        ac = AirGapConfig()
        assert ac.offline is False
        assert ac.self_hosted is False
        assert ac.health_check_interval_s == 30

    def test_airgap_config_offline(self) -> None:
        from spanforge.sdk._types import AirGapConfig

        ac = AirGapConfig(offline=True, self_hosted=True)
        assert ac.offline is True
        assert ac.self_hosted is True

    def test_health_endpoint_result(self) -> None:
        from spanforge.sdk._types import HealthEndpointResult

        h = HealthEndpointResult(
            service="sf-pii",
            endpoint="/healthz",
            status=200,
            ok=True,
            latency_ms=1.5,
            checked_at="2025-01-01T00:00:00Z",
        )
        assert h.ok is True
        assert h.service == "sf-pii"

    def test_dependency_vulnerability(self) -> None:
        from spanforge.sdk._types import DependencyVulnerability

        dv = DependencyVulnerability(
            package="requests",
            version="2.25.0",
            advisory_id="CVE-2021-12345",
            severity="high",
            description="Test vuln",
        )
        assert dv.severity == "high"
        assert dv.package == "requests"

    def test_static_analysis_finding(self) -> None:
        from spanforge.sdk._types import StaticAnalysisFinding

        f = StaticAnalysisFinding(
            file_path="src/foo.py",
            line=42,
            rule_id="B101",
            severity="medium",
            message="Use of assert detected.",
            tool="bandit",
        )
        assert f.tool == "bandit"
        assert f.line == 42

    def test_threat_model_entry(self) -> None:
        from spanforge.sdk._types import ThreatModelEntry

        e = ThreatModelEntry(
            service="sf-identity",
            category="spoofing",
            threat="Credential theft",
            mitigation="MFA required",
            risk_level="high",
            reviewed_at="2025-01-01T00:00:00Z",
        )
        assert e.category == "spoofing"
        assert e.risk_level == "high"

    def test_security_scan_result(self) -> None:
        from spanforge.sdk._types import SecurityScanResult

        r = SecurityScanResult(
            vulnerabilities=[],
            static_findings=[],
            secrets_in_logs=0,
            pass_=True,
            scanned_at="2025-01-01T00:00:00Z",
        )
        assert r.pass_ is True

    def test_security_audit_result(self) -> None:
        from spanforge.sdk._types import SecurityAuditResult

        r = SecurityAuditResult(
            categories={"API1": {"name": "BOLA", "status": "pass", "detail": "ok"}},
            pass_=True,
            audited_at="2025-01-01T00:00:00Z",
            threat_model=[],
        )
        assert r.pass_ is True
        assert "API1" in r.categories

    def test_enterprise_status_info(self) -> None:
        from spanforge.sdk._types import EnterpriseStatusInfo

        s = EnterpriseStatusInfo(
            status="ok",
            multi_tenancy_enabled=True,
            encryption_at_rest=False,
            fips_mode=False,
            offline_mode=False,
            data_residency="eu",
            tenant_count=3,
            last_security_scan=None,
        )
        assert s.tenant_count == 3
        assert s.status == "ok"


# ===========================================================================
# Phase 11 Exceptions — _exceptions.py
# ===========================================================================


@pytest.mark.unit
class TestPhase11Exceptions:
    """Exception hierarchy tests for Phase 11."""

    def test_enterprise_error_base(self) -> None:
        from spanforge.sdk._exceptions import SFEnterpriseError, SFError

        exc = SFEnterpriseError("base")
        assert isinstance(exc, SFError)
        assert "base" in str(exc)

    def test_isolation_error(self) -> None:
        from spanforge.sdk._exceptions import SFEnterpriseError, SFIsolationError

        exc = SFIsolationError("proj-1", "Not registered")
        assert isinstance(exc, SFEnterpriseError)
        assert "proj-1" in str(exc)

    def test_data_residency_error(self) -> None:
        from spanforge.sdk._exceptions import SFDataResidencyError, SFEnterpriseError

        exc = SFDataResidencyError(region="eu", attempted="us")
        assert isinstance(exc, SFEnterpriseError)
        assert "eu" in str(exc)
        assert "us" in str(exc)

    def test_encryption_error(self) -> None:
        from spanforge.sdk._exceptions import SFEncryptionError, SFEnterpriseError

        exc = SFEncryptionError("KMS failed")
        assert isinstance(exc, SFEnterpriseError)

    def test_fips_error(self) -> None:
        from spanforge.sdk._exceptions import SFEnterpriseError, SFFIPSError

        exc = SFFIPSError("TLS 1.0 detected")
        assert isinstance(exc, SFEnterpriseError)
        assert "FIPS" in str(exc)

    def test_airgap_error(self) -> None:
        from spanforge.sdk._exceptions import SFAirGapError, SFEnterpriseError

        exc = SFAirGapError("blocked")
        assert isinstance(exc, SFEnterpriseError)

    def test_security_scan_error(self) -> None:
        from spanforge.sdk._exceptions import SFEnterpriseError, SFSecurityScanError

        exc = SFSecurityScanError("invalid category")
        assert isinstance(exc, SFEnterpriseError)

    def test_secrets_in_logs_error(self) -> None:
        from spanforge.sdk._exceptions import SFEnterpriseError, SFSecretsInLogsError

        exc = SFSecretsInLogsError(5)
        assert isinstance(exc, SFEnterpriseError)
        assert "5" in str(exc)


# ===========================================================================
# Enterprise Client — sdk/enterprise.py
# ===========================================================================


@pytest.mark.unit
class TestEnterpriseClient:
    """SFEnterpriseClient multi-tenancy, encryption, and air-gap tests."""

    def _make_client(self) -> Any:
        from spanforge.sdk.enterprise import SFEnterpriseClient

        return SFEnterpriseClient(_make_config())

    # --- Multi-tenancy (ENT-001 / ENT-002) ---

    def test_register_tenant(self) -> None:
        client = self._make_client()
        tenant = client.register_tenant(
            project_id="proj-1",
            org_id="org-1",
            data_residency="eu",
        )
        assert tenant.project_id == "proj-1"
        assert tenant.org_id == "org-1"
        assert tenant.data_residency == "eu"
        assert len(tenant.org_secret) == 64  # sha256 hex digest

    def test_register_tenant_invalid_residency(self) -> None:
        from spanforge.sdk._exceptions import SFDataResidencyError

        client = self._make_client()
        with pytest.raises(SFDataResidencyError):
            client.register_tenant(
                project_id="p1",
                org_id="o1",
                data_residency="mars",
            )

    def test_get_tenant(self) -> None:
        client = self._make_client()
        client.register_tenant(project_id="p1", org_id="o1")
        assert client.get_tenant("p1") is not None
        assert client.get_tenant("nonexistent") is None

    def test_list_tenants(self) -> None:
        client = self._make_client()
        client.register_tenant(project_id="p1", org_id="o1")
        client.register_tenant(project_id="p2", org_id="o1")
        assert len(client.list_tenants()) == 2

    def test_get_isolation_scope(self) -> None:
        client = self._make_client()
        client.register_tenant(project_id="p1", org_id="o1")
        scope = client.get_isolation_scope("p1")
        assert f"{scope.org_id}:{scope.project_id}" == "o1:p1"

    def test_get_isolation_scope_not_registered(self) -> None:
        from spanforge.sdk._exceptions import SFIsolationError

        client = self._make_client()
        with pytest.raises(SFIsolationError):
            client.get_isolation_scope("nonexistent")

    def test_check_cross_project_access_disabled(self) -> None:
        from spanforge.sdk._exceptions import SFIsolationError

        client = self._make_client()
        client.register_tenant(project_id="p1", org_id="o1")
        with pytest.raises(SFIsolationError, match="cross_project_read"):
            client.check_cross_project_access("p1", ["p2"])

    def test_check_cross_project_access_allowed(self) -> None:
        client = self._make_client()
        client.register_tenant(
            project_id="p1",
            org_id="o1",
            cross_project_read=True,
            allowed_project_ids=["p2"],
        )
        # Should not raise
        client.check_cross_project_access("p1", ["p2"])

    def test_check_cross_project_access_not_in_allowlist(self) -> None:
        from spanforge.sdk._exceptions import SFIsolationError

        client = self._make_client()
        client.register_tenant(
            project_id="p1",
            org_id="o1",
            cross_project_read=True,
            allowed_project_ids=["p2"],
        )
        with pytest.raises(SFIsolationError, match="not in the allowed"):
            client.check_cross_project_access("p1", ["p3"])

    def test_check_cross_project_not_registered(self) -> None:
        from spanforge.sdk._exceptions import SFIsolationError

        client = self._make_client()
        with pytest.raises(SFIsolationError):
            client.check_cross_project_access("nonexist", ["p2"])

    # --- Data residency (ENT-004 / ENT-005) ---

    def test_get_endpoint_for_project(self) -> None:
        client = self._make_client()
        client.register_tenant(project_id="p1", org_id="o1", data_residency="eu")
        assert "eu" in client.get_endpoint_for_project("p1")

    def test_get_endpoint_unregistered_project(self) -> None:
        client = self._make_client()
        assert "api.spanforge.dev" in client.get_endpoint_for_project("unknown")

    def test_enforce_data_residency_pass(self) -> None:
        client = self._make_client()
        client.register_tenant(project_id="p1", org_id="o1", data_residency="eu")
        # Should not raise
        client.enforce_data_residency("p1", "eu")

    def test_enforce_data_residency_global(self) -> None:
        client = self._make_client()
        client.register_tenant(project_id="p1", org_id="o1", data_residency="global")
        # Global allows any region
        client.enforce_data_residency("p1", "us")

    def test_enforce_data_residency_fail(self) -> None:
        from spanforge.sdk._exceptions import SFDataResidencyError

        client = self._make_client()
        client.register_tenant(project_id="p1", org_id="o1", data_residency="eu")
        with pytest.raises(SFDataResidencyError):
            client.enforce_data_residency("p1", "us")

    def test_enforce_data_residency_no_tenant(self) -> None:
        client = self._make_client()
        # No tenant → no enforcement → should not raise
        client.enforce_data_residency("unknown", "us")

    # --- Encryption (ENT-010 through ENT-013) ---

    def test_configure_encryption(self) -> None:
        client = self._make_client()
        enc = client.configure_encryption(encrypt_at_rest=True, kms_provider="aws")
        assert enc.encrypt_at_rest is True
        assert enc.kms_provider == "aws"

    def test_configure_encryption_invalid_kms(self) -> None:
        from spanforge.sdk._exceptions import SFEncryptionError

        client = self._make_client()
        with pytest.raises(SFEncryptionError, match="Unknown KMS"):
            client.configure_encryption(kms_provider="oracle")

    def test_get_encryption_config(self) -> None:
        client = self._make_client()
        enc = client.get_encryption_config()
        assert enc.encrypt_at_rest is False

    def test_encrypt_payload(self) -> None:
        client = self._make_client()
        client.configure_encryption(encrypt_at_rest=True)
        key = secrets.token_bytes(32)
        result = client.encrypt_payload(b"hello world", key)
        assert "ciphertext" in result
        assert "nonce" in result
        assert "tag" in result
        assert result["algorithm"] == "aes-256-gcm"

    def test_encrypt_payload_wrong_key_size(self) -> None:
        from spanforge.sdk._exceptions import SFEncryptionError

        client = self._make_client()
        client.configure_encryption(encrypt_at_rest=True)
        with pytest.raises(SFEncryptionError, match="32-byte"):
            client.encrypt_payload(b"data", b"short")

    def test_encrypt_payload_not_enabled(self) -> None:
        from spanforge.sdk._exceptions import SFEncryptionError

        client = self._make_client()
        with pytest.raises(SFEncryptionError, match="not enabled"):
            client.encrypt_payload(b"data", secrets.token_bytes(32))

    def test_decrypt_payload(self) -> None:
        client = self._make_client()
        client.configure_encryption(encrypt_at_rest=True)
        key = secrets.token_bytes(32)
        enc = client.encrypt_payload(b"hello world", key)
        decrypted = client.decrypt_payload(
            enc["ciphertext"], enc["nonce"], enc["tag"], key
        )
        assert isinstance(decrypted, bytes)

    def test_decrypt_payload_bad_tag(self) -> None:
        from spanforge.sdk._exceptions import SFEncryptionError

        client = self._make_client()
        client.configure_encryption(encrypt_at_rest=True)
        key = secrets.token_bytes(32)
        enc = client.encrypt_payload(b"hello", key)
        with pytest.raises(SFEncryptionError, match="Tag verification"):
            client.decrypt_payload(enc["ciphertext"], enc["nonce"], "00" * 16, key)

    def test_decrypt_not_enabled(self) -> None:
        from spanforge.sdk._exceptions import SFEncryptionError

        client = self._make_client()
        with pytest.raises(SFEncryptionError, match="not enabled"):
            client.decrypt_payload("aa", "bb", "cc", secrets.token_bytes(32))

    # --- Air-gap (ENT-020 through ENT-023) ---

    def test_configure_airgap(self) -> None:
        client = self._make_client()
        cfg = client.configure_airgap(offline=True, self_hosted=True)
        assert cfg.offline is True
        assert cfg.self_hosted is True

    def test_get_airgap_config(self) -> None:
        client = self._make_client()
        cfg = client.get_airgap_config()
        assert cfg.offline is False

    def test_assert_network_allowed(self) -> None:
        client = self._make_client()
        # Should not raise when offline=False
        client.assert_network_allowed()

    def test_assert_network_blocked_offline(self) -> None:
        from spanforge.sdk._exceptions import SFAirGapError

        client = self._make_client()
        client.configure_airgap(offline=True)
        with pytest.raises(SFAirGapError):
            client.assert_network_allowed()

    def test_check_health_endpoint(self) -> None:
        client = self._make_client()
        result = client.check_health_endpoint("sf-pii", "/healthz")
        assert result.ok is True
        assert result.service == "sf-pii"
        assert result.endpoint == "/healthz"

    def test_check_health_endpoint_self_hosted(self) -> None:
        client = self._make_client()
        client.configure_airgap(self_hosted=True)
        result = client.check_health_endpoint("sf-audit", "/readyz")
        assert result.ok is True
        assert result.latency_ms == 0.1

    def test_check_all_services_health(self) -> None:
        client = self._make_client()
        results = client.check_all_services_health()
        # 8 services × 2 endpoints (/healthz + /readyz) = 16
        assert len(results) == 16
        assert all(r.ok for r in results)

    # --- Status ---

    def test_get_status_empty(self) -> None:
        client = self._make_client()
        status = client.get_status()
        assert status.status == "ok"
        assert status.multi_tenancy_enabled is False
        assert status.tenant_count == 0

    def test_get_status_with_tenants(self) -> None:
        client = self._make_client()
        client.register_tenant(project_id="p1", org_id="o1", data_residency="eu")
        client.register_tenant(project_id="p2", org_id="o1", data_residency="eu")
        status = client.get_status()
        assert status.multi_tenancy_enabled is True
        assert status.tenant_count == 2
        assert status.data_residency == "eu"

    def test_get_status_mixed_residency(self) -> None:
        client = self._make_client()
        client.register_tenant(project_id="p1", org_id="o1", data_residency="eu")
        client.register_tenant(project_id="p2", org_id="o1", data_residency="us")
        status = client.get_status()
        assert status.data_residency == "mixed"

    def test_get_status_encryption_on(self) -> None:
        client = self._make_client()
        client.configure_encryption(encrypt_at_rest=True, fips_mode=False)
        status = client.get_status()
        assert status.encryption_at_rest is True

    def test_get_status_offline(self) -> None:
        client = self._make_client()
        client.configure_airgap(offline=True)
        status = client.get_status()
        assert status.offline_mode is True


# ===========================================================================
# Security Client — sdk/security.py
# ===========================================================================


@pytest.mark.unit
class TestSecurityClient:
    """SFSecurityClient OWASP, STRIDE, scanning, and logs audit tests."""

    def _make_client(self) -> Any:
        from spanforge.sdk.security import SFSecurityClient

        return SFSecurityClient(_make_config())

    # --- OWASP API Security Top 10 (ENT-030) ---

    def test_run_owasp_audit_defaults_pass(self) -> None:
        client = self._make_client()
        result = client.run_owasp_audit(
            auth_mechanisms=["bearer"],
            rate_limiting_enabled=True,
            input_validation_enabled=True,
            ssrf_protection_enabled=True,
        )
        assert result.pass_ is True
        assert len(result.categories) == 10

    def test_run_owasp_audit_no_auth_fails(self) -> None:
        client = self._make_client()
        result = client.run_owasp_audit(auth_mechanisms=[])
        assert result.pass_ is False
        assert result.categories["API2"]["status"] == "fail"

    def test_run_owasp_audit_no_rate_limiting_fails(self) -> None:
        client = self._make_client()
        result = client.run_owasp_audit(
            auth_mechanisms=["bearer"],
            rate_limiting_enabled=False,
        )
        assert result.pass_ is False
        assert result.categories["API4"]["status"] == "fail"

    def test_run_owasp_audit_no_ssrf_protection_fails(self) -> None:
        client = self._make_client()
        result = client.run_owasp_audit(
            auth_mechanisms=["bearer"],
            ssrf_protection_enabled=False,
        )
        assert result.pass_ is False
        assert result.categories["API7"]["status"] == "fail"

    def test_run_owasp_audit_no_input_validation_fails(self) -> None:
        client = self._make_client()
        result = client.run_owasp_audit(
            auth_mechanisms=["bearer"],
            input_validation_enabled=False,
        )
        assert result.pass_ is False
        assert result.categories["API8"]["status"] == "fail"

    # --- STRIDE threat model (ENT-031) ---

    def test_add_threat(self) -> None:
        client = self._make_client()
        entry = client.add_threat(
            service="sf-identity",
            category="spoofing",
            threat="Credential theft",
            mitigation="MFA required",
            risk_level="high",
        )
        assert entry.category == "spoofing"
        assert entry.risk_level == "high"

    def test_add_threat_invalid_category(self) -> None:
        from spanforge.sdk._exceptions import SFSecurityScanError

        client = self._make_client()
        with pytest.raises(SFSecurityScanError, match="Unknown STRIDE"):
            client.add_threat(
                service="sf-identity",
                category="flying",
                threat="test",
                mitigation="test",
            )

    def test_get_threat_model(self) -> None:
        client = self._make_client()
        client.add_threat("sf-pii", "tampering", "Data corruption", "HMAC chain")
        client.add_threat("sf-audit", "repudiation", "Log deletion", "WORM storage")
        assert len(client.get_threat_model()) == 2
        assert len(client.get_threat_model(service="sf-pii")) == 1

    def test_generate_default_threat_model(self) -> None:
        client = self._make_client()
        entries = client.generate_default_threat_model()
        assert len(entries) == 10  # 10 default threats
        categories = {e.category for e in entries}
        # Should cover at least 5 of the 6 STRIDE categories
        assert len(categories) >= 5

    # --- Dependency scanning (ENT-033) ---

    def test_scan_dependencies_empty(self) -> None:
        client = self._make_client()
        assert client.scan_dependencies() == []

    def test_scan_dependencies_clean(self) -> None:
        client = self._make_client()
        result = client.scan_dependencies(packages={"requests": "2.31.0"})
        assert result == []

    # --- Static analysis (ENT-034) ---

    def test_run_static_analysis_empty(self) -> None:
        client = self._make_client()
        assert client.run_static_analysis() == []

    def test_run_static_analysis_clean(self) -> None:
        client = self._make_client()
        result = client.run_static_analysis(source_files=["src/foo.py"])
        assert result == []

    # --- Secrets in logs (ENT-035) ---

    def test_audit_logs_for_secrets_clean(self) -> None:
        client = self._make_client()
        count = client.audit_logs_for_secrets(["INFO: normal log line"])
        assert count == 0

    def test_audit_logs_for_secrets_detects_api_key(self) -> None:
        from spanforge.sdk._exceptions import SFSecretsInLogsError

        client = self._make_client()
        with pytest.raises(SFSecretsInLogsError):
            client.audit_logs_for_secrets([
                "ERROR: key=sf_live_" + "a" * 48,
            ])

    def test_audit_logs_for_secrets_detects_jwt(self) -> None:
        from spanforge.sdk._exceptions import SFSecretsInLogsError

        client = self._make_client()
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.dGVzdHNpZ25hdHVyZQ"
        with pytest.raises(SFSecretsInLogsError):
            client.audit_logs_for_secrets([f"WARNING: token={jwt}"])

    def test_audit_logs_for_secrets_detects_aws_key(self) -> None:
        from spanforge.sdk._exceptions import SFSecretsInLogsError

        client = self._make_client()
        with pytest.raises(SFSecretsInLogsError):
            client.audit_logs_for_secrets(["ERROR: key=AKIA1234567890123456"])

    def test_audit_logs_for_secrets_detects_github_token(self) -> None:
        from spanforge.sdk._exceptions import SFSecretsInLogsError

        client = self._make_client()
        with pytest.raises(SFSecretsInLogsError):
            client.audit_logs_for_secrets([
                "WARNING: ghp_" + "a" * 36,
            ])

    def test_audit_logs_for_secrets_detects_openai_key(self) -> None:
        from spanforge.sdk._exceptions import SFSecretsInLogsError

        client = self._make_client()
        with pytest.raises(SFSecretsInLogsError):
            client.audit_logs_for_secrets([
                "ERROR: sk-" + "a" * 32,
            ])

    def test_audit_logs_for_secrets_detects_private_key(self) -> None:
        from spanforge.sdk._exceptions import SFSecretsInLogsError

        client = self._make_client()
        with pytest.raises(SFSecretsInLogsError):
            client.audit_logs_for_secrets([
                "ERROR: -----BEGIN RSA PRIVATE KEY-----",
            ])

    def test_audit_logs_safe_variant(self) -> None:
        client = self._make_client()
        count = client.audit_logs_for_secrets_safe([
            "ERROR: key=sf_live_" + "a" * 48,
            "INFO: normal line",
        ])
        assert count == 1

    # --- Full scan ---

    def test_run_full_scan_clean(self) -> None:
        client = self._make_client()
        result = client.run_full_scan()
        assert result.pass_ is True
        assert result.secrets_in_logs == 0

    def test_run_full_scan_with_secrets(self) -> None:
        client = self._make_client()
        result = client.run_full_scan(
            log_lines=["ERROR: key=sf_live_" + "a" * 48],
        )
        assert result.pass_ is False
        assert result.secrets_in_logs == 1

    def test_get_last_scan(self) -> None:
        client = self._make_client()
        assert client.get_last_scan() is None
        client.run_full_scan()
        assert client.get_last_scan() is not None

    def test_get_last_audit(self) -> None:
        client = self._make_client()
        assert client.get_last_audit() is None
        client.run_owasp_audit(auth_mechanisms=["bearer"])
        assert client.get_last_audit() is not None


# ===========================================================================
# SDK __init__.py — Singletons & Exports
# ===========================================================================


@pytest.mark.unit
class TestSDKExports:
    """Verify Phase 11 types, exceptions, and clients are exported."""

    def test_enterprise_singleton_exists(self) -> None:
        from spanforge.sdk import sf_enterprise

        assert sf_enterprise is not None

    def test_security_singleton_exists(self) -> None:
        from spanforge.sdk import sf_security

        assert sf_security is not None

    def test_enterprise_client_exported(self) -> None:
        from spanforge.sdk import SFEnterpriseClient

        assert SFEnterpriseClient is not None

    def test_security_client_exported(self) -> None:
        from spanforge.sdk import SFSecurityClient

        assert SFSecurityClient is not None

    def test_phase11_types_exported(self) -> None:
        from spanforge.sdk import (
            AirGapConfig,
            DataResidency,
            DependencyVulnerability,
            EncryptionConfig,
            EnterpriseStatusInfo,
            HealthEndpointResult,
            IsolationScope,
            SecurityAuditResult,
            SecurityScanResult,
            StaticAnalysisFinding,
            TenantConfig,
            ThreatModelEntry,
        )

        assert all([
            AirGapConfig,
            DataResidency,
            DependencyVulnerability,
            EncryptionConfig,
            EnterpriseStatusInfo,
            HealthEndpointResult,
            IsolationScope,
            SecurityAuditResult,
            SecurityScanResult,
            StaticAnalysisFinding,
            TenantConfig,
            ThreatModelEntry,
        ])

    def test_phase11_exceptions_exported(self) -> None:
        from spanforge.sdk import (
            SFAirGapError,
            SFDataResidencyError,
            SFEncryptionError,
            SFEnterpriseError,
            SFFIPSError,
            SFIsolationError,
            SFSecurityScanError,
            SFSecretsInLogsError,
        )

        assert all([
            SFAirGapError,
            SFDataResidencyError,
            SFEncryptionError,
            SFEnterpriseError,
            SFFIPSError,
            SFIsolationError,
            SFSecurityScanError,
            SFSecretsInLogsError,
        ])

    def test_configure_recreates_enterprise_and_security(self) -> None:
        from spanforge.sdk import SFClientConfig, SecretStr, configure, sf_enterprise, sf_security

        old_ent = sf_enterprise
        old_sec = sf_security
        configure(SFClientConfig(
            endpoint="http://localhost:9999",
            api_key=SecretStr("sf_test_reconfig"),
            signing_key="new-key",
        ))
        import spanforge.sdk as sdk

        assert sdk.sf_enterprise is not old_ent
        assert sdk.sf_security is not old_sec


# ===========================================================================
# CLI — enterprise & security subcommands
# ===========================================================================


@pytest.mark.unit
class TestCLIEnterprise:
    """CLI ``spanforge enterprise`` subcommand tests."""

    def test_enterprise_status_text(self, capsys: pytest.CaptureFixture[str]) -> None:
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc:
            main(["enterprise", "status"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "Enterprise Hardening Status" in out

    def test_enterprise_status_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc:
            main(["enterprise", "status", "--format", "json"])
        assert exc.value.code == 0
        data = json.loads(capsys.readouterr().out)
        assert "status" in data

    def test_enterprise_health_text(self, capsys: pytest.CaptureFixture[str]) -> None:
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc:
            main(["enterprise", "health"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "HEALTHY" in out

    def test_enterprise_health_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc:
            main(["enterprise", "health", "--format", "json"])
        assert exc.value.code == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)

    def test_enterprise_encrypt_config(self, capsys: pytest.CaptureFixture[str]) -> None:
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc:
            main(["enterprise", "encrypt-config"])
        assert exc.value.code == 0
        data = json.loads(capsys.readouterr().out)
        assert "encrypt_at_rest" in data

    def test_enterprise_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc:
            main(["enterprise"])
        assert exc.value.code == 2


@pytest.mark.unit
class TestCLISecurity:
    """CLI ``spanforge security`` subcommand tests."""

    def test_security_owasp_text(self, capsys: pytest.CaptureFixture[str]) -> None:
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc:
            main(["security", "owasp"])
        # May fail (no auth configured), so exit code could be 0 or 1
        out = capsys.readouterr().out
        assert "OWASP" in out

    def test_security_owasp_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc:
            main(["security", "owasp", "--format", "json"])
        data = json.loads(capsys.readouterr().out)
        assert "categories" in data

    def test_security_threat_model_text(self, capsys: pytest.CaptureFixture[str]) -> None:
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc:
            main(["security", "threat-model"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "STRIDE" in out

    def test_security_threat_model_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc:
            main(["security", "threat-model", "--format", "json"])
        assert exc.value.code == 0
        data = json.loads(capsys.readouterr().out)
        assert isinstance(data, list)
        assert len(data) > 0

    def test_security_scan_text(self, capsys: pytest.CaptureFixture[str]) -> None:
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc:
            main(["security", "scan"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "Security Scan" in out

    def test_security_scan_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc:
            main(["security", "scan", "--format", "json"])
        assert exc.value.code == 0
        data = json.loads(capsys.readouterr().out)
        assert "pass_" in data

    def test_security_audit_logs_no_file(self, capsys: pytest.CaptureFixture[str]) -> None:
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc:
            main(["security", "audit-logs"])
        assert exc.value.code == 0
        out = capsys.readouterr().out
        assert "clean" in out

    def test_security_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc:
            main(["security"])
        assert exc.value.code == 2


# ===========================================================================
# Server — /healthz, /readyz, enterprise, security endpoints
# ===========================================================================


@pytest.mark.unit
class TestServerEndpoints:
    """HTTP server endpoint tests for Phase 11."""

    def _get(self, handler_class: type, path: str) -> tuple[int, dict[str, Any]]:
        """Simulate a GET request to the server handler."""
        import io
        from unittest.mock import MagicMock

        handler = handler_class.__new__(handler_class)
        handler.path = path
        handler.headers = {}
        handler.wfile = io.BytesIO()

        # Mock response methods
        responses: list[tuple[int, str]] = []

        def send_response(code: int) -> None:
            responses.append((code, ""))

        def send_header(name: str, value: str) -> None:
            pass

        def end_headers() -> None:
            pass

        handler.send_response = send_response
        handler.send_header = send_header
        handler.end_headers = end_headers

        handler.do_GET()

        body = handler.wfile.getvalue()
        status = responses[0][0] if responses else 500
        try:
            data = json.loads(body.decode())
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = {}
        return status, data

    def test_healthz(self) -> None:
        from spanforge._server import _TraceAPIHandler

        status, data = self._get(_TraceAPIHandler, "/healthz")
        assert status == 200
        assert data.get("status") == "ok"

    def test_readyz(self) -> None:
        from spanforge._server import _TraceAPIHandler

        status, data = self._get(_TraceAPIHandler, "/readyz")
        assert status == 200
        assert data.get("ready") is True

    def test_enterprise_status(self) -> None:
        from spanforge._server import _TraceAPIHandler

        status, data = self._get(_TraceAPIHandler, "/v1/enterprise/status")
        assert status == 200
        assert "status" in data

    def test_enterprise_health(self) -> None:
        from spanforge._server import _TraceAPIHandler

        status, data = self._get(_TraceAPIHandler, "/v1/enterprise/health")
        assert status == 200
        assert "healthy" in data

    def test_security_owasp(self) -> None:
        from spanforge._server import _TraceAPIHandler

        status, data = self._get(_TraceAPIHandler, "/v1/security/owasp")
        assert status == 200
        assert "categories" in data

    def test_security_threat_model(self) -> None:
        from spanforge._server import _TraceAPIHandler

        status, data = self._get(_TraceAPIHandler, "/v1/security/threat-model")
        assert status == 200
        assert isinstance(data, list)

    def test_security_scan(self) -> None:
        from spanforge._server import _TraceAPIHandler

        status, data = self._get(_TraceAPIHandler, "/v1/security/scan")
        assert status == 200
        assert "pass_" in data


# ===========================================================================
# Docker & Helm artifact existence checks
# ===========================================================================


@pytest.mark.unit
class TestDeploymentArtifacts:
    """Verify Docker Compose self-hosted and Helm chart files exist."""

    def test_docker_compose_selfhosted_exists(self) -> None:
        import os

        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "docker-compose.selfhosted.yml",
        )
        assert os.path.isfile(path), "docker-compose.selfhosted.yml not found"

    def test_helm_chart_yaml_exists(self) -> None:
        import os

        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "helm",
            "spanforge",
            "Chart.yaml",
        )
        assert os.path.isfile(path), "helm/spanforge/Chart.yaml not found"

    def test_helm_values_yaml_exists(self) -> None:
        import os

        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "helm",
            "spanforge",
            "values.yaml",
        )
        assert os.path.isfile(path), "helm/spanforge/values.yaml not found"

    def test_helm_deployment_template_exists(self) -> None:
        import os

        path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "helm",
            "spanforge",
            "templates",
            "deployment.yaml",
        )
        assert os.path.isfile(path), "helm/spanforge/templates/deployment.yaml not found"
