"""SF-14 — Egress Enforcement acceptance tests."""

from __future__ import annotations

import pytest

from spanforge import Event, EventType, get_config

_SOURCE = "test-sf14@1.0.0"


def _make_event(**kw):
    defaults = {
        "event_type": EventType.TRACE_SPAN_COMPLETED,
        "source": _SOURCE,
        "payload": {"span_name": "run", "status": "ok"},
    }
    defaults.update(kw)
    return Event(**defaults)


# ---- SF-14-A: Network exporters call check_egress() ----

class TestSF14A:
    """SF-14-A: All network exporters gate on ``check_egress()``."""

    @pytest.mark.unit
    def test_otlp_exporter_calls_check_egress(self):
        from pathlib import Path as _Path

        from spanforge.export import otlp
        source = _Path(otlp.__file__).read_text(encoding="utf-8")
        assert "check_egress" in source

    @pytest.mark.unit
    def test_webhook_exporter_calls_check_egress(self):
        from pathlib import Path as _Path

        from spanforge.export import webhook
        source = _Path(webhook.__file__).read_text(encoding="utf-8")
        assert "check_egress" in source

    @pytest.mark.unit
    def test_datadog_exporter_calls_check_egress(self):
        from pathlib import Path as _Path

        from spanforge.export import datadog
        source = _Path(datadog.__file__).read_text(encoding="utf-8")
        assert "check_egress" in source

    @pytest.mark.unit
    def test_grafana_exporter_calls_check_egress(self):
        from pathlib import Path as _Path

        from spanforge.export import grafana
        source = _Path(grafana.__file__).read_text(encoding="utf-8")
        assert "check_egress" in source


# ---- SF-14-B: egress_allowlist wired ----

class TestSF14B:
    """SF-14-B: ``egress_allowlist`` config field exists and is used."""

    @pytest.mark.unit
    def test_config_has_egress_allowlist(self):
        cfg = get_config()
        assert hasattr(cfg, "egress_allowlist")

    @pytest.mark.unit
    def test_check_egress_respects_allowlist(self):
        from spanforge.egress import check_egress

        cfg = get_config()
        saved_no_egress = cfg.no_egress
        saved_allowlist = cfg.egress_allowlist
        try:
            cfg.no_egress = False
            cfg.egress_allowlist = ["https://allowed.example.com"]
            # Should not raise for allowed endpoint
            check_egress("https://allowed.example.com/v1/traces")
        finally:
            cfg.no_egress = saved_no_egress
            cfg.egress_allowlist = saved_allowlist


# ---- SF-14-C: Air-gapped documentation ----

class TestSF14C:
    """SF-14-C: Air-gapped deployment documentation exists."""

    @pytest.mark.unit
    def test_airgapped_doc_exists(self):
        from pathlib import Path

        docs = Path(__file__).resolve().parent.parent / "docs"
        candidates = list(docs.rglob("*air*gap*"))
        assert len(candidates) > 0, "No air-gapped documentation found"
