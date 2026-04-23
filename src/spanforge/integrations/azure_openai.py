"""spanforge.integrations.azure_openai - Azure OpenAI client instrumentation.

Provides an instance-level integration path for Azure-hosted OpenAI clients.
Unlike the generic OpenAI integration, Azure OpenAI is typically configured on
dedicated client instances with an Azure endpoint and deployment wiring, so the
public surface here instruments one client at a time.
"""

from __future__ import annotations

import functools
from typing import Any

from spanforge.integrations import openai as _openai_integration
from spanforge.namespaces.trace import GenAISystem, ModelInfo

__all__ = [
    "instrument_async_client",
    "instrument_client",
    "is_instrumented",
    "normalize_response",
    "uninstrument_client",
]

_PATCH_FLAG = "_spanforge_azure_openai_instrumented"
_ORIG_SYNC = "_spanforge_azure_openai_orig_create"


def normalize_response(response: Any) -> tuple[Any, ModelInfo, Any]:
    """Extract token usage, model identity, and cost from an Azure response."""
    token_usage, _model_info, cost = _openai_integration.normalize_response(response)
    model_name = getattr(response, "model", None) or "unknown"
    model_info = ModelInfo(system=GenAISystem.OPENAI, name=model_name)
    return token_usage, model_info, cost


def instrument_client(client: Any) -> Any:
    """Wrap one Azure OpenAI client instance in-place."""
    completions = _get_completions(client)
    if getattr(completions, _PATCH_FLAG, False):
        return client

    original = completions.create

    @functools.wraps(original)
    def _patched(*args: Any, **kwargs: Any) -> Any:
        response = original(*args, **kwargs)
        _auto_populate_span(response, client=client, kwargs=kwargs)
        return response

    setattr(completions, _ORIG_SYNC, original)
    setattr(completions, "create", _patched)
    setattr(completions, _PATCH_FLAG, True)
    return client


def instrument_async_client(client: Any) -> Any:
    """Wrap one async Azure OpenAI client instance in-place."""
    completions = _get_completions(client)
    if getattr(completions, _PATCH_FLAG, False):
        return client

    original = completions.create

    @functools.wraps(original)
    async def _patched(*args: Any, **kwargs: Any) -> Any:
        response = await original(*args, **kwargs)
        _auto_populate_span(response, client=client, kwargs=kwargs)
        return response

    setattr(completions, _ORIG_SYNC, original)
    setattr(completions, "create", _patched)
    setattr(completions, _PATCH_FLAG, True)
    return client


def uninstrument_client(client: Any) -> Any:
    """Restore the original Azure OpenAI client instance method."""
    completions = _get_completions(client)
    original = getattr(completions, _ORIG_SYNC, None)
    if original is not None:
        setattr(completions, "create", original)
        delattr(completions, _ORIG_SYNC)
    if getattr(completions, _PATCH_FLAG, False):
        delattr(completions, _PATCH_FLAG)
    return client


def is_instrumented(client: Any) -> bool:
    """Return ``True`` when a client instance has been instrumented."""
    completions = _get_completions(client)
    return bool(getattr(completions, _PATCH_FLAG, False))


def _get_completions(client: Any) -> Any:
    chat = getattr(client, "chat", None)
    completions = getattr(chat, "completions", None) if chat is not None else None
    if completions is None or not hasattr(completions, "create"):
        raise TypeError("Azure OpenAI client must expose client.chat.completions.create(...)")
    return completions


def _auto_populate_span(response: Any, *, client: Any, kwargs: dict[str, Any]) -> None:
    """Populate the active span with Azure OpenAI-specific metadata."""
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
        span.attributes.setdefault("gen_ai.system", "openai")
        span.attributes.setdefault("llm.system", "openai")
        span.attributes.setdefault("llm.provider", "azure")
        azure_endpoint = getattr(client, "azure_endpoint", None) or getattr(client, "base_url", None)
        if azure_endpoint:
            span.attributes.setdefault("azure.openai.endpoint", str(azure_endpoint))
        api_version = getattr(client, "api_version", None)
        if api_version:
            span.attributes.setdefault("azure.openai.api_version", str(api_version))
        deployment = kwargs.get("model") or getattr(response, "model", None)
        if deployment:
            span.attributes.setdefault("azure.openai.deployment", str(deployment))
    except Exception:
        return
