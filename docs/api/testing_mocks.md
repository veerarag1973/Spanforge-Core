# `spanforge.testing_mocks` — Mock Service Clients

> **DX-003 · Phase 12 · Added in v2.0.11**

Zero-network mock replacements for all 11 SpanForge SDK service clients.
Every mock records calls, supports custom return values, and installs/restores
automatically via `mock_all_services()`.

---

## Installation

No extra install required — `testing_mocks` is part of the core `spanforge`
package:

```python
from spanforge.testing_mocks import mock_all_services
```

---

## `mock_all_services()`

```python
@contextmanager
def mock_all_services() -> Generator[dict[str, _MockBase], None, None]:
```

Context manager that patches all 11 singleton service clients in
`spanforge.sdk` with mock instances.  On exit the original clients are
restored.

```python
from spanforge.testing_mocks import mock_all_services

def test_pipeline():
    with mock_all_services() as mocks:
        run_pipeline()
        mocks["sf_pii"].assert_called("scan")
        mocks["sf_audit"].assert_called("append")
```

### Returned dict keys

| Key | Mock Class | Real Client |
|-----|-----------|-------------|
| `sf_identity` | `MockSFIdentity` | `SFIdentityClient` |
| `sf_pii` | `MockSFPII` | `SFPIIClient` |
| `sf_secrets` | `MockSFSecrets` | `SFSecretsClient` |
| `sf_audit` | `MockSFAudit` | `SFAuditClient` |
| `sf_cec` | `MockSFCEC` | `SFCECClient` |
| `sf_observe` | `MockSFObserve` | `SFObserveClient` |
| `sf_alert` | `MockSFAlert` | `SFAlertClient` |
| `sf_gate` | `MockSFGate` | `SFGateClient` |
| `sf_enterprise` | `MockSFEnterprise` | `SFEnterpriseClient` |
| `sf_trust` | `MockSFTrust` | `SFTrustClient` |
| `sf_security` | `MockSFSecurity` | `SFSecurityClient` |

---

## `_MockBase` — Base Class

All mock clients inherit from `_MockBase`, which provides:

### Properties & Methods

| Member | Signature | Description |
|--------|-----------|-------------|
| `.calls` | `dict[str, list[tuple]]` | Recorded calls per method name. |
| `.call_count()` | `call_count(method: str) -> int` | Number of times `method` was called. |
| `.assert_called()` | `assert_called(method: str)` | Raise `AssertionError` if `method` was never called. |
| `.assert_not_called()` | `assert_not_called(method: str)` | Raise `AssertionError` if `method` **was** called. |
| `.configure_response()` | `configure_response(method: str, response: Any)` | Set a custom return value for all future calls. |
| `.reset()` | `reset()` | Clear all recorded calls and configured responses. |

---

## Mock Classes

### `MockSFIdentity`

Replaces `SFIdentityClient`.

| Method | Default Return |
|--------|---------------|
| `issue_api_key(**kwargs)` | `APIKeyBundle(api_key="sf_test_mock_key_...", ...)` |
| `verify_token(jwt)` | `JWTClaims(subject="mock-subject", scopes=["*"], ...)` |
| `revoke_key(key_id)` | `None` |
| `rotate_key(key_id)` | `APIKeyBundle(...)` |
| `create_session(api_key)` | `"mock.session.jwt"` |
| `refresh_token()` | `"mock.refreshed.jwt"` |
| `introspect(token)` | `TokenIntrospectionResult(active=True, ...)` |
| `get_status()` | `{"status": "ok", "mode": "local", ...}` |

### `MockSFPII`

Replaces `SFPIIClient`.

| Method | Default Return |
|--------|---------------|
| `scan(payload, **kwargs)` | `SFPIIScanResult(hits=[], scanned=1)` |
| `scan_text(text, **kwargs)` | `PIITextScanResult(entities=[], detected=False, ...)` |
| `redact(event, **kwargs)` | `SFPIIRedactResult(event=event, redaction_count=0, ...)` |
| `contains_pii(event, **kwargs)` | `False` |
| `anonymize(text, **kwargs)` | `SFPIIAnonymizeResult(text=text, replacements=0, ...)` |
| `scan_batch(texts, **kwargs)` | `[PIITextScanResult(...) for t in texts]` |
| `get_status()` | `PIIStatusInfo(status="ok", ...)` |

### `MockSFSecrets`

Replaces `SFSecretsClient`.

| Method | Default Return |
|--------|---------------|
| `scan(text, **kwargs)` | `None` |
| `scan_batch(texts, **kwargs)` | `[]` |
| `get_status()` | `{"status": "ok", "patterns_loaded": 0}` |

### `MockSFAudit`

Replaces `SFAuditClient`.

| Method | Default Return |
|--------|---------------|
| `append(record, schema_key, **kwargs)` | `AuditAppendResult(record_id="mock-record-id", ...)` |
| `sign(record)` | `SignedRecord(record_id="mock-id", ...)` |
| `verify_chain(records, **kwargs)` | `{"valid": True, "gaps": []}` |
| `export(schema_key, **kwargs)` | `[]` |
| `get_trust_scorecard(project_id, **kwargs)` | `None` |
| `get_status()` | `AuditStatusInfo(status="ok", ...)` |
| `close()` | `None` |

### `MockSFCEC`

Replaces `SFCECClient`.

| Method | Default Return |
|--------|---------------|
| `build_bundle(project_id, date_range, **kwargs)` | `BundleResult(bundle_id="mock-bundle", zip_path="mock.zip", ...)` |
| `verify_bundle(zip_path)` | `BundleVerificationResult(overall_valid=True, ...)` |
| `generate_dpa(project_id, controller_details, processor_details, **kwargs)` | `DPADocument(document_id="mock-dpa", ...)` |
| `get_status()` | `CECStatusInfo(status="ok", ...)` |

### `MockSFObserve`

Replaces `SFObserveClient`.

| Method | Default Return |
|--------|---------------|
| `emit_span(name, attributes, **kwargs)` | `{"span_id": "mock-span-id"}` |
| `add_annotation(event_type, payload, **kwargs)` | `"mock-annotation-id"` |
| `get_annotations(event_type, from_dt, to_dt, **kwargs)` | `[]` |
| `export_spans(spans, **kwargs)` | `ExportResult(exported_count=len(spans), backend="mock", ...)` |
| `healthy` *(property)* | `True` |
| `last_export_at` *(property)* | `None` |

### `MockSFAlert`

Replaces `SFAlertClient`.

| Method | Default Return |
|--------|---------------|
| `publish(topic, payload, **kwargs)` | `PublishResult(alert_id="mock-alert-id", routed_to=[], suppressed=False)` |
| `register_topic(topic, description, **kwargs)` | `None` |
| `acknowledge(alert_id)` | `True` |
| `get_alert_history(**kwargs)` | `[]` |
| `get_status()` | `AlertStatusInfo(status="ok", healthy=True, ...)` |
| `healthy` *(property)* | `True` |

### `MockSFGate`

Replaces `SFGateClient`.

| Method | Default Return |
|--------|---------------|
| `evaluate(gate_id, payload, **kwargs)` | `GateEvaluationResult(gate_id=gate_id, verdict="PASS", ...)` |
| `run_trust_gate(project_id, **kwargs)` | `TrustGateResult(verdict="PASS", pass_=True, ...)` |
| `evaluate_prri(project_id, **kwargs)` | `PRRIResult(verdict="GREEN", prri_score=95, allow=True, ...)` |
| `list_artifacts(gate_id, **kwargs)` | `[]` |
| `get_status()` | `GateStatusInfo(status="ok", ...)` |

### `MockSFEnterprise`

Replaces `SFEnterpriseClient`.

| Method | Default Return |
|--------|---------------|
| `register_tenant(project_id, org_id, **kwargs)` | `TenantConfig(project_id=..., org_id=..., ...)` |
| `get_tenant(project_id)` | `None` |
| `list_tenants()` | `[]` |
| `get_isolation_scope(project_id)` | `IsolationScope(org_id="mock-org", ...)` |
| `get_endpoint_for_project(project_id)` | `"http://localhost:8080"` |
| `configure_encryption(**kwargs)` | `EncryptionConfig()` |
| `get_status()` | `EnterpriseStatusInfo(status="ok")` |

### `MockSFTrust`

Replaces `SFTrustClient`.

| Method | Default Return |
|--------|---------------|
| `get_scorecard(project_id, **kwargs)` | `TrustScorecardResponse(overall_score=1.0, colour_band="green", ...)` |
| `get_history(project_id, **kwargs)` | `[]` |
| `get_badge(project_id)` | `TrustBadgeResult(overall=1.0, colour_band="green", svg="<svg/>", ...)` |
| `get_status()` | `TrustStatusInfo(status="ok", ...)` |

### `MockSFSecurity`

Replaces `SFSecurityClient`.

| Method | Default Return |
|--------|---------------|
| `run_owasp_audit(**kwargs)` | `SecurityAuditResult(categories={}, pass_=True, ...)` |
| `get_threat_model(service)` | `[]` |
| `add_threat(service, category, threat, mitigation, risk_level)` | `ThreatModelEntry(...)` |
| `scan_dependencies(**kwargs)` | `[]` |
| `audit_logs_for_secrets(log_lines)` | `0` |
| `run_full_scan(**kwargs)` | `SecurityScanResult(vulnerabilities=[], pass_=True, ...)` |
| `get_status()` | `{"status": "ok"}` |

---

## Examples

### Assert service interactions

```python
from spanforge.testing_mocks import mock_all_services

def test_audit_trail():
    with mock_all_services() as mocks:
        process_llm_request("What is AI?")

        mocks["sf_pii"].assert_called("scan")
        mocks["sf_audit"].assert_called("append")
        assert mocks["sf_observe"].call_count("emit_span") == 1
        mocks["sf_alert"].assert_not_called("publish")
```

### Custom responses for error paths

```python
def test_gate_blocks_high_risk():
    with mock_all_services() as mocks:
        mocks["sf_gate"].configure_response("evaluate", {
            "verdict": "FAIL",
            "message": "Hallucination score too high",
        })

        result = run_pipeline()
        assert result.blocked is True
```

### Reset between sub-tests

```python
def test_multiple_scenarios():
    with mock_all_services() as mocks:
        run_scenario_a()
        assert mocks["sf_pii"].call_count("scan") == 2

        mocks["sf_pii"].reset()

        run_scenario_b()
        assert mocks["sf_pii"].call_count("scan") == 1
```

---

## See Also

- [testing](testing.md) — `MockExporter`, `capture_events()`, `trace_store()`
- [sdk-reference](sdk-reference.md) — Full SDK client reference
- [Configuration](../configuration.md#sandbox-mode-phase-12) — Sandbox mode settings
- [CLI — doctor](../cli.md#doctor) — Environment diagnostics
