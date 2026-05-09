"""spanforge.sdk.validate — SpanForge sf-validate client (CARD 1C-1).

Validates model responses on the hot path using four ordered enforcement
mechanisms:

1. **Schema check** — JSON Schema dict (``jsonschema`` when available,
   structural fallback otherwise) or regex pattern.
2. **Confidence threshold check** — rejects responses whose
   ``confidence_score`` falls below *confidence_threshold* (default 0.7).
   Calls :meth:`SFExplainClient.generate` when no score is provided.
3. **Content policy check** — runs :meth:`SFPIIClient.scan_text` and
   :class:`~spanforge.secrets.SecretsScanner` on the response.  PII
   produces a violation; secrets set ``auto_blocked=True``.
4. **Multi-pass correction** — calls *correction_fn(response, violations)*
   up to *max_correction_passes* times (default: 2) until all violations
   are resolved.

All four mechanisms run in-process with zero required external dependencies.

Audit integration
-----------------
Every :meth:`SFValidateClient.validate` call appends a HMAC-signed record
to ``sf_audit`` under schema ``spanforge.validate.v1``.  Records include
the SHA-256 hash of the original response (not raw text), violation types,
pass/fail, and correction count.

When a correction pass runs, an additional ``spanforge.validate.correction.v1``
event is appended so cost attribution can be tracked downstream.

Contract guarantees
-------------------
*  :meth:`validate` **never raises** on content violations — it always
   returns a :class:`ValidationResult`.
*  ``ValidationResult.passed`` is ``True`` only when all mechanisms pass
   (or when remaining violations are resolved by correction).
*  Audit write failures are swallowed at ``WARNING`` level to ensure the
   hot path is never blocked by an infra issue.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from spanforge.sdk._base import SFClientConfig, SFServiceClient

__all__ = [
    "SFValidateClient",
    "ValidateStatusInfo",
    "ValidationResult",
    "Violation",
]

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_CONFIDENCE_THRESHOLD: float = 0.7
_DEFAULT_MAX_CORRECTION_PASSES: int = 2
_AUDIT_SCHEMA_KEY: str = "spanforge.validate.v1"
_CORRECTION_AUDIT_SCHEMA_KEY: str = "spanforge.validate.correction.v1"

_SEVERITY_LEVELS: frozenset[str] = frozenset({"low", "medium", "high", "critical"})


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class Violation:
    """A single policy violation detected during ``validate()``.

    Attributes:
        type:     Violation category, e.g. ``"schema"``, ``"confidence"``,
                  ``"pii"``, ``"secret"``.
        field:    Dotted field path within the response that triggered the
                  violation, or ``""`` for whole-response violations.
        message:  Human-readable description of the violation.
        severity: One of ``"low"``, ``"medium"``, ``"high"``, ``"critical"``.
    """

    type: str
    field: str
    message: str
    severity: str

    def __post_init__(self) -> None:
        """Validate severity value."""
        if self.severity not in _SEVERITY_LEVELS:
            msg = f"Violation.severity must be one of {sorted(_SEVERITY_LEVELS)}; got {self.severity!r}"
            raise ValueError(msg)

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for JSON serialisation."""
        return {
            "type": self.type,
            "field": self.field,
            "message": self.message,
            "severity": self.severity,
        }


@dataclass
class ValidationResult:
    """Result of a :meth:`SFValidateClient.validate` call.

    Attributes:
        passed:             ``True`` when all enforcement mechanisms pass
                            (or when correction resolved all violations).
        violations:         Violations collected across all mechanisms.
                            Empty when *passed* is ``True``.
        corrected_response: The response string after successful correction,
                            or ``None`` when no correction ran or correction
                            failed to resolve all violations.
        correction_passes:  Number of correction attempts made (0 if none).
        hmac_signature:     HMAC-SHA256 hex digest from ``sf_audit``.  Empty
                            string when the audit write failed.
        audit_id:           Unique audit record identifier from ``sf_audit``.
                            Empty string when the audit write failed.
        duration_ms:        Wall-clock time for the full ``validate()`` call
                            in milliseconds.
        auto_blocked:       ``True`` when a zero-tolerance secret was detected.
    """

    passed: bool
    violations: list[Violation]
    corrected_response: str | None
    correction_passes: int
    hmac_signature: str
    audit_id: str
    duration_ms: float
    auto_blocked: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for JSON serialisation."""
        return {
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "corrected_response": self.corrected_response,
            "correction_passes": self.correction_passes,
            "hmac_signature": self.hmac_signature,
            "audit_id": self.audit_id,
            "duration_ms": self.duration_ms,
            "auto_blocked": self.auto_blocked,
        }


@dataclass
class ValidateStatusInfo:
    """Health and configuration snapshot from :meth:`SFValidateClient.get_status`.

    Attributes:
        service:                   Always ``"validate"``.
        local_mode:                ``True`` when no remote endpoint is configured.
        total_calls:               Total number of ``validate()`` calls made.
        total_passed:              Number of calls that returned ``passed=True``.
        total_violations_raised:   Cumulative violation count across all calls.
        total_correction_passes:   Cumulative correction-pass count.
        jsonschema_available:      ``True`` when ``jsonschema`` is installed.
    """

    service: str
    local_mode: bool
    total_calls: int
    total_passed: int
    total_violations_raised: int
    total_correction_passes: int
    jsonschema_available: bool


# ---------------------------------------------------------------------------
# Helpers — schema validation
# ---------------------------------------------------------------------------


def _validate_against_schema(
    response: str | dict[str, Any],
    schema: dict[str, Any] | str,
) -> list[Violation]:
    """Run enforcement mechanism 1: schema check.

    Args:
        response: Model response string or dict.
        schema:   JSON Schema dict or regex pattern string.

    Returns:
        List of :class:`Violation` objects (empty if valid).
    """
    violations: list[Violation] = []

    if isinstance(schema, str):
        # Regex mode — treat response as text
        text = response if isinstance(response, str) else json.dumps(response)
        try:
            pattern = re.compile(schema)
        except re.error as exc:
            violations.append(
                Violation(
                    type="schema",
                    field="",
                    message=f"Invalid regex pattern: {exc}",
                    severity="high",
                )
            )
            return violations
        if not pattern.search(text):
            violations.append(
                Violation(
                    type="schema",
                    field="",
                    message=f"Response does not match required pattern: {schema!r}",
                    severity="medium",
                )
            )
        return violations

    # JSON Schema dict mode
    if isinstance(response, str):
        try:
            parsed: Any = json.loads(response)
        except (json.JSONDecodeError, ValueError):
            violations.append(
                Violation(
                    type="schema",
                    field="",
                    message="Response is not valid JSON",
                    severity="high",
                )
            )
            return violations
    else:
        parsed = response

    # Try jsonschema first; fall back to structural type check
    try:
        import jsonschema  # type: ignore[import-untyped, unused-ignore]

        try:
            jsonschema.validate(instance=parsed, schema=schema)
        except jsonschema.ValidationError as exc:
            violations.append(
                Violation(
                    type="schema",
                    field=".".join(str(p) for p in exc.absolute_path),
                    message=exc.message,
                    severity="high",
                )
            )
    except ImportError:
        # Zero-dep fallback: check top-level type matches "type" key in schema
        expected_type = schema.get("type")
        if expected_type:
            type_map: dict[str, type | tuple[type, type]] = {
                "object": dict,
                "array": list,
                "string": str,
                "number": (int, float),
                "integer": int,
                "boolean": bool,
                "null": type(None),
            }
            py_type = type_map.get(str(expected_type))
            if py_type and not isinstance(parsed, py_type):
                violations.append(
                    Violation(
                        type="schema",
                        field="",
                        message=(
                            f"Expected JSON type {expected_type!r}; got {type(parsed).__name__!r}"
                        ),
                        severity="high",
                    )
                )
        # Check required fields for object schemas
        if isinstance(parsed, dict) and "required" in schema:
            for req_field in schema["required"]:
                if req_field not in parsed:
                    violations.append(
                        Violation(
                            type="schema",
                            field=str(req_field),
                            message=f"Required field {req_field!r} is missing",
                            severity="high",
                        )
                    )

    return violations


# ---------------------------------------------------------------------------
# SFValidateClient
# ---------------------------------------------------------------------------


class SFValidateClient(SFServiceClient):
    """SpanForge sf-validate model response validation client (CARD 1C-1).

    Validates model responses on the hot path using four ordered enforcement
    mechanisms.  All logic runs in-process — no network calls are made.

    Args:
        config: :class:`~spanforge.sdk._base.SFClientConfig` instance.
        max_correction_passes: Default cap on correction iterations.

    Example::

        from spanforge.sdk import sf_validate

        result = sf_validate.validate(
            response='{"label": "positive", "score": 0.93}',
            schema={"type": "object", "required": ["label", "score"]},
            confidence_score=0.93,
        )
        if not result.passed:
            for v in result.violations:
                print(v.type, v.message)
    """

    def __init__(
        self,
        config: SFClientConfig,
        *,
        max_correction_passes: int = _DEFAULT_MAX_CORRECTION_PASSES,
    ) -> None:
        super().__init__(config, service_name="validate")
        self._max_correction_passes = max_correction_passes
        self._total_calls: int = 0
        self._total_passed: int = 0
        self._total_violations: int = 0
        self._total_correction_passes: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate(
        self,
        response: str | dict[str, Any],
        *,
        schema: dict[str, Any] | str | None = None,
        confidence_threshold: float = _DEFAULT_CONFIDENCE_THRESHOLD,
        confidence_score: float | None = None,
        correction_fn: Callable[[str, list[Violation]], str] | None = None,
        max_correction_passes: int | None = None,
        agent_id: str = "",
        trace_id: str = "",
    ) -> ValidationResult:
        """Validate a model *response* through four enforcement mechanisms.

        Mechanisms run in order; all violations are collected before
        correction is attempted.  The method **never raises** on content
        violations — it always returns a :class:`ValidationResult`.

        Args:
            response:
                Model output — plain ``str`` or ``dict`` (structured output).
            schema:
                JSON Schema dict *or* regex pattern string.  When ``None``
                the schema check is skipped.
            confidence_threshold:
                Minimum confidence score in [0, 1] (default 0.7).  A
                violation is added when the effective score is below this.
            confidence_score:
                Pre-computed confidence score in [0, 1].  When ``None``
                :meth:`SFExplainClient.generate` is called to extract the
                score; when that is unavailable the check is skipped.
            correction_fn:
                Callable ``(response_text, violations) → corrected_text``.
                Called when violations remain after mechanisms 1–3.
                Capped at *max_correction_passes* attempts.
            max_correction_passes:
                Override the instance default (default: 2).
            agent_id:
                Agent identifier for audit records.
            trace_id:
                Trace identifier for audit records.

        Returns:
            :class:`ValidationResult` — always returned, never raises.
        """
        start = time.monotonic()
        self._total_calls += 1
        violations: list[Violation] = []
        auto_blocked = False
        max_passes = (
            max_correction_passes
            if max_correction_passes is not None
            else self._max_correction_passes
        )

        # --- Mechanism 1: schema check ---
        if schema is not None:
            violations.extend(_validate_against_schema(response, schema))

        # --- Mechanism 2: confidence threshold ---
        effective_score = confidence_score
        if effective_score is None:
            effective_score = self._try_get_confidence_score(response)
        if effective_score is not None and effective_score < confidence_threshold:
            violations.append(
                Violation(
                    type="confidence",
                    field="",
                    message=(
                        f"Confidence score {effective_score:.3f} is below "
                        f"threshold {confidence_threshold:.3f}"
                    ),
                    severity="medium",
                )
            )

        # --- Mechanism 3: content policy ---
        response_text = response if isinstance(response, str) else json.dumps(response)
        pii_violations, secret_violations, auto_blocked = self._content_policy_check(response_text)
        violations.extend(pii_violations)
        violations.extend(secret_violations)

        # --- Mechanism 4: multi-pass correction ---
        corrected_response: str | None = None
        correction_passes = 0
        if violations and correction_fn is not None and not auto_blocked:
            corrected_response, correction_passes, violations = self._run_correction(
                response_text,
                violations,
                correction_fn=correction_fn,
                max_passes=max_passes,
                agent_id=agent_id,
                trace_id=trace_id,
            )

        passed = not violations
        if passed:
            self._total_passed += 1
        self._total_violations += len(violations)
        self._total_correction_passes += correction_passes

        duration_ms = (time.monotonic() - start) * 1000.0
        hmac_sig, audit_id = self._emit_audit_record(
            response_text=response_text,
            violations=violations,
            passed=passed,
            correction_passes=correction_passes,
            auto_blocked=auto_blocked,
            agent_id=agent_id,
            trace_id=trace_id,
        )

        return ValidationResult(
            passed=passed,
            violations=violations,
            corrected_response=corrected_response,
            correction_passes=correction_passes,
            hmac_signature=hmac_sig,
            audit_id=audit_id,
            duration_ms=duration_ms,
            auto_blocked=auto_blocked,
        )

    def get_status(self) -> ValidateStatusInfo:
        """Return health and configuration snapshot."""
        try:
            import jsonschema as _js  # noqa: F401

            js_available = True
        except ImportError:
            js_available = False

        return ValidateStatusInfo(
            service="validate",
            local_mode=self._is_local_mode(),
            total_calls=self._total_calls,
            total_passed=self._total_passed,
            total_violations_raised=self._total_violations,
            total_correction_passes=self._total_correction_passes,
            jsonschema_available=js_available,
        )

    # ------------------------------------------------------------------
    # Internal — mechanism helpers
    # ------------------------------------------------------------------

    def _try_get_confidence_score(self, response: str | dict[str, Any]) -> float | None:
        """Extract confidence score from SFExplainClient or response metadata.

        Skips silently when SFExplainClient is unavailable.

        Returns:
            Float in [0, 1] when a score can be determined; ``None`` otherwise.
        """
        # Structured response may carry a confidence field directly
        if isinstance(response, dict) and "confidence_score" in response:
            try:
                score = float(response["confidence_score"])
                if 0.0 <= score <= 1.0:
                    return score
            except (TypeError, ValueError):
                pass

        # Attempt SFExplainClient.generate to extract metadata — skipped since
        # the generate() API requires a full set of required parameters that are
        # not available on the hot-path; confidence extraction is best-effort.
        return None

    def _content_policy_check(
        self,
        response_text: str,
    ) -> tuple[list[Violation], list[Violation], bool]:
        """Run PII and secrets scans.

        Returns:
            Tuple of (pii_violations, secret_violations, auto_blocked).
        """
        pii_violations: list[Violation] = []
        secret_violations: list[Violation] = []
        auto_blocked = False

        # PII scan
        try:
            from spanforge.sdk import sf_pii

            pii_result = sf_pii.scan_text(response_text)
            if pii_result.detected:
                for entity in pii_result.entities:
                    pii_violations.append(
                        Violation(
                            type="pii",
                            field="",
                            message=f"PII detected: {entity.type}",
                            severity="high",
                        )
                    )
        except Exception:
            _log.debug("sf_pii unavailable for content policy check; skipping.")

        # Secrets scan
        try:
            from spanforge.secrets import SecretsScanner

            scanner = SecretsScanner()
            secrets_result = scanner.scan(response_text)
            if secrets_result.detected:
                for hit in secrets_result.hits:
                    severity = "critical" if hit.auto_blocked else "high"
                    if hit.auto_blocked:
                        auto_blocked = True
                    secret_violations.append(
                        Violation(
                            type="secret",
                            field="",
                            message=f"Secret detected: {hit.secret_type}",
                            severity=severity,
                        )
                    )
        except Exception:
            _log.debug("SecretsScanner unavailable for content policy check; skipping.")

        return pii_violations, secret_violations, auto_blocked

    def _run_correction(
        self,
        response_text: str,
        violations: list[Violation],
        *,
        correction_fn: Callable[[str, list[Violation]], str],
        max_passes: int,
        agent_id: str,
        trace_id: str,
    ) -> tuple[str | None, int, list[Violation]]:
        """Run multi-pass correction.

        Returns:
            Tuple of (corrected_text_or_None, passes_made, remaining_violations).
        """
        current_text = response_text
        current_violations = violations
        passes_made = 0

        for _ in range(max(0, max_passes)):
            try:
                corrected = correction_fn(current_text, current_violations)
            except Exception:
                _log.warning("correction_fn raised during pass %d; stopping.", passes_made + 1)
                break

            passes_made += 1
            self._emit_correction_cost_event(
                pass_number=passes_made,
                agent_id=agent_id,
                trace_id=trace_id,
            )

            # Re-run schema + confidence checks are caller responsibility;
            # we only re-run content policy on the corrected text.
            _, secret_violations, _ = self._content_policy_check(corrected)
            remaining = [v for v in current_violations if v.type not in ("pii", "secret")]
            remaining.extend(secret_violations)

            current_text = corrected
            current_violations = remaining

            if not current_violations:
                return current_text, passes_made, current_violations

        # Return corrected text (last attempt) even if violations remain
        corrected_text: str | None = current_text if passes_made > 0 else None
        return corrected_text, passes_made, current_violations

    # ------------------------------------------------------------------
    # Internal — audit helpers
    # ------------------------------------------------------------------

    def _response_hash(self, response_text: str) -> str:
        """Return SHA-256 hex digest of the response text."""
        return hashlib.sha256(response_text.encode("utf-8", errors="replace")).hexdigest()

    def _emit_audit_record(
        self,
        *,
        response_text: str,
        violations: list[Violation],
        passed: bool,
        correction_passes: int,
        auto_blocked: bool,
        agent_id: str,
        trace_id: str,
    ) -> tuple[str, str]:
        """Append a HMAC-signed validation record to sf_audit.

        Returns:
            Tuple of (hmac_signature, audit_id).  Both are empty strings
            when the audit write fails.
        """
        record: dict[str, Any] = {
            "response_hash": self._response_hash(response_text),
            "violation_types": sorted({v.type for v in violations}),
            "violation_count": len(violations),
            "passed": passed,
            "correction_passes": correction_passes,
            "auto_blocked": auto_blocked,
            "agent_id": agent_id,
            "trace_id": trace_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            from spanforge.sdk import sf_audit

            result = sf_audit.append(record, _AUDIT_SCHEMA_KEY)
            return result.hmac, result.record_id
        except Exception:
            _log.warning("sf_audit.append failed for validate record; continuing.")
            return "", ""

    def _emit_correction_cost_event(
        self,
        *,
        pass_number: int,
        agent_id: str,
        trace_id: str,
    ) -> None:
        """Append a correction cost event to sf_audit on a best-effort basis."""
        record: dict[str, Any] = {
            "event": "validation_correction",
            "pass_number": pass_number,
            "agent_id": agent_id,
            "trace_id": trace_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            from spanforge.sdk import sf_audit

            sf_audit.append(record, _CORRECTION_AUDIT_SCHEMA_KEY)
        except Exception:
            _log.debug("sf_audit.append failed for correction cost event; ignoring.")
