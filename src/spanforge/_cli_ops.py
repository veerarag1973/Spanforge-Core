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
) -> tuple[argparse.ArgumentParser, argparse.ArgumentParser, argparse.ArgumentParser]:
    """Register operational CLI subcommands."""
    config_parser = sub.add_parser(
        "config",
        help="Integration config management (.halluccheck.toml)",
    )
    config_sub = config_parser.add_subparsers(dest="config_command", metavar="<action>")

    config_validate_parser = config_sub.add_parser(
        "validate",
        help="Validate a .halluccheck.toml config file against the v6.0 schema",
    )
    config_validate_parser.add_argument(
        "--file",
        default=None,
        metavar="PATH",
        help="Path to .halluccheck.toml (default: auto-discover in cwd or ~)",
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

    sub.add_parser(
        "doctor",
        help="Run environment health checks: config, services, patterns, connectivity",
    )

    return config_parser, trust_parser, gate_parser


def dispatch_ops_command(
    args: argparse.Namespace,
    config_parser: argparse.ArgumentParser,
    trust_parser: argparse.ArgumentParser,
    gate_parser: argparse.ArgumentParser,
) -> int | None:
    """Dispatch operational commands when selected."""
    command = getattr(args, "command", None)
    if command == "config":
        config_action = getattr(args, "config_command", None)
        if config_action == "validate":
            return _cmd_config_validate(args)
        config_parser.print_help()
        return 2
    if command == "trust":
        return _cmd_trust(args, trust_parser)
    if command == "gate":
        return _cmd_gate(args, gate_parser)
    if command == "doctor":
        return _cmd_doctor(args)
    return None


def _cmd_gate(args: argparse.Namespace, gate_parser: argparse.ArgumentParser) -> int:
    """Handle ``spanforge gate`` subcommands."""
    action = getattr(args, "gate_command", None)

    if action == "run":
        return _cmd_gate_run(args)
    if action == "evaluate":
        return _cmd_gate_evaluate(args)
    if action == "trust-gate":
        return _cmd_trust_gate(args)

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
    else:
        if not sys.stdin.isatty():
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
        print(
            f"  Transparency:  {scorecard.transparency.score:.1f} ({scorecard.transparency.trend})"
        )
        print(f"  Reliability:   {scorecard.reliability.score:.1f} ({scorecard.reliability.trend})")
        print(f"  UserTrust:     {scorecard.user_trust.score:.1f} ({scorecard.user_trust.trend})")
        print(f"  Security:      {scorecard.security.score:.1f} ({scorecard.security.trend})")
        print(
            f"  Traceability:  {scorecard.traceability.score:.1f} ({scorecard.traceability.trend})"
        )
        print(f"  Records: {scorecard.record_count}")

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

    print("\n" + "=" * 40)
    if failures == 0:
        print(f"{pass_marker} All checks passed.")
        return 0

    print(f"{fail_marker} {failures} check(s) failed.")
    return 1
