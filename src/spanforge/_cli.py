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
import contextlib
import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, NoReturn

from spanforge._cli_audit import add_audit_subcommands, dispatch_audit_command
from spanforge._cli_compliance import add_compliance_subcommands, dispatch_compliance_command
from spanforge._cli_cost import add_cost_subcommands, dispatch_cost_command
from spanforge._cli_ops import add_ops_subcommands, dispatch_ops_command
from spanforge._cli_phase11 import add_phase11_subcommands, dispatch_phase11_command

_NO_EVENTS_MSG = "No events found in file."


def _cmd_check(_args: argparse.Namespace) -> int:
    """Implement the ``check`` sub-command — end-to-end health check."""
    import time
    import traceback

    verbose = getattr(_args, "verbose", False)

    def _step(label: str, fn: Any) -> tuple[bool, float]:
        t0 = time.monotonic()
        try:
            result = fn()
            elapsed = time.monotonic() - t0
            return (result if isinstance(result, bool) else True, elapsed)
        except Exception as exc:
            elapsed = time.monotonic() - t0
            print(f"[✗] {label}: {exc}", file=sys.stderr)
            if verbose:
                traceback.print_exc(file=sys.stderr)
            return (False, elapsed)

    print("spanforge health check")
    print("=" * 40)
    ok = True

    # Step 1: Config
    try:
        t0 = time.monotonic()
        from spanforge.config import get_config

        cfg = get_config()
        elapsed = time.monotonic() - t0
        timing_str = f"  ({elapsed*1000:.0f}ms)" if verbose else ""
        print(
            f"[✓] Config loaded  exporter={cfg.exporter!r}  env={cfg.env!r}  "
            f"service={cfg.service_name!r}{timing_str}"
        )
    except Exception as exc:
        print(f"[✗] Config failed: {exc}", file=sys.stderr)
        return 1

    # Step 2: Event creation
    try:
        t0 = time.monotonic()
        from spanforge.event import Event
        from spanforge.ulid import generate as gen_ulid

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
        elapsed = time.monotonic() - t0
        timing_str = f"  ({elapsed*1000:.0f}ms)" if verbose else ""
        print(f"[✓] Test event created{timing_str}")
    except Exception as exc:
        print(f"[✗] Event creation failed: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return 1

    # Step 3: Schema validation
    try:
        t0 = time.monotonic()
        from spanforge.validate import validate_event

        validate_event(event)
        elapsed = time.monotonic() - t0
        timing_str = f"  ({elapsed*1000:.0f}ms)" if verbose else ""
        print(f"[✓] Schema validation passed{timing_str}")
    except Exception as exc:
        print(f"[✗] Schema validation failed: {exc}", file=sys.stderr)
        ok = False

    # Step 4: Export pipeline
    try:
        t0 = time.monotonic()
        from spanforge._stream import _dispatch

        _dispatch(event)
        elapsed = time.monotonic() - t0
        timing_str = f"  ({elapsed*1000:.0f}ms)" if verbose else ""
        print(f"[✓] Export pipeline: event dispatched successfully{timing_str}")
    except Exception as exc:
        print(f"[✗] Export pipeline failed: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        ok = False

    # Step 5: TraceStore recording (only if enabled)
    if cfg.enable_trace_store:
        try:
            t0 = time.monotonic()
            from spanforge._store import get_store

            store = get_store()
            events = store.get_trace("0" * 32)
            elapsed = time.monotonic() - t0
            if events is not None and len(events) >= 1:
                timing_str = f"  ({elapsed*1000:.0f}ms)" if verbose else ""
                print(f"[✓] TraceStore recorded {len(events)} event(s){timing_str}")
            else:
                print("[✗] TraceStore: event not found after dispatch", file=sys.stderr)
                ok = False
        except Exception as exc:
            print(f"[✗] TraceStore check failed: {exc}", file=sys.stderr)
            ok = False
    else:
        print("[-] TraceStore: disabled (set SPANFORGE_ENABLE_TRACE_STORE=1 to enable)")

    # Step 6: Signing key check
    import os
    t0 = time.monotonic()
    signing_key = os.environ.get("SPANFORGE_SIGNING_KEY", "")
    elapsed = time.monotonic() - t0
    timing_str = f"  ({elapsed*1000:.0f}ms)" if verbose else ""
    if signing_key and len(signing_key) >= 32:
        print(f"[✓] Signing key present and meets minimum length{timing_str}")
    elif signing_key:
        print(f"[!] Signing key present but short (<32 chars) — consider rotating{timing_str}")
    else:
        print(f"[-] Signing key: not set (SPANFORGE_SIGNING_KEY not configured){timing_str}")

    # Step 7: Exporter connectivity (best-effort ping)
    t0 = time.monotonic()
    exporter_ok = False
    exporter_detail = ""
    try:
        exporter_type = getattr(cfg, "exporter", "none")
        if exporter_type in ("none", "noop", None, ""):
            exporter_detail = "noop exporter — no connectivity check needed"
            exporter_ok = True
        elif exporter_type == "otlp":
            import socket
            otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "")
            if otlp_endpoint:
                from urllib.parse import urlparse
                parsed = urlparse(otlp_endpoint)
                host = parsed.hostname or "localhost"
                port = parsed.port or 4317
                sock = socket.create_connection((host, port), timeout=2)
                sock.close()
                exporter_detail = f"OTLP endpoint {host}:{port} reachable"
                exporter_ok = True
            else:
                exporter_detail = "OTEL_EXPORTER_OTLP_ENDPOINT not set"
        else:
            exporter_detail = f"exporter={exporter_type!r} — skipping connectivity check"
            exporter_ok = True
    except OSError as exc:
        exporter_detail = f"connection failed: {exc}"
    elapsed = time.monotonic() - t0
    timing_str = f"  ({elapsed*1000:.0f}ms)" if verbose else ""
    if exporter_ok:
        print(f"[✓] Exporter: {exporter_detail}{timing_str}")
    else:
        print(f"[!] Exporter: {exporter_detail}{timing_str}")

    # Step 8: Database connectivity (if trace store configured)
    t0 = time.monotonic()
    if cfg.enable_trace_store:
        try:
            from spanforge._store import get_store as _get_store
            _s = _get_store()
            _ = _s.get_trace("__ping__")
            elapsed = time.monotonic() - t0
            timing_str = f"  ({elapsed*1000:.0f}ms)" if verbose else ""
            print(f"[✓] Database/TraceStore: accessible{timing_str}")
        except Exception as exc:
            elapsed = time.monotonic() - t0
            timing_str = f"  ({elapsed*1000:.0f}ms)" if verbose else ""
            print(f"[!] Database/TraceStore: {exc}{timing_str}")
    else:
        elapsed = time.monotonic() - t0
        timing_str = f"  ({elapsed*1000:.0f}ms)" if verbose else ""
        print(f"[-] Database: TraceStore disabled — skipping DB connectivity check{timing_str}")

    # Step 9: File write permissions (working directory)
    t0 = time.monotonic()
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(dir=".", prefix=".sf_write_check_", delete=True):
            pass
        elapsed = time.monotonic() - t0
        timing_str = f"  ({elapsed*1000:.0f}ms)" if verbose else ""
        print(f"[✓] File write permissions: working directory is writable{timing_str}")
    except OSError as exc:
        elapsed = time.monotonic() - t0
        timing_str = f"  ({elapsed*1000:.0f}ms)" if verbose else ""
        print(f"[✗] File write permissions: {exc}{timing_str}")
        ok = False

    print("=" * 40)
    if ok:
        print("PASS — all checks passed.")
        return 0
    print("FAIL — one or more checks failed.", file=sys.stderr)
    return 1


def _cmd_check_compat(args: argparse.Namespace) -> int:
    """Implement the ``check-compat`` sub-command."""
    from spanforge.compliance import test_compatibility
    from spanforge.event import Event

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

    from spanforge.exceptions import DeserializationError, SchemaValidationError

    try:
        events = [Event.from_dict(item) for item in raw]
    except (DeserializationError, SchemaValidationError, KeyError, TypeError) as exc:
        print(f"error: could not deserialise events: {exc}", file=sys.stderr)
        return 2

    result = test_compatibility(events)
    verbose = getattr(args, "verbose", False)
    fmt = getattr(args, "output_format", "text")

    # Build deprecation info map for verbose output
    dep_info: dict[str, Any] = {}
    if verbose:
        try:
            from spanforge.deprecations import get_deprecation_notice
            seen_types = {str(getattr(e, "event_type", "")) for e in events if getattr(e, "event_type", "")}
            for et in seen_types:
                notice = get_deprecation_notice(et)
                if notice is not None:
                    dep_info[et] = notice
        except Exception:
            pass

    if fmt == "json":
        out: dict[str, Any] = {
            "passed": result.passed,
            "events_checked": result.events_checked,
            "violations": [
                {
                    "event_id": v.event_id,
                    "check_id": v.check_id,
                    "rule": v.rule,
                    "detail": v.detail,
                }
                for v in result.violations
            ],
        }
        if verbose and dep_info:
            out["deprecation_info"] = {
                et: {
                    "since": n.since,
                    "sunset": n.sunset,
                    "replacement": n.replacement,
                    "notes": n.notes,
                }
                for et, n in dep_info.items()
            }
        print(json.dumps(out, indent=2))
        return 0 if result.passed else 1

    if result.passed:
        print(f"OK — {result.events_checked} event(s) passed all compatibility checks.")
        if verbose and dep_info:
            print("\nDeprecation notices:")
            for et, n in dep_info.items():
                repl = f" → {n.replacement}" if n.replacement else ""
                print(f"  [{et}] deprecated since {n.since}, sunset {n.sunset}{repl}")
                if n.notes:
                    print(f"    Note: {n.notes}")
        return 0

    print(
        f"FAIL — {len(result.violations)} violation(s) found in {result.events_checked} event(s):\n"
    )
    for v in result.violations:
        event_ref = f"[{v.event_id}] " if v.event_id else ""
        print(f"  {event_ref}{v.check_id} ({v.rule}): {v.detail}")
        if verbose:
            et = str(v.event_id or "")
            # Try to get event_type from the event itself for deprecation lookup
            matching = [e for e in events if str(getattr(e, "event_id", "")) == et]
            if matching:
                event_type = str(getattr(matching[0], "event_type", ""))
                notice = dep_info.get(event_type)
                if notice is None:
                    try:
                        from spanforge.deprecations import get_deprecation_notice
                        notice = get_deprecation_notice(event_type)
                    except Exception:
                        pass
                if notice is not None:
                    repl = f" → {notice.replacement}" if notice.replacement else ""
                    print(f"    Deprecated: {event_type} (since {notice.since}, sunset {notice.sunset}{repl})")
                    if notice.notes:
                        print(f"    Migration: {notice.notes}")

    return 1


def _cmd_list_deprecated(args: argparse.Namespace) -> int:
    """Implement the ``list-deprecated`` sub-command."""
    fmt = getattr(args, "output_format", "text")
    try:
        from spanforge.deprecations import list_deprecated

        notices = list_deprecated()
        if not notices:
            if fmt == "json":
                print(json.dumps([], indent=2))
            else:
                print("No deprecated event types registered.")
            return 0

        if fmt == "json":
            output = [
                {
                    "event_type": n.event_type,
                    "since": n.since,
                    "sunset": n.sunset,
                    "replacement": n.replacement,
                    "notes": n.notes,
                }
                for n in notices
            ]
            print(json.dumps(output, indent=2))
            return 0

        print(f"{'Event Type':<50} {'Since':<8} {'Sunset':<12} Replacement")
        print("-" * 96)
        for n in notices:
            repl = n.replacement or "(no replacement)"
            sunset_info = n.sunset or "TBD"
            print(f"{n.event_type:<50} {n.since:<8} {sunset_info:<12} {repl}")
            if n.notes:
                print(f"  {'':50} Note: {n.notes}")
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    else:
        return 0


def _cmd_migration_roadmap(args: argparse.Namespace) -> int:
    """Implement the ``migration-roadmap`` sub-command."""
    try:
        import spanforge.migrate as _migrate_mod

        v2_migration_roadmap = getattr(_migrate_mod, "v2_migration_roadmap", None)
        if v2_migration_roadmap is None:
            print("No migration records found.")
            return 0
    except ImportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    roadmap = v2_migration_roadmap()
    if not roadmap:
        print("No migration records found.")
        return 0

    use_timeline = getattr(args, "timeline", False)

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
                "effort": getattr(r, "effort", "medium"),
            }
            for r in roadmap
        ]
        print(json.dumps(output, indent=2))
        return 0

    if use_timeline:
        # Group by since→sunset period
        from collections import defaultdict
        groups: dict[str, list[Any]] = defaultdict(list)
        for r in roadmap:
            key = f"{r.since} → {r.sunset}"
            groups[key].append(r)

        print(f"v1 → v2 Migration Timeline ({len(roadmap)} changes)\n")
        for period, records in sorted(groups.items()):
            print(f"  [{period}] ({len(records)} change(s)):")
            for r in records:
                arrow = f" → {r.replacement}" if r.replacement else " (removed)"
                effort = getattr(r, "effort", "medium")
                effort_str = f" [effort: {effort}]" if effort else ""
                print(f"    • {r.event_type}{arrow}{effort_str}")
                if r.migration_notes:
                    import textwrap
                    wrapped = textwrap.fill(
                        r.migration_notes, width=68,
                        initial_indent="      ", subsequent_indent="      "
                    )
                    print(wrapped)
            print()
        return 0

    print(f"v1 → v2 Migration Roadmap ({len(roadmap)} changes)\n")
    for r in roadmap:
        arrow = f" → {r.replacement}" if r.replacement else " (removed)"
        effort = getattr(r, "effort", "medium")
        effort_str = f" [effort: {effort}]" if effort else ""
        print(f"  [{r.since}→{r.sunset}] {r.event_type}{arrow}{effort_str}")
        if r.migration_notes:
            import textwrap

            wrapped = textwrap.fill(
                r.migration_notes, width=72, initial_indent="    ", subsequent_indent="    "
            )
            print(wrapped)
        if r.field_renames:
            for old, new in r.field_renames.items():
                print(f"    field rename: {old!r} → {new!r}")
        print()
    return 0


def _cmd_check_consumers(args: argparse.Namespace) -> int:
    """Implement the ``check-consumers`` sub-command."""
    from spanforge.consumer import get_registry

    verbose = getattr(args, "verbose", False)
    registry = get_registry()
    all_records = registry.all()
    if not all_records:
        print("No consumers registered.")
        return 0

    incompatible = registry.check_compatible()

    if verbose:
        print(f"Registered consumers ({len(all_records)}):")
        print(f"  {'Tool':<40} {'Schema Ver':<12} {'Namespaces':<40} Status")
        print("  " + "-" * 105)
        compat_set = {t for t, _ in incompatible}
        for rec in sorted(all_records, key=lambda r: r.tool_name):
            ns_str = ", ".join(rec.namespaces)
            status = "INCOMPATIBLE" if rec.tool_name in compat_set else "OK"
            contact_str = f" [{rec.contact}]" if rec.contact else ""
            print(f"  {rec.tool_name:<40} {rec.schema_version:<12} {ns_str:<40} {status}{contact_str}")
        print()

    if not incompatible:
        print(f"OK — all {len(all_records)} consumer(s) are compatible.")
        return 0

    print(f"INCOMPATIBLE — {len(incompatible)} consumer(s) require a newer schema:\n")
    for tool_name, version in incompatible:
        print(f"  {tool_name!r} requires schema v{version}")
    return 1


def _read_jsonl_events(path: Path) -> list[tuple[int, Any]]:
    """Read a JSONL file and return a list of (lineno, Event | Exception) pairs."""
    from spanforge.event import Event
    from spanforge.exceptions import DeserializationError, SchemaValidationError

    results: list[tuple[int, Any]] = []
    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            event = Event.from_dict(obj)
            results.append((lineno, event))
        except (
            json.JSONDecodeError,
            DeserializationError,
            SchemaValidationError,
            KeyError,
            TypeError,
        ) as exc:
            results.append((lineno, exc))
    return results


def _cmd_event_create(args: argparse.Namespace) -> int:
    """Implement the ``event create`` sub-command."""
    import sys

    from spanforge.event import Event
    from spanforge.ulid import generate as gen_ulid

    event_type = args.event_type
    count = max(1, args.count)
    output_format = getattr(args, "output_format", "jsonl")
    output_file = getattr(args, "output", None)

    # Parse payload
    raw_payload: dict[str, object] = {}
    if args.payload:
        if args.payload.startswith("@"):
            payload_path = Path(args.payload[1:])
            if not payload_path.exists():
                print(f"error: payload file not found: {payload_path}", file=sys.stderr)
                return 2
            try:
                raw_payload = json.loads(payload_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                print(f"error: invalid JSON in payload file: {exc}", file=sys.stderr)
                return 2
        else:
            try:
                raw_payload = json.loads(args.payload)
            except json.JSONDecodeError as exc:
                print(f"error: invalid JSON payload: {exc}", file=sys.stderr)
                return 2

    # Build default payload for llm events if none provided
    if not raw_payload and event_type.startswith("llm."):
        raw_payload = {
            "span_id": "0" * 16,
            "trace_id": "0" * 32,
            "span_name": event_type,
            "operation": "chat",
            "span_kind": "client",
            "status": "ok",
            "start_time_unix_nano": 0,
            "end_time_unix_nano": 1_000_000,
            "duration_ms": 1.0,
        }

    # Validate event type
    try:
        from spanforge.validate import validate_event
        from spanforge.exceptions import SchemaValidationError
        test_event = Event(
            event_type=event_type,
            source="spanforge-cli@1.0.0",
            payload=raw_payload or {"_generated": True},
            event_id=gen_ulid(),
        )
        try:
            validate_event(test_event)
        except SchemaValidationError as exc:
            print(f"warning: generated event may not pass schema validation: {exc}", file=sys.stderr)
    except Exception:
        pass

    # Generate events
    generated: list[dict[str, object]] = []
    for _ in range(count):
        event = Event(
            event_type=event_type,
            source="spanforge-cli@1.0.0",
            payload=dict(raw_payload) if raw_payload else {"_generated": True},
            event_id=gen_ulid(),
        )
        generated.append(event.to_dict())

    # Write output
    if output_file:
        out_path = Path(output_file)
        with out_path.open("w", encoding="utf-8") as fh:
            if output_format == "json":
                fh.write(json.dumps(generated, indent=2))
                fh.write("\n")
            else:
                for d in generated:
                    fh.write(json.dumps(d))
                    fh.write("\n")
        print(f"[✓] {count} event(s) written to {out_path}")
    else:
        if output_format == "json":
            print(json.dumps(generated, indent=2))
        else:
            for d in generated:
                print(json.dumps(d))

    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    """Implement the ``validate`` sub-command."""
    # Branch: dataset compliance scanning mode
    dataset_file = getattr(args, "dataset_file", None)
    if dataset_file is not None:
        return _cmd_validate_dataset(args)

    from spanforge.exceptions import SchemaValidationError
    from spanforge.validate import validate_event

    if not getattr(args, "file", None):
        print("error: EVENTS_JSONL is required when not using --dataset", file=sys.stderr)
        return 2

    path = Path(args.file)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    rows = _read_jsonl_events(path)
    if not rows:
        print(_NO_EVENTS_MSG)
        return 0

    report_mode = getattr(args, "report", "summary")
    output_format = getattr(args, "output_format", "text")

    errors: list[dict[str, object]] = []
    for lineno, item in rows:
        if isinstance(item, Exception):
            errors.append({"line": lineno, "field": None, "reason": f"parse error: {item}"})
            continue
        try:
            validate_event(item)
        except SchemaValidationError as exc:
            err_str = str(exc)
            # attempt to extract field name from error message
            field: str | None = None
            if ":" in err_str:
                maybe_field = err_str.split(":")[0].strip()
                if " " not in maybe_field:
                    field = maybe_field
            errors.append({"line": lineno, "field": field, "reason": err_str})

    total = len(rows)
    if output_format == "json":
        print(
            json.dumps(
                {
                    "total": total,
                    "passed": total - len(errors),
                    "failed": len(errors),
                    "errors": errors if report_mode == "detailed" else [
                        {"line": e["line"], "reason": e["reason"]} for e in errors
                    ],
                },
                indent=2,
            )
        )
        return 1 if errors else 0

    if not errors:
        print(f"OK — {total} event(s) passed schema validation.")
        return 0

    print(f"FAIL — {len(errors)} of {total} event(s) failed validation:\n")
    for err in errors:
        if report_mode == "detailed":
            field_str = f" [{err['field']}]" if err.get("field") else ""
            print(f"  line {err['line']}{field_str}: {err['reason']}")
        else:
            print(f"  line {err['line']}: {err['reason']}")
    return 1




def _cmd_validate_dataset(args: argparse.Namespace) -> int:
    """1C-4 — EU AI Act Article 10 compliance scan for a training dataset."""
    from spanforge.sdk.dataset_scanner import scan_dataset_compliance

    dataset_path = Path(getattr(args, "dataset_file", None) or "")
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
            if report.hmac_signature:
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
    return 0 if all_passed else 1


def _cmd_inspect(args: argparse.Namespace) -> int:
    """Implement the ``inspect`` sub-command."""
    path = Path(args.file)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    rows = _read_jsonl_events(path)
    target_id = args.event_id
    output_format = getattr(args, "output_format", "json")

    for _lineno, item in rows:
        if isinstance(item, Exception):
            continue
        if item.event_id == target_id:
            d = item.to_dict()
            if output_format == "pretty":
                # colored key=value pairs — use ANSI codes (no external deps)
                BOLD = "\033[1m"
                CYAN = "\033[36m"
                GREEN = "\033[32m"
                RESET = "\033[0m"
                print(f"{BOLD}event_id{RESET}={CYAN}{d.get('event_id', '')}{RESET}")
                for k, v in d.items():
                    if k == "event_id":
                        continue
                    print(f"  {GREEN}{k}{RESET}={v!r}")
            elif output_format == "csv":
                import csv
                import io
                flat: dict[str, str] = {}
                for k, v in d.items():
                    if isinstance(v, dict):
                        for sk, sv in v.items():
                            flat[f"{k}.{sk}"] = str(sv)
                    else:
                        flat[k] = str(v)
                buf = io.StringIO()
                writer = csv.DictWriter(buf, fieldnames=list(flat.keys()))
                writer.writeheader()
                writer.writerow(flat)
                print(buf.getvalue(), end="")
            else:
                print(json.dumps(d, indent=2))
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
    return (
        type_counts,
        prompt_tokens,
        completion_tokens,
        total_tokens,
        cost_usd,
        timestamps,
        parse_errors,
    )


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

    group_by = getattr(args, "group_by", "type")
    output_format = getattr(args, "output_format", "table")

    (
        type_counts,
        prompt_tokens,
        completion_tokens,
        total_tokens,
        cost_usd,
        timestamps,
        parse_errors,
    ) = _accumulate_stats(rows)

    # Build group counts based on --group-by
    if group_by == "model":
        group_counts: dict[str, int] = {}
        for _lineno, item in rows:
            if isinstance(item, Exception):
                continue
            model = str((item.payload or {}).get("model") or "(unknown)")
            group_counts[model] = group_counts.get(model, 0) + 1
        group_label = "Model"
    elif group_by == "user":
        group_counts = {}
        for _lineno, item in rows:
            if isinstance(item, Exception):
                continue
            user = str((item.payload or {}).get("user_id") or (item.payload or {}).get("user") or "(unknown)")
            group_counts[user] = group_counts.get(user, 0) + 1
        group_label = "User"
    else:
        group_counts = type_counts
        group_label = "Event Type"

    total_events = len(rows) - parse_errors

    if output_format == "json":
        result = {
            "total_events": total_events,
            "parse_errors": parse_errors,
            "group_by": group_by,
            "groups": dict(sorted(group_counts.items(), key=lambda x: -x[1])),
            "tokens": {
                "prompt": prompt_tokens,
                "completion": completion_tokens,
                "total": total_tokens,
            },
            "cost_usd": round(cost_usd, 6),
            "time_range": {
                "earliest": min(timestamps) if timestamps else None,
                "latest": max(timestamps) if timestamps else None,
            },
        }
        print(json.dumps(result, indent=2))
        return 0

    print(
        f"Events: {total_events}"
        + (f" ({parse_errors} parse error(s) skipped)" if parse_errors else "")
    )
    print()

    if group_counts:
        col_w = max(len(group_label), max(len(k) for k in group_counts)) + 2
        print(f"  {group_label:<{col_w}} {'Count':>7}")
        print("  " + "-" * (col_w + 9))
        for et, cnt in sorted(group_counts.items(), key=lambda x: -x[1]):
            print(f"  {et:<{col_w}} {cnt:>7}")
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




def _cmd_dev(args: argparse.Namespace) -> int:
    """Implement ``spanforge dev <action>``."""
    from spanforge.core.dx import DevCLI

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
    from spanforge.core.dx import ModuleCLI

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
    import signal

    from spanforge._server import TraceViewerServer

    port: int = getattr(args, "port", 8888)
    host: str = getattr(args, "host", "127.0.0.1")
    jsonl_file: str | None = getattr(args, "file", None)

    # Pre-load a JSONL file if provided.
    if jsonl_file:
        try:
            import json

            from spanforge._store import get_store
            from spanforge.event import Event

            store = get_store()
            loaded = 0
            with open(Path(jsonl_file), encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    raw = json.loads(line)
                    try:
                        evt = Event.from_dict(raw)
                        store.record(evt)
                        loaded += 1
                    except Exception as exc:
                        _ = exc
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

    def _handle_signal(sig: int, frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    with contextlib.suppress(OSError, ValueError):
        signal.signal(
            signal.SIGTERM, _handle_signal
        )  # SIGTERM not available on Windows in some contexts

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
    out_dir = Path(args.output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    toml_path = out_dir / "spanforge.toml"
    if toml_path.exists() and not args.force:
        print(f"[!] {toml_path} already exists. Use --force to overwrite.", file=sys.stderr)
        return 1

    service_name = args.service_name or Path.cwd().name or "my-service"
    toml_path.write_text(
        _SPANFORGE_TOML_TEMPLATE.format(service_name=service_name), encoding="utf-8"
    )
    print(f"[OK] Created {toml_path}")

    examples_dir = out_dir / "examples"
    examples_dir.mkdir(exist_ok=True)
    ex_path = examples_dir / "trace_llm.py"
    if not ex_path.exists():
        ex_path.write_text(_EXAMPLE_PY_TEMPLATE.format(service_name=service_name), encoding="utf-8")
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
        exporter = input("Exporter (console/jsonl/otlp/datadog) [console]: ").strip() or "console"
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
        lines.append('# signing_key = ""  # export SPANFORGE_SIGNING_KEY=<key>')
    Path("spanforge.toml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("[OK] Wrote spanforge.toml")

    print("\nRunning health check ...")
    import importlib

    try:
        sf = importlib.import_module("spanforge")
        sf.configure(exporter=exporter, service_name=service_name, env=env)
        with sf.span("quickstart-test") as span:
            span.set_status("ok")
        print("[OK] Test event emitted successfully!")
    except Exception as exc:
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
    events: list[dict[str, Any]] = []
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
    import signal
    import webbrowser

    from spanforge._server import TraceViewerServer

    port = args.port

    if args.file:
        src = Path(args.file)
        if not src.exists():
            print(f"[x] File not found: {src}", file=sys.stderr)
            return 1
        from spanforge._store import get_store
        from spanforge.event import Event

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
                except Exception as exc:
                    _ = exc
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




def _cmd_scan(args: argparse.Namespace) -> int:
    """Implement ``spanforge scan`` — deep PII scan on a JSONL file."""
    from spanforge.redact import scan_payload

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
            all_hits.append(
                {
                    "event_index": str(idx),
                    "event_id": getattr(event, "event_id", "unknown"),
                    "pii_type": hit.pii_type,
                    "path": hit.path,
                    "match_count": str(hit.match_count),
                    "sensitivity": hit.sensitivity,
                }
            )

    fmt = getattr(args, "format", "text")
    if fmt == "json":
        import json as _json

        print(
            _json.dumps(
                {
                    "file": str(path),
                    "events_scanned": len(rows),
                    "strings_scanned": total_scanned,
                    "pii_hits": len(all_hits),
                    "hits": all_hits,
                },
                indent=2,
            )
        )
    else:
        print(f"Scanned {len(rows)} events ({total_scanned} string values)")
        if not all_hits:
            print("[✓] No PII detected.")
        else:
            print(f"[!] Found {len(all_hits)} PII hit(s):\n")
            for h in all_hits:
                print(
                    f"  event #{h['event_index']} ({h['event_id']})  "
                    f"{h['pii_type']:20s} path={h['path']}  "
                    f"matches={h['match_count']}  sensitivity={h['sensitivity']}"
                )

    # GA-03-D: --fail-on-match returns 1 on any hit
    fail_on_match = getattr(args, "fail_on_match", False)
    if fail_on_match and all_hits:
        return 1
    return 1 if all_hits else 0


def _cmd_migrate(args: argparse.Namespace) -> int:
    """Implement ``spanforge migrate`` — schema v1→v2 migration."""
    from spanforge.migrate import migrate_file

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


def _cmd_migrate_langsmith(args: argparse.Namespace) -> int:
    """Implement ``spanforge migrate-langsmith`` — LangSmith export import."""
    import time as _time

    from spanforge import EventType
    from spanforge.ulid import generate as ulid_generate

    path = Path(args.file)
    if not path.exists():
        print(f"error: file not found: {path}", file=sys.stderr)
        return 2

    output = args.output or str(path).rsplit(".", 1)[0] + "_spanforge.jsonl"
    source = args.source

    # Read LangSmith export (supports JSONL and JSON array)
    raw_runs: list[dict[str, Any]] = []
    content = path.read_text(encoding="utf-8")
    first_char = content.lstrip()[:1]
    if first_char == "[":
        # JSON array format
        try:
            raw_runs = json.loads(content)
        except json.JSONDecodeError as exc:
            print(f"error: invalid JSON: {exc}", file=sys.stderr)
            return 1
    else:
        # JSONL format
        for line in content.splitlines():
            line = line.strip()
            if line:
                try:
                    raw_runs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

    if not raw_runs:
        print("error: no runs found in file", file=sys.stderr)
        return 1

    events: list[dict[str, Any]] = []
    for run in raw_runs:
        # LangSmith run schema: id, name, run_type, inputs, outputs,
        # start_time, end_time, parent_run_id, trace_id, dotted_order,
        # total_tokens, prompt_tokens, completion_tokens, status, error
        run_type = run.get("run_type", "chain")
        run_name = run.get("name", "unknown")
        run_id = run.get("id", ulid_generate())

        # Map LangSmith run_type → SpanForge EventType (F-27)
        if run_type == "llm":
            event_type = EventType.TRACE_SPAN_COMPLETED.value
        elif run_type in {"tool", "retriever"}:
            event_type = EventType.TOOL_CALL_COMPLETED.value
        elif run_type == "chain":
            event_type = EventType.CHAIN_COMPLETED.value
        else:
            event_type = EventType.TRACE_SPAN_COMPLETED.value

        # Build payload
        payload: dict[str, Any] = {
            "span_name": run_name,
            "run_type": run_type,
            "status": run.get("status", "ok"),
        }

        # Token usage
        total_tok = run.get("total_tokens") or 0
        prompt_tok = run.get("prompt_tokens") or 0
        completion_tok = run.get("completion_tokens") or 0
        if total_tok or prompt_tok or completion_tok:
            payload["token_usage"] = {
                "input_tokens": prompt_tok,
                "output_tokens": completion_tok,
                "total_tokens": total_tok or (prompt_tok + completion_tok),
            }

        # Timing
        if run.get("start_time"):
            payload["start_time"] = run["start_time"]
        if run.get("end_time"):
            payload["end_time"] = run["end_time"]

        # Inputs/outputs (sanitised — no raw content)
        if run.get("inputs"):
            payload["input_keys"] = (
                list(run["inputs"].keys()) if isinstance(run["inputs"], dict) else ["input"]
            )
        if run.get("outputs"):
            payload["output_keys"] = (
                list(run["outputs"].keys()) if isinstance(run["outputs"], dict) else ["output"]
            )

        # Error info
        if run.get("error"):
            payload["error"] = str(run["error"])[:500]

        # Build event
        trace_id = run.get("trace_id", run.get("session_id", ""))
        parent_id = run.get("parent_run_id", "")

        event = {
            "event_id": ulid_generate(),
            "event_type": event_type,
            "source": source,
            "schema_version": "2.0",
            "timestamp": run.get("start_time") or _time.time(),
            "payload": payload,
            "tags": {
                "langsmith_run_id": str(run_id),
                "langsmith_trace_id": str(trace_id) if trace_id else "",
                "langsmith_parent_id": str(parent_id) if parent_id else "",
            },
        }
        events.append(event)

    # Write output
    out_path = Path(output)
    with out_path.open("w", encoding="utf-8") as fh:
        for evt in events:
            fh.write(json.dumps(evt, default=str) + "\n")

    print(f"[✓] Imported {len(events)} runs from LangSmith export")
    print(f"    Source: {path}")
    print(f"    Output: {out_path}")

    # Summary by run_type
    type_counts: dict[str, int] = {}
    for run in raw_runs:
        rt = run.get("run_type", "unknown")
        type_counts[rt] = type_counts.get(rt, 0) + 1
    for rt, count in sorted(type_counts.items()):
        print(f"    {rt}: {count}")

    return 0




# ---------------------------------------------------------------------------
# T.R.U.S.T. Framework CLI handlers
# ---------------------------------------------------------------------------


def _cmd_consent(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Handle ``spanforge consent`` subcommands."""
    from spanforge.consent import check_consent, grant_consent, revoke_consent

    action = getattr(args, "consent_command", None)
    if action == "check":
        ok = check_consent(args.subject, args.scope)
        status = "GRANTED" if ok else "NOT GRANTED"
        print(f"consent({args.subject!r}, {args.scope!r}) = {status}")
        return 0 if ok else 1
    elif action == "grant":
        grant_consent(
            subject_id=args.subject,
            scope=args.scope,
            purpose=args.purpose,
            legal_basis=args.legal_basis,
        )
        print(f"[✓] Consent granted: subject={args.subject!r} scope={args.scope!r}")
        return 0
    elif action == "revoke":
        revoke_consent(subject_id=args.subject, scope=args.scope)
        print(f"[✓] Consent revoked: subject={args.subject!r} scope={args.scope!r}")
        return 0
    else:
        parser.print_help()
        return 2


def _cmd_hitl(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Handle ``spanforge hitl`` subcommands."""
    from spanforge.hitl import list_pending, review_item

    action = getattr(args, "hitl_command", None)
    if action == "pending":
        items = list_pending()
        if not items:
            print("No pending HITL items.")
        else:
            for item in items:
                print(
                    f"  {item.decision_id}  risk={item.risk_tier}  "
                    f"agent={item.agent_id}  reason={item.reason}"
                )
        return 0
    elif action == "review":
        result = review_item(args.decision_id, args.reviewer, args.outcome)
        if result is None:
            print(f"[!] Decision {args.decision_id!r} not found in queue.")
            return 1
        print(f"[✓] Decision {args.decision_id!r} marked as {args.outcome} by {args.reviewer}")
        return 0
    else:
        parser.print_help()
        return 2


def _cmd_model(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Handle ``spanforge model`` subcommands."""
    from spanforge.model_registry import (
        deprecate_model,
        list_models,
        register_model,
        retire_model,
    )

    action = getattr(args, "model_command", None)
    if action == "list":
        models = list_models()
        if not models:
            print("No models registered.")
        else:
            for m in models:
                print(
                    f"  {m.model_id}  name={m.name!r}  version={m.version}  "
                    f"status={m.status}  risk={m.risk_tier}  owner={m.owner}"
                )
        return 0
    elif action == "register":
        try:
            entry = register_model(
                model_id=args.model_id,
                name=args.name,
                version=args.version,
                risk_tier=args.risk_tier,
                owner=args.owner,
                purpose=args.purpose,
            )
            print(f"[✓] Model registered: {entry.model_id}")
        except ValueError as exc:
            print(f"[!] {exc}")
            return 1
        else:
            return 0
    elif action == "deprecate":
        try:
            entry = deprecate_model(args.model_id, reason=args.reason)
            print(f"[✓] Model deprecated: {entry.model_id}")
        except (KeyError, ValueError) as exc:
            print(f"[!] {exc}")
            return 1
        else:
            return 0
    elif action == "retire":
        try:
            entry = retire_model(args.model_id)
            print(f"[✓] Model retired: {entry.model_id}")
        except (KeyError, ValueError) as exc:
            print(f"[!] {exc}")
            return 1
        else:
            return 0
    else:
        parser.print_help()
        return 2


def _cmd_explain(args: argparse.Namespace) -> int:
    """Handle ``spanforge explain`` subcommand."""
    from spanforge.explain import generate_explanation

    record = generate_explanation(
        trace_id=args.trace_id,
        agent_id=args.agent_id,
        decision_id=args.decision_id,
        factors=[],
        summary=args.summary,
    )
    print(record.to_text())
    return 0


def _cmd_eval(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    """Handle ``spanforge eval`` subcommands."""
    import json

    action = getattr(args, "eval_command", None)

    if action == "save":
        # Save examples to JSONL dataset file
        examples: list[dict[str, Any]] = []
        if getattr(args, "input", None):
            in_path = Path(args.input)
            if not in_path.exists():
                print(f"[!] File not found: {in_path}")
                return 1
            with in_path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            obj = json.loads(line)
                            # Extract example-shaped data from events
                            payload = obj.get("payload", obj)
                            example: dict[str, Any] = {}
                            if "output" in payload:
                                example["output"] = payload["output"]
                            elif "response" in payload:
                                example["output"] = payload["response"]
                            if "context" in payload:
                                example["context"] = payload["context"]
                            if "reference" in payload:
                                example["reference"] = payload["reference"]
                            if "input" in payload:
                                example["input"] = payload["input"]
                            elif "query" in payload:
                                example["input"] = payload["query"]
                            if "span_id" in obj:
                                example["span_id"] = obj["span_id"]
                            if "trace_id" in obj:
                                example["trace_id"] = obj["trace_id"]
                            if example:
                                examples.append(example)
                        except json.JSONDecodeError:
                            continue
        else:
            print("[!] --input is required for 'eval save'")
            return 1

        out_path = Path(args.output)
        with out_path.open("w", encoding="utf-8") as fh:
            for ex in examples:
                fh.write(json.dumps(ex, default=str) + "\n")
        print(f"[✓] Saved {len(examples)} examples to {out_path}")
        return 0

    elif action == "run":
        from spanforge.eval import (
            EvalRunner,
            EvalScorer,
            FaithfulnessScorer,
            PIILeakageScorer,
            RefusalDetectionScorer,
        )

        dataset_path = Path(args.file)
        if not dataset_path.exists():
            print(f"[!] File not found: {dataset_path}")
            return 1

        dataset: list[dict[str, Any]] = []
        with dataset_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        dataset.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        if not dataset:
            print("[!] No examples found in dataset file")
            return 1

        # Build scorers from --scorers flag (or default to all)
        scorer_map: dict[str, type[EvalScorer]] = {
            "faithfulness": FaithfulnessScorer,
            "refusal": RefusalDetectionScorer,
            "pii_leakage": PIILeakageScorer,
        }
        requested = args.scorers.split(",") if args.scorers else list(scorer_map.keys())
        scorers: list[EvalScorer] = []
        for name in requested:
            name = name.strip()
            if name not in scorer_map:
                print(f"[!] Unknown scorer: {name}  (available: {', '.join(scorer_map)})")
                return 1
            scorers.append(scorer_map[name]())

        runner = EvalRunner(scorers=scorers, emit=False)
        report = runner.run(dataset)
        summary = report.summary()

        fmt = getattr(args, "format", "text")
        if fmt == "json":
            result = {
                "examples": len(dataset),
                "scores": len(report.scores),
                "summary": summary,
            }
            print(json.dumps(result, indent=2, default=str))
        else:
            print(f"Dataset: {dataset_path}  ({len(dataset)} examples)")
            print(f"{'Metric':<30}  {'Mean':>10}")
            print("-" * 43)
            for metric, mean in sorted(summary.items()):
                print(f"{metric:<30}  {mean:>10.4f}")
            print("-" * 43)
            print(f"Total scores: {len(report.scores)}")

        return 0

    else:
        parser.print_help()
        return 2


# ---------------------------------------------------------------------------
# secrets sub-command — SEC-040 secrets scanning
# ---------------------------------------------------------------------------


def _cmd_secrets(args: argparse.Namespace, secrets_parser: argparse.ArgumentParser) -> int:
    """Implement the ``secrets`` sub-command group."""
    action = getattr(args, "secrets_command", None)
    if action == "scan":
        return _cmd_secrets_scan(args)
    if action == "install-hook":
        return _cmd_secrets_install_hook(args)
    secrets_parser.print_help()
    return 2


def _cmd_secrets_scan(args: argparse.Namespace) -> int:
    """Implement the ``secrets scan`` sub-command (SEC-040).

    Reads a file (plain text, JSONL, or source code), scans every line for
    hard-coded secrets, and reports results.

    Exit codes::

        0  — no secrets detected above the confidence threshold.
        1  — secrets detected (CI gate mode).
        2  — usage or I/O error.
    """
    from spanforge.secrets import SecretsScanner

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"error: file not found: {file_path}", file=sys.stderr)
        return 2

    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        print(f"error: could not read {file_path}: {exc}", file=sys.stderr)
        return 2

    confidence = float(getattr(args, "confidence", 0.75))
    redact = getattr(args, "redact", False)
    fmt = getattr(args, "format", "text")

    try:
        scanner = SecretsScanner(confidence_threshold=confidence)
        result = scanner.scan(text, confidence_threshold=confidence)
    except Exception as exc:
        print(f"error: scan failed: {exc}", file=sys.stderr)
        return 2

    if fmt == "sarif":
        output = result.to_sarif(tool_name="spanforge-secrets")
        print(json.dumps(output, indent=2))
        return 1 if result.detected else 0

    if fmt == "json":
        data = result.to_dict()
        if not redact:
            data.pop("redacted_text", None)
        print(json.dumps(data, indent=2))
        return 1 if result.detected else 0

    # --- text output ---
    if not result.detected:
        print(f"[✓] No secrets detected in {file_path}")
        return 0

    print(f"[✗] {len(result.hits)} secret(s) detected in {file_path}:")
    for hit in result.hits:
        block_marker = " [BLOCKED]" if hit.auto_blocked else ""
        print(
            f"  [{hit.secret_type}] offset {hit.start}-{hit.end} "
            f"confidence={hit.confidence:.2f}{block_marker}"
        )
        if hit.vault_hint:
            print(f"      Hint: {hit.vault_hint}")

    if redact:
        print("\n--- Redacted output ---")
        print(result.redacted_text)

    if result.auto_blocked:
        print(
            "\nAUTO-BLOCKED: Zero-tolerance or high-confidence secrets detected. "
            "Remove secrets and rotate credentials before committing.",
            file=sys.stderr,
        )

    return 1


def _cmd_secrets_install_hook(args: argparse.Namespace) -> int:
    """Implement the ``secrets install-hook`` sub-command.

    Writes a git hook script to ``.git/hooks/<hook_type>`` that runs
    ``spanforge secrets scan`` on staged files.

    Exit codes::

        0  — hook installed successfully.
        1  — installation error (already exists without --force, not a git repo, etc.).
        2  — usage error.
    """
    import stat

    repo_path = Path(getattr(args, "path", None) or ".")
    hook_type = getattr(args, "hook_type", "pre-commit")
    force = getattr(args, "force", False)

    git_dir = repo_path / ".git"
    if not git_dir.is_dir():
        print(f"error: not a git repository (or no .git found in {repo_path.resolve()})", file=sys.stderr)
        return 1

    hooks_dir = git_dir / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_file = hooks_dir / hook_type

    if hook_file.exists() and not force:
        print(
            f"error: hook already exists at {hook_file}. Use --force to overwrite.",
            file=sys.stderr,
        )
        return 1

    if hook_type == "pre-commit":
        script = (
            "#!/usr/bin/env sh\n"
            "# Auto-generated by spanforge secrets install-hook\n"
            "# Scans staged files for hard-coded secrets before commit.\n"
            "set -e\n"
            "STAGED=$(git diff --cached --name-only --diff-filter=ACMR 2>/dev/null)\n"
            "if [ -z \"$STAGED\" ]; then exit 0; fi\n"
            "for FILE in $STAGED; do\n"
            "  if [ -f \"$FILE\" ]; then\n"
            "    spanforge secrets scan \"$FILE\" --format text\n"
            "    if [ $? -ne 0 ]; then\n"
            "      echo \"[spanforge] Secrets detected in $FILE. Commit blocked.\" >&2\n"
            "      exit 1\n"
            "    fi\n"
            "  fi\n"
            "done\n"
            "exit 0\n"
        )
    else:  # pre-push
        script = (
            "#!/usr/bin/env sh\n"
            "# Auto-generated by spanforge secrets install-hook\n"
            "# Scans changed files for hard-coded secrets before push.\n"
            "set -e\n"
            "while read LOCAL_REF LOCAL_SHA REMOTE_REF REMOTE_SHA; do\n"
            "  CHANGED=$(git diff --name-only \"$REMOTE_SHA\" \"$LOCAL_SHA\" 2>/dev/null || true)\n"
            "  for FILE in $CHANGED; do\n"
            "    if [ -f \"$FILE\" ]; then\n"
            "      spanforge secrets scan \"$FILE\" --format text\n"
            "      if [ $? -ne 0 ]; then\n"
            "        echo \"[spanforge] Secrets detected in $FILE. Push blocked.\" >&2\n"
            "        exit 1\n"
            "      fi\n"
            "    fi\n"
            "  done\n"
            "done\n"
            "exit 0\n"
        )

    hook_file.write_text(script, encoding="utf-8")
    # Make the hook executable
    hook_file.chmod(hook_file.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    action_str = "Updated" if force and (hooks_dir / hook_type).exists() else "Installed"
    print(f"[\u2713] {action_str} {hook_type} hook: {hook_file}")
    print(f"  Hook will run 'spanforge secrets scan' on staged files before each {hook_type.replace('-', ' ')}.")
    return 0


def main(argv: list[str] | None = None) -> NoReturn:
    """Entry point for the ``spanforge`` CLI tool."""
    from spanforge import CONFORMANCE_PROFILE, __version__

    parser = argparse.ArgumentParser(
        prog="spanforge",
        description="spanforge command-line utilities",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"spanforge {__version__} [{CONFORMANCE_PROFILE}]",
    )
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    # check sub-command (health check)
    check_parser = sub.add_parser(
        "check",
        help="End-to-end health check: validates config, emits a test event, confirms export pipeline",
    )
    check_parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Show timing for each check",
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
    compat_parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Show deprecation info and replacement fields for each violation",
    )
    compat_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        dest="output_format",
        help="Output format: text (default) or json",
    )

    # list-deprecated sub-command
    list_dep_parser = sub.add_parser(
        "list-deprecated",
        help="Print all deprecated event types from the global deprecation registry",
    )
    list_dep_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        dest="output_format",
        help="Output format: text (default) or json",
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
    roadmap_parser.add_argument(
        "--timeline",
        action="store_true",
        default=False,
        help="Group migrations by timeline (since/sunset period)",
    )

    # check-consumers sub-command
    consumers_parser = sub.add_parser(
        "check-consumers",
        help="Assert all registered consumers are compatible with the installed schema",
    )
    consumers_parser.add_argument(
        "--verbose",
        action="store_true",
        default=False,
        help="Show per-consumer version listing",
    )

    # validate sub-command
    validate_parser = sub.add_parser(
        "validate",
        help="Validate every event in a JSONL file against the published schema",
    )
    validate_parser.add_argument(
        "file",
        metavar="EVENTS_JSONL",
        nargs="?",
        default=None,
        help="Path to a JSONL file (one event JSON per line); optional when --dataset is used",
    )
    validate_parser.add_argument(
        "--report",
        choices=["summary", "detailed"],
        default="summary",
        help="Report verbosity: summary (default) or detailed (line + field + reason)",
    )
    validate_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        dest="output_format",
        help="Output format: text (default) or json",
    )
    validate_parser.add_argument(
        "--dataset",
        default=None,
        metavar="PATH",
        dest="dataset_file",
        help="Scan a dataset file or directory for EU AI Act Article 10 compliance",
    )
    validate_parser.add_argument(
        "--output",
        dest="output_format",
        choices=["report", "json", "pdf"],
        default="report",
        help="Dataset output format: report (markdown, default), json, or pdf (requires reportlab)",
    )
    validate_parser.add_argument(
        "--no-sign",
        dest="no_sign",
        action="store_true",
        default=False,
        help="Skip HMAC signing of the dataset compliance report",
    )

    # event command group
    event_parser = sub.add_parser(
        "event",
        help="Event management utilities",
    )
    event_sub = event_parser.add_subparsers(dest="event_command", metavar="<action>")

    event_create_parser = event_sub.add_parser(
        "create",
        help="Create one or more synthetic SpanForge events and write to JSONL",
    )
    event_create_parser.add_argument(
        "--type",
        dest="event_type",
        required=True,
        help="Event type (e.g. llm.trace.span.completed)",
    )
    event_create_parser.add_argument(
        "--payload",
        default=None,
        help="JSON payload string, @/path/to/file.json, or omit for defaults",
    )
    event_create_parser.add_argument(
        "--count",
        type=int,
        default=1,
        help="Number of events to generate (default: 1)",
    )
    event_create_parser.add_argument(
        "--output",
        default=None,
        metavar="FILE",
        help="Output JSONL file (default: stdout)",
    )
    event_create_parser.add_argument(
        "--format",
        choices=["jsonl", "json"],
        default="jsonl",
        dest="output_format",
        help="Output format: jsonl (default, one per line) or json (array)",
    )

    audit_group_parser = add_audit_subcommands(sub)

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
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    scan_parser.add_argument(
        "--types",
        default=None,
        help="Comma-separated PII types to filter (e.g. 'ssn,credit_card')",
    )
    scan_parser.add_argument(
        "--fail-on-match",
        dest="fail_on_match",
        action="store_true",
        default=False,
        help="Exit with code 1 if any PII is detected (CI gate mode)",
    )

    # secrets sub-command group — SEC-040 secrets scanning
    secrets_parser = sub.add_parser(
        "secrets",
        help="Secrets scanning utilities (scan files for hard-coded credentials)",
    )
    secrets_sub = secrets_parser.add_subparsers(dest="secrets_command", metavar="<action>")

    secrets_scan_parser = secrets_sub.add_parser(
        "scan",
        help="Scan a file for hard-coded secrets (API keys, tokens, private keys, etc.)",
    )
    secrets_scan_parser.add_argument(
        "file",
        metavar="FILE",
        help="Path to the file to scan (plain text, source code, or JSONL)",
    )
    secrets_scan_parser.add_argument(
        "--format",
        choices=["text", "json", "sarif"],
        default="text",
        help="Output format: text (human-readable), json, or sarif 2.1.0 (default: text)",
    )
    secrets_scan_parser.add_argument(
        "--redact",
        action="store_true",
        default=False,
        help="Include redacted text in text/json output",
    )
    secrets_scan_parser.add_argument(
        "--confidence",
        type=float,
        default=0.75,
        metavar="FLOAT",
        help="Minimum confidence threshold [0.0-1.0] to report a hit (default: 0.75)",
    )

    secrets_hook_parser = secrets_sub.add_parser(
        "install-hook",
        help="Install a git pre-commit or pre-push hook to run 'spanforge secrets scan'",
    )
    secrets_hook_parser.add_argument(
        "--hook-type",
        dest="hook_type",
        choices=["pre-commit", "pre-push"],
        default="pre-commit",
        help="Which git hook to install (default: pre-commit)",
    )
    secrets_hook_parser.add_argument(
        "--path",
        default=None,
        metavar="REPO_PATH",
        help="Path to the git repository root (default: current working directory)",
    )
    secrets_hook_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite existing hook file",
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
        "--output",
        default=None,
        metavar="FILE",
        help="Output file (default: <input>_v2.jsonl)",
    )
    migrate_parser.add_argument(
        "--target-version",
        dest="target_version",
        default="2.0",
        help="Target schema version (default: 2.0)",
    )
    migrate_parser.add_argument(
        "--sign",
        action="store_true",
        default=False,
        help="Re-sign the migrated chain (reads SPANFORGE_SIGNING_KEY)",
    )
    migrate_parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=False,
        help="Preview migration without writing output",
    )

    # migrate-langsmith sub-command — import LangSmith exports
    ls_migrate_parser = sub.add_parser(
        "migrate-langsmith",
        help="Import a LangSmith export file and convert to SpanForge events",
    )
    ls_migrate_parser.add_argument(
        "file",
        metavar="FILE",
        help="Path to the LangSmith export file (JSONL or JSON)",
    )
    ls_migrate_parser.add_argument(
        "--output",
        default=None,
        metavar="FILE",
        help="Output JSONL file (default: <input>_spanforge.jsonl)",
    )
    ls_migrate_parser.add_argument(
        "--source",
        default="langsmith-import",
        help="Source identifier for generated events (default: langsmith-import)",
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
    inspect_parser.add_argument(
        "--format",
        choices=["json", "pretty", "csv"],
        default="json",
        dest="output_format",
        help="Output format: json (default), pretty (colored key=value), or csv",
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
    stats_parser.add_argument(
        "--group-by",
        choices=["type", "model", "user"],
        default="type",
        dest="group_by",
        help="Field to group counts by: type (default), model, or user",
    )
    stats_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        dest="output_format",
        help="Output format: table (default) or json",
    )

    compliance_parser = add_compliance_subcommands(sub)

    cost_parser = add_cost_subcommands(sub)

    # dev command group
    dev_parser = sub.add_parser(
        "dev",
        help="Local development environment lifecycle",
    )
    dev_sub = dev_parser.add_subparsers(dest="dev_command", metavar="<action>")

    dev_start_p = dev_sub.add_parser("start", help="Start the local dev environment")
    dev_start_p.add_argument(
        "service",
        nargs="?",
        default="spanforge-dev",
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
    create_parser.add_argument(
        "name", metavar="MODULE_NAME", help="Python-package-safe module name"
    )
    create_parser.add_argument(
        "--trust-level",
        dest="trust_level",
        default="UNTRUSTED",
        metavar="LEVEL",
        help="Trust level: UNTRUSTED, COMMUNITY, VERIFIED, OFFICIAL (default: UNTRUSTED)",
    )
    create_parser.add_argument("--author", default="unknown", help="Author identifier")
    create_parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default=".",
        metavar="DIR",
        help="Parent directory for the scaffolded module (default: .)",
    )

    # serve subcommand — local trace viewer
    serve_parser = sub.add_parser(
        "serve",
        help="Start a local HTTP trace viewer at /traces (default port 8888)",
    )
    serve_parser.add_argument(
        "--port",
        type=int,
        default=8888,
        help="HTTP port to bind (default: 8888)",
    )
    serve_parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Interface to bind (default: 127.0.0.1)",
    )
    serve_parser.add_argument(
        "--file",
        dest="file",
        default=None,
        metavar="FILE",
        help="Optional JSONL file to pre-load into the trace store before serving",
    )

    # init sub-command
    init_parser = sub.add_parser(
        "init",
        help="Scaffold a spanforge.toml config file in the current directory",
    )
    init_parser.add_argument(
        "--service-name",
        dest="service_name",
        default=None,
        help="Service name to embed in spanforge.toml (default: current directory name)",
    )
    init_parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default=".",
        metavar="DIR",
        help="Directory to write files into (default: .)",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
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
        "--output",
        default="spanforge-report.html",
        metavar="HTML_FILE",
        help="Output HTML file path (default: spanforge-report.html)",
    )

    # ui sub-command
    ui_parser = sub.add_parser(
        "ui",
        help="Open a local HTML trace viewer in your browser",
    )
    ui_parser.add_argument(
        "--file",
        dest="file",
        default=None,
        metavar="EVENTS_JSONL",
        help="JSONL file to render as a trace report",
    )
    ui_parser.add_argument(
        "--port",
        type=int,
        default=8889,
        help="HTTP port to bind (default: 8889)",
    )
    ui_parser.add_argument(
        "--no-browser",
        dest="no_browser",
        action="store_true",
        default=False,
        help="Do not automatically open the browser",
    )

    # ---------------------------------------------------------------------------
    # T.R.U.S.T. Framework CLI commands
    # ---------------------------------------------------------------------------

    # consent command group
    consent_parser = sub.add_parser(
        "consent",
        help="Consent boundary management",
    )
    consent_sub = consent_parser.add_subparsers(dest="consent_command", metavar="<action>")

    consent_check_parser = consent_sub.add_parser(
        "check",
        help="Check if consent is granted for a given subject and scope",
    )
    consent_check_parser.add_argument("--subject", required=True, help="Subject ID")
    consent_check_parser.add_argument("--scope", required=True, help="Consent scope")

    consent_grant_parser = consent_sub.add_parser(
        "grant",
        help="Grant consent for a subject/scope",
    )
    consent_grant_parser.add_argument("--subject", required=True, help="Subject ID")
    consent_grant_parser.add_argument("--scope", required=True, help="Consent scope")
    consent_grant_parser.add_argument(
        "--purpose", default="cli-grant", help="Purpose (default: cli-grant)"
    )
    consent_grant_parser.add_argument(
        "--legal-basis", dest="legal_basis", default="consent", help="Legal basis"
    )

    consent_revoke_parser = consent_sub.add_parser(
        "revoke",
        help="Revoke consent for a subject/scope",
    )
    consent_revoke_parser.add_argument("--subject", required=True, help="Subject ID")
    consent_revoke_parser.add_argument("--scope", required=True, help="Consent scope")

    # hitl command group
    hitl_parser = sub.add_parser(
        "hitl",
        help="Human-in-the-loop review queue",
    )
    hitl_sub = hitl_parser.add_subparsers(dest="hitl_command", metavar="<action>")

    hitl_sub.add_parser(
        "pending",
        help="List all pending (queued) HITL items",
    )

    hitl_review_parser = hitl_sub.add_parser(
        "review",
        help="Record a review decision for a pending item",
    )
    hitl_review_parser.add_argument("--id", dest="decision_id", required=True, help="Decision ID")
    hitl_review_parser.add_argument("--reviewer", required=True, help="Reviewer name")
    hitl_review_parser.add_argument(
        "--outcome",
        required=True,
        choices=["approved", "rejected"],
        help="Review outcome",
    )

    # model command group
    model_parser = sub.add_parser(
        "model",
        help="Model registry management",
    )
    model_sub = model_parser.add_subparsers(dest="model_command", metavar="<action>")

    model_sub.add_parser("list", help="List all registered models")

    model_reg_parser = model_sub.add_parser(
        "register",
        help="Register a new model",
    )
    model_reg_parser.add_argument("--model-id", dest="model_id", required=True, help="Model ID")
    model_reg_parser.add_argument("--name", required=True, help="Model name")
    model_reg_parser.add_argument("--version", required=True, help="Model version")
    model_reg_parser.add_argument(
        "--risk-tier",
        dest="risk_tier",
        required=True,
        choices=["low", "medium", "high", "critical"],
        help="Risk tier",
    )
    model_reg_parser.add_argument("--owner", required=True, help="Owner")
    model_reg_parser.add_argument("--purpose", required=True, help="Purpose")

    model_dep_parser = model_sub.add_parser(
        "deprecate",
        help="Deprecate a model",
    )
    model_dep_parser.add_argument("--model-id", dest="model_id", required=True, help="Model ID")
    model_dep_parser.add_argument("--reason", default="", help="Deprecation reason")

    model_ret_parser = model_sub.add_parser(
        "retire",
        help="Retire a model",
    )
    model_ret_parser.add_argument("--model-id", dest="model_id", required=True, help="Model ID")

    # explain command
    explain_parser = sub.add_parser(
        "explain",
        help="Generate an explainability record",
    )
    explain_parser.add_argument("--trace-id", dest="trace_id", required=True, help="Trace ID")
    explain_parser.add_argument("--agent-id", dest="agent_id", required=True, help="Agent ID")
    explain_parser.add_argument(
        "--decision-id", dest="decision_id", required=True, help="Decision ID"
    )
    explain_parser.add_argument("--summary", required=True, help="Human-readable summary")

    # eval command group
    eval_parser = sub.add_parser(
        "eval",
        help="Evaluation dataset management and scorer execution",
    )
    eval_sub = eval_parser.add_subparsers(dest="eval_command", metavar="<action>")

    eval_save_parser = eval_sub.add_parser(
        "save",
        help="Extract evaluation examples from a JSONL events file",
    )
    eval_save_parser.add_argument(
        "--input",
        required=True,
        metavar="JSONL",
        help="Path to a JSONL events file to extract examples from",
    )
    eval_save_parser.add_argument(
        "--output",
        default="eval_dataset.jsonl",
        metavar="FILE",
        help="Output JSONL file for evaluation examples (default: eval_dataset.jsonl)",
    )

    eval_run_parser = eval_sub.add_parser(
        "run",
        help="Run evaluation scorers over a JSONL dataset",
    )
    eval_run_parser.add_argument(
        "--file",
        required=True,
        metavar="JSONL",
        help="Path to a JSONL evaluation dataset file",
    )
    eval_run_parser.add_argument(
        "--scorers",
        default=None,
        help="Comma-separated scorer names (default: all).  Available: faithfulness, refusal, pii_leakage",
    )
    eval_run_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    config_parser, trust_parser, gate_parser, operator_parser = add_ops_subcommands(sub)

    enterprise_parser, security_parser = add_phase11_subcommands(sub)


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
    elif args.command == "event":
        event_action = getattr(args, "event_command", None)
        if event_action == "create":
            sys.exit(_cmd_event_create(args))
        else:
            event_parser.print_help()
            sys.exit(2)
    elif args.command == "validate":
        sys.exit(_cmd_validate(args))
    elif args.command in {"audit-chain", "audit"}:
        sys.exit(
            dispatch_audit_command(
                args,
                audit_group_parser,
                _read_jsonl_events,
                _NO_EVENTS_MSG,
            )
        )
    elif args.command == "inspect":
        sys.exit(_cmd_inspect(args))
    elif args.command == "scan":
        sys.exit(_cmd_scan(args))
    elif args.command == "secrets":
        sys.exit(_cmd_secrets(args, secrets_parser))
    elif args.command == "migrate":
        sys.exit(_cmd_migrate(args))
    elif args.command == "migrate-langsmith":
        sys.exit(_cmd_migrate_langsmith(args))
    elif args.command == "stats":
        sys.exit(_cmd_stats(args))
    elif args.command == "compliance":
        sys.exit(dispatch_compliance_command(args, compliance_parser))
    elif args.command == "cost":
        sys.exit(dispatch_cost_command(args, cost_parser))
    elif args.command in {"config", "trust", "gate", "operator", "doctor"}:
        sys.exit(dispatch_ops_command(args, config_parser, trust_parser, gate_parser, operator_parser))
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
    elif args.command == "consent":
        sys.exit(_cmd_consent(args, consent_parser))
    elif args.command == "hitl":
        sys.exit(_cmd_hitl(args, hitl_parser))
    elif args.command == "model":
        sys.exit(_cmd_model(args, model_parser))
    elif args.command == "explain":
        sys.exit(_cmd_explain(args))
    elif args.command == "eval":
        sys.exit(_cmd_eval(args, eval_parser))
    elif args.command in {"enterprise", "security"}:
        sys.exit(dispatch_phase11_command(args, enterprise_parser, security_parser))
    else:
        parser.print_help()
        sys.exit(2)
