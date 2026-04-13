"""spanforge.namespaces — Namespace-specific payload dataclasses (v2.0).

Each sub-module provides dataclasses that model the ``payload`` field of
:class:`~spanforge.event.Event` for a given namespace.

All payload classes share the same contract:

* ``to_dict() -> dict`` — serialise to a plain dict for ``Event.payload``.
* ``from_dict(data) -> cls`` — reconstruct from a plain dict.
* ``__post_init__`` — validates every field at construction time.

Sub-modules
-----------
audit
    :class:`AuditKeyRotatedPayload`, :class:`AuditChainVerifiedPayload`,
    :class:`AuditChainTamperedPayload`, :class:`AuditChainPayload`
cache
    :class:`CacheHitPayload`, :class:`CacheMissPayload`,
    :class:`CacheEvictedPayload`, :class:`CacheWrittenPayload`
chain (RFC-0001 SPANFORGE)
    :class:`ChainPayload`
confidence (RFC-0001 SPANFORGE)
    :class:`ConfidencePayload`
consent (RFC-0001 SPANFORGE)
    *removed*
hitl (RFC-0001 SPANFORGE)
    *removed*
playbook (RFC-0001 SPANFORGE)
    *removed*
cost
    :class:`CostTokenRecordedPayload`, :class:`CostSessionRecordedPayload`,
    :class:`CostAttributedPayload`
decision (RFC-0001 SPANFORGE)
    :class:`DecisionDriver`, :class:`DecisionPayload`
diff
    :class:`DiffComputedPayload`, :class:`DiffRegressionFlaggedPayload`
drift (RFC-0001 SPANFORGE)
    :class:`DriftPayload`
eval_
    :class:`EvalScoreRecordedPayload`, :class:`EvalRegressionDetectedPayload`,
    :class:`EvalScenarioStartedPayload`, :class:`EvalScenarioCompletedPayload`
fence
    :class:`FenceValidatedPayload`, :class:`FenceRetryTriggeredPayload`,
    :class:`FenceMaxRetriesExceededPayload`
guard
    :class:`GuardPayload`
hitl (RFC-0001 SPANFORGE)
    *removed*
latency (RFC-0001 SPANFORGE)
    :class:`LatencyPayload`
playbook (RFC-0001 SPANFORGE)
    *removed*
prompt
    :class:`PromptRenderedPayload`, :class:`PromptTemplateLoadedPayload`,
    :class:`PromptVersionChangedPayload`
redact
    :class:`RedactPiiDetectedPayload`, :class:`RedactPhiDetectedPayload`,
    :class:`RedactAppliedPayload`
template
    :class:`TemplateRegisteredPayload`, :class:`TemplateVariableBoundPayload`,
    :class:`TemplateValidationFailedPayload`
tool_call (RFC-0001 SPANFORGE)
    :class:`ToolCallPayload`
trace
    :class:`GenAISystem`, :class:`GenAIOperationName`, :class:`SpanKind`,
    :class:`TokenUsage`, :class:`ModelInfo`, :class:`CostBreakdown`,
    :class:`PricingTier`, :class:`ToolCall`, :class:`ReasoningStep`,
    :class:`DecisionPoint`, :class:`SpanPayload`, :class:`AgentStepPayload`,
    :class:`AgentRunPayload`
"""

from spanforge.namespaces.audit import (
    AuditChainPayload,
    AuditChainTamperedPayload,
    AuditChainVerifiedPayload,
    AuditKeyRotatedPayload,
)
from spanforge.namespaces.cache import (
    CacheEvictedPayload,
    CacheHitPayload,
    CacheMissPayload,
    CacheWrittenPayload,
)
from spanforge.namespaces.chain import ChainPayload
from spanforge.namespaces.confidence import ConfidencePayload
from spanforge.namespaces.cost import (
    CostAttributedPayload,
    CostSessionRecordedPayload,
    CostTokenRecordedPayload,
)
from spanforge.namespaces.decision import DecisionDriver, DecisionPayload
from spanforge.namespaces.diff import (
    DiffComputedPayload,
    DiffRegressionFlaggedPayload,
)
from spanforge.namespaces.drift import DriftPayload
from spanforge.namespaces.eval_ import (
    EvalRegressionDetectedPayload,
    EvalScenarioCompletedPayload,
    EvalScenarioStartedPayload,
    EvalScoreRecordedPayload,
)
from spanforge.namespaces.fence import (
    FenceMaxRetriesExceededPayload,
    FenceRetryTriggeredPayload,
    FenceValidatedPayload,
)
from spanforge.namespaces.guard import GuardPayload
from spanforge.namespaces.latency import LatencyPayload
from spanforge.namespaces.prompt import (
    PromptRenderedPayload,
    PromptTemplateLoadedPayload,
    PromptVersionChangedPayload,
)
from spanforge.namespaces.redact import (
    RedactAppliedPayload,
    RedactPhiDetectedPayload,
    RedactPiiDetectedPayload,
)
from spanforge.namespaces.template import (
    TemplateRegisteredPayload,
    TemplateValidationFailedPayload,
    TemplateVariableBoundPayload,
)
from spanforge.namespaces.tool_call import ToolCallPayload
from spanforge.namespaces.trace import (
    AgentRunPayload,
    AgentStepPayload,
    CostBreakdown,
    DecisionPoint,
    GenAIOperationName,
    GenAISystem,
    ModelInfo,
    PricingTier,
    ReasoningStep,
    SpanKind,
    SpanPayload,
    TokenUsage,
    ToolCall,
)

__all__: list = [
    "AgentRunPayload",
    "AgentStepPayload",
    # audit (legacy + RFC-0001 SPANFORGE)
    "AuditChainPayload",
    "AuditChainTamperedPayload",
    "AuditChainVerifiedPayload",
    "AuditKeyRotatedPayload",
    # cache
    "CacheEvictedPayload",
    "CacheHitPayload",
    "CacheMissPayload",
    "CacheWrittenPayload",
    # chain (RFC-0001 SPANFORGE)
    "ChainPayload",
    # confidence (RFC-0001 SPANFORGE)
    "ConfidencePayload",
    # cost
    "CostAttributedPayload",
    "CostBreakdown",
    "CostSessionRecordedPayload",
    "CostTokenRecordedPayload",
    # decision (RFC-0001 SPANFORGE)
    "DecisionDriver",
    "DecisionPayload",
    # diff
    "DiffComputedPayload",
    "DiffRegressionFlaggedPayload",
    # drift (RFC-0001 SPANFORGE)
    "DriftPayload",
    # eval
    "EvalRegressionDetectedPayload",
    "EvalScenarioCompletedPayload",
    "EvalScenarioStartedPayload",
    "EvalScoreRecordedPayload",
    # fence
    "FenceMaxRetriesExceededPayload",
    "FenceRetryTriggeredPayload",
    "FenceValidatedPayload",
    # guard
    "GuardPayload",
    # latency (RFC-0001 SPANFORGE)
    "LatencyPayload",
    # trace — value objects and payloads
    "GenAIOperationName",
    "GenAISystem",
    "ModelInfo",
    "PricingTier",
    # prompt
    "PromptRenderedPayload",
    "PromptTemplateLoadedPayload",
    "PromptVersionChangedPayload",
    "ReasoningStep",
    # redact
    "RedactAppliedPayload",
    "RedactPhiDetectedPayload",
    "RedactPiiDetectedPayload",
    "SpanKind",
    "SpanPayload",
    # template
    "TemplateRegisteredPayload",
    "TemplateValidationFailedPayload",
    "TemplateVariableBoundPayload",
    "TokenUsage",
    "ToolCall",
    # tool_call (RFC-0001 SPANFORGE)
    "ToolCallPayload",
    # Backward-compat trace value object
    "DecisionPoint",
]
