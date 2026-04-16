"""Tests for spanforge.stats — latency / percentile helpers."""
from __future__ import annotations

import pytest

from spanforge.stats import latency_summary, percentile


# ---------------------------------------------------------------------------
# percentile()
# ---------------------------------------------------------------------------

class TestPercentile:
    def test_single_value(self):
        assert percentile([42.0], 0) == 42.0
        assert percentile([42.0], 50) == 42.0
        assert percentile([42.0], 100) == 42.0

    def test_two_values_median(self):
        result = percentile([10.0, 20.0], 50)
        assert result == pytest.approx(15.0)

    def test_p0_returns_min(self):
        data = [5.0, 3.0, 8.0, 1.0]
        assert percentile(data, 0) == pytest.approx(1.0)

    def test_p100_returns_max(self):
        data = [5.0, 3.0, 8.0, 1.0]
        assert percentile(data, 100) == pytest.approx(8.0)

    def test_p50_even_list(self):
        data = [1.0, 2.0, 3.0, 4.0]
        result = percentile(data, 50)
        assert result == pytest.approx(2.5)

    def test_p95_standard(self):
        data = list(range(1, 101))  # 1..100
        result = percentile(data, 95)
        assert result == pytest.approx(95.05, abs=0.5)

    def test_sorted_vs_unsorted_same(self):
        data = [50.0, 10.0, 90.0, 30.0, 70.0]
        assert percentile(data, 50) == percentile(sorted(data), 50)

    def test_invalid_p_below_zero(self):
        with pytest.raises(ValueError, match="p"):
            percentile([1.0, 2.0], -1)

    def test_invalid_p_above_100(self):
        with pytest.raises(ValueError, match="p"):
            percentile([1.0, 2.0], 101)

    def test_empty_list_returns_zero(self):
        # percentile() returns 0.0 for empty input (latency_summary guards this)
        assert percentile([], 50) == 0.0

    def test_does_not_mutate_input(self):
        data = [3.0, 1.0, 2.0]
        original = data.copy()
        percentile(data, 50)
        assert data == original

    def test_returns_float(self):
        result = percentile([1, 2, 3], 50)  # int inputs
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# latency_summary()
# ---------------------------------------------------------------------------

class TestLatencySummary:
    def test_empty_returns_zeros(self):
        summary = latency_summary([])
        assert summary["count"] == 0
        assert summary["mean"] == 0.0
        assert summary["min"] == 0.0
        assert summary["max"] == 0.0
        assert summary["p50"] == 0.0
        assert summary["p95"] == 0.0
        assert summary["p99"] == 0.0

    def test_all_keys_present(self):
        summary = latency_summary([100.0, 200.0])
        for key in ("count", "mean", "min", "max", "p50", "p95", "p99"):
            assert key in summary

    def test_single_value(self):
        summary = latency_summary([42.0])
        assert summary["count"] == 1
        assert summary["mean"] == 42.0
        assert summary["min"] == 42.0
        assert summary["max"] == 42.0
        assert summary["p50"] == 42.0
        assert summary["p95"] == 42.0
        assert summary["p99"] == 42.0

    def test_count_correct(self):
        summary = latency_summary([10.0] * 50)
        assert summary["count"] == 50

    def test_mean_correct(self):
        summary = latency_summary([10.0, 20.0, 30.0])
        assert summary["mean"] == pytest.approx(20.0)

    def test_min_max_correct(self):
        summary = latency_summary([5.0, 10.0, 1.0, 8.0])
        assert summary["min"] == pytest.approx(1.0)
        assert summary["max"] == pytest.approx(10.0)

    def test_values_rounded_to_3dp(self):
        summary = latency_summary([1.0, 3.0])
        # mean is 2.0 — already 3dp
        result = round(summary["mean"], 4)
        # Ensure it wasn't truncated past 3dp
        assert str(summary["mean"]).count(".") <= 1

    def test_p99_greater_equal_p95(self):
        data = list(range(1, 201))
        summary = latency_summary(data)
        assert summary["p99"] >= summary["p95"]

    def test_p95_greater_equal_p50(self):
        data = list(range(1, 201))
        summary = latency_summary(data)
        assert summary["p95"] >= summary["p50"]
