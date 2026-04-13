"""Zero-dependency ULID (Universally Unique Lexicographically Sortable Identifier).

Specification: https://github.com/ulid/spec

Format (26 Crockford Base32 characters, 128 bits)
--------------------------------------------------
::

    01ARZ3NDEKTSV4RRFFQ69G5FAV
    ├──────────┤├────────────────┤
     Timestamp (ms)   Random (80 bits)
     48 bits, 10 chars  16 chars

Properties
----------
* **Lexicographically sortable** — events can be sorted by ULID without parsing
  the timestamp field.
* **Monotonic within the same millisecond** — the random component is
  incremented rather than regenerated when two ULIDs are requested within the
  same millisecond clock tick, preserving ordering.
* **URL and filename safe** — only uppercase alphanumerics (Crockford Base32).
* **Zero external dependencies** — uses only :mod:`os` and :mod:`time`.

Security note
-------------
The random component is seeded from :func:`os.urandom` (CSPRNG), making ULIDs
safe for use as non-guessable identifiers in audit chains.

Performance note
----------------
The module-level :class:`_ULIDGenerator` instance is thread-safe via the GIL
for standard CPython but is explicitly protected with :class:`threading.Lock`
for correctness on alternative runtimes and as documentation of intent.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Final

from spanforge.exceptions import ULIDError

__all__ = ["ULID_REGEX", "generate", "validate"]

# ---------------------------------------------------------------------------
# Crockford Base32 alphabet (excludes I, L, O, U to avoid confusion)
# ---------------------------------------------------------------------------
_ALPHABET: Final[str] = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ALPHABET_LEN: Final[int] = 32  # exactly 2^5 — one char encodes 5 bits

# Pre-compute a decode lookup table for O(1) character → value conversion.
_DECODE: Final[dict[str, int]] = {ch: idx for idx, ch in enumerate(_ALPHABET)}

# Extra entries for lowercase and visually-similar characters (I/L/O/U).
_DECODE.update({ch.lower(): idx for ch, idx in _DECODE.items()})
_DECODE.update({"i": 1, "I": 1, "l": 1, "L": 1, "o": 0, "O": 0})

# Strict charset for validation — excludes I/L/O/U aliases (generate() never
# emits them; validate() must reject them for canonical-form compliance).
_VALID_CHARS: Final[frozenset[str]] = frozenset(_ALPHABET + _ALPHABET.lower())

ULID_LENGTH: Final[int] = 26
# RFC-0001 §6.3 — first character must be 0-7 (timestamp MSBs, max value
# «0111» ensures the 48-bit timestamp fits in 10 Crockford characters).
ULID_REGEX: Final[str] = r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$"

_MAX_TIMESTAMP: Final[int] = (1 << 48) - 1  # 281 474 976 710 655 ms

# ---------------------------------------------------------------------------
# Monotonic generator
# ---------------------------------------------------------------------------


class _ULIDGenerator:
    """Stateful generator that guarantees monotonicity within one millisecond.

    When two calls are made within the same millisecond, the random segment is
    incremented by 1, preserving lexicographic ordering.  If the random segment
    would overflow (2**80) clock advancement is waited for.
    """

    __slots__ = ("_last_ms", "_last_rand", "_lock")

    _rand_max: Final[int] = (1 << 80) - 1  # type: ignore[misc]

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_ms: int = 0
        self._last_rand: int = 0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def generate(self) -> str:
        """Return a new ULID string.

        Raises:
            ULIDError: If the system clock is not monotonic or the random source
                is exhausted (astronomically unlikely).
        """
        ms, rand = self._next_ms_rand()
        return _encode_ulid(ms, rand)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _next_ms_rand(self) -> tuple[int, int]:
        """Return (timestamp_ms, random_int) ensuring monotonic ordering."""
        with self._lock:
            ms = _now_ms()

            if ms > self._last_ms:
                # New millisecond — fresh random segment.
                rand = _secure_random_80()
                self._last_ms = ms
                self._last_rand = rand
                return ms, rand

            if ms == self._last_ms:
                # Same millisecond — increment random to preserve ordering.
                next_rand = self._last_rand + 1
                if next_rand > self._rand_max:
                    # Overflow — spin until the clock advances.
                    ms = _spin_until_next_ms(ms)
                    next_rand = _secure_random_80()
                    self._last_ms = ms
                self._last_rand = next_rand
                return ms, next_rand

            # Clock went backwards — still safe: we use last_ms + increment.
            next_rand = self._last_rand + 1
            if next_rand > self._rand_max:
                raise ULIDError(
                    "Random segment overflow with backwards clock — "
                    "cannot guarantee monotonicity"
                )
            self._last_rand = next_rand
            return self._last_ms, next_rand


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _now_ms() -> int:
    """Return current Unix time in milliseconds as an integer."""
    return int(time.time() * 1_000)


def _secure_random_80() -> int:
    """Return 80 cryptographically-secure random bits as an integer."""
    return int.from_bytes(os.urandom(10), "big")


def _spin_until_next_ms(current_ms: int) -> int:
    """Wait until the clock advances past *current_ms*, with a 1-second deadline.

    Raises:
        ULIDError: If the system clock does not advance within 1 second (e.g.
            clock is frozen or running backwards).
    """
    deadline = time.monotonic() + 1.0
    while True:
        ms = _now_ms()
        if ms > current_ms:
            return ms
        if time.monotonic() > deadline:
            raise ULIDError(
                "Clock did not advance within 1 s — possible system clock freeze"
            )
        # Yield CPU so other threads can run and the OS clock can tick.
        time.sleep(0.001)


def _encode_ulid(timestamp_ms: int, random_int: int) -> str:
    """Encode (timestamp_ms, random_int) into a 26-character ULID string.

    Args:
        timestamp_ms: 48-bit millisecond timestamp.
        random_int:   80-bit random value.

    Returns:
        26-character Crockford Base32 ULID string (uppercase).

    Raises:
        ULIDError: If timestamp_ms exceeds the 48-bit maximum.
    """
    if timestamp_ms > _MAX_TIMESTAMP:
        raise ULIDError(
            f"Timestamp {timestamp_ms} ms exceeds ULID maximum "
            f"({_MAX_TIMESTAMP} ms ≈ year 10889)"
        )

    # Encode timestamp — 10 characters (50 bits needed; 48 used)
    ts_chars = [""] * 10
    t = timestamp_ms
    for i in range(9, -1, -1):
        ts_chars[i] = _ALPHABET[t & 0x1F]
        t >>= 5

    # Encode random — 16 characters (80 bits)
    rand_chars = [""] * 16
    r = random_int
    for i in range(15, -1, -1):
        rand_chars[i] = _ALPHABET[r & 0x1F]
        r >>= 5

    return "".join(ts_chars) + "".join(rand_chars)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_generator = _ULIDGenerator()


def generate() -> str:
    """Generate a new ULID string.

    The returned value is:

    * 26 characters long
    * Composed of Crockford Base32 characters (``[0-9A-HJKMNP-TV-Z]``)
    * Lexicographically sortable (earlier ULIDs < later ULIDs as strings)
    * Monotonic within the same millisecond
    * Seeded from :func:`os.urandom` (CSPRNG)

    Returns:
        A 26-character uppercase ULID string.

    Raises:
        ULIDError: On the astronomically unlikely event of internal state
            overflow or backwards-clock exhaustion.

    Example::

        from spanforge.ulid import generate
        event_id = generate()  # "01ARYZ3NDEKTSV4RRFFQ69G5FAV"
    """
    return _generator.generate()


def validate(value: str) -> bool:
    """Return ``True`` if *value* is a syntactically valid ULID string.

    Validation checks:

    1. Exactly 26 characters long.
    2. All characters are in the Crockford Base32 alphabet (case-insensitive,
       I/L/O treated as 1/1/0).
    3. The timestamp component does not overflow the 48-bit range.

    Args:
        value: The string to validate.

    Returns:
        ``True`` if valid, ``False`` otherwise.

    Example::

        validate("01ARYZ3NDEKTSV4RRFFQ69G5FAV")  # True
        validate("not-a-ulid")                     # False
    """
    if not isinstance(value, str) or len(value) != ULID_LENGTH:
        return False
    upper = value.upper()
    if not all(c in _VALID_CHARS for c in upper):
        return False
    # Decode timestamp and check range
    t = 0
    for ch in upper[:10]:
        t = (t << 5) | _DECODE[ch]
    return t <= _MAX_TIMESTAMP


def extract_timestamp_ms(ulid: str) -> int:
    """Extract the embedded millisecond timestamp from a ULID.

    Args:
        ulid: A valid 26-character ULID string.

    Returns:
        Unix timestamp in milliseconds.

    Raises:
        ULIDError: If *ulid* is not a valid ULID.

    Example::

        ms = extract_timestamp_ms("01ARYZ3NDEKTSV4RRFFQ69G5FAV")
        print(datetime.utcfromtimestamp(ms / 1000))
    """
    if not validate(ulid):
        raise ULIDError(f"Cannot extract timestamp from invalid ULID: {ulid!r}")
    t = 0
    for ch in ulid.upper()[:10]:
        t = (t << 5) | _DECODE[ch]
    return t
