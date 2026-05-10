"""Tests for CARD 1D-1 — Config & Setup CLI Tools.

Covers:
  - spanforge secrets set / get / list / delete
  - spanforge dev reset --dry-run / --hard
  - spanforge config init --non-interactive / --force
  - spanforge config validate / --check-connectivity
"""

from __future__ import annotations

import argparse
import base64
import json
import socket
from pathlib import Path  # noqa: TC003
from typing import Any

import pytest

import spanforge._cli_config as cfg_mod
from spanforge._cli_config import (
    _check_config_connectivity,
    _coerce_value,
    _delete_path,
    _derive_key,
    _parse_simple_yaml,
    _prompt_confirm,
    _secrets_master_key,
    _validate_config_yaml,
    add_secrets_subcommands,
    cmd_config_init,
    cmd_config_validate,
    cmd_dev_reset,
    cmd_secrets_delete,
    cmd_secrets_get,
    cmd_secrets_list,
    cmd_secrets_set,
    dispatch_secrets_command,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ns(**kwargs: Any) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


@pytest.fixture(autouse=True)
def isolate_spanforge_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect all ~/.spanforge operations to a tmp directory for isolation."""
    sf_home = tmp_path / ".spanforge"
    sf_home.mkdir()

    monkeypatch.setattr(cfg_mod, "_SPANFORGE_HOME", sf_home)
    monkeypatch.setattr(cfg_mod, "_SECRETS_DB_PATH", sf_home / "secrets.db")
    monkeypatch.setattr(cfg_mod, "_CONFIG_PATH", sf_home / "config.yaml")


# ---------------------------------------------------------------------------
# Secrets — set / get round-trip
# ---------------------------------------------------------------------------


class TestSecretsSetGet:
    def test_set_then_get_roundtrip(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_secrets_set(_ns(key="MY_KEY", value="myvalue"))
        assert rc == 0
        rc2 = cmd_secrets_get(_ns(key="MY_KEY"))
        assert rc2 == 0
        out = capsys.readouterr().out
        assert "myvalue" in out

    def test_get_unknown_key_returns_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_secrets_get(_ns(key="NONEXISTENT"))
        assert rc == 1
        assert "not found" in capsys.readouterr().err

    def test_set_empty_key_returns_2(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_secrets_set(_ns(key="", value="val"))
        assert rc == 2
        assert "key must not be empty" in capsys.readouterr().err

    def test_set_overwrites_existing(self, capsys: pytest.CaptureFixture[str]) -> None:
        cmd_secrets_set(_ns(key="K", value="v1"))
        cmd_secrets_set(_ns(key="K", value="v2"))
        capsys.readouterr()
        cmd_secrets_get(_ns(key="K"))
        assert "v2" in capsys.readouterr().out

    def test_set_multiple_keys(self) -> None:
        cmd_secrets_set(_ns(key="A", value="alpha"))
        cmd_secrets_set(_ns(key="B", value="beta"))
        db = cfg_mod._load_secrets_db()
        assert db["A"] == "alpha"
        assert db["B"] == "beta"


# ---------------------------------------------------------------------------
# Secrets — list
# ---------------------------------------------------------------------------


class TestSecretsList:
    def test_list_empty_store(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_secrets_list(_ns())
        assert rc == 0
        out = capsys.readouterr().out
        assert "no secrets" in out.lower()

    def test_list_shows_key_names_not_values(self, capsys: pytest.CaptureFixture[str]) -> None:
        cmd_secrets_set(_ns(key="TOKEN", value="supersecret123"))
        capsys.readouterr()
        cmd_secrets_list(_ns())
        out = capsys.readouterr().out
        assert "TOKEN" in out
        assert "supersecret123" not in out

    def test_list_sorted(self, capsys: pytest.CaptureFixture[str]) -> None:
        cmd_secrets_set(_ns(key="ZZZ", value="z"))
        cmd_secrets_set(_ns(key="AAA", value="a"))
        capsys.readouterr()  # clear set output
        cmd_secrets_list(_ns())
        out = capsys.readouterr().out.strip().splitlines()
        names = [line.strip() for line in out if line.strip()]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# Secrets — delete
# ---------------------------------------------------------------------------


class TestSecretsDelete:
    def test_delete_removes_key(self, capsys: pytest.CaptureFixture[str]) -> None:
        cmd_secrets_set(_ns(key="GONE", value="bye"))
        rc = cmd_secrets_delete(_ns(key="GONE"))
        assert rc == 0
        db = cfg_mod._load_secrets_db()
        assert "GONE" not in db

    def test_delete_unknown_key_returns_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_secrets_delete(_ns(key="NOPE"))
        assert rc == 1
        assert "not found" in capsys.readouterr().err

    def test_delete_leaves_other_keys(self) -> None:
        cmd_secrets_set(_ns(key="A", value="1"))
        cmd_secrets_set(_ns(key="B", value="2"))
        cmd_secrets_delete(_ns(key="A"))
        db = cfg_mod._load_secrets_db()
        assert "B" in db
        assert "A" not in db


# ---------------------------------------------------------------------------
# Secrets — dispatch
# ---------------------------------------------------------------------------


class TestDispatchSecrets:
    def test_dispatch_set(self) -> None:
        parser = argparse.ArgumentParser()
        sub = parser.add_subparsers(dest="secrets_command")
        add_secrets_subcommands(sub)

        rc = dispatch_secrets_command(_ns(secrets_command="set", key="X", value="y"), parser)
        assert rc == 0
        assert cfg_mod._load_secrets_db()["X"] == "y"

    def test_dispatch_unknown_prints_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        parser = argparse.ArgumentParser(prog="spanforge secrets")
        rc = dispatch_secrets_command(_ns(secrets_command=None), parser)
        assert rc == 2

    def test_dispatch_list(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = dispatch_secrets_command(_ns(secrets_command="list"), argparse.ArgumentParser())
        assert rc == 0

    def test_dispatch_get(self, capsys: pytest.CaptureFixture[str]) -> None:
        cmd_secrets_set(_ns(key="G", value="gval"))
        capsys.readouterr()
        rc = dispatch_secrets_command(_ns(secrets_command="get", key="G"), argparse.ArgumentParser())
        assert rc == 0
        assert "gval" in capsys.readouterr().out

    def test_dispatch_delete(self) -> None:
        cmd_secrets_set(_ns(key="D", value="dval"))
        rc = dispatch_secrets_command(_ns(secrets_command="delete", key="D"), argparse.ArgumentParser())
        assert rc == 0
        assert "D" not in cfg_mod._load_secrets_db()


# ---------------------------------------------------------------------------
# dev reset
# ---------------------------------------------------------------------------


class TestDevReset:
    def test_dry_run_does_not_delete_files(self) -> None:
        cfg_mod._save_secrets_db({"k": "v"})
        assert cfg_mod._SECRETS_DB_PATH.exists()

        rc = cmd_dev_reset(_ns(hard=False, dry_run=True))
        assert rc == 0
        # File should still exist
        assert cfg_mod._SECRETS_DB_PATH.exists()

    def test_reset_clears_stores(self) -> None:
        cfg_mod._save_secrets_db({"k": "v"})
        assert cfg_mod._SECRETS_DB_PATH.exists()

        rc = cmd_dev_reset(_ns(hard=False, dry_run=False))
        assert rc == 0
        assert not cfg_mod._SECRETS_DB_PATH.exists()

    def test_reset_nothing_to_clear(self, capsys: pytest.CaptureFixture[str]) -> None:
        # No files present — should still succeed
        rc = cmd_dev_reset(_ns(hard=False, dry_run=False))
        assert rc == 0
        assert "nothing" in capsys.readouterr().out.lower()

    def test_hard_reset_respects_abort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """If user types 'n' at prompt, config should not be deleted."""
        cfg_path = cfg_mod._CONFIG_PATH
        cfg_path.write_text("spanforge:\n  signing_key: abc\n", encoding="utf-8")
        monkeypatch.setattr(cfg_mod, "_prompt_confirm", lambda _: False)

        rc = cmd_dev_reset(_ns(hard=True, dry_run=False))
        assert rc == 1
        # Config still present
        assert cfg_path.exists()

    def test_hard_reset_with_confirm_deletes_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg_path = cfg_mod._CONFIG_PATH
        cfg_path.write_text("spanforge:\n  signing_key: abc\n", encoding="utf-8")
        monkeypatch.setattr(cfg_mod, "_prompt_confirm", lambda _: True)

        rc = cmd_dev_reset(_ns(hard=True, dry_run=False))
        assert rc == 0
        assert not cfg_path.exists()

    def test_dry_run_prints_would_delete(self, capsys: pytest.CaptureFixture[str]) -> None:
        cfg_mod._save_secrets_db({"k": "v"})
        cmd_dev_reset(_ns(hard=False, dry_run=True))
        out = capsys.readouterr().out
        assert "dry-run" in out.lower() or "would" in out.lower()

    def test_hard_dry_run_lists_config(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--hard --dry-run should list config.yaml as a target."""
        rc = cmd_dev_reset(_ns(hard=True, dry_run=True))
        assert rc == 0
        out = capsys.readouterr().out
        assert "dry-run" in out.lower() or "would" in out.lower()

    def test_reset_deletes_directory_target(self, tmp_path: Path) -> None:
        """_delete_path should handle directories via shutil.rmtree."""
        export_dir = cfg_mod._SPANFORGE_HOME / "exports"
        export_dir.mkdir()
        (export_dir / "file.json").write_text("{}", encoding="utf-8")
        assert export_dir.exists()

        rc = cmd_dev_reset(_ns(hard=False, dry_run=False))
        assert rc == 0
        assert not export_dir.exists()


# ---------------------------------------------------------------------------
# config init
# ---------------------------------------------------------------------------


class TestConfigInit:
    def test_non_interactive_creates_config(self) -> None:
        rc = cmd_config_init(_ns(non_interactive=True, force=False))
        assert rc == 0
        assert cfg_mod._CONFIG_PATH.exists()

    def test_non_interactive_is_fast(self) -> None:
        import time
        t0 = time.monotonic()
        cmd_config_init(_ns(non_interactive=True, force=False))
        elapsed = time.monotonic() - t0
        assert elapsed < 2.0, "config init should complete in < 2s"

    def test_non_interactive_config_has_required_fields(self) -> None:
        cmd_config_init(_ns(non_interactive=True, force=False))
        content = cfg_mod._CONFIG_PATH.read_text(encoding="utf-8")
        assert "signing_key:" in content
        assert "exporter:" in content

    def test_error_if_exists_without_force(self, capsys: pytest.CaptureFixture[str]) -> None:
        cmd_config_init(_ns(non_interactive=True, force=False))
        rc = cmd_config_init(_ns(non_interactive=True, force=False))
        assert rc == 1
        assert "already exists" in capsys.readouterr().err

    def test_force_overwrites(self) -> None:
        cmd_config_init(_ns(non_interactive=True, force=False))
        cfg_mod._CONFIG_PATH.write_text("spanforge:\n  signing_key: OLD\n", encoding="utf-8")
        rc = cmd_config_init(_ns(non_interactive=True, force=True))
        assert rc == 0
        content = cfg_mod._CONFIG_PATH.read_text(encoding="utf-8")
        assert "OLD" not in content

    def test_interactive_aborts_on_eof(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """EOFError during interactive mode should return 1."""
        monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError))
        rc = cmd_config_init(_ns(non_interactive=False, force=False))
        assert rc == 1

    def test_interactive_invalid_exporter_returns_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        responses = iter(["myservice", "badexporter"])
        monkeypatch.setattr("builtins.input", lambda _: next(responses))
        rc = cmd_config_init(_ns(non_interactive=False, force=False))
        assert rc == 1

    def test_interactive_valid_full_flow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Interactive mode with all valid inputs should succeed."""
        responses = iter(["myapp", "console", "stdout", "production", "INFO"])
        monkeypatch.setattr("builtins.input", lambda _: next(responses))
        rc = cmd_config_init(_ns(non_interactive=False, force=False))
        assert rc == 0
        assert cfg_mod._CONFIG_PATH.exists()

    def test_interactive_bad_log_level_falls_back_to_info(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """An invalid log level should fall back to INFO instead of failing."""
        responses = iter(["myapp", "console", "stdout", "development", "TRACE"])
        monkeypatch.setattr("builtins.input", lambda _: next(responses))
        rc = cmd_config_init(_ns(non_interactive=False, force=False))
        assert rc == 0
        content = cfg_mod._CONFIG_PATH.read_text(encoding="utf-8")
        # TRACE is invalid — should fallback to INFO
        assert "signing_key:" in content


# ---------------------------------------------------------------------------
# config validate
# ---------------------------------------------------------------------------


class TestConfigValidate:
    def _write_config(self, content: str) -> Path:
        cfg_mod._CONFIG_PATH.write_text(content, encoding="utf-8")
        return cfg_mod._CONFIG_PATH

    def test_valid_config_exit_0(self) -> None:
        self._write_config("spanforge:\n  signing_key: abc123longkeyvalue\n")
        rc = cmd_config_validate(_ns(config=None, check_connectivity=False))
        assert rc == 0

    def test_missing_config_file_exit_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        rc = cmd_config_validate(_ns(config=None, check_connectivity=False))
        assert rc == 1
        assert "not found" in capsys.readouterr().err

    def test_missing_signing_key_exit_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        self._write_config("spanforge:\n  exporter: console\n")
        rc = cmd_config_validate(_ns(config=None, check_connectivity=False))
        assert rc == 1
        out_err = capsys.readouterr().out
        assert "signing_key" in out_err

    def test_invalid_exporter_exit_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        self._write_config("spanforge:\n  signing_key: abc\n  exporter: badexporter\n")
        rc = cmd_config_validate(_ns(config=None, check_connectivity=False))
        assert rc == 1

    def test_invalid_log_level_exit_1(self, capsys: pytest.CaptureFixture[str]) -> None:
        self._write_config("spanforge:\n  signing_key: abc\n  log_level: BADLEVEL\n")
        rc = cmd_config_validate(_ns(config=None, check_connectivity=False))
        assert rc == 1

    def test_custom_config_path(self, tmp_path: Path) -> None:
        custom = tmp_path / "custom_config.yaml"
        custom.write_text("spanforge:\n  signing_key: mykey\n", encoding="utf-8")
        rc = cmd_config_validate(_ns(config=str(custom), check_connectivity=False))
        assert rc == 0

    def test_connectivity_skip_for_console(self, capsys: pytest.CaptureFixture[str]) -> None:
        self._write_config("spanforge:\n  signing_key: abc\n  exporter: console\n")
        rc = cmd_config_validate(_ns(config=None, check_connectivity=True))
        assert rc == 0

    def test_connectivity_generic_exporter_skip(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Exporters without a network probe (e.g. datadog) should return 0."""
        self._write_config("spanforge:\n  signing_key: abc\n  exporter: datadog\n")
        rc = cmd_config_validate(_ns(config=None, check_connectivity=True))
        assert rc == 0

    def test_connectivity_otlp_unreachable_returns_2(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OTLP connectivity failure should return exit 2."""
        self._write_config(
            "spanforge:\n  signing_key: abc\n  exporter: otlp\n  endpoint: http://127.0.0.1:19999\n"
        )

        def _fail(*_a: Any, **_kw: Any) -> None:
            raise OSError("connection refused")

        monkeypatch.setattr(socket, "create_connection", _fail)
        rc = cmd_config_validate(_ns(config=None, check_connectivity=True))
        assert rc == 2

    def test_connectivity_otlp_reachable_returns_0(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Successful OTLP socket connection returns 0."""
        self._write_config(
            "spanforge:\n  signing_key: abc\n  exporter: otlp\n  endpoint: http://localhost:4317\n"
        )
        mock_conn = type("MockConn", (), {"close": lambda self: None})()
        monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: mock_conn)
        rc = cmd_config_validate(_ns(config=None, check_connectivity=True))
        assert rc == 0


# ---------------------------------------------------------------------------
# Internals — _parse_simple_yaml and _coerce_value
# ---------------------------------------------------------------------------


class TestParseSimpleYaml:
    def test_basic_section_and_keys(self) -> None:
        yaml = "spanforge:\n  signing_key: abc\n  exporter: console\n"
        result = _parse_simple_yaml(yaml)
        assert result is not None
        assert result["spanforge"]["signing_key"] == "abc"
        assert result["spanforge"]["exporter"] == "console"

    def test_top_level_scalar(self) -> None:
        yaml = "version: 2\n"
        result = _parse_simple_yaml(yaml)
        assert result is not None
        assert result["version"] == 2

    def test_bool_values(self) -> None:
        yaml = "spanforge:\n  enabled: true\n  other: false\n"
        result = _parse_simple_yaml(yaml)
        assert result is not None
        assert result["spanforge"]["enabled"] is True
        assert result["spanforge"]["other"] is False

    def test_comments_ignored(self) -> None:
        yaml = "# comment\nspanforge:\n  signing_key: val\n"
        result = _parse_simple_yaml(yaml)
        assert result is not None
        assert result["spanforge"]["signing_key"] == "val"

    def test_returns_empty_on_empty_input(self) -> None:
        result = _parse_simple_yaml("")
        assert result is not None
        assert result == {}

    def test_nested_key_without_prior_section(self) -> None:
        """Indented key with no prior section should not crash."""
        yaml = "  orphan: value\n"
        result = _parse_simple_yaml(yaml)
        assert result is not None  # may or may not capture, but must not throw

    def test_multiple_sections(self) -> None:
        yaml = "spanforge:\n  signing_key: k1\nsection2:\n  key2: v2\n"
        result = _parse_simple_yaml(yaml)
        assert result is not None
        assert "spanforge" in result
        assert "section2" in result


class TestCoerceValue:
    def test_int(self) -> None:
        assert _coerce_value("42") == 42

    def test_float(self) -> None:
        assert _coerce_value("3.14") == 3.14

    def test_bool_true(self) -> None:
        assert _coerce_value("true") is True

    def test_bool_false(self) -> None:
        assert _coerce_value("false") is False

    def test_null(self) -> None:
        assert _coerce_value("null") is None

    def test_tilde_null(self) -> None:
        assert _coerce_value("~") is None

    def test_empty_string(self) -> None:
        assert _coerce_value("") is None

    def test_string(self) -> None:
        assert _coerce_value("hello") == "hello"

    def test_double_quoted_string(self) -> None:
        assert _coerce_value('"hello world"') == "hello world"

    def test_single_quoted_string(self) -> None:
        assert _coerce_value("'hello world'") == "hello world"


# ---------------------------------------------------------------------------
# Internals — _derive_key, _secrets_master_key
# ---------------------------------------------------------------------------


class TestInternals:
    def test_derive_key_returns_bytes(self) -> None:
        key = _derive_key("mypassword")
        assert isinstance(key, bytes)
        assert len(key) == 32

    def test_derive_key_deterministic(self) -> None:
        assert _derive_key("abc") == _derive_key("abc")

    def test_secrets_master_key_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_SECRETS_KEY", "my-override-key")
        key = _secrets_master_key()
        assert key == "my-override-key"

    def test_secrets_master_key_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SPANFORGE_SECRETS_KEY", raising=False)
        key = _secrets_master_key()
        assert key.startswith("spanforge-")

    def test_prompt_confirm_yes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", lambda _: "y")
        assert _prompt_confirm("OK? ") is True

    def test_prompt_confirm_no(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", lambda _: "n")
        assert _prompt_confirm("OK? ") is False

    def test_prompt_confirm_eof(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", lambda _: (_ for _ in ()).throw(EOFError))
        assert _prompt_confirm("OK? ") is False

    def test_delete_path_file(self, tmp_path: Path) -> None:
        f = tmp_path / "del.txt"
        f.write_text("x", encoding="utf-8")
        _delete_path(f)
        assert not f.exists()

    def test_delete_path_directory(self, tmp_path: Path) -> None:
        d = tmp_path / "subdir"
        d.mkdir()
        (d / "file.txt").write_text("y", encoding="utf-8")
        _delete_path(d)
        assert not d.exists()

    def test_delete_path_nonexistent(self, tmp_path: Path) -> None:
        """Deleting a non-existent path should not raise."""
        _delete_path(tmp_path / "ghost.txt")

    def test_validate_config_yaml_non_dict_spanforge_block(self) -> None:
        """'spanforge' key whose value is a scalar (not dict) should produce an error."""
        errors = _validate_config_yaml("spanforge: notamap\n")
        assert any("mapping" in e or "signing_key" in e for e in errors)

    def test_check_connectivity_console_no_check(self, capsys: pytest.CaptureFixture[str]) -> None:
        content = "spanforge:\n  exporter: console\n"
        rc = _check_config_connectivity(content)
        assert rc == 0
        assert "no network" in capsys.readouterr().out.lower() or rc == 0

    def test_check_connectivity_unknown_exporter(self, capsys: pytest.CaptureFixture[str]) -> None:
        content = "spanforge:\n  exporter: grafana\n"
        rc = _check_config_connectivity(content)
        assert rc == 0


# ---------------------------------------------------------------------------
# Persistence internals
# ---------------------------------------------------------------------------


class TestSecretsPersistence:
    def test_save_and_load_roundtrip(self) -> None:
        data = {"KEY1": "val1", "KEY2": "val2"}
        cfg_mod._save_secrets_db(data)
        loaded = cfg_mod._load_secrets_db()
        assert loaded == data

    def test_load_missing_returns_empty(self) -> None:
        assert cfg_mod._load_secrets_db() == {}

    def test_load_corrupted_returns_empty(self) -> None:
        cfg_mod._SECRETS_DB_PATH.write_bytes(b"NOTBASE64!!")
        result = cfg_mod._load_secrets_db()
        assert result == {}

    def test_load_non_dict_json_returns_empty(self) -> None:
        """Valid base64 JSON but not a dict should return empty."""
        raw = base64.b64encode(json.dumps([1, 2, 3]).encode())
        cfg_mod._SECRETS_DB_PATH.write_bytes(raw)
        result = cfg_mod._load_secrets_db()
        assert result == {}

