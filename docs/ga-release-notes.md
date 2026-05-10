# GA Release Notes

This page summarizes the Phase 0 through Phase 7 GA spine for the May 2, 2026 release.

---

## v1.0.1 — Production Hardening (2026-05-02 … 2026-05-08)

**Phase 1B/1C: Explain model types + full explain() API + @governed, Scope circuit breaker, Validate enforcement modes, RBAC standard roles + JWT/YAML, Training Data Compliance Scanner**

### `sf_explain` full production hardening (CARD 1B-1 · 2026-05-08)

- `ModelOutputType` enum — CLASSIFICATION, GENERATION, STRUCTURED, REJECTION, TOOL_CALL. Passed as `context["model_output_type"]` or auto-inferred from response shape.
- `EUAIActClause` dataclass — Article 13 (transparency) and Article 14 (human oversight) clauses emitted on every `ExplainRecord`. Article 14 `satisfied = confidence_score >= threshold`.
- `ExplainRecord` dataclass — canonical return type from `explain()`: `record_id`, `agent_id`, `model_output_type`, `decision_drivers`, `confidence_score`, `model_version`, `eu_ai_act_clauses`, `hmac_signature`, `timestamp`.
- `SFExplainClient.explain(response, context) → ExplainRecord` — production hot-path method. Infers output type → extracts decision drivers → maps EU AI Act clauses → HMAC-signs via `sf_audit.append()`. Emit failures never propagate (fail-safe).
- `@spanforge.governed` decorator — wraps any callable; auto-calls `sf_explain.explain()` on the return value. Supports bare `@governed` and parameterised `@governed(agent_id=..., confidence_threshold=...)` forms. Never raises on audit failure.
- 24 new unit tests in `tests/test_sdk_explain.py` (7 test classes); **6 565 passed** total, coverage **91.27%**.

### `sf_explain` model type hardening (1B-1 · 2026-05-02)

### `sf_scope` (1B-2)

- `ACTION_CATEGORIES` — five canonical categories (read / write / execute / admin / stream) as a module-level dict.
- `resolve_action_category(action)` static method.
- Circuit-breaker fail-secure: `cb_threshold=5`, `cb_reset_seconds=30.0`. When open, `evaluate()` returns `block` immediately.

### `sf_validate` (1C-1 + 1C-4)

- `EnforcementMode` — STRICT / LENIENT / WARN / CORRECT.
- `ValidationResult` dataclass, `enforce_event()`, `correct_event()`.
- `sign_event_hmac(event, key)` — HMAC-SHA256 event signing.
- `scan_dataset_compliance(path) → DatasetComplianceReport` — EU AI Act Article 10 file scanner (CARD 1C-4). Supports `.jsonl`, `.json`, `.csv`, `.txt`, `.parquet`. HMAC-signed report verifiable via `spanforge audit check-health`.
- `Article10Clause` + `DatasetComplianceReport` dataclasses with four Article 10 clause checks (PII density, consent coverage, provenance coverage, bias signal).
- CLI: `spanforge compliance validate-dataset PATH [--output report|json|pdf] [--no-sign]` and `spanforge validate --dataset PATH [--output report|json] [--no-sign]`.
- Legacy: `scan_dataset()`, `DatasetScanFinding`, `DatasetScanReport` remain available in `spanforge.validate` for backwards compatibility.

### `sf_rbac` (1C-2)

- `STANDARD_ROLE_MATRIX` — 10 canonical actor types (viewer / editor / admin / operator / auditor / developer / deployer / reviewer / service_account / superadmin).
- `register_actor_from_yaml(yaml_str)` — YAML manifest registration.
- `register_actor_from_jwt(token, *, verify, secret)` — JWT claim extraction and registration.

### Tests

- **6 565 passed**, 0 failed, 19 skipped (123 new tests vs v1.0.0). Combined branch+statement coverage: **91.27%**; threshold 90% ✅.
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
