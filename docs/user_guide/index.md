# User Guide

This guide covers all major features of spanforge in depth.
Start with [Events](events.md) if you are new to the library, then proceed to
whichever features your use case requires.

## Contents

- [Events](events.md)
- [Tracing API](tracing.md) — `Trace`, `start_trace()`, async spans, `add_event()`, error categories
- [HMAC Signing & Audit Chains](signing.md)
- [PII Redaction](redaction.md)
- [Compliance & Tenant Isolation](compliance.md)
- [Export Backends & EventStream](export.md)
- [Governance, Consumer Registry & Deprecations](governance.md)
- [Migration Guide](migration.md)
- [Debugging & Visualization](debugging.md) — `print_tree()`, `summary()`, `visualize()`, sampling
- [Metrics & Analytics](metrics.md) — `metrics.aggregate()`, `MetricsSummary`, `TraceStore`
- [Semantic Cache](cache.md) — `SemanticCache`, `@cached`, `InMemoryBackend`, `SQLiteBackend`, `RedisBackend`
- [Linting & Static Analysis](linting.md) — `run_checks()`, AO001–AO005, flake8 plugin, CI integration
- [Audit Service (sf-audit)](audit.md) — `sf_audit.append()`, schema key registry, T.R.U.S.T. scorecard, chain verification, GDPR Article 30, BYOS routing
- [In-Memory State Behaviour](in_memory_state.md) — risks of local/sandbox mode, multi-process inconsistency, production checklist
- [Runtime Governance GA Guide](../runtime-governance.md) — GA services, policy actions, replay/simulation, operator workflow, evidence exports
- [Runtime Governance Contracts](../runtime-governance-contracts.md) — stable GA control contracts, evidence contract, and fallback semantics
- [Replay, Simulation, and Calibration](../replay-simulation.md) — candidate-policy testing, comparison, and threshold tuning
- [Evidence Export Guide](../evidence-export.md) — operator packages, enterprise packages, JSONL archives, SIEM, and OpenInference
- [Enterprise Integrations](../enterprise-integrations.md) — OpenAI, Anthropic, Azure OpenAI, LangChain, LangGraph, OTLP, JSONL, SIEM
- [RAG Tracing](rag.md) — `sf_rag.trace_query()`, retrieval scoring, grounding, session lifecycle, privacy controls
- [User Feedback](feedback.md) — `sf_feedback.submit()`, rating enums, NPS/CSAT/thumbs, T.R.U.S.T. integration
- [SSO & Identity](../api/identity.md) — SAML 2.0, SCIM 2.0, OIDC PKCE, SSO session delegation, `SFIdentityClient`
