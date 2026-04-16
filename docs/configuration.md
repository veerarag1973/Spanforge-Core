# Configuration Reference

spanforge can be configured at runtime via **environment variables**, a
**`spanforge.toml` file** (loaded by `spanforge init`), or the
**Python API** (`spanforge.configure(...)`).

Use `spanforge.interpolate_env(template)` to expand `${VAR}` placeholders
in configuration strings at runtime.

Environment variables always take the highest precedence and override values
set programmatically or in the TOML file.

---

## Core settings

These variables are read at import time by `spanforge.config._load_from_env()`.

| Variable | Type | Default | Description |
|---|---|---|---|
| `SPANFORGE_EXPORTER` | `string` | `console` | Export backend. Supported values: `console`, `jsonl`, `otlp`, `otlp-grpc`, `webhook`, `datadog`, `grafana`, `cloud`. |
| `SPANFORGE_ENDPOINT` | `string` | *(none)* | Destination URL for the configured exporter (e.g. OTLP collector, webhook URL). |
| `SPANFORGE_ORG_ID` | `string` | *(none)* | Organisation / tenant identifier attached to every event. Useful for multi-tenant deployments. |
| `SPANFORGE_SERVICE_NAME` | `string` | `unknown-service` | Logical name of the instrumented service. |
| `SPANFORGE_ENV` | `string` | `production` | Deployment environment tag (e.g. `production`, `staging`, `development`). |
| `SPANFORGE_SERVICE_VERSION` | `string` | `0.0.0` | Semantic version of the instrumented service. |
| `SPANFORGE_SIGNING_KEY` | `string` | *(none)* | Base64-encoded HMAC-SHA256 key. When set, every emitted event receives a `_sig` field as per RFC-0001. |
| `SPANFORGE_ON_EXPORT_ERROR` | `string` | `warn` | Behaviour when an export call fails. Options: `warn` (log warning), `raise` (propagate exception), `drop` (silently discard). |
| `SPANFORGE_SAMPLE_RATE` | `float` | `1.0` | Fraction of events to emit (0.0–1.0). Values outside this range are clamped automatically. |
| `SPANFORGE_ENABLE_TRACE_STORE` | `bool` | `false` | Enable the in-process trace store (required for the `/traces` HTTP query endpoint and `spanforge ui`). Accepts `1`, `true`, or `yes`. |
| `SPANFORGE_ALLOW_PRIVATE_ENDPOINTS` | `bool` | `false` | Allow HTTP-based exporters (Webhook, OTLP, Datadog, Grafana Loki, Cloud) to target loopback or RFC-1918 addresses. **For development only** — never enable in production as it bypasses SSRF protections (URL validation + DNS resolution check). Accepts `1`, `true`, or `yes`. |

---

## Signing & compliance settings *(v1.0)*

These variables configure the advanced signing features introduced in v1.0.0.

| Variable | Type | Default | Description |
|---|---|---|---|
| `SPANFORGE_SIGNING_KEY_CONTEXT` | `string` | *(none)* | Environment label (e.g. `prod`, `staging`) used as an additional HKDF context when deriving signing keys via `derive_key()`. Isolates key material per environment. |
| `SPANFORGE_SIGNING_KEY_EXPIRES_AT` | `string` | *(none)* | ISO-8601 datetime (e.g. `2025-03-01T00:00:00Z`). When set and the key is expired, `sign()` raises `KeyExpiredError`. Use `check_key_expiry()` to inspect status without signing. |
| `SPANFORGE_SIGNING_KEY_MIN_BITS` | `int` | `256` | Minimum acceptable key strength in bits. `validate_key_strength()` returns warnings for keys below this threshold. |
| `SPANFORGE_REQUIRE_ORG_ID` | `bool` | `false` | When `true`, `AuditStream.write()` raises `ValueError` if an event has no `org_id`. Useful in multi-tenant deployments. Accepts `1`, `true`, or `yes`. |
| `SPANFORGE_NO_EGRESS` | `bool` | `false` | Block all outbound network calls from exporters. When enabled, only local/file-based exporters (`console`, `jsonl`) are permitted. Accepts `1`, `true`, or `yes`. |
| `SPANFORGE_EGRESS_ALLOWLIST` | `string` | *(none)* | Comma-separated list of allowed egress hostnames (e.g. `otel.example.com,logs.example.com`). Only evaluated when `SPANFORGE_NO_EGRESS` is `false`. |
| `SPANFORGE_COMPLIANCE_SAMPLING` | `bool` | `false` | Enable compliance-grade sampling that preserves deterministic reproducibility for audit trails. Accepts `1`, `true`, or `yes`. |

### Example — production signing with expiry and egress lockdown

```shell
export SPANFORGE_SIGNING_KEY="base64-encoded-key-here"
export SPANFORGE_SIGNING_KEY_CONTEXT="prod"
export SPANFORGE_SIGNING_KEY_EXPIRES_AT="2026-01-01T00:00:00Z"
export SPANFORGE_REQUIRE_ORG_ID=true
export SPANFORGE_EGRESS_ALLOWLIST="otel-collector.internal,logs.example.com"
```

---

## Alerting settings

Read by `spanforge.alerts.AlertConfig.from_env()`. At least one channel must
be configured for alerts to be dispatched.

| Variable | Type | Default | Description |
|---|---|---|---|
| `SPANFORGE_ALERT_SLACK_WEBHOOK` | `string` | *(none)* | Slack Incoming Webhook URL for alert notifications. |
| `SPANFORGE_ALERT_TEAMS_WEBHOOK` | `string` | *(none)* | Microsoft Teams Incoming Webhook URL. |
| `SPANFORGE_ALERT_PAGERDUTY_KEY` | `string` | *(none)* | PagerDuty Events API v2 routing/integration key. |
| `SPANFORGE_ALERT_SMTP_HOST` | `string` | *(none)* | SMTP server hostname for email alerts (e.g. `smtp.sendgrid.net`). |
| `SPANFORGE_ALERT_SMTP_PORT` | `int` | `587` | SMTP server port. STARTTLS is used automatically on port 587. |
| `SPANFORGE_ALERT_EMAIL_FROM` | `string` | `spanforge@localhost` | Sender address used in alert emails. |
| `SPANFORGE_ALERT_EMAIL_TO` | `string` | *(none)* | Comma-separated list of recipient addresses (e.g. `ops@example.com,oncall@example.com`). |
| `SPANFORGE_ALERT_EMAIL_USERNAME` | `string` | *(none)* | SMTP authentication username. |
| `SPANFORGE_ALERT_EMAIL_PASSWORD` | `string` | *(none)* | SMTP authentication password. **Never commit this to source control** — use a secret manager or CI secret. |
| `SPANFORGE_ALERT_COOLDOWN_SECONDS` | `int` | `300` | Deduplication window in seconds. Alerts with the same key are suppressed for this duration after the first delivery. |

### Example — Slack alerting

```shell
export SPANFORGE_ALERT_SLACK_WEBHOOK="https://hooks.slack.com/services/T.../B.../xxx"
export SPANFORGE_ALERT_COOLDOWN_SECONDS=120
```

```python
from spanforge.alerts import AlertConfig

config = AlertConfig.from_env()
manager = config.build_manager()
manager.fire("budget_exceeded", "Cost limit reached: $45.20 / $40.00")
```

---

## Redis stream settings

Read by `spanforge.export.redis_backend.RedisExporter`. Requires the
`spanforge[redis]` extra (`pip install "spanforge[redis]"`).

| Variable | Type | Default | Description |
|---|---|---|---|
| `SPANFORGE_REDIS_URL` | `string` | `redis://localhost:6379` | Redis connection URL. Supports `redis://`, `rediss://` (TLS), and `unix://` socket paths. |
| `SPANFORGE_REDIS_STREAM_KEY` | `string` | `spanforge:events` | Redis Stream key that events are written to via `XADD`. |
| `SPANFORGE_REDIS_MAX_LEN` | `int` | `100000` | Maximum number of entries in the stream (`XADD MAXLEN ~`). Older entries are evicted automatically when the limit is reached. |
| `SPANFORGE_REDIS_TTL_SECONDS` | `int` | `0` | Per-key TTL in seconds. `0` (default) means no TTL is set. |

### Example — Redis exporter

```shell
export SPANFORGE_EXPORTER=redis
export SPANFORGE_REDIS_URL="rediss://my-redis.example.com:6380"
export SPANFORGE_REDIS_STREAM_KEY="prod:spanforge:events"
export SPANFORGE_REDIS_MAX_LEN=500000
```

---

## Python API

Environment variables are applied automatically at import time. You can also
override any setting programmatically:

```python
import spanforge

spanforge.configure(
    service_name="my-service",
    env="production",
    exporter="otlp",
    endpoint="http://otel-collector:4318",
    signing_key="<base64-key>",
    sample_rate=0.5,
    # v1.0 signing & compliance options
    signing_key_context="prod",
    signing_key_expires_at="2026-01-01T00:00:00Z",
    require_org_id=True,
    no_egress=False,
    egress_allowlist=frozenset({"otel-collector.internal"}),
    compliance_sampling=True,
)
```

`spanforge.configure()` merges the supplied fields onto the live singleton; any
field not listed keeps its current value (env-var-sourced or default).

---

## spanforge.toml

Running `spanforge init` scaffolds a `spanforge.toml` file in the current
directory. Settings in this file are loaded when the TOML is explicitly
referenced via `spanforge.configure_from_file("spanforge.toml")`.

```toml
[spanforge]
service_name = "my-service"
env          = "production"
exporter     = "otlp"
endpoint     = "http://otel-collector:4318"
sample_rate  = 1.0
```

Environment variables always override values from `spanforge.toml`.

---

## Security notes

- Never log or display `SPANFORGE_SIGNING_KEY`, `SPANFORGE_SIGNING_KEY_CONTEXT`,
  `SPANFORGE_ALERT_EMAIL_PASSWORD`, or `SPANFORGE_ALERT_PAGERDUTY_KEY`. All
  sensitive fields are excluded from `repr()` on the config dataclass.
- Use a secrets manager (AWS Secrets Manager, Azure Key Vault, HashiCorp Vault)
  or your CI/CD platform's secret injection for credentials in production.
- `SPANFORGE_ALLOW_PRIVATE_ENDPOINTS=true` disables SSRF protection. Only use it
  in fully isolated development environments.
