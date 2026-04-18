# API Reference

The spanforge API surface is organised by module. All public symbols are
exported at the top-level package under `spanforge`.

## Modules

- [event](event.md)
- [types](types.md)
- [signing](signing.md)
- [redact](redact.md)
- [compliance](compliance.md)
- [export](export.md)
- [stream](stream.md)
- [validate](validate.md)
- [normalizer](normalizer.md)
- [migrate](migrate.md)
- [consumer](consumer.md)
- [governance](governance.md)
- [deprecations](deprecations.md)
- [integrations](integrations.md)
- [trace](trace.md)
- [debug](debug.md)
- [metrics](metrics.md)
- [store](store.md)
- [hooks](hooks.md)
- [testing](testing.md)
- [auto](auto.md)
- [ulid](ulid.md)
- [exceptions](exceptions.md)
- [models](models.md)
- [cache](cache.md)
- [lint](lint.md)
- [eval](eval.md)
- [config](config.md)
- [http](http.md)
- [io](io.md)
- [plugins](plugins.md)
- [schema](schema.md)
- [regression](regression.md)
- [stats](stats.md)
- [secrets](secrets.md)
- [audit](audit.md)
- [cec](cec.md)
- [observe](observe.md)
- [gate](gate.md)

## Module summary

| Module | Responsibility |
|--------|---------------|
| `spanforge.event` | `Event` envelope and serialisation |
| `spanforge.types` | `EventType` enum, `SpanErrorCategory`, custom type validation |
| `spanforge.signing` | HMAC signing, `AuditStream`, chain verification |
| `spanforge.redact` | `Redactable`, `RedactionPolicy`, PII helpers |
| `spanforge.compliance` | `ComplianceMappingEngine`, evidence packages, regulatory framework mapping (EU AI Act, GDPR, SOC 2, HIPAA, ISO 42001, NIST AI RMF), chain integrity, scope verification |
| `spanforge.export` | OTLP, Webhook, JSONL, Datadog, and Grafana Loki export backends |
| `spanforge.stream` | `EventStream` multiplexer with Kafka support |
| `spanforge.validate` | JSON Schema validation helpers (version-aware: v1.0 + v2.0) |
| `spanforge.normalizer` | `ProviderNormalizer` protocol and `GenericNormalizer` fallback |
| `spanforge.migrate` | `MigrationResult`, `SunsetPolicy`, `DeprecationRecord`, `v2_migration_roadmap()` |
| `spanforge.consumer` | `ConsumerRegistry`, `ConsumerRecord`, `IncompatibleSchemaError` |
| `spanforge.governance` | `EventGovernancePolicy`, `GovernanceViolationError`, `GovernanceWarning` |
| `spanforge.deprecations` | `DeprecationRegistry`, `DeprecationNotice`, `warn_if_deprecated()` |
| `spanforge.integrations` | `LLMSchemaCallbackHandler` (LangChain), `LLMSchemaEventHandler` (LlamaIndex), `SpanForgeCrewAIHandler` (CrewAI), OpenAI `patch()` |
| `spanforge._trace` | `Trace` dataclass and `start_trace()` high-level entry point |
| `spanforge.debug` | `print_tree()`, `summary()`, `visualize()` debug utilities |
| `spanforge.metrics` | `aggregate()`, `MetricsSummary`, `LatencyStats`, per-metric helpers |
| `spanforge._store` | `TraceStore` ring buffer; `get_trace()`, `list_tool_calls()`, `list_llm_calls()` |
| `spanforge._hooks` | `HookRegistry`, `hooks` singleton, sync and async span lifecycle callbacks (`on_llm_call`, `on_tool_call`, `on_agent_start`, `on_agent_end` and `*_async` variants) |
| `spanforge.testing` | `MockExporter`, `capture_events()` context manager, `assert_event_schema_valid()`, `trace_store()` — test utilities with no real exporters required |
| `spanforge.auto` | `setup()` / `teardown()` — auto-detect and patch every installed LLM integration |
| `spanforge.ulid` | ULID generation and helpers |
| `spanforge.exceptions` | Package-level exception hierarchy |
| `spanforge.models` | Shared Pydantic base models |
| `spanforge.cache` | `SemanticCache`, `@cached` decorator, `InMemoryBackend`, `SQLiteBackend`, `RedisBackend`, `CacheEntry`, `CacheBackendError` |
| `spanforge.consent` | `ConsentPayload`, consent lifecycle tracking (`granted` / `revoked` / `violation`), GDPR Art. 22/25 mapping |
| `spanforge.hitl` | `HITLPayload`, human-in-the-loop review workflow (`queued` / `reviewed` / `escalated` / `timeout`), EU AI Act Art. 14 mapping |
| `spanforge.model_registry` | `ModelRegistryEntry`, model governance lifecycle (`registered` / `deprecated` / `retired`), attestation integration |
| `spanforge.explain` | `ExplainabilityRecord`, decision explainability (`generated`), EU AI Act Art. 13 / NIST MAP 1.1 mapping |
| `spanforge.lint` | `run_checks()`, `LintError`, AO001–AO005 checks, `SpanForgeChecker` flake8 plugin, `python -m spanforge.lint` CLI |
| `spanforge.eval` | `record_eval_score()`, `EvalScore`, `EvalRunner`, `EvalReport`, `RegressionDetector` (mean-based), `BehaviourScorer` ABC, built-in scorers |
| `spanforge.config` | `SpanForgeConfig`, `configure()`, `get_config()`, `interpolate_env()` — global configuration and env-var interpolation |
| `spanforge.http` | `chat_completion()`, `ChatCompletionResponse` — zero-dependency OpenAI-compatible HTTP client with exponential-backoff retry |
| `spanforge.io` | `write_jsonl()`, `read_jsonl()`, `append_jsonl()`, `write_events()`, `read_events()` — synchronous JSONL read/write utilities |
| `spanforge.plugins` | `discover(group)` — Python-version-aware entry-point plugin discovery (3.9 / 3.10 / 3.12+) |
| `spanforge.schema` | `validate()`, `validate_strict()`, `SchemaValidationError` — lightweight zero-dependency JSON Schema validator |
| `spanforge.regression` | `RegressionDetector`, `RegressionReport`, `compare()` — pass/fail and score-drop regression detection |
| `spanforge.stats` | `percentile()`, `latency_summary()` — latency statistics with linear-interpolation percentiles |
| `spanforge._ansi` | `color()`, `strip_ansi()`, ANSI color constants — terminal colour helpers with `NO_COLOR` / non-TTY support |
| `spanforge.secrets` | `SecretsScanner`, `SecretsScanResult`, `SecretHit`, `entropy_score()` — 20-pattern secrets detection engine with SARIF 2.1.0 output and zero-tolerance auto-block for 10 high-risk credential types |
| `spanforge.sdk.secrets` | `SFSecretsClient` — SDK client with local + remote modes, `scan()`, `scan_batch()`, `SFSecretsBlockedError`, `SFSecretsError`, `SFSecretsScanError` |
| `spanforge.sdk.audit` | `SFAuditClient` — HMAC-chained record append, schema key registry, SQLite index query, T.R.U.S.T. scorecard, Article 30 RoPA, BYOS backend routing (Phase 4) |
| `spanforge.sdk.cec` | `SFCECClient` — signed ZIP compliance evidence bundles, 5-framework clause mapping (EU AI Act, ISO 42001, NIST AI RMF, ISO 27001, SOC 2), `verify_bundle()`, `generate_dpa()`, HMAC signing, BYOS detection (Phase 5) |
| `spanforge.sdk.observe` | `SFObserveClient` — span export (OTLP/Datadog/Grafana/Splunk/Elastic/local), annotation store, `emit_span()` with W3C TraceContext + OTel GenAI attrs, sampling strategies, health probes (Phase 6) |
| `spanforge.sdk.gate` | `SFGateClient`, `GateRunner` YAML engine, 6 gate executors (`schema_validation`, `dependency_security`, `secrets_scan`, `performance_regression`, `halluccheck_prri`, `halluccheck_trust`), `GateArtifact` store, PRRI evaluation, trust gate, 5 gate exception types (Phase 8) |
