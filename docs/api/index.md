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

## Module summary

| Module | Responsibility |
|--------|---------------|
| `spanforge.event` | `Event` envelope and serialisation |
| `spanforge.types` | `EventType` enum, `SpanErrorCategory`, custom type validation |
| `spanforge.signing` | HMAC signing, `AuditStream`, chain verification |
| `spanforge.redact` | `Redactable`, `RedactionPolicy`, PII helpers |
| `spanforge.compliance` | Compatibility checks, isolation, chain integrity, scope verification |
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
| `spanforge.lint` | `run_checks()`, `LintError`, AO001–AO005 checks, `SpanForgeChecker` flake8 plugin, `python -m spanforge.lint` CLI |
