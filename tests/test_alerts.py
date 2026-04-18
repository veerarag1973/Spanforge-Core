"""Tests for spanforge.alerts — AlertManager, SlackAlerter, TeamsAlerter,
PagerDutyAlerter, EmailAlerter, and AlertConfig.

All network / SMTP calls are mocked so no real connections are made.
"""

from __future__ import annotations

import smtplib
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from spanforge.alerts import (
    AlertConfig,
    Alerter,
    AlertManager,
    EmailAlerter,
    PagerDutyAlerter,
    SlackAlerter,
    TeamsAlerter,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_urlopen_ctx(status: int = 200) -> MagicMock:
    """Return a context-manager mock that simulates a successful urllib response."""
    resp = MagicMock()
    resp.status = status
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=resp)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


# ---------------------------------------------------------------------------
# Alerter base class
# ---------------------------------------------------------------------------


class TestAlerterBase:
    def test_send_raises_not_implemented(self) -> None:
        a = Alerter()
        with pytest.raises(NotImplementedError):
            a.send("title", "message")


# ---------------------------------------------------------------------------
# SlackAlerter
# ---------------------------------------------------------------------------


class TestSlackAlerter:
    def test_send_posts_json(self) -> None:
        alerter = SlackAlerter(webhook_url="https://hooks.slack.example/T/B/x")
        ctx = _make_urlopen_ctx(200)
        with patch("urllib.request.urlopen", return_value=ctx) as mock_open:
            alerter.send("Budget exceeded", "Spent $200", severity="critical")
        assert mock_open.called
        req = mock_open.call_args[0][0]
        assert req.get_header("Content-type") == "application/json"
        # "critical" severity maps to the colour #ff0000 in the Slack payload
        assert b"#ff0000" in req.data

    def test_send_includes_channel_when_set(self) -> None:
        alerter = SlackAlerter(
            webhook_url="https://hooks.slack.example/T/B/x",
            channel="#ops-alerts",
        )
        ctx = _make_urlopen_ctx(200)
        with patch("urllib.request.urlopen", return_value=ctx) as mock_open:
            alerter.send("title", "msg")
        req = mock_open.call_args[0][0]
        assert b"#ops-alerts" in req.data

    def test_send_with_unexpected_status_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        alerter = SlackAlerter(webhook_url="https://hooks.slack.example/T/B/x")
        ctx = _make_urlopen_ctx(500)
        with patch("urllib.request.urlopen", return_value=ctx):
            import logging
            with caplog.at_level(logging.WARNING, logger="spanforge.alerts"):
                alerter.send("t", "m")
        assert any("unexpected status" in r.message for r in caplog.records)

    def test_send_swallows_url_error(self) -> None:
        alerter = SlackAlerter(webhook_url="https://hooks.slack.example/T/B/x")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            alerter.send("t", "m")  # must not propagate

    def test_severities_produce_different_colours(self) -> None:
        alerter = SlackAlerter(webhook_url="https://hooks.slack.example/T/B/x")
        colours = {}
        for sev in ("info", "warning", "critical"):
            ctx = _make_urlopen_ctx(200)
            with patch("urllib.request.urlopen", return_value=ctx) as mock_open:
                alerter.send("t", "m", severity=sev)
            req = mock_open.call_args[0][0]
            colours[sev] = req.data
        assert colours["info"] != colours["critical"]

    def test_default_severity_unknown_key(self) -> None:
        """An unknown severity should still send (defaults to green)."""
        alerter = SlackAlerter(webhook_url="https://hooks.slack.example/T/B/x")
        ctx = _make_urlopen_ctx(200)
        with patch("urllib.request.urlopen", return_value=ctx) as mock_open:
            alerter.send("t", "m", severity="unknown_level")
        assert mock_open.called


# ---------------------------------------------------------------------------
# TeamsAlerter
# ---------------------------------------------------------------------------


class TestTeamsAlerter:
    def test_send_posts_adaptive_card(self) -> None:
        alerter = TeamsAlerter(webhook_url="https://teams.example.com/webhook")
        ctx = _make_urlopen_ctx(200)
        with patch("urllib.request.urlopen", return_value=ctx) as mock_open:
            alerter.send("Alert", "Something happened", severity="warning")
        req = mock_open.call_args[0][0]
        assert b"AdaptiveCard" in req.data

    def test_send_swallows_url_error(self) -> None:
        alerter = TeamsAlerter(webhook_url="https://teams.example.com/webhook")
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("conn")):
            alerter.send("t", "m")  # must not propagate

    def test_unexpected_status_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        alerter = TeamsAlerter(webhook_url="https://teams.example.com/webhook")
        ctx = _make_urlopen_ctx(400)
        import logging
        with patch("urllib.request.urlopen", return_value=ctx):
            with caplog.at_level(logging.WARNING, logger="spanforge.alerts"):
                alerter.send("t", "m")
        assert any("unexpected status" in r.message for r in caplog.records)

    def test_severity_colours(self) -> None:
        alerter = TeamsAlerter(webhook_url="https://teams.example.com/webhook")
        for sev in ("info", "warning", "critical", "unknown"):
            ctx = _make_urlopen_ctx(200)
            with patch("urllib.request.urlopen", return_value=ctx) as mock_open:
                alerter.send("t", "m", severity=sev)
            assert mock_open.called


# ---------------------------------------------------------------------------
# PagerDutyAlerter
# ---------------------------------------------------------------------------


class TestPagerDutyAlerter:
    def test_send_posts_to_pagerduty_url(self) -> None:
        alerter = PagerDutyAlerter(integration_key="a" * 32)
        ctx = _make_urlopen_ctx(202)
        with patch("urllib.request.urlopen", return_value=ctx) as mock_open:
            alerter.send("Incident title", "Details here", severity="critical")
        req = mock_open.call_args[0][0]
        assert "pagerduty.com" in req.full_url
        assert b"trigger" in req.data

    def test_integration_key_not_in_repr(self) -> None:
        key = "secret_key_value_abc123"
        alerter = PagerDutyAlerter(integration_key=key)
        assert key not in repr(alerter)

    def test_send_swallows_url_error(self) -> None:
        alerter = PagerDutyAlerter(integration_key="k" * 32)
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            alerter.send("t", "m")

    def test_unexpected_status_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        alerter = PagerDutyAlerter(integration_key="k" * 32)
        ctx = _make_urlopen_ctx(500)
        import logging
        with patch("urllib.request.urlopen", return_value=ctx):
            with caplog.at_level(logging.WARNING, logger="spanforge.alerts"):
                alerter.send("t", "m")
        assert any("unexpected status" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# EmailAlerter
# ---------------------------------------------------------------------------


class TestEmailAlerter:
    def test_send_sends_email(self) -> None:
        alerter = EmailAlerter(
            smtp_host="smtp.example.com",
            smtp_port=587,
            from_address="spanforge@example.com",
            to_addresses=["ops@example.com"],
            username="user",
            password="pass",
            use_tls=True,
        )
        smtp_mock = MagicMock()
        smtp_mock.__enter__ = MagicMock(return_value=smtp_mock)
        smtp_mock.__exit__ = MagicMock(return_value=False)
        with patch("smtplib.SMTP", return_value=smtp_mock):
            alerter.send("Alert title", "Alert body", severity="warning")
        smtp_mock.starttls.assert_called_once()
        smtp_mock.login.assert_called_once_with("user", "pass")
        smtp_mock.sendmail.assert_called_once()

    def test_send_no_tls_skips_starttls(self) -> None:
        alerter = EmailAlerter(
            smtp_host="smtp.example.com",
            to_addresses=["ops@example.com"],
            use_tls=False,
        )
        smtp_mock = MagicMock()
        smtp_mock.__enter__ = MagicMock(return_value=smtp_mock)
        smtp_mock.__exit__ = MagicMock(return_value=False)
        with patch("smtplib.SMTP", return_value=smtp_mock):
            alerter.send("t", "m")
        smtp_mock.starttls.assert_not_called()

    def test_send_no_credentials_skips_login(self) -> None:
        alerter = EmailAlerter(
            smtp_host="smtp.example.com",
            to_addresses=["ops@example.com"],
            use_tls=False,
        )
        smtp_mock = MagicMock()
        smtp_mock.__enter__ = MagicMock(return_value=smtp_mock)
        smtp_mock.__exit__ = MagicMock(return_value=False)
        with patch("smtplib.SMTP", return_value=smtp_mock):
            alerter.send("t", "m")
        smtp_mock.login.assert_not_called()

    def test_send_no_recipients_logs_and_skips(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        alerter = EmailAlerter(smtp_host="smtp.example.com", to_addresses=[])
        import logging
        with caplog.at_level(logging.WARNING, logger="spanforge.alerts"):
            alerter.send("t", "m")
        assert any("no recipients" in r.message for r in caplog.records)

    def test_send_swallows_smtp_exception(self) -> None:
        alerter = EmailAlerter(
            smtp_host="smtp.example.com",
            to_addresses=["ops@example.com"],
        )
        with patch("smtplib.SMTP", side_effect=smtplib.SMTPConnectError(421, "busy")):
            alerter.send("t", "m")  # must not propagate

    def test_send_swallows_os_error(self) -> None:
        alerter = EmailAlerter(
            smtp_host="smtp.example.com",
            to_addresses=["ops@example.com"],
        )
        with patch("smtplib.SMTP", side_effect=OSError("connection refused")):
            alerter.send("t", "m")  # must not propagate


# ---------------------------------------------------------------------------
# AlertConfig
# ---------------------------------------------------------------------------


class TestAlertConfig:
    def test_defaults(self) -> None:
        cfg = AlertConfig()
        assert cfg.slack_webhook_url is None
        assert cfg.teams_webhook_url is None
        assert cfg.cooldown_seconds == 300

    def test_from_env_reads_all_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_ALERT_SLACK_WEBHOOK", "https://hooks.slack.example/x")
        monkeypatch.setenv("SPANFORGE_ALERT_TEAMS_WEBHOOK", "https://teams.example.com/w")
        monkeypatch.setenv("SPANFORGE_ALERT_PAGERDUTY_KEY", "pdkey123")
        monkeypatch.setenv("SPANFORGE_ALERT_SMTP_HOST", "smtp.example.com")
        monkeypatch.setenv("SPANFORGE_ALERT_SMTP_PORT", "465")
        monkeypatch.setenv("SPANFORGE_ALERT_EMAIL_FROM", "noreply@example.com")
        monkeypatch.setenv("SPANFORGE_ALERT_EMAIL_TO", "a@example.com,b@example.com")
        monkeypatch.setenv("SPANFORGE_ALERT_EMAIL_USERNAME", "user")
        monkeypatch.setenv("SPANFORGE_ALERT_EMAIL_PASSWORD", "pw")
        monkeypatch.setenv("SPANFORGE_ALERT_COOLDOWN_SECONDS", "60")

        cfg = AlertConfig.from_env()

        assert cfg.slack_webhook_url == "https://hooks.slack.example/x"
        assert cfg.teams_webhook_url == "https://teams.example.com/w"
        assert cfg.pagerduty_integration_key == "pdkey123"
        assert cfg.smtp_host == "smtp.example.com"
        assert cfg.smtp_port == 465
        assert cfg.email_from == "noreply@example.com"
        assert list(cfg.email_to) == ["a@example.com", "b@example.com"]
        assert cfg.email_username == "user"
        assert cfg.email_password == "pw"
        assert cfg.cooldown_seconds == 60

    def test_from_env_defaults_when_missing(self) -> None:
        cfg = AlertConfig.from_env()
        assert cfg.slack_webhook_url is None
        assert cfg.cooldown_seconds == 300
        assert cfg.smtp_port == 587

    def test_from_env_bad_cooldown_defaults_to_300(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SPANFORGE_ALERT_COOLDOWN_SECONDS", "not_a_number")
        cfg = AlertConfig.from_env()
        assert cfg.cooldown_seconds == 300

    def test_from_env_bad_smtp_port_defaults_to_587(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SPANFORGE_ALERT_SMTP_PORT", "not_a_number")
        cfg = AlertConfig.from_env()
        assert cfg.smtp_port == 587

    def test_build_manager_no_alerters_when_empty(self) -> None:
        cfg = AlertConfig()
        manager = cfg.build_manager()
        assert isinstance(manager, AlertManager)
        # No alerters configured → fire returns False
        assert manager.fire("k", "m") is False

    def test_build_manager_creates_slack_alerter(self) -> None:
        cfg = AlertConfig(slack_webhook_url="https://hooks.slack.example/x")
        manager = cfg.build_manager()
        assert any(isinstance(a, SlackAlerter) for a in manager._alerters)

    def test_build_manager_creates_teams_alerter(self) -> None:
        cfg = AlertConfig(teams_webhook_url="https://teams.example.com/w")
        manager = cfg.build_manager()
        assert any(isinstance(a, TeamsAlerter) for a in manager._alerters)

    def test_build_manager_creates_pagerduty_alerter(self) -> None:
        cfg = AlertConfig(pagerduty_integration_key="k" * 32)
        manager = cfg.build_manager()
        assert any(isinstance(a, PagerDutyAlerter) for a in manager._alerters)

    def test_build_manager_creates_email_alerter_when_smtp_and_recipients(self) -> None:
        cfg = AlertConfig(
            smtp_host="smtp.example.com",
            email_to=["ops@example.com"],
        )
        manager = cfg.build_manager()
        assert any(isinstance(a, EmailAlerter) for a in manager._alerters)

    def test_build_manager_skips_email_without_smtp_host(self) -> None:
        cfg = AlertConfig(smtp_host=None, email_to=["ops@example.com"])
        manager = cfg.build_manager()
        assert not any(isinstance(a, EmailAlerter) for a in manager._alerters)

    def test_build_manager_skips_email_without_recipients(self) -> None:
        cfg = AlertConfig(smtp_host="smtp.example.com", email_to=[])
        manager = cfg.build_manager()
        assert not any(isinstance(a, EmailAlerter) for a in manager._alerters)


# ---------------------------------------------------------------------------
# AlertManager
# ---------------------------------------------------------------------------


class TestAlertManager:
    def test_fire_dispatches_to_alerter(self) -> None:
        alerter = MagicMock(spec=Alerter)
        manager = AlertManager(alerters=[alerter], cooldown_seconds=0)
        result = manager.fire("cpu_high", "CPU at 99%", severity="critical")
        assert result is True
        alerter.send.assert_called_once_with("Cpu High", "CPU at 99%", severity="critical")

    def test_fire_uses_alert_key_as_default_title(self) -> None:
        alerter = MagicMock(spec=Alerter)
        manager = AlertManager(alerters=[alerter], cooldown_seconds=0)
        manager.fire("budget_exceeded", "over budget")
        _, call_kwargs = alerter.send.call_args
        # title should be title-cased version of the key
        assert alerter.send.call_args[0][0] == "Budget Exceeded"

    def test_fire_uses_explicit_title(self) -> None:
        alerter = MagicMock(spec=Alerter)
        manager = AlertManager(alerters=[alerter], cooldown_seconds=0)
        manager.fire("key", "msg", title="My Custom Title")
        assert alerter.send.call_args[0][0] == "My Custom Title"

    def test_fire_returns_false_with_no_alerters(self) -> None:
        manager = AlertManager(alerters=[], cooldown_seconds=0)
        assert manager.fire("k", "m") is False

    def test_fire_cooldown_suppresses_second_call(self) -> None:
        alerter = MagicMock(spec=Alerter)
        manager = AlertManager(alerters=[alerter], cooldown_seconds=300)
        first = manager.fire("key", "first message")
        second = manager.fire("key", "second message")
        assert first is True
        assert second is False
        alerter.send.assert_called_once()  # only one call despite two fires

    def test_fire_cooldown_allows_different_keys(self) -> None:
        alerter = MagicMock(spec=Alerter)
        manager = AlertManager(alerters=[alerter], cooldown_seconds=300)
        r1 = manager.fire("key_a", "msg a")
        r2 = manager.fire("key_b", "msg b")
        assert r1 is True
        assert r2 is True
        assert alerter.send.call_count == 2

    def test_fire_after_reset_cooldown_sends_again(self) -> None:
        alerter = MagicMock(spec=Alerter)
        manager = AlertManager(alerters=[alerter], cooldown_seconds=300)
        manager.fire("key", "first")
        manager.reset_cooldown("key")
        manager.fire("key", "second")
        assert alerter.send.call_count == 2

    def test_reset_cooldown_noop_for_unknown_key(self) -> None:
        manager = AlertManager()
        manager.reset_cooldown("never_fired_key")  # must not raise

    def test_add_alerter_appends(self) -> None:
        manager = AlertManager()
        a = MagicMock(spec=Alerter)
        manager.add_alerter(a)
        assert a in manager._alerters

    def test_fire_with_zero_cooldown_fires_every_time(self) -> None:
        alerter = MagicMock(spec=Alerter)
        manager = AlertManager(alerters=[alerter], cooldown_seconds=0)
        for _ in range(3):
            manager.fire("key", "msg")
        assert alerter.send.call_count == 3

    def test_alerter_exception_is_caught_and_logged(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An alerter that raises must not propagate and must be logged."""
        bad_alerter = MagicMock(spec=Alerter)
        bad_alerter.send.side_effect = RuntimeError("network gone")
        manager = AlertManager(alerters=[bad_alerter], cooldown_seconds=0)
        import logging
        with caplog.at_level(logging.ERROR, logger="spanforge.alerts"):
            result = manager.fire("k", "m")
        # fire still returns True (the attempt was made)
        assert result is True
        assert any("raised an exception" in r.message for r in caplog.records)

    def test_fire_logs_suppression_when_cooldown_active(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        alerter = MagicMock(spec=Alerter)
        manager = AlertManager(alerters=[alerter], cooldown_seconds=300)
        manager.fire("key", "first")
        import logging
        with caplog.at_level(logging.DEBUG, logger="spanforge.alerts"):
            manager.fire("key", "second")
        assert any("suppressed" in r.message for r in caplog.records)

    def test_thread_safety_concurrent_fires(self) -> None:
        """Concurrent fires must not double-send within the cooldown window."""
        import threading
        alerter = MagicMock(spec=Alerter)
        manager = AlertManager(alerters=[alerter], cooldown_seconds=300)
        results: list[bool] = []
        lock = threading.Lock()

        def _fire() -> None:
            r = manager.fire("concurrent_key", "message")
            with lock:
                results.append(r)

        threads = [threading.Thread(target=_fire) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Exactly one fire should succeed due to cooldown
        assert results.count(True) == 1
        assert alerter.send.call_count == 1
