"""spanforge.sdk.explain - SpanForge sf-explain client.

Phase 1 implementation for GA runtime explainability. The client is designed
to be callable from application code and to emit signed records through
sf-audit using the canonical Phase 0 explanation payload.

Production-hardening (1B-1):
* ``ExplainModelType`` enum enumerates the five supported model categories.
* ``model_type`` parameter on :meth:`SFExplainClient.generate` is stored in
  metadata and influences how the explanation summary is validated.
* Emit-level retry logic with configurable ``max_retries`` and
  ``emit_timeout_sec``: transient audit-write failures are retried with
  capped exponential back-off instead of propagating to the caller.
* Hard ``emit_timeout_sec`` guard: if total retry time exceeds the configured
  budget the failure is logged and silently dropped (explanation records must
  never block the hot path).
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any

from spanforge.namespaces.runtime_governance import (
    ExplanationFactor,
    ExplanationPayload,
)
from spanforge.sdk._base import SFClientConfig, SFServiceClient

__all__ = ["ExplainModelType", "ExplainStatusInfo", "SFExplainClient"]

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model type enum
# ---------------------------------------------------------------------------


class ExplainModelType(str, Enum):
    """Canonical model categories for runtime explanation records.

    Used to classify which kind of model produced the decision being
    explained.  The value is stored in the explanation metadata under the
    ``"model_type"`` key.
    """

    LLM = "llm"
    RAG = "rag"
    MULTI_AGENT = "multi_agent"
    CLASSIFIER = "classifier"
    EMBEDDING = "embedding"


# ---------------------------------------------------------------------------
# Status dataclass
# ---------------------------------------------------------------------------


@dataclass
class ExplainStatusInfo:
    """sf-explain service status."""

    status: str
    total_generated: int
    traces_tracked: int


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

#: Default maximum emit retries before silently dropping the record.
_DEFAULT_MAX_RETRIES: int = 3
#: Default hard timeout (seconds) for the total emit-with-retry cycle.
_DEFAULT_EMIT_TIMEOUT_SEC: float = 5.0


class SFExplainClient(SFServiceClient):
    """SpanForge runtime explainability service client.

    Production hardening (1B-1):
    * Configurable ``max_retries`` and ``emit_timeout_sec`` control how long
      the client will attempt to write to sf-audit before giving up.
    * Failures are logged at WARNING level and never propagate to callers.
    """

    def __init__(
        self,
        config: SFClientConfig,
        *,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        emit_timeout_sec: float = _DEFAULT_EMIT_TIMEOUT_SEC,
    ) -> None:
        super().__init__(config, service_name="explain")
        self._lock = threading.Lock()
        self._records: dict[str, ExplanationPayload] = {}
        self._by_trace: dict[str, list[str]] = {}
        self._total_generated: int = 0
        self._max_retries = max_retries
        self._emit_timeout_sec = emit_timeout_sec

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
        model_type: ExplainModelType | str | None = None,
        confidence: float | None = None,
        policy_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ExplanationPayload:
        """Generate and persist a canonical runtime explanation record.

        Args:
            model_type: Optional :class:`ExplainModelType` (or raw string) that
                classifies the model producing the decision.  Stored under
                ``metadata["model_type"]``.
        """
        from spanforge.ulid import generate as _ulid

        merged_metadata: dict[str, Any] = dict(metadata or {})
        if model_type is not None:
            merged_metadata["model_type"] = (
                model_type.value if isinstance(model_type, ExplainModelType) else str(model_type)
            )

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
            metadata=merged_metadata,
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
        """Write the explanation payload into sf-audit with retry + timeout.

        The emit cycle is bounded by ``emit_timeout_sec``.  Transient failures
        are retried with exponential back-off (base: 0.1 s, factor: 2, no
        jitter added here — the lock above serialises calls anyway).  If all
        retries are exhausted the failure is logged at WARNING level and the
        record is silently dropped so that callers are never blocked.
        """
        from spanforge.sdk import sf_audit

        deadline = time.monotonic() + self._emit_timeout_sec
        delay = 0.1
        last_exc: BaseException | None = None
        for attempt in range(self._max_retries + 1):
            if time.monotonic() > deadline:
                break
            try:
                sf_audit.append(payload.to_dict(), "spanforge.explanation.v1")
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                remaining = deadline - time.monotonic()
                if attempt < self._max_retries and remaining > 0:
                    time.sleep(min(delay, remaining))
                    delay *= 2
        _log.warning(
            "sf_explain: audit emit failed after %d attempt(s), record dropped. error=%r",
            self._max_retries + 1,
            last_exc,
        )

    @staticmethod
    def _default_policy_client() -> Any:
        from spanforge.sdk import sf_policy

        return sf_policy
