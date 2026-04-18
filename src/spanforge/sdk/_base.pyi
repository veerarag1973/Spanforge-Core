"""Type stubs for spanforge.sdk._base (DX-001)."""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any

from spanforge.sdk._types import RateLimitInfo, SecretStr

__all__ = [
    "SFClientConfig",
    "SFServiceClient",
    "_CircuitBreaker",
    "_SlidingWindowRateLimiter",
]

class _CircuitBreaker:
    CLOSED: str
    OPEN: str
    def __init__(
        self,
        threshold: int = 5,
        reset_seconds: float = 30.0,
    ) -> None: ...
    @property
    def state(self) -> str: ...
    def is_open(self) -> bool: ...
    def record_success(self) -> None: ...
    def record_failure(self) -> None: ...
    def reset(self) -> None: ...

class _SlidingWindowRateLimiter:
    def __init__(
        self,
        limit: int = 600,
        window_seconds: float = 60.0,
    ) -> None: ...
    def check(self, key_id: str) -> RateLimitInfo: ...
    def record(self, key_id: str) -> bool: ...
    def remaining(self, key_id: str) -> int: ...
    def clear(self, key_id: str) -> None: ...

@dataclass
class SFClientConfig:
    endpoint: str = ""
    api_key: SecretStr = ...
    project_id: str = ""
    timeout_ms: int = 2_000
    max_retries: int = 3
    local_fallback_enabled: bool = True
    tls_verify: bool = True
    proxy: str | None = None
    signing_key: str = ""
    magic_secret: str = ""
    @classmethod
    def from_env(cls) -> SFClientConfig: ...

class SFServiceClient(abc.ABC):
    _config: SFClientConfig
    _service_name: str
    _circuit_breaker: _CircuitBreaker
    def __init__(self, config: SFClientConfig, service_name: str) -> None: ...
    def _is_local_mode(self) -> bool: ...
    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...
    def _on_token_near_expiry(self, seconds_remaining: int) -> None: ...
