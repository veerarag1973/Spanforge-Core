# Demo: Runtime Governance Trace to Evidence

This demo walks through the core GA operator story:

`runtime trace -> policy decision -> explanation / grounding / scope / RBAC / lineage -> operator package`

## Script

Run:

```bash
python examples/runtime_governance_demo.py
```

What it does:

1. Loads and activates a production runtime policy bundle.
2. Registers scope and RBAC manifests.
3. Creates a trace with one low-grounding answer path.
4. Emits signed policy, explanation, grounding, scope, RBAC, and lineage records.
5. Inspects the trace through `sf_operator`.
6. Exports a signed operator evidence package to `examples/artifacts/runtime_governance_operator_package.json`.

## Expected Outcome

The example is intentionally tuned so the grounding path triggers human review:

- policy action: `human_review`
- scope decision: allowed
- RBAC decision: allowed
- grounding result: below threshold
- operator outcome: escalated for review

## Relevant APIs

- `sf_policy.load_bundle()`
- `sf_policy.activate()`
- `sf_scope.evaluate_with_policy()`
- `sf_rbac.authorize_with_policy()`
- `sf_rag.assess_grounding_with_policy()`
- `sf_explain.generate_with_policy()`
- `sf_lineage.record_with_policy()`
- `sf_operator.inspect_trace()`
- `sf_operator.export_package()`

## CLI Follow-Up

After running the script, inspect the same trace from the CLI:

```bash
spanforge operator inspect trace-phase7-runtime --format json
spanforge operator export trace-phase7-runtime --output operator-package.json
```
