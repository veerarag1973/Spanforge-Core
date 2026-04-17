"""spanforge.integrations.groq — Auto-instrumentation for the Groq Python SDK.

This module monkey-patches the Groq client so every
``client.chat.completions.create(...)`` call automatically populates the
active :class:`~spanforge._span.Span` with:

* :class:`~spanforge.namespaces.trace.TokenUsage` (input / output token counts)
* :class:`~spanforge.namespaces.trace.ModelInfo` (provider = ``groq``, name
  from response)
* :class:`~spanforge.namespaces.trace.CostBreakdown` (computed from the static
  pricing table below)

The Groq SDK mirrors the OpenAI API surface, so the response object has the
same ``usage.prompt_tokens`` / ``usage.completion_tokens`` fields.
Additionally, Groq exposes per-request timing via ``usage.total_time``
(seconds).  Use :func:`get_duration_ms` to extract the API-measured latency
from a response object.

Usage::

    from spanforge.integrations import groq as groq_integration
    groq_integration.patch()

    from groq import Groq
    client = Groq()

    import spanforge
    spanforge.configure(exporter="console")

    with spanforge.span("groq-chat", model="llama3-70b-8192") as span:
        resp = client.chat.completions.create(
            model="llama3-70b-8192",
            messages=[{"role": "user", "content": "Hello"}],
        )
    # → span.token_usage and span.cost auto-populated on exit

Calling ``patch()`` is **idempotent** — calling it multiple times has no
effect.  Call :func:`unpatch` to restore the original methods.

Install with::

    pip install "spanforge[groq]"
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
    "get_duration_ms",
    "is_patched",
    "normalize_response",
    "patch",
    "unpatch",
]

# ---------------------------------------------------------------------------
# Static pricing table  (USD per million tokens, effective 2026-03-04)
# ---------------------------------------------------------------------------

PRICING_DATE: str = "2026-03-04"

#: Groq model pricing — USD per million tokens.
GROQ_PRICING: dict[str, dict[str, float]] = {
    # ------------------------------------------------------------------
    # LLaMA 3.3
    # ------------------------------------------------------------------
    "llama-3.3-70b-versatile": {
        "input": 0.59,
        "output": 0.79,
    },
    "llama-3.3-70b-specdec": {
        "input": 0.59,
        "output": 0.99,
    },
    # ------------------------------------------------------------------
    # LLaMA 3.1
    # ------------------------------------------------------------------
    "llama-3.1-70b-versatile": {
        "input": 0.59,
        "output": 0.79,
    },
    "llama-3.1-8b-instant": {
        "input": 0.05,
        "output": 0.08,
    },
    "llama-3.1-405b-reasoning": {
        "input": 3.00,
        "output": 3.00,
    },
    # ------------------------------------------------------------------
    # LLaMA 3.2
    # ------------------------------------------------------------------
    "llama-3.2-1b-preview": {
        "input": 0.04,
        "output": 0.04,
    },
    "llama-3.2-3b-preview": {
        "input": 0.06,
        "output": 0.06,
    },
    "llama-3.2-11b-vision-preview": {
        "input": 0.18,
        "output": 0.18,
    },
    "llama-3.2-90b-vision-preview": {
        "input": 0.90,
        "output": 0.90,
    },
    # ------------------------------------------------------------------
    # LLaMA 3 (legacy names)
    # ------------------------------------------------------------------
    "llama3-70b-8192": {
        "input": 0.59,
        "output": 0.79,
    },
    "llama3-8b-8192": {
        "input": 0.05,
        "output": 0.08,
    },
    "llama3-groq-70b-8192-tool-use-preview": {
        "input": 0.89,
        "output": 0.89,
    },
    "llama3-groq-8b-8192-tool-use-preview": {
        "input": 0.19,
        "output": 0.19,
    },
    # ------------------------------------------------------------------
    # Mixtral
    # ------------------------------------------------------------------
    "mixtral-8x7b-32768": {
        "input": 0.24,
        "output": 0.24,
    },
    # ------------------------------------------------------------------
    # Gemma
    # ------------------------------------------------------------------
    "gemma-7b-it": {
        "input": 0.07,
        "output": 0.07,
    },
    "gemma2-9b-it": {
        "input": 0.20,
        "output": 0.20,
    },
}

# Sentinel attribute set on the groq module to prevent double-patching.
_PATCH_FLAG = "_spanforge_patched"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def patch() -> None:
    """Monkey-patch the Groq client to auto-instrument all chat completions.

    Wraps both ``groq.resources.chat.completions.Completions.create``
    (sync) and ``AsyncCompletions.create`` (async).  The wrapper calls
    :func:`normalize_response` on the result and, if a span is currently
    active on this thread, updates it.

    This function is **idempotent** — safe to call multiple times.

    Raises:
        ImportError: If the ``groq`` package is not installed.
    """
    groq_mod = _require_groq()

    if getattr(groq_mod, _PATCH_FLAG, False):
        return  # already patched

    # --- sync ----------------------------------------------------------------
    try:
        from groq.resources.chat.completions import (
            Completions,  # type: ignore[import-untyped]
        )

        _orig_sync = Completions.create  # type: ignore[attr-defined]

        @functools.wraps(_orig_sync)
        def _patched_sync(self: Any, *args: Any, **kwargs: Any) -> Any:
            response = _orig_sync(self, *args, **kwargs)
            _auto_populate_span(response)
            return response

        Completions.create = _patched_sync  # type: ignore[method-assign]
        Completions._spanforge_orig_create = _orig_sync  # type: ignore[attr-defined]
    except (ImportError, AttributeError):  # pragma: no cover
        pass

    # --- async ---------------------------------------------------------------
    try:
        from groq.resources.chat.completions import (
            AsyncCompletions,  # type: ignore[import-untyped]
        )

        _orig_async = AsyncCompletions.create  # type: ignore[attr-defined]

        @functools.wraps(_orig_async)
        async def _patched_async(self: Any, *args: Any, **kwargs: Any) -> Any:
            response = await _orig_async(self, *args, **kwargs)
            _auto_populate_span(response)
            return response

        AsyncCompletions.create = _patched_async  # type: ignore[method-assign]
        AsyncCompletions._spanforge_orig_create = _orig_async  # type: ignore[attr-defined]
    except (ImportError, AttributeError):  # pragma: no cover
        pass

    groq_mod._spanforge_patched = True  # type: ignore[attr-defined]


def unpatch() -> None:
    """Restore the original Groq methods and remove the patch flag.

    Safe to call even if :func:`patch` was never called.

    Raises:
        ImportError: If the ``groq`` package is not installed.
    """
    groq_mod = _require_groq()

    if not getattr(groq_mod, _PATCH_FLAG, False):
        return  # nothing to do

    try:
        from groq.resources.chat.completions import (
            Completions,  # type: ignore[import-untyped]
        )

        Completions.create = Completions._spanforge_orig_create  # type: ignore[attr-defined,method-assign]
        del Completions._spanforge_orig_create  # type: ignore[attr-defined]
    except (ImportError, AttributeError):  # pragma: no cover
        pass

    try:
        from groq.resources.chat.completions import (
            AsyncCompletions,  # type: ignore[import-untyped]
        )

        AsyncCompletions.create = AsyncCompletions._spanforge_orig_create  # type: ignore[attr-defined,method-assign]
        del AsyncCompletions._spanforge_orig_create  # type: ignore[attr-defined]
    except (ImportError, AttributeError):  # pragma: no cover
        pass

    try:
        del groq_mod._spanforge_patched  # type: ignore[attr-defined]
    except AttributeError:  # pragma: no cover
        pass


def is_patched() -> bool:
    """Return ``True`` if the Groq client has been patched by spanforge.

    Returns ``False`` if the ``groq`` package is not installed.
    """
    try:
        groq_mod = _require_groq()
        return bool(getattr(groq_mod, _PATCH_FLAG, False))
    except ImportError:
        return False


def normalize_response(
    response: Any,
) -> tuple[TokenUsage, ModelInfo, CostBreakdown]:
    """Extract structured observability data from a Groq chat completion.

    The Groq SDK mirrors the OpenAI response structure, so token fields
    follow the same ``prompt_tokens`` / ``completion_tokens`` naming.
    Groq additionally provides per-request timing in ``usage.total_time``
    (seconds); use :func:`get_duration_ms` to extract it separately.

    Args:
        response: A Groq ``ChatCompletion`` (or compatible object).

    Returns:
        A 3-tuple of ``(TokenUsage, ModelInfo, CostBreakdown)``.

    Field mapping:

    +--------------------------------------------+---------------------------+
    | Groq field                                 | SpanForge field             |
    +============================================+===========================+
    | ``response.model``                         | ``ModelInfo.name``        |
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
        total_tokens = int(getattr(usage, "total_tokens", input_tokens + output_tokens) or 0)

    token_usage = TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )

    # ---------------------------------------------------------------- model
    model_name: str = getattr(response, "model", None) or "unknown"
    model_info = ModelInfo(system=GenAISystem.GROQ, name=model_name)

    # ----------------------------------------------------------------- cost
    cost = _compute_cost(model_name, input_tokens, output_tokens)

    return token_usage, model_info, cost


def get_duration_ms(response: Any) -> float | None:
    """Return the API-measured processing time in milliseconds from a Groq response.

    Groq exposes sub-millisecond inference latency via ``usage.total_time``
    (in seconds).  This helper converts it to milliseconds.

    Args:
        response: A Groq ``ChatCompletion`` (or compatible object).

    Returns:
        Processing time in milliseconds, or ``None`` if not available.
    """
    usage = getattr(response, "usage", None)
    if usage is None:
        return None
    total_time = getattr(usage, "total_time", None)
    if total_time is None:
        return None
    try:
        return float(total_time) * 1000.0
    except (TypeError, ValueError):
        return None


def list_models() -> list[str]:
    """Return a sorted list of all Groq model names in the pricing table."""
    return sorted(GROQ_PRICING.keys())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_groq() -> Any:
    """Import and return the ``groq`` module, raising ``ImportError`` if absent."""
    try:
        import groq  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "The 'groq' package is required for spanforge Groq integration.\n"
            "Install it with: pip install 'spanforge[groq]'"
        ) from exc
    else:
        return groq


def _get_pricing(model: str) -> dict[str, float] | None:
    """Return the pricing entry for *model*, or ``None`` if unknown."""
    if model in GROQ_PRICING:
        return GROQ_PRICING[model]

    # Try prefix-only matches by stripping trailing date/version suffixes.
    parts = model.rsplit("-", 3)
    for i in range(len(parts) - 1, 0, -1):
        candidate = "-".join(parts[:i])
        if candidate in GROQ_PRICING:
            return GROQ_PRICING[candidate]

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


def _auto_populate_span(response: Any) -> None:
    """If there is an active span on this thread, populate it from *response*.

    Silently does nothing if:

    * There is no active span.
    * ``normalize_response`` raises (malformed response).
    * The span already has ``token_usage`` set (don't overwrite manual data).
    """
    try:
        from spanforge._span import _span_stack

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

    except Exception:  # NOSONAR
        pass
