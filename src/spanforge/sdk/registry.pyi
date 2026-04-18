"""Type stubs for spanforge.sdk.registry (DX-001)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

class ServiceStatus(str, Enum):
    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"

@dataclass
class ServiceHealth:
    status: ServiceStatus = ServiceStatus.DOWN
    latency_ms: float = -1.0
    last_checked_at: datetime | None = None

class ServiceRegistry:
    @classmethod
    def get_instance(cls) -> ServiceRegistry: ...
    @classmethod
    def _reset_for_testing(cls) -> None: ...
    def register(self, name: str, client: Any) -> None: ...
    def get(self, name: str) -> Any: ...
    def register_all(self, clients: dict[str, Any]) -> None: ...
    def run_startup_check(
        self,
        endpoint: str = "",
        *,
        enabled_services: set[str] | None = None,
        local_fallback_enabled: bool = True,
        timeout_ms: int = 2000,
    ) -> dict[str, ServiceHealth]: ...
    def status_response(self) -> dict[str, dict[str, Any]]: ...
    def get_health(self, name: str) -> ServiceHealth: ...
    def update_health(self, name: str, health: ServiceHealth) -> None: ...
    def start_background_checker(
        self,
        endpoint: str = "",
        interval: float = 60.0,
        timeout_ms: int = 2000,
    ) -> None: ...
    def stop_background_checker(self) -> None: ...
