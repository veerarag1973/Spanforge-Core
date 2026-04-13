"""examples/budget_alert.py — Cost tracking and budget alert integration.

Demonstrates:
* Attaching token usage and cost estimates to spans.
* Using the CostGuard / budget alert callback to receive notifications when
  spend crosses a threshold.
* Recording the alert as an eval score (pass/fail) on the span.

Run
---
::

    pip install spanforge
    python examples/budget_alert.py
"""

from __future__ import annotations

import spanforge
from spanforge import configure, start_span
from spanforge.eval import record_eval_score

# ---------------------------------------------------------------------------
# Budget alert callback
# ---------------------------------------------------------------------------

_BUDGET_USD = 0.05  # 5 cents per trace
_alerts_fired: list[dict] = []


def on_budget_exceeded(info: dict) -> None:
    """Called when a span's estimated cost crosses the budget threshold."""
    _alerts_fired.append(info)
    print(
        f"[ALERT] Budget exceeded! "
        f"trace_id={info.get('trace_id')} "
        f"cost=${info.get('estimated_cost_usd', 0):.4f} "
        f"budget=${_BUDGET_USD:.4f}"
    )


configure(
    exporter="console",
    service_name="budget-demo",
    service_version="1.0.0",
    export_error_callback=lambda exc: print(f"[export error] {exc}"),
)

# ---------------------------------------------------------------------------
# Simulated priced LLM calls
# ---------------------------------------------------------------------------

# GPT-4o pricing (illustrative).
_PROMPT_PRICE_PER_1K = 0.005    # $0.005 / 1K prompt tokens
_COMPLETION_PRICE_PER_1K = 0.015  # $0.015 / 1K completion tokens


def estimate_cost(prompt_tokens: int, completion_tokens: int) -> float:
    return (
        prompt_tokens / 1000 * _PROMPT_PRICE_PER_1K
        + completion_tokens / 1000 * _COMPLETION_PRICE_PER_1K
    )


def llm_call(prompt: str, prompt_tokens: int, completion_tokens: int) -> str:
    """Simulate an LLM call and record cost on the span."""
    cost = estimate_cost(prompt_tokens, completion_tokens)

    with start_span("llm_call") as span:
        span.set_attribute("gen_ai.system", "openai")
        span.set_attribute("gen_ai.request.model", "gpt-4o")
        span.set_attribute("gen_ai.usage.input_tokens", prompt_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", completion_tokens)
        span.set_attribute("gen_ai.estimated_cost_usd", round(cost, 6))

        # Record a pass/fail eval score based on budget.
        under_budget = cost <= _BUDGET_USD
        record_eval_score(
            "budget_check",
            value=1.0 if under_budget else 0.0,
            span_id=span.span_id,
            trace_id=span.trace_id,
            label="pass" if under_budget else "fail",
            metadata={"cost_usd": round(cost, 6), "budget_usd": _BUDGET_USD},
        )

        if not under_budget:
            on_budget_exceeded({
                "trace_id": span.trace_id,
                "span_id": span.span_id,
                "estimated_cost_usd": round(cost, 6),
            })

        return f"[simulated response to: {prompt[:40]}]"


# ---------------------------------------------------------------------------
# Demo: run several calls
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    calls = [
        ("Summarise this 10-page document.", 2000, 500),
        ("Translate this paragraph.", 200, 150),
        ("Write a 2000-word essay.",  500, 4000),  # large → should exceed budget
    ]

    for prompt, p_toks, c_toks in calls:
        response = llm_call(prompt, p_toks, c_toks)
        cost = estimate_cost(p_toks, c_toks)
        print(f"Cost: ${cost:.4f}  | {response}")

    print(f"\nTotal alerts fired: {len(_alerts_fired)}")
    spanforge.flush()
