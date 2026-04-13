"""SF-11 — OTel Passthrough & Dual-Stream Export acceptance tests."""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock, patch

import pytest

from spanforge import Event, EventType, OTelBridgeExporter, Tags, configure, get_config


_SOURCE = "test-sf11@1.0.0"


def _make_event(**kw):
    defaults = {
        "event_type": EventType.TRACE_SPAN_COMPLETED,
        "source": _SOURCE,
        "payload": {"span_name": "run", "status": "ok"},
    }
    defaults.update(kw)
    return Event(**defaults)


# ---- SF-11-A: OTelBridgeExporter importable at top level ----

class TestSF11A:
    """SF-11-A: ``OTelBridgeExporter`` importable from ``spanforge``."""

    @pytest.mark.unit
    def test_otel_bridge_in_all(self):
        import spanforge
        assert "OTelBridgeExporter" in spanforge.__all__

    @pytest.mark.unit
    def test_otel_bridge_importable(self):
        from spanforge import OTelBridgeExporter  # noqa: F811
        assert OTelBridgeExporter is not None


# ---- SF-11-B: otel_passthrough preset ----

class TestSF11B:
    """SF-11-B: ``mode='otel_passthrough'`` wires the OTel bridge exporter."""

    @pytest.fixture(autouse=True)
    def _restore_config(self):
        cfg = get_config()
        saved = {k: getattr(cfg, k) for k in vars(cfg)}
        yield
        for k, v in saved.items():
            setattr(cfg, k, v)

    @pytest.mark.unit
    def test_configure_otel_passthrough_sets_preset(self):
        configure(mode="otel_passthrough")
        cfg = get_config()
        assert cfg.exporter == "otel_bridge"


# ---- SF-11-C: Dual-stream _FanOutExporter ----

class TestSF11C:
    """SF-11-C: Dual-stream export via ``_FanOutExporter``."""

    @pytest.mark.unit
    def test_fan_out_exporter_dispatches_to_all_children(self):
        from spanforge._stream import _FanOutExporter

        child_a = MagicMock()
        child_b = MagicMock()
        fan = _FanOutExporter([("a", child_a), ("b", child_b)])

        event = _make_event()
        fan.export(event)

        child_a.export.assert_called_once_with(event)
        child_b.export.assert_called_once_with(event)

    @pytest.mark.unit
    def test_fan_out_exporter_isolates_failures(self):
        from spanforge._stream import _FanOutExporter

        child_a = MagicMock()
        child_a.export.side_effect = RuntimeError("boom")
        child_b = MagicMock()
        fan = _FanOutExporter([("a", child_a), ("b", child_b)])

        event = _make_event()
        fan.export(event)  # should not raise

        child_b.export.assert_called_once_with(event)

    @pytest.mark.unit
    def test_fan_out_close_calls_all_children(self):
        from spanforge._stream import _FanOutExporter

        child_a = MagicMock()
        child_b = MagicMock()
        fan = _FanOutExporter([("a", child_a), ("b", child_b)])

        fan.close()

        child_a.close.assert_called_once()
        child_b.close.assert_called_once()

    @pytest.mark.unit
    def test_build_exporter_creates_fan_out_for_multiple(self):
        from spanforge._stream import _FanOutExporter, _build_exporter

        cfg = get_config()
        saved_exporters = cfg.exporters
        try:
            cfg.exporters = ["jsonl", "console"]
            exporter = _build_exporter()
            assert isinstance(exporter, _FanOutExporter)
        finally:
            cfg.exporters = saved_exporters


# ---- SF-11-D: README OTel section ----

class TestSF11D:
    """SF-11-D: README contains OTel passthrough section."""

    @pytest.mark.unit
    def test_readme_has_otel_section(self, tmp_path):
        from pathlib import Path

        readme = Path(__file__).resolve().parent.parent / "README.md"
        if not readme.exists():
            pytest.skip("README.md not found")
        text = readme.read_text(encoding="utf-8")
        assert "Using SpanForge alongside OpenTelemetry" in text
        assert "otel_passthrough" in text
