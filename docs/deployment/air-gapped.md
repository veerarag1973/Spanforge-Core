# Air-Gapped Deployment Guide

This guide covers deploying SpanForge in **air-gapped** (no-egress) environments
where outbound network access from the SDK is prohibited.

## Configuration

Enable air-gapped mode via environment variable or code:

### Environment Variable

```bash
export SPANFORGE_NO_EGRESS=1
```

### Code

```python
import spanforge

spanforge.configure(
    no_egress=True,
    exporter="jsonl",            # local-only exporter
    endpoint="audit.jsonl",
)
```

### With Egress Allowlist

In environments where selected internal endpoints are permitted:

```python
spanforge.configure(
    no_egress=True,
    egress_allowlist=frozenset([
        "https://internal-collector.corp.local/",
        "https://otel.internal:4318/",
    ]),
    exporter="otlp",
    endpoint="https://internal-collector.corp.local/v1/traces",
)
```

## Behaviour

When `no_egress=True`:

| Exporter          | Behaviour                                    |
|-------------------|----------------------------------------------|
| `console`         | Works (no network I/O)                       |
| `jsonl`           | Works (local file only)                      |
| `append_only`     | Works (local file only)                      |
| `otlp`            | **Blocked** — raises `EgressViolationError`  |
| `webhook`         | **Blocked** — raises `EgressViolationError`  |
| `datadog`         | **Blocked** — raises `EgressViolationError`  |
| `grafana_loki`    | **Blocked** — raises `EgressViolationError`  |
| `otel_bridge`     | Depends on the configured OTel SDK exporter  |

Blocked exporters raise `EgressViolationError` immediately — no partial data
is sent. The exception includes both the `backend` name and the `endpoint`
that was rejected.

## Recommended Architecture

```
┌─────────────────┐       ┌─────────────────────────┐
│  Application    │       │  Internal Collector      │
│  + SpanForge    │─ ─ ─▶│  (allowlisted endpoint)  │
│  no_egress=True │       │  e.g. OTLP on 4318      │
└─────────────────┘       └─────────────────────────┘
        │
        ▼ (local)
   audit.jsonl
   (append-only)
```

For maximum security, use the `AppendOnlyJSONLExporter` with a WORM backend
to push sealed files to internal immutable storage.

## Compliance Notes

- **SOC 2 CC6.1**: Air-gapped mode satisfies the "no data leaves the boundary"
  access control requirement. `model_registry.*` events are also mapped to this
  clause for model access governance.
- **HIPAA 164.312(e)**: Prevents accidental PHI exfiltration via telemetry.
- **GDPR Art. 25**: Privacy-by-design — no external data transfer by default.
  `consent.*` events are mapped to this clause in compliance evidence packages.
- **GDPR Art. 22**: `consent.*` and `hitl.*` events map to automated
  decision-making oversight requirements.
- **EU AI Act Art. 14**: `hitl.*` and `consent.*` events map to human oversight
  requirements.

## Verification

```bash
# Check health (will fail if exporter tries to reach a blocked endpoint)
spanforge check

# Verify audit chain locally
spanforge audit-chain audit.jsonl
```

---

## Enterprise Air-Gap Mode (Phase 11)

Phase 11 introduces `SFEnterpriseClient.configure_airgap()` for a richer
air-gap experience that also covers multi-tenant isolation, encryption, and
health probes.

### Environment Variable

```bash
export SPANFORGE_ENTERPRISE_ENABLED=true
export SPANFORGE_ENTERPRISE_AIRGAP=true
```

### Python API

```python
from spanforge.sdk import sf_enterprise

sf_enterprise.configure_airgap(enabled=True)

# All outbound calls are blocked; local-only operations proceed normally
status = sf_enterprise.status()
print(status.airgap_enabled)  # True
```

### Self-Hosted Docker Compose

For fully self-hosted deployments, use the `docker-compose.selfhosted.yml` in
the repository root:

```bash
docker compose -f docker-compose.selfhosted.yml up -d
```

This starts SpanForge with all telemetry stored locally (no egress), bundled
with a local Prometheus + Grafana stack for observability.

### Helm Chart (Kubernetes)

For Kubernetes air-gapped deployments, use the Helm chart at `helm/spanforge/`:

```bash
helm install spanforge ./helm/spanforge \
  --set enterprise.airgap=true \
  --set enterprise.enabled=true
```

See [Kubernetes deployment](kubernetes.md) for full Helm chart reference.
