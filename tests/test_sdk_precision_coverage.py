"""Precision tests for the last ~12 remaining missed statements.

Each test is named uniquely and targets a SPECIFIC missed line.
"""
from __future__ import annotations

import pytest

# ===========================================================================
# redact.py 87 — raise in RedactPhiDetectedPayload.detected_categories empty
# ===========================================================================

@pytest.mark.unit
class TestRedactPhiPrecision:
    def test_phi_empty_detected_categories_raises(self) -> None:
        """Line 87: raise in RedactPhiDetectedPayload for empty detected_categories."""
        from spanforge.namespaces.redact import RedactPhiDetectedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="detected_categories"):
            RedactPhiDetectedPayload(
                detected_categories=[],  # empty → raise
                field_names=["record.ssn"],
                sensitivity_level="PHI",
            )

    def test_phi_invalid_sensitivity_level_raises(self) -> None:
        """Line 91: raise in RedactPhiDetectedPayload when sensitivity != 'PHI'."""
        from spanforge.namespaces.redact import RedactPhiDetectedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="sensitivity_level"):
            RedactPhiDetectedPayload(
                detected_categories=["ssn"],
                field_names=["record.ssn"],
                sensitivity_level="HIGH",  # must be exactly "PHI"
            )

    def test_phi_basic_valid_creation(self) -> None:
        """Baseline: valid RedactPhiDetectedPayload creation doesn't raise."""
        from spanforge.namespaces.redact import RedactPhiDetectedPayload  # noqa: PLC0415
        p = RedactPhiDetectedPayload(
            detected_categories=["ssn", "dob"],
            field_names=["patient.ssn"],
            sensitivity_level="PHI",
        )
        d = p.to_dict()
        assert d["sensitivity_level"] == "PHI"


# ===========================================================================
# redact.py 141 — raise for redacted_count < 0 in RedactAppliedPayload
# ===========================================================================

@pytest.mark.unit
class TestRedactAppliedCountPrecision:
    def test_applied_negative_redacted_count_raises(self) -> None:
        """Line 141: raise in RedactAppliedPayload for redacted_count < 0."""
        from spanforge.namespaces.redact import RedactAppliedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="redacted_count"):
            RedactAppliedPayload(
                policy_min_sensitivity="HIGH",
                redacted_by="auto-agent",
                redacted_count=-1,  # must be >= 0
            )


# ===========================================================================
# template.py 48 — raise for empty version in TemplateRegisteredPayload
# ===========================================================================

@pytest.mark.unit
class TestTemplateRegisteredVersionPrecision:
    def test_registered_empty_version_raises(self) -> None:
        """Line 48: raise in TemplateRegisteredPayload for empty version."""
        from spanforge.namespaces.template import TemplateRegisteredPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="version"):
            TemplateRegisteredPayload(
                template_id="t1",
                version="",           # empty → raise
                template_hash="a" * 64,
            )


# ===========================================================================
# template.py 109 — raise for empty version in TemplateVariableBoundPayload
# ===========================================================================

@pytest.mark.unit
class TestTemplateVarBoundVersionPrecision:
    def test_variable_bound_empty_version_raises(self) -> None:
        """Line 109: raise in TemplateVariableBoundPayload for empty version."""
        from spanforge.namespaces.template import TemplateVariableBoundPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="version"):
            TemplateVariableBoundPayload(
                template_id="t1",
                version="",      # empty → raise
                variable_name="user_name",
            )

    def test_variable_bound_empty_variable_name_raises_2(self) -> None:
        """Line 111: raise in TemplateVariableBoundPayload for empty variable_name."""
        from spanforge.namespaces.template import TemplateVariableBoundPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="variable_name"):
            TemplateVariableBoundPayload(
                template_id="t1",
                version="2.0",
                variable_name="",  # empty → raise
            )


# ===========================================================================
# template.py 164 — raise for empty failure_reason in TemplateValidationFailedPayload
# ===========================================================================

@pytest.mark.unit
class TestTemplateValFailedReasonPrecision:
    def test_validation_failed_empty_failure_reason_raises_2(self) -> None:
        """Line 164: raise in TemplateValidationFailedPayload for empty failure_reason."""
        from spanforge.namespaces.template import TemplateValidationFailedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="failure_reason"):
            TemplateValidationFailedPayload(
                template_id="tmpl-a",
                version="3.0",
                failure_reason="",  # empty → raise
            )

    def test_validation_failed_empty_version_raises(self) -> None:
        """Line 162: raise in TemplateValidationFailedPayload for empty version."""
        from spanforge.namespaces.template import TemplateValidationFailedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="version"):
            TemplateValidationFailedPayload(
                template_id="t1",
                version="",        # empty → raise
                failure_reason="hash check failed",
            )


# ===========================================================================
# eval_.py 150 — raise for empty scenario_id in EvalScenarioStartedPayload
# ===========================================================================

@pytest.mark.unit
class TestEvalScenarioStartedIdPrecision:
    def test_scenario_started_empty_scenario_id_raises(self) -> None:
        """Line 150: raise in EvalScenarioStartedPayload for empty scenario_id."""
        from spanforge.namespaces.eval_ import EvalScenarioStartedPayload  # noqa: PLC0415
        with pytest.raises(ValueError, match="scenario_id"):
            EvalScenarioStartedPayload(
                scenario_id="",      # empty → raise
                scenario_name="My Test",
                evaluator="pytest-auto",
            )


# ===========================================================================
# trace.py 810 — raise for negative start_time in AgentRunPayload
# ===========================================================================

@pytest.mark.unit
class TestAgentRunStartTimePrecision:
    def test_agent_run_negative_start_time_raises(self) -> None:
        """Line 810: raise in AgentRunPayload for start_time_unix_nano < 0."""
        from spanforge.namespaces.trace import (  # noqa: PLC0415
            AgentRunPayload,
            CostBreakdown,
            TokenUsage,
        )
        tok = TokenUsage(input_tokens=1, output_tokens=1, total_tokens=2)
        cost = CostBreakdown(input_cost_usd=0.0, output_cost_usd=0.0, total_cost_usd=0.0)
        with pytest.raises(ValueError, match="start_time_unix_nano"):
            AgentRunPayload(
                agent_run_id="r1",
                agent_name="bot",
                trace_id="b" * 32,
                root_span_id="a" * 16,
                total_steps=0,
                total_model_calls=0,
                total_tool_calls=0,
                total_token_usage=tok,
                total_cost=cost,
                status="ok",
                start_time_unix_nano=-1,   # negative → raise
                end_time_unix_nano=1_000_000,
                duration_ms=1.0,
            )
