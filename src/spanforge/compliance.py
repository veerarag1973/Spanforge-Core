"""Public compliance facade for SpanForge.

This module exposes the stable ``spanforge.compliance`` API referenced by the
CLI and documentation. It provides lightweight compatibility and isolation
checks while re-exporting the richer compliance evidence engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING

from spanforge.core.compliance_mapping import (
    ClauseStatus,
    ComplianceAttestation,
    ComplianceEvidencePackage,
    ComplianceFramework,
    ComplianceMappingEngine,
    EvidenceRecord,
    GapReport,
    verify_attestation_signature,
    verify_pdf_attestation,
)
from spanforge.event import _SOURCE_PATTERN
from spanforge.signing import ChainVerificationResult, verify_chain
from spanforge.types import is_registered, validate_custom
from spanforge.ulid import validate as validate_ulid

if TYPE_CHECKING:
    from collections.abc import Sequence

    from spanforge.event import Event

__all__ = [
    "ChainIntegrityResult",
    "ChainIntegrityViolation",
    "ClauseStatus",
    "CompatibilityResult",
    "CompatibilityViolation",
    "ComplianceAttestation",
    "ComplianceEvidencePackage",
    "ComplianceFramework",
    "ComplianceMappingEngine",
    "EvidenceRecord",
    "GapReport",
    "IsolationResult",
    "IsolationViolation",
    "test_compatibility",
    "verify_attestation_signature",
    "verify_chain_integrity",
    "verify_events_scoped",
    "verify_pdf_attestation",
    "verify_tenant_isolation",
]


@dataclass(frozen=True)
class CompatibilityViolation:
    """A single compatibility non-conformance."""

    check_id: str
    rule: str
    detail: str
    event_id: str | None


@dataclass(frozen=True)
class CompatibilityResult:
    """Result of running the compatibility checklist."""

    passed: bool
    events_checked: int
    violations: list[CompatibilityViolation]

    def __bool__(self) -> bool:
        return self.passed


@dataclass(frozen=True)
class ChainIntegrityViolation:
    """A single audit-chain integrity issue."""

    kind: str
    detail: str
    event_id: str | None = None


@dataclass(frozen=True)
class ChainIntegrityResult:
    """Result of audit-chain integrity verification."""

    passed: bool
    chain_result: ChainVerificationResult
    violations: list[ChainIntegrityViolation]
    events_verified: int
    gaps_detected: int

    def __bool__(self) -> bool:
        return self.passed


@dataclass(frozen=True)
class IsolationViolation:
    """A single tenant-scoping violation."""

    detail: str
    event_id: str | None = None


@dataclass(frozen=True)
class IsolationResult:
    """Result of tenant/isolation checks."""

    passed: bool
    violations: list[IsolationViolation]

    def __bool__(self) -> bool:
        return self.passed


def test_compatibility(events: Sequence[Event]) -> CompatibilityResult:
    """Apply the public compatibility checklist to a batch of events."""

    violations: list[CompatibilityViolation] = []

    for event in events:
        if not getattr(event, "schema_version", ""):
            violations.append(
                CompatibilityViolation(
                    check_id="CHK-1",
                    rule="required fields present",
                    detail="schema_version must be present and non-empty",
                    event_id=getattr(event, "event_id", None),
                )
            )
        if not getattr(event, "source", ""):
            violations.append(
                CompatibilityViolation(
                    check_id="CHK-1",
                    rule="required fields present",
                    detail="source must be present and non-empty",
                    event_id=getattr(event, "event_id", None),
                )
            )
        payload = getattr(event, "payload", None)
        if not isinstance(payload, (dict, MappingProxyType)) or not payload:
            violations.append(
                CompatibilityViolation(
                    check_id="CHK-1",
                    rule="required fields present",
                    detail="payload must be a non-empty dict",
                    event_id=getattr(event, "event_id", None),
                )
            )

        event_type = str(getattr(event, "event_type", ""))
        if not event_type:
            violations.append(
                CompatibilityViolation(
                    check_id="CHK-2",
                    rule="event_type namespace validity",
                    detail="event_type must be present and non-empty",
                    event_id=getattr(event, "event_id", None),
                )
            )
        elif not is_registered(event_type):
            try:
                validate_custom(event_type)
            except Exception as exc:
                violations.append(
                    CompatibilityViolation(
                        check_id="CHK-2",
                        rule="event_type namespace validity",
                        detail=str(exc),
                        event_id=getattr(event, "event_id", None),
                    )
                )

        source = str(getattr(event, "source", ""))
        if source and not _SOURCE_PATTERN.match(source):
            violations.append(
                CompatibilityViolation(
                    check_id="CHK-3",
                    rule="source format",
                    detail="source must match <service>@<semver>",
                    event_id=getattr(event, "event_id", None),
                )
            )

        event_id = str(getattr(event, "event_id", ""))
        if event_id and not validate_ulid(event_id):
            violations.append(
                CompatibilityViolation(
                    check_id="CHK-5",
                    rule="event_id is a valid ULID",
                    detail="event_id must be a valid 26-character ULID",
                    event_id=event_id,
                )
            )

    return CompatibilityResult(
        passed=not violations,
        events_checked=len(events),
        violations=violations,
    )


test_compatibility.__test__ = False


def verify_chain_integrity(
    events: Sequence[Event],
    org_secret: str,
    *,
    check_monotonic_timestamps: bool = True,
) -> ChainIntegrityResult:
    """Verify an ordered event chain for gaps, tampering, and timestamp regressions."""

    chain_result = verify_chain(events, org_secret)
    violations: list[ChainIntegrityViolation] = []

    if chain_result.first_tampered is not None:
        violations.append(
            ChainIntegrityViolation(
                kind="tampered_signature",
                detail="one or more event signatures failed verification",
                event_id=chain_result.first_tampered,
            )
        )

    for event_id in chain_result.gaps:
        violations.append(
            ChainIntegrityViolation(
                kind="broken_prev_id_link",
                detail="prev_id chain linkage is broken",
                event_id=event_id,
            )
        )

    if check_monotonic_timestamps:
        previous: str | None = None
        previous_event_id: str | None = None
        for event in events:
            current = getattr(event, "timestamp", None)
            if previous is not None and current is not None and str(current) < str(previous):
                violations.append(
                    ChainIntegrityViolation(
                        kind="non_monotonic_timestamp",
                        detail="timestamps must be monotonically non-decreasing",
                        event_id=getattr(event, "event_id", previous_event_id),
                    )
                )
                break
            previous = str(current) if current is not None else None
            previous_event_id = getattr(event, "event_id", None)

    return ChainIntegrityResult(
        passed=not violations,
        chain_result=chain_result,
        violations=violations,
        events_verified=len(events),
        gaps_detected=len(chain_result.gaps),
    )


def verify_tenant_isolation(
    group_a: Sequence[Event],
    group_b: Sequence[Event],
    *,
    strict: bool = False,
) -> IsolationResult:
    """Verify that two event batches are scoped to separate tenants."""

    violations: list[IsolationViolation] = []
    orgs_a = {event.org_id for event in group_a if event.org_id}
    orgs_b = {event.org_id for event in group_b if event.org_id}
    overlap = sorted(orgs_a & orgs_b)

    if overlap:
        violations.append(
            IsolationViolation(
                detail=f"tenant groups share org_id values: {', '.join(overlap)}",
            )
        )

    if strict:
        for event in list(group_a) + list(group_b):
            if not event.org_id:
                violations.append(
                    IsolationViolation(
                        detail="strict tenant isolation requires org_id on every event",
                        event_id=event.event_id,
                    )
                )

    return IsolationResult(passed=not violations, violations=violations)


def verify_events_scoped(
    events: Sequence[Event],
    *,
    expected_org_id: str | None = None,
    expected_team_id: str | None = None,
) -> IsolationResult:
    """Verify that events carry the expected tenant scope values."""

    violations: list[IsolationViolation] = []
    for event in events:
        if expected_org_id is not None and event.org_id != expected_org_id:
            violations.append(
                IsolationViolation(
                    detail=(
                        f"expected org_id={expected_org_id!r}, found {event.org_id!r}"
                    ),
                    event_id=event.event_id,
                )
            )
        if expected_team_id is not None and event.team_id != expected_team_id:
            violations.append(
                IsolationViolation(
                    detail=(
                        f"expected team_id={expected_team_id!r}, found {event.team_id!r}"
                    ),
                    event_id=event.event_id,
                )
            )

    return IsolationResult(passed=not violations, violations=violations)
