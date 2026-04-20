"""Tests for spanforge.export.siem_splunk — SplunkHECExporter."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from io import BytesIO
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from spanforge.export.siem_splunk import SplunkHECError, SplunkHECExporter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_URL = "https://splunk.example.com:8088/services/collector/event"
_TOKEN = "test-token-abc"


def _make_exporter(**kwargs: Any) -> SplunkHECExporter:
    defaults = dict(hec_url=_URL, token=_TOKEN, batch_size=10)
    defaults.update(kwargs)
    return SplunkHECExporter(**defaults)


def _fake_event(
    event_type: str = "llm.trace.span.completed",
    event_id: str = "evt-001",
    payload: dict[str, Any] | None = None,
) -> MagicMock:
    ev = MagicMock()
    ev.event_type = event_type
    ev.event_id = event_id
    ev.timestamp = 1_700_000_000.0
    ev.schema_version = "1.0"
    ev.payload = payload or {"model": "gpt-4"}
    return ev


def _mock_200_response() -> MagicMock:
    resp = MagicMock()
    resp.status = 200
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestSplunkHECExporterInit:
    def test_requires_url_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="HEC URL"):
            SplunkHECExporter(token=_TOKEN)

    def test_requires_token_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="token"):
            SplunkHECExporter(hec_url=_URL)

    def test_init_from_constructor_args(self) -> None:
        exp = _make_exporter(index="myindex", source="myapp", sourcetype="myapp:log")
        assert exp._index == "myindex"
        assert exp._source == "myapp"
        assert exp._sourcetype == "myapp:log"

    def test_init_from_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_SPLUNK_HEC_URL", _URL)
        monkeypatch.setenv("SPANFORGE_SPLUNK_HEC_TOKEN", "env-token")
        monkeypatch.setenv("SPANFORGE_SPLUNK_INDEX", "env-index")
        monkeypatch.setenv("SPANFORGE_SPLUNK_SOURCE", "env-source")
        monkeypatch.setenv("SPANFORGE_SPLUNK_SOURCETYPE", "env:st")
        monkeypatch.setenv("SPANFORGE_SPLUNK_BATCH_SIZE", "25")
        monkeypatch.setenv("SPANFORGE_SPLUNK_TIMEOUT", "5.5")
        exp = SplunkHECExporter()
        assert exp._token == "env-token"
        assert exp._index == "env-index"
        assert exp._source == "env-source"
        assert exp._sourcetype == "env:st"
        assert exp._batch_size == 25
        assert exp._timeout == 5.5

    def test_constructor_args_override_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_SPLUNK_INDEX", "env-index")
        exp = _make_exporter(index="arg-index")
        assert exp._index == "arg-index"

    def test_defaults_applied(self) -> None:
        exp = _make_exporter()
        assert exp._index == "main"
        assert exp._source == "spanforge"
        assert exp._sourcetype == "spanforge:event"
        assert exp._batch_size == 10  # overridden in _make_exporter
        assert exp._timeout == 10.0

    def test_http_non_localhost_warns(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging
        with caplog.at_level(logging.WARNING, logger="spanforge.export.siem_splunk"):
            SplunkHECExporter(
                hec_url="http://remote.example.com:8088/services/collector",
                token=_TOKEN,
            )
        assert any("plaintext HTTP" in r.message for r in caplog.records)

    def test_http_localhost_no_warn(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging
        with caplog.at_level(logging.WARNING, logger="spanforge.export.siem_splunk"):
            SplunkHECExporter(
                hec_url="http://localhost:8088/services/collector",
                token=_TOKEN,
            )
        assert not any("plaintext HTTP" in r.message for r in caplog.records)

    def test_http_127_no_warn(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging
        with caplog.at_level(logging.WARNING, logger="spanforge.export.siem_splunk"):
            SplunkHECExporter(
                hec_url="http://127.0.0.1:8088/services/collector",
                token=_TOKEN,
            )
        assert not any("plaintext HTTP" in r.message for r in caplog.records)

    def test_initial_counts_zero(self) -> None:
        exp = _make_exporter()
        assert exp.sent_count == 0
        assert exp.error_count == 0


# ---------------------------------------------------------------------------
# Payload building
# ---------------------------------------------------------------------------


class TestBuildHECPayload:
    def test_payload_contains_required_keys(self) -> None:
        exp = _make_exporter()
        ev = _fake_event()
        payload = exp._build_hec_payload(ev)
        assert "time" in payload
        assert "index" in payload
        assert "source" in payload
        assert "sourcetype" in payload
        assert "event" in payload

    def test_payload_event_contains_event_fields(self) -> None:
        exp = _make_exporter()
        ev = _fake_event(event_type="alert.budget.exceeded", event_id="x-99")
        payload = exp._build_hec_payload(ev)
        assert payload["event"]["event_type"] == "alert.budget.exceeded"
        assert payload["event"]["event_id"] == "x-99"

    def test_payload_uses_configured_index(self) -> None:
        exp = _make_exporter(index="custom-index")
        ev = _fake_event()
        payload = exp._build_hec_payload(ev)
        assert payload["index"] == "custom-index"

    def test_payload_timestamp_from_event(self) -> None:
        exp = _make_exporter()
        ev = _fake_event()
        ev.timestamp = 9999.0
        payload = exp._build_hec_payload(ev)
        assert payload["time"] == 9999.0


# ---------------------------------------------------------------------------
# Buffering and batching
# ---------------------------------------------------------------------------


class TestBufferingAndBatching:
    def test_export_buffers_below_batch_size(self) -> None:
        exp = _make_exporter(batch_size=5)
        ev = _fake_event()
        with patch.object(exp, "_send") as mock_send:
            for _ in range(4):
                exp.export(ev)
            mock_send.assert_not_called()

    def test_export_flushes_at_batch_size(self) -> None:
        exp = _make_exporter(batch_size=3)
        ev = _fake_event()
        with patch("urllib.request.urlopen", return_value=_mock_200_response()):
            for _ in range(3):
                exp.export(ev)
        assert exp.sent_count == 3
        assert len(exp._pending) == 0

    def test_flush_sends_buffered_events(self) -> None:
        exp = _make_exporter(batch_size=100)
        ev = _fake_event()
        with patch("urllib.request.urlopen", return_value=_mock_200_response()):
            exp.export(ev)
            exp.export(ev)
            assert exp.sent_count == 0
            exp.flush()
        assert exp.sent_count == 2

    def test_flush_clears_pending(self) -> None:
        exp = _make_exporter(batch_size=100)
        ev = _fake_event()
        with patch("urllib.request.urlopen", return_value=_mock_200_response()):
            exp.export(ev)
            exp.flush()
        assert len(exp._pending) == 0

    def test_export_batch_returns_count(self) -> None:
        exp = _make_exporter(batch_size=100)
        events = [_fake_event() for _ in range(5)]
        with patch("urllib.request.urlopen", return_value=_mock_200_response()):
            count = exp.export_batch(events)
        assert count == 5

    def test_empty_flush_is_noop(self) -> None:
        exp = _make_exporter()
        with patch.object(exp, "_send") as mock_send:
            exp.flush()
            mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# Sent / error counters
# ---------------------------------------------------------------------------


class TestCounters:
    def test_sent_count_increments_on_success(self) -> None:
        exp = _make_exporter(batch_size=1)
        ev = _fake_event()
        with patch("urllib.request.urlopen", return_value=_mock_200_response()):
            exp.export(ev)
            exp.export(ev)
        assert exp.sent_count == 2

    def test_error_count_increments_on_failure(self) -> None:
        exp = _make_exporter(batch_size=1)
        ev = _fake_event()
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("refused")):
            exp.export(ev)
        assert exp.error_count == 1
        assert exp.sent_count == 0

    def test_error_count_does_not_raise(self) -> None:
        """flush_locked catches exceptions and increments error_count."""
        exp = _make_exporter(batch_size=100)
        ev = _fake_event()
        with patch("urllib.request.urlopen", side_effect=Exception("boom")):
            exp.export(ev)
            exp.flush()
        assert exp.error_count == 1


# ---------------------------------------------------------------------------
# _send method
# ---------------------------------------------------------------------------


class TestSendMethod:
    def test_send_uses_authorization_header(self) -> None:
        exp = _make_exporter()
        with patch("urllib.request.urlopen", return_value=_mock_200_response()) as mock_open:
            exp._send([{"event": "test"}])
        req_obj = mock_open.call_args[0][0]
        assert req_obj.get_header("Authorization") == f"Splunk {_TOKEN}"

    def test_send_content_type_is_json(self) -> None:
        exp = _make_exporter()
        with patch("urllib.request.urlopen", return_value=_mock_200_response()) as mock_open:
            exp._send([{"event": "test"}])
        req_obj = mock_open.call_args[0][0]
        assert req_obj.get_header("Content-type") == "application/json"

    def test_send_multiple_events_newline_delimited(self) -> None:
        exp = _make_exporter()
        captured_body: list[bytes] = []
        orig_request = urllib.request.Request

        def capture_request(url: str, data: bytes | None = None, **kw: Any) -> Any:
            if data:
                captured_body.append(data)
            return orig_request(url, data=data, **kw)

        with patch("urllib.request.Request", side_effect=capture_request):
            with patch("urllib.request.urlopen", return_value=_mock_200_response()):
                exp._send([{"a": 1}, {"b": 2}])

        assert len(captured_body) == 1
        lines = captured_body[0].decode().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"a": 1}

    def test_send_http_error_raises_siem_error(self) -> None:
        exp = _make_exporter()
        err = urllib.error.HTTPError(
            url=_URL, code=403, msg="Forbidden", hdrs=None, fp=None  # type: ignore[arg-type]
        )
        with patch("urllib.request.urlopen", side_effect=err):
            with pytest.raises(SplunkHECError, match="403"):
                exp._send([{"event": "test"}])

    def test_send_url_error_raises_siem_error(self) -> None:
        exp = _make_exporter()
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("connection refused")):
            with pytest.raises(SplunkHECError, match="connection error"):
                exp._send([{"event": "test"}])

    def test_verify_ssl_false_creates_unverified_context(self) -> None:
        exp = _make_exporter(verify_ssl=False)
        import ssl

        with patch("urllib.request.urlopen", return_value=_mock_200_response()) as mock_open:
            exp._send([{"event": "test"}])

        _, kwargs = mock_open.call_args
        ctx = kwargs.get("context")
        assert ctx is not None
        assert ctx.verify_mode == ssl.CERT_NONE


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    def test_context_manager_flushes_on_exit(self) -> None:
        ev = _fake_event()
        with patch("urllib.request.urlopen", return_value=_mock_200_response()) as mock_open:
            with _make_exporter(batch_size=100) as exp:
                exp.export(ev)
                assert exp.sent_count == 0  # not flushed yet
            # __exit__ called close() -> flush()
        assert exp.sent_count == 1

    def test_context_manager_returns_self(self) -> None:
        exp = _make_exporter()
        with exp as ctx:
            assert ctx is exp


# ---------------------------------------------------------------------------
# __repr__
# ---------------------------------------------------------------------------


class TestRepr:
    def test_repr_contains_url_and_index(self) -> None:
        exp = _make_exporter(index="ops")
        r = repr(exp)
        assert "SplunkHECExporter" in r
        assert "ops" in r
        assert "sent=0" in r

    def test_token_not_in_repr(self) -> None:
        exp = _make_exporter()
        assert _TOKEN not in repr(exp)
