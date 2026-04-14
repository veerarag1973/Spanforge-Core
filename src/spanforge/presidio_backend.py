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

from collections.abc import Mapping
from typing import Any

from spanforge.redact import PIIScanHit, PIIScanResult

__all__ = [
    "is_available",
    "presidio_scan_payload",
]

# ---------------------------------------------------------------------------
# Availability check
# ---------------------------------------------------------------------------


def is_available() -> bool:
    """Return ``True`` if the ``presidio-analyzer`` package is importable."""
    try:
        import presidio_analyzer  # type: ignore[import-untyped]  # noqa: PLC0415, F401
        return True
    except ImportError:
        return False


# Map Presidio entity types to SpanForge PII labels / sensitivity
_ENTITY_MAP: dict[str, tuple[str, str]] = {
    "CREDIT_CARD": ("credit_card", "high"),
    "CRYPTO": ("crypto_address", "medium"),
    "EMAIL_ADDRESS": ("email", "medium"),
    "IBAN_CODE": ("iban", "high"),
    "IP_ADDRESS": ("ip_address", "low"),
    "LOCATION": ("location", "low"),
    "PERSON": ("person_name", "medium"),
    "PHONE_NUMBER": ("phone", "medium"),
    "US_SSN": ("ssn", "high"),
    "UK_NHS": ("uk_nhs", "high"),
    "US_DRIVER_LICENSE": ("us_driver_license", "high"),
    "US_PASSPORT": ("us_passport", "high"),
    "IN_AADHAAR": ("aadhaar", "high"),
    "IN_PAN": ("pan", "high"),
    "NRP": ("nationality", "low"),
    "MEDICAL_LICENSE": ("medical_license", "medium"),
    "URL": ("url", "low"),
    "DATE_TIME": ("date_time", "low"),
}


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
    try:
        from presidio_analyzer import AnalyzerEngine  # type: ignore[import-untyped]  # noqa: PLC0415
    except ImportError as exc:
        raise ImportError(
            "The 'presidio-analyzer' package is required for the Presidio backend.\n"
            "Install it with: pip install 'spanforge[presidio]'"
        ) from exc

    analyzer = AnalyzerEngine()
    hits: list[PIIScanHit] = []
    scanned = 0

    def _walk(obj: Any, path: str, depth: int) -> None:  # noqa: ANN401
        nonlocal scanned
        if depth > max_depth:
            return
        if isinstance(obj, str):
            scanned += 1
            results = analyzer.analyze(
                text=obj,
                language=language,
                score_threshold=score_threshold,
            )
            # Group by entity type
            entity_counts: dict[str, int] = {}
            for r in results:
                entity_counts[r.entity_type] = entity_counts.get(r.entity_type, 0) + 1
            for entity_type, count in entity_counts.items():
                label, sensitivity = _ENTITY_MAP.get(
                    entity_type, (entity_type.lower(), "medium")
                )
                hits.append(PIIScanHit(
                    pii_type=label,
                    path=path,
                    match_count=count,
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
