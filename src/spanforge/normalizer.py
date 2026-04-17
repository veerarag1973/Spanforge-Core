"""spanforge.normalizer — ProviderNormalizer Protocol and GenericNormalizer.

Defines the :class:`ProviderNormalizer` structural protocol (RFC-0001 §10.4)
that provider-specific integration modules must satisfy, plus a
:class:`GenericNormalizer` fallback that handles OpenAI-compatible,
Anthropic-compatible, and raw ``dict`` response shapes without requiring
any vendored SDK.

Usage
-----
::

    from spanforge.normalizer import GenericNormalizer

    normalizer = GenericNormalizer()
    token_usage, model_info, cost = normalizer.normalize_response(raw_response)

RFC reference
-------------
RFC-0001-SPANFORGE §10.4 — Provider Normalizer interface mandate.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from spanforge.namespaces.trace import CostBreakdown, ModelInfo, TokenUsage

__all__: list[str] = ["GenericNormalizer", "ProviderNormalizer"]


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class ProviderNormalizer(Protocol):
    """Structural protocol for provider-specific response normalizers.

    Any object implementing this single-method interface can be used as a
    drop-in normalizer within the SpanForge instrumentation pipeline.  No
    base class is required — structural (duck-typed) conformance is enough.

    Implementors
    ------------
    * :class:`GenericNormalizer` — OpenAI-compatible + Anthropic-compatible
      shapes; zero-dependency fallback.
    * ``spanforge.integrations.openai.OpenAINormalizer`` (when available)
    * ``spanforge.integrations.anthropic.AnthropicNormalizer`` (when available)
    """

    def normalize_response(
        self,
        response: object,
    ) -> tuple[TokenUsage, ModelInfo, CostBreakdown | None]:
        """Extract TokenUsage, ModelInfo, and optionally CostBreakdown from a raw LLM response.

        Parameters
        ----------
        response:
            Raw response object or dict from a provider SDK call.

        Returns:
        -------
        tuple[TokenUsage, ModelInfo, CostBreakdown | None]
            A 3-tuple of typed value objects.  ``CostBreakdown`` will be
            ``None`` when pricing data is unavailable.
        """
        ...  # pragma: no cover — Protocol method, never called directly.


# ---------------------------------------------------------------------------
# Generic fallback implementation
# ---------------------------------------------------------------------------

_UNKNOWN = "_custom"


def _get(obj: Any, *keys: str, default: Any = None) -> Any:
    """Attribute-then-dict key lookup — tolerates both objects and dicts."""
    for key in keys:
        if obj is None:
            return default
        obj = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    return obj if obj is not None else default


class GenericNormalizer:
    """Zero-dependency fallback normalizer for common LLM response shapes.

    Supports three structural layouts without requiring any provider SDK:

    1. **OpenAI-compatible** — ``response.usage.{prompt_tokens,
       completion_tokens, total_tokens}``, ``response.model``.
    2. **Anthropic-compatible** — ``response.usage.{input_tokens,
       output_tokens}``, ``response.model``.
    3. **Raw dict** — any dict with keys from either layout above.

    When neither layout matches, sensible zero-value defaults are returned
    so the caller always gets a valid :class:`~spanforge.namespaces.trace.TokenUsage`
    regardless of the provider response shape.
    """

    def normalize_response(
        self,
        response: object,
    ) -> tuple[TokenUsage, ModelInfo, CostBreakdown | None]:
        """Normalise *response* into typed SpanForge value objects.

        Parameters
        ----------
        response:
            Raw provider response — may be a dataclass, SDK response object,
            or plain ``dict``.

        Returns:
        -------
        tuple[TokenUsage, ModelInfo, CostBreakdown | None]
            Typed value objects; ``CostBreakdown`` is always ``None`` (pricing
            data requires a :class:`~spanforge.namespaces.trace.PricingTier`
            which this generic normalizer does not possess).
        """
        usage = _get(response, "usage")

        # ---------- token counts ----------
        # OpenAI layout: prompt_tokens / completion_tokens / total_tokens
        # Anthropic layout: input_tokens / output_tokens
        input_tokens: int = int(
            _get(usage, "prompt_tokens", default=0) or _get(usage, "input_tokens", default=0) or 0
        )
        output_tokens: int = int(
            _get(usage, "completion_tokens", default=0)
            or _get(usage, "output_tokens", default=0)
            or 0
        )
        total_tokens: int = int(
            _get(usage, "total_tokens", default=0) or (input_tokens + output_tokens)
        )
        cached_tokens: int = int(
            _get(usage, "cached_tokens", default=0)
            or _get(usage, "cache_read_input_tokens", default=0)
            or 0
        )
        cache_creation_tokens: int = int(_get(usage, "cache_creation_input_tokens", default=0) or 0)
        reasoning_tokens: int = int(_get(usage, "reasoning_tokens", default=0) or 0)

        token_usage = TokenUsage(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            cached_tokens=cached_tokens if cached_tokens else None,
            cache_creation_tokens=cache_creation_tokens if cache_creation_tokens else None,
            reasoning_tokens=reasoning_tokens if reasoning_tokens else None,
        )

        # ---------- model info ----------
        model_name: str = str(
            _get(response, "model", default="")
            or _get(response, "model_id", default="")
            or "unknown"
        )

        model_info = ModelInfo(
            system=_UNKNOWN,
            name=model_name,
            response_model=model_name,
        )

        return token_usage, model_info, None
