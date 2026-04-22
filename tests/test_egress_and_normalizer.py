"""Focused coverage for older low-coverage utility modules."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from spanforge.exceptions import EgressViolationError
from spanforge.normalizer import GenericNormalizer, ProviderNormalizer


def test_check_egress_blocks_when_no_egress_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import spanforge.egress as egress
    import spanforge.config as config

    monkeypatch.setattr(
        config,
        "get_config",
        lambda: SimpleNamespace(no_egress=True, egress_allowlist=()),
    )

    with pytest.raises(EgressViolationError):
        egress.check_egress("https://blocked.example.com/v1/traces", backend="otlp")


def test_check_egress_allows_matching_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    import spanforge.egress as egress
    import spanforge.config as config

    monkeypatch.setattr(
        config,
        "get_config",
        lambda: SimpleNamespace(
            no_egress=True,
            egress_allowlist=("https://allowed.example.com/", "https://backup.example.com/"),
        ),
    )

    egress.check_egress("https://allowed.example.com/v1/traces", backend="otlp")


def test_provider_normalizer_protocol_runtime_checkable() -> None:
    class _Impl:
        def normalize_response(self, response: object):
            return response

    assert isinstance(_Impl(), ProviderNormalizer)
    assert not isinstance(object(), ProviderNormalizer)


def test_generic_normalizer_handles_openai_object_shape() -> None:
    normalizer = GenericNormalizer()
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=12,
            completion_tokens=5,
            total_tokens=17,
            cached_tokens=3,
            reasoning_tokens=2,
        ),
        model="gpt-4o",
    )

    token_usage, model_info, cost = normalizer.normalize_response(response)

    assert token_usage.input_tokens == 12
    assert token_usage.output_tokens == 5
    assert token_usage.total_tokens == 17
    assert token_usage.cached_tokens == 3
    assert token_usage.reasoning_tokens == 2
    assert model_info.name == "gpt-4o"
    assert model_info.system == "_custom"
    assert cost is None


def test_generic_normalizer_handles_anthropic_dict_shape() -> None:
    normalizer = GenericNormalizer()
    response = {
        "usage": {
            "input_tokens": 21,
            "output_tokens": 8,
            "cache_read_input_tokens": 4,
            "cache_creation_input_tokens": 6,
        },
        "model_id": "claude-3-5-sonnet",
    }

    token_usage, model_info, cost = normalizer.normalize_response(response)

    assert token_usage.input_tokens == 21
    assert token_usage.output_tokens == 8
    assert token_usage.total_tokens == 29
    assert token_usage.cached_tokens == 4
    assert token_usage.cache_creation_tokens == 6
    assert model_info.name == "claude-3-5-sonnet"
    assert cost is None


def test_generic_normalizer_defaults_for_unknown_shape() -> None:
    normalizer = GenericNormalizer()

    token_usage, model_info, cost = normalizer.normalize_response({"unexpected": "value"})

    assert token_usage.input_tokens == 0
    assert token_usage.output_tokens == 0
    assert token_usage.total_tokens == 0
    assert token_usage.cached_tokens is None
    assert token_usage.cache_creation_tokens is None
    assert token_usage.reasoning_tokens is None
    assert model_info.name == "unknown"
    assert cost is None
