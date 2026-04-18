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

### `monitor_pipeline(drift_event, *, project_id="", alert_on_drift=True)`

**TRS-012** — Monitor pipeline: observe → alert → OTel export.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `drift_event` | `dict` | — | Drift detection event |
| `project_id` | `str` | `""` | Project scope |
| `alert_on_drift` | `bool` | `True` | Whether to alert on drift detection |

**Returns:** `PipelineResult`

**Steps:**
1. `sf_observe.emit_span("hc.monitor.drift", ...)`
2. If drift detected and `alert_on_drift` → `sf_alert.publish("halluccheck.drift.detected", ...)`
3. `sf_observe.export_spans(...)` to configured receiver

---

### `risk_pipeline(prri_score, *, project_id="", framework="", policy_file="")`

**TRS-013** — Risk pipeline: PRRI evaluation → alert → gate → CEC bundle.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `prri_score` | `float` | — | Pre-Release Readiness Index score |
| `project_id` | `str` | `""` | Project scope |
| `framework` | `str` | `""` | Regulatory framework |
| `policy_file` | `str` | `""` | Path to policy file |

**Returns:** `PipelineResult`

**Steps:**
1. `sf_gate.evaluate_prri(prri_score)` — GREEN/AMBER/RED verdict
2. If RED → `sf_alert.publish("halluccheck.risk.critical", ...)`
3. `sf_gate.evaluate("trust-gate", ...)` — blocking gate
4. `sf_cec.build_bundle(...)` — compliance evidence

---

### `benchmark_pipeline(benchmark_results, *, project_id="", model="")`

**TRS-014** — Benchmark pipeline: audit → alert → anonymise.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `benchmark_results` | `dict` | — | Benchmark run results |
| `project_id` | `str` | `""` | Project scope |
| `model` | `str` | `""` | Model identifier |

**Returns:** `PipelineResult`

**Steps:**
1. `sf_audit.append(benchmark_results, "halluccheck.benchmark.v1")`
2. If accuracy below threshold → `sf_alert.publish("halluccheck.benchmark.degraded", ...)`
3. `sf_pii.anonymise()` on results before export

---

## Return type

### `PipelineResult`

| Field | Type | Description |
|-------|------|-------------|
| `pipeline` | `str` | Pipeline name (`"score"`, `"bias"`, `"monitor"`, `"risk"`, `"benchmark"`) |
| `success` | `bool` | Whether the pipeline completed without errors |
| `audit_id` | `str` | Audit record ID from the pipeline's audit step |
| `span_id` | `str` | Span ID from the observe step (if applicable) |
| `details` | `dict` | Pipeline-specific details and metrics |

---

## Exceptions

| Exception | Raised when |
|-----------|-------------|
| `SFPipelineError` | A critical step within a pipeline fails |
