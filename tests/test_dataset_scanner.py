"""Tests for the 1C-4 Training Data Compliance Scanner.

Covers:
* spanforge.validate.scan_dataset (core logic)
* spanforge _cli.py: ``sf validate --dataset`` subcommand
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from spanforge.validate import (
    DatasetScanFinding,
    DatasetScanReport,
    scan_dataset,
)


# ===========================================================================
# Core scan_dataset tests
# ===========================================================================


class TestScanDatasetClean:
    def test_clean_rows_returns_zero_findings(self) -> None:
        rows = [
            {"prompt": "What is the capital of France?", "response": "Paris"},
            {"prompt": "Hello", "response": "Hi there"},
        ]
        report = scan_dataset(rows)
        assert report.total_rows == 2
        assert report.total_findings == 0
        assert report.clean_rows == 2
        assert report.pii_hits == 0

    def test_empty_dataset_returns_zero_counts(self) -> None:
        report = scan_dataset([])
        assert report.total_rows == 0
        assert report.total_findings == 0
        assert report.clean_rows == 0

    def test_report_type(self) -> None:
        report = scan_dataset([{"key": "value"}])
        assert isinstance(report, DatasetScanReport)


class TestScanDatasetPII:
    def test_detects_email_in_value(self) -> None:
        rows = [{"prompt": "Contact me at alice@example.com for details"}]
        report = scan_dataset(rows)
        assert report.pii_hits >= 1
        pii_issues = [f for f in report.findings if f.issue_type == "pii_value"]
        assert any("email" in f.detail for f in pii_issues)

    def test_detects_phone_number_in_value(self) -> None:
        rows = [{"contact": "Call us at 555-867-5309 any time"}]
        report = scan_dataset(rows)
        assert report.pii_hits >= 1

    def test_detects_ssn_in_value(self) -> None:
        rows = [{"data": "SSN: 123-45-6789"}]
        report = scan_dataset(rows)
        assert report.pii_hits >= 1
        ssn_issues = [f for f in report.findings if "SSN" in f.detail]
        assert len(ssn_issues) >= 1

    def test_detects_pii_field_name(self) -> None:
        rows = [{"email": "not-actually-pii-here", "name": "Alice"}]
        report = scan_dataset(rows)
        field_name_issues = [f for f in report.findings if f.issue_type == "pii_field_name"]
        assert len(field_name_issues) >= 1
        assert any(f.field == "email" for f in field_name_issues)

    def test_detects_phone_field_name(self) -> None:
        rows = [{"phone": "555-000-0000"}]
        report = scan_dataset(rows)
        assert report.pii_hits >= 1

    def test_pii_field_name_check_can_be_disabled(self) -> None:
        rows = [{"email": "legit-field-no-pii-value"}]
        report = scan_dataset(rows, check_pii_field_names=False)
        field_name_issues = [f for f in report.findings if f.issue_type == "pii_field_name"]
        assert len(field_name_issues) == 0

    def test_pii_value_check_can_be_disabled(self) -> None:
        rows = [{"content": "Email: test@example.org"}]
        report = scan_dataset(rows, check_pii_values=False)
        value_issues = [f for f in report.findings if f.issue_type == "pii_value"]
        assert len(value_issues) == 0


class TestScanDatasetRequiredFields:
    def test_missing_required_field_raises_schema_violation(self) -> None:
        rows = [{"prompt": "Hello"}, {"response": "Hi"}]
        report = scan_dataset(rows, required_fields=["prompt", "response"])
        violations = [f for f in report.findings if f.issue_type == "schema_violation"]
        assert len(violations) >= 1

    def test_all_required_fields_present_no_violation(self) -> None:
        rows = [{"prompt": "Q", "response": "A"}]
        report = scan_dataset(rows, required_fields=["prompt", "response"])
        violations = [f for f in report.findings if f.issue_type == "schema_violation"]
        assert len(violations) == 0


class TestScanDatasetSummaryCounts:
    def test_clean_rows_count_is_accurate(self) -> None:
        rows = [
            {"prompt": "Clean row"},
            {"email": "pii-field"},  # PII field name
            {"prompt": "Another clean row"},
        ]
        report = scan_dataset(rows)
        assert report.clean_rows == 2
        assert report.total_rows == 3

    def test_findings_row_numbers_are_1_based(self) -> None:
        rows = [{"ssn_number": "secret"}]
        report = scan_dataset(rows)
        assert report.findings[0].row == 1


# ===========================================================================
# CLI --dataset tests
# ===========================================================================


def _run_cli(*args: str) -> tuple[int, str]:
    """Run the spanforge CLI main() with given args and capture stdout."""
    import io
    import sys
    from unittest.mock import patch

    from spanforge._cli import main

    buf = io.StringIO()
    with patch("sys.stdout", buf), patch("sys.argv", ["spanforge", *args]):
        try:
            rc = main()
        except SystemExit as exc:
            rc = int(exc.code) if exc.code is not None else 0
    return rc, buf.getvalue()


class TestCLIDatasetScanner:
    def test_clean_jsonl_returns_zero(self, tmp_path: Path) -> None:
        f = tmp_path / "data.jsonl"
        f.write_text(
            '{"prompt": "What is AI?", "response": "Artificial Intelligence"}\n'
            '{"prompt": "Hello", "response": "World"}\n',
            encoding="utf-8",
        )
        rc, out = _run_cli("validate", "--dataset", str(f))
        assert rc == 0

    def test_pii_jsonl_reported_but_zero_exit_by_default(self, tmp_path: Path) -> None:
        f = tmp_path / "pii.jsonl"
        f.write_text(
            '{"prompt": "My email is bob@corp.example.com", "response": "ok"}\n',
            encoding="utf-8",
        )
        rc, out = _run_cli("validate", "--dataset", str(f))
        # Default behaviour: report findings but exit 0
        assert rc == 0

    def test_fail_on_violations_returns_1_when_pii_found(self, tmp_path: Path) -> None:
        f = tmp_path / "pii2.jsonl"
        f.write_text(
            '{"data": "Call 555-123-4567 for help"}\n',
            encoding="utf-8",
        )
        rc, out = _run_cli("validate", "--dataset", str(f), "--fail-on-violations")
        assert rc == 1

    def test_json_format_output(self, tmp_path: Path) -> None:
        f = tmp_path / "data.jsonl"
        f.write_text('{"prompt": "Hello", "response": "Hi"}\n', encoding="utf-8")
        rc, out = _run_cli("validate", "--dataset", str(f), "--format", "json")
        assert rc == 0
        parsed = json.loads(out)
        assert "total_rows" in parsed
        assert "pii_hits" in parsed
        assert "findings" in parsed

    def test_missing_dataset_file_returns_2(self, tmp_path: Path) -> None:
        import io
        import sys
        from unittest.mock import patch

        from spanforge._cli import main

        buf_err = io.StringIO()
        with patch("sys.stderr", buf_err), patch(
            "sys.argv", ["spanforge", "validate", "--dataset", str(tmp_path / "nonexistent.jsonl")]
        ):
            try:
                rc = main()
            except SystemExit as exc:
                rc = int(exc.code) if exc.code is not None else 0
        assert rc == 2

    def test_empty_jsonl_returns_0_with_zero_counts(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        rc, out = _run_cli("validate", "--dataset", str(f), "--format", "json")
        assert rc == 0
        parsed = json.loads(out)
        assert parsed["total_rows"] == 0
        assert parsed["total_findings"] == 0

    def test_required_fields_flag_reports_missing_fields(self, tmp_path: Path) -> None:
        f = tmp_path / "data.jsonl"
        f.write_text('{"prompt": "Hello"}\n', encoding="utf-8")
        rc, out = _run_cli(
            "validate",
            "--dataset",
            str(f),
            "--required-fields",
            "prompt,response",
            "--format",
            "json",
        )
        parsed = json.loads(out)
        assert parsed["schema_violations"] >= 1
