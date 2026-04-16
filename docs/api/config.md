# spanforge.config — Global configuration

> **Module:** `spanforge.config`

`spanforge.config` provides the global configuration singleton, the
`configure()` entry point, and environment-variable interpolation utilities.

---

## Quick example

```python
from spanforge import configure
from spanforge.config import get_config

configure(
    preset="production",
    exporter="otlp",
    endpoint="http://collector:4318",
)
cfg = get_config()
print(cfg.exporter)  # "otlp"
```

---

## API

### `SpanForgeConfig`

Mutable dataclass holding all SDK configuration fields.  Key fields:

| Field | Default | Env var | Description |
|-------|---------|---------|-------------|
| `exporter` | `"console"` | `SPANFORGE_EXPORTER` | Backend: `console`, `jsonl`, `otlp`, `webhook`, `datadog`, `grafana_loki` |
| `endpoint` | `None` | `SPANFORGE_ENDPOINT` | Exporter destination (file path or URL) |
| `org_id` | `None` | `SPANFORGE_ORG_ID` | Organisation identifier |
| `service_name` | `"unknown-service"` | `SPANFORGE_SERVICE_NAME` | Human-readable service name |
| `env` | `"production"` | `SPANFORGE_ENV` | Deployment environment tag |
| `service_version` | `"0.0.0"` | `SPANFORGE_SERVICE_VERSION` | SemVer string |
| `signing_key` | `None` | `SPANFORGE_SIGNING_KEY` | Base64-encoded HMAC key |
| `sample_rate` | `1.0` | `SPANFORGE_SAMPLE_RATE` | Fraction of traces to emit (0.0–1.0) |
| `on_export_error` | `"warn"` | `SPANFORGE_ON_EXPORT_ERROR` | `"warn"` / `"raise"` / `"drop"` |
| `enable_trace_store` | `False` | `SPANFORGE_ENABLE_TRACE_STORE` | In-process ring buffer |
| `no_egress` | `False` | `SPANFORGE_NO_EGRESS` | Block all network exporters |
| `compliance_sampling` | `True` | `SPANFORGE_COMPLIANCE_SAMPLING` | Always-record compliance events |
| `consent_enforcement` | `False` | `SPANFORGE_CONSENT_ENFORCEMENT` | T.R.U.S.T. consent checks |
| `hitl_enabled` | `False` | `SPANFORGE_HITL_ENABLED` | Human-in-the-loop review queue |

See the source docstring for the full list of fields.

---

### `configure(**kwargs)`

```python
def configure(**kwargs: Any) -> None: ...
```

Mutate the global `SpanForgeConfig` singleton.  Accepts any field name as a
keyword argument.  Unknown keys raise `ValueError`.

**Presets:** Pass `preset="<name>"` to apply a sensible defaults bundle
before other kwargs:

| Preset | Exporter | Sample rate | Notes |
|--------|----------|-------------|-------|
| `development` | `console` | 1.0 | Trace store on, private endpoints allowed |
| `testing` | `console` | 1.0 | `on_export_error="raise"` |
| `staging` | `console` | 0.5 | Always-sample errors |
| `production` | `otlp` | 0.1 | Batch 512, flush 5 s |
| `otel_passthrough` | `otel_bridge` | 1.0 | Compliance sampling on |

---

### `get_config()`

```python
def get_config() -> SpanForgeConfig: ...
```

Return the live configuration singleton.  Modifications to the returned
object affect all subsequent SDK operations.

---

### `interpolate_env()`

> **Added in:** 2.0.3

```python
def interpolate_env(data: Any) -> Any: ...
```

Recursively replace `${VAR}` and `${VAR:default}` patterns in *data*.

Walks strings, dicts (values only), and lists depth-first.  Non-string
leaves are returned unchanged.

| Pattern | Behaviour |
|---------|-----------|
| `${FOO}` | Replaced with `os.environ["FOO"]`; left as-is if unset. |
| `${FOO:bar}` | Replaced with `os.environ["FOO"]` when set, `"bar"` otherwise. |

**Example:**

```python
import os
from spanforge.config import interpolate_env

os.environ["MODEL"] = "gpt-4o"
result = interpolate_env({
    "model": "${MODEL}",
    "endpoint": "${ENDPOINT:https://api.openai.com/v1}",
})
# {"model": "gpt-4o", "endpoint": "https://api.openai.com/v1"}
```

> **Note:** Dict keys are **not** interpolated — only values.
