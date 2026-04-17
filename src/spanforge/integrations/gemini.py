"""spanforge.integrations.gemini — Auto-instrumentation for the Google Generative AI SDK.

This module monkey-patches the Google ``generativeai`` client so every
``model.generate_content(...)`` call automatically populates the
active :class:`~spanforge._span.Span` with:

* :class:`~spanforge.namespaces.trace.TokenUsage` (prompt / candidate token counts)
* :class:`~spanforge.namespaces.trace.ModelInfo` (provider = ``google``, model name)
* :class:`~spanforge.namespaces.trace.CostBreakdown` (computed from the static
  pricing table below)

Usage::

    from spanforge.integrations import gemini as gemini_integration
    gemini_integration.patch()

    import google.generativeai as genai
    genai.configure(api_key="...")

    import spanforge
    spanforge.configure(exporter="console")

    with spanforge.span("gemini-chat", model="gemini-1.5-pro") as span:
        model = genai.GenerativeModel("gemini-1.5-pro")
        resp = model.generate_content("Hello")
    # → span.token_usage and span.cost auto-populated on exit

Calling ``patch()`` is **idempotent** — calling it multiple times has no
effect.  Call :func:`unpatch` to restore the original methods.

Install with::

    pip install "spanforge[gemini]"
"""

from __future__ import annotations

import functools
from typing import Any

from spanforge.namespaces.trace import (
    CostBreakdown,
    GenAISystem,
    ModelInfo,
    TokenUsage,
)

__all__ = [
    "is_patched",
    "normalize_response",
    "patch",
    "unpatch",
]

# ---------------------------------------------------------------------------
# Static pricing table  (USD per million tokens, effective 2026-03-04)
# ---------------------------------------------------------------------------

PRICING_DATE: str = "2026-03-04"

#: Google Gemini model pricing — USD per million tokens.
GEMINI_PRICING: dict[str, dict[str, float]] = {
    # ------------------------------------------------------------------
    # Gemini 2.0
    # ------------------------------------------------------------------
    "gemini-2.0-flash": {
        "input": 0.10,
        "output": 0.40,
    },
    "gemini-2.0-flash-lite": {
        "input": 0.075,
        "output": 0.30,
    },
    # ------------------------------------------------------------------
    # Gemini 1.5 family
    # ------------------------------------------------------------------
    "gemini-1.5-pro": {
        "input": 1.25,
        "output": 5.00,
    },
    "gemini-1.5-pro-latest": {
        "input": 1.25,
        "output": 5.00,
    },
    "gemini-1.5-flash": {
        "input": 0.075,
        "output": 0.30,
    },
    "gemini-1.5-flash-latest": {
        "input": 0.075,
        "output": 0.30,
    },
    "gemini-1.5-flash-8b": {
        "input": 0.0375,
        "output": 0.15,
    },
    # ------------------------------------------------------------------
    # Gemini 1.0 family
    # ------------------------------------------------------------------
    "gemini-1.0-pro": {
        "input": 0.50,
        "output": 1.50,
    },
    "gemini-pro": {
        "input": 0.50,
        "output": 1.50,
    },
}

# Sentinel attribute set on the genai module to prevent double-patching.
_PATCH_FLAG = "_spanforge_patched"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def patch() -> None:
    """Monkey-patch the Google Generative AI client to auto-instrument.

    Wraps ``generativeai.GenerativeModel.generate_content`` (sync) and
    ``generate_content_async`` (async).  The wrapper calls
    :func:`normalize_response` on the result and, if a span is currently
    active, updates it with token usage, model info, and cost.

    This function is **idempotent** — safe to call multiple times.

    Raises:
        ImportError: If the ``google-generativeai`` package is not installed.
    """
    genai_mod = _require_genai()

    if getattr(genai_mod, _PATCH_FLAG, False):
        return  # already patched

    # --- sync ----------------------------------------------------------------
    try:
        GenerativeModel = genai_mod.GenerativeModel

        _orig_sync = GenerativeModel.generate_content

        @functools.wraps(_orig_sync)
        def _patched_sync(self: Any, *args: Any, **kwargs: Any) -> Any:
            response = _orig_sync(self, *args, **kwargs)
            _auto_populate_span(response, model_name=getattr(self, "model_name", None))
            return response

        GenerativeModel.generate_content = _patched_sync
        GenerativeModel._spanforge_orig_generate_content = _orig_sync
    except (ImportError, AttributeError):  # pragma: no cover
        pass

    # --- async ---------------------------------------------------------------
    try:
        GenerativeModel = genai_mod.GenerativeModel

        _orig_async = GenerativeModel.generate_content_async

        @functools.wraps(_orig_async)
        async def _patched_async(self: Any, *args: Any, **kwargs: Any) -> Any:
            response = await _orig_async(self, *args, **kwargs)
            _auto_populate_span(response, model_name=getattr(self, "model_name", None))
            return response

        GenerativeModel.generate_content_async = _patched_async
        GenerativeModel._spanforge_orig_generate_content_async = _orig_async
    except (ImportError, AttributeError):  # pragma: no cover
        pass

    genai_mod._spanforge_patched = True  # type: ignore[attr-defined]


def unpatch() -> None:
    """Restore the original Google Generative AI methods.

    Safe to call even if :func:`patch` was never called.

    Raises:
        ImportError: If the ``google-generativeai`` package is not installed.
    """
    genai_mod = _require_genai()

    if not getattr(genai_mod, _PATCH_FLAG, False):
        return  # nothing to do

    try:
        GenerativeModel = genai_mod.GenerativeModel
        if hasattr(GenerativeModel, "_spanforge_orig_generate_content"):
            GenerativeModel.generate_content = GenerativeModel._spanforge_orig_generate_content
            del GenerativeModel._spanforge_orig_generate_content
        if hasattr(GenerativeModel, "_spanforge_orig_generate_content_async"):
            GenerativeModel.generate_content_async = (
                GenerativeModel._spanforge_orig_generate_content_async
            )
            del GenerativeModel._spanforge_orig_generate_content_async
    except (ImportError, AttributeError):  # pragma: no cover
        pass

    try:
        del genai_mod._spanforge_patched  # type: ignore[attr-defined]
    except AttributeError:  # pragma: no cover
        pass


def is_patched() -> bool:
    """Return ``True`` if the Google Generative AI client has been patched.

    Returns ``False`` if the ``google-generativeai`` package is not installed.
    """
    try:
        genai_mod = _require_genai()
        return bool(getattr(genai_mod, _PATCH_FLAG, False))
    except ImportError:
        return False


def normalize_response(
    response: Any,
    *,
    model_name: str | None = None,
) -> tuple[TokenUsage, ModelInfo, CostBreakdown]:
    """Extract structured observability data from a Gemini response.

    Works with ``google.generativeai.types.GenerateContentResponse`` objects
    and any duck-typed mock with the same attribute structure.

    Args:
        response:    A Gemini ``GenerateContentResponse`` (or compatible).
        model_name:  Optional model name override (from the GenerativeModel).

    Returns:
        A 3-tuple of ``(TokenUsage, ModelInfo, CostBreakdown)``.
    """
    # ------------------------------------------------------------------ usage
    usage_meta = getattr(response, "usage_metadata", None)
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int | None = None

    if usage_meta is not None:
        input_tokens = int(getattr(usage_meta, "prompt_token_count", 0) or 0)
        output_tokens = int(getattr(usage_meta, "candidates_token_count", 0) or 0)
        ct = getattr(usage_meta, "cached_content_token_count", None)
        if ct is not None:
            cached_tokens = int(ct)

    total_tokens = input_tokens + output_tokens

    token_usage = TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_tokens=cached_tokens,
    )

    # ---------------------------------------------------------------- model
    name = model_name or "unknown"
    # Strip "models/" prefix if present (Gemini SDK convention)
    if name.startswith("models/"):
        name = name[7:]
    model_info = ModelInfo(system=GenAISystem.GOOGLE, name=name)

    # ----------------------------------------------------------------- cost
    cost = _compute_cost(name, input_tokens, output_tokens)

    return token_usage, model_info, cost


def list_models() -> list[str]:
    """Return a sorted list of all Gemini model names in the pricing table."""
    return sorted(GEMINI_PRICING.keys())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_genai() -> Any:
    """Import and return the ``google.generativeai`` module."""
    try:
        import google.generativeai as genai  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "The 'google-generativeai' package is required for spanforge Gemini integration.\n"
            "Install it with: pip install 'spanforge[gemini]'"
        ) from exc
    else:
        return genai


def _get_pricing(model: str) -> dict[str, float] | None:
    """Return the pricing entry for *model*, or ``None`` if unknown."""
    if model in GEMINI_PRICING:
        return GEMINI_PRICING[model]

    # Try prefix match (strip trailing version date)
    parts = model.rsplit("-", 2)
    for i in range(len(parts) - 1, 0, -1):
        candidate = "-".join(parts[:i])
        if candidate in GEMINI_PRICING:
            return GEMINI_PRICING[candidate]

    return None


def _compute_cost(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
) -> CostBreakdown:
    """Compute :class:`~spanforge.namespaces.trace.CostBreakdown` from token counts."""
    pricing = _get_pricing(model_name)
    if pricing is None:
        return CostBreakdown.zero()

    input_cost = input_tokens * pricing["input"] / 1_000_000.0
    output_cost = output_tokens * pricing["output"] / 1_000_000.0
    total = input_cost + output_cost

    return CostBreakdown(
        input_cost_usd=input_cost,
        output_cost_usd=output_cost,
        total_cost_usd=total,
        pricing_date=PRICING_DATE,
    )


def _auto_populate_span(response: Any, *, model_name: str | None = None) -> None:
    """If there is an active span, populate it from *response*."""
    try:
        from spanforge._span import _span_stack

        stack = _span_stack()
        if not stack:
            return
        span = stack[-1]

        if span.token_usage is not None:
            return

        token_usage, model_info, cost = normalize_response(response, model_name=model_name)
        span.token_usage = token_usage
        span.cost = cost

        if span.model is None:
            span.model = model_info.name

    except Exception:  # NOSONAR
        pass
