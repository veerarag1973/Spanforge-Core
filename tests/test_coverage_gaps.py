"""Coverage gap tests — F-41/F-42/F-43/F-44.

Targeted tests for modules with insufficient coverage:
* F-41  export/append_only.py  — WORM rotation paths
* F-42  gate.py                — executor helper functions
* F-43  sdk/pipelines.py       — pipeline integration paths
* F-44  namespaces/*           — validation error paths
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# F-44: Namespace validation errors
# ---------------------------------------------------------------------------


class TestConfidencePayloadValidation:
    def test_empty_model_id_raises(self) -> None:
        from spanforge.namespaces.confidence import ConfidencePayload

        with pytest.raises(ValueError, match="model_id must be non-empty"):
            ConfidencePayload(
                model_id="",
                decision_type="decision",
                score=0.9,
                threshold_breached=False,
                sampled_at="2024-01-01T00:00:00Z",
            )

    def test_empty_decision_type_raises(self) -> None:
        from spanforge.namespaces.confidence import ConfidencePayload

        with pytest.raises(ValueError, match="decision_type must be non-empty"):
            ConfidencePayload(
                model_id="gpt-4o",
                decision_type="",
                score=0.9,
                threshold_breached=False,
                sampled_at="2024-01-01T00:00:00Z",
            )

    def test_invalid_score_raises(self) -> None:
        from spanforge.namespaces.confidence import ConfidencePayload

        with pytest.raises(ValueError, match="score must be in"):
            ConfidencePayload(
                model_id="gpt-4o",
                decision_type="decision",
                score=1.5,
                threshold_breached=False,
                sampled_at="2024-01-01T00:00:00Z",
            )

    def test_empty_sampled_at_raises(self) -> None:
        from spanforge.namespaces.confidence import ConfidencePayload

        with pytest.raises(ValueError, match="sampled_at must be non-empty"):
            ConfidencePayload(
                model_id="gpt-4o",
                decision_type="decision",
                score=0.9,
                threshold_breached=False,
                sampled_at="",
            )

    def test_valid_payload_roundtrip(self) -> None:
        from spanforge.namespaces.confidence import ConfidencePayload

        p = ConfidencePayload(
            model_id="gpt-4o",
            decision_type="summarise",
            score=0.85,
            threshold_breached=False,
            sampled_at="2024-01-01T00:00:00Z",
            baseline_mean=0.90,
            baseline_stddev=0.05,
            z_score=-1.0,
        )
        d = p.to_dict()
        assert d["model_id"] == "gpt-4o"
        assert d["baseline_mean"] == 0.90
        p2 = ConfidencePayload.from_dict(d)
        assert p2.z_score == p.z_score


class TestLatencyPayloadValidation:
    def test_empty_agent_id_raises(self) -> None:
        from spanforge.namespaces.latency import LatencyPayload

        with pytest.raises(ValueError, match="agent_id must be non-empty"):
            LatencyPayload(
                agent_id="",
                operation="chat",
                latency_ms=100.0,
                sla_target_ms=500.0,
                sla_met=True,
            )

    def test_empty_operation_raises(self) -> None:
        from spanforge.namespaces.latency import LatencyPayload

        with pytest.raises(ValueError, match="operation must be non-empty"):
            LatencyPayload(
                agent_id="agent-1",
                operation="",
                latency_ms=100.0,
                sla_target_ms=500.0,
                sla_met=True,
            )

    def test_negative_latency_raises(self) -> None:
        from spanforge.namespaces.latency import LatencyPayload

        with pytest.raises(ValueError, match="latency_ms must be"):
            LatencyPayload(
                agent_id="agent-1",
                operation="chat",
                latency_ms=-1.0,
                sla_target_ms=500.0,
                sla_met=True,
            )

    def test_zero_sla_raises(self) -> None:
        from spanforge.namespaces.latency import LatencyPayload

        with pytest.raises(ValueError, match="sla_target_ms must be"):
            LatencyPayload(
                agent_id="agent-1",
                operation="chat",
                latency_ms=100.0,
                sla_target_ms=0.0,
                sla_met=True,
            )

    def test_valid_latency_payload_roundtrip(self) -> None:
        from spanforge.namespaces.latency import LatencyPayload

        p = LatencyPayload(
            agent_id="agent-1",
            operation="chat",
            latency_ms=120.0,
            sla_target_ms=500.0,
            sla_met=True,
        )
        d = p.to_dict()
        p2 = LatencyPayload.from_dict(d)
        assert p2.latency_ms == 120.0


class TestChainPayloadValidation:
    def test_empty_chain_id_raises(self) -> None:
        from spanforge.namespaces.chain import ChainPayload

        with pytest.raises(ValueError, match="chain_id must be non-empty"):
            ChainPayload(
                chain_id="",
                step_index=0,
                step_name="step",
                cumulative_latency_ms=100.0,
                cumulative_token_cost=10.0,
                error_propagated=False,
            )

    def test_negative_step_index_raises(self) -> None:
        from spanforge.namespaces.chain import ChainPayload

        with pytest.raises(ValueError, match="step_index must be"):
            ChainPayload(
                chain_id="chain-1",
                step_index=-1,
                step_name="step",
                cumulative_latency_ms=100.0,
                cumulative_token_cost=10.0,
                error_propagated=False,
            )

    def test_empty_step_name_raises(self) -> None:
        from spanforge.namespaces.chain import ChainPayload

        with pytest.raises(ValueError, match="step_name must be non-empty"):
            ChainPayload(
                chain_id="chain-1",
                step_index=0,
                step_name="",
                cumulative_latency_ms=100.0,
                cumulative_token_cost=10.0,
                error_propagated=False,
            )

    def test_negative_cumulative_latency_raises(self) -> None:
        from spanforge.namespaces.chain import ChainPayload

        with pytest.raises(ValueError, match="cumulative_latency_ms must be"):
            ChainPayload(
                chain_id="chain-1",
                step_index=0,
                step_name="step",
                cumulative_latency_ms=-1.0,
                cumulative_token_cost=10.0,
                error_propagated=False,
            )

    def test_negative_token_cost_raises(self) -> None:
        from spanforge.namespaces.chain import ChainPayload

        with pytest.raises(ValueError, match="cumulative_token_cost must be"):
            ChainPayload(
                chain_id="chain-1",
                step_index=0,
                step_name="step",
                cumulative_latency_ms=100.0,
                cumulative_token_cost=-0.1,
                error_propagated=False,
            )

    def test_valid_chain_payload_roundtrip(self) -> None:
        from spanforge.namespaces.chain import ChainPayload

        p = ChainPayload(
            chain_id="c1",
            step_index=2,
            step_name="retrieve",
            cumulative_latency_ms=300.0,
            cumulative_token_cost=50.0,
            error_propagated=False,
        )
        d = p.to_dict()
        p2 = ChainPayload.from_dict(d)
        assert p2.step_index == 2


class TestToolCallPayloadValidation:
    def test_empty_call_id_raises(self) -> None:
        from spanforge.namespaces.tool_call import ToolCallPayload

        with pytest.raises(ValueError, match="call_id must be non-empty"):
            ToolCallPayload(
                call_id="",
                tool_name="search",
                status="success",
                latency_ms=50.0,
                consent_checked=True,
            )

    def test_empty_tool_name_raises(self) -> None:
        from spanforge.namespaces.tool_call import ToolCallPayload

        with pytest.raises(ValueError, match="tool_name must be non-empty"):
            ToolCallPayload(
                call_id="c1",
                tool_name="",
                status="success",
                latency_ms=50.0,
                consent_checked=True,
            )

    def test_invalid_status_raises(self) -> None:
        from spanforge.namespaces.tool_call import ToolCallPayload

        with pytest.raises(ValueError, match="status must be one of"):
            ToolCallPayload(
                call_id="c1",
                tool_name="search",
                status="unknown_status",  # type: ignore[arg-type]
                latency_ms=50.0,
                consent_checked=True,
            )

    def test_negative_latency_raises(self) -> None:
        from spanforge.namespaces.tool_call import ToolCallPayload

        with pytest.raises(ValueError, match="latency_ms must be"):
            ToolCallPayload(
                call_id="c1",
                tool_name="search",
                status="success",
                latency_ms=-1.0,
                consent_checked=True,
            )

    def test_valid_tool_call_payload_roundtrip(self) -> None:
        from spanforge.namespaces.tool_call import ToolCallPayload

        p = ToolCallPayload(
            call_id="call-001",
            tool_name="web_search",
            status="success",
            latency_ms=120.0,
            consent_checked=True,
        )
        d = p.to_dict()
        p2 = ToolCallPayload.from_dict(d)
        assert p2.tool_name == "web_search"


class TestConsentPayloadValidation:
    def test_empty_subject_id_raises(self) -> None:
        from spanforge.namespaces.consent import ConsentPayload

        with pytest.raises(ValueError, match="subject_id must be non-empty"):
            ConsentPayload(
                subject_id="",
                scope="data_processing",
                purpose="analytics",
                status="granted",
            )

    def test_empty_scope_raises(self) -> None:
        from spanforge.namespaces.consent import ConsentPayload

        with pytest.raises(ValueError, match="scope must be non-empty"):
            ConsentPayload(
                subject_id="user-1",
                scope="",
                purpose="analytics",
                status="granted",
            )

    def test_empty_purpose_raises(self) -> None:
        from spanforge.namespaces.consent import ConsentPayload

        with pytest.raises(ValueError, match="purpose must be non-empty"):
            ConsentPayload(
                subject_id="user-1",
                scope="data_processing",
                purpose="",
                status="granted",
            )

    def test_invalid_status_raises(self) -> None:
        from spanforge.namespaces.consent import ConsentPayload

        with pytest.raises(ValueError, match="status must be one of"):
            ConsentPayload(
                subject_id="user-1",
                scope="data_processing",
                purpose="analytics",
                status="maybe",  # type: ignore[arg-type]
            )

    def test_valid_consent_payload_roundtrip(self) -> None:
        from spanforge.namespaces.consent import ConsentPayload

        p = ConsentPayload(
            subject_id="user-42",
            scope="analytics",
            purpose="model training",
            status="granted",
        )
        d = p.to_dict()
        p2 = ConsentPayload.from_dict(d)
        assert p2.subject_id == "user-42"


class TestDriftPayloadValidation:
    def test_empty_metric_name_raises(self) -> None:
        from spanforge.namespaces.drift import DriftPayload

        with pytest.raises(ValueError, match="metric_name must be non-empty"):
            DriftPayload(
                metric_name="",
                agent_id="agent-1",
                status="detected",
                current_value=5.0,
                baseline_mean=3.0,
                baseline_stddev=0.5,
                z_score=4.0,
                threshold=3.0,
                window_seconds=3600,
            )

    def test_empty_agent_id_raises(self) -> None:
        from spanforge.namespaces.drift import DriftPayload

        with pytest.raises(ValueError, match="agent_id must be non-empty"):
            DriftPayload(
                metric_name="latency_ms",
                agent_id="",
                status="detected",
                current_value=5.0,
                baseline_mean=3.0,
                baseline_stddev=0.5,
                z_score=4.0,
                threshold=3.0,
                window_seconds=3600,
            )

    def test_invalid_status_raises(self) -> None:
        from spanforge.namespaces.drift import DriftPayload

        with pytest.raises(ValueError, match="status must be one of"):
            DriftPayload(
                metric_name="latency_ms",
                agent_id="agent-1",
                status="unknown",  # type: ignore[arg-type]
                current_value=5.0,
                baseline_mean=3.0,
                baseline_stddev=0.5,
                z_score=4.0,
                threshold=3.0,
                window_seconds=3600,
            )

    def test_zero_window_seconds_raises(self) -> None:
        from spanforge.namespaces.drift import DriftPayload

        with pytest.raises(ValueError, match="window_seconds must be"):
            DriftPayload(
                metric_name="latency_ms",
                agent_id="agent-1",
                status="detected",
                current_value=5.0,
                baseline_mean=3.0,
                baseline_stddev=0.5,
                z_score=4.0,
                threshold=3.0,
                window_seconds=0,
            )

    def test_negative_baseline_stddev_raises(self) -> None:
        from spanforge.namespaces.drift import DriftPayload

        with pytest.raises(ValueError, match="baseline_stddev must be"):
            DriftPayload(
                metric_name="latency_ms",
                agent_id="agent-1",
                status="detected",
                current_value=5.0,
                baseline_mean=3.0,
                baseline_stddev=-0.1,
                z_score=4.0,
                threshold=3.0,
                window_seconds=3600,
            )

    def test_valid_drift_payload_roundtrip(self) -> None:
        from spanforge.namespaces.drift import DriftPayload

        p = DriftPayload(
            metric_name="latency_ms",
            agent_id="agent-1",
            status="threshold_breach",
            current_value=4.5,
            baseline_mean=3.0,
            baseline_stddev=0.5,
            z_score=3.0,
            threshold=3.0,
            window_seconds=3600,
        )
        d = p.to_dict()
        p2 = DriftPayload.from_dict(d)
        assert p2.metric_name == "latency_ms"


class TestHITLPayloadValidation:
    def test_empty_decision_id_raises(self) -> None:
        from spanforge.namespaces.hitl import HITLPayload

        with pytest.raises(ValueError, match="decision_id must be non-empty"):
            HITLPayload(
                decision_id="",
                agent_id="agent-1",
                risk_tier="high",
                status="queued",
                reason="budget exceeded",
            )

    def test_empty_agent_id_raises(self) -> None:
        from spanforge.namespaces.hitl import HITLPayload

        with pytest.raises(ValueError, match="agent_id must be non-empty"):
            HITLPayload(
                decision_id="d1",
                agent_id="",
                risk_tier="high",
                status="queued",
                reason="budget exceeded",
            )

    def test_invalid_risk_tier_raises(self) -> None:
        from spanforge.namespaces.hitl import HITLPayload

        with pytest.raises(ValueError, match="risk_tier must be one of"):
            HITLPayload(
                decision_id="d1",
                agent_id="agent-1",
                risk_tier="super_high",  # type: ignore[arg-type]
                status="queued",
                reason="budget exceeded",
            )

    def test_invalid_status_raises(self) -> None:
        from spanforge.namespaces.hitl import HITLPayload

        with pytest.raises(ValueError, match="status must be one of"):
            HITLPayload(
                decision_id="d1",
                agent_id="agent-1",
                risk_tier="high",
                status="unknown_status",  # type: ignore[arg-type]
                reason="budget exceeded",
            )

    def test_empty_reason_raises(self) -> None:
        from spanforge.namespaces.hitl import HITLPayload

        with pytest.raises(ValueError, match="reason must be non-empty"):
            HITLPayload(
                decision_id="d1",
                agent_id="agent-1",
                risk_tier="high",
                status="queued",
                reason="",
            )

    def test_zero_sla_seconds_raises(self) -> None:
        from spanforge.namespaces.hitl import HITLPayload

        with pytest.raises(ValueError, match="sla_seconds must be"):
            HITLPayload(
                decision_id="d1",
                agent_id="agent-1",
                risk_tier="high",
                status="queued",
                reason="budget exceeded",
                sla_seconds=0,
            )

    def test_invalid_confidence_raises(self) -> None:
        from spanforge.namespaces.hitl import HITLPayload

        with pytest.raises(ValueError, match="confidence must be in"):
            HITLPayload(
                decision_id="d1",
                agent_id="agent-1",
                risk_tier="high",
                status="queued",
                reason="budget exceeded",
                confidence=1.5,
            )

    def test_valid_hitl_payload_roundtrip(self) -> None:
        from spanforge.namespaces.hitl import HITLPayload

        p = HITLPayload(
            decision_id="dec-001",
            agent_id="agent-1",
            risk_tier="high",
            status="queued",
            reason="Exceeds budget threshold",
            confidence=0.75,
        )
        d = p.to_dict()
        p2 = HITLPayload.from_dict(d)
        assert p2.decision_id == "dec-001"


# ---------------------------------------------------------------------------
# F-41: export/append_only.py — WORM rotation paths
# ---------------------------------------------------------------------------


class TestAppendOnlyWORMRotation:
    def test_rotation_calls_worm_upload(self, tmp_path: Path) -> None:
        from spanforge.event import Event
        from spanforge.export.append_only import AppendOnlyJSONLExporter, WORMUploadResult

        worm = MagicMock()
        worm.upload.return_value = WORMUploadResult(success=True, location="s3://bucket/key")

        # Use max_bytes=1 so the first write triggers rotation
        exp = AppendOnlyJSONLExporter(
            path=tmp_path / "audit.jsonl",
            org_secret="test-secret",
            source="test@1.0.0",
            max_bytes=1,
            worm_backend=worm,
        )

        event = Event(
            event_type="trace.span.completed",
            source="test@1.0.0",
            payload={"span_name": "s", "status": "ok"},
        )

        exp.append(event)
        exp.close()

        assert worm.upload.call_count >= 1
        assert exp.rotation_count >= 1

    def test_rotation_without_worm(self, tmp_path: Path) -> None:
        from spanforge.event import Event
        from spanforge.export.append_only import AppendOnlyJSONLExporter

        exp = AppendOnlyJSONLExporter(
            path=tmp_path / "audit.jsonl",
            org_secret="test-secret",
            source="test@1.0.0",
            max_bytes=1,
        )
        event = Event(
            event_type="trace.span.completed",
            source="test@1.0.0",
            payload={"span_name": "s", "status": "ok"},
        )
        exp.append(event)
        exp.close()
        assert exp.rotation_count >= 1

    def test_append_batch_triggers_rotation(self, tmp_path: Path) -> None:
        from spanforge.event import Event
        from spanforge.export.append_only import AppendOnlyJSONLExporter

        exp = AppendOnlyJSONLExporter(
            path=tmp_path / "audit.jsonl",
            org_secret="s",
            source="t@1.0",
            max_bytes=1,
        )
        events = [
            Event(
                event_type="trace.span.completed",
                source="t@1.0",
                payload={"span_name": f"s{i}", "status": "ok"},
            )
            for i in range(3)
        ]
        count = exp.append_batch(events)
        exp.close()
        assert count == 3
        assert exp.rotation_count >= 1

    def test_force_rotate_method(self, tmp_path: Path) -> None:
        from spanforge.event import Event
        from spanforge.export.append_only import AppendOnlyJSONLExporter

        exp = AppendOnlyJSONLExporter(
            path=tmp_path / "audit.jsonl",
            org_secret="s",
            source="t@1.0",
        )
        # Write something to open the file
        event = Event(
            event_type="trace.span.completed",
            source="t@1.0",
            payload={"span_name": "s", "status": "ok"},
        )
        exp.append(event)
        exp.rotate(max_size_mb=0)  # force immediate rotation
        exp.close()
        assert exp.rotation_count == 1

    def test_context_manager(self, tmp_path: Path) -> None:
        from spanforge.event import Event
        from spanforge.export.append_only import AppendOnlyJSONLExporter

        with AppendOnlyJSONLExporter(
            path=tmp_path / "audit.jsonl",
            org_secret="s",
            source="t@1.0",
        ) as exp:
            exp.append(
                Event(
                    event_type="trace.span.completed",
                    source="t@1.0",
                    payload={"span_name": "s", "status": "ok"},
                )
            )
        # After exit, file handle should be closed
        assert exp._fh is None

    def test_negative_max_bytes_raises(self, tmp_path: Path) -> None:
        from spanforge.export.append_only import AppendOnlyJSONLExporter

        with pytest.raises(ValueError, match="max_bytes"):
            AppendOnlyJSONLExporter(
                path=tmp_path / "audit.jsonl",
                org_secret="s",
                source="t@1.0",
                max_bytes=-1,
            )

    def test_write_exclusive_raises_if_exists(self, tmp_path: Path) -> None:
        from spanforge.export.append_only import AppendOnlyJSONLExporter

        p = tmp_path / "existing.jsonl"
        p.write_text("{}")
        exp = AppendOnlyJSONLExporter(
            path=tmp_path / "audit.jsonl",
            org_secret="s",
            source="t@1.0",
        )
        from spanforge.exceptions import AuditStorageError

        with pytest.raises(AuditStorageError):
            exp.write_exclusive(p)

    def test_repr(self, tmp_path: Path) -> None:
        from spanforge.export.append_only import AppendOnlyJSONLExporter

        exp = AppendOnlyJSONLExporter(
            path=tmp_path / "audit.jsonl",
            org_secret="s",
            source="t@1.0",
        )
        r = repr(exp)
        assert "AppendOnlyJSONLExporter" in r


# ---------------------------------------------------------------------------
# F-42: gate.py — executor helper functions
# ---------------------------------------------------------------------------


class TestGateExecutorHelpers:
    def test_substitute_template_basic(self) -> None:
        from spanforge.gate import _substitute_template

        result = _substitute_template("echo {{ project }}", {"project": "my-project"})
        assert result == "echo my-project"

    def test_validate_template_value_unsafe_raises(self) -> None:
        from spanforge.gate import _validate_template_value

        with pytest.raises(ValueError, match="unsafe characters"):
            _validate_template_value("key", "val;rm -rf /")

    def test_evaluate_pass_condition_numeric(self) -> None:
        from spanforge.gate import _evaluate_pass_condition

        assert _evaluate_pass_condition("< 70", 50) is True
        assert _evaluate_pass_condition("< 70", 80) is False
        assert _evaluate_pass_condition(">= 0.5", 0.6) is True
        assert _evaluate_pass_condition("== 0", 0) is True
        assert _evaluate_pass_condition("!= 1", 0) is True

    def test_evaluate_pass_condition_boolean(self) -> None:
        from spanforge.gate import _evaluate_pass_condition

        assert _evaluate_pass_condition("false", False) is True
        assert _evaluate_pass_condition("true", True) is True
        assert _evaluate_pass_condition("false", True) is False

    def test_evaluate_pass_condition_unrecognised(self) -> None:
        from spanforge.gate import _evaluate_pass_condition

        assert _evaluate_pass_condition("??? 99", 50) is False

    def test_exec_schema_validation_no_command(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_schema_validation

        cfg = GateConfig(id="g1", name="Schema", type="schema_validation")
        verdict, metrics, detail = _exec_schema_validation(cfg, {}, 30)
        assert verdict == GateVerdict.PASS
        assert metrics["schemas_checked"] == 1

    def test_exec_schema_validation_timeout(self) -> None:
        import subprocess

        from spanforge.gate import GateConfig, GateVerdict, _exec_schema_validation

        cfg = GateConfig(
            id="g1",
            name="Schema",
            type="schema_validation",
            command="sleep 100",
        )
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 1)):
            verdict, _m, detail = _exec_schema_validation(cfg, {}, 1)
        assert verdict == GateVerdict.FAIL
        assert "timed out" in detail

    def test_exec_dependency_security_pip_audit_not_installed(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_dependency_security

        cfg = GateConfig(
            id="g2",
            name="DepSec",
            type="dependency_security",
            command="nonexistent-binary-xyz",
        )
        with patch("subprocess.run", side_effect=FileNotFoundError):
            verdict, metrics, detail = _exec_dependency_security(cfg, {}, 30)
        assert verdict == GateVerdict.WARN
        assert "not found" in detail

    def test_exec_performance_regression_no_command(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_performance_regression

        cfg = GateConfig(id="g4", name="Perf", type="performance_regression")
        verdict, metrics, detail = _exec_performance_regression(cfg, {}, 30)
        assert verdict == GateVerdict.PASS

    def test_exec_performance_regression_timeout(self) -> None:
        import subprocess

        from spanforge.gate import GateConfig, GateVerdict, _exec_performance_regression

        cfg = GateConfig(
            id="g4",
            name="Perf",
            type="performance_regression",
            command="sleep 100",
        )
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 1)):
            verdict, _m, detail = _exec_performance_regression(cfg, {}, 1)
        assert verdict == GateVerdict.FAIL

    def test_exec_halluccheck_prri_no_artifact(self, tmp_path: Path) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_halluccheck_prri

        cfg = GateConfig(id="g5", name="PRRI", type="halluccheck_prri")
        ctx = {"artifact_dir": str(tmp_path)}
        verdict, _m, detail = _exec_halluccheck_prri(cfg, ctx, 30)
        assert verdict == GateVerdict.WARN
        assert "not found" in detail

    def test_exec_halluccheck_prri_pass(self, tmp_path: Path) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_halluccheck_prri

        prri_data = {"prri_score": 30, "verdict": "GREEN", "allow": True}
        (tmp_path / "prri_result.json").write_text(json.dumps(prri_data))

        cfg = GateConfig(
            id="g5",
            name="PRRI",
            type="halluccheck_prri",
            artifact="prri_result.json",
        )
        ctx = {"artifact_dir": str(tmp_path)}
        verdict, metrics, _d = _exec_halluccheck_prri(cfg, ctx, 30)
        assert verdict == GateVerdict.PASS
        assert metrics["prri_score"] == 30

    def test_exec_halluccheck_prri_fail(self, tmp_path: Path) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_halluccheck_prri

        prri_data = {"prri_score": 85, "verdict": "RED", "allow": False}
        (tmp_path / "prri_result.json").write_text(json.dumps(prri_data))

        cfg = GateConfig(
            id="g5",
            name="PRRI",
            type="halluccheck_prri",
            artifact="prri_result.json",
        )
        ctx = {"artifact_dir": str(tmp_path)}
        verdict, metrics, _d = _exec_halluccheck_prri(cfg, ctx, 30)
        assert verdict == GateVerdict.FAIL

    def test_exec_secrets_scan_no_git_changes(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_secrets_scan

        cfg = GateConfig(id="g3", name="Secrets", type="secrets_scan")
        mock_proc = MagicMock()
        mock_proc.stdout = ""
        mock_proc.returncode = 0

        with patch("subprocess.run", return_value=mock_proc):
            verdict, metrics, _d = _exec_secrets_scan(cfg, {}, 30)
        assert verdict == GateVerdict.PASS
        assert metrics["files_scanned"] == 0


# ---------------------------------------------------------------------------
# F-42: subprocess.run gate executor mock tests
# ---------------------------------------------------------------------------


class TestGateExecutorSubprocessMocks:
    """Dedicated mock tests for all 6 subprocess.run-based gate executors.

    Each executor is tested for: PASS via subprocess, FAIL via subprocess,
    timeout, and generic exception paths.
    """

    # --- 1. _exec_schema_validation ----------------------------------------

    def test_schema_validation_command_pass(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_schema_validation

        cfg = GateConfig(
            id="g1", name="Schema", type="schema_validation", command="check-schema"
        )
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch("spanforge.gate.subprocess.run", return_value=mock_proc):
            verdict, metrics, detail = _exec_schema_validation(cfg, {}, 30)
        assert verdict == GateVerdict.PASS
        assert metrics["exit_code"] == 0
        assert metrics["violations"] == 0

    def test_schema_validation_command_fail(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_schema_validation

        cfg = GateConfig(
            id="g1", name="Schema", type="schema_validation", command="check-schema"
        )
        mock_proc = MagicMock(returncode=1, stdout="", stderr="invalid field X")
        with patch("spanforge.gate.subprocess.run", return_value=mock_proc):
            verdict, metrics, detail = _exec_schema_validation(cfg, {}, 30)
        assert verdict == GateVerdict.FAIL
        assert metrics["violations"] == 1
        assert "invalid field X" in detail

    def test_schema_validation_command_fail_empty_stderr(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_schema_validation

        cfg = GateConfig(
            id="g1", name="Schema", type="schema_validation", command="check-schema"
        )
        mock_proc = MagicMock(returncode=1, stdout="", stderr="")
        with patch("spanforge.gate.subprocess.run", return_value=mock_proc):
            verdict, metrics, detail = _exec_schema_validation(cfg, {}, 30)
        assert verdict == GateVerdict.FAIL
        assert "Schema validation failed" in detail

    def test_schema_validation_generic_exception(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_schema_validation

        cfg = GateConfig(
            id="g1", name="Schema", type="schema_validation", command="check-schema"
        )
        with patch("spanforge.gate.subprocess.run", side_effect=OSError("no such file")):
            verdict, metrics, detail = _exec_schema_validation(cfg, {}, 30)
        assert verdict == GateVerdict.ERROR
        assert "error" in detail.lower()

    # --- 2. _exec_dependency_security --------------------------------------

    def test_dependency_security_pass_no_vulns(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_dependency_security

        cfg = GateConfig(id="g2", name="DepSec", type="dependency_security")
        mock_proc = MagicMock(returncode=0, stdout="{}", stderr="")
        with patch("spanforge.gate.subprocess.run", return_value=mock_proc):
            verdict, metrics, detail = _exec_dependency_security(cfg, {}, 30)
        assert verdict == GateVerdict.PASS
        assert metrics["total_vulnerabilities"] == 0

    def test_dependency_security_fail_critical_cves(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_dependency_security

        vulns = {
            "vulnerabilities": [
                {"severity": "critical", "id": "CVE-2024-0001"},
                {"severity": "high", "id": "CVE-2024-0002"},
                {"severity": "low", "id": "CVE-2024-0003"},
            ]
        }
        cfg = GateConfig(id="g2", name="DepSec", type="dependency_security")
        mock_proc = MagicMock(returncode=1, stdout=json.dumps(vulns), stderr="")
        with patch("spanforge.gate.subprocess.run", return_value=mock_proc):
            verdict, metrics, detail = _exec_dependency_security(cfg, {}, 30)
        assert verdict == GateVerdict.FAIL
        assert metrics["critical_cves"] == 1
        assert metrics["high_cves"] == 1
        assert metrics["total_vulnerabilities"] == 3

    def test_dependency_security_pass_with_json_parse_error(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_dependency_security

        cfg = GateConfig(id="g2", name="DepSec", type="dependency_security")
        mock_proc = MagicMock(returncode=0, stdout="not-json", stderr="")
        with patch("spanforge.gate.subprocess.run", return_value=mock_proc):
            verdict, metrics, detail = _exec_dependency_security(cfg, {}, 30)
        assert verdict == GateVerdict.PASS
        # JSON couldn't be parsed, but exit code is 0, so PASS

    def test_dependency_security_timeout(self) -> None:
        import subprocess as _subprocess

        from spanforge.gate import GateConfig, GateVerdict, _exec_dependency_security

        cfg = GateConfig(id="g2", name="DepSec", type="dependency_security")
        with patch(
            "spanforge.gate.subprocess.run",
            side_effect=_subprocess.TimeoutExpired("cmd", 1),
        ):
            verdict, metrics, detail = _exec_dependency_security(cfg, {}, 1)
        assert verdict == GateVerdict.FAIL
        assert "timed out" in detail

    def test_dependency_security_generic_exception(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_dependency_security

        cfg = GateConfig(id="g2", name="DepSec", type="dependency_security")
        with patch(
            "spanforge.gate.subprocess.run", side_effect=RuntimeError("boom")
        ):
            verdict, metrics, detail = _exec_dependency_security(cfg, {}, 30)
        assert verdict == GateVerdict.ERROR
        assert "error" in detail.lower()

    def test_dependency_security_custom_command(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_dependency_security

        cfg = GateConfig(
            id="g2", name="DepSec", type="dependency_security",
            command="safety check --json",
        )
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch("spanforge.gate.subprocess.run", return_value=mock_proc) as mock_run:
            verdict, metrics, detail = _exec_dependency_security(cfg, {}, 30)
        assert verdict == GateVerdict.PASS
        # Verify custom command was tokenised and passed
        args, kwargs = mock_run.call_args
        assert args[0] == ["safety", "check", "--json"]

    # --- 3. _exec_secrets_scan ---------------------------------------------

    def test_secrets_scan_detects_secrets_in_diff(self, tmp_path: Path) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_secrets_scan

        # Create a staged file with a "secret"
        secret_file = tmp_path / "config.py"
        secret_file.write_text('API_KEY = "sk-live-abc123xyz"', encoding="utf-8")

        cfg = GateConfig(id="g3", name="Secrets", type="secrets_scan")

        # First git diff --cached returns the file, second is not reached
        mock_proc = MagicMock(returncode=0, stdout=str(secret_file) + "\n")

        scan_result = MagicMock()
        scan_result.detected = True
        scan_result.hits = [MagicMock()]

        with (
            patch("spanforge.gate.subprocess.run", return_value=mock_proc),
            patch("spanforge.sdk.sf_secrets.scan", return_value=scan_result),
        ):
            verdict, metrics, detail = _exec_secrets_scan(cfg, {}, 30)
        assert verdict == GateVerdict.FAIL
        assert metrics["secrets_detected"] == 1

    def test_secrets_scan_falls_back_to_unstaged_diff(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_secrets_scan

        cfg = GateConfig(id="g3", name="Secrets", type="secrets_scan")

        # First call (--cached) returns empty, second call returns empty too
        mock_empty = MagicMock(returncode=0, stdout="")
        with patch("spanforge.gate.subprocess.run", return_value=mock_empty) as mock_run:
            verdict, metrics, _d = _exec_secrets_scan(cfg, {}, 30)
        assert verdict == GateVerdict.PASS
        # Two subprocess.run calls: --cached then --name-only
        assert mock_run.call_count == 2

    def test_secrets_scan_import_error(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_secrets_scan

        cfg = GateConfig(id="g3", name="Secrets", type="secrets_scan")

        with patch.dict("sys.modules", {"spanforge.sdk": None}):
            # sf_secrets import will fail
            verdict, metrics, detail = _exec_secrets_scan(cfg, {}, 30)
        assert verdict == GateVerdict.ERROR

    def test_secrets_scan_generic_exception(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_secrets_scan

        cfg = GateConfig(id="g3", name="Secrets", type="secrets_scan")

        with patch(
            "spanforge.gate.subprocess.run", side_effect=RuntimeError("git gone")
        ):
            verdict, metrics, detail = _exec_secrets_scan(cfg, {}, 30)
        assert verdict == GateVerdict.ERROR
        assert "error" in detail.lower()

    # --- 4. _exec_performance_regression -----------------------------------

    def test_performance_regression_command_pass(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_performance_regression

        cfg = GateConfig(
            id="g4", name="Perf", type="performance_regression", command="perf-check"
        )
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch("spanforge.gate.subprocess.run", return_value=mock_proc):
            verdict, metrics, detail = _exec_performance_regression(cfg, {}, 30)
        assert verdict == GateVerdict.PASS
        assert metrics["exit_code"] == 0
        assert metrics["services_checked"] == 1

    def test_performance_regression_command_fail(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_performance_regression

        cfg = GateConfig(
            id="g4", name="Perf", type="performance_regression", command="perf-check"
        )
        mock_proc = MagicMock(returncode=1, stdout="", stderr="regression found")
        with patch("spanforge.gate.subprocess.run", return_value=mock_proc):
            verdict, metrics, detail = _exec_performance_regression(cfg, {}, 30)
        assert verdict == GateVerdict.FAIL
        assert "regression" in detail.lower()

    def test_performance_regression_generic_exception(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_performance_regression

        cfg = GateConfig(
            id="g4", name="Perf", type="performance_regression", command="perf-check"
        )
        with patch(
            "spanforge.gate.subprocess.run", side_effect=OSError("not found")
        ):
            verdict, metrics, detail = _exec_performance_regression(cfg, {}, 30)
        assert verdict == GateVerdict.ERROR
        assert "error" in detail.lower()

    # --- 5. _exec_halluccheck_prri -----------------------------------------

    def test_halluccheck_prri_command_then_artifact(self, tmp_path: Path) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_halluccheck_prri

        prri_data = {
            "prri_score": 45,
            "verdict": "AMBER",
            "allow": True,
            "dimension_breakdown": {"coherence": 0.9},
        }
        (tmp_path / "prri_result.json").write_text(json.dumps(prri_data))

        cfg = GateConfig(
            id="g5", name="PRRI", type="halluccheck_prri",
            command="run-prri-check",
            artifact="prri_result.json",
        )
        mock_proc = MagicMock(returncode=0)
        ctx = {"artifact_dir": tmp_path.as_posix()}
        with patch("spanforge.gate.subprocess.run", return_value=mock_proc):
            verdict, metrics, detail = _exec_halluccheck_prri(cfg, ctx, 30)
        assert verdict == GateVerdict.PASS
        assert metrics["prri_score"] == 45
        assert metrics["exit_code"] == 0

    def test_halluccheck_prri_timeout(self, tmp_path: Path) -> None:
        import subprocess as _subprocess

        from spanforge.gate import GateConfig, GateVerdict, _exec_halluccheck_prri

        cfg = GateConfig(
            id="g5", name="PRRI", type="halluccheck_prri",
            command="slow-prri-check",
        )
        ctx = {"artifact_dir": tmp_path.as_posix()}
        with patch(
            "spanforge.gate.subprocess.run",
            side_effect=_subprocess.TimeoutExpired("cmd", 1),
        ):
            verdict, metrics, detail = _exec_halluccheck_prri(cfg, ctx, 1)
        assert verdict == GateVerdict.FAIL
        assert "timed out" in detail.lower()

    def test_halluccheck_prri_malformed_json(self, tmp_path: Path) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_halluccheck_prri

        (tmp_path / "prri_result.json").write_text("NOT-VALID-JSON")

        cfg = GateConfig(
            id="g5", name="PRRI", type="halluccheck_prri",
            artifact="prri_result.json",
        )
        verdict, metrics, detail = _exec_halluccheck_prri(
            cfg, {"artifact_dir": str(tmp_path)}, 30
        )
        assert verdict == GateVerdict.ERROR
        assert "parse" in detail.lower()

    def test_halluccheck_prri_generic_exception(self, tmp_path: Path) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_halluccheck_prri

        cfg = GateConfig(
            id="g5", name="PRRI", type="halluccheck_prri",
            command="prri-check",
        )
        with patch(
            "spanforge.gate.subprocess.run", side_effect=RuntimeError("kaboom")
        ):
            verdict, metrics, detail = _exec_halluccheck_prri(
                cfg, {"artifact_dir": str(tmp_path)}, 30
            )
        assert verdict == GateVerdict.ERROR
        assert "error" in detail.lower()

    # --- 6. _exec_halluccheck_trust ----------------------------------------

    def test_halluccheck_trust_sdk_pass(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_halluccheck_trust

        cfg = GateConfig(id="g6", name="Trust", type="halluccheck_trust")

        mock_result = MagicMock()
        mock_result.pass_ = True
        mock_result.hri_critical_rate = 0.01
        mock_result.pii_detected = False
        mock_result.pii_detections_24h = 0
        mock_result.secrets_detected = False
        mock_result.secrets_detections_24h = 0
        mock_result.failures = []

        mock_client = MagicMock()
        mock_client.run_trust_gate.return_value = mock_result

        with (
            patch("spanforge.sdk.gate.SFGateClient", return_value=mock_client),
            patch("spanforge.sdk._base.SFClientConfig.from_env"),
        ):
            verdict, metrics, detail = _exec_halluccheck_trust(cfg, {}, 30)
        assert verdict == GateVerdict.PASS
        assert metrics["hri_critical_rate"] == 0.01
        assert metrics["pii_detected"] is False

    def test_halluccheck_trust_sdk_fail(self) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_halluccheck_trust

        cfg = GateConfig(id="g6", name="Trust", type="halluccheck_trust")

        mock_result = MagicMock()
        mock_result.pass_ = False
        mock_result.hri_critical_rate = 0.12
        mock_result.pii_detected = True
        mock_result.pii_detections_24h = 3
        mock_result.secrets_detected = False
        mock_result.secrets_detections_24h = 0
        mock_result.failures = ["HRI critical rate too high", "PII detected"]

        mock_client_cls = MagicMock()
        mock_client_cls.return_value.run_trust_gate.return_value = mock_result

        with (
            patch("spanforge.sdk.gate.SFGateClient", mock_client_cls),
            patch("spanforge.sdk._base.SFClientConfig.from_env"),
        ):
            verdict, metrics, detail = _exec_halluccheck_trust(cfg, {}, 30)
        assert verdict == GateVerdict.FAIL
        assert "FAILED" in detail
        assert metrics["hri_critical_rate"] == 0.12

    def test_halluccheck_trust_artifact_pass(self, tmp_path: Path) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_halluccheck_trust

        trust_data = {
            "verdict": "PASS",
            "hri_critical_rate": 0.02,
            "pii_detected": False,
            "secrets_detected": False,
            "failures": [],
        }
        (tmp_path / "trust_gate_result.json").write_text(json.dumps(trust_data))

        cfg = GateConfig(
            id="g6", name="Trust", type="halluccheck_trust",
            artifact="trust_gate_result.json",
        )
        # SDK import fails, so it falls through to artifact
        with patch(
            "spanforge.sdk.gate.SFGateClient",
            side_effect=ImportError("no sdk"),
        ):
            verdict, metrics, detail = _exec_halluccheck_trust(
                cfg, {"artifact_dir": str(tmp_path)}, 30
            )
        assert verdict == GateVerdict.PASS
        assert metrics["hri_critical_rate"] == 0.02

    def test_halluccheck_trust_artifact_fail(self, tmp_path: Path) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_halluccheck_trust

        trust_data = {
            "verdict": "FAIL",
            "hri_critical_rate": 0.15,
            "pii_detected": True,
            "secrets_detected": False,
            "failures": ["HRI too high"],
        }
        (tmp_path / "trust_gate_result.json").write_text(json.dumps(trust_data))

        cfg = GateConfig(
            id="g6", name="Trust", type="halluccheck_trust",
            artifact="trust_gate_result.json",
        )
        with patch(
            "spanforge.sdk.gate.SFGateClient",
            side_effect=ImportError("no sdk"),
        ):
            verdict, metrics, detail = _exec_halluccheck_trust(
                cfg, {"artifact_dir": str(tmp_path)}, 30
            )
        assert verdict == GateVerdict.FAIL
        assert metrics["pii_detected"] is True

    def test_halluccheck_trust_artifact_malformed(self, tmp_path: Path) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_halluccheck_trust

        (tmp_path / "trust_gate_result.json").write_text("{bad-json!!!")

        cfg = GateConfig(
            id="g6", name="Trust", type="halluccheck_trust",
            artifact="trust_gate_result.json",
        )
        with patch(
            "spanforge.sdk.gate.SFGateClient",
            side_effect=ImportError("no sdk"),
        ):
            verdict, metrics, detail = _exec_halluccheck_trust(
                cfg, {"artifact_dir": str(tmp_path)}, 30
            )
        assert verdict == GateVerdict.ERROR
        assert "parse" in detail.lower()

    def test_halluccheck_trust_no_sdk_no_artifact(self, tmp_path: Path) -> None:
        from spanforge.gate import GateConfig, GateVerdict, _exec_halluccheck_trust

        cfg = GateConfig(id="g6", name="Trust", type="halluccheck_trust")
        with patch(
            "spanforge.sdk.gate.SFGateClient",
            side_effect=ImportError("no sdk"),
        ):
            verdict, metrics, detail = _exec_halluccheck_trust(
                cfg, {"artifact_dir": str(tmp_path)}, 30
            )
        assert verdict == GateVerdict.WARN
        assert "not found" in detail


# ---------------------------------------------------------------------------
# F-43: sdk/pipelines.py — pipeline paths
# ---------------------------------------------------------------------------


def _make_pipeline_mocks():
    """Return mocked sf_pii, sf_secrets, sf_observe, sf_audit, sf_alert."""
    pii_result = MagicMock()
    pii_result.clean = True
    pii_result.entities = []
    pii_result.redacted = "redacted text"

    secrets_result = MagicMock()
    secrets_result.clean = True
    secrets_result.hits = []
    secrets_result.detected = False

    span = MagicMock()
    span.span_id = "span-001"

    audit_result = MagicMock()
    audit_result.record_id = "audit-001"

    pii_mod = MagicMock()
    pii_mod.scan_text.return_value = pii_result
    pii_mod.anonymise.return_value = {}

    secrets_mod = MagicMock()
    secrets_mod.scan.return_value = secrets_result

    observe_mod = MagicMock()
    observe_mod.emit_span.return_value = span

    audit_mod = MagicMock()
    audit_mod.append.return_value = audit_result

    alert_mod = MagicMock()

    return pii_mod, secrets_mod, observe_mod, audit_mod, alert_mod


class TestScorePipeline:
    def test_score_pipeline_success(self) -> None:
        from spanforge.sdk.pipelines import score_pipeline

        pii_mod, secrets_mod, observe_mod, audit_mod, _alert_mod = _make_pipeline_mocks()

        with (
            patch("spanforge.sdk.sf_pii", pii_mod),
            patch("spanforge.sdk.sf_secrets", secrets_mod),
            patch("spanforge.sdk.sf_observe", observe_mod),
            patch("spanforge.sdk.sf_audit", audit_mod),
        ):
            result = score_pipeline("clean text", model="gpt-4o", project_id="proj-1")

        assert result.success is True
        assert result.pipeline == "score"
        assert result.audit_id == "audit-001"

    def test_score_pipeline_pii_redaction(self) -> None:
        from spanforge.sdk.pipelines import score_pipeline

        pii_mod, secrets_mod, observe_mod, audit_mod, _alert_mod = _make_pipeline_mocks()
        pii_mod.scan_text.return_value.clean = False
        pii_mod.scan_text.return_value.entities = [MagicMock()]

        with (
            patch("spanforge.sdk.sf_pii", pii_mod),
            patch("spanforge.sdk.sf_secrets", secrets_mod),
            patch("spanforge.sdk.sf_observe", observe_mod),
            patch("spanforge.sdk.sf_audit", audit_mod),
        ):
            result = score_pipeline("text with PII", pii_action="redact")

        assert result.success is True
        assert result.details.get("pii_entities_found", 0) >= 1

    def test_score_pipeline_observe_failure_non_fatal(self) -> None:
        from spanforge.sdk.pipelines import score_pipeline

        pii_mod, secrets_mod, observe_mod, audit_mod, _alert_mod = _make_pipeline_mocks()
        observe_mod.emit_span.side_effect = RuntimeError("observe down")

        with (
            patch("spanforge.sdk.sf_pii", pii_mod),
            patch("spanforge.sdk.sf_secrets", secrets_mod),
            patch("spanforge.sdk.sf_observe", observe_mod),
            patch("spanforge.sdk.sf_audit", audit_mod),
        ):
            result = score_pipeline("text")

        assert result.success is True

    def test_score_pipeline_audit_failure_raises(self) -> None:
        from spanforge.sdk._exceptions import SFPipelineError
        from spanforge.sdk.pipelines import score_pipeline

        pii_mod, secrets_mod, observe_mod, audit_mod, _alert_mod = _make_pipeline_mocks()
        audit_mod.append.side_effect = RuntimeError("audit down")

        with (
            patch("spanforge.sdk.sf_pii", pii_mod),
            patch("spanforge.sdk.sf_secrets", secrets_mod),
            patch("spanforge.sdk.sf_observe", observe_mod),
            patch("spanforge.sdk.sf_audit", audit_mod),
        ):
            with pytest.raises(SFPipelineError):
                score_pipeline("text")


class TestBiasPipeline:
    def test_bias_pipeline_success(self) -> None:
        from spanforge.sdk.pipelines import bias_pipeline

        pii_mod, _s, observe_mod, audit_mod, alert_mod = _make_pipeline_mocks()
        bias_report = {
            "segment_labels": ["group_a", "group_b"],
            "disparity_score": 0.05,
        }

        with (
            patch("spanforge.sdk.sf_pii", pii_mod),
            patch("spanforge.sdk.sf_observe", observe_mod),
            patch("spanforge.sdk.sf_audit", audit_mod),
            patch("spanforge.sdk.sf_alert", alert_mod),
        ):
            result = bias_pipeline(bias_report)

        assert result.success is True
        assert result.pipeline == "bias"

    def test_bias_pipeline_disparity_alert(self) -> None:
        from spanforge.sdk.pipelines import bias_pipeline

        pii_mod, _s, observe_mod, audit_mod, alert_mod = _make_pipeline_mocks()
        bias_report = {
            "segment_labels": ["group_a"],
            "disparity_score": 0.5,  # exceeds default threshold 0.1
        }

        with (
            patch("spanforge.sdk.sf_pii", pii_mod),
            patch("spanforge.sdk.sf_observe", observe_mod),
            patch("spanforge.sdk.sf_audit", audit_mod),
            patch("spanforge.sdk.sf_alert", alert_mod),
        ):
            result = bias_pipeline(bias_report, disparity_threshold=0.1)

        assert result.success is True


class TestMonitorPipeline:
    def test_monitor_pipeline_success(self) -> None:
        from spanforge.sdk.pipelines import monitor_pipeline

        _pii, _s, observe_mod, audit_mod, _alert = _make_pipeline_mocks()

        metrics_snapshot = {"latency_p95_ms": 120.0, "error_rate": 0.01}

        with (
            patch("spanforge.sdk.sf_observe", observe_mod),
            patch("spanforge.sdk.sf_audit", audit_mod),
        ):
            result = monitor_pipeline(metrics_snapshot)

        assert result.success is True
        assert result.pipeline == "monitor"


class TestRiskPipeline:
    def test_risk_pipeline_success(self) -> None:
        from spanforge.sdk.pipelines import risk_pipeline

        _pii, _s, observe_mod, audit_mod, alert_mod = _make_pipeline_mocks()

        risk_data = {"risk_score": 0.2, "category": "compliance"}

        with (
            patch("spanforge.sdk.sf_observe", observe_mod),
            patch("spanforge.sdk.sf_audit", audit_mod),
            patch("spanforge.sdk.sf_alert", alert_mod),
        ):
            result = risk_pipeline(risk_data)

        assert result.success is True
        assert result.pipeline == "risk"


class TestBenchmarkPipeline:
    def test_benchmark_pipeline_success(self) -> None:
        from spanforge.sdk.pipelines import benchmark_pipeline

        _pii, _s, observe_mod, audit_mod, _alert = _make_pipeline_mocks()

        benchmark_result = {"task": "qa", "f1_score": 0.95, "f1_delta": 0.01}

        with (
            patch("spanforge.sdk.sf_observe", observe_mod),
            patch("spanforge.sdk.sf_audit", audit_mod),
        ):
            result = benchmark_pipeline(benchmark_result)

        assert result.success is True
        assert result.pipeline == "benchmark"
