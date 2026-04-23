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
