"""Compliance command group for the SpanForge CLI."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_FRAMEWORK_SLUG_MAP: dict[str, str] = {
    "eu_ai_act": "EU AI Act",
    "iso_42001": "ISO/IEC 42001",
    "nist_ai_rmf": "NIST AI RMF",
    "gdpr": "GDPR",
    "soc2": "SOC 2 Type II",
    "hipaa": "HIPAA",
}


def _resolve_framework(framework: str) -> tuple[str, Any]:
    """Resolve a CLI framework value to a ComplianceFramework enum."""
    from spanforge.core.compliance_mapping import ComplianceFramework

    fw_map = {member.value: member for member in ComplianceFramework}
    for slug, value in _FRAMEWORK_SLUG_MAP.items():
        if value in fw_map:
            fw_map[slug] = fw_map[value]

    framework_key = framework.lower()
    for key, fw_member in fw_map.items():
        if key.lower() == framework_key:
            return framework_key, fw_member

    valid = ", ".join(sorted(_FRAMEWORK_SLUG_MAP))
    print(f"error: unknown framework {framework!r}. Valid slugs: {valid}", file=sys.stderr)
    return framework_key, None


def _load_audit_events(events_file: str | None) -> tuple[int, list[dict[str, Any]] | None]:
    """Load audit events from an optional JSONL file."""
    if not events_file:
        return 0, None

    events_path = Path(events_file)
    if not events_path.exists():
        print(f"error: events file not found: {events_path}", file=sys.stderr)
        return 2, None

    audit_events: list[dict[str, Any]] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            audit_events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"warning: skipping invalid JSON line in events file: {exc}", file=sys.stderr)
    return 0, audit_events


def _attestation_from_dict(data: dict[str, Any]) -> object:
    """Reconstruct a ComplianceAttestation from its JSON form."""
    from spanforge.core.compliance_mapping import (
        ClauseStatus,
        ComplianceAttestation,
        EvidenceRecord,
    )

    period = data.get("period", {})
    clauses = [
        EvidenceRecord(
            clause_id=clause["clause_id"],
            status=ClauseStatus(clause["status"]),
            evidence_count=clause.get("evidence_count", 0),
            audit_ids=clause.get("audit_ids", []),
            summary=clause.get("summary", ""),
        )
        for clause in data.get("clauses", [])
    ]
    return ComplianceAttestation(
        model_id=data["model_id"],
        framework=data["framework"],
        period_from=period.get("from", data.get("period_from", "")),
        period_to=period.get("to", data.get("period_to", "")),
        generated_at=data.get("generated_at", ""),
        generated_by=data.get("generated_by", ""),
        clauses=clauses,
        overall_status=ClauseStatus(data["overall_status"]),
        hmac_sig=data.get("hmac_sig", ""),
    )


def cmd_generate(args: argparse.Namespace) -> int:
    """Implement ``spanforge compliance generate``."""
    from spanforge.core.compliance_mapping import ComplianceMappingEngine

    framework_key, framework = _resolve_framework(args.framework)
    if framework is None:
        return 2

    status, audit_events = _load_audit_events(getattr(args, "events_file", None))
    if status != 0:
        return status

    engine = ComplianceMappingEngine()
    try:
        package = engine.generate_evidence_package(
            model_id=args.model_id,
            framework=framework.value,
            from_date=args.from_date,
            to_date=args.to_date,
            audit_events=audit_events or None,
        )
    except Exception as exc:
        print(f"error: evidence package generation failed: {exc}", file=sys.stderr)
        return 1

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_id = args.model_id.replace("/", "_")[:40]
    prefix = f"{framework_key}_{safe_id}_{args.from_date}_{args.to_date}"

    attestation_path = out_dir / f"{prefix}_attestation.json"
    attestation_path.write_text(package.attestation.to_json(), encoding="utf-8")
    print(f"[✓] Attestation  → {attestation_path}")

    report_path = out_dir / f"{prefix}_report.txt"
    report_path.write_text(package.report_text, encoding="utf-8")
    print(f"[✓] Report       → {report_path}")

    if package.gap_report.has_gaps:
        gap_data = {
            "model_id": package.gap_report.model_id,
            "framework": package.gap_report.framework,
            "period_from": package.gap_report.period_from,
            "period_to": package.gap_report.period_to,
            "generated_at": package.gap_report.generated_at,
            "gap_clause_ids": package.gap_report.gap_clause_ids,
            "partial_clause_ids": package.gap_report.partial_clause_ids,
        }
        gap_path = out_dir / f"{prefix}_gap_report.json"
        gap_path.write_text(json.dumps(gap_data, indent=2), encoding="utf-8")
        print(f"[✓] Gap report   → {gap_path}")
    else:
        print("[✓] No compliance gaps found")

    if package.audit_exports:
        exports_dir = out_dir / "exports"
        exports_dir.mkdir(exist_ok=True)
        for clause_id, events in package.audit_exports.items():
            safe_clause = clause_id.replace("/", "_").replace(".", "_")
            clause_path = exports_dir / f"{safe_clause}.jsonl"
            clause_path.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")
        print(f"[✓] Clause exports → {exports_dir}/ ({len(package.audit_exports)} clause(s))")

    print(f"\nOverall status: {package.attestation.overall_status.value}")
    return 0


def cmd_validate_attestation(args: argparse.Namespace) -> int:
    """Implement ``spanforge compliance validate-attestation``."""
    from spanforge.compliance import verify_attestation_signature
    from spanforge.core.compliance_mapping import ComplianceAttestation

    attestation_path = Path(args.attestation_file)
    if not attestation_path.exists():
        print(f"error: file not found: {attestation_path}", file=sys.stderr)
        return 2

    try:
        data = json.loads(attestation_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in {attestation_path}: {exc}", file=sys.stderr)
        return 2

    try:
        attestation = _attestation_from_dict(data)
    except (KeyError, ValueError) as exc:
        print(f"error: could not parse attestation: {exc}", file=sys.stderr)
        return 2

    assert isinstance(attestation, ComplianceAttestation)  # nosec B101
    if verify_attestation_signature(attestation):
        print(f"[✓] Attestation signature is valid  model_id={data.get('model_id')!r}")
        return 0
    print(
        f"[✗] Attestation signature is INVALID  model_id={data.get('model_id')!r}",
        file=sys.stderr,
    )
    return 1


def cmd_report(args: argparse.Namespace) -> int:
    """Implement ``spanforge compliance report``."""
    from spanforge.core.compliance_mapping import ComplianceMappingEngine

    framework_key, framework = _resolve_framework(args.framework)
    if framework is None:
        return 2

    status, audit_events = _load_audit_events(getattr(args, "events_file", None))
    if status != 0:
        return status

    engine = ComplianceMappingEngine()
    try:
        package = engine.generate_evidence_package(
            model_id=args.model_id,
            framework=framework.value,
            from_date=args.from_date,
            to_date=args.to_date,
            audit_events=audit_events or None,
        )
    except Exception as exc:
        print(f"error: report generation failed: {exc}", file=sys.stderr)
        return 1

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_id = args.model_id.replace("/", "_")[:40]
    prefix = f"{framework_key}_{safe_id}_{args.from_date}_{args.to_date}"
    fmt = getattr(args, "report_format", "json")

    if fmt in ("json", "both"):
        json_path = out_dir / f"{prefix}_report.json"
        json_path.write_text(package.to_json(), encoding="utf-8")
        print(f"[✓] JSON report → {json_path}")

    if fmt in ("pdf", "both"):
        pdf_path = out_dir / f"{prefix}_report.pdf"
        try:
            package.to_pdf(str(pdf_path))
            print(f"[✓] PDF report  → {pdf_path}")
        except ImportError:
            print(
                "error: PDF generation requires reportlab. Install: pip install spanforge[compliance]",
                file=sys.stderr,
            )
            return 1

    overall = package.attestation.overall_status.value
    print(f"\nOverall status: {overall.upper()}")
    return 0 if overall == "pass" else 1


def cmd_check(args: argparse.Namespace) -> int:
    """Implement ``spanforge compliance check``."""
    from spanforge.core.compliance_mapping import ComplianceMappingEngine

    status, audit_events = _load_audit_events(getattr(args, "events_file", None))
    if status != 0:
        return status

    engine = ComplianceMappingEngine()
    try:
        package = engine.generate_evidence_package(
            model_id=args.model_id,
            framework=args.framework,
            from_date=args.from_date,
            to_date=args.to_date,
            audit_events=audit_events or None,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"error: compliance check failed: {exc}", file=sys.stderr)
        return 1

    allow_partial = getattr(args, "allow_partial", False)
    gap = package.gap_report
    overall = package.attestation.overall_status.value

    for record in package.attestation.clauses:
        icon = {"pass": "[✓]", "fail": "[✗]", "partial": "[~]"}.get(record.status.value, "[?]")  # nosec B105
        print(f"  {icon} {record.clause_id:<20} {record.status.value:<8}  {record.evidence_count} events")

    print(f"\nOverall: {overall.upper()}")

    if gap.gap_clause_ids:
        print(f"Gaps    : {', '.join(gap.gap_clause_ids)}")
    if gap.partial_clause_ids:
        print(f"Partial : {', '.join(gap.partial_clause_ids)}")

    if gap.has_gaps and (not allow_partial or gap.gap_clause_ids):
        print("\n[FAIL] Compliance check failed — fix gaps before deploying.", file=sys.stderr)
        return 1
    print("\n[PASS] Compliance check passed.")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Implement ``spanforge compliance status``."""
    from spanforge.redact import scan_payload
    from spanforge.signing import verify_chain

    events_path = Path(args.events_file)
    if not events_path.exists():
        print(f"error: events file not found: {events_path}", file=sys.stderr)
        return 2

    raw_events: list[dict[str, Any]] = []
    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            raw_events.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    if not raw_events:
        print("error: no events found in file", file=sys.stderr)
        return 1

    signing_key = os.environ.get("SPANFORGE_SIGNING_KEY", "")
    chain_ok = False
    chain_msg = "no signing key"
    if signing_key:
        try:
            chain_result = verify_chain(raw_events, signing_key)  # type: ignore[arg-type]
            chain_ok = chain_result.valid
            chain_msg = (
                "valid" if chain_result.valid else f"broken at event {chain_result.first_tampered}"
            )
        except Exception as exc:
            chain_msg = f"error: {exc}"

    pii_clean = True
    pii_hits = 0
    for event in raw_events:
        payload = event.get("payload", {})
        if isinstance(payload, dict):
            scan_result = scan_payload(payload)
            if not scan_result.clean:
                pii_clean = False
                pii_hits += len(scan_result.hits)

    clause_summary: dict[str, Any] = {}
    try:
        from spanforge.core.compliance_mapping import ComplianceMappingEngine

        engine = ComplianceMappingEngine()
        package = engine.generate_evidence_package(
            model_id="*",
            framework=args.framework,
            from_date="2000-01-01",
            to_date="2099-12-31",
            audit_events=raw_events,
        )
        for record in package.attestation.clauses:
            clause_summary[record.clause_id] = {
                "status": record.status.value,
                "evidence_count": record.evidence_count,
            }
    except Exception:
        clause_summary = {"error": "could not evaluate clause coverage"}

    last_attestation: str | None = None
    for event in reversed(raw_events):
        event_type = event.get("event_type", "")
        if "attestation" in event_type.lower() or "compliance" in event_type.lower():
            last_attestation = event.get("timestamp")
            break

    summary = {
        "chain_integrity": {"valid": chain_ok, "message": chain_msg},
        "pii_scan": {"clean": pii_clean, "hit_count": pii_hits},
        "clause_coverage": clause_summary,
        "last_attestation_timestamp": last_attestation,
        "events_analysed": len(raw_events),
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


def add_compliance_subcommands(subparsers: argparse._SubParsersAction[argparse.ArgumentParser]) -> argparse.ArgumentParser:
    """Register the compliance subcommands on the top-level parser."""
    compliance_parser = subparsers.add_parser(
        "compliance",
        help="Compliance evidence generation and attestation validation",
    )
    comp_sub = compliance_parser.add_subparsers(dest="compliance_command", metavar="<action>")

    gen_parser = comp_sub.add_parser(
        "generate",
        help="Generate a compliance evidence package for a model/framework/period",
    )
    gen_parser.add_argument("--model-id", dest="model_id", required=True, help="Model UUID")
    gen_parser.add_argument(
        "--framework",
        required=True,
        help="Compliance framework (eu_ai_act, gdpr, iso_42001, nist_ai_rmf, soc2)",
    )
    gen_parser.add_argument("--from", dest="from_date", required=True, metavar="DATE", help="Period start date (YYYY-MM-DD)")
    gen_parser.add_argument("--to", dest="to_date", required=True, metavar="DATE", help="Period end date (YYYY-MM-DD)")
    gen_parser.add_argument(
        "--output",
        default=".",
        metavar="DIR",
        help="Output directory for evidence files (default: .)",
    )
    gen_parser.add_argument(
        "--events-file",
        dest="events_file",
        metavar="JSONL",
        help="Optional JSONL file of audit events to include",
    )

    val_att_parser = comp_sub.add_parser(
        "validate-attestation",
        help="Verify the HMAC signature of a compliance attestation JSON file",
    )
    val_att_parser.add_argument(
        "attestation_file",
        metavar="ATTESTATION_JSON",
        help="Path to a compliance attestation JSON file",
    )

    report_parser = comp_sub.add_parser(
        "report",
        help="Generate a compliance report (JSON, PDF, or both) with HMAC attestation",
    )
    report_parser.add_argument("--model-id", dest="model_id", required=True, help="Model UUID")
    report_parser.add_argument(
        "--framework",
        required=True,
        help="Compliance framework (eu_ai_act, gdpr, hipaa, iso_42001, nist_ai_rmf, soc2)",
    )
    report_parser.add_argument("--from", dest="from_date", required=True, metavar="DATE", help="Period start date (YYYY-MM-DD)")
    report_parser.add_argument("--to", dest="to_date", required=True, metavar="DATE", help="Period end date (YYYY-MM-DD)")
    report_parser.add_argument(
        "--format",
        dest="report_format",
        default="json",
        choices=["json", "pdf", "both"],
        help="Output format: json, pdf, or both (default: json)",
    )
    report_parser.add_argument(
        "--output",
        default=".",
        metavar="DIR",
        help="Output directory (default: .)",
    )
    report_parser.add_argument(
        "--events-file",
        dest="events_file",
        metavar="JSONL",
        help="Optional JSONL file of audit events to include",
    )
    report_parser.add_argument(
        "--sign",
        action="store_true",
        default=False,
        help="Embed HMAC attestation signature in the output",
    )

    check_parser = comp_sub.add_parser(
        "check",
        help="CI-friendly compliance gate: exits 0 if all clauses pass, 1 if gaps exist",
    )
    check_parser.add_argument(
        "--model-id",
        dest="model_id",
        default="*",
        help="Model ID to check (default: * = all models)",
    )
    check_parser.add_argument(
        "--framework",
        required=True,
        help="Compliance framework (eu_ai_act, gdpr, hipaa, iso_42001, nist_ai_rmf, soc2)",
    )
    check_parser.add_argument("--from", dest="from_date", required=True, metavar="DATE", help="Period start date (YYYY-MM-DD)")
    check_parser.add_argument("--to", dest="to_date", required=True, metavar="DATE", help="Period end date (YYYY-MM-DD)")
    check_parser.add_argument(
        "--events-file",
        dest="events_file",
        metavar="JSONL",
        help="Optional JSONL file of audit events",
    )
    check_parser.add_argument(
        "--allow-partial",
        dest="allow_partial",
        action="store_true",
        help="Exit 0 on partial coverage (only fail on zero-evidence clauses)",
    )

    status_parser = comp_sub.add_parser(
        "status",
        help="Output a single JSON summary of compliance posture",
    )
    status_parser.add_argument(
        "--events-file",
        dest="events_file",
        required=True,
        metavar="JSONL",
        help="JSONL file of audit events to analyse",
    )
    status_parser.add_argument(
        "--framework",
        default="eu_ai_act",
        help="Compliance framework (default: eu_ai_act)",
    )

    return compliance_parser


def dispatch_compliance_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Dispatch the compliance command group."""
    action = getattr(args, "compliance_command", None)
    if action == "generate":
        return cmd_generate(args)
    if action == "validate-attestation":
        return cmd_validate_attestation(args)
    if action == "check":
        return cmd_check(args)
    if action == "report":
        return cmd_report(args)
    if action == "status":
        return cmd_status(args)
    parser.print_help()
    return 2
