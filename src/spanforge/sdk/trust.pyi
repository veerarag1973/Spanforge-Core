"""Type stubs for spanforge.sdk.trust (DX-001)."""

from __future__ import annotations

from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.sdk._types import (
    TrustBadgeResult,
    TrustDimensionWeights,
    TrustHistoryEntry,
    TrustScorecardResponse,
    TrustStatusInfo,
)

class SFTrustClient(SFServiceClient):
    def __init__(
        self,
        config: SFClientConfig,
        *,
        weights: TrustDimensionWeights | None = None,
    ) -> None: ...
    def get_scorecard(
        self,
        project_id: str | None = None,
        *,
        from_dt: str | None = None,
        to_dt: str | None = None,
        weights: TrustDimensionWeights | None = None,
    ) -> TrustScorecardResponse: ...
    def get_history(
        self,
        project_id: str | None = None,
        *,
        from_dt: str | None = None,
        to_dt: str | None = None,
        buckets: int = 10,
    ) -> list[TrustHistoryEntry]: ...
    def get_badge(
        self,
        project_id: str | None = None,
    ) -> TrustBadgeResult: ...
    def get_status(self) -> TrustStatusInfo: ...
