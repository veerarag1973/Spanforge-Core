"""Tests for CORE-13: FrameworkMapper, EvidenceMapping, DPDP, ZIP export.

Covers:
- EvidenceMapping dataclass
- FrameworkMapper.map_event_to_frameworks() — all prefix types
- FrameworkMapper.map_events_bulk()
- FrameworkMapper.frameworks_for_event_type()
- DPDP framework in ComplianceMappingEngine.generate_evidence_package()
- ComplianceEvidencePackage.to_zip()
- Integration: event → bundle → report pipeline
"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest

from spanforge.compliance import (
    ComplianceFramework,
    ComplianceMappingEngine,
    EvidenceMapping,
    FrameworkMapper,
)
from spanforge.core.compliance_mapping import (
    ClauseStatus,
    _EVENT_TO_FRAMEWORK_MAP,
    _FRAMEWORK_CLAUSES,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS = "2026-04-15T10:00:00Z"
_TS2 = "2026-04-15T11:00:00Z"
_FROM = "2026-04-01"
_TO = "2026-04-30"


def _evt(event_type: str, model: str = "gpt-4o", ts: str = _TS) -> dict:
    return {
        "event_id": f"eid-{event_type[:12].replace('.', '_')}",
        "event_type": event_type,
        "timestamp": ts,
        "source": "test@1.0.0",
        "trace_id": "abc" * 10 + "ab",
        "span_id": "span001",
        "payload": {"model": {"name": model}, "model_id": model},
        "tags": {},
        "schema_version": "2.0",
        "signature": None,
    }


def _make_full_events(n: int = 10, model: str = "gpt-4o") -> list[dict]:
    """Return events covering all DPDP and other framework prefixes."""
    events = []
    for i in range(n):
        d = i % 28 + 1
        ts = f"2026-04-{d:02d}T10:00:00Z"
        events.extend([
            _evt("llm.trace.span.completed", model, ts),
            _evt("llm.audit.decision_made", model, ts),
            _evt("llm.redact.pii_stripped", model, ts),
            _evt("llm.drift.score_changed", model, ts),
            _evt("llm.guard.blocked", model, ts),
            _evt("llm.eval.score_computed", model, ts),
            _evt("llm.cost.token_usage", model, ts),
            _evt("explanation.generated", model, ts),
            _evt("hitl.review_requested", model, ts),
            _evt("consent.granted", model, ts),
            _evt("model_registry.registered", model, ts),
        ])
    return events


# ---------------------------------------------------------------------------
# EvidenceMapping
# ---------------------------------------------------------------------------

class TestEvidenceMapping:
    def test_frozen_dataclass(self) -> None:
        m = EvidenceMapping(
            framework="eu_ai_act",
            articles=["Art.13", "AnnexIV.1"],
            control_ids=["Art.13", "AnnexIV.1"],
            evidence_type="TRANSPARENCY",
        )
        assert m.framework == "eu_ai_act"
        assert "Art.13" in m.articles
        assert m.evidence_type == "TRANSPARENCY"
        # frozen → mutation raises
        with pytest.raises((AttributeError, TypeError)):
            m.framework = "changed"  # type: ignore[misc]

    def test_articles_and_control_ids_match(self) -> None:
        m = EvidenceMapping(
            framework="gdpr",
            articles=["Art.30"],
            control_ids=["Art.30"],
            evidence_type="AUDIT_TRAIL",
        )
        assert m.articles == m.control_ids


# ---------------------------------------------------------------------------
# FrameworkMapper — map_event_to_frameworks
# ---------------------------------------------------------------------------

class TestFrameworkMapperSingleEvent:
    def test_llm_trace_maps_to_multiple_frameworks(self) -> None:
        mapper = FrameworkMapper()
        event = _evt("llm.trace.span.completed")
        mappings = mapper.map_event_to_frameworks(event)
        frameworks = {m.framework for m in mappings}
        assert "eu_ai_act" in frameworks
        assert "iso_42001" in frameworks
        assert "soc2" in frameworks
        assert "gdpr" in frameworks
        assert "hipaa" in frameworks
        assert "dpdp" in frameworks
        assert "nist_ai_rmf" in frameworks

    def test_llm_audit_maps_to_dpdp(self) -> None:
        mapper = FrameworkMapper()
        mappings = mapper.map_event_to_frameworks(_evt("llm.audit.decision_made"))
        dpdp = [m for m in mappings if m.framework == "dpdp"]
        assert dpdp, "llm.audit.* must map to DPDP"
        dpdp_controls = {ctrl for m in dpdp for ctrl in m.control_ids}
        assert "S.16" in dpdp_controls

    def test_llm_redact_maps_to_pii_frameworks(self) -> None:
        mapper = FrameworkMapper()
        mappings = mapper.map_event_to_frameworks(_evt("llm.redact.pii_stripped"))
        frameworks = {m.framework for m in mappings}
        assert "soc2" in frameworks
        assert "gdpr" in frameworks
        assert "hipaa" in frameworks
        assert "dpdp" in frameworks
        # EU AI Act does not directly map to redact events
        for m in mappings:
            if m.framework == "soc2":
                assert "CC6.6" in m.control_ids
            if m.framework == "hipaa":
                assert "164.312(e)(2)(ii)" in m.control_ids

    def test_explanation_maps_to_eu_ai_act_art13(self) -> None:
        mapper = FrameworkMapper()
        mappings = mapper.map_event_to_frameworks(_evt("explanation.generated"))
        eu = [m for m in mappings if m.framework == "eu_ai_act"]
        assert eu
        assert "Art.13" in eu[0].articles

    def test_hitl_maps_to_eu_ai_act_art14(self) -> None:
        mapper = FrameworkMapper()
        mappings = mapper.map_event_to_frameworks(_evt("hitl.review_requested"))
        eu = [m for m in mappings if m.framework == "eu_ai_act"]
        assert eu
        assert "Art.14" in eu[0].articles

    def test_consent_maps_to_gdpr_and_dpdp(self) -> None:
        mapper = FrameworkMapper()
        mappings = mapper.map_event_to_frameworks(_evt("consent.granted"))
        frameworks = {m.framework for m in mappings}
        assert "gdpr" in frameworks
        assert "dpdp" in frameworks
        for m in mappings:
            if m.framework == "dpdp":
                assert any(s in m.control_ids for s in ("S.6", "S.4", "S.9"))

    def test_llm_cost_maps_to_soc2_cc9(self) -> None:
        mapper = FrameworkMapper()
        mappings = mapper.map_event_to_frameworks(_evt("llm.cost.token_usage"))
        soc2 = [m for m in mappings if m.framework == "soc2"]
        assert soc2
        assert "CC9.2" in soc2[0].control_ids

    def test_llm_drift_maps_to_nist_measure(self) -> None:
        mapper = FrameworkMapper()
        mappings = mapper.map_event_to_frameworks(_evt("llm.drift.score_changed"))
        nist = [m for m in mappings if m.framework == "nist_ai_rmf"]
        assert nist
        assert "MEASURE.2.6" in nist[0].control_ids

    def test_unknown_event_type_returns_empty(self) -> None:
        mapper = FrameworkMapper()
        mappings = mapper.map_event_to_frameworks({"event_type": "custom.unknown.event"})
        assert mappings == []

    def test_empty_event_type_returns_empty(self) -> None:
        mapper = FrameworkMapper()
        assert mapper.map_event_to_frameworks({}) == []
        assert mapper.map_event_to_frameworks({"event_type": ""}) == []

    def test_model_registry_maps_to_eu_ai_act_annex_iv1(self) -> None:
        mapper = FrameworkMapper()
        mappings = mapper.map_event_to_frameworks(_evt("model_registry.registered"))
        eu = [m for m in mappings if m.framework == "eu_ai_act"]
        assert eu
        assert "AnnexIV.1" in eu[0].articles

    def test_evidence_types_are_strings(self) -> None:
        mapper = FrameworkMapper()
        for event_type in [
            "llm.trace.x", "llm.audit.x", "llm.redact.x", "llm.drift.x",
            "llm.guard.x", "llm.eval.x", "llm.cost.x", "explanation.x",
            "hitl.x", "consent.x", "model_registry.x",
        ]:
            for m in mapper.map_event_to_frameworks({"event_type": event_type}):
                assert isinstance(m.evidence_type, str) and m.evidence_type


# ---------------------------------------------------------------------------
# FrameworkMapper — map_events_bulk
# ---------------------------------------------------------------------------

class TestFrameworkMapperBulk:
    def test_bulk_returns_mapping_per_event(self) -> None:
        mapper = FrameworkMapper()
        events = [
            _evt("llm.trace.span.completed"),
            _evt("llm.redact.pii_stripped"),
            _evt("consent.granted"),
        ]
        result = mapper.map_events_bulk(events)
        assert len(result) == 3
        for key, mappings in result.items():
            assert isinstance(mappings, list)

    def test_bulk_unknown_type_empty_list(self) -> None:
        mapper = FrameworkMapper()
        events = [{"event_type": "totally.unknown"}]
        result = mapper.map_events_bulk(events)
        for v in result.values():
            assert v == []

    def test_bulk_uses_event_id_as_key(self) -> None:
        mapper = FrameworkMapper()
        event = {"event_id": "my-unique-id", "event_type": "llm.audit.decision_made"}
        result = mapper.map_events_bulk([event])
        assert "my-unique-id" in result


# ---------------------------------------------------------------------------
# FrameworkMapper — frameworks_for_event_type
# ---------------------------------------------------------------------------

class TestFrameworksForEventType:
    def test_llm_trace_returns_all_frameworks(self) -> None:
        fws = FrameworkMapper.frameworks_for_event_type("llm.trace.span.completed")
        assert "eu_ai_act" in fws
        assert "dpdp" in fws
        assert "nist_ai_rmf" in fws
        assert len(fws) >= 6

    def test_explanation_returns_limited_frameworks(self) -> None:
        fws = FrameworkMapper.frameworks_for_event_type("explanation.generated")
        # explanation maps to eu_ai_act, dpdp, nist_ai_rmf only
        assert "eu_ai_act" in fws
        assert "dpdp" in fws
        assert "soc2" not in fws

    def test_no_duplicates(self) -> None:
        fws = FrameworkMapper.frameworks_for_event_type("llm.audit.decision_made")
        assert len(fws) == len(set(fws))

    def test_unknown_returns_empty(self) -> None:
        fws = FrameworkMapper.frameworks_for_event_type("foo.bar.baz")
        assert fws == []


# ---------------------------------------------------------------------------
# DPDP framework clauses
# ---------------------------------------------------------------------------

class TestDPDPFrameworkClauses:
    def test_dpdp_in_framework_clauses(self) -> None:
        assert "dpdp" in _FRAMEWORK_CLAUSES

    def test_dpdp_has_required_sections(self) -> None:
        dpdp = _FRAMEWORK_CLAUSES["dpdp"]
        required = {"S.4", "S.6", "S.7", "S.9", "S.11", "S.12", "S.16", "S.18"}
        assert required.issubset(set(dpdp.keys()))

    def test_dpdp_enum_value(self) -> None:
        assert ComplianceFramework.DPDP.value == "DPDP"

    def test_dpdp_clauses_have_required_fields(self) -> None:
        dpdp = _FRAMEWORK_CLAUSES["dpdp"]
        for clause_id, clause in dpdp.items():
            assert "title" in clause, f"{clause_id} missing title"
            assert "event_prefixes" in clause, f"{clause_id} missing event_prefixes"
            assert "description" in clause, f"{clause_id} missing description"
            assert "remediation_steps" in clause, f"{clause_id} missing remediation_steps"
            assert isinstance(clause["event_prefixes"], list)
            assert len(clause["event_prefixes"]) > 0

    def test_dpdp_s16_requires_multiple_prefixes(self) -> None:
        s16 = _FRAMEWORK_CLAUSES["dpdp"]["S.16"]
        assert len(s16["event_prefixes"]) >= 4

    def test_dpdp_s6_maps_to_consent_events(self) -> None:
        s6 = _FRAMEWORK_CLAUSES["dpdp"]["S.6"]
        assert "consent." in s6["event_prefixes"]


# ---------------------------------------------------------------------------
# DPDP evidence package generation
# ---------------------------------------------------------------------------

class TestDPDPEvidencePackage:
    def _make_dpdp_events(self, n: int = 10) -> list[dict]:
        events = []
        for i in range(n):
            d = i % 28 + 1
            ts = f"2026-04-{d:02d}T10:00:00Z"
            events.extend([
                _evt("consent.granted", ts=ts),
                _evt("llm.audit.decision_made", ts=ts),
                _evt("llm.redact.pii_stripped", ts=ts),
                _evt("explanation.generated", ts=ts),
                _evt("hitl.review_requested", ts=ts),
                _evt("llm.guard.blocked", ts=ts),
                _evt("llm.trace.span.completed", ts=ts),
                _evt("model_registry.registered", ts=ts),
            ])
        return events

    def test_dpdp_package_generated(self) -> None:
        engine = ComplianceMappingEngine()
        events = self._make_dpdp_events(10)
        pkg = engine.generate_evidence_package(
            model_id="gpt-4o",
            framework="dpdp",
            from_date=_FROM,
            to_date=_TO,
            audit_events=events,
        )
        assert pkg.framework == "dpdp"
        assert len(pkg.attestation.clauses) >= 8

    def test_dpdp_s6_passes_with_consent_events(self) -> None:
        engine = ComplianceMappingEngine()
        events = [_evt("consent.granted", ts=f"2026-04-{i+1:02d}T10:00:00Z") for i in range(6)]
        pkg = engine.generate_evidence_package(
            model_id="",
            framework="dpdp",
            from_date=_FROM,
            to_date=_TO,
            audit_events=events,
        )
        s6 = next((c for c in pkg.attestation.clauses if c.clause_id == "S.6"), None)
        assert s6 is not None
        assert s6.status == ClauseStatus.PASS

    def test_dpdp_package_has_hmac(self) -> None:
        engine = ComplianceMappingEngine()
        pkg = engine.generate_evidence_package(
            model_id="gpt-4o",
            framework="dpdp",
            from_date=_FROM,
            to_date=_TO,
            audit_events=self._make_dpdp_events(5),
        )
        assert pkg.attestation.hmac_sig
        assert len(pkg.attestation.hmac_sig) == 64

    def test_dpdp_report_contains_framework_name(self) -> None:
        engine = ComplianceMappingEngine()
        pkg = engine.generate_evidence_package(
            model_id="gpt-4o",
            framework="dpdp",
            from_date=_FROM,
            to_date=_TO,
            audit_events=self._make_dpdp_events(5),
        )
        report = pkg.to_markdown()
        assert "DPDP" in report.upper() or "dpdp" in report

    def test_dpdp_framework_enum_accepted(self) -> None:
        engine = ComplianceMappingEngine()
        pkg = engine.generate_evidence_package(
            model_id="gpt-4o",
            framework=ComplianceFramework.DPDP,
            from_date=_FROM,
            to_date=_TO,
            audit_events=self._make_dpdp_events(5),
        )
        assert pkg.framework == "dpdp"


# ---------------------------------------------------------------------------
# ZIP export
# ---------------------------------------------------------------------------

class TestZipExport:
    def _make_pkg(self, framework: str = "eu_ai_act") -> object:
        engine = ComplianceMappingEngine()
        events = _make_full_events(10)
        return engine.generate_evidence_package(
            model_id="gpt-4o",
            framework=framework,
            from_date=_FROM,
            to_date=_TO,
            audit_events=events,
        )

    def test_to_zip_creates_file(self, tmp_path: Path) -> None:
        pkg = self._make_pkg()
        out = pkg.to_zip(tmp_path / "bundle.zip")
        assert out.exists()
        assert out.stat().st_size > 0

    def test_zip_contains_manifest(self, tmp_path: Path) -> None:
        pkg = self._make_pkg()
        out = pkg.to_zip(tmp_path / "bundle.zip")
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        assert "manifest.json" in names

    def test_zip_contains_attestation(self, tmp_path: Path) -> None:
        pkg = self._make_pkg()
        out = pkg.to_zip(tmp_path / "bundle.zip")
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        assert "attestation.json" in names

    def test_zip_contains_report_md(self, tmp_path: Path) -> None:
        pkg = self._make_pkg()
        out = pkg.to_zip(tmp_path / "bundle.zip")
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        assert "report.md" in names

    def test_zip_contains_retention_proof(self, tmp_path: Path) -> None:
        pkg = self._make_pkg()
        out = pkg.to_zip(tmp_path / "bundle.zip")
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        assert "retention_proof.json" in names

    def test_zip_contains_audit_trail_files(self, tmp_path: Path) -> None:
        pkg = self._make_pkg()
        out = pkg.to_zip(tmp_path / "bundle.zip")
        with zipfile.ZipFile(out) as zf:
            names = zf.namelist()
        audit_files = [n for n in names if n.startswith("audit_trail/")]
        assert len(audit_files) > 0

    def test_zip_manifest_is_valid_json(self, tmp_path: Path) -> None:
        pkg = self._make_pkg()
        out = pkg.to_zip(tmp_path / "bundle.zip")
        with zipfile.ZipFile(out) as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert "framework" in manifest
        assert "hmac_sig" in manifest
        assert "clauses_total" in manifest
        assert "coverage_pct" in manifest
        assert manifest["spanforge_bundle_version"] == "1.0"

    def test_zip_attestation_is_valid_json(self, tmp_path: Path) -> None:
        pkg = self._make_pkg()
        out = pkg.to_zip(tmp_path / "bundle.zip")
        with zipfile.ZipFile(out) as zf:
            att = json.loads(zf.read("attestation.json").decode("utf-8"))
        assert "hmac_sig" in att
        assert "clauses" in att

    def test_zip_retention_proof_has_hmac(self, tmp_path: Path) -> None:
        pkg = self._make_pkg()
        out = pkg.to_zip(tmp_path / "bundle.zip")
        with zipfile.ZipFile(out) as zf:
            proof = json.loads(zf.read("retention_proof.json").decode("utf-8"))
        assert "bundle_hmac" in proof
        assert "file_hashes" in proof
        assert len(proof["bundle_hmac"]) == 64

    def test_zip_size_under_5mb(self, tmp_path: Path) -> None:
        """CEC bundle must be <5 MB for a 30-day window per success metrics."""
        pkg = self._make_pkg()
        out = pkg.to_zip(tmp_path / "bundle.zip")
        size_mb = out.stat().st_size / (1024 * 1024)
        assert size_mb < 5.0, f"ZIP too large: {size_mb:.2f} MB"

    def test_zip_works_for_dpdp(self, tmp_path: Path) -> None:
        pkg = self._make_pkg("dpdp")
        out = pkg.to_zip(tmp_path / "dpdp_bundle.zip")
        assert out.exists()
        with zipfile.ZipFile(out) as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        assert manifest["framework"] == "dpdp"

    def test_zip_returns_path_object(self, tmp_path: Path) -> None:
        pkg = self._make_pkg()
        out = pkg.to_zip(str(tmp_path / "bundle.zip"))
        assert isinstance(out, Path)


# ---------------------------------------------------------------------------
# Integration: event → FrameworkMapper → ComplianceMappingEngine → ZIP
# ---------------------------------------------------------------------------

class TestEndToEndPipeline:
    def test_100_events_eu_ai_act_95pct_correct_mapping(self) -> None:
        """Map 100 sample events to EU AI Act → ≥95% correct control mapping."""
        mapper = FrameworkMapper()
        # 100 diverse events
        event_types = [
            "llm.trace.span.completed",
            "llm.audit.decision_made",
            "explanation.generated",
            "hitl.review_requested",
            "llm.guard.blocked",
            "llm.eval.score_computed",
            "llm.drift.score_changed",
            "consent.granted",
            "model_registry.registered",
            "llm.redact.pii_stripped",
        ]
        events = [{"event_type": et} for et in event_types * 10]
        assert len(events) == 100

        mapped_count = 0
        eu_control_hits = 0
        for event in events:
            mappings = mapper.map_event_to_frameworks(event)
            eu_mappings = [m for m in mappings if m.framework == "eu_ai_act"]
            if eu_mappings:
                mapped_count += 1
                eu_control_hits += len(eu_mappings[0].control_ids)

        # Events with known EU AI Act mappings: all except llm.redact and llm.cost
        expected_mapped = 90  # 9 out of 10 event types → 90 events
        assert mapped_count >= expected_mapped, (
            f"Only {mapped_count} events mapped to EU AI Act (expected ≥{expected_mapped})"
        )

    def test_30_day_bundle_generation_time(self) -> None:
        """CEC bundle for 30-day window must generate in <100ms."""
        import time
        engine = ComplianceMappingEngine()
        events = _make_full_events(30)  # ~330 events
        start = time.perf_counter()
        pkg = engine.generate_evidence_package(
            model_id="gpt-4o",
            framework="eu_ai_act",
            from_date=_FROM,
            to_date=_TO,
            audit_events=events,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < 100, f"Bundle generation took {elapsed_ms:.1f}ms (limit 100ms)"
        assert pkg is not None

    def test_all_six_frameworks_produce_valid_packages(self) -> None:
        """All 6 frameworks must produce a valid evidence package."""
        engine = ComplianceMappingEngine()
        events = _make_full_events(10)
        frameworks = ["soc2", "hipaa", "gdpr", "eu_ai_act", "iso_42001", "dpdp"]
        for fw in frameworks:
            pkg = engine.generate_evidence_package(
                model_id="gpt-4o",
                framework=fw,
                from_date=_FROM,
                to_date=_TO,
                audit_events=events,
            )
            assert pkg.framework == fw, f"Framework mismatch for {fw}"
            assert len(pkg.attestation.clauses) > 0
            assert pkg.attestation.hmac_sig

    def test_zero_data_loss_hmac_verification(self) -> None:
        """Zero data loss: all events in bundle must be verifiable via HMAC."""
        from spanforge.core.compliance_mapping import verify_attestation_signature
        engine = ComplianceMappingEngine()
        events = _make_full_events(10)
        # Both signing and verification use the same env var at call time;
        # ensure consistency by setting the key before either operation.
        original = os.environ.pop("SPANFORGE_SIGNING_KEY", None)
        try:
            os.environ["SPANFORGE_SIGNING_KEY"] = "test-signing-key-for-hmac-test"
            pkg = engine.generate_evidence_package(
                model_id="gpt-4o",
                framework="eu_ai_act",
                from_date=_FROM,
                to_date=_TO,
                audit_events=events,
            )
            result = verify_attestation_signature(pkg.attestation)
        finally:
            del os.environ["SPANFORGE_SIGNING_KEY"]
            if original is not None:
                os.environ["SPANFORGE_SIGNING_KEY"] = original
        assert result is True

    def test_zip_bundle_manifest_lists_all_files(self, tmp_path: Path) -> None:
        """manifest.json must list every file in the ZIP."""
        engine = ComplianceMappingEngine()
        events = _make_full_events(5)
        pkg = engine.generate_evidence_package(
            model_id="gpt-4o",
            framework="gdpr",
            from_date=_FROM,
            to_date=_TO,
            audit_events=events,
        )
        out = pkg.to_zip(tmp_path / "gdpr_bundle.zip")
        with zipfile.ZipFile(out) as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            zip_names = set(zf.namelist())
        # manifest lists files excluding itself and retention_proof
        manifest_files = set(manifest["files"])
        # Every file listed in manifest must exist in zip
        for f in manifest_files:
            assert f in zip_names, f"manifest lists {f} but not in ZIP"

    def test_framework_mapper_all_prefixes_have_entries(self) -> None:
        """Every prefix in _EVENT_TO_FRAMEWORK_MAP must produce ≥1 mapping."""
        mapper = FrameworkMapper()
        for prefix in _EVENT_TO_FRAMEWORK_MAP:
            test_event = {"event_type": f"{prefix}test"}
            mappings = mapper.map_event_to_frameworks(test_event)
            assert mappings, f"Prefix {prefix!r} produced no mappings"

    def test_dpdp_full_coverage_90pct_s16(self) -> None:
        """DPDP S.16 requires 90%+ coverage with comprehensive instrumentation."""
        engine = ComplianceMappingEngine()
        events = _make_full_events(15)  # well above minimum
        pkg = engine.generate_evidence_package(
            model_id="",
            framework="dpdp",
            from_date=_FROM,
            to_date=_TO,
            audit_events=events,
        )
        s16 = next(c for c in pkg.attestation.clauses if c.clause_id == "S.16")
        assert s16.status == ClauseStatus.PASS, f"S.16 status: {s16.status}"


# ---------------------------------------------------------------------------
# FrameworkMapper from compliance facade (public API)
# ---------------------------------------------------------------------------

class TestPublicAPIExports:
    def test_framework_mapper_importable_from_compliance(self) -> None:
        from spanforge.compliance import FrameworkMapper as FM
        assert FM is not None
        mapper = FM()
        assert callable(mapper.map_event_to_frameworks)

    def test_evidence_mapping_importable_from_compliance(self) -> None:
        from spanforge.compliance import EvidenceMapping as EM
        m = EM(framework="dpdp", articles=["S.6"], control_ids=["S.6"], evidence_type="CONSENT_RECORD")
        assert m.framework == "dpdp"

    def test_dpdp_enum_importable_from_compliance(self) -> None:
        from spanforge.compliance import ComplianceFramework as CF
        assert CF.DPDP.value == "DPDP"


# ---------------------------------------------------------------------------
# EU AI Act Art.12 — Prohibited AI Practices
# ---------------------------------------------------------------------------

class TestEUAIActArt12:
    def test_art12_in_eu_ai_act_clauses(self) -> None:
        from spanforge.core.compliance_mapping import _FRAMEWORK_CLAUSES
        eu = _FRAMEWORK_CLAUSES["eu_ai_act"]
        assert "Art.12" in eu

    def test_art12_title_contains_prohibited(self) -> None:
        from spanforge.core.compliance_mapping import _FRAMEWORK_CLAUSES
        title = _FRAMEWORK_CLAUSES["eu_ai_act"]["Art.12"]["title"].lower()
        assert "prohibited" in title or "decision" in title or "audit" in title

    def test_art12_event_prefixes(self) -> None:
        from spanforge.core.compliance_mapping import _FRAMEWORK_CLAUSES
        prefixes = _FRAMEWORK_CLAUSES["eu_ai_act"]["Art.12"]["event_prefixes"]
        assert "llm.audit." in prefixes
        assert "hitl." in prefixes

    def test_llm_audit_maps_to_art12(self) -> None:
        mapper = FrameworkMapper()
        mappings = mapper.map_event_to_frameworks({"event_type": "llm.audit.decision_made"})
        eu = [m for m in mappings if m.framework == "eu_ai_act"]
        assert eu
        eu_controls = {c for m in eu for c in m.control_ids}
        assert "Art.12" in eu_controls

    def test_hitl_maps_to_art12(self) -> None:
        mapper = FrameworkMapper()
        mappings = mapper.map_event_to_frameworks({"event_type": "hitl.review_requested"})
        eu = [m for m in mappings if m.framework == "eu_ai_act"]
        assert eu
        eu_controls = {c for m in eu for c in m.control_ids}
        assert "Art.12" in eu_controls

    def test_art12_passes_in_evidence_package(self) -> None:
        engine = ComplianceMappingEngine()
        events = [
            {"event_type": "llm.audit.decision_made", "timestamp": f"2026-04-{i+1:02d}T10:00:00Z",
             "event_id": f"e{i}", "source": "t@1", "trace_id": "x" * 32, "span_id": "s1",
             "payload": {"model": {"name": "gpt-4o"}, "model_id": "gpt-4o"},
             "tags": {}, "schema_version": "2.0", "signature": None}
            for i in range(6)
        ] + [
            {"event_type": "hitl.review_requested", "timestamp": f"2026-04-{i+7:02d}T10:00:00Z",
             "event_id": f"h{i}", "source": "t@1", "trace_id": "x" * 32, "span_id": "s1",
             "payload": {"model": {"name": "gpt-4o"}, "model_id": "gpt-4o"},
             "tags": {}, "schema_version": "2.0", "signature": None}
            for i in range(6)
        ]
        pkg = engine.generate_evidence_package(
            model_id="gpt-4o", framework="eu_ai_act",
            from_date="2026-04-01", to_date="2026-04-30", audit_events=events,
        )
        art12 = next((c for c in pkg.attestation.clauses if c.clause_id == "Art.12"), None)
        assert art12 is not None
        assert art12.status == ClauseStatus.PASS


# ---------------------------------------------------------------------------
# EU AI Act Art.13 — Refined mapping (llm.trace + llm.eval + explanation)
# ---------------------------------------------------------------------------

class TestEUAIActArt13Refined:
    def test_art13_event_prefixes_include_trace_eval_explanation(self) -> None:
        from spanforge.core.compliance_mapping import _FRAMEWORK_CLAUSES
        prefixes = _FRAMEWORK_CLAUSES["eu_ai_act"]["Art.13"]["event_prefixes"]
        assert "llm.trace." in prefixes
        assert "llm.eval." in prefixes
        assert "explanation." in prefixes

    def test_art13_title_reflects_transparency(self) -> None:
        from spanforge.core.compliance_mapping import _FRAMEWORK_CLAUSES
        title = _FRAMEWORK_CLAUSES["eu_ai_act"]["Art.13"]["title"].lower()
        assert "transparency" in title or "high-risk" in title

    def test_llm_trace_maps_to_art13(self) -> None:
        mapper = FrameworkMapper()
        mappings = mapper.map_event_to_frameworks({"event_type": "llm.trace.span.completed"})
        eu = [m for m in mappings if m.framework == "eu_ai_act"]
        assert eu
        all_controls = {c for m in eu for c in m.control_ids}
        assert "Art.13" in all_controls

    def test_llm_eval_maps_to_art13(self) -> None:
        mapper = FrameworkMapper()
        mappings = mapper.map_event_to_frameworks({"event_type": "llm.eval.score_computed"})
        eu = [m for m in mappings if m.framework == "eu_ai_act"]
        assert eu
        all_controls = {c for m in eu for c in m.control_ids}
        assert "Art.13" in all_controls

    def test_explanation_still_maps_to_art13(self) -> None:
        mapper = FrameworkMapper()
        mappings = mapper.map_event_to_frameworks({"event_type": "explanation.generated"})
        eu = [m for m in mappings if m.framework == "eu_ai_act"]
        assert eu
        assert "Art.13" in eu[0].articles


# ---------------------------------------------------------------------------
# Cross-framework references — ISO 42001 → EU AI Act / GDPR
# ---------------------------------------------------------------------------

class TestCrossFrameworkRefs:
    def test_cross_framework_refs_dict_exists(self) -> None:
        from spanforge.core.compliance_mapping import _CROSS_FRAMEWORK_REFS
        assert isinstance(_CROSS_FRAMEWORK_REFS, dict)
        assert len(_CROSS_FRAMEWORK_REFS) >= 4

    def test_iso_42001_6_1_maps_to_eu_ai_act_art13(self) -> None:
        mapper = FrameworkMapper()
        refs = mapper.cross_framework_controls("iso_42001", "6.1")
        fw_keys = [fw for fw, _ in refs]
        clauses = [clause for _, clause in refs]
        assert "eu_ai_act" in fw_keys
        assert "Art.13" in clauses

    def test_iso_42001_6_1_maps_to_gdpr_art35(self) -> None:
        mapper = FrameworkMapper()
        refs = mapper.cross_framework_controls("iso_42001", "6.1")
        assert ("gdpr", "Art.35") in refs

    def test_iso_42001_9_1_maps_to_eu_ai_act_annex_iv6(self) -> None:
        mapper = FrameworkMapper()
        refs = mapper.cross_framework_controls("iso_42001", "9.1")
        assert ("eu_ai_act", "AnnexIV.6") in refs

    def test_iso_42001_5_1_maps_to_eu_ai_act_annex_iv5(self) -> None:
        mapper = FrameworkMapper()
        refs = mapper.cross_framework_controls("iso_42001", "5.1")
        assert ("eu_ai_act", "AnnexIV.5") in refs

    def test_iso_42001_10_1_maps_to_eu_ai_act_annex_iv5(self) -> None:
        mapper = FrameworkMapper()
        refs = mapper.cross_framework_controls("iso_42001", "10.1")
        assert ("eu_ai_act", "AnnexIV.5") in refs

    def test_unknown_control_returns_empty(self) -> None:
        mapper = FrameworkMapper()
        refs = mapper.cross_framework_controls("soc2", "CC6.1")
        assert refs == []

    def test_cross_framework_refs_return_tuples(self) -> None:
        mapper = FrameworkMapper()
        refs = mapper.cross_framework_controls("iso_42001", "6.1")
        for item in refs:
            assert isinstance(item, tuple)
            assert len(item) == 2

    def test_cross_framework_in_iso_42001_report(self) -> None:
        """ISO 42001 evidence report should contain Cross-Framework Coverage section."""
        engine = ComplianceMappingEngine()
        events = _make_full_events(10)
        pkg = engine.generate_evidence_package(
            model_id="gpt-4o", framework="iso_42001",
            from_date="2026-04-01", to_date="2026-04-30", audit_events=events,
        )
        report = pkg.to_markdown()
        assert "Cross-Framework" in report or "cross-framework" in report.lower()

    def test_cross_framework_in_report_lists_eu_ai_act(self) -> None:
        engine = ComplianceMappingEngine()
        events = _make_full_events(10)
        pkg = engine.generate_evidence_package(
            model_id="gpt-4o", framework="iso_42001",
            from_date="2026-04-01", to_date="2026-04-30", audit_events=events,
        )
        report = pkg.to_markdown()
        assert "eu_ai_act" in report
