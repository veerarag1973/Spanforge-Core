# spanforge SDK — Release Runbook
# PyPI distribution: spanforge  |  Import: spanforge
# Version: 1.0.0 — 2026-03-04
#
# STATUS: READY TO PUBLISH
#
# ─────────────────────────────────────────────────────────────────────────────
# WHAT'S IN 1.0.0
# ─────────────────────────────────────────────────────────────────────────────
#
#   Phase 0   Package rename llm_toolkit_schema → spanforge
#   Phase 1   Configuration layer (configure(), env vars, singleton)
#   Phase 2   Core tracer + span (tracer.span() context manager)
#   Phase 3   Event emission (SpanPayload → Event → EventStream → Exporter)
#   Phase 4   Agent instrumentation (agent_run(), agent_step())
#   Phase 5   ConsoleExporter (human-readable dev output)
#   Phase 6   OpenAI integration (auto token + cost extraction)
#   Phase 7   Provider integrations (Anthropic, Ollama, Groq, Together AI)
#   Phase 8   Additional exporters (OTLP, Webhook, Datadog, Grafana Loki)
#   Phase 9   Framework integrations (LangChain, LlamaIndex)
#   Phase 10  CLI tooling (spanforge validate / audit-chain / inspect / stats)
#   Phase 11  Security + privacy (HMAC signing chain, PII redaction)
#   Phase 12  Hardening + docs + 1.0.0 (this release)
#
#   Tests      3023+ passing, 93.74% coverage
#
# ─────────────────────────────────────────────────────────────────────────────
# PREREQUISITES
# ─────────────────────────────────────────────────────────────────────────────
#
#   pip install build twine
#
# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURE CREDENTIALS (~/.pypirc)
# ─────────────────────────────────────────────────────────────────────────────
#
#   [distutils]
#   index-servers = pypi testpypi
#
#   [pypi]
#   username = __token__
#   password = pypi-XXXXXXXXXX...
#
#   [testpypi]
#   username = __token__
#   password = pypi-XXXXXXXXXX...
#
#   OR export as environment variables (CI/CD preferred):
#     $env:TWINE_USERNAME = "__token__"
#     $env:TWINE_PASSWORD = "pypi-XXXXXXXXXX..."
#
# ─────────────────────────────────────────────────────────────────────────────
# RELEASE STEPS
# ─────────────────────────────────────────────────────────────────────────────
#
#   1. Confirm all tests pass:
#        python -m pytest --tb=short -q
#
#   2. Confirm version:
#        python -c "import spanforge; print(spanforge.__version__)"
#        # → 1.0.0
#
#   3. Build distribution artefacts:
#        python -m build
#
#   4. Upload to TestPyPI and smoke-test:
#        python -m twine upload --repository testpypi dist/*
#        pip install --index-url https://test.pypi.org/simple/ spanforge==1.0.0
#        python -c "import spanforge; print(spanforge.__version__)"
#
#   5. Upload to PyPI:
#        python -m twine upload dist/*
#        # Users then: pip install spanforge
#
#   6. Tag the release:
#        git tag v1.0.0
#        git push origin v1.0.0
#
# ─────────────────────────────────────────────────────────────────────────────
# CHANGELOG
# ─────────────────────────────────────────────────────────────────────────────
#
#   1.0.0 (2026-03-04)  — Initial stable release
#     - Full SpanForge AI Compliance Standard v2.0 compliance
#     - HMAC signing chain (opt-in via signing_key=)
#     - PII redaction pipeline (opt-in via redaction_policy=)
#     - CLI: spanforge validate / audit-chain / inspect / stats
#     - Exporters: console, jsonl, otlp, webhook, datadog, grafana_loki, cloud
#     - Integrations: openai, anthropic, ollama, groq, together, langchain, llamaindex, crewai
#
#   2.0.0 (2026-03-15)  — Commercial features
#     - SPA Trace Viewer: spanforge serve / spanforge ui (single-page trace browser)
#     - ComplianceMappingEngine: regulatory framework mapping (EU AI Act, ISO 42001, NIST AI RMF, GDPR, SOC 2)
#       with evidence packages and HMAC-signed attestations
#     - CloudExporter: thread-safe, batched export to spanforge Cloud (exporter="cloud")
#     - CLI additions: compliance, cost, dev, module, serve, init, quickstart, report, ui
#     - Trace API: start_trace(), async with, HookRegistry, TraceStore, metrics.aggregate()
#     - 3023+ tests, 93.74% coverage
#
#   2.1.0 (2026-06-XX)  — Compliance integration hardening
#     - consent.* → GDPR Art. 22 (new), Art. 25; hitl.* → EU AI Act Art. 14 (new), Annex IV.5
#     - explanation.* → EU AI Act Art. 13 (new), NIST MAP 1.1
#     - model_registry.* → SOC 2 CC6.1, NIST MAP 1.1
#     - ComplianceAttestation gains model_owner, model_risk_tier, model_status, model_warnings,
#       explanation_coverage_pct fields
#     - /compliance/summary endpoint includes explanation_coverage_pct
#     - 3331 tests passing, 0 failures
