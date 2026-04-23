# Runtime Governance GA Guide

SpanForge GA is centered on one operational story:

`runtime request -> policy decision -> signed evidence -> operator review -> export package`

This guide ties together the Phase 1 through Phase 6 runtime-governance surface so platform, security, and compliance teams can understand the product as one control plane instead of a set of disconnected SDK clients.

For the adjacent contract, calibration, and export details, see:

- [Runtime Governance Contracts](runtime-governance-contracts.md)
- [Replay, Simulation, and Calibration](replay-simulation.md)
- [Evidence Export Guide](evidence-export.md)
- [Enterprise Integrations](enterprise-integrations.md)

## GA Services

The May 2, 2026 GA runtime-governance surface consists of five core services:

| Service | Purpose | Primary SDK |
|---------|---------|-------------|
| Explainability | Generate accountable "why" records for runtime decisions | `sf_explain` |
| Scope enforcement | Prevent agents from using capabilities or resources outside their manifest | `sf_scope` |
| RBAC enforcement | Check actor roles before sensitive actions | `sf_rbac` |
| RAG grounding | Score answer grounding and record source-level evidence | `sf_rag` |
| Lineage | Capture provenance across transformation and decision boundaries | `sf_lineage` |

These services are coordinated by:

- `sf_policy` for policy loading, activation, replay, simulation, promotion, and review loops
- `sf_operator` for the operator-facing trace inspection and export workflow
- `sf_enterprise` for deployment posture, retention/export controls, and enterprise evidence packaging

## Runtime Policy Model

Runtime policy bundles are versioned per environment:

```python
from spanforge.runtime_policy import RuntimePolicyBundle, RuntimePolicyRule

bundle = RuntimePolicyBundle(
    policy_id="prod-governance",
    version="2026.05.02",
    environment="prod",
    owner="platform-security",
    effective_at="2026-05-02T00:00:00Z",
    rules=[
        RuntimePolicyRule(
            rule_id="rag-grounding-prod",
            service="sf_rag",
            control="grounding_threshold",
            action="human_review",
            threshold=0.85,
            rationale="Escalate low-grounding answers before delivery.",
            metadata={"comparator": "lt"},
        ),
    ],
)
```

Supported runtime actions:

- `allow`
- `allow+log`
- `redact`
- `block`
- `human_review`

Those actions are emitted as signed policy decisions and then attached to explanation, scope, RBAC, grounding, and lineage evidence.

## Operator Workflow

The operator path is intentionally narrow:

1. Inspect a trace or run.
2. Review the policy decision and its explanation.
3. Check grounding, scope, RBAC, and lineage evidence in one place.
4. Export a signed evidence package from the same path.

CLI:

```bash
spanforge operator inspect TRACE_ID
spanforge operator export TRACE_ID --output operator-package.json
```

SDK:

```python
from spanforge.sdk import sf_operator

workflow = sf_operator.inspect_trace("trace-123")
package = sf_operator.export_package("trace-123", output_path="operator-package.json")
```

The workflow summary is built to answer the operator question directly:

- Why was this request allowed?
- Why was it blocked?
- Which controls contributed?
- Is the signed evidence chain valid?

## Replay, Simulation, and Calibration

`sf_policy` separates production decisions from candidate-policy testing:

- `evaluate()` records live production decisions
- `simulate()` runs a candidate bundle without changing production behavior
- `replay()` pushes historical events through a candidate bundle
- `compare_policies()` summarizes action changes between baseline and candidate bundles
- `record_review()` captures false-positive and tuning feedback
- `suggest_threshold()` derives tuning hints from reviewed decisions

This lets teams test changes such as:

- tightening a grounding threshold
- switching a failed scope check from `human_review` to `block`
- moving explainability coverage from `allow+log` to `human_review`

without changing live traffic first.

See the dedicated [Replay, Simulation, and Calibration](replay-simulation.md) guide for the full Phase 3 workflow.

## Evidence Exports

SpanForge now has two export layers:

| Export | Producer | Intended audience |
|--------|----------|-------------------|
| Operator evidence package | `sf_operator.export_package()` | operators, incident responders, control owners |
| Enterprise evidence package | `sf_enterprise.generate_evidence_package()` | auditors, security, platform review boards |

The enterprise package wraps:

- deployment profile
- retention and export controls
- enterprise status
- operator workflow package
- reference deployment architectures
- signed checksum and signature

See the dedicated [Evidence Export Guide](evidence-export.md) for operator package, enterprise package, JSONL, SIEM, and OpenInference coverage.

## Deployment Credibility

The runtime-governance story assumes real enterprise deployment constraints:

- self-hosted deployment
- air-gapped deployment
- tenant and project isolation
- retention and export controls
- reference architectures for Docker Compose and Kubernetes

See:

- [Enterprise API](api/enterprise.md)
- [Air-Gapped Deployment](deployment/air-gapped.md)
- [Kubernetes Deployment](deployment/kubernetes.md)
- [Reference Architectures](reference-architectures.md)

## Demo Paths

Two runnable demos ship with the repo for the Phase 7 story:

- [Runtime Governance Demo](demos/runtime-governance-demo.md)
- [Enterprise Evidence Demo](demos/enterprise-evidence-demo.md)

The matching scripts live in `examples/` and are intended to be executable from a clean local checkout.
