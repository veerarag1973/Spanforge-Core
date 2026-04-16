"""spanforge.stats — Latency percentile and summary statistics.

Lightweight, dependency-free statistics helpers for latency analysis.  All
inputs are plain Python lists; no NumPy or pandas required.

Usage::

    from spanforge.stats import percentile, latency_summary

    latencies_ms = [12.3, 45.6, 23.1, 89.4, 34.7]

    p95 = percentile(latencies_ms, 95)
    summary = latency_summary(latencies_ms)
    print(summary)
    # {'count': 5, 'mean': 41.02, 'min': 12.3, 'max': 89.4,
    #  'p50': 34.7, 'p95': 89.4, 'p99': 89.4}
"""

from __future__ import annotations

import statistics
from typing import Any

__all__ = [
    "latency_summary",
    "percentile",
]


def percentile(values: list[float], p: float) -> float:
    """Return the *p*-th percentile of *values* using linear interpolation.

    Args:
        values:  List of numeric values (need not be sorted).
        p:       Percentile in the range ``[0, 100]``.

    Returns:
        The interpolated percentile value, or ``0.0`` for an empty list.

    Raises:
        ValueError:  If *p* is not in ``[0, 100]``.

    Example::

        percentile([1.0, 2.0, 3.0, 4.0, 5.0], 50)   # → 3.0
        percentile([1.0, 2.0, 3.0, 4.0, 5.0], 95)   # → 4.8
    """
    if not 0.0 <= p <= 100.0:
        raise ValueError(f"p must be in [0, 100], got {p!r}")
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    if n == 1:
        return float(sorted_vals[0])
    idx = (p / 100.0) * (n - 1)
    lo = int(idx)
    hi = lo + 1
    if hi >= n:
        return float(sorted_vals[-1])
    frac = idx - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def latency_summary(values_ms: list[float]) -> dict[str, Any]:
    """Return a summary statistics dict for a list of latency measurements.

    Args:
        values_ms:  List of latency values in milliseconds.

    Returns:
        A dict with keys ``count``, ``mean``, ``min``, ``max``, ``p50``,
        ``p95``, and ``p99``.  All float values are rounded to 3 decimal
        places.  Returns zeroed-out values for an empty list.

    Example::

        summary = latency_summary([10.0, 20.0, 30.0, 40.0, 50.0])
        # {'count': 5, 'mean': 30.0, 'min': 10.0, 'max': 50.0,
        #  'p50': 30.0, 'p95': 48.0, 'p99': 49.6}
    """
    if not values_ms:
        return {
            "count": 0,
            "mean": 0.0,
            "min": 0.0,
            "max": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "p99": 0.0,
        }
    return {
        "count": len(values_ms),
        "mean": round(statistics.mean(values_ms), 3),
        "min": round(min(values_ms), 3),
        "max": round(max(values_ms), 3),
        "p50": round(percentile(values_ms, 50), 3),
        "p95": round(percentile(values_ms, 95), 3),
        "p99": round(percentile(values_ms, 99), 3),
    }
