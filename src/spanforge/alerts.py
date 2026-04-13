"""spanforge.alerts — Built-in alerting integrations for threshold-based notifications.

Supports Slack, Microsoft Teams, PagerDuty, and SMTP email.  All alerters share
a cooldown mechanism to avoid alert storms: the same ``alert_key`` will not fire
again until ``cooldown_seconds`` have elapsed.

Zero required dependencies — each alerter uses only stdlib (``urllib.request``,
``smtplib``, ``json``).

Usage::

    from spanforge.alerts import AlertManager, AlertConfig, SlackAlerter

    manager = AlertManager(
        alerters=[SlackAlerter(webhook_url="https://hooks.slack.com/services/...")],
        cooldown_seconds=300,
    )
    manager.fire("high_error_rate", "Error rate exceeded 5% in the last minute")

Integration with cost budgets::

    from spanforge import configure
    from spanforge.alerts import AlertManager, SlackAlerter

    configure(
        alert_manager=AlertManager(
            alerters=[SlackAlerter(webhook_url=os.environ["SLACK_WEBHOOK"])],
        )
    )
"""

from __future__ import annotations

import json
import logging
import smtplib
import ssl
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from email.mime.text import MIMEText
from typing import Optional, Sequence

__all__ = [
    "Alerter",
    "SlackAlerter",
    "TeamsAlerter",
    "PagerDutyAlerter",
    "EmailAlerter",
    "AlertConfig",
    "AlertManager",
]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Base protocol
# ---------------------------------------------------------------------------


class Alerter:
    """Abstract base class for alerters.  Subclasses must implement :meth:`send`."""

    def send(self, title: str, message: str, severity: str = "warning") -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Concrete alerters
# ---------------------------------------------------------------------------


@dataclass
class SlackAlerter(Alerter):
    """Send a message to a Slack Incoming Webhook.

    Args:
        webhook_url: Slack Incoming Webhook URL.
        channel:     Optional channel override (e.g. ``"#alerts"``).
        username:    Bot display name.
        icon_emoji:  Emoji icon for the bot message.
        timeout:     HTTP request timeout in seconds.
    """

    webhook_url: str
    channel: Optional[str] = None
    username: str = "spanforge"
    icon_emoji: str = ":robot_face:"
    timeout: int = 10

    def send(self, title: str, message: str, severity: str = "warning") -> None:
        colour = {"info": "#36a64f", "warning": "#ffcc00", "critical": "#ff0000"}.get(
            severity, "#36a64f"
        )
        payload: dict = {
            "username": self.username,
            "icon_emoji": self.icon_emoji,
            "attachments": [
                {
                    "color": colour,
                    "title": title,
                    "text": message,
                    "footer": "spanforge",
                }
            ],
        }
        if self.channel:
            payload["channel"] = self.channel

        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            self.webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                if resp.status not in (200, 204):
                    logger.warning("SlackAlerter: unexpected status %s", resp.status)
        except urllib.error.URLError as exc:
            logger.warning("SlackAlerter: request failed: %s", exc)


@dataclass
class TeamsAlerter(Alerter):
    """Send an Adaptive Card to a Microsoft Teams Incoming Webhook.

    Args:
        webhook_url: Teams channel Incoming Webhook URL.
        timeout:     HTTP request timeout in seconds.
    """

    webhook_url: str
    timeout: int = 10

    def send(self, title: str, message: str, severity: str = "warning") -> None:
        colour = {"info": "Good", "warning": "Warning", "critical": "Attention"}.get(
            severity, "Warning"
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
                        "body": [
                            {
                                "type": "TextBlock",
                                "text": title,
                                "weight": "Bolder",
                                "size": "Medium",
                                "color": colour,
                            },
                            {"type": "TextBlock", "text": message, "wrap": True},
                        ],
                    },
                }
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
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                if resp.status not in (200, 202):
                    logger.warning("TeamsAlerter: unexpected status %s", resp.status)
        except urllib.error.URLError as exc:
            logger.warning("TeamsAlerter: request failed: %s", exc)


@dataclass
class PagerDutyAlerter(Alerter):
    """Trigger a PagerDuty incident via the Events API v2.

    Args:
        integration_key: PagerDuty integration/routing key (32-char hex string).
        source:          Source field in the PD event.
        timeout:         HTTP request timeout in seconds.
    """

    integration_key: str = field(repr=False)
    source: str = "spanforge"
    timeout: int = 10

    _PD_URL = "https://events.pagerduty.com/v2/enqueue"

    def send(self, title: str, message: str, severity: str = "warning") -> None:
        pd_severity = {"info": "info", "warning": "warning", "critical": "critical"}.get(
            severity, "warning"
        )
        payload = {
            "routing_key": self.integration_key,
            "event_action": "trigger",
            "payload": {
                "summary": title,
                "source": self.source,
                "severity": pd_severity,
                "custom_details": {"message": message},
            },
        }
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            self._PD_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:  # noqa: S310
                if resp.status not in (200, 202):
                    logger.warning("PagerDutyAlerter: unexpected status %s", resp.status)
        except urllib.error.URLError as exc:
            logger.warning("PagerDutyAlerter: request failed: %s", exc)


@dataclass
class EmailAlerter(Alerter):
    """Send alert emails via SMTP.

    Uses STARTTLS when ``use_tls=True`` (default).  Credentials are taken from
    the ``username`` / ``password`` fields; pass ``None`` for unauthenticated
    SMTP (e.g. internal relay).

    Args:
        smtp_host:    SMTP server hostname.
        smtp_port:    SMTP server port (default: 587 for STARTTLS).
        from_address: Sender address.
        to_addresses: List of recipient addresses.
        subject_prefix: Prefix for the email subject line.
        username:     SMTP auth username; ``None`` skips AUTH.
        password:     SMTP auth password; ``None`` skips AUTH.
        use_tls:      Use STARTTLS (default: True).
        timeout:      Connection timeout in seconds.
    """

    smtp_host: str
    smtp_port: int = 587
    from_address: str = "spanforge@localhost"
    to_addresses: Sequence[str] = field(default_factory=list)
    subject_prefix: str = "[spanforge]"
    username: Optional[str] = field(default=None, repr=False)
    password: Optional[str] = field(default=None, repr=False)
    use_tls: bool = True
    timeout: int = 10

    def send(self, title: str, message: str, severity: str = "warning") -> None:
        if not self.to_addresses:
            logger.warning("EmailAlerter: no recipients configured, skipping")
            return

        subject = f"{self.subject_prefix} [{severity.upper()}] {title}"
        body = f"{title}\n\nSeverity: {severity}\n\n{message}"
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = self.from_address
        msg["To"] = ", ".join(self.to_addresses)

        context = ssl.create_default_context() if self.use_tls else None
        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=self.timeout) as smtp:
                if self.use_tls and context:
                    smtp.starttls(context=context)
                if self.username and self.password:
                    smtp.login(self.username, self.password)
                smtp.sendmail(self.from_address, list(self.to_addresses), msg.as_string())
        except (smtplib.SMTPException, OSError) as exc:
            logger.warning("EmailAlerter: send failed: %s", exc)


# ---------------------------------------------------------------------------
# AlertConfig (thin data container for env-var driven configuration)
# ---------------------------------------------------------------------------


@dataclass
class AlertConfig:
    """Data class holding alert configuration loaded from environment variables.

    Typically accessed via :attr:`spanforge.config.SpanForgeConfig.alert_config`.

    Environment variable mapping::

        SPANFORGE_ALERT_SLACK_WEBHOOK    → slack_webhook_url
        SPANFORGE_ALERT_TEAMS_WEBHOOK    → teams_webhook_url
        SPANFORGE_ALERT_PAGERDUTY_KEY    → pagerduty_integration_key
        SPANFORGE_ALERT_SMTP_HOST        → smtp_host
        SPANFORGE_ALERT_SMTP_PORT        → smtp_port  (int)
        SPANFORGE_ALERT_EMAIL_FROM       → email_from
        SPANFORGE_ALERT_EMAIL_TO         → email_to   (comma-separated)
        SPANFORGE_ALERT_EMAIL_USERNAME   → email_username
        SPANFORGE_ALERT_EMAIL_PASSWORD   → email_password
        SPANFORGE_ALERT_COOLDOWN_SECONDS → cooldown_seconds (int, default 300)
    """

    slack_webhook_url: Optional[str] = None
    teams_webhook_url: Optional[str] = None
    pagerduty_integration_key: Optional[str] = field(default=None, repr=False)
    smtp_host: Optional[str] = None
    smtp_port: int = 587
    email_from: str = "spanforge@localhost"
    email_to: Sequence[str] = field(default_factory=list)
    email_username: Optional[str] = field(default=None, repr=False)
    email_password: Optional[str] = field(default=None, repr=False)
    cooldown_seconds: int = 300

    @classmethod
    def from_env(cls) -> "AlertConfig":
        """Construct an :class:`AlertConfig` by reading ``SPANFORGE_ALERT_*`` env vars."""
        import os

        email_to_raw = os.environ.get("SPANFORGE_ALERT_EMAIL_TO", "")
        email_to = [a.strip() for a in email_to_raw.split(",") if a.strip()]

        cooldown_raw = os.environ.get("SPANFORGE_ALERT_COOLDOWN_SECONDS", "300")
        try:
            cooldown = int(cooldown_raw)
        except ValueError:
            cooldown = 300

        smtp_port_raw = os.environ.get("SPANFORGE_ALERT_SMTP_PORT", "587")
        try:
            smtp_port = int(smtp_port_raw)
        except ValueError:
            smtp_port = 587

        return cls(
            slack_webhook_url=os.environ.get("SPANFORGE_ALERT_SLACK_WEBHOOK"),
            teams_webhook_url=os.environ.get("SPANFORGE_ALERT_TEAMS_WEBHOOK"),
            pagerduty_integration_key=os.environ.get("SPANFORGE_ALERT_PAGERDUTY_KEY"),
            smtp_host=os.environ.get("SPANFORGE_ALERT_SMTP_HOST"),
            smtp_port=smtp_port,
            email_from=os.environ.get("SPANFORGE_ALERT_EMAIL_FROM", "spanforge@localhost"),
            email_to=email_to,
            email_username=os.environ.get("SPANFORGE_ALERT_EMAIL_USERNAME"),
            email_password=os.environ.get("SPANFORGE_ALERT_EMAIL_PASSWORD"),
            cooldown_seconds=cooldown,
        )

    def build_manager(self) -> "AlertManager":
        """Create an :class:`AlertManager` from this config."""
        alerters: list[Alerter] = []
        if self.slack_webhook_url:
            alerters.append(SlackAlerter(webhook_url=self.slack_webhook_url))
        if self.teams_webhook_url:
            alerters.append(TeamsAlerter(webhook_url=self.teams_webhook_url))
        if self.pagerduty_integration_key:
            alerters.append(
                PagerDutyAlerter(integration_key=self.pagerduty_integration_key)
            )
        if self.smtp_host and self.email_to:
            alerters.append(
                EmailAlerter(
                    smtp_host=self.smtp_host,
                    smtp_port=self.smtp_port,
                    from_address=self.email_from,
                    to_addresses=self.email_to,
                    username=self.email_username,
                    password=self.email_password,
                )
            )
        return AlertManager(alerters=alerters, cooldown_seconds=self.cooldown_seconds)


# ---------------------------------------------------------------------------
# AlertManager
# ---------------------------------------------------------------------------


class AlertManager:
    """Dispatch alerts to one or more :class:`Alerter` backends with deduplication.

    The same ``alert_key`` will not trigger again within ``cooldown_seconds``
    (per-key cooldown window), preventing alert storms.

    Thread-safe.

    Args:
        alerters:         List of :class:`Alerter` instances to notify.
        cooldown_seconds: Minimum seconds between repeated firings of the same key.

    Example::

        manager = AlertManager(
            alerters=[SlackAlerter(webhook_url="https://hooks.slack.com/...")],
            cooldown_seconds=300,
        )
        manager.fire("budget_exceeded", "Daily spend exceeded $100", severity="critical")
    """

    def __init__(
        self,
        alerters: Optional[Sequence[Alerter]] = None,
        cooldown_seconds: int = 300,
    ) -> None:
        self._alerters: list[Alerter] = list(alerters or [])
        self._cooldown = cooldown_seconds
        self._last_fired: dict[str, float] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def add_alerter(self, alerter: Alerter) -> None:
        """Append *alerter* to the notification list."""
        with self._lock:
            self._alerters.append(alerter)

    def fire(
        self,
        alert_key: str,
        message: str,
        title: Optional[str] = None,
        severity: str = "warning",
    ) -> bool:
        """Fire an alert if the cooldown window has elapsed.

        Args:
            alert_key: Unique identifier for the alert type (used for deduplication).
            message:   Human-readable alert body.
            title:     Short alert title.  Defaults to *alert_key*.
            severity:  One of ``"info"``, ``"warning"``, ``"critical"``.

        Returns:
            ``True`` if the alert was dispatched; ``False`` if suppressed by cooldown.
        """
        if not self._alerters:
            return False

        now = time.monotonic()
        with self._lock:
            last = self._last_fired.get(alert_key, 0.0)
            if now - last < self._cooldown:
                logger.debug(
                    "AlertManager: suppressed '%s' (cooldown %ss remaining)",
                    alert_key,
                    int(self._cooldown - (now - last)),
                )
                return False
            self._last_fired[alert_key] = now
            active_alerters = list(self._alerters)

        resolved_title = title or alert_key.replace("_", " ").title()
        for alerter in active_alerters:
            try:
                alerter.send(resolved_title, message, severity=severity)
            except Exception:  # noqa: BLE001
                logger.exception("AlertManager: alerter %r raised an exception", alerter)
        return True

    def reset_cooldown(self, alert_key: str) -> None:
        """Reset the cooldown for *alert_key*, allowing it to fire immediately."""
        with self._lock:
            self._last_fired.pop(alert_key, None)
