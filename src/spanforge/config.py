"""spanforge.config — Global configuration singleton and ``configure()`` entry point.

The configuration layer is intentionally simple: a single mutable dataclass
backed by a module-level ``threading.Lock`` for safe concurrent mutation.
Environment variables are read once at import time; subsequent calls to
:func:`configure` override individual fields.

Environment variable mapping
-----------------------------
+-----------------------------+-----------------------+
| Env var                     | Config field          |
+=============================+=======================+
| ``SPANFORGE_EXPORTER``       | ``exporter``          |
| ``SPANFORGE_ENDPOINT``       | ``endpoint``          |
| ``SPANFORGE_ORG_ID``         | ``org_id``            |
| ``SPANFORGE_SERVICE_NAME``   | ``service_name``      |
| ``SPANFORGE_ENV``            | ``env``               |
| ``SPANFORGE_SERVICE_VERSION``| ``service_version``   |
| ``SPANFORGE_SIGNING_KEY``    | ``signing_key``       |
| ``SPANFORGE_SAMPLE_RATE``    | ``sample_rate``       |
+-----------------------------+-----------------------+

Usage::

    from spanforge import configure
    configure(exporter="jsonl", service_name="my-agent", endpoint="./events.jsonl")

    from spanforge.config import get_config
    cfg = get_config()
    print(cfg.service_name)   # "my-agent"
"""

from __future__ import annotations

import contextlib
import os
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from spanforge.event import Event

__all__ = ["SpanForgeConfig", "configure", "get_config", "interpolate_env"]

# ---------------------------------------------------------------------------
# Configuration dataclass
# ---------------------------------------------------------------------------

_VALID_EXPORTERS = frozenset(
    {
        "console",
        "jsonl",
        "otlp",
        "webhook",
        "datadog",
        "grafana_loki",
        "otel_bridge",
        "otel_passthrough",
    }
)

# ---------------------------------------------------------------------------
# Config presets
# ---------------------------------------------------------------------------

_PRESETS: dict[str, dict[str, Any]] = {
    "development": {
        "exporter": "console",
        "sample_rate": 1.0,
        "enable_trace_store": True,
        "trace_store_size": 500,
        "on_export_error": "warn",
        "allow_private_endpoints": True,
        "env": "development",
        "flush_interval_seconds": 1.0,
    },
    "testing": {
        "exporter": "console",
        "sample_rate": 1.0,
        "enable_trace_store": True,
        "trace_store_size": 1000,
        "on_export_error": "raise",
        "allow_private_endpoints": True,
        "env": "testing",
        "flush_interval_seconds": 0.1,
    },
    "staging": {
        "exporter": "console",
        "sample_rate": 0.5,
        "enable_trace_store": True,
        "trace_store_size": 200,
        "on_export_error": "warn",
        "always_sample_errors": True,
        "env": "staging",
    },
    "production": {
        "exporter": "otlp",
        "sample_rate": 0.1,
        "enable_trace_store": False,
        "on_export_error": "drop",
        "always_sample_errors": True,
        "batch_size": 512,
        "flush_interval_seconds": 5.0,
        "max_queue_size": 10_000,
        "env": "production",
    },
    "otel_passthrough": {
        "exporter": "otel_bridge",
        "sample_rate": 1.0,
        "enable_trace_store": True,
        "on_export_error": "warn",
        "compliance_sampling": True,
        "env": "production",
    },
}


@dataclass
class SpanForgeConfig:
    """Mutable global configuration for the SpanForge SDK.

    All fields have safe defaults so zero-configuration usage works
    out-of-the-box (``exporter="console"`` prints to stdout).

    Attributes:
        exporter:        Backend to use:  ``"console"`` | ``"jsonl"`` | ``"otlp"``
                         | ``"webhook"`` | ``"datadog"`` | ``"grafana_loki"``.
        endpoint:        Exporter-specific destination
                         (file path for JSONL, URL for OTLP/webhook/Datadog/Loki).
        org_id:          Organisation identifier; included on all emitted events.
        service_name:    Human-readable service name (used in ``source`` field).
                         Must start with a letter and contain only
                         ``[a-zA-Z0-9._-]``.  Defaults to ``"unknown-service"``.
        env:             Deployment environment tag (e.g. ``"production"``).
        service_version: SemVer string for the emitting service.
                         Defaults to ``"0.0.0"``.
        signing_key:     Base64-encoded HMAC-SHA256 key for audit-chain signing.
                         ``None`` disables signing.
        redaction_policy: :class:`~spanforge.redact.RedactionPolicy` instance or
                          ``None`` to disable PII redaction.
        on_export_error: Policy when an exporter or emission error occurs.
                         One of ``"warn"`` (emit to ``stderr``, default),
                         ``"raise"`` (re-raise the exception into caller code),
                         or ``"drop"`` (silently discard).
        include_raw_tool_io: Opt-in flag to include raw tool arguments
                             (``arguments_raw``) and results (``result_raw``)
                             in serialised :class:`~spanforge.namespaces.trace.ToolCall`
                             payloads.  Defaults to ``False`` to prevent
                             accidental PII leakage.  Set programmatically;
                             no corresponding environment variable is provided.
        sample_rate:         Fraction of traces to emit (0.0-1.0 inclusive).
                             Sampling is deterministic per ``trace_id`` so
                             all spans of a trace are sampled together.
                             Defaults to ``1.0`` (emit everything).  Set via
                             ``SPANFORGE_SAMPLE_RATE`` env var.
        always_sample_errors: When ``True`` (the default), spans/traces with
                             ``status="error"`` or ``status="timeout"`` are
                             always emitted regardless of *sample_rate*.
        trace_filters:       List of callables ``(Event) -> bool``.  An event
                             is emitted only when **all** filters return
                             ``True``.  Applied after probabilistic sampling.
                             Not configurable via environment variable.
        enable_trace_store:  When ``True``, every dispatched event is also
                             written to the in-process
                             :class:`~spanforge._store.TraceStore` ring buffer so
                             it can be queried via :func:`~spanforge.get_trace`
                             etc.  Defaults to ``False``.  Set via
                             ``SPANFORGE_ENABLE_TRACE_STORE=1``.
        trace_store_size:    Maximum number of distinct traces the ring buffer
                             retains.  Oldest trace is evicted when full.
                             Default: 100.
        export_max_retries:  Number of retry attempts on transient export failures
                             before the ``on_export_error`` policy is applied.
                             Retries use exponential back-off (0.5 s, 1 s, 2 s …).
                             Default: 3.
        auto_emit_cost:      When ``True``, automatically emit a
                             ``llm.cost.token.recorded`` event whenever a span
                             closes with a non-``None`` ``cost`` attribute.
                             Defaults to ``False``.
        budget_usd_per_run:  When set, a budget alert is fired on the global
                             :class:`~spanforge.cost.CostTracker` when any single
                             agent run accumulates costs exceeding this value.
                             ``None`` disables per-run budget checks.
        budget_usd_per_day:  Rolling 24-hour USD budget cap on the global tracker.
                             ``None`` disables the daily budget check.
    """

    exporter: str = "console"
    endpoint: str | None = None
    org_id: str | None = None
    service_name: str = "unknown-service"
    env: str = "production"
    service_version: str = "0.0.0"
    signing_key: str | None = field(default=None, repr=False)
    redaction_policy: Any = None  # RedactionPolicy | None — avoids circular import
    on_export_error: str = "warn"  # "warn" | "raise" | "drop"
    include_raw_tool_io: bool = (
        False  # opt-in to store raw tool I/O (ToolCall.arguments_raw / result_raw)
    )
    sample_rate: float = 1.0  # 0.0-1.0; fraction of traces to emit
    always_sample_errors: bool = True  # emit error/timeout spans regardless of sample_rate
    trace_filters: list[Callable[[Event], bool]] = field(default_factory=list)
    enable_trace_store: bool = False  # opt-in in-process trace store
    trace_store_size: int = 100  # ring buffer capacity (number of traces)
    export_max_retries: int = 3  # retry count for transient export failures
    # SSRF protection: set to True to allow private/loopback endpoints (local dev only)
    allow_private_endpoints: bool = False  # SPANFORGE_ALLOW_PRIVATE_ENDPOINTS=true
    # Tool 2 — Cost Calculation Engine
    auto_emit_cost: bool = False  # auto-emit llm.cost.token.recorded on span close
    budget_usd_per_run: float | None = None  # per-run budget cap (USD)
    budget_usd_per_day: float | None = None  # rolling 24-hour budget cap (USD)
    # ---------------------------------------------------------------------------
    # New fields (P0 + P1 + P2 additions)
    # ---------------------------------------------------------------------------
    # Async batch export pipeline
    batch_size: int = 512  # max events per batch
    flush_interval_seconds: float = 5.0  # max seconds between flushes
    max_queue_size: int = 10_000  # bounded in-memory queue depth
    # Error callback (invoked on every export error, regardless of on_export_error policy)
    export_error_callback: Callable[[Exception], None] | None = field(default=None, repr=False)
    # Span processor pipeline
    span_processors: list[Any] = field(default_factory=list)  # list[SpanProcessor]
    # Custom sampler (overrides sample_rate when set)
    sampler: Any = field(default=None, repr=False)  # Sampler | None
    # Session / user tracking defaults
    default_session_id: str | None = None
    default_user_id: str | None = None
    # Maximum span events held per Span (deque maxlen); 0 means unlimited
    max_span_events: int = 1000
    # ---------------------------------------------------------------------------
    # Alerting
    # ---------------------------------------------------------------------------
    # alert_config:   AlertConfig data class (loaded from SPANFORGE_ALERT_* env vars).
    #                 When set, build_manager() is called lazily the first time an
    #                 alert fires.  Ignored when alert_manager is provided directly.
    # alert_manager:  Pre-built AlertManager instance.  Takes precedence over
    #                 alert_config.  Inject directly for full control.
    alert_config: Any = field(default=None, repr=False)  # AlertConfig | None
    alert_manager: Any = field(default=None, repr=False)  # AlertManager | None
    # ---------------------------------------------------------------------------
    # v1.0 — Compliance layer additions
    # ---------------------------------------------------------------------------
    # SF-14: Data residency & no-egress controls
    no_egress: bool = False  # block all network exporters
    egress_allowlist: frozenset[str] = field(default_factory=frozenset)  # URL prefixes
    # SF-16: Compliance-aware sampling
    compliance_sampling: bool = True  # always-record compliance events when sample_rate < 1.0
    # GA-01: Signing key security
    signing_key_expires_at: str | None = None  # ISO-8601 date
    # GA-01-D: Context-based key derivation for multi-env isolation
    signing_key_context: str | None = None  # e.g. "production", "staging"
    # GA-04: Multi-tenant key isolation
    require_org_id: bool = False  # raise SigningError if event.org_id is None
    # SF-11-C: Dual-stream export — multiple simultaneous exporters
    exporters: list[str] = field(default_factory=list)  # e.g. ['otel_passthrough', 'jsonl']
    # ---------------------------------------------------------------------------
    # v2.0 — T.R.U.S.T. Framework additions
    # ---------------------------------------------------------------------------
    # Consent boundary enforcement
    consent_enforcement: bool = False  # enable runtime consent checks
    # Human-in-the-loop (HITL) review queue
    hitl_enabled: bool = False  # activate HITL queue
    hitl_confidence_threshold: float = 0.7  # auto-queue below this confidence
    hitl_sla_seconds: int = 3600  # SLA timeout for pending reviews
    # Model registry
    model_registry_path: str | None = None  # JSON persistence path (optional)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_config: SpanForgeConfig = SpanForgeConfig()
_config_lock: threading.Lock = threading.Lock()


def _load_from_env() -> None:
    """Read environment variables and overlay them onto *_config*."""
    env_map = {
        "SPANFORGE_EXPORTER": "exporter",
        "SPANFORGE_ENDPOINT": "endpoint",
        "SPANFORGE_ORG_ID": "org_id",
        "SPANFORGE_SERVICE_NAME": "service_name",
        "SPANFORGE_ENV": "env",
        "SPANFORGE_SERVICE_VERSION": "service_version",
        "SPANFORGE_SIGNING_KEY": "signing_key",
        "SPANFORGE_ON_EXPORT_ERROR": "on_export_error",
    }
    for env_var, field_name in env_map.items():
        value = os.environ.get(env_var)
        if value is not None:
            setattr(_config, field_name, value)
    # Numeric env vars need explicit conversion.
    raw_rate = os.environ.get("SPANFORGE_SAMPLE_RATE")
    if raw_rate is not None:
        try:
            rate = float(raw_rate)
        except ValueError:
            rate = 1.0
        _config.sample_rate = max(0.0, min(1.0, rate))
    # Boolean env var: SPANFORGE_ENABLE_TRACE_STORE=1 / true / yes enables the store.
    raw_store = os.environ.get("SPANFORGE_ENABLE_TRACE_STORE")
    if raw_store is not None:
        _config.enable_trace_store = raw_store.strip().lower() in ("1", "true", "yes")
    # SSRF override: SPANFORGE_ALLOW_PRIVATE_ENDPOINTS=true allows private IPs (dev only).
    raw_priv = os.environ.get("SPANFORGE_ALLOW_PRIVATE_ENDPOINTS")
    if raw_priv is not None:
        _config.allow_private_endpoints = raw_priv.strip().lower() in ("1", "true", "yes")
    # v1.0 — No-egress mode
    raw_no_egress = os.environ.get("SPANFORGE_NO_EGRESS")
    if raw_no_egress is not None:
        _config.no_egress = raw_no_egress.strip().lower() in ("1", "true", "yes")
    # v1.0 — Egress allowlist (comma-separated URLs)
    raw_allowlist = os.environ.get("SPANFORGE_EGRESS_ALLOWLIST")
    if raw_allowlist is not None:
        _config.egress_allowlist = frozenset(
            u.strip() for u in raw_allowlist.split(",") if u.strip()
        )
    # v1.0 — Compliance sampling
    raw_comp_samp = os.environ.get("SPANFORGE_COMPLIANCE_SAMPLING")
    if raw_comp_samp is not None:
        _config.compliance_sampling = raw_comp_samp.strip().lower() not in ("0", "false", "no")
    # v1.0 — Signing key expiry
    raw_key_expiry = os.environ.get("SPANFORGE_SIGNING_KEY_EXPIRES_AT")
    if raw_key_expiry is not None:
        _config.signing_key_expires_at = raw_key_expiry.strip()
    # v1.0 — Signing key context (GA-01-D)
    raw_key_ctx = os.environ.get("SPANFORGE_SIGNING_KEY_CONTEXT")
    if raw_key_ctx is not None:
        _config.signing_key_context = raw_key_ctx.strip() or None
    # v1.0 — Require org_id
    raw_req_org = os.environ.get("SPANFORGE_REQUIRE_ORG_ID")
    if raw_req_org is not None:
        _config.require_org_id = raw_req_org.strip().lower() in ("1", "true", "yes")
    # v2.0 — T.R.U.S.T. Framework env vars
    raw_consent = os.environ.get("SPANFORGE_CONSENT_ENFORCEMENT")
    if raw_consent is not None:
        _config.consent_enforcement = raw_consent.strip().lower() in ("1", "true", "yes")
    raw_hitl = os.environ.get("SPANFORGE_HITL_ENABLED")
    if raw_hitl is not None:
        _config.hitl_enabled = raw_hitl.strip().lower() in ("1", "true", "yes")
    raw_hitl_thresh = os.environ.get("SPANFORGE_HITL_CONFIDENCE_THRESHOLD")
    if raw_hitl_thresh is not None:
        with contextlib.suppress(ValueError):
            _config.hitl_confidence_threshold = max(0.0, min(1.0, float(raw_hitl_thresh)))
    raw_hitl_sla = os.environ.get("SPANFORGE_HITL_SLA_SECONDS")
    if raw_hitl_sla is not None:
        with contextlib.suppress(ValueError):
            _config.hitl_sla_seconds = max(1, int(raw_hitl_sla))
    raw_registry_path = os.environ.get("SPANFORGE_MODEL_REGISTRY_PATH")
    if raw_registry_path is not None:
        _config.model_registry_path = raw_registry_path.strip() or None


# Apply env vars immediately at import time.
_load_from_env()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_config() -> SpanForgeConfig:
    """Return the active :class:`SpanForgeConfig` singleton.

    The returned object is the *live* singleton — modifications to it will
    affect all subsequent tracer operations.  Prefer :func:`configure` for
    intentional mutations.
    """
    return _config


def configure(**kwargs: Any) -> None:
    """Mutate the global :class:`SpanForgeConfig` singleton.

    Accepts the same keyword arguments as :class:`SpanForgeConfig` field names.
    Unknown keys raise :exc:`ValueError` immediately.  Calling ``configure()``
    with no arguments is a no-op (safe for idempotent setup scripts).

    Passing ``preset="<name>"`` applies a set of sensible defaults for the
    environment **before** applying any other kwargs.  Available presets:
    ``"development"``, ``"testing"``, ``"staging"``, ``"production"``.

    Args:
        **kwargs: One or more :class:`SpanForgeConfig` field names and their
                  new values. ``preset`` is a special keyword handled here.

    Raises:
        ValueError: If an unknown configuration key or preset name is passed.

    Examples::

        configure(preset="production", exporter="otlp", endpoint="http://collector:4318")
        configure(preset="development")
        configure(exporter="jsonl", endpoint="./events.jsonl")
    """
    if not kwargs:
        return
    with _config_lock:
        # Handle mode shortcut (SF-11-B): configure(mode='otel_passthrough')
        mode = kwargs.pop("mode", None)
        if mode is not None:
            if mode == "otel_passthrough":
                kwargs.setdefault("preset", "otel_passthrough")
            else:
                raise ValueError(
                    f"Unknown spanforge mode {mode!r}. Valid modes: 'otel_passthrough'"
                )

        # Handle preset first so explicit kwargs override preset defaults.
        preset_name = kwargs.pop("preset", None)
        if preset_name is not None:
            if preset_name not in _PRESETS:
                valid_presets = sorted(_PRESETS.keys())
                raise ValueError(
                    f"Unknown spanforge preset {preset_name!r}. Valid presets: {valid_presets}"
                )
            for key, value in _PRESETS[preset_name].items():
                setattr(_config, key, value)

        for key, value in kwargs.items():
            if not hasattr(_config, key):
                valid = sorted(vars(_config).keys())
                raise ValueError(
                    f"Unknown spanforge configuration key {key!r}. Valid keys: {valid}"
                )
            # Validate numeric range fields.
            if key == "batch_size":
                if not isinstance(value, int) or value < 1:
                    raise ValueError("batch_size must be a positive integer >= 1")
            elif key == "flush_interval_seconds":
                if not isinstance(value, (int, float)) or value <= 0:
                    raise ValueError("flush_interval_seconds must be a positive number > 0")
            elif key == "max_queue_size":
                if not isinstance(value, int) or value < 1:
                    raise ValueError("max_queue_size must be a positive integer >= 1")
            elif key == "sample_rate":
                if not isinstance(value, (int, float)) or not (0.0 <= value <= 1.0):
                    raise ValueError("sample_rate must be a float in [0.0, 1.0]")
            setattr(_config, key, value)
        # Auto-wire ComplianceSampler when compliance_sampling is enabled
        # and a sub-1.0 sample_rate is set but no explicit sampler provided.
        if _config.compliance_sampling and _config.sample_rate < 1.0 and _config.sampler is None:
            from spanforge.sampling import ComplianceSampler

            _config.sampler = ComplianceSampler(base_rate=_config.sample_rate)
        # GA-01-A: Validate signing key strength when a key is configured.
        if _config.signing_key:
            import logging as _logging

            from spanforge.signing import validate_key_strength

            _key_warnings = validate_key_strength(_config.signing_key)
            if _key_warnings:
                _log = _logging.getLogger("spanforge.config")
                for _w in _key_warnings:
                    _log.warning("signing key: %s", _w)
        # Invalidate the cached exporter in the stream so the next emit
        # picks up the new configuration.  Import here to avoid circular
        # import at module load time.
        try:
            from spanforge import _stream

            _stream._reset_exporter()
        except (ImportError, AttributeError):
            # _stream not yet loaded (e.g. during package init) — safe to skip.
            pass


# ---------------------------------------------------------------------------
# interpolate_env — recursive ${VAR} / ${VAR:default} substitution
# ---------------------------------------------------------------------------

import re as _re

_ENV_VAR_RE = _re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::([^}]*))?\}")


def interpolate_env(data: Any) -> Any:
    """Recursively replace ``${VAR}`` and ``${VAR:default}`` patterns in *data*.

    Walks *data* depth-first and performs environment-variable interpolation
    on every string value:

    * ``${FOO}`` — replaced with ``os.environ["FOO"]``; left as-is if the
      variable is not set and no default is provided.
    * ``${FOO:bar}`` — replaced with ``os.environ["FOO"]`` when set, or
      ``"bar"`` when the variable is not set.

    Non-string leaves (numbers, booleans, ``None``) are returned unchanged.
    Dicts and lists are recursed into.

    Args:
        data:  A Python value of any type.  Typically the parsed contents of
               a YAML or JSON configuration file.

    Returns:
        A deep copy of *data* with all interpolatable strings substituted.

    Example::

        import os
        from spanforge.config import interpolate_env

        os.environ["MODEL"] = "gpt-4o"
        result = interpolate_env({
            "model": "${MODEL}",
            "endpoint": "${ENDPOINT:https://api.openai.com/v1}",
        })
        # {"model": "gpt-4o", "endpoint": "https://api.openai.com/v1"}
    """
    if isinstance(data, str):
        return _ENV_VAR_RE.sub(_replace_env_var, data)
    if isinstance(data, dict):
        return {k: interpolate_env(v) for k, v in data.items()}
    if isinstance(data, list):
        return [interpolate_env(item) for item in data]
    return data


def _replace_env_var(match: _re.Match[str]) -> str:  # type: ignore[type-arg]
    """Regex substitution callback for :func:`interpolate_env`."""
    var_name, default = match.group(1), match.group(2)
    env_val = os.environ.get(var_name)
    if env_val is not None:
        return env_val
    if default is not None:
        return default
    return match.group(0)  # leave unresolved when no default
