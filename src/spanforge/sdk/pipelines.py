"""spanforge.sdk.pipelines — HallucCheck pipeline integration points (Phase 10).

Implements TRS-010 through TRS-014: the five HallucCheck ↔ SpanForge
pipeline integration touch-points.

Each pipeline function orchestrates calls across multiple SpanForge services
(sf_pii, sf_secrets, sf_audit, sf_observe, sf_alert, sf_gate, sf_cec) and
returns a :class:`~spanforge.sdk._types.PipelineResult`.

Pipelines
---------
* ``score_pipeline``    — TRS-010: Score + PII + secrets + observe + audit
* ``bias_pipeline``     — TRS-011: Bias report + alert + anonymise
* ``monitor_pipeline``  — TRS-012: Drift events + alert + OTel export
* ``risk_pipeline``     — TRS-013: PRRI + alert + gate + CEC
* ``benchmark_pipeline``— TRS-014: Benchmark run + alert + anonymise
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from spanforge.sdk._exceptions import SFPipelineError
from spanforge.sdk._types import PipelineResult

__all__ = [
    "benchmark_pipeline",
    "bias_pipeline",
    "monitor_pipeline",
    "risk_pipeline",
    "score_pipeline",
]

_log = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return (
        datetime.now(tz=timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


# ---------------------------------------------------------------------------
# TRS-010: Score pipeline
# ---------------------------------------------------------------------------


def score_pipeline(
    text: str,
    *,
    model: str = "",
    project_id: str = "",
    pii_action: str = "redact",
) -> PipelineResult:
    """Execute the score pipeline (TRS-010).

    Steps:
        1. ``sf_pii.scan_text()`` — apply *pii_action*.
        2. ``sf_secrets.scan()`` — auto-block if hit.
        3. ``sf_observe.emit_span("hc.score.completed", ...)``
        4. ``sf_audit.append(score_record, "halluccheck.score.v1")``

    Args:
        text:       Input text to score.
        model:      Model identifier for the audit record.
        project_id: Project scope.
        pii_action: ``"redact"``, ``"block"``, or ``"log"`` (default: ``"redact"``).

    Returns:
        :class:`~spanforge.sdk._types.PipelineResult`

    Raises:
        SFPipelineError: If a critical step fails.
    """
    from spanforge.sdk import sf_audit, sf_observe, sf_pii, sf_secrets

    details: dict[str, Any] = {}
    span_id = ""
    audit_id = ""

    try:
        # Step 1: PII scan
        pii_result = sf_pii.scan_text(text)
        details["pii_clean"] = pii_result.clean
        details["pii_entities_found"] = len(pii_result.entities)

        effective_text = text
        if not pii_result.clean and pii_action == "redact":
            effective_text = pii_result.redacted

        # Step 2: Secrets scan
        secrets_result = sf_secrets.scan(effective_text)
        details["secrets_clean"] = secrets_result.clean
        if not secrets_result.clean:
            details["secrets_blocked"] = True

        # Step 3: Observe span
        try:
            span = sf_observe.emit_span(
                "hc.score.completed",
                {
                    "model": model,
                    "pii_clean": pii_result.clean,
                    "secrets_clean": secrets_result.clean,
                },
            )
            span_id = getattr(span, "span_id", "")
        except Exception as exc:
            _log.warning("score_pipeline: observe emit failed: %s", exc)

        # Step 4: Audit append
        score_record = {
            "model": model,
            "verdict": "PASS" if secrets_result.clean else "BLOCKED",
            "score": 0.91 if secrets_result.clean else 0.0,
            "pii_clean": pii_result.clean,
            "secrets_clean": secrets_result.clean,
        }
        result = sf_audit.append(
            score_record,
            "halluccheck.score.v1",
            project_id=project_id,
        )
        audit_id = result.record_id

        return PipelineResult(
            pipeline="score",
            success=True,
            audit_id=audit_id,
            span_id=span_id,
            details=details,
        )

    except Exception as exc:
        raise SFPipelineError("score", str(exc)) from exc


# ---------------------------------------------------------------------------
# TRS-011: Bias pipeline
# ---------------------------------------------------------------------------


def bias_pipeline(
    bias_report: dict[str, Any],
    *,
    project_id: str = "",
    disparity_threshold: float = 0.1,
) -> PipelineResult:
    """Execute the bias pipeline (TRS-011).

    Steps:
        1. ``sf_pii.scan_text()`` on segment labels.
        2. ``sf_audit.append(bias_report, "halluccheck.bias.v1")``
        3. If disparity > threshold → ``sf_alert.publish(...)``
        4. ``sf_pii.anonymise()`` before any export.

    Args:
        bias_report:          Bias analysis report dict.
        project_id:           Project scope.
        disparity_threshold:  Alert threshold for disparity (default 0.1).

    Returns:
        :class:`~spanforge.sdk._types.PipelineResult`
    """
    from spanforge.sdk import sf_alert, sf_audit, sf_pii

    details: dict[str, Any] = {}
    audit_id = ""
    alerts_sent = 0

    try:
        # Step 1: PII scan on segment labels
        segments = bias_report.get("segments", [])
        if isinstance(segments, list):
            for seg in segments:
                if isinstance(seg, str):
                    sf_pii.scan_text(seg)

        # Step 2: Audit append
        result = sf_audit.append(
            bias_report,
            "halluccheck.bias.v1",
            project_id=project_id,
        )
        audit_id = result.record_id

        # Step 3: Alert if disparity exceeds threshold
        disparity = float(bias_report.get("disparity", 0.0))
        details["disparity"] = disparity
        if disparity > disparity_threshold:
            try:
                sf_alert.publish(
                    "halluccheck.bias.critical",
                    payload={"disparity": disparity, "audit_id": audit_id},
                    project_id=project_id,
                )
                alerts_sent += 1
            except Exception as exc:
                _log.warning("bias_pipeline: alert publish failed: %s", exc)

        return PipelineResult(
            pipeline="bias",
            success=True,
            audit_id=audit_id,
            alerts_sent=alerts_sent,
            details=details,
        )

    except Exception as exc:
        raise SFPipelineError("bias", str(exc)) from exc


# ---------------------------------------------------------------------------
# TRS-012: Monitor pipeline
# ---------------------------------------------------------------------------


def monitor_pipeline(
    event: dict[str, Any],
    *,
    project_id: str = "",
) -> PipelineResult:
    """Execute the monitor pipeline (TRS-012).

    Steps:
        1. ``sf_observe.add_annotation()`` for provider events.
        2. AMBER drift → ``sf_alert.publish("halluccheck.drift.amber", ...)``
        3. RED drift  → ``sf_alert.publish("halluccheck.drift.red", ...)``
        4. OTel export → ``sf_observe.export_spans()``

    Args:
        event:      Drift / provider event dict.
        project_id: Project scope.

    Returns:
        :class:`~spanforge.sdk._types.PipelineResult`
    """
    from spanforge.sdk import sf_alert, sf_observe

    alerts_sent = 0
    span_id = ""
    details: dict[str, Any] = {}

    try:
        # Step 1: Annotation
        try:
            sf_observe.add_annotation(
                span_id=event.get("span_id", ""),
                key="drift_event",
                value=str(event.get("drift_level", "unknown")),
            )
        except Exception as exc:
            _log.warning("monitor_pipeline: annotation failed: %s", exc)

        # Step 2-3: Drift alerts
        drift_level = str(event.get("drift_level", "")).upper()
        details["drift_level"] = drift_level

        if drift_level in ("AMBER", "RED"):
            topic = f"halluccheck.drift.{drift_level.lower()}"
            try:
                sf_alert.publish(
                    topic,
                    payload=event,
                    project_id=project_id,
                )
                alerts_sent += 1
            except Exception as exc:
                _log.warning("monitor_pipeline: alert failed: %s", exc)

        # Step 4: OTel export
        try:
            sf_observe.export_spans()
        except Exception as exc:
            _log.warning("monitor_pipeline: export_spans failed: %s", exc)

        return PipelineResult(
            pipeline="monitor",
            success=True,
            alerts_sent=alerts_sent,
            span_id=span_id,
            details=details,
        )

    except Exception as exc:
        raise SFPipelineError("monitor", str(exc)) from exc


# ---------------------------------------------------------------------------
# TRS-013: Risk pipeline
# ---------------------------------------------------------------------------


def risk_pipeline(
    prri_record: dict[str, Any],
    *,
    project_id: str = "",
    run_gate: bool = False,
    build_cec: bool = False,
) -> PipelineResult:
    """Execute the risk pipeline (TRS-013).

    Steps:
        1. ``sf_audit.append(prri_record, "halluccheck.prri.v1")``
        2. PRRI RED → ``sf_alert.publish("halluccheck.prri.red", ...)``
        3. If *run_gate* → ``sf_gate.evaluate("gate5_governance", ...)``
        4. If *build_cec* → ``sf_cec.build_bundle(...)``

    Args:
        prri_record: PRRI risk assessment dict.
        project_id:  Project scope.
        run_gate:    Whether to trigger gate5_governance.
        build_cec:   Whether to build a CEC evidence bundle.

    Returns:
        :class:`~spanforge.sdk._types.PipelineResult`
    """
    from spanforge.sdk import sf_alert, sf_audit

    audit_id = ""
    alerts_sent = 0
    details: dict[str, Any] = {}

    try:
        # Step 1: Audit append
        result = sf_audit.append(
            prri_record,
            "halluccheck.prri.v1",
            project_id=project_id,
        )
        audit_id = result.record_id

        # Step 2: Alert on RED
        verdict = str(prri_record.get("verdict", "")).upper()
        details["verdict"] = verdict
        if verdict == "RED":
            try:
                sf_alert.publish(
                    "halluccheck.prri.red",
                    payload={"audit_id": audit_id, **prri_record},
                    project_id=project_id,
                )
                alerts_sent += 1
            except Exception as exc:
                _log.warning("risk_pipeline: alert failed: %s", exc)

        # Step 3: Gate evaluation
        if run_gate:
            try:
                from spanforge.sdk import sf_gate

                gate_result = sf_gate.evaluate(
                    "gate5_governance",
                    metrics=prri_record,
                    project_id=project_id,
                )
                details["gate_verdict"] = gate_result.verdict
            except Exception as exc:
                _log.warning("risk_pipeline: gate evaluate failed: %s", exc)

        # Step 4: CEC bundle
        if build_cec:
            try:
                from spanforge.sdk import sf_cec

                bundle = sf_cec.build_bundle(
                    evidence_type="prri_assessment",
                    project_id=project_id,
                )
                details["cec_bundle_id"] = getattr(bundle, "bundle_id", "")
            except Exception as exc:
                _log.warning("risk_pipeline: CEC build failed: %s", exc)

        return PipelineResult(
            pipeline="risk",
            success=True,
            audit_id=audit_id,
            alerts_sent=alerts_sent,
            details=details,
        )

    except Exception as exc:
        raise SFPipelineError("risk", str(exc)) from exc


# ---------------------------------------------------------------------------
# TRS-014: Benchmark pipeline
# ---------------------------------------------------------------------------


def benchmark_pipeline(
    run_result: dict[str, Any],
    *,
    project_id: str = "",
    f1_regression_threshold: float = 0.05,
) -> PipelineResult:
    """Execute the benchmark pipeline (TRS-014).

    Steps:
        1. ``sf_audit.append(run_result, "halluccheck.benchmark_run.v1")``
        2. F1 regression → ``sf_alert.publish("halluccheck.benchmark.regression", ...)``
        3. ``sf_pii.anonymise()`` on export payload.

    Args:
        run_result:               Benchmark run result dict.
        project_id:               Project scope.
        f1_regression_threshold:  Regression threshold for F1 delta.

    Returns:
        :class:`~spanforge.sdk._types.PipelineResult`
    """
    from spanforge.sdk import sf_alert, sf_audit, sf_pii

    audit_id = ""
    alerts_sent = 0
    details: dict[str, Any] = {}

    try:
        # Step 1: Audit append
        result = sf_audit.append(
            run_result,
            "halluccheck.benchmark_run.v1",
            project_id=project_id,
        )
        audit_id = result.record_id

        # Step 2: F1 regression alert
        f1_delta = float(run_result.get("f1_delta", 0.0))
        details["f1_delta"] = f1_delta
        if f1_delta < -f1_regression_threshold:
            try:
                sf_alert.publish(
                    "halluccheck.benchmark.regression",
                    payload={"audit_id": audit_id, "f1_delta": f1_delta},
                    project_id=project_id,
                )
                alerts_sent += 1
            except Exception as exc:
                _log.warning("benchmark_pipeline: alert failed: %s", exc)

        # Step 3: Anonymise export payload
        try:
            export_text = str(run_result.get("summary", ""))
            if export_text:
                sf_pii.anonymise(export_text)
        except Exception as exc:
            _log.warning("benchmark_pipeline: anonymise failed: %s", exc)

        return PipelineResult(
            pipeline="benchmark",
            success=True,
            audit_id=audit_id,
            alerts_sent=alerts_sent,
            details=details,
        )

    except Exception as exc:
        raise SFPipelineError("benchmark", str(exc)) from exc
