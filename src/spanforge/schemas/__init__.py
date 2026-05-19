"""spanforge.schemas — Canonical schema key constants (DX-008).

Use these string constants everywhere you pass a ``schema_key`` argument
to :meth:`~spanforge.sdk.audit.SFAuditClient.append`,
:meth:`~spanforge.sdk.cec.SFCECClient.build_bundle`, or any other
SpanForge API that accepts a schema key.  They eliminate typos, enable
IDE auto-complete, and ensure your code stays in sync with schema
versioning changes.

Usage::

    from spanforge.schemas import TRACE_V1, AUDIT_V1, PII_V1

    sf_audit.append(record, schema_key=AUDIT_V1)
"""

from __future__ import annotations

__all__ = [
    "ALERT_V1",
    "AUDIT_V1",
    "BIAS_V1",
    "CONSENT_V1",
    "DRIFT_V1",
    "GATE_V1",
    "PII_V1",
    "PRRI_V1",
    "SCORE_V1",
    "SECRETS_V1",
    "TRACE_V1",
    "TRUST_V1",
]

# ---------------------------------------------------------------------------
# Core trace / telemetry
# ---------------------------------------------------------------------------

#: Schema key for OpenTelemetry-compatible LLM trace spans.
TRACE_V1: str = "spanforge.trace.v1"

# ---------------------------------------------------------------------------
# PII & secrets
# ---------------------------------------------------------------------------

#: Schema key for Presidio-backed PII scan and redaction records.
PII_V1: str = "spanforge.pii.v1"

#: Schema key for sf-secrets scanning records.
SECRETS_V1: str = "spanforge.secrets.v1"

# ---------------------------------------------------------------------------
# Audit chain
# ---------------------------------------------------------------------------

#: Schema key for general-purpose audit records written by sf-audit.
AUDIT_V1: str = "spanforge.audit.v1"

#: Schema key for DPDP / GDPR consent records (subject + purpose pairs).
CONSENT_V1: str = "spanforge.consent.v1"

# ---------------------------------------------------------------------------
# Compliance Evidence Chain (HallucCheck scoring artefacts)
# ---------------------------------------------------------------------------

#: Schema key for HallucCheck hallucination-score evidence records.
SCORE_V1: str = "halluccheck.score.v1"

#: Schema key for HallucCheck bias-scan evidence records.
BIAS_V1: str = "halluccheck.bias.v1"

#: Schema key for PRRI (Protected & Restricted Representation Index) records.
PRRI_V1: str = "halluccheck.prri.v1"

#: Schema key for behavioural-drift detection event records.
DRIFT_V1: str = "halluccheck.drift.v1"

# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

#: Schema key for CI/CD gate evaluation result records.
GATE_V1: str = "halluccheck.gate.v1"

# ---------------------------------------------------------------------------
# Trust
# ---------------------------------------------------------------------------

#: Schema key for trust-scorecard computation records.
TRUST_V1: str = "spanforge.trust.v1"

# ---------------------------------------------------------------------------
# Alerting
# ---------------------------------------------------------------------------

#: Schema key for sf-alert routed alert records.
ALERT_V1: str = "spanforge.alert.v1"
