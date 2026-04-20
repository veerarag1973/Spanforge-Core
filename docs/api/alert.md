# spanforge.sdk.alert — Alert Routing Service

> **Module:** `spanforge.sdk.alert`  
> **Added in:** 2.0.6 (Phase 7: Alert Routing Service)

`spanforge.sdk.alert` provides the Phase 7 alert routing SDK client. It handles
topic-based publish/subscribe, per-sink circuit breakers, deduplication,
per-project rate limiting, alert grouping, CRITICAL escalation policy,
maintenance-window suppression, HMAC-signed webhooks, and integrations with
Slack, Teams, PagerDuty, OpsGenie, VictorOps, Incident.io, SMS (Twilio), and
generic webhooks.

The pre-built `sf_alert` singleton is available at the top level:

```python
from spanforge.sdk import sf_alert
```

---

## Quick example

```python
from spanforge.sdk import sf_alert

# Publish a CRITICAL hallucination-drift alert
result = sf_alert.publish(
    "halluccheck.drift.red",
    {"model": "gpt-4o", "drift_score": 0.91},
    severity="critical",
    project_id="proj-abc123",
)

# Acknowledge to cancel the escalation timer
sf_alert.acknowledge(result.alert_id)
```

---

## Singletons and constructors

### `sf_alert`

```python
from spanforge.sdk import sf_alert  # SFAlertClient instance
```

Auto-configured from `SPANFORGE_ALERT_*` environment variables.

### `SFAlertClient(config, sinks=None, *, dedup_window_seconds, rate_limit_per_minute, escalation_wait_seconds, escalation_sinks)`

```python
from spanforge.sdk.alert import SFAlertClient
from spanforge.sdk._base import SFClientConfig

client = SFAlertClient(
    SFClientConfig(),
    dedup_window_seconds=300.0,
    rate_limit_per_minute=60,
    escalation_wait_seconds=900.0,
)
```

---

## Public methods

### `publish(topic, payload, *, severity=None, project_id=None) → PublishResult`

Publish an alert to all configured sinks.

**Steps (in order):**
1. Topic lookup — warns if unknown
2. Resolve severity (override → registry default → `"warning"`)
3. Maintenance-window check — returns `suppressed=True` if active
4. Rate-limit check — suppresses or raises `SFAlertRateLimitedError` (strict mode)
5. Deduplication check — suppresses if within effective window
6. Grouping — first alert dispatched immediately; subsequent alerts with same `(topic_prefix, project_id)` coalesced for 2 minutes
7. Dispatch via background worker

**Returns** `PublishResult(alert_id, routed_to, suppressed)`.

```python
result = sf_alert.publish(
    "halluccheck.pii.detected",
    {"field": "email", "model": "claude-3"},
    severity="high",
    project_id="proj-abc",
)
print(result.alert_id)     # UUID4 string
print(result.suppressed)   # True if deduplicated / maintenance window / rate-limited
```

---

### `acknowledge(alert_id) → bool`

Cancel the escalation timer for a CRITICAL alert.

```python
ok = sf_alert.acknowledge("c7d3e2a1-...")
# True  → timer found and cancelled
# False → no pending escalation for this ID
```

---

### `register_topic(topic, description, default_severity, *, runbook_url=None, dedup_window_seconds=None) → None`

Register a custom topic with optional per-topic deduplication window and runbook URL.

```python
sf_alert.register_topic(
    "myapp.pipeline.failed",
    "ML pipeline execution failure",
    "high",
    runbook_url="https://runbooks.example.com/pipeline",
    dedup_window_seconds=600.0,
)
```

---

### `set_maintenance_window(project_id, start, end) → None`

Suppress all alerts for a project during the specified UTC window.

```python
from datetime import datetime, timezone, timedelta

sf_alert.set_maintenance_window(
    "proj-abc",
    start=datetime.now(timezone.utc),
    end=datetime.now(timezone.utc) + timedelta(hours=2),
)
```

---

### `remove_maintenance_windows(project_id) → int`

Remove all maintenance windows for a project. Returns count removed.

---

### `get_alert_history(*, project_id="", topic="", from_dt=None, to_dt=None, status="", limit=100) → list[AlertRecord]`

Retrieve alert history with optional filtering. Returns most-recent-first.

```python
records = sf_alert.get_alert_history(
    project_id="proj-abc",
    status="open",
    limit=20,
)
for r in records:
    print(r.alert_id, r.topic, r.severity, r.timestamp)
```

---

### `get_status() → AlertStatusInfo`

Return a snapshot of client state.

```python
info = sf_alert.get_status()
print(info.publish_count, info.suppress_count, info.healthy)
```

---

### `add_sink(alerter, name=None) → None`

Dynamically add a sink at runtime.

```python
from spanforge.sdk.alert import OpsGenieAlerter

sf_alert.add_sink(OpsGenieAlerter(api_key="og-key"), name="opsgenie-prod")
```

---

### `shutdown(timeout=5.0) → None`

Drain the dispatch queue, cancel all escalation timers, and stop the worker thread.

```python
sf_alert.shutdown(timeout=10.0)
```

---

## Sinks

### `WebhookAlerter(url, secret="", timeout=10)`

Generic HMAC-signed webhook sink.

- Posts JSON body with `X-SF-Signature: sha256=<hex>` header
- URL validated by SSRF guard (rejects private/loopback IPs, non-HTTPS)

```python
from spanforge.sdk.alert import WebhookAlerter

sink = WebhookAlerter(url="https://hooks.example.com/alert", secret="mysecret")
sf_alert.add_sink(sink, "my-webhook")
```

---

### `OpsGenieAlerter(api_key, region="us", timeout=10)`

OpsGenie v2 Alerts API sink.

- Severity → priority map: `critical → P1`, `high → P2`, `warning → P3`, `info → P5`
- `repr=False` on `api_key` (never printed)

```python
from spanforge.sdk.alert import OpsGenieAlerter

sink = OpsGenieAlerter(api_key="og-key-...", region="eu")
```

---

### `VictorOpsAlerter(rest_endpoint_url, timeout=10)`

VictorOps REST Endpoint sink.

- Severity map: `critical → CRITICAL`, `high → WARNING`, others → `INFO`

```python
from spanforge.sdk.alert import VictorOpsAlerter

sink = VictorOpsAlerter(
    rest_endpoint_url="https://alert.victorops.com/integrations/generic/..."
)
```

---

### `IncidentIOAlerter(api_key, timeout=10)`

Incident.io v2 Alerts API sink.

- Severity map: `critical → critical`, `high → major`, others → `minor`
- `Bearer` token auth

```python
from spanforge.sdk.alert import IncidentIOAlerter

sink = IncidentIOAlerter(api_key="iio-key-...")
```

---

### `SMSAlerter(account_sid, auth_token, from_number, to_numbers, timeout=10)`

Twilio Messages API sink.

- Messages truncated to 160 characters
- `repr=False` on `auth_token`

```python
from spanforge.sdk.alert import SMSAlerter

sink = SMSAlerter(
    account_sid="AC...",
    auth_token="token",
    from_number="+15550001234",
    to_numbers=["+15550005678"],
)
```

---

### `TeamsAdaptiveCardAlerter(webhook_url, timeout=10)`

Microsoft Teams Incoming Webhook sink using Adaptive Cards v1.3.

- Severity colour band: `info → Good`, `warning/high → Warning`, `critical → Attention`
- Payload fields rendered as FactSet table
- Acknowledge and Silence action buttons

```python
from spanforge.sdk.alert import TeamsAdaptiveCardAlerter

sink = TeamsAdaptiveCardAlerter(
    webhook_url="https://xxx.webhook.office.com/webhookb2/..."
)
```

---

## Types

### `AlertSeverity`

```python
from spanforge.sdk import AlertSeverity

AlertSeverity.INFO      # "info"
AlertSeverity.WARNING   # "warning"
AlertSeverity.HIGH      # "high"
AlertSeverity.CRITICAL  # "critical"

AlertSeverity.from_str("bogus")  # → AlertSeverity.WARNING (fallback)
```

---

### `PublishResult`

```python
@dataclass(frozen=True)
class PublishResult:
    alert_id: str           # UUID4
    routed_to: list[str]    # Sink names notified (empty when suppressed or first-in-group)
    suppressed: bool        # True when deduplicated / maintenance / rate-limited
```

---

### `TopicRegistration`

```python
@dataclass(frozen=True)
class TopicRegistration:
    topic: str
    description: str
    default_severity: str
    runbook_url: str | None
    dedup_window_seconds: float | None
```

---

### `MaintenanceWindow`

```python
@dataclass(frozen=True)
class MaintenanceWindow:
    project_id: str
    start: datetime
    end: datetime
```

---

### `AlertRecord`

```python
@dataclass(frozen=True)
class AlertRecord:
    alert_id: str
    topic: str
    severity: str
    project_id: str
    payload: dict[str, Any]
    sinks_notified: list[str]
    suppressed: bool
    status: str             # "open" | "acknowledged" | "escalated"
    timestamp: str          # ISO-8601 UTC
```

---

### `AlertStatusInfo`

```python
@dataclass(frozen=True)
class AlertStatusInfo:
    status: str
    publish_count: int
    suppress_count: int
    sink_count: int
    queue_depth: int
    pending_escalations: int
    healthy: bool
```

---

### `publish_async(topic, payload, *, severity=None, project_id=None) → Coroutine[PublishResult]`

Async variant of `publish()`. Runs the publish operation (including rate-limit
check, deduplication, and dispatch) in a thread-pool executor so it does not
block the event loop.

```python
import asyncio
from spanforge.sdk import sf_alert

async def notify_drift(score: float):
    result = await sf_alert.publish_async(
        "halluccheck.drift.red",
        {"score": score},
        severity="critical",
    )
    return result.alert_id
```

Accepts the same parameters and returns the same `PublishResult` as `publish()`.

---

## Exceptions

| Exception | Raised when |
|-----------|-------------|
| `SFAlertError` | Base for all sf-alert errors |
| `SFAlertPublishError` | All configured sinks have open circuit breakers |
| `SFAlertRateLimitedError` | Per-project rate limit exceeded (`local_fallback_enabled=False`) |
| `SFAlertQueueFullError` | Dispatch queue full (> 1 000 items) |

---

## Built-in topics (`KNOWN_TOPICS`)

```python
from spanforge.sdk.alert import KNOWN_TOPICS

print(KNOWN_TOPICS)
# frozenset({
#   "halluccheck.drift.red",
#   "halluccheck.drift.amber",
#   "halluccheck.pii.detected",
#   "halluccheck.cost.exceeded",
#   "halluccheck.latency.breach",
#   "halluccheck.audit.gap",
#   "halluccheck.security.violation",
#   "halluccheck.compliance.breach",
# })
```

---

## Environment variables

| Variable | Default | Effect |
|----------|---------|--------|
| `SPANFORGE_ALERT_SLACK_WEBHOOK` | — | Auto-register Slack sink |
| `SPANFORGE_ALERT_TEAMS_WEBHOOK` | — | Auto-register Teams Adaptive Card sink |
| `SPANFORGE_ALERT_PAGERDUTY_KEY` | — | Auto-register PagerDuty sink |
| `SPANFORGE_ALERT_OPSGENIE_KEY` | — | Auto-register OpsGenie sink |
| `SPANFORGE_ALERT_OPSGENIE_REGION` | `us` | OpsGenie region (`us` or `eu`) |
| `SPANFORGE_ALERT_VICTOROPS_URL` | — | Auto-register VictorOps sink |
| `SPANFORGE_ALERT_WEBHOOK_URL` | — | Auto-register generic webhook sink |
| `SPANFORGE_ALERT_WEBHOOK_SECRET` | `""` | HMAC secret for generic webhook |
| `SPANFORGE_ALERT_DEDUP_SECONDS` | `300` | Deduplication window in seconds |
| `SPANFORGE_ALERT_RATE_LIMIT` | `60` | Alerts per minute per project |
| `SPANFORGE_ALERT_ESCALATION_WAIT` | `900` | Seconds before CRITICAL auto-escalation |

---

## See also

- [User guide: Alert Routing Service](../user_guide/alert.md)
- [Changelog: Phase 7](../changelog.md)
- [sf-audit (Phase 4)](audit.md) — audit records written by sf-alert
