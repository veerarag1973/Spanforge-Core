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
| `sf_identity` | `MockIdentityClient` | `SFIdentityClient` |
| `sf_pii` | `MockPIIClient` | `SFPIIClient` |
| `sf_secrets` | `MockSecretsClient` | `SFSecretsClient` |
| `sf_audit` | `MockAuditClient` | `SFAuditClient` |
| `sf_cec` | `MockCECClient` | `SFCECClient` |
| `sf_observe` | `MockObserveClient` | `SFObserveClient` |
| `sf_alert` | `MockAlertClient` | `SFAlertClient` |
| `sf_gate` | `MockGateClient` | `SFGateClient` |
| `sf_config` | `MockConfigClient` | `SFConfigClient` |
| `sf_trust` | `MockTrustClient` | `SFTrustClient` |
| `sf_security` | `MockSecurityClient` | `SFSecurityClient` |

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

### `MockIdentityClient`

Replaces `SFIdentityClient`.

| Method | Default Return |
|--------|---------------|
| `issue_token(**kwargs)` | `{"token": "mock-token", "expires_in": 3600}` |
| `validate_token(token)` | `{"valid": True, "sub": "mock-subject"}` |
| `revoke_token(token)` | `{"revoked": True}` |
| `rotate_keys()` | `{"rotated": True}` |

### `MockPIIClient`

Replaces `SFPIIClient`.

| Method | Default Return |
|--------|---------------|
| `scan(payload)` | `{"entities": [], "clean": True}` |
| `scan_text(text)` | `{"entities": [], "clean": True}` |
| `redact(payload)` | `types.SimpleNamespace(event=payload, redacted=False)` |
| `get_entity_types()` | `["PERSON", "EMAIL", "PHONE", "SSN", ...]` |

### `MockSecretsClient`

Replaces `SFSecretsClient`.

| Method | Default Return |
|--------|---------------|
| `get(key)` | `"mock-secret-value"` |
| `put(key, value)` | `{"stored": True}` |
| `delete(key)` | `{"deleted": True}` |
| `list_keys()` | `[]` |

### `MockAuditClient`

Replaces `SFAuditClient`.

| Method | Default Return |
|--------|---------------|
| `append(record, **kwargs)` | `{"record_id": "mock-id", "chain_hash": "mock-hash"}` |
| `verify_chain(**kwargs)` | `{"valid": True, "records": 0}` |
| `get_record(record_id)` | `None` |

### `MockCECClient`

Replaces `SFCECClient`.

| Method | Default Return |
|--------|---------------|
| `build_bundle(**kwargs)` | `types.SimpleNamespace(bundle_id="mock-bundle", zip_path="/tmp/mock.zip")` |
| `generate_dpa(**kwargs)` | `types.SimpleNamespace(document_id="mock-dpa")` |
| `validate_attestation(evidence)` | `{"valid": True}` |

### `MockObserveClient`

Replaces `SFObserveClient`.

| Method | Default Return |
|--------|---------------|
| `emit_span(name, attributes)` | `"mock-span-id"` |
| `add_annotation(name, data, **kwargs)` | `"mock-annotation-id"` |
| `get_annotations(query, start, end)` | `[]` |
| `export_spans(spans, **kwargs)` | `types.SimpleNamespace(exported_count=len(spans), backend="mock")` |

### `MockAlertClient`

Replaces `SFAlertClient`.

| Method | Default Return |
|--------|---------------|
| `send(alert_type, message)` | `{"sent": True}` |
| `send_batch(alerts)` | `{"sent": len(alerts)}` |

### `MockGateClient`

Replaces `SFGateClient`.

| Method | Default Return |
|--------|---------------|
| `evaluate(gate_id, **kwargs)` | `types.SimpleNamespace(verdict="PASS", message="mock gate pass")` |
| `evaluate_batch(gate_id, payloads)` | `[SimpleNamespace(verdict="PASS", ...)]` |

### `MockConfigClient`

Replaces `SFConfigClient`.

| Method | Default Return |
|--------|---------------|
| `validate(**kwargs)` | `{"valid": True, "errors": []}` |
| `get(key)` | `None` |
| `set(key, value)` | `{"updated": True}` |

### `MockTrustClient`

Replaces `SFTrustClient`.

| Method | Default Return |
|--------|---------------|
| `get_scorecard(**kwargs)` | `{"overall": 0.95, "dimensions": {}}` |
| `get_badge(**kwargs)` | `types.SimpleNamespace(overall=0.95, colour_band="green")` |
| `get_scores(**kwargs)` | `{}` |

### `MockSecurityClient`

Replaces `SFSecurityClient`.

| Method | Default Return |
|--------|---------------|
| `owasp_audit(**kwargs)` | `{"categories": [], "pass_": True}` |
| `threat_model(**kwargs)` | `{"threats": [], "mitigations": []}` |
| `dependency_scan(**kwargs)` | `{"vulnerabilities": [], "clean": True}` |
| `scan_logs(**kwargs)` | `{"secrets_found": 0, "clean": True}` |

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
        mocks["sf_alert"].assert_not_called("send")
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
