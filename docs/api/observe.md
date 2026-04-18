# spanforge.sdk.observe — Observability Client

> **Module:** `spanforge.sdk.observe`  
> **Added in:** 2.0.5 (Phase 6: Observability Named SDK)

`spanforge.sdk.observe` provides the Phase 6 observability SDK client. It
handles span export (local buffer + OTLP / Datadog / Grafana / Splunk / Elastic),
structured annotation storage, W3C TraceContext / Baggage injection, OTel GenAI
semantic conventions, deterministic sampling, and health probes.

The pre-built `sf_observe` singleton is available at the top level:

```python
from spanforge.sdk import sf_observe
```

---

## Quick example

```python
from spanforge.sdk import sf_observe

# Emit a span for an LLM call
span_id = sf_observe.emit_span(
    "chat.completion",
    {
        "gen_ai.system": "openai",
        "gen_ai.request.model": "gpt-4o",
        "gen_ai.usage.input_tokens": 512,
        "gen_ai.usage.output_tokens": 64,
    },
)
print(span_id)  # 16-hex span ID, e.g. "a3f1b2c4d5e6f708"

# Add a deploy annotation
annotation_id = sf_observe.add_annotation(
    "model_deployed",
    {"model": "gpt-4o", "version": "2024-11", "environment": "production"},
    project_id="my-project",
)
print(annotation_id)  # UUID string

# Retrieve recent annotations
from datetime import datetime, timedelta, timezone
now = datetime.now(timezone.utc)
annotations = sf_observe.get_annotations(
    "model_deployed",
    (now - timedelta(hours=1)).isoformat(),
    now.isoformat(),
    project_id="my-project",
)
for ann in annotations:
    print(ann.event_type, ann.created_at)

# Export a batch of pre-built spans to an external OTLP endpoint
from spanforge.sdk import sf_observe, ReceiverConfig
result = sf_observe.export_spans(
    my_span_list,
    receiver_config=ReceiverConfig(
        endpoint="https://otel.collector.example.com/v1/traces",
        headers={"Authorization": "Bearer my-token"},
        timeout_seconds=10.0,
    ),
)
print(result.exported_count, result.backend)

# Health check
print(sf_observe.healthy)        # True / False
print(sf_observe.last_export_at) # ISO-8601 string or None
```

---

## `SFObserveClient`

```python
class SFObserveClient(SFServiceClient)
```

All public methods are thread-safe. A `threading.Lock()` guards the in-memory
annotation store and session statistics.

### Constructor

```python
SFObserveClient(config: SFClientConfig)
```

Reads the following environment variables at construction time:

| Variable | Meaning | Default |
|----------|---------|---------|
| `SPANFORGE_OBSERVE_BACKEND` | Export backend | `"local"` |
| `SPANFORGE_OBSERVE_SAMPLER` | Sampling strategy | `"always_on"` |
| `SPANFORGE_OBSERVE_SAMPLE_RATE` | Ratio sampler rate `[0.0, 1.0]` | `1.0` |
| `SPANFORGE_ENV` | `deployment.environment` OTel resource attribute | `"production"` |

---

### `export_spans`

```python
def export_spans(
    spans: list[dict[str, Any]],
    *,
    receiver_config: ReceiverConfig | None = None,
) -> ExportResult
```

Export a list of span dicts to the active backend (OBS-001).

| Parameter | Description |
|-----------|-------------|
| `spans` | List of OTLP-compatible span dicts. Empty list returns `ExportResult(0, 0, backend, ...)`. |
| `receiver_config` | Optional per-call override. When set, spans are POSTed to `receiver_config.endpoint` as OTLP JSON, ignoring the global backend. |

**Returns:** `ExportResult(exported_count, failed_count, backend, exported_at)`.

**Raises:** `SFObserveExportError` on transport/HTTP failure (unless `local_fallback_enabled=True` on the config, in which case spans are buffered locally).

---

### `emit_span`

```python
def emit_span(name: str, attributes: dict[str, Any]) -> str
```

Build and export a single span with OTel GenAI conventions (OBS-004).

- Injects W3C `traceparent` and `baggage` (OBS-011, OBS-012).
- Adds OTel resource attributes (OBS-013).
- Applies the active sampling strategy (OBS-031).
- Inherits `traceId` from `attributes["traceparent"]` when present.
- Sets `status.code = STATUS_CODE_ERROR` on error (OBS-015).

**Returns:** 16-hex span ID (always returned even when sampled out).

**Raises:** `SFObserveEmitError` on invalid `name` (empty) or `attributes` (non-dict).

---

### `add_annotation`

```python
def add_annotation(
    event_type: str,
    payload: dict[str, Any],
    *,
    project_id: str,
) -> str
```

Store a structured annotation in the in-memory log (OBS-002).

**Returns:** UUID annotation ID string.

**Raises:** `SFObserveAnnotationError` if `event_type` is empty or `payload` is not a dict.

---

### `get_annotations`

```python
def get_annotations(
    event_type: str,
    from_dt: str,
    to_dt: str,
    *,
    project_id: str = "",
) -> list[Annotation]
```

Retrieve annotations from the in-memory store (OBS-003).

| Parameter | Description |
|-----------|-------------|
| `event_type` | Filter by event type. Use `"*"` to return all types. |
| `from_dt` | ISO-8601 datetime string (inclusive lower bound). |
| `to_dt` | ISO-8601 datetime string (inclusive upper bound). |
| `project_id` | Optional project ID filter. Empty string = no filter. |

**Raises:** `SFObserveAnnotationError` if `from_dt` or `to_dt` is not a valid ISO-8601 datetime.

---

### `get_status`

```python
def get_status() -> ObserveStatusInfo
```

Return current service health and session statistics.

---

### `healthy`

```python
@property
def healthy(self) -> bool
```

`True` unless the most recent export attempt raised an unrecovered error (OBS-043).

---

### `last_export_at`

```python
@property
def last_export_at(self) -> str | None
```

ISO-8601 timestamp of the last successful `export_spans` call, or `None` if
no export has occurred yet (OBS-043).

---

## W3C TraceContext helpers

```python
from spanforge.sdk.observe import make_traceparent, extract_traceparent
```

### `make_traceparent`

```python
def make_traceparent(
    trace_id_hex: str,
    span_id_hex: str,
    *,
    sampled: bool,
) -> str
```

Encode a W3C `traceparent` header value (OBS-011).

```
00-<32 hex trace_id>-<16 hex span_id>-{01|00}
```

**Raises:** `ValueError` if `trace_id_hex` is not 32 hex chars or `span_id_hex` is not 16 hex chars.

### `extract_traceparent`

```python
def extract_traceparent(traceparent: str) -> tuple[str, str, bool]
```

Parse a `traceparent` header. Returns `(trace_id_hex, span_id_hex, sampled)`.

**Raises:** `ValueError` on malformed input.

---

## Sampling strategies

Set via `SPANFORGE_OBSERVE_SAMPLER` environment variable or by assigning
`client._sampler_strategy = SamplerStrategy.XXX` before use.

| Strategy | Env value | Behaviour |
|----------|-----------|-----------|
| `ALWAYS_ON` | `"always_on"` | Every span is exported (default) |
| `ALWAYS_OFF` | `"always_off"` | No spans are exported |
| `PARENT_BASED` | `"parent_based"` | Follows parent's sampled flag; samples by default when no parent |
| `TRACE_ID_RATIO` | `"trace_id_ratio"` | Deterministic fraction based on SHA-256 hash of `trace_id` |

---

## Backend exporters

| Backend | Env value | Protocol |
|---------|-----------|----------|
| Local buffer | `"local"` (default) | Bounded in-memory deque (≤ 10 000 spans) |
| OTLP | `"otlp"` | HTTP POST to `{endpoint}/v1/traces` as OTLP JSON |
| Datadog | `"datadog"` | HTTP POST to `{endpoint}/api/v0.2/traces` |
| Grafana Tempo | `"grafana"` | HTTP POST to `{endpoint}/api/v1/push` |
| Splunk HEC | `"splunk"` | HTTP POST to `{endpoint}/services/collector` |
| Elastic APM | `"elastic"` | HTTP POST to `{endpoint}/_bulk` as ECS documents |

---

## Types

### `ReceiverConfig`

```python
@dataclass(frozen=True)
class ReceiverConfig:
    endpoint: str
    headers: dict[str, str] = {}
    timeout_seconds: float = 30.0
```

Per-call OTLP receiver override for `export_spans`.

### `ExportResult`

```python
@dataclass(frozen=True)
class ExportResult:
    exported_count: int
    failed_count: int
    backend: str
    exported_at: str        # ISO-8601
```

### `Annotation`

```python
@dataclass(frozen=True)
class Annotation:
    annotation_id: str      # UUID
    event_type: str
    payload: dict[str, Any]
    project_id: str
    created_at: str         # ISO-8601
```

### `ObserveStatusInfo`

```python
@dataclass(frozen=True)
class ObserveStatusInfo:
    status: str             # "ok" | "error"
    backend: str
    sampler_strategy: str
    span_count: int
    annotation_count: int
    export_count: int
    last_export_at: str | None
    healthy: bool
```

### `SamplerStrategy`

```python
class SamplerStrategy(enum.Enum):
    ALWAYS_ON = "always_on"
    ALWAYS_OFF = "always_off"
    PARENT_BASED = "parent_based"
    TRACE_ID_RATIO = "trace_id_ratio"
```

---

## Exceptions

| Exception | Inherits | Raised by |
|-----------|----------|-----------|
| `SFObserveError` | `SFError` | Base for all observe errors |
| `SFObserveExportError` | `SFObserveError` | `export_spans` on transport / HTTP failure |
| `SFObserveEmitError` | `SFObserveError` | `emit_span` on invalid input or export failure |
| `SFObserveAnnotationError` | `SFObserveError` | `add_annotation` / `get_annotations` on invalid input |
