"""Type stubs for spanforge.sdk.config (DX-001)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

@dataclass
class SFServiceToggles:
    sf_observe: bool = True
    sf_pii: bool = True
    sf_secrets: bool = True
    sf_audit: bool = True
    sf_gate: bool = True
    sf_cec: bool = True
    sf_identity: bool = True
    sf_alert: bool = True
    def is_enabled(self, name: str) -> bool: ...
    def as_dict(self) -> dict[str, bool]: ...

@dataclass
class SFLocalFallbackConfig:
    enabled: bool = True
    max_retries: int = 3
    timeout_ms: int = 2000

@dataclass
class SFPIIConfig:
    enabled: bool = True
    action: str = "redact"
    threshold: float = 0.75
    entity_types: list[str] = ...
    dpdp_scope: list[str] = ...

@dataclass
class SFSecretsConfig:
    enabled: bool = True
    auto_block: bool = True
    confidence: float = 0.75
    allowlist: list[str] = ...
    store_redacted: bool = False

@dataclass
class SFConfigBlock:
    enabled: bool = True
    project_id: str = ""
    endpoint: str = ""
    services: SFServiceToggles = ...
    local_fallback: SFLocalFallbackConfig = ...
    pii: SFPIIConfig = ...
    secrets: SFSecretsConfig = ...

def load_config_file(path: str | Path | None = None) -> SFConfigBlock: ...
def validate_config(block: SFConfigBlock) -> list[str]: ...
def validate_config_strict(block: SFConfigBlock) -> None: ...
