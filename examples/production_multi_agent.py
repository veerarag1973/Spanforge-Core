"""Production-scale multi-agent pipeline example with spanforge.

Demonstrates:
  - Multi-agent trace hierarchy (orchestrator → sub-agents)
  - Cost tracking and budget alerting
  - PII redaction before export
  - HMAC signing for tamper-proof audit trail
  - OTLP export to an observability backend
  - Error sampling (always emit on failure)
  - AlertManager integration

Run:
    pip install "spanforge[http]"
    SPANFORGE_SIGNING_KEY=$(python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())")
    python examples/production_multi_agent.py
"""

from __future__ import annotations

import os
import random
import time

import spanforge
from spanforge.alerts import AlertManager, SlackAlerter
from spanforge.cost import CostTracker


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

spanforge.configure(
    exporter="console",           # swap to "otlp" + endpoint in prod
    service_name="research-agent",
    env=os.environ.get("SPANFORGE_ENV", "production"),
    signing_key=os.environ.get("SPANFORGE_SIGNING_KEY"),  # HMAC signing
    sample_rate=float(os.environ.get("SPANFORGE_SAMPLE_RATE", "0.1")),
    always_sample_errors=True,
    budget_usd_per_run=0.50,      # alert if a single run exceeds $0.50
    enable_trace_store=True,
    alert_manager=AlertManager(
        # In production: replace with real Slack webhook
        alerters=[SlackAlerter(webhook_url=os.environ.get("SLACK_WEBHOOK", ""))]
        if os.environ.get("SLACK_WEBHOOK") else [],
        cooldown_seconds=300,
    ),
)

cost_tracker = CostTracker()


# ---------------------------------------------------------------------------
# Simulated sub-agent functions
# ---------------------------------------------------------------------------

def _simulate_llm_call(model: str, prompt: str, *, fail: bool = False) -> dict:
    """Fake LLM call — returns simulated token counts."""
    time.sleep(random.uniform(0.01, 0.05))  # simulate latency
    if fail:
        raise RuntimeError(f"LLM {model} returned 500 Internal Server Error")
    tokens_in = len(prompt.split())
    tokens_out = random.randint(50, 200)
    return {
        "content": f"[{model} response to: {prompt[:40]}...]",
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": (tokens_in + tokens_out) * 0.000002,
    }


def _simulate_tool_call(tool: str, args: dict) -> dict:
    time.sleep(random.uniform(0.005, 0.02))
    return {"tool": tool, "result": f"result for {args}", "ok": True}


# ---------------------------------------------------------------------------
# Sub-agents
# ---------------------------------------------------------------------------

def research_sub_agent(trace, query: str) -> str:
    """Run a research sub-agent: retrieval + summarisation."""
    with trace.tool_call("web-retrieval") as span:
        result = _simulate_tool_call("web_search", {"query": query})
        span.set_status("ok")
        span.set_attribute("result_count", 5)

    with trace.llm_call("gpt-4o") as span:
        resp = _simulate_llm_call("gpt-4o", f"Summarise research on: {query}")
        span.set_token_usage(
            input=resp["tokens_in"], output=resp["tokens_out"],
            total=resp["tokens_in"] + resp["tokens_out"],
        )
        span.set_attribute("cost_usd", resp["cost_usd"])
        span.set_status("ok")
        cost_tracker.record(resp["cost_usd"])

    return resp["content"]


def critique_sub_agent(trace, draft: str, *, inject_error: bool = False) -> str:
    """Run a critique sub-agent: evaluate and refine the draft."""
    with trace.llm_call("claude-3-5-sonnet") as span:
        resp = _simulate_llm_call(
            "claude-3-5-sonnet", f"Critique this draft: {draft[:80]}", fail=inject_error
        )
        span.set_token_usage(
            input=resp["tokens_in"], output=resp["tokens_out"],
            total=resp["tokens_in"] + resp["tokens_out"],
        )
        span.set_status("ok")
        cost_tracker.record(resp["cost_usd"])

    return resp["content"]


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def run_research_pipeline(query: str, *, inject_error: bool = False) -> str:
    """Top-level orchestration trace."""
    with spanforge.start_trace("research-pipeline", user_id="user-042") as trace:
        trace.set_attribute("query", query)

        # Step 1: Research
        with trace.span("research-phase") as phase_span:
            phase_span.add_event("phase.start", {"phase": "research"})
            draft = research_sub_agent(trace, query)
            phase_span.set_status("ok")

        # Step 2: Critique (potentially fails)
        try:
            with trace.span("critique-phase") as phase_span:
                phase_span.add_event("phase.start", {"phase": "critique"})
                final = critique_sub_agent(trace, draft, inject_error=inject_error)
                phase_span.set_status("ok")
        except RuntimeError as exc:
            print(f"[!] Critique failed: {exc} — falling back to draft")
            final = draft

        # Step 3: Cost summary
        total_cost = cost_tracker.total_cost()
        trace.set_attribute("total_cost_usd", total_cost)
        trace.set_attribute("final_answer_length", len(final))

        if total_cost > 0.50:
            from spanforge.config import get_config  # noqa: PLC0415
            cfg = get_config()
            if cfg.alert_manager:
                cfg.alert_manager.fire(
                    "budget_exceeded",
                    f"Run cost ${total_cost:.4f} exceeded $0.50 budget",
                    severity="warning",
                )

        return final


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("spanforge — production multi-agent pipeline example")
    print("=" * 60)

    # Normal run
    answer = run_research_pipeline("What are the latest advances in AI safety?")
    print(f"\nFinal answer: {answer[:100]}...")

    # Run with error injection (always emitted regardless of sample_rate)
    print("\n--- Injecting error for sampling test ---")
    answer2 = run_research_pipeline("Explain quantum computing", inject_error=True)
    print(f"Fallback answer: {answer2[:100]}...")

    print(f"\nTotal cost across all runs: ${cost_tracker.total_cost():.6f}")
