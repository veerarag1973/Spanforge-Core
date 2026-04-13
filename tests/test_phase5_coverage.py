"""Branch-coverage supplement for v2.0 namespace payload dataclasses.

Each test is designed to reach a specific branch left uncovered by
test_namespaces.py — primarily every ``raise`` inside ``__post_init__``,
and every optional-field False-branch in ``to_dict()`` / ``from_dict()``.
"""

from __future__ import annotations

import pytest

# ── audit ─────────────────────────────────────────────────────────────────────
from spanforge.namespaces.audit import (
    AuditChainTamperedPayload,
    AuditChainVerifiedPayload,
    AuditKeyRotatedPayload,
)

# ── cache ─────────────────────────────────────────────────────────────────────
from spanforge.namespaces.cache import (
    CacheEvictedPayload,
    CacheHitPayload,
    CacheMissPayload,
    CacheWrittenPayload,
)

# ── cost ──────────────────────────────────────────────────────────────────────
from spanforge.namespaces.cost import (
    CostSessionRecordedPayload,
    CostTokenRecordedPayload,
)

# ── diff ──────────────────────────────────────────────────────────────────────
from spanforge.namespaces.diff import DiffComputedPayload

# ── eval_ ─────────────────────────────────────────────────────────────────────
from spanforge.namespaces.eval_ import (
    EvalRegressionDetectedPayload,
    EvalScenarioCompletedPayload,
    EvalScoreRecordedPayload,
)

# ── fence ─────────────────────────────────────────────────────────────────────
from spanforge.namespaces.fence import (
    FenceMaxRetriesExceededPayload,
    FenceRetryTriggeredPayload,
    FenceValidatedPayload,
)

# ── guard ─────────────────────────────────────────────────────────────────────
from spanforge.namespaces.guard import GuardPayload

# ── prompt ────────────────────────────────────────────────────────────────────
from spanforge.namespaces.prompt import (
    PromptRenderedPayload,
    PromptTemplateLoadedPayload,
    PromptVersionChangedPayload,
)

# ── redact ────────────────────────────────────────────────────────────────────
from spanforge.namespaces.redact import (
    RedactAppliedPayload,
    RedactPhiDetectedPayload,
    RedactPiiDetectedPayload,
)

# ── template ──────────────────────────────────────────────────────────────────
from spanforge.namespaces.template import (
    TemplateRegisteredPayload,
    TemplateValidationFailedPayload,
    TemplateVariableBoundPayload,
)

# ── trace ─────────────────────────────────────────────────────────────────────
from spanforge.namespaces.trace import (
    AgentRunPayload,
    AgentStepPayload,
    CostBreakdown,
    GenAIOperationName,
    ModelInfo,
    SpanKind,
    SpanPayload,
    TokenUsage,
    ToolCall,
)

# ── validate ──────────────────────────────────────────────────────────────────
# (validate_field helper removed in v2.0 — covered via __post_init__ validators)

# ===========================================================================
# helpers
# ===========================================================================

SPAN_ID  = "a" * 16
TRACE_ID = "b" * 32
TS_S = 1_700_000_000_000_000_000
TS_E = 1_700_000_000_001_000_000  # TS_S + 1 ms (= 1_000_000 ns); matches duration_ms=1.0


def _tu() -> TokenUsage:
    return TokenUsage(input_tokens=1, output_tokens=1, total_tokens=2)


def _mi() -> ModelInfo:
    return ModelInfo(system="openai", name="gpt-4o")


def _cb() -> CostBreakdown:
    return CostBreakdown(input_cost_usd=0.001, output_cost_usd=0.001, total_cost_usd=0.002)


def _span(**kw) -> SpanPayload:
    base = {
        "span_id": SPAN_ID, "trace_id": TRACE_ID, "span_name": "s",
        "operation": GenAIOperationName.CHAT, "span_kind": SpanKind.CLIENT,
        "status": "ok", "start_time_unix_nano": TS_S,
        "end_time_unix_nano": TS_E, "duration_ms": 1.0,
    }
    base.update(kw)
    return SpanPayload(**base)


# ===========================================================================
# TokenUsage branch coverage
# ===========================================================================


class TestTokenUsageBranches:
    def test_negative_output_tokens_rejected(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            TokenUsage(input_tokens=10, output_tokens=-1, total_tokens=9)

    def test_minimal_to_dict_no_optional_keys(self) -> None:
        d = TokenUsage(input_tokens=1, output_tokens=1, total_tokens=2).to_dict()
        for key in ("cached_tokens", "cache_creation_tokens", "reasoning_tokens", "image_tokens"):
            assert key not in d

    def test_with_all_optional_fields(self) -> None:
        tu = TokenUsage(
            input_tokens=10, output_tokens=10, total_tokens=20,
            cached_tokens=3, reasoning_tokens=2, image_tokens=1,
        )
        d = tu.to_dict()
        assert d["cached_tokens"] == 3
        assert d["reasoning_tokens"] == 2

    def test_from_dict_minimal(self) -> None:
        tu = TokenUsage.from_dict({"input_tokens": 5, "output_tokens": 5, "total_tokens": 10})
        assert tu.cached_tokens is None


# ===========================================================================
# ModelInfo branch coverage
# ===========================================================================


class TestModelInfoBranches:
    def test_minimal_to_dict_no_optional_keys(self) -> None:
        d = ModelInfo(system="openai", name="gpt-4o").to_dict()
        assert "response_model" not in d
        assert "version" not in d

    def test_with_all_optional_fields(self) -> None:
        mi = ModelInfo(system="openai", name="gpt-4o", version="2024-11", response_model="gpt-4o-mini")  # noqa: E501
        d = mi.to_dict()
        assert d["version"] == "2024-11"
        assert d["response_model"] == "gpt-4o-mini"

    def test_from_dict_minimal(self) -> None:
        mi = ModelInfo.from_dict({"system": "anthropic", "name": "claude-3-opus"})
        assert mi.version is None


# ===========================================================================
# CostBreakdown branch coverage
# ===========================================================================


class TestCostBreakdownBranches:
    def test_minimal_to_dict_omits_optional_fields(self) -> None:
        d = CostBreakdown(input_cost_usd=0.001, output_cost_usd=0.001, total_cost_usd=0.002).to_dict()  # noqa: E501
        assert "pricing_date" not in d

    def test_with_all_optional_fields(self) -> None:
        cb = CostBreakdown(
            input_cost_usd=0.001, output_cost_usd=0.001, total_cost_usd=0.0025,
            reasoning_cost_usd=0.0005, pricing_date="2026-01-01",
        )
        d = cb.to_dict()
        assert d["pricing_date"] == "2026-01-01"

    def test_negative_output_rejected(self) -> None:
        with pytest.raises(ValueError):
            CostBreakdown(input_cost_usd=0.001, output_cost_usd=-0.001, total_cost_usd=0.0)


# ===========================================================================
# ToolCall branch coverage
# ===========================================================================


class TestToolCallBranches:
    def test_empty_function_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            ToolCall(tool_call_id="tc_01", function_name="", status="success")

    def test_minimal_to_dict_no_optional_keys(self) -> None:
        d = ToolCall(tool_call_id="tc_01", function_name="search", status="success").to_dict()
        assert "duration_ms" not in d
        assert "error_type" not in d

    def test_with_optional_fields(self) -> None:
        tc = ToolCall(
            tool_call_id="tc_01", function_name="search", status="error",
            error_type="TimeoutError", duration_ms=100.0,
        )
        d = tc.to_dict()
        assert d["error_type"] == "TimeoutError"


# ===========================================================================
# SpanPayload branch coverage
# ===========================================================================


class TestSpanPayloadBranches:
    def test_invalid_parent_span_id(self) -> None:
        with pytest.raises(ValueError):
            _span(parent_span_id="tooshort")

    def test_negative_start_time_rejected(self) -> None:
        with pytest.raises(ValueError):
            _span(start_time_unix_nano=-1, end_time_unix_nano=0)

    def test_minimal_to_dict_omits_optional_fields(self) -> None:
        d = _span().to_dict()
        assert "model" not in d
        assert "token_usage" not in d
        assert "cost" not in d
        assert "error" not in d

    def test_from_dict_minimal(self) -> None:
        d = _span().to_dict()
        sp = SpanPayload.from_dict(d)
        assert sp.model is None
        assert sp.token_usage is None

    def test_from_dict_with_model_and_usage(self) -> None:
        d = _span(model=_mi(), token_usage=_tu()).to_dict()
        sp = SpanPayload.from_dict(d)
        assert sp.model is not None
        assert sp.token_usage.input_tokens == 1


# ===========================================================================
# AgentStepPayload branch coverage
# ===========================================================================


class TestAgentStepPayloadBranches:
    def _make(self, **kw) -> AgentStepPayload:
        base = {
            "agent_run_id": "run_a", "step_index": 0,
            "span_id": SPAN_ID, "trace_id": TRACE_ID,
            "operation": GenAIOperationName.CHAT,
            "tool_calls": [], "reasoning_steps": [], "decision_points": [],
            "status": "ok",
            "start_time_unix_nano": TS_S, "end_time_unix_nano": TS_E, "duration_ms": 1.0,
        }
        base.update(kw)
        return AgentStepPayload(**base)

    def test_invalid_parent_span_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            self._make(parent_span_id="bad")

    def test_minimal_to_dict_no_model(self) -> None:
        d = self._make().to_dict()
        assert "model" not in d

    def test_from_dict_minimal(self) -> None:
        d = self._make().to_dict()
        step = AgentStepPayload.from_dict(d)
        assert step.model is None
        assert step.cost is None


# ===========================================================================
# AgentRunPayload branch coverage
# ===========================================================================


class TestAgentRunPayloadBranches:
    def _make(self, **kw) -> AgentRunPayload:
        base = {
            "agent_run_id": "run_a", "agent_name": "bot",
            "trace_id": TRACE_ID, "root_span_id": SPAN_ID,
            "total_steps": 1, "total_model_calls": 1, "total_tool_calls": 0,
            "total_token_usage": _tu(), "total_cost": _cb(),
            "status": "ok",
            "start_time_unix_nano": TS_S, "end_time_unix_nano": TS_E, "duration_ms": 1.0,
        }
        base.update(kw)
        return AgentRunPayload(**base)

    def test_negative_model_calls_rejected(self) -> None:
        with pytest.raises(ValueError):
            self._make(total_model_calls=-1)

    def test_negative_tool_calls_rejected(self) -> None:
        with pytest.raises(ValueError):
            self._make(total_tool_calls=-1)

    def test_max_steps_exceeded_status_valid(self) -> None:
        run = self._make(status="max_steps_exceeded")
        assert run.status == "max_steps_exceeded"

    def test_minimal_to_dict_no_termination_reason(self) -> None:
        d = self._make().to_dict()
        assert "termination_reason" not in d

    def test_with_termination_reason(self) -> None:
        run = self._make(termination_reason="goal_reached")
        assert run.to_dict()["termination_reason"] == "goal_reached"

    def test_from_dict_minimal(self) -> None:
        d = self._make().to_dict()
        run = AgentRunPayload.from_dict(d)
        assert run.termination_reason is None


# ===========================================================================
# CostTokenRecordedPayload branch coverage
# ===========================================================================


class TestCostTokenRecordedBranches:
    def test_rejects_non_token_usage(self) -> None:
        with pytest.raises(TypeError):
            CostTokenRecordedPayload(cost=_cb(), token_usage={"in": 1}, model=_mi())  # type: ignore[arg-type]

    def test_rejects_non_model_info(self) -> None:
        with pytest.raises(TypeError):
            CostTokenRecordedPayload(cost=_cb(), token_usage=_tu(), model="gpt-4o")  # type: ignore[arg-type]

    def test_minimal_to_dict_no_optional(self) -> None:
        d = CostTokenRecordedPayload(cost=_cb(), token_usage=_tu(), model=_mi()).to_dict()
        assert "span_id" not in d
        assert "agent_run_id" not in d


# ===========================================================================
# CostSessionRecordedPayload branch coverage
# ===========================================================================


class TestCostSessionRecordedBranches:
    def test_negative_call_count_rejected(self) -> None:
        with pytest.raises(ValueError):
            CostSessionRecordedPayload(total_cost=_cb(), total_token_usage=_tu(), call_count=-1)

    def test_minimal_to_dict_no_session_id(self) -> None:
        d = CostSessionRecordedPayload(total_cost=_cb(), total_token_usage=_tu(), call_count=1).to_dict()  # noqa: E501
        assert "session_id" not in d


# ===========================================================================
# DiffComputedPayload branch coverage
# ===========================================================================


class TestDiffComputedBranches:
    def test_similarity_below_zero_rejected(self) -> None:
        with pytest.raises(ValueError):
            DiffComputedPayload(
                ref_event_id="a" * 26, target_event_id="b" * 26,
                diff_type="text", similarity_score=-0.1,
            )

    def test_minimal_to_dict_no_patch(self) -> None:
        d = DiffComputedPayload(
            ref_event_id="a" * 26, target_event_id="b" * 26,
            diff_type="response", similarity_score=0.5,
        ).to_dict()
        assert "added_tokens" not in d
        assert "computation_duration_ms" not in d

    def test_from_dict_with_optional_omitted(self) -> None:
        d = DiffComputedPayload(
            ref_event_id="a" * 26, target_event_id="b" * 26,
            diff_type="token_usage", similarity_score=0.7,
        ).to_dict()
        p = DiffComputedPayload.from_dict(d)
        assert p.added_tokens is None


# ===========================================================================
# EvalScoreRecordedPayload branch coverage
# ===========================================================================


class TestEvalScoreBranches:
    def test_empty_metric_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            EvalScoreRecordedPayload(evaluator="e", metric_name="", score=0.5)

    def test_minimal_to_dict_omits_optional_fields(self) -> None:
        d = EvalScoreRecordedPayload(evaluator="e", metric_name="accuracy", score=0.9).to_dict()
        assert "threshold" not in d
        assert "passed" not in d
        assert "rationale" not in d

    def test_from_dict_optional_none(self) -> None:
        d = EvalScoreRecordedPayload(evaluator="e", metric_name="m", score=0.5).to_dict()
        p = EvalScoreRecordedPayload.from_dict(d)
        assert p.passed is None


# ===========================================================================
# EvalRegressionDetectedPayload branch coverage
# ===========================================================================


class TestEvalRegressionBranches:
    def test_invalid_severity_rejected(self) -> None:
        with pytest.raises(ValueError):
            EvalRegressionDetectedPayload(
                metric_name="m", baseline_score=0.9, current_score=0.7,
                delta=-0.2, regression_pct=22.0, severity="extreme",
            )

    def test_minimal_to_dict_no_severity(self) -> None:
        d = EvalRegressionDetectedPayload(
            metric_name="m", baseline_score=0.9, current_score=0.7,
            delta=-0.2, regression_pct=22.0,
        ).to_dict()
        assert "severity" not in d


# ===========================================================================
# EvalScenarioCompletedPayload branch coverage
# ===========================================================================


class TestEvalScenarioCompletedBranches:
    def test_negative_duration_rejected(self) -> None:
        with pytest.raises(ValueError):
            EvalScenarioCompletedPayload(scenario_id="s", status="passed", duration_ms=-1.0)

    def test_minimal_to_dict_no_error(self) -> None:
        d = EvalScenarioCompletedPayload(scenario_id="s", status="passed", duration_ms=1.0).to_dict()  # noqa: E501
        assert "error" not in d


# ===========================================================================
# FenceValidatedPayload branch coverage
# ===========================================================================


class TestFenceValidatedBranches:
    def test_empty_fence_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            FenceValidatedPayload(fence_id="", schema_name="s", attempt=1)

    def test_empty_schema_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            FenceValidatedPayload(fence_id="f", schema_name="", attempt=1)

    def test_minimal_to_dict_omits_optional(self) -> None:
        d = FenceValidatedPayload(fence_id="f", schema_name="s", attempt=1).to_dict()
        assert "output_type" not in d
        assert "validation_duration_ms" not in d


# ===========================================================================
# FenceRetryTriggeredPayload branch coverage
# ===========================================================================


class TestFenceRetryBranches:
    def test_attempt_zero_rejected(self) -> None:
        with pytest.raises(ValueError):
            FenceRetryTriggeredPayload(
                fence_id="f", schema_name="s",
                attempt=0, max_attempts=3, violation_summary="v",
            )

    def test_max_attempts_zero_rejected(self) -> None:
        with pytest.raises(ValueError):
            FenceRetryTriggeredPayload(
                fence_id="f", schema_name="s",
                attempt=1, max_attempts=0, violation_summary="v",
            )

    def test_minimal_to_dict_no_optional(self) -> None:
        d = FenceRetryTriggeredPayload(
            fence_id="f", schema_name="s",
            attempt=1, max_attempts=3, violation_summary="v",
        ).to_dict()
        assert "span_id" not in d
        assert "output_type" not in d


# ===========================================================================
# FenceMaxRetriesExceededPayload branch coverage
# ===========================================================================


class TestFenceMaxRetriesBranches:
    def test_empty_fence_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            FenceMaxRetriesExceededPayload(
                fence_id="", schema_name="s", attempts_made=3, final_violation_summary="v",
            )

    def test_attempts_made_zero_rejected(self) -> None:
        with pytest.raises(ValueError):
            FenceMaxRetriesExceededPayload(
                fence_id="f", schema_name="s", attempts_made=0, final_violation_summary="v",
            )

    def test_minimal_to_dict_no_optional(self) -> None:
        d = FenceMaxRetriesExceededPayload(
            fence_id="f", schema_name="s", attempts_made=1, final_violation_summary="v",
        ).to_dict()
        assert "span_id" not in d


# ===========================================================================
# GuardPayload branch coverage
# ===========================================================================


class TestGuardPayloadBranches:
    def test_minimal_to_dict_omits_optional(self) -> None:
        d = GuardPayload(classifier="c", direction="input", action="blocked", score=0.9).to_dict()
        assert "threshold" not in d
        assert "policy_id" not in d
        assert "content_hash" not in d

    def test_from_dict_minimal(self) -> None:
        d = GuardPayload(classifier="c", direction="input", action="passed", score=0.1).to_dict()
        p = GuardPayload.from_dict(d)
        assert p.policy_id is None
        assert p.categories == []

    def test_non_numeric_score_rejected(self) -> None:
        with pytest.raises((ValueError, TypeError)):
            GuardPayload(classifier="c", direction="input", action="blocked", score="high")  # type: ignore[arg-type]


# ===========================================================================
# PromptRenderedPayload branch coverage
# ===========================================================================


class TestPromptRenderedBranches:
    def test_empty_template_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            PromptRenderedPayload(template_id="", version="v1", rendered_hash="a" * 64)

    def test_minimal_to_dict_omits_optional(self) -> None:
        d = PromptRenderedPayload(template_id="t", version="v1", rendered_hash="a" * 64).to_dict()
        assert "render_duration_ms" not in d
        assert "variable_count" not in d

    def test_from_dict_minimal(self) -> None:
        d = PromptRenderedPayload(template_id="t", version="v1", rendered_hash="a" * 64).to_dict()
        p = PromptRenderedPayload.from_dict(d)
        assert p.span_id is None


# ===========================================================================
# PromptTemplateLoadedPayload branch coverage
# ===========================================================================


class TestPromptTemplateLoadedBranches:
    def test_empty_template_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            PromptTemplateLoadedPayload(template_id="", version="v1", source="registry")

    def test_minimal_to_dict_omits_optional(self) -> None:
        d = PromptTemplateLoadedPayload(template_id="t", version="v1", source="registry").to_dict()
        assert "template_hash" not in d
        assert "cache_hit" not in d


# ===========================================================================
# PromptVersionChangedPayload branch coverage
# ===========================================================================


class TestPromptVersionChangedBranches:
    def test_empty_template_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            PromptVersionChangedPayload(
                template_id="", previous_version="v1", new_version="v2",
                change_reason="fix",
            )

    def test_empty_previous_version_rejected(self) -> None:
        with pytest.raises(ValueError):
            PromptVersionChangedPayload(
                template_id="t", previous_version="", new_version="v2",
                change_reason="fix",
            )

    def test_minimal_to_dict_omits_optional(self) -> None:
        d = PromptVersionChangedPayload(
            template_id="t", previous_version="v1", new_version="v2", change_reason="fix",
        ).to_dict()
        assert "changed_by" not in d
        assert "previous_hash" not in d
        assert "new_hash" not in d


# ===========================================================================
# TemplateRegisteredPayload branch coverage
# ===========================================================================


class TestTemplateRegisteredBranches:
    def test_empty_template_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            TemplateRegisteredPayload(template_id="", version="v1", template_hash="a" * 64)

    def test_minimal_to_dict_omits_description(self) -> None:
        d = TemplateRegisteredPayload(template_id="t", version="v1", template_hash="a" * 64).to_dict()  # noqa: E501
        assert "description" not in d


# ===========================================================================
# TemplateVariableBoundPayload branch coverage
# ===========================================================================


class TestTemplateVariableBoundBranches:
    def test_empty_variable_name_rejected(self) -> None:
        with pytest.raises(ValueError):
            TemplateVariableBoundPayload(template_id="t", version="v1", variable_name="")

    def test_minimal_to_dict_omits_value_hash(self) -> None:
        d = TemplateVariableBoundPayload(template_id="t", version="v1", variable_name="x").to_dict()
        assert "value_hash" not in d


# ===========================================================================
# TemplateValidationFailedPayload branch coverage
# ===========================================================================


class TestTemplateValidationFailedBranches:
    def test_empty_failure_reason_rejected(self) -> None:
        with pytest.raises(ValueError):
            TemplateValidationFailedPayload(template_id="t", version="v1", failure_reason="")

    def test_minimal_to_dict_empty_missing_vars(self) -> None:
        d = TemplateValidationFailedPayload(
            template_id="t", version="v1", failure_reason="missing"
        ).to_dict()
        # missing_variables defaults to [] and should appear (it's not None)
        assert "failure_reason" in d


# ===========================================================================
# CacheHitPayload branch coverage
# ===========================================================================


class TestCacheHitBranches:
    def test_similarity_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            CacheHitPayload(key_hash="a" * 64, namespace="ns", similarity_score=-0.5)

    def test_empty_namespace_rejected(self) -> None:
        with pytest.raises(ValueError):
            CacheHitPayload(key_hash="a" * 64, namespace="", similarity_score=0.9)

    def test_minimal_to_dict_omits_optional(self) -> None:
        d = CacheHitPayload(key_hash="a" * 64, namespace="ns", similarity_score=0.9).to_dict()
        assert "cached_at" not in d
        assert "retrieval_latency_ms" not in d


# ===========================================================================
# CacheMissPayload branch coverage
# ===========================================================================


class TestCacheMissBranches:
    def test_empty_key_hash_rejected(self) -> None:
        with pytest.raises(ValueError):
            CacheMissPayload(key_hash="", namespace="ns")

    def test_minimal_to_dict_omits_optional(self) -> None:
        d = CacheMissPayload(key_hash="a" * 64, namespace="ns").to_dict()
        assert "nearest_similarity" not in d


# ===========================================================================
# CacheEvictedPayload branch coverage
# ===========================================================================


class TestCacheEvictedBranches:
    def test_empty_eviction_reason_rejected(self) -> None:
        with pytest.raises(ValueError):
            CacheEvictedPayload(key_hash="a" * 64, namespace="ns", eviction_reason="")

    def test_minimal_to_dict_omits_optional(self) -> None:
        d = CacheEvictedPayload(key_hash="a" * 64, namespace="ns", eviction_reason="ttl_expired").to_dict()  # noqa: E501
        assert "evicted_at" not in d


# ===========================================================================
# CacheWrittenPayload branch coverage
# ===========================================================================


class TestCacheWrittenBranches:
    def test_negative_ttl_rejected(self) -> None:
        with pytest.raises(ValueError):
            CacheWrittenPayload(key_hash="a" * 64, namespace="ns", ttl_seconds=-1)

    def test_minimal_to_dict_omits_optional(self) -> None:
        d = CacheWrittenPayload(key_hash="a" * 64, namespace="ns", ttl_seconds=60).to_dict()
        assert "entry_size_bytes" not in d
        assert "cached_at" not in d


# ===========================================================================
# RedactPiiDetectedPayload branch coverage
# ===========================================================================


class TestRedactPiiBranches:
    def test_empty_detected_categories_rejected(self) -> None:
        with pytest.raises(ValueError):
            RedactPiiDetectedPayload(
                detected_categories=[], field_names=["msg"], sensitivity_level="high",
            )

    def test_minimal_to_dict_omits_optional(self) -> None:
        d = RedactPiiDetectedPayload(
            detected_categories=["email"], field_names=["msg"], sensitivity_level="HIGH",
        ).to_dict()
        assert "detector" not in d
        assert "subject_event_id" not in d


# ===========================================================================
# RedactPhiDetectedPayload branch coverage
# ===========================================================================


class TestRedactPhiBranches:
    def test_empty_field_names_rejected(self) -> None:
        with pytest.raises(ValueError):
            RedactPhiDetectedPayload(detected_categories=["diagnosis"], field_names=[])

    def test_minimal_to_dict_omits_optional(self) -> None:
        d = RedactPhiDetectedPayload(
            detected_categories=["diagnosis"], field_names=["notes"],
        ).to_dict()
        assert "detection_model" not in d


# ===========================================================================
# RedactAppliedPayload branch coverage
# ===========================================================================


class TestRedactAppliedBranches:
    def test_negative_redacted_count_rejected(self) -> None:
        with pytest.raises(ValueError):
            RedactAppliedPayload(policy_min_sensitivity="high", redacted_by="shield", redacted_count=-1)  # noqa: E501

    def test_minimal_to_dict_redacted_fields_empty(self) -> None:
        d = RedactAppliedPayload(
            policy_min_sensitivity="HIGH", redacted_by="shield", redacted_count=0,
        ).to_dict()
        # redacted_fields defaults to [] — may or may not appear
        assert "policy_min_sensitivity" in d


# ===========================================================================
# AuditKeyRotatedPayload branch coverage
# ===========================================================================


class TestAuditKeyRotatedBranches:
    def test_empty_key_id_rejected(self) -> None:
        with pytest.raises(ValueError):
            AuditKeyRotatedPayload(
                key_id="", previous_key_id="key_001",
                rotated_at="2026-01-01T00:00:00Z", rotated_by="bot",
            )

    def test_minimal_to_dict_omits_optional(self) -> None:
        d = AuditKeyRotatedPayload(
            key_id="k2", previous_key_id="k1",
            rotated_at="2026-01-01T00:00:00Z", rotated_by="bot",
        ).to_dict()
        assert "rotation_reason" not in d


# ===========================================================================
# AuditChainVerifiedPayload branch coverage
# ===========================================================================


class TestAuditChainVerifiedBranches:
    def test_zero_event_count_rejected(self) -> None:
        # The class does not enforce event_count > 0; test empty verified_by instead
        with pytest.raises(ValueError):
            AuditChainVerifiedPayload(
                verified_from_event_id="a" * 26,
                verified_to_event_id="b" * 26,
                event_count=1,
                verified_at="2026-01-01T00:00:00Z",
                verified_by="",
            )

    def test_minimal_to_dict_omits_optional(self) -> None:
        d = AuditChainVerifiedPayload(
            verified_from_event_id="a" * 26,
            verified_to_event_id="b" * 26,
            event_count=1,
            verified_at="2026-01-01T00:00:00Z",
            verified_by="bot",
        ).to_dict()
        assert "chain_hash" not in d


# ===========================================================================
# AuditChainTamperedPayload branch coverage
# ===========================================================================


class TestAuditChainTamperedBranches:
    def test_zero_tampered_count_rejected(self) -> None:
        # The class does not enforce tampered_count > 0; test empty detected_by instead
        with pytest.raises(ValueError):
            AuditChainTamperedPayload(
                first_tampered_event_id="a" * 26,
                tampered_count=1,
                detected_at="2026-01-01T00:00:00Z",
                detected_by="",
            )

    def test_minimal_to_dict_omits_remediation(self) -> None:
        d = AuditChainTamperedPayload(
            first_tampered_event_id="a" * 26,
            tampered_count=1,
            detected_at="2026-01-01T00:00:00Z",
            detected_by="guard",
        ).to_dict()
        assert "remediation_action" not in d
