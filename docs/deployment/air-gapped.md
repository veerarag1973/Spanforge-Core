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
  access control requirement.
- **HIPAA 164.312(e)**: Prevents accidental PHI exfiltration via telemetry.
- **GDPR Art. 25**: Privacy-by-design — no external data transfer by default.

## Verification

```bash
# Check health (will fail if exporter tries to reach a blocked endpoint)
spanforge check

# Verify audit chain locally
spanforge audit-chain audit.jsonl
```
