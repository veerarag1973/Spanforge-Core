"""spanforge.integrations.ollama — Auto-instrumentation for the Ollama Python SDK.

This module monkey-patches the Ollama client so every
``ollama.chat(...)`` (or ``client.chat(...)``) call automatically populates the
active :class:`~spanforge._span.Span` with:

* :class:`~spanforge.namespaces.trace.TokenUsage` (prompt / eval token counts
  mapped to input / output)
* :class:`~spanforge.namespaces.trace.ModelInfo` (provider = ``ollama``, name
  from response)
* :class:`~spanforge.namespaces.trace.CostBreakdown` (always zero — Ollama is a
  local runtime with no per-token billing)

Usage::

    from spanforge.integrations import ollama as ollama_integration
    ollama_integration.patch()

    import ollama

    import spanforge
    spanforge.configure(exporter="console")

    with spanforge.span("ollama-chat", model="llama3") as span:
        resp = ollama.chat(
            model="llama3",
            messages=[{"role": "user", "content": "Hello"}],
        )
    # → span.token_usage auto-populated on exit; cost is always zero

Calling ``patch()`` is **idempotent** — calling it multiple times has no
effect.  Call :func:`unpatch` to restore the original functions.

Install with::

    pip install "spanforge[ollama]"

.. note::
   Ollama has no per-token pricing.  :func:`normalize_response` always returns
   :meth:`~spanforge.namespaces.trace.CostBreakdown.zero` for the cost field.
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

# Sentinel to prevent double-patching.
_PATCH_FLAG = "_spanforge_patched"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def patch() -> None:
    """Monkey-patch the Ollama module to auto-instrument all chat calls.

    Wraps the module-level ``ollama.chat`` function and, when instantiated,
    ``ollama.Client.chat``.  The wrapper calls :func:`normalize_response` on
    the result and, if a span is currently active, updates it.

    This function is **idempotent** — safe to call multiple times.

    Raises:
        ImportError: If the ``ollama`` package is not installed.
    """
    ollama_mod = _require_ollama()

    if getattr(ollama_mod, _PATCH_FLAG, False):
        return  # already patched

    # --- module-level ollama.chat --------------------------------------------
    _orig_chat = getattr(ollama_mod, "chat", None)
    if _orig_chat is not None:

        @functools.wraps(_orig_chat)
        def _patched_chat(*args: Any, **kwargs: Any) -> Any:
            response = _orig_chat(*args, **kwargs)
            _auto_populate_span(response)
            return response

        ollama_mod.chat = _patched_chat  # type: ignore[attr-defined]
        ollama_mod._spanforge_orig_chat = _orig_chat  # type: ignore[attr-defined]

    # --- Client.chat ---------------------------------------------------------
    try:
        from ollama import Client  # type: ignore[import-untyped]

        _orig_client_chat = Client.chat  # type: ignore[attr-defined]

        @functools.wraps(_orig_client_chat)
        def _patched_client_chat(self: Any, *args: Any, **kwargs: Any) -> Any:
            response = _orig_client_chat(self, *args, **kwargs)
            _auto_populate_span(response)
            return response

        Client.chat = _patched_client_chat  # type: ignore[method-assign]
        Client._spanforge_orig_chat = _orig_client_chat  # type: ignore[attr-defined]
    except (ImportError, AttributeError):  # pragma: no cover
        pass

    # --- AsyncClient.chat ----------------------------------------------------
    try:
        from ollama import AsyncClient  # type: ignore[import-untyped]

        _orig_async_chat = AsyncClient.chat  # type: ignore[attr-defined]

        @functools.wraps(_orig_async_chat)
        async def _patched_async_chat(self: Any, *args: Any, **kwargs: Any) -> Any:
            response = await _orig_async_chat(self, *args, **kwargs)
            _auto_populate_span(response)
            return response

        AsyncClient.chat = _patched_async_chat  # type: ignore[method-assign]
        AsyncClient._spanforge_orig_chat = _orig_async_chat  # type: ignore[attr-defined]
    except (ImportError, AttributeError):  # pragma: no cover
        pass

    ollama_mod._spanforge_patched = True  # type: ignore[attr-defined]


def unpatch() -> None:
    """Restore the original Ollama functions and remove the patch flag.

    Safe to call even if :func:`patch` was never called.

    Raises:
        ImportError: If the ``ollama`` package is not installed.
    """
    ollama_mod = _require_ollama()

    if not getattr(ollama_mod, _PATCH_FLAG, False):
        return  # nothing to do

    orig_chat = getattr(ollama_mod, "_spanforge_orig_chat", None)
    if orig_chat is not None:
        ollama_mod.chat = orig_chat  # type: ignore[attr-defined]
        del ollama_mod._spanforge_orig_chat  # type: ignore[attr-defined]

    try:
        from ollama import Client  # type: ignore[import-untyped]

        Client.chat = Client._spanforge_orig_chat  # type: ignore[attr-defined,method-assign]
        del Client._spanforge_orig_chat  # type: ignore[attr-defined]
    except (ImportError, AttributeError):  # pragma: no cover
        pass

    try:
        from ollama import AsyncClient  # type: ignore[import-untyped]

        AsyncClient.chat = AsyncClient._spanforge_orig_chat  # type: ignore[attr-defined,method-assign]
        del AsyncClient._spanforge_orig_chat  # type: ignore[attr-defined]
    except (ImportError, AttributeError):  # pragma: no cover
        pass

    try:
        del ollama_mod._spanforge_patched  # type: ignore[attr-defined]
    except AttributeError:  # pragma: no cover
        pass


def is_patched() -> bool:
    """Return ``True`` if Ollama has been patched by spanforge.

    Returns ``False`` if the ``ollama`` package is not installed.
    """
    try:
        ollama_mod = _require_ollama()
        return bool(getattr(ollama_mod, _PATCH_FLAG, False))
    except ImportError:
        return False


def normalize_response(
    response: Any,
) -> tuple[TokenUsage, ModelInfo, CostBreakdown]:
    """Extract structured observability data from an Ollama chat response.

    Works with both ``ollama.ChatResponse`` objects and any duck-typed mock
    with the same attribute structure.

    Args:
        response: An Ollama chat response (or compatible object).

    Returns:
        A 3-tuple of ``(TokenUsage, ModelInfo, CostBreakdown)``.
        The ``CostBreakdown`` is **always zero** — Ollama has no billing.

    Field mapping:

    +--------------------------------------------+---------------------------+
    | Ollama field                               | SpanForge field             |
    +============================================+===========================+
    | ``response.model``                         | ``ModelInfo.name``        |
    | ``response.prompt_eval_count``             | ``TokenUsage.input_tokens``|
    | ``response.eval_count``                    | ``TokenUsage.output_tokens``|
    +--------------------------------------------+---------------------------+
    """
    # Ollama may return a dict or an object depending on SDK version.
    if isinstance(response, dict):
        model_name: str = response.get("model", None) or "unknown"
        input_tokens = int(response.get("prompt_eval_count", 0) or 0)
        output_tokens = int(response.get("eval_count", 0) or 0)
    else:
        model_name = getattr(response, "model", None) or "unknown"
        input_tokens = int(getattr(response, "prompt_eval_count", 0) or 0)
        output_tokens = int(getattr(response, "eval_count", 0) or 0)

    total_tokens = input_tokens + output_tokens

    token_usage = TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )

    model_info = ModelInfo(system=GenAISystem.OLLAMA, name=model_name)

    # Ollama is local — no billing data available.
    cost = CostBreakdown.zero()

    return token_usage, model_info, cost


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_ollama() -> Any:
    """Import and return the ``ollama`` module, raising ``ImportError`` if absent."""
    try:
        import ollama  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ImportError(
            "The 'ollama' package is required for spanforge Ollama integration.\n"
            "Install it with: pip install 'spanforge[ollama]'"
        ) from exc
    else:
        return ollama


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
