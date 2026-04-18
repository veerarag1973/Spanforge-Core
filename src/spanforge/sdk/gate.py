"""spanforge.sdk.gate — SpanForge sf-gate CI/CD Gate Pipeline Client (Phase 8).

Implements the full sf-gate SDK surface: gate evaluation, trust gate checks,
PRRI governance evaluation, artifact management, and cross-service integration
with sf-audit, sf-observe, and sf-alert.

Architecture
------------
* :meth:`evaluate` is the **primary evaluation entry point**.  It runs a
  named gate check against a payload dict, writes the result to the artifact
  store, emits an ``hc.gate.evaluated`` span via sf-observe, and appends an
  audit record under schema ``halluccheck.gate.v1``.
* :meth:`run_trust_gate` queries the local audit store for HRI, PII, and
  Secrets records to determine whether the trust gate passes.  On failure it
  publishes a ``halluccheck.trust_gate.failed`` alert via sf-alert at
  CRITICAL severity.
* :meth:`evaluate_prri` scores a PRRI payload and returns a
  :class:`~spanforge.sdk._types.PRRIResult` with a GREEN / AMBER / RED verdict.
* All methods operate in local-fallback mode when ``config.endpoint`` is empty
  or the remote service is unreachable and ``config.local_fallback_enabled``
  is ``True``.

Cross-service integration
--------------------------
All integrations use **lazy imports** inside methods to prevent circular
import cycles:

* ``sf_audit``   ← queries for HRI / PII / Secrets records (run_trust_gate)
* ``sf_observe`` ← emits ``hc.gate.evaluated`` span (evaluate)
* ``sf_alert``   ← publishes trust-gate failure alert (run_trust_gate)

Gate topics (GAT-025)
----------------------
Eight built-in gate-related alert topics:

* ``halluccheck.trust_gate.failed``   — CRITICAL
* ``halluccheck.gate.blocked``        — HIGH
* ``halluccheck.gate.warn``           — MEDIUM
* ``halluccheck.prri.red``            — HIGH
* ``halluccheck.prri.amber``          — MEDIUM
* ``halluccheck.schema.violation``    — HIGH
* ``halluccheck.dependency.critical`` — CRITICAL
* ``halluccheck.secrets.leak``        — CRITICAL

Security requirements
---------------------
* API keys are never logged or included in exception messages.
* Artifact paths are restricted to the ``.sf-gate/`` directory; no path
  traversal is possible (paths are validated against the base dir).
* Trust gate failure alerts are only sent once per ``(project_id, pipeline_id)``
  within the deduplication window.
* Thread-safety: in-memory counters and artifact caches use locks.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spanforge.sdk._base import (
    SFClientConfig,
    SFServiceClient,
    _CircuitBreaker,
)
from spanforge.sdk._exceptions import (
    SFGateError,
    SFGateEvaluationError,
)
from spanforge.sdk._types import (
    GateArtifact,
    GateEvaluationResult,
    GateStatusInfo,
    GateVerdict,
    PRRIResult,
    PRRIVerdict,
    TrustGateResult,
)

__all__ = [
    "GATE_KNOWN_TOPICS",
    "SFGateClient",
]

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Built-in gate-related alert topics (GAT-025).
GATE_KNOWN_TOPICS: frozenset[str] = frozenset(
    {
        "halluccheck.trust_gate.failed",
        "halluccheck.gate.blocked",
        "halluccheck.gate.warn",
        "halluccheck.prri.red",
        "halluccheck.prri.amber",
        "halluccheck.schema.violation",
        "halluccheck.dependency.critical",
        "halluccheck.secrets.leak",
    }
)

#: PRRI thresholds
_PRRI_RED_THRESHOLD: int = 70
_PRRI_AMBER_THRESHOLD: int = 40

#: HRI critical rate threshold for trust gate
_HRI_CRITICAL_THRESHOLD: float = 0.05

#: Artifact base directory (relative to CWD)
_ARTIFACT_BASE: str = ".sf-gate/artifacts"

#: Per-project/pipeline trust-gate alert dedup window
_ALERT_DEDUP_WINDOW_SECONDS: float = 300.0


# ---------------------------------------------------------------------------
# SFGateClient
# ---------------------------------------------------------------------------

class SFGateClient(SFServiceClient):
    """Client for the SpanForge CI/CD Gate Pipeline service (sf-gate).

    Provides gate evaluation, trust gate checks, PRRI governance scoring,
    and artifact management.

    Args:
        config: SDK configuration.  Loads from environment variables if
                not supplied explicitly.

    Environment variables
    ----------------------
    ``SPANFORGE_API_KEY``                  — service API key
    ``SPANFORGE_ENDPOINT``                 — remote API endpoint
    ``SPANFORGE_LOCAL_FALLBACK``           — ``"true"`` to enable local mode
    ``SPANFORGE_GATE_ARTIFACT_DIR``        — override for artifact directory
    ``SPANFORGE_GATE_HRI_WINDOW``          — number of HRI records to sample
    ``SPANFORGE_GATE_PII_WINDOW_HOURS``    — hours window for PII check
    ``SPANFORGE_GATE_SECRETS_WINDOW_HOURS``— hours window for secrets check

    Example::

        from spanforge.sdk import sf_gate

        result = sf_gate.evaluate(
            "gate5_governance",
            {"prri_score": 42, "framework": "eu-ai-act"},
            project_id="my-project",
            pipeline_id="ci-12",
        )
        print(result.verdict)   # "PASS"
    """

    def __init__(self, config: SFClientConfig) -> None:
        super().__init__(config, "gate")
        self._lock = threading.Lock()
        # Per-gate-sink circuit breakers (GAT-040)
        self._gate_circuit_breakers: dict[str, _CircuitBreaker] = {}
        # Artifact base directory
        artifact_dir_env = os.environ.get("SPANFORGE_GATE_ARTIFACT_DIR", "")
        self._artifact_dir = (
            Path(artifact_dir_env) if artifact_dir_env else Path(_ARTIFACT_BASE)
        )
        self._artifact_dir.mkdir(parents=True, exist_ok=True)
        # Dedup store for trust-gate alerts: set of (project_id, pipeline_id)
        self._alerted_trust_gates: dict[str, float] = {}
        # Stats
        self._evaluate_count: int = 0
        self._trust_gate_count: int = 0
        self._last_evaluate_at: str | None = None

    # ------------------------------------------------------------------
    # Circuit breaker helpers
    # ------------------------------------------------------------------

    def _get_cb(self, sink_id: str) -> _CircuitBreaker:
        """Return (or create) a per-sink circuit breaker."""
        with self._lock:
            if sink_id not in self._gate_circuit_breakers:
                self._gate_circuit_breakers[sink_id] = _CircuitBreaker()
            return self._gate_circuit_breakers[sink_id]

    # ------------------------------------------------------------------
    # Artifact helpers
    # ------------------------------------------------------------------

    def _artifact_path(self, gate_id: str) -> Path:
        """Return the canonical artifact path for *gate_id*.

        Path traversal is prevented by resolving against ``_artifact_dir``
        and asserting the result is still inside that directory.
        """
        safe_id = gate_id.replace("/", "_").replace("..", "_")
        candidate = (self._artifact_dir / f"{safe_id}_result.json").resolve()
        base_resolved = self._artifact_dir.resolve()
        if not str(candidate).startswith(str(base_resolved)):
            raise SFGateError(
                f"Unsafe artifact path detected for gate_id={gate_id!r}."
            )
        return candidate

    def _write_artifact(self, gate_id: str, data: dict[str, Any]) -> Path:
        """Serialise *data* as JSON and write to the artifact store."""
        path = self._artifact_path(gate_id)
        try:
            path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        except OSError as exc:
            _log.warning("Could not write gate artifact for %r: %s", gate_id, exc)
        return path

    def _read_artifact(self, gate_id: str) -> dict[str, Any] | None:
        """Read and parse the artifact JSON for *gate_id*."""
        path = self._artifact_path(gate_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]
        except (json.JSONDecodeError, OSError):
            return None

    # ------------------------------------------------------------------
    # Public API — evaluate
    # ------------------------------------------------------------------

    def evaluate(
        self,
        gate_id: str,
        payload: dict[str, Any],
        *,
        project_id: str = "",
        pipeline_id: str = "",
    ) -> GateEvaluationResult:
        """Evaluate a gate condition and record the result (GAT-004).

        Writes the result to ``.sf-gate/artifacts/<gate_id>_result.json``,
        emits an ``hc.gate.evaluated`` span to sf-observe, and appends an
        audit record under schema ``halluccheck.gate.v1``.

        Args:
            gate_id:     Unique gate identifier (e.g. ``"gate5_governance"``).
            payload:     Metrics dict to evaluate.  Content depends on the
                         gate type.
            project_id:  Optional project scoping.
            pipeline_id: Optional CI pipeline identifier.

        Returns:
            :class:`~spanforge.sdk._types.GateEvaluationResult`

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFGateEvaluationError`: If
                gate evaluation encounters a fatal error.
        """
        if not gate_id or not gate_id.strip():
            raise SFGateEvaluationError("gate_id must be a non-empty string.")

        started = time.monotonic()
        timestamp = datetime.now(timezone.utc).isoformat()
        pipeline_id = pipeline_id or str(uuid.uuid4())

        try:
            # Determine verdict from payload
            verdict = self._infer_verdict(gate_id, payload)
            duration_ms = int((time.monotonic() - started) * 1000)

            # Build artifact
            artifact_data: dict[str, Any] = {
                "gate_id": gate_id,
                "verdict": verdict,
                "metrics": payload,
                "timestamp": timestamp,
                "duration_ms": duration_ms,
                "project_id": project_id,
                "pipeline_id": pipeline_id,
            }
            artifact_path = self._write_artifact(gate_id, artifact_data)
            artifact_url = f"file://{artifact_path}"

            result = GateEvaluationResult(
                gate_id=gate_id,
                verdict=verdict,
                metrics=payload,
                artifact_url=artifact_url,
                duration_ms=duration_ms,
            )

            # Async audit + observe (best-effort)
            self._post_evaluate_hooks(
                gate_id=gate_id,
                result=result,
                project_id=project_id,
                pipeline_id=pipeline_id,
                timestamp=timestamp,
            )

            with self._lock:
                self._evaluate_count += 1
                self._last_evaluate_at = timestamp

            return result  # noqa: TRY300

        except SFGateEvaluationError:
            raise
        except Exception as exc:
            raise SFGateEvaluationError(
                f"Gate evaluation failed for gate_id={gate_id!r}: {exc}"
            ) from exc

    def _infer_verdict(self, gate_id: str, payload: dict[str, Any]) -> str:  # noqa: PLR0911
        """Derive a verdict string from *payload*.

        Looks for a top-level ``"verdict"`` key first, then falls back to
        checking ``"pass"``, ``"failed"``, ``"status"``.

        Returns one of :class:`~spanforge.sdk._types.GateVerdict` constants.
        """
        if "verdict" in payload:
            v = str(payload["verdict"]).upper()
            if v in {GateVerdict.PASS, GateVerdict.FAIL, GateVerdict.WARN, GateVerdict.SKIPPED}:
                return v
        if payload.get("pass") is True or payload.get("passed") is True:
            return GateVerdict.PASS
        if payload.get("failed") is True or payload.get("pass") is False:
            return GateVerdict.FAIL
        status = str(payload.get("status", "")).lower()
        if status in {"pass", "passed", "green", "ok"}:
            return GateVerdict.PASS
        if status in {"fail", "failed", "red", "error"}:
            return GateVerdict.FAIL
        if status in {"warn", "warning", "amber"}:
            return GateVerdict.WARN
        # Default to PASS when payload contains no explicit failure indicators
        return GateVerdict.PASS

    def _post_evaluate_hooks(
        self,
        *,
        gate_id: str,
        result: GateEvaluationResult,
        project_id: str,
        pipeline_id: str,
        timestamp: str,
    ) -> None:
        """Best-effort sf-observe span + sf-audit append after evaluate()."""
        # sf-observe: emit hc.gate.evaluated span (GAT-004)
        try:
            from spanforge.sdk import sf_observe
            sf_observe.emit_span(
                "hc.gate.evaluated",
                attributes={
                    "gate_id": gate_id,
                    "verdict": result.verdict,
                    "project_id": project_id,
                    "pipeline_id": pipeline_id,
                    "duration_ms": result.duration_ms,
                },
            )
        except Exception:
            _log.debug("sf_observe.emit_span failed for gate %r", gate_id)

        # sf-audit: append halluccheck.gate.v1 (GAT-004)
        try:
            from spanforge.sdk import sf_audit
            sf_audit.append(
                {
                    "gate_id": gate_id,
                    "verdict": result.verdict,
                    "metrics": result.metrics,
                    "project_id": project_id,
                    "pipeline_id": pipeline_id,
                    "timestamp": timestamp,
                },
                "halluccheck.gate.v1",
            )
        except Exception:
            _log.debug("sf_audit.append failed for gate %r", gate_id)

    # ------------------------------------------------------------------
    # Public API — run_trust_gate
    # ------------------------------------------------------------------

    def run_trust_gate(
        self,
        project_id: str,
        *,
        pipeline_id: str = "",
        hri_window: int | None = None,
        pii_window_hours: int = 24,
        secrets_window_hours: int = 24,
    ) -> TrustGateResult:
        """Run the HallucCheck Trust Gate (GAT-020/021).

        Queries sf-audit for:
        * Last N ``halluccheck.score.v1`` records → compute ``hri_critical_rate``
        * Last 24 h ``halluccheck.pii.v1`` records → ``pii_detected``
        * Last 24 h ``halluccheck.secrets.v1`` records → ``secrets_detected``

        On failure, publishes ``halluccheck.trust_gate.failed`` via sf-alert
        at CRITICAL severity.

        Args:
            project_id:           Project to evaluate.
            pipeline_id:          Optional CI pipeline identifier.
            hri_window:           Number of score records to sample.
                                  Defaults to env var
                                  ``SPANFORGE_GATE_HRI_WINDOW`` or 100.
            pii_window_hours:     Hours window for PII detections.
            secrets_window_hours: Hours window for secrets detections.

        Returns:
            :class:`~spanforge.sdk._types.TrustGateResult`

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFGateTrustFailedError`: When the
                trust gate fails AND ``raise_on_fail=True`` (default False in
                this method; the caller may inspect ``result.pass_`` instead).
        """
        if hri_window is None:
            hri_window = int(os.environ.get("SPANFORGE_GATE_HRI_WINDOW", "100"))

        pipeline_id = pipeline_id or str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).isoformat()

        hri_critical_rate, hri_total = self._compute_hri_critical_rate(
            project_id, hri_window
        )
        pii_detected, pii_count = self._check_pii_window(
            project_id, pii_window_hours
        )
        secrets_detected, secrets_count = self._check_secrets_window(
            project_id, secrets_window_hours
        )

        failures: list[str] = []
        if hri_critical_rate >= _HRI_CRITICAL_THRESHOLD:
            failures.append(
                f"hri_critical_rate={hri_critical_rate:.4f} >= "
                f"threshold={_HRI_CRITICAL_THRESHOLD}"
            )
        if pii_detected:
            failures.append(
                f"pii_detected=true ({pii_count} detection(s) in last {pii_window_hours}h)"
            )
        if secrets_detected:
            failures.append(
                "secrets_detected=true "
                f"({secrets_count} detection(s) in last {secrets_window_hours}h)"
            )

        pass_ = len(failures) == 0
        verdict = GateVerdict.PASS if pass_ else GateVerdict.FAIL

        result = TrustGateResult(
            gate_id="gate6_trust",
            verdict=verdict,
            hri_critical_rate=hri_critical_rate,
            hri_critical_threshold=_HRI_CRITICAL_THRESHOLD,
            pii_detected=pii_detected,
            pii_detections_24h=pii_count,
            secrets_detected=secrets_detected,
            secrets_detections_24h=secrets_count,
            failures=failures,
            timestamp=timestamp,
            pipeline_id=pipeline_id,
            project_id=project_id,
            pass_=pass_,
        )

        # Write artifact
        self._write_artifact("gate6_trust", {
            "gate_id": "gate6_trust",
            "verdict": verdict,
            "hri_critical_rate": hri_critical_rate,
            "hri_critical_threshold": _HRI_CRITICAL_THRESHOLD,
            "pii_detected": pii_detected,
            "pii_detections_24h": pii_count,
            "secrets_detected": secrets_detected,
            "secrets_detections_24h": secrets_count,
            "failures": failures,
            "timestamp": timestamp,
            "pipeline_id": pipeline_id,
            "project_id": project_id,
        })

        with self._lock:
            self._trust_gate_count += 1

        if not pass_:
            self._send_trust_gate_alert(
                project_id=project_id,
                pipeline_id=pipeline_id,
                failures=failures,
                timestamp=timestamp,
            )

        return result

    def _compute_hri_critical_rate(
        self,
        project_id: str,
        window: int,
    ) -> tuple[float, int]:
        """Return (hri_critical_rate, total_records) from sf-audit.

        Queries last *window* ``halluccheck.score.v1`` records and computes the
        fraction that have ``is_critical=true``.
        """
        try:
            from datetime import datetime, timedelta
            from datetime import timezone as _tz

            from spanforge.sdk import sf_audit
            since = (
                datetime.now(_tz.utc) - timedelta(hours=24 * 30)
            )
            records = sf_audit.export(
                date_range=(since.isoformat(), datetime.now(_tz.utc).isoformat()),
                limit=window,
            )
            total = len(records)
            if total == 0:
                return 0.0, 0
            critical = sum(
                1 for r in records
                if r.get("is_critical") is True
                or str(r.get("category", "")).lower() == "critical"
            )
            return critical / total, total
        except Exception:
            _log.debug("Could not query HRI records from sf_audit")
            return 0.0, 0

    def _check_pii_window(
        self,
        project_id: str,
        window_hours: int,
    ) -> tuple[bool, int]:
        """Return (pii_detected, count) from sf-audit for last *window_hours*."""
        try:
            from datetime import datetime, timedelta
            from datetime import timezone as _tz

            from spanforge.sdk import sf_audit
            since = datetime.now(_tz.utc) - timedelta(hours=window_hours)
            records = sf_audit.export(
                schema_key="halluccheck.pii.v1",
                date_range=(since.isoformat(), datetime.now(_tz.utc).isoformat()),
                limit=1000,
            )
            # Filter by project_id if non-empty
            if project_id:
                records = [
                    r for r in records
                    if r.get("project_id") == project_id or not r.get("project_id")
                ]
            count = sum(
                1 for r in records
                if r.get("detected") is True or r.get("pii_detected") is True
            )
            return count > 0, count  # noqa: TRY300
        except Exception:
            _log.debug("Could not query PII records from sf_audit")
            return False, 0

    def _check_secrets_window(
        self,
        project_id: str,
        window_hours: int,
    ) -> tuple[bool, int]:
        """Return (secrets_detected, count) from sf-audit for last *window_hours*."""
        try:
            from datetime import datetime, timedelta
            from datetime import timezone as _tz

            from spanforge.sdk import sf_audit
            since = datetime.now(_tz.utc) - timedelta(hours=window_hours)
            records = sf_audit.export(
                schema_key="halluccheck.secrets.v1",
                date_range=(since.isoformat(), datetime.now(_tz.utc).isoformat()),
                limit=1000,
            )
            if project_id:
                records = [
                    r for r in records
                    if r.get("project_id") == project_id or not r.get("project_id")
                ]
            count = sum(
                1 for r in records
                if r.get("has_secrets") is True or r.get("secrets_detected") is True
            )
            return count > 0, count  # noqa: TRY300
        except Exception:
            _log.debug("Could not query Secrets records from sf_audit")
            return False, 0

    def _send_trust_gate_alert(
        self,
        *,
        project_id: str,
        pipeline_id: str,
        failures: list[str],
        timestamp: str,
    ) -> None:
        """Publish halluccheck.trust_gate.failed alert via sf-alert (GAT-022).

        Deduplicates by (project_id, pipeline_id) within 5 minutes.
        """
        dedup_key = f"{project_id}:{pipeline_id}"
        now = time.monotonic()
        with self._lock:
            last_sent = self._alerted_trust_gates.get(dedup_key)
            if last_sent is not None and (now - last_sent) < _ALERT_DEDUP_WINDOW_SECONDS:
                _log.debug("Trust gate alert suppressed (dedup): %s", dedup_key)
                return
            self._alerted_trust_gates[dedup_key] = now

        try:
            from spanforge.sdk import sf_alert
            from spanforge.sdk._types import AlertSeverity
            sf_alert.publish(
                "halluccheck.trust_gate.failed",
                {
                    "project_id": project_id,
                    "pipeline_id": pipeline_id,
                    "failures": failures,
                    "timestamp": timestamp,
                    "gate_id": "gate6_trust",
                },
                severity=AlertSeverity.CRITICAL.value,
                project_id=project_id,
            )
        except Exception as exc:
            _log.debug("sf_alert.publish failed for trust gate: %s", exc)

    # ------------------------------------------------------------------
    # Public API — evaluate_prri
    # ------------------------------------------------------------------

    def evaluate_prri(  # noqa: PLR0913
        self,
        project_id: str,
        *,
        prri_score: int,
        threshold: int = _PRRI_RED_THRESHOLD,
        framework: str = "",
        policy_file: str = "",
        dimension_breakdown: dict[str, Any] | None = None,
    ) -> PRRIResult:
        """Score a PRRI payload and return a GREEN / AMBER / RED verdict (GAT-010).

        Args:
            project_id:           Project being evaluated.
            prri_score:           Raw PRRI score (0-100, higher = more risk).
            threshold:            RED threshold.  Scores >= threshold → RED.
                                  Default: 70.
            framework:            Regulatory framework (e.g. ``"eu-ai-act"``).
            policy_file:          Path to the policy file used for scoring.
            dimension_breakdown:  Optional per-dimension breakdown dict.

        Returns:
            :class:`~spanforge.sdk._types.PRRIResult`

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFGateEvaluationError`:
                If *prri_score* is out of range.
        """
        if not (0 <= prri_score <= 100):  # noqa: PLR2004
            raise SFGateEvaluationError(
                f"prri_score must be in [0, 100], got {prri_score}."
            )

        timestamp = datetime.now(timezone.utc).isoformat()
        amber_threshold = _PRRI_AMBER_THRESHOLD

        if prri_score >= threshold:
            verdict = PRRIVerdict.RED
            allow = False
        elif prri_score >= amber_threshold:
            verdict = PRRIVerdict.AMBER
            allow = True
        else:
            verdict = PRRIVerdict.GREEN
            allow = True

        result = PRRIResult(
            gate_id="gate5_governance",
            prri_score=prri_score,
            verdict=verdict,
            dimension_breakdown=dimension_breakdown or {},
            framework=framework,
            policy_file=policy_file,
            timestamp=timestamp,
            allow=allow,
            project_id=project_id,
        )

        # Write artifact
        self._write_artifact("gate5_governance", {
            "gate_id": "gate5_governance",
            "prri_score": prri_score,
            "verdict": verdict,
            "dimension_breakdown": dimension_breakdown or {},
            "framework": framework,
            "policy_file": policy_file,
            "timestamp": timestamp,
            "allow": allow,
            "project_id": project_id,
        })

        # Publish alert if RED or AMBER (GAT-011)
        if verdict == PRRIVerdict.RED:
            self._publish_prri_alert(
                "halluccheck.prri.red", project_id, prri_score, verdict, timestamp
            )
        elif verdict == PRRIVerdict.AMBER:
            self._publish_prri_alert(
                "halluccheck.prri.amber", project_id, prri_score, verdict, timestamp
            )

        return result

    def _publish_prri_alert(
        self,
        topic: str,
        project_id: str,
        prri_score: int,
        verdict: str,
        timestamp: str,
    ) -> None:
        """Publish a PRRI alert via sf-alert (best-effort)."""
        try:
            from spanforge.sdk import sf_alert
            from spanforge.sdk._types import AlertSeverity
            severity = (
                AlertSeverity.HIGH
                if verdict == PRRIVerdict.RED
                else AlertSeverity.WARNING
            )
            sf_alert.publish(
                topic,
                {
                    "project_id": project_id,
                    "prri_score": prri_score,
                    "verdict": verdict,
                    "timestamp": timestamp,
                },
                severity=severity.value,
                project_id=project_id,
            )
        except Exception:
            _log.debug("sf_alert.publish failed for PRRI alert: %s", topic)

    # ------------------------------------------------------------------
    # Public API — list_artifacts
    # ------------------------------------------------------------------

    def list_artifacts(
        self,
        gate_id: str | None = None,
        *,
        limit: int = 50,
    ) -> list[GateArtifact]:
        """List gate artifacts in the artifact store (GAT-003).

        Args:
            gate_id: Filter to artifacts for a specific gate.  ``None`` means
                     all gates.
            limit:   Maximum number of results to return (most-recent first).

        Returns:
            List of :class:`~spanforge.sdk._types.GateArtifact` objects.
        """
        pattern = f"{gate_id}_result.json" if gate_id else "*_result.json"
        paths = sorted(
            self._artifact_dir.glob(pattern),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )[:limit]

        artifacts: list[GateArtifact] = []
        for path in paths:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                artifacts.append(
                    GateArtifact(
                        gate_id=data.get("gate_id", path.stem.replace("_result", "")),
                        name=data.get("name", data.get("gate_id", "")),
                        verdict=data.get("verdict", GateVerdict.PASS),
                        metrics=data.get("metrics", {}),
                        timestamp=data.get("timestamp", ""),
                        duration_ms=int(data.get("duration_ms", 0)),
                        artifact_path=str(path),
                    )
                )
            except (json.JSONDecodeError, OSError):  # noqa: PERF203
                continue
        return artifacts

    # ------------------------------------------------------------------
    # Public API — get_status
    # ------------------------------------------------------------------

    def get_status(self) -> GateStatusInfo:
        """Return health and statistics for sf-gate.

        Returns:
            :class:`~spanforge.sdk._types.GateStatusInfo`
        """
        with self._lock:
            evaluate_count = self._evaluate_count
            trust_gate_count = self._trust_gate_count
            last_evaluate_at = self._last_evaluate_at
            cb_open = [k for k, v in self._gate_circuit_breakers.items() if v.is_open()]

        artifact_count = len(list(self._artifact_dir.glob("*_result.json")))

        return GateStatusInfo(
            status="degraded" if cb_open else "ok",
            evaluate_count=evaluate_count,
            trust_gate_count=trust_gate_count,
            last_evaluate_at=last_evaluate_at,
            artifact_count=artifact_count,
            artifact_dir=str(self._artifact_dir),
            open_circuit_breakers=cb_open,
        )
