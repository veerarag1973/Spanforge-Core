# Reference Architectures

SpanForge Phase 6 and Phase 7 use a small set of reference deployment artifacts already present in the repository. This page consolidates them into one buyer- and operator-facing view.

## Self-Hosted Docker Compose

Artifact:

- `docker-compose.selfhosted.yml`

Use when you need:

- single-environment self-hosting
- local evidence retention
- controlled internal egress
- an operator-friendly lab or staging deployment

The enterprise SDK exposes this artifact through `sf_enterprise.get_reference_architectures()`.

## Kubernetes / Helm

Artifacts:

- `helm/spanforge/values.yaml`
- [Kubernetes deployment guide](deployment/kubernetes.md)

Use when you need:

- multi-replica production runtime
- platform-managed secrets and networking
- controlled rollout and cluster-level policy
- enterprise self-hosted deployments

## Air-Gapped

Artifact:

- [Air-gapped deployment guide](deployment/air-gapped.md)

Use when you need:

- no-egress environments
- regulated or classified workloads
- internal-only telemetry and evidence movement
- deployment reviews that require explicit network-control posture

## Programmatic Access

```python
from spanforge.sdk import sf_enterprise

for ref in sf_enterprise.get_reference_architectures():
    print(ref.architecture_id, ref.mode, ref.artifact_path)
```

That list is also embedded into enterprise evidence packages so exported evidence always points back to the deployment guidance used for review.
