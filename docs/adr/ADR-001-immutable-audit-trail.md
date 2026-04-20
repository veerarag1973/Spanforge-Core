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

## Alternatives Considered

| Alternative | Reason Rejected |
|---|---|
| Blockchain-based notary | External dependency, operational complexity, cost |
| Database row-level audit triggers | Vendor-locked, not portable, schema-dependent |
| Write-once S3 object lock only | No cryptographic chain, no offline verification |
