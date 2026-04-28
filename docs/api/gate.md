# `spanforge.sdk.gate` — CI/CD Gate Pipeline

> **Module:** `spanforge.sdk.gate`  
> **Added in:** 2.0.7 (Phase 8 — CI/CD Gate Pipeline)  
> **Import:** `from spanforge.sdk import sf_gate` or `from spanforge.sdk.gate import SFGateClient`

The gate module provides the `SFGateClient` singleton and the `GateRunner` YAML engine. It evaluates quality gates (schema validation, dependency security, secrets scanning, performance regression, and hallucination checks) against AI system artifacts and emits structured `GateArtifact` records with durable storage.

---

## Quick example

```python
from spanforge.sdk import sf_gate
from spanforge.sdk import GateVerdict

# Evaluate a single gate
result = sf_gate.evaluate(
    gate_id="schema-check",
    payload={"schema_version": "2.0", "source": "my-app@1.0.0"},
)
if result.verdict == GateVerdict.PASS:
    print(f"Gate passed in {result.duration_ms:.0f} ms")
else:
    raise RuntimeError(f"Gate {result.gate_id} {result.verdict.value}: {result.metrics}")
```

---

## Singleton

`spanforge.sdk.sf_gate` is a module-level `SFGateClient` instance constructed
from environment variables. For most use-cases, import and use the singleton:

```python
from spanforge.sdk import sf_gate

status = sf_gate.get_status()
print(status.gate_count, status.artifact_count)
```

---

## `SFGateClient`

```python
class SFGateClient:
    def evaluate(
        self,
        gate_id: str,
        payload: dict,
        *,
        project_id: str | None = None,
    ) -> GateEvaluationResult: ...

    def evaluate_prri(
        self,
        prri_score: float,
        *,
        project_id: str | None = None,
        framework: str = "default",
        policy_file: str | None = None,
        dimension_breakdown: dict[str, float] | None = None,
    ) -> PRRIResult: ...

    def run_pipeline(
        self,
        gate_config_path: str,
        *,
        context: dict | None = None,
    ) -> GateRunResult: ...

    def get_artifact(self, gate_id: str) -> GateArtifact | None: ...

    def list_artifacts(self, *, project_id: str | None = None) -> list[GateArtifact]: ...

    def purge_artifacts(self, *, older_than_days: int = 90) -> int: ...

    def get_status(self) -> GateStatusInfo: ...

    def configure(self, config: dict) -> None: ...
```

### `evaluate(gate_id, payload, *, project_id) → GateEvaluationResult`

Evaluate a single named gate against `payload`.

---

### `evaluate_async()` — async variant

> **Added in:** 1.0.0

```python
async def evaluate_async(
    self,
    gate_id: str,
    payload: dict,
    *,
    project_id: str = "",
    pipeline_id: str = "",
) -> GateEvaluationResult
```

Non-blocking async variant of `evaluate()`.  Delegates to the synchronous
method via `asyncio.get_event_loop().run_in_executor()` so it never blocks the
event loop.  Ideal for async CI/CD runners and FastAPI-based pipelines.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `gate_id` | `str` | *(required)* | Gate identifier. |
| `payload` | `dict` | *(required)* | Payload to evaluate. |
| `project_id` | `str` | `""` | Optional project scope. |
| `pipeline_id` | `str` | `""` | Optional pipeline label for the artifact. |

**Returns** `GateEvaluationResult`

**Example:**

```python
import asyncio
from spanforge.sdk import sf_gate

result = asyncio.run(
    sf_gate.evaluate_async("schema-check", {"schema_version": "2.0"})
)
assert result.verdict.value == "pass"
```

---

The evaluation applies the gate logic registered under `gate_id` (schema
validation, secrets scan, dependency audit, performance regression check, or
hallucination verifier). The result is written to the artifact store.

**Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `gate_id` | `str` | Identifier for the gate to evaluate. Used as the artifact key. |
| `payload` | `dict` | Data to evaluate (event dict, schema snippet, config object, etc.). |
| `project_id` | `str \| None` | Optional project scope for artifact isolation. |

**Returns** `GateEvaluationResult`

**Raises**

| Exception | When |
|-----------|------|
| `SFGateEvaluationError` | Evaluation logic raised an error or gate returned `FAIL` with `on_fail="block"`. |
| `SFGateTrustFailedError` | Trust gate detected a blocking condition (HRI critical rate, PII window, or secrets window exceeded). |

**Example**

```python
from spanforge.sdk import sf_gate, GateVerdict

result = sf_gate.evaluate("dependency-audit", {"package": "requests==2.28.0"})
assert result.verdict in (GateVerdict.PASS, GateVerdict.WARN)
print(result.metrics)         # {"cve_count": 0, "severity_max": "NONE"}
print(result.artifact_url)    # ".sf-gate/artifacts/dependency-audit-<ulid>.json"
```

---

### `evaluate_prri(prri_score, *, project_id, framework, policy_file, dimension_breakdown) → PRRIResult`

Evaluate a Pre-Release Readiness Index (PRRI) score against policy thresholds.

Scores at or above `SPANFORGE_GATE_PRRI_RED_THRESHOLD` (default 70) receive a
`RED` verdict, which blocks release when `on_fail="block"`. Scores between 30 and
69 receive `AMBER` (warn). Scores below 30 receive `GREEN` (pass).

**Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `prri_score` | `float` | Aggregate PRRI score (0–100). Higher = more risk. |
| `project_id` | `str \| None` | Optional project scope. |
| `framework` | `str` | Policy framework identifier (default: `"default"`). |
| `policy_file` | `str \| None` | Path to a custom YAML policy file. When `None`, the built-in thresholds apply. |
| `dimension_breakdown` | `dict[str, float] \| None` | Per-dimension scores (e.g. `{"hallucination": 0.72, "bias": 0.41}`). Stored in the artifact for audit. |

**Returns** `PRRIResult`

**Raises** `SFGateEvaluationError` — policy file not found, or `prri_score` outside `[0, 100]`.

**Example**

```python
result = sf_gate.evaluate_prri(
    65.0,
    project_id="my-agent",
    dimension_breakdown={"hallucination": 0.65, "bias": 0.50},
)
print(result.verdict)    # PRRIVerdict.AMBER
print(result.allow)      # True  (AMBER warns but does not block by default)
```

---

### `run_pipeline(gate_config_path, *, context) → GateRunResult`

Parse and execute a YAML gate pipeline file.

The YAML file defines an ordered list of gates. Each gate has an `id`, `type`,
optional `pass_condition`, `on_fail` policy (`block`, `warn`, or `report`), and
optional `parallel` flag. Gates with `on_fail: block` that evaluate to `FAIL`
raise `SFGatePipelineError`.

**Parameters**

| Parameter | Type | Description |
|-----------|------|-------------|
| `gate_config_path` | `str` | Path to the gate YAML file. |
| `context` | `dict \| None` | Runtime context variables injected into gate commands (`${var}` substitution). |

**Returns** `GateRunResult` — aggregate result with per-gate `GateArtifact` list.

**Raises**

| Exception | When |
|-----------|------|
| `SFGateSchemaError` | YAML file is missing required fields or has an unrecognised gate type. |
| `SFGatePipelineError` | One or more blocking gates failed. |

**Example**

```python
from spanforge.sdk import sf_gate

run = sf_gate.run_pipeline(
    "examples/gates/sf-gate.yaml",
    context={"project_id": "my-agent", "env": "staging"},
)
print(run.passed, run.failed, run.warned)
for artifact in run.artifacts:
    print(f"  {artifact.gate_id}: {artifact.verdict.value}")
```

**Gate YAML format**

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

  - id: perf-regression
    name: "Performance Regression"
    type: performance_regression
    pass_condition: "p99_latency_ms < 2000"
    on_fail: warn
    artifact: true

  - id: prri-check
    name: "PRRI Readiness Gate"
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

**Gate types**

| Type | Description |
|------|-------------|
| `schema_validation` | Validates payload against the SpanForge v2.0 JSON Schema. |
| `dependency_security` | Audits package dependencies for known CVEs via the advisory database. |
| `secrets_scan` | Runs the built-in 20-pattern secrets scanner over the target files. |
| `performance_regression` | Compares p50/p95/p99 latencies against a baseline stored in the artifact store. |
| `halluccheck_prri` | Evaluates the Pre-Release Readiness Index against policy thresholds. |
| `halluccheck_trust` | Composite trust gate: checks HRI critical rate, PII detection window, and secrets detection window. |

**Gate YAML fields**

| Field | Required | Description |
|-------|----------|-------------|
| `id` | ✅ | Unique gate identifier within the pipeline. Used as the artifact key. |
| `name` | — | Human-readable display name. |
| `type` | ✅ | Gate executor type (see table above). |
| `command` | — | Shell command to run for custom evaluation (output parsed for pass/fail). |
| `pass_condition` | — | Boolean expression evaluated against gate metrics (e.g. `p99_latency_ms < 2000`). |
| `on_fail` | — | `block` (default), `warn`, or `report`. `block` raises `SFGatePipelineError`. |
| `artifact` | — | `true` to write a `GateArtifact` JSON file to the artifact store. |
| `framework` | — | PRRI policy framework identifier (used with `halluccheck_prri`). |
| `timeout_seconds` | — | Per-gate execution timeout (default: `60`). |
| `skip_on` | — | Condition expression; when truthy the gate is skipped with `SKIPPED` verdict. |
| `parallel` | — | `true` to run this gate in parallel with adjacent parallel-flagged gates. |

---

### `get_artifact(gate_id) → GateArtifact | None`

Retrieve the most recent stored artifact for a gate by `gate_id`.

Returns `None` if no artifact is found.

```python
artifact = sf_gate.get_artifact("schema-validation")
if artifact:
    print(artifact.verdict, artifact.timestamp)
```

---

### `list_artifacts(*, project_id) → list[GateArtifact]`

List all stored artifacts, optionally filtered to a `project_id`.

Returns artifacts sorted most-recent-first.

```python
artifacts = sf_gate.list_artifacts(project_id="my-agent")
for a in artifacts:
    print(f"{a.gate_id}: {a.verdict.value} @ {a.timestamp}")
```

---

### `purge_artifacts(*, older_than_days) → int`

Delete artifacts older than `older_than_days`. Returns the count of files
removed from the artifact store.

```python
removed = sf_gate.purge_artifacts(older_than_days=30)
print(f"Purged {removed} stale artifact(s)")
```

---

### `get_status() → GateStatusInfo`

Return a live status snapshot of the gate subsystem.

```python
status = sf_gate.get_status()
print(status.status)         # "ok"
print(status.gate_count)     # number of registered gate types
print(status.artifact_count) # total artifacts on disk
print(status.healthy)        # True
```

---

### `configure(config) → None`

Override gate settings at runtime. Any keys not present keep their
current (env-var-sourced or default) values.

```python
sf_gate.configure({
    "artifact_dir": "/var/spanforge/gate-artifacts",
    "artifact_retention_days": 30,
    "prri_red_threshold": 60,
    "hri_critical_threshold": 0.03,
})
```

---

## Types

All types are exported from `spanforge.sdk`:

```python
from spanforge.sdk import (
    GateVerdict,
    PRRIVerdict,
    GateArtifact,
    GateEvaluationResult,
    PRRIResult,
    TrustGateResult,
    GateStatusInfo,
)
```

### `GateVerdict`

```python
class GateVerdict(str, Enum):
    PASS    = "PASS"
    FAIL    = "FAIL"
    WARN    = "WARN"
    SKIPPED = "SKIPPED"
```

### `PRRIVerdict`

```python
class PRRIVerdict(str, Enum):
    GREEN = "GREEN"   # score < 30 — release ready
    AMBER = "AMBER"   # 30 ≤ score < 70 — warn
    RED   = "RED"     # score ≥ 70 — block
```

### `GateArtifact`

Immutable record written to the artifact store after gate evaluation.

| Field | Type | Description |
|-------|------|-------------|
| `gate_id` | `str` | Gate identifier. |
| `name` | `str` | Human-readable gate name. |
| `verdict` | `GateVerdict` | Evaluation verdict. |
| `metrics` | `dict` | Gate-specific metrics dictionary. |
| `timestamp` | `str` | ISO-8601 UTC timestamp. |
| `duration_ms` | `float` | Wall-clock evaluation time. |
| `artifact_path` | `str \| None` | Absolute path to the JSON artifact file, or `None` if not persisted. |

### `GateEvaluationResult`

Returned by `evaluate()`.

| Field | Type | Description |
|-------|------|-------------|
| `gate_id` | `str` | Gate identifier. |
| `verdict` | `GateVerdict` | Evaluation verdict. |
| `metrics` | `dict` | Gate-specific metrics dictionary. |
| `artifact_url` | `str \| None` | Path to the stored artifact file. |
| `duration_ms` | `float` | Wall-clock evaluation time. |
| `timestamp` | `str` | ISO-8601 UTC timestamp. |

### `PRRIResult`

Returned by `evaluate_prri()`.

| Field | Type | Description |
|-------|------|-------------|
| `gate_id` | `str` | Always `"prri"`. |
| `prri_score` | `float` | Input score (0–100). |
| `verdict` | `PRRIVerdict` | GREEN / AMBER / RED. |
| `dimension_breakdown` | `dict \| None` | Per-dimension scores, if provided. |
| `framework` | `str` | Policy framework used. |
| `policy_file` | `str \| None` | Custom policy file path, if used. |
| `timestamp` | `str` | ISO-8601 UTC timestamp. |
| `allow` | `bool` | `True` if the verdict does not block (GREEN or AMBER). |

### `TrustGateResult`

Returned internally by the `halluccheck_trust` executor; also accessible via
`get_artifact()` after a trust gate run.

| Field | Type | Description |
|-------|------|-------------|
| `gate_id` | `str` | Gate identifier. |
| `verdict` | `GateVerdict` | `PASS`, `FAIL`, or `WARN`. |
| `hri_critical_rate` | `float` | Observed HRI critical rate (0–1). |
| `hri_critical_threshold` | `float` | Configured threshold (from `SPANFORGE_GATE_HRI_CRITICAL_THRESHOLD`). |
| `pii_detected` | `bool` | Whether PII detections exceeded the window threshold. |
| `pii_detections_24h` | `int` | PII detection count in the audit window. |
| `secrets_detected` | `bool` | Whether secrets detections exceeded the window threshold. |
| `secrets_detections_24h` | `int` | Secrets detection count in the audit window. |
| `failures` | `list[str]` | Human-readable description of each blocking failure. |
| `timestamp` | `str` | ISO-8601 UTC timestamp. |
| `pipeline_id` | `str \| None` | Pipeline run ID, if executed via `run_pipeline()`. |
| `project_id` | `str \| None` | Project scope. |

### `GateStatusInfo`

Returned by `get_status()`.

| Field | Type | Description |
|-------|------|-------------|
| `status` | `str` | `"ok"` or `"degraded"`. |
| `gate_count` | `int` | Number of registered gate executors. |
| `artifact_count` | `int` | Total artifact files currently in the store. |
| `artifact_dir` | `str` | Absolute path to the artifact directory. |
| `retention_days` | `int` | Configured artifact retention in days. |
| `open_circuit_breakers` | `int` | Currently open circuit breakers (always 0 for gate — informational). |
| `healthy` | `bool` | `True` when the gate subsystem is operational. |

---

## Exceptions

All exceptions are exported from `spanforge.sdk`:

```python
from spanforge.sdk import (
    SFGateError,
    SFGateEvaluationError,
    SFGatePipelineError,
    SFGateTrustFailedError,
    SFGateSchemaError,
)
```

| Exception | Base | When raised |
|-----------|------|-------------|
| `SFGateError` | `SpanForgeError` | Base for all gate exceptions. Never raised directly. |
| `SFGateEvaluationError` | `SFGateError` | A single gate evaluation failed (logic error, unsupported payload, or `FAIL` with `block` policy). |
| `SFGatePipelineError` | `SFGateError` | Pipeline runner encountered one or more blocking gate failures. `failed_gates: list[str]` attribute lists the gate IDs. |
| `SFGateTrustFailedError` | `SFGateError` | Trust gate detected a blocking condition — HRI critical rate, PII detections, or secrets detections exceeded their window threshold. `trust_result: TrustGateResult` attribute carries full details. |
| `SFGateSchemaError` | `SFGateError` | YAML gate configuration is invalid (missing required field, unrecognised gate type, or malformed pass condition). |

---

## Environment variables

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SPANFORGE_GATE_ARTIFACT_DIR` | `string` | `.sf-gate/artifacts` | Directory where `GateArtifact` JSON files are persisted. Relative to the working directory; absolute paths accepted. |
| `SPANFORGE_GATE_ARTIFACT_RETENTION_DAYS` | `int` | `90` | Artifacts older than this value are eligible for `purge_artifacts()`. |
| `SPANFORGE_GATE_PRRI_RED_THRESHOLD` | `float` | `70` | PRRI scores at or above this value receive a `RED` verdict and block release. |
| `SPANFORGE_GATE_HRI_CRITICAL_THRESHOLD` | `float` | `0.05` | HRI critical-event rate threshold (0–1) for the trust gate. Exceeding this causes `FAIL`. |
| `SPANFORGE_GATE_PII_WINDOW_HOURS` | `int` | `24` | Audit window in hours for the PII detection count check in the trust gate. |
| `SPANFORGE_GATE_SECRETS_WINDOW_HOURS` | `int` | `24` | Audit window in hours for the secrets detection count check in the trust gate. |

---

## Test coverage

The gate module has dedicated subprocess-level mock tests for every built-in
executor (`tests/test_coverage_gaps.py :: TestGateExecutorSubprocessMocks`).

| Executor | Tests | Paths covered |
|----------|-------|---------------|
| `_exec_schema_validation` | 4 | command PASS, command FAIL (with/without stderr), generic exception |
| `_exec_dependency_security` | 6 | PASS (no vulns), FAIL (critical CVEs parsed), JSON parse error, timeout, generic exception, custom command |
| `_exec_secrets_scan` | 4 | secrets detected FAIL, fallback to unstaged diff, ImportError, generic exception |
| `_exec_performance_regression` | 3 | command PASS, command FAIL, generic exception |
| `_exec_halluccheck_prri` | 4 | command + artifact combo, timeout, malformed JSON, generic exception |
| `_exec_halluccheck_trust` | 6 | SDK PASS, SDK FAIL, artifact PASS, artifact FAIL, malformed artifact, no-SDK-no-artifact WARN |

Additional gate tests in `tests/test_sf_gate.py`:

- **`TestInferVerdictBranches`** (18 tests) — exercises every `_infer_verdict` path.
- **`TestPostEvaluateHooksSideEffects`** (7 tests) — hook execution, failure isolation, ordering, and metrics access.
- **`TestGateExecutorHelpers`** — `_evaluate_pass_condition` and `_substitute_template` edge cases.

---

## See also

- [Gate Pipeline user guide](../user_guide/gate.md) — Getting started, YAML examples, CI/CD integration
- [alert](alert.md) — `SFAlertClient` (Phase 7) triggered by `SFGateTrustFailedError`
- [secrets](secrets.md) — Secrets scanner underlying the `secrets_scan` gate type
- [pii](pii.md) — PII scanner underlying the trust gate PII window check
