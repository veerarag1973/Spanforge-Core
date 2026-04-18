# ADR-001: Immutable Audit Trail with HMAC Chain

**Status:** Accepted
**Date:** 2025-06-01
**Authors:** SpanForge Core Team

## Context

LLM-powered applications require tamper-evident audit logging for regulatory
compliance (SOC 2, GDPR Article 30, EU AI Act).  We need a mechanism that
proves no audit record has been altered or deleted after the fact.

## Decision

Implement a hash-chain (HMAC) based append-only audit trail:

- Each record includes the HMAC of the previous record, forming a linked chain.
- Records are signed with HMAC-SHA256 using a per-project secret.
- Chain integrity is verifiable offline via `sf_audit.verify_chain()`.
- WORM (Write-Once-Read-Many) backend support is optional.

## Consequences

- **Positive:** Tamper evidence without requiring a blockchain or external notary.
- **Positive:** Works in local mode (no network needed).
- **Negative:** Append-only means storage grows monotonically; retention policies
  must handle archival.
- **Negative:** Chain verification is O(n) in the number of records.

---

# ADR-002: Singleton Service Clients

**Status:** Accepted
**Date:** 2025-06-01

## Context

The SDK needs to provide globally accessible service clients (`sf_pii`,
`sf_audit`, etc.) that share configuration and connection state.

## Decision

Use module-level singleton instances in `spanforge.sdk.__init__`.  Each client
is instantiated lazily from `SFClientConfig.from_env()`.

## Consequences

- **Positive:** Simple ergonomics — `from spanforge.sdk import sf_pii`.
- **Positive:** Configuration is loaded once.
- **Negative:** Singletons are harder to test — mitigated by
  `spanforge.testing_mocks.mock_all_services()`.
- **Negative:** Thread safety relies on each client being internally synchronized.

---

# ADR-003: Schema Versioning Strategy

**Status:** Accepted
**Date:** 2025-06-01

## Context

Event schemas evolve across releases.  Consumers must handle events from
multiple schema versions simultaneously.

## Decision

- Every event carries `schema_version` (string, e.g. `"6"`).
- Schema changes require a new `schema_key` (e.g. `halluc_check_v1`).
- The `spanforge migrate` CLI handles offline schema upgrades.
- Backward-incompatible changes bump the major schema version.

## Consequences

- **Positive:** Consumers can route events by schema version.
- **Positive:** Offline migration enables safe rollouts.
- **Negative:** Multiple schema versions increase validation complexity.

---

# ADR-004: Local-First Architecture

**Status:** Accepted
**Date:** 2025-06-01

## Context

Developers need SpanForge to work without an internet connection or remote
endpoint.

## Decision

All services detect "local mode" (`endpoint == ""`) and fall back to in-process
implementations:
- PII: Presidio-based local scanning.
- Audit: File-based JSONL backend.
- Observe: In-memory span store.
- Gate: Local YAML rule evaluation.

## Consequences

- **Positive:** Zero external dependencies for basic operation.
- **Positive:** Tests run without network access.
- **Negative:** Feature parity between local and remote modes must be maintained.

---

# ADR-005: Sandbox Mode for Safe Experimentation

**Status:** Accepted
**Date:** 2025-07-01

## Context

Developers need a way to experiment with SpanForge without affecting
production audit trails or triggering real alerts.

## Decision

Add `sandbox = true` to `[spanforge]` config (or `SPANFORGE_SANDBOX=1` env var).
When enabled, all service calls route to in-memory storage with no side effects.

## Consequences

- **Positive:** Safe for tutorials, demos, and CI.
- **Positive:** No accidental production writes.
- **Negative:** Sandbox behaviour may diverge from production — `spanforge doctor`
  warns when sandbox is active.
