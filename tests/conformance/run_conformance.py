#!/usr/bin/env python3
"""Standalone conformance runner for SpanForge v1.1.

Usage::

    python tests/conformance/run_conformance.py [-v] [--fixture CATEGORY]

Loads fixture files from ``tests/conformance/fixtures/`` and executes each
test vector against the public SpanForge API.  Returns exit-code 0 when all
vectors pass, 1 on any failure.

The runner can be invoked independently of pytest so that third-party
implementations can validate their outputs against the same vectors.
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"
LEGACY_FIXTURE = Path(__file__).parent / "fixtures.json"

# Map of fixture category → file
CATEGORIES = {
    "signing": FIXTURES_DIR / "signing.json",
    "chain": FIXTURES_DIR / "chain.json",
    "migration": FIXTURES_DIR / "migration.json",
    "pii": FIXTURES_DIR / "pii.json",
    "key_security": FIXTURES_DIR / "key_security.json",
    "compliance": FIXTURES_DIR / "compliance.json",
}


def _load_cases(category: str | None = None) -> list[dict]:
    """Load test vectors from fixture JSON files."""
    cases: list[dict] = []
    if category:
        fp = CATEGORIES.get(category)
        if fp and fp.exists():
            cases.extend(json.loads(fp.read_text("utf-8")))
        return cases
    for fp in CATEGORIES.values():
        if fp.exists():
            cases.extend(json.loads(fp.read_text("utf-8")))
    return cases


def _run_c001(case: dict) -> tuple[bool, str]:
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
    ok = (
        signed.checksum.startswith(case["expect"]["checksum_prefix"])
        and signed.signature.startswith(case["expect"]["signature_prefix"])
        and verify(signed, case["org_secret"]) is case["expect"]["verify"]
    )
    return ok, "" if ok else "signing round-trip mismatch"


def _run_c002(case: dict) -> tuple[bool, str]:
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
    ok = (
        len(events) == 2
        and events[1].prev_id == events[0].event_id
        and stream.verify().valid is case["expect"]["chain_valid"]
    )
    return ok, "" if ok else "chain linkage failed"


def _run_c003(case: dict) -> tuple[bool, str]:
    from spanforge.event import Event, EventType
    from spanforge.exceptions import SigningError
    from spanforge.signing import sign

    event = Event(
        event_type=EventType(case["input"]["event_type"]),
        source=case["input"]["source"],
        payload=case["input"]["payload"],
    )
    try:
        sign(event, case["org_secret"])
        return False, "expected SigningError not raised"
    except SigningError:
        return True, ""


def _run_c004(case: dict) -> tuple[bool, str]:
    from spanforge.event import Event, EventType
    from spanforge.signing import sign, verify

    event = Event(
        event_type=EventType(case["input"]["event_type"]),
        source=case["input"]["source"],
        payload=case["input"]["payload"],
    )
    signed = sign(event, case["org_secret"])
    ok = verify(signed, case["wrong_secret"]) is case["expect"]["verify_wrong_key"]
    return ok, "" if ok else "wrong-key verify mismatch"


def _run_c005(case: dict) -> tuple[bool, str]:
    from spanforge.migrate import v1_to_v2

    result = v1_to_v2(case["input"])
    ok = (
        result["schema_version"] == case["expect"]["schema_version"]
        and "model_id" in result.get("payload", {})
        and "model" not in result.get("payload", {})
    )
    return ok, "" if ok else "migration v1→v2 mismatch"


def _run_c006(case: dict) -> tuple[bool, str]:
    from spanforge.redact import scan_payload

    result = scan_payload(case["input"])
    detected = {h.pii_type for h in result.hits}
    ok = (
        (not result.clean) is case["expect"]["pii_detected"]
        and all(t in detected for t in case["expect"]["pii_types"])
    )
    return ok, "" if ok else f"PII detection mismatch (got {detected})"


def _run_c007(case: dict) -> tuple[bool, str]:
    from spanforge.signing import validate_key_strength

    warnings = validate_key_strength(case["input"]["org_secret"])
    ok = bool(warnings) is case["expect"]["has_warnings"]
    return ok, "" if ok else f"key strength mismatch (warnings={warnings})"


def _run_c008(case: dict) -> tuple[bool, str]:
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
    ok = len(tombstones) == case["expect"]["tombstone_count"]
    return ok, "" if ok else f"tombstone count mismatch (got {len(tombstones)})"


def _run_c009(case: dict) -> tuple[bool, str]:
    from spanforge.config import configure
    from spanforge.egress import check_egress
    from spanforge.exceptions import EgressViolationError

    configure(no_egress=case["config"]["no_egress"])
    try:
        try:
            check_egress(case["input"]["endpoint"], case["input"]["backend"])
            return False, "expected EgressViolationError not raised"
        except EgressViolationError:
            return True, ""
    finally:
        configure(no_egress=False)


def _run_c010(case: dict) -> tuple[bool, str]:
    from spanforge.core.compliance_mapping import (
        ComplianceFramework,
        ComplianceMappingEngine,
    )

    framework_names = [f.name for f in ComplianceFramework]
    ok = (
        len(framework_names) == case["expect"]["framework_count"]
        and all(n in framework_names for n in case["expect"]["frameworks"])
    )
    if not ok:
        return False, f"framework mismatch (got {framework_names})"

    engine = ComplianceMappingEngine()
    for fw in ComplianceFramework:
        pkg = engine.generate_evidence_package(
            model_id="gpt-4",
            framework=fw,
            from_date="2025-01-01",
            to_date="2025-12-31",
            audit_events=[],
        )
        if pkg is None:
            return False, f"evidence package is None for {fw.name}"
    return True, ""


def _run_c011(case: dict) -> tuple[bool, str]:
    from spanforge.migrate import v1_to_v2

    result = v1_to_v2(case["input"])
    ok = (
        result.get("checksum", "").startswith(case["expect"]["checksum_prefix"])
        and result["schema_version"] == case["expect"]["schema_version"]
    )
    return ok, "" if ok else "md5→sha256 rehash failed"


def _run_c012(case: dict) -> tuple[bool, str]:
    from spanforge.migrate import v1_to_v2

    result = v1_to_v2(case["input"])
    tags = result.get("tags", {})
    ok = result["schema_version"] == "2.0" and all(isinstance(v, str) for v in tags.values())
    return ok, "" if ok else f"tag coercion failed: {tags}"


def _run_c013(case: dict) -> tuple[bool, str]:
    from spanforge.redact import scan_payload

    result = scan_payload(case["input"])
    detected = {h.pii_type for h in result.hits}
    ok = (not result.clean) is case["expect"]["pii_detected"] and all(
        t in detected for t in case["expect"]["pii_types"]
    )
    return ok, "" if ok else f"SSN detection mismatch (got {detected})"


def _run_c014(case: dict) -> tuple[bool, str]:
    from spanforge.redact import scan_payload

    result = scan_payload(case["input"])
    ok = (not result.clean) is case["expect"]["pii_detected"]
    if ok and result.hits:
        hit = result.hits[0]
        ok = hit.match_count >= case["expect"]["first_hit_match_count_gte"]
        ok = ok and hasattr(hit, "sensitivity") and hit.sensitivity != ""
    return ok, "" if ok else "match_count/sensitivity mismatch"


def _run_c015(case: dict) -> tuple[bool, str]:
    from spanforge.redact import scan_payload

    result = scan_payload(case["input"])
    ok = result.clean is (not case["expect"]["pii_detected"])
    return ok, "" if ok else "Luhn false positive not filtered"


def _run_c016(case: dict) -> tuple[bool, str]:
    from spanforge.signing import check_key_expiry

    status, days = check_key_expiry(case["input"]["expires_at"])
    ok = status == case["expect"]["status"] and days > 0
    return ok, "" if ok else f"expiry mismatch (status={status}, days={days})"


def _run_c017(case: dict) -> tuple[bool, str]:
    from spanforge.signing import derive_key

    inp = case["input"]
    key_a = derive_key(inp["passphrase"], inp["salt"].encode(), context=inp["context_a"])
    key_b = derive_key(inp["passphrase"], inp["salt"].encode(), context=inp["context_b"])
    ok = key_a != key_b
    return ok, "" if ok else "derive_key context isolation failed"


RUNNERS: dict[str, object] = {
    "C001": _run_c001,
    "C002": _run_c002,
    "C003": _run_c003,
    "C004": _run_c004,
    "C005": _run_c005,
    "C006": _run_c006,
    "C007": _run_c007,
    "C008": _run_c008,
    "C009": _run_c009,
    "C010": _run_c010,
    "C011": _run_c011,
    "C012": _run_c012,
    "C013": _run_c013,
    "C014": _run_c014,
    "C015": _run_c015,
    "C016": _run_c016,
    "C017": _run_c017,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SpanForge conformance runner")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Print details for each test"
    )
    parser.add_argument(
        "--fixture",
        default=None,
        choices=list(CATEGORIES.keys()),
        help="Run only a specific fixture category",
    )
    args = parser.parse_args(argv)

    cases = _load_cases(args.fixture)
    passed = 0
    failed = 0
    skipped = 0

    for case in cases:
        cid = case["id"]
        title = case.get("title", "")
        clause = case.get("clause", "")
        runner = RUNNERS.get(cid)
        if runner is None:
            if args.verbose:
                print(f"  SKIP  {cid} {title} (no runner)")
            skipped += 1
            continue
        try:
            ok, detail = runner(case)  # type: ignore[operator]
            if ok:
                passed += 1
                if args.verbose:
                    print(f"  PASS  {cid} {title}")
            else:
                failed += 1
                print(f"  FAIL  {cid} {title}: {detail}")
                if clause:
                    print(f"        clause: {clause}")
        except Exception:
            failed += 1
            print(f"  ERROR {cid} {title}")
            traceback.print_exc(limit=3)

    print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
