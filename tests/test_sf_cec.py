"""Tests for spanforge Phase 5 — sf-cec Compliance Evidence Chain.

Coverage targets: ≥ 90 % on spanforge/sdk/cec.py, Phase 5 additions to
spanforge/sdk/_exceptions.py and spanforge/sdk/_types.py.

Test structure
--------------
* Exception hierarchy — SFCECError, SFCECBuildError, SFCECVerifyError,
  SFCECExportError all subclass SFError.
* Type shapes — BundleResult, BundleVerificationResult, CECStatusInfo,
  ClauseMapEntry, ClauseSatisfaction, DPADocument are importable, frozen.
* build_bundle — happy path shape, ZIP file created, hmac_manifest format,
  record_counts dict, frameworks list, bundle_id UUID format.
* ZIP structure — all required files present inside the archive.
* clause_map.json — per-framework clause IDs are present and correct.
* Regulatory coverage — eu_ai_act, iso_42001, nist_ai_rmf, iso27001, soc2.
* verify_bundle — valid bundle passes all three checks; tampered manifest
  fails manifest_valid; missing chain_proof fails chain_valid; missing tsr
  fails timestamp_valid; bad zip path raises SFCECVerifyError.
* generate_dpa — all 16 DPADocument fields populated; text contains key
  sections; document_id is UUID; scc_clauses present.
* get_status — bundle_count increments correctly; byos_enabled reflects env;
  frameworks_supported contains all 5 supported frameworks.
* Thread safety — 20 concurrent build_bundle calls all succeed and
  bundle_count is exactly 20.
* BYOS detection — SPANFORGE_AUDIT_BYOS_PROVIDER env var.
* SDK singleton — ``from spanforge.sdk import sf_cec`` is SFCECClient.
* configure() — sf_cec is recreated.
* ClauseSatisfaction enum — SATISFIED / PARTIAL / GAP values.
* Unknown framework — raises ValueError.
* Empty date_range — bundle still produced.
* SUPPORTED_FRAMEWORKS constant.
"""

from __future__ import annotations

import json
import threading
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from spanforge.sdk._base import SFClientConfig
from spanforge.sdk._exceptions import (
    SFCECBuildError,
    SFCECError,
    SFCECExportError,
    SFCECVerifyError,
    SFError,
)
from spanforge.sdk._types import (
    BundleResult,
    BundleVerificationResult,
    CECStatusInfo,
    ClauseMapEntry,
    ClauseSatisfaction,
    DPADocument,
)
from spanforge.sdk.cec import (
    SUPPORTED_FRAMEWORKS,
    SFCECClient,
    _compute_clause_map,
    _hmac_sign,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DATE_RANGE = ("2026-01-01", "2026-03-31")
_PROJECT_ID = "test-project"


def _make_client(signing_key: str = "test-cec-secret") -> SFCECClient:
    config = SFClientConfig(signing_key=signing_key)
    return SFCECClient(config)


# ---------------------------------------------------------------------------
# Exception hierarchy (Phase 5)
# ---------------------------------------------------------------------------


class TestCECExceptionHierarchy:
    def test_sfcecerror_is_sferror(self) -> None:
        assert issubclass(SFCECError, SFError)

    def test_sfcecbuilderror_is_sfcecerror(self) -> None:
        assert issubclass(SFCECBuildError, SFCECError)

    def test_sfcecverifyerror_is_sfcecerror(self) -> None:
        assert issubclass(SFCECVerifyError, SFCECError)

    def test_sfcecexporterror_is_sfcecerror(self) -> None:
        assert issubclass(SFCECExportError, SFCECError)

    def test_sfcecbuilderror_message(self) -> None:
        err = SFCECBuildError("disk full")
        assert "disk full" in str(err)

    def test_sfcecverifyerror_message(self) -> None:
        err = SFCECVerifyError("bad zip")
        assert "bad zip" in str(err)

    def test_sfcecexporterror_message(self) -> None:
        err = SFCECExportError("template error")
        assert "template error" in str(err)

    def test_sfcecerror_direct_instantiation(self) -> None:
        err = SFCECError("base")
        assert isinstance(err, SFError)

    def test_sfcecbuilderror_has_detail(self) -> None:
        err = SFCECBuildError("oops")
        assert hasattr(err, "detail")

    def test_sfcecverifyerror_has_detail(self) -> None:
        err = SFCECVerifyError("oops")
        assert hasattr(err, "detail")

    def test_sfcecexporterror_has_detail(self) -> None:
        err = SFCECExportError("oops")
        assert hasattr(err, "detail")


# ---------------------------------------------------------------------------
# ClauseSatisfaction enum
# ---------------------------------------------------------------------------


class TestClauseSatisfactionEnum:
    def test_satisfied_value(self) -> None:
        assert ClauseSatisfaction.SATISFIED.value == "SATISFIED"

    def test_partial_value(self) -> None:
        assert ClauseSatisfaction.PARTIAL.value == "PARTIAL"

    def test_gap_value(self) -> None:
        assert ClauseSatisfaction.GAP.value == "GAP"

    def test_three_members(self) -> None:
        assert len(list(ClauseSatisfaction)) == 3


# ---------------------------------------------------------------------------
# SUPPORTED_FRAMEWORKS constant
# ---------------------------------------------------------------------------


class TestSupportedFrameworks:
    def test_all_five_present(self) -> None:
        assert frozenset(
            {"eu_ai_act", "iso_42001", "nist_ai_rmf", "iso27001", "soc2"}
        ) == SUPPORTED_FRAMEWORKS

    def test_is_frozenset(self) -> None:
        assert isinstance(SUPPORTED_FRAMEWORKS, frozenset)


# ---------------------------------------------------------------------------
# _hmac_sign helper
# ---------------------------------------------------------------------------


class TestHmacSign:
    def test_prefix(self) -> None:
        sig = _hmac_sign(b"data", "key")
        assert sig.startswith("hmac-sha256:")

    def test_deterministic(self) -> None:
        sig1 = _hmac_sign(b"hello", "secret")
        sig2 = _hmac_sign(b"hello", "secret")
        assert sig1 == sig2

    def test_different_key(self) -> None:
        sig1 = _hmac_sign(b"hello", "key1")
        sig2 = _hmac_sign(b"hello", "key2")
        assert sig1 != sig2

    def test_length(self) -> None:
        sig = _hmac_sign(b"data", "key")
        # "hmac-sha256:" (12) + 64 hex chars = 76
        assert len(sig) == 12 + 64


# ---------------------------------------------------------------------------
# _compute_clause_map helper
# ---------------------------------------------------------------------------


class TestComputeClauseMap:
    def test_returns_list_of_clause_map_entries(self) -> None:
        entries = _compute_clause_map(["eu_ai_act"], {"halluccheck.score.v1": 10})
        assert all(isinstance(e, ClauseMapEntry) for e in entries)

    def test_eu_ai_act_clause_ids(self) -> None:
        counts = dict.fromkeys(
            [
                "halluccheck.score.v1", "halluccheck.bias.v1",
                "halluccheck.prri.v1", "halluccheck.drift.v1",
                "halluccheck.pii.v1", "halluccheck.gate.v1",
            ],
            20,
        )
        entries = _compute_clause_map(["eu_ai_act"], counts)
        clause_ids = {e.clause_id for e in entries}
        assert {"Art.9", "Art.10", "Art.12", "Art.13", "Art.14", "Art.15"} == clause_ids

    def test_iso_42001_clause_ids(self) -> None:
        counts = dict.fromkeys(
            [
                "halluccheck.score.v1", "halluccheck.bias.v1",
                "halluccheck.drift.v1", "halluccheck.pii.v1",
                "halluccheck.gate.v1",
            ],
            20,
        )
        entries = _compute_clause_map(["iso_42001"], counts)
        clause_ids = {e.clause_id for e in entries}
        assert {"6.1", "8.3", "9.1", "10"} == clause_ids

    def test_nist_ai_rmf_clause_ids(self) -> None:
        counts = dict.fromkeys(
            [
                "halluccheck.score.v1", "halluccheck.drift.v1",
                "halluccheck.gate.v1", "halluccheck.prri.v1",
                "halluccheck.bias.v1",
            ],
            20,
        )
        entries = _compute_clause_map(["nist_ai_rmf"], counts)
        clause_ids = {e.clause_id for e in entries}
        assert {"GOVERN", "MAP", "MEASURE", "MANAGE"} == clause_ids

    def test_iso27001_clause_ids(self) -> None:
        counts = dict.fromkeys(
            [
                "halluccheck.score.v1", "halluccheck.gate.v1",
                "halluccheck.drift.v1", "halluccheck.pii.v1",
                "halluccheck.bias.v1", "halluccheck.prri.v1",
            ],
            20,
        )
        entries = _compute_clause_map(["iso27001"], counts)
        clause_ids = {e.clause_id for e in entries}
        assert {"A.12.4.1", "A.12.4.2", "A.12.4.3"} == clause_ids

    def test_soc2_clause_ids(self) -> None:
        counts = dict.fromkeys(
            [
                "halluccheck.score.v1", "halluccheck.gate.v1",
                "halluccheck.pii.v1", "halluccheck.drift.v1",
            ],
            20,
        )
        entries = _compute_clause_map(["soc2"], counts)
        clause_ids = {e.clause_id for e in entries}
        assert {"CC6", "CC7", "CC9"} == clause_ids

    def test_satisfied_when_enough_evidence(self) -> None:
        counts = dict.fromkeys(
            [
                "halluccheck.score.v1", "halluccheck.gate.v1",
                "halluccheck.pii.v1", "halluccheck.drift.v1",
            ],
            50,
        )
        entries = _compute_clause_map(["soc2"], counts)
        assert all(e.status == ClauseSatisfaction.SATISFIED for e in entries)

    def test_gap_when_no_evidence(self) -> None:
        entries = _compute_clause_map(["soc2"], {})
        assert all(e.status == ClauseSatisfaction.GAP for e in entries)

    def test_partial_when_some_evidence(self) -> None:
        # Provide just 1 record (< min_count=5 for soc2/CC6 = pii+gate)
        entries = _compute_clause_map(
            ["soc2"],
            {"halluccheck.gate.v1": 1},
        )
        cc6 = next((e for e in entries if e.clause_id == "CC6"), None)
        assert cc6 is not None
        assert cc6.status == ClauseSatisfaction.PARTIAL

    def test_multiple_frameworks_combined(self) -> None:
        counts = dict.fromkeys(
            [
                "halluccheck.score.v1", "halluccheck.bias.v1",
                "halluccheck.prri.v1", "halluccheck.drift.v1",
                "halluccheck.pii.v1", "halluccheck.gate.v1",
            ],
            20,
        )
        entries = _compute_clause_map(["eu_ai_act", "soc2"], counts)
        frameworks = {e.framework for e in entries}
        assert "eu_ai_act" in frameworks
        assert "soc2" in frameworks

    def test_empty_frameworks_list_returns_no_entries(self) -> None:
        entries = _compute_clause_map([], {"halluccheck.score.v1": 10})
        assert entries == []


# ---------------------------------------------------------------------------
# build_bundle — happy path
# ---------------------------------------------------------------------------


class TestBuildBundle:
    def test_returns_bundle_result(self) -> None:
        client = _make_client()
        result = client.build_bundle(_PROJECT_ID, _DATE_RANGE)
        assert isinstance(result, BundleResult)

    def test_bundle_id_is_uuid(self) -> None:
        client = _make_client()
        result = client.build_bundle(_PROJECT_ID, _DATE_RANGE)
        uuid.UUID(result.bundle_id)  # raises ValueError if not a valid UUID

    def test_hmac_manifest_format(self) -> None:
        client = _make_client()
        result = client.build_bundle(_PROJECT_ID, _DATE_RANGE)
        assert result.hmac_manifest.startswith("hmac-sha256:")
        assert len(result.hmac_manifest) == 12 + 64

    def test_zip_path_is_string(self) -> None:
        client = _make_client()
        result = client.build_bundle(_PROJECT_ID, _DATE_RANGE)
        assert isinstance(result.zip_path, str)

    def test_zip_file_exists(self) -> None:
        client = _make_client()
        result = client.build_bundle(_PROJECT_ID, _DATE_RANGE)
        assert Path(result.zip_path).exists()

    def test_download_url_non_empty(self) -> None:
        client = _make_client()
        result = client.build_bundle(_PROJECT_ID, _DATE_RANGE)
        assert len(result.download_url) > 0

    def test_expires_at_in_future(self) -> None:
        client = _make_client()
        result = client.build_bundle(_PROJECT_ID, _DATE_RANGE)
        exp = datetime.fromisoformat(result.expires_at.replace("Z", "+00:00"))
        assert exp > datetime.now(timezone.utc)

    def test_record_counts_has_all_schema_keys(self) -> None:
        client = _make_client()
        result = client.build_bundle(_PROJECT_ID, _DATE_RANGE)
        for sk in [
            "halluccheck.score.v1",
            "halluccheck.bias.v1",
            "halluccheck.prri.v1",
            "halluccheck.drift.v1",
            "halluccheck.pii.v1",
            "halluccheck.gate.v1",
        ]:
            assert sk in result.record_counts

    def test_record_counts_values_are_ints(self) -> None:
        client = _make_client()
        result = client.build_bundle(_PROJECT_ID, _DATE_RANGE)
        for v in result.record_counts.values():
            assert isinstance(v, int)

    def test_frameworks_list_is_subset_of_supported(self) -> None:
        client = _make_client()
        result = client.build_bundle(_PROJECT_ID, _DATE_RANGE, frameworks=["eu_ai_act", "soc2"])
        assert set(result.frameworks) <= SUPPORTED_FRAMEWORKS

    def test_frameworks_in_result_match_input(self) -> None:
        client = _make_client()
        result = client.build_bundle(_PROJECT_ID, _DATE_RANGE, frameworks=["eu_ai_act", "soc2"])
        assert set(result.frameworks) == {"eu_ai_act", "soc2"}

    def test_project_id_in_result(self) -> None:
        client = _make_client()
        result = client.build_bundle(_PROJECT_ID, _DATE_RANGE)
        assert result.project_id == _PROJECT_ID

    def test_generated_at_iso_format(self) -> None:
        client = _make_client()
        result = client.build_bundle(_PROJECT_ID, _DATE_RANGE)
        datetime.fromisoformat(result.generated_at.replace("Z", "+00:00"))

    def test_unknown_framework_raises_value_error(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="Unknown framework"):
            client.build_bundle(_PROJECT_ID, _DATE_RANGE, frameworks=["unknown_fw"])

    def test_all_frameworks_default(self) -> None:
        """build_bundle with no frameworks arg includes all supported."""
        client = _make_client()
        result = client.build_bundle(_PROJECT_ID, _DATE_RANGE)
        assert set(result.frameworks) == SUPPORTED_FRAMEWORKS

    def test_bundle_result_is_frozen(self) -> None:
        client = _make_client()
        result = client.build_bundle(_PROJECT_ID, _DATE_RANGE)
        with pytest.raises((AttributeError, TypeError)):
            result.bundle_id = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ZIP structure (CEC-002)
# ---------------------------------------------------------------------------


class TestZipStructure:
    @pytest.fixture
    def bundle(self) -> BundleResult:
        return _make_client().build_bundle(_PROJECT_ID, _DATE_RANGE)

    def test_manifest_json_present(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            assert "manifest.json" in zf.namelist()

    def test_clause_map_json_present(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            assert "clause_map.json" in zf.namelist()

    def test_chain_proof_json_present(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            assert "chain_proof.json" in zf.namelist()

    def test_attestation_json_present(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            assert "attestation.json" in zf.namelist()

    def test_rfc3161_tsr_present(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            assert "rfc3161_timestamp.tsr" in zf.namelist()

    def test_score_records_dir(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            assert any(n.startswith("score_records/") for n in zf.namelist())

    def test_bias_reports_dir(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            assert any(n.startswith("bias_reports/") for n in zf.namelist())

    def test_prri_records_dir(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            assert any(n.startswith("prri_records/") for n in zf.namelist())

    def test_drift_events_dir(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            assert any(n.startswith("drift_events/") for n in zf.namelist())

    def test_pii_detections_dir(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            assert any(n.startswith("pii_detections/") for n in zf.namelist())

    def test_gate_evaluations_dir(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            assert any(n.startswith("gate_evaluations/") for n in zf.namelist())

    def test_manifest_json_schema_field(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))
        assert manifest.get("bundle_schema") == "spanforge.cec.v1"

    def test_manifest_json_has_hmac(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))
        assert "hmac" in manifest
        assert manifest["hmac"].startswith("hmac-sha256:")

    def test_manifest_record_counts_present(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            manifest = json.loads(zf.read("manifest.json"))
        assert "record_counts" in manifest

    def test_clause_map_json_is_list(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            clause_map = json.loads(zf.read("clause_map.json"))
        assert isinstance(clause_map, list)

    def test_clause_map_entry_has_required_fields(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            clause_map = json.loads(zf.read("clause_map.json"))
        if clause_map:
            entry = clause_map[0]
            for field in ("framework", "clause_id", "title", "status", "evidence_count"):
                assert field in entry, f"Missing field: {field}"

    def test_rfc3161_has_gen_time(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            tsr = json.loads(zf.read("rfc3161_timestamp.tsr"))
        assert "genTime" in tsr

    def test_rfc3161_has_message_imprint(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            tsr = json.loads(zf.read("rfc3161_timestamp.tsr"))
        assert "messageImprint" in tsr

    def test_attestation_has_schema(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            att = json.loads(zf.read("attestation.json"))
        assert att.get("schema") == "spanforge.cec.attestation.v1"

    def test_attestation_has_hmac_sig(self, bundle: BundleResult) -> None:
        with zipfile.ZipFile(bundle.zip_path, "r") as zf:
            att = json.loads(zf.read("attestation.json"))
        assert "hmac_sig" in att
        assert att["hmac_sig"].startswith("hmac-sha256:")


# ---------------------------------------------------------------------------
# Clause map content per framework
# ---------------------------------------------------------------------------


class TestClauseMapContent:
    @pytest.fixture
    def bundle_eu_ai(self) -> BundleResult:
        return _make_client().build_bundle(
            _PROJECT_ID, _DATE_RANGE, frameworks=["eu_ai_act"]
        )

    @pytest.fixture
    def bundle_iso42001(self) -> BundleResult:
        return _make_client().build_bundle(
            _PROJECT_ID, _DATE_RANGE, frameworks=["iso_42001"]
        )

    @pytest.fixture
    def bundle_nist(self) -> BundleResult:
        return _make_client().build_bundle(
            _PROJECT_ID, _DATE_RANGE, frameworks=["nist_ai_rmf"]
        )

    @pytest.fixture
    def bundle_soc2(self) -> BundleResult:
        return _make_client().build_bundle(
            _PROJECT_ID, _DATE_RANGE, frameworks=["soc2"]
        )

    @pytest.fixture
    def bundle_iso27001(self) -> BundleResult:
        return _make_client().build_bundle(
            _PROJECT_ID, _DATE_RANGE, frameworks=["iso27001"]
        )

    def _clause_ids(self, zip_path: str) -> set[str]:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return {e["clause_id"] for e in json.loads(zf.read("clause_map.json"))}

    def test_eu_ai_act_art9_present(self, bundle_eu_ai: BundleResult) -> None:
        assert "Art.9" in self._clause_ids(bundle_eu_ai.zip_path)

    def test_eu_ai_act_art10_present(self, bundle_eu_ai: BundleResult) -> None:
        assert "Art.10" in self._clause_ids(bundle_eu_ai.zip_path)

    def test_eu_ai_act_art12_present(self, bundle_eu_ai: BundleResult) -> None:
        assert "Art.12" in self._clause_ids(bundle_eu_ai.zip_path)

    def test_eu_ai_act_art13_present(self, bundle_eu_ai: BundleResult) -> None:
        assert "Art.13" in self._clause_ids(bundle_eu_ai.zip_path)

    def test_eu_ai_act_art14_present(self, bundle_eu_ai: BundleResult) -> None:
        assert "Art.14" in self._clause_ids(bundle_eu_ai.zip_path)

    def test_eu_ai_act_art15_present(self, bundle_eu_ai: BundleResult) -> None:
        assert "Art.15" in self._clause_ids(bundle_eu_ai.zip_path)

    def test_eu_ai_act_framework_label(self, bundle_eu_ai: BundleResult) -> None:
        with zipfile.ZipFile(bundle_eu_ai.zip_path, "r") as zf:
            entries = json.loads(zf.read("clause_map.json"))
        assert all(e["framework"] == "eu_ai_act" for e in entries)

    def test_iso42001_61_present(self, bundle_iso42001: BundleResult) -> None:
        assert "6.1" in self._clause_ids(bundle_iso42001.zip_path)

    def test_iso42001_83_present(self, bundle_iso42001: BundleResult) -> None:
        assert "8.3" in self._clause_ids(bundle_iso42001.zip_path)

    def test_iso42001_91_present(self, bundle_iso42001: BundleResult) -> None:
        assert "9.1" in self._clause_ids(bundle_iso42001.zip_path)

    def test_iso42001_10_present(self, bundle_iso42001: BundleResult) -> None:
        assert "10" in self._clause_ids(bundle_iso42001.zip_path)

    def test_nist_govern_present(self, bundle_nist: BundleResult) -> None:
        assert "GOVERN" in self._clause_ids(bundle_nist.zip_path)

    def test_nist_map_present(self, bundle_nist: BundleResult) -> None:
        assert "MAP" in self._clause_ids(bundle_nist.zip_path)

    def test_nist_measure_present(self, bundle_nist: BundleResult) -> None:
        assert "MEASURE" in self._clause_ids(bundle_nist.zip_path)

    def test_nist_manage_present(self, bundle_nist: BundleResult) -> None:
        assert "MANAGE" in self._clause_ids(bundle_nist.zip_path)

    def test_soc2_cc6_present(self, bundle_soc2: BundleResult) -> None:
        assert "CC6" in self._clause_ids(bundle_soc2.zip_path)

    def test_soc2_cc7_present(self, bundle_soc2: BundleResult) -> None:
        assert "CC7" in self._clause_ids(bundle_soc2.zip_path)

    def test_soc2_cc9_present(self, bundle_soc2: BundleResult) -> None:
        assert "CC9" in self._clause_ids(bundle_soc2.zip_path)

    def test_iso27001_a1241(self, bundle_iso27001: BundleResult) -> None:
        assert "A.12.4.1" in self._clause_ids(bundle_iso27001.zip_path)

    def test_iso27001_a1242(self, bundle_iso27001: BundleResult) -> None:
        assert "A.12.4.2" in self._clause_ids(bundle_iso27001.zip_path)

    def test_iso27001_a1243(self, bundle_iso27001: BundleResult) -> None:
        assert "A.12.4.3" in self._clause_ids(bundle_iso27001.zip_path)


# ---------------------------------------------------------------------------
# verify_bundle
# ---------------------------------------------------------------------------


class TestVerifyBundle:
    @pytest.fixture
    def valid_bundle(self) -> BundleResult:
        return _make_client().build_bundle(_PROJECT_ID, _DATE_RANGE)

    def test_valid_bundle_overall_valid(self, valid_bundle: BundleResult) -> None:
        client = _make_client()
        result = client.verify_bundle(valid_bundle.zip_path)
        assert isinstance(result, BundleVerificationResult)
        assert result.overall_valid is True

    def test_valid_bundle_manifest_valid(self, valid_bundle: BundleResult) -> None:
        client = _make_client()
        result = client.verify_bundle(valid_bundle.zip_path)
        assert result.manifest_valid is True

    def test_valid_bundle_chain_valid(self, valid_bundle: BundleResult) -> None:
        client = _make_client()
        result = client.verify_bundle(valid_bundle.zip_path)
        assert result.chain_valid is True

    def test_valid_bundle_timestamp_valid(self, valid_bundle: BundleResult) -> None:
        client = _make_client()
        result = client.verify_bundle(valid_bundle.zip_path)
        assert result.timestamp_valid is True

    def test_valid_bundle_no_errors(self, valid_bundle: BundleResult) -> None:
        client = _make_client()
        result = client.verify_bundle(valid_bundle.zip_path)
        assert result.errors == []

    def test_tampered_manifest_fails(self, valid_bundle: BundleResult, tmp_path: Path) -> None:
        """Rebuild bundle ZIP with a tampered manifest.json."""
        tampered = tmp_path / "tampered.zip"

        # Read all original entries then rebuild, substituting a tampered manifest
        with zipfile.ZipFile(valid_bundle.zip_path, "r") as src:
            entries = {item.filename: src.read(item.filename) for item in src.infolist()}

        manifest = json.loads(entries["manifest.json"])
        manifest["project_id"] = "TAMPERED"
        entries["manifest.json"] = json.dumps(manifest, indent=2).encode()

        with zipfile.ZipFile(str(tampered), "w") as dst:
            for name, data in entries.items():
                dst.writestr(name, data)

        client = _make_client()
        result = client.verify_bundle(str(tampered))
        assert result.manifest_valid is False
        assert result.overall_valid is False
        assert any("tamper" in e.lower() or "mismatch" in e.lower() for e in result.errors)

    def test_missing_chain_proof_fails(self, tmp_path: Path) -> None:
        """Build a ZIP that lacks chain_proof.json."""

        zip_path = tmp_path / "no_chain.zip"
        # Build valid bundle first and strip chain_proof
        base = _make_client().build_bundle(_PROJECT_ID, _DATE_RANGE)
        with zipfile.ZipFile(base.zip_path, "r") as src, \
             zipfile.ZipFile(str(zip_path), "w") as dst:
            for item in src.infolist():
                if item.filename != "chain_proof.json":
                    dst.writestr(item, src.read(item.filename))

        client = _make_client()
        result = client.verify_bundle(str(zip_path))
        assert result.chain_valid is False
        assert result.overall_valid is False

    def test_missing_tsr_fails(self, tmp_path: Path) -> None:
        """Build a ZIP without the RFC 3161 timestamp stub."""
        base = _make_client().build_bundle(_PROJECT_ID, _DATE_RANGE)
        zip_path = tmp_path / "no_tsr.zip"
        with zipfile.ZipFile(base.zip_path, "r") as src, \
             zipfile.ZipFile(str(zip_path), "w") as dst:
            for item in src.infolist():
                if item.filename != "rfc3161_timestamp.tsr":
                    dst.writestr(item, src.read(item.filename))

        client = _make_client()
        result = client.verify_bundle(str(zip_path))
        assert result.timestamp_valid is False
        assert result.overall_valid is False

    def test_bad_zip_path_raises(self, tmp_path: Path) -> None:
        not_exist = tmp_path / "does-not-exist-cec-test.zip"
        client = _make_client()
        with pytest.raises(SFCECVerifyError):
            client.verify_bundle(str(not_exist))

    def test_not_a_zip_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "not_a_zip.zip"
        bad.write_bytes(b"this is not a zip file")
        client = _make_client()
        with pytest.raises(SFCECVerifyError):
            client.verify_bundle(str(bad))

    def test_bundle_verification_result_is_frozen(self, valid_bundle: BundleResult) -> None:
        client = _make_client()
        result = client.verify_bundle(valid_bundle.zip_path)
        with pytest.raises((AttributeError, TypeError)):
            result.overall_valid = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# generate_dpa
# ---------------------------------------------------------------------------


class TestGenerateDPA:
    def test_returns_dpa_document(self) -> None:
        client = _make_client()
        dpa = client.generate_dpa(
            project_id=_PROJECT_ID,
            controller_details={"name": "Acme Corp", "address": "123 Main St"},
            processor_details={"name": "SpanForge", "address": "456 Cloud Ave"},
        )
        assert isinstance(dpa, DPADocument)

    def test_document_id_is_uuid(self) -> None:
        client = _make_client()
        dpa = client.generate_dpa(
            project_id=_PROJECT_ID,
            controller_details={"name": "Acme Corp"},
            processor_details={"name": "SpanForge"},
        )
        uuid.UUID(dpa.document_id)

    def test_project_id_in_dpa(self) -> None:
        client = _make_client()
        dpa = client.generate_dpa(
            project_id=_PROJECT_ID,
            controller_details={"name": "Acme Corp"},
            processor_details={"name": "SpanForge"},
        )
        assert dpa.project_id == _PROJECT_ID

    def test_controller_name(self) -> None:
        client = _make_client()
        dpa = client.generate_dpa(
            project_id=_PROJECT_ID,
            controller_details={"name": "MyController"},
            processor_details={"name": "SpanForge"},
        )
        assert dpa.controller_name == "MyController"

    def test_processor_name(self) -> None:
        client = _make_client()
        dpa = client.generate_dpa(
            project_id=_PROJECT_ID,
            controller_details={"name": "Ctrl"},
            processor_details={"name": "MyProcessor"},
        )
        assert dpa.processor_name == "MyProcessor"

    def test_text_contains_gdpr_title(self) -> None:
        client = _make_client()
        dpa = client.generate_dpa(
            project_id=_PROJECT_ID,
            controller_details={"name": "Acme"},
            processor_details={"name": "SpanForge"},
        )
        assert "DATA PROCESSING AGREEMENT" in dpa.text

    def test_text_contains_article_28(self) -> None:
        client = _make_client()
        dpa = client.generate_dpa(
            project_id=_PROJECT_ID,
            controller_details={"name": "Acme"},
            processor_details={"name": "SpanForge"},
        )
        assert "Article 28" in dpa.text or "GDPR Art" in dpa.text or "Article 28" in dpa.text

    def test_text_contains_project_id(self) -> None:
        client = _make_client()
        dpa = client.generate_dpa(
            project_id=_PROJECT_ID,
            controller_details={"name": "Acme"},
            processor_details={"name": "SpanForge"},
        )
        assert _PROJECT_ID in dpa.text

    def test_text_contains_controller_name(self) -> None:
        client = _make_client()
        dpa = client.generate_dpa(
            project_id=_PROJECT_ID,
            controller_details={"name": "UNIQUE_CONTROLLER"},
            processor_details={"name": "SpanForge"},
        )
        assert "UNIQUE_CONTROLLER" in dpa.text

    def test_scc_clauses_default(self) -> None:
        client = _make_client()
        dpa = client.generate_dpa(
            project_id=_PROJECT_ID,
            controller_details={"name": "Ctrl"},
            processor_details={"name": "Proc"},
        )
        assert "Module 2" in dpa.scc_clauses

    def test_custom_purposes(self) -> None:
        client = _make_client()
        dpa = client.generate_dpa(
            project_id=_PROJECT_ID,
            controller_details={"name": "Ctrl"},
            processor_details={"name": "Proc"},
            processing_purposes=["Custom Purpose A"],
        )
        assert "Custom Purpose A" in dpa.processing_purposes
        assert "Custom Purpose A" in dpa.text

    def test_retention_period_default(self) -> None:
        client = _make_client()
        dpa = client.generate_dpa(
            project_id=_PROJECT_ID,
            controller_details={"name": "Ctrl"},
            processor_details={"name": "Proc"},
        )
        assert "7 years" in dpa.retention_period

    def test_generated_at_iso(self) -> None:
        client = _make_client()
        dpa = client.generate_dpa(
            project_id=_PROJECT_ID,
            controller_details={"name": "Ctrl"},
            processor_details={"name": "Proc"},
        )
        datetime.fromisoformat(dpa.generated_at.replace("Z", "+00:00"))

    def test_all_fields_populated(self) -> None:
        """All 16 DPADocument fields must be non-None."""
        client = _make_client()
        dpa = client.generate_dpa(
            project_id=_PROJECT_ID,
            controller_details={"name": "Ctrl"},
            processor_details={"name": "Proc"},
        )
        for field in (
            "project_id", "controller_name", "controller_address",
            "processor_name", "processor_address", "processing_purposes",
            "data_categories", "data_subjects", "sub_processors",
            "transfer_mechanism", "retention_period", "security_measures",
            "scc_clauses", "document_id", "generated_at", "text",
        ):
            assert getattr(dpa, field) is not None, f"Field {field!r} is None"

    def test_dpa_document_is_frozen(self) -> None:
        client = _make_client()
        dpa = client.generate_dpa(
            project_id=_PROJECT_ID,
            controller_details={"name": "Ctrl"},
            processor_details={"name": "Proc"},
        )
        with pytest.raises((AttributeError, TypeError)):
            dpa.document_id = "tampered"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------


class TestGetStatus:
    def test_returns_cec_status_info(self) -> None:
        client = _make_client()
        status = client.get_status()
        assert isinstance(status, CECStatusInfo)

    def test_status_ok(self) -> None:
        client = _make_client()
        assert client.get_status().status == "ok"

    def test_bundle_count_starts_at_zero(self) -> None:
        client = _make_client()
        assert client.get_status().bundle_count == 0

    def test_bundle_count_increments(self) -> None:
        client = _make_client()
        client.build_bundle(_PROJECT_ID, _DATE_RANGE)
        assert client.get_status().bundle_count == 1

    def test_bundle_count_increments_twice(self) -> None:
        client = _make_client()
        client.build_bundle(_PROJECT_ID, _DATE_RANGE)
        client.build_bundle(_PROJECT_ID, _DATE_RANGE)
        assert client.get_status().bundle_count == 2

    def test_last_bundle_at_none_initially(self) -> None:
        client = _make_client()
        assert client.get_status().last_bundle_at is None

    def test_last_bundle_at_set_after_build(self) -> None:
        client = _make_client()
        client.build_bundle(_PROJECT_ID, _DATE_RANGE)
        ts = client.get_status().last_bundle_at
        assert ts is not None
        datetime.fromisoformat(ts.replace("Z", "+00:00"))

    def test_byos_disabled_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SPANFORGE_AUDIT_BYOS_PROVIDER", raising=False)
        client = _make_client()
        assert client.get_status().byos_enabled is False

    def test_frameworks_supported_list(self) -> None:
        client = _make_client()
        supported = client.get_status().frameworks_supported
        assert isinstance(supported, list)
        assert set(supported) == SUPPORTED_FRAMEWORKS

    def test_cec_status_info_is_frozen(self) -> None:
        client = _make_client()
        status = client.get_status()
        with pytest.raises((AttributeError, TypeError)):
            status.status = "down"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# BYOS detection
# ---------------------------------------------------------------------------


class TestByosDetection:
    @pytest.mark.parametrize("provider", ["s3", "azure", "gcs", "r2"])
    def test_byos_enabled_per_provider(
        self, provider: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SPANFORGE_AUDIT_BYOS_PROVIDER", provider)
        client = _make_client()
        assert client._byos_provider == provider

    def test_byos_unknown_provider_ignored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("SPANFORGE_AUDIT_BYOS_PROVIDER", "ftp")
        client = _make_client()
        assert client._byos_provider is None

    def test_byos_empty_env_not_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("SPANFORGE_AUDIT_BYOS_PROVIDER", raising=False)
        client = _make_client()
        assert client._byos_provider is None

    def test_byos_case_insensitive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_AUDIT_BYOS_PROVIDER", "S3")
        client = _make_client()
        assert client._byos_provider == "s3"

    def test_status_byos_enabled_true(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_AUDIT_BYOS_PROVIDER", "gcs")
        client = _make_client()
        assert client.get_status().byos_enabled is True


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_build_bundle_count(self) -> None:
        """20 concurrent threads each call build_bundle; count must equal 20."""
        num_threads = 20
        client = _make_client()
        errors: list[Exception] = []

        def _worker() -> None:
            try:
                client.build_bundle(_PROJECT_ID, _DATE_RANGE, frameworks=["soc2"])
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        threads = [threading.Thread(target=_worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread errors: {errors}"
        assert client.get_status().bundle_count == num_threads

    def test_concurrent_build_unique_bundle_ids(self) -> None:
        """Every concurrent build_bundle call must return a unique bundle_id."""
        num_threads = 10
        client = _make_client()
        results: list[BundleResult] = []
        lock = threading.Lock()

        def _worker() -> None:
            result = client.build_bundle(_PROJECT_ID, _DATE_RANGE, frameworks=["soc2"])
            with lock:
                results.append(result)

        threads = [threading.Thread(target=_worker) for _ in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len({r.bundle_id for r in results}) == num_threads


# ---------------------------------------------------------------------------
# SDK singleton re-export
# ---------------------------------------------------------------------------


class TestSDKSingleton:
    def test_sf_cec_is_sfcec_client(self) -> None:
        from spanforge.sdk import sf_cec

        assert isinstance(sf_cec, SFCECClient)

    def test_sdk_exports_bundle_result(self) -> None:
        from spanforge import sdk

        assert sdk.BundleResult is BundleResult

    def test_sdk_exports_bundle_verification_result(self) -> None:
        from spanforge import sdk

        assert sdk.BundleVerificationResult is BundleVerificationResult

    def test_sdk_exports_cec_status_info(self) -> None:
        from spanforge import sdk

        assert sdk.CECStatusInfo is CECStatusInfo

    def test_sdk_exports_clause_map_entry(self) -> None:
        from spanforge import sdk

        assert sdk.ClauseMapEntry is ClauseMapEntry

    def test_sdk_exports_clause_satisfaction(self) -> None:
        from spanforge import sdk

        assert sdk.ClauseSatisfaction is ClauseSatisfaction

    def test_sdk_exports_dpa_document(self) -> None:
        from spanforge import sdk

        assert sdk.DPADocument is DPADocument

    def test_sdk_exports_sfcecbuilderror(self) -> None:
        from spanforge import sdk

        assert sdk.SFCECBuildError is SFCECBuildError

    def test_sdk_exports_sfcecerror(self) -> None:
        from spanforge import sdk

        assert sdk.SFCECError is SFCECError

    def test_sdk_exports_sfcecexporterror(self) -> None:
        from spanforge import sdk

        assert sdk.SFCECExportError is SFCECExportError

    def test_sdk_exports_sfcecverifyerror(self) -> None:
        from spanforge import sdk

        assert sdk.SFCECVerifyError is SFCECVerifyError


# ---------------------------------------------------------------------------
# configure() recreates sf_cec
# ---------------------------------------------------------------------------


class TestConfigure:
    def test_configure_recreates_sf_cec(self) -> None:
        from spanforge import sdk

        old = sdk.sf_cec
        sdk.configure(SFClientConfig(signing_key="new-key-for-test"))
        assert sdk.sf_cec is not old
        assert isinstance(sdk.sf_cec, SFCECClient)

    def test_configure_preserves_sf_audit(self) -> None:
        from spanforge import sdk
        from spanforge.sdk.audit import SFAuditClient

        sdk.configure(SFClientConfig(signing_key="new-key-for-test-2"))
        assert isinstance(sdk.sf_audit, SFAuditClient)
