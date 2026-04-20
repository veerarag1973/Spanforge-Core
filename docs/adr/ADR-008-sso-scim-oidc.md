# ADR-008: SSO Local-First — SAML 2.0, SCIM 2.0, OIDC, Session Delegation

| Field | Value |
|-------|-------|
| **Status** | Accepted |
| **Date** | 2025-01-01 |
| **Authors** | SpanForge Core Team |
| **Closes** | ID-040, ID-041, ID-042, ID-043 |

---

## Context

SpanForge Phase 13 (v2.0.13) introduces enterprise SSO capabilities required
by large organisations deploying SpanForge behind an Identity Provider (IdP).
The primary requirements are:

1. **SAML 2.0** — Allow IdPs (Okta, Azure AD, ADFS) to authenticate users
   against SpanForge via an SP-initiated or IdP-initiated flow.
2. **SCIM 2.0** — Allow IdPs to provision and deprovision SpanForge users and
   groups automatically, without manual admin intervention.
3. **OIDC (PKCE)** — Allow modern IdPs and social login providers to authenticate
   users via OAuth 2.0 / OpenID Connect with the Proof Key for Code Exchange
   extension (no client secret exposed to the browser).
4. **SSO Session Delegation** — Tie SpanForge internal sessions to the lifecycle
   of the originating IdP session, enabling back-channel logout and session
   revocation without requiring users to log in again.

### Constraints

- SpanForge uses a **local-first architecture** (ADR-004): all state must be
  usable without an external service.
- The SSO layer must operate with **zero external network calls** in its
  local/sandbox mode.
- SCIM and OIDC must conform to RFC 7643 / RFC 7644 and RFC 8252 respectively.
- No third-party SSO libraries should be required at the `spanforge` core
  package level — only standard-library / already-vendored dependencies.

---

## Decision

Implement the full SSO suite **inside `SFIdentityClient`** using a
local-first in-memory store, keeping the same architectural pattern as other
Phase services (`SFAuditClient`, `SFCECClient`, etc.).

### Protocol implementations

| Protocol | Implementation strategy |
|----------|------------------------|
| **SAML 2.0 SP** | Stub SP metadata XML generated from configurable env vars; ACS validates base64 SAMLResponse and issues a SpanForge session JWT. |
| **SCIM 2.0** | RFC 7643/7644-compliant in-memory user and group store; supports `list`, `create`, `get`, `patch`, `delete` for Users and `list`, `create`, `delete` for Groups. |
| **OIDC PKCE RP** | Pure-Python PKCE `code_challenge` generation (`S256`); `oidc_authorize()` builds the redirect URL; `oidc_callback()` validates state and issues a SpanForge session JWT. |
| **Session Delegation** | `sso_delegate_session()` creates an `SSOSession` keyed by `idp_session_id`; `sso_revoke_idp_session()` soft-deletes all sessions for a given IdP session, enabling SAML back-channel logout and OIDC front-channel logout. |

### Session JWT

SpanForge issues a short-lived (default 8 h) JWT after successful SAML ACS,
OIDC callback, or session delegation.  The JWT is signed with
`SPANFORGE_SIGNING_KEY` (already required for audit chain integrity) — no
additional key material is needed.

### Storage

All state (users, groups, sessions) is stored in per-instance `dict` objects
protected by `threading.Lock()`, consistent with the in-memory approach
established in ADR-004 for Phase 2–12 services.  A future BYOS adapter
(equivalent to `SPANFORGE_AUDIT_BYOS_PROVIDER`) may persist sessions to
Redis or a relational database without API surface changes.

---

## Consequences

### Positive

- Zero-dependency implementation; works offline and in CI with no IdP
  connection.
- Consistent architecture with all existing Phase services.
- SCIM endpoints can be registered with any RFC 7644-compliant IdP
  provisioner (Okta, Azure AD, OneLogin) by pointing the IdP at
  `SPANFORGE_SCIM_BASE_URL`.
- `sso_revoke_idp_session()` enables true back-channel logout — IdPs can
  revoke SpanForge sessions server-side without browser involvement.

### Negative / Trade-offs

- **In-memory only (v2.0.13):** Sessions and SCIM users are lost on process
  restart.  Teams running multiple replicas must implement sticky sessions or
  wait for the BYOS session backend (planned for v2.1.x).
- **Stub SAML validation:** The ACS implementation decodes the SAMLResponse
  but does not cryptographically verify the IdP signature in the local-first
  mode.  Full signature validation requires `SPANFORGE_SAML_IDP_METADATA_URL`
  and a future `xmlsec1`-based verifier.
- **No refresh token rotation:** OIDC callback issues a session JWT but does
  not implement refresh token rotation.  Long-lived sessions require periodic
  re-authentication.

---

## Alternatives Considered

### A. Use `python3-saml` / `pysaml2`

**Rejected.** Introduces C-extension dependencies (`lxml`, `xmlsec1`) that
conflict with the zero-dependency goal (ADR-004) and are problematic in
constrained deployment environments (Lambda, air-gapped).

### B. Delegate SSO entirely to a reverse proxy (e.g. Nginx + auth_request)

**Rejected.** Requires infrastructure changes that SpanForge Core cannot
control.  The SDK's local-first principle means self-hosted deployments must
function without a sidecar.

### C. Integrate with an existing identity platform (Keycloak, Auth0)

**Rejected for Phase 13.** Creates a hard dependency on a third-party service,
violating ADR-004.  The session delegation pattern (`sso_delegate_session()`)
is designed to *wrap* any upstream IdP session, so Keycloak/Auth0 can be used
as the upstream IdP without SpanForge depending on it directly.

---

## Related

- [ADR-004 — Local-First Architecture](ADR-004-local-first-architecture.md)
- [ADR-002 — Singleton Service Clients](ADR-002-singleton-service-clients.md)
- [identity API reference](../api/identity.md)
- [Identity service settings](../configuration.md#identity-service-settings-phase-13)
- [SSO Session Management runbook](../runbook.md#16-sso-session-management-phase-13--20130)
