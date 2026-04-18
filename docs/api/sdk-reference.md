# SDK Reference Overview

> **DX-010 · Phase 12**

This page provides a quick-reference map of all SpanForge SDK service clients,
their primary methods, and links to detailed module documentation.

---

## Service Clients

All clients are available as singletons from `spanforge.sdk`:

```python
from spanforge.sdk import (
    sf_identity, sf_pii, sf_secrets, sf_audit,
    sf_observe, sf_gate, sf_cec, sf_alert,
    sf_trust, sf_enterprise, sf_security,
)
```

### sf_identity — Authentication & API Key Management

| Method | Description |
|--------|-------------|
| `issue_api_key(**kwargs)` | Issue a new API key bundle |
| `verify_token(jwt)` | Verify and decode a JWT |
| `refresh_token()` | Refresh the current auth token |
| `rotate_key(key_id)` | Rotate an existing API key |
| `revoke_key(key_id)` | Revoke an API key |
| `check_rate_limit(key_id)` | Check rate limit status |
| `enroll_totp(key_id)` | Enroll TOTP MFA |

[Full reference →](api/index.md)

### sf_pii — PII Detection & Redaction

| Method | Description |
|--------|-------------|
| `scan(payload)` | Scan a dict for PII |
| `scan_text(text)` | Scan plain text for PII |
| `redact(event)` | Redact PII from an event |
| `anonymize(text)` | Anonymize text (replace PII with placeholders) |
| `scan_batch(texts)` | Batch scan multiple texts |
| `erase_subject(subject_id, project_id)` | GDPR erasure |
| `export_subject_data(subject_id, project_id)` | DSAR export |

[Full reference →](api/pii.md)

### sf_secrets — Secret Detection

| Method | Description |
|--------|-------------|
| `scan(text)` | Scan text for credentials/secrets |
| `scan_batch(texts)` | Batch scan |
| `get_status()` | Scanner status |

[Full reference →](api/secrets.md)

### sf_audit — Immutable Audit Trail

| Method | Description |
|--------|-------------|
| `append(record, schema_key)` | Append a record to the audit chain |
| `sign(record)` | Sign a record with HMAC |
| `verify_chain(records)` | Verify chain integrity |
| `export(schema_key)` | Export audit records |
| `get_status()` | Audit backend status |

[Full reference →](api/audit.md)

### sf_observe — Observability & Tracing

| Method | Description |
|--------|-------------|
| `export_spans(spans)` | Export a batch of spans |
| `emit_span(name, attributes)` | Emit a single span |
| `add_annotation(event_type, payload)` | Add annotation |
| `get_annotations(event_type, from_dt, to_dt)` | Query annotations |
| `healthy` | Property: exporter health |

[Full reference →](api/observe.md)

### sf_gate — Quality Gates

| Method | Description |
|--------|-------------|
| `evaluate(gate_id, payload)` | Evaluate a gate |
| `run_trust_gate(project_id)` | Run the trust quality gate |
| `evaluate_prri(project_id)` | Production Readiness Risk Index |
| `list_artifacts(gate_id)` | List gate artifacts |

[Full reference →](api/gate.md)

### sf_cec — Compliance Evidence Collection

| Method | Description |
|--------|-------------|
| `build_bundle(project_id, date_range)` | Generate compliance bundle |
| `verify_bundle(zip_path)` | Verify bundle integrity |
| `generate_dpa(project_id, ...)` | Generate Data Processing Agreement |

[Full reference →](api/cec.md)

### sf_alert — Alert Management

| Method | Description |
|--------|-------------|
| `publish(topic, payload)` | Publish an alert |
| `register_topic(topic)` | Register a topic |
| `acknowledge(alert_id)` | Acknowledge an alert |
| `get_alert_history()` | Query alert history |

[Full reference →](api/alert.md)

### sf_trust — Trust Scorecard

| Method | Description |
|--------|-------------|
| `get_scorecard(project_id)` | Get trust scorecard |
| `get_history(project_id)` | Trust score history |
| `get_badge(project_id)` | Generate trust badge SVG |

[Full reference →](api/trust.md)

### sf_enterprise — Multi-Tenant & Enterprise Features

| Method | Description |
|--------|-------------|
| `register_tenant(project_id, org_id)` | Register a tenant |
| `get_isolation_scope(project_id)` | Get isolation scope |
| `configure_encryption(...)` | Configure encryption at rest |
| `configure_airgap(...)` | Configure air-gap mode |
| `check_health_endpoint(service)` | Health check a service |

[Full reference →](api/enterprise.md)

### sf_security — Security Scanning

| Method | Description |
|--------|-------------|
| `run_owasp_audit()` | Run OWASP Top 10 audit |
| `run_full_scan()` | Full security scan |
| `add_threat(...)` | Add to threat model |
| `scan_dependencies()` | Dependency vulnerability scan |

[Full reference →](api/enterprise.md)

---

## Configuration

```python
from spanforge.sdk.config import load_config_file, validate_config

cfg = load_config_file()        # loads spanforge.toml
errors = validate_config(cfg)   # returns list of errors
```

Key config fields: `enabled`, `project_id`, `endpoint`, `sandbox`, `services`,
`pii`, `secrets`, `local_fallback`.

[Configuration guide →](configuration.md)

---

## Testing

```python
from spanforge.testing_mocks import mock_all_services

with mock_all_services() as mocks:
    # all sf_* singletons replaced with in-memory mocks
    mocks["sf_pii"].configure_response("scan", custom_result)
    mocks["sf_audit"].assert_called("append")
```

[Testing guide →](api/testing.md)

---

## CLI

```bash
spanforge doctor      # environment diagnostics
spanforge check       # quick health check
spanforge validate    # config validation
spanforge scan FILE   # PII scan
```

[CLI reference →](cli.md)
