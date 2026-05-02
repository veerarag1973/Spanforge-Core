# Changelog

All notable changes to spanforge are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and
this project adheres to [Semantic Versioning](https://semver.org/).

---

## [1.0.1] — 2026-05-02

**Phase 1B/1C SDK Production-Hardening: Explain model types, Scope circuit breaker, Validate enforcement modes, RBAC standard roles + JWT, Training Data Compliance Scanner**

---

### Added — `sf_explain` Production Hardening (1B-1)

- **`ExplainModelType` enum** — five typed model classifications for explanation records: `LLM`, `RAG`, `MULTI_AGENT`, `CLASSIFIER`, `EMBEDDING`. Pass as the new `model_type` parameter on `sf_explain.generate()` — stored under `metadata["model_type"]` in the signed record. Raw strings are also accepted for forward compatibility.
- **Retry + timeout on emit** — `SFExplainClient.__init__()` now accepts `max_retries: int = 3` and `emit_timeout_sec: float = 5.0`. The internal `_emit_signed_record()` retries with exponential back-off (1 s → 2 s → 4 s) and honours the deadline. Emit failures are logged at `WARNING` level and never propagate to the caller — a fail-safe guarantee that explainability tracking never breaks the request path.

### Added — `sf_scope` Circuit Breaker + Action Categories (1B-2)

- **`ACTION_CATEGORIES` dict** — module-level mapping of five canonical categories to frozensets of action strings:
  - `read` — `{"read", "list", "get", "describe", "view", "query", "fetch", "download"}`
  - `write` — `{"write", "create", "update", "delete", "patch", "put", "append", "insert", "remove"}`
  - `execute` — `{"execute", "run", "invoke", "trigger", "call", "dispatch", "submit"}`
  - `admin` — `{"admin", "configure", "deploy", "restart", "scale", "shutdown", "grant", "revoke", "manage"}`
  - `stream` — `{"stream", "subscribe", "publish", "consume", "emit", "broadcast"}`
- **`SFScopeClient.resolve_action_category(action)`** — static method returning the category name for a given action string, or `None` if the action is not in any category.
- **Circuit-breaker integration** — `SFScopeClient.__init__()` now accepts `cb_threshold: int = 5` and `cb_reset_seconds: float = 30.0`. When the internal emit store raises repeatedly, the circuit opens and `evaluate()` immediately returns `allowed=False` with `outcome="block"` and `reason="circuit breaker is open; failing secure"` — no manifest lookup, no network call. Circuit recovers automatically after `cb_reset_seconds`.

### Added — `sf_validate` Enforcement Modes + HMAC Signing (1C-1)

- **`EnforcementMode` enum** — four validation enforcement levels: `STRICT` (raise on first violation), `LENIENT` (raise with full violation list), `WARN` (log warnings, never raise), `CORRECT` (auto-correct and return corrected document without raising).
- **`ValidationResult` dataclass** — structured result from `enforce_event()`: `valid: bool`, `mode: EnforcementMode`, `violations: list[str]`, `corrected_doc: dict | None`.
- **`enforce_event(event, mode=EnforcementMode.STRICT) -> ValidationResult`** — dispatches to `validate_event()` and returns a `ValidationResult` according to the chosen mode.
- **`correct_event(doc: dict) -> dict`** — correction pass that: strips unknown top-level keys, removes `None`-valued optional fields (`trace_id`, `span_id`, `tags`, `checksum`, `signature`), and normalises `schema_version` to the current default when the value is unrecognised.
- **`sign_event_hmac(event: Event, key: str) -> Event`** — HMAC-SHA256 signing using stdlib `hmac`. Returns a new `Event` with `signature = "hmac-sha256:<64hex>"`. Raises `ValueError` on empty key.

### Added — `sf_rbac` Standard Role Matrix + YAML + JWT (1C-2)

- **`STANDARD_ROLE_MATRIX`** — module-level dict of ten canonical actor configurations:

  | Actor type | Roles | Notes |
  |------------|-------|-------|
  | `viewer` | `["viewer"]` | Read-only |
  | `editor` | `["viewer", "editor"]` | Read + write |
  | `admin` | `["viewer", "editor", "admin"]` | Full tenant control |
  | `operator` | `["viewer", "operator"]` | Operational tasks, no admin |
  | `auditor` | `["viewer", "auditor"]` | Audit access |
  | `developer` | `["viewer", "editor", "developer"]` | Dev access |
  | `deployer` | `["viewer", "deployer"]` | Deployment tasks |
  | `reviewer` | `["viewer", "reviewer"]` | Review / approve |
  | `service_account` | `["service_account"]` | Machine identity |
  | `superadmin` | `["viewer", "editor", "admin", "superadmin"]` | Super-admin |

- **`SFRBACClient.register_actor_from_yaml(yaml_str: str) -> RBACManifest`** — parses a YAML actor manifest and registers the actor. Requires `actor_id`; validates `roles` is a list when PyYAML is available. Falls back to a minimal stdlib YAML parser for flat manifests when PyYAML is not installed.
- **`SFRBACClient.register_actor_from_jwt(token, *, verify=False) -> RBACManifest`** — decodes the JWT payload segment (base64url, no signature verification in default mode), extracts `sub` → `actor_id`, `roles` → roles, `resource_roles` → resource roles, and remaining claims → metadata. Raises `ValueError` for malformed tokens or missing `sub`.

### Added — Training Data Compliance Scanner (1C-4)

- **`scan_dataset(rows, *, check_pii_field_names, check_pii_values, required_fields) -> DatasetScanReport`** — scans a list of record dicts for compliance issues. Detects:
  - PII field names (email, phone, SSN, passport, IP address, biometric, GPS, and 10+ more) via compiled regex.
  - PII values: email addresses, US phone numbers, and SSNs via distinct compiled patterns.
  - Required field violations when `required_fields` is supplied.
- **`DatasetScanFinding` dataclass** — `row` (1-based), `field`, `issue_type` (`pii_field_name` / `pii_value` / `schema_violation` / `parse_error`), `detail`.
- **`DatasetScanReport` dataclass** — `total_rows`, `total_findings`, `clean_rows`, `pii_hits`, `schema_violations`, `parse_errors`, `findings`.
- **`spanforge validate --dataset PATH`** CLI subcommand — scans a JSONL training dataset file:
  - `--fail-on-violations` exits with code 1 when any finding is present (CI-gate compatible).
  - `--required-fields FIELDS` comma-separated list of required fields per record.
  - `--format json` emits machine-readable JSON summary for pipeline consumption.
  - `--format text` (default) prints a human-readable summary with per-finding detail.

### Tests · 2026-05-02

- Full suite: **6 541 passed**, 0 failed, 19 skipped. Combined branch+statement coverage: **90%** (25 757 / 28 762); statement coverage: **91%** (20 591 / 22 574).
- 99 new tests across 6 test files:
  - `tests/test_sf_explain.py` — `TestExplainModelTypes` (8 tests): 5 model type enum variants, raw string acceptance, no-model-type preservation, fail-safe emit.
  - `tests/test_sf_scope.py` — `TestCircuitBreaker` (5 tests) + `TestActionCategories` (7 tests).
  - `tests/test_validate.py` — `TestEnforcementModes` (6) + `TestCorrectionPass` (5) + `TestSignEventHmac` (5).
  - `tests/test_sf_rbac.py` — `TestRegisterActorFromYAML` (5) + `TestRegisterActorFromJWT` (5) + `TestStandardRoleMatrix` (10).
  - `tests/test_dataset_scanner.py` — `TestScanDatasetClean` (3) + `TestScanDatasetPII` (7) + `TestScanDatasetRequiredFields` (2) + `TestScanDatasetSummaryCounts` (2) + `TestCLIDatasetScanner` (7).
  - `tests/test_e2e_cli.py` — Flows 26–32 (22 tests): `TestAuditEraseWorkflow` (4), `TestAuditCheckHealthWorkflow` (5), `TestAuditVerifyWorkflow` (3), `TestAuditRotateKeyWorkflow` (3), `TestTrustBadgeWorkflow` (3), `TestTrustGateWorkflow` (3), `TestDoctorWorkflow` (1). Full E2E coverage of `audit erase`, `audit check-health`, `audit verify`, `audit rotate-key`, `trust badge`, `trust gate`, and `doctor` CLI commands via in-process `main()` invocation.

---

## [1.0.0] — 2026-04-28

**F-series + Compliance value hardening: Async SDK, RAG Auto-instrumentation, Feedback Endpoint, Gate Coverage, Batch Exporter Tests, Compliance Readiness, Presidio NLP PII Backend**

---

### Added — Workflow Engine (CORE-15) · 2026-05-01

- **`spanforge.workflow` — Human-in-the-Loop Workflow Engine** — Orchestrates approval workflows for gate reviews, policy escalations, and compliance sign-offs. Every action is written to the tamper-evident audit trail as a `workflow.*` structured event.
  - **`WorkflowType.GATE_REVIEW`** — gate execution approval; requires `required_approvals` distinct approvals before the gate proceeds.
  - **`WorkflowType.POLICY_APPROVAL`** — new policy-version sign-off; requires security, compliance, and business roles to all approve.
  - **`WorkflowType.ESCALATION`** — drift detected or cost overrun; requires CTO/executive sign-off before auto-remediation proceeds.
  - **State machine**: `PENDING → ASSIGNED → IN_PROGRESS → APPROVED / REJECTED → CLOSED`, with automatic SLA promotion to `ESCALATED` via `check_and_auto_escalate()`.
  - **Role-based action matrix**: `compliance_officer` (approve, request_info, reject, delegate), `cto` (approve, override, escalate, reject, delegate), `security` (approve, reject, request_info, delegate), `business` (approve, reject, request_info, delegate), `system` (auto_approve, escalate, close).
  - `WorkflowEngine` accepts `workflow_type`, `trigger_event`, `assignees`, `sla_hours`, and `escalation_after_hours` at construction.
- 142 unit tests covering all workflow types, state transitions, role constraints, multi-approval quorum, delegation chains, and SLA auto-escalation paths.

### Added — CLI toolset expansion · 2026-05-01

- **`spanforge event create`** — Generate compliant test/sample events from the CLI. Flags: `--type` (event type), `--payload` (JSON string), `--count` (N events, default 1), `--output` (file path), `--format json|jsonl`. Auto-generates ULID event IDs. Useful for integration testing, CI seed data, and schema-validation pipelines.
- **`spanforge audit extract`** — Filter and extract events from a JSONL audit file. Flags: `--type` (filter by event type), `--since` / `--until` (ISO-8601 date range), `--limit` (max records), `--format jsonl|json`. Exit code 0 on success; 2 on file errors.
- **`spanforge audit cec generate`** — Generate a Compliance Evidence Chain (CEC) bundle ZIP from the CLI without the Python SDK. Produces a 6-file HMAC-signed archive: `manifest.json`, `compliance_mapping.json`, `trust_scorecard.json`, `audit_trail_sample.jsonl`, `ropa_article_30.json`, `timestamp.json`. Optional `--sign` flag activates HMAC bundle signing using `SPANFORGE_SIGNING_KEY`.
- **`spanforge audit gap-finder`** — Data quality audit for JSONL event logs. Detects: time gaps exceeding a configurable threshold, missing required event fields, and duplicate `event_id` values. Flags: `--threshold-minutes` (gap detection, default 60), `--required-fields`, `--format text|json`. Exit code 1 when gaps found — suitable as a CI quality gate.
- **`spanforge gate audit`** — Policy auditor for gate execution records. Audits a JSONL events file against gate policy rules. Falls back to 5 built-in schema rules when no gate YAML is present. Flags: `--gate` (target gate ID), `--format text|json`, `--fail-on-violation` (CI exit code 1 on any violation). Uses `GateRunner` when a gate YAML config is found.

### Enhanced — CLI command polish · 2026-05-01

- **`spanforge check`** expanded from 5 to 9 health checks. New checks include signing-key entropy, event-store capacity, export-pipeline throughput, and schema-registry coverage. Added `--verbose` flag that prints per-check timing in milliseconds.
- **`spanforge validate`** — new `--report summary|detailed` flag generates a human-readable validation report in addition to pass/fail output; new `--format text|json` flag (dest `output_format`) for CI pipeline integration.
- **`spanforge inspect`** — new `--format json|pretty|csv` flag. `pretty` mode adds ANSI colour-coded field types. `csv` mode exports all event fields as a single-row CSV suitable for spreadsheet import.
- **`spanforge stats`** — new `--group-by type|model|user` flag for dimension-based aggregation; new `--format table|json` flag for machine-readable output from CI dashboards.

### Tests · 2026-05-01

- Full suite: **6 136 passed**, 0 failed, 19 skipped.
- 142 new tests for `spanforge.workflow` (Workflow Engine, CORE-15).
- New CLI integration tests for `event create`, `audit extract`, `audit cec generate`, `audit gap-finder`, and `gate audit` subcommands.

---

### Added — Presidio NLP PII Backend (Phase 0 GA gate)

- **`spanforge.presidio_backend`** — new module providing a Presidio-powered PII detection backend. When `presidio-analyzer` and the `en_core_web_lg` spaCy model are installed (via `pip install "spanforge[presidio]"`), `sf_pii.scan_text()` and `sf_pii.anonymise()` automatically use the NLP engine for higher accuracy than the built-in regex fallback.
- **15-entity coverage**: `credit_card`, `crypto_address`, `email`, `iban`, `ip_address`, `person_name`, `phone`, `ssn`, `uk_nhs`, `us_driver_license`, `us_passport`, `aadhaar`, `pan`, `medical_license`, `uk_national_insurance`.
- **Custom PatternRecognizers** added for entity types not reliably covered by the default Presidio English model:
  - `PHONE_NUMBER`: 3 format patterns (`+1-NXX-NXX-XXXX`, `(NXX) NXX-XXXX`, `NXX-NXX-XXXX`) at 0.60–0.75 confidence.
  - `IN_AADHAAR`: 12-digit groups (`DDDD DDDD DDDD`), confidence 0.85.
  - `IN_PAN`: 5 uppercase letters + 4 digits + 1 uppercase letter, confidence 0.85.
  - `UK_NATIONAL_INSURANCE`: standard NI format, confidence 0.85.
- **Post-filters** applied after Presidio analysis to reduce false positives:
  - Lowercase-only `PERSON` matches are suppressed (common in technical identifiers and variable names).
  - IPv4 addresses are validated for 4-octet format (0–255 each) and checked for adjacent digit/dot characters to prevent OID substring false positives (e.g. `OID: 2.16.840.1.101.3.4.2.1`).
- **TF/transformers isolation**: `USE_TF=0` and `TRANSFORMERS_NO_TF=1` are set at module load time to prevent TensorFlow double-registration crash in Python 3.13.
- **`sdk/pii.py` `_scan_local()` fix**: `extra_patterns` regex hits are now merged with Presidio results. Previously, any user-supplied custom patterns were silently ignored when the Presidio backend was active.

### Fixed — PII accuracy test data

- Replaced invalid SSNs (`123-45-6789` and `987-65-4321`, which Presidio's built-in SSN validator rejects as test-number placeholders) with valid SSNs (`219-09-9999` and `231-45-7890`) in `tests/test_sf_pii.py` (4 occurrences) and `tests/test_phase0_scale.py` (2 occurrences).

### Tests — GA accuracy gates confirmed

- `TestPIIAccuracy::test_pii_fp_rate_under_half_percent` — **PASSED** (FP rate < 0.5% on 191-item clean corpus).
- `TestPIIAccuracy::test_pii_tp_rate_over_95_percent` — **PASSED** (100% = 25/25 known-PII samples detected).
- Full `tests/test_sf_pii.py`: **273 passed**, 1 skipped (Presidio-unavailability path; correctly skipped when Presidio is installed).
- Full suite: **6 138 passed**, 14 skipped, 0 failed. ruff 0 · mypy 0 · bandit 0.

---

### Added — Compliance value hardening (session 3)

- **Remediation guidance** — `_FRAMEWORK_CLAUSES` now includes `remediation_steps` for every clause across all six frameworks (SOC 2, HIPAA, GDPR, NIST AI RMF, EU AI Act, ISO 42001). Gap reports render each step as `> **Fix**: <steps>` in the Markdown output.
- **Markdown reports** — `ComplianceEvidencePackage.to_markdown()` method added. `spanforge compliance report` now accepts `--format markdown` (writes `<prefix>_report.md`) and `--format both` (writes both JSON and Markdown in one pass).
- **`spanforge compliance readiness` command** — scored pre-production checklist for any supported framework. Checks signing key, event store, evidence package generation, gap count, and attestation. Exits 0 (all pass), 1 (failures present), or 2 (unknown framework).
- **Live compliance posture in `spanforge doctor`** — after the PII Engine section, doctor now queries the event store, runs `generate_evidence_package(framework="eu_ai_act")`, and prints passing/total clause count with a list of gap/partial clauses.

### Tests — Compliance hardening

- `TestRemediationSteps` — verifies every clause in every framework has a non-empty `remediation_steps` string (length > 20).
- `test_gap_report_text_contains_remediation` — asserts `> **Fix**:` appears in gap report output.
- `test_to_markdown_returns_report_text` — asserts `to_markdown()` is identical to `report_text` and contains `# spanforge Compliance Report`.
- `TestCmdReadiness` — smoke tests for exit codes 0/1/2, all-framework acceptance, and signing-key environment variable check.
- `test_cmd_report_markdown_format`, `test_cmd_report_both_format_writes_json_and_markdown` — coverage for the two new `--format` modes.
- `test_compliance_readiness_registered_in_parser`, `test_dispatch_routes_readiness` — CLI wiring tests.
- Full suite after this session: **6 109 passed**, 14 skipped, 0 failed. ruff 0 · mypy 0 · bandit 0.

---

### Added — Phase 7 documentation and demos

- Added a new [runtime governance GA guide](runtime-governance.md) that consolidates the Phase 1 through Phase 6 runtime-governance story into one operator and buyer-facing control-plane narrative.
- Added dedicated Phase 0/3/5/7 alignment pages:
  - `docs/runtime-governance-contracts.md`
  - `docs/replay-simulation.md`
  - `docs/evidence-export.md`
  - `docs/enterprise-integrations.md`
  - `docs/competitor-comparison.md`
  - `docs/ga-release-notes.md`
- Added focused API documentation for:
  - `spanforge.sdk.explain`
  - `spanforge.sdk.policy`
  - `spanforge.sdk.scope`
  - `spanforge.sdk.rbac`
  - `spanforge.sdk.lineage`
  - `spanforge.sdk.operator`
- Expanded API reference coverage for:
  - `spanforge.integrations.azure_openai`
  - `spanforge.integrations.langgraph`
  - `spanforge.export.openinference`
  - `spanforge.export.siem_schema`

### Added — Phase 8 release hardening

- Added `tests/test_phase8_release_hardening.py` to lock the GA release gate around:
  - end-to-end trace-to-enterprise-evidence workflow verification
  - enforceability of all five runtime policy actions
  - malformed runtime policy input validation
  - incomplete replay/comparison event rejection
  - degraded-mode RAG behavior when the local observe path times out

### Fixed — runtime governance hardening

- `spanforge.runtime_policy` now raises clear `ValueError` messages for malformed bundle and rule dictionaries instead of leaking raw key errors.
- `spanforge.sdk.policy` now validates historical replay and comparison events before evaluation, producing clearer failures for incomplete or mismatched payloads.
- `spanforge.sdk.rag` now normalizes internal `timeout` session states to a schema-valid session summary status during `get_session()` and `end_session()`.
- Added two runnable Phase 7 demo scripts:
  - `examples/runtime_governance_demo.py`
  - `examples/enterprise_evidence_demo.py`
- Added matching walkthrough docs:
  - `docs/demos/runtime-governance-demo.md`
  - `docs/demos/enterprise-evidence-demo.md`
- Added `docs/reference-architectures.md` to centralize the self-hosted, Kubernetes, and air-gapped reference deployment artifacts surfaced by enterprise evidence packaging.
- Updated `README.md`, `docs/index.md`, `docs/quickstart.md`, `docs/api/index.md`, `docs/user_guide/index.md`, and `docs/api/enterprise.md` so the runtime-governance and enterprise evidence paths are discoverable from the main entrypoints.

### Changed — CLI modularization, package-root cleanup, and guardrails

- Split the large CLI router into focused command modules:
  - `spanforge._cli_audit`
  - `spanforge._cli_cost`
  - `spanforge._cli_ops`
  - `spanforge._cli_phase11`
- Reduced top-level package import coupling in `spanforge.__init__` by moving module-style and selected grouped exports behind lazy resolution.
- Added explicit CI drift guardrails in `.github/workflows/ci.yml` plus `tests/test_repo_guardrails.py` to fail fast on:
  - `spanforge.__version__` / `pyproject.toml` mismatch
  - stale known-bad documentation patterns
  - documented CLI entrypoints that no longer parse

### Fixed

- `spanforge.normalizer.GenericNormalizer` now sets a valid `ModelInfo.custom_system_name` when returning `_custom` model-system metadata.

### Tests

- Added direct unit coverage for extracted CLI modules, especially `spanforge._cli_compliance`, so module-level coverage reflects the post-refactor architecture instead of relying only on router integration tests.
- Added focused deep-coverage suites for:
  - `spanforge.sdk.pipelines`
  - `spanforge.gate`
  - `spanforge.egress`
  - `spanforge.normalizer`
- Full suite status after these changes:
  - `6 001 passed`, `14 skipped`
  - overall coverage: `91.72%`

### Added — `spanforge.auto` — RAG Auto-instrumentation (F-20)

- **`trace_rag(func)` decorator** — wraps any retrieval callable; calls `sf_rag.trace_query()` before and `sf_rag.trace_retrieval()` after; fail-safe (never raises).
- **`_patch_rag_llama_index()`** — monkey-patches `llama_index.core.retrievers.VectorIndexRetriever.retrieve` to emit RAG spans automatically when LlamaIndex is installed.
- **`_patch_rag_langchain()`** — monkey-patches `langchain_core.retrievers.BaseRetriever.invoke` to emit RAG spans automatically when LangChain Core is installed.
- **`setup()` extended** — now calls both RAG patches after LLM patches; returns set now includes `"llama_index:rag"` / `"langchain_core:rag"` entries.
- **`teardown()` extended** — calls `_unpatch_rag_llama_index()` and `_unpatch_rag_langchain()` to cleanly restore original methods.
- **`__all__`** updated to export `trace_rag`.
- All RAG import calls wrapped in `warnings.catch_warnings(simplefilter("ignore"))` to suppress NumPy reload `RuntimeWarning` in test environments.

### Added — Async SDK methods (F-10)

- **`SFPIIClient.scan_async(text, *, language="en", score_threshold=0.5)`** — non-blocking async PII scan via `run_in_executor`.
- **`SFGateClient.evaluate_async(gate_id, payload, *, project_id="", pipeline_id="")`** — non-blocking async gate evaluation.
- **`SFCECClient.build_bundle_async(project_id, date_range, frameworks=None)`** — non-blocking async CEC bundle build.
- **`SFTrustClient.get_scorecard_async(project_id=None, *, from_dt=None, to_dt=None, weights=None)`** — non-blocking async T.R.U.S.T. scorecard computation.
- **`SFIdentityClient.sso_delegate_session_async(idp_session_id, subject, *, email="", project_id="default")`** — non-blocking async SSO session delegation.
- All five async methods use `asyncio.get_event_loop().run_in_executor(None, functools.partial(...))`.

### Added — `spanforge._server` — POST /v1/feedback (F-21)

- **`POST /v1/feedback`** route added to the embedded HTTP server.
- Accepts: `session_id`, `trace_id`, `rating` (required); `comment`, `user_id`, `source`, `metadata`, `linked_trust_dimension` (optional).
- Returns: `{"feedback_id": "<ulid>", "accepted": true}` with HTTP 201.
- Delegates to `sf_feedback.submit()`.

### Added — `docs/api/drift.md`

- **Note callout** added after the `BehaviouralBaseline` constructor description: LLM-only warning that `tokens` and `confidence_by_type` fields are only populated when `detector_type="llm"`.

### Tests

- **`tests/test_coverage_gaps.py :: TestGateExecutorSubprocessMocks`** — 27 new tests covering all 6 built-in `subprocess.run` gate executors with dedicated mocks (F-42):
  - `_exec_schema_validation` (4): command PASS, command FAIL (with/without stderr), generic exception.
  - `_exec_dependency_security` (6): PASS (no vulns), FAIL (critical CVEs parsed), JSON parse error, timeout, generic exception, custom command.
  - `_exec_secrets_scan` (4): secrets detected FAIL, fallback to unstaged diff, ImportError, generic exception.
  - `_exec_performance_regression` (3): command PASS, command FAIL, generic exception.
  - `_exec_halluccheck_prri` (4): command + artifact combo, timeout, malformed JSON, generic exception.
  - `_exec_halluccheck_trust` (6): SDK PASS, SDK FAIL, artifact PASS, artifact FAIL, malformed artifact, no-SDK-no-artifact WARN.
- **`tests/test_batch_exporter.py`** — 17 new tests across 5 classes (`TestBatchExporterPutFlush`, `TestBatchExporterShutdown`, `TestBatchExporterQueueFull`, `TestBatchExporterCircuitBreaker`, `TestBatchExporterHealth`). Covers put/flush, shutdown, queue-full, circuit breaker open/half-open/reset, and aggregate health (F-45).
- **`tests/test_prompt_registry.py`** — 19 new tests across 6 classes (`TestPromptVersion`, `TestRegister`, `TestGetList`, `TestRender`, `TestModuleFunctions`, `TestThreadSafety`). Covers version dataclass, registry CRUD, template rendering, module-level helpers, and thread-safe concurrent registration (F-45).
- **`tests/test_sf_gate.py`** — 22 new tests: `TestInferVerdictBranches` (15) for every `_infer_verdict` branch; `TestPostEvaluateHooksSideEffects` (7) for hook execution, hook failure isolation, multi-hook ordering, and metrics access (F-42).
- **`tests/test_sf13.py`** — 3 new test classes: `TestSF13D` (WORM upload on rotation), `TestSF13E` (rotation-by-size + no-rotation-when-zero), `TestSF13F` (append_batch count/content/empty) (F-41).
- Total: **5 863 passed**, 14 skipped, **0 failed**. Coverage: **91.08 %**.

### Fixed

- `tests/test_sf_gate.py` — removed stray `timestamp` kwarg from `GateEvaluationResult()` frozen-dataclass constructor in `TestPostEvaluateHooksSideEffects.setUp`.
- `tests/test_auto.py` — replaced `_rag_libs` wholesale deletion fixture with save/restore of `sys.modules` entries (`_rag_saved`) so RAG lib blocking works without triggering NumPy reload `RuntimeWarning` cascade.
- `src/spanforge/auto.py` — reverted erroneous `_RAG_PATCHED.clear()` call that caused repeated LlamaIndex reimports and NumPy reload warnings.

---

## [2.0.13] — Unreleased

**Phase 1 SSO completion + Phase 5 CEC endpoint additions**

### Added — `spanforge.sdk.identity` — Full SSO Suite (ID-040–ID-043)

- **SAML 2.0 ACS (ID-040)** — `saml_acs()` now processes real SAMLResponse payloads in local mode. Decodes base64 XML, extracts `NameID`, and issues a SpanForge session JWT. `saml_metadata()` now returns a complete SP metadata XML with AssertionConsumerService binding.
- **SCIM 2.0 User provisioning (ID-041)** — Full CRUD: `scim_create_user()`, `scim_get_user()`, `scim_list_users()` (with `eq` filter), `scim_patch_user()` (active/displayName/emails), `scim_delete_user()`. Thread-safe in-memory store with `userName` uniqueness enforcement.
- **SCIM 2.0 Group provisioning (ID-041)** — `scim_create_group()`, `scim_list_groups()`, `scim_delete_group()`. Membership is maintained bidirectionally between user and group records.
- **OIDC relying party (ID-042)** — `oidc_authorize()` generates a PKCE authorization URL (RFC 7636, S256) with `state`, `nonce`, `code_verifier`, `code_challenge`. `oidc_callback()` validates the CSRF state, enforces a 10-minute state TTL, and issues a SpanForge session JWT.
- **SSO session delegation (ID-043)** — `sso_delegate_session()` creates a SpanForge session bound to an IdP session id. `sso_revoke_idp_session()` propagates IdP-side revocation. `sso_get_session()` retrieves session state.
- **New types** — `SCIMUser`, `SCIMGroup`, `SCIMListResponse`, `OIDCAuthRequest`, `OIDCTokenResult`, `SSOSession` added to `spanforge.sdk._types` and exported from `spanforge.sdk`.

### Added — `spanforge.sdk.cec` — Bundle Registry & URL Re-issue (CEC-003, CEC-004)

- **`build_bundle()` now registers results** in an in-memory `_bundle_registry` keyed by `bundle_id`.
- **`get_bundle(bundle_id)`** — Retrieves a previously-built bundle from the session registry; returns `None` if not found.
- **`reissue_download_url(bundle_id)`** — Re-issues a fresh `expires_at` (+24 h) for an existing bundle without rebuilding the ZIP. Raises `SFCECBuildError` if the bundle is unknown or the ZIP was deleted.

### Added — `spanforge._server` — New REST Endpoints (CEC-003, CEC-004)

- **`POST /v1/risk/cec`** — Builds a CEC compliance evidence bundle. Accepts `project_id`, `date_range`, and `frameworks` in the JSON body. Returns `bundle_id`, `download_url`, `expires_at`, `hmac_manifest`, `record_counts`. HTTP 201.
- **`GET /v1/risk/cec/{bundle_id}`** — Re-issues a fresh download URL for an existing bundle. Returns 404 if the `bundle_id` is not in the session registry.

### Tests

- 38 new SSO tests across `TestSAMLStub`, `TestSCIMUsers`, `TestSCIMGroups`, `TestOIDC`, `TestSSOSessionDelegation`, `TestReissueDownloadUrl`.
- 13 new chaos tests in `tests/chaos/test_service_unavailability.py` (DX-023): PII/secrets/audit/observe/identity fallback, no-secrets-in-logs assertions, network-partition simulation.
- Total: **5 766 passed**, 14 skipped. Coverage: **90.01 %**.

---

## [2.0.12] — Unreleased

**Phase 13: RAG Tracing, User Feedback, Async SDK & LangSmith Migration**

### Added — `spanforge.sdk.rag` — RAG Tracing Client (Phase 13)

- **`SFRAGClient`** — End-to-end tracing for Retrieval-Augmented Generation pipelines. Six methods: `trace_query()`, `trace_retrieval()`, `trace_generation()`, `end_session()`, `get_session()`, `get_status()`.
- **`RAGStatusInfo`** — Health DTO with `healthy`, `version`, `mode`, `service`, `total_sessions`, `active_sessions`.
- **`_RAGSession`** — Internal per-session accumulator (query span, retrieved chunks, generation span).
- **Privacy controls** — `include_content=False` drops raw text; `include_metadata=False` drops chunk metadata; `include_query_text=False` anonymises the query.
- **Grounding scores** — `grounding_score` (0–1) on `trace_generation()` measures answer fidelity against retrieved chunks.
- **T.R.U.S.T. integration** — Retrieval quality + grounding scores feed the Reliability pillar of the T.R.U.S.T. scorecard.

### Added — `spanforge.sdk.feedback` — User Feedback Client (Phase 13)

- **`SFFeedbackClient`** — Collects, queries, and aggregates user-facing feedback on LLM responses. Five methods: `submit()`, `get_feedback()`, `get_summary()`, `link_to_trust()`, `get_status()`.
- **`FeedbackStatusInfo`** — Health DTO with `healthy`, `version`, `mode`, `service`, `total_submissions`, `linked_trust_sessions`.
- **`FeedbackRating`** enum (13 values) — `THUMBS_UP`, `THUMBS_DOWN`, `STAR_1`–`STAR_5`, `NPS_0`–`NPS_10` (anchors only), `CSAT_1`–`CSAT_5`.
- **`FeedbackSubmittedPayload`** / **`FeedbackSummaryPayload`** — Namespace payload dataclasses in `spanforge.namespaces.feedback`.

### Added — `spanforge.namespaces.retrieval` — RAG Namespace Payloads (Phase 13)

- **5 dataclasses:** `RetrievedChunk`, `RetrievalQueryPayload`, `RetrievalResultPayload`, `RAGSpanPayload`, `RAGSessionPayload`.

### Added — `spanforge.namespaces.feedback` — Feedback Namespace Payloads (Phase 13)

- **`FeedbackRating`** enum with `numeric_value()` helper.
- **`FeedbackSubmittedPayload`** and **`FeedbackSummaryPayload`** dataclasses.

### Added — Async SDK methods (F-10)

- **`SecretsScanner.scan_async()`** — Non-blocking async variant of `scan()` using `asyncio.to_thread`.
- **`SFAuditClient.append_async()`** — Async append for use in async application code.
- **`SFObserveClient.emit_span_async()`** — Async span emission.
- **`SFAlertClient.publish_async()`** — Async alert publishing.

### Added — `migrate_from_langsmith()` (F-27)

- **`spanforge.migrate.migrate_from_langsmith(runs, *, source="langsmith-import")`** — Converts a list of LangSmith run dicts to SpanForge v2 event dicts. Maps `run_type` → `event_type` using a 4-entry lookup table. Stores only input/output key names (not raw values) for privacy. Truncates `error` fields to 500 characters.
- **CLI:** `spanforge migrate-langsmith` command added.

### Fixed — `DriftDetector` constructor parameters (F-09)

- Renamed `zscore_threshold` → `z_threshold`.
- Removed non-existent `circuit_breaker_reset_seconds` parameter.
- Added `window_seconds` (int, default 3600), `auto_emit` (bool, default True), `metric_ttl_seconds` (int, default 86400).
- Corrected default `window_size` from 100 → 500.

### Quality gates

- **70 new tests** — RAG client, feedback client, async methods, LangSmith migration, DriftDetector params.
- **5 715 total** (12 skipped) — full regression pass, zero failures.
- **Coverage:** 90.01% overall.
- **ruff** clean.

---

## [Unreleased] — Cross-cutting additions

### Added — `spanforge.export.siem_splunk` — Splunk HEC Exporter

- **`SplunkHECExporter`** — Thread-safe, batched exporter for Splunk HTTP Event Collector. Buffers events to configurable `batch_size` (default 50) then flushes in a single HEC HTTP request. SSL verification, configurable index / source / sourcetype, context-manager support. All parameters fall back to `SPANFORGE_SPLUNK_*` environment variables.
- **`SplunkHECError`** — Raised on permanent HEC delivery failures (HTTP errors, URL parse failure, network errors).
- **Security** — HEC token is excluded from `repr()` and log output. HTTP to non-localhost addresses emits a `WARNING`. `verify_ssl=False` is supported for controlled lab environments only.
- **Env vars added:** `SPANFORGE_SPLUNK_HEC_URL`, `SPANFORGE_SPLUNK_HEC_TOKEN`, `SPANFORGE_SPLUNK_INDEX`, `SPANFORGE_SPLUNK_SOURCE`, `SPANFORGE_SPLUNK_SOURCETYPE`, `SPANFORGE_SPLUNK_BATCH_SIZE`, `SPANFORGE_SPLUNK_TIMEOUT`.

### Added — `spanforge.export.siem_syslog` — Syslog / CEF Exporter

- **`SyslogExporter`** — Forwards events to a remote syslog receiver via UDP (default) or TCP. Supports **RFC 5424** and **ArcSight Common Event Format (CEF)** encoding. Severity derived from `event_type` prefix (`error`→3, `warn`→4, `info`→6, `debug`/`trace`→7). Facility configurable (0–23, default `16` = local0). All parameters fall back to `SPANFORGE_SYSLOG_*` environment variables.
- **`SyslogExporterError`** — Wraps `OSError` from socket failures.
- **CEF** — Escapes `\`, `|`, `=` in extension values. Extension fields include `event_id`, `event_type`, `source`, `ts`, and JSON-serialised `payload`.
- **Env vars added:** `SPANFORGE_SYSLOG_HOST`, `SPANFORGE_SYSLOG_PORT`, `SPANFORGE_SYSLOG_TRANSPORT`, `SPANFORGE_SYSLOG_FORMAT`, `SPANFORGE_SYSLOG_APP_NAME`, `SPANFORGE_SYSLOG_FACILITY`.

### Fixed — `spanforge.migrate` — `v1_to_v2` empty tags

- **Bug:** `v1_to_v2()` returned `tags=None` when a v1 event had no tags, causing downstream code to fail on `Tags` attribute access. Now always returns `Tags(**raw_tags)` (an empty `Tags()` object when no tags are present).

### Quality gates

- **223 new tests** — comprehensive coverage of `siem_splunk`, `siem_syslog`, `cache`, `deprecations`, `governance`, and `lint` modules (all new test files).
- **5 645 total** (12 skipped) — full regression pass, zero failures.
- **Coverage:** 90.15% overall; all new modules at high branch + line coverage.
- **ruff** clean, **mypy strict** clean, **bandit** clean.

---

## 2.0.11 — Unreleased

**Phase 12: Developer Experience & Ecosystem**

### Added — `spanforge.testing_mocks` (Phase 12)

- **`MockSFIdentity`** (DX-003) — Mock for `SFIdentityClient`. All 18 methods: `issue_api_key()`, `rotate_api_key()`, `revoke_api_key()`, `validate_api_key()`, `create_session()`, `validate_session()`, `revoke_session()`, `issue_magic_link()`, `exchange_magic_link()`, `enroll_totp()`, `verify_totp()`, `generate_backup_codes()`, `set_ip_allowlist()`, `check_rate_limit()`, `get_status()`, plus `healthy` property.
- **`MockSFPII`** (DX-003) — Mock for `SFPIIClient`. 14 methods: `scan_text()`, `anonymise()`, `scan_batch()`, `apply_pipeline_action()`, `get_status()`, `erase_subject()`, `export_subject_data()`, `safe_harbor_deidentify()`, `audit_training_data()`, `get_pii_stats()`, plus `healthy` property.
- **`MockSFSecrets`** (DX-003) — Mock for `SFSecretsClient`. `scan()`, `scan_batch()`, `get_status()`.
- **`MockSFAudit`** (DX-003) — Mock for `SFAuditClient`. `append()`, `query()`, `verify_chain()`, `export()`, `sign()`, `get_status()`, `get_trust_scorecard()`, `generate_article30_record()`.
- **`MockSFObserve`** (DX-003) — Mock for `SFObserveClient`. `emit_span()`, `export_spans()`, `add_annotation()`, `get_annotations()`, `get_status()`, plus `healthy`/`last_export_at` properties.
- **`MockSFGate`** (DX-003) — Mock for `SFGateClient`. `evaluate()`, `evaluate_prri()`, `run_pipeline()`, `get_artifact()`, `list_artifacts()`, `purge_artifacts()`, `get_status()`, `configure()`.
- **`MockSFCEC`** (DX-003) — Mock for `SFCECClient`. `build_bundle()`, `verify_bundle()`, `generate_dpa()`, `get_status()`.
- **`MockSFAlert`** (DX-003) — Mock for `SFAlertClient`. `publish()`, `acknowledge()`, `register_topic()`, `set_maintenance_window()`, `remove_maintenance_windows()`, `get_alert_history()`, `get_status()`, plus `healthy` property.
- **`MockSFTrust`** (DX-003) — Mock for `SFTrustClient`. `get_scorecard()`, `get_badge()`, `get_history()`, `get_status()`.
- **`MockSFEnterprise`** (DX-003) — Mock for `SFEnterpriseClient`. All 15 methods including `register_tenant()`, `get_isolation_scope()`, `configure_encryption()`, `encrypt_payload()`, `decrypt_payload()`, `configure_airgap()`, `assert_network_allowed()`, `check_all_services_health()`, `get_status()`, plus `healthy` property.
- **`MockSFSecurity`** (DX-003) — Mock for `SFSecurityClient`. `run_owasp_audit()`, `add_threat()`, `generate_default_threat_model()`, `scan_dependencies()`, `run_static_analysis()`, `audit_logs_for_secrets()`, `run_full_scan()`, `get_status()`, plus `healthy` property.
- **`_MockBase`** (DX-003) — Base class with `.calls` recording list, `.configure_response(method, value)` for overriding default returns, and `._record(method, kwargs)` / `._resolve(method, default)` helpers.
- **`mock_all_services()`** (DX-003) — Context manager that patches all 11 `sf_*` singletons in `spanforge.sdk` with their mock counterparts. Restores originals on exit.

### Added — Sandbox mode (Phase 12)

- **`SFServiceClient._is_sandbox()`** (DX-004) — All service clients check `[spanforge] sandbox = true` config to route calls to local in-memory sandbox mode. No network calls, no quota consumption.

### Added — CLI (Phase 12)

- **`spanforge doctor`** (DX-005) — Full environment diagnostic: config validation, service reachability, API key expiry check, PII/secrets pattern loading, gate YAML validation. Coloured pass/fail output.

### Fixed — Mock default return values (Phase 12)

- Corrected 8 mock default return value constructors to match actual `_types.py` dataclass signatures: `ExportResult`, `ObserveStatusInfo`, `PRRIResult`, `GateStatusInfo`, `DPADocument`, `CECStatusInfo`, `AlertStatusInfo`, `EnterpriseStatusInfo`.

### Fixed — Integration tests (Phase 12)

- `test_audit_sign_and_verify` — Changed from `sign()` + `verify_chain()` to `append()` → `export()` → `verify_chain()` workflow to match the API contract.
- `test_observe_export_spans` — Fixed assertion from `ExportResult.success` to `ExportResult.exported_count >= 1`.
- `test_alert_publish_and_deduplicate` — Fixed assertion from `PublishResult.topic` to `not PublishResult.suppressed`.

### Quality gates (Phase 12)

- **130 new tests** — comprehensive coverage of all 11 mock service clients (every method tested), sandbox mode, doctor CLI, integration workflows
- **5 351 total** (12 skipped) — full regression pass, zero failures
- **Coverage**: `testing_mocks.py` 100% line + 100% branch
- **ruff** clean, **mypy strict** clean, **bandit** clean

---

## 2.0.10 — Unreleased

**Phase 11: Enterprise Hardening & Supply Chain Security**

### Added — `spanforge.sdk.enterprise` (Phase 11)

- **`SFEnterpriseClient.register_tenant(project_id, org_id, *, data_residency, cross_project_read, allowed_project_ids) → TenantConfig`** (ENT-001) — Registers a project with namespace isolation, unique HMAC chain secret, and data residency configuration.
- **`SFEnterpriseClient.get_isolation_scope(project_id) → IsolationScope`** (ENT-002) — Returns the `(org_id, project_id)` composite key for namespace scoping.
- **`SFEnterpriseClient.check_cross_project_access(source, targets)`** (ENT-001) — Validates cross-project read access against the allow-list.
- **`SFEnterpriseClient.enforce_data_residency(project_id, target_region)`** (ENT-004) — Blocks data from leaving the configured region.
- **`SFEnterpriseClient.configure_encryption(*, encrypt_at_rest, kms_provider, mtls_enabled, fips_mode) → EncryptionConfig`** (ENT-010–013) — AES-256-GCM at rest, envelope encryption via cloud KMS, mTLS, FIPS 140-2 mode.
- **`SFEnterpriseClient.encrypt_payload(plaintext, key) → dict`** / **`decrypt_payload(...) → bytes`** (ENT-010) — AES-256-GCM encrypt/decrypt with HMAC tag verification.
- **`SFEnterpriseClient.configure_airgap(*, offline, self_hosted) → AirGapConfig`** (ENT-020/021) — Air-gap and self-hosted deployment configuration.
- **`SFEnterpriseClient.assert_network_allowed()`** (ENT-021) — Raises `SFAirGapError` if offline mode is active.
- **`SFEnterpriseClient.check_all_services_health() → list[HealthEndpointResult]`** (ENT-023) — Probes `/healthz` + `/readyz` for all 8 services (16 checks total).
- **`sf_enterprise`** singleton — pre-built `SFEnterpriseClient` in `spanforge.sdk.__init__`.

### Added — `spanforge.sdk.security` (Phase 11)

- **`SFSecurityClient.run_owasp_audit(...) → SecurityAuditResult`** (ENT-030) — Walks all 10 OWASP API Security Top 10 categories with pass/fail per category.
- **`SFSecurityClient.add_threat(service, category, threat, mitigation) → ThreatModelEntry`** (ENT-031) — Adds a STRIDE threat model entry.
- **`SFSecurityClient.generate_default_threat_model() → list[ThreatModelEntry]`** (ENT-031) — Generates 10 default threats across all 8 service boundaries.
- **`SFSecurityClient.scan_dependencies(packages) → list[DependencyVulnerability]`** (ENT-033) — pip-audit wrapper for CVE scanning.
- **`SFSecurityClient.run_static_analysis(source_files) → list[StaticAnalysisFinding]`** (ENT-034) — bandit + semgrep wrapper for SAST.
- **`SFSecurityClient.audit_logs_for_secrets(log_lines) → int`** (ENT-035) — Replays log lines through 7 secret patterns (API keys, JWTs, AWS keys, GitHub tokens, OpenAI keys, Slack tokens, PEM keys).
- **`SFSecurityClient.run_full_scan(...) → SecurityScanResult`** — Combined dependency + static + secrets scan.
- **`sf_security`** singleton — pre-built `SFSecurityClient` in `spanforge.sdk.__init__`.

### Added — Types (Phase 11)

- `DataResidency`, `IsolationScope`, `TenantConfig`, `EncryptionConfig`, `AirGapConfig`, `HealthEndpointResult`, `DependencyVulnerability`, `StaticAnalysisFinding`, `ThreatModelEntry`, `SecurityScanResult`, `SecurityAuditResult`, `EnterpriseStatusInfo`.

### Added — Exceptions (Phase 11)

- `SFEnterpriseError` (base), `SFIsolationError`, `SFDataResidencyError`, `SFEncryptionError`, `SFFIPSError`, `SFAirGapError`, `SFSecurityScanError`, `SFSecretsInLogsError`.

### Added — CLI (Phase 11)

- `spanforge enterprise status|register-tenant|list-tenants|encrypt-config|health`
- `spanforge security owasp|threat-model|scan|audit-logs`

### Added — Server Endpoints (Phase 11)

- `GET /healthz` — Kubernetes liveness probe.
- `GET /readyz` — Kubernetes readiness probe (probes all 8 services).
- `GET /v1/enterprise/status` — Enterprise hardening summary.
- `GET /v1/enterprise/health` — All-services health probe.
- `GET /v1/security/owasp` — OWASP audit results.
- `GET /v1/security/threat-model` — STRIDE threat model.
- `GET /v1/security/scan` — Full security scan.

### Added — Deployment (Phase 11)

- `docker-compose.selfhosted.yml` — Self-hosted Docker Compose stack (ENT-020).
- `helm/spanforge/` — Helm chart skeleton for Kubernetes deployment (ENT-022).

---

## 2.0.9 — Unreleased

**Phase 10: T.R.U.S.T. Scorecard & HallucCheck Contract**

### Added — `spanforge.sdk.trust` (Phase 10)

- **`SFTrustClient.get_scorecard(project_id, *, from_dt, to_dt, weights) → TrustScorecardResponse`** (TRS-001/005) — Aggregates trust records from sf-audit and computes the five T.R.U.S.T. dimensions (Transparency · Reliability · UserTrust · Security · Traceability) with configurable weights. Overall score is a weighted average; colour bands: green ≥ 80, amber ≥ 60, red < 60.
- **`SFTrustClient.get_badge(project_id) → TrustBadgeResult`** (TRS-006) — Generates an SVG badge showing the T.R.U.S.T. score with colour-coded background. Returns `svg`, `overall`, `colour_band`, and `etag`.
- **`SFTrustClient.get_history(project_id, *, from_dt, to_dt, buckets) → list[TrustHistoryEntry]`** (TRS-005) — Returns time-series snapshots by dividing the time range into equal buckets and computing a scorecard for each.
- **`SFTrustClient.get_status() → TrustStatusInfo`** — Returns service health information including dimension count, total trust records, and pipelines registered.
- **`sf_trust`** singleton — pre-built `SFTrustClient` instance in `spanforge.sdk.__init__`, configured from environment variables.

### Added — `spanforge.sdk.pipelines` (Phase 10)

- **`score_pipeline(text, *, model, project_id, pii_action) → PipelineResult`** (TRS-010) — PII scan → secrets scan → observe span → audit append. Orchestrates sf_pii, sf_secrets, sf_observe, and sf_audit in sequence.
- **`bias_pipeline(bias_report, *, project_id, disparity_threshold) → PipelineResult`** (TRS-011) — PII scan on segments → audit append → alert if disparity exceeds threshold → anonymise before export.
- **`monitor_pipeline(drift_event, *, project_id, alert_on_drift) → PipelineResult`** (TRS-012) — Observe drift span → alert if drift detected → OTel export.
- **`risk_pipeline(prri_score, *, project_id, framework, policy_file) → PipelineResult`** (TRS-013) — PRRI evaluation → alert if RED → gate block → CEC bundle generation.
- **`benchmark_pipeline(benchmark_results, *, project_id, model) → PipelineResult`** (TRS-014) — Audit append → alert if accuracy degraded → anonymise before export.

### Added — CLI (Phase 10)

- **`spanforge trust scorecard [--project-id PID]`** — Display the five-pillar T.R.U.S.T. scorecard as a text table.
- **`spanforge trust badge [--project-id PID]`** — Write the T.R.U.S.T. SVG badge to stdout.
- **`spanforge trust gate [--project-id PID]`** — Run the composite trust gate. Exit code 1 = overall score below threshold (red band).

### Added — HTTP server routes (Phase 10)

- **`GET /v1/trust/scorecard?project_id=…`** — Returns the T.R.U.S.T. scorecard as JSON.
- **`GET /v1/trust/badge/{project_id}.svg`** — Returns the SVG badge with `image/svg+xml` content type.
- **`POST /v1/trust-gate`** — Evaluates the composite trust gate and returns pass/fail.
- **`GET /v1/audit/{record_type}`** — Query audit records by record type.
- **`GET /v1/privacy/dsar/{subject_id}`** — DSAR data export for a subject.
- **`POST /v1/scan/secrets`** — Secrets scanning endpoint.

### New types (Phase 10)

| Type | Module | Description |
|------|--------|-------------|
| `TrustScorecardResponse` | `spanforge.sdk._types` | Full scorecard: overall score, colour band, 5 dimensions, weights |
| `TrustDimension` | `spanforge.sdk._types` | Single dimension: `score`, `trend`, `last_updated` |
| `TrustDimensionWeights` | `spanforge.sdk._types` | Configurable weights for each pillar (default 1.0) |
| `TrustHistoryEntry` | `spanforge.sdk._types` | Time-series data point: `timestamp`, `overall`, 5 dimension scores |
| `TrustBadgeResult` | `spanforge.sdk._types` | SVG badge: `svg`, `overall`, `colour_band`, `etag` |
| `TrustStatusInfo` | `spanforge.sdk._types` | Service health: `status`, `dimension_count`, `total_trust_records` |
| `PipelineResult` | `spanforge.sdk._types` | Pipeline result: `pipeline`, `success`, `audit_id`, `span_id`, `details` |

### New exceptions (Phase 10)

| Exception | Raised when |
|-----------|-------------|
| `SFTrustComputeError` | Underlying audit store is unreachable or query fails |
| `SFPipelineError` | A critical step within a pipeline fails |

### Quality gates (Phase 10)

- **28 new tests** — trust client, pipelines, CLI commands, server routes
- **5 102 total** (12 skipped) — full regression pass
- **Coverage**: `trust.py` 100% line + 100% branch, `pipelines.py` 100%/100%
- **ruff** clean, **mypy strict** clean, **bandit** clean

---

## 2.0.8 — Unreleased

**Phase 9: Integration Config & Local Fallback**

### Added — `spanforge.sdk.config` (Phase 9)

- **`load_config_file(path?) → SFConfigBlock`** (CFG-001/002) — Auto-discovers and parses `.halluccheck.toml` from the current directory, parent directories, or `$SPANFORGE_CONFIG_PATH`. Falls back to environment-variable defaults when no file is found. TOML parsing uses `tomllib` (Python 3.11+) or the vendored `tomli` fallback.
- **`validate_config(block) → list[str]`** (CFG-005) — Validates a `SFConfigBlock` against the v6.0 schema. Returns a list of human-readable error strings (empty when valid). Checks key names, value types, ranges, and inter-field consistency.
- **`validate_config_strict(block) → None`** (CFG-006) — Like `validate_config`, but raises `SFConfigValidationError` on the first error. Intended for startup / CI gates.
- **`SFConfigBlock`** (CFG-003) — Typed dataclass representing the full `[spanforge]` configuration block: `enabled`, `project_id`, `endpoint`, `api_key`, `services: SFServiceToggles`, `local_fallback: SFLocalFallbackConfig`, `pii: SFPIIConfig`, `secrets: SFSecretsConfig`.
- **`SFServiceToggles`** (CFG-003) — Per-service on/off toggles for all 8 services (`sf_pii`, `sf_secrets`, `sf_audit`, `sf_observe`, `sf_alert`, `sf_identity`, `sf_gate`, `sf_cec`).
- **`SFLocalFallbackConfig`** (CFG-003) — Fallback settings: `enabled`, `max_retries`, `timeout_ms`.
- **`SFPIIConfig`** / **`SFSecretsConfig`** (CFG-003) — Service-specific typed configuration blocks with `threshold` and `auto_block` settings.

### Added — `spanforge.sdk.registry` (Phase 9)

- **`ServiceRegistry.get_instance() → ServiceRegistry`** (CFG-010) — Thread-safe singleton holding references to all 8 service clients. Access individual clients via `registry.get("sf_pii")`.
- **`ServiceRegistry.run_startup_check()`** (CFG-011) — Pings all enabled services and reports per-service status: `up`, `degraded` (latency > 2 s), or `down`. Raises `SFStartupError` when any service is `down` and `local_fallback.enabled=False`.
- **`ServiceRegistry.status_response() → dict`** (CFG-012) — Returns a dict matching the `GET /v1/spanforge/status` specification. Each service entry includes `{status, latency_ms, last_checked_at}`.
- **`ServiceRegistry.start_background_checker()`** (CFG-013) — Launches a daemon thread that re-checks all services every 60 s. Status changes logged at WARNING; recovery (down → up) at INFO.
- **`ServiceHealth`**, **`ServiceStatus`** — Typed enums for health status tracking.

### Added — `spanforge.sdk.fallback` (Phase 9)

- **`pii_fallback(text)`** (CFG-020) — Local regex PII scan via `spanforge.redact`. Returns entity list without remote service dependency.
- **`secrets_fallback(text)`** (CFG-021) — Local regex secrets scan via `spanforge.secrets`. Returns scan result.
- **`audit_fallback(record, schema_key)`** (CFG-022) — HMAC-chained JSONL append to a local file.
- **`observe_fallback(name, attributes)`** (CFG-023) — OTLP JSON output to stdout.
- **`alert_fallback(topic, payload, severity)`** (CFG-024) — Logs alert to stderr at WARNING level.
- **`identity_fallback(token?)`** (CFG-025) — Trusts `SPANFORGE_LOCAL_TOKEN` env var for CLI/local dev use.
- **`gate_fallback(gate_id, payload)`** (CFG-026) — Runs gate evaluation locally via `spanforge.gate`.
- **`cec_fallback(bundle_data)`** (CFG-027) — Writes CEC bundle to local JSONL file.

### Added — CLI (Phase 9)

- **`spanforge config validate [--file PATH]`** (CFG-007) — Validates `.halluccheck.toml` against the v6.0 schema. Exit codes: 0 = valid, 1 = validation errors, 2 = parse/I/O error.

### New types (Phase 9)

| Type | Module | Description |
|------|--------|-------------|
| `SFConfigBlock` | `spanforge.sdk.config` | Full config representation |
| `SFServiceToggles` | `spanforge.sdk.config` | Per-service enable/disable flags |
| `SFLocalFallbackConfig` | `spanforge.sdk.config` | Fallback settings (enabled, retries, timeout) |
| `SFPIIConfig` | `spanforge.sdk.config` | PII-specific configuration |
| `SFSecretsConfig` | `spanforge.sdk.config` | Secrets-specific configuration |
| `ServiceRegistry` | `spanforge.sdk.registry` | Singleton service registry |
| `ServiceHealth` | `spanforge.sdk.registry` | Health status data |
| `ServiceStatus` | `spanforge.sdk.registry` | Status enum (up/degraded/down) |

### New exceptions (Phase 9)

| Exception | Raised when |
|-----------|-------------|
| `SFConfigError` | `.halluccheck.toml` cannot be parsed or I/O error |
| `SFConfigValidationError` | Config block fails strict validation |
| `SFStartupError` | Service is down on startup and fallback is disabled |
| `SFServiceUnavailableError` | Service becomes unreachable at runtime |

### New environment variables (Phase 9)

| Variable | Default | Description |
|----------|---------|-------------|
| `SPANFORGE_ENDPOINT` | `""` | SpanForge API endpoint URL |
| `SPANFORGE_API_KEY` | `""` | API key for authentication |
| `SPANFORGE_PROJECT_ID` | `"default"` | Project identifier |
| `SPANFORGE_PII_THRESHOLD` | `0.8` | Minimum PII detection confidence |
| `SPANFORGE_SECRETS_AUTO_BLOCK` | `true` | Auto-block high-risk secret types |
| `SPANFORGE_LOCAL_TOKEN` | `""` | Local identity token (dev/CLI mode) |
| `SPANFORGE_FALLBACK_TIMEOUT_MS` | `5000` | Timeout before fallback activation |

### Quality gates (Phase 9)

- **122 new tests** — config parser, registry lifecycle, fallback correctness, CLI validation
- **5 074 total** (12 skipped) — full regression pass
- **Coverage**: `config.py` 100% line + 100% branch, `fallback.py` 100%/100%, `registry.py` 99%/99%
- **ruff** clean, **mypy strict** clean, **bandit** clean

---

## 2.0.7

**Phase 8: CI/CD Gate Pipeline (sf-gate)**

### Added — `spanforge.sdk.gate` (Phase 8)

- **`SFGateClient.evaluate(gate_id, payload, *, project_id) → GateEvaluationResult`** (GAT-004) — Evaluates a single named gate against `payload`. Applies gate logic (schema validation, secrets scan, dependency audit, performance regression, or hallucination check), writes a `GateArtifact` to the artifact store, and returns the structured result immediately.
- **`SFGateClient.evaluate_prri(prri_score, *, project_id, framework, policy_file, dimension_breakdown) → PRRIResult`** (GAT-010/011) — Evaluates a Pre-Release Readiness Index (PRRI) score against configurable thresholds. Scores ≥ `SPANFORGE_GATE_PRRI_RED_THRESHOLD` (default 70) receive `RED` verdict and block release; 30–69 = `AMBER` (warn); < 30 = `GREEN` (pass).
- **`SFGateClient.run_pipeline(gate_config_path, *, context) → GateRunResult`** (GAT-002) — Parses and executes a YAML gate pipeline file. Gates with `on_fail: block` that evaluate to `FAIL` raise `SFGatePipelineError`. Context variables support `${var}` substitution in gate commands.
- **`SFGateClient.get_artifact(gate_id) → GateArtifact | None`** (GAT-003) — Retrieves the most recent stored artifact for a gate. Returns `None` if no artifact is found.
- **`SFGateClient.list_artifacts(*, project_id) → list[GateArtifact]`** — Lists all stored artifacts, optionally filtered to a project. Returns most-recent-first.
- **`SFGateClient.purge_artifacts(*, older_than_days) → int`** — Deletes artifact files older than `older_than_days` from the store. Returns the count of files removed.
- **`SFGateClient.get_status() → GateStatusInfo`** — Returns a live status snapshot: `{status, gate_count, artifact_count, artifact_dir, retention_days, open_circuit_breakers, healthy}`.
- **`SFGateClient.configure(config) → None`** — Overrides gate settings at runtime. Keys not present keep their current (env-var-sourced or default) values.

### Gate YAML engine (Phase 8)

The `GateRunner` class parses YAML gate pipeline files and dispatches each gate to its executor. Supports sequential and parallel execution (`parallel: true`), per-gate timeouts (`timeout_seconds`), conditional skipping (`skip_on`), and three failure policies (`on_fail: block | warn | report`).

**Built-in gate executors:**

| Type | Description |
|------|-------------|
| `schema_validation` | Validates payload against the SpanForge v2.0 JSON Schema. |
| `dependency_security` | Audits package dependencies for known CVEs via the advisory database. |
| `secrets_scan` | Runs the built-in 20-pattern secrets scanner over target files. |
| `performance_regression` | Compares p50/p95/p99 latencies against a stored baseline. |
| `halluccheck_prri` | Evaluates the Pre-Release Readiness Index against policy thresholds. |
| `halluccheck_trust` | Composite trust gate: HRI critical rate + PII window + secrets window. |

### New types (Phase 8)

Added to `spanforge.sdk._types` and re-exported from `spanforge.sdk`:

| Type | Description |
|------|-------------|
| `GateVerdict` | Enum — `PASS`, `FAIL`, `WARN`, `SKIPPED`. |
| `PRRIVerdict` | Enum — `GREEN` (< 30), `AMBER` (30–69), `RED` (≥ 70). |
| `GateArtifact` | Immutable record written to the artifact store after each gate evaluation: `{gate_id, name, verdict, metrics, timestamp, duration_ms, artifact_path}`. |
| `GateEvaluationResult` | Result of a single `evaluate()` call: `{gate_id, verdict, metrics, artifact_url, duration_ms, timestamp}`. |
| `PRRIResult` | Result of `evaluate_prri()`: `{gate_id, prri_score, verdict, dimension_breakdown, framework, policy_file, timestamp, allow}`. |
| `TrustGateResult` | Detailed trust gate outcome: `{gate_id, verdict, hri_critical_rate, hri_critical_threshold, pii_detected, pii_detections_24h, secrets_detected, secrets_detections_24h, failures, timestamp, pipeline_id, project_id}`. |
| `GateStatusInfo` | Live status snapshot: `{status, gate_count, artifact_count, artifact_dir, retention_days, open_circuit_breakers, healthy}`. |

### New exceptions (Phase 8)

Added to `spanforge.sdk._exceptions` and re-exported from `spanforge.sdk`:

| Exception | Base | When raised |
|-----------|------|-------------|
| `SFGateError` | `SpanForgeError` | Base for all gate exceptions. Never raised directly. |
| `SFGateEvaluationError` | `SFGateError` | A single gate evaluation failed (logic error, unsupported payload, or `FAIL` with `block` policy). |
| `SFGatePipelineError` | `SFGateError` | Pipeline runner encountered one or more blocking failures. `failed_gates: list[str]` attribute. |
| `SFGateTrustFailedError` | `SFGateError` | Trust gate detected a blocking condition. `trust_result: TrustGateResult` attribute carries full details. |
| `SFGateSchemaError` | `SFGateError` | YAML gate configuration is invalid (missing field, unrecognised type, or malformed pass condition). |

### Environment variables (Phase 8)

| Variable | Default | Description |
|----------|---------|-------------|
| `SPANFORGE_GATE_ARTIFACT_DIR` | `.sf-gate/artifacts` | Directory for persisted `GateArtifact` JSON files. |
| `SPANFORGE_GATE_ARTIFACT_RETENTION_DAYS` | `90` | Artifact retention period for `purge_artifacts()`. |
| `SPANFORGE_GATE_PRRI_RED_THRESHOLD` | `70` | PRRI scores ≥ this value receive `RED` verdict and block release. |
| `SPANFORGE_GATE_HRI_CRITICAL_THRESHOLD` | `0.05` | HRI critical rate threshold (0–1) for the trust gate. |
| `SPANFORGE_GATE_PII_WINDOW_HOURS` | `24` | PII detection audit window in hours for the trust gate. |
| `SPANFORGE_GATE_SECRETS_WINDOW_HOURS` | `24` | Secrets detection audit window in hours for the trust gate. |

### Promoted from stub (Phase 8)

`spanforge.sdk.sf_gate` — promoted from a no-op stub to a fully operational `SFGateClient` instance backed by `GateRunner`, six gate executors, and a durable JSON artifact store.

### Quality gates

- **174 new tests** — `tests/test_sf_gate.py` covers all 45 acceptance criteria (GAT-001 through GAT-045): single-gate evaluation, PRRI verdicts (GREEN/AMBER/RED), trust gate blocking/passing, YAML pipeline runner, parallel execution, artifact persistence, purge, status, configure, all five exception types, and 30+ edge cases.
- **4,952 total tests** — all passing.
- ruff, mypy, and bandit clean.

---

## 2.0.6 — Unreleased

**Phase 7: Alert Routing Service (sf-alert)**

### Added — `spanforge.sdk.alert` (Phase 7)

- **`SFAlertClient.publish(topic, payload, *, severity, project_id) → PublishResult`** (ALT-001) — Publishes an alert to all configured sinks. Validates topic, checks maintenance windows, deduplicates by `(topic, project_id)`, applies per-project rate limits, and returns a `PublishResult` immediately. The first alert in a topic-prefix group is dispatched immediately; subsequent alerts within 2 minutes are coalesced.
- **`SFAlertClient.acknowledge(alert_id) → bool`** (ALT-020) — Cancels the escalation timer for a CRITICAL alert. Returns `True` if a pending timer was found and cancelled.
- **`SFAlertClient.register_topic(topic, description, default_severity, *, runbook_url, dedup_window_seconds) → None`** (ALT-002/003) — Registers a custom topic in the topic registry with optional runbook URL and per-topic deduplication window.
- **`SFAlertClient.set_maintenance_window(project_id, start, end) → None`** (ALT-030) — Suppresses all alerts for a project during the specified UTC window. Appends a `spanforge.alert.maintenance.v1` audit record.
- **`SFAlertClient.remove_maintenance_windows(project_id) → int`** — Removes all maintenance windows for a project; returns count removed.
- **`SFAlertClient.get_alert_history(*, project_id, topic, from_dt, to_dt, status, limit) → list[AlertRecord]`** (ALT-042) — Retrieves alert history with optional filtering by project, topic, time range, and status. Returns most-recent-first, bounded by `limit` (default 100).
- **`SFAlertClient.get_status() → AlertStatusInfo`** — Returns `{status, publish_count, suppress_count, sink_count, queue_depth, pending_escalations, healthy}`.
- **`SFAlertClient.add_sink(alerter, name) → None`** — Dynamically adds a sink at runtime.
- **`SFAlertClient.healthy: bool`** — `True` when the worker thread is alive.
- **`SFAlertClient.shutdown(timeout) → None`** — Drains the dispatch queue, cancels all escalation timers, and stops the worker thread.
- **Eight built-in topics** (ALT-003) — Pre-registered: `halluccheck.drift.red`, `halluccheck.drift.amber`, `halluccheck.pii.detected`, `halluccheck.cost.exceeded`, `halluccheck.latency.breach`, `halluccheck.audit.gap`, `halluccheck.security.violation`, `halluccheck.compliance.breach`.
- **Deduplication** (ALT-010) — `(topic, project_id)` pairs suppressed for `dedup_window_seconds` (default: 300 s). Per-topic overrides via `register_topic`.
- **Alert grouping** (ALT-011) — First alert in a `(topic_prefix, project_id)` group dispatched immediately; subsequent alerts within 2 minutes coalesced into one notification.
- **CRITICAL escalation policy** (ALT-020/021) — CRITICAL alerts schedule a `threading.Timer` (default: 900 s). If not acknowledged, alert is re-dispatched with `[ESCALATED]` title prefix.
- **Maintenance-window suppression** (ALT-030) — Per-project UTC windows; suppressed alerts are audit-logged and returned as `PublishResult(suppressed=True)`.
- **Per-project rate limiting** (ALT-012) — Sliding window 60 alerts/minute; configurable. Strict mode raises `SFAlertRateLimitedError`.
- **Audit integration** — Every publish, suppression, and maintenance-window event appended to `sf_audit` schema `spanforge.alert.v1` (best-effort; failures logged at DEBUG).
- **Per-sink circuit breakers** — Each sink has its own `_CircuitBreaker` (5-failure threshold, 30 s reset). Failing sinks are bypassed without blocking other sinks.
- **History bounded at 10,000 records** — Oldest entries discarded on overflow.

### New sinks (Phase 7)

All sinks in `spanforge.sdk.alert`:

| Class | Protocol | Security |
|-------|----------|----------|
| `WebhookAlerter(url, secret, timeout)` | POST JSON | HMAC `X-SF-Signature: sha256=<hex>`, SSRF guard |
| `OpsGenieAlerter(api_key, region, timeout)` | OpsGenie v2 Alerts API | `GenieKey` auth, P1–P5 priority map, US/EU URL |
| `VictorOpsAlerter(rest_endpoint_url, timeout)` | VictorOps REST Endpoint | `message_type` CRITICAL/WARNING/INFO |
| `IncidentIOAlerter(api_key, timeout)` | Incident.io v2 Alerts API | `Bearer` auth, critical/major/minor severity |
| `SMSAlerter(account_sid, auth_token, from_number, to_numbers, timeout)` | Twilio Messages API | Basic auth, 160-char truncation, `repr=False` token |
| `TeamsAdaptiveCardAlerter(webhook_url, timeout)` | Teams Incoming Webhook | Adaptive Card v1.3, severity colour band, FactSet, Acknowledge/Silence action buttons |

### New types (Phase 7)

Added to `spanforge.sdk._types` and re-exported from `spanforge.sdk`:

| Type | Description |
|------|-------------|
| `AlertSeverity` | Enum: `INFO`, `WARNING`, `HIGH`, `CRITICAL`; `from_str()` with fallback to `WARNING` |
| `PublishResult` | `{alert_id, routed_to, suppressed}` |
| `TopicRegistration` | `{topic, description, default_severity, runbook_url, dedup_window_seconds}` |
| `MaintenanceWindow` | `{project_id, start, end}` |
| `AlertRecord` | `{alert_id, topic, severity, project_id, payload, sinks_notified, suppressed, status, timestamp}` |
| `AlertStatusInfo` | `{status, publish_count, suppress_count, sink_count, queue_depth, pending_escalations, healthy}` |

### New exceptions (Phase 7)

Added to `spanforge.sdk._exceptions` and re-exported from `spanforge.sdk`:

| Exception | Trigger |
|-----------|---------|
| `SFAlertError` | Base for all alert errors |
| `SFAlertPublishError` | All sinks circuit-open on publish |
| `SFAlertRateLimitedError` | Per-project rate limit exceeded (strict mode) |
| `SFAlertQueueFullError` | Dispatch queue full (> 1 000 items) |

### Environment variables (Phase 7)

| Variable | Effect |
|----------|--------|
| `SPANFORGE_ALERT_SLACK_WEBHOOK` | Auto-register Slack sink |
| `SPANFORGE_ALERT_TEAMS_WEBHOOK` | Auto-register Teams Adaptive Card sink |
| `SPANFORGE_ALERT_PAGERDUTY_KEY` | Auto-register PagerDuty sink |
| `SPANFORGE_ALERT_OPSGENIE_KEY` | Auto-register OpsGenie sink |
| `SPANFORGE_ALERT_OPSGENIE_REGION` | OpsGenie region (`us` or `eu`, default `us`) |
| `SPANFORGE_ALERT_VICTOROPS_URL` | Auto-register VictorOps sink |
| `SPANFORGE_ALERT_WEBHOOK_URL` | Auto-register generic webhook sink |
| `SPANFORGE_ALERT_WEBHOOK_SECRET` | HMAC secret for generic webhook |
| `SPANFORGE_ALERT_DEDUP_SECONDS` | Override dedup window (default `300`) |
| `SPANFORGE_ALERT_RATE_LIMIT` | Override rate limit per minute (default `60`) |
| `SPANFORGE_ALERT_ESCALATION_WAIT` | Override escalation wait seconds (default `900`) |

### Promoted from stub (Phase 7)

- `sf_alert` — previously `_UnimplementedClient("alert")`; now `SFAlertClient(_get_config())`.

---

## 2.0.5 — Unreleased

**Phase 6: Observability Named SDK (sf-observe)**

### Added — `spanforge.sdk.observe` (Phase 6)

- **`SFObserveClient.export_spans(spans, *, receiver_config=None) → ExportResult`** (OBS-001) — Exports a list of OTLP span dicts to the configured backend. Accepts a per-call `ReceiverConfig` override to route to any OTLP-compatible collector. Returns `{exported_count, failed_count, backend, exported_at}`. Falls back to the local buffer on failure when `local_fallback_enabled=True`.
- **`SFObserveClient.add_annotation(event_type, payload, *, project_id) → str`** (OBS-002) — Stores a structured annotation (deploy marker, threshold breach, etc.) in the in-memory annotation log. Returns the generated UUID annotation ID.
- **`SFObserveClient.get_annotations(event_type, from_dt, to_dt, *, project_id="") → list[Annotation]`** (OBS-003) — Retrieves stored annotations filtered by event type (``"*"`` for all), ISO-8601 time window, and optional project ID.
- **`SFObserveClient.emit_span(name, attributes) → str`** (OBS-004) — Constructs a fully-formed OTLP span with W3C TraceContext, OTel GenAI attributes, and error detection; applies the active sampler; emits to the backend; returns the 16-hex span ID.
- **`SFObserveClient.get_status() → ObserveStatusInfo`** — Returns `{status, backend, sampler_strategy, span_count, annotation_count, export_count, last_export_at, healthy}`.
- **`SFObserveClient.healthy: bool`** (OBS-043) — `True` unless the most recent export attempt raised an unrecovered error.
- **`SFObserveClient.last_export_at: str | None`** (OBS-043) — ISO-8601 timestamp of the last successful `export_spans` call.
- **`make_traceparent(trace_id_hex, span_id_hex, *, sampled) → str`** (OBS-011) — Encodes a W3C `traceparent` header value (`00-<32>-<16>-{01|00}`).
- **`extract_traceparent(traceparent) → tuple[str, str, bool]`** (OBS-011) — Parses a `traceparent` header; raises `ValueError` on malformed input.
- **W3C Baggage injection** (OBS-012) — `emit_span` injects `project_id`, `domain`, and `tier` keys into a `baggage` span attribute when present in `attributes`.
- **OTel GenAI semantic conventions** (OBS-010, OBS-014) — `gen_ai.*` attribute keys are forwarded unchanged; `otel.status_code`, `exception.message` handled per OTel spec.
- **Error span detection** (OBS-015) — Sets `status.code = STATUS_CODE_ERROR` and `otel.status_code = ERROR` when `attributes["status"] == "error"` or `attributes["otel.status_code"] == "ERROR"`.
- **OTel resource attributes** (OBS-013) — Every span carries `service.name`, `service.version`, `service.namespace`, `telemetry.sdk.name`, `telemetry.sdk.language`, `telemetry.sdk.version`, and `deployment.environment`.
- **Sampling strategies** (OBS-031) — Configurable via `SPANFORGE_OBSERVE_SAMPLER` (`always_on` [default], `always_off`, `parent_based`, `trace_id_ratio`). Sample rate controlled by `SPANFORGE_OBSERVE_SAMPLE_RATE` (default `1.0`).
- **Backend routing** (OBS-001, OBS-040, OBS-041) — `SPANFORGE_OBSERVE_BACKEND` selects from: `local` (bounded deque, default), `otlp` (`/v1/traces`), `datadog` (`/api/v0.2/traces`), `grafana` (`/api/v1/push`), `splunk` (HEC `/services/collector`), `elastic` (ECS `/_bulk`).
- **Splunk HEC export** (OBS-040) — Spans serialised as `{"event": <span>, "sourcetype": "spanforge:otel"}` events.
- **Elastic ECS export** (OBS-041) — Spans translated to Elastic Common Schema with `trace.id`, `transaction.id`, `span.name`, `event.outcome`, `@timestamp`.
- **Local span buffer** — Bounded at 10,000 spans; oldest entries discarded on overflow.
- **Thread safety** — `_ObserveSessionStats` protected by `threading.Lock`; annotation store uses a separate lock.

### New types (Phase 6)

Added to `spanforge.sdk._types` and re-exported from `spanforge.sdk`:

| Type | Description |
|------|-------------|
| `SamplerStrategy` | Enum: `ALWAYS_ON`, `ALWAYS_OFF`, `PARENT_BASED`, `TRACE_ID_RATIO` |
| `ReceiverConfig` | `{endpoint, headers, timeout_seconds}` — per-call OTLP receiver config |
| `ExportResult` | `{exported_count, failed_count, backend, exported_at}` |
| `Annotation` | `{annotation_id, event_type, payload, project_id, created_at}` |
| `ObserveStatusInfo` | `{status, backend, sampler_strategy, span_count, annotation_count, export_count, last_export_at, healthy}` |

### New exceptions (Phase 6)

Added to `spanforge.sdk._exceptions` and re-exported from `spanforge.sdk`:

| Exception | Trigger |
|-----------|---------|
| `SFObserveError` | Base for all observe errors |
| `SFObserveExportError` | `export_spans` transport or HTTP failure |
| `SFObserveEmitError` | `emit_span` input validation or export failure |
| `SFObserveAnnotationError` | `add_annotation` / `get_annotations` validation failure |

### Promoted from stub (Phase 6)

- `sf_observe` — previously `_UnimplementedClient("observe")`; now `SFObserveClient(_get_config())`.

---

## 2.0.4 — Unreleased

**Phase 5: Compliance Evidence Chain (sf-cec)**

### Added — `spanforge.sdk.cec` (Phase 5)

- **`SFCECClient.build_bundle(project_id, date_range, frameworks=None) → BundleResult`** — orchestrates a full CEC bundle: exports audit records for all 6 schema keys via `sf_audit`, runs clause mapping for each requested framework, assembles a signed ZIP, and returns `{bundle_id, zip_path, hmac_manifest, record_counts, frameworks_covered, generated_at}`.
- **ZIP structure** — `halluccheck_cec_{project}_{from}_{to}.zip` containing:
  - `manifest.json` — record inventory with HMAC-SHA256 signature
  - `clause_map.json` — per-framework clause satisfaction entries (SATISFIED / PARTIAL / GAP)
  - `chain_proof.json` — `verify_chain()` result from sf-audit
  - `attestation.json` — HMAC-signed attestation metadata
  - `rfc3161_timestamp.tsr` — RFC 3161 trusted timestamp stub
  - `score_records/`, `bias_reports/`, `prri_records/`, `drift_events/`, `pii_detections/`, `gate_evaluations/` — NDJSON evidence per schema key
- **`SFCECClient.verify_bundle(zip_path) → BundleVerificationResult`** — re-computes manifest HMAC, verifies chain proof, validates TSR presence, and returns `{bundle_id, manifest_valid, chain_valid, timestamp_valid, overall_valid, errors}`.
- **`SFCECClient.generate_dpa(project_id, controller_details, processor_details, *, subject_categories, transfer_mechanisms, retention_period_days, law_of_contract) → DPADocument`** — generates a GDPR Article 28 Data Processing Agreement. Returns `{document_id, project_id, controller_details, processor_details, generated_at, content, subject_categories, transfer_mechanisms}`.
- **`SFCECClient.get_status() → CECStatusInfo`** — returns `{byos_provider, bundle_count, last_bundle_at, frameworks_supported}`.
- **Supported regulatory frameworks** — `eu_ai_act`, `iso_42001`, `nist_ai_rmf`, `iso27001`, `soc2`.
- **Clause mapping detail per framework**:
  - *EU AI Act* — Art.9 (Risk Management), Art.10 (Data Governance), Art.12 (Record-keeping), Art.13 (Transparency), Art.14 (Human Oversight), Art.15 (Accuracy & Robustness)
  - *ISO/IEC 42001* — Clause 6.1 (Risk assessment), 8.3 (Impact assessment), 9.1 (Monitoring), 10 (Improvement)
  - *NIST AI RMF* — GOVERN, MAP, MEASURE, MANAGE
  - *ISO/IEC 27001 Annex A* — A.12.4.1, A.12.4.2, A.12.4.3
  - *SOC 2* — CC6, CC7, CC9
- **BYOS detection** — respects `SPANFORGE_AUDIT_BYOS_PROVIDER` env var; `get_status()` reflects provider.
- **HMAC signing** — uses `SPANFORGE_SIGNING_KEY` env var; warns at client init if unset or using insecure default.
- **Thread safety** — `_CECSessionStats` dataclass with `threading.Lock()` protects `bundle_count` and `last_bundle_at`.

### New types (Phase 5)

Added to `spanforge.sdk._types` and re-exported from `spanforge.sdk`:

| Type | Description |
|------|-------------|
| `ClauseSatisfaction` | Enum: `SATISFIED`, `PARTIAL`, `GAP` |
| `ClauseMapEntry` | `{framework, clause_id, clause_name, description, status, evidence_count}` |
| `BundleResult` | Result of `build_bundle()` |
| `BundleVerificationResult` | Result of `verify_bundle()` |
| `DPADocument` | Result of `generate_dpa()` |
| `CECStatusInfo` | Result of `get_status()` |

### New exceptions (Phase 5)

Added to `spanforge.sdk._exceptions` and re-exported from `spanforge.sdk`:

| Exception | When raised |
|-----------|-------------|
| `SFCECError` | Base class for all sf-cec errors |
| `SFCECBuildError` | Bundle assembly fails (ZIP write error, HMAC failure) |
| `SFCECVerifyError` | Bundle verification fails (file not found, HMAC mismatch, tampered manifest) |
| `SFCECExportError` | DPA generation or export fails |

### SDK singleton

- `sf_cec: SFCECClient` singleton registered in `spanforge.sdk`; loaded from `_get_config()` on import.
- `configure()` now recreates `sf_cec` alongside the other service clients.

### Quality Gates (Phase 5)

- **148 Phase 5 tests** passing, 0 failures.
- `ruff check` ✅ | `mypy --strict` ✅ | `bandit -r -ll` ✅
- **4 544 total tests** passing across full suite (12 skipped).

---

## 2.0.3 — Unreleased

**Phase 4: Audit Service High-Level API (sf-audit)**

### Added — `spanforge.sdk.audit` (Phase 4)

- **`SFAuditClient.append(record, schema_key, *, project_id, strict_schema) -> AuditAppendResult`** — validates schema key, appends HMAC-chained record to local store, writes T.R.U.S.T. feed on score schemas. Thread-safe.
- **`SFAuditClient.sign(record) -> SignedRecord`** — HMAC-SHA256 sign a raw dict.
- **`SFAuditClient.verify_chain(records) -> dict`** — re-derive and verify HMAC chain integrity; returns `{valid, verified_count, tampered_count, first_tampered, gaps}`.
- **`SFAuditClient.query(*, schema_key, project_id, from_dt, to_dt, limit) -> list[dict]`** — O(log n) SQLite-indexed date-range query with linear fallback.
- **`SFAuditClient.export(*, format, compress) -> bytes`** — JSONL or CSV export of full local store, with optional gzip compression.
- **`SFAuditClient.get_trust_scorecard(*, project_id, from_dt, to_dt) -> TrustScorecard`** — aggregates T.R.U.S.T. dimensions (hallucination, PII hygiene, secrets hygiene, gate pass rate, compliance posture).
- **`SFAuditClient.generate_article30_record(*, project_id, controller_name, ...) -> Article30Record`** — GDPR Article 30 Records of Processing Activity.
- **`SFAuditClient.get_status() -> AuditStatusInfo`** — returns backend, record count, chain length, BYOS provider, last record timestamp.
- Schema key registry with 13 known keys (`halluccheck.*`, `spanforge.*`); `strict_schema=False` allows custom keys.
- BYOS routing via `SPANFORGE_AUDIT_BYOS_PROVIDER` env var (`s3`, `azure`, `gcs`, `r2`).
- SQLite WAL-mode index for O(log n) date-range queries; in-memory fallback.
- New exceptions: `SFAuditError`, `SFAuditSchemaError`, `SFAuditAppendError`, `SFAuditQueryError`.
- New types: `AuditAppendResult`, `SignedRecord`, `TrustDimension`, `TrustScorecard`, `Article30Record`, `AuditStatusInfo`.
- `sf_audit` singleton registered in `spanforge.sdk` with `configure()` support.

---

**Phase 3: PII Service Hardening (sf-pii)**

### Added — `spanforge.sdk.pii` (Phase 3)

- **`SFPIIClient.scan_text(text, *, language) -> PIITextScanResult`** — full-text PII scan
  via Presidio with `redact` fallback; returns `{entities, redacted_text, detected}`.
- **`SFPIIClient.anonymise(payload) -> PIIAnonymisedResult`** — recursively replaces PII in
  all string fields with `<TYPE>` placeholders; returns `{clean_payload, redaction_manifest}`.
- **`SFPIIClient.scan_batch(texts) -> list[PIITextScanResult]`** — parallel batch scan.
- **`SFPIIClient.apply_pipeline_action(scan_result, action, threshold) -> PIIPipelineResult`** —
  enforces `"flag"` / `"redact"` / `"block"` (raises `SFPIIBlockedError`); filters by
  confidence threshold (default 0.85).
- **`SFPIIClient.get_status() -> PIIServiceStatus`** — returns
  `{status, presidio_available, entity_types_loaded, last_scan_at}`.
- **`SFPIIClient.erase_subject(subject_id, project_id) -> ErasureReceipt`** — GDPR Article 17
  erasure; subject ID SHA-256 hashed in receipt.
- **`SFPIIClient.export_subject_data(subject_id, project_id) -> DSARExport`** — CCPA DSAR export
  aggregating all audit events for a subject.
- **`SFPIIClient.safe_harbor_deidentify(text) -> SafeHarborResult`** — HIPAA Safe Harbor
  de-identification of 18 PHI identifier types (45 CFR §164.514(b)(2)); dates → year,
  ages > 89 → "90+", ZIP → first 3 digits.
- **`SFPIIClient.audit_training_data(dataset_path, *, max_records) -> TrainingDataPIIReport`** —
  EU AI Act Article 10 training-data PII prevalence report.
- **`SFPIIClient.get_pii_stats(project_id) -> list[PIIHeatMapEntry]`** — per-entity-type
  detection stats for dashboard heat-map.

- **`POST /v1/scan/pii`** HTTP endpoint — standalone PII scan; returns `{entities[], redacted_text}`.
- **`GET /v1/spanforge/status`** — extended with `sf_pii` status block.

- **New types** in `spanforge.sdk._types`:
  `PIITextScanResult`, `PIIAnonymisedResult`, `PIIRedactionManifestEntry`,
  `PIIPipelineResult`, `PIIServiceStatus`, `PIIHeatMapEntry`,
  `ErasureReceipt`, `DSARExport`, `SafeHarborResult`, `TrainingDataPIIReport`,
  `PIIEntityResult`.

- **New exceptions** in `spanforge.sdk._exceptions`:
  `SFPIIBlockedError` (HTTP 422, action=block), `SFPIIDPDPConsentMissingError`
  (DPDP consent missing for subject).

- **China PIPL patterns** in `presidio_backend.py`: Chinese national ID (`\d{17}[\dX]`),
  Chinese mobile (`1[3-9]\d{9}`), Chinese bank card.

### Quality Gates (Phase 3)

- **273 Phase 3 tests** passing, 1 presidio integration skip.
- **95% line coverage** on `sdk/pii.py`; **92.31% repo-wide**.
- `ruff check` ✅  |  `mypy --strict` ✅  |  `bandit -r` ✅

---

**Phase 1: sf-identity + sf-pii Service SDK**

### Added — `spanforge.sdk` (Phase 1: sf-identity + sf-pii)

- **`SFIdentityClient`** (`spanforge.sdk.identity`) — full sf-identity API surface:
  - `issue_api_key(scopes, key_format, quota_tier, ip_allowlist)` — cryptographically signed
    key in `sf_live_*` / `sf_test_*` format (48 base62 chars).
  - `rotate_api_key(old_key)` — atomic rotate with immediate old-key revocation.
  - `revoke_api_key(key)` — single-use revocation; replays silently ignored.
  - `verify_api_key(key)` — validates format, revocation state, IP allowlist, and rate limit.
  - `create_session(api_key)` — issues HS256 JWT (RS256 when remote service configured).
  - `verify_token(token)` — returns `JWTClaims`; raises `SFTokenInvalidError` on tampering.
  - `introspect_token(token)` — returns `TokenIntrospectionResult` with expiry and scopes.
  - `issue_magic_link(identifier, redirect_url)` — 15-minute HMAC-signed single-use URL.
  - `exchange_magic_link(token)` — exchanges token for a session JWT; replays raise
    `SFTokenInvalidError`.
  - `enroll_totp(identifier)` — RFC 6238 TOTP (SHA-1, 6 digits, 30 s); returns
    `TOTPEnrollResult` with provisioning URI and 8 single-use backup codes.
  - `verify_totp(identifier, code)` — ±1 time-step drift tolerance; 5-failure lockout.
  - `verify_backup_code(identifier, code)` — single-use; stored as SHA-256 hashes only.
  - Brute-force lockout: 5 consecutive failures → 15-minute lockout (`SFBruteForceLockedError`).
  - IP allowlist enforcement (`SFIPDeniedError`).
  - Per-key sliding-window rate limiting (`SFQuotaExceededError`).

- **`SFPIIClient`** (`spanforge.sdk.pii`) — full sf-pii API surface:
  - `scan(event)` — deep regex PII scan; returns `SFPIIScanResult` (hits, field paths, types).
  - `redact(event, policy)` — apply `RedactionPolicy`; returns `SFPIIRedactResult`.
  - `contains_pii(event)` — boolean check; never raises.
  - `assert_redacted(event)` — raises `SFPIINotRedactedError` with SHA-256-hashed context
    (never raw PII) if unredacted PII remains.
  - `anonymize(text, sensitivity)` — replaces PII patterns in raw strings; returns
    `SFPIIAnonymizeResult` with replacement count and labels.
  - `wrap(event)` — returns a `Redactable` wrapper for chained redaction.
  - `make_policy(min_sensitivity, redacted_by)` — convenience `RedactionPolicy` factory.

- **`spanforge.sdk._base`** — shared infrastructure:
  - `SFClientConfig` — dataclass loaded from env vars (`SPANFORGE_ENDPOINT`,
    `SPANFORGE_API_KEY`, `SPANFORGE_LOCAL_FALLBACK`, `SPANFORGE_TLS_VERIFY`).
    Supports `from_env()` and `from_dict()`.
  - `SFServiceClient` — abstract base with HTTP retry (3 attempts, exponential back-off),
    circuit breaker (5 failures → OPEN, 30 s reset), and TLS verification.
  - `_CircuitBreaker` — thread-safe CLOSED → OPEN → CLOSED lifecycle.
  - `_SlidingWindowRateLimiter` — per-key, configurable window and max calls.

- **`spanforge.sdk._types`** — value objects:
  - `SecretStr` — never exposed in `__repr__` / `__str__` / pickle; equality via
    `hmac.compare_digest`.
  - `APIKeyBundle`, `JWTClaims`, `MagicLinkResult`, `TOTPEnrollResult`,
    `TokenIntrospectionResult`, `RateLimitInfo`.
  - `SFPIIScanResult`, `SFPIIHit`, `SFPIIRedactResult`, `SFPIIAnonymizeResult`.
  - `KeyFormat`, `KeyScope`, `QuotaTier` enumerations.

- **`spanforge.sdk._exceptions`** — full exception hierarchy:
  - `SFError` base → `SFAuthError`, `SFTokenInvalidError`, `SFScopeError`,
    `SFIPDeniedError`, `SFMFARequiredError`, `SFBruteForceLockedError`,
    `SFQuotaExceededError`, `SFRateLimitError`, `SFServiceUnavailableError`,
    `SFStartupError`, `SFKeyFormatError`.
  - `SFPIIError` → `SFPIIScanError`, `SFPIINotRedactedError`, `SFPIIPolicyError`.

- Pre-built `sf_identity` and `sf_pii` singletons exported from `spanforge.sdk`.
  Configuration auto-loaded from env vars on first import; call `configure()` to override.

### Changed — Code Quality

- `ruff check src/` now passes with **zero errors** — 60 missing public-method docstrings
  added across `processor.py`, `prompt_registry.py`, `redact.py`, `sampling.py`, and
  `signing.py`; `pyproject.toml` extended with justified `ignore` and `per-file-ignores`
  entries for rule categories that are either inapplicable (lazy imports, module-state
  globals) or intentionally suppressed project-wide.

---

**Upstream utility modules from sf-behaviour**

### Added — `spanforge.http`

- **`chat_completion(endpoint, model, messages, …)`** — zero-dependency,
  synchronous OpenAI-compatible HTTP client built on `urllib.request`.
  Retries on `429 / 5xx` and network errors with exponential back-off
  (`min(2**attempt, 8)` s, up to `max_retries` attempts).
- **`ChatCompletionResponse`** frozen dataclass: `text`, `latency_ms`,
  `error`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `ok`.
- Falls back to `OPENAI_API_KEY` env var when no `api_key` is supplied.

### Added — `spanforge.io`

- **`write_jsonl(records, path, *, mode)`** — write an iterable of dicts as
  newline-delimited JSON; creates parent directories automatically.
- **`read_jsonl(path, *, event_type, skip_errors)`** — read all dicts from a
  JSONL file with optional `event_type` filtering and resilient error
  handling.
- **`append_jsonl(record, path)`** — single-record convenience wrapper.
- **`write_events(payloads, path, *, event_type, source, mode)`** — wraps
  each payload in a `{"event_type":…, "source":…, "payload":…}` envelope.
- **`read_events(path, *, event_type)`** — reads envelopes and returns
  unwrapped payloads filtered by type.

### Added — `spanforge.plugins`

- **`discover(group)`** — load all entry-point plugins registered under
  *group*.  Handles the Python 3.9 / 3.10 / 3.12+ `entry_points()` API
  split; silently skips broken entry points.

### Added — `spanforge.schema`

- **`validate(instance, schema, path)`** — lightweight, zero-dependency JSON
  Schema validator.  Returns a list of error strings.  Supports `type`,
  `enum`, `required`, `properties`, `items`, `minimum`, `maximum`,
  `minLength`, `maxLength`.
- **`validate_strict(…)`** — raises `SchemaValidationError` on any error.
- **`SchemaValidationError`** — `ValueError` subclass carrying an `errors`
  list.
- Correctly distinguishes `bool` from `integer`/`number` (Python's
  `isinstance(True, int)` is `True` but JSON Schema treats them as separate
  types).

### Added — `spanforge.regression`

- **`RegressionDetector[T]`** — generic per-case pass/fail regression
  detector.  Identifies *new failures* and *score drops* between a baseline
  and current eval run.
- **`RegressionReport[T]`** — result dataclass with `new_failures`,
  `score_drops`, `has_regression`, and `summary()`.
- **`compare(…)`** — convenience one-shot function.
- Distinct from the existing `spanforge.eval.RegressionDetector`
  (mean-based); exposed as `PassFailRegressionDetector` at the top-level
  package to avoid naming collision.

### Added — `spanforge.stats`

- **`percentile(values, p)`** — linear-interpolation percentile; does not
  mutate the input list.
- **`latency_summary(values_ms)`** — returns `{count, mean, min, max, p50,
  p95, p99}` rounded to 3 dp; returns zeroed output for empty input.

### Added — `spanforge._ansi`

- **`color(text, code, *, file)`** — wraps text with ANSI escape codes.
  Suppressed automatically when `NO_COLOR` is set or the target file is not
  a TTY.
- **`strip_ansi(text)`** — strips all `\033[…m` sequences from a string
  (useful in tests and log processors).
- Color constants: `GREEN`, `RED`, `YELLOW`, `CYAN`, `BOLD`, `RESET`.

### Added — `spanforge.eval.BehaviourScorer`

- **`BehaviourScorer`** abstract base class — pluggable scorer for named
  test-case workflows.  Subclasses implement
  `score(case, response) -> (float, reason)`.  Distinct from the existing
  `EvalScorer` Protocol (which scores full `dict` examples).
- Registered via `spanforge.scorers` entry-point group for third-party
  scorer packages.

### Added — `spanforge.config.interpolate_env()`

- **`interpolate_env(data)`** — recursively walks `str`/`dict`/`list`
  structures and replaces `${VAR}` / `${VAR:default}` placeholders with
  environment variable values.  Non-string leaves are returned unchanged.
  Unresolved variables with no default are left as-is.

### Exposed at top-level (`spanforge.*`)

All new symbols are exported from the top-level `spanforge` package:
`BehaviourScorer`, `ChatCompletionResponse`, `JsonSchemaValidationError`,
`PassFailRegressionDetector`, `RegressionReport`, `ansi_color`,
`append_jsonl`, `chat_completion`, `compare_regressions`, `discover_plugins`,
`interpolate_env`, `latency_summary`, `percentile`, `read_events`,
`read_jsonl`, `strip_ansi`, `validate_json_schema`,
`validate_json_schema_strict`, `write_events`, `write_jsonl`.

---

**Phase 2: sf-secrets — Secrets Scanning Engine**

### Added — `spanforge.secrets` (Phase 2)

- **`SecretsScanner`** — standalone secrets detection engine; no network calls required.
  - `scan(text, *, confidence_threshold=0.85)` → `SecretsScanResult`
  - `scan_batch(texts)` → `list[SecretsScanResult]` (asyncio parallel execution)
  - 20-pattern registry: 7 spec-defined types + 13 industry-standard additions
    (GitHub PAT, npm token, Slack token, Stripe key, Twilio, SendGrid, Azure SAS,
    SSH private key, Google API key, Terraform Cloud, HashiCorp Vault token, generic JWT,
    SpanForge API key)
  - Shannon entropy scorer (`entropy_score(s)`) — bits/char; boosts confidence for
    high-entropy tokens (≥ 3.5 bits/char, ≥ 32 chars)
  - Three-tier confidence model: pattern-only → 0.75; + entropy → 0.90; + context keyword → 0.97
  - Zero-tolerance auto-block for 10 high-risk types (Bearer Token, AWS Access Key,
    GCP Service Account, PEM Private Key, SSH Private Key, HallucCheck API key,
    SpanForge API key, GitHub PAT, Stripe live key, npm token)
  - Configurable allowlist suppresses known test/placeholder values
  - Span deduplication: highest-confidence hit wins per overlapping region

- **`SecretHit`** — frozen dataclass: `secret_type`, `start`, `end`, `confidence`,
  `redacted_value` (`[REDACTED:TYPE]` replacement)

- **`SecretsScanResult`** — result dataclass:
  - `detected: bool`, `hits: list[SecretHit]`, `auto_blocked: bool`, `redacted_text: str`
  - `to_dict()` — JSON-serialisable dict
  - `to_sarif()` — SARIF 2.1.0 log object for GitHub Code Scanning / VS Code

- **`entropy_score(s)`** — Shannon entropy in bits/char; importable as a standalone utility

### Added — `spanforge.sdk.secrets` (Phase 2)

- **`SFSecretsClient`** — SDK client with local + remote modes:
  - `scan(text)` → `SecretsScanResult` — runs `SecretsScanner` locally; if remote endpoint
    configured, POST `/v1/scan/secrets` with local fallback
  - `scan_batch(texts)` → `list[SecretsScanResult]` — asyncio parallel with sequential fallback
  - Inherits retry, circuit breaker, and TLS verification from `SFServiceClient`

- **`sf_secrets`** singleton exported from `spanforge.sdk` — eager-initialised from
  env vars alongside `sf_identity` and `sf_pii`

- **Three new exceptions** added to `spanforge.sdk._exceptions`:
  - `SFSecretsError` — base class for all sf-secrets errors
  - `SFSecretsBlockedError(secret_types, count)` — raised when auto-block policy fires;
    `message` includes detected type list
  - `SFSecretsScanError` — wraps unexpected scanner failures

### Added — CLI command `spanforge secrets scan` (Phase 2)

```
spanforge secrets scan <file> [--format text|json|sarif] [--redact] [--confidence FLOAT]
```

| Flag | Description |
|------|-------------|
| `--format` | Output format: `text` (default), `json`, or `sarif` (SARIF 2.1.0) |
| `--redact` | Print redacted version of the file to stdout |
| `--confidence` | Override minimum confidence threshold (default: `0.85`) |

Exit codes: `0` = clean, `1` = secrets detected, `2` = error / file not found

### Added — Pre-commit hook `.pre-commit-hooks.yaml` (Phase 2)

```yaml
- id: spanforge-secrets-scan
  name: SpanForge Secrets Scan
  entry: spanforge secrets scan
  language: python
  types: [text]
  stages: [pre-commit, pre-push]
```

Covers Python, JavaScript/TypeScript, YAML, JSON, TOML, INI, and `.env` files.

### Changed — `spanforge.sdk` (Phase 2)

- `sf_secrets: SFSecretsClient` singleton added alongside `sf_identity` and `sf_pii`
- `configure()` updated to accept secrets-specific overrides
- Baseline absent-service note for `sf-secrets` is now resolved — full implementation complete

### Quality gates (Phase 2)

- **120 new tests** (all passing) — `tests/test_sf_secrets.py`
- **4 147 total tests** passing, 11 skipped
- **92.28% line coverage** (≥ 90% gate enforced in CI)
- Ruff clean — zero errors across all Phase 2 files

---

## 2.0.2 — 2026-04-14

**Compliance Integration Hardening & CostGuard Enhancements**

### Added — Built-in Evaluation Scorers

- **`FaithfulnessScorer`** — token-overlap scorer comparing LLM output
  against provided context.  Returns 0–1 score; label `"pass"` when
  overlap ≥ 0.5, `"skip"` when context or output is missing.
- **`RefusalDetectionScorer`** — heuristic scorer that detects common
  refusal phrases (e.g. "I'm sorry", "as an AI") via case-insensitive
  matching.  Returns 1.0 / label `"refusal"` on match.
- **`PIILeakageScorer`** — wraps `scan_payload()` to flag PII in the
  `output` field.  Returns 1.0 / label `"leak"` with hit count metadata.
- All three exported from `spanforge` top-level package.

### Added — Eval Dataset CLI (`spanforge eval`)

- **`spanforge eval save --input EVENTS.jsonl --output DATASET.jsonl`** —
  extracts evaluation examples from event payloads (output, context,
  reference, input, span/trace IDs) into a reusable JSONL dataset.
- **`spanforge eval run --file DATASET.jsonl [--scorers S1,S2] [--format text|json]`** —
  runs selected built-in scorers over a JSONL dataset and prints a summary.
  Supports `faithfulness`, `refusal`, and `pii_leakage` scorer names.

### Added — Compliance Status CLI

- **`spanforge compliance status --events-file FILE [--framework FRAMEWORK]`** —
  outputs a single JSON summary with chain integrity, PII scan results,
  per-clause coverage, last attestation timestamp, and events analysed count.

### Added — LangSmith Migration CLI

- **`spanforge migrate-langsmith FILE [--output FILE] [--source NAME]`** —
  reads a LangSmith export (JSONL or JSON array), converts runs to
  SpanForge events (llm → `TRACE_SPAN_COMPLETED`, tool → `TOOL_CALL_COMPLETED`),
  preserving token usage, timing, input/output, and error info.  Tags with
  `langsmith_run_id`, `langsmith_trace_id`, and `langsmith_parent_id`.

### Added — Gemini Provider Integration

- **`spanforge.integrations.gemini`** — auto-instrumentation for Google
  Gemini (`google-generativeai`).  `patch()` / `unpatch()` wraps
  `GenerativeModel.generate_content` and its async variant.
- **`normalize_response(response, *, model_name)`** — extracts tokens
  from `usage_metadata`, strips `models/` prefix, uses `GenAISystem.GOOGLE`.
- **`GEMINI_PRICING`** table — covers gemini-2.0-flash, gemini-1.5-pro,
  gemini-1.5-flash, gemini-1.0-pro, and more.
- Install: `pip install spanforge[gemini]`

### Added — Bedrock Provider Integration

- **`spanforge.integrations.bedrock`** — integration for AWS Bedrock
  Runtime's Converse API.
- **`normalize_converse_response(response, *, model_id)`** — extracts
  tokens from `response["usage"]` (`inputTokens` / `outputTokens`),
  uses `GenAISystem.AWS_BEDROCK`.
- **`BEDROCK_PRICING`** table — covers Claude 3 (Sonnet/Haiku/Opus),
  Titan (Text/Embed), Llama 3, Mistral, and Cohere on Bedrock.
- Install: `pip install spanforge[bedrock]`

### Added — Presidio PII Backend

- **`spanforge.presidio_backend`** — optional Presidio-powered PII
  detection backend gated behind `pip install spanforge[presidio]`.
- **`presidio_scan_payload(payload, *, language, score_threshold)`** —
  walks payload recursively using Presidio `AnalyzerEngine`, maps entity
  types to SpanForge labels, returns standard `PIIScanResult`.

### Changed — Security Default: `scan_raw=True`

- **`contains_pii()`** and **`assert_redacted()`** now default to
  `scan_raw=True`, catching raw-string PII by default.  Pass
  `scan_raw=False` to restore previous behaviour.
- Fixed `isinstance` check to use `Mapping` instead of `dict` so
  `scan_raw` works correctly with `Event.payload` (which returns
  `MappingProxyType`).

### Changed — GenAISystem Enum

- Added `GOOGLE = "google"` to `GenAISystem` enum in `namespaces/trace.py`.

### Changed — pyproject.toml

- New optional dependency groups: `presidio`, `gemini`, `bedrock`.

### Added — India PII Pattern Pack (DPDP Act)

- **`DPDP_PATTERNS` named constant** — ships Aadhaar and PAN number regex
  detectors for India's Digital Personal Data Protection Act compliance.
  Pass as `extra_patterns=DPDP_PATTERNS` to `scan_payload()`.
- **Aadhaar detection** — matches 12-digit numbers (XXXX XXXX XXXX,
  XXXX-XXXX-XXXX, or contiguous) starting with digits 2–9, validated
  with the **Verhoeff checksum** algorithm (zero false-positive on
  random 12-digit strings).
- **PAN detection** — matches the [A-Z]{5}[0-9]{4}[A-Z] format
  (Person, Company, Trust, etc.).
- Both types mapped to sensitivity `"high"` in `_SENSITIVITY_MAP`.
- Exported from the top-level `spanforge` package.

### Added — Extended PII Pattern Coverage

- **`date_of_birth` pattern** — detects dates of birth across all major global
  formats (centuries 1900–2099):
  - ISO / year-first: `YYYY-MM-DD`, `YYYY/MM/DD`, `YYYY.MM.DD`
  - US month-first: `MM/DD/YYYY`, `MM-DD-YYYY`, `MM.DD.YYYY`
  - Day-first (UK, EU, Germany, Asia, Australia, Latin America): `DD/MM/YYYY`,
    `DD-MM-YYYY`, `DD.MM.YYYY`
  - Written day-first: `15 Jan 2000`, `15-Jan-2000`, `15 January 2000`
  - Written month-first: `Jan 15, 2000`, `January 15 2000`

  Secondary calendar validation via `_is_valid_date()` rejects impossible dates
  (e.g. `02/30/1990`, `31/04/1990`).  Mapped to sensitivity `"high"`.
- **`address` pattern** — detects street addresses (`<number> <name> <suffix>`)
  with a curated suffix list (Street/St, Avenue/Ave, Road/Rd, Boulevard/Blvd,
  Drive/Dr, Lane/Ln, Court/Ct, Way, Place/Pl, Circle/Cir, Trail/Trl,
  Terrace/Ter, Parkway/Pkwy, Highway/Hwy, Route/Rte).  Mapped to sensitivity
  `"medium"`.
- **`_is_valid_ssn(ssn_str)`** — SSA range validator applied post-regex to every
  SSN match in `scan_payload()`.  Rejects area `000`, area `666`, areas
  `900–999` (ITIN-reserved), group `00`, and serial `0000`, eliminating the
  most common false-positive ranges.
- **`_is_valid_date(date_str)`** — calendar correctness validator applied
  post-regex to every `date_of_birth` match.  Tries 15 `strptime` format
  strings covering all numeric and written-month orderings; delegates to
  `datetime.strptime` for accurate month-length and leap-year enforcement.
- Both validators follow the same pattern as existing `_luhn_check()` and
  `_verhoeff_check()` — applied inside `scan_payload._walk()` after the regex
  pass.

### Fixed — Compliance Attestation with Missing Signing Key

- `generate_evidence_package()`, `to_pdf()`, and `verify_attestation_signature()`
  previously raised `ValueError` when `SPANFORGE_SIGNING_KEY` was not set in
  the environment.  They now emit a `logging.WARNING` and fall back to an
  insecure internal default (`_INSECURE_DEFAULT_KEY`).  **Production
  deployments must always set `SPANFORGE_SIGNING_KEY`; the default key exists
  only for development and CI environments.**

### Added — Compliance Dashboard in SPA Viewer

- **Clause pass/fail table** — clicking the compliance chip in the
  `spanforge serve` / `spanforge ui` header opens a full compliance
  dashboard showing per-framework clause breakdown (clause ID,
  description, PASS/FAIL badge) and score percentages.
- **Chain integrity banner** — prominent status display for chain
  verification: verified (green), not verified (warning), or tampered
  (red with count).
- **Overview stat grid** — total events, signed events, PII hits,
  events with PII, and explanation coverage percentage.
- **Model registry card** — lists all models observed in event payloads
  with invocation counts, sources, and last-seen timestamps.
- **Back to Traces** navigation — returns to the standard trace/event
  list view.

### Added — Multi-Agent Cost Rollup

- **Child run cost propagation** — `AgentRunContext` gains
  `_child_run_costs` accumulator and `record_child_run_cost()` method.
  `AgentRunContextManager.__exit__` now automatically propagates the
  child run's `CostBreakdown` to the parent run on the `contextvars`
  stack. The parent `AgentRunPayload.total_cost` includes both its own
  step costs and all nested child agent costs.

### Added — Unified Provider Pricing Table

- **`get_pricing()` is now cross-provider** — searches OpenAI, Anthropic,
  Groq, and Together AI pricing tables automatically via lazy imports.
  Callers (e.g. `_calculate_cost()`) no longer need to know which provider
  a model belongs to.
- **`list_models()` returns all providers** — aggregates model names from
  all four pricing tables.
- **`_lookup_in_table()` internal helper** — handles exact match,
  date-suffix stripping, and Together AI `org/model` key formats.

### Added — Per-Run Cost Report CLI

- **`spanforge cost run --run-id <id> --input <file.jsonl>`** — new CLI
  subcommand that reads a JSONL events file, filters `llm.cost.*` and
  `llm.trace.agent.completed` events by run ID, and prints a formatted
  table with agent name, status, duration, per-model cost breakdown, and
  total cost. Exit code 1 when no events match; exit code 2 on file errors.

### Added — Consent Boundary Monitoring in Compliance Mapping

- **GDPR Art. 22** (new clause) — `consent.*` and `hitl.*` events now map to
  "Automated Individual Decision-Making — consent and oversight".
- **GDPR Art. 25** — `consent.*` events added to "Data Protection by Design"
  prefix list alongside `llm.redact.*`.

### Added — HITL Hooks in Compliance Mapping

- **EU AI Act Art. 14** (new clause) — `hitl.*` and `consent.*` events now map
  to "Human Oversight — HITL review and escalation".
- **EU AI Act Annex IV.5** — `hitl.*` events added alongside `llm.guard.*` and
  `llm.audit.*`.

### Added — Model Registry Attestation Enrichment

- `ComplianceAttestation` gains `model_owner`, `model_risk_tier`,
  `model_status`, and `model_warnings` fields — populated automatically from
  `ModelRegistry` when a registered model is found.
- **SOC 2 CC6.1** — `model_registry.*` events added to access control clause.
- **NIST MAP 1.1** — `model_registry.*` events added to risk mapping clause.
- Warnings emitted for deprecated, retired, or unregistered models.

### Added — Explainability in Compliance Mapping

- **EU AI Act Art. 13** (new clause) — `explanation.*` events map to
  "Transparency — explainability of AI decisions".
- **NIST MAP 1.1** — `explanation.*` events added alongside trace and eval
  prefixes.
- `ComplianceAttestation` gains `explanation_coverage_pct` field — percentage
  of decision events (`llm.trace.*` / `hitl.*`) with matching `explanation.*`
  events.
- `/compliance/summary` HTTP endpoint now includes `explanation_coverage_pct`.

### Changed

- 40 new compliance mapping tests (76 total); 19 new CostGuard gap tests;
  26 new India PII + dashboard tests; full suite: 3 376 passing.
- Fixed flaky `test_sign_verify_roundtrip` Hypothesis property test by
  suppressing `HealthCheck.too_slow`.

---

## 1.0.0 — 2026-04-13

**GA Release — Production Hardening & Multi-Tenant Support**

This release implements all 28 items from the SpanForge v1.0 GA Addendum.
All changes are backward-compatible; no existing public API was removed.

### Added — GA-01: Signing Key Security

- **`validate_key_strength(org_secret, min_length=None) -> list[str]`** —
  checks key length (min 32 chars / 256-bit), repeated characters, well-known
  placeholders, and mixed character classes. Returns a list of warnings.
- **`check_key_expiry(expires_at) -> tuple[str, int]`** — returns
  `(status, days)` where status is `"no_expiry"`, `"expired"`,
  `"expiring_soon"`, or `"valid"`.
- **`derive_key()` gains `context` parameter** — appends
  `"|" + context` to the passphrase before PBKDF2 derivation, enabling
  environment isolation (e.g. `"staging"` vs `"production"`).
- **`sign()` checks key expiry** — raises `SigningError` when the configured
  key has expired.
- **`SPANFORGE_SIGNING_KEY_MIN_BITS`** env var — configures minimum key length
  in bits (divided by 8 for character count).
- **`SPANFORGE_SIGNING_KEY_EXPIRES_AT`** env var — ISO-8601 date for key expiry.
- **`SPANFORGE_SIGNING_KEY_CONTEXT`** env var — context string for `derive_key`.
- `configure()` now calls `validate_key_strength()` when `signing_key` is set,
  logging warnings for weak keys.

### Added — GA-02: Audit Chain Hardening

- **`ChainVerificationResult`** gains `tombstone_count` and
  `tombstone_event_ids` fields for GDPR right-to-erasure tracking.
- `AuditStream` lock scope narrowed — HMAC computation runs outside the lock
  to reduce contention under concurrent appends.

### Added — GA-03: Deep PII Scanning

- **`PIIScanHit`** dataclass — `pii_type`, `path`, `match_count`, `sensitivity`.
  No `snippet` field (matched values are never exposed).
- **`scan_payload()`** gains `max_depth` parameter (default 10) to cap
  recursion depth.
- **`_luhn_check()`** — Luhn algorithm validation for credit card pattern
  matches, reducing false positives.
- `contains_pii()` and `assert_redacted()` gain `scan_raw` keyword — when
  `True`, also runs regex-based PII scanning (not just `Redactable` checks).

### Added — GA-04: Multi-Tenant Key Resolution

- **`KeyResolver`** protocol — `resolve(org_id) -> str`.
- **`StaticKeyResolver`** — returns the same key for every org.
- **`EnvKeyResolver`** — resolves from `SPANFORGE_KEY_{ORG_ID}` env vars.
- **`DictKeyResolver`** — resolves from an in-memory `{org_id: secret}` dict.
- **`verify_chain()`** gains `key_resolver` and `default_key` parameters —
  per-org key resolution for multi-tenant chains.
- **`AuditStream`** gains `key_resolver` and `require_org_id` parameters —
  per-event key resolution during append, and strict org_id enforcement.
- **`SPANFORGE_REQUIRE_ORG_ID`** env var — when `true`, signing raises
  `SigningError` if `event.org_id` is `None`.

### Added — GA-05: Schema Migration (Working Implementation)

- **`MigrationStats`** dataclass — `total`, `migrated`, `skipped`, `errors`,
  `warnings`, `output_path`, `transformed_fields`.
- **`v1_to_v2()`** now works — no longer raises `NotImplementedError`. Handles
  both `Event` and `dict` inputs. Normalises `model` → `model_id`, coerces tag
  values to strings, re-hashes md5 → sha256 checksums. Idempotent.
- **`migrate_file()`** — bulk JSONL migration with `org_secret` re-signing,
  `target_version`, and `dry_run` support.
- **Internal helpers**: `_rehash_md5_to_sha256()`, `_coerce_tag_values()`.

### Added — GA-06: Async Audit Stream

- **`AsyncAuditStream`** — asyncio-native audit chain using `asyncio.Lock`.
  Mirrors `AuditStream` API: `await stream.append(event)`,
  `await stream.rotate_key(...)`, `await stream.verify()`.

### Added — GA-07: Event Unknown Fields

- **`Event._unknown_fields`** — preserves unrecognised fields during
  `from_dict()` round-trips. Accessible via `event.unknown_fields` property.
  Included in `to_dict()` output for lossless serialisation.

### Added — GA-08: CLI Enhancements

- **`spanforge scan`** — new `--types` filter and `--fail-on-match` exit-code
  flag. Snippet field removed from output (matched values never exposed).
- **`spanforge migrate`** — new `--target-version`, `--sign`, `--dry-run`
  flags for bulk JSONL migration.
- **`spanforge check-health`** — new `--output json` flag, PII scan step,
  egress configuration check, and exit code 1 on any failure.
- **`spanforge rotate-key`** — defaults output to `.rotated.jsonl`,
  re-verifies chain after rotation.

### Changed

- `spanforge.__version__` is `"1.0.0"`.
- Minimum signing key length raised from 0 to 32 characters (256-bit).
- `_server.py` compliance summary includes chain verification and PII data.
- `_server.py` events endpoint supports prefix matching, `hmac_valid` filter,
  and pagination with 30-second poll interval.

### Test Suite

- **3162 tests passing**, 10 skipped, 91.74% line coverage.
- 7 new conformance tests (C011–C017).
- 28 new migration tests, ~30 new signing tests, ~12 new config tests.
- Concurrent `AuditStream` benchmark test.

---

## 1.0.7 — 2026-03-09

**Instrumentation Engine — Seven Tools Complete**

This release delivers the complete instrumentation engine planned in
`spanforge-IMPL-PLAN.md`. All seven tools are implemented, tested, and
fully exported from the top-level `spanforge` namespace. All changes are
backward-compatible; no existing public API was removed.

### Added

- **Tool 1 — `@trace()` decorator** (`spanforge.trace`, `spanforge.export.otlp_bridge`)
  - `@trace(name, span_kind, attributes)` — wraps sync and async functions,
    auto-emits `llm.trace.span` start/end events with timing and error capture.
  - `SpanOTLPBridge`, `span_to_otlp_dict()` — converts spanforge span events
    to OpenTelemetry proto-compatible dicts for OTLP/gRPC export.

- **Tool 2 — Cost Calculation Engine** (`spanforge.cost`)
  - `CostTracker` — tracks cumulative token costs per model across a session.
  - `BudgetMonitor` — per-session USD budget with threshold alerts.
  - `@budget_alert(limit_usd, on_exceed)` — fires a callback when the
    session budget is exceeded.
  - `emit_cost_event()`, `emit_cost_attributed()` — emit `llm.cost.*` events.
  - `cost_summary()` — aggregate totals over a list of `CostRecord` objects.
  - `CostRecord` — immutable dataclass capturing model, tokens, and USD cost.

- **Tool 3 — Tool Call Inspector** (`spanforge.inspect`)
  - `InspectorSession` — context manager that intercepts tool calls within a
    trace and records their arguments, results, latency, and errors.
  - `inspect_trace(trace_id)` — returns a list of `ToolCallRecord` objects
    for a completed trace.
  - `ToolCallRecord` — dataclass with `tool_name`, `arguments`, `result`,
    `duration_ms`, `error`, and `span_id` fields.

- **Tool 4 — Tool Schema Builder** (`spanforge.toolsmith`)
  - `@tool(name, description, tags)` — registers a function as a typed tool
    in the default registry; infers parameters from type annotations.
  - `ToolRegistry` — manages a collection of `ToolSchema` objects; supports
    `register()`, `get()`, `list_tools()`, and `unregister()`.
  - `build_openai_schema(tool)` — renders a `ToolSchema` as an OpenAI
    function-calling JSON object.
  - `build_anthropic_schema(tool)` — renders a `ToolSchema` as an Anthropic
    tool-use JSON object.
  - `ToolSchema`, `ToolParameter`, `ToolValidationError`, `default_registry`.

- **Tool 5 — Retry and Fallback Engine** (`spanforge.retry`)
  - `@retry(max_attempts, backoff, exceptions, on_retry)` — retries a
    sync/async callable with exponential back-off; emits retry events.
  - `FallbackChain(*providers)` — tries providers in order; falls back on
    any exception.
  - `CircuitBreaker(failure_threshold, recovery_timeout)` — open/close/
    half-open state machine; raises `CircuitOpenError` when open.
  - `CostAwareRouter(providers)` — routes each call to the cheapest
    available provider given current `CostTracker` state.
  - `AllProvidersFailedError`, `CircuitOpenError`, `CircuitState`.

- **Tool 6 — Semantic Cache Engine** (`spanforge.cache`)
  - `SemanticCache(backend, similarity_threshold, ttl_seconds, namespace,
    embedder, max_size, emit_events)` — prompt deduplication via cosine
    similarity; pluggable backends.
  - `@cached(threshold, ttl, namespace, backend, tags, emit_events)` —
    decorator for sync and async functions; supports bare `@cached` and
    `@cached(...)` forms.
  - `InMemoryBackend(max_size)` — LRU in-process store, thread-safe.
  - `SQLiteBackend(db_path)` — persistent store using stdlib `sqlite3`.
  - `RedisBackend(host, port, db, prefix)` — distributed store; requires
    the optional `redis` package.
  - Emits `llm.cache.hit`, `llm.cache.miss`, `llm.cache.written`,
    `llm.cache.evicted` events when `emit_events=True`.
  - `CacheBackendError`, `CacheEntry`.

- **Tool 7 — SDK Instrumentation Linter** (`spanforge.lint`)
  - `run_checks(source, filename) -> list[LintError]` — parses Python source
    with `ast` and runs all AO-code checks.
  - `LintError(code, message, filename, line, col)` — dataclass returned by
    every check.
  - **AO001** — `Event()` missing one of `event_type`, `source`, or `payload`.
  - **AO002** — bare `str` literal passed to `actor_id`, `session_id`, or
    `user_id` (should use `Redactable()`).
  - **AO003** — `event_type=` string literal not present in registered
    `EventType` values.
  - **AO004** — LLM provider API call (`.chat.completions.create()` etc.)
    outside a `with tracer.span()` / `agent_run()` context.
  - **AO005** — `emit_span` / `emit_agent_*` called outside `agent_run()` /
    `agent_step()` context.
  - **flake8 plugin** — registered as `AO = "spanforge.lint._flake8:SpanForgeChecker"`
    via `[project.entry-points."flake8.extension"]`; all five codes surfaced
    natively in flake8 / ruff output.
  - **CLI** — `python -m spanforge.lint [FILES_OR_DIRS...]`; exits `0` (clean)
    or `1` (errors found).

### Test suite

- **3 032 tests passing**, 42 skipped, ≥ 92.84 % line and branch coverage.

---

## 1.0.6 — 2026-03-07


**Architect Review — Developer Experience & Reliability Improvements**

All changes are backward-compatible; no existing public API was removed.

### Added

- **`spanforge/testing.py`** — first-class test utilities: `MockExporter`,
  `capture_events()` context manager, `assert_event_schema_valid()`, and
  `trace_store()` isolated store context manager.  Write unit tests for your
  AI pipeline without real exporters.
- **`spanforge/auto.py`** \u2014 integration auto-discovery.  Call
  `spanforge.auto.setup()` to auto-patch every installed LLM integration
  (OpenAI, Anthropic, Ollama, Groq, Together AI).  `setup()` must be called
  explicitly \u2014 `import spanforge.auto` alone does not patch anything.
  `spanforge.auto.teardown()` cleanly unpatches all.
- **Async hooks** (`spanforge._hooks`) — `AsyncHookFn` type alias and four new
  async registration methods on `HookRegistry`: `on_agent_start_async()`,
  `on_agent_end_async()`, `on_llm_call_async()`, `on_tool_call_async()`.
  Async hooks are fired via `asyncio.ensure_future()` on the running loop;
  silently skipped when no loop is running.
- **`spanforge check` CLI** — new `spanforge check` sub-command performs a
  five-step end-to-end health check (config → event creation → schema
  validation → export pipeline → trace store) and exits 0/1.
- **`trace_store()` context manager** (`spanforge.trace_store`) — installs a
  fresh, isolated `TraceStore` for the duration of a `with` block and restores
  the previous singleton on exit.  Exported at package level.
- **Export retry with back-off** (`spanforge._stream`) — the dispatch pipeline
  now retries failed exports up to `export_max_retries` times (default: 3)
  with exponential back-off (0.5 s, 1 s, 2 s …).  Configurable via
  `spanforge.configure(export_max_retries=N)`.
- **Structured export logging** — `logging.getLogger("spanforge.export")` now
  emits `WARNING`-level messages on every export error and `DEBUG`-level
  messages on each retry attempt.
- **Export error counter** — `spanforge._stream.get_export_error_count()`
  returns the cumulative count of export errors since process start; useful
  for health-check endpoints.
- **`unpatch()` / `is_patched()`** for all three callback-based integrations
  (`crewai`, `langchain`, `llamaindex`) — consistent unpatch API across every
  integration module.
- **`NotImplementedWarning`** (`spanforge.migrate`) — `v1_to_v2()` now emits a
  `NotImplementedWarning` via `warnings.warn()` before raising
  `NotImplementedError` so tools that filter warnings still see the signal.
  `v1_to_v2` is removed from `spanforge.__all__`.
- **`assert_no_sunset_reached()`** (`spanforge.assert_no_sunset_reached`) — CI
  helper that raises `AssertionError` listing any `SunsetPolicy` records whose
  `sunset` version is ≤ the current SDK version.
- **Frozen payload dataclasses** — `SpanPayload`, `AgentStepPayload`, and
  `AgentRunPayload` are now `@dataclass(frozen=True)`; attempts to mutate a
  completed span record now raise `FrozenInstanceError` immediately.
- **Custom exporter tutorial** — new doc at
  `docs/user_guide/custom_exporters.md` covering the `SyncExporter` protocol,
  HTTP + batching examples, error handling, and test patterns.

### Changed

- `spanforge.__version__` bumped from `"1.0.5"` to `"1.0.6"`.
- `HookRegistry.__repr__` now includes both sync and async hook counts.
- `spanforge.__all__` updated: added `AsyncHookFn`, `assert_no_sunset_reached`,
  `NotImplementedWarning`, `trace_store`, `testing`, `auto`; removed
  `v1_to_v2`.

---

## 2.0.0 (previous) — 2026-03-07

**Phases 1–5 — Core Foundation, Compliance Infrastructure, Developer Experience, Production Analytics, Ecosystem Expansion**

This release is a comprehensive upgrade of the SDK runtime. All changes are
backward-compatible unless noted; no existing public API was removed.

### Added — Phase 1: Core Foundation

- **`contextvars`-based context propagation** — the three internal stacks
  (`_span_stack_var`, `_run_stack_var`) are now `contextvars.ContextVar` tuples
  instead of `threading.local` lists. Context flows correctly across `asyncio`
  tasks, `loop.run_in_executor` thread pools, and `concurrent.futures` workers.
  Sync code is unaffected.
- **`copy_context()`** (`spanforge.copy_context`) — returns a shallow copy of
  the current `contextvars.Context` for manually spawned threads or executor
  tasks. Re-exported at the top-level `spanforge` package.
- **Async context-manager support** — `SpanContextManager`,
  `AgentRunContextManager`, and `AgentStepContextManager` now implement
  `__aenter__` / `__aexit__` so `async with tracer.span(...)`,
  `async with tracer.agent_run(...)`, and `async with tracer.agent_step(...)`
  all work without any API change.
- **`Trace` class** (`spanforge.Trace`) — a first-class object returned by
  `start_trace()` that holds a reference to the root span and accumulates all
  child spans.  Convenience methods: `llm_call()`, `tool_call()`, `end()`,
  `to_json()`, `save()`, `print_tree()`, `summary()`.
  Supports `with start_trace(...) as trace:` and `async with start_trace(...) as trace:`.
- **`start_trace(agent_name, **attributes)`** (`spanforge.start_trace`) — opens
  a new trace, pushes a root `AgentRunContextManager` onto the context stack,
  and returns a `Trace` object that acts as the root context for all child
  spans.  Re-exported at the top-level `spanforge` package.

### Added — Phase 2: Compliance Infrastructure

- **`SpanEvent` dataclass** (`spanforge.namespaces.trace.SpanEvent`) — a
  named, timestamped event (nanosecond resolution) with an open-ended
  `metadata: dict` field.  Participates in `to_dict()` / `from_dict()`
  round-trips.
- **`Span.add_event(name, metadata=None)`** — append a `SpanEvent` to the
  active span at any point during its lifetime.
- **`SpanErrorCategory` type alias** (`spanforge.types.SpanErrorCategory`) —
  typed `Literal` for `"agent_error"`, `"llm_error"`, `"tool_error"`,
  `"timeout_error"`, `"unknown_error"`. Built-in exception types
  (`TimeoutError`, `asyncio.TimeoutError`) are auto-mapped to
  `"timeout_error"` by `Span.record_error()`.
- **`Span.record_error(exc, category=...)`** — enhanced to accept an optional
  `category: SpanErrorCategory`; stores `error_category` on the span and
  in `SpanPayload.error_category`.
- **`Span.set_timeout_deadline(seconds)`** — schedules a background timer that
  sets `status = "timeout"` and `error_category = "timeout_error"` if the
  span is not closed within the deadline.
- **LLM span schema extensions** — `SpanPayload` gains three optional fields:
  `temperature: float | None`, `top_p: float | None`,
  `max_tokens: int | None`. All existing calls that do not set these fields
  are unaffected.
- **Tool span schema extensions** — `ToolCall` gains:
  - `arguments_raw: str | None` — raw tool arguments (populated only when
    `SpanForgeConfig.include_raw_tool_io = True`; redaction policy is applied
    before storage).
  - `result_raw: str | None` — raw tool result (same opt-in flag).
  - `retry_count: int | None` — zero-based retry counter.
  - `external_api: str | None` — identifier for the external service called.
- **`SpanForgeConfig.include_raw_tool_io`** (`bool`, default `False`) — opt-in
  flag that controls whether `arguments_raw` / `result_raw` are stored. When a
  `RedactionPolicy` is configured, raw values are passed through
  `redact.redact_value()` before storage.

### Added — Phase 3: Developer Experience

- **`spanforge.debug`** module — standalone debug utilities (also available as
  methods on `Trace`):
  - **`print_tree(spans, *, file=None)`** — pretty-prints a hierarchical span
    tree with Unicode box-drawing characters, duration, token counts, and
    costs. Respects the `NO_COLOR` environment variable.
  - **`summary(spans) -> dict`** — returns an aggregated statistics
    dictionary: `trace_id`, `agent_name`, `total_duration_ms`, `span_count`,
    `llm_calls`, `tool_calls`, `total_input_tokens`, `total_output_tokens`,
    `total_cost_usd`, `errors`.
  - **`visualize(spans, output="html", *, path=None) -> str`** — generates a
    self-contained HTML Gantt-timeline string (no external dependencies).
    Pass `path="trace.html"` to write directly to a file.
- `print_tree`, `summary`, `visualize` re-exported from the top-level
  `spanforge` package.
- **Sampling controls** added to `SpanForgeConfig`:
  - `sample_rate: float = 1.0` — fraction of traces to emit (0.0–1.0).
    Decision is made per `trace_id` (deterministic SHA-256 hash) so all
    spans of a trace are always sampled together.
  - `always_sample_errors: bool = True` — spans/traces with
    `status = "error"` or `"timeout"` are always emitted regardless of
    `sample_rate`.
  - `trace_filters: list[Callable[[Event], bool]]` — custom per-event predicates
    evaluated after the probabilistic gate.
- **`SPANFORGE_SAMPLE_RATE`** environment variable — overrides
  `sample_rate` at startup.

### Added — Phase 4: Production Analytics

- **`spanforge.metrics`** module:
  - **`aggregate(events) -> MetricsSummary`** — single-call aggregation
    over any `Iterable[Event]` (file, in-memory list, or `TraceStore`).
  - **`MetricsSummary`** dataclass — `trace_count`, `span_count`,
    `agent_success_rate`, `avg_trace_duration_ms`, `p50_trace_duration_ms`,
    `p95_trace_duration_ms`, `total_input_tokens`, `total_output_tokens`,
    `total_cost_usd`, `llm_latency_ms` (`LatencyStats`),
    `tool_failure_rate`, `token_usage_by_model`, `cost_by_model`.
  - **`agent_success_rate(events)`**, **`llm_latency(events)`**,
    **`tool_failure_rate(events)`**, **`token_usage(events)`** — focused
    single-metric helpers.
  - Re-exported as `import spanforge; spanforge.metrics.aggregate(events)`.
- **`spanforge._store.TraceStore`** — in-memory ring buffer (bounded to
  `SpanForgeConfig.trace_store_size`, default 100) that retains the last N
  traces for programmatic access:
  - `get_trace(trace_id)` → `list[Event] | None`
  - `get_last_agent_run()` → `list[Event] | None`
  - `list_tool_calls(trace_id)` → `list[SpanPayload]`
  - `list_llm_calls(trace_id)` → `list[SpanPayload]`
  - `clear()`
- **Module-level convenience functions** re-exported from `spanforge`:
  `get_trace()`, `get_last_agent_run()`, `list_tool_calls()`,
  `list_llm_calls()`.
- **`SpanForgeConfig.enable_trace_store`** (`bool`, default `False`) — enables
  the `TraceStore` ring buffer. When a `RedactionPolicy` is configured, events
  are redacted before storage.
- **`SpanForgeConfig.trace_store_size`** (`int`, default `100`) — maximum
  number of traces retained in the ring buffer.
- **`SPANFORGE_ENABLE_TRACE_STORE=1`** environment variable override.

### Added — Phase 5: Ecosystem Expansion

- **`spanforge._hooks.HookRegistry`** — callback registry for global span
  lifecycle hooks with decorator API:
  - `@hooks.on_agent_start` / `@hooks.on_agent_end`
  - `@hooks.on_llm_call`
  - `@hooks.on_tool_call`
  - `hooks.clear()` — unregister all hooks (useful in tests)
  - Thread-safe via `threading.RLock`.
- **`spanforge.hooks`** — module-level singleton `HookRegistry`. Re-exported
  from the top-level `spanforge` package.
  ```python
  @spanforge.hooks.on_llm_call
  def my_hook(span):
      print(f"LLM called: {span.model}")
  ```
- **`spanforge.integrations.crewai`** — CrewAI event handler:
  - `SpanForgeCrewAIHandler` — callback handler that emits `llm.trace.*`
    events for agent actions, task lifecycle, and tool calls. Follows the
    same pattern as `LLMSchemaCallbackHandler`.
  - `patch()` — convenience function that registers the handler into CrewAI
    globally (guards with `importlib.util.find_spec("crewai")` so the module
    is safely importable without CrewAI installed).

### Changed

- `spanforge.__version__`: `1.0.6` → `2.0.0`

---

## 1.0.6 — 2026-03-07

**Phase 6 — OpenAI Auto-Instrumentation**

### Added

- **`spanforge.integrations.openai`** — zero-boilerplate OpenAI tracing.
  Calling `patch()` monkey-patches both `openai.resources.chat.completions.Completions.create`
  (sync) and `AsyncCompletions.create` (async) so every chat completion
  automatically populates the active `spanforge` span with token usage, model
  info, and a computed cost breakdown.
  - `patch()` / `unpatch()` — idempotent lifecycle; safe to call multiple
    times; `unpatch()` fully restores original methods.
  - `is_patched()` — returns `True` after `patch()`, `False` if OpenAI is not
    installed or `unpatch()` has been called.
  - `normalize_response(response) -> (TokenUsage, ModelInfo, CostBreakdown)` —
    extracts all available token counts (input, output, total, cached,
    reasoning) and computes USD cost from the static pricing table.
  - `_auto_populate_span(response)` — updates the active span if one is
    present; silently skips if no span is active or if the span already has
    `token_usage` set; swallows all instrumentation errors so they never
    surface in user code.
- **`spanforge.integrations._pricing`** — static OpenAI pricing table (USD / 1 M
  tokens) covering GPT-4o, GPT-4o-mini, GPT-4 Turbo, GPT-4, GPT-3.5 Turbo,
  o1, o1-mini, o1-preview, o3-mini, o3, and the text-embedding-3-* / ada-002
  families.  Prices reflect OpenAI's published rates as of `2026-03-04`.
  - `get_pricing(model)` — exact lookup with automatic date-suffix stripping
    fallback (e.g. `"gpt-4o-2024-11-20"` → `"gpt-4o"`).
  - `list_models()` — sorted list of all known model names.
  - `PRICING_DATE = "2026-03-04"` — snapshot date attached to every
    `CostBreakdown` for auditability.
- **68 new tests** in `tests/test_phase6_openai_integration.py` covering
  pricing table correctness, `normalize_response` field mapping, all
  `_compute_cost` branches (cached discount, o1/o3 reasoning rate, non-negative
  clamp, pricing-date attachment), `_auto_populate_span` (including the
  `except Exception: pass` instrumentation-error-swallow branch), patch
  lifecycle, async wrapper, and end-to-end tracer integration.

### Fixed

- **`openai.py` — `_PATCH_FLAG` consistency**: `patch()` and `unpatch()` now
  use `setattr` / `delattr` with the `_PATCH_FLAG` constant instead of
  hardcoding the string `"_spanforge_patched"`, eliminating a silent mismatch
  risk if the constant is ever renamed.
- **`openai.py` docstring**: usage example corrected from `spanforge.span()`
  to `spanforge.tracer.span()`.

### Coverage

- `spanforge/integrations/openai.py`: **100 %** (was 99 %)
- `spanforge/integrations/_pricing.py`: **100 %**
- Total suite: **2 407 tests**, **97.00 % coverage**

---

## 1.0.5 — 2026-03-06

**Version bump**

- Bumped version to 1.0.5 across `pyproject.toml`, `spanforge/__init__.py`, docs, and tests.
- Completed full rename from `tracium` to `spanforge` across the entire codebase.

---

## 1.0.4 — 2026-03-05

**Version bump**

- Bumped version to 1.0.4 across `pyproject.toml`, `spanforge/__init__.py`, docs, and tests.

---

## 1.0.3 — 2026-03-05

**Version bump**

- Updated version references in `docs/index.md` and `docs/changelog.md` to match `pyproject.toml`.

---

## 1.0.2 — 2026-03-04

**Packaging fix**

- Added PyPI badge (links to `https://pypi.org/project/spanforge/`) to README, docs index, and installation page.
- Fixed remaining relative spanforge Standard link in `docs/index.md`.

---

## 1.0.1 — 2026-03-04

**Packaging fix**

- Fixed broken spanforge Standard link on PyPI project page — now points to `https://www.getspanforge.com/standard`.

---

## 1.0.0 — 2026-03-04

**Phase 10 — CLI Tooling**

- **`spanforge validate EVENTS_JSONL`** — schema-validates every event in a
  JSONL file; prints per-line errors.
- **`spanforge audit-chain EVENTS_JSONL`** — verifies HMAC signing-chain
  integrity; reads `spanforge_SIGNING_KEY` from the environment.
- **`spanforge inspect EVENT_ID EVENTS_JSONL`** — pretty-prints a single event
  looked up by `event_id`.
- **`spanforge stats EVENTS_JSONL`** — prints a summary of event counts, token
  totals, estimated cost, and timestamp range.

**Phase 11 — Security & Privacy Pipeline**

- **Auto-redaction via `configure()`** — passing `redaction_policy=` to
  `configure()` wires `RedactionPolicy.apply()` into the `_dispatch()` path;
  every emitted span/event is redacted before being handed to the exporter.
- **Auto-signing via `configure()`** — passing `signing_key=` to
  `configure()` wires HMAC-SHA256 signing into the dispatch path; every event
  is signed and chained to the previous one automatically.
- **Pipeline order guaranteed** — redaction always runs before signing, so
  each signature covers the already-redacted payload.
- **`_reset_exporter()` closes file handles** — calling `_reset_exporter()`
  now flushes and closes any open `SyncJSONLExporter` file handle and clears
  the HMAC chain state, preventing `ResourceWarning` in tests and on shutdown.
- **`examples/`** — four runnable sample scripts: `openai_chat.py`,
  `agent_workflow.py`, `langchain_chain.py`, `secure_pipeline.py`.
- **Version**: `0.2.0` → `1.0.0`; coverage threshold: `99 %` → `90 %`.

---

## 0.1.0 — 2026-03-04

### Changed

- **Package renamed** from `llm-toolkit-schema` to `spanforge` — PyPI distribution is `spanforge` (`pip install spanforge`), import name is `spanforge`. The old package name is a deprecated shim that re-exports from `spanforge` and emits a `DeprecationWarning`.
- **Schema version** bumped to `2.0` (SpanForge AI Compliance Standard RFC-0001 v2.0).
- **36 canonical `EventType` values** registered (RFC-0001 Appendix B).
- **11 namespace payload modules** ship 42 v2.0 dataclasses under `spanforge.namespaces.*`.
- **`TokenUsage`** fields renamed: `prompt_tokens` → `input_tokens`, `completion_tokens` → `output_tokens`, `total` → `total_tokens`.
- **`ModelInfo`** field change: `provider` (plain string) replaced by `system` (`GenAISystem` enum, OTel `gen_ai.system` aligned).
- **`SpanPayload`** replaces `SpanCompletedPayload` / `TracePayload`. New sibling payloads: `AgentStepPayload`, `AgentRunPayload`.
- **`CacheHitPayload`** replaces `CachePayload`; `CostTokenRecordedPayload` replaces `CostPayload`; `EvalScoreRecordedPayload` replaces `EvalPayload`; `FenceValidatedPayload` replaces `FencePayload`; `PromptRenderedPayload` replaces `PromptPayload`; `RedactPiiDetectedPayload` replaces `RedactPayload`; `TemplateRegisteredPayload` replaces `TemplatePayload`; `DiffComputedPayload` replaces `DiffPayload`.
- **`spanforge.namespaces.audit`** — new module: `AuditKeyRotatedPayload`, `AuditChainVerifiedPayload`, `AuditChainTamperedPayload`.

---

## 1.0.0-rc.3 — 2026-03-15

### Added

- **`OTelBridgeExporter`** (`spanforge.export.otel_bridge`) — exports
  events through any configured OpenTelemetry `TracerProvider`. Requires the
  `[otel]` extra (`opentelemetry-sdk>=1.24`). Unlike `OTLPExporter`, this
  bridge uses the SDK's span lifecycle so all registered `SpanProcessor`
  instances (sampling, batching, auto-instrumentation hooks) fire normally.
- **`make_traceparent(trace_id, span_id, *, sampled=True)`**
  (`spanforge.export.otlp`) — constructs a W3C TraceContext
  `traceparent` header string (RFC 9429).
- **`extract_trace_context(headers)`** (`spanforge.export.otlp`) —
  parses `traceparent` / `tracestate` headers and returns a dict of
  `{trace_id, span_id, sampled[, tracestate]}`.
- **`gen_ai.*` semantic convention attributes** (GenAI semconv 1.27+) —
  `to_otlp_span()` now emits `gen_ai.system`, `gen_ai.request.model`,
  `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
  `gen_ai.operation.name`, and `gen_ai.response.finish_reasons` from the
  corresponding `payload.*` fields, enabling native LLM dashboards in Grafana,
  Honeycomb, and Dynatrace.

### Fixed

- **`deployment.environment.name`** — `ResourceAttributes.to_otlp()` now
  emits the semconv 1.21+ key `deployment.environment.name` instead of the
  legacy `deployment.environment`.
- **`spanKind`** — `to_otlp_span()` now sets `kind: 3` (CLIENT) as required
  by the OTLP specification.
- **`traceFlags`** — `to_otlp_span()` now sets `traceFlags: 1` (sampled) on
  every span context.
- **`endTimeUnixNano`** — computed correctly as
  `startTimeUnixNano + payload.duration_ms × 1 000 000`; previously omitted.
- **`status.code` / `status.message`** — `payload.status` values `"error"` and
  `"timeout"` now map to OTLP `STATUS_CODE_ERROR` (2); `"ok"` maps to
  `STATUS_CODE_OK` (1). Previously the status block was always empty.

---

## 1.0.0-rc.2 — 2026-03-15

### Fixed

- **`Event.payload`** now returns a read-only `MappingProxyType` — mutating
  the returned object no longer silently corrupts event state.
- **`EventGovernancePolicy(strict_unknown=True)`** now correctly raises
  `GovernanceViolationError` for unregistered event types (was a no-op
  previously); docstring corrected to match actual behaviour.
- **`_cli.py`** — broad `except Exception` replaced with typed
  `(DeserializationError, SchemaValidationError, KeyError, TypeError)`,
  preventing silent swallowing of unexpected errors.
- **`stream.py`** — broad `except Exception` in `EventStream.from_file` and
  `EventStream.from_kafka` replaced with `(LLMSchemaError, ValueError)`.
- **`validate.py`** — checksum regex tightened to `^sha256:[0-9a-f]{64}$`
  and signature regex to `^hmac-sha256:[0-9a-f]{64}$`, aligning with the
  prefixes actually produced by `signing.py` (bare 64-hex patterns accepted
  invalid values).
- **`export/datadog.py`**:
  - Fallback span/trace IDs are now deterministic SHA-256 derivations of the
    event ID instead of Python `hash()` (non-reproducible across processes).
  - Span start timestamp uses `event.timestamp` rather than wall-clock time.
  - `dd_site` is validated as a hostname (no scheme/path).
  - `agent_url` is validated as an `http://` or `https://` URL.
- **`export/otlp.py`** — `export_batch` now chunks the event list by
  `batch_size` and issues one request per chunk; previously the parameter
  was accepted but never applied.  URL scheme validated on construction.
- **`export/webhook.py`** — URL scheme validated on construction (`http://`
  or `https://` only).
- **`export/grafana.py`** — URL scheme validated on construction.
- **`redact.py`** — `_has_redactable` / `_count_redactable` use the
  `collections.abc.Mapping` ABC instead of `dict`, so payloads built from
  `MappingProxyType` or other mapping types are handled correctly.

### Added

- **`GuardPolicy`** (`spanforge.namespaces.guard`) — runtime
  input/output guardrail enforcement with configurable fail-open / fail-closed
  mode and callable checker injection.
- **`FencePolicy`** (`spanforge.namespaces.fence`) — structured-output
  validation driver with retry-sequence loop and `max_retries` limit.
- **`TemplatePolicy`** (`spanforge.namespaces.template`) — variable
  presence checking and output validation for prompt-template workflows.
- **`iter_file(path)`** (`spanforge.stream`) — synchronous generator
  that streams events from an NDJSON file without buffering the entire file.
- **`aiter_file(path)`** (`spanforge.stream`) — async-generator
  equivalent of `iter_file`.

---

## 1.0.0-rc.1 — 2026-03-01

### Added

**Phase 7 — Enterprise Export Backends**

- **`DatadogExporter`** (`spanforge.export.datadog`) — async exporter
  that sends events as Datadog APM trace spans (via the local Agent) and as
  Datadog metrics series (via the public API). No `ddtrace` dependency.
- **`DatadogResourceAttributes`** — frozen dataclass with `service`, `env`,
  `version`, and `extra` fields; `.to_tags()` for tag-string serialisation.
- **`GrafanaLokiExporter`** (`spanforge.export.grafana`) — async
  exporter that pushes events to Grafana Loki via the `/loki/api/v1/push`
  HTTP endpoint. Supports multi-tenant deployments via `X-Scope-OrgID`.
- **`ConsumerRegistry`** / **`ConsumerRecord`** (`spanforge.consumer`)
  — thread-safe registry for declaring schema-namespace dependencies at startup.
  `assert_compatible()` raises `IncompatibleSchemaError` on version mismatches.
- **`EventGovernancePolicy`** (`spanforge.governance`) — data-class
  policy with blocked types, deprecated-type warnings, and arbitrary custom
  rule callbacks. Module-level `set_global_policy()` / `check_event()`.
- **`GovernanceViolationError`**, **`GovernanceWarning`** — governance
  exception and warning types.

**Phase 8 — Ecosystem Integrations & Kafka**

- **`EventStream.from_kafka()`** — classmethod constructor that drains a Kafka
  topic into an `EventStream`. Requires optional extra `kafka`.
- **`DeprecationRegistry`** / **`DeprecationNotice`**
  (`spanforge.deprecations`) — structured per-event-type deprecation
  tracking with `warn_if_deprecated()` and `list_deprecated()`.
- **`LLMSchemaCallbackHandler`** (`spanforge.integrations.langchain`)
  — LangChain `BaseCallbackHandler` that emits `llm.trace.*` events for all LLM
  and tool invocations. Requires optional extra `langchain`.
- **`LLMSchemaEventHandler`** (`spanforge.integrations.llamaindex`)
  — LlamaIndex callback event handler. Requires optional extra `llamaindex`.

**Phase 9 — v2 Migration Framework**

- **`SunsetPolicy`** (`spanforge.migrate`) — `Enum` classifying
  removal urgency: `NEXT_MAJOR`, `NEXT_MINOR`, `LONG_TERM`, `UNSCHEDULED`.
- **`DeprecationRecord`** (`spanforge.migrate`) — frozen dataclass
  capturing `event_type`, `since`, `sunset`, `sunset_policy`, `replacement`,
  `migration_notes`, and `field_renames` for structured migration guidance.
- **`v2_migration_roadmap()`** — returns all 9 deprecation records for event
  types that will change in v2.0, sorted by `event_type`.
- **CLI: `list-deprecated`** — prints all deprecation notices from the global
  registry.
- **CLI: `migration-roadmap [--json]`** — prints the v2 migration roadmap in
  human-readable or JSON form.
- **CLI: `check-consumers`** — lists all registered consumers and their
  compatibility status against the installed schema version.

### Changed

- Version: `1.0.1` → `1.0.0-rc.1`
- `export/__init__.py` now re-exports `DatadogExporter`,
  `DatadogResourceAttributes`, and `GrafanaLokiExporter`.
- Top-level `spanforge` package re-exports all Phase 7/8/9 public
  symbols.

### Optional extras added

| Extra | Enables |
|-------|---------|
| `kafka` | `EventStream.from_kafka()` via `kafka-python>=2.0` |
| `langchain` | `LLMSchemaCallbackHandler` via `langchain-core>=0.2` |
| `llamaindex` | `LLMSchemaEventHandler` via `llama-index-core>=0.10` |
| `datadog` | `DatadogExporter` (stdlib-only transport; extra reserved for future `ddtrace` integration) |
| `all` | All optional extras in one install target |

---

## 1.0.1 — 2026-03-01

### Changed

- **Python package renamed** from `llm_schema` to `spanforge`.
  The import path is now `import spanforge` (or
  `from spanforge import ...`).
  The distribution name `spanforge` and all runtime behaviour are
  unchanged. This is the canonical, permanently stable import name.
- Version: `1.0.0` → `1.0.1`

---

## 1.0.0 — 2026-03-01

**General Availability release.** The public API is now stable and covered
by semantic versioning guarantees.

### Added

- **Compliance package** (`spanforge.compliance`) — programmatic v1.0
  compatibility checklist (CHK-1 through CHK-5), multi-tenant isolation
  verification, and audit chain integrity suite. All checks are callable
  without a pytest dependency.
- **`test_compatibility()`** — applies the five-point adoption checklist to
  any sequence of events. Powers the new `spanforge check-compat` CLI command.
- **`verify_tenant_isolation()` / `verify_events_scoped()`** — detect
  cross-tenant data leakage in multi-org deployments.
- **`verify_chain_integrity()`** — wraps `verify_chain()` with gap,
  tamper, and timestamp-monotonicity diagnostics.
- **`spanforge check-compat`** CLI sub-command — reads a JSON file of
  serialised events and prints compatibility violations.
- **`spanforge.migrate`** — `MigrationResult` dataclass and
  `v1_to_v2()` scaffold (raises `NotImplementedError`; full implementation
  ships in Phase 9).
- Performance benchmark test suite (`tests/test_benchmarks.py`,
  `@pytest.mark.perf`) validating all NFR targets.

### Changed

- Version: `0.5.0` → `1.0.0`
- PyPI classifier: `Development Status :: 3 - Alpha` →
  `Development Status :: 5 - Production/Stable`

---

## 0.5.0 — 2026-02-22

### Added

- **Namespace payload dataclasses** for all 10 reserved namespaces
  (`llm.trace.*`, `llm.cost.*`, `llm.cache.*`, `llm.diff.*`,
  `llm.eval.*`, `llm.fence.*`, `llm.guard.*`, `llm.prompt.*`,
  `llm.redact.*`, `llm.template.*`). The `llm.trace` payload is
  **FROZEN** at v1 — no breaking changes permitted.
- **`schemas/v1.0/schema.json`** — published JSON Schema for the event envelope.
- **`validate_event()`** — validates an event against the JSON Schema with an
  optional `jsonschema` backend; falls back to structural stdlib checks.

---

## 0.4.0 — 2026-02-15

### Added

- **`OTLPExporter`** — async OTLP/HTTP JSON exporter with retry, gzip
  compression, and configurable resource attributes.
- **`WebhookExporter`** — async HTTP webhook exporter with configurable
  headers, retry backoff, and timeout.
- **`JSONLExporter`** — synchronous JSONL file exporter with optional
  per-event gzip compression.
- **`EventStream`** — in-process event router with type filters, org/team
  scoping, sampling, and fan-out to multiple exporters.

---

## 0.3.0 — 2026-02-08

### Added

- **`sign()` / `verify()`** — HMAC-SHA256 event signing and verification
  (`sha256:` payload checksum + `hmac-sha256:` chain signature).
- **`verify_chain()`** — batch chain verification with gap detection and
  tampered-event identification.
- **`AuditStream`** — sequential event stream that signs and links every
  appended event via `prev_id`.
- **Key rotation** — `AuditStream.rotate_key()` emits a signed rotation
  event and switches the active HMAC key.
- **`assert_verified()`** — strict raising variant of `verify()`.

---

## 0.2.0 — 2026-02-01

### Added

- **PII redaction framework** — `Redactable`, `Sensitivity`,
  `RedactionPolicy`, `RedactionResult`, `contains_pii()`,
  `assert_redacted()`.
- **Pydantic v2 model layer** — `spanforge.models.EventModel` with
  `from_event()` / `to_event()` round-trip and `model_json_schema()`.

---

## 0.1.0 — 2026-01-25

### Added

- **Core `Event` dataclass** — frozen, validated, zero external dependencies.
- **`EventType` enum** — exhaustive registry of all 50+ first-party event types
  across 10 namespaces plus audit types.
- **ULID utilities** — `generate()`, `validate()`, `extract_timestamp_ms()`.
- **`Tags`** dataclass — arbitrary `str → str` metadata.
- **JSON serialisation** — `Event.to_dict()`, `Event.to_json()`,
  `Event.from_dict()`, `Event.from_json()`.
- **`Event.validate()`** — full structural validation of all fields.
- **`is_registered()`**, **`validate_custom()`**, **`namespace_of()`** —
  event-type introspection helpers.
- **Domain exceptions hierarchy** — `LLMSchemaError` base with
  `SchemaValidationError`, `ULIDError`, `SerializationError`,
  `DeserializationError`, `EventTypeError`.
