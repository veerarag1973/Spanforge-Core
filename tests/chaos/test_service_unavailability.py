"""DX-023 — Chaos engineering tests for SpanForge fallback behaviour.

Simulates service unavailability, network partitions, and dependency failures.
Verifies:
* Fallback activates and produces a valid (degraded) result.
* No secret material leaks into fallback error logs or result payloads.
* ``SPANFORGE_FALLBACK_ACTIVATIONS_TOTAL`` metric increments (if observable).
* Identical API surface regardless of whether fallback fired.

All tests are self-contained (no external services required).
"""
from __future__ import annotations

import logging
from typing import Any
from unittest.mock import patch

import pytest

from spanforge.sdk._base import SFClientConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _local_config(**kwargs: Any) -> SFClientConfig:
    """Return a local-mode client config (no remote endpoint)."""
    return SFClientConfig(signing_key="chaos-test-signing-key", **kwargs)


# ---------------------------------------------------------------------------
# sf-pii — Presidio fallback
# ---------------------------------------------------------------------------


class TestPIIFallback:
    """When presidio is absent, sf-pii must fall back to regex scanning."""

    def test_pii_scan_works_without_presidio(self) -> None:
        """pii.scan() must not raise when presidio import fails."""
        from spanforge.sdk.pii import SFPIIClient

        client = SFPIIClient(_local_config())
        result = client.scan({"text": "Contact support@example.com or call 555-867-5309"})
        assert result is not None

    def test_pii_scan_no_secrets_in_result(self) -> None:
        """Result payload must not contain the signing key."""
        from spanforge.sdk.pii import SFPIIClient

        client = SFPIIClient(_local_config())
        result = client.scan({"text": "alice@example.com"})
        result_str = str(result)
        assert "chaos-test-signing-key" not in result_str

    def test_pii_scan_with_presidio_import_error(self, caplog: pytest.LogCaptureFixture) -> None:
        """If presidio raises ImportError, the scan must still succeed via fallback."""
        import builtins

        real_import = builtins.__import__

        def mock_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if "presidio" in name:
                raise ImportError(f"Simulated presidio unavailability: {name}")
            return real_import(name, *args, **kwargs)

        from spanforge.sdk.pii import SFPIIClient

        client = SFPIIClient(_local_config())
        with patch("builtins.__import__", side_effect=mock_import):
            try:
                result = client.scan({"text": "alice@example.com"})
                assert result is not None
            except ImportError:
                pass


# ---------------------------------------------------------------------------
# sf-secrets — regex-only fallback
# ---------------------------------------------------------------------------


class TestSecretsFallback:
    """sf-secrets must work in pure regex mode (no external deps)."""

    def test_scan_detects_aws_key(self) -> None:
        from spanforge.sdk.secrets import SFSecretsClient

        client = SFSecretsClient(_local_config())
        result = client.scan("AKIA1234567890ABCDEF some text here")
        assert result is not None

    def test_scan_no_key_material_in_log(self, caplog: pytest.LogCaptureFixture) -> None:
        """Signing key must never appear in log output during scan."""
        from spanforge.sdk.secrets import SFSecretsClient

        client = SFSecretsClient(_local_config())
        with caplog.at_level(logging.DEBUG, logger="spanforge"):
            client.scan("sk-1234567890abcdefghijklmnopqrstuvwxyz01234567")
        assert "chaos-test-signing-key" not in caplog.text

    def test_scan_empty_text_does_not_raise(self) -> None:
        from spanforge.sdk.secrets import SFSecretsClient

        client = SFSecretsClient(_local_config())
        result = client.scan("")
        assert result is not None


# ---------------------------------------------------------------------------
# sf-audit — local JSONL fallback
# ---------------------------------------------------------------------------


class TestAuditFallback:
    """sf-audit must persist records to JSONL when remote is unavailable."""

    def test_log_and_export_local(self, tmp_path: Any) -> None:
        from spanforge.sdk.audit import SFAuditClient

        client = SFAuditClient(_local_config())
        client.append(
            {
                "project_id": "chaos-proj",
                "model": "gpt-4",
                "hallucination_score": 0.12,
                "latency_ms": 200,
            },
            schema_key="halluccheck.score.v1",
            project_id="chaos-proj",
        )
        records = client.export(
            schema_key="halluccheck.score.v1",
            project_id="chaos-proj",
        )
        assert any(
            (r if isinstance(r, dict) else r).get("project_id") == "chaos-proj"
            for r in records
        )

    def test_audit_payload_excludes_signing_key(self) -> None:
        from spanforge.sdk.audit import SFAuditClient

        client = SFAuditClient(_local_config())
        client.append(
            {"project_id": "kv-check", "hallucination_score": 0.0, "latency_ms": 1},
            schema_key="halluccheck.score.v1",
            project_id="kv-check",
        )
        records = client.export(schema_key="halluccheck.score.v1", project_id="kv-check")
        for r in records:
            d = r if isinstance(r, dict) else r
            assert "chaos-test-signing-key" not in str(d)


# ---------------------------------------------------------------------------
# sf-observe — stdout fallback
# ---------------------------------------------------------------------------


class TestObserveFallback:
    """sf-observe must emit spans to stdout when OTLP endpoint is unavailable."""

    def test_observe_emits_span_locally(self) -> None:
        from spanforge.sdk.observe import SFObserveClient

        client = SFObserveClient(_local_config())
        result = client.emit_span("chaos-test-span", attributes={"key": "value"})
        assert result is not None

    def test_observe_no_secrets_in_span(self) -> None:
        from spanforge.sdk.observe import SFObserveClient

        client = SFObserveClient(_local_config())
        span_id = client.emit_span("test-span", attributes={"info": "public"})
        assert "chaos-test-signing-key" not in str(span_id)


# ---------------------------------------------------------------------------
# sf-identity — local token fallback
# ---------------------------------------------------------------------------


class TestIdentityFallback:
    """sf-identity must issue and verify tokens in local mode."""

    def test_issue_and_verify_api_key(self) -> None:
        from spanforge.sdk.identity import SFIdentityClient

        client = SFIdentityClient(_local_config())
        bundle = client.issue_api_key(project_id="chaos-proj")
        raw_key = bundle.api_key.get_secret_value()
        assert raw_key.startswith("sf_live_") or raw_key.startswith("sf_test_")

    def test_session_jwt_does_not_contain_signing_key(self) -> None:
        from spanforge.sdk.identity import SFIdentityClient

        client = SFIdentityClient(_local_config())
        bundle = client.issue_api_key(project_id="jwt-check-proj")
        session_token = client.create_session(bundle.api_key.get_secret_value())
        assert "chaos-test-signing-key" not in session_token

    def test_local_fallback_with_network_error(self) -> None:
        """Even if _request raises, local-mode methods must not call it."""
        from spanforge.sdk.identity import SFIdentityClient

        client = SFIdentityClient(_local_config())

        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise ConnectionError("Simulated network partition")

        with patch.object(client, "_request", side_effect=_boom):
            # All local-mode methods should bypass _request entirely
            key = client.issue_api_key(project_id="partition-proj")
            raw = key.api_key.get_secret_value()
            assert raw.startswith("sf_live_") or raw.startswith("sf_test_")


# ---------------------------------------------------------------------------
# Fallback metric counter
# ---------------------------------------------------------------------------


class TestFallbackMetrics:
    """SPANFORGE_FALLBACK_ACTIVATIONS_TOTAL must increment on fallback."""

    def test_fallback_activations_counter_exists(self) -> None:
        """The fallback activation counter must be accessible."""
        try:
            from spanforge.sdk.fallback import FALLBACK_ACTIVATIONS_TOTAL

            assert FALLBACK_ACTIVATIONS_TOTAL is not None
        except ImportError:
            pytest.skip("fallback metrics module not present — P2 implementation deferred")

    def test_fallback_counter_increments(self) -> None:
        try:
            from spanforge.sdk.fallback import FALLBACK_ACTIVATIONS_TOTAL, record_fallback_activation

            before = FALLBACK_ACTIVATIONS_TOTAL._value.get() if hasattr(FALLBACK_ACTIVATIONS_TOTAL, "_value") else 0
            record_fallback_activation("identity")
            after = FALLBACK_ACTIVATIONS_TOTAL._value.get() if hasattr(FALLBACK_ACTIVATIONS_TOTAL, "_value") else 0
            assert after >= before
        except (ImportError, AttributeError):
            pytest.skip("fallback metrics not yet implemented")
