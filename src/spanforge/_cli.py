"""Command-line interface for spanforge utilities.

This module provides the ``spanforge`` entry-point command.  It is excluded
from coverage measurement because it is a thin integration shim over the
public library API — all business logic lives in tested library modules.

Entry-point (configured in pyproject.toml)::

    spanforge = "spanforge._cli:main"

Sub-commands
------------
``spanforge check``
    End-to-end health check: validates configuration, emits a test event,
    and confirms the export pipeline is working.  Exits 0 on success.

``spanforge check-compat <events.json>``
    Load a JSON file containing a list of serialised events and run the
    v1.0 compatibility checklist.  Exits 0 on success, 1 on violations,
    2 on usage/parse errors.

``spanforge list-deprecated``
    Print all event types registered in the global deprecation registry.

``spanforge migration-roadmap [--json]``
    Print the planned v1 → v2 migration roadmap from
    :func:`~spanforge.migrate.v2_migration_roadmap`.  Pass
    ``--json`` to emit JSON for machine consumption.

``spanforge check-consumers``
    Assert that all globally registered consumers are compatible with the
    installed schema version.  Exits 0 on success, 1 on incompatibilities.

``spanforge validate <events.jsonl>``
    Validate every event in a JSONL file against the published schema.
    Exits 0 if all events are valid, 1 if any fail validation.

``spanforge audit-chain <events.jsonl>``
    Verify the HMAC signing chain of events in a JSONL file.  Reads the
    signing key from the ``SPANFORGE_SIGNING_KEY`` environment variable.
    Exits 0 if the chain is intact, 1 if tampering or gaps are found.

``spanforge inspect <event_id> <events.jsonl>``
    Find a single event by ``event_id`` in a JSONL file and pretty-print
    its JSON envelope to stdout.  Exits 0 on success, 1 if not found.

``spanforge stats <events.jsonl>``
    Print a summary table of events in a JSONL file: event counts by type,
    total prompt/completion/total tokens, total cost, and timestamp range.
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path
from typing import NoReturn

_NO_EVENTS_MSG = "No events found in file."

def _cmd_check(_args: argparse.Namespace) -> int:
    """Implement the ``check`` sub-command — end-to-end health check."""
    import traceback  # noqa: PLC0415

    print("spanforge health check")
    print("=" * 40)
    ok = True

    # Step 1: Config
    try:
        from spanforge.config import get_config  # noqa: PLC0415
        cfg = get_config()
        print(f"[✓] Config loaded  exporter={cfg.exporter!r}  env={cfg.env!r}  "
              f"service={cfg.service_name!r}")
    except Exception as exc:
        print(f"[✗] Config failed: {exc}", file=sys.stderr)
        return 1

    # Step 2: Event creation
    try:
        from spanforge.event import Event  # noqa: PLC0415
        from spanforge.ulid import generate as gen_ulid  # noqa: PLC0415
        event = Event(
            event_type="llm.trace.span.completed",
            source=f"{cfg.service_name}@0.0.0",
            payload={
                "span_id": "0" * 16,
                "trace_id": "0" * 32,
                "span_name": "spanforge.health.check",
                "operation": "chat",
                "span_kind": "client",
                "status": "ok",
                "start_time_unix_nano": 0,
                "end_time_unix_nano": 1_000_000,
                "duration_ms": 1.0,
            },
            event_id=gen_ulid(),
        )
        print("[✓] Test event created")
    except Exception as exc:
        print(f"[✗] Event creation failed: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1

    # Step 3: Schema validation
    try:
        from spanforge.validate import validate_event  # noqa: PLC0415
        validate_event(event)
        print("[✓] Schema validation passed")
    except Exception as exc:
        print(f"[✗] Schema validation failed: {exc}", file=sys.stderr)
        ok = False

    # Step 4: Export pipeline
    try:
        from spanforge._stream import _dispatch  # noqa: PLC0415
        _dispatch(event)
        print("[✓] Export pipeline: event dispatched successfully")
    except Exception as exc:
        print(f"[✗] Export pipeline failed: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        ok = False

    # Step 5: TraceStore recording (only if enabled)
    if cfg.enable_trace_store:
        try:
            from spanforge._store import get_store  # noqa: PLC0415
            store = get_store()
            events = store.get_trace("0" * 32)
            if events is not None and len(events) >= 1:
                print(f"[✓] TraceStore recorded {len(events)} event(s)")
            else:
                print("[✗] TraceStore: event not found after dispatch", file=sys.stderr)
                ok = False
        except Exception as exc:
            print(f"[✗] TraceStore check failed: {exc}", file=sys.stderr)
            ok = False
    else:
        print("[–] TraceStore: disabled (set SPANFORGE_ENABLE_TRACE_STORE=1 to enable)")

    print("=" * 40)
    if ok:
        print("PASS — all checks passed.")
        return 0
    print("FAIL — one or more checks failed.", file=sys.stderr)
    return 1


def _cmd_check_compat(args: argparse.Namespace) -> int:
    """Implement the ``check-compat`` sub-command."""
    from spanforge.compliance import test_compatibility  # noqa: PLC0415
    from spanforge.event import Event  # noqa: PLC0415

    path = Path(args.file)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in {path}: {exc}", file=sys.stderr)
        return 2

    if not isinstance(raw, list):
        print("error: JSON file must contain a top-level array of events", file=sys.stderr)
        return 2

    from spanforge.exceptions import DeserializationError, SchemaValidationError  # noqa: PLC0415
    try:
        events = [Event.from_dict(item) for item in raw]
    except (DeserializationError, SchemaValidationError, KeyError, TypeError) as exc:
        print(f"error: could not deserialise events: {exc}", file=sys.stderr)
        return 2

    result = test_compatibility(events)

    if result.passed:
        print(
            f"OK — {result.events_checked} event(s) passed all compatibility checks."
        )
        return 0

    print(
        f"FAIL — {len(result.violations)} violation(s) found in "
        f"{result.events_checked} event(s):\n"
    )
    for v in result.violations:
        event_ref = f"[{v.event_id}] " if v.event_id else ""
        print(f"  {event_ref}{v.check_id} ({v.rule}): {v.detail}")

    return 1


def _cmd_list_deprecated(_args: argparse.Namespace) -> int:
    """Implement the ``list-deprecated`` sub-command."""
    try:
        from spanforge.deprecations import list_deprecated  # noqa: PLC0415

        notices = list_deprecated()
        if not notices:
            print("No deprecated event types registered.")
            return 0

        print(f"{'Event Type':<50} {'Since':<8} {'Sunset':<8} Replacement")
        print("-" * 90)
        for n in notices:
            repl = n.replacement or "(no replacement)"
            print(f"{n.event_type:<50} {n.since:<8} {n.sunset:<8} {repl}")
        return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _cmd_migration_roadmap(args: argparse.Namespace) -> int:
    """Implement the ``migration-roadmap`` sub-command."""
    try:
        from spanforge.migrate import v2_migration_roadmap  # noqa: PLC0415
    except ImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    roadmap = v2_migration_roadmap()
    if not roadmap:
        print("No migration records found.")
        return 0

    if getattr(args, "json", False):
        output = [
            {
                "event_type": r.event_type,
                "since": r.since,
                "sunset": r.sunset,
                "sunset_policy": r.sunset_policy.value,
                "replacement": r.replacement,
                "migration_notes": r.migration_notes,
                "field_renames": r.field_renames,
            }
            for r in roadmap
        ]
        print(json.dumps(output, indent=2))
        return 0

    print(f"v1 → v2 Migration Roadmap ({len(roadmap)} changes)\n")
    for r in roadmap:
        arrow = f" → {r.replacement}" if r.replacement else " (removed)"
        print(f"  [{r.since}→{r.sunset}] {r.event_type}{arrow}")
        if r.migration_notes:
            import textwrap  # noqa: PLC0415
            wrapped = textwrap.fill(r.migration_notes, width=72, initial_indent="    ", subsequent_indent="    ")  # noqa: E501
            print(wrapped)
        if r.field_renames:
            for old, new in r.field_renames.items():
                print(f"    field rename: {old!r} → {new!r}")
        print()
    return 0


def _cmd_check_consumers(_args: argparse.Namespace) -> int:
    """Implement the ``check-consumers`` sub-command."""
    from spanforge.consumer import get_registry  # noqa: PLC0415

    registry = get_registry()
    all_records = registry.all()
    if not all_records:
        print("No consumers registered.")
        return 0

    incompatible = registry.check_compatible()
    if not incompatible:
        print(f"OK — all {len(all_records)} consumer(s) are compatible.")
        return 0

    print(f"INCOMPATIBLE — {len(incompatible)} consumer(s) require a newer schema:\n")
    for tool_name, version in incompatible:
        print(f"  {tool_name!r} requires schema v{version}")
    return 1


def _read_jsonl_events(path: Path):  # noqa: ANN202
    """Read a JSONL file and return a list of (lineno, Event | Exception) pairs."""
    from spanforge.event import Event  # noqa: PLC0415
    from spanforge.exceptions import DeserializationError, SchemaValidationError  # noqa: PLC0415

    results = []
    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            event = Event.from_dict(obj)
            results.append((lineno, event))
        except (json.JSONDecodeError, DeserializationError, SchemaValidationError, KeyError, TypeError) as exc:  # noqa: E501
            results.append((lineno, exc))
    return results


def _cmd_validate(args: argparse.Namespace) -> int:
    """Implement the ``validate`` sub-command."""
    from spanforge.exceptions import SchemaValidationError  # noqa: PLC0415
    from spanforge.validate import validate_event  # noqa: PLC0415

    path = Path(args.file)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    rows = _read_jsonl_events(path)
    if not rows:
        print(_NO_EVENTS_MSG)
        return 0

    errors: list[tuple[int, str]] = []
    for lineno, item in rows:
        if isinstance(item, Exception):
            errors.append((lineno, f"parse error: {item}"))
            continue
        try:
            validate_event(item)
        except SchemaValidationError as exc:
            errors.append((lineno, str(exc)))

    total = len(rows)
    if not errors:
        print(f"OK — {total} event(s) passed schema validation.")
        return 0

    print(f"FAIL — {len(errors)} of {total} event(s) failed validation:\n")
    for lineno, msg in errors:
        print(f"  line {lineno}: {msg}")
    return 1


def _cmd_audit_chain(args: argparse.Namespace) -> int:  # noqa: PLR0911
    """Implement the ``audit-chain`` sub-command."""
    import os  # noqa: PLC0415

    from spanforge.signing import SigningError, verify_chain  # noqa: PLC0415

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

    rows = _read_jsonl_events(path)
    if not rows:
        print(_NO_EVENTS_MSG)
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
        print(f"OK — chain of {len(events)} event(s) is intact.")
        return 0

    print(f"FAIL — chain verification failed ({result.tampered_count} tampered event(s)):\n")
    if result.first_tampered:
        print(f"  first tampered event_id: {result.first_tampered}")
    if result.gaps:
        print(f"  linkage gaps ({len(result.gaps)}):")
        for gap_id in result.gaps:
            print(f"    {gap_id}")
    return 1


def _cmd_inspect(args: argparse.Namespace) -> int:
    """Implement the ``inspect`` sub-command."""
    path = Path(args.file)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    rows = _read_jsonl_events(path)
    target_id = args.event_id

    for _lineno, item in rows:
        if isinstance(item, Exception):
            continue
        if item.event_id == target_id:
            print(json.dumps(item.to_dict(), indent=2))
            return 0

    print(f"error: event_id {target_id!r} not found in {path}", file=sys.stderr)
    return 1


def _accumulate_stats(
    rows: list[tuple[int, Any]],
) -> tuple[dict[str, int], int, int, int, float, list[str], int]:
    """Aggregate token/cost/type counters from parsed event rows."""
    type_counts: dict[str, int] = {}
    prompt_tokens = 0
    completion_tokens = 0
    total_tokens = 0
    cost_usd = 0.0
    timestamps: list[str] = []
    parse_errors = 0
    for _lineno, item in rows:
        if isinstance(item, Exception):
            parse_errors += 1
            continue
        event_type = str(item.event_type) if item.event_type else "(unknown)"
        type_counts[event_type] = type_counts.get(event_type, 0) + 1
        payload = item.payload or {}
        prompt_tokens += int(payload.get("prompt_tokens") or 0)
        completion_tokens += int(payload.get("completion_tokens") or 0)
        total_tokens += int(payload.get("total_tokens") or 0)
        cost_usd += float(payload.get("cost_usd") or 0.0)
        if item.timestamp:
            timestamps.append(item.timestamp)
    return type_counts, prompt_tokens, completion_tokens, total_tokens, cost_usd, timestamps, parse_errors


def _cmd_stats(args: argparse.Namespace) -> int:
    """Implement the ``stats`` sub-command."""
    path = Path(args.file)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    rows = _read_jsonl_events(path)
    if not rows:
        print(_NO_EVENTS_MSG)
        return 0

    type_counts, prompt_tokens, completion_tokens, total_tokens, cost_usd, timestamps, parse_errors = _accumulate_stats(rows)  # noqa: E501

    total_events = len(rows) - parse_errors
    print(f"Events: {total_events}" + (f" ({parse_errors} parse error(s) skipped)" if parse_errors else ""))  # noqa: E501
    print()

    if type_counts:
        print(f"{'Event Type':<55} {'Count':>7}")
        print("-" * 65)
        for et, cnt in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f"  {et:<53} {cnt:>7}")
        print()

    print(f"Prompt tokens:     {prompt_tokens:>12,}")
    print(f"Completion tokens: {completion_tokens:>12,}")
    print(f"Total tokens:      {total_tokens:>12,}")
    print(f"Cost (USD):        {cost_usd:>12.6f}")
    print()

    if timestamps:
        ts_sorted = sorted(timestamps)
        print(f"Earliest: {ts_sorted[0]}")
        print(f"Latest:   {ts_sorted[-1]}")

    return 0


def _cmd_compliance_generate(args: argparse.Namespace) -> int:  # noqa: PLR0911
    """Implement ``spanforge compliance generate``."""
    from spanforge.core.compliance_mapping import (  # noqa: PLC0415
        ComplianceFramework,
        ComplianceMappingEngine,
    )

    # Resolve framework enum — accept both enum value ("EU AI Act") and YAML slug ("eu_ai_act")
    _FRAMEWORK_SLUG_MAP = {
        "eu_ai_act": "EU AI Act",
        "iso_42001": "ISO/IEC 42001",
        "nist_ai_rmf": "NIST AI RMF",
        "gdpr": "GDPR",
        "soc2": "SOC 2 Type II",
    }
    fw_map = {e.value: e for e in ComplianceFramework}
    # also index by slug
    for _slug, _val in _FRAMEWORK_SLUG_MAP.items():
        if _val in fw_map:
            fw_map[_slug] = fw_map[_val]
    framework_key = args.framework.lower()
    # try case-insensitive match against all keys
    matched = None
    for k, v in fw_map.items():
        if k.lower() == framework_key:
            matched = v
            break
    if matched is None:
        valid = ", ".join(sorted(_FRAMEWORK_SLUG_MAP.keys()))
        print(f"error: unknown framework {args.framework!r}. Valid slugs: {valid}", file=sys.stderr)
        return 2

    framework = matched

    # Optionally load audit events from a JSONL file
    audit_events: list[dict] = []
    if getattr(args, "events_file", None):
        events_path = Path(args.events_file)
        if not events_path.exists():
            print(f"error: events file not found: {events_path}", file=sys.stderr)
            return 2
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    audit_events.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    print(f"warning: skipping invalid JSON line in events file: {exc}", file=sys.stderr)

    engine = ComplianceMappingEngine()
    try:
        pkg = engine.generate_evidence_package(
            model_id=args.model_id,
            framework=framework,
            from_date=args.from_date,
            to_date=args.to_date,
            audit_events=audit_events or None,
        )
    except Exception as exc:
        print(f"error: evidence package generation failed: {exc}", file=sys.stderr)
        return 1

    # Write output files
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    safe_id = args.model_id.replace("/", "_")[:40]
    prefix = f"{framework_key}_{safe_id}_{args.from_date}_{args.to_date}"

    attestation_path = out_dir / f"{prefix}_attestation.json"
    attestation_path.write_text(pkg.attestation.to_json(), encoding="utf-8")
    print(f"[✓] Attestation  → {attestation_path}")

    report_path = out_dir / f"{prefix}_report.txt"
    report_path.write_text(pkg.report_text, encoding="utf-8")
    print(f"[✓] Report       → {report_path}")

    if pkg.gap_report.has_gaps:
        gap_data = {
            "model_id": pkg.gap_report.model_id,
            "framework": pkg.gap_report.framework,
            "period_from": pkg.gap_report.period_from,
            "period_to": pkg.gap_report.period_to,
            "generated_at": pkg.gap_report.generated_at,
            "gap_clause_ids": pkg.gap_report.gap_clause_ids,
            "partial_clause_ids": pkg.gap_report.partial_clause_ids,
        }
        gap_path = out_dir / f"{prefix}_gap_report.json"
        gap_path.write_text(json.dumps(gap_data, indent=2), encoding="utf-8")
        print(f"[✓] Gap report   → {gap_path}")
    else:
        print("[✓] No compliance gaps found")

    if pkg.audit_exports:
        exports_dir = out_dir / "exports"
        exports_dir.mkdir(exist_ok=True)
        for clause_id, events in pkg.audit_exports.items():
            safe_clause = clause_id.replace("/", "_").replace(".", "_")
            clause_path = exports_dir / f"{safe_clause}.jsonl"
            clause_path.write_text(
                "\n".join(json.dumps(e) for e in events), encoding="utf-8"
            )
        print(f"[✓] Clause exports → {exports_dir}/ ({len(pkg.audit_exports)} clause(s))")

    print(f"\nOverall status: {pkg.attestation.overall_status.value}")
    return 0


def _attestation_from_dict(data: dict) -> "object":  # noqa: ANN001
    """Reconstruct a ComplianceAttestation from its to_dict() output."""
    from spanforge.core.compliance_mapping import (  # noqa: PLC0415
        ClauseStatus,
        ComplianceAttestation,
        EvidenceRecord,
    )

    period = data.get("period", {})
    clauses = [
        EvidenceRecord(
            clause_id=c["clause_id"],
            status=ClauseStatus(c["status"]),
            evidence_count=c.get("evidence_count", 0),
            audit_ids=c.get("audit_ids", []),
            summary=c.get("summary", ""),
        )
        for c in data.get("clauses", [])
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


def _cmd_compliance_validate_attestation(args: argparse.Namespace) -> int:
    """Implement ``spanforge compliance validate-attestation``."""
    from spanforge.core.compliance_mapping import verify_attestation_signature  # noqa: PLC0415

    att_path = Path(args.attestation_file)
    if not att_path.exists():
        print(f"error: file not found: {att_path}", file=sys.stderr)
        return 2

    try:
        data = json.loads(att_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in {att_path}: {exc}", file=sys.stderr)
        return 2

    try:
        attestation = _attestation_from_dict(data)
    except (KeyError, ValueError) as exc:
        print(f"error: could not parse attestation: {exc}", file=sys.stderr)
        return 2

    valid = verify_attestation_signature(attestation)
    if valid:
        print(f"[✓] Attestation signature is valid  model_id={data.get('model_id')!r}")
        return 0
    print(f"[✗] Attestation signature is INVALID  model_id={data.get('model_id')!r}", file=sys.stderr)
    return 1


def _cmd_compliance_report(args: argparse.Namespace) -> int:  # noqa: PLR0911
    """Implement ``spanforge compliance report`` — JSON/PDF report with attestation."""
    from spanforge.core.compliance_mapping import (  # noqa: PLC0415
        ComplianceFramework,
        ComplianceMappingEngine,
    )

    _FRAMEWORK_SLUG_MAP = {
        "eu_ai_act": "EU AI Act",
        "iso_42001": "ISO/IEC 42001",
        "nist_ai_rmf": "NIST AI RMF",
        "gdpr": "GDPR",
        "soc2": "SOC 2 Type II",
        "hipaa": "HIPAA",
    }
    fw_map = {e.value: e for e in ComplianceFramework}
    for _slug, _val in _FRAMEWORK_SLUG_MAP.items():
        if _val in fw_map:
            fw_map[_slug] = fw_map[_val]
    framework_key = args.framework.lower()
    matched = None
    for k, v in fw_map.items():
        if k.lower() == framework_key:
            matched = v
            break
    if matched is None:
        valid = ", ".join(sorted(_FRAMEWORK_SLUG_MAP.keys()))
        print(f"error: unknown framework {args.framework!r}. Valid slugs: {valid}", file=sys.stderr)
        return 2

    audit_events: list[dict] = []
    if getattr(args, "events_file", None):
        events_path = Path(args.events_file)
        if not events_path.exists():
            print(f"error: events file not found: {events_path}", file=sys.stderr)
            return 2
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    audit_events.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    print(f"warning: skipping invalid JSON line: {exc}", file=sys.stderr)

    engine = ComplianceMappingEngine()
    try:
        pkg = engine.generate_evidence_package(
            model_id=args.model_id,
            framework=matched,
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
        json_path.write_text(pkg.to_json(), encoding="utf-8")
        print(f"[✓] JSON report → {json_path}")

    if fmt in ("pdf", "both"):
        pdf_path = out_dir / f"{prefix}_report.pdf"
        try:
            pkg.to_pdf(str(pdf_path))
            print(f"[✓] PDF report  → {pdf_path}")
        except ImportError:
            print("error: PDF generation requires reportlab. Install: pip install spanforge[compliance]",
                  file=sys.stderr)
            return 1

    overall = pkg.attestation.overall_status.value
    print(f"\nOverall status: {overall.upper()}")
    return 0 if overall == "pass" else 1


def _cmd_compliance_check(args: argparse.Namespace) -> int:
    """Implement ``spanforge compliance check`` — CI-friendly exit-code gate."""
    from spanforge.core.compliance_mapping import ComplianceMappingEngine  # noqa: PLC0415

    audit_events: list[dict] = []
    if getattr(args, "events_file", None):
        events_path = Path(args.events_file)
        if not events_path.exists():
            print(f"error: events file not found: {events_path}", file=sys.stderr)
            return 2
        for line in events_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    audit_events.append(json.loads(line))
                except json.JSONDecodeError as exc:
                    print(f"warning: skipping invalid JSON line in events file: {exc}", file=sys.stderr)

    engine = ComplianceMappingEngine()
    try:
        pkg = engine.generate_evidence_package(
            model_id=args.model_id,
            framework=args.framework,
            from_date=args.from_date,
            to_date=args.to_date,
            audit_events=audit_events or None,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # noqa: BLE001
        print(f"error: compliance check failed: {exc}", file=sys.stderr)
        return 1

    allow_partial = getattr(args, "allow_partial", False)
    gap = pkg.gap_report
    overall = pkg.attestation.overall_status.value

    # Print concise per-clause summary
    for rec in pkg.attestation.clauses:
        icon = {"pass": "[✓]", "fail": "[✗]", "partial": "[~]"}.get(rec.status.value, "[?]")
        print(f"  {icon} {rec.clause_id:<20} {rec.status.value:<8}  {rec.evidence_count} events")

    print(f"\nOverall: {overall.upper()}")

    if gap.gap_clause_ids:
        print(f"Gaps    : {', '.join(gap.gap_clause_ids)}")
    if gap.partial_clause_ids:
        print(f"Partial : {', '.join(gap.partial_clause_ids)}")

    # Exit code logic
    if gap.has_gaps:
        if not allow_partial or gap.gap_clause_ids:
            print("\n[FAIL] Compliance check failed — fix gaps before deploying.", file=sys.stderr)
            return 1
    print("\n[PASS] Compliance check passed.")
    return 0


def _load_cost_brief_store_json(store_path: Path) -> dict:
    """Load or initialise a JSON-file-backed cost brief store."""
    if store_path.exists():
        try:
            return json.loads(store_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _cmd_cost_brief_submit(args: argparse.Namespace) -> int:
    """Implement ``spanforge cost brief submit``."""
    brief_path = Path(args.file)
    if not brief_path.exists():
        print(f"error: file not found: {brief_path}", file=sys.stderr)
        return 2

    try:
        brief_data = json.loads(brief_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"error: invalid JSON in {brief_path}: {exc}", file=sys.stderr)
        return 2

    # Validate required fields
    required = {"model_id", "submitted_by", "resource_config", "scenarios"}
    missing = required - set(brief_data.keys())
    if missing:
        print(f"error: cost brief missing required fields: {', '.join(sorted(missing))}", file=sys.stderr)
        return 2

    store_path = Path(args.store)
    store = _load_cost_brief_store_json(store_path)
    from datetime import datetime, timezone  # noqa: PLC0415
    store[brief_data["model_id"]] = {
        **brief_data,
        "stored_at": datetime.now(timezone.utc).isoformat(),
    }
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(store, indent=2), encoding="utf-8")

    print(f"[✓] Cost brief submitted  model_id={brief_data['model_id']!r}  store={store_path}")
    return 0


def _cmd_dev(args: argparse.Namespace) -> int:
    """Implement ``spanforge dev <action>``."""
    from spanforge.core.dx import DevCLI  # noqa: PLC0415

    action = getattr(args, "dev_command", None)
    if action is None:
        print("error: specify a dev sub-command: start, stop, reset, logs, status", file=sys.stderr)
        return 2

    cli = DevCLI()
    if action == "start":
        service = getattr(args, "service", "spanforge-dev")
        cli.start(service)
        print(f"[✓] Dev environment started  service={service!r}")
    elif action == "stop":
        cli.stop()
        print("[✓] Dev environment stopped (no buffered spans)")
    elif action == "reset":
        cli.reset()
        print("[✓] Dev environment reset")
    elif action == "logs":
        entries = cli.logs()
        if not entries:
            print("(no log entries for this session)")
        else:
            for line in entries:
                print(line)
    elif action == "status":
        status = cli.status()
        print(json.dumps(status, indent=2))
    else:
        print(f"error: unknown dev sub-command: {action!r}", file=sys.stderr)
        return 2
    return 0


def _cmd_module_create(args: argparse.Namespace) -> int:
    """Implement ``spanforge module create``."""
    from spanforge.core.dx import ModuleCLI  # noqa: PLC0415

    base_dir = Path(getattr(args, "output_dir", ".") or ".")
    cli = ModuleCLI()
    try:
        scaffolded = cli.scaffold(
            module_name=args.name,
            trust_level=getattr(args, "trust_level", "UNTRUSTED"),
            author=getattr(args, "author", "unknown"),
            base_dir=base_dir,
        )
    except Exception as exc:
        print(f"error: scaffolding failed: {exc}", file=sys.stderr)
        return 1

    # Write generated files to disk
    root = scaffolded.root_dir
    root.mkdir(parents=True, exist_ok=True)
    for rel_path, content in scaffolded.files.items():
        file_path = root / rel_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        print(f"[✓] {file_path}")

    print(f"\nModule {args.name!r} created at {root}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    """Implement ``spanforge serve`` — start a local trace viewer."""
    import signal  # noqa: PLC0415
    from spanforge._server import TraceViewerServer  # noqa: PLC0415

    port: int = getattr(args, "port", 8888)
    host: str = getattr(args, "host", "127.0.0.1")
    jsonl_file: str | None = getattr(args, "file", None)

    # Pre-load a JSONL file if provided.
    if jsonl_file:
        try:
            import json  # noqa: PLC0415
            from spanforge._store import get_store  # noqa: PLC0415
            from spanforge.event import Event  # noqa: PLC0415
            store = get_store()
            loaded = 0
            with open(jsonl_file, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    raw = json.loads(line)
                    try:
                        evt = Event.from_dict(raw)
                        store.record(evt)
                        loaded += 1
                    except Exception:  # NOSONAR
                        pass
            print(f"[spanforge] Loaded {loaded} events from {jsonl_file!r}")
        except FileNotFoundError:
            print(f"error: file not found: {jsonl_file!r}", file=sys.stderr)
            return 1
        except Exception as exc:
            print(f"error: could not load file: {exc}", file=sys.stderr)
            return 1

    server = TraceViewerServer(port=port, host=host)
    server.start()
    print(f"[spanforge] Serving traces at http://{host}:{port}/traces")
    print("[spanforge] Press Ctrl+C to stop.")

    # Block until SIGINT / SIGTERM.
    stop_event = threading.Event()

    def _handle_signal(sig: int, frame: object) -> None:  # noqa: ARG001
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    try:
        signal.signal(signal.SIGTERM, _handle_signal)
    except (OSError, ValueError):
        pass  # SIGTERM not available on Windows in some contexts

    stop_event.wait()
    server.stop()
    return 0


# ---------------------------------------------------------------------------
# New Phase B sub-commands: init, quickstart, report, ui
# ---------------------------------------------------------------------------

_SPANFORGE_TOML_TEMPLATE = """\
# spanforge.toml — project-level spanforge configuration
# Generated by: spanforge init
# Reference: https://www.getspanforge.com/docs/configuration

[spanforge]
service_name   = "{service_name}"
env            = "development"     # development | staging | production
exporter       = "console"         # console | jsonl | otlp | webhook | datadog | grafana_loki

# Uncomment to write events to a local JSONL file:
# endpoint = "events.jsonl"

# Uncomment to enable HMAC audit-chain signing:
# signing_key = ""  # base64-encoded 32-byte key; set via SPANFORGE_SIGNING_KEY env var

# PII redaction — enabled by default in production:
[spanforge.redaction]
enabled = true

# Sampling:
[spanforge.sampling]
rate                 = 1.0   # 1.0 = emit all events; 0.1 = 10 % sample
always_sample_errors = true
"""

_EXAMPLE_PY_TEMPLATE = '''\
"""Example: tracing an LLM call with spanforge.

Run:  python examples/trace_llm.py
"""

import spanforge

spanforge.configure(exporter="console", service_name="{service_name}")

with spanforge.span("call-llm") as span:
    span.set_model(model="gpt-4o", system="openai")
    # --- replace with your real LLM call ---
    result = {{"role": "assistant", "content": "Hello, world!"}}
    # ---------------------------------------
    span.set_token_usage(input=10, output=8, total=18)
    span.set_status("ok")

print("Event emitted. Check above output for the JSON envelope.")
'''


def _cmd_init(args: argparse.Namespace) -> int:
    """Implement the ``init`` sub-command — scaffold spanforge.toml in current dir."""
    import os  # noqa: PLC0415

    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    toml_path = out_dir / "spanforge.toml"
    if toml_path.exists() and not args.force:
        print(f"[!] {toml_path} already exists. Use --force to overwrite.", file=sys.stderr)
        return 1

    service_name = args.service_name or Path(os.getcwd()).name or "my-service"
    toml_path.write_text(
        _SPANFORGE_TOML_TEMPLATE.format(service_name=service_name), encoding="utf-8"
    )
    print(f"[OK] Created {toml_path}")

    examples_dir = out_dir / "examples"
    examples_dir.mkdir(exist_ok=True)
    ex_path = examples_dir / "trace_llm.py"
    if not ex_path.exists():
        ex_path.write_text(
            _EXAMPLE_PY_TEMPLATE.format(service_name=service_name), encoding="utf-8"
        )
        print(f"[OK] Created {ex_path}")

    print("\nNext steps:")
    print(f"  1. Edit {toml_path} to configure your exporter.")
    print("  2. Run: python examples/trace_llm.py")
    print("  3. Run: spanforge check")
    return 0


def _cmd_quickstart(_args: argparse.Namespace) -> int:
    """Implement the ``quickstart`` sub-command — interactive setup wizard."""
    print("spanforge quickstart wizard")
    print("=" * 40)
    print("This wizard will configure spanforge for your project.\n")

    try:
        service_name = input("Service name [my-service]: ").strip() or "my-service"
        env = (
            input("Environment (development/staging/production) [development]: ").strip()
            or "development"
        )
        exporter = (
            input("Exporter (console/jsonl/otlp/datadog) [console]: ").strip() or "console"
        )
        endpoint = ""
        if exporter == "jsonl":
            endpoint = input("JSONL output path [events.jsonl]: ").strip() or "events.jsonl"
        elif exporter in ("otlp", "datadog"):
            endpoint = input("Endpoint URL: ").strip()
        enable_signing = input("Enable HMAC signing? (y/N): ").strip().lower() in ("y", "yes")
    except (KeyboardInterrupt, EOFError):
        print("\nAborted.", file=sys.stderr)
        return 1

    lines = [
        "# spanforge.toml — generated by spanforge quickstart",
        "[spanforge]",
        f'service_name = "{service_name}"',
        f'env          = "{env}"',
        f'exporter     = "{exporter}"',
    ]
    if endpoint:
        lines.append(f'endpoint     = "{endpoint}"')
    if enable_signing:
        lines.append("# signing_key = \"\"  # export SPANFORGE_SIGNING_KEY=<key>")
    Path("spanforge.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("[OK] Wrote spanforge.toml")

    print("\nRunning health check ...")
    import importlib  # noqa: PLC0415

    try:
        sf = importlib.import_module("spanforge")
        sf.configure(exporter=exporter, service_name=service_name, env=env)
        with sf.span("quickstart-test") as span:
            span.set_status("ok")
        print("[OK] Test event emitted successfully!")
    except Exception as exc:  # noqa: BLE001
        print(f"[!] Health check failed: {exc}", file=sys.stderr)

    print("\nSetup complete. Run 'spanforge check' any time to verify your pipeline.")
    return 0


def _cmd_report(args: argparse.Namespace) -> int:
    """Implement the ``report`` sub-command — generate a static HTML trace report."""
    src = Path(args.file)
    if not src.exists():
        print(f"[x] File not found: {src}", file=sys.stderr)
        return 1

    out_path = Path(args.output)
    events: list[dict] = []
    with src.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError as exc:
                print(f"[!] Line {lineno}: {exc}", file=sys.stderr)

    if not events:
        print(_NO_EVENTS_MSG)
        return 0

    rows: list[str] = []
    for ev in events:
        ts = ev.get("timestamp", "")[:19]
        ns = ev.get("namespace", "")
        eid = ev.get("event_id", "")[:8]
        svc = ev.get("service_name", "")
        payload_str = json.dumps(ev.get("payload", {}), separators=(",", ":"))[:120]
        rows.append(
            f"<tr><td>{ts}</td><td><code>{ns}</code></td>"
            f"<td><code>{eid}</code></td><td>{svc}</td>"
            f"<td><pre style='margin:0;font-size:11px'>{payload_str}</pre></td></tr>"
        )

    html = (
        "<!DOCTYPE html>\n<html lang='en'>\n<head>\n"
        "  <meta charset='utf-8'/>\n"
        f"  <title>spanforge report \u2014 {src.name}</title>\n"
        "  <style>\n"
        "    body{font-family:system-ui,sans-serif;padding:1rem 2rem}\n"
        "    h1{font-size:1.3rem;color:#333}\n"
        "    table{border-collapse:collapse;width:100%;font-size:13px}\n"
        "    th,td{border:1px solid #ddd;padding:6px 8px;text-align:left;vertical-align:top}\n"
        "    th{background:#f4f4f4}\n"
        "    tr:nth-child(even){background:#fafafa}\n"
        "  </style>\n</head>\n<body>\n"
        "  <h1>spanforge \u2014 Trace Report</h1>\n"
        f"  <p>Source: <code>{src}</code> &nbsp;|&nbsp; Events: <strong>{len(events)}</strong></p>\n"
        "  <table>\n    <thead>\n"
        "      <tr><th>Timestamp</th><th>Namespace</th><th>Event ID</th>"
        "<th>Service</th><th>Payload</th></tr>\n"
        "    </thead>\n    <tbody>\n"
        + "".join(f"      {r}\n" for r in rows)
        + "    </tbody>\n  </table>\n</body>\n</html>"
    )

    out_path.write_text(html, encoding="utf-8")
    print(f"[OK] Report written to {out_path}  ({len(events)} events)")
    return 0


def _cmd_ui(args: argparse.Namespace) -> int:
    """Implement the ``ui`` sub-command — serve the interactive SPA trace viewer."""
    import signal  # noqa: PLC0415
    import webbrowser  # noqa: PLC0415

    from spanforge._server import TraceViewerServer  # noqa: PLC0415

    port = args.port

    if args.file:
        src = Path(args.file)
        if not src.exists():
            print(f"[x] File not found: {src}", file=sys.stderr)
            return 1
        from spanforge._store import get_store  # noqa: PLC0415
        from spanforge.event import Event  # noqa: PLC0415

        store = get_store()
        loaded = 0
        with src.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    store.record(Event.from_dict(json.loads(line)))
                    loaded += 1
                except Exception:  # noqa: BLE001
                    pass
        print(f"[spanforge] Loaded {loaded} events from {str(src)!r}")

    server = TraceViewerServer(port=port, host="127.0.0.1")
    server.start()
    url = f"http://127.0.0.1:{port}/"
    print(f"[spanforge] Trace viewer running at {url}")
    print("[spanforge] Press Ctrl+C to stop.")

    if not args.no_browser:
        webbrowser.open(url)

    stop_evt = threading.Event()

    def _handle_sig(*_: object) -> None:
        stop_evt.set()

    signal.signal(signal.SIGINT, _handle_sig)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_sig)

    stop_evt.wait()
    server.stop()
    print("\n[spanforge] Stopped.")
    return 0


def _cmd_audit_erase(args: argparse.Namespace) -> int:
    """Implement ``spanforge audit erase`` — GDPR subject erasure on a JSONL file."""
    import os  # noqa: PLC0415

    from spanforge.signing import AuditStream, verify_chain  # noqa: PLC0415

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

    # Prevent accidental overwrite of the input file
    out_path = Path(args.output) if args.output else path.with_suffix(".erased.jsonl")
    if out_path.resolve() == path.resolve():
        print(
            "error: --output must differ from input file to prevent overwrite",
            file=sys.stderr,
        )
        return 2

    rows = _read_jsonl_events(path)
    if not rows:
        print(_NO_EVENTS_MSG)
        return 0

    bad_lines = [(ln, exc) for ln, exc in rows if isinstance(exc, Exception)]
    if bad_lines:
        print(f"error: {len(bad_lines)} line(s) could not be parsed:", file=sys.stderr)
        for ln, exc in bad_lines[:5]:
            print(f"  line {ln}: {exc}", file=sys.stderr)
        return 2

    events = [ev for _, ev in rows]

    stream = AuditStream(org_secret=org_secret, source="spanforge-cli@1.0.0")
    # Load events into stream
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

    # Pre-verify: ensure chain is still valid before writing
    chain_result = verify_chain(list(stream.events), org_secret)
    if not chain_result.valid:
        print(
            "error: chain verification failed after erasure — aborting write",
            file=sys.stderr,
        )
        return 2

    # Write the updated chain back to the output file
    with out_path.open("w", encoding="utf-8") as fh:
        for evt in stream.events:
            fh.write(evt.to_json())
            fh.write("\n")

    print(f"[✓] Erased {len(tombstones)} event(s) mentioning {subject_id!r}")
    print(f"[✓] Updated chain written to {out_path}")
    return 0


def _cmd_scan(args: argparse.Namespace) -> int:
    """Implement ``spanforge scan`` — deep PII scan on a JSONL file."""
    from spanforge.redact import scan_payload  # noqa: PLC0415

    path = Path(args.file)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    rows = _read_jsonl_events(path)
    if not rows:
        print(_NO_EVENTS_MSG)
        return 0

    # GA-03-D: --types filter
    type_filter: set[str] | None = None
    raw_types = getattr(args, "types", None)
    if raw_types:
        type_filter = {t.strip().lower() for t in raw_types.split(",")}

    all_hits: list[dict[str, str]] = []
    total_scanned = 0

    for idx, row in enumerate(rows):
        if isinstance(row[1], Exception):
            continue
        event = row[1]
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            continue
        result = scan_payload(payload)
        total_scanned += result.scanned
        for hit in result.hits:
            if type_filter and hit.pii_type.lower() not in type_filter:
                continue
            all_hits.append({
                "event_index": str(idx),
                "event_id": getattr(event, "event_id", "unknown"),
                "pii_type": hit.pii_type,
                "path": hit.path,
                "match_count": str(hit.match_count),
                "sensitivity": hit.sensitivity,
            })

    fmt = getattr(args, "format", "text")
    if fmt == "json":
        import json as _json  # noqa: PLC0415
        print(_json.dumps({
            "file": str(path),
            "events_scanned": len(rows),
            "strings_scanned": total_scanned,
            "pii_hits": len(all_hits),
            "hits": all_hits,
        }, indent=2))
    else:
        print(f"Scanned {len(rows)} events ({total_scanned} string values)")
        if not all_hits:
            print("[✓] No PII detected.")
        else:
            print(f"[!] Found {len(all_hits)} PII hit(s):\n")
            for h in all_hits:
                print(f"  event #{h['event_index']} ({h['event_id']})  "
                      f"{h['pii_type']:20s} path={h['path']}  "
                      f"matches={h['match_count']}  sensitivity={h['sensitivity']}")

    # GA-03-D: --fail-on-match returns 1 on any hit
    fail_on_match = getattr(args, "fail_on_match", False)
    if fail_on_match and all_hits:
        return 1
    return 1 if all_hits else 0


def _cmd_migrate(args: argparse.Namespace) -> int:
    """Implement ``spanforge migrate`` — schema v1→v2 migration."""
    import os  # noqa: PLC0415

    from spanforge.migrate import migrate_file  # noqa: PLC0415

    path = Path(args.file)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    output = getattr(args, "output", None)
    target_version = getattr(args, "target_version", "2.0")
    dry_run = getattr(args, "dry_run", False)

    # GA-05-C: --sign reads SPANFORGE_SIGNING_KEY for chain re-signing
    org_secret: str | None = None
    if getattr(args, "sign", False):
        org_secret = os.environ.get("SPANFORGE_SIGNING_KEY", "")
        if not org_secret:
            print("error: --sign requires SPANFORGE_SIGNING_KEY", file=sys.stderr)
            return 2

    stats = migrate_file(
        path,
        output=output,
        org_secret=org_secret,
        target_version=target_version,
        dry_run=dry_run,
    )

    print(f"Total events:     {stats.total}")
    print(f"Migrated (v1→v2): {stats.migrated}")
    print(f"Skipped (v2):     {stats.skipped}")
    print(f"Errors:           {stats.errors}")
    if stats.warnings:
        print(f"Warnings:         {len(stats.warnings)}")
        for w in stats.warnings:
            print(f"  - {w}")
    if stats.transformed_fields:
        print("Transformations:")
        for k, v in stats.transformed_fields.items():
            print(f"  {k}: {v}")
    if dry_run:
        print("(dry run — no files written)")
    else:
        print(f"Output:           {stats.output_path}")
    return 1 if stats.errors > 0 else 0


def _cmd_audit_check_health(args: argparse.Namespace) -> int:
    """Implement ``spanforge audit check-health``."""
    import os  # noqa: PLC0415

    from spanforge.redact import scan_payload  # noqa: PLC0415
    from spanforge.signing import (  # noqa: PLC0415
        AuditStream,
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

    # 1. File readable
    checks.append({"name": "file_readable", "status": "pass", "detail": str(path)})

    # 2. Parse events
    rows = _read_jsonl_events(path)
    if not rows:
        checks.append({"name": "parse_events", "status": "skip", "detail": "File is empty"})
        if output_fmt == "json":
            import json as _json  # noqa: PLC0415
            print(_json.dumps({"file": str(path), "checks": checks, "result": "pass"}, indent=2))
        else:
            print(f"Health check: {path}\n")
            print("[✓] File exists and is readable")
            print("[!] File is empty — no events to check")
        return 0

    bad_lines = [(ln, exc) for ln, exc in rows if isinstance(exc, Exception)]
    events = [ev for _, ev in rows if not isinstance(ev, Exception)]

    parse_status = "pass" if not bad_lines else "fail"
    if bad_lines:
        all_ok = False
    checks.append({
        "name": "parse_events",
        "status": parse_status,
        "detail": f"{len(events)} parsed, {len(bad_lines)} error(s)",
    })

    # 3. Chain integrity
    org_secret = os.environ.get("SPANFORGE_SIGNING_KEY", "")
    if org_secret and events:
        result = verify_chain(events, org_secret)
        if result.valid:
            checks.append({
                "name": "chain_integrity",
                "status": "pass",
                "detail": f"{len(events)} events verified",
            })
        else:
            all_ok = False
            checks.append({
                "name": "chain_integrity",
                "status": "fail",
                "detail": f"{result.tampered_count} tampered, {len(result.gaps)} gap(s)",
            })
    else:
        checks.append({
            "name": "chain_integrity",
            "status": "skip",
            "detail": "SPANFORGE_SIGNING_KEY not set",
        })

    # 4. Key strength
    if org_secret:
        warnings = validate_key_strength(org_secret)
        if warnings:
            all_ok = False
            checks.append({
                "name": "key_strength",
                "status": "fail",
                "detail": "; ".join(warnings),
            })
        else:
            checks.append({"name": "key_strength", "status": "pass", "detail": "OK"})
    else:
        checks.append({
            "name": "key_strength",
            "status": "skip",
            "detail": "No key to check",
        })

    # 5. Key expiry
    expires_at = os.environ.get("SPANFORGE_SIGNING_KEY_EXPIRES_AT", "")
    if expires_at:
        status, days = check_key_expiry(expires_at)
        if status == "expired":
            all_ok = False
            checks.append({
                "name": "key_expiry",
                "status": "fail",
                "detail": f"EXPIRED {days} day(s) ago",
            })
        elif status == "expiring_soon":
            all_ok = False
            checks.append({
                "name": "key_expiry",
                "status": "fail",
                "detail": f"expiring in {days} day(s)",
            })
        else:
            checks.append({
                "name": "key_expiry",
                "status": "pass",
                "detail": f"valid for {days} day(s)",
            })
    else:
        checks.append({
            "name": "key_expiry",
            "status": "skip",
            "detail": "SPANFORGE_SIGNING_KEY_EXPIRES_AT not set",
        })

    # 6. GA-08-B: PII scan
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
        checks.append({
            "name": "pii_scan",
            "status": "fail",
            "detail": f"{pii_hit_count} PII hit(s) detected",
        })
    else:
        checks.append({"name": "pii_scan", "status": "pass", "detail": "No PII detected"})

    # 7. GA-08-B: Egress config check
    from spanforge.config import get_config  # noqa: PLC0415
    try:
        cfg = get_config()
        if cfg.exporter:
            checks.append({
                "name": "egress_config",
                "status": "pass",
                "detail": f"exporter={cfg.exporter!r}",
            })
        else:
            checks.append({
                "name": "egress_config",
                "status": "skip",
                "detail": "No exporter configured",
            })
    except Exception as exc:
        all_ok = False
        checks.append({
            "name": "egress_config",
            "status": "fail",
            "detail": str(exc),
        })

    # Output
    if output_fmt == "json":
        import json as _json  # noqa: PLC0415
        print(_json.dumps({
            "file": str(path),
            "events": len(events),
            "errors": len(bad_lines),
            "checks": checks,
            "result": "pass" if all_ok else "fail",
        }, indent=2))
    else:
        print(f"Health check: {path}\n")
        for c in checks:
            icon = {"pass": "✓", "fail": "!", "skip": "–"}.get(c["status"], "?")  # type: ignore[arg-type]
            print(f"[{icon}] {c['name']}: {c['detail']}")
        print(f"\nTotal: {len(events)} events, {len(bad_lines)} errors")
        print(f"Result: {'PASS' if all_ok else 'FAIL'}")

    # GA-08-B: return 1 on ANY check failure
    return 0 if all_ok else 1


def _cmd_audit_verify(args: argparse.Namespace) -> int:
    """Implement ``spanforge audit verify``."""
    import glob as _glob  # noqa: PLC0415
    import os  # noqa: PLC0415

    from spanforge.signing import verify_chain  # noqa: PLC0415

    org_secret = args.key or os.environ.get("SPANFORGE_SIGNING_KEY", "")
    if not org_secret:
        print(
            "error: no signing key — pass --key or set SPANFORGE_SIGNING_KEY",
            file=sys.stderr,
        )
        return 2

    # Expand glob pattern
    matched = sorted(_glob.glob(args.input, recursive=True))
    if not matched:
        print(f"error: no files matched: {args.input}", file=sys.stderr)
        return 2

    all_events = []
    parse_errors = 0
    for fpath in matched:
        rows = _read_jsonl_events(Path(fpath))
        for _ln, item in rows:
            if isinstance(item, Exception):
                parse_errors += 1
            else:
                all_events.append(item)

    if not all_events:
        print("error: no events found in matched files", file=sys.stderr)
        return 2

    result = verify_chain(all_events, org_secret)

    # Report
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
    else:
        print("\nResult: FAIL")
        return 1


def _cmd_audit_rotate_key(args: argparse.Namespace) -> int:
    """Implement ``spanforge audit rotate-key``."""
    import os  # noqa: PLC0415

    from spanforge.signing import AuditStream, verify_chain  # noqa: PLC0415

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

    rows = _read_jsonl_events(path)
    if not rows:
        print(_NO_EVENTS_MSG)
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

    # GA-01-C: default output must differ from input
    explicit_output = getattr(args, "output", None)
    if explicit_output:
        out_path = Path(explicit_output)
    else:
        out_path = path.with_suffix(".rotated.jsonl")

    with out_path.open("w", encoding="utf-8") as fh:
        for evt in stream.events:
            fh.write(evt.to_json())
            fh.write("\n")

    print(f"[✓] Key rotated — chain rewritten to {out_path}")

    # GA-01-C: re-verify the rotated chain with the new key
    rotated_events = stream.events
    vr = verify_chain(rotated_events, new_secret)
    if vr.valid:
        print(f"[✓] Re-verification: chain valid ({len(rotated_events)} events)")
    else:
        print(f"[!] Re-verification: FAILED — {vr.tampered_count} tampered, {len(vr.gaps)} gap(s)")
        return 1

    print(f"[✓] Update SPANFORGE_SIGNING_KEY to the value of {new_key_env}")
    return 0


def main(argv: list[str] | None = None) -> NoReturn:
    """Entry point for the ``spanforge`` CLI tool."""
    from spanforge import CONFORMANCE_PROFILE, __version__  # noqa: PLC0415
    parser = argparse.ArgumentParser(
        prog="spanforge",
        description="spanforge command-line utilities",
    )
    parser.add_argument(
        "-V", "--version",
        action="version",
        version=f"spanforge {__version__} [{CONFORMANCE_PROFILE}]",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # check sub-command (health check)
    sub.add_parser(
        "check",
        help="End-to-end health check: validates config, emits a test event, confirms export pipeline",
    )

    # check-compat sub-command
    compat_parser = sub.add_parser(
        "check-compat",
        help="Check a JSON file of events against the v1.0 compatibility checklist",
    )
    compat_parser.add_argument(
        "file",
        metavar="EVENTS_JSON",
        help="Path to a JSON file containing a list of serialised events",
    )

    # list-deprecated sub-command
    sub.add_parser(
        "list-deprecated",
        help="Print all deprecated event types from the global deprecation registry",
    )

    # migration-roadmap sub-command
    roadmap_parser = sub.add_parser(
        "migration-roadmap",
        help="Print the planned v1 → v2 migration roadmap",
    )
    roadmap_parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Emit JSON output for machine consumption",
    )

    # check-consumers sub-command
    sub.add_parser(
        "check-consumers",
        help="Assert all registered consumers are compatible with the installed schema",
    )

    # validate sub-command
    validate_parser = sub.add_parser(
        "validate",
        help="Validate every event in a JSONL file against the published schema",
    )
    validate_parser.add_argument(
        "file",
        metavar="EVENTS_JSONL",
        help="Path to a JSONL file (one event JSON per line)",
    )

    # audit-chain sub-command
    audit_parser = sub.add_parser(
        "audit-chain",
        help="Verify HMAC signing chain integrity of events in a JSONL file",
    )
    audit_parser.add_argument(
        "file",
        metavar="EVENTS_JSONL",
        help="Path to a JSONL file of signed events (reads SPANFORGE_SIGNING_KEY env var)",
    )

    # audit command group (erase, check-health)
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
        "file", metavar="EVENTS_JSONL",
        help="Path to the JSONL audit file",
    )
    erase_parser.add_argument(
        "--subject-id", dest="subject_id", required=True,
        help="The data-subject identifier to erase",
    )
    erase_parser.add_argument(
        "--erased-by", dest="erased_by", default="cli",
        help="Identity of the operator performing erasure (default: cli)",
    )
    erase_parser.add_argument(
        "--reason", default="GDPR Art.17 right to erasure",
        help="Reason for erasure (default: 'GDPR Art.17 right to erasure')",
    )
    erase_parser.add_argument(
        "--request-ref", dest="request_ref", default="",
        help="External erasure request reference (e.g. ticket ID)",
    )
    erase_parser.add_argument(
        "--output", default=None, metavar="FILE",
        help="Output file (required — must differ from input to prevent accidental overwrite)",
    )

    rotate_key_parser = audit_sub.add_parser(
        "rotate-key",
        help="Rotate the signing key in a JSONL audit file",
    )
    rotate_key_parser.add_argument(
        "file", metavar="EVENTS_JSONL",
        help="Path to the JSONL audit file",
    )
    rotate_key_parser.add_argument(
        "--new-key-env", dest="new_key_env", default="SPANFORGE_NEW_SIGNING_KEY",
        help="Environment variable holding the new signing key (default: SPANFORGE_NEW_SIGNING_KEY)",
    )
    rotate_key_parser.add_argument(
        "--output", default=None, metavar="FILE",
        help="Output file (default: overwrite input file)",
    )
    rotate_key_parser.add_argument(
        "--reason", default="scheduled rotation",
        help="Reason for key rotation (default: 'scheduled rotation')",
    )

    check_health_parser = audit_sub.add_parser(
        "check-health",
        help="Run health checks on a JSONL audit file",
    )
    check_health_parser.add_argument(
        "file", metavar="EVENTS_JSONL",
        help="Path to the JSONL audit file",
    )
    check_health_parser.add_argument(
        "--output", choices=["text", "json"], default="text",
        help="Output format (default: text)",
    )

    # SF-13-C: audit verify — chain integrity verification
    verify_parser = audit_sub.add_parser(
        "verify",
        help="Verify HMAC chain integrity of JSONL audit file(s)",
    )
    verify_parser.add_argument(
        "--input", required=True,
        help="Path to JSONL audit file (supports glob: 'audit-*.jsonl')",
    )
    verify_parser.add_argument(
        "--key", default=None,
        help="HMAC signing key (default: $SPANFORGE_SIGNING_KEY)",
    )

    # scan sub-command — GA-03 deep PII scanning
    scan_parser = sub.add_parser(
        "scan",
        help="Scan a JSONL file for PII using regex detectors",
    )
    scan_parser.add_argument(
        "file",
        metavar="FILE",
        help="Path to the JSONL file to scan",
    )
    scan_parser.add_argument(
        "--format", choices=["text", "json"], default="text",
        help="Output format (default: text)",
    )
    scan_parser.add_argument(
        "--types", default=None,
        help="Comma-separated PII types to filter (e.g. 'ssn,credit_card')",
    )
    scan_parser.add_argument(
        "--fail-on-match", dest="fail_on_match", action="store_true", default=False,
        help="Exit with code 1 if any PII is detected (CI gate mode)",
    )

    # migrate sub-command — GA-05 schema migration
    migrate_parser = sub.add_parser(
        "migrate",
        help="Migrate a JSONL file from schema v1 to v2",
    )
    migrate_parser.add_argument(
        "file",
        metavar="FILE",
        help="Path to the JSONL file to migrate",
    )
    migrate_parser.add_argument(
        "--output", default=None, metavar="FILE",
        help="Output file (default: <input>_v2.jsonl)",
    )
    migrate_parser.add_argument(
        "--target-version", dest="target_version", default="2.0",
        help="Target schema version (default: 2.0)",
    )
    migrate_parser.add_argument(
        "--sign", action="store_true", default=False,
        help="Re-sign the migrated chain (reads SPANFORGE_SIGNING_KEY)",
    )
    migrate_parser.add_argument(
        "--dry-run", dest="dry_run", action="store_true", default=False,
        help="Preview migration without writing output",
    )

    # inspect sub-command
    inspect_parser = sub.add_parser(
        "inspect",
        help="Pretty-print a single event by event_id from a JSONL file",
    )
    inspect_parser.add_argument(
        "event_id",
        metavar="EVENT_ID",
        help="The event_id to look up",
    )
    inspect_parser.add_argument(
        "file",
        metavar="EVENTS_JSONL",
        help="Path to a JSONL file to search",
    )

    # stats sub-command
    stats_parser = sub.add_parser(
        "stats",
        help="Print a summary of events in a JSONL file (counts, tokens, cost, timestamps)",
    )
    stats_parser.add_argument(
        "file",
        metavar="EVENTS_JSONL",
        help="Path to a JSONL file",
    )

    # compliance command group
    compliance_parser = sub.add_parser(
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
    gen_parser.add_argument("--from", dest="from_date", required=True, metavar="DATE",
                            help="Period start date (YYYY-MM-DD)")
    gen_parser.add_argument("--to", dest="to_date", required=True, metavar="DATE",
                            help="Period end date (YYYY-MM-DD)")
    gen_parser.add_argument("--output", default=".", metavar="DIR",
                            help="Output directory for evidence files (default: .)")
    gen_parser.add_argument("--events-file", dest="events_file", metavar="JSONL",
                            help="Optional JSONL file of audit events to include")

    val_att_parser = comp_sub.add_parser(
        "validate-attestation",
        help="Verify the HMAC signature of a compliance attestation JSON file",
    )
    val_att_parser.add_argument(
        "attestation_file",
        metavar="ATTESTATION_JSON",
        help="Path to a compliance attestation JSON file",
    )

    report_comp_parser = comp_sub.add_parser(
        "report",
        help="Generate a compliance report (JSON, PDF, or both) with HMAC attestation",
    )
    report_comp_parser.add_argument("--model-id", dest="model_id", required=True, help="Model UUID")
    report_comp_parser.add_argument(
        "--framework", required=True,
        help="Compliance framework (eu_ai_act, gdpr, hipaa, iso_42001, nist_ai_rmf, soc2)",
    )
    report_comp_parser.add_argument("--from", dest="from_date", required=True, metavar="DATE",
                                    help="Period start date (YYYY-MM-DD)")
    report_comp_parser.add_argument("--to", dest="to_date", required=True, metavar="DATE",
                                    help="Period end date (YYYY-MM-DD)")
    report_comp_parser.add_argument(
        "--format", dest="report_format", default="json",
        choices=["json", "pdf", "both"],
        help="Output format: json, pdf, or both (default: json)",
    )
    report_comp_parser.add_argument("--output", default=".", metavar="DIR",
                                    help="Output directory (default: .)")
    report_comp_parser.add_argument("--events-file", dest="events_file", metavar="JSONL",
                                    help="Optional JSONL file of audit events to include")
    report_comp_parser.add_argument(
        "--sign", action="store_true", default=False,
        help="Embed HMAC attestation signature in the output",
    )

    check_parser = comp_sub.add_parser(
        "check",
        help="CI-friendly compliance gate: exits 0 if all clauses pass, 1 if gaps exist",
    )
    check_parser.add_argument("--model-id", dest="model_id", default="*",
                              help="Model ID to check (default: * = all models)")
    check_parser.add_argument(
        "--framework",
        required=True,
        help="Compliance framework (eu_ai_act, gdpr, hipaa, iso_42001, nist_ai_rmf, soc2)",
    )
    check_parser.add_argument("--from", dest="from_date", required=True, metavar="DATE",
                              help="Period start date (YYYY-MM-DD)")
    check_parser.add_argument("--to", dest="to_date", required=True, metavar="DATE",
                              help="Period end date (YYYY-MM-DD)")
    check_parser.add_argument("--events-file", dest="events_file", metavar="JSONL",
                              help="Optional JSONL file of audit events")
    check_parser.add_argument(
        "--allow-partial", dest="allow_partial", action="store_true",
        help="Exit 0 on partial coverage (only fail on zero-evidence clauses)",
    )

    # cost command group
    cost_parser = sub.add_parser(
        "cost",
        help="Cost brief management",
    )
    cost_sub = cost_parser.add_subparsers(dest="cost_command", metavar="<action>")

    brief_parser = cost_sub.add_parser("brief", help="Cost brief operations")
    brief_sub = brief_parser.add_subparsers(dest="brief_command", metavar="<action>")

    submit_parser = brief_sub.add_parser(
        "submit",
        help="Submit a cost brief JSON file to the local brief store",
    )
    submit_parser.add_argument(
        "--file", required=True, metavar="BRIEF_JSON",
        help="Path to a cost brief JSON file",
    )
    submit_parser.add_argument(
        "--store", default=".spanforge-cost-briefs.json", metavar="STORE_JSON",
        help="Path to the local cost brief store JSON file (default: .spanforge-cost-briefs.json)",
    )

    # dev command group
    dev_parser = sub.add_parser(
        "dev",
        help="Local development environment lifecycle",
    )
    dev_sub = dev_parser.add_subparsers(dest="dev_command", metavar="<action>")

    dev_start_p = dev_sub.add_parser("start", help="Start the local dev environment")
    dev_start_p.add_argument(
        "service", nargs="?", default="spanforge-dev",
        help="Service name (default: spanforge-dev)",
    )
    dev_sub.add_parser("stop", help="Flush buffer and stop the local dev environment")
    dev_sub.add_parser("reset", help="Reset all in-memory dev state")
    dev_sub.add_parser("logs", help="Print accumulated dev log entries")
    dev_sub.add_parser("status", help="Print the current dev environment status as JSON")

    # module command group
    module_parser = sub.add_parser(
        "module",
        help="SpanForge plugin module scaffolding",
    )
    module_sub = module_parser.add_subparsers(dest="module_command", metavar="<action>")

    create_parser = module_sub.add_parser(
        "create",
        help="Scaffold a new SpanForge plugin module directory",
    )
    create_parser.add_argument("name", metavar="MODULE_NAME", help="Python-package-safe module name")
    create_parser.add_argument(
        "--trust-level", dest="trust_level", default="UNTRUSTED",
        metavar="LEVEL",
        help="Trust level: UNTRUSTED, COMMUNITY, VERIFIED, OFFICIAL (default: UNTRUSTED)",
    )
    create_parser.add_argument("--author", default="unknown", help="Author identifier")
    create_parser.add_argument(
        "--output-dir", dest="output_dir", default=".",
        metavar="DIR", help="Parent directory for the scaffolded module (default: .)",
    )

    # serve subcommand — local trace viewer
    serve_parser = sub.add_parser(
        "serve",
        help="Start a local HTTP trace viewer at /traces (default port 8888)",
    )
    serve_parser.add_argument(
        "--port", type=int, default=8888,
        help="HTTP port to bind (default: 8888)",
    )
    serve_parser.add_argument(
        "--host", default="127.0.0.1",
        help="Interface to bind (default: 127.0.0.1)",
    )
    serve_parser.add_argument(
        "--file", dest="file", default=None, metavar="FILE",
        help="Optional JSONL file to pre-load into the trace store before serving",
    )

    # init sub-command
    init_parser = sub.add_parser(
        "init",
        help="Scaffold a spanforge.toml config file in the current directory",
    )
    init_parser.add_argument(
        "--service-name", dest="service_name", default=None,
        help="Service name to embed in spanforge.toml (default: current directory name)",
    )
    init_parser.add_argument(
        "--output-dir", dest="output_dir", default=".",
        metavar="DIR", help="Directory to write files into (default: .)",
    )
    init_parser.add_argument(
        "--force", action="store_true", default=False,
        help="Overwrite existing spanforge.toml without prompting",
    )

    # quickstart sub-command
    sub.add_parser(
        "quickstart",
        help="Interactive setup wizard: configure exporter, service name, and signing",
    )

    # report sub-command
    report_parser = sub.add_parser(
        "report",
        help="Generate a static HTML trace report from a JSONL events file",
    )
    report_parser.add_argument(
        "file",
        metavar="EVENTS_JSONL",
        help="Path to the JSONL events file",
    )
    report_parser.add_argument(
        "--output", default="spanforge-report.html",
        metavar="HTML_FILE",
        help="Output HTML file path (default: spanforge-report.html)",
    )

    # ui sub-command
    ui_parser = sub.add_parser(
        "ui",
        help="Open a local HTML trace viewer in your browser",
    )
    ui_parser.add_argument(
        "--file", dest="file", default=None, metavar="EVENTS_JSONL",
        help="JSONL file to render as a trace report",
    )
    ui_parser.add_argument(
        "--port", type=int, default=8889,
        help="HTTP port to bind (default: 8889)",
    )
    ui_parser.add_argument(
        "--no-browser", dest="no_browser", action="store_true", default=False,
        help="Do not automatically open the browser",
    )

    args = parser.parse_args(argv)

    if args.command == "check":
        sys.exit(_cmd_check(args))
    elif args.command == "check-compat":
        sys.exit(_cmd_check_compat(args))
    elif args.command == "list-deprecated":
        sys.exit(_cmd_list_deprecated(args))
    elif args.command == "migration-roadmap":
        sys.exit(_cmd_migration_roadmap(args))
    elif args.command == "check-consumers":
        sys.exit(_cmd_check_consumers(args))
    elif args.command == "validate":
        sys.exit(_cmd_validate(args))
    elif args.command == "audit-chain":
        sys.exit(_cmd_audit_chain(args))
    elif args.command == "audit":
        audit_action = getattr(args, "audit_command", None)
        if audit_action == "erase":
            sys.exit(_cmd_audit_erase(args))
        elif audit_action == "rotate-key":
            sys.exit(_cmd_audit_rotate_key(args))
        elif audit_action == "check-health":
            sys.exit(_cmd_audit_check_health(args))
        elif audit_action == "verify":
            sys.exit(_cmd_audit_verify(args))
        else:
            audit_group_parser.print_help()
            sys.exit(2)
    elif args.command == "inspect":
        sys.exit(_cmd_inspect(args))
    elif args.command == "scan":
        sys.exit(_cmd_scan(args))
    elif args.command == "migrate":
        sys.exit(_cmd_migrate(args))
    elif args.command == "stats":
        sys.exit(_cmd_stats(args))
    elif args.command == "compliance":
        action = getattr(args, "compliance_command", None)
        if action == "generate":
            sys.exit(_cmd_compliance_generate(args))
        elif action == "validate-attestation":
            sys.exit(_cmd_compliance_validate_attestation(args))
        elif action == "check":
            sys.exit(_cmd_compliance_check(args))
        elif action == "report":
            sys.exit(_cmd_compliance_report(args))
        else:
            compliance_parser.print_help()
            sys.exit(2)
    elif args.command == "cost":
        cost_action = getattr(args, "cost_command", None)
        brief_action = getattr(args, "brief_command", None)
        if cost_action == "brief" and brief_action == "submit":
            sys.exit(_cmd_cost_brief_submit(args))
        else:
            cost_parser.print_help()
            sys.exit(2)
    elif args.command == "dev":
        sys.exit(_cmd_dev(args))
    elif args.command == "module":
        action = getattr(args, "module_command", None)
        if action == "create":
            sys.exit(_cmd_module_create(args))
        else:
            module_parser.print_help()
            sys.exit(2)
    elif args.command == "serve":
        sys.exit(_cmd_serve(args))
    elif args.command == "init":
        sys.exit(_cmd_init(args))
    elif args.command == "quickstart":
        sys.exit(_cmd_quickstart(args))
    elif args.command == "report":
        sys.exit(_cmd_report(args))
    elif args.command == "ui":
        sys.exit(_cmd_ui(args))
    else:
        parser.print_help()
        sys.exit(2)
