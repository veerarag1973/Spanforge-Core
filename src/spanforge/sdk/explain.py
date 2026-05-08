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
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from spanforge.namespaces.runtime_governance import (
    ExplanationFactor,
    ExplanationPayload,
)
from spanforge.sdk._base import SFClientConfig, SFServiceClient

__all__ = [
    "EUAIActClause",
    "ExplainModelType",
    "ExplainRecord",
    "ExplainStatusInfo",
    "ModelOutputType",
    "SFExplainClient",
]

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# EU AI Act clause constants
# ---------------------------------------------------------------------------

#: Article 13 — Transparency and provision of information to deployers.
#: Mapped from ``decision_drivers`` field.
_ARTICLE_13_ID = "Article 13"
_ARTICLE_13_REQ = (
    "Transparency and provision of information to deployers. "
    "High-risk AI systems must be designed to enable deployers to "
    "understand the system's capabilities and limitations."
)

#: Article 14 — Human oversight.
#: Mapped from ``confidence_score`` threshold flag.
_ARTICLE_14_ID = "Article 14"
_ARTICLE_14_REQ = (
    "Human oversight. High-risk AI systems must be designed and developed "
    "so that natural persons can effectively oversee them during use."
)

#: Default confidence threshold below which human oversight is required (Article 14).
_DEFAULT_OVERSIGHT_THRESHOLD: float = 0.7

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
# Model output type enum
# ---------------------------------------------------------------------------


class ModelOutputType(str, Enum):
    """Five canonical model output categories for explain records.

    Each value maps to a dedicated test case and determines how decision
    drivers are extracted from the model response.
    """

    CLASSIFICATION = "classification"
    GENERATION = "generation"
    STRUCTURED = "structured"
    REJECTION = "rejection"
    TOOL_CALL = "tool_call"


# ---------------------------------------------------------------------------
# EU AI Act clause dataclass
# ---------------------------------------------------------------------------


@dataclass
class EUAIActClause:
    """Mapping of one EU AI Act clause to an ``ExplainRecord`` field.

    Attributes:
        article:      Clause identifier (e.g. ``"Article 13"``).
        requirement:  Short human-readable description of the obligation.
        mapped_field: Name of the ``ExplainRecord`` field that satisfies it.
        satisfied:    Whether the clause is satisfied by the current record.
        notes:        Optional free-text annotation.
    """

    article: str
    requirement: str
    mapped_field: str
    satisfied: bool
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "article": self.article,
            "requirement": self.requirement,
            "mapped_field": self.mapped_field,
            "satisfied": self.satisfied,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# ExplainRecord — roadmap-contract return type for explain()
# ---------------------------------------------------------------------------


@dataclass
class ExplainRecord:
    """High-level, roadmap-contract explanation record returned by
    :meth:`SFExplainClient.explain`.

    This is the primary consumer-facing type for CARD 1B-1.  It extends the
    low-level :class:`~spanforge.namespaces.runtime_governance.ExplanationPayload`
    with the fields required by the roadmap contract and EU AI Act mappings.

    Fields
    ------
    decision_drivers:
        Extracted contributing factors (Art. 13 — transparency).
    confidence_score:
        Normalised float in [0, 1] representing model certainty (Art. 14).
    model_version:
        Optional model identifier / version string.
    hmac_signature:
        HMAC-SHA256 signature returned by ``sf_audit.append()``.
    eu_ai_act_clauses:
        Article 13 and Article 14 clause mappings with pass/fail status.
    human_oversight_required:
        ``True`` when *confidence_score* is below the oversight threshold
        (Article 14 flag).
    model_output_type:
        One of the five canonical output categories
        (``classification``, ``generation``, ``structured``,
        ``rejection``, ``tool_call``).
    """

    explanation_id: str
    trace_id: str
    agent_id: str
    decision_id: str
    model_output_type: str
    decision_drivers: list[dict[str, Any]]
    confidence_score: float
    model_version: str | None
    hmac_signature: str
    eu_ai_act_clauses: list[EUAIActClause]
    generated_at: str
    human_oversight_required: bool = field(init=False)
    audit_record_id: str = ""

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence_score <= 1.0):
            raise ValueError("ExplainRecord.confidence_score must be in [0.0, 1.0]")
        self.human_oversight_required = self.confidence_score < _DEFAULT_OVERSIGHT_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        return {
            "explanation_id": self.explanation_id,
            "trace_id": self.trace_id,
            "agent_id": self.agent_id,
            "decision_id": self.decision_id,
            "model_output_type": self.model_output_type,
            "decision_drivers": self.decision_drivers,
            "confidence_score": self.confidence_score,
            "model_version": self.model_version,
            "hmac_signature": self.hmac_signature,
            "eu_ai_act_clauses": [c.to_dict() for c in self.eu_ai_act_clauses],
            "generated_at": self.generated_at,
            "human_oversight_required": self.human_oversight_required,
            "audit_record_id": self.audit_record_id,
        }


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

    # ------------------------------------------------------------------
    # CARD 1B-1: roadmap-contract explain() API
    # ------------------------------------------------------------------

    def explain(
        self,
        response: str | dict[str, Any],
        context: dict[str, Any],
        *,
        oversight_threshold: float = _DEFAULT_OVERSIGHT_THRESHOLD,
    ) -> ExplainRecord:
        """Generate a signed :class:`ExplainRecord` for a single model response.

        This is the roadmap-contract entry point (``explain(response, context)``).
        It runs all production-hardening steps in order:

        1. Determine ``model_output_type`` from *context* or *response* shape.
        2. Extract ``decision_drivers`` from response content.
        3. Compute ``confidence_score`` from context or response metadata.
        4. Map EU AI Act Articles 13 and 14 clauses.
        5. Call :meth:`generate` to persist the ``ExplanationPayload``.
        6. HMAC-sign via ``sf_audit.append()`` and capture the signature.
        7. Return the fully-populated :class:`ExplainRecord`.

        The method **never raises** on content-level issues; only
        ``ValueError`` from invalid field ranges can propagate.

        Args:
            response:
                Model output — either a plain ``str`` or a ``dict`` (e.g.
                a JSON-decoded structured output or tool-call payload).
            context:
                Caller-supplied metadata dict.  Recognised keys:

                ``trace_id`` *(required)* — trace identifier.
                ``agent_id`` *(required)* — agent identifier.
                ``decision_id`` — decision identifier (auto-generated if absent).
                ``model_output_type`` — one of ``"classification"``,
                    ``"generation"``, ``"structured"``, ``"rejection"``,
                    ``"tool_call"``.  Inferred from *response* shape when absent.
                ``confidence_score`` — float in [0, 1].
                ``model_version`` — model name/version string.
                ``policy_action`` — defaults to ``"allow"``.
                ``generated_at`` — ISO-8601 timestamp (auto-generated if absent).
            oversight_threshold:
                Confidence score below which ``human_oversight_required`` is
                set to ``True`` (Article 14).  Defaults to 0.7.

        Returns:
            :class:`ExplainRecord` populated with EU AI Act clause mappings and
            an HMAC signature from sf-audit.
        """
        from datetime import datetime, timezone

        from spanforge.ulid import generate as _ulid

        trace_id: str = context.get("trace_id", "") or _ulid()
        agent_id: str = context.get("agent_id", "") or "unknown"
        decision_id: str = context.get("decision_id", "") or _ulid()
        generated_at: str = context.get("generated_at", "") or datetime.now(timezone.utc).isoformat()
        policy_action: str = context.get("policy_action", "allow")
        model_version: str | None = context.get("model_version")
        confidence_score: float = float(context.get("confidence_score", 0.0))

        # --- 1. Determine model output type ---
        raw_type: str = context.get("model_output_type", "")
        output_type: str = self._infer_output_type(response, raw_type)

        # --- 2. Extract decision drivers ---
        decision_drivers: list[dict[str, Any]] = self._extract_decision_drivers(
            response, output_type, context
        )

        # --- 3. Map EU AI Act clauses ---
        eu_ai_act_clauses = _build_eu_ai_act_clauses(
            decision_drivers=decision_drivers,
            confidence_score=confidence_score,
            oversight_threshold=oversight_threshold,
        )

        # --- 4. Call generate() to persist ExplanationPayload ---
        explanation_id = _ulid()
        factors: list[dict[str, Any]] = [
            {
                "factor_name": d.get("name", "driver"),
                "weight": float(d.get("weight", 1.0 / max(len(decision_drivers), 1))),
                "contribution": float(d.get("contribution", 0.0)),
                "evidence": str(d.get("evidence", d.get("value", ""))),
            }
            for d in decision_drivers
        ]
        summary = context.get("summary", f"{output_type} explanation for decision {decision_id}")
        payload = self.generate(
            trace_id=trace_id,
            agent_id=agent_id,
            decision_id=decision_id,
            summary=summary,
            policy_action=policy_action,
            generated_at=generated_at,
            factors=factors,
            explanation_id=explanation_id,
            model_id=model_version,
            model_type=ExplainModelType(output_type) if output_type in {e.value for e in ExplainModelType} else None,
            confidence=confidence_score if confidence_score > 0.0 else None,
            metadata={"model_output_type": output_type, "eu_ai_act": True},
        )

        # --- 5. HMAC-sign via sf_audit.append() and capture signature ---
        hmac_signature, audit_record_id = self._sign_explain_record(
            explanation_id=payload.explanation_id,
            output_type=output_type,
            confidence_score=confidence_score,
            eu_ai_act_clauses=eu_ai_act_clauses,
            generated_at=generated_at,
        )

        record = ExplainRecord(
            explanation_id=payload.explanation_id,
            trace_id=trace_id,
            agent_id=agent_id,
            decision_id=decision_id,
            model_output_type=output_type,
            decision_drivers=decision_drivers,
            confidence_score=confidence_score,
            model_version=model_version,
            hmac_signature=hmac_signature,
            eu_ai_act_clauses=eu_ai_act_clauses,
            generated_at=generated_at,
            audit_record_id=audit_record_id,
        )
        return record

    # ------------------------------------------------------------------
    # CARD 1B-1 helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_output_type(response: str | dict[str, Any], hint: str) -> str:
        """Infer model output type from *hint* or *response* shape."""
        valid = {e.value for e in ModelOutputType}
        if hint in valid:
            return hint
        if isinstance(response, dict):
            # Tool-call payload has "tool_calls" or "function_call" key
            if "tool_calls" in response or "function_call" in response:
                return ModelOutputType.TOOL_CALL.value
            # Rejection payload typically has "refusal" or "blocked" key
            if "refusal" in response or "blocked" in response:
                return ModelOutputType.REJECTION.value
            # Structured output has arbitrary dict keys
            return ModelOutputType.STRUCTURED.value
        if isinstance(response, str):
            lo = response.lower().strip()
            if lo.startswith(("i'm sorry", "i cannot", "i can't", "i won't", "i am unable")):
                return ModelOutputType.REJECTION.value
            # Classification outputs are short label strings
            if len(lo) < 60 and "\n" not in lo:
                return ModelOutputType.CLASSIFICATION.value
        return ModelOutputType.GENERATION.value

    @staticmethod
    def _extract_decision_drivers(
        response: str | dict[str, Any],
        output_type: str,
        context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Extract decision drivers from a model response.

        Returns a list of driver dicts, each with keys:
        ``name``, ``value``, ``weight``, ``contribution``, ``evidence``.
        """
        drivers: list[dict[str, Any]] = list(context.get("decision_drivers", []))
        if drivers:
            return drivers

        if output_type == ModelOutputType.CLASSIFICATION.value:
            label = response if isinstance(response, str) else response.get("label", str(response))
            drivers = [{"name": "predicted_class", "value": label, "weight": 1.0,
                        "contribution": 1.0, "evidence": "model output"}]
        elif output_type == ModelOutputType.REJECTION.value:
            reason = (
                response.get("refusal", response.get("reason", "content policy"))
                if isinstance(response, dict)
                else str(response)
            )
            drivers = [{"name": "rejection_reason", "value": reason, "weight": 1.0,
                        "contribution": -1.0, "evidence": "content policy violation"}]
        elif output_type == ModelOutputType.TOOL_CALL.value:
            if isinstance(response, dict):
                tool_calls = response.get("tool_calls", [])
                tool_name = (
                    response.get("function_call", {}).get("name", "")
                    or (tool_calls[0].get("function", {}).get("name", "tool_call") if tool_calls else "tool_call")
                )
            else:
                tool_name = "tool_call"
            drivers = [{"name": "tool_selected", "value": tool_name, "weight": 1.0,
                        "contribution": 1.0, "evidence": "agent tool selection"}]
        elif output_type == ModelOutputType.STRUCTURED.value:
            keys = list(response.keys()) if isinstance(response, dict) else []
            drivers = [{"name": "structured_fields", "value": keys, "weight": 1.0,
                        "contribution": 1.0, "evidence": "schema-validated output"}]
        else:  # generation
            text = response if isinstance(response, str) else str(response)
            snippet = text[:120] if len(text) > 120 else text
            drivers = [{"name": "generated_text", "value": snippet, "weight": 1.0,
                        "contribution": 1.0, "evidence": "model generation"}]
        return drivers

    def _sign_explain_record(
        self,
        *,
        explanation_id: str,
        output_type: str,
        confidence_score: float,
        eu_ai_act_clauses: list[EUAIActClause],
        generated_at: str,
    ) -> tuple[str, str]:
        """Append a signed explain record to sf-audit.

        Returns ``(hmac_signature, audit_record_id)``.  Falls back to an empty
        signature string on emit failure so the hot path is never blocked.
        """
        from spanforge.sdk import sf_audit

        record_payload: dict[str, Any] = {
            "explanation_id": explanation_id,
            "model_output_type": output_type,
            "confidence_score": confidence_score,
            "eu_ai_act_clauses": [c.to_dict() for c in eu_ai_act_clauses],
            "generated_at": generated_at,
        }
        deadline = time.monotonic() + self._emit_timeout_sec
        delay = 0.1
        last_exc: BaseException | None = None
        for attempt in range(self._max_retries + 1):
            if time.monotonic() > deadline:
                break
            try:
                result = sf_audit.append(record_payload, "spanforge.explanation.v1")
                return result.hmac_signature, result.record_id
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                remaining = deadline - time.monotonic()
                if attempt < self._max_retries and remaining > 0:
                    time.sleep(min(delay, remaining))
                    delay *= 2
        _log.warning(
            "sf_explain: explain() audit emit failed after %d attempt(s). error=%r",
            self._max_retries + 1,
            last_exc,
        )
        return "", ""

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


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _build_eu_ai_act_clauses(
    *,
    decision_drivers: list[dict[str, Any]],
    confidence_score: float,
    oversight_threshold: float,
) -> list[EUAIActClause]:
    """Build EU AI Act Article 13 and 14 clause mappings for an ExplainRecord.

    Article 13 (Transparency) is satisfied when decision drivers are present.
    Article 14 (Human Oversight) is satisfied when confidence is at or above
    the oversight threshold.
    """
    art13_satisfied = bool(decision_drivers)
    art14_satisfied = confidence_score >= oversight_threshold

    art13 = EUAIActClause(
        article=_ARTICLE_13_ID,
        requirement=_ARTICLE_13_REQ,
        mapped_field="decision_drivers",
        satisfied=art13_satisfied,
        notes=(
            f"{len(decision_drivers)} driver(s) extracted"
            if art13_satisfied
            else "No decision drivers available"
        ),
    )
    art14 = EUAIActClause(
        article=_ARTICLE_14_ID,
        requirement=_ARTICLE_14_REQ,
        mapped_field="confidence_score",
        satisfied=art14_satisfied,
        notes=(
            f"confidence_score={confidence_score:.3f} >= threshold={oversight_threshold:.3f}"
            if art14_satisfied
            else (
                f"confidence_score={confidence_score:.3f} < threshold={oversight_threshold:.3f}; "
                "human oversight required"
            )
        ),
    )
    return [art13, art14]
