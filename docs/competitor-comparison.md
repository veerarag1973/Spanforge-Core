# Runtime Governance Comparison

SpanForge GA is positioned as a runtime governance and signed-evidence control plane, not as a general-purpose tracing dashboard.

## Comparison Lens

The useful question is not "which tool stores traces?" The useful question is "which tool gives a buyer a clean path from runtime decision to signed, explainable, exportable evidence?"

## Comparison

| Capability | SpanForge | LangSmith | Langfuse | OpenLLMetry | Arize Phoenix |
|------------|-----------|-----------|----------|-------------|---------------|
| Runtime policy actions (`allow`, `allow+log`, `redact`, `block`, `human_review`) | Yes | No | No | No | No |
| Signed runtime evidence chain | Yes | No | No | No | No |
| Trace-to-operator-package workflow | Yes | No | No | No | No |
| Scope and RBAC enforcement in the governance story | Yes | Partial | No | No | No |
| Grounding plus lineage as audit evidence | Yes | Partial | Partial | Partial | Partial |
| Replay and simulation for policy tuning | Yes | Partial | Partial | No | Partial |
| Air-gapped and self-hosted evidence-packaging story | Yes | Partial | Self-host | Partial | Self-host |
| SIEM-friendly governance export path | Yes | Partial | Partial | Partial | Partial |

## Positioning Summary

- SpanForge is strongest when the buyer cares about runtime controls, signed evidence, operator review, and audit handoff.
- LangSmith and Langfuse are strong for general tracing and developer observability, but that is not the same as a runtime-governance control plane.
- OpenLLMetry is strongest as telemetry instrumentation, not as a policy-and-evidence layer.
- Phoenix is strong for evaluation and trace analysis, but the core story is still not signed governance evidence.

## Recommended Reading

- [Runtime Governance GA Guide](runtime-governance.md)
- [Evidence Export Guide](evidence-export.md)
- [Reference Architectures](reference-architectures.md)
