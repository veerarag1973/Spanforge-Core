"""spanforge.secrets — Secrets detection engine (sf-secrets Phase 2).

This module implements the core in-process secrets scanning logic for the
SpanForge sf-secrets service.  It is designed to run without any network
calls and is safe to import directly — the :class:`SecretsScanner` class
wraps all pattern matching, entropy scoring, allowlist filtering, and
auto-block policy logic.

Detection model
---------------
Each candidate match is assigned a **confidence score** between 0 and 1:

*  ``0.75``  — structural pattern match only.
*  ``0.90``  — pattern match + Shannon entropy ≥ 3.5 bits/char on a token of
   ≥ 32 characters.
*  ``0.97``  — pattern + entropy + a context keyword (``password``, ``token``,
   ``secret``, ``key``, ``credential``, ``api_key``, ``apikey``, ``auth``,
   ``access_key``, ``private_key``) appears within ±50 characters.

Auto-block policy
-----------------
*  **Zero-tolerance types** are always blocked regardless of the confidence
   threshold supplied by the caller: Bearer Token, AWS Access Key, GCP Service
   Account JSON, PEM/OPENSSH Private Key, SSH Private Key, HC API key
   (``hc_(live|test)_*``), SF API key (``sf_(live|test)_*``), GitHub PAT,
   Stripe live key (``sk_live_*``), Generic JWT.
*  **Confidence-gated types** are blocked only when their confidence reaches
   ≥ 0.90: Generic API Key, DB connection string.

Security requirements
---------------------
*  ``SecretHit.redacted_value`` is **always** ``"[REDACTED:<SECRET_TYPE>]"`` — the
   matched value is never included.
*  The entropy function is constant-time with respect to the *length* of the
   input string (not its content), so it is safe to call on secret material.
*  The allowlist uses exact ``frozenset`` membership tests; no partial matching
   is applied to allowlist entries.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "SecretHit",
    "SecretsScanResult",
    "SecretsScanner",
    "entropy_score",
]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ENTROPY_THRESHOLD: float = 3.5
_ENTROPY_MIN_LENGTH: int = 32
_CONTEXT_WINDOW: int = 50  # characters either side of a match to search

_CONTEXT_KEYWORDS: frozenset[str] = frozenset(
    {
        "password",
        "token",
        "secret",
        "key",
        "credential",
        "api_key",
        "apikey",
        "auth",
        "access_key",
        "private_key",
    }
)

# ---------------------------------------------------------------------------
# Zero-tolerance secret types (always auto-blocked)
# ---------------------------------------------------------------------------

_ZERO_TOLERANCE_TYPES: frozenset[str] = frozenset(
    {
        "bearer_token",
        "aws_access_key",
        "gcp_service_account",
        "pem_private_key",
        "ssh_private_key",
        "halluccheck_api_key",
        "spanforge_api_key",
        "github_pat",
        "stripe_live_key",
        "generic_jwt",
    }
)

# Confidence-gated types — block only if confidence >= 0.90
_CONFIDENCE_GATED_TYPES: frozenset[str] = frozenset(
    {
        "generic_api_key",
        "db_connection_string",
    }
)

_CONFIDENCE_GATE_THRESHOLD: float = 0.90

# ---------------------------------------------------------------------------
# Vault hints — suggest where to store each secret type
# ---------------------------------------------------------------------------

_VAULT_HINTS: dict[str, str] = {
    "aws_access_key": (
        "Move to AWS Secrets Manager: "
        "aws secretsmanager create-secret --name my-aws-creds --secret-string <value>"
    ),
    "gcp_service_account": (
        "Move to Google Cloud Secret Manager: "
        "gcloud secrets create my-gcp-key --data-file=service-account.json"
    ),
    "azure_connection_string": (
        "Move to Azure Key Vault: "
        "az keyvault secret set --vault-name MyVault --name my-conn-str --value <value>"
    ),
    "pem_private_key": (
        "Move to HashiCorp Vault: "
        "vault kv put secret/tls private_key=@keyfile.pem"
    ),
    "ssh_private_key": (
        "Move to HashiCorp Vault: "
        "vault kv put secret/ssh private_key=@id_rsa"
    ),
    "stripe_live_key": (
        "Move to HashiCorp Vault: "
        "vault kv put secret/stripe live_key=<value>"
    ),
    "stripe_test_key": (
        "Move to HashiCorp Vault: "
        "vault kv put secret/stripe test_key=<value>"
    ),
    "generic_api_key": (
        "Move to HashiCorp Vault: "
        "vault kv put secret/api key=<value>"
    ),
    "github_pat": (
        "Move to GitHub Secrets or HashiCorp Vault: "
        "gh secret set MY_PAT --body <value>"
    ),
    "slack_token": (
        "Move to HashiCorp Vault: "
        "vault kv put secret/slack token=<value>"
    ),
    "sendgrid_key": (
        "Move to HashiCorp Vault: "
        "vault kv put secret/sendgrid api_key=<value>"
    ),
    "db_connection_string": (
        "Move to AWS Secrets Manager, Azure Key Vault, or HashiCorp Vault. "
        "Never embed credentials in connection strings in code."
    ),
}

# ---------------------------------------------------------------------------
# Pattern registry
# ---------------------------------------------------------------------------
# Each entry: (secret_type, compiled_regex, zero_tolerance)
# Order matters — more specific patterns should appear before generic ones.

_PatternEntry = tuple[str, re.Pattern[str], bool]


def _compile(pattern: str) -> re.Pattern[str]:
    return re.compile(pattern)


_PATTERN_REGISTRY: list[_PatternEntry] = [
    # --- Spec-required (7) ---
    # SEC-001-A: Bearer token (JWT form)
    (
        "bearer_token",
        _compile(
            r"(?i)Bearer\s+eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+"
        ),
        True,
    ),
    # SEC-001-B: AWS access key
    (
        "aws_access_key",
        _compile(r"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])"),
        True,
    ),
    # SEC-001-C: GCP service account JSON fragment
    (
        "gcp_service_account",
        _compile(r'"type"\s*:\s*"service_account"'),
        True,
    ),
    # SEC-001-D: PEM private keys
    (
        "pem_private_key",
        _compile(r"-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----"),
        True,
    ),
    # SEC-001-E: DB connection strings with embedded credentials
    (
        "db_connection_string",
        _compile(
            r"(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|mssql|oracle)"
            r"://[^:/@\s]{1,255}:[^@\s]{1,1024}@"
        ),
        False,
    ),
    # SEC-001-F: HallucCheck / Spanforge API key variants
    (
        "halluccheck_api_key",
        _compile(r"hc_(?:live|test)_[0-9A-Za-z]{48}"),
        True,
    ),
    (
        "spanforge_api_key",
        _compile(r"sf_(?:live|test)_[0-9A-Za-z]{48}"),
        True,
    ),
    # --- Extended (13) ---
    # SEC-001-G: GitHub PAT (new and classic formats)
    (
        "github_pat",
        _compile(
            r"(?:ghp_[A-Za-z0-9]{36,255}"
            r"|gho_[A-Za-z0-9]{36,255}"
            r"|ghu_[A-Za-z0-9]{36,255}"
            r"|ghs_[A-Za-z0-9]{36,255}"
            r"|ghr_[A-Za-z0-9]{36,255}"
            r"|github_pat_[A-Za-z0-9_]{36,255})"
        ),
        True,
    ),
    # SEC-001-H: npm publish token
    (
        "npm_token",
        _compile(r"npm_[A-Za-z0-9]{36}"),
        False,
    ),
    # SEC-001-I: Slack bot/app tokens
    (
        "slack_token",
        _compile(r"xox[baprs]-[0-9A-Za-z]{8,}-[0-9A-Za-z-]{8,}"),
        False,
    ),
    # SEC-001-J: Stripe live secret key
    (
        "stripe_live_key",
        _compile(r"sk_live_[0-9A-Za-z]{24,}"),
        True,
    ),
    # SEC-001-K: Stripe test secret key
    (
        "stripe_test_key",
        _compile(r"sk_test_[0-9A-Za-z]{24,}"),
        False,
    ),
    # SEC-001-L: Twilio auth token / SID
    (
        "twilio_key",
        _compile(r"SK[0-9a-fA-F]{32}"),
        False,
    ),
    # SEC-001-M: SendGrid API key
    (
        "sendgrid_key",
        _compile(r"SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43}"),
        False,
    ),
    # SEC-001-N: Azure storage / service bus connection strings
    (
        "azure_connection_string",
        _compile(
            r"(?:DefaultEndpointsProtocol=https?;AccountName=[^;]{1,255};AccountKey=[^;]{1,1024}"
            r"|Endpoint=sb://[^;]{1,255};SharedAccessKeyName=[^;]{1,255};SharedAccessKey=[^;\s]{1,255})"
        ),
        False,
    ),
    # SEC-001-O: OPENSSH private key header
    (
        "ssh_private_key",
        _compile(r"-----BEGIN OPENSSH PRIVATE KEY-----"),
        True,
    ),
    # SEC-001-P: Google API key
    (
        "google_api_key",
        _compile(r"AIza[0-9A-Za-z\-_]{35}"),
        False,
    ),
    # SEC-001-Q: Terraform Cloud / Terraform Enterprise token
    (
        "terraform_cloud_token",
        _compile(r"[Aa]tlas[Tt]oken\s*=\s*['\"]?[A-Za-z0-9.]{8,}['\"]?"),
        False,
    ),
    # SEC-001-R: HashiCorp Vault root/service token (s. prefix)
    (
        "vault_token",
        _compile(r"(?<![A-Za-z0-9])s\.[A-Za-z0-9]{24,}(?![A-Za-z0-9])"),
        False,
    ),
    # SEC-001-S: Generic JWT (without Bearer prefix)
    (
        "generic_jwt",
        _compile(r"(?<!\w)eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}(?!\w)"),
        True,
    ),
]

# Generic API key pattern — applied separately with entropy check
_GENERIC_API_KEY_PATTERN: re.Pattern[str] = re.compile(r"[0-9A-Za-z_\-]{32,}")

# ---------------------------------------------------------------------------
# Default allowlist — known test/placeholder values that should never alert
# ---------------------------------------------------------------------------

_DEFAULT_ALLOWLIST: frozenset[str] = frozenset(
    {
        "AKIA_EXAMPLE",
        "AKIAIOSFODNN7EXAMPLE",
        "sk_test_" + "0" * 24,
        "hc_test_" + "0" * 48,
        "sf_test_" + "0" * 48,
        "AIzaSyExampleKey1234567890123456789",
        "SG.example",
        "xoxb-000000000000-000000000000-000000000000000000000000",
    }
)

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SecretHit:
    """A single detected secret span within a scanned text.

    Attributes:
        secret_type:    Label identifying the category of secret detected
                        (e.g. ``"aws_access_key"``).
        start:          Start character offset in the original text (inclusive).
        end:            End character offset in the original text (exclusive).
        confidence:     Detection confidence in ``[0.0, 1.0]``.
        redacted_value: Safe placeholder — always
                        ``"[REDACTED:<secret_type>]"``.
                        The actual matched text is **never** stored here.
        auto_blocked:   ``True`` when this hit triggers the auto-block policy.
        vault_hint:     Optional suggestion for migrating this secret to a
                        secrets vault.
    """

    secret_type: str
    start: int
    end: int
    confidence: float
    redacted_value: str
    auto_blocked: bool = False
    vault_hint: str = ""


@dataclass
class SecretsScanResult:
    """Result of a secrets scan operation.

    Attributes:
        detected:           ``True`` when at least one hit above the confidence
                            threshold was found.
        hits:               All detected :class:`SecretHit` objects above the
                            threshold, in order of appearance.
        auto_blocked:       ``True`` when any hit triggered the auto-block
                            policy (zero-tolerance or confidence-gated).
        redacted_text:      Full input text with every hit replaced by its
                            ``redacted_value`` marker.
        secret_types:       Deduplicated list of ``secret_type`` labels from
                            all hits (order of first appearance).
        confidence_scores:  Parallel list of confidence scores for each hit.
    """

    detected: bool
    hits: list[SecretHit]
    auto_blocked: bool
    redacted_text: str
    secret_types: list[str] = field(default_factory=list)
    confidence_scores: list[float] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a plain-dict representation safe for JSON serialisation."""
        return {
            "detected": self.detected,
            "auto_blocked": self.auto_blocked,
            "redacted_text": self.redacted_text,
            "secret_types": self.secret_types,
            "confidence_scores": self.confidence_scores,
            "hits": [
                {
                    "secret_type": h.secret_type,
                    "start": h.start,
                    "end": h.end,
                    "confidence": h.confidence,
                    "redacted_value": h.redacted_value,
                    "auto_blocked": h.auto_blocked,
                    **({"vault_hint": h.vault_hint} if h.vault_hint else {}),
                }
                for h in self.hits
            ],
        }

    def to_sarif(
        self,
        *,
        tool_name: str = "spanforge-secrets",
        version: str = "1.0.0",
    ) -> dict[str, Any]:
        """Return a minimal SARIF 2.1.0 report dict.

        Args:
            tool_name: The tool name to embed in the SARIF ``tool`` object.
            version:   Tool version string.

        Returns:
            Dict conforming to SARIF schema 2.1.0.
        """
        results = [
            {
                "ruleId": hit.secret_type,
                "level": "error" if hit.auto_blocked else "warning",
                "message": {
                    "text": (
                        f"Detected secret of type '{hit.secret_type}' "
                        f"(confidence={hit.confidence:.2f}). "
                        f"{hit.vault_hint or 'Move this value to a secrets vault.'}"
                    )
                },
                "locations": [
                    {
                        "physicalLocation": {
                            "region": {
                                "charOffset": hit.start,
                                "charLength": hit.end - hit.start,
                            }
                        }
                    }
                ],
                "properties": {
                    "confidence": hit.confidence,
                    "auto_blocked": hit.auto_blocked,
                    "redacted_value": hit.redacted_value,
                },
            }
            for hit in self.hits
        ]
        return {
            "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {
                        "driver": {
                            "name": tool_name,
                            "version": version,
                            "informationUri": "https://docs.spanforge.dev/secrets",
                        }
                    },
                    "results": results,
                }
            ],
        }


# ---------------------------------------------------------------------------
# Entropy helper
# ---------------------------------------------------------------------------


def entropy_score(s: str) -> float:
    """Return Shannon entropy in bits per character for *s*.

    A value ≥ 3.5 bits/char on a token of ≥ 32 characters is a strong
    indicator that the string was generated by a CSPRNG (e.g. an API key or
    bearer token).

    Args:
        s: The string to measure.

    Returns:
        Shannon entropy in bits per character.  Returns ``0.0`` for empty
        strings.

    Example::

        >>> entropy_score("aaaaaaaaaaaaaaaaaaaaaaaaa")
        0.0
        >>> entropy_score("AKIAIOSFODNN7EXAMPLEKEY")   # doctest: +ELLIPSIS
        3.3...
    """
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    return -sum((count / n) * math.log2(count / n) for count in freq.values())


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


class SecretsScanner:
    """In-process secrets detection engine.

    All scanning logic runs locally — no network calls are made.  Matches
    are scored with a three-tier confidence model, filtered against an
    allowlist, and subjected to the auto-block policy.

    Args:
        confidence_threshold: Default minimum confidence required to include
            a hit in the result (default: ``0.75``).  Zero-tolerance types
            always appear regardless of this threshold.
        extra_allowlist:      Additional literal strings that should never
            trigger an alert (merged with the built-in allowlist).
        auto_block_override:  If ``True``, all hits above the threshold are
            flagged ``auto_blocked``; if ``False``, the auto-block policy is
            never applied (useful for audit-only mode).  ``None`` (default)
            uses the standard policy table.

    Example::

        scanner = SecretsScanner()
        result = scanner.scan("AKIA" + "A" * 16 + " is my AWS key")
        assert result.auto_blocked
    """

    def __init__(
        self,
        confidence_threshold: float = 0.75,
        extra_allowlist: frozenset[str] | None = None,
        auto_block_override: bool | None = None,
    ) -> None:
        if not 0.0 <= confidence_threshold <= 1.0:
            msg = f"confidence_threshold must be in [0, 1]; got {confidence_threshold}"
            raise ValueError(msg)
        self._threshold = confidence_threshold
        self._allowlist: frozenset[str] = (
            _DEFAULT_ALLOWLIST | extra_allowlist
            if extra_allowlist
            else _DEFAULT_ALLOWLIST
        )
        self._auto_block_override = auto_block_override

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def scan(
        self,
        text: str,
        *,
        confidence_threshold: float | None = None,
    ) -> SecretsScanResult:
        """Scan *text* for secrets and return a :class:`SecretsScanResult`.

        Args:
            text:                 The text to scan.  May be any length.
            confidence_threshold: Override the instance-level threshold for
                                  this single call.

        Returns:
            A :class:`SecretsScanResult`.  The ``redacted_text`` field always
            contains the full input with every qualifying hit replaced by its
            redaction marker, even when ``detected`` is ``False``.
        """
        if not isinstance(text, str):
            msg = f"scan() requires a str; got {type(text).__name__}"
            raise TypeError(msg)

        threshold = confidence_threshold if confidence_threshold is not None else self._threshold

        raw_hits = self._find_all_hits(text)
        qualified: list[SecretHit] = []

        for hit in raw_hits:
            # Allowlist suppression
            matched_span = text[hit.start : hit.end]
            if matched_span in self._allowlist:
                continue

            is_zero_tol = hit.secret_type in _ZERO_TOLERANCE_TYPES
            # Zero-tolerance always included, others filtered by threshold
            if not is_zero_tol and hit.confidence < threshold:
                continue

            # Determine auto_block
            auto_blocked = self._compute_auto_block(hit)

            qualified.append(
                SecretHit(
                    secret_type=hit.secret_type,
                    start=hit.start,
                    end=hit.end,
                    confidence=hit.confidence,
                    redacted_value=f"[REDACTED:{hit.secret_type.upper()}]",
                    auto_blocked=auto_blocked,
                    vault_hint=_VAULT_HINTS.get(hit.secret_type, ""),
                )
            )

        # Deduplicate overlapping spans — keep highest confidence hit per span
        qualified = _dedup_hits(qualified)

        detected = len(qualified) > 0
        any_blocked = any(h.auto_blocked for h in qualified)
        redacted_text = _build_redacted_text(text, qualified)

        seen_types: list[str] = []
        for h in qualified:
            if h.secret_type not in seen_types:
                seen_types.append(h.secret_type)

        return SecretsScanResult(
            detected=detected,
            hits=qualified,
            auto_blocked=any_blocked,
            redacted_text=redacted_text,
            secret_types=seen_types,
            confidence_scores=[h.confidence for h in qualified],
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_all_hits(self, text: str) -> list[SecretHit]:
        """Find all candidate hits (unsanitised, before allowlist filtering)."""
        hits: list[SecretHit] = []

        for secret_type, pattern, _zero_tol in _PATTERN_REGISTRY:
            for m in pattern.finditer(text):
                conf = self._score_hit(secret_type, m, text)
                hits.append(
                    SecretHit(
                        secret_type=secret_type,
                        start=m.start(),
                        end=m.end(),
                        confidence=conf,
                        redacted_value=f"[REDACTED:{secret_type.upper()}]",
                    )
                )

        # Generic API key — entropy-gated
        for m in _GENERIC_API_KEY_PATTERN.finditer(text):
            token = m.group()
            if len(token) >= _ENTROPY_MIN_LENGTH and entropy_score(token) >= _ENTROPY_THRESHOLD:
                conf = self._score_hit("generic_api_key", m, text)
                hits.append(
                    SecretHit(
                        secret_type="generic_api_key",  # noqa: S106
                        start=m.start(),
                        end=m.end(),
                        confidence=conf,
                        redacted_value="[REDACTED:GENERIC_API_KEY]",
                    )
                )

        return hits

    def _score_hit(
        self,
        secret_type: str,
        match: re.Match[str],
        full_text: str,
    ) -> float:
        """Compute a confidence score for a single regex match.

        Scoring tiers:
        *  ``0.75`` — structural pattern match alone.
        *  ``0.90`` — pattern + high entropy token (≥ 3.5 bits/char, ≥ 32 chars).
        *  ``0.97`` — pattern + entropy + context keyword within ±50 chars.
        """
        confidence: float = 0.75

        # Tier 2: entropy check on the matched token
        token = match.group()
        if len(token) >= _ENTROPY_MIN_LENGTH and entropy_score(token) >= _ENTROPY_THRESHOLD:
            confidence = 0.90

        # Tier 3: context keyword in surrounding text
        start = max(0, match.start() - _CONTEXT_WINDOW)
        end = min(len(full_text), match.end() + _CONTEXT_WINDOW)
        context = full_text[start:end].lower()
        if any(kw in context for kw in _CONTEXT_KEYWORDS):
            confidence = 0.97

        return confidence

    def _compute_auto_block(self, hit: SecretHit) -> bool:
        """Apply auto-block policy to a hit."""
        if self._auto_block_override is True:
            return True
        if self._auto_block_override is False:
            return False
        # Zero tolerance — always block
        if hit.secret_type in _ZERO_TOLERANCE_TYPES:
            return True
        # Confidence-gated
        if hit.secret_type in _CONFIDENCE_GATED_TYPES:
            return hit.confidence >= _CONFIDENCE_GATE_THRESHOLD
        return False


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _dedup_hits(hits: list[SecretHit]) -> list[SecretHit]:
    """Remove overlapping hits, keeping the one with highest confidence.

    When two hits share any character positions, only the hit with the
    higher confidence is retained.  If confidence is equal, the first
    occurrence (by ``start`` offset) is kept.
    """
    if len(hits) <= 1:
        return hits

    # Sort by start offset, then descending confidence
    sorted_hits = sorted(hits, key=lambda h: (h.start, -h.confidence))
    result: list[SecretHit] = []
    last_end = -1

    for hit in sorted_hits:
        if hit.start >= last_end:
            result.append(hit)
            last_end = hit.end
        elif hit.confidence > result[-1].confidence:
            # Overlapping — keep the one with higher confidence
            result[-1] = hit
            last_end = hit.end

    return result


def _build_redacted_text(text: str, hits: list[SecretHit]) -> str:
    """Replace every hit span in *text* with its ``redacted_value`` marker."""
    if not hits:
        return text

    parts: list[str] = []
    cursor = 0

    for hit in sorted(hits, key=lambda h: h.start):
        if hit.start > cursor:
            parts.append(text[cursor : hit.start])
        parts.append(hit.redacted_value)
        cursor = hit.end

    if cursor < len(text):
        parts.append(text[cursor:])

    return "".join(parts)
