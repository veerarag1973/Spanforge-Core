"""spanforge.integrations._pricing — Static OpenAI model pricing table.

Prices are in **USD per million tokens** and reflect OpenAI's published rates as
of March 2026.  Update via patch releases when OpenAI changes prices.

Schema for each entry::

    {
        "input":        float,   # $ / 1M input tokens (required)
        "output":       float,   # $ / 1M output tokens (required)
        "cached_input": float,   # $ / 1M cached input tokens (optional)
        "reasoning":    float,   # $ / 1M reasoning tokens (optional, o1/o3 only)
        "effective_date": str,   # YYYY-MM-DD (optional)
    }
"""

from __future__ import annotations

__all__ = [
    "OPENAI_PRICING",
    "PRICING_DATE",
    "get_pricing",
    "list_models",
]

# Effective date of this pricing snapshot
PRICING_DATE: str = "2026-03-04"

# ---------------------------------------------------------------------------
# Static pricing table  (USD per million tokens)
# ---------------------------------------------------------------------------

OPENAI_PRICING: dict[str, dict[str, float]] = {
    # ------------------------------------------------------------------
    # GPT-4o family
    # ------------------------------------------------------------------
    "gpt-4o": {
        "input": 2.50,
        "output": 10.00,
        "cached_input": 1.25,
    },
    "gpt-4o-2024-11-20": {
        "input": 2.50,
        "output": 10.00,
        "cached_input": 1.25,
    },
    "gpt-4o-2024-08-06": {
        "input": 2.50,
        "output": 10.00,
        "cached_input": 1.25,
    },
    "gpt-4o-2024-05-13": {
        "input": 5.00,
        "output": 15.00,
    },
    # GPT-4o-mini
    "gpt-4o-mini": {
        "input": 0.15,
        "output": 0.60,
        "cached_input": 0.075,
    },
    "gpt-4o-mini-2024-07-18": {
        "input": 0.15,
        "output": 0.60,
        "cached_input": 0.075,
    },
    # ------------------------------------------------------------------
    # GPT-4 Turbo
    # ------------------------------------------------------------------
    "gpt-4-turbo": {
        "input": 10.00,
        "output": 30.00,
    },
    "gpt-4-turbo-2024-04-09": {
        "input": 10.00,
        "output": 30.00,
    },
    "gpt-4-0125-preview": {
        "input": 10.00,
        "output": 30.00,
    },
    "gpt-4-1106-preview": {
        "input": 10.00,
        "output": 30.00,
    },
    # ------------------------------------------------------------------
    # GPT-4 base
    # ------------------------------------------------------------------
    "gpt-4": {
        "input": 30.00,
        "output": 60.00,
    },
    "gpt-4-0613": {
        "input": 30.00,
        "output": 60.00,
    },
    # ------------------------------------------------------------------
    # GPT-3.5 Turbo
    # ------------------------------------------------------------------
    "gpt-3.5-turbo": {
        "input": 0.50,
        "output": 1.50,
    },
    "gpt-3.5-turbo-0125": {
        "input": 0.50,
        "output": 1.50,
    },
    "gpt-3.5-turbo-1106": {
        "input": 1.00,
        "output": 2.00,
    },
    # ------------------------------------------------------------------
    # o1 reasoning family
    # ------------------------------------------------------------------
    "o1": {
        "input": 15.00,
        "output": 60.00,
        "cached_input": 7.50,
        "reasoning": 60.00,
    },
    "o1-2024-12-17": {
        "input": 15.00,
        "output": 60.00,
        "cached_input": 7.50,
        "reasoning": 60.00,
    },
    "o1-mini": {
        "input": 3.00,
        "output": 12.00,
        "cached_input": 1.50,
    },
    "o1-mini-2024-09-12": {
        "input": 3.00,
        "output": 12.00,
        "cached_input": 1.50,
    },
    "o1-preview": {
        "input": 15.00,
        "output": 60.00,
        "cached_input": 7.50,
    },
    # ------------------------------------------------------------------
    # o3 reasoning family
    # ------------------------------------------------------------------
    "o3-mini": {
        "input": 1.10,
        "output": 4.40,
        "cached_input": 0.55,
    },
    "o3-mini-2025-01-31": {
        "input": 1.10,
        "output": 4.40,
        "cached_input": 0.55,
    },
    "o3": {
        "input": 10.00,
        "output": 40.00,
        "cached_input": 2.50,
    },
    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------
    "text-embedding-3-small": {
        "input": 0.02,
        "output": 0.00,
    },
    "text-embedding-3-large": {
        "input": 0.13,
        "output": 0.00,
    },
    "text-embedding-ada-002": {
        "input": 0.10,
        "output": 0.00,
    },
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_pricing(model: str) -> dict[str, float] | None:
    """Return the pricing entry for *model*, or ``None`` if unknown.

    Performs an exact lookup first, then falls back to stripping trailing
    date suffixes so ``"gpt-4o-mini"`` matches ``"gpt-4o-mini-2024-07-18"``
    entries that might have been added in future updates.

    Args:
        model: Model name string exactly as returned by the OpenAI API.

    Returns:
        Pricing dict with at least ``"input"`` and ``"output"`` keys ($/1M
        tokens), or ``None`` if the model is not in the table.
    """
    if model in OPENAI_PRICING:
        return OPENAI_PRICING[model]

    # Strip trailing version date suffix (e.g. "-2024-08-06")
    parts = model.rsplit("-", 3)
    for i in range(len(parts) - 1, 0, -1):
        candidate = "-".join(parts[:i])
        if candidate in OPENAI_PRICING:
            return OPENAI_PRICING[candidate]

    return None


def list_models() -> list[str]:
    """Return a sorted list of all model names in the pricing table."""
    return sorted(OPENAI_PRICING.keys())
