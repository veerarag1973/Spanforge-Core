# GA Release Notes

This page summarizes the Phase 0 through Phase 7 GA spine for the May 2, 2026 release.

## What GA Means

SpanForge GA is the runtime governance and compliance control plane for enterprise and regulated AI systems.

The GA path is:

`runtime request -> policy decision -> signed evidence -> operator review -> export package`

## Included at GA

Core runtime-governance services:

- `SFExplainClient`
- `SFScopeClient`
- `SFRBACClient`
- `SFRAGClient`
- `SFLineageClient`

Supporting control-plane services:

- `SFPolicyClient`
- `SFOperatorClient`
- `SFEnterpriseClient`

Enterprise integration and export story:

- OpenAI, Anthropic, Azure OpenAI, LangChain, and LangGraph paths
- OTLP, JSONL, SIEM, and OpenInference-compatible export paths
- self-hosted and air-gapped deployment guidance
- operator and enterprise evidence packaging

## Deferred or Explicitly Not Central to GA

- `SFBiasClient` only if already solid
- `SFRollbackClient`
- `SFCanaryClient`
- `SFWatermarkClient`

## Recommended GA Entry Points

- [Runtime Governance GA Guide](runtime-governance.md)
- [Runtime Governance Contracts](runtime-governance-contracts.md)
- [Replay, Simulation, and Calibration](replay-simulation.md)
- [Evidence Export Guide](evidence-export.md)
- [Enterprise Integrations](enterprise-integrations.md)
- [Reference Architectures](reference-architectures.md)
- [Runtime Governance Demo](demos/runtime-governance-demo.md)
- [Enterprise Evidence Demo](demos/enterprise-evidence-demo.md)
