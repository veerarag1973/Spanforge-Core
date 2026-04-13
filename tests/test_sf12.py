"""SF-12 — Compliance Reporting acceptance tests."""

from __future__ import annotations

import json

import pytest

from spanforge import Event, EventType
from spanforge.core.compliance_mapping import (
    ComplianceEvidencePackage,
    ComplianceFramework,
    ComplianceMappingEngine,
    _FRAMEWORK_CLAUSES,
)


_SOURCE = "test-sf12@1.0.0"


def _make_event(**kw):
    defaults = {
        "event_type": EventType.TRACE_SPAN_COMPLETED,
        "source": _SOURCE,
        "payload": {"span_name": "run", "status": "ok"},
    }
    defaults.update(kw)
    return Event(**defaults)


# ---- SF-12-A: to_json() compliance report ----

class TestSF12A:
    """SF-12-A: ``ComplianceEvidencePackage.to_json()`` returns valid JSON."""

    @pytest.mark.unit
    def test_to_json_returns_valid_json(self):
        engine = ComplianceMappingEngine()
        pkg = engine.generate_evidence_package(
            model_id="gpt-4o",
            framework=ComplianceFramework("SOC 2 Type II"),
            from_date="2024-01-01",
            to_date="2024-12-31",
        )
        j = pkg.to_json()
        parsed = json.loads(j)
        assert isinstance(parsed, dict)
        assert "clauses" in parsed


# ---- SF-12-B: to_pdf() ----

class TestSF12B:
    """SF-12-B: PDF export."""

    @pytest.mark.unit
    def test_to_pdf_produces_file(self, tmp_path):
        engine = ComplianceMappingEngine()
        pkg = engine.generate_evidence_package(
            model_id="gpt-4o",
            framework=ComplianceFramework("SOC 2 Type II"),
            from_date="2024-01-01",
            to_date="2024-12-31",
        )
        pdf_path = tmp_path / "report.pdf"
        try:
            pkg.to_pdf(str(pdf_path))
            assert pdf_path.exists()
            assert pdf_path.stat().st_size > 0
        except ImportError:
            pytest.skip("reportlab not installed")


# ---- SF-12-C: CLI compliance report ----

class TestSF12C:
    """SF-12-C: CLI ``compliance report`` sub-command exists."""

    @pytest.mark.unit
    def test_cli_compliance_report_help(self):
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["compliance", "report", "--help"])
        assert exc_info.value.code == 0


# ---- SF-12-D: Compliance thresholds ----

class TestSF12D:
    """SF-12-D: All framework clauses have thresholds."""

    @pytest.mark.unit
    def test_all_clauses_have_min_event_count(self):
        for fw_key, clauses in _FRAMEWORK_CLAUSES.items():
            for clause_id, clause_info in clauses.items():
                assert "min_event_count" in clause_info, \
                    f"Framework {fw_key}, clause {clause_id} missing min_event_count"
