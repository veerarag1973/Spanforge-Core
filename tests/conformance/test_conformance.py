"""Conformance test runner for SpanForge v1.1.

Reads fixture JSON files from ``fixtures/`` (and the legacy ``fixtures.json``)
and runs each test case against the public API.
Execute via ``pytest tests/conformance/`` or ``python -m tests.conformance.run_conformance``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
LEGACY_FIXTURE = Path(__file__).parent / "fixtures.json"


def _load_fixtures() -> list[dict]:
    """Load all fixture JSON files (split + legacy)."""
    cases: list[dict] = []
    # Load split fixture files
    if FIXTURES_DIR.is_dir():
        for fp in sorted(FIXTURES_DIR.glob("*.json")):
            cases.extend(json.loads(fp.read_text("utf-8")))
    # Merge any legacy-only cases not already present
    if LEGACY_FIXTURE.exists():
        seen_ids = {c["id"] for c in cases}
        for c in json.loads(LEGACY_FIXTURE.read_text("utf-8")):
            if c["id"] not in seen_ids:
                cases.append(c)
    return cases


_CASES = _load_fixtures()


def _case_ids() -> list[str]:
    return [f"{c['id']}-{c['title']}" for c in _CASES]


# ---------------------------------------------------------------------------
# C001 — basic signing round-trip
# ---------------------------------------------------------------------------


class TestC001:
    @pytest.fixture()
    def case(self):
        return next(c for c in _CASES if c["id"] == "C001")

    def test_sign_and_verify(self, case):
        from spanforge.event import Event, EventType
        from spanforge.signing import sign, verify

        inp = case["input"]
        event = Event(
            event_type=EventType(inp["event_type"]),
            source=inp["source"],
            payload=inp["payload"],
            org_id=inp.get("org_id"),
        )
        signed = sign(event, case["org_secret"])
        assert signed.checksum.startswith(case["expect"]["checksum_prefix"])
        assert signed.signature.startswith(case["expect"]["signature_prefix"])
        assert verify(signed, case["org_secret"]) is case["expect"]["verify"]


# ---------------------------------------------------------------------------
# C002 — chain linkage
# ---------------------------------------------------------------------------


class TestC002:
    @pytest.fixture()
    def case(self):
        return next(c for c in _CASES if c["id"] == "C002")

    def test_chain_linkage(self, case):
        from spanforge.event import Event, EventType
        from spanforge.signing import AuditStream

        stream = AuditStream(org_secret=case["org_secret"], source="conformance@1.0.0")
        for inp in case["input"]:
            event = Event(
                event_type=EventType(inp["event_type"]),
                source=inp["source"],
                payload=inp["payload"],
            )
            stream.append(event)

        events = stream.events
        assert len(events) == 2
        assert events[1].prev_id == events[0].event_id
        result = stream.verify()
        assert result.valid is case["expect"]["chain_valid"]


# ---------------------------------------------------------------------------
# C003 — empty secret rejected
# ---------------------------------------------------------------------------


class TestC003:
    @pytest.fixture()
    def case(self):
        return next(c for c in _CASES if c["id"] == "C003")

    def test_empty_secret_raises(self, case):
        from spanforge.event import Event, EventType
        from spanforge.exceptions import SigningError
        from spanforge.signing import sign

        event = Event(
            event_type=EventType(case["input"]["event_type"]),
            source=case["input"]["source"],
            payload=case["input"]["payload"],
        )
        with pytest.raises(SigningError):
            sign(event, case["org_secret"])


# ---------------------------------------------------------------------------
# C004 — wrong key fails verification
# ---------------------------------------------------------------------------


class TestC004:
    @pytest.fixture()
    def case(self):
        return next(c for c in _CASES if c["id"] == "C004")

    def test_verify_wrong_key(self, case):
        from spanforge.event import Event, EventType
        from spanforge.signing import sign, verify

        event = Event(
            event_type=EventType(case["input"]["event_type"]),
            source=case["input"]["source"],
            payload=case["input"]["payload"],
        )
        signed = sign(event, case["org_secret"])
        assert verify(signed, case["wrong_secret"]) is case["expect"]["verify_wrong_key"]


# ---------------------------------------------------------------------------
# C005 — schema migration v1 → v2
# ---------------------------------------------------------------------------


class TestC005:
    @pytest.fixture()
    def case(self):
        return next(c for c in _CASES if c["id"] == "C005")

    def test_v1_to_v2(self, case):
        from spanforge.migrate import v1_to_v2

        result = v1_to_v2(case["input"])
        assert result["schema_version"] == case["expect"]["schema_version"]
        assert "model_id" in result.get("payload", {})
        assert "model" not in result.get("payload", {})


# ---------------------------------------------------------------------------
# C006 — PII scan
# ---------------------------------------------------------------------------


class TestC006:
    @pytest.fixture()
    def case(self):
        return next(c for c in _CASES if c["id"] == "C006")

    def test_pii_scan(self, case):
        from spanforge.redact import scan_payload

        result = scan_payload(case["input"])
        assert (not result.clean) is case["expect"]["pii_detected"]
        detected_types = {h.pii_type for h in result.hits}
        for expected_type in case["expect"]["pii_types"]:
            assert expected_type in detected_types


# ---------------------------------------------------------------------------
# C007 — key strength validation
# ---------------------------------------------------------------------------


class TestC007:
    @pytest.fixture()
    def case(self):
        return next(c for c in _CASES if c["id"] == "C007")

    def test_key_strength(self, case):
        from spanforge.signing import validate_key_strength

        warnings = validate_key_strength(case["input"]["org_secret"])
        assert bool(warnings) is case["expect"]["has_warnings"]


# ---------------------------------------------------------------------------
# C008 — tombstone erasure
# ---------------------------------------------------------------------------


class TestC008:
    @pytest.fixture()
    def case(self):
        return next(c for c in _CASES if c["id"] == "C008")

    def test_erase_subject(self, case):
        from spanforge.event import Event, EventType
        from spanforge.signing import AuditStream

        stream = AuditStream(org_secret=case["org_secret"], source="conformance@1.0.0")
        for inp in case["input"]["events"]:
            event = Event(
                event_type=EventType(inp["event_type"]),
                source=inp["source"],
                payload=inp["payload"],
                actor_id=inp.get("actor_id"),
            )
            stream.append(event)

        tombstones = stream.erase_subject(
            case["input"]["subject_id"],
            erased_by="conformance-runner",
            reason="test erasure",
        )
        assert len(tombstones) == case["expect"]["tombstone_count"]


# ---------------------------------------------------------------------------
# C009 — egress enforcement
# ---------------------------------------------------------------------------


class TestC009:
    @pytest.fixture()
    def case(self):
        return next(c for c in _CASES if c["id"] == "C009")

    def test_egress_blocked(self, case):
        from spanforge.config import configure
        from spanforge.egress import check_egress
        from spanforge.exceptions import EgressViolationError

        configure(no_egress=case["config"]["no_egress"])
        try:
            with pytest.raises(EgressViolationError):
                check_egress(case["input"]["endpoint"], case["input"]["backend"])
        finally:
            configure(no_egress=False)


# ---------------------------------------------------------------------------
# C010 — compliance mapper frameworks
# ---------------------------------------------------------------------------


class TestC010:
    @pytest.fixture()
    def case(self):
        return next(c for c in _CASES if c["id"] == "C010")

    def test_compliance_frameworks(self, case):
        from spanforge.core.compliance_mapping import (
            ComplianceFramework,
            ComplianceMappingEngine,
        )

        # Verify the enum contains all expected frameworks
        framework_names = [f.name for f in ComplianceFramework]
        assert len(framework_names) == case["expect"]["framework_count"]
        for expected in case["expect"]["frameworks"]:
            assert expected in framework_names

        # Verify the engine can generate a package for each framework
        engine = ComplianceMappingEngine()
        for fw in ComplianceFramework:
            pkg = engine.generate_evidence_package(
                model_id="gpt-4",
                framework=fw,
                from_date="2025-01-01",
                to_date="2025-12-31",
                audit_events=[],
            )
            assert pkg is not None


# ---------------------------------------------------------------------------
# C011 — migration rehashes md5 checksums
# ---------------------------------------------------------------------------


class TestC011:
    @pytest.fixture()
    def case(self):
        return next(c for c in _CASES if c["id"] == "C011")

    def test_md5_to_sha256(self, case):
        from spanforge.migrate import v1_to_v2

        result = v1_to_v2(case["input"])
        assert result.get("checksum", "").startswith(case["expect"]["checksum_prefix"])
        assert result["schema_version"] == case["expect"]["schema_version"]


# ---------------------------------------------------------------------------
# C012 — migration coerces tag values to strings
# ---------------------------------------------------------------------------


class TestC012:
    @pytest.fixture()
    def case(self):
        return next(c for c in _CASES if c["id"] == "C012")

    def test_tag_coercion(self, case):
        from spanforge.migrate import v1_to_v2

        result = v1_to_v2(case["input"])
        tags = result.get("tags", {})
        assert result["schema_version"] == "2.0"
        assert all(isinstance(v, str) for v in tags.values())


# ---------------------------------------------------------------------------
# C013 — PII scan detects SSN
# ---------------------------------------------------------------------------


class TestC013:
    @pytest.fixture()
    def case(self):
        return next(c for c in _CASES if c["id"] == "C013")

    def test_ssn_detection(self, case):
        from spanforge.redact import scan_payload

        result = scan_payload(case["input"])
        detected = {h.pii_type for h in result.hits}
        assert (not result.clean) is case["expect"]["pii_detected"]
        for expected_type in case["expect"]["pii_types"]:
            assert expected_type in detected


# ---------------------------------------------------------------------------
# C014 — PII hit match_count and sensitivity
# ---------------------------------------------------------------------------


class TestC014:
    @pytest.fixture()
    def case(self):
        return next(c for c in _CASES if c["id"] == "C014")

    def test_match_count_sensitivity(self, case):
        from spanforge.redact import scan_payload

        result = scan_payload(case["input"])
        assert (not result.clean) is case["expect"]["pii_detected"]
        assert result.hits
        hit = result.hits[0]
        assert hit.match_count >= case["expect"]["first_hit_match_count_gte"]
        assert hit.sensitivity != ""


# ---------------------------------------------------------------------------
# C015 — credit card Luhn validation
# ---------------------------------------------------------------------------


class TestC015:
    @pytest.fixture()
    def case(self):
        return next(c for c in _CASES if c["id"] == "C015")

    def test_luhn_filter(self, case):
        from spanforge.redact import scan_payload

        result = scan_payload(case["input"])
        assert result.clean is (not case["expect"]["pii_detected"])


# ---------------------------------------------------------------------------
# C016 — key expiry returns tuple
# ---------------------------------------------------------------------------


class TestC016:
    @pytest.fixture()
    def case(self):
        return next(c for c in _CASES if c["id"] == "C016")

    def test_key_expiry_tuple(self, case):
        from spanforge.signing import check_key_expiry

        status, days = check_key_expiry(case["input"]["expires_at"])
        assert status == case["expect"]["status"]
        assert days > 0


# ---------------------------------------------------------------------------
# C017 — derive_key context isolation
# ---------------------------------------------------------------------------


class TestC017:
    @pytest.fixture()
    def case(self):
        return next(c for c in _CASES if c["id"] == "C017")

    def test_context_isolation(self, case):
        from spanforge.signing import derive_key

        inp = case["input"]
        key_a = derive_key(inp["passphrase"], inp["salt"].encode(), context=inp["context_a"])
        key_b = derive_key(inp["passphrase"], inp["salt"].encode(), context=inp["context_b"])
        assert key_a != key_b
