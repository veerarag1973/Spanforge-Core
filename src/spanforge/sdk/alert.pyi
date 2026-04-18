"""Type stubs for spanforge.sdk.alert (DX-001)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.sdk._types import (
    AlertRecord,
    AlertStatusInfo,
    PublishResult,
)

class SFAlertClient(SFServiceClient):
    def __init__(self, config: SFClientConfig) -> None: ...
    def register_topic(
        self,
        topic: str,
        description: str,
        default_severity: str = "warning",
        *,
        runbook_url: str | None = None,
        dedup_window_seconds: float | None = None,
    ) -> None: ...
    def set_maintenance_window(
        self,
        project_id: str,
        start: datetime,
        end: datetime,
    ) -> None: ...
    def remove_maintenance_windows(self, project_id: str) -> int: ...
    def publish(
        self,
        topic: str,
        payload: dict[str, Any],
        *,
        severity: str | None = None,
        project_id: str | None = None,
    ) -> PublishResult: ...
    def acknowledge(self, alert_id: str) -> bool: ...
    def get_alert_history(
        self,
        *,
        project_id: str | None = None,
        topic: str | None = None,
        from_dt: datetime | None = None,
        to_dt: datetime | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[AlertRecord]: ...
    def get_status(self) -> AlertStatusInfo: ...
    def add_sink(self, alerter: Any, name: str | None = None) -> None: ...
    def shutdown(self, timeout: float = 5.0) -> None: ...
    @property
    def healthy(self) -> bool: ...
