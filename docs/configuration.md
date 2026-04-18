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

## Secrets scanning settings

Read by `spanforge.secrets.SecretsScanner` and `spanforge.sdk.secrets.SFSecretsClient`.
No extra install required — the secrets scanner is part of the core package.

| Variable | Type | Default | Description |
|---|---|---|---|
| `SPANFORGE_SECRETS_CONFIDENCE_THRESHOLD` | `float` | `0.85` | Minimum confidence score (0.0–1.0) for a pattern match to be reported. Lower values surface more candidates; raise to reduce false positives. |
| `SPANFORGE_SECRETS_AUTO_BLOCK` | `bool` | `true` | When `true`, `SFSecretsClient.scan()` raises `SFSecretsBlockedError` if any zero-tolerance secret type is detected. Accepts `1`, `true`, or `yes`. |
| `SPANFORGE_SECRETS_ALLOWLIST` | `string` | *(none)* | Comma-separated list of known-safe placeholder values to suppress (e.g. `YOUR_KEY_HERE,example_token`). Case-insensitive. |
| `SPANFORGE_SECRETS_STORE_REDACTED` | `bool` | `false` | When `true`, the SDK client stores a redacted copy of the scanned text alongside each scan result for audit trail purposes. Accepts `1`, `true`, or `yes`. |
| `SPANFORGE_SF_SECRETS_ENDPOINT` | `string` | *(none)* | Optional remote sf-secrets service endpoint. When set, `SFSecretsClient` forwards scans to the service for centralised policy enforcement; falls back to local scanning on network error. |

### Zero-tolerance auto-blocked types

The following secret types always trigger auto-block regardless of threshold when
`SPANFORGE_SECRETS_AUTO_BLOCK=true`:

`BEARER_TOKEN`, `AWS_ACCESS_KEY`, `GCP_SERVICE_ACCOUNT`, `PEM_PRIVATE_KEY`,
`SSH_PRIVATE_KEY`, `HC_API_KEY`, `SF_API_KEY`, `GITHUB_PAT`, `STRIPE_LIVE_KEY`,
`NPM_TOKEN`

### Example — strict CI/CD configuration

```shell
export SPANFORGE_SECRETS_CONFIDENCE_THRESHOLD=0.75
export SPANFORGE_SECRETS_AUTO_BLOCK=true
export SPANFORGE_SECRETS_ALLOWLIST="YOUR_API_KEY_HERE,REPLACE_ME,example_token"
```

### Example — disable auto-block for audit-only mode

```shell
export SPANFORGE_SECRETS_AUTO_BLOCK=false
export SPANFORGE_SECRETS_CONFIDENCE_THRESHOLD=0.70
```

### Example — Python API

```python
from spanforge.secrets import SecretsScanner

scanner = SecretsScanner(
    confidence_threshold=0.80,
    allowlist=["YOUR_KEY_HERE", "example_token"],
)
result = scanner.scan(open("config.env").read())
if result.detected:
    print(result.to_sarif())
```

---

## PII service settings (Phase 3)

Read by `spanforge.sdk.pii.SFPIIClient`.  These variables control the sf-pii
integration introduced in Phase 3.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SPANFORGE_SF_PII_ENDPOINT` | `string` | `""` *(local Presidio)* | URL of a remote sf-pii service. When empty, the local Presidio/regex engine is used. Example: `https://pii.internal.example.com`. |
| `SPANFORGE_PII_ACTION` | `"flag" \| "redact" \| "block"` | `"flag"` | Pipeline action applied by `apply_pipeline_action()`. `"flag"` annotates; `"redact"` replaces with type labels; `"block"` raises `SFPIIBlockedError`. |
| `SPANFORGE_PII_THRESHOLD` | `float` | `0.85` | Minimum confidence score (0–1) for a detected entity to be acted upon. |
| `SPANFORGE_PII_LANGUAGE` | `string` | `"en"` | Default ISO 639-1 language for text scanning. Overridden per-call by the `language` parameter. |
| `SPANFORGE_PII_MAX_DEPTH` | `int` | `10` | Maximum JSON nesting depth when scanning structured payloads via `scan_payload()`. |

### Example — flag-only mode (default)

```shell
export SPANFORGE_PII_ACTION=flag
export SPANFORGE_PII_THRESHOLD=0.85
```

### Example — strict block on PII detection

```shell
export SPANFORGE_PII_ACTION=block
export SPANFORGE_PII_THRESHOLD=0.80
```

### Example — remote sf-pii service

```shell
export SPANFORGE_SF_PII_ENDPOINT=https://pii.internal.example.com
export SPANFORGE_PII_ACTION=redact
```

### Example — Python API

```python
from spanforge.sdk import sf_pii

# Action and threshold can also be passed per-call
result = sf_pii.apply_pipeline_action(
    sf_pii.scan_text("Contact alice@example.com"),
    action="redact",
    threshold=0.80,
)
```

---

## Audit service settings (Phase 4)

Read by `spanforge.sdk.audit.SFAuditClient`. These variables control the
sf-audit service introduced in Phase 4.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SPANFORGE_AUDIT_BYOS_PROVIDER` | `"s3" \| "azure" \| "gcs" \| "r2"` | *(none — local)* | Bring-Your-Own-Storage backend. When set, `sf_audit.append()` routes records to the specified cloud provider. When unset, records are stored in-process. |

### BYOS provider values

| Value | Backend |
|-------|---------|
| `s3` | Amazon S3 |
| `azure` | Azure Blob Storage |
| `gcs` | Google Cloud Storage |
| `r2` | Cloudflare R2 |
| *(unset)* | Local in-memory store (default) |

### Example — route to S3

```shell
export SPANFORGE_AUDIT_BYOS_PROVIDER=s3
```

### Example — local mode (default, no env var needed)

```python
from spanforge.sdk import sf_audit

result = sf_audit.append(
    {"score": 0.92, "model": "gpt-4o"},
    schema_key="halluccheck.score.v1",
)
print(result.backend)   # "local"
```

### Example — standalone client with custom config

```python
from spanforge.sdk.audit import SFAuditClient
from spanforge.sdk._base import SFClientConfig

client = SFAuditClient(
    SFClientConfig(
        endpoint="https://audit.internal.example.com",
        api_key="...",
        signing_key="base64-key",
        project_id="my-project",
    ),
    strict_schema=True,
    retention_years=7,
    persist_index=True,
    db_path="/var/spanforge/audit_index.db",
)
```

---

## CEC service settings (Phase 5)

Read by `spanforge.sdk.cec.SFCECClient`. These variables control the
Compliance Evidence Chain service introduced in Phase 5.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SPANFORGE_SIGNING_KEY` | `string` | *(insecure default)* | HMAC-SHA256 key used to sign bundle manifests. Also shared with sf-audit. If unset or using the insecure default, a warning is logged at client init. **Always set this in production.** |
| `SPANFORGE_AUDIT_BYOS_PROVIDER` | `"s3" \| "azure" \| "gcs" \| "r2"` | *(none — local)* | Shared with sf-audit. When set, `sf_cec.get_status()` reports the active BYOS provider. |

### Supported framework values

| Value | Standard |
|-------|----------|
| `eu_ai_act` | EU AI Act (Articles 9, 10, 12, 13, 14, 15) |
| `iso_42001` | ISO/IEC 42001 AI Management System (Clauses 6.1, 8.3, 9.1, 10) |
| `nist_ai_rmf` | NIST AI Risk Management Framework (GOVERN, MAP, MEASURE, MANAGE) |
| `iso27001` | ISO/IEC 27001 Annex A (A.12.4.1–A.12.4.3) |
| `soc2` | SOC 2 Type II (CC6, CC7, CC9) |

### Example — build a compliance evidence bundle

```python
from spanforge.sdk import sf_cec

result = sf_cec.build_bundle(
    project_id="my-agent",
    date_range=("2026-01-01", "2026-03-31"),
    frameworks=["eu_ai_act", "soc2"],
)
print(result.zip_path)       # path to the signed ZIP
print(result.hmac_manifest)  # "hmac-sha256:<hex>"
```

### Example — set a production signing key

```shell
export SPANFORGE_SIGNING_KEY=$(openssl rand -hex 32)
```

### Example — verify a bundle

```python
from spanforge.sdk import sf_cec

result = sf_cec.verify_bundle("/path/to/bundle.zip")
assert result.overall_valid, result.errors
```

---

## Observe service settings (Phase 6)

Read by `spanforge.sdk.observe.SFObserveClient` at construction time.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SPANFORGE_OBSERVE_BACKEND` | `string` | `"local"` | Export backend. One of `local`, `otlp`, `datadog`, `grafana`, `splunk`, `elastic`. |
| `SPANFORGE_OBSERVE_SAMPLER` | `string` | `"always_on"` | Sampling strategy. One of `always_on`, `always_off`, `parent_based`, `trace_id_ratio`. |
| `SPANFORGE_OBSERVE_SAMPLE_RATE` | `float` | `1.0` | Fraction of spans to export when `SPANFORGE_OBSERVE_SAMPLER=trace_id_ratio`. Clamped to `[0.0, 1.0]`. |
| `SPANFORGE_ENV` | `string` | `"production"` | Value used for the `deployment.environment` OTel resource attribute on every span. |

### Backend URLs

When using a remote backend the base URL is taken from the matching
`SPANFORGE_<BACKEND>_ENDPOINT` variable (e.g. `SPANFORGE_OTLP_ENDPOINT`).
The path suffix is appended automatically:

| Backend | Path appended |
|---------|--------------|
| `otlp` | `/v1/traces` |
| `datadog` | `/api/v0.2/traces` |
| `grafana` | `/api/v1/push` |
| `splunk` | `/services/collector` |
| `elastic` | `/_bulk` |

### Example — enable Datadog export with ratio sampling

```shell
export SPANFORGE_OBSERVE_BACKEND=datadog
export SPANFORGE_OBSERVE_SAMPLER=trace_id_ratio
export SPANFORGE_OBSERVE_SAMPLE_RATE=0.25
export SPANFORGE_ENV=staging
```

---

## Gate service settings (Phase 8)

Read by `spanforge.sdk.gate.SFGateClient` and the `spanforge.gate.GateRunner`
YAML pipeline engine. These variables control artifact retention, PRRI thresholds,
HRI threshold, and the rolling detection windows for the trust gate.

| Variable | Type | Default | Description |
|---|---|---|---|
| `SPANFORGE_GATE_ARTIFACT_DIR` | `string` | `.sf-gate/artifacts` | Directory where gate artifacts (`.sf-gate.json` files) are written and retained. Relative paths are resolved from the current working directory. |
| `SPANFORGE_GATE_ARTIFACT_RETENTION_DAYS` | `int` | `90` | Artifacts older than this many days are eligible for purge via `purge_artifacts()`. |
| `SPANFORGE_GATE_PRRI_RED_THRESHOLD` | `float` | `70` | PRRI score at or above this value is classified as `RED` (block). Scores below this and at or above the amber boundary are `AMBER`; scores below amber are `GREEN`. |
| `SPANFORGE_GATE_HRI_CRITICAL_THRESHOLD` | `float` | `0.05` | Maximum tolerated hallucination risk index (HRI) critical rate (0.0–1.0). If the rate in the observation window exceeds this, the trust gate blocks. |
| `SPANFORGE_GATE_PII_WINDOW_HOURS` | `int` | `24` | Rolling window in hours for counting PII detection events used by the trust gate. |
| `SPANFORGE_GATE_SECRETS_WINDOW_HOURS` | `int` | `24` | Rolling window in hours for counting secrets detection events used by the trust gate. |

### Example — CI/CD environment

```shell
export SPANFORGE_GATE_ARTIFACT_DIR=".sf-gate/artifacts"
export SPANFORGE_GATE_ARTIFACT_RETENTION_DAYS=30
export SPANFORGE_GATE_PRRI_RED_THRESHOLD=65
export SPANFORGE_GATE_HRI_CRITICAL_THRESHOLD=0.03
export SPANFORGE_GATE_PII_WINDOW_HOURS=24
export SPANFORGE_GATE_SECRETS_WINDOW_HOURS=24
```

### Example — strict production mode

```shell
# Block on PRRI scores ≥ 60, HRI rate ≥ 2%, shorter windows
export SPANFORGE_GATE_PRRI_RED_THRESHOLD=60
export SPANFORGE_GATE_HRI_CRITICAL_THRESHOLD=0.02
export SPANFORGE_GATE_PII_WINDOW_HOURS=6
export SPANFORGE_GATE_SECRETS_WINDOW_HOURS=6
```

### Example — Python API

```python
from spanforge.sdk import sf_gate

sf_gate.configure({
    "artifact_dir": ".sf-gate/artifacts",
    "artifact_retention_days": 30,
    "prri_red_threshold": 65.0,
    "hri_critical_threshold": 0.03,
})
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

## `.halluccheck.toml` — Integration Config (v2.0.8+)

Phase 9 introduces a unified config block in `.halluccheck.toml` that bootstraps
all 8 SDK services, the service registry, and local fallback from a single file.

### Auto-discovery

`load_config_file()` searches for `.halluccheck.toml` in:

1. The path in `$SPANFORGE_CONFIG_PATH` (if set)
2. The current working directory
3. Parent directories (up to filesystem root)

If no file is found, all values fall back to environment variable defaults.

### Full config reference

```toml
# .halluccheck.toml — Phase 9 Integration Config

[spanforge]
enabled    = true              # Master switch (default: true)
project_id = "my-agent"        # Override: SPANFORGE_PROJECT_ID
endpoint   = "https://api.spanforge.example.com"  # Override: SPANFORGE_ENDPOINT
api_key    = ""                # Override: SPANFORGE_API_KEY (prefer env var)

[spanforge.services]
sf_pii      = true             # Enable PII service
sf_secrets  = true             # Enable secrets scanning service
sf_audit    = true             # Enable audit service
sf_observe  = true             # Enable observability service
sf_alert    = false            # Enable alerting service
sf_identity = false            # Enable identity service
sf_gate     = false            # Enable CI/CD gate service
sf_cec      = false            # Enable CEC (compliance evidence) service

[spanforge.local_fallback]
enabled     = true             # Activate fallback when services are unreachable
max_retries = 3                # Retries before fallback activation
timeout_ms  = 2000             # Override: SPANFORGE_FALLBACK_TIMEOUT_MS (default: 5000)

[pii]
threshold   = 0.8              # Override: SPANFORGE_PII_THRESHOLD (default: 0.8)

[secrets]
auto_block  = true             # Override: SPANFORGE_SECRETS_AUTO_BLOCK (default: true)
```

### Environment variable overrides

Environment variables always take precedence over `.halluccheck.toml` values:

| Variable | Config key | Default |
|----------|-----------|---------|
| `SPANFORGE_ENDPOINT` | `spanforge.endpoint` | `""` |
| `SPANFORGE_API_KEY` | `spanforge.api_key` | `""` |
| `SPANFORGE_PROJECT_ID` | `spanforge.project_id` | `"default"` |
| `SPANFORGE_PII_THRESHOLD` | `pii.threshold` | `0.8` |
| `SPANFORGE_SECRETS_AUTO_BLOCK` | `secrets.auto_block` | `true` |
| `SPANFORGE_LOCAL_TOKEN` | *(identity fallback)* | `""` |
| `SPANFORGE_FALLBACK_TIMEOUT_MS` | `spanforge.local_fallback.timeout_ms` | `5000` |

### Python API

```python
from spanforge.sdk import load_config_file, validate_config, validate_config_strict

# Load and auto-discover
config = load_config_file()                    # SFConfigBlock

# Load from explicit path
config = load_config_file("path/to/.halluccheck.toml")

# Validate (soft — returns error list)
errors = validate_config(config)
if errors:
    for e in errors:
        print(f"  - {e}")

# Validate (strict — raises SFConfigValidationError)
validate_config_strict(config)
```

### CLI validation

```bash
spanforge config validate                          # auto-discover
spanforge config validate --file .halluccheck.toml # explicit path
```

Exit codes: `0` = valid, `1` = validation errors, `2` = parse/I/O error.

### Service Registry

The `ServiceRegistry` singleton is initialised from the loaded config and
tracks health for all enabled services:

```python
from spanforge.sdk import ServiceRegistry

registry = ServiceRegistry.get_instance()
registry.run_startup_check()                   # ping all enabled services
status = registry.status_response()            # {service: {status, latency_ms, ...}}
registry.start_background_checker()            # re-check every 60 s in daemon thread
```

### Local fallback

When `local_fallback.enabled = true` and a service is unreachable, the SDK
automatically delegates to one of 8 local-mode fallback functions:

| Fallback function | Service | Behaviour |
|-------------------|---------|-----------|
| `pii_fallback()` | sf-pii | Regex PII scan via `spanforge.redact` |
| `secrets_fallback()` | sf-secrets | Regex secrets scan via `spanforge.secrets` |
| `audit_fallback()` | sf-audit | HMAC-chained JSONL to local file |
| `observe_fallback()` | sf-observe | OTLP JSON to stdout |
| `alert_fallback()` | sf-alert | Log to stderr at WARNING |
| `identity_fallback()` | sf-identity | Trust `SPANFORGE_LOCAL_TOKEN` env var |
| `gate_fallback()` | sf-gate | Local gate evaluation via `spanforge.gate` |
| `cec_fallback()` | sf-cec | Write CEC bundle to local JSONL file |

All fallback functions emit a `WARNING` log entry when activated.

---

## Security notes

- Never log or display `SPANFORGE_SIGNING_KEY`, `SPANFORGE_SIGNING_KEY_CONTEXT`,
  `SPANFORGE_ALERT_EMAIL_PASSWORD`, or `SPANFORGE_ALERT_PAGERDUTY_KEY`. All
  sensitive fields are excluded from `repr()` on the config dataclass.
- Use a secrets manager (AWS Secrets Manager, Azure Key Vault, HashiCorp Vault)
  or your CI/CD platform's secret injection for credentials in production.
- `SPANFORGE_ALLOW_PRIVATE_ENDPOINTS=true` disables SSRF protection. Only use it
  in fully isolated development environments.
