"""spanforge.validate — JSON Schema validation for Event envelopes.

This module validates :class:`~spanforge.event.Event` instances against the
published JSON Schema specification. Schema version is selected automatically
from the event's ``schema_version`` field:

* ``"1.0"`` → ``schemas/v1.0/schema.json``
* ``"2.0"`` (default) → ``schemas/v2.0/schema.json``

It uses the optional ``jsonschema`` library when available for full Draft 2020-12
validation.  If ``jsonschema`` is not installed, a lightweight structural check
is performed using only the Python standard library — external dependencies are
strictly optional in line with *spanforge*'s zero-required-dependency policy.

Usage
-----
::

    from spanforge import Event, EventType
    from spanforge.validate import validate_event

    event = Event(
        event_type=EventType.TRACE_SPAN_COMPLETED,
        source="llm-trace@0.3.1",
        payload={"span_name": "run", "status": "ok"},
    )
    validate_event(event)   # raises SchemaValidationError if invalid

Public API
----------
* :func:`validate_event` — validate an :class:`~spanforge.event.Event`
  against the matching envelope schema (version-aware).
* :func:`load_schema` — load a specific schema version by key.
* :exc:`~spanforge.exceptions.SchemaValidationError` — raised on validation
  failure (re-exported from :mod:`spanforge.exceptions`).
"""

from __future__ import annotations

import enum
import hashlib
import hmac
import json
import logging
import pathlib
import re
from dataclasses import dataclass, field
from typing import Any

from spanforge.event import Event
from spanforge.exceptions import EventTypeError, SchemaValidationError
from spanforge.types import is_registered, validate_custom

__all__: list[str] = [
    "DatasetScanFinding",
    "DatasetScanReport",
    "EnforcementMode",
    "ValidationResult",
    "correct_event",
    "enforce_event",
    "load_schema",
    "scan_dataset",
    "sign_event_hmac",
    "validate_event",
]

# ---------------------------------------------------------------------------
# Schema paths — version-aware (RFC-0001 §15.5)
# ---------------------------------------------------------------------------

_SCHEMAS_DIR: pathlib.Path = pathlib.Path(__file__).parent / "schemas"

#: Map of schema-version strings to their JSON Schema file paths.
_SCHEMA_PATHS: dict[str, pathlib.Path] = {
    "1.0": _SCHEMAS_DIR / "v1.0" / "schema.json",
    "2.0": _SCHEMAS_DIR / "v2.0" / "schema.json",
}

#: Default (current) schema version (RFC-0001-SPANFORGE-Enterprise-2.0).
_DEFAULT_SCHEMA_VERSION: str = "2.0"

# Legacy single-path alias kept for backwards-compatible callers.
_SCHEMA_PATH: pathlib.Path = _SCHEMA_PATHS["1.0"]

# ---------------------------------------------------------------------------
# Compiled patterns from schema (stdlib fallback)
# ---------------------------------------------------------------------------

# RFC-0001 §6.3 — first char 0-7 (timestamp MSB constraint)
_ULID_RE: re.Pattern[str] = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")
# RFC-0001 §15.5 — only 1.0 and 2.0 are accepted schema versions.
_ACCEPTED_SCHEMA_VERSIONS: frozenset[str] = frozenset({"1.0", "2.0"})
_EVENT_TYPE_RE: re.Pattern[str] = re.compile(
    r"^(?:llm\.(?:trace|cost|cache|eval|guard|fence|prompt|redact|diff|template|audit)\.(?:[a-z][a-z0-9_]*|[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)|(?!llm\.)[a-z][a-z0-9-]*(?:\.[a-z][a-z0-9-]*)+\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*)$"  # NOSONAR — RFC §7 grammar with registered llm namespaces
)
# RFC-0001 §6.1 — microsecond precision mandatory (exactly 6 decimal places)
_TIMESTAMP_RE: re.Pattern[str] = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
# RFC-0001 §5.1 — source: letter start, letters/digits/._-, then @semver
_SOURCE_RE: re.Pattern[str] = re.compile(
    r"^[a-zA-Z][a-zA-Z0-9._\-]*@\d+\.\d+\.\d+(?:[.\-][a-zA-Z0-9.]+)?$"
)
_TRACE_ID_RE: re.Pattern[str] = re.compile(r"^[0-9a-f]{32}$")
_SPAN_ID_RE: re.Pattern[str] = re.compile(r"^[0-9a-f]{16}$")
# Checksum and signature carry distinct prefix indicators set by signing.py.
_CHECKSUM_RE: re.Pattern[str] = re.compile(r"^sha256:[0-9a-f]{64}$")
_SIGNATURE_RE: re.Pattern[str] = re.compile(r"^hmac-sha256:[0-9a-f]{64}$")
_MAX_TAG_KEYS: int = 50

# RFC-0001 §6.3 — ULID max length is 26 characters; 1 MB payload cap.
_MAX_EVENT_ID_LEN: int = 26
_MAX_PAYLOAD_BYTES: int = 1_000_000

# ---------------------------------------------------------------------------
# Schema loader
# ---------------------------------------------------------------------------

_CACHED_SCHEMAS: dict[str, dict[str, Any]] = {}

# Legacy alias kept for call sites that used the old single-schema API.
_CACHED_SCHEMA: dict[str, Any] | None = None


def load_schema(version: str | None = None) -> dict[str, Any]:
    """Load and cache a JSON Schema from disk by version.

    Parameters
    ----------
    version:
        Schema version string, e.g. ``"1.0"`` or ``"2.0"``.
        Defaults to the current SDK schema version (``"2.0"``; RFC §15.5).

    Returns:
    -------
    dict
        Parsed JSON Schema as a plain Python dict.

    Raises:
    ------
    FileNotFoundError
        If the requested schema file cannot be found relative to the
        package root.  This should never happen in a correctly installed
        distribution.
    ValueError
        If an unknown schema version is requested.
    """
    resolved = version or _DEFAULT_SCHEMA_VERSION
    if resolved in _CACHED_SCHEMAS:
        return _CACHED_SCHEMAS[resolved]

    # RFC-0001 §15.5: unknown schema versions MUST raise and stop processing.
    path = _SCHEMA_PATHS.get(resolved)
    if path is None:
        raise ValueError(
            f"Unknown schema version {resolved!r}. Available versions: {list(_SCHEMA_PATHS)}"
        )

    if not path.is_file():
        raise FileNotFoundError(
            f"JSON Schema not found at {path}.  "
            "Ensure the 'schemas/' directory is included in the "
            "installed package."
        )
    with path.open("r", encoding="utf-8") as fh:
        schema: dict[str, Any] = json.load(fh)
    _CACHED_SCHEMAS[resolved] = schema
    return schema


# ---------------------------------------------------------------------------
# Internal: stdlib structural validation
# ---------------------------------------------------------------------------


def _check_string_field(
    doc: dict[str, Any],
    field: str,
    *,
    required: bool = True,
    pattern: re.Pattern[str] | None = None,
    min_length: int = 1,
) -> None:
    """Validate a single string field in *doc*."""
    if field not in doc:
        if required:
            raise SchemaValidationError(
                field=field,
                received=None,
                reason=f"required field '{field}' is missing",
            )
        return
    value = doc[field]
    if not isinstance(value, str):
        raise SchemaValidationError(
            field=field,
            received=value,
            reason=f"'{field}' must be a string",
        )
    if len(value) < min_length:
        raise SchemaValidationError(
            field=field,
            received=value,
            reason=f"'{field}' must be at least {min_length} character(s)",
        )
    if pattern is not None and not pattern.match(value):
        raise SchemaValidationError(
            field=field,
            received=value,
            reason=f"'{field}' does not match pattern {pattern.pattern!r}",
        )


def _validate_tags(tags: Any) -> None:
    """Validate the tags dict; raise SchemaValidationError on any violation."""
    if not isinstance(tags, dict):
        raise SchemaValidationError(
            field="tags",
            received=tags,
            reason="'tags' must be an object",
        )
    if len(tags) > _MAX_TAG_KEYS:
        raise SchemaValidationError(
            field="tags",
            received=tags,
            reason=f"'tags' must contain at most {_MAX_TAG_KEYS} keys",
        )
    for k, v in tags.items():
        if not isinstance(k, str) or not k:
            raise SchemaValidationError(
                field=f"tags.{k!r}",
                received=k,
                reason="tag key must be a non-empty string",
            )
        if not isinstance(v, str) or not v:
            raise SchemaValidationError(
                field=f"tags.{k}",
                received=v,
                reason="tag value must be a non-empty string",
            )


def _stdlib_validate(doc: dict[str, Any]) -> None:
    """Perform structural validation without the ``jsonschema`` library.

    Checks required fields, types, and regex patterns as per the published
    JSON Schema spec.  Raises :exc:`~spanforge.exceptions.SchemaValidationError`
    on the first violation found.
    """
    if not isinstance(doc, dict):
        raise SchemaValidationError(
            field="<root>",
            received=doc,
            reason="event must serialise to a JSON object",
        )

    _check_string_field(doc, "schema_version")
    if doc["schema_version"] not in _ACCEPTED_SCHEMA_VERSIONS:
        raise SchemaValidationError(
            field="schema_version",
            received=doc["schema_version"],
            reason=f"'schema_version' must be one of {sorted(_ACCEPTED_SCHEMA_VERSIONS)!r}",
        )
    _check_string_field(doc, "event_id", pattern=_ULID_RE)
    _check_string_field(doc, "event_type", pattern=_EVENT_TYPE_RE)
    if not is_registered(doc["event_type"]):
        try:
            validate_custom(doc["event_type"])
        except EventTypeError as exc:
            raise SchemaValidationError(
                field="event_type",
                received=doc["event_type"],
                reason=str(exc),
            ) from exc
    _check_string_field(doc, "timestamp", pattern=_TIMESTAMP_RE)
    _check_string_field(doc, "source", pattern=_SOURCE_RE)

    # payload
    if "payload" not in doc:
        raise SchemaValidationError(
            field="payload",
            received=None,
            reason="required field 'payload' is missing",
        )
    if not isinstance(doc["payload"], dict) or not doc["payload"]:
        raise SchemaValidationError(
            field="payload",
            received=doc["payload"],
            reason="'payload' must be a non-empty object",
        )

    # Optional tracing fields
    for span_field in ("span_id", "parent_span_id"):
        _check_string_field(doc, span_field, required=False, pattern=_SPAN_ID_RE)
    _check_string_field(doc, "trace_id", required=False, pattern=_TRACE_ID_RE)

    # Optional context fields
    for ctx_field in ("org_id", "team_id", "actor_id", "session_id"):
        _check_string_field(doc, ctx_field, required=False, min_length=1)

    # Optional integrity fields — checksum and signature use distinct prefix patterns.
    _check_string_field(doc, "checksum", required=False, pattern=_CHECKSUM_RE)
    _check_string_field(doc, "signature", required=False, pattern=_SIGNATURE_RE)
    _check_string_field(doc, "prev_id", required=False, pattern=_ULID_RE)

    # tags
    if "tags" in doc:
        _validate_tags(doc["tags"])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_event(event: Event) -> None:
    """Validate *event* against the published v1.0 JSON Schema.

    Serialises *event* to a plain dict and validates the envelope structure.
    When the optional ``jsonschema`` package is installed, full Draft 2020-12
    validation is performed.  Otherwise a stdlib-only structural check is run
    that covers all required fields, types, and regex patterns.

    Parameters
    ----------
    event:
        The :class:`~spanforge.event.Event` instance to validate.

    Raises:
    ------
    SchemaValidationError
        If the event does not conform to the envelope schema.
    FileNotFoundError
        If the schema file is missing from the installed distribution.

    Examples:
    --------
    ::

        from spanforge import Event, EventType
        from spanforge.validate import validate_event

        event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source="llm-trace@0.3.1",
            payload={"span_name": "run", "status": "ok"},
        )
        validate_event(event)  # passes silently
    """
    if not isinstance(event, Event):
        raise TypeError(f"validate_event() expects an Event instance, got {type(event)!r}")

    doc = event.to_dict()

    # H9: bound-check event_id length and payload wire size before schema validation.
    event_id_val: str = doc.get("event_id", "")
    if len(event_id_val) > _MAX_EVENT_ID_LEN:
        raise SchemaValidationError(
            field="event_id",
            received=event_id_val,
            reason=(
                f"event_id length {len(event_id_val)} exceeds maximum "
                f"{_MAX_EVENT_ID_LEN} characters"
            ),
        )
    _payload_bytes = len(json.dumps(doc.get("payload", {}), default=str).encode())
    if _payload_bytes > _MAX_PAYLOAD_BYTES:
        raise SchemaValidationError(
            field="payload",
            received=None,
            reason=(
                f"payload size {_payload_bytes} bytes exceeds maximum {_MAX_PAYLOAD_BYTES} bytes"
            ),
        )

    # Select schema version from event envelope (RFC §15.5).
    schema_version: str = doc.get("schema_version") or _DEFAULT_SCHEMA_VERSION

    try:
        import jsonschema
        import jsonschema.exceptions

        schema = load_schema(schema_version)
        try:
            jsonschema.validate(instance=doc, schema=schema)
        except jsonschema.exceptions.ValidationError as exc:
            # Convert jsonschema's error into our domain error.
            field_path = ".".join(str(part) for part in exc.absolute_path) or "<root>"
            raise SchemaValidationError(
                field=field_path,
                received=exc.instance,
                reason=exc.message,
            ) from exc

    except ImportError:
        # jsonschema not installed — fall back to stdlib structural check.
        _stdlib_validate(doc)


# ---------------------------------------------------------------------------
# 1C-1: Enforcement mechanisms
# ---------------------------------------------------------------------------

_enforce_log = logging.getLogger(__name__)


class EnforcementMode(str, enum.Enum):
    """Validation enforcement mode used by :func:`enforce_event`.

    * ``STRICT``  — raise :exc:`~spanforge.exceptions.SchemaValidationError`
      on the **first** violation found (mirrors the behaviour of
      :func:`validate_event`).
    * ``LENIENT`` — collect **all** violations and raise a single
      :exc:`~spanforge.exceptions.SchemaValidationError` at the end that
      lists every violation in the message.
    * ``WARN``    — collect all violations, emit one ``WARNING`` log line per
      violation, and return without raising.
    * ``CORRECT`` — run :func:`correct_event` first (which auto-fixes known
      correctable problems), then validate the corrected document.  Returns
      the corrected event in :attr:`ValidationResult.corrected_doc`.
    """

    STRICT = "strict"
    LENIENT = "lenient"
    WARN = "warn"
    CORRECT = "correct"


@dataclass
class ValidationResult:
    """Result returned by :func:`enforce_event`.

    Attributes:
        valid: ``True`` if no violations were found (or all were corrected).
        mode: The enforcement mode that produced this result.
        violations: Human-readable list of violation messages.
        corrected_doc: The auto-corrected event document (only populated
            when ``mode=CORRECT``).
    """

    valid: bool
    mode: EnforcementMode
    violations: list[str] = field(default_factory=list)
    corrected_doc: dict[str, Any] | None = None


def enforce_event(
    event: Event | dict[str, Any],
    mode: EnforcementMode = EnforcementMode.STRICT,
) -> ValidationResult:
    """Validate *event* according to *mode* and return a :class:`ValidationResult`.

    Args:
        event: The event to validate.  May be an :class:`~spanforge.event.Event`
            instance or a raw ``dict``.
        mode: Enforcement mode controlling whether violations raise, warn, or
            are auto-corrected.

    Returns:
        A :class:`ValidationResult` instance.

    Raises:
        :exc:`~spanforge.exceptions.SchemaValidationError`: In ``STRICT`` or
            ``LENIENT`` mode when at least one violation is found.
    """
    doc: dict[str, Any] = event.to_dict() if isinstance(event, Event) else dict(event)

    if mode is EnforcementMode.CORRECT:
        doc = correct_event(doc)

    violations: list[str] = []

    # Collect violations by running validate_event and catching errors.
    # In STRICT mode we propagate immediately; in all others we gather.
    try:
        validate_event(Event.from_dict(doc) if not isinstance(event, Event) else event)
    except SchemaValidationError as exc:
        if mode is EnforcementMode.STRICT:
            raise
        violations.append(str(exc))
    except Exception as exc:  # noqa: BLE001
        if mode is EnforcementMode.STRICT:
            raise SchemaValidationError(field="<unknown>", received=None, reason=str(exc)) from exc
        violations.append(str(exc))

    if violations:
        if mode is EnforcementMode.LENIENT:
            raise SchemaValidationError(
                field="<multiple>",
                received=None,
                reason="; ".join(violations),
            )
        if mode is EnforcementMode.WARN:
            for v in violations:
                _enforce_log.warning("sf_validate [warn]: %s", v)
            return ValidationResult(valid=False, mode=mode, violations=violations)
        # CORRECT — violations remain after correction; report but don't raise
        return ValidationResult(valid=False, mode=mode, violations=violations, corrected_doc=doc)

    return ValidationResult(
        valid=True,
        mode=mode,
        violations=[],
        corrected_doc=doc if mode is EnforcementMode.CORRECT else None,
    )


# ---------------------------------------------------------------------------
# 1C-1: Correction pass
# ---------------------------------------------------------------------------

#: Top-level keys that are recognised in a v2.0 event envelope.
_KNOWN_ENVELOPE_KEYS: frozenset[str] = frozenset(
    {
        "event_id",
        "event_type",
        "schema_version",
        "source",
        "timestamp",
        "trace_id",
        "span_id",
        "payload",
        "tags",
        "checksum",
        "signature",
    }
)


def correct_event(doc: dict[str, Any]) -> dict[str, Any]:
    """Return a corrected copy of *doc* with known auto-fixable issues repaired.

    Corrections applied:
    1. Strip unknown top-level envelope keys.
    2. Normalise ``schema_version`` to the default (``"2.0"``) if missing or
       unrecognised.
    3. Strip ``None``-valued optional fields (``trace_id``, ``span_id``,
       ``tags``, ``checksum``, ``signature``).

    Args:
        doc: Raw event dict to correct.  The original is *not* mutated.

    Returns:
        A new dict with corrections applied.
    """
    out: dict[str, Any] = {}
    for k, v in doc.items():
        if k not in _KNOWN_ENVELOPE_KEYS:
            continue  # strip unknown keys
        if v is None and k in {"trace_id", "span_id", "tags", "checksum", "signature"}:
            continue  # strip None optional fields
        out[k] = v

    # Normalise schema_version
    sv = out.get("schema_version")
    if sv not in _ACCEPTED_SCHEMA_VERSIONS:
        out["schema_version"] = _DEFAULT_SCHEMA_VERSION

    return out


# ---------------------------------------------------------------------------
# 1C-1: HMAC signing
# ---------------------------------------------------------------------------


def sign_event_hmac(event: Event, key: str) -> Event:
    """Return a copy of *event* with an HMAC-SHA256 signature attached.

    The signature is computed over the canonical JSON serialisation of the
    event's ``to_dict()`` representation **excluding** any existing
    ``signature`` field.  The result is formatted as
    ``hmac-sha256:<64-hex-chars>`` and stored in ``event.signature``.

    Args:
        event: The event to sign.  A new :class:`~spanforge.event.Event`
            instance is returned; the original is not mutated.
        key: Secret key for the HMAC computation.  Must be a non-empty string.

    Returns:
        A new :class:`~spanforge.event.Event` with ``signature`` set.

    Raises:
        ValueError: If *key* is empty.
    """
    if not key:
        raise ValueError("sign_event_hmac: key must be non-empty")

    doc = event.to_dict()
    doc.pop("signature", None)  # exclude prior signature from the message
    message = json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()
    digest = hmac.new(key.encode(), message, hashlib.sha256).hexdigest()
    signature = f"hmac-sha256:{digest}"

    # Build a new Event with the signature attached
    updated = Event.from_dict({**event.to_dict(), "signature": signature})
    return updated


# ---------------------------------------------------------------------------
# 1C-4: Training Data Compliance Scanner
# ---------------------------------------------------------------------------

#: Compiled patterns for common PII field names (case-insensitive).
_PII_FIELD_NAME_RE: re.Pattern[str] = re.compile(
    r"(?:email|e_mail|phone|telephone|mobile|ssn|social_security|"
    r"passport|national_id|tax_id|credit_card|card_number|cvv|"
    r"bank_account|iban|date_of_birth|dob|ip_address|ipv4|ipv6|"
    r"mac_address|biometric|fingerprint|face_id|gps|latitude|longitude)",
    re.IGNORECASE,
)

#: Compiled patterns for PII *values* (email, phone, SSN etc.).
_PII_EMAIL_RE: re.Pattern[str] = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)
_PII_PHONE_RE: re.Pattern[str] = re.compile(r"\b(?:\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}\b")
_PII_SSN_RE: re.Pattern[str] = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


@dataclass
class DatasetScanFinding:
    """A single compliance finding in a dataset record.

    Attributes:
        row: 1-based row index of the finding.
        field: Field name where the finding occurred (``"<row>"`` for row-level issues).
        issue_type: Category — ``"pii_field_name"``, ``"pii_value"``,
            ``"schema_violation"``, or ``"parse_error"``.
        detail: Human-readable description of the finding.
    """

    row: int
    field: str
    issue_type: str
    detail: str


@dataclass
class DatasetScanReport:
    """Summary report from :func:`scan_dataset`.

    Attributes:
        total_rows: Total number of rows processed.
        total_findings: Total number of findings across all rows.
        clean_rows: Number of rows with zero findings.
        pii_hits: Number of findings categorised as PII (field name or value).
        schema_violations: Number of schema-related findings.
        parse_errors: Number of rows that could not be parsed.
        findings: Complete list of :class:`DatasetScanFinding` instances.
    """

    total_rows: int
    total_findings: int
    clean_rows: int
    pii_hits: int
    schema_violations: int
    parse_errors: int
    findings: list[DatasetScanFinding] = field(default_factory=list)


def scan_dataset(
    rows: list[dict[str, Any]],
    *,
    check_pii_field_names: bool = True,
    check_pii_values: bool = True,
    required_fields: list[str] | None = None,
) -> DatasetScanReport:
    """Scan a list of dataset records for compliance issues.

    Each record is a plain ``dict`` (e.g. from a JSONL file).  The scan
    checks for:

    * **PII field names** — field keys matching :data:`_PII_FIELD_NAME_RE`.
    * **PII values** — string values matching common email / phone / SSN
      patterns.
    * **Required field violations** — records missing any field listed in
      *required_fields*.

    Args:
        rows: List of record dicts to scan.
        check_pii_field_names: Whether to flag PII-like field names.
        check_pii_values: Whether to scan string values for PII patterns.
        required_fields: Optional list of field names that every record must
            contain.  Absence is reported as a ``"schema_violation"``.

    Returns:
        A :class:`DatasetScanReport` summarising all findings.
    """
    findings: list[DatasetScanFinding] = []
    required = list(required_fields or [])

    for row_idx, record in enumerate(rows, start=1):
        row_findings_before = len(findings)

        if not isinstance(record, dict):
            findings.append(
                DatasetScanFinding(
                    row=row_idx,
                    field="<row>",
                    issue_type="parse_error",
                    detail=f"row is not a dict: {type(record).__name__}",
                )
            )
            continue

        # Required field check
        for rf in required:
            if rf not in record:
                findings.append(
                    DatasetScanFinding(
                        row=row_idx,
                        field=rf,
                        issue_type="schema_violation",
                        detail=f"required field '{rf}' is missing",
                    )
                )

        # PII checks
        for key, value in record.items():
            if check_pii_field_names and _PII_FIELD_NAME_RE.search(str(key)):
                findings.append(
                    DatasetScanFinding(
                        row=row_idx,
                        field=str(key),
                        issue_type="pii_field_name",
                        detail=f"field name '{key}' matches PII pattern",
                    )
                )

            if check_pii_values and isinstance(value, str):
                if _PII_EMAIL_RE.search(value):
                    findings.append(
                        DatasetScanFinding(
                            row=row_idx,
                            field=str(key),
                            issue_type="pii_value",
                            detail=f"field '{key}' contains an email address",
                        )
                    )
                elif _PII_PHONE_RE.search(value):
                    findings.append(
                        DatasetScanFinding(
                            row=row_idx,
                            field=str(key),
                            issue_type="pii_value",
                            detail=f"field '{key}' contains a phone number",
                        )
                    )
                elif _PII_SSN_RE.search(value):
                    findings.append(
                        DatasetScanFinding(
                            row=row_idx,
                            field=str(key),
                            issue_type="pii_value",
                            detail=f"field '{key}' contains an SSN",
                        )
                    )

        _ = row_findings_before  # reserved for future per-row callbacks

    total_findings = len(findings)
    pii_hits = sum(1 for f in findings if f.issue_type in {"pii_field_name", "pii_value"})
    schema_violations = sum(1 for f in findings if f.issue_type == "schema_violation")
    parse_errors = sum(1 for f in findings if f.issue_type == "parse_error")
    rows_with_findings = len({f.row for f in findings})
    clean_rows = len(rows) - rows_with_findings

    return DatasetScanReport(
        total_rows=len(rows),
        total_findings=total_findings,
        clean_rows=clean_rows,
        pii_hits=pii_hits,
        schema_violations=schema_violations,
        parse_errors=parse_errors,
        findings=findings,
    )
