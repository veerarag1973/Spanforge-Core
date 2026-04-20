# spanforge.sdk.audit — Audit Service Client

> **Module:** `spanforge.sdk.audit`  
> **Added in:** 2.0.3 (Phase 4: Audit Service High-Level API)

`spanforge.sdk.audit` provides the Phase 4 high-level audit service client
with HMAC-chained record appending, schema key enforcement, O(log n) date-range
queries, T.R.U.S.T. scorecard aggregation, GDPR Article 30 record generation,
and BYOS (Bring-Your-Own-Storage) backend routing.

The pre-built `sf_audit` singleton is available at the top level:

```python
from spanforge.sdk import sf_audit
```

---

## Quick example

```python
from spanforge.sdk import sf_audit

# Append a hallucination score record
result = sf_audit.append(
    {"score": 0.92, "model": "gpt-4o", "prompt_id": "p-001"},
    schema_key="halluccheck.score.v1",
)
print(result.record_id)       # uuid4
print(result.chain_position)  # 0
print(result.hmac)            # "hmac-sha256:<64 hex chars>"

# Query recent records
records = sf_audit.query(
    schema_key="halluccheck.score.v1",
    from_dt="2026-01-01T00:00:00.000000Z",
)

# Verify chain integrity
chain = sf_audit.query(limit=1000)
report = sf_audit.verify_chain(chain)
assert report["valid"], report["first_tampered"]

# T.R.U.S.T. scorecard
scorecard = sf_audit.get_trust_scorecard(
    from_dt="2026-01-01T00:00:00.000000Z",
    to_dt="2026-12-31T23:59:59.999999Z",
)
print(scorecard.hallucination.score)  # 0–100
```

---

## `SFAuditClient`

```python
class SFAuditClient(SFServiceClient)
```

All methods are thread-safe. Backed by `_LocalAuditStore` (SQLite WAL-mode
index + in-memory record list) in local/fallback mode, or routed to a
BYOS backend when `SPANFORGE_AUDIT_BYOS_PROVIDER` is set.

### Constructor

```python
SFAuditClient(
    config: SFClientConfig,
    *,
    strict_schema: bool = True,
    retention_years: int = 7,
    byos_provider: str | None = None,
    db_path: str | None = None,
    persist_index: bool = False,
)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `config` | *(required)* | SDK client config (endpoint, api_key, signing_key, project_id). |
| `strict_schema` | `True` | Reject unknown schema keys with `SFAuditSchemaError`. Set `False` to allow custom keys. |
| `retention_years` | `7` | Years to retain records; surfaced in Article 30 output. |
| `byos_provider` | `None` | Override BYOS provider (`"s3"`, `"azure"`, `"gcs"`, `"r2"`). Normally set via env var. |
| `db_path` | `None` | SQLite database file path. Defaults to an in-memory database. |
| `persist_index` | `False` | When `True`, the SQLite index persists to `db_path` across restarts. |

---

### `append()`

```python
def append(
    self,
    record: dict,
    schema_key: str,
    *,
    project_id: str | None = None,
    strict_schema: bool | None = None,
) -> AuditAppendResult
```

Validate, HMAC-sign, and append a record to the audit chain. Automatically
writes a T.R.U.S.T. dimension feed entry for score-bearing schema keys
(`halluccheck.score.v1`, `halluccheck.pii.v1`, `halluccheck.secrets.v1`,
`halluccheck.gate.v1`).

| Parameter | Default | Description |
|-----------|---------|-------------|
| `record` | *(required)* | Dict payload. Must not be empty. |
| `schema_key` | *(required)* | One of the [known schema keys](#schema-key-registry) unless `strict_schema=False`. |
| `project_id` | config value | Overrides the project ID for this record only. |
| `strict_schema` | client default | Per-call override of the `strict_schema` constructor setting. |

**Returns:** [`AuditAppendResult`](#auditappendresult)

**Raises:** `SFAuditSchemaError` for unknown schema keys (strict mode). `SFAuditAppendError` on chain write failure.

**Example:**

```python
result = sf_audit.append(
    {"score": 0.85, "model": "claude-3-5-sonnet"},
    schema_key="halluccheck.score.v1",
)
print(result.chain_position)  # increments per project
```

---

### `append_async()`

```python
async def append_async(
    self,
    record: dict,
    schema_key: str,
    *,
    project_id: str | None = None,
    strict_schema: bool | None = None,
) -> AuditAppendResult
```

Async variant of `append()`. Runs the validate-sign-append pipeline in a
thread-pool executor so it does not block the event loop.

```python
import asyncio
from spanforge.sdk import sf_audit

async def log_score(score: float):
    result = await sf_audit.append_async(
        {"score": score, "model": "gpt-4o"},
        schema_key="halluccheck.score.v1",
    )
    print(result.chain_position)
```

Accepts the same parameters and returns the same `AuditAppendResult` as `append()`.

---

### `sign()`

```python
def sign(self, record: dict) -> SignedRecord
```

Compute an HMAC-SHA256 signature for a raw record dict. Does not append to
the chain — use `append()` for persistence.

**Returns:** [`SignedRecord`](#signedrecord)

---

### `verify_chain()`

```python
def verify_chain(self, records: list[dict]) -> dict
```

Re-derive and verify the HMAC chain for a list of record dicts. Detects
tampered records and sequence gaps.

**Returns:** `dict` with keys:

| Key | Type | Description |
|-----|------|-------------|
| `valid` | `bool` | `True` if all HMACs verified and no gaps found. |
| `verified_count` | `int` | Number of records with valid HMACs. |
| `tampered_count` | `int` | Number of records with invalid HMACs. |
| `first_tampered` | `str \| None` | `record_id` of the first tampered record, or `None`. |
| `gaps` | `list[int]` | Sequence positions where `chain_position` jumps. |

**Example:**

```python
records = sf_audit.query(limit=500)
report = sf_audit.verify_chain(records)
if not report["valid"]:
    print("Tampered:", report["first_tampered"])
```

---

### `query()`

```python
def query(
    self,
    *,
    schema_key: str | None = None,
    project_id: str | None = None,
    from_dt: str | None = None,
    to_dt: str | None = None,
    limit: int = 1000,
) -> list[dict]
```

Date-range query backed by a SQLite WAL-mode index (O(log n)); falls back
to linear scan on SQLite error. All timestamps are ISO-8601 UTC.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `schema_key` | `None` | Filter to a specific schema key. |
| `project_id` | `None` | Filter to a specific project. |
| `from_dt` | `None` | Inclusive lower bound (`"2026-01-01T00:00:00.000000Z"`). |
| `to_dt` | `None` | Inclusive upper bound. |
| `limit` | `1000` | Maximum records to return. |

**Returns:** `list[dict]` — each dict is the original appended payload plus
`record_id`, `chain_position`, `timestamp`, `hmac`, `schema_key`, `project_id`.

**Raises:** `SFAuditQueryError` on unexpected query failure.

---

### `export()`

```python
def export(
    self,
    *,
    format: str = "jsonl",
    compress: bool = False,
) -> bytes
```

Export the full local store.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `format` | `"jsonl"` | Output format. Supported: `"jsonl"`, `"csv"`. |
| `compress` | `False` | gzip-compress the output when `True`. |

**Returns:** `bytes` — raw JSONL/CSV, optionally gzip-compressed.

**Example:**

```python
data = sf_audit.export(format="jsonl", compress=True)
with open("audit_export.jsonl.gz", "wb") as f:
    f.write(data)
```

---

### `get_trust_scorecard()`

```python
def get_trust_scorecard(
    self,
    *,
    project_id: str | None = None,
    from_dt: str | None = None,
    to_dt: str | None = None,
) -> TrustScorecard
```

Aggregate T.R.U.S.T. dimension scores from feed records written by `append()`.
Each dimension reflects a weighted average of scores observed in the time
window, plus an up/flat/down trend indicator.

**Dimensions:**

| Dimension | Source schema key(s) |
|-----------|---------------------|
| `hallucination` | `halluccheck.score.v1` |
| `pii_hygiene` | `halluccheck.pii.v1` |
| `secrets_hygiene` | `halluccheck.secrets.v1` |
| `gate_pass_rate` | `halluccheck.gate.v1` |
| `compliance_posture` | `halluccheck.opa.v1`, `halluccheck.auth.v1` |

**Returns:** [`TrustScorecard`](#trustscorecard)

---

### `generate_article30_record()`

```python
def generate_article30_record(
    self,
    *,
    project_id: str | None = None,
    controller_name: str,
    processor_name: str,
    processing_purposes: list[str],
    data_categories: list[str],
    data_subjects: list[str],
    recipients: list[str],
    third_country: bool = False,
    security_measures: list[str] | None = None,
) -> Article30Record
```

Generate a GDPR Article 30 Record of Processing Activities (RoPA).

**Returns:** [`Article30Record`](#article30record)

**Example:**

```python
ropa = sf_audit.generate_article30_record(
    controller_name="Acme Corp",
    processor_name="SpanForge",
    processing_purposes=["AI quality assurance", "hallucination monitoring"],
    data_categories=["LLM outputs", "prompts"],
    data_subjects=["end users"],
    recipients=["DPO", "compliance team"],
    third_country=False,
    security_measures=["HMAC-SHA256 chain", "AES-256 at rest"],
)
print(ropa.record_id)  # uuid4
```

---

### `get_status()`

```python
def get_status(self) -> AuditStatusInfo
```

Return current client status.

**Returns:** [`AuditStatusInfo`](#auditstatusinfo)

---

## Schema key registry

`SFAuditClient` enforces a known-key registry when `strict_schema=True` (default).

| Schema key | Purpose |
|------------|---------|
| `halluccheck.score.v1` | Hallucination quality scores |
| `halluccheck.pii.v1` | PII scan results |
| `halluccheck.secrets.v1` | Secrets scan results |
| `halluccheck.gate.v1` | Gate pass/fail decisions |
| `halluccheck.bias.v1` | Bias detection scores |
| `halluccheck.drift.v1` | Distribution drift signals |
| `halluccheck.opa.v1` | OPA policy evaluation results |
| `halluccheck.prri.v1` | Prompt risk/relevance index |
| `halluccheck.auth.v1` | Authentication/authorisation events |
| `halluccheck.benchmark_run.v1` | Benchmark run metadata |
| `halluccheck.benchmark_version.v1` | Benchmark version metadata |
| `spanforge.auth.v1` | SpanForge platform auth events |
| `spanforge.consent.v1` | Consent lifecycle events |

Use `strict_schema=False` at the client or per-call level to allow custom keys:

```python
sf_audit.append({"custom": "data"}, schema_key="acme.custom.v1", strict_schema=False)
```

---

## Return types

### `AuditAppendResult`

```python
@dataclass(frozen=True)
class AuditAppendResult:
    record_id: str        # UUID4
    chain_position: int   # Zero-based position in the chain
    timestamp: str        # ISO-8601 UTC, microsecond precision
    hmac: str             # "hmac-sha256:<64 hex chars>"
    schema_key: str
    backend: str          # "local" | "s3" | "azure" | "gcs" | "r2"
```

### `SignedRecord`

```python
@dataclass(frozen=True)
class SignedRecord:
    record_id: str
    payload: dict
    hmac: str             # "hmac-sha256:<64 hex chars>"
    signed_at: str        # ISO-8601 UTC
    project_id: str
```

### `TrustDimension`

```python
@dataclass(frozen=True)
class TrustDimension:
    score: float          # 0.0–100.0
    trend: str            # "up" | "flat" | "down"
    last_updated: str     # ISO-8601 UTC
```

### `TrustScorecard`

```python
@dataclass(frozen=True)
class TrustScorecard:
    project_id: str
    from_dt: str
    to_dt: str
    hallucination: TrustDimension
    pii_hygiene: TrustDimension
    secrets_hygiene: TrustDimension
    gate_pass_rate: TrustDimension
    compliance_posture: TrustDimension
    record_count: int
```

### `Article30Record`

```python
@dataclass(frozen=True)
class Article30Record:
    project_id: str
    controller_name: str
    processor_name: str
    processing_purposes: list[str]
    data_categories: list[str]
    data_subjects: list[str]
    recipients: list[str]
    third_country: bool
    retention_period: str   # e.g. "7 years"
    security_measures: list[str]
    generated_at: str       # ISO-8601 UTC
    record_id: str          # UUID4
```

### `AuditStatusInfo`

```python
@dataclass(frozen=True)
class AuditStatusInfo:
    status: str           # "ok" | "degraded"
    backend: str          # "local" | "s3" | "azure" | "gcs" | "r2"
    record_count: int
    chain_length: int
    byos_provider: str | None
    last_record_at: str | None   # ISO-8601 UTC, or None if no records
    retention_years: int
```

---

## Exceptions

| Exception | Inherits | Raised when |
|-----------|----------|-------------|
| `SFAuditError` | `SFError` | Base class for all sf-audit errors |
| `SFAuditSchemaError` | `SFAuditError` | Unknown schema key in strict mode |
| `SFAuditAppendError` | `SFAuditError` | Chain write failure |
| `SFAuditQueryError` | `SFAuditError` | Query execution failure |

All exceptions are importable from `spanforge.sdk`:

```python
from spanforge.sdk import SFAuditError, SFAuditSchemaError
```

---

## BYOS backend routing

Set `SPANFORGE_AUDIT_BYOS_PROVIDER` to route appends to your own storage:

| Value | Storage |
|-------|---------|
| `s3` | Amazon S3 |
| `azure` | Azure Blob Storage |
| `gcs` | Google Cloud Storage |
| `r2` | Cloudflare R2 |
| *(unset)* | Local in-memory store |

```shell
export SPANFORGE_AUDIT_BYOS_PROVIDER=s3
```

The `backend` field on `AuditAppendResult` and `AuditStatusInfo` reflects the
active provider.

---

## Thread safety

`SFAuditClient` uses `threading.Lock` to protect the record list, chain
counter, and T.R.U.S.T. feed. All public methods are safe to call from
multiple threads concurrently.
