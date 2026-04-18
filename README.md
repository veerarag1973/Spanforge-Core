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
  <img src="https://img.shields.io/badge/tests-4952%20passing-brightgreen" alt="4952 tests"/>
  <img src="https://img.shields.io/badge/version-2.0.7-4c8cbf" alt="Version 2.0.7"/>
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
- **Compliance Evidence Chain (sf-cec)** — signed ZIP bundles with regulatory clause maps, DPA generation, and RFC 3161 timestamps for auditor hand-off
- **Observability SDK (sf-observe)** — span export (OTLP/Datadog/Grafana/Splunk/Elastic), W3C TraceContext, OTel GenAI attrs, sampling strategies, annotation store, and health probes
- **CI/CD Gate Pipeline (sf-gate)** — evaluate release quality gates (schema, secrets, performance, PRRI, trust), YAML pipeline engine, artifact store, and blocking trust gate to prevent unsafe releases

</td>
<td width="50%">

### Privacy & Audit Infrastructure- **Secrets scanning** — 20-pattern registry detects API keys, tokens, private keys; SARIF output; pre-commit hook- **PII redaction** — detect and strip sensitive data before it leaves your app
- **HMAC audit chains** — tamper-evident, blockchain-style event signing- **Audit SDK (`sf-audit`)** — `sf_audit.append()`, schema key registry, T.R.U.S.T. scorecard, GDPR Article 30 RoPA, BYOS cloud routing- **GDPR subject erasure** — right-to-erasure with tombstone events that preserve chain integrity
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
- **25 CLI commands** — compliance checks, PII scans, secrets scanning, audit-chain verification, CI/CD gate pipelines, all CI-ready

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
| OTLP export (any OTel backend) | ✅ | ❌ | ✅ | ✅ | ✅ |
| MIT license, no call-home | ✅ | Partial | ✅ | ✅ | ✅ |
| CI/CD release quality gates (schema, secrets, PRRI, trust gate) | ✅ | ❌ | ❌ | ❌ | ❌ |

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
### 5. Package for auditors with sf-cec (v2.0.4+)

Bundle your audit records into a regulator-ready, HMAC-signed ZIP:

```python
from spanforge.sdk import sf_cec

# Build a compliance evidence bundle for Q1 2026
result = sf_cec.build_bundle(
    project_id="my-agent",
    date_range=("2026-01-01", "2026-03-31"),
    frameworks=["eu_ai_act", "iso_42001", "soc2"],
)

print(result.bundle_id)       # sfcec_my-agent_20260401T000000Z_abc123
print(result.zip_path)        # /tmp/sfcec/halluccheck_cec_my-agent_2026-01-01_2026-03-31.zip
print(result.hmac_manifest)   # hmac-sha256:a3f9…
print(result.record_counts)   # {"halluccheck.score.v1": 214, "halluccheck.bias.v1": 87, …}

# Verify bundle integrity before sharing
verify = sf_cec.verify_bundle(result.zip_path)
assert verify.overall_valid

# Generate a GDPR Art. 28 Data Processing Agreement
dpa = sf_cec.generate_dpa(
    project_id="my-agent",
    controller_details={"name": "Acme Corp", "contact": "dpo@acme.com"},
    processor_details={"name": "ML Platform Team"},
)
print(dpa.document_id)  # sfcec-dpa-my-agent-20260401
```

The ZIP bundle contains:
- `manifest.json` — record inventory with HMAC-SHA256 signature
- `clause_map.json` — per-framework clause satisfaction (SATISFIED / PARTIAL / GAP)
- `chain_proof.json` — audit chain verification result
- `attestation.json` — HMAC-signed attestation metadata
- `rfc3161_timestamp.tsr` — trusted timestamp stub (RFC 3161)
- `score_records/`, `bias_reports/`, `prri_records/`, `drift_events/`, `pii_detections/`, `gate_evaluations/` — NDJSON evidence per schema key

### 6. Observe spans with sf-observe (v2.0.5+)

Export spans to any OTLP-compatible backend, emit structured annotations, and
trace LLM calls with OTel GenAI semantic conventions:

```python
from spanforge.sdk import sf_observe

# Emit a span for an LLM call — W3C traceparent + OTel GenAI attrs added automatically
span_id = sf_observe.emit_span(
    "chat.completion",
    {
        "gen_ai.system": "openai",
        "gen_ai.request.model": "gpt-4o",
        "gen_ai.usage.input_tokens": 512,
        "gen_ai.usage.output_tokens": 64,
    },
)
print(span_id)  # "a3f1b2c4d5e6f708"

# Mark a model deployment
annotation_id = sf_observe.add_annotation(
    "model_deployed",
    {"model": "gpt-4o", "environment": "production"},
    project_id="my-agent",
)

# Health probe
print(sf_observe.healthy)         # True
print(sf_observe.last_export_at)  # ISO-8601 or None

# Export to any OTLP endpoint per-call
from spanforge.sdk import ReceiverConfig
result = sf_observe.export_spans(
    my_spans,
    receiver_config=ReceiverConfig(
        endpoint="https://otel.collector.example.com/v1/traces",
        headers={"Authorization": "Bearer tok"},
    ),
)
print(result.exported_count, result.backend)
```

Select backend and sampler via environment:

```bash
export SPANFORGE_OBSERVE_BACKEND=otlp          # otlp | datadog | grafana | splunk | elastic | local
export SPANFORGE_OBSERVE_SAMPLER=trace_id_ratio
export SPANFORGE_OBSERVE_SAMPLE_RATE=0.25
```

---

### 7. Route alerts with sf-alert (v2.0.6+)

Publish topic-based alerts to Slack, PagerDuty, OpsGenie, Teams, SMS, and
custom webhooks — with built-in deduplication, escalation policy, and
maintenance-window suppression:

```python
from spanforge.sdk import sf_alert

# Publish a CRITICAL drift alert
result = sf_alert.publish(
    "halluccheck.drift.red",
    {"model": "gpt-4o", "drift_score": 0.91},
    severity="critical",
    project_id="my-agent",
)
print(result.alert_id)    # UUID4
print(result.suppressed)  # True if deduplicated / maintenance window

# Acknowledge to cancel the 15-minute escalation timer
sf_alert.acknowledge(result.alert_id)

# Register a custom topic
sf_alert.register_topic(
    "myapp.pipeline.failed",
    "ML pipeline execution failure",
    "high",
    runbook_url="https://runbooks.example.com/pipeline",
)
```

Configure sinks via environment variables (zero code required):

```bash
export SPANFORGE_ALERT_TEAMS_WEBHOOK=https://xxx.webhook.office.com/...
export SPANFORGE_ALERT_OPSGENIE_KEY=og-key-...
export SPANFORGE_ALERT_DEDUP_SECONDS=300
```

---

### 8. Enforce release gates with sf-gate (v2.0.7+)

Run YAML-declared quality gates before every release. Block on schema violations,
secrets leaks, performance regressions, unsafe PRRI scores, and trust failures
— all in a single pipeline command:

```python
from spanforge.sdk import sf_gate

# Run a full YAML gate pipeline — blocks on any FAIL gate
result = sf_gate.run_pipeline("gates/ci-pipeline.yaml")
for g in result.gate_results:
    print(f"[{g.verdict.value}] {g.gate_id}")  # e.g. [PASS] schema-validation

# Evaluate a single gate programmatically
verdict = sf_gate.evaluate("schema-validation", event.to_dict())
print(verdict.verdict)   # GateVerdict.PASS

# Standalone PRRI evaluation
prri = sf_gate.evaluate_prri(prri_score=28.5)
print(prri.verdict)      # PRRIVerdict.GREEN

# Composite trust gate — checks HRI rate, PII, and secrets windows
trust = sf_gate.get_status()
print(trust.healthy)     # True if all thresholds are within bounds
```

Or from CI directly:

```bash
# Runs the pipeline, exits 1 if any blocking gate fails
spanforge gate run gates/ci-pipeline.yaml

# Enforce the composite trust gate as a deployment prerequisite
spanforge gate trust-gate --project-id my-agent
```

A minimal `ci-pipeline.yaml`:

```yaml
version: "1.0"
gates:
  - id: schema-validation
    type: schema_validation
    on_fail: block
  - id: secrets-scan
    type: secrets_scan
    on_fail: block
  - id: prri-check
    type: halluccheck_prri
    params:
      red_threshold: 65
    on_fail: block
  - id: trust-gate
    type: halluccheck_trust
    on_fail: block
```

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

25 commands — all CI-pipeline ready:

```bash
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

# Privacy & Secrets
spanforge scan events.jsonl --fail-on-match    # CI-gate PII scan
spanforge secrets scan <file>                  # scan file for secrets (exit 0=clean, 1=found)
spanforge secrets scan <file> --format sarif   # SARIF output for GitHub Code Scanning
spanforge secrets scan <file> --redact         # print redacted version to stdout

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

# CI/CD Gate Pipeline
spanforge gate run gates/ci-pipeline.yaml               # run YAML gate pipeline (exit 1 = blocking gate failed)
spanforge gate run gates/ci-pipeline.yaml --format json  # JSON output for CI dashboards
spanforge gate evaluate schema-validation --payload event.json  # evaluate single gate
spanforge gate trust-gate --project-id my-agent         # composite trust gate check

# Viewer
spanforge serve                                # local SPA trace viewer
spanforge ui                                   # standalone HTML viewer
```

---

## Event namespaces

Every event carries a typed ``payload``. The built-in namespaces:

| Prefix | Dataclass | What it records |
|---|---|---|
| `consent.*` | `ConsentPayload` | User consent grants, revocations, violations |
| `hitl.*` | `HITLPayload` | Human-in-the-loop review, escalation, timeout |
| `model_registry.*` | `ModelRegistryEntry` | Model registration, deprecation, retirement |
| `explanation.*` | `ExplainabilityRecord` | Explainability records for AI decisions |
| `llm.trace.*` | `SpanPayload` | Model calls — tokens, latency, cost **(frozen v2)** |
| `llm.guard.*` | `GuardPayload` | Safety classifier outputs, block decisions |
| `llm.redact.*` | `RedactPayload` | PII audit — what was found and removed |
| `llm.audit.*` | `AuditChainPayload` | Access logs and chain-of-custody |
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
+-- core/
│   +-- compliance_mapping.py  — ComplianceMappingEngine, evidence packages, attestations
+-- compliance/                — Programmatic compliance test suite
+-- signing.py                 — HMAC audit chains, key management, multi-tenant KeyResolver
+-- redact.py                  — PII detection + redaction policies
+-- model_registry.py          — Model lifecycle governance
+-- explain.py                 — Explainability records
+-- consent.py                 — Consent boundary events
+-- hitl.py                    — Human-in-the-loop events
+-- governance.py              — Policy-based event gating
+-- event.py                   — Event envelope
+-- types.py                   — EventType enum (consent.*, hitl.*, model_registry.*, explanation.*, llm.*)
+-- config.py                  — configure() / get_config()
+-- _span.py                   — Span, AgentRun, AgentStep context managers
+-- _trace.py                  — Trace + start_trace()
+-- _tracer.py                 — Top-level tracing entry point
+-- _stream.py                 — Internal dispatch: sample — redact — sign — export
+-- _store.py                  — TraceStore ring buffer
+-- _hooks.py                  — HookRegistry (lifecycle hooks)
+-- _server.py                 — HTTP server (/traces, /compliance/summary)
+-- _cli.py                    ← 25 CLI sub-commands
+-- cost.py                    — CostTracker, BudgetMonitor, @budget_alert
+-- cache.py                   — SemanticCache, @cached decorator
+-- retry.py                   — @retry, FallbackChain, CircuitBreaker
+-- toolsmith.py               — @tool, ToolRegistry
+-- http.py                    — Zero-dependency OpenAI-compatible HTTP client
+-- io.py                      — JSONL read/write/append utilities
+-- plugins.py                 — Entry-point plugin discovery
+-- schema.py                  — Lightweight zero-dependency JSON Schema validator
+-- regression.py              — Pass/fail regression detector
+-- stats.py                   — Percentile, latency summary utilities
+-- presidio_backend.py        — Optional Presidio-powered PII detection
+-- _ansi.py                   — ANSI color helpers (NO_COLOR aware)
+-- lint/                      — AST-based instrumentation linter (AO001–AO005)
+-- export/                    — JSONL, OTLP, Webhook, Datadog, Grafana Loki, Cloud
+-- integrations/              — OpenAI, Anthropic, Gemini, Bedrock, LangChain, LlamaIndex, CrewAI, Ollama, Groq, Together
+-- namespaces/                — Typed payload dataclasses
+-- gate.py                    — GateRunner YAML pipeline engine, 6 gate executors, artifact store (Phase 8)
+-- sdk/                       — Service SDK clients (sf-identity, sf-pii, sf-secrets, sf-audit, sf-cec, sf-observe, sf-alert, sf-gate)
│   +-- identity.py            —   SFIdentityClient – keys, JWT, TOTP, MFA, magic-link
│   +-- pii.py                 —   SFPIIClient – scan, redact, anonymize
│   +-- secrets.py             —   SFSecretsClient – 20-pattern secret scanning, SARIF output
│   +-- audit.py               —   SFAuditClient – HMAC-chained records, T.R.U.S.T. scorecard, Article 30, BYOS
│   +-- cec.py                 —   SFCECClient – signed CEC ZIP bundles, clause mapping, DPA generation (Phase 5)
│   +-- observe.py             —   SFObserveClient – span export, OTel GenAI attrs, W3C TraceContext, sampling (Phase 6)
│   +-- alert.py               —   SFAlertClient – topic-based routing, dedup, escalation policy, 6 sink integrations (Phase 7)
│   +-- gate.py                —   SFGateClient – YAML pipeline runner, evaluate(), evaluate_prri(), trust-gate, artifact management (Phase 8)
│   +-- _base.py               —   SFClientConfig, SFServiceClient, circuit breaker
│   +-- _types.py              —   SecretStr, APIKeyBundle, JWTClaims, BundleResult, ClauseMapEntry, ExportResult, Annotation, AlertSeverity, …
│   +-- _exceptions.py         —   SFError hierarchy
│   +-- __init__.py            —   sf_identity / sf_pii / sf_secrets / sf_audit / sf_cec / sf_observe / sf_alert / sf_gate singletons + configure()
+-- migrate.py                 — Schema migration (v1 — v2), LangSmith migration
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
  <td><code>spanforge.secrets</code></td>
  <td><code>SecretsScanner</code> — 20-pattern registry (7 spec-defined + 13 industry-standard), Shannon entropy scoring, three-tier confidence model, zero-tolerance auto-block for 10 high-risk types, <code>SecretsScanResult</code> with <code>to_dict()</code> and SARIF 2.1.0 output, span deduplication, configurable allowlist</td>
  <td>Security / DevSecOps teams</td>
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
<tr>
  <td><strong>Service SDK (v2.0.3+)</strong></td><td colspan="2"></td>
</tr>
<tr>
  <td><code>spanforge.sdk.identity</code></td>
  <td><code>SFIdentityClient</code> — API key lifecycle (<code>issue_api_key</code>, <code>rotate_api_key</code>, <code>revoke_api_key</code>), session JWT (HS256 stdlib / RS256 remote), magic-link issuance + single-use exchange, TOTP enrolment + verification (RFC 6238, 6-digit, 30 s), backup codes, per-key IP allowlist, sliding-window rate limiting, brute-force lockout. Fully local-mode capable — no external service required.</td>
  <td>Security / platform teams</td>
</tr>
<tr>
  <td><code>spanforge.sdk.pii</code></td>
  <td><code>SFPIIClient</code> — <code>scan_text()</code>, <code>anonymise()</code>, <code>scan_batch()</code>, <code>apply_pipeline_action()</code>, <code>get_status()</code>, <code>erase_subject()</code> (GDPR Art. 17), <code>export_subject_data()</code> (CCPA DSAR), <code>safe_harbor_deidentify()</code> (HIPAA 18-PHI), <code>audit_training_data()</code> (EU AI Act Art. 10), <code>get_pii_stats()</code>. PIPL patterns for Chinese national ID / mobile / bank card. Pipeline action routing (<code>flag</code> / <code>redact</code> / <code>block</code>) with confidence threshold gate. Scan results never include raw PII — only type labels, field paths, and SHA-256 hashes. Runs locally or delegates to a remote sf-pii service.</td>
  <td>Data privacy / GDPR teams</td>
</tr>
<tr>
  <td><code>spanforge.sdk.secrets</code></td>
  <td><code>SFSecretsClient</code> — <code>scan(text)</code> → <code>SecretsScanResult</code>, <code>scan_batch(texts)</code> with asyncio parallel execution. 20-pattern registry covering all spec-required types plus 13 industry-standard additions. Three-tier confidence model (0.75 / 0.90 / 0.97). Zero-tolerance auto-block for 10 high-risk secret types. SARIF 2.1.0 output. Runs fully locally — no external service required.</td>
  <td>Security / DevSecOps teams</td>
</tr>
<tr>
  <td><code>spanforge.sdk.audit</code></td>
  <td><code>SFAuditClient</code> — <code>append(record, schema_key)</code> with HMAC-SHA256 chaining, <code>query()</code> SQLite index with full-text and date-range filters, <code>verify_chain()</code> tamper detection, <code>get_trust_scorecard()</code> T.R.U.S.T. dimensions (hallucination · PII hygiene · secrets hygiene · gate pass-rate · compliance posture), <code>generate_article30_record()</code> GDPR Article 30 RoPA, <code>export()</code> JSONL/CSV/compressed, <code>sign()</code>, <code>get_status()</code>. BYOS routing via <code>SPANFORGE_AUDIT_BYOS_PROVIDER</code> (S3 / Azure / GCS / R2). Strict-schema mode, configurable retention years, optional SQLite persistence. 123 tests, 85 % coverage, mypy strict clean.</td>
  <td>Compliance / security / audit teams</td>
</tr>
<tr>
  <td><code>spanforge.sdk.observe</code></td>
  <td><code>SFObserveClient</code> — <code>emit_span(name, attributes)</code> builds OTel-compliant spans with W3C traceparent / baggage injection and OTel GenAI semantic attributes; <code>export_spans(spans, receiver_config=...)</code> routes to <code>local</code> / <code>otlp</code> / <code>datadog</code> / <code>grafana</code> / <code>splunk</code> / <code>elastic</code>; <code>add_annotation(event_type, payload)</code> / <code>get_annotations(event_type, from_dt, to_dt)</code> annotation store; <code>get_status()</code>, <code>healthy</code>, <code>last_export_at</code> health probes. Sampling via <code>SPANFORGE_OBSERVE_SAMPLER</code> (<code>always_on</code> / <code>always_off</code> / <code>parent_based</code> / <code>trace_id_ratio</code>). 139 tests, 97% coverage, mypy strict + bandit clean. <em>(Phase 6, v2.0.5+)</em></td>
  <td>Platform / MLOps / observability teams</td>
</tr>
<tr>
  <td><code>spanforge.sdk.alert</code></td>
  <td><code>SFAlertClient</code> — <code>publish(topic, payload, *, severity, project_id) → PublishResult</code> routes to all configured sinks with deduplication, rate-limiting, alert grouping, and maintenance-window suppression; <code>acknowledge(alert_id)</code> cancels CRITICAL escalation; <code>register_topic()</code> custom topic registry; <code>set_maintenance_window()</code> / <code>remove_maintenance_windows()</code>; <code>get_alert_history()</code> with filtering; <code>get_status()</code> / <code>healthy</code> health probes. Built-in sinks: <code>WebhookAlerter</code> (HMAC), <code>OpsGenieAlerter</code>, <code>VictorOpsAlerter</code>, <code>IncidentIOAlerter</code>, <code>SMSAlerter</code> (Twilio), <code>TeamsAdaptiveCardAlerter</code>. Auto-discovery from <code>SPANFORGE_ALERT_*</code> env vars. Per-sink circuit breakers. 95 tests, mypy strict + bandit clean. <em>(Phase 7, v2.0.6+)</em></td>
  <td>Platform / SRE / on-call teams</td>
</tr>
<tr>
  <td><code>spanforge.sdk.gate</code></td>
  <td><code>SFGateClient</code> — <code>evaluate(gate_id, payload) → GateEvaluationResult</code>, <code>evaluate_prri(prri_score) → PRRIResult</code>, <code>run_pipeline(gate_config_path) → GateRunResult</code>, <code>get_artifact(gate_id)</code>, <code>list_artifacts()</code>, <code>purge_artifacts(older_than_days)</code>, <code>get_status() → GateStatusInfo</code>, <code>configure(config)</code>. Six built-in gate executors: <code>schema_validation</code>, <code>dependency_security</code>, <code>secrets_scan</code>, <code>performance_regression</code>, <code>halluccheck_prri</code>, <code>halluccheck_trust</code>. PRRI three-tier verdict (<code>GREEN</code>/<code>AMBER</code>/<code>RED</code>), <code>GateArtifact</code> store with configurable retention, composite trust gate (HRI rate + PII window + secrets window), five exception types. 174 tests, mypy strict + bandit clean. <em>(Phase 8, v2.0.7+)</em></td>
  <td>DevOps / CI / platform teams</td>
</tr>
  <td><code>SFCECClient</code> — <code>build_bundle(project_id, date_range, frameworks)</code> assembles a signed ZIP with <code>manifest.json</code>, <code>clause_map.json</code>, <code>chain_proof.json</code>, <code>attestation.json</code>, <code>rfc3161_timestamp.tsr</code>, and 6 NDJSON evidence directories. HMAC-SHA256 manifest signing, BYOS detection. <code>verify_bundle(zip_path)</code> re-verifies HMAC + chain + timestamp. <code>generate_dpa(project_id, controller_details, processor_details)</code> produces a GDPR Article 28 Data Processing Agreement. <code>get_status()</code> returns bundle count, BYOS provider, and last bundle timestamp. Supports all 5 frameworks: <code>eu_ai_act</code>, <code>iso_42001</code>, <code>nist_ai_rmf</code>, <code>iso27001</code>, <code>soc2</code>. 148 tests, 87% coverage, mypy strict + bandit clean. <em>(Phase 5, v2.0.4+)</em></td>
  <td>Compliance / legal / audit teams</td>
</tr>
<tr>
  <td><code>spanforge.sdk</code></td>
  <td>Pre-built <code>sf_identity</code>, <code>sf_pii</code>, <code>sf_secrets</code>, <code>sf_audit</code>, <code>sf_cec</code>, <code>sf_observe</code>, <code>sf_alert</code>, and <code>sf_gate</code> singletons loaded from env vars on first import. <code>SFClientConfig</code>, <code>SecretStr</code>, full exception hierarchy (<code>SFAuthError</code>, <code>SFBruteForceLockedError</code>, <code>SFPIINotRedactedError</code>, <code>SFPIIBlockedError</code>, <code>SFPIIDPDPConsentMissingError</code>, <code>SFSecretsBlockedError</code>, <code>SFAuditSchemaError</code>, <code>SFAuditChainError</code>, <code>SFAuditRetentionError</code>, <code>SFCECError</code>, <code>SFCECBuildError</code>, <code>SFCECVerifyError</code>, <code>SFCECExportError</code>, <code>SFObserveError</code>, <code>SFObserveExportError</code>, <code>SFObserveEmitError</code>, <code>SFObserveAnnotationError</code>, <code>SFAlertError</code>, <code>SFAlertPublishError</code>, <code>SFAlertRateLimitedError</code>, <code>SFAlertQueueFullError</code>, <code>SFGateError</code>, <code>SFGateEvaluationError</code>, <code>SFGatePipelineError</code>, <code>SFGateTrustFailedError</code>, <code>SFGateSchemaError</code>, …), and all value-object types exported from the top-level package.</td>
  <td>All teams</td>
</tr>
</tbody>
</table>

---

## Quality

- **4 952 tests** passing (12 skipped) — unit, integration, property-based (Hypothesis), performance benchmarks
- **≥ 92% line and branch coverage** — 90% minimum enforced in CI
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
pytest                      # 4 952 tests
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

Contributions welcome — see the [Contributing Guide](docs/contributing.md). All new code must maintain ≥ 90% coverage. Run `ruff` and `mypy` before submitting.

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
  <a href="docs/index.md">Docs</a> —
  <a href="docs/quickstart.md">Quickstart</a> —
  <a href="docs/api/index.md">API Reference</a> —
  <a href="https://github.com/veerarag1973/spanforge/discussions">Discussions</a> —
  <a href="https://github.com/veerarag1973/spanforge/issues">Report a bug</a>
</p>