# Chaos Engineering Tests — DX-023

> **Status:** 🔜 Planned — not yet implemented.

## Overview

Chaos tests for SpanForge verify that the SDK behaves correctly under
adverse conditions: network partitions, service unavailability, WORM
backend failures, and resource exhaustion.

## Failure Scenarios

### 1. Service Unavailability
- Remote endpoint returns HTTP 503 / connection refused.
- **Expected:** local fallback activates within one retry cycle; no
  exceptions propagate to the caller; `local_fallback_enabled=True` is
  the default.

### 2. Network Partition (intermittent)
- Randomly drop 30 % of outbound HTTP requests.
- **Expected:** retry with exponential jitter; circuit breaker trips
  after 5 consecutive failures; `dropped_count` increments; circuit
  auto-resets after 30 s.

### 3. WORM Backend Write Failure
- `append_only.py` underlying file is made read-only mid-session.
- **Expected:** `SFAuditAppendError` raised; audit chain integrity
  verified on existing records; no silent data loss.

### 4. Secrets in Logs Regression
- All log output captured during fault injection.
- **Expected:** zero occurrences of any value matching
  `SecretsScanner.scan()` → non-empty hits in log lines.

### 5. Resource Exhaustion
- BatchExporter queue filled to capacity (`max_queue_size`).
- **Expected:** `put()` returns `False`; `dropped_count` increments;
  no blocking on the caller thread; worker thread remains alive.

## Prerequisites

- `pytest-timeout` and `pytest-mock` installed.
- Linux/macOS: `tc netem` or [toxiproxy](https://github.com/Shopify/toxiproxy)
  for network fault injection.
- Windows: [Clumsy](https://jagt.github.io/clumsy/) or mock-based network stubs.

## Running (future)

```bash
pytest tests/chaos/ -v --timeout=120
```

## Tracking

DX-023 — see `ROADMAP.md` for priority and schedule.
