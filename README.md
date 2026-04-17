<h1 align="center">spanforge</h1>

<p align="center">
  <strong>The AI Compliance Platform for Agentic Systems.</strong><br/>
  Ship AI applications that are auditable, regulator-ready, and privacy-safe — from day one.
</p>

<p align="center">
  <em>Built on <a href="https://www.getspanforge.com/standard">RFC-0001 — the SpanForge AI Compliance Standard</a> for agentic AI systems.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9%2B-4c8cbf?logo=python&logoColor=white" alt="Python 3.9+"/>
  <a href="https://pypi.org/project/spanforge/"><img src="https://img.shields.io/pypi/v/spanforge?color=4c8cbf&logo=pypi&logoColor=white" alt="PyPI"/></a>
  <a href="https://www.getspanforge.com/standard"><img src="https://img.shields.io/badge/standard-SpanForge_RFC--0001-4c8cbf" alt="spanforge RFC-0001"/></a>
  <img src="https://img.shields.io/badge/coverage-92%25-brightgreen" alt="92% test coverage"/>
  <img src="https://img.shields.io/badge/tests-3376%20passing-brightgreen" alt="3376 tests"/>
  <img src="https://img.shields.io/badge/version-2.0.3-4c8cbf" alt="Version 2.0.3"/>
  <img src="https://img.shields.io/badge/dependencies-zero-brightgreen" alt="Zero dependencies"/>
  <a href="docs/index.md"><img src="https://img.shields.io/badge/docs-local-4c8cbf" alt="Documentation"/></a>
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"/>
</p>

---

## The problem

You're building AI applications in a world where regulators are catching up fast. The EU AI Act is in force. GDPR applies to every LLM that touches personal data. SOC 2 auditors want evidence that your AI systems are governed. And your team is stitching together ad-hoc logs, hoping they'll hold up in an audit.

**spanforge** solves this. It is a **compliance-first platform** — not a monitoring add-on — that gives every AI action in your stack a cryptographically signed, privacy-safe, regulator-ready record.

---

## What spanforge does

<table>
<tr>
<td width="50%">

### Compliance & Regulatory Mapping
- Map telemetry to **EU AI Act**, **GDPR**, **SOC 2**, **HIPAA**, **ISO 42001**, **NIST AI RMF** clauses automatically
- Generate HMAC-signed **evidence packages** with gap analysis
- Track **consent boundaries**, **HITL oversight**, **model registry** governance, and **explainability** coverage
- Produce audit-ready attestations with model owner, risk tier, and status metadata

</td>
<td width="50%">

### Privacy & Audit Infrastructure
- **PII redaction** — detect and strip sensitive data before it leaves your app
- **HMAC audit chains** — tamper-evident, blockchain-style event signing
- **GDPR subject erasure** — right-to-erasure with tombstone events that preserve chain integrity
- **Air-gapped deployment** — runs fully offline with zero egress

</td>
</tr>
<tr>
<td>

### Governance & Controls
- **Consent boundary monitoring** — `consent.granted`, `consent.revoked`, `consent.violation` events
- **Human-in-the-loop hooks** — `hitl.queued`, `hitl.reviewed`, `hitl.escalated`, `hitl.timeout` events
- **Model registry** — register, deprecate, retire models; attestations auto-warn on ungoverned models
- **Explainability tracking** — measure what % of AI decisions have explanations attached

</td>
<td>

### Developer Experience
- **Zero required dependencies** — pure Python 3.9+ stdlib
- **One-line setup** — `spanforge.configure()` and you're compliant
- **Auto-instrumentation** — patch OpenAI, Anthropic, LangChain, CrewAI, and more
- **18 CLI commands** — compliance checks, PII scans, audit-chain verification, all CI-ready

</td>
</tr>
</table>

---

## How it compares

spanforge is the only **open-standard, zero-dependency AI compliance platform**. Other tools are monitoring platforms that bolt on compliance as an afterthought. spanforge is compliance infrastructure that happens to capture the telemetry needed to prove it.

| Capability | **spanforge** | LangSmith | Langfuse | OpenLLMetry | Arize Phoenix |
|---|:---:|:---:|:---:|:---:|:---:|
| Regulatory framework mapping (EU AI Act, GDPR, SOC 2…) | ✅ | ❌ | ❌ | ❌ | ❌ |
| HMAC-signed evidence packages & attestations | ✅ | ❌ | ❌ | ❌ | ❌ |
| Consent boundary monitoring | ✅ | ❌ | ❌ | ❌ | ❌ |
| Human-in-the-loop compliance events | ✅ | ❌ | ❌ | ❌ | ❌ |
| Model registry with risk-tier governance | ✅ | ❌ | ❌ | ❌ | ❌ |
| Explainability coverage metrics | ✅ | ❌ | ❌ | ❌ | ❌ |
| Built-in PII redaction | ✅ | ❌ | ❌ | ❌ | ❌ |
| Tamper-proof audit chain | ✅ | ❌ | ❌ | ❌ | ❌ |
| GDPR subject erasure (right-to-erasure) | ✅ | ❌ | ❌ | ❌ | ❌ |
| Works fully offline / air-gapped | ✅ | ❌ | Self-host | Partial | Self-host |
| Open schema standard (RFC-driven) | ✅ | ❌ | ❌ | Partial | ❌ |
| Zero required dependencies | ✅ | ❌ | ❌ | ❌ | ❌ |
| OTLP export (any OTel backend) | ✅ | ❌ | ❌ | ✅ | ✅ |
| MIT license, no call-home | ✅ | Partial | ✅ | ✅ | ✅ |

> **Bottom line**: Others help you *watch* your AI. spanforge helps you *govern* it.

---

## Install

```bash
pip install spanforge
```

**Requires Python 3.9+.** Zero mandatory dependencies.

### Optional extras

```bash
pip install "spanforge[openai]"       # OpenAI auto-instrumentation
pip install "spanforge[langchain]"    # LangChain callback handler
pip install "spanforge[crewai]"       # CrewAI callback handler
pip install "spanforge[http]"         # Webhook + OTLP export
pip install "spanforge[datadog]"      # Datadog APM + metrics
pip install "spanforge[kafka]"        # Kafka EventStream source
pip install "spanforge[pydantic]"     # Pydantic v2 model layer
pip install "spanforge[otel]"         # OpenTelemetry SDK integration
pip install "spanforge[jsonschema]"   # Strict JSON Schema validation
pip install "spanforge[llamaindex]"   # LlamaIndex event handler
pip install "spanforge[gemini]"       # Google Gemini auto-instrumentation
pip install "spanforge[bedrock]"      # AWS Bedrock Converse API
pip install "spanforge[presidio]"     # Presidio-powered PII detection
pip install "spanforge[all]"          # everything above
```

---

## Quick start — compliance in 5 minutes

### 1. Configure and instrument

```python
import spanforge

spanforge.configure(
    service_name="my-agent",
    signing_key="your-org-secret",      # HMAC audit chain — tamper-proof
    redaction_policy="gdpr",            # PII stripped before export
    exporter="jsonl",
    endpoint="audit.jsonl",
)
```

Every event your app emits is now **signed**, **PII-redacted**, and **stored** — with zero per-call boilerplate.

### 2. Trace AI decisions

```python
with spanforge.start_trace("loan-approval-agent") as trace:
    with trace.llm_call("gpt-4o", temperature=0.2) as span:
        decision = call_llm(prompt)
        span.set_token_usage(input=512, output=200, total=712)
        span.set_status("ok")
```

### 3. Generate compliance evidence

```python
from spanforge.core.compliance_mapping import ComplianceMappingEngine

engine = ComplianceMappingEngine()
package = engine.generate_evidence_package(
    model_id="gpt-4o",
    framework="eu_ai_act",
    from_date="2026-01-01",
    to_date="2026-03-31",
    audit_events=events,
)

print(package.attestation.coverage_pct)            # e.g. 87.5%
print(package.attestation.explanation_coverage_pct) # e.g. 75.0%
print(package.attestation.model_risk_tier)          # e.g. "high"
print(package.gap_report)                           # what's missing
```

Or from the CLI:

```bash
spanforge compliance generate \
  --model gpt-4o \
  --framework eu_ai_act \
  --from 2026-01-01 --to 2026-03-31 \
  audit.jsonl
```

### 4. Hand to your auditor

The evidence package contains:
- **Clause mappings** — which telemetry events satisfy which regulatory clauses
- **Gap analysis** — which clauses lack evidence and need attention
- **HMAC-signed attestation** — cryptographic proof the evidence hasn't been tampered with
- **Model governance metadata** — owner, risk tier, status, warnings for deprecated/retired models
- **Explanation coverage** — percentage of AI decisions with explainability records

---

## Regulatory framework coverage

The `ComplianceMappingEngine` maps your telemetry events to specific regulatory clauses:

| Framework | Clause | Mapped events | What it proves |
|-----------|--------|---------------|----------------|
| **GDPR** | Art. 22 | `consent.*`, `hitl.*` | Automated decisions have consent + human oversight |
| **GDPR** | Art. 25 | `llm.redact.*`, `consent.*` | Privacy by design — PII handled before export |
| **EU AI Act** | Art. 13 | `explanation.*` | AI decisions are transparent and explainable |
| **EU AI Act** | Art. 14 | `hitl.*`, `consent.*` | Human oversight of high-risk AI |
| **EU AI Act** | Annex IV.5 | `llm.guard.*`, `llm.audit.*`, `hitl.*` | Technical documentation — safety + oversight |
| **SOC 2** | CC6.1 | `llm.audit.*`, `llm.trace.*`, `model_registry.*` | Logical access controls + model governance |
| **NIST AI RMF** | MAP 1.1 | `llm.trace.*`, `llm.eval.*`, `model_registry.*`, `explanation.*` | Risk identification and mapping |
| **HIPAA** | §164.312 | `llm.redact.*`, `llm.audit.*` | PHI access controls and audit |
| **ISO 42001** | A.5–A.10 | Full event set | AI management system controls |

---

## Compliance event types

spanforge defines purpose-built event types for AI governance — these aren't afterthought log messages, they are first-class compliance primitives:

| Category | Event types | Purpose |
|----------|------------|---------|
| **Consent** | `consent.granted`, `consent.revoked`, `consent.violation` | Track user consent for automated processing |
| **Human-in-the-Loop** | `hitl.queued`, `hitl.reviewed`, `hitl.escalated`, `hitl.timeout` | Prove human oversight of AI decisions |
| **Model Registry** | `model_registry.registered`, `model_registry.deprecated`, `model_registry.retired` | Govern model lifecycle and risk |
| **Explainability** | `explanation.generated` | Attach explanations to AI decisions |
| **Guardrails** | `llm.guard.*` | Safety classifier outputs and block decisions |
| **PII** | `llm.redact.*` | Audit trail of what PII was found and removed |
| **Audit** | `llm.audit.*` | Access logs and chain-of-custody records |
| **Traces** | `llm.trace.*` | Model calls, tokens, latency, cost |

---

## Core capabilities

### Tamper-proof audit chains

Every event is HMAC-SHA256 signed and chained to its predecessor — the same principle as certificate chains. Alter one event and the entire chain breaks.

```python
from spanforge.signing import AuditStream, verify_chain

stream = AuditStream(org_secret="your-secret")
for event in events:
    stream.append(event)

result = verify_chain(stream.events, org_secret="your-secret")
assert result.valid  # any tampering → False
```

### PII redaction

Strip personal data before events leave your application boundary. Deep scanning with Luhn and Verhoeff validation for credit cards and Aadhaar numbers, SSN range validation (`_is_valid_ssn`), calendar validation for dates of birth (`_is_valid_date`), and built-in patterns for `date_of_birth` and street `address`.

```python
from spanforge.redact import RedactionPolicy, Sensitivity

policy = RedactionPolicy(min_sensitivity=Sensitivity.PII, redacted_by="policy:gdpr-v1")
result = policy.apply(event)
# All PII fields → "[REDACTED by policy:gdpr-v1]"
```

### Model registry governance

Register models with ownership and risk metadata. Attestations automatically warn when models are deprecated, retired, or unregistered.

```python
from spanforge.model_registry import ModelRegistry

registry = ModelRegistry()
registry.register("gpt-4o", owner="ml-platform", risk_tier="high")
registry.deprecate("gpt-3.5-turbo", reason="Successor available")

# Evidence packages now include:
#   model_owner: "ml-platform"
#   model_risk_tier: "high"
#   model_status: "active"
#   model_warnings: []  (or ["model 'gpt-3.5-turbo' is deprecated"])
```

### Explainability tracking

Measure what percentage of your AI decisions have explanations attached:

```python
from spanforge.explain import generate_explanation

explanation = generate_explanation(
    decision_event_id="evt_01HX...",
    method="feature_importance",
    content="Top factors: credit_score (0.42), income (0.31)...",
)
# explanation_coverage_pct in attestations = explained / total decisions
```

### GDPR subject erasure

Right-to-erasure with tombstone events that preserve audit chain integrity:

```bash
spanforge audit erase audit.jsonl --subject-id user123
```

---

## Auto-instrumentation

Patch supported providers once — compliance data flows automatically:

```python
# Instrument all installed providers in one call
import spanforge.auto
spanforge.auto.setup()

# Or patch individually
from spanforge.integrations import openai as sf_openai
sf_openai.patch()    # every OpenAI call → signed, redacted, compliant
sf_openai.unpatch()  # restore original behaviour
```

**Supported providers:** OpenAI, Anthropic, Google Gemini, AWS Bedrock, Ollama, Groq, Together AI

**Supported frameworks:** LangChain, LlamaIndex, CrewAI

---

## Using SpanForge alongside OpenTelemetry

spanforge is not an OTel replacement. OTel handles performance monitoring. spanforge adds the compliance layer OTel cannot provide — audit chains, PII redaction, consent tracking, and regulator-ready attestations.

```python
# Your existing OTel pipeline stays untouched
from opentelemetry.sdk.trace import TracerProvider
provider = TracerProvider()

# Add spanforge's compliance layer alongside it
import spanforge
spanforge.configure(mode="otel_passthrough")

# Dual-stream: OTel for monitoring, spanforge for compliance
spanforge.configure(exporters=["otel_passthrough", "jsonl"], endpoint="audit.jsonl")
```

---

## Export

Ship compliance events to any backend:

```python
from spanforge.stream import EventStream
from spanforge.export.jsonl import JSONLExporter
from spanforge.export.otlp import OTLPExporter
from spanforge.export.datadog import DatadogExporter
from spanforge.export.grafana import GrafanaLokiExporter
from spanforge.export.cloud import CloudExporter

stream = EventStream(events)

await stream.drain(JSONLExporter("audit.jsonl"))                    # local file
await stream.drain(OTLPExporter("http://collector:4318/v1/traces")) # OTel collector
await stream.drain(DatadogExporter(service="my-app"))               # Datadog APM
await stream.drain(GrafanaLokiExporter(url="http://loki:3100"))     # Grafana Loki
await stream.drain(CloudExporter(api_key="sf_live_xxx"))            # spanforge Cloud
```

Fan-out routing for compliance alerting:

```python
from spanforge.export.webhook import WebhookExporter

# Route guardrail violations to Slack
await stream.route(
    WebhookExporter("https://hooks.slack.com/your-webhook"),
    predicate=lambda e: e.event_type == "llm.guard.output.blocked",
)
```

---

## CLI

18 commands — all CI-pipeline ready:

```bash
# Compliance
spanforge compliance generate --model gpt-4o --framework eu_ai_act \
  --from 2026-01-01 --to 2026-03-31 events.jsonl
spanforge compliance check evidence.json
spanforge compliance validate-attestation evidence.json

# Compliance
spanforge compliance generate --model gpt-4o --framework eu_ai_act \
  --from 2026-01-01 --to 2026-03-31 events.jsonl
spanforge compliance check evidence.json
spanforge compliance validate-attestation evidence.json
spanforge compliance status --events-file events.jsonl   # compliance summary JSON

# Audit chain
spanforge audit-chain events.jsonl             # verify chain integrity
spanforge audit erase events.jsonl --subject-id user123  # GDPR erasure
spanforge audit rotate-key events.jsonl        # key rotation
spanforge audit verify --input events.jsonl    # verify integrity

# Privacy
spanforge scan events.jsonl --fail-on-match    # CI-gate PII scan

# Validation
spanforge check                                # end-to-end health check
spanforge check-compat events.json             # v2.0 compatibility
spanforge validate events.jsonl                # JSON Schema validation

# Analysis
spanforge stats events.jsonl                   # counts, tokens, cost
spanforge inspect <EVENT_ID> events.jsonl      # pretty-print one event
spanforge cost events.jsonl                    # token spend report
spanforge cost run --run-id <id> --input events.jsonl  # per-run cost report

# Evaluation
spanforge eval save --input events.jsonl --output dataset.jsonl  # extract eval dataset
spanforge eval run --file dataset.jsonl --scorers faithfulness,pii_leakage  # run scorers

# Migration
spanforge migrate events.jsonl --sign          # v1→v2 migration
spanforge migrate-langsmith export.jsonl       # LangSmith → SpanForge conversion
spanforge list-deprecated                      # deprecated event types
spanforge migration-roadmap                    # v2 migration plan
spanforge check-consumers                      # consumer compatibility

# Viewer
spanforge serve                                # local SPA trace viewer
spanforge ui                                   # standalone HTML viewer
```

---

## Event namespaces

Every event carries a typed ``payload``. The built-in namespaces:

| Prefix | Dataclass | What it records |
|---|---|---|
| `consent.*` | — | User consent grants, revocations, violations |
| `hitl.*` | — | Human-in-the-loop review, escalation, timeout |
| `model_registry.*` | — | Model registration, deprecation, retirement |
| `explanation.*` | — | Explainability records for AI decisions |
| `llm.trace.*` | `SpanPayload` | Model calls — tokens, latency, cost **(frozen v2)** |
| `llm.guard.*` | `GuardPayload` | Safety classifier outputs, block decisions |
| `llm.redact.*` | `RedactPayload` | PII audit — what was found and removed |
| `llm.audit.*` | — | Access logs and chain-of-custody |
| `llm.eval.*` | `EvalScenarioPayload` | Scores, labels, evaluator identity |
| `llm.cost.*` | `CostPayload` | Per-call cost in USD |
| `llm.cache.*` | `CachePayload` | Cache hit/miss, backend, TTL |
| `llm.prompt.*` | `PromptPayload` | Prompt template version, rendered text |
| `llm.fence.*` | `FencePayload` | Topic constraints, allow/block lists |
| `llm.diff.*` | `DiffPayload` | Prompt/response delta between events |
| `llm.template.*` | `TemplatePayload` | Template registry metadata |

---

## Architecture

```
spanforge/
├── core/
│   └── compliance_mapping.py  ← ComplianceMappingEngine, evidence packages, attestations
├── compliance/                ← Programmatic compliance test suite
├── signing.py                 ← HMAC audit chains, key management, multi-tenant KeyResolver
├── redact.py                  ← PII detection + redaction policies
├── model_registry.py          ← Model lifecycle governance
├── explain.py                 ← Explainability records
├── consent.py                 ← Consent boundary events
├── hitl.py                    ← Human-in-the-loop events
├── governance.py              ← Policy-based event gating
├── event.py                   ← Event envelope
├── types.py                   ← EventType enum (consent.*, hitl.*, model_registry.*, explanation.*, llm.*)
├── config.py                  ← configure() / get_config()
├── _span.py                   ← Span, AgentRun, AgentStep context managers
├── _trace.py                  ← Trace + start_trace()
├── _tracer.py                 ← Top-level tracing entry point
├── _stream.py                 ← Internal dispatch: sample → redact → sign → export
├── _store.py                  ← TraceStore ring buffer
├── _hooks.py                  ← HookRegistry (lifecycle hooks)
├── _server.py                 ← HTTP server (/traces, /compliance/summary)
├── _cli.py                    ← 18 CLI sub-commands
├── cost.py                    ← CostTracker, BudgetMonitor, @budget_alert
├── cache.py                   ← SemanticCache, @cached decorator
├── retry.py                   ← @retry, FallbackChain, CircuitBreaker
├── toolsmith.py               ← @tool, ToolRegistry
├── http.py                    ← Zero-dependency OpenAI-compatible HTTP client
├── io.py                      ← JSONL read/write/append utilities
├── plugins.py                 ← Entry-point plugin discovery
├── schema.py                  ← Lightweight zero-dependency JSON Schema validator
├── regression.py              ← Pass/fail regression detector
├── stats.py                   ← Percentile, latency summary utilities
├── presidio_backend.py        ← Optional Presidio-powered PII detection
├── _ansi.py                   ← ANSI color helpers (NO_COLOR aware)
├── lint/                      ← AST-based instrumentation linter (AO001–AO005)
├── export/                    ← JSONL, OTLP, Webhook, Datadog, Grafana Loki, Cloud
├── integrations/              ← OpenAI, Anthropic, Gemini, Bedrock, LangChain, LlamaIndex, CrewAI, Ollama, Groq, Together
├── namespaces/                ← Typed payload dataclasses
└── migrate.py                 ← Schema migration (v1 → v2), LangSmith migration
```

---

## What is inside the box

<table>
<thead>
<tr><th>Module</th><th>What it does</th><th>For whom</th></tr>
</thead>
<tbody>
<tr>
  <td><strong>Compliance & Governance</strong></td><td colspan="2"></td>
</tr>
<tr>
  <td><code>spanforge.compliance</code></td>
  <td><code>ComplianceMappingEngine</code> maps telemetry to regulatory frameworks (EU AI Act, ISO 42001, NIST AI RMF, GDPR, SOC 2, HIPAA). Generates evidence packages with HMAC-signed attestations. Consent, HITL, model registry, and explainability events integrated into clause mappings. Attestations include model owner, risk tier, status, warnings, and <code>explanation_coverage_pct</code>. Also: programmatic v2.0 compatibility checks — no pytest required.</td>
  <td>Compliance / legal / platform teams</td>
</tr>
<tr>
  <td><code>spanforge.signing</code></td>
  <td>HMAC-SHA256 event signing, tamper-evident audit chains, key strength validation, key expiry checks, environment-isolated key derivation, multi-tenant <code>KeyResolver</code> protocol, and <code>AsyncAuditStream</code></td>
  <td>Security / compliance teams</td>
</tr>
<tr>
  <td><code>spanforge.redact</code></td>
  <td>PII detection, sensitivity levels, redaction policies, deep <code>scan_payload()</code> with Luhn / Verhoeff / SSN-range / date-calendar validation, built-in <code>date_of_birth</code> and <code>address</code> patterns, and <code>contains_pii()</code> / <code>assert_redacted()</code> with raw string scanning</td>
  <td>Data privacy / GDPR teams</td>
</tr>
<tr>
  <td><code>spanforge.governance</code></td>
  <td>Policy-based event gating — block prohibited types, warn on deprecated usage, enforce custom rules</td>
  <td>Platform / compliance teams</td>
</tr>
<tr>
  <td><strong>Instrumentation & Tracing</strong></td><td colspan="2"></td>
</tr>
<tr>
  <td><code>spanforge.event</code></td>
  <td>The core <code>Event</code> envelope — the one structure all tools share</td>
  <td>Everyone</td>
</tr>
<tr>
  <td><code>spanforge.types</code></td>
  <td>All built-in event types — compliance events (<code>consent.*</code>, <code>hitl.*</code>, <code>model_registry.*</code>, <code>explanation.*</code>) and telemetry events (<code>llm.trace.*</code>, <code>llm.guard.*</code>, etc.)</td>
  <td>Everyone</td>
</tr>
<tr>
  <td><code>spanforge._span</code></td>
  <td>Span, AgentRun, AgentStep context managers. <code>contextvars</code>-based async/thread-safe propagation. <code>async with</code>, <code>span.add_event()</code>, <code>span.set_timeout_deadline()</code></td>
  <td>App developers</td>
</tr>
<tr>
  <td><code>spanforge._trace</code></td>
  <td><code>Trace</code> + <code>start_trace()</code> — high-level tracing entry point; accumulates child spans</td>
  <td>App developers</td>
</tr>
<tr>
  <td><code>spanforge.config</code></td>
  <td><code>configure()</code> and <code>get_config()</code> — signing key, redaction policy, exporters, sample rate</td>
  <td>Everyone</td>
</tr>
<tr>
  <td><strong>Export & Integration</strong></td><td colspan="2"></td>
</tr>
<tr>
  <td><code>spanforge.export</code></td>
  <td>Ship events to JSONL, HTTP webhooks, OTLP collectors, Datadog APM, Grafana Loki, or spanforge Cloud</td>
  <td>Infra / compliance teams</td>
</tr>
<tr>
  <td><code>spanforge.stream</code></td>
  <td>Fan-out router — one <code>drain()</code> call reaches multiple backends; Kafka source</td>
  <td>Platform engineers</td>
</tr>
<tr>
  <td><code>spanforge.integrations</code></td>
  <td>Auto-instrumentation for OpenAI, Anthropic, LangChain, LlamaIndex, CrewAI, Groq, Ollama, Together</td>
  <td>App developers</td>
</tr>
<tr>
  <td><code>spanforge.auto</code></td>
  <td><code>setup()</code> auto-patches all installed LLM integrations; <code>teardown()</code> cleanly unpatches</td>
  <td>App developers</td>
</tr>
<tr>
  <td><strong>Developer Tools</strong></td><td colspan="2"></td>
</tr>
<tr>
  <td><code>spanforge.cost</code></td>
  <td><code>CostTracker</code>, <code>BudgetMonitor</code>, <code>@budget_alert</code> — track and alert on token spend</td>
  <td>App developers / FinOps</td>
</tr>
<tr>
  <td><code>spanforge.cache</code></td>
  <td><code>SemanticCache</code> + <code>@cached</code> — deduplicate LLM calls via cosine similarity; <code>InMemoryBackend</code>, <code>SQLiteBackend</code>, <code>RedisBackend</code></td>
  <td>App developers / FinOps</td>
</tr>
<tr>
  <td><code>spanforge.retry</code></td>
  <td><code>@retry</code>, <code>FallbackChain</code>, <code>CircuitBreaker</code>, <code>CostAwareRouter</code> — resilient LLM routing with compliance events</td>
  <td>App developers / SREs</td>
</tr>
<tr>
  <td><code>spanforge.toolsmith</code></td>
  <td><code>@tool</code> + <code>ToolRegistry</code> — register functions as typed tools; render JSON schemas for function-calling APIs</td>
  <td>App developers</td>
</tr>
<tr>
  <td><code>spanforge.lint</code></td>
  <td>AST-based instrumentation linter; AO001–AO005 codes; flake8 plugin; CLI</td>
  <td>All teams / CI</td>
</tr>
<tr>
  <td><strong>Utilities (v2.0.2+)</strong></td><td colspan="2"></td>
</tr>
<tr>
  <td><code>spanforge.http</code></td>
  <td><code>chat_completion()</code> — zero-dependency, synchronous OpenAI-compatible HTTP client with retry and back-off</td>
  <td>App developers</td>
</tr>
<tr>
  <td><code>spanforge.io</code></td>
  <td><code>read_jsonl()</code>, <code>write_jsonl()</code>, <code>append_jsonl()</code>, <code>write_events()</code>, <code>read_events()</code> — JSONL I/O utilities</td>
  <td>Everyone</td>
</tr>
<tr>
  <td><code>spanforge.schema</code></td>
  <td>Lightweight zero-dependency JSON Schema validator — <code>validate()</code>, <code>validate_strict()</code></td>
  <td>Tool authors / CI</td>
</tr>
<tr>
  <td><code>spanforge.regression</code></td>
  <td><code>RegressionDetector</code> — per-case pass/fail regression detection between baseline and current eval runs</td>
  <td>ML / eval teams</td>
</tr>
<tr>
  <td><code>spanforge.stats</code></td>
  <td><code>percentile()</code>, <code>latency_summary()</code> — statistical utilities for eval and performance analysis</td>
  <td>Analytics engineers</td>
</tr>
<tr>
  <td><code>spanforge.plugins</code></td>
  <td><code>discover(group)</code> — entry-point plugin discovery across Python 3.9–3.12+</td>
  <td>Plugin authors</td>
</tr>
<tr>
  <td><code>spanforge.presidio_backend</code></td>
  <td>Optional Presidio-powered PII detection backend — <code>presidio_scan_payload()</code> with standard <code>PIIScanResult</code></td>
  <td>Data privacy teams</td>
</tr>
<tr>
  <td><code>spanforge.eval</code></td>
  <td>Built-in scorers: <code>FaithfulnessScorer</code>, <code>RefusalDetectionScorer</code>, <code>PIILeakageScorer</code>, <code>BehaviourScorer</code> base class</td>
  <td>ML / eval teams</td>
</tr>
<tr>
  <td><code>spanforge.debug</code></td>
  <td><code>print_tree()</code>, <code>summary()</code>, <code>visualize()</code> — terminal tree, stats dict, HTML Gantt timeline</td>
  <td>App developers</td>
</tr>
<tr>
  <td><code>spanforge.metrics</code></td>
  <td><code>aggregate()</code> — success rates, latency percentiles, token totals, cost breakdowns</td>
  <td>Analytics engineers</td>
</tr>
<tr>
  <td><code>spanforge.testing</code></td>
  <td><code>MockExporter</code>, <code>capture_events()</code>, <code>assert_event_schema_valid()</code>, <code>trace_store()</code></td>
  <td>Test authors</td>
</tr>
<tr>
  <td><code>spanforge.validate</code></td>
  <td>JSON Schema validation against the published v2.0 schema</td>
  <td>All teams</td>
</tr>
<tr>
  <td><code>spanforge.namespaces</code></td>
  <td>Typed payload dataclasses for all built-in event namespaces</td>
  <td>Tool authors</td>
</tr>
<tr>
  <td><code>spanforge.models</code></td>
  <td>Optional Pydantic v2 models for validated schemas</td>
  <td>API / backend teams</td>
</tr>
<tr>
  <td><code>spanforge.consumer</code></td>
  <td>Declare schema-namespace dependencies; fail fast at startup if version requirements are not met</td>
  <td>Platform teams</td>
</tr>
<tr>
  <td><code>spanforge.deprecations</code></td>
  <td>Per-event-type deprecation notices at runtime</td>
  <td>Library maintainers</td>
</tr>
<tr>
  <td><code>spanforge._hooks</code></td>
  <td>Lifecycle hooks: <code>@hooks.on_llm_call</code>, <code>@hooks.on_tool_call</code>, <code>@hooks.on_agent_start</code> (sync + async)</td>
  <td>App developers / platform</td>
</tr>
<tr>
  <td><code>spanforge._store</code></td>
  <td><code>TraceStore</code> ring buffer — <code>get_trace()</code>, <code>list_tool_calls()</code>, <code>list_llm_calls()</code></td>
  <td>Platform / tooling engineers</td>
</tr>
<tr>
  <td><code>spanforge._cli</code></td>
  <td>CLI sub-commands including eval, compliance status, migrate-langsmith, cost run, and more</td>
  <td>DevOps / CI teams</td>
</tr>
</tbody>
</table>

---

## Quality

- **3 376 tests** passing (10 skipped) — unit, integration, property-based (Hypothesis), performance benchmarks
- **≥ 92 % line and branch coverage** — 90 % minimum enforced in CI
- **Zero required dependencies** — entire core runs on Python stdlib
- **Typed** — full `py.typed` marker; mypy + pyright clean
- **Frozen v2 trace schema** — `llm.trace.*` payload fields never break between minor releases
- **Async-safe** — `contextvars`-based context propagation across asyncio, threads, and executors

---

## Development

```bash
git clone https://github.com/veerarag1973/spanforge.git
cd spanforge
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
pytest                      # 3 376 tests
```

<details>
<summary><strong>Code quality</strong></summary>

```bash
ruff check . && ruff format .
mypy spanforge
pytest --cov                # >=90% required
```

</details>

<details>
<summary><strong>Build docs</strong></summary>

```bash
pip install -e ".[docs]"
cd docs && sphinx-build -b html . _build/html
```

</details>

---

## Versioning

spanforge implements **RFC-0001** (AI Compliance Standard for Agentic AI Systems). Current schema version: **2.0**.

This project follows [Semantic Versioning](https://semver.org/). The `llm.trace.*` namespace is additionally **frozen at v2** — even major releases won't remove fields from `SpanPayload`, `AgentRunPayload`, or `AgentStepPayload`.

See [docs/changelog.md](docs/changelog.md) for the full version history.

---

## Contributing

Contributions welcome — see the [Contributing Guide](docs/contributing.md). All new code must maintain ≥ 90 % coverage. Run `ruff` and `mypy` before submitting.

---

## Community

- **[Discussions](https://github.com/veerarag1973/spanforge/discussions)** — questions, ideas, show-and-tell
- **[Issues](https://github.com/veerarag1973/spanforge/issues)** — bug reports and feature requests
- **[SECURITY.md](SECURITY.md)** — responsible disclosure process
- **[Code of Conduct](CODE_OF_CONDUCT.md)** — Contributor Covenant v2.1

> Topics: `ai-compliance` `ai-governance` `eu-ai-act` `gdpr` `soc2` `audit-trail` `pii-redaction` `hmac-signing` `llm-governance` `python`

---

## License

[MIT](LICENSE) — free for personal and commercial use.

---

<p align="center">
  Built for teams that take AI governance seriously.<br/>
  <a href="docs/index.md">Docs</a> ·
  <a href="docs/quickstart.md">Quickstart</a> ·
  <a href="docs/api/index.md">API Reference</a> ·
  <a href="https://github.com/veerarag1973/spanforge/discussions">Discussions</a> ·
  <a href="https://github.com/veerarag1973/spanforge/issues">Report a bug</a>
</p>
  <td><code>spanforge.eval</code></td>
  <td>Built-in scorers: <code>FaithfulnessScorer</code>, <code>RefusalDetectionScorer</code>, <code>PIILeakageScorer</code>, <code>BehaviourScorer</code> base class</td>
  <td>ML / eval teams</td>
</tr>
<tr>
  <td><code>spanforge.debug</code></td>
  <td><code>print_tree()</code>, <code>summary()</code>, <code>visualize()</code> — terminal tree, stats dict, HTML Gantt timeline</td>
  <td>App developers</td>
</tr>
<tr>
  <td><code>spanforge.metrics</code></td>
  <td><code>aggregate()</code> — success rates, latency percentiles, token totals, cost breakdowns</td>
  <td>Analytics engineers</td>
</tr>
<tr>
  <td><code>spanforge.testing</code></td>
  <td><code>MockExporter</code>, <code>capture_events()</code>, <code>assert_event_schema_valid()</code>, <code>trace_store()</code></td>
  <td>Test authors</td>
</tr>
<tr>
  <td><code>spanforge.validate</code></td>
  <td>JSON Schema validation against the published v2.0 schema</td>
  <td>All teams</td>
</tr>
<tr>
  <td><code>spanforge.namespaces</code></td>
  <td>Typed payload dataclasses for all built-in event namespaces</td>
  <td>Tool authors</td>
</tr>
<tr>
  <td><code>spanforge.models</code></td>
  <td>Optional Pydantic v2 models for validated schemas</td>
  <td>API / backend teams</td>
</tr>
<tr>
  <td><code>spanforge.consumer</code></td>
  <td>Declare schema-namespace dependencies; fail fast at startup if version requirements are not met</td>
  <td>Platform teams</td>
</tr>
<tr>
  <td><code>spanforge.deprecations</code></td>
  <td>Per-event-type deprecation notices at runtime</td>
  <td>Library maintainers</td>
</tr>
<tr>
  <td><code>spanforge._hooks</code></td>
  <td>Lifecycle hooks: <code>@hooks.on_llm_call</code>, <code>@hooks.on_tool_call</code>, <code>@hooks.on_agent_start</code> (sync + async)</td>
  <td>App developers / platform</td>
</tr>
<tr>
  <td><code>spanforge._store</code></td>
  <td><code>TraceStore</code> ring buffer — <code>get_trace()</code>, <code>list_tool_calls()</code>, <code>list_llm_calls()</code></td>
  <td>Platform / tooling engineers</td>
</tr>
<tr>
  <td><code>spanforge._cli</code></td>
  <td>18 CLI sub-commands: compliance, audit, scan, validate, stats, serve, ui, and more</td>
  <td>DevOps / CI teams</td>
</tr>
</tbody>
</table>

---

## Quality

- **3 376 tests** passing (10 skipped) — unit, integration, property-based (Hypothesis), performance benchmarks
- **≥ 92 % line and branch coverage** — 90 % minimum enforced in CI
- **Zero required dependencies** — entire core runs on Python stdlib
- **Typed** — full `py.typed` marker; mypy + pyright clean
- **Frozen v2 trace schema** — `llm.trace.*` payload fields never break between minor releases
- **Async-safe** — `contextvars`-based context propagation across asyncio, threads, and executors

---

## Development

```bash
git clone https://github.com/veerarag1973/spanforge.git
cd spanforge
python -m venv .venv && .venv\Scripts\activate
pip install -e ".[dev]"
pytest                      # 3 376 tests
```

<details>
<summary><strong>Code quality</strong></summary>

```bash
ruff check . && ruff format .
mypy spanforge
pytest --cov                # >=90% required
```

</details>

<details>
<summary><strong>Build docs</strong></summary>

```bash
pip install -e ".[docs]"
cd docs && sphinx-build -b html . _build/html
```

</details>

---

## Versioning

spanforge implements **RFC-0001** (AI Compliance Standard for Agentic AI Systems). Current schema version: **2.0**.

This project follows [Semantic Versioning](https://semver.org/). The `llm.trace.*` namespace is additionally **frozen at v2** — even major releases won't remove fields from `SpanPayload`, `AgentRunPayload`, or `AgentStepPayload`.

See [docs/changelog.md](docs/changelog.md) for the full version history.

---

## Contributing

Contributions welcome — see the [Contributing Guide](docs/contributing.md). All new code must maintain ≥ 90 % coverage. Run `ruff` and `mypy` before submitting.

---

## Community

- **[Discussions](https://github.com/veerarag1973/spanforge/discussions)** — questions, ideas, show-and-tell
- **[Issues](https://github.com/veerarag1973/spanforge/issues)** — bug reports and feature requests
- **[SECURITY.md](SECURITY.md)** — responsible disclosure process
- **[Code of Conduct](CODE_OF_CONDUCT.md)** — Contributor Covenant v2.1

> Topics: `ai-compliance` `ai-governance` `eu-ai-act` `gdpr` `soc2` `audit-trail` `pii-redaction` `hmac-signing` `llm-governance` `python`

---

## License

[MIT](LICENSE) — free for personal and commercial use.

---

<p align="center">
  Built for teams that take AI governance seriously.<br/>
  <a href="docs/index.md">Docs</a> ·
  <a href="docs/quickstart.md">Quickstart</a> ·
  <a href="docs/api/index.md">API Reference</a> ·
  <a href="https://github.com/veerarag1973/spanforge/discussions">Discussions</a> ·
  <a href="https://github.com/veerarag1973/spanforge/issues">Report a bug</a>
</p>
