# spanforge.regression — Pass/fail regression detection

> **Module:** `spanforge.regression`  
> **Added in:** 2.0.3

`spanforge.regression` provides generic, pass/fail–based regression
detection over evaluation runs.  It is **distinct** from the mean-based
`spanforge.eval.RegressionDetector` — this module focuses on two concrete
failure signals:

1. **New failures** — test cases that passed in the baseline but fail now.
2. **Score drops** — test cases whose numeric score fell by more than a
   configurable threshold.

---

## Quick example

```python
from spanforge.regression import RegressionDetector, compare

baseline = [
    {"id": "tc-001", "passed": True,  "score": 0.95},
    {"id": "tc-002", "passed": True,  "score": 0.88},
]
current = [
    {"id": "tc-001", "passed": True,  "score": 0.93},  # small drop — OK
    {"id": "tc-002", "passed": False, "score": 0.45},  # NEW FAILURE
]

report = compare(
    baseline, current,
    key_fn=lambda x: x["id"],
    passed_fn=lambda x: x["passed"],
    score_fn=lambda x: x["score"],
    score_drop_threshold=0.10,
)

if report.has_regression:
    print(report.summary())
    # "1 new failure(s), 0 score drop(s)"
```

---

## API

### `compare()` — convenience function

```python
def compare(
    baseline: list[T],
    current: list[T],
    *,
    key_fn: Callable[[T], Any],
    passed_fn: Callable[[T], bool],
    score_fn: Callable[[T], float],
    score_drop_threshold: float = 0.10,
) -> RegressionReport[T]: ...
```

One-shot helper equivalent to
`RegressionDetector(score_drop_threshold).compare(...)`.

---

### `RegressionDetector`

```python
class RegressionDetector(Generic[T]):
    def __init__(self, score_drop_threshold: float = 0.10) -> None: ...

    def compare(
        self,
        baseline: list[T],
        current: list[T],
        *,
        key_fn: Callable[[T], Any],
        passed_fn: Callable[[T], bool],
        score_fn: Callable[[T], float],
    ) -> RegressionReport[T]: ...
```

| Parameter | Description |
|-----------|-------------|
| `score_drop_threshold` | Minimum score decrease (0–1) to count as a regression. Default `0.10`. |
| `key_fn` | Function that extracts a unique key from each result item. |
| `passed_fn` | Function that returns `True` if the item passed. |
| `score_fn` | Function that returns the numeric score for the item. |

Only items present in **both** baseline and current are compared; items
added to current or removed from baseline are ignored.

---

### `RegressionReport`

```python
@dataclass
class RegressionReport(Generic[T]):
    new_failures:  list[T]
    score_drops:   list[tuple[T, T]]   # (baseline_item, current_item)

    @property
    def has_regression(self) -> bool: ...

    def summary(self) -> str: ...
```

| Attribute / method | Description |
|--------------------|-------------|
| `new_failures` | Items that were passing in baseline but failing now. |
| `score_drops` | Pairs `(baseline, current)` where the score drop exceeded the threshold. |
| `has_regression` | `True` when either list is non-empty. |
| `summary()` | Short human-readable string, e.g. `"1 new failure(s), 1 score drop(s)"` or `"no regression detected"`. |

---

## Difference from `spanforge.eval.RegressionDetector`

| | `spanforge.eval.RegressionDetector` | `spanforge.regression.RegressionDetector` |
|--|--------------------------------------|-------------------------------------------|
| Signal | Mean score across *all* metrics | Per-case pass/fail and score delta |
| Input | `EvalReport` objects | Any list of generic items |
| Use case | Overall eval pipeline health | CI gating, per-case diff |
