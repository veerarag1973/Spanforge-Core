"""spanforge.drift — Behavioural drift detection engine (Phase 3).

:class:`DriftDetector` maintains a sliding window of observed metric values
and compares them against a :class:`~spanforge.baseline.BehaviouralBaseline`
using Z-score and KL-divergence statistics.  When a threshold is breached it
returns :class:`~spanforge.namespaces.drift.DriftPayload` objects that can be
emitted as RFC-0001 SPANFORGE ``drift.*`` events via
:func:`~spanforge._stream.emit_rfc_event`.

Usage::

    from spanforge.baseline import BehaviouralBaseline
    from spanforge.drift import DriftDetector
    from spanforge._stream import emit_rfc_event
    from spanforge.types import EventType

    baseline = BehaviouralBaseline.load("baseline.json")
    detector = DriftDetector(baseline, agent_id="my-agent")

    for event in live_event_stream():
        results = detector.record(event)
        for payload in results:
            emit_rfc_event(
                EventType("drift." + payload.status.replace("_", "_")),
                payload.to_dict(),
            )
"""

from __future__ import annotations

import math
import statistics
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from spanforge.baseline import BehaviouralBaseline
from spanforge.namespaces.drift import DriftPayload

if TYPE_CHECKING:
    from spanforge.event import Event

__all__ = ["DriftDetector", "DriftResult"]

# Minimum observations required in the window before drift analysis is attempted.
_MIN_WINDOW_SAMPLES: int = 10


# ---------------------------------------------------------------------------
# Value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DriftResult:
    """Drift assessment for a single metric observation.

    Attributes:
        metric_name:      Dot-separated metric identifier (e.g. ``"tokens"``,
                          ``"confidence.classification"``, ``"latency.chat"``).
        current_value:    The raw observed value that triggered the assessment.
        window_mean:      Current window mean (rolling).
        window_stddev:    Current window standard deviation (rolling).
        baseline_mean:    Mean from the :class:`~spanforge.baseline.BehaviouralBaseline`.
        baseline_stddev:  Std-dev from the baseline.
        z_score:          ``(window_mean - baseline_mean) / baseline_stddev``.
        kl_divergence:    KL-divergence between window and baseline Gaussian
                          (``None`` if baseline stddev is zero or window has
                          fewer than 2 samples).
        threshold:        The configured Z-score threshold.
        status:           ``"ok"`` | ``"detected"`` | ``"threshold_breach"`` |
                          ``"resolved"``.
        payload:          Ready-to-emit :class:`~spanforge.namespaces.drift.DriftPayload`
                          (``None`` when status is ``"ok"``).
    """

    metric_name: str
    current_value: float
    window_mean: float
    window_stddev: float
    baseline_mean: float
    baseline_stddev: float
    z_score: float
    kl_divergence: float | None
    threshold: float
    status: str
    payload: DriftPayload | None


# ---------------------------------------------------------------------------
# KL-divergence (Gaussian approximation)
# ---------------------------------------------------------------------------


def _kl_divergence_gaussian(
    mu_p: float,
    sigma_p: float,
    mu_q: float,
    sigma_q: float,
) -> float | None:
    """KL-divergence KL(P || Q) between two univariate Gaussians.

    KL(N(μ_P, σ_P²) || N(μ_Q, σ_Q²)) =
        log(σ_Q / σ_P) + (σ_P² + (μ_P − μ_Q)²) / (2 σ_Q²) − 1/2

    Returns ``None`` when σ_P ≤ 0 or σ_Q ≤ 0 (degenerate distribution).
    """
    if sigma_p <= 0.0 or sigma_q <= 0.0:
        return None
    return (
        math.log(sigma_q / sigma_p)
        + (sigma_p ** 2 + (mu_p - mu_q) ** 2) / (2.0 * sigma_q ** 2)
        - 0.5
    )


# ---------------------------------------------------------------------------
# DriftDetector
# ---------------------------------------------------------------------------


class DriftDetector:
    """Sliding-window behavioural drift detector.

    Maintains per-metric rolling windows and reports
    :class:`DriftResult` / :class:`~spanforge.namespaces.drift.DriftPayload`
    objects whenever the current window deviates significantly from the
    recorded :class:`~spanforge.baseline.BehaviouralBaseline`.

    Args:
        baseline:        Deployment-time statistical baseline.
        agent_id:        Identifier for the monitored agent (embedded in every
                         emitted :class:`~spanforge.namespaces.drift.DriftPayload`).
        window_size:     Maximum number of observations per metric in the rolling
                         window (default 500).
        z_threshold:     Z-score that triggers a ``threshold_breach`` (default 3.0).
        kl_threshold:    KL-divergence that triggers a ``threshold_breach``
                         (default 0.5).
        window_seconds:  Nominal window duration embedded in emitted payloads
                         (default 3 600 s = 1 h).
        auto_emit:       When ``True`` (default), calls
                         :func:`~spanforge._stream.emit_rfc_event` for each
                         ``detected`` / ``threshold_breach`` / ``resolved`` result.
    """

    def __init__(
        self,
        baseline: BehaviouralBaseline,
        agent_id: str,
        window_size: int = 500,
        z_threshold: float = 3.0,
        kl_threshold: float = 0.5,
        window_seconds: int = 3600,
        auto_emit: bool = True,
        metric_ttl_seconds: int = 86400,
    ) -> None:
        if not agent_id:
            raise ValueError("DriftDetector: agent_id must be non-empty")
        if window_size < 1:
            raise ValueError("DriftDetector: window_size must be >= 1")
        if not math.isfinite(z_threshold) or z_threshold <= 0:
            raise ValueError("DriftDetector: z_threshold must be a finite positive number")
        if window_seconds <= 0:
            raise ValueError("DriftDetector: window_seconds must be > 0")
        if metric_ttl_seconds <= 0:
            raise ValueError("DriftDetector: metric_ttl_seconds must be > 0")

        self._baseline = baseline
        self._agent_id = agent_id
        self._window_size = window_size
        self._z_threshold = z_threshold
        self._kl_threshold = kl_threshold
        self._window_seconds = window_seconds
        self._auto_emit = auto_emit
        self._metric_ttl_seconds = metric_ttl_seconds

        self._lock = threading.Lock()
        # metric_name → rolling deque of float observations
        self._windows: dict[str, deque[float]] = {}
        # metric_name → current breach state
        self._in_breach: dict[str, bool] = {}
        # metric_name → last observation time (monotonic clock)
        self._last_seen: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def baseline(self) -> BehaviouralBaseline:
        """The baseline this detector is comparing against."""
        return self._baseline

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @property
    def window_size(self) -> int:
        return self._window_size

    def record(self, event: "Event") -> list[DriftResult]:
        """Ingest *event*, update rolling windows, and return drift results.

        Extracts metric observations from the event payload based on its
        event type and compares the updated window statistics against the
        baseline.

        Args:
            event: A :class:`~spanforge.event.Event` (any type; non-metric
                   events are silently ignored).

        Returns:
            A list of :class:`DriftResult` objects for every metric that had a
            state transition (``ok``, ``detected``, ``threshold_breach``,
            or ``resolved``).  Returns an empty list for most events.
        """
        observations = _extract_metric_observations(event)
        if not observations:
            return []

        results: list[DriftResult] = []
        with self._lock:
            for metric_name, value in observations:
                result = self._assess(metric_name, value)
                if result is not None:
                    results.append(result)

        if self._auto_emit:
            self._emit_results(results)

        return results

    def window_stats(self, metric_name: str) -> tuple[float, float, int] | None:
        """Return ``(mean, stddev, count)`` for *metric_name*'s current window.

        Returns ``None`` if no data has been recorded for the metric yet.
        """
        with self._lock:
            window = self._windows.get(metric_name)
            if not window:
                return None
            data = list(window)
        mean = statistics.mean(data)
        stddev = statistics.stdev(data) if len(data) >= 2 else 0.0
        return mean, stddev, len(data)

    def reset_window(self, metric_name: str | None = None) -> None:
        """Clear the rolling window(s).

        Args:
            metric_name: If given, clears only that metric's window and breach
                         state.  If ``None``, clears all metrics.
        """
        with self._lock:
            if metric_name is None:
                self._windows.clear()
                self._in_breach.clear()
            else:
                self._windows.pop(metric_name, None)
                self._in_breach.pop(metric_name, None)

    def in_breach(self, metric_name: str) -> bool:
        """Return ``True`` if *metric_name* is currently in threshold breach."""
        with self._lock:
            return self._in_breach.get(metric_name, False)

    # ------------------------------------------------------------------
    # Internal helpers (must be called with self._lock held)
    # ------------------------------------------------------------------

    def _get_baseline_stats(
        self, metric_name: str
    ) -> tuple[float, float] | None:
        """Return (baseline_mean, baseline_stddev) for *metric_name*, or None."""
        if metric_name == "tokens":
            return self._baseline.tokens.mean, self._baseline.tokens.stddev

        if metric_name.startswith("confidence."):
            dtype = metric_name[len("confidence."):]
            stats = self._baseline.confidence_by_type.get(dtype)
            if stats is not None:
                return stats.mean, stats.stddev

        if metric_name.startswith("latency."):
            op = metric_name[len("latency."):]
            stats = self._baseline.latency_by_operation.get(op)
            if stats is not None:
                return stats.mean, stats.stddev

        return None

    def _evict_stale(self) -> None:
        """Evict metrics that have not been observed within ``metric_ttl_seconds``.\n\n        Called with ``self._lock`` already held.  Prevents unbounded memory\n        growth when many short-lived agent instances write unique metric keys.\n        """
        now = time.monotonic()
        cutoff = now - self._metric_ttl_seconds
        stale = [k for k, ts in self._last_seen.items() if ts < cutoff]
        for k in stale:
            self._windows.pop(k, None)
            self._in_breach.pop(k, None)
            self._last_seen.pop(k, None)

    def _assess(self, metric_name: str, value: float) -> DriftResult | None:
        """Update the window for *metric_name* with *value* and return a result.

        Returns ``None`` when there is no baseline for the metric or the window
        has fewer than ``_MIN_WINDOW_SAMPLES`` observations.
        """
        # Update rolling window
        window = self._windows.setdefault(
            metric_name, deque(maxlen=self._window_size)
        )
        window.append(value)
        self._last_seen[metric_name] = time.monotonic()

        # Evict metrics that haven't been seen within the TTL.
        self._evict_stale()

        if len(window) < _MIN_WINDOW_SAMPLES:
            return None

        baseline_stats = self._get_baseline_stats(metric_name)
        if baseline_stats is None:
            return None

        baseline_mean, baseline_stddev = baseline_stats

        # Avoid division by zero for constant-baseline metrics
        effective_stddev = baseline_stddev if baseline_stddev > 0 else 1e-9

        data = list(window)
        win_mean = statistics.mean(data)
        win_stddev = statistics.stdev(data) if len(data) >= 2 else 0.0

        z_score = abs(win_mean - baseline_mean) / effective_stddev

        kl_div = _kl_divergence_gaussian(
            mu_p=win_mean,
            sigma_p=win_stddev,
            mu_q=baseline_mean,
            sigma_q=baseline_stddev,
        )

        # Determine status
        was_in_breach = self._in_breach.get(metric_name, False)

        if z_score >= self._z_threshold or (
            kl_div is not None and kl_div >= self._kl_threshold
        ):
            new_status = "threshold_breach"
            self._in_breach[metric_name] = True
        else:
            # No active breach — resolve or downgrade
            if was_in_breach:
                new_status = "resolved"
                self._in_breach[metric_name] = False
            elif z_score >= self._z_threshold * (2.0 / 3.0):
                # "detected" zone: Z is elevated but below the breach threshold
                new_status = "detected"
            else:
                new_status = "ok"

        if new_status == "ok":
            return None

        # Map to DriftPayload status literals
        payload_status: str
        if new_status == "threshold_breach":
            payload_status = "threshold_breach"
        elif new_status == "detected":
            payload_status = "detected"
        else:  # resolved
            payload_status = "resolved"

        drift_payload = DriftPayload(
            metric_name=metric_name,
            agent_id=self._agent_id,
            current_value=value,
            baseline_mean=baseline_mean,
            baseline_stddev=baseline_stddev,
            z_score=round(z_score, 6),
            kl_divergence=round(kl_div, 6) if kl_div is not None else None,
            threshold=self._z_threshold,
            window_seconds=self._window_seconds,
            status=payload_status,  # type: ignore[arg-type]
        )

        return DriftResult(
            metric_name=metric_name,
            current_value=value,
            window_mean=win_mean,
            window_stddev=win_stddev,
            baseline_mean=baseline_mean,
            baseline_stddev=baseline_stddev,
            z_score=z_score,
            kl_divergence=kl_div,
            threshold=self._z_threshold,
            status=new_status,
            payload=drift_payload,
        )

    # ------------------------------------------------------------------
    # Auto-emit
    # ------------------------------------------------------------------

    def _emit_results(self, results: list[DriftResult]) -> None:
        """Emit drift events for each non-ok result via emit_rfc_event."""
        if not results:
            return
        try:
            from spanforge._stream import emit_rfc_event  # noqa: PLC0415
            from spanforge.types import EventType  # noqa: PLC0415

            _status_to_event_type = {
                "detected": EventType.DRIFT_DETECTED,
                "threshold_breach": EventType.DRIFT_THRESHOLD_BREACH,
                "resolved": EventType.DRIFT_RESOLVED,
            }
            for result in results:
                if result.payload is None:
                    continue
                et = _status_to_event_type.get(result.status)
                if et is not None:
                    try:
                        emit_rfc_event(et, result.payload.to_dict())
                    except Exception:  # noqa: BLE001
                        pass  # never let auto-emit failures disrupt the caller
        except ImportError:
            pass


# ---------------------------------------------------------------------------
# Metric extraction helpers
# ---------------------------------------------------------------------------


def _event_type_str(event: "Event") -> str:
    et = event.event_type
    return et.value if hasattr(et, "value") else str(et)


def _extract_metric_observations(
    event: "Event",
) -> list[tuple[str, float]]:
    """Extract (metric_name, value) pairs from *event*.

    Returns an empty list for event types that carry no drift-relevant metrics.
    """
    etype = _event_type_str(event)
    payload = event.payload
    observations: list[tuple[str, float]] = []

    # LLM span events — token count + latency per operation
    if etype in ("llm.trace.span.completed", "llm.trace.span.failed"):
        tu = payload.get("token_usage")
        if tu:
            total = int(tu.get("total_tokens", 0) or 0)
            if total > 0:
                observations.append(("tokens", float(total)))
        dur = payload.get("duration_ms")
        if dur is not None:
            op = str(payload.get("operation", "unknown"))
            observations.append((f"latency.{op}", float(dur)))

    # Confidence namespace
    elif etype == "confidence.sample":
        dtype = str(payload.get("decision_type", "unknown"))
        score = payload.get("score")
        if score is not None:
            observations.append((f"confidence.{dtype}", float(score)))

    # Latency namespace
    elif etype == "latency.sample":
        op = str(payload.get("operation", "unknown"))
        lat = payload.get("latency_ms")
        if lat is not None:
            observations.append((f"latency.{op}", float(lat)))

    # Tool call namespace
    elif etype.startswith("tool_call."):
        lat = payload.get("latency_ms")
        tool_name = str(payload.get("tool_name", "unknown"))
        if lat is not None:
            observations.append((f"latency.{tool_name}", float(lat)))

    return observations
