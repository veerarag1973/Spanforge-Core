"""Tests for spanforge.config — SpanForgeConfig, configure(), get_config(), env vars.

Phase 1 SDK coverage target.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

import pytest

from spanforge.config import SpanForgeConfig, configure, get_config

if TYPE_CHECKING:
    from collections.abc import Generator

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _restore_config() -> Generator[None, None, None]:
    """Restore the global config after every test."""
    cfg = get_config()
    saved = {k: getattr(cfg, k) for k in vars(cfg)}
    yield
    for k, v in saved.items():
        setattr(cfg, k, v)


# ===========================================================================
# SpanForgeConfig defaults
# ===========================================================================


@pytest.mark.unit
class TestSpanForgeConfigDefaults:
    def test_default_exporter(self) -> None:
        cfg = SpanForgeConfig()
        assert cfg.exporter == "console"

    def test_default_endpoint_is_none(self) -> None:
        cfg = SpanForgeConfig()
        assert cfg.endpoint is None

    def test_default_org_id_is_none(self) -> None:
        cfg = SpanForgeConfig()
        assert cfg.org_id is None

    def test_default_service_name(self) -> None:
        cfg = SpanForgeConfig()
        assert cfg.service_name == "unknown-service"

    def test_default_env(self) -> None:
        cfg = SpanForgeConfig()
        assert cfg.env == "production"

    def test_default_service_version(self) -> None:
        cfg = SpanForgeConfig()
        assert cfg.service_version == "0.0.0"

    def test_default_signing_key_is_none(self) -> None:
        cfg = SpanForgeConfig()
        assert cfg.signing_key is None

    def test_default_redaction_policy_is_none(self) -> None:
        cfg = SpanForgeConfig()
        assert cfg.redaction_policy is None

    def test_custom_construction(self) -> None:
        cfg = SpanForgeConfig(
            exporter="jsonl",
            endpoint="./events.jsonl",
            service_name="my-agent",
            env="staging",
        )
        assert cfg.exporter == "jsonl"
        assert cfg.endpoint == "./events.jsonl"
        assert cfg.service_name == "my-agent"
        assert cfg.env == "staging"


# ===========================================================================
# configure() function
# ===========================================================================


@pytest.mark.unit
class TestConfigureFunction:
    def test_configure_no_args_is_noop(self) -> None:
        before = get_config().service_name
        configure()
        assert get_config().service_name == before

    def test_configure_sets_exporter(self) -> None:
        configure(exporter="jsonl")
        assert get_config().exporter == "jsonl"

    def test_configure_sets_service_name(self) -> None:
        configure(service_name="test-service")
        assert get_config().service_name == "test-service"

    def test_configure_sets_endpoint(self) -> None:
        configure(endpoint="./test.jsonl")
        assert get_config().endpoint == "./test.jsonl"

    def test_configure_sets_org_id(self) -> None:
        configure(org_id="org_abc123")
        assert get_config().org_id == "org_abc123"

    def test_configure_sets_env(self) -> None:
        configure(env="staging")
        assert get_config().env == "staging"

    def test_configure_sets_service_version(self) -> None:
        configure(service_version="1.2.3")
        assert get_config().service_version == "1.2.3"

    def test_configure_sets_signing_key(self) -> None:
        configure(signing_key="abc123==")
        assert get_config().signing_key == "abc123=="

    def test_configure_multiple_fields(self) -> None:
        configure(exporter="console", service_name="foo", env="dev")
        cfg = get_config()
        assert cfg.exporter == "console"
        assert cfg.service_name == "foo"
        assert cfg.env == "dev"

    def test_configure_unknown_key_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown spanforge configuration key"):
            configure(unknown_key="value")

    def test_configure_multiple_calls_accumulate(self) -> None:
        configure(exporter="jsonl")
        configure(service_name="chained")
        cfg = get_config()
        assert cfg.exporter == "jsonl"
        assert cfg.service_name == "chained"

    def test_configure_resets_exporter_cache(self) -> None:
        """configure() should invalidate the _stream exporter cache."""
        configure(exporter="console")
        # Calling configure again should not raise.
        configure(exporter="console")
        assert get_config().exporter == "console"


# ===========================================================================
# get_config() returns live singleton
# ===========================================================================


@pytest.mark.unit
class TestGetConfig:
    def test_returns_same_instance(self) -> None:
        cfg1 = get_config()
        cfg2 = get_config()
        assert cfg1 is cfg2

    def test_mutation_reflected_immediately(self) -> None:
        cfg = get_config()
        cfg.service_name = "direct-mutation"
        assert get_config().service_name == "direct-mutation"


# ===========================================================================
# Environment variable loading
# ===========================================================================


@pytest.mark.unit
class TestEnvVars:
    def test_spanforge_exporter_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_EXPORTER", "jsonl")
        # Force re-import by directly calling _load_from_env
        import spanforge.config as config_mod  # noqa: PLC0415
        old = config_mod._config.exporter
        config_mod._load_from_env()
        assert config_mod._config.exporter == "jsonl"
        # Restore
        config_mod._config.exporter = old

    def test_spanforge_service_name_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_SERVICE_NAME", "env-service")
        import spanforge.config as config_mod  # noqa: PLC0415
        old = config_mod._config.service_name
        config_mod._load_from_env()
        assert config_mod._config.service_name == "env-service"
        config_mod._config.service_name = old

    def test_spanforge_endpoint_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_ENDPOINT", "http://localhost:4317")  # NOSONAR
        import spanforge.config as config_mod  # noqa: PLC0415
        old = config_mod._config.endpoint
        config_mod._load_from_env()
        assert config_mod._config.endpoint == "http://localhost:4317"  # NOSONAR
        config_mod._config.endpoint = old

    def test_spanforge_org_id_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_ORG_ID", "org_test")
        import spanforge.config as config_mod  # noqa: PLC0415
        old = config_mod._config.org_id
        config_mod._load_from_env()
        assert config_mod._config.org_id == "org_test"
        config_mod._config.org_id = old

    def test_spanforge_env_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_ENV", "development")
        import spanforge.config as config_mod  # noqa: PLC0415
        old = config_mod._config.env
        config_mod._load_from_env()
        assert config_mod._config.env == "development"
        config_mod._config.env = old

    def test_spanforge_service_version_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_SERVICE_VERSION", "2.0.0")
        import spanforge.config as config_mod  # noqa: PLC0415
        old = config_mod._config.service_version
        config_mod._load_from_env()
        assert config_mod._config.service_version == "2.0.0"
        config_mod._config.service_version = old

    def test_spanforge_signing_key_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_SIGNING_KEY", "test_key==")
        import spanforge.config as config_mod  # noqa: PLC0415
        old = config_mod._config.signing_key
        config_mod._load_from_env()
        assert config_mod._config.signing_key == "test_key=="
        config_mod._config.signing_key = old

    def test_unset_env_vars_do_not_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SPANFORGE_SERVICE_NAME", raising=False)
        import spanforge.config as config_mod  # noqa: PLC0415
        config_mod._config.service_name = "my-service"
        config_mod._load_from_env()
        assert config_mod._config.service_name == "my-service"


# ===========================================================================
# Thread safety
# ===========================================================================


@pytest.mark.unit
class TestConfigureThreadSafety:
    def test_concurrent_configure_does_not_raise(self) -> None:
        errors = []

        def worker(n: int) -> None:
            try:
                configure(service_name=f"worker-{n}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        # config should have a valid service_name (one of the workers' values)
        assert get_config().service_name.startswith("worker-")


# ===========================================================================
# GA env vars
# ===========================================================================


@pytest.mark.unit
class TestGAEnvVars:
    def test_signing_key_context_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_SIGNING_KEY_CONTEXT", "production")
        import spanforge.config as config_mod  # noqa: PLC0415
        old = config_mod._config.signing_key_context
        config_mod._load_from_env()
        assert config_mod._config.signing_key_context == "production"
        config_mod._config.signing_key_context = old

    def test_signing_key_context_empty_becomes_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_SIGNING_KEY_CONTEXT", "   ")
        import spanforge.config as config_mod  # noqa: PLC0415
        old = config_mod._config.signing_key_context
        config_mod._load_from_env()
        assert config_mod._config.signing_key_context is None
        config_mod._config.signing_key_context = old

    def test_no_egress_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_NO_EGRESS", "true")
        import spanforge.config as config_mod  # noqa: PLC0415
        old = config_mod._config.no_egress
        config_mod._load_from_env()
        assert config_mod._config.no_egress is True
        config_mod._config.no_egress = old

    def test_egress_allowlist_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_EGRESS_ALLOWLIST", "https://a.com, https://b.com")
        import spanforge.config as config_mod  # noqa: PLC0415
        old = config_mod._config.egress_allowlist
        config_mod._load_from_env()
        assert "https://a.com" in config_mod._config.egress_allowlist
        assert "https://b.com" in config_mod._config.egress_allowlist
        config_mod._config.egress_allowlist = old

    def test_compliance_sampling_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_COMPLIANCE_SAMPLING", "true")
        import spanforge.config as config_mod  # noqa: PLC0415
        old = config_mod._config.compliance_sampling
        config_mod._load_from_env()
        assert config_mod._config.compliance_sampling is True
        config_mod._config.compliance_sampling = old

    def test_signing_key_expires_at_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_SIGNING_KEY_EXPIRES_AT", "2030-01-01T00:00:00Z")
        import spanforge.config as config_mod  # noqa: PLC0415
        old = config_mod._config.signing_key_expires_at
        config_mod._load_from_env()
        assert config_mod._config.signing_key_expires_at == "2030-01-01T00:00:00Z"
        config_mod._config.signing_key_expires_at = old

    def test_require_org_id_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_REQUIRE_ORG_ID", "1")
        import spanforge.config as config_mod  # noqa: PLC0415
        old = config_mod._config.require_org_id
        config_mod._load_from_env()
        assert config_mod._config.require_org_id is True
        config_mod._config.require_org_id = old

    def test_enable_trace_store_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_ENABLE_TRACE_STORE", "yes")
        import spanforge.config as config_mod  # noqa: PLC0415
        old = config_mod._config.enable_trace_store
        config_mod._load_from_env()
        assert config_mod._config.enable_trace_store is True
        config_mod._config.enable_trace_store = old

    def test_allow_private_endpoints_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_ALLOW_PRIVATE_ENDPOINTS", "true")
        import spanforge.config as config_mod  # noqa: PLC0415
        old = config_mod._config.allow_private_endpoints
        config_mod._load_from_env()
        assert config_mod._config.allow_private_endpoints is True
        config_mod._config.allow_private_endpoints = old


# ===========================================================================
# configure() — signing key validation (GA-01-A)
# ===========================================================================


@pytest.mark.unit
class TestConfigureSigningKeyValidation:
    def test_configure_with_weak_key_logs_warnings(self, caplog) -> None:
        """When a weak signing key is set, warnings should be logged."""
        import logging
        with caplog.at_level(logging.WARNING, logger="spanforge.config"):
            configure(signing_key="short")
        assert any("signing key" in r.message.lower() for r in caplog.records)
        # Clean up
        configure(signing_key=None)

    def test_configure_with_strong_key_no_warnings(self, caplog) -> None:
        import logging
        with caplog.at_level(logging.WARNING, logger="spanforge.config"):
            configure(signing_key="Super-Strong!Key-With-Mixed-Classes-1234")
        signing_warnings = [r for r in caplog.records if "signing key" in r.message.lower()]
        assert len(signing_warnings) == 0
        configure(signing_key=None)
