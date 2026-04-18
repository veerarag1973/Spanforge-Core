"""spanforge.sdk._types — Value objects for the SpanForge service SDK.

All types here are immutable or clearly documented as mutable where needed.

Security requirements
---------------------
*  :class:`SecretStr` **never** exposes its value via ``__repr__``,
   ``__str__``, or Python's pickle protocol.
*  :class:`APIKeyBundle` redacts its ``api_key`` field in ``__repr__``.
*  Equality on :class:`SecretStr` uses :func:`hmac.compare_digest` to
   resist timing-based side-channel attacks.
"""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, ClassVar

__all__ = [
    # Phase 1 — identity
    "APIKeyBundle",
    # Phase 3 — PII hardening
    "DSARExport",
    "ErasureReceipt",
    "JWTClaims",
    "KeyFormat",
    "KeyScope",
    "MagicLinkResult",
    "PIIAnonymisedResult",
    "PIIEntity",
    "PIIHeatMapEntry",
    "PIIPipelineResult",
    "PIIRedactionManifestEntry",
    "PIIStatusInfo",
    "PIITextScanResult",
    "QuotaTier",
    "RateLimitInfo",
    # Phase 2 — PII
    "SFPIIAnonymizeResult",
    "SFPIIHit",
    "SFPIIRedactResult",
    "SFPIIScanResult",
    "SafeHarborResult",
    "SecretStr",
    "TOTPEnrollResult",
    "TokenIntrospectionResult",
    "TrainingDataPIIReport",
    # Phase 4 — Audit service
    "Article30Record",
    "AuditAppendResult",
    "AuditStatusInfo",
    "SignedRecord",
    "TrustDimension",
    "TrustScorecard",
    # Phase 5 — Compliance Evidence Chain
    "BundleResult",
    "BundleVerificationResult",
    "CECStatusInfo",
    "ClauseMapEntry",
    "ClauseSatisfaction",
    "DPADocument",
    # Phase 6 — Observability Named SDK
    "Annotation",
    "ExportResult",
    "ObserveStatusInfo",
    "ReceiverConfig",
    "SamplerStrategy",
    # Phase 7 — Alert Routing Service
    "AlertRecord",
    "AlertSeverity",
    "AlertStatusInfo",
    "MaintenanceWindow",
    "PublishResult",
    "TopicRegistration",
]

# ---------------------------------------------------------------------------
# API key format constant
# ---------------------------------------------------------------------------

#: Regex for valid SpanForge API keys: ``sf_(live|test)_<48 base62 chars>``
_KEY_PATTERN: re.Pattern[str] = re.compile(r"^sf_(?:live|test)_[0-9A-Za-z]{48}$")

# ---------------------------------------------------------------------------
# SecretStr — a string that hides its value
# ---------------------------------------------------------------------------


class SecretStr:
    """A string whose value is never exposed by ``__repr__`` or ``__str__``.

    Use :meth:`get_secret_value` to retrieve the underlying string for
    cryptographic operations.  All other operations (repr, str, pickle)
    deliberately conceal the value to prevent accidental leakage into logs,
    error messages, or serialised state.

    Equality comparisons use :func:`hmac.compare_digest` to resist
    timing-based side-channel attacks.

    Example::

        key = SecretStr("sf_live_abc...")
        print(key)               # <SecretStr:***>
        print(repr(key))         # <SecretStr:***>
        print(key.get_secret_value())  # sf_live_abc...
    """

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        object.__setattr__(self, "_value", value)

    # ------------------------------------------------------------------
    # Prevent accidental exposure
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return "<SecretStr:***>"

    def __str__(self) -> str:
        return "<SecretStr:***>"

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("SecretStr is immutable")

    def __reduce__(self) -> None:  # type: ignore[override]
        """Prevent pickling to avoid secret leakage via serialised objects."""
        raise TypeError(
            "SecretStr cannot be pickled. "
            "Extract the secret value with get_secret_value() before serialising."
        )

    # ------------------------------------------------------------------
    # Timing-safe equality
    # ------------------------------------------------------------------

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SecretStr):
            a = object.__getattribute__(self, "_value")
            b = object.__getattribute__(other, "_value")
            return hmac.compare_digest(a, b)
        return NotImplemented

    def __hash__(self) -> int:
        return hash(object.__getattribute__(self, "_value"))

    # ------------------------------------------------------------------
    # Intentional access
    # ------------------------------------------------------------------

    def get_secret_value(self) -> str:
        """Return the underlying secret string.

        Call this explicitly and only where the raw value is needed (e.g.
        to set an HTTP header or perform a cryptographic operation).  Do not
        pass the result to logging calls.
        """
        return str(object.__getattribute__(self, "_value"))

    def __len__(self) -> int:
        """Return length without exposing value — safe for format checks."""
        return len(object.__getattribute__(self, "_value"))


# ---------------------------------------------------------------------------
# KeyFormat — API key validation helpers
# ---------------------------------------------------------------------------


class KeyFormat:
    """Validate and inspect SpanForge API key format.

    Valid format: ``sf_live_<48 base62 chars>`` or ``sf_test_<48 base62 chars>``.

    Example::

        KeyFormat.validate("sf_live_" + "A" * 48)   # OK
        KeyFormat.validate("bad-key")                 # raises SFKeyFormatError
    """

    PATTERN: re.Pattern[str] = _KEY_PATTERN

    @classmethod
    def validate(cls, key: str) -> None:
        """Raise :exc:`~spanforge.sdk._exceptions.SFKeyFormatError` if invalid."""
        from spanforge.sdk._exceptions import SFKeyFormatError

        if not isinstance(key, str) or not cls.PATTERN.match(key):
            raise SFKeyFormatError(
                f"Key must match sf_(live|test)_<48 base62 chars>. "
                f"Received length={len(key) if isinstance(key, str) else 'non-string'}."
            )

    @classmethod
    def is_test_key(cls, key: str) -> bool:
        """Return ``True`` if *key* is a test-mode key."""
        return isinstance(key, str) and key.startswith("sf_test_")

    @classmethod
    def is_live_key(cls, key: str) -> bool:
        """Return ``True`` if *key* is a live-mode key."""
        return isinstance(key, str) and key.startswith("sf_live_")

    @classmethod
    def is_valid(cls, key: str) -> bool:
        """Return ``True`` without raising if *key* matches the format."""
        return isinstance(key, str) and bool(cls.PATTERN.match(key))


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass
class KeyScope:
    """Scoping constraints attached to an API key.

    All fields default to *empty / unrestricted*.  Non-empty lists restrict
    access to the listed values only.

    Attributes:
        pillar_whitelist: SpanForge service names the key may call (e.g.
            ``["sf_pii", "sf_audit"]``).  Empty = unrestricted.
        project_scope: Project IDs the key may act on.  Empty = unrestricted.
        ip_allowlist: CIDR strings (e.g. ``["192.168.1.0/24", "10.0.0.1/32"]``).
            Empty = unrestricted.
        expires_at: Optional hard expiry.  ``None`` = no expiry.
    """

    pillar_whitelist: list[str] = field(default_factory=list)
    project_scope: list[str] = field(default_factory=list)
    ip_allowlist: list[str] = field(default_factory=list)
    expires_at: datetime | None = None

    def is_expired(self) -> bool:
        """Return ``True`` if the key has passed its hard expiry."""
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= self.expires_at

    def allows_service(self, service_name: str) -> bool:
        """Return ``True`` if this scope permits calls to *service_name*."""
        if not self.pillar_whitelist:
            return True
        return service_name in self.pillar_whitelist

    def allows_project(self, project_id: str) -> bool:
        """Return ``True`` if this scope permits acting on *project_id*."""
        if not self.project_scope:
            return True
        return project_id in self.project_scope


@dataclass
class APIKeyBundle:
    """Result of issuing or rotating a SpanForge API key.

    The ``api_key`` field is a :class:`SecretStr` and must be presented to
    the user **once** at issuance time only.  SpanForge never returns it
    again after the initial issuance response.

    Attributes:
        api_key: The raw key value (write-once; never log).
        key_id: Opaque identifier used for ``rotate_key`` / ``revoke_key``.
        jwt: RS256 (or HS256 in local mode) session JWT.
        expires_at: When the session JWT expires.
        scopes: Permission scopes granted to this key.
    """

    api_key: SecretStr
    key_id: str
    jwt: str
    expires_at: datetime
    scopes: list[str] = field(default_factory=list)

    def __repr__(self) -> str:
        return (
            f"APIKeyBundle("
            f"key_id={self.key_id!r}, "
            f"expires_at={self.expires_at.isoformat()!r}, "
            f"scopes={self.scopes!r}, "
            f"api_key=<redacted>)"
        )


@dataclass
class JWTClaims:
    """Decoded and validated JWT payload.

    Attributes:
        subject: The ``sub`` claim — typically the ``key_id``.
        scopes: Permission scopes extracted from the JWT.
        project_id: The ``aud`` claim.
        expires_at: Token expiry (UTC).
        issued_at: Token issuance time (UTC).
        jti: Unique JWT ID used for revocation checks.
        issuer: The ``iss`` claim.
    """

    subject: str
    scopes: list[str]
    project_id: str
    expires_at: datetime
    issued_at: datetime
    jti: str
    issuer: str = "spanforge"

    def is_expired(self) -> bool:
        """Return ``True`` if the JWT has passed its expiry."""
        return datetime.now(timezone.utc) >= self.expires_at


@dataclass
class RateLimitInfo:
    """Current rate-limit state for a key.

    Attributes:
        limit: Total requests allowed per window.
        remaining: Requests remaining in the current window.
        reset_at: When the window resets (UTC).
    """

    limit: int
    remaining: int
    reset_at: datetime


@dataclass
class TokenIntrospectionResult:
    """RFC 7662 token introspection response.

    Attributes:
        active: ``True`` if the token is currently valid.
        scope: Space-separated list of scopes.
        exp: Unix timestamp of expiry, or ``None``.
        sub: Subject claim.
        client_id: Client identifier.
    """

    active: bool
    scope: str = ""
    exp: int | None = None
    sub: str = ""
    client_id: str = ""


@dataclass
class MagicLinkResult:
    """Result of :meth:`~spanforge.sdk.identity.SFIdentityClient.issue_magic_link`.

    Attributes:
        link_id: Opaque ID used to look up the link record.
        expires_at: When the one-time link expires (15 min from issuance, UTC).
    """

    link_id: str
    expires_at: datetime


@dataclass
class TOTPEnrollResult:
    """Result of :meth:`~spanforge.sdk.identity.SFIdentityClient.enroll_totp`.

    Attributes:
        secret_base32: Base32-encoded TOTP secret.  **Display once then
            discard** — never store this in logs or database plaintext.
        qr_uri: ``otpauth://`` URI suitable for encoding as a QR code.
        backup_codes: 8 single-use, 8-character alphanumeric codes.
            Store hashed (already done server-side); present plaintext to
            user exactly once.
    """

    secret_base32: SecretStr
    qr_uri: str
    backup_codes: list[str]  # plaintext; user must save these

    def __repr__(self) -> str:
        return (
            f"TOTPEnrollResult("
            f"qr_uri={self.qr_uri!r}, "
            f"backup_codes=<{len(self.backup_codes)} codes redacted>, "
            f"secret_base32=<redacted>)"
        )


# ---------------------------------------------------------------------------
# Quota tier constants
# ---------------------------------------------------------------------------


class QuotaTier:
    """Named quota tier constants.

    Attributes:
        FREE:       Local CLI only (no network calls allowed).
        API:        $99 / month — 10 000 scored records / day.
        TEAM:       $499 / month — 100 000 scored records / day.
        ENTERPRISE: Unlimited.
    """

    FREE = "free"
    API = "api"
    TEAM = "team"
    ENTERPRISE = "enterprise"

    #: Mapping from tier name to daily quota (-1 = unlimited).
    DAILY_LIMITS: ClassVar[dict[str, int]] = {
        FREE: 0,
        API: 10_000,
        TEAM: 100_000,
        ENTERPRISE: -1,
    }

    @classmethod
    def daily_limit(cls, tier: str) -> int:
        """Return daily record limit for *tier* (``-1`` = unlimited)."""
        return cls.DAILY_LIMITS.get(tier, 0)


# ---------------------------------------------------------------------------
# Phase 2 — PII redaction service types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SFPIIHit:
    """A single PII detection hit returned by :meth:`~spanforge.sdk.pii.SFPIIClient.scan`.

    Attributes:
        pii_type:    PII category label (e.g. ``"email"``, ``"ssn"``,
                     ``"credit_card"``, ``"phone"``).
        path:        Dot-separated path to the detected field within the
                     payload (empty string for top-level string values).
        match_count: Number of regex matches of this type at this path.
        sensitivity: Sensitivity level: ``"high"``, ``"medium"``, or ``"low"``.
    """

    pii_type: str
    path: str
    match_count: int = 1
    sensitivity: str = "medium"


@dataclass(frozen=True)
class SFPIIScanResult:
    """Aggregated result of a PII scan operation.

    Attributes:
        hits:    All :class:`SFPIIHit` instances detected.  Empty when clean.
        scanned: Total number of string values examined during the scan.
    """

    hits: list[SFPIIHit]
    scanned: int

    @property
    def clean(self) -> bool:
        """``True`` when no PII was detected."""
        return len(self.hits) == 0


@dataclass(frozen=True)
class SFPIIRedactResult:
    """Result of a PII redaction operation.

    Attributes:
        event:           The newly reconstructed event with PII fields replaced
                         by safe marker strings (e.g. ``"[REDACTED:pii]"``).
        redaction_count: Number of :class:`~spanforge.redact.Redactable` fields
                         that were scrubbed by the policy.
        redacted_at:     UTC ISO-8601 timestamp when redaction was applied.
        redacted_by:     Policy identifier string embedded in the result.
    """

    event: Any
    redaction_count: int
    redacted_at: str
    redacted_by: str


@dataclass(frozen=True)
class SFPIIAnonymizeResult:
    """Result of a text anonymization operation.

    Attributes:
        text:            The anonymized text with PII replaced by type-tagged
                         markers (e.g. ``"[REDACTED:email]"``).
        replacements:    Total count of PII segments replaced across all
                         pattern types.
        pii_types_found: Ordered list of distinct PII type labels detected
                         (e.g. ``["email", "phone"]``).
    """

    text: str
    replacements: int
    pii_types_found: list[str]


# ---------------------------------------------------------------------------
# Phase 3 — PII Service Hardening types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PIIEntity:
    """A single character-level PII entity detected by Presidio.

    Attributes:
        type:  PII entity type label (e.g. ``"EMAIL_ADDRESS"``, ``"US_SSN"``).
        start: Start character offset in the scanned text.
        end:   End character offset in the scanned text (exclusive).
        score: Presidio confidence score in ``[0.0, 1.0]``.
    """

    type: str
    start: int
    end: int
    score: float


@dataclass(frozen=True)
class PIITextScanResult:
    """Result of a presidio-backed text scan (PII-001).

    Attributes:
        entities:      List of character-level :class:`PIIEntity` instances.
        redacted_text: The input text with each detected entity replaced by
                       ``<TYPE>`` (e.g. ``<EMAIL_ADDRESS>``).
        detected:      ``True`` if at least one entity was found.
    """

    entities: list[PIIEntity]
    redacted_text: str
    detected: bool


@dataclass(frozen=True)
class PIIRedactionManifestEntry:
    """One entry in an anonymise() redaction manifest.

    Attributes:
        field_path:    Dot-separated path to the field within the payload.
        type:          PII type label (e.g. ``"email"``, ``"ssn"``).
        original_hash: SHA-256 hex digest of the original value — for audit
                       without disclosing the raw PII.
        replacement:   The placeholder string that replaced the original value
                       (e.g. ``"<EMAIL>"``).
    """

    field_path: str
    type: str
    original_hash: str
    replacement: str


@dataclass(frozen=True)
class PIIAnonymisedResult:
    """Result of :meth:`~spanforge.sdk.pii.SFPIIClient.anonymise` (PII-002).

    Attributes:
        clean_payload:       A deep copy of the input payload with all detected
                             PII replaced by ``<TYPE>`` placeholders.
        redaction_manifest:  Ordered list of :class:`PIIRedactionManifestEntry`
                             items — one per replacement, in traversal order.
    """

    clean_payload: dict[str, Any]
    redaction_manifest: list[PIIRedactionManifestEntry]


@dataclass(frozen=True)
class PIIPipelineResult:
    """Result of :meth:`~spanforge.sdk.pii.SFPIIClient.apply_pipeline_action` (PII-010/011/012).

    Attributes:
        text:               The effective text after the action was applied.
                            For ``"redact"`` this is the redacted text; for
                            ``"flag"`` / ``"block"`` it is the original text.
        action:             The action that was applied: ``"flag"``,
                            ``"redact"``, or ``"block"``.
        detected:           ``True`` if any entity was detected above the
                            confidence threshold.
        entity_types:       List of entity type labels that triggered the
                            action (above-threshold hits only).
        low_confidence_hits: List of :class:`PIIEntity` instances that were
                             below the threshold — recorded for audit only.
        redacted_text:      The redacted form of the input text (always
                            populated, even for ``"flag"``).
        blocked:            ``True`` when *action* is ``"block"`` and PII
                            was detected at or above the threshold.
    """

    text: str
    action: str
    detected: bool
    entity_types: list[str]
    low_confidence_hits: list[PIIEntity]
    redacted_text: str
    blocked: bool


@dataclass(frozen=True)
class PIIStatusInfo:
    """sf-pii service status (PII-005).

    Attributes:
        status:               Service status: ``"ok"`` or ``"degraded"``.
        presidio_available:   ``True`` if the presidio-analyzer package is
                              importable.
        entity_types_loaded:  List of entity type labels currently loaded
                              (regex + presidio combined).
        last_scan_at:         ISO-8601 UTC timestamp of the most recent scan,
                              or ``None`` if no scan has run since startup.
    """

    status: str
    presidio_available: bool
    entity_types_loaded: list[str]
    last_scan_at: str | None


@dataclass(frozen=True)
class ErasureReceipt:
    """Receipt for a GDPR Article 17 erasure request (PII-021).

    Attributes:
        subject_id:           The data subject whose records were erased.
        project_id:           Scoping project for the erasure.
        records_erased:       Number of audit records found and marked for
                              erasure.
        erasure_id:           Opaque UUID for the erasure event itself.
        erased_at:            ISO-8601 UTC timestamp of the erasure.
        exceptions:           Any Article 17(3) exceptions that prevented
                              full erasure (list of reason strings).
    """

    subject_id: str
    project_id: str
    records_erased: int
    erasure_id: str
    erased_at: str
    exceptions: list[str]


@dataclass(frozen=True)
class DSARExport:
    """CCPA/DSAR export package (PII-022).

    Attributes:
        subject_id:    The data subject whose records were exported.
        project_id:    Scoping project.
        event_count:   Number of events included in the export.
        export_id:     Opaque UUID for this export package.
        exported_at:   ISO-8601 UTC timestamp.
        events:        Serialised event records (dicts) — PII-safe subset.
    """

    subject_id: str
    project_id: str
    event_count: int
    export_id: str
    exported_at: str
    events: list[dict[str, Any]]


@dataclass(frozen=True)
class SafeHarborResult:
    """Result of HIPAA Safe Harbor de-identification (PII-023).

    Attributes:
        text:            De-identified text with all 18 PHI identifiers
                         removed or generalised per 45 CFR §164.514(b)(2).
        replacements:    Number of PHI identifiers that were replaced or
                         generalised.
        phi_types_found: List of PHI identifier type labels that were
                         encountered (e.g. ``["name", "date", "zip"]``).
    """

    text: str
    replacements: int
    phi_types_found: list[str]


@dataclass(frozen=True)
class PIIHeatMapEntry:
    """One data point in the PII heat map (PII-032).

    Attributes:
        project_id:   Project the scan belongs to.
        entity_type:  PII entity type label (e.g. ``"email"``, ``"ssn"``).
        date:         Calendar date in ``YYYY-MM-DD`` format.
        count:        Number of detections of this entity type on this date.
    """

    project_id: str
    entity_type: str
    date: str
    count: int


@dataclass(frozen=True)
class TrainingDataPIIReport:
    """PII prevalence report for a training dataset (PII-025).

    Attributes:
        dataset_path:    Path to the scanned dataset file.
        total_records:   Total number of records scanned.
        pii_records:     Number of records that contained at least one PII hit.
        prevalence_pct:  ``pii_records / total_records * 100`` (or 0.0).
        entity_counts:   Mapping of entity type label → total hit count
                         across all records.
        report_id:       Opaque UUID for this report.
        generated_at:    ISO-8601 UTC timestamp.
    """

    dataset_path: str
    total_records: int
    pii_records: int
    prevalence_pct: float
    entity_counts: dict[str, int]
    report_id: str
    generated_at: str


# ---------------------------------------------------------------------------
# Phase 4 — Audit Service High-Level API types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuditAppendResult:
    """Result of :meth:`~spanforge.sdk.audit.SFAuditClient.append` (AUD-001).

    Attributes:
        record_id:       Unique identifier for the audit record (ULID string).
        chain_position:  Zero-based position of this record in the HMAC chain.
        timestamp:       ISO-8601 UTC timestamp assigned at append time.
        hmac:            ``"hmac-sha256:<hex>"`` signature of this record.
        schema_key:      The schema key under which this record was stored.
        backend:         Storage backend used: ``"local"``, ``"s3"``,
                         ``"azure"``, ``"gcs"``, ``"r2"``, or ``"trust_only"``.
    """

    record_id: str
    chain_position: int
    timestamp: str
    hmac: str
    schema_key: str
    backend: str = "local"


@dataclass(frozen=True)
class SignedRecord:
    """A raw-dict record signed with an HMAC-SHA256 signature (AUD-003).

    Attributes:
        record:    The original record dict.
        record_id: Unique identifier for this record.
        checksum:  ``"sha256:<hex>"`` digest of the canonical JSON payload.
        signature: ``"hmac-sha256:<hex>"`` HMAC signature.
        timestamp: ISO-8601 UTC timestamp when the record was signed.
    """

    record: dict[str, Any]
    record_id: str
    checksum: str
    signature: str
    timestamp: str


@dataclass(frozen=True)
class TrustDimension:
    """One dimension of the T.R.U.S.T. scorecard (AUD-031).

    Attributes:
        score:        Normalised score in ``[0, 100]``.
        trend:        Direction of recent movement: ``"up"``, ``"flat"``,
                      or ``"down"``.
        last_updated: ISO-8601 UTC timestamp of the most recent signal.
    """

    score: float
    trend: str
    last_updated: str


@dataclass(frozen=True)
class TrustScorecard:
    """Aggregated T.R.U.S.T. scorecard for a project (AUD-031).

    Attributes:
        project_id:          Scoping project.
        from_dt:             ISO-8601 UTC start of the reporting window.
        to_dt:               ISO-8601 UTC end of the reporting window.
        hallucination:       T.R.U.S.T. hallucination score dimension.
        pii_hygiene:         PII detection/redaction hygiene dimension.
        secrets_hygiene:     Secrets scanning hygiene dimension.
        gate_pass_rate:      CI/CD gate pass-rate dimension.
        compliance_posture:  Compliance evidence posture dimension.
        record_count:        Total audit records contributing to this scorecard.
    """

    project_id: str
    from_dt: str
    to_dt: str
    hallucination: TrustDimension
    pii_hygiene: TrustDimension
    secrets_hygiene: TrustDimension
    gate_pass_rate: TrustDimension
    compliance_posture: TrustDimension
    record_count: int


@dataclass(frozen=True)
class Article30Record:
    """GDPR Article 30 Record of Processing Activities (AUD-042).

    Attributes:
        project_id:           Scoping project.
        controller_name:      Name of the data controller.
        processor_name:       Name of the data processor (SpanForge).
        processing_purposes:  List of processing purposes.
        data_categories:      Categories of personal data processed.
        data_subjects:        Categories of data subjects.
        recipients:           List of recipient categories.
        third_country:        Whether data is transferred to a third country.
        retention_period:     Retention period description.
        security_measures:    List of technical/organisational measures.
        generated_at:         ISO-8601 UTC timestamp when the record was generated.
        record_id:            Opaque UUID for this Article 30 record.
    """

    project_id: str
    controller_name: str
    processor_name: str
    processing_purposes: list[str]
    data_categories: list[str]
    data_subjects: list[str]
    recipients: list[str]
    third_country: bool
    retention_period: str
    security_measures: list[str]
    generated_at: str
    record_id: str


@dataclass(frozen=True)
class AuditStatusInfo:
    """sf-audit service status.

    Attributes:
        status:            Service status: ``"ok"`` or ``"degraded"``.
        backend:           Active backend name: ``"local"``, ``"s3"``,
                           ``"azure"``, ``"gcs"``, or ``"r2"``.
        byos_enabled:      ``True`` if a BYOS provider is configured.
        record_count:      Total number of records in the local store.
        last_append_at:    ISO-8601 UTC timestamp of the most recent append,
                           or ``None`` if no record has been appended.
        schema_count:      Number of distinct schema keys in the registry.
        index_healthy:     ``True`` if the SQLite query index is healthy.
        retention_years:   Configured retention period in years.
    """

    status: str
    backend: str
    byos_enabled: bool
    record_count: int
    last_append_at: str | None
    schema_count: int
    index_healthy: bool
    retention_years: int


# ---------------------------------------------------------------------------
# Phase 5 — Compliance Evidence Chain (sf-cec) types
# ---------------------------------------------------------------------------

import enum as _enum


class ClauseSatisfaction(_enum.Enum):
    """Satisfaction status for a single regulatory clause in a CEC bundle.

    Attributes:
        SATISFIED: Sufficient evidence records exist for this clause.
        PARTIAL:   Some evidence exists but below the minimum threshold.
        GAP:       No evidence records found for this clause.
    """

    SATISFIED = "SATISFIED"
    PARTIAL = "PARTIAL"
    GAP = "GAP"


@dataclass(frozen=True)
class ClauseMapEntry:
    """One clause entry in ``clause_map.json`` (CEC-010 through CEC-014).

    Attributes:
        framework:       Regulatory framework identifier (e.g. ``"eu_ai_act"``).
        clause_id:       Clause identifier within the framework (e.g.
                         ``"Art.9"``).
        title:           Human-readable clause title.
        status:          :class:`ClauseSatisfaction` value.
        evidence_count:  Number of audit records supporting this clause.
        evidence_ids:    Up to 20 record IDs providing evidence.
        description:     Short description of what the clause requires.
    """

    framework: str
    clause_id: str
    title: str
    status: ClauseSatisfaction
    evidence_count: int
    evidence_ids: list[str]
    description: str


@dataclass(frozen=True)
class BundleResult:
    """Result of :meth:`~spanforge.sdk.cec.SFCECClient.build_bundle` (CEC-001).

    Attributes:
        bundle_id:      Opaque UUID identifying this CEC bundle.
        download_url:   Signed URL (local file path in local mode) to the ZIP.
        expires_at:     ISO-8601 UTC timestamp when the download URL expires.
        hmac_manifest:  ``"hmac-sha256:<hex>"`` signature over ``manifest.json``.
        record_counts:  Mapping of schema key → number of records exported.
        zip_path:       Absolute path to the assembled ZIP file.
        frameworks:     List of regulatory framework identifiers included.
        project_id:     Project this bundle covers.
        generated_at:   ISO-8601 UTC timestamp of bundle generation.
    """

    bundle_id: str
    download_url: str
    expires_at: str
    hmac_manifest: str
    record_counts: dict[str, int]
    zip_path: str
    frameworks: list[str]
    project_id: str
    generated_at: str


@dataclass(frozen=True)
class BundleVerificationResult:
    """Result of :meth:`~spanforge.sdk.cec.SFCECClient.verify_bundle` (CEC-005).

    Attributes:
        bundle_id:          Bundle identifier extracted from the manifest.
        manifest_valid:     ``True`` if the manifest HMAC verifies correctly.
        chain_valid:        ``True`` if the embedded chain_proof.json is valid.
        timestamp_valid:    ``True`` if the RFC 3161 timestamp stub is present.
        overall_valid:      ``True`` if all three checks pass.
        errors:             List of human-readable validation error strings.
    """

    bundle_id: str
    manifest_valid: bool
    chain_valid: bool
    timestamp_valid: bool
    overall_valid: bool
    errors: list[str]


@dataclass(frozen=True)
class DPADocument:
    """GDPR Article 28 Data Processing Agreement (CEC-015).

    Attributes:
        project_id:         Scoping project.
        controller_name:    Legal name of the data controller.
        controller_address: Registered address of the controller.
        processor_name:     Legal name of the data processor (SpanForge).
        processor_address:  Registered address of the processor.
        processing_purposes: List of processing purpose descriptions.
        data_categories:    Categories of personal data processed.
        data_subjects:      Categories of data subjects.
        sub_processors:     List of sub-processor names authorised.
        transfer_mechanism: Cross-border transfer mechanism (e.g. ``"SCCs"``).
        retention_period:   Retention period description.
        security_measures:  List of technical / organisational security measures.
        scc_clauses:        EU Standard Contractual Clauses module applied
                            (e.g. ``"Module 2 (controller-to-processor)"``).
        document_id:        Opaque UUID for this DPA document.
        generated_at:       ISO-8601 UTC timestamp.
        text:               Full plain-text body of the DPA.
    """

    project_id: str
    controller_name: str
    controller_address: str
    processor_name: str
    processor_address: str
    processing_purposes: list[str]
    data_categories: list[str]
    data_subjects: list[str]
    sub_processors: list[str]
    transfer_mechanism: str
    retention_period: str
    security_measures: list[str]
    scc_clauses: str
    document_id: str
    generated_at: str
    text: str


@dataclass(frozen=True)
class CECStatusInfo:
    """sf-cec service status.

    Attributes:
        status:          Service status: ``"ok"`` or ``"degraded"``.
        byos_enabled:    ``True`` if a BYOS provider is configured.
        bundle_count:    Total number of bundles generated in this session.
        last_bundle_at:  ISO-8601 UTC timestamp of the most recent bundle
                         generation, or ``None`` if none generated yet.
        frameworks_supported: List of regulatory framework identifiers
                              supported by this installation.
    """

    status: str
    byos_enabled: bool
    bundle_count: int
    last_bundle_at: str | None
    frameworks_supported: list[str]


# ---------------------------------------------------------------------------
# Phase 6 — Observability Named SDK (sf-observe) types
# ---------------------------------------------------------------------------


class SamplerStrategy(_enum.Enum):
    """Trace sampling strategy for :class:`~spanforge.sdk.observe.SFObserveClient`.

    Attributes:
        ALWAYS_ON:    Every span is exported.
        ALWAYS_OFF:   No spans are exported.
        PARENT_BASED: Respect parent sampling decision; use
                      :attr:`ALWAYS_ON` when there is no parent.
        TRACE_ID_RATIO: Export a deterministic fraction of traces based on
                        the trace-ID hash (see ``sample_rate``).
    """

    ALWAYS_ON = "always_on"
    ALWAYS_OFF = "always_off"
    PARENT_BASED = "parent_based"
    TRACE_ID_RATIO = "trace_id_ratio"


@dataclass(frozen=True)
class ReceiverConfig:
    """Per-call receiver override for :meth:`~spanforge.sdk.observe.SFObserveClient.export_spans`.

    When provided, overrides the global endpoint and headers for a single
    ``export_spans`` call.

    Attributes:
        endpoint:        Target OTLP/HTTP receiver URL
                         (e.g. ``"https://collector.example.com/v1/traces"``).
        headers:         Extra HTTP headers to include (e.g. authorization).
        timeout_seconds: Per-request timeout in seconds (default: 30).
    """

    endpoint: str
    headers: dict[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0


@dataclass(frozen=True)
class ExportResult:
    """Result of :meth:`~spanforge.sdk.observe.SFObserveClient.export_spans` (OBS-001).

    Attributes:
        exported_count: Number of spans successfully exported.
        failed_count:   Number of spans that could not be exported.
        backend:        Backend used: ``"local"``, ``"otlp"``, ``"datadog"``,
                        ``"grafana"``, ``"splunk"``, or ``"elastic"``.
        exported_at:    ISO-8601 UTC timestamp of the export.
    """

    exported_count: int
    failed_count: int
    backend: str
    exported_at: str


@dataclass(frozen=True)
class Annotation:
    """An observability annotation stored by
    :meth:`~spanforge.sdk.observe.SFObserveClient.add_annotation` (OBS-002).

    Attributes:
        annotation_id: Opaque UUID for this annotation.
        event_type:    Category label for the annotation (e.g.
                       ``"model_deployed"``, ``"alert_fired"``).
        payload:       Arbitrary key/value metadata (must be JSON-serialisable).
        project_id:    Project scope for this annotation.
        created_at:    ISO-8601 UTC timestamp when the annotation was stored.
    """

    annotation_id: str
    event_type: str
    payload: dict[str, Any]
    project_id: str
    created_at: str


@dataclass(frozen=True)
class ObserveStatusInfo:
    """sf-observe service status returned by
    :meth:`~spanforge.sdk.observe.SFObserveClient.get_status`.

    Attributes:
        status:           Service status: ``"ok"`` or ``"degraded"``.
        backend:          Active exporter backend name.
        sampler_strategy: Active :class:`SamplerStrategy` label.
        span_count:       Total spans emitted in this session.
        annotation_count: Total annotations stored in this session.
        export_count:     Total export calls completed in this session.
        last_export_at:   ISO-8601 UTC timestamp of the most recent export,
                          or ``None`` if none yet.
        healthy:          ``True`` if the last export succeeded (or no export
                          has been attempted).
    """

    status: str
    backend: str
    sampler_strategy: str
    span_count: int
    annotation_count: int
    export_count: int
    last_export_at: str | None
    healthy: bool


# ---------------------------------------------------------------------------
# Phase 7 — Alert Routing Service
# ---------------------------------------------------------------------------

import enum as _enum


class AlertSeverity(_enum.Enum):
    """Severity levels for :class:`PublishResult` and alert history.

    Values are ordered from least to most severe.  Use
    :meth:`AlertSeverity.from_str` to parse a case-insensitive string.
    """

    INFO = "info"
    WARNING = "warning"
    HIGH = "high"
    CRITICAL = "critical"

    @classmethod
    def from_str(cls, value: str) -> "AlertSeverity":
        """Parse a severity string, returning WARNING on unknown values."""
        try:
            return cls(value.lower())
        except ValueError:
            return cls.WARNING


@dataclass(frozen=True)
class PublishResult:
    """Result of :meth:`~spanforge.sdk.alert.SFAlertClient.publish`.

    Attributes:
        alert_id:   UUID4 string uniquely identifying this alert emission.
        routed_to:  List of sink names that were notified (may be empty when
                    suppressed).
        suppressed: ``True`` when the alert was deduplicated, maintenance-window
                    suppressed, or rate-limited and **not** dispatched.
    """

    alert_id: str
    routed_to: list[str]
    suppressed: bool


@dataclass(frozen=True)
class TopicRegistration:
    """A registered alert topic with metadata.

    Attributes:
        topic:            Canonical topic string (e.g. ``"halluccheck.drift.red"``).
        description:      Human-readable purpose of the topic.
        default_severity: Default :class:`AlertSeverity` applied when the caller
                          does not specify one.
        runbook_url:      Optional URL to a runbook for this alert topic.
        dedup_window_seconds: Per-topic deduplication window in seconds
                              (overrides the client-wide default).
    """

    topic: str
    description: str
    default_severity: str
    runbook_url: str | None = None
    dedup_window_seconds: float | None = None


@dataclass(frozen=True)
class MaintenanceWindow:
    """A scheduled maintenance window during which all alerts are suppressed.

    Attributes:
        project_id: Project whose alerts are suppressed.
        start:      Window start (UTC).
        end:        Window end (UTC).
    """

    project_id: str
    start: datetime
    end: datetime


@dataclass(frozen=True)
class AlertRecord:
    """An entry in the in-memory alert history.

    Attributes:
        alert_id:       UUID4 of the alert.
        topic:          Full topic string.
        severity:       Severity string (e.g. ``"critical"``).
        project_id:     Project scope.
        payload:        Caller-supplied payload dict.
        sinks_notified: Sink names that received this alert.
        suppressed:     Whether the alert was suppressed.
        status:         ``"open"``, ``"acknowledged"``, or ``"resolved"``.
        timestamp:      ISO-8601 UTC emission time.
    """

    alert_id: str
    topic: str
    severity: str
    project_id: str
    payload: dict[str, Any]
    sinks_notified: list[str]
    suppressed: bool
    status: str
    timestamp: str


@dataclass(frozen=True)
class AlertStatusInfo:
    """Health and session statistics for :class:`~spanforge.sdk.alert.SFAlertClient`.

    Attributes:
        status:          ``"ok"`` or ``"degraded"``.
        publish_count:   Total ``publish()`` calls this session.
        suppress_count:  Total suppressed alert count this session.
        queue_depth:     Current number of items waiting in the dispatch queue.
        registered_topics: Number of topics in the registry.
        active_maintenance_windows: Number of currently active maintenance windows.
        healthy:         ``True`` when no circuit-breaker is open.
    """

    status: str
    publish_count: int
    suppress_count: int
    queue_depth: int
    registered_topics: int
    active_maintenance_windows: int
    healthy: bool

