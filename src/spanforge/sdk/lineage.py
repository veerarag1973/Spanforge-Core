"""spanforge.sdk.lineage - SpanForge sf-lineage client.

Phase 1 implementation for GA runtime provenance and decision lineage. The
client records canonical lineage payloads and emits signed evidence via
sf-audit.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from spanforge.namespaces.runtime_governance import LineagePayload
from spanforge.sdk._base import SFClientConfig, SFServiceClient

__all__ = ["LineageStatusInfo", "SFLineageClient"]


@dataclass
class LineageStatusInfo:
    """sf-lineage service status."""

    status: str
    total_recorded: int
    traces_tracked: int


class SFLineageClient(SFServiceClient):
    """SpanForge runtime lineage service client."""

    def __init__(self, config: SFClientConfig) -> None:
        super().__init__(config, service_name="lineage")
        self._lock = threading.Lock()
        self._records: dict[str, LineagePayload] = {}
        self._by_trace: dict[str, list[str]] = {}
        self._by_subject: dict[str, list[str]] = {}
        self._total_recorded = 0

    def record(
        self,
        *,
        trace_id: str,
        decision_id: str,
        subject_type: str,
        subject_id: str,
        operation: str,
        recorded_at: str,
        lineage_id: str | None = None,
        input_refs: list[str] | None = None,
        output_refs: list[str] | None = None,
        parent_lineage_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LineagePayload:
        """Create and persist a canonical lineage record."""
        from spanforge.ulid import generate as _ulid

        payload = LineagePayload(
            lineage_id=lineage_id or _ulid(),
            trace_id=trace_id,
            decision_id=decision_id,
            subject_type=subject_type,
            subject_id=subject_id,
            operation=operation,
            recorded_at=recorded_at,
            input_refs=list(input_refs or []),
            output_refs=list(output_refs or []),
            parent_lineage_ids=list(parent_lineage_ids or []),
            metadata=metadata or {},
        )

        subject_key = self._subject_key(subject_type, subject_id)
        with self._lock:
            self._records[payload.lineage_id] = payload
            self._by_trace.setdefault(trace_id, []).append(payload.lineage_id)
            self._by_subject.setdefault(subject_key, []).append(payload.lineage_id)
            self._total_recorded += 1

        self._emit_signed_record(payload)
        return payload

    def record_with_policy(
        self,
        *,
        environment: str,
        trace_id: str,
        decision_id: str,
        subject_type: str,
        subject_id: str,
        operation: str,
        recorded_at: str,
        policy_client: Any | None = None,
        control: str = "lineage_capture",
        lineage_id: str | None = None,
        input_refs: list[str] | None = None,
        output_refs: list[str] | None = None,
        parent_lineage_ids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LineagePayload:
        """Record lineage using the active runtime policy decision metadata."""
        engine = policy_client or self._default_policy_client()
        decision = engine.evaluate(
            environment=environment,
            trace_id=trace_id,
            service="sf_lineage",
            control=control,
            evaluated_at=recorded_at,
            metadata={"subject_type": subject_type, "subject_id": subject_id},
        )
        merged_metadata = dict(metadata or {})
        merged_metadata.setdefault("policy_id", decision.policy_id)
        merged_metadata.setdefault("policy_action", decision.action)
        return self.record(
            trace_id=trace_id,
            decision_id=decision_id,
            subject_type=subject_type,
            subject_id=subject_id,
            operation=operation,
            recorded_at=recorded_at,
            lineage_id=lineage_id,
            input_refs=input_refs,
            output_refs=output_refs,
            parent_lineage_ids=parent_lineage_ids,
            metadata=merged_metadata,
        )

    async def record_async(self, **kwargs: Any) -> LineagePayload:
        """Async wrapper around :meth:`record`."""
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.record(**kwargs))

    def get(self, lineage_id: str) -> LineagePayload | None:
        """Return a previously emitted lineage record."""
        with self._lock:
            return self._records.get(lineage_id)

    def list_for_trace(self, trace_id: str) -> list[LineagePayload]:
        """Return all lineage records emitted for a trace."""
        with self._lock:
            ids = list(self._by_trace.get(trace_id, []))
            return [self._records[item] for item in ids if item in self._records]

    def list_for_subject(self, *, subject_type: str, subject_id: str) -> list[LineagePayload]:
        """Return all lineage records for one subject."""
        subject_key = self._subject_key(subject_type, subject_id)
        with self._lock:
            ids = list(self._by_subject.get(subject_key, []))
            return [self._records[item] for item in ids if item in self._records]

    def get_status(self) -> LineageStatusInfo:
        """Return service health and lineage counters."""
        with self._lock:
            return LineageStatusInfo(
                status="ok",
                total_recorded=self._total_recorded,
                traces_tracked=len(self._by_trace),
            )

    @staticmethod
    def _subject_key(subject_type: str, subject_id: str) -> str:
        return f"{subject_type}:{subject_id}"

    def _emit_signed_record(self, payload: LineagePayload) -> None:
        """Write the lineage payload into sf-audit."""
        from spanforge.sdk import sf_audit

        sf_audit.append(payload.to_dict(), "spanforge.lineage.v1")

    @staticmethod
    def _default_policy_client() -> Any:
        from spanforge.sdk import sf_policy

        return sf_policy
