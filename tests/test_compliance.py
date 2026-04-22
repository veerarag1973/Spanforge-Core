"""Tests for the public spanforge.compliance facade."""

from __future__ import annotations

from spanforge.compliance import (
    ComplianceMappingEngine,
    test_compatibility,
    verify_chain_integrity,
    verify_events_scoped,
    verify_tenant_isolation,
)
from spanforge.event import Event, EventType
from spanforge.signing import sign


def _event(**overrides: object) -> Event:
    payload = overrides.pop("payload", {"span_name": "test-span"})
    return Event(
        event_type=overrides.pop("event_type", EventType.TRACE_SPAN_COMPLETED),
        source=overrides.pop("source", "compliance-test@1.0.0"),
        payload=payload,
        timestamp=overrides.pop("timestamp", "2026-01-01T00:00:00.000000Z"),
        org_id=overrides.pop("org_id", "org-a"),
        team_id=overrides.pop("team_id", "team-a"),
        **overrides,
    )


class TestComplianceFacade:
    def test_public_module_exposes_mapping_engine(self) -> None:
        assert ComplianceMappingEngine.__name__ == "ComplianceMappingEngine"

    def test_compatibility_passes_for_valid_event(self) -> None:
        result = test_compatibility([_event()])
        assert result.passed is True
        assert not result.violations

    def test_compatibility_reports_invalid_source(self) -> None:
        result = test_compatibility([_event(source="bad source")])
        assert result.passed is False
        assert any(v.check_id == "CHK-3" for v in result.violations)

    def test_chain_integrity_detects_timestamp_regression(self) -> None:
        first = sign(_event(timestamp="2026-01-01T00:00:02.000000Z"), "secret-123")
        second = sign(
            _event(timestamp="2026-01-01T00:00:01.000000Z"),
            "secret-123",
            prev_event=first,
        )
        result = verify_chain_integrity([first, second], "secret-123")
        assert result.passed is False
        assert any(v.kind == "non_monotonic_timestamp" for v in result.violations)

    def test_verify_tenant_isolation_detects_overlap(self) -> None:
        left = [_event(org_id="shared-org")]
        right = [_event(org_id="shared-org")]
        result = verify_tenant_isolation(left, right)
        assert result.passed is False
        assert result.violations

    def test_verify_events_scoped_detects_wrong_team(self) -> None:
        result = verify_events_scoped([_event(team_id="team-b")], expected_team_id="team-a")
        assert result.passed is False
        assert result.violations[0].event_id is not None
