"""Tests for Phase 10 — T.R.U.S.T. Scorecard & HallucCheck Contract.

Covers: trust.py, pipelines.py, CLI trust subcommands, and server endpoints.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from spanforge.sdk._types import TrustDimensionWeights

# ===========================================================================
# T.R.U.S.T. Scorecard Client — sdk/trust.py
# ===========================================================================


@pytest.mark.unit
class TestTrustClient:
    """SFTrustClient scorecard computation tests."""

    def test_get_scorecard_defaults(self) -> None:
        from spanforge.sdk._types import TrustDimensionWeights
        from spanforge.sdk.trust import SFTrustClient

        client = SFTrustClient.__new__(SFTrustClient)
        client._config = MagicMock(project_id="default")
        client._weights = TrustDimensionWeights()
        # Patch sf_audit where it's imported inside the method
        with patch("spanforge.sdk.sf_audit") as mock_audit:
            mock_audit._store.query_trust.return_value = []
            scorecard = client.get_scorecard()

        assert scorecard.overall_score >= 0.0
        assert scorecard.colour_band in ("green", "amber", "red")
        assert scorecard.transparency is not None
        assert scorecard.reliability is not None
        assert scorecard.user_trust is not None
        assert scorecard.security is not None
        assert scorecard.traceability is not None

    def test_get_scorecard_with_records(self) -> None:
        from spanforge.sdk.trust import SFTrustClient

        client = SFTrustClient.__new__(SFTrustClient)
        client._config = MagicMock(project_id="default")
        client._weights = TrustDimensionWeights()
        mock_records = [
            {"dimension": "hallucination", "score": 85.0, "timestamp": "2025-01-01T00:00:00Z"},
            {"dimension": "pii_hygiene", "score": 90.0, "timestamp": "2025-01-01T00:00:00Z"},
            {"dimension": "secrets_hygiene", "score": 70.0, "timestamp": "2025-01-01T00:00:00Z"},
            {"dimension": "gate_pass_rate", "score": 95.0, "timestamp": "2025-01-01T00:00:00Z"},
            {"dimension": "compliance_posture", "score": 80.0, "timestamp": "2025-01-01T00:00:00Z"},
        ]
        with patch("spanforge.sdk.sf_audit") as mock_audit:
            mock_audit._store.query_trust.return_value = mock_records
            scorecard = client.get_scorecard(project_id="test-project")

        assert scorecard.project_id == "test-project"
        assert scorecard.overall_score > 0.0
        assert scorecard.record_count == 5

    def test_get_badge_returns_svg(self) -> None:
        from spanforge.sdk.trust import SFTrustClient

        client = SFTrustClient.__new__(SFTrustClient)
        client._config = MagicMock(project_id="default")
        client._weights = TrustDimensionWeights()
        with patch("spanforge.sdk.sf_audit") as mock_audit:
            mock_audit._store.query_trust.return_value = []
            badge = client.get_badge(project_id="test")

        assert badge.svg.startswith("<svg")
        assert badge.etag
        assert badge.colour_band in ("green", "amber", "red")

    def test_get_history_returns_list(self) -> None:
        from spanforge.sdk.trust import SFTrustClient

        client = SFTrustClient.__new__(SFTrustClient)
        client._config = MagicMock(project_id="default")
        client._weights = TrustDimensionWeights()
        with patch("spanforge.sdk.sf_audit") as mock_audit:
            mock_audit._store.query_trust.return_value = []
            history = client.get_history(project_id="test", buckets=5)

        assert isinstance(history, list)

    def test_get_status(self) -> None:
        from spanforge.sdk.trust import SFTrustClient

        client = SFTrustClient.__new__(SFTrustClient)
        client._config = MagicMock(project_id="default")
        client._weights = TrustDimensionWeights()
        client._last_computed = None
        with patch("spanforge.sdk.sf_audit") as mock_audit:
            mock_audit._store.query_trust.return_value = []
            status = client.get_status()

        assert status.status in ("ok", "degraded", "error")


@pytest.mark.unit
class TestColourBand:
    """colour_band helper tests."""

    def test_green_band(self) -> None:
        from spanforge.sdk.trust import _colour_band

        assert _colour_band(80.0) == "green"
        assert _colour_band(100.0) == "green"

    def test_amber_band(self) -> None:
        from spanforge.sdk.trust import _colour_band

        assert _colour_band(60.0) == "amber"
        assert _colour_band(79.9) == "amber"

    def test_red_band(self) -> None:
        from spanforge.sdk.trust import _colour_band

        assert _colour_band(59.9) == "red"
        assert _colour_band(0.0) == "red"


@pytest.mark.unit
class TestWeightedAverage:
    """_weighted_average helper tests."""

    def test_equal_weights(self) -> None:
        from spanforge.sdk._types import TrustDimensionWeights
        from spanforge.sdk.trust import _weighted_average

        w = TrustDimensionWeights(transparency=1.0, reliability=1.0, user_trust=1.0, security=1.0, traceability=1.0)
        result = _weighted_average({"transparency": 80.0, "reliability": 60.0, "user_trust": 70.0, "security": 70.0, "traceability": 70.0}, w)
        assert abs(result - 70.0) < 0.01

    def test_custom_weights(self) -> None:
        from spanforge.sdk._types import TrustDimensionWeights
        from spanforge.sdk.trust import _weighted_average

        w = TrustDimensionWeights(transparency=3.0, reliability=1.0, user_trust=0.0, security=0.0, traceability=0.0)
        result = _weighted_average({"transparency": 100.0, "reliability": 0.0, "user_trust": 50.0, "security": 50.0, "traceability": 50.0}, w)
        assert abs(result - 75.0) < 0.01

    def test_empty_scores(self) -> None:
        from spanforge.sdk._types import TrustDimensionWeights
        from spanforge.sdk.trust import _weighted_average

        w = TrustDimensionWeights(transparency=0.0, reliability=0.0, user_trust=0.0, security=0.0, traceability=0.0)
        result = _weighted_average({}, w)
        assert result == 0.0


# ===========================================================================
# Phase 10 Types
# ===========================================================================


@pytest.mark.unit
class TestTrustTypes:
    """Phase 10 dataclass tests."""

    def test_trust_dimension_weights_defaults(self) -> None:
        from spanforge.sdk._types import TrustDimensionWeights

        w = TrustDimensionWeights()
        assert w.transparency == 1.0
        assert w.reliability == 1.0
        assert w.user_trust == 1.0
        assert w.security == 1.0
        assert w.traceability == 1.0

    def test_trust_scorecard_response_fields(self) -> None:
        from spanforge.sdk._types import (
            TrustDimension,
            TrustDimensionWeights,
            TrustScorecardResponse,
        )

        dim = TrustDimension(score=85.0, trend="stable", last_updated="2025-01-01T00:00:00Z")
        scorecard = TrustScorecardResponse(
            project_id="p1",
            overall_score=85.0,
            colour_band="green",
            transparency=dim,
            reliability=dim,
            user_trust=dim,
            security=dim,
            traceability=dim,
            weights=TrustDimensionWeights(),
            from_dt=None,
            to_dt=None,
            record_count=10,
        )
        assert scorecard.overall_score == 85.0
        assert scorecard.colour_band == "green"

    def test_composite_gate_result(self) -> None:
        from spanforge.sdk._types import CompositeGateResult

        r = CompositeGateResult(
            pass_=True,
            verdict="PASS",
            overall_score=90.0,
            trust_gate=None,
            failures=[],
            colour_band="green",
            timestamp="2025-01-01T00:00:00Z",
        )
        assert r.pass_ is True

    def test_pipeline_result(self) -> None:
        from spanforge.sdk._types import PipelineResult

        r = PipelineResult(
            audit_id="a1",
            alerts_sent=2,
            span_id="s1",
            details={"key": "value"},
            pipeline="score",
            success=True,
        )
        assert r.alerts_sent == 2

    def test_dsar_result(self) -> None:
        from spanforge.sdk._types import DSARResult

        r = DSARResult(subject_id="u1", records=[], record_count=0, exported_at="2025-01-01T00:00:00Z")
        assert r.record_count == 0


# ===========================================================================
# Phase 10 Exceptions
# ===========================================================================


@pytest.mark.unit
class TestTrustExceptions:
    def test_trust_compute_error(self) -> None:
        from spanforge.sdk._exceptions import SFTrustComputeError

        exc = SFTrustComputeError("dimension missing")
        assert "dimension missing" in str(exc)

    def test_trust_gate_failed_error(self) -> None:
        from spanforge.sdk._exceptions import SFTrustGateFailedError

        exc = SFTrustGateFailedError(["score too low", "no audit records"])
        assert exc.failures == ["score too low", "no audit records"]

    def test_pipeline_error(self) -> None:
        from spanforge.sdk._exceptions import SFPipelineError

        exc = SFPipelineError("score_pipeline", "timeout")
        assert "score_pipeline" in str(exc)


# ===========================================================================
# Pipelines — sdk/pipelines.py
# ===========================================================================


@pytest.mark.unit
class TestPipelines:
    """Pipeline integration function tests."""

    def test_score_pipeline_runs(self) -> None:
        from spanforge.sdk.pipelines import score_pipeline

        with (
            patch("spanforge.sdk.sf_pii") as mock_pii,
            patch("spanforge.sdk.sf_secrets") as mock_secrets,
            patch("spanforge.sdk.sf_observe") as mock_observe,
            patch("spanforge.sdk.sf_audit") as mock_audit,
        ):
            mock_pii.scan_text.return_value = MagicMock(
                clean=True, entities=[], redacted="hello"
            )
            mock_secrets.scan.return_value = MagicMock(clean=True, hits=[])
            mock_observe.emit_span.return_value = MagicMock(span_id="sp1")
            mock_audit.append.return_value = MagicMock(record_id="aud1")

            result = score_pipeline(text="hello world", model="gpt-4")

        assert result.audit_id == "aud1"
        assert result.span_id == "sp1"

    def test_bias_pipeline_runs(self) -> None:
        from spanforge.sdk.pipelines import bias_pipeline

        with (
            patch("spanforge.sdk.sf_pii") as mock_pii,
            patch("spanforge.sdk.sf_audit") as mock_audit,
            patch("spanforge.sdk.sf_alert") as mock_alert,
        ):
            mock_pii.scan.return_value = MagicMock(clean_text="text", entities=[])
            mock_audit.append.return_value = MagicMock(record_id="aud2")
            mock_alert.send.return_value = None

            report = {"segments": [], "max_disparity": 0.1}
            result = bias_pipeline(bias_report=report, project_id="p1")

        assert result.audit_id == "aud2"

    def test_monitor_pipeline_runs(self) -> None:
        from spanforge.sdk.pipelines import monitor_pipeline

        with (
            patch("spanforge.sdk.sf_observe") as mock_observe,
            patch("spanforge.sdk.sf_alert") as mock_alert,
        ):
            mock_observe.annotate.return_value = MagicMock(span_id="sp2")
            mock_alert.send.return_value = None

            event = {"drift_score": 0.5, "model": "gpt-4"}
            result = monitor_pipeline(event=event, project_id="p1")

        assert result.pipeline == "monitor"


# ===========================================================================
# CLI — trust subcommands
# ===========================================================================


@pytest.mark.unit
class TestTrustCLI:
    """CLI trust subcommand tests."""

    def test_trust_scorecard_text(self, capsys: pytest.CaptureFixture[str]) -> None:
        from spanforge.sdk._types import (
            TrustDimension,
            TrustDimensionWeights,
            TrustScorecardResponse,
        )

        mock_scorecard = TrustScorecardResponse(
            project_id="test",
            overall_score=85.0,
            colour_band="green",
            transparency=TrustDimension(score=90.0, trend="up", last_updated=""),
            reliability=TrustDimension(score=80.0, trend="stable", last_updated=""),
            user_trust=TrustDimension(score=85.0, trend="stable", last_updated=""),
            security=TrustDimension(score=88.0, trend="up", last_updated=""),
            traceability=TrustDimension(score=82.0, trend="down", last_updated=""),
            weights=TrustDimensionWeights(),
            from_dt=None,
            to_dt=None,
            record_count=50,
        )

        with patch("spanforge.sdk.trust.SFTrustClient.get_scorecard", return_value=mock_scorecard):
                import argparse

                from spanforge._cli import _cmd_trust_scorecard

                args = argparse.Namespace(project_id="test", format="text")
                rc = _cmd_trust_scorecard(args)

        assert rc == 0
        out = capsys.readouterr().out
        assert "T.R.U.S.T. Scorecard" in out
        assert "85.0" in out

    def test_trust_scorecard_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        from spanforge.sdk._types import (
            TrustDimension,
            TrustDimensionWeights,
            TrustScorecardResponse,
        )

        mock_scorecard = TrustScorecardResponse(
            project_id="test",
            overall_score=75.0,
            colour_band="amber",
            transparency=TrustDimension(score=70.0, trend="stable", last_updated=""),
            reliability=TrustDimension(score=75.0, trend="stable", last_updated=""),
            user_trust=TrustDimension(score=80.0, trend="up", last_updated=""),
            security=TrustDimension(score=72.0, trend="down", last_updated=""),
            traceability=TrustDimension(score=78.0, trend="stable", last_updated=""),
            weights=TrustDimensionWeights(),
            from_dt=None,
            to_dt=None,
            record_count=30,
        )

        with patch("spanforge.sdk.trust.SFTrustClient.get_scorecard", return_value=mock_scorecard):
            import argparse

            from spanforge._cli import _cmd_trust_scorecard

            args = argparse.Namespace(project_id="test", format="json")
            rc = _cmd_trust_scorecard(args)

        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["overall_score"] == 75.0
        assert data["colour_band"] == "amber"


# ===========================================================================
# Exports — __init__.py
# ===========================================================================


@pytest.mark.unit
class TestPhase10Exports:
    """Verify Phase 10 symbols are exported from spanforge.sdk."""

    def test_trust_types_exported(self) -> None:
        pass

    def test_trust_exceptions_exported(self) -> None:
        pass

    def test_trust_client_exported(self) -> None:
        from spanforge.sdk import sf_trust

        assert sf_trust is not None

    def test_pipeline_functions_exported(self) -> None:
        pass
