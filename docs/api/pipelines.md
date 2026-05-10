# `spanforge.sdk.pipelines` — HallucCheck Pipeline Integrations

> **Module:** `spanforge.sdk.pipelines`  
> **Added in:** 2.0.9 (Phase 10 — T.R.U.S.T. Scorecard & HallucCheck Contract)  
> **Import:** `from spanforge.sdk.pipelines import score_pipeline, bias_pipeline, ...`

The pipelines module provides five HallucCheck ↔ SpanForge integration
touch-points. Each pipeline orchestrates calls across multiple SpanForge
services and returns a `PipelineResult` with an audit trail.

---

## Quick example

```python
from spanforge.sdk.pipelines import score_pipeline

result = score_pipeline("The model output to check", model="gpt-4o")
print(result.success)    # True
print(result.audit_id)   # "rec_..."
print(result.details)    # {"pii_clean": True, "secrets_clean": True, ...}
```

---

## Pipelines

### `score_pipeline(text, *, model="", project_id="", pii_action="redact")`

**TRS-010** — Score pipeline: PII scan → secrets scan → observe span → audit append.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `text` | `str` | — | Input text to score |
| `model` | `str` | `""` | Model identifier for the audit record |
| `project_id` | `str` | `""` | Project scope |
| `pii_action` | `str` | `"redact"` | `"redact"`, `"block"`, or `"log"` |

**Returns:** `PipelineResult`

**Steps:**
1. `sf_pii.scan_text()` — apply PII action
2. `sf_secrets.scan()` — auto-block if hit
3. `sf_observe.emit_span("hc.score.completed", ...)`
4. `sf_audit.append(score_record, "halluccheck.score.v1")`

---

### `bias_pipeline(bias_report, *, project_id="", disparity_threshold=0.1)`

**TRS-011** — Bias pipeline: PII scan → audit → alert (if disparity exceeds threshold) → anonymise.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `bias_report` | `dict` | — | Bias analysis report |
| `project_id` | `str` | `""` | Project scope |
| `disparity_threshold` | `float` | `0.1` | Alert threshold for disparity |

**Returns:** `PipelineResult`

**Steps:**
1. `sf_pii.scan_text()` on segment labels
2. `sf_audit.append(bias_report, "halluccheck.bias.v1")`
3. If disparity > threshold → `sf_alert.publish("halluccheck.bias.critical", ...)`
4. `sf_pii.anonymise()` before export

---

### `monitor_pipeline(event, *, project_id="")`

**TRS-012** — Monitor pipeline: annotate drift event → alert on AMBER/RED → OTel export.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `event` | `dict` | — | Drift/provider event dict (use `"drift_level"` key: `"AMBER"` or `"RED"`) |
| `project_id` | `str` | `""` | Project scope |

**Returns:** `PipelineResult`

**Steps:**
1. `sf_observe.add_annotation(span_id=..., key="drift_event", ...)` — tag the span
2. If `event["drift_level"]` is `"AMBER"` or `"RED"` → `sf_alert.publish("halluccheck.drift.amber"` / `"halluccheck.drift.red", ...)`
3. `sf_observe.export_spans()` — flush to configured receiver

---

### `risk_pipeline(prri_record, *, project_id="", run_gate=False, build_cec=False)`

**TRS-013** — Risk pipeline: audit append → alert on RED verdict → optional gate → optional CEC bundle.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `prri_record` | `dict` | — | PRRI risk assessment dict (must include `"verdict"` key: `"GREEN"`, `"AMBER"`, or `"RED"`) |
| `project_id` | `str` | `""` | Project scope |
| `run_gate` | `bool` | `False` | Whether to trigger `gate5_governance` gate evaluation |
| `build_cec` | `bool` | `False` | Whether to build a CEC evidence bundle |

**Returns:** `PipelineResult`

**Steps:**
1. `sf_audit.append(prri_record, "halluccheck.prri.v1")` — audit record
2. If `prri_record["verdict"] == "RED"` → `sf_alert.publish("halluccheck.prri.red", ...)`
3. If `run_gate` → `sf_gate.evaluate("gate5_governance", metrics=prri_record, ...)`
4. If `build_cec` → `sf_cec.build_bundle(evidence_type="prri_assessment", ...)`

---

### `benchmark_pipeline(run_result, *, project_id="", f1_regression_threshold=0.05)`

**TRS-014** — Benchmark pipeline: audit → F1 regression alert → anonymise export payload.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `run_result` | `dict` | — | Benchmark run result dict (use `"f1_delta"` key for regression check, `"summary"` for anonymisation) |
| `project_id` | `str` | `""` | Project scope |
| `f1_regression_threshold` | `float` | `0.05` | F1 delta threshold below which a regression alert fires |

**Returns:** `PipelineResult`

**Steps:**
1. `sf_audit.append(run_result, "halluccheck.benchmark_run.v1")`
2. If `run_result["f1_delta"] < -f1_regression_threshold` → `sf_alert.publish("halluccheck.benchmark.regression", ...)`
3. `sf_pii.anonymise()` on `run_result["summary"]` before export

---

## Return type

### `PipelineResult`

| Field | Type | Description |
|-------|------|-------------|
| `pipeline` | `str` | Pipeline name (`"score"`, `"bias"`, `"monitor"`, `"risk"`, `"benchmark"`) |
| `success` | `bool` | Whether the pipeline completed without errors |
| `audit_id` | `str` | Audit record ID from the pipeline's audit step |
| `alerts_sent` | `int` | Number of alerts published by this pipeline run |
| `span_id` | `str` | Span ID from the observe step (if applicable) |
| `details` | `dict` | Pipeline-specific details and metrics |

---

## Exceptions

| Exception | Raised when |
|-----------|-------------|
| `SFPipelineError` | A critical step within a pipeline fails |
