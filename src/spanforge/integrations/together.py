"""spanforge.integrations.together — Auto-instrumentation for the Together AI Python SDK.

This module monkey-patches the Together AI client so every
``client.chat.completions.create(...)`` call automatically populates the
active :class:`~spanforge._span.Span` with:

* :class:`~spanforge.namespaces.trace.TokenUsage` (input / output token counts)
* :class:`~spanforge.namespaces.trace.ModelInfo` (provider = ``together_ai``,
  normalized name from response)
* :class:`~spanforge.namespaces.trace.CostBreakdown` (computed from the static
  pricing table below)

Together AI model names include an organization prefix separated by ``/``
(e.g. ``"meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"``).  This module
normalizes the name by stripping the org prefix so ``ModelInfo.name`` is
``"Meta-Llama-3.1-8B-Instruct-Turbo"``.  The full identifier (with prefix)
is retained as :attr:`~spanforge.namespaces.trace.ModelInfo.name` when the
normalized name is not found in the pricing table, to preserve observability
accuracy.

Usage::

    from spanforge.integrations import together as together_integration
    together_integration.patch()

    from together import Together
    client = Together()

    import spanforge
    spanforge.configure(exporter="console")

    with spanforge.span("together-chat") as span:
        resp = client.chat.completions.create(
            model="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
            messages=[{"role": "user", "content": "Hello"}],
        )
    # → span.token_usage and span.cost auto-populated on exit

Calling ``patch()`` is **idempotent** — calling it multiple times has no
effect.  Call :func:`unpatch` to restore the original methods.

Install with::

    pip install "spanforge[together]"
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
    "normalize_model_name",
    "normalize_response",
    "patch",
    "unpatch",
]

# ---------------------------------------------------------------------------
# Static pricing table  (USD per million tokens, effective 2026-03-04)
# Keys are the *full* model identifiers as returned by the Together AI API.
# ---------------------------------------------------------------------------

PRICING_DATE: str = "2026-03-04"

#: Together AI model pricing — USD per million tokens.
#: Keys use the full ``org/model`` identifier from the API.
TOGETHER_PRICING: dict[str, dict[str, float]] = {
    # ------------------------------------------------------------------
    # Meta LLaMA 3.3
    # ------------------------------------------------------------------
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": {
        "input": 0.88,
        "output": 0.88,
    },
    "meta-llama/Llama-3.3-70B-Instruct-Turbo-Free": {
        "input": 0.00,
        "output": 0.00,
    },
    # ------------------------------------------------------------------
    # Meta LLaMA 3.2
    # ------------------------------------------------------------------
    "meta-llama/Llama-3.2-90B-Vision-Instruct-Turbo": {
        "input": 1.20,
        "output": 1.20,
    },
    "meta-llama/Llama-3.2-11B-Vision-Instruct-Turbo": {
        "input": 0.18,
        "output": 0.18,
    },
    "meta-llama/Llama-3.2-3B-Instruct-Turbo": {
        "input": 0.06,
        "output": 0.06,
    },
    "meta-llama/Llama-3.2-1B-Instruct-Turbo": {
        "input": 0.04,
        "output": 0.04,
    },
    # ------------------------------------------------------------------
    # Meta LLaMA 3.1
    # ------------------------------------------------------------------
    "meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo": {
        "input": 3.50,
        "output": 3.50,
    },
    "meta-llama/Meta-Llama-3.1-70B-Instruct-Turbo": {
        "input": 0.88,
        "output": 0.88,
    },
    "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo": {
        "input": 0.18,
        "output": 0.18,
    },
    # ------------------------------------------------------------------
    # Meta LLaMA 3
    # ------------------------------------------------------------------
    "meta-llama/Meta-Llama-3-70B-Instruct-Turbo": {
        "input": 0.88,
        "output": 0.88,
    },
    "meta-llama/Meta-Llama-3-8B-Instruct-Turbo": {
        "input": 0.18,
        "output": 0.18,
    },
    # ------------------------------------------------------------------
    # Qwen
    # ------------------------------------------------------------------
    "Qwen/Qwen2.5-72B-Instruct-Turbo": {
        "input": 1.20,
        "output": 1.20,
    },
    "Qwen/Qwen2.5-7B-Instruct-Turbo": {
        "input": 0.30,
        "output": 0.30,
    },
    "Qwen/QwQ-32B-Preview": {
        "input": 1.20,
        "output": 1.20,
    },
    # ------------------------------------------------------------------
    # Mistral / Mixtral
    # ------------------------------------------------------------------
    "mistralai/Mixtral-8x7B-Instruct-v0.1": {
        "input": 0.60,
        "output": 0.60,
    },
    "mistralai/Mixtral-8x22B-Instruct-v0.1": {
        "input": 1.20,
        "output": 1.20,
    },
    "mistralai/Mistral-7B-Instruct-v0.3": {
        "input": 0.20,
        "output": 0.20,
    },
    # ------------------------------------------------------------------
    # DeepSeek
    # ------------------------------------------------------------------
    "deepseek-ai/DeepSeek-V3": {
        "input": 1.25,
        "output": 1.25,
    },
    "deepseek-ai/DeepSeek-R1": {
        "input": 2.19,
        "output": 7.89,
    },
    "deepseek-ai/DeepSeek-R1-Distill-Llama-70B": {
        "input": 2.19,
        "output": 2.19,
    },
    "deepseek-ai/DeepSeek-R1-Distill-Qwen-1.5B": {
        "input": 0.18,
        "output": 0.18,
    },
    # ------------------------------------------------------------------
    # Google Gemma
    # ------------------------------------------------------------------
    "google/gemma-2-27b-it": {
        "input": 0.80,
        "output": 0.80,
    },
    "google/gemma-2-9b-it": {
        "input": 0.30,
        "output": 0.30,
    },
}

# Sentinel attribute set on the together module to prevent double-patching.
_PATCH_FLAG = "_spanforge_patched"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def patch() -> None:
    """Monkey-patch the Together AI client to auto-instrument all chat completions.

    Wraps both the sync and async ``create`` methods on the Completions
    resource.  The wrapper calls :func:`normalize_response` on the result
    and, if a span is currently active on this thread, updates it.

    This function is **idempotent** — safe to call multiple times.

    Raises:
        ImportError: If the ``together`` package is not installed.
    """
    together_mod = _require_together()

    if getattr(together_mod, _PATCH_FLAG, False):
        return  # already patched

    # --- sync ----------------------------------------------------------------
    try:
        from together.resources.chat.completions import (  # noqa: PLC0415
            Completions,  # type: ignore[import-untyped]
        )

        _orig_sync = Completions.create  # type: ignore[attr-defined]

        @functools.wraps(_orig_sync)
        def _patched_sync(self: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            response = _orig_sync(self, *args, **kwargs)
            _auto_populate_span(response)
            return response

        Completions.create = _patched_sync  # type: ignore[method-assign]
        Completions._spanforge_orig_create = _orig_sync  # type: ignore[attr-defined]
    except (ImportError, AttributeError):  # pragma: no cover
        pass

    # --- async ---------------------------------------------------------------
    try:
        from together.resources.chat.completions import (  # noqa: PLC0415
            AsyncCompletions,  # type: ignore[import-untyped]
        )

        _orig_async = AsyncCompletions.create  # type: ignore[attr-defined]

        @functools.wraps(_orig_async)
        async def _patched_async(self: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            response = await _orig_async(self, *args, **kwargs)
            _auto_populate_span(response)
            return response

        AsyncCompletions.create = _patched_async  # type: ignore[method-assign]
        AsyncCompletions._spanforge_orig_create = _orig_async  # type: ignore[attr-defined]
    except (ImportError, AttributeError):  # pragma: no cover
        pass

    together_mod._spanforge_patched = True  # type: ignore[attr-defined]


def unpatch() -> None:
    """Restore the original Together AI methods and remove the patch flag.

    Safe to call even if :func:`patch` was never called.

    Raises:
        ImportError: If the ``together`` package is not installed.
    """
    together_mod = _require_together()

    if not getattr(together_mod, _PATCH_FLAG, False):
        return  # nothing to do

    try:
        from together.resources.chat.completions import (  # noqa: PLC0415
            Completions,  # type: ignore[import-untyped]
        )

        Completions.create = Completions._spanforge_orig_create  # type: ignore[attr-defined,method-assign]
        del Completions._spanforge_orig_create  # type: ignore[attr-defined]
    except (ImportError, AttributeError):  # pragma: no cover
        pass

    try:
        from together.resources.chat.completions import (  # noqa: PLC0415
            AsyncCompletions,  # type: ignore[import-untyped]
        )

        AsyncCompletions.create = AsyncCompletions._spanforge_orig_create  # type: ignore[attr-defined,method-assign]
        del AsyncCompletions._spanforge_orig_create  # type: ignore[attr-defined]
    except (ImportError, AttributeError):  # pragma: no cover
        pass

    try:  # noqa: SIM105
        del together_mod._spanforge_patched  # type: ignore[attr-defined]
    except AttributeError:  # pragma: no cover
        pass


def is_patched() -> bool:
    """Return ``True`` if the Together AI client has been patched by spanforge.

    Returns ``False`` if the ``together`` package is not installed.
    """
    try:
        together_mod = _require_together()
        return bool(getattr(together_mod, _PATCH_FLAG, False))
    except ImportError:
        return False


def normalize_model_name(raw_name: str) -> str:
    """Normalize a Together AI model name by stripping the organization prefix.

    Together AI uses ``org/model-name`` identifiers.  This function strips
    the ``org/`` prefix so the returned name contains only the model
    component.  If no ``/`` is present the name is returned unchanged.

    Examples::

        >>> normalize_model_name("meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo")
        'Meta-Llama-3.1-8B-Instruct-Turbo'
        >>> normalize_model_name("gpt-4o")
        'gpt-4o'

    Args:
        raw_name: Model identifier as returned by the Together AI API.

    Returns:
        Model name without the organization prefix.
    """
    if "/" in raw_name:
        return raw_name.split("/", 1)[1]
    return raw_name


def normalize_response(
    response: Any,  # noqa: ANN401
) -> tuple[TokenUsage, ModelInfo, CostBreakdown]:
    """Extract structured observability data from a Together AI chat completion.

    Together AI mirrors the OpenAI response format for token fields, but
    model names use an ``org/model`` scheme.  The model name is stored with
    the full identifier preserved for unique identification, while the
    normalized (org-stripped) name is available via :func:`normalize_model_name`.

    Args:
        response: A Together AI ``ChatCompletion`` (or compatible object).

    Returns:
        A 3-tuple of ``(TokenUsage, ModelInfo, CostBreakdown)``.

    Field mapping:

    +--------------------------------------------+---------------------------+
    | Together AI field                          | SpanForge field             |
    +============================================+===========================+
    | ``response.model``                         | ``ModelInfo.name`` (full) |
    | ``usage.prompt_tokens``                    | ``TokenUsage.input_tokens``|
    | ``usage.completion_tokens``                | ``TokenUsage.output_tokens``|
    | ``usage.total_tokens``                     | ``TokenUsage.total_tokens``|
    +--------------------------------------------+---------------------------+
    """
    # ------------------------------------------------------------------ usage
    usage = getattr(response, "usage", None)
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    if usage is not None:
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        total_tokens = int(
            getattr(usage, "total_tokens", input_tokens + output_tokens) or 0
        )

    token_usage = TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )

    # ---------------------------------------------------------------- model
    # Keep the full ``org/model`` identifier for unique model identification.
    model_name: str = getattr(response, "model", None) or "unknown"
    model_info = ModelInfo(system=GenAISystem.TOGETHER_AI, name=model_name)

    # ----------------------------------------------------------------- cost
    cost = _compute_cost(model_name, input_tokens, output_tokens)

    return token_usage, model_info, cost


def list_models() -> list[str]:
    """Return a sorted list of all Together AI model identifiers in the pricing table."""
    return sorted(TOGETHER_PRICING.keys())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_together() -> Any:  # noqa: ANN401
    """Import and return the ``together`` module, raising ``ImportError`` if absent."""
    try:
        import together  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "The 'together' package is required for spanforge Together AI integration.\n"
            "Install it with: pip install 'spanforge[together]'"
        ) from exc
    else:
        return together


def _get_pricing(model: str) -> dict[str, float] | None:
    """Return the pricing entry for *model*, or ``None`` if unknown.

    Tries the full ``org/model`` key first, then falls back to the
    normalized (org-stripped) name.
    """
    if model in TOGETHER_PRICING:
        return TOGETHER_PRICING[model]

    # Try without org prefix
    normalized = normalize_model_name(model)
    if normalized in TOGETHER_PRICING:
        return TOGETHER_PRICING[normalized]

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


def _auto_populate_span(response: Any) -> None:  # noqa: ANN401
    """If there is an active span on this thread, populate it from *response*.

    Silently does nothing if:

    * There is no active span.
    * ``normalize_response`` raises (malformed response).
    * The span already has ``token_usage`` set (don't overwrite manual data).
    """
    try:
        from spanforge._span import _span_stack  # noqa: PLC0415

        stack = _span_stack()
        if not stack:
            return
        span = stack[-1]

        if span.token_usage is not None:
            return

        token_usage, model_info, cost = normalize_response(response)
        span.token_usage = token_usage
        span.cost = cost

        if span.model is None:
            span.model = model_info.name

    except Exception:  # noqa: S110  # NOSONAR
        pass
