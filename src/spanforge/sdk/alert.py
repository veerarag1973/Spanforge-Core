"""spanforge.sdk.alert — SpanForge sf-alert Alert Routing Service (Phase 7).

Implements the full sf-alert API surface: topic-based publish, per-sink circuit
breakers, 5-minute deduplication, per-project rate limiting, alert grouping,
CRITICAL escalation policy, maintenance-window suppression, webhook HMAC signing,
and integrations with Slack, Teams, PagerDuty, OpsGenie, VictorOps, Incident.io,
SMS (Twilio), and generic HMAC-signed webhooks.

Architecture
------------
* :meth:`publish` is the **primary entry point**.  It validates the topic,
  checks maintenance windows, deduplicates by ``(topic, project_id)``, applies
  per-project rate limits, enqueues the alert, and returns a
  :class:`~spanforge.sdk._types.PublishResult` immediately.
* A **background worker thread** drains the queue and dispatches to each
  configured sink through its own :class:`~spanforge.sdk._base._CircuitBreaker`.
* **CRITICAL alerts** schedule a :class:`threading.Timer` for auto-escalation
  after ``escalation_wait_seconds`` (default: 900 s = 15 min).
  :meth:`acknowledge` cancels the timer.
* All alert emissions are appended to ``sf-audit`` schema ``spanforge.alert.v1``
  on a best-effort basis (failures are logged at DEBUG level).

Topic registry (ALT-002, ALT-003)
-----------------------------------
Eight built-in topics match HallucCheck's published event taxonomy.  Additional
topics can be registered with :meth:`register_topic`.  Publishing to an unknown
topic logs a WARNING and routes to the catch-all sink list if configured.

Deduplication (ALT-010)
------------------------
The same ``(topic, project_id)`` pair is suppressed for ``dedup_window_seconds``
(default: 300 s).  Per-topic windows override the client default.

Alert grouping (ALT-011)
--------------------------
Multiple alerts sharing the same ``(topic_prefix, project_id)`` within a 2-minute
window are coalesced into a single notification.  The group is flushed when the
timer fires or when the window elapses.

Escalation policy (ALT-020, ALT-021)
--------------------------------------
CRITICAL severity alerts schedule an escalation timer.  When the timer fires the
alert is re-dispatched to the escalation sink list.  Call :meth:`acknowledge` to
cancel the timer.

Sink integrations
-----------------
All sinks live in this module:

* :class:`WebhookAlerter` — generic HMAC-signed webhook (ALT-034)
* :class:`OpsGenieAlerter` — OpsGenie Alert API v2 (ALT-030)
* :class:`VictorOpsAlerter` — VictorOps / Splunk On-Call (ALT-031)
* :class:`IncidentIOAlerter` — Incident.io (ALT-032)
* :class:`SMSAlerter` — Twilio SMS (ALT-033)
* :class:`TeamsAdaptiveCardAlerter` — enhanced Teams Adaptive Card (ALT-035)

The existing ``spanforge.alerts`` sinks (Slack, Teams, PagerDuty, Email) are
re-exported here for convenience.

Security requirements
---------------------
* Webhook HMAC secrets are never logged.  :class:`WebhookAlerter` uses
  :func:`hmac.compare_digest` for constant-time comparison and sets the
  ``X-SF-Signature: sha256=<hex>`` header.
* PagerDuty and OpsGenie integration keys are stored in ``repr=False`` fields.
* All remote URLs are validated with :func:`_validate_http_url` (same guard used
  in ``observe.py``) before each request.
* The audit log appended to sf-audit uses ``best_effort=True``; any failure is
  swallowed at DEBUG level so alerting itself is never blocked by audit issues.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import ipaddress
import json
import logging
import os
import queue
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Union

from spanforge.sdk._base import (
    SFClientConfig,
    SFServiceClient,
    _CircuitBreaker,
    _SlidingWindowRateLimiter,
)
from spanforge.sdk._exceptions import (
    SFAlertRateLimitedError,
)
from spanforge.sdk._types import (
    AlertRecord,
    AlertStatusInfo,
    MaintenanceWindow,
    PublishResult,
    TopicRegistration,
)

__all__ = [
    "KNOWN_TOPICS",
    "IncidentIOAlerter",
    "OpsGenieAlerter",
    "SFAlertClient",
    "SMSAlerter",
    "TeamsAdaptiveCardAlerter",
    "VictorOpsAlerter",
    "WebhookAlerter",
]

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: The eight HallucCheck-defined topics wired at design time.
KNOWN_TOPICS: frozenset[str] = frozenset(
    {
        "halluccheck.drift.amber",
        "halluccheck.drift.red",
        "halluccheck.bias.critical",
        "halluccheck.prri.red",
        "halluccheck.benchmark.regression",
        "halluccheck.pii.detected",
        "halluccheck.secrets.detected",
        "halluccheck.trust_gate.failed",
    },
)

_DEDUP_WINDOW_DEFAULT: float = 300.0  # 5 min
_GROUP_WINDOW_SECS: float = 120.0  # 2 min
_ESCALATION_WAIT_DEFAULT: float = 900.0  # 15 min
_QUEUE_MAX: int = 1_000
_RATE_LIMIT_PER_MINUTE: int = 60
_HISTORY_MAX: int = 10_000

# Severity ordinal for escalation gating
_SEVERITY_RANK: dict[str, int] = {"info": 0, "warning": 1, "high": 2, "critical": 3}


# ---------------------------------------------------------------------------
# URL validation (SSRF guard)
# ---------------------------------------------------------------------------


def _validate_http_url(url: str) -> None:
    """Raise :exc:`ValueError` if *url* is not a safe HTTP/HTTPS URL.

    Rejects:
    * Non-HTTP/HTTPS schemes.
    * Private/loopback IP targets (unless ``SPANFORGE_ALLOW_LOOPBACK=1``).
    * Overly long URLs (> 2 048 chars).
    """
    if len(url) > 2048:
        raise ValueError(f"URL too long: {len(url)} chars (max 2048)")
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported scheme {parsed.scheme!r}; only http/https allowed")
    hostname = parsed.hostname or ""
    if os.environ.get("SPANFORGE_ALLOW_LOOPBACK", "").lower() not in ("1", "true", "yes"):
        try:
            addr = ipaddress.ip_address(hostname)
            if addr.is_private or addr.is_loopback or addr.is_link_local:
                raise ValueError(f"Destination IP {hostname!r} is private/loopback (SSRF guard)")
        except ValueError as exc:
            if "SSRF" in str(exc):
                raise


# ---------------------------------------------------------------------------
# Sink implementations (Phase 7 additions)
# ---------------------------------------------------------------------------


@dataclass
class WebhookAlerter:
    """Generic HMAC-signed webhook sink (ALT-034).

    Sends a JSON POST with ``X-SF-Signature: sha256=<hmac>`` header.
    The HMAC is computed over the UTF-8 encoded request body using the
    configured *secret*.  Receivers verify with :func:`hmac.compare_digest`.

    Args:
        url:     Webhook endpoint URL.
        secret:  HMAC signing secret.  **Never logged.**
        timeout: HTTP timeout in seconds.
    """

    url: str
    secret: str = field(repr=False, default="")
    timeout: int = 10

    def send(
        self, title: str, message: str, severity: str = "warning", extra: dict[str, Any] | None = None,
    ) -> None:
        """POST alert JSON with HMAC signature."""
        _validate_http_url(self.url)
        body: dict[str, Any] = {"title": title, "message": message, "severity": severity}
        if extra:
            body.update(extra)
        data = json.dumps(body).encode()
        sig = _hmac.new(self.secret.encode(), data, hashlib.sha256).hexdigest()
        req = urllib.request.Request(
            self.url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "X-SF-Signature": f"sha256={sig}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # nosec B310
                if resp.status not in (200, 201, 202, 204):
                    _log.warning("WebhookAlerter: unexpected status %s", resp.status)
        except urllib.error.URLError as exc:
            _log.warning("WebhookAlerter: request failed: %s", exc)


@dataclass
class OpsGenieAlerter:
    """OpsGenie Alert API v2 sink (ALT-030).

    Args:
        api_key:  OpsGenie API key.  **Never logged.**
        region:   ``"us"`` (default) or ``"eu"``.
        timeout:  HTTP timeout in seconds.
    """

    api_key: str = field(repr=False)
    region: str = "us"
    timeout: int = 10

    _PRIORITY_MAP: dict[str, str] = field(
        init=False,
        repr=False,
        default_factory=lambda: {
            "info": "P5",
            "warning": "P3",
            "high": "P2",
            "critical": "P1",
        },
    )

    def _url(self) -> str:
        if self.region == "eu":
            return "https://api.eu.opsgenie.com/v2/alerts"
        return "https://api.opsgenie.com/v2/alerts"

    def send(
        self, title: str, message: str, severity: str = "warning", extra: dict[str, Any] | None = None,
    ) -> None:
        """Create an OpsGenie alert."""
        url = self._url()
        _validate_http_url(url)
        priority = self._PRIORITY_MAP.get(severity.lower(), "P3")
        payload: dict[str, Any] = {
            "message": title,
            "description": message,
            "priority": priority,
            "tags": [f"severity:{severity}", "spanforge"],
        }
        if extra:
            payload["details"] = {str(k): str(v) for k, v in extra.items()}
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"GenieKey {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # nosec B310
                if resp.status not in (200, 201, 202):
                    _log.warning("OpsGenieAlerter: unexpected status %s", resp.status)
        except urllib.error.URLError as exc:
            _log.warning("OpsGenieAlerter: request failed: %s", exc)


@dataclass
class VictorOpsAlerter:
    """VictorOps / Splunk On-Call sink (ALT-031).

    Args:
        rest_endpoint_url: VictorOps REST endpoint URL including routing key.
        timeout:           HTTP timeout in seconds.
    """

    rest_endpoint_url: str
    timeout: int = 10

    _MSG_TYPE_MAP: dict[str, str] = field(
        init=False,
        repr=False,
        default_factory=lambda: {
            "info": "INFO",
            "warning": "WARNING",
            "high": "CRITICAL",
            "critical": "CRITICAL",
        },
    )

    def send(
        self, title: str, message: str, severity: str = "warning", extra: dict[str, Any] | None = None,
    ) -> None:
        """POST to VictorOps REST endpoint."""
        _validate_http_url(self.rest_endpoint_url)
        message_type = self._MSG_TYPE_MAP.get(severity.lower(), "WARNING")
        payload: dict[str, Any] = {
            "message_type": message_type,
            "entity_display_name": title,
            "state_message": message,
        }
        if extra:
            payload.update(extra)
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            self.rest_endpoint_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # nosec B310
                if resp.status not in (200, 201, 202):
                    _log.warning("VictorOpsAlerter: unexpected status %s", resp.status)
        except urllib.error.URLError as exc:
            _log.warning("VictorOpsAlerter: request failed: %s", exc)


@dataclass
class IncidentIOAlerter:
    """Incident.io sink (ALT-032).

    Creates or updates an Incident.io incident via the REST API.

    Args:
        api_key:  Incident.io API key.  **Never logged.**
        timeout:  HTTP timeout in seconds.
    """

    api_key: str = field(repr=False)
    timeout: int = 10

    _SEVERITY_MAP: dict[str, str] = field(
        init=False,
        repr=False,
        default_factory=lambda: {
            "info": "minor",
            "warning": "major",
            "high": "major",
            "critical": "critical",
        },
    )

    _URL: str = "https://api.incident.io/v1/incidents"

    def send(
        self, title: str, message: str, severity: str = "warning", extra: dict[str, Any] | None = None,
    ) -> None:
        """Create an Incident.io incident."""
        _validate_http_url(self._URL)
        sev = self._SEVERITY_MAP.get(severity.lower(), "major")
        payload: dict[str, Any] = {
            "name": title,
            "summary": message,
            "severity": {"name": sev},
            "visibility": "public",
        }
        if extra:
            payload["custom_field_entries"] = [
                {"custom_field": {"name": str(k)}, "values": [{"value_text": str(v)}]}
                for k, v in extra.items()
            ]
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            self._URL,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # nosec B310
                if resp.status not in (200, 201, 202):
                    _log.warning("IncidentIOAlerter: unexpected status %s", resp.status)
        except urllib.error.URLError as exc:
            _log.warning("IncidentIOAlerter: request failed: %s", exc)


@dataclass
class SMSAlerter:
    """Twilio SMS sink (ALT-033).  Enterprise tier only.

    Sends a 160-character-limited SMS via the Twilio REST API.

    Args:
        account_sid:  Twilio Account SID.
        auth_token:   Twilio Auth Token.  **Never logged.**
        from_number:  Twilio phone number (E.164 format, e.g. ``"+15005550006"``).
        to_numbers:   List of recipient phone numbers (E.164 format).
        timeout:      HTTP timeout in seconds.
    """

    account_sid: str
    auth_token: str = field(repr=False)
    from_number: str
    to_numbers: list[str] = field(default_factory=list)
    timeout: int = 10

    def send(
        self, title: str, message: str, severity: str = "warning", extra: dict[str, Any] | None = None,  # noqa: ARG002
    ) -> None:
        """Send SMS to all configured recipients."""
        if not self.to_numbers:
            _log.warning("SMSAlerter: no recipients configured, skipping")
            return
        body_raw = f"[{severity.upper()}] {title}: {message}"
        body = body_raw[:160]
        url = f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json"
        _validate_http_url(url)
        for to_number in self.to_numbers:
            form_data = urllib.parse.urlencode(
                {"From": self.from_number, "To": to_number, "Body": body},
            ).encode()
            # Basic auth: account_sid:auth_token
            cred = f"{self.account_sid}:{self.auth_token}".encode()
            import base64  # noqa: PLC0415
            b64 = base64.b64encode(cred).decode()
            req = urllib.request.Request(
                url,
                data=form_data,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Authorization": f"Basic {b64}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # nosec B310
                    if resp.status not in (200, 201):
                        _log.warning("SMSAlerter: unexpected status %s for %s", resp.status, to_number)
            except urllib.error.URLError as exc:
                _log.warning("SMSAlerter: request failed for %s: %s", to_number, exc)


@dataclass
class TeamsAdaptiveCardAlerter:
    """Enhanced Microsoft Teams Adaptive Card sink (ALT-035).

    Sends a rich Adaptive Card with a severity colour band, a fact table
    from payload fields, and Acknowledge / Silence action buttons.

    Args:
        webhook_url: Teams channel Incoming Webhook URL.
        timeout:     HTTP timeout in seconds.
    """

    webhook_url: str
    timeout: int = 10

    _COLOUR_MAP: dict[str, str] = field(
        init=False,
        repr=False,
        default_factory=lambda: {
            "info": "Good",
            "warning": "Warning",
            "high": "Warning",
            "critical": "Attention",
        },
    )

    def send(
        self, title: str, message: str, severity: str = "warning", extra: dict[str, Any] | None = None,
    ) -> None:
        """POST an Adaptive Card to the Teams webhook."""
        _validate_http_url(self.webhook_url)
        colour = self._COLOUR_MAP.get(severity.lower(), "Warning")
        facts = [{"title": str(k), "value": str(v)} for k, v in (extra or {}).items()]
        card_body: list[dict[str, Any]] = [
            {
                "type": "TextBlock",
                "text": title,
                "weight": "Bolder",
                "size": "Medium",
                "color": colour,
            },
            {"type": "TextBlock", "text": message, "wrap": True},
        ]
        if facts:
            card_body.append(
                {
                    "type": "FactSet",
                    "facts": facts,
                },
            )
        payload = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.3",
                        "body": card_body,
                        "actions": [
                            {
                                "type": "Action.Submit",
                                "title": "Acknowledge",
                                "data": {"action": "acknowledge"},
                            },
                            {
                                "type": "Action.Submit",
                                "title": "Silence",
                                "data": {"action": "silence"},
                            },
                        ],
                    },
                },
            ],
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # nosec B310
                if resp.status not in (200, 202):
                    _log.warning("TeamsAdaptiveCardAlerter: unexpected status %s", resp.status)
        except urllib.error.URLError as exc:
            _log.warning("TeamsAdaptiveCardAlerter: request failed: %s", exc)


# ---------------------------------------------------------------------------
# Sink wrapper (circuit breaker per sink)
# ---------------------------------------------------------------------------

#: A type alias for any sink that supports a ``send()`` method.
_Alerter = Union[WebhookAlerter, OpsGenieAlerter, VictorOpsAlerter, IncidentIOAlerter, SMSAlerter, TeamsAdaptiveCardAlerter, Any]  # noqa: PYI016


@dataclass
class _SinkWrapper:
    """Wraps a sink instance with its own circuit breaker and a name."""

    alerter: _Alerter
    name: str
    cb: _CircuitBreaker = field(default_factory=_CircuitBreaker)

    def dispatch(
        self, title: str, message: str, severity: str, extra: dict[str, Any] | None = None,
    ) -> bool:
        """Send alert through the wrapped alerter, updating the circuit breaker.

        Returns:
            ``True`` if the alert was sent successfully.
        """
        if self.cb.is_open():
            _log.debug("_SinkWrapper[%s]: circuit open, skipping", self.name)
            return False
        try:
            if hasattr(self.alerter, "send"):
                try:
                    self.alerter.send(title, message, severity=severity, extra=extra)
                except TypeError:
                    # Older sinks (from alerts.py) don't accept extra kwarg
                    self.alerter.send(title, message, severity=severity)
        except Exception:  # noqa: BLE001
            self.cb.record_failure()
            _log.exception("_SinkWrapper[%s]: dispatch error", self.name)
            return False
        else:
            self.cb.record_success()
            return True


# ---------------------------------------------------------------------------
# Queue item
# ---------------------------------------------------------------------------

@dataclass
class _QueueItem:
    alert_id: str
    topic: str
    title: str
    message: str
    severity: str
    project_id: str
    payload: dict[str, Any]
    runbook_url: str | None
    is_escalation: bool = False


# ---------------------------------------------------------------------------
# SFAlertClient
# ---------------------------------------------------------------------------


class SFAlertClient(SFServiceClient):
    """SpanForge sf-alert Alert Routing Service client.

    Topic-based publish/subscribe model with deduplication, escalation policy,
    per-sink circuit breakers, per-project rate limiting, and audit logging.

    All operations are **thread-safe**.

    Args:
        config:                 :class:`~spanforge.sdk._base.SFClientConfig` loaded
                                from env or via :func:`~spanforge.sdk.configure`.
        sinks:                  Optional list of sink instances pre-wired at
                                construction time.  Sinks are also auto-discovered
                                from ``SPANFORGE_ALERT_*`` environment variables.
        dedup_window_seconds:   Client-wide deduplication window (default: 300 s).
        rate_limit_per_minute:  Per-project alert rate limit (default: 60).
        escalation_wait_seconds: Seconds before a CRITICAL alert auto-escalates
                                 (default: 900 s = 15 min).
        escalation_sinks:       Sink names to route escalated alerts to.  If
                                 empty, all sinks are used for escalation.

    Environment variables
    ---------------------
    .. code-block:: text

        SPANFORGE_ALERT_SLACK_WEBHOOK       → SlackAlerter (from spanforge.alerts)
        SPANFORGE_ALERT_TEAMS_WEBHOOK       → TeamsAdaptiveCardAlerter
        SPANFORGE_ALERT_PAGERDUTY_KEY       → PagerDutyAlerter (from spanforge.alerts)
        SPANFORGE_ALERT_OPSGENIE_KEY        → OpsGenieAlerter
        SPANFORGE_ALERT_OPSGENIE_REGION     → OpsGenieAlerter region (us|eu)
        SPANFORGE_ALERT_VICTOROPS_URL       → VictorOpsAlerter
        SPANFORGE_ALERT_WEBHOOK_URL         → WebhookAlerter
        SPANFORGE_ALERT_WEBHOOK_SECRET      → WebhookAlerter HMAC secret
        SPANFORGE_ALERT_DEDUP_SECONDS       → dedup_window_seconds (default: 300)
        SPANFORGE_ALERT_RATE_LIMIT          → rate_limit_per_minute (default: 60)
        SPANFORGE_ALERT_ESCALATION_WAIT     → escalation_wait_seconds (default: 900)
    """

    def __init__(
        self,
        config: SFClientConfig,
        sinks: list[_Alerter] | None = None,
        *,
        dedup_window_seconds: float | None = None,
        rate_limit_per_minute: int | None = None,
        escalation_wait_seconds: float | None = None,
        escalation_sinks: list[str] | None = None,
    ) -> None:
        super().__init__(config, "alert")
        self._lock = threading.RLock()

        # Configuration
        _dedup_raw = os.environ.get("SPANFORGE_ALERT_DEDUP_SECONDS", "")
        self._dedup_window: float = (
            dedup_window_seconds
            if dedup_window_seconds is not None
            else (float(_dedup_raw) if _dedup_raw else _DEDUP_WINDOW_DEFAULT)
        )
        _rl_raw = os.environ.get("SPANFORGE_ALERT_RATE_LIMIT", "")
        self._rate_limit: int = (
            rate_limit_per_minute
            if rate_limit_per_minute is not None
            else (int(_rl_raw) if _rl_raw else _RATE_LIMIT_PER_MINUTE)
        )
        _esc_raw = os.environ.get("SPANFORGE_ALERT_ESCALATION_WAIT", "")
        self._escalation_wait: float = (
            escalation_wait_seconds
            if escalation_wait_seconds is not None
            else (float(_esc_raw) if _esc_raw else _ESCALATION_WAIT_DEFAULT)
        )
        self._escalation_sink_names: list[str] = escalation_sinks or []

        # Topic registry — pre-populate known topics
        self._topic_registry: dict[str, TopicRegistration] = {}
        for t in KNOWN_TOPICS:
            sev = "critical" if t.endswith((".red", ".critical", ".failed")) else "warning"
            self._topic_registry[t] = TopicRegistration(
                topic=t,
                description=f"Built-in topic: {t}",
                default_severity=sev,
            )

        # Sinks — env-var discovery + constructor-supplied
        self._sinks: list[_SinkWrapper] = []
        self._build_sinks_from_env()
        for s in sinks or []:
            name = type(s).__name__.lower()
            self._sinks.append(_SinkWrapper(alerter=s, name=name))

        # Rate limiter (per project_id)
        self._rate_limiter: _SlidingWindowRateLimiter = _SlidingWindowRateLimiter(
            limit=self._rate_limit,
            window_seconds=60.0,
        )

        # Deduplication state
        self._dedup: dict[tuple[str, str], float] = {}

        # Alert grouping buffer
        self._group_buffers: dict[tuple[str, str], list[_QueueItem]] = {}
        self._group_timers: dict[tuple[str, str], threading.Timer] = {}

        # Maintenance windows
        self._maintenance_windows: list[MaintenanceWindow] = []

        # Escalation tracking
        self._escalation_timers: dict[str, threading.Timer] = {}
        self._pending_escalation: dict[str, _QueueItem] = {}

        # Alert history (bounded)
        self._history: list[AlertRecord] = []

        # Session stats
        self._publish_count: int = 0
        self._suppress_count: int = 0

        # Async dispatch queue + worker thread
        self._queue: queue.Queue[_QueueItem | None] = queue.Queue(maxsize=_QUEUE_MAX)
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="sf-alert-worker",
            daemon=True,
        )
        self._worker.start()

    # ------------------------------------------------------------------
    # SFServiceClient abstract method
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Env-var sink discovery
    # ------------------------------------------------------------------

    def _build_sinks_from_env(self) -> None:
        """Auto-discover sinks from ``SPANFORGE_ALERT_*`` environment variables."""
        # Slack
        slack_url = os.environ.get("SPANFORGE_ALERT_SLACK_WEBHOOK", "")
        if slack_url:
            try:
                from spanforge.alerts import SlackAlerter  # noqa: PLC0415
                self._sinks.append(_SinkWrapper(alerter=SlackAlerter(webhook_url=slack_url), name="slack"))
            except Exception:  # noqa: BLE001
                _log.warning("Failed to create SlackAlerter from env")

        # Teams
        teams_url = os.environ.get("SPANFORGE_ALERT_TEAMS_WEBHOOK", "")
        if teams_url:
            self._sinks.append(
                _SinkWrapper(alerter=TeamsAdaptiveCardAlerter(webhook_url=teams_url), name="teams"),
            )

        # PagerDuty
        pd_key = os.environ.get("SPANFORGE_ALERT_PAGERDUTY_KEY", "")
        if pd_key:
            try:
                from spanforge.alerts import PagerDutyAlerter  # noqa: PLC0415
                self._sinks.append(
                    _SinkWrapper(alerter=PagerDutyAlerter(integration_key=pd_key), name="pagerduty"),
                )
            except Exception:  # noqa: BLE001
                _log.warning("Failed to create PagerDutyAlerter from env")

        # OpsGenie
        og_key = os.environ.get("SPANFORGE_ALERT_OPSGENIE_KEY", "")
        if og_key:
            region = os.environ.get("SPANFORGE_ALERT_OPSGENIE_REGION", "us")
            self._sinks.append(
                _SinkWrapper(alerter=OpsGenieAlerter(api_key=og_key, region=region), name="opsgenie"),
            )

        # VictorOps
        vo_url = os.environ.get("SPANFORGE_ALERT_VICTOROPS_URL", "")
        if vo_url:
            self._sinks.append(
                _SinkWrapper(alerter=VictorOpsAlerter(rest_endpoint_url=vo_url), name="victorops"),
            )

        # Generic webhook
        wh_url = os.environ.get("SPANFORGE_ALERT_WEBHOOK_URL", "")
        if wh_url:
            wh_secret = os.environ.get("SPANFORGE_ALERT_WEBHOOK_SECRET", "")
            self._sinks.append(
                _SinkWrapper(alerter=WebhookAlerter(url=wh_url, secret=wh_secret), name="webhook"),
            )

    # ------------------------------------------------------------------
    # Public API — topic registry (ALT-003)
    # ------------------------------------------------------------------

    def register_topic(
        self,
        topic: str,
        description: str,
        default_severity: str = "warning",
        *,
        runbook_url: str | None = None,
        dedup_window_seconds: float | None = None,
    ) -> None:
        """Register a custom topic.

        Args:
            topic:               Dot-separated topic string.
            description:         Human-readable purpose.
            default_severity:    Default severity (``"info"``, ``"warning"``,
                                 ``"high"``, or ``"critical"``).
            runbook_url:         Optional URL to the runbook for this topic.
            dedup_window_seconds: Per-topic dedup window override.
        """
        reg = TopicRegistration(
            topic=topic,
            description=description,
            default_severity=default_severity,
            runbook_url=runbook_url,
            dedup_window_seconds=dedup_window_seconds,
        )
        with self._lock:
            self._topic_registry[topic] = reg

    # ------------------------------------------------------------------
    # Public API — maintenance windows (ALT-012)
    # ------------------------------------------------------------------

    def set_maintenance_window(
        self, project_id: str, start: datetime, end: datetime,
    ) -> None:
        """Register a maintenance window during which all alerts for
        *project_id* are suppressed.

        Args:
            project_id: Project whose alerts should be suppressed.
            start:      Window start (UTC-aware recommended).
            end:        Window end (UTC-aware recommended).
        """
        mw = MaintenanceWindow(project_id=project_id, start=start, end=end)
        with self._lock:
            self._maintenance_windows.append(mw)
        self._append_audit_record(
            {
                "event": "maintenance_window_set",
                "project_id": project_id,
                "start": start.isoformat(),
                "end": end.isoformat(),
            },
        )

    def remove_maintenance_windows(self, project_id: str) -> int:
        """Remove all maintenance windows for *project_id*.

        Returns the number of windows removed.
        """
        with self._lock:
            before = len(self._maintenance_windows)
            self._maintenance_windows = [
                mw for mw in self._maintenance_windows if mw.project_id != project_id
            ]
            return before - len(self._maintenance_windows)

    # ------------------------------------------------------------------
    # Public API — publish (ALT-001, ALT-050)
    # ------------------------------------------------------------------

    def publish(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        severity: str | None = None,
        project_id: str | None = None,
    ) -> PublishResult:
        """Publish an alert to the given *topic*.

        Steps:
        1. Resolve topic registration (warn on unknown topics).
        2. Resolve effective severity.
        3. Check maintenance window suppression.
        4. Check per-project rate limit.
        5. Check deduplication window.
        6. Enqueue for background dispatch.

        Args:
            topic:      Dot-separated topic identifier.
            payload:    Arbitrary payload dict.  **Never include raw secrets.**
            severity:   Explicit severity override.  Defaults to the topic's
                        ``default_severity``.
            project_id: Project scope.  Defaults to ``config.project_id``.

        Returns:
            :class:`~spanforge.sdk._types.PublishResult` with ``alert_id``,
            ``routed_to``, and ``suppressed``.

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFAlertRateLimitedError` when the
                per-project rate limit is exceeded **and** the client is in
                strict mode (``local_fallback_enabled=False``).
        """
        pid = project_id or self._config.project_id or ""
        alert_id = str(uuid.uuid4())

        with self._lock:
            self._publish_count += 1

            # Topic lookup
            reg = self._topic_registry.get(topic)
            if reg is None:
                _log.warning(
                    "sf-alert: unknown topic %r — routing to catch-all. "
                    "Register custom topics with register_topic().",
                    topic,
                )
            resolved_severity = severity or (reg.default_severity if reg else "warning")
            runbook_url = reg.runbook_url if reg else None
            per_topic_dedup = reg.dedup_window_seconds if reg else None
            effective_dedup = per_topic_dedup if per_topic_dedup is not None else self._dedup_window

            # Maintenance window check
            if self._is_maintenance_window(pid):
                self._suppress_count += 1
                _log.debug("sf-alert: suppressed %r — maintenance window for project %r", topic, pid)
                return PublishResult(alert_id=alert_id, routed_to=[], suppressed=True)

            # Rate limit check
            if not self._rate_limiter.record(pid or "__global__"):
                self._suppress_count += 1
                _log.warning(
                    "sf-alert: rate limit %d/min exceeded for project %r; alert suppressed",
                    self._rate_limit,
                    pid,
                )
                if not self._config.local_fallback_enabled:
                    raise SFAlertRateLimitedError(pid, self._rate_limit)
                return PublishResult(alert_id=alert_id, routed_to=[], suppressed=True)

            # Deduplication check
            dedup_key = (topic, pid)
            last_ts = self._dedup.get(dedup_key, 0.0)
            if time.monotonic() - last_ts < effective_dedup:
                self._suppress_count += 1
                _log.debug("sf-alert: suppressed %r (dedup window %.0fs)", topic, effective_dedup)
                return PublishResult(alert_id=alert_id, routed_to=[], suppressed=True)
            self._dedup[dedup_key] = time.monotonic()

        # Build summary message
        title = f"[{resolved_severity.upper()}] {topic}"
        message = _build_message(topic, payload, runbook_url)
        item = _QueueItem(
            alert_id=alert_id,
            topic=topic,
            title=title,
            message=message,
            severity=resolved_severity,
            project_id=pid,
            payload=payload,
            runbook_url=runbook_url,
        )

        # Alert grouping check (ALT-011)
        # The FIRST alert in a group is dispatched immediately.
        # Subsequent alerts sharing the same (topic_prefix, project_id) within
        # _GROUP_WINDOW_SECS are coalesced and flushed as one notification.
        group_key = (_topic_prefix(topic), pid)
        with self._lock:
            if group_key in self._group_buffers:
                # Add to existing group buffer; dispatch deferred until flush
                self._group_buffers[group_key].append(item)
                _log.debug("sf-alert: grouped %r into existing group %r", topic, group_key)
                return PublishResult(alert_id=alert_id, routed_to=[], suppressed=False)
            # Start a new group window; the first item is enqueued immediately
            self._group_buffers[group_key] = []  # buffer for SUBSEQUENT items only
            timer = threading.Timer(
                _GROUP_WINDOW_SECS,
                self._flush_group,
                args=(group_key,),
            )
            timer.daemon = True
            self._group_timers[group_key] = timer
            timer.start()

        # Enqueue the first item for immediate dispatch
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(item)
            except queue.Full:
                pass
            _log.warning("sf-alert: alert queue full (%d items), oldest item dropped", _QUEUE_MAX)

        return PublishResult(alert_id=alert_id, routed_to=[], suppressed=False)

    # ------------------------------------------------------------------
    # Public API — acknowledge (ALT-020)
    # ------------------------------------------------------------------

    def acknowledge(self, alert_id: str) -> bool:
        """Acknowledge a CRITICAL alert, cancelling its escalation timer.

        Args:
            alert_id: The UUID returned by :meth:`publish`.

        Returns:
            ``True`` if a pending escalation timer was found and cancelled.
        """
        with self._lock:
            timer = self._escalation_timers.pop(alert_id, None)
            self._pending_escalation.pop(alert_id, None)
        if timer is not None:
            timer.cancel()
            _log.debug("sf-alert: escalation cancelled for alert %s", alert_id)
            # Update status in history
            self._update_history_status(alert_id, "acknowledged")
            return True
        return False

    # ------------------------------------------------------------------
    # Public API — alert history (ALT-042)
    # ------------------------------------------------------------------

    def get_alert_history(
        self,
        *,
        project_id: str | None = None,
        topic: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[AlertRecord]:
        """Query the in-memory alert history.

        Args:
            project_id: Filter by project.
            topic:      Filter by topic.
            from_dt:    Include alerts at or after this UTC datetime.
            to_dt:      Include alerts at or before this UTC datetime.
            status:     Filter by status: ``"open"``, ``"acknowledged"``,
                        or ``"resolved"``.
            limit:      Maximum number of results (default: 100).

        Returns:
            Most-recent-first list of matching :class:`~spanforge.sdk._types.AlertRecord`.
        """
        with self._lock:
            results = list(self._history)

        # Filter
        if project_id:
            results = [r for r in results if r.project_id == project_id]
        if topic:
            results = [r for r in results if r.topic == topic]
        if status:
            results = [r for r in results if r.status == status]
        if from_dt:
            from_str = from_dt.isoformat()
            results = [r for r in results if r.timestamp >= from_str]
        if to_dt:
            to_str = to_dt.isoformat()
            results = [r for r in results if r.timestamp <= to_str]

        # Most recent first
        results.sort(key=lambda r: r.timestamp, reverse=True)
        return results[:limit]

    # ------------------------------------------------------------------
    # Public API — status / health
    # ------------------------------------------------------------------

    def get_status(self) -> AlertStatusInfo:
        """Return health and session statistics."""
        with self._lock:
            publish_count = self._publish_count
            suppress_count = self._suppress_count
            now = datetime.now(timezone.utc)
            active_mw = sum(
                1 for mw in self._maintenance_windows if mw.start <= now <= mw.end
            )
            registered = len(self._topic_registry)

        queue_depth = self._queue.qsize()
        all_healthy = all(not w.cb.is_open() for w in self._sinks)
        status = "ok" if all_healthy else "degraded"
        return AlertStatusInfo(
            status=status,
            publish_count=publish_count,
            suppress_count=suppress_count,
            queue_depth=queue_depth,
            registered_topics=registered,
            active_maintenance_windows=active_mw,
            healthy=all_healthy,
        )

    @property
    def healthy(self) -> bool:
        """``True`` when no sink circuit breaker is open."""
        return all(not w.cb.is_open() for w in self._sinks)

    # ------------------------------------------------------------------
    # Public API — sink management
    # ------------------------------------------------------------------

    def add_sink(self, alerter: _Alerter, name: str | None = None) -> None:
        """Add a sink at runtime.

        Args:
            alerter: Sink instance with a ``send()`` method.
            name:    Optional display name (defaults to class name).
        """
        sink_name = name or type(alerter).__name__.lower()
        with self._lock:
            self._sinks.append(_SinkWrapper(alerter=alerter, name=sink_name))

    # ------------------------------------------------------------------
    # Graceful shutdown
    # ------------------------------------------------------------------

    def shutdown(self, timeout: float = 5.0) -> None:
        """Drain the queue and stop the worker thread.

        Args:
            timeout: Seconds to wait for the worker to finish (default: 5.0).
        """
        # Cancel all escalation timers
        with self._lock:
            timers = list(self._escalation_timers.values())
            self._escalation_timers.clear()
        for t in timers:
            t.cancel()
        # Flush all groups
        with self._lock:
            group_keys = list(self._group_buffers.keys())
        for gk in group_keys:
            self._flush_group(gk)
        # Signal worker to stop
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._worker.join(timeout=timeout)

    # ------------------------------------------------------------------
    # Internal — group flushing
    # ------------------------------------------------------------------

    def _flush_group(self, group_key: tuple[str, str]) -> None:
        """Flush a group window: coalesce buffered secondary items and enqueue one dispatch task."""
        with self._lock:
            items = self._group_buffers.pop(group_key, [])
            timer = self._group_timers.pop(group_key, None)
        if timer is not None:
            timer.cancel()
        if not items:
            # No secondary alerts buffered; the first item was already dispatched
            return

        # Coalesce: use the first item as the representative
        first = items[0]
        if len(items) > 1:
            extra_topics = ", ".join(i.topic for i in items[1:])
            first = _QueueItem(
                alert_id=first.alert_id,
                topic=first.topic,
                title=first.title,
                message=f"{first.message}\n(+{len(items) - 1} grouped: {extra_topics})",
                severity=max(
                    (i.severity for i in items),
                    key=lambda s: _SEVERITY_RANK.get(s, 0),
                ),
                project_id=first.project_id,
                payload=first.payload,
                runbook_url=first.runbook_url,
            )

        try:
            self._queue.put_nowait(first)
        except queue.Full:
            # Drop oldest
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(first)
            except queue.Full:
                pass
            _log.warning("sf-alert: alert queue full (%d items), oldest item dropped", _QUEUE_MAX)

    # ------------------------------------------------------------------
    # Internal — worker loop (ALT-050)
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        """Background thread: drain queue and dispatch to sinks."""
        while True:
            try:
                item = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            if item is None:
                # Shutdown sentinel
                break
            try:
                self._dispatch(item)
            except Exception:  # noqa: BLE001
                _log.exception("sf-alert: unhandled error dispatching %r", item.topic)
            finally:
                self._queue.task_done()

    def _dispatch(self, item: _QueueItem) -> None:
        """Dispatch an alert to all configured sinks."""
        with self._lock:
            sinks = list(self._sinks)
            escalation_names = list(self._escalation_sink_names)

        if item.is_escalation and escalation_names:
            sinks = [s for s in sinks if s.name in escalation_names] or sinks

        extra: dict[str, Any] = {
            "alert_id": item.alert_id,
            "topic": item.topic,
            "project_id": item.project_id,
        }
        if item.runbook_url:
            extra["runbook_url"] = item.runbook_url

        routed_to: list[str] = []
        for sink in sinks:
            ok = sink.dispatch(item.title, item.message, item.severity, extra)
            if ok:
                routed_to.append(sink.name)

        # Record in history
        record = AlertRecord(
            alert_id=item.alert_id,
            topic=item.topic,
            severity=item.severity,
            project_id=item.project_id,
            payload=item.payload,
            sinks_notified=routed_to,
            suppressed=False,
            status="open",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            self._history.append(record)
            if len(self._history) > _HISTORY_MAX:
                self._history = self._history[-_HISTORY_MAX:]

        # Audit log
        self._append_audit_record(
            {
                "event": "alert.published",
                "alert_id": item.alert_id,
                "topic": item.topic,
                "severity": item.severity,
                "project_id": item.project_id,
                "sinks_notified": routed_to,
                "suppressed": False,
            },
        )

        # Schedule escalation for CRITICAL (ALT-020)
        if _SEVERITY_RANK.get(item.severity, 0) >= _SEVERITY_RANK["critical"] and not item.is_escalation:
            self._schedule_escalation(item)

    # ------------------------------------------------------------------
    # Internal — escalation (ALT-020)
    # ------------------------------------------------------------------

    def _schedule_escalation(self, item: _QueueItem) -> None:
        """Start a timer to escalate *item* after :attr:`_escalation_wait` seconds."""
        timer = threading.Timer(
            self._escalation_wait,
            self._fire_escalation,
            args=(item.alert_id,),
        )
        timer.daemon = True
        with self._lock:
            self._escalation_timers[item.alert_id] = timer
            self._pending_escalation[item.alert_id] = item
        timer.start()
        _log.debug(
            "sf-alert: escalation scheduled for %s in %.0fs",
            item.alert_id,
            self._escalation_wait,
        )

    def _fire_escalation(self, alert_id: str) -> None:
        """Escalation timer callback — re-dispatch with ``is_escalation=True``."""
        with self._lock:
            item = self._pending_escalation.pop(alert_id, None)
            self._escalation_timers.pop(alert_id, None)
        if item is None:
            return
        escalated = _QueueItem(
            alert_id=item.alert_id,
            topic=item.topic,
            title=f"[ESCALATED] {item.title}",
            message=f"[AUTO-ESCALATED after {self._escalation_wait:.0f}s]\n{item.message}",
            severity=item.severity,
            project_id=item.project_id,
            payload=item.payload,
            runbook_url=item.runbook_url,
            is_escalation=True,
        )
        _log.warning(
            "sf-alert: CRITICAL alert %r not acknowledged in %.0fs — escalating",
            alert_id,
            self._escalation_wait,
        )
        try:
            self._queue.put_nowait(escalated)
        except queue.Full:
            _log.warning("sf-alert: queue full during escalation; escalated alert dropped")

    # ------------------------------------------------------------------
    # Internal — audit log (ALT-053)
    # ------------------------------------------------------------------

    def _append_audit_record(self, record: dict[str, Any]) -> None:
        """Append *record* to sf-audit schema ``spanforge.alert.v1`` (best-effort)."""
        try:
            from spanforge.sdk import sf_audit  # noqa: PLC0415
            sf_audit.append(record, "spanforge.alert.v1")
        except Exception:  # noqa: BLE001
            _log.debug("sf-alert: audit append skipped (sf_audit unavailable or error)")

    # ------------------------------------------------------------------
    # Internal — helper predicates
    # ------------------------------------------------------------------

    def _is_maintenance_window(self, project_id: str) -> bool:
        """Return ``True`` when *project_id* is currently in a maintenance window.

        Must be called with ``self._lock`` held **or** within a context that
        doesn't need the lock (the caller holds it).
        """
        now = datetime.now(timezone.utc)
        for mw in self._maintenance_windows:
            if mw.project_id == project_id and mw.start <= now <= mw.end:
                return True
        return False

    def _update_history_status(self, alert_id: str, status: str) -> None:
        """Update the status field of a history record (best-effort)."""
        with self._lock:
            for i, rec in enumerate(self._history):
                if rec.alert_id == alert_id:
                    # Dataclass is frozen — replace the record
                    self._history[i] = AlertRecord(
                        alert_id=rec.alert_id,
                        topic=rec.topic,
                        severity=rec.severity,
                        project_id=rec.project_id,
                        payload=rec.payload,
                        sinks_notified=rec.sinks_notified,
                        suppressed=rec.suppressed,
                        status=status,
                        timestamp=rec.timestamp,
                    )
                    break

    # ------------------------------------------------------------------
    # SFServiceClient — abstract requirement
    # ------------------------------------------------------------------

    def _request(  # noqa: PLR0913
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Not used directly; alert routing is purely outbound push."""
        raise NotImplementedError("SFAlertClient does not expose a request interface")


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _topic_prefix(topic: str) -> str:
    """Return everything before the last dot in *topic*."""
    idx = topic.rfind(".")
    return topic[:idx] if idx != -1 else topic


def _build_message(topic: str, payload: dict[str, Any], runbook_url: str | None) -> str:
    """Construct a human-readable alert message."""
    lines: list[str] = [f"Topic: {topic}"]
    for key, value in payload.items():
        lines.append(f"  {key}: {value}")
    if runbook_url:
        lines.append(f"Runbook: {runbook_url}")
    return "\n".join(lines)
