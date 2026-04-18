"""Type stubs for spanforge.sdk.cec (DX-001)."""

from __future__ import annotations

from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.sdk._types import (
    BundleResult,
    BundleVerificationResult,
    CECStatusInfo,
    DPADocument,
)

class SFCECClient(SFServiceClient):
    def __init__(self, config: SFClientConfig) -> None: ...
    def build_bundle(
        self,
        project_id: str,
        date_range: tuple[str, str],
        frameworks: list[str] | None = None,
    ) -> BundleResult: ...
    def verify_bundle(self, zip_path: str) -> BundleVerificationResult: ...
    def generate_dpa(
        self,
        project_id: str,
        controller_details: dict[str, str],
        processor_details: dict[str, str],
        *,
        processing_purposes: list[str] | None = None,
        data_categories: list[str] | None = None,
        data_subjects: list[str] | None = None,
        sub_processors: list[str] | None = None,
        transfer_mechanism: str = "SCCs",
        scc_clauses: str = "Module 2 (controller-to-processor)",
        retention_period: str = ...,
        security_measures: list[str] | None = None,
    ) -> DPADocument: ...
    def get_status(self) -> CECStatusInfo: ...
