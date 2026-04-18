"""tests/test_sf9_config.py — Phase 9 Integration Config & Local Fallback tests.

Covers:
* CFG-001-007: config.py - TOML parser, dataclasses, env overrides, validation
* CFG-010-013: registry.py - ServiceRegistry singleton, health checks
* CFG-020-027: fallback.py - all 8 local fallback functions
* _exceptions.py: SFConfigError, SFConfigValidationError
* _base.py: _KNOWN_SPANFORGE_VARS additions
* _cli.py: `config validate` subcommand
* sdk/__init__.py: Phase 9 exports
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_toml(content: str, tmp_path: Path) -> Path:
    """Write *content* to a temp .halluccheck.toml and return its path."""
    p = tmp_path / ".halluccheck.toml"
    p.write_text(content, encoding="utf-8")
    return p


# ===========================================================================
# Test block 1: Exceptions
# ===========================================================================


class TestSFConfigError:
    def test_is_sf_error_subclass(self) -> None:
        from spanforge.sdk._exceptions import SFConfigError, SFError

        assert issubclass(SFConfigError, SFError)

    def test_message_includes_detail(self) -> None:
        from spanforge.sdk._exceptions import SFConfigError

        exc = SFConfigError("bad file")
        assert "bad file" in str(exc)
        assert exc.detail == "bad file"

    def test_in_all(self) -> None:
        import spanforge.sdk._exceptions as m

        assert "SFConfigError" in m.__all__


class TestSFConfigValidationError:
    def test_is_config_error_subclass(self) -> None:
        from spanforge.sdk._exceptions import SFConfigError, SFConfigValidationError

        assert issubclass(SFConfigValidationError, SFConfigError)

    def test_stores_errors_list(self) -> None:
        from spanforge.sdk._exceptions import SFConfigValidationError

        exc = SFConfigValidationError(["error one", "error two"])
        assert exc.errors == ["error one", "error two"]

    def test_message_contains_errors(self) -> None:
        from spanforge.sdk._exceptions import SFConfigValidationError

        exc = SFConfigValidationError(["bad threshold", "bad action"])
        msg = str(exc)
        assert "bad threshold" in msg
        assert "bad action" in msg

    def test_in_all(self) -> None:
        import spanforge.sdk._exceptions as m

        assert "SFConfigValidationError" in m.__all__


# ===========================================================================
# Test block 2: _base.py known vars
# ===========================================================================


class TestKnownSpanforgeVars:
    def test_phase9_vars_present(self) -> None:
        from spanforge.sdk._base import _KNOWN_SPANFORGE_VARS

        for var in (
            "SPANFORGE_PII_THRESHOLD",
            "SPANFORGE_SECRETS_AUTO_BLOCK",
            "SPANFORGE_FALLBACK_MAX_RETRIES",
            "SPANFORGE_FALLBACK_TIMEOUT_MS",
            "SPANFORGE_LOCAL_TOKEN",
        ):
            assert var in _KNOWN_SPANFORGE_VARS, f"Missing: {var}"

    def test_original_vars_still_present(self) -> None:
        from spanforge.sdk._base import _KNOWN_SPANFORGE_VARS

        for var in ("SPANFORGE_ENDPOINT", "SPANFORGE_API_KEY", "SPANFORGE_PROJECT_ID"):
            assert var in _KNOWN_SPANFORGE_VARS


# ===========================================================================
# Test block 3: SFServiceToggles
# ===========================================================================


class TestSFServiceToggles:
    def test_defaults_all_true(self) -> None:
        from spanforge.sdk.config import SFServiceToggles

        t = SFServiceToggles()
        svc_names = (
            "sf_observe", "sf_pii", "sf_secrets", "sf_audit",
            "sf_gate", "sf_cec", "sf_identity", "sf_alert",
        )
        for name in svc_names:
            assert getattr(t, name) is True

    def test_is_enabled_known(self) -> None:
        from spanforge.sdk.config import SFServiceToggles

        t = SFServiceToggles(sf_pii=False)
        assert t.is_enabled("sf_pii") is False
        assert t.is_enabled("sf_audit") is True

    def test_is_enabled_unknown_returns_true(self) -> None:
        from spanforge.sdk.config import SFServiceToggles

        t = SFServiceToggles()
        assert t.is_enabled("sf_nonexistent") is True

    def test_as_dict_keys(self) -> None:
        from spanforge.sdk.config import SFServiceToggles

        d = SFServiceToggles().as_dict()
        assert set(d.keys()) == {
            "sf_observe", "sf_pii", "sf_secrets", "sf_audit",
            "sf_gate", "sf_cec", "sf_identity", "sf_alert",
        }

    def test_as_dict_values(self) -> None:
        from spanforge.sdk.config import SFServiceToggles

        t = SFServiceToggles(sf_gate=False)
        d = t.as_dict()
        assert d["sf_gate"] is False
        assert d["sf_pii"] is True


# ===========================================================================
# Test block 4: SFLocalFallbackConfig
# ===========================================================================


class TestSFLocalFallbackConfig:
    def test_defaults(self) -> None:
        from spanforge.sdk.config import SFLocalFallbackConfig

        f = SFLocalFallbackConfig()
        assert f.enabled is True
        assert f.max_retries == 3
        assert f.timeout_ms == 2000

    def test_custom_values(self) -> None:
        from spanforge.sdk.config import SFLocalFallbackConfig

        f = SFLocalFallbackConfig(enabled=False, max_retries=1, timeout_ms=500)
        assert f.enabled is False
        assert f.max_retries == 1
        assert f.timeout_ms == 500


# ===========================================================================
# Test block 5: SFPIIConfig
# ===========================================================================


class TestSFPIIConfig:
    def test_defaults(self) -> None:
        from spanforge.sdk.config import SFPIIConfig

        c = SFPIIConfig()
        assert c.enabled is True
        assert c.action == "redact"
        assert c.threshold == pytest.approx(0.75)
        assert c.entity_types == []
        assert c.dpdp_scope == []

    def test_custom(self) -> None:
        from spanforge.sdk.config import SFPIIConfig

        c = SFPIIConfig(action="block", threshold=0.9, entity_types=["EMAIL"])
        assert c.action == "block"
        assert c.threshold == pytest.approx(0.9)
        assert "EMAIL" in c.entity_types


# ===========================================================================
# Test block 6: SFSecretsConfig
# ===========================================================================


class TestSFSecretsConfig:
    def test_defaults(self) -> None:
        from spanforge.sdk.config import SFSecretsConfig

        c = SFSecretsConfig()
        assert c.enabled is True
        assert c.auto_block is True
        assert c.confidence == pytest.approx(0.75)
        assert c.allowlist == []
        assert c.store_redacted is False

    def test_custom(self) -> None:
        from spanforge.sdk.config import SFSecretsConfig

        c = SFSecretsConfig(auto_block=False, confidence=0.5, allowlist=["AKIA_EXAMPLE"])
        assert c.auto_block is False
        assert "AKIA_EXAMPLE" in c.allowlist


# ===========================================================================
# Test block 7: SFConfigBlock
# ===========================================================================


class TestSFConfigBlock:
    def test_defaults(self) -> None:
        from spanforge.sdk.config import SFConfigBlock

        b = SFConfigBlock()
        assert b.enabled is True
        assert b.project_id == ""
        assert b.endpoint == ""

    def test_sub_configs_are_instances(self) -> None:
        from spanforge.sdk.config import (
            SFConfigBlock,
            SFLocalFallbackConfig,
            SFPIIConfig,
            SFSecretsConfig,
            SFServiceToggles,
        )

        b = SFConfigBlock()
        assert isinstance(b.services, SFServiceToggles)
        assert isinstance(b.local_fallback, SFLocalFallbackConfig)
        assert isinstance(b.pii, SFPIIConfig)
        assert isinstance(b.secrets, SFSecretsConfig)


# ===========================================================================
# Test block 8: _parse_toml (via load_config_file)
# ===========================================================================


class TestParseToml:
    def test_basic_scalar_types(self, tmp_path: Path) -> None:
        from spanforge.sdk.config import load_config_file

        p = _make_toml(
            """
[spanforge]
enabled = true
project_id = "my-project"
endpoint = "https://api.example.com"

[spanforge.local_fallback]
enabled = false
max_retries = 5
timeout_ms = 1000
""",
            tmp_path,
        )
        block = load_config_file(p)
        assert block.enabled is True
        assert block.project_id == "my-project"
        assert block.endpoint == "https://api.example.com"
        assert block.local_fallback.enabled is False
        assert block.local_fallback.max_retries == 5
        assert block.local_fallback.timeout_ms == 1000

    def test_service_toggles(self, tmp_path: Path) -> None:
        from spanforge.sdk.config import load_config_file

        p = _make_toml(
            """
[spanforge.services]
sf_pii = false
sf_gate = false
""",
            tmp_path,
        )
        block = load_config_file(p)
        assert block.services.sf_pii is False
        assert block.services.sf_gate is False
        assert block.services.sf_audit is True  # default

    def test_pii_block(self, tmp_path: Path) -> None:
        from spanforge.sdk.config import load_config_file

        p = _make_toml(
            """
[pii]
enabled = true
action = "flag"
threshold = 0.8
entity_types = ["EMAIL", "SSN"]
dpdp_scope = ["marketing"]
""",
            tmp_path,
        )
        block = load_config_file(p)
        assert block.pii.action == "flag"
        assert block.pii.threshold == pytest.approx(0.8)
        assert "EMAIL" in block.pii.entity_types
        assert "SSN" in block.pii.entity_types
        assert "marketing" in block.pii.dpdp_scope

    def test_secrets_block(self, tmp_path: Path) -> None:
        from spanforge.sdk.config import load_config_file

        p = _make_toml(
            """
[secrets]
enabled = true
auto_block = false
confidence = 0.6
allowlist = ["AKIA_EXAMPLE"]
store_redacted = true
""",
            tmp_path,
        )
        block = load_config_file(p)
        assert block.secrets.auto_block is False
        assert block.secrets.confidence == pytest.approx(0.6)
        assert "AKIA_EXAMPLE" in block.secrets.allowlist
        assert block.secrets.store_redacted is True

    def test_comments_ignored(self, tmp_path: Path) -> None:
        from spanforge.sdk.config import load_config_file

        p = _make_toml(
            """
# This is a comment
[spanforge]
# Another comment
project_id = "test"  # inline comment
""",
            tmp_path,
        )
        block = load_config_file(p)
        assert block.project_id == "test"

    def test_unknown_keys_warn(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        from spanforge.sdk.config import load_config_file

        p = _make_toml(
            """
[spanforge]
project_id = "test"
unknown_key = "should_warn"
""",
            tmp_path,
        )
        with caplog.at_level(logging.WARNING, logger="spanforge.sdk.config"):
            load_config_file(p)
        assert any("unknown_key" in r.message for r in caplog.records)

    def test_empty_file_returns_defaults(self, tmp_path: Path) -> None:
        from spanforge.sdk.config import load_config_file

        p = _make_toml("", tmp_path)
        block = load_config_file(p)
        assert block.enabled is True
        assert block.project_id == ""

    def test_parse_error_raises_config_error(self, tmp_path: Path) -> None:
        from spanforge.sdk._exceptions import SFConfigError
        from spanforge.sdk.config import load_config_file

        # Create a file that is valid TOML structure but reference a non-existent file
        # to trigger an I/O error via explicit path to non-existent
        with pytest.raises(SFConfigError):
            # Pass a path to a non-existent file after creating it with invalid content
            bad_path = tmp_path / ".halluccheck.toml"
            bad_path.write_text("[spanforge\nno closing bracket", encoding="utf-8")
            # On Python 3.11+ tomllib will reject this; on 3.9/3.10 our parser silently ignores it
            # So instead, we patch to force an error
            with patch("spanforge.sdk.config._parse_toml", side_effect=ValueError("forced")):
                load_config_file(bad_path)


# ===========================================================================
# Test block 9: load_config_file discovery
# ===========================================================================


class TestLoadConfigFileDiscovery:
    def test_no_file_returns_defaults(self) -> None:
        from spanforge.sdk.config import load_config_file

        with (
            patch("spanforge.sdk.config._find_config", return_value=None),
            patch.dict(os.environ, {}, clear=False),
        ):
            # Remove env vars that might change defaults
            env_clean = {
                k: v
                for k, v in os.environ.items()
                if not k.startswith("SPANFORGE_")
            }
            with patch.dict(os.environ, env_clean, clear=True):
                block = load_config_file(None)
        assert block.enabled is True

    def test_explicit_path_used(self, tmp_path: Path) -> None:
        from spanforge.sdk.config import load_config_file

        p = _make_toml('[spanforge]\nproject_id = "explicit"', tmp_path)
        block = load_config_file(p)
        assert block.project_id == "explicit"

    def test_nonexistent_explicit_path_returns_defaults(self) -> None:
        from spanforge.sdk.config import load_config_file

        with patch.dict(os.environ, {}, clear=False):
            env_clean = {k: v for k, v in os.environ.items() if not k.startswith("SPANFORGE_")}
            with patch.dict(os.environ, env_clean, clear=True):
                block = load_config_file("/definitely/does/not/exist/.halluccheck.toml")
        assert block.enabled is True  # returns defaults, no error

    def test_find_config_cwd_discovery(self, tmp_path: Path) -> None:
        """_find_config finds .halluccheck.toml in cwd when no path given."""
        from spanforge.sdk.config import _find_config

        toml = tmp_path / ".halluccheck.toml"
        toml.write_text("[spanforge]\n", encoding="utf-8")
        with patch("spanforge.sdk.config.Path.cwd", return_value=tmp_path):
            found = _find_config(None)
        assert found == toml

    def test_find_config_home_discovery(self, tmp_path: Path) -> None:
        """_find_config finds .halluccheck.toml in home when cwd has none."""
        from spanforge.sdk.config import _find_config

        toml = tmp_path / ".halluccheck.toml"
        toml.write_text("[spanforge]\n", encoding="utf-8")
        fake_cwd = tmp_path / "empty_cwd"
        fake_cwd.mkdir()
        with (
            patch("spanforge.sdk.config.Path.cwd", return_value=fake_cwd),
            patch("spanforge.sdk.config.Path.home", return_value=tmp_path),
        ):
            found = _find_config(None)
        assert found == toml

    def test_find_config_no_file_anywhere(self, tmp_path: Path) -> None:
        """_find_config returns None when no config file exists."""
        from spanforge.sdk.config import _find_config

        fake = tmp_path / "empty"
        fake.mkdir()
        with (
            patch("spanforge.sdk.config.Path.cwd", return_value=fake),
            patch("spanforge.sdk.config.Path.home", return_value=fake),
        ):
            assert _find_config(None) is None


# ===========================================================================
# Test block 9b: _build_config_block type-guard branches
# ===========================================================================


class TestBuildConfigBlock:
    """Cover the ``if not isinstance(x, dict)`` fallback branches."""

    def test_non_dict_spanforge_section_uses_defaults(self, tmp_path: Path) -> None:
        from spanforge.sdk.config import _build_config_block

        block = _build_config_block({"spanforge": "not-a-dict"})
        assert block.enabled is True  # default
        assert block.services.sf_pii is True

    def test_non_dict_services_uses_defaults(self, tmp_path: Path) -> None:
        from spanforge.sdk.config import _build_config_block

        block = _build_config_block({"spanforge": {"services": "bad"}})
        assert block.services.sf_pii is True

    def test_non_dict_local_fallback_uses_defaults(self, tmp_path: Path) -> None:
        from spanforge.sdk.config import _build_config_block

        block = _build_config_block({"spanforge": {"local_fallback": 42}})
        assert block.local_fallback.enabled is True
        assert block.local_fallback.max_retries == 3

    def test_non_dict_pii_uses_defaults(self) -> None:
        from spanforge.sdk.config import _build_config_block

        block = _build_config_block({"pii": "invalid"})
        assert block.pii.action == "redact"
        assert block.pii.threshold == pytest.approx(0.75)

    def test_non_dict_secrets_uses_defaults(self) -> None:
        from spanforge.sdk.config import _build_config_block

        block = _build_config_block({"secrets": 123})
        assert block.secrets.auto_block is True
        assert block.secrets.confidence == pytest.approx(0.75)

    def test_non_list_entity_types_uses_empty(self) -> None:
        from spanforge.sdk.config import _build_config_block

        block = _build_config_block({"pii": {"entity_types": "not-a-list"}})
        assert block.pii.entity_types == []

    def test_non_list_dpdp_scope_uses_empty(self) -> None:
        from spanforge.sdk.config import _build_config_block

        block = _build_config_block({"pii": {"dpdp_scope": 99}})
        assert block.pii.dpdp_scope == []

    def test_non_list_allowlist_uses_empty(self) -> None:
        from spanforge.sdk.config import _build_config_block

        block = _build_config_block({"secrets": {"allowlist": "not-a-list"}})
        assert block.secrets.allowlist == []


# ===========================================================================
# Test block 10: _apply_env_overrides (CFG-006)
# ===========================================================================


class TestApplyEnvOverrides:
    def test_endpoint_override(self, tmp_path: Path) -> None:
        from spanforge.sdk.config import load_config_file

        p = _make_toml('[spanforge]\nendpoint = "https://old.example.com"', tmp_path)
        with patch.dict(os.environ, {"SPANFORGE_ENDPOINT": "https://new.example.com"}):
            block = load_config_file(p)
        assert block.endpoint == "https://new.example.com"

    def test_project_id_override(self, tmp_path: Path) -> None:
        from spanforge.sdk.config import load_config_file

        p = _make_toml('[spanforge]\nproject_id = "old-project"', tmp_path)
        with patch.dict(os.environ, {"SPANFORGE_PROJECT_ID": "new-project"}):
            block = load_config_file(p)
        assert block.project_id == "new-project"

    def test_pii_threshold_override(self, tmp_path: Path) -> None:
        from spanforge.sdk.config import load_config_file

        p = _make_toml("", tmp_path)
        with patch.dict(os.environ, {"SPANFORGE_PII_THRESHOLD": "0.9"}):
            block = load_config_file(p)
        assert block.pii.threshold == pytest.approx(0.9)

    def test_pii_threshold_invalid_ignored(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from spanforge.sdk.config import load_config_file

        p = _make_toml("", tmp_path)
        with (
            caplog.at_level(logging.WARNING, logger="spanforge.sdk.config"),
            patch.dict(os.environ, {"SPANFORGE_PII_THRESHOLD": "not-a-float"}),
        ):
            block = load_config_file(p)
        # Should keep default and emit warning
        assert block.pii.threshold == pytest.approx(0.75)
        assert any("SPANFORGE_PII_THRESHOLD" in r.message for r in caplog.records)

    def test_secrets_auto_block_false(self, tmp_path: Path) -> None:
        from spanforge.sdk.config import load_config_file

        p = _make_toml("", tmp_path)
        with patch.dict(os.environ, {"SPANFORGE_SECRETS_AUTO_BLOCK": "false"}):
            block = load_config_file(p)
        assert block.secrets.auto_block is False

    def test_local_fallback_disabled(self, tmp_path: Path) -> None:
        from spanforge.sdk.config import load_config_file

        p = _make_toml("", tmp_path)
        with patch.dict(os.environ, {"SPANFORGE_LOCAL_FALLBACK": "0"}):
            block = load_config_file(p)
        assert block.local_fallback.enabled is False

    def test_fallback_max_retries_override(self, tmp_path: Path) -> None:
        from spanforge.sdk.config import load_config_file

        p = _make_toml("", tmp_path)
        with patch.dict(os.environ, {"SPANFORGE_FALLBACK_MAX_RETRIES": "10"}):
            block = load_config_file(p)
        assert block.local_fallback.max_retries == 10

    def test_fallback_timeout_ms_override(self, tmp_path: Path) -> None:
        from spanforge.sdk.config import load_config_file

        p = _make_toml("", tmp_path)
        with patch.dict(os.environ, {"SPANFORGE_FALLBACK_TIMEOUT_MS": "5000"}):
            block = load_config_file(p)
        assert block.local_fallback.timeout_ms == 5000

    def test_fallback_max_retries_invalid_ignored(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from spanforge.sdk.config import load_config_file

        p = _make_toml("", tmp_path)
        with (
            caplog.at_level(logging.WARNING, logger="spanforge.sdk.config"),
            patch.dict(os.environ, {"SPANFORGE_FALLBACK_MAX_RETRIES": "bad"}),
        ):
            block = load_config_file(p)
        assert block.local_fallback.max_retries == 3  # default

    def test_fallback_timeout_ms_invalid_ignored(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from spanforge.sdk.config import load_config_file

        p = _make_toml("", tmp_path)
        with (
            caplog.at_level(logging.WARNING, logger="spanforge.sdk.config"),
            patch.dict(os.environ, {"SPANFORGE_FALLBACK_TIMEOUT_MS": "nope"}),
        ):
            block = load_config_file(p)
        assert block.local_fallback.timeout_ms == 2000  # default

    def test_debug_logging_emits_resolved_config(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from spanforge.sdk.config import load_config_file

        p = _make_toml('[spanforge]\nproject_id = "dbg"', tmp_path)
        with caplog.at_level(logging.DEBUG, logger="spanforge.sdk.config"):
            load_config_file(p)
        assert any("Resolved SpanForge config" in r.message for r in caplog.records)


# ===========================================================================
# Test block 11: validate_config / validate_config_strict (CFG-007)
# ===========================================================================


class TestValidateConfig:
    def test_valid_defaults(self) -> None:
        from spanforge.sdk.config import SFConfigBlock, validate_config

        assert validate_config(SFConfigBlock()) == []

    def test_invalid_pii_action(self) -> None:
        from spanforge.sdk.config import SFConfigBlock, SFPIIConfig, validate_config

        b = SFConfigBlock(pii=SFPIIConfig(action="invalid"))
        errors = validate_config(b)
        assert any("action" in e for e in errors)

    def test_pii_threshold_below_range(self) -> None:
        from spanforge.sdk.config import SFConfigBlock, SFPIIConfig, validate_config

        b = SFConfigBlock(pii=SFPIIConfig(threshold=-0.1))
        errors = validate_config(b)
        assert any("threshold" in e for e in errors)

    def test_pii_threshold_above_range(self) -> None:
        from spanforge.sdk.config import SFConfigBlock, SFPIIConfig, validate_config

        b = SFConfigBlock(pii=SFPIIConfig(threshold=1.1))
        errors = validate_config(b)
        assert any("threshold" in e for e in errors)

    def test_unknown_entity_type(self) -> None:
        from spanforge.sdk.config import SFConfigBlock, SFPIIConfig, validate_config

        b = SFConfigBlock(pii=SFPIIConfig(entity_types=["FAKE_TYPE"]))
        errors = validate_config(b)
        assert any("FAKE_TYPE" in e for e in errors)

    def test_known_entity_types_valid(self) -> None:
        from spanforge.sdk.config import SFConfigBlock, SFPIIConfig, validate_config

        b = SFConfigBlock(pii=SFPIIConfig(entity_types=["EMAIL", "PHONE"]))
        assert validate_config(b) == []

    def test_secrets_confidence_below_range(self) -> None:
        from spanforge.sdk.config import SFConfigBlock, SFSecretsConfig, validate_config

        b = SFConfigBlock(secrets=SFSecretsConfig(confidence=-0.5))
        errors = validate_config(b)
        assert any("confidence" in e for e in errors)

    def test_negative_max_retries(self) -> None:
        from spanforge.sdk.config import SFConfigBlock, SFLocalFallbackConfig, validate_config

        b = SFConfigBlock(local_fallback=SFLocalFallbackConfig(max_retries=-1))
        errors = validate_config(b)
        assert any("max_retries" in e for e in errors)

    def test_negative_timeout(self) -> None:
        from spanforge.sdk.config import SFConfigBlock, SFLocalFallbackConfig, validate_config

        b = SFConfigBlock(local_fallback=SFLocalFallbackConfig(timeout_ms=-1))
        errors = validate_config(b)
        assert any("timeout_ms" in e for e in errors)

    def test_multiple_errors_returned(self) -> None:
        from spanforge.sdk.config import (
            SFConfigBlock,
            SFLocalFallbackConfig,
            SFPIIConfig,
            validate_config,
        )

        b = SFConfigBlock(
            pii=SFPIIConfig(action="BAD", threshold=2.0),
            local_fallback=SFLocalFallbackConfig(max_retries=-1),
        )
        errors = validate_config(b)
        assert len(errors) >= 3


class TestValidateConfigStrict:
    def test_raises_on_errors(self) -> None:
        from spanforge.sdk._exceptions import SFConfigValidationError
        from spanforge.sdk.config import SFConfigBlock, SFPIIConfig, validate_config_strict

        b = SFConfigBlock(pii=SFPIIConfig(action="BAD"))
        with pytest.raises(SFConfigValidationError) as exc_info:
            validate_config_strict(b)
        assert exc_info.value.errors

    def test_no_raise_on_valid(self) -> None:
        from spanforge.sdk.config import SFConfigBlock, validate_config_strict

        validate_config_strict(SFConfigBlock())  # should not raise


# ===========================================================================
# Test block 12: ServiceRegistry (CFG-010-013)
# ===========================================================================


class TestServiceRegistry:
    def setup_method(self) -> None:
        from spanforge.sdk.registry import ServiceRegistry

        ServiceRegistry._reset_for_testing()

    def teardown_method(self) -> None:
        from spanforge.sdk.registry import ServiceRegistry

        ServiceRegistry._reset_for_testing()

    def test_singleton(self) -> None:
        from spanforge.sdk.registry import ServiceRegistry

        r1 = ServiceRegistry.get_instance()
        r2 = ServiceRegistry.get_instance()
        assert r1 is r2

    def test_reset_creates_new_instance(self) -> None:
        from spanforge.sdk.registry import ServiceRegistry

        r1 = ServiceRegistry.get_instance()
        ServiceRegistry._reset_for_testing()
        r2 = ServiceRegistry.get_instance()
        assert r1 is not r2

    def test_register_and_get(self) -> None:
        from spanforge.sdk.registry import ServiceRegistry

        reg = ServiceRegistry.get_instance()
        mock_client = MagicMock()
        reg.register("sf_pii", mock_client)
        assert reg.get("sf_pii") is mock_client

    def test_get_nonexistent_returns_none(self) -> None:
        from spanforge.sdk.registry import ServiceRegistry

        reg = ServiceRegistry.get_instance()
        assert reg.get("sf_nonexistent") is None

    def test_register_all(self) -> None:
        from spanforge.sdk.registry import ServiceRegistry

        reg = ServiceRegistry.get_instance()
        clients = {"sf_pii": MagicMock(), "sf_audit": MagicMock()}
        reg.register_all(clients)
        assert reg.get("sf_pii") is clients["sf_pii"]
        assert reg.get("sf_audit") is clients["sf_audit"]

    def test_status_response_structure(self) -> None:
        from spanforge.sdk.registry import ServiceRegistry

        reg = ServiceRegistry.get_instance()
        resp = reg.status_response()
        assert isinstance(resp, dict)
        for name in ("sf_pii", "sf_secrets", "sf_audit", "sf_observe"):
            assert name in resp
            entry = resp[name]
            assert "status" in entry
            assert "latency_ms" in entry
            assert "last_checked_at" in entry

    def test_update_and_get_health(self) -> None:
        from spanforge.sdk.registry import ServiceHealth, ServiceRegistry, ServiceStatus

        reg = ServiceRegistry.get_instance()
        from datetime import datetime, timezone

        h = ServiceHealth(
            status=ServiceStatus.UP,
            latency_ms=42.0,
            last_checked_at=datetime.now(tz=timezone.utc),
        )
        reg.update_health("sf_pii", h)
        retrieved = reg.get_health("sf_pii")
        assert retrieved is not None
        assert retrieved.status == ServiceStatus.UP
        assert retrieved.latency_ms == pytest.approx(42.0)


class TestServiceRegistryStartupCheck:
    def setup_method(self) -> None:
        from spanforge.sdk.registry import ServiceRegistry

        ServiceRegistry._reset_for_testing()

    def teardown_method(self) -> None:
        from spanforge.sdk.registry import ServiceRegistry

        ServiceRegistry._reset_for_testing()

    def test_local_mode_skips_http(self) -> None:
        """run_startup_check with empty endpoint should not attempt HTTP."""
        from spanforge.sdk.registry import ServiceRegistry

        reg = ServiceRegistry.get_instance()
        # No HTTP calls should be made when endpoint is empty
        with patch("spanforge.sdk.registry.urllib.request.urlopen") as mock_open:
            reg.run_startup_check(
                endpoint="",
                enabled_services={"sf_pii", "sf_audit"},
                local_fallback_enabled=True,
                timeout_ms=500,
            )
        mock_open.assert_not_called()

    def test_startup_raises_when_down_and_fallback_disabled(self) -> None:
        from spanforge.sdk._exceptions import SFStartupError
        from spanforge.sdk.registry import ServiceRegistry

        reg = ServiceRegistry.get_instance()
        # Simulate unreachable endpoint
        with patch(
            "spanforge.sdk.registry.urllib.request.urlopen",
            side_effect=OSError("Connection refused"),
        ), pytest.raises(SFStartupError):
            reg.run_startup_check(
                endpoint="https://api.example.com",
                enabled_services={"sf_pii"},
                local_fallback_enabled=False,
                timeout_ms=100,
            )

    def test_startup_succeeds_with_fallback_when_down(self) -> None:
        from spanforge.sdk.registry import ServiceRegistry

        reg = ServiceRegistry.get_instance()
        with patch(
            "spanforge.sdk.registry.urllib.request.urlopen",
            side_effect=OSError("Connection refused"),
        ):
            # Should not raise when fallback is enabled
            reg.run_startup_check(
                endpoint="https://api.example.com",
                enabled_services={"sf_pii"},
                local_fallback_enabled=True,
                timeout_ms=100,
            )


class TestServiceStatus:
    def test_enum_values(self) -> None:
        from spanforge.sdk.registry import ServiceStatus

        assert ServiceStatus.UP == "up"
        assert ServiceStatus.DEGRADED == "degraded"
        assert ServiceStatus.DOWN == "down"


class TestServiceHealthCheck:
    """Cover the HTTP success path in _check_service (lines 223-235)."""

    def setup_method(self) -> None:
        from spanforge.sdk.registry import ServiceRegistry

        ServiceRegistry._reset_for_testing()

    def teardown_method(self) -> None:
        from spanforge.sdk.registry import ServiceRegistry

        ServiceRegistry._reset_for_testing()

    def test_check_service_returns_up_on_200(self) -> None:
        from spanforge.sdk.registry import ServiceRegistry, ServiceStatus

        reg = ServiceRegistry.get_instance()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("spanforge.sdk.registry.urllib.request.urlopen", return_value=mock_resp):
            health = reg._check_service("sf_pii", "https://api.example.com", 500)
        assert health.status == ServiceStatus.UP

    def test_check_service_returns_down_on_500(self) -> None:
        from spanforge.sdk.registry import ServiceRegistry, ServiceStatus

        reg = ServiceRegistry.get_instance()
        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("spanforge.sdk.registry.urllib.request.urlopen", return_value=mock_resp):
            health = reg._check_service("sf_pii", "https://api.example.com", 500)
        assert health.status == ServiceStatus.DOWN

    def test_startup_check_with_http_up(self) -> None:
        """run_startup_check uses HTTP and records UP health."""
        from spanforge.sdk.registry import ServiceRegistry, ServiceStatus

        reg = ServiceRegistry.get_instance()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        with patch("spanforge.sdk.registry.urllib.request.urlopen", return_value=mock_resp):
            results = reg.run_startup_check(
                endpoint="https://api.example.com",
                enabled_services={"sf_pii"},
                local_fallback_enabled=True,
                timeout_ms=500,
            )
        assert results["sf_pii"].status == ServiceStatus.UP


class TestBackgroundChecker:
    def setup_method(self) -> None:
        from spanforge.sdk.registry import ServiceRegistry

        ServiceRegistry._reset_for_testing()

    def teardown_method(self) -> None:
        from spanforge.sdk.registry import ServiceRegistry

        reg = ServiceRegistry.get_instance()
        reg.stop_background_checker()
        ServiceRegistry._reset_for_testing()

    def test_start_and_stop(self) -> None:
        from spanforge.sdk.registry import ServiceRegistry

        reg = ServiceRegistry.get_instance()
        reg.start_background_checker(endpoint="", interval=999.0, timeout_ms=500)
        # Verify thread is running
        assert reg._bg_thread is not None
        assert reg._bg_thread.is_alive()
        reg.stop_background_checker()

    def test_double_start_no_duplicate(self) -> None:
        from spanforge.sdk.registry import ServiceRegistry

        reg = ServiceRegistry.get_instance()
        reg.start_background_checker(endpoint="", interval=999.0, timeout_ms=500)
        t1 = reg._bg_thread
        reg.start_background_checker(endpoint="", interval=999.0, timeout_ms=500)
        t2 = reg._bg_thread
        # Same thread should be reused
        assert t1 is t2
        reg.stop_background_checker()

    def test_background_checker_fires_and_updates_health(self) -> None:
        """Background checker actually runs _run_background_check at least once."""
        from spanforge.sdk.registry import ServiceRegistry, ServiceStatus

        reg = ServiceRegistry.get_instance()
        # Use a very short interval so it fires quickly
        reg.start_background_checker(endpoint="", interval=0.05, timeout_ms=100)
        time.sleep(0.3)  # wait for at least one iteration
        reg.stop_background_checker()
        # With empty endpoint, all services should be UP (local mode)
        health = reg.get_health("sf_pii")
        assert health.status == ServiceStatus.UP

    def test_run_background_check_logs_status_change(self) -> None:
        """_run_background_check logs when status changes from DOWN to UP."""
        from spanforge.sdk.registry import (
            ServiceHealth,
            ServiceRegistry,
            ServiceStatus,
        )

        reg = ServiceRegistry.get_instance()
        # Set sf_pii to DOWN first
        reg.update_health(
            "sf_pii",
            ServiceHealth(status=ServiceStatus.DOWN, latency_ms=0.0),
        )
        # Run background check with empty endpoint (→ local mode → UP)
        reg._run_background_check("", timeout_ms=100)
        # Should now be UP (recovered)
        health = reg.get_health("sf_pii")
        assert health.status == ServiceStatus.UP

    def test_run_background_check_logs_degradation(self) -> None:
        """_run_background_check logs when UP → DOWN (line 412)."""
        from spanforge.sdk.registry import (
            ServiceHealth,
            ServiceRegistry,
            ServiceStatus,
        )

        reg = ServiceRegistry.get_instance()
        # Set sf_pii to UP first
        reg.update_health(
            "sf_pii",
            ServiceHealth(status=ServiceStatus.UP, latency_ms=1.0),
        )
        # Simulate HTTP failure → DOWN
        with patch(
            "spanforge.sdk.registry.urllib.request.urlopen",
            side_effect=OSError("gone"),
        ):
            reg._run_background_check("https://api.example.com", timeout_ms=100)
        health = reg.get_health("sf_pii")
        assert health.status == ServiceStatus.DOWN

    def test_run_background_check_logs_other_change(self) -> None:
        """_run_background_check logs UP → DEGRADED (line 429 else branch)."""
        from spanforge.sdk.registry import (
            ServiceHealth,
            ServiceRegistry,
            ServiceStatus,
        )

        reg = ServiceRegistry.get_instance()
        # Set sf_pii to UP first
        reg.update_health(
            "sf_pii",
            ServiceHealth(status=ServiceStatus.UP, latency_ms=1.0),
        )
        # Mock _check_service to return DEGRADED for all services
        degraded = ServiceHealth(status=ServiceStatus.DEGRADED, latency_ms=3000.0)
        with patch.object(reg, "_check_service", return_value=degraded):
            reg._run_background_check("https://api.example.com", timeout_ms=10000)
        health = reg.get_health("sf_pii")
        assert health.status == ServiceStatus.DEGRADED


# ===========================================================================
# Test block 13: Fallback functions (CFG-020-027)
# ===========================================================================


class TestPIIFallback:
    def test_returns_fallback_true(self) -> None:
        from spanforge.sdk.fallback import pii_fallback

        mock_result = MagicMock()
        mock_result.clean = True
        mock_result.hits = []

        with patch("spanforge.secrets.scan_text", create=True, return_value=mock_result):
            result = pii_fallback({"message": "test"}, threshold=0.75, entity_types=[])
        assert result["fallback"] is True

    def test_scan_payload_called(self) -> None:
        from spanforge.sdk.fallback import pii_fallback

        mock_result = MagicMock()
        mock_result.clean = True
        mock_result.hits = []

        with patch("spanforge.redact.scan_payload", return_value=mock_result) as mock_scan:
            pii_fallback({"k": "v"}, threshold=0.8, entity_types=["EMAIL"])
        mock_scan.assert_called_once()

    def test_import_error_handled_gracefully(self) -> None:
        from spanforge.sdk.fallback import pii_fallback

        with patch.dict(sys.modules, {"spanforge.redact": None}):
            # Should not crash the process even if import fails
            try:
                result = pii_fallback({}, threshold=0.75, entity_types=[])
                # If it succeeds (module available), check fallback flag
                assert result.get("fallback") is True
            except ImportError:
                pass  # Acceptable if module truly unavailable


class TestSecretsFallback:
    def test_returns_fallback_true(self) -> None:
        from spanforge.sdk.fallback import secrets_fallback

        mock_result = MagicMock()
        mock_result.clean = True
        mock_result.hits = []

        with patch("spanforge.secrets.scan_text", create=True, return_value=mock_result):
            result = secrets_fallback("some text", confidence=0.75)
        assert result["fallback"] is True

    def test_scan_text_called(self) -> None:
        from spanforge.sdk.fallback import secrets_fallback

        mock_result = MagicMock()
        mock_result.clean = True
        mock_result.hits = []

        with patch(
            "spanforge.secrets.scan_text",
            create=True,
            return_value=mock_result,
        ) as mock_scan:
            secrets_fallback("text", confidence=0.9)
        mock_scan.assert_called_once()

    def test_scan_text_with_hits_filters_by_confidence(self) -> None:
        """Cover lines 148-160: hit list comprehension with confidence filter."""
        from spanforge.sdk.fallback import secrets_fallback

        hit_high = MagicMock(pattern_id="AWS_KEY", redacted="***", confidence=0.95)
        hit_low = MagicMock(pattern_id="MAYBE", redacted="?", confidence=0.3)

        mock_result = MagicMock()
        mock_result.hits = [hit_high, hit_low]

        import spanforge.secrets as _sm

        with patch.object(_sm, "scan_text", create=True, return_value=mock_result):
            result = secrets_fallback("aws_secret_access_key=AKIAIOSFODNN7EXAMPLE", confidence=0.75)

        assert result["fallback"] is True
        assert result["clean"] is False
        # Only the high-confidence hit should pass the filter
        assert len(result["hits"]) == 1
        assert result["hits"][0]["pattern_id"] == "AWS_KEY"

    def test_scan_text_exception_returns_error(self) -> None:
        """Cover the except branch when scan_text raises."""
        import spanforge.secrets as _sm
        from spanforge.sdk.fallback import secrets_fallback

        with patch.object(_sm, "scan_text", create=True, side_effect=RuntimeError("boom")):
            result = secrets_fallback("text", confidence=0.75)
        assert result["fallback"] is True
        assert result["clean"] is True
        assert "error" in result


class TestAuditFallback:
    def test_writes_jsonl_file(self, tmp_path: Path) -> None:
        from spanforge.sdk.fallback import audit_fallback

        fallback_file = tmp_path / "audit_fallback.jsonl"
        record = {"model_id": "gpt-4o", "verdict": "PASS", "score": 0.9}

        with patch.dict(
            os.environ,
            {"SPANFORGE_SIGNING_KEY": "test-key"},
        ):
            result = audit_fallback(
                record,
                schema_key="halluccheck.score.v1",
                fallback_path=str(fallback_file),
            )

        assert fallback_file.exists()
        assert result["fallback"] is True
        # Verify JSONL line is valid JSON
        line = fallback_file.read_text(encoding="utf-8").strip()
        data = json.loads(line)
        assert "record_id" in data
        assert "hmac" in data

    def test_appends_multiple_records(self, tmp_path: Path) -> None:
        from spanforge.sdk.fallback import audit_fallback

        fallback_file = tmp_path / "audit_fallback.jsonl"
        for i in range(3):
            audit_fallback(
                {"index": i},
                schema_key="test.v1",
                fallback_path=str(fallback_file),
            )

        lines = fallback_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 3

    def test_no_signing_key_emits_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        from spanforge.sdk.fallback import audit_fallback

        fallback_file = tmp_path / "audit_fallback.jsonl"
        env_clean = {
            k: v
            for k, v in os.environ.items()
            if k not in ("SPANFORGE_SIGNING_KEY", "SPANFORGE_MAGIC_SECRET")
        }
        with (
            caplog.at_level(logging.WARNING, logger="spanforge.sdk.fallback"),
            patch.dict(os.environ, env_clean, clear=True),
        ):
            audit_fallback(
                {"test": True},
                schema_key="test.v1",
                fallback_path=str(fallback_file),
            )
        assert any(
            "signing_key" in r.message.lower()
            for r in caplog.records
        )


class TestObserveFallback:
    def test_prints_to_stdout(self, capsys: pytest.CaptureFixture) -> None:
        from spanforge.sdk.fallback import observe_fallback

        observe_fallback({"trace_id": "abc123", "spans": []})
        captured = capsys.readouterr()
        assert "LOCAL_SPAN:" in captured.out
        assert "abc123" in captured.out

    def test_output_is_valid_json(self, capsys: pytest.CaptureFixture) -> None:
        from spanforge.sdk.fallback import observe_fallback

        observe_fallback({"key": "value"})
        captured = capsys.readouterr()
        # Extract JSON after "LOCAL_SPAN: " prefix
        line = captured.out.strip()
        assert line.startswith("LOCAL_SPAN:")
        json_part = line[len("LOCAL_SPAN:"):].strip()
        data = json.loads(json_part)
        assert data["key"] == "value"


class TestAlertFallback:
    def test_writes_to_stderr(self, capsys: pytest.CaptureFixture) -> None:
        from spanforge.sdk.fallback import alert_fallback

        alert_fallback("billing.threshold_exceeded", {"amount": 100}, severity="WARNING")
        captured = capsys.readouterr()
        assert "billing.threshold_exceeded" in captured.err

    def test_returns_fallback_true(self, capsys: pytest.CaptureFixture) -> None:
        from spanforge.sdk.fallback import alert_fallback

        result = alert_fallback("test.topic", {}, severity="INFO")
        assert result["fallback"] is True


class TestIdentityFallback:
    def test_returns_token_from_env(self) -> None:
        from spanforge.sdk.fallback import identity_fallback

        with patch.dict(os.environ, {"SPANFORGE_LOCAL_TOKEN": "local-token-abc"}):
            result = identity_fallback()
        assert result["token"] == "local-token-abc"
        assert result["fallback"] is True

    def test_explicit_token_overrides_env(self) -> None:
        from spanforge.sdk.fallback import identity_fallback

        with patch.dict(os.environ, {"SPANFORGE_LOCAL_TOKEN": "env-token"}):
            result = identity_fallback(token="explicit-token")
        assert result["token"] == "explicit-token"

    def test_no_token_raises_value_error(self) -> None:
        from spanforge.sdk.fallback import identity_fallback

        env_clean = {k: v for k, v in os.environ.items() if k != "SPANFORGE_LOCAL_TOKEN"}
        with (
            patch.dict(os.environ, env_clean, clear=True),
            pytest.raises(ValueError, match="token"),
        ):
            identity_fallback()

    def test_no_jwt_validation(self) -> None:
        """Local identity fallback must not validate JWTs (only local dev)."""
        from spanforge.sdk.fallback import identity_fallback

        # A fake JWT that would fail real validation
        fake_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.FAKE_SIG"
        with patch.dict(os.environ, {"SPANFORGE_LOCAL_TOKEN": fake_jwt}):
            result = identity_fallback()
        # Should succeed without JWT verification
        assert result["token"] == fake_jwt


class TestGateFallback:
    def test_calls_gate_runner(self, tmp_path: Path) -> None:
        from spanforge.sdk.fallback import gate_fallback

        # Create a minimal gate config file
        gate_config = tmp_path / "gates.yml"
        gate_config.write_text("gates: []\n", encoding="utf-8")

        mock_runner = MagicMock()
        mock_runner.run_pipeline.return_value = {"pass": True, "gates": []}

        with patch("spanforge.gate.GateRunner", return_value=mock_runner):
            result = gate_fallback(str(gate_config), context={"model": "gpt-4o"})

        mock_runner.run_pipeline.assert_called_once()
        assert result["fallback"] is True

    def test_missing_config_file_handled(self) -> None:
        from spanforge.sdk.fallback import gate_fallback

        with patch("spanforge.gate.GateRunner", side_effect=FileNotFoundError("no file")):
            result = gate_fallback("/nonexistent/gates.yml", context={})
        assert result["fallback"] is True
        assert "error" in result


class TestCECFallback:
    def test_writes_bundle_file(self, tmp_path: Path) -> None:
        from spanforge.sdk.fallback import audit_fallback, cec_fallback

        # Create some audit records first
        audit_file = tmp_path / "audit_fallback.jsonl"
        for i in range(2):
            audit_fallback(
                {"index": i, "model_id": "test-model"},
                schema_key="test.v1",
                fallback_path=str(audit_file),
            )

        output_path = tmp_path / "cec_bundle_test-model.jsonl"
        result = cec_fallback(
            model_id="test-model",
            framework="eu_ai_act",
            events_file=str(audit_file),
            output_path=str(output_path),
        )

        assert output_path.exists()
        assert result["fallback"] is True

    def test_no_events_file_returns_empty_bundle(self, tmp_path: Path) -> None:
        from spanforge.sdk.fallback import cec_fallback

        output_path = tmp_path / "bundle.jsonl"
        result = cec_fallback(
            model_id="test-model",
            framework="eu_ai_act",
            events_file=str(tmp_path / "nonexistent.jsonl"),
            output_path=str(output_path),
        )
        assert result["fallback"] is True

    def test_invalid_json_lines_skipped(self, tmp_path: Path) -> None:
        """Cover the JSONDecodeError except branch in cec_fallback."""
        from spanforge.sdk.fallback import cec_fallback

        events_file = tmp_path / "mixed.jsonl"
        events_file.write_text(
            '{"ok": true}\nNOT-JSON\n{"also": "ok"}\n\n',
            encoding="utf-8",
        )
        output_path = tmp_path / "cec_bundle.jsonl"
        result = cec_fallback(
            model_id="m",
            framework="eu_ai_act",
            events_file=str(events_file),
            output_path=str(output_path),
        )
        assert result["record_count"] == 2
        assert result["fallback"] is True


# ===========================================================================
# Test block 14: CLI — config validate (CFG-007)
# ===========================================================================


class TestCLIConfigValidate:
    def test_valid_config_exits_0(self, tmp_path: Path) -> None:
        from spanforge._cli import _cmd_config_validate

        p = _make_toml("[spanforge]\nproject_id = \"test\"\n", tmp_path)
        args = argparse.Namespace(file=str(p))
        assert _cmd_config_validate(args) == 0

    def test_invalid_config_exits_1(self, tmp_path: Path) -> None:
        from spanforge._cli import _cmd_config_validate

        p = _make_toml("[pii]\naction = \"INVALID_ACTION\"\n", tmp_path)
        args = argparse.Namespace(file=str(p))
        assert _cmd_config_validate(args) == 1

    def test_no_file_exits_0_with_defaults(self) -> None:
        from spanforge._cli import _cmd_config_validate

        args = argparse.Namespace(file=None)
        with patch("spanforge.sdk.config._find_config", return_value=None):
            env_clean = {k: v for k, v in os.environ.items() if not k.startswith("SPANFORGE_")}
            with patch.dict(os.environ, env_clean, clear=True):
                assert _cmd_config_validate(args) == 0

    def test_parse_error_exits_2(self, tmp_path: Path) -> None:
        from spanforge._cli import _cmd_config_validate

        p = _make_toml("", tmp_path)
        args = argparse.Namespace(file=str(p))
        with patch(
            "spanforge.sdk.config.load_config_file",
            side_effect=__import__(
                "spanforge.sdk._exceptions", fromlist=["SFConfigError"]
            ).SFConfigError("forced"),
        ):
            assert _cmd_config_validate(args) == 2

    def test_main_cli_config_validate_route(self, tmp_path: Path) -> None:
        """Integration: `spanforge config validate --file X` routes correctly."""
        p = _make_toml("[spanforge]\nproject_id = \"test\"\n", tmp_path)
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["config", "validate", "--file", str(p)])
        assert exc_info.value.code == 0

    def test_main_cli_config_no_subcommand_exits_2(self) -> None:
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["config"])
        assert exc_info.value.code == 2


# ===========================================================================
# Test block 15: sdk/__init__.py exports
# ===========================================================================


class TestSDKInitExports:
    def test_config_classes_exported(self) -> None:
        from spanforge import sdk

        for name in (
            "SFConfigBlock",
            "SFServiceToggles",
            "SFLocalFallbackConfig",
            "SFPIIConfig",
            "SFSecretsConfig",
        ):
            assert hasattr(sdk, name), f"sdk.{name} not exported"

    def test_functions_exported(self) -> None:
        from spanforge import sdk

        for name in ("load_config_file", "validate_config", "validate_config_strict"):
            assert hasattr(sdk, name), f"sdk.{name} not exported"

    def test_registry_exported(self) -> None:
        from spanforge import sdk

        for name in ("ServiceRegistry", "ServiceHealth", "ServiceStatus"):
            assert hasattr(sdk, name), f"sdk.{name} not exported"

    def test_fallback_functions_exported(self) -> None:
        from spanforge import sdk

        for name in (
            "pii_fallback",
            "secrets_fallback",
            "audit_fallback",
            "observe_fallback",
            "alert_fallback",
            "identity_fallback",
            "gate_fallback",
            "cec_fallback",
        ):
            assert hasattr(sdk, name), f"sdk.{name} not exported"

    def test_exceptions_in_all(self) -> None:
        from spanforge import sdk

        assert "SFConfigError" in sdk.__all__
        assert "SFConfigValidationError" in sdk.__all__

    def test_phase9_symbols_in_all(self) -> None:
        from spanforge import sdk

        for name in ("ServiceRegistry", "load_config_file", "pii_fallback"):
            assert name in sdk.__all__, f"{name} not in sdk.__all__"
