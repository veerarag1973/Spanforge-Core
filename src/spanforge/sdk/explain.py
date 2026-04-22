"""spanforge.sdk.explain - SpanForge sf-explain client.

Phase 1 implementation for GA runtime explainability. The client is designed
to be callable from application code and to emit signed records through
sf-audit using the canonical Phase 0 explanation payload.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from spanforge.namespaces.runtime_governance import (
    ExplanationFactor,
    ExplanationPayload,
)
from spanforge.sdk._base import SFClientConfig, SFServiceClient

__all__ = ["ExplainStatusInfo", "SFExplainClient"]


@dataclass
class ExplainStatusInfo:
    """sf-explain service status."""

    status: str
    total_generated: int
    traces_tracked: int


class SFExplainClient(SFServiceClient):
    """SpanForge runtime explainability service client."""

    def __init__(self, config: SFClientConfig) -> None:
        super().__init__(config, service_name="explain")
        self._lock = threading.Lock()
        self._records: dict[str, ExplanationPayload] = {}
        self._by_trace: dict[str, list[str]] = {}
        self._total_generated: int = 0

    def generate(
        self,
        *,
        trace_id: str,
        agent_id: str,
        decision_id: str,
        summary: str,
        policy_action: str,
        generated_at: str,
        factors: list[ExplanationFactor | dict[str, Any]] | None = None,
        explanation_id: str | None = None,
        model_id: str | None = None,
        confidence: float | None = None,
        policy_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExplanationPayload:
        """Generate and persist a canonical runtime explanation record."""
        from spanforge.ulid import generate as _ulid

        payload = ExplanationPayload(
            explanation_id=explanation_id or _ulid(),
            trace_id=trace_id,
            decision_id=decision_id,
            agent_id=agent_id,
            summary=summary,
            policy_action=policy_action,
            generated_at=generated_at,
            factors=[
                factor
                if isinstance(factor, ExplanationFactor)
                else ExplanationFactor.from_dict(factor)
                for factor in (factors or [])
            ],
            model_id=model_id,
            confidence=confidence,
            policy_id=policy_id,
            metadata=metadata or {},
        )

        with self._lock:
            self._records[payload.explanation_id] = payload
            self._by_trace.setdefault(trace_id, []).append(payload.explanation_id)
            self._total_generated += 1

        self._emit_signed_record(payload)
        return payload

    def generate_with_policy(
        self,
        *,
        environment: str,
        trace_id: str,
        agent_id: str,
        decision_id: str,
        summary: str,
        generated_at: str,
        policy_client: Any | None = None,
        control: str = "explanation_generation",
        coverage_score: float | None = None,
        factors: list[ExplanationFactor | dict[str, Any]] | None = None,
        explanation_id: str | None = None,
        model_id: str | None = None,
        confidence: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExplanationPayload:
        """Generate an explanation using the active runtime policy action."""
        engine = policy_client or self._default_policy_client()
        decision = engine.evaluate(
            environment=environment,
            trace_id=trace_id,
            service="sf_explain",
            control=control,
            evaluated_at=generated_at,
            observed_value=coverage_score,
            metadata={"agent_id": agent_id, "decision_id": decision_id},
        )
        return self.generate(
            trace_id=trace_id,
            agent_id=agent_id,
            decision_id=decision_id,
            summary=summary,
            policy_action=decision.action,
            generated_at=generated_at,
            factors=factors,
            explanation_id=explanation_id,
            model_id=model_id,
            confidence=confidence,
            policy_id=decision.policy_id,
            metadata=metadata,
        )

    async def generate_async(self, **kwargs: Any) -> ExplanationPayload:
        """Async wrapper around :meth:`generate`."""
        import asyncio

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self.generate(**kwargs))

    def get(self, explanation_id: str) -> ExplanationPayload | None:
        """Return a previously generated explanation payload."""
        with self._lock:
            return self._records.get(explanation_id)

    def list_for_trace(self, trace_id: str) -> list[ExplanationPayload]:
        """Return all explanation records emitted for a trace."""
        with self._lock:
            ids = list(self._by_trace.get(trace_id, []))
            return [self._records[item] for item in ids if item in self._records]

    def get_status(self) -> ExplainStatusInfo:
        """Return service health and usage counters."""
        with self._lock:
            return ExplainStatusInfo(
                status="ok",
                total_generated=self._total_generated,
                traces_tracked=len(self._by_trace),
            )

    def _emit_signed_record(self, payload: ExplanationPayload) -> None:
        """Write the explanation payload into sf-audit."""
        from spanforge.sdk import sf_audit

        sf_audit.append(payload.to_dict(), "spanforge.explanation.v1")

    @staticmethod
    def _default_policy_client() -> Any:
        from spanforge.sdk import sf_policy

        return sf_policy
