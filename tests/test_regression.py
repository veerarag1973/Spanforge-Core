"""Tests for spanforge.regression — pass/fail regression detection."""
from __future__ import annotations

import pytest

from spanforge.regression import RegressionDetector, RegressionReport, compare


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_results(data: dict[str, tuple[bool, float]]):
    """Create list of dicts keyed by test id with passed and score fields."""
    return [
        {"id": k, "passed": v[0], "score": v[1]}
        for k, v in data.items()
    ]


def _key_fn(item: dict) -> str:
    return item["id"]


def _passed_fn(item: dict) -> bool:
    return item["passed"]


def _score_fn(item: dict) -> float:
    return item["score"]


# ---------------------------------------------------------------------------
# RegressionReport
# ---------------------------------------------------------------------------

class TestRegressionReport:
    def test_no_regression_when_empty(self):
        report = RegressionReport(new_failures=[], score_drops=[])
        assert not report.has_regression

    def test_has_regression_on_new_failure(self):
        item = {"id": "tc-001", "passed": False, "score": 0.0}
        report = RegressionReport(new_failures=[item], score_drops=[])
        assert report.has_regression

    def test_has_regression_on_score_drop(self):
        old = {"id": "tc-001", "passed": True, "score": 0.9}
        new = {"id": "tc-001", "passed": True, "score": 0.7}
        report = RegressionReport(new_failures=[], score_drops=[(old, new)])
        assert report.has_regression

    def test_summary_lists_new_failures(self):
        item = {"id": "tc-003", "passed": False, "score": 0.1}
        report = RegressionReport(new_failures=[item], score_drops=[])
        summary = report.summary()
        # Summary must indicate at least 1 new failure
        assert "1" in summary and "failure" in summary.lower()

    def test_summary_clean(self):
        report = RegressionReport(new_failures=[], score_drops=[])
        assert "no regression" in report.summary().lower() or "clean" in report.summary().lower()


# ---------------------------------------------------------------------------
# RegressionDetector.compare
# ---------------------------------------------------------------------------

class TestRegressionDetectorCompare:
    def test_no_regression_identical_results(self):
        data = {
            "tc-001": (True, 0.95),
            "tc-002": (True, 0.88),
        }
        baseline = _make_results(data)
        current = _make_results(data)

        detector = RegressionDetector()
        report = detector.compare(baseline, current, key_fn=_key_fn, passed_fn=_passed_fn, score_fn=_score_fn)
        assert not report.has_regression

    def test_new_failure_detected(self):
        baseline = _make_results({"tc-001": (True, 0.9), "tc-002": (True, 0.8)})
        current = _make_results({"tc-001": (True, 0.9), "tc-002": (False, 0.4)})

        detector = RegressionDetector()
        report = detector.compare(baseline, current, key_fn=_key_fn, passed_fn=_passed_fn, score_fn=_score_fn)
        assert report.has_regression
        assert len(report.new_failures) == 1
        assert report.new_failures[0]["id"] == "tc-002"

    def test_score_drop_detected(self):
        baseline = _make_results({"tc-001": (True, 0.95)})
        current = _make_results({"tc-001": (True, 0.75)})  # 0.20 drop > default 0.10 threshold

        detector = RegressionDetector(score_drop_threshold=0.10)
        report = detector.compare(baseline, current, key_fn=_key_fn, passed_fn=_passed_fn, score_fn=_score_fn)
        assert report.has_regression
        assert len(report.score_drops) == 1

    def test_small_score_drop_not_detected(self):
        baseline = _make_results({"tc-001": (True, 0.90)})
        current = _make_results({"tc-001": (True, 0.85)})  # 0.05 drop < 0.10 threshold

        detector = RegressionDetector(score_drop_threshold=0.10)
        report = detector.compare(baseline, current, key_fn=_key_fn, passed_fn=_passed_fn, score_fn=_score_fn)
        assert not report.has_regression

    def test_new_cases_in_current_not_flagged(self):
        baseline = _make_results({"tc-001": (True, 0.9)})
        current = _make_results({"tc-001": (True, 0.9), "tc-002": (True, 0.85)})

        detector = RegressionDetector()
        report = detector.compare(baseline, current, key_fn=_key_fn, passed_fn=_passed_fn, score_fn=_score_fn)
        assert not report.has_regression

    def test_cases_removed_from_current_not_flagged(self):
        baseline = _make_results({"tc-001": (True, 0.9), "tc-002": (True, 0.8)})
        current = _make_results({"tc-001": (True, 0.9)})  # tc-002 missing

        detector = RegressionDetector()
        report = detector.compare(baseline, current, key_fn=_key_fn, passed_fn=_passed_fn, score_fn=_score_fn)
        assert not report.has_regression

    def test_improvement_not_flagged(self):
        baseline = _make_results({"tc-001": (True, 0.70)})
        current = _make_results({"tc-001": (True, 0.95)})  # improvement

        detector = RegressionDetector()
        report = detector.compare(baseline, current, key_fn=_key_fn, passed_fn=_passed_fn, score_fn=_score_fn)
        assert not report.has_regression

    def test_empty_baseline_and_current(self):
        detector = RegressionDetector()
        report = detector.compare([], [], key_fn=_key_fn, passed_fn=_passed_fn, score_fn=_score_fn)
        assert not report.has_regression

    def test_threshold_exactly_at_boundary(self):
        baseline = _make_results({"tc-001": (True, 0.80)})
        current = _make_results({"tc-001": (True, 0.70)})  # exactly 0.10 drop

        # Default threshold is 0.10; a drop of exactly 0.10 should be flagged
        detector = RegressionDetector(score_drop_threshold=0.10)
        report = detector.compare(baseline, current, key_fn=_key_fn, passed_fn=_passed_fn, score_fn=_score_fn)
        assert report.has_regression

    def test_both_new_failure_and_score_drop(self):
        baseline = _make_results({"a": (True, 0.9), "b": (True, 0.8)})
        current = _make_results({"a": (False, 0.3), "b": (True, 0.5)})

        detector = RegressionDetector(score_drop_threshold=0.10)
        report = detector.compare(baseline, current, key_fn=_key_fn, passed_fn=_passed_fn, score_fn=_score_fn)
        assert report.has_regression
        assert len(report.new_failures) == 1
        assert len(report.score_drops) == 1


# ---------------------------------------------------------------------------
# compare() convenience function
# ---------------------------------------------------------------------------

class TestCompareConvenience:
    def test_returns_regression_report(self):
        baseline = _make_results({"tc-001": (True, 0.9)})
        current = _make_results({"tc-001": (False, 0.2)})

        report = compare(baseline, current, key_fn=_key_fn, passed_fn=_passed_fn, score_fn=_score_fn)
        assert isinstance(report, RegressionReport)
        assert report.has_regression

    def test_accepts_custom_threshold(self):
        baseline = _make_results({"tc-001": (True, 0.90)})
        current = _make_results({"tc-001": (True, 0.85)})

        # With a tight 0.03 threshold, 0.05 drop IS a regression
        report = compare(
            baseline, current,
            key_fn=_key_fn, passed_fn=_passed_fn, score_fn=_score_fn,
            score_drop_threshold=0.03,
        )
        assert report.has_regression
