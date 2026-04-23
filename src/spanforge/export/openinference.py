"""spanforge.export.openinference - OpenInference-compatible span translation.

This bridge follows the OpenInference semantic conventions for the subset of
fields SpanForge already captures reliably today.  It is intended to provide an
interoperable export path on top of existing SpanForge traces.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from spanforge._span import Span

__all__ = ["OpenInferenceSpanBridge", "span_to_openinference_dict"]


def span_to_openinference_dict(span: Span) -> dict[str, Any]:
    """Translate a SpanForge span into an OpenInference-style span dict."""
    attrs = dict(span.attributes or {})
    oi_attrs: dict[str, Any] = {}
    oi_attrs["openinference.span.kind"] = _span_kind(span)
    oi_attrs["metadata"] = json.dumps(attrs, sort_keys=True, default=str)
    if span.session_id:
        oi_attrs["session.id"] = span.session_id

    input_value = _first_string(
        attrs,
        "input.value",
        "arg.input",
        "input",
        "prompt",
        "query",
        "message",
    )
    output_value = _first_string(
        attrs,
        "output.value",
        "return_value",
        "output",
        "result",
    )
    if input_value is not None:
        oi_attrs["input.value"] = input_value
    if output_value is not None:
        oi_attrs["output.value"] = output_value

    _populate_model_attrs(span, oi_attrs)
    _populate_token_attrs(span, oi_attrs)
    _populate_cost_attrs(span, oi_attrs)

    if span.error:
        oi_attrs["exception.message"] = span.error
    if span.error_type:
        oi_attrs["exception.type"] = span.error_type
    if span.error or span.error_type:
        oi_attrs["exception.escaped"] = True

    return {
        "name": span.name,
        "context": {
            "trace_id": span.trace_id,
            "span_id": span.span_id,
            "parent_span_id": span.parent_span_id,
        },
        "status": "ERROR" if span.status == "error" else "OK",
        "start_time_unix_nano": str(span.start_ns),
        "end_time_unix_nano": str(span.end_ns or span.start_ns),
        "attributes": oi_attrs,
    }


@dataclass
class OpenInferenceSpanBridge:
    """Build OpenInference-compatible traces from SpanForge spans."""

    def to_spans(self, spans: list[Span]) -> list[dict[str, Any]]:
        return [span_to_openinference_dict(span) for span in spans]

    def to_trace(self, spans: list[Span]) -> dict[str, Any]:
        return {"spans": self.to_spans(spans)}


def _span_kind(span: Span) -> str:
    attrs = span.attributes or {}
    if bool(attrs.get("tool")) or span.tool_calls:
        return "TOOL"
    op = str(span.operation or "").lower()
    name = str(span.name or "").lower()
    if "agent" in op or "agent" in name:
        return "AGENT"
    if "retriev" in op or "retriev" in name or "rag" in op:
        return "RETRIEVER"
    if span.model or "gen_ai.system" in attrs or "llm.system" in attrs:
        return "LLM"
    return "CHAIN"


def _populate_model_attrs(span: Span, attrs: dict[str, Any]) -> None:
    payload = span.to_span_payload()
    system = _first_string(span.attributes or {}, "llm.system", "gen_ai.system")
    model_name = _first_string(span.attributes or {}, "llm.model_name", "model")
    if payload.model is not None:
        system = (
            payload.model.system.value
            if hasattr(payload.model.system, "value")
            else str(payload.model.system)
        )
        model_name = payload.model.name
    elif span.model:
        model_name = span.model

    if system is not None:
        attrs["llm.system"] = system
    if model_name is not None:
        attrs["llm.model_name"] = model_name

    provider = _first_string(span.attributes or {}, "llm.provider", "provider")
    if provider is not None:
        attrs["llm.provider"] = provider


def _populate_token_attrs(span: Span, attrs: dict[str, Any]) -> None:
    if span.token_usage is None:
        return
    attrs["llm.token_count.prompt"] = span.token_usage.input_tokens
    attrs["llm.token_count.completion"] = span.token_usage.output_tokens
    attrs["llm.token_count.total"] = span.token_usage.total_tokens
    if span.token_usage.cached_tokens is not None:
        attrs["llm.token_count.prompt_details.cache_read"] = span.token_usage.cached_tokens
    if span.token_usage.reasoning_tokens is not None:
        attrs["llm.token_count.completion_details.reasoning"] = span.token_usage.reasoning_tokens


def _populate_cost_attrs(span: Span, attrs: dict[str, Any]) -> None:
    if span.cost is None:
        return
    attrs["llm.cost.prompt"] = span.cost.input_cost_usd
    attrs["llm.cost.completion"] = span.cost.output_cost_usd
    attrs["llm.cost.total"] = span.cost.total_cost_usd
    attrs["llm.cost.prompt_details.input"] = span.cost.input_cost_usd
    attrs["llm.cost.completion_details.output"] = span.cost.output_cost_usd
    if span.cost.cached_discount_usd:
        attrs["llm.cost.prompt_details.cache_read"] = span.cost.cached_discount_usd
    if span.cost.reasoning_cost_usd:
        attrs["llm.cost.completion_details.reasoning"] = span.cost.reasoning_cost_usd


def _first_string(attrs: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = attrs.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            return value
        return json.dumps(value, sort_keys=True, default=str)
    return None
