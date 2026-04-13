"""tests/test_costguard_gaps.py — Tests for CostGuard gaps 1-3.

Gap 1: Multi-agent cost rollup (child run costs bubble to parent).
Gap 2: Unified pricing table (all providers resolved from _pricing.get_pricing).
Gap 3: Per-run cost report CLI (spanforge cost run --run-id <id> --input <jsonl>).
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from spanforge._span import (
    AgentRunContext,
    AgentRunContextManager,
    AgentStepContext,
    _run_stack_var,
    _span_id,
    _trace_id,
    _now_ns,
)
from spanforge.namespaces.trace import CostBreakdown, TokenUsage


# ===========================================================================
# Fixtures
# ===========================================================================


@pytest.fixture(autouse=True)
def no_export(monkeypatch):
    """Suppress all export side-effects."""
    monkeypatch.setattr("spanforge._stream._dispatch", lambda event: None)


# ===========================================================================
# Gap 1: Multi-agent cost rollup
# ===========================================================================


class TestChildRunCostRollup:
    """Verify that child agent run costs bubble up to the parent."""

    @staticmethod
    def _make_step(input_cost: float = 0.0, output_cost: float = 0.0) -> AgentStepContext:
        return AgentStepContext(
            step_name="test-step",
            step_index=0,
            agent_run_id=_span_id(),
            span_id=_span_id(),
            start_ns=_now_ns(),
            end_ns=_now_ns() + 1_000_000,
            duration_ms=1.0,
            status="ok",
            tool_calls=[],
            token_usage=TokenUsage(input_tokens=100, output_tokens=50, total_tokens=150),
            cost=CostBreakdown(
                input_cost_usd=input_cost,
                output_cost_usd=output_cost,
                total_cost_usd=input_cost + output_cost,
            ),
        )

    def test_record_child_run_cost(self):
        ctx = AgentRunContext(agent_name="parent")
        child_cost = CostBreakdown(
            input_cost_usd=0.001, output_cost_usd=0.002, total_cost_usd=0.003
        )
        ctx.record_child_run_cost(child_cost)
        assert len(ctx._child_run_costs) == 1
        assert ctx._child_run_costs[0] is child_cost

    def test_child_costs_included_in_payload(self):
        ctx = AgentRunContext(agent_name="orchestrator")

        # Record one direct step
        step = self._make_step(input_cost=0.01, output_cost=0.02)
        ctx.record_step(step)

        # Record child run cost
        ctx.record_child_run_cost(CostBreakdown(
            input_cost_usd=0.05, output_cost_usd=0.10, total_cost_usd=0.15
        ))

        ctx.end()
        payload = ctx.to_agent_run_payload()

        # Total should be: step (0.01 + 0.02) + child (0.05 + 0.10) = 0.18
        assert abs(payload.total_cost.total_cost_usd - 0.18) < 1e-6
        assert abs(payload.total_cost.input_cost_usd - 0.06) < 1e-6
        assert abs(payload.total_cost.output_cost_usd - 0.12) < 1e-6

    def test_multiple_child_runs_accumulated(self):
        ctx = AgentRunContext(agent_name="orchestrator")

        ctx.record_child_run_cost(CostBreakdown(
            input_cost_usd=0.01, output_cost_usd=0.02, total_cost_usd=0.03
        ))
        ctx.record_child_run_cost(CostBreakdown(
            input_cost_usd=0.04, output_cost_usd=0.05, total_cost_usd=0.09
        ))

        ctx.end()
        payload = ctx.to_agent_run_payload()

        assert abs(payload.total_cost.input_cost_usd - 0.05) < 1e-6
        assert abs(payload.total_cost.output_cost_usd - 0.07) < 1e-6
        assert abs(payload.total_cost.total_cost_usd - 0.12) < 1e-6

    def test_no_child_costs_means_zero_delta(self):
        ctx = AgentRunContext(agent_name="solo-agent")
        step = self._make_step(input_cost=0.001, output_cost=0.002)
        ctx.record_step(step)
        ctx.end()
        payload = ctx.to_agent_run_payload()

        assert abs(payload.total_cost.input_cost_usd - 0.001) < 1e-6
        assert abs(payload.total_cost.output_cost_usd - 0.002) < 1e-6

    def test_nested_run_bubbles_cost_to_parent(self):
        """Integration test: nested AgentRunContextManagers bubble costs."""
        import spanforge

        emitted_payloads: list[dict] = []

        def capture_emit(ctx):
            emitted_payloads.append(ctx.to_agent_run_payload().to_dict())

        with patch("spanforge._stream.emit_agent_run", side_effect=capture_emit):
            with spanforge.tracer.agent_run("orchestrator") as parent:
                # Parent does its own step
                parent_step = self._make_step(input_cost=0.01, output_cost=0.02)
                parent.record_step(parent_step)

                with spanforge.tracer.agent_run("sub-agent") as child:
                    child_step = self._make_step(input_cost=0.05, output_cost=0.10)
                    child.record_step(child_step)

        # Two payloads emitted: child first, then parent
        assert len(emitted_payloads) == 2

        child_payload = emitted_payloads[0]
        parent_payload = emitted_payloads[1]

        # Child's own cost
        assert abs(child_payload["total_cost"]["total_cost_usd"] - 0.15) < 1e-6

        # Parent includes its own step (0.03) + child's cost (0.15) = 0.18
        assert abs(parent_payload["total_cost"]["total_cost_usd"] - 0.18) < 1e-6

    def test_three_level_nesting(self):
        """Three-level nesting: grandchild -> child -> parent."""
        import spanforge

        emitted_payloads: list[dict] = []

        def capture_emit(ctx):
            emitted_payloads.append({
                "agent": ctx.agent_name,
                "cost": ctx.to_agent_run_payload().total_cost.to_dict(),
            })

        with patch("spanforge._stream.emit_agent_run", side_effect=capture_emit):
            with spanforge.tracer.agent_run("level-0") as l0:
                l0.record_step(self._make_step(input_cost=0.01, output_cost=0.01))

                with spanforge.tracer.agent_run("level-1") as l1:
                    l1.record_step(self._make_step(input_cost=0.02, output_cost=0.02))

                    with spanforge.tracer.agent_run("level-2") as l2:
                        l2.record_step(self._make_step(input_cost=0.03, output_cost=0.03))

        assert len(emitted_payloads) == 3

        # level-2: own cost only = 0.06
        assert emitted_payloads[0]["agent"] == "level-2"
        assert abs(emitted_payloads[0]["cost"]["total_cost_usd"] - 0.06) < 1e-6

        # level-1: own (0.04) + level-2 (0.06) = 0.10
        assert emitted_payloads[1]["agent"] == "level-1"
        assert abs(emitted_payloads[1]["cost"]["total_cost_usd"] - 0.10) < 1e-6

        # level-0: own (0.02) + level-1 (0.10) = 0.12
        assert emitted_payloads[2]["agent"] == "level-0"
        assert abs(emitted_payloads[2]["cost"]["total_cost_usd"] - 0.12) < 1e-6


# ===========================================================================
# Gap 2: Unified pricing table
# ===========================================================================


class TestUnifiedPricing:
    """Verify that get_pricing resolves models from all providers."""

    def test_openai_model_resolved(self):
        from spanforge.integrations._pricing import get_pricing
        p = get_pricing("gpt-4o")
        assert p is not None
        assert "input" in p and "output" in p

    def test_anthropic_model_resolved(self):
        from spanforge.integrations._pricing import get_pricing
        p = get_pricing("claude-3-5-sonnet-20241022")
        assert p is not None
        assert p["input"] == 3.00

    def test_groq_model_resolved(self):
        from spanforge.integrations._pricing import get_pricing
        p = get_pricing("llama-3.3-70b-versatile")
        assert p is not None
        assert p["input"] == 0.59

    def test_together_model_resolved(self):
        from spanforge.integrations._pricing import get_pricing
        p = get_pricing("meta-llama/Llama-3.3-70B-Instruct-Turbo")
        assert p is not None
        assert p["input"] == 0.88

    def test_unknown_model_returns_none(self):
        from spanforge.integrations._pricing import get_pricing
        assert get_pricing("nonexistent-model-xyz") is None

    def test_list_models_includes_all_providers(self):
        from spanforge.integrations._pricing import list_models
        models = list_models()
        # Should include models from all providers
        assert "gpt-4o" in models
        assert "claude-3-5-sonnet-20241022" in models
        assert "llama-3.3-70b-versatile" in models
        assert "meta-llama/Llama-3.3-70B-Instruct-Turbo" in models

    def test_calculate_cost_resolves_anthropic(self):
        """_calculate_cost in cost.py should now resolve Anthropic models."""
        from spanforge.cost import _calculate_cost
        in_cost, out_cost, total = _calculate_cost(
            "claude-3-5-sonnet-20241022", input_tokens=1_000_000, output_tokens=1_000_000
        )
        # Anthropic pricing: input=3.00, output=15.00 per 1M tokens
        assert abs(in_cost - 3.00) < 1e-6
        assert abs(out_cost - 15.00) < 1e-6
        assert abs(total - 18.00) < 1e-6

    def test_calculate_cost_resolves_groq(self):
        from spanforge.cost import _calculate_cost
        in_cost, out_cost, total = _calculate_cost(
            "llama-3.3-70b-versatile", input_tokens=1_000_000, output_tokens=1_000_000
        )
        assert abs(in_cost - 0.59) < 1e-6
        assert abs(out_cost - 0.79) < 1e-6

    def test_calculate_cost_still_works_for_openai(self):
        from spanforge.cost import _calculate_cost
        in_cost, out_cost, total = _calculate_cost(
            "gpt-4o", input_tokens=1_000_000, output_tokens=1_000_000
        )
        assert abs(in_cost - 2.50) < 1e-6
        assert abs(out_cost - 10.00) < 1e-6


# ===========================================================================
# Gap 3: Per-run cost report CLI
# ===========================================================================


class TestCostRunCLI:
    """Verify the ``spanforge cost run`` CLI subcommand."""

    @staticmethod
    def _write_events(path: Path, events: list[dict]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")

    def test_cost_run_basic_report(self, tmp_path: Path, capsys: pytest.CaptureFixture):
        """Basic end-to-end test of cost run report."""
        from spanforge._cli import _cmd_cost_run

        events_file = tmp_path / "events.jsonl"
        run_id = "abc123def456"

        events = [
            {
                "namespace": "llm.cost.token.recorded",
                "payload": {
                    "agent_run_id": run_id,
                    "model": {"name": "gpt-4o", "system": "openai"},
                    "cost": {"input_cost_usd": 0.001, "output_cost_usd": 0.004, "total_cost_usd": 0.005},
                    "token_usage": {"input_tokens": 400, "output_tokens": 400, "total_tokens": 800},
                },
            },
            {
                "namespace": "llm.cost.token.recorded",
                "payload": {
                    "agent_run_id": run_id,
                    "model": {"name": "gpt-4o", "system": "openai"},
                    "cost": {"input_cost_usd": 0.002, "output_cost_usd": 0.008, "total_cost_usd": 0.010},
                    "token_usage": {"input_tokens": 800, "output_tokens": 800, "total_tokens": 1600},
                },
            },
            {
                "namespace": "llm.trace.agent.completed",
                "payload": {
                    "agent_run_id": run_id,
                    "agent_name": "test-agent",
                    "status": "ok",
                    "duration_ms": 1234.5,
                    "total_cost": {"input_cost_usd": 0.003, "output_cost_usd": 0.012, "total_cost_usd": 0.015},
                },
            },
            # Unrelated event (different run_id)
            {
                "namespace": "llm.cost.token.recorded",
                "payload": {
                    "agent_run_id": "other-run",
                    "model": {"name": "gpt-4o-mini", "system": "openai"},
                    "cost": {"input_cost_usd": 0.0001, "output_cost_usd": 0.0002, "total_cost_usd": 0.0003},
                    "token_usage": {"input_tokens": 100, "output_tokens": 100, "total_tokens": 200},
                },
            },
        ]
        self._write_events(events_file, events)

        class Args:
            pass

        args = Args()
        args.run_id = run_id
        args.input = str(events_file)

        rc = _cmd_cost_run(args)
        assert rc == 0

        captured = capsys.readouterr()
        assert run_id in captured.out
        assert "test-agent" in captured.out
        assert "gpt-4o" in captured.out
        assert "$0.015" in captured.out

    def test_cost_run_no_matching_events(self, tmp_path: Path, capsys: pytest.CaptureFixture):
        from spanforge._cli import _cmd_cost_run

        events_file = tmp_path / "events.jsonl"
        self._write_events(events_file, [
            {"namespace": "llm.cost.token.recorded", "payload": {"agent_run_id": "other-run"}},
        ])

        class Args:
            pass

        args = Args()
        args.run_id = "missing-run"
        args.input = str(events_file)

        rc = _cmd_cost_run(args)
        assert rc == 1

        captured = capsys.readouterr()
        assert "no events found" in captured.err

    def test_cost_run_file_not_found(self, tmp_path: Path, capsys: pytest.CaptureFixture):
        from spanforge._cli import _cmd_cost_run

        class Args:
            pass

        args = Args()
        args.run_id = "some-run"
        args.input = str(tmp_path / "nonexistent.jsonl")

        rc = _cmd_cost_run(args)
        assert rc == 2

    def test_cost_run_multiple_models(self, tmp_path: Path, capsys: pytest.CaptureFixture):
        from spanforge._cli import _cmd_cost_run

        events_file = tmp_path / "events.jsonl"
        run_id = "multi-model-run"

        events = [
            {
                "namespace": "llm.cost.token.recorded",
                "payload": {
                    "agent_run_id": run_id,
                    "model": {"name": "gpt-4o", "system": "openai"},
                    "cost": {"input_cost_usd": 0.01, "output_cost_usd": 0.04, "total_cost_usd": 0.05},
                    "token_usage": {"input_tokens": 4000, "output_tokens": 4000, "total_tokens": 8000},
                },
            },
            {
                "namespace": "llm.cost.token.recorded",
                "payload": {
                    "agent_run_id": run_id,
                    "model": {"name": "claude-3-5-sonnet-20241022", "system": "anthropic"},
                    "cost": {"input_cost_usd": 0.003, "output_cost_usd": 0.015, "total_cost_usd": 0.018},
                    "token_usage": {"input_tokens": 1000, "output_tokens": 1000, "total_tokens": 2000},
                },
            },
        ]
        self._write_events(events_file, events)

        class Args:
            pass

        args = Args()
        args.run_id = run_id
        args.input = str(events_file)

        rc = _cmd_cost_run(args)
        assert rc == 0

        captured = capsys.readouterr()
        assert "gpt-4o" in captured.out
        assert "claude-3-5-sonnet-20241022" in captured.out
        # gpt-4o costs more, should appear first
        gpt_pos = captured.out.find("gpt-4o")
        claude_pos = captured.out.find("claude-3-5-sonnet")
        assert gpt_pos < claude_pos  # sorted by descending cost
