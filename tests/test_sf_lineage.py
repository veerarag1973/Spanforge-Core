"""Tests for spanforge.sdk.lineage - Phase 1 sf-lineage client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spanforge.sdk._base import SFClientConfig
from spanforge.sdk.lineage import LineageStatusInfo, SFLineageClient


def _make_client() -> SFLineageClient:
    return SFLineageClient(SFClientConfig(project_id="test-proj"))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class TestSFLineageClient:
    def test_record_returns_payload_and_indexes_it(self) -> None:
        client = _make_client()

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = client.record(
                trace_id="trace-001",
                decision_id="decision-001",
                subject_type="document",
                subject_id="doc-001",
                operation="retrieval",
                recorded_at="2026-04-22T12:30:00Z",
                input_refs=["store://kb/doc-001"],
                output_refs=["chunk://doc-001#0"],
                metadata={"retriever": "chroma-main"},
            )

        assert client.get(payload.lineage_id) == payload
        assert client.list_for_trace("trace-001") == [payload]
        assert client.list_for_subject(subject_type="document", subject_id="doc-001") == [payload]

    def test_record_preserves_parent_relationships(self) -> None:
        client = _make_client()

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = client.record(
                trace_id="trace-002",
                decision_id="decision-002",
                subject_type="response",
                subject_id="resp-001",
                operation="generation",
                recorded_at="2026-04-22T12:35:00Z",
                parent_lineage_ids=["lin-parent"],
                input_refs=["chunk://doc-001#0"],
                output_refs=["response://resp-001"],
            )

        assert payload.parent_lineage_ids == ["lin-parent"]
        assert payload.output_refs == ["response://resp-001"]

    def test_get_unknown_returns_none(self) -> None:
        client = _make_client()
        assert client.get("missing") is None

    def test_status_reflects_recorded_count(self) -> None:
        client = _make_client()

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            client.record(
                trace_id="trace-003",
                decision_id="decision-003",
                subject_type="agent",
                subject_id="agent-001",
                operation="plan",
                recorded_at="2026-04-22T12:40:00Z",
            )

        status = client.get_status()
        assert isinstance(status, LineageStatusInfo)
        assert status.total_recorded == 1
        assert status.traces_tracked == 1

    def test_record_writes_to_sf_audit(self) -> None:
        client = _make_client()

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = client.record(
                trace_id="trace-004",
                decision_id="decision-004",
                subject_type="document",
                subject_id="doc-004",
                operation="index",
                recorded_at="2026-04-22T12:45:00Z",
            )

        mock_audit_module.append.assert_called_once_with(
            payload.to_dict(),
            "spanforge.lineage.v1",
        )

    @pytest.mark.anyio
    async def test_record_async(self) -> None:
        client = _make_client()

        with patch("spanforge.sdk.sf_audit") as mock_audit_module:
            mock_audit_module.append = MagicMock()
            payload = await client.record_async(
                trace_id="trace-005",
                decision_id="decision-005",
                subject_type="response",
                subject_id="resp-005",
                operation="deliver",
                recorded_at="2026-04-22T12:50:00Z",
            )

        assert payload.subject_id == "resp-005"
