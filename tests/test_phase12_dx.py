"""Unit tests for Phase 12 — Developer Experience features."""

from __future__ import annotations

import argparse

import pytest

# -----------------------------------------------------------------------
# DX-003: Mock library unit tests
# -----------------------------------------------------------------------

class TestMockBase:
    """Tests for the _MockBase call recording and assertion helpers."""

    def test_record_and_assert_called(self) -> None:
        from spanforge.testing_mocks import MockSFPII

        m = MockSFPII()
        m.scan({"text": "hello"})
        m.assert_called("scan")

    def test_assert_not_called_raises(self) -> None:
        from spanforge.testing_mocks import MockSFPII

        m = MockSFPII()
        m.scan({"text": "hello"})
        with pytest.raises(AssertionError, match="was called"):
            m.assert_not_called("scan")

    def test_assert_called_raises_when_not(self) -> None:
        from spanforge.testing_mocks import MockSFPII

        m = MockSFPII()
        with pytest.raises(AssertionError, match="was never called"):
            m.assert_called("scan")

    def test_call_count(self) -> None:
        from spanforge.testing_mocks import MockSFPII

        m = MockSFPII()
        m.scan({"a": 1})
        m.scan({"b": 2})
        m.redact({"c": 3})
        assert m.call_count("scan") == 2
        assert m.call_count("redact") == 1
        assert m.call_count("anonymize") == 0

    def test_configure_response(self) -> None:
        from spanforge.sdk._types import SFPIIScanResult
        from spanforge.testing_mocks import MockSFPII

        m = MockSFPII()
        custom = SFPIIScanResult(hits=[{"type": "SSN"}], scanned=1)
        m.configure_response("scan", custom)
        result = m.scan({"text": "123-45-6789"})
        assert result is custom

    def test_reset(self) -> None:
        from spanforge.testing_mocks import MockSFPII

        m = MockSFPII()
        m.scan({"x": 1})
        m.configure_response("scan", "custom")
        m.reset()
        assert m.calls == []
        assert m.call_count("scan") == 0


class TestMockAllServices:
    """Tests for the mock_all_services context manager."""

    def test_replaces_and_restores_singletons(self) -> None:
        from spanforge import sdk
        from spanforge.testing_mocks import MockSFPII, mock_all_services

        original_pii = sdk.sf_pii
        with mock_all_services() as mocks:
            assert isinstance(sdk.sf_pii, MockSFPII)
            assert sdk.sf_pii is mocks["sf_pii"]
        assert sdk.sf_pii is original_pii

    def test_all_11_services_mocked(self) -> None:
        from spanforge.testing_mocks import mock_all_services

        expected = {
            "sf_identity", "sf_pii", "sf_secrets", "sf_audit",
            "sf_observe", "sf_gate", "sf_cec", "sf_alert",
            "sf_trust", "sf_enterprise", "sf_security",
        }
        with mock_all_services() as mocks:
            assert set(mocks.keys()) == expected


class TestMockIdentity:
    """Smoke tests for MockSFIdentity."""

    def test_issue_api_key(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity

        m = MockSFIdentity()
        result = m.issue_api_key(scopes=["read"])
        assert result.key_id == "mock-key-id"
        assert "read" in result.scopes

    def test_verify_token(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity

        m = MockSFIdentity()
        claims = m.verify_token("test.jwt")
        assert claims.subject == "mock-subject"

    def test_refresh_token(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity
        m = MockSFIdentity()
        assert m.refresh_token() == "mock.refreshed.jwt"
        m.assert_called("refresh_token")

    def test_create_session(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity
        m = MockSFIdentity()
        assert m.create_session("key") == "mock.session.jwt"

    def test_introspect(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity
        m = MockSFIdentity()
        r = m.introspect("tok")
        assert r.active is True

    def test_rotate_key(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity
        m = MockSFIdentity()
        r = m.rotate_key("k1")
        assert r.key_id == "mock-key-id"

    def test_revoke_key(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity
        m = MockSFIdentity()
        m.revoke_key("k1")
        m.assert_called("revoke_key")

    def test_issue_magic_link(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity
        m = MockSFIdentity()
        r = m.issue_magic_link("a@b.com")
        assert r.link_id == "mock-magic-link"

    def test_enroll_totp(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity
        m = MockSFIdentity()
        r = m.enroll_totp("k1")
        assert r.qr_uri.startswith("otpauth://")

    def test_verify_backup_code(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity
        m = MockSFIdentity()
        assert m.verify_backup_code("k1", "000000") is True

    def test_check_rate_limit(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity
        m = MockSFIdentity()
        r = m.check_rate_limit("k1")
        assert r.remaining == 599

    def test_record_request(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity
        m = MockSFIdentity()
        assert m.record_request("k1") is True

    def test_require_scope(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity
        m = MockSFIdentity()
        m.require_scope(None, "read")
        m.assert_called("require_scope")

    def test_get_jwks(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity
        m = MockSFIdentity()
        assert "keys" in m.get_jwks()

    def test_check_ip_allowlist(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity
        m = MockSFIdentity()
        m.check_ip_allowlist("k1", "1.2.3.4")
        m.assert_called("check_ip_allowlist")

    def test_saml_metadata(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity
        m = MockSFIdentity()
        assert "<mock-saml/>" in m.saml_metadata()

    def test_mfa_policy(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity
        m = MockSFIdentity()
        m.set_mfa_policy("proj", True)
        assert m.get_mfa_policy("proj") is False  # default mock
        m.assert_called("set_mfa_policy")
        m.assert_called("get_mfa_policy")

    def test_set_key_tier(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity
        m = MockSFIdentity()
        m.set_key_tier("k1", "enterprise")
        m.assert_called("set_key_tier")

    def test_consume_quota(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity
        m = MockSFIdentity()
        assert m.consume_quota("k1") is True

    def test_get_quota_usage(self) -> None:
        from spanforge.testing_mocks import MockSFIdentity
        m = MockSFIdentity()
        r = m.get_quota_usage("k1")
        assert r["limit"] == 1000


class TestMockAudit:
    """Smoke tests for MockSFAudit."""

    def test_append(self) -> None:
        from spanforge.testing_mocks import MockSFAudit

        m = MockSFAudit()
        result = m.append({"action": "test"}, "test_v1")
        assert result.record_id == "mock-record-id"
        assert result.schema_key == "test_v1"

    def test_sign(self) -> None:
        from spanforge.testing_mocks import MockSFAudit

        m = MockSFAudit()
        signed = m.sign({"action": "test"})
        assert signed.signature == "mock-sig"

    def test_verify_chain(self) -> None:
        from spanforge.testing_mocks import MockSFAudit
        m = MockSFAudit()
        r = m.verify_chain([{"record_id": "a"}])
        assert r["valid"] is True

    def test_export(self) -> None:
        from spanforge.testing_mocks import MockSFAudit
        m = MockSFAudit()
        assert m.export("key") == []

    def test_get_trust_scorecard(self) -> None:
        from spanforge.testing_mocks import MockSFAudit
        m = MockSFAudit()
        assert m.get_trust_scorecard("proj") is None

    def test_get_status(self) -> None:
        from spanforge.testing_mocks import MockSFAudit
        m = MockSFAudit()
        s = m.get_status()
        assert s.status == "ok"

    def test_close(self) -> None:
        from spanforge.testing_mocks import MockSFAudit
        m = MockSFAudit()
        m.close()
        m.assert_called("close")


class TestMockGate:
    """Smoke tests for MockSFGate."""

    def test_evaluate(self) -> None:
        from spanforge.testing_mocks import MockSFGate

        m = MockSFGate()
        result = m.evaluate("g1", {"score": 0.9})
        assert result.verdict == "PASS"
        assert result.gate_id == "g1"

    def test_run_trust_gate(self) -> None:
        from spanforge.testing_mocks import MockSFGate
        m = MockSFGate()
        r = m.run_trust_gate("proj-1")
        assert r.verdict == "PASS"
        assert r.project_id == "proj-1"

    def test_evaluate_prri(self) -> None:
        from spanforge.testing_mocks import MockSFGate
        m = MockSFGate()
        r = m.evaluate_prri("proj-1")
        assert r.verdict == "GREEN"
        assert r.allow is True

    def test_list_artifacts(self) -> None:
        from spanforge.testing_mocks import MockSFGate
        m = MockSFGate()
        assert m.list_artifacts("g1") == []

    def test_get_status(self) -> None:
        from spanforge.testing_mocks import MockSFGate
        m = MockSFGate()
        assert m.get_status().status == "ok"


class TestMockAlert:
    """Smoke tests for MockSFAlert."""

    def test_publish(self) -> None:
        from spanforge.testing_mocks import MockSFAlert

        m = MockSFAlert()
        result = m.publish("test.topic", {"msg": "hi"})
        assert result.alert_id == "mock-alert-id"
        assert result.suppressed is False

    def test_register_topic(self) -> None:
        from spanforge.testing_mocks import MockSFAlert
        m = MockSFAlert()
        m.register_topic("t1", "desc")
        m.assert_called("register_topic")

    def test_acknowledge(self) -> None:
        from spanforge.testing_mocks import MockSFAlert
        m = MockSFAlert()
        assert m.acknowledge("alert-1") is True

    def test_get_alert_history(self) -> None:
        from spanforge.testing_mocks import MockSFAlert
        m = MockSFAlert()
        assert m.get_alert_history() == []

    def test_get_status(self) -> None:
        from spanforge.testing_mocks import MockSFAlert
        m = MockSFAlert()
        assert m.get_status().status == "ok"

    def test_add_sink(self) -> None:
        from spanforge.testing_mocks import MockSFAlert
        m = MockSFAlert()
        m.add_sink(None, "webhook")
        m.assert_called("add_sink")

    def test_shutdown(self) -> None:
        from spanforge.testing_mocks import MockSFAlert
        m = MockSFAlert()
        m.shutdown()
        m.assert_called("shutdown")

    def test_healthy_property(self) -> None:
        from spanforge.testing_mocks import MockSFAlert
        m = MockSFAlert()
        assert m.healthy is True


class TestMockTrust:
    """Smoke tests for MockSFTrust."""

    def test_get_scorecard(self) -> None:
        from spanforge.testing_mocks import MockSFTrust

        m = MockSFTrust()
        sc = m.get_scorecard("proj-1")
        assert sc.overall_score == 1.0
        assert sc.colour_band == "green"

    def test_get_history(self) -> None:
        from spanforge.testing_mocks import MockSFTrust
        m = MockSFTrust()
        assert m.get_history("proj-1") == []

    def test_get_badge(self) -> None:
        from spanforge.testing_mocks import MockSFTrust
        m = MockSFTrust()
        r = m.get_badge("proj-1")
        assert r.colour_band == "green"
        assert "<svg" in r.svg

    def test_get_status(self) -> None:
        from spanforge.testing_mocks import MockSFTrust
        m = MockSFTrust()
        assert m.get_status().status == "ok"


class TestMockEnterprise:
    """Smoke tests for MockSFEnterprise."""

    def test_register_tenant(self) -> None:
        from spanforge.testing_mocks import MockSFEnterprise

        m = MockSFEnterprise()
        tc = m.register_tenant("proj-1", "org-1")
        assert tc.project_id == "proj-1"
        assert tc.org_id == "org-1"

    def test_get_tenant(self) -> None:
        from spanforge.testing_mocks import MockSFEnterprise
        m = MockSFEnterprise()
        assert m.get_tenant("proj-1") is None

    def test_list_tenants(self) -> None:
        from spanforge.testing_mocks import MockSFEnterprise
        m = MockSFEnterprise()
        assert m.list_tenants() == []

    def test_get_isolation_scope(self) -> None:
        from spanforge.testing_mocks import MockSFEnterprise
        m = MockSFEnterprise()
        r = m.get_isolation_scope("proj-1")
        assert r.project_id == "proj-1"

    def test_check_cross_project_access(self) -> None:
        from spanforge.testing_mocks import MockSFEnterprise
        m = MockSFEnterprise()
        m.check_cross_project_access("src", ["dst"])
        m.assert_called("check_cross_project_access")

    def test_get_endpoint_for_project(self) -> None:
        from spanforge.testing_mocks import MockSFEnterprise
        m = MockSFEnterprise()
        assert m.get_endpoint_for_project("proj-1").startswith("http")

    def test_enforce_data_residency(self) -> None:
        from spanforge.testing_mocks import MockSFEnterprise
        m = MockSFEnterprise()
        m.enforce_data_residency("proj-1", "eu-west-1")
        m.assert_called("enforce_data_residency")

    def test_configure_encryption(self) -> None:
        from spanforge.testing_mocks import MockSFEnterprise
        m = MockSFEnterprise()
        r = m.configure_encryption()
        assert r is not None

    def test_get_encryption_config(self) -> None:
        from spanforge.testing_mocks import MockSFEnterprise
        m = MockSFEnterprise()
        r = m.get_encryption_config()
        assert r is not None

    def test_encrypt_decrypt_payload(self) -> None:
        from spanforge.testing_mocks import MockSFEnterprise
        m = MockSFEnterprise()
        enc = m.encrypt_payload(b"hello", b"key")
        assert "ciphertext" in enc
        dec = m.decrypt_payload("aa", "bb", "cc", b"key")
        assert isinstance(dec, bytes)

    def test_configure_airgap(self) -> None:
        from spanforge.testing_mocks import MockSFEnterprise
        m = MockSFEnterprise()
        r = m.configure_airgap()
        assert r is not None

    def test_get_airgap_config(self) -> None:
        from spanforge.testing_mocks import MockSFEnterprise
        m = MockSFEnterprise()
        r = m.get_airgap_config()
        assert r is not None

    def test_assert_network_allowed(self) -> None:
        from spanforge.testing_mocks import MockSFEnterprise
        m = MockSFEnterprise()
        m.assert_network_allowed()
        m.assert_called("assert_network_allowed")

    def test_check_health_endpoint(self) -> None:
        from spanforge.testing_mocks import MockSFEnterprise
        m = MockSFEnterprise()
        r = m.check_health_endpoint("sf-pii")
        assert r.ok is True

    def test_check_all_services_health(self) -> None:
        from spanforge.testing_mocks import MockSFEnterprise
        m = MockSFEnterprise()
        assert m.check_all_services_health() == []

    def test_get_status(self) -> None:
        from spanforge.testing_mocks import MockSFEnterprise
        m = MockSFEnterprise()
        assert m.get_status().status == "ok"


class TestMockSecurity:
    """Smoke tests for MockSFSecurity."""

    def test_run_owasp_audit(self) -> None:
        from spanforge.testing_mocks import MockSFSecurity

        m = MockSFSecurity()
        result = m.run_owasp_audit()
        assert result.pass_ is True

    def test_add_threat(self) -> None:
        from spanforge.testing_mocks import MockSFSecurity
        m = MockSFSecurity()
        r = m.add_threat("svc", "cat", "threat", "mitigate")
        assert r.service == "svc"

    def test_get_threat_model(self) -> None:
        from spanforge.testing_mocks import MockSFSecurity
        m = MockSFSecurity()
        assert m.get_threat_model("svc") == []

    def test_generate_default_threat_model(self) -> None:
        from spanforge.testing_mocks import MockSFSecurity
        m = MockSFSecurity()
        assert m.generate_default_threat_model() == []

    def test_scan_dependencies(self) -> None:
        from spanforge.testing_mocks import MockSFSecurity
        m = MockSFSecurity()
        assert m.scan_dependencies() == []

    def test_run_static_analysis(self) -> None:
        from spanforge.testing_mocks import MockSFSecurity
        m = MockSFSecurity()
        assert m.run_static_analysis() == []

    def test_audit_logs_for_secrets(self) -> None:
        from spanforge.testing_mocks import MockSFSecurity
        m = MockSFSecurity()
        assert m.audit_logs_for_secrets(["line1"]) == 0

    def test_audit_logs_for_secrets_safe(self) -> None:
        from spanforge.testing_mocks import MockSFSecurity
        m = MockSFSecurity()
        assert m.audit_logs_for_secrets_safe(["line1"]) == 0

    def test_run_full_scan(self) -> None:
        from spanforge.testing_mocks import MockSFSecurity
        m = MockSFSecurity()
        r = m.run_full_scan()
        assert r.pass_ is True

    def test_get_last_scan(self) -> None:
        from spanforge.testing_mocks import MockSFSecurity
        m = MockSFSecurity()
        assert m.get_last_scan() is None

    def test_get_status(self) -> None:
        from spanforge.testing_mocks import MockSFSecurity
        m = MockSFSecurity()
        assert m.get_status()["status"] == "ok"


class TestMockPII:
    """Comprehensive tests for MockSFPII."""

    def test_scan(self) -> None:
        from spanforge.testing_mocks import MockSFPII
        m = MockSFPII()
        r = m.scan({"text": "hello"})
        assert r.scanned == 1

    def test_redact(self) -> None:
        from spanforge.testing_mocks import MockSFPII
        m = MockSFPII()
        r = m.redact({"text": "hello"})
        assert r.redaction_count == 0

    def test_contains_pii(self) -> None:
        from spanforge.testing_mocks import MockSFPII
        m = MockSFPII()
        assert m.contains_pii({"text": "hello"}) is False

    def test_assert_redacted(self) -> None:
        from spanforge.testing_mocks import MockSFPII
        m = MockSFPII()
        m.assert_redacted({"text": "hello"})
        m.assert_called("assert_redacted")

    def test_anonymize(self) -> None:
        from spanforge.testing_mocks import MockSFPII
        m = MockSFPII()
        r = m.anonymize("test text")
        assert r.text == "test text"

    def test_scan_text(self) -> None:
        from spanforge.testing_mocks import MockSFPII
        m = MockSFPII()
        r = m.scan_text("hello")
        assert r.detected is False

    def test_anonymise(self) -> None:
        from spanforge.testing_mocks import MockSFPII
        m = MockSFPII()
        r = m.anonymise({"x": 1})
        assert r.clean_payload == {"x": 1}

    def test_scan_batch(self) -> None:
        from spanforge.testing_mocks import MockSFPII
        m = MockSFPII()
        r = m.scan_batch(["a", "b"])
        assert len(r) == 2

    def test_apply_pipeline_action(self) -> None:
        from spanforge.testing_mocks import MockSFPII
        m = MockSFPII()
        r = m.apply_pipeline_action("text")
        assert r.blocked is False

    def test_get_status(self) -> None:
        from spanforge.testing_mocks import MockSFPII
        m = MockSFPII()
        assert m.get_status().status == "ok"

    def test_erase_subject(self) -> None:
        from spanforge.testing_mocks import MockSFPII
        m = MockSFPII()
        r = m.erase_subject("sub1", "proj1")
        assert r.subject_id == "sub1"

    def test_export_subject_data(self) -> None:
        from spanforge.testing_mocks import MockSFPII
        m = MockSFPII()
        r = m.export_subject_data("sub1", "proj1")
        assert r.subject_id == "sub1"

    def test_safe_harbor_deidentify(self) -> None:
        from spanforge.testing_mocks import MockSFPII
        m = MockSFPII()
        r = m.safe_harbor_deidentify("text")
        assert r.text == "text"

    def test_get_pii_stats(self) -> None:
        from spanforge.testing_mocks import MockSFPII
        m = MockSFPII()
        assert m.get_pii_stats("proj") == []


class TestMockSecrets:
    """Comprehensive tests for MockSFSecrets."""

    def test_scan(self) -> None:
        from spanforge.testing_mocks import MockSFSecrets
        m = MockSFSecrets()
        assert m.scan("text") is None

    def test_scan_batch(self) -> None:
        from spanforge.testing_mocks import MockSFSecrets
        m = MockSFSecrets()
        assert m.scan_batch(["a", "b"]) == []

    def test_get_status(self) -> None:
        from spanforge.testing_mocks import MockSFSecrets
        m = MockSFSecrets()
        assert m.get_status()["status"] == "ok"


class TestMockObserve:
    """Comprehensive tests for MockSFObserve."""

    def test_export_spans(self) -> None:
        from spanforge.testing_mocks import MockSFObserve
        m = MockSFObserve()
        r = m.export_spans([{"name": "t"}])
        assert r.exported_count == 1

    def test_emit_span(self) -> None:
        from spanforge.testing_mocks import MockSFObserve
        m = MockSFObserve()
        r = m.emit_span("test", {"k": "v"})
        assert "span_id" in r

    def test_add_annotation(self) -> None:
        from spanforge.testing_mocks import MockSFObserve
        m = MockSFObserve()
        assert m.add_annotation("deploy", {"v": "1"}) == "mock-annotation-id"

    def test_get_annotations(self) -> None:
        from spanforge.testing_mocks import MockSFObserve
        m = MockSFObserve()
        assert m.get_annotations("deploy", "2025-01-01", "2025-12-31") == []

    def test_healthy_property(self) -> None:
        from spanforge.testing_mocks import MockSFObserve
        m = MockSFObserve()
        assert m.healthy is True

    def test_last_export_at(self) -> None:
        from spanforge.testing_mocks import MockSFObserve
        m = MockSFObserve()
        assert m.last_export_at is None

    def test_get_status(self) -> None:
        from spanforge.testing_mocks import MockSFObserve
        m = MockSFObserve()
        assert m.get_status().status == "ok"


class TestMockCEC:
    """Comprehensive tests for MockSFCEC."""

    def test_build_bundle(self) -> None:
        from spanforge.testing_mocks import MockSFCEC
        m = MockSFCEC()
        r = m.build_bundle("proj-1", ("2025-01-01", "2025-12-31"))
        assert r.bundle_id == "mock-bundle"

    def test_verify_bundle(self) -> None:
        from spanforge.testing_mocks import MockSFCEC
        m = MockSFCEC()
        r = m.verify_bundle("/tmp/test.zip")
        assert r.overall_valid is True

    def test_generate_dpa(self) -> None:
        from spanforge.testing_mocks import MockSFCEC
        m = MockSFCEC()
        r = m.generate_dpa("proj-1", {"name": "C"}, {"name": "P"})
        assert r.document_id == "mock-dpa"

    def test_get_status(self) -> None:
        from spanforge.testing_mocks import MockSFCEC
        m = MockSFCEC()
        assert m.get_status().status == "ok"


# -----------------------------------------------------------------------
# DX-004: Sandbox mode
# -----------------------------------------------------------------------

class TestSandboxConfig:

    def test_default_false(self) -> None:
        from spanforge.sdk.config import SFConfigBlock
        assert SFConfigBlock().sandbox is False

    def test_env_override_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spanforge.sdk.config import SFConfigBlock, _apply_env_overrides
        cfg = SFConfigBlock()
        monkeypatch.setenv("SPANFORGE_SANDBOX", "1")
        _apply_env_overrides(cfg)
        assert cfg.sandbox is True

    def test_env_override_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spanforge.sdk.config import SFConfigBlock, _apply_env_overrides
        cfg = SFConfigBlock()
        monkeypatch.setenv("SPANFORGE_SANDBOX", "no")
        _apply_env_overrides(cfg)
        assert cfg.sandbox is False

    def test_sandbox_in_known_keys(self) -> None:
        from spanforge.sdk.config import _KNOWN_SPANFORGE_KEYS
        assert "sandbox" in _KNOWN_SPANFORGE_KEYS

    def test_base_client_is_sandbox(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spanforge.sdk._base import SFClientConfig, SFServiceClient
        monkeypatch.setenv("SPANFORGE_SANDBOX", "true")

        class _Dummy(SFServiceClient):
            pass

        cfg = SFClientConfig(endpoint="", api_key="", project_id="test")
        d = _Dummy(cfg, "test")
        assert d._is_sandbox() is True


# -----------------------------------------------------------------------
# DX-005: Doctor CLI
# -----------------------------------------------------------------------

class TestDoctorCLI:

    def test_doctor_returns_int(self) -> None:
        from spanforge._cli import _cmd_doctor
        code = _cmd_doctor(argparse.Namespace())
        assert isinstance(code, int)
        assert code in (0, 1)

    def test_doctor_detects_sandbox(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        from spanforge._cli import _cmd_doctor
        monkeypatch.setenv("SPANFORGE_SANDBOX", "true")
        _cmd_doctor(argparse.Namespace())
        captured = capsys.readouterr()
        assert "Sandbox" in captured.out or "sandbox" in captured.out.lower()
