"""tests/test_sdk_validate.py — CARD 1C-1 SFValidateClient production tests.

Covers all 10 required test cases:
1.  Schema check: valid JSON response → passes
2.  Schema check: malformed JSON response → violation collected
3.  Confidence check: score above threshold → passes
4.  Confidence check: score below threshold → violation collected
5.  Content policy: response with PII → violation collected
6.  Content policy: response with secret → auto_blocked=True
7.  Correction: one pass resolves violation → correction_passes=1, passed=True
8.  Correction: still failing after 2 passes → passed=False, correction_passes=2
9.  Audit: every call emits a signed record
10. validate() never raises on content violations — always returns ValidationResult
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from spanforge.sdk._base import SFClientConfig
from spanforge.sdk.validate import (
    SFValidateClient,
    ValidateStatusInfo,
    ValidationResult,
    Violation,
    _validate_against_schema,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client(**kwargs: Any) -> SFValidateClient:
    return SFValidateClient(SFClientConfig(project_id="test-1c1"), **kwargs)


def _audit_mock() -> MagicMock:
    """Return a mock sf_audit that records appended payloads and returns a signed result."""
    mock = MagicMock()
    result = MagicMock()
    result.hmac = "hmac-test-sig"
    result.record_id = "audit-rec-001"
    mock.append.return_value = result
    return mock


# ---------------------------------------------------------------------------
# TestSchemaCheck
# ---------------------------------------------------------------------------


class TestSchemaCheck:
    """Enforcement mechanism 1 — schema validation."""

    def test_valid_json_response_passes(self) -> None:
        """Schema check: valid JSON response → passes."""
        client = _make_client()
        schema = {"type": "object", "required": ["label", "score"]}
        response = '{"label": "positive", "score": 0.93}'

        with patch("spanforge.sdk.sf_audit", _audit_mock(), create=True):
            result = client.validate(response, schema=schema, confidence_score=0.93)

        assert result.passed is True
        schema_violations = [v for v in result.violations if v.type == "schema"]
        assert schema_violations == []

    def test_malformed_json_response_violation(self) -> None:
        """Schema check: malformed JSON response → violation collected."""
        client = _make_client()
        schema = {"type": "object", "required": ["label"]}
        response = "not-json-at-all"

        with patch("spanforge.sdk.validate.sf_audit", _audit_mock(), create=True):
            result = client.validate(response, schema=schema, confidence_score=0.95)

        assert result.passed is False
        schema_violations = [v for v in result.violations if v.type == "schema"]
        assert len(schema_violations) >= 1
        assert schema_violations[0].severity == "high"

    def test_regex_schema_passes_when_matched(self) -> None:
        """Schema check: regex pattern matching response text → passes."""
        client = _make_client()
        response = "The sentiment is POSITIVE with high confidence."

        with patch("spanforge.sdk.validate.sf_audit", _audit_mock(), create=True):
            result = client.validate(
                response, schema=r"POSITIVE|NEGATIVE", confidence_score=0.90
            )

        assert result.passed is True

    def test_regex_schema_violation_when_unmatched(self) -> None:
        """Schema check: regex pattern not matching → violation collected."""
        client = _make_client()
        response = "uncertain"

        with patch("spanforge.sdk.validate.sf_audit", _audit_mock(), create=True):
            result = client.validate(
                response, schema=r"POSITIVE|NEGATIVE", confidence_score=0.90
            )

        assert result.passed is False
        schema_violations = [v for v in result.violations if v.type == "schema"]
        assert len(schema_violations) == 1

    def test_dict_response_validated_as_json(self) -> None:
        """Schema check: dict response validated against JSON schema → passes."""
        client = _make_client()
        schema = {"type": "object", "required": ["answer"]}
        response = {"answer": "yes"}

        with patch("spanforge.sdk.sf_audit", _audit_mock(), create=True):
            result = client.validate(response, schema=schema, confidence_score=0.80)

        assert result.passed is True


# ---------------------------------------------------------------------------
# TestConfidenceCheck
# ---------------------------------------------------------------------------


class TestConfidenceCheck:
    """Enforcement mechanism 2 — confidence threshold."""

    def test_score_above_threshold_passes(self) -> None:
        """Confidence check: score above threshold → passes (no schema, no content violations)."""
        client = _make_client()

        with patch("spanforge.sdk.validate.sf_audit", _audit_mock(), create=True):
            result = client.validate(
                "Safe plain text response.",
                confidence_score=0.95,
            )

        confidence_violations = [v for v in result.violations if v.type == "confidence"]
        assert confidence_violations == []
        assert result.passed is True

    def test_score_below_threshold_violation(self) -> None:
        """Confidence check: score below threshold → violation collected."""
        client = _make_client()

        with patch("spanforge.sdk.validate.sf_audit", _audit_mock(), create=True):
            result = client.validate(
                "I am not sure about this answer.",
                confidence_score=0.40,
                confidence_threshold=0.70,
            )

        confidence_violations = [v for v in result.violations if v.type == "confidence"]
        assert len(confidence_violations) == 1
        assert "0.400" in confidence_violations[0].message
        assert confidence_violations[0].severity == "medium"
        assert result.passed is False

    def test_no_score_provided_check_skipped_when_explain_unavailable(self) -> None:
        """Confidence check: when score is None and sf_explain fails, check is skipped."""
        client = _make_client()

        with (
            patch("spanforge.sdk.sf_audit", _audit_mock(), create=True),
            patch(
                "spanforge.sdk.sf_pii",
                MagicMock(scan_text=MagicMock(return_value=MagicMock(detected=False, entities=[]))),
                create=True,
            ),
        ):
            # sf_explain not patched → import will succeed but generate may raise
            result = client.validate("Generic text.", confidence_score=None)

        # Should not raise; confidence violation only if score obtained and below threshold
        assert isinstance(result, ValidationResult)


# ---------------------------------------------------------------------------
# TestContentPolicy
# ---------------------------------------------------------------------------


class TestContentPolicy:
    """Enforcement mechanism 3 — PII and secrets content policy."""

    def test_response_with_pii_violation_collected(self) -> None:
        """Content policy: response with PII → pii violation collected."""
        client = _make_client()

        pii_entity = MagicMock()
        pii_entity.type = "EMAIL_ADDRESS"
        pii_result = MagicMock()
        pii_result.detected = True
        pii_result.entities = [pii_entity]

        mock_pii = MagicMock()
        mock_pii.scan_text.return_value = pii_result

        with (
            patch("spanforge.sdk.sf_audit", _audit_mock(), create=True),
            patch("spanforge.sdk.sf_pii", mock_pii, create=True),
        ):
            result = client.validate(
                "Contact user@example.com for details.",
                confidence_score=0.90,
            )

        pii_violations = [v for v in result.violations if v.type == "pii"]
        assert len(pii_violations) == 1
        assert pii_entity.type in pii_violations[0].message
        assert result.passed is False

    def test_response_with_secret_auto_blocked(self) -> None:
        """Content policy: response with secret → auto_blocked=True."""
        client = _make_client()

        # Inject a Stripe live key to trigger auto-block
        stripe_key = "sk_live_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef012345678901"
        response_text = f"Use this key: {stripe_key}"

        with patch("spanforge.sdk.validate.sf_audit", _audit_mock(), create=True):
            result = client.validate(response_text, confidence_score=0.90)

        assert result.auto_blocked is True
        secret_violations = [v for v in result.violations if v.type == "secret"]
        assert len(secret_violations) >= 1
        assert result.passed is False


# ---------------------------------------------------------------------------
# TestMultiPassCorrection
# ---------------------------------------------------------------------------


class TestMultiPassCorrection:
    """Enforcement mechanism 4 — multi-pass correction."""

    def test_one_pass_resolves_violation_passes(self) -> None:
        """Correction: one pass resolves violations → correction_passes=1, passed=True."""
        client = _make_client()

        call_count = 0

        def correction_fn(text: str, violations: list[Violation]) -> str:
            nonlocal call_count
            call_count += 1
            # Return safe text that has no PII or secrets
            return "Safe corrected response with no violations."

        pii_entity = MagicMock()
        pii_entity.type = "PERSON"
        pii_result_with_pii = MagicMock()
        pii_result_with_pii.detected = True
        pii_result_with_pii.entities = [pii_entity]

        pii_result_clean = MagicMock()
        pii_result_clean.detected = False
        pii_result_clean.entities = []

        mock_pii = MagicMock()
        mock_pii.scan_text.side_effect = [pii_result_with_pii, pii_result_clean]

        with (
            patch("spanforge.sdk.sf_audit", _audit_mock(), create=True),
            patch("spanforge.sdk.sf_pii", mock_pii, create=True),
        ):
            result = client.validate(
                "John Smith is the contact.",
                confidence_score=0.90,
                correction_fn=correction_fn,
            )

        assert result.correction_passes == 1
        assert result.passed is True
        assert result.corrected_response == "Safe corrected response with no violations."

    def test_still_failing_after_two_passes(self) -> None:
        """Correction: still failing after 2 passes → passed=False, correction_passes=2."""
        client = _make_client()

        call_count = 0

        def correction_fn(text: str, violations: list[Violation]) -> str:
            nonlocal call_count
            call_count += 1
            # Always returns text with a confidence violation embedded (confidence re-runs)
            return f"Still problematic text pass {call_count}"

        with patch("spanforge.sdk.sf_audit", _audit_mock(), create=True):
            # Start with a confidence violation that correction can't fix
            result = client.validate(
                "Uncertain answer.",
                confidence_score=0.30,
                confidence_threshold=0.70,
                correction_fn=correction_fn,
                max_correction_passes=2,
            )

        # confidence violations are not in the pii/secret category re-run,
        # so they remain after correction
        assert result.passed is False
        assert result.correction_passes == 2


# ---------------------------------------------------------------------------
# TestAuditChain
# ---------------------------------------------------------------------------


class TestAuditChain:
    """Every validate() call must emit a signed audit record."""

    def test_every_call_emits_signed_record(self) -> None:
        """Audit: validate() appends a signed record on each call."""
        client = _make_client()
        mock_audit = _audit_mock()

        with patch("spanforge.sdk.sf_audit", mock_audit, create=True):
            result = client.validate("Hello world.", confidence_score=0.90)

        mock_audit.append.assert_called_once()
        call_args = mock_audit.append.call_args
        payload, schema_key = call_args[0]
        assert schema_key == "spanforge.validate.v1"
        assert "response_hash" in payload
        assert "passed" in payload
        assert isinstance(payload["response_hash"], str)
        assert len(payload["response_hash"]) == 64  # SHA-256 hex

    def test_audit_record_contains_violation_types(self) -> None:
        """Audit: violation types are recorded in the audit payload."""
        client = _make_client()
        mock_audit = _audit_mock()

        with patch("spanforge.sdk.sf_audit", mock_audit, create=True):
            result = client.validate(
                "not-json",
                schema={"type": "object"},
                confidence_score=0.30,
                confidence_threshold=0.70,
            )

        payload = mock_audit.append.call_args[0][0]
        assert "schema" in payload["violation_types"]
        assert "confidence" in payload["violation_types"]

    def test_hmac_signature_stored_in_result(self) -> None:
        """Audit: hmac_signature and audit_id are populated from sf_audit result."""
        client = _make_client()

        with patch("spanforge.sdk.sf_audit", _audit_mock(), create=True):
            result = client.validate("Valid response.", confidence_score=0.80)

        assert result.hmac_signature == "hmac-test-sig"
        assert result.audit_id == "audit-rec-001"

    def test_audit_failure_does_not_raise(self) -> None:
        """Audit: sf_audit failure is swallowed — validate() still returns a result."""
        client = _make_client()
        mock_audit = MagicMock()
        mock_audit.append.side_effect = RuntimeError("audit down")

        with patch("spanforge.sdk.sf_audit", mock_audit, create=True):
            result = client.validate("Some text.", confidence_score=0.90)

        # Should return gracefully with empty signature
        assert isinstance(result, ValidationResult)
        assert result.hmac_signature == ""
        assert result.audit_id == ""

    def test_correction_emits_cost_event(self) -> None:
        """Audit: correction pass emits a validation_correction cost event."""
        client = _make_client()
        mock_audit = _audit_mock()

        pii_entity = MagicMock()
        pii_entity.type = "LOCATION"
        pii_result = MagicMock()
        pii_result.detected = True
        pii_result.entities = [pii_entity]

        clean_result = MagicMock()
        clean_result.detected = False
        clean_result.entities = []

        mock_pii = MagicMock()
        mock_pii.scan_text.side_effect = [pii_result, clean_result]

        with (
            patch("spanforge.sdk.sf_audit", mock_audit, create=True),
            patch("spanforge.sdk.sf_pii", mock_pii, create=True),
        ):
            result = client.validate(
                "Visit London for the event.",
                confidence_score=0.90,
                correction_fn=lambda t, v: "Visit the venue for the event.",
            )

        # Should have 2 append calls: one correction cost event + one main record
        assert mock_audit.append.call_count == 2
        schema_keys = [call[0][1] for call in mock_audit.append.call_args_list]
        assert "spanforge.validate.correction.v1" in schema_keys
        assert "spanforge.validate.v1" in schema_keys


# ---------------------------------------------------------------------------
# TestNeverRaises
# ---------------------------------------------------------------------------


class TestNeverRaises:
    """validate() must never raise on content violations."""

    def test_validate_never_raises_on_content_violations(self) -> None:
        """validate() always returns ValidationResult — never raises."""
        client = _make_client()

        with patch("spanforge.sdk.sf_audit", _audit_mock(), create=True):
            # Multiple simultaneous violations: bad schema + low confidence
            result = client.validate(
                "not-json",
                schema={"type": "object", "required": ["x"]},
                confidence_score=0.10,
                confidence_threshold=0.80,
            )

        assert isinstance(result, ValidationResult)
        assert result.passed is False
        assert len(result.violations) >= 2

    def test_validate_returns_result_with_broken_correction_fn(self) -> None:
        """validate() does not raise when correction_fn raises internally."""
        client = _make_client()

        def broken_fn(text: str, violations: list[Violation]) -> str:
            msg = "correction exploded"
            raise RuntimeError(msg)

        with patch("spanforge.sdk.sf_audit", _audit_mock(), create=True):
            result = client.validate(
                "not-json",
                schema={"type": "object"},
                confidence_score=0.90,
                correction_fn=broken_fn,
            )

        assert isinstance(result, ValidationResult)
        # No passes completed successfully
        assert result.correction_passes == 0


# ---------------------------------------------------------------------------
# TestGetStatus
# ---------------------------------------------------------------------------


class TestGetStatus:
    """ValidateStatusInfo accumulates counters correctly."""

    def test_status_increments_correctly(self) -> None:
        """get_status() reflects total_calls and total_passed accurately."""
        client = _make_client()

        with patch("spanforge.sdk.sf_audit", _audit_mock(), create=True):
            client.validate("Good response.", confidence_score=0.90)
            client.validate("Another response.", confidence_score=0.90)
            client.validate("Bad response.", confidence_score=0.20, confidence_threshold=0.70)

        status = client.get_status()
        assert status.service == "validate"
        assert status.total_calls == 3
        assert status.total_passed == 2
        assert status.total_violations_raised >= 1


# ---------------------------------------------------------------------------
# TestViolationDataclass
# ---------------------------------------------------------------------------


class TestViolationDataclass:
    """Violation dataclass correctness."""

    def test_invalid_severity_raises(self) -> None:
        """Violation rejects invalid severity values."""
        with pytest.raises(ValueError, match="severity"):
            Violation(type="schema", field="", message="bad", severity="unknown")

    def test_to_dict_round_trip(self) -> None:
        """Violation.to_dict() produces the expected keys."""
        v = Violation(type="pii", field="output", message="PII found", severity="high")
        d = v.to_dict()
        assert d == {
            "type": "pii",
            "field": "output",
            "message": "PII found",
            "severity": "high",
        }

    def test_validation_result_to_dict(self) -> None:
        """ValidationResult.to_dict() serialises all fields."""
        result = ValidationResult(
            passed=True,
            violations=[],
            corrected_response=None,
            correction_passes=0,
            hmac_signature="sig",
            audit_id="id",
            duration_ms=1.5,
            auto_blocked=False,
        )
        d = result.to_dict()
        assert d["passed"] is True
        assert d["violations"] == []
        assert d["hmac_signature"] == "sig"
        assert d["duration_ms"] == 1.5
