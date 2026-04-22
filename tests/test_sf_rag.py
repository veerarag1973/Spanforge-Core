"""Tests for GA grounding additions in spanforge.sdk.rag."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spanforge.namespaces.runtime_governance import GroundingClaim
from spanforge.sdk._base import SFClientConfig
from spanforge.sdk.rag import SFRAGClient
from spanforge.sdk._types import SecretStr


def _make_client() -> SFRAGClient:
    return SFRAGClient(SFClientConfig(api_key=SecretStr("test"), project_id="test-proj"))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class TestSFRAGClientGovernance:
    def test_assess_grounding_creates_signed_payload(self) -> None:
        client = _make_client()
        session_id = client.trace_query("What is AI?", top_k=3, retriever_name="chroma-main")

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = client.assess_grounding(
                trace_id="trace-001",
                decision_id="decision-001",
                session_id=session_id,
                threshold=0.8,
                policy_action="allow+log",
                assessed_at="2026-04-22T12:00:00Z",
                claims=[
                    GroundingClaim(
                        claim_id="claim-001",
                        claim_text="AI stands for artificial intelligence.",
                        grounded=True,
                        score=0.92,
                        source_ids=["doc-1"],
                    )
                ],
                model_id="gpt-4o",
            )

        assert payload.status == "grounded"
        assert payload.retriever_name == "chroma-main"
        assert client.get_grounding(payload.grounding_id) == payload
        assert client.list_grounding_for_trace("trace-001") == [payload]
        mock_audit_module.append.assert_called_once_with(
            payload.to_dict(),
            "spanforge.grounding.v1",
        )

    def test_assess_grounding_accepts_dict_claims_and_marks_partial(self) -> None:
        client = _make_client()
        session_id = client.trace_query("test", top_k=1, retriever_name="retriever")

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = client.assess_grounding(
                trace_id="trace-002",
                decision_id="decision-002",
                session_id=session_id,
                threshold=0.9,
                policy_action="human_review",
                assessed_at="2026-04-22T12:05:00Z",
                claims=[
                    {
                        "claim_id": "claim-001",
                        "claim_text": "Claim one",
                        "grounded": True,
                        "score": 0.95,
                        "source_ids": ["doc-1"],
                    },
                    {
                        "claim_id": "claim-002",
                        "claim_text": "Claim two",
                        "grounded": False,
                        "score": 0.4,
                        "source_ids": [],
                    },
                ],
            )

        assert payload.status == "partially_grounded"
        assert len(payload.claims) == 2
        assert payload.average_score == pytest.approx(0.675)

    def test_assess_grounding_without_claims_is_ungrounded(self) -> None:
        client = _make_client()
        session_id = client.trace_query("test", top_k=1, retriever_name="retriever")

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = client.assess_grounding(
                trace_id="trace-003",
                decision_id="decision-003",
                session_id=session_id,
                threshold=0.5,
                policy_action="block",
                assessed_at="2026-04-22T12:10:00Z",
                claims=[],
            )

        assert payload.status == "ungrounded"
        assert payload.average_score == 0.0

    @pytest.mark.anyio
    async def test_assess_grounding_async(self) -> None:
        client = _make_client()
        session_id = client.trace_query("async", top_k=1, retriever_name="retriever")

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = await client.assess_grounding_async(
                trace_id="trace-004",
                decision_id="decision-004",
                session_id=session_id,
                threshold=0.5,
                policy_action="allow",
                assessed_at="2026-04-22T12:15:00Z",
                claims=[
                    {
                        "claim_id": "claim-001",
                        "claim_text": "Async grounded claim",
                        "grounded": True,
                        "score": 0.8,
                        "source_ids": ["doc-1"],
                    }
                ],
            )

        assert payload.grounding_id
        assert payload.status == "grounded"
