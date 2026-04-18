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
from typing import TYPE_CHECKING, Any
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
    SecretStr,
    SFPIIAnonymizeResult,
    SFPIIHit,
    SFPIIRedactResult,
    SFPIIScanResult,
)
from spanforge.sdk.pii import SFPIIClient

if TYPE_CHECKING:
    from io import BytesIO

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
        from spanforge.redact import Redactable, RedactionPolicy, Sensitivity

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
            except Exception as exc:
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
            except Exception as exc:
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
            except Exception as exc:
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
        from spanforge.sdk import SecretStr, SFClientConfig, configure

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


# ===========================================================================
# Phase 3 — PII Service Hardening tests
# ===========================================================================


# ---------------------------------------------------------------------------
# New type dataclasses
# ---------------------------------------------------------------------------


class TestPIIEntity:
    def test_fields(self) -> None:
        from spanforge.sdk._types import PIIEntity

        e = PIIEntity(type="email", start=0, end=5, score=0.9)
        assert e.type == "email"
        assert e.start == 0
        assert e.end == 5
        assert e.score == 0.9

    def test_frozen(self) -> None:
        from spanforge.sdk._types import PIIEntity

        e = PIIEntity(type="email", start=0, end=5, score=0.9)
        with pytest.raises((AttributeError, TypeError)):
            e.type = "ssn"  # type: ignore[misc]


class TestPIITextScanResult:
    def test_detected_true(self) -> None:
        from spanforge.sdk._types import PIIEntity, PIITextScanResult

        r = PIITextScanResult(
            entities=[PIIEntity(type="email", start=0, end=5, score=1.0)],
            redacted_text="<EMAIL>",
            detected=True,
        )
        assert r.detected is True
        assert len(r.entities) == 1

    def test_detected_false(self) -> None:
        from spanforge.sdk._types import PIITextScanResult

        r = PIITextScanResult(entities=[], redacted_text="hello", detected=False)
        assert r.detected is False


class TestPIIAnonymisedResult:
    def test_fields(self) -> None:
        from spanforge.sdk._types import PIIAnonymisedResult, PIIRedactionManifestEntry

        entry = PIIRedactionManifestEntry(
            field_path="name",
            type="email",
            original_hash="abc",
            replacement="<EMAIL>",
        )
        r = PIIAnonymisedResult(clean_payload={"name": "<EMAIL>"}, redaction_manifest=[entry])
        assert r.clean_payload == {"name": "<EMAIL>"}
        assert len(r.redaction_manifest) == 1


class TestPIIPipelineResult:
    def test_fields(self) -> None:
        from spanforge.sdk._types import PIIPipelineResult

        r = PIIPipelineResult(
            text="hello",
            action="flag",
            detected=False,
            entity_types=[],
            low_confidence_hits=[],
            redacted_text="hello",
            blocked=False,
        )
        assert r.action == "flag"
        assert r.blocked is False


class TestPIIStatusInfo:
    def test_fields(self) -> None:
        from spanforge.sdk._types import PIIStatusInfo

        s = PIIStatusInfo(
            status="ok",
            presidio_available=False,
            entity_types_loaded=["email"],
            last_scan_at=None,
        )
        assert s.status == "ok"
        assert s.presidio_available is False


class TestErasureReceipt:
    def test_fields(self) -> None:
        from spanforge.sdk._types import ErasureReceipt

        r = ErasureReceipt(
            subject_id="u1",
            project_id="p1",
            records_erased=3,
            erasure_id="eid",
            erased_at="2024-01-01T00:00:00Z",
            exceptions=[],
        )
        assert r.records_erased == 3
        assert r.exceptions == []


class TestDSARExport:
    def test_fields(self) -> None:
        from spanforge.sdk._types import DSARExport

        d = DSARExport(
            subject_id="u1",
            project_id="p1",
            event_count=0,
            export_id="eid",
            exported_at="2024-01-01T00:00:00Z",
            events=[],
        )
        assert d.event_count == 0


class TestSafeHarborResult:
    def test_fields(self) -> None:
        from spanforge.sdk._types import SafeHarborResult

        r = SafeHarborResult(text="hello", replacements=0, phi_types_found=[])
        assert r.replacements == 0


class TestPIIHeatMapEntry:
    def test_fields(self) -> None:
        from spanforge.sdk._types import PIIHeatMapEntry

        h = PIIHeatMapEntry(project_id="p", entity_type="email", date="2024-01-01", count=5)
        assert h.count == 5


class TestTrainingDataPIIReport:
    def test_fields(self) -> None:
        from spanforge.sdk._types import TrainingDataPIIReport

        r = TrainingDataPIIReport(
            dataset_path="/tmp/data.jsonl",
            total_records=100,
            pii_records=10,
            prevalence_pct=10.0,
            entity_counts={"email": 10},
            report_id="rid",
            generated_at="2024-01-01T00:00:00Z",
        )
        assert r.prevalence_pct == 10.0


# ---------------------------------------------------------------------------
# New exceptions
# ---------------------------------------------------------------------------


class TestSFPIIBlockedError:
    def test_attributes(self) -> None:
        from spanforge.sdk._exceptions import SFPIIBlockedError

        err = SFPIIBlockedError(entity_types=["email", "ssn"], count=2)
        assert err.entity_types == ["email", "ssn"]
        assert err.count == 2
        assert "block" in str(err)

    def test_inherits_sfpii(self) -> None:
        from spanforge.sdk._exceptions import SFPIIBlockedError, SFPIIError

        err = SFPIIBlockedError(entity_types=[], count=0)
        assert isinstance(err, SFPIIError)


class TestSFPIIDPDPConsentMissingError:
    def test_attributes(self) -> None:
        from spanforge.sdk._exceptions import SFPIIDPDPConsentMissingError

        err = SFPIIDPDPConsentMissingError(
            subject_id="u1", purpose="analytics", entity_type="aadhaar"
        )
        assert err.purpose == "analytics"
        assert err.entity_type == "aadhaar"
        # raw subject_id must NOT appear in message (security)
        assert "u1" not in str(err)

    def test_subject_id_hashed(self) -> None:
        import hashlib

        from spanforge.sdk._exceptions import SFPIIDPDPConsentMissingError

        err = SFPIIDPDPConsentMissingError(
            subject_id="my_user", purpose="analytics", entity_type="pan"
        )
        expected_hash_prefix = hashlib.sha256(b"my_user").hexdigest()[:12]
        assert expected_hash_prefix in str(err)


# ---------------------------------------------------------------------------
# PIPL patterns
# ---------------------------------------------------------------------------


class TestPIPLPatterns:
    def test_cn_national_id_valid(self) -> None:
        from spanforge.presidio_backend import PIPL_PATTERNS

        pat = PIPL_PATTERNS["cn_national_id"]
        assert pat.search("110101199003077515")  # 18 chars, ends digit
        assert pat.search("11010119900307751X")  # ends X

    def test_cn_national_id_invalid(self) -> None:
        from spanforge.presidio_backend import PIPL_PATTERNS

        pat = PIPL_PATTERNS["cn_national_id"]
        assert not pat.search("12345")  # too short

    def test_cn_mobile_valid(self) -> None:
        from spanforge.presidio_backend import PIPL_PATTERNS

        pat = PIPL_PATTERNS["cn_mobile"]
        assert pat.search("13812345678")
        assert pat.search("19987654321")

    def test_cn_mobile_invalid(self) -> None:
        from spanforge.presidio_backend import PIPL_PATTERNS

        pat = PIPL_PATTERNS["cn_mobile"]
        assert not pat.search("12312345678")  # starts with 12

    def test_cn_bank_card_valid(self) -> None:
        from spanforge.presidio_backend import PIPL_PATTERNS

        pat = PIPL_PATTERNS["cn_bank_card"]
        assert pat.search("6225888888888888")  # 16 digits

    def test_pipl_sensitive_types(self) -> None:
        from spanforge.presidio_backend import PIPL_PATTERNS, PIPL_SENSITIVE_TYPES

        assert frozenset(PIPL_PATTERNS.keys()) == PIPL_SENSITIVE_TYPES


# ---------------------------------------------------------------------------
# presidio_scan_text
# ---------------------------------------------------------------------------


class TestPresidioScanText:
    def test_fallback_when_presidio_unavailable(self) -> None:
        """presidio_scan_text should raise ImportError when engine unavailable."""
        from spanforge.presidio_backend import is_available, presidio_scan_text

        if is_available():
            pytest.skip("Presidio is installed — skipping unavailability test")
        with pytest.raises(ImportError):
            presidio_scan_text("my email is test@example.com")

    def test_returns_correct_shape_when_available(self) -> None:
        """When Presidio is installed, shape check."""
        from spanforge.presidio_backend import is_available, presidio_scan_text

        if not is_available():
            pytest.skip("Presidio not installed")
        entities, redacted, detected = presidio_scan_text("Call me at test@example.com")
        assert isinstance(entities, list)
        assert isinstance(redacted, str)
        assert isinstance(detected, bool)
        if detected:
            for e in entities:
                assert {"type", "start", "end", "score"} == set(e.keys())


# ---------------------------------------------------------------------------
# SFPIIClient.scan_text (PII-001)
# ---------------------------------------------------------------------------


class TestScanText:
    @pytest.fixture()
    def client(self, local_config: SFClientConfig) -> SFPIIClient:
        return SFPIIClient(local_config)

    def test_scan_text_no_pii(self, client: SFPIIClient) -> None:
        result = client.scan_text("The quick brown fox")
        assert result.detected is False
        assert result.entities == []
        assert result.redacted_text == "The quick brown fox"

    def test_scan_text_detects_email(self, client: SFPIIClient) -> None:
        result = client.scan_text("Contact alice@example.com today")
        assert result.detected is True
        assert any(e.type == "email" for e in result.entities)

    def test_scan_text_detects_ssn(self, client: SFPIIClient) -> None:
        result = client.scan_text("SSN is 123-45-6789")
        assert result.detected is True
        assert any(e.type == "ssn" for e in result.entities)

    def test_scan_text_redacts_email(self, client: SFPIIClient) -> None:
        result = client.scan_text("Email: test@example.com")
        assert "<EMAIL>" in result.redacted_text.upper() or "EMAIL" in result.redacted_text.upper()

    def test_scan_text_entities_have_correct_types(self, client: SFPIIClient) -> None:
        from spanforge.sdk._types import PIIEntity

        result = client.scan_text("test@example.com")
        for e in result.entities:
            assert isinstance(e, PIIEntity)
            assert isinstance(e.start, int)
            assert isinstance(e.end, int)
            assert isinstance(e.score, float)

    def test_scan_text_tracks_last_scan_at(self, client: SFPIIClient) -> None:
        assert client._last_scan_at is None
        client.scan_text("hello")
        assert client._last_scan_at is not None

    def test_scan_text_rejects_non_str(self, client: SFPIIClient) -> None:
        with pytest.raises(SFPIIScanError):
            client.scan_text(123)  # type: ignore[arg-type]

    def test_scan_text_entity_values_not_in_result(self, client: SFPIIClient) -> None:
        """Security: raw PII values must never appear in scan result."""
        text = "alice@example.com"
        result = client.scan_text(text)
        # The entities must not expose the actual email string
        for e in result.entities:
            assert not hasattr(e, "value")

    def test_scan_text_presidio_path(self, client: SFPIIClient) -> None:
        """Test Presidio code path (mocked)."""
        fake_entities = [{"type": "EMAIL_ADDRESS", "start": 0, "end": 16, "score": 0.85}]
        with patch("spanforge.presidio_backend.is_available", return_value=True), patch(
            "spanforge.presidio_backend.presidio_scan_text",
            return_value=(fake_entities, "<EMAIL_ADDRESS>", True),
        ):
            result = client.scan_text("alice@example.com")
        assert result.detected is True
        assert result.entities[0].type == "EMAIL_ADDRESS"

    def test_scan_text_presidio_import_error_fallback(self, client: SFPIIClient) -> None:
        """If Presidio raises ImportError, fall back to regex."""
        with patch("spanforge.presidio_backend.is_available", return_value=True), patch(
            "spanforge.presidio_backend.presidio_scan_text",
            side_effect=ImportError("no presidio"),
        ):
            result = client.scan_text("Call 555-867-5309")
        # Should succeed via regex fallback
        assert isinstance(result.detected, bool)


# ---------------------------------------------------------------------------
# SFPIIClient.anonymise (PII-002)
# ---------------------------------------------------------------------------


class TestAnonymise:
    @pytest.fixture()
    def client(self, local_config: SFClientConfig) -> SFPIIClient:
        return SFPIIClient(local_config)

    def test_anonymise_flat_dict(self, client: SFPIIClient) -> None:
        payload = {"message": "email is alice@example.com"}
        result = client.anonymise(payload)
        assert "alice@example.com" not in result.clean_payload.get("message", "")

    def test_anonymise_manifest_has_hash(self, client: SFPIIClient) -> None:
        import hashlib

        payload = {"x": "alice@example.com"}
        result = client.anonymise(payload)
        if result.redaction_manifest:
            hashed = hashlib.sha256(b"alice@example.com").hexdigest()
            hashes = [e.original_hash for e in result.redaction_manifest]
            assert hashed in hashes

    def test_anonymise_manifest_never_raw_value(self, client: SFPIIClient) -> None:
        payload = {"msg": "ssn 123-45-6789"}
        result = client.anonymise(payload)
        for entry in result.redaction_manifest:
            assert "123-45-6789" not in entry.original_hash

    def test_anonymise_nested_dict(self, client: SFPIIClient) -> None:
        payload = {"user": {"contact": {"email": "bob@example.com"}}}
        result = client.anonymise(payload)
        inner = result.clean_payload["user"]["contact"]["email"]
        assert "bob@example.com" not in inner

    def test_anonymise_list_values(self, client: SFPIIClient) -> None:
        payload = {"emails": ["a@b.com", "clean text"]}
        result = client.anonymise(payload)
        assert "a@b.com" not in result.clean_payload["emails"][0]

    def test_anonymise_no_pii(self, client: SFPIIClient) -> None:
        payload = {"msg": "no pii here"}
        result = client.anonymise(payload)
        assert result.clean_payload == payload
        assert result.redaction_manifest == []

    def test_anonymise_non_dict_raises(self, client: SFPIIClient) -> None:
        with pytest.raises(SFPIIScanError):
            client.anonymise("not a dict")  # type: ignore[arg-type]

    def test_anonymise_returns_type(self, client: SFPIIClient) -> None:
        from spanforge.sdk._types import PIIAnonymisedResult

        result = client.anonymise({"x": "hello"})
        assert isinstance(result, PIIAnonymisedResult)


# ---------------------------------------------------------------------------
# SFPIIClient.scan_batch (PII-003)
# ---------------------------------------------------------------------------


class TestScanBatch:
    @pytest.fixture()
    def client(self, local_config: SFClientConfig) -> SFPIIClient:
        return SFPIIClient(local_config)

    def test_scan_batch_empty(self, client: SFPIIClient) -> None:
        assert client.scan_batch([]) == []

    def test_scan_batch_returns_same_order(self, client: SFPIIClient) -> None:
        texts = ["alice@example.com", "no pii", "ssn 123-45-6789"]
        results = client.scan_batch(texts)
        assert len(results) == 3
        assert results[0].detected is True  # email
        assert results[1].detected is False  # no pii
        assert results[2].detected is True   # ssn

    def test_scan_batch_rejects_non_list(self, client: SFPIIClient) -> None:
        with pytest.raises(SFPIIScanError):
            client.scan_batch("not a list")  # type: ignore[arg-type]

    def test_scan_batch_rejects_non_str_element(self, client: SFPIIClient) -> None:
        with pytest.raises(SFPIIScanError):
            client.scan_batch(["valid", 42])  # type: ignore[list-item]

    def test_scan_batch_parallel(self, client: SFPIIClient) -> None:
        texts = ["clean"] * 10
        results = client.scan_batch(texts, max_workers=4)
        assert all(not r.detected for r in results)


# ---------------------------------------------------------------------------
# SFPIIClient.apply_pipeline_action (PII-010/011/012)
# ---------------------------------------------------------------------------


class TestApplyPipelineAction:
    @pytest.fixture()
    def client(self, local_config: SFClientConfig) -> SFPIIClient:
        return SFPIIClient(local_config)

    def test_flag_no_pii(self, client: SFPIIClient) -> None:
        from spanforge.sdk._types import PIIPipelineResult

        result = client.apply_pipeline_action("no pii here", action="flag")
        assert isinstance(result, PIIPipelineResult)
        assert result.action == "flag"
        assert result.detected is False
        assert result.blocked is False

    def test_flag_with_pii(self, client: SFPIIClient) -> None:
        result = client.apply_pipeline_action("alice@example.com", action="flag", threshold=0.0)
        assert result.action == "flag"
        assert result.detected is True

    def test_redact_action(self, client: SFPIIClient) -> None:
        result = client.apply_pipeline_action(
            "email alice@example.com here", action="redact", threshold=0.0
        )
        assert result.action == "redact"
        assert "alice@example.com" not in result.text

    def test_block_action_raises(self, client: SFPIIClient) -> None:
        from spanforge.sdk._exceptions import SFPIIBlockedError

        with pytest.raises(SFPIIBlockedError) as exc_info:
            client.apply_pipeline_action("alice@example.com", action="block", threshold=0.0)
        assert exc_info.value.count >= 1

    def test_block_action_no_pii_no_raise(self, client: SFPIIClient) -> None:
        result = client.apply_pipeline_action("clean text", action="block", threshold=0.0)
        assert result.detected is False
        assert result.blocked is False

    def test_threshold_splits_entities(self, client: SFPIIClient) -> None:
        """Entities below threshold go to low_confidence_hits, not triggering action."""
        # Patch scan to return low-score entity
        from spanforge.sdk._types import PIIEntity

        fake_result = MagicMock()
        fake_result.entities = [PIIEntity(type="email", start=0, end=16, score=0.3)]
        with patch.object(client, "_scan_text_local", return_value=fake_result):
            result = client.apply_pipeline_action(
                "alice@example.com", action="block", threshold=0.5
            )
        assert result.detected is False
        assert len(result.low_confidence_hits) == 1

    def test_invalid_action_raises(self, client: SFPIIClient) -> None:
        with pytest.raises(SFPIIScanError):
            client.apply_pipeline_action("text", action="unknown")

    def test_non_str_raises(self, client: SFPIIClient) -> None:
        with pytest.raises(SFPIIScanError):
            client.apply_pipeline_action(42, action="flag")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# SFPIIClient.get_status (PII-005)
# ---------------------------------------------------------------------------


class TestGetStatus:
    @pytest.fixture()
    def client(self, local_config: SFClientConfig) -> SFPIIClient:
        return SFPIIClient(local_config)

    def test_status_ok(self, client: SFPIIClient) -> None:
        from spanforge.sdk._types import PIIStatusInfo

        status = client.get_status()
        assert isinstance(status, PIIStatusInfo)
        assert status.status == "ok"

    def test_entity_types_loaded(self, client: SFPIIClient) -> None:
        status = client.get_status()
        assert "email" in status.entity_types_loaded

    def test_presidio_available_false_without_presidio(self, client: SFPIIClient) -> None:
        with patch("spanforge.presidio_backend.is_available", return_value=False):
            status = client.get_status()
        assert status.presidio_available is False

    def test_last_scan_at_none_initially(self, client: SFPIIClient) -> None:
        status = client.get_status()
        assert status.last_scan_at is None

    def test_last_scan_at_set_after_scan(self, client: SFPIIClient) -> None:
        client.scan_text("hello")
        status = client.get_status()
        assert status.last_scan_at is not None


# ---------------------------------------------------------------------------
# SFPIIClient.erase_subject (PII-021)
# ---------------------------------------------------------------------------


class TestEraseSubject:
    @pytest.fixture()
    def client(self, local_config: SFClientConfig) -> SFPIIClient:
        return SFPIIClient(local_config)

    def test_returns_erasure_receipt(self, client: SFPIIClient) -> None:
        from spanforge.sdk._types import ErasureReceipt

        receipt = client.erase_subject("user123", "proj456")
        assert isinstance(receipt, ErasureReceipt)

    def test_receipt_has_erasure_id(self, client: SFPIIClient) -> None:
        import uuid

        receipt = client.erase_subject("u1", "p1")
        uuid.UUID(receipt.erasure_id)  # should not raise

    def test_receipt_erased_at_is_iso(self, client: SFPIIClient) -> None:
        import datetime

        receipt = client.erase_subject("u1", "p1")
        dt = datetime.datetime.fromisoformat(receipt.erased_at.replace("Z", "+00:00"))
        assert dt.year >= 2024

    def test_receipt_exceptions_empty(self, client: SFPIIClient) -> None:
        receipt = client.erase_subject("u1", "p1")
        assert receipt.exceptions == []

    def test_empty_subject_id_raises(self, client: SFPIIClient) -> None:
        from spanforge.sdk._exceptions import SFPIIError

        with pytest.raises(SFPIIError):
            client.erase_subject("", "p1")

    def test_empty_project_id_raises(self, client: SFPIIClient) -> None:
        from spanforge.sdk._exceptions import SFPIIError

        with pytest.raises(SFPIIError):
            client.erase_subject("u1", "")


# ---------------------------------------------------------------------------
# SFPIIClient.export_subject_data (PII-022)
# ---------------------------------------------------------------------------


class TestExportSubjectData:
    @pytest.fixture()
    def client(self, local_config: SFClientConfig) -> SFPIIClient:
        return SFPIIClient(local_config)

    def test_returns_dsar_export(self, client: SFPIIClient) -> None:
        from spanforge.sdk._types import DSARExport

        export = client.export_subject_data("u1", "p1")
        assert isinstance(export, DSARExport)

    def test_export_id_is_uuid(self, client: SFPIIClient) -> None:
        import uuid

        export = client.export_subject_data("u1", "p1")
        uuid.UUID(export.export_id)

    def test_events_list(self, client: SFPIIClient) -> None:
        export = client.export_subject_data("u1", "p1")
        assert isinstance(export.events, list)

    def test_empty_subject_id_raises(self, client: SFPIIClient) -> None:
        from spanforge.sdk._exceptions import SFPIIError

        with pytest.raises(SFPIIError):
            client.export_subject_data("", "p1")

    def test_empty_project_id_raises(self, client: SFPIIClient) -> None:
        from spanforge.sdk._exceptions import SFPIIError

        with pytest.raises(SFPIIError):
            client.export_subject_data("u1", "")


# ---------------------------------------------------------------------------
# SFPIIClient.safe_harbor_deidentify (PII-023)
# ---------------------------------------------------------------------------


class TestSafeHarborDeidentify:
    @pytest.fixture()
    def client(self, local_config: SFClientConfig) -> SFPIIClient:
        return SFPIIClient(local_config)

    def test_removes_email(self, client: SFPIIClient) -> None:
        result = client.safe_harbor_deidentify("Contact alice@example.com")
        assert "alice@example.com" not in result.text
        assert result.replacements >= 1
        assert "email" in result.phi_types_found

    def test_removes_phone(self, client: SFPIIClient) -> None:
        result = client.safe_harbor_deidentify("Call 555-867-5309")
        assert "555-867-5309" not in result.text

    def test_removes_ssn(self, client: SFPIIClient) -> None:
        result = client.safe_harbor_deidentify("SSN: 123-45-6789")
        assert "123-45-6789" not in result.text

    def test_truncates_zip(self, client: SFPIIClient) -> None:
        result = client.safe_harbor_deidentify("ZIP 90210")
        assert "90210" not in result.text
        assert "902" in result.text  # first 3 digits preserved

    def test_replaces_age_over_89(self, client: SFPIIClient) -> None:
        result = client.safe_harbor_deidentify("Patient is 92 years old")
        assert "90+" in result.text

    def test_does_not_modify_age_under_90(self, client: SFPIIClient) -> None:
        result = client.safe_harbor_deidentify("Patient is 45 years old")
        assert "45" in result.text

    def test_removes_url(self, client: SFPIIClient) -> None:
        result = client.safe_harbor_deidentify("Visit https://example.com/health")
        assert "https://example.com/health" not in result.text

    def test_removes_ip(self, client: SFPIIClient) -> None:
        result = client.safe_harbor_deidentify("From IP 192.168.1.100")
        assert "192.168.1.100" not in result.text

    def test_dates_reduced_to_year(self, client: SFPIIClient) -> None:
        result = client.safe_harbor_deidentify("DOB: 01/15/1985")
        assert "01/15/1985" not in result.text
        # Year should be preserved
        assert "1985" in result.text

    def test_no_pii_unchanged(self, client: SFPIIClient) -> None:
        result = client.safe_harbor_deidentify("No PHI here at all")
        assert result.replacements == 0

    def test_non_str_raises(self, client: SFPIIClient) -> None:
        with pytest.raises(SFPIIScanError):
            client.safe_harbor_deidentify(42)  # type: ignore[arg-type]

    def test_returns_safe_harbor_result(self, client: SFPIIClient) -> None:
        from spanforge.sdk._types import SafeHarborResult

        result = client.safe_harbor_deidentify("hello")
        assert isinstance(result, SafeHarborResult)


# ---------------------------------------------------------------------------
# SFPIIClient.audit_training_data (PII-025)
# ---------------------------------------------------------------------------


class TestAuditTrainingData:
    @pytest.fixture()
    def client(self, local_config: SFClientConfig) -> SFPIIClient:
        return SFPIIClient(local_config)

    def test_jsonl_scan(self, client: SFPIIClient, tmp_path: Any) -> None:
        from spanforge.sdk._types import TrainingDataPIIReport

        f = tmp_path / "data.jsonl"
        f.write_text(
            '{"text": "alice@example.com"}\n'
            '{"text": "no pii here"}\n'
            '{"text": "ssn 123-45-6789"}\n',
            encoding="utf-8",
        )
        report = client.audit_training_data(f)
        assert isinstance(report, TrainingDataPIIReport)
        assert report.total_records == 3
        assert report.pii_records >= 2
        assert report.prevalence_pct > 0

    def test_plain_text_scan(self, client: SFPIIClient, tmp_path: Any) -> None:
        f = tmp_path / "plain.txt"
        f.write_text("clean line\nalice@example.com\n", encoding="utf-8")
        report = client.audit_training_data(f)
        assert report.total_records == 2
        assert report.pii_records >= 1

    def test_entity_counts_populated(self, client: SFPIIClient, tmp_path: Any) -> None:
        f = tmp_path / "data.jsonl"
        f.write_text(
            '{"text": "alice@example.com"}\n{"text": "bob@example.com"}\n',
            encoding="utf-8",
        )
        report = client.audit_training_data(f)
        assert "email" in report.entity_counts
        assert report.entity_counts["email"] >= 2

    def test_report_id_is_uuid(self, client: SFPIIClient, tmp_path: Any) -> None:
        import uuid

        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        report = client.audit_training_data(f)
        uuid.UUID(report.report_id)

    def test_empty_file(self, client: SFPIIClient, tmp_path: Any) -> None:
        f = tmp_path / "empty.jsonl"
        f.write_text("", encoding="utf-8")
        report = client.audit_training_data(f)
        assert report.total_records == 0
        assert report.prevalence_pct == 0.0

    def test_missing_file_raises(self, client: SFPIIClient) -> None:
        with pytest.raises(SFPIIScanError):
            client.audit_training_data("/nonexistent/path/data.jsonl")

    def test_string_path(self, client: SFPIIClient, tmp_path: Any) -> None:
        f = tmp_path / "d.jsonl"
        f.write_text('{"text": "hello"}\n', encoding="utf-8")
        report = client.audit_training_data(str(f))
        assert report.total_records == 1


# ---------------------------------------------------------------------------
# SFPIIClient.get_pii_stats (PII-032)
# ---------------------------------------------------------------------------


class TestGetPIIStats:
    @pytest.fixture()
    def client(self, local_config: SFClientConfig) -> SFPIIClient:
        return SFPIIClient(local_config)

    def test_returns_list(self, client: SFPIIClient) -> None:
        result = client.get_pii_stats("proj1")
        assert isinstance(result, list)

    def test_empty_project_raises(self, client: SFPIIClient) -> None:
        from spanforge.sdk._exceptions import SFPIIError

        with pytest.raises(SFPIIError):
            client.get_pii_stats("")

    def test_entity_type_filter(self, client: SFPIIClient) -> None:
        result = client.get_pii_stats("proj1", entity_type="email")
        assert all(e.entity_type == "email" for e in result)

    def test_returns_heatmap_entries(self, client: SFPIIClient) -> None:
        from spanforge.sdk._types import PIIHeatMapEntry

        result = client.get_pii_stats("proj1")
        for entry in result:
            assert isinstance(entry, PIIHeatMapEntry)


# ---------------------------------------------------------------------------
# POST /v1/scan/pii endpoint (PII-004)
# ---------------------------------------------------------------------------


def _make_post_handler(
    path: str,
    body: bytes = b"",
    content_type: str = "application/json",
) -> tuple[Any, BytesIO]:
    """Create a _TraceAPIHandler with mocked HTTP machinery (no real socket)."""
    from io import BytesIO as _BytesIO

    from spanforge._server import _TraceAPIHandler

    h = object.__new__(_TraceAPIHandler)
    h._get_store = lambda: None  # type: ignore[attr-defined]
    h._cors_origins = ""  # type: ignore[attr-defined]
    h.path = path
    h.command = "POST"
    h.headers = MagicMock()
    h.headers.get = MagicMock(
        side_effect=lambda k, default=None: {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
        }.get(k, default)
    )
    h.rfile = _BytesIO(body)
    buf = _BytesIO()
    h.wfile = buf
    h.send_response = MagicMock()
    h.send_header = MagicMock()
    h.end_headers = MagicMock()
    return h, buf


def _make_get_handler_direct(path: str) -> tuple[Any, BytesIO]:
    """Create a _TraceAPIHandler for GET requests with mocked HTTP machinery."""
    from io import BytesIO as _BytesIO

    from spanforge._server import _TraceAPIHandler

    h = object.__new__(_TraceAPIHandler)
    h._get_store = lambda: None  # type: ignore[attr-defined]
    h._cors_origins = ""  # type: ignore[attr-defined]
    h.path = path
    h.command = "GET"
    h.headers = MagicMock()
    buf = _BytesIO()
    h.wfile = buf
    h.send_response = MagicMock()
    h.send_header = MagicMock()
    h.end_headers = MagicMock()
    return h, buf


class TestPostScanPIIEndpoint:
    def test_post_scan_pii_no_pii(self) -> None:
        import json as _json

        body = _json.dumps({"text": "clean text"}).encode()
        h, buf = _make_post_handler("/v1/scan/pii", body)
        h.do_POST()
        data = _json.loads(buf.getvalue())
        assert data["detected"] is False
        assert isinstance(data["entities"], list)

    def test_post_scan_pii_with_email(self) -> None:
        import json as _json

        body = _json.dumps({"text": "email is alice@example.com"}).encode()
        h, buf = _make_post_handler("/v1/scan/pii", body)
        h.do_POST()
        data = _json.loads(buf.getvalue())
        assert data["detected"] is True

    def test_post_scan_pii_invalid_json(self) -> None:
        h, _ = _make_post_handler("/v1/scan/pii", b"not json")
        h.do_POST()
        h.send_response.assert_called_with(400)

    def test_post_scan_pii_missing_text_field(self) -> None:
        import json as _json

        body = _json.dumps({"language": "en"}).encode()
        h, _ = _make_post_handler("/v1/scan/pii", body)
        h.do_POST()
        h.send_response.assert_called_with(400)

    def test_post_unknown_path_404(self) -> None:
        h, _ = _make_post_handler("/v1/unknown", b"{}")
        h.do_POST()
        h.send_response.assert_called_with(404)


# ---------------------------------------------------------------------------
# GET /v1/spanforge/status endpoint (PII-005)
# ---------------------------------------------------------------------------


class TestSpanforgeStatusEndpoint:
    def test_get_spanforge_status(self) -> None:
        import json as _json

        h, buf = _make_get_handler_direct("/v1/spanforge/status")
        h.do_GET()
        data = _json.loads(buf.getvalue())
        assert "sf_pii" in data
        assert "status" in data["sf_pii"]

    def test_status_has_entity_types(self) -> None:
        import json as _json

        h, buf = _make_get_handler_direct("/v1/spanforge/status")
        h.do_GET()
        data = _json.loads(buf.getvalue())
        assert isinstance(data["sf_pii"]["entity_types_loaded"], list)


# ---------------------------------------------------------------------------
# sdk/__init__.py Phase 3 export tests
# ---------------------------------------------------------------------------


class TestSDKPhase3Exports:
    def test_pii_blocked_error_exported(self) -> None:
        from spanforge.sdk import SFPIIBlockedError  # noqa: F401

    def test_dpdp_consent_error_exported(self) -> None:
        from spanforge.sdk import SFPIIDPDPConsentMissingError  # noqa: F401

    def test_pii_entity_exported(self) -> None:
        from spanforge.sdk import PIIEntity  # noqa: F401

    def test_pii_text_scan_result_exported(self) -> None:
        from spanforge.sdk import PIITextScanResult  # noqa: F401

    def test_pii_anonymised_result_exported(self) -> None:
        from spanforge.sdk import PIIAnonymisedResult  # noqa: F401

    def test_pii_pipeline_result_exported(self) -> None:
        from spanforge.sdk import PIIPipelineResult  # noqa: F401

    def test_pii_status_info_exported(self) -> None:
        from spanforge.sdk import PIIStatusInfo  # noqa: F401

    def test_erasure_receipt_exported(self) -> None:
        from spanforge.sdk import ErasureReceipt  # noqa: F401

    def test_dsar_export_exported(self) -> None:
        from spanforge.sdk import DSARExport  # noqa: F401

    def test_safe_harbor_result_exported(self) -> None:
        from spanforge.sdk import SafeHarborResult  # noqa: F401

    def test_pii_heatmap_entry_exported(self) -> None:
        from spanforge.sdk import PIIHeatMapEntry  # noqa: F401

    def test_training_data_report_exported(self) -> None:
        from spanforge.sdk import TrainingDataPIIReport  # noqa: F401

    def test_pii_redaction_manifest_entry_exported(self) -> None:
        from spanforge.sdk import PIIRedactionManifestEntry  # noqa: F401


# ---------------------------------------------------------------------------
# Coverage gap tests — Phase 3 edge cases
# ---------------------------------------------------------------------------


class TestCoverageGaps:
    @pytest.fixture()
    def client(self, local_config: SFClientConfig) -> SFPIIClient:
        return SFPIIClient(local_config)

    # anonymise depth limit
    def test_anonymise_max_depth_truncates(self, client: SFPIIClient) -> None:
        deeply_nested: dict[str, Any] = {}
        current = deeply_nested
        for _i in range(12):
            current["n"] = {}
            current = current["n"]  # type: ignore[assignment]
        current["email"] = "alice@example.com"
        # Should not raise even with very deep nesting
        result = client.anonymise(deeply_nested, max_depth=3)
        assert isinstance(result.clean_payload, dict)

    # anonymise non-str/dict/list fallback
    def test_anonymise_walk_non_serialisable_value(self, client: SFPIIClient) -> None:
        payload = {"value": 42}  # int not str — should pass through unchanged
        result = client.anonymise(payload)
        assert result.clean_payload["value"] == 42

    # scan_text — validator skips invalid CC / SSN / DOB
    def test_scan_text_invalid_cc_skipped(self, client: SFPIIClient) -> None:
        # Luhn-invalid number that matches pattern
        result = client.scan_text("card 1234567890123456")
        # Should not add invalid CC as entity (luhn fails)
        cc_hits = [e for e in result.entities if e.type == "credit_card"]
        assert len(cc_hits) == 0

    # audit_training_data — malformed JSON line falls back to plain text
    def test_audit_training_data_malformed_json(self, client: SFPIIClient, tmp_path: Any) -> None:
        f = tmp_path / "bad.jsonl"
        f.write_text("{not valid json\n", encoding="utf-8")
        report = client.audit_training_data(f)
        assert report.total_records == 1  # line was still processed as plain text

    # audit_training_data — max_records limits scan
    def test_audit_training_data_max_records(self, client: SFPIIClient, tmp_path: Any) -> None:
        f = tmp_path / "big.jsonl"
        f.write_text("\n".join(f'{{"text": "line {i}"}}' for i in range(20)), encoding="utf-8")
        report = client.audit_training_data(f, max_records=5)
        assert report.total_records == 5

    # audit_training_data — empty lines are skipped
    def test_audit_training_data_empty_lines(self, client: SFPIIClient, tmp_path: Any) -> None:
        f = tmp_path / "empty_lines.jsonl"
        f.write_text("\n\n\nhello\n\n", encoding="utf-8")
        report = client.audit_training_data(f)
        assert report.total_records == 1

    # safe_harbor — fax pattern
    def test_safe_harbor_removes_fax(self, client: SFPIIClient) -> None:
        result = client.safe_harbor_deidentify("Fax: 555-867-5309")
        assert "555-867-5309" not in result.text

    # safe_harbor — medical record
    def test_safe_harbor_removes_mrn(self, client: SFPIIClient) -> None:
        result = client.safe_harbor_deidentify("MRN 1234567")
        assert "1234567" not in result.text

    # safe_harbor — account number
    def test_safe_harbor_removes_account(self, client: SFPIIClient) -> None:
        result = client.safe_harbor_deidentify("Account: 1234567890")
        assert "1234567890" not in result.text

    # get_pii_stats — store traversal with matching events
    def test_get_pii_stats_with_store_events(self, client: SFPIIClient) -> None:
        """Test store traversal path for get_pii_stats by patching the store."""
        import datetime as _dt

        class FakeEvent:
            payload = {
                "project_id": "testproj",
                "event_class": "pii_detection",
                "entity_type": "email",
                "count": 2,
            }
            timestamp = _dt.datetime.now(_dt.timezone.utc).isoformat()

        class FakeStore:
            _lock = threading.Lock()
            _traces = {"trace1": [FakeEvent()]}

            @classmethod
            def get_default(cls) -> FakeStore:
                return cls()

        import sys

        fake_module = MagicMock()
        fake_module.TraceStore = FakeStore
        with patch.dict(sys.modules, {"spanforge._store": fake_module}):
            result = client.get_pii_stats("testproj")
        assert isinstance(result, list)

    # erase_subject — store traversal with matching subject
    def test_erase_subject_with_matching_events(self, client: SFPIIClient) -> None:
        class FakeEvent:
            payload: dict[str, Any] = {"subject_id": "u1", "project_id": "p1"}

        class FakeStore:
            _lock = threading.Lock()
            _traces: dict[str, list[Any]] = {"t1": [FakeEvent()]}

            @classmethod
            def get_default(cls) -> FakeStore:
                return cls()

        import sys

        fake_module = MagicMock()
        fake_module.TraceStore = FakeStore
        with patch.dict(sys.modules, {"spanforge._store": fake_module}):
            receipt = client.erase_subject("u1", "p1")
        assert receipt.records_erased >= 1

    # export_subject_data — store traversal with matching events
    def test_export_subject_data_with_matching_events(self, client: SFPIIClient) -> None:
        class FakeEvent:
            payload: dict[str, Any] = {"subject_id": "u2", "project_id": "p2"}
            event_id = "eid1"
            event_type = "pii.scan"
            timestamp = "2024-01-01T00:00:00Z"

        class FakeStore:
            _lock = threading.Lock()
            _traces: dict[str, list[Any]] = {"t2": [FakeEvent()]}

            @classmethod
            def get_default(cls) -> FakeStore:
                return cls()

        import sys

        fake_module = MagicMock()
        fake_module.TraceStore = FakeStore
        with patch.dict(sys.modules, {"spanforge._store": fake_module}):
            export = client.export_subject_data("u2", "p2")
        assert export.event_count >= 1


