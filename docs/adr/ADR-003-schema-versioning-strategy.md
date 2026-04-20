# ADR-003: Schema Versioning Strategy

**Status:** Accepted  
**Date:** 2025-06-01  
**Authors:** SpanForge Core Team  

## Context

Event schemas evolve across releases.  Consumers must handle events from
multiple schema versions simultaneously.  Breaking changes must not silently
corrupt downstream consumers.

## Decision

- Every event carries a `schema_version` field (string, e.g. `"6"`).
- Schema changes require a new `schema_key` (e.g. `halluc_check_v1`).
- The `spanforge migrate` CLI handles offline schema upgrades.
- Backward-incompatible changes bump the major schema version.
- The `VersionRegistry` tracks all known version tuples and enforces
  compatibility checks via `check_compatible()`.

Version format: `MAJOR.MINOR` (e.g. `"6.0"`).  The dot is a literal separator
and must be escaped in regex patterns (e.g. `r"MAJOR\.MINOR"`).

## Consequences

- **Positive:** Consumers can route events by schema version.
- **Positive:** Offline migration enables safe rollouts without downtime.
- **Negative:** Multiple schema versions increase validation complexity.
- **Negative:** Version registry must be kept in sync with released event shapes.

## Alternatives Considered

| Alternative | Reason Rejected |
|---|---|
| No versioning (implicit schema) | Breaks silently on upgrades |
| Content-type header versioning only | Not portable to JSONL / file-based transports |
| Protobuf field numbers | Binary format; incompatible with JSON-native tooling |
