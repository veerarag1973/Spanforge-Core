# ADR-005: Sandbox Mode for Safe Experimentation

**Status:** Accepted  
**Date:** 2025-07-01  
**Authors:** SpanForge Core Team  

## Context

Developers need a way to experiment with SpanForge without affecting production
audit trails or triggering real alerts.  A misplaced integration test should
never create a permanent audit record or send an alert to on-call engineers.

## Decision

Add `sandbox = true` to `[spanforge]` config (or `SPANFORGE_SANDBOX=1` env var).
When enabled:

- All service calls route to in-memory storage with **no side effects**.
- No events are persisted to disk or exported to remote endpoints.
- `spanforge doctor` displays a prominent `[SANDBOX ACTIVE]` warning.
- The `sandbox` flag is surfaced in every service client's `get_status()` response.

```toml
# spanforge.toml
[spanforge]
sandbox = true
```

```bash
# or via environment variable
SPANFORGE_SANDBOX=1 python my_script.py
```

> **Warning:** Sandbox mode silently discards all audit records.  Never
> enable `sandbox = true` in production; configure `SPANFORGE_SANDBOX` only
> in development and CI environments.

## Consequences

- **Positive:** Safe for tutorials, demos, and CI pipelines.
- **Positive:** No accidental production writes during development.
- **Negative:** Sandbox behaviour may diverge from production; integration
  tests should run against a real endpoint in at least one CI stage.
- **Negative:** Forgetting to disable sandbox in production causes silent data
  loss — mitigated by the `spanforge doctor` warning.

## Alternatives Considered

| Alternative | Reason Rejected |
|---|---|
| Separate "test" project/namespace | Pollutes production accounts; harder to clean up |
| Mock all services in tests only | Doesn't help exploratory scripting outside tests |
| Dry-run flag per call | Verbose API; easy to forget on individual calls |
