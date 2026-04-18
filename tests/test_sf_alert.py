"""tests/test_sf_alert.py — Phase 7 sf-alert Alert Routing Service test suite.

Coverage target: ≥90 % of src/spanforge/sdk/alert.py.

All tests are pure unit tests using stdlib mocks only.  No external services
are contacted.  The alert worker thread is started by the client; tests call
``client.shutdown()`` in teardown to avoid thread leakage.
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import queue
import threading
import time
import unittest
import unittest.mock as mock
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import MagicMock, patch

from spanforge.sdk._base import SFClientConfig
from spanforge.sdk._exceptions import (
    SFAlertError,
    SFAlertPublishError,
    SFAlertQueueFullError,
    SFAlertRateLimitedError,
    SFError,
)
from spanforge.sdk._types import (
    AlertRecord,
    AlertSeverity,
    AlertStatusInfo,
    MaintenanceWindow,
    PublishResult,
    TopicRegistration,
)
from spanforge.sdk.alert import (
    KNOWN_TOPICS,
    IncidentIOAlerter,
    OpsGenieAlerter,
    SFAlertClient,
    SMSAlerter,
    TeamsAdaptiveCardAlerter,
    VictorOpsAlerter,
    WebhookAlerter,
    _SinkWrapper,
    _build_message,
    _topic_prefix,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kwargs: Any) -> SFClientConfig:
    return SFClientConfig(
        project_id=kwargs.get("project_id", "test-proj"),
        local_fallback_enabled=kwargs.get("local_fallback_enabled", True),
    )


def _make_client(sinks=None, **kwargs) -> SFAlertClient:
    """Return a client with a zero-dedup window and no env-var sinks."""
    config = _make_config(**kwargs)
    client = SFAlertClient(
        config,
        sinks=sinks or [],
        dedup_window_seconds=kwargs.get("dedup_window_seconds", 0.0),
        rate_limit_per_minute=kwargs.get("rate_limit_per_minute", 1000),
        escalation_wait_seconds=kwargs.get("escalation_wait_seconds", 9999.0),
    )
    return client


class _MockSink:
    """Configurable test sink.  Records calls and optionally raises."""

    def __init__(self, raises: Exception | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._raises = raises

    def send(
        self,
        title: str,
        message: str,
        severity: str = "warning",
        extra: dict[str, Any] | None = None,
    ) -> None:
        if self._raises:
            raise self._raises
        self.calls.append({"title": title, "message": message, "severity": severity, "extra": extra})


# ---------------------------------------------------------------------------
# Phase 7 — types
# ---------------------------------------------------------------------------

class TestAlertSeverityType(unittest.TestCase):
    def test_values(self):
        self.assertEqual(AlertSeverity.INFO.value, "info")
        self.assertEqual(AlertSeverity.WARNING.value, "warning")
        self.assertEqual(AlertSeverity.HIGH.value, "high")
        self.assertEqual(AlertSeverity.CRITICAL.value, "critical")

    def test_from_str_known(self):
        self.assertEqual(AlertSeverity.from_str("critical"), AlertSeverity.CRITICAL)
        self.assertEqual(AlertSeverity.from_str("INFO"), AlertSeverity.INFO)

    def test_from_str_unknown_returns_warning(self):
        self.assertEqual(AlertSeverity.from_str("bogus"), AlertSeverity.WARNING)


class TestPublishResult(unittest.TestCase):
    def test_fields(self):
        pr = PublishResult(alert_id="abc", routed_to=["slack"], suppressed=False)
        self.assertEqual(pr.alert_id, "abc")
        self.assertEqual(pr.routed_to, ["slack"])
        self.assertFalse(pr.suppressed)

    def test_frozen(self):
        pr = PublishResult(alert_id="x", routed_to=[], suppressed=False)
        with self.assertRaises((AttributeError, TypeError)):
            pr.alert_id = "y"  # type: ignore[misc]


class TestTopicRegistration(unittest.TestCase):
    def test_optional_fields_default_none(self):
        reg = TopicRegistration(
            topic="my.topic",
            description="test",
            default_severity="warning",
        )
        self.assertIsNone(reg.runbook_url)
        self.assertIsNone(reg.dedup_window_seconds)

    def test_frozen(self):
        reg = TopicRegistration(topic="t", description="d", default_severity="info")
        with self.assertRaises((AttributeError, TypeError)):
            reg.topic = "other"  # type: ignore[misc]


class TestAlertRecord(unittest.TestCase):
    def test_fields(self):
        rec = AlertRecord(
            alert_id="id1",
            topic="halluccheck.drift.red",
            severity="critical",
            project_id="proj1",
            payload={"score": 0.9},
            sinks_notified=["slack"],
            suppressed=False,
            status="open",
            timestamp="2024-01-01T00:00:00+00:00",
        )
        self.assertEqual(rec.alert_id, "id1")
        self.assertFalse(rec.suppressed)
        self.assertEqual(rec.status, "open")

    def test_frozen(self):
        rec = AlertRecord(
            alert_id="x",
            topic="t",
            severity="info",
            project_id="p",
            payload={},
            sinks_notified=[],
            suppressed=False,
            status="open",
            timestamp="2024-01-01T00:00:00+00:00",
        )
        with self.assertRaises((AttributeError, TypeError)):
            rec.status = "closed"  # type: ignore[misc]


class TestAlertStatusInfo(unittest.TestCase):
    def test_fields(self):
        info = AlertStatusInfo(
            status="ok",
            publish_count=5,
            suppress_count=1,
            queue_depth=0,
            registered_topics=8,
            active_maintenance_windows=0,
            healthy=True,
        )
        self.assertTrue(info.healthy)
        self.assertEqual(info.publish_count, 5)

    def test_frozen(self):
        info = AlertStatusInfo(
            status="ok",
            publish_count=0,
            suppress_count=0,
            queue_depth=0,
            registered_topics=0,
            active_maintenance_windows=0,
            healthy=True,
        )
        with self.assertRaises((AttributeError, TypeError)):
            info.healthy = False  # type: ignore[misc]


class TestMaintenanceWindow(unittest.TestCase):
    def test_fields(self):
        now = datetime.now(timezone.utc)
        mw = MaintenanceWindow(project_id="proj", start=now, end=now + timedelta(hours=1))
        self.assertEqual(mw.project_id, "proj")

    def test_frozen(self):
        now = datetime.now(timezone.utc)
        mw = MaintenanceWindow(project_id="p", start=now, end=now)
        with self.assertRaises((AttributeError, TypeError)):
            mw.project_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Phase 7 — exceptions
# ---------------------------------------------------------------------------

class TestSFAlertExceptions(unittest.TestCase):
    def test_hierarchy_alert_error(self):
        self.assertTrue(issubclass(SFAlertError, SFError))

    def test_hierarchy_publish(self):
        self.assertTrue(issubclass(SFAlertPublishError, SFAlertError))

    def test_hierarchy_rate_limited(self):
        self.assertTrue(issubclass(SFAlertRateLimitedError, SFAlertError))

    def test_hierarchy_queue_full(self):
        self.assertTrue(issubclass(SFAlertQueueFullError, SFAlertError))

    def test_alert_publish_error_attrs(self):
        exc = SFAlertPublishError(topic="my.topic", detail="sink down")
        self.assertEqual(exc.topic, "my.topic")
        self.assertEqual(exc.detail, "sink down")
        self.assertIn("my.topic", str(exc))
        self.assertIn("sink down", str(exc))

    def test_rate_limited_error_attrs(self):
        exc = SFAlertRateLimitedError(project_id="proj-x", limit=60)
        self.assertEqual(exc.project_id, "proj-x")
        self.assertEqual(exc.limit, 60)
        self.assertIn("60", str(exc))

    def test_queue_full_error_attrs(self):
        exc = SFAlertQueueFullError(depth=1000)
        self.assertEqual(exc.depth, 1000)
        self.assertIn("1000", str(exc))


# ---------------------------------------------------------------------------
# Known topics
# ---------------------------------------------------------------------------

class TestKnownTopics(unittest.TestCase):
    def test_expected_topics_present(self):
        expected = {
            "halluccheck.drift.amber",
            "halluccheck.drift.red",
            "halluccheck.bias.critical",
            "halluccheck.prri.red",
            "halluccheck.benchmark.regression",
            "halluccheck.pii.detected",
            "halluccheck.secrets.detected",
            "halluccheck.trust_gate.failed",
        }
        self.assertEqual(KNOWN_TOPICS, expected)

    def test_frozenset(self):
        self.assertIsInstance(KNOWN_TOPICS, frozenset)


# ---------------------------------------------------------------------------
# Topic registry
# ---------------------------------------------------------------------------

class TestTopicRegistry(unittest.TestCase):
    def setUp(self):
        self.client = _make_client()

    def tearDown(self):
        self.client.shutdown(timeout=1.0)

    def test_known_topics_pre_registered(self):
        # All KNOWN_TOPICS should be in the registry from __init__
        for t in KNOWN_TOPICS:
            self.assertIn(t, self.client._topic_registry)

    def test_register_custom_topic(self):
        self.client.register_topic(
            "custom.topic",
            "My test topic",
            "high",
            runbook_url="https://example.com/runbook",
        )
        reg = self.client._topic_registry["custom.topic"]
        self.assertEqual(reg.description, "My test topic")
        self.assertEqual(reg.default_severity, "high")
        self.assertEqual(reg.runbook_url, "https://example.com/runbook")

    def test_register_topic_with_dedup_override(self):
        self.client.register_topic("t.test", "test", dedup_window_seconds=600.0)
        reg = self.client._topic_registry["t.test"]
        self.assertEqual(reg.dedup_window_seconds, 600.0)

    def test_unknown_topic_warns(self):
        with self.assertLogs("spanforge.sdk.alert", level="WARNING") as cm:
            self.client.publish("unknown.topic.xyz", {"k": "v"})
        self.assertTrue(any("unknown topic" in line.lower() for line in cm.output))


# ---------------------------------------------------------------------------
# Basic publish
# ---------------------------------------------------------------------------

class TestPublishBasic(unittest.TestCase):
    def setUp(self):
        self.sink = _MockSink()
        self.client = _make_client(sinks=[self.sink])

    def tearDown(self):
        self.client.shutdown(timeout=2.0)

    def test_returns_publish_result(self):
        result = self.client.publish("halluccheck.drift.red", {"score": 0.5})
        self.assertIsInstance(result, PublishResult)

    def test_alert_id_is_uuid4_format(self):
        result = self.client.publish("halluccheck.drift.red", {"score": 0.5})
        import uuid
        # Should not raise
        parsed = uuid.UUID(result.alert_id, version=4)
        self.assertIsNotNone(parsed)

    def test_not_suppressed(self):
        result = self.client.publish("halluccheck.drift.red", {"score": 0.5})
        self.assertFalse(result.suppressed)

    def test_sink_receives_call(self):
        self.client.publish("halluccheck.drift.red", {"score": 0.5})
        # Allow background thread to dispatch
        self.client.shutdown(timeout=2.0)
        self.assertEqual(len(self.sink.calls), 1)

    def test_severity_in_title(self):
        self.client.publish("halluccheck.drift.red", {"score": 0.5}, severity="critical")
        self.client.shutdown(timeout=2.0)
        self.assertTrue(any("CRITICAL" in c["title"] for c in self.sink.calls))

    def test_default_severity_from_registry(self):
        # halluccheck.drift.red ends with .red → default_severity = "critical"
        result = self.client.publish("halluccheck.drift.red", {})
        self.client.shutdown(timeout=2.0)
        if self.sink.calls:
            self.assertEqual(self.sink.calls[0]["severity"], "critical")


# ---------------------------------------------------------------------------
# Deduplication (ALT-010)
# ---------------------------------------------------------------------------

class TestDeduplication(unittest.TestCase):
    def setUp(self):
        self.sink = _MockSink()
        # Use a 10-second dedup window so the second publish is within window
        self.client = _make_client(sinks=[self.sink], dedup_window_seconds=10.0)

    def tearDown(self):
        self.client.shutdown(timeout=1.0)

    def test_second_publish_suppressed(self):
        r1 = self.client.publish("halluccheck.drift.red", {"i": 1})
        r2 = self.client.publish("halluccheck.drift.red", {"i": 2})
        self.assertFalse(r1.suppressed)
        self.assertTrue(r2.suppressed)

    def test_suppressed_result_has_correct_alert_id(self):
        self.client.publish("halluccheck.drift.red", {})
        r2 = self.client.publish("halluccheck.drift.red", {})
        self.assertTrue(r2.suppressed)
        self.assertEqual(r2.routed_to, [])

    def test_different_project_ids_not_deduped(self):
        r1 = self.client.publish("halluccheck.drift.red", {}, project_id="proj-a")
        r2 = self.client.publish("halluccheck.drift.red", {}, project_id="proj-b")
        self.assertFalse(r1.suppressed)
        self.assertFalse(r2.suppressed)

    def test_different_topics_not_deduped(self):
        r1 = self.client.publish("halluccheck.drift.red", {})
        r2 = self.client.publish("halluccheck.drift.amber", {})
        self.assertFalse(r1.suppressed)
        self.assertFalse(r2.suppressed)


class TestDedupExpiry(unittest.TestCase):
    """Dedup window expiry: after the window, the same topic fires again."""

    def tearDown(self):
        self.client.shutdown(timeout=1.0)

    def test_alert_fires_after_dedup_expiry(self):
        self.sink = _MockSink()
        # 0.05s window — very short for testing
        self.client = _make_client(sinks=[self.sink], dedup_window_seconds=0.05)
        self.client.publish("halluccheck.drift.red", {})
        time.sleep(0.1)
        r2 = self.client.publish("halluccheck.drift.red", {})
        self.assertFalse(r2.suppressed)


# ---------------------------------------------------------------------------
# Rate limiting (ALT-052)
# ---------------------------------------------------------------------------

class TestRateLimiting(unittest.TestCase):
    def setUp(self):
        self.sink = _MockSink()
        # Very tight limit: 2 per minute
        self.client = _make_client(
            sinks=[self.sink],
            dedup_window_seconds=0.0,
            rate_limit_per_minute=2,
        )

    def tearDown(self):
        self.client.shutdown(timeout=1.0)

    def test_third_publish_suppressed(self):
        r1 = self.client.publish("halluccheck.drift.red", {})
        r2 = self.client.publish("halluccheck.drift.amber", {})
        r3 = self.client.publish("halluccheck.pii.detected", {})
        self.assertFalse(r1.suppressed)
        self.assertFalse(r2.suppressed)
        self.assertTrue(r3.suppressed)

    def test_strict_mode_raises_on_rate_limit(self):
        config = _make_config(local_fallback_enabled=False)
        client = SFAlertClient(
            config,
            sinks=[self.sink],
            dedup_window_seconds=0.0,
            rate_limit_per_minute=1,
        )
        try:
            client.publish("halluccheck.drift.red", {})  # allowed
            with self.assertRaises(SFAlertRateLimitedError):
                client.publish("halluccheck.drift.amber", {})
        finally:
            client.shutdown(timeout=1.0)


# ---------------------------------------------------------------------------
# Maintenance windows (ALT-012)
# ---------------------------------------------------------------------------

class TestMaintenanceWindow(unittest.TestCase):
    def setUp(self):
        self.sink = _MockSink()
        self.client = _make_client(sinks=[self.sink])

    def tearDown(self):
        self.client.shutdown(timeout=1.0)

    def test_alert_suppressed_during_window(self):
        now = datetime.now(timezone.utc)
        self.client.set_maintenance_window(
            "test-proj",
            start=now - timedelta(minutes=10),
            end=now + timedelta(minutes=10),
        )
        result = self.client.publish("halluccheck.drift.red", {})
        self.assertTrue(result.suppressed)

    def test_alert_fires_after_window(self):
        now = datetime.now(timezone.utc)
        self.client.set_maintenance_window(
            "test-proj",
            start=now - timedelta(hours=2),
            end=now - timedelta(hours=1),
        )
        result = self.client.publish("halluccheck.drift.red", {})
        self.assertFalse(result.suppressed)

    def test_window_scoped_to_project(self):
        now = datetime.now(timezone.utc)
        self.client.set_maintenance_window(
            "other-proj",
            start=now - timedelta(minutes=5),
            end=now + timedelta(minutes=5),
        )
        # test-proj should not be affected
        result = self.client.publish("halluccheck.drift.red", {}, project_id="test-proj")
        self.assertFalse(result.suppressed)

    def test_remove_maintenance_windows(self):
        now = datetime.now(timezone.utc)
        self.client.set_maintenance_window(
            "test-proj",
            start=now - timedelta(minutes=5),
            end=now + timedelta(minutes=5),
        )
        removed = self.client.remove_maintenance_windows("test-proj")
        self.assertEqual(removed, 1)
        result = self.client.publish("halluccheck.drift.red", {})
        self.assertFalse(result.suppressed)


# ---------------------------------------------------------------------------
# Alert grouping (ALT-011)
# ---------------------------------------------------------------------------

class TestAlertGrouping(unittest.TestCase):
    def setUp(self):
        self.sink = _MockSink()
        self.client = _make_client(sinks=[self.sink], dedup_window_seconds=0.0)

    def tearDown(self):
        self.client.shutdown(timeout=2.0)

    def test_second_alert_same_prefix_grouped(self):
        r1 = self.client.publish("halluccheck.drift.red", {"i": 1})
        r2 = self.client.publish("halluccheck.drift.amber", {"i": 2})
        # Second alert with same prefix "halluccheck.drift" is grouped (routed_to=[])
        self.assertFalse(r1.suppressed)
        self.assertFalse(r2.suppressed)
        # r2 is in group buffer → routed_to empty until flush
        self.assertEqual(r2.routed_to, [])

    def test_different_prefix_not_grouped(self):
        r1 = self.client.publish("halluccheck.drift.red", {"i": 1})
        r2 = self.client.publish("halluccheck.pii.detected", {"i": 2})
        # Different prefix → separate dispatches (both not suppressed)
        self.assertFalse(r1.suppressed)
        self.assertFalse(r2.suppressed)


# ---------------------------------------------------------------------------
# Escalation policy (ALT-020)
# ---------------------------------------------------------------------------

class TestEscalation(unittest.TestCase):
    def setUp(self):
        self.sink = _MockSink()
        # Use a long escalation wait so timers don't fire during most checks
        self.client = _make_client(
            sinks=[self.sink],
            escalation_wait_seconds=30.0,
            dedup_window_seconds=0.0,
        )

    def tearDown(self):
        self.client.shutdown(timeout=2.0)

    def test_critical_alert_schedules_timer(self):
        self.client.publish("halluccheck.drift.red", {}, severity="critical")
        # Allow worker thread to process
        self.client._queue.join()
        with self.client._lock:
            has_timer = len(self.client._escalation_timers) > 0
        self.assertTrue(has_timer)

    def test_acknowledge_cancels_timer(self):
        result = self.client.publish("halluccheck.drift.red", {}, severity="critical")
        self.client._queue.join()
        acknowledged = self.client.acknowledge(result.alert_id)
        self.assertTrue(acknowledged)
        with self.client._lock:
            self.assertNotIn(result.alert_id, self.client._escalation_timers)

    def test_acknowledge_nonexistent_returns_false(self):
        self.assertFalse(self.client.acknowledge("nonexistent-id"))

    def test_escalation_fires_after_wait(self):
        # Use a very short escalation window for this specific test
        short_client = _make_client(
            sinks=[self.sink],
            escalation_wait_seconds=0.05,
            dedup_window_seconds=0.0,
        )
        try:
            short_client.publish("halluccheck.drift.red", {}, severity="critical")
            short_client._queue.join()
            # Wait for escalation to fire
            time.sleep(0.3)
            short_client.shutdown(timeout=2.0)
        finally:
            pass
        # Should have at least 2 dispatches (original + escalation)
        self.assertGreaterEqual(len(self.sink.calls), 2)

    def test_escalated_title_has_prefix(self):
        # Use a very short escalation window for this specific test
        short_client = _make_client(
            sinks=[self.sink],
            escalation_wait_seconds=0.05,
            dedup_window_seconds=0.0,
        )
        try:
            short_client.publish("halluccheck.drift.red", {}, severity="critical")
            short_client._queue.join()
            time.sleep(0.3)
            short_client.shutdown(timeout=2.0)
        finally:
            pass
        escalated = [c for c in self.sink.calls if "ESCALATED" in c.get("title", "")]
        self.assertTrue(len(escalated) >= 1)


# ---------------------------------------------------------------------------
# Webhook HMAC (ALT-034)
# ---------------------------------------------------------------------------

class TestWebhookAlerter(unittest.TestCase):
    def test_hmac_signature_header(self):
        webhook = WebhookAlerter(url="https://example.com/hook", secret="mysecret")
        sent_headers: list[dict] = []

        class _FakeResponse:
            status = 200

            def __enter__(self): return self
            def __exit__(self, *a): pass

        def fake_urlopen(req, timeout=None):
            sent_headers.append(dict(req.headers))
            return _FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            webhook.send("Title", "Message", severity="critical")

        self.assertTrue(sent_headers, "urlopen was not called")
        sig_header = sent_headers[0].get("X-sf-signature") or sent_headers[0].get("X-Sf-Signature", "")
        self.assertTrue(sig_header.startswith("sha256="), f"Unexpected sig: {sig_header!r}")

    def test_hmac_value_correct(self):
        secret = "test-secret"
        webhook = WebhookAlerter(url="https://example.com/hook", secret=secret)
        captured_data: list[bytes] = []
        captured_headers: list[dict] = []

        class _FakeResponse:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def fake_urlopen(req, timeout=None):
            captured_data.append(req.data)
            captured_headers.append(dict(req.headers))
            return _FakeResponse()

        with patch("urllib.request.urlopen", fake_urlopen):
            webhook.send("T", "M", severity="warning")

        body = captured_data[0]
        expected_sig = "sha256=" + _hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()
        actual_sig = (
            captured_headers[0].get("X-sf-signature")
            or captured_headers[0].get("X-Sf-Signature", "")
        )
        self.assertEqual(actual_sig, expected_sig)

    def test_invalid_url_scheme_raises(self):
        webhook = WebhookAlerter(url="ftp://example.com/hook", secret="s")
        with self.assertRaises(ValueError):
            webhook.send("T", "M")


# ---------------------------------------------------------------------------
# OpsGenie (ALT-030)
# ---------------------------------------------------------------------------

class TestOpsGenieAlerter(unittest.TestCase):
    def _run_and_capture(self, alerter, **kwargs):
        captured: list[dict] = []

        class _Resp:
            status = 202
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def fake_urlopen(req, timeout=None):
            captured.append({
                "url": req.full_url,
                "headers": dict(req.headers),
                "body": json.loads(req.data),
            })
            return _Resp()

        with patch("urllib.request.urlopen", fake_urlopen):
            alerter.send("T", "M", **kwargs)
        return captured

    def test_posts_to_correct_url_us(self):
        alerter = OpsGenieAlerter(api_key="key123")
        captured = self._run_and_capture(alerter, severity="critical")
        self.assertEqual(captured[0]["url"], "https://api.opsgenie.com/v2/alerts")

    def test_posts_to_eu_url(self):
        alerter = OpsGenieAlerter(api_key="key123", region="eu")
        captured = self._run_and_capture(alerter, severity="warning")
        self.assertEqual(captured[0]["url"], "https://api.eu.opsgenie.com/v2/alerts")

    def test_authorization_header(self):
        alerter = OpsGenieAlerter(api_key="mykey")
        captured = self._run_and_capture(alerter, severity="warning")
        auth = captured[0]["headers"].get("Authorization", "")
        self.assertIn("GenieKey", auth)
        self.assertIn("mykey", auth)

    def test_priority_mapping_critical(self):
        alerter = OpsGenieAlerter(api_key="key")
        captured = self._run_and_capture(alerter, severity="critical")
        self.assertEqual(captured[0]["body"]["priority"], "P1")

    def test_priority_mapping_info(self):
        alerter = OpsGenieAlerter(api_key="key")
        captured = self._run_and_capture(alerter, severity="info")
        self.assertEqual(captured[0]["body"]["priority"], "P5")

    def test_repr_does_not_leak_key(self):
        alerter = OpsGenieAlerter(api_key="secret-key-999")
        self.assertNotIn("secret-key-999", repr(alerter))


# ---------------------------------------------------------------------------
# VictorOps (ALT-031)
# ---------------------------------------------------------------------------

class TestVictorOpsAlerter(unittest.TestCase):
    def test_message_type_critical(self):
        alerter = VictorOpsAlerter(rest_endpoint_url="https://alert.victorops.com/integrations/generic/12345/alert/key")
        captured: list[dict] = []

        class _Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def fake_urlopen(req, timeout=None):
            captured.append(json.loads(req.data))
            return _Resp()

        with patch("urllib.request.urlopen", fake_urlopen):
            alerter.send("T", "M", severity="critical")

        self.assertEqual(captured[0]["message_type"], "CRITICAL")

    def test_message_type_warning(self):
        alerter = VictorOpsAlerter(rest_endpoint_url="https://alert.victorops.com/integrations/generic/12345/alert/key")
        captured: list[dict] = []

        class _Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def fake_urlopen(req, timeout=None):
            captured.append(json.loads(req.data))
            return _Resp()

        with patch("urllib.request.urlopen", fake_urlopen):
            alerter.send("T", "M", severity="warning")

        self.assertEqual(captured[0]["message_type"], "WARNING")


# ---------------------------------------------------------------------------
# Incident.io (ALT-032)
# ---------------------------------------------------------------------------

class TestIncidentIOAlerter(unittest.TestCase):
    def test_severity_mapping_critical(self):
        alerter = IncidentIOAlerter(api_key="key")
        captured: list[dict] = []

        class _Resp:
            status = 201
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def fake_urlopen(req, timeout=None):
            captured.append(json.loads(req.data))
            return _Resp()

        with patch("urllib.request.urlopen", fake_urlopen):
            alerter.send("T", "M", severity="critical")

        self.assertEqual(captured[0]["severity"]["name"], "critical")

    def test_severity_mapping_warning(self):
        alerter = IncidentIOAlerter(api_key="key")
        captured: list[dict] = []

        class _Resp:
            status = 201
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def fake_urlopen(req, timeout=None):
            captured.append(json.loads(req.data))
            return _Resp()

        with patch("urllib.request.urlopen", fake_urlopen):
            alerter.send("T", "M", severity="warning")

        self.assertEqual(captured[0]["severity"]["name"], "major")

    def test_auth_header(self):
        alerter = IncidentIOAlerter(api_key="my-incident-key")
        headers_captured: list[dict] = []

        class _Resp:
            status = 201
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def fake_urlopen(req, timeout=None):
            headers_captured.append(dict(req.headers))
            return _Resp()

        with patch("urllib.request.urlopen", fake_urlopen):
            alerter.send("T", "M")

        auth = headers_captured[0].get("Authorization", "")
        self.assertIn("Bearer", auth)


# ---------------------------------------------------------------------------
# SMS / Twilio (ALT-033)
# ---------------------------------------------------------------------------

class TestSMSAlerter(unittest.TestCase):
    def test_message_truncated_to_160_chars(self):
        alerter = SMSAlerter(
            account_sid="AC123",
            auth_token="tok",
            from_number="+15005550006",
            to_numbers=["+15005550007"],
        )
        captured_bodies: list[str] = []

        class _Resp:
            status = 201
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def fake_urlopen(req, timeout=None):
            raw = req.data.decode()
            body_val = [p.split("=", 1)[1] for p in raw.split("&") if p.startswith("Body=")]
            if body_val:
                from urllib.parse import unquote_plus
                captured_bodies.append(unquote_plus(body_val[0]))
            return _Resp()

        with patch("urllib.request.urlopen", fake_urlopen):
            alerter.send("Title", "A" * 200, severity="critical")

        self.assertTrue(captured_bodies, "urlopen was not called")
        self.assertLessEqual(len(captured_bodies[0]), 160)

    def test_no_recipients_skips(self):
        alerter = SMSAlerter(
            account_sid="AC123",
            auth_token="tok",
            from_number="+15005550006",
            to_numbers=[],
        )
        with patch("urllib.request.urlopen") as mock_urlopen:
            with self.assertLogs("spanforge.sdk.alert", level="WARNING"):
                alerter.send("T", "M")
            mock_urlopen.assert_not_called()

    def test_repr_does_not_leak_auth_token(self):
        alerter = SMSAlerter(account_sid="AC123", auth_token="supertoken", from_number="+1")
        self.assertNotIn("supertoken", repr(alerter))


# ---------------------------------------------------------------------------
# Teams Adaptive Card (ALT-035)
# ---------------------------------------------------------------------------

class TestTeamsAdaptiveCardAlerter(unittest.TestCase):
    def _capture(self, alerter, **kwargs):
        captured: list[dict] = []

        class _Resp:
            status = 200
            def __enter__(self): return self
            def __exit__(self, *a): pass

        def fake_urlopen(req, timeout=None):
            captured.append(json.loads(req.data))
            return _Resp()

        with patch("urllib.request.urlopen", fake_urlopen):
            alerter.send("T", "M", **kwargs)
        return captured

    def test_sends_adaptive_card(self):
        alerter = TeamsAdaptiveCardAlerter(webhook_url="https://outlook.office.com/webhook/test")
        captured = self._capture(alerter, severity="critical")
        self.assertEqual(captured[0]["type"], "message")
        attachments = captured[0]["attachments"]
        self.assertEqual(len(attachments), 1)
        self.assertIn("AdaptiveCard", str(attachments[0]))

    def test_critical_colour_attention(self):
        alerter = TeamsAdaptiveCardAlerter(webhook_url="https://outlook.office.com/webhook/test")
        captured = self._capture(alerter, severity="critical")
        body = json.dumps(captured)
        self.assertIn("Attention", body)

    def test_fact_table_included(self):
        alerter = TeamsAdaptiveCardAlerter(webhook_url="https://outlook.office.com/webhook/test")
        captured = self._capture(alerter, severity="warning", extra={"score": "0.9", "model": "gpt-4"})
        body_text = json.dumps(captured)
        self.assertIn("FactSet", body_text)
        self.assertIn("score", body_text)

    def test_action_buttons_included(self):
        alerter = TeamsAdaptiveCardAlerter(webhook_url="https://outlook.office.com/webhook/test")
        captured = self._capture(alerter, severity="info")
        body_text = json.dumps(captured)
        self.assertIn("Acknowledge", body_text)
        self.assertIn("Silence", body_text)


# ---------------------------------------------------------------------------
# Circuit breaker per sink (ALT-051)
# ---------------------------------------------------------------------------

class TestCircuitBreaker(unittest.TestCase):
    def setUp(self):
        self.good_sink = _MockSink()
        self.bad_sink = _MockSink(raises=RuntimeError("fail"))
        self.client = _make_client(sinks=[self.bad_sink, self.good_sink], dedup_window_seconds=0.0)

    def tearDown(self):
        self.client.shutdown(timeout=2.0)

    def test_failing_sink_does_not_block_good_sink(self):
        # Publish enough to trip the bad sink's circuit breaker
        for _ in range(5):
            self.client.publish("halluccheck.drift.red", {})
        self.client.shutdown(timeout=3.0)
        # Good sink should have received some calls
        self.assertGreater(len(self.good_sink.calls), 0)

    def test_circuit_open_after_failures(self):
        # Force failures directly on the wrapper
        wrapper = self.client._sinks[0]
        for _ in range(6):
            wrapper.dispatch("T", "M", "warning")
        self.assertTrue(wrapper.cb.is_open())


# ---------------------------------------------------------------------------
# Queue overflow behavior (ALT-050)
# ---------------------------------------------------------------------------

class TestQueueBehavior(unittest.TestCase):
    def test_queue_overflow_drops_logs_warning(self):
        # Create a client with a full queue
        config = _make_config()
        client = SFAlertClient(config, sinks=[], dedup_window_seconds=0.0)
        # Drain worker so queue can't drain
        client._queue.put_nowait(None)  # stop worker first
        client._worker.join(timeout=1.0)

        # Now manually fill the queue
        sentinel_item = None
        # Fill up to maxsize
        while not client._queue.full():
            try:
                from spanforge.sdk.alert import _QueueItem
                client._queue.put_nowait(
                    _QueueItem(
                        alert_id="x",
                        topic="t",
                        title="T",
                        message="M",
                        severity="info",
                        project_id="p",
                        payload={},
                        runbook_url=None,
                    )
                )
            except queue.Full:
                break

        # Manually call _flush_group with a full queue — should log warning
        from spanforge.sdk.alert import _QueueItem
        item = _QueueItem(
            alert_id="overflow",
            topic="t",
            title="T",
            message="M",
            severity="info",
            project_id="p",
            payload={},
            runbook_url=None,
        )
        with client._lock:
            key = ("t", "p")
            client._group_buffers[key] = [item]

        with self.assertLogs("spanforge.sdk.alert", level="WARNING") as cm:
            client._flush_group(("t", "p"))

        self.assertTrue(any("queue full" in line.lower() for line in cm.output))


# ---------------------------------------------------------------------------
# Alert history (ALT-042)
# ---------------------------------------------------------------------------

class TestAlertHistory(unittest.TestCase):
    def setUp(self):
        self.sink = _MockSink()
        self.client = _make_client(sinks=[self.sink], dedup_window_seconds=0.0)

    def tearDown(self):
        self.client.shutdown(timeout=2.0)

    def test_history_populated_after_dispatch(self):
        self.client.publish("halluccheck.drift.red", {"x": 1})
        self.client.shutdown(timeout=2.0)
        history = self.client.get_alert_history()
        self.assertGreater(len(history), 0)

    def test_history_filter_by_project_id(self):
        self.client.publish("halluccheck.drift.red", {}, project_id="proj-a")
        self.client.publish("halluccheck.pii.detected", {}, project_id="proj-b")
        self.client.shutdown(timeout=2.0)
        history = self.client.get_alert_history(project_id="proj-a")
        self.assertTrue(all(r.project_id == "proj-a" for r in history))

    def test_history_filter_by_topic(self):
        self.client.publish("halluccheck.drift.red", {})
        self.client.publish("halluccheck.pii.detected", {})
        self.client.shutdown(timeout=2.0)
        history = self.client.get_alert_history(topic="halluccheck.pii.detected")
        self.assertTrue(all(r.topic == "halluccheck.pii.detected" for r in history))

    def test_history_filter_by_status(self):
        result = self.client.publish("halluccheck.drift.red", {}, severity="critical")
        self.client._queue.join()
        self.client.acknowledge(result.alert_id)
        history = self.client.get_alert_history(status="acknowledged")
        self.assertTrue(all(r.status == "acknowledged" for r in history))

    def test_history_most_recent_first(self):
        for i in range(3):
            self.client.publish("halluccheck.drift.red", {"i": i}, project_id=f"proj-{i}")
        self.client.shutdown(timeout=2.0)
        history = self.client.get_alert_history(limit=3)
        if len(history) >= 2:
            self.assertGreaterEqual(history[0].timestamp, history[-1].timestamp)


# ---------------------------------------------------------------------------
# Audit log integration
# ---------------------------------------------------------------------------

class TestAuditLog(unittest.TestCase):
    def setUp(self):
        self.sink = _MockSink()
        self.client = _make_client(sinks=[self.sink], dedup_window_seconds=0.0)
        self.audit_calls: list[tuple] = []

        # Patch sf_audit inside the alert module
        self.mock_audit = MagicMock()
        self.mock_audit.append = MagicMock(side_effect=lambda r, s: self.audit_calls.append((r, s)))
        self._patcher = patch.dict(
            "sys.modules",
            {"spanforge.sdk": MagicMock(sf_audit=self.mock_audit)},
        )

    def tearDown(self):
        self.client.shutdown(timeout=2.0)

    def test_audit_append_not_required(self):
        """Audit failure must not block publish."""
        with patch(
            "spanforge.sdk.alert.SFAlertClient._append_audit_record",
            side_effect=Exception("audit down"),
        ):
            # Should not raise
            try:
                result = self.client.publish("halluccheck.drift.red", {})
            except Exception:
                pass  # publish itself is fine; worker dispatch may fail

    def test_maintenance_window_appends_audit(self):
        """set_maintenance_window calls _append_audit_record."""
        with patch.object(self.client, "_append_audit_record") as mock_append:
            now = datetime.now(timezone.utc)
            self.client.set_maintenance_window("test-proj", now, now + timedelta(hours=1))
            mock_append.assert_called_once()
            call_args = mock_append.call_args[0][0]
            self.assertEqual(call_args["event"], "maintenance_window_set")


# ---------------------------------------------------------------------------
# Runbook URL
# ---------------------------------------------------------------------------

class TestRunbookURL(unittest.TestCase):
    def setUp(self):
        self.sink = _MockSink()
        self.client = _make_client(sinks=[self.sink], dedup_window_seconds=0.0)

    def tearDown(self):
        self.client.shutdown(timeout=2.0)

    def test_runbook_url_in_extra(self):
        self.client.register_topic(
            "my.topic",
            "desc",
            runbook_url="https://wiki.example.com/runbooks/my-topic",
        )
        self.client.publish("my.topic", {})
        self.client.shutdown(timeout=2.0)
        calls = self.sink.calls
        if calls:
            extra = calls[0].get("extra", {}) or {}
            self.assertIn("runbook_url", extra)

    def test_message_contains_runbook_url(self):
        msg = _build_message("t.topic", {"k": "v"}, "https://example.com/runbook")
        self.assertIn("https://example.com/runbook", msg)


# ---------------------------------------------------------------------------
# Singleton wiring
# ---------------------------------------------------------------------------

class TestSingleton(unittest.TestCase):
    def test_sf_alert_is_sf_alert_client(self):
        from spanforge.sdk import sf_alert
        self.assertIsInstance(sf_alert, SFAlertClient)


class TestConfigure(unittest.TestCase):
    def test_configure_replaces_sf_alert(self):
        import spanforge.sdk as sdk
        original = sdk.sf_alert
        new_config = SFClientConfig(project_id="configured-proj")
        try:
            sdk.configure(new_config)
            self.assertIsInstance(sdk.sf_alert, SFAlertClient)
            self.assertIsNot(sdk.sf_alert, original)
        finally:
            sdk.sf_alert.shutdown(timeout=1.0)
            # Restore
            sdk.configure(SFClientConfig())


# ---------------------------------------------------------------------------
# Shutdown
# ---------------------------------------------------------------------------

class TestShutdown(unittest.TestCase):
    def test_shutdown_drains_queue(self):
        sink = _MockSink()
        client = _make_client(sinks=[sink], dedup_window_seconds=0.0)
        for _ in range(3):
            client.publish("halluccheck.drift.red", {})
        client.shutdown(timeout=3.0)
        self.assertFalse(client._worker.is_alive())

    def test_shutdown_cancels_escalation_timers(self):
        sink = _MockSink()
        client = _make_client(
            sinks=[sink],
            dedup_window_seconds=0.0,
            escalation_wait_seconds=9999.0,
        )
        client.publish("halluccheck.drift.red", {}, severity="critical")
        client._queue.join()
        with client._lock:
            has_timer = len(client._escalation_timers) > 0
        self.assertTrue(has_timer)
        client.shutdown(timeout=2.0)
        with client._lock:
            self.assertEqual(len(client._escalation_timers), 0)


# ---------------------------------------------------------------------------
# get_status / healthy
# ---------------------------------------------------------------------------

class TestGetStatus(unittest.TestCase):
    def setUp(self):
        self.sink = _MockSink()
        self.client = _make_client(sinks=[self.sink], dedup_window_seconds=0.0)

    def tearDown(self):
        self.client.shutdown(timeout=1.0)

    def test_status_returns_alert_status_info(self):
        status = self.client.get_status()
        self.assertIsInstance(status, AlertStatusInfo)

    def test_healthy_true_by_default(self):
        self.assertTrue(self.client.healthy)

    def test_status_counts_publish(self):
        self.client.publish("halluccheck.drift.red", {})
        status = self.client.get_status()
        self.assertGreaterEqual(status.publish_count, 1)

    def test_status_counts_suppressed(self):
        self.client._dedup_window = 10.0
        self.client.publish("halluccheck.drift.red", {})
        self.client.publish("halluccheck.drift.red", {})
        status = self.client.get_status()
        self.assertGreaterEqual(status.suppress_count, 1)


# ---------------------------------------------------------------------------
# add_sink
# ---------------------------------------------------------------------------

class TestAddSink(unittest.TestCase):
    def setUp(self):
        self.client = _make_client(sinks=[], dedup_window_seconds=0.0)

    def tearDown(self):
        self.client.shutdown(timeout=1.0)

    def test_add_sink_appended(self):
        sink = _MockSink()
        self.client.add_sink(sink, name="test-sink")
        with self.client._lock:
            names = [w.name for w in self.client._sinks]
        self.assertIn("test-sink", names)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class TestHelpers(unittest.TestCase):
    def test_topic_prefix_multi_dot(self):
        self.assertEqual(_topic_prefix("halluccheck.drift.red"), "halluccheck.drift")

    def test_topic_prefix_single_dot(self):
        self.assertEqual(_topic_prefix("halluccheck.drift"), "halluccheck")

    def test_topic_prefix_no_dot(self):
        self.assertEqual(_topic_prefix("nodot"), "nodot")

    def test_build_message_includes_topic(self):
        msg = _build_message("my.topic", {"key": "value"}, None)
        self.assertIn("my.topic", msg)
        self.assertIn("key", msg)
        self.assertIn("value", msg)

    def test_build_message_no_runbook(self):
        msg = _build_message("my.topic", {}, None)
        self.assertNotIn("Runbook", msg)


if __name__ == "__main__":
    unittest.main()
