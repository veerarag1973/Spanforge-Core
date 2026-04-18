# spanforge.sdk.cec — Compliance Evidence Chain Client

> **Module:** `spanforge.sdk.cec`  
> **Added in:** 2.0.4 (Phase 5: Compliance Evidence Chain)

`spanforge.sdk.cec` provides the Phase 5 high-level Compliance Evidence Chain
(CEC) service client. It orchestrates signed ZIP bundle assembly, multi-framework
regulatory clause mapping, bundle integrity verification, GDPR Article 28
Data Processing Agreement generation, and BYOS-aware status reporting.

The pre-built `sf_cec` singleton is available at the top level:

```python
from spanforge.sdk import sf_cec
```

---

## Quick example

```python
from spanforge.sdk import sf_cec

# Build a signed compliance evidence bundle
result = sf_cec.build_bundle(
    project_id="my-agent",
    date_range=("2026-01-01", "2026-03-31"),
    frameworks=["eu_ai_act", "soc2"],
)
print(result.bundle_id)       # "cec-<ulid>"
print(result.zip_path)        # "/tmp/halluccheck_cec_my-agent_2026-01-01_2026-03-31.zip"
print(result.hmac_manifest)   # "hmac-sha256:<64 hex chars>"
print(result.record_counts)   # {"score_records": 120, "pii_detections": 8, ...}

# Verify the bundle
check = sf_cec.verify_bundle(result.zip_path)
assert check.overall_valid
assert check.manifest_valid
assert check.chain_valid

# Generate a GDPR Art.28 DPA
dpa = sf_cec.generate_dpa(
    project_id="my-agent",
    controller_details={"name": "Acme Corp", "address": "1 Main St"},
    processor_details={"name": "SpanForge Inc", "address": "2 Cloud Way"},
    subject_categories=["employees", "end-users"],
    transfer_mechanisms=["SCCs"],
    retention_period_days=2555,
    law_of_contract="GDPR Art.28",
)
print(dpa.document_id)

# Check service status
status = sf_cec.get_status()
print(status.bundle_count)
print(status.frameworks_supported)   # ["eu_ai_act", "iso_42001", ...]
```

---

## `SFCECClient`

```python
class SFCECClient(SFServiceClient)
```

All methods are thread-safe. A `threading.Lock()` protects `bundle_count`
and `last_bundle_at` via the internal `_CECSessionStats` dataclass.

### Constructor

```python
SFCECClient(config: SFClientConfig)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `config` | *(required)* | SDK client config. Reads `signing_key` for HMAC operations. A warning is emitted if the key is unset or uses the insecure default. |

---

### `build_bundle()`

```python
def build_bundle(
    self,
    project_id: str,
    date_range: tuple[str, str],
    frameworks: list[str] | None = None,
) -> BundleResult
```

Orchestrates a full CEC bundle:

1. Exports audit records for all 6 schema keys via `sf_audit.export()`.
2. Computes regulatory clause satisfaction for each requested framework.
3. Assembles a ZIP archive (see [Bundle structure](#bundle-structure)).
4. HMAC-SHA256 signs the manifest.
5. Updates session stats (`bundle_count`, `last_bundle_at`).

| Parameter | Default | Description |
|-----------|---------|-------------|
| `project_id` | *(required)* | The project/agent identifier. Used in the ZIP filename. |
| `date_range` | *(required)* | `(from_date, to_date)` as ISO 8601 date strings (`"YYYY-MM-DD"`). |
| `frameworks` | all supported | List of framework values to include in clause mapping. Defaults to all 5 supported frameworks. |

**Returns:** [`BundleResult`](#bundleresult)

**Raises:** `SFCECBuildError` on ZIP write failure or HMAC error.

**Supported `frameworks` values:**

| Value | Standard |
|-------|----------|
| `eu_ai_act` | EU AI Act (Articles 9, 10, 12, 13, 14, 15) |
| `iso_42001` | ISO/IEC 42001 AI Management System |
| `nist_ai_rmf` | NIST AI Risk Management Framework |
| `iso27001` | ISO/IEC 27001 Annex A |
| `soc2` | SOC 2 Type II |

---

### `verify_bundle()`

```python
def verify_bundle(self, zip_path: str) -> BundleVerificationResult
```

Verifies a previously built bundle by:

1. Re-computing the manifest HMAC and comparing against the stored value.
2. Re-validating the chain proof entries.
3. Confirming the RFC 3161 timestamp stub (`rfc3161_timestamp.tsr`) is present.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `zip_path` | *(required)* | Absolute path to the `.zip` bundle file. |

**Returns:** [`BundleVerificationResult`](#bundleverificationresult)

**Raises:** `SFCECVerifyError` if the ZIP file is missing or unreadable. Individual check failures are captured in `result.errors` rather than raised.

---

### `generate_dpa()`

```python
def generate_dpa(
    self,
    project_id: str,
    controller_details: dict,
    processor_details: dict,
    *,
    subject_categories: list[str],
    transfer_mechanisms: list[str],
    retention_period_days: int,
    law_of_contract: str,
) -> DPADocument
```

Generates a GDPR Article 28 Data Processing Agreement document populated
with the project's evidence records and the provided party details.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `project_id` | *(required)* | Project identifier. |
| `controller_details` | *(required)* | Dict with at minimum `name` and `address` of the data controller. |
| `processor_details` | *(required)* | Dict with at minimum `name` and `address` of the data processor. |
| `subject_categories` | *(required)* | List of data subject categories (e.g. `["employees", "end-users"]`). |
| `transfer_mechanisms` | *(required)* | Legal basis for international transfers (e.g. `["SCCs"]`). |
| `retention_period_days` | *(required)* | Record retention period in days. |
| `law_of_contract` | *(required)* | Governing law string (e.g. `"GDPR Art.28"`). |

**Returns:** [`DPADocument`](#dpadocument)

**Raises:** `SFCECExportError` on generation failure.

---

### `get_status()`

```python
def get_status(self) -> CECStatusInfo
```

Returns current session statistics and service configuration.

**Returns:** [`CECStatusInfo`](#cecstatusinfo)

---

## Bundle structure

A bundle ZIP is named `halluccheck_cec_{project_id}_{from}_{to}.zip` and contains:

| Entry | Description |
|-------|-------------|
| `manifest.json` | Record inventory with per-schema-key counts and HMAC-SHA256 signature |
| `clause_map.json` | Per-framework clause satisfaction entries (SATISFIED / PARTIAL / GAP) |
| `chain_proof.json` | `verify_chain()` result from `sf_audit` |
| `attestation.json` | HMAC-signed attestation metadata block |
| `rfc3161_timestamp.tsr` | RFC 3161 trusted timestamp stub |
| `score_records/` | NDJSON — hallucination score records |
| `bias_reports/` | NDJSON — bias evaluation records |
| `prri_records/` | NDJSON — PRRI risk records |
| `drift_events/` | NDJSON — model drift events |
| `pii_detections/` | NDJSON — PII detection records |
| `gate_evaluations/` | NDJSON — trust gate evaluation records |

---

## Return types

### `BundleResult`

```python
@dataclass
class BundleResult:
    bundle_id: str           # "cec-<ulid>"
    zip_path: str            # absolute path to the ZIP
    hmac_manifest: str       # "hmac-sha256:<64 hex chars>"
    record_counts: dict      # {schema_key: count, ...}
    frameworks_covered: list[str]
    generated_at: str        # ISO 8601 UTC
```

### `BundleVerificationResult`

```python
@dataclass
class BundleVerificationResult:
    bundle_id: str
    manifest_valid: bool
    chain_valid: bool
    timestamp_valid: bool
    overall_valid: bool      # True iff all three checks pass
    errors: list[str]        # populated when any check fails
    verified_at: str         # ISO 8601 UTC
```

### `DPADocument`

```python
@dataclass
class DPADocument:
    document_id: str
    project_id: str
    controller_details: dict
    processor_details: dict
    generated_at: str
    content: str             # full DPA text
    subject_categories: list[str]
    transfer_mechanisms: list[str]
```

### `CECStatusInfo`

```python
@dataclass
class CECStatusInfo:
    byos_provider: str | None    # None when using local storage
    bundle_count: int
    last_bundle_at: str | None   # ISO 8601 UTC or None
    frameworks_supported: list[str]
```

### `ClauseMapEntry`

```python
@dataclass
class ClauseMapEntry:
    framework: str
    clause_id: str
    clause_name: str
    description: str
    status: ClauseSatisfaction   # SATISFIED | PARTIAL | GAP
    evidence_count: int
```

### `ClauseSatisfaction`

```python
class ClauseSatisfaction(str, Enum):
    SATISFIED = "SATISFIED"
    PARTIAL   = "PARTIAL"
    GAP       = "GAP"
```

---

## Exceptions

| Exception | Raised when |
|-----------|-------------|
| `SFCECError` | Base class for all sf-cec errors |
| `SFCECBuildError` | `build_bundle()` — ZIP write error or HMAC failure |
| `SFCECVerifyError` | `verify_bundle()` — file not found, unreadable ZIP, or HMAC mismatch |
| `SFCECExportError` | `generate_dpa()` — DPA generation or export failure |

All CEC exceptions are re-exported from `spanforge.sdk`:

```python
from spanforge.sdk import SFCECError, SFCECBuildError, SFCECVerifyError, SFCECExportError
```

---

## Environment variables

| Variable | Description |
|----------|-------------|
| `SPANFORGE_SIGNING_KEY` | HMAC-SHA256 key for signing bundle manifests. **Set this in production.** Warning emitted if unset. |
| `SPANFORGE_AUDIT_BYOS_PROVIDER` | Shared with sf-audit. When set, `get_status()` reflects the active provider. |

See [configuration.md](../configuration.md#cec-service-settings-phase-5) for full details.

---

## Thread safety

`SFCECClient` is safe to use from multiple threads simultaneously.
The session counters (`bundle_count`, `last_bundle_at`) are protected by
a `threading.Lock()` inside `_CECSessionStats`. The `sf_cec` singleton uses
the same lock, so concurrent `build_bundle()` calls will not race on stats.
