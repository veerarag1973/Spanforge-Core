"""Type stubs for spanforge.sdk.audit (DX-001)."""

from __future__ import annotations

from typing import Any

from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.sdk._types import (
    Article30Record,
    AuditAppendResult,
    AuditStatusInfo,
    SignedRecord,
    TrustScorecard,
)

class SFAuditClient(SFServiceClient):
    def __init__(
        self,
        config: SFClientConfig,
        *,
        strict_schema: bool = True,
        retention_years: int = 7,
        byos_provider: str | None = None,
        db_path: str | None = None,
        persist_index: bool = False,
    ) -> None: ...
    def append(
        self,
        record: dict[str, Any],
        schema_key: str,
        *,
        project_id: str = "",
        strict_schema: bool | None = None,
    ) -> AuditAppendResult: ...
    def sign(self, record: dict[str, Any]) -> SignedRecord: ...
    def verify_chain(
        self,
        records: list[dict[str, Any]],
        *,
        org_secret: str | None = None,
    ) -> dict[str, Any]: ...
    def export(
        self,
        schema_key: str | None = None,
        *,
        date_range: tuple[str | None, str | None] | None = None,
        project_id: str | None = None,
        limit: int = 10_000,
    ) -> list[dict[str, Any]]: ...
    def get_trust_scorecard(
        self,
        project_id: str | None = None,
        *,
        from_dt: str | None = None,
        to_dt: str | None = None,
    ) -> TrustScorecard: ...
    def generate_article30_record(
        self,
        project_id: str | None = None,
        *,
        controller_name: str = "Data Controller",
        processor_name: str = ...,
        third_country: bool = False,
        retention_period: str | None = None,
    ) -> Article30Record: ...
    def get_status(self) -> AuditStatusInfo: ...
    def close(self) -> None: ...
