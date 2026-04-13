# Compliance & Tenant Isolation

The `spanforge.compliance` package provides programmatic compliance tests
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
from spanforge.compliance import verify_chain_integrity

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
from spanforge.compliance import verify_tenant_isolation

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
from spanforge.compliance import verify_events_scoped

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
spanforge compliance generate --model gpt-4o --framework eu_ai_act --from 2026-01-01 --to 2026-03-31 events.jsonl

# Validate an existing evidence package
spanforge compliance check evidence.json

# Verify attestation signature only
spanforge compliance validate-attestation evidence.json
```

The attestation signature uses HMAC-SHA256 with the signing key from
`SPANFORGE_SIGNING_KEY` (falls back to `"spanforge-default"` with a warning).
