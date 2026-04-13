"""Gap-filler tests targeting every remaining uncovered statement.

After careful analysis of coverage output, the specific missed lines are:
  audit.py     140=raise(first_tampered empty) 142=raise(tampered_count<0) 144=raise(detected_at empty)
  cache.py     131=raise(CacheEvicted key_hash empty) 133=raise(namespace empty) 172=raise(CacheWritten key_hash) 174=raise(namespace)
  cost.py      98=raise TypeError(total_cost) 100=raise TypeError(total_token_usage) 144=raise(attribution_target empty)
  eval_.py     150=raise(scenario_name empty) 152=raise(evaluator empty) 195=EvalScenarioCompleted optional field
  fence.py     141=raise(FenceMaxRetries schema_name empty)
  prompt.py    99=raise(PromptLoaded version empty) 103=raise(template_hash invalid)
  redact.py    87=raise(RedactPii sensitivity invalid) 91=raise(RedactApplied policy_min_sensitivity) 141=raise(RedactApplied redacted_by)
  template.py  48=raise(TemplateRegistered) 109=raise(TemplateVarBound) 111=raise(TemplateVarBound) 164=raise(TemplateValFailed)
  trace.py     810=raise loop(AgentRunPayload.total_tool_calls < 0)
  exceptions.py 209-210
"""  # noqa: E501
from __future__ import annotations

import pytest

# ===========================================================================
# audit.py: AuditChainTamperedPayload raises (lines 140, 142, 144)
# ===========================================================================

@pytest.mark.unit
class TestAuditChainTamperedRaises:
    def test_empty_first_tampered_id_raises(self) -> None:
        from spanforge.namespaces.audit import AuditChainTamperedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="first_tampered_event_id"):
            AuditChainTamperedPayload(
                first_tampered_event_id="",
                tampered_count=1,
                detected_at="2024-01-01T00:00:00.000000Z",
                detected_by="system",
            )

    def test_negative_tampered_count_raises(self) -> None:
        from spanforge.namespaces.audit import AuditChainTamperedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="tampered_count"):
            AuditChainTamperedPayload(
                first_tampered_event_id="ev-50",
                tampered_count=-1,
                detected_at="2024-01-01T00:00:00.000000Z",
                detected_by="system",
            )

    def test_empty_detected_at_raises(self) -> None:
        from spanforge.namespaces.audit import AuditChainTamperedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="detected_at"):
            AuditChainTamperedPayload(
                first_tampered_event_id="ev-50",
                tampered_count=1,
                detected_at="",
                detected_by="system",
            )

    def test_empty_detected_by_raises(self) -> None:
        from spanforge.namespaces.audit import AuditChainTamperedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="detected_by"):
            AuditChainTamperedPayload(
                first_tampered_event_id="ev-50",
                tampered_count=1,
                detected_at="2024-01-01T00:00:00.000000Z",
                detected_by="",
            )


# ===========================================================================
# cache.py: raises for CacheEvictedPayload + CacheWrittenPayload (131,133,172,174)
# ===========================================================================

@pytest.mark.unit
class TestCacheEvictedWrittenRaises:
    def test_evicted_empty_key_hash_raises(self) -> None:
        from spanforge.namespaces.cache import CacheEvictedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="key_hash"):
            CacheEvictedPayload(key_hash="", namespace="ns", eviction_reason="ttl_expired")

    def test_evicted_empty_namespace_raises(self) -> None:
        from spanforge.namespaces.cache import CacheEvictedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="namespace"):
            CacheEvictedPayload(key_hash="abc", namespace="", eviction_reason="ttl_expired")

    def test_written_empty_key_hash_raises(self) -> None:
        from spanforge.namespaces.cache import CacheWrittenPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="key_hash"):
            CacheWrittenPayload(key_hash="", namespace="ns", ttl_seconds=300)

    def test_written_empty_namespace_raises(self) -> None:
        from spanforge.namespaces.cache import CacheWrittenPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="namespace"):
            CacheWrittenPayload(key_hash="abc", namespace="", ttl_seconds=300)


# ===========================================================================
# cost.py: TypeError raises for wrong types (lines 98, 100) + attribution (144)
# ===========================================================================

@pytest.mark.unit
class TestCostTypeErrors:
    def test_session_wrong_total_cost_type_raises(self) -> None:
        from spanforge.namespaces.cost import CostSessionRecordedPayload  # noqa: PLC0415
        from spanforge.namespaces.trace import TokenUsage  # noqa: PLC0415
        with pytest.raises(TypeError, match="total_cost"):
            CostSessionRecordedPayload(
                total_cost="not_a_cost_breakdown",  # wrong type
                total_token_usage=TokenUsage(input_tokens=1, output_tokens=1, total_tokens=2),
                call_count=1,
            )

    def test_session_wrong_token_usage_type_raises(self) -> None:
        from spanforge.namespaces.cost import CostSessionRecordedPayload  # noqa: PLC0415
        from spanforge.namespaces.trace import CostBreakdown  # noqa: PLC0415
        with pytest.raises(TypeError, match="total_token_usage"):
            CostSessionRecordedPayload(
                total_cost=CostBreakdown(
                    input_cost_usd=0.001, output_cost_usd=0.002, total_cost_usd=0.003
                ),
                total_token_usage="not_a_token_usage",  # wrong type  # noqa: S106
                call_count=1,
            )

    def test_attributed_wrong_cost_type_raises(self) -> None:
        from spanforge.namespaces.cost import CostAttributedPayload  # noqa: PLC0415
        with pytest.raises(TypeError, match="cost"):
            CostAttributedPayload(
                cost="not_a_cost",  # wrong type
                attribution_target="user-42",
                attribution_type="direct",
            )

    def test_attributed_empty_attribution_target_raises(self) -> None:
        from spanforge.namespaces.cost import CostAttributedPayload  # noqa: PLC0415
        from spanforge.namespaces.trace import CostBreakdown  # noqa: PLC0415
        with pytest.raises(ValueError, match="attribution_target"):
            CostAttributedPayload(
                cost=CostBreakdown(input_cost_usd=0.0, output_cost_usd=0.0, total_cost_usd=0.0),
                attribution_target="",  # empty
                attribution_type="direct",
            )


# ===========================================================================
# eval_.py: EvalScenarioStartedPayload + EvalScenarioCompletedPayload.
# Reference lines: 150, 152, and 195.
# ===========================================================================

@pytest.mark.unit
class TestEvalScenarioRaises:
    def test_started_empty_scenario_name_raises(self) -> None:
        from spanforge.namespaces.eval_ import EvalScenarioStartedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="scenario_name"):
            EvalScenarioStartedPayload(
                scenario_id="s1",
                scenario_name="",
                evaluator="auto",
            )

    def test_started_empty_evaluator_raises(self) -> None:
        from spanforge.namespaces.eval_ import EvalScenarioStartedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="evaluator"):
            EvalScenarioStartedPayload(
                scenario_id="s1",
                scenario_name="Test",
                evaluator="",
            )

    def test_completed_with_all_optionals(self) -> None:
        from spanforge.namespaces.eval_ import EvalScenarioCompletedPayload  # noqa: PLC0415
        p = EvalScenarioCompletedPayload(
            scenario_id="s1",
            status="passed",
            duration_ms=200.0,
            completed_sample_count=50,
            scores_summary={"accuracy": 0.95},
            errors=["minor warning"],
        )
        d = p.to_dict()
        assert d["completed_sample_count"] == 50
        assert d["scores_summary"] == {"accuracy": 0.95}
        assert d["errors"] == ["minor warning"]

    def test_completed_empty_scenario_id_raises(self) -> None:
        from spanforge.namespaces.eval_ import EvalScenarioCompletedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="scenario_id"):
            EvalScenarioCompletedPayload(
                scenario_id="",
                status="passed",
                duration_ms=100.0,
            )


# ===========================================================================
# fence.py: FenceMaxRetriesExceededPayload schema_name empty (line 141)
# ===========================================================================

@pytest.mark.unit
class TestFenceMaxRetriesSchemaName:
    def test_empty_schema_name_raises(self) -> None:
        from spanforge.namespaces.fence import FenceMaxRetriesExceededPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="schema_name"):
            FenceMaxRetriesExceededPayload(
                fence_id="f1",
                schema_name="",
                attempts_made=3,
                final_violation_summary="still wrong",
            )


# ===========================================================================
# prompt.py: PromptTemplateLoadedPayload raises (lines 99, 103)
# ===========================================================================

@pytest.mark.unit
class TestPromptLoadedRaises:
    def test_loaded_empty_version_raises(self) -> None:
        from spanforge.namespaces.prompt import PromptTemplateLoadedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="version"):
            PromptTemplateLoadedPayload(
                template_id="t1",
                version="",
                source="registry",
            )

    def test_loaded_invalid_template_hash_raises(self) -> None:
        from spanforge.namespaces.prompt import PromptTemplateLoadedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="template_hash"):
            PromptTemplateLoadedPayload(
                template_id="t1",
                version="1.0",
                source="registry",
                template_hash="tooshort",  # must be 64 chars
            )


# ===========================================================================
# redact.py: RedactPiiDetectedPayload + RedactAppliedPayload raises (87, 91, 141)
# ===========================================================================

@pytest.mark.unit
class TestRedactRemainingRaises:
    def test_pii_detected_empty_detected_categories_raises(self) -> None:
        from spanforge.namespaces.redact import RedactPiiDetectedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="detected_categories"):
            RedactPiiDetectedPayload(
                detected_categories=[],
                field_names=["user.email"],
                sensitivity_level="HIGH",
            )

    def test_applied_empty_policy_min_sensitivity_raises(self) -> None:
        from spanforge.namespaces.redact import RedactAppliedPayload  # noqa: PLC0415
        # Non-empty but invalid sensitivity level
        with pytest.raises(ValueError, match="policy_min_sensitivity"):
            RedactAppliedPayload(
                policy_min_sensitivity="INVALID_LEVEL",
                redacted_by="agent",
                redacted_count=1,
            )

    def test_applied_empty_redacted_by_raises(self) -> None:
        from spanforge.namespaces.redact import RedactAppliedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="redacted_by"):
            RedactAppliedPayload(
                policy_min_sensitivity="HIGH",
                redacted_by="",
                redacted_count=1,
            )


# ===========================================================================
# template.py: remaining raises (48, 109, 111, 164)
# ===========================================================================

@pytest.mark.unit
class TestTemplateRemainingRaises:
    def test_registered_invalid_hash_format_raises(self) -> None:
        from spanforge.namespaces.template import TemplateRegisteredPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="template_hash"):
            TemplateRegisteredPayload(
                template_id="t1",
                version="1.0",
                template_hash="not64chars",  # invalid
            )

    def test_variable_bound_empty_name_raises(self) -> None:
        from spanforge.namespaces.template import TemplateVariableBoundPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="variable_name"):
            TemplateVariableBoundPayload(
                template_id="t1",
                version="1.0",
                variable_name="",
                value_type="string",
            )

    def test_variable_bound_invalid_value_type_raises(self) -> None:
        from spanforge.namespaces.template import TemplateVariableBoundPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="value_type"):
            TemplateVariableBoundPayload(
                template_id="t1",
                version="1.0",
                variable_name="x",
                value_type="invalid_type",
            )

    def test_validation_failed_empty_failure_reason_raises(self) -> None:
        from spanforge.namespaces.template import TemplateValidationFailedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="failure_reason"):
            TemplateValidationFailedPayload(
                template_id="t1",
                version="1.0",
                failure_reason="",
            )


# ===========================================================================
# trace.py: AgentRunPayload total_tool_calls < 0 (line 810)
# ===========================================================================

@pytest.mark.unit
class TestAgentRunTotalToolCallsRaise:
    def test_negative_total_tool_calls_raises(self) -> None:
        import time  # noqa: PLC0415

        from spanforge.namespaces.trace import (  # noqa: PLC0415
            AgentRunPayload,
            CostBreakdown,
            TokenUsage,
        )
        t0 = int(time.time_ns())
        t1 = t0 + 1_000_000
        tok = TokenUsage(input_tokens=10, output_tokens=5, total_tokens=15)
        cost = CostBreakdown(input_cost_usd=0.0, output_cost_usd=0.0, total_cost_usd=0.0)
        with pytest.raises(ValueError, match="total_tool_calls"):
            AgentRunPayload(
                agent_run_id="run-1",
                agent_name="bot",
                trace_id="b" * 32,
                root_span_id="a" * 16,
                total_steps=0,
                total_model_calls=0,
                total_tool_calls=-1,  # negative
                total_token_usage=tok,
                total_cost=cost,
                status="ok",
                start_time_unix_nano=t0,
                end_time_unix_nano=t1,
                duration_ms=1.0,
            )


# ===========================================================================
# exceptions.py: lines 209-210 — SchemaVersionError.__init__  # noqa: ERA001
# ===========================================================================

@pytest.mark.unit
class TestExceptionLines:
    def test_schema_version_error_instantiation(self) -> None:
        """Lines 209-210: SchemaVersionError.__init__ sets self.version."""
        from spanforge.exceptions import SchemaVersionError  # noqa: PLC0415
        err = SchemaVersionError("3.0")
        assert err.version == "3.0"
        assert "3.0" in str(err)

    def test_schema_version_error_message(self) -> None:
        from spanforge.exceptions import SchemaVersionError  # noqa: PLC0415
        err = SchemaVersionError("99.0")
        assert "Unsupported" in str(err)
        assert "99.0" in str(err)
