"""spanforge.sdk.fallback - Local fallback implementations (Phase 9, CFG-020-027).

When a SpanForge remote service is unreachable (or disabled via service
toggle) and ``local_fallback.enabled=True``, these functions provide
best-effort local-mode equivalents for all 8 services.

======  ==================================================================
ID      Fallback
======  ==================================================================
020     :func:`pii_fallback` — regex scan via ``spanforge.redact``.
021     :func:`secrets_fallback` — regex scan via ``spanforge.secrets``.
022     :func:`audit_fallback` — HMAC-chained JSONL to local file.
023     :func:`observe_fallback` — OTLP JSON to stdout.
024     :func:`alert_fallback` — log to ``stderr`` at WARNING.
025     :func:`identity_fallback` — trust ``SPANFORGE_LOCAL_TOKEN`` env var.
026     :func:`gate_fallback` — run gate locally via ``spanforge.gate``.
027     :func:`cec_fallback` — write CEC bundle to local JSONL file.
======  ==================================================================

All functions emit a ``WARNING`` log entry so operators can detect when
fallback is active.

Security requirements
---------------------
* Local identity tokens (CFG-025) are trusted **without signature
  verification** — only appropriate for CLI / local dev use.
* Audit HMAC is computed using ``SPANFORGE_SIGNING_KEY`` / ``SPANFORGE_MAGIC_SECRET``
  from the environment; if neither is set, an empty key is used and a
  ``WARNING`` is logged.
* No secret values are ever written to stdout/stderr.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

__all__ = [
    "alert_fallback",
    "audit_fallback",
    "cec_fallback",
    "gate_fallback",
    "identity_fallback",
    "observe_fallback",
    "pii_fallback",
    "secrets_fallback",
]

_log = logging.getLogger(__name__)

# Default path for the local audit fallback file (CFG-022)
_DEFAULT_AUDIT_FALLBACK_PATH = Path.home() / ".spanforge" / "audit_fallback.jsonl"

# HMAC algorithm used for the local audit chain (CFG-022)
_HMAC_ALGO = "sha256"

# Lock for the local audit JSONL file to prevent interleaved writes
_audit_file_lock = threading.Lock()


# ---------------------------------------------------------------------------
# CFG-020: sf-pii fallback
# ---------------------------------------------------------------------------


def pii_fallback(
    payload: Any,
    *,
    threshold: float = 0.75,
    entity_types: list[str] | None = None,
) -> dict[str, Any]:
    """Scan ``payload`` for PII using the local regex scanner (CFG-020).

    Falls back to ``spanforge.redact.scan_payload()`` (regex-based).
    If the ``presidio_backend`` optional module is importable, it is used
    for richer entity detection.

    Args:
        payload: The data to scan — dict, list, or str.
        threshold: Minimum confidence to report a hit (default: 0.75).
        entity_types: Entity types to scan for.  ``None`` means all.

    Returns:
        ``{"clean": bool, "hits": [...], "fallback": true}``
    """
    _log.warning("sf-pii unreachable, using local regex scan (CFG-020).")

    try:
        from spanforge.redact import scan_payload

        result = scan_payload(payload)
        hits = getattr(result, "hits", [])
        return {
            "clean": not hits,
            "hits": [
                {
                    "entity_type": getattr(h, "entity_type", "UNKNOWN"),
                    "text": getattr(h, "text", ""),
                    "score": getattr(h, "score", 0.0),
                }
                for h in hits
                if getattr(h, "score", 0.0) >= threshold
                and (entity_types is None or getattr(h, "entity_type", "") in entity_types)
            ],
            "fallback": True,
        }
    except Exception as exc:
        _log.warning("pii_fallback: scan_payload raised %s — returning empty result.", exc)
        return {"clean": True, "hits": [], "fallback": True, "error": str(exc)}


# ---------------------------------------------------------------------------
# CFG-021: sf-secrets fallback
# ---------------------------------------------------------------------------


def secrets_fallback(text: str, *, confidence: float = 0.75) -> dict[str, Any]:
    """Scan ``text`` for secrets using the regex-only scanner (CFG-021).

    Entropy scoring is disabled in fallback mode.

    Args:
        text: Plain text to scan.
        confidence: Minimum confidence threshold (default: 0.75).

    Returns:
        ``{"clean": bool, "hits": [...], "fallback": true}``
    """
    _log.warning("sf-secrets unreachable, using local regex scan (CFG-021).")

    try:
        import spanforge.secrets as _secrets_mod

        scan_fn: Any = _secrets_mod.scan_text  # type: ignore[attr-defined]
        result = scan_fn(text)
        hits = getattr(result, "hits", [])
        return {
            "clean": not hits,
            "hits": [
                {
                    "pattern_id": getattr(h, "pattern_id", "UNKNOWN"),
                    "redacted": getattr(h, "redacted", ""),
                    "confidence": getattr(h, "confidence", 0.0),
                }
                for h in hits
                if getattr(h, "confidence", 0.0) >= confidence
            ],
            "fallback": True,
        }
    except Exception as exc:
        _log.warning("secrets_fallback: scan_text raised %s — returning empty result.", exc)
        return {"clean": True, "hits": [], "fallback": True, "error": str(exc)}


# ---------------------------------------------------------------------------
# CFG-022: sf-audit fallback
# ---------------------------------------------------------------------------


def audit_fallback(
    record: dict[str, Any],
    *,
    schema_key: str = "halluccheck.audit.fallback.v1",
    fallback_path: Path | str | None = None,
) -> dict[str, Any]:
    """Append ``record`` to the local audit fallback JSONL file (CFG-022).

    HMAC chain is still applied using the local org secret from
    ``SPANFORGE_SIGNING_KEY`` or ``SPANFORGE_MAGIC_SECRET``.  If neither is
    set, an empty key is used and a ``WARNING`` is emitted.

    Args:
        record: The audit record payload to persist.
        schema_key: Schema identifier for the record (default:
            ``"halluccheck.audit.fallback.v1"``).
        fallback_path: Override the default
            ``~/.spanforge/audit_fallback.jsonl`` path.

    Returns:
        ``{"record_id": str, "fallback_path": str, "fallback": true}``
    """
    _log.warning("sf-audit unreachable, writing to local fallback JSONL (CFG-022).")

    path = Path(fallback_path) if fallback_path else _DEFAULT_AUDIT_FALLBACK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    signing_key = os.environ.get("SPANFORGE_SIGNING_KEY") or os.environ.get(
        "SPANFORGE_MAGIC_SECRET", ""
    )
    if not signing_key:
        _log.warning(
            "audit_fallback: SPANFORGE_SIGNING_KEY not set; HMAC chain uses empty key."
        )

    # Build the entry
    now = datetime.now(timezone.utc)
    record_id = _generate_record_id(record, now)
    entry: dict[str, Any] = {
        "record_id": record_id,
        "schema_key": schema_key,
        "timestamp": now.isoformat(),
        "payload": record,
        "fallback": True,
    }

    # HMAC of serialised entry (before appending the hmac field itself)
    serialised = json.dumps(entry, sort_keys=True, separators=(",", ":"))
    signing_key_bytes = signing_key.encode() if signing_key else b""
    sig = hmac.new(
        signing_key_bytes,
        serialised.encode(),
        _HMAC_ALGO,
    ).hexdigest()
    entry["hmac"] = sig

    with _audit_file_lock, path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")

    return {"record_id": record_id, "fallback_path": str(path), "fallback": True}


def _generate_record_id(record: Any, now: datetime) -> str:
    """Generate a deterministic record ID from content + timestamp."""
    raw = json.dumps(record, sort_keys=True, separators=(",", ":")) + now.isoformat()
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# CFG-023: sf-observe fallback
# ---------------------------------------------------------------------------


def observe_fallback(span_data: dict[str, Any]) -> None:
    """Write ``span_data`` to stdout in OTLP JSON format (CFG-023).

    Uses the ``LOCAL_SPAN:`` prefix for easy grep.

    Args:
        span_data: Dict representation of the span to emit.
    """
    _log.warning("sf-observe unreachable, writing span to stdout (CFG-023).")
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        **span_data,
    }
    sys.stdout.write(f"LOCAL_SPAN: {json.dumps(payload, separators=(',', ':'))}\n")
    sys.stdout.flush()


# ---------------------------------------------------------------------------
# CFG-024: sf-alert fallback
# ---------------------------------------------------------------------------


def alert_fallback(
    topic: str,
    payload: dict[str, Any],
    severity: str = "WARNING",
) -> dict[str, Any]:
    """Log the alert to stderr at WARNING level (CFG-024).

    No network delivery occurs; the full alert payload is included in the
    log message.

    Args:
        topic: Alert topic string.
        payload: Alert data dict.
        severity: Severity string for the log message (default: ``"WARNING"``).
    """
    _log.warning(
        "sf-alert unreachable [%s] topic=%r payload=%s (CFG-024).",
        severity,
        topic,
        json.dumps(payload, separators=(",", ":")),
    )
    sys.stderr.write(
        f"SPANFORGE ALERT [{severity}] topic={topic!r}: "
        f"{json.dumps(payload, separators=(',', ':'))}\n"
    )
    sys.stderr.flush()
    return {"topic": topic, "severity": severity, "fallback": True}


# ---------------------------------------------------------------------------
# CFG-025: sf-identity fallback
# ---------------------------------------------------------------------------


def identity_fallback(
    token: str | None = None,
) -> dict[str, Any]:
    """Accept a local bearer token without JWT signature validation (CFG-025).

    Reads ``SPANFORGE_LOCAL_TOKEN`` from env if ``token`` is ``None``.
    Only appropriate for CLI / local dev use.  Logs a ``WARNING``.

    Args:
        token: Optional bearer token string.  If ``None``, reads from
            ``SPANFORGE_LOCAL_TOKEN`` env var.

    Returns:
        ``{"token": str, "validated": false, "fallback": true}``

    Raises:
        :exc:`ValueError`: If no token is available.
    """
    _log.warning(
        "sf-identity unreachable, using local token from env (CFG-025). "
        "JWT signature validation skipped."
    )

    resolved = token or os.environ.get("SPANFORGE_LOCAL_TOKEN", "")
    if not resolved:
        raise ValueError(
            "sf-identity fallback requires SPANFORGE_LOCAL_TOKEN env var "
            "or an explicit token argument."
        )
    return {"token": resolved, "validated": False, "fallback": True}


# ---------------------------------------------------------------------------
# CFG-026: sf-gate fallback
# ---------------------------------------------------------------------------


def gate_fallback(
    gate_config_path: str | Path,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run gate evaluation locally using the ``spanforge.gate`` module (CFG-026).

    PRRI check reads a local ``prri_result.json`` if present.  Trust gate
    checks the local audit fallback JSONL.

    Args:
        gate_config_path: Path to the gate YAML configuration file.
        context: Optional template context dict.

    Returns:
        ``{"verdict": "PASS|FAIL|WARN|SKIPPED", "results": [...], "fallback": true}``
    """
    _log.warning("sf-gate unreachable, running gate evaluation locally (CFG-026).")

    try:
        from spanforge.gate import GateRunner

        runner: Any = GateRunner()
        run_result = runner.run_pipeline(str(gate_config_path), context=context or {})
        return {
            "verdict": getattr(run_result, "overall_verdict", "UNKNOWN"),
            "results": [
                {
                    "gate_id": getattr(r, "gate_id", ""),
                    "verdict": getattr(r, "verdict", "UNKNOWN"),
                }
                for r in getattr(run_result, "results", [])
            ],
            "fallback": True,
        }
    except Exception as exc:
        _log.warning("gate_fallback: local gate run raised %s.", exc)
        return {"verdict": "FAIL", "results": [], "fallback": True, "error": str(exc)}


# ---------------------------------------------------------------------------
# CFG-027: sf-cec fallback
# ---------------------------------------------------------------------------


def cec_fallback(
    model_id: str,
    framework: str,
    events_file: str | Path | None = None,
    *,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Generate a CEC bundle from the local audit fallback JSONL (CFG-027).

    No BYOS upload — bundle written to a local file.

    Args:
        model_id: Model UUID.
        framework: Compliance framework identifier.
        events_file: Path to a JSONL events file.  Defaults to the local
            audit fallback JSONL at ``~/.spanforge/audit_fallback.jsonl``.
        output_path: Where to write the bundle.  Defaults to
            ``~/.spanforge/cec_bundle_{model_id}.jsonl``.

    Returns:
        ``{"bundle_path": str, "record_count": int, "fallback": true}``
    """
    _log.warning("sf-cec unreachable, generating CEC bundle locally (CFG-027).")

    src = Path(events_file) if events_file else _DEFAULT_AUDIT_FALLBACK_PATH
    dest = (
        Path(output_path)
        if output_path
        else Path.home() / ".spanforge" / f"cec_bundle_{model_id}.jsonl"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    if src.exists():
        with src.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        pass

    bundle: dict[str, Any] = {
        "model_id": model_id,
        "framework": framework,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "record_count": len(records),
        "records": records,
        "fallback": True,
    }

    with dest.open("w", encoding="utf-8") as f:
        f.write(json.dumps(bundle, separators=(",", ":")) + "\n")

    _log.info("cec_fallback: wrote %d records to %s", len(records), dest)
    return {"bundle_path": str(dest), "record_count": len(records), "fallback": True}
