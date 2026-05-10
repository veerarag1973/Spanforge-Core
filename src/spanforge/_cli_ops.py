"""Operational command groups for the SpanForge CLI."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, cast


def add_ops_subcommands(
    sub: argparse._SubParsersAction[argparse.ArgumentParser],
) -> tuple[
    argparse.ArgumentParser,
    argparse.ArgumentParser,
    argparse.ArgumentParser,
    argparse.ArgumentParser,
]:
    """Register operational CLI subcommands."""
    config_parser = sub.add_parser(
        "config",
        help="Integration config management (.halluccheck.toml / ~/.spanforge/config.yaml)",
    )
    config_sub = config_parser.add_subparsers(dest="config_command", metavar="<action>")

    config_validate_parser = config_sub.add_parser(
        "validate",
        help="Validate ~/.spanforge/config.yaml (or --config PATH)",
    )
    config_validate_parser.add_argument(
        "--file",
        default=None,
        metavar="PATH",
        help="Path to .halluccheck.toml (default: auto-discover in cwd or ~)",
    )
    config_validate_parser.add_argument(
        "--config",
        default=None,
        metavar="PATH",
        dest="config",
        help="Path to ~/.spanforge/config.yaml (default: ~/.spanforge/config.yaml)",
    )
    config_validate_parser.add_argument(
        "--check-connectivity",
        dest="check_connectivity",
        action="store_true",
        default=False,
        help="Attempt to reach the configured export backend (exit 2 on failure)",
    )

    # CARD 1D-1: spanforge config init
    config_init_parser = config_sub.add_parser(
        "init",
        help="Generate ~/.spanforge/config.yaml (interactive or --non-interactive)",
    )
    config_init_parser.add_argument(
        "--non-interactive",
        dest="non_interactive",
        action="store_true",
        default=False,
        help="Use defaults without prompting (CI-safe)",
    )
    config_init_parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite existing config without prompting",
    )

    trust_parser = sub.add_parser(
        "trust",
        help="T.R.U.S.T. scorecard operations",
    )
    trust_sub = trust_parser.add_subparsers(dest="trust_command", metavar="<action>")

    trust_scorecard_parser = trust_sub.add_parser(
        "scorecard",
        help="Show T.R.U.S.T. scorecard for a project",
    )
    trust_scorecard_parser.add_argument(
        "--project-id",
        default="",
        metavar="ID",
        help="Project ID to query (default: from config)",
    )
    trust_scorecard_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    trust_scorecard_parser.add_argument(
        "--min-score",
        type=float,
        default=70.0,
        dest="min_score",
        metavar="N",
        help="Gap threshold: dimensions below this score appear in the gap report (default: 70)",
    )

    trust_badge_parser = trust_sub.add_parser(
        "badge",
        help="Generate T.R.U.S.T. badge SVG for a project",
    )
    trust_badge_parser.add_argument(
        "--project-id",
        default="",
        metavar="ID",
        help="Project ID (default: from config)",
    )
    trust_badge_parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="Write SVG to file instead of stdout",
    )

    trust_gate_parser = trust_sub.add_parser(
        "gate",
        help="Run composite trust gate (TRS-020)",
    )
    trust_gate_parser.add_argument(
        "--project-id",
        default="",
        metavar="ID",
        help="Project ID (default: from config)",
    )
    trust_gate_parser.add_argument(
        "--min-score",
        type=float,
        default=60.0,
        metavar="N",
        help="Minimum T.R.U.S.T. score to pass (default: 60)",
    )
    trust_gate_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    gate_parser = sub.add_parser(
        "gate",
        help="CI/CD gate pipeline commands (evaluate, run, trust-gate)",
    )
    gate_sub = gate_parser.add_subparsers(dest="gate_command", metavar="<action>")

    gate_run_parser = gate_sub.add_parser(
        "run",
        help="Parse and execute a YAML gate pipeline file",
    )
    gate_run_parser.add_argument(
        "gate_yaml",
        metavar="GATE_YAML",
        help="Path to the gate pipeline YAML file",
    )
    gate_run_parser.add_argument(
        "--context",
        action="append",
        metavar="KEY=VALUE",
        help="Context variable for ${var} substitution (repeatable)",
    )
    gate_run_parser.add_argument(
        "--artifact-dir",
        dest="artifact_dir",
        default=None,
        metavar="DIR",
        help="Override the artifact storage directory",
    )
    gate_run_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    gate_eval_parser = gate_sub.add_parser(
        "evaluate",
        help="Evaluate a single named gate against a payload file or stdin",
    )
    gate_eval_parser.add_argument(
        "gate_id",
        metavar="GATE_ID",
        help="Gate identifier to evaluate",
    )
    gate_eval_parser.add_argument(
        "--payload",
        default=None,
        metavar="FILE",
        help="Path to a JSON payload file (default: read from stdin)",
    )
    gate_eval_parser.add_argument(
        "--project-id",
        dest="project_id",
        default="",
        metavar="ID",
        help="Project scope for artifact isolation",
    )
    gate_eval_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    gate_tg_parser = gate_sub.add_parser(
        "trust-gate",
        help="Run the composite trust gate check against live telemetry windows",
    )
    gate_tg_parser.add_argument(
        "--project-id",
        dest="project_id",
        default="",
        metavar="ID",
        help="Project scope for the trust gate check",
    )
    gate_tg_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    gate_audit_parser = gate_sub.add_parser(
        "audit",
        help="Audit a JSONL event log against a gate pipeline file and report policy violations",
    )
    gate_audit_parser.add_argument(
        "source",
        metavar="EVENTS_JSONL",
        help="Path to the JSONL event log file to audit",
    )
    gate_audit_parser.add_argument(
        "--gate",
        dest="gate_file",
        default=None,
        metavar="GATE_YAML",
        help="Gate pipeline YAML file (omit to use spanforge.gate.yaml in cwd)",
    )
    gate_audit_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        dest="output_format",
        help="Output format: text (default) or json",
    )
    gate_audit_parser.add_argument(
        "--fail-on-violation",
        dest="fail_on_violation",
        action="store_true",
        default=False,
        help="Exit 1 if any policy violations found (CI gate mode)",
    )

    gate_status_parser = gate_sub.add_parser(
        "status",
        help="Show current gate pipeline status and recent run summary",
    )
    gate_status_parser.add_argument(
        "--project-id",
        dest="project_id",
        default="",
        metavar="ID",
        help="Project scope (default: from config or cwd)",
    )
    gate_status_parser.add_argument(
        "--artifact-dir",
        dest="artifact_dir",
        default=None,
        metavar="DIR",
        help="Artifact directory to scan (default: .sf-gate/artifacts)",
    )
    gate_status_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    gate_history_parser = gate_sub.add_parser(
        "history",
        help="Show gate run history with pass/fail timeline",
    )
    gate_history_parser.add_argument(
        "--project-id",
        dest="project_id",
        default="",
        metavar="ID",
        help="Project scope (default: from config or cwd)",
    )
    gate_history_parser.add_argument(
        "--limit",
        type=int,
        default=10,
        metavar="N",
        help="Maximum number of runs to show (default: 10)",
    )
    gate_history_parser.add_argument(
        "--since",
        default=None,
        metavar="ISO_DATE",
        help="Filter runs since this ISO-8601 timestamp",
    )
    gate_history_parser.add_argument(
        "--artifact-dir",
        dest="artifact_dir",
        default=None,
        metavar="DIR",
        help="Artifact directory to scan (default: .sf-gate/artifacts)",
    )
    gate_history_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    gate_policy_parser = gate_sub.add_parser(
        "load-policy",
        help="Load and validate a YAML runtime policy bundle",
    )
    gate_policy_parser.add_argument(
        "policy_yaml",
        metavar="POLICY_YAML",
        help="Path to a runtime policy YAML file",
    )
    gate_policy_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Validate the policy file without applying it",
    )
    gate_policy_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    sub.add_parser(
        "doctor",
        help="Run environment health checks: config, services, patterns, connectivity",
    )

    operator_parser = sub.add_parser(
        "operator",
        help="Operator workflow inspection and evidence export",
    )
    operator_sub = operator_parser.add_subparsers(dest="operator_command", metavar="<action>")

    operator_inspect_parser = operator_sub.add_parser(
        "inspect",
        help="Inspect one runtime-governance trace workflow",
    )
    operator_inspect_parser.add_argument(
        "trace_id",
        metavar="TRACE_ID",
        help="Trace identifier to inspect",
    )
    operator_inspect_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    operator_export_parser = operator_sub.add_parser(
        "export",
        help="Export a signed operator evidence package for one trace",
    )
    operator_export_parser.add_argument(
        "trace_id",
        metavar="TRACE_ID",
        help="Trace identifier to export",
    )
    operator_export_parser.add_argument(
        "--output",
        default=None,
        metavar="PATH",
        help="Optional JSON output path for the export package",
    )
    operator_export_parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format when writing to stdout (default: text)",
    )

    return config_parser, trust_parser, gate_parser, operator_parser


def dispatch_ops_command(
    args: argparse.Namespace,
    config_parser: argparse.ArgumentParser,
    trust_parser: argparse.ArgumentParser,
    gate_parser: argparse.ArgumentParser,
    operator_parser: argparse.ArgumentParser,
) -> int | None:
    """Dispatch operational commands when selected."""
    command = getattr(args, "command", None)
    if command == "config":
        config_action = getattr(args, "config_command", None)
        if config_action == "validate":
            # Prefer new CARD 1D-1 validator if --config flag is set, else legacy
            from spanforge._cli_config import cmd_config_validate as _new_validate
            if getattr(args, "config", None) or not getattr(args, "file", None):
                return _new_validate(args)
            return _cmd_config_validate(args)
        if config_action == "init":
            from spanforge._cli_config import cmd_config_init
            return cmd_config_init(args)
        config_parser.print_help()
        return 2
    if command == "trust":
        return _cmd_trust(args, trust_parser)
    if command == "gate":
        return _cmd_gate(args, gate_parser)
    if command == "operator":
        return _cmd_operator(args, operator_parser)
    if command == "doctor":
        return _cmd_doctor(args)
    return None


def _cmd_operator(args: argparse.Namespace, operator_parser: argparse.ArgumentParser) -> int:
    """Handle ``spanforge operator`` subcommands."""
    action = getattr(args, "operator_command", None)

    if action == "inspect":
        return _cmd_operator_inspect(args)
    if action == "export":
        return _cmd_operator_export(args)

    operator_parser.print_help()
    return 2


def _cmd_gate(args: argparse.Namespace, gate_parser: argparse.ArgumentParser) -> int:
    """Handle ``spanforge gate`` subcommands."""
    action = getattr(args, "gate_command", None)

    if action == "run":
        return _cmd_gate_run(args)
    if action == "evaluate":
        return _cmd_gate_evaluate(args)
    if action == "trust-gate":
        return _cmd_trust_gate(args)
    if action == "audit":
        return _cmd_gate_audit(args)
    if action == "status":
        return _cmd_gate_status(args)
    if action == "history":
        return _cmd_gate_history(args)
    if action == "load-policy":
        return _cmd_gate_load_policy(args)

    gate_parser.print_help()
    return 2


def _cmd_gate_run(args: argparse.Namespace) -> int:
    """``spanforge gate run`` - execute a YAML gate pipeline file."""
    import json as _json

    from spanforge.gate import GateRunner

    gate_yaml = args.gate_yaml
    fmt = getattr(args, "format", "text")
    artifact_dir = getattr(args, "artifact_dir", None)
    raw_context: list[str] = getattr(args, "context", []) or []

    context: dict[str, str] = {}
    for kv in raw_context:
        if "=" not in kv:
            print(f"error: --context value must be KEY=VALUE, got {kv!r}", file=sys.stderr)
            return 2
        key, _, value = kv.partition("=")
        context[key.strip()] = value

    if artifact_dir:
        os.environ.setdefault("SPANFORGE_GATE_ARTIFACT_DIR", artifact_dir)

    try:
        runner = GateRunner()
        result = runner.run(gate_yaml, context or None)
    except FileNotFoundError:
        print(f"error: gate YAML not found: {gate_yaml}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if fmt == "json":
        print(
            _json.dumps(
                result.to_dict()
                if hasattr(result, "to_dict")
                else {
                    "overall_pass": result.overall_pass,
                    "exit_code": result.exit_code,
                    "run_id": result.run_id,
                    "duration_ms": result.duration_ms,
                    "gates": [
                        {
                            "gate_id": gate.gate_id,
                            "name": gate.name,
                            "verdict": gate.verdict.value
                            if hasattr(gate.verdict, "value")
                            else str(gate.verdict),
                            "duration_ms": gate.duration_ms,
                            "detail": gate.detail,
                            "metrics": gate.metrics,
                        }
                        for gate in result.gates
                    ],
                },
                indent=2,
            )
        )
    else:
        print(f"Running gate pipeline: {gate_yaml}")
        for gate in result.gates:
            verdict_str = gate.verdict.value if hasattr(gate.verdict, "value") else str(gate.verdict)
            detail_str = f"  {gate.detail}" if gate.detail else ""
            print(f"  [{verdict_str}] {gate.name or gate.gate_id}  ({gate.duration_ms} ms){detail_str}")
        passed = sum(
            1
            for gate in result.gates
            if str(getattr(gate.verdict, "value", gate.verdict)).upper() in ("PASS",)
        )
        warned = sum(
            1
            for gate in result.gates
            if str(getattr(gate.verdict, "value", gate.verdict)).upper() in ("WARN",)
        )
        failed = sum(
            1
            for gate in result.gates
            if str(getattr(gate.verdict, "value", gate.verdict)).upper() in ("FAIL", "ERROR")
        )
        print(f"Result: {passed} passed, {failed} failed, {warned} warned")

    return int(getattr(result, "exit_code", 0))


def _cmd_gate_evaluate(args: argparse.Namespace) -> int:
    """``spanforge gate evaluate`` - evaluate a single named gate."""
    import json as _json

    from spanforge.sdk import sf_gate

    gate_id: str = args.gate_id
    project_id: str = getattr(args, "project_id", "") or ""
    payload_file = getattr(args, "payload", None)
    fmt = getattr(args, "format", "text")

    payload: dict[str, object] = {}
    if payload_file:
        try:
            with open(payload_file, encoding="utf-8") as fh:
                payload = _json.load(fh)
        except (OSError, _json.JSONDecodeError) as exc:
            print(f"error reading payload: {exc}", file=sys.stderr)
            return 2
    elif not sys.stdin.isatty():
        try:
            payload = _json.load(sys.stdin)
        except _json.JSONDecodeError as exc:
            print(f"error: invalid JSON on stdin: {exc}", file=sys.stderr)
            return 2

    try:
        result = sf_gate.evaluate(gate_id, payload, project_id=project_id)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    verdict_str = result.verdict.value if hasattr(result.verdict, "value") else str(result.verdict)
    exit_code = 0 if verdict_str.upper() in ("PASS", "WARN") else 1

    if fmt == "json":
        print(
            _json.dumps(
                {
                    "gate_id": result.gate_id,
                    "verdict": verdict_str,
                    "metrics": result.metrics,
                    "artifact_url": result.artifact_url,
                    "duration_ms": result.duration_ms,
                },
                indent=2,
            )
        )
    else:
        print(f"[{verdict_str}] {gate_id}  ({result.duration_ms} ms)")

    return exit_code


def _cmd_trust(args: argparse.Namespace, trust_parser: argparse.ArgumentParser) -> int:
    """Handle ``spanforge trust`` subcommands."""
    action = getattr(args, "trust_command", None)

    if action == "scorecard":
        return _cmd_trust_scorecard(args)
    if action == "badge":
        return _cmd_trust_badge(args)
    if action == "gate":
        return _cmd_trust_gate(args)

    trust_parser.print_help()
    return 2


def _cmd_trust_scorecard(args: argparse.Namespace) -> int:
    """``spanforge trust scorecard`` - show T.R.U.S.T. scorecard."""
    from spanforge.sdk import sf_trust

    project_id = getattr(args, "project_id", "") or ""
    fmt = getattr(args, "format", "text")

    try:
        scorecard = sf_trust.get_scorecard(project_id=project_id or None)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if fmt == "json":
        import json as _json

        data = {
            "project_id": scorecard.project_id,
            "overall_score": scorecard.overall_score,
            "colour_band": scorecard.colour_band,
            "transparency": {
                "score": scorecard.transparency.score,
                "trend": scorecard.transparency.trend,
            },
            "reliability": {
                "score": scorecard.reliability.score,
                "trend": scorecard.reliability.trend,
            },
            "user_trust": {
                "score": scorecard.user_trust.score,
                "trend": scorecard.user_trust.trend,
            },
            "security": {"score": scorecard.security.score, "trend": scorecard.security.trend},
            "traceability": {
                "score": scorecard.traceability.score,
                "trend": scorecard.traceability.trend,
            },
            "record_count": scorecard.record_count,
        }
        print(_json.dumps(data, indent=2))
    else:
        band = scorecard.colour_band.upper()
        print(f"T.R.U.S.T. Scorecard - {scorecard.project_id or '(default project)'}")
        print(f"  Overall: {scorecard.overall_score:.1f} [{band}]")
        print(f"  Transparency:  {scorecard.transparency.score:.1f} ({scorecard.transparency.trend})")
        print(f"  Reliability:   {scorecard.reliability.score:.1f} ({scorecard.reliability.trend})")
        print(f"  UserTrust:     {scorecard.user_trust.score:.1f} ({scorecard.user_trust.trend})")
        print(f"  Security:      {scorecard.security.score:.1f} ({scorecard.security.trend})")
        print(
            f"  Traceability:  {scorecard.traceability.score:.1f} ({scorecard.traceability.trend})"
        )
        print(f"  Records: {scorecard.record_count}")

        # Gap report: show dimensions below threshold
        min_score = getattr(args, "min_score", 70.0)
        dim_scores = [
            ("Transparency", scorecard.transparency.score),
            ("Reliability", scorecard.reliability.score),
            ("UserTrust", scorecard.user_trust.score),
            ("Security", scorecard.security.score),
            ("Traceability", scorecard.traceability.score),
        ]
        gaps = [(name, score) for name, score in dim_scores if score < min_score]
        if gaps:
            print(f"\nGap Report (dimensions below {min_score:.0f}):")
            for dim_name, dim_score in gaps:
                shortfall = min_score - dim_score
                print(f"  [GAP] {dim_name}: {dim_score:.1f} — {shortfall:.1f} points below threshold")
        else:
            print(f"\nGap Report: all dimensions meet the {min_score:.0f} threshold.")

    return 0


def _cmd_trust_badge(args: argparse.Namespace) -> int:
    """``spanforge trust badge`` - generate T.R.U.S.T. badge SVG."""
    from spanforge.sdk import sf_trust

    project_id = getattr(args, "project_id", "") or ""
    output = getattr(args, "output", None)

    try:
        badge = sf_trust.get_badge(project_id=project_id or None)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if output:
        Path(output).write_text(badge.svg, encoding="utf-8")
        print(f"Badge written to {output} (score={badge.overall:.1f}, {badge.colour_band})")
    else:
        print(badge.svg)

    return 0


def _cmd_trust_gate(args: argparse.Namespace) -> int:
    """``spanforge trust gate`` - run composite trust gate."""
    from spanforge.sdk import sf_gate, sf_trust

    project_id = getattr(args, "project_id", "") or ""
    min_score = getattr(args, "min_score", 60.0)
    fmt = getattr(args, "format", "text")

    try:
        scorecard = sf_trust.get_scorecard(project_id=project_id or None)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    failures: list[str] = []
    if scorecard.overall_score < min_score:
        failures.append(f"T.R.U.S.T. score {scorecard.overall_score} < minimum {min_score}")

    try:
        trust_gate = sf_gate.run_trust_gate(project_id=project_id)
        if not trust_gate.pass_:
            failures.extend(trust_gate.failures)
    except Exception as exc:
        failures.append(f"Trust gate error: {exc}")

    verdict = "PASS" if not failures else "FAIL"

    if fmt == "json":
        import json as _json

        print(
            _json.dumps(
                {
                    "pass": not failures,
                    "verdict": verdict,
                    "overall_score": scorecard.overall_score,
                    "colour_band": scorecard.colour_band,
                    "failures": failures,
                },
                indent=2,
            )
        )
    else:
        band = scorecard.colour_band.upper()
        print(f"Composite Trust Gate: {verdict}")
        print(f"  Score: {scorecard.overall_score:.1f} [{band}] (min: {min_score})")
        if failures:
            for failure in failures:
                print(f"  FAIL: {failure}")
        else:
            print("  All checks passed.")

    return 0 if not failures else 1


def _cmd_config_validate(args: argparse.Namespace) -> int:
    """Validate a ``.halluccheck.toml`` config file against the v6.0 schema."""
    from spanforge.sdk._exceptions import SFConfigError
    from spanforge.sdk.config import load_config_file, validate_config

    file_path = getattr(args, "file", None)

    try:
        block = load_config_file(file_path)
    except SFConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    errors = validate_config(block)
    if errors:
        print(f"Config validation failed ({len(errors)} error(s)):")
        for err in errors:
            print(f"  - {err}")
        return 1

    source = file_path or "(auto-discovered .halluccheck.toml or defaults)"
    print(f"[✓] Config is valid: {source}")
    return 0


def _cmd_doctor(_args: argparse.Namespace) -> int:
    """Run environment health checks."""
    from spanforge.sdk import (
        sf_alert,
        sf_audit,
        sf_cec,
        sf_enterprise,
        sf_gate,
        sf_identity,
        sf_observe,
        sf_pii,
        sf_secrets,
        sf_security,
        sf_trust,
    )
    from spanforge.sdk.config import load_config_file, validate_config

    pass_marker = "[✓]"  # nosec B105
    fail_marker = "[✗]"
    warn_marker = "[!]"
    failures = 0

    print("SpanForge Doctor")
    print("=" * 40)

    print("\n--- Configuration ---")
    try:
        cfg = load_config_file()
        errors = validate_config(cfg)
        if errors:
            for err in errors:
                print(f"  {fail_marker} {err}")
            failures += len(errors)
        else:
            print(f"  {pass_marker} Config valid")
        if getattr(cfg, "sandbox", False):
            print(f"  {warn_marker} Sandbox mode is ENABLED")
    except FileNotFoundError:
        print(f"  {warn_marker} No spanforge.toml found (using defaults)")
    except Exception as exc:
        print(f"  {fail_marker} Config load error: {exc}")
        failures += 1

    print("\n--- Service Status ---")
    services = [
        ("sf_identity", sf_identity),
        ("sf_pii", sf_pii),
        ("sf_secrets", sf_secrets),
        ("sf_audit", sf_audit),
        ("sf_observe", sf_observe),
        ("sf_gate", sf_gate),
        ("sf_cec", sf_cec),
        ("sf_alert", sf_alert),
        ("sf_trust", sf_trust),
        ("sf_enterprise", sf_enterprise),
        ("sf_security", sf_security),
    ]
    for name, svc in services:
        try:
            status = cast("Any", svc).get_status()
            service_state = (
                getattr(status, "status", None) if not isinstance(status, dict) else status.get("status")
            )
            if service_state == "ok":
                print(f"  {pass_marker} {name}: ok")
            else:
                print(f"  {warn_marker} {name}: {service_state}")
        except Exception as exc:
            print(f"  {fail_marker} {name}: {exc}")
            failures += 1

    print("\n--- PII Engine ---")
    try:
        pii_status = sf_pii.get_status()
        types_loaded = getattr(pii_status, "entity_types_loaded", [])
        if types_loaded:
            print(f"  {pass_marker} {len(types_loaded)} entity type(s) loaded")
        else:
            print(f"  {warn_marker} No PII entity types loaded (Presidio not available?)")
    except Exception as exc:
        print(f"  {fail_marker} PII status error: {exc}")
        failures += 1

    print("\n--- Compliance Posture ---")
    try:
        from datetime import datetime, timezone

        from spanforge.core.compliance_mapping import ComplianceMappingEngine

        engine = ComplianceMappingEngine()
        store_events = engine._load_from_store()
        if store_events:
            _today = datetime.now(timezone.utc)
            _from = _today.strftime("%Y-%m-01")
            _to = _today.strftime("%Y-%m-%d")
            try:
                pkg = engine.generate_evidence_package(
                    model_id="*",
                    framework="eu_ai_act",
                    from_date=_from,
                    to_date=_to,
                    audit_events=store_events,
                )
                passing = sum(1 for r in pkg.attestation.clauses if r.status.value == "pass")
                total = len(pkg.attestation.clauses)
                gaps = pkg.gap_report.gap_clause_ids
                partials = pkg.gap_report.partial_clause_ids
                overall = pkg.attestation.overall_status.value.upper()
                icon = pass_marker if overall == "PASS" else (warn_marker if not gaps else fail_marker)
                print(f"  {icon} EU AI Act posture: {passing}/{total} clauses passing — {overall}")
                if gaps:
                    print(f"  {fail_marker} Gaps: {', '.join(gaps)}")
                if partials:
                    print(f"  {warn_marker} Partial: {', '.join(partials)}")
                print("     Run `spanforge compliance readiness` for a full pre-audit checklist.")
            except Exception as _ce:
                print(f"  {warn_marker} Could not evaluate compliance posture: {_ce}")
        else:
            print(f"  {warn_marker} No events in store — instrument your first LLM call to see posture.")
            print("     Run `spanforge compliance readiness` for a pre-audit config check.")
    except Exception as _exc:
        print(f"  {warn_marker} Compliance posture check unavailable: {_exc}")

    print("\n" + "=" * 40)
    if failures == 0:
        print(f"{pass_marker} All checks passed.")
        return 0

    print(f"{fail_marker} {failures} check(s) failed.")
    return 1


def _cmd_operator_inspect(args: argparse.Namespace) -> int:
    """``spanforge operator inspect`` - inspect one operator workflow trace."""
    from spanforge.sdk import sf_operator

    fmt = getattr(args, "format", "text")
    trace_id = getattr(args, "trace_id", "")

    try:
        workflow = sf_operator.inspect_trace(trace_id)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if fmt == "json":
        print(json.dumps(workflow.to_dict(), indent=2))
    else:
        print(f"Trace: {workflow.trace_id}")
        print(f"Outcome: {workflow.outcome}")
        print(f"Summary: {workflow.summary}")
        print(f"Policy decisions: {len(workflow.policy_decisions)}")
        print(f"Grounding results: {len(workflow.grounding_results)}")
        print(f"Scope decisions: {len(workflow.scope_decisions)}")
        print(f"RBAC decisions: {len(workflow.rbac_decisions)}")
        print(f"Lineage records: {len(workflow.lineage_records)}")
        print(f"Signed audit records: {len(workflow.audit_records)}")

    return 0


def _cmd_operator_export(args: argparse.Namespace) -> int:
    """``spanforge operator export`` - export a signed trace evidence package."""
    from spanforge.sdk import sf_operator

    trace_id = getattr(args, "trace_id", "")
    output = getattr(args, "output", None)
    fmt = getattr(args, "format", "text")

    try:
        package = sf_operator.export_package(trace_id, output_path=output)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if fmt == "json":
        print(json.dumps(package.to_dict(), indent=2))
    elif output:
        print(f"Evidence package written to {output}")
    else:
        print(f"Package: {package.package_id}")
        print(f"Trace: {package.trace_id}")
        print(f"Outcome: {package.outcome}")
        print(f"Records: {package.exported_records}")
        print(f"Signature: {package.signature}")

    return 0


# ---------------------------------------------------------------------------
# Policy Auditor (Task 2.7) — gate audit
# ---------------------------------------------------------------------------

def _cmd_gate_audit(args: argparse.Namespace) -> int:
    """Implement ``spanforge gate audit`` — policy auditor."""
    import json as _json
    import sys
    from pathlib import Path as _Path

    source_path = _Path(args.source)
    if not source_path.exists():
        print(f"error: file not found: {source_path}", file=sys.stderr)
        return 2

    gate_file = getattr(args, "gate_file", None)
    output_format = getattr(args, "output_format", "text")
    fail_on_violation = getattr(args, "fail_on_violation", False)

    # Locate gate file
    if gate_file is None:
        candidates = [
            _Path("spanforge.gate.yaml"),
            _Path("spanforge.gate.yml"),
            _Path(".spanforge/gate.yaml"),
        ]
        for c in candidates:
            if c.exists():
                gate_file = str(c)
                break

    # Load events from JSONL
    events_raw: list[dict[str, object]] = []
    parse_errors = 0
    with source_path.open(encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                events_raw.append(_json.loads(line))
            except _json.JSONDecodeError:
                parse_errors += 1

    violations: list[dict[str, object]] = []

    if gate_file and _Path(gate_file).exists():
        # Use the GateRunner to evaluate each event against gate policies
        try:
            from spanforge.gate import GateRunner
            runner = GateRunner()
            for i, ev in enumerate(events_raw):
                try:
                    result = runner.run(gate_file, context={"event": _json.dumps(ev)})
                    if not result.overall_pass:
                        failed_gates = []
                        if hasattr(result, "gate_results"):
                            for gr in result.gate_results:
                                if not gr.passed:
                                    failed_gates.append(getattr(gr, "gate_id", str(gr)))
                        violations.append({
                            "event_index": i,
                            "event_id": ev.get("event_id", "(unknown)"),
                            "event_type": ev.get("event_type", "(unknown)"),
                            "failed_gates": failed_gates,
                        })
                except Exception:
                    pass
        except ImportError:
            print("warning: GateRunner not available, falling back to schema-only audit", file=sys.stderr)
            gate_file = None

    # Fallback: basic policy checks without a gate YAML
    if not gate_file or not _Path(str(gate_file)).exists():
        for i, ev in enumerate(events_raw):
            ev_violations: list[str] = []
            # Rule 1: Must have event_id
            if not ev.get("event_id"):
                ev_violations.append("missing event_id")
            # Rule 2: Must have event_type
            if not ev.get("event_type"):
                ev_violations.append("missing event_type")
            # Rule 3: Must have timestamp
            if not ev.get("timestamp"):
                ev_violations.append("missing timestamp")
            # Rule 4: Must have source
            if not ev.get("source"):
                ev_violations.append("missing source field")
            # Rule 5: schema_version must be present
            if not ev.get("schema_version"):
                ev_violations.append("missing schema_version")
            if ev_violations:
                violations.append({
                    "event_index": i,
                    "event_id": ev.get("event_id", "(unknown)"),
                    "event_type": ev.get("event_type", "(unknown)"),
                    "policy_violations": ev_violations,
                })

    total = len(events_raw)
    vcount = len(violations)

    if output_format == "json":
        print(_json.dumps({
            "source": str(source_path),
            "gate_file": gate_file,
            "total_events": total,
            "parse_errors": parse_errors,
            "violations_found": vcount,
            "violations": violations,
        }, indent=2))
    else:
        print(f"Policy Audit: {source_path}")
        print(f"  Gate file:     {gate_file or '(built-in rules)'}")
        print(f"  Total events:  {total}")
        print(f"  Parse errors:  {parse_errors}")
        print(f"  Violations:    {vcount}")
        print()
        if violations:
            for v in violations:
                rules = v.get("policy_violations") or v.get("failed_gates") or []
                print(f"  [{v['event_index']}] {v['event_id']} ({v['event_type']})")
                for r in rules:
                    print(f"       ! {r}")
            print()
        if not violations:
            print("OK -- all events pass policy checks.")

    if fail_on_violation and violations:
        return 1
    return 0


def _cmd_gate_status(args: argparse.Namespace) -> int:
    """``spanforge gate status`` — show most recent gate run summary."""
    import json as _json
    from pathlib import Path as _Path

    artifact_dir = _Path(getattr(args, "artifact_dir", None) or ".sf-gate/artifacts")
    fmt = getattr(args, "format", "text")

    if not artifact_dir.exists():
        if fmt == "json":
            print(_json.dumps({"status": "no_runs", "artifact_dir": str(artifact_dir)}, indent=2))
        else:
            print(f"No gate runs found in {artifact_dir}.")
        return 0

    # Collect all result JSON files from the artifact directory
    result_files = sorted(artifact_dir.glob("*_result.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not result_files:
        if fmt == "json":
            print(_json.dumps({"status": "no_runs", "artifact_dir": str(artifact_dir)}, indent=2))
        else:
            print(f"No gate run artifacts found in {artifact_dir}.")
        return 0

    # Load the most recent result
    latest = result_files[0]
    try:
        data = _json.loads(latest.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"error reading artifact {latest}: {exc}", file=sys.stderr)
        return 1

    if fmt == "json":
        print(_json.dumps({
            "status": "ok",
            "artifact_dir": str(artifact_dir),
            "latest_artifact": str(latest),
            "run_count": len(result_files),
            "latest": data,
        }, indent=2))
        return 0

    verdict = data.get("verdict", data.get("overall_pass", "unknown"))
    gate_id = data.get("gate_id", latest.stem.replace("_result", ""))
    ts = data.get("timestamp", latest.stat().st_mtime)
    print(f"Gate Status — {artifact_dir}")
    print(f"  Artifact count: {len(result_files)}")
    print(f"  Latest gate:    {gate_id}")
    print(f"  Verdict:        {str(verdict).upper()}")
    print(f"  Timestamp:      {ts}")
    return 0


def _cmd_gate_history(args: argparse.Namespace) -> int:
    """``spanforge gate history`` — show gate run history."""
    import json as _json
    from datetime import datetime, timezone
    from pathlib import Path as _Path

    artifact_dir = _Path(getattr(args, "artifact_dir", None) or ".sf-gate/artifacts")
    limit = int(getattr(args, "limit", 10))
    since_str = getattr(args, "since", None)
    fmt = getattr(args, "format", "text")

    if not artifact_dir.exists():
        if fmt == "json":
            print(_json.dumps({"runs": [], "artifact_dir": str(artifact_dir)}, indent=2))
        else:
            print(f"No gate runs found in {artifact_dir}.")
        return 0

    result_files = sorted(artifact_dir.glob("*_result.json"), key=lambda p: p.stat().st_mtime, reverse=True)

    # Apply --since filter
    if since_str:
        try:
            since_dt = datetime.fromisoformat(since_str.replace("Z", "+00:00"))
            result_files = [
                p for p in result_files
                if datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc) >= since_dt
            ]
        except ValueError:
            print(f"error: invalid --since value {since_str!r} (expected ISO-8601)", file=sys.stderr)
            return 2

    result_files = result_files[:limit]

    runs = []
    for p in result_files:
        try:
            data = _json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        runs.append({
            "gate_id": data.get("gate_id", p.stem.replace("_result", "")),
            "verdict": data.get("verdict", data.get("overall_pass", "unknown")),
            "timestamp": data.get("timestamp", ""),
            "duration_ms": data.get("duration_ms", 0),
            "artifact": str(p),
        })

    if fmt == "json":
        print(_json.dumps({"runs": runs, "artifact_dir": str(artifact_dir)}, indent=2))
        return 0

    if not runs:
        print(f"No gate run history found in {artifact_dir}.")
        return 0

    print(f"Gate History — {artifact_dir} (showing {len(runs)} of {len(result_files)} runs)")
    print(f"  {'Gate ID':<40} {'Verdict':<8} {'Timestamp':<26} Duration")
    print("  " + "-" * 90)
    for run in runs:
        verdict = str(run["verdict"]).upper()
        gate_id = str(run["gate_id"])[:40]
        ts = str(run["timestamp"])[:25]
        dur = f"{run['duration_ms']} ms"
        print(f"  {gate_id:<40} {verdict:<8} {ts:<26} {dur}")
    return 0


def _cmd_gate_load_policy(args: argparse.Namespace) -> int:
    """``spanforge gate load-policy`` — load and validate a YAML runtime policy bundle."""
    import json as _json
    from pathlib import Path as _Path

    policy_path = _Path(args.policy_yaml)
    dry_run = getattr(args, "dry_run", False)
    fmt = getattr(args, "format", "text")

    if not policy_path.exists():
        print(f"error: policy file not found: {policy_path}", file=sys.stderr)
        return 2

    try:
        import yaml  # type: ignore[import]
    except ImportError:
        print("error: PyYAML is required. Install: pip install pyyaml", file=sys.stderr)
        return 1

    try:
        raw = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        print(f"error: invalid YAML in {policy_path}: {exc}", file=sys.stderr)
        return 2

    if not isinstance(raw, dict):
        print("error: policy YAML must contain a top-level mapping", file=sys.stderr)
        return 2

    try:
        from spanforge.runtime_policy import RuntimePolicyBundle

        bundle = RuntimePolicyBundle.from_dict(raw)
    except (ValueError, KeyError) as exc:
        print(f"error: invalid policy bundle: {exc}", file=sys.stderr)
        return 1
    except ImportError as exc:
        print(f"error: runtime_policy module not available: {exc}", file=sys.stderr)
        return 1

    if fmt == "json":
        data = bundle.to_dict()
        data["dry_run"] = dry_run
        print(_json.dumps(data, indent=2))
        return 0

    action = "Validated (dry-run)" if dry_run else "Loaded"
    print(f"[✓] {action}: {bundle.policy_id} v{bundle.version}")
    print(f"  Environment: {bundle.environment}")
    print(f"  Owner:       {bundle.owner}")
    print(f"  Effective:   {bundle.effective_at}")
    print(f"  {len(bundle.rules)} rule(s) from {policy_path}")
    for rule in bundle.rules:
        enabled_str = "" if rule.enabled else " [disabled]"
        thresh_str = f" (threshold={rule.threshold})" if rule.threshold is not None else ""
        print(f"    {rule.rule_id}: {rule.service}/{rule.control} → {rule.action}{thresh_str}{enabled_str}")
    return 0
