"""Compliance command group for the SpanForge CLI."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

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


def cmd_validate_dataset(args: argparse.Namespace) -> int:
    """Implement ``spanforge compliance validate-dataset``."""
    from spanforge.sdk.dataset_scanner import scan_dataset_compliance

    dataset_path = Path(getattr(args, "dataset_path", None) or "")
    if not dataset_path or not dataset_path.exists():
        print(f"error: dataset path not found: {dataset_path}", file=sys.stderr)
        return 2

    output_fmt = getattr(args, "output_format", "report")
    sign = not getattr(args, "no_sign", False)

    try:
        report = scan_dataset_compliance(dataset_path, sign=sign)
    except Exception as exc:  # noqa: BLE001
        print(f"error: dataset scan failed: {exc}", file=sys.stderr)
        return 1

    if output_fmt == "json":
        print(report.to_json())
    elif output_fmt == "pdf":
        try:
            import reportlab  # type: ignore[import-untyped]  # noqa: F401

            if dataset_path.is_dir():
                pdf_path = dataset_path / "compliance_report.pdf"
            else:
                pdf_path = dataset_path.with_suffix(".compliance_report.pdf")
            from spanforge.sdk.dataset_scanner import _render_pdf  # type: ignore[attr-defined]
            _render_pdf(report, pdf_path)
            print(f"[✓] PDF report written to {pdf_path}")
            print(f"HMAC-SHA256: {report.hmac_signature}")
        except ImportError:
            print(
                "error: PDF output requires reportlab. "
                "Install: pip install spanforge[compliance]",
                file=sys.stderr,
            )
            return 1
    else:
        print(report.to_markdown())
        if report.hmac_signature:
            print(f"\nHMAC-SHA256: {report.hmac_signature}")

    all_passed = all(c.passed for c in report.eu_ai_act_article_10_clauses)
    if not all_passed:
        return 1
    return 0


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
        from spanforge.core.compliance_mapping import _FRAMEWORK_CLAUSES, _FRAMEWORK_KEY_MAP

        _fw_key = _FRAMEWORK_KEY_MAP.get(framework_key, framework_key)
        _clauses_def = _FRAMEWORK_CLAUSES.get(_fw_key, {})
        gap_data = {
            "model_id": package.gap_report.model_id,
            "framework": package.gap_report.framework,
            "period_from": package.gap_report.period_from,
            "period_to": package.gap_report.period_to,
            "generated_at": package.gap_report.generated_at,
            "gap_clause_ids": package.gap_report.gap_clause_ids,
            "partial_clause_ids": package.gap_report.partial_clause_ids,
            "remediation": {
                cid: _clauses_def.get(cid, {}).get("remediation_steps", "")
                for cid in package.gap_report.gap_clause_ids
            },
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


def _generate_compliance_html(package: Any) -> str:
    """Generate a self-contained HTML compliance report from an evidence package."""
    import html as _html

    att = package.attestation
    overall = att.overall_status.value
    overall_color = "#2ecc71" if overall == "pass" else "#e74c3c"
    gap_ids = set(package.gap_report.gap_clause_ids)

    status_colors = {
        "pass": "#2ecc71",
        "fail": "#e74c3c",
        "partial": "#f39c12",
        "n_a": "#95a5a6",
    }

    rows = []
    for clause in att.clauses:
        cid = _html.escape(clause.clause_id)
        st = clause.status.value
        color = status_colors.get(st, "#bdc3c7")
        gap_marker = " ⚠" if clause.clause_id in gap_ids else ""
        summary = _html.escape(clause.summary or "")
        rows.append(
            f"  <tr>"
            f"<td style='padding:6px 10px;border:1px solid #ddd'>{cid}</td>"
            f"<td style='padding:6px 10px;border:1px solid #ddd;color:{color};font-weight:bold'>"
            f"{st.upper()}{_html.escape(gap_marker)}</td>"
            f"<td style='padding:6px 10px;border:1px solid #ddd;text-align:center'>"
            f"{clause.evidence_count}</td>"
            f"<td style='padding:6px 10px;border:1px solid #ddd'>{summary}</td>"
            f"</tr>"
        )

    rows_html = "\n".join(rows)
    total = len(att.clauses)
    passed = sum(1 for c in att.clauses if c.status.value == "pass")
    gaps_count = len(gap_ids)
    framework_esc = _html.escape(att.framework)
    model_esc = _html.escape(att.model_id)
    period_esc = _html.escape(f"{att.period_from} to {att.period_to}")
    generated_esc = _html.escape(att.generated_at)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Compliance Report — {framework_esc}</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         margin: 0; padding: 20px 40px; background: #f8f9fa; color: #333; }}
  h1 {{ border-bottom: 3px solid #3498db; padding-bottom: 10px; color: #2c3e50; }}
  .meta {{ background: #fff; border-radius: 6px; padding: 16px 20px;
           box-shadow: 0 1px 4px rgba(0,0,0,.1); margin-bottom: 24px; }}
  .meta dt {{ font-weight: 600; color: #555; }}
  .meta dd {{ margin-left: 20px; margin-bottom: 6px; }}
  .overall {{ display: inline-block; padding: 6px 16px; border-radius: 4px;
              font-weight: bold; color: #fff; background: {overall_color}; font-size: 1.1em; }}
  .summary {{ display: flex; gap: 20px; margin-bottom: 24px; flex-wrap: wrap; }}
  .stat {{ background: #fff; border-radius: 6px; padding: 14px 20px;
           box-shadow: 0 1px 4px rgba(0,0,0,.1); text-align: center; min-width: 100px; }}
  .stat .num {{ font-size: 2em; font-weight: bold; color: #2c3e50; }}
  .stat .lbl {{ font-size: .85em; color: #777; }}
  table {{ border-collapse: collapse; width: 100%; background: #fff;
           border-radius: 6px; box-shadow: 0 1px 4px rgba(0,0,0,.1); overflow: hidden; }}
  th {{ background: #3498db; color: #fff; padding: 10px 10px; text-align: left; }}
  tr:nth-child(even) {{ background: #f9f9f9; }}
  tr:hover {{ background: #eaf4fd; }}
</style>
</head>
<body>
<h1>Compliance Report</h1>
<div class="meta">
  <dl>
    <dt>Framework</dt><dd>{framework_esc}</dd>
    <dt>Model ID</dt><dd>{model_esc}</dd>
    <dt>Period</dt><dd>{period_esc}</dd>
    <dt>Generated</dt><dd>{generated_esc}</dd>
    <dt>Overall Status</dt><dd><span class="overall">{overall.upper()}</span></dd>
  </dl>
</div>
<div class="summary">
  <div class="stat"><div class="num">{total}</div><div class="lbl">Total Clauses</div></div>
  <div class="stat"><div class="num" style="color:#2ecc71">{passed}</div><div class="lbl">Passed</div></div>
  <div class="stat"><div class="num" style="color:#e74c3c">{gaps_count}</div><div class="lbl">Gaps</div></div>
</div>
<h2>Clause Coverage</h2>
<table>
  <thead>
    <tr><th>Clause ID</th><th>Status</th><th>Evidence</th><th>Summary</th></tr>
  </thead>
  <tbody>
{rows_html}
  </tbody>
</table>
</body>
</html>"""


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

    if fmt in ("markdown", "both"):
        md_path = out_dir / f"{prefix}_report.md"
        md_path.write_text(package.to_markdown(), encoding="utf-8")
        print(f"[✓] Markdown report → {md_path}")

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

    if fmt == "html":
        html_path = out_dir / f"{prefix}_report.html"
        html_content = _generate_compliance_html(package)
        html_path.write_text(html_content, encoding="utf-8")
        print(f"[✓] HTML report → {html_path}")

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


def _build_readiness_checks(fw_slug: str) -> list[tuple[bool, str, str]]:  # noqa: PLR0915
    """Build the list of (passed, label, fix) tuples for *cmd_readiness*."""
    import os

    checks: list[tuple[bool, str, str]] = []

    # Check 1: signing key
    signing_key = os.environ.get("SPANFORGE_SIGNING_KEY", "")
    signing_ok = bool(signing_key) and signing_key not in {
        "spanforge-default",
        "spanforge-insecure-default-do-not-use-in-production",
    }
    checks.append((
        signing_ok,
        "SPANFORGE_SIGNING_KEY is set to a non-default value",
        "export SPANFORGE_SIGNING_KEY=$(openssl rand -hex 32)",
    ))

    # Check 2: durable exporter
    exporter_name = "unknown"
    durable = False
    try:
        from spanforge.config import get_config
        cfg = get_config()
        exporter_name = getattr(cfg, "exporter", "console") or "console"
        durable = exporter_name not in ("console", "")
    except Exception:  # nosec B110
        pass
    checks.append((
        durable,
        f"Durable exporter configured (current: {exporter_name!r})",
        "spanforge.configure(exporter='sqlite', endpoint='./spanforge.db')",
    ))

    # Check 3: PII redaction
    pii_on = False
    try:
        from spanforge.config import get_config
        cfg = get_config()
        pii_on = bool(getattr(cfg, "redact_pii", False))
    except Exception:  # nosec B110
        pass
    checks.append((
        pii_on,
        "PII redaction enabled (redact_pii=True)",
        "spanforge.configure(redact_pii=True)",
    ))

    # Framework-specific
    if fw_slug in ("eu_ai_act", "gdpr"):
        explain_available = False
        try:
            from spanforge.sdk import sf_explain  # noqa: F401
            explain_available = True
        except Exception:  # nosec B110
            pass
        checks.append((
            explain_available,
            "sf_explain module available",
            "pip install spanforge  # sf_explain is bundled",
        ))

    if fw_slug in ("eu_ai_act", "gdpr", "nist_ai_rmf"):
        drift_on = False
        try:
            from spanforge.config import get_config
            cfg = get_config()
            drift_on = bool(getattr(cfg, "drift_detection", False))
        except Exception:  # nosec B110
            pass
        checks.append((
            drift_on,
            "Drift detection enabled (drift_detection=True)",
            "spanforge.configure(drift_detection=True)",
        ))

    if fw_slug in ("eu_ai_act", "gdpr"):
        hitl_available = False
        try:
            from spanforge.sdk import sf_hitl  # type: ignore[attr-defined]  # noqa: F401
            hitl_available = True
        except Exception:  # nosec B110
            pass
        checks.append((
            hitl_available,
            "sf_hitl (human-in-the-loop) module available",
            "pip install spanforge  # sf_hitl is bundled",
        ))

    if fw_slug in ("soc2", "hipaa", "nist_ai_rmf", "iso_42001"):
        eval_on = False
        try:
            from spanforge.config import get_config
            cfg = get_config()
            eval_on = bool(getattr(cfg, "track_eval", False))
        except Exception:  # nosec B110
            pass
        checks.append((
            eval_on,
            "Eval tracking enabled (track_eval=True)",
            "spanforge.configure(track_eval=True)",
        ))

    if fw_slug in ("soc2", "hipaa", "iso_42001"):
        cost_on = False
        try:
            from spanforge.config import get_config
            cfg = get_config()
            cost_on = bool(getattr(cfg, "track_cost", False))
        except Exception:  # nosec B110
            pass
        checks.append((
            cost_on,
            "Cost tracking enabled (track_cost=True)",
            "spanforge.configure(track_cost=True)",
        ))

    return checks


def cmd_readiness(args: argparse.Namespace) -> int:
    """Implement ``spanforge compliance readiness``.

    Checks the current SpanForge configuration against the requirements
    for a target framework — *without* needing any events.  Answers:
    "What do I need to turn on before I hire an auditor?"
    """
    framework_key, framework = _resolve_framework(getattr(args, "framework", "eu_ai_act"))
    if framework is None:
        return 2

    pass_marker = "[✓]"  # noqa: S105  # nosec B105
    fail_marker = "[✗]"
    warn_marker = "[!]"

    checks = _build_readiness_checks(framework_key.lower())

    # --- Render ---
    print(f"SpanForge Compliance Readiness — {framework.value}")
    print("=" * 56)
    failures = 0
    for passed, label, fix in checks:
        if passed:
            print(f"  {pass_marker} {label}")
        else:
            print(f"  {fail_marker} {label}")
            print(f"         Fix: {fix}")
            failures += 1

    score = len(checks) - failures
    pct = int(score / len(checks) * 100) if checks else 0
    print("")
    print(f"Readiness: {score}/{len(checks)} checks passing ({pct}%)")

    if failures == 0:
        print(f"\n{pass_marker} Ready to begin a {framework.value} audit engagement.")
        return 0
    print(f"\n{warn_marker} Fix {failures} item(s) above before starting your audit engagement.")
    return 1


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
        choices=["json", "pdf", "markdown", "html", "both"],
        help="Output format: json, pdf, markdown, html, or both (default: json)",
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

    readiness_parser = comp_sub.add_parser(
        "readiness",
        help="Pre-audit config check: are you ready to start a compliance engagement?",
    )
    readiness_parser.add_argument(
        "--framework",
        default="eu_ai_act",
        help="Target framework to check readiness for (default: eu_ai_act)",
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

    vd_parser = comp_sub.add_parser(
        "validate-dataset",
        help="EU AI Act Article 10 compliance scan for training datasets",
    )
    vd_parser.add_argument(
        "dataset_path",
        metavar="PATH",
        help="Path to a dataset file or directory to scan recursively",
    )
    vd_parser.add_argument(
        "--output",
        dest="output_format",
        choices=["report", "json", "pdf"],
        default="report",
        help="Output format: report (markdown, default), json, or pdf (requires reportlab)",
    )
    vd_parser.add_argument(
        "--no-sign",
        dest="no_sign",
        action="store_true",
        default=False,
        help="Omit HMAC signing of the report",
    )

    return compliance_parser


def dispatch_compliance_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Dispatch the compliance command group."""
    action = getattr(args, "compliance_command", None)
    import argparse as _ap
    _dispatch: dict[str, Callable[[_ap.Namespace], int]] = {
        "generate": cmd_generate,
        "validate-attestation": cmd_validate_attestation,
        "validate-dataset": cmd_validate_dataset,
        "check": cmd_check,
        "report": cmd_report,
        "status": cmd_status,
        "readiness": cmd_readiness,
    }
    handler = _dispatch.get(action or "")
    if handler is not None:
        return handler(args)
    parser.print_help()
    return 2
