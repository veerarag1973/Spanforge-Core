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

### `build_bundle_async()` — async variant

> **Added in:** 2.0.14

```python
async def build_bundle_async(
    self,
    project_id: str,
    date_range: tuple,
    frameworks: list | None = None,
) -> BundleResult
```

Non-blocking async variant of `build_bundle()`.  Delegates to the synchronous
method via `asyncio.get_event_loop().run_in_executor()` so it never blocks the
event loop.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project_id` | `str` | *(required)* | Project identifier. |
| `date_range` | `tuple` | *(required)* | `(from_date, to_date)` ISO 8601 strings. |
| `frameworks` | `list \| None` | `None` | Framework list (same values as `build_bundle`). |

**Returns:** [`BundleResult`](#bundleresult)

**Example:**

```python
import asyncio
from spanforge.sdk import sf_cec

result = asyncio.run(
    sf_cec.build_bundle_async(
        "my-agent",
        ("2026-01-01", "2026-03-31"),
        frameworks=["eu_ai_act"],
    )
)
print(result.bundle_id)
```

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

### `get_bundle()`

> **Added in:** 2.0.13 (CEC-004)

```python
def get_bundle(self, bundle_id: str) -> BundleResult | None
```

Retrieves a previously built bundle from the in-memory session registry.
Returns `None` if the `bundle_id` was not found (bundle was never built in
this process, or the process was restarted).

| Parameter | Description |
|-----------|-------------|
| `bundle_id` | The `bundle_id` returned by a previous `build_bundle()` call. |

**Returns:** [`BundleResult`](#bundleresult) or `None`.

```python
result = sf_cec.get_bundle("cec-01JXXXXXXXXXXXXXXXXXX")
if result:
    print(result.download_url)
else:
    print("Bundle not found in session registry")
```

---

### `reissue_download_url()`

> **Added in:** 2.0.13 (CEC-004)

```python
def reissue_download_url(self, bundle_id: str) -> BundleResult
```

Extends the download URL expiry of an existing bundle by `+24 h` without
rebuilding the ZIP.  The ZIP file must still exist on disk.  The updated
`BundleResult` is stored back into the registry.

| Parameter | Description |
|-----------|-------------|
| `bundle_id` | The `bundle_id` returned by a previous `build_bundle()` call. |

**Returns:** [`BundleResult`](#bundleresult) with a refreshed `expires_at`.

**Raises:**
- `SFCECBuildError` — if `bundle_id` is not in the session registry.
- `SFCECBuildError` — if the ZIP file referenced by the bundle has been deleted from disk.

```python
# Re-issue a download URL 23 hours after bundle creation
refreshed = sf_cec.reissue_download_url("cec-01JXXXXXXXXXXXXXXXXXX")
print(refreshed.expires_at)   # now +24 h from now
print(refreshed.download_url) # same path, fresh expiry
```

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
    download_url: str        # file:// URI or presigned URL  (added 2.0.13)
    expires_at: datetime     # expiry of the download URL (default +24 h)  (added 2.0.13)
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
| `SFCECBuildError` | `build_bundle()` — ZIP write error or HMAC failure; `reissue_download_url()` — bundle not in registry or ZIP deleted from disk |
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

---

## REST Endpoints

> **Added in:** 2.0.13 (CEC-003 / CEC-004)

The `SFCECClient` exposes two HTTP endpoints when `spanforge serve` is
running (or when imported in a FastAPI / ASGI application).

### `POST /v1/risk/cec`

Build a compliance evidence bundle for the project identified by
`project_id`.  Equivalent to calling `build_bundle()` via the SDK.

**Request body (JSON):**

```json
{
  "project_id": "proj-abc123",
  "org_id": "org-prod",
  "org_secret": "SPANFORGE_SIGNING_KEY value",
  "output_dir": "/tmp/bundles",
  "frameworks": ["EU AI Act", "SOC 2"]
}
```

`org_secret` and `output_dir` are optional; defaults are read from env vars.
`frameworks` is optional; defaults to all 5 supported frameworks.

**Response `201 Created`:**

```json
{
  "bundle_id": "cec-01JXXXXXXXXXXXXXXXXXX",
  "zip_path": "/tmp/bundles/cec-01JXXXXXXXXXXXXXXXXXX.zip",
  "download_url": "file:///tmp/bundles/cec-01JXXXXXXXXXXXXXXXXXX.zip",
  "expires_at": "2026-01-02T15:04:05.000000+00:00",
  "hmac_manifest": "hmac-sha256:aabbcc...",
  "frameworks_covered": ["EU AI Act", "SOC 2"],
  "generated_at": "2026-01-01T15:04:05.000000+00:00"
}
```

**Error responses:**

| Status | Body | Meaning |
|--------|------|---------|
| `422 Unprocessable Entity` | `{"detail": "..."}` | Missing or invalid fields |
| `500 Internal Server Error` | `{"detail": "CEC build failed: ..."}` | `SFCECBuildError` |

---

### `GET /v1/risk/cec/{bundle_id}`

Retrieve a previously built bundle from the session registry.  Returns
`404` if the bundle was not found.

**Path parameter:** `bundle_id` — the `bundle_id` returned by a previous
`POST /v1/risk/cec` or `build_bundle()` call.

**Response `200 OK`:** same shape as the `POST` response above.

**Error responses:**

| Status | Body | Meaning |
|--------|------|---------|
| `404 Not Found` | `{"detail": "Bundle not found"}` | `bundle_id` not in session registry |

---

## Thread safety

`SFCECClient` is safe to use from multiple threads simultaneously.
The session counters (`bundle_count`, `last_bundle_at`) are protected by
a `threading.Lock()` inside `_CECSessionStats`. The `sf_cec` singleton uses
the same lock, so concurrent `build_bundle()` calls will not race on stats.
