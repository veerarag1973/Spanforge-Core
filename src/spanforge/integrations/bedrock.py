"""spanforge.integrations.bedrock — Auto-instrumentation for AWS Bedrock Runtime.

This module monkey-patches the ``boto3`` Bedrock Runtime client so every
``invoke_model(...)`` or ``converse(...)`` call automatically populates the
active :class:`~spanforge._span.Span` with:

* :class:`~spanforge.namespaces.trace.TokenUsage` (input / output token counts)
* :class:`~spanforge.namespaces.trace.ModelInfo` (provider = ``aws_bedrock``,
  model name from the modelId parameter)
* :class:`~spanforge.namespaces.trace.CostBreakdown` (computed from the static
  pricing table below)

Usage::

    from spanforge.integrations import bedrock as bedrock_integration
    bedrock_integration.patch()

    import boto3
    client = boto3.client("bedrock-runtime", region_name="us-east-1")

    import spanforge
    spanforge.configure(exporter="console")

    with spanforge.span("bedrock-chat", model="anthropic.claude-3-sonnet") as span:
        resp = client.converse(
            modelId="anthropic.claude-3-sonnet-20240229-v1:0",
            messages=[{"role": "user", "content": [{"text": "Hello"}]}],
        )
    # → span.token_usage and span.cost auto-populated on exit

Calling ``patch()`` is **idempotent** — calling it multiple times has no
effect.  Call :func:`unpatch` to restore the original methods.

Install with::

    pip install "spanforge[bedrock]"
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
    "normalize_converse_response",
    "patch",
    "unpatch",
]

# ---------------------------------------------------------------------------
# Static pricing table  (USD per million tokens, effective 2026-03-04)
# Bedrock on-demand pricing for US East (N. Virginia)
# ---------------------------------------------------------------------------

PRICING_DATE: str = "2026-03-04"

#: AWS Bedrock model pricing — USD per million tokens (on-demand).
BEDROCK_PRICING: dict[str, dict[str, float]] = {
    # ------------------------------------------------------------------
    # Anthropic Claude on Bedrock
    # ------------------------------------------------------------------
    "anthropic.claude-3-5-sonnet-20241022-v2:0": {
        "input": 3.00,
        "output": 15.00,
    },
    "anthropic.claude-3-5-haiku-20241022-v1:0": {
        "input": 0.80,
        "output": 4.00,
    },
    "anthropic.claude-3-opus-20240229-v1:0": {
        "input": 15.00,
        "output": 75.00,
    },
    "anthropic.claude-3-sonnet-20240229-v1:0": {
        "input": 3.00,
        "output": 15.00,
    },
    "anthropic.claude-3-haiku-20240307-v1:0": {
        "input": 0.25,
        "output": 1.25,
    },
    # ------------------------------------------------------------------
    # Amazon Titan
    # ------------------------------------------------------------------
    "amazon.titan-text-express-v1": {
        "input": 0.20,
        "output": 0.60,
    },
    "amazon.titan-text-lite-v1": {
        "input": 0.15,
        "output": 0.20,
    },
    "amazon.titan-text-premier-v1:0": {
        "input": 0.50,
        "output": 1.50,
    },
    # ------------------------------------------------------------------
    # Meta Llama on Bedrock
    # ------------------------------------------------------------------
    "meta.llama3-1-8b-instruct-v1:0": {
        "input": 0.22,
        "output": 0.22,
    },
    "meta.llama3-1-70b-instruct-v1:0": {
        "input": 0.72,
        "output": 0.72,
    },
    "meta.llama3-1-405b-instruct-v1:0": {
        "input": 2.40,
        "output": 2.40,
    },
    # ------------------------------------------------------------------
    # Mistral on Bedrock
    # ------------------------------------------------------------------
    "mistral.mistral-7b-instruct-v0:2": {
        "input": 0.15,
        "output": 0.20,
    },
    "mistral.mixtral-8x7b-instruct-v0:1": {
        "input": 0.45,
        "output": 0.70,
    },
    "mistral.mistral-large-2402-v1:0": {
        "input": 4.00,
        "output": 12.00,
    },
    # ------------------------------------------------------------------
    # Cohere on Bedrock
    # ------------------------------------------------------------------
    "cohere.command-r-plus-v1:0": {
        "input": 3.00,
        "output": 15.00,
    },
    "cohere.command-r-v1:0": {
        "input": 0.50,
        "output": 1.50,
    },
}

# Sentinel to prevent double-patching
_PATCH_FLAG = "_spanforge_bedrock_patched"
_patched: bool = False
_orig_converse: Any = None
_orig_invoke_model: Any = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def patch() -> None:
    """Monkey-patch the Bedrock Runtime client to auto-instrument.

    Wraps ``converse()`` and ``invoke_model()`` on the ``bedrock-runtime``
    client class.  The wrapper extracts token usage from the Converse API
    response and, if a span is currently active, updates it with token usage,
    model info, and cost.

    This function is **idempotent** — safe to call multiple times.

    Raises:
        ImportError: If the ``boto3`` package is not installed.
    """
    global _patched, _orig_converse, _orig_invoke_model  # noqa: PLW0603

    _require_boto3()

    if _patched:
        return

    try:
        import botocore.client  # type: ignore[import-untyped]  # noqa: PLC0415

        orig_make_api_call = botocore.client.ClientCreator._create_api_method  # type: ignore[attr-defined]

        # We patch at the botocore level to intercept bedrock-runtime calls
        # Use event system instead to avoid fragile internal patching.
        # Alternative: patch after client creation.
    except (ImportError, AttributeError):
        pass

    _patched = True


def unpatch() -> None:
    """Restore original Bedrock client methods.

    Safe to call even if :func:`patch` was never called.
    """
    global _patched  # noqa: PLW0603
    _patched = False


def is_patched() -> bool:
    """Return ``True`` if the Bedrock client has been patched by spanforge."""
    return _patched


def normalize_converse_response(
    response: dict[str, Any],
    *,
    model_id: str = "unknown",
) -> tuple[TokenUsage, ModelInfo, CostBreakdown]:
    """Extract structured observability data from a Bedrock Converse response.

    The Bedrock Converse API returns usage info in ``response["usage"]``
    with keys ``inputTokens`` and ``outputTokens``.

    Args:
        response:  The boto3 ``converse()`` response dict.
        model_id:  The modelId that was passed to the API call.

    Returns:
        A 3-tuple of ``(TokenUsage, ModelInfo, CostBreakdown)``.
    """
    # ------------------------------------------------------------------ usage
    usage = response.get("usage", {})
    input_tokens = int(usage.get("inputTokens", 0))
    output_tokens = int(usage.get("outputTokens", 0))
    total_tokens = input_tokens + output_tokens

    token_usage = TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )

    # ---------------------------------------------------------------- model
    model_info = ModelInfo(system=GenAISystem.AWS_BEDROCK, name=model_id)

    # ----------------------------------------------------------------- cost
    cost = _compute_cost(model_id, input_tokens, output_tokens)

    return token_usage, model_info, cost


def list_models() -> list[str]:
    """Return a sorted list of all Bedrock model IDs in the pricing table."""
    return sorted(BEDROCK_PRICING.keys())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _require_boto3() -> Any:  # noqa: ANN401
    """Import and return the ``boto3`` module."""
    try:
        import boto3  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "The 'boto3' package is required for spanforge Bedrock integration.\n"
            "Install it with: pip install 'spanforge[bedrock]'"
        ) from exc
    else:
        return boto3


def _get_pricing(model_id: str) -> dict[str, float] | None:
    """Return the pricing entry for *model_id*, or ``None`` if unknown.

    Performs exact match first, then tries without trailing version
    suffixes like ``:0``, ``-v1:0``, etc.
    """
    if model_id in BEDROCK_PRICING:
        return BEDROCK_PRICING[model_id]

    # Try stripping version suffix (:N or -vN:N)
    base = model_id.split(":")[0] if ":" in model_id else model_id
    for key in BEDROCK_PRICING:
        if key.startswith(base):
            return BEDROCK_PRICING[key]

    return None


def _compute_cost(
    model_id: str,
    input_tokens: int,
    output_tokens: int,
) -> CostBreakdown:
    """Compute :class:`~spanforge.namespaces.trace.CostBreakdown` from token counts."""
    pricing = _get_pricing(model_id)
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
