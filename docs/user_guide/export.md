# Export Backends & EventStream

spanforge ships six export backends and an `EventStream`
routing layer that ties them together.

## Quick overview

| Class | Protocol | Typical use |
|-------|----------|-------------|
| `OTLPExporter` | OTLP / HTTP JSON | OpenTelemetry collector, Grafana Tempo |
| `OTelBridgeExporter` | OTel SDK `TracerProvider` | Auto-instrumentation pipelines (requires `[otel]`) |
| `WebhookExporter` | HTTPS POST | Slack, PagerDuty, or any custom HTTP endpoint |
| `JSONLExporter` | Local file | Data-lake ingestion, offline analysis, tests |
| `DatadogExporter` | Datadog Agent + API | Datadog APM traces and metrics |
| `GrafanaLokiExporter` | Grafana Loki HTTP | Structured log aggregation in Grafana |
| `CloudExporter` | spanforge Cloud API | Hosted trace viewer, dashboards, retention |

## JSONLExporter

The simplest backend — useful for local replay and testing:

```python
from spanforge.export.jsonl import JSONLExporter

exporter = JSONLExporter("events.jsonl", gzip=False)
exporter.export(event)
exporter.flush()
```

Pass `gzip=True` to compress inline:

```python
exporter = JSONLExporter("events.jsonl.gz", gzip=True)
```

Each line is a compact JSON object identical to `Event.to_dict()`.

## WebhookExporter

POSTs each event as JSON to an arbitrary HTTP endpoint:

```python
from spanforge.export.webhook import WebhookExporter

exporter = WebhookExporter(
    url="https://hooks.example.com/llm-events",
    headers={"Authorization": "Bearer <token>"},
    timeout=5.0,
    max_retries=3,
    backoff_factor=0.5,
)
exporter.export(event)
```

Retry behaviour uses truncated-exponential back-off. After `max_retries`
failed attempts the event is dropped and a warning is logged.

## OTLPExporter

Sends events to an OpenTelemetry collector via gRPC:

```python
from spanforge.export.otlp import OTLPExporter

exporter = OTLPExporter(
    endpoint="http://otel-collector:4317",
    service_name="my-llm-service",
    resource_attrs={"deployment.environment.name": "production"},
    insecure=True,
    compression="gzip",
)
exporter.export(event)
```

Events **with** a `trace_id` become OTLP trace spans (`resourceSpans`). The
emitter sets `spanKind: CLIENT`, `traceFlags: 1` (sampled), and
`endTimeUnixNano` computed from `payload.duration_ms`. LLM metadata is exposed
as `gen_ai.*` attributes (GenAI semconv 1.27+): `gen_ai.system`,
`gen_ai.request.model`, `gen_ai.usage.input_tokens`,
`gen_ai.usage.output_tokens`, `gen_ai.operation.name`, and
`gen_ai.response.finish_reasons`.

Events **without** a `trace_id` become OTLP log records (`resourceLogs`).

## EventStream

`EventStream` multiplexes events across one or more backends and supports
filterable routing:

```python
from spanforge.stream import EventStream
from spanforge.export.jsonl import JSONLExporter
from spanforge.export.webhook import WebhookExporter

stream = EventStream()
stream.add_exporter(JSONLExporter("all.jsonl"))
stream.add_exporter(
    WebhookExporter("https://pagerduty.example/events"),
    filter=lambda e: e.event_type == "llm.guard.output.blocked",
)

stream.emit(event)     # emits to all matching exporters
```

## Scope filtering

Restrict an exporter to a specific org or team:

```python
from spanforge.stream import EventStream

stream = EventStream()
stream.add_exporter(
    JSONLExporter("team-alpha.jsonl"),
    filter=lambda e: e.team_id == "team_alpha",
)
```

## Fan-out pattern

Emit one event to many backends:

```python
stream = EventStream()
stream.add_exporter(JSONLExporter("archive.jsonl"))
stream.add_exporter(OTLPExporter("http://otel:4317", service_name="llm"))
stream.add_exporter(WebhookExporter("https://slack.example/webhook"))

for event in events:
    stream.emit(event)
```

## Flush and close

Exporters that buffer output implement a `flush()` method. Use as a context
manager to ensure resources are released:

```python
with JSONLExporter("events.jsonl") as exporter:
    for event in events:
        exporter.export(event)
# flush + close called automatically
```

---

## OTelBridgeExporter

Emits events through any configured OpenTelemetry `TracerProvider` — useful
when the SDK is already initialised by auto-instrumentation and you want
events to participate in the same trace pipeline.

```bash
pip install "spanforge[otel]"
```

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, BatchSpanProcessor

# Set up once at startup
provider = TracerProvider()
provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
trace.set_tracer_provider(provider)

from spanforge.export.otel_bridge import OTelBridgeExporter

exporter = OTelBridgeExporter(tracer_name="spanforge")
exporter.export(event)               # single event
await exporter.export_batch(events)  # batch
```

Unlike `OTLPExporter`, this bridge delegates span lifecycle to the SDK —
sampling decisions, `BatchSpanProcessor` flushing, and any other registered
`SpanProcessor` instances all fire normally.

---

## DatadogExporter

Sends events to the Datadog Agent as APM trace spans, and optionally to the
Datadog metrics API for numeric payload fields.

```bash
pip install "spanforge[datadog]"
```

```python
from spanforge.export.datadog import DatadogExporter

exporter = DatadogExporter(
    service="llm-gateway",
    env="production",
    agent_url="http://dd-agent:8126",    # Datadog Agent
    api_key="your-dd-api-key",           # Required for metrics
)

# Single event
await exporter.export(event)

# Batch
await exporter.export_batch(events)
```

### Tag format

All events are tagged with `service:<name>`, `env:<env>`, and `version:<ver>`.
LLM metadata (source, org_id, team_id) is stored under `meta["llm.*"]` keys
in the Datadog span.

### Metric extraction

Numeric fields in `event.payload` matching the built-in `_METRIC_FIELDS` set
(`cost_usd`, `token_count`, `duration_ms`, `score`, etc.) are sent as Datadog
metric series automatically.

---

## GrafanaLokiExporter

Pushes events to a Grafana Loki instance via the HTTP push API.

```python
from spanforge.export.grafana import GrafanaLokiExporter

exporter = GrafanaLokiExporter(
    url="http://loki:3100",
    labels={"env": "production", "app": "llm-gateway"},
    include_envelope_labels=True,   # adds source, org_id, team_id as labels
    tenant_id="my-org",             # sets X-Scope-OrgID
)

count = await exporter.export_batch(events)
print(f"Pushed {count} events")
```

### Label sanitisation

`event_type` dots are replaced with underscores for Loki label
compatibility:

```
llm.trace.span.completed  →  llm_trace_span_completed
```

### Multi-tenant deployments

Set `tenant_id` to add the `X-Scope-OrgID` header expected by Grafana
Enterprise Loki multi-tenant configurations.

### Fan-out with Loki + OTLP

```python
from spanforge.stream import EventStream
from spanforge.export.otlp import OTLPExporter
from spanforge.export.grafana import GrafanaLokiExporter

stream = EventStream(events)
await stream.route(OTLPExporter("http://otel-collector:4318/v1/traces"))
await stream.route(GrafanaLokiExporter("http://loki:3100"))
```

---

## Kafka source

Load events from a Kafka topic directly into an `EventStream`:

```bash
pip install "spanforge[kafka]"
```

```python
from spanforge.stream import EventStream

stream = EventStream.from_kafka(
    topic="llm-events",
    bootstrap_servers="kafka:9092",
    group_id="analytics",
    max_messages=5000,
)
await stream.drain(exporter)
```

---

## CloudExporter

Send events to spanforge Cloud — the hosted trace viewer and dashboard
service. Uses stdlib-only HTTP transport with thread-safe batching.

```python
from spanforge.export.cloud import CloudExporter

exporter = CloudExporter(
    api_key="sf_live_xxx",
    endpoint="https://ingest.getspanforge.com/v1/events",
    batch_size=100,
    flush_interval=5.0,
    timeout=10.0,
    max_retries=3,
)

await exporter.export(event)
await exporter.export_batch(events)
```

The exporter queues events in a thread-safe buffer (capped at 10,000) and
flushes automatically at the configured interval or batch size. SSRF
protections (URL validation + DNS resolution) are enforced by default; set
`allow_private_addresses=True` only in development.

Configure via environment variable:

```bash
export SPANFORGE_EXPORTER=cloud
export SPANFORGE_ENDPOINT=https://ingest.getspanforge.com/v1/events
```

Or via `spanforge.configure()`:

```python
import spanforge

spanforge.configure(
    exporter="cloud",
    endpoint="https://ingest.getspanforge.com/v1/events",
)
```
