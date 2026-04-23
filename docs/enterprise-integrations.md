# Enterprise Integrations

Phase 5 is the integration surface that makes the runtime-governance story usable in real stacks without custom glue everywhere.

## GA Integration Story

The GA integration surface covers:

- OpenAI
- Anthropic
- Azure OpenAI
- LangChain
- LangGraph
- OTLP export
- OpenInference-compatible span translation
- JSONL export for audit workflows
- SIEM-friendly schema mapping

## Provider and Framework Paths

| Integration | Path | Primary use |
|-------------|------|-------------|
| OpenAI | `spanforge.integrations.openai` | SDK auto-instrumentation for traced LLM calls |
| Anthropic | `spanforge.integrations.anthropic` and pricing coverage | Claude integration and cross-provider cost normalization |
| Azure OpenAI | `spanforge.integrations.azure_openai` | Instance-level instrumentation for Azure-hosted OpenAI clients |
| LangChain | `spanforge.integrations.langchain` | Callback-based event capture |
| LangGraph | `spanforge.integrations.langgraph` | Governance-aware agent graph demo path |

## Export and Interop Paths

| Path | Module | Purpose |
|------|--------|---------|
| OTLP | `spanforge.export.otlp` | coexist with existing observability backends |
| JSONL | `spanforge.export.jsonl` and `spanforge.io` | audit retention, replay, air-gapped transport |
| Splunk | `spanforge.export.siem_splunk` | SIEM ingestion with normalized event mapping |
| Syslog / CEF | `spanforge.export.siem_syslog` | legacy SIEM and SOC pipelines |
| OpenInference | `spanforge.export.openinference` | interoperability with OpenInference consumers |

## When To Use Which Path

- Use OpenAI or Azure OpenAI instrumentation when you want token, model, and cost telemetry attached automatically to active spans.
- Use LangChain when your orchestration layer is already callback-oriented.
- Use LangGraph when you need node-level scope, RBAC, and lineage coverage in an agent workflow demo.
- Use JSONL when durability and offline portability matter more than streaming.
- Use OTLP when SpanForge should coexist with your current telemetry collector.
- Use SIEM exporters when the audience is the SOC instead of an observability team.
- Use OpenInference when you need downstream compatibility, but keep SpanForge packages as the source of signed governance evidence.

## Related Docs

- [API Reference: `spanforge.integrations`](api/integrations.md)
- [API Reference: `spanforge.export`](api/export.md)
- [User Guide: Export Backends](user_guide/export.md)
- [Runtime Governance GA Guide](runtime-governance.md)
