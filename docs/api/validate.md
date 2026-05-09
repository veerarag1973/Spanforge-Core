# spanforge.validate

JSON Schema validation for `Event` envelopes.

Validates `Event` instances against the published JSON Schema. Schema version
is selected automatically from the event's `schema_version` field:

- `"1.0"` → `schemas/v1.0/schema.json`
- `"2.0"` (default) → `schemas/v2.0/schema.json`

When the optional `jsonschema` package is installed, full Draft 2020-12
validation is performed. Otherwise a stdlib-only structural check covers all
required fields, types, and regex patterns.

**Install for full validation:**

```bash
pip install "spanforge[jsonschema]"
```

---

## Module-level functions

### `validate_event(event: Event) -> None`

Validate `event` against the published JSON Schema.

The schema version is read from `event.schema_version` and the matching schema
file is selected automatically (RFC §15.5).

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `event` | `Event` | The `Event` instance to validate. |

**Raises:**

- `SchemaValidationError` — if the event does not conform to the envelope schema.
- `FileNotFoundError` — if the matching schema file is missing from the distribution.
- `TypeError` — if `event` is not an `Event` instance.

**Example:**

```python
from spanforge import Event, EventType
from spanforge.validate import validate_event

event = Event(
    event_type=EventType.TRACE_SPAN_COMPLETED,
    source="llm-trace@0.3.1",
    payload={"span_name": "run", "status": "ok"},
)
validate_event(event)  # passes silently
```

---

### `load_schema(version: Optional[str] = None) -> Dict[str, Any]`

Load and cache a JSON Schema from disk by version.

The schema is loaded once per version key and cached in memory. If `version`
is `None`, the current default (`"2.0"`) is used. Unknown versions raise
`ValueError`.

**Args:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `version` | `str \| None` | `None` | Schema version string, e.g. `"1.0"` or `"2.0"`. Defaults to `"2.0"`. |

**Returns:** `Dict[str, Any]` — parsed JSON Schema as a plain Python dict.

**Raises:**

- `FileNotFoundError` — if the schema file cannot be found relative to the package root.
- `ValueError` — if an unknown schema version is requested.

**Example:**

```python
from spanforge.validate import load_schema

schema_v2 = load_schema()        # loads schemas/v2.0/schema.json
schema_v1 = load_schema("1.0")   # loads schemas/v1.0/schema.json
```

---

## Enforcement Modes (1.0.1)

### `EnforcementMode`

Four validation enforcement levels:

| Member | Behaviour |
|--------|-----------|
| `STRICT` | Raise `ValidationError` on the first violation. |
| `LENIENT` | Collect all violations, then raise at the end. |
| `WARN` | Log every violation at `WARNING` level, never raise. |
| `CORRECT` | Apply a correction pass, return corrected doc without raising. |

### `ValidationResult`

Dataclass returned by `enforce_event()`:

| Field | Type | Description |
|-------|------|-------------|
| `valid` | `bool` | `True` when there are no violations. |
| `mode` | `EnforcementMode` | The enforcement mode that was applied. |
| `violations` | `list[str]` | Violation messages (empty when valid). |
| `corrected_doc` | `dict \| None` | Corrected document — only set in `CORRECT` mode. |

### `enforce_event(event, mode=EnforcementMode.STRICT) -> ValidationResult`

Validate and enforce an event according to the chosen mode.

```python
from spanforge.validate import enforce_event, EnforcementMode

result = enforce_event(event, mode=EnforcementMode.WARN)
if result.violations:
    print(result.violations)
```

### `correct_event(doc: dict) -> dict`

Correction pass that:
- Strips unknown top-level keys.
- Removes `None`-valued optional fields (`trace_id`, `span_id`, `tags`, `checksum`, `signature`).
- Normalises `schema_version` to the current default when the value is unrecognised.

Returns a new dict; does not mutate the input.

---

## HMAC Signing (1.0.1)

### `sign_event_hmac(event: Event, key: str) -> Event`

Sign an event with HMAC-SHA256. Returns a new `Event` with:

```
signature = "hmac-sha256:<64-hex-digest>"
```

The digest is computed over the canonical JSON representation of the event payload (sorted keys, no whitespace). Raises `ValueError` for an empty `key`.

```python
from spanforge.validate import sign_event_hmac

signed = sign_event_hmac(event, key="my-secret-key")
```

---

## Training Data Compliance Scanner

> **Current API (v1.0.1+):** `scan_dataset_compliance()` in `spanforge.sdk.dataset_scanner` — EU AI Act Article 10 file-level scanner with HMAC-signed reports. See [compliance API reference](compliance.md) for full documentation.

### Legacy row-level API (v1.0.0)

> **Deprecated.** The row-level `scan_dataset()` API below is preserved for backwards compatibility. New integrations should use `scan_dataset_compliance()` instead.

### `scan_dataset(rows, *, check_pii_field_names=True, check_pii_values=True, required_fields=None) -> DatasetScanReport`

Scan a list of record dicts (e.g. from a JSONL training dataset) for compliance issues:

- **PII field names** — flags fields whose names match known PII patterns (email, phone, ssn, passport, ip_address, biometric, gps, lat, lon, dob, national_id, driver_license, and more).
- **PII values** — flags field values that match email address, US phone number, or SSN patterns.
- **Required field violations** — flags records missing any field listed in `required_fields`.

```python
from spanforge.validate import scan_dataset

rows = [
    {"prompt": "Hello", "email": "user@example.com"},
    {"prompt": "World"},
]
report = scan_dataset(rows, required_fields=["prompt", "response"])
print(report.total_findings)  # 2: pii_field_name + schema_violation
```

### `DatasetScanFinding`

| Field | Type | Description |
|-------|------|-------------|
| `row` | `int` | 1-based row index. |
| `field` | `str` | Affected field name. |
| `issue_type` | `str` | `pii_field_name`, `pii_value`, `schema_violation`, or `parse_error`. |
| `detail` | `str` | Human-readable explanation. |

### `DatasetScanReport`

| Field | Type | Description |
|-------|------|-------------|
| `total_rows` | `int` | Total records scanned. |
| `total_findings` | `int` | Total issues found. |
| `clean_rows` | `int` | Rows with no findings. |
| `pii_hits` | `int` | PII field-name or value hits. |
| `schema_violations` | `int` | Required-field violations. |
| `parse_errors` | `int` | Records that could not be parsed. |
| `findings` | `list[DatasetScanFinding]` | Full finding list. |

---

## Model Response Validation — `spanforge.sdk.validate` (1.0.1)

> **Distinct from `spanforge.validate`** (event-envelope validation above). This module validates **model responses** on the hot path, running four ordered enforcement mechanisms before the response reaches the caller.

```python
from spanforge.sdk import sf_validate          # singleton
from spanforge.sdk.validate import (
    SFValidateClient,
    ValidationResult,
    Violation,
    ValidateStatusInfo,
)
```

### `SFValidateClient`

```python
SFValidateClient(config: SFClientConfig, service_name: str = "sf-validate")
```

Four enforcement mechanisms run in order on every `validate()` call:

| # | Mechanism | Trigger | Effect |
|---|-----------|---------|--------|
| 1 | **Schema check** | `schema` param set | JSON Schema dict (jsonschema / structural fallback) or regex pattern; adds `"schema"` violation |
| 2 | **Confidence threshold** | `confidence_threshold` param | Rejects `confidence_score < threshold` (default 0.7); adds `"confidence"` violation |
| 3 | **Content policy** | always | `sf_pii.scan_text()` → `"pii"` violations; `SecretsScanner` → `"secret"` violation + `auto_blocked=True` |
| 4 | **Multi-pass correction** | `correction_fn` param + violations present | Calls `correction_fn(response, violations)` up to `max_correction_passes` (default 2) times |

### `validate(response, *, schema=None, confidence_threshold=0.7, correction_fn=None, max_correction_passes=2, agent_id="", trace_id="") -> ValidationResult`

Run all four enforcement mechanisms in order. **Never raises on content violations** — always returns `ValidationResult`.

**Args:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `response` | `str \| dict \| Any` | — | The model response to validate. |
| `schema` | `dict \| str \| None` | `None` | JSON Schema dict, or regex pattern string. `None` skips the schema check. |
| `confidence_threshold` | `float` | `0.7` | Minimum acceptable confidence score. |
| `correction_fn` | `Callable[[Any, list[Violation]], Any] \| None` | `None` | Called with `(response, violations)` to produce a corrected response. |
| `max_correction_passes` | `int` | `2` | Maximum correction iterations. |
| `agent_id` | `str` | `""` | Agent identifier — included in the audit record. |
| `trace_id` | `str` | `""` | Trace identifier — included in the audit record. |

**Returns:** `ValidationResult`

**Example:**

```python
import re
from spanforge.sdk import sf_validate

# Schema check (regex)
result = sf_validate.validate(
    response="Order confirmed for customer@example.com",
    schema=r"^Order confirmed",
    agent_id="order-agent",
    trace_id="abc123",
)
print(result.passed)          # True or False
print(result.violations)      # list[Violation]
print(result.hmac_signature)  # HMAC of the audit record

# Multi-pass correction
def fix(resp, viols):
    return resp.replace("badword", "***")

result = sf_validate.validate(
    response="Please say badword now",
    correction_fn=fix,
)
print(result.correction_passes)    # 1
print(result.corrected_response)   # "Please say *** now"
```

### `get_status() -> ValidateStatusInfo`

Return a snapshot of health and configuration:

```python
info = sf_validate.get_status()
print(info.total_calls)            # total validate() calls
print(info.total_passed)           # calls where passed=True
print(info.jsonschema_available)   # True if jsonschema installed
```

---

### `ValidationResult` dataclass

Returned by `SFValidateClient.validate()`.

| Field | Type | Description |
|-------|------|-------------|
| `passed` | `bool` | `True` when no violations remain after all mechanisms. |
| `violations` | `list[Violation]` | All collected violations (empty when `passed=True`). |
| `corrected_response` | `Any \| None` | Final corrected response after correction passes, or `None`. |
| `correction_passes` | `int` | Number of correction iterations performed. |
| `hmac_signature` | `str` | HMAC signature of the audit record (from `sf_audit`). |
| `audit_id` | `str` | Record ID of the appended audit entry. |
| `duration_ms` | `float` | Wall-clock time of the full `validate()` call in milliseconds. |
| `auto_blocked` | `bool` | `True` when a secret hit was detected. |

**`to_dict() -> dict`** — returns all fields as a plain dict.

---

### `Violation` dataclass

| Field | Type | Description |
|-------|------|-------------|
| `type` | `str` | Violation category: `"schema"`, `"confidence"`, `"pii"`, or `"secret"`. |
| `field` | `str` | Dotted field path or `"response"` for top-level violations. |
| `message` | `str` | Human-readable description. |
| `severity` | `str` | One of `"low"`, `"medium"`, `"high"`, `"critical"`. |

`Violation.__post_init__()` raises `ValueError` for unknown severity values.

**`to_dict() -> dict`** — returns all fields as a plain dict.

---

### `ValidateStatusInfo` dataclass

| Field | Type | Description |
|-------|------|-------------|
| `service` | `str` | Always `"sf-validate"`. |
| `local_mode` | `bool` | `True` when running without a remote endpoint. |
| `total_calls` | `int` | Total `validate()` invocations. |
| `total_passed` | `int` | Calls where `passed=True`. |
| `total_violations_raised` | `int` | Cumulative violation count across all calls. |
| `total_correction_passes` | `int` | Cumulative correction passes performed. |
| `jsonschema_available` | `bool` | Whether the optional `jsonschema` package is installed. |

---

### Audit schema keys

| Schema key | Emitted when |
|------------|--------------|
| `spanforge.validate.v1` | Every `validate()` call — includes `response_hash` (SHA-256), `violation_types`, `violation_count`, `passed`, `correction_passes`, `auto_blocked`. |
| `spanforge.validate.correction.v1` | Each correction pass — lightweight cost-attribution record. |

---

## CLI — Dataset Scanner

```bash
# Scan a JSONL training dataset (exits 1 if any Article 10 clause fails)
spanforge validate --dataset training.jsonl

# Machine-readable JSON output
spanforge validate --dataset training.jsonl --output json

# PDF report (requires reportlab)
spanforge validate --dataset training.jsonl --output pdf
```

---



| Field | Rule |
|-------|------|
| `schema_version` | Required. Must be one of `"1.0"` or `"2.0"`. |
| `event_id` | Required. Must be a valid 26-character ULID. |
| `event_type` | Required. Must be either a registered first-party RFC event type or a valid reverse-domain custom type outside `llm.*`. |
| `timestamp` | Required. Must be UTC ISO-8601 ending in `Z`. |
| `source` | Required. Must match `tool-name@semver` pattern. |
| `payload` | Required. Must be a non-empty object. |
| `trace_id` | Optional. Must be exactly 32 lowercase hex characters. |
| `span_id` | Optional. Must be exactly 16 lowercase hex characters. |
| `parent_span_id` | Optional. Must be exactly 16 lowercase hex characters. |
| `org_id`, `team_id`, `actor_id`, `session_id` | Optional. Must be non-empty strings. |
| `checksum` | Optional. Must match `sha256:<64-char lowercase hex>` format. |
| `signature` | Optional. Must match `hmac-sha256:<64-char lowercase hex>` format. |
| `prev_id` | Optional. Must be a valid 26-character ULID. |
| `tags` | Optional. Must be an object with non-empty string keys and values. |
