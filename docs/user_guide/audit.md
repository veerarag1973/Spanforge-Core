# Audit Service (sf-audit)

> **Added in:** 2.0.3 (Phase 4)  
> **Module:** `spanforge.sdk.audit`  
> **Singleton:** `spanforge.sdk.sf_audit`

The sf-audit service provides a single call-site for writing tamper-evident,
HMAC-chained audit records across all SpanForge quality signals. It enforces
schema keys, builds a T.R.U.S.T. scorecard from score feeds, and generates
GDPR Article 30 Records of Processing Activity.

---

## Installation

sf-audit ships with the core package — no extra dependencies required for
local mode. BYOS backends (S3, Azure, GCS, R2) require the corresponding
cloud SDK to be installed separately.

```shell
pip install spanforge          # local mode
pip install spanforge boto3    # + S3 BYOS backend
pip install spanforge azure-storage-blob  # + Azure BYOS backend
```

---

## Getting started

```python
from spanforge.sdk import sf_audit

# Append a hallucination score
result = sf_audit.append(
    {"score": 0.92, "model": "gpt-4o", "prompt_id": "p-001"},
    schema_key="halluccheck.score.v1",
)
print(result.record_id)       # "3f9a7e12-..."
print(result.chain_position)  # 0
print(result.hmac)            # "hmac-sha256:a3f..."
```

The `sf_audit` singleton is initialised automatically from environment
variables. Call `spanforge.sdk.configure()` to reconfigure at runtime:

```python
from spanforge.sdk import configure, SFClientConfig

configure(SFClientConfig(
    endpoint="https://audit.internal.example.com",
    api_key="...",
    signing_key="base64-key",
    project_id="my-project",
))
```

---

## Appending records

### Basic append

```python
result = sf_audit.append(
    {"score": 0.85, "model": "claude-3-5-sonnet", "run_id": "r-42"},
    schema_key="halluccheck.score.v1",
)
```

### Per-call project override

```python
result = sf_audit.append(
    {"decision": "allow", "policy": "data-access"},
    schema_key="halluccheck.gate.v1",
    project_id="project-b",
)
```

### Custom schema keys (non-strict mode)

```python
result = sf_audit.append(
    {"custom_field": "value"},
    schema_key="acme.internal.v1",
    strict_schema=False,   # bypass registry enforcement for this call
)
```

---

## Schema key registry

SpanForge enforces a registry of known schema keys. Unknown keys raise
`SFAuditSchemaError` unless `strict_schema=False`.

| Schema key | Purpose |
|------------|---------|
| `halluccheck.score.v1` | Hallucination quality scores (T.R.U.S.T. feed) |
| `halluccheck.pii.v1` | PII scan results (T.R.U.S.T. feed) |
| `halluccheck.secrets.v1` | Secrets scan results (T.R.U.S.T. feed) |
| `halluccheck.gate.v1` | Gate pass/fail decisions (T.R.U.S.T. feed) |
| `halluccheck.bias.v1` | Bias detection scores |
| `halluccheck.drift.v1` | Distribution drift signals |
| `halluccheck.opa.v1` | OPA policy evaluation results |
| `halluccheck.prri.v1` | Prompt risk/relevance index |
| `halluccheck.auth.v1` | Authentication/authorisation events |
| `halluccheck.benchmark_run.v1` | Benchmark run metadata |
| `halluccheck.benchmark_version.v1` | Benchmark version metadata |
| `spanforge.auth.v1` | SpanForge platform auth events |
| `spanforge.consent.v1` | Consent lifecycle events |

---

## Querying records

```python
# All records for a schema key in a date range
records = sf_audit.query(
    schema_key="halluccheck.score.v1",
    from_dt="2026-01-01T00:00:00.000000Z",
    to_dt="2026-03-31T23:59:59.999999Z",
    limit=500,
)

# All records for a project
records = sf_audit.query(project_id="project-a", limit=1000)
```

Queries use a SQLite WAL-mode index for O(log n) date-range lookups and
fall back to a linear scan on any SQLite error.

---

## Verifying chain integrity

```python
records = sf_audit.query(limit=10000)
report = sf_audit.verify_chain(records)

if report["valid"]:
    print(f"Chain intact — {report['verified_count']} records verified")
else:
    print(f"Tampered records: {report['tampered_count']}")
    print(f"First tampered:   {report['first_tampered']}")
    print(f"Sequence gaps:    {report['gaps']}")
```

`verify_chain()` re-derives the HMAC-SHA256 for each record and checks
`chain_position` for gaps. An empty list returns `valid=True`.

---

## T.R.U.S.T. scorecard

Every `append()` call for a score-bearing schema key automatically writes
a T.R.U.S.T. dimension feed entry. Retrieve the aggregated scorecard with:

```python
scorecard = sf_audit.get_trust_scorecard(
    from_dt="2026-01-01T00:00:00.000000Z",
    to_dt="2026-12-31T23:59:59.999999Z",
)

print(f"Hallucination score: {scorecard.hallucination.score:.1f}")
print(f"  Trend: {scorecard.hallucination.trend}")    # "up" | "flat" | "down"
print(f"PII hygiene:         {scorecard.pii_hygiene.score:.1f}")
print(f"Gate pass rate:      {scorecard.gate_pass_rate.score:.1f}")
print(f"Records in window:   {scorecard.record_count}")
```

**T.R.U.S.T. dimension → schema key mapping:**

| Dimension | Fed by |
|-----------|--------|
| Hallucination | `halluccheck.score.v1` |
| PII hygiene | `halluccheck.pii.v1` |
| Secrets hygiene | `halluccheck.secrets.v1` |
| Gate pass rate | `halluccheck.gate.v1` |
| Compliance posture | `halluccheck.opa.v1`, `halluccheck.auth.v1` |

---

## GDPR Article 30 record generation

```python
ropa = sf_audit.generate_article30_record(
    controller_name="Acme Corp",
    processor_name="SpanForge",
    processing_purposes=["AI quality assurance", "hallucination monitoring"],
    data_categories=["LLM outputs", "prompts", "evaluation scores"],
    data_subjects=["end users", "employees"],
    recipients=["DPO", "compliance team", "external auditors"],
    third_country=False,
    security_measures=["HMAC-SHA256 chain", "AES-256 at rest", "TLS 1.3 in transit"],
)

import json
print(json.dumps(ropa.__dict__, indent=2))
```

The returned `Article30Record` is a frozen dataclass; persist it via your
preferred serialisation format.

---

## Exporting audit records

```python
# JSONL export
raw = sf_audit.export(format="jsonl")
with open("audit.jsonl", "wb") as f:
    f.write(raw)

# Compressed CSV for archival
compressed = sf_audit.export(format="csv", compress=True)
with open("audit.csv.gz", "wb") as f:
    f.write(compressed)
```

---

## Signing individual records

```python
signed = sf_audit.sign({"event": "model_deployed", "version": "2.1.0"})
print(signed.hmac)        # "hmac-sha256:..."
print(signed.signed_at)   # ISO-8601 UTC
```

`sign()` does not append to the chain — use `append()` for persistent records.

---

## Status check

```python
status = sf_audit.get_status()
print(status.status)         # "ok" | "degraded"
print(status.backend)        # "local" | "s3" | "azure" | "gcs" | "r2"
print(status.record_count)   # total records in local store
print(status.chain_length)   # length of HMAC chain
```

---

## BYOS backend routing

Route appends to your own storage by setting `SPANFORGE_AUDIT_BYOS_PROVIDER`:

```shell
# Amazon S3
export SPANFORGE_AUDIT_BYOS_PROVIDER=s3

# Azure Blob Storage
export SPANFORGE_AUDIT_BYOS_PROVIDER=azure

# Google Cloud Storage
export SPANFORGE_AUDIT_BYOS_PROVIDER=gcs

# Cloudflare R2
export SPANFORGE_AUDIT_BYOS_PROVIDER=r2
```

When unset (default), records are stored in-process. The `backend` field on
`AuditAppendResult` reflects the active provider.

---

## Integrating with the pipeline

sf-audit integrates naturally after each SpanForge quality check:

```python
from spanforge.sdk import sf_audit, sf_pii, sf_secrets

# PII scan → audit
pii_result = sf_pii.scan_text(llm_output)
sf_audit.append(
    {"detected": pii_result.detected, "entity_count": len(pii_result.entities)},
    schema_key="halluccheck.pii.v1",
)

# Secrets scan → audit
sec_result = sf_secrets.scan(llm_output)
sf_audit.append(
    {"detected": sec_result.detected, "hit_count": len(sec_result.hits)},
    schema_key="halluccheck.secrets.v1",
)

# Hallucination score → audit
sf_audit.append(
    {"score": eval_score, "model": model_id},
    schema_key="halluccheck.score.v1",
)
```

---

## Error handling

```python
from spanforge.sdk import SFAuditSchemaError, SFAuditAppendError, SFAuditQueryError

try:
    sf_audit.append({"data": 1}, schema_key="unknown.v99")
except SFAuditSchemaError as e:
    print(f"Unknown schema key: {e}")

try:
    records = sf_audit.query(from_dt="invalid-date")
except SFAuditQueryError as e:
    print(f"Query failed: {e}")
```

---

## See also

- [API Reference — spanforge.sdk.audit](../api/audit.md)
- [Configuration Reference — Audit settings](../configuration.md#audit-service-settings-phase-4)
- [Runbook — Audit chain verification](../runbook.md#3-chain-verification)
- [HMAC Signing & Audit Chains](signing.md)
- [PII Redaction](redaction.md)
