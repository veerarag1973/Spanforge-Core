"""spanforge.integrations._pricing — Unified model pricing table (all providers).

Prices are in **USD per million tokens**.  This module consolidates pricing
data from OpenAI, Anthropic, Groq, Together AI and any future providers into
a single lookup so that ``spanforge.cost._calculate_cost()`` can resolve
costs for *any* supported model without knowing which provider it belongs to.

Individual provider modules (``anthropic.py``, ``groq.py``, ``together.py``)
still carry their own ``_PRICING`` dicts for use inside ``_compute_cost()``,
but :func:`get_pricing` here is the **canonical** cross-provider entry point.

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

    Searches **all** provider pricing tables in order: OpenAI, Anthropic,
    Groq, Together AI.  Performs an exact lookup first, then falls back to
    stripping trailing date suffixes so ``"gpt-4o-mini"`` matches
    ``"gpt-4o-mini-2024-07-18"`` entries.

    Args:
        model: Model name string exactly as returned by the provider API.

    Returns:
        Pricing dict with at least ``"input"`` and ``"output"`` keys ($/1M
        tokens), or ``None`` if the model is not in any table.
    """
    result = _lookup_in_table(model, OPENAI_PRICING)
    if result is not None:
        return result

    # Lazy-import provider tables to avoid circular imports and keep
    # the module importable even if provider packages are not installed.
    for _table_getter in (_get_anthropic_table, _get_groq_table, _get_together_table):
        table = _table_getter()
        if table is not None:
            result = _lookup_in_table(model, table)
            if result is not None:
                return result

    return None


def list_models() -> list[str]:
    """Return a sorted list of all model names across all provider pricing tables."""
    all_models: set[str] = set(OPENAI_PRICING.keys())
    for _table_getter in (_get_anthropic_table, _get_groq_table, _get_together_table):
        table = _table_getter()
        if table is not None:
            all_models.update(table.keys())
    return sorted(all_models)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _lookup_in_table(model: str, table: dict[str, dict[str, float]]) -> dict[str, float] | None:
    """Exact match, then strip trailing date suffixes."""
    if model in table:
        return table[model]

    parts = model.rsplit("-", 3)
    for i in range(len(parts) - 1, 0, -1):
        candidate = "-".join(parts[:i])
        if candidate in table:
            return table[candidate]

    # Together AI uses org/model keys — also try with org prefix stripped.
    if "/" in model:
        bare = model.split("/", 1)[1]
        for key in table:
            if "/" in key and key.split("/", 1)[1] == bare:
                return table[key]

    return None


def _get_anthropic_table() -> dict[str, dict[str, float]] | None:
    try:
        from spanforge.integrations.anthropic import ANTHROPIC_PRICING  # noqa: PLC0415
        return ANTHROPIC_PRICING
    except Exception:  # noqa: BLE001
        return None


def _get_groq_table() -> dict[str, dict[str, float]] | None:
    try:
        from spanforge.integrations.groq import GROQ_PRICING  # noqa: PLC0415
        return GROQ_PRICING
    except Exception:  # noqa: BLE001
        return None


def _get_together_table() -> dict[str, dict[str, float]] | None:
    try:
        from spanforge.integrations.together import TOGETHER_PRICING  # noqa: PLC0415
        return TOGETHER_PRICING
    except Exception:  # noqa: BLE001
        return None
