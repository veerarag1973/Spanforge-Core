# spanforge.eval — Evaluation framework

> **Module:** `spanforge.eval`

`spanforge.eval` provides lightweight instrumentation for attaching quality
scores to active spans and emitting them as RFC-0001 `llm.eval.*` events.
It ships built-in scorers, a batch runner, a mean-based regression detector,
and a plug-in scorer ABC for the entry-point ecosystem.

---

## Quick example

```python
from spanforge.eval import record_eval_score, EvalScore

score = record_eval_score(
    metric="faithfulness",
    value=0.87,
    span_id="abcdef0123456789",
    trace_id="abcdef0123456789abcdef0123456789",
    label="pass",
    metadata={"evaluator": "ragas"},
)
```

---

## API

### `record_eval_score()`

```python
def record_eval_score(
    metric: str,
    value: float,
    *,
    span_id: str | None = None,
    trace_id: str | None = None,
    label: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> EvalScore: ...
```

Record a score and emit it as an `llm.eval.score.recorded` event via the
configured SpanForge exporter.

| Parameter | Description |
|-----------|-------------|
| `metric` | Name of the quality metric (e.g. `"faithfulness"`). |
| `value` | Numeric score value (any float). |
| `span_id` | Optional parent span ID (16 lowercase hex chars). |
| `trace_id` | Optional trace ID (32 lowercase hex chars). |
| `label` | Optional human-readable label (`"pass"` / `"fail"` / etc.). |
| `metadata` | Optional free-form dict with evaluator details. |

---

### `EvalScore`

```python
@dataclass
class EvalScore:
    metric: str
    value: float
    span_id: str | None = None
    trace_id: str | None = None
    label: str | None = None
    metadata: dict[str, Any] | None = None
    timestamp: float = ...  # auto-set
```

A single quality measurement attached to a span or agent run.

| Method | Description |
|--------|-------------|
| `to_dict()` | Serialise to a plain dict. |
| `from_dict(data)` | Class method — deserialise from a dict. |

---

### `EvalScorer` (Protocol)

```python
@runtime_checkable
class EvalScorer(Protocol):
    @property
    def metric_name(self) -> str: ...
    def score(self, example: dict[str, Any]) -> EvalScore: ...
```

Protocol for scorers compatible with `EvalRunner`.  Each scorer receives a
single example dict (with at least an `"output"` key) and returns an
`EvalScore`.

---

### `EvalRunner`

```python
class EvalRunner:
    def __init__(
        self,
        scorers: list[EvalScorer] | None = None,
        *,
        emit: bool = True,
    ) -> None: ...

    def add_scorer(self, scorer: EvalScorer) -> None: ...
    def run(self, dataset: list[dict[str, Any]]) -> EvalReport: ...
```

Run one or more scorers over a dataset.  When `emit=True` (default) each
score is also emitted via `record_eval_score()`.

---

### `EvalReport`

```python
@dataclass
class EvalReport:
    scores: list[EvalScore]
    dataset: list[dict[str, Any]]
```

| Method | Description |
|--------|-------------|
| `summary()` | Return `{metric: mean_value}` dict. |
| `print_summary()` | Print a human-readable table to stdout. |

---

### `RegressionDetector`

```python
class RegressionDetector:
    def __init__(
        self,
        baseline: dict[str, float] | None = None,
        *,
        threshold_pct: float = 5.0,
        emit: bool = True,
    ) -> None: ...

    def set_baseline(self, metric: str, value: float) -> None: ...
    def check(self, report: EvalReport) -> list[dict[str, Any]]: ...
```

Mean-based regression detection.  When the mean score for a metric drops
below `baseline_mean * (1 - threshold_pct / 100)`, an
`llm.eval.regression.detected` event is emitted.

> **Note:** For per-case pass/fail regression detection, see
> [`spanforge.regression`](regression.md).

---

## Built-in scorers

| Scorer | `metric_name` | Description |
|--------|---------------|-------------|
| `FaithfulnessScorer` | `faithfulness` | Token-overlap proxy between `output` and `context`. |
| `RefusalDetectionScorer` | `refusal_detection` | Matches common refusal phrases (returns 1.0 on refusal). |
| `PIILeakageScorer` | `pii_leakage` | Delegates to `spanforge.redact.scan_payload()`; returns 1.0 on PII detection. |

---

### `BehaviourScorer` (ABC)

> **Added in:** 2.0.3

```python
class BehaviourScorer(ABC):
    name: str = "base"

    @abstractmethod
    def score(self, case: Any, response: str) -> tuple[float, str]: ...
```

Abstract base class for plug-in behaviour scorers registered via the
`spanforge.scorers` entry-point group.  Unlike `EvalScorer` (which scores
full `dict` examples), `BehaviourScorer` targets named test-case workflows
where the scorer receives a structured test case object and the raw model
response.

| Attribute / Method | Description |
|--------------------|-------------|
| `name` | Unique identifier for the scorer (override in subclasses). |
| `score(case, response)` | Return `(score, reason)` where score ∈ [0.0, 1.0]. |

**Registration:**

```toml
[project.entry-points."spanforge.scorers"]
toxicity = "my_package.scorers:ToxicityScorer"
```

**Example:**

```python
from spanforge.eval import BehaviourScorer

class ToxicityScorer(BehaviourScorer):
    name = "toxicity"

    def score(self, case, response: str) -> tuple[float, str]:
        if any(w in response.lower() for w in ("hate", "kill")):
            return 0.0, "toxic content detected"
        return 1.0, "no toxicity detected"
```
