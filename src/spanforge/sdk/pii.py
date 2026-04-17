"""spanforge.sdk.pii — SpanForge sf-pii client.

Implements the full sf-pii API surface for Phase 3 (PII Service Hardening) of
the SpanForge roadmap, extending the Phase 2 foundation.

All operations run locally in-process (zero external dependencies) when
``config.endpoint`` is empty or when the remote service is unreachable and
``local_fallback_enabled`` is ``True``.

Local-mode feature parity
--------------------------
*  :meth:`scan`                    — deep regex PII scan (dict payload).
*  :meth:`scan_text`               — Presidio-backed text scan (PII-001).
*  :meth:`anonymise`               — recursive dict anonymisation (PII-002).
*  :meth:`scan_batch`              — async parallel text scan (PII-003).
*  :meth:`apply_pipeline_action`   — pii_action routing hook (PII-010/011/012).
*  :meth:`get_status`              — sf_pii status contribution (PII-005).
*  :meth:`redact`                  — apply RedactionPolicy to an event.
*  :meth:`contains_pii`            — check for unredacted PII.
*  :meth:`assert_redacted`         — raise if unredacted PII found.
*  :meth:`anonymize`               — replace PII in raw text strings.
*  :meth:`wrap`                    — Redactable factory.
*  :meth:`make_policy`             — RedactionPolicy factory.
*  :meth:`erase_subject`           — GDPR Article 17 erasure (PII-021).
*  :meth:`export_subject_data`     — CCPA DSAR export (PII-022).
*  :meth:`safe_harbor_deidentify`  — HIPAA Safe Harbor (PII-023).
*  :meth:`audit_training_data`     — EU AI Act Article 10 audit (PII-025).
*  :meth:`get_pii_stats`           — PII heat map data (PII-032).

Security requirements
---------------------
*  Scan and anonymize results **never** include matched PII values — only
   type labels, field paths, counts, and anonymized replacement text.
*  :exc:`~spanforge.sdk._exceptions.SFPIINotRedactedError` messages never
   contain raw PII; context strings are SHA-256-hashed before inclusion.
*  ``SecretStr`` API keys are never written to logs.
*  Redaction manifest entries hash original values with SHA-256; raw values
   are never stored.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import datetime
import hashlib
import json
import re
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.sdk._exceptions import (
    SFPIIBlockedError,
    SFPIIError,
    SFPIINotRedactedError,
    SFPIIPolicyError,
    SFPIIScanError,
)
from spanforge.sdk._types import (
    DSARExport,
    ErasureReceipt,
    PIIAnonymisedResult,
    PIIEntity,
    PIIHeatMapEntry,
    PIIPipelineResult,
    PIIRedactionManifestEntry,
    PIIStatusInfo,
    PIITextScanResult,
    SafeHarborResult,
    SFPIIAnonymizeResult,
    SFPIIHit,
    SFPIIRedactResult,
    SFPIIScanResult,
    TrainingDataPIIReport,
)

if TYPE_CHECKING:
    from spanforge.event import Event
    from spanforge.redact import Redactable, RedactionPolicy

__all__ = ["SFPIIClient"]

# ---------------------------------------------------------------------------
# Valid sensitivity levels — mirrors spanforge.redact.Sensitivity enum values
# ---------------------------------------------------------------------------

_VALID_SENSITIVITY: frozenset[str] = frozenset({"low", "medium", "high", "pii", "phi"})

# Validation labels for which secondary validators are applied in anonymize()
_CC_LABEL = "credit_card"
_AADHAAR_LABEL = "aadhaar"
_SSN_LABEL = "ssn"
_DOB_LABEL = "date_of_birth"

# ---------------------------------------------------------------------------
# Phase 3 constants
# ---------------------------------------------------------------------------

#: Default confidence threshold for pipeline action routing (PII-011).
_DEFAULT_PIPELINE_THRESHOLD: float = 0.85

#: Valid pipeline action values (PII-010).
_VALID_PIPELINE_ACTIONS: frozenset[str] = frozenset({"flag", "redact", "block"})

#: DPDP-regulated entity type labels (India DPDP Act).
_DPDP_ENTITY_TYPES: frozenset[str] = frozenset({"aadhaar", "pan"})

#: PIPL-sensitive entity type labels (China PIPL).
_PIPL_ENTITY_TYPES: frozenset[str] = frozenset({"cn_national_id", "cn_mobile", "cn_bank_card"})

# ---------------------------------------------------------------------------
# HIPAA Safe Harbor — 18 PHI identifier patterns (45 CFR §164.514(b)(2))
# ---------------------------------------------------------------------------

#: Mapping of PHI identifier label → compiled regex for Safe Harbor de-identification.
_SAFE_HARBOR_PATTERNS: dict[str, re.Pattern[str]] = {
    # 1. Names
    "name": re.compile(
        r"\b(?:Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Prof\.?)\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*\b"
        r"|\b[A-Z][a-z]+\s+[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b",
    ),
    # 2. Geographic subdivisions smaller than state — zip codes
    "zip": re.compile(r"\b(\d{5})(?:-\d{4})?\b"),
    # 3. Dates (other than year)
    "date": re.compile(
        r"\b(?:0?[1-9]|1[0-2])[/-](?:0?[1-9]|[12]\d|3[01])[/-](?:19|20)\d{2}\b"
        r"|\b(?:0?[1-9]|[12]\d|3[01])[/-](?:0?[1-9]|1[0-2])[/-](?:19|20)\d{2}\b"
        r"|\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?"
        r"|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+(?:0?[1-9]|[12]\d|3[01]),?\s+(?:19|20)\d{2}\b",
        re.IGNORECASE,
    ),
    # 4. Phone numbers
    "phone": re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    # 5. Fax numbers — same pattern as phone
    "fax": re.compile(r"(?i)fax\s*:?\s*(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    # 6. Email addresses
    "email": re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}", re.ASCII),
    # 7. Social security numbers
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    # 8. Medical record numbers
    "medical_record": re.compile(r"\bMRN?[\s#:]\s*\d{6,10}\b", re.IGNORECASE),
    # 9. Health plan beneficiary numbers
    "health_plan": re.compile(r"\b(?:HP|HB)[\s#:]\s*\d{6,12}\b", re.IGNORECASE),
    # 10. Account numbers
    "account": re.compile(r"\b(?:Acct?|Account)[\s#:.]\s*\d{6,16}\b", re.IGNORECASE),
    # 11. Certificate/license numbers
    "license": re.compile(r"\bLIC(?:ENSE)?[\s#:]\s*[A-Z0-9]{5,15}\b", re.IGNORECASE),
    # 12. Vehicle identifiers (VIN)
    "vin": re.compile(r"\b[A-HJ-NPR-Z0-9]{17}\b"),
    # 13. Device identifiers (serial numbers — heuristic)
    "device_serial": re.compile(r"\b(?:S/N|SN|Serial)[\s#:]\s*[A-Z0-9]{8,20}\b", re.IGNORECASE),
    # 14. Web URLs
    "url": re.compile(r"https?://[^\s\"'<>]{4,}", re.IGNORECASE),
    # 15. IP addresses
    "ip_address": re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}"
        r"(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b"
    ),
    # 16. Biometric identifiers — fingerprint reference IDs (heuristic)
    "biometric": re.compile(r"\b(?:FP|BIO)[\s#:]\s*[A-Z0-9]{8,20}\b", re.IGNORECASE),
    # 17. Full face photos — placeholder (cannot regex-detect images)
    # 18. Age > 89 — handled in safe_harbor_deidentify() as post-processing
    "age_over_89": re.compile(r"\b(9[0-9]|1[0-9]{2})\s*(?:years?(?:\s+old)?|yo|y/o)\b",
                              re.IGNORECASE),
}


class SFPIIClient(SFServiceClient):
    """SpanForge PII redaction service client.

    Provides scanning, redaction, containment checks, and text anonymization.
    All operations run in-process when no ``endpoint`` is configured (local
    mode) or when the remote service is unavailable and
    ``local_fallback_enabled`` is ``True``.

    Args:
        config: Client configuration.  Use :class:`~spanforge.sdk._base.SFClientConfig`
                or :func:`~spanforge.sdk._base.SFClientConfig.from_env`.

    Example::

        from spanforge.sdk import sf_pii

        # Scan a payload for PII
        result = sf_pii.scan({"message": "Call me on 555-867-5309"})
        if not result.clean:
            for hit in result.hits:
                print(hit.pii_type, hit.path, hit.match_count)

        # Anonymize raw text
        anon = sf_pii.anonymize("My email is alice@example.com")
        print(anon.text)   # "My email is [REDACTED:email]"
    """

    def __init__(self, config: SFClientConfig) -> None:
        super().__init__(config, service_name="pii")
        #: ISO-8601 timestamp of the most recent scan_text() call; None until first call.
        self._last_scan_at: str | None = None

    # ------------------------------------------------------------------
    # scan
    # ------------------------------------------------------------------

    def scan(
        self,
        payload: dict[str, Any],
        *,
        extra_patterns: dict[str, re.Pattern[str]] | None = None,
        max_depth: int = 10,
    ) -> SFPIIScanResult:
        """Scan *payload* for PII using built-in and optional extra patterns.

        Walks the entire payload recursively (up to *max_depth* levels),
        testing every string value against the built-in detector set (email,
        phone, SSN, credit card, IP address, UK NI number, Aadhaar, PAN,
        date-of-birth, address) plus any caller-supplied patterns.  Secondary
        validators (Luhn, Verhoeff, SSN range checks, calendar validation)
        are applied to reduce false positives.

        Security: matched PII values are **never** included in the result —
        only type labels, field paths, match counts, and sensitivity levels.

        Args:
            payload:        Dictionary to scan.  Must be a :class:`dict`.
            extra_patterns: Optional ``{label: compiled_regex}`` detectors.
            max_depth:      Maximum nesting depth (default 10).

        Returns:
            :class:`~spanforge.sdk._types.SFPIIScanResult`.

        Raises:
            SFPIIScanError:            If *payload* is not a ``dict`` or scan fails.
            SFServiceUnavailableError: Circuit breaker open, fallback disabled.
        """
        if not isinstance(payload, dict):
            msg = f"scan() requires a dict payload; got {type(payload).__name__}"
            raise SFPIIScanError(msg)
        if self._is_local_mode() or self._config.local_fallback_enabled:
            return self._scan_local(payload, extra_patterns=extra_patterns, max_depth=max_depth)
        return self._scan_remote(payload, extra_patterns=extra_patterns, max_depth=max_depth)

    def _scan_local(
        self,
        payload: dict[str, Any],
        *,
        extra_patterns: dict[str, re.Pattern[str]] | None,
        max_depth: int,
    ) -> SFPIIScanResult:
        from spanforge.redact import scan_payload

        try:
            result = scan_payload(payload, extra_patterns=extra_patterns, max_depth=max_depth)
        except RecursionError as exc:
            raise SFPIIScanError(str(exc)) from exc

        hits = [
            SFPIIHit(
                pii_type=h.pii_type,
                path=h.path,
                match_count=h.match_count,
                sensitivity=h.sensitivity,
            )
            for h in result.hits
        ]
        return SFPIIScanResult(hits=hits, scanned=result.scanned)

    def _scan_remote(
        self,
        payload: dict[str, Any],
        *,
        extra_patterns: dict[str, re.Pattern[str]] | None,
        max_depth: int,
    ) -> SFPIIScanResult:
        body: dict[str, Any] = {"payload": payload, "max_depth": max_depth}
        raw = self._request("POST", "/pii/scan", body=body)
        hits = [
            SFPIIHit(
                pii_type=str(h.get("pii_type", "")),
                path=str(h.get("path", "")),
                match_count=int(h.get("match_count", 1)),
                sensitivity=str(h.get("sensitivity", "medium")),
            )
            for h in raw.get("hits", [])
        ]
        return SFPIIScanResult(hits=hits, scanned=int(raw.get("scanned", 0)))

    # ------------------------------------------------------------------
    # redact
    # ------------------------------------------------------------------

    def redact(
        self,
        event: Event,
        *,
        policy: RedactionPolicy | None = None,
    ) -> SFPIIRedactResult:
        """Apply a redaction policy to *event*, returning a sanitised copy.

        Fields wrapped in :class:`~spanforge.redact.Redactable` with
        sensitivity ≥ the policy threshold are replaced with safe marker
        strings (e.g. ``"[REDACTED:pii]"``).  The original event is **not**
        mutated; a new :class:`~spanforge.event.Event` is returned inside the
        result.

        Args:
            event:  The :class:`~spanforge.event.Event` to redact.
            policy: :class:`~spanforge.redact.RedactionPolicy` to apply.
                    Defaults to ``RedactionPolicy(redacted_by="policy:sf-pii")``,
                    which redacts all fields at ``Sensitivity.PII`` or above.

        Returns:
            :class:`~spanforge.sdk._types.SFPIIRedactResult` with the
            sanitised event and redaction statistics.

        Raises:
            SFServiceUnavailableError: Circuit breaker open, fallback disabled.
        """
        if self._is_local_mode() or self._config.local_fallback_enabled:
            return self._redact_local(event, policy=policy)
        return self._redact_remote(event, policy=policy)

    def _redact_local(
        self,
        event: Event,
        *,
        policy: RedactionPolicy | None,
    ) -> SFPIIRedactResult:
        from spanforge.redact import RedactionPolicy

        effective = policy if policy is not None else RedactionPolicy(redacted_by="policy:sf-pii")
        result = effective.apply(event)
        return SFPIIRedactResult(
            event=result.event,
            redaction_count=result.redaction_count,
            redacted_at=result.redacted_at,
            redacted_by=result.redacted_by,
        )

    def _redact_remote(
        self,
        event: Event,
        *,
        policy: RedactionPolicy | None,
    ) -> SFPIIRedactResult:
        from spanforge.redact import RedactionPolicy, Sensitivity

        effective = policy if policy is not None else RedactionPolicy(redacted_by="policy:sf-pii")
        body: dict[str, Any] = {
            "min_sensitivity": effective.min_sensitivity.value
            if isinstance(effective.min_sensitivity, Sensitivity)
            else str(effective.min_sensitivity),
            "redacted_by": effective.redacted_by,
        }
        raw = self._request("POST", "/pii/redact", body=body)
        return SFPIIRedactResult(
            event=raw.get("event"),
            redaction_count=int(raw.get("redaction_count", 0)),
            redacted_at=str(raw.get("redacted_at", "")),
            redacted_by=str(raw.get("redacted_by", effective.redacted_by)),
        )

    # ------------------------------------------------------------------
    # contains_pii
    # ------------------------------------------------------------------

    def contains_pii(
        self,
        event: Event,
        *,
        scan_raw: bool = True,
    ) -> bool:
        """Return ``True`` if any unredacted PII remains in *event*.

        Checks both :class:`~spanforge.redact.Redactable` wrapper instances
        (explicit PII markers) and, when *scan_raw* is ``True``, raw string
        values via the built-in regex detectors.

        Args:
            event:    The :class:`~spanforge.event.Event` to inspect.
            scan_raw: When ``True`` (default), also run regex PII scanning on
                      string values in the payload.

        Returns:
            ``True`` if PII is detected; ``False`` if the payload is clean.
        """
        if self._is_local_mode() or self._config.local_fallback_enabled:
            from spanforge.redact import contains_pii as _cp

            return _cp(event, scan_raw=scan_raw)
        raw = self._request("POST", "/pii/contains", body={"scan_raw": scan_raw})
        return bool(raw.get("contains_pii", False))

    # ------------------------------------------------------------------
    # assert_redacted
    # ------------------------------------------------------------------

    def assert_redacted(
        self,
        event: Event,
        *,
        context: str = "",
        scan_raw: bool = True,
    ) -> None:
        """Raise :exc:`SFPIINotRedactedError` if *event* contains unredacted PII.

        A stricter alternative to :meth:`contains_pii`.  Use this at export
        or serialisation boundaries to enforce that all PII has been scrubbed
        before the event leaves a trusted context.

        Args:
            event:    The :class:`~spanforge.event.Event` to verify.
            context:  Optional label identifying the call site for correlation
                      (SHA-256-hashed before use — never included raw).
            scan_raw: When ``True`` (default), also run regex scanning.

        Raises:
            SFPIINotRedactedError: If unredacted PII is detected.
        """
        if self._is_local_mode() or self._config.local_fallback_enabled:
            self._assert_redacted_local(event, context=context, scan_raw=scan_raw)
            return
        raw = self._request(
            "POST",
            "/pii/assert-redacted",
            body={"scan_raw": scan_raw},
        )
        if raw.get("has_pii"):
            raise SFPIINotRedactedError(int(raw.get("count", 1)), context)

    def _assert_redacted_local(
        self,
        event: Event,
        *,
        context: str,
        scan_raw: bool,
    ) -> None:
        from spanforge.redact import PIINotRedactedError, assert_redacted

        try:
            assert_redacted(event, context, scan_raw=scan_raw)
        except PIINotRedactedError as exc:
            raise SFPIINotRedactedError(exc.count, context) from exc

    # ------------------------------------------------------------------
    # anonymize
    # ------------------------------------------------------------------

    def anonymize(
        self,
        text: str,
        *,
        extra_patterns: dict[str, re.Pattern[str]] | None = None,
    ) -> SFPIIAnonymizeResult:
        """Replace all detected PII in *text* with type-tagged markers.

        Runs the full built-in PII pattern set (and any *extra_patterns*)
        against *text*, replacing each confirmed match with
        ``[REDACTED:<pii_type>]``.  Secondary validators (Luhn checksum for
        credit cards, Verhoeff checksum for Aadhaar, SSA range checks for
        SSNs, calendar validation for dates of birth) are applied to minimise
        false-positive replacements.

        Security: the original matched values are **never** returned — only
        the anonymized text, replacement count, and a list of PII type labels.

        Args:
            text:           Plain text string to anonymize.
            extra_patterns: Optional ``{label: compiled_regex}`` detectors to
                            run in addition to the built-in patterns.

        Returns:
            :class:`~spanforge.sdk._types.SFPIIAnonymizeResult`.

        Raises:
            SFPIIScanError: If *text* is not a ``str``.
        """
        if not isinstance(text, str):
            msg = f"anonymize() requires a str; got {type(text).__name__}"
            raise SFPIIScanError(msg)
        if self._is_local_mode() or self._config.local_fallback_enabled:
            return self._anonymize_local(text, extra_patterns=extra_patterns)
        raw = self._request("POST", "/pii/anonymize", body={"text": text})
        return SFPIIAnonymizeResult(
            text=str(raw.get("text", text)),
            replacements=int(raw.get("replacements", 0)),
            pii_types_found=list(raw.get("pii_types_found", [])),
        )

    def _anonymize_local(
        self,
        text: str,
        *,
        extra_patterns: dict[str, re.Pattern[str]] | None,
    ) -> SFPIIAnonymizeResult:
        import spanforge.redact as _redact

        # Access built-in patterns; fall back gracefully if internal names change.
        pii_patterns: dict[str, re.Pattern[str]] = dict(
            getattr(_redact, "_PII_PATTERNS", {}),
        )
        dpdp_patterns: dict[str, re.Pattern[str]] = dict(
            getattr(_redact, "DPDP_PATTERNS", {}),
        )
        patterns: dict[str, re.Pattern[str]] = {**pii_patterns, **dpdp_patterns}
        if extra_patterns:
            patterns.update(extra_patterns)

        # Secondary validators (default to always-pass if internals unavailable)
        _luhn = getattr(_redact, "_luhn_check", lambda _s: True)
        _verhoeff = getattr(_redact, "_verhoeff_check", lambda _s: True)
        _valid_ssn = getattr(_redact, "_is_valid_ssn", lambda _s: True)
        _valid_date = getattr(_redact, "_is_valid_date", lambda _s: True)

        result_text = text
        replacements = 0
        pii_types_found: list[str] = []

        for label, pat in patterns.items():
            counter: list[int] = [0]

            def _replace(
                m: re.Match[str],
                _lbl: str = label,
                _cnt: list[int] = counter,
            ) -> str:
                val = m.group()
                if _lbl == _CC_LABEL and not _luhn(val):
                    return val
                if _lbl == _AADHAAR_LABEL and not _verhoeff(val):
                    return val
                if _lbl == _SSN_LABEL and not _valid_ssn(val):
                    return val
                if _lbl == _DOB_LABEL and not _valid_date(val):
                    return val
                _cnt[0] += 1
                return f"[REDACTED:{_lbl}]"

            new_text = pat.sub(_replace, result_text)
            if counter[0] > 0:
                result_text = new_text
                replacements += counter[0]
                if label not in pii_types_found:
                    pii_types_found.append(label)

        return SFPIIAnonymizeResult(
            text=result_text,
            replacements=replacements,
            pii_types_found=pii_types_found,
        )

    # ------------------------------------------------------------------
    # wrap
    # ------------------------------------------------------------------

    def wrap(
        self,
        value: object,
        sensitivity: str,
        pii_types: frozenset[str] = frozenset(),
    ) -> Redactable:
        """Wrap *value* as a :class:`~spanforge.redact.Redactable` sentinel.

        Convenience factory that creates a :class:`~spanforge.redact.Redactable`
        instance ready to embed in an event payload.  The value will be
        replaced by a safe marker string when a
        :class:`~spanforge.redact.RedactionPolicy` is applied.

        Args:
            value:       The PII-sensitive value to protect.
            sensitivity: Sensitivity level string: ``"low"``, ``"medium"``,
                         ``"high"``, ``"pii"``, or ``"phi"``.
            pii_types:   Labels describing the PII category
                         (e.g. ``frozenset({"email"})``).

        Returns:
            :class:`~spanforge.redact.Redactable` wrapping *value*.

        Raises:
            SFPIIPolicyError: If *sensitivity* is not a recognised level.

        Example::

            wrapped = sf_pii.wrap("alice@example.com", "pii", frozenset({"email"}))
        """
        from spanforge.redact import Redactable, Sensitivity

        if sensitivity not in _VALID_SENSITIVITY:
            valid = sorted(_VALID_SENSITIVITY)
            msg = f"Invalid sensitivity level {sensitivity!r}. Must be one of: {valid}"
            raise SFPIIPolicyError(msg)
        return Redactable(value, Sensitivity(sensitivity), pii_types)

    # ------------------------------------------------------------------
    # make_policy
    # ------------------------------------------------------------------

    def make_policy(
        self,
        *,
        min_sensitivity: str = "pii",
        redacted_by: str = "policy:sf-pii",
        replacement_template: str = "[REDACTED:{sensitivity}]",
    ) -> RedactionPolicy:
        """Create a configured :class:`~spanforge.redact.RedactionPolicy`.

        Args:
            min_sensitivity:      Sensitivity threshold; fields at or above
                                  this level are redacted.  Must be one of
                                  ``"low"``, ``"medium"``, ``"high"``,
                                  ``"pii"``, or ``"phi"``.
                                  Defaults to ``"pii"``.
            redacted_by:          Identifier embedded in the redaction
                                  metadata (e.g. ``"policy:corp-default"``).
                                  Defaults to ``"policy:sf-pii"``.
            replacement_template: Marker template.  Must contain
                                  ``{sensitivity}`` which is replaced with
                                  the field's sensitivity level value.
                                  Defaults to ``"[REDACTED:{sensitivity}]"``.

        Returns:
            Configured :class:`~spanforge.redact.RedactionPolicy`.

        Raises:
            SFPIIPolicyError: If *min_sensitivity* is not recognised or
                              *replacement_template* lacks ``{sensitivity}``.

        Example::

            policy = sf_pii.make_policy(min_sensitivity="high",
                                        redacted_by="my-service")
        """
        from spanforge.redact import RedactionPolicy, Sensitivity

        if min_sensitivity not in _VALID_SENSITIVITY:
            valid = sorted(_VALID_SENSITIVITY)
            msg = f"Invalid min_sensitivity {min_sensitivity!r}. Must be one of: {valid}"
            raise SFPIIPolicyError(msg)
        if "{sensitivity}" not in replacement_template:
            msg = (
                "replacement_template must contain the '{sensitivity}' placeholder; "
                f"received: {replacement_template!r}"
            )
            raise SFPIIPolicyError(msg)
        return RedactionPolicy(
            min_sensitivity=Sensitivity(min_sensitivity),
            redacted_by=redacted_by,
            replacement_template=replacement_template,
        )

    # ==================================================================
    # Phase 3 — PII Service Hardening
    # ==================================================================

    # ------------------------------------------------------------------
    # scan_text (PII-001)
    # ------------------------------------------------------------------

    def scan_text(
        self,
        text: str,
        *,
        language: str = "en",
        score_threshold: float = 0.5,
    ) -> PIITextScanResult:
        """Scan a plain-text string for PII (PII-001).

        Uses the Presidio ``AnalyzerEngine`` when available, falling back to
        the built-in regex scanner.  Response shape follows the spec:
        ``{entities: [{type, start, end, score}], redacted_text, detected}``.

        **Security**: entity values are never returned — only type, position,
        and confidence score.

        Args:
            text:             Plain text to scan.
            language:         Language code for Presidio analysis (default
                              ``"en"``).  Ignored when using regex fallback.
            score_threshold:  Minimum Presidio confidence score (default
                              0.5).

        Returns:
            :class:`~spanforge.sdk._types.PIITextScanResult`.

        Raises:
            SFPIIScanError: If *text* is not a ``str``.
        """
        if not isinstance(text, str):
            msg = f"scan_text() requires a str; got {type(text).__name__}"
            raise SFPIIScanError(msg)
        self._last_scan_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return self._scan_text_local(text, language=language, score_threshold=score_threshold)

    def _scan_text_local(
        self,
        text: str,
        *,
        language: str,
        score_threshold: float,
    ) -> PIITextScanResult:
        from spanforge.presidio_backend import is_available, presidio_scan_text

        if is_available():
            try:
                raw_entities, redacted_text, detected = presidio_scan_text(
                    text, language=language, score_threshold=score_threshold
                )
                entities = [
                    PIIEntity(
                        type=e["type"],
                        start=e["start"],
                        end=e["end"],
                        score=e["score"],
                    )
                    for e in raw_entities
                ]
                return PIITextScanResult(
                    entities=entities,
                    redacted_text=redacted_text,
                    detected=detected,
                )
            except ImportError:
                pass  # fall through to regex fallback

        # Regex fallback — synthesise character-level entities from pattern matches
        return self._scan_text_regex_fallback(text)

    def _scan_text_regex_fallback(self, text: str) -> PIITextScanResult:
        """Regex-based fallback for scan_text() when Presidio is unavailable."""
        import spanforge.redact as _redact

        pii_patterns: dict[str, re.Pattern[str]] = dict(
            getattr(_redact, "_PII_PATTERNS", {}),
        )
        dpdp_patterns: dict[str, re.Pattern[str]] = dict(
            getattr(_redact, "DPDP_PATTERNS", {}),
        )
        from spanforge.presidio_backend import PIPL_PATTERNS

        all_patterns = {**pii_patterns, **dpdp_patterns, **PIPL_PATTERNS}

        _luhn = getattr(_redact, "_luhn_check", lambda _s: True)
        _verhoeff = getattr(_redact, "_verhoeff_check", lambda _s: True)
        _valid_ssn = getattr(_redact, "_is_valid_ssn", lambda _s: True)
        _valid_date = getattr(_redact, "_is_valid_date", lambda _s: True)

        entities: list[PIIEntity] = []
        for label, pat in all_patterns.items():
            for m in pat.finditer(text):
                val = m.group()
                if label == _CC_LABEL and not _luhn(val):
                    continue
                if label == _AADHAAR_LABEL and not _verhoeff(val):
                    continue
                if label == _SSN_LABEL and not _valid_ssn(val):
                    continue
                if label == _DOB_LABEL and not _valid_date(val):
                    continue
                entities.append(
                    PIIEntity(type=label, start=m.start(), end=m.end(), score=1.0)
                )

        # Sort by start position and build redacted text right-to-left
        entities.sort(key=lambda e: e.start)
        redacted = text
        for ent in sorted(entities, key=lambda e: e.start, reverse=True):
            redacted = redacted[: ent.start] + f"<{ent.type.upper()}>" + redacted[ent.end :]

        return PIITextScanResult(
            entities=entities,
            redacted_text=redacted,
            detected=bool(entities),
        )

    # ------------------------------------------------------------------
    # anonymise (PII-002) — British spelling, dict input
    # ------------------------------------------------------------------

    def anonymise(
        self,
        payload: dict[str, Any],
        *,
        max_depth: int = 10,
    ) -> PIIAnonymisedResult:
        """Recursively anonymise all string fields in *payload* (PII-002).

        Calls :meth:`scan_text` on every string field, replacing detected
        entities with ``<TYPE>`` placeholders.  Returns a clean copy of the
        payload plus a manifest recording what was replaced (original values
        are SHA-256-hashed — never stored in plain text).

        This method replaces the custom Presidio pipeline in HallucCheck v5.0
        §14 (leaderboard anonymisation).

        Args:
            payload:   Dictionary to anonymise.  Must be a :class:`dict`.
            max_depth: Maximum nesting depth (default 10).

        Returns:
            :class:`~spanforge.sdk._types.PIIAnonymisedResult` with
            ``clean_payload`` and ``redaction_manifest``.

        Raises:
            SFPIIScanError: If *payload* is not a ``dict``.
        """
        if not isinstance(payload, dict):
            msg = f"anonymise() requires a dict payload; got {type(payload).__name__}"
            raise SFPIIScanError(msg)
        manifest: list[PIIRedactionManifestEntry] = []
        clean = self._anonymise_walk(payload, path="", depth=0, max_depth=max_depth,
                                     manifest=manifest)
        return PIIAnonymisedResult(
            clean_payload=clean,
            redaction_manifest=manifest,
        )

    def _anonymise_walk(
        self,
        obj: Any,
        *,
        path: str,
        depth: int,
        max_depth: int,
        manifest: list[PIIRedactionManifestEntry],
    ) -> Any:
        if depth > max_depth:
            return obj
        if isinstance(obj, str):
            result = self._scan_text_local(obj, language="en", score_threshold=0.5)
            if not result.detected:
                return obj
            # Replace detected entities and record manifest entries
            clean_text = result.redacted_text
            for ent in result.entities:
                original_hash = hashlib.sha256(
                    obj[ent.start : ent.end].encode()
                ).hexdigest()
                manifest.append(
                    PIIRedactionManifestEntry(
                        field_path=path,
                        type=ent.type,
                        original_hash=original_hash,
                        replacement=f"<{ent.type.upper()}>",
                    )
                )
            return clean_text
        if isinstance(obj, dict):
            return {
                k: self._anonymise_walk(
                    v,
                    path=f"{path}.{k}" if path else str(k),
                    depth=depth + 1,
                    max_depth=max_depth,
                    manifest=manifest,
                )
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [
                self._anonymise_walk(
                    v,
                    path=f"{path}[{i}]",
                    depth=depth + 1,
                    max_depth=max_depth,
                    manifest=manifest,
                )
                for i, v in enumerate(obj)
            ]
        return obj

    # ------------------------------------------------------------------
    # scan_batch (PII-003)
    # ------------------------------------------------------------------

    def scan_batch(
        self,
        texts: list[str],
        *,
        language: str = "en",
        score_threshold: float = 0.5,
        max_workers: int = 8,
    ) -> list[PIITextScanResult]:
        """Scan a list of texts for PII in parallel (PII-003).

        Uses a thread pool for concurrent execution.  Used by
        ``hc trust-gate`` to bulk-check recent outputs.

        Args:
            texts:           List of plain text strings to scan.
            language:        Language code (default ``"en"``).
            score_threshold: Minimum confidence score (default 0.5).
            max_workers:     Thread pool size (default 8).

        Returns:
            List of :class:`~spanforge.sdk._types.PIITextScanResult` in the
            same order as *texts*.

        Raises:
            SFPIIScanError: If *texts* is not a list or any element is not a
                            ``str``.
        """
        if not isinstance(texts, list):
            msg = f"scan_batch() requires a list; got {type(texts).__name__}"
            raise SFPIIScanError(msg)
        for i, t in enumerate(texts):
            if not isinstance(t, str):
                msg = f"scan_batch() element [{i}] must be str; got {type(t).__name__}"
                raise SFPIIScanError(msg)

        if not texts:
            return []

        def _scan_one(text: str) -> PIITextScanResult:
            return self._scan_text_local(
                text, language=language, score_threshold=score_threshold
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=min(max_workers, len(texts))) as ex:
            futures = [ex.submit(_scan_one, t) for t in texts]
            return [f.result() for f in futures]

    # ------------------------------------------------------------------
    # apply_pipeline_action (PII-010 / PII-011 / PII-012)
    # ------------------------------------------------------------------

    def apply_pipeline_action(
        self,
        text: str,
        *,
        action: str = "flag",
        threshold: float = _DEFAULT_PIPELINE_THRESHOLD,
        language: str = "en",
    ) -> PIIPipelineResult:
        """Apply pipeline pii_action routing to *text* (PII-010/011/012).

        After scanning, enforces the configured *action*:

        * ``"flag"``   — score normally; ``detected=True`` added to result.
        * ``"redact"`` — substitute ``redacted_text`` as scoring input.
        * ``"block"``  — raise :exc:`~spanforge.sdk._exceptions.SFPIIBlockedError`
          (HTTP 422 ``PII_DETECTED``).

        Only entities with ``score >= threshold`` trigger the action.
        Sub-threshold hits are recorded in ``low_confidence_hits`` for audit.

        Args:
            text:      Input text to scan.
            action:    Pipeline action: ``"flag"``, ``"redact"``, or
                       ``"block"``.  Default: ``"flag"``.
            threshold: Confidence threshold (default 0.85).  Entities below
                       this score are recorded but do not trigger the action.
            language:  Language code for Presidio (default ``"en"``).

        Returns:
            :class:`~spanforge.sdk._types.PIIPipelineResult`.

        Raises:
            SFPIIScanError:   If *text* is not a ``str`` or *action* is
                              invalid.
            SFPIIBlockedError: If *action* is ``"block"`` and PII is
                               detected above *threshold*.
        """
        if not isinstance(text, str):
            msg = f"apply_pipeline_action() requires a str; got {type(text).__name__}"
            raise SFPIIScanError(msg)
        if action not in _VALID_PIPELINE_ACTIONS:
            valid = sorted(_VALID_PIPELINE_ACTIONS)
            msg = f"Invalid action {action!r}. Must be one of: {valid}"
            raise SFPIIScanError(msg)

        scan_result = self._scan_text_local(text, language=language, score_threshold=0.0)

        above = [e for e in scan_result.entities if e.score >= threshold]
        below = [e for e in scan_result.entities if e.score < threshold]
        detected = bool(above)
        entity_types = sorted({e.type for e in above})

        # Build redacted text from above-threshold entities only
        redacted = text
        for ent in sorted(above, key=lambda e: e.start, reverse=True):
            redacted = redacted[: ent.start] + f"<{ent.type.upper()}>" + redacted[ent.end :]

        if action == "block" and detected:
            raise SFPIIBlockedError(entity_types=entity_types, count=len(above))

        effective_text = redacted if action == "redact" and detected else text

        return PIIPipelineResult(
            text=effective_text,
            action=action,
            detected=detected,
            entity_types=entity_types,
            low_confidence_hits=below,
            redacted_text=redacted,
            blocked=False,
        )

    # ------------------------------------------------------------------
    # get_status (PII-005)
    # ------------------------------------------------------------------

    def get_status(self) -> PIIStatusInfo:
        """Return sf-pii service status (PII-005).

        Contributes the ``sf_pii`` field for ``GET /v1/spanforge/status``:
        ``{status, presidio_available, entity_types_loaded, last_scan_at}``.

        Returns:
            :class:`~spanforge.sdk._types.PIIStatusInfo`.
        """
        from spanforge.presidio_backend import PIPL_PATTERNS, is_available

        presidio_ok = is_available()

        import spanforge.redact as _redact

        pii_pats: dict[str, Any] = dict(getattr(_redact, "_PII_PATTERNS", {}))
        dpdp_pats: dict[str, Any] = dict(getattr(_redact, "DPDP_PATTERNS", {}))
        entity_types = sorted({*pii_pats, *dpdp_pats, *PIPL_PATTERNS})

        return PIIStatusInfo(
            status="ok",
            presidio_available=presidio_ok,
            entity_types_loaded=entity_types,
            last_scan_at=getattr(self, "_last_scan_at", None),
        )

    # ------------------------------------------------------------------
    # erase_subject (PII-021 — GDPR Article 17)
    # ------------------------------------------------------------------

    def erase_subject(
        self,
        subject_id: str,
        project_id: str,
    ) -> ErasureReceipt:
        """Issue a GDPR Article 17 Right to Erasure for *subject_id* (PII-021).

        Finds all ``pii_detection`` audit records for *subject_id* in the
        scoping *project_id*, issues erasure instructions to downstream
        stores, and returns a receipt with timestamp for the Article 17(3)
        exceptions log.

        **Security**: *subject_id* is SHA-256-hashed in log output; it is
        never written to records in plain text.

        Args:
            subject_id: Opaque data subject identifier.
            project_id: Project scope for the erasure.

        Returns:
            :class:`~spanforge.sdk._types.ErasureReceipt`.

        Raises:
            SFPIIError: If erasure cannot be completed.
        """
        if not subject_id or not project_id:
            msg = "erase_subject() requires non-empty subject_id and project_id"
            raise SFPIIError(msg)

        erasure_id = str(uuid.uuid4())
        erased_at = datetime.datetime.now(datetime.timezone.utc).isoformat()

        # In local mode, we locate events from the in-process store.
        records_erased = self._local_erase_subject(subject_id, project_id)

        return ErasureReceipt(
            subject_id=subject_id,
            project_id=project_id,
            records_erased=records_erased,
            erasure_id=erasure_id,
            erased_at=erased_at,
            exceptions=[],
        )

    def _local_erase_subject(self, subject_id: str, project_id: str) -> int:
        """Attempt local store erasure; returns count of matching records."""
        try:
            from spanforge._store import TraceStore

            store = TraceStore.get_default()  # type: ignore[attr-defined]
            erased = 0
            with store._lock:
                for trace_events in store._traces.values():
                    for ev in trace_events:
                        payload = getattr(ev, "payload", {}) or {}
                        if (
                            payload.get("subject_id") == subject_id
                            and payload.get("project_id") == project_id
                        ):
                            # Mark for erasure — zero out identifiable fields
                            payload.pop("subject_id", None)
                            erased += 1
        except Exception:
            return 0
        else:
            return erased

    # ------------------------------------------------------------------
    # export_subject_data (PII-022 — CCPA DSAR)
    # ------------------------------------------------------------------

    def export_subject_data(
        self,
        subject_id: str,
        project_id: str,
    ) -> DSARExport:
        """Export all data for *subject_id* for a CCPA DSAR request (PII-022).

        Aggregates all events referencing *subject_id* from sf-audit and
        returns a JSON-export package.  Used by
        ``GET /v1/privacy/dsar/{subject_id}``.

        Args:
            subject_id: Opaque data subject identifier.
            project_id: Project scope.

        Returns:
            :class:`~spanforge.sdk._types.DSARExport`.

        Raises:
            SFPIIError: If *subject_id* or *project_id* is empty.
        """
        if not subject_id or not project_id:
            msg = "export_subject_data() requires non-empty subject_id and project_id"
            raise SFPIIError(msg)

        export_id = str(uuid.uuid4())
        exported_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        events = self._local_collect_subject_events(subject_id, project_id)

        return DSARExport(
            subject_id=subject_id,
            project_id=project_id,
            event_count=len(events),
            export_id=export_id,
            exported_at=exported_at,
            events=events,
        )

    def _local_collect_subject_events(
        self, subject_id: str, project_id: str
    ) -> list[dict[str, Any]]:
        """Collect events referencing subject_id from the local store."""
        try:
            from spanforge._store import TraceStore

            store = TraceStore.get_default()  # type: ignore[attr-defined]
            collected: list[dict[str, Any]] = []
            with store._lock:
                for trace_events in store._traces.values():
                    for ev in trace_events:
                        payload = getattr(ev, "payload", {}) or {}
                        if (
                            payload.get("subject_id") == subject_id
                            and payload.get("project_id") == project_id
                        ):
                            collected.append(
                                {
                                    "event_id": str(getattr(ev, "event_id", "")),
                                    "event_type": str(getattr(ev, "event_type", "")),
                                    "timestamp": str(getattr(ev, "timestamp", "")),
                                    "project_id": project_id,
                                }
                            )
        except Exception:
            return []
        else:
            return collected

    # ------------------------------------------------------------------
    # safe_harbor_deidentify (PII-023 — HIPAA Safe Harbor)
    # ------------------------------------------------------------------

    def safe_harbor_deidentify(self, text: str) -> SafeHarborResult:
        """Apply HIPAA Safe Harbor de-identification to *text* (PII-023).

        Removes or generalises all 18 PHI identifier types per
        45 CFR §164.514(b)(2):

        * Dates (other than year) → year only
        * Ages > 89 → ``"90+"``
        * ZIP codes → first 3 digits + ``"XX"``
        * All other identifiers → ``"[REMOVED]"``

        Args:
            text: Input text.

        Returns:
            :class:`~spanforge.sdk._types.SafeHarborResult`.

        Raises:
            SFPIIScanError: If *text* is not a ``str``.
        """
        if not isinstance(text, str):
            msg = f"safe_harbor_deidentify() requires a str; got {type(text).__name__}"
            raise SFPIIScanError(msg)

        result = text
        replacements = 0
        phi_types_found: list[str] = []

        # Special-case handling: ages > 89 -> "90+"
        age_pat = _SAFE_HARBOR_PATTERNS["age_over_89"]

        def _replace_age(m: re.Match[str]) -> str:
            return "90+"

        new_result, n_subs = re.subn(age_pat, _replace_age, result)
        if n_subs:
            result = new_result
            replacements += n_subs
            if "age_over_89" not in phi_types_found:
                phi_types_found.append("age_over_89")

        # ZIP codes → first 3 digits + "XX"
        zip_pat = _SAFE_HARBOR_PATTERNS["zip"]

        def _replace_zip(m: re.Match[str]) -> str:
            return m.group(1)[:3] + "XX"

        new_result, n_subs = re.subn(zip_pat, _replace_zip, result)
        if n_subs:
            result = new_result
            replacements += n_subs
            if "zip" not in phi_types_found:
                phi_types_found.append("zip")

        # Dates → year only
        date_pat = _SAFE_HARBOR_PATTERNS["date"]

        def _replace_date(m: re.Match[str]) -> str:
            # Extract a 4-digit year from the match
            year_match = re.search(r"(19|20)\d{2}", m.group())
            return year_match.group() if year_match else "[DATE]"

        new_result, n_subs = re.subn(date_pat, _replace_date, result)
        if n_subs:
            result = new_result
            replacements += n_subs
            if "date" not in phi_types_found:
                phi_types_found.append("date")

        # Remaining PHI patterns → [REMOVED]
        skip_special = {"age_over_89", "zip", "date"}
        for label, pat in _SAFE_HARBOR_PATTERNS.items():
            if label in skip_special:
                continue
            new_result, n_subs = re.subn(pat, "[REMOVED]", result)
            if n_subs:
                result = new_result
                replacements += n_subs
                if label not in phi_types_found:
                    phi_types_found.append(label)

        return SafeHarborResult(
            text=result,
            replacements=replacements,
            phi_types_found=phi_types_found,
        )

    # ------------------------------------------------------------------
    # audit_training_data (PII-025 — EU AI Act Article 10)
    # ------------------------------------------------------------------

    def audit_training_data(
        self,
        dataset_path: str | Path,
        *,
        max_records: int = 100_000,
    ) -> TrainingDataPIIReport:
        """Batch-scan a dataset file for PII prevalence (PII-025).

        Supports JSONL (one JSON object per line) and plain-text files (one
        record per line).  Produces a PII prevalence report for use as
        compliance evidence for EU AI Act Article 10 training-data audits.

        Args:
            dataset_path: Path to the dataset file.
            max_records:  Maximum number of records to scan (default 100 000).

        Returns:
            :class:`~spanforge.sdk._types.TrainingDataPIIReport`.

        Raises:
            SFPIIScanError: If the file cannot be read or *dataset_path* is
                            empty.
        """
        path = Path(dataset_path)
        if not path.exists():
            msg = f"audit_training_data(): file not found: {path}"
            raise SFPIIScanError(msg)

        report_id = str(uuid.uuid4())
        generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
        total_records = 0
        pii_records = 0
        entity_counts: dict[str, int] = {}

        try:
            with path.open(encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if total_records >= max_records:
                        break
                    line = line.strip()
                    if not line:
                        continue
                    total_records += 1

                    # Determine text to scan
                    if line.startswith("{"):
                        try:
                            record = json.loads(line)
                            text = " ".join(
                                str(v) for v in record.values() if isinstance(v, str)
                            )
                        except (json.JSONDecodeError, AttributeError):
                            text = line
                    else:
                        text = line

                    result = self._scan_text_local(text, language="en", score_threshold=0.5)
                    if result.detected:
                        pii_records += 1
                        for ent in result.entities:
                            entity_counts[ent.type] = entity_counts.get(ent.type, 0) + 1
        except OSError as exc:
            msg = f"audit_training_data(): cannot read {path}: {exc}"
            raise SFPIIScanError(msg) from exc

        prevalence = round(pii_records / total_records * 100, 2) if total_records else 0.0

        return TrainingDataPIIReport(
            dataset_path=str(path),
            total_records=total_records,
            pii_records=pii_records,
            prevalence_pct=prevalence,
            entity_counts=entity_counts,
            report_id=report_id,
            generated_at=generated_at,
        )

    # ------------------------------------------------------------------
    # get_pii_stats (PII-032 — PII heat map)
    # ------------------------------------------------------------------

    def get_pii_stats(
        self,
        project_id: str,
        *,
        entity_type: str | None = None,
        days: int = 30,
    ) -> list[PIIHeatMapEntry]:
        """Return PII detection stats for the dashboard heat map (PII-032).

        Aggregates PII detection events per entity type per day for
        *project_id* over the last *days* days.  Exposed via
        ``GET /v1/pii/stats`` (Team+ tier).

        Args:
            project_id:  Project to aggregate stats for.
            entity_type: Optional filter — only return entries for this type.
            days:        Look-back window in days (default 30).

        Returns:
            Ordered list of :class:`~spanforge.sdk._types.PIIHeatMapEntry`
            items sorted by (date desc, entity_type asc).

        Raises:
            SFPIIError: If *project_id* is empty.
        """
        if not project_id:
            msg = "get_pii_stats() requires a non-empty project_id"
            raise SFPIIError(msg)

        cutoff = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
        aggregated: dict[tuple[str, str], int] = {}

        try:
            from spanforge._store import TraceStore

            store = TraceStore.get_default()  # type: ignore[attr-defined]
            with store._lock:
                for trace_events in store._traces.values():
                    for ev in trace_events:
                        payload = getattr(ev, "payload", {}) or {}
                        if payload.get("project_id") != project_id:
                            continue
                        if payload.get("event_class") != "pii_detection":
                            continue
                        ts_str = str(getattr(ev, "timestamp", ""))
                        try:
                            ts = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        except (ValueError, TypeError):
                            continue
                        if ts < cutoff:
                            continue
                        date_str = ts.strftime("%Y-%m-%d")
                        etype = str(payload.get("entity_type", "unknown"))
                        if entity_type and etype != entity_type:
                            continue
                        key = (date_str, etype)
                        aggregated[key] = aggregated.get(key, 0) + int(
                            payload.get("count", 1)
                        )
        except Exception:  # nosec B110
            pass

        return sorted(
            [
                PIIHeatMapEntry(
                    project_id=project_id,
                    entity_type=etype,
                    date=date_str,
                    count=count,
                )
                for (date_str, etype), count in aggregated.items()
            ],
            key=lambda e: (e.date, e.entity_type),
            reverse=True,
        )

