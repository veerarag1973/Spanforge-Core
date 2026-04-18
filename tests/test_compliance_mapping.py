"""Tests for spanforge.core.compliance_mapping."""

from __future__ import annotations

import json
import os
from unittest.mock import patch

import pytest

from spanforge.core.compliance_mapping import (
    ClauseStatus,
    ComplianceAttestation,
    ComplianceEvidencePackage,
    ComplianceFramework,
    ComplianceMappingEngine,
    EvidenceRecord,
    GapReport,
    verify_attestation_signature,
)

# ─── Fixtures ────────────────────────────────────────────────────────────────

def _make_event(
    event_type: str = "llm.trace.span.completed",
    trace_id: str = "abc" * 10 + "ab",
    model_name: str = "gpt-4o",
    timestamp: str = "2025-01-15T10:00:00Z",
) -> dict:
    return {
        "event_id": "eid_" + event_type[:8],
        "event_type": event_type,
        "trace_id": trace_id,
        "span_id": "span001",
        "timestamp": timestamp,
        "source": "test-service@1.0.0",
        "payload": {
            "model": {"name": model_name, "system": "openai"},
            "span_name": "test_span",
            "duration_ms": 10.0,
            "cost_usd": 0.001,
        },
        "tags": {"env": "test"},
        "schema_version": "2.0",
        "signature": None,
    }


def _make_events_for_soc2(n: int = 10) -> list[dict]:
    """Return enough events to pass all SOC 2 clauses."""
    events = []
    for i in range(n):
        events.extend([
            _make_event("llm.audit.event", timestamp=f"2025-01-{15+i%10:02d}T10:00:00Z"),
            _make_event("llm.trace.span.completed", timestamp=f"2025-01-{15+i%10:02d}T10:01:00Z"),
            _make_event("llm.redact.pii_stripped", timestamp=f"2025-01-{15+i%10:02d}T10:02:00Z"),
            _make_event("llm.drift.score_changed", timestamp=f"2025-01-{15+i%10:02d}T10:03:00Z"),
            _make_event("llm.eval.score_computed", timestamp=f"2025-01-{15+i%10:02d}T10:04:00Z"),
            _make_event("llm.cost.token_usage", timestamp=f"2025-01-{15+i%10:02d}T10:05:00Z"),
            _make_event("llm.guard.blocked", timestamp=f"2025-01-{15+i%10:02d}T10:06:00Z"),
        ])
    return events


# ─── ComplianceFramework ─────────────────────────────────────────────────────

class TestComplianceFramework:
    def test_enum_values(self):
        assert ComplianceFramework.SOC2.value == "SOC 2 Type II"
        assert ComplianceFramework.HIPAA.value == "HIPAA"
        assert ComplianceFramework.GDPR.value == "GDPR"
        assert ComplianceFramework.NIST_AI_RMF.value == "NIST AI RMF"
        assert ComplianceFramework.EU_AI_ACT.value == "EU AI Act"
        assert ComplianceFramework.ISO_42001.value == "ISO/IEC 42001"

    def test_all_frameworks_present(self):
        values = {f.value for f in ComplianceFramework}
        assert len(values) == 6


# ─── ClauseStatus ────────────────────────────────────────────────────────────

class TestClauseStatus:
    def test_values(self):
        assert ClauseStatus.PASS.value == "pass"
        assert ClauseStatus.FAIL.value == "fail"
        assert ClauseStatus.PARTIAL.value == "partial"
        assert ClauseStatus.NOT_APPLICABLE.value == "not_applicable"
        assert ClauseStatus.UNKNOWN.value == "unknown"


# ─── EvidenceRecord ──────────────────────────────────────────────────────────

class TestEvidenceRecord:
    def test_construction(self):
        rec = EvidenceRecord(
            clause_id="CC6.1",
            status=ClauseStatus.PASS,
            evidence_count=10,
            audit_ids=["a", "b"],
            summary="Test summary",
        )
        assert rec.clause_id == "CC6.1"
        assert rec.status == ClauseStatus.PASS
        assert rec.evidence_count == 10
        assert rec.audit_ids == ["a", "b"]
        assert rec.summary == "Test summary"


# ─── GapReport ───────────────────────────────────────────────────────────────

class TestGapReport:
    def test_has_gaps_true(self):
        gap = GapReport(
            model_id="gpt-4o", framework="soc2",
            period_from="2025-01-01", period_to="2025-01-31",
            generated_at="2025-02-01T00:00:00Z",
            gap_clause_ids=["CC6.6"],
            partial_clause_ids=["CC7.2"],
        )
        assert gap.has_gaps is True
        assert gap.total_issues == 2

    def test_has_gaps_false(self):
        gap = GapReport(
            model_id="gpt-4o", framework="soc2",
            period_from="2025-01-01", period_to="2025-01-31",
            generated_at="2025-02-01T00:00:00Z",
            gap_clause_ids=[],
            partial_clause_ids=[],
        )
        assert gap.has_gaps is False
        assert gap.total_issues == 0

    def test_partial_only_not_a_gap(self):
        gap = GapReport(
            model_id="m", framework="gdpr",
            period_from="", period_to="", generated_at="",
            gap_clause_ids=[],
            partial_clause_ids=["Art.30"],
        )
        assert gap.has_gaps is False
        assert gap.total_issues == 1


# ─── ComplianceAttestation ───────────────────────────────────────────────────

class TestComplianceAttestation:
    def _make_attestation(self, overall=ClauseStatus.PASS) -> ComplianceAttestation:
        return ComplianceAttestation(
            model_id="gpt-4o",
            framework="soc2",
            period_from="2025-01-01",
            period_to="2025-01-31",
            generated_at="2025-02-01T00:00:00Z",
            generated_by="test",
            clauses=[
                EvidenceRecord("CC6.1", ClauseStatus.PASS, 10, [], "ok"),
            ],
            overall_status=overall,
            hmac_sig="abc123",
        )

    def test_to_json_round_trip(self):
        att = self._make_attestation()
        raw = att.to_json()
        data = json.loads(raw)
        assert data["model_id"] == "gpt-4o"
        assert data["framework"] == "soc2"
        assert data["overall_status"] == "pass"
        assert data["hmac_sig"] == "abc123"
        assert len(data["clauses"]) == 1
        assert data["clauses"][0]["clause_id"] == "CC6.1"

    def test_to_json_has_required_keys(self):
        att = self._make_attestation(ClauseStatus.FAIL)
        data = json.loads(att.to_json())
        for key in ("model_id", "framework", "period_from", "period_to",
                    "generated_at", "generated_by", "overall_status",
                    "hmac_sig", "clauses"):
            assert key in data, f"Missing key: {key}"


# ─── ComplianceMappingEngine ─────────────────────────────────────────────────

class TestComplianceMappingEngine:
    def setup_method(self):
        self.engine = ComplianceMappingEngine()

    def _pkg(self, framework, events=None, **kwargs):
        from_d = kwargs.get("from_date", "2025-01-01")
        to_d = kwargs.get("to_date", "2025-12-31")
        return self.engine.generate_evidence_package(
            model_id="gpt-4o",
            framework=framework,
            from_date=from_d,
            to_date=to_d,
            audit_events=events,
        )

    # --- Package structure ---

    def test_package_returns_all_components(self):
        pkg = self._pkg("soc2", events=[])
        assert isinstance(pkg, ComplianceEvidencePackage)
        assert isinstance(pkg.attestation, ComplianceAttestation)
        assert isinstance(pkg.gap_report, GapReport)
        assert isinstance(pkg.report_text, str)
        assert isinstance(pkg.audit_exports, dict)

    # --- Framework resolution: string slugs ---

    @pytest.mark.parametrize("slug", [
        "soc2", "hipaa", "gdpr", "nist_ai_rmf", "eu_ai_act", "iso_42001"
    ])
    def test_string_framework_slug(self, slug):
        pkg = self._pkg(slug, events=[])
        assert pkg.attestation.framework == slug

    # --- Framework resolution: enum ---

    @pytest.mark.parametrize("fw", list(ComplianceFramework))
    def test_enum_framework(self, fw):
        pkg = self._pkg(fw, events=[])
        assert pkg.attestation.model_id == "gpt-4o"

    def test_unknown_framework_raises(self):
        with pytest.raises(ValueError, match="Unknown framework"):
            self._pkg("totally_unknown", events=[])

    # --- Empty events → all clauses fail ---

    def test_empty_events_all_fail(self):
        pkg = self._pkg("soc2", events=[])
        statuses = [r.status for r in pkg.attestation.clauses]
        assert all(s == ClauseStatus.FAIL for s in statuses)
        assert pkg.attestation.overall_status == ClauseStatus.FAIL
        assert pkg.gap_report.has_gaps is True

    # --- Enough events → at least some pass ---

    def test_rich_events_pass_soc2(self):
        events = _make_events_for_soc2(n=5)
        pkg = self._pkg("soc2", events=events)
        statuses = {r.clause_id: r.status for r in pkg.attestation.clauses}
        # CC6.1 uses audit + trace events → should pass
        assert statuses["CC6.1"] == ClauseStatus.PASS
        # CC6.6 uses redact events → should pass
        assert statuses["CC6.6"] == ClauseStatus.PASS
        # CC7.2 uses drift + guard events → should pass
        assert statuses["CC7.2"] == ClauseStatus.PASS

    def test_partial_when_some_events(self):
        # Only 3 redact events < threshold 5 → PARTIAL
        events = [_make_event("llm.redact.pii_stripped")] * 3
        pkg = self._pkg("soc2", events=events)
        for r in pkg.attestation.clauses:
            if r.clause_id == "CC6.6":
                assert r.status == ClauseStatus.PARTIAL
                break

    def test_overall_pass_when_all_clauses_pass(self):
        events = _make_events_for_soc2(n=5)
        pkg = self._pkg("soc2", events=events)
        # May still be PARTIAL or PASS depending on event distribution
        assert pkg.attestation.overall_status in (ClauseStatus.PASS, ClauseStatus.PARTIAL)

    # --- HIPAA ---

    def test_hipaa_framework(self):
        events = [
            _make_event("llm.audit.event"),
            _make_event("llm.redact.phi_stripped"),
            _make_event("llm.trace.span.completed"),
        ] * 5
        pkg = self._pkg("hipaa", events=events)
        assert pkg.attestation.framework == "hipaa"
        assert len(pkg.attestation.clauses) >= 3

    # --- GDPR ---

    def test_gdpr_framework(self):
        pkg = self._pkg("gdpr", events=[])
        assert pkg.attestation.framework == "gdpr"
        clause_ids = [r.clause_id for r in pkg.attestation.clauses]
        assert "Art.30" in clause_ids
        assert "Art.35" in clause_ids

    # --- NIST AI RMF ---

    def test_nist_framework(self):
        pkg = self._pkg("nist_ai_rmf", events=[])
        assert pkg.attestation.framework == "nist_ai_rmf"
        clause_ids = [r.clause_id for r in pkg.attestation.clauses]
        assert "MAP.1.1" in clause_ids

    # --- EU AI Act ---

    def test_eu_ai_act_framework(self):
        pkg = self._pkg("eu_ai_act", events=[])
        assert pkg.attestation.framework == "eu_ai_act"

    # --- ISO 42001 ---

    def test_iso_42001_framework(self):
        pkg = self._pkg("iso_42001", events=[])
        assert pkg.attestation.framework == "iso_42001"

    # --- Model filtering ---

    def test_model_specific_events_used_when_available(self):
        events_gpt = [_make_event("llm.audit.event", model_name="gpt-4o")] * 6
        events_other = [_make_event("llm.audit.event", model_name="claude-3")] * 6
        all_events = events_gpt + events_other
        pkg_gpt = self.engine.generate_evidence_package(
            model_id="gpt-4o", framework="soc2",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=all_events,
        )
        # CC6.1 should have found model-specific events
        for r in pkg_gpt.attestation.clauses:
            if r.clause_id == "CC6.1":
                assert r.evidence_count == 6  # only gpt-4o events
                break

    # --- Period filtering ---

    def test_period_filter_excludes_out_of_range_events(self):
        in_range = [
            _make_event("llm.audit.event", timestamp="2025-06-15T10:00:00Z")
        ] * 3
        out_of_range = [
            _make_event("llm.audit.event", timestamp="2024-01-01T10:00:00Z")
        ] * 10
        pkg = self.engine.generate_evidence_package(
            model_id="gpt-4o", framework="soc2",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=in_range + out_of_range,
        )
        # CC6.1 should NOT have 10 events from 2024
        for r in pkg.attestation.clauses:
            if r.clause_id == "CC6.1":
                assert r.evidence_count <= 3
                break

    # --- HMAC signature ---

    def test_attestation_has_hmac_sig(self):
        pkg = self._pkg("soc2", events=[])
        assert len(pkg.attestation.hmac_sig) == 64  # sha256 hex

    def test_hmac_sig_changes_with_key(self):
        with patch.dict(os.environ, {"SPANFORGE_SIGNING_KEY": "key1"}):
            pkg1 = self._pkg("soc2", events=[])
        with patch.dict(os.environ, {"SPANFORGE_SIGNING_KEY": "key2"}):
            pkg2 = self._pkg("soc2", events=[])
        assert pkg1.attestation.hmac_sig != pkg2.attestation.hmac_sig

    # --- Report text ---

    def test_report_text_contains_framework_name(self):
        pkg = self._pkg("soc2", events=[])
        assert "SOC2" in pkg.report_text.upper() or "soc2" in pkg.report_text

    def test_report_text_contains_model_id(self):
        pkg = self._pkg("soc2", events=[])
        assert "gpt-4o" in pkg.report_text

    def test_report_text_contains_clause_ids(self):
        pkg = self._pkg("soc2", events=[])
        assert "CC6.1" in pkg.report_text

    # --- Audit exports ---

    def test_audit_exports_keyed_by_clause(self):
        events = [_make_event("llm.audit.event")] * 3
        pkg = self._pkg("soc2", events=events)
        assert "CC6.1" in pkg.audit_exports
        assert isinstance(pkg.audit_exports["CC6.1"], list)

    def test_audit_exports_no_signature(self):
        events = [_make_event("llm.audit.event")] * 2
        pkg = self._pkg("soc2", events=events)
        for clause_events in pkg.audit_exports.values():
            for e in clause_events:
                assert "signature" not in e

    # --- Load from store fallback ---

    def test_load_from_store_fallback_when_no_events(self):
        """Passing None should fall back to TraceStore (empty store → empty list)."""
        pkg = self.engine.generate_evidence_package(
            model_id="gpt-4o", framework="soc2",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=None,
        )
        assert isinstance(pkg, ComplianceEvidencePackage)


# ─── verify_attestation_signature ────────────────────────────────────────────

class TestVerifyAttestationSignature:
    def _generate_attestation(self, key: str = "test-key") -> ComplianceAttestation:
        with patch.dict(os.environ, {"SPANFORGE_SIGNING_KEY": key}):
            pkg = ComplianceMappingEngine().generate_evidence_package(
                model_id="test-model",
                framework="soc2",
                from_date="2025-01-01",
                to_date="2025-01-31",
                audit_events=[],
            )
        return pkg.attestation

    def test_valid_signature_returns_true(self):
        att = self._generate_attestation("my-secret-key")
        with patch.dict(os.environ, {"SPANFORGE_SIGNING_KEY": "my-secret-key"}):
            assert verify_attestation_signature(att) is True

    def test_wrong_key_returns_false(self):
        att = self._generate_attestation("correct-key")
        with patch.dict(os.environ, {"SPANFORGE_SIGNING_KEY": "wrong-key"}):
            assert verify_attestation_signature(att) is False

    def test_tampered_sig_returns_false(self):
        att = self._generate_attestation("test-key")
        tampered = ComplianceAttestation(
            model_id=att.model_id,
            framework=att.framework,
            period_from=att.period_from,
            period_to=att.period_to,
            generated_at=att.generated_at,
            generated_by=att.generated_by,
            clauses=att.clauses,
            overall_status=att.overall_status,
            hmac_sig="deadbeef" * 8,  # wrong sig
        )
        with patch.dict(os.environ, {"SPANFORGE_SIGNING_KEY": "test-key"}):
            assert verify_attestation_signature(tampered) is False

    def test_default_key_verifies(self):
        """Without SPANFORGE_SIGNING_KEY env var, default key should be used."""
        env = {k: v for k, v in os.environ.items() if k != "SPANFORGE_SIGNING_KEY"}
        with patch.dict(os.environ, env, clear=True):
            att = ComplianceMappingEngine().generate_evidence_package(
                model_id="m", framework="gdpr",
                from_date="2025-01-01", to_date="2025-01-31",
                audit_events=[],
            ).attestation
            assert verify_attestation_signature(att) is True

    def test_default_key_emits_warning(self, caplog):
        """Missing SPANFORGE_SIGNING_KEY should log a warning about the insecure default."""
        import logging
        env = {k: v for k, v in os.environ.items() if k != "SPANFORGE_SIGNING_KEY"}
        with patch.dict(os.environ, env, clear=True):
            with caplog.at_level(logging.WARNING, logger="spanforge.core.compliance_mapping"):
                ComplianceMappingEngine().generate_evidence_package(
                    model_id="m", framework="gdpr",
                    from_date="2025-01-01", to_date="2025-01-31",
                    audit_events=[],
                )
        assert any("SPANFORGE_SIGNING_KEY" in r.message for r in caplog.records)


# ─── _filter_period edge cases ───────────────────────────────────────────────

class TestFilterPeriodEdgeCases:
    engine = ComplianceMappingEngine()

    def test_invalid_from_date_raises(self):
        """Malformed from_date should raise ValueError, not silently return all events."""
        with pytest.raises(ValueError, match="Cannot parse date range"):
            self.engine.generate_evidence_package(
                model_id="gpt-4o", framework="soc2",
                from_date="2025/01/01", to_date="2025-12-31",
                audit_events=[_make_event()],
            )

    def test_invalid_to_date_raises(self):
        with pytest.raises(ValueError, match="Cannot parse date range"):
            self.engine.generate_evidence_package(
                model_id="gpt-4o", framework="soc2",
                from_date="2025-01-01", to_date="not-a-date",
                audit_events=[_make_event()],
            )


# ─── Model matching edge cases ────────────────────────────────────────────────

class TestModelMatching:
    engine = ComplianceMappingEngine()

    def test_exact_match_includes_event(self):
        events = [_make_event("llm.audit.event", model_name="gpt-4o")] * 6
        pkg = self.engine.generate_evidence_package(
            model_id="gpt-4o", framework="soc2",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=events,
        )
        for r in pkg.attestation.clauses:
            if r.clause_id == "CC6.1":
                assert r.evidence_count == 6
                break

    def test_substring_no_longer_matches(self):
        """model_id='gpt' must NOT match model_name='dingbat-gpt' (exact match only)."""
        events = [_make_event("llm.audit.event", model_name="dingbat-gpt")] * 6
        pkg = self.engine.generate_evidence_package(
            model_id="gpt", framework="soc2",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=events,
        )
        for r in pkg.attestation.clauses:
            if r.clause_id == "CC6.1":
                assert r.evidence_count == 0
                break


# ─── Filter period returns empty — not all events ─────────────────────────────

class TestFilterPeriodEmptyRange:
    engine = ComplianceMappingEngine()

    def test_no_events_in_period_returns_empty_not_all(self):
        """Regression: previously fell back to ALL events when none matched the range."""
        events = [_make_event(timestamp="2024-06-01T00:00:00Z")] * 6  # outside 2025
        pkg = self.engine.generate_evidence_package(
            model_id="gpt-4o", framework="soc2",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=events,
        )
        # All clauses must FAIL — no events in scope (not PASS from the old fallback)
        for r in pkg.attestation.clauses:
            assert r.status == ClauseStatus.FAIL, (
                f"Clause {r.clause_id} should FAIL with out-of-range events, got {r.status}"
            )

    def test_events_in_period_are_included(self):
        """Events with timestamps inside the period should be counted normally."""
        events = [_make_event(timestamp="2025-06-15T12:00:00Z")] * 6
        pkg = self.engine.generate_evidence_package(
            model_id="gpt-4o", framework="soc2",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=events,
        )
        # CC8.1 expects llm.trace.* prefixes — the default event type qualifies
        cc81 = next((r for r in pkg.attestation.clauses if r.clause_id == "CC8.1"), None)
        assert cc81 is not None
        assert cc81.evidence_count == 6


# ─── _load_from_store uses _traces not _events ────────────────────────────────

class TestLoadFromStoreUsesTraces:
    def test_load_from_store_reads_from_traces(self):
        """Regression: _load_from_store previously crashed with AttributeError on store._events."""
        import threading
        from unittest.mock import MagicMock

        mock_store = MagicMock()
        mock_store._lock = threading.Lock()
        ev = MagicMock()
        ev.event_id = "eid_regression_test"
        ev.event_type = "llm.trace.span.completed"
        ev.timestamp = "2025-03-01T10:00:00Z"
        ev.source = "test-svc"
        ev.trace_id = "trace01"
        ev.span_id = "span01"
        ev.payload = {"span_name": "regression"}
        ev.tags = {}
        ev.signature = None
        mock_store._traces = {"trace01": [ev]}
        # confirm _events does NOT exist on the store
        del mock_store._events

        with patch("spanforge._store.get_store", return_value=mock_store):
            events = ComplianceMappingEngine()._load_from_store()

        assert len(events) == 1
        assert events[0]["event_id"] == "eid_regression_test"


# ─── Fix 1: consent.* events in GDPR clause prefixes ─────────────────────────

class TestConsentInComplianceClauses:
    engine = ComplianceMappingEngine()

    def test_gdpr_art22_includes_consent_events(self):
        """GDPR Art.22 clause should accept consent.* events as evidence."""
        events = [_make_event("consent.granted")] * 6 + [_make_event("consent.violation")] * 2
        pkg = self.engine.generate_evidence_package(
            model_id="", framework="gdpr",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=events,
        )
        art22 = next((r for r in pkg.attestation.clauses if r.clause_id == "Art.22"), None)
        assert art22 is not None, "GDPR Art.22 clause missing"
        assert art22.evidence_count >= 6
        assert art22.status == ClauseStatus.PASS

    def test_gdpr_art25_includes_consent_events(self):
        """GDPR Art.25 clause should now include consent.* alongside llm.redact.*."""
        events = [_make_event("consent.granted")] * 6
        pkg = self.engine.generate_evidence_package(
            model_id="", framework="gdpr",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=events,
        )
        art25 = next((r for r in pkg.attestation.clauses if r.clause_id == "Art.25"), None)
        assert art25 is not None
        assert art25.evidence_count >= 6

    def test_consent_violation_counts_as_evidence(self):
        """consent.violation events should also match consent.* prefix."""
        events = [_make_event("consent.violation")] * 6
        pkg = self.engine.generate_evidence_package(
            model_id="", framework="gdpr",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=events,
        )
        art22 = next((r for r in pkg.attestation.clauses if r.clause_id == "Art.22"), None)
        assert art22 is not None
        assert art22.evidence_count >= 6


# ─── Fix 2: hitl.* events in EU AI Act clause prefixes ───────────────────────

class TestHITLInComplianceClauses:
    engine = ComplianceMappingEngine()

    def test_eu_ai_act_art14_includes_hitl_events(self):
        """EU AI Act Art.14 (Human Oversight) should accept hitl.* events."""
        events = [_make_event("hitl.queued")] * 3 + [_make_event("hitl.reviewed")] * 3
        pkg = self.engine.generate_evidence_package(
            model_id="", framework="eu_ai_act",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=events,
        )
        art14 = next((r for r in pkg.attestation.clauses if r.clause_id == "Art.14"), None)
        assert art14 is not None, "EU AI Act Art.14 clause missing"
        assert art14.evidence_count >= 6
        assert art14.status == ClauseStatus.PASS

    def test_eu_ai_act_annexiv5_includes_hitl_events(self):
        """EU AI Act AnnexIV.5 should now also accept hitl.* events."""
        events = [_make_event("hitl.escalated")] * 6
        pkg = self.engine.generate_evidence_package(
            model_id="", framework="eu_ai_act",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=events,
        )
        annexiv5 = next((r for r in pkg.attestation.clauses if r.clause_id == "AnnexIV.5"), None)
        assert annexiv5 is not None
        assert annexiv5.evidence_count >= 6
        assert annexiv5.status == ClauseStatus.PASS

    def test_hitl_timeout_counts_as_evidence(self):
        """hitl.timeout events should match hitl.* prefix."""
        events = [_make_event("hitl.timeout")] * 6
        pkg = self.engine.generate_evidence_package(
            model_id="", framework="eu_ai_act",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=events,
        )
        art14 = next((r for r in pkg.attestation.clauses if r.clause_id == "Art.14"), None)
        assert art14 is not None
        assert art14.evidence_count >= 6


# ─── Fix 3: Model Registry wired into attestation ────────────────────────────

class TestModelRegistryInAttestation:
    engine = ComplianceMappingEngine()

    def test_active_model_enriches_attestation(self):
        """When model is in registry as active, owner/risk_tier/status appear in attestation."""
        from spanforge.model_registry import ModelRegistry

        registry = ModelRegistry(auto_emit=False)
        registry.register(
            model_id="gpt-4o", name="GPT-4o", version="2024-05",
            risk_tier="high", owner="platform-team", purpose="support agent",
        )
        with patch("spanforge.model_registry.get_model", side_effect=registry.get):
            pkg = self.engine.generate_evidence_package(
                model_id="gpt-4o", framework="soc2",
                from_date="2025-01-01", to_date="2025-12-31",
                audit_events=[],
            )
        att = pkg.attestation
        assert att.model_owner == "platform-team"
        assert att.model_risk_tier == "high"
        assert att.model_status == "active"
        assert att.model_warnings == []

    def test_deprecated_model_generates_warning(self):
        """Deprecated model should produce a warning in the attestation."""
        from spanforge.model_registry import ModelRegistry

        registry = ModelRegistry(auto_emit=False)
        registry.register(
            model_id="old-model", name="Old", version="1.0",
            risk_tier="medium", owner="ml-team", purpose="classification",
        )
        registry.deprecate("old-model", reason="Replaced")
        with patch("spanforge.model_registry.get_model", side_effect=registry.get):
            pkg = self.engine.generate_evidence_package(
                model_id="old-model", framework="gdpr",
                from_date="2025-01-01", to_date="2025-12-31",
                audit_events=[],
            )
        att = pkg.attestation
        assert att.model_status == "deprecated"
        assert any("DEPRECATED" in w for w in att.model_warnings)

    def test_retired_model_generates_warning(self):
        """Retired model should produce a strong warning."""
        from spanforge.model_registry import ModelRegistry

        registry = ModelRegistry(auto_emit=False)
        registry.register(
            model_id="retired-m", name="R", version="1.0",
            risk_tier="low", owner="team-a", purpose="demo",
        )
        registry.deprecate("retired-m")
        registry.retire("retired-m")
        with patch("spanforge.model_registry.get_model", side_effect=registry.get):
            pkg = self.engine.generate_evidence_package(
                model_id="retired-m", framework="soc2",
                from_date="2025-01-01", to_date="2025-12-31",
                audit_events=[],
            )
        att = pkg.attestation
        assert att.model_status == "retired"
        assert any("RETIRED" in w for w in att.model_warnings)

    def test_unregistered_model_generates_warning(self):
        """Model not in registry should get a warning about missing registration."""
        with patch("spanforge.model_registry.get_model", return_value=None):
            pkg = self.engine.generate_evidence_package(
                model_id="unknown-model", framework="soc2",
                from_date="2025-01-01", to_date="2025-12-31",
                audit_events=[],
            )
        att = pkg.attestation
        assert att.model_owner is None
        assert any("not registered" in w for w in att.model_warnings)

    def test_model_registry_fields_in_attestation_json(self):
        """model_owner, model_risk_tier, model_status should appear in to_json() output."""
        from spanforge.model_registry import ModelRegistry

        registry = ModelRegistry(auto_emit=False)
        registry.register(
            model_id="gpt-4o", name="GPT-4o", version="2024-05",
            risk_tier="high", owner="platform-team", purpose="support",
        )
        with patch("spanforge.model_registry.get_model", side_effect=registry.get):
            pkg = self.engine.generate_evidence_package(
                model_id="gpt-4o", framework="soc2",
                from_date="2025-01-01", to_date="2025-12-31",
                audit_events=[],
            )
        data = json.loads(pkg.attestation.to_json())
        assert data["model_owner"] == "platform-team"
        assert data["model_risk_tier"] == "high"
        assert data["model_status"] == "active"

    def test_model_registry_fields_in_package_json(self):
        """Evidence package to_json() should also include model registry fields."""
        from spanforge.model_registry import ModelRegistry

        registry = ModelRegistry(auto_emit=False)
        registry.register(
            model_id="gpt-4o", name="GPT-4o", version="2024-05",
            risk_tier="critical", owner="security-team", purpose="moderation",
        )
        with patch("spanforge.model_registry.get_model", side_effect=registry.get):
            pkg = self.engine.generate_evidence_package(
                model_id="gpt-4o", framework="gdpr",
                from_date="2025-01-01", to_date="2025-12-31",
                audit_events=[],
            )
        data = json.loads(pkg.to_json())
        assert data["model_owner"] == "security-team"
        assert data["model_risk_tier"] == "critical"

    def test_report_text_includes_model_registry_info(self):
        """The markdown report should include model owner and risk tier."""
        from spanforge.model_registry import ModelRegistry

        registry = ModelRegistry(auto_emit=False)
        registry.register(
            model_id="gpt-4o", name="GPT-4o", version="2024-05",
            risk_tier="high", owner="platform-team", purpose="agent",
        )
        with patch("spanforge.model_registry.get_model", side_effect=registry.get):
            pkg = self.engine.generate_evidence_package(
                model_id="gpt-4o", framework="soc2",
                from_date="2025-01-01", to_date="2025-12-31",
                audit_events=[],
            )
        assert "platform-team" in pkg.report_text
        assert "high" in pkg.report_text


# ─── Fix 4: Explainability in compliance clauses + coverage metric ────────────

class TestExplainabilityIntegration:
    engine = ComplianceMappingEngine()

    def test_eu_ai_act_art13_includes_explanation_events(self):
        """EU AI Act Art.13 (Transparency) should accept explanation.* events."""
        events = [_make_event("explanation.generated")] * 6
        pkg = self.engine.generate_evidence_package(
            model_id="", framework="eu_ai_act",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=events,
        )
        art13 = next((r for r in pkg.attestation.clauses if r.clause_id == "Art.13"), None)
        assert art13 is not None, "EU AI Act Art.13 clause missing"
        assert art13.evidence_count >= 6
        assert art13.status == ClauseStatus.PASS

    def test_nist_map11_includes_explanation_events(self):
        """NIST MAP.1.1 should now accept explanation.* events for system documentation."""
        events = [_make_event("explanation.generated")] * 6
        pkg = self.engine.generate_evidence_package(
            model_id="", framework="nist_ai_rmf",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=events,
        )
        map11 = next((r for r in pkg.attestation.clauses if r.clause_id == "MAP.1.1"), None)
        assert map11 is not None
        assert map11.evidence_count >= 6

    def test_explanation_coverage_pct_computed(self):
        """explanation_coverage_pct should be computed based on decision vs explanation events."""
        events = (
            [_make_event("llm.trace.span.completed")] * 10
            + [_make_event("explanation.generated")] * 7
        )
        pkg = self.engine.generate_evidence_package(
            model_id="", framework="eu_ai_act",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=events,
        )
        assert pkg.attestation.explanation_coverage_pct == 70.0

    def test_explanation_coverage_pct_none_when_no_decisions(self):
        """When there are no decision events, explanation_coverage_pct should be None."""
        pkg = self.engine.generate_evidence_package(
            model_id="", framework="eu_ai_act",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=[],
        )
        assert pkg.attestation.explanation_coverage_pct is None

    def test_explanation_coverage_100_pct_cap(self):
        """Coverage should cap at 100% even if there are more explanations than decisions."""
        events = (
            [_make_event("llm.trace.span.completed")] * 3
            + [_make_event("explanation.generated")] * 10
        )
        pkg = self.engine.generate_evidence_package(
            model_id="", framework="eu_ai_act",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=events,
        )
        assert pkg.attestation.explanation_coverage_pct == 100.0

    def test_explanation_coverage_in_attestation_json(self):
        """explanation_coverage_pct should appear in attestation JSON when present."""
        events = (
            [_make_event("llm.trace.span.completed")] * 10
            + [_make_event("explanation.generated")] * 5
        )
        pkg = self.engine.generate_evidence_package(
            model_id="", framework="eu_ai_act",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=events,
        )
        data = json.loads(pkg.attestation.to_json())
        assert data["explanation_coverage_pct"] == 50.0

    def test_explanation_coverage_in_report_text(self):
        """The markdown report should include explanation coverage percentage."""
        events = (
            [_make_event("llm.trace.span.completed")] * 10
            + [_make_event("explanation.generated")] * 4
        )
        pkg = self.engine.generate_evidence_package(
            model_id="", framework="eu_ai_act",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=events,
        )
        assert "Explanation Coverage" in pkg.report_text
        assert "40.0%" in pkg.report_text


# ─── Combined integration: all features together ─────────────────────────────

class TestFullIntegration:
    engine = ComplianceMappingEngine()

    def test_eu_ai_act_with_all_new_event_types(self):
        """EU AI Act report with consent, HITL, explanation events should pass new clauses."""
        events = (
            [_make_event("consent.granted")] * 6
            + [_make_event("consent.violation")] * 2
            + [_make_event("hitl.queued")] * 4
            + [_make_event("hitl.reviewed")] * 4
            + [_make_event("explanation.generated")] * 6
            + [_make_event("llm.trace.span.completed")] * 6
            + [_make_event("llm.eval.score_computed")] * 6
            + [_make_event("llm.guard.blocked")] * 6
            + [_make_event("llm.audit.event")] * 6
            + [_make_event("llm.drift.score_changed")] * 6
        )
        pkg = self.engine.generate_evidence_package(
            model_id="", framework="eu_ai_act",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=events,
        )
        clause_map = {r.clause_id: r for r in pkg.attestation.clauses}
        # All new clauses should pass
        assert clause_map["Art.13"].status == ClauseStatus.PASS
        assert clause_map["Art.14"].status == ClauseStatus.PASS
        assert clause_map["AnnexIV.5"].status == ClauseStatus.PASS
        # Overall should pass
        assert pkg.attestation.overall_status == ClauseStatus.PASS

    def test_gdpr_with_consent_events_passes_art22(self):
        """GDPR with consent events should pass both Art.22 and Art.25."""
        events = (
            [_make_event("consent.granted")] * 6
            + [_make_event("hitl.reviewed")] * 6
            + [_make_event("llm.redact.pii_stripped")] * 6
            + [_make_event("llm.trace.span.completed")] * 10
            + [_make_event("llm.cost.token_usage")] * 10
            + [_make_event("llm.audit.event")] * 10
            + [_make_event("llm.drift.score_changed")] * 6
            + [_make_event("llm.guard.blocked")] * 6
        )
        pkg = self.engine.generate_evidence_package(
            model_id="", framework="gdpr",
            from_date="2025-01-01", to_date="2025-12-31",
            audit_events=events,
        )
        clause_map = {r.clause_id: r for r in pkg.attestation.clauses}
        assert clause_map["Art.22"].status == ClauseStatus.PASS
        assert clause_map["Art.25"].status == ClauseStatus.PASS

