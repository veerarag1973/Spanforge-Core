# Documentation Index

> **spanforge** (`spanforge`) — The reference implementation of the [spanforge Standard](https://www.getspanforge.com/standard) (RFC-0001), the open event-schema standard for compliance and governance of agentic AI systems.  
> Current release: **2.0.10** — [Changelog](changelog.md) · [![PyPI](https://img.shields.io/pypi/v/spanforge?color=4c8cbf&logo=pypi&logoColor=white)](https://pypi.org/project/spanforge/)

This index links to every documentation page in this folder.

---

## Getting Started

| Page | Description |
|------|-------------|
| [Quickstart](quickstart.md) | Create your first event, sign a chain, and export — in 5 minutes |
| [Installation](installation.md) | Install from PyPI, optional extras, and dev setup |

---

## User Guide

| Page | Description |
|------|-------------|
| [User Guide](user_guide/index.md) | Overview of all user guide topics |
| [Events](user_guide/events.md) | Event envelope, event types, serialisation, validation, ULIDs |
| [Tracing API](user_guide/tracing.md) | `Trace`, `start_trace()`, async context managers, `span.add_event()`, error categories, timeout deadline |
| [HMAC Signing & Audit Chains](user_guide/signing.md) | Sign events, build tamper-evident chains, detect tampering |
| [PII Redaction](user_guide/redaction.md) | Sensitivity levels, redaction policies, PII detection |
| [Compliance & Tenant Isolation](user_guide/compliance.md) | Compatibility checklist, chain integrity, tenant isolation, `ComplianceMappingEngine`, evidence packages, regulatory framework mappings (EU AI Act, ISO 42001, NIST AI RMF, GDPR, SOC 2), HMAC-signed attestations, consent/HITL/model-registry/explainability clause integration, model owner & risk-tier enrichment, `explanation_coverage_pct` metric |
| [Export Backends & EventStream](user_guide/export.md) | JSONL, Webhook, OTLP, Datadog, Grafana Loki, Cloud exporters; EventStream; Kafka source |
| [Governance, Consumer Registry & Deprecations](user_guide/governance.md) | Block/warn event types, declare schema dependencies, track deprecations |
| [Migration Guide](user_guide/migration.md) | v2 migration roadmap, deprecation records, `v1_to_v2()` scaffold |
| [Debugging & Visualization](user_guide/debugging.md) | `print_tree()`, `summary()`, `visualize()`, and sampling controls |
| [Metrics & Analytics](user_guide/metrics.md) | `metrics.aggregate()`, `MetricsSummary`, `TraceStore`, `get_trace()` |
| [Semantic Cache](user_guide/cache.md) | `SemanticCache`, `@cached` decorator, `InMemoryBackend`, `SQLiteBackend`, `RedisBackend` |
| [Linting & Static Analysis](user_guide/linting.md) | `run_checks()`, AO001–AO005 error codes, flake8 plugin, CI integration |
| [Audit Service (sf-audit)](user_guide/audit.md) | `sf_audit.append()`, schema keys, T.R.U.S.T. scorecard, chain verification, GDPR Article 30, BYOS routing |
| [Alert Routing Service (sf-alert)](user_guide/alert.md) | `sf_alert.publish()`, topic registry, deduplication, rate limiting, escalation policy, maintenance windows, sinks (Slack, Teams, PagerDuty, OpsGenie, VictorOps, Incident.io, SMS, Webhook) |
| [Gate Pipeline (sf-gate)](user_guide/gate.md) | `sf_gate.evaluate()`, YAML pipeline runner, 6 gate executors, PRRI gate, trust gate, artifact store, CI/CD integration (Phase 8) |

---

## API Reference

| Page | Module |
|------|--------|
| [API Reference](api/index.md) | Module summary and full listing |
| [event](api/event.md) | `spanforge.event` — Event envelope and serialisation |
| [types](api/types.md) | `spanforge.types` — EventType enum, custom type validation |
| [signing](api/signing.md) | `spanforge.signing` — HMAC signing and AuditStream |
| [redact](api/redact.md) | `spanforge.redact` — Redactable, RedactionPolicy, PII helpers |
| [compliance](api/compliance.md) | `spanforge.compliance` — Compatibility and isolation checks |
| [export](api/export.md) | `spanforge.export` — OTLP, Webhook, JSONL, Datadog, Grafana Loki, Cloud backends |
| [stream](api/stream.md) | `spanforge.stream` — EventStream multiplexer with Kafka support |
| [validate](api/validate.md) | `spanforge.validate` — JSON Schema validation |
| [migrate](api/migrate.md) | `spanforge.migrate` — Migration scaffold, `SunsetPolicy`, `v2_migration_roadmap()` |
| [consumer](api/consumer.md) | `spanforge.consumer` — ConsumerRegistry, IncompatibleSchemaError |
| [governance](api/governance.md) | `spanforge.governance` — EventGovernancePolicy, GovernanceViolationError |
| [deprecations](api/deprecations.md) | `spanforge.deprecations` — DeprecationRegistry, warn_if_deprecated() |
| [integrations](api/integrations.md) | `spanforge.integrations` — LangChain, LlamaIndex, OpenAI, CrewAI adapters |
| [trace](api/trace.md) | `spanforge._trace` — `Trace` class and `start_trace()` |
| [debug](api/debug.md) | `spanforge.debug` — `print_tree()`, `summary()`, `visualize()` |
| [metrics](api/metrics.md) | `spanforge.metrics` — `aggregate()`, `MetricsSummary`, `LatencyStats` |
| [store](api/store.md) | `spanforge._store` — `TraceStore` and MCP trace access functions |
| [hooks](api/hooks.md) | `spanforge._hooks` — `HookRegistry`, `hooks` singleton, sync and async lifecycle hooks |
| [testing](api/testing.md) | `spanforge.testing` — `MockExporter`, `capture_events()`, `assert_event_schema_valid()`, `trace_store()` |
| [auto](api/auto.md) | `spanforge.auto` — `setup()` / `teardown()` integration auto-discovery |
| [ulid](api/ulid.md) | `spanforge.ulid` — ULID generation and helpers |
| [exceptions](api/exceptions.md) | `spanforge.exceptions` — Exception hierarchy |
| [models](api/models.md) | `spanforge.models` — Pydantic v2 model layer |
| [cache](api/cache.md) | `spanforge.cache` — `SemanticCache`, `@cached`, backends, `CacheEntry`, `CacheBackendError` |
| [lint](api/lint.md) | `spanforge.lint` — `run_checks()`, `LintError`, AO001–AO005, flake8 plugin, CLI |
| [http](api/http.md) | `spanforge.http` — HTTP trace viewer and `/traces` endpoint |
| [io](api/io.md) | `spanforge.io` — Event I/O helpers (read/write JSONL) |
| [plugins](api/plugins.md) | `spanforge.plugins` — Plugin discovery and loading |
| [schema](api/schema.md) | `spanforge.schema` — Schema utilities and version helpers |
| [regression](api/regression.md) | `spanforge.regression` — Regression detection and alerting |
| [stats](api/stats.md) | `spanforge.stats` — Statistical helpers and summary functions |
| [eval](api/eval.md) | `spanforge.eval` — Evaluation scorers and dataset management |
| [consent](api/consent.md) | `spanforge.consent` — Consent tracking and data-subject management |
| [hitl](api/hitl.md) | `spanforge.hitl` — Human-in-the-loop review queues |
| [model_registry](api/model_registry.md) | `spanforge.model_registry` — Model registration, risk tiers, ownership |
| [explain](api/explain.md) | `spanforge.explain` — Explainability records and coverage metrics |
| [presidio_backend](api/presidio_backend.md) | `spanforge.presidio_backend` — Presidio-based PII detection backend |
| [cost](api/cost.md) | `spanforge.cost` — Cost tracking and budget management |
| [identity](api/identity.md) | `spanforge.identity` — `SFIdentityClient`, `IdentityToken`, PII-safe audit events |
| [secrets](api/secrets.md) | `spanforge.secrets` — `SecretsScanner`, `SecretsScanResult`, `SecretHit`, 20-pattern registry, SARIF output |
| [pii](api/pii.md) | `spanforge.sdk.pii` — `SFPIIClient`, PII scanning, anonymisation, GDPR Art.17 erasure, CCPA DSAR, HIPAA safe harbor, DPDP consent gate, PIPL entity types (Phase 3) |
| [audit](api/audit.md) | `spanforge.sdk.audit` — `SFAuditClient`, HMAC chain, schema key registry, T.R.U.S.T. scorecard, Article 30, BYOS routing (Phase 4) |
| [cec](api/cec.md) | `spanforge.sdk.cec` — `SFCECClient`, signed ZIP compliance bundles, 5-framework clause mapping, `verify_bundle()`, `generate_dpa()`, HMAC signing, BYOS detection (Phase 5) |
| [observe](api/observe.md) | `spanforge.sdk.observe` — `SFObserveClient`, span export (OTLP/Datadog/Grafana/Splunk/Elastic/local), `emit_span()`, annotation store, W3C TraceContext, OTel GenAI attrs, sampling strategies, health probes (Phase 6) |
| [alert](api/alert.md) | `spanforge.sdk.alert` — `SFAlertClient`, topic-based publish, deduplication, rate limiting, escalation policy, maintenance windows, circuit breakers, 6 sink integrations (Phase 7) |
| [gate](api/gate.md) | `spanforge.sdk.gate` — `SFGateClient`, `GateRunner` YAML engine, 6 gate executors, PRRI evaluation, trust gate, `GateArtifact` store (Phase 8) |
| [config](api/config.md) | `spanforge.sdk.config` — `.halluccheck.toml` parser, `SFConfigBlock`, `SFServiceToggles`, `SFLocalFallbackConfig`, `load_config_file()`, `validate_config()`, `validate_config_strict()` (Phase 9) |
| [registry](api/registry.md) | `spanforge.sdk.registry` — `ServiceRegistry` singleton, health checks, background checker, `status_response()`, `ServiceHealth`, `ServiceStatus` (Phase 9) |
| [fallback](api/fallback.md) | `spanforge.sdk.fallback` — 8 local fallback implementations: `pii_fallback()`, `secrets_fallback()`, `audit_fallback()`, `observe_fallback()`, `alert_fallback()`, `identity_fallback()`, `gate_fallback()`, `cec_fallback()` (Phase 9) |
| [trust](api/trust.md) | `spanforge.sdk.trust` — `SFTrustClient`, T.R.U.S.T. five-pillar scorecard, SVG badge, history time-series, configurable weights (Phase 10) |
| [pipelines](api/pipelines.md) | `spanforge.sdk.pipelines` — 5 HallucCheck pipeline integrations (Phase 10) |
| [enterprise](api/enterprise.md) | `spanforge.sdk.enterprise` — `SFEnterpriseClient`, multi-tenancy, encryption, air-gap, health probes (Phase 11) |
| [security](api/enterprise.md#sfsecurityclient) | `spanforge.sdk.security` — `SFSecurityClient`, OWASP audit, STRIDE threat model, dependency scanning, secrets-in-logs (Phase 11) |

---

## Namespace Payload Catalogue

| Page | Namespace | Purpose |
|------|-----------|----------|
| [Namespace index](namespaces/index.md) | — | Overview and quick-reference table |
| [trace](namespaces/trace.md) | `llm.trace.*` | Model inputs, outputs, latency, token counts  |
| [cost](namespaces/cost.md) | `llm.cost.*` | Per-event cost estimates and budget tracking |
| [cache](namespaces/cache.md) | `llm.cache.*` | Cache hit/miss, key, TTL, backend metadata |
| [diff](namespaces/diff.md) | `llm.diff.*` | Prompt/response delta between two events |
| [eval](namespaces/eval.md) | `llm.eval.*` | Scoring, grading, and human-feedback payloads |
| [fence](namespaces/fence.md) | `llm.fence.*` | Perimeter checks, topic constraints, allow/block lists |
| [guard](namespaces/guard.md) | `llm.guard.*` | Safety classifier outputs and block decisions |
| [prompt](namespaces/prompt.md) | `llm.prompt.*` | Prompt versioning, template rendering, variable sets |
| [redact_ns](namespaces/redact_ns.md) | `llm.redact.*` | PII detection and redaction audit records |
| [template](namespaces/template.md) | `llm.template.*` | Template registry metadata and render snapshots |
| [audit](namespaces/audit.md) | `llm.audit.*` | HMAC audit chain events |

---

## Command-Line Interface

| Page | Description |
|------|-------------|
| [CLI](cli.md) | `spanforge` command reference: `check`, `check-compat`, `validate`, `audit-chain`, `audit`, `scan`, `migrate`, `inspect`, `stats`, `list-deprecated`, `migration-roadmap`, `check-consumers`, `compliance`, `cost`, `dev`, `module`, `serve`, `init`, `quickstart`, `report`, `eval`, `migrate-langsmith`, `ui`, `consent`, `hitl`, `model`, `explain`, `secrets`, `gate`, `config`, `trust`, `enterprise`, `security` |

---

## Development

| Page | Description |
|------|-------------|
| [Contributing](contributing.md) | Dev setup, code standards, PR checklist |
| [Changelog](changelog.md) | Version history and release notes |
