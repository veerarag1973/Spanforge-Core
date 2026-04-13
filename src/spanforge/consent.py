"""Consent boundary enforcement for SpanForge compliance pipeline.

Provides runtime monitoring that flags agent decisions made on
out-of-consent data, distinct from PII redaction. Consent enforcement
checks whether data *should be used at all*, while redaction masks
sensitive values.

Configuration
-------------
* ``consent_enforcement=True`` on :class:`~spanforge.config.SpanForgeConfig`
  activates consent boundary checks.
* Call :func:`grant_consent` / :func:`revoke_consent` to manage the
  consent store, then :func:`check_consent` before data processing.

Emits ``consent.granted``, ``consent.revoked``, ``consent.violation``
events into the HMAC audit chain via :func:`emit_rfc_event`.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

from spanforge.namespaces.consent import ConsentPayload

__all__ = [
    "ConsentBoundary",
    "ConsentRecord",
    "check_consent",
    "grant_consent",
    "revoke_consent",
]


@dataclass
class ConsentRecord:
    """A single consent grant for a data subject."""

    subject_id: str
    scope: str
    purpose: str
    legal_basis: str = "consent"
    expiry: str | None = None  # ISO 8601
    data_categories: list[str] = field(default_factory=list)


class ConsentBoundary:
    """Thread-safe runtime consent store and boundary enforcer.

    Manages active consent records and checks data-use against them.
    Emits HMAC-signed events for grants, revocations, and violations.
    """

    def __init__(self, *, auto_emit: bool = True) -> None:
        self._lock = threading.Lock()
        self._records: dict[tuple[str, str], ConsentRecord] = {}
        self._auto_emit = auto_emit

    def grant(
        self,
        subject_id: str,
        scope: str,
        purpose: str,
        *,
        legal_basis: str = "consent",
        expiry: str | None = None,
        agent_id: str | None = None,
        data_categories: list[str] | None = None,
    ) -> ConsentRecord:
        """Record a consent grant and emit a ``consent.granted`` event."""
        if not subject_id:
            raise ValueError("subject_id must be non-empty")
        if not scope:
            raise ValueError("scope must be non-empty")
        if not purpose:
            raise ValueError("purpose must be non-empty")

        record = ConsentRecord(
            subject_id=subject_id,
            scope=scope,
            purpose=purpose,
            legal_basis=legal_basis,
            expiry=expiry,
            data_categories=data_categories or [],
        )
        with self._lock:
            self._records[(subject_id, scope)] = record

        if self._auto_emit:
            payload = ConsentPayload(
                subject_id=subject_id,
                scope=scope,
                purpose=purpose,
                status="granted",
                legal_basis=legal_basis,
                expiry=expiry,
                agent_id=agent_id,
                data_categories=data_categories or [],
            )
            self._emit(payload, "granted")
        return record

    def revoke(
        self,
        subject_id: str,
        scope: str,
        *,
        reason: str = "user request",
        agent_id: str | None = None,
    ) -> bool:
        """Revoke a consent record and emit a ``consent.revoked`` event.

        Returns ``True`` if a matching record was found and removed.
        """
        with self._lock:
            removed = self._records.pop((subject_id, scope), None)

        if removed is not None and self._auto_emit:
            payload = ConsentPayload(
                subject_id=subject_id,
                scope=scope,
                purpose=removed.purpose,
                status="revoked",
                legal_basis=removed.legal_basis,
                agent_id=agent_id,
                violation_detail=reason,
            )
            self._emit(payload, "revoked")
        return removed is not None

    def check(
        self,
        subject_id: str,
        scope: str,
        *,
        agent_id: str | None = None,
        purpose: str = "",
    ) -> bool:
        """Check whether consent is active for the given subject + scope.

        If no active consent exists, emits a ``consent.violation`` event
        and returns ``False``.
        """
        with self._lock:
            record = self._records.get((subject_id, scope))

        if record is not None:
            return True

        # Violation: no consent for this subject + scope
        if self._auto_emit:
            payload = ConsentPayload(
                subject_id=subject_id,
                scope=scope,
                purpose=purpose or "unspecified",
                status="violation",
                agent_id=agent_id,
                violation_detail=f"No active consent for subject={subject_id!r} scope={scope!r}",
            )
            self._emit(payload, "violation")
        return False

    def has_consent(self, subject_id: str, scope: str) -> bool:
        """Return ``True`` if an active consent record exists (no event emitted)."""
        with self._lock:
            return (subject_id, scope) in self._records

    def list_consents(self, subject_id: str | None = None) -> list[ConsentRecord]:
        """Return all active consent records, optionally filtered by subject."""
        with self._lock:
            if subject_id is None:
                return list(self._records.values())
            return [r for r in self._records.values() if r.subject_id == subject_id]

    def clear(self) -> None:
        """Remove all consent records (for testing)."""
        with self._lock:
            self._records.clear()

    @staticmethod
    def _emit(payload: ConsentPayload, status: str) -> None:
        """Emit a consent event into the HMAC audit chain."""
        try:
            from spanforge._stream import emit_rfc_event  # noqa: PLC0415
            from spanforge.types import EventType  # noqa: PLC0415

            _status_to_event = {
                "granted": EventType.CONSENT_GRANTED,
                "revoked": EventType.CONSENT_REVOKED,
                "violation": EventType.CONSENT_VIOLATION,
            }
            et = _status_to_event.get(status)
            if et is not None:
                try:
                    emit_rfc_event(et, payload.to_dict())
                except Exception:  # noqa: BLE001
                    pass  # never let auto-emit failures disrupt the caller
        except ImportError:
            pass


# ---------------------------------------------------------------------------
# Module-level singleton & convenience functions
# ---------------------------------------------------------------------------

_boundary = ConsentBoundary()


def grant_consent(
    subject_id: str,
    scope: str,
    purpose: str,
    **kwargs: Any,
) -> ConsentRecord:
    """Grant consent via the module-level :class:`ConsentBoundary`."""
    return _boundary.grant(subject_id, scope, purpose, **kwargs)


def revoke_consent(subject_id: str, scope: str, **kwargs: Any) -> bool:
    """Revoke consent via the module-level :class:`ConsentBoundary`."""
    return _boundary.revoke(subject_id, scope, **kwargs)


def check_consent(subject_id: str, scope: str, **kwargs: Any) -> bool:
    """Check consent via the module-level :class:`ConsentBoundary`."""
    return _boundary.check(subject_id, scope, **kwargs)
