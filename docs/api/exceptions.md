# spanforge.exceptions

Typed exception hierarchy for spanforge.

All exceptions inherit from `LLMSchemaError`, allowing callers to catch the
entire family with a single `except LLMSchemaError`.

**Security:** HMAC keys and PII-tagged content are **never** embedded in exception
messages or `__cause__` chains.

---

## Exception hierarchy

```
LLMSchemaError
├── SchemaValidationError
├── ULIDError
├── SerializationError
├── DeserializationError
├── EventTypeError
├── SigningError
├── VerificationError
└── ExportError
```

---

## `LLMSchemaError`

```python
class LLMSchemaError(Exception)
```

Base class for all spanforge exceptions.

Write a single broad guard:

```python
try:
    ...
except LLMSchemaError as exc:
    logger.error("spanforge error: %s", exc)
```

---

## `SchemaValidationError`

```python
class SchemaValidationError(LLMSchemaError)
SchemaValidationError(field: str, received: object, reason: str)
```

Raised when an `Event` fails field-level validation.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `field` | `str` | The dotted field path that failed (e.g. `"event_id"`). |
| `received` | `Any` | The actual value that was provided (redacted if sensitive). |
| `reason` | `str` | Human-readable explanation of the constraint violated. |

**Example:**

```python
try:
    event.validate()
except SchemaValidationError as exc:
    logger.error("field=%s reason=%s", exc.field, exc.reason)
```

---

## `ULIDError`

```python
class ULIDError(LLMSchemaError)
ULIDError(detail: str)
```

Raised when ULID generation or parsing fails.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `detail` | `str` | Human-readable description of the failure. |

---

## `SerializationError`

```python
class SerializationError(LLMSchemaError)
SerializationError(event_id: str, reason: str)
```

Raised when an `Event` cannot be serialised to JSON.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `event_id` | `str` | The ULID of the event that failed (safe to log). |
| `reason` | `str` | Human-readable description of the failure. |

---

## `DeserializationError`

```python
class DeserializationError(LLMSchemaError)
DeserializationError(reason: str, source_hint: str = "<unknown>")
```

Raised when a JSON blob cannot be deserialised into an `Event`.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `reason` | `str` | Human-readable description of the failure. |
| `source_hint` | `str` | A short, non-PII hint about the source (e.g. filename). |

---

## `EventTypeError`

```python
class EventTypeError(LLMSchemaError)
EventTypeError(event_type: str, reason: str)
```

Raised when an unknown or malformed event type string is encountered.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `event_type` | `str` | The offending event type string. |
| `reason` | `str` | Human-readable description of the failure. |

---

## `SigningError`

```python
class SigningError(LLMSchemaError)
SigningError(reason: str)
```

Raised when HMAC event signing fails.

The `org_secret` value is **never** included in the message.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `reason` | `str` | Human-readable description of why signing failed. |

---

## `VerificationError`

```python
class VerificationError(LLMSchemaError)
VerificationError(event_id: str)
```

Raised by `assert_verified()` when an event fails cryptographic verification.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `event_id` | `str` | The ULID of the event that failed (safe to log). |

---

## `ExportError`

```python
class ExportError(LLMSchemaError)
ExportError(backend: str, reason: str, event_id: str = "")
```

Raised when exporting events to an external backend fails.

HMAC secrets and PII-tagged payloads are **never** embedded in the message.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `backend` | `str` | Short identifier for the backend (e.g. `"otlp"`, `"webhook"`, `"jsonl"`). |
| `reason` | `str` | Human-readable description of the failure. |
| `event_id` | `str` | The ULID of the failed event, or `""` for batch failures. |

**Example:**

```python
try:
    await exporter.export(event)
except ExportError as exc:
    logger.error("backend=%s reason=%s", exc.backend, exc.reason)
```

---

## `SchemaVersionError`

```python
class SchemaVersionError(LLMSchemaError)
SchemaVersionError(version: str)
```

Raised when an event carries an unsupported `schema_version` value.

v2.0 consumers MUST accept `"1.0"` and `"2.0"` and MUST raise this error for
any other value (RFC-0001 §15.5).

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `version` | `str` | The unsupported schema version string that was encountered. |

**Example:**

```python
try:
    consumer.ingest(event)
except SchemaVersionError as exc:
    logger.warning("Skipping event with unknown version %s", exc.version)
```

---

## `SigningError`

```python
class SigningError(LLMSchemaError)
SigningError(reason: str)
```

Raised when HMAC event signing fails.

The `org_secret` value is **never** included in the message.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `reason` | `str` | Human-readable description of why signing failed. |

---

## `VerificationError`

```python
class VerificationError(LLMSchemaError)
VerificationError(event_id: str)
```

Raised by `assert_verified()` when an event fails cryptographic verification.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `event_id` | `str` | The ULID of the event that failed (safe to log). |

---

## `ExportError`

```python
class ExportError(LLMSchemaError)
ExportError(backend: str, reason: str, event_id: str = "")
```

Raised when exporting events to an external backend fails.

HMAC secrets and PII-tagged payloads are **never** embedded in the message.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `backend` | `str` | Short identifier for the backend (e.g. `"otlp"`, `"webhook"`, `"jsonl"`). |
| `reason` | `str` | Human-readable description of the failure. |
| `event_id` | `str` | The ULID of the failed event, or `""` for batch failures. |

**Example:**

```python
try:
    await exporter.export(event)
except ExportError as exc:
    logger.error("backend=%s reason=%s", exc.backend, exc.reason)
```

---

## SDK exceptions — `spanforge.sdk._exceptions`

The SDK uses its own exception hierarchy rooted at `SFError`.  All SDK
exceptions are safe to log: they never embed raw PII, HMAC keys, or secret
values.

### Hierarchy

```
SFError
├── SFAuthError
│   ├── SFTokenInvalidError
│   ├── SFScopeError
│   ├── SFIPDeniedError
│   ├── SFMFARequiredError
│   └── SFBruteForceLockedError
├── SFQuotaExceededError
├── SFRateLimitError
├── SFServiceUnavailableError
├── SFStartupError
├── SFKeyFormatError
├── SFPIIError                         # Phase 3
│   ├── SFPIIScanError
│   ├── SFPIINotRedactedError
│   ├── SFPIIPolicyError
│   ├── SFPIIBlockedError              # pipeline action="block"
│   └── SFPIIDPDPConsentMissingError   # DPDP consent gate
├── SFSecretsError
│   ├── SFSecretsBlockedError
│   └── SFSecretsScanError
├── SFAuditError                       # Phase 4
│   ├── SFAuditSchemaError
│   ├── SFAuditAppendError
│   └── SFAuditQueryError
├── SFCECError                         # Phase 5
│   ├── SFCECBuildError
│   ├── SFCECVerifyError
│   └── SFCECExportError
├── SFObserveError                     # Phase 6
│   ├── SFObserveExportError
│   ├── SFObserveEmitError
│   └── SFObserveAnnotationError
├── SFAlertError                       # Phase 7
│   ├── SFAlertPublishError
│   ├── SFAlertRateLimitedError
│   └── SFAlertQueueFullError
├── SFGateError                        # Phase 8
│   ├── SFGateEvaluationError
│   ├── SFGatePipelineError
│   ├── SFGateTrustFailedError
│   └── SFGateSchemaError
├── SFConfigError                      # Phase 9
│   └── SFConfigValidationError
├── SFTrustError                       # Phase 10
│   ├── SFTrustComputeError
│   ├── SFTrustGateFailedError
│   └── SFPipelineError
├── SFEnterpriseError                  # Phase 11
│   ├── SFIsolationError
│   ├── SFDataResidencyError
│   ├── SFEncryptionError
│   ├── SFFIPSError
│   └── SFAirGapError
└── SFSecurityScanError                # Phase 11
    └── SFSecretsInLogsError
```

---

### `SFPIIError` {#sfpii-exceptions}

```python
class SFPIIError(SFError)
```

Base class for all sf-pii SDK errors.  Catch this to handle any PII-related
failure in a single `except` clause.

---

### `SFPIIBlockedError`

```python
class SFPIIBlockedError(SFPIIError)
SFPIIBlockedError(entity_types: list[str], count: int)
```

Raised by `SFPIIClient.apply_pipeline_action(action="block")` when PII above
the confidence threshold is detected.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `entity_types` | `list[str]` | Entity type labels that triggered the block (e.g. `["US_SSN", "EMAIL_ADDRESS"]`). |
| `count` | `int` | Number of entities that exceeded the threshold. |

**HTTP status equivalent:** `422 Unprocessable Entity` (`PII_DETECTED`).

**Security:** Entity type *labels* are included; matched text is **never** embedded.

**Example:**

```python
from spanforge.sdk import sf_pii
from spanforge.sdk._exceptions import SFPIIBlockedError

scan = sf_pii.scan_text("SSN: 078-05-1120")
try:
    sf_pii.apply_pipeline_action(scan, action="block")
except SFPIIBlockedError as exc:
    # exc.entity_types == ["US_SSN"]
    # exc.count == 1
    return http_422("PII_DETECTED", exc.entity_types)
```

---

### `SFPIIDPDPConsentMissingError`

```python
class SFPIIDPDPConsentMissingError(SFPIIError)
SFPIIDPDPConsentMissingError(subject_id_hash: str, entity_types: list[str])
```

Raised when a DPDP-regulated entity is detected but no valid consent record
exists for the current processing purpose.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `subject_id_hash` | `str` | SHA-256 hex digest of the subject identifier (never the raw ID). |
| `entity_types` | `list[str]` | DPDP entity types that triggered the consent check. |

**Security:** The raw subject ID is **never** stored in this exception —
only its SHA-256 hash.

**Example:**

```python
from spanforge.sdk._exceptions import SFPIIDPDPConsentMissingError

try:
    result = sf_pii.scan_text(user_text)
except SFPIIDPDPConsentMissingError as exc:
    logger.warning(
        "DPDP consent missing for subject=%s types=%s",
        exc.subject_id_hash,
        exc.entity_types,
    )
```

---

### `SFPIIScanError`

```python
class SFPIIScanError(SFPIIError)
SFPIIScanError(reason: str)
```

Wraps unexpected failures from the underlying PII scan engine (Presidio or
regex fallback).

---

### `SFPIINotRedactedError`

```python
class SFPIINotRedactedError(SFPIIError)
SFPIINotRedactedError(field_path: str, pii_type: str)
```

Raised by `assert_redacted()` when an event contains an unredacted
`Redactable` field.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `field_path` | `str` | Dotted path to the unredacted field. |
| `pii_type` | `str` | The PII type label of the unredacted value. |

---

### `SFPIIPolicyError`

```python
class SFPIIPolicyError(SFPIIError)
SFPIIPolicyError(reason: str)
```

Raised when a `RedactionPolicy` or pipeline-action configuration is invalid
(e.g. unknown action string).

---

## Alert exceptions — Phase 7 {#sf-alert-exceptions}

### `SFAlertError`

```python
class SFAlertError(SFError)
```

Base class for all sf-alert SDK errors. Catch this to handle any alert
routing failure in a single `except` clause.

---

### `SFAlertPublishError`

```python
class SFAlertPublishError(SFAlertError)
SFAlertPublishError(reason: str)
```

Raised when an alert cannot be published to one or more configured sinks.

---

### `SFAlertRateLimitedError`

```python
class SFAlertRateLimitedError(SFAlertError)
SFAlertRateLimitedError(reason: str)
```

Raised when an alert is rejected due to rate-limiting.

---

### `SFAlertQueueFullError`

```python
class SFAlertQueueFullError(SFAlertError)
SFAlertQueueFullError(reason: str)
```

Raised when the alert queue has reached capacity.

---

## Audit exceptions — Phase 4 {#sf-audit-exceptions}

### `SFAuditAppendError`

```python
class SFAuditAppendError(SFAuditError)
SFAuditAppendError(reason: str)
```

Raised when appending to the audit chain fails (e.g. file I/O, HMAC error).

---

### `SFAuditQueryError`

```python
class SFAuditQueryError(SFAuditError)
SFAuditQueryError(reason: str)
```

Raised when an audit chain query fails (e.g. invalid filter, SQLite error).

---

## Gate exceptions — Phase 8 {#sf-gate-exceptions}

### `SFGateError`

```python
class SFGateError(SFError)
```

Base class for all CI/CD Gate Pipeline service errors. Catch this to handle
any sf-gate failure in a single `except` clause.

---

### `SFGateEvaluationError`

```python
class SFGateEvaluationError(SFGateError)
SFGateEvaluationError(detail: str)
```

Raised when a `gate.evaluate()` call fails (e.g. invalid gate_id, executor
crash, or artifact write failure).

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `detail` | `str` | Human-readable description of the failure. |

---

### `SFGatePipelineError`

```python
class SFGatePipelineError(SFGateError)
SFGatePipelineError(failed_gates: list[str], detail: str = "")
```

Raised when a gate pipeline run fails with one or more blocking gates.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `failed_gates` | `list[str]` | Gate IDs that produced FAIL verdicts. |

---

### `SFGateTrustFailedError`

```python
class SFGateTrustFailedError(SFGateError)
SFGateTrustFailedError(failures: list[str])
```

Raised when the trust gate fails in strict mode.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `failures` | `list[str]` | Human-readable failure reasons. |

---

### `SFGateSchemaError`

```python
class SFGateSchemaError(SFGateError)
SFGateSchemaError(detail: str)
```

Raised when a YAML gate configuration is invalid or contains unknown gate types.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `detail` | `str` | Human-readable description of the schema violation. |

---

## Config exceptions — Phase 9 {#sf-config-exceptions}

### `SFConfigError`

```python
class SFConfigError(SFError)
SFConfigError(detail: str)
```

Raised when a `.halluccheck.toml` config file cannot be read or parsed.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `detail` | `str` | Human-readable description of the problem. |

---

### `SFConfigValidationError`

```python
class SFConfigValidationError(SFConfigError)
SFConfigValidationError(errors: list[str])
```

Raised when one or more config schema validation errors are found.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `errors` | `list[str]` | List of validation error descriptions. |

---

## T.R.U.S.T. exceptions — Phase 10 {#sf-trust-exceptions}

### `SFTrustError`

```python
class SFTrustError(SFError)
```

Base class for all T.R.U.S.T. scorecard errors.

---

### `SFTrustComputeError`

```python
class SFTrustComputeError(SFTrustError)
SFTrustComputeError(detail: str)
```

Raised when dimension score calculation fails due to insufficient data.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `detail` | `str` | Human-readable description of the failure. |

---

### `SFTrustGateFailedError`

```python
class SFTrustGateFailedError(SFTrustError)
SFTrustGateFailedError(failures: list[str])
```

Raised when the composite trust gate evaluation fails in strict mode.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `failures` | `list[str]` | Human-readable failure reasons. |

---

### `SFPipelineError`

```python
class SFPipelineError(SFTrustError)
SFPipelineError(pipeline: str, detail: str)
```

Raised when a HallucCheck pipeline integration call fails.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `pipeline` | `str` | Pipeline name that failed. |
| `detail` | `str` | Human-readable description. |

---

## Enterprise exceptions — Phase 11 {#sf-enterprise-exceptions}

### `SFEnterpriseError`

```python
class SFEnterpriseError(SFError)
```

Base class for all enterprise SDK errors. Catch this to handle any
multi-tenancy, encryption, or air-gap failure in a single `except` clause.

---

### `SFIsolationError`

```python
class SFIsolationError(SFEnterpriseError)
SFIsolationError(reason: str)
```

Raised when tenant isolation is violated — e.g. cross-tenant data access
or missing isolation scope.

---

### `SFDataResidencyError`

```python
class SFDataResidencyError(SFEnterpriseError)
SFDataResidencyError(reason: str)
```

Raised when a data residency constraint is violated — e.g. writing data to
a non-compliant region.

---

### `SFEncryptionError`

```python
class SFEncryptionError(SFEnterpriseError)
SFEncryptionError(reason: str)
```

Raised when field-level encryption or decryption fails.

---

### `SFFIPSError`

```python
class SFFIPSError(SFEnterpriseError)
SFFIPSError(reason: str)
```

Raised when a FIPS 140-2 compliance check fails — e.g. non-FIPS algorithm
requested in a FIPS-enforced environment.

---

### `SFAirGapError`

```python
class SFAirGapError(SFEnterpriseError)
SFAirGapError(reason: str)
```

Raised when an operation requires network access but air-gap mode is enabled.

---

### `SFSecurityScanError`

```python
class SFSecurityScanError(SFError)
SFSecurityScanError(reason: str)
```

Raised when a security scan (dependency, static analysis, or OWASP audit)
encounters an unexpected failure.

---

### `SFSecretsInLogsError`

```python
class SFSecretsInLogsError(SFSecurityScanError)
SFSecretsInLogsError(reason: str)
```

Raised when secrets are detected in log output during a security audit.

---

## See also

- [spanforge.sdk.pii](pii.md) — full PII service client reference
- [spanforge.sdk.secrets](secrets.md) — secrets scanning exceptions
- [spanforge.sdk.audit](audit.md) — audit service exceptions (Phase 4)
- [spanforge.sdk.cec](cec.md) — compliance evidence chain exceptions (Phase 5)
- [spanforge.sdk.observe](observe.md) — observability SDK exceptions (Phase 6)
- [spanforge.sdk.alert](alert.md) — alert routing exceptions (Phase 7)
- [spanforge.sdk.gate](gate.md) — CI/CD gate pipeline exceptions (Phase 8)
- [spanforge.sdk.config](config.md) — configuration exceptions (Phase 9)
- [spanforge.sdk.trust](trust.md) — T.R.U.S.T. scorecard exceptions (Phase 10)
- [spanforge.sdk.enterprise](enterprise.md) — enterprise multi-tenancy exceptions (Phase 11)
- [spanforge.sdk.security](security.md) — supply-chain security exceptions (Phase 11)
