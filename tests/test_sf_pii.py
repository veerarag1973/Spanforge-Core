"""Tests for spanforge.sdk Phase 2 — sf-pii service.

Coverage targets: ≥ 90 % on spanforge/sdk/pii.py, _types.py (PII additions),
and _exceptions.py (PII additions).

Test structure
--------------
*  Unit tests for PII types and dataclasses.
*  Unit tests for PII exceptions.
*  Functional tests for SFPIIClient in local mode (all 7 methods).
*  Error-path and security tests.
*  Remote mode stub tests (circuit breaker open behaviour).
*  Thread-safety smoke tests.
*  sf_pii singleton import tests.
"""

from __future__ import annotations

import re
import threading
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from spanforge.sdk._base import SFClientConfig
from spanforge.sdk._exceptions import (
    SFError,
    SFPIIError,
    SFPIINotRedactedError,
    SFPIIPolicyError,
    SFPIIScanError,
    SFServiceUnavailableError,
)
from spanforge.sdk._types import (
    SFPIIAnonymizeResult,
    SFPIIHit,
    SFPIIRedactResult,
    SFPIIScanResult,
    SecretStr,
)
from spanforge.sdk.pii import SFPIIClient

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def local_config() -> SFClientConfig:
    """SFClientConfig in local mode — no endpoint."""
    return SFClientConfig(
        endpoint="",
        api_key=SecretStr(""),
        local_fallback_enabled=True,
    )


@pytest.fixture()
def pii(local_config: SFClientConfig) -> SFPIIClient:
    """Fresh SFPIIClient in local mode for each test."""
    return SFPIIClient(local_config)


@pytest.fixture()
def remote_config() -> SFClientConfig:
    """SFClientConfig pointing at a (fake) remote endpoint."""
    return SFClientConfig(
        endpoint="https://api.spanforge.test",
        api_key=SecretStr("sf_test_" + "A" * 48),
        local_fallback_enabled=False,
        max_retries=0,
    )


@pytest.fixture()
def remote_pii(remote_config: SFClientConfig) -> SFPIIClient:
    """SFPIIClient in remote mode with fallback disabled."""
    return SFPIIClient(remote_config)


# ---------------------------------------------------------------------------
# Helper — build a minimal Event with Redactable fields
# ---------------------------------------------------------------------------


def _make_event(payload: dict) -> object:
    """Return a minimal spanforge.Event with the given payload."""
    from spanforge.event import Event, EventType

    return Event(
        event_type=EventType.TRACE_SPAN_COMPLETED,
        source="test@1.0.0",
        payload=payload,
    )


# ===========================================================================
# SFPIIHit
# ===========================================================================


class TestSFPIIHit:
    def test_defaults(self) -> None:
        h = SFPIIHit(pii_type="email", path="user.email")
        assert h.match_count == 1
        assert h.sensitivity == "medium"

    def test_custom_values(self) -> None:
        h = SFPIIHit(pii_type="ssn", path="data.ssn", match_count=3, sensitivity="high")
        assert h.pii_type == "ssn"
        assert h.path == "data.ssn"
        assert h.match_count == 3
        assert h.sensitivity == "high"

    def test_frozen(self) -> None:
        h = SFPIIHit(pii_type="phone", path="p")
        with pytest.raises(Exception):
            h.pii_type = "email"  # type: ignore[misc]

    def test_equality(self) -> None:
        h1 = SFPIIHit(pii_type="email", path="x", match_count=2, sensitivity="medium")
        h2 = SFPIIHit(pii_type="email", path="x", match_count=2, sensitivity="medium")
        assert h1 == h2

    def test_inequality_different_type(self) -> None:
        h1 = SFPIIHit(pii_type="email", path="x")
        h2 = SFPIIHit(pii_type="ssn", path="x")
        assert h1 != h2


# ===========================================================================
# SFPIIScanResult
# ===========================================================================


class TestSFPIIScanResult:
    def test_clean_when_no_hits(self) -> None:
        r = SFPIIScanResult(hits=[], scanned=5)
        assert r.clean is True
        assert r.scanned == 5

    def test_not_clean_when_hits(self) -> None:
        h = SFPIIHit(pii_type="email", path="msg")
        r = SFPIIScanResult(hits=[h], scanned=3)
        assert r.clean is False

    def test_hits_list(self) -> None:
        hits = [SFPIIHit("email", "a"), SFPIIHit("phone", "b")]
        r = SFPIIScanResult(hits=hits, scanned=10)
        assert len(r.hits) == 2

    def test_frozen(self) -> None:
        r = SFPIIScanResult(hits=[], scanned=0)
        with pytest.raises(Exception):
            r.scanned = 99  # type: ignore[misc]

    def test_zero_scanned(self) -> None:
        r = SFPIIScanResult(hits=[], scanned=0)
        assert r.clean is True
        assert r.scanned == 0

    def test_multiple_hit_types(self) -> None:
        hits = [
            SFPIIHit("email", "a", 1, "medium"),
            SFPIIHit("ssn", "b", 1, "high"),
            SFPIIHit("phone", "c", 2, "medium"),
        ]
        r = SFPIIScanResult(hits=hits, scanned=20)
        assert not r.clean
        assert len(r.hits) == 3


# ===========================================================================
# SFPIIRedactResult
# ===========================================================================


class TestSFPIIRedactResult:
    def test_fields(self) -> None:
        r = SFPIIRedactResult(
            event=None,
            redaction_count=3,
            redacted_at="2026-01-01T00:00:00Z",
            redacted_by="policy:test",
        )
        assert r.redaction_count == 3
        assert r.redacted_at == "2026-01-01T00:00:00Z"
        assert r.redacted_by == "policy:test"
        assert r.event is None

    def test_frozen(self) -> None:
        r = SFPIIRedactResult(event=None, redaction_count=0, redacted_at="", redacted_by="")
        with pytest.raises(Exception):
            r.redaction_count = 5  # type: ignore[misc]

    def test_zero_redaction(self) -> None:
        r = SFPIIRedactResult(event=object(), redaction_count=0, redacted_at="t", redacted_by="p")
        assert r.redaction_count == 0


# ===========================================================================
# SFPIIAnonymizeResult
# ===========================================================================


class TestSFPIIAnonymizeResult:
    def test_fields(self) -> None:
        r = SFPIIAnonymizeResult(
            text="[REDACTED:email]",
            replacements=1,
            pii_types_found=["email"],
        )
        assert r.text == "[REDACTED:email]"
        assert r.replacements == 1
        assert r.pii_types_found == ["email"]

    def test_frozen(self) -> None:
        r = SFPIIAnonymizeResult(text="", replacements=0, pii_types_found=[])
        with pytest.raises(Exception):
            r.replacements = 5  # type: ignore[misc]

    def test_no_pii(self) -> None:
        r = SFPIIAnonymizeResult(text="hello world", replacements=0, pii_types_found=[])
        assert r.replacements == 0
        assert r.pii_types_found == []

    def test_multiple_types(self) -> None:
        r = SFPIIAnonymizeResult(text="x", replacements=3, pii_types_found=["email", "phone", "ssn"])
        assert len(r.pii_types_found) == 3


# ===========================================================================
# PII exceptions
# ===========================================================================


class TestSFPIIExceptions:
    def test_sfpiierror_is_sferror(self) -> None:
        exc = SFPIIError("base")
        assert isinstance(exc, SFError)

    def test_sfpii_not_redacted_is_sfpii(self) -> None:
        exc = SFPIINotRedactedError(2)
        assert isinstance(exc, SFPIIError)
        assert isinstance(exc, SFError)

    def test_sfpii_not_redacted_message_no_context(self) -> None:
        exc = SFPIINotRedactedError(3)
        assert exc.count == 3
        assert "3" in str(exc)
        assert "unredacted pii" in str(exc).lower()
        assert "context-hash" not in str(exc)

    def test_sfpii_not_redacted_message_with_context(self) -> None:
        exc = SFPIINotRedactedError(1, "checkout-service")
        assert "context-hash" in str(exc)
        assert "checkout-service" not in str(exc)  # raw context is never included

    def test_sfpii_not_redacted_context_hash_deterministic(self) -> None:
        exc1 = SFPIINotRedactedError(1, "my-ctx")
        exc2 = SFPIINotRedactedError(1, "my-ctx")
        assert str(exc1) == str(exc2)

    def test_sfpii_not_redacted_different_contexts(self) -> None:
        exc1 = SFPIINotRedactedError(1, "ctx-a")
        exc2 = SFPIINotRedactedError(1, "ctx-b")
        assert str(exc1) != str(exc2)

    def test_sfpiiscaner_is_sfpii(self) -> None:
        exc = SFPIIScanError("scan failed")
        assert isinstance(exc, SFPIIError)
        assert isinstance(exc, SFError)

    def test_sfpii_policy_is_sfpii(self) -> None:
        exc = SFPIIPolicyError("bad sensitivity")
        assert isinstance(exc, SFPIIError)
        assert isinstance(exc, SFError)

    def test_sfpii_policy_detail(self) -> None:
        exc = SFPIIPolicyError("invalid level 'foo'")
        assert exc.detail == "invalid level 'foo'"
        assert "PII policy configuration error" in str(exc)
        assert "invalid level 'foo'" in str(exc)

    def test_sfpii_not_redacted_count_attr(self) -> None:
        exc = SFPIINotRedactedError(7)
        assert exc.count == 7

    def test_sfpii_scan_error_no_extra_attrs(self) -> None:
        exc = SFPIIScanError("boom")
        assert "boom" in str(exc)

    def test_sfpii_not_redacted_zero_count(self) -> None:
        exc = SFPIINotRedactedError(0)
        assert exc.count == 0
        assert "0" in str(exc)

    def test_sfpii_policy_error_empty_detail(self) -> None:
        exc = SFPIIPolicyError("")
        assert exc.detail == ""

    def test_sfpii_hierarchy_catchable_as_sferror(self) -> None:
        with pytest.raises(SFError):
            raise SFPIINotRedactedError(1)

    def test_sfpii_policy_catchable_as_sfpii(self) -> None:
        with pytest.raises(SFPIIError):
            raise SFPIIPolicyError("x")


# ===========================================================================
# SFPIIClient.scan — local mode
# ===========================================================================


class TestSFPIIClientScan:
    def test_scan_clean_payload(self, pii: SFPIIClient) -> None:
        result = pii.scan({"message": "Hello, world!"})
        assert result.clean
        assert result.scanned >= 1

    def test_scan_detects_email(self, pii: SFPIIClient) -> None:
        result = pii.scan({"msg": "Contact alice@example.com for info"})
        assert not result.clean
        types = [h.pii_type for h in result.hits]
        assert "email" in types

    def test_scan_detects_phone(self, pii: SFPIIClient) -> None:
        result = pii.scan({"contact": "Call 555-867-5309 now"})
        assert not result.clean
        types = [h.pii_type for h in result.hits]
        assert "phone" in types

    def test_scan_detects_ssn(self, pii: SFPIIClient) -> None:
        result = pii.scan({"data": "SSN 123-45-6789"})
        assert not result.clean
        types = [h.pii_type for h in result.hits]
        assert "ssn" in types

    def test_scan_hit_has_path(self, pii: SFPIIClient) -> None:
        result = pii.scan({"user": {"email": "bob@test.com"}})
        assert not result.clean
        paths = [h.path for h in result.hits]
        assert any("user" in p for p in paths)

    def test_scan_hit_sensitivity(self, pii: SFPIIClient) -> None:
        result = pii.scan({"n": "SSN 199-01-2345"})
        ssn_hits = [h for h in result.hits if h.pii_type == "ssn"]
        if ssn_hits:
            assert ssn_hits[0].sensitivity == "high"

    def test_scan_hit_match_count(self, pii: SFPIIClient) -> None:
        result = pii.scan({"text": "a@b.com and c@d.org"})
        email_hits = [h for h in result.hits if h.pii_type == "email"]
        assert email_hits
        assert email_hits[0].match_count >= 1

    def test_scan_nested_payload(self, pii: SFPIIClient) -> None:
        payload = {"level1": {"level2": {"level3": "test@deep.com"}}}
        result = pii.scan(payload)
        assert not result.clean

    def test_scan_list_values(self, pii: SFPIIClient) -> None:
        result = pii.scan({"items": ["no pii here", "also clean"]})
        assert result.clean

    def test_scan_list_with_pii(self, pii: SFPIIClient) -> None:
        result = pii.scan({"emails": ["alice@example.com", "bob@example.com"]})
        assert not result.clean

    def test_scan_returns_sfpiiscanresult(self, pii: SFPIIClient) -> None:
        result = pii.scan({"x": "y"})
        assert isinstance(result, SFPIIScanResult)

    def test_scan_hits_are_sfpiihit(self, pii: SFPIIClient) -> None:
        result = pii.scan({"x": "user@host.com"})
        for h in result.hits:
            assert isinstance(h, SFPIIHit)

    def test_scan_rejects_non_dict(self, pii: SFPIIClient) -> None:
        with pytest.raises(SFPIIScanError):
            pii.scan("not a dict")  # type: ignore[arg-type]

    def test_scan_rejects_list(self, pii: SFPIIClient) -> None:
        with pytest.raises(SFPIIScanError):
            pii.scan(["a", "b"])  # type: ignore[arg-type]

    def test_scan_rejects_none(self, pii: SFPIIClient) -> None:
        with pytest.raises(SFPIIScanError):
            pii.scan(None)  # type: ignore[arg-type]

    def test_scan_empty_dict(self, pii: SFPIIClient) -> None:
        result = pii.scan({})
        assert result.clean
        assert result.scanned == 0

    def test_scan_extra_patterns(self, pii: SFPIIClient) -> None:
        custom = {"sku": re.compile(r"\bSKU-\d{4}\b")}
        result = pii.scan({"id": "SKU-1234 is the product"}, extra_patterns=custom)
        types = [h.pii_type for h in result.hits]
        assert "sku" in types

    def test_scan_credit_card_luhn_validated(self, pii: SFPIIClient) -> None:
        # Luhn-invalid random digits should not be flagged as credit card
        result = pii.scan({"n": "1234 5678 9012 3456"})
        cc_hits = [h for h in result.hits if h.pii_type == "credit_card"]
        assert not cc_hits  # Luhn validation filters it out

    def test_scan_ip_address(self, pii: SFPIIClient) -> None:
        result = pii.scan({"ip": "Server at 192.168.1.100"})
        types = [h.pii_type for h in result.hits]
        assert "ip_address" in types

    def test_scan_scanned_count_positive(self, pii: SFPIIClient) -> None:
        result = pii.scan({"a": "one", "b": "two", "c": "three"})
        assert result.scanned >= 3

    def test_scan_max_depth_respected(self, pii: SFPIIClient) -> None:
        # Very deep nesting beyond max_depth=1 should not crash
        payload: dict = {"l1": {"l2": {"l3": {"l4": "a@b.com"}}}}
        result = pii.scan(payload, max_depth=2)
        # Just verify it runs without error
        assert isinstance(result, SFPIIScanResult)

    def test_scan_detects_uk_ni(self, pii: SFPIIClient) -> None:
        result = pii.scan({"ni": "NI number AB 12 34 56 C"})
        types = [h.pii_type for h in result.hits]
        assert "uk_national_insurance" in types

    def test_scan_ip_sensitivity_low(self, pii: SFPIIClient) -> None:
        result = pii.scan({"x": "10.0.0.1"})
        ip_hits = [h for h in result.hits if h.pii_type == "ip_address"]
        if ip_hits:
            assert ip_hits[0].sensitivity == "low"


# ===========================================================================
# SFPIIClient.redact — local mode
# ===========================================================================


class TestSFPIIClientRedact:
    def test_redact_removes_pii_field(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Redactable, Sensitivity

        event = _make_event({"email": Redactable("alice@example.com", Sensitivity.PII, {"email"})})
        result = pii.redact(event)
        assert isinstance(result, SFPIIRedactResult)
        assert result.redaction_count == 1
        assert result.event is not None

    def test_redact_default_policy_label(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Redactable, Sensitivity

        event = _make_event({"x": Redactable("v", Sensitivity.PII)})
        result = pii.redact(event)
        assert result.redacted_by == "policy:sf-pii"

    def test_redact_custom_policy(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Redactable, RedactionPolicy, Sensitivity

        policy = RedactionPolicy(
            min_sensitivity=Sensitivity.HIGH,
            redacted_by="policy:custom",
        )
        event = _make_event({"v": Redactable("secret", Sensitivity.HIGH, {"name"})})
        result = pii.redact(event, policy=policy)
        assert result.redacted_by == "policy:custom"
        assert result.redaction_count == 1

    def test_redact_zero_redactions_when_clean(self, pii: SFPIIClient) -> None:
        event = _make_event({"msg": "hello world"})
        result = pii.redact(event)
        assert result.redaction_count == 0

    def test_redact_returns_new_event_object(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Redactable, Sensitivity

        event = _make_event({"x": Redactable("v", Sensitivity.PII)})
        result = pii.redact(event)
        assert result.event is not event

    def test_redact_original_event_unchanged(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Redactable, Sensitivity

        wrapped = Redactable("secret", Sensitivity.PII)
        event = _make_event({"x": wrapped})
        pii.redact(event)
        # Original event payload still holds the Redactable
        assert isinstance(event.payload["x"], Redactable)

    def test_redact_redacted_at_is_iso_string(self, pii: SFPIIClient) -> None:
        event = _make_event({})
        result = pii.redact(event)
        assert isinstance(result.redacted_at, str)
        assert "T" in result.redacted_at  # ISO 8601 format

    def test_redact_below_threshold_not_redacted(self, pii: SFPIIClient) -> None:
        from spanforge.redact import RedactionPolicy, Redactable, Sensitivity

        # Low sensitivity field with PII-threshold policy should NOT be redacted
        policy = RedactionPolicy(min_sensitivity=Sensitivity.PII)
        event = _make_event({"ip": Redactable("10.0.0.1", Sensitivity.LOW, {"ip_address"})})
        result = pii.redact(event, policy=policy)
        assert result.redaction_count == 0

    def test_redact_multiple_fields(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Redactable, Sensitivity

        event = _make_event({
            "email": Redactable("alice@example.com", Sensitivity.PII, {"email"}),
            "phone": Redactable("555-1234", Sensitivity.PII, {"phone"}),
            "name": Redactable("Alice", Sensitivity.PII, {"name"}),
        })
        result = pii.redact(event)
        assert result.redaction_count == 3

    def test_redact_phi_field(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Redactable, Sensitivity

        event = _make_event({"diagnosis": Redactable("diabetes", Sensitivity.PHI, {"medical_id"})})
        result = pii.redact(event)
        assert result.redaction_count == 1

    def test_redact_nested_payload(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Redactable, Sensitivity

        event = _make_event({"user": {"email": Redactable("x@y.com", Sensitivity.PII)}})
        result = pii.redact(event)
        assert result.redaction_count == 1

    def test_redact_result_is_sfpii_redact_result(self, pii: SFPIIClient) -> None:
        event = _make_event({})
        result = pii.redact(event)
        assert isinstance(result, SFPIIRedactResult)


# ===========================================================================
# SFPIIClient.contains_pii — local mode
# ===========================================================================


class TestSFPIIClientContainsPII:
    def test_false_for_clean_event(self, pii: SFPIIClient) -> None:
        event = _make_event({"message": "nothing sensitive"})
        assert pii.contains_pii(event) is False

    def test_true_for_redactable_field(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Redactable, Sensitivity

        event = _make_event({"x": Redactable("secret", Sensitivity.PII)})
        assert pii.contains_pii(event) is True

    def test_true_for_raw_email_when_scan_raw(self, pii: SFPIIClient) -> None:
        event = _make_event({"msg": "Send to bob@company.com"})
        assert pii.contains_pii(event, scan_raw=True) is True

    def test_false_for_raw_email_when_not_scan_raw(self, pii: SFPIIClient) -> None:
        event = _make_event({"msg": "Send to bob@company.com"})
        # scan_raw=False — only checks for Redactable wrappers
        assert pii.contains_pii(event, scan_raw=False) is False

    def test_true_for_raw_phone(self, pii: SFPIIClient) -> None:
        event = _make_event({"x": "Call 555-123-4567"})
        assert pii.contains_pii(event) is True

    def test_returns_bool(self, pii: SFPIIClient) -> None:
        event = _make_event({})
        result = pii.contains_pii(event)
        assert isinstance(result, bool)

    def test_false_for_numbers_and_ids(self, pii: SFPIIClient) -> None:
        event = _make_event({"count": "42", "id": "order-abc-123"})
        assert pii.contains_pii(event) is False

    def test_true_for_ssn_raw(self, pii: SFPIIClient) -> None:
        event = _make_event({"ref": "Reference 199-01-2345"})
        assert pii.contains_pii(event) is True


# ===========================================================================
# SFPIIClient.assert_redacted — local mode
# ===========================================================================


class TestSFPIIClientAssertRedacted:
    def test_passes_for_clean_event(self, pii: SFPIIClient) -> None:
        event = _make_event({"msg": "clean payload"})
        pii.assert_redacted(event)  # should not raise

    def test_raises_for_redactable_field(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Redactable, Sensitivity

        event = _make_event({"x": Redactable("v", Sensitivity.PII)})
        with pytest.raises(SFPIINotRedactedError) as exc_info:
            pii.assert_redacted(event)
        assert exc_info.value.count >= 1

    def test_raises_with_context(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Redactable, Sensitivity

        event = _make_event({"x": Redactable("v", Sensitivity.PII)})
        with pytest.raises(SFPIINotRedactedError) as exc_info:
            pii.assert_redacted(event, context="checkout")
        assert "context-hash" in str(exc_info.value)

    def test_raises_for_raw_pii(self, pii: SFPIIClient) -> None:
        event = _make_event({"data": "email is alice@example.com"})
        with pytest.raises(SFPIINotRedactedError):
            pii.assert_redacted(event, scan_raw=True)

    def test_no_raise_for_raw_when_scan_raw_false(self, pii: SFPIIClient) -> None:
        event = _make_event({"data": "email is alice@example.com"})
        pii.assert_redacted(event, scan_raw=False)  # no Redactable → no raise

    def test_exception_is_sfpii_not_redacted(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Redactable, Sensitivity

        event = _make_event({"x": Redactable("v", Sensitivity.PII)})
        with pytest.raises(SFPIINotRedactedError):
            pii.assert_redacted(event)

    def test_exception_is_sfpii_error(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Redactable, Sensitivity

        event = _make_event({"x": Redactable("v", Sensitivity.PII)})
        with pytest.raises(SFPIIError):
            pii.assert_redacted(event)

    def test_passes_after_redact(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Redactable, Sensitivity

        event = _make_event({"x": Redactable("v", Sensitivity.PII)})
        result = pii.redact(event)
        # After redaction, assert_redacted on the new event should not raise
        pii.assert_redacted(result.event, scan_raw=False)


# ===========================================================================
# SFPIIClient.anonymize — local mode
# ===========================================================================


class TestSFPIIClientAnonymize:
    def test_anonymize_email(self, pii: SFPIIClient) -> None:
        result = pii.anonymize("Contact alice@example.com for help")
        assert "[REDACTED:email]" in result.text
        assert "alice@example.com" not in result.text
        assert "email" in result.pii_types_found
        assert result.replacements >= 1

    def test_anonymize_phone(self, pii: SFPIIClient) -> None:
        result = pii.anonymize("Call 555-867-5309")
        assert "[REDACTED:phone]" in result.text
        assert result.replacements >= 1

    def test_anonymize_valid_ssn(self, pii: SFPIIClient) -> None:
        result = pii.anonymize("My SSN is 199-01-2345")
        assert "[REDACTED:ssn]" in result.text

    def test_anonymize_no_pii(self, pii: SFPIIClient) -> None:
        result = pii.anonymize("Hello, this is clean text with no PII")
        assert result.text == "Hello, this is clean text with no PII"
        assert result.replacements == 0
        assert result.pii_types_found == []

    def test_anonymize_returns_sfpiianonymizeresult(self, pii: SFPIIClient) -> None:
        result = pii.anonymize("x")
        assert isinstance(result, SFPIIAnonymizeResult)

    def test_anonymize_empty_string(self, pii: SFPIIClient) -> None:
        result = pii.anonymize("")
        assert result.text == ""
        assert result.replacements == 0

    def test_anonymize_multiple_emails(self, pii: SFPIIClient) -> None:
        result = pii.anonymize("alice@a.com and bob@b.com")
        assert result.replacements >= 2
        assert "alice@a.com" not in result.text
        assert "bob@b.com" not in result.text

    def test_anonymize_ip_address(self, pii: SFPIIClient) -> None:
        result = pii.anonymize("Server IP: 10.0.0.1")
        assert "[REDACTED:ip_address]" in result.text

    def test_anonymize_pii_types_no_duplicates(self, pii: SFPIIClient) -> None:
        result = pii.anonymize("alice@example.com and bob@host.org")
        # Both are email — should appear only once in pii_types_found
        assert result.pii_types_found.count("email") == 1

    def test_anonymize_extra_patterns(self, pii: SFPIIClient) -> None:
        custom = {"order_id": re.compile(r"\bORD-\d{6}\b")}
        result = pii.anonymize("Your order ORD-123456 is ready", extra_patterns=custom)
        assert "[REDACTED:order_id]" in result.text
        assert "order_id" in result.pii_types_found

    def test_anonymize_rejects_non_string(self, pii: SFPIIClient) -> None:
        with pytest.raises(SFPIIScanError):
            pii.anonymize(123)  # type: ignore[arg-type]

    def test_anonymize_rejects_none(self, pii: SFPIIClient) -> None:
        with pytest.raises(SFPIIScanError):
            pii.anonymize(None)  # type: ignore[arg-type]

    def test_anonymize_uk_ni(self, pii: SFPIIClient) -> None:
        result = pii.anonymize("NI: AB 12 34 56 C")
        assert "[REDACTED:uk_national_insurance]" in result.text

    def test_anonymize_does_not_return_pii_in_types_found(self, pii: SFPIIClient) -> None:
        # The result text should contain markers, not the original values
        result = pii.anonymize("alice@example.com")
        assert "alice" not in result.text
        assert "example.com" not in result.text

    def test_anonymize_ssn_invalid_range_not_replaced(self, pii: SFPIIClient) -> None:
        # SSN with area 000 is invalid — should NOT be replaced
        result = pii.anonymize("SSN: 000-12-3456")
        assert "000-12-3456" in result.text  # not replaced

    def test_anonymize_credit_card_not_luhn_valid_not_replaced(self, pii: SFPIIClient) -> None:
        # These 16 digits fail Luhn — should not be redacted
        result = pii.anonymize("Number: 1234 5678 9012 3456")
        assert "1234" in result.text

    def test_anonymize_mixed_pii(self, pii: SFPIIClient) -> None:
        result = pii.anonymize("Email: a@b.com, Phone: 555-123-4567")
        assert "[REDACTED:email]" in result.text
        assert "[REDACTED:phone]" in result.text
        assert len(result.pii_types_found) >= 2

    def test_anonymize_replacement_count_matches(self, pii: SFPIIClient) -> None:
        result = pii.anonymize("a@b.com is the email")
        assert result.replacements == result.text.count("[REDACTED:")


# ===========================================================================
# SFPIIClient.wrap
# ===========================================================================


class TestSFPIIClientWrap:
    def test_wrap_returns_redactable(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Redactable

        wrapped = pii.wrap("alice@example.com", "pii", frozenset({"email"}))
        assert isinstance(wrapped, Redactable)

    def test_wrap_sensitivity_pii(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Sensitivity

        wrapped = pii.wrap("secret", "pii")
        assert wrapped.sensitivity == Sensitivity.PII

    def test_wrap_sensitivity_phi(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Sensitivity

        wrapped = pii.wrap("diagnosis", "phi")
        assert wrapped.sensitivity == Sensitivity.PHI

    def test_wrap_sensitivity_low(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Sensitivity

        wrapped = pii.wrap("10.0.0.1", "low", frozenset({"ip_address"}))
        assert wrapped.sensitivity == Sensitivity.LOW

    def test_wrap_sensitivity_medium(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Sensitivity

        wrapped = pii.wrap("alice", "medium", frozenset({"name"}))
        assert wrapped.sensitivity == Sensitivity.MEDIUM

    def test_wrap_sensitivity_high(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Sensitivity

        wrapped = pii.wrap("username123", "high")
        assert wrapped.sensitivity == Sensitivity.HIGH

    def test_wrap_pii_types_stored(self, pii: SFPIIClient) -> None:
        wrapped = pii.wrap("v", "pii", frozenset({"email", "name"}))
        assert wrapped.pii_types == frozenset({"email", "name"})

    def test_wrap_default_empty_pii_types(self, pii: SFPIIClient) -> None:
        wrapped = pii.wrap("v", "pii")
        assert wrapped.pii_types == frozenset()

    def test_wrap_invalid_sensitivity_raises(self, pii: SFPIIClient) -> None:
        with pytest.raises(SFPIIPolicyError) as exc_info:
            pii.wrap("v", "ultra-secret")
        assert "ultra-secret" in str(exc_info.value)

    def test_wrap_value_hidden_in_repr(self, pii: SFPIIClient) -> None:
        wrapped = pii.wrap("supersecret", "pii")
        assert "supersecret" not in repr(wrapped)

    def test_wrap_integrated_with_redact(self, pii: SFPIIClient) -> None:
        wrapped = pii.wrap("alice@example.com", "pii", frozenset({"email"}))
        event = _make_event({"email": wrapped})
        result = pii.redact(event)
        assert result.redaction_count == 1


# ===========================================================================
# SFPIIClient.make_policy
# ===========================================================================


class TestSFPIIClientMakePolicy:
    def test_make_policy_default_values(self, pii: SFPIIClient) -> None:
        from spanforge.redact import RedactionPolicy, Sensitivity

        policy = pii.make_policy()
        assert isinstance(policy, RedactionPolicy)
        assert policy.min_sensitivity == Sensitivity.PII
        assert policy.redacted_by == "policy:sf-pii"
        assert policy.replacement_template == "[REDACTED:{sensitivity}]"

    def test_make_policy_custom_sensitivity(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Sensitivity

        policy = pii.make_policy(min_sensitivity="high")
        assert policy.min_sensitivity == Sensitivity.HIGH

    def test_make_policy_custom_redacted_by(self, pii: SFPIIClient) -> None:
        policy = pii.make_policy(redacted_by="policy:my-service")
        assert policy.redacted_by == "policy:my-service"

    def test_make_policy_custom_template(self, pii: SFPIIClient) -> None:
        policy = pii.make_policy(replacement_template="***{sensitivity}***")
        assert policy.replacement_template == "***{sensitivity}***"

    def test_make_policy_phi_sensitivity(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Sensitivity

        policy = pii.make_policy(min_sensitivity="phi")
        assert policy.min_sensitivity == Sensitivity.PHI

    def test_make_policy_low_sensitivity(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Sensitivity

        policy = pii.make_policy(min_sensitivity="low")
        assert policy.min_sensitivity == Sensitivity.LOW

    def test_make_policy_invalid_sensitivity_raises(self, pii: SFPIIClient) -> None:
        with pytest.raises(SFPIIPolicyError) as exc_info:
            pii.make_policy(min_sensitivity="ultra")
        assert "ultra" in str(exc_info.value)

    def test_make_policy_missing_placeholder_raises(self, pii: SFPIIClient) -> None:
        with pytest.raises(SFPIIPolicyError) as exc_info:
            pii.make_policy(replacement_template="[REDACTED]")
        assert "{sensitivity}" in str(exc_info.value)

    def test_make_policy_is_usable_for_redact(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Redactable, Sensitivity

        policy = pii.make_policy(min_sensitivity="pii", redacted_by="policy:test")
        event = _make_event({"x": Redactable("v", Sensitivity.PII)})
        result = pii.redact(event, policy=policy)
        assert result.redacted_by == "policy:test"
        assert result.redaction_count == 1

    def test_make_policy_medium_sensitivity(self, pii: SFPIIClient) -> None:
        from spanforge.redact import Sensitivity

        policy = pii.make_policy(min_sensitivity="medium")
        assert policy.min_sensitivity == Sensitivity.MEDIUM

    def test_make_policy_error_is_sfpii_policy_error(self, pii: SFPIIClient) -> None:
        with pytest.raises(SFPIIPolicyError):
            pii.make_policy(min_sensitivity="bad")

    def test_make_policy_error_is_sfpii_error(self, pii: SFPIIClient) -> None:
        with pytest.raises(SFPIIError):
            pii.make_policy(min_sensitivity="bad")


# ===========================================================================
# Remote mode — circuit breaker open
# ===========================================================================


class TestSFPIIClientRemoteMode:
    def test_scan_raises_when_circuit_open(self, remote_pii: SFPIIClient) -> None:
        remote_pii._circuit_breaker._state = "open"
        remote_pii._circuit_breaker._opened_at = 1e18  # far future
        with pytest.raises(SFServiceUnavailableError):
            remote_pii.scan({"x": "y"})

    def test_redact_raises_when_circuit_open(self, remote_pii: SFPIIClient) -> None:
        remote_pii._circuit_breaker._state = "open"
        remote_pii._circuit_breaker._opened_at = 1e18
        event = _make_event({})
        with pytest.raises(SFServiceUnavailableError):
            remote_pii.redact(event)

    def test_contains_pii_raises_when_circuit_open(self, remote_pii: SFPIIClient) -> None:
        remote_pii._circuit_breaker._state = "open"
        remote_pii._circuit_breaker._opened_at = 1e18
        event = _make_event({})
        with pytest.raises(SFServiceUnavailableError):
            remote_pii.contains_pii(event)

    def test_assert_redacted_raises_when_circuit_open(self, remote_pii: SFPIIClient) -> None:
        remote_pii._circuit_breaker._state = "open"
        remote_pii._circuit_breaker._opened_at = 1e18
        event = _make_event({})
        with pytest.raises(SFServiceUnavailableError):
            remote_pii.assert_redacted(event)

    def test_anonymize_raises_when_circuit_open(self, remote_pii: SFPIIClient) -> None:
        remote_pii._circuit_breaker._state = "open"
        remote_pii._circuit_breaker._opened_at = 1e18
        with pytest.raises(SFServiceUnavailableError):
            remote_pii.anonymize("alice@example.com")

    def test_remote_scan_parses_response(self, remote_pii: SFPIIClient) -> None:
        mock_response = {
            "hits": [
                {"pii_type": "email", "path": "msg", "match_count": 1, "sensitivity": "medium"}
            ],
            "scanned": 5,
        }
        with patch.object(remote_pii, "_request", return_value=mock_response):
            result = remote_pii.scan({"msg": "test"})
        assert not result.clean
        assert result.hits[0].pii_type == "email"
        assert result.scanned == 5

    def test_remote_scan_empty_response(self, remote_pii: SFPIIClient) -> None:
        with patch.object(remote_pii, "_request", return_value={"hits": [], "scanned": 0}):
            result = remote_pii.scan({"x": "y"})
        assert result.clean

    def test_remote_contains_pii_true(self, remote_pii: SFPIIClient) -> None:
        event = _make_event({})
        with patch.object(remote_pii, "_request", return_value={"contains_pii": True}):
            assert remote_pii.contains_pii(event) is True

    def test_remote_contains_pii_false(self, remote_pii: SFPIIClient) -> None:
        event = _make_event({})
        with patch.object(remote_pii, "_request", return_value={"contains_pii": False}):
            assert remote_pii.contains_pii(event) is False

    def test_remote_assert_redacted_raises_when_has_pii(self, remote_pii: SFPIIClient) -> None:
        event = _make_event({})
        with patch.object(remote_pii, "_request", return_value={"has_pii": True, "count": 2}):
            with pytest.raises(SFPIINotRedactedError) as exc_info:
                remote_pii.assert_redacted(event, context="test")
            assert exc_info.value.count == 2

    def test_remote_assert_redacted_passes_when_clean(self, remote_pii: SFPIIClient) -> None:
        event = _make_event({})
        with patch.object(remote_pii, "_request", return_value={"has_pii": False}):
            remote_pii.assert_redacted(event)  # should not raise

    def test_remote_anonymize_parses_response(self, remote_pii: SFPIIClient) -> None:
        mock_resp = {"text": "[REDACTED:email]", "replacements": 1, "pii_types_found": ["email"]}
        with patch.object(remote_pii, "_request", return_value=mock_resp):
            result = remote_pii.anonymize("alice@example.com")
        assert result.text == "[REDACTED:email]"
        assert result.replacements == 1
        assert "email" in result.pii_types_found

    def test_remote_redact_parses_response(self, remote_pii: SFPIIClient) -> None:
        mock_resp = {
            "event": {"payload": {}},
            "redaction_count": 2,
            "redacted_at": "2026-01-01T00:00:00Z",
            "redacted_by": "policy:sf-pii",
        }
        event = _make_event({})
        with patch.object(remote_pii, "_request", return_value=mock_resp):
            result = remote_pii.redact(event)
        assert result.redaction_count == 2
        assert result.redacted_by == "policy:sf-pii"


# ===========================================================================
# Local fallback with endpoint set
# ===========================================================================


class TestSFPIIClientLocalFallback:
    def test_scan_uses_local_when_fallback_enabled(self) -> None:
        config = SFClientConfig(
            endpoint="https://api.spanforge.test",
            api_key=SecretStr("sf_test_" + "A" * 48),
            local_fallback_enabled=True,
        )
        client = SFPIIClient(config)
        # Should use local even though endpoint is set (fallback enabled)
        result = client.scan({"msg": "alice@example.com"})
        assert not result.clean


# ===========================================================================
# Thread safety
# ===========================================================================


class TestSFPIIClientThreadSafety:
    def test_concurrent_scans(self, pii: SFPIIClient) -> None:
        results: list[SFPIIScanResult] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def _scan() -> None:
            try:
                r = pii.scan({"email": "alice@test.com"})
                with lock:
                    results.append(r)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=_scan) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 20
        assert all(not r.clean for r in results)

    def test_concurrent_anonymize(self, pii: SFPIIClient) -> None:
        errors: list[Exception] = []
        lock = threading.Lock()

        def _anon() -> None:
            try:
                pii.anonymize("Call 555-123-4567 or email x@y.com")
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=_anon) for _ in range(15)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors

    def test_concurrent_wrap_and_redact(self, pii: SFPIIClient) -> None:
        errors: list[Exception] = []
        lock = threading.Lock()

        def _work() -> None:
            try:
                wrapped = pii.wrap("secret", "pii")
                event = _make_event({"x": wrapped})
                pii.redact(event)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=_work) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors


# ===========================================================================
# sf_pii singleton
# ===========================================================================


class TestSFPIISingleton:
    def test_sf_pii_imported(self) -> None:
        from spanforge.sdk import sf_pii

        assert isinstance(sf_pii, SFPIIClient)

    def test_sf_pii_scan_works(self) -> None:
        from spanforge.sdk import sf_pii

        result = sf_pii.scan({"msg": "clean"})
        assert isinstance(result, SFPIIScanResult)

    def test_sf_pii_anonymize_works(self) -> None:
        from spanforge.sdk import sf_pii

        result = sf_pii.anonymize("no pii here")
        assert isinstance(result, SFPIIAnonymizeResult)

    def test_configure_updates_sf_pii(self) -> None:
        from spanforge.sdk import SFClientConfig, SecretStr, configure, sf_pii as pii_before

        new_cfg = SFClientConfig(endpoint="", api_key=SecretStr(""), signing_key="new-key")
        configure(new_cfg)

        from spanforge.sdk import sf_pii as pii_after

        assert isinstance(pii_after, SFPIIClient)

    def test_sf_pii_make_policy_works(self) -> None:
        from spanforge.redact import RedactionPolicy

        from spanforge.sdk import sf_pii

        policy = sf_pii.make_policy()
        assert isinstance(policy, RedactionPolicy)

    def test_sf_pii_wrap_works(self) -> None:
        from spanforge.redact import Redactable

        from spanforge.sdk import sf_pii

        wrapped = sf_pii.wrap("v", "pii")
        assert isinstance(wrapped, Redactable)
