# Compliance & Tenant Isolation

The `spanforge.core.compliance_mapping` module provides programmatic compliance tests
that enterprise teams and third-party tool authors can run in CI pipelines, at
deployment time, or as part of security audits — without requiring pytest.

## Compatibility checklist (`test_compatibility`)

The five-point compatibility checklist verifies that a batch of events meets
the spanforge v1.0 adoption requirements:

```python
from spanforge.compliance import test_compatibility

result = test_compatibility(events)

if result.passed:
    print(f"All {result.events_checked} events are compatible.")
else:
    for v in result.violations:
        print(f"[{v.check_id}] {v.event_id}: {v.rule} — {v.detail}")
```

The five checks:

| Check | Rule | Description |
|-------|------|-------------|
| CHK-1 | Required fields present | `schema_version`, `source`, and `payload` must be non-empty. |
| CHK-2 | Event type registered or valid custom | Must be a first-party `EventType` value **or** pass `validate_custom`. |
| CHK-3 | Source identifier format | Must match `^[a-z][a-z0-9-]*@\d+\.\d+(\.\d+)?([.-][a-z0-9]+)*$`. |
| CHK-5 | Event ID is a valid ULID | `event_id` must be a well-formed 26-character ULID string. |

## Audit chain integrity (`verify_chain_integrity`)

Wraps `verify_chain()` with higher-level diagnostics:

```python
from spanforge.core.compliance_mapping import verify_chain_integrity

result = verify_chain_integrity(
    events,
    org_secret="my-org-secret",
    check_monotonic_timestamps=True,   # default
)

print(f"Events verified: {result.events_verified}")
print(f"Gaps detected:   {result.gaps_detected}")

for v in result.violations:
    # v.violation_type: "tampered" | "gap" | "non_monotonic_timestamp"
    print(f"[{v.violation_type}] {v.event_id}: {v.detail}")
```

## Multi-tenant isolation (`verify_tenant_isolation`)

Verify that events from two tenants share no `org_id` values and that each
tenant's events are internally consistent:

```python
from spanforge.core.compliance_mapping import verify_tenant_isolation

result = verify_tenant_isolation(
    tenant_a_events,
    tenant_b_events,
    strict=True,    # flag events missing org_id (default)
)

if not result:
    for v in result.violations:
        # v.violation_type: "missing_org_id" | "mixed_org_ids" | "shared_org_id"
        print(f"  {v.violation_type}: {v.detail}")
```

## Scope verification (`verify_events_scoped`)

Assert that all events in a batch belong to an expected org/team:

```python
from spanforge.core.compliance_mapping import verify_events_scoped

result = verify_events_scoped(
    events,
    expected_org_id="org_01HX",
    expected_team_id="team_engineering",
)

if not result:
    for v in result.violations:
        # v.violation_type: "wrong_org_id" | "wrong_team_id"
        print(f"  {v.event_id}: {v.detail}")
```

## Using compliance results

All result objects are truthy on success and falsy on failure:

```python
result = verify_tenant_isolation(a, b)
assert result, f"Isolation failed: {result.violations}"

# Or use in conditional logic:
if not result:
    notify_security_team(result.violations)
```

## CI integration

```python
# conftest.py or test_compliance.py
import pytest
from spanforge.compliance import test_compatibility

def test_all_events_compatible(captured_events):
    result = test_compatibility(captured_events)
    assert result, "\n".join(
        f"  [{v.check_id}] {v.event_id}: {v.detail}"
        for v in result.violations
    )
```

---

## Regulatory compliance mapping (`ComplianceMappingEngine`)

The `ComplianceMappingEngine` maps spanforge telemetry events to clauses in
regulatory frameworks and generates full evidence packages — including gap
analysis and HMAC-signed attestations.

### Supported frameworks

| Framework | Key |
|-----------|-----|
| EU AI Act | `eu_ai_act` |
| ISO 42001 | `iso_42001` |
| NIST AI RMF | `nist_ai_rmf` |
| GDPR | `gdpr` |
| SOC 2 | `soc2` |

### Generating an evidence package

```python
from spanforge.core.compliance_mapping import ComplianceMappingEngine

engine = ComplianceMappingEngine()
package = engine.generate_evidence_package(
    model_id="gpt-4o",
    framework="eu_ai_act",
    from_date="2026-01-01",
    to_date="2026-03-31",
    audit_events=events,  # list of event dicts; omit to load from TraceStore
)

print(package.framework)        # "eu_ai_act"
print(package.model_id)         # "gpt-4o"
print(len(package.mappings))    # number of clause mappings
print(package.gap_report)       # gap analysis with coverage stats
print(package.attestation)      # HMAC-signed attestation dict
```

### CLI usage

```bash
# Generate evidence package
spanforge compliance generate --model-id gpt-4o --framework eu_ai_act --from 2026-01-01 --to 2026-03-31 --events-file events.jsonl

# Run a compliance gate over an events file
spanforge compliance check --framework eu_ai_act --from 2026-01-01 --to 2026-03-31 --events-file events.jsonl

# Verify attestation signature only
spanforge compliance validate-attestation evidence.json
```

The attestation signature uses HMAC-SHA256 with the signing key from
`SPANFORGE_SIGNING_KEY` (falls back to `"spanforge-default"` with a warning).

### Clause-to-event-prefix mapping

The engine maps spanforge telemetry event prefixes to specific regulatory
clauses. The following table summarises the key mappings:

| Framework | Clause | Event prefixes | Description |
|-----------|--------|----------------|-------------|
| GDPR | Art. 22 | `consent.*`, `hitl.*` | Automated Individual Decision-Making — consent and oversight |
| GDPR | Art. 25 | `llm.redact.*`, `consent.*` | Data Protection by Design |
| EU AI Act | Art. 13 | `explanation.*` | Transparency — explainability of AI decisions |
| EU AI Act | Art. 14 | `hitl.*`, `consent.*` | Human Oversight — HITL review and escalation |
| EU AI Act | Annex IV.5 | `llm.guard.*`, `llm.audit.*`, `hitl.*` | Technical Documentation — safety and oversight |
| SOC 2 | CC6.1 | `llm.audit.*`, `llm.trace.*`, `model_registry.*` | Logical and Physical Access Controls |
| NIST AI RMF | MAP 1.1 | `llm.trace.*`, `llm.eval.*`, `model_registry.*`, `explanation.*` | Risk identification and mapping |

### Model registry enrichment

When a model is registered in the `ModelRegistry`, the attestation is
automatically enriched with metadata:

```python
from spanforge.model_registry import ModelRegistry

registry = ModelRegistry()
registry.register("gpt-4o", owner="ml-team", risk_tier="high")

# Evidence packages now include:
# attestation.model_owner    → "ml-team"
# attestation.model_risk_tier → "high"
# attestation.model_status   → "active"
# attestation.model_warnings → []  (empty if active/registered)
```

Warnings are automatically emitted for:
- **Deprecated models** — `"model 'X' is deprecated"`
- **Retired models** — `"model 'X' is retired"`
- **Unregistered models** — `"model 'X' not found in registry"`

### Explanation coverage metric

The engine computes the percentage of decision events (`llm.trace.*` and
`hitl.*`) that have corresponding `explanation.*` events:

```python
package = engine.generate_evidence_package(
    model_id="gpt-4o",
    framework="eu_ai_act",
    from_date="2026-01-01",
    to_date="2026-03-31",
    audit_events=events,
)

print(package.attestation.explanation_coverage_pct)  # e.g. 75.0
```

This metric is also available via the `/compliance/summary` HTTP endpoint.

---

## Regulation-specific PII compliance (Phase 3)

`spanforge.sdk.pii` exposes dedicated helpers for each major privacy regulation.
All helpers are available on the `sf_pii` singleton:

```python
from spanforge.sdk import sf_pii
```

---

### GDPR — Article 17 (Right to Erasure)

When a data subject invokes their right to erasure ("right to be forgotten"),
call `erase_subject()` to purge their PII from spanforge storage and receive a
machine-readable receipt suitable for your compliance audit trail.

```python
receipt = sf_pii.erase_subject(subject_id="user-42")
# ErasureReceipt
print(receipt.receipt_id)         # "erase-20260417-abc123"
print(receipt.subject_id_hash)    # SHA-256 of "user-42" (never the raw ID)
print(receipt.fields_erased)      # number of fields purged
print(receipt.timestamp)          # ISO 8601
print(receipt.audit_log_entry)    # dict ready for your audit log
```

**Security note:** The raw `subject_id` is never stored in the receipt.
Only its SHA-256 digest is retained.

---

### CCPA — Data Subject Access Request (DSAR)

California consumers may request a copy of their personal data held by your
service.  `export_subject_data()` collects all PII-tagged fields for a subject:

```python
export = sf_pii.export_subject_data(subject_id="user-42")
# DSARExport
print(export.subject_id_hash)     # SHA-256 digest
print(export.record_count)        # number of records exported
for field in export.fields:
    print(field.field_path, field.pii_type, field.event_id)
```

Combine with `erase_subject()` to implement a full CCPA deletion-plus-export
flow:

```python
export = sf_pii.export_subject_data("user-42")
receipt = sf_pii.erase_subject("user-42")
store_compliance_record(export, receipt)
```

---

### HIPAA — Safe Harbor De-identification

The 18 HIPAA Safe Harbor identifiers (name, dates, geographic data, phone,
fax, email, SSN, etc.) are removed in a single call:

```python
safe = sf_pii.safe_harbor_deidentify(
    {
        "name": "Alice Smith",
        "dob": "1980-01-15",
        "zip": "02139",
        "email": "alice@example.com",
        "ssn": "078-05-1120",
    }
)
# SafeHarborResult
print(safe.method)                  # "HIPAA_SAFE_HARBOR"
print(safe.original_field_count)    # 5
print(safe.redacted_field_count)    # 5
print(safe.redacted_record)         # dict with all 18 identifiers replaced
```

**Training data audit** — run safe harbor checks across a dataset before
fine-tuning:

```python
report = sf_pii.audit_training_data(training_records)
# TrainingDataPIIReport
print(report.pii_row_count)      # rows containing PII
print(report.total_row_count)    # total rows
print(report.risk_score)         # pii_row_count / total_row_count
print(report.entity_breakdown)   # {entity_type: count}
```

---

### DPDP — India Digital Personal Data Protection Act (2023)

The DPDP Act requires consent before processing sensitive personal data.
When a DPDP-regulated entity is detected without a consent record, the SDK
raises `SFPIIDPDPConsentMissingError`:

```python
from spanforge.sdk._exceptions import SFPIIDPDPConsentMissingError

try:
    result = sf_pii.scan_text("Aadhaar: 2950 7148 9635")
except SFPIIDPDPConsentMissingError as exc:
    # exc.subject_id_hash — SHA-256 of the subject ID
    # exc.entity_types    — ["IN_AADHAAR"]
    return consent_required_response(exc.entity_types)
```

DPDP entity types recognised:

| Entity type | Description |
|-------------|-------------|
| `IN_AADHAAR` | 12-digit UID (with/without spaces) |
| `IN_PAN` | Permanent Account Number (ABCDE1234F) |
| `IN_VOTER_ID` | Election Commission voter ID |
| `IN_PASSPORT` | Indian passport number |
| `IN_DRIVING_LICENSE` | Driving licence number |

You can also use the low-level `scan_payload()` with `DPDP_PATTERNS` for
backwards compatibility:

```python
from spanforge import scan_payload, DPDP_PATTERNS

result = scan_payload(
    {"uid": "2950 7148 9635"},
    extra_patterns=DPDP_PATTERNS,
)
```

---

### PIPL — China Personal Information Protection Law

China's PIPL defines sensitive categories of personal information.
Scan for PIPL entities by passing `language="zh"`:

```python
result = sf_pii.scan_text("身份证: 110101199003077516", language="zh")
for entity in result.entities:
    print(entity.entity_type, entity.score)  # PIPL_NATIONAL_ID 0.98
```

PIPL entity types:

| Entity type | Description |
|-------------|-------------|
| `PIPL_NATIONAL_ID` | 18-digit Resident Identity Card number |
| `PIPL_PASSPORT` | Chinese passport number |
| `PIPL_MOBILE` | Chinese mainland mobile number (+86 …) |
| `PIPL_BANK_CARD` | Chinese bank card / UnionPay number |
| `PIPL_SOCIAL_CREDIT` | Unified Social Credit Code (企业) |

---

## See also

- [spanforge.sdk.pii](../api/pii.md) — full API reference for all Phase 3 methods
- [user_guide/redaction.md](redaction.md#pii-service-sdk-phase-3) — field-level + SDK redaction
- [configuration](../configuration.md#pii-service-settings-phase-3) — environment variables
- [runbook](../runbook.md) — operational playbooks for PII service
