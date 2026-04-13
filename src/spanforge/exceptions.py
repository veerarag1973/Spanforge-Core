"""Typed exception hierarchy for spanforge.

All exceptions raised by spanforge inherit from :class:`LLMSchemaError` so
callers can catch the whole family with a single ``except LLMSchemaError``.

Design rules
------------
* Exceptions carry enough context to be actionable — field name, received value,
  and an explanation of what was expected.
* HMAC keys and PII-tagged content are **never** embedded in exception messages
  or ``__cause__`` chains.
* No bare ``raise`` — every raise site uses a typed subclass.
"""

from __future__ import annotations

__all__ = [
    "AuditStorageError",
    "DeserializationError",
    "EgressViolationError",
    "EventTypeError",
    "ExportError",
    "LLMSchemaError",
    "SchemaValidationError",
    "SchemaVersionError",
    "SerializationError",
    "SigningError",
    "ULIDError",
    "VerificationError",
]


class LLMSchemaError(Exception):
    """Base class for all spanforge exceptions.

    All public-facing exceptions derive from this class, enabling callers to
    write a single broad ``except LLMSchemaError`` guard as a safety net while
    still being able to catch specific sub-types for targeted handling.
    """


class SchemaValidationError(LLMSchemaError):
    """Raised when an :class:`~spanforge.event.Event` fails validation.

    Attributes:
        field: The dotted field path that failed (e.g. ``"event_id"``).
        received: The actual value that was provided (redacted if sensitive).
        reason: Human-readable explanation of the constraint that was violated.

    Example::

        try:
            event.validate()
        except SchemaValidationError as exc:
            logger.error("Invalid event field=%s reason=%s", exc.field, exc.reason)
    """

    def __init__(self, field: str, received: object, reason: str) -> None:
        self.field = field
        self.received = received
        self.reason = reason
        super().__init__(
            f"Validation failed for field '{field}': {reason} "
            f"(received type={type(received).__name__!r})"
        )


class ULIDError(LLMSchemaError):
    """Raised when ULID generation or parsing fails.

    Attributes:
        detail: Human-readable description of the failure.

    This exception is intentionally opaque about internal state to avoid
    leaking timing information that could aid side-channel attacks.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"ULID error: {detail}")


class SerializationError(LLMSchemaError):
    """Raised when an :class:`~spanforge.event.Event` cannot be serialized.

    Attributes:
        event_id: The ULID of the event that failed (safe to log).
        reason: Human-readable description of the failure.
    """

    def __init__(self, event_id: str, reason: str) -> None:
        self.event_id = event_id
        self.reason = reason
        super().__init__(
            f"Serialization failed for event '{event_id}': {reason}"
        )


class DeserializationError(LLMSchemaError):
    """Raised when a JSON blob cannot be deserialized into an Event.

    Attributes:
        reason: Human-readable description of the failure.
        source_hint: A short, non-PII hint about the source (e.g. filename).
    """

    def __init__(self, reason: str, source_hint: str = "<unknown>") -> None:
        self.reason = reason
        self.source_hint = source_hint
        super().__init__(
            f"Deserialization failed (source={source_hint!r}): {reason}"
        )


class EventTypeError(LLMSchemaError):
    """Raised when an unknown or malformed event type string is encountered.

    Attributes:
        event_type: The offending event type string.
        reason: Human-readable description of the failure.
    """

    def __init__(self, event_type: str, reason: str) -> None:
        self.event_type = event_type
        self.reason = reason
        super().__init__(
            f"Invalid event type '{event_type}': {reason}"
        )


class SigningError(LLMSchemaError):
    """Raised when HMAC event signing fails.

    Security: the ``org_secret`` value is **never** included in the message.

    Attributes:
        reason: Human-readable description of why signing failed.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Signing failed: {reason}")


class VerificationError(LLMSchemaError):
    """Raised when an event fails cryptographic verification.

    Raised by :func:`~spanforge.signing.assert_verified` on verification failure.

    Attributes:
        event_id: The ULID of the event that failed (safe to log).
    """

    def __init__(self, event_id: str) -> None:
        self.event_id = event_id
        super().__init__(
            f"Event '{event_id}' failed cryptographic verification. "
            "The event may have been tampered with or the wrong key was used."
        )


class ExportError(LLMSchemaError):
    """Raised when exporting events to an external backend fails.

    Attributes:
        backend:  Short identifier for the backend (e.g. ``"otlp"``,
                  ``"webhook"``, ``"jsonl"``).
        reason:   Human-readable description of the failure.
        event_id: The ULID of the event that failed, or ``""`` for batch
                  failures where no single event is responsible.

    Security: HMAC secrets and PII-tagged payloads are **never** embedded in
    the message or ``__cause__``.

    Example::

        try:
            await exporter.export(event)
        except ExportError as exc:
            logger.error("backend=%s reason=%s", exc.backend, exc.reason)
    """

    def __init__(self, backend: str, reason: str, event_id: str = "") -> None:
        self.backend = backend
        self.reason = reason
        self.event_id = event_id
        msg = f"Export to '{backend}' failed: {reason}"
        if event_id:
            msg += f" (event_id={event_id!r})"
        super().__init__(msg)


class SchemaVersionError(LLMSchemaError):
    """Raised when an event carries an unsupported ``schema_version`` value.

    RFC-0001 §15.5 specifies that v2.0 consumers MUST accept events with
    ``schema_version`` ``"1.0"`` or ``"2.0"`` and MUST raise this error
    for any other value.

    Attributes:
        version: The unsupported schema version string that was encountered.

    Example::

        try:
            consumer.ingest(event)
        except SchemaVersionError as exc:
            logger.warning("Skipping event with unknown version %s", exc.version)
    """

    def __init__(self, version: str) -> None:
        self.version = version
        super().__init__(
            f"Unsupported schema_version {version!r}. "
            "Accepted values: '1.0', '2.0' (RFC-0001 §15.5)."
        )


class EgressViolationError(LLMSchemaError):
    """Raised when an exporter attempts a network call in no-egress mode.

    Attributes:
        backend: Short identifier for the backend that violated the policy.
        endpoint: The endpoint URL that was blocked (may be ``""`` if unknown).
    """

    def __init__(self, backend: str, endpoint: str = "") -> None:
        self.backend = backend
        self.endpoint = endpoint
        msg = f"Egress violation: exporter '{backend}' attempted a network call"
        if endpoint:
            msg += f" to {endpoint!r}"
        msg += " but no_egress mode is active"
        super().__init__(msg)


class AuditStorageError(LLMSchemaError):
    """Raised when the audit log storage layer detects a violation.

    Attributes:
        reason: Human-readable description of the storage violation.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Audit storage error: {reason}")
