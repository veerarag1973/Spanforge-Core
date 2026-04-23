# Replay, Simulation, and Calibration

Phase 3 turns runtime governance from a blocking layer into a tunable control plane. This page is the focused guide for testing policy changes before they affect production traffic.

## What Runs Where

`sf_policy` separates live enforcement from candidate-policy analysis:

- `evaluate()` records the production decision that actually governed the request
- `simulate()` runs a candidate bundle without changing the production result
- `replay()` runs historical events through a candidate bundle
- `compare_policies()` summarizes how baseline and candidate actions differ
- `record_review()` captures false-positive and analyst feedback
- `suggest_threshold()` proposes threshold adjustments from reviewed outcomes

## Typical Workflow

1. Start from a versioned baseline bundle for `dev`, `staging`, or `prod`.
2. Create a candidate bundle with one concrete change.
3. Run `simulate()` for representative live-like requests.
4. Run `replay()` against historical trace-linked events.
5. Use `compare_policies()` to quantify action changes.
6. Record review outcomes for false positives and justified escalations.
7. Promote the candidate only after the calibration data is acceptable.

## Tuning Targets

The main GA calibration knobs are:

- grounding confidence thresholds
- scope violation handling
- RBAC violation handling
- explainability coverage rules

Examples:

- move low-grounding responses from `allow+log` to `human_review`
- tighten a scope rule from `human_review` to `block`
- relax an RBAC rule that is producing known false positives in staging

## Production Separation

Replay and simulation records are intentionally separate from production evidence:

- production decisions describe what actually governed the request
- simulation decisions describe what a candidate policy would have done
- replay outputs are for tuning and approval, not for claiming live enforcement

That separation matters for audits and incident review. Operators should be able to tell whether a result came from live control enforcement or from policy testing.

## False-Positive Review Loop

The practical loop is:

1. review a blocked or escalated decision
2. classify it as justified or false positive
3. persist that review with `record_review()`
4. use `suggest_threshold()` and comparison output to adjust the candidate bundle
5. rerun replay or simulation before activation

## Related Docs

- [Runtime Governance GA Guide](runtime-governance.md)
- [Runtime Governance Contracts](runtime-governance-contracts.md)
- [API Reference: `spanforge.sdk.policy`](api/policy.md)
- [Runtime Governance Demo](demos/runtime-governance-demo.md)
