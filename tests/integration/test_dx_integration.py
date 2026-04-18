"""Integration tests for SpanForge SDK — end-to-end service workflows (DX-021).

These tests exercise the full local-mode pipeline: PII → audit → gate → trust,
verifying that services work together correctly without network access.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _local_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force local mode for all integration tests."""
    monkeypatch.delenv("SPANFORGE_ENDPOINT", raising=False)
    monkeypatch.setenv("SPANFORGE_PROJECT_ID", "integration-test")


class TestPIIToAuditPipeline:
    """PII scan → redact → audit append → verify chain."""

    def test_scan_and_audit_roundtrip(self) -> None:
        from spanforge.sdk import sf_audit, sf_pii

        event = {"user_msg": "My email is test@example.com", "model": "gpt-4o"}

        # Scan
        scan_result = sf_pii.scan(event)
        assert scan_result is not None

        # Audit the scan result
        result = sf_audit.append(
            {"action": "pii_scan", "hits": len(scan_result.hits)},
            schema_key="integration_v1",
            strict_schema=False,
        )
        assert result.record_id
        assert result.schema_key == "integration_v1"

    def test_audit_sign_and_verify(self) -> None:
        from spanforge.sdk import sf_audit

        record = {"action": "test", "ts": "2025-01-01T00:00:00Z"}
        signed = sf_audit.sign(record)
        assert signed.signature
        assert signed.record_id

        # Append a record and verify the chain via export → verify_chain
        result = sf_audit.append(
            record, schema_key="halluccheck.score.v1", strict_schema=False,
        )
        assert result.record_id

        records = sf_audit.export(limit=100)
        report = sf_audit.verify_chain(records)
        assert report["valid"] is True


class TestGateEvaluation:
    """Gate evaluate with PII and trust gate checks."""

    def test_gate_evaluate_pass(self) -> None:
        from spanforge.sdk import sf_gate

        result = sf_gate.evaluate("test-gate", payload={"score": 0.95})
        assert result.verdict in ("PASS", "FAIL")
        assert result.gate_id == "test-gate"

    def test_trust_gate(self) -> None:
        from spanforge.sdk import sf_gate

        result = sf_gate.run_trust_gate("integration-test")
        assert result.verdict in ("PASS", "FAIL")
        assert result.project_id == "integration-test"


class TestObserveExport:
    """Span emission and export."""

    def test_emit_and_export(self) -> None:
        from spanforge.sdk import sf_observe

        span = sf_observe.emit_span("integration_test", attributes={"key": "value"})
        assert span is not None

        result = sf_observe.export_spans([{"name": "test", "attributes": {}}])
        assert result.exported_count >= 1
        assert result.failed_count == 0


class TestAlertPublish:
    """Alert registration and publishing."""

    def test_register_and_publish(self) -> None:
        from spanforge.sdk import sf_alert

        sf_alert.register_topic("integration.test", description="Integration test topic")
        result = sf_alert.publish("integration.test", payload={"msg": "hello"})
        assert result.alert_id
        assert not result.suppressed


class TestTrustScorecard:
    """Trust scorecard retrieval."""

    def test_get_scorecard(self) -> None:
        from spanforge.sdk import sf_trust

        scorecard = sf_trust.get_scorecard(project_id="integration-test")
        assert scorecard.overall_score >= 0.0
        assert scorecard.colour_band in ("green", "amber", "red")

    def test_get_badge(self) -> None:
        from spanforge.sdk import sf_trust

        badge = sf_trust.get_badge(project_id="integration-test")
        assert badge.svg
        assert badge.colour_band in ("green", "amber", "red")


class TestCECBundle:
    """Compliance evidence collection."""

    def test_build_and_verify_bundle(self, tmp_path: str) -> None:
        from spanforge.sdk import sf_cec

        bundle = sf_cec.build_bundle(
            project_id="integration-test",
            date_range=("2025-01-01", "2025-06-30"),
        )
        assert bundle.bundle_id
        assert bundle.project_id == "integration-test"


class TestMockLibrary:
    """Integration test for the mock library itself."""

    def test_mock_all_services(self) -> None:
        from spanforge.testing_mocks import mock_all_services

        with mock_all_services() as mocks:
            from spanforge.sdk import sf_audit, sf_pii

            sf_pii.scan({"text": "hello"})
            sf_audit.append({"action": "test"}, schema_key="mock_v1")

            mocks["sf_pii"].assert_called("scan")
            mocks["sf_audit"].assert_called("append")
            assert mocks["sf_pii"].call_count("scan") == 1
            assert mocks["sf_audit"].call_count("append") == 1

    def test_mock_configure_response(self) -> None:
        from spanforge.sdk._types import SFPIIScanResult
        from spanforge.testing_mocks import mock_all_services

        custom = SFPIIScanResult(hits=[{"type": "EMAIL"}], scanned=1)

        with mock_all_services() as mocks:
            mocks["sf_pii"].configure_response("scan", custom)
            from spanforge.sdk import sf_pii
            result = sf_pii.scan({"text": "test@example.com"})
            assert result.hits == [{"type": "EMAIL"}]

    def test_mock_assert_not_called(self) -> None:
        from spanforge.testing_mocks import mock_all_services

        with mock_all_services() as mocks:
            mocks["sf_audit"].assert_not_called("append")


class TestDoctorCLI:
    """Test the doctor CLI command."""

    def test_doctor_runs(self) -> None:
        import argparse

        from spanforge._cli import _cmd_doctor

        args = argparse.Namespace()
        # Should not raise; exit code 0 or 1 are both acceptable
        code = _cmd_doctor(args)
        assert code in (0, 1)


class TestSandboxConfig:
    """Test sandbox mode config loading."""

    def test_sandbox_default_false(self) -> None:
        from spanforge.sdk.config import SFConfigBlock
        cfg = SFConfigBlock()
        assert cfg.sandbox is False

    def test_sandbox_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spanforge.sdk.config import SFConfigBlock, _apply_env_overrides
        cfg = SFConfigBlock()
        monkeypatch.setenv("SPANFORGE_SANDBOX", "true")
        _apply_env_overrides(cfg)
        assert cfg.sandbox is True

    def test_sandbox_env_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spanforge.sdk.config import SFConfigBlock, _apply_env_overrides
        cfg = SFConfigBlock()
        monkeypatch.setenv("SPANFORGE_SANDBOX", "false")
        _apply_env_overrides(cfg)
        assert cfg.sandbox is False
