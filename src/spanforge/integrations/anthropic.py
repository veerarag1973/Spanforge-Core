"""spanforge.integrations.anthropic — Auto-instrumentation for the Anthropic Python SDK.

This module monkey-patches the Anthropic client so every
``client.messages.create(...)`` call automatically populates the
active :class:`~spanforge._span.Span` with:

* :class:`~spanforge.namespaces.trace.TokenUsage` (input / output token counts)
* :class:`~spanforge.namespaces.trace.ModelInfo` (provider = ``anthropic``, name
  from response)
* :class:`~spanforge.namespaces.trace.CostBreakdown` (computed from the static
  pricing table below)

Usage::

    from spanforge.integrations import anthropic as anthropic_integration
    anthropic_integration.patch()

    import anthropic
    client = anthropic.Anthropic()

    import spanforge
    spanforge.configure(exporter="console")

    with spanforge.span("claude-chat", model="claude-3-5-sonnet-20241022") as span:
        resp = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            messages=[{"role": "user", "content": "Hello"}],
        )
    # → span.token_usage and span.cost auto-populated on exit

Calling ``patch()`` is **idempotent** — calling it multiple times has no
effect.  Call :func:`unpatch` to restore the original methods.

Install with::

    pip install "spanforge[anthropic]"
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

#: Anthropic model pricing — USD per million tokens.
ANTHROPIC_PRICING: dict[str, dict[str, float]] = {
    # ------------------------------------------------------------------
    # Claude 3.5 family
    # ------------------------------------------------------------------
    "claude-3-5-sonnet-20241022": {
        "input": 3.00,
        "output": 15.00,
    },
    "claude-3-5-sonnet-20240620": {
        "input": 3.00,
        "output": 15.00,
    },
    "claude-3-5-haiku-20241022": {
        "input": 0.80,
        "output": 4.00,
    },
    # ------------------------------------------------------------------
    # Claude 3 family
    # ------------------------------------------------------------------
    "claude-3-opus-20240229": {
        "input": 15.00,
        "output": 75.00,
    },
    "claude-3-sonnet-20240229": {
        "input": 3.00,
        "output": 15.00,
    },
    "claude-3-haiku-20240307": {
        "input": 0.25,
        "output": 1.25,
    },
    # ------------------------------------------------------------------
    # Claude 2
    # ------------------------------------------------------------------
    "claude-2.1": {
        "input": 8.00,
        "output": 24.00,
    },
    "claude-2.0": {
        "input": 8.00,
        "output": 24.00,
    },
    # ------------------------------------------------------------------
    # Claude Instant
    # ------------------------------------------------------------------
    "claude-instant-1.2": {
        "input": 0.80,
        "output": 2.40,
    },
}

# Sentinel attribute set on the anthropic module to prevent double-patching.
_PATCH_FLAG = "_spanforge_patched"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def patch() -> None:
    """Monkey-patch the Anthropic client to auto-instrument all message creations.

    Wraps both ``anthropic.resources.Messages.create`` (sync) and the
    async variant.  The wrapper calls :func:`normalize_response` on the
    result and, if a span is currently active, updates it with token usage,
    model info, and cost.

    This function is **idempotent** — safe to call multiple times.

    Raises:
        ImportError: If the ``anthropic`` package is not installed.
    """
    anthropic_mod = _require_anthropic()

    if getattr(anthropic_mod, _PATCH_FLAG, False):
        return  # already patched

    # --- sync ----------------------------------------------------------------
    try:
        from anthropic.resources.messages import (  # noqa: PLC0415
            Messages,  # type: ignore[import-untyped]
        )

        _orig_sync = Messages.create  # type: ignore[attr-defined]

        @functools.wraps(_orig_sync)
        def _patched_sync(self: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            response = _orig_sync(self, *args, **kwargs)
            _auto_populate_span(response)
            return response

        Messages.create = _patched_sync  # type: ignore[method-assign]
        Messages._spanforge_orig_create = _orig_sync  # type: ignore[attr-defined]
    except (ImportError, AttributeError):  # pragma: no cover
        pass

    # --- async ---------------------------------------------------------------
    try:
        from anthropic.resources.messages import (  # noqa: PLC0415
            AsyncMessages,  # type: ignore[import-untyped]
        )

        _orig_async = AsyncMessages.create  # type: ignore[attr-defined]

        @functools.wraps(_orig_async)
        async def _patched_async(self: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
            response = await _orig_async(self, *args, **kwargs)
            _auto_populate_span(response)
            return response

        AsyncMessages.create = _patched_async  # type: ignore[method-assign]
        AsyncMessages._spanforge_orig_create = _orig_async  # type: ignore[attr-defined]
    except (ImportError, AttributeError):  # pragma: no cover
        pass

    anthropic_mod._spanforge_patched = True  # type: ignore[attr-defined]


def unpatch() -> None:
    """Restore the original Anthropic methods and remove the patch flag.

    Safe to call even if :func:`patch` was never called.

    Raises:
        ImportError: If the ``anthropic`` package is not installed.
    """
    anthropic_mod = _require_anthropic()

    if not getattr(anthropic_mod, _PATCH_FLAG, False):
        return  # nothing to do

    try:
        from anthropic.resources.messages import (  # noqa: PLC0415
            Messages,  # type: ignore[import-untyped]
        )

        Messages.create = Messages._spanforge_orig_create  # type: ignore[attr-defined,method-assign]
        del Messages._spanforge_orig_create  # type: ignore[attr-defined]
    except (ImportError, AttributeError):  # pragma: no cover
        pass

    try:
        from anthropic.resources.messages import (  # noqa: PLC0415
            AsyncMessages,  # type: ignore[import-untyped]
        )

        AsyncMessages.create = AsyncMessages._spanforge_orig_create  # type: ignore[attr-defined,method-assign]
        del AsyncMessages._spanforge_orig_create  # type: ignore[attr-defined]
    except (ImportError, AttributeError):  # pragma: no cover
        pass

    try:  # noqa: SIM105
        del anthropic_mod._spanforge_patched  # type: ignore[attr-defined]
    except AttributeError:  # pragma: no cover
        pass


def is_patched() -> bool:
    """Return ``True`` if the Anthropic client has been patched by spanforge.

    Returns ``False`` if the ``anthropic`` package is not installed.
    """
    try:
        anthropic_mod = _require_anthropic()
        return bool(getattr(anthropic_mod, _PATCH_FLAG, False))
    except ImportError:
        return False


def normalize_response(
    response: Any,  # noqa: ANN401
) -> tuple[TokenUsage, ModelInfo, CostBreakdown]:
    """Extract structured observability data from an Anthropic message response.

    Works with both ``anthropic.types.Message`` objects and any duck-typed
    mock with the same attribute structure.

    Args:
        response: An Anthropic ``Message`` (or compatible object).

    Returns:
        A 3-tuple of ``(TokenUsage, ModelInfo, CostBreakdown)``.

    Field mapping:

    +--------------------------------------------+---------------------------+
    | Anthropic field                            | SpanForge field             |
    +============================================+===========================+
    | ``response.model``                         | ``ModelInfo.name``        |
    | ``usage.input_tokens``                     | ``TokenUsage.input_tokens``|
    | ``usage.output_tokens``                    | ``TokenUsage.output_tokens``|
    | ``usage.cache_read_input_tokens``          | ``TokenUsage.cached_tokens``|
    +--------------------------------------------+---------------------------+
    """
    # ------------------------------------------------------------------ usage
    usage = getattr(response, "usage", None)
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int | None = None

    if usage is not None:
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)

        # Anthropic exposes cache reads as ``cache_read_input_tokens``
        cr = getattr(usage, "cache_read_input_tokens", None)
        if cr is not None:
            cached_tokens = int(cr)

    total_tokens = input_tokens + output_tokens

    token_usage = TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_tokens=cached_tokens,
    )

    # ---------------------------------------------------------------- model
    model_name: str = getattr(response, "model", None) or "unknown"
    model_info = ModelInfo(system=GenAISystem.ANTHROPIC, name=model_name)

    # ----------------------------------------------------------------- cost
    cost = _compute_cost(model_name, input_tokens, output_tokens)

    return token_usage, model_info, cost


def list_models() -> list[str]:
    """Return a sorted list of all Anthropic model names in the pricing table."""
    return sorted(ANTHROPIC_PRICING.keys())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_anthropic() -> Any:  # noqa: ANN401
    """Import and return the ``anthropic`` module, raising ``ImportError`` if absent."""
    try:
        import anthropic  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "The 'anthropic' package is required for spanforge Anthropic integration.\n"
            "Install it with: pip install 'spanforge[anthropic]'"
        ) from exc
    else:
        return anthropic


def _get_pricing(model: str) -> dict[str, float] | None:
    """Return the pricing entry for *model*, or ``None`` if unknown.

    Performs an exact lookup first, then tries stripping trailing version
    date suffixes (e.g. ``"claude-3-5-sonnet"`` matches
    ``"claude-3-5-sonnet-20241022"``).
    """
    if model in ANTHROPIC_PRICING:
        return ANTHROPIC_PRICING[model]

    # Try prefix-only matches (strip trailing -YYYYMMDD or -YYYY-MM-DD)
    parts = model.rsplit("-", 3)
    for i in range(len(parts) - 1, 0, -1):
        candidate = "-".join(parts[:i])
        if candidate in ANTHROPIC_PRICING:
            return ANTHROPIC_PRICING[candidate]

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
