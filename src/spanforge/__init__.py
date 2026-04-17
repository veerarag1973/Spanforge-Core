"""SpanForge — AI lifecycle and governance platform (RFC-0001 SPANFORGE v2.0).

Every tool in the LLM Developer Toolkit emits events that conform to the
:class:`~spanforge.event.Event` envelope defined here.  The schema is
OpenTelemetry-compatible, tamper-evident, and enterprise-grade.

Quick start
-----------
::

    from spanforge import Event, EventType, Tags

    event = Event(
        event_type=EventType.TRACE_SPAN_COMPLETED,
        source="my-agent@1.0.0",
        payload={"span_name": "run_agent", "status": "ok"},
        tags=Tags(env="production", model="gpt-4o"),
    )
    event.validate()
    print(event.to_json())

Public API
----------
Core envelope
~~~~~~~~~~~~~
* :class:`~spanforge.event.Event`
* :class:`~spanforge.event.Tags`
* :data:`~spanforge.event.SCHEMA_VERSION`

Event types
~~~~~~~~~~~
* :class:`~spanforge.types.EventType` â€” RFC Appendix B canonical types
* :func:`~spanforge.types.is_registered`
* :func:`~spanforge.types.namespace_of`
* :func:`~spanforge.types.validate_custom`
* :func:`~spanforge.types.get_by_value`

ULID
~~~~
* :func:`~spanforge.ulid.generate`
* :func:`~spanforge.ulid.validate`
* :func:`~spanforge.ulid.extract_timestamp_ms`

PII redaction (RFC Â§12)
~~~~~~~~~~~~~~~~~~~~~~~
* :class:`~spanforge.redact.Sensitivity`
* :class:`~spanforge.redact.Redactable`
* :class:`~spanforge.redact.RedactionPolicy`
* :class:`~spanforge.redact.RedactionResult`
* :class:`~spanforge.redact.PIINotRedactedError`
* :func:`~spanforge.redact.contains_pii`
* :func:`~spanforge.redact.assert_redacted`

HMAC signing & audit chain (RFC Â§11)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* :func:`~spanforge.signing.sign`
* :func:`~spanforge.signing.verify`
* :func:`~spanforge.signing.verify_chain`
* :func:`~spanforge.signing.assert_verified`
* :class:`~spanforge.signing.ChainVerificationResult`
* :class:`~spanforge.signing.AuditStream`

Export backends (RFC Â§14)
~~~~~~~~~~~~~~~~~~~~~~~~~
* :class:`~spanforge.export.otlp.OTLPExporter`
* :class:`~spanforge.export.otlp.ResourceAttributes`
* :class:`~spanforge.export.webhook.WebhookExporter`
* :class:`~spanforge.export.jsonl.JSONLExporter`

Event routing (RFC Â§14)
~~~~~~~~~~~~~~~~~~~~~~~
* :class:`~spanforge.stream.EventStream`
* :class:`~spanforge.stream.Exporter`
* :func:`~spanforge.stream.iter_file`
* :func:`~spanforge.stream.aiter_file`

Observability spans & tracing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* :class:`~spanforge._span.SpanEvent`
* :data:`~spanforge.types.SpanErrorCategory`

Debug utilities
~~~~~~~~~~~~~~~
* :func:`~spanforge.debug.print_tree`
* :func:`~spanforge.debug.summary`
* :func:`~spanforge.debug.visualize`

Governance (RFC Â§13)
~~~~~~~~~~~~~~~~~~~~~
* :class:`~spanforge.governance.EventGovernancePolicy`
* :class:`~spanforge.governance.GovernanceViolationError`
* :class:`~spanforge.governance.GovernanceWarning`

Consumer registration (RFC Â§16)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* :class:`~spanforge.consumer.ConsumerRecord`
* :class:`~spanforge.consumer.ConsumerRegistry`
* :class:`~spanforge.consumer.IncompatibleSchemaError`
* :func:`~spanforge.consumer.register_consumer`
* :func:`~spanforge.consumer.assert_compatible`

Validation
~~~~~~~~~~
* :func:`~spanforge.validate.validate_event`

Exceptions
~~~~~~~~~~
* :class:`~spanforge.exceptions.LLMSchemaError`
* :class:`~spanforge.exceptions.SchemaValidationError`
* :class:`~spanforge.exceptions.SchemaVersionError`
* :class:`~spanforge.exceptions.ULIDError`
* :class:`~spanforge.exceptions.SerializationError`
* :class:`~spanforge.exceptions.DeserializationError`
* :class:`~spanforge.exceptions.EventTypeError`
* :class:`~spanforge.exceptions.SigningError`
* :class:`~spanforge.exceptions.VerificationError`
* :class:`~spanforge.exceptions.ExportError`

Version history
---------------
v2.0 â€” RFC-0001 SPANFORGE v2.0 SDK baseline.  Canonical 36-type EventType
        registry (Appendix B), v2.0 envelope (SCHEMA_VERSION="2.0"),
        microsecond-precision timestamp mandate, RFC Â§6.3 ULID first-char
        constraint, source pattern allowing mixed-case, SchemaVersionError,
        11 namespace payload modules (RFC Â§8â€“Â§10), audit chain helpers.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Phase 4: Metrics extraction + in-process trace store
# ---------------------------------------------------------------------------
from spanforge import metrics
from spanforge._ansi import BOLD, CYAN, GREEN, RED, RESET, YELLOW, strip_ansi
from spanforge._ansi import color as ansi_color
from spanforge._batch_exporter import BatchExporter

# ---------------------------------------------------------------------------
# Phase 5: Hook registry
# ---------------------------------------------------------------------------
from spanforge._hooks import AsyncHookFn, HookRegistry, hooks
from spanforge._server import TraceViewerServer
from spanforge._span import (
    AgentRunContext,
    AgentRunContextManager,
    AgentStepContext,
    AgentStepContextManager,
    Span,
    SpanContextManager,
    copy_context,
    extract_traceparent,
    inject_traceparent,
)
from spanforge._store import (
    TraceStore,
    get_last_agent_run,
    get_store,
    get_trace,
    list_llm_calls,
    list_tool_calls,
    trace_store,
)
from spanforge._stream import flush, shutdown

# ---------------------------------------------------------------------------
# Phase 1: Trace object and start_trace()
# ---------------------------------------------------------------------------
from spanforge._trace import Trace, start_trace

# ---------------------------------------------------------------------------
# Phase 2: Core tracer + span
# ---------------------------------------------------------------------------
from spanforge._tracer import Tracer, tracer
from spanforge.actor import ActorContext

# ---------------------------------------------------------------------------
# Phase 1: Configuration layer
# ---------------------------------------------------------------------------
from spanforge.config import SpanForgeConfig, configure, get_config, interpolate_env

# ---------------------------------------------------------------------------
# T.R.U.S.T. Framework — Consent, HITL, Model Registry, Explainability
# ---------------------------------------------------------------------------
from spanforge.consent import (
    ConsentBoundary,
    ConsentRecord,
    check_consent,
    grant_consent,
    revoke_consent,
)
from spanforge.consumer import (
    ConsumerRecord,
    ConsumerRegistry,
    IncompatibleSchemaError,
    assert_compatible,
    register_consumer,
)
from spanforge.consumer import (
    get_registry as get_consumer_registry,
)
from spanforge.cost import (
    BudgetMonitor,
    CostRecord,
    CostTracker,
    budget_alert,
    cost_summary,
    emit_cost_attributed,
    emit_cost_event,
)
from spanforge.debug import print_tree, summary, visualize
from spanforge.egress import check_egress
from spanforge.eval import (
    BehaviourScorer,
    EvalReport,
    EvalRunner,
    EvalScore,
    EvalScorer,
    FaithfulnessScorer,
    PIILeakageScorer,
    RefusalDetectionScorer,
    RegressionDetector,
    record_eval_score,
)
from spanforge.event import SCHEMA_VERSION, Event, Tags
from spanforge.exceptions import (
    AuditStorageError,
    DeserializationError,
    EgressViolationError,
    EventTypeError,
    ExportError,
    LLMSchemaError,
    SchemaValidationError,
    SchemaVersionError,
    SerializationError,
    SigningError,
    ULIDError,
    VerificationError,
)
from spanforge.explain import (
    ExplainabilityRecord,
    generate_explanation,
)
from spanforge.export import (
    AppendOnlyJSONLExporter,
    JSONLExporter,
    OTelBridgeExporter,
    OTLPExporter,
    ResourceAttributes,
    WebhookExporter,
    WORMBackend,
    WORMUploadResult,
)
from spanforge.export.otlp_bridge import SpanOTLPBridge, span_to_otlp_dict
from spanforge.hitl import (
    HITLItem,
    HITLQueue,
    list_pending,
    queue_for_review,
    review_item,
)

# ---------------------------------------------------------------------------
# Upstream utilities (upstreamed from sf-behaviour)
# ---------------------------------------------------------------------------
from spanforge.http import ChatCompletionResponse, chat_completion
from spanforge.inspect import InspectorSession, ToolCallRecord, inspect_trace
from spanforge.io import append_jsonl, read_events, read_jsonl, write_events, write_jsonl
from spanforge.metrics_export import (
    MetricsSummary,
    PrometheusMetricsExporter,
    serve_metrics,
)
from spanforge.migrate import MigrationStats, migrate_file, v1_to_v2
from spanforge.model_registry import (
    ModelRegistry,
    ModelRegistryEntry,
    deprecate_model,
    get_model,
    list_models,
    register_model,
    retire_model,
)

# ---------------------------------------------------------------------------
# Namespace payload dataclasses (RFC §8-§10, §11 audit)
# ---------------------------------------------------------------------------
from spanforge.namespaces.audit import (
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
from spanforge.namespaces.consent import ConsentPayload
from spanforge.namespaces.cost import (
    CostAttributedPayload,
    CostSessionRecordedPayload,
    CostTokenRecordedPayload,
)
from spanforge.namespaces.diff import (
    DiffComputedPayload,
    DiffRegressionFlaggedPayload,
)
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
from spanforge.namespaces.hitl import HITLPayload
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
    SpanEvent,
    SpanKind,
    SpanPayload,
    TokenUsage,
    ToolCall,
)
from spanforge.normalizer import GenericNormalizer, ProviderNormalizer
from spanforge.plugins import discover as discover_plugins
from spanforge.processor import (
    NoopSpanProcessor,
    ProcessorChain,
    SpanProcessor,
    add_processor,
    clear_processors,
)
from spanforge.prompt_registry import (
    PromptRegistry,
    PromptVersion,
    get_prompt_version,
    register_prompt,
    render_prompt,
)
from spanforge.redact import (
    DPDP_PATTERNS,
    PII_TYPES,
    PIINotRedactedError,
    PIIScanResult,
    Redactable,
    RedactionPolicy,
    RedactionResult,
    Sensitivity,
    assert_redacted,
    contains_pii,
    scan_payload,
)
from spanforge.regression import RegressionDetector as PassFailRegressionDetector
from spanforge.regression import RegressionReport
from spanforge.regression import compare as compare_regressions
from spanforge.sampling import (
    AlwaysOffSampler,
    AlwaysOnSampler,
    ComplianceSampler,
    ParentBasedSampler,
    RatioSampler,
    RuleBasedSampler,
    Sampler,
    TailBasedSampler,
    bypass_sampling,
)
from spanforge.schema import SchemaValidationError as JsonSchemaValidationError
from spanforge.schema import validate as validate_json_schema
from spanforge.schema import validate_strict as validate_json_schema_strict
from spanforge.signing import (
    AsyncAuditStream,
    AuditStream,
    ChainVerificationResult,
    DictKeyResolver,
    EnvKeyResolver,
    KeyResolver,
    StaticKeyResolver,
    assert_verified,
    check_key_expiry,
    derive_key,
    sign,
    validate_key_strength,
    verify,
    verify_chain,
)
from spanforge.stats import latency_summary, percentile
from spanforge.stream import EventStream, Exporter, aiter_file, iter_file
from spanforge.trace import trace
from spanforge.types import (
    EventType,
    SpanErrorCategory,
    get_by_value,
    is_registered,
    namespace_of,
    validate_custom,
)
from spanforge.ulid import extract_timestamp_ms
from spanforge.ulid import generate as generate_ulid
from spanforge.ulid import validate as validate_ulid
from spanforge.validate import validate_event

__version__: str = "2.0.2"
#: RFC-0001 SPANFORGE conformance profile label.
from typing import Final as _Final

CONFORMANCE_PROFILE: _Final[str] = "SPANFORGE-Enterprise-2.0"

# Optional sub-modules — import on demand to keep startup cost zero.
from spanforge import (
    auto,
    testing,
)

__all__: list[str] = [
    # Upstream utilities
    "BOLD",
    # Conformance
    "CONFORMANCE_PROFILE",
    "CYAN",
    # DPDP compliance patterns
    "DPDP_PATTERNS",
    "GREEN",
    "PII_TYPES",
    "RED",
    "RESET",
    "SCHEMA_VERSION",
    "YELLOW",
    # Actor identity context
    "ActorContext",
    "AgentRunContext",
    "AgentRunContextManager",
    "AgentRunPayload",
    "AgentStepContext",
    "AgentStepContextManager",
    "AgentStepPayload",
    # Sampling
    "AlwaysOffSampler",
    "AlwaysOnSampler",
    # Append-only export + WORM (SF-13)
    "AppendOnlyJSONLExporter",
    # Async audit stream (GA-06)
    "AsyncAuditStream",
    # Phase 5 — Hooks
    "AsyncHookFn",
    "AuditChainTamperedPayload",
    "AuditChainVerifiedPayload",
    # audit
    "AuditKeyRotatedPayload",
    "AuditStorageError",
    "AuditStream",
    # Batch exporter
    "BatchExporter",
    "BehaviourScorer",
    # Tool 2 — Cost Calculation Engine
    "BudgetMonitor",
    "CacheEvictedPayload",
    # cache
    "CacheHitPayload",
    "CacheMissPayload",
    "CacheWrittenPayload",
    "ChainVerificationResult",
    "ChatCompletionResponse",
    # Compliance sampling (SF-16)
    "ComplianceSampler",
    # ---------------------------------------------------------------------------
    # T.R.U.S.T. Framework — Consent, HITL, Model Registry, Explainability
    # ---------------------------------------------------------------------------
    # Consent boundary
    "ConsentBoundary",
    "ConsentPayload",
    "ConsentRecord",
    # Consumer registration (RFC Â§16)
    "ConsumerRecord",
    "ConsumerRegistry",
    "CostAttributedPayload",
    "CostBreakdown",
    "CostRecord",
    "CostSessionRecordedPayload",
    # cost
    "CostTokenRecordedPayload",
    "CostTracker",
    "DecisionPoint",
    "DeserializationError",
    "DictKeyResolver",
    # diff
    "DiffComputedPayload",
    "DiffRegressionFlaggedPayload",
    # Egress enforcement exceptions (SF-14)
    "EgressViolationError",
    "EnvKeyResolver",
    "EvalRegressionDetectedPayload",
    # Evaluation hooks
    "EvalReport",
    "EvalRunner",
    "EvalScenarioCompletedPayload",
    "EvalScenarioStartedPayload",
    "EvalScore",
    # eval
    "EvalScoreRecordedPayload",
    "EvalScorer",
    # Core envelope
    "Event",
    # Event routing (RFC §14)
    "EventStream",
    # Event types
    "EventType",
    "EventTypeError",
    # Explainability
    "ExplainabilityRecord",
    "ExportError",
    "Exporter",
    "FaithfulnessScorer",
    "FenceMaxRetriesExceededPayload",
    "FenceRetryTriggeredPayload",
    # fence
    "FenceValidatedPayload",
    "GenAIOperationName",
    # Namespace payload dataclasses (RFC §8-§11)
    # trace — value objects
    "GenAISystem",
    "GenericNormalizer",
    # guard
    "GuardPayload",
    # Human-in-the-loop
    "HITLItem",
    "HITLPayload",
    "HITLQueue",
    "HookRegistry",
    "IncompatibleSchemaError",
    # Tool 3 — Tool Call Inspector
    "InspectorSession",
    "JSONLExporter",
    "JsonSchemaValidationError",
    # Multi-tenant key resolvers (GA-04)
    "KeyResolver",
    # Exceptions
    "LLMSchemaError",
    # Prometheus metrics
    "MetricsSummary",
    # Schema migration (GA-05)
    "MigrationStats",
    "ModelInfo",
    # Model registry
    "ModelRegistry",
    "ModelRegistryEntry",
    "NoopSpanProcessor",
    "OTLPExporter",
    # Export backends (RFC §14)
    "OTelBridgeExporter",
    "PIILeakageScorer",
    "PIINotRedactedError",
    # PII deep scan (GA-03)
    "PIIScanResult",
    "ParentBasedSampler",
    "PassFailRegressionDetector",
    "PricingTier",
    "ProcessorChain",
    "PrometheusMetricsExporter",
    # Prompt registry
    "PromptRegistry",
    # prompt
    "PromptRenderedPayload",
    "PromptTemplateLoadedPayload",
    "PromptVersion",
    "PromptVersionChangedPayload",
    # Normalizer (RFC-0001 §10.4)
    "ProviderNormalizer",
    "RatioSampler",
    "ReasoningStep",
    "RedactAppliedPayload",
    "RedactPhiDetectedPayload",
    # redact
    "RedactPiiDetectedPayload",
    "Redactable",
    "RedactionPolicy",
    "RedactionResult",
    "RefusalDetectionScorer",
    "RegressionDetector",
    "RegressionReport",
    "ResourceAttributes",
    "RuleBasedSampler",
    "Sampler",
    "SchemaValidationError",
    "SchemaVersionError",
    # PII Redaction (RFC Â§12)
    "Sensitivity",
    "SerializationError",
    "SigningError",
    "Span",
    "SpanContextManager",
    "SpanErrorCategory",
    "SpanEvent",
    # Phase 1 — Configuration
    "SpanForgeConfig",
    "SpanKind",
    "SpanOTLPBridge",
    # trace — payloads
    "SpanPayload",
    # Span processor pipeline
    "SpanProcessor",
    "StaticKeyResolver",
    "Tags",
    "TailBasedSampler",
    # template
    "TemplateRegisteredPayload",
    "TemplateValidationFailedPayload",
    "TemplateVariableBoundPayload",
    "TokenUsage",
    "ToolCall",
    "ToolCallRecord",
    # Phase 1 — Trace object
    "Trace",
    "TraceStore",
    # Local trace viewer
    "TraceViewerServer",
    # Phase 2 — Tracer + Span
    "Tracer",
    "ULIDError",
    "VerificationError",
    "WORMBackend",
    "WORMUploadResult",
    "WebhookExporter",
    # Metadata
    "__version__",
    "add_processor",
    "aiter_file",
    "ansi_color",
    "append_jsonl",
    "assert_compatible",
    "assert_redacted",
    "assert_verified",
    "auto",
    "budget_alert",
    "bypass_sampling",
    "chat_completion",
    "check_consent",
    # Egress enforcement (SF-14)
    "check_egress",
    # Key management (GA-01)
    "check_key_expiry",
    "clear_processors",
    "compare_regressions",
    "configure",
    "contains_pii",
    # Context propagation helper (Phase 1)
    "copy_context",
    "cost_summary",
    "deprecate_model",
    "derive_key",
    "discover_plugins",
    "emit_cost_attributed",
    "emit_cost_event",
    "extract_timestamp_ms",
    # W3C context propagation
    "extract_traceparent",
    # Graceful shutdown
    "flush",
    "generate_explanation",
    # ULID
    "generate_ulid",
    "get_by_value",
    "get_config",
    "get_consumer_registry",
    "get_last_agent_run",
    "get_model",
    "get_prompt_version",
    "get_store",
    "get_trace",
    "grant_consent",
    "hooks",
    "inject_traceparent",
    "inspect_trace",
    "interpolate_env",
    "is_registered",
    "iter_file",
    "latency_summary",
    "list_llm_calls",
    "list_models",
    "list_pending",
    "list_tool_calls",
    # Phase 4 — Metrics + trace store
    "metrics",
    "migrate_file",
    "namespace_of",
    "percentile",
    # Phase 3 — Debug utilities
    "print_tree",
    "queue_for_review",
    "read_events",
    "read_jsonl",
    "record_eval_score",
    "register_consumer",
    "register_model",
    "register_prompt",
    "render_prompt",
    "retire_model",
    "review_item",
    "revoke_consent",
    "scan_payload",
    "serve_metrics",
    "shutdown",
    # HMAC Signing & Audit Chain (RFC Â§11)
    "sign",
    "span_to_otlp_dict",
    "start_trace",
    "strip_ansi",
    "summary",
    "testing",
    # Tool 1 — @trace() decorator + OTLP bridge
    "trace",
    "trace_store",
    "tracer",
    "v1_to_v2",
    "validate_custom",
    # Validation
    "validate_event",
    "validate_json_schema",
    "validate_json_schema_strict",
    "validate_key_strength",
    "validate_ulid",
    "verify",
    "verify_chain",
    "visualize",
    "write_events",
    "write_jsonl",
]
