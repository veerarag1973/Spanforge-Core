"""Type stubs for spanforge.sdk.gate (DX-001)."""

from __future__ import annotations

from typing import Any

from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.sdk._types import (
    GateArtifact,
    GateEvaluationResult,
    GateStatusInfo,
    PRRIResult,
    TrustGateResult,
)

class SFGateClient(SFServiceClient):
    def __init__(self, config: SFClientConfig) -> None: ...
    def evaluate(
        self,
        gate_id: str,
        payload: dict[str, Any],
        *,
        project_id: str = "",
        pipeline_id: str = "",
    ) -> GateEvaluationResult: ...
    def run_trust_gate(
        self,
        project_id: str,
        *,
        pipeline_id: str = "",
        hri_window: int | None = None,
        pii_window_hours: int = 24,
        secrets_window_hours: int = 24,
    ) -> TrustGateResult: ...
    def evaluate_prri(
        self,
        project_id: str,
        *,
        prri_score: int,
        threshold: int = 70,
        framework: str = "",
        policy_file: str = "",
        dimension_breakdown: dict[str, Any] | None = None,
    ) -> PRRIResult: ...
    def list_artifacts(
        self,
        gate_id: str | None = None,
        *,
        limit: int = 50,
    ) -> list[GateArtifact]: ...
    def get_status(self) -> GateStatusInfo: ...
