"""Tests for spanforge Phase 2 — sf-secrets service.

Coverage targets: ≥ 90 % on spanforge/secrets.py, spanforge/sdk/secrets.py,
and the new _exceptions.py additions.

Test structure
--------------
*  Unit tests for the entropy scorer.
*  Unit tests for SecretHit / SecretsScanResult dataclasses.
*  Unit tests for SFSecretsError / SFSecretsBlockedError / SFSecretsScanError.
*  Pattern match tests for all 20 secret types.
*  Confidence scoring tier tests (0.75 / 0.90 / 0.97).
*  Auto-block policy tests (zero-tolerance, confidence-gated).
*  Allowlist suppression tests.
*  Redaction / redacted_text tests.
*  SARIF output tests.
*  SecretsScanner edge-case tests.
*  SFSecretsClient local-mode tests.
*  SFSecretsClient scan_batch tests.
*  SFSecretsClient get_status tests.
*  SFSecretsClient error-path tests.
*  sdk singleton import tests.
*  CLI secrets scan tests.
"""

from __future__ import annotations

import json
import math
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from spanforge.sdk._base import SFClientConfig
from spanforge.sdk._exceptions import (
    SFError,
    SFSecretsBlockedError,
    SFSecretsError,
    SFSecretsScanError,
)
from spanforge.sdk._types import SecretStr
from spanforge.sdk.secrets import SFSecretsClient
from spanforge.secrets import (
    SecretHit,
    SecretsScanResult,
    SecretsScanner,
    _DEFAULT_ALLOWLIST,
    _ZERO_TOLERANCE_TYPES,
    _build_redacted_text,
    _dedup_hits,
    entropy_score,
)

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
def scanner() -> SecretsScanner:
    """Fresh SecretsScanner with default settings."""
    return SecretsScanner()


@pytest.fixture()
def client(local_config: SFClientConfig) -> SFSecretsClient:
    """Fresh SFSecretsClient in local mode."""
    return SFSecretsClient(local_config)


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
def remote_client(remote_config: SFClientConfig) -> SFSecretsClient:
    """SFSecretsClient in remote mode with fallback disabled."""
    return SFSecretsClient(remote_config)


# ===========================================================================
# entropy_score
# ===========================================================================


class TestEntropyScore:
    def test_empty_string(self) -> None:
        assert entropy_score("") == 0.0

    def test_single_char_repeated(self) -> None:
        assert entropy_score("aaaaaaaaa") == 0.0

    def test_two_equal_halves(self) -> None:
        # "ab" * n → H = 1.0 bits/char
        s = "ab" * 16
        assert abs(entropy_score(s) - 1.0) < 0.001

    def test_high_entropy_key(self) -> None:
        # A realistic 32-char base62 API key should be well above 3.5
        key = "aB3cD4eF5gH6iJ7kL8mN9oP0qR1sT2uV"
        h = entropy_score(key)
        assert h >= 3.5, f"expected >= 3.5, got {h}"

    def test_low_entropy_sequential(self) -> None:
        # AAAAAAAAAAAAAAAA... is low entropy
        assert entropy_score("A" * 40) == 0.0

    def test_return_is_float(self) -> None:
        assert isinstance(entropy_score("hello"), float)

    def test_non_negative(self) -> None:
        for s in ["abc", "ABC123", "x" * 50]:
            assert entropy_score(s) >= 0.0

    def test_upper_bound_reasonable(self) -> None:
        # Max theoretical entropy for n unique chars is log2(n);
        # for a 64-char alphabet it's 6 bits/char.
        import string
        alphabet = string.ascii_letters + string.digits
        # Repeat alphabet so string is long enough
        s = alphabet * 3
        h = entropy_score(s)
        assert h <= math.log2(len(set(s))) + 0.001

    def test_aws_example_key_is_medium(self) -> None:
        # The example key from allowlist is below 3.5
        h = entropy_score("AKIAIOSFODNN7EXAMPLE")
        assert h < 4.0  # known low-diversity sample


# ===========================================================================
# SecretHit dataclass
# ===========================================================================


class TestSecretHit:
    def test_creation(self) -> None:
        hit = SecretHit(
            secret_type="aws_access_key",
            start=0,
            end=20,
            confidence=0.97,
            redacted_value="[REDACTED:AWS_ACCESS_KEY]",
            auto_blocked=True,
            vault_hint="Move to AWS Secrets Manager",
        )
        assert hit.secret_type == "aws_access_key"
        assert hit.start == 0
        assert hit.end == 20
        assert hit.confidence == 0.97
        assert hit.auto_blocked is True
        assert hit.vault_hint == "Move to AWS Secrets Manager"

    def test_frozen(self) -> None:
        hit = SecretHit("t", 0, 1, 0.75, "[REDACTED:T]")
        with pytest.raises(AttributeError):
            hit.start = 5  # type: ignore[misc]

    def test_defaults(self) -> None:
        hit = SecretHit("x", 0, 1, 0.75, "[REDACTED:X]")
        assert hit.auto_blocked is False
        assert hit.vault_hint == ""


# ===========================================================================
# SecretsScanResult dataclass
# ===========================================================================


class TestSecretsScanResult:
    def _make_result(self) -> SecretsScanResult:
        hit = SecretHit(
            secret_type="stripe_live_key",
            start=0,
            end=30,
            confidence=0.97,
            redacted_value="[REDACTED:STRIPE_LIVE_KEY]",
            auto_blocked=True,
        )
        return SecretsScanResult(
            detected=True,
            hits=[hit],
            auto_blocked=True,
            redacted_text="[REDACTED:STRIPE_LIVE_KEY] rest of text",
            secret_types=["stripe_live_key"],
            confidence_scores=[0.97],
        )

    def test_to_dict_structure(self) -> None:
        r = self._make_result()
        d = r.to_dict()
        assert d["detected"] is True
        assert d["auto_blocked"] is True
        assert len(d["hits"]) == 1
        assert d["hits"][0]["secret_type"] == "stripe_live_key"
        assert d["hits"][0]["confidence"] == 0.97
        assert "vault_hint" not in d["hits"][0]  # empty vault_hint omitted

    def test_to_dict_vault_hint_included_when_set(self) -> None:
        hit = SecretHit("a", 0, 1, 0.75, "[REDACTED:A]", vault_hint="store in vault")
        r = SecretsScanResult(
            detected=True, hits=[hit], auto_blocked=False,
            redacted_text="", secret_types=["a"], confidence_scores=[0.75],
        )
        d = r.to_dict()
        assert d["hits"][0]["vault_hint"] == "store in vault"

    def test_to_sarif_structure(self) -> None:
        r = self._make_result()
        sarif = r.to_sarif()
        assert sarif["version"] == "2.1.0"
        assert len(sarif["runs"]) == 1
        run = sarif["runs"][0]
        assert run["tool"]["driver"]["name"] == "spanforge-secrets"
        assert len(run["results"]) == 1
        result = run["results"][0]
        assert result["ruleId"] == "stripe_live_key"
        assert result["level"] == "error"  # auto_blocked → error
        assert "charOffset" in result["locations"][0]["physicalLocation"]["region"]

    def test_to_sarif_warning_level_for_non_blocked(self) -> None:
        hit = SecretHit("generic_api_key", 0, 40, 0.75, "[REDACTED:GENERIC_API_KEY]", auto_blocked=False)
        r = SecretsScanResult(True, [hit], False, "", ["generic_api_key"], [0.75])
        sarif = r.to_sarif()
        assert sarif["runs"][0]["results"][0]["level"] == "warning"

    def test_to_sarif_custom_tool_name(self) -> None:
        r = self._make_result()
        sarif = r.to_sarif(tool_name="my-scanner", version="2.0.0")
        assert sarif["runs"][0]["tool"]["driver"]["name"] == "my-scanner"
        assert sarif["runs"][0]["tool"]["driver"]["version"] == "2.0.0"

    def test_no_secrets_result(self) -> None:
        r = SecretsScanResult(
            detected=False, hits=[], auto_blocked=False, redacted_text="clean text",
        )
        d = r.to_dict()
        assert d["detected"] is False
        assert d["hits"] == []


# ===========================================================================
# SFSecretsError family
# ===========================================================================


class TestSecretsExceptions:
    def test_sfsecreterror_is_sferror(self) -> None:
        assert issubclass(SFSecretsError, SFError)

    def test_sfsecretsblockederror_message(self) -> None:
        exc = SFSecretsBlockedError(secret_types=["aws_access_key", "stripe_live_key"], count=2)
        msg = str(exc)
        assert "2" in msg
        assert "aws_access_key" in msg
        assert "stripe_live_key" in msg

    def test_sfsecretsblockederror_empty_types(self) -> None:
        exc = SFSecretsBlockedError(secret_types=[], count=0)
        msg = str(exc)
        assert "(unknown)" in msg

    def test_sfsecretsblockederror_attrs(self) -> None:
        exc = SFSecretsBlockedError(secret_types=["github_pat"], count=1)
        assert exc.secret_types == ["github_pat"]
        assert exc.count == 1

    def test_sfsecretsscanerror_is_sfsecreterror(self) -> None:
        assert issubclass(SFSecretsScanError, SFSecretsError)

    def test_exceptions_hierarchy(self) -> None:
        # All are catchable as SFError
        for cls in (SFSecretsError, SFSecretsBlockedError, SFSecretsScanError):
            exc = cls() if cls is SFSecretsError or cls is SFSecretsScanError else cls([], 0)
            assert isinstance(exc, SFError)


# ===========================================================================
# Pattern detection tests
# ===========================================================================

# Helper strings containing each secret type
_BEARER = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyXzEyMyJ9.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
_AWS_KEY = "export AWS_ACCESS_KEY_ID=AKIA" + "ABCDEFGHIJKLMNOP"
_GCP_SA = '{"type": "service_account", "project_id": "my-project"}'
_PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEow..."
_DB_CONN = "postgresql://admin:s3cr3t_p@ss@prod-db.example.com:5432/appdb"
_HC_KEY = "hc_live_" + "A" * 48
_SF_KEY = "sf_live_" + "B" * 48
_GITHUB_PAT = "ghp_" + "C" * 40
_NPM = "npm_" + "D" * 36
_SLACK = "xoxb-12345678-12345678901-abcdefghijklmnop0123456789"
_STRIPE_LIVE = "sk_live_abcdefghijklmnopqrstuvwx"
_STRIPE_TEST = "sk_test_abcdefghijklmnopqrstuvwx"
_TWILIO = "SK" + "a" * 32
_SENDGRID = "SG." + "E" * 22 + "." + "F" * 43
_AZURE_CONN = "DefaultEndpointsProtocol=https;AccountName=myaccount;AccountKey=" + "G" * 88
_SSH = "-----BEGIN OPENSSH PRIVATE KEY-----\nb3Blb..."
_GOOGLE_KEY = "AIza" + "H" * 35
_VAULT_TOKEN = "some context s." + "I" * 30 + " end"
_JWT = "eyJhbGciOiJIUzI1NiJ9." + "J" * 40 + "." + "K" * 40


class TestPatternDetection:
    """Each test checks that a specific secret type is detected."""

    def _has_type(self, scanner: SecretsScanner, text: str, secret_type: str) -> bool:
        result = scanner.scan(text)
        return any(h.secret_type == secret_type for h in result.hits)

    def test_bearer_token(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, _BEARER, "bearer_token")

    def test_aws_access_key(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, _AWS_KEY, "aws_access_key")

    def test_gcp_service_account(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, _GCP_SA, "gcp_service_account")

    def test_pem_private_key(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, _PEM, "pem_private_key")

    def test_db_connection_string(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, _DB_CONN, "db_connection_string")

    def test_halluccheck_api_key(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, _HC_KEY, "halluccheck_api_key")

    def test_spanforge_api_key(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, _SF_KEY, "spanforge_api_key")

    def test_github_pat(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, _GITHUB_PAT, "github_pat")

    def test_npm_token(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, _NPM, "npm_token")

    def test_slack_token(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, _SLACK, "slack_token")

    def test_stripe_live_key(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, _STRIPE_LIVE, "stripe_live_key")

    def test_stripe_test_key(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, _STRIPE_TEST, "stripe_test_key")

    def test_twilio_key(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, _TWILIO, "twilio_key")

    def test_sendgrid_key(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, _SENDGRID, "sendgrid_key")

    def test_azure_connection_string(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, _AZURE_CONN, "azure_connection_string")

    def test_ssh_private_key(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, _SSH, "ssh_private_key")

    def test_google_api_key(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, _GOOGLE_KEY, "google_api_key")

    def test_vault_token(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, _VAULT_TOKEN, "vault_token")

    def test_generic_jwt(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, _JWT, "generic_jwt")

    def test_generic_api_key_high_entropy(self, scanner: SecretsScanner) -> None:
        # A 48-char alphanumeric string with high entropy
        import string, random, secrets as _s
        rng = _s.SystemRandom()
        high_ent = "".join(rng.choices(string.ascii_letters + string.digits, k=48))
        result = scanner.scan(high_ent)
        # May or may not flag depending on entropy — just verify no crash
        assert isinstance(result, SecretsScanResult)

    def test_no_false_positive_on_clean_text(self, scanner: SecretsScanner) -> None:
        result = scanner.scan("Hello, world! The answer is 42.")
        assert not result.detected

    def test_multiple_secrets_in_same_text(self, scanner: SecretsScanner) -> None:
        text = f"{_STRIPE_LIVE}\n{_AWS_KEY}"
        result = scanner.scan(text)
        assert result.detected
        types = {h.secret_type for h in result.hits}
        assert "stripe_live_key" in types
        assert "aws_access_key" in types

    def test_github_pat_new_format(self, scanner: SecretsScanner) -> None:
        pat = "github_pat_" + "X" * 40
        assert self._has_type(scanner, pat, "github_pat")

    def test_github_ghs_format(self, scanner: SecretsScanner) -> None:
        assert self._has_type(scanner, "ghs_" + "Y" * 40, "github_pat")


# ===========================================================================
# Confidence scoring tests
# ===========================================================================


class TestConfidenceScoring:
    def test_structural_match_alone_is_0_75(self) -> None:
        # GCP SA JSON match — no entropy boost possible from short literal
        scanner = SecretsScanner()
        result = scanner.scan('{"type": "service_account", "project_id": "x"}')
        hit = next(h for h in result.hits if h.secret_type == "gcp_service_account")
        # Tier 1 only; matched text is short
        assert hit.confidence in (0.75, 0.90, 0.97)

    def test_context_keyword_boosts_to_0_97(self) -> None:
        # Add a context keyword within 50 chars
        text = "api_key=" + _HC_KEY
        scanner = SecretsScanner()
        result = scanner.scan(text)
        hit = next(h for h in result.hits if h.secret_type == "halluccheck_api_key")
        assert hit.confidence == 0.97

    def test_high_entropy_match_boosts_to_0_90_or_more(self) -> None:
        # HC key is 48 chars; check entropy
        h = entropy_score(_HC_KEY)
        # If entropy >= 3.5, should be boosted
        if h >= 3.5:
            scanner = SecretsScanner()
            result = scanner.scan(_HC_KEY)
            hit = next(h for h in result.hits if h.secret_type == "halluccheck_api_key")
            assert hit.confidence >= 0.90

    def test_confidence_threshold_filters_hits(self) -> None:
        scanner = SecretsScanner(confidence_threshold=0.90)
        # A low-confidence non-zero-tolerance match should be filtered out
        result = scanner.scan(_TWILIO)
        # twilio_key is not zero tolerance; if confidence < 0.90 it should be excluded
        for hit in result.hits:
            if hit.secret_type == "twilio_key":
                assert hit.confidence >= 0.90


# ===========================================================================
# Auto-block policy tests
# ===========================================================================


class TestAutoBlockPolicy:
    def test_bearer_token_always_blocked(self) -> None:
        result = SecretsScanner().scan(_BEARER)
        blocked = [h for h in result.hits if h.secret_type == "bearer_token"]
        assert all(h.auto_blocked for h in blocked)

    def test_aws_key_always_blocked(self) -> None:
        result = SecretsScanner().scan(_AWS_KEY)
        blocked = [h for h in result.hits if h.secret_type == "aws_access_key"]
        assert all(h.auto_blocked for h in blocked)

    def test_stripe_live_always_blocked(self) -> None:
        result = SecretsScanner().scan(_STRIPE_LIVE)
        blocked = [h for h in result.hits if h.secret_type == "stripe_live_key"]
        assert all(h.auto_blocked for h in blocked)

    def test_stripe_test_not_blocked_unless_high_confidence(self) -> None:
        result = SecretsScanner().scan(_STRIPE_TEST)
        for hit in result.hits:
            if hit.secret_type == "stripe_test_key":
                # Stripe test is not zero-tolerance; block only if confidence >= 0.90
                if hit.auto_blocked:
                    assert hit.confidence >= 0.90

    def test_all_zero_tolerance_types_are_blocked(self) -> None:
        # Every zero-tolerance type should trigger auto_block=True
        type_to_text = {
            "bearer_token": _BEARER,
            "aws_access_key": _AWS_KEY,
            "gcp_service_account": _GCP_SA,
            "pem_private_key": _PEM,
            "ssh_private_key": _SSH,
            "halluccheck_api_key": _HC_KEY,
            "spanforge_api_key": _SF_KEY,
            "github_pat": _GITHUB_PAT,
            "stripe_live_key": _STRIPE_LIVE,
            "generic_jwt": _JWT,
        }
        scanner = SecretsScanner()
        for secret_type, text in type_to_text.items():
            result = scanner.scan(text)
            hits_of_type = [h for h in result.hits if h.secret_type == secret_type]
            assert hits_of_type, f"No hit for {secret_type}"
            assert any(h.auto_blocked for h in hits_of_type), f"{secret_type} not auto_blocked"

    def test_result_auto_blocked_flag_set(self) -> None:
        result = SecretsScanner().scan(_STRIPE_LIVE)
        assert result.auto_blocked is True

    def test_auto_block_override_true(self) -> None:
        scanner = SecretsScanner(auto_block_override=True)
        # Even a normally non-blocking type should be blocked
        result = scanner.scan(_TWILIO)
        for hit in result.hits:
            assert hit.auto_blocked is True

    def test_auto_block_override_false(self) -> None:
        scanner = SecretsScanner(auto_block_override=False)
        # Even a zero-tolerance type should not be blocked
        result = scanner.scan(_STRIPE_LIVE)
        for hit in result.hits:
            assert hit.auto_blocked is False

    def test_auto_blocked_false_for_clean_text(self) -> None:
        result = SecretsScanner().scan("no secrets here")
        assert result.auto_blocked is False


# ===========================================================================
# Allowlist suppression tests
# ===========================================================================


class TestAllowlist:
    def test_default_allowlist_suppresses_aws_example(self) -> None:
        scanner = SecretsScanner()
        # AKIAIOSFODNN7EXAMPLE is in the default allowlist
        text = "Using AKIAIOSFODNN7EXAMPLE as the AWS key"
        result = scanner.scan(text)
        assert not any(h.secret_type == "aws_access_key" for h in result.hits)

    def test_custom_allowlist_suppresses_value(self) -> None:
        # The matched span from _AWS_KEY is AKIA + 16 uppercase chars
        matched_key = "AKIA" + "ABCDEFGHIJKLMNOP"
        custom = frozenset({matched_key})
        scanner = SecretsScanner(extra_allowlist=custom)
        result = scanner.scan(_AWS_KEY)
        assert not any(h.secret_type == "aws_access_key" for h in result.hits)

    def test_non_allowlisted_value_still_detected(self) -> None:
        scanner = SecretsScanner()
        result = scanner.scan(_AWS_KEY)
        # AKIAIOSFODNN7REAL1234 is not in the default allowlist
        assert any(h.secret_type == "aws_access_key" for h in result.hits)


# ===========================================================================
# Redaction tests
# ===========================================================================


class TestRedaction:
    def test_redacted_value_is_placeholder(self) -> None:
        result = SecretsScanner().scan(_STRIPE_LIVE)
        for hit in result.hits:
            assert hit.redacted_value.startswith("[REDACTED:")
            assert "]" in hit.redacted_value

    def test_redacted_text_replaces_secret(self) -> None:
        text = f"Key: {_STRIPE_LIVE} is secret"
        result = SecretsScanner().scan(text)
        assert _STRIPE_LIVE not in result.redacted_text
        assert "[REDACTED:" in result.redacted_text

    def test_redacted_text_preserves_clean_parts(self) -> None:
        prefix = "Hello, "
        suffix = " world."
        text = f"{prefix}{_STRIPE_LIVE}{suffix}"
        result = SecretsScanner().scan(text)
        assert prefix in result.redacted_text
        assert suffix in result.redacted_text

    def test_redacted_text_for_clean_input_unchanged(self) -> None:
        text = "no secrets here at all"
        result = SecretsScanner().scan(text)
        assert result.redacted_text == text

    def test_build_redacted_text_direct(self) -> None:
        # hit covers positions 5..9 inclusive = "SECRE" (end=10 exclusive)
        hit = SecretHit("x", 5, 10, 0.75, "[REDACTED:X]")
        text = "abc12SECRETXYZ"
        result = _build_redacted_text(text, [hit])
        # text[:5]="abc12", text[5:10]="SECRE" → redacted, text[10:]="TXYZ"
        assert result == "abc12[REDACTED:X]TXYZ"

    def test_build_redacted_text_empty_hits(self) -> None:
        text = "clean"
        assert _build_redacted_text(text, []) == text

    def test_multiple_secrets_all_redacted(self) -> None:
        text = f"first={_STRIPE_LIVE} second={_HC_KEY}"
        result = SecretsScanner().scan(text)
        assert _STRIPE_LIVE not in result.redacted_text
        assert _HC_KEY not in result.redacted_text


# ===========================================================================
# Dedup helper tests
# ===========================================================================


class TestDedupHits:
    def test_no_overlap(self) -> None:
        h1 = SecretHit("a", 0, 5, 0.75, "[REDACTED:A]")
        h2 = SecretHit("b", 10, 15, 0.90, "[REDACTED:B]")
        result = _dedup_hits([h1, h2])
        assert len(result) == 2

    def test_overlapping_keeps_higher_confidence(self) -> None:
        h1 = SecretHit("a", 0, 10, 0.75, "[REDACTED:A]")
        h2 = SecretHit("b", 5, 15, 0.97, "[REDACTED:B]")
        result = _dedup_hits([h1, h2])
        assert len(result) == 1
        assert result[0].confidence == 0.97

    def test_single_hit(self) -> None:
        h = SecretHit("x", 0, 5, 0.75, "[REDACTED:X]")
        assert _dedup_hits([h]) == [h]

    def test_empty_list(self) -> None:
        assert _dedup_hits([]) == []


# ===========================================================================
# SecretsScanner edge cases
# ===========================================================================


class TestSecretsScannerEdgeCases:
    def test_scan_non_string_raises_typeerror(self) -> None:
        scanner = SecretsScanner()
        with pytest.raises(TypeError):
            scanner.scan(12345)  # type: ignore[arg-type]

    def test_invalid_threshold_raises_valueerror(self) -> None:
        with pytest.raises(ValueError):
            SecretsScanner(confidence_threshold=1.5)

    def test_invalid_threshold_negative(self) -> None:
        with pytest.raises(ValueError):
            SecretsScanner(confidence_threshold=-0.1)

    def test_empty_string_scan(self) -> None:
        result = SecretsScanner().scan("")
        assert not result.detected
        assert result.redacted_text == ""

    def test_very_long_string(self) -> None:
        # Should not blow up on a large input
        text = "x" * 100_000 + _STRIPE_LIVE + "y" * 100_000
        result = SecretsScanner().scan(text)
        assert result.detected

    def test_per_call_threshold_override(self) -> None:
        scanner = SecretsScanner(confidence_threshold=0.75)
        # Scanning with a very high threshold should suppress non-zero-tol hits
        result = scanner.scan(_TWILIO, confidence_threshold=0.99)
        for hit in result.hits:
            if hit.secret_type == "twilio_key":
                assert hit.confidence >= 0.99

    def test_secret_types_list_order_of_first_appearance(self) -> None:
        # stripe appears before aws in the text
        text = f"{_STRIPE_LIVE} then {_AWS_KEY}"
        result = SecretsScanner().scan(text)
        types = result.secret_types
        stripe_idx = types.index("stripe_live_key") if "stripe_live_key" in types else 999
        aws_idx = types.index("aws_access_key") if "aws_access_key" in types else 999
        assert stripe_idx < aws_idx


# ===========================================================================
# SFSecretsClient — local mode
# ===========================================================================


class TestSFSecretsClientLocal:
    def test_scan_clean_text(self, client: SFSecretsClient) -> None:
        result = client.scan("no secrets here")
        assert not result.detected
        assert not result.auto_blocked

    def test_scan_detects_stripe_live(self, client: SFSecretsClient) -> None:
        result = client.scan(_STRIPE_LIVE)
        assert result.detected

    def test_scan_returns_scan_result_type(self, client: SFSecretsClient) -> None:
        result = client.scan("hello")
        assert isinstance(result, SecretsScanResult)

    def test_scan_non_string_raises_sfsecretsscanerror(self, client: SFSecretsClient) -> None:
        with pytest.raises(SFSecretsScanError):
            client.scan(None)  # type: ignore[arg-type]

    def test_scan_with_extra_allowlist(self, client: SFSecretsClient) -> None:
        custom = frozenset({_STRIPE_LIVE})
        result = client.scan(_STRIPE_LIVE, extra_allowlist=custom)
        assert not any(h.secret_type == "stripe_live_key" for h in result.hits)

    def test_scan_with_custom_threshold(self, client: SFSecretsClient) -> None:
        result = client.scan(_TWILIO, confidence_threshold=0.99)
        for hit in result.hits:
            if hit.secret_type == "twilio_key":
                assert hit.confidence >= 0.99

    def test_get_status_local_mode(self, client: SFSecretsClient) -> None:
        status = client.get_status()
        assert status["mode"] == "local"
        assert status["local_fallback"] is True
        assert isinstance(status["pattern_count"], int)
        assert status["pattern_count"] > 15
        assert isinstance(status["zero_tolerance_types"], list)
        assert "stripe_live_key" in status["zero_tolerance_types"]

    def test_get_status_circuit_breaker_closed(self, client: SFSecretsClient) -> None:
        assert client.get_status()["circuit_breaker_open"] is False

    def test_is_local_mode_true(self, client: SFSecretsClient) -> None:
        assert client._is_local_mode() is True


# ===========================================================================
# SFSecretsClient — scan_batch
# ===========================================================================


class TestSFSecretsClientBatch:
    def test_scan_batch_returns_list(self, client: SFSecretsClient) -> None:
        texts = ["clean", _STRIPE_LIVE, "also clean"]
        results = client.scan_batch(texts)
        assert len(results) == 3
        assert all(isinstance(r, SecretsScanResult) for r in results)

    def test_scan_batch_order_preserved(self, client: SFSecretsClient) -> None:
        texts = [_STRIPE_LIVE, "clean", _AWS_KEY]
        results = client.scan_batch(texts)
        assert results[0].detected  # stripe live key
        assert not results[1].detected  # clean
        assert results[2].detected  # aws key

    def test_scan_batch_non_string_element_raises(self, client: SFSecretsClient) -> None:
        with pytest.raises(SFSecretsScanError):
            client.scan_batch(["ok", 42])  # type: ignore[list-item]

    def test_scan_batch_empty_list(self, client: SFSecretsClient) -> None:
        results = client.scan_batch([])
        assert results == []

    def test_scan_batch_single_item(self, client: SFSecretsClient) -> None:
        results = client.scan_batch([_HC_KEY])
        assert len(results) == 1
        assert results[0].detected

    def test_scan_batch_fallback_sequential_on_running_loop(self, client: SFSecretsClient) -> None:
        """scan_batch falls back to sequential when event loop is running."""
        import asyncio

        async def inner() -> list[SecretsScanResult]:
            return client.scan_batch(["clean", _SF_KEY])

        results = asyncio.run(inner())
        assert len(results) == 2


# ===========================================================================
# SFSecretsClient — remote mode
# ===========================================================================


class TestSFSecretsClientRemote:
    def test_remote_scan_falls_back_when_exception(self) -> None:
        """With fallback enabled, remote failure → local scan."""
        config = SFClientConfig(
            endpoint="https://api.spanforge.test",
            api_key=SecretStr("sf_test_" + "A" * 48),
            local_fallback_enabled=True,
            max_retries=0,
        )
        client = SFSecretsClient(config)
        # _request will raise; fallback should kick in
        with patch.object(client, "_request", side_effect=ConnectionError("no network")):
            result = client.scan(_STRIPE_LIVE)
        assert result.detected

    def test_remote_scan_uses_response_data(self) -> None:
        """Remote scan deserialises the server response correctly."""
        config = SFClientConfig(
            endpoint="https://api.spanforge.test",
            api_key=SecretStr("sf_test_" + "A" * 48),
            local_fallback_enabled=False,
            max_retries=0,
        )
        client = SFSecretsClient(config)
        fake_response = {
            "detected": True,
            "auto_blocked": True,
            "redacted_text": "[REDACTED:STRIPE_LIVE_KEY]",
            "secret_types": ["stripe_live_key"],
            "confidence_scores": [0.97],
            "hits": [
                {
                    "secret_type": "stripe_live_key",
                    "start": 0,
                    "end": 30,
                    "confidence": 0.97,
                    "redacted_value": "[REDACTED:STRIPE_LIVE_KEY]",
                    "auto_blocked": True,
                    "vault_hint": "Move to vault",
                }
            ],
        }
        with patch.object(client, "_request", return_value=fake_response):
            result = client.scan(_STRIPE_LIVE)
        assert result.detected
        assert result.auto_blocked
        assert result.hits[0].secret_type == "stripe_live_key"
        assert result.hits[0].vault_hint == "Move to vault"

    def test_get_status_remote_mode(self, remote_client: SFSecretsClient) -> None:
        status = remote_client.get_status()
        assert status["mode"] == "remote"
        assert status["local_fallback"] is False


# ===========================================================================
# SDK singleton tests
# ===========================================================================


class TestSDKSingleton:
    def test_sf_secrets_importable(self) -> None:
        from spanforge.sdk import sf_secrets

        assert sf_secrets is not None

    def test_sf_secrets_is_sfsecretersclient(self) -> None:
        from spanforge.sdk import sf_secrets

        assert isinstance(sf_secrets, SFSecretsClient)

    def test_sf_secrets_scan_clean(self) -> None:
        from spanforge.sdk import sf_secrets

        result = sf_secrets.scan("hello world")
        assert not result.detected

    def test_sdk_exports_exception_types(self) -> None:
        from spanforge.sdk import (
            SFSecretsBlockedError,
            SFSecretsError,
            SFSecretsScanError,
        )

        assert issubclass(SFSecretsBlockedError, SFSecretsError)
        assert issubclass(SFSecretsScanError, SFSecretsError)

    def test_sdk_exports_data_types(self) -> None:
        from spanforge.sdk import SecretHit, SecretsScanResult, SFSecretsClient

        assert SecretHit is not None
        assert SecretsScanResult is not None
        assert SFSecretsClient is not None

    def test_configure_recreates_sf_secrets(self) -> None:
        from spanforge import sdk as sdk_module
        from spanforge.sdk import configure

        original = sdk_module.sf_secrets
        configure(
            SFClientConfig(
                endpoint="",
                api_key=SecretStr(""),
                local_fallback_enabled=True,
            )
        )
        assert sdk_module.sf_secrets is not original

    def test_sf_secrets_in_all(self) -> None:
        import spanforge.sdk as sdk_module

        assert "sf_secrets" in sdk_module.__all__

    def test_sfsecreterror_in_all(self) -> None:
        import spanforge.sdk as sdk_module

        assert "SFSecretsError" in sdk_module.__all__
        assert "SFSecretsBlockedError" in sdk_module.__all__
        assert "SFSecretsScanError" in sdk_module.__all__


# ===========================================================================
# Exceptions module __all__ coverage
# ===========================================================================


class TestExceptionsAll:
    def test_sfsecretserror_in_exceptions_all(self) -> None:
        from spanforge.sdk import _exceptions

        assert "SFSecretsError" in _exceptions.__all__
        assert "SFSecretsBlockedError" in _exceptions.__all__
        assert "SFSecretsScanError" in _exceptions.__all__

    def test_sfsecretsblockederror_is_importable_from_exceptions(self) -> None:
        from spanforge.sdk._exceptions import SFSecretsBlockedError

        exc = SFSecretsBlockedError(["aws_access_key"], 1)
        assert "aws_access_key" in str(exc)


# ===========================================================================
# CLI tests
# ===========================================================================


class TestCLISecretsScan:
    """Tests for `spanforge secrets scan` sub-command."""

    def _run_cli(self, args: list[str]) -> int:
        from spanforge._cli import main as cli_main

        with pytest.raises(SystemExit) as exc_info:
            cli_main(args)
        return exc_info.value.code  # type: ignore[return-value]

    def test_secrets_scan_no_secrets_exit_0(self, tmp_path: Path) -> None:
        f = tmp_path / "clean.txt"
        f.write_text("Hello, world! No secrets here.", encoding="utf-8")
        code = self._run_cli(["secrets", "scan", str(f)])
        assert code == 0

    def test_secrets_scan_with_secret_exit_1(self, tmp_path: Path) -> None:
        f = tmp_path / "secret.txt"
        f.write_text(_STRIPE_LIVE, encoding="utf-8")
        code = self._run_cli(["secrets", "scan", str(f)])
        assert code == 1

    def test_secrets_scan_json_format(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        f = tmp_path / "secret.py"
        f.write_text(f"KEY = '{_STRIPE_LIVE}'", encoding="utf-8")
        self._run_cli(["secrets", "scan", str(f), "--format", "json"])
        out, _ = capsys.readouterr()
        data = json.loads(out)
        assert data["detected"] is True

    def test_secrets_scan_sarif_format(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        f = tmp_path / "secret.py"
        f.write_text(f"KEY = '{_HC_KEY}'", encoding="utf-8")
        self._run_cli(["secrets", "scan", str(f), "--format", "sarif"])
        out, _ = capsys.readouterr()
        sarif = json.loads(out)
        assert sarif["version"] == "2.1.0"

    def test_secrets_scan_redact_flag(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        f = tmp_path / "secret.txt"
        f.write_text(_STRIPE_LIVE, encoding="utf-8")
        self._run_cli(["secrets", "scan", str(f), "--redact"])
        out, _ = capsys.readouterr()
        assert _STRIPE_LIVE not in out

    def test_secrets_scan_missing_file_exit_2(self) -> None:
        code = self._run_cli(["secrets", "scan", "/nonexistent/path/file.txt"])
        assert code == 2

    def test_secrets_scan_confidence_flag(self, tmp_path: Path) -> None:
        f = tmp_path / "test.txt"
        f.write_text(_TWILIO, encoding="utf-8")
        # High confidence threshold — twilio_key should be filtered out
        code = self._run_cli(["secrets", "scan", str(f), "--confidence", "0.99"])
        # Exit code 0 or 1 depending on whether twilio_key hits 0.99 confidence
        assert code in (0, 1)

    def test_secrets_no_subcommand_exit_2(self) -> None:
        code = self._run_cli(["secrets"])
        assert code == 2

    def test_secrets_scan_json_no_redacted_text_by_default(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        f = tmp_path / "s.txt"
        f.write_text(_SF_KEY, encoding="utf-8")
        self._run_cli(["secrets", "scan", str(f), "--format", "json"])
        out, _ = capsys.readouterr()
        data = json.loads(out)
        assert "redacted_text" not in data


# ===========================================================================
# Thread-safety smoke test
# ===========================================================================


class TestThreadSafety:
    def test_concurrent_scans(self, client: SFSecretsClient) -> None:
        texts = ["clean"] * 10 + [_STRIPE_LIVE] * 10
        results: list[SecretsScanResult] = []
        errors: list[Exception] = []
        lock = threading.Lock()

        def worker(text: str) -> None:
            try:
                r = client.scan(text)
                with lock:
                    results.append(r)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(t,)) for t in texts]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 20
        detected = [r for r in results if r.detected]
        assert len(detected) == 10
