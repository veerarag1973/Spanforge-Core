"""PII redaction framework for spanforge.

Provides a layered, policy-driven approach to PII identification and redaction
in event payloads.  Redaction is **opt-in per field** — fields must be
explicitly wrapped in :class:`Redactable` to participate in the lifecycle.

Sensitivity ladder
------------------

``low`` < ``medium`` < ``high`` < ``pii`` < ``phi``

A :class:`RedactionPolicy` is configured with a ``min_sensitivity`` level.
Only fields whose sensitivity is **≥ min_sensitivity** are scrubbed when
:meth:`RedactionPolicy.apply` is called.

Usage example
-------------
::

    from spanforge.redact import Redactable, RedactionPolicy, Sensitivity, contains_pii
    from spanforge import Event, EventType

    policy = RedactionPolicy(
        min_sensitivity=Sensitivity.PII,
        redacted_by="policy:corp-default",
    )

    event = Event(
        event_type=EventType.PROMPT_SAVED,
        source="promptlock@1.0.0",
        payload={
            "version": "v3",
            "author": Redactable("alice@example.com", Sensitivity.PII, {"email"}),
        },
    )

    result = policy.apply(event)
    # result.event.payload["author"]   == "[REDACTED:pii]"
    # result.redaction_count           == 1
    # contains_pii(result.event)       == False

Security guarantees
-------------------
* :class:`Redactable` never exposes its wrapped value in ``__repr__``,
  ``__str__``, or any exception message.
* Exception messages only reveal the *sensitivity level* and *field depth*,
  never the content of the wrapped value.
* The literal replacement strings (``"[REDACTED:pii]"`` etc.) are safe to
  log, export, or include in error messages.
* :meth:`RedactionPolicy.apply` rebuilds the payload recursively so nested
  structures are fully scanned even in deeply-nested payloads.
"""

from __future__ import annotations

import datetime
import hashlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Final

from spanforge.exceptions import LLMSchemaError

if TYPE_CHECKING:
    from spanforge.event import Event

__all__ = [
    "PII_TYPES",
    "PIINotRedactedError",
    "PIIScanResult",
    "Redactable",
    "RedactionPolicy",
    "RedactionResult",
    "Sensitivity",
    "contains_pii",
    "scan_payload",
]

# ---------------------------------------------------------------------------
# Known PII type label constants
# ---------------------------------------------------------------------------

PII_TYPES: Final[frozenset[str]] = frozenset(
    [
        "credit_card",
        "date_of_birth",
        "email",
        "financial_id",
        "ip_address",
        "medical_id",
        "name",
        "phone",
        "ssn",
        "address",
    ]
)

# ---------------------------------------------------------------------------
# Sensitivity ordering
# ---------------------------------------------------------------------------

#: Numeric ordering for each sensitivity level (ascending sensitivity).
_SENSITIVITY_ORDER: Final[dict[str, int]] = {
    "low": 0,
    "medium": 1,
    "high": 2,
    "pii": 3,
    "phi": 4,
}


class Sensitivity(str, Enum):
    """Ordered sensitivity levels for PII classification.

    Levels increase in sensitivity: LOW < MEDIUM < HIGH < PII < PHI.

    * **LOW** — Non-sensitive; informational or operational metadata.
    * **MEDIUM** — Pseudonymous or indirectly identifying data.
    * **HIGH** — Directly identifying but non-regulated (e.g. usernames).
    * **PII** — Directly identifying, regulated personal data (GDPR / CCPA).
    * **PHI** — Protected health information (HIPAA).  Most restrictive.

    Comparison operators (``<``, ``<=``, ``>``, ``>=``) work as expected::

        Sensitivity.PII > Sensitivity.HIGH   # True
        Sensitivity.PHI >= Sensitivity.PII   # True
        Sensitivity.LOW < Sensitivity.MEDIUM # True
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    PII = "pii"
    PHI = "phi"

    # ------------------------------------------------------------------
    # Ordered comparisons (delegated to integer order table)
    # ------------------------------------------------------------------

    @property
    def _order(self) -> int:
        """Integer rank — for comparison only; not part of the public API."""
        return _SENSITIVITY_ORDER[self.value]

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Sensitivity):
            return NotImplemented  # type: ignore[return-value]
        return self._order < other._order

    def __le__(self, other: object) -> bool:
        if not isinstance(other, Sensitivity):
            return NotImplemented  # type: ignore[return-value]
        return self._order <= other._order

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Sensitivity):
            return NotImplemented  # type: ignore[return-value]
        return self._order > other._order

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, Sensitivity):
            return NotImplemented  # type: ignore[return-value]
        return self._order >= other._order

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str) and not isinstance(other, Sensitivity):
            return str.__eq__(self, other)
        return Enum.__eq__(self, other)

    def __hash__(self) -> int:
        return str.__hash__(self)


# ---------------------------------------------------------------------------
# Redactable wrapper
# ---------------------------------------------------------------------------


class Redactable:
    """Immutable wrapper that marks a payload value as PII-sensitive.

    Wrapping a value in :class:`Redactable` does **not** redact it immediately.
    The value is redacted only when :meth:`RedactionPolicy.apply` is called on
    the event that contains it.

    Security: :class:`Redactable` never surfaces its wrapped value in
    ``__repr__``, ``__str__``, or exceptions.  Only the sensitivity level and
    PII type labels are visible in any string representation.

    Args:
        value:       The raw PII-sensitive value.
        sensitivity: How sensitive the value is.
        pii_types:   Labels describing what type of PII this is.  Use
                     constants from :data:`PII_TYPES` or custom strings.
                     Defaults to an empty frozenset.

    Example::

        field = Redactable("alice@example.com", Sensitivity.PII, {"email"})
        str(field)   # "<Redactable:pii>"   — value hidden
        repr(field)  # "<Redactable sensitivity='pii' pii_types={'email'}>"
    """

    __slots__ = ("_pii_types", "_sensitivity", "_value")

    def __init__(
        self,
        value: Any,  # noqa: ANN401
        sensitivity: Sensitivity,
        pii_types: frozenset[str] = frozenset(),
    ) -> None:
        object.__setattr__(self, "_value", value)
        object.__setattr__(self, "_sensitivity", sensitivity)
        object.__setattr__(self, "_pii_types", frozenset(pii_types))

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    @property
    def sensitivity(self) -> Sensitivity:
        """The sensitivity level of this field."""
        return self._sensitivity  # type: ignore[return-value]

    @property
    def pii_types(self) -> frozenset[str]:
        """Set of PII type labels (e.g. ``{'email', 'pii_identifier'}``)."""
        return self._pii_types  # type: ignore[return-value]

    def reveal(self) -> Any:  # noqa: ANN401
        """Return the raw unredacted value.

        Use with extreme care.  Access to raw values should be restricted to
        trusted internal code paths.  Ensure the returned value is never
        logged or included in any observable output.

        Returns:
            The original unwrapped value passed to the constructor.
        """
        return self._value  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Immutability guard
    # ------------------------------------------------------------------

    def __setattr__(self, name: str, value: object) -> None:  # type: ignore[override]
        raise AttributeError("Redactable is immutable — use a new instance to change values")

    # ------------------------------------------------------------------
    # Safe string representations — value intentionally hidden
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"<Redactable sensitivity={self._sensitivity!r} "  # type: ignore[misc]
            f"pii_types={set(self._pii_types)!r}>"  # type: ignore[misc]
        )

    def __str__(self) -> str:
        return f"<Redactable:{self._sensitivity}>"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Redaction result
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RedactionResult:
    """Immutable result returned by :meth:`RedactionPolicy.apply`.

    Attributes:
        event:            The newly constructed event with PII removed.
        redaction_count:  How many :class:`Redactable` fields were scrubbed.
        redacted_at:      UTC ISO-8601 timestamp when redaction was applied.
        redacted_by:      The policy identifier string.
    """

    event: Event
    redaction_count: int
    redacted_at: str
    redacted_by: str


# ---------------------------------------------------------------------------
# PIINotRedactedError
# ---------------------------------------------------------------------------


class PIINotRedactedError(LLMSchemaError):
    """Raised when :func:`contains_pii` detects un-redacted PII in an event.

    This error signals that a :class:`Redactable` instance is still present in
    the event payload after a :class:`RedactionPolicy` should have been applied.

    Security: the error message never reveals the actual PII value — only field
    path depth and sensitivity information.

    Args:
        count:    Number of unredacted :class:`Redactable` instances found.
        context:  Optional short label for where the check was done.

    Attributes:
        count:   Number of outstanding :class:`Redactable` instances found.
    """

    count: int

    def __init__(self, count: int, context: str = "") -> None:
        self.count = count
        # M11: never embed the raw context string — it may itself contain PII.
        # Include only a hash for correlation without disclosure.
        ctx = ""
        if context:
            ctx_hash = hashlib.sha256(context.encode()).hexdigest()[:8]
            ctx = f" [context-hash:{ctx_hash}]"
        super().__init__(
            f"Found {count} unredacted PII field(s){ctx}. "
            "Apply a RedactionPolicy before serialising or exporting this event."
        )


# ---------------------------------------------------------------------------
# RedactionPolicy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RedactionPolicy:
    """Policy that defines which fields to scrub and how to label redactions.

    A policy is immutable; create a new instance to change configuration.
    Apply it to an event via :meth:`apply`, which returns a :class:`RedactionResult`
    containing a new event with PII removed.

    Args:
        min_sensitivity:       Fields with sensitivity **≥** this level are
                               redacted.  Defaults to :attr:`Sensitivity.PII`.
        redacted_by:           Identifier embedded in the redaction metadata
                               (e.g. ``"policy:corp-default"``).
        replacement_template:  String template for the redaction marker.
                               The ``{sensitivity}`` placeholder is replaced
                               with the field's sensitivity level value.
                               Defaults to ``"[REDACTED:{sensitivity}]"``.

    Example::

        policy = RedactionPolicy(
            min_sensitivity=Sensitivity.HIGH,
            redacted_by="policy:strict",
        )
        result = policy.apply(event)
    """

    min_sensitivity: Sensitivity = Sensitivity.PII
    redacted_by: str = "policy:default"
    replacement_template: str = "[REDACTED:{sensitivity}]"

    def _make_marker(self, sensitivity: Sensitivity) -> str:
        """Format the replacement string for a given sensitivity level."""
        return self.replacement_template.format(sensitivity=sensitivity.value)

    def _should_redact(self, r: Redactable) -> bool:
        """Return True if the Redactable field meets the policy threshold."""
        return r.sensitivity >= self.min_sensitivity

    def _redact_value(self, value: Any, counter: list[int], _depth: int = 0) -> Any:  # noqa: ANN401
        """Recursively replace Redactable instances in *value*.

        Args:
            value:   Any Python value (dict, list, Redactable, or scalar).
            counter: Single-element list used as a mutable integer counter.
            _depth:  Current recursion depth (internal; raises at > 100).

        Returns:
            The value with any qualifying Redactable instances replaced by
            their marker strings.  Non-Redactable values are returned as-is.
        """
        if _depth > 100:
            raise RecursionError(
                "RedactionPolicy._redact_value: maximum nesting depth (100) exceeded"
            )
        if isinstance(value, Redactable):
            if self._should_redact(value):
                counter[0] += 1
                return self._make_marker(value.sensitivity)
            # Below threshold — leave as-is for now;
            # contains_pii() will detect it post-apply if needed.
            return value
        if isinstance(value, dict):
            return {k: self._redact_value(v, counter, _depth + 1) for k, v in value.items()}
        if isinstance(value, list):
            return [self._redact_value(v, counter, _depth + 1) for v in value]
        if isinstance(value, tuple):
            return tuple(self._redact_value(v, counter, _depth + 1) for v in value)
        return value

    def apply(self, event: Event) -> RedactionResult:
        """Apply this policy to *event*, returning a new redacted event.

        All :class:`Redactable` fields in the payload whose sensitivity is ≥
        :attr:`min_sensitivity` are replaced with safe marker strings.
        Redaction metadata is appended under the reserved ``__redacted_*``
        keys in the payload.

        The original event is **not** mutated; a new :class:`Event` is returned
        inside the :class:`RedactionResult`.

        Args:
            event: The event whose payload should be scanned and redacted.

        Returns:
            A :class:`RedactionResult` with the new event and redaction stats.

        Raises:
            LLMSchemaError: If reconstruction of the redacted event fails for
                structural reasons.
        """
        # Import here to avoid circular dependency at module load time.
        from spanforge.event import Event  # noqa: PLC0415

        counter: list[int] = [0]
        redacted_payload = self._redact_value(dict(event.payload), counter)

        now = _utcnow_iso()

        if isinstance(redacted_payload, dict) and counter[0] > 0:
            redacted_payload["__redacted_at"] = now
            redacted_payload["__redacted_by"] = self.redacted_by
            redacted_payload["__redaction_count"] = counter[0]

        new_event = Event(
            schema_version=event.schema_version,
            event_id=event.event_id,
            event_type=event.event_type,
            timestamp=event.timestamp,
            source=event.source,
            payload=redacted_payload,
            trace_id=event.trace_id,
            span_id=event.span_id,
            parent_span_id=event.parent_span_id,
            org_id=event.org_id,
            team_id=event.team_id,
            actor_id=event.actor_id,
            session_id=event.session_id,
            tags=event.tags,
            checksum=event.checksum,
            signature=event.signature,
            prev_id=event.prev_id,
        )

        return RedactionResult(
            event=new_event,
            redaction_count=counter[0],
            redacted_at=now,
            redacted_by=self.redacted_by,
        )


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def contains_pii(event: Event, *, scan_raw: bool = True) -> bool:
    """Return ``True`` if any unredacted :class:`Redactable` values remain.

    Use this after :meth:`RedactionPolicy.apply` to verify that all qualifying
    fields were scrubbed before the event is serialised or exported.

    Does **not** raise; callers decide the appropriate response.  For a
    strict raising version, see :func:`assert_redacted`.

    .. versionchanged:: 2.1
       Default for *scan_raw* changed from ``False`` to ``True`` so that
       raw-string PII is caught by default.  Pass ``scan_raw=False``
       explicitly to restore the old behaviour.

    Args:
        event:    The event to inspect.
        scan_raw: When ``True`` (default), also run regex-based PII scanning
                  on the payload strings (via :func:`scan_payload`), not just
                  check for :class:`Redactable` wrappers.

    Returns:
        ``True`` if at least one :class:`Redactable` instance is found in the
        payload (at any nesting depth), or if ``scan_raw=True`` and a regex
        PII hit is detected.  ``False`` if the payload is clean.

    Example::

        if contains_pii(event):
            raise RuntimeError("Unredacted PII detected — cannot export")
    """
    if _has_redactable(event.payload):
        return True
    if scan_raw and isinstance(event.payload, Mapping):
        result = scan_payload(event.payload)  # type: ignore[arg-type]
        return not result.clean
    return False


def assert_redacted(event: Event, context: str = "", *, scan_raw: bool = True) -> None:
    """Assert that *event* contains no unredacted :class:`Redactable` values.

    This is the strict variant of :func:`contains_pii`.  It raises
    :exc:`PIINotRedactedError` if any :class:`Redactable` instances remain,
    or if ``scan_raw=True`` and regex-based PII is detected.

    .. versionchanged:: 2.1
       Default for *scan_raw* changed from ``False`` to ``True``.

    Args:
        event:    The event to inspect.
        context:  Optional short label for the error message (e.g. filename).
        scan_raw: When ``True`` (default), also run regex-based PII scanning.

    Raises:
        PIINotRedactedError: If any :class:`Redactable` instances or raw PII
            patterns are found.

    Example::

        assert_redacted(event, context="export_to_otlp", scan_raw=True)
    """
    count = _count_redactable(event.payload)
    if count > 0:
        raise PIINotRedactedError(count=count, context=context)
    if scan_raw and isinstance(event.payload, Mapping):
        result = scan_payload(event.payload)  # type: ignore[arg-type]
        if not result.clean:
            raise PIINotRedactedError(count=len(result.hits), context=context)


# ---------------------------------------------------------------------------
# Internal helpers (module-private)
# ---------------------------------------------------------------------------


def _has_redactable(value: Any) -> bool:  # noqa: ANN401
    """Return True if *value* contains any Redactable instance (recursive)."""
    if isinstance(value, Redactable):
        return True
    if isinstance(value, Mapping):
        return any(_has_redactable(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_has_redactable(v) for v in value)
    return False


def _count_redactable(value: Any, _depth: int = 0) -> int:  # noqa: ANN401
    """Count the total number of Redactable instances in *value* (recursive)."""
    if isinstance(value, Redactable):
        return 1
    if isinstance(value, Mapping):
        return sum(_count_redactable(v, _depth + 1) for v in value.values())
    if isinstance(value, (list, tuple)):
        return sum(_count_redactable(v, _depth + 1) for v in value)
    return 0


def _utcnow_iso() -> str:
    """Return current UTC time as an ISO-8601 string (same format as Event)."""
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond:06d}Z"


# ---------------------------------------------------------------------------
# GA-03: Deep PII scanning — regex-based detection
# ---------------------------------------------------------------------------

_PII_PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    "email": re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}", re.ASCII),
    "phone": re.compile(
        r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
    ),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    "ip_address": re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
        r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
    ),
    "uk_national_insurance": re.compile(
        r"\b[A-CEGHJ-PR-TW-Z]{2}\s?\d{2}\s?\d{2}\s?\d{2}\s?[A-D]\b",
        re.IGNORECASE,
    ),
    # Date of birth — numeric (/, -, .) and written-month forms covering
    # ISO/YMD, US MDY, day-first DMY (Europe/Asia/Australia/etc.), and
    # long/short written-month variants.  Years restricted to 19xx–20xx to
    # limit false positives.  _is_valid_date() provides secondary calendar-
    # correctness check (leap-year rules, month lengths, etc.).
    "date_of_birth": re.compile(
        # ISO / YMD: YYYY-MM-DD, YYYY/MM/DD, YYYY.MM.DD
        r"\b(?:19|20)\d{2}[-/.](?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])\b"
        r"|"
        # US MDY: MM/DD/YYYY, MM-DD-YYYY, MM.DD.YYYY
        r"\b(?:0?[1-9]|1[0-2])[-/.](?:0?[1-9]|[12]\d|3[01])[-/.](?:19|20)\d{2}\b"
        r"|"
        # Day-first DMY: DD/MM/YYYY, DD-MM-YYYY, DD.MM.YYYY (UK, EU, Asia, etc.)
        r"\b(?:0?[1-9]|[12]\d|3[01])[-/.](?:0?[1-9]|1[0-2])[-/.](?:19|20)\d{2}\b"
        r"|"
        # Written DMY: "15 Jan 2000", "15-Jan-2000", "15 January 2000"
        r"\b(?:0?[1-9]|[12]\d|3[01])[\s\-]"
        r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
        r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"[\s\-](?:19|20)\d{2}\b"
        r"|"
        # Written MDY: "Jan 15, 2000", "January 15 2000"
        r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
        r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+(?:0?[1-9]|[12]\d|3[01]),?\s+(?:19|20)\d{2}\b",
        re.IGNORECASE,
    ),
    # Street address — house number + street name + recognised suffix
    "address": re.compile(
        r"\b\d{1,5}\s+(?:[A-Za-z0-9'.#\-]+\s+){1,5}"
        r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|Lane|Ln|"
        r"Court|Ct|Way|Place|Pl|Circle|Cir|Trail|Trl|Terrace|Ter|"
        r"Parkway|Pkwy|Highway|Hwy|Route|Rte)\.?\b",
        re.IGNORECASE,
    ),
}


# ---------------------------------------------------------------------------
# GA-03-IN: India PII patterns — DPDP Act (Digital Personal Data Protection)
# ---------------------------------------------------------------------------

# Verhoeff checksum tables for Aadhaar validation
_VERHOEFF_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)

_VERHOEFF_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)

_VERHOEFF_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def _verhoeff_check(number_str: str) -> bool:
    """Validate a number string using the Verhoeff checksum algorithm."""
    digits = [int(d) for d in number_str if d.isdigit()]
    c = 0
    for i, d in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][d]]
    return c == 0


DPDP_PATTERNS: Final[dict[str, re.Pattern[str]]] = {
    "aadhaar": re.compile(
        r"\b[2-9]\d{3}[\s-]?\d{4}[\s-]?\d{4}\b"
    ),
    "pan": re.compile(
        r"\b[A-Z]{5}\d{4}[A-Z]\b"
    ),
}


@dataclass(frozen=True)
class PIIScanHit:
    """Single PII detection hit.

    Attributes:
        pii_type:    The type of PII detected (e.g. ``"email"``, ``"ssn"``).
        path:        Dot-separated path to the field in the payload.
        match_count: Number of matches of this type at this path.
        sensitivity: Sensitivity level: ``"high"`` for SSN/credit_card,
                     ``"medium"`` for email/phone, ``"low"`` for IP/NI.
    """

    pii_type: str
    path: str
    match_count: int = 1
    sensitivity: str = "medium"


_SENSITIVITY_MAP: dict[str, str] = {
    "ssn": "high",
    "credit_card": "high",
    "aadhaar": "high",
    "pan": "high",
    "date_of_birth": "high",
    "email": "medium",
    "phone": "medium",
    "address": "medium",
    "ip_address": "low",
    "uk_national_insurance": "low",
}


@dataclass(frozen=True)
class PIIScanResult:
    """Result of a deep PII scan on a payload dictionary.

    Attributes:
        hits:       List of :class:`PIIScanHit` instances found.
        scanned:    Number of string values scanned.
        clean:      ``True`` if no PII was detected.
    """

    hits: list[PIIScanHit]
    scanned: int

    @property
    def clean(self) -> bool:
        return len(self.hits) == 0


def _luhn_check(number_str: str) -> bool:
    """Validate a credit card number using the Luhn algorithm."""
    digits = [int(d) for d in number_str if d.isdigit()]
    if len(digits) < 13 or len(digits) > 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _is_valid_ssn(ssn_str: str) -> bool:
    """Return ``False`` for SSNs in known-invalid SSA number ranges.

    Filters out the following ranges that the SSA has *never* assigned:

    * Area ``000`` — never issued.
    * Area ``666`` — explicitly excluded by SSA policy.
    * Areas ``900``–``999`` — reserved for Individual Taxpayer
      Identification Numbers (ITINs); never used as SSNs.
    * Group ``00`` — never issued within any valid area.
    * Serial ``0000`` — never issued within any valid area/group.

    Args:
        ssn_str: Raw match string from :data:`_PII_PATTERNS` ``"ssn"``
                 regex (e.g. ``"123-45-6789"``).

    Returns:
        ``True`` if the SSN passes all range checks; ``False`` otherwise.
    """
    digits = "".join(c for c in ssn_str if c.isdigit())
    if len(digits) != 9:
        return False
    area = int(digits[:3])
    group = int(digits[3:5])
    serial = int(digits[5:])
    if area == 0 or area == 666 or area >= 900:
        return False
    if group == 0:
        return False
    if serial == 0:
        return False
    return True


def _is_valid_date(date_str: str) -> bool:
    """Return ``True`` if *date_str* is a valid calendar date.

    Accepts all numeric and written-month formats produced by the
    ``"date_of_birth"`` regex in :data:`_PII_PATTERNS`.

    Numeric formats (separators ``/``, ``-``, ``.``):

    * ``YYYY/MM/DD``, ``YYYY-MM-DD``, ``YYYY.MM.DD`` — ISO / year-first
    * ``MM/DD/YYYY``, ``MM-DD-YYYY``, ``MM.DD.YYYY`` — US month-first
    * ``DD/MM/YYYY``, ``DD-MM-YYYY``, ``DD.MM.YYYY`` — day-first (Europe,
      Asia, Australia, Latin America, etc.)

    Written-month formats:

    * ``DD Mon YYYY``, ``DD-Mon-YYYY``, ``DD Month YYYY`` (e.g. 15 Jan 2000)
    * ``Mon DD, YYYY``, ``Mon DD YYYY``, ``Month DD, YYYY`` (e.g. Jan 15, 2000)

    Delegates to :func:`datetime.datetime.strptime` so leap-year rules and
    month-length limits are enforced (e.g. ``31/04/1990`` is rejected).

    Args:
        date_str: Raw match string from the ``"date_of_birth"`` regex.

    Returns:
        ``True`` if the string represents a real calendar date in any of the
        recognised formats; ``False`` otherwise.
    """
    _FORMATS = (
        # ISO / YMD
        "%Y/%m/%d", "%Y-%m-%d", "%Y.%m.%d",
        # US MDY
        "%m/%d/%Y", "%m-%d-%Y", "%m.%d.%Y",
        # Day-first DMY (Europe, Asia, Australia, Latin America, etc.)
        "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
        # Written DMY: "15 Jan 2000", "15-Jan-2000", "15 January 2000"
        "%d %b %Y", "%d-%b-%Y", "%d %B %Y", "%d-%B-%Y",
        # Written MDY: "Jan 15, 2000", "Jan 15 2000", "January 15, 2000"
        "%b %d, %Y", "%b %d %Y", "%B %d, %Y", "%B %d %Y",
    )
    for fmt in _FORMATS:
        try:
            datetime.datetime.strptime(date_str.strip(), fmt)
            return True
        except ValueError:
            continue
    return False


def scan_payload(
    payload: dict[str, Any],
    *,
    extra_patterns: dict[str, re.Pattern[str]] | None = None,
    max_depth: int = 10,
) -> PIIScanResult:
    """Scan a payload dict for PII using regex detectors.

    Walks the entire payload recursively (up to *max_depth*), testing every
    string value against the built-in pattern set (email, phone, SSN, credit
    card, IP address, UK National Insurance number) plus any caller-supplied
    patterns.

    **Security**: matched values are never returned — only the PII type, path,
    match count, and sensitivity level.

    Args:
        payload:         The dictionary to scan.
        extra_patterns:  Additional ``{label: compiled_regex}`` detectors.
        max_depth:       Maximum nesting depth to scan (default 10).

    Returns:
        A :class:`PIIScanResult` summarising all detections.
    """
    patterns = {**_PII_PATTERNS, **DPDP_PATTERNS}
    if extra_patterns:
        patterns.update(extra_patterns)

    hits: list[PIIScanHit] = []
    scanned = 0

    def _walk(obj: Any, path: str, depth: int) -> None:  # noqa: ANN401
        nonlocal scanned
        if depth > max_depth:
            return
        if isinstance(obj, str):
            scanned += 1
            for label, pat in patterns.items():
                matches = list(pat.finditer(obj))
                if not matches:
                    continue
                # Luhn validation for credit card patterns
                if label == "credit_card":
                    valid_matches = [
                        m for m in matches
                        if _luhn_check(m.group())
                    ]
                    if not valid_matches:
                        continue
                    matches = valid_matches
                # Verhoeff validation for Aadhaar patterns
                if label == "aadhaar":
                    valid_matches = [
                        m for m in matches
                        if _verhoeff_check(m.group())
                    ]
                    if not valid_matches:
                        continue
                    matches = valid_matches
                # SSN range validation — drop known-invalid SSA ranges
                if label == "ssn":
                    valid_matches = [
                        m for m in matches
                        if _is_valid_ssn(m.group())
                    ]
                    if not valid_matches:
                        continue
                    matches = valid_matches
                # Calendar validation for date_of_birth patterns
                if label == "date_of_birth":
                    valid_matches = [
                        m for m in matches
                        if _is_valid_date(m.group())
                    ]
                    if not valid_matches:
                        continue
                    matches = valid_matches
                sensitivity = _SENSITIVITY_MAP.get(label, "medium")
                hits.append(PIIScanHit(
                    pii_type=label,
                    path=path,
                    match_count=len(matches),
                    sensitivity=sensitivity,
                ))
        elif isinstance(obj, Mapping):
            for k, v in obj.items():
                _walk(v, f"{path}.{k}" if path else str(k), depth + 1)
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                _walk(v, f"{path}[{i}]", depth + 1)

    _walk(payload, "", 0)
    return PIIScanResult(hits=hits, scanned=scanned)
