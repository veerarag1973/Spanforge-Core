# spanforge.types

Namespaced event type registry and custom type validation helpers.

---

## `EventType`

```python
class EventType(str, Enum)
```

Exhaustive registry of all first-party SPANFORGE event types.

`EventType` is a `str` subclass, so values can be compared directly with plain
strings, used as dict keys, and serialised without conversion:

```python
assert EventType.TRACE_SPAN_COMPLETED == "llm.trace.span.completed"
```

Each member also carries `.namespace` and `.description` properties.

### Properties

#### `namespace -> str`

The `llm.<ns>` namespace prefix for this event type.

```python
EventType.TRACE_SPAN_COMPLETED.namespace  # "llm.trace"
```

#### `description -> str`

A one-line human-readable description of this event type.

### Members

#### `llm.diff.*`

| Member | String value | Description |
|--------|-------------|-------------|
| `DIFF_COMPUTED` | `llm.diff.computed` | A textual or semantic diff was computed between two events. |
| `DIFF_REGRESSION_FLAGGED` | `llm.diff.regression.flagged` | A diff computation exceeded the regression similarity threshold. |

#### `llm.prompt.*`

| Member | String value | Description |
|--------|-------------|-------------|
| `PROMPT_RENDERED` | `llm.prompt.rendered` | A prompt template was instantiated with variable values. |
| `PROMPT_TEMPLATE_LOADED` | `llm.prompt.template.loaded` | A prompt template was loaded from the registry. |
| `PROMPT_VERSION_CHANGED` | `llm.prompt.version.changed` | The active version of a prompt template was updated. |

#### `llm.template.*`

| Member | String value | Description |
|--------|-------------|-------------|
| `TEMPLATE_REGISTERED` | `llm.template.registered` | A new template or version was added to the registry. |
| `TEMPLATE_VARIABLE_BOUND` | `llm.template.variable.bound` | A variable was bound to a template for a specific rendering. |
| `TEMPLATE_VALIDATION_FAILED` | `llm.template.validation.failed` | A template could not be loaded or rendered due to validation errors. |

#### `llm.trace.*`

| Member | String value | Description |
|--------|-------------|-------------|
| `TRACE_SPAN_STARTED` | `llm.trace.span.started` | A new LLM call/tool-execution span was opened. |
| `TRACE_SPAN_COMPLETED` | `llm.trace.span.completed` | A span completed successfully. |
| `TRACE_SPAN_FAILED` | `llm.trace.span.failed` | A span terminated with an error or timeout. |
| `TRACE_AGENT_STEP` | `llm.trace.agent.step` | One iteration of a multi-step agent loop. |
| `TRACE_AGENT_COMPLETED` | `llm.trace.agent.completed` | A multi-step agent run resolved. |
| `TRACE_REASONING_STEP` | `llm.trace.reasoning.step` | One chain-of-thought reasoning step (v2.0+). |

#### `llm.cost.*`

| Member | String value | Description |
|--------|-------------|-------------|
| `COST_TOKEN_RECORDED` | `llm.cost.token.recorded` | Per-call token cost recorded. |
| `COST_SESSION_RECORDED` | `llm.cost.session.recorded` | Session-level cost rollup recorded. |
| `COST_ATTRIBUTED` | `llm.cost.attributed` | Cost attributed to a feature, team, or budget centre. |

#### `llm.eval.*`

| Member | String value | Description |
|--------|-------------|-------------|
| `EVAL_SCORE_RECORDED` | `llm.eval.score.recorded` | A quality score was attached to a span or agent run. |
| `EVAL_REGRESSION_DETECTED` | `llm.eval.regression.detected` | A quality regression relative to baseline was detected. |
| `EVAL_SCENARIO_STARTED` | `llm.eval.scenario.started` | An evaluation scenario run started. |
| `EVAL_SCENARIO_COMPLETED` | `llm.eval.scenario.completed` | An evaluation scenario run completed. |

#### `llm.guard.*`

| Member | String value | Description |
|--------|-------------|-------------|
| `GUARD_INPUT_BLOCKED` | `llm.guard.input.blocked` | A model input was blocked by the safety classifier. |
| `GUARD_INPUT_PASSED` | `llm.guard.input.passed` | A model input passed the safety classifier. |
| `GUARD_OUTPUT_BLOCKED` | `llm.guard.output.blocked` | A model output was blocked by the safety classifier. |
| `GUARD_OUTPUT_PASSED` | `llm.guard.output.passed` | A model output passed the safety classifier. |

#### `llm.redact.*`

| Member | String value | Description |
|--------|-------------|-------------|
| `REDACT_PII_DETECTED` | `llm.redact.pii.detected` | PII categories were found in one or more event fields. |
| `REDACT_PHI_DETECTED` | `llm.redact.phi.detected` | PHI categories (HIPAA-regulated) were found. |
| `REDACT_APPLIED` | `llm.redact.applied` | A RedactionPolicy was applied; sensitive values replaced. |

#### `llm.fence.*`

| Member | String value | Description |
|--------|-------------|-------------|
| `FENCE_VALIDATED` | `llm.fence.validated` | Model output passed all structural constraint checks. |
| `FENCE_RETRY_TRIGGERED` | `llm.fence.retry.triggered` | Model output failed schema validation; retry initiated. |
| `FENCE_MAX_RETRIES_EXCEEDED` | `llm.fence.max_retries.exceeded` | All retry attempts exhausted without conforming output. |

#### `llm.audit.*`

| Member | String value | Description |
|--------|-------------|-------------|
| `AUDIT_KEY_ROTATED` | `llm.audit.key.rotated` | The HMAC signing key was rotated (RFC-0001 §11.5). |

#### `consent.*`

| Member | String value | Description |
|--------|-------------|-------------|
| `CONSENT_GRANTED` | `consent.granted` | Data-subject consent was recorded. |
| `CONSENT_REVOKED` | `consent.revoked` | Previously granted consent was withdrawn. |
| `CONSENT_VIOLATION` | `consent.violation` | Processing occurred without valid consent. |

#### `hitl.*`

| Member | String value | Description |
|--------|-------------|-------------|
| `HITL_QUEUED` | `hitl.queued` | A decision was queued for human review. |
| `HITL_REVIEWED` | `hitl.reviewed` | A human reviewer completed their review. |
| `HITL_ESCALATED` | `hitl.escalated` | A decision was escalated to a higher review tier. |
| `HITL_TIMEOUT` | `hitl.timeout` | A human-review SLA expired without resolution. |

#### `model_registry.*`

| Member | String value | Description |
|--------|-------------|-------------|
| `MODEL_REGISTRY_REGISTERED` | `model_registry.registered` | A model was registered in the governance registry. |
| `MODEL_REGISTRY_DEPRECATED` | `model_registry.deprecated` | A registered model was marked as deprecated. |
| `MODEL_REGISTRY_RETIRED` | `model_registry.retired` | A model was fully decommissioned. |

#### `explanation.*`

| Member | String value | Description |
|--------|-------------|-------------|
| `EXPLANATION_GENERATED` | `explanation.generated` | An explainability record was generated for a decision. |

#### `llm.cache.*`

| Member | String value | Description |
|--------|-------------|-------------|
| `CACHE_HIT` | `llm.cache.hit` | Semantic cache returned a cached result without a new model call. |
| `CACHE_MISS` | `llm.cache.miss` | Semantic cache lookup found no matching entry. |
| `CACHE_EVICTED` | `llm.cache.evicted` | A cache entry was evicted (TTL, LRU, or manual invalidation). |
| `CACHE_WRITTEN` | `llm.cache.written` | A new entry was written to the semantic cache. |

---

## Module-level functions

### `is_registered(event_type: str) -> bool`

Return `True` if `event_type` is a registered first-party `EventType` value.

```python
from spanforge.types import is_registered

is_registered("llm.trace.span.completed")  # True
is_registered("x.my-org.custom.event")      # False
```

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `event_type` | `str` | Event type string to look up. |

**Returns:** `bool`

---

### `namespace_of(event_type: str) -> str`

Return the `llm.<tool>` namespace of a registered event type.

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `event_type` | `str` | A registered event type string. |

**Returns:** `str` — the namespace prefix (e.g. `"llm.trace"`).

**Raises:** `EventTypeError` — if `event_type` does not match the expected pattern.

---

### `validate_custom(event_type: str) -> None`

Validate a custom (third-party) event type string.

Custom event types must use a reverse-domain prefix (e.g. `com.example.<…>`).

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `event_type` | `str` | Custom event type string to validate. |

**Raises:** `EventTypeError` — if `event_type` does not match the required pattern or claims a reserved `llm.*` namespace.

---

### `get_by_value(value: str) -> Optional[EventType]`

Look up an `EventType` by its string value.

Returns `None` instead of raising if the value is not found.

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `value` | `str` | Event type string value to look up. |

**Returns:** `EventType | None`

---

## Constants

### `EVENT_TYPE_PATTERN: str`

Regex pattern that all valid event type strings (registered and custom) must match:

```
^(?:llm\.[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*){1,3}|[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*){2,}\.[a-z][a-z0-9_]*)$
```
- `validate_custom()` — validate a custom reverse-domain event type string (e.g. `com.example.<…>`)
- `namespace_of()` — return the namespace prefix of a given event type string

---

## SDK Types — `spanforge.sdk._types`

Phase 11 introduces the following dataclass types used by `SFEnterpriseClient`
and `SFSecurityClient`.

### Enterprise types

| Type | Fields | Description |
|------|--------|-------------|
| `DataResidency` | `region: str`, `enforcement: str` | Data residency constraint for a tenant. |
| `IsolationScope` | `org_id: str`, `project_id: str`, `cross_project_read: bool` | Multi-tenant isolation boundary. |
| `TenantConfig` | `project_id: str`, `org_id: str`, `data_residency: DataResidency`, `isolation_scope: IsolationScope`, `created_at: str` | Full tenant configuration record. |
| `EncryptionConfig` | `encrypt_at_rest: bool`, `kms_provider: str`, `mtls_enabled: bool`, `fips_mode: bool` | Encryption subsystem configuration. |
| `AirGapConfig` | `offline: bool`, `self_hosted: bool`, `local_collector: str` | Air-gap / self-hosted deployment configuration. |
| `HealthEndpointResult` | `healthy: bool`, `checks: dict` | Result of enterprise health probe. |
| `EnterpriseStatusInfo` | `tenants: int`, `encryption_enabled: bool`, `airgap_enabled: bool`, `fips_mode: bool` | Enterprise subsystem status summary. |

### Security types

| Type | Fields | Description |
|------|--------|-------------|
| `DependencyVulnerability` | `package: str`, `version: str`, `severity: str`, `cve: str`, `description: str` | A single dependency vulnerability finding. |
| `StaticAnalysisFinding` | `file_path: str`, `line: int`, `rule_id: str`, `severity: str`, `message: str` | A single static analysis finding. |
| `ThreatModelEntry` | `threat: str`, `category: str`, `mitigation: str`, `severity: str` | A STRIDE threat model entry. |
| `SecurityScanResult` | `vulnerabilities: list[DependencyVulnerability]`, `static_findings: list[StaticAnalysisFinding]`, `scanned_at: str` | Combined dependency + static scan results. |
| `SecurityAuditResult` | `findings: list[dict]`, `timestamp: str` | OWASP audit result. |

### Import

```python
from spanforge.sdk._types import (
    DataResidency,
    IsolationScope,
    TenantConfig,
    EncryptionConfig,
    AirGapConfig,
    HealthEndpointResult,
    EnterpriseStatusInfo,
    DependencyVulnerability,
    StaticAnalysisFinding,
    ThreatModelEntry,
    SecurityScanResult,
    SecurityAuditResult,
)
```
