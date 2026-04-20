# Architecture Decision Records (ADR)

This directory contains the Architecture Decision Records for SpanForge Core.

ADRs document significant design decisions, their context, and their trade-offs.

## Index

| ADR | Title | Status |
|---|---|---|
| [ADR-001](ADR-001-immutable-audit-trail.md) | Immutable Audit Trail with HMAC Chain | Accepted |
| [ADR-002](ADR-002-singleton-service-clients.md) | Singleton Service Clients | Accepted |
| [ADR-003](ADR-003-schema-versioning-strategy.md) | Schema Versioning Strategy | Accepted |
| [ADR-004](ADR-004-local-first-architecture.md) | Local-First Architecture | Accepted |
| [ADR-005](ADR-005-sandbox-mode.md) | Sandbox Mode for Safe Experimentation | Accepted |
| [ADR-006](ADR-006-rag-tracing.md) | RAG Tracing Namespace and SDK Design | Accepted |
| [ADR-007](ADR-007-user-feedback.md) | User Feedback Collection Design | Accepted |
| [ADR-008](ADR-008-sso-scim-oidc.md) | SSO Local-First: SAML 2.0, SCIM 2.0, OIDC, Session Delegation | Accepted |

## Format

Each ADR follows this structure:

- **Status:** Proposed / Accepted / Deprecated / Superseded
- **Date:** Date accepted
- **Context:** Why a decision was needed
- **Decision:** What was decided
- **Consequences:** Trade-offs (positive and negative)
- **Alternatives Considered:** Other options and why they were rejected
