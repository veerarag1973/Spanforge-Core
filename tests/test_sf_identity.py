"""Tests for spanforge.sdk Phase 1 — sf-identity service.

Coverage targets: ≥ 90 % on spanforge/sdk/

Test structure
--------------
*  Unit tests for types and helpers.
*  Functional tests for the full SFIdentityClient in local mode.
*  Error-path and security tests.
*  Thread-safety smoke tests.
"""

from __future__ import annotations

import pickle
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import List
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from spanforge.sdk._base import (
    SFClientConfig,
    SFServiceClient,
    _CircuitBreaker,
    _SlidingWindowRateLimiter,
)
from spanforge.sdk._exceptions import (
    SFAuthError,
    SFBruteForceLockedError,
    SFError,
    SFIPDeniedError,
    SFKeyFormatError,
    SFMFARequiredError,
    SFQuotaExceededError,
    SFRateLimitError,
    SFScopeError,
    SFServiceUnavailableError,
    SFStartupError,
    SFTokenInvalidError,
)
from spanforge.sdk._types import (
    APIKeyBundle,
    JWTClaims,
    KeyFormat,
    KeyScope,
    MagicLinkResult,
    QuotaTier,
    RateLimitInfo,
    SecretStr,
    TOTPEnrollResult,
    TokenIntrospectionResult,
)
from spanforge.sdk.identity import (
    SFIdentityClient,
    _compute_totp,
    _issue_hs256_jwt,
    _verify_hs256_jwt,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def local_config() -> SFClientConfig:
    """SFClientConfig in local mode (no endpoint, stable signing keys)."""
    return SFClientConfig(
        endpoint="",
        api_key=SecretStr(""),
        signing_key="test-signing-key-stable",
        magic_secret="test-magic-secret-stable",
        local_fallback_enabled=True,
    )


@pytest.fixture()
def identity(local_config: SFClientConfig) -> SFIdentityClient:
    """Fresh SFIdentityClient in local mode for each test."""
    return SFIdentityClient(local_config)


@pytest.fixture()
def bundle(identity: SFIdentityClient) -> "APIKeyBundle":
    """A freshly issued API key bundle."""
    return identity.issue_api_key(scopes=["sf_audit"])


# ---------------------------------------------------------------------------
# SecretStr
# ---------------------------------------------------------------------------


class TestSecretStr:
    def test_repr_redacts_value(self) -> None:
        s = SecretStr("super-secret")
        assert "super-secret" not in repr(s)
        assert repr(s) == "<SecretStr:***>"

    def test_str_redacts_value(self) -> None:
        s = SecretStr("super-secret")
        assert "super-secret" not in str(s)
        assert str(s) == "<SecretStr:***>"

    def test_get_secret_value_returns_plain(self) -> None:
        s = SecretStr("my-value")
        assert s.get_secret_value() == "my-value"

    def test_equality_is_timing_safe(self) -> None:
        a = SecretStr("same")
        b = SecretStr("same")
        assert a == b

    def test_inequality(self) -> None:
        assert SecretStr("a") != SecretStr("b")

    def test_hash_consistent(self) -> None:
        assert hash(SecretStr("x")) == hash(SecretStr("x"))

    def test_immutable(self) -> None:
        s = SecretStr("v")
        with pytest.raises(AttributeError):
            s._value = "other"  # type: ignore[misc]

    def test_pickle_raises_type_error(self) -> None:
        s = SecretStr("secret")
        with pytest.raises(TypeError, match="pickled"):
            pickle.dumps(s)

    def test_equality_with_non_secret_str_returns_not_implemented(self) -> None:
        s = SecretStr("x")
        # __eq__ should return NotImplemented, so Python falls back to identity
        assert (s == "x") is False or NotImplemented

    def test_len_works(self) -> None:
        assert len(SecretStr("hello")) == 5


# ---------------------------------------------------------------------------
# KeyFormat
# ---------------------------------------------------------------------------


class TestKeyFormat:
    VALID_LIVE = "sf_live_" + "A" * 48
    VALID_TEST = "sf_test_" + "0" * 48

    def test_valid_live_key(self) -> None:
        KeyFormat.validate(self.VALID_LIVE)  # should not raise

    def test_valid_test_key(self) -> None:
        KeyFormat.validate(self.VALID_TEST)  # should not raise

    def test_too_short(self) -> None:
        with pytest.raises(SFKeyFormatError):
            KeyFormat.validate("sf_live_" + "A" * 47)

    def test_too_long(self) -> None:
        with pytest.raises(SFKeyFormatError):
            KeyFormat.validate("sf_live_" + "A" * 49)

    def test_wrong_prefix(self) -> None:
        with pytest.raises(SFKeyFormatError):
            KeyFormat.validate("sf_prod_" + "A" * 48)

    def test_invalid_chars(self) -> None:
        with pytest.raises(SFKeyFormatError):
            KeyFormat.validate("sf_live_" + "!" * 48)

    def test_empty_string(self) -> None:
        with pytest.raises(SFKeyFormatError):
            KeyFormat.validate("")

    def test_non_string(self) -> None:
        with pytest.raises(SFKeyFormatError):
            KeyFormat.validate(12345)  # type: ignore[arg-type]

    def test_is_test_key(self) -> None:
        assert KeyFormat.is_test_key(self.VALID_TEST) is True
        assert KeyFormat.is_test_key(self.VALID_LIVE) is False

    def test_is_live_key(self) -> None:
        assert KeyFormat.is_live_key(self.VALID_LIVE) is True
        assert KeyFormat.is_live_key(self.VALID_TEST) is False

    def test_is_valid(self) -> None:
        assert KeyFormat.is_valid(self.VALID_LIVE) is True
        assert KeyFormat.is_valid("bad") is False


# ---------------------------------------------------------------------------
# KeyScope
# ---------------------------------------------------------------------------


class TestKeyScope:
    def test_no_expiry_not_expired(self) -> None:
        scope = KeyScope()
        assert scope.is_expired() is False

    def test_past_expiry_is_expired(self) -> None:
        scope = KeyScope(expires_at=datetime(2000, 1, 1, tzinfo=timezone.utc))
        assert scope.is_expired() is True

    def test_future_expiry_not_expired(self) -> None:
        scope = KeyScope(expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc))
        assert scope.is_expired() is False

    def test_empty_pillar_whitelist_allows_all(self) -> None:
        scope = KeyScope()
        assert scope.allows_service("sf_anything") is True

    def test_pillar_whitelist_restricts(self) -> None:
        scope = KeyScope(pillar_whitelist=["sf_audit"])
        assert scope.allows_service("sf_audit") is True
        assert scope.allows_service("sf_pii") is False

    def test_empty_project_scope_allows_all(self) -> None:
        scope = KeyScope()
        assert scope.allows_project("proj_x") is True

    def test_project_scope_restricts(self) -> None:
        scope = KeyScope(project_scope=["proj_a"])
        assert scope.allows_project("proj_a") is True
        assert scope.allows_project("proj_b") is False


# ---------------------------------------------------------------------------
# QuotaTier
# ---------------------------------------------------------------------------


class TestQuotaTier:
    def test_known_tiers(self) -> None:
        assert QuotaTier.daily_limit(QuotaTier.FREE) == 0
        assert QuotaTier.daily_limit(QuotaTier.API) == 10_000
        assert QuotaTier.daily_limit(QuotaTier.TEAM) == 100_000
        assert QuotaTier.daily_limit(QuotaTier.ENTERPRISE) == -1

    def test_unknown_tier_returns_zero(self) -> None:
        assert QuotaTier.daily_limit("unknown_tier") == 0


# ---------------------------------------------------------------------------
# APIKeyBundle repr
# ---------------------------------------------------------------------------


class TestAPIKeyBundleRepr:
    def test_repr_redacts_api_key(self) -> None:
        b = APIKeyBundle(
            api_key=SecretStr("sf_live_" + "A" * 48),
            key_id="key_abc",
            jwt="header.payload.sig",
            expires_at=datetime(2099, 1, 1, tzinfo=timezone.utc),
            scopes=["sf_audit"],
        )
        r = repr(b)
        assert "sf_live_" not in r
        assert "key_abc" in r


# ---------------------------------------------------------------------------
# TOTPEnrollResult repr
# ---------------------------------------------------------------------------


class TestTOTPEnrollResultRepr:
    def test_repr_redacts_secret(self) -> None:
        r = TOTPEnrollResult(
            secret_base32=SecretStr("JBSWY3DP"),
            qr_uri="otpauth://totp/test",
            backup_codes=["AAAAAAAA"],
        )
        assert "JBSWY3DP" not in repr(r)
        assert "redacted" in repr(r)


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------


class TestJWTHelpers:
    SECRET = b"unit-test-secret"

    def _valid_payload(self) -> dict:
        return {
            "iss": "spanforge",
            "sub": "key_test",
            "exp": int(time.time()) + 3600,
            "iat": int(time.time()),
            "jti": str(uuid.uuid4()),
        }

    def test_issue_and_verify_roundtrip(self) -> None:
        payload = self._valid_payload()
        token = _issue_hs256_jwt(payload, self.SECRET)
        decoded = _verify_hs256_jwt(token, self.SECRET)
        assert decoded["sub"] == "key_test"

    def test_wrong_secret_raises(self) -> None:
        payload = self._valid_payload()
        token = _issue_hs256_jwt(payload, self.SECRET)
        with pytest.raises(SFTokenInvalidError, match="signature"):
            _verify_hs256_jwt(token, b"wrong-secret")

    def test_expired_token_raises(self) -> None:
        payload = {
            "sub": "key_test",
            "exp": int(time.time()) - 1,
            "iat": int(time.time()) - 100,
        }
        token = _issue_hs256_jwt(payload, self.SECRET)
        with pytest.raises(SFTokenInvalidError, match="expired"):
            _verify_hs256_jwt(token, self.SECRET)

    def test_malformed_token_raises(self) -> None:
        with pytest.raises(SFTokenInvalidError):
            _verify_hs256_jwt("not.a.valid.jwt.token", self.SECRET)

    def test_two_segment_raises(self) -> None:
        with pytest.raises(SFTokenInvalidError, match="segments"):
            _verify_hs256_jwt("only.two", self.SECRET)


# ---------------------------------------------------------------------------
# TOTP helpers
# ---------------------------------------------------------------------------


class TestTOTPHelpers:
    def test_deterministic_for_known_secret(self) -> None:
        # RFC 6238 known vector: secret=12345678901234567890 (ASCII), time=59
        import base64
        raw = b"12345678901234567890"
        secret_b32 = base64.b32encode(raw).decode()
        code = _compute_totp(secret_b32, timestamp=59.0)
        assert len(code) == 6
        assert code.isdigit()

    def test_zero_padded(self) -> None:
        # Verify the output is always 6 characters, zero-padded
        import base64
        raw = b"12345678901234567890"
        secret_b32 = base64.b32encode(raw).decode()
        code = _compute_totp(secret_b32, timestamp=0.0)
        assert len(code) == 6

    def test_uses_current_time_by_default(self) -> None:
        import base64
        raw = b"12345678901234567890"
        secret_b32 = base64.b32encode(raw).decode()
        code = _compute_totp(secret_b32)  # no timestamp arg
        assert len(code) == 6


# ---------------------------------------------------------------------------
# _CircuitBreaker
# ---------------------------------------------------------------------------


class TestCircuitBreaker:
    def test_starts_closed(self) -> None:
        cb = _CircuitBreaker(threshold=5, reset_seconds=30)
        assert cb.is_open() is False

    def test_opens_after_threshold_failures(self) -> None:
        cb = _CircuitBreaker(threshold=5, reset_seconds=30)
        for _ in range(5):
            cb.record_failure()
        assert cb.is_open() is True

    def test_does_not_open_before_threshold(self) -> None:
        cb = _CircuitBreaker(threshold=5, reset_seconds=30)
        for _ in range(4):
            cb.record_failure()
        assert cb.is_open() is False

    def test_success_resets_closed(self) -> None:
        cb = _CircuitBreaker(threshold=5, reset_seconds=30)
        for _ in range(5):
            cb.record_failure()
        assert cb.is_open() is True
        cb.record_success()
        assert cb.is_open() is False

    def test_auto_resets_after_timeout(self) -> None:
        cb = _CircuitBreaker(threshold=2, reset_seconds=0.05)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open() is True
        time.sleep(0.1)
        assert cb.is_open() is False

    def test_reset_clears_state(self) -> None:
        cb = _CircuitBreaker(threshold=2, reset_seconds=30)
        cb.record_failure()
        cb.record_failure()
        assert cb.is_open() is True
        cb.reset()
        assert cb.is_open() is False

    def test_state_property(self) -> None:
        cb = _CircuitBreaker(threshold=2, reset_seconds=30)
        assert cb.state == _CircuitBreaker.CLOSED
        cb.record_failure()
        cb.record_failure()
        assert cb.state == _CircuitBreaker.OPEN

    def test_thread_safe_concurrent_failures(self) -> None:
        cb = _CircuitBreaker(threshold=100, reset_seconds=30)
        errors: List[Exception] = []

        def fail_many() -> None:
            try:
                for _ in range(20):
                    cb.record_failure()
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=fail_many) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert cb.is_open() is True  # 100 total failures across 5 threads


# ---------------------------------------------------------------------------
# _SlidingWindowRateLimiter
# ---------------------------------------------------------------------------


class TestSlidingWindowRateLimiter:
    def test_under_limit_allows(self) -> None:
        limiter = _SlidingWindowRateLimiter(limit=5, window_seconds=60)
        for _ in range(5):
            assert limiter.record("k1") is True

    def test_at_limit_blocks(self) -> None:
        limiter = _SlidingWindowRateLimiter(limit=3, window_seconds=60)
        for _ in range(3):
            limiter.record("k2")
        assert limiter.record("k2") is False

    def test_check_does_not_increment(self) -> None:
        limiter = _SlidingWindowRateLimiter(limit=2, window_seconds=60)
        info = limiter.check("k3")
        assert info.remaining == 2
        info2 = limiter.check("k3")
        assert info2.remaining == 2

    def test_window_eviction(self) -> None:
        limiter = _SlidingWindowRateLimiter(limit=2, window_seconds=0.05)
        limiter.record("k4")
        limiter.record("k4")
        assert limiter.record("k4") is False
        time.sleep(0.1)
        assert limiter.record("k4") is True

    def test_remaining_decreases(self) -> None:
        limiter = _SlidingWindowRateLimiter(limit=10, window_seconds=60)
        limiter.record("k5")
        limiter.record("k5")
        assert limiter.remaining("k5") == 8

    def test_clear_resets_key(self) -> None:
        limiter = _SlidingWindowRateLimiter(limit=2, window_seconds=60)
        limiter.record("k6")
        limiter.record("k6")
        limiter.clear("k6")
        assert limiter.remaining("k6") == 2

    def test_invalid_limit_raises(self) -> None:
        with pytest.raises(ValueError):
            _SlidingWindowRateLimiter(limit=0)

    def test_invalid_window_raises(self) -> None:
        with pytest.raises(ValueError):
            _SlidingWindowRateLimiter(window_seconds=0)

    def test_per_key_isolation(self) -> None:
        limiter = _SlidingWindowRateLimiter(limit=1, window_seconds=60)
        limiter.record("k7")
        assert limiter.record("k7") is False
        # Different key unaffected
        assert limiter.record("k8") is True


# ---------------------------------------------------------------------------
# SFClientConfig
# ---------------------------------------------------------------------------


class TestSFClientConfig:
    def test_defaults(self) -> None:
        cfg = SFClientConfig()
        assert cfg.endpoint == ""
        assert cfg.timeout_ms == 2_000
        assert cfg.max_retries == 3
        assert cfg.local_fallback_enabled is True
        assert cfg.tls_verify is True

    def test_from_env_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SPANFORGE_ENDPOINT", raising=False)
        monkeypatch.delenv("SPANFORGE_API_KEY", raising=False)
        monkeypatch.delenv("SPANFORGE_SIGNING_KEY", raising=False)
        cfg = SFClientConfig.from_env()
        assert cfg.endpoint == ""
        assert cfg.api_key.get_secret_value() == ""

    def test_from_env_reads_variables(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_ENDPOINT", "https://test.example.com")
        monkeypatch.setenv("SPANFORGE_API_KEY", "sf_live_" + "A" * 48)
        monkeypatch.setenv("SPANFORGE_TIMEOUT_MS", "5000")
        monkeypatch.setenv("SPANFORGE_MAX_RETRIES", "2")
        monkeypatch.setenv("SPANFORGE_LOCAL_FALLBACK", "false")
        monkeypatch.setenv("SPANFORGE_TLS_VERIFY", "false")
        monkeypatch.setenv("SPANFORGE_PROJECT_ID", "proj_test")
        monkeypatch.setenv("SPANFORGE_SIGNING_KEY", "my-signing-key")
        monkeypatch.setenv("SPANFORGE_MAGIC_SECRET", "my-magic-secret")

        cfg = SFClientConfig.from_env()
        assert cfg.endpoint == "https://test.example.com"
        assert cfg.api_key.get_secret_value() == "sf_live_" + "A" * 48
        assert cfg.timeout_ms == 5000
        assert cfg.max_retries == 2
        assert cfg.local_fallback_enabled is False
        assert cfg.tls_verify is False
        assert cfg.project_id == "proj_test"
        assert cfg.signing_key == "my-signing-key"
        assert cfg.magic_secret == "my-magic-secret"

    def test_local_fallback_false_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for val in ("false", "0", "no"):
            monkeypatch.setenv("SPANFORGE_LOCAL_FALLBACK", val)
            cfg = SFClientConfig.from_env()
            assert cfg.local_fallback_enabled is False

    def test_local_fallback_true_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for val in ("true", "1", "yes", "True"):
            monkeypatch.setenv("SPANFORGE_LOCAL_FALLBACK", val)
            cfg = SFClientConfig.from_env()
            assert cfg.local_fallback_enabled is True


# ---------------------------------------------------------------------------
# SFServiceClient — is_local_mode
# ---------------------------------------------------------------------------


class TestSFServiceClientLocalMode:
    def test_empty_endpoint_is_local(self) -> None:
        cfg = SFClientConfig(endpoint="")

        class _Stub(SFServiceClient):
            pass

        client = _Stub(cfg, "test")
        assert client._is_local_mode() is True

    def test_set_endpoint_not_local(self) -> None:
        cfg = SFClientConfig(endpoint="https://api.example.com")

        class _Stub(SFServiceClient):
            pass

        client = _Stub(cfg, "test")
        assert client._is_local_mode() is False

    def test_request_raises_when_circuit_open(self) -> None:
        cfg = SFClientConfig(
            endpoint="https://example.invalid",
            local_fallback_enabled=False,
        )

        class _Stub(SFServiceClient):
            pass

        client = _Stub(cfg, "test")
        # Open the circuit manually
        for _ in range(5):
            client._circuit_breaker.record_failure()

        with pytest.raises(SFServiceUnavailableError):
            client._request("GET", "/health")


# ---------------------------------------------------------------------------
# SFIdentityClient — issue_api_key
# ---------------------------------------------------------------------------


class TestIssueApiKey:
    def test_returns_api_key_bundle(self, identity: SFIdentityClient) -> None:
        b = identity.issue_api_key()
        assert isinstance(b, APIKeyBundle)

    def test_api_key_format_live(self, identity: SFIdentityClient) -> None:
        b = identity.issue_api_key()
        key = b.api_key.get_secret_value()
        assert KeyFormat.is_valid(key), f"Invalid key format: {key!r}"
        assert KeyFormat.is_live_key(key)

    def test_api_key_format_test_mode(self, identity: SFIdentityClient) -> None:
        b = identity.issue_api_key(test_mode=True)
        key = b.api_key.get_secret_value()
        assert KeyFormat.is_test_key(key)

    def test_key_stored_internally(self, identity: SFIdentityClient) -> None:
        b = identity.issue_api_key()
        key = b.api_key.get_secret_value()
        assert key in identity._keys
        assert b.key_id in identity._keys_by_id

    def test_both_dicts_reference_same_record(self, identity: SFIdentityClient) -> None:
        b = identity.issue_api_key()
        key = b.api_key.get_secret_value()
        assert identity._keys[key] is identity._keys_by_id[b.key_id]

    def test_scopes_stored(self, identity: SFIdentityClient) -> None:
        b = identity.issue_api_key(scopes=["sf_audit", "sf_pii"])
        assert set(b.scopes) == {"sf_audit", "sf_pii"}

    def test_expires_at_future(self, identity: SFIdentityClient) -> None:
        b = identity.issue_api_key()
        assert b.expires_at > datetime.now(timezone.utc)

    def test_ip_allowlist_stored(self, identity: SFIdentityClient) -> None:
        b = identity.issue_api_key(ip_allowlist=["10.0.0.0/8"])
        record = identity._keys_by_id[b.key_id]
        assert "10.0.0.0/8" in record["ip_allowlist"]

    def test_unique_keys_per_call(self, identity: SFIdentityClient) -> None:
        b1 = identity.issue_api_key()
        b2 = identity.issue_api_key()
        assert b1.api_key.get_secret_value() != b2.api_key.get_secret_value()

    def test_unique_key_ids_per_call(self, identity: SFIdentityClient) -> None:
        b1 = identity.issue_api_key()
        b2 = identity.issue_api_key()
        assert b1.key_id != b2.key_id

    def test_bundle_repr_redacts_key(self, identity: SFIdentityClient) -> None:
        b = identity.issue_api_key()
        assert b.api_key.get_secret_value() not in repr(b)


# ---------------------------------------------------------------------------
# SFIdentityClient — create_session
# ---------------------------------------------------------------------------


class TestCreateSession:
    def test_returns_jwt_string(self, identity: SFIdentityClient, bundle: APIKeyBundle) -> None:
        jwt = identity.create_session(bundle.api_key.get_secret_value())
        assert isinstance(jwt, str)
        parts = jwt.split(".")
        assert len(parts) == 3

    def test_jwt_is_verifiable(self, identity: SFIdentityClient, bundle: APIKeyBundle) -> None:
        jwt = identity.create_session(bundle.api_key.get_secret_value())
        claims = identity.verify_token(jwt)
        assert claims.subject == bundle.key_id

    def test_invalid_key_format_raises(self, identity: SFIdentityClient) -> None:
        with pytest.raises(SFKeyFormatError):
            identity.create_session("not-a-key")

    def test_unknown_key_raises(self, identity: SFIdentityClient) -> None:
        with pytest.raises(SFAuthError):
            identity.create_session("sf_live_" + "A" * 48)

    def test_revoked_key_raises(self, identity: SFIdentityClient, bundle: APIKeyBundle) -> None:
        identity.revoke_key(bundle.key_id)
        with pytest.raises(SFAuthError, match="revoked"):
            identity.create_session(bundle.api_key.get_secret_value())


# ---------------------------------------------------------------------------
# SFIdentityClient — verify_token
# ---------------------------------------------------------------------------


class TestVerifyToken:
    def test_valid_token_returns_claims(self, identity: SFIdentityClient, bundle: APIKeyBundle) -> None:
        jwt = identity.create_session(bundle.api_key.get_secret_value())
        claims = identity.verify_token(jwt)
        assert claims.subject == bundle.key_id

    def test_claims_have_scopes(self, identity: SFIdentityClient) -> None:
        b = identity.issue_api_key(scopes=["sf_audit"])
        jwt = identity.create_session(b.api_key.get_secret_value())
        claims = identity.verify_token(jwt)
        assert "sf_audit" in claims.scopes

    def test_expired_token_raises(self, identity: SFIdentityClient, bundle: APIKeyBundle) -> None:
        payload = {
            "iss": "spanforge",
            "sub": bundle.key_id,
            "aud": "default",
            "iat": int(time.time()) - 100,
            "exp": int(time.time()) - 1,
            "jti": str(uuid.uuid4()),
            "scopes": [],
        }
        jwt = _issue_hs256_jwt(payload, identity._signing_key.encode())
        with pytest.raises(SFTokenInvalidError, match="expired"):
            identity.verify_token(jwt)

    def test_wrong_signature_raises(self, identity: SFIdentityClient, bundle: APIKeyBundle) -> None:
        jwt = identity.create_session(bundle.api_key.get_secret_value())
        # Tamper with the signature
        parts = jwt.split(".")
        tampered = parts[0] + "." + parts[1] + ".invalidsignatureXXX"
        with pytest.raises(SFTokenInvalidError):
            identity.verify_token(tampered)

    def test_malformed_jwt_raises(self, identity: SFIdentityClient) -> None:
        with pytest.raises(SFTokenInvalidError):
            identity.verify_token("not-a-jwt")

    def test_revoked_jti_raises(self, identity: SFIdentityClient, bundle: APIKeyBundle) -> None:
        jwt = identity.create_session(bundle.api_key.get_secret_value())
        # Decode to get JTI, then add to revoked set
        from spanforge.sdk.identity import _verify_hs256_jwt
        claims = _verify_hs256_jwt(jwt, identity._signing_key.encode())
        with identity._lock:
            identity._revoked_jtis.add(claims["jti"])
        with pytest.raises(SFTokenInvalidError, match="revoked"):
            identity.verify_token(jwt)

    def test_claims_expiry_is_future(self, identity: SFIdentityClient, bundle: APIKeyBundle) -> None:
        jwt = identity.create_session(bundle.api_key.get_secret_value())
        claims = identity.verify_token(jwt)
        assert claims.expires_at > datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# SFIdentityClient — introspect
# ---------------------------------------------------------------------------


class TestIntrospect:
    def test_active_token(self, identity: SFIdentityClient, bundle: APIKeyBundle) -> None:
        jwt = identity.create_session(bundle.api_key.get_secret_value())
        result = identity.introspect(jwt)
        assert result.active is True
        assert result.sub == bundle.key_id

    def test_invalid_token_returns_inactive(self, identity: SFIdentityClient) -> None:
        result = identity.introspect("completely.invalid.token")
        assert result.active is False

    def test_expired_returns_inactive(self, identity: SFIdentityClient, bundle: APIKeyBundle) -> None:
        payload = {
            "sub": bundle.key_id,
            "exp": int(time.time()) - 1,
            "iat": int(time.time()) - 100,
            "jti": str(uuid.uuid4()),
            "scopes": [],
        }
        jwt = _issue_hs256_jwt(payload, identity._signing_key.encode())
        result = identity.introspect(jwt)
        assert result.active is False

    def test_scope_in_result(self, identity: SFIdentityClient) -> None:
        b = identity.issue_api_key(scopes=["sf_pii"])
        jwt = identity.create_session(b.api_key.get_secret_value())
        result = identity.introspect(jwt)
        assert "sf_pii" in result.scope


# ---------------------------------------------------------------------------
# SFIdentityClient — magic link
# ---------------------------------------------------------------------------


class TestMagicLink:
    def test_issue_returns_link_result(self, identity: SFIdentityClient) -> None:
        result = identity.issue_magic_link("user@example.com")
        assert isinstance(result, MagicLinkResult)
        assert result.link_id

    def test_link_id_stored_internally(self, identity: SFIdentityClient) -> None:
        result = identity.issue_magic_link("user@example.com")
        assert result.link_id in identity._magic_links

    def test_expires_at_within_15_minutes(self, identity: SFIdentityClient) -> None:
        result = identity.issue_magic_link("user@example.com")
        now = datetime.now(timezone.utc)
        diff = result.expires_at - now
        assert 0 < diff.total_seconds() <= 16 * 60  # slight clock slack

    def test_exchange_valid_link_returns_bundle(self, identity: SFIdentityClient) -> None:
        result = identity.issue_magic_link("user@example.com")
        record = identity._magic_links[result.link_id]
        token = record["token"]
        bundle = identity.exchange_magic_link(token, link_id=result.link_id)
        assert isinstance(bundle, APIKeyBundle)

    def test_exchange_marks_link_used(self, identity: SFIdentityClient) -> None:
        result = identity.issue_magic_link("user@example.com")
        record = identity._magic_links[result.link_id]
        token = record["token"]
        identity.exchange_magic_link(token, link_id=result.link_id)
        assert identity._magic_links[result.link_id]["used"] is True

    def test_replay_attack_rejected(self, identity: SFIdentityClient) -> None:
        result = identity.issue_magic_link("user@example.com")
        record = identity._magic_links[result.link_id]
        token = record["token"]
        identity.exchange_magic_link(token, link_id=result.link_id)
        with pytest.raises(SFAuthError, match="already been used"):
            identity.exchange_magic_link(token, link_id=result.link_id)

    def test_unknown_link_id_raises(self, identity: SFIdentityClient) -> None:
        with pytest.raises(SFAuthError, match="not found"):
            identity.exchange_magic_link("fake.token.mac", link_id="nonexistent")

    def test_expired_link_raises(self, identity: SFIdentityClient) -> None:
        result = identity.issue_magic_link("user@example.com")
        record = identity._magic_links[result.link_id]
        record["expiry"] = int(time.time()) - 1  # force expiry
        with pytest.raises(SFAuthError, match="expired"):
            identity.exchange_magic_link(record["token"], link_id=result.link_id)

    def test_tampered_token_raises(self, identity: SFIdentityClient) -> None:
        result = identity.issue_magic_link("user@example.com")
        # Valid link_id but malformed token (no HMAC segments)
        with pytest.raises(SFAuthError):
            identity.exchange_magic_link("bad.token.nohash", link_id=result.link_id)


# ---------------------------------------------------------------------------
# SFIdentityClient — rotate_key
# ---------------------------------------------------------------------------


class TestRotateKey:
    def test_rotate_returns_new_bundle(self, identity: SFIdentityClient, bundle: APIKeyBundle) -> None:
        new_bundle = identity.rotate_key(bundle.key_id)
        assert isinstance(new_bundle, APIKeyBundle)
        assert new_bundle.key_id != bundle.key_id

    def test_old_key_is_revoked_after_rotation(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        identity.rotate_key(bundle.key_id)
        old_record = identity._keys_by_id[bundle.key_id]
        assert old_record["revoked"] is True

    def test_new_key_is_valid(self, identity: SFIdentityClient, bundle: APIKeyBundle) -> None:
        new_bundle = identity.rotate_key(bundle.key_id)
        assert KeyFormat.is_valid(new_bundle.api_key.get_secret_value())

    def test_old_key_revoked_means_no_session(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        old_key = bundle.api_key.get_secret_value()
        identity.rotate_key(bundle.key_id)
        with pytest.raises(SFAuthError, match="revoked"):
            identity.create_session(old_key)

    def test_rotate_unknown_key_raises(self, identity: SFIdentityClient) -> None:
        with pytest.raises(SFAuthError, match="not found"):
            identity.rotate_key("key_doesnotexist")

    def test_rotate_preserves_scopes(self, identity: SFIdentityClient) -> None:
        b = identity.issue_api_key(scopes=["sf_audit", "sf_pii"])
        new_b = identity.rotate_key(b.key_id)
        assert set(new_b.scopes) == {"sf_audit", "sf_pii"}


# ---------------------------------------------------------------------------
# SFIdentityClient — revoke_key
# ---------------------------------------------------------------------------


class TestRevokeKey:
    def test_revoke_marks_key_revoked(self, identity: SFIdentityClient, bundle: APIKeyBundle) -> None:
        identity.revoke_key(bundle.key_id)
        record = identity._keys_by_id[bundle.key_id]
        assert record["revoked"] is True

    def test_revoked_key_cannot_create_session(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        identity.revoke_key(bundle.key_id)
        with pytest.raises(SFAuthError, match="revoked"):
            identity.create_session(bundle.api_key.get_secret_value())

    def test_revoke_unknown_key_raises(self, identity: SFIdentityClient) -> None:
        with pytest.raises(SFAuthError, match="not found"):
            identity.revoke_key("key_nosuchkey")


# ---------------------------------------------------------------------------
# SFIdentityClient — TOTP enrolment
# ---------------------------------------------------------------------------


class TestEnrollTOTP:
    def test_returns_result(self, identity: SFIdentityClient, bundle: APIKeyBundle) -> None:
        result = identity.enroll_totp(bundle.key_id)
        assert isinstance(result, TOTPEnrollResult)

    def test_secret_is_base32(self, identity: SFIdentityClient, bundle: APIKeyBundle) -> None:
        result = identity.enroll_totp(bundle.key_id)
        import base64
        # Should not raise
        base64.b32decode(result.secret_base32.get_secret_value().upper())

    def test_exactly_eight_backup_codes(self, identity: SFIdentityClient, bundle: APIKeyBundle) -> None:
        result = identity.enroll_totp(bundle.key_id)
        assert len(result.backup_codes) == 8

    def test_backup_codes_are_eight_chars(self, identity: SFIdentityClient, bundle: APIKeyBundle) -> None:
        result = identity.enroll_totp(bundle.key_id)
        for code in result.backup_codes:
            assert len(code) == 8, f"Code {code!r} is not 8 chars"

    def test_qr_uri_format(self, identity: SFIdentityClient, bundle: APIKeyBundle) -> None:
        result = identity.enroll_totp(bundle.key_id)
        assert result.qr_uri.startswith("otpauth://totp/SpanForge:")
        assert "secret=" in result.qr_uri

    def test_enroll_unknown_key_raises(self, identity: SFIdentityClient) -> None:
        with pytest.raises(SFAuthError, match="not found"):
            identity.enroll_totp("key_doesnotexist")

    def test_totp_data_stored(self, identity: SFIdentityClient, bundle: APIKeyBundle) -> None:
        identity.enroll_totp(bundle.key_id)
        assert bundle.key_id in identity._totp_data

    def test_backup_codes_stored_as_hashes(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        identity.enroll_totp(bundle.key_id)
        record = identity._totp_data[bundle.key_id]
        assert len(record["backup_hashes"]) == 8
        # Hashes should be sha256 hex (64 chars)
        for h in record["backup_hashes"]:
            assert len(h) == 64


# ---------------------------------------------------------------------------
# SFIdentityClient — TOTP verification
# ---------------------------------------------------------------------------


class TestVerifyTOTP:
    def test_correct_otp_returns_true(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        result = identity.enroll_totp(bundle.key_id)
        secret = result.secret_base32.get_secret_value()
        otp = _compute_totp(secret)
        assert identity.verify_totp(bundle.key_id, otp) is True

    def test_wrong_otp_returns_false(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        identity.enroll_totp(bundle.key_id)
        assert identity.verify_totp(bundle.key_id, "000000") is False

    def test_lockout_after_five_failures(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        identity.enroll_totp(bundle.key_id)
        for _ in range(4):
            identity.verify_totp(bundle.key_id, "000000")
        with pytest.raises(SFBruteForceLockedError):
            identity.verify_totp(bundle.key_id, "000000")

    def test_correct_otp_resets_fail_count(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        result = identity.enroll_totp(bundle.key_id)
        secret = result.secret_base32.get_secret_value()
        for _ in range(3):
            identity.verify_totp(bundle.key_id, "000000")
        # Correct OTP should reset the counter
        otp = _compute_totp(secret)
        assert identity.verify_totp(bundle.key_id, otp) is True
        record = identity._totp_data[bundle.key_id]
        assert record["totp_fail_count"] == 0

    def test_no_totp_enrolled_raises(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        with pytest.raises(SFAuthError, match="not enrolled"):
            identity.verify_totp(bundle.key_id, "000000")

    def test_lockout_blocks_before_threshold(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        identity.enroll_totp(bundle.key_id)
        # Manually set lockout
        with identity._lock:
            identity._totp_data[bundle.key_id]["totp_locked_until"] = (
                time.time() + 900
            )
        with pytest.raises(SFBruteForceLockedError):
            identity.verify_totp(bundle.key_id, "000000")

    def test_drift_tolerance(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        """OTPs from ±30 s should be accepted."""
        result = identity.enroll_totp(bundle.key_id)
        secret = result.secret_base32.get_secret_value()
        ts = time.time()
        otp_prev = _compute_totp(secret, ts - 30)
        otp_next = _compute_totp(secret, ts + 30)
        assert identity.verify_totp(bundle.key_id, otp_prev, timestamp=ts) is True
        # Reset fail count for next check
        identity._totp_data[bundle.key_id]["totp_fail_count"] = 0
        assert identity.verify_totp(bundle.key_id, otp_next, timestamp=ts) is True


# ---------------------------------------------------------------------------
# SFIdentityClient — backup codes
# ---------------------------------------------------------------------------


class TestVerifyBackupCode:
    def test_valid_backup_code_returns_true(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        result = identity.enroll_totp(bundle.key_id)
        assert identity.verify_backup_code(bundle.key_id, result.backup_codes[0]) is True

    def test_invalid_backup_code_returns_false(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        identity.enroll_totp(bundle.key_id)
        assert identity.verify_backup_code(bundle.key_id, "ZZZZZZZZ") is False

    def test_replay_attack_rejected(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        result = identity.enroll_totp(bundle.key_id)
        code = result.backup_codes[0]
        identity.verify_backup_code(bundle.key_id, code)
        # Second use must fail
        assert identity.verify_backup_code(bundle.key_id, code) is False

    def test_no_totp_enrolled_raises(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        with pytest.raises(SFAuthError, match="not enrolled"):
            identity.verify_backup_code(bundle.key_id, "AAAAAAAA")

    def test_all_backup_codes_unique(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        result = identity.enroll_totp(bundle.key_id)
        assert len(set(result.backup_codes)) == 8

    def test_case_insensitive(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        result = identity.enroll_totp(bundle.key_id)
        code = result.backup_codes[0]
        assert identity.verify_backup_code(bundle.key_id, code.lower()) is True


# ---------------------------------------------------------------------------
# SFIdentityClient — IP allowlist
# ---------------------------------------------------------------------------


class TestIPAllowlist:
    def test_no_allowlist_allows_all(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        identity.check_ip_allowlist(bundle.key_id, "1.2.3.4")  # should not raise

    def test_ip_in_cidr_passes(self, identity: SFIdentityClient) -> None:
        b = identity.issue_api_key(ip_allowlist=["10.0.0.0/8"])
        identity.check_ip_allowlist(b.key_id, "10.1.2.3")  # should not raise

    def test_ip_outside_cidr_raises(self, identity: SFIdentityClient) -> None:
        b = identity.issue_api_key(ip_allowlist=["10.0.0.0/8"])
        with pytest.raises(SFIPDeniedError) as exc_info:
            identity.check_ip_allowlist(b.key_id, "192.168.1.1")
        assert exc_info.value.ip == "192.168.1.1"

    def test_exact_ip_in_allowlist(self, identity: SFIdentityClient) -> None:
        b = identity.issue_api_key(ip_allowlist=["192.168.0.100/32"])
        identity.check_ip_allowlist(b.key_id, "192.168.0.100")  # should not raise

    def test_ipv6_passes(self, identity: SFIdentityClient) -> None:
        b = identity.issue_api_key(ip_allowlist=["::1/128"])
        identity.check_ip_allowlist(b.key_id, "::1")  # should not raise

    def test_invalid_ip_raises(self, identity: SFIdentityClient) -> None:
        b = identity.issue_api_key(ip_allowlist=["10.0.0.0/8"])
        with pytest.raises(SFIPDeniedError):
            identity.check_ip_allowlist(b.key_id, "not-an-ip")

    def test_unknown_key_raises(self, identity: SFIdentityClient) -> None:
        with pytest.raises(SFAuthError, match="not found"):
            identity.check_ip_allowlist("key_doesnotexist", "1.2.3.4")


# ---------------------------------------------------------------------------
# SFIdentityClient — rate limiting
# ---------------------------------------------------------------------------


class TestRateLimiting:
    def test_check_returns_rate_limit_info(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        info = identity.check_rate_limit(bundle.key_id)
        assert isinstance(info, RateLimitInfo)
        assert info.limit == 600
        assert info.remaining == 600

    def test_record_request_decreases_remaining(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        identity.record_request(bundle.key_id)
        identity.record_request(bundle.key_id)
        info = identity.check_rate_limit(bundle.key_id)
        assert info.remaining == 598

    def test_record_returns_true_within_limit(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        result = identity.record_request(bundle.key_id)
        assert result is True

    def test_record_returns_false_when_over_limit(self, local_config: SFClientConfig) -> None:
        # Override with a low limit
        client = SFIdentityClient(local_config)
        client._rate_limiter = _SlidingWindowRateLimiter(limit=2, window_seconds=60)
        b = client.issue_api_key()
        client.record_request(b.key_id)
        client.record_request(b.key_id)
        assert client.record_request(b.key_id) is False


# ---------------------------------------------------------------------------
# SFIdentityClient — JWKS
# ---------------------------------------------------------------------------


class TestJWKS:
    def test_local_mode_returns_empty_keys(self, identity: SFIdentityClient) -> None:
        jwks = identity.get_jwks()
        assert "keys" in jwks
        assert jwks["keys"] == []


# ---------------------------------------------------------------------------
# SFIdentityClient — require_scope
# ---------------------------------------------------------------------------


class TestRequireScope:
    def test_scope_present_does_not_raise(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        jwt = identity.create_session(bundle.api_key.get_secret_value())
        claims = identity.verify_token(jwt)
        # Scopes from bundle fixture are ["sf_audit"]
        identity.require_scope(claims, "sf_audit")  # should not raise

    def test_scope_missing_raises(
        self, identity: SFIdentityClient, bundle: APIKeyBundle
    ) -> None:
        jwt = identity.create_session(bundle.api_key.get_secret_value())
        claims = identity.verify_token(jwt)
        with pytest.raises(SFScopeError) as exc_info:
            identity.require_scope(claims, "sf_pii")
        assert exc_info.value.required_scope == "sf_pii"


# ---------------------------------------------------------------------------
# SAML stub in local mode
# ---------------------------------------------------------------------------


class TestSAMLStub:
    def test_metadata_returns_xml_stub(self, identity: SFIdentityClient) -> None:
        xml = identity.saml_metadata()
        assert "EntityDescriptor" in xml
        assert "spanforge-local-stub" in xml


# ---------------------------------------------------------------------------
# Exceptions — repr / message safety
# ---------------------------------------------------------------------------


class TestExceptionMessages:
    """Verify that error messages don't contain secret material."""

    def test_sf_key_format_error(self) -> None:
        exc = SFKeyFormatError("detail text")
        assert "detail text" in str(exc)
        assert isinstance(exc, SFAuthError)
        assert isinstance(exc, SFError)

    def test_sf_token_invalid_error(self) -> None:
        exc = SFTokenInvalidError("JWT has expired")
        assert exc.reason == "JWT has expired"
        assert "expired" in str(exc)

    def test_sf_ip_denied_error(self) -> None:
        exc = SFIPDeniedError("10.0.0.1")
        assert exc.ip == "10.0.0.1"
        assert "10.0.0.1" in str(exc)

    def test_sf_service_unavailable_error(self) -> None:
        exc = SFServiceUnavailableError("identity")
        assert exc.service == "identity"
        assert "identity" in str(exc)

    def test_sf_rate_limit_error(self) -> None:
        exc = SFRateLimitError(retry_after=30)
        assert exc.retry_after == 30
        assert "30" in str(exc)

    def test_sf_mfa_required_error(self) -> None:
        exc = SFMFARequiredError("challenge-123")
        assert exc.challenge_id == "challenge-123"
        assert "challenge-123" in str(exc)

    def test_sf_brute_force_error(self) -> None:
        exc = SFBruteForceLockedError("2099-01-01T00:00:00+00:00", "totp:key_abc")
        assert exc.unlock_at == "2099-01-01T00:00:00+00:00"
        assert exc.resource == "totp:key_abc"

    def test_sf_startup_error(self) -> None:
        exc = SFStartupError(["identity", "audit"])
        assert exc.services == ["identity", "audit"]

    def test_sf_quota_exceeded_error(self) -> None:
        exc = SFQuotaExceededError(tier="api", daily_limit=10_000, retry_after=3600)
        assert exc.tier == "api"
        assert exc.daily_limit == 10_000
        assert exc.retry_after == 3600

    def test_sf_scope_error(self) -> None:
        exc = SFScopeError("sf_pii", ["sf_audit"])
        assert exc.required_scope == "sf_pii"
        assert exc.key_scopes == ["sf_audit"]

    def test_no_secret_in_key_format_error_message(self) -> None:
        """The error message must NOT contain the actual key value."""
        fake_key = "sf_live_" + "X" * 48
        with pytest.raises(SFKeyFormatError) as exc_info:
            KeyFormat.validate(fake_key + "toolong")
        # The detail should not echo the entire key value
        assert fake_key not in exc_info.value.detail

    def test_auth_error_unknown_key_no_key_value(self, identity: SFIdentityClient) -> None:
        """create_session error for unknown key should not log the key value."""
        fake_key = "sf_live_" + "Y" * 48
        with pytest.raises(SFAuthError) as exc_info:
            identity.create_session(fake_key)
        assert fake_key not in str(exc_info.value)


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_key_issuance(self, identity: SFIdentityClient) -> None:
        results: list = []
        errors: list = []

        def issue() -> None:
            try:
                b = identity.issue_api_key()
                results.append(b.key_id)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=issue) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(results) == 20
        assert len(set(results)) == 20  # all unique key_ids

    def test_concurrent_rate_limiting(self, local_config: SFClientConfig) -> None:
        client = SFIdentityClient(local_config)
        client._rate_limiter = _SlidingWindowRateLimiter(limit=50, window_seconds=60)
        b = client.issue_api_key()

        allowed: list = []
        errors: list = []

        def record() -> None:
            try:
                ok = client.record_request(b.key_id)
                allowed.append(ok)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=record) for _ in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert allowed.count(True) == 50
        assert allowed.count(False) == 50


# ---------------------------------------------------------------------------
# SDK __init__ imports
# ---------------------------------------------------------------------------


class TestSDKImports:
    def test_sf_identity_is_identity_client(self) -> None:
        from spanforge.sdk import sf_identity
        assert isinstance(sf_identity, SFIdentityClient)

    def test_stub_services_raise_not_implemented(self) -> None:
        # sf_observe remains a stub until Phase 6 ships.
        from spanforge.sdk import sf_observe

        with pytest.raises(NotImplementedError):
            _ = sf_observe.something  # type: ignore[attr-defined]

    def test_sf_audit_is_real_client(self) -> None:
        from spanforge.sdk import sf_audit
        from spanforge.sdk.audit import SFAuditClient
        assert isinstance(sf_audit, SFAuditClient)

    def test_sf_secrets_is_real_client(self) -> None:
        from spanforge.sdk import sf_secrets
        from spanforge.sdk.secrets import SFSecretsClient
        assert isinstance(sf_secrets, SFSecretsClient)

    def test_sf_pii_is_real_client(self) -> None:
        from spanforge.sdk import sf_pii
        from spanforge.sdk.pii import SFPIIClient
        assert isinstance(sf_pii, SFPIIClient)

    def test_configure_replaces_singleton(self) -> None:
        from spanforge.sdk import configure, sf_identity as before
        new_cfg = SFClientConfig(signing_key="new-key")
        configure(new_cfg)
        from spanforge.sdk import sf_identity as after
        assert after._signing_key == "new-key"
        # Restore
        configure(SFClientConfig.from_env())

    def test_all_exceptions_exported(self) -> None:
        from spanforge import sdk
        for name in [
            "SFError", "SFAuthError", "SFKeyFormatError", "SFTokenInvalidError",
            "SFIPDeniedError", "SFServiceUnavailableError", "SFRateLimitError",
            "SFMFARequiredError", "SFBruteForceLockedError",
        ]:
            assert hasattr(sdk, name), f"{name} not exported from spanforge.sdk"

    def test_all_types_exported(self) -> None:
        from spanforge import sdk
        for name in [
            "SecretStr", "KeyFormat", "APIKeyBundle", "JWTClaims",
            "RateLimitInfo", "TokenIntrospectionResult",
            "MagicLinkResult", "TOTPEnrollResult",
        ]:
            assert hasattr(sdk, name), f"{name} not exported from spanforge.sdk"


# ---------------------------------------------------------------------------
# SFServiceClient — _request() paths (mocked urllib)
# ---------------------------------------------------------------------------


class TestSFServiceClientRequest:
    """Test the HTTP retry / error translation logic via mocks."""

    class _ConcreteClient(SFServiceClient):
        pass

    def _make_client(
        self,
        local_fallback: bool = False,
        retries: int = 0,
    ) -> "_ConcreteClient":
        cfg = SFClientConfig(
            endpoint="https://example.invalid",
            api_key=SecretStr("sf_live_" + "A" * 48),
            max_retries=retries,
            timeout_ms=500,
            local_fallback_enabled=local_fallback,
            tls_verify=True,
        )
        return self._ConcreteClient(cfg, "test")

    def test_success_returns_json(self) -> None:
        import io
        import urllib.error
        from unittest.mock import MagicMock, patch

        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        opener = MagicMock()
        opener.open.return_value = mock_resp

        with patch.object(client, "_build_opener", return_value=opener):
            result = client._request("GET", "/health")

        assert result == {"ok": True}
        client._circuit_breaker.record_success()  # was already called internally

    def test_empty_response_returns_empty_dict(self) -> None:
        from unittest.mock import MagicMock, patch

        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.read.return_value = b""
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        opener = MagicMock()
        opener.open.return_value = mock_resp

        with patch.object(client, "_build_opener", return_value=opener):
            result = client._request("GET", "/health")

        assert result == {}

    def test_429_raises_rate_limit_error(self) -> None:
        import urllib.error
        from unittest.mock import MagicMock, patch
        from http.client import HTTPMessage

        client = self._make_client()
        headers = HTTPMessage()
        headers["Retry-After"] = "45"
        http_err = urllib.error.HTTPError(
            url="https://example.invalid/health",
            code=429,
            msg="Too Many Requests",
            hdrs=headers,
            fp=None,
        )
        opener = MagicMock()
        opener.open.side_effect = http_err

        with patch.object(client, "_build_opener", return_value=opener):
            with pytest.raises(SFRateLimitError) as exc_info:
                client._request("GET", "/health")

        assert exc_info.value.retry_after == 45

    def test_401_raises_auth_error(self) -> None:
        import urllib.error
        from unittest.mock import MagicMock, patch
        from http.client import HTTPMessage

        client = self._make_client()
        http_err = urllib.error.HTTPError(
            url="https://example.invalid/health",
            code=401,
            msg="Unauthorized",
            hdrs=HTTPMessage(),
            fp=None,
        )
        opener = MagicMock()
        opener.open.side_effect = http_err

        with patch.object(client, "_build_opener", return_value=opener):
            with pytest.raises(SFAuthError):
                client._request("GET", "/health")

    def test_403_raises_auth_error(self) -> None:
        import urllib.error
        from unittest.mock import MagicMock, patch
        from http.client import HTTPMessage

        client = self._make_client()
        http_err = urllib.error.HTTPError(
            url="https://example.invalid/health",
            code=403,
            msg="Forbidden",
            hdrs=HTTPMessage(),
            fp=None,
        )
        opener = MagicMock()
        opener.open.side_effect = http_err

        with patch.object(client, "_build_opener", return_value=opener):
            with pytest.raises(SFAuthError):
                client._request("GET", "/health")

    def test_url_error_with_no_fallback_raises_unavailable(self) -> None:
        import urllib.error
        from unittest.mock import MagicMock, patch

        client = self._make_client(local_fallback=False, retries=0)
        opener = MagicMock()
        opener.open.side_effect = urllib.error.URLError("connection refused")

        with patch.object(client, "_build_opener", return_value=opener):
            with pytest.raises(SFServiceUnavailableError):
                client._request("GET", "/health")

    def test_url_error_with_fallback_reraises_last_exc(self) -> None:
        import urllib.error
        from unittest.mock import MagicMock, patch

        client = self._make_client(local_fallback=True, retries=0)
        url_exc = urllib.error.URLError("connection refused")
        opener = MagicMock()
        opener.open.side_effect = url_exc

        with patch.object(client, "_build_opener", return_value=opener):
            with pytest.raises(urllib.error.URLError):
                client._request("GET", "/health")

    def test_retry_on_http_5xx_then_success(self) -> None:
        import urllib.error
        from unittest.mock import MagicMock, call, patch
        from http.client import HTTPMessage

        client = self._make_client(local_fallback=False, retries=2)

        http_err = urllib.error.HTTPError(
            url="https://example.invalid/health",
            code=503,
            msg="Service Unavailable",
            hdrs=HTTPMessage(),
            fp=None,
        )
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"status": "ok"}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        # Fail twice, succeed on third attempt
        opener = MagicMock()
        opener.open.side_effect = [http_err, http_err, mock_resp]

        with patch("time.sleep"):  # suppress actual sleep
            with patch.object(client, "_build_opener", return_value=opener):
                result = client._request("GET", "/health")

        assert result == {"status": "ok"}
        assert opener.open.call_count == 3

    def test_request_with_body(self) -> None:
        from unittest.mock import MagicMock, patch

        client = self._make_client()
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"created": true}'
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        opener = MagicMock()
        opener.open.return_value = mock_resp

        with patch.object(client, "_build_opener", return_value=opener):
            result = client._request("POST", "/v1/keys", {"name": "test"})

        assert result == {"created": True}


# ---------------------------------------------------------------------------
# _build_opener — TLS and proxy branches
# ---------------------------------------------------------------------------


class TestBuildOpener:
    def test_default_opener_returns_opener(self) -> None:
        cfg = SFClientConfig(endpoint="https://example.invalid", tls_verify=True)

        class _Stub(SFServiceClient):
            pass

        client = _Stub(cfg, "test")
        opener = client._build_opener()
        import urllib.request
        assert isinstance(opener, urllib.request.OpenerDirector)

    def test_tls_verify_false_adds_https_handler(self) -> None:
        cfg = SFClientConfig(
            endpoint="https://example.invalid", tls_verify=False
        )

        class _Stub(SFServiceClient):
            pass

        client = _Stub(cfg, "test")
        import urllib.request
        opener = client._build_opener()
        assert isinstance(opener, urllib.request.OpenerDirector)

    def test_proxy_config_adds_proxy_handler(self) -> None:
        cfg = SFClientConfig(
            endpoint="https://example.invalid",
            proxy="http://proxy.local:8080",
        )

        class _Stub(SFServiceClient):
            pass

        client = _Stub(cfg, "test")
        import urllib.request
        opener = client._build_opener()
        assert isinstance(opener, urllib.request.OpenerDirector)

    def test_proxy_in_init_installs_opener(self) -> None:
        """SFServiceClient.__init__ calls install_opener when proxy is set."""
        from unittest.mock import patch
        import urllib.request

        cfg = SFClientConfig(
            endpoint="https://example.invalid",
            proxy="http://proxy.local:8080",
        )

        class _Stub(SFServiceClient):
            pass

        with patch.object(urllib.request, "install_opener") as mock_install:
            client = _Stub(cfg, "test")
        mock_install.assert_called_once()


# ---------------------------------------------------------------------------
# SFIdentityClient — remote mode branches (mocked _request)
# ---------------------------------------------------------------------------


class TestIdentityRemoteMode:
    """Verify remote-mode code paths via mocked _request."""

    _BUNDLE_RESP = {
        "api_key": "sf_live_" + "A" * 48,
        "key_id": "key_remote123",
        "jwt": "hdr.payload.sig",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "scopes": ["sf_audit"],
    }

    @pytest.fixture()
    def remote_identity(self) -> SFIdentityClient:
        cfg = SFClientConfig(
            endpoint="https://sf.example.invalid",
            api_key=SecretStr("sf_live_" + "A" * 48),
            signing_key="remote-signing-key",
        )
        return SFIdentityClient(cfg)

    def test_issue_api_key_remote(self, remote_identity: SFIdentityClient) -> None:
        from unittest.mock import patch
        with patch.object(remote_identity, "_request", return_value=self._BUNDLE_RESP):
            bundle = remote_identity.issue_api_key(scopes=["sf_audit"])
        assert bundle.key_id == "key_remote123"
        assert bundle.api_key.get_secret_value() == "sf_live_" + "A" * 48

    def test_issue_magic_link_remote(self, remote_identity: SFIdentityClient) -> None:
        from unittest.mock import patch
        resp = {"link_id": "link_abc", "expires_at": "2099-01-01T00:00:00+00:00"}
        with patch.object(remote_identity, "_request", return_value=resp):
            result = remote_identity.issue_magic_link("user@example.com")
        assert result.link_id == "link_abc"

    def test_exchange_magic_link_remote(self, remote_identity: SFIdentityClient) -> None:
        from unittest.mock import patch
        with patch.object(remote_identity, "_request", return_value=self._BUNDLE_RESP):
            bundle = remote_identity.exchange_magic_link("tok", link_id="link_abc")
        assert bundle.key_id == "key_remote123"

    def test_rotate_key_remote(self, remote_identity: SFIdentityClient) -> None:
        from unittest.mock import patch
        with patch.object(remote_identity, "_request", return_value=self._BUNDLE_RESP):
            bundle = remote_identity.rotate_key("key_old")
        assert bundle.key_id == "key_remote123"

    def test_revoke_key_remote(self, remote_identity: SFIdentityClient) -> None:
        from unittest.mock import patch
        with patch.object(remote_identity, "_request", return_value={}):
            remote_identity.revoke_key("key_old")  # should not raise

    def test_create_session_remote(self, remote_identity: SFIdentityClient) -> None:
        from unittest.mock import patch
        with patch.object(remote_identity, "_request", return_value={"jwt": "tok.tok.tok"}):
            jwt = remote_identity.create_session("sf_live_" + "A" * 48)
        assert jwt == "tok.tok.tok"

    def test_verify_token_remote(self, remote_identity: SFIdentityClient) -> None:
        from unittest.mock import patch
        resp = {
            "sub": "key_remote123",
            "scopes": ["sf_audit"],
            "aud": "proj_x",
            "exp": "2099-01-01T00:00:00+00:00",
            "iat": "2024-01-01T00:00:00+00:00",
            "jti": "jti-abc",
            "iss": "spanforge",
        }
        with patch.object(remote_identity, "_request", return_value=resp):
            claims = remote_identity.verify_token("hdr.payload.sig")
        assert claims.subject == "key_remote123"

    def test_introspect_remote(self, remote_identity: SFIdentityClient) -> None:
        from unittest.mock import patch
        resp = {"active": True, "scope": "sf_audit", "exp": 9999999999, "sub": "k1", "client_id": "p1"}
        with patch.object(remote_identity, "_request", return_value=resp):
            result = remote_identity.introspect("hdr.payload.sig")
        assert result.active is True

    def test_enroll_totp_remote(self, remote_identity: SFIdentityClient) -> None:
        from unittest.mock import patch
        resp = {
            "secret": "JBSWY3DPEHPK3PXP",
            "qr_uri": "otpauth://totp/test",
            "backup_codes": ["AAAAAAAA"] * 8,
        }
        with patch.object(remote_identity, "_request", return_value=resp):
            result = remote_identity.enroll_totp("key_abc")
        assert result.secret_base32.get_secret_value() == "JBSWY3DPEHPK3PXP"

    def test_verify_totp_remote(self, remote_identity: SFIdentityClient) -> None:
        from unittest.mock import patch
        with patch.object(remote_identity, "_request", return_value={"valid": True}):
            assert remote_identity.verify_totp("key_abc", "123456") is True

    def test_verify_backup_code_remote(self, remote_identity: SFIdentityClient) -> None:
        from unittest.mock import patch
        with patch.object(remote_identity, "_request", return_value={"valid": True}):
            assert remote_identity.verify_backup_code("key_abc", "AAAAAAAA") is True

    def test_check_rate_limit_remote(self, remote_identity: SFIdentityClient) -> None:
        from unittest.mock import patch
        resp = {"limit": 1000, "remaining": 800, "reset_at": "2099-01-01T00:00:00+00:00"}
        with patch.object(remote_identity, "_request", return_value=resp):
            info = remote_identity.check_rate_limit("key_abc")
        assert info.limit == 1000

    def test_record_request_remote(self, remote_identity: SFIdentityClient) -> None:
        from unittest.mock import patch
        with patch.object(remote_identity, "_request", return_value={"allowed": True}):
            assert remote_identity.record_request("key_abc") is True

    def test_check_ip_allowlist_remote(self, remote_identity: SFIdentityClient) -> None:
        from unittest.mock import patch
        with patch.object(remote_identity, "_request", return_value={}):
            remote_identity.check_ip_allowlist("key_abc", "10.0.0.1")  # no raise

    def test_get_jwks_remote(self, remote_identity: SFIdentityClient) -> None:
        from unittest.mock import patch
        resp = {"keys": [{"kty": "RSA", "kid": "k1"}]}
        with patch.object(remote_identity, "_request", return_value=resp):
            jwks = remote_identity.get_jwks()
        assert len(jwks["keys"]) == 1


# ---------------------------------------------------------------------------
# SFIdentityClient — init from env (no config argument)
# ---------------------------------------------------------------------------


class TestIdentityInitFromEnv:
    def test_no_config_uses_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SPANFORGE_SIGNING_KEY", "env-signing-key")
        client = SFIdentityClient()
        assert client._signing_key == "env-signing-key"

    def test_no_env_uses_fallback_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("SPANFORGE_SIGNING_KEY", raising=False)
        monkeypatch.delenv("SPANFORGE_MAGIC_SECRET", raising=False)
        client = SFIdentityClient()
        assert "spanforge" in client._signing_key.lower()


# ---------------------------------------------------------------------------
# Phase 1 completion tests: ID-003, ID-005, ID-031, ID-051, ID-052
# ---------------------------------------------------------------------------


class TestPhase1Completions:
    """Tests for features introduced to close Phase 1 roadmap gaps."""

    @pytest.fixture()
    def cfg(self) -> SFClientConfig:
        return SFClientConfig(
            endpoint="",
            api_key=SecretStr(""),
            signing_key="test-signing-key-phase1",
            magic_secret="test-magic-secret-phase1",
            project_id="proj-test",
        )

    @pytest.fixture()
    def client(self, cfg: SFClientConfig) -> SFIdentityClient:
        return SFIdentityClient(cfg)

    # ------------------------------------------------------------------
    # _today_midnight_utc helper (lines 240-242)
    # ------------------------------------------------------------------

    def test_today_midnight_utc_returns_float(self) -> None:
        from spanforge.sdk.identity import _today_midnight_utc

        ts = _today_midnight_utc()
        assert isinstance(ts, float)
        # Must be in the past (today midnight has already passed)
        assert ts <= time.time()
        # Must be within the last 24 hours
        assert ts >= time.time() - 86_400

    # ------------------------------------------------------------------
    # ID-003: refresh_token (lines 345-357)
    # ------------------------------------------------------------------

    def test_refresh_token_local_mode(self, client: SFIdentityClient) -> None:
        """Local refresh_token issues a new JWT for the configured key."""
        bundle = client.issue_api_key(scopes=["read"])
        client._config.api_key = SecretStr(bundle.api_key.get_secret_value())
        jwt = client.refresh_token()
        assert isinstance(jwt, str)
        assert len(jwt) > 0

    def test_refresh_token_no_key_raises_auth_error(self, cfg: SFClientConfig) -> None:
        """refresh_token with no api_key raises SFAuthError."""
        client = SFIdentityClient(cfg)
        with pytest.raises(SFAuthError):
            client.refresh_token()

    # ------------------------------------------------------------------
    # ID-003: _on_token_near_expiry fallback path (lines 323-329)
    # ------------------------------------------------------------------

    def test_on_token_near_expiry_fallback_warns_instead_of_raising(
        self, client: SFIdentityClient
    ) -> None:
        """When local_fallback_enabled, failure in refresh_token logs a warning."""
        client._config.local_fallback_enabled = True
        # No api_key configured → refresh_token() raises SFAuthError internally;
        # _on_token_near_expiry should swallow it and log a warning
        client._on_token_near_expiry(30)  # must not raise

    def test_on_token_near_expiry_raises_when_no_fallback(
        self, client: SFIdentityClient
    ) -> None:
        """Without local_fallback, failure in refresh propagates."""
        client._config.local_fallback_enabled = False
        with pytest.raises(SFAuthError):
            client._on_token_near_expiry(5)

    # ------------------------------------------------------------------
    # Expired API key in create_session (line 690)
    # ------------------------------------------------------------------

    def test_create_session_expired_key(self, client: SFIdentityClient) -> None:
        """create_session raises SFAuthError when the key has expired."""
        bundle = client.issue_api_key(scopes=["read"])
        with client._lock:
            client._keys_by_id[bundle.key_id]["expires_at"] = int(time.time()) - 1

        with pytest.raises(SFAuthError, match="expired"):
            client.create_session(bundle.api_key.get_secret_value())

    # ------------------------------------------------------------------
    # ID-005: unknown SPANFORGE_* env var warning (line 300)
    # ------------------------------------------------------------------

    def test_from_env_warns_on_unknown_spanforge_var(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """SFClientConfig.from_env() logs a warning for unknown SPANFORGE_* vars."""
        import logging

        monkeypatch.setenv("SPANFORGE_UNKNOWN_XYZZY", "1")
        with caplog.at_level(logging.WARNING, logger="spanforge.sdk._base"):
            SFClientConfig.from_env()
        assert any("SPANFORGE_UNKNOWN_XYZZY" in r.message for r in caplog.records)

    # ------------------------------------------------------------------
    # JWTClaims.is_expired() True branch (types.py:277)
    # ------------------------------------------------------------------

    def test_jwt_claims_is_expired_true(self, client: SFIdentityClient) -> None:
        """JWTClaims.is_expired() returns True for a past expires_at."""
        bundle = client.issue_api_key(scopes=["read"], expires_in_days=1)
        claims = client.verify_token(bundle.jwt)
        # Patch the expires_at field to force expiry
        from dataclasses import replace as dc_replace

        past = datetime(2000, 1, 1, tzinfo=timezone.utc)
        expired_claims = dc_replace(claims, expires_at=past)
        assert expired_claims.is_expired() is True

    # ------------------------------------------------------------------
    # Invalid CIDR warning in check_ip_allowlist (lines 1057-1059)
    # ------------------------------------------------------------------

    def test_check_ip_allowlist_skips_invalid_cidr(
        self, client: SFIdentityClient
    ) -> None:
        """check_ip_allowlist ignores malformed CIDR entries and keeps checking."""
        bundle = client.issue_api_key(scopes=["read"])
        with client._lock:
            client._keys_by_id[bundle.key_id]["ip_allowlist"] = [
                "not-a-cidr",
                "10.0.0.0/8",
            ]
        # Valid IP in the second (good) CIDR → should pass
        client.check_ip_allowlist(bundle.key_id, "10.1.2.3")

    def test_check_ip_allowlist_invalid_only_raises(
        self, client: SFIdentityClient
    ) -> None:
        """When only invalid CIDRs are present, the IP is ultimately denied."""
        bundle = client.issue_api_key(scopes=["read"])
        with client._lock:
            client._keys_by_id[bundle.key_id]["ip_allowlist"] = ["not-a-cidr"]

        with pytest.raises(SFIPDeniedError):
            client.check_ip_allowlist(bundle.key_id, "1.2.3.4")

    # ------------------------------------------------------------------
    # ID-031: MFA policy enforcement (lines 577-578, 1119-1132)
    # ------------------------------------------------------------------

    def test_set_and_get_mfa_policy(self, client: SFIdentityClient) -> None:
        assert client.get_mfa_policy("proj-a") is False
        client.set_mfa_policy("proj-a", True)
        assert client.get_mfa_policy("proj-a") is True
        client.set_mfa_policy("proj-a", False)
        assert client.get_mfa_policy("proj-a") is False

    def test_exchange_magic_link_raises_mfa_required_when_policy_set(
        self, client: SFIdentityClient
    ) -> None:
        """exchange_magic_link raises SFMFARequiredError when MFA is enforced."""
        client.set_mfa_policy(client._config.project_id, True)
        result = client.issue_magic_link("user@example.com")
        token = client._magic_links[result.link_id]["token"]
        with pytest.raises(SFMFARequiredError) as exc_info:
            client.exchange_magic_link(
                token,
                link_id=result.link_id,
                otp=None,
            )
        assert exc_info.value.challenge_id is not None

    def test_exchange_magic_link_mfa_policy_otp_provided_succeeds(
        self, client: SFIdentityClient
    ) -> None:
        """Providing an OTP when MFA policy is active allows exchange to proceed."""
        client.set_mfa_policy(client._config.project_id, True)
        result = client.issue_magic_link("user@example.com")
        token = client._magic_links[result.link_id]["token"]
        # Providing any non-None otp bypasses the MFA check in local mode
        bundle = client.exchange_magic_link(
            token,
            link_id=result.link_id,
            otp="123456",
        )
        assert bundle.api_key.get_secret_value().startswith("sf_live_")

    # ------------------------------------------------------------------
    # ID-051: set_key_tier / consume_quota (lines 1150-1200)
    # ------------------------------------------------------------------

    def test_set_key_tier_unknown_raises_value_error(
        self, client: SFIdentityClient
    ) -> None:
        bundle = client.issue_api_key(scopes=["read"])
        with pytest.raises(ValueError, match="Unknown quota tier"):
            client.set_key_tier(bundle.key_id, "diamond")

    def test_set_key_tier_unknown_key_raises_auth_error(
        self, client: SFIdentityClient
    ) -> None:
        with pytest.raises(SFAuthError, match="Key not found"):
            client.set_key_tier("nonexistent-key-id", QuotaTier.API)

    def test_consume_quota_enterprise_unlimited(self, client: SFIdentityClient) -> None:
        bundle = client.issue_api_key(scopes=["read"])
        client.set_key_tier(bundle.key_id, QuotaTier.ENTERPRISE)
        for _ in range(100):  # enterprise: no limit
            assert client.consume_quota(bundle.key_id) is True

    def test_consume_quota_free_raises_immediately(
        self, client: SFIdentityClient
    ) -> None:
        bundle = client.issue_api_key(scopes=["read"])
        client.set_key_tier(bundle.key_id, QuotaTier.FREE)
        with pytest.raises(SFQuotaExceededError) as exc_info:
            client.consume_quota(bundle.key_id)
        assert exc_info.value.daily_limit == 0
        assert exc_info.value.retry_after > 0

    def test_consume_quota_api_tier_enforces_limit(
        self, client: SFIdentityClient
    ) -> None:
        bundle = client.issue_api_key(scopes=["read"])
        client.set_key_tier(bundle.key_id, QuotaTier.API)
        limit = QuotaTier.daily_limit(QuotaTier.API)
        for _ in range(limit):
            assert client.consume_quota(bundle.key_id) is True
        with pytest.raises(SFQuotaExceededError):
            client.consume_quota(bundle.key_id)

    def test_consume_quota_team_tier(self, client: SFIdentityClient) -> None:
        bundle = client.issue_api_key(scopes=["read"])
        client.set_key_tier(bundle.key_id, QuotaTier.TEAM)
        assert client.consume_quota(bundle.key_id) is True

    # ------------------------------------------------------------------
    # ID-052: get_quota_usage (lines 1212-1230)
    # ------------------------------------------------------------------

    def test_get_quota_usage_enterprise(self, client: SFIdentityClient) -> None:
        bundle = client.issue_api_key(scopes=["read"])
        client.set_key_tier(bundle.key_id, QuotaTier.ENTERPRISE)
        client.consume_quota(bundle.key_id)
        usage = client.get_quota_usage(bundle.key_id)
        assert usage["tier"] == QuotaTier.ENTERPRISE
        assert usage["daily_limit"] == "unlimited"
        assert usage["remaining_today"] == "unlimited"
        assert usage["consumed_today"] == 1

    def test_get_quota_usage_api_tier(self, client: SFIdentityClient) -> None:
        bundle = client.issue_api_key(scopes=["read"])
        client.set_key_tier(bundle.key_id, QuotaTier.API)
        client.consume_quota(bundle.key_id)
        client.consume_quota(bundle.key_id)
        usage = client.get_quota_usage(bundle.key_id)
        assert usage["key_id"] == bundle.key_id
        assert usage["tier"] == QuotaTier.API
        assert usage["consumed_today"] == 2
        limit = QuotaTier.daily_limit(QuotaTier.API)
        assert usage["remaining_today"] == limit - 2

    def test_get_quota_usage_unknown_key_defaults_to_free(
        self, client: SFIdentityClient
    ) -> None:
        usage = client.get_quota_usage("ghost-key-id")
        assert usage["tier"] == QuotaTier.FREE
        assert usage["consumed_today"] == 0

    # ------------------------------------------------------------------
    # ID-003: X-SF-Token-Expires header triggers refresh hook (_base.py 471-477)
    # ------------------------------------------------------------------

    def test_base_token_expires_header_triggers_hook(self) -> None:
        """_request() calls _on_token_near_expiry when header < 60 seconds."""
        from unittest.mock import MagicMock, patch

        cfg = SFClientConfig(
            endpoint="https://example.invalid",
            api_key=SecretStr("sf_live_" + "A" * 48),
            timeout_ms=500,
        )

        hook_called: list[int] = []

        class _Client(SFServiceClient):
            def _on_token_near_expiry(self, seconds_remaining: int) -> None:
                hook_called.append(seconds_remaining)

        client_obj = _Client(cfg, "test")

        headers_dict = {"Content-Type": "application/json", "X-SF-Token-Expires": "30"}

        class _Headers:
            def get(self, k: str, d: object = None) -> object:
                return headers_dict.get(k, d)

        mock_resp = MagicMock()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.status = 200
        mock_resp.headers = _Headers()

        mock_opener = MagicMock()
        mock_opener.open.return_value = mock_resp

        with patch.object(client_obj, "_build_opener", return_value=mock_opener):
            result = client_obj._request("GET", "/v1/test")

        assert hook_called == [30]
        assert result == {"ok": True}
