"""spanforge.presidio_backend — Optional Presidio-powered PII detection backend.

Wraps Microsoft Presidio AnalyzerEngine to provide entity recognition that
is more accurate than regex-only scanning.  Falls back gracefully if the
``presidio-analyzer`` package is not installed.

Install with::

    pip install "spanforge[presidio]"

Usage::

    from spanforge.presidio_backend import presidio_scan_payload, is_available

    if is_available():
        result = presidio_scan_payload({"message": "My SSN is 123-45-6789"})
        print(result.clean)  # False

The result is a standard :class:`~spanforge.redact.PIIScanResult`, fully
compatible with the built-in regex scanner.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Any

# Prevent transformers (pulled in as a Presidio optional dep) from importing
# TensorFlow. TF has a protobuf registration bug on Python 3.13 that raises
# ValueError at import time and breaks the entire Presidio initialisation.
os.environ.setdefault("USE_TF", "0")
os.environ.setdefault("TRANSFORMERS_NO_TF", "1")

from spanforge.redact import PIIScanHit, PIIScanResult

__all__ = [
    "PIPL_PATTERNS",
    "is_available",
    "presidio_scan_payload",
    "presidio_scan_text",
]

# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------

# Module-level cached AnalyzerEngine — built once on first successful call.
_analyzer: Any = None
_analyzer_available: bool | None = None  # None = not yet tested


def _get_analyzer() -> Any:
    """Return a lazily-created Presidio AnalyzerEngine configured for spaCy.

    Explicitly configures ``en_core_web_lg`` so that Presidio never falls back
    to the transformers NLP engine (which would trigger a TensorFlow import and
    crash on Python 3.13 due to a protobuf double-registration bug).

    Raises:
        ImportError: If ``presidio-analyzer`` is not installed.
        OSError:     If ``en_core_web_lg`` is not installed.
    """
    global _analyzer
    if _analyzer is not None:
        return _analyzer

    from presidio_analyzer import AnalyzerEngine
    from presidio_analyzer.nlp_engine import NlpEngineProvider

    configuration = {
        "nlp_engine_name": "spacy",
        "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}],
    }
    provider = NlpEngineProvider(nlp_configuration=configuration)
    nlp_engine = provider.create_engine()
    _analyzer = AnalyzerEngine(nlp_engine=nlp_engine)

    # Register custom high-precision pattern recognizers to supplement the
    # built-in recognizers where Presidio's default confidence is too low.
    from presidio_analyzer import PatternRecognizer
    from presidio_analyzer.pattern import Pattern

    # US phone formats that the built-in recognizer scores at 0.4 (below the
    # default 0.5 threshold).  These two patterns are high-precision and
    # represent the two test corpus entries that would otherwise be missed.
    _analyzer.registry.add_recognizer(
        PatternRecognizer(
            supported_entity="PHONE_NUMBER",
            patterns=[
                Pattern("US_PHONE_INTL", r"\+1[-.\s]\d{3}[-.\s]\d{3}[-.\s]\d{4}\b", 0.75),
                Pattern("US_PHONE_PAREN", r"\(\d{3}\)\s*\d{3}[-.\s]\d{4}\b", 0.75),
                Pattern("US_PHONE_PLAIN", r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b", 0.60),
            ],
            supported_language="en",
        )
    )

    # Indian Aadhaar (12-digit UID in groups of 4) for English-locale corpora.
    _analyzer.registry.add_recognizer(
        PatternRecognizer(
            supported_entity="IN_AADHAAR",
            patterns=[Pattern("AADHAAR", r"\b\d{4}[ \-]\d{4}[ \-]\d{4}\b", 0.85)],
            supported_language="en",
        )
    )

    # Indian PAN (Permanent Account Number: AAAAA9999A format).
    _analyzer.registry.add_recognizer(
        PatternRecognizer(
            supported_entity="IN_PAN",
            patterns=[Pattern("IN_PAN", r"\b[A-Z]{5}\d{4}[A-Z]\b", 0.85)],
            supported_language="en",
        )
    )

    # UK National Insurance Number (e.g. AB 12 34 56 C / AB123456C).
    # Not included in Presidio's default recognizer set for English.
    _analyzer.registry.add_recognizer(
        PatternRecognizer(
            supported_entity="UK_NATIONAL_INSURANCE",
            patterns=[
                Pattern(
                    "UK_NI",
                    r"\b[A-Z]{2}[\s]?\d{2}[\s]?\d{2}[\s]?\d{2}[\s]?[A-D]\b",
                    0.85,
                )
            ],
            supported_language="en",
        )
    )

    return _analyzer


def is_available() -> bool:
    """Return ``True`` if Presidio + en_core_web_lg are usable."""
    global _analyzer_available
    if _analyzer_available is not None:
        return _analyzer_available
    try:
        _get_analyzer()
        _analyzer_available = True
    except Exception:  # noqa: BLE001 — ImportError, OSError, ValueError, etc.
        _analyzer_available = False
    return _analyzer_available


# ---------------------------------------------------------------------------
# PII-024 — China PIPL sensitive personal information patterns
# ---------------------------------------------------------------------------

#: Regex patterns for China PIPL sensitive personal information.
#: Matches are flagged as ``pipl_sensitive`` for cross-border transfer controls.
PIPL_PATTERNS: dict[str, re.Pattern[str]] = {
    # Chinese Resident Identity Card: 17 digits + check digit (digit or 'X')
    "cn_national_id": re.compile(r"\b\d{17}[\dXx]\b"),
    # Chinese mobile numbers: begin with 1 followed by 3-9, then 9 digits
    "cn_mobile": re.compile(r"\b1[3-9]\d{9}\b"),
    # Chinese bank card numbers: 16-19 digits (Luhn-validated at scan time)
    "cn_bank_card": re.compile(r"\b(?:\d[ -]?){15,18}\d\b"),
}

#: Entity types that are classified as PIPL-sensitive.
PIPL_SENSITIVE_TYPES: frozenset[str] = frozenset(PIPL_PATTERNS.keys())

# Map Presidio entity types to SpanForge PII labels / sensitivity.
# DATE_TIME, LOCATION, NRP (nationality), and URL are intentionally excluded:
# they fire excessively on technical log strings (timestamps, cloud regions,
# registry paths) producing unacceptable false-positive rates in production.
_ENTITY_MAP: dict[str, tuple[str, str]] = {
    "CREDIT_CARD": ("credit_card", "high"),
    "CRYPTO": ("crypto_address", "medium"),
    "EMAIL_ADDRESS": ("email", "medium"),
    "IBAN_CODE": ("iban", "high"),
    "IP_ADDRESS": ("ip_address", "low"),
    "PERSON": ("person_name", "medium"),
    "PHONE_NUMBER": ("phone", "medium"),
    "US_SSN": ("ssn", "high"),
    "UK_NHS": ("uk_nhs", "high"),
    "US_DRIVER_LICENSE": ("us_driver_license", "high"),
    "US_PASSPORT": ("us_passport", "high"),
    "IN_AADHAAR": ("aadhaar", "high"),
    "IN_PAN": ("pan", "high"),
    "MEDICAL_LICENSE": ("medical_license", "medium"),
    "UK_NATIONAL_INSURANCE": ("uk_national_insurance", "high"),
}

# Explicit entity allow-list passed to every AnalyzerEngine.analyze() call.
# Keeps only high-precision recognizers; excludes noisy NER labels.
_SCAN_ENTITIES: list[str] = list(_ENTITY_MAP.keys())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def presidio_scan_payload(
    payload: dict[str, Any],
    *,
    language: str = "en",
    score_threshold: float = 0.5,
    max_depth: int = 10,
) -> PIIScanResult:
    """Scan a payload dict for PII using Microsoft Presidio.

    Walks the payload recursively (up to *max_depth*), analysing every string
    value with the Presidio ``AnalyzerEngine``.

    **Security**: detected values are never returned — only the entity type,
    path, count, and sensitivity level.

    Args:
        payload:          The dictionary to scan.
        language:         Language code for analysis (default: ``"en"``).
        score_threshold:  Minimum Presidio confidence score (default: 0.5).
        max_depth:        Maximum nesting depth (default: 10).

    Returns:
        A :class:`~spanforge.redact.PIIScanResult` summarising detections.

    Raises:
        ImportError: If ``presidio-analyzer`` is not installed.
    """
    analyzer = _get_analyzer()
    hits: list[PIIScanHit] = []
    scanned = 0

    def _walk(obj: Any, path: str, depth: int) -> None:
        nonlocal scanned
        if depth > max_depth:
            return
        if isinstance(obj, str):
            scanned += 1
            results = analyzer.analyze(
                text=obj,
                language=language,
                score_threshold=score_threshold,
                entities=_SCAN_ENTITIES,
            )
            # Post-filter: suppress known low-precision false-positive patterns.
            #   PERSON — spaCy NER fires on lowercase technical identifiers
            #            (e.g. "cafebabe1234", "tenant_id", "failed_count").
            #            Real person names are Title-cased; reject all-lowercase matches.
            #   IP_ADDRESS — fires on dotted-decimal OIDs (e.g. 2.16.840.1.101.3.4.2.1)
            #                which have more than 3 dots. Skip those.
            def _keep(r: Any) -> bool:
                matched = obj[r.start : r.end]
                if r.entity_type == "PERSON" and matched == matched.lower():
                    return False
                if r.entity_type == "IP_ADDRESS" and ":" not in matched:
                    # Filter dotted-decimal OIDs — a valid IPv4 has exactly 4
                    # segments each in [0, 255], AND is not embedded inside a
                    # longer dotted-decimal sequence (e.g. 2.16.840.1.101.3.4.2.1).
                    parts = matched.split(".")
                    try:
                        if len(parts) != 4 or not all(0 <= int(p) <= 255 for p in parts):
                            return False
                    except ValueError:
                        return False
                    # Reject matches embedded in longer dotted-decimal sequences (e.g. OIDs)
                    # by checking characters immediately adjacent to the match.
                    # Use set membership (not substring) so empty-string boundary is not
                    # a false positive — `"" in "0123456789."` is True in Python.
                    _boundary = frozenset("0123456789.")
                    before = obj[r.start - 1] if r.start > 0 else ""
                    after = obj[r.end] if r.end < len(obj) else ""
                    if before in _boundary or after in _boundary:
                        return False
                return True

            filtered = [r for r in results if _keep(r)]
            # Group by entity type
            entity_counts: dict[str, int] = {}
            for r in filtered:
                entity_counts[r.entity_type] = entity_counts.get(r.entity_type, 0) + 1
            for entity_type, count in entity_counts.items():
                label, sensitivity = _ENTITY_MAP.get(entity_type, (entity_type.lower(), "medium"))
                hits.append(
                    PIIScanHit(
                        pii_type=label,
                        path=path,
                        match_count=count,
                        sensitivity=sensitivity,
                    )
                )
        elif isinstance(obj, Mapping):
            for k, v in obj.items():
                _walk(v, f"{path}.{k}" if path else str(k), depth + 1)
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                _walk(v, f"{path}[{i}]", depth + 1)

    _walk(payload, "", 0)
    return PIIScanResult(hits=hits, scanned=scanned)


def presidio_scan_text(
    text: str,
    *,
    language: str = "en",
    score_threshold: float = 0.5,
) -> tuple[list[dict[str, Any]], str, bool]:
    """Scan a plain text string for PII using Microsoft Presidio.

    Returns a tuple of ``(entities, redacted_text, detected)`` where
    *entities* is a list of ``{"type", "start", "end", "score"}`` dicts
    and *redacted_text* replaces each detected entity with ``<TYPE>``.

    **Security**: raw entity values are never included — only type, position,
    and confidence score.

    Args:
        text:             The text to scan.
        language:         Language code for analysis (default: ``"en"``).
        score_threshold:  Minimum Presidio confidence score (default: 0.5).

    Returns:
        ``(entities, redacted_text, detected)`` tuple.

    Raises:
        ImportError: If ``presidio-analyzer`` is not installed.
    """
    analyzer = _get_analyzer()
    results = analyzer.analyze(
        text=text,
        language=language,
        score_threshold=score_threshold,
        entities=_SCAN_ENTITIES,
    )

    entities: list[dict[str, Any]] = [
        {
            "type": _ENTITY_MAP.get(r.entity_type, (r.entity_type.lower(), "medium"))[0],
            "start": r.start,
            "end": r.end,
            "score": round(float(r.score), 4),
        }
        for r in sorted(results, key=lambda r: r.start)
    ]

    # Build redacted text by replacing spans from right-to-left to preserve offsets.
    redacted = text
    for ent in sorted(entities, key=lambda e: e["start"], reverse=True):
        redacted = redacted[: ent["start"]] + f"<{ent['type'].upper()}>" + redacted[ent["end"] :]

    return entities, redacted, bool(entities)
