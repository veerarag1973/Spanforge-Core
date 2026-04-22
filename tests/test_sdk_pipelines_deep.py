"""Deep branch coverage for spanforge.sdk.pipelines."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _pipeline_mocks():
    pii_result = SimpleNamespace(clean=True, entities=[], redacted="redacted text")
    secrets_result = SimpleNamespace(clean=True, hits=[])
    span = SimpleNamespace(span_id="span-001")
    audit_result = SimpleNamespace(record_id="audit-001")

    pii_mod = MagicMock()
    pii_mod.scan_text.return_value = pii_result
    pii_mod.anonymise.return_value = {"text": "anon"}

    secrets_mod = MagicMock()
    secrets_mod.scan.return_value = secrets_result

    observe_mod = MagicMock()
    observe_mod.emit_span.return_value = span

    audit_mod = MagicMock()
    audit_mod.append.return_value = audit_result

    alert_mod = MagicMock()
    gate_mod = MagicMock()
    cec_mod = MagicMock()
    cec_mod.build_bundle.return_value = SimpleNamespace(bundle_id="cec-001")

    return pii_mod, secrets_mod, observe_mod, audit_mod, alert_mod, gate_mod, cec_mod


def test_score_pipeline_marks_secret_block_and_wraps_scan_error() -> None:
    from spanforge.sdk._exceptions import SFPipelineError
    from spanforge.sdk.pipelines import score_pipeline

    pii_mod, secrets_mod, observe_mod, audit_mod, _alert_mod, _gate_mod, _cec_mod = _pipeline_mocks()
    secrets_mod.scan.return_value.clean = False

    with (
        patch("spanforge.sdk.sf_pii", pii_mod),
        patch("spanforge.sdk.sf_secrets", secrets_mod),
        patch("spanforge.sdk.sf_observe", observe_mod),
        patch("spanforge.sdk.sf_audit", audit_mod),
    ):
        result = score_pipeline("secret text", pii_action="log")

    assert result.success is True
    assert result.details["secrets_blocked"] is True
    assert result.details["secrets_clean"] is False

    pii_mod.scan_text.side_effect = RuntimeError("pii down")
    with (
        patch("spanforge.sdk.sf_pii", pii_mod),
        patch("spanforge.sdk.sf_secrets", secrets_mod),
        patch("spanforge.sdk.sf_observe", observe_mod),
        patch("spanforge.sdk.sf_audit", audit_mod),
    ):
        with pytest.raises(SFPipelineError, match="pii down"):
            score_pipeline("text")


def test_bias_pipeline_warns_on_alert_failure_and_wraps_audit_error(caplog: pytest.LogCaptureFixture) -> None:
    from spanforge.sdk._exceptions import SFPipelineError
    from spanforge.sdk.pipelines import bias_pipeline

    pii_mod, _secrets_mod, _observe_mod, audit_mod, alert_mod, _gate_mod, _cec_mod = _pipeline_mocks()
    alert_mod.publish.side_effect = RuntimeError("alert unavailable")
    report = {"segments": ["group-a", 42], "disparity": 0.5}

    with caplog.at_level(logging.WARNING):
        with (
            patch("spanforge.sdk.sf_pii", pii_mod),
            patch("spanforge.sdk.sf_audit", audit_mod),
            patch("spanforge.sdk.sf_alert", alert_mod),
        ):
            result = bias_pipeline(report, disparity_threshold=0.1)

    assert result.success is True
    assert result.alerts_sent == 0
    assert "alert publish failed" in caplog.text
    pii_mod.scan_text.assert_called_once_with("group-a")

    audit_mod.append.side_effect = RuntimeError("audit failed")
    with (
        patch("spanforge.sdk.sf_pii", pii_mod),
        patch("spanforge.sdk.sf_audit", audit_mod),
        patch("spanforge.sdk.sf_alert", alert_mod),
    ):
        with pytest.raises(SFPipelineError, match="audit failed"):
            bias_pipeline(report)


def test_monitor_pipeline_handles_annotation_alert_export_failures(caplog: pytest.LogCaptureFixture) -> None:
    from spanforge.sdk._exceptions import SFPipelineError
    from spanforge.sdk.pipelines import monitor_pipeline

    _pii_mod, _secrets_mod, observe_mod, _audit_mod, alert_mod, _gate_mod, _cec_mod = _pipeline_mocks()
    observe_mod.add_annotation.side_effect = RuntimeError("annotate failed")
    alert_mod.publish.side_effect = RuntimeError("alert failed")
    observe_mod.export_spans.side_effect = RuntimeError("export failed")

    with caplog.at_level(logging.WARNING):
        with (
            patch("spanforge.sdk.sf_observe", observe_mod),
            patch("spanforge.sdk.sf_alert", alert_mod),
        ):
            result = monitor_pipeline({"drift_level": "RED", "span_id": "sp1"}, project_id="p1")

    assert result.success is True
    assert result.details["drift_level"] == "RED"
    assert result.alerts_sent == 0
    assert "annotation failed" in caplog.text
    assert "alert failed" in caplog.text
    assert "export_spans failed" in caplog.text

    with (
        patch("spanforge.sdk.sf_observe", observe_mod),
        patch("spanforge.sdk.sf_alert", alert_mod),
    ):
        with pytest.raises(SFPipelineError):
            monitor_pipeline(None)  # type: ignore[arg-type]


def test_risk_pipeline_covers_gate_cec_and_error_paths(caplog: pytest.LogCaptureFixture) -> None:
    from spanforge.sdk._exceptions import SFPipelineError
    from spanforge.sdk.pipelines import risk_pipeline

    _pii_mod, _secrets_mod, _observe_mod, audit_mod, alert_mod, gate_mod, cec_mod = _pipeline_mocks()
    gate_mod.evaluate.return_value = SimpleNamespace(verdict="WARN")

    with (
        patch("spanforge.sdk.sf_audit", audit_mod),
        patch("spanforge.sdk.sf_alert", alert_mod),
        patch("spanforge.sdk.sf_gate", gate_mod),
        patch("spanforge.sdk.sf_cec", cec_mod),
    ):
        result = risk_pipeline(
            {"verdict": "RED", "risk_score": 0.9},
            project_id="p1",
            run_gate=True,
            build_cec=True,
        )

    assert result.success is True
    assert result.alerts_sent == 1
    assert result.details["gate_verdict"] == "WARN"
    assert result.details["cec_bundle_id"] == "cec-001"

    alert_mod.publish.side_effect = RuntimeError("alert broke")
    gate_mod.evaluate.side_effect = RuntimeError("gate broke")
    cec_mod.build_bundle.side_effect = RuntimeError("cec broke")

    with caplog.at_level(logging.WARNING):
        with (
            patch("spanforge.sdk.sf_audit", audit_mod),
            patch("spanforge.sdk.sf_alert", alert_mod),
            patch("spanforge.sdk.sf_gate", gate_mod),
            patch("spanforge.sdk.sf_cec", cec_mod),
        ):
            result = risk_pipeline({"verdict": "RED"}, run_gate=True, build_cec=True)

    assert result.success is True
    assert result.alerts_sent == 0
    assert "alert failed" in caplog.text
    assert "gate evaluate failed" in caplog.text
    assert "CEC build failed" in caplog.text

    audit_mod.append.side_effect = RuntimeError("audit broke")
    with (
        patch("spanforge.sdk.sf_audit", audit_mod),
        patch("spanforge.sdk.sf_alert", alert_mod),
    ):
        with pytest.raises(SFPipelineError, match="audit broke"):
            risk_pipeline({"verdict": "GREEN"})


def test_benchmark_pipeline_covers_alert_anonymise_and_error_paths(caplog: pytest.LogCaptureFixture) -> None:
    from spanforge.sdk._exceptions import SFPipelineError
    from spanforge.sdk.pipelines import benchmark_pipeline

    pii_mod, _secrets_mod, _observe_mod, audit_mod, alert_mod, _gate_mod, _cec_mod = _pipeline_mocks()

    with (
        patch("spanforge.sdk.sf_pii", pii_mod),
        patch("spanforge.sdk.sf_audit", audit_mod),
        patch("spanforge.sdk.sf_alert", alert_mod),
    ):
        result = benchmark_pipeline(
            {"f1_delta": -0.2, "summary": "report text"},
            project_id="p1",
            f1_regression_threshold=0.05,
        )

    assert result.success is True
    assert result.alerts_sent == 1
    pii_mod.anonymise.assert_called_once_with("report text")

    alert_mod.publish.side_effect = RuntimeError("alert broke")
    pii_mod.anonymise.side_effect = RuntimeError("anon broke")

    with caplog.at_level(logging.WARNING):
        with (
            patch("spanforge.sdk.sf_pii", pii_mod),
            patch("spanforge.sdk.sf_audit", audit_mod),
            patch("spanforge.sdk.sf_alert", alert_mod),
        ):
            result = benchmark_pipeline({"f1_delta": -0.2, "summary": "report text"})

    assert result.success is True
    assert result.alerts_sent == 0
    assert "alert failed" in caplog.text
    assert "anonymise failed" in caplog.text

    audit_mod.append.side_effect = RuntimeError("audit broke")
    with (
        patch("spanforge.sdk.sf_pii", pii_mod),
        patch("spanforge.sdk.sf_audit", audit_mod),
        patch("spanforge.sdk.sf_alert", alert_mod),
    ):
        with pytest.raises(SFPipelineError, match="audit broke"):
            benchmark_pipeline({"f1_delta": 0.0})
