# Runtime Governance Contracts

This page captures the Phase 0 contract surface for the GA runtime-governance spine. It is the short reference for what is stable, what evidence is produced, and how the control plane behaves when a service is unavailable.

## GA Runtime Services

The May 2, 2026 GA runtime-governance services are:

- `SFExplainClient`
- `SFScopeClient`
- `SFRBACClient`
- `SFRAGClient`
- `SFLineageClient`

They are coordinated by:

- `SFPolicyClient` for loading, activating, replaying, simulating, and reviewing policies
- `SFOperatorClient` for trace inspection and operator evidence export
- `SFEnterpriseClient` for deployment posture, retention/export controls, and enterprise evidence packaging

## Stable Service Contracts

| Service | Stable responsibility | Primary signed record |
|--------|------------------------|-----------------------|
| `sf_explain` | Generate runtime decision explanations | `spanforge.explanation.v1` |
| `sf_scope` | Check agent capability and resource boundaries | `spanforge.scope.v1` |
| `sf_rbac` | Check actor role and permission alignment | `spanforge.rbac.v1` |
| `sf_rag` | Record grounding scores, sources, and threshold outcomes | `spanforge.grounding.v1` |
| `sf_lineage` | Capture decision and data provenance | `spanforge.lineage.v1` |
| `sf_policy` | Record runtime policy decisions, comparisons, replay, and review | `spanforge.policy.*.v1` |

The policy action contract is fixed at GA:

- `allow`
- `allow+log`
- `redact`
- `block`
- `human_review`

## Evidence Contract

Every runtime-governance flow is expected to support:

- a trace-linked decision path
- signed evidence for each control that ran
- policy decision records that explain the final action
- exportable JSON packages for operators and auditors

The two top-level packaging contracts are:

| Export | Producer | Purpose |
|--------|----------|---------|
| Operator package | `sf_operator.export_package()` | Incident review, trace-level explanation, control-owner handoff |
| Enterprise package | `sf_enterprise.generate_evidence_package()` | Audit handoff, deployment posture, retention/export control evidence |

## Failure Semantics

The runtime-governance docs assume these semantics:

| Condition | Expected behavior |
|----------|-------------------|
| Service returns a normal decision | Signed record is emitted and can participate in policy evaluation |
| Service has no matching policy | Runtime request continues with service-local behavior and no synthetic block is introduced |
| Candidate-policy replay or simulation fails | Failure is isolated to replay/simulation output and does not change production enforcement |
| Operator export runs with no matching trace evidence | Export still succeeds with an `allow`-style empty workflow summary rather than inventing controls |

## Fallback Behavior

SpanForge already documents broader local fallback behavior in [configuration.md](configuration.md). For the GA runtime-governance story, the important rule is narrower:

- Fallback is allowed for evidence continuity and local operation.
- Replay and simulation must remain separate from live production enforcement.
- Export packages must reflect the evidence that actually exists; they must not synthesize missing scope, RBAC, grounding, explanation, or lineage records.

When you need the wider service-registry and local-fallback details, see:

- [Configuration](configuration.md#local-fallback)
- [Runtime Governance GA Guide](runtime-governance.md)
- [Replay, Simulation, and Calibration](replay-simulation.md)
- [Evidence Export Guide](evidence-export.md)
