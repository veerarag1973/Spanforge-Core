# spanforge.baseline & spanforge.drift

## Overview

`spanforge.baseline` builds a statistical summary of an agent's historical behaviour.
`spanforge.drift` uses that summary at runtime to detect statistically significant
deviations and emit `drift.*` events.

---

## DistributionStats

```python
from spanforge.baseline import DistributionStats
```

Frozen dataclass that holds a numeric distribution snapshot.

| Attribute | Type | Description |
|---|---|---|
| `mean` | `float` | Arithmetic mean |
| `stddev` | `float` | Sample standard deviation (0.0 when `sample_count < 2`) |
| `p50` | `float` | 50th percentile (median) |
| `p95` | `float` | 95th percentile |
| `p99` | `float` | 99th percentile |
| `sample_count` | `int` | Number of observations |

### Factory

```python
stats = DistributionStats.from_samples([10.2, 15.3, 11.8, ...])
```

### Serialisation

```python
d = stats.to_dict()          # → dict
stats2 = DistributionStats.from_dict(d)
```

---

## BehaviouralBaseline

```python
from spanforge.baseline import BehaviouralBaseline
```

Dataclass that captures the typical behaviour of a *single* agent across a
traffic window.

> **Note — LLM spans only**
> `BehaviouralBaseline` tracks `tokens` and `confidence_by_type` **only for LLM spans**
> (event types matching `llm.trace.*`).  Tool-call and decision spans contribute to
> `latency_by_operation` and `tool_rate_per_hour` but will never populate the `tokens`
> distribution.  Passing non-LLM spans to `from_events()` is intentional and safe — the
> baseline simply accumulates the metrics each span type supports.

| Attribute | Type | Description |
|---|---|---|
| `tokens` | `DistributionStats` | Token count distribution across all LLM spans |
| `confidence_by_type` | `dict[str, DistributionStats]` | Per-decision-type confidence score distributions |
| `latency_by_operation` | `dict[str, DistributionStats]` | Per-operation latency (ms) distributions |
| `tool_rate_per_hour` | `dict[str, float]` | Observed tool invocation rate per tool name (calls/h) |
| `decision_rate_per_hour` | `dict[str, float]` | Observed decision rate per decision type (decisions/h) |
| `event_count` | `int` | Number of events consumed to build this baseline |
| `window_seconds` | `float` | Duration of the baseline traffic window (seconds) |
| `recorded_at` | `str` | ISO 8601 UTC timestamp when the baseline was created |

### Building from events

```python
from spanforge.baseline import BehaviouralBaseline

baseline = BehaviouralBaseline.from_events(
    events,               # Iterable[Event]
    max_events=1000,      # optional upper bound on events consumed
    window_seconds=86400.0,  # 24 h — denominator for rate calculations
)
```

### Persistence

```python
baseline.save("baseline.json")
baseline2 = BehaviouralBaseline.load("baseline.json")

# JSON round-trip
json_str = baseline.to_json()
baseline3 = BehaviouralBaseline.from_json(json_str)
```

---

## DriftDetector

```python
from spanforge.drift import DriftDetector
```

Maintains a sliding window of recent metric observations and compares them
against a `BehaviouralBaseline` using Z-score and KL-divergence statistics.

### Constructor

```python
detector = DriftDetector(
    baseline,                        # BehaviouralBaseline
    agent_id="my-agent",
    window_size=500,                 # observations in the sliding window (default 500)
    z_threshold=3.0,                 # σ deviation before alert
    kl_threshold=0.5,                # KL-divergence threshold
    window_seconds=3600,             # rate-calculation window in seconds
    auto_emit=True,                  # emit drift.* events automatically
    metric_ttl_seconds=86400,        # seconds before an idle metric window expires
)
```

**Constructor parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `baseline` | `BehaviouralBaseline` | *(required)* | Baseline to compare observations against. |
| `agent_id` | `str` | *(required)* | Non-empty string identifying the agent being monitored. |
| `window_size` | `int` | `500` | Maximum number of observations kept in the rolling window. |
| `z_threshold` | `float` | `3.0` | Z-score above which a metric is considered drifted. Must be finite and positive. |
| `kl_threshold` | `float` | `0.5` | KL-divergence above which a distribution shift is flagged. |
| `window_seconds` | `int` | `3600` | Time window (seconds) used for rate calculations. Must be > 0. |
| `auto_emit` | `bool` | `True` | When `True`, `DriftDetector` automatically emits `drift.*` events on breach. |
| `metric_ttl_seconds` | `int` | `86400` | Seconds of inactivity before an idle metric window is evicted. |

### Recording events

```python
results: list[DriftResult] = detector.record(event)
```

Returns zero or more `DriftResult` objects — one per metric that breached a
threshold in this observation.

### DriftResult

| Attribute | Type | Description |
|---|---|---|
| `metric_name` | `str` | Metric that drifted |
| `status` | `str` | `"alert"` or `"warn"` |
| `observed_value` | `float` | The triggering observation |
| `baseline_mean` | `float` | Baseline `DistributionStats.mean` for this metric |
| `baseline_stddev` | `float` | Baseline `DistributionStats.stddev` |
| `zscore` | `float \| None` | Z-score of the observation |
| `kl_divergence` | `float \| None` | KL divergence of window vs. baseline |
| `window_size` | `int` | Current window size at detection time |
| `event_id` | `str` | ID of the triggering event |
| `agent_id` | `str` | Agent the detector is tracking |

### Inspection helpers

```python
# Returns (mean, stddev, n) for the current window
stats = detector.window_stats("latency_ms")

# True if the given metric is currently in breach
if detector.in_breach("latency_ms"):
    ...

# Reset one or all windows
detector.reset_window("latency_ms")
detector.reset_window()          # reset all metrics
```

---

## Emitting drift events

```python
from spanforge._stream import emit_rfc_event
from spanforge.types import EventType

for result in detector.record(event):
    emit_rfc_event(
        EventType("drift." + result.status),
        result.__dict__,
    )
```

When `emit_events=True` (the default), `DriftDetector` does this automatically.
