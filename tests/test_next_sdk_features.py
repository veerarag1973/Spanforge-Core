"""Tests for NEXT_SDK_FEATURES.md — Features 2-10 implemented in this sprint.

Covers the five lowest-coverage / new modules:
  - spanforge.schemas            (Feature 8  — canonical schema key constants)
  - spanforge.sdk._factory       (Feature 3  — SFClientFactory)
  - spanforge.sdk._pipeline_builder (Feature 4 — SFPipeline)
  - spanforge.sdk.audit          (Feature 5  — SFCompositeAuditSink)
  - spanforge.sdk.cec            (Feature 10 — SFCECClient.export_local)

Also verifies Features 2, 6, 7, 9 (already tested indirectly; targeted here for
full branch coverage).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Feature 8 — Canonical schema key constants
# ---------------------------------------------------------------------------


class TestSchemaConstants:
    def test_all_expected_constants_present(self) -> None:
        from spanforge import schemas

        expected = [
            "TRACE_V1",
            "PII_V1",
            "SECRETS_V1",
            "AUDIT_V1",
            "CONSENT_V1",
            "SCORE_V1",
            "BIAS_V1",
            "PRRI_V1",
            "DRIFT_V1",
            "GATE_V1",
            "TRUST_V1",
            "ALERT_V1",
        ]
        for name in expected:
            assert hasattr(schemas, name), f"Missing constant: {name}"

    def test_constants_are_strings(self) -> None:
        from spanforge import schemas

        for name in schemas.__all__:
            val = getattr(schemas, name)
            assert isinstance(val, str), f"{name} should be str, got {type(val)}"

    def test_constants_are_non_empty(self) -> None:
        from spanforge import schemas

        for name in schemas.__all__:
            val = getattr(schemas, name)
            assert val, f"{name} should not be empty"

    def test_no_duplicates(self) -> None:
        from spanforge import schemas

        values = [getattr(schemas, n) for n in schemas.__all__]
        assert len(values) == len(set(values)), "Schema constants must be unique"

    def test_trace_v1_value(self) -> None:
        from spanforge.schemas import TRACE_V1

        assert "trace" in TRACE_V1.lower() or "span" in TRACE_V1.lower()

    def test_importable_from_spanforge_schemas(self) -> None:
        from spanforge.schemas import AUDIT_V1, GATE_V1, PII_V1, SCORE_V1

        # Just assert they all resolve to distinct strings
        assert len({AUDIT_V1, GATE_V1, PII_V1, SCORE_V1}) == 4


# ---------------------------------------------------------------------------
# Feature 3 — SFClientFactory
# ---------------------------------------------------------------------------


class TestSFClientFactory:
    def test_from_env_returns_factory(self) -> None:
        from spanforge.sdk import SFClientFactory

        f = SFClientFactory.from_env()
        assert isinstance(f, SFClientFactory)

    def test_explicit_config(self) -> None:
        from spanforge.sdk import SFClientFactory
        from spanforge.sdk._base import SFClientConfig

        cfg = SFClientConfig(endpoint="")
        f = SFClientFactory(cfg)
        assert f._config is cfg

    def test_pii_client_lazy(self) -> None:
        from spanforge.sdk import SFClientFactory

        f = SFClientFactory.from_env()
        assert f._pii is None
        client = f.pii
        # Second access returns the same instance (cached)
        assert f.pii is client

    def test_audit_client_lazy(self) -> None:
        from spanforge.sdk import SFClientFactory

        f = SFClientFactory.from_env()
        assert f._audit is None
        client = f.audit
        assert f.audit is client

    def test_secrets_client_lazy(self) -> None:
        from spanforge.sdk import SFClientFactory

        f = SFClientFactory.from_env()
        assert f._secrets is None
        client = f.secrets
        assert f.secrets is client

    def test_cec_client_lazy(self) -> None:
        from spanforge.sdk import SFClientFactory

        f = SFClientFactory.from_env()
        client = f.cec
        assert f.cec is client

    def test_gate_client_lazy(self) -> None:
        from spanforge.sdk import SFClientFactory

        f = SFClientFactory.from_env()
        client = f.gate
        assert f.gate is client

    def test_observe_client_lazy(self) -> None:
        from spanforge.sdk import SFClientFactory

        f = SFClientFactory.from_env()
        client = f.observe
        assert f.observe is client

    def test_alert_client_lazy(self) -> None:
        from spanforge.sdk import SFClientFactory

        f = SFClientFactory.from_env()
        client = f.alert
        assert f.alert is client

    def test_identity_client_lazy(self) -> None:
        from spanforge.sdk import SFClientFactory

        f = SFClientFactory.from_env()
        client = f.identity
        assert f.identity is client

    def test_all_clients_use_same_config(self) -> None:
        from spanforge.sdk import SFClientFactory
        from spanforge.sdk._base import SFClientConfig

        cfg = SFClientConfig(endpoint="https://example.com", project_id="proj-1")
        f = SFClientFactory(cfg)
        assert f.audit._config is cfg
        assert f.pii._config is cfg

    def test_exported_from_spanforge_sdk(self) -> None:
        from spanforge import sdk

        assert hasattr(sdk, "SFClientFactory")


# ---------------------------------------------------------------------------
# Feature 4 — SFPipeline builder
# ---------------------------------------------------------------------------


class TestSFPipeline:
    def test_empty_pipeline(self) -> None:
        from spanforge.sdk import SFPipeline

        result = SFPipeline().run({"x": 1})
        assert result.success is True
        assert result.stage_count == 0
        assert result.payload == {"x": 1}

    def test_single_stage_transforms_payload(self) -> None:
        from spanforge.sdk import SFPipeline

        result = SFPipeline().add_stage(lambda p: {**p, "y": 2}).run({"x": 1})
        assert result.success is True
        assert result.payload == {"x": 1, "y": 2}

    def test_multiple_stages_chain(self) -> None:
        from spanforge.sdk import SFPipeline

        p = (
            SFPipeline()
            .add_stage(lambda d: {**d, "a": 1}, name="stage-a")
            .add_stage(lambda d: {**d, "b": 2}, name="stage-b")
            .add_stage(lambda d: {**d, "c": 3}, name="stage-c")
        )
        result = p.run({})
        assert result.success is True
        assert result.payload == {"a": 1, "b": 2, "c": 3}
        assert result.stage_count == 3

    def test_stage_returning_none_passes_payload_through(self) -> None:
        from spanforge.sdk import SFPipeline

        called: list[bool] = []

        def side_effect(d: dict) -> None:
            called.append(True)  # side-effect only, returns None

        result = SFPipeline().add_stage(side_effect, name="noop").run({"x": 1})
        # Stage was called
        assert called
        # payload is the same object (passed through since stage returned None)
        assert result.payload == {"x": 1}

    def test_error_collected_when_fail_silent(self) -> None:
        from spanforge.sdk import SFPipeline

        def boom(_: Any) -> None:
            raise ValueError("intentional error")

        result = SFPipeline(fail_fast=False).add_stage(boom, name="bomb").run({})
        assert result.success is False
        assert "bomb" in result.errors
        assert "intentional error" in result.errors["bomb"]

    def test_fail_fast_raises_pipeline_stage_error(self) -> None:
        from spanforge.sdk import PipelineStageError, SFPipeline

        def boom(_: Any) -> None:
            raise RuntimeError("boom")

        with pytest.raises(PipelineStageError, match="boom"):
            SFPipeline(fail_fast=True).add_stage(boom, name="boomer").run({})

    def test_fail_fast_stops_execution(self) -> None:
        from spanforge.sdk import PipelineStageError, SFPipeline

        calls: list[str] = []

        def s1(d: Any) -> Any:
            calls.append("s1")
            raise RuntimeError("s1 fails")

        def s2(d: Any) -> Any:
            calls.append("s2")  # should NOT be called
            return d

        with pytest.raises(PipelineStageError):
            SFPipeline(fail_fast=True).add_stage(s1, name="s1").add_stage(s2, name="s2").run({})

        assert calls == ["s1"]

    def test_elapsed_ms_is_positive(self) -> None:

        from spanforge.sdk import SFPipeline

        result = SFPipeline().add_stage(lambda d: d).run({})
        assert result.elapsed_ms >= 0

    def test_outputs_list_length_matches_stage_count(self) -> None:
        from spanforge.sdk import SFPipeline

        p = SFPipeline().add_stage(lambda d: d).add_stage(lambda d: d)
        result = p.run({"z": 0})
        assert len(result.outputs) == 2

    def test_resolve_callable_picks_scan_method(self) -> None:
        from spanforge.sdk._pipeline_builder import SFPipeline

        class FakeClient:
            def scan(self, payload: Any) -> Any:
                return {**payload, "scanned": True}

        client = FakeClient()
        result = SFPipeline().add_stage(client, name="scanner").run({"x": 1})
        assert result.payload == {"x": 1, "scanned": True}

    def test_resolve_callable_raises_for_non_callable_obj(self) -> None:
        from spanforge.sdk._pipeline_builder import SFPipeline

        with pytest.raises(TypeError, match="not callable"):
            SFPipeline().add_stage(42, name="bad-stage")

    def test_pipeline_result_exported_from_sdk(self) -> None:
        from spanforge import sdk

        assert hasattr(sdk, "SFPipeline")
        assert hasattr(sdk, "SFPipelineResult")
        assert hasattr(sdk, "PipelineStageError")

    def test_method_chaining_returns_same_instance(self) -> None:
        from spanforge.sdk import SFPipeline

        p = SFPipeline()
        p2 = p.add_stage(lambda d: d, name="x")
        assert p2 is p


# ---------------------------------------------------------------------------
# Feature 5 — SFCompositeAuditSink
# ---------------------------------------------------------------------------


class TestSFCompositeAuditSink:
    def _make_sink(
        self, *, fail_silent: bool = True
    ):
        from spanforge.sdk._base import SFClientConfig
        from spanforge.sdk.audit import SFAuditClient, SFCompositeAuditSink
        from spanforge.signing import AuditStream

        cfg = SFClientConfig()
        client = SFAuditClient(cfg)
        stream = AuditStream(
            org_secret="test-secret-32chars-long-enough!!",
            source="test@1.0.0",
        )
        sink = SFCompositeAuditSink(stream, client, fail_silent=fail_silent)
        return sink, stream, client

    def test_append_returns_audit_result(self) -> None:
        from spanforge.sdk._types import AuditAppendResult

        sink, _, _ = self._make_sink()
        result = sink.append({"score": 0.9}, "halluccheck.score.v1")
        assert isinstance(result, AuditAppendResult)
        assert result.schema_key == "halluccheck.score.v1"

    def test_append_with_project_id(self) -> None:
        from spanforge.sdk._types import AuditAppendResult

        sink, _, _ = self._make_sink()
        result = sink.append({"k": "v"}, "halluccheck.score.v1", project_id="proj-x")
        assert isinstance(result, AuditAppendResult)

    def test_fail_silent_true_returns_local_result_on_error(self) -> None:
        from spanforge.sdk._base import SFClientConfig
        from spanforge.sdk._types import AuditAppendResult
        from spanforge.sdk.audit import SFAuditClient, SFCompositeAuditSink
        from spanforge.signing import AuditStream

        cfg = SFClientConfig()
        client = SFAuditClient(cfg)
        stream = AuditStream(
            org_secret="test-secret-32chars-long-enough!!",
            source="test@1.0.0",
        )
        # Patch the client's append to raise
        client.append = MagicMock(side_effect=RuntimeError("network down"))
        sink = SFCompositeAuditSink(stream, client, fail_silent=True)
        result = sink.append({"score": 0.5}, "halluccheck.score.v1")
        assert isinstance(result, AuditAppendResult)
        assert result.backend == "local"
        assert result.schema_key == "halluccheck.score.v1"

    def test_fail_silent_false_raises_on_error(self) -> None:
        from spanforge.sdk._base import SFClientConfig
        from spanforge.sdk.audit import SFAuditClient, SFCompositeAuditSink
        from spanforge.signing import AuditStream

        cfg = SFClientConfig()
        client = SFAuditClient(cfg)
        stream = AuditStream(
            org_secret="test-secret-32chars-long-enough!!",
            source="test@1.0.0",
        )
        client.append = MagicMock(side_effect=RuntimeError("explode"))
        sink = SFCompositeAuditSink(stream, client, fail_silent=False)
        with pytest.raises(RuntimeError, match="explode"):
            sink.append({"score": 0.5}, "halluccheck.score.v1")

    def test_exported_from_spanforge_sdk(self) -> None:
        from spanforge import sdk

        assert hasattr(sdk, "SFCompositeAuditSink")

    def test_sink_result_chain_position(self) -> None:
        from spanforge.sdk._types import AuditAppendResult

        sink, _, _ = self._make_sink()
        r1 = sink.append({"n": 1}, "halluccheck.score.v1")
        r2 = sink.append({"n": 2}, "halluccheck.score.v1")
        assert isinstance(r1, AuditAppendResult)
        assert isinstance(r2, AuditAppendResult)
        # chain positions should be sequential
        assert r2.chain_position > r1.chain_position


# ---------------------------------------------------------------------------
# Feature 10 — SFCECClient.export_local
# ---------------------------------------------------------------------------


class TestExportLocal:
    def test_export_local_creates_file(self) -> None:
        from spanforge.sdk._base import SFClientConfig
        from spanforge.sdk.cec import SFCECClient

        cfg = SFClientConfig()
        client = SFCECClient(cfg)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "evidence" / "bundle.ndjson"
            result = client.export_local(out)
            assert out.exists()
            assert result.backend == "local"
            assert result.exported_count >= 0
            assert result.failed_count == 0

    def test_export_local_ndjson_format(self) -> None:
        from spanforge.sdk._base import SFClientConfig
        from spanforge.sdk.cec import SFCECClient

        cfg = SFClientConfig()
        client = SFCECClient(cfg)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "bundle.ndjson"
            client.export_local(out)
            lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
            assert lines, "Output file should not be empty"
            # Every line must be valid JSON
            for line in lines:
                parsed = json.loads(line)
                assert isinstance(parsed, dict)

    def test_export_local_manifest_line(self) -> None:
        from spanforge.sdk._base import SFClientConfig
        from spanforge.sdk.cec import SFCECClient

        cfg = SFClientConfig()
        client = SFCECClient(cfg)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "bundle.ndjson"
            client.export_local(out)
            lines = [
                json.loads(ln)
                for ln in out.read_text(encoding="utf-8").splitlines()
                if ln.strip()
            ]
            # Last line should be the manifest
            manifest = lines[-1]
            assert manifest["schema"] == "spanforge.cec.local.v1"
            assert "hmac" in manifest
            assert manifest["hmac"].startswith("hmac-sha256:")
            assert "generated_at" in manifest
            assert "record_count" in manifest

    def test_export_local_returns_export_result(self) -> None:
        from spanforge.sdk._base import SFClientConfig
        from spanforge.sdk._types import ExportResult
        from spanforge.sdk.cec import SFCECClient

        cfg = SFClientConfig()
        client = SFCECClient(cfg)
        with tempfile.TemporaryDirectory() as tmp:
            result = client.export_local(Path(tmp) / "out.ndjson")
            assert isinstance(result, ExportResult)

    def test_export_local_accepts_str_path(self) -> None:
        from spanforge.sdk._base import SFClientConfig
        from spanforge.sdk.cec import SFCECClient

        cfg = SFClientConfig()
        client = SFCECClient(cfg)
        with tempfile.TemporaryDirectory() as tmp:
            out = str(Path(tmp) / "str_path.ndjson")
            result = client.export_local(out)
            assert result.backend == "local"

    def test_export_local_with_project_id(self) -> None:
        from spanforge.sdk._base import SFClientConfig
        from spanforge.sdk.cec import SFCECClient

        cfg = SFClientConfig()
        client = SFCECClient(cfg)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "proj.ndjson"
            result = client.export_local(out, project_id="my-project")
            assert result.backend == "local"
            lines = [
                json.loads(ln)
                for ln in out.read_text(encoding="utf-8").splitlines()
                if ln.strip()
            ]
            manifest = lines[-1]
            assert manifest["project_id"] == "my-project"

    def test_export_local_raises_on_unwritable_path(self) -> None:
        from spanforge.sdk._base import SFClientConfig
        from spanforge.sdk._exceptions import SFCECExportError
        from spanforge.sdk.cec import SFCECClient

        cfg = SFClientConfig()
        client = SFCECClient(cfg)
        # Use a path that cannot be created (file as parent dir)
        with tempfile.NamedTemporaryFile() as f:
            bad_path = Path(f.name) / "subdir" / "bundle.ndjson"
            with pytest.raises(SFCECExportError):
                client.export_local(bad_path)


# ---------------------------------------------------------------------------
# Feature 2 — PIIEntity.entity_type property alias
# ---------------------------------------------------------------------------


class TestPIIEntityAlias:
    def test_entity_type_matches_type(self) -> None:
        from spanforge.sdk._types import PIIEntity

        e = PIIEntity(type="EMAIL", start=0, end=16, score=0.99)
        assert e.entity_type == "EMAIL"
        assert e.entity_type == e.type

    def test_entity_type_on_phone(self) -> None:
        from spanforge.sdk._types import PIIEntity

        e = PIIEntity(type="PHONE_NUMBER", start=0, end=8, score=0.95)
        assert e.entity_type == "PHONE_NUMBER"


# ---------------------------------------------------------------------------
# Feature 6 — TSC-labelled exceptions
# ---------------------------------------------------------------------------


class TestTSCExceptions:
    def test_sf_error_default_tsc(self) -> None:
        from spanforge.sdk._exceptions import SFError

        err = SFError("base error")
        assert err.tsc_criterion == ""

    def test_sf_error_custom_tsc(self) -> None:
        from spanforge.sdk._exceptions import SFError

        err = SFError("oops", tsc_criterion="CC6.1")
        assert err.tsc_criterion == "CC6.1"

    def test_pii_blocked_error_tsc(self) -> None:
        from spanforge.sdk._exceptions import SFPIIBlockedError

        err = SFPIIBlockedError(["EMAIL", "PHONE"])
        assert err.tsc_criterion == "CC6.6"

    def test_secrets_blocked_error_tsc(self) -> None:
        from spanforge.sdk._exceptions import SFSecretsBlockedError

        err = SFSecretsBlockedError(["AWS_KEY"])
        assert err.tsc_criterion == "CC6.7"

    def test_gate_evaluation_error_tsc(self) -> None:
        from spanforge.sdk._exceptions import SFGateEvaluationError

        err = SFGateEvaluationError("gate failed")
        assert err.tsc_criterion == "CC7.2"

    def test_gate_trust_failed_error_tsc(self) -> None:
        from spanforge.sdk._exceptions import SFGateTrustFailedError

        err = SFGateTrustFailedError(["trust1"])
        assert err.tsc_criterion == "CC7.4"

    def test_custom_tsc_override(self) -> None:
        from spanforge.sdk._exceptions import SFPIIBlockedError

        err = SFPIIBlockedError(["EMAIL"], tsc_criterion="CC9.9")
        assert err.tsc_criterion == "CC9.9"


# ---------------------------------------------------------------------------
# Feature 7 — BehaviouralBaseline.fit()
# ---------------------------------------------------------------------------


def _make_baseline():
    from spanforge.baseline import BehaviouralBaseline, DistributionStats

    ds = DistributionStats(mean=100, stddev=10, p50=100, p95=120, p99=130, sample_count=3)
    return BehaviouralBaseline(tokens=ds)


class TestBehaviouralBaselineFit:
    def test_fit_from_dicts(self) -> None:
        baseline = _make_baseline()
        observations = [
            {"latency_ms": 100, "token_count": 50},
            {"latency_ms": 120, "token_count": 60},
            {"latency_ms": 110, "token_count": 55},
        ]
        before = baseline.event_count
        baseline.fit(observations)
        # fit() should update event_count
        assert baseline.event_count >= before

    def test_fit_accepts_generator(self) -> None:
        baseline = _make_baseline()

        def gen():
            for i in range(5):
                yield {"latency_ms": 100 + i * 10, "token_count": 50}

        baseline.fit(gen())
        assert baseline.event_count >= 5

    def test_fit_empty_observations(self) -> None:
        baseline = _make_baseline()
        before = baseline.event_count
        baseline.fit([])  # should not raise
        assert baseline.event_count == before

    def test_fit_custom_window(self) -> None:
        baseline = _make_baseline()
        baseline.fit([{"latency_ms": 200}], window_seconds=3600.0)
        assert baseline.window_seconds == 3600.0


# ---------------------------------------------------------------------------
# Feature 9 — spanforge.testing factory functions
# ---------------------------------------------------------------------------


class TestTestingFactories:
    def test_fake_pii_client(self) -> None:
        from spanforge.testing import fake_pii_client

        client = fake_pii_client()
        assert client is not None
        # Should be callable / have scan method
        assert callable(getattr(client, "scan", None))

    def test_fake_gate_client(self) -> None:
        from spanforge.testing import fake_gate_client

        client = fake_gate_client()
        assert client is not None

    def test_fake_secrets_client(self) -> None:
        from spanforge.testing import fake_secrets_client

        client = fake_secrets_client()
        assert client is not None

    def test_fake_audit_client(self) -> None:
        from spanforge.testing import fake_audit_client

        client = fake_audit_client()
        assert client is not None

    def test_fake_cec_client(self) -> None:
        from spanforge.testing import fake_cec_client

        client = fake_cec_client()
        assert client is not None

    def test_fake_observe_client(self) -> None:
        from spanforge.testing import fake_observe_client

        client = fake_observe_client()
        assert client is not None

    def test_fake_alert_client(self) -> None:
        from spanforge.testing import fake_alert_client

        client = fake_alert_client()
        assert client is not None

    def test_fake_identity_client(self) -> None:
        from spanforge.testing import fake_identity_client

        client = fake_identity_client()
        assert client is not None

    def test_all_factories_in_all(self) -> None:
        import spanforge.testing as t

        for name in [
            "fake_pii_client",
            "fake_gate_client",
            "fake_secrets_client",
            "fake_audit_client",
            "fake_cec_client",
            "fake_observe_client",
            "fake_alert_client",
            "fake_identity_client",
        ]:
            assert name in t.__all__, f"{name} not in __all__"
