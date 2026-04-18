"""Type stubs for spanforge.sdk.secrets (DX-001)."""

from __future__ import annotations

from typing import Any

from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.secrets import SecretsScanResult

class SFSecretsClient(SFServiceClient):
    def __init__(self, config: SFClientConfig) -> None: ...
    def scan(
        self,
        text: str,
        *,
        confidence_threshold: float = 0.75,
        extra_allowlist: frozenset[str] | None = None,
    ) -> SecretsScanResult: ...
    def scan_batch(
        self,
        texts: list[str],
        *,
        confidence_threshold: float = 0.75,
    ) -> list[SecretsScanResult]: ...
    def get_status(self) -> dict[str, Any]: ...
