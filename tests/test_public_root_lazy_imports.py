"""Tests for lazy module exports from the spanforge package root."""

from __future__ import annotations

import importlib


def test_lazy_module_exports_are_not_eagerly_bound() -> None:
    import spanforge

    for name in (
        "auto",
        "metrics",
        "sdk",
        "testing",
        "print_tree",
        "ChatCompletionResponse",
        "serve_metrics",
        "register_model",
        "render_prompt",
    ):
        spanforge.__dict__.pop(name, None)
    root = importlib.reload(spanforge)

    assert "auto" not in root.__dict__
    assert "metrics" not in root.__dict__
    assert "sdk" not in root.__dict__
    assert "testing" not in root.__dict__
    assert "print_tree" not in root.__dict__
    assert "ChatCompletionResponse" not in root.__dict__
    assert "serve_metrics" not in root.__dict__
    assert "register_model" not in root.__dict__
    assert "render_prompt" not in root.__dict__


def test_lazy_module_exports_resolve_and_cache() -> None:
    import spanforge

    root = importlib.reload(spanforge)

    auto_mod = root.auto
    metrics_mod = root.metrics
    sdk_mod = root.sdk
    testing_mod = root.testing

    assert auto_mod is importlib.import_module("spanforge.auto")
    assert metrics_mod is importlib.import_module("spanforge.metrics")
    assert sdk_mod is importlib.import_module("spanforge.sdk")
    assert testing_mod is importlib.import_module("spanforge.testing")
    assert root.__dict__["auto"] is auto_mod
    assert root.__dict__["metrics"] is metrics_mod
    assert root.__dict__["sdk"] is sdk_mod
    assert root.__dict__["testing"] is testing_mod


def test_dir_includes_lazy_module_exports() -> None:
    import spanforge

    root = importlib.reload(spanforge)
    names = dir(root)

    assert "auto" in names
    assert "metrics" in names
    assert "sdk" in names
    assert "testing" in names
    assert "print_tree" in names
    assert "ChatCompletionResponse" in names
    assert "serve_metrics" in names
    assert "register_model" in names
    assert "render_prompt" in names


def test_lazy_attribute_exports_resolve_and_cache() -> None:
    import spanforge

    root = importlib.reload(spanforge)

    print_tree = root.print_tree
    response_cls = root.ChatCompletionResponse
    serve_metrics = root.serve_metrics
    register_model = root.register_model
    render_prompt = root.render_prompt

    assert print_tree is importlib.import_module("spanforge.debug").print_tree
    assert response_cls is importlib.import_module("spanforge.http").ChatCompletionResponse
    assert serve_metrics is importlib.import_module("spanforge.metrics_export").serve_metrics
    assert register_model is importlib.import_module("spanforge.model_registry").register_model
    assert render_prompt is importlib.import_module("spanforge.prompt_registry").render_prompt
    assert root.__dict__["print_tree"] is print_tree
    assert root.__dict__["ChatCompletionResponse"] is response_cls
    assert root.__dict__["serve_metrics"] is serve_metrics
    assert root.__dict__["register_model"] is register_model
    assert root.__dict__["render_prompt"] is render_prompt
