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

---

# ADR-006: Topic-Based Alert Routing Design

**Status:** Accepted
**Date:** 2025-08-01
**Authors:** SpanForge Core Team

## Context

As SpanForge deployments grow, operators need to route alert notifications to
different channels based on alert content — e.g. PII violations go to a
security Slack channel, cost overruns go to a finance channel, and model drift
goes to the ML-ops channel.  A flat list of webhook URLs does not support
selective routing.

## Decision

Introduce **topics** as a first-class routing primitive in the Alert service:

1. Each alert carries an optional `topic: str` field (e.g. `"pii"`,
   `"cost"`, `"drift"`, `"trust"`).
2. `SFAlertClient.publish()` accepts `topic=` keyword argument.
3. Routing rules are expressed as a list of `TopicRoute` objects, each
   specifying `pattern` (glob or regex), `channel`, and `webhook_url`.
4. Rules are evaluated in declaration order; the **first matching rule** wins.
5. If no rule matches, the alert falls through to the default channel.
6. The server-side `/v1/alert/routes` endpoint allows runtime rule
   inspection (GET) and replacement (PUT) without restart.

Topic constants are defined in `spanforge.sdk._types.AlertTopic`:
```python
class AlertTopic(str, Enum):
    PII        = "pii"
    COST       = "cost"
    DRIFT      = "drift"
    TRUST      = "trust"
    GATE       = "gate"
    SECURITY   = "security"
    COMPLIANCE = "compliance"
    DEFAULT    = "default"
```

## Consequences

- **Positive:** Operators can target alerts without modifying application code.
- **Positive:** Topic constants reduce typo-driven misrouting.
- **Positive:** Runtime rule updates enable dynamic on-call routing.
- **Negative:** Rule ordering introduces ambiguity when patterns overlap —
  mitigated by `spanforge doctor --check-alert-routes` overlap detection.
- **Negative:** Adds a new runtime config surface that must be persisted and
  replicated across server instances.

---

# ADR-007: T.R.U.S.T. Dimension Design Rationale

**Status:** Accepted
**Date:** 2025-08-01
**Authors:** SpanForge Core Team

## Context

"Trust" in LLM outputs is a multidimensional property.  Early SpanForge
releases computed a single scalar trust score, which proved too coarse for
operators who needed to know *why* an output was flagged and *which* policy
dimension was violated.

## Decision

Replace the scalar trust score with the **T.R.U.S.T. framework** — five
orthogonal dimensions each scored 0.0–1.0:

| Dimension | Symbol | Measures |
|-----------|--------|----------|
| **T**ransparency  | T | Disclosure of model identity, limitations, and uncertainty |
| **R**eliability   | R | Factual accuracy, hallucination rate, citation quality |
| **U**ser-safety   | U | Absence of harmful, biased, or manipulative content |
| **S**ecurity      | S | Resistance to prompt injection, data leakage, jailbreaks |
| **T**raceability  | T | Auditability of reasoning steps and data provenance |

Implementation details:

1. `TrustScore` dataclass holds five `float` fields plus an aggregate
   `overall: float = mean(dimensions)`.
2. Individual dimension scorers are pluggable via `TrustScorerPlugin`
   protocol; built-in scorers cover common heuristics.
3. `sf_trust.evaluate()` returns `TrustScore`; each dimension can be
   individually overridden via `dimension_overrides=` keyword.
4. Trust scores are stored as a payload sub-object in `llm.trust.evaluated`
   events, enabling time-series trending via `sf_observe`.
5. A `TrustGate` rule type allows blocking on any single dimension threshold,
   e.g. `trust.reliability < 0.5 → block`.

## Consequences

- **Positive:** Dimensional scoring enables root-cause analysis of trust failures.
- **Positive:** Pluggable scorers allow domain-specific customisation.
- **Positive:** Backward-compatible — `overall` field replicates the old scalar.
- **Negative:** Five scores are harder to visualise than one — dashboard support
  required (addressed in Phase 14 dashboards).
- **Negative:** Individual scorer accuracy varies by domain; default scorers are
  conservative (prefer false-negatives over false-positives).

