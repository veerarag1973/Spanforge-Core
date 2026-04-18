"""Type stubs for spanforge.sdk.security (DX-001)."""

from __future__ import annotations

from typing import Any

from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.sdk._types import (
    DependencyVulnerability,
    SecurityAuditResult,
    SecurityScanResult,
    StaticAnalysisFinding,
    ThreatModelEntry,
)

class SFSecurityClient(SFServiceClient):
    def __init__(self, config: SFClientConfig) -> None: ...
    def run_owasp_audit(
        self,
        *,
        endpoint_count: int = 0,
        auth_mechanisms: list[str] | None = None,
        rate_limiting_enabled: bool = True,
        input_validation_enabled: bool = True,
        ssrf_protection_enabled: bool = True,
    ) -> SecurityAuditResult: ...
    def add_threat(
        self,
        service: str,
        category: str,
        threat: str,
        mitigation: str,
        risk_level: str = "medium",
    ) -> ThreatModelEntry: ...
    def get_threat_model(self, service: str | None = None) -> list[ThreatModelEntry]: ...
    def generate_default_threat_model(self) -> list[ThreatModelEntry]: ...
    def scan_dependencies(
        self,
        *,
        packages: dict[str, str] | None = None,
    ) -> list[DependencyVulnerability]: ...
    def run_static_analysis(
        self,
        *,
        source_files: list[str] | None = None,
    ) -> list[StaticAnalysisFinding]: ...
    def audit_logs_for_secrets(self, log_lines: list[str]) -> int: ...
    def audit_logs_for_secrets_safe(self, log_lines: list[str]) -> int: ...
    def run_full_scan(
        self,
        *,
        packages: dict[str, str] | None = None,
        source_files: list[str] | None = None,
        log_lines: list[str] | None = None,
    ) -> SecurityScanResult: ...
    def get_last_scan(self) -> SecurityScanResult | None: ...
    def get_status(self) -> dict[str, Any]: ...
