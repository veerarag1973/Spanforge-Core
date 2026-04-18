# Migration Guide: SpanForge v5 → v6

> **DX-012 · Priority P0**

This guide walks you through upgrading from SpanForge v5 (schema v5) to
SpanForge v6 (schema v6, SDK 2.x).

---

## Summary of Breaking Changes

| Area | v5 | v6 | Action |
|------|----|----|--------|
| Schema version | `schema_version: "5"` | `schema_version: "6"` | Run `spanforge migrate` |
| Config format | `spanforge.ini` / env-only | `spanforge.toml` | Run `spanforge init` |
| PII scanner | `sf_pii.check()` | `sf_pii.scan()` / `sf_pii.scan_text()` | Rename calls |
| Audit append | `sf_audit.log(record)` | `sf_audit.append(record, schema_key)` | Add `schema_key` arg |
| Gate evaluate | `sf_gate.check(gate_id, data)` | `sf_gate.evaluate(gate_id, payload)` | Rename `data` → `payload` |
| Trust | N/A (new in v6) | `sf_trust.get_scorecard()` | No migration needed |
| Enterprise | N/A (new in v6) | `sf_enterprise.*` | No migration needed |
| Security | N/A (new in v6) | `sf_security.*` | No migration needed |
| Sandbox mode | N/A | `sandbox = true` in config | No migration needed |
| Testing mocks | Manual patching | `from spanforge.testing_mocks import mock_all_services` | Adopt new API |
| CLI doctor | N/A | `spanforge doctor` | No migration needed |

---

## Step-by-Step Migration

### 1. Update the Package

```bash
pip install --upgrade spanforge>=2.0.0
```

### 2. Migrate Schema

Run the built-in migration tool:

```bash
spanforge migrate --from 5 --to 6 --dir ./events/
```

This rewrites JSONL event files in-place, adding the new required fields and
updating `schema_version` from `"5"` to `"6"`.

### 3. Update Configuration

**v5** used environment variables or `spanforge.ini`.  **v6** uses
`spanforge.toml`:

```bash
spanforge init --service-name my-service
```

This generates a `spanforge.toml` with sensible defaults.  Map your old env
vars:

| Old env var | New TOML key |
|-------------|-------------|
| `SF_ENDPOINT` | `endpoint` under `[spanforge]` |
| `SF_PROJECT` | `project_id` under `[spanforge]` |
| `SF_PII_ENABLED` | `enabled` under `[spanforge.pii]` |

Environment overrides still work with the `SPANFORGE_` prefix (e.g.
`SPANFORGE_ENDPOINT`).

### 4. Update PII Calls

```python
# v5
result = sf_pii.check(payload)

# v6
result = sf_pii.scan(payload)        # structured dict scan
result = sf_pii.scan_text("hello")   # plain-text scan
```

### 5. Update Audit Calls

```python
# v5
sf_audit.log(record)

# v6 — schema_key is now required
sf_audit.append(record, schema_key="my_event_v1")
```

### 6. Update Gate Calls

```python
# v5
result = sf_gate.check("gate-id", data=payload)

# v6
result = sf_gate.evaluate("gate-id", payload=payload)
# result.verdict is now "PASS" / "FAIL" (was boolean)
```

### 7. Validate

```bash
spanforge validate           # validate config
spanforge check              # health check
spanforge doctor             # full environment diagnostic
```

---

## Deprecated APIs

The following v5 APIs are deprecated and will be removed in v7:

| Deprecated | Replacement |
|-----------|-------------|
| `sf_pii.check()` | `sf_pii.scan()` |
| `sf_audit.log()` | `sf_audit.append()` |
| `sf_gate.check()` | `sf_gate.evaluate()` |
| `spanforge check-compat` | `spanforge doctor` |

Run `spanforge list-deprecated` to see all deprecated symbols in your codebase.

---

## Rollback

If you need to rollback:

```bash
pip install spanforge==1.x.x   # last v5-compatible release
spanforge migrate --from 6 --to 5 --dir ./events/
```

---

## FAQ

**Q: Can I run v5 and v6 side-by-side?**
No. The SDK is a singleton — only one version can be active per process.
Use schema versioning (`schema_key`) to process events from both versions.

**Q: Do I need to re-sign my audit chain?**
No. The migration preserves existing HMAC signatures. New records use the
v6 signing algorithm, which is backward-compatible with v5 chain verification.

**Q: What about my gate YAML files?**
Gate YAML format is unchanged. No migration needed.
