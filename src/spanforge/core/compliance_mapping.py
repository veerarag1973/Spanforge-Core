"""spanforge.core.compliance_mapping — Compliance evidence engine.

Maps spanforge telemetry events to regulatory framework clauses and produces
signed attestation packages suitable for audit submission.

Supported frameworks
--------------------
* soc2         — SOC 2 Type II (CC series)
* hipaa        — HIPAA Security Rule
* gdpr         — GDPR (EU) 2016/679
* nist_ai_rmf  — NIST AI Risk Management Framework 1.0
* eu_ai_act    — EU AI Act (Annex IV documentation requirements)
* iso_42001    — ISO/IEC 42001:2023 AI Management System
"""

from __future__ import annotations

import enum
import hashlib
import hmac as _hmac
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

__all__ = [
    "ClauseStatus",
    "ComplianceAttestation",
    "ComplianceEvidencePackage",
    "ComplianceFramework",
    "ComplianceMappingEngine",
    "EvidenceRecord",
    "GapReport",
    "verify_attestation_signature",
    "verify_pdf_attestation",
]

_log = logging.getLogger("spanforge.core.compliance_mapping")

# Fallback signing key used when SPANFORGE_SIGNING_KEY is absent.  Only
# safe for development / CI — never use in production.
_INSECURE_DEFAULT_KEY: str = "spanforge-insecure-default-do-not-use-in-production"

# ---------------------------------------------------------------------------
# Framework enum
# ---------------------------------------------------------------------------


class ComplianceFramework(enum.Enum):
    """Supported regulatory frameworks."""

    SOC2 = "SOC 2 Type II"
    HIPAA = "HIPAA"
    GDPR = "GDPR"
    NIST_AI_RMF = "NIST AI RMF"
    EU_AI_ACT = "EU AI Act"
    ISO_42001 = "ISO/IEC 42001"


# Maps enum value strings and slug strings to _FRAMEWORK_CLAUSES keys
_FRAMEWORK_KEY_MAP: dict[str, str] = {
    # enum values
    "soc 2 type ii": "soc2",
    "hipaa": "hipaa",
    "gdpr": "gdpr",
    "nist ai rmf": "nist_ai_rmf",
    "eu ai act": "eu_ai_act",
    "iso/iec 42001": "iso_42001",
    # slugs (already match keys, but listed for completeness)
    "soc2": "soc2",
    "nist_ai_rmf": "nist_ai_rmf",
    "eu_ai_act": "eu_ai_act",
    "iso_42001": "iso_42001",
}


# ---------------------------------------------------------------------------
# Framework → clause definitions
# ---------------------------------------------------------------------------

# Each clause maps to a list of event-type prefixes that provide evidence.
_FRAMEWORK_CLAUSES: dict[str, dict[str, dict[str, Any]]] = {
    "soc2": {
        "CC6.1": {
            "title": "Logical and Physical Access Controls — access management",
            "event_prefixes": ["llm.audit.", "llm.trace.", "model_registry."],
            "description": "Events demonstrating actor-based access controls, audit trails, and model lifecycle tracking.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
        "CC6.6": {
            "title": "PII / Sensitive Data Protection",
            "event_prefixes": ["llm.redact."],
            "description": "Evidence of PII detection and redaction before model transmission.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
        "CC7.2": {
            "title": "Anomaly and Threat Detection",
            "event_prefixes": ["llm.drift.", "llm.guard."],
            "description": "Drift detection and guard-rail events demonstrating anomaly monitoring.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
        "CC8.1": {
            "title": "Change Management — schema validation",
            "event_prefixes": ["llm.trace.", "llm.eval."],
            "description": "Schema-validated telemetry providing a tamper-evident event chain.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
        "CC9.2": {
            "title": "Risk Mitigation — cost and budget controls",
            "event_prefixes": ["llm.cost."],
            "description": "Cost budget and spend telemetry supporting financial risk controls.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
    },
    "hipaa": {
        "164.312(b)": {
            "title": "Audit Controls",
            "event_prefixes": ["llm.audit.", "llm.trace."],
            "description": "HMAC-signed event chain providing tamper-evident audit record of PHI activity.",
            "min_event_count": 10,
            "time_window_hours": None,
        },
        "164.312(a)(1)": {
            "title": "Access Control",
            "event_prefixes": ["llm.trace.", "llm.audit."],
            "description": "Actor-tagged events demonstrating user/system access to PHI workloads.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
        "164.312(e)(2)(ii)": {
            "title": "Encryption and Decryption",
            "event_prefixes": ["llm.redact."],
            "description": "PII redaction events demonstrating PHI de-identification before model use.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
        "164.530(j)": {
            "title": "Documentation and Retention",
            "event_prefixes": ["llm.trace.", "llm.audit.", "llm.cost."],
            "description": "Complete event log supporting required 6-year audit retention.",
            "min_event_count": 10,
            "time_window_hours": 168,
        },
    },
    "gdpr": {
        "Art.30": {
            "title": "Records of Processing Activities",
            "event_prefixes": ["llm.trace.", "llm.cost.", "llm.audit."],
            "description": "Structured event log mapping to Article 30 processing record requirements.",
            "min_event_count": 10,
            "time_window_hours": None,
        },
        "Art.35": {
            "title": "Data Protection Impact Assessment",
            "event_prefixes": ["llm.redact.", "llm.guard.", "llm.drift."],
            "description": "Redaction, guard-rail, and drift events supporting DPIA risk evidence.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
        "Art.22": {
            "title": "Automated Individual Decision-Making — consent and oversight",
            "event_prefixes": ["consent.", "hitl."],
            "description": "Consent boundary and human-in-the-loop events demonstrating safeguards for automated decisions affecting individuals.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
        "Art.25": {
            "title": "Data Protection by Design and by Default",
            "event_prefixes": ["llm.redact.", "consent."],
            "description": "PII stripping and consent enforcement at instrumentation level demonstrates privacy-by-design.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
    },
    "nist_ai_rmf": {
        "MAP.1.1": {
            "title": "AI System Documentation",
            "event_prefixes": ["llm.trace.", "llm.eval.", "model_registry.", "explanation."],
            "description": "Trace, evaluation, model registry, and explainability events documenting AI system behaviour.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
        "MEASURE.2.6": {
            "title": "AI Risk Monitoring",
            "event_prefixes": ["llm.drift.", "llm.guard.", "llm.eval."],
            "description": "Drift and guard events demonstrating continuous risk monitoring.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
        "MANAGE.3.2": {
            "title": "Incident Response",
            "event_prefixes": ["llm.guard.", "llm.audit."],
            "description": "Guard and audit events providing evidence of incident detection and response.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
        "GOVERN.1.7": {
            "title": "AI Policies and Processes",
            "event_prefixes": ["llm.audit.", "llm.trace."],
            "description": "Audit chain demonstrating policy enforcement in AI pipelines.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
    },
    "eu_ai_act": {
        "AnnexIV.1": {
            "title": "General Description of the AI System",
            "event_prefixes": ["llm.trace.", "llm.eval."],
            "description": "Trace and evaluation telemetry documenting system purpose and behaviour.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
        "Art.13": {
            "title": "Transparency — explainability of AI decisions",
            "event_prefixes": ["explanation."],
            "description": "Explainability records demonstrating that high-risk AI decisions are accompanied by human-readable rationale.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
        "Art.14": {
            "title": "Human Oversight — HITL review and escalation",
            "event_prefixes": ["hitl.", "consent."],
            "description": "Human-in-the-loop review, escalation, and consent events demonstrating mandatory human oversight of high-risk AI.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
        "AnnexIV.5": {
            "title": "Human Oversight Measures",
            "event_prefixes": ["llm.guard.", "llm.audit.", "hitl."],
            "description": "Guard, audit, and human-in-the-loop events demonstrating human oversight mechanisms.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
        "AnnexIV.6": {
            "title": "Robustness, Accuracy and Cybersecurity",
            "event_prefixes": ["llm.eval.", "llm.drift."],
            "description": "Evaluation and drift telemetry supporting robustness and accuracy evidence.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
    },
    "iso_42001": {
        "6.1": {
            "title": "Actions to Address AI Risks and Opportunities",
            "event_prefixes": ["llm.drift.", "llm.guard.", "llm.eval."],
            "description": "Drift, guard, and evaluation events supporting risk treatment records.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
        "9.1": {
            "title": "Monitoring, Measurement, Analysis and Evaluation",
            "event_prefixes": ["llm.trace.", "llm.eval.", "llm.cost."],
            "description": "Continuous telemetry supporting measurement and evaluation requirements.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
        "10.1": {
            "title": "Nonconformity and Corrective Action",
            "event_prefixes": ["llm.audit.", "llm.guard."],
            "description": "Audit and guard events documenting corrective actions.",
            "min_event_count": 5,
            "time_window_hours": None,
        },
    },
}

# Minimum event count to consider a clause "passed" (not just partial)
_MIN_PASS_THRESHOLD = 5


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class ClauseStatus(enum.Enum):
    """Pass/fail/coverage status for a single compliance clause."""

    PASS = "pass"
    FAIL = "fail"
    PARTIAL = "partial"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


@dataclass
class EvidenceRecord:
    """Evidence collected for one framework clause."""

    clause_id: str
    status: ClauseStatus
    evidence_count: int
    audit_ids: list[str]
    summary: str


@dataclass
class ComplianceAttestation:
    """HMAC-signed attestation package for a model + framework + period."""

    model_id: str
    framework: str
    period_from: str
    period_to: str
    generated_at: str
    generated_by: str
    clauses: list[EvidenceRecord]
    overall_status: ClauseStatus
    hmac_sig: str
    model_owner: str | None = None
    model_risk_tier: str | None = None
    model_status: str | None = None
    model_warnings: list[str] = field(default_factory=list)
    explanation_coverage_pct: float | None = None

    def to_json(self) -> str:
        """Return the attestation as a compact JSON string."""
        doc: dict[str, Any] = {
            "model_id": self.model_id,
            "framework": self.framework,
            "period_from": self.period_from,
            "period_to": self.period_to,
            "generated_at": self.generated_at,
            "generated_by": self.generated_by,
            "overall_status": self.overall_status.value,
            "hmac_sig": self.hmac_sig,
            "clauses": [
                {
                    "clause_id": r.clause_id,
                    "status": r.status.value,
                    "evidence_count": r.evidence_count,
                    "audit_ids": r.audit_ids[:20],  # cap for readability
                    "summary": r.summary,
                }
                for r in self.clauses
            ],
        }
        if self.model_owner is not None:
            doc["model_owner"] = self.model_owner
        if self.model_risk_tier is not None:
            doc["model_risk_tier"] = self.model_risk_tier
        if self.model_status is not None:
            doc["model_status"] = self.model_status
        if self.model_warnings:
            doc["model_warnings"] = self.model_warnings
        if self.explanation_coverage_pct is not None:
            doc["explanation_coverage_pct"] = self.explanation_coverage_pct
        return json.dumps(doc, indent=2)


@dataclass
class GapReport:
    """Summary of compliance gaps found during the analysis."""

    model_id: str
    framework: str
    period_from: str
    period_to: str
    generated_at: str
    gap_clause_ids: list[str]
    partial_clause_ids: list[str]

    @property
    def has_gaps(self) -> bool:
        """Return True if any gap clause IDs exist."""
        return bool(self.gap_clause_ids)

    @property
    def total_issues(self) -> int:
        """Return total number of gap and partial clause issues."""
        return len(self.gap_clause_ids) + len(self.partial_clause_ids)


@dataclass
class ComplianceEvidencePackage:
    """Full deliverable: attestation + human-readable report + gap analysis + audit exports."""

    attestation: ComplianceAttestation
    report_text: str
    gap_report: GapReport
    audit_exports: dict[str, list[dict[str, Any]]] = field(default_factory=dict)

    def to_json(self) -> str:
        """Return a signed JSON attestation with HMAC covering canonical bytes.

        The output includes: framework, model_id, period, generated_at,
        clauses with status/evidence_count/summary, gap_clause_ids,
        overall_status, and hmac_sig.
        """
        att = self.attestation
        doc: dict[str, Any] = {
            "framework": att.framework,
            "model_id": att.model_id,
            "period_from": att.period_from,
            "period_to": att.period_to,
            "generated_at": att.generated_at,
            "generated_by": att.generated_by,
            "overall_status": att.overall_status.value,
            "clauses": [
                {
                    "clause_id": r.clause_id,
                    "status": r.status.value,
                    "evidence_count": r.evidence_count,
                    "summary": r.summary,
                }
                for r in att.clauses
            ],
            "gap_clause_ids": self.gap_report.gap_clause_ids,
            "hmac_sig": att.hmac_sig,
        }
        if att.model_owner is not None:
            doc["model_owner"] = att.model_owner
        if att.model_risk_tier is not None:
            doc["model_risk_tier"] = att.model_risk_tier
        if att.model_status is not None:
            doc["model_status"] = att.model_status
        if att.model_warnings:
            doc["model_warnings"] = att.model_warnings
        if att.explanation_coverage_pct is not None:
            doc["explanation_coverage_pct"] = att.explanation_coverage_pct
        return json.dumps(doc, sort_keys=True, separators=(",", ":"))

    def to_pdf(self, path: str | Any) -> Any:
        """Generate a signed PDF attestation report.

        Requires ``reportlab``: ``pip install 'spanforge[compliance]'``.

        Args:
            path: File path for the output PDF.

        Returns:
            :class:`pathlib.Path` to the written PDF file.

        Raises:
            ImportError: If ``reportlab`` is not installed.
        """
        from pathlib import Path as _Path

        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.units import mm
            from reportlab.pdfgen import canvas
        except ImportError:
            raise ImportError(
                "PDF attestation export requires reportlab. "
                "Install it with: pip install 'spanforge[compliance]'"
            ) from None

        out_path = _Path(path)
        att = self.attestation

        c = canvas.Canvas(str(out_path), pagesize=A4)
        width, height = A4
        y = height - 40 * mm

        # Cover page
        c.setFont("Helvetica-Bold", 18)
        c.drawString(30 * mm, y, "SpanForge Compliance Attestation")
        y -= 12 * mm
        c.setFont("Helvetica", 11)
        c.drawString(30 * mm, y, f"Framework: {att.framework.upper()}")
        y -= 7 * mm
        c.drawString(30 * mm, y, f"Model: {att.model_id}")
        y -= 7 * mm
        c.drawString(30 * mm, y, f"Period: {att.period_from} — {att.period_to}")
        y -= 7 * mm
        c.drawString(30 * mm, y, f"Generated: {att.generated_at}")
        y -= 7 * mm
        c.drawString(30 * mm, y, f"Overall Status: {att.overall_status.value.upper()}")
        y -= 14 * mm

        # Clause table
        c.setFont("Helvetica-Bold", 12)
        c.drawString(30 * mm, y, "Clause Analysis")
        y -= 8 * mm
        c.setFont("Helvetica", 9)
        for rec in att.clauses:
            if y < 30 * mm:
                c.showPage()
                y = height - 30 * mm
                c.setFont("Helvetica", 9)
            icon = {"pass": "PASS", "fail": "FAIL", "partial": "PARTIAL"}.get(rec.status.value, "?")
            c.drawString(30 * mm, y, f"[{icon}] {rec.clause_id}: {rec.summary[:80]}")
            y -= 5 * mm

        # Gap list
        if self.gap_report.has_gaps:
            y -= 6 * mm
            c.setFont("Helvetica-Bold", 11)
            c.drawString(30 * mm, y, "Gaps Requiring Action")
            y -= 6 * mm
            c.setFont("Helvetica", 9)
            for cid in self.gap_report.gap_clause_ids:
                c.drawString(32 * mm, y, f"- {cid}")
                y -= 5 * mm

        # HMAC footer
        y -= 10 * mm
        c.setFont("Helvetica", 8)
        c.drawString(30 * mm, y, f"HMAC-SHA256: {att.hmac_sig}")

        c.save()

        # Sign the PDF bytes and store in metadata
        pdf_bytes = out_path.read_bytes()
        pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
        signing_key = os.environ.get("SPANFORGE_SIGNING_KEY", "")
        if not signing_key or signing_key == "spanforge-default":
            _log.warning(
                "SPANFORGE_SIGNING_KEY is not set or uses the insecure default value. "
                "Set a strong secret before generating PDF attestations for production. "
                "Example: export SPANFORGE_SIGNING_KEY=$(openssl rand -hex 32)"
            )
            signing_key = _INSECURE_DEFAULT_KEY
        pdf_hmac = _hmac.new(
            signing_key.encode(),
            pdf_hash.encode(),
            hashlib.sha256,
        ).hexdigest()

        # Re-open and set metadata
        # Store the HMAC as a sidecar JSON (reportlab doesn't support PDF metadata update easily)
        sidecar = out_path.with_suffix(".pdf.sig")
        sidecar.write_text(
            json.dumps({"SpanForgeHMAC": pdf_hmac, "pdf_sha256": pdf_hash}),
            encoding="utf-8",
        )

        return out_path


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class ComplianceMappingEngine:
    """Map spanforge telemetry events to framework clauses and generate evidence packages."""

    def generate_evidence_package(
        self,
        model_id: str,
        framework: str,
        from_date: str,
        to_date: str,
        audit_events: list[dict[str, Any]] | None = None,
    ) -> ComplianceEvidencePackage:
        """Analyse *audit_events* and produce a full compliance evidence package.

        Parameters
        ----------
        model_id:
            The AI model identifier (e.g. ``gpt-4o``).
        framework:
            One of ``soc2``, ``hipaa``, ``gdpr``, ``nist_ai_rmf``,
            ``eu_ai_act``, ``iso_42001``.
        from_date / to_date:
            ISO-8601 date strings defining the audit period.
        audit_events:
            Raw event dicts.  If *None* or empty the engine will load from the
            active ``TraceStore`` instead.
        """
        # ------------------------------------------------------------------
        # Resolve framework
        # ------------------------------------------------------------------
        if isinstance(framework, ComplianceFramework):
            raw = framework.value.lower()
        else:
            raw = str(framework).lower().replace("-", "_").replace(" ", "_")

        framework_key = _FRAMEWORK_KEY_MAP.get(raw, raw)
        if framework_key not in _FRAMEWORK_CLAUSES:
            supported = ", ".join(sorted(_FRAMEWORK_CLAUSES))
            raise ValueError(f"Unknown framework {framework!r}. Supported: {supported}")

        # ------------------------------------------------------------------
        # Load events
        # ------------------------------------------------------------------
        if not audit_events:
            audit_events = self._load_from_store()

        # ------------------------------------------------------------------
        # Filter to period
        # ------------------------------------------------------------------
        period_events = self._filter_period(audit_events, from_date, to_date)

        # ------------------------------------------------------------------
        # Map events to clauses
        # ------------------------------------------------------------------
        clauses_def = _FRAMEWORK_CLAUSES[framework_key]
        evidence_records: list[EvidenceRecord] = []
        audit_exports: dict[str, list[dict[str, Any]]] = {}

        _now_utc = datetime.now(timezone.utc)

        for clause_id, clause_info in clauses_def.items():
            prefixes: list[str] = clause_info["event_prefixes"]
            # Per-clause minimum, falling back to global default
            clause_min: int = clause_info.get("min_event_count") or _MIN_PASS_THRESHOLD
            # Optional rolling time window (hours) scoped to this clause
            tw_hours: int | None = clause_info.get("time_window_hours")

            matching = [
                e
                for e in period_events
                if any(str(e.get("event_type", "")).startswith(p) for p in prefixes)
            ]

            # Apply clause-level time window filter when defined
            if tw_hours is not None:
                _tw_cutoff = _now_utc - timedelta(hours=tw_hours)
                _cutoff_iso = _tw_cutoff.isoformat()
                matching = [e for e in matching if str(e.get("timestamp", "")) >= _cutoff_iso]

            model_matching = [e for e in matching if self._event_matches_model(e, model_id)]
            # When a model_id is given, restrict to model-specific events only.
            # Fall back to all matching events only when no model_id is specified.
            effective = model_matching if model_id else matching

            audit_ids = [str(e.get("event_id", "")) for e in effective[:50]]
            count = len(effective)
            audit_exports[clause_id] = [
                {k: v for k, v in e.items() if k != "signature"} for e in effective[:100]
            ]

            if count >= clause_min:
                status = ClauseStatus.PASS
                summary = f"{count} events from prefixes {prefixes} satisfy this clause."
            elif count > 0:
                status = ClauseStatus.PARTIAL
                summary = (
                    f"Only {count} events found (need ≥{clause_min}). "
                    f"Increase instrumentation coverage."
                )
            else:
                status = ClauseStatus.FAIL
                summary = (
                    f"No events found matching {prefixes}. "
                    f"Add {framework_key.upper()} instrumentation for this clause."
                )

            evidence_records.append(
                EvidenceRecord(
                    clause_id=clause_id,
                    status=status,
                    evidence_count=count,
                    audit_ids=audit_ids,
                    summary=summary,
                )
            )

        # ------------------------------------------------------------------
        # Overall status
        # ------------------------------------------------------------------
        statuses = [r.status for r in evidence_records]
        if all(s == ClauseStatus.PASS for s in statuses):
            overall = ClauseStatus.PASS
        elif any(s == ClauseStatus.FAIL for s in statuses):
            overall = ClauseStatus.FAIL
        else:
            overall = ClauseStatus.PARTIAL

        # ------------------------------------------------------------------
        # HMAC signature
        # ------------------------------------------------------------------
        generated_at = datetime.now(timezone.utc).isoformat()
        sig_payload = json.dumps(
            {
                "model_id": model_id,
                "framework": framework_key,
                "from": from_date,
                "to": to_date,
                "generated_at": generated_at,
                "clauses": {r.clause_id: r.status.value for r in evidence_records},
                "event_count": len(period_events),
            },
            sort_keys=True,
        )
        signing_key = os.environ.get("SPANFORGE_SIGNING_KEY", "")
        if not signing_key or signing_key == "spanforge-default":
            _log.warning(
                "SPANFORGE_SIGNING_KEY is not set or uses the insecure default value. "
                "Set a strong secret before generating compliance attestations for production. "
                "Example: export SPANFORGE_SIGNING_KEY=$(openssl rand -hex 32)"
            )
            signing_key = _INSECURE_DEFAULT_KEY
        hmac_sig = _hmac.new(
            signing_key.encode(),
            sig_payload.encode(),
            hashlib.sha256,
        ).hexdigest()

        attestation = ComplianceAttestation(
            model_id=model_id,
            framework=framework_key,
            period_from=from_date,
            period_to=to_date,
            generated_at=generated_at,
            generated_by="spanforge.core.compliance_mapping v1",
            clauses=evidence_records,
            overall_status=overall,
            hmac_sig=hmac_sig,
        )

        # ------------------------------------------------------------------
        # Model registry enrichment (Fix 3)
        # ------------------------------------------------------------------
        self._enrich_from_model_registry(attestation, model_id)

        # ------------------------------------------------------------------
        # Explanation coverage metric (Fix 4)
        # ------------------------------------------------------------------
        self._compute_explanation_coverage(attestation, period_events, model_id)

        # ------------------------------------------------------------------
        # Gap report
        # ------------------------------------------------------------------
        gap_ids = [r.clause_id for r in evidence_records if r.status == ClauseStatus.FAIL]
        partial_ids = [r.clause_id for r in evidence_records if r.status == ClauseStatus.PARTIAL]
        gap_report = GapReport(
            model_id=model_id,
            framework=framework_key,
            period_from=from_date,
            period_to=to_date,
            generated_at=generated_at,
            gap_clause_ids=gap_ids,
            partial_clause_ids=partial_ids,
        )

        # ------------------------------------------------------------------
        # Human-readable report
        # ------------------------------------------------------------------
        report_text = self._build_report(attestation, gap_report, period_events, clauses_def)

        return ComplianceEvidencePackage(
            attestation=attestation,
            report_text=report_text,
            gap_report=gap_report,
            audit_exports=audit_exports,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _enrich_from_model_registry(attestation: ComplianceAttestation, model_id: str) -> None:
        """Enrich *attestation* with model registry metadata (owner, risk_tier, status)."""
        if not model_id:
            return
        try:
            from spanforge.model_registry import get_model

            entry = get_model(model_id)
            if entry is None:
                attestation.model_warnings.append(
                    f"Model {model_id!r} is not registered in the model registry. "
                    "Register it for full compliance traceability."
                )
                return

            attestation.model_owner = entry.owner
            attestation.model_risk_tier = entry.risk_tier
            attestation.model_status = entry.status

            if entry.status == "deprecated":
                attestation.model_warnings.append(
                    f"Model {model_id!r} is DEPRECATED in the registry. "
                    "Consider migrating to an active model before the next audit period."
                )
            elif entry.status == "retired":
                attestation.model_warnings.append(
                    f"Model {model_id!r} is RETIRED in the registry. "
                    "Generating a compliance attestation for a retired model is unusual — "
                    "verify this is intentional."
                )
        except Exception as _err:
            _log.debug("model registry lookup failed: %s", _err)

    def _compute_explanation_coverage(
        self,
        attestation: ComplianceAttestation,
        period_events: list[dict[str, Any]],
        model_id: str,
    ) -> None:
        """Compute explanation coverage: % of high-risk decisions with an explanation."""
        # Count decisions (trace spans) for this model in the period
        decision_events = [
            e
            for e in period_events
            if str(e.get("event_type", "")).startswith(("llm.trace.", "hitl."))
            and (
                not model_id
                or (e.get("payload") or {}).get("model", {}).get("name", "").lower()
                == model_id.lower()
                or (e.get("payload") or {}).get("model_id", "").lower() == model_id.lower()
                or str((e.get("payload") or {}).get("model", "")).lower() == model_id.lower()
            )
        ]
        explanation_events = [
            e for e in period_events if str(e.get("event_type", "")).startswith("explanation.")
        ]

        decision_count = len(decision_events)
        explanation_count = len(explanation_events)

        if decision_count > 0:
            attestation.explanation_coverage_pct = round(
                min(explanation_count / decision_count * 100, 100.0), 1
            )
        else:
            # No decisions → coverage is N/A; store None to omit from output
            attestation.explanation_coverage_pct = None

    def _load_from_store(self) -> list[dict[str, Any]]:
        """Load events from the active TraceStore."""
        try:
            from spanforge._store import get_store

            store = get_store()
            with store._lock:
                events = [e for evts in store._traces.values() for e in evts]
            return [
                {
                    "event_id": getattr(e, "event_id", None),
                    "event_type": getattr(e, "event_type", None),
                    "timestamp": getattr(e, "timestamp", None),
                    "source": getattr(e, "source", None),
                    "trace_id": getattr(e, "trace_id", None),
                    "span_id": getattr(e, "span_id", None),
                    "payload": getattr(e, "payload", {}),
                    "tags": getattr(e, "tags", {}),
                    "signature": getattr(e, "signature", None),
                }
                for e in events
            ]
        except Exception:
            return []

    @staticmethod
    def _filter_period(
        events: list[dict[str, Any]], from_date: str, to_date: str
    ) -> list[dict[str, Any]]:
        """Filter events to the requested date range (inclusive)."""

        def _parse(s: str) -> datetime | None:
            """Parse a date or datetime string to an aware UTC datetime."""
            try:
                dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            except ValueError:
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt

        from_dt = _parse(from_date)
        to_dt = _parse(to_date)
        if from_dt is None or to_dt is None:
            raise ValueError(
                f"Cannot parse date range: from_date={from_date!r}, to_date={to_date!r}. "
                "Use ISO-8601 format: YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ"
            )

        filtered = []
        for e in events:
            ts_raw = e.get("timestamp")
            if not ts_raw:
                continue
            ts = _parse(str(ts_raw))
            if ts is not None and from_dt <= ts <= to_dt:
                filtered.append(e)

        return filtered  # empty list is correct when no events fall in the period

    @staticmethod
    def _event_matches_model(event: dict[str, Any], model_id: str) -> bool:
        """Return True if event is associated with *model_id*."""
        if not model_id:
            return True
        payload = event.get("payload") or {}
        model_block = payload.get("model") or {}
        model_name = (
            model_block.get("name") or payload.get("model_id") or payload.get("model") or ""
        )
        return model_id.lower() == str(model_name).lower()

    @staticmethod
    def _build_report(
        att: ComplianceAttestation,
        gap: GapReport,
        events: list[dict[str, Any]],
        clauses_def: dict[str, Any],
    ) -> str:
        """Build a human-readable markdown-style compliance report."""
        lines = [
            "# spanforge Compliance Report",
            "",
            "| Field         | Value |",
            "|---------------|-------|",
            f"| Framework     | {att.framework.upper()} |",
            f"| Model         | {att.model_id} |",
            f"| Period        | {att.period_from} → {att.period_to} |",
            f"| Generated     | {att.generated_at} |",
            f"| Overall       | **{att.overall_status.value.upper()}** |",
            f"| Events in scope | {len(events)} |",
            f"| HMAC Sig      | `{att.hmac_sig[:32]}…` |",
        ]

        # Model registry metadata
        if att.model_owner is not None:
            lines.append(f"| Model Owner   | {att.model_owner} |")
        if att.model_risk_tier is not None:
            lines.append(f"| Risk Tier     | {att.model_risk_tier} |")
        if att.model_status is not None:
            lines.append(f"| Model Status  | {att.model_status} |")

        # Explanation coverage
        if att.explanation_coverage_pct is not None:
            lines.append(f"| Explanation Coverage | {att.explanation_coverage_pct}% |")

        lines.append("")

        # Model warnings
        if att.model_warnings:
            lines.append("## ⚠️ Model Registry Warnings")
            lines.append("")
            for w in att.model_warnings:
                lines.append(f"- {w}")
            lines.append("")

        lines.extend(
            [
                "## Clause Analysis",
                "",
            ]
        )
        for rec in att.clauses:
            info = clauses_def.get(rec.clause_id, {})
            icon = {"pass": "✅", "fail": "❌", "partial": "⚠️"}.get(rec.status.value, "❓")
            lines.append(f"### {icon} {rec.clause_id} — {info.get('title', rec.clause_id)}")
            lines.append("")
            lines.append(f"- **Status**: {rec.status.value.upper()}")
            lines.append(f"- **Evidence events**: {rec.evidence_count}")
            lines.append(f"- **Summary**: {rec.summary}")
            lines.append("")

        if gap.has_gaps:
            lines.append("## ❌ Gaps Requiring Action")
            lines.append("")
            for cid in gap.gap_clause_ids:
                info = clauses_def.get(cid, {})
                lines.append(
                    f"- **{cid}** — {info.get('title', cid)}: {info.get('description', '')}"
                )
            lines.append("")

        if gap.partial_clause_ids:
            lines.append("## ⚠️  Partial Coverage")
            lines.append("")
            for cid in gap.partial_clause_ids:
                info = clauses_def.get(cid, {})
                lines.append(f"- **{cid}** — {info.get('title', cid)}")
            lines.append("")

        lines.append("---")
        lines.append(
            "*Generated by spanforge.core.compliance_mapping. HMAC key: `SPANFORGE_SIGNING_KEY` env var.*"
        )
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Attestation verification
# ---------------------------------------------------------------------------


def verify_attestation_signature(attestation: ComplianceAttestation) -> bool:
    """Re-compute the HMAC and compare against the stored signature.

    Returns ``True`` if the attestation has not been tampered with.
    Note: verification requires the same ``SPANFORGE_SIGNING_KEY`` that was
    used during generation.
    """
    sig_payload = json.dumps(
        {
            "model_id": attestation.model_id,
            "framework": attestation.framework,
            "from": attestation.period_from,
            "to": attestation.period_to,
            "generated_at": attestation.generated_at,
            "clauses": {r.clause_id: r.status.value for r in attestation.clauses},
            "event_count": sum(r.evidence_count for r in attestation.clauses),
        },
        sort_keys=True,
    )
    signing_key = os.environ.get("SPANFORGE_SIGNING_KEY", "")
    if not signing_key or signing_key == "spanforge-default":
        _log.warning(
            "SPANFORGE_SIGNING_KEY is not set or uses the insecure default value. "
            "Attestation verification requires the same key used at signing time. "
            "Example: export SPANFORGE_SIGNING_KEY=<your-secret>"
        )
        signing_key = _INSECURE_DEFAULT_KEY
    expected = _hmac.new(
        signing_key.encode(),
        sig_payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return _hmac.compare_digest(attestation.hmac_sig, expected)


def verify_pdf_attestation(path: str | Any, org_secret: str | None = None) -> bool:
    """Verify that a PDF attestation has not been modified since signing.

    Reads the ``.pdf.sig`` sidecar file to obtain the original HMAC, then
    re-computes ``HMAC-SHA256(SHA256(pdf_bytes), org_secret)`` and compares.

    Args:
        path: Path to the PDF file.
        org_secret: HMAC signing key. If ``None``, reads from
            ``SPANFORGE_SIGNING_KEY`` env var.

    Returns:
        ``True`` if the PDF bytes have not been altered since signing.
    """
    from pathlib import Path as _Path

    pdf_path = _Path(path)
    sig_path = pdf_path.with_suffix(".pdf.sig")

    if not sig_path.exists():
        return False

    sig_data = json.loads(sig_path.read_text(encoding="utf-8"))
    stored_hmac = sig_data.get("SpanForgeHMAC", "")

    signing_key = org_secret or os.environ.get("SPANFORGE_SIGNING_KEY", "")
    if not signing_key or signing_key == "spanforge-default":
        raise ValueError(
            "SPANFORGE_SIGNING_KEY is not set or uses the insecure default value. "
            "PDF attestation verification requires the same key used at signing time. "
            "Example: export SPANFORGE_SIGNING_KEY=<your-secret>"
        )
    pdf_bytes = pdf_path.read_bytes()
    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
    expected_hmac = _hmac.new(
        signing_key.encode(),
        pdf_hash.encode(),
        hashlib.sha256,
    ).hexdigest()

    return _hmac.compare_digest(stored_hmac, expected_hmac)
