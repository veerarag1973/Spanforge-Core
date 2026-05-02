# GA Release Notes

This page summarizes the Phase 0 through Phase 7 GA spine for the May 2, 2026 release.

---

## v1.0.1 — Production Hardening (2026-05-02)

**Phase 1B/1C: Explain model types, Scope circuit breaker, Validate enforcement modes, RBAC standard roles + JWT/YAML, Training Data Compliance Scanner**

### `sf_explain` (1B-1)

- `ExplainModelType` enum — LLM, RAG, MULTI_AGENT, CLASSIFIER, EMBEDDING. Pass as `model_type` on `generate()`.
- Retry + timeout on `_emit_signed_record()` — `max_retries=3`, `emit_timeout_sec=5.0`. Fail-safe: emit errors never propagate.

### `sf_scope` (1B-2)

- `ACTION_CATEGORIES` — five canonical categories (read / write / execute / admin / stream) as a module-level dict.
- `resolve_action_category(action)` static method.
- Circuit-breaker fail-secure: `cb_threshold=5`, `cb_reset_seconds=30.0`. When open, `evaluate()` returns `block` immediately.

### `sf_validate` (1C-1 + 1C-4)

- `EnforcementMode` — STRICT / LENIENT / WARN / CORRECT.
- `ValidationResult` dataclass, `enforce_event()`, `correct_event()`.
- `sign_event_hmac(event, key)` — HMAC-SHA256 event signing.
- `scan_dataset()` training data compliance scanner — PII field-name detection, PII value regex matching, required-field checks.
- `DatasetScanFinding` + `DatasetScanReport` dataclasses.
- CLI: `spanforge validate --dataset PATH [--fail-on-violations] [--required-fields FIELDS] [--format json|text]`.

### `sf_rbac` (1C-2)

- `STANDARD_ROLE_MATRIX` — 10 canonical actor types (viewer / editor / admin / operator / auditor / developer / deployer / reviewer / service_account / superadmin).
- `register_actor_from_yaml(yaml_str)` — YAML manifest registration.
- `register_actor_from_jwt(token, *, verify, secret)` — JWT claim extraction and registration.

### Tests

- **6 541 passed**, 0 failed, 19 skipped (99 new tests vs v1.0.0). Combined branch+statement coverage: **90%** (25 757 / 28 762); statement coverage: **91%** (20 591 / 22 574).
- 22 new E2E CLI tests across 7 workflow classes (Flows 26–32) in `tests/test_e2e_cli.py`: `TestAuditEraseWorkflow` (4), `TestAuditCheckHealthWorkflow` (5), `TestAuditVerifyWorkflow` (3), `TestAuditRotateKeyWorkflow` (3), `TestTrustBadgeWorkflow` (3), `TestTrustGateWorkflow` (3), `TestDoctorWorkflow` (1).

---

## v1.0.0 — Initial GA Release (2026-04-28)

## What GA Means

SpanForge GA is the runtime governance and compliance control plane for enterprise and regulated AI systems.

The GA path is:

`runtime request -> policy decision -> signed evidence -> operator review -> export package`

## Included at GA

Core runtime-governance services:

- `SFExplainClient`
- `SFScopeClient`
- `SFRBACClient`
- `SFRAGClient`
- `SFLineageClient`

Privacy and PII protection:

- `SFPIIClient` — Presidio NLP backend (`spanforge[presidio]`) covering 15 entity types with GA-verified accuracy: false-positive rate < 0.5 % and true-positive rate ≥ 95 % (achieved 100 % on 25-sample corpus). Includes custom recognizers for phone, AADHAAR, PAN, and UK National Insurance numbers, plus post-filters to suppress lowercase-PERSON and OID-fragment false positives.

Supporting control-plane services:

- `SFPolicyClient`
- `SFOperatorClient`
- `SFEnterpriseClient`

Enterprise integration and export story:

- OpenAI, Anthropic, Azure OpenAI, LangChain, and LangGraph paths
- OTLP, JSONL, SIEM, and OpenInference-compatible export paths
- self-hosted and air-gapped deployment guidance
- operator and enterprise evidence packaging

## Deferred or Explicitly Not Central to GA

- `SFBiasClient` only if already solid
- `SFRollbackClient`
- `SFCanaryClient`
- `SFWatermarkClient`

## Recommended GA Entry Points

- [Runtime Governance GA Guide](runtime-governance.md)
- [Runtime Governance Contracts](runtime-governance-contracts.md)
- [Replay, Simulation, and Calibration](replay-simulation.md)
- [Evidence Export Guide](evidence-export.md)
- [Enterprise Integrations](enterprise-integrations.md)
- [Reference Architectures](reference-architectures.md)
- [Runtime Governance Demo](demos/runtime-governance-demo.md)
- [Enterprise Evidence Demo](demos/enterprise-evidence-demo.md)
