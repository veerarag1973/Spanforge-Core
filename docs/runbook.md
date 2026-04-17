# SpanForge Operations Runbook

## Overview

This runbook covers day-to-day operational tasks for SpanForge in production.

---

## 1. Health Check

### CLI
```bash
spanforge audit check-health audit.jsonl
```

Checks:
- File exists and is readable
- Events parse as valid JSON
- Chain integrity (signatures, linkage)
- Key expiry status
- Tombstone count

### HTTP
```bash
curl http://localhost:8888/health
curl http://localhost:8888/ready
```

---

## 2. Key Rotation

### Scheduled Rotation
```bash
export SPANFORGE_SIGNING_KEY="current-key"
export SPANFORGE_NEW_SIGNING_KEY="new-production-key-v2"
spanforge audit rotate-key audit.jsonl --reason "quarterly rotation"
# Then update SPANFORGE_SIGNING_KEY to the new key value
export SPANFORGE_SIGNING_KEY="new-production-key-v2"
```

### Emergency Rotation (Key Compromise)
```bash
# 1. Generate a new key
python -c "import secrets; print(secrets.token_hex(32))"

# 2. Rotate
export SPANFORGE_NEW_SIGNING_KEY="<new-key>"
spanforge audit rotate-key audit.jsonl --reason "emergency: key compromise"

# 3. Update all services
export SPANFORGE_SIGNING_KEY="<new-key>"
```

---

## 3. Chain Verification

```bash
# Full chain verification
spanforge audit-chain audit.jsonl

# Check output for:
# - "Chain is valid" = all good
# - "Tampered events" = investigate immediately
# - "Gap events" = possible deletions
```

---

## 4. GDPR Subject Erasure

```bash
spanforge audit erase audit.jsonl \
  --subject-id "user-12345" \
  --erased-by "dpo@company.com" \
  --reason "GDPR Art.17 right to erasure" \
  --output audit_erased.jsonl
```

Post-erasure verification:
```bash
spanforge audit-chain audit_erased.jsonl
```

---

## 5. PII Scanning

```bash
# Text report
spanforge scan audit.jsonl

# JSON report (for CI/CD pipelines)
spanforge scan audit.jsonl --format json
```

Exit codes:
- `0` = no PII found
- `1` = PII detected (review required)
- `2` = file error

---

## 5a. Secrets Scanning

Scan source files, configuration files, or any text for credentials before
they are committed or deployed.

```bash
# Scan a single file (text output)
spanforge secrets scan config.env

# JSON report (CI/CD pipelines)
spanforge secrets scan src/settings.py --format json

# SARIF output (GitHub Code Scanning)
spanforge secrets scan . --format sarif > secrets.sarif

# Redacted output (review without exposing values)
spanforge secrets scan .env --redact
```

Exit codes:
- `0` = no secrets detected
- `1` = secrets detected (review required)
- `2` = file error

### Incident Response: Secret Detected in Source

If `spanforge secrets scan` exits with code `1` or `SFSecretsBlockedError` is raised:

1. **Do NOT commit or push** the affected file.
2. **Identify the secret type** from the scan output — auto-blocked types
   (`BEARER_TOKEN`, `AWS_ACCESS_KEY`, `GCP_SERVICE_ACCOUNT`, `PEM_PRIVATE_KEY`,
   `SSH_PRIVATE_KEY`, `HC_API_KEY`, `SF_API_KEY`, `GITHUB_PAT`, `STRIPE_LIVE_KEY`,
   `NPM_TOKEN`) require immediate credential rotation.
3. **Rotate the credential** via the issuing service before proceeding.
4. **Remove from history** if the secret was already committed:
   ```bash
   # Remove the file from git history (requires BFG or git-filter-repo)
   git filter-repo --path config.env --invert-paths
   # Force-push after team notification
   git push --force-with-lease
   ```
5. **Add to allowlist** only if the value is a known test placeholder:
   ```shell
   export SPANFORGE_SECRETS_ALLOWLIST="YOUR_KEY_HERE,example_token"
   ```

### Pre-commit hook setup

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/veerarag1973/spanforge
    rev: v2.0.3
    hooks:
      - id: spanforge-secrets-scan
```

Install and run:
```bash
pip install pre-commit
pre-commit install
pre-commit run spanforge-secrets-scan --all-files
```

---

## 6. Schema Migration

```bash
spanforge migrate audit_v1.jsonl --output audit_v2.jsonl
```

Always verify after migration:
```bash
spanforge audit-chain audit_v2.jsonl
```

---

## 7. Compliance Reports

### Generate Evidence Package
```bash
spanforge compliance generate \
  --events-file audit.jsonl \
  --org-id "org-prod" \
  --org-secret "$SPANFORGE_SIGNING_KEY"
```

### Generate PDF Report
```bash
spanforge compliance report \
  --events-file audit.jsonl \
  --format pdf \
  --sign \
  --output compliance_q1.pdf
```

### Validate Attestation
```bash
spanforge compliance validate-attestation audit.jsonl
```

---

## 8. Air-Gapped Deployment

See [Air-Gapped Deployment Guide](deployment/air-gapped.md).

```bash
export SPANFORGE_NO_EGRESS=1
# All outbound exporter calls will be blocked
```

---

## 9. Monitoring

### Metrics Endpoint
```bash
curl http://localhost:8888/metrics
# Returns:
# spanforge_traces_in_store 42
# spanforge_events_in_store 1337
# spanforge_export_errors_total 0
```

### Compliance Dashboard
```bash
spanforge serve --port 8888 --file audit.jsonl
# Navigate to http://localhost:8888/compliance
```

---

## 10. Incident Response: Chain Tamper Detected

**Severity:** Critical  
**Trigger:** `spanforge audit check-health` reports chain integrity FAIL, or `verify_chain()` returns `tampered_count > 0`.

### Immediate Actions

1. **Isolate** — Stop ingesting new events to the affected file.
2. **Preserve evidence** — Copy the affected JSONL file to an immutable store before any remediation.
3. **Identify scope** — Run full verification to get the exact tampered event IDs:
   ```bash
   spanforge audit verify --input audit.jsonl --key "$SPANFORGE_SIGNING_KEY"
   ```
4. **Time-bound the window** — Compare timestamps of the first and last tampered events to determine the exposure window.

### Investigation

1. Check system access logs for the time window around the tampered events.
2. Verify no key leak occurred (see §11 below).
3. Determine whether the tampering was accidental (e.g. manual file edits) or malicious.

### Remediation

1. If the original events exist in a backup or upstream exporter, restore them.
2. Re-sign the restored chain:
   ```bash
   export SPANFORGE_SIGNING_KEY="$KEY"
   spanforge audit rotate-key restored.jsonl --reason "chain tamper remediation"
   ```
3. Verify the restored chain passes:
   ```bash
   spanforge audit check-health restored.jsonl
   ```

### Post-Incident

- File an incident report documenting root cause, timeline, and remediation steps.
- Review file-system permissions on audit JSONL files.
- Consider enabling append-only storage (e.g. WORM blob storage).

---

## 11. Incident Response: Key Compromise

**Severity:** Critical  
**Trigger:** Signing key material found in logs, source code, or was accessed by an unauthorized party.

### Immediate Actions

1. **Rotate immediately** — Generate a new key and rotate all chains:
   ```bash
   NEW_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
   export SPANFORGE_NEW_SIGNING_KEY="$NEW_KEY"
   spanforge audit rotate-key audit.jsonl --reason "key compromise"
   ```
2. **Revoke the old key** — Remove it from all secret stores, environment variables, and CI/CD pipelines.
3. **Verify rotation** — Confirm the rotated chain is valid with the new key:
   ```bash
   export SPANFORGE_SIGNING_KEY="$NEW_KEY"
   spanforge audit check-health audit.jsonl
   ```

### Investigation

1. Determine how the key was leaked (logs, code, shared chat, compromised host).
2. Audit all events signed between the last known-good time and the rotation to determine if any were forged.
3. Cross-reference with the chain tamper detection (§10) — if tampered events exist during the exposure window, treat them as potentially forged.

### Remediation

1. Propagate the new key to all services that read or write audit events.
2. Update `SPANFORGE_SIGNING_KEY_EXPIRES_AT` if using key expiry.
3. Set `SPANFORGE_SIGNING_KEY_MIN_BITS` to enforce stronger keys (e.g. `512`).

### Post-Incident

- Conduct a root-cause analysis and update access control policies.
- Enable automated key rotation on a schedule (e.g. quarterly).
- Review key storage practices — prefer vault-backed secrets over environment variables.

---

## 12. Incident Response: PII Leak Detected

**Severity:** High  
**Trigger:** `spanforge scan` detects PII in production audit events, or `check-health` reports PII hits.

### Immediate Actions

1. **Identify affected events** — Run a PII scan to locate all events containing PII:
   ```bash
   spanforge scan audit.jsonl --format json > pii_report.json
   ```
2. **Classify the data** — Check sensitivity levels in the scan report (`high` = SSN/credit card, `medium` = email/phone, `low` = IP).
3. **Stop further leakage** — Ensure redaction is active at the ingestion layer:
   ```python
   from spanforge.redact import Redactable
   redactable = Redactable(payload)
   redactable.redact()
   ```

### Investigation

1. Determine how PII bypassed the redaction layer (missing `scan_raw=True`, skipped fields, new payload structure).
2. Identify all downstream consumers that received unredacted events.
3. Determine regulatory notification requirements (GDPR 72-hour window, CCPA, HIPAA).

### Remediation

1. **Redact in-place** — If the storage format allows, re-process the affected events:
   ```bash
   # For individual subject data, use GDPR erasure
   spanforge audit erase audit.jsonl \
     --subject-id "affected-user" \
     --erased-by "security-team" \
     --reason "PII leak remediation" \
     --output audit_clean.jsonl
   ```
2. **Purge downstream** — Notify downstream consumers to delete or redact the affected events.
3. **Re-sign the chain** after any modifications:
   ```bash
   spanforge audit rotate-key audit_clean.jsonl --reason "PII remediation re-sign"
   ```

### Post-Incident

- Update PII detection patterns if new PII types were missed.
- Add `--fail-on-match` to CI/CD pipelines:
  ```bash
  spanforge scan audit.jsonl --fail-on-match
  ```
- Review the `contains_pii(scan_raw=True)` setting in pre-export hooks.
- File a breach notification if required by applicable regulations.
```bash
curl http://localhost:8888/compliance/summary
```

The `/compliance/summary` response includes:
- `explanation_coverage_pct` — percentage of decision events (`llm.trace.*`,
  `hitl.*`) with matching `explanation.*` events.
- Model registry metadata (`model_owner`, `model_risk_tier`, `model_status`,
  `model_warnings`) when models are registered.

---

## 10. Troubleshooting

### Events Not Appearing
1. Check exporter configuration: `spanforge dev config`
2. Verify signing key is set: `echo $SPANFORGE_SIGNING_KEY`
3. Check for export errors in metrics endpoint

### Chain Verification Fails
1. Run `spanforge audit-chain <file>` to identify the first tampered event
2. Check for out-of-order writes (concurrent access without locking)
3. If tombstones are present, they're expected after GDPR erasure

### Key Expiry Warnings
```python
from spanforge.signing import check_key_expiry
result = check_key_expiry("2025-12-31T00:00:00Z")
print(result)  # ("valid", days_remaining) or ("expired", days_past)
```

---

## 11. Backup & Recovery

### Backup
```bash
cp audit.jsonl audit.jsonl.bak
# Or use append-only exporter with WORM backend
```

### Recovery from Corruption
1. Identify the last valid event: `spanforge audit-chain audit.jsonl`
2. Truncate to the last valid event
3. Re-sign from that point forward

---

## Quick Reference

| Task                      | Command                                         |
|---------------------------|--------------------------------------------------|
| Health check              | `spanforge audit check-health <file>`            |
| Verify chain              | `spanforge audit-chain <file>`                   |
| Rotate key                | `spanforge audit rotate-key <file>`              |
| Erase subject             | `spanforge audit erase <file> --subject-id X`    |
| Scan for PII              | `spanforge scan <file>`                          |
| Scan for secrets          | `spanforge secrets scan <file>`                  |
| Migrate schema            | `spanforge migrate <file>`                       |
| Compliance report         | `spanforge compliance report --events-file <f>`  |
| Start viewer              | `spanforge ui`                                   |
| View config               | `spanforge dev config`                           |
