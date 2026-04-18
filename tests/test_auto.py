"""Tests for spanforge.auto — setup(), teardown(), patched_integrations().

All integration patches are isolated via sys.modules manipulation so no real
SDK is required and the global patch state is restored after each test.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import importlib.util
import sys
import types
import warnings
from unittest.mock import patch

import pytest

import spanforge.auto as auto_mod
from spanforge.auto import patched_integrations, setup, teardown

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_patch_state() -> None:
    """Reset the global _PATCHED set before and after each test."""
    auto_mod._PATCHED.clear()
    yield
    auto_mod._PATCHED.clear()


def _inject_fake_lib(name: str) -> types.ModuleType:
    """Insert a minimal fake module for *name* into sys.modules.

    The module is given a non-None ``__spec__`` so that
    ``importlib.util.find_spec()`` does not raise ``ValueError``.
    """
    mod = types.ModuleType(name)
    mod.__spec__ = importlib.machinery.ModuleSpec(name, loader=None)
    sys.modules[name] = mod
    return mod


def _remove_lib(name: str) -> None:
    """Remove *name* (and any sub-modules) from sys.modules."""
    keys = [k for k in sys.modules if k == name or k.startswith(f"{name}.")]
    for k in keys:
        del sys.modules[k]


def _make_integration_module(lib_name: str) -> types.ModuleType:
    """Return a fake spanforge integration module with patch/unpatch/is_patched."""
    mod = types.ModuleType(f"spanforge.integrations.{lib_name}")
    mod._patched = False  # type: ignore[attr-defined]

    def patch_fn() -> None:
        mod._patched = True  # type: ignore[attr-defined]

    def unpatch_fn() -> None:
        mod._patched = False  # type: ignore[attr-defined]

    def is_patched() -> bool:
        return mod._patched  # type: ignore[attr-defined]

    mod.patch = patch_fn  # type: ignore[attr-defined]
    mod.unpatch = unpatch_fn  # type: ignore[attr-defined]
    mod.is_patched = is_patched  # type: ignore[attr-defined]
    return mod


# ---------------------------------------------------------------------------
# setup()
# ---------------------------------------------------------------------------


class TestSetup:
    def test_returns_empty_set_when_no_libs_installed(self) -> None:
        """When none of the target libraries are on sys.path / installed, returns {}."""
        for lib, _, _, _ in auto_mod._INTEGRATIONS:
            _remove_lib(lib)
            sys.modules[lib] = None  # type: ignore[assignment]  # block import
        try:
            result = setup()
            assert result == set()
        finally:
            for lib, _, _, _ in auto_mod._INTEGRATIONS:
                sys.modules.pop(lib, None)

    def test_patches_single_installed_lib(self) -> None:
        """setup() patches a lib whose fake module is in sys.modules."""
        _inject_fake_lib("openai")
        fake_integration = _make_integration_module("openai")
        fake_integration_path = "spanforge.integrations.openai"

        with patch.dict(sys.modules, {fake_integration_path: fake_integration}):
            with patch.object(auto_mod, "_INTEGRATIONS", [
                ("openai", fake_integration_path, "patch", "unpatch"),
            ]):
                result = setup()

        assert "openai" in result
        assert "openai" in patched_integrations()
        _remove_lib("openai")

    def test_skips_already_patched_lib(self) -> None:
        """A lib already in _PATCHED is skipped (idempotent)."""
        auto_mod._PATCHED.add("openai")
        _inject_fake_lib("openai")
        fake_integration = _make_integration_module("openai")

        with patch.dict(sys.modules, {"spanforge.integrations.openai": fake_integration}):
            with patch.object(auto_mod, "_INTEGRATIONS", [
                ("openai", "spanforge.integrations.openai", "patch", "unpatch"),
            ]):
                result = setup()

        assert "openai" not in result  # not newly patched
        _remove_lib("openai")

    def test_skips_lib_not_installed(self) -> None:
        """A lib not findable via importlib.util.find_spec is silently skipped."""
        _remove_lib("__nonexistent_lib__")
        sys.modules["__nonexistent_lib__"] = None  # type: ignore[assignment]
        fake_integration = _make_integration_module("__nonexistent_lib__")

        with patch.dict(sys.modules, {
            "spanforge.integrations.__nonexistent_lib__": fake_integration
        }):
            with patch.object(auto_mod, "_INTEGRATIONS", [
                ("__nonexistent_lib__", "spanforge.integrations.__nonexistent_lib__", "patch", "unpatch"),
            ]):
                result = setup()

        assert "__nonexistent_lib__" not in result
        sys.modules.pop("__nonexistent_lib__", None)

    def test_patch_failure_emits_warning(self) -> None:
        """A broken patch() function should warn, not raise."""
        _inject_fake_lib("broken_lib")
        broken_mod = types.ModuleType("spanforge.integrations.broken_lib")

        def bad_patch() -> None:
            raise RuntimeError("patch failed")

        broken_mod.patch = bad_patch  # type: ignore[attr-defined]
        broken_mod.unpatch = lambda: None  # type: ignore[attr-defined]

        with patch.dict(sys.modules, {
            "broken_lib": sys.modules["broken_lib"],
            "spanforge.integrations.broken_lib": broken_mod,
        }), patch.object(auto_mod, "_INTEGRATIONS", [
            ("broken_lib", "spanforge.integrations.broken_lib", "patch", "unpatch"),
        ]), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = setup()

        assert "broken_lib" not in result
        assert any("failed to patch" in str(w.message) for w in caught)
        _remove_lib("broken_lib")

    def test_verbose_prints_output(self, capsys: pytest.CaptureFixture) -> None:
        """verbose=True should produce stdout output."""
        _inject_fake_lib("openai")
        fake_integration = _make_integration_module("openai")

        with patch.dict(sys.modules, {"spanforge.integrations.openai": fake_integration}):
            with patch.object(auto_mod, "_INTEGRATIONS", [
                ("openai", "spanforge.integrations.openai", "patch", "unpatch"),
            ]):
                setup(verbose=True)

        captured = capsys.readouterr()
        assert "openai" in captured.out
        _remove_lib("openai")

    def test_verbose_reports_skipped_when_already_patched(
        self, capsys: pytest.CaptureFixture
    ) -> None:
        auto_mod._PATCHED.add("anthropic")
        _inject_fake_lib("anthropic")
        fake_integration = _make_integration_module("anthropic")

        with patch.dict(sys.modules, {"spanforge.integrations.anthropic": fake_integration}):
            with patch.object(auto_mod, "_INTEGRATIONS", [
                ("anthropic", "spanforge.integrations.anthropic", "patch", "unpatch"),
            ]):
                setup(verbose=True)

        captured = capsys.readouterr()
        assert "already patched" in captured.out
        _remove_lib("anthropic")


# ---------------------------------------------------------------------------
# teardown()
# ---------------------------------------------------------------------------


class TestTeardown:
    def test_teardown_unpatches_registered_libs(self) -> None:
        """teardown() must call unpatch for every lib in _PATCHED."""
        _inject_fake_lib("openai")
        fake_integration = _make_integration_module("openai")
        fake_integration.patch()  # type: ignore[attr-defined]
        auto_mod._PATCHED.add("openai")

        with patch.dict(sys.modules, {"spanforge.integrations.openai": fake_integration}):
            with patch.object(auto_mod, "_INTEGRATIONS", [
                ("openai", "spanforge.integrations.openai", "patch", "unpatch"),
            ]):
                result = teardown()

        assert "openai" in result
        assert "openai" not in patched_integrations()
        assert not fake_integration.is_patched()  # type: ignore[attr-defined]
        _remove_lib("openai")

    def test_teardown_noop_when_nothing_patched(self) -> None:
        """teardown() with nothing patched should return an empty set."""
        result = teardown()
        assert result == set()

    def test_teardown_verbose_prints_output(self, capsys: pytest.CaptureFixture) -> None:
        auto_mod._PATCHED.add("groq")
        _inject_fake_lib("groq")
        fake_integration = _make_integration_module("groq")

        with patch.dict(sys.modules, {"spanforge.integrations.groq": fake_integration}):
            with patch.object(auto_mod, "_INTEGRATIONS", [
                ("groq", "spanforge.integrations.groq", "patch", "unpatch"),
            ]):
                teardown(verbose=True)

        captured = capsys.readouterr()
        assert "groq" in captured.out
        _remove_lib("groq")

    def test_teardown_emits_warning_on_unpatch_failure(self) -> None:
        auto_mod._PATCHED.add("ollama")
        _inject_fake_lib("ollama")
        broken_mod = types.ModuleType("spanforge.integrations.ollama")

        def bad_unpatch() -> None:
            raise RuntimeError("cannot unpatch")

        broken_mod.patch = lambda: None  # type: ignore[attr-defined]
        broken_mod.unpatch = bad_unpatch  # type: ignore[attr-defined]

        with patch.dict(sys.modules, {
            "ollama": sys.modules["ollama"],
            "spanforge.integrations.ollama": broken_mod,
        }), patch.object(auto_mod, "_INTEGRATIONS", [
            ("ollama", "spanforge.integrations.ollama", "patch", "unpatch"),
        ]), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            teardown()

        assert any("failed to unpatch" in str(w.message) for w in caught)
        _remove_lib("ollama")


# ---------------------------------------------------------------------------
# patched_integrations()
# ---------------------------------------------------------------------------


class TestPatchedIntegrations:
    def test_returns_empty_initially(self) -> None:
        assert patched_integrations() == set()

    def test_returns_snapshot_not_live_reference(self) -> None:
        auto_mod._PATCHED.add("openai")
        snapshot = patched_integrations()
        auto_mod._PATCHED.add("anthropic")
        assert "anthropic" not in snapshot

    def test_reflects_patched_state(self) -> None:
        auto_mod._PATCHED.add("groq")
        auto_mod._PATCHED.add("ollama")
        result = patched_integrations()
        assert "groq" in result
        assert "ollama" in result


# ---------------------------------------------------------------------------
# setup → teardown round-trip
# ---------------------------------------------------------------------------


class TestSetupTeardownRoundtrip:
    def test_setup_then_teardown_leaves_clean_state(self) -> None:
        _inject_fake_lib("openai")
        fake_integration = _make_integration_module("openai")

        with patch.dict(sys.modules, {"spanforge.integrations.openai": fake_integration}):
            with patch.object(auto_mod, "_INTEGRATIONS", [
                ("openai", "spanforge.integrations.openai", "patch", "unpatch"),
            ]):
                patched = setup()
                assert "openai" in patched
                unpatched = teardown()
                assert "openai" in unpatched
                assert patched_integrations() == set()

        _remove_lib("openai")

    def test_double_setup_is_idempotent(self) -> None:
        _inject_fake_lib("openai")
        fake_integration = _make_integration_module("openai")

        with patch.dict(sys.modules, {"spanforge.integrations.openai": fake_integration}):
            with patch.object(auto_mod, "_INTEGRATIONS", [
                ("openai", "spanforge.integrations.openai", "patch", "unpatch"),
            ]):
                first = setup()
                second = setup()

        assert "openai" in first
        assert "openai" not in second  # second call returns nothing new
        _remove_lib("openai")
