"""spanforge.sdk.pii — SpanForge sf-pii client.

Implements the full sf-pii API surface for Phase 2 of the SpanForge roadmap.
All operations run locally in-process (zero external dependencies) when
``config.endpoint`` is empty or when the remote service is unreachable and
``config.local_fallback_enabled`` is ``True``.

Local-mode feature parity
--------------------------
*  :meth:`scan`            — deep regex PII scan via :func:`~spanforge.redact.scan_payload`.
*  :meth:`redact`          — apply a :class:`~spanforge.redact.RedactionPolicy` to an event.
*  :meth:`contains_pii`    — check whether any unredacted PII remains in an event.
*  :meth:`assert_redacted` — raise :exc:`~spanforge.sdk._exceptions.SFPIINotRedactedError`
                             if unredacted PII is found.
*  :meth:`anonymize`       — replace PII patterns in raw text strings.
*  :meth:`wrap`            — convenience :class:`~spanforge.redact.Redactable` factory.
*  :meth:`make_policy`     — convenience :class:`~spanforge.redact.RedactionPolicy` factory.

Security requirements
---------------------
*  Scan and anonymize results **never** include matched PII values — only
   type labels, field paths, counts, and anonymized replacement text.
*  :exc:`~spanforge.sdk._exceptions.SFPIINotRedactedError` messages never
   contain raw PII; context strings are SHA-256-hashed before inclusion.
*  ``SecretStr`` API keys are never written to logs.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.sdk._exceptions import (
    SFPIIError,
    SFPIINotRedactedError,
    SFPIIPolicyError,
    SFPIIScanError,
)
from spanforge.sdk._types import (
    SFPIIAnonymizeResult,
    SFPIIHit,
    SFPIIRedactResult,
    SFPIIScanResult,
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
