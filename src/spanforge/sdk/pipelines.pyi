"""Type stubs for spanforge.sdk.pipelines (DX-001)."""

from __future__ import annotations

from typing import Any

from spanforge.sdk._types import PipelineResult

def score_pipeline(
    text: str,
    *,
    model: str = "",
    project_id: str = "",
    pii_action: str = "redact",
) -> PipelineResult: ...

def bias_pipeline(
    bias_report: dict[str, Any],
    *,
    project_id: str = "",
    disparity_threshold: float = 0.1,
) -> PipelineResult: ...

def monitor_pipeline(
    event: dict[str, Any],
    *,
    project_id: str = "",
) -> PipelineResult: ...

def risk_pipeline(
    prri_record: dict[str, Any],
    *,
    project_id: str = "",
    run_gate: bool = False,
    build_cec: bool = False,
) -> PipelineResult: ...

def benchmark_pipeline(
    run_result: dict[str, Any],
    *,
    project_id: str = "",
    f1_regression_threshold: float = 0.05,
) -> PipelineResult: ...
