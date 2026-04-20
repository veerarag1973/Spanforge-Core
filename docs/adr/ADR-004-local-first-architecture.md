# ADR-004: Local-First Architecture

**Status:** Accepted  
**Date:** 2025-06-01  
**Authors:** SpanForge Core Team  

## Context

Developers need SpanForge to work without an internet connection or a remote
endpoint during development and testing.  Requiring a live server for every
test run slows CI and creates unnecessary external dependencies.

## Decision

All services detect "local mode" when `endpoint == ""` (or is not set) and fall
back to in-process implementations:

| Service | Local Mode Behaviour |
|---|---|
| `sf_pii` | Presidio-based local scanning |
| `sf_audit` | File-based JSONL append-only backend |
| `sf_observe` | In-memory span store; OTLP export skipped |
| `sf_gate` | Local YAML rule evaluation; subprocess gates still run |
| `sf_alert` | In-memory alert queue; no webhook/email delivery |

> **Warning:** In local mode, state is stored **in-memory or in local files**.
> It is not shared across processes and is lost on restart.  See the
> [In-Memory State](../user_guide/in_memory_state.md) guide for details.

## Consequences

- **Positive:** Zero external dependencies for basic operation.
- **Positive:** Tests run without network access; no mocking of HTTP clients.
- **Negative:** Feature parity between local and remote modes must be actively
  maintained.
- **Negative:** In-memory spans/alerts are lost on process restart; production
  deployments must configure a real endpoint.

## Alternatives Considered

| Alternative | Reason Rejected |
|---|---|
| Always require a remote endpoint | Breaks offline development; slow CI |
| Embedded SQLite for all local state | Adds a dependency; overkill for ephemeral dev data |
| Docker-compose test stack required | Too heavy for unit tests; poor DX |
