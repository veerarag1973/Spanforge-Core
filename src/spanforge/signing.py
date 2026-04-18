"""HMAC-SHA256 signing and tamper-evident audit chain for spanforge.

Provides compliance-grade audit log integrity without requiring a blockchain
or external service.  All cryptography uses pure Python stdlib — no network
calls, no external dependencies.

Signing algorithm
-----------------

Each event is signed in two steps::

    checksum  = "sha256:"      + sha256(canonical_payload_json).hexdigest()
    sig_input = event_id + "|" + checksum + "|" + (prev_id or "")
    signature = "hmac-sha256:" + HMAC-SHA256(sig_input, org_secret).hexdigest()

The *canonical payload JSON* uses ``sort_keys=True, separators=(",", ":")``
(compact, no whitespace) so the same payload always produces the same checksum
regardless of dict insertion order or Python version.

Chain linkage
-------------

Each event (except the first) stores the ``prev_id`` of its predecessor.
A missing or mismatched ``prev_id`` indicates a deleted or reordered event::

    events[n].prev_id == events[n-1].event_id   # must hold for every n > 0

Key rotation
------------

The HMAC key can be rotated mid-chain using :meth:`AuditStream.rotate_key`.
A key-rotation event (``EventType.AUDIT_KEY_ROTATED``) is inserted into the
chain, signed with the *current* key.  All subsequent events are signed with
the *new* key.  :func:`verify_chain` accepts a ``key_map`` argument that maps
rotation event IDs to the corresponding new secrets, enabling independent
chain verification across rotation boundaries.

Security requirements
---------------------

*   The ``org_secret`` **never** appears in exception messages, ``__repr__``,
    ``__str__``, or ``__reduce__`` output.
*   Signing failures always raise :exc:`~spanforge.exceptions.SigningError`
    — never silently pass.
*   Empty or whitespace-only secrets are rejected immediately.
*   :func:`verify` uses :func:`hmac.compare_digest` for all comparisons to
    prevent timing-based side-channel attacks.

Usage
-----
::

    from spanforge import Event, EventType
    from spanforge.signing import sign, verify, verify_chain, AuditStream

    # Sign a single event
    signed = sign(event, org_secret="corp-key-001")
    assert verify(signed, org_secret="corp-key-001")

    # Build a verifiable chain
    stream = AuditStream(org_secret="corp-key-001", source="audit-daemon@1.0.0")
    for evt in raw_events:
        stream.append(evt)

    result = stream.verify()
    # result.valid          → True
    # result.first_tampered → None
    # result.gaps           → []
    # result.tampered_count → 0
"""

from __future__ import annotations

import hashlib
import hmac as _hmac
import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from typing import Protocol as _Protocol
from typing import runtime_checkable as _runtime_checkable

from spanforge.exceptions import SigningError, VerificationError

if TYPE_CHECKING:
    import threading
    from collections.abc import Sequence

    from spanforge.event import Event

__all__ = [
    "AsyncAuditStream",
    "AuditStream",
    "ChainVerificationResult",
    "DictKeyResolver",
    "EnvKeyResolver",
    "KeyResolver",
    "StaticKeyResolver",
    "_event_mentions_subject",
    "assert_verified",
    "check_key_expiry",
    "derive_key",
    "sign",
    "validate_key_strength",
    "verify",
    "verify_chain",
]


# ---------------------------------------------------------------------------
# ChainVerificationResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChainVerificationResult:
    """Immutable result returned by :func:`verify_chain` and :meth:`AuditStream.verify`.

    Attributes:
        valid:              ``True`` only if **all** signatures are valid, **no**
                            ``prev_id`` linkage gaps exist, and no tampering was
                            found.
        first_tampered:     The ``event_id`` of the first event whose signature
                            did not verify, or ``None`` if the chain is clean.
        gaps:               List of ``event_id`` values where the expected
                            ``prev_id`` linkage is broken — each entry represents
                            a potential deletion or reordering.
        tampered_count:     Total number of events with invalid signatures across
                            the entire chain.
        tombstone_count:    Number of ``AUDIT_TOMBSTONE`` events found in the chain.
        tombstone_event_ids: Event IDs of all tombstone events.
    """

    valid: bool
    first_tampered: str | None
    gaps: list[str]
    tampered_count: int
    tombstone_count: int = 0
    tombstone_event_ids: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal crypto helpers
# ---------------------------------------------------------------------------


def _canonical_payload_bytes(payload: dict[str, Any]) -> bytes:
    """Return compact, sorted UTF-8 JSON bytes for *payload*.

    Uses ``sort_keys=True`` for determinism across Python versions and
    ``separators=(",", ":")`` to eliminate optional whitespace.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _compute_checksum(payload: dict[str, Any]) -> str:
    """Return ``"sha256:<hex>"`` digest of the canonical payload JSON."""
    digest = hashlib.sha256(_canonical_payload_bytes(payload)).hexdigest()
    return f"sha256:{digest}"


def _compute_signature(
    event_id: str,
    checksum: str,
    prev_id: str | None,
    org_secret: str,
) -> str:
    """Return ``"hmac-sha256:<hex>"`` signature.

    Message is ``"{event_id}|{checksum}|{prev_id or ''}"`` encoded as UTF-8.
    """
    msg = f"{event_id}|{checksum}|{prev_id or ''}"
    mac = _hmac.new(
        key=org_secret.encode("utf-8"),
        msg=msg.encode("utf-8"),
        digestmod=hashlib.sha256,
    )
    return f"hmac-sha256:{mac.hexdigest()}"


def _validate_secret(org_secret: str) -> None:
    """Raise :exc:`~spanforge.exceptions.SigningError` if *org_secret* is empty or whitespace-only.

    Security: the value of *org_secret* is **never** included in the error
    message.
    """
    if not isinstance(org_secret, str) or not org_secret.strip():
        raise SigningError("org_secret must be a non-empty, non-whitespace string")


_MIN_KEY_LENGTH = 32  # minimum bytes (256-bit) for production keys


def validate_key_strength(org_secret: str, *, min_length: int | None = None) -> list[str]:
    """Check the signing key against strength requirements.

    Returns a list of warning strings.  Empty list = strong key.

    Checks:
    * Minimum length (default 32 chars / 256-bit, or ``SPANFORGE_SIGNING_KEY_MIN_BITS`` env var)
    * Not all-same character
    * Not a well-known placeholder
    * Mixed character classes (upper, lower, digit, special)

    Args:
        org_secret: The signing key to check.
        min_length: Minimum key length in characters.  When ``None``, uses
                    ``SPANFORGE_SIGNING_KEY_MIN_BITS / 8`` or falls back to 32.

    Returns:
        List of human-readable warning strings.  Empty if key is strong.
    """
    import os as _os

    if min_length is None:
        raw_bits = _os.environ.get("SPANFORGE_SIGNING_KEY_MIN_BITS")
        if raw_bits is not None:
            try:
                min_length = max(1, int(raw_bits) // 8)
            except (ValueError, TypeError):
                min_length = _MIN_KEY_LENGTH
        else:
            min_length = _MIN_KEY_LENGTH

    warnings: list[str] = []
    if len(org_secret) < min_length:
        warnings.append(f"Key length {len(org_secret)} < minimum {min_length} characters")
    if len(set(org_secret)) == 1:
        warnings.append("Key consists of a single repeated character")
    _weak_keys = {
        "spanforge-default",
        "secret",
        "password",
        "changeme",
        "test",
        "key",
        "demo",
    }
    if org_secret.lower().strip() in _weak_keys:
        warnings.append("Key matches a well-known placeholder")
    # Mixed character class check: at least 2 of (upper, lower, digit, special)
    has_upper = any(c.isupper() for c in org_secret)
    has_lower = any(c.islower() for c in org_secret)
    has_digit = any(c.isdigit() for c in org_secret)
    has_special = any(not c.isalnum() for c in org_secret)
    char_classes = sum([has_upper, has_lower, has_digit, has_special])
    if char_classes < 2:
        warnings.append(
            f"Key uses only {char_classes} character class(es); "
            "recommend at least 2 (upper, lower, digit, special)"
        )
    return warnings


def check_key_expiry(expires_at: str | None) -> tuple[str, int]:
    """Check the signing key expiry status.

    Args:
        expires_at: ISO-8601 datetime string, or ``None`` (no expiry).

    Returns:
        A tuple of ``(status, days)`` where *status* is one of:
        - ``"no_expiry"`` — no expiration configured (days=0)
        - ``"expired"`` — key has expired (days = days since expiry)
        - ``"expiring_soon"`` — key expires within 7 days (days = days remaining)
        - ``"valid"`` — key is valid (days = days remaining)
    """
    if expires_at is None:
        return ("no_expiry", 0)
    from datetime import datetime, timezone

    try:
        expiry = datetime.fromisoformat(expires_at)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = expiry - now
        days = delta.days
        if days < 0:
            return ("expired", abs(days))
        if days <= 7:
            return ("expiring_soon", days)
    except (ValueError, TypeError):
        return ("no_expiry", 0)
    else:
        return ("valid", days)


def derive_key(
    passphrase: str,
    salt: bytes | None = None,
    iterations: int = 600_000,
    *,
    context: str | None = None,
) -> tuple[str, bytes]:
    """Derive a signing key from a passphrase using PBKDF2-HMAC-SHA256.

    Args:
        passphrase: The human-memorable passphrase.
        salt:       16-byte salt.  A random salt is generated if ``None``.
        iterations: PBKDF2 iteration count (default 600,000 per OWASP 2023).
        context:    Optional context string for environment isolation.
                    When provided, it is appended to the passphrase
                    (``passphrase + "|" + context``) before derivation,
                    ensuring the same passphrase yields different keys
                    for different environments (e.g. ``"staging"`` vs
                    ``"production"``).

    Returns:
        Tuple of ``(derived_key_hex, salt_bytes)``.

    Example::

        key, salt = derive_key("my strong passphrase", context="production")
        # Store salt alongside the config; use key as org_secret.
    """
    import os as _os

    if salt is None:
        salt = _os.urandom(16)
    effective_passphrase = passphrase
    if context:
        effective_passphrase = f"{passphrase}|{context}"
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        effective_passphrase.encode("utf-8"),
        salt,
        iterations,
        dklen=32,
    )
    return derived.hex(), salt


# ---------------------------------------------------------------------------
# Public signing API
# ---------------------------------------------------------------------------


def sign(
    event: Event,
    org_secret: str,
    prev_event: Event | None = None,
) -> Event:
    """Sign *event* and return a new event with ``checksum``, ``signature``, and ``prev_id`` set.

    The original *event* is not mutated — a new
    :class:`~spanforge.event.Event` instance is returned.

    Signing steps::

        checksum  = sha256(canonical_payload_json)
        sig_input = event_id + "|" + checksum + "|" + (prev_id or "")
        signature = HMAC-SHA256(sig_input, org_secret)

    Args:
        event:       The event to sign.
        org_secret:  HMAC signing key (non-empty string).
        prev_event:  The immediately preceding event in the audit chain, or
                     ``None`` if *event* is the first in the chain.

    Returns:
        A new :class:`~spanforge.event.Event` with ``checksum``, ``signature``,
        and (if *prev_event* is given) ``prev_id`` populated.

    Raises:
        SigningError: If *org_secret* is empty or whitespace-only.

    Example::

        signed = sign(event, org_secret="my-key")
        assert signed.checksum.startswith("sha256:")
        assert signed.signature.startswith("hmac-sha256:")
    """
    # Deferred import to avoid circular dependency at module-load time.
    from spanforge.event import Event

    _validate_secret(org_secret)

    # GA-01-B: Check key expiry before signing.
    try:
        from spanforge.config import get_config

        _cfg = get_config()
        if _cfg.signing_key_expires_at:
            _expiry_status, _expiry_days = check_key_expiry(_cfg.signing_key_expires_at)
            if _expiry_status == "expired":
                raise SigningError(
                    f"Signing key expired {_expiry_days} day(s) ago — rotate key before signing"
                )
    except ImportError:
        pass  # config module not available — skip enforcement

    # GA-04: Enforce require_org_id when configured.
    try:
        from spanforge.config import get_config as _get_config

        if _get_config().require_org_id and not getattr(event, "org_id", None):
            raise SigningError("require_org_id is enabled but event.org_id is None or empty")
    except ImportError:
        pass  # config module not available — skip enforcement

    prev_id: str | None = prev_event.event_id if prev_event is not None else None
    checksum = _compute_checksum(dict(event.payload))
    signature = _compute_signature(event.event_id, checksum, prev_id, org_secret)

    return Event(
        schema_version=event.schema_version,
        event_id=event.event_id,
        event_type=event.event_type,
        timestamp=event.timestamp,
        source=event.source,
        payload=dict(event.payload),
        trace_id=event.trace_id,
        span_id=event.span_id,
        parent_span_id=event.parent_span_id,
        org_id=event.org_id,
        team_id=event.team_id,
        actor_id=event.actor_id,
        session_id=event.session_id,
        tags=event.tags,
        checksum=checksum,
        signature=signature,
        prev_id=prev_id,
    )


def verify(event: Event, org_secret: str) -> bool:
    """Verify the checksum and HMAC signature of a single signed event.

    Uses :func:`hmac.compare_digest` for both comparisons to guard against
    timing-based side-channel attacks.

    Args:
        event:      The event to verify.
        org_secret: HMAC signing key used when the event was signed.

    Returns:
        ``True`` if both the checksum and signature are cryptographically
        valid.  ``False`` if either fails (tampered payload, wrong key, or
        missing checksum/signature).

    Raises:
        SigningError: If *org_secret* is empty or whitespace-only.

    Note:
        This function deliberately returns ``False`` rather than raising for
        tampered events — :func:`verify_chain` calls it in a loop and needs
        to accumulate all failures.  For the strict raising variant see
        :func:`assert_verified`.

    Example::

        if not verify(event, org_secret="my-key"):
            raise RuntimeError(f"Tampered event: {event.event_id}")
    """
    _validate_secret(org_secret)

    if event.checksum is None or event.signature is None:
        return False

    expected_checksum = _compute_checksum(dict(event.payload))
    if not _hmac.compare_digest(event.checksum, expected_checksum):
        return False

    expected_signature = _compute_signature(
        event.event_id, event.checksum, event.prev_id, org_secret
    )
    return _hmac.compare_digest(event.signature, expected_signature)


def assert_verified(event: Event, org_secret: str) -> None:
    """Assert that *event* passes cryptographic verification.

    Strict variant of :func:`verify` that raises instead of returning
    ``False``.

    Args:
        event:      The event to verify.
        org_secret: HMAC signing key used when the event was signed.

    Raises:
        VerificationError: If :func:`verify` returns ``False``.
        SigningError:      If *org_secret* is empty or whitespace-only.

    Example::

        assert_verified(event, org_secret="my-key")   # raises on tamper
    """
    if not verify(event, org_secret):
        raise VerificationError(event_id=event.event_id)


def _check_event_signature(
    event: Event,
    current_secret: str,
    first_tampered: str | None,
    tampered_count: int,
) -> tuple[str | None, int]:
    """Check signature validity; returns updated (first_tampered, tampered_count)."""
    if not verify(event, current_secret):
        tampered_count += 1
        if first_tampered is None:
            first_tampered = event.event_id
    return first_tampered, tampered_count


def _check_chain_linkage(
    event: Event,
    i: int,
    event_list: list[Event],
    gaps: list[str],
) -> None:
    """Check chain linkage; appends to gaps if a gap is detected."""
    if i == 0:
        if event.prev_id is not None:
            gaps.append(event.event_id)
    else:
        expected_prev = event_list[i - 1].event_id
        if event.prev_id != expected_prev:
            gaps.append(event.event_id)


def verify_chain(
    events: Sequence[Event],
    org_secret: str,
    key_map: dict[str, str] | None = None,
    *,
    key_resolver: KeyResolver | None = None,
    default_key: str | None = None,
) -> ChainVerificationResult:
    """Verify an entire ordered sequence of signed events as an audit chain.

    Performs three checks per event:

    1. **Signature validity** — recomputes checksum and HMAC; flags mismatches.
    2. **Chain linkage** — ``events[n].prev_id == events[n-1].event_id``.
    3. **Head integrity** — ``events[0].prev_id`` must be ``None`` (no missing
       predecessor); non-``None`` signals an undetected gap at the head.

    Key rotation
    ~~~~~~~~~~~~
    Pass ``key_map`` to handle chains that span a key rotation.  The dict maps
    a rotation event's ``event_id`` to the new secret that takes effect
    **after** that event is verified::

        result = verify_chain(events, org_secret="old-key",
                              key_map={"<rotation_event_id>": "new-key"})

    Multi-tenant verification
    ~~~~~~~~~~~~~~~~~~~~~~~~~
    Pass ``key_resolver`` to verify chains containing events from different
    orgs.  For each event with an ``org_id``, the resolver provides the
    corresponding secret.  Events without ``org_id`` use *default_key* (falls
    back to *org_secret*).

    Args:
        events:       Ordered sequence of events (earliest first).  May be
                      empty — returns ``valid=True`` with no failures.
        org_secret:   HMAC signing key for the first chain segment.
        key_map:      Optional ``{rotation_event_id: new_secret}`` dict
                      enabling multi-segment verification after key rotation.
        key_resolver: Optional :class:`KeyResolver` for per-org key resolution.
        default_key:  Fallback key for events without ``org_id`` when using
                      *key_resolver*.  Defaults to *org_secret*.

    Returns:
        A :class:`ChainVerificationResult` with ``valid``, ``first_tampered``,
        ``gaps``, and ``tampered_count``.

    Raises:
        SigningError: If *org_secret* (or any value in *key_map*) is empty.

    Example::

        result = verify_chain(signed_events, org_secret="my-key")
        if not result.valid:
            print(f"First tampered: {result.first_tampered}")
            print(f"Gaps (deleted events): {result.gaps}")
    """
    _validate_secret(org_secret)
    if key_map:
        for new_secret in key_map.values():
            _validate_secret(new_secret)

    _default_key = default_key if default_key is not None else org_secret
    current_secret = org_secret
    km = key_map or {}

    first_tampered: str | None = None
    gaps: list[str] = []
    tampered_count = 0
    tombstone_count = 0
    tombstone_event_ids: list[str] = []

    _tombstone_type = "llm.audit.tombstone"

    event_list = list(events)

    for i, event in enumerate(event_list):
        # Determine the secret to use for this event
        verify_secret = current_secret
        if key_resolver is not None:
            oid = getattr(event, "org_id", None)
            if oid:
                try:
                    verify_secret = key_resolver.resolve(oid)
                except Exception:
                    # If resolver fails, use default key
                    verify_secret = _default_key
            else:
                verify_secret = _default_key

        first_tampered, tampered_count = _check_event_signature(
            event, verify_secret, first_tampered, tampered_count
        )
        _check_chain_linkage(event, i, event_list, gaps)
        if event.event_id in km:
            current_secret = km[event.event_id]

        # Track tombstone events
        evt_type = str(event.event_type) if event.event_type else ""
        if evt_type == _tombstone_type:
            tombstone_count += 1
            tombstone_event_ids.append(event.event_id)

    valid = tampered_count == 0 and len(gaps) == 0
    return ChainVerificationResult(
        valid=valid,
        first_tampered=first_tampered,
        gaps=gaps,
        tampered_count=tampered_count,
        tombstone_count=tombstone_count,
        tombstone_event_ids=tombstone_event_ids,
    )


# ---------------------------------------------------------------------------
# Subject mention helper
# ---------------------------------------------------------------------------


def _event_mentions_subject(event: Event, subject_id: str) -> bool:
    """Return ``True`` if *event* contains *subject_id* in searchable fields.

    Scans ``actor_id``, ``session_id``, and flattened payload values.
    Uses **exact** match to avoid false positives from substring overlap.
    """
    if event.actor_id and event.actor_id == subject_id:
        return True
    if event.session_id and event.session_id == subject_id:
        return True
    # Scan payload values (shallow — one level deep)
    payload = event.payload or {}
    return any(isinstance(v, str) and v == subject_id for v in payload.values())


# ---------------------------------------------------------------------------
# GA-04: Multi-tenant Key Resolvers
# ---------------------------------------------------------------------------


@_runtime_checkable
class KeyResolver(_Protocol):
    """Protocol for resolving signing keys per-org in multi-tenant setups.

    Implementations must return a non-empty string secret for the given
    ``org_id``.  Raise :exc:`~spanforge.exceptions.SigningError` if the key
    cannot be resolved.
    """

    def resolve(self, org_id: str) -> str:
        """Return the signing secret for *org_id*."""
        ...  # pragma: no cover


class StaticKeyResolver:
    """Resolves every org to the same static key.

    Useful for single-tenant deployments or testing.
    """

    __slots__ = ("_secret",)

    def __init__(self, secret: str) -> None:
        _validate_secret(secret)
        self._secret = secret

    def resolve(self, org_id: str) -> str:
        """Return the static signing secret, ignoring org_id."""
        return self._secret


class EnvKeyResolver:
    """Resolves the signing key from an environment variable.

    The env var name is derived from the org_id:
    ``{prefix}{org_id.upper().replace('-', '_')}``.

    Args:
        prefix: Env var prefix (default ``"SPANFORGE_KEY_"``).
    """

    __slots__ = ("_prefix",)

    def __init__(self, prefix: str = "SPANFORGE_KEY_") -> None:
        self._prefix = prefix

    def resolve(self, org_id: str) -> str:
        """Look up the signing key from the environment variable for org_id."""
        import os as _os

        var_name = self._prefix + org_id.upper().replace("-", "_")
        secret = _os.environ.get(var_name, "")
        if not secret.strip():
            raise SigningError(
                f"No signing key found for org '{org_id}' (expected env var {var_name})"
            )
        return secret


class DictKeyResolver:
    """Resolves signing keys from an in-memory dictionary.

    Args:
        keys: Mapping of ``org_id`` → signing secret.
    """

    __slots__ = ("_keys",)

    def __init__(self, keys: dict[str, str]) -> None:
        for secret in keys.values():
            _validate_secret(secret)
        self._keys = dict(keys)

    def resolve(self, org_id: str) -> str:
        """Look up the signing key for org_id from the in-memory dictionary."""
        secret = self._keys.get(org_id)
        if not secret:
            raise SigningError(f"No signing key found for org '{org_id}' in key map")
        return secret


# ---------------------------------------------------------------------------
# AuditStream
# ---------------------------------------------------------------------------


class AuditStream:
    """Tamper-evident HMAC-signed audit chain stream.

    Sequential event stream that HMAC-signs every appended event and links
    them via ``prev_id``, forming a tamper-evident audit chain.

    The signing secret is **never** exposed in :func:`repr`, :func:`str`, or
    any exception message.

    Args:
        org_secret: HMAC signing key (non-empty string).
        source:     The ``source`` field used for auto-generated audit events
                    such as key-rotation events.  Must follow the
                    ``tool-name@x.y.z`` format accepted by
                    :class:`~spanforge.event.Event`.

    Raises:
        SigningError: If *org_secret* is empty or whitespace-only.

    Example::

        stream = AuditStream(org_secret="corp-key", source="audit-daemon@1.0.0")
        for event in events:
            stream.append(event)
        stream.rotate_key("corp-key-v2", metadata={"reason": "scheduled"})
        result = stream.verify()
        assert result.valid
    """

    _events: list[Event]
    _initial_secret: str
    _key_map: dict[str, str]
    _key_resolver: KeyResolver | None
    _lock: threading.RLock
    _org_secret: str
    _require_org_id: bool
    _source: str

    __slots__ = (
        "_events",
        "_initial_secret",
        "_key_map",
        "_key_resolver",
        "_lock",
        "_org_secret",
        "_require_org_id",
        "_source",
    )

    def __init__(
        self,
        org_secret: str,
        source: str,
        *,
        key_resolver: KeyResolver | None = None,
        require_org_id: bool = False,
    ) -> None:
        _validate_secret(org_secret)
        object.__setattr__(self, "_initial_secret", org_secret)
        object.__setattr__(self, "_org_secret", org_secret)
        object.__setattr__(self, "_source", source)
        object.__setattr__(self, "_events", [])
        # maps rotation_event_id → new_secret for verify()
        object.__setattr__(self, "_key_map", {})
        object.__setattr__(self, "_key_resolver", key_resolver)
        object.__setattr__(self, "_require_org_id", require_org_id)
        # Protects _events list and _org_secret during concurrent appends / rotations.
        object.__setattr__(self, "_lock", __import__("threading").RLock())

    def __setattr__(self, name: str, value: object) -> None:
        """Block external attribute mutation.

        Internal code uses :func:`object.__setattr__` directly.
        """
        raise AttributeError(
            f"AuditStream is immutable externally — attribute '{name}' cannot be set. "
            "Use append() or rotate_key() to modify the stream."
        )

    def __repr__(self) -> str:
        """Safe repr that never exposes the signing secret."""
        return f"<AuditStream events={len(self._events)}>"

    def __str__(self) -> str:
        return f"<AuditStream events={len(self._events)}>"

    def __len__(self) -> int:
        return len(self._events)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def events(self) -> list[Event]:
        """A read-only copy of all signed events in the stream.

        Returns a new list each call so callers cannot mutate the internal
        state.
        """
        return list(self._events)

    # ------------------------------------------------------------------
    # Mutation methods (guarded)
    # ------------------------------------------------------------------

    def append(self, event: Event) -> Event:
        """Sign *event*, link it to the chain, append, and return the signed event.

        The given *event* is not mutated.  A new
        :class:`~spanforge.event.Event` with ``checksum``, ``signature``, and
        ``prev_id`` set is returned **and** stored in the stream.

        Args:
            event: The unsigned (or partially signed) event to add.

        Returns:
            The freshly signed event with full chain linkage.

        Raises:
            SigningError: If the current signing key is somehow invalid
                          (should not happen if the stream was constructed
                          correctly).
        """
        with self._lock:
            # GA-04-C: Enforce require_org_id at the stream level.
            if self._require_org_id and not getattr(event, "org_id", None):
                raise SigningError("require_org_id is enabled but event.org_id is None or empty")
            # If a key_resolver is configured and the event has an org_id, use it.
            resolver: KeyResolver | None = self._key_resolver
            secret: str = self._org_secret
            if resolver is not None and getattr(event, "org_id", None):
                secret = resolver.resolve(event.org_id)
            events_list: list[Event] = self._events
            prev_event: Event | None = events_list[-1] if events_list else None
            # GA-06-A: Sign and append under the same lock to guarantee
            # prev_event linkage is never stale under concurrent appends.
            signed = sign(event, secret, prev_event=prev_event)
            events_list.append(signed)
        return signed

    def rotate_key(
        self,
        new_secret: str,
        metadata: dict[str, str] | None = None,
    ) -> Event:
        """Rotate the signing key: append a key-rotation event and switch keys.

        The key-rotation event is signed with the **current** key, ensuring
        continuity of the chain at the rotation boundary.  All events appended
        after this call are signed with *new_secret*.

        Args:
            new_secret: The new HMAC signing key (non-empty string).
            metadata:   Optional ``str → str`` payload fields for the
                        rotation event (e.g. ``{"reason": "scheduled",
                        "rotated_by": "ops-team"}``).

        Returns:
            The signed key-rotation :class:`~spanforge.event.Event`.

        Raises:
            SigningError: If *new_secret* is empty or whitespace-only.

        Example::

            stream.rotate_key("new-secret-v2", metadata={"reason": "annual"})
        """
        # Deferred imports to avoid circular dependency at module-load time.
        from spanforge.event import Event
        from spanforge.types import EventType

        _validate_secret(new_secret)

        # Include SHA-256 hash of new secret so verifiers can detect key substitution.
        new_secret_hash = hashlib.sha256(new_secret.encode("utf-8")).hexdigest()
        payload: dict[str, str] = {
            "rotation_marker": "true",
            "new_secret_hash": new_secret_hash,
        }
        if metadata:
            payload.update(metadata)
        # Ensure rotated_by is always present for audit trail completeness.
        if "rotated_by" not in payload:
            payload["rotated_by"] = "unknown"

        rotation_event = Event(
            event_type=EventType.AUDIT_KEY_ROTATED,
            source=self._source,
            payload=payload,
        )

        # Hold the lock for the entire sign + key-switch so that no other
        # thread can append events between the rotation event and the first
        # event signed with the new key.
        with self._lock:
            events_list: list[Event] = self._events
            prev_event: Event | None = events_list[-1] if events_list else None
            signed_rotation = sign(rotation_event, self._org_secret, prev_event=prev_event)
            events_list.append(signed_rotation)

            # After this event_id, use new_secret for subsequent events.
            # Both key_map update and secret switch happen inside the lock
            # so other threads see a consistent state.
            key_map: dict[str, str] = self._key_map
            key_map[signed_rotation.event_id] = new_secret
            object.__setattr__(self, "_org_secret", new_secret)

        return signed_rotation

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------

    def verify(self) -> ChainVerificationResult:
        """Verify the entire chain, respecting any key-rotation boundaries.

        Internally calls :func:`verify_chain` with the initial secret and the
        accumulated ``key_map`` from all :meth:`rotate_key` calls.

        Returns:
            A :class:`ChainVerificationResult` reflecting the state of the
            complete chain.
        """
        key_map: dict[str, str] = self._key_map
        return verify_chain(
            self._events,
            org_secret=self._initial_secret,
            key_map=dict(key_map) if key_map else None,
        )

    def erase_subject(
        self,
        subject_id: str,
        *,
        erased_by: str = "unknown",
        reason: str = "GDPR Art.17 right to erasure",
        request_ref: str = "",
    ) -> list[Event]:
        """Replace all events mentioning *subject_id* with TOMBSTONE events.

        Scans the chain for events whose ``actor_id``, ``session_id``, or
        payload values contain *subject_id*.  Each matched event is replaced
        in-place with an ``AUDIT_TOMBSTONE`` event that preserves the original
        ``event_id`` and chain linkage (``prev_id``, ``checksum``,
        ``signature``) so the chain remains verifiable.

        The tombstone payload records the original ``event_type`` and reason.
        **No PII is retained** in the tombstone.

        Args:
            subject_id: The data-subject identifier to erase (e.g. user ID,
                        email, or session token).
            erased_by:  Identity of the operator performing the erasure.
            reason:     Free-text reason recorded in each tombstone.
            request_ref: External reference for the erasure request
                         (e.g. ticket ID or GDPR request number).

        Returns:
            List of the tombstone :class:`Event` instances that replaced
            original events.  Empty if no matches were found.
        """
        from spanforge.event import Event as _Event
        from spanforge.types import EventType

        tombstones: list[Event] = []
        with self._lock:
            events_list: list[Event] = self._events
            for idx, event in enumerate(events_list):
                if not _event_mentions_subject(event, subject_id):
                    continue

                # Build tombstone payload — no PII
                tombstone_payload = {
                    "erased_subject_id_hash": hashlib.sha256(
                        subject_id.encode("utf-8")
                    ).hexdigest(),
                    "original_event_type": str(event.event_type),
                    "erased_by": erased_by,
                    "reason": reason,
                }
                if request_ref:
                    tombstone_payload["erasure_request_ref"] = request_ref

                tombstone = _Event(
                    schema_version=event.schema_version,
                    event_id=event.event_id,
                    event_type=EventType.AUDIT_TOMBSTONE.value,
                    timestamp=event.timestamp,
                    source=self._source,
                    payload=tombstone_payload,
                    trace_id=event.trace_id,
                    span_id=event.span_id,
                    parent_span_id=event.parent_span_id,
                    org_id=event.org_id,
                    team_id=event.team_id,
                    actor_id=None,
                    session_id=None,
                    tags=event.tags,
                    checksum=event.checksum,
                    signature=event.signature,
                    prev_id=event.prev_id,
                )

                # Re-sign to maintain chain integrity
                prev_event: Event | None = events_list[idx - 1] if idx > 0 else None
                signed_tombstone = sign(tombstone, self._org_secret, prev_event=prev_event)

                events_list[idx] = signed_tombstone
                tombstones.append(signed_tombstone)

                # Re-sign subsequent event to maintain linkage
                if idx + 1 < len(events_list):
                    next_evt = events_list[idx + 1]
                    re_signed = sign(next_evt, self._org_secret, prev_event=signed_tombstone)
                    events_list[idx + 1] = re_signed

        return tombstones


# ---------------------------------------------------------------------------
# GA-06: AsyncAuditStream — asyncio-native audit chain
# ---------------------------------------------------------------------------


class AsyncAuditStream:
    """Asyncio-native tamper-evident HMAC-signed audit chain.

    Mirrors the API of :class:`AuditStream` but uses :class:`asyncio.Lock`
    instead of :class:`threading.RLock`, making it safe for ``async def``
    code paths without blocking the event loop.

    Args:
        org_secret: HMAC signing key (non-empty string).
        source:     The ``source`` field for auto-generated audit events.
        key_resolver: Optional :class:`KeyResolver` for multi-tenant setups.

    Example::

        stream = AsyncAuditStream(org_secret="key", source="svc@1.0.0")
        signed = await stream.append(event)
        result = await stream.verify()
    """

    __slots__ = (
        "_events",
        "_initial_secret",
        "_key_map",
        "_key_resolver",
        "_lock",
        "_org_secret",
        "_source",
    )

    def __init__(
        self,
        org_secret: str,
        source: str,
        *,
        key_resolver: KeyResolver | None = None,
    ) -> None:
        import asyncio

        _validate_secret(org_secret)
        self._initial_secret = org_secret
        self._org_secret = org_secret
        self._source = source
        self._events: list[Any] = []
        self._key_map: dict[str, str] = {}
        self._key_resolver = key_resolver
        self._lock = asyncio.Lock()

    def __repr__(self) -> str:
        return f"<AsyncAuditStream events={len(self._events)}>"

    def __len__(self) -> int:
        return len(self._events)

    @property
    def events(self) -> list[Any]:
        """A read-only copy of all signed events."""
        return list(self._events)

    async def append(self, event: Any) -> Any:
        """Sign *event*, link it to the chain, and return the signed event."""
        async with self._lock:
            resolver = self._key_resolver
            secret = self._org_secret
            if resolver is not None and getattr(event, "org_id", None):
                secret = resolver.resolve(event.org_id)
            prev_event = self._events[-1] if self._events else None
            signed = sign(event, secret, prev_event=prev_event)
            self._events.append(signed)
        return signed

    async def rotate_key(
        self,
        new_secret: str,
        metadata: dict[str, str] | None = None,
    ) -> Any:
        """Rotate the signing key (async version)."""
        from spanforge.event import Event, EventType

        _validate_secret(new_secret)
        async with self._lock:
            rotation_payload = {"action": "key_rotation"}
            if metadata:
                rotation_payload.update(metadata)

            rotation_event = Event(
                event_type=EventType.AUDIT_KEY_ROTATED,
                source=self._source,
                payload=rotation_payload,
            )
            prev_event = self._events[-1] if self._events else None
            signed_rotation = sign(rotation_event, self._org_secret, prev_event=prev_event)
            self._events.append(signed_rotation)
            self._key_map[signed_rotation.event_id] = new_secret
            self._org_secret = new_secret
        return signed_rotation

    async def verify(self) -> ChainVerificationResult:
        """Verify the full chain (async wrapper)."""
        async with self._lock:
            return verify_chain(
                self._events,
                self._initial_secret,
                key_map=self._key_map,
            )
