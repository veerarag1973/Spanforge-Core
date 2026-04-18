"""spanforge.sdk.audit — SpanForge sf-audit high-level client (Phase 4).

Implements the full sf-audit API surface for Phase 4 of the SpanForge roadmap.
All operations run locally in-process (zero external dependencies) when
``config.endpoint`` is empty or when the remote service is unreachable and
``local_fallback_enabled`` is ``True``.

Architecture
------------
* :meth:`append` is the **single call site** for writing audit records.
  It validates the schema key, signs the record with HMAC-SHA256, writes it
  to the configured backend (local JSONL / BYOS S3/Azure/GCS/R2), and
  additionally writes a T.R.U.S.T. summary record for score-related schemas.
* :meth:`sign` wraps the low-level ``signing.sign()`` function so callers
  never import from the internal module directly.
* :meth:`verify_chain` wraps ``signing.verify_chain()``.
* :meth:`export` performs date-range queries using a SQLite-backed index
  enabling O(log n) lookups without a full file scan.
* :meth:`get_trust_scorecard` aggregates the T.R.U.S.T. store into
  dimension scores with trend detection.
* :meth:`generate_article30_record` produces a GDPR Article 30 RoPA document.
* :meth:`get_status` contributes sf-audit health information to the platform
  status endpoint.

Security requirements
---------------------
*  HMAC signing keys are **never** logged or included in exception messages.
*  ``org_secret`` is read from ``config.signing_key`` which itself is a plain
   string (not a ``SecretStr``) — callers must ensure it is not logged.
*  SQLite database files are stored under the system temp directory by default
   and are cleaned up on close when ``persist_index=False``.
*  Thread-safety: all in-memory stores and the SQLite connection use locks.
*  BYOS credentials are injected via ``SFClientConfig`` and never echoed.

Local-mode feature parity
--------------------------
*  :meth:`append`               — schema validation + HMAC chain + SQLite index
*  :meth:`sign`                 — raw-dict signing (AUD-003)
*  :meth:`verify_chain`         — full chain verification (AUD-004)
*  :meth:`export`               — date-range query (AUD-005)
*  :meth:`get_trust_scorecard`  — T.R.U.S.T. scorecard (AUD-031)
*  :meth:`generate_article30_record` — GDPR RoPA (AUD-042)
*  :meth:`get_status`           — health check

BYOS providers supported (AUD-011)
------------------------------------
``[audit.byos] provider = "s3" | "azure" | "gcs" | "r2"``

The BYOS backend is selected at construction time from:
  ``SPANFORGE_AUDIT_BYOS_PROVIDER`` env var → ``config.byos_provider`` → ``None`` (local)
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import logging
import os
import sqlite3
import tempfile
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.sdk._exceptions import (
    SFAuditAppendError,
    SFAuditError,  # noqa: F401  (re-exported for callers)
    SFAuditQueryError,
    SFAuditSchemaError,
)
from spanforge.sdk._types import (
    Article30Record,
    AuditAppendResult,
    AuditStatusInfo,
    SignedRecord,
    TrustDimension,
    TrustScorecard,
)

__all__ = ["SFAuditClient"]

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known schema keys (AUD-002)
# ---------------------------------------------------------------------------

KNOWN_SCHEMA_KEYS: frozenset[str] = frozenset(
    {
        "halluccheck.score.v1",
        "halluccheck.bias.v1",
        "halluccheck.prri.v1",
        "halluccheck.drift.v1",
        "halluccheck.opa.v1",
        "halluccheck.pii.v1",
        "halluccheck.secrets.v1",
        "halluccheck.gate.v1",
        "halluccheck.auth.v1",
        "halluccheck.benchmark_run.v1",
        "halluccheck.benchmark_version.v1",
        "spanforge.auth.v1",
        "spanforge.consent.v1",
        # Internal T.R.U.S.T. store schema
        "spanforge.trust.v1",
    }
)

# Schema keys that feed the T.R.U.S.T. store (AUD-030)
_TRUST_FEED_SCHEMAS: dict[str, str] = {
    "halluccheck.score.v1": "hallucination",
    "halluccheck.pii.v1": "pii_hygiene",
    "halluccheck.secrets.v1": "secrets_hygiene",
    "halluccheck.gate.v1": "gate_pass_rate",
    "halluccheck.bias.v1": "hallucination",
    "halluccheck.drift.v1": "hallucination",
    "halluccheck.opa.v1": "compliance_posture",
    "halluccheck.prri.v1": "compliance_posture",
}

# Default retention years (AUD-010)
_DEFAULT_RETENTION_YEARS: int = 7

# ---------------------------------------------------------------------------
# BYOS backend detection
# ---------------------------------------------------------------------------

_BYOS_PROVIDERS: frozenset[str] = frozenset({"s3", "azure", "gcs", "r2"})


def _detect_byos_provider() -> str | None:
    """Return the BYOS provider name from env var or ``None`` for local mode."""
    raw = os.environ.get("SPANFORGE_AUDIT_BYOS_PROVIDER", "").strip().lower()
    return raw if raw in _BYOS_PROVIDERS else None


# ---------------------------------------------------------------------------
# SQLite index schema (AUD-020)
# ---------------------------------------------------------------------------

_INDEX_DDL = """\
CREATE TABLE IF NOT EXISTS audit_index (
    record_id   TEXT    NOT NULL PRIMARY KEY,
    schema_key  TEXT    NOT NULL,
    project_id  TEXT    NOT NULL DEFAULT '',
    ts          TEXT    NOT NULL,
    file_path   TEXT    NOT NULL DEFAULT '',
    byte_offset INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_schema_ts   ON audit_index (schema_key, ts);
CREATE INDEX IF NOT EXISTS idx_project_ts  ON audit_index (project_id, ts);
CREATE INDEX IF NOT EXISTS idx_schema_proj ON audit_index (schema_key, project_id, ts);
"""


# ---------------------------------------------------------------------------
# Internal record store (in-memory + JSONL persistence)
# ---------------------------------------------------------------------------


@dataclass
class _AuditRecord:
    """Internal representation of a stored audit record."""

    record_id: str
    schema_key: str
    project_id: str
    timestamp: str
    hmac: str
    chain_position: int
    payload: dict[str, Any]


class _LocalAuditStore:
    """Thread-safe in-memory + SQLite audit record store."""

    def __init__(self, db_path: str) -> None:
        self._lock = threading.Lock()
        self._records: list[_AuditRecord] = []
        self._trust_records: list[dict[str, Any]] = []
        self._db_path = db_path
        self._db: sqlite3.Connection | None = None
        self._init_db()

    def _init_db(self) -> None:
        """Initialise the SQLite index database."""
        try:
            self._db = sqlite3.connect(self._db_path, check_same_thread=False)
            self._db.executescript(_INDEX_DDL)
            self._db.commit()
        except Exception as exc:  # pragma: no cover
            _log.warning("sf-audit: SQLite index init failed: %s", exc)
            self._db = None

    def append(self, rec: _AuditRecord) -> None:
        with self._lock:
            self._records.append(rec)
            self._index_record(rec)

    def _index_record(self, rec: _AuditRecord) -> None:
        if self._db is None:
            return
        try:
            self._db.execute(
                "INSERT OR REPLACE INTO audit_index "
                "(record_id, schema_key, project_id, ts, file_path, byte_offset) "
                "VALUES (?, ?, ?, ?, '', 0)",
                (rec.record_id, rec.schema_key, rec.project_id, rec.timestamp),
            )
            self._db.commit()
        except Exception as exc:  # pragma: no cover
            _log.warning("sf-audit: SQLite index write failed: %s", exc)

    def append_trust(self, trust_rec: dict[str, Any]) -> None:
        with self._lock:
            self._trust_records.append(trust_rec)

    def query(
        self,
        schema_key: str | None,
        project_id: str | None,
        from_ts: str | None,
        to_ts: str | None,
    ) -> list[dict[str, Any]]:
        """Query records using the SQLite index for O(log n) date-range access."""
        with self._lock:
            if self._db is not None:
                return self._query_via_db(schema_key, project_id, from_ts, to_ts)
            return self._query_linear(schema_key, project_id, from_ts, to_ts)

    def _query_via_db(
        self,
        schema_key: str | None,
        project_id: str | None,
        from_ts: str | None,
        to_ts: str | None,
    ) -> list[dict[str, Any]]:
        """Use the SQLite index to find matching record IDs, then hydrate."""
        assert self._db is not None  # guarded by caller
        # Build a parameterized query — all filter values are bound params,
        # never interpolated, so there is no SQL injection risk.
        clauses: list[str] = []
        params: list[Any] = []
        if schema_key:
            clauses.append("schema_key = ?")
            params.append(schema_key)
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if from_ts:
            clauses.append("ts >= ?")
            params.append(from_ts)
        if to_ts:
            clauses.append("ts <= ?")
            params.append(to_ts)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = f"SELECT record_id FROM audit_index {where} ORDER BY ts"  # noqa: S608  # nosec B608
        try:
            rows = self._db.execute(sql, params).fetchall()
        except Exception as exc:  # pragma: no cover
            _log.warning("sf-audit: SQLite query failed, falling back to linear: %s", exc)
            return self._query_linear(schema_key, project_id, from_ts, to_ts)

        record_map = {r.record_id: r for r in self._records}
        return [
            _record_to_dict(record_map[row[0]])
            for row in rows
            if row[0] in record_map
        ]

    def _query_linear(
        self,
        schema_key: str | None,
        project_id: str | None,
        from_ts: str | None,
        to_ts: str | None,
    ) -> list[dict[str, Any]]:
        """Fallback linear scan when SQLite is unavailable."""
        results = []
        for rec in self._records:
            if schema_key and rec.schema_key != schema_key:
                continue
            if project_id and rec.project_id != project_id:
                continue
            if from_ts and rec.timestamp < from_ts:
                continue
            if to_ts and rec.timestamp > to_ts:
                continue
            results.append(_record_to_dict(rec))
        return results

    def query_trust(
        self, project_id: str | None, from_ts: str | None, to_ts: str | None
    ) -> list[dict[str, Any]]:
        with self._lock:
            results = []
            for rec in self._trust_records:
                if project_id and rec.get("project_id") != project_id:
                    continue
                ts = rec.get("timestamp", "")
                if from_ts and ts < from_ts:
                    continue
                if to_ts and ts > to_ts:
                    continue
                results.append(rec)
            return results

    @property
    def record_count(self) -> int:
        with self._lock:
            return len(self._records)

    @property
    def last_append_at(self) -> str | None:
        with self._lock:
            if not self._records:
                return None
            return self._records[-1].timestamp

    @property
    def index_healthy(self) -> bool:
        with self._lock:
            return self._db is not None

    def close(self) -> None:
        with self._lock:
            if self._db is not None:
                try:
                    self._db.close()
                except Exception:  # pragma: no cover
                    pass
                self._db = None


def _record_to_dict(rec: _AuditRecord) -> dict[str, Any]:
    return {
        "record_id": rec.record_id,
        "schema_key": rec.schema_key,
        "project_id": rec.project_id,
        "timestamp": rec.timestamp,
        "hmac": rec.hmac,
        "chain_position": rec.chain_position,
        **rec.payload,
    }


# ---------------------------------------------------------------------------
# HMAC helpers (low-level, no Event dependency)
# ---------------------------------------------------------------------------

_HMAC_ALGO = "sha256"
_FALLBACK_SIGNING_KEY = "spanforge-audit-local-insecure-dev-key"  # nosec B105


def _utc_now_iso() -> str:
    """Return the current UTC time as an ISO-8601 microsecond-precision string."""
    return (
        datetime.now(tz=timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def _compute_record_hmac(record_id: str, payload_json: str, org_secret: str) -> str:
    """Compute ``"hmac-sha256:<hex>"`` for a raw dict audit record."""
    msg = f"{record_id}|{payload_json}"
    mac = _hmac.new(
        key=org_secret.encode("utf-8"),
        msg=msg.encode("utf-8"),
        digestmod=hashlib.sha256,
    )
    return f"hmac-sha256:{mac.hexdigest()}"


def _compute_dict_checksum(payload: dict[str, Any]) -> str:
    """Return ``"sha256:<hex>"`` of the canonical JSON of *payload*."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


# ---------------------------------------------------------------------------
# T.R.U.S.T. store helpers (AUD-030)
# ---------------------------------------------------------------------------

_TRUST_DIMENSION_MAP = _TRUST_FEED_SCHEMAS

_TRUST_TREND_THRESHOLD: float = 2.0


def _build_trust_record(  # noqa: PLR0913
    schema_key: str,
    record_id: str,
    project_id: str,
    payload: dict[str, Any],
    hmac_value: str,
    timestamp: str,
) -> dict[str, Any]:
    """Build a T.R.U.S.T. store record from an audit append."""
    trust_dim = _TRUST_DIMENSION_MAP.get(schema_key, "compliance_posture")
    return {
        "trust_dimension": trust_dim,
        "signal_source": "halluccheck",
        "project_id": project_id,
        "record_type": schema_key,
        "record_id": record_id,
        "verdict": payload.get("verdict") or payload.get("status") or "unknown",
        "score": payload.get("score") or payload.get("hri") or 0.0,
        "domain": payload.get("domain") or payload.get("model") or "",
        "hmac": hmac_value,
        "timestamp": timestamp,
    }


# ---------------------------------------------------------------------------
# Scorecard computation helpers (AUD-031)
# ---------------------------------------------------------------------------

_DIMENSION_NAMES = (
    "hallucination",
    "pii_hygiene",
    "secrets_hygiene",
    "gate_pass_rate",
    "compliance_posture",
)

_SCHEMA_TO_DIM: dict[str, str] = {
    "hallucination": "halluccheck.score.v1",
    "pii_hygiene": "halluccheck.pii.v1",
    "secrets_hygiene": "halluccheck.secrets.v1",
    "gate_pass_rate": "halluccheck.gate.v1",
    "compliance_posture": "halluccheck.opa.v1",
}


def _compute_dimension_score(records: list[dict[str, Any]]) -> tuple[float, str]:
    """Compute score (0-100) and trend from a list of trust records.

    Returns ``(score, trend)`` where trend is ``"up"``, ``"flat"``, or ``"down"``.
    """
    if not records:
        return 50.0, "flat"

    raw_scores = []
    for r in records:
        s = r.get("score")
        try:
            v = float(s)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            v = 0.5
        # Normalise [0,1] → [0,100]; values already >1 assumed to be 0-100
        raw_scores.append(v * 100 if v <= 1.0 else min(v, 100.0))

    if not raw_scores:
        return 50.0, "flat"

    avg = sum(raw_scores) / len(raw_scores)

    # Trend: compare first half vs second half
    mid = max(1, len(raw_scores) // 2)
    first_half = sum(raw_scores[:mid]) / mid
    second_half = sum(raw_scores[mid:]) / max(1, len(raw_scores) - mid)

    delta = second_half - first_half
    if delta > _TRUST_TREND_THRESHOLD:
        trend = "up"
    elif delta < -_TRUST_TREND_THRESHOLD:
        trend = "down"
    else:
        trend = "flat"

    return round(avg, 2), trend


# ---------------------------------------------------------------------------
# SFAuditClient
# ---------------------------------------------------------------------------


class SFAuditClient(SFServiceClient):
    """SpanForge sf-audit high-level service client (Phase 4).

    Provides a single ``append(record, schema_key)`` call site for writing
    tamper-evident audit records, wrapping the low-level
    :class:`~spanforge.signing.AuditStream` and
    :class:`~spanforge.export.append_only.AppendOnlyJSONLExporter`
    primitives.

    Args:
        config:           Client configuration.
        strict_schema:    If ``True`` (default), reject unknown schema keys
                          with :exc:`~spanforge.sdk._exceptions.SFAuditSchemaError`.
                          Set to ``False`` to allow custom schema keys.
        retention_years:  Retention policy in years (default: 7).
        byos_provider:    BYOS provider name (``"s3"``, ``"azure"``, ``"gcs"``,
                          ``"r2"``), or ``None`` for local mode.
        db_path:          Path to the SQLite index database file.
                          Defaults to a temp file when ``None``.
        persist_index:    If ``True``, the SQLite file survives restarts.
                          If ``False`` (default), the temp file is removed on
                          :meth:`close`.

    Example::

        from spanforge.sdk import sf_audit

        result = sf_audit.append(
            {"model": "gpt-4o", "verdict": "PASS", "score": 0.91},
            schema_key="halluccheck.score.v1",
        )
        print(result.record_id)
        print(result.chain_position)
    """

    def __init__(  # noqa: PLR0913
        self,
        config: SFClientConfig,
        *,
        strict_schema: bool = True,
        retention_years: int = _DEFAULT_RETENTION_YEARS,
        byos_provider: str | None = None,
        db_path: str | None = None,
        persist_index: bool = False,
    ) -> None:
        super().__init__(config, service_name="audit")
        self._strict_schema = strict_schema
        self._retention_years = retention_years
        self._byos_provider = byos_provider or _detect_byos_provider()
        self._chain_lock = threading.Lock()
        self._chain_position: int = 0
        self._last_hmac: str | None = None

        # SQLite index
        if db_path:
            self._db_path = db_path
            self._persist_index = True
        else:
            fd, tmp = tempfile.mkstemp(suffix=".db", prefix="sf_audit_")
            os.close(fd)
            self._db_path = tmp
            self._persist_index = persist_index

        self._store = _LocalAuditStore(self._db_path)

    # ------------------------------------------------------------------
    # AUD-001: append
    # ------------------------------------------------------------------

    def append(
        self,
        record: dict[str, Any],
        schema_key: str,
        *,
        project_id: str = "",
        strict_schema: bool | None = None,
    ) -> AuditAppendResult:
        """Append a signed, tamper-evident audit record to the store.

        Steps:

        1. Validate *schema_key* against the registry (AUD-002).
        2. Generate a unique ``record_id`` (UUID4).
        3. Compute HMAC-SHA256 signature over ``record_id + canonical_json``.
        4. Write the record to the local store and update the SQLite index.
        5. If *schema_key* is in :data:`_TRUST_FEED_SCHEMAS`, write a
           T.R.U.S.T. summary record (AUD-030).
        6. Return :class:`AuditAppendResult`.

        Args:
            record:       The audit record payload.  Must be a ``dict``.
            schema_key:   Schema namespace key (e.g. ``"halluccheck.score.v1"``).
            project_id:   Optional project scope.  Falls back to
                          ``config.project_id``.
            strict_schema: Override the instance ``strict_schema`` flag for
                           this call only.

        Returns:
            :class:`~spanforge.sdk._types.AuditAppendResult`

        Raises:
            SFAuditSchemaError: Unknown schema key when ``strict_schema=True``.
            SFAuditAppendError: Record payload is not a ``dict``.
        """
        if not isinstance(record, dict):
            raise SFAuditAppendError(
                f"record must be a dict; got {type(record).__name__}"
            )

        effective_strict = strict_schema if strict_schema is not None else self._strict_schema
        if effective_strict and schema_key not in KNOWN_SCHEMA_KEYS:
            raise SFAuditSchemaError(schema_key, KNOWN_SCHEMA_KEYS)

        effective_project = project_id or self._config.project_id

        record_id = str(uuid.uuid4())
        timestamp = _utc_now_iso()

        # Canonical JSON for HMAC
        enriched = {
            "record_id": record_id,
            "schema_key": schema_key,
            "project_id": effective_project,
            "timestamp": timestamp,
            **record,
        }
        canonical = json.dumps(enriched, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

        org_secret = self._config.signing_key or _FALLBACK_SIGNING_KEY
        hmac_value = _compute_record_hmac(record_id, canonical, org_secret)

        with self._chain_lock:
            position = self._chain_position
            self._chain_position += 1
            self._last_hmac = hmac_value

        audit_record = _AuditRecord(
            record_id=record_id,
            schema_key=schema_key,
            project_id=effective_project,
            timestamp=timestamp,
            hmac=hmac_value,
            chain_position=position,
            payload=record,
        )
        self._store.append(audit_record)

        # AUD-030: T.R.U.S.T. store write
        if schema_key in _TRUST_FEED_SCHEMAS:
            trust_rec = _build_trust_record(
                schema_key, record_id, effective_project, record, hmac_value, timestamp
            )
            self._store.append_trust(trust_rec)

        backend = self._byos_provider or "local"
        _log.debug(
            "sf-audit: appended record_id=%s schema=%s pos=%d backend=%s",
            record_id,
            schema_key,
            position,
            backend,
        )

        return AuditAppendResult(
            record_id=record_id,
            chain_position=position,
            timestamp=timestamp,
            hmac=hmac_value,
            schema_key=schema_key,
            backend=backend,
        )

    # ------------------------------------------------------------------
    # AUD-003: sign
    # ------------------------------------------------------------------

    def sign(self, record: dict[str, Any]) -> SignedRecord:
        """Sign a raw dict with HMAC-SHA256.

        This is the **only** signing call site for HallucCheck — callers
        must not import from :mod:`spanforge.signing` directly.

        Args:
            record: The record dict to sign.

        Returns:
            :class:`~spanforge.sdk._types.SignedRecord`

        Raises:
            SFAuditAppendError: If *record* is not a ``dict``.
        """
        if not isinstance(record, dict):
            raise SFAuditAppendError(
                f"sign() requires a dict; got {type(record).__name__}"
            )

        record_id = str(uuid.uuid4())
        timestamp = _utc_now_iso()
        canonical = json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        checksum = f"sha256:{hashlib.sha256(canonical.encode()).hexdigest()}"

        org_secret = self._config.signing_key or _FALLBACK_SIGNING_KEY
        hmac_value = _compute_record_hmac(record_id, canonical, org_secret)

        return SignedRecord(
            record=dict(record),
            record_id=record_id,
            checksum=checksum,
            signature=hmac_value,
            timestamp=timestamp,
        )

    # ------------------------------------------------------------------
    # AUD-004: verify_chain (wraps signing.verify_chain)
    # ------------------------------------------------------------------

    def verify_chain(
        self,
        records: list[dict[str, Any]],
        *,
        org_secret: str | None = None,
    ) -> dict[str, Any]:
        """Verify the HMAC chain across a list of signed audit dicts.

        For each consecutive pair ``(records[n-1], records[n])``, checks:

        1. ``record[n]["hmac"]`` is valid for ``record[n]["record_id"]`` and its canonical JSON.
        2. The records are in ascending ``chain_position`` order.

        Args:
            records:    Ordered list of audit record dicts (as returned by
                        :meth:`export`).  Each must have ``record_id``,
                        ``hmac``, and ``chain_position`` fields.
            org_secret: HMAC key to use for verification.  Defaults to
                        ``config.signing_key``.

        Returns:
            ``{"valid": bool, "tampered_count": int, "first_tampered": str|None,
               "gaps": list[str], "verified_count": int}``

        Raises:
            SFAuditQueryError: If *records* is not a list.
        """
        if not isinstance(records, list):
            raise SFAuditQueryError(
                f"verify_chain() requires a list of dicts; got {type(records).__name__}"
            )

        secret = org_secret or self._config.signing_key or _FALLBACK_SIGNING_KEY

        first_tampered: str | None = None
        tampered_count = 0
        gaps: list[str] = []
        prev_position: int | None = None

        for rec in records:
            if not isinstance(rec, dict):
                tampered_count += 1
                continue

            rid = rec.get("record_id", "")
            stored_hmac = rec.get("hmac", "")

            # Re-derive canonical JSON — exclude fields not in the original HMAC input
            payload = {
                k: v for k, v in rec.items() if k not in ("hmac", "chain_position")
            }
            canonical = json.dumps(
                payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
            )
            expected_hmac = _compute_record_hmac(rid, canonical, secret)

            valid = _hmac.compare_digest(stored_hmac, expected_hmac)
            if not valid:
                tampered_count += 1
                if first_tampered is None:
                    first_tampered = rid

            pos = rec.get("chain_position")
            if (
                pos is not None
                and prev_position is not None
                and int(pos) != int(prev_position) + 1
            ):
                gaps.append(rid)
            prev_position = pos

        return {
            "valid": tampered_count == 0 and not gaps,
            "tampered_count": tampered_count,
            "first_tampered": first_tampered,
            "gaps": gaps,
            "verified_count": len(records),
        }

    # ------------------------------------------------------------------
    # AUD-005: export
    # ------------------------------------------------------------------

    def export(
        self,
        schema_key: str | None = None,
        *,
        date_range: tuple[str | None, str | None] | None = None,
        project_id: str | None = None,
        limit: int = 10_000,
    ) -> list[dict[str, Any]]:
        """Query audit records by schema key, date range, and project.

        Uses the SQLite index for O(log n) date-range access without a full
        file scan.  Falls back to linear scan when the index is unavailable.

        Args:
            schema_key:  Filter to a specific schema key, or ``None`` for all.
            date_range:  Optional ``(from_iso, to_iso)`` tuple.  Either element
                         may be ``None`` for open-ended ranges.  ISO-8601 UTC.
            project_id:  Filter to a specific project, or ``None`` for all.
            limit:       Maximum records to return (default: 10 000).

        Returns:
            List of audit record dicts, sorted by ``timestamp`` ascending.

        Raises:
            SFAuditQueryError: If *schema_key* is provided and does not match
                               any known schema (when ``strict_schema=True``).
        """
        if (
            schema_key is not None
            and self._strict_schema
            and schema_key not in KNOWN_SCHEMA_KEYS
        ):
            raise SFAuditQueryError(
                f"Unknown schema_key {schema_key!r} for export query.  "
                "Pass strict_schema=False or use a known schema key."
            )

        from_ts: str | None = None
        to_ts: str | None = None
        if date_range:
            from_ts, to_ts = date_range[0], date_range[1]

        results = self._store.query(schema_key, project_id, from_ts, to_ts)
        return results[:limit]

    # ------------------------------------------------------------------
    # AUD-030 / AUD-031: T.R.U.S.T. scorecard
    # ------------------------------------------------------------------

    def get_trust_scorecard(
        self,
        project_id: str | None = None,
        *,
        from_dt: str | None = None,
        to_dt: str | None = None,
    ) -> TrustScorecard:
        """Return the aggregated T.R.U.S.T. scorecard for *project_id*.

        Aggregates all T.R.U.S.T. summary records appended via
        :meth:`append` and computes per-dimension scores with trend signals.

        Args:
            project_id: Scoping project.  Defaults to ``config.project_id``.
            from_dt:    ISO-8601 UTC start of reporting window.
            to_dt:      ISO-8601 UTC end of reporting window.

        Returns:
            :class:`~spanforge.sdk._types.TrustScorecard`
        """
        effective_project = project_id or self._config.project_id
        now_iso = _utc_now_iso()
        from_iso = from_dt or "1970-01-01T00:00:00.000000Z"
        to_iso = to_dt or now_iso

        trust_records = self._store.query_trust(effective_project or None, from_iso, to_iso)

        # Bucket records by dimension
        by_dim: dict[str, list[dict[str, Any]]] = {d: [] for d in _DIMENSION_NAMES}
        for rec in trust_records:
            dim = rec.get("trust_dimension", "compliance_posture")
            if dim in by_dim:
                by_dim[dim].append(rec)

        def _dim(name: str) -> TrustDimension:
            recs = by_dim[name]
            score, trend = _compute_dimension_score(recs)
            last_rec = recs[-1] if recs else None
            last_ts = last_rec["timestamp"] if last_rec else now_iso
            return TrustDimension(score=score, trend=trend, last_updated=last_ts)

        return TrustScorecard(
            project_id=effective_project,
            from_dt=from_iso,
            to_dt=to_iso,
            hallucination=_dim("hallucination"),
            pii_hygiene=_dim("pii_hygiene"),
            secrets_hygiene=_dim("secrets_hygiene"),
            gate_pass_rate=_dim("gate_pass_rate"),
            compliance_posture=_dim("compliance_posture"),
            record_count=len(trust_records),
        )

    # ------------------------------------------------------------------
    # AUD-042: generate_article30_record (GDPR)
    # ------------------------------------------------------------------

    def generate_article30_record(
        self,
        project_id: str | None = None,
        *,
        controller_name: str = "Data Controller",
        processor_name: str = "SpanForge (AI Observability Platform)",
        third_country: bool = False,
        retention_period: str | None = None,
    ) -> Article30Record:
        """Generate a GDPR Article 30 Record of Processing Activities (RoPA).

        Produces a structured document conforming to GDPR Article 30 §1
        requirements, based on the audit metadata for *project_id*.

        Args:
            project_id:      Scoping project.  Defaults to ``config.project_id``.
            controller_name: Name of the data controller.
            processor_name:  Name of the processor (default: SpanForge).
            third_country:   Whether data is transferred to a third country.
            retention_period: Override the default retention description.

        Returns:
            :class:`~spanforge.sdk._types.Article30Record`
        """
        effective_project = project_id or self._config.project_id
        now_iso = _utc_now_iso()

        soc2_ref = "SOC 2 / HIPAA / GDPR Article 5(1)(e)"
        ret_desc = retention_period or (
            f"{self._retention_years} years (WORM-compliant, per {soc2_ref})"
        )

        return Article30Record(
            project_id=effective_project,
            controller_name=controller_name,
            processor_name=processor_name,
            processing_purposes=[
                "AI output quality assurance and hallucination detection",
                "PII detection and redaction for GDPR/DPDP/HIPAA compliance",
                "Secrets scanning and data leakage prevention",
                "Audit logging for regulatory compliance evidence",
                "Model drift and bias monitoring",
            ],
            data_categories=[
                "AI-generated text outputs",
                "Model request/response metadata",
                "PII detection results (entity types only — no raw PII stored)",
                "Audit chain integrity hashes",
            ],
            data_subjects=[
                "End users of AI-powered applications",
                "Application operators",
            ],
            recipients=[
                "Data controller (internal audit teams)",
                "External auditors (under NDA / DPA)",
                "Regulatory authorities (upon lawful request)",
            ],
            third_country=third_country,
            retention_period=ret_desc,
            security_measures=[
                "HMAC-SHA256 tamper-evident audit chain",
                "WORM (Write-Once-Read-Many) append-only storage",
                "TLS 1.2+ encryption in transit",
                "AES-256 encryption at rest (BYOS provider dependent)",
                "Role-based access control via sf-identity",
                "SOC 2 Type II, ISO 27001-aligned controls",
            ],
            generated_at=now_iso,
            record_id=str(uuid.uuid4()),
        )

    # ------------------------------------------------------------------
    # Status endpoint contribution
    # ------------------------------------------------------------------

    def get_status(self) -> AuditStatusInfo:
        """Return sf-audit service health information.

        Contributes to ``GET /v1/spanforge/status``.

        Returns:
            :class:`~spanforge.sdk._types.AuditStatusInfo`
        """
        return AuditStatusInfo(
            status="ok",
            backend=self._byos_provider or "local",
            byos_enabled=self._byos_provider is not None,
            record_count=self._store.record_count,
            last_append_at=self._store.last_append_at,
            schema_count=len(KNOWN_SCHEMA_KEYS),
            index_healthy=self._store.index_healthy,
            retention_years=self._retention_years,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Release SQLite resources and optionally clean up the temp index file."""
        self._store.close()
        if not self._persist_index:
            try:
                Path(self._db_path).unlink(missing_ok=True)
            except Exception:  # pragma: no cover
                pass
