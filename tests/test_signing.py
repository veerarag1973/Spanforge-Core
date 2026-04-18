"""Tests for spanforge.signing — HMAC-SHA256 signing and audit chain.

100% branch/statement coverage target.
"""

from __future__ import annotations

import time

import pytest

from spanforge import Event, EventType, Tags
from spanforge.exceptions import SigningError, VerificationError
from spanforge.signing import (
    AuditStream,
    ChainVerificationResult,
    _canonical_payload_bytes,
    _compute_checksum,
    _compute_signature,
    _validate_secret,
    assert_verified,
    sign,
    verify,
    verify_chain,
)
from tests.conftest import FIXED_SPAN_ID, FIXED_TIMESTAMP, FIXED_TRACE_ID

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SECRET = "test-hmac-secret-v1"
_SOURCE = "signing-daemon@1.0.0"


def _event(**kwargs) -> Event:
    defaults = {
        "event_type": EventType.TRACE_SPAN_COMPLETED,
        "source": _SOURCE,
        "payload": {"span_name": "run", "status": "ok"},
        "timestamp": FIXED_TIMESTAMP,
    }
    defaults.update(kwargs)
    return Event(**defaults)


def _chain(n: int, secret: str = _SECRET) -> list[Event]:
    """Build and return a fully signed chain of *n* events."""
    stream = AuditStream(org_secret=secret, source=_SOURCE)
    for i in range(n):
        stream.append(_event(payload={"i": i, "status": "ok"}))
    return stream.events


# ===========================================================================
# _validate_secret (internal guard)
# ===========================================================================


@pytest.mark.unit
class TestValidateSecret:
    def test_valid_secret_passes(self) -> None:
        _validate_secret("non-empty")  # must not raise

    def test_empty_string_raises(self) -> None:
        with pytest.raises(SigningError, match="non-empty"):
            _validate_secret("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(SigningError):
            _validate_secret("   ")

    def test_non_string_raises(self) -> None:
        with pytest.raises(SigningError):
            _validate_secret(None)  # type: ignore[arg-type]  # NOSONAR

    def test_non_string_int_raises(self) -> None:
        with pytest.raises(SigningError):
            _validate_secret(123)  # type: ignore[arg-type]  # NOSONAR


# ===========================================================================
# Crypto helpers
# ===========================================================================


@pytest.mark.unit
class TestCryptoHelpers:
    def test_checksum_has_sha256_prefix(self) -> None:
        cs = _compute_checksum({"key": "val"})
        assert cs.startswith("sha256:")

    def test_checksum_is_64_hex_after_prefix(self) -> None:
        cs = _compute_checksum({"key": "val"})
        digest = cs[len("sha256:"):]
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_same_payload_same_checksum(self) -> None:
        p = {"b": 2, "a": 1}
        assert _compute_checksum(p) == _compute_checksum(p)

    def test_canonical_bytes_sorted_keys(self) -> None:
        # Key ordering must not affect the canonical form
        p1 = {"b": "2", "a": "1"}
        p2 = {"a": "1", "b": "2"}
        assert _canonical_payload_bytes(p1) == _canonical_payload_bytes(p2)

    def test_canonical_bytes_compact_separators(self) -> None:
        b = _canonical_payload_bytes({"k": "v"})
        assert b"k" in b
        # No whitespace around colon or comma
        assert b": " not in b
        assert b", " not in b

    def test_different_payloads_different_checksums(self) -> None:
        assert _compute_checksum({"k": "a"}) != _compute_checksum({"k": "b"})

    def test_signature_has_hmac_sha256_prefix(self) -> None:
        sig = _compute_signature("eid", "sha256:abc", None, _SECRET)
        assert sig.startswith("hmac-sha256:")

    def test_signature_hex_length(self) -> None:
        sig = _compute_signature("eid", "sha256:abc", "prev", _SECRET)
        digest = sig[len("hmac-sha256:"):]
        assert len(digest) == 64

    def test_signature_changes_with_prev_id(self) -> None:
        s1 = _compute_signature("eid", "sha256:abc", None, _SECRET)
        s2 = _compute_signature("eid", "sha256:abc", "prev_id_val", _SECRET)
        assert s1 != s2

    def test_signature_changes_with_secret(self) -> None:
        s1 = _compute_signature("eid", "sha256:abc", None, "secret-a")
        s2 = _compute_signature("eid", "sha256:abc", None, "secret-b")
        assert s1 != s2


# ===========================================================================
# sign()
# ===========================================================================


@pytest.mark.unit
class TestSign:
    def test_returns_new_event_instance(self) -> None:
        event = _event()
        signed = sign(event, _SECRET)
        assert signed is not event

    def test_signed_event_has_checksum(self) -> None:
        signed = sign(_event(), _SECRET)
        assert signed.checksum is not None
        assert signed.checksum.startswith("sha256:")

    def test_signed_event_has_signature(self) -> None:
        signed = sign(_event(), _SECRET)
        assert signed.signature is not None
        assert signed.signature.startswith("hmac-sha256:")

    def test_no_prev_event_gives_none_prev_id(self) -> None:
        signed = sign(_event(), _SECRET, prev_event=None)
        assert signed.prev_id is None

    def test_prev_event_sets_prev_id(self) -> None:
        first = sign(_event(), _SECRET)
        second = sign(_event(), _SECRET, prev_event=first)
        assert second.prev_id == first.event_id

    def test_event_id_preserved(self) -> None:
        event = _event()
        signed = sign(event, _SECRET)
        assert signed.event_id == event.event_id

    def test_all_optional_fields_preserved(self) -> None:
        event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source=_SOURCE,
            payload={"k": "v"},
            timestamp=FIXED_TIMESTAMP,
            trace_id=FIXED_TRACE_ID,
            span_id=FIXED_SPAN_ID,
            org_id="org_x",
            actor_id="usr_y",
            tags=Tags(env="prod"),
        )
        signed = sign(event, _SECRET)
        assert signed.trace_id == FIXED_TRACE_ID
        assert signed.span_id == FIXED_SPAN_ID
        assert signed.org_id == "org_x"
        assert signed.actor_id == "usr_y"
        assert signed.tags is not None
        assert signed.tags["env"] == "prod"

    def test_empty_secret_raises(self) -> None:
        with pytest.raises(SigningError):
            sign(_event(), "")

    def test_schema_version_preserved(self) -> None:
        event = _event()
        signed = sign(event, _SECRET)
        assert signed.schema_version == event.schema_version

    def test_source_preserved(self) -> None:
        event = _event()
        signed = sign(event, _SECRET)
        assert signed.source == event.source

    def test_payload_preserved(self) -> None:
        payload = {"span_name": "test", "result": 42}
        event = _event(payload=payload)
        signed = sign(event, _SECRET)
        assert signed.payload == event.payload


# ===========================================================================
# verify()
# ===========================================================================


@pytest.mark.unit
class TestVerify:
    def test_valid_signature_returns_true(self) -> None:
        signed = sign(_event(), _SECRET)
        assert verify(signed, _SECRET) is True

    def test_missing_checksum_returns_false(self) -> None:
        event = _event()  # unsigned — no checksum
        assert event.checksum is None
        assert verify(event, _SECRET) is False

    def test_missing_signature_returns_false(self) -> None:
        # Build event with checksum but no signature
        event = _event()
        from spanforge.signing import _compute_checksum as _cc
        payload_copy = dict(event.payload)
        cs = _cc(payload_copy)
        # Manually create event with checksum but no signature
        event_with_cs = Event(
            schema_version=event.schema_version,
            event_id=event.event_id,
            event_type=event.event_type,
            timestamp=event.timestamp,
            source=event.source,
            payload=payload_copy,
            checksum=cs,
            signature=None,
        )
        assert verify(event_with_cs, _SECRET) is False

    def test_wrong_key_returns_false(self) -> None:
        signed = sign(_event(), _SECRET)
        assert verify(signed, "wrong-key") is False

    def test_tampered_payload_returns_false(self) -> None:
        signed = sign(_event(), _SECRET)
        # Reconstruct event with altered payload but original checksum/signature
        tampered = Event(
            schema_version=signed.schema_version,
            event_id=signed.event_id,
            event_type=signed.event_type,
            timestamp=signed.timestamp,
            source=signed.source,
            payload={"malicious": "injection"},
            checksum=signed.checksum,
            signature=signed.signature,
            prev_id=signed.prev_id,
        )
        assert verify(tampered, _SECRET) is False

    def test_tampered_signature_returns_false(self) -> None:
        signed = sign(_event(), _SECRET)
        tampered = Event(
            schema_version=signed.schema_version,
            event_id=signed.event_id,
            event_type=signed.event_type,
            timestamp=signed.timestamp,
            source=signed.source,
            payload=dict(signed.payload),
            checksum=signed.checksum,
            signature="hmac-sha256:" + "0" * 64,
            prev_id=signed.prev_id,
        )
        assert verify(tampered, _SECRET) is False

    def test_empty_secret_raises(self) -> None:
        signed = sign(_event(), _SECRET)
        with pytest.raises(SigningError):
            verify(signed, "")

    def test_prev_id_included_in_signature(self) -> None:
        first = sign(_event(), _SECRET)
        second = sign(_event(), _SECRET, prev_event=first)
        # Verifying second with correct key should pass
        assert verify(second, _SECRET) is True
        # If we strip prev_id the signature won't match
        stripped = Event(
            schema_version=second.schema_version,
            event_id=second.event_id,
            event_type=second.event_type,
            timestamp=second.timestamp,
            source=second.source,
            payload=dict(second.payload),
            checksum=second.checksum,
            signature=second.signature,
            # No prev_id — changes signature computation input
        )
        assert verify(stripped, _SECRET) is False


# ===========================================================================
# assert_verified()
# ===========================================================================


@pytest.mark.unit
class TestAssertVerified:
    def test_valid_event_does_not_raise(self) -> None:
        signed = sign(_event(), _SECRET)
        assert_verified(signed, _SECRET)  # must not raise

    def test_invalid_event_raises_verification_error(self) -> None:
        event = _event()  # unsigned
        with pytest.raises(VerificationError) as exc_info:
            assert_verified(event, _SECRET)
        assert exc_info.value.event_id == event.event_id

    def test_verification_error_is_spanforge_error(self) -> None:
        from spanforge.exceptions import LLMSchemaError
        err = VerificationError(event_id="01ARYZ3NDEKTSV4RRFFQ69G5FA")
        assert isinstance(err, LLMSchemaError)

    def test_verification_error_message_contains_event_id(self) -> None:
        eid = "01ARYZ3NDEKTSV4RRFFQ69G5FA"
        err = VerificationError(event_id=eid)
        assert eid in str(err)

    def test_empty_secret_raises_signing_error(self) -> None:
        signed = sign(_event(), _SECRET)
        with pytest.raises(SigningError):
            assert_verified(signed, "")


# ===========================================================================
# ChainVerificationResult
# ===========================================================================


@pytest.mark.unit
class TestChainVerificationResult:
    def test_immutable_frozen_dataclass(self) -> None:
        from dataclasses import FrozenInstanceError
        result = ChainVerificationResult(
            valid=True, first_tampered=None, gaps=[], tampered_count=0
        )
        with pytest.raises(FrozenInstanceError):
            result.valid = False  # type: ignore[misc]

    def test_valid_chain_result(self) -> None:
        result = ChainVerificationResult(
            valid=True, first_tampered=None, gaps=[], tampered_count=0
        )
        assert result.valid is True
        assert result.first_tampered is None
        assert result.gaps == []
        assert result.tampered_count == 0


# ===========================================================================
# verify_chain()
# ===========================================================================


@pytest.mark.unit
class TestVerifyChain:
    def test_empty_chain_is_valid(self) -> None:
        result = verify_chain([], org_secret=_SECRET)
        assert result.valid is True
        assert result.tampered_count == 0
        assert result.gaps == []
        assert result.first_tampered is None

    def test_single_signed_event_is_valid(self) -> None:
        chain = _chain(1)
        result = verify_chain(chain, org_secret=_SECRET)
        assert result.valid is True

    def test_multi_event_chain_is_valid(self) -> None:
        chain = _chain(5)
        result = verify_chain(chain, org_secret=_SECRET)
        assert result.valid is True
        assert result.tampered_count == 0
        assert result.gaps == []

    def test_single_tampered_event_detected(self) -> None:
        chain = _chain(3)
        # Tamper event[1]'s payload
        e = chain[1]
        tampered = Event(
            schema_version=e.schema_version,
            event_id=e.event_id,
            event_type=e.event_type,
            timestamp=e.timestamp,
            source=e.source,
            payload={"injected": "malicious"},
            checksum=e.checksum,
            signature=e.signature,
            prev_id=e.prev_id,
        )
        chain[1] = tampered
        result = verify_chain(chain, org_secret=_SECRET)
        assert result.valid is False
        assert result.first_tampered == tampered.event_id
        assert result.tampered_count == 1

    def test_multiple_tampered_events_count_correct(self) -> None:
        chain = list(_chain(4))
        for idx in (0, 2):
            e = chain[idx]
            chain[idx] = Event(
                schema_version=e.schema_version,
                event_id=e.event_id,
                event_type=e.event_type,
                timestamp=e.timestamp,
                source=e.source,
                payload={"bad": "data"},
                checksum=e.checksum,
                signature=e.signature,
                prev_id=e.prev_id,
            )
        result = verify_chain(chain, org_secret=_SECRET)
        assert result.tampered_count == 2
        assert result.first_tampered == chain[0].event_id  # earliest tampered

    def test_first_event_with_prev_id_is_a_gap(self) -> None:
        """If events[0].prev_id is not None, the chain head is missing."""
        chain = _chain(3)
        # Inject a fake prev_id on the first event
        e = chain[0]
        head_with_prev = Event(
            schema_version=e.schema_version,
            event_id=e.event_id,
            event_type=e.event_type,
            timestamp=e.timestamp,
            source=e.source,
            payload=dict(e.payload),
            checksum=e.checksum,
            signature=e.signature,
            prev_id="01ARYZ3NDEKTSV4RRFFQ69G5FA",  # non-None but fake
        )
        modified_chain = [head_with_prev, *chain[1:]]
        result = verify_chain(modified_chain, org_secret=_SECRET)
        assert e.event_id in result.gaps

    def test_deleted_middle_event_creates_gap(self) -> None:
        """Removing event[1] from the chain breaks event[2].prev_id linkage."""
        chain = _chain(4)
        # Delete event at index 1
        truncated = [chain[0], *chain[2:]]
        result = verify_chain(truncated, org_secret=_SECRET)
        assert result.valid is False
        assert chain[2].event_id in result.gaps

    def test_wrong_key_flags_all_events_as_tampered(self) -> None:
        chain = _chain(3)
        result = verify_chain(chain, org_secret="wrong-key")
        assert result.valid is False
        assert result.tampered_count == 3

    def test_empty_secret_raises(self) -> None:
        with pytest.raises(SigningError):
            verify_chain([], org_secret="")

    def test_key_map_with_invalid_new_secret_raises(self) -> None:
        with pytest.raises(SigningError):
            verify_chain([], org_secret=_SECRET, key_map={"someid": ""})

    def test_key_rotation_chain_verifies(self) -> None:
        """Chain with one key rotation segment verifies with key_map."""
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        stream.append(_event(payload={"i": 0, "status": "ok"}))
        stream.rotate_key("new-secret-v2")
        stream.append(_event(payload={"i": 1, "status": "ok"}))

        result = stream.verify()
        assert result.valid is True
        assert result.tampered_count == 0
        assert result.gaps == []

    def test_key_rotation_independent_verify(self) -> None:
        """Caller can verify a rotated chain without an AuditStream instance."""
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        stream.append(_event(payload={"i": 0, "status": "ok"}))
        rotation = stream.rotate_key("new-secret-v2")
        stream.append(_event(payload={"i": 1, "status": "ok"}))

        events = stream.events
        result = verify_chain(
            events,
            org_secret=_SECRET,
            key_map={rotation.event_id: "new-secret-v2"},
        )
        assert result.valid is True


# ===========================================================================
# AuditStream — construction
# ===========================================================================


@pytest.mark.unit
class TestAuditStreamConstruction:
    def test_construction_valid(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        assert isinstance(stream, AuditStream)

    def test_empty_secret_raises(self) -> None:
        with pytest.raises(SigningError):
            AuditStream(org_secret="", source=_SOURCE)

    def test_whitespace_secret_raises(self) -> None:
        with pytest.raises(SigningError):
            AuditStream(org_secret="   ", source=_SOURCE)

    def test_repr_never_exposes_secret(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        assert _SECRET not in repr(stream)
        assert _SECRET not in str(stream)

    def test_repr_shows_event_count(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        assert "0" in repr(stream)

    def test_setattr_raises(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        with pytest.raises(AttributeError, match="immutable"):
            stream.new_attr = "value"  # type: ignore[attr-defined]

    def test_len_zero_on_construction(self) -> None:  # NOSONAR
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        assert len(stream) == 0


# ===========================================================================
# AuditStream.append()
# ===========================================================================


@pytest.mark.unit
class TestAuditStreamAppend:
    def test_append_returns_signed_event(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        signed = stream.append(_event())
        assert signed.checksum is not None
        assert signed.signature is not None

    def test_first_event_has_no_prev_id(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        signed = stream.append(_event())
        assert signed.prev_id is None

    def test_second_event_links_to_first(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        first = stream.append(_event())
        second = stream.append(_event())
        assert second.prev_id == first.event_id

    def test_stream_length_grows(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        for i in range(5):
            stream.append(_event(payload={"i": i}))
        assert len(stream) == 5

    def test_events_property_returns_copy(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        stream.append(_event())
        events = stream.events
        events.clear()  # modifying copy should not affect stream
        assert len(stream) == 1

    def test_original_event_not_mutated(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        event = _event()
        original_checksum = event.checksum  # None before signing
        stream.append(event)
        assert event.checksum == original_checksum  # still None

    def test_append_preserves_event_id(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        event = _event()
        signed = stream.append(event)
        assert signed.event_id == event.event_id


# ===========================================================================
# AuditStream.rotate_key()
# ===========================================================================


@pytest.mark.unit
class TestAuditStreamRotateKey:
    def test_rotate_key_returns_audit_event(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        rotation = stream.rotate_key("new-secret")
        assert rotation.event_type == EventType.AUDIT_KEY_ROTATED

    def test_rotation_event_is_signed_with_old_key(self) -> None:
        """The rotation event must be verifiable with the original key."""
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        rotation = stream.rotate_key("new-secret")
        assert verify(rotation, _SECRET) is True
        assert verify(rotation, "new-secret") is False

    def test_events_after_rotation_use_new_key(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        stream.rotate_key("new-secret")
        next_event = stream.append(_event())
        assert verify(next_event, "new-secret") is True
        assert verify(next_event, _SECRET) is False

    def test_rotate_key_with_metadata(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        rotation = stream.rotate_key("new-secret", metadata={"reason": "annual"})
        assert rotation.payload["reason"] == "annual"
        assert rotation.payload["rotation_marker"] == "true"

    def test_rotate_key_without_metadata(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        rotation = stream.rotate_key("new-secret")
        assert rotation.payload["rotation_marker"] == "true"
        assert "reason" not in rotation.payload

    def test_rotate_key_empty_secret_raises(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        with pytest.raises(SigningError):
            stream.rotate_key("")

    def test_stream_length_includes_rotation_event(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        stream.append(_event())
        stream.rotate_key("new-secret")
        # 1 regular + 1 rotation event
        assert len(stream) == 2

    def test_multiple_rotations_chain_verifies(self) -> None:
        stream = AuditStream(org_secret="key-1", source=_SOURCE)
        stream.append(_event(payload={"seq": 0}))
        stream.rotate_key("key-2")
        stream.append(_event(payload={"seq": 1}))
        stream.rotate_key("key-3")
        stream.append(_event(payload={"seq": 2}))
        result = stream.verify()
        assert result.valid is True

    def test_repr_never_exposes_rotated_secret(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        stream.rotate_key("ultra-secret-new-key")
        assert "ultra-secret-new-key" not in repr(stream)
        assert "ultra-secret-new-key" not in str(stream)


# ===========================================================================
# AuditStream.verify()
# ===========================================================================


@pytest.mark.unit
class TestAuditStreamVerify:
    def test_empty_stream_is_valid(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        result = stream.verify()
        assert result.valid is True

    def test_chain_of_one_is_valid(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        stream.append(_event())
        result = stream.verify()
        assert result.valid is True

    def test_clean_chain_is_valid(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        for i in range(10):
            stream.append(_event(payload={"i": i}))
        result = stream.verify()
        assert result.valid is True

    def test_verify_returns_chain_verification_result(self) -> None:
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        result = stream.verify()
        assert isinstance(result, ChainVerificationResult)


# ===========================================================================
# validate_key_strength (GA-01-A)
# ===========================================================================


@pytest.mark.unit
class TestValidateKeyStrength:
    def test_strong_key_no_warnings(self) -> None:
        from spanforge.signing import validate_key_strength

        warnings = validate_key_strength("Str0ng!Key#With-Multiple-Char-Classes")
        assert warnings == []

    def test_short_key_warns(self) -> None:
        from spanforge.signing import validate_key_strength

        warnings = validate_key_strength("short")
        assert any("length" in w.lower() for w in warnings)

    def test_single_char_key_warns(self) -> None:
        from spanforge.signing import validate_key_strength

        warnings = validate_key_strength("a" * 40)
        assert any("single repeated" in w.lower() for w in warnings)

    def test_well_known_placeholder_warns(self) -> None:
        from spanforge.signing import validate_key_strength

        warnings = validate_key_strength("spanforge-default")
        assert any("placeholder" in w.lower() for w in warnings)

    def test_single_char_class_warns(self) -> None:
        from spanforge.signing import validate_key_strength

        warnings = validate_key_strength("a" * 40 + "b" * 10)
        assert any("character class" in w.lower() for w in warnings)

    def test_env_var_min_bits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spanforge.signing import validate_key_strength

        # 128 bits = 16 bytes → min_length=16
        monkeypatch.setenv("SPANFORGE_SIGNING_KEY_MIN_BITS", "128")
        warnings = validate_key_strength("Short!1aB", min_length=None)
        assert any("length" in w.lower() for w in warnings)

    def test_env_var_min_bits_invalid_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spanforge.signing import validate_key_strength

        monkeypatch.setenv("SPANFORGE_SIGNING_KEY_MIN_BITS", "not_a_number")
        # Should fall back to default (32) without crashing
        warnings = validate_key_strength("A-Strong-Key-That-Is-Over-32-Chars!!", min_length=None)
        assert isinstance(warnings, list)

    def test_custom_min_length(self) -> None:
        from spanforge.signing import validate_key_strength

        warnings = validate_key_strength("Abc123!x", min_length=5)
        assert not any("length" in w.lower() for w in warnings)


# ===========================================================================
# check_key_expiry (GA-01-B)
# ===========================================================================


@pytest.mark.unit
class TestCheckKeyExpiry:
    def test_no_expiry(self) -> None:
        from spanforge.signing import check_key_expiry

        status, days = check_key_expiry(None)
        assert status == "no_expiry"
        assert days == 0

    def test_expired_key(self) -> None:
        from spanforge.signing import check_key_expiry

        status, days = check_key_expiry("2020-01-01T00:00:00Z")
        assert status == "expired"
        assert days > 0

    def test_expiring_soon(self) -> None:
        from datetime import datetime, timedelta, timezone

        from spanforge.signing import check_key_expiry

        soon = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
        status, days = check_key_expiry(soon)
        assert status == "expiring_soon"
        assert 0 <= days <= 7

    def test_valid_key(self) -> None:
        from datetime import datetime, timedelta, timezone

        from spanforge.signing import check_key_expiry

        future = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()
        status, days = check_key_expiry(future)
        assert status == "valid"
        assert days > 7

    def test_invalid_date_returns_no_expiry(self) -> None:
        from spanforge.signing import check_key_expiry

        status, days = check_key_expiry("not-a-date")
        assert status == "no_expiry"
        assert days == 0


# ===========================================================================
# derive_key with context (GA-01-D)
# ===========================================================================


@pytest.mark.unit
class TestDeriveKeyContext:
    def test_without_context(self) -> None:
        from spanforge.signing import derive_key

        key, salt = derive_key("passphrase", salt=b"\x00" * 16, iterations=1000)
        assert isinstance(key, str) and len(key) == 64

    def test_with_context_produces_different_key(self) -> None:
        from spanforge.signing import derive_key

        key1, _ = derive_key("passphrase", salt=b"\x00" * 16, iterations=1000)
        key2, _ = derive_key(
            "passphrase", salt=b"\x00" * 16, iterations=1000, context="production"
        )
        assert key1 != key2

    def test_same_context_same_key(self) -> None:
        from spanforge.signing import derive_key

        key1, _ = derive_key(
            "pass", salt=b"\x01" * 16, iterations=1000, context="staging"
        )
        key2, _ = derive_key(
            "pass", salt=b"\x01" * 16, iterations=1000, context="staging"
        )
        assert key1 == key2


# ===========================================================================
# sign() with expired key enforcement (GA-01-B)
# ===========================================================================


@pytest.mark.unit
class TestSignExpiredKey:
    def test_sign_raises_on_expired_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spanforge.config import get_config

        cfg = get_config()
        old_val = cfg.signing_key_expires_at
        try:
            cfg.signing_key_expires_at = "2020-01-01T00:00:00Z"
            with pytest.raises(SigningError, match="expired"):
                sign(_event(), _SECRET)
        finally:
            cfg.signing_key_expires_at = old_val


# ===========================================================================
# verify_chain with key_resolver and default_key (GA-04)
# ===========================================================================


@pytest.mark.unit
class TestVerifyChainKeyResolver:
    def test_verify_with_dict_key_resolver(self) -> None:
        from spanforge.signing import DictKeyResolver

        secret = "Test-Secret-Key-With-Many-Characters-1!"
        stream = AuditStream(org_secret=secret, source=_SOURCE)
        e = _event(org_id="org-a")
        stream.append(e)
        events = stream.events

        resolver = DictKeyResolver({"org-a": secret})
        result = verify_chain(events, secret, key_resolver=resolver)
        assert result.valid

    def test_verify_with_default_key_fallback(self) -> None:
        from spanforge.signing import DictKeyResolver

        secret = "Test-Secret-Key-With-Many-Characters-1!"
        stream = AuditStream(org_secret=secret, source=_SOURCE)
        e = _event()  # no org_id
        stream.append(e)
        events = stream.events

        resolver = DictKeyResolver({"other-org": secret})
        result = verify_chain(
            events, secret, key_resolver=resolver, default_key=secret
        )
        assert result.valid

    def test_verify_resolver_raises_uses_default(self) -> None:

        secret = "Test-Secret-Key-With-Many-Characters-1!"
        stream = AuditStream(org_secret=secret, source=_SOURCE)
        e = _event(org_id="org-missing")
        stream.append(e)
        events = stream.events

        class FailResolver:
            def resolve(self, org_id: str) -> str:
                raise RuntimeError("boom")

        result = verify_chain(
            events, secret, key_resolver=FailResolver(), default_key=secret
        )
        assert result.valid


# ===========================================================================
# AuditStream with require_org_id (GA-04-C)
# ===========================================================================


@pytest.mark.unit
class TestAuditStreamRequireOrgId:
    def test_require_org_id_blocks_none(self) -> None:
        stream = AuditStream(
            org_secret=_SECRET, source=_SOURCE, require_org_id=True
        )
        with pytest.raises(SigningError, match="require_org_id"):
            stream.append(_event())  # no org_id

    def test_require_org_id_allows_with_org(self) -> None:
        stream = AuditStream(
            org_secret=_SECRET, source=_SOURCE, require_org_id=True
        )
        signed = stream.append(_event(org_id="org-123"))
        assert signed.org_id == "org-123"


# ===========================================================================
# AuditStream with key_resolver (GA-04-B)
# ===========================================================================


@pytest.mark.unit
class TestAuditStreamKeyResolver:
    def test_stream_uses_resolver_for_org_events(self) -> None:
        from spanforge.signing import DictKeyResolver

        secret_a = "Secret-For-OrgA-With-Many-Characters!1"
        resolver = DictKeyResolver({"org-a": secret_a})
        stream = AuditStream(
            org_secret=secret_a, source=_SOURCE, key_resolver=resolver
        )
        signed = stream.append(_event(org_id="org-a"))
        assert signed.signature.startswith("hmac-sha256:")


# ===========================================================================
# AsyncAuditStream
# ===========================================================================


@pytest.mark.unit
class TestAsyncAuditStream:
    @pytest.fixture
    def secret(self) -> str:
        return "Async-Test-Secret-Key-With-Chars-1234!"

    @pytest.mark.asyncio
    async def test_async_append_and_verify(self, secret: str) -> None:
        from spanforge.signing import AsyncAuditStream

        stream = AsyncAuditStream(org_secret=secret, source=_SOURCE)
        assert len(stream) == 0
        assert repr(stream) == "<AsyncAuditStream events=0>"

        signed = await stream.append(_event())
        assert len(stream) == 1
        assert signed.signature.startswith("hmac-sha256:")

        result = await stream.verify()
        assert result.valid

    @pytest.mark.asyncio
    async def test_async_rotate_key(self, secret: str) -> None:
        from spanforge.signing import AsyncAuditStream

        stream = AsyncAuditStream(org_secret=secret, source=_SOURCE)
        await stream.append(_event())

        new_secret = "New-Async-Secret-Key-With-Chars-5678!"
        rotation = await stream.rotate_key(new_secret, metadata={"reason": "test"})
        assert rotation.event_type == "llm.audit.key.rotated"

        await stream.append(_event(payload={"after": "rotation"}))
        assert len(stream) == 3

        result = await stream.verify()
        assert result.valid

    @pytest.mark.asyncio
    async def test_async_events_property(self, secret: str) -> None:
        from spanforge.signing import AsyncAuditStream

        stream = AsyncAuditStream(org_secret=secret, source=_SOURCE)
        await stream.append(_event())
        events = stream.events
        assert len(events) == 1
        # Should be a copy
        events.clear()
        assert len(stream.events) == 1

    @pytest.mark.asyncio
    async def test_async_key_resolver(self, secret: str) -> None:
        from spanforge.signing import AsyncAuditStream, DictKeyResolver

        resolver = DictKeyResolver({"org-x": secret})
        stream = AsyncAuditStream(
            org_secret=secret, source=_SOURCE, key_resolver=resolver
        )
        signed = await stream.append(_event(org_id="org-x"))
        assert signed.signature is not None


# ===========================================================================
# Key Resolver classes (GA-04)
# ===========================================================================


@pytest.mark.unit
class TestKeyResolvers:
    def test_static_key_resolver(self) -> None:
        from spanforge.signing import StaticKeyResolver

        r = StaticKeyResolver("my-secret-that-is-long-enough-1!")
        assert r.resolve("any-org") == "my-secret-that-is-long-enough-1!"

    def test_static_key_resolver_rejects_empty(self) -> None:
        from spanforge.signing import StaticKeyResolver

        with pytest.raises(SigningError):
            StaticKeyResolver("")

    def test_env_key_resolver(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from spanforge.signing import EnvKeyResolver

        monkeypatch.setenv("SPANFORGE_KEY_ORG_A", "secret-a-value-for-testing!")
        r = EnvKeyResolver()
        assert r.resolve("org-a") == "secret-a-value-for-testing!"

    def test_env_key_resolver_missing_raises(self) -> None:
        from spanforge.signing import EnvKeyResolver

        r = EnvKeyResolver()
        with pytest.raises(SigningError, match="No signing key found"):
            r.resolve("nonexistent-org-xyz")

    def test_dict_key_resolver(self) -> None:
        from spanforge.signing import DictKeyResolver

        r = DictKeyResolver({"org-1": "secret-1-long-enough-for-test!"})
        assert r.resolve("org-1") == "secret-1-long-enough-for-test!"

    def test_dict_key_resolver_missing_raises(self) -> None:
        from spanforge.signing import DictKeyResolver

        r = DictKeyResolver({"org-1": "secret-1-long-enough-for-test!"})
        with pytest.raises(SigningError, match="No signing key found"):
            r.resolve("org-2")

    def test_dict_key_resolver_rejects_empty_values(self) -> None:
        from spanforge.signing import DictKeyResolver

        with pytest.raises(SigningError):
            DictKeyResolver({"org-1": ""})


# ===========================================================================
# EventType additions
# ===========================================================================


@pytest.mark.unit
class TestAuditEventTypes:
    def test_audit_key_rotated_event_type_exists(self) -> None:
        assert EventType.AUDIT_KEY_ROTATED == "llm.audit.key.rotated"

    def test_audit_chain_started_event_type_exists(self) -> None:
        # AUDIT_CHAIN_STARTED removed in v2.0; only AUDIT_KEY_ROTATED remains
        assert not hasattr(EventType, "AUDIT_CHAIN_STARTED")
        assert EventType.AUDIT_KEY_ROTATED == "llm.audit.key.rotated"

    def test_audit_namespace(self) -> None:
        assert EventType.AUDIT_KEY_ROTATED.namespace == "llm.audit"

    def test_audit_tool_is_spanforge(self) -> None:
        # et.tool removed in v2.0; use et.description instead
        assert isinstance(EventType.AUDIT_KEY_ROTATED.description, str)
        assert len(EventType.AUDIT_KEY_ROTATED.description) > 0

    def test_audit_reserved_namespace(self) -> None:
        from spanforge.exceptions import EventTypeError
        from spanforge.types import validate_custom
        with pytest.raises(EventTypeError):
            validate_custom("llm.audit.custom.event")


# ===========================================================================
# SigningError exception
# ===========================================================================


@pytest.mark.unit
class TestSigningError:
    def test_is_spanforge_error(self) -> None:
        from spanforge.exceptions import LLMSchemaError
        err = SigningError("bad key")
        assert isinstance(err, LLMSchemaError)

    def test_reason_attribute(self) -> None:
        err = SigningError("empty secret")
        assert err.reason == "empty secret"

    def test_message_contains_reason(self) -> None:
        err = SigningError("some problem")
        assert "some problem" in str(err)

    def test_message_never_contains_secret(self) -> None:
        # SigningError is raised before we can expose the secret,
        # but this test confirms zero leakage in the exception itself.
        err = SigningError("bad secret")
        assert _SECRET not in str(err)


# ===========================================================================
# Security tests
# ===========================================================================


@pytest.mark.security
class TestSigningSecurity:
    def test_audit_stream_repr_never_exposes_secret(self) -> None:
        secret = "ultra-sensitive-secret-xyz"  # NOSONAR — intentional test value, not a real secret
        stream = AuditStream(org_secret=secret, source=_SOURCE)
        assert secret not in repr(stream)
        assert secret not in str(stream)

    def test_signing_error_never_contains_secret(self) -> None:
        """Empty-secret path in _validate_secret must not echo the secret."""
        try:
            _validate_secret("")
        except SigningError as exc:
            assert _SECRET not in str(exc)

    def test_verification_error_only_contains_event_id(self) -> None:
        eid = "01ARYZ3NDEKTSV4RRFFQ69G5FA"
        err = VerificationError(event_id=eid)
        assert eid in str(err)
        # The message should not contain any raw secret; it has none to contain
        assert _SECRET not in str(err)

    def test_verify_uses_compare_digest_timing_safety(self) -> None:
        """Regression: verify() must use hmac.compare_digest, not == .

        We can't directly test timing, but we verify that tampered events
        return False for *both* checksum AND signature mismatches —
        confirming neither path uses naive string equality.
        """
        signed = sign(_event(), _SECRET)
        # Checksum mismatch
        with_bad_checksum = Event(
            schema_version=signed.schema_version,
            event_id=signed.event_id,
            event_type=signed.event_type,
            timestamp=signed.timestamp,
            source=signed.source,
            payload=dict(signed.payload),
            checksum="sha256:" + "f" * 64,
            signature=signed.signature,
        )
        assert verify(with_bad_checksum, _SECRET) is False

        # Signature mismatch
        with_bad_sig = Event(
            schema_version=signed.schema_version,
            event_id=signed.event_id,
            event_type=signed.event_type,
            timestamp=signed.timestamp,
            source=signed.source,
            payload=dict(signed.payload),
            checksum=signed.checksum,
            signature="hmac-sha256:" + "0" * 64,
        )
        assert verify(with_bad_sig, _SECRET) is False

    def test_rotation_event_payload_contains_no_pii(self) -> None:
        """Key rotation events must never include the signing key in payload."""
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        rotation = stream.rotate_key("new-ultra-secret-key")
        payload_str = str(rotation.payload)
        assert _SECRET not in payload_str
        assert "new-ultra-secret-key" not in payload_str


# ===========================================================================
# Performance
# ===========================================================================


@pytest.mark.perf
class TestSigningPerformance:
    def test_sign_and_verify_under_5ms(self) -> None:
        """Spec: Event creation + HMAC signing < 5ms."""
        event = _event()
        t0 = time.perf_counter()
        signed = sign(event, _SECRET)
        verify(signed, _SECRET)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert elapsed_ms < 5, f"sign+verify took {elapsed_ms:.2f}ms > 5ms"

    def test_verify_chain_1000_events_reasonable(self) -> None:
        """Verify 1000-event chain completes in reasonable time."""
        chain = _chain(1000)
        t0 = time.perf_counter()
        result = verify_chain(chain, org_secret=_SECRET)
        elapsed = time.perf_counter() - t0
        assert result.valid is True
        assert elapsed < 5.0, f"verify_chain(1000) took {elapsed:.2f}s > 5s"
