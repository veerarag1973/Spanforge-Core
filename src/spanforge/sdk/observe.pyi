"""Type stubs for spanforge.sdk.observe (DX-001)."""

from __future__ import annotations

from typing import Any

from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.sdk._types import (
    Annotation,
    ExportResult,
    ObserveStatusInfo,
    ReceiverConfig,
)

class SFObserveClient(SFServiceClient):
    def __init__(self, config: SFClientConfig) -> None: ...
    def export_spans(
        self,
        spans: list[dict[str, Any]],
        *,
        receiver_config: ReceiverConfig | None = None,
    ) -> ExportResult: ...
    def emit_span(
        self,
        name: str,
        attributes: dict[str, Any],
        *,
        trace_id_hex: str | None = None,
        parent_traceparent: str | None = None,
    ) -> dict[str, Any]: ...
    def add_annotation(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        project_id: str,
    ) -> str: ...
    def get_annotations(
        self,
        event_type: str,
        from_dt: str,
        to_dt: str,
        *,
        project_id: str = "",
    ) -> list[Annotation]: ...
    @property
    def healthy(self) -> bool: ...
    @property
    def last_export_at(self) -> str | None: ...
    def get_status(self) -> ObserveStatusInfo: ...
