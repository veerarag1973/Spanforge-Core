# Alert Routing Service (sf-alert)

> **Added in:** 2.0.6 (Phase 7)  
> **Module:** `spanforge.sdk.alert`  
> **Singleton:** `spanforge.sdk.sf_alert`

The sf-alert service provides topic-based alert routing with deduplication,
CRITICAL escalation, per-project rate limiting, maintenance-window suppression,
and six production-ready sink integrations. Every dispatch is audit-logged to
`sf_audit` schema `spanforge.alert.v1` on a best-effort basis.

---

## Installation

sf-alert ships with the core package — no extra dependencies required. Sink
credentials are loaded from environment variables at startup.

```shell
pip install spanforge
```

---

## Getting started

```python
from spanforge.sdk import sf_alert

# Publish a CRITICAL drift alert
result = sf_alert.publish(
    "halluccheck.drift.red",
    {"model": "gpt-4o", "drift_score": 0.91, "threshold": 0.80},
    severity="critical",
    project_id="proj-abc123",
)
print(result.alert_id)    # UUID4, e.g. "3f9a7e12-..."
print(result.suppressed)  # False — alert was dispatched

# Acknowledge to cancel the 15-min escalation timer
sf_alert.acknowledge(result.alert_id)
```

---

## Configuration via environment variables

Set the following variables before starting your application:

```shell
# Sink credentials
export SPANFORGE_ALERT_SLACK_WEBHOOK="https://hooks.slack.com/services/..."
export SPANFORGE_ALERT_TEAMS_WEBHOOK="https://xxx.webhook.office.com/webhookb2/..."
export SPANFORGE_ALERT_PAGERDUTY_KEY="pd-routing-key"
export SPANFORGE_ALERT_OPSGENIE_KEY="og-api-key"
export SPANFORGE_ALERT_OPSGENIE_REGION="us"   # or "eu"
export SPANFORGE_ALERT_VICTOROPS_URL="https://alert.victorops.com/integrations/..."
export SPANFORGE_ALERT_WEBHOOK_URL="https://hooks.example.com/alert"
export SPANFORGE_ALERT_WEBHOOK_SECRET="my-hmac-secret"

# Tuning
export SPANFORGE_ALERT_DEDUP_SECONDS=300     # default: 300
export SPANFORGE_ALERT_RATE_LIMIT=60         # default: 60 alerts/min/project
export SPANFORGE_ALERT_ESCALATION_WAIT=900   # default: 900 s (15 min)
```

---

## Topic registry

Eight built-in topics from the HallucCheck event taxonomy are pre-registered:

| Topic | Default severity |
|-------|-----------------|
| `halluccheck.drift.red` | `critical` |
| `halluccheck.drift.amber` | `warning` |
| `halluccheck.pii.detected` | `high` |
| `halluccheck.cost.exceeded` | `warning` |
| `halluccheck.latency.breach` | `warning` |
| `halluccheck.audit.gap` | `high` |
| `halluccheck.security.violation` | `critical` |
| `halluccheck.compliance.breach` | `critical` |

### Registering custom topics

```python
sf_alert.register_topic(
    "myapp.pipeline.failed",
    description="ML pipeline execution failure",
    default_severity="high",
    runbook_url="https://runbooks.example.com/pipeline",
    dedup_window_seconds=600.0,  # 10-minute per-topic dedup window
)
```

Publishing to an unregistered topic logs a `WARNING` and routes to all sinks.

---

## Deduplication

The same `(topic, project_id)` pair is suppressed for `dedup_window_seconds`
(default: 300 s) after the first dispatch. Per-topic overrides take precedence
over the client-wide setting.

```python
# First publish → dispatched
r1 = sf_alert.publish("halluccheck.drift.red", {}, project_id="proj-1")
assert not r1.suppressed

# Second publish within 5 minutes → suppressed
r2 = sf_alert.publish("halluccheck.drift.red", {}, project_id="proj-1")
assert r2.suppressed
```

---

## Alert grouping

Multiple alerts sharing the same `(topic_prefix, project_id)` — where
*prefix* is everything before the last `.` — are coalesced within a
2-minute window. The first alert is dispatched immediately; subsequent
alerts are buffered and sent as a single notification when the timer
fires.

```python
# Both share prefix "halluccheck.drift" → r2 buffered
r1 = sf_alert.publish("halluccheck.drift.red", {"i": 1})   # dispatched
r2 = sf_alert.publish("halluccheck.drift.amber", {"i": 2}) # buffered
assert r2.routed_to == []  # deferred until flush
```

---

## CRITICAL escalation

CRITICAL alerts schedule an escalation timer (default: 900 s = 15 min).
If the alert is not acknowledged before the timer fires, it is
re-dispatched with an `[ESCALATED]` title prefix.

```python
result = sf_alert.publish(
    "halluccheck.security.violation",
    {"attacker_ip": "203.0.113.1"},
    severity="critical",
)

# Cancel escalation after investigating
sf_alert.acknowledge(result.alert_id)
```

---

## Maintenance windows

Suppress all alerts for a project during a planned maintenance period:

```python
from datetime import datetime, timezone, timedelta

# Suppress for 2 hours
sf_alert.set_maintenance_window(
    project_id="proj-abc",
    start=datetime.now(timezone.utc),
    end=datetime.now(timezone.utc) + timedelta(hours=2),
)

# Alert during window → suppressed and audit-logged
result = sf_alert.publish("halluccheck.drift.red", {}, project_id="proj-abc")
assert result.suppressed

# Remove when maintenance is over
removed = sf_alert.remove_maintenance_windows("proj-abc")
print(f"Removed {removed} windows")
```

---

## Alert history

```python
from datetime import datetime, timezone, timedelta

records = sf_alert.get_alert_history(
    project_id="proj-abc",
    topic="halluccheck.drift.red",
    from_dt=datetime.now(timezone.utc) - timedelta(hours=1),
    status="open",
    limit=50,
)

for r in records:
    print(r.alert_id, r.severity, r.timestamp, r.sinks_notified)
```

---

## Adding sinks at runtime

```python
from spanforge.sdk.alert import OpsGenieAlerter, WebhookAlerter

# Add OpsGenie
sf_alert.add_sink(OpsGenieAlerter(api_key="og-key", region="eu"), "opsgenie-eu")

# Add a generic HMAC-signed webhook
sf_alert.add_sink(
    WebhookAlerter(url="https://hooks.example.com/alert", secret="secret"),
    "custom-webhook",
)
```

---

## Rate limiting

Per-project sliding-window rate limiting (default: 60 alerts/minute).
When exceeded in normal mode, the alert is suppressed and logged. In strict
mode (`local_fallback_enabled=False`), `SFAlertRateLimitedError` is raised.

```python
from spanforge.sdk._base import SFClientConfig
from spanforge.sdk.alert import SFAlertClient

# Strict mode: raise instead of suppress
client = SFAlertClient(
    SFClientConfig(local_fallback_enabled=False),
    rate_limit_per_minute=10,
)
```

---

## Sink security

| Sink | Secret handling |
|------|----------------|
| `WebhookAlerter` | `secret` field has `repr=False`; HMAC computed with `hmac.new()`; constant-time compare |
| `OpsGenieAlerter` | `api_key` has `repr=False` |
| `IncidentIOAlerter` | `api_key` has `repr=False` |
| `SMSAlerter` | `auth_token` has `repr=False` |
| All URL-based sinks | URLs validated by SSRF guard (rejects private/loopback IPs, non-HTTPS) |

---

## Circuit breakers

Each sink has an independent `_CircuitBreaker` (5-failure threshold, 30 s
auto-reset). A failing sink is bypassed without blocking other sinks.

```python
status = sf_alert.get_status()
print(status.sink_count)  # number of registered sinks
print(status.healthy)     # True when worker thread is alive
```

---

## Graceful shutdown

```python
# Drains queue, cancels escalation timers, stops worker thread
sf_alert.shutdown(timeout=10.0)
```

---

## See also

- [API reference: spanforge.sdk.alert](../api/alert.md)
- [Changelog: Phase 7](../changelog.md)
- [Audit Service (sf-audit)](audit.md) — audit records written by sf-alert
