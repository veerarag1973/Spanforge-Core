# SpanForge â€” Implementation Roadmap
### HallucCheck v6.0 Integration + Industry-Standard Platform Hardening

> **Document scope:** This roadmap covers every engineering deliverable needed to
> (a) fully satisfy the HallucCheck v6.0 SpanForge dependency spec, and
> (b) raise each service to the level expected of a production-grade, enterprise-ready
> AI observability platform.  Every item is grounded in either the spec contract or a
> recognised industry standard (OpenTelemetry, SOC 2, ISO 27001, EU AI Act, OWASP,
> SLSA, NIST AI RMF, GDPR/CCPA/DPDP/HIPAA, eIDAS).

---

## Table of Contents

1. [Guiding Principles](#1-guiding-principles)
2. [Baseline â€” What Already Exists](#2-baseline--what-already-exists)
3. [Milestone Overview & Timeline](#3-milestone-overview--timeline)
4. [Phase 1 â€” SDK Foundation & Identity (sf-identity)](#4-phase-1--sdk-foundation--identity-sf-identity)
5. [Phase 2 â€” Secrets Scanning (sf-secrets)](#5-phase-2--secrets-scanning-sf-secrets)
6. [Phase 3 â€” PII Service Hardening (sf-pii)](#6-phase-3--pii-service-hardening-sf-pii)
7. [Phase 4 â€” Audit Service High-Level API (sf-audit)](#7-phase-4--audit-service-high-level-api-sf-audit)
8. [Phase 5 â€” Compliance Evidence Chain (sf-cec)](#8-phase-5--compliance-evidence-chain-sf-cec)
9. [Phase 6 â€” Observability Named SDK (sf-observe)](#9-phase-6--observability-named-sdk-sf-observe)
10. [Phase 7 â€” Alert Routing Service (sf-alert)](#10-phase-7--alert-routing-service-sf-alert)
11. [Phase 8 â€” CI/CD Gate Pipeline (sf-gate)](#11-phase-8--cicd-gate-pipeline-sf-gate)
12. [Phase 9 â€” Integration Config & Local Fallback](#12-phase-9--integration-config--local-fallback)
13. [Phase 10 â€” T.R.U.S.T. Scorecard & HallucCheck Contract](#13-phase-10--trust-scorecard--halluccheck-contract)
14. [Phase 11 â€” Enterprise Hardening & Supply Chain Security](#14-phase-11--enterprise-hardening--supply-chain-security)
15. [Phase 12 â€” Developer Experience & Ecosystem](#15-phase-12--developer-experience--ecosystem)
16. [Non-Functional Requirements](#16-non-functional-requirements)
17. [Story Index](#17-story-index)
18. [Definition of Done](#18-definition-of-done)

---

## 1. Guiding Principles

| # | Principle | Implication |
|---|-----------|-------------|
| P1 | **HallucCheck does not reinvent cross-cutting infrastructure** | Every auth, audit, PII, secrets, gate, CEC, observe, and alert path goes through a named SpanForge SDK method â€” never a raw HTTP call or duplicated library. |
| P2 | **SDK is the only integration surface** | The SDK handles retry, auth-token refresh, circuit-breaking, and local-mode fallback internally.  HallucCheck callers see one method. |
| P3 | **Lean failure surfaces** | Every service degrades gracefully under `local_fallback.enabled=true`.  Enterprise mode disables fallback and fails hard. |
| P4 | **Zero secrets in code or logs** | Org secrets, HMAC keys, JWT private keys, and API key values are never embedded in exception messages, `__repr__`, or log lines. |
| P5 | **Compliance is structural, not bolted on** | GDPR, DPDP, HIPAA, EU AI Act, ISO 27001, SOC 2, and NIST AI RMF controls are embedded in the data model, not checked in a separate compliance layer. |
| P6 | **OpenTelemetry-first** | All observability primitives conform to OTel Semantic Conventions v1.x and W3C TraceContext.  No proprietary span formats. |
| P7 | **Policy-as-code** | Gate pass/fail logic, alert routing rules, and compliance mappings are declarative YAML/JSON files, not hard-coded conditionals. |
| P8 | **Cryptographic integrity everywhere** | Every audit record, CEC bundle, and signed artifact carries an HMAC-SHA256 or RSA-SHA256 signature that a third party can independently verify. |

---

## 2. Baseline â€” What Already Exists

The following capabilities are **production-ready** and require only thin adapter work to surface as named SDK methods:

| Service | Existing Asset | Location |
|---------|---------------|----------|
| sf-audit | `AuditStream`, `sign()`, `verify()`, `verify_chain()`, `rotate_key()`, `AsyncAuditStream` | `signing.py` |
| sf-audit | `AppendOnlyJSONLExporter` with WORM backend protocol (S3 Object Lock, GCS, Azure Immutable) | `export/append_only.py` |
| sf-audit | `AuditStorageError` exception hierarchy | `exceptions.py` |
| sf-observe | OTLP, Datadog, Grafana Loki, `otel_bridge`, `otel_passthrough`, Cloud, Webhook exporters | `export/` |
| sf-observe | `BatchExporter` with per-exporter circuit breaker | `_batch_exporter.py` |
| sf-observe | T.R.U.S.T. Framework CLI handlers scaffolding | `_cli.py` |
| sf-pii | `PIIScanHit`, `PIIScanResult`, `scan_payload()`, `RedactionPolicy`, `Redactable`, `Sensitivity` | `redact.py` |
| sf-pii | Presidio `AnalyzerEngine` wrapper with 18-entity map including `IN_AADHAAR`, `MEDICAL_LICENSE`, `NRP` | `presidio_backend.py` |
| sf-pii | DPDP Act India patterns (`DPDP_PATTERNS`) | `redact.py` |
| sf-pii | `PIILeakageScorer` eval metric | `eval.py` |
| sf-alert | `SlackAlerter`, `TeamsAlerter`, `PagerDutyAlerter`, `EmailAlerter`, `AlertManager` with cooldown dedup | `alerts.py` |
| sf-cec | `ComplianceEvidencePackage`, HMAC-signed PDF attestation, framework clause mapper | `core/compliance_mapping.py` |
| sf-gate | `spanforge compliance check` (exits 0/1 on framework gaps) | `_cli.py` |
| SDK infra | Circuit breaker, batch exporter, stream multi-exporter | `_batch_exporter.py`, `_stream.py` |

**What is entirely absent:**  
- `sf-identity` â€” no auth module exists anywhere  
- `sf-secrets` â€” no secrets scanning module exists  
- `sf-gate` â€” no 6-gate pipeline YAML engine  
- Named SDK methods for all services (`.append()`, `.publish()`, `.export_spans()`, etc.)

---

## 3. Milestone Overview & Timeline

| Milestone | Phases | Target | HallucCheck Stories Unblocked |
|-----------|--------|--------|-------------------------------|
| **M1 â€” Security Primitives** | 1, 2 | Week 6 | SF-007, SF-009 |
| **M2 â€” Data Trust Pipeline** | 3, 4 | Week 10 | SF-002, SF-003, SF-010, SF-012 |
| **M3 â€” Compliance Layer** | 5 | Week 14 | SF-008 |
| **M4 â€” Observability & Alerting** | 6, 7 | Week 17 | SF-004, SF-011 |
| **M5 â€” Gate Pipeline** | 8 | Week 21 | SF-005, SF-006 |
| **M6 â€” Integration & Config** | 9 | Week 23 | SF-001, SF-010 |
| **M7 â€” T.R.U.S.T. + HallucCheck Contract** | 10 | Week 26 | SF-012, all remaining |
| **M8 â€” Enterprise & Supply Chain** | 11 | Week 32 | SF-009 enterprise |
| **M9 â€” DX & Ecosystem** | 12 | Week 36 | â€” (developer velocity) |

---

## 4. Phase 1 â€” SDK Foundation & Identity (sf-identity)

### Context
`sf-identity` is the **only fully absent service** that blocks everything else â€” API keys must exist before any other service can authenticate.  This phase also establishes the SDK base class pattern all other services inherit.

### 4.1  SDK Base Infrastructure

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| ID-001 | `SFServiceClient` abstract base class | Shared: endpoint URL, API key header injection, retry-with-backoff (exponential, jitter, max 3), circuit breaker (threshold 5), timeout, auth-token refresh hook, local-fallback flag, structured logging.  All 8 service clients inherit this. | P0 |
| ID-002 | `SFClientConfig` dataclass | `endpoint`, `api_key` (never logged), `timeout_ms`, `max_retries`, `local_fallback_enabled`, `tls_verify`, `proxy`.  Loaded from `[spanforge]` block in `.halluccheck.toml` and from `SPANFORGE_*` env vars.  Env vars always win. | P0 |
| ID-003 | Auth token refresh pipeline | Before every request, SDK checks `X-SF-Token-Expires` response header.  If expiry < 60 s, calls `sf_identity.refresh_token()` inline.  Refresh failures trigger local fallback if enabled, else raise `SFAuthError`. | P0 |
| ID-004 | SDK package entry points | `from spanforge.sdk import sf_identity, sf_pii, sf_secrets, sf_audit, sf_observe, sf_gate, sf_cec, sf_alert` â€” all 8 service singletons importable from one namespace. | P0 |
| ID-005 | `SPANFORGE_*` environment variable contract | Document and enforce precedence: env var > `.halluccheck.toml` > default.  Sanitise env-var names at startup and emit warning for unknown `SPANFORGE_` prefixed vars. | P1 |

### 4.2  API Key Lifecycle

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| ID-010 | API key format enforcement | Format: `sf_live_<48-char-base62>` (live) and `sf_test_<48-char-base62>` (test).  Base62 alphabet `[0-9A-Za-z]`.  Validation regex enforced at parse time.  Reject keys that do not match â€” raise `SFKeyFormatError`. | P0 |
| ID-011 | `sf_identity.issue_magic_link(email)` | POST `/v1/auth/magic-link`.  Sends one-time link to email; link TTL 15 min; single-use token encoded as HMAC-SHA256 of `{email}:{nonce}:{expiry}`.  Returns `{link_id, expires_at}`.  Link delivery uses async email queue (not blocking). | P0 |
| ID-012 | `sf_identity.exchange_magic_link(token)` â†’ `APIKeyBundle` | POST `/v1/auth/magic-link/exchange`.  Validates token, issues `sf_live_*` API key and RS256 session JWT.  Returns `{api_key (write-once), jwt, expires_at, scopes}`. | P0 |
| ID-013 | `sf_identity.rotate_key(key_id)` â†’ `APIKeyBundle` | POST `/v1/auth/keys/{id}/rotate`.  Issues new key, marks old key `rotating` for 5-min overlap window, then revokes.  Returns new bundle.  Emits `auth_event` to `sf-audit`. | P0 |
| ID-014 | `sf_identity.revoke_key(key_id)` | DELETE `/v1/auth/keys/{id}`.  Immediate revocation.  All in-flight JWTs signed by this key become invalid at next JWT validation.  Emits `auth_event` to `sf-audit`. | P0 |
| ID-015 | Key scoping model | Fields: `pillar_whitelist` (list of SpanForge service names), `project_scope` (list of project IDs), `ip_allowlist` (CIDR list), `expires_at` (ISO-8601).  Enforced by `sf-identity` middleware before the request reaches service code. | P0 |
| ID-016 | `sf_identity.verify_token(jwt)` | Validates RS256 JWT signature against sf-identity JWKS endpoint (`/.well-known/jwks.json`).  JWKS keys cached locally with 1-hour TTL.  Returns `{subject, scopes, project_id, expires_at}` or raises `SFTokenInvalidError`. | P0 |
| ID-017 | JWT specification | Algorithm: RS256.  TTL: 7 days.  Claims: `iss` (spanforge), `sub` (key_id), `aud` (project_id), `iat`, `exp`, `scopes` (list), `jti` (UUID for revocation).  `jti` checked against revocation list on every validation. | P0 |
| ID-018 | JWKS endpoint & key rotation | `GET /.well-known/jwks.json` returns current RSA public keys.  New key pair generated every 90 days (rolling).  Previous key retained for 7-day JWT expiry overlap.  Keys identified by `kid` claim. | P1 |

### 4.3  Session Management

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| ID-020 | Session JWT issuance | `sf_identity.create_session(api_key)` â†’ RS256 JWT.  Sliding expiry: each API call within 24 h extends session by 24 h up to 7-day hard cap. | P0 |
| ID-021 | Token introspection endpoint | `POST /v1/auth/introspect` â€” RFC 7662 compliant.  Returns `{active, scope, exp, sub, client_id}`. | P1 |
| ID-022 | Concurrent session limiting | Per project, max 10 concurrent active sessions (configurable).  New session beyond limit invalidates oldest. | P2 |
| ID-023 | Session activity log | Every `verify_token` call logged to `sf-audit` schema `spanforge.auth.v1` with `{event: token_verified, sub, ip_hash, user_agent_hash, timestamp}`.  No raw IPs or user-agents stored. | P1 |

### 4.4  Multi-Factor Authentication

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| ID-030 | TOTP-based MFA | RFC 6238 TOTP.  `sf_identity.enroll_totp(key_id)` â†’ `{secret_base32, qr_uri}`.  `sf_identity.verify_totp(key_id, otp)`.  Backup codes: 8 Ã— 8-char alphanumeric, single-use, stored as bcrypt hashes. | P1 |
| ID-031 | MFA enforcement policy | Per-project `mfa_required: true/false`.  If enforced, any `exchange_magic_link` without MFA factor returns `{mfa_required: true, challenge_id}`. | P1 |
| ID-032 | WebAuthn / FIDO2 support | `sf_identity.register_webauthn(key_id, credential)` and `sf_identity.authenticate_webauthn(challenge, assertion)`.  Server-side resident key support.  Enterprise tier only. | P2 |

### 4.5  SSO â€” SAML 2.0 & SCIM

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| ID-040 | SAML 2.0 SP-initiated SSO | `sf_identity.saml_metadata()` â†’ SP metadata XML.  `sf_identity.saml_acs(saml_response)` â†’ session JWT.  Tested against Okta, Azure AD, Google Workspace. | P1 |
| ID-041 | SCIM 2.0 provisioning | `POST/GET/PATCH/DELETE /scim/v2/Users` and `/Groups`.  Auto-provision users from IdP.  Group â†’ SpanForge role mapping configurable in admin dashboard.  RFC 7644 compliant. | P1 |
| ID-042 | OIDC relying party | `sf_identity.oidc_authorize()` and `sf_identity.oidc_callback(code)`.  Supports PKCE (RFC 7636).  Tested against Auth0, AWS Cognito. | P2 |
| ID-043 | SSO session delegation | When a project uses SSO, `sf-identity` issues SpanForge-native session tokens mapped to the IdP session.  IdP session revocation propagates to SpanForge within 5 min via SCIM `PATCH active=false`. | P1 |

### 4.6  Rate Limiting & Quota Enforcement

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| ID-050 | Rate-limit middleware | Per-key sliding window counters.  Headers returned: `X-SF-RateLimit-Limit`, `X-SF-RateLimit-Remaining`, `X-SF-RateLimit-Reset`.  HallucCheck reflects these as `X-RateLimit-*` in its own response. | P0 |
| ID-051 | Tier quota table enforcement | Free CLI: local-only.  API $99/mo: 10 k scored records/day.  Team $499/mo: 100 k/day.  Enterprise: unlimited.  Quota exceeded returns HTTP 429 with `Retry-After`. | P0 |
| ID-052 | Quota telemetry | Every quota event emitted as `sf.quota.consumed` span to `sf-observe`.  Monthly quota summary queryable via `GET /v1/auth/quota`. | P1 |

### 4.7  Security Hardening â€” sf-identity

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| ID-060 | Constant-time comparisons | All token comparison uses `hmac.compare_digest()`.  No early-exit string equality. | P0 |
| ID-061 | Key material never logged | API key values, TOTP secrets, and private keys are wrapped in `SecretStr` (similar to `Redactable`).  `__repr__` returns `"<SecretStr:***>"`. | P0 |
| ID-062 | Brute-force protection | Magic link: 5 failed exchanges in 15 min â†’ 1-hour lockout per email.  TOTP: 5 wrong OTPs â†’ 30-min lockout.  All lockout events emitted to `sf-audit`. | P0 |
| ID-063 | IP allowlist enforcement | If `ip_allowlist` set on key, requests from non-listed CIDRs return 403 with `SFIPDeniedError`.  CIDR matching uses `ipaddress.ip_network` â€” no DNS lookups. | P1 |
| ID-064 | OWASP API Security Top 10 compliance sign-off | Checklist: Broken Object Level Auth, Broken Auth, Excessive Data Exposure, Lack of Resources/Rate Limiting, Function Level Auth, Mass Assignment, Security Misconfiguration, Injection, Improper Asset Management, Insufficient Logging.  All 10 items reviewed and signed off before M1 release. | P0 |

---

## 5. Phase 2 â€” Secrets Scanning (sf-secrets)

### Context
This service is **entirely absent** from the codebase.  Every LLM output passes through it before storage.  The spec classifies this as "New in v6.0 â€” no equivalent in v5.0".

### 5.1  Core Detection Engine

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| SEC-001 | `spanforge/secrets.py` module | New file.  `SecretsScanner` class with `scan(text: str, *, confidence_threshold: float = 0.85) -> SecretsScanResult`.  `SecretsScanResult`: `{detected: bool, hits: list[SecretHit], auto_blocked: bool}`.  `SecretHit`: `{secret_type, start, end, confidence, redacted_value}`. | P0 |
| SEC-002 | Pattern registry â€” 7 spec-defined types | Implement all 7 from the spec table: (1) Generic API Key â€” entropy â‰¥ 3.5 bits/char on 32+ char alphanumeric tokens.  (2) Bearer Token â€” `Bearer eyJ` prefix (JWT).  (3) AWS Access Key â€” `AKIA[0-9A-Z]{16}`.  (4) GCP Service Account â€” JSON with `"type":"service_account"`.  (5) PEM Private Key â€” `-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----`.  (6) DB connection string â€” `(postgres|mysql|mongodb|redis|mssql)://[^:]+:[^@]+@`.  (7) HallucCheck API key â€” `hc_(live|test)_[0-9A-Za-z]{48}`. | P0 |
| SEC-003 | Extended pattern registry â€” industry standard additions | (8) SpanForge API key â€” `sf_(live|test)_[0-9A-Za-z]{48}`.  (9) GitHub PAT â€” `gh[pousr]_[A-Za-z0-9]{36,255}` and `github_pat_`.  (10) npm token â€” `npm_[A-Za-z0-9]{36}`.  (11) Slack token â€” `xox[baprs]-[0-9A-Za-z-]{10,}`.  (12) Stripe key â€” `sk_(live|test)_[0-9a-zA-Z]{24,}`.  (13) Twilio â€” `SK[0-9a-fA-F]{32}`.  (14) SendGrid â€” `SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}`.  (15) Azure SAS / Connection String â€” `DefaultEndpointsProtocol=https`.  (16) SSH private key â€” `-----BEGIN OPENSSH PRIVATE KEY-----`.  (17) Google API key â€” `AIza[0-9A-Za-z-_]{35}`.  (18) Terraform Cloud â€” `[Tt]erraform [Cc]loud`.  (19) HashiCorp Vault token â€” `s\.[A-Za-z0-9]{24}`.  (20) JWT (generic) â€” three base64url segments separated by dots matching RFC 7519. | P0 |
| SEC-004 | Shannon entropy scorer | `entropy_score(s: str) -> float` â€” Shannon entropy in bits/char.  Tokens with entropy â‰¥ 3.5 and length â‰¥ 32 flagged as potential high-entropy secrets.  Combined with structural pattern match for confidence scoring. | P0 |
| SEC-005 | Confidence scoring model | Per-type confidence:  structural pattern match alone â†’ 0.75.  Pattern + entropy â‰¥ 3.5 â†’ 0.90.  Pattern + entropy + context keyword (e.g. `"password"`, `"token"`, `"secret"`, `"key"`, `"credential"`) in Â±50 chars â†’ 0.97.  Configurable `confidence_threshold` gate. | P1 |
| SEC-006 | False-positive suppression | Allowlist for known test/placeholder values: `AKIA_EXAMPLE`, `sk_test_000`, `hc_test_0000â€¦`.  Configurable via `[secrets] allowlist` in `.halluccheck.toml`. | P1 |
| SEC-007 | Redaction in scan result | `SecretHit.redacted_value` replaces the matched span with `[REDACTED:SECRET_TYPE]`.  Full `redacted_text` field on `SecretsScanResult` with all hits replaced. | P0 |

### 5.2  Auto-block Logic

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| SEC-010 | Auto-block policy table | Zero tolerance (always block regardless of confidence): Bearer Token, AWS Access Key, GCP Service Account, PEM Private Key, SSH Private Key, HallucCheck API key, SpanForge API key, GitHub PAT, Stripe live key.  Confidence-gated (block if â‰¥ 0.90): Generic API Key, DB connection string, high-entropy token.  Configurable override via `[secrets] auto_block = true/false` (enterprise only for override). | P0 |
| SEC-011 | Blocked response contract | When `auto_blocked=true`: score_record created with `verdict=BLOCKED`, `hri=null`.  API returns HTTP 200 with `{"blocked": true, "reason": "SECRET_DETECTED", "secret_types": [...]}`.  Raw `output_text` **never stored**.  Redacted version stored only if `[secrets] store_redacted = true`. | P0 |
| SEC-012 | HallucCheck API key self-alert | When `hc_(live|test)_*` key detected in an output, trigger `sf_alert.publish("halluccheck.secrets.detected", {..., "action": "key_rotation_recommended"})` in addition to blocking. | P0 |
| SEC-013 | CRITICAL span emission | Every auto-block emits `hc.secrets.detected` span to `sf-observe` with attributes: `secret_type`, `record_id`, `auto_blocked=true`, `confidence`, `output_text_hash` (SHA-256, never plaintext). | P0 |

### 5.3  SDK Surface

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| SEC-020 | `sf_secrets.scan(text)` â†’ `SecretsScanResult` | Primary method called in the HallucCheck scoring pipeline.  P95 latency target: < 200 ms (< 80 ms by Month 18 per spec metrics). | P0 |
| SEC-021 | `sf_secrets.scan_batch(texts)` â†’ `list[SecretsScanResult]` | For benchmark and bulk operations.  Parallel execution with `asyncio.gather`. | P1 |
| SEC-022 | `POST /v1/scan/secrets` HTTP endpoint | New endpoint per spec Â§6.  Returns `{detected, secret_types[], confidence_scores[]}`.  Available from API tier. | P0 |
| SEC-023 | `GET /v1/spanforge/status` â€” sf-secrets status | Contribute `sf_secrets` field to the health check endpoint.  Returns `{status: up|degraded|down, pattern_count, last_scan_at}`. | P1 |

### 5.4  Local Fallback

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| SEC-030 | Regex-only fallback mode | When `sf-secrets` endpoint unreachable and `local_fallback.enabled=true`, run regex patterns locally without entropy scoring (reduced accuracy).  Log `WARNING: sf-secrets unreachable, using regex fallback`. | P0 |
| SEC-031 | Fallback telemetry | Fallback activations counted in `SPANFORGE_SECRETS_FALLBACK_COUNT` Prometheus counter.  Exposed at `GET /v1/spanforge/status`. | P2 |

### 5.5  Git Pre-commit Integration (Industry Standard)

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| SEC-040 | `spanforge secrets scan <file>` CLI command | Scans a file or stdin for secrets.  Exit 0 = clean.  Exit 1 = secrets found.  `--format json` for CI.  `--redact` prints redacted version to stdout. | P1 |
| SEC-041 | `.pre-commit-hooks.yaml` entry | Add `spanforge-secrets-scan` hook to the repo's pre-commit config.  Stage: `pre-commit`.  Types: `[text]`.  Entry: `spanforge secrets scan`. | P1 |
| SEC-042 | SARIF output format | `spanforge secrets scan --format sarif` â€” GitHub Code Scanning / VS Code compatible output. | P2 |
| SEC-043 | Vault integration hints | When a secret is detected, optionally suggest the appropriate vault path pattern for the identified secret type (HashiCorp Vault, Azure Key Vault, AWS Secrets Manager).  No automatic rotation â€” suggestion only. | P2 |

---

## 6. Phase 3 â€” PII Service Hardening (sf-pii)

### Context
The detection engine (`presidio_backend.py`, `redact.py`) is solid.  This phase wraps it in a named SDK service, adds the missing `anonymise()` method, wires the pipeline action routing, and adds multi-regulation compliance coverage.

### 6.1  SDK Surface

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| PII-001 | `sf_pii.scan(text, *, language="en") -> PIIScanResult` | Thin wrapper over `presidio_scan_payload()` with fallback to `redact.scan_payload()`.  Response shape per spec: `{entities: [{type, start, end, score}], redacted_text, detected: bool}`.  P95 target: < 400 ms (< 200 ms by Month 18). | P0 |
| PII-002 | `sf_pii.anonymise(payload: dict) -> AnonymisedResult` | New method.  Calls `presidio_scan_payload()` on all string fields recursively, replaces hits with `<TYPE>` placeholders.  Returns `{clean_payload, redaction_manifest: [{field_path, type, original_hash, replacement}]}`.  This replaces the custom Presidio pipeline in HallucCheck v5.0 Â§14 (leaderboard anonymisation). | P0 |
| PII-003 | `sf_pii.scan_batch(texts) -> list[PIIScanResult]` | Async parallel execution.  Used by `hc trust-gate` to bulk-check recent outputs. | P1 |
| PII-004 | `POST /v1/scan/pii` HTTP endpoint | Per spec Â§6.  Standalone PII scan on arbitrary text.  Returns `{entities[], redacted_text}`.  API tier+. | P0 |
| PII-005 | `GET /v1/spanforge/status` â€” sf-pii status | Contribute `sf_pii` field: `{status, presidio_available, entity_types_loaded, last_scan_at}`. | P1 |

### 6.2  Pipeline Action Routing

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| PII-010 | `pii_action` pipeline hook | After `sf_pii.scan()` returns, HallucCheck scoring pipeline enforces `[pii] action`:  `"flag"` â€” score normally, add `pii.detected=true` to response.  `"redact"` â€” substitute `redacted_text` as the scoring input.  `"block"` â€” return HTTP 422 `PII_DETECTED` without scoring.  Default: `"flag"`. | P0 |
| PII-011 | Confidence threshold gate | Only entities with `score >= [pii] threshold` (default 0.85) trigger the action.  Sub-threshold hits recorded in response under `pii.low_confidence_hits` for audit only. | P0 |
| PII-012 | `pii.detected` field in HRI JSON | Add `"pii": {"detected": bool, "entity_types": [], "action": null|"flag"|"redact"|"block"}` to the HRI score JSON schema. | P0 |

### 6.3  DPDP, GDPR, HIPAA, CCPA, PIPL Coverage

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| PII-020 | DPDP scope enforcement | `dpdp_scope` in `[pii]` config declares permitted processing purposes.  `sf_pii.scan()` checks consent record from `sf-audit` (schema `spanforge.consent.v1`).  If output contains DPDP entity AND no valid consent for current purpose â†’ return `DPDP_CONSENT_MISSING` error regardless of `pii_action`. | P1 |
| PII-021 | GDPR Article 17 â€” Right to Erasure | `sf_pii.erase_subject(subject_id, project_id)` â€” finds all `pii_detection` audit records for `subject_id`, issues erasure instructions to downstream stores.  Returns erasure receipt with timestamp for GDPR Article 17(3) exceptions log. | P1 |
| PII-022 | CCPA data subject request (DSAR) export | `sf_pii.export_subject_data(subject_id, project_id)` â€” aggregates all events referencing `subject_id` from `sf-audit`.  Returns JSON export package.  Used by `GET /v1/privacy/dsar/{subject_id}`. | P1 |
| PII-023 | HIPAA Safe Harbor De-identification | 18 PHI identifier types per 45 CFR Â§164.514(b)(2).  `sf_pii.safe_harbor_deidentify(text)` returns text with all 18 identifiers removed or generalised (dates â†’ year, ages > 89 â†’ "90+", zip â†’ first 3 digits). | P2 |
| PII-024 | China PIPL â€” sensitive personal information | Add patterns for: Chinese national ID (`\d{17}[\dX]`), Chinese mobile (`1[3-9]\d{9}`), Chinese bank card.  Flag as `pipl_sensitive` for cross-border transfer controls. | P2 |
| PII-025 | EU AI Act Article 10 â€” training data PII | `sf_pii.audit_training_data(dataset_path)` â€” batch scan a dataset file, produce a PII prevalence report.  Used by compliance evidence chain. | P2 |

### 6.4  Industry-Standard Additions

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| PII-030 | Differential privacy noise injection option | When `[pii] dp_epsilon` is set, apply Laplace mechanism noise to numeric quasi-identifiers before scoring.  For research/analytics use cases.  IEEE/NIST SP 800-188 guidance. | P3 |
| PII-031 | Synthetic data generation hint | When `pii_action = "redact"` and `[pii] suggest_synthetic = true`, return a Faker-compatible template alongside the redacted text so callers can generate plausible synthetic replacements. | P3 |
| PII-032 | PII heat map for dashboards | Aggregate PII detection stats per entity type per project per day.  Exposed via `GET /v1/pii/stats` (Team+).  Powers SpanForge dashboard PII trend chart. | P2 |

---

## 7. Phase 4 â€” Audit Service High-Level API (sf-audit)

### Context
The cryptographic primitives (`AuditStream`, `sign()`, `verify_chain()`, WORM exporters) are production-ready.  This phase wraps them in a high-level named SDK so `sf_audit.append(record, schema_key)` is the single call site, and adds the schema key namespace, query API, BYOS routing, and T.R.U.S.T. store write path.

### 7.1  High-Level SDK API

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| AUD-001 | `sf_audit.append(record: dict, schema_key: str)` | Validates record has required fields for `schema_key`, calls `AuditStream.append()` with HMAC chain, routes to configured backend (cloud, BYOS, or local JSONL fallback).  Returns `{record_id, chain_position, timestamp, hmac}`.  Thread-safe. | P0 |
| AUD-002 | Schema key registry | Enforce known schema keys: `halluccheck.score.v1`, `halluccheck.bias.v1`, `halluccheck.prri.v1`, `halluccheck.drift.v1`, `halluccheck.opa.v1`, `halluccheck.pii.v1`, `halluccheck.secrets.v1`, `halluccheck.gate.v1`, `halluccheck.auth.v1`, `halluccheck.benchmark_run.v1`, `halluccheck.benchmark_version.v1`, `spanforge.auth.v1`, `spanforge.consent.v1`.  Unknown schema keys rejected with `SFAuditSchemaError` unless `strict_schema=False`. | P0 |
| AUD-003 | `sf_audit.sign(record: dict) -> SignedRecord` | Wraps `sign()` from `signing.py`.  Delegates HMAC computation â€” HallucCheck never calls `sign()` directly. | P0 |
| AUD-004 | `sf_audit.verify_chain(records) -> ChainVerificationResult` | Wraps `verify_chain()`.  Called by `hc verify-chain` CLI. | P0 |
| AUD-005 | `sf_audit.export(schema_key, date_range, project_id) -> list[dict]` | Query audit store for records matching schema key and date range.  Used by `sf-cec.build_bundle()` to pull records without HallucCheck needing direct DB access. | P0 |
| AUD-006 | `GET /v1/audit/{record_type}` HTTP endpoint | Per spec Â§6.  Proxies to `sf_audit.export()` with HallucCheck schema key filter.  Team+ tier.  Returns paginated JSON. | P0 |

### 7.2  Retention & BYOS

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| AUD-010 | 7-year retention policy configuration | `[audit] retention_years = 7` in config.  WORM backend enforces object-lock rules: S3 â†’ `ObjectLockConfiguration` with `COMPLIANCE` mode, 7-year retention.  Azure â†’ Immutable Blob Storage policy.  GCS â†’ Retention policy object.  Cloudflare R2 â†’ Object Lock (COMPLIANCE). | P0 |
| AUD-011 | BYOS routing | `[audit.byos] provider = "s3|azure|gcs|r2"`.  Config: bucket/container name, region, credentials injected from `sf-identity`.  `AppendOnlyJSONLExporter.WORMBackend` implementations for each provider.  Seal-and-upload on rotation trigger. | P1 |
| AUD-012 | Multi-region replication | Enterprise: after WORM upload to primary region, replicate sealed file to secondary region within 15 min.  Replication lag tracked as `sf.audit.replication_lag_seconds` metric. | P2 |
| AUD-013 | RFC 3161 trusted timestamp | On every WORM-sealed file, obtain a trusted timestamp from a public TSA (e.g. DigiCert, Sectigo).  Embed TSR (timestamp response) as `.tsr` sidecar.  Provides cryptographic proof-of-existence for legal proceedings. | P2 |

### 7.3  Query & Export

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| AUD-020 | Date-range query index | Local index (SQLite or LMDB) mapping `(schema_key, project_id, timestamp)` â†’ `(file_path, byte_offset)`.  Enables O(log n) range queries without full file scan. | P1 |
| AUD-021 | SIEM export connectors | Push audit records to: Splunk HEC, IBM QRadar CEF, Microsoft Sentinel (Azure Monitor), Elastic ECS.  Configurable via `[audit.siem]` block.  Batch push every 60 s, with retry on failure. | P2 |
| AUD-022 | Audit record search API | `GET /v1/audit/search?q=<lucene-style-query>&schema_key=...&from=...&to=...` â€” full-text search over audit records.  Enterprise.  Powered by local Whoosh index or delegated to Elastic. | P2 |

### 7.4  T.R.U.S.T. Store Write Path

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| AUD-030 | T.R.U.S.T. store integration | After `sf_audit.append(record, "halluccheck.score.v1")`, additionally write a T.R.U.S.T. summary record with: `trust_dimension="hallucination"`, `signal_source="halluccheck"`, `project_id`, `record_type`, `record_id`, `verdict`, `score`, `domain`, `hmac`, `timestamp`.  This feeds the T.R.U.S.T. scorecard aggregation. | P0 |
| AUD-031 | T.R.U.S.T. scorecard query API | `GET /v1/trust/scorecard?project_id=...&from=...&to=...` â€” returns aggregated T.R.U.S.T. dimensions: `{hallucination, pii_hygiene, secrets_hygiene, gate_pass_rate, compliance_posture}`.  Each dimension: `{score: 0-100, trend: up|flat|down, last_updated}`. | P1 |

### 7.5  Compliance & Standards

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| AUD-040 | SOC 2 Type II readiness | Audit log meets CC7.2 (monitoring), CC9.2 (risk assessment).  Evidence: immutability proof via WORM, chain integrity via `verify_chain`, access log via `spanforge.auth.v1` schema. | P1 |
| AUD-041 | ISO 27001 Annex A.12.4 | Event logging controls: A.12.4.1 (event logging), A.12.4.2 (protection of log information), A.12.4.3 (administrator and operator logs), A.12.4.4 (clock synchronisation).  Clock sync: all audit records use UTC; NTP drift > 1 s triggers warning. | P1 |
| AUD-042 | GDPR Article 30 records | `sf_audit.generate_article30_record(project_id)` â€” produces the Record of Processing Activities document from audit metadata.  JSON and PDF export. | P2 |

---

## 8. Phase 5 â€” Compliance Evidence Chain (sf-cec)

### Context
`ComplianceEvidencePackage` in `core/compliance_mapping.py` is a solid analysis and PDF-generation engine.  This phase wraps it in a proper packaging service â€” signed ZIP assembly, multi-product record aggregation, regulatory clause mapping for EU AI Act and ISO/IEC 42001, and a download URL contract for `POST /v1/risk/cec`.

### 8.1  Bundle Assembly

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| CEC-001 | `sf_cec.build_bundle(project_id, date_range, frameworks=[]) -> BundleResult` | Orchestrator method.  Steps: (1) call `sf_audit.export()` for each schema key in the CEC contribution table.  (2) Call `ComplianceEvidencePackage` analysis.  (3) Assemble ZIP per structure below.  (4) HMAC-SHA256 sign the ZIP manifest.  (5) Upload to BYOS or ephemeral signed URL.  Returns `{bundle_id, download_url, expires_at, hmac_manifest, record_counts}`. | P0 |
| CEC-002 | ZIP bundle structure | `halluccheck_cec_{project}_{date}.zip` containing: `manifest.json` (record inventory + HMAC), `score_records/` (NDJSON), `bias_reports/` (NDJSON), `prri_records/` (NDJSON), `drift_events/` (NDJSON), `pii_detections/` (NDJSON), `gate_evaluations/` (NDJSON), `clause_map.json` (regulatory clause mapping), `attestation.pdf` (HMAC-signed PDF from `ComplianceEvidencePackage`), `chain_proof.json` (`verify_chain()` result), `rfc3161_timestamp.tsr` (trusted timestamp). | P0 |
| CEC-003 | `POST /v1/risk/cec` endpoint | Per spec Â§6.  Calls `sf_cec.build_bundle()`.  Returns `{download_url, expires_at, bundle_id}`.  Enterprise tier. | P0 |
| CEC-004 | Bundle expiry & re-generation | Signed download URLs expire in 24 h.  `GET /v1/risk/cec/{bundle_id}` re-issues a fresh URL without rebuilding.  Bundles retained in BYOS for retention period. | P1 |
| CEC-005 | Bundle integrity verification | `sf_cec.verify_bundle(zip_path) -> BundleVerificationResult` â€” re-computes manifest HMAC, verifies chain_proof, validates RFC 3161 timestamp.  CLI: `spanforge cec verify <path>`. | P1 |

### 8.2  Regulatory Framework Mappings

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| CEC-010 | EU AI Act clause mapping | Map SpanForge evidence records to specific EU AI Act articles: Art. 9 (Risk Management), Art. 10 (Data Governance), Art. 12 (Record-keeping), Art. 13 (Transparency), Art. 14 (Human Oversight), Art. 15 (Accuracy, Robustness, Cybersecurity).  `clause_map.json` output lists each article, status (SATISFIED/PARTIAL/GAP), and evidence records supporting it. | P0 |
| CEC-011 | ISO/IEC 42001 (AI Management System) | Map evidence to: Clause 6.1 (Risk assessment), Clause 8.3 (AI system impact assessment), Clause 9.1 (Monitoring and measurement), Clause 10 (Improvement).  Add `iso42001` as a valid `frameworks` value. | P1 |
| CEC-012 | NIST AI RMF alignment | Map to: GOVERN (policies, accountability), MAP (context, risk identification), MEASURE (evaluation, monitoring), MANAGE (response, recovery).  `nist_ai_rmf` as framework value. | P1 |
| CEC-013 | ISO/IEC 27001 Annex A sub-controls | Map audit log evidence to A.12.4.x sub-controls.  `iso27001` as framework value. | P1 |
| CEC-014 | SOC 2 Type II controls | Map to CC6, CC7, CC9.  `soc2` as framework value.  Output includes control satisfaction summary suitable for auditor attachment. | P2 |
| CEC-015 | DPA / SCC generation | `sf_cec.generate_dpa(project_id, controller_details, processor_details) -> DPADocument` â€” generates a GDPR Article 28 Data Processing Agreement using the evidence records.  EU Standard Contractual Clauses (SCCs) template for data transfers.  PDF export. | P2 |

### 8.3  eIDAS & Qualified Signatures (Industry Standard)

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| CEC-020 | RFC 3161 timestamp on every bundle | Integrate with public TSA (DigiCert RFC 3161 or Sectigo).  `obtain_timestamp(data_bytes) -> TimestampResponse`.  Embed `.tsr` in ZIP.  Verification: `verify_timestamp(tsr_bytes, data_bytes) -> bool`. | P2 |
| CEC-021 | Qualified Electronic Signature (QES) option | Enterprise: optionally sign the attestation PDF with a QES-compatible provider (e.g. DocuSign, Adobe Sign API, or eIDAS-compliant HSM).  Signature embedded in PDF as CAdES/PAdES. | P3 |
| CEC-022 | Notarization receipt | Integrate with Ethereum-based notarization (OpenTimestamps) as an optional supplement.  Hash of ZIP manifest committed to Bitcoin/Ethereum chain.  Proof file included in bundle. | P3 |

---

## 9. Phase 6 â€” Observability Named SDK (sf-observe)

### Context
The exporter infrastructure is mature.  This phase surfaces named SDK methods (`export_spans()`, `add_annotation()`) that HallucCheck can call without depending on internal SpanForge exporter details, and adds OTel Semantic Convention compliance, SLO tracking, and continuous profiling.

### 9.1  Named SDK Methods

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| OBS-001 | `sf_observe.export_spans(spans, *, receiver_config=None) -> ExportResult` | The spec requires `hc monitor export --format otel` to call this instead of raw OTel SDK code.  Method accepts a list of `Span` objects or OTLP-compatible dicts, routes to the configured exporters (OTLP, Datadog, Grafana, Elastic, Splunk).  `receiver_config` can override endpoint/auth for the call.  Returns `{exported_count, failed_count, backend}`. | P0 |
| OBS-002 | `sf_observe.add_annotation(event_type, payload, *, project_id) -> AnnotationId` | Adds a named annotation to the shared event store.  Used by `POST /v1/monitor/provider-event`.  Provider release calendar synced from this store.  Annotations queryable by `event_type` and time range. | P0 |
| OBS-003 | `sf_observe.get_annotations(event_type, from_dt, to_dt) -> list[Annotation]` | Query shared annotation store.  Used by `hc monitor` to overlay provider events on drift charts. | P1 |
| OBS-004 | `sf_observe.emit_span(name, attributes) -> SpanId` | Convenience method for emitting a single named span without needing to manage the tracer context.  Used by HallucCheck for `hc.score.started`, `hc.score.completed`, `hc.pii.detected`, `hc.secrets.detected`, etc. | P0 |

### 9.2  OTel Semantic Convention Compliance

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| OBS-010 | Span attribute naming â€” OTel GenAI conventions | Apply OpenTelemetry Semantic Conventions for Generative AI (v1.27+): `gen_ai.system`, `gen_ai.request.model`, `gen_ai.request.max_tokens`, `gen_ai.response.finish_reasons`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`.  Audit existing span attributes and migrate any non-conforming names. | P0 |
| OBS-011 | W3C TraceContext propagation | All spans set `traceparent` and `tracestate` headers on outbound calls.  Incoming `traceparent` from HallucCheck must be propagated onto all sf-observe spans, creating a unified trace across both systems. | P0 |
| OBS-012 | W3C Baggage propagation | `project_id`, `domain`, `tier` propagated as W3C Baggage entries.  Available to all downstream span processors without explicit parameter threading. | P1 |
| OBS-013 | Exemplars | OTLP metrics export includes exemplars linking metric data points to trace IDs.  Enables jump-from-metric-to-trace in Grafana/Tempo. | P1 |
| OBS-014 | OTel resource attributes | `service.name=spanforge`, `service.version=<semver>`, `deployment.environment`, `telemetry.sdk.language=python`, `telemetry.sdk.name=opentelemetry`, `telemetry.sdk.version`. | P0 |
| OBS-015 | Span status & error codes | All error spans set `otel.status_code=ERROR` and `exception.*` attributes per OTel exception semantic conventions.  No swallowed exceptions. | P0 |

### 9.3  Metrics & SLO Tracking

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| OBS-020 | SLO definitions per service | Define SLOs: sf-pii p95 < 400 ms, sf-secrets p95 < 200 ms, sf-audit append < 50 ms, sf-gate evaluate < 2 s, sf-cec build_bundle < 30 s.  SLO budget burn rate tracked as `sf.<service>.slo_burn_rate` gauge. | P1 |
| OBS-021 | Error budget alerting | When SLO burn rate > 2Ã— for 1 h â†’ WARNING alert via `sf-alert`.  When burn rate > 5Ã— for 15 min â†’ CRITICAL alert. | P1 |
| OBS-022 | Prometheus metrics exposition | `GET /metrics` endpoint exposing all SpanForge service metrics in Prometheus text format.  Metrics: `sf_pii_scan_duration_seconds`, `sf_secrets_scan_duration_seconds`, `sf_audit_append_duration_seconds`, `sf_gate_evaluate_duration_seconds`, `sf_identity_token_verify_duration_seconds`, `sf_pii_detected_total`, `sf_secrets_blocked_total`, `sf_audit_chain_verified_total`. | P1 |
| OBS-023 | Grafana dashboard provisioning | Ship a `grafana/dashboards/spanforge-overview.json` dashboard JSON.  Panels: PII detection rate, secrets block rate, audit chain health, SLO burn rates, gate pass/fail rate, token verify latency, alert volume by topic. | P2 |

### 9.4  Continuous Profiling & Tracing

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| OBS-030 | Continuous profiling â€” Pyroscope integration | Optional `[observe] profiling = true`.  Sends CPU/memory profiles to Pyroscope-compatible endpoint.  Profiling labels: `service`, `version`, `project_id`.  Zero overhead when disabled. | P2 |
| OBS-031 | Trace sampling strategies | Implement `ParentBasedSampler`, `TraceIdRatioBased`, `AlwaysOn`, `AlwaysOff`.  Default: `ParentBasedSampler(TraceIdRatioBased(0.1))`.  Override per-project via `[observe] sample_rate`. | P1 |
| OBS-032 | Span processor pipeline | Head-based sampling â†’ `BatchSpanProcessor` â†’ multi-exporter fan-out.  `SimpleSpanProcessor` available for development/debug mode. | P1 |

### 9.5  Backend Exporter Hardening

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| OBS-040 | Splunk HEC exporter | New `export/splunk.py`.  OTLP â†’ Splunk HEC JSON translation.  Batched POST to `https://<host>:8088/services/collector`.  Auth via `Splunk <token>` header.  Index and sourcetype configurable. | P2 |
| OBS-041 | Elastic/OpenSearch exporter | New `export/elastic.py`.  ECS-compatible event format.  Index pattern: `spanforge-{service}-{YYYY.MM.dd}`.  Auth: API key or basic. | P2 |
| OBS-042 | Azure Monitor / Sentinel exporter | New `export/azure_monitor.py`.  Uses Azure Monitor Data Collection Endpoint (DCE) REST API.  Auth via Managed Identity or client credentials. | P2 |
| OBS-043 | Exporter health probes | Every exporter exposes `healthy() -> bool` and `last_export_at` property.  Surfaced in `GET /v1/spanforge/status`. | P1 |

---

## 10. Phase 7 â€” Alert Routing Service (sf-alert)

### Context
`AlertManager` with Slack/Teams/PagerDuty/Email and cooldown-based dedup exists.  This phase lifts it to a topic-based publish model, adds escalation policy, webhook HMAC signing, SMS, and OpsGenie / Incident.io integration.

### 10.1  Topic-Based Publish API

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| ALT-001 | `sf_alert.publish(topic: str, payload: dict, *, severity: str) -> PublishResult` | Primary method HallucCheck calls.  Routes based on topic to configured sinks.  Topics: `halluccheck.drift.amber`, `halluccheck.drift.red`, `halluccheck.bias.critical`, `halluccheck.prri.red`, `halluccheck.benchmark.regression`, `halluccheck.pii.detected`, `halluccheck.secrets.detected`, `halluccheck.trust_gate.failed`.  Returns `{alert_id, routed_to: [str], suppressed: bool}`. | P0 |
| ALT-002 | Topic routing configuration | `[alert.routing]` in `.halluccheck.toml` or SpanForge dashboard.  Per-topic sink list: `halluccheck.drift.red â†’ [pagerduty, slack:#incidents]`.  Routing config owned by SpanForge â€” HallucCheck only calls `publish()`. | P0 |
| ALT-003 | Topic registry & validation | Known topics enforced at `publish()` call.  Unknown topics: WARNING log and route to a default catch-all sink if configured.  `sf_alert.register_topic(topic, description, default_severity)` for custom topics. | P1 |

### 10.2  Deduplication & Suppression

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| ALT-010 | 5-minute dedup window | Same `(topic, project_id)` combination within 5 min â†’ suppressed.  `suppressed=true` in `PublishResult`.  Dedup window configurable per topic. | P0 |
| ALT-011 | Alert grouping | Multiple related alerts within 2 min grouped into a single notification with a summary.  Group key: `(topic_prefix, project_id)` where prefix = everything before the last `.`. | P1 |
| ALT-012 | Maintenance window suppression | `sf_alert.set_maintenance_window(project_id, start, end)` â€” all alerts for project suppressed during window.  Maintenance windows stored in `sf-audit` for auditability. | P2 |

### 10.3  Escalation Policy

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| ALT-020 | CRITICAL auto-escalation | CRITICAL severity alerts not acknowledged within 15 min auto-escalate to PagerDuty (or next sink in escalation chain).  Acknowledgement via `sf_alert.acknowledge(alert_id)` or PagerDuty webhook callback. | P0 |
| ALT-021 | Escalation chain configuration | `[alert.escalation]` config: `level_1_wait_minutes = 15`, `level_2_sink = "pagerduty"`, `level_3_sink = "sms"`, `max_levels = 3`.  Escalation chain events logged to `sf-audit`. | P1 |
| ALT-022 | On-call rotation awareness | `[alert.oncall] provider = "pagerduty|opsgenie"`, `schedule_id`.  `sf-alert` queries on-call schedule at escalation time to direct alert to the current on-call engineer, not a static channel. | P2 |

### 10.4  New Sink Integrations

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| ALT-030 | OpsGenie alerter | `OpsGenieAlerter`.  Uses OpsGenie Alert API v2.  Fields: `message`, `description`, `priority` (P1â€“P5 mapped from severity), `tags`, `details` (payload fields). | P1 |
| ALT-031 | VictorOps / Splunk On-Call | `VictorOpsAlerter`.  POST to VictorOps REST endpoint with `message_type` (CRITICAL/WARNING/INFO). | P2 |
| ALT-032 | Incident.io integration | `IncidentIOAlerter`.  Creates or updates Incident.io incidents via REST API.  Maps CRITICAL â†’ `severity: critical`, HIGH â†’ `severity: major`. | P2 |
| ALT-033 | SMS alerter | `SMSAlerter` via Twilio API.  Character-limited to 160 chars.  Topic + severity + project ID + short reason.  Enterprise tier only. | P2 |
| ALT-034 | Webhook with HMAC signing | Per spec, webhooks must carry HMAC signature.  `WebhookAlerter` adds `X-SF-Signature: sha256=<hmac>` header.  Secret configurable per sink.  Receiver can verify with `hmac.compare_digest`. | P0 |
| ALT-035 | Microsoft Teams adaptive card | Upgrade `TeamsAlerter` from simple text to Adaptive Card format.  Include severity colour band, fact table with payload fields, action buttons (Acknowledge / Silence). | P2 |

### 10.5  Runbook Automation (Industry Standard)

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| ALT-040 | Runbook URL attachment | Each registered topic can carry a `runbook_url`.  `sf_alert.publish()` includes the URL in every notification for that topic.  `[alert.runbooks]` config block. | P1 |
| ALT-041 | Auto-remediation webhook trigger | When `[alert.auto_remediate] enabled = true`, CRITICAL alerts additionally POST to a configurable `remediation_webhook_url`.  Payload includes `{alert_id, topic, project_id, suggested_action}`.  Integration point for PagerDuty Event Orchestration, Rundeck, or Ansible AWX. | P2 |
| ALT-042 | Alert history query API | `GET /v1/alerts?project_id=...&topic=...&from=...&to=...&status=open|acknowledged|resolved` â€” query alert history.  Team+.  Returns paginated list with dedup and escalation timeline. | P1 |

### 10.6  Reliability & Security

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| ALT-050 | Async publish pipeline | `publish()` enqueues to an in-process async queue.  Background coroutine dispatches to sinks.  Max queue depth: 1 000.  Overflow: drop oldest + log `WARNING: alert queue overflow`. | P0 |
| ALT-051 | Per-sink circuit breaker | Each sink has independent circuit breaker (inherits `SFServiceClient` from Phase 1).  Failed sink does not block other sinks. | P0 |
| ALT-052 | Rate limiting on publish | Per-project `max_alerts_per_minute` (default: 60).  Excess alerts bucketed and summarised: "X alerts suppressed in last 60 s". | P1 |
| ALT-053 | Alert audit log | Every `publish()` call appended to `sf-audit` schema `spanforge.alert.v1`: `{alert_id, topic, severity, project_id, sinks_notified, suppressed, timestamp}`. | P1 |

---

## 11. Phase 8 â€” CI/CD Gate Pipeline (sf-gate)

### Context
Only a `spanforge compliance check` exit-code command exists.  This phase implements the full 6-gate YAML pipeline engine, Gate 5 (Governance/PRRI), Gate 6 (Trust: HRI + PII + Secrets), SLSA provenance, and the `hc trust-gate` command.

### 11.1  Gate YAML Engine

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| GAT-001 | Gate YAML schema v1 | Fields per gate: `id` (string), `name` (string), `type` (string â€” maps to gate executor), `command` (shell template), `pass_condition` (dict of metric: threshold), `on_fail` (block|warn|report), `artifact` (output file name), `framework` (eu-ai-act|nist-ai-rmf|iso42001|...), `timeout_seconds` (default: 120), `skip_on` (list of branch patterns). | P0 |
| GAT-002 | Gate runner engine | `spanforge/gate.py` â€” `GateRunner.run(gate_config_path, context) -> GateRunResult`.  Parses YAML, executes each gate sequentially (or parallel if `parallel: true`).  Collects artifacts.  Final exit code: 0 if all pass, 1 if any block gate fails.  Warn gates never fail the pipeline. | P0 |
| GAT-003 | Gate artifact store | Each gate writes a JSON artifact to `.sf-gate/artifacts/<gate_id>_result.json`.  Artifact schema: `{gate_id, name, verdict: PASS|FAIL|WARN, metrics: {}, timestamp, duration_ms, artifact_path}`.  Artifacts retained for 90 days. | P0 |
| GAT-004 | `sf_gate.evaluate(gate_id, payload) -> GateEvaluationResult` | SDK method called by HallucCheck.  Returns `{gate_id, verdict, metrics, artifact_url}`.  Writes result to artifact store.  Emits `hc.gate.evaluated` span to `sf-observe`.  Appends to `sf-audit` schema `halluccheck.gate.v1`. | P0 |
| GAT-005 | Template variable substitution | Gate `command` supports `{{ project }}`, `{{ branch }}`, `{{ commit_sha }}`, `{{ pipeline_id }}`, `{{ timestamp }}`.  Injected at runtime by `GateRunner`. | P0 |
| GAT-006 | Gate skip conditions | `skip_on: ["refs/heads/main"]` â€” skip gate for specified branch patterns.  `skip_on_draft: true` â€” skip for draft PRs.  Skipped gates recorded as `SKIPPED` in artifact. | P1 |

### 11.2  Gate 5 â€” Governance (PRRI)

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| GAT-010 | `halluccheck_prri` gate type | Executor: runs `hc risk --gate --project {{ project }}`, reads `prri_result.json`, checks `prri_score < prri_red_threshold` (default: 70).  On fail: block pipeline. | P0 |
| GAT-011 | `prri_result.json` artifact schema | `{gate_id: "gate5_governance", prri_score, verdict: GREEN|AMBER|RED, dimension_breakdown: {}, framework, policy_file, timestamp, allow: bool}`. | P0 |
| GAT-012 | Gate 5 YAML reference config | Ship `examples/gates/gate5_governance.yaml` as a reference.  `type: halluccheck_prri`, `pass_condition: {prri_score: "< 70"}`, `on_fail: block`, `framework: eu-ai-act`. | P0 |

### 11.3  Gate 6 â€” Trust Gate (HRI + PII + Secrets)

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| GAT-020 | `halluccheck_trust` gate type | New gate type.  Runs `hc trust-gate --project {{ project }}`.  Pass conditions: `hri_critical_rate < 0.05`, `pii_detected == false`, `secrets_detected == false`.  All three must pass.  `on_fail: block`. | P0 |
| GAT-021 | `hc trust-gate` command | New CLI command (SF-006).  Steps: (1) Query `sf-audit` for last 100 `halluccheck.score.v1` records â†’ compute `critical_rate`.  (2) Query `sf-audit` for `halluccheck.pii.v1` records in last 24 h â†’ `pii_detected = count > 0`.  (3) Query `sf-audit` for `halluccheck.secrets.v1` records in last 24 h â†’ `secrets_detected = count > 0`.  Exit 0 = all clear.  Exit 1 = FAIL with JSON reason. | P0 |
| GAT-022 | `trust_gate_result.json` artifact | `{gate_id: "gate6_trust", verdict: PASS|FAIL, hri_critical_rate, hri_critical_threshold: 0.05, pii_detected, pii_detections_24h, secrets_detected, secrets_detections_24h, failures: [], timestamp, pipeline_id, project_id}`. | P0 |
| GAT-023 | `hc trust-gate --report` | Full trust gate report: HRI trend last 30 days, PII detection history by entity type, secrets scan history by secret type, PRRI summary.  PDF + JSON output.  Calls `sf_cec` for PDF generation. | P1 |
| GAT-024 | `POST /v1/trust-gate` endpoint | Per spec Â§6.  Composite Trust Gate.  Returns `{pass, hri_critical_rate, pii_detected, secrets_detected, reasons[]}`.  Team+. | P0 |
| GAT-025 | Trust gate alert | When Gate 6 fails, publish `halluccheck.trust_gate.failed` to `sf-alert` with `{project_id, gate_id: "gate6_trust", failure_reason, pipeline_id}`, severity: CRITICAL. | P0 |

### 11.4  All 6 Gates â€” Reference Pipeline

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| GAT-030 | Gate 1 â€” Schema Validation | `type: schema_validation`.  Validates all output schemas against registered SpanForge schema versions.  Blocks on any breaking change without a migration path. | P1 |
| GAT-031 | Gate 2 â€” Dependency Security | `type: dependency_security`.  Runs `pip-audit` (Python) or `npm audit` (Node).  Blocks on critical CVEs.  Artifact: `pip_audit_result.json`. | P1 |
| GAT-032 | Gate 3 â€” Secrets Pre-commit | `type: secrets_scan`.  Runs `sf_secrets.scan()` against the diff of the PR.  Blocks on any detected secret in source code.  Artifact: `secrets_scan_result.json`. | P1 |
| GAT-033 | Gate 4 â€” Performance Regression | `type: performance_regression`.  Compares p95 latency against baseline.  Block if any service degrades > 20%.  Artifact: `perf_regression_result.json`. | P2 |
| GAT-034 | Gate 5 â€” Governance | (PRRI â€” defined above in GAT-010) | P0 |
| GAT-035 | Gate 6 â€” Trust | (HRI + PII + Secrets â€” defined above in GAT-020) | P0 |
| GAT-036 | Reference `sf-gate.yaml` | Ship `examples/gates/sf-gate.yaml` with all 6 gates pre-configured and commented.  Used as the canonical reference for HallucCheck integration. | P0 |

### 11.5  SLSA & Supply Chain Security (Industry Standard)

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| GAT-040 | SLSA Level 2 provenance | Generate signed SLSA provenance attestations for every release build.  Provenance: `builder.id`, `build.type`, `invocation.configSource`, `materials` (git commit SHA + tag), `metadata.buildInvocationId`.  Signed with Sigstore/cosign. | P1 |
| GAT-041 | SLSA Level 3 â€” isolated build | CI pipeline runs in an ephemeral, hermetic build environment.  Build instructions fetched from version-controlled source, not mutable scripts. | P2 |
| GAT-042 | SBOM generation | CycloneDX 1.5 SBOM generated for every release.  `spanforge sbom generate --format cyclonedx > sbom.json`.  SBOM included in CEC bundle under `sbom/`. | P1 |
| GAT-043 | SBOM vulnerability enrichment | SBOM enriched with VEX (Vulnerability Exploitability eXchange) statements.  Known CVEs with `not_affected` status documented with justification. | P2 |
| GAT-044 | Sigstore / cosign artifact signing | All release wheel, Docker image, and SBOM artifacts signed with `cosign sign`.  Signature stored in Rekor transparency log.  Verification: `cosign verify <artifact>`. | P2 |
| GAT-045 | Dependency pinning policy | All Python dependencies pinned to exact versions in `requirements.txt`.  Automated weekly `pip-compile` PR to update pins.  No `>=` ranges in production dependencies. | P1 |

---

## 12. Phase 9 — Integration Config & Local Fallback

### Context
HallucCheck requires a `[spanforge]` config block in `.halluccheck.toml` that bootstraps all 8 services.  This phase implements the config parser, service registry, health check endpoint, and the graceful local-fallback path.

### 12.1  `.halluccheck.toml` Config Block

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| CFG-001 | `[spanforge]` block parser | Parse `enabled`, `project_id`, `api_key` (from env, never stored), `endpoint`, `[spanforge.services]` toggle dict (8 booleans), `[spanforge.local_fallback]` sub-block.  Inject into `SFClientConfig` at startup.  Unknown keys → warning, not error. | P0 |
| CFG-002 | `[spanforge.services]` service toggles | Each of the 8 services can be individually enabled/disabled: `sf_observe`, `sf_pii`, `sf_secrets`, `sf_audit`, `sf_gate`, `sf_cec`, `sf_identity`, `sf_alert`.  Disabled service → always uses local fallback regardless of endpoint availability. | P0 |
| CFG-003 | `[spanforge.local_fallback]` | `enabled` (bool), `max_retries` (int, default 3), `timeout_ms` (int, default 2000).  Enterprise mode: `enabled = false` is enforced — any service unreachability raises `SFServiceUnavailableError` immediately. | P0 |
| CFG-004 | `[pii]` block | `enabled`, `action` (flag\|redact\|block), `threshold` (0.0–1.0), `entity_types` (list), `dpdp_scope` (list of purposes).  Validated against known entity types at startup. | P0 |
| CFG-005 | `[secrets]` block | `enabled`, `auto_block` (bool), `confidence` (0.0–1.0), `allowlist` (list of known-safe patterns), `store_redacted` (bool). | P0 |
| CFG-006 | Env var precedence layer | `SPANFORGE_ENDPOINT`, `SPANFORGE_API_KEY`, `SPANFORGE_PROJECT_ID`, `SPANFORGE_PII_THRESHOLD`, `SPANFORGE_SECRETS_AUTO_BLOCK` etc.  Env vars always override `.halluccheck.toml`.  Startup log prints resolved config (values redacted) at DEBUG level. | P0 |
| CFG-007 | Config validation schema | JSONSchema or `pydantic` model for the full `.halluccheck.toml` v6.0 schema.  `spanforge config validate` CLI command — exit 0 if valid, exit 1 with errors. | P1 |

### 12.2  Service Registry & Startup Health Check

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| CFG-010 | `ServiceRegistry` singleton | Holds references to all 8 instantiated service clients.  Initialised once at startup.  `registry.get("sf_pii") -> SFPIIClient`.  Thread-safe. | P0 |
| CFG-011 | Startup connectivity check | On first request after config load, ping all enabled services.  Status per service: `up`, `degraded` (responded but latency > 2 s), `down` (unreachable).  Log table at INFO level.  If any P0 service `down` and `local_fallback.enabled=false` → raise `SFStartupError`. | P0 |
| CFG-012 | `GET /v1/spanforge/status` endpoint | Per spec §6.  Returns `{sf_pii, sf_secrets, sf_audit, sf_observe, sf_gate, sf_cec, sf_identity, sf_alert}` each with `{status: up\|degraded\|down, latency_ms, last_checked_at}`.  Available all tiers. | P0 |
| CFG-013 | Periodic health re-check | Background task re-checks all services every 60 s.  Status changes logged at WARNING.  Recovery (down → up) logged at INFO. | P1 |

### 12.3  Local Fallback Implementations

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| CFG-020 | sf-pii fallback | `local_fallback.enabled=true` + sf-pii unreachable → use `redact.scan_payload()` (regex scanner) + `presidio_backend` if available.  Log `WARNING: sf-pii unreachable, using local regex scan`. | P0 |
| CFG-021 | sf-secrets fallback | Regex-only scan (SEC-030).  Entropy scoring disabled in fallback. | P0 |
| CFG-022 | sf-audit fallback | Write to local JSONL file at `[audit.local_fallback_path]` (default: `~/.spanforge/audit_fallback.jsonl`).  HMAC chain still applied using local org secret. | P0 |
| CFG-023 | sf-observe fallback | Write spans to stdout in OTLP JSON format.  `LOCAL_SPAN: <json>` prefix for easy grep. | P0 |
| CFG-024 | sf-alert fallback | Log alert to stderr at WARNING level with full payload.  No network delivery. | P0 |
| CFG-025 | sf-identity fallback | Accept bearer token from `SPANFORGE_LOCAL_TOKEN` env var.  Skip JWT signature validation (trust locally for CLI use).  Log `WARNING: sf-identity unreachable, using local token`. | P0 |
| CFG-026 | sf-gate fallback | Run gate logic locally.  PRRI check reads local `prri_result.json` if present.  Trust gate checks local audit fallback JSONL. | P1 |
| CFG-027 | sf-cec fallback | Generate bundle from local audit fallback JSONL.  No BYOS upload — bundle written to local file. | P1 |
| CFG-028 | Fallback telemetry counters | `SPANFORGE_FALLBACK_ACTIVATIONS_TOTAL{service="sf_pii\|sf_secrets\|..."}` Prometheus counter.  Fallback duration tracked as histogram. | P2 |

---

## 13. Phase 10 — T.R.U.S.T. Scorecard & HallucCheck Contract

### Context
This phase delivers the complete HallucCheck ↔ SpanForge integration contract — the T.R.U.S.T. scorecard, all 5-pillar integration touchpoints, and the `hc trust-gate` composite command.

### 13.1  T.R.U.S.T. Scorecard

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| TRS-001 | T.R.U.S.T. dimension model | Five dimensions: **T**ransparency (explainability events), **R**eliability (HRI + drift), **U**serTrust (bias parity), **S**ecurity (PII + secrets hygiene), **T**raceability (audit chain completeness).  Each dimension scored 0–100.  Overall T.R.U.S.T. score = weighted average (weights configurable). | P0 |
| TRS-002 | Hallucination dimension write | After every `sf_audit.append(record, "halluccheck.score.v1")`, write to T.R.U.S.T. store.  `trust_dimension="hallucination"`, score = `(1 - hri) * 100`. | P0 |
| TRS-003 | Security dimension write | After every `halluccheck.pii.v1` or `halluccheck.secrets.v1` audit record, update Security dimension.  Score degrades per detection event and recovers over a 7-day rolling window of clean records. | P1 |
| TRS-004 | Traceability dimension | Score based on audit chain completeness: 100 if `verify_chain()` passes for last 30 days.  Degrades per gap or tampered event. | P1 |
| TRS-005 | T.R.U.S.T. scorecard API | `GET /v1/trust/scorecard?project_id=...` — returns all dimensions + trend.  History: `GET /v1/trust/scorecard/history?project_id=...&from=...&to=...`. | P1 |
| TRS-006 | T.R.U.S.T. badge | `GET /v1/trust/badge/{project_id}.svg` — shield.io-style SVG badge with overall score and colour band (green ≥ 80, amber ≥ 60, red < 60).  `ETag` cache-busted. | P2 |

### 13.2  HallucCheck Pipeline Integration Points

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| TRS-010 | Score pipeline (SF-002) | Every `POST /v1/score`: (1) `sf_pii.scan()` → apply pii_action.  (2) `sf_secrets.scan()` → auto-block if hit.  (3) NLI scoring on (redacted or original) text.  (4) `sf_observe.emit_span("hc.score.completed", {...})`.  (5) `sf_audit.append(score_record, "halluccheck.score.v1")` → T.R.U.S.T. write.  Latency overhead: < 400 ms p95 total for steps 1+2. | P0 |
| TRS-011 | Bias pipeline (SF touchpoints §4.2) | `POST /v1/bias`: (1) `sf_pii.scan()` on segment labels.  (2) `sf_audit.append(bias_report, "halluccheck.bias.v1")`.  (3) If `disparity > threshold` → `sf_alert.publish("halluccheck.bias.critical", ...)`.  (4) `sf_pii.anonymise(export_payload)` before leaderboard publish. | P0 |
| TRS-012 | Monitor pipeline (SF touchpoints §4.3) | `POST /v1/monitor/provider-event` → `sf_observe.add_annotation()`.  AMBER drift → `sf_alert.publish("halluccheck.drift.amber", ...)`.  RED drift → `sf_alert.publish("halluccheck.drift.red", ...)`.  OTel export → `sf_observe.export_spans()`. | P0 |
| TRS-013 | Risk pipeline (SF touchpoints §4.4) | `POST /v1/risk` → `sf_audit.append(prri_record, "halluccheck.prri.v1")`.  PRRI RED → `sf_alert.publish("halluccheck.prri.red", ...)`.  `hc risk --gate` → `sf_gate.evaluate("gate5_governance", prri_result)`.  `POST /v1/risk/cec` → `sf_cec.build_bundle()`. | P0 |
| TRS-014 | Benchmark pipeline (SF touchpoints §4.5) | `hc benchmark` run → `sf_audit.append(run_result, "halluccheck.benchmark_run.v1")`.  F1 regression → `sf_alert.publish("halluccheck.benchmark.regression", ...)`.  `hc benchmark publish` → `sf_pii.anonymise(export_payload)`. | P0 |

### 13.3  New API Endpoints (spec §6 completion)

| ID | Endpoint | Tier |
|----|----------|------|
| TRS-020 | `POST /v1/trust-gate` — Composite Trust Gate | Team+ |
| TRS-021 | `POST /v1/scan/pii` — Standalone PII scan | API+ |
| TRS-022 | `POST /v1/scan/secrets` — Standalone secrets scan | API+ |
| TRS-023 | `GET /v1/audit/{record_type}` — Audit query | Team+ |
| TRS-024 | `GET /v1/spanforge/status` — 8-service health | All |
| TRS-025 | `GET /v1/privacy/dsar/{subject_id}` — DSAR export | Enterprise |
| TRS-026 | `GET /v1/trust/scorecard` — T.R.U.S.T. scorecard | Team+ |
| TRS-027 | `GET /v1/trust/badge/{project_id}.svg` — T.R.U.S.T. badge | All |

---

## 14. Phase 11 — Enterprise Hardening & Supply Chain Security

### 14.1  Multi-Tenancy & Isolation

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| ENT-001 | Project-level data isolation | All audit records, PII detections, secrets detections, gate results scoped to `project_id`.  Cross-project queries require explicit `project_ids[]` list and `cross_project_read` scope.  Row-level filtering enforced at SDK layer. | P0 |
| ENT-002 | Namespace isolation | Extend SpanForge namespace system to scope all T.R.U.S.T. store records and gate artifacts by `(org_id, project_id)` composite key. | P1 |
| ENT-003 | Audit log isolation proof | Each project's HMAC chain uses a unique `org_secret` scoped to that project.  Cross-chain collusion impossible. | P0 |
| ENT-004 | Data residency — EU Cloud | All data for EU-scoped projects stored in EU data centres only.  `[project] data_residency = "eu"`.  EU projects routed to EU endpoint. | P1 |
| ENT-005 | Data residency — additional regions | US, AP (APAC), IN (India/DPDP).  `data_residency` enum: `eu\|us\|ap\|in\|global`. | P2 |

### 14.2  Encryption & Key Management

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| ENT-010 | Encryption at rest | Audit JSONL files encrypted with AES-256-GCM before WORM upload.  Key managed by sf-identity key store.  `encrypt_at_rest: true` in `[audit]`. | P1 |
| ENT-011 | Envelope encryption | DEK encrypted with PMK stored in HSM or cloud KMS (AWS KMS, Azure Key Vault, GCP KMS).  `[audit.kms] provider = "aws\|azure\|gcp"`. | P2 |
| ENT-012 | TLS mutual authentication | All SDK-to-service calls support mTLS.  `tls_cert_path`, `tls_key_path`, `tls_ca_path` config.  Certificate rotation without downtime via PKCS#12 reload. | P2 |
| ENT-013 | FIPS 140-2 mode | When `fips_mode = true`, restrict to FIPS-approved algorithms only.  Reject weak curves/ciphers at startup. | P3 |

### 14.3  Air-Gap & Self-Hosted

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| ENT-020 | Docker Compose self-hosted stack | `docker-compose.yml` deploying all 8 services locally.  Internal networking only — no external calls. | P1 |
| ENT-021 | Air-gap offline mode | `offline=true` — no network attempts at all.  All services run from bundled local implementations. | P1 |
| ENT-022 | Helm chart for Kubernetes | `helm/spanforge/` chart.  Configmaps, Sealed Secrets, HPA for sf-pii and sf-secrets. | P2 |
| ENT-023 | Container orchestration health endpoints | Each service exposes `GET /healthz` (liveness) and `GET /readyz` (readiness). | P1 |

### 14.4  Security Review

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| ENT-030 | OWASP API Security Top 10 audit | Formal review against all 10 OWASP API Security categories before each major milestone release. | P0 |
| ENT-031 | Threat model (STRIDE) | STRIDE threat model for all 8 service boundaries.  Documented in `docs/security/threat-model.md`.  Annual review. | P1 |
| ENT-032 | Annual penetration test | Third-party penetration test: all public API endpoints + authentication flows + audit chain integrity. | P2 |
| ENT-033 | Dependency vulnerability scanning | `pip-audit` on every PR.  Critical/High CVEs block merge.  `safety check` as secondary scanner. | P0 |
| ENT-034 | Static analysis | `bandit -r src/` + `semgrep --config=auto`.  High-severity findings block merge. | P0 |
| ENT-035 | Secrets never in logs audit | Automated test: replay all WARNING/ERROR log lines through `sf_secrets.scan()`.  Fail if any API key, JWT, or HMAC secret detected. | P0 |

---

## 15. Phase 12 — Developer Experience & Ecosystem

### 15.1  SDK Ergonomics

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| DX-001 | Type stubs for all 8 service clients | `.pyi` stub files with full type coverage for IDE autocompletion and mypy. | P1 |
| DX-002 | Async variants for all SDK methods | `await sf_pii.scan_async(text)`, `await sf_audit.append_async(record, schema_key)`, etc.  `AsyncSFServiceClient` base class. | P1 |
| DX-003 | SDK mock library | `spanforge.testing.mocks` — `MockSFPII`, `MockSFSecrets`, `MockSFAudit` etc.  `with spanforge.testing.mock_all_services():` context manager.  No network calls in tests. | P1 |
| DX-004 | SDK sandbox mode | `[spanforge] sandbox = true` — all service calls routed to local in-memory sandbox.  Costs/quotas not consumed. | P1 |
| DX-005 | `spanforge doctor` CLI command | Checks: config valid, all services reachable, API key not expired, PII/secrets patterns loaded, gate YAML valid, WORM backend accessible.  Coloured pass/fail output. | P1 |

### 15.2  Documentation

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| DX-010 | SDK reference docs | Auto-generated API docs from docstrings.  Each method: description, parameters, return type, example, error table. | P1 |
| DX-011 | HallucCheck integration guide | `docs/integrations/halluccheck.md` — step-by-step integration walkthrough with code examples for every integration point. | P0 |
| DX-012 | Migration guide v5→v6 | `docs/migrations/v5-to-v6.md` — maps every SF-CHG-xx change to the corresponding code change in HallucCheck. | P0 |
| DX-013 | Architecture decision records (ADRs) | `docs/adr/` — mandatory ADR for: SDK-only surface, topic-based alerts, schema key namespace design, local fallback policy, T.R.U.S.T. dimensions. | P1 |
| DX-014 | Runbook library | `docs/runbooks/` — one runbook per alert topic: meaning, immediate steps, escalation, resolution, post-mortem template. | P1 |

### 15.3  Testing & Quality Gates

| ID | Task | Detail | Pri |
|----|------|--------|-----|
| DX-020 | Unit test coverage ≥ 90% | All new Phase 1–10 code.  `pytest-cov` gate blocks merge below threshold. | P0 |
| DX-021 | Integration test suite | `tests/integration/` — end-to-end against local Docker Compose stack.  PII pipeline, secrets auto-block, audit chain, gate 5+6, CEC bundle, trust gate. | P1 |
| DX-022 | Contract tests (Pact) | Consumer-driven contract tests between HallucCheck and each SpanForge service.  Published to Pact Broker. | P2 |
| DX-023 | Chaos engineering tests | `tests/chaos/` — service unavailability, network partitions, WORM failures.  Verify fallback, no data loss, no secrets in logs. | P2 |
| DX-024 | Load tests | k6 load test scripts for scoring (100 rps), PII scan (50 rps), secrets scan (100 rps).  Verify p95 latency SLOs. | P2 |
| DX-025 | Property-based tests | `hypothesis` strategies for HMAC chain invariants, API key format, PII scan payload types, entropy scorer. | P2 |

---

## 16. Non-Functional Requirements

| Category | Requirement | Target | Measurement |
|----------|-------------|--------|-------------|
| **Latency — sf-pii scan** | p95 end-to-end | < 400 ms (Month 3) → < 200 ms (Month 18) | k6 histogram |
| **Latency — sf-secrets scan** | p95 end-to-end | < 200 ms (Month 3) → < 80 ms (Month 18) | k6 histogram |
| **Latency — sf-audit append** | p95 | < 50 ms | k6 histogram |
| **Latency — sf-identity verify_token** | p95 | < 20 ms (JWKS cached) | k6 histogram |
| **Latency — sf-gate evaluate** | p95 | < 2 s | k6 histogram |
| **Latency — sf-cec build_bundle** | p95 | < 30 s | k6 histogram |
| **Uptime — all services** | Monthly availability | > 99.5% (Month 3) → > 99.9% (Month 18) | Uptime monitor |
| **Throughput — scoring pipeline** | Sustained RPS | 100 rps (API tier), 1 000 rps (Enterprise) | k6 load test |
| **Chain integrity** | HMAC verify pass rate | 100% — any failure is a P0 incident | `verify_chain()` nightly job |
| **Test coverage** | Line coverage | ≥ 90% on all new code | `pytest-cov` CI gate |
| **Dependency CVEs** | Critical/High open CVEs | 0 — patched within 72 h of disclosure | `pip-audit` CI gate |
| **Secret leakage** | Secrets in logs | 0 — enforced by log-scan test | Automated log scan |
| **Cold start** | SDK initialisation time | < 500 ms (first request after cold start) | Startup benchmark |
| **Memory footprint** | SDK resident set | < 50 MB overhead above baseline | `psutil` benchmark |
| **Audit retention** | Records accessible | 7 years — WORM enforced | WORM policy verification |

---

## 17. Story Index

### HallucCheck v6.0 Spec Stories

| Spec Story | Title | Phase | Pri |
|------------|-------|-------|-----|
| SF-001 | Configure SpanForge in `.halluccheck.toml` | Phase 9 (CFG-001→007) | P0 |
| SF-002 | PII + Secrets scan on every score | Phase 3 (PII-010→012) + Phase 2 (SEC-010→013) + Phase 10 (TRS-010) | P0 |
| SF-003 | All audit records written with correct schema keys | Phase 4 (AUD-001→006) + Phase 10 (TRS-010→014) | P0 |
| SF-004 | Drift alerts via sf-alert | Phase 7 (ALT-001→003) + Phase 10 (TRS-012) | P0 |
| SF-005 | `hc risk --gate` as Gate 5 in sf-gate | Phase 8 (GAT-010→012) + Phase 10 (TRS-013) | P0 |
| SF-006 | `hc trust-gate` as Gate 6 in sf-gate | Phase 8 (GAT-020→025) + Phase 10 (TRS-020) | P0 |
| SF-007 | Secrets detection → block + CRITICAL alert | Phase 2 (SEC-010→013) | P0 |
| SF-008 | CEC bundle via sf-cec using sf-audit records | Phase 5 (CEC-001→005) | P1 |
| SF-009 | SSO via sf-identity (Okta/Azure AD) | Phase 1 (ID-040→043) | P1 |
| SF-010 | Free CLI local fallback | Phase 9 (CFG-020→028) | P1 |
| SF-011 | OTel export delegates to sf-observe | Phase 6 (OBS-001) | P1 |
| SF-012 | T.R.U.S.T. scorecard updated after every score | Phase 4 (AUD-030→031) + Phase 10 (TRS-001→006) | P2 |

### Industry-Standard Stories (this roadmap)

| Story ID | Title | Phase |
|----------|-------|-------|
| IS-001 | SLSA Level 2 provenance for all releases | Phase 8 (GAT-040) |
| IS-002 | CycloneDX SBOM generation | Phase 8 (GAT-042) |
| IS-003 | RFC 3161 trusted timestamp on CEC bundles | Phase 5 (CEC-020) |
| IS-004 | GDPR Article 17 Right to Erasure | Phase 3 (PII-021) |
| IS-005 | GDPR Article 30 Records of Processing | Phase 4 (AUD-042) |
| IS-006 | CCPA DSAR data export | Phase 3 (PII-022) |
| IS-007 | HIPAA Safe Harbor de-identification | Phase 3 (PII-023) |
| IS-008 | OpsGenie + Incident.io alert sinks | Phase 7 (ALT-030→032) |
| IS-009 | Webhook HMAC signing on all alert sinks | Phase 7 (ALT-034) |
| IS-010 | OWASP API Security Top 10 sign-off | Phase 1 (ID-064) + Phase 11 (ENT-030) |
| IS-011 | MFA/TOTP for all API keys | Phase 1 (ID-030→031) |
| IS-012 | Air-gap / self-hosted Docker stack | Phase 11 (ENT-020→021) |
| IS-013 | Prometheus metrics exposition | Phase 6 (OBS-022) |
| IS-014 | SOC 2 Type II readiness | Phase 4 (AUD-040) |
| IS-015 | ISO 27001 Annex A.12.4 compliance | Phase 4 (AUD-041) |
| IS-016 | Pre-commit secrets scanning hook | Phase 2 (SEC-040→041) |
| IS-017 | GitHub PAT + Stripe + Slack pattern detection | Phase 2 (SEC-003) |
| IS-018 | Escalation policy + on-call rotation | Phase 7 (ALT-020→022) |
| IS-019 | T.R.U.S.T. badge SVG | Phase 10 (TRS-006) |
| IS-020 | Contract tests (Pact) | Phase 12 (DX-022) |

---

## 18. Definition of Done

A story is **Done** when all of the following are true:

### Code Quality
- [ ] Implementation merged to `main`
- [ ] Unit tests written, coverage ≥ 90% on new code
- [ ] `mypy --strict` passes with no new errors
- [ ] `ruff` / `flake8` passes with no new warnings
- [ ] `bandit -r src/` — no new HIGH or CRITICAL findings
- [ ] `pip-audit` — no new Critical/High CVEs introduced
- [ ] No `# noqa` suppressions added without justification comment

### Security
- [ ] No secrets, PII, HMAC keys in any log output (automated log-scan test passes)
- [ ] All token comparisons use `hmac.compare_digest()`
- [ ] All `SecretStr`-wrapped values have `__repr__ = "<SecretStr:***>"`
- [ ] OWASP API Security Top 10 checklist reviewed for any new endpoint
- [ ] Input validation at all system boundaries — no injection vectors

### Contracts & Compatibility
- [ ] SDK method signature matches this roadmap spec
- [ ] Pact contract test (if applicable) updated and passing
- [ ] `.halluccheck.toml` schema validated against JSONSchema
- [ ] Audit record schema changes are additive only (backward-compatible)
- [ ] `GET /v1/spanforge/status` reflects new service correctly

### Observability
- [ ] New code paths emit appropriate OTel spans with correct attribute names
- [ ] Error paths set `otel.status_code=ERROR` and `exception.*` attributes
- [ ] Prometheus metric registered and documented
- [ ] Span attribute names conform to OTel Semantic Conventions

### Audit & Compliance
- [ ] All new audit record types registered in schema key registry (AUD-002)
- [ ] Correct schema key used in `sf_audit.append()`
- [ ] Audit records include all required fields per retention spec
- [ ] `verify_chain()` passes on any new chain-producing code path

### Documentation
- [ ] Docstring on every public method/class (parameters, returns, raises, example)
- [ ] CHANGELOG entry added (conventional commit format)
- [ ] Relevant `docs/` page updated or created
- [ ] ADR created if an architectural decision was made

### Release
- [ ] Integration test passes against local Docker Compose stack
- [ ] Load test p95 latency within SLO targets
- [ ] `spanforge doctor` passes in a clean environment
- [ ] Release notes reviewed by at least one other engineer

---

*Last updated: April 2026 — aligns with HallucCheck v6.0 spec and SpanForge Platform roadmap.*
