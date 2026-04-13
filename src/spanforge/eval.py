"""spanforge.eval — Evaluation framework hooks for LLM / agent quality scoring.

This module provides lightweight instrumentation for attaching quality scores
to active spans and emitting them as RFC-0001 ``llm.eval.*`` events.  It is
intentionally infrastructure-agnostic: scores can be produced by RAGAS,
DeepEval, custom rubric LLMs, or simple rule-based checks.

Quick start
-----------
::

    from spanforge import start_span
    from spanforge.eval import record_eval_score, EvalScore

    with start_span("rag_pipeline") as span:
        answer = run_rag(query)
        # Attach an evaluation score to the active span.
        record_eval_score(
            metric="faithfulness",
            value=0.87,
            span_id=span.span_id,
            trace_id=span.trace_id,
            label="pass",
            metadata={"evaluator": "ragas", "version": "0.1.12"},
        )

Batch evaluation
----------------
Use :class:`EvalRunner` to run a set of :class:`EvalScorer` callables over a
list of trace outputs and compare them against a baseline::

    runner = EvalRunner(scorers=[FaithfulnessScorer(), RelevanceScorer()])
    report = runner.run(dataset)
    report.print_summary()

Regression detection
--------------------
:class:`RegressionDetector` detects when mean scores drop below a configurable
threshold relative to a saved baseline and emits
``llm.eval.regression.detected`` events automatically.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, runtime_checkable

__all__ = [
    "EvalReport",
    "EvalRunner",
    "EvalScore",
    "EvalScorer",
    "RegressionDetector",
    "record_eval_score",
]

_log = logging.getLogger("spanforge.eval")

# H13 — span_id / trace_id format patterns (RFC-0001 §8.2)
_SPAN_ID_PAT: re.Pattern[str] = re.compile(r"^[0-9a-f]{16}$")
_TRACE_ID_PAT: re.Pattern[str] = re.compile(r"^[0-9a-f]{32}$")


# ---------------------------------------------------------------------------
# EvalScore dataclass
# ---------------------------------------------------------------------------


@dataclass
class EvalScore:
    """A single quality measurement attached to a span or agent run.

    Args:
        metric:     Name of the metric (e.g. ``"faithfulness"``, ``"toxicity"``).
        value:      Numeric score.  Typically in ``[0.0, 1.0]`` but any float
                    is accepted (some metrics like BLEU can exceed 1.0).
        span_id:    Optional 16-hex-char span ID of the parent span.
        trace_id:   Optional 32-hex-char trace ID.
        label:      Optional string label (``"pass"`` / ``"fail"`` / ``"warn"``).
        metadata:   Optional free-form metadata dict (evaluator version, etc.).
        timestamp:  Unix timestamp (seconds).  Set automatically if omitted.
    """

    metric: str
    value: float
    span_id: str | None = None
    trace_id: str | None = None
    label: str | None = None
    metadata: dict[str, Any] | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "metric": self.metric,
            "value": self.value,
            "timestamp": self.timestamp,
        }
        if self.span_id is not None:
            d["span_id"] = self.span_id
        if self.trace_id is not None:
            d["trace_id"] = self.trace_id
        if self.label is not None:
            d["label"] = self.label
        if self.metadata is not None:
            d["metadata"] = self.metadata
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvalScore":
        return cls(
            metric=data["metric"],
            value=float(data["value"]),
            span_id=data.get("span_id"),
            trace_id=data.get("trace_id"),
            label=data.get("label"),
            metadata=data.get("metadata"),
            timestamp=float(data.get("timestamp", time.time())),
        )


# ---------------------------------------------------------------------------
# record_eval_score — primary public function
# ---------------------------------------------------------------------------


def record_eval_score(
    metric: str,
    value: float,
    *,
    span_id: str | None = None,
    trace_id: str | None = None,
    label: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> EvalScore:
    """Record an evaluation score and emit it as an RFC-0001 event.

    The score is emitted as a ``llm.eval.score.recorded`` event via the
    configured SpanForge exporter.  It is also returned for convenience so
    callers can inspect or store it locally.

    Args:
        metric:   Name of the quality metric.
        value:    Numeric score value.
        span_id:  Optional parent span ID (16 hex chars).
        trace_id: Optional trace ID (32 hex chars).
        label:    Optional human-readable label (``"pass"``/``"fail"``/etc.).
        metadata: Optional free-form dict with evaluator details.

    Returns:
        The :class:`EvalScore` that was recorded and emitted.

    Example::

        score = record_eval_score("faithfulness", 0.92, span_id=span.span_id)
    """
    # H13: validate span_id / trace_id format at the boundary.
    if span_id is not None and not _SPAN_ID_PAT.match(span_id):
        raise ValueError(f"span_id must be 16 lowercase hex chars, got {span_id!r}")
    if trace_id is not None and not _TRACE_ID_PAT.match(trace_id):
        raise ValueError(f"trace_id must be 32 lowercase hex chars, got {trace_id!r}")

    score = EvalScore(
        metric=metric,
        value=value,
        span_id=span_id,
        trace_id=trace_id,
        label=label,
        metadata=metadata,
    )
    try:
        from spanforge._stream import emit_rfc_event  # noqa: PLC0415
        from spanforge.types import EventType  # noqa: PLC0415
        emit_rfc_event(
            EventType.EVAL_SCORE_RECORDED,
            payload=score.to_dict(),
            span_id=span_id,
            trace_id=trace_id,
        )
    except Exception as exc:  # NOSONAR
        _log.warning("spanforge.eval: failed to emit eval score event: %s", exc)

    return score


# ---------------------------------------------------------------------------
# EvalScorer protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class EvalScorer(Protocol):
    """Protocol for evaluation scorers compatible with :class:`EvalRunner`.

    Each scorer must implement :meth:`score` which receives a single example
    dict and returns an :class:`EvalScore`.
    """

    @property
    def metric_name(self) -> str:
        """Unique name of this scorer's metric (e.g. ``"faithfulness"``)."""
        ...

    def score(self, example: dict[str, Any]) -> EvalScore:
        """Score a single example.

        Args:
            example: Dict containing at least ``"output"`` key; may also
                     include ``"reference"``, ``"context"``, ``"span_id"``
                     and ``"trace_id"`` for correlation.

        Returns:
            An :class:`EvalScore` with the metric value.
        """
        ...


# ---------------------------------------------------------------------------
# EvalReport
# ---------------------------------------------------------------------------


@dataclass
class EvalReport:
    """Aggregated result of running multiple scorers over a dataset.

    Args:
        scores:  Flat list of all :class:`EvalScore` instances produced.
        dataset: The dataset used to generate this report.
    """

    scores: list[EvalScore] = field(default_factory=list)
    dataset: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, float]:
        """Return a ``{metric: mean_value}`` dict."""
        from collections import defaultdict  # noqa: PLC0415
        totals: dict[str, list[float]] = defaultdict(list)
        for s in self.scores:
            totals[s.metric].append(s.value)
        return {m: sum(vs) / len(vs) for m, vs in totals.items()}

    def print_summary(self) -> None:  # pragma: no cover
        """Print a human-readable summary table."""
        summary = self.summary()
        print(f"{'Metric':<40}  {'Mean':>10}")
        print("-" * 53)
        for metric, mean in sorted(summary.items()):
            print(f"{metric:<40}  {mean:>10.4f}")
        print("-" * 53)
        print(f"Total scores recorded: {len(self.scores)}")


# ---------------------------------------------------------------------------
# EvalRunner
# ---------------------------------------------------------------------------


class EvalRunner:
    """Run one or more :class:`EvalScorer` callables over a dataset.

    Args:
        scorers:  List of scorers to apply to each example.
        emit:     If ``True`` (default), each score is emitted via
                  :func:`record_eval_score`.  Set to ``False`` to collect
                  scores in-process only.

    Example::

        class FaithfulnessScorer:
            metric_name = "faithfulness"

            def score(self, example):
                # run your faithfulness check here
                return EvalScore("faithfulness", value=..., span_id=example.get("span_id"))

        runner = EvalRunner(scorers=[FaithfulnessScorer()])
        report = runner.run([{"output": "Paris", "reference": "Paris is the capital."}])
        report.print_summary()
    """

    def __init__(
        self,
        scorers: list[EvalScorer] | None = None,
        *,
        emit: bool = True,
    ) -> None:
        self._scorers: list[Any] = list(scorers or [])
        self._emit = emit

    def add_scorer(self, scorer: EvalScorer) -> None:
        """Append *scorer* to the runner."""
        self._scorers.append(scorer)

    def run(self, dataset: list[dict[str, Any]]) -> EvalReport:
        """Score every example in *dataset* with every scorer.

        Args:
            dataset: List of example dicts passed to each scorer's
                     :meth:`~EvalScorer.score` method.

        Returns:
            An :class:`EvalReport` containing all scores.
        """
        all_scores: list[EvalScore] = []
        for example in dataset:
            for scorer in self._scorers:
                try:
                    score = scorer.score(example)
                except Exception as exc:  # NOSONAR
                    _log.warning(
                        "EvalRunner: scorer %r raised on example %r: %s",
                        getattr(scorer, "metric_name", type(scorer).__name__),
                        example,
                        exc,
                    )
                    continue
                if self._emit:
                    try:
                        record_eval_score(
                            metric=score.metric,
                            value=score.value,
                            span_id=score.span_id,
                            trace_id=score.trace_id,
                            label=score.label,
                            metadata=score.metadata,
                        )
                    except Exception as exc:  # NOSONAR
                        _log.warning("EvalRunner: emit failed: %s", exc)
                all_scores.append(score)
        return EvalReport(scores=all_scores, dataset=dataset)


# ---------------------------------------------------------------------------
# RegressionDetector
# ---------------------------------------------------------------------------


class RegressionDetector:
    """Detect quality regressions by comparing current scores against a baseline.

    When the mean score for a metric drops below
    ``baseline_mean * (1 - threshold_pct / 100)`` the detector emits a
    ``llm.eval.regression.detected`` RFC-0001 event.

    Args:
        baseline:       ``{metric: baseline_mean}`` dict.  Use :meth:`set_baseline`.
        threshold_pct:  Float percentage drop that triggers a regression.
                        Default: ``5.0`` (5 % drop).
        emit:           If ``True`` (default), regression events are emitted.

    Example::

        detector = RegressionDetector(baseline={"faithfulness": 0.90}, threshold_pct=5.0)
        detector.check(report)
    """

    def __init__(
        self,
        baseline: dict[str, float] | None = None,
        *,
        threshold_pct: float = 5.0,
        emit: bool = True,
    ) -> None:
        self._baseline: dict[str, float] = dict(baseline or {})
        self._threshold_pct = threshold_pct
        self._emit = emit

    def set_baseline(self, metric: str, value: float) -> None:
        """Update the baseline mean for *metric*."""
        self._baseline[metric] = value

    def check(self, report: EvalReport) -> list[dict[str, Any]]:
        """Compare *report* summary against the baseline.

        Returns a list of regression dicts (may be empty).  Each dict has
        keys ``metric``, ``baseline``, ``current``, and ``drop_pct``.
        """
        regressions: list[dict[str, Any]] = []
        summary = report.summary()
        for metric, current in summary.items():
            baseline = self._baseline.get(metric)
            if baseline is None or baseline <= 0:
                continue
            drop_pct = (baseline - current) / baseline * 100
            if drop_pct >= self._threshold_pct:
                reg = {
                    "metric": metric,
                    "baseline": baseline,
                    "current": current,
                    "drop_pct": round(drop_pct, 4),
                }
                regressions.append(reg)
                _log.warning(
                    "spanforge.eval: regression detected for metric=%r "
                    "(baseline=%.4f current=%.4f drop=%.2f%%)",
                    metric,
                    baseline,
                    current,
                    drop_pct,
                )
                if self._emit:
                    try:
                        from spanforge._stream import emit_rfc_event  # noqa: PLC0415
                        from spanforge.types import EventType  # noqa: PLC0415
                        emit_rfc_event(
                            EventType.EVAL_REGRESSION_DETECTED,
                            payload=reg,
                        )
                    except Exception as exc:  # NOSONAR
                        _log.warning(
                            "spanforge.eval: failed to emit regression event: %s", exc
                        )
        return regressions
