# Load Tests — DX-024

> **Status:** 🔜 Planned — not yet implemented.

## Overview

k6-based load tests verifying p95 latency SLOs for the core SpanForge services
under sustained traffic.

## Target SLOs

| Endpoint | Target RPS | p95 Latency SLO |
|----------|-----------|-----------------|
| Scoring (`sf_gate.evaluate()`) | 100 rps | < 200 ms |
| PII scan (`sf_pii.scan_text()`) | 50 rps | < 150 ms |
| Secrets scan (`sf_secrets.scan()`) | 100 rps | < 100 ms |
| Audit append (`sf_audit.append()`) | 200 rps | < 50 ms |
| Observe emit (`sf_observe.emit_span()`) | 500 rps | < 20 ms |

## Planned Test Scenarios

1. **Steady-state** — constant load at 50 % of target RPS for 5 minutes.
2. **Ramp-up** — linear ramp from 0 → target RPS over 2 minutes, hold for
   3 minutes, ramp down over 1 minute.
3. **Spike** — 10 × target RPS burst for 30 seconds; verify graceful degradation
   (circuit breaker opens, dropped_count increments, 200 ms SLO NOT violated for
   requests that are admitted).
4. **Soak** — target RPS sustained for 30 minutes; verify no memory growth > 20 MB,
   no file-descriptor leaks.

## Prerequisites

- [k6](https://k6.io) ≥ v0.50
- SpanForge server running locally:
  ```bash
  spanforge serve --port 8765
  ```

## Running (future)

```bash
k6 run tests/load/scoring.js --env SPANFORGE_URL=http://localhost:8765
k6 run tests/load/pii_scan.js --env SPANFORGE_URL=http://localhost:8765
k6 run tests/load/secrets_scan.js --env SPANFORGE_URL=http://localhost:8765
```

## Tracking

DX-024 — see `ROADMAP.md` for priority and schedule.
