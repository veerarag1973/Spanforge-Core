"""spanforge.baseline — Behavioural baseline construction for drift detection.

:class:`BehaviouralBaseline` captures the statistical summary of an agent's
typical behaviour over an initial traffic window (default: up to 1 000 events
or 24 hours).  The baseline is serialisable to JSON so it can be persisted and
reloaded across restarts.

Usage::

    from spanforge.baseline import BehaviouralBaseline
    from spanforge.stream import iter_file

    events = list(iter_file("events.jsonl"))
    baseline = BehaviouralBaseline.from_events(events)
    baseline.save("baseline.json")

    # — on restart —
    baseline = BehaviouralBaseline.load("baseline.json")
"""

from __future__ import annotations

import datetime
import json
import pathlib
import statistics
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

    from spanforge.event import Event

__all__ = ["BehaviouralBaseline", "DistributionStats"]


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------


def _percentile(sorted_data: list[float], pct: float) -> float:
    """Return the *pct*-th percentile of an already-sorted list."""
    if not sorted_data:
        return 0.0
    if len(sorted_data) == 1:
        return float(sorted_data[0])
    idx = (pct / 100.0) * (len(sorted_data) - 1)
    lo = int(idx)
    hi = lo + 1
    if hi >= len(sorted_data):
        return float(sorted_data[-1])
    frac = idx - lo
    return sorted_data[lo] * (1.0 - frac) + sorted_data[hi] * frac


def _event_type_str(event: Event) -> str:
    et = event.event_type
    return et.value if hasattr(et, "value") else str(et)


# ---------------------------------------------------------------------------
# Value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DistributionStats:
    """Mean, standard deviation, and percentiles for a numeric metric.

    Attributes:
        mean:         Arithmetic mean of the sample population.
        stddev:       Sample standard deviation (0.0 when fewer than 2 samples).
        p50:          50th percentile (median).
        p95:          95th percentile.
        p99:          99th percentile.
        sample_count: Number of observations used to compute the statistics.
    """

    mean: float
    stddev: float
    p50: float
    p95: float
    p99: float
    sample_count: int

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_samples(cls, samples: list[float]) -> DistributionStats:
        """Build a :class:`DistributionStats` from a list of observations."""
        if not samples:
            return cls(mean=0.0, stddev=0.0, p50=0.0, p95=0.0, p99=0.0, sample_count=0)
        s = sorted(samples)
        mean = statistics.mean(s)
        stddev = statistics.stdev(s) if len(s) >= 2 else 0.0
        return cls(
            mean=mean,
            stddev=stddev,
            p50=_percentile(s, 50),
            p95=_percentile(s, 95),
            p99=_percentile(s, 99),
            sample_count=len(s),
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "mean": self.mean,
            "stddev": self.stddev,
            "p50": self.p50,
            "p95": self.p95,
            "p99": self.p99,
            "sample_count": self.sample_count,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> DistributionStats:
        """Deserialise from a plain dict."""
        return cls(
            mean=float(d["mean"]),
            stddev=float(d["stddev"]),
            p50=float(d["p50"]),
            p95=float(d["p95"]),
            p99=float(d["p99"]),
            sample_count=int(d["sample_count"]),
        )


# ---------------------------------------------------------------------------
# Baseline
# ---------------------------------------------------------------------------


@dataclass
class BehaviouralBaseline:
    """Statistical summary of an agent's typical behaviour.

    Built from an initial traffic window and used by :class:`~spanforge.drift.DriftDetector`
    to detect statistically significant deviations at runtime.

    Attributes:
        tokens:                  Token count distribution across all LLM spans.
        confidence_by_type:      Per-decision-type confidence score distributions.
        latency_by_operation:    Per-operation latency distributions (milliseconds).
        tool_rate_per_hour:      Observed tool invocation rate per tool name (calls/h).
        decision_rate_per_hour:  Observed decision rate per decision type (decisions/h).
        event_count:             Number of events consumed to build this baseline.
        window_seconds:          Duration of the baseline traffic window in seconds.
        recorded_at:             ISO 8601 UTC timestamp when the baseline was created.
    """

    tokens: DistributionStats
    confidence_by_type: dict[str, DistributionStats] = field(default_factory=dict)
    latency_by_operation: dict[str, DistributionStats] = field(default_factory=dict)
    tool_rate_per_hour: dict[str, float] = field(default_factory=dict)
    decision_rate_per_hour: dict[str, float] = field(default_factory=dict)
    event_count: int = 0
    window_seconds: float = 86400.0
    recorded_at: str = ""

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_events(
        cls,
        events: Iterable[Event],
        max_events: int = 1000,
        window_seconds: float = 86400.0,
    ) -> BehaviouralBaseline:
        """Build a baseline from a stream of events.

        Consumes at most *max_events* events from *events* (or the whole
        iterable, whichever comes first) and computes statistical distributions
        for the following metric groups:

        - **Tokens** — total token count from ``llm.trace.span.completed``
          payloads that contain a ``token_usage`` dict.
        - **Confidence** — per-decision-type score from ``confidence.sample``
          events.
        - **Latency** — per-operation latency from ``llm.trace.span.completed``,
          ``tool_call.*``, and ``latency.sample`` events.
        - **Tool invocation rates** — calls per hour from ``tool_call.*`` events.
        - **Decision rates** — decisions per hour from ``decision.made`` events.

        Args:
            events:         Source iterable of :class:`~spanforge.event.Event`.
            max_events:     Upper bound on events consumed (default 1 000).
            window_seconds: Denominator for rate calculations (default 86 400 s = 24 h).

        Returns:
            A fully-populated :class:`BehaviouralBaseline`.
        """
        token_samples: list[float] = []
        confidence_samples: dict[str, list[float]] = {}
        latency_samples: dict[str, list[float]] = {}
        tool_counts: dict[str, int] = {}
        decision_counts: dict[str, int] = {}

        count = 0
        for event in events:
            if count >= max_events:
                break
            count += 1
            etype = _event_type_str(event)
            payload = event.payload

            # LLM span events — tokens + latency
            if etype in ("llm.trace.span.completed", "llm.trace.span.failed"):
                tu = payload.get("token_usage")
                if tu:
                    total = int(tu.get("total_tokens", 0) or 0)
                    if total > 0:
                        token_samples.append(float(total))
                dur = payload.get("duration_ms")
                if dur is not None:
                    op = str(payload.get("operation", "unknown"))
                    latency_samples.setdefault(op, []).append(float(dur))
                    if op == "tool_call":
                        tool_counts[op] = tool_counts.get(op, 0) + 1

            # Confidence namespace events
            elif etype == "confidence.sample":
                dtype = str(payload.get("decision_type", "unknown"))
                score = payload.get("score")
                if score is not None:
                    confidence_samples.setdefault(dtype, []).append(float(score))

            # Decision namespace events
            elif etype == "decision.made":
                dtype = str(payload.get("decision_type", "unknown"))
                decision_counts[dtype] = decision_counts.get(dtype, 0) + 1

            # Tool call namespace events
            elif etype.startswith("tool_call."):
                tool_name = str(payload.get("tool_name", "unknown"))
                tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1
                lat = payload.get("latency_ms")
                if lat is not None:
                    latency_samples.setdefault(tool_name, []).append(float(lat))

            # Latency namespace events
            elif etype == "latency.sample":
                op = str(payload.get("operation", "unknown"))
                lat = payload.get("latency_ms")
                if lat is not None:
                    latency_samples.setdefault(op, []).append(float(lat))

        hours = (window_seconds / 3600.0) if window_seconds > 0 else 1.0

        return cls(
            tokens=DistributionStats.from_samples(token_samples),
            confidence_by_type={
                dt: DistributionStats.from_samples(samples)
                for dt, samples in confidence_samples.items()
            },
            latency_by_operation={
                op: DistributionStats.from_samples(samples)
                for op, samples in latency_samples.items()
            },
            tool_rate_per_hour={op: cnt / hours for op, cnt in tool_counts.items()},
            decision_rate_per_hour={dt: cnt / hours for dt, cnt in decision_counts.items()},
            event_count=count,
            window_seconds=window_seconds,
            recorded_at=datetime.datetime.now(datetime.timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%S.%f"
            )
            + "Z",
        )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict."""
        return {
            "tokens": self.tokens.to_dict(),
            "confidence_by_type": {k: v.to_dict() for k, v in self.confidence_by_type.items()},
            "latency_by_operation": {k: v.to_dict() for k, v in self.latency_by_operation.items()},
            "tool_rate_per_hour": dict(self.tool_rate_per_hour),
            "decision_rate_per_hour": dict(self.decision_rate_per_hour),
            "event_count": self.event_count,
            "window_seconds": self.window_seconds,
            "recorded_at": self.recorded_at,
        }

    def to_json(self) -> str:
        """Serialise to a compact JSON string (keys sorted)."""
        return json.dumps(self.to_dict(), sort_keys=True, indent=2)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> BehaviouralBaseline:
        """Deserialise from a plain dict."""
        return cls(
            tokens=DistributionStats.from_dict(d["tokens"]),
            confidence_by_type={
                k: DistributionStats.from_dict(v)
                for k, v in d.get("confidence_by_type", {}).items()
            },
            latency_by_operation={
                k: DistributionStats.from_dict(v)
                for k, v in d.get("latency_by_operation", {}).items()
            },
            tool_rate_per_hour={k: float(v) for k, v in d.get("tool_rate_per_hour", {}).items()},
            decision_rate_per_hour={
                k: float(v) for k, v in d.get("decision_rate_per_hour", {}).items()
            },
            event_count=int(d.get("event_count", 0)),
            window_seconds=float(d.get("window_seconds", 86400.0)),
            recorded_at=str(d.get("recorded_at", "")),
        )

    @classmethod
    def from_json(cls, s: str) -> BehaviouralBaseline:
        """Deserialise from a JSON string produced by :meth:`to_json`."""
        return cls.from_dict(json.loads(s))

    def save(self, path: str | pathlib.Path) -> None:
        """Write the baseline to *path* as UTF-8 JSON."""
        pathlib.Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: str | pathlib.Path) -> BehaviouralBaseline:
        """Load a baseline previously saved with :meth:`save`."""
        return cls.from_json(pathlib.Path(path).read_text(encoding="utf-8"))
