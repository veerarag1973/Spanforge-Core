"""Type stubs for spanforge.sdk.pii (DX-001)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from spanforge.event import Event
from spanforge.pii import Redactable, RedactionPolicy
from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.sdk._types import (
    DSARExport,
    ErasureReceipt,
    PIIAnonymisedResult,
    PIIHeatMapEntry,
    PIIPipelineResult,
    PIIStatusInfo,
    PIITextScanResult,
    SafeHarborResult,
    SFPIIAnonymizeResult,
    SFPIIRedactResult,
    SFPIIScanResult,
    TrainingDataPIIReport,
)

class SFPIIClient(SFServiceClient):
    def __init__(self, config: SFClientConfig) -> None: ...
    def scan(
        self,
        payload: dict[str, Any],
        *,
        extra_patterns: dict[str, re.Pattern[str]] | None = None,
        max_depth: int = 10,
    ) -> SFPIIScanResult: ...
    def redact(
        self,
        event: Event,
        *,
        policy: RedactionPolicy | None = None,
    ) -> SFPIIRedactResult: ...
    def contains_pii(
        self,
        event: Event,
        *,
        scan_raw: bool = True,
    ) -> bool: ...
    def assert_redacted(
        self,
        event: Event,
        *,
        context: str = "",
        scan_raw: bool = True,
    ) -> None: ...
    def anonymize(
        self,
        text: str,
        *,
        extra_patterns: dict[str, re.Pattern[str]] | None = None,
    ) -> SFPIIAnonymizeResult: ...
    def wrap(
        self,
        value: object,
        sensitivity: str,
        pii_types: frozenset[str] = ...,
    ) -> Redactable: ...
    def make_policy(
        self,
        *,
        min_sensitivity: str = "pii",
        redacted_by: str = "policy:sf-pii",
        replacement_template: str = "[REDACTED:{sensitivity}]",
    ) -> RedactionPolicy: ...
    def scan_text(
        self,
        text: str,
        *,
        language: str = "en",
        score_threshold: float = 0.5,
    ) -> PIITextScanResult: ...
    def anonymise(
        self,
        payload: dict[str, Any],
        *,
        max_depth: int = 10,
    ) -> PIIAnonymisedResult: ...
    def scan_batch(
        self,
        texts: list[str],
        *,
        language: str = "en",
        score_threshold: float = 0.5,
        max_workers: int = 8,
    ) -> list[PIITextScanResult]: ...
    def apply_pipeline_action(
        self,
        text: str,
        *,
        action: str = "flag",
        threshold: float = 0.85,
        language: str = "en",
    ) -> PIIPipelineResult: ...
    def get_status(self) -> PIIStatusInfo: ...
    def erase_subject(self, subject_id: str, project_id: str) -> ErasureReceipt: ...
    def export_subject_data(self, subject_id: str, project_id: str) -> DSARExport: ...
    def safe_harbor_deidentify(self, text: str) -> SafeHarborResult: ...
    def audit_training_data(
        self,
        dataset_path: str | Path,
        *,
        max_records: int = 100_000,
    ) -> TrainingDataPIIReport: ...
    def get_pii_stats(
        self,
        project_id: str,
        *,
        entity_type: str | None = None,
        days: int = 30,
    ) -> list[PIIHeatMapEntry]: ...
