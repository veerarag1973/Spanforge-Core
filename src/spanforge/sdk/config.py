"""spanforge.sdk.config — .halluccheck.toml config block parser (Phase 9).

Implements:

* CFG-001: ``[spanforge]`` block parser — ``enabled``, ``project_id``,
  ``api_key`` (env-only, never stored), ``endpoint``,
  ``[spanforge.services]`` toggle dict, ``[spanforge.local_fallback]``.
  Unknown keys → ``WARNING``, not error.
* CFG-002: ``[spanforge.services]`` service toggles (8 booleans).
  Disabled service → always uses local fallback regardless of endpoint.
* CFG-003: ``[spanforge.local_fallback]`` sub-block — ``enabled``,
  ``max_retries``, ``timeout_ms``.  Enterprise mode: ``enabled=false``
  causes any unreachable service to raise :exc:`SFServiceUnavailableError`.
* CFG-004: ``[pii]`` block — ``enabled``, ``action``, ``threshold``,
  ``entity_types``, ``dpdp_scope``.
* CFG-005: ``[secrets]`` block — ``enabled``, ``auto_block``,
  ``confidence``, ``allowlist``, ``store_redacted``.
* CFG-006: Env var precedence — env vars always override file values.
  Startup DEBUG log prints resolved config with all secrets redacted.
* CFG-007: :func:`validate_config` — validates full schema.

Security requirements
---------------------
* ``api_key`` is **never** stored to disk.  It is only read from
  ``SPANFORGE_API_KEY`` at runtime and is never passed to
  :func:`load_config_file`.
* Resolved config is logged at DEBUG level with all secret values masked
  (``"***"``).
* Unknown top-level keys (outside known blocks) emit a ``WARNING`` but
  do not abort startup.
"""

from __future__ import annotations

import logging
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spanforge.sdk._exceptions import SFConfigError, SFConfigValidationError

__all__ = [
    "SFConfigBlock",
    "SFLocalFallbackConfig",
    "SFPIIConfig",
    "SFSecretsConfig",
    "SFServiceToggles",
    "load_config_file",
    "validate_config",
]

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known keys — used to warn on unknown entries (CFG-001)
# ---------------------------------------------------------------------------

_KNOWN_SPANFORGE_KEYS: frozenset[str] = frozenset(
    {"enabled", "project_id", "endpoint", "sandbox", "services", "local_fallback"}
)
_KNOWN_SERVICES_KEYS: frozenset[str] = frozenset(
    {
        "sf_alert",
        "sf_audit",
        "sf_cec",
        "sf_gate",
        "sf_identity",
        "sf_observe",
        "sf_pii",
        "sf_secrets",
    }
)
_KNOWN_FALLBACK_KEYS: frozenset[str] = frozenset({"enabled", "max_retries", "timeout_ms"})
_KNOWN_PII_KEYS: frozenset[str] = frozenset(
    {"action", "dpdp_scope", "enabled", "entity_types", "threshold"}
)
_KNOWN_SECRETS_KEYS: frozenset[str] = frozenset(
    {"enabled", "auto_block", "confidence", "allowlist", "store_redacted"}
)
_KNOWN_PII_ENTITY_TYPES: frozenset[str] = frozenset(
    {
        "EMAIL", "PHONE", "SSN", "CREDIT_CARD", "IBAN", "IP_ADDRESS", "URL",
        "PERSON", "LOCATION", "DATE_TIME", "NRP", "MEDICAL_LICENSE", "US_PASSPORT",
        "UK_NHS", "AU_ABN", "AU_ACN", "AU_TFN", "AU_MEDICARE", "IN_PAN", "IN_AADHAAR",
        "CRYPTO", "DRIVER_LICENSE",
    }
)
_KNOWN_PII_ACTIONS: frozenset[str] = frozenset({"flag", "redact", "block"})


# ---------------------------------------------------------------------------
# Dataclasses (CFG-002, CFG-003, CFG-004, CFG-005)
# ---------------------------------------------------------------------------


@dataclass
class SFServiceToggles:
    """Per-service enable/disable toggles (CFG-002).

    A disabled service always uses local fallback regardless of whether the
    remote endpoint is reachable.
    """

    sf_observe: bool = True
    sf_pii: bool = True
    sf_secrets: bool = True
    sf_audit: bool = True
    sf_gate: bool = True
    sf_cec: bool = True
    sf_identity: bool = True
    sf_alert: bool = True

    def is_enabled(self, name: str) -> bool:
        """Return ``True`` if the named service is enabled.

        Args:
            name: Service name, e.g. ``"sf_pii"``.

        Returns:
            ``True`` when the service toggle is on (default).
        """
        return bool(getattr(self, name, True))

    def as_dict(self) -> dict[str, bool]:
        """Return a dict of ``{service_name: enabled}``."""
        return {
            "sf_observe": self.sf_observe,
            "sf_pii": self.sf_pii,
            "sf_secrets": self.sf_secrets,
            "sf_audit": self.sf_audit,
            "sf_gate": self.sf_gate,
            "sf_cec": self.sf_cec,
            "sf_identity": self.sf_identity,
            "sf_alert": self.sf_alert,
        }


@dataclass
class SFLocalFallbackConfig:
    """``[spanforge.local_fallback]`` configuration (CFG-003).

    Enterprise mode: ``enabled=False`` causes any unreachable service to
    raise :exc:`~spanforge.sdk._exceptions.SFServiceUnavailableError`
    immediately rather than falling back to local logic.
    """

    enabled: bool = True
    max_retries: int = 3
    timeout_ms: int = 2000


@dataclass
class SFPIIConfig:
    """``[pii]`` block configuration (CFG-004).

    Attributes:
        enabled: Whether PII scanning is active (default: ``True``).
        action: What to do on a hit — ``"flag"``, ``"redact"``, or
            ``"block"`` (default: ``"redact"``).
        threshold: Confidence score [0.0-1.0] for PII detection
            (default: ``0.75``).
        entity_types: List of entity-type codes to scan for.  An empty
            list means *all* supported entity types.
        dpdp_scope: List of DPDP purposes that require consent checks.
    """

    enabled: bool = True
    action: str = "redact"
    threshold: float = 0.75
    entity_types: list[str] = field(default_factory=list)
    dpdp_scope: list[str] = field(default_factory=list)


@dataclass
class SFSecretsConfig:
    """``[secrets]`` block configuration (CFG-005).

    Attributes:
        enabled: Whether secrets scanning is active (default: ``True``).
        auto_block: Automatically block requests that contain secrets
            (default: ``True``).
        confidence: Minimum detection confidence [0.0-1.0]
            (default: ``0.75``).
        allowlist: Known-safe patterns (e.g. ``["AKIA_EXAMPLE"]``).
        store_redacted: Persist redacted versions in the audit log
            (default: ``False``).
    """

    enabled: bool = True
    auto_block: bool = True
    confidence: float = 0.75
    allowlist: list[str] = field(default_factory=list)
    store_redacted: bool = False


@dataclass
class SFConfigBlock:
    """Resolved configuration for the ``[spanforge]`` block.

    This is the single source of truth for all Phase 9 config.  Produced
    by :func:`load_config_file` after merging the TOML file with env-var
    overrides.

    Attributes:
        enabled: Whether the SpanForge integration is active.
        project_id: Default project scope.
        endpoint: Remote service endpoint URL.  Empty string → local mode.
        services: Per-service enable/disable toggles.
        local_fallback: Fallback policy configuration.
        pii: PII scanning configuration.
        secrets: Secrets scanning configuration.
    """

    enabled: bool = True
    project_id: str = ""
    endpoint: str = ""
    sandbox: bool = False
    services: SFServiceToggles = field(default_factory=SFServiceToggles)
    local_fallback: SFLocalFallbackConfig = field(default_factory=SFLocalFallbackConfig)
    pii: SFPIIConfig = field(default_factory=SFPIIConfig)
    secrets: SFSecretsConfig = field(default_factory=SFSecretsConfig)


# ---------------------------------------------------------------------------
# Minimal TOML parser (stdlib-only, Python 3.9+ compatible)
# ---------------------------------------------------------------------------

_ARRAY_STR_RE = re.compile(r'"([^"]*)"')
_ARRAY_SINGLE_STR_RE = re.compile(r"'([^']*)'")


def _parse_inline_string_array(raw: str) -> list[str]:  # pragma: no cover
    """Parse a TOML inline array of strings — ``["a", "b"]`` or ``['a', 'b']``."""
    inner = raw.strip()
    if not (inner.startswith("[") and inner.endswith("]")):
        return []
    content = inner[1:-1]
    # Try double-quoted first, then single-quoted
    results = _ARRAY_STR_RE.findall(content)
    if not results:
        results = _ARRAY_SINGLE_STR_RE.findall(content)
    return results


def _parse_toml_value(raw: str) -> Any:  # pragma: no cover
    """Parse a single TOML scalar or inline array value."""
    s = raw.strip()
    # Strip trailing inline comment (only if outside a string)
    if s and s[0] not in ('"', "'", "["):
        s = s.split("#")[0].strip()

    if s == "true":
        return True
    if s == "false":
        return False
    if s.startswith("[") and s.endswith("]"):
        return _parse_inline_string_array(s)
    if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        return s[1:-1]
    # Try numeric coercion
    try:
        return float(s) if "." in s else int(s)
    except ValueError:
        return s


def _parse_toml(text: str) -> dict[str, Any]:
    """Parse a ``.halluccheck.toml`` file into a nested dict.

    Handles the subset of TOML used by SpanForge config:
    * ``[section]`` and ``[section.sub]`` headers.
    * ``key = value`` (bool, int, float, quoted string, inline string array).
    * ``# comments`` (line and inline).
    * Blank lines.

    This intentionally does NOT handle multi-line strings, inline tables,
    or other advanced TOML features which are not used in ``.halluccheck.toml``.
    """
    # Prefer stdlib tomllib on Python 3.11+
    if sys.version_info >= (3, 11):
        import tomllib  # type: ignore[import-not-found]

        return tomllib.loads(text)  # type: ignore[return-value]

    result: dict[str, Any] = {}  # pragma: no cover
    current_path: list[str] = []  # pragma: no cover

    for raw_line in text.splitlines():  # pragma: no cover
        line = raw_line.strip()

        # Skip blank lines and comments
        if not line or line.startswith("#"):
            continue

        # Section header: [section] or [section.sub]
        if line.startswith("[") and not line.startswith("[["):
            # Strip inline comment after closing bracket
            closing = line.find("]")
            if closing == -1:
                continue
            header = line[1:closing].strip()
            current_path = header.split(".")
            # Ensure the nested path exists
            node: dict[str, Any] = result
            for part in current_path:
                node = node.setdefault(part, {})
            continue

        # Key = value
        if "=" in line:
            eq_pos = line.index("=")
            key = line[:eq_pos].strip()
            raw_val = line[eq_pos + 1 :].strip()
            value = _parse_toml_value(raw_val)
            # Navigate to current section
            node = result
            for part in current_path:
                node = node.setdefault(part, {})
            node[key] = value

    return result  # pragma: no cover


# ---------------------------------------------------------------------------
# Config loading (CFG-001 through CFG-006)
# ---------------------------------------------------------------------------


def _warn_unknown(section_label: str, keys: set[str], known: frozenset[str]) -> None:
    for k in keys - known:
        _log.warning(
            "Unknown key %r in [%s] of .halluccheck.toml — ignored.",
            k,
            section_label,
        )


def load_config_file(
    path: str | Path | None = None,
) -> SFConfigBlock:
    """Parse a ``.halluccheck.toml`` file and return an :class:`SFConfigBlock`.

    Env vars are applied **after** file parsing and always take precedence
    (CFG-006).  The resolved config is logged at ``DEBUG`` level with all
    secret values redacted.

    If ``path`` is ``None`` the function searches for ``.halluccheck.toml``
    first in the current working directory, then in the user's home directory
    (``~/.halluccheck.toml``).  If no file is found a default
    :class:`SFConfigBlock` is returned with all values populated from env
    vars and defaults.

    Args:
        path: Explicit path to the config file.  Pass ``None`` for automatic
            discovery.

    Returns:
        A fully resolved :class:`SFConfigBlock`.

    Raises:
        :exc:`~spanforge.sdk._exceptions.SFConfigError`: If the file exists
            but cannot be parsed.
    """
    raw: dict[str, Any] = {}

    resolved_path = _find_config(path)
    if resolved_path is not None:
        try:
            text = resolved_path.read_text(encoding="utf-8")
            raw = _parse_toml(text)
        except Exception as exc:
            raise SFConfigError(f"Failed to parse {resolved_path}: {exc}") from exc
        _log.debug("Loaded SpanForge config from %s", resolved_path)
    else:
        _log.debug("No .halluccheck.toml found; using defaults + env vars.")

    block = _build_config_block(raw)
    _apply_env_overrides(block)
    _log_resolved_config(block)
    return block


def _find_config(path: str | Path | None) -> Path | None:
    """Resolve config file location."""
    if path is not None:
        p = Path(path)
        return p if p.exists() else None
    for candidate in (
        Path.cwd() / ".halluccheck.toml",
        Path.home() / ".halluccheck.toml",
    ):
        if candidate.exists():
            return candidate
    return None


def _build_config_block(raw: dict[str, Any]) -> SFConfigBlock:
    """Construct an :class:`SFConfigBlock` from the raw parsed dict."""
    sf_raw = raw.get("spanforge", {})
    if not isinstance(sf_raw, dict):
        sf_raw = {}

    _warn_unknown("spanforge", set(sf_raw.keys()), _KNOWN_SPANFORGE_KEYS)

    # [spanforge.services]
    svc_raw = sf_raw.get("services", {})
    if not isinstance(svc_raw, dict):
        svc_raw = {}
    _warn_unknown("spanforge.services", set(svc_raw.keys()), _KNOWN_SERVICES_KEYS)

    toggles = SFServiceToggles(
        sf_observe=bool(svc_raw.get("sf_observe", True)),
        sf_pii=bool(svc_raw.get("sf_pii", True)),
        sf_secrets=bool(svc_raw.get("sf_secrets", True)),
        sf_audit=bool(svc_raw.get("sf_audit", True)),
        sf_gate=bool(svc_raw.get("sf_gate", True)),
        sf_cec=bool(svc_raw.get("sf_cec", True)),
        sf_identity=bool(svc_raw.get("sf_identity", True)),
        sf_alert=bool(svc_raw.get("sf_alert", True)),
    )

    # [spanforge.local_fallback]
    fb_raw = sf_raw.get("local_fallback", {})
    if not isinstance(fb_raw, dict):
        fb_raw = {}
    _warn_unknown("spanforge.local_fallback", set(fb_raw.keys()), _KNOWN_FALLBACK_KEYS)

    fallback = SFLocalFallbackConfig(
        enabled=bool(fb_raw.get("enabled", True)),
        max_retries=int(fb_raw.get("max_retries", 3)),
        timeout_ms=int(fb_raw.get("timeout_ms", 2000)),
    )

    # [pii]
    pii_raw = raw.get("pii", {})
    if not isinstance(pii_raw, dict):
        pii_raw = {}
    _warn_unknown("pii", set(pii_raw.keys()), _KNOWN_PII_KEYS)

    entity_types = pii_raw.get("entity_types", [])
    if not isinstance(entity_types, list):
        entity_types = []
    dpdp_scope = pii_raw.get("dpdp_scope", [])
    if not isinstance(dpdp_scope, list):
        dpdp_scope = []

    pii_cfg = SFPIIConfig(
        enabled=bool(pii_raw.get("enabled", True)),
        action=str(pii_raw.get("action", "redact")),
        threshold=float(pii_raw.get("threshold", 0.75)),
        entity_types=list(entity_types),
        dpdp_scope=list(dpdp_scope),
    )

    # [secrets]
    sec_raw = raw.get("secrets", {})
    if not isinstance(sec_raw, dict):
        sec_raw = {}
    _warn_unknown("secrets", set(sec_raw.keys()), _KNOWN_SECRETS_KEYS)

    allowlist = sec_raw.get("allowlist", [])
    if not isinstance(allowlist, list):
        allowlist = []

    secrets_cfg = SFSecretsConfig(
        enabled=bool(sec_raw.get("enabled", True)),
        auto_block=bool(sec_raw.get("auto_block", True)),
        confidence=float(sec_raw.get("confidence", 0.75)),
        allowlist=list(allowlist),
        store_redacted=bool(sec_raw.get("store_redacted", False)),
    )

    return SFConfigBlock(
        enabled=bool(sf_raw.get("enabled", True)),
        project_id=str(sf_raw.get("project_id", "")),
        endpoint=str(sf_raw.get("endpoint", "")),
        sandbox=bool(sf_raw.get("sandbox", False)),
        services=toggles,
        local_fallback=fallback,
        pii=pii_cfg,
        secrets=secrets_cfg,
    )


def _apply_env_overrides(block: SFConfigBlock) -> None:
    """Apply SPANFORGE_* env var overrides to ``block`` in-place (CFG-006)."""
    if val := os.environ.get("SPANFORGE_ENDPOINT"):
        block.endpoint = val
    if val := os.environ.get("SPANFORGE_PROJECT_ID"):
        block.project_id = val
    if val := os.environ.get("SPANFORGE_SANDBOX"):
        block.sandbox = val.lower() in ("1", "true", "yes")

    # PII threshold
    if val := os.environ.get("SPANFORGE_PII_THRESHOLD"):
        try:
            block.pii.threshold = float(val)
        except ValueError:
            _log.warning("SPANFORGE_PII_THRESHOLD=%r is not a valid float — ignored.", val)

    # Secrets auto-block
    if val := os.environ.get("SPANFORGE_SECRETS_AUTO_BLOCK"):
        block.secrets.auto_block = val.lower() not in ("false", "0", "no")

    # Local fallback enable/disable
    if val := os.environ.get("SPANFORGE_LOCAL_FALLBACK"):
        block.local_fallback.enabled = val.lower() not in ("false", "0", "no")

    # Fallback max_retries
    if val := os.environ.get("SPANFORGE_FALLBACK_MAX_RETRIES"):
        try:
            block.local_fallback.max_retries = int(val)
        except ValueError:
            _log.warning("SPANFORGE_FALLBACK_MAX_RETRIES=%r is not a valid int — ignored.", val)

    # Fallback timeout_ms
    if val := os.environ.get("SPANFORGE_FALLBACK_TIMEOUT_MS"):
        try:
            block.local_fallback.timeout_ms = int(val)
        except ValueError:
            _log.warning("SPANFORGE_FALLBACK_TIMEOUT_MS=%r is not a valid int — ignored.", val)


def _log_resolved_config(block: SFConfigBlock) -> None:
    """Log the resolved config at DEBUG level.  Secrets are always redacted."""
    if not _log.isEnabledFor(logging.DEBUG):
        return
    _log.debug(
        "Resolved SpanForge config: enabled=%s project_id=%r endpoint=%r "
        "api_key=*** local_fallback.enabled=%s max_retries=%d timeout_ms=%d "
        "pii.action=%r pii.threshold=%.2f secrets.auto_block=%s "
        "services=%s",
        block.enabled,
        block.project_id,
        block.endpoint or "(local-mode)",
        block.local_fallback.enabled,
        block.local_fallback.max_retries,
        block.local_fallback.timeout_ms,
        block.pii.action,
        block.pii.threshold,
        block.secrets.auto_block,
        block.services.as_dict(),
    )


# ---------------------------------------------------------------------------
# Config validation (CFG-007)
# ---------------------------------------------------------------------------


def validate_config(block: SFConfigBlock) -> list[str]:
    """Validate an :class:`SFConfigBlock` against the v6.0 schema.

    Returns a list of human-readable error strings.  An empty list means
    the config is valid.

    Args:
        block: The config block to validate.

    Returns:
        A (possibly empty) list of validation error strings.

    Example::

        errors = validate_config(my_block)
        if errors:
            for err in errors:
                print(f"  - {err}")
    """
    errors: list[str] = []

    # PII action
    if block.pii.action not in _KNOWN_PII_ACTIONS:
        errors.append(
            f"[pii] action={block.pii.action!r} is invalid; "
            f"must be one of {sorted(_KNOWN_PII_ACTIONS)}"
        )

    # PII threshold
    if not 0.0 <= block.pii.threshold <= 1.0:
        errors.append(
            f"[pii] threshold={block.pii.threshold} is out of range; must be 0.0-1.0"
        )

    # PII entity types
    errors.extend(
        f"[pii] entity_types contains unknown type {et!r}; "
        f"supported types: {sorted(_KNOWN_PII_ENTITY_TYPES)}"
        for et in block.pii.entity_types
        if et not in _KNOWN_PII_ENTITY_TYPES
    )

    # Secrets confidence
    if not 0.0 <= block.secrets.confidence <= 1.0:
        errors.append(
            f"[secrets] confidence={block.secrets.confidence} is out of range; must be 0.0-1.0"
        )

    # Fallback retries / timeout
    if block.local_fallback.max_retries < 0:
        errors.append(
            f"[spanforge.local_fallback] max_retries={block.local_fallback.max_retries} "
            "must be >= 0"
        )
    if block.local_fallback.timeout_ms < 0:
        errors.append(
            f"[spanforge.local_fallback] timeout_ms={block.local_fallback.timeout_ms} "
            "must be >= 0"
        )

    return errors


def validate_config_strict(block: SFConfigBlock) -> None:
    """Like :func:`validate_config` but raises on any errors.

    Raises:
        :exc:`~spanforge.sdk._exceptions.SFConfigValidationError`: If any
            validation errors are found.
    """
    errors = validate_config(block)
    if errors:
        raise SFConfigValidationError(errors)
