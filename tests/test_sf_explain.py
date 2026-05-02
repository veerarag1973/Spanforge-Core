"""Tests for spanforge.sdk.explain - Phase 1 sf-explain client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spanforge.namespaces.runtime_governance import ExplanationFactor
from spanforge.sdk._base import SFClientConfig
from spanforge.sdk.explain import ExplainModelType, ExplainStatusInfo, SFExplainClient


def _make_client() -> SFExplainClient:
    return SFExplainClient(SFClientConfig(project_id="test-proj"))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class TestSFExplainClient:
    def test_generate_returns_payload_and_records_it(self) -> None:
        client = _make_client()

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = client.generate(
                trace_id="trace-001",
                agent_id="agent-001",
                decision_id="decision-001",
                summary="The request passed the reliability policy.",
                policy_action="allow+log",
                generated_at="2026-04-22T10:00:00Z",
                factors=[
                    ExplanationFactor(
                        factor_name="grounding_score",
                        weight=0.7,
                        contribution=0.5,
                        evidence="retrieved evidence exceeded threshold",
                    )
                ],
                policy_id="policy-ga-v1",
            )

        assert payload.trace_id == "trace-001"
        assert client.get(payload.explanation_id) == payload
        assert client.list_for_trace("trace-001") == [payload]

    def test_generate_accepts_dict_factors(self) -> None:
        client = _make_client()
        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = client.generate(
                trace_id="trace-001",
                agent_id="agent-001",
                decision_id="decision-001",
                summary="The request passed the reliability policy.",
                policy_action="allow",
                generated_at="2026-04-22T10:00:00Z",
                factors=[
                    {
                        "factor_name": "policy_rule",
                        "weight": 1.0,
                        "contribution": 1.0,
                        "evidence": "rule sf_rag.grounding_threshold allowed the request",
                    }
                ],
            )
        assert payload.factors[0].factor_name == "policy_rule"

    def test_get_unknown_returns_none(self) -> None:
        client = _make_client()
        assert client.get("missing") is None

    def test_status_reflects_generated_count(self) -> None:
        client = _make_client()
        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            client.generate(
                trace_id="trace-001",
                agent_id="agent-001",
                decision_id="decision-001",
                summary="The request passed.",
                policy_action="allow",
                generated_at="2026-04-22T10:00:00Z",
            )
        status = client.get_status()
        assert isinstance(status, ExplainStatusInfo)
        assert status.total_generated == 1
        assert status.traces_tracked == 1

    def test_generate_writes_to_sf_audit(self) -> None:
        client = _make_client()
        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = client.generate(
                trace_id="trace-001",
                agent_id="agent-001",
                decision_id="decision-001",
                summary="The request passed.",
                policy_action="allow",
                generated_at="2026-04-22T10:00:00Z",
            )
        mock_audit_module.append.assert_called_once_with(
            payload.to_dict(),
            "spanforge.explanation.v1",
        )

    @pytest.mark.anyio
    async def test_generate_async(self) -> None:
        client = _make_client()
        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = await client.generate_async(
                trace_id="trace-001",
                agent_id="agent-001",
                decision_id="decision-001",
                summary="The request passed.",
                policy_action="allow",
                generated_at="2026-04-22T10:00:00Z",
            )
        assert payload.agent_id == "agent-001"


# ---------------------------------------------------------------------------
# 1B-1: model type tests
# ---------------------------------------------------------------------------


def _gen(client: SFExplainClient, **kwargs: object) -> object:
    """Helper: generate with a patched audit append."""
    with patch("spanforge.sdk.sf_audit") as m:
        m.append = MagicMock()
        return client.generate(
            trace_id="trace-mt",
            agent_id="agent-mt",
            decision_id="decision-mt",
            summary="test",
            policy_action="allow",
            generated_at="2026-04-22T10:00:00Z",
            **kwargs,  # type: ignore[arg-type]
        )


class TestExplainModelTypes:
    """1B-1 — five model-type classification paths."""

    def test_llm_model_type_stored_in_metadata(self) -> None:
        client = _make_client()
        payload = _gen(client, model_type=ExplainModelType.LLM)
        assert payload.metadata.get("model_type") == "llm"

    def test_rag_model_type_stored_in_metadata(self) -> None:
        client = _make_client()
        payload = _gen(client, model_type=ExplainModelType.RAG)
        assert payload.metadata.get("model_type") == "rag"

    def test_multi_agent_model_type_stored_in_metadata(self) -> None:
        client = _make_client()
        payload = _gen(client, model_type=ExplainModelType.MULTI_AGENT)
        assert payload.metadata.get("model_type") == "multi_agent"

    def test_classifier_model_type_stored_in_metadata(self) -> None:
        client = _make_client()
        payload = _gen(client, model_type=ExplainModelType.CLASSIFIER)
        assert payload.metadata.get("model_type") == "classifier"

    def test_embedding_model_type_stored_in_metadata(self) -> None:
        client = _make_client()
        payload = _gen(client, model_type=ExplainModelType.EMBEDDING)
        assert payload.metadata.get("model_type") == "embedding"

    def test_raw_string_model_type_accepted(self) -> None:
        """Raw strings (e.g. from config) are stored as-is."""
        client = _make_client()
        payload = _gen(client, model_type="custom_model")
        assert payload.metadata.get("model_type") == "custom_model"

    def test_no_model_type_leaves_metadata_unchanged(self) -> None:
        client = _make_client()
        payload = _gen(client, metadata={"env": "prod"})
        assert "model_type" not in payload.metadata
        assert payload.metadata.get("env") == "prod"

    def test_emit_failure_does_not_propagate(self) -> None:
        """Audit write failures must be swallowed — never block the caller."""
        client = SFExplainClient(SFClientConfig(), max_retries=0, emit_timeout_sec=0.5)
        with patch("spanforge.sdk.sf_audit") as m:
            m.append = MagicMock(side_effect=RuntimeError("audit unavailable"))
            # Should complete without raising
            payload = client.generate(
                trace_id="trace-safe",
                agent_id="agent-safe",
                decision_id="decision-safe",
                summary="fail-safe test",
                policy_action="allow",
                generated_at="2026-04-22T10:00:00Z",
            )
        assert payload.trace_id == "trace-safe"
