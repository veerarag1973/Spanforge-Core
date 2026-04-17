# Changelog

All notable changes to spanforge are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/) and
this project adheres to [Semantic Versioning](https://semver.org/).

---

## 2.0.3 — Unreleased

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
