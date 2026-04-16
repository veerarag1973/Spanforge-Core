"""Tests for spanforge.config.interpolate_env."""
from __future__ import annotations

import os

import pytest

from spanforge.config import interpolate_env


class TestInterpolateEnvStrings:
    def test_resolves_set_variable(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "hello")
        assert interpolate_env("${MY_VAR}") == "hello"

    def test_unset_variable_no_default_left_as_is(self, monkeypatch):
        monkeypatch.delenv("UNSET_VAR_XYZ", raising=False)
        result = interpolate_env("${UNSET_VAR_XYZ}")
        assert result == "${UNSET_VAR_XYZ}"

    def test_unset_variable_with_default(self, monkeypatch):
        monkeypatch.delenv("UNSET_WITH_DEFAULT", raising=False)
        result = interpolate_env("${UNSET_WITH_DEFAULT:fallback-value}")
        assert result == "fallback-value"

    def test_set_variable_with_default_uses_env_not_default(self, monkeypatch):
        monkeypatch.setenv("MY_VAR", "real-value")
        result = interpolate_env("${MY_VAR:default-value}")
        assert result == "real-value"

    def test_multiple_vars_in_one_string(self, monkeypatch):
        monkeypatch.setenv("HOST", "localhost")
        monkeypatch.setenv("PORT", "5432")
        result = interpolate_env("${HOST}:${PORT}/db")
        assert result == "localhost:5432/db"

    def test_partial_substitution_preserves_unset(self, monkeypatch):
        monkeypatch.setenv("HOST", "localhost")
        monkeypatch.delenv("UNSET_PORT", raising=False)
        result = interpolate_env("${HOST}:${UNSET_PORT}/db")
        assert result == "localhost:${UNSET_PORT}/db"

    def test_no_vars_unchanged(self):
        result = interpolate_env("plain text with no vars")
        assert result == "plain text with no vars"

    def test_default_can_be_empty_string(self, monkeypatch):
        monkeypatch.delenv("EMPTY_DEFAULT", raising=False)
        result = interpolate_env("${EMPTY_DEFAULT:}")
        assert result == ""


class TestInterpolateEnvDict:
    def test_interpolates_values(self, monkeypatch):
        monkeypatch.setenv("API_KEY", "secret-123")
        data = {"key": "${API_KEY}", "static": "no-change"}
        result = interpolate_env(data)
        assert result == {"key": "secret-123", "static": "no-change"}

    def test_interpolates_nested_dict(self, monkeypatch):
        monkeypatch.setenv("NESTED_VAR", "nested-value")
        data = {"outer": {"inner": "${NESTED_VAR}"}}
        result = interpolate_env(data)
        assert result["outer"]["inner"] == "nested-value"

    def test_original_dict_not_mutated(self, monkeypatch):
        monkeypatch.setenv("X", "val")
        data = {"key": "${X}"}
        original = {"key": "${X}"}
        interpolate_env(data)
        assert data == original

    def test_does_not_interpolate_keys(self, monkeypatch):
        monkeypatch.setenv("KEYVAR", "replaced")
        data = {"${KEYVAR}": "value"}
        result = interpolate_env(data)
        # Keys should NOT be interpolated — only values
        assert "${KEYVAR}" in result


class TestInterpolateEnvList:
    def test_interpolates_list_items(self, monkeypatch):
        monkeypatch.setenv("ITEM", "val")
        data = ["${ITEM}", "static"]
        result = interpolate_env(data)
        assert result == ["val", "static"]

    def test_nested_list_in_dict(self, monkeypatch):
        monkeypatch.setenv("HOST", "myhost")
        data = {"hosts": ["${HOST}", "other"]}
        result = interpolate_env(data)
        assert result["hosts"] == ["myhost", "other"]


class TestInterpolateEnvNonString:
    def test_integer_unchanged(self):
        assert interpolate_env(42) == 42

    def test_float_unchanged(self):
        assert interpolate_env(3.14) == 3.14

    def test_none_unchanged(self):
        assert interpolate_env(None) is None

    def test_bool_unchanged(self):
        assert interpolate_env(True) is True
        assert interpolate_env(False) is False

    def test_mixed_dict_values(self, monkeypatch):
        monkeypatch.setenv("STR_VAR", "replaced")
        data = {
            "str": "${STR_VAR}",
            "int": 42,
            "float": 3.14,
            "null": None,
            "bool": True,
            "list": [1, "${STR_VAR}"],
        }
        result = interpolate_env(data)
        assert result["str"] == "replaced"
        assert result["int"] == 42
        assert result["float"] == 3.14
        assert result["null"] is None
        assert result["bool"] is True
        assert result["list"] == [1, "replaced"]
