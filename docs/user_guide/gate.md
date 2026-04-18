# Gate Pipeline (sf-gate)

> **Added in:** 2.0.7 (Phase 8)  
> **Module:** `spanforge.sdk.gate`  
> **Singleton:** `spanforge.sdk.sf_gate`

sf-gate is SpanForge's CI/CD quality gate pipeline. It evaluates AI system artifacts against a configurable set of gates — schema validation, dependency security, secrets scanning, performance regression, and hallucination readiness checks — before each release or deployment.

---

## Installation

sf-gate is included in the core package. No additional extras are required:

```bash
pip install spanforge
```

---

## Getting started

### 1 — Quick single-gate evaluation

```python
from spanforge.sdk import sf_gate, GateVerdict

result = sf_gate.evaluate(
    "schema-validation",
    {"schema_version": "2.0", "source": "my-app@1.0.0", "payload": {}},
)
if result.verdict == GateVerdict.PASS:
    print(f"Gate passed in {result.duration_ms:.0f} ms")
else:
    print(f"Gate {result.verdict.value}: {result.metrics}")
```

### 2 — YAML pipeline

Define your gates in a YAML file and run the whole pipeline with one call:

```python
from spanforge.sdk import sf_gate

run = sf_gate.run_pipeline("gates/ci-pipeline.yaml")
print(f"Passed: {run.passed}  Failed: {run.failed}  Warned: {run.warned}")
for artifact in run.artifacts:
    print(f"  {artifact.gate_id}: {artifact.verdict.value} ({artifact.duration_ms:.0f} ms)")
```

**`gates/ci-pipeline.yaml`**

```yaml
gates:
  - id: schema-validation
    name: "Schema Validation"
    type: schema_validation
    on_fail: block
    artifact: true

  - id: secrets-scan
    name: "Secrets Scan"
    type: secrets_scan
    on_fail: block
    artifact: true

  - id: dependency-audit
    name: "Dependency Security Audit"
    type: dependency_security
    on_fail: warn
    artifact: true

  - id: perf-regression
    name: "Performance Regression"
    type: performance_regression
    pass_condition: "p99_latency_ms < 2000"
    on_fail: warn
    artifact: true

  - id: prri-check
    name: "Pre-Release Readiness Index"
    type: halluccheck_prri
    framework: default
    on_fail: block
    artifact: true

  - id: trust-gate
    name: "Trust Gate"
    type: halluccheck_trust
    on_fail: block
    artifact: true
```

---

## Configuration

Gate settings are read from environment variables at client construction time.

| Variable | Default | Description |
|----------|---------|-------------|
| `SPANFORGE_GATE_ARTIFACT_DIR` | `.sf-gate/artifacts` | Directory for persisted `GateArtifact` JSON files. |
| `SPANFORGE_GATE_ARTIFACT_RETENTION_DAYS` | `90` | Artifact retention period for `purge_artifacts()`. |
| `SPANFORGE_GATE_PRRI_RED_THRESHOLD` | `70` | PRRI scores ≥ this value receive `RED` (block). |
| `SPANFORGE_GATE_HRI_CRITICAL_THRESHOLD` | `0.05` | HRI critical rate threshold for the trust gate. |
| `SPANFORGE_GATE_PII_WINDOW_HOURS` | `24` | PII detection audit window in hours for the trust gate. |
| `SPANFORGE_GATE_SECRETS_WINDOW_HOURS` | `24` | Secrets detection audit window in hours for the trust gate. |

Override at runtime with `sf_gate.configure()`:

```python
sf_gate.configure({
    "artifact_dir": "/ci/gate-artifacts",
    "artifact_retention_days": 30,
    "prri_red_threshold": 60,
})
```

See [Gate service settings](../configuration.md#gate-service-settings-phase-8) for the full reference.

---

## Gate types

### `schema_validation`

Validates the supplied payload against the SpanForge v2.0 JSON Schema. Checks
required fields (`schema_version`, `source`, `payload`), field formats, and
registered event types.

```yaml
- id: schema-check
  type: schema_validation
  on_fail: block
```

**Metrics emitted:** `valid: bool`, `violations: list[str]`

---

### `dependency_security`

Audits Python package dependencies for known CVEs. Reads from `requirements.txt`
or the lock file specified in `command`. Reports the maximum CVE severity found.

```yaml
- id: dep-audit
  type: dependency_security
  command: "pip list --format=json"
  on_fail: warn
```

**Metrics emitted:** `cve_count: int`, `severity_max: str`, `packages_scanned: int`

---

### `secrets_scan`

Runs the built-in 20-pattern secrets scanner over the file or directory
specified in `command`. Auto-blocking secret types immediately produce `FAIL`.

```yaml
- id: secrets-scan
  type: secrets_scan
  command: "src/"
  on_fail: block
```

**Metrics emitted:** `detected: bool`, `auto_blocked: bool`, `hit_count: int`, `types: list[str]`

---

### `performance_regression`

Compares p50/p95/p99 latency percentiles from the most recent trace events
against a stored baseline. Use `pass_condition` to specify the threshold.

```yaml
- id: perf-check
  type: performance_regression
  pass_condition: "p99_latency_ms < 2000"
  on_fail: warn
```

**Metrics emitted:** `p50_latency_ms: float`, `p95_latency_ms: float`, `p99_latency_ms: float`, `baseline_p99_ms: float`, `regression_pct: float`

---

### `halluccheck_prri`

Evaluates the Pre-Release Readiness Index (PRRI). PRRI scores are derived from
hallucination rate, refusal accuracy, PII leakage rate, and cost drift metrics.

| Score range | Verdict | Default policy |
|-------------|---------|----------------|
| < 30 | `GREEN` → `PASS` | Allow |
| 30–69 | `AMBER` → `WARN` | Warn |
| ≥ 70 | `RED` → `FAIL` | Block |

```yaml
- id: prri-gate
  type: halluccheck_prri
  framework: default
  on_fail: block
```

Use `sf_gate.evaluate_prri()` directly when you have a computed score:

```python
result = sf_gate.evaluate_prri(
    42.5,
    project_id="my-agent",
    dimension_breakdown={"hallucination": 0.42, "bias": 0.31, "pii_leak": 0.15},
)
print(result.verdict)   # PRRIVerdict.AMBER
print(result.allow)     # True
```

---

### `halluccheck_trust`

Composite trust gate that checks three live telemetry windows:

1. **HRI critical rate** — fraction of spans with `hri_critical=True` over the last 24 h. Blocks when rate ≥ `SPANFORGE_GATE_HRI_CRITICAL_THRESHOLD` (default `0.05`).
2. **PII detection window** — any PII detections in the last `SPANFORGE_GATE_PII_WINDOW_HOURS` hours. Blocks when detections > 0.
3. **Secrets detection window** — any secrets detections in the last `SPANFORGE_GATE_SECRETS_WINDOW_HOURS` hours. Blocks when detections > 0.

All three must pass for the gate to return `GateVerdict.PASS`. A blocking failure raises `SFGateTrustFailedError` and triggers a `CRITICAL` sf-alert notification.

```yaml
- id: trust-gate
  type: halluccheck_trust
  on_fail: block
```

**Metrics emitted:** `hri_critical_rate: float`, `pii_detections_24h: int`, `secrets_detections_24h: int`, `failures: list[str]`

---

## PRRI gate (standalone)

Use `evaluate_prri()` when integrating with an external evaluation harness that
already computes a PRRI score:

```python
from spanforge.sdk import sf_gate, PRRIVerdict

result = sf_gate.evaluate_prri(
    prri_score=55.0,
    project_id="my-agent",
    framework="default",
    dimension_breakdown={
        "hallucination": 0.55,
        "refusal_accuracy": 0.40,
        "pii_leak_rate": 0.20,
        "cost_drift": 0.15,
    },
)

if result.verdict == PRRIVerdict.RED:
    raise SystemExit(f"Release blocked: PRRI score {result.prri_score} is RED")
elif result.verdict == PRRIVerdict.AMBER:
    print(f"Warning: PRRI score {result.prri_score} is AMBER — review before release")
```

---

## Artifact store

Every gate evaluation optionally writes a `GateArtifact` JSON record to
`SPANFORGE_GATE_ARTIFACT_DIR`. Artifacts provide a durable audit trail of every
gate decision.

```python
# Retrieve the most recent artifact for a gate
artifact = sf_gate.get_artifact("schema-validation")
print(artifact.verdict, artifact.timestamp, artifact.duration_ms)

# List all artifacts for a project
artifacts = sf_gate.list_artifacts(project_id="my-agent")

# Purge artifacts older than 30 days
removed = sf_gate.purge_artifacts(older_than_days=30)
print(f"Purged {removed} artifact(s)")
```

**Artifact file format** (`.sf-gate/artifacts/<gate_id>-<ulid>.json`):

```json
{
  "gate_id": "schema-validation",
  "name": "Schema Validation",
  "verdict": "PASS",
  "metrics": {"valid": true, "violations": []},
  "timestamp": "2026-03-15T10:23:45.123Z",
  "duration_ms": 4.7,
  "artifact_path": ".sf-gate/artifacts/schema-validation-01JP....json"
}
```

---

## CI/CD integration

### GitHub Actions

Add a gate pipeline step to your workflow to block merges on failing gates:

```yaml
# .github/workflows/ci.yml
jobs:
  gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install spanforge
        run: pip install spanforge

      - name: Run SpanForge gate pipeline
        env:
          SPANFORGE_GATE_ARTIFACT_DIR: .sf-gate/artifacts
          SPANFORGE_GATE_PRRI_RED_THRESHOLD: "65"
          SPANFORGE_GATE_HRI_CRITICAL_THRESHOLD: "0.03"
        run: |
          python - <<'EOF'
          from spanforge.sdk import sf_gate
          from spanforge.sdk import SFGatePipelineError

          try:
              run = sf_gate.run_pipeline("gates/ci-pipeline.yaml")
              print(f"Gates passed: {run.passed}/{run.passed + run.failed + run.warned}")
          except SFGatePipelineError as exc:
              print(f"BLOCKED: {exc.failed_gates}")
              raise SystemExit(1)
          EOF

      - name: Upload gate artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: spanforge-gate-artifacts
          path: .sf-gate/artifacts/
```

### CLI

Run the gate pipeline from the command line:

```bash
# Run a YAML pipeline
spanforge gate run gates/ci-pipeline.yaml

# Evaluate a single gate
spanforge gate evaluate schema-validation --payload events.jsonl

# Run the composite trust gate
spanforge gate trust-gate --project-id my-agent
```

See [`gate` CLI reference](../cli.md#gate) for full options.

---

## Error handling

```python
from spanforge.sdk import sf_gate
from spanforge.sdk import (
    SFGatePipelineError,
    SFGateTrustFailedError,
    SFGateSchemaError,
)

try:
    run = sf_gate.run_pipeline("gates/ci-pipeline.yaml")
except SFGateSchemaError as exc:
    # Invalid YAML — fix the gate config
    print(f"Gate config error: {exc}")
    raise SystemExit(2)
except SFGateTrustFailedError as exc:
    # Trust gate blocked — inspect the full trust result
    trust = exc.trust_result
    print(f"Trust failures: {trust.failures}")
    print(f"  HRI critical rate: {trust.hri_critical_rate:.3f}")
    print(f"  PII detections:    {trust.pii_detections_24h}")
    print(f"  Secrets detections:{trust.secrets_detections_24h}")
    raise SystemExit(1)
except SFGatePipelineError as exc:
    # One or more blocking gates failed
    print(f"Blocked by gates: {exc.failed_gates}")
    raise SystemExit(1)
```

---

## Status check

```python
status = sf_gate.get_status()
print(f"Status:          {status.status}")
print(f"Gate executors:  {status.gate_count}")
print(f"Stored artifacts:{status.artifact_count}")
print(f"Artifact dir:    {status.artifact_dir}")
print(f"Retention days:  {status.retention_days}")
print(f"Healthy:         {status.healthy}")
```

---

## Reference

- [API reference — spanforge.sdk.gate](../api/gate.md) — Full method signatures, types, and exceptions
- [Configuration — Gate service settings](../configuration.md#gate-service-settings-phase-8) — All `SPANFORGE_GATE_*` environment variables
- [CLI — `gate`](../cli.md#gate) — Command-line interface
- [Alert Routing Service (sf-alert)](alert.md) — Receives `CRITICAL` alerts from trust gate failures
- [Secrets scanning](../api/secrets.md) — Underlying `secrets_scan` gate executor
- [PII Redaction](redaction.md) — Underlying trust gate PII window check
