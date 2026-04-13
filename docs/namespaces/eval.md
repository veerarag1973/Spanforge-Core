# llm.eval — Scoring & Evaluation

> **Auto-documented module:** `spanforge.namespaces.eval_`

The `llm.eval.*` namespace records evaluation scores, regression detections,
and evaluation scenario lifecycle events (RFC-0001 §5).

## Payload classes

| Class | Event type | Description |
|-------|-----------|-------------|
| `EvalScoreRecordedPayload` | `llm.eval.score.recorded` | A numeric score was recorded for a metric |
| `EvalRegressionDetectedPayload` | `llm.eval.regression.detected` | A metric score crossed a regression threshold |
| `EvalScenarioStartedPayload` | `llm.eval.scenario.started` | An evaluation scenario started |
| `EvalScenarioCompletedPayload` | `llm.eval.scenario.completed` | An evaluation scenario completed |

---

## `EvalScoreRecordedPayload` — key fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `evaluator` | `str` | ✓ | Evaluator identifier (e.g. `"human"`, `"gpt-4o"`, `"rubric-v2"`) |
| `metric_name` | `str` | ✓ | Name of the metric being scored (e.g. `"faithfulness"`) |
| `score` | `float` | ✓ | Numeric score value |
| `score_min` | `float \| None` | — | Minimum of the scoring scale |
| `score_max` | `float \| None` | — | Maximum of the scoring scale |
| `threshold` | `float \| None` | — | Pass/fail threshold |
| `passed` | `bool \| None` | — | Whether the score met the threshold |
| `subject_event_id` | `str \| None` | — | ULID of the event being evaluated |
| `subject_type` | `str \| None` | — | Type of the evaluated subject (e.g. `"span"`, `"agent_run"`) |
| `eval_run_id` | `str \| None` | — | Evaluation run identifier |

---

## Example

```python
from spanforge import Event, EventType
from spanforge.namespaces.eval_ import EvalScoreRecordedPayload

payload = EvalScoreRecordedPayload(
    evaluator="gpt-4o",
    metric_name="faithfulness",
    score=0.85,
    score_min=0.0,
    score_max=1.0,
    threshold=0.7,
    passed=True,
)

event = Event(
    event_type=EventType.EVAL_SCORE_RECORDED,
    source="eval-worker@1.0.0",
    org_id="org_01HX",
    payload=payload.to_dict(),
)
```
