# spanforge.sdk.pii — PII Service Client

> **Module:** `spanforge.sdk.pii`  
> **Added in:** 2.0.3 (Phase 3: PII Service Hardening)

`spanforge.sdk.pii` provides the Phase 3 PII service client with full-text
scanning, payload anonymisation, pipeline action enforcement, GDPR/HIPAA/CCPA/
DPDP/PIPL compliance helpers, and training-data auditing.

The pre-built `sf_pii` singleton is available at the top level:

```python
from spanforge.sdk import sf_pii
```

---

## Presidio NLP backend

When the `presidio` optional extra is installed, spanforge automatically switches
from the built-in regex engine to a full NLP-powered Presidio analysis pipeline:

```bash
pip install "spanforge[presidio]"
python -m spacy download en_core_web_lg   # ~400 MB — required for NER
```

No code changes are needed. The backend is detected and activated at import time.

### Entity types covered

| Entity type | Label returned | Severity |
|-------------|---------------|----------|
| Credit card | `credit_card` | high |
| Cryptocurrency address | `crypto_address` | medium |
| Email address | `email` | medium |
| IBAN bank code | `iban` | high |
| IPv4 / IPv6 address | `ip_address` | low |
| Person name | `person_name` | medium |
| Phone number | `phone` | medium |
| US Social Security Number | `ssn` | high |
| UK NHS number | `uk_nhs` | high |
| US driver's license | `us_driver_license` | high |
| US passport | `us_passport` | high |
| India Aadhaar number | `aadhaar` | high |
| India PAN card | `pan` | high |
| Medical license number | `medical_license` | medium |
| UK National Insurance number | `uk_national_insurance` | high |

### Custom recognizers

The following entity types have custom `PatternRecognizer` rules registered on
top of the default Presidio English model to improve recall:

- **`PHONE_NUMBER`**: three format patterns — `+1-NXX-NXX-XXXX` (0.75), `(NXX) NXX-XXXX` (0.75), `NXX-NXX-XXXX` (0.60).
- **`IN_AADHAAR`**: `DDDD DDDD DDDD` (space- or hyphen-delimited 12-digit groups), confidence 0.85.
- **`IN_PAN`**: 5 uppercase letters + 4 digits + 1 uppercase letter, confidence 0.85.
- **`UK_NATIONAL_INSURANCE`**: standard NI number format, confidence 0.85.

### Post-filters

After Presidio analysis, spanforge applies additional filters to reduce false positives:

- **Lowercase `PERSON` suppression** — all-lowercase matches for `PERSON` are discarded; they typically indicate programming identifiers or function names, not human names.
- **IPv4 boundary check** — IPv4 matches are validated (4 octets, each 0–255) and must not be adjacent to other digit or dot characters. This prevents OID fragments like `1.101.3.4` inside longer strings from being flagged as IP addresses.

### GA accuracy gates (verified)

| Metric | Threshold | Result |
|--------|-----------|--------|
| False-positive rate | < 0.5 % | ✅ Passed (191-item clean corpus) |
| True-positive rate | ≥ 95 % | ✅ Passed (100 % = 25/25 samples) |

### Custom regex patterns alongside Presidio

The `extra_patterns` argument to `scan_text()` and `scan_payload()` is always
honoured, even when the Presidio backend is active. Results from Presidio and
from custom regex patterns are merged before returning.

---

## Quick example

```python
from spanforge.sdk import sf_pii

# Scan raw text
result = sf_pii.scan_text("Contact alice@example.com or call +1 555-867-5309")
print(result.detected)           # True
for entity in result.entities:
    print(entity.type, entity.start, entity.end, entity.score)

# Anonymise a payload dict
anon = sf_pii.anonymise({
    "user": "alice@example.com",
    "note": "SSN 078-05-1120",
})
print(anon.clean_payload)        # {"user": "<EMAIL_ADDRESS>", "note": "<US_SSN>"}
```

---

## `SFPIIClient`

```python
class SFPIIClient(SFServiceClient)
```

All methods are thread-safe. The class can be used standalone or via the
`sf_pii` singleton exported from `spanforge.sdk`.

### `scan_text()`

```python
def scan_text(
    self,
    text: str,
    *,
    language: str = "en",
) -> PIITextScanResult
```

Scan raw text for PII entities.  Uses Presidio when installed; falls back to
the regex-based `redact.scan_payload()` engine automatically.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `text` | *(required)* | The text string to scan. |
| `language` | `"en"` | ISO 639-1 language code (e.g. `"zh"` for Chinese). |

**Returns:** [`PIITextScanResult`](#piitextscanresult)

**Example:**

```python
result = sf_pii.scan_text("SSN: 078-05-1120", language="en")
assert result.detected
assert result.entities[0].type == "US_SSN"
```

---

### `anonymise()`

```python
def anonymise(
    self,
    payload: dict,
    *,
    language: str = "en",
    max_depth: int = 10,
) -> PIIAnonymisedResult
```

Recursively walk `payload`, scan every string value, and replace PII hits with
`<TYPE>` placeholders.  Returns the cleaned payload alongside a full
`redaction_manifest` recording each replacement.

**Returns:** [`PIIAnonymisedResult`](#piianonymisedresult)

**Example:**

```python
anon = sf_pii.anonymise({"email": "alice@example.com", "meta": {"ip": "203.0.113.4"}})
# anon.clean_payload == {"email": "<EMAIL_ADDRESS>", "meta": {"ip": "<IP_ADDRESS>"}}
# anon.redaction_manifest[0].field_path == "email"
# anon.redaction_manifest[0].original_hash  (SHA-256 of original — never raw PII)
```

---

### `scan_async()`

> **Added in:** 1.0.0

```python
async def scan_async(
    self,
    text: str,
    *,
    language: str = "en",
    score_threshold: float = 0.5,
) -> PIITextScanResult
```

Non-blocking async variant of `scan_text()`.  Delegates to the synchronous
method via `asyncio.get_event_loop().run_in_executor()` so it never blocks the
event loop.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `text` | *(required)* | The text string to scan. |
| `language` | `"en"` | ISO 639-1 language code. |
| `score_threshold` | `0.5` | Filter out entities below this confidence score. |

**Returns:** [`PIITextScanResult`](#piitextscanresult)

**Example:**

```python
import asyncio
from spanforge.sdk import sf_pii

result = asyncio.run(sf_pii.scan_async("alice@example.com"))
assert result.detected
assert result.entities[0].type == "EMAIL_ADDRESS"
```

---

### `scan_batch()`

```python
async def scan_batch(
    self,
    texts: list[str],
    *,
    language: str = "en",
) -> list[PIITextScanResult]
```

Scan multiple texts in parallel via `asyncio.gather`.  Falls back to sequential
execution when no running event loop is present.

**Example:**

```python
import asyncio

results = asyncio.run(sf_pii.scan_batch(["alice@example.com", "hello world"]))
assert results[0].detected
assert not results[1].detected
```

---

### `apply_pipeline_action()`

```python
def apply_pipeline_action(
    self,
    scan_result: PIITextScanResult,
    action: str = "flag",
    *,
    threshold: float = 0.85,
) -> PIIPipelineResult
```

Enforce a pipeline action based on a previous `scan_text()` result.

| Action | Behaviour |
|--------|-----------|
| `"flag"` | Return result with `detected` set; no text modification. |
| `"redact"` | Replace PII spans in `redacted_text`; `detected=True`. |
| `"block"` | Raise `SFPIIBlockedError`; never returns. |

The `threshold` parameter filters entities: only those with `score >= threshold`
are considered when deciding whether to fire the action (default `0.85`).
Sub-threshold entities are still included in `scan_result` for audit purposes.

**Returns:** [`PIIPipelineResult`](#piipipelineresult)

**Raises:** [`SFPIIBlockedError`](exceptions.md#sfpiiblockederror) (action `"block"` only)

**Example:**

```python
from spanforge.sdk._exceptions import SFPIIBlockedError

scan = sf_pii.scan_text("My SSN is 078-05-1120")
try:
    pipeline = sf_pii.apply_pipeline_action(scan, action="block", threshold=0.85)
except SFPIIBlockedError as exc:
    print("Blocked:", exc.entity_types)   # ["US_SSN"]
```

---

### `get_status()`

```python
def get_status(self) -> PIIServiceStatus
```

Return the current sf-pii service status.

**Returns:** [`PIIServiceStatus`](#piiservicestatus)

**Example:**

```python
status = sf_pii.get_status()
print(status.presidio_available)      # True / False
print(status.entity_types_loaded)     # ["EMAIL_ADDRESS", "PHONE_NUMBER", ...]
print(status.last_scan_at)            # "2026-04-17T12:00:00Z" or None
```

---

### `erase_subject()`

```python
def erase_subject(
    self,
    subject_id: str,
    project_id: str,
) -> ErasureReceipt
```

**GDPR Article 17 — Right to Erasure.**  Locate all audit events associated
with `subject_id` in `project_id` and issue erasure instructions to the
downstream store.

The `subject_id` is SHA-256 hashed in the returned `ErasureReceipt` —
the raw identifier is never persisted.

**Returns:** [`ErasureReceipt`](#erasurereceipt)

**Example:**

```python
receipt = sf_pii.erase_subject("user-12345", "proj-abc")
print(receipt.records_erased)         # 42
print(receipt.erased_at)              # "2026-04-17T12:00:00Z"
print(receipt.subject_id_hash)        # SHA-256 of "user-12345"
```

---

### `export_subject_data()`

```python
def export_subject_data(
    self,
    subject_id: str,
    project_id: str,
) -> DSARExport
```

**CCPA / GDPR — Data Subject Access Request (DSAR).**  Aggregate all events
referencing `subject_id` from the audit store for `project_id`.

**Returns:** [`DSARExport`](#dsarexport)

**Example:**

```python
export = sf_pii.export_subject_data("user-12345", "proj-abc")
print(export.total_records)
for record in export.records:
    print(record["event_type"], record["created_at"])
```

---

### `safe_harbor_deidentify()`

```python
def safe_harbor_deidentify(self, text: str) -> SafeHarborResult
```

**HIPAA Safe Harbor De-identification** per 45 CFR §164.514(b)(2).  Removes or
generalises all 18 PHI identifier categories from `text`:

| Transformation | Rule |
|---------------|------|
| Dates (except year) | Replaced with year only — `April 17 2026` → `2026` |
| Ages > 89 | Replaced with `"90+"` |
| ZIP codes | Truncated to first 3 digits — `90210` → `902XX` |
| Phone/fax | Removed |
| Email | Removed |
| SSN, MRN, account/certificate numbers | Removed |
| URLs, IP addresses, device identifiers | Removed |
| Names, geographic subdivisions, biometric data | Removed |

**Returns:** [`SafeHarborResult`](#safehaborresult)

**Example:**

```python
result = sf_pii.safe_harbor_deidentify(
    "Patient John Doe (DOB: 04/17/1932, MRN 0000-4321) lives at 902 Oak Lane, 90210."
)
print(result.deidentified_text)
# "Patient [NAME] (DOB: 1932, MRN [REMOVED]) lives at [ADDRESS], 902XX."
print(result.identifiers_removed)    # 5
```

---

### `audit_training_data()`

```python
def audit_training_data(
    self,
    dataset_path: str,
    *,
    max_records: int = 10_000,
    language: str = "en",
) -> TrainingDataPIIReport
```

**EU AI Act Article 10 — Training Data Governance.**  Scan each line of a
JSONL dataset file for PII and produce a prevalence report.  Lines that are not
valid JSON are counted as `malformed_lines` and skipped.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `dataset_path` | *(required)* | Path to a JSONL dataset file. |
| `max_records` | `10_000` | Stop after scanning this many records. |
| `language` | `"en"` | Language code forwarded to `scan_text`. |

**Returns:** [`TrainingDataPIIReport`](#trainingdatapiireport)

**Example:**

```python
report = sf_pii.audit_training_data("dataset/train.jsonl", max_records=5000)
print(f"{report.pii_record_count} / {report.total_records} records contain PII")
for entry in report.entity_breakdown:
    print(f"  {entry.entity_type}: {entry.count}")
```

---

### `get_pii_stats()`

```python
def get_pii_stats(self, project_id: str) -> list[PIIHeatMapEntry]
```

Aggregate PII detection statistics per entity type for `project_id`.  Powers
the SpanForge dashboard PII heat-map.

**Returns:** `list[`[`PIIHeatMapEntry`](#piiheatmapentry)`]`

**Example:**

```python
for entry in sf_pii.get_pii_stats("proj-abc"):
    print(entry.entity_type, entry.count, entry.last_seen_at)
```

---

## Return types

### `PIIEntityResult`

```python
@dataclass(frozen=True)
class PIIEntityResult:
    type: str
    start: int
    end: int
    score: float
```

A single detected PII entity.

| Field | Description |
|-------|-------------|
| `type` | Entity type label, e.g. `"EMAIL_ADDRESS"`, `"US_SSN"`, `"PIPL_NATIONAL_ID"`. |
| `start` | Byte offset of the match start in the input text. |
| `end` | Byte offset of the match end (exclusive). |
| `score` | Confidence score in `[0.0, 1.0]`. |

---

### `PIITextScanResult`

```python
@dataclass
class PIITextScanResult:
    detected: bool
    entities: list[PIIEntityResult]
    redacted_text: str
```

| Field | Description |
|-------|-------------|
| `detected` | `True` if at least one entity was found. |
| `entities` | All entities found (regardless of score threshold). |
| `redacted_text` | Input text with all detected PII replaced by `<TYPE>` placeholders. |

---

### `PIIRedactionManifestEntry`

```python
@dataclass(frozen=True)
class PIIRedactionManifestEntry:
    field_path: str
    entity_type: str
    original_hash: str
    replacement: str
```

One entry in an `anonymise()` redaction manifest.

| Field | Description |
|-------|-------------|
| `field_path` | Dot-delimited path to the field in the original payload (e.g. `"user.email"`). |
| `entity_type` | Entity type label. |
| `original_hash` | SHA-256 of the original field value. The raw value is never stored. |
| `replacement` | The `<TYPE>` placeholder that replaced the original. |

---

### `PIIAnonymisedResult`

```python
@dataclass
class PIIAnonymisedResult:
    clean_payload: dict
    redaction_manifest: list[PIIRedactionManifestEntry]
```

| Field | Description |
|-------|-------------|
| `clean_payload` | Deep copy of the input payload with all PII replaced. |
| `redaction_manifest` | Full list of replacements made. |

---

### `PIIPipelineResult`

```python
@dataclass
class PIIPipelineResult:
    action: str
    detected: bool
    entity_types: list[str]
    redacted_text: str | None
```

| Field | Description |
|-------|-------------|
| `action` | The action that was applied: `"flag"`, `"redact"`, or `"block"`. |
| `detected` | Whether PII above the threshold was present. |
| `entity_types` | List of distinct entity type labels that triggered the action. |
| `redacted_text` | Redacted text (only set when `action="redact"`). |

---

### `PIIServiceStatus`

```python
@dataclass
class PIIServiceStatus:
    status: str
    presidio_available: bool
    entity_types_loaded: list[str]
    last_scan_at: str | None
```

| Field | Description |
|-------|-------------|
| `status` | `"ok"` or `"degraded"`. |
| `presidio_available` | `True` when the Presidio engine is importable and healthy. |
| `entity_types_loaded` | Entity type labels currently registered in the active engine. |
| `last_scan_at` | ISO-8601 timestamp of the most recent scan, or `None`. |

---

### `ErasureReceipt`

```python
@dataclass
class ErasureReceipt:
    subject_id_hash: str
    project_id: str
    records_erased: int
    erased_at: str
```

| Field | Description |
|-------|-------------|
| `subject_id_hash` | SHA-256 hex digest of the subject ID (never the raw ID). |
| `project_id` | Project the erasure was scoped to. |
| `records_erased` | Number of audit records removed. |
| `erased_at` | ISO-8601 UTC timestamp of the erasure. |

---

### `DSARExport`

```python
@dataclass
class DSARExport:
    subject_id_hash: str
    project_id: str
    total_records: int
    records: list[dict]
    exported_at: str
```

| Field | Description |
|-------|-------------|
| `subject_id_hash` | SHA-256 hex digest of the subject ID. |
| `project_id` | Project the export was scoped to. |
| `total_records` | Number of records in the export. |
| `records` | List of serialisable event dicts. |
| `exported_at` | ISO-8601 UTC timestamp of the export. |

---

### `SafeHarborResult`

```python
@dataclass
class SafeHarborResult:
    deidentified_text: str
    identifiers_removed: int
```

| Field | Description |
|-------|-------------|
| `deidentified_text` | The input text after Safe Harbor de-identification. |
| `identifiers_removed` | Count of identifier instances removed or generalised. |

---

### `TrainingDataPIIReport`

```python
@dataclass
class TrainingDataPIIReport:
    dataset_path: str
    total_records: int
    pii_record_count: int
    malformed_lines: int
    entity_breakdown: list[PIIHeatMapEntry]
```

| Field | Description |
|-------|-------------|
| `dataset_path` | Path that was scanned. |
| `total_records` | Lines successfully parsed. |
| `pii_record_count` | Lines that contained at least one PII entity. |
| `malformed_lines` | Lines that could not be parsed as JSON (skipped). |
| `entity_breakdown` | Per-entity-type occurrence counts. |

---

### `PIIHeatMapEntry`

```python
@dataclass
class PIIHeatMapEntry:
    entity_type: str
    count: int
    last_seen_at: str | None
```

| Field | Description |
|-------|-------------|
| `entity_type` | Entity type label (e.g. `"EMAIL_ADDRESS"`). |
| `count` | Number of times this entity type was detected in the project. |
| `last_seen_at` | ISO-8601 timestamp of the most recent detection, or `None`. |

---

## Exceptions

| Exception | Description |
|-----------|-------------|
| `SFPIIError` | Base class for all sf-pii SDK errors. |
| `SFPIIBlockedError(entity_types, count)` | Raised by `apply_pipeline_action(action="block")`. `entity_types` lists the types that triggered the block. |
| `SFPIIDPDPConsentMissingError(subject_id_hash, entity_types)` | Raised when a DPDP-regulated entity is detected but no valid consent record exists for the current purpose. `subject_id_hash` is a SHA-256 digest. |
| `SFPIIScanError` | Wraps unexpected engine failures. |

See [exceptions reference](exceptions.md#sfpii-exceptions) for full details.

---

## PIPL entity types

China PIPL-specific entity types registered in `presidio_backend.py`:

| Type | Pattern |
|------|---------|
| `PIPL_NATIONAL_ID` | Chinese national ID — 17 digits followed by a digit or `X` |
| `PIPL_MOBILE` | Chinese mobile — `1[3-9]` followed by 9 digits |
| `PIPL_BANK_CARD` | Chinese bank card — 16–19 digit card numbers |

These types are flagged as `pipl_sensitive` for cross-border transfer controls.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SPANFORGE_SF_PII_ENDPOINT` | *(none)* | Remote sf-pii service URL.  When set, `SFPIIClient` forwards scans to the service; falls back to local engine on network error. |
| `SPANFORGE_PII_ACTION` | `"flag"` | Default pipeline action (`"flag"` / `"redact"` / `"block"`). |
| `SPANFORGE_PII_THRESHOLD` | `0.85` | Default confidence threshold for pipeline action enforcement. |
| `SPANFORGE_PII_LANGUAGE` | `"en"` | Default language code forwarded to scan calls. |
| `SPANFORGE_PII_MAX_DEPTH` | `10` | Maximum recursion depth for `anonymise()`. |

---

## See also

- [Configuration reference — PII service settings](../configuration.md#pii-service-settings)
- [User Guide — PII Redaction](../user_guide/redaction.md)
- [User Guide — Compliance](../user_guide/compliance.md)
- [Runbook — PII Scanning](../runbook.md#5-pii-scanning)
- [`spanforge.redact`](redact.md) — low-level PII detection and field-level redaction
- [`spanforge.sdk.secrets`](secrets.md) — secrets scanning
- [Exceptions reference](exceptions.md#sfpii-exceptions)
