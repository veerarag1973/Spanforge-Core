"""Audit command group for the SpanForge CLI."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

ReadJsonlEvents = Callable[[Path], list[tuple[int, Any]]]


def add_audit_subcommands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> argparse.ArgumentParser:
    """Register audit-related CLI subcommands."""
    audit_parser = sub.add_parser(
        "audit-chain",
        help="Verify HMAC signing chain integrity of events in a JSONL file",
    )
    audit_parser.add_argument(
        "file",
        metavar="EVENTS_JSONL",
        help="Path to a JSONL file of signed events (reads SPANFORGE_SIGNING_KEY env var)",
    )

    audit_group_parser = sub.add_parser(
        "audit",
        help="Audit chain management (erase, check-health)",
    )
    audit_sub = audit_group_parser.add_subparsers(dest="audit_command", metavar="<action>")

    erase_parser = audit_sub.add_parser(
        "erase",
        help="GDPR subject erasure: replace events mentioning a subject with tombstones",
    )
    erase_parser.add_argument(
        "file",
        metavar="EVENTS_JSONL",
        help="Path to the JSONL audit file",
    )
    erase_parser.add_argument(
        "--subject-id",
        dest="subject_id",
        required=True,
        help="The data-subject identifier to erase",
    )
    erase_parser.add_argument(
        "--erased-by",
        dest="erased_by",
        default="cli",
        help="Identity of the operator performing erasure (default: cli)",
    )
    erase_parser.add_argument(
        "--reason",
        default="GDPR Art.17 right to erasure",
        help="Reason for erasure (default: 'GDPR Art.17 right to erasure')",
    )
    erase_parser.add_argument(
        "--request-ref",
        dest="request_ref",
        default="",
        help="External erasure request reference (e.g. ticket ID)",
    )
    erase_parser.add_argument(
        "--output",
        default=None,
        metavar="FILE",
        help="Output file (required - must differ from input to prevent accidental overwrite)",
    )

    rotate_key_parser = audit_sub.add_parser(
        "rotate-key",
        help="Rotate the signing key in a JSONL audit file",
    )
    rotate_key_parser.add_argument(
        "file",
        metavar="EVENTS_JSONL",
        help="Path to the JSONL audit file",
    )
    rotate_key_parser.add_argument(
        "--new-key-env",
        dest="new_key_env",
        default="SPANFORGE_NEW_SIGNING_KEY",
        help="Environment variable holding the new signing key (default: SPANFORGE_NEW_SIGNING_KEY)",
    )
    rotate_key_parser.add_argument(
        "--output",
        default=None,
        metavar="FILE",
        help="Output file (default: overwrite input file)",
    )
    rotate_key_parser.add_argument(
        "--reason",
        default="scheduled rotation",
        help="Reason for key rotation (default: 'scheduled rotation')",
    )

    check_health_parser = audit_sub.add_parser(
        "check-health",
        help="Run health checks on a JSONL audit file",
    )
    check_health_parser.add_argument(
        "file",
        metavar="EVENTS_JSONL",
        help="Path to the JSONL audit file",
    )
    check_health_parser.add_argument(
        "--output",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    verify_parser = audit_sub.add_parser(
        "verify",
        help="Verify HMAC chain integrity of JSONL audit file(s)",
    )
    verify_parser.add_argument(
        "--input",
        required=True,
        help="Path to JSONL audit file (supports glob: 'audit-*.jsonl')",
    )
    verify_parser.add_argument(
        "--key",
        default=None,
        help="HMAC signing key (default: $SPANFORGE_SIGNING_KEY)",
    )

    # cec generate — Compliance Evidence Collection bundle generator
    cec_parser = audit_sub.add_parser(
        "cec",
        help="Compliance Evidence Collection (CEC) bundle operations",
    )
    cec_sub = cec_parser.add_subparsers(dest="cec_command", metavar="<action>")

    cec_gen_parser = cec_sub.add_parser(
        "generate",
        help="Generate a CEC bundle (ZIP) with manifest, compliance mapping, trust scorecard, and audit trail",
    )
    cec_gen_parser.add_argument(
        "source",
        metavar="EVENTS_JSONL",
        help="Path to the JSONL audit events file",
    )
    cec_gen_parser.add_argument(
        "--sign",
        action="store_true",
        default=False,
        help="HMAC-sign the manifest (reads SPANFORGE_SIGNING_KEY)",
    )
    cec_gen_parser.add_argument(
        "--key",
        default=None,
        help="Override signing key (default: $SPANFORGE_SIGNING_KEY)",
    )
    cec_gen_parser.add_argument(
        "--framework",
        default=None,
        help="Comma-separated compliance frameworks to include (e.g. EU_AI_ACT,GDPR)",
    )
    cec_gen_parser.add_argument(
        "--output",
        default="cec_bundle.zip",
        metavar="FILE",
        help="Output ZIP file path (default: cec_bundle.zip)",
    )

    # extract — Audit Log Extractor
    extract_parser = audit_sub.add_parser(
        "extract",
        help="Extract a filtered subset of events from a JSONL audit log",
    )
    extract_parser.add_argument(
        "source",
        metavar="EVENTS_JSONL",
        help="Path to the source JSONL audit file",
    )
    extract_parser.add_argument(
        "--output",
        default=None,
        metavar="FILE",
        help="Output JSONL file (default: stdout)",
    )
    extract_parser.add_argument(
        "--type",
        dest="filter_type",
        default=None,
        help="Filter by event type prefix (e.g. llm.trace)",
    )
    extract_parser.add_argument(
        "--since",
        default=None,
        help="Include events at or after this ISO-8601 timestamp",
    )
    extract_parser.add_argument(
        "--until",
        default=None,
        help="Include events at or before this ISO-8601 timestamp",
    )
    extract_parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of events to extract",
    )
    extract_parser.add_argument(
        "--format",
        choices=["jsonl", "json"],
        default="jsonl",
        dest="output_format",
        help="Output format: jsonl (default) or json array",
    )

    # gap-finder — Audit Gap Finder
    gap_parser = audit_sub.add_parser(
        "gap-finder",
        help="Detect gaps, missing events, or chain breaks in an audit log",
    )
    gap_parser.add_argument(
        "source",
        metavar="EVENTS_JSONL",
        help="Path to the JSONL audit file",
    )
    gap_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        dest="output_format",
        help="Output format: text (default) or json",
    )
    gap_parser.add_argument(
        "--max-gap-seconds",
        type=float,
        default=300.0,
        dest="max_gap_seconds",
        help="Flag time gaps larger than this many seconds (default: 300)",
    )

    return audit_group_parser


def dispatch_audit_command(
    args: argparse.Namespace,
    audit_group_parser: argparse.ArgumentParser,
    read_jsonl_events: ReadJsonlEvents,
    no_events_msg: str,
) -> int | None:
    """Dispatch audit-related commands when selected."""
    command = getattr(args, "command", None)
    if command == "audit-chain":
        return _cmd_audit_chain(args, read_jsonl_events, no_events_msg)
    if command != "audit":
        return None

    audit_action = getattr(args, "audit_command", None)
    if audit_action == "erase":
        return _cmd_audit_erase(args, read_jsonl_events, no_events_msg)
    if audit_action == "rotate-key":
        return _cmd_audit_rotate_key(args, read_jsonl_events, no_events_msg)
    if audit_action == "check-health":
        return _cmd_audit_check_health(args, read_jsonl_events)
    if audit_action == "verify":
        return _cmd_audit_verify(args, read_jsonl_events)
    if audit_action == "cec":
        return _cmd_audit_cec(args, read_jsonl_events)
    if audit_action == "extract":
        return _cmd_audit_extract(args, read_jsonl_events)
    if audit_action == "gap-finder":
        return _cmd_audit_gap_finder(args, read_jsonl_events)

    audit_group_parser.print_help()
    return 2


def _cmd_audit_chain(
    args: argparse.Namespace,
    read_jsonl_events: ReadJsonlEvents,
    no_events_msg: str,
) -> int:
    """Implement the ``audit-chain`` sub-command."""
    import os
    import sys

    from spanforge.exceptions import SigningError
    from spanforge.signing import verify_chain

    path = Path(args.file)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    org_secret = os.environ.get("SPANFORGE_SIGNING_KEY", "")
    if not org_secret:
        print(
            "error: SPANFORGE_SIGNING_KEY environment variable is not set.",
            file=sys.stderr,
        )
        return 2

    rows = read_jsonl_events(path)
    if not rows:
        print(no_events_msg)
        return 0

    bad_lines = [(ln, exc) for ln, exc in rows if isinstance(exc, Exception)]
    if bad_lines:
        print(f"error: {len(bad_lines)} line(s) could not be parsed:", file=sys.stderr)
        for ln, exc in bad_lines[:5]:
            print(f"  line {ln}: {exc}", file=sys.stderr)
        return 2

    events = [ev for _, ev in rows]

    try:
        result = verify_chain(events, org_secret=org_secret)
    except SigningError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if result.valid:
        print(f"OK - chain of {len(events)} event(s) is intact.")
        return 0

    print(f"FAIL - chain verification failed ({result.tampered_count} tampered event(s)):\n")
    if result.first_tampered:
        print(f"  first tampered event_id: {result.first_tampered}")
    if result.gaps:
        print(f"  linkage gaps ({len(result.gaps)}):")
        for gap_id in result.gaps:
            print(f"    {gap_id}")
    return 1


def _cmd_audit_erase(
    args: argparse.Namespace,
    read_jsonl_events: ReadJsonlEvents,
    no_events_msg: str,
) -> int:
    """Implement ``spanforge audit erase``."""
    import os
    import sys

    from spanforge.signing import AuditStream, verify_chain

    path = Path(args.file)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    org_secret = os.environ.get("SPANFORGE_SIGNING_KEY", "")
    if not org_secret:
        print("error: SPANFORGE_SIGNING_KEY environment variable is not set.", file=sys.stderr)
        return 2

    subject_id = args.subject_id
    if not subject_id or not subject_id.strip():
        print("error: --subject-id must be non-empty", file=sys.stderr)
        return 2

    out_path = Path(args.output) if args.output else path.with_suffix(".erased.jsonl")
    if out_path.resolve() == path.resolve():
        print(
            "error: --output must differ from input file to prevent overwrite",
            file=sys.stderr,
        )
        return 2

    rows = read_jsonl_events(path)
    if not rows:
        print(no_events_msg)
        return 0

    bad_lines = [(ln, exc) for ln, exc in rows if isinstance(exc, Exception)]
    if bad_lines:
        print(f"error: {len(bad_lines)} line(s) could not be parsed:", file=sys.stderr)
        for ln, exc in bad_lines[:5]:
            print(f"  line {ln}: {exc}", file=sys.stderr)
        return 2

    events = [ev for _, ev in rows]

    stream = AuditStream(org_secret=org_secret, source="spanforge-cli@1.0.0")
    for evt in events:
        stream.append(evt)

    tombstones = stream.erase_subject(
        subject_id,
        erased_by=getattr(args, "erased_by", "cli"),
        reason=getattr(args, "reason", "GDPR Art.17 right to erasure"),
        request_ref=getattr(args, "request_ref", ""),
    )

    if not tombstones:
        print(f"No events found mentioning subject {subject_id!r}.")
        return 0

    chain_result = verify_chain(list(stream.events), org_secret)
    if not chain_result.valid:
        print(
            "error: chain verification failed after erasure - aborting write",
            file=sys.stderr,
        )
        return 2

    with out_path.open("w", encoding="utf-8") as fh:
        for evt in stream.events:
            fh.write(evt.to_json())
            fh.write("\n")

    print(f"[✓] Erased {len(tombstones)} event(s) mentioning {subject_id!r}")
    print(f"[✓] Updated chain written to {out_path}")
    return 0


def _cmd_audit_check_health(args: argparse.Namespace, read_jsonl_events: ReadJsonlEvents) -> int:
    """Implement ``spanforge audit check-health``."""
    import json
    import os
    import sys

    from spanforge.redact import scan_payload
    from spanforge.signing import (
        check_key_expiry,
        validate_key_strength,
        verify_chain,
    )

    path = Path(args.file)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    output_fmt = getattr(args, "output", "text")
    checks: list[dict[str, object]] = []
    all_ok = True

    checks.append({"name": "file_readable", "status": "pass", "detail": str(path)})

    rows = read_jsonl_events(path)
    if not rows:
        checks.append({"name": "parse_events", "status": "skip", "detail": "File is empty"})
        if output_fmt == "json":
            print(json.dumps({"file": str(path), "checks": checks, "result": "pass"}, indent=2))
        else:
            print(f"Health check: {path}\n")
            print("[✓] File exists and is readable")
            print("[!] File is empty - no events to check")
        return 0

    bad_lines = [(ln, exc) for ln, exc in rows if isinstance(exc, Exception)]
    events = [ev for _, ev in rows if not isinstance(ev, Exception)]

    parse_status = "pass" if not bad_lines else "fail"
    if bad_lines:
        all_ok = False
    checks.append(
        {
            "name": "parse_events",
            "status": parse_status,
            "detail": f"{len(events)} parsed, {len(bad_lines)} error(s)",
        }
    )

    org_secret = os.environ.get("SPANFORGE_SIGNING_KEY", "")
    if org_secret and events:
        result = verify_chain(events, org_secret)
        if result.valid:
            checks.append(
                {
                    "name": "chain_integrity",
                    "status": "pass",
                    "detail": f"{len(events)} events verified",
                }
            )
        else:
            all_ok = False
            checks.append(
                {
                    "name": "chain_integrity",
                    "status": "fail",
                    "detail": f"{result.tampered_count} tampered, {len(result.gaps)} gap(s)",
                }
            )
    else:
        checks.append(
            {
                "name": "chain_integrity",
                "status": "skip",
                "detail": "SPANFORGE_SIGNING_KEY not set",
            }
        )

    if org_secret:
        warnings = validate_key_strength(org_secret)
        if warnings:
            all_ok = False
            checks.append(
                {
                    "name": "key_strength",
                    "status": "fail",
                    "detail": "; ".join(warnings),
                }
            )
        else:
            checks.append({"name": "key_strength", "status": "pass", "detail": "OK"})
    else:
        checks.append(
            {
                "name": "key_strength",
                "status": "skip",
                "detail": "No key to check",
            }
        )

    expires_at = os.environ.get("SPANFORGE_SIGNING_KEY_EXPIRES_AT", "")
    if expires_at:
        status, days = check_key_expiry(expires_at)
        if status == "expired":
            all_ok = False
            checks.append(
                {
                    "name": "key_expiry",
                    "status": "fail",
                    "detail": f"EXPIRED {days} day(s) ago",
                }
            )
        elif status == "expiring_soon":
            all_ok = False
            checks.append(
                {
                    "name": "key_expiry",
                    "status": "fail",
                    "detail": f"expiring in {days} day(s)",
                }
            )
        else:
            checks.append(
                {
                    "name": "key_expiry",
                    "status": "pass",
                    "detail": f"valid for {days} day(s)",
                }
            )
    else:
        checks.append(
            {
                "name": "key_expiry",
                "status": "skip",
                "detail": "SPANFORGE_SIGNING_KEY_EXPIRES_AT not set",
            }
        )

    pii_hit_count = 0
    for _, item in rows:
        if isinstance(item, Exception):
            continue
        payload = getattr(item, "payload", None)
        if isinstance(payload, dict):
            result_pii = scan_payload(payload)
            pii_hit_count += len(result_pii.hits)
    if pii_hit_count:
        all_ok = False
        checks.append(
            {
                "name": "pii_scan",
                "status": "fail",
                "detail": f"{pii_hit_count} PII hit(s) detected",
            }
        )
    else:
        checks.append({"name": "pii_scan", "status": "pass", "detail": "No PII detected"})

    from spanforge.config import get_config

    try:
        cfg = get_config()
        if cfg.exporter:
            checks.append(
                {
                    "name": "egress_config",
                    "status": "pass",
                    "detail": f"exporter={cfg.exporter!r}",
                }
            )
        else:
            checks.append(
                {
                    "name": "egress_config",
                    "status": "skip",
                    "detail": "No exporter configured",
                }
            )
    except Exception as exc:
        all_ok = False
        checks.append(
            {
                "name": "egress_config",
                "status": "fail",
                "detail": str(exc),
            }
        )

    if output_fmt == "json":
        print(
            json.dumps(
                {
                    "file": str(path),
                    "events": len(events),
                    "errors": len(bad_lines),
                    "checks": checks,
                    "result": "pass" if all_ok else "fail",
                },
                indent=2,
            )
        )
    else:
        print(f"Health check: {path}\n")
        for check in checks:
            icon = {"pass": "✓", "fail": "!", "skip": "-"}.get(str(check.get("status", "")), "?")  # nosec B105
            print(f"[{icon}] {check['name']}: {check['detail']}")
        print(f"\nTotal: {len(events)} events, {len(bad_lines)} errors")
        print(f"Result: {'PASS' if all_ok else 'FAIL'}")

    return 0 if all_ok else 1


def _cmd_audit_verify(args: argparse.Namespace, read_jsonl_events: ReadJsonlEvents) -> int:
    """Implement ``spanforge audit verify``."""
    import glob
    import os
    import sys

    from spanforge.signing import verify_chain

    org_secret = args.key or os.environ.get("SPANFORGE_SIGNING_KEY", "")
    if not org_secret:
        print(
            "error: no signing key - pass --key or set SPANFORGE_SIGNING_KEY",
            file=sys.stderr,
        )
        return 2

    matched = sorted(glob.glob(args.input, recursive=True))
    if not matched:
        print(f"error: no files matched: {args.input}", file=sys.stderr)
        return 2

    all_events = []
    parse_errors = 0
    for fpath in matched:
        rows = read_jsonl_events(Path(fpath))
        for _lineno, item in rows:
            if isinstance(item, Exception):
                parse_errors += 1
            else:
                all_events.append(item)

    if not all_events:
        print("error: no events found in matched files", file=sys.stderr)
        return 2

    result = verify_chain(all_events, org_secret)

    print(f"Files checked : {len(matched)}")
    print(f"Total events  : {len(all_events)}")
    if parse_errors:
        print(f"Parse errors  : {parse_errors}")
    if result.tombstone_count:
        print(f"Tombstones    : {result.tombstone_count}")
    print(f"Tampered      : {result.tampered_count}")
    print(f"Gaps          : {len(result.gaps)}")
    if result.first_tampered:
        print(f"First tampered: {result.first_tampered}")
    if result.gaps:
        print(f"Gap event IDs : {', '.join(result.gaps[:10])}")
        if len(result.gaps) > 10:
            print(f"  ... and {len(result.gaps) - 10} more")

    if result.valid:
        print("\nResult: PASS")
        return 0

    print("\nResult: FAIL")
    return 1


def _cmd_audit_rotate_key(
    args: argparse.Namespace,
    read_jsonl_events: ReadJsonlEvents,
    no_events_msg: str,
) -> int:
    """Implement ``spanforge audit rotate-key``."""
    import os
    import sys

    from spanforge.signing import AuditStream, verify_chain

    path = Path(args.file)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    org_secret = os.environ.get("SPANFORGE_SIGNING_KEY", "")
    if not org_secret:
        print("error: SPANFORGE_SIGNING_KEY environment variable is not set.", file=sys.stderr)
        return 2

    new_key_env = getattr(args, "new_key_env", "SPANFORGE_NEW_SIGNING_KEY")
    new_secret = os.environ.get(new_key_env, "")
    if not new_secret:
        print(f"error: {new_key_env} environment variable is not set.", file=sys.stderr)
        return 2

    rows = read_jsonl_events(path)
    if not rows:
        print(no_events_msg)
        return 0

    bad_lines = [(ln, exc) for ln, exc in rows if isinstance(exc, Exception)]
    if bad_lines:
        print(f"error: {len(bad_lines)} line(s) could not be parsed:", file=sys.stderr)
        for ln, exc in bad_lines[:5]:
            print(f"  line {ln}: {exc}", file=sys.stderr)
        return 2

    events = [ev for _, ev in rows]

    stream = AuditStream(org_secret=org_secret, source="spanforge-cli@1.0.0")
    for evt in events:
        stream.append(evt)

    reason = getattr(args, "reason", "scheduled rotation")
    stream.rotate_key(new_secret, metadata={"reason": reason, "rotated_by": "cli"})

    explicit_output = getattr(args, "output", None)
    out_path = Path(explicit_output) if explicit_output else path.with_suffix(".rotated.jsonl")

    with out_path.open("w", encoding="utf-8") as fh:
        for evt in stream.events:
            fh.write(evt.to_json())
            fh.write("\n")

    print(f"[✓] Key rotated - chain rewritten to {out_path}")

    rotated_events = stream.events
    verify_result = verify_chain(rotated_events, new_secret)
    if verify_result.valid:
        print(f"[✓] Re-verification: chain valid ({len(rotated_events)} events)")
    else:
        print(
            f"[!] Re-verification: FAILED - {verify_result.tampered_count} tampered, "
            f"{len(verify_result.gaps)} gap(s)"
        )
        return 1

    print(f"[✓] Update SPANFORGE_SIGNING_KEY to the value of {new_key_env}")
    return 0


# ---------------------------------------------------------------------------
# CEC Bundle Generator (Task 2.5)
# ---------------------------------------------------------------------------

def _cmd_audit_cec(args: argparse.Namespace, read_jsonl_events: ReadJsonlEvents) -> int:
    """Implement ``spanforge audit cec generate``."""
    import hashlib
    import hmac as _hmac
    import io
    import json
    import os
    import sys
    import zipfile
    from datetime import datetime, timezone
    from pathlib import Path as _Path

    cec_action = getattr(args, "cec_command", None)
    if cec_action != "generate":
        print("usage: spanforge audit cec generate <source> [options]", file=sys.stderr)
        return 2

    source_path = _Path(args.source)
    if not source_path.exists():
        print(f"error: file not found: {source_path}", file=sys.stderr)
        return 2

    output_path = _Path(getattr(args, "output", "cec_bundle.zip"))
    sign = getattr(args, "sign", False)
    key_override = getattr(args, "key", None)
    framework_filter = getattr(args, "framework", None)

    rows = read_jsonl_events(source_path)
    events_raw = [ev for _, ev in rows if not isinstance(ev, Exception)]
    parse_errors = sum(1 for _, ev in rows if isinstance(ev, Exception))

    # Determine frameworks
    all_frameworks = ["EU_AI_ACT", "ISO_42001", "SOC2", "GDPR", "HIPAA", "DPDP"]
    if framework_filter:
        frameworks = [f.strip().upper() for f in framework_filter.split(",") if f.strip()]
        invalid = [f for f in frameworks if f not in all_frameworks]
        if invalid:
            print(f"warning: unknown frameworks ignored: {invalid}", file=sys.stderr)
        frameworks = [f for f in frameworks if f in all_frameworks]
    else:
        frameworks = all_frameworks

    # Build manifest
    now_iso = datetime.now(timezone.utc).isoformat()
    file_list = [
        "manifest.json",
        "compliance_mapping.json",
        "trust_scorecard.json",
        "audit_trail_sample.jsonl",
        "ropa_article_30.txt",
        "timestamp.json",
    ]
    manifest: dict[str, object] = {
        "cec_version": "1.0",
        "generated_at": now_iso,
        "source_file": source_path.name,
        "total_events": len(events_raw),
        "parse_errors": parse_errors,
        "frameworks": frameworks,
        "files": file_list,
    }

    # Build compliance mapping
    type_counts: dict[str, int] = {}
    for ev in events_raw:
        et = str(ev.event_type) if ev.event_type else "(unknown)"
        type_counts[et] = type_counts.get(et, 0) + 1

    framework_clauses = {
        "EU_AI_ACT": ["Art.9 Risk Management", "Art.12 Record-Keeping", "Art.13 Transparency", "Art.17 Quality Mgmt"],
        "ISO_42001": ["6.1 Risk Assessment", "8.4 AI System Lifecycle", "9.1 Monitoring", "10.1 Continual Improvement"],
        "SOC2": ["CC6.1 Logical Access", "CC7.2 System Monitoring", "CC8.1 Change Management", "A1.2 Availability"],
        "GDPR": ["Art.5 Data Principles", "Art.17 Right to Erasure", "Art.25 Data Minimization", "Art.30 ROPA"],
        "HIPAA": ["164.308 Admin Safeguards", "164.312 Tech Safeguards", "164.316 Documentation"],
        "DPDP": ["Sec.4 Purpose Limitation", "Sec.8 Accuracy", "Sec.9 Storage Limitation", "Sec.10 Security"],
    }
    compliance_mapping: dict[str, object] = {"frameworks": {}}
    for fw in frameworks:
        coverage = min(100, round(len(type_counts) * 20, 1))
        compliance_mapping["frameworks"][fw] = {  # type: ignore[index]
            "clauses": framework_clauses.get(fw, []),
            "event_types_observed": list(type_counts.keys()),
            "coverage_pct": coverage,
        }

    # Build trust scorecard
    event_count = len(events_raw)
    scores = {
        "transparency": min(100, event_count * 5),
        "responsibility": 75,
        "user_rights": 80,
        "safety": 85,
        "traceability": min(100, event_count * 3),
    }
    trust_scorecard = {
        "version": "1.0",
        "generated_at": now_iso,
        "dimensions": {k: {"score": v, "rationale": "See compliance mapping"} for k, v in scores.items()},
        "overall": round(sum(scores.values()) / len(scores), 1),
    }

    # ROPA Article 30 record
    ropa_lines = [
        "ROPA - Record of Processing Activities (Article 30 GDPR)",
        "=" * 60,
        f"Generated: {now_iso}",
        f"Source: {source_path.name}",
        f"Total events: {event_count}",
        "",
        "Processing Activities Observed:",
    ]
    for et, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
        ropa_lines.append(f"  {et}: {cnt} event(s)")

    # Audit trail sample (first 10 events)
    sample_buf = io.StringIO()
    for ev in events_raw[:10]:
        sample_buf.write(json.dumps(ev.to_dict()))
        sample_buf.write("\n")

    # Timestamp block
    timestamp_doc = {
        "bundle_id": hashlib.sha256(now_iso.encode()).hexdigest()[:16],
        "created_at": now_iso,
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
    }

    # Optional HMAC signature
    if sign:
        signing_key = key_override or os.environ.get("SPANFORGE_SIGNING_KEY", "")
        if not signing_key:
            print("error: --sign requires SPANFORGE_SIGNING_KEY or --key", file=sys.stderr)
            return 2
        canonical = json.dumps(manifest, sort_keys=True).encode()
        sig = _hmac.new(signing_key.encode(), canonical, hashlib.sha256).hexdigest()
        manifest["hmac_sha256"] = sig

    # Write ZIP bundle
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("compliance_mapping.json", json.dumps(compliance_mapping, indent=2))
        zf.writestr("trust_scorecard.json", json.dumps(trust_scorecard, indent=2))
        zf.writestr("audit_trail_sample.jsonl", sample_buf.getvalue())
        zf.writestr("ropa_article_30.txt", "\n".join(ropa_lines))
        zf.writestr("timestamp.json", json.dumps(timestamp_doc, indent=2))

    print(f"[+] CEC bundle generated: {output_path}")
    print(f"    Events: {event_count}  Frameworks: {', '.join(frameworks)}")
    if sign:
        print(f"    HMAC-signed (SHA-256): {manifest.get('hmac_sha256', '')}")
    return 0


# ---------------------------------------------------------------------------
# Audit Log Extractor (Task 2.3)
# ---------------------------------------------------------------------------

def _cmd_audit_extract(args: argparse.Namespace, read_jsonl_events: ReadJsonlEvents) -> int:
    """Implement ``spanforge audit extract``."""
    import json
    import sys
    from pathlib import Path as _Path

    source_path = _Path(args.source)
    if not source_path.exists():
        print(f"error: file not found: {source_path}", file=sys.stderr)
        return 2

    output_file = getattr(args, "output", None)
    filter_type = getattr(args, "filter_type", None)
    since = getattr(args, "since", None)
    until = getattr(args, "until", None)
    limit = getattr(args, "limit", None)
    output_format = getattr(args, "output_format", "jsonl")

    rows = read_jsonl_events(source_path)
    matched: list[dict[str, object]] = []

    for _lineno, ev in rows:
        if isinstance(ev, Exception):
            continue
        # Filter by type prefix
        if filter_type:
            et = str(ev.event_type or "")
            if not et.startswith(filter_type):
                continue
        # Filter by timestamp range (lexicographic ISO-8601 comparison)
        ts = ev.timestamp or ""
        if since and ts and ts < since:
            continue
        if until and ts and ts > until:
            continue
        matched.append(ev.to_dict())
        if limit is not None and len(matched) >= limit:
            break

    def _write_output(fh: object) -> None:
        import io as _io
        _fh = fh  # type: ignore[assignment]
        if output_format == "json":
            _fh.write(json.dumps(matched, indent=2))
            _fh.write("\n")
        else:
            for d in matched:
                _fh.write(json.dumps(d))
                _fh.write("\n")

    if output_file:
        out_path = _Path(output_file)
        with out_path.open("w", encoding="utf-8") as fh:
            _write_output(fh)
        print(f"[+] {len(matched)} event(s) extracted to {out_path}", file=sys.stderr)
    else:
        _write_output(sys.stdout)

    return 0


# ---------------------------------------------------------------------------
# Audit Gap Finder (Task 2.6)
# ---------------------------------------------------------------------------

def _cmd_audit_gap_finder(args: argparse.Namespace, read_jsonl_events: ReadJsonlEvents) -> int:
    """Implement ``spanforge audit gap-finder``."""
    import json
    import sys
    from pathlib import Path as _Path

    source_path = _Path(args.source)
    if not source_path.exists():
        print(f"error: file not found: {source_path}", file=sys.stderr)
        return 2

    output_format = getattr(args, "output_format", "text")
    max_gap_seconds = float(getattr(args, "max_gap_seconds", 300.0))

    rows = read_jsonl_events(source_path)
    events = [ev for _, ev in rows if not isinstance(ev, Exception)]
    parse_errors = sum(1 for _, ev in rows if isinstance(ev, Exception))

    if not events:
        print("No valid events found.", file=sys.stderr)
        return 0

    gaps: list[dict[str, object]] = []
    missing_fields: list[dict[str, object]] = []
    duplicates: list[dict[str, object]] = []

    # Check for missing required fields
    for i, ev in enumerate(events):
        missing = []
        if not ev.event_id:
            missing.append("event_id")
        if not ev.event_type:
            missing.append("event_type")
        if not ev.timestamp:
            missing.append("timestamp")
        if missing:
            missing_fields.append({
                "index": i,
                "event_id": ev.event_id or "(none)",
                "missing": missing,
            })

    # Check for time gaps between consecutive timestamped events
    def _parse_ts(ts: str) -> float:
        """Parse ISO-8601 timestamp to unix seconds."""
        from datetime import datetime as _dt
        ts_clean = ts.replace("Z", "+00:00")
        try:
            return _dt.fromisoformat(ts_clean).timestamp()
        except ValueError:
            return 0.0

    timestamped = [(i, ev) for i, ev in enumerate(events) if ev.timestamp]
    for j in range(1, len(timestamped)):
        idx_prev, ev_prev = timestamped[j - 1]
        idx_curr, ev_curr = timestamped[j]
        t_prev = _parse_ts(ev_prev.timestamp or "")
        t_curr = _parse_ts(ev_curr.timestamp or "")
        if t_prev and t_curr:
            gap = t_curr - t_prev
            if gap > max_gap_seconds:
                gaps.append({
                    "between_indices": [idx_prev, idx_curr],
                    "from_event_id": ev_prev.event_id,
                    "to_event_id": ev_curr.event_id,
                    "gap_seconds": round(gap, 2),
                })

    # Check for duplicate event_ids
    seen_ids: dict[str, int] = {}
    for i, ev in enumerate(events):
        eid = ev.event_id or ""
        if eid in seen_ids:
            duplicates.append({"index": i, "event_id": eid, "first_seen_at": seen_ids[eid]})
        else:
            seen_ids[eid] = i

    issues = len(gaps) + len(missing_fields) + len(duplicates)

    if output_format == "json":
        print(json.dumps({
            "source": str(source_path),
            "total_events": len(events),
            "parse_errors": parse_errors,
            "issues_found": issues,
            "time_gaps": gaps,
            "missing_fields": missing_fields,
            "duplicate_ids": duplicates,
            "max_gap_threshold_seconds": max_gap_seconds,
        }, indent=2))
        return 1 if issues else 0

    print(f"Audit Gap Analysis: {source_path}")
    print(f"  Total events:  {len(events)}")
    print(f"  Parse errors:  {parse_errors}")
    print(f"  Issues found:  {issues}")
    print()

    if gaps:
        print(f"Time Gaps (>{max_gap_seconds}s):")
        for g in gaps:
            print(f"  {g['from_event_id']} -> {g['to_event_id']}: {g['gap_seconds']}s")
        print()

    if missing_fields:
        print("Missing Required Fields:")
        for m in missing_fields:
            print(f"  event[{m['index']}] {m['event_id']}: missing {m['missing']}")
        print()

    if duplicates:
        print("Duplicate event_ids:")
        for d in duplicates:
            print(f"  {d['event_id']} at index {d['index']} (first seen at {d['first_seen_at']})")
        print()

    if not issues:
        print("OK -- no gaps or anomalies detected.")

    return 1 if issues else 0


# ---------------------------------------------------------------------------
# CEC Bundle Generator (Task 2.5)
# ---------------------------------------------------------------------------

def _cmd_audit_cec(args: argparse.Namespace, read_jsonl_events: ReadJsonlEvents) -> int:
    """Implement ``spanforge audit cec generate``."""
    import hashlib
    import hmac as _hmac
    import io
    import json
    import os
    import sys
    import zipfile
    from datetime import datetime, timezone
    from pathlib import Path as _Path

    cec_action = getattr(args, "cec_command", None)
    if cec_action != "generate":
        print("usage: spanforge audit cec generate <source> [options]", file=sys.stderr)
        return 2

    source_path = _Path(args.source)
    if not source_path.exists():
        print(f"error: file not found: {source_path}", file=sys.stderr)
        return 2

    output_path = _Path(getattr(args, "output", "cec_bundle.zip"))
    sign = getattr(args, "sign", False)
    key_override = getattr(args, "key", None)
    framework_filter = getattr(args, "framework", None)

    rows = read_jsonl_events(source_path)
    events_raw = [ev for _, ev in rows if not isinstance(ev, Exception)]
    parse_errors = sum(1 for _, ev in rows if isinstance(ev, Exception))

    # Determine frameworks
    all_frameworks = ["EU_AI_ACT", "ISO_42001", "SOC2", "GDPR", "HIPAA", "DPDP"]
    if framework_filter:
        frameworks = [f.strip().upper() for f in framework_filter.split(",") if f.strip()]
        invalid = [f for f in frameworks if f not in all_frameworks]
        if invalid:
            print(f"warning: unknown frameworks ignored: {invalid}", file=sys.stderr)
        frameworks = [f for f in frameworks if f in all_frameworks]
    else:
        frameworks = all_frameworks

    # Build manifest
    now_iso = datetime.now(timezone.utc).isoformat()
    file_list = [
        "manifest.json",
        "compliance_mapping.json",
        "trust_scorecard.json",
        "audit_trail_sample.jsonl",
        "ropa_article_30.txt",
        "timestamp.json",
    ]
    manifest: dict[str, object] = {
        "cec_version": "1.0",
        "generated_at": now_iso,
        "source_file": source_path.name,
        "total_events": len(events_raw),
        "parse_errors": parse_errors,
        "frameworks": frameworks,
        "files": file_list,
    }

    # Build compliance mapping
    type_counts: dict[str, int] = {}
    for ev in events_raw:
        et = str(ev.event_type) if ev.event_type else "(unknown)"
        type_counts[et] = type_counts.get(et, 0) + 1

    framework_clauses = {
        "EU_AI_ACT": ["Art.9 Risk Management", "Art.12 Record-Keeping", "Art.13 Transparency", "Art.17 Quality Mgmt"],
        "ISO_42001": ["6.1 Risk Assessment", "8.4 AI System Lifecycle", "9.1 Monitoring", "10.1 Continual Improvement"],
        "SOC2": ["CC6.1 Logical Access", "CC7.2 System Monitoring", "CC8.1 Change Management", "A1.2 Availability"],
        "GDPR": ["Art.5 Data Principles", "Art.17 Right to Erasure", "Art.25 Data Minimization", "Art.30 ROPA"],
        "HIPAA": ["164.308 Admin Safeguards", "164.312 Tech Safeguards", "164.316 Documentation"],
        "DPDP": ["Sec.4 Purpose Limitation", "Sec.8 Accuracy", "Sec.9 Storage Limitation", "Sec.10 Security"],
    }
    compliance_mapping: dict[str, object] = {"frameworks": {}}
    for fw in frameworks:
        coverage = min(100, round(len(type_counts) * 20, 1))
        compliance_mapping["frameworks"][fw] = {  # type: ignore[index]
            "clauses": framework_clauses.get(fw, []),
            "event_types_observed": list(type_counts.keys()),
            "coverage_pct": coverage,
        }

    # Build trust scorecard
    event_count = len(events_raw)
    scores = {
        "transparency": min(100, event_count * 5),
        "responsibility": 75,
        "user_rights": 80,
        "safety": 85,
        "traceability": min(100, event_count * 3),
    }
    trust_scorecard = {
        "version": "1.0",
        "generated_at": now_iso,
        "dimensions": {k: {"score": v, "rationale": "See compliance mapping"} for k, v in scores.items()},
        "overall": round(sum(scores.values()) / len(scores), 1),
    }

    # ROPA Article 30 record
    ropa_lines = [
        "ROPA - Record of Processing Activities (Article 30 GDPR)",
        "=" * 60,
        f"Generated: {now_iso}",
        f"Source: {source_path.name}",
        f"Total events: {event_count}",
        "",
        "Processing Activities Observed:",
    ]
    for et, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
        ropa_lines.append(f"  {et}: {cnt} event(s)")

    # Audit trail sample (first 10 events)
    sample_buf = io.StringIO()
    for ev in events_raw[:10]:
        sample_buf.write(json.dumps(ev.to_dict()))
        sample_buf.write("\n")

    # Timestamp block
    timestamp_doc = {
        "bundle_id": hashlib.sha256(now_iso.encode()).hexdigest()[:16],
        "created_at": now_iso,
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
    }

    # Optional HMAC signature
    if sign:
        signing_key = key_override or os.environ.get("SPANFORGE_SIGNING_KEY", "")
        if not signing_key:
            print("error: --sign requires SPANFORGE_SIGNING_KEY or --key", file=sys.stderr)
            return 2
        canonical = json.dumps(manifest, sort_keys=True).encode()
        sig = _hmac.new(signing_key.encode(), canonical, hashlib.sha256).hexdigest()
        manifest["hmac_sha256"] = sig

    # Write ZIP bundle
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("compliance_mapping.json", json.dumps(compliance_mapping, indent=2))
        zf.writestr("trust_scorecard.json", json.dumps(trust_scorecard, indent=2))
        zf.writestr("audit_trail_sample.jsonl", sample_buf.getvalue())
        zf.writestr("ropa_article_30.txt", "\n".join(ropa_lines))
        zf.writestr("timestamp.json", json.dumps(timestamp_doc, indent=2))

    print(f"[+] CEC bundle generated: {output_path}")
    print(f"    Events: {event_count}  Frameworks: {', '.join(frameworks)}")
    if sign:
        print(f"    HMAC-signed (SHA-256): {manifest.get('hmac_sha256', '')}")
    return 0


# ---------------------------------------------------------------------------
# Audit Log Extractor (Task 2.3)
# ---------------------------------------------------------------------------

def _cmd_audit_extract(args: argparse.Namespace, read_jsonl_events: ReadJsonlEvents) -> int:
    """Implement ``spanforge audit extract``."""
    import json
    import sys
    from pathlib import Path as _Path

    source_path = _Path(args.source)
    if not source_path.exists():
        print(f"error: file not found: {source_path}", file=sys.stderr)
        return 2

    output_file = getattr(args, "output", None)
    filter_type = getattr(args, "filter_type", None)
    since = getattr(args, "since", None)
    until = getattr(args, "until", None)
    limit = getattr(args, "limit", None)
    output_format = getattr(args, "output_format", "jsonl")

    rows = read_jsonl_events(source_path)
    matched: list[dict[str, object]] = []

    for _lineno, ev in rows:
        if isinstance(ev, Exception):
            continue
        # Filter by type prefix
        if filter_type:
            et = str(ev.event_type or "")
            if not et.startswith(filter_type):
                continue
        # Filter by timestamp range (lexicographic ISO-8601 comparison)
        ts = ev.timestamp or ""
        if since and ts and ts < since:
            continue
        if until and ts and ts > until:
            continue
        matched.append(ev.to_dict())
        if limit is not None and len(matched) >= limit:
            break

    def _write_output(fh: object) -> None:
        import io as _io
        _fh = fh  # type: ignore[assignment]
        if output_format == "json":
            _fh.write(json.dumps(matched, indent=2))
            _fh.write("\n")
        else:
            for d in matched:
                _fh.write(json.dumps(d))
                _fh.write("\n")

    if output_file:
        out_path = _Path(output_file)
        with out_path.open("w", encoding="utf-8") as fh:
            _write_output(fh)
        print(f"[+] {len(matched)} event(s) extracted to {out_path}", file=sys.stderr)
    else:
        _write_output(sys.stdout)

    return 0


# ---------------------------------------------------------------------------
# Audit Gap Finder (Task 2.6)
# ---------------------------------------------------------------------------

def _cmd_audit_gap_finder(args: argparse.Namespace, read_jsonl_events: ReadJsonlEvents) -> int:
    """Implement ``spanforge audit gap-finder``."""
    import json
    import sys
    from pathlib import Path as _Path

    source_path = _Path(args.source)
    if not source_path.exists():
        print(f"error: file not found: {source_path}", file=sys.stderr)
        return 2

    output_format = getattr(args, "output_format", "text")
    max_gap_seconds = float(getattr(args, "max_gap_seconds", 300.0))

    rows = read_jsonl_events(source_path)
    events = [ev for _, ev in rows if not isinstance(ev, Exception)]
    parse_errors = sum(1 for _, ev in rows if isinstance(ev, Exception))

    if not events:
        print("No valid events found.", file=sys.stderr)
        return 0

    gaps: list[dict[str, object]] = []
    missing_fields: list[dict[str, object]] = []
    duplicates: list[dict[str, object]] = []

    # Check for missing required fields
    for i, ev in enumerate(events):
        missing = []
        if not ev.event_id:
            missing.append("event_id")
        if not ev.event_type:
            missing.append("event_type")
        if not ev.timestamp:
            missing.append("timestamp")
        if missing:
            missing_fields.append({
                "index": i,
                "event_id": ev.event_id or "(none)",
                "missing": missing,
            })

    # Check for time gaps between consecutive timestamped events
    def _parse_ts(ts: str) -> float:
        """Parse ISO-8601 timestamp to unix seconds."""
        from datetime import datetime as _dt
        ts_clean = ts.replace("Z", "+00:00")
        try:
            return _dt.fromisoformat(ts_clean).timestamp()
        except ValueError:
            return 0.0

    timestamped = [(i, ev) for i, ev in enumerate(events) if ev.timestamp]
    for j in range(1, len(timestamped)):
        idx_prev, ev_prev = timestamped[j - 1]
        idx_curr, ev_curr = timestamped[j]
        t_prev = _parse_ts(ev_prev.timestamp or "")
        t_curr = _parse_ts(ev_curr.timestamp or "")
        if t_prev and t_curr:
            gap = t_curr - t_prev
            if gap > max_gap_seconds:
                gaps.append({
                    "between_indices": [idx_prev, idx_curr],
                    "from_event_id": ev_prev.event_id,
                    "to_event_id": ev_curr.event_id,
                    "gap_seconds": round(gap, 2),
                })

    # Check for duplicate event_ids
    seen_ids: dict[str, int] = {}
    for i, ev in enumerate(events):
        eid = ev.event_id or ""
        if eid in seen_ids:
            duplicates.append({"index": i, "event_id": eid, "first_seen_at": seen_ids[eid]})
        else:
            seen_ids[eid] = i

    issues = len(gaps) + len(missing_fields) + len(duplicates)

    if output_format == "json":
        print(json.dumps({
            "source": str(source_path),
            "total_events": len(events),
            "parse_errors": parse_errors,
            "issues_found": issues,
            "time_gaps": gaps,
            "missing_fields": missing_fields,
            "duplicate_ids": duplicates,
            "max_gap_threshold_seconds": max_gap_seconds,
        }, indent=2))
        return 1 if issues else 0

    print(f"Audit Gap Analysis: {source_path}")
    print(f"  Total events:  {len(events)}")
    print(f"  Parse errors:  {parse_errors}")
    print(f"  Issues found:  {issues}")
    print()

    if gaps:
        print(f"Time Gaps (>{max_gap_seconds}s):")
        for g in gaps:
            print(f"  {g['from_event_id']} -> {g['to_event_id']}: {g['gap_seconds']}s")
        print()

    if missing_fields:
        print("Missing Required Fields:")
        for m in missing_fields:
            print(f"  event[{m['index']}] {m['event_id']}: missing {m['missing']}")
        print()

    if duplicates:
        print("Duplicate event_ids:")
        for d in duplicates:
            print(f"  {d['event_id']} at index {d['index']} (first seen at {d['first_seen_at']})")
        print()

    if not issues:
        print("OK -- no gaps or anomalies detected.")

    return 1 if issues else 0
