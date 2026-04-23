# spanforge.sdk.policy

Runtime policy engine for SpanForge GA governance controls.

## `SFPolicyClient`

```python
from spanforge.sdk import sf_policy
```

`sf_policy` is the control-plane layer used by `sf_explain`, `sf_scope`, `sf_rbac`, `sf_rag`, and `sf_lineage`.

## Core Lifecycle

### `load_bundle(bundle)`

Load a `RuntimePolicyBundle` into the local registry.

### `activate(environment, policy_id, version, activated_at)`

Make one loaded bundle active for an environment.

### `deactivate(environment, deactivated_at)`

Remove the active bundle for an environment.

### `promote(...)`

Clone a bundle version from one environment into another.

## Runtime Evaluation

### `evaluate(...)`

Evaluate one service/control pair against the active environment bundle and emit a signed decision.

Supported decision actions:

- `allow`
- `allow+log`
- `redact`
- `block`
- `human_review`

## Replay and Simulation

### `simulate(...)`

Run a candidate bundle against one event without changing production state.

### `replay(...)`

Replay historical events through a candidate bundle and return a summary with simulation records.

### `compare_policies(...)`

Summarize action changes between baseline and candidate bundles.

## Review Loop

### `record_review(...)`

Record analyst feedback on a decision with one of:

- `false_positive`
- `true_positive`
- `needs_tuning`

### `suggest_threshold(...)`

Derive a threshold hint from reviewed decisions.

## Signed Audit Records

`sf_policy` writes the following schema keys into `sf_audit`:

- `spanforge.policy.lifecycle.v1`
- `spanforge.policy.decision.v1`
- `spanforge.policy.simulation.v1`
- `spanforge.policy.replay.v1`
- `spanforge.policy.comparison.v1`
- `spanforge.policy.review.v1`
