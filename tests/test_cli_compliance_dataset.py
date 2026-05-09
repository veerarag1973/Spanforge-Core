"""Tests for CARD 1C-4 — Training Data Compliance Scanner.

Coverage:
  * clean dataset passes all Article 10 clauses
  * PII-laden dataset fails Art.10(2)(a)
  * no-consent dataset fails Art.10(2)(b)
  * JSON output round-trips cleanly
  * HMAC signature is verifiable
  * CSV file loading
  * plain-text file loading
  * directory containing mixed file types
  * empty dataset
  * non-existent path raises FileNotFoundError
  * ``spanforge compliance validate-dataset`` CLI path (subprocess)
  * ``spanforge validate --dataset`` CLI path (subprocess)
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import pathlib
from typing import Any
from unittest.mock import patch

import pytest

from spanforge.sdk.dataset_scanner import (
    Article10Clause,
    DatasetComplianceReport,
    scan_dataset_compliance,
)


def _run_cli(*args: str) -> tuple[int, str]:
    """Invoke ``spanforge main()`` in-process; return (exit_code, stdout)."""
    from spanforge._cli import main

    buf = io.StringIO()
    with patch("sys.stdout", buf), patch("sys.argv", ["spanforge", *args]):
        try:
            rc = main()
        except SystemExit as exc:
            rc = int(exc.code) if exc.code is not None else 0
    return rc, buf.getvalue()

# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

CLEAN_DATASET = pathlib.Path("tests/fixtures/clean_dataset")
PII_DATASET = pathlib.Path("tests/fixtures/pii_dataset")
NO_CONSENT_DATASET = pathlib.Path("tests/fixtures/no_consent_dataset")


# ---------------------------------------------------------------------------
# Core scanner tests
# ---------------------------------------------------------------------------


class TestCleanDataset:
    def test_all_clauses_pass(self) -> None:
        report = scan_dataset_compliance(CLEAN_DATASET, sign=False)
        failed = [c for c in report.eu_ai_act_article_10_clauses if not c.passed]
        assert failed == [], f"Unexpected failures: {[c.clause_id for c in failed]}"

    def test_pii_density_is_zero(self) -> None:
        report = scan_dataset_compliance(CLEAN_DATASET, sign=False)
        assert report.pii_density_score == pytest.approx(0.0)

    def test_consent_coverage_is_100(self) -> None:
        report = scan_dataset_compliance(CLEAN_DATASET, sign=False)
        assert report.consent_coverage_pct == pytest.approx(100.0)

    def test_provenance_coverage_is_100(self) -> None:
        report = scan_dataset_compliance(CLEAN_DATASET, sign=False)
        assert report.provenance_coverage_pct == pytest.approx(100.0)

    def test_row_count(self) -> None:
        report = scan_dataset_compliance(CLEAN_DATASET, sign=False)
        assert report.row_count == 5

    def test_file_count(self) -> None:
        report = scan_dataset_compliance(CLEAN_DATASET, sign=False)
        assert report.file_count == 1

    def test_scan_id_non_empty(self) -> None:
        report = scan_dataset_compliance(CLEAN_DATASET, sign=False)
        assert len(report.scan_id) == 26  # ULID is 26 chars

    def test_scanned_at_iso8601(self) -> None:
        report = scan_dataset_compliance(CLEAN_DATASET, sign=False)
        # Basic check — should end with timezone info or +00:00
        assert "T" in report.scanned_at and (
            report.scanned_at.endswith("+00:00") or report.scanned_at.endswith("Z")
        )


class TestPiiDataset:
    def test_article10a_fails(self) -> None:
        report = scan_dataset_compliance(PII_DATASET, sign=False)
        art10a = next(c for c in report.eu_ai_act_article_10_clauses if c.clause_id == "Art.10(2)(a)")
        assert not art10a.passed, "Art.10(2)(a) should FAIL for a PII-laden dataset"

    def test_pii_density_above_zero(self) -> None:
        report = scan_dataset_compliance(PII_DATASET, sign=False)
        assert report.pii_density_score > 0.0

    def test_other_clauses_still_evaluated(self) -> None:
        report = scan_dataset_compliance(PII_DATASET, sign=False)
        assert len(report.eu_ai_act_article_10_clauses) == 4


class TestNoConsentDataset:
    def test_article10b_fails(self) -> None:
        report = scan_dataset_compliance(NO_CONSENT_DATASET, sign=False)
        art10b = next(c for c in report.eu_ai_act_article_10_clauses if c.clause_id == "Art.10(2)(b)")
        assert not art10b.passed, "Art.10(2)(b) should FAIL — no consent field"

    def test_consent_coverage_is_zero(self) -> None:
        report = scan_dataset_compliance(NO_CONSENT_DATASET, sign=False)
        assert report.consent_coverage_pct == pytest.approx(0.0)

    def test_provenance_coverage_is_100(self) -> None:
        report = scan_dataset_compliance(NO_CONSENT_DATASET, sign=False)
        assert report.provenance_coverage_pct == pytest.approx(100.0)


class TestJsonOutput:
    def test_to_json_is_valid_json(self) -> None:
        report = scan_dataset_compliance(CLEAN_DATASET, sign=False)
        parsed = json.loads(report.to_json())
        assert isinstance(parsed, dict)

    def test_to_json_has_required_fields(self) -> None:
        report = scan_dataset_compliance(CLEAN_DATASET, sign=False)
        parsed: dict[str, Any] = json.loads(report.to_json())
        required = {
            "scan_id", "scanned_at", "dataset_path", "file_count", "row_count",
            "token_estimate", "pii_density_score", "consent_coverage_pct",
            "provenance_coverage_pct", "bias_signal", "eu_ai_act_article_10_clauses",
            "hmac_signature",
        }
        missing = required - set(parsed.keys())
        assert not missing, f"Missing fields in JSON output: {missing}"

    def test_to_json_clauses_are_complete(self) -> None:
        report = scan_dataset_compliance(CLEAN_DATASET, sign=False)
        parsed = json.loads(report.to_json())
        clauses = parsed["eu_ai_act_article_10_clauses"]
        assert len(clauses) == 4
        ids = {c["clause_id"] for c in clauses}
        assert ids == {"Art.10(2)(a)", "Art.10(2)(b)", "Art.10(2)(c)", "Art.10(2)(d)"}


class TestMarkdownOutput:
    def test_to_markdown_contains_heading(self) -> None:
        report = scan_dataset_compliance(CLEAN_DATASET, sign=False)
        md = report.to_markdown()
        assert "EU AI Act Article 10" in md

    def test_to_markdown_contains_all_clause_ids(self) -> None:
        report = scan_dataset_compliance(CLEAN_DATASET, sign=False)
        md = report.to_markdown()
        for clause_id in ("Art.10(2)(a)", "Art.10(2)(b)", "Art.10(2)(c)", "Art.10(2)(d)"):
            assert clause_id in md


class TestHmacSigning:
    def test_hmac_signature_format(self) -> None:
        report = scan_dataset_compliance(CLEAN_DATASET, sign=True)
        assert report.hmac_signature.startswith("hmac-sha256:")

    def test_hmac_signature_verifiable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify that the HMAC can be re-derived from the report body."""
        test_key = "test-signing-key-for-unit-tests"
        monkeypatch.setenv("SPANFORGE_SIGNING_KEY", test_key)

        report = scan_dataset_compliance(CLEAN_DATASET, sign=True)
        body_json = json.dumps(report._body_dict(), sort_keys=True)

        expected_hex = hmac.new(
            test_key.encode("utf-8"),
            body_json.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        assert report.hmac_signature == f"hmac-sha256:{expected_hex}"

    def test_no_sign_yields_empty_signature(self) -> None:
        report = scan_dataset_compliance(CLEAN_DATASET, sign=False)
        assert report.hmac_signature == ""


class TestCsvLoading:
    def test_csv_file(self, tmp_path: pathlib.Path) -> None:
        csv_file = tmp_path / "data.csv"
        csv_file.write_text(
            "text,source,consent\n"
            "Hello world training example,web,true\n"
            "Another sample row,book,true\n",
            encoding="utf-8",
        )
        report = scan_dataset_compliance(csv_file, sign=False)
        assert report.row_count == 2
        assert report.consent_coverage_pct == pytest.approx(100.0)
        assert report.provenance_coverage_pct == pytest.approx(100.0)


class TestTxtLoading:
    def test_txt_file(self, tmp_path: pathlib.Path) -> None:
        txt_file = tmp_path / "data.txt"
        txt_file.write_text(
            "First line of training text\nSecond line of training text\n",
            encoding="utf-8",
        )
        report = scan_dataset_compliance(txt_file, sign=False)
        assert report.row_count == 2
        # Plain text rows have no consent or source fields
        assert report.consent_coverage_pct == pytest.approx(0.0)


class TestDirectoryScanning:
    def test_mixed_directory(self, tmp_path: pathlib.Path) -> None:
        """Directory with JSONL + CSV should aggregate all rows."""
        (tmp_path / "part1.jsonl").write_text(
            '{"text": "row1", "source": "web", "consent": true}\n'
            '{"text": "row2", "source": "web", "consent": true}\n',
            encoding="utf-8",
        )
        (tmp_path / "part2.csv").write_text(
            "text,source,consent\nrow3,book,true\n",
            encoding="utf-8",
        )
        report = scan_dataset_compliance(tmp_path, sign=False)
        assert report.file_count == 2
        assert report.row_count == 3


class TestEdgeCases:
    def test_empty_directory_raises_no_error(self, tmp_path: pathlib.Path) -> None:
        report = scan_dataset_compliance(tmp_path, sign=False)
        assert report.row_count == 0
        assert report.file_count == 0
        assert report.pii_density_score == pytest.approx(0.0)
        # Empty datasets vacuously pass all coverage checks
        assert report.consent_coverage_pct == pytest.approx(100.0)
        assert report.provenance_coverage_pct == pytest.approx(100.0)

    def test_empty_jsonl_file(self, tmp_path: pathlib.Path) -> None:
        (tmp_path / "empty.jsonl").write_text("", encoding="utf-8")
        report = scan_dataset_compliance(tmp_path, sign=False)
        assert report.row_count == 0

    def test_nonexistent_path_raises(self) -> None:
        with pytest.raises(FileNotFoundError):
            scan_dataset_compliance("/nonexistent/path/to/dataset")

    def test_single_file_scan(self) -> None:
        report = scan_dataset_compliance(CLEAN_DATASET / "data.jsonl", sign=False)
        assert report.file_count == 1
        assert report.row_count == 5


class TestArticle10ClauseDataclass:
    def test_to_dict_fields(self) -> None:
        clause = Article10Clause(
            clause_id="Art.10(2)(a)",
            title="Data quality — PII density",
            passed=True,
            detail="within threshold",
        )
        d = clause.to_dict()
        assert d["clause_id"] == "Art.10(2)(a)"
        assert d["passed"] is True
        assert "title" in d
        assert "detail" in d


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------


class TestCliComplianceValidateDataset:
    """Test ``spanforge compliance validate-dataset`` via direct main() invocation."""

    def test_clean_dataset_exits_zero(self) -> None:
        rc, _ = _run_cli("compliance", "validate-dataset", str(CLEAN_DATASET), "--no-sign")
        assert rc == 0

    def test_pii_dataset_exits_nonzero(self) -> None:
        rc, _ = _run_cli("compliance", "validate-dataset", str(PII_DATASET), "--no-sign")
        assert rc != 0

    def test_json_output_clean_dataset(self) -> None:
        rc, stdout = _run_cli(
            "compliance", "validate-dataset", str(CLEAN_DATASET),
            "--output", "json", "--no-sign",
        )
        assert rc == 0
        parsed = json.loads(stdout)
        assert "eu_ai_act_article_10_clauses" in parsed

    def test_no_consent_exits_nonzero(self) -> None:
        rc, _ = _run_cli(
            "compliance", "validate-dataset", str(NO_CONSENT_DATASET), "--no-sign",
        )
        assert rc != 0

    def test_nonexistent_path_exits_nonzero(self) -> None:
        rc, _ = _run_cli("compliance", "validate-dataset", "/nonexistent/path")
        assert rc != 0


class TestCliValidateDataset:
    """Test the ``spanforge validate --dataset`` top-level command."""

    def test_clean_dataset_exits_zero(self) -> None:
        rc, _ = _run_cli("validate", "--dataset", str(CLEAN_DATASET), "--no-sign")
        assert rc == 0

    def test_json_output(self) -> None:
        rc, stdout = _run_cli(
            "validate", "--dataset", str(CLEAN_DATASET),
            "--output", "json", "--no-sign",
        )
        assert rc == 0
        parsed = json.loads(stdout)
        assert "scan_id" in parsed

    def test_pii_dataset_exits_nonzero(self) -> None:
        rc, _ = _run_cli("validate", "--dataset", str(PII_DATASET), "--no-sign")
        assert rc != 0


class TestPdfOutput:
    """Test ``--output pdf`` for compliance validate-dataset."""

    def test_pdf_output_creates_file(self, tmp_path: pathlib.Path) -> None:
        pytest.importorskip("reportlab")
        dataset = tmp_path / "data.jsonl"
        dataset.write_text(
            '{"text": "sample row", "source": "web", "consent": true}\n',
            encoding="utf-8",
        )
        rc, stdout = _run_cli(
            "compliance", "validate-dataset", str(tmp_path),
            "--output", "pdf", "--no-sign",
        )
        assert rc == 0, f"Expected exit 0, got {rc}; stdout: {stdout}"
        assert "PDF report written to" in stdout
        # The PDF file must exist on disk
        pdf_files = list(tmp_path.glob("*.pdf"))
        assert pdf_files, "Expected a PDF file to be written"

    def test_pdf_output_missing_reportlab(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When reportlab is not installed the CLI should print a clear error."""
        import importlib
        import sys

        dataset = tmp_path / "data.jsonl"
        dataset.write_text('{"text": "sample"}\n', encoding="utf-8")

        # Hide reportlab from the import system temporarily
        monkeypatch.setitem(sys.modules, "reportlab", None)  # type: ignore[arg-type]

        rc, _ = _run_cli(
            "compliance", "validate-dataset", str(tmp_path),
            "--output", "pdf", "--no-sign",
        )
        assert rc == 1


class TestAuditCheckHealthComplianceReport:
    """Test ``spanforge audit check-health`` with a DatasetComplianceReport JSON file."""

    def _write_report_json(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
        key: str = "test-audit-key",
    ) -> pathlib.Path:
        monkeypatch.setenv("SPANFORGE_SIGNING_KEY", key)
        report = scan_dataset_compliance(CLEAN_DATASET, sign=True)
        report_path = tmp_path / "compliance_report.json"
        report_path.write_text(report.to_json(), encoding="utf-8")
        return report_path

    def test_valid_report_exits_zero(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        key = "test-audit-key-valid"
        report_path = self._write_report_json(tmp_path, monkeypatch, key)
        rc, stdout = _run_cli("audit", "check-health", str(report_path))
        assert rc == 0, f"Expected exit 0; stdout:\n{stdout}"
        assert "PASS" in stdout
        assert "Signature valid" in stdout

    def test_tampered_report_exits_nonzero(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        key = "test-audit-key-tamper"
        report_path = self._write_report_json(tmp_path, monkeypatch, key)
        data = json.loads(report_path.read_text(encoding="utf-8"))
        data["row_count"] = data["row_count"] + 999  # tamper
        report_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        rc, stdout = _run_cli("audit", "check-health", str(report_path))
        assert rc == 1
        assert "mismatch" in stdout.lower() or "tampered" in stdout.lower() or "FAIL" in stdout

    def test_json_output_format(
        self,
        tmp_path: pathlib.Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        key = "test-audit-key-json"
        report_path = self._write_report_json(tmp_path, monkeypatch, key)
        rc, stdout = _run_cli("audit", "check-health", str(report_path), "--output", "json")
        assert rc == 0
        parsed = json.loads(stdout)
        assert parsed["report_type"] == "DatasetComplianceReport"
        assert parsed["result"] == "pass"
        assert any(c["name"] == "hmac_signature" for c in parsed["checks"])

    def test_regular_jsonl_still_works(self, tmp_path: pathlib.Path) -> None:
        """Ensure non-compliance-report JSONL files still go through the events path."""
        jsonl = tmp_path / "events.jsonl"
        jsonl.write_text('{"schema": "spanforge.event.v1", "event_id": "abc"}\n', encoding="utf-8")
        rc, stdout = _run_cli("audit", "check-health", str(jsonl))
        # Should NOT raise; exit code depends on chain verification
        assert isinstance(rc, int)
        assert "DatasetComplianceReport" not in stdout
