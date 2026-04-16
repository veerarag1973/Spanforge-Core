# spanforge.stats — Latency statistics

> **Module:** `spanforge.stats`  
> **Added in:** 2.0.3

`spanforge.stats` provides latency percentile helpers for LLM call
instrumentation.  All functions are pure Python with no external
dependencies.

---

## Quick example

```python
from spanforge.stats import latency_summary, percentile

latencies = [120.5, 134.2, 98.7, 210.0, 155.3, 143.8, 189.4]

print(percentile(latencies, 95))    # 204.06 ms
print(latency_summary(latencies))
# {
#   "count": 7,
#   "mean":  150.271,
#   "min":   98.7,
#   "max":   210.0,
#   "p50":   143.8,
#   "p95":   204.06,
#   "p99":   208.812,
# }
```

---

## API

### `percentile()`

```python
def percentile(values: list[float], p: float) -> float: ...
```

Return the *p*-th percentile of *values* using linear interpolation.
Returns `0.0` for an empty list.

| Parameter | Description |
|-----------|-------------|
| `values` | List of numeric values (need not be sorted; the original list is not mutated). |
| `p` | Percentile in the range `[0, 100]`. |

**Raises:** `ValueError` if *p* is outside `[0, 100]`.

---

### `latency_summary()`

```python
def latency_summary(values_ms: list[float]) -> dict: ...
```

Compute a standard latency summary dict from a list of millisecond values.

**Returns:**

```python
{
    "count": int,
    "mean":  float,   # arithmetic mean
    "min":   float,
    "max":   float,
    "p50":   float,
    "p95":   float,
    "p99":   float,
}
```

All float values are rounded to 3 decimal places.  For an empty list every
value is `0.0` and `count` is `0`.
