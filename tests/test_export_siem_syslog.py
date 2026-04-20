"""Tests for spanforge.export.siem_syslog — SyslogExporter."""

from __future__ import annotations

import re
import socket
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

from spanforge.export.siem_syslog import (
    SyslogExporter,
    SyslogExporterError,
    _CEF_ESCAPE_RE,
    _SEVERITY_MAP,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HOST = "siem.example.com"


def _make_exporter(**kwargs: Any) -> SyslogExporter:
    defaults = dict(host=_HOST)
    defaults.update(kwargs)
    return SyslogExporter(**defaults)


def _fake_event(
    event_type: str = "llm.trace.span.completed",
    event_id: str = "evt-syslog-01",
    payload: dict[str, Any] | None = None,
) -> MagicMock:
    ev = MagicMock()
    ev.event_type = event_type
    ev.event_id = event_id
    ev.payload = payload or {"model": "gpt-4"}
    return ev


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestSyslogExporterInit:
    def test_requires_host_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="host"):
            SyslogExporter()

    def test_init_from_env_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_SYSLOG_HOST", "env-host")
        monkeypatch.setenv("SPANFORGE_SYSLOG_PORT", "6514")
        monkeypatch.setenv("SPANFORGE_SYSLOG_TRANSPORT", "tcp")
        monkeypatch.setenv("SPANFORGE_SYSLOG_FORMAT", "cef")
        monkeypatch.setenv("SPANFORGE_SYSLOG_APP_NAME", "myapp")
        monkeypatch.setenv("SPANFORGE_SYSLOG_FACILITY", "20")
        exp = SyslogExporter()
        assert exp._host == "env-host"
        assert exp._port == 6514
        assert exp._transport == "tcp"
        assert exp._format == "cef"
        assert exp._app_name == "myapp"
        assert exp._facility == 20

    def test_constructor_args_override_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_SYSLOG_HOST", "env-host")
        exp = SyslogExporter(host="arg-host")
        assert exp._host == "arg-host"

    def test_defaults_applied(self) -> None:
        exp = _make_exporter()
        assert exp._port == 514
        assert exp._transport == "udp"
        assert exp._format == "rfc5424"
        assert exp._app_name == "spanforge"
        assert exp._facility == 16

    def test_invalid_transport_raises(self) -> None:
        with pytest.raises(ValueError, match="transport"):
            SyslogExporter(host=_HOST, transport="ftp")

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="format"):
            SyslogExporter(host=_HOST, format="syslog")

    def test_facility_too_high_raises(self) -> None:
        with pytest.raises(ValueError, match="facility"):
            SyslogExporter(host=_HOST, facility=24)

    def test_facility_zero_is_valid(self) -> None:
        exp = SyslogExporter(host=_HOST, facility=0)
        assert exp._facility == 0

    def test_facility_23_is_valid(self) -> None:
        exp = SyslogExporter(host=_HOST, facility=23)
        assert exp._facility == 23

    def test_initial_counts_zero(self) -> None:
        exp = _make_exporter()
        assert exp.sent_count == 0
        assert exp.error_count == 0

    def test_transport_normalised_to_lowercase(self) -> None:
        exp = SyslogExporter(host=_HOST, transport="UDP")
        assert exp._transport == "udp"

    def test_format_normalised_to_lowercase(self) -> None:
        exp = SyslogExporter(host=_HOST, format="RFC5424")
        assert exp._format == "rfc5424"


# ---------------------------------------------------------------------------
# Severity mapping
# ---------------------------------------------------------------------------


class TestSeverityMapping:
    @pytest.mark.parametrize("prefix,expected", [
        ("alert", 1),
        ("error", 3),
        ("warn", 4),
        ("warning", 4),
        ("info", 6),
        ("debug", 7),
        ("trace", 7),
        ("unknown", 6),  # default
    ])
    def test_severity_from_event_type_prefix(self, prefix: str, expected: int) -> None:
        exp = _make_exporter()
        ev = _fake_event(event_type=f"{prefix}.something.happened")
        assert exp._severity_from_event(ev) == expected

    def test_severity_map_exported(self) -> None:
        assert "alert" in _SEVERITY_MAP
        assert "error" in _SEVERITY_MAP

    def test_priority_calculation(self) -> None:
        exp = _make_exporter()
        # facility=16 (local0), severity=6 (info) => PRI = 16*8+6 = 134
        assert exp._priority(6) == 134

    def test_priority_with_custom_facility(self) -> None:
        exp = _make_exporter(facility=1)
        # facility=1, severity=3 => PRI = 1*8+3 = 11
        assert exp._priority(3) == 11


# ---------------------------------------------------------------------------
# RFC 5424 formatting
# ---------------------------------------------------------------------------


class TestRFC5424Formatting:
    def test_rfc5424_starts_with_pri_version(self) -> None:
        exp = _make_exporter()
        ev = _fake_event(event_type="info.test")
        msg = exp._format_rfc5424(ev)
        # Should start with <PRI>1
        assert re.match(r"^<\d+>1 ", msg)

    def test_rfc5424_contains_event_id(self) -> None:
        exp = _make_exporter()
        ev = _fake_event(event_id="my-evt-id")
        msg = exp._format_rfc5424(ev)
        assert "my-evt-id" in msg

    def test_rfc5424_contains_event_type_as_msgid(self) -> None:
        exp = _make_exporter()
        ev = _fake_event(event_type="llm.trace.span.completed")
        msg = exp._format_rfc5424(ev)
        assert "llm.trace.span.completed" in msg

    def test_rfc5424_contains_payload_json(self) -> None:
        exp = _make_exporter()
        ev = _fake_event(payload={"key": "value"})
        msg = exp._format_rfc5424(ev)
        assert "key" in msg

    def test_rfc5424_contains_app_name(self) -> None:
        exp = _make_exporter(app_name="myagent")
        ev = _fake_event()
        msg = exp._format_rfc5424(ev)
        assert "myagent" in msg

    def test_rfc5424_timestamp_is_iso8601(self) -> None:
        exp = _make_exporter()
        ev = _fake_event()
        msg = exp._format_rfc5424(ev)
        # Should contain a Z-terminated ISO timestamp
        assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", msg)


# ---------------------------------------------------------------------------
# CEF formatting
# ---------------------------------------------------------------------------


class TestCEFFormatting:
    def test_cef_contains_cef_header(self) -> None:
        exp = _make_exporter()
        ev = _fake_event()
        msg = exp._format_cef(ev)
        assert "CEF:0|SpanForge|SpanForge|" in msg

    def test_cef_contains_severity(self) -> None:
        exp = _make_exporter()
        ev = _fake_event(event_type="error.module.fail")
        msg = exp._format_cef(ev)
        # severity 3 should appear in header
        assert "|3|" in msg

    def test_cef_contains_event_id_in_extension(self) -> None:
        exp = _make_exporter()
        ev = _fake_event(event_id="cef-42")
        msg = exp._format_cef(ev)
        assert "cef-42" in msg

    def test_cef_contains_payload_keys(self) -> None:
        exp = _make_exporter()
        ev = _fake_event(payload={"score": "0.9", "model": "gpt-4"})
        msg = exp._format_cef(ev)
        assert "score=0.9" in msg
        assert "model=gpt-4" in msg

    def test_cef_escapes_pipe_in_event_type(self) -> None:
        ev = _fake_event(event_type="llm|bad|type")
        exp = _make_exporter()
        msg = exp._format_cef(ev)
        assert r"llm\|bad\|type" in msg

    def test_cef_escapes_backslash_in_value(self) -> None:
        exp = _make_exporter()
        ev = _fake_event(payload={"path": "C:\\Users\\test"})
        msg = exp._format_cef(ev)
        # backslash escaped
        assert r"C:\\Users\\test" in msg

    def test_cef_escapes_equals_in_value(self) -> None:
        exp = _make_exporter()
        ev = _fake_event(payload={"expr": "a=b"})
        msg = exp._format_cef(ev)
        assert r"a\=b" in msg

    def test_cef_escape_re_matches_special_chars(self) -> None:
        assert _CEF_ESCAPE_RE.sub(r"\\\1", "a|b=c\\d") == r"a\|b\=c\\d"

    def test_cef_payload_key_sanitised(self) -> None:
        """Non-alphanumeric payload key chars become underscores."""
        exp = _make_exporter()
        ev = _fake_event(payload={"my-key.here": "val"})
        msg = exp._format_cef(ev)
        assert "my_key_here=val" in msg


# ---------------------------------------------------------------------------
# Transport — UDP
# ---------------------------------------------------------------------------


class TestUDPTransport:
    def test_export_udp_sends_message(self) -> None:
        exp = _make_exporter(transport="udp")
        ev = _fake_event()
        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)
        with patch("socket.socket", return_value=mock_sock):
            exp.export(ev)
        mock_sock.sendto.assert_called_once()
        data, addr = mock_sock.sendto.call_args[0]
        assert addr == (_HOST, 514)
        assert isinstance(data, bytes)

    def test_export_udp_increments_sent_count(self) -> None:
        exp = _make_exporter(transport="udp")
        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)
        with patch("socket.socket", return_value=mock_sock):
            exp.export(_fake_event())
            exp.export(_fake_event())
        assert exp.sent_count == 2

    def test_export_udp_os_error_increments_error_count(self) -> None:
        exp = _make_exporter(transport="udp")
        with patch("socket.socket", side_effect=OSError("network unreachable")):
            exp.export(_fake_event())
        assert exp.error_count == 1
        assert exp.sent_count == 0

    def test_send_raises_syslog_exporter_error_on_os_error(self) -> None:
        exp = _make_exporter(transport="udp")
        with patch("socket.socket", side_effect=OSError("refused")):
            with pytest.raises(SyslogExporterError, match="Syslog delivery failed"):
                exp._send("test message")


# ---------------------------------------------------------------------------
# Transport — TCP
# ---------------------------------------------------------------------------


class TestTCPTransport:
    def test_export_tcp_sends_message(self) -> None:
        exp = _make_exporter(transport="tcp", port=6514)
        ev = _fake_event()
        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)
        with patch("socket.create_connection", return_value=mock_sock):
            exp.export(ev)
        mock_sock.sendall.assert_called_once()
        data = mock_sock.sendall.call_args[0][0]
        assert data.endswith(b"\n")

    def test_export_tcp_increments_sent_count(self) -> None:
        exp = _make_exporter(transport="tcp")
        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)
        with patch("socket.create_connection", return_value=mock_sock):
            exp.export(_fake_event())
        assert exp.sent_count == 1

    def test_export_tcp_os_error_increments_error_count(self) -> None:
        exp = _make_exporter(transport="tcp")
        with patch("socket.create_connection", side_effect=OSError("timeout")):
            exp.export(_fake_event())
        assert exp.error_count == 1


# ---------------------------------------------------------------------------
# CEF mode via export()
# ---------------------------------------------------------------------------


class TestCEFMode:
    def test_export_cef_format_sends_cef_string(self) -> None:
        exp = _make_exporter(format="cef")
        ev = _fake_event()
        sent_messages: list[bytes] = []

        def capture_sendto(data: bytes, addr: tuple[str, int]) -> None:
            sent_messages.append(data)

        mock_sock = MagicMock()
        mock_sock.__enter__ = lambda s: s
        mock_sock.__exit__ = MagicMock(return_value=False)
        mock_sock.sendto.side_effect = capture_sendto

        with patch("socket.socket", return_value=mock_sock):
            exp.export(ev)

        assert len(sent_messages) == 1
        assert b"CEF:0" in sent_messages[0]


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    def test_context_manager_enter_returns_self(self) -> None:
        exp = _make_exporter()
        with exp as ctx:
            assert ctx is exp

    def test_close_is_noop(self) -> None:
        exp = _make_exporter()
        exp.close()  # should not raise


# ---------------------------------------------------------------------------
# __repr__
# ---------------------------------------------------------------------------


class TestRepr:
    def test_repr_contains_host_and_transport(self) -> None:
        exp = _make_exporter(port=6514, transport="tcp")
        r = repr(exp)
        assert "SyslogExporter" in r
        assert _HOST in r
        assert "6514" in r
        assert "tcp" in r
        assert "sent=0" in r
