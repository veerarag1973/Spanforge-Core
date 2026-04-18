"""Type stubs for spanforge.sdk.enterprise (DX-001)."""

from __future__ import annotations

from typing import Any

from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.sdk._types import (
    AirGapConfig,
    EncryptionConfig,
    EnterpriseStatusInfo,
    HealthEndpointResult,
    IsolationScope,
    TenantConfig,
)

class SFEnterpriseClient(SFServiceClient):
    def __init__(self, config: SFClientConfig) -> None: ...
    def register_tenant(
        self,
        project_id: str,
        org_id: str,
        *,
        data_residency: str = "global",
        cross_project_read: bool = False,
        allowed_project_ids: list[str] | None = None,
    ) -> TenantConfig: ...
    def get_tenant(self, project_id: str) -> TenantConfig | None: ...
    def list_tenants(self) -> list[TenantConfig]: ...
    def get_isolation_scope(self, project_id: str) -> IsolationScope: ...
    def check_cross_project_access(
        self,
        source_project_id: str,
        target_project_ids: list[str],
    ) -> None: ...
    def get_endpoint_for_project(self, project_id: str) -> str: ...
    def enforce_data_residency(
        self,
        project_id: str,
        target_region: str,
    ) -> None: ...
    def configure_encryption(
        self,
        *,
        encrypt_at_rest: bool = False,
        kms_provider: str | None = None,
        mtls_enabled: bool = False,
        tls_cert_path: str = "",
        tls_key_path: str = "",
        tls_ca_path: str = "",
        fips_mode: bool = False,
    ) -> EncryptionConfig: ...
    def get_encryption_config(self) -> EncryptionConfig: ...
    def encrypt_payload(self, plaintext: bytes, key: bytes) -> dict[str, Any]: ...
    def decrypt_payload(
        self,
        ciphertext_hex: str,
        nonce_hex: str,
        tag_hex: str,
        key: bytes,
    ) -> bytes: ...
    def configure_airgap(
        self,
        *,
        offline: bool = False,
        self_hosted: bool = False,
        compose_file: str = "docker-compose.yml",
        helm_release_name: str = "spanforge",
        health_check_interval_s: int = 30,
    ) -> AirGapConfig: ...
    def get_airgap_config(self) -> AirGapConfig: ...
    def assert_network_allowed(self) -> None: ...
    def check_health_endpoint(
        self,
        service: str,
        endpoint: str = "/healthz",
    ) -> HealthEndpointResult: ...
    def check_all_services_health(self) -> list[HealthEndpointResult]: ...
    def get_status(self) -> EnterpriseStatusInfo: ...
