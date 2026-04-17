"""spanforge.sdk.secrets — SpanForge sf-secrets client.

Implements the full sf-secrets API surface for Phase 2 of the SpanForge
roadmap.  All operations run locally in-process (zero external dependencies)
when ``config.endpoint`` is empty or when the remote service is unreachable
and ``config.local_fallback_enabled`` is ``True``.

Local-mode feature parity
--------------------------
*  :meth:`scan`        — scan raw text for secrets using the built-in engine.
*  :meth:`scan_batch`  — scan multiple texts concurrently.
*  :meth:`get_status`  — return scanner configuration and health information.

Security requirements
---------------------
*  ``SecretHit.redacted_value`` is **always** ``"[REDACTED:<SECRET_TYPE>]"`` —
   the matched secret value is never stored or transmitted.
*  ``SecretStr`` API keys are never written to logs.
*  All ``auto_blocked=True`` results should cause the caller to refuse storage
   or further processing of the original text.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.sdk._exceptions import SFSecretsError, SFSecretsScanError
from spanforge.secrets import SecretsScanner, SecretsScanResult

__all__ = ["SFSecretsClient"]

_log = logging.getLogger(__name__)


class SFSecretsClient(SFServiceClient):
    """SpanForge sf-secrets service client.

    Provides secrets scanning over the full :class:`~spanforge.secrets.SecretsScanner`
    detection engine.  When ``config.endpoint`` is empty (local mode), all
    logic runs in-process.  When a remote endpoint is configured, the client
    will attempt to call the remote service and fall back to local mode if
    ``local_fallback_enabled`` is ``True``.

    Args:
        config: :class:`~spanforge.sdk._base.SFClientConfig` instance.

    Example::

        from spanforge.sdk import sf_secrets

        # Scan a string for secrets
        result = sf_secrets.scan("export STRIPE_KEY=sk_live_abc123...")
        if result.auto_blocked:
            raise RuntimeError("Secrets detected — refusing to process")
        safe_text = result.redacted_text
    """

    def __init__(self, config: SFClientConfig) -> None:
        super().__init__(config, service_name="secrets")
        self._scanner = SecretsScanner()

    # ------------------------------------------------------------------
    # scan
    # ------------------------------------------------------------------

    def scan(
        self,
        text: str,
        *,
        confidence_threshold: float = 0.75,
        extra_allowlist: frozenset[str] | None = None,
    ) -> SecretsScanResult:
        """Scan *text* for secrets.

        Args:
            text:                 The raw string to scan.  May be any length.
            confidence_threshold: Minimum confidence to include a hit in the
                                  result (default: ``0.75``).  Zero-tolerance
                                  types are always included.
            extra_allowlist:      Additional literal strings to suppress.

        Returns:
            :class:`~spanforge.secrets.SecretsScanResult`.

        Raises:
            SFSecretsScanError:        If *text* is not a ``str`` or scanning fails.
            SFSecretsBlockedError:     If ``auto_blocked=True`` and the caller should
                                       not continue processing.  (**Not** raised
                                       automatically — callers must check ``result.auto_blocked``
                                       and raise this themselves if required by their policy.)
            SFServiceUnavailableError: Circuit breaker open and fallback disabled.
        """
        if not isinstance(text, str):
            msg = f"scan() requires a str; got {type(text).__name__}"
            raise SFSecretsScanError(msg)

        if self._is_local_mode() or self._config.local_fallback_enabled:
            return self._scan_local(
                text,
                confidence_threshold=confidence_threshold,
                extra_allowlist=extra_allowlist,
            )
        return self._scan_remote(text, confidence_threshold=confidence_threshold)

    def _scan_local(
        self,
        text: str,
        *,
        confidence_threshold: float,
        extra_allowlist: frozenset[str] | None,
    ) -> SecretsScanResult:
        """Run the in-process scanner."""
        try:
            if extra_allowlist:
                scanner = SecretsScanner(
                    confidence_threshold=confidence_threshold,
                    extra_allowlist=extra_allowlist,
                )
            else:
                scanner = SecretsScanner(confidence_threshold=confidence_threshold)
            return scanner.scan(text, confidence_threshold=confidence_threshold)
        except (TypeError, ValueError) as exc:
            raise SFSecretsScanError(str(exc)) from exc
        except Exception as exc:
            raise SFSecretsError(f"Unexpected error during secrets scan: {exc}") from exc

    def _scan_remote(self, text: str, *, confidence_threshold: float) -> SecretsScanResult:
        """Call the remote sf-secrets service."""
        from spanforge.secrets import SecretHit

        body: dict[str, Any] = {
            "text": text,
            "confidence_threshold": confidence_threshold,
        }
        try:
            raw = self._request("POST", "/secrets/scan", body=body)
        except Exception:
            if self._config.local_fallback_enabled:
                _log.warning(
                    "sf-secrets remote scan failed; falling back to local mode",
                    exc_info=True,
                )
                return self._scan_local(
                    text,
                    confidence_threshold=confidence_threshold,
                    extra_allowlist=None,
                )
            raise

        hits = [
            SecretHit(
                secret_type=str(h.get("secret_type", "unknown")),
                start=int(h.get("start", 0)),
                end=int(h.get("end", 0)),
                confidence=float(h.get("confidence", 0.75)),
                redacted_value=str(
                    h.get("redacted_value", f"[REDACTED:{h.get('secret_type', 'UNKNOWN').upper()}]")
                ),
                auto_blocked=bool(h.get("auto_blocked", False)),
                vault_hint=str(h.get("vault_hint", "")),
            )
            for h in raw.get("hits", [])
        ]
        return SecretsScanResult(
            detected=bool(raw.get("detected", False)),
            hits=hits,
            auto_blocked=bool(raw.get("auto_blocked", False)),
            redacted_text=str(raw.get("redacted_text", text)),
            secret_types=list(raw.get("secret_types", [])),
            confidence_scores=list(raw.get("confidence_scores", [])),
        )

    # ------------------------------------------------------------------
    # scan_batch
    # ------------------------------------------------------------------

    def scan_batch(
        self,
        texts: list[str],
        *,
        confidence_threshold: float = 0.75,
    ) -> list[SecretsScanResult]:
        """Scan a list of strings concurrently.

        Uses :func:`asyncio.gather` to parallelise local scans.  If the
        event loop is already running, falls back to sequential scanning.

        Args:
            texts:                Strings to scan.
            confidence_threshold: Passed to each :meth:`scan` call.

        Returns:
            List of :class:`~spanforge.secrets.SecretsScanResult`, one per
            input string, in the same order.

        Raises:
            SFSecretsScanError: If any element of *texts* is not a ``str``.
        """
        for i, t in enumerate(texts):
            if not isinstance(t, str):
                msg = f"scan_batch() element {i} is not a str; got {type(t).__name__}"
                raise SFSecretsScanError(msg)

        try:
            return asyncio.run(
                self._scan_batch_async(texts, confidence_threshold=confidence_threshold)
            )
        except RuntimeError:
            # Event loop already running — fall back to sequential
            return [
                self.scan(t, confidence_threshold=confidence_threshold) for t in texts
            ]

    async def _scan_batch_async(
        self,
        texts: list[str],
        *,
        confidence_threshold: float,
    ) -> list[SecretsScanResult]:
        """Async helper — scan all texts concurrently in the thread pool."""
        loop = asyncio.get_running_loop()
        tasks = [
            loop.run_in_executor(
                None,
                lambda t=text: self.scan(t, confidence_threshold=confidence_threshold),
            )
            for text in texts
        ]
        return list(await asyncio.gather(*tasks))

    # ------------------------------------------------------------------
    # get_status
    # ------------------------------------------------------------------

    def get_status(self) -> dict[str, Any]:
        """Return scanner status and configuration.

        Returns a dictionary with:

        *  ``"mode"``                — ``"local"`` or ``"remote"``.
        *  ``"local_fallback"``      — ``True`` when fallback is enabled.
        *  ``"circuit_breaker_open"``— ``True`` when the circuit is open.
        *  ``"pattern_count"``       — Number of patterns in the registry.
        *  ``"zero_tolerance_types"``— List of zero-tolerance type labels.
        """
        from spanforge.secrets import _PATTERN_REGISTRY, _ZERO_TOLERANCE_TYPES

        return {
            "mode": "local" if self._is_local_mode() else "remote",
            "local_fallback": self._config.local_fallback_enabled,
            "circuit_breaker_open": self._circuit_breaker.is_open(),
            "pattern_count": len(_PATTERN_REGISTRY) + 1,  # +1 for generic_api_key
            "zero_tolerance_types": sorted(_ZERO_TOLERANCE_TYPES),
        }
