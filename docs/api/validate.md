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

## Training Data Compliance Scanner (1.0.1)

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

## CLI — Dataset Scanner

```bash
# Scan a JSONL training dataset
spanforge validate --dataset training.jsonl

# CI gate: exit 1 if any findings
spanforge validate --dataset training.jsonl --fail-on-violations

# Require specific fields in every record
spanforge validate --dataset training.jsonl --required-fields prompt,response

# Machine-readable JSON output
spanforge validate --dataset training.jsonl --format json
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
