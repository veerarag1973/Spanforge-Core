# Quickstart

spanforge is the reference implementation of **RFC-0001 spanforge** — the open
event-schema standard for compliance and governance of agentic AI systems. This page walks
you through creating your first event, signing an audit chain, and exporting to
OTLP — in under five minutes.

## Installation

```bash
pip install spanforge
```

> The PyPI distribution is **`spanforge`**; the import name is `spanforge`.

For optional features:

```bash
pip install "spanforge[jsonschema]"   # JSON Schema validation
pip install "spanforge[http]"         # Async OTLP/webhook export (httpx)
pip install "spanforge[pydantic]"     # Pydantic v2 model layer
pip install "spanforge[otel]"         # OTelBridgeExporter — TracerProvider integration
```

Python 3.9+ is required.

## Creating your first event

Every interaction with an LLM tool is represented as an `Event`.
The minimum required fields are `event_type`, `source`, and `payload`:

```python
from spanforge import Event, EventType

event = Event(
    event_type=EventType.TRACE_SPAN_COMPLETED,
    source="my-tool@1.0.0",
    payload={"span_name": "run_agent", "status": "ok", "duration_ms": 312},
)

print(event.event_id)        # 01JPXXXXXXXXXXXXXXXXXXXXXXXX  (auto-generated ULID)
print(event.schema_version)  # 2.0
print(event.to_json())       # compact JSON
```

### Full event with optional fields

```python
from spanforge import Event, EventType, Tags

event = Event(
    event_type=EventType.TRACE_SPAN_COMPLETED,
    source="my-tool@1.0.0",
    payload={"span_name": "chat_completion", "status": "ok"},
    org_id="org_01HX",
    team_id="team_engineering",
    trace_id="a" * 32,        # 32-char hex OpenTelemetry trace ID
    span_id="b" * 16,         # 16-char hex span ID
    tags=Tags(env="production", model="gpt-4o"),
)
```

## Typed namespace payloads

Use the typed payload dataclasses from `spanforge.namespaces` to get
field validation and IDE auto-complete for each event namespace:

```python
import dataclasses
from spanforge import Event, EventType
from spanforge.namespaces.trace import (
    SpanPayload, TokenUsage, ModelInfo, GenAISystem, GenAIOperationName
)

token_usage = TokenUsage(input_tokens=120, output_tokens=80, total_tokens=200)
model_info  = ModelInfo(system=GenAISystem.OPENAI, name="gpt-4o")

payload = SpanPayload(
    span_name="chat_completion",
    status="ok",
    duration_ms=250,
    token_usage=token_usage.to_dict(),
    model_info=model_info.to_dict(),
    operation=GenAIOperationName.CHAT,
)

event = Event(
    event_type=EventType.TRACE_SPAN_COMPLETED,
    source="llm-trace@1.0.0",
    payload=dataclasses.asdict(payload),
)
```

## HMAC signing and audit chains

Sign individual events or build a full tamper-evident chain:

```python
from spanforge import Event, EventType
from spanforge.signing import sign, verify, AuditStream

# --- Single event ---
event = Event(
    event_type=EventType.TRACE_SPAN_COMPLETED,
    source="my-tool@1.0.0",
    payload={"span_name": "chat"},
)
signed = sign(event, org_secret="my-secret")
assert verify(signed, org_secret="my-secret")

# --- Audit chain ---
stream = AuditStream(org_secret="my-secret", source="my-tool@1.0.0")
for i in range(5):
    evt = Event(
        event_type=EventType.TRACE_SPAN_COMPLETED,
        source="my-tool@1.0.0",
        payload={"index": i},
    )
    stream.append(evt)

result = stream.verify()
assert result.valid                   # cryptographically intact
assert result.tampered_count == 0     # nothing altered
assert result.gaps == []              # no deletions
```

## PII redaction

Mark sensitive fields and apply a policy before storing or exporting events:

```python
from spanforge import Event, EventType
from spanforge.redact import Redactable, RedactionPolicy, Sensitivity

policy = RedactionPolicy(min_sensitivity=Sensitivity.PII, redacted_by="policy:corp-v1")

event = Event(
    event_type=EventType.PROMPT_SAVED,
    source="promptlock@1.0.0",
    payload={
        "prompt_text": Redactable("User email: alice@example.com", Sensitivity.PII, {"email"}),
        "model": "gpt-4o",
    },
)
result = policy.apply(event)
# result.event.payload["prompt_text"] is now "[REDACTED]"
```

### India PII detection (DPDP Act)

Detect Aadhaar and PAN numbers using the built-in India pattern pack:

```python
from spanforge import scan_payload, DPDP_PATTERNS

result = scan_payload(
    {"user_id": "2950 7148 9635", "pan": "ABCDE1234F"},
    extra_patterns=DPDP_PATTERNS,
)
for hit in result.hits:
    print(f"{hit.pii_type}: {hit.path} (sensitivity={hit.sensitivity})")
# aadhaar: user_id (sensitivity=high)
# pan: pan (sensitivity=high)
```

### PII service SDK (Phase 3)

The `spanforge.sdk.pii` module provides a rich, regulation-aware PII client
backed by Presidio (with regex fallback).

**Scan text:**

```python
from spanforge.sdk import sf_pii

result = sf_pii.scan_text("Contact alice@example.com or call +1 555-867-5309")
print(result.detected)         # True
for entity in result.entities:
    print(entity.entity_type, entity.score)  # EMAIL_ADDRESS 0.95
```

**Anonymise (replace with stable pseudonyms):**

```python
anon = sf_pii.anonymise(result)
print(anon.anonymised_text)    # "Contact <EMAIL_ADDRESS_1> or call <PHONE_NUMBER_1>"
```

**Pipeline action (flag / redact / block):**

```python
from spanforge.sdk._exceptions import SFPIIBlockedError

try:
    sf_pii.apply_pipeline_action(result, action="block", threshold=0.80)
except SFPIIBlockedError as exc:
    print("Blocked:", exc.entity_types)  # ["EMAIL_ADDRESS", "PHONE_NUMBER"]
```

**GDPR Art.17 — right to erasure:**

```python
receipt = sf_pii.erase_subject(subject_id="user-42")
print(receipt.fields_erased, receipt.receipt_id)
```

**CCPA DSAR — subject data export:**

```python
export = sf_pii.export_subject_data(subject_id="user-42")
for field in export.fields:
    print(field.field_path, field.pii_type)
```

**HIPAA safe harbor de-identification:**

```python
safe = sf_pii.safe_harbor_deidentify({"dob": "1980-01-15", "zip": "02139"})
print(safe.original_field_count, safe.redacted_field_count)
```

**PIPL (China) entity types:**

```python
result = sf_pii.scan_text("身份证: 110101199003077516", language="zh")
for e in result.entities:
    print(e.entity_type)  # PIPL_NATIONAL_ID
```

See the full reference at [spanforge.sdk.pii](api/pii.md).

### Audit service SDK (Phase 4)

`spanforge.sdk.audit` provides tamper-evident HMAC-chained record storage,
schema key enforcement, and regulatory compliance reporting.

**Append an audit record:**

```python
from spanforge.sdk import sf_audit

result = sf_audit.append(
    {"score": 0.92, "model": "gpt-4o", "prompt_id": "p-001"},
    schema_key="halluccheck.score.v1",
)
print(result.record_id)       # uuid4
print(result.hmac)            # "hmac-sha256:<64 hex chars>"
```

**Query and verify chain integrity:**

```python
records = sf_audit.query(schema_key="halluccheck.score.v1", limit=500)
chain = sf_audit.query(limit=1000)
report = sf_audit.verify_chain(chain)
assert report["valid"]
```

**T.R.U.S.T. scorecard:**

```python
scorecard = sf_audit.get_trust_scorecard(
    from_dt="2026-01-01T00:00:00.000000Z",
    to_dt="2026-12-31T23:59:59.999999Z",
)
print(scorecard.hallucination.score)   # 0–100
print(scorecard.overall)
```

See the full reference at [spanforge.sdk.audit](api/audit.md).

### Compliance Evidence Chain SDK (Phase 5)

`spanforge.sdk.cec` assembles regulator-ready signed ZIP bundles with
multi-framework clause mapping for EU AI Act, ISO 42001, NIST AI RMF,
ISO 27001, and SOC 2.

**Build a compliance bundle:**

```python
from spanforge.sdk import sf_cec

result = sf_cec.build_bundle(
    project_id="my-agent",
    date_range=("2026-01-01", "2026-03-31"),
    frameworks=["eu_ai_act", "soc2"],
)
print(result.zip_path)        # signed ZIP ready for auditors
print(result.hmac_manifest)   # "hmac-sha256:<64 hex chars>"
print(result.record_counts)   # {"score_records": 120, ...}
```

**Verify a bundle:**

```python
check = sf_cec.verify_bundle(result.zip_path)
assert check.overall_valid, check.errors
```

**Generate a GDPR Art.28 DPA:**

```python
dpa = sf_cec.generate_dpa(
    project_id="my-agent",
    controller_details={"name": "Acme Corp", "address": "1 Main St"},
    processor_details={"name": "SpanForge Inc", "address": "2 Cloud Way"},
    subject_categories=["employees", "end-users"],
    transfer_mechanisms=["SCCs"],
    retention_period_days=2555,
    law_of_contract="GDPR Art.28",
)
print(dpa.document_id)
```

See the full reference at [spanforge.sdk.cec](api/cec.md).

### Date-of-birth and address detection

`scan_payload()` also detects dates of birth and US street addresses out of the
box — no extra patterns required:

```python
from spanforge.redact import scan_payload

result = scan_payload({
    "dob": "04/15/1990",
    "home": "123 Maple Street",
})
for hit in result.hits:
    print(f"{hit.pii_type}: {hit.path} (sensitivity={hit.sensitivity})")
# date_of_birth: dob (sensitivity=high)
# address: home (sensitivity=medium)
```

The `date_of_birth` detector recognises all major global formats: ISO
(`YYYY-MM-DD`, `YYYY.MM.DD`), US month-first (`MM/DD/YYYY`, `MM.DD.YYYY`),
day-first (UK/EU/Asia: `DD/MM/YYYY`, `DD.MM.YYYY`), and written-month forms
(`15 Jan 2000`, `January 15, 2000`).  Calendar-invalid dates (e.g.
`02/30/1990`, `31/04/1990`) and SSNs in reserved ranges (area `000`, `666`,
`900–999`) are automatically filtered out to reduce false positives.

## Exporting events

```python
import asyncio
from spanforge import Event, EventType
from spanforge.export.jsonl import JSONLExporter

exporter = JSONLExporter("events.jsonl")
events = [
    Event(event_type=EventType.TRACE_SPAN_COMPLETED, source="tool@1.0.0", payload={"i": i})
    for i in range(10)
]
asyncio.run(exporter.export_batch(events))
```

See [user_guide/export.md](user_guide/export.md) for OTLP, webhook, Cloud, and `OTelBridgeExporter` (TracerProvider integration).

---

## Trace API (new in 2.0)

`start_trace()` gives you a first-class `Trace` object that tracks all spans
inside a single agent run. It works with both `with` and `async with`:

```python
import spanforge

spanforge.configure(exporter="console", service_name="my-agent")

with spanforge.start_trace("research-agent") as trace:
    with trace.llm_call("gpt-4o", temperature=0.7) as span:
        result = call_llm(prompt)
        span.set_token_usage(input=512, output=200, total=712)
        span.set_status("ok")
        span.add_event("reasoning_complete", {"steps": 3})

    with trace.tool_call("web_search") as span:
        output = run_search("latest AI news")
        span.set_status("ok")

# Pretty-print the span tree
trace.print_tree()
# — Agent Run: research-agent  [1.2s]
#  ├─ LLM Call: gpt-4o  [0.8s]  in=512 out=200 tokens  $0.0034
#  └─ Tool Call: web_search  [0.4s]  ok

# Summary statistics
print(trace.summary())
# {'trace_id': '...', 'agent_name': 'research-agent', 'span_count': 3,
#  'llm_calls': 1, 'tool_calls': 1, 'total_cost_usd': 0.0034, 'errors': 0}
```

---

## Lifecycle hooks (new in 2.0)

Register callbacks that fire on every span of a given type, globally:

```python
import spanforge

@spanforge.hooks.on_llm_call
def log_llm(span):
    print(f"LLM: {span.model}  temp={span.temperature}")

@spanforge.hooks.on_tool_call
def log_tool(span):
    print(f"Tool: {span.name}")
```

---

## Aggregating metrics (new in 2.0)

```python
import spanforge
from spanforge.stream import EventStream

events = list(EventStream.from_file("events.jsonl"))
m = spanforge.metrics.aggregate(events)

print(f"Success rate : {m.agent_success_rate:.0%}")
print(f"p95 LLM      : {m.llm_latency_ms.p95:.0f} ms")
print(f"Total cost   : ${m.total_cost_usd:.4f}")
print(f"By model     : {m.cost_by_model}")
```

---

## Semantic cache (new in 1.0.7)

Wrap any LLM function with `@cached` to skip the model entirely when a
semantically similar prompt was recently answered:

```python
from spanforge.cache import cached, SQLiteBackend

@cached(
    threshold=0.92,          # cosine similarity cutoff
    ttl=3600,                # seconds
    backend=SQLiteBackend("cache.db"),
    emit_events=True,        # emits llm.cache.hit/miss/written events
)
async def ask(prompt: str) -> str:
    return await my_llm(prompt)

# First call: cache miss → LLM runs
reply1 = await ask("Summarise the spanforge RFC.")

# Second call with a semantically near-identical prompt: instant cache hit
reply2 = await ask("Give me a short summary of the spanforge RFC.")
```

See the full [Semantic Cache user guide](user_guide/cache.md) and
[spanforge.cache API reference](api/cache.md).

---

## Lint your instrumentation (new in 1.0.7)

`spanforge.lint` scans Python files for instrumentation mistakes — missing
required fields, bare PII strings, LLM calls outside span contexts, etc.:

```python
from spanforge.lint import run_checks

errors = run_checks(open("myapp/pipeline.py").read(), "myapp/pipeline.py")
for e in errors:
    print(f"{e.filename}:{e.line}:{e.col}: {e.code} {e.message}")
```

Or run the CLI over a whole directory:

```bash
python -m spanforge.lint myapp/
# AO001  Event() missing required field 'payload'    pipeline.py:17
# AO004  LLM call outside tracer span context        pipeline.py:53
# 2 errors in 1 file.
```

The five AO-codes also appear in standard `flake8` / `ruff` output with no
extra configuration after installing `spanforge`.

See the full [Linting user guide](user_guide/linting.md) and
[spanforge.lint API reference](api/lint.md).

---

## Next steps

- [User Guide](user_guide/index.md) — in-depth guide to all features
- [Tracing API](user_guide/tracing.md) — `Trace`, `start_trace()`, async spans, `add_event()`
- [Debugging & Visualization](user_guide/debugging.md) — `print_tree()`, `summary()`, `visualize()`
- [Metrics & Analytics](user_guide/metrics.md) — `metrics.aggregate()`, `TraceStore`
- [Semantic Cache](user_guide/cache.md) — `SemanticCache`, `@cached`, backends
- [Linting & Static Analysis](user_guide/linting.md) — AO001–AO005, flake8 plugin, CI setup
- [API Reference](api/index.md) — full API reference
- [Namespace Payload Catalogue](namespaces/index.md) — typed payload catalogue
- [CLI](cli.md) — `spanforge check-compat` command
