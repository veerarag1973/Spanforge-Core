"""Tests for spanforge.sdk.explain - Phase 1 sf-explain client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spanforge.namespaces.runtime_governance import ExplanationFactor
from spanforge.sdk._base import SFClientConfig
from spanforge.sdk.explain import ExplainStatusInfo, SFExplainClient


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
