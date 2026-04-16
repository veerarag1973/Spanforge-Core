"""spanforge.regression — Generic pass/fail regression detection.

Provides :class:`RegressionDetector` for comparing two evaluation runs and
surfacing cases that have *regressed*: passing in the baseline but failing in
the current run, or whose score dropped by more than a configurable threshold.

Unlike :class:`spanforge.eval.RegressionDetector` (which compares mean metric
scores between runs), this detector operates on individual result records with
explicit ``passed`` and ``score`` fields — making it well-suited for CI gates
where each test case must individually pass.

Usage::

    from spanforge.regression import RegressionDetector

    detector = RegressionDetector(score_drop_threshold=0.1)
    report = detector.compare(
        baseline=baseline_results,
        current=current_results,
        key_fn=lambda r: (r["case_id"], r["scorer_name"]),
        passed_fn=lambda r: r["passed"],
        score_fn=lambda r: r["score"],
    )

    if report.has_regression:
        for item in report.new_failures:
            print("NEW FAILURE:", item)
        for base, curr in report.score_drops:
            print(f"SCORE DROP: {base} → {curr}")
        sys.exit(1)

Works with any record type (dicts, dataclasses, etc.) via the *key_fn*,
*passed_fn*, and *score_fn* callbacks.  There is also a convenience
:func:`compare` top-level function for one-shot use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Generic, TypeVar

__all__ = [
    "RegressionDetector",
    "RegressionReport",
    "compare",
]

T = TypeVar("T")


@dataclass
class RegressionReport(Generic[T]):
    """Summary of regressions found between two evaluation runs.

    Attributes:
        new_failures:  Items that *passed* in the baseline but *fail* in the
                       current run.
        score_drops:   ``(baseline_item, current_item)`` pairs where the score
                       dropped by at least the configured threshold.
    """

    new_failures: list[T] = field(default_factory=list)
    score_drops: list[tuple[T, T]] = field(default_factory=list)

    @property
    def has_regression(self) -> bool:
        """``True`` when at least one regression was detected."""
        return bool(self.new_failures or self.score_drops)

    def summary(self) -> str:
        """Return a short human-readable summary string."""
        parts: list[str] = []
        if self.new_failures:
            parts.append(f"{len(self.new_failures)} new failure(s)")
        if self.score_drops:
            parts.append(f"{len(self.score_drops)} score drop(s)")
        if not parts:
            return "no regression detected"
        return "; ".join(parts)


class RegressionDetector(Generic[T]):
    """Compare two evaluation runs and report regressions.

    A *regression* is one of:

    * A key that **passed** in the baseline but **fails** in the current run.
    * A key whose score **dropped** by at least *score_drop_threshold*
      (even when the current result still passes).

    New keys that appear only in the current run are **not** flagged as
    regressions (they may be new test cases).  Keys that disappear from the
    current run are also silently ignored.

    Args:
        score_drop_threshold:  Minimum absolute score decrease that
                               constitutes a regression.  Default is ``0.1``.

    Example::

        detector = RegressionDetector[dict](score_drop_threshold=0.05)
        report = detector.compare(
            baseline, current,
            key_fn=lambda r: (r["case_id"], r["scorer"]),
            passed_fn=lambda r: r["passed"],
            score_fn=lambda r: r["score"],
        )
        print(report.summary())
    """

    def __init__(self, score_drop_threshold: float = 0.1) -> None:
        self.score_drop_threshold = score_drop_threshold

    def compare(
        self,
        baseline: list[T],
        current: list[T],
        *,
        key_fn: Callable[[T], Any],
        passed_fn: Callable[[T], bool],
        score_fn: Callable[[T], float],
    ) -> "RegressionReport[T]":
        """Compare *current* against *baseline* and return a :class:`RegressionReport`.

        Args:
            baseline:   Results from a known-good previous run.
            current:    Results from the run being checked.
            key_fn:     Callable that returns a hashable key identifying a
                        result (e.g. ``lambda r: (r.case_id, r.scorer_name)``).
            passed_fn:  Callable that returns ``True`` when a result passed.
            score_fn:   Callable that returns the numeric score of a result.

        Returns:
            A :class:`RegressionReport` describing found regressions.
        """
        baseline_map: dict[Any, T] = {key_fn(r): r for r in baseline}
        current_map: dict[Any, T] = {key_fn(r): r for r in current}

        new_failures: list[T] = []
        score_drops: list[tuple[T, T]] = []

        for key, curr in current_map.items():
            base = baseline_map.get(key)
            if base is None:
                continue  # new key — not a regression

            if passed_fn(base) and not passed_fn(curr):
                new_failures.append(curr)
            elif (score_fn(base) - score_fn(curr)) >= self.score_drop_threshold:
                score_drops.append((base, curr))

        return RegressionReport(new_failures=new_failures, score_drops=score_drops)


def compare(
    baseline: list[Any],
    current: list[Any],
    *,
    key_fn: Callable[[Any], Any],
    passed_fn: Callable[[Any], bool],
    score_fn: Callable[[Any], float],
    score_drop_threshold: float = 0.1,
) -> RegressionReport[Any]:
    """One-shot convenience wrapper around :class:`RegressionDetector`.

    Args:
        baseline:              Results from the baseline run.
        current:               Results from the run being checked.
        key_fn:                Returns a unique key for each result.
        passed_fn:             Returns ``True`` when a result passed.
        score_fn:              Returns the numeric score of a result.
        score_drop_threshold:  Minimum score drop to flag as regression.

    Returns:
        A :class:`RegressionReport`.

    Example::

        report = compare(
            baseline, current,
            key_fn=lambda r: r["id"],
            passed_fn=lambda r: r["ok"],
            score_fn=lambda r: r["score"],
        )
    """
    return RegressionDetector(score_drop_threshold=score_drop_threshold).compare(
        baseline,
        current,
        key_fn=key_fn,
        passed_fn=passed_fn,
        score_fn=score_fn,
    )
