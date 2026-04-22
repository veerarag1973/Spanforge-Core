"""Cost command group for the SpanForge CLI."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def add_cost_subcommands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> argparse.ArgumentParser:
    """Register cost-related CLI subcommands."""
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
        "--file",
        required=True,
        metavar="BRIEF_JSON",
        help="Path to a cost brief JSON file",
    )
    submit_parser.add_argument(
        "--store",
        default=".spanforge-cost-briefs.json",
        metavar="STORE_JSON",
        help="Path to the local cost brief store JSON file (default: .spanforge-cost-briefs.json)",
    )

    run_cost_parser = cost_sub.add_parser(
        "run",
        help="Show per-run cost breakdown for an agent run",
    )
    run_cost_parser.add_argument(
        "--run-id",
        required=True,
        metavar="RUN_ID",
        help="Agent run ID to look up",
    )
    run_cost_parser.add_argument(
        "--input",
        required=True,
        metavar="JSONL",
        help="Path to a JSONL events file to search",
    )

    return cost_parser


def dispatch_cost_command(args: argparse.Namespace, cost_parser: argparse.ArgumentParser) -> int | None:
    """Dispatch cost-related commands when selected."""
    if getattr(args, "command", None) != "cost":
        return None

    cost_action = getattr(args, "cost_command", None)
    brief_action = getattr(args, "brief_command", None)
    if cost_action == "brief" and brief_action == "submit":
        return _cmd_cost_brief_submit(args)
    if cost_action == "run":
        return _cmd_cost_run(args)

    cost_parser.print_help()
    return 2


def _load_cost_brief_store_json(store_path: Path) -> dict[str, Any]:
    """Load or initialise a JSON-file-backed cost brief store."""
    if store_path.exists():
        try:
            data: dict[str, Any] = json.loads(store_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
        else:
            return data
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

    required = {"model_id", "submitted_by", "resource_config", "scenarios"}
    missing = required - set(brief_data.keys())
    if missing:
        print(
            f"error: cost brief missing required fields: {', '.join(sorted(missing))}",
            file=sys.stderr,
        )
        return 2

    store_path = Path(args.store)
    store = _load_cost_brief_store_json(store_path)

    from datetime import datetime, timezone

    store[brief_data["model_id"]] = {
        **brief_data,
        "stored_at": datetime.now(timezone.utc).isoformat(),
    }
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps(store, indent=2), encoding="utf-8")

    print(f"[✓] Cost brief submitted  model_id={brief_data['model_id']!r}  store={store_path}")
    return 0


def _cmd_cost_run(args: argparse.Namespace) -> int:
    """Implement ``spanforge cost run --run-id <id> --input <jsonl>``."""
    run_id: str = args.run_id
    events_path = Path(args.input)

    if not events_path.exists():
        print(f"error: file not found: {events_path}", file=sys.stderr)
        return 2

    cost_events: list[dict[str, Any]] = []
    agent_run_event: dict[str, Any] | None = None

    for line in events_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue

        payload = event.get("payload", {})
        ns = event.get("namespace", "")

        if ns.startswith("llm.cost.") and payload.get("agent_run_id") == run_id:
            cost_events.append(event)
        elif ns == "llm.trace.agent.completed" and payload.get("agent_run_id") == run_id:
            agent_run_event = event

    if not cost_events and agent_run_event is None:
        print(f"error: no events found for run_id={run_id!r}", file=sys.stderr)
        return 1

    by_model: dict[str, dict[str, float]] = {}
    total_usd = 0.0
    total_input_tokens = 0
    total_output_tokens = 0

    for ev in cost_events:
        payload = ev.get("payload", {})
        cost_data = payload.get("cost", {})
        model_data = payload.get("model", {})
        model_name = (
            model_data.get("name", "unknown") if isinstance(model_data, dict) else "unknown"
        )

        input_cost = float(cost_data.get("input_cost_usd", 0.0))
        output_cost = float(cost_data.get("output_cost_usd", 0.0))
        total_cost = float(cost_data.get("total_cost_usd", 0.0))

        token_data = payload.get("token_usage", {})
        input_tokens = int(token_data.get("input_tokens", 0))
        output_tokens = int(token_data.get("output_tokens", 0))

        if model_name not in by_model:
            by_model[model_name] = {
                "input_cost": 0.0,
                "output_cost": 0.0,
                "total_cost": 0.0,
                "input_tokens": 0,
                "output_tokens": 0,
                "calls": 0,
            }
        by_model[model_name]["input_cost"] += input_cost
        by_model[model_name]["output_cost"] += output_cost
        by_model[model_name]["total_cost"] += total_cost
        by_model[model_name]["input_tokens"] += input_tokens
        by_model[model_name]["output_tokens"] += output_tokens
        by_model[model_name]["calls"] += 1

        total_usd += total_cost
        total_input_tokens += input_tokens
        total_output_tokens += output_tokens

    agent_name = "unknown"
    run_status = "unknown"
    run_duration_ms = 0.0
    if agent_run_event:
        run_payload = agent_run_event.get("payload", {})
        agent_name = run_payload.get("agent_name", "unknown")
        run_status = run_payload.get("status", "unknown")
        run_duration_ms = float(run_payload.get("duration_ms", 0.0))
        run_cost = run_payload.get("total_cost", {})
        if run_cost:
            total_usd = max(total_usd, float(run_cost.get("total_cost_usd", total_usd)))

    lines: list[str] = []
    lines.append("=" * 62)
    lines.append("  SpanForge Per-Run Cost Report")
    lines.append("=" * 62)
    lines.append(f"  Run ID         : {run_id}")
    lines.append(f"  Agent          : {agent_name}")
    lines.append(f"  Status         : {run_status}")
    if run_duration_ms > 0:
        lines.append(f"  Duration       : {run_duration_ms:,.1f} ms")
    lines.append(f"  Total cost     : ${total_usd:.6f}")
    lines.append(f"  Input tokens   : {total_input_tokens:,}")
    lines.append(f"  Output tokens  : {total_output_tokens:,}")
    lines.append(f"  LLM calls      : {len(cost_events)}")
    lines.append("-" * 62)

    if by_model:
        lines.append("  Cost by model:")
        lines.append(
            f"  {'Model':<30s} {'Calls':>5s} {'Input $':>9s} {'Output $':>9s} {'Total $':>10s}"
        )
        lines.append(f"  {'-' * 30} {'-' * 5} {'-' * 9} {'-' * 9} {'-' * 10}")
        for model_name, data in sorted(
            by_model.items(), key=lambda kv: kv[1]["total_cost"], reverse=True
        ):
            lines.append(
                f"  {model_name:<30s} {int(data['calls']):>5d} "
                f"${data['input_cost']:>8.6f} ${data['output_cost']:>8.6f} ${data['total_cost']:>9.6f}"
            )

    lines.append("=" * 62)
    print("\n".join(lines))
    return 0
