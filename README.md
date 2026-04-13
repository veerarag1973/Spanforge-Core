<h1 align="center">spanforge</h1>

<p align="center">
  <strong>The reference implementation of the spanforge Standard.</strong><br/>
  A lightweight Python SDK that gives your AI applications a common, structured way to record, sign, redact, and export events — with zero mandatory dependencies.
</p>

<p align="center">
  <em>spanforge (RFC-0001) is the open event-schema standard for compliance and governance of agentic AI systems.</em>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9%2B-4c8cbf?logo=python&logoColor=white" alt="Python 3.9+"/>
  <a href="https://pypi.org/project/spanforge/"><img src="https://img.shields.io/pypi/v/spanforge?color=4c8cbf&logo=pypi&logoColor=white" alt="PyPI"/></a>
  <a href="https://www.getspanforge.com/standard"><img src="https://img.shields.io/badge/standard-SpanForge_RFC--0001-4c8cbf" alt="spanforge RFC-0001"/></a>
  <img src="https://img.shields.io/badge/coverage-92%25-brightgreen" alt="92% test coverage"/>
  <img src="https://img.shields.io/badge/tests-3162%20passing-brightgreen" alt="3162 tests"/>
  <img src="https://img.shields.io/badge/version-1.0.0-4c8cbf" alt="Version 1.0.0"/>
  <img src="https://img.shields.io/badge/dependencies-zero-brightgreen" alt="Zero dependencies"/>
  <a href="docs/index.md"><img src="https://img.shields.io/badge/docs-local-4c8cbf" alt="Documentation"/></a>
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"/>
</p>

---

## What is this?

**spanforge** (``spanforge``) is the **reference implementation of [RFC-0001 spanforge](https://www.getspanforge.com/standard)** — the open event-schema standard for compliance and governance of agentic AI systems.

spanforge defines a structured, typed event envelope that every LLM-adjacent instrumentation tool can emit and every compliance backend can consume. It covers the full lifecycle: event envelopes, agent span hierarchies, token and cost models, HMAC audit chains, PII redaction, OTLP-compatible export, and schema governance.

> Think of **spanforge** as a **universal receipt format** for your AI application.
> Every time your app calls a language model, makes a decision, redacts private data, or checks a guardrail — this library gives that action a consistent, structured record that any tool in your stack can read.

---

## Why use it?

Without a shared schema, every team invents their own log format. With ``spanforge`` (and the spanforge standard it implements), your logs, dashboards, compliance reports, and monitoring tools all speak the same language — automatically.

| Without spanforge | With spanforge |
|---|---|
| Each service logs events differently | Every event follows the same structure |
| Hard to audit who saw what data | Built-in HMAC signing creates a tamper-proof audit trail |
| PII scattered across logs | First-class PII redaction before data leaves your app |
| Vendor-specific telemetry | OpenTelemetry-compatible — works with any monitoring stack |
| No way to check compatibility | CLI + programmatic compliance checks in CI |
| Complex integration glue | Zero required dependencies — just ``pip install`` |

---

## How spanforge compares

spanforge is the only **open-schema, zero-dependency** AI compliance platform. Everything else either requires a hosted backend, imposes a proprietary event format, or has mandatory heavy dependencies.

| Feature | **spanforge** | LangSmith | Langfuse | OpenLLMetry | Arize Phoenix |
|---|:---:|:---:|:---:|:---:|:---:|
| Open schema standard (RFC-driven) | ✅ | ❌ | ❌ | Partial | ❌ |
| Zero required dependencies | ✅ | ❌ | ❌ | ❌ | ❌ |
| Works fully offline / air-gapped | ✅ | ❌ | Self-host only | Partial | Self-host only |
| HMAC tamper-proof audit chain | ✅ | ❌ | ❌ | ❌ | ❌ |
| First-class PII redaction (built-in) | ✅ | ❌ | ❌ | ❌ | ❌ |
| OTLP export (any OTel backend) | ✅ | ❌ | ❌ | ✅ | ✅ |
| MIT license (self-hosted, no call-home) | ✅ | Partial | ✅ | ✅ | ✅ |
| Python 3.9+ (no Pydantic required) | ✅ | ❌ | ❌ | ❌ | ❌ |
| CLI-first compliance checks | ✅ | ❌ | ❌ | ❌ | ❌ |
| Schema versioning & migration tools | ✅ | ❌ | ❌ | ❌ | ❌ |

> **Bottom line**: Use spanforge when you need a *standard* rather than a *service* — especially in regulated, offline, or multi-vendor environments.

---

## Install

```bash
pip install spanforge
```

```python
import spanforge  # distribution name is spanforge, import name is spanforge
```

**Requires Python 3.9 or later.** No other packages are required for core usage.

> **Note:** The PyPI distribution is named `spanforge`. The Python import name remains `spanforge`.

### Optional extras

```bash
pip install "spanforge[jsonschema]"   # strict JSON Schema validation
pip install "spanforge[openai]"       # OpenAI auto-instrumentation (patch/unpatch)
pip install "spanforge[http]"         # Webhook + OTLP export
pip install "spanforge[pydantic]"     # Pydantic v2 model layer
pip install "spanforge[otel]"         # OpenTelemetry SDK integration
pip install "spanforge[kafka]"        # EventStream.from_kafka() via kafka-python
pip install "spanforge[langchain]"    # LangChain callback handler
pip install "spanforge[llamaindex]"   # LlamaIndex event handler
pip install "spanforge[crewai]"       # CrewAI callback handler
pip install "spanforge[datadog]"      # Datadog APM + metrics exporter
pip install "spanforge[all]"          # everything above
```

---

## Using SpanForge alongside OpenTelemetry

SpanForge does not replace your OTel setup. It adds the compliance layer OTel cannot provide — tamper-proof audit chains, PII redaction, and regulator-ready attestation reports.

```python
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

# 1. Set up your existing OTel pipeline as normal
provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

# 2. Add SpanForge's compliance layer in one line
import spanforge
spanforge.configure(mode="otel_passthrough")

# 3. Use SpanForge spans — OTel + HMAC audit chain + PII redaction all active
with spanforge.Tracer().span("retrieve_docs") as s:
    s.set_attribute("user_query", "What is our refund policy?")
```

For dual-stream export (OTel bridge + local audit log):

```python
spanforge.configure(exporters=["otel_passthrough", "jsonl"], endpoint="audit.jsonl")
```

---

## Five-minute tour

### 1 — Trace an LLM call with the span API

```python
import spanforge

spanforge.configure(exporter="console", service_name="my-agent")

with spanforge.span("call-llm") as span:
    span.set_model(model="gpt-4o", system="openai")
    result = call_llm(prompt)                          # your LLM call here
    span.set_token_usage(input=512, output=128, total=640)
    span.set_status("ok")
```

The context manager automatically records start/end times, parent-child span relationships, and emits a structured event when it exits.

---

### 1c — Use the high-level `Trace` API (new in 2.0)

```python
import spanforge

spanforge.configure(exporter="console", service_name="my-agent")

with spanforge.start_trace("research-agent") as trace:
    with trace.llm_call("gpt-4o", temperature=0.7) as span:
        result = call_llm(prompt)
        span.set_token_usage(input=512, output=200, total=712)
        span.set_status("ok")
        span.add_event("tool_selected", {"name": "web_search"})

    with trace.tool_call("web_search") as span:
        output = run_search(query)
        span.set_status("ok")

# Inspect the trace in the terminal
trace.print_tree()
# ─ Agent Run: research-agent  [1.2s]
#  ├─ LLM Call: gpt-4o  [0.8s]  in=512 out=200 tokens  $0.0034
#  └─ Tool Call: web_search  [0.4s]  ok

print(trace.summary())
# {'trace_id': '...', 'agent_name': 'research-agent', 'span_count': 3, ...}
```

The `Trace` object works with `async with` too:

```python
async with spanforge.start_trace("async-agent") as trace:
    async with trace.llm_call("gpt-4o") as span:
        response = await async_call_llm(prompt)
        span.set_status("ok")
```

---

### 1b — Auto-instrument the OpenAI client (zero boilerplate)

```python
from spanforge.integrations import openai as openai_integration
import openai, spanforge

# One-time setup: patch the OpenAI SDK
openai_integration.patch()

spanforge.configure(exporter="console", service_name="my-agent")

client = openai.OpenAI()

with spanforge.tracer.span("chat-gpt4o") as span:
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": "Hello"}],
    )
    # span.token_usage, span.cost, and span.model are now populated automatically
```

`patch()` wraps every `client.chat.completions.create()` call (sync and async)
so that `token_usage`, `cost`, and `model` are auto-populated on the active span
from the API response — no per-call boilerplate required.

```python
# Restore original behaviour when you're done
openai_integration.unpatch()
```

---

### 2 — Record a raw event

```python
from spanforge import Event, EventType, Tags

event = Event(
    event_type=EventType.TRACE_SPAN_COMPLETED,
    source="my-app@1.0.0",          # who emitted this
    org_id="org_acme",              # your organisation
    payload={
        "model": "gpt-4o",
        "prompt_tokens": 512,
        "completion_tokens": 128,
        "latency_ms": 340.5,
    },
    tags=Tags(env="production"),
)

event.validate()         # raises if structure is invalid
print(event.to_json())   # compact JSON string, ready to store or ship
```

Every event gets a **ULID** (a time-sortable unique ID) automatically — no need to generate one yourself.

---

### 3 — Redact private information before logging

```python
from spanforge import Event, EventType
from spanforge.redact import Redactable, RedactionPolicy, Sensitivity

policy = RedactionPolicy(min_sensitivity=Sensitivity.PII, redacted_by="policy:gdpr-v1")

# Wrap any string that might contain PII
event = Event(
    event_type=EventType.TRACE_SPAN_COMPLETED,
    source="my-app@1.0.0",
    payload={"prompt": Redactable("Call me at 555-867-5309", Sensitivity.PII)},
)
result = policy.apply(event)
# result.event.payload["prompt"] -> "[REDACTED by policy:gdpr-v1]"
```

``Redactable`` is a string wrapper. You mark fields as sensitive at the point where they are created; the policy decides what to remove before the event is written to any log.

> **Tip — auto-redact every span:** pass `redaction_policy=policy` to
> `spanforge.configure()` and the policy runs automatically inside `_dispatch()`
> before any exporter sees the event.

---

### 4 — Sign events for tamper-proof audit trails

```python
from spanforge.signing import sign, verify_chain, AuditStream

# Sign a single event
signed = sign(event, org_secret="my-org-secret")

# Or build a chain — every event references the one before it,
# so any gap or modification is immediately detectable.
stream = AuditStream(org_secret="my-org-secret")
for e in events:
    stream.append(e)

result = verify_chain(stream.events, org_secret="my-org-secret")
```

This is the same principle used in certificate chains and blockchain — each event's signature covers the previous event's signature, so you cannot alter history without breaking the chain.
> **Tip — auto-sign every span:** pass `signing_key="your-secret"` to
> `spanforge.configure()` and every emitted span is signed and chained
> automatically, with no per-event boilerplate.
---

### 5 — Export to anywhere

```python
from spanforge.stream import EventStream
from spanforge.export.jsonl import JSONLExporter
from spanforge.export.webhook import WebhookExporter
from spanforge.export.otlp import OTLPExporter
from spanforge.export.datadog import DatadogExporter
from spanforge.export.grafana import GrafanaLokiExporter
from spanforge.export.cloud import CloudExporter

stream = EventStream(events)

# Write everything to a local file
await stream.drain(JSONLExporter("events.jsonl"))

# Ship to your OpenTelemetry collector
await stream.drain(OTLPExporter("http://otel-collector:4318/v1/traces"))

# Send to Datadog APM (traces + metrics)
await stream.drain(DatadogExporter(
    service="my-app",
    env="production",
    agent_url="http://dd-agent:8126",
    api_key="your-dd-api-key",
))

# Push to Grafana Loki
await stream.drain(GrafanaLokiExporter(
    url="http://loki:3100",
    labels={"app": "my-app", "env": "production"},
))

# Send to spanforge Cloud
await stream.drain(CloudExporter(
    api_key="sf_live_xxx",
    endpoint="https://ingest.getspanforge.com/v1/events",
))

# Fan-out: guard-blocked events -> Slack webhook
await stream.route(
    WebhookExporter("https://hooks.slack.com/your-webhook"),
  predicate=lambda e: e.event_type == "llm.guard.output.blocked",
)
```

#### Kafka source

```python
from spanforge.stream import EventStream

# Drain a Kafka topic directly into an EventStream
stream = EventStream.from_kafka(
    topic="llm-events",
    bootstrap_servers="kafka:9092",
    group_id="analytics",
    max_messages=5000,
)
await stream.drain(exporter)
```

---

### 6 — Sync exporters for non-async workflows

```python
from spanforge.exporters.jsonl import SyncJSONLExporter
from spanforge.exporters.console import SyncConsoleExporter

# Log all events to a JSONL file synchronously
exporter = SyncJSONLExporter("events.jsonl")
exporter.export(event)
exporter.close()

# Pretty-print events to the terminal during development
console = SyncConsoleExporter()
console.export(event)
```

---

### 7b — Register lifecycle hooks (new in 2.0)

```python
import spanforge

@spanforge.hooks.on_llm_call
def log_llm(span):
    print(f"LLM called: {span.model}  temp={span.temperature}")

@spanforge.hooks.on_tool_call
def log_tool(span):
    print(f"Tool called: {span.name}")

# Hooks fire automatically for every span of the matching type
```

---

### 7c — Aggregate metrics from a trace file (new in 2.0)

```python
import spanforge
from spanforge.stream import EventStream

events = list(EventStream.from_file("events.jsonl"))
summary = spanforge.metrics.aggregate(events)

print(f"Traces:  {summary.trace_count}")
print(f"Success: {summary.agent_success_rate:.0%}")
print(f"p95 LLM: {summary.llm_latency_ms.p95:.0f} ms")
print(f"Cost:    ${summary.total_cost_usd:.4f}")
```

---

### 7d — Visualize a Gantt timeline (new in 2.0)

```python
from spanforge.debug import visualize

html = visualize(trace.spans, path="trace.html")
# Opens trace.html in a browser — self-contained, no external deps
```

---

### 8a — Semantic cache — skip redundant LLM calls

```python
from spanforge.cache import SemanticCache, InMemoryBackend

cache = SemanticCache(
    backend=InMemoryBackend(max_size=1024),
    similarity_threshold=0.92,   # cosine similarity cutoff
    ttl_seconds=3600,
    namespace="responses",
    emit_events=True,            # emits llm.cache.hit/miss/written events
)

# Or use the @cached decorator on any async function
from spanforge.cache import cached

@cached(threshold=0.92, ttl=3600, emit_events=True)
async def call_llm(prompt: str) -> str:
    # ... real LLM call only on cache miss
    return response

reply = await call_llm("Summarise the spanforge RFC in one sentence.")
# Second call with a semantically identical prompt → instant cache hit, zero tokens spent
reply2 = await call_llm("Give me a one-sentence summary of the spanforge RFC.")
```

---

### 8b — Lint your instrumentation in CI

```python
from spanforge.lint import run_checks

source = open("myapp/pipeline.py").read()
errors = run_checks(source, filename="myapp/pipeline.py")

for err in errors:
    print(f"{err.filename}:{err.line}:{err.col}: {err.code} {err.message}")
# myapp/pipeline.py:42:12: AO002 actor_id receives a bare str; wrap with Redactable()
```

Or run the CLI against a whole directory:

```bash
python -m spanforge.lint myapp/
# AO001  Event() missing required field 'payload'     myapp/pipeline.py:17
# AO004  LLM call outside tracer span context         myapp/pipeline.py:53
# 2 errors in 1 file.

# Plug into flake8 / ruff automatically (entry-point registered in pyproject.toml):
flake8 myapp/
```

---

### 9 — Check compliance and inspect events from the command line

```bash
spanforge check                           # end-to-end health check (config → export → trace store)
spanforge check-compat events.json        # v2.0 compatibility checklist
spanforge validate events.jsonl           # JSON Schema validation per event
spanforge audit-chain events.jsonl        # verify HMAC signing chain integrity
spanforge audit check-health events.jsonl # PII scan + chain + egress health check
spanforge audit rotate-key events.jsonl   # rotate signing key & re-sign chain
spanforge audit erase events.jsonl --subject-id user123  # GDPR subject erasure
spanforge audit verify --input events.jsonl              # verify chain integrity
spanforge scan events.jsonl --fail-on-match              # CI-gate PII scan
spanforge migrate events.jsonl --sign                    # v1→v2 schema migration
spanforge inspect <EVENT_ID> events.jsonl # pretty-print a single event
spanforge stats events.jsonl              # summary: counts, tokens, cost, timestamps
spanforge list-deprecated                 # list all deprecated event types
spanforge migration-roadmap [--json]      # v2 migration roadmap
spanforge check-consumers                 # consumer registry compatibility check
```

```
CHK-1  All required fields present          (500 / 500 events)
CHK-2  Event types valid                    (500 / 500 events)
CHK-3  Source identifiers well-formed       (500 / 500 events)
CHK-5  Event IDs are valid ULIDs            (500 / 500 events)
All checks passed.
```

Drop any of these into your CI pipeline to catch schema drift, signing failures, or schema-breaking migrations before they reach production.

---

### 10 — SPA Trace Viewer

Browse traces in a local single-page application — no external dependencies:

```bash
# Start the HTTP trace viewer server (default port 8888)
spanforge serve

# Or open the standalone HTML viewer in your default browser
spanforge ui
```

`spanforge serve` starts a lightweight HTTP server that exposes a `/traces`
JSON API backed by the in-memory `TraceStore`. The SPA renders agent runs,
LLM calls, tool calls, and timing data in a searchable table.

`spanforge ui` generates a self-contained HTML file from a JSONL export
and opens it directly — useful for sharing trace snapshots offline.

---

## What is inside the box

<table>
<thead>
<tr><th>Module</th><th>What it does</th><th>For whom</th></tr>
</thead>
<tbody>
<tr>
  <td><code>spanforge.event</code></td>
  <td>The core <code>Event</code> envelope — the one structure all tools share</td>
  <td>Everyone</td>
</tr>
<tr>
  <td><code>spanforge.types</code></td>
  <td>All built-in event type strings (trace, cost, cache, eval, guard…)</td>
  <td>Everyone</td>
</tr>
<tr>
  <td><code>spanforge.config</code></td>
  <td><code>configure()</code> and <code>get_config()</code> — global SDK configuration</td>
  <td>Everyone</td>
</tr>
<tr>
  <td><code>spanforge._span</code></td>
  <td>Span, AgentRun, AgentStep context managers — the runtime tracing API. Uses <code>contextvars</code> for safe async/thread context propagation. Supports <code>async with</code>, <code>span.add_event()</code>, <code>span.set_timeout_deadline()</code></td>
  <td>App developers</td>
</tr>
<tr>
  <td><code>spanforge._trace</code></td>
  <td><code>Trace</code> object and <code>start_trace()</code> — high-level, imperative tracing entry point; accumulates all child spans</td>
  <td>App developers</td>
</tr>
<tr>
  <td><code>spanforge.debug</code></td>
  <td><code>print_tree()</code>, <code>summary()</code>, <code>visualize()</code> — terminal tree, stats dict, and self-contained HTML Gantt timeline</td>
  <td>App developers</td>
</tr>
<tr>
  <td><code>spanforge.metrics</code></td>
  <td><code>aggregate()</code> and <code>MetricsSummary</code> — compute success rates, latency percentiles, token totals, and cost breakdowns from any <code>Iterable[Event]</code></td>
  <td>Data / analytics engineers</td>
</tr>
<tr>
  <td><code>spanforge._store</code></td>
  <td><code>TraceStore</code> — in-memory ring buffer; <code>get_trace()</code>, <code>list_tool_calls()</code>, <code>list_llm_calls()</code></td>
  <td>Platform / tooling engineers</td>
</tr>
<tr>
  <td><code>spanforge._hooks</code></td>
  <td><code>HookRegistry</code> / <code>hooks</code> — global span lifecycle hooks: <code>@hooks.on_llm_call</code>, <code>@hooks.on_tool_call</code>, <code>@hooks.on_agent_start</code>, <code>@hooks.on_agent_end</code>. Async variants: <code>@hooks.on_llm_call_async</code>, <code>@hooks.on_tool_call_async</code>, <code>@hooks.on_agent_start_async</code>, <code>@hooks.on_agent_end_async</code> — fired via <code>asyncio.ensure_future()</code>.</td>
  <td>App developers / platform</td>
</tr>
<tr>
  <td><code>spanforge._cli</code></td>
  <td>CLI sub-commands: <code>check</code>, <code>check-compat</code>, <code>validate</code>, <code>audit-chain</code>, <code>audit</code> (<code>erase</code>, <code>rotate-key</code>, <code>check-health</code>, <code>verify</code>), <code>scan</code>, <code>migrate</code>, <code>inspect</code>, <code>stats</code>, <code>list-deprecated</code>, <code>migration-roadmap</code>, <code>check-consumers</code>, <code>compliance</code>, <code>cost</code>, <code>dev</code>, <code>module</code>, <code>serve</code>, <code>init</code>, <code>quickstart</code>, <code>report</code>, <code>ui</code></td>
  <td>DevOps / CI teams</td>
</tr>
<tr>
  <td><code>spanforge.redact</code></td>
  <td>PII detection, sensitivity levels, redaction policies, deep <code>scan_payload()</code> with Luhn validation, and <code>contains_pii()</code> / <code>assert_redacted()</code> with raw string scanning</td>
  <td>Data privacy / GDPR teams</td>
</tr>
<tr>
  <td><code>spanforge.signing</code></td>
  <td>HMAC-SHA256 event signing, tamper-evident audit chains, key strength validation, key expiry checks, environment-isolated key derivation, multi-tenant <code>KeyResolver</code> protocol, and <code>AsyncAuditStream</code></td>
  <td>Security / compliance teams</td>
</tr>
<tr>
  <td><code>spanforge.compliance</code></td>
  <td>Programmatic v2.0 compatibility checks — no pytest required. <code>ComplianceMappingEngine</code> maps telemetry to regulatory frameworks (EU AI Act, ISO 42001, NIST AI RMF, GDPR, SOC 2) and generates evidence packages with HMAC-signed attestations</td>
  <td>Platform / DevOps / Compliance teams</td>
</tr>
<tr>
  <td><code>spanforge.export</code></td>
  <td>Ship events to files (JSONL), HTTP webhooks, OTLP collectors, Datadog APM, Grafana Loki, or spanforge Cloud</td>
  <td>Infra / compliance teams</td>
</tr>
<tr>
  <td><code>spanforge.exporters</code></td>
  <td>Sync exporters — <code>SyncJSONLExporter</code> and <code>SyncConsoleExporter</code> for non-async code</td>
  <td>App developers</td>
</tr>
<tr>
  <td><code>spanforge.stream</code></td>
  <td>Fan-out router — one <code>drain()</code> call reaches multiple backends; Kafka source via <code>from_kafka()</code></td>
  <td>Platform engineers</td>
</tr>
<tr>
  <td><code>spanforge.validate</code></td>
  <td>JSON Schema validation against the published v2.0 schema</td>
  <td>All teams</td>
</tr>
<tr>
  <td><code>spanforge.consumer</code></td>
  <td>Declare schema-namespace dependencies; fail fast at startup if version requirements are not met</td>
  <td>Platform / integration teams</td>
</tr>
<tr>
  <td><code>spanforge.governance</code></td>
  <td>Policy-based event gating — block prohibited types, warn on deprecated usage, enforce custom rules</td>
  <td>Platform / compliance teams</td>
</tr>
<tr>
  <td><code>spanforge.deprecations</code></td>
  <td>Register and surface per-event-type deprecation notices at runtime</td>
  <td>Library maintainers</td>
</tr>
<tr>
  <td><code>spanforge.testing</code></td>
  <td>Test utilities: <code>MockExporter</code>, <code>capture_events()</code> context manager, <code>assert_event_schema_valid()</code>, and <code>trace_store()</code> isolated store context manager. Write unit tests for your AI pipeline without real exporters.</td>
  <td>App developers / test authors</td>
</tr>
<tr>
  <td><code>spanforge.auto</code></td>
  <td>Integration auto-discovery: <code>spanforge.auto.setup()</code> auto-patches every installed LLM integration (OpenAI, Anthropic, Ollama, Groq, Together AI). <code>setup()</code> must be called explicitly; <code>spanforge.auto.teardown()</code> cleanly unpatches all.</td>
  <td>App developers</td>
</tr>
<tr>
  <td><code>spanforge.integrations</code></td>
  <td>Plug-in adapters for OpenAI (auto-instrumentation via <code>patch()</code>), LangChain, LlamaIndex, Anthropic, Groq, Ollama, Together, and <strong>CrewAI</strong> (<code>SpanForgeCrewAIHandler</code> + <code>patch()</code>). <code>spanforge.integrations._pricing</code> ships a static USD/1M-token pricing table for all current OpenAI models.</td>
  <td>App developers</td>
</tr>
<tr>
  <td><code>spanforge.namespaces</code></td>
  <td>Typed payload dataclasses for all 10 built-in event namespaces</td>
  <td>Tool authors</td>
</tr>
<tr>
  <td><code>spanforge.models</code></td>
  <td>Optional Pydantic v2 models for teams that prefer validated schemas</td>
  <td>API / backend teams</td>
</tr>
<tr>
  <td><code>spanforge.trace</code></td>
  <td><code>@trace()</code> decorator — wraps sync/async functions, auto-emits span start/end events with timing and error capture. <code>spanforge.export.otlp_bridge</code> converts spans to OTLP proto dicts.</td>
  <td>App developers</td>
</tr>
<tr>
  <td><code>spanforge.cost</code></td>
  <td><code>CostTracker</code>, <code>BudgetMonitor</code>, <code>@budget_alert</code>, <code>emit_cost_event()</code>, <code>cost_summary()</code> — track and alert on token spend across a session</td>
  <td>App developers / FinOps</td>
</tr>
<tr>
  <td><code>spanforge.inspect</code></td>
  <td><code>InspectorSession</code> context manager + <code>inspect_trace()</code> — intercept and record tool call arguments, results, latency, and errors within a trace</td>
  <td>Platform / debugging</td>
</tr>
<tr>
  <td><code>spanforge.toolsmith</code></td>
  <td><code>@tool</code> decorator + <code>ToolRegistry</code> — register functions as typed tools; <code>build_openai_schema()</code> / <code>build_anthropic_schema()</code> render JSON schemas for function-calling APIs</td>
  <td>App developers</td>
</tr>
<tr>
  <td><code>spanforge.retry</code></td>
  <td><code>@retry</code> with exponential back-off, <code>FallbackChain</code>, <code>CircuitBreaker</code>, <code>CostAwareRouter</code> — resilient LLM provider routing with compliance events at each step</td>
  <td>App developers / SREs</td>
</tr>
<tr>
  <td><code>spanforge.cache</code></td>
  <td><code>SemanticCache</code> + <code>@cached</code> decorator — deduplicate LLM calls via cosine-similarity matching; pluggable backends: <code>InMemoryBackend</code>, <code>SQLiteBackend</code>, <code>RedisBackend</code>; emits <code>llm.cache.*</code> events</td>
  <td>App developers / FinOps</td>
</tr>
<tr>
  <td><code>spanforge.lint</code></td>
  <td><code>run_checks(source, filename)</code> — AST-based instrumentation linter; five AO-codes (AO001–AO005); flake8 plugin; <code>python -m spanforge.lint</code> CLI</td>
  <td>All teams / CI pipelines</td>
</tr>
</tbody>
</table>

---

## Event namespaces

Every event carries a ``payload`` — a dictionary whose shape is defined by the event's **namespace**. The ten built-in namespaces cover everything from raw model traces to safety guardrails:

| Namespace prefix | Dataclass | What it records |
|---|---|---|
| ``llm.trace.*`` | ``SpanPayload``, ``AgentRunPayload``, ``AgentStepPayload`` | Model call — tokens, latency, finish reason **(frozen v2)** |
| ``llm.cost.*`` | ``CostPayload`` | Per-call cost in USD |
| ``llm.cache.*`` | ``CachePayload`` | Cache hit/miss, backend, TTL |
| ``llm.eval.*`` | ``EvalScenarioPayload`` | Scores, labels, evaluator identity |
| ``llm.guard.*`` | ``GuardPayload`` | Safety classifier output, block decisions |
| ``llm.fence.*`` | ``FencePayload`` | Topic constraints, allow/block lists |
| ``llm.prompt.*`` | ``PromptPayload`` | Prompt template version, rendered text |
| ``llm.redact.*`` | ``RedactPayload`` | PII audit record — what was found and removed |
| ``llm.diff.*`` | ``DiffPayload`` | Prompt/response delta between two events |
| ``llm.template.*`` | ``TemplatePayload`` | Template registry metadata |

```python
from spanforge.namespaces.trace import SpanPayload
from spanforge import Event

payload = SpanPayload(
    span_name="call-llm",
    span_id="abc123",
    trace_id="def456",
    start_time_ns=1_000_000_000,
    end_time_ns=1_340_000_000,
    status="ok",
)

event = Event(
    event_type="llm.trace.span.completed",
    source="my-app@1.0.0",
    payload=payload.to_dict(),
)
```

---

## Quality standards

- **3 032 tests** (2 990 passing, 42 skipped) — unit, integration, property-based (Hypothesis), and performance benchmarks
- **≥ 92.84 % line and branch coverage** — measured with ``pytest-cov``; 90 % minimum enforced in CI
- **Zero required dependencies** — the entire core runs on Python's standard library alone
- **Typed** — full ``py.typed`` marker; works with mypy and pyright out of the box
- **Frozen v2 trace schema** — ``llm.trace.*`` payload fields will never break between minor releases
- **async-safe context propagation** — `contextvars`-based span stacks work correctly across `asyncio` tasks, thread pools, and executors
- **Version 1.0.7** adds: `@trace()` decorator, OTLP bridge, `CostTracker` / `BudgetMonitor`, `InspectorSession`, `ToolRegistry` / `@tool`, `@retry` / `FallbackChain` / `CircuitBreaker`, `SemanticCache` / `@cached`, and `spanforge.lint` (AO001–AO005, flake8 plugin, CLI)
- **Version 2.0.0** adds: `Trace` / `start_trace()`, `async with`, `span.add_event()`, `print_tree()` / `summary()` / `visualize()`, sampling controls, `metrics.aggregate()`, `TraceStore`, `HookRegistry`, CrewAI integration
- **Version 1.0.6** adds: `spanforge.testing`, `spanforge.auto`, async lifecycle hooks, `spanforge check` CLI, export retry with back-off, `unpatch()` / `is_patched()` for all integrations, frozen payload dataclasses, `assert_no_sunset_reached()`

---

## Project structure

```
spanforge/
├── __init__.py       <- Public API surface (start here)
├── event.py          <- The Event envelope
├── types.py          <- EventType enum  (+ SpanErrorCategory)
├── config.py         <- configure() / get_config() / SpanForgeConfig
│                        (sample_rate, always_sample_errors, include_raw_tool_io,
│                         enable_trace_store, trace_store_size)
├── _span.py          <- Span, AgentRun, AgentStep context managers
│                        (contextvars stacks, async with, add_event,
│                         record_error, set_timeout_deadline)
├── _trace.py         <- Trace class + start_trace()          [NEW in 2.0]
├── _tracer.py        <- Tracer — top-level tracing entry point
├── _stream.py        <- Internal dispatch: sample → redact → sign → export
├── _store.py         <- TraceStore ring buffer                [NEW in 2.0]
├── _hooks.py         <- HookRegistry singleton (hooks)        [NEW in 2.0]
├── _cli.py           <- CLI entry-point (18 sub-commands: check, check-compat, validate,
│                        audit-chain, inspect, stats, list-deprecated, migration-roadmap,
│                        check-consumers, compliance, cost, dev, module, serve, init,
│                        quickstart, report, ui)
├── _server.py        <- TraceViewerServer — lightweight HTTP server for /traces endpoint
├── trace.py          <- @trace() decorator + SpanOTLPBridge   [NEW in 1.0.7]
├── cost.py           <- CostTracker, BudgetMonitor, @budget_alert [NEW in 1.0.7]
├── inspect.py        <- InspectorSession, inspect_trace()     [NEW in 1.0.7]
├── toolsmith.py      <- @tool, ToolRegistry, build_openai_schema() [NEW in 1.0.7]
├── retry.py          <- @retry, FallbackChain, CircuitBreaker [NEW in 1.0.7]
├── cache.py          <- SemanticCache, @cached, *Backend      [NEW in 1.0.7]
├── lint/             <- run_checks(), AO001-AO005, flake8 plugin, CLI [NEW in 1.0.7]
│   ├── __init__.py
│   ├── _visitor.py
│   ├── _checks.py
│   ├── _flake8.py
│   └── __main__.py
├── testing.py        <- MockExporter, capture_events(), assert_event_schema_valid(),
│                        trace_store() — test utilities without real exporters [1.0.6]
├── auto.py           <- Integration auto-discovery; setup() / teardown()        [1.0.6]
├── debug.py          <- print_tree, summary, visualize        [NEW in 2.0]
├── metrics.py        <- aggregate(), MetricsSummary, etc.     [NEW in 2.0]
├── signing.py        <- HMAC signing & audit chains
├── redact.py         <- PII redaction
├── validate.py       <- JSON Schema validation
├── consumer.py       <- Consumer registry & schema-version compatibility
├── governance.py     <- Event governance policies
├── deprecations.py   <- Per-event-type deprecation tracking
├── compliance/       <- Compatibility checklist suite
├── core/
│   └── compliance_mapping.py <- ComplianceMappingEngine + evidence packages [Commercial]
├── export/
│   ├── jsonl.py      <- Local file export (async)
│   ├── webhook.py    <- HTTP POST export
│   ├── otlp.py       <- OpenTelemetry export
│   ├── datadog.py    <- Datadog APM traces + metrics
│   ├── grafana.py    <- Grafana Loki export
│   └── cloud.py      <- spanforge Cloud export (thread-safe, batched) [Commercial]
├── exporters/
│   ├── jsonl.py      <- SyncJSONLExporter
│   └── console.py    <- SyncConsoleExporter
├── stream.py         <- EventStream fan-out router (+ Kafka source)
├── integrations/
│   ├── langchain.py  <- LangChain callback handler
│   ├── llamaindex.py <- LlamaIndex event handler
│   ├── openai.py     <- OpenAI tracing wrapper
│   ├── crewai.py     <- CrewAI handler + patch()              [NEW in 2.0]
│   └── ...           (anthropic, groq, ollama, together)
├── namespaces/       <- Typed payload dataclasses
│   ├── trace.py        (SpanPayload + temperature/top_p/max_tokens/error_category,
│   │                    SpanEvent, ToolCall + arguments_raw/result_raw/retry_count)
│   ├── cost.py
│   ├── cache.py
│   └── ...
├── models.py         <- Optional Pydantic v2 models
└── migrate.py        <- Schema migration: v1_to_v2(), migrate_file(), MigrationStats
examples/             <- Runnable sample scripts
├── openai_chat.py    <- OpenAI + JSONL export
├── agent_workflow.py <- Multi-step agent + console exporter
├── langchain_chain.py<- LangChain callback handler
└── secure_pipeline.py<- HMAC signing + PII redaction together
```

---

## Development setup

```bash
git clone https://github.com/veerarag1973/spanforge.git
cd spanforge

python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux

pip install -e ".[dev]"
pytest                          # run all 3 032 tests
```

<details>
<summary><strong>Code quality commands</strong></summary>

```bash
ruff check .                  # linting
ruff format .                 # auto-format
mypy spanforge                  # type checking
pytest --cov                  # tests + coverage report (>=90% required)
```

</details>

<details>
<summary><strong>Build the docs locally</strong></summary>

```bash
pip install -e ".[docs]"
cd docs
sphinx-build -b html . _build/html   # open _build/html/index.html
```

</details>

---

## Compatibility and versioning

``spanforge`` implements **RFC-0001 spanforge** (AI Compliance Standard for Agentic AI Systems). The current schema version is **2.0**.

This project follows [Semantic Versioning](https://semver.org/):

- **Patch** releases (``1.0.x``) — bug fixes only, fully backwards-compatible
- **Minor** releases (``1.x.0``) — new features, backwards-compatible
- **Major** releases (``x.0.0``) — breaking changes, announced in advance

The ``llm.trace.*`` namespace payload schema is **additionally frozen at v2**: even a major release will not remove or rename fields from ``SpanPayload``, ``AgentRunPayload``, or ``AgentStepPayload``.

---

## Changelog

See [docs/changelog.md](docs/changelog.md) for the full version history.

---

## Contributing

Contributions are welcome! Please read the [Contributing Guide](docs/contributing.md) first, then open an issue or pull request.

Key rules:
- All new code must maintain **>= 90 % test coverage**
- Follow the existing **Google-style docstrings**
- Run ``ruff`` and ``mypy`` before submitting

---

## Community

- **GitHub Discussions** — questions, ideas, and show-and-tell: [github.com/veerarag1973/spanforge/discussions](https://github.com/veerarag1973/spanforge/discussions)
- **Bug reports & feature requests** — use GitHub Issues with the provided templates
- **Security disclosures** — see [SECURITY.md](SECURITY.md) for our responsible-disclosure process
- **Code of Conduct** — this project follows the [Contributor Covenant v2.1](CODE_OF_CONDUCT.md)
- **Changelog** — see [docs/changelog.md](docs/changelog.md) for release history

> GitHub topics for discoverability: `ai-compliance` `ai-governance` `llm-tracing` `opentelemetry` `pii-redaction` `audit-trail` `langchain` `openai` `python`

---

## License

[MIT](LICENSE) — free for personal and commercial use.

---

<p align="center">
  Made with care for the AI compliance community.<br/>
  <a href="docs/index.md">Docs</a> ·
  <a href="docs/quickstart.md">Quickstart</a> ·
  <a href="docs/api/index.md">API Reference</a> ·
  <a href="https://github.com/veerarag1973/spanforge/discussions">Discussions</a> ·
  <a href="https://github.com/veerarag1973/spanforge/issues">Report a bug</a>
</p>
