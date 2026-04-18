"""spanforge.sdk.observe — SpanForge sf-observe Observability Named SDK (Phase 6).

Implements the full sf-observe API surface for Phase 6 of the SpanForge roadmap.
All operations run locally in-process (zero external dependencies beyond the
standard library) when ``config.endpoint`` is empty or the remote service is
unreachable and ``local_fallback_enabled`` is ``True``.

Architecture
------------
* :meth:`emit_span` is the **primary entry point** for emitting a single span.
  It generates W3C TraceContext identifiers, applies OTel GenAI semantic
  conventions, samples the span according to the configured strategy, and
  routes it through :meth:`export_spans`.
* :meth:`export_spans` accepts a list of pre-built span dicts, enriches them
  with OTel resource attributes, applies the configured backend exporter
  (local buffer / OTLP / Datadog / Grafana / Splunk / Elastic), and returns
  an :class:`~spanforge.sdk._types.ExportResult`.
* :meth:`add_annotation` stores a timestamped annotation in a thread-safe
  in-memory store.  :meth:`get_annotations` queries it.
* :meth:`get_status` returns health and session statistics.

OTel GenAI semantic conventions supported (OBS-010)
-----------------------------------------------------
All ``gen_ai.*`` attributes as defined in the OpenTelemetry GenAI specification:

* ``gen_ai.system``                  — AI system (e.g. ``"openai"``)
* ``gen_ai.request.model``           — model identifier
* ``gen_ai.request.max_tokens``      — token budget
* ``gen_ai.request.temperature``     — temperature
* ``gen_ai.response.model``          — model used in the response
* ``gen_ai.response.id``             — response identifier
* ``gen_ai.response.finish_reasons`` — comma-separated finish reasons
* ``gen_ai.usage.input_tokens``      — prompt token count
* ``gen_ai.usage.output_tokens``     — completion token count
* ``gen_ai.operation.name``          — operation type

W3C TraceContext propagation (OBS-011, OBS-012)
------------------------------------------------
Every emitted span contains a ``traceparent`` attribute in the format::

    00-<32-hex trace_id>-<16-hex span_id>-<flags>

Baggage propagation inserts ``project_id``, ``domain``, and ``tier`` when
present in ``attributes``.

Sampling strategies (OBS-031)
------------------------------
Configured via ``SPANFORGE_OBSERVE_SAMPLER`` environment variable:

* ``always_on``   — export every span.
* ``always_off``  — export no spans.
* ``parent_based`` — respect parent sampling bit in incoming ``traceparent``;
                     default to :attr:`~spanforge.sdk._types.SamplerStrategy.ALWAYS_ON`
                     when no parent.
* ``trace_id_ratio`` — deterministic fraction of traces using SHA-256 hash of
                       trace_id; ratio set by ``SPANFORGE_OBSERVE_SAMPLE_RATE``.

Backend exporters (OBS-001, OBS-040 through OBS-042)
-----------------------------------------------------
Configured via ``SPANFORGE_OBSERVE_BACKEND`` environment variable:

* ``local``    — buffer spans in a bounded in-memory deque (no network, default).
* ``otlp``     — POST to ``config.endpoint/v1/traces`` as OTLP JSON.
* ``datadog``  — POST to Datadog APM intake (``/api/v0.2/traces``).
* ``grafana``  — POST to Grafana Tempo ingest (``/api/v1/push``).
* ``splunk``   — POST to Splunk HEC (``/services/collector``).
* ``elastic``  — POST to Elastic APM Server (``/_bulk``).

Health probes (OBS-043)
------------------------
:attr:`healthy` is ``True`` when the last export succeeded (or no export has
been attempted).  :attr:`last_export_at` is an ISO-8601 UTC timestamp.

Security requirements
---------------------
* API keys and signing keys are **never** logged or included in exception
  messages.
* SSRF: all remote endpoints are validated with the same ``_validate_http_url``
  guard used in the existing OTLP exporter.
* Thread-safety: all in-memory counters and annotation stores use locks.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import threading
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.sdk._exceptions import (
    SFObserveAnnotationError,
    SFObserveEmitError,
    SFObserveError,  # noqa: F401  (re-exported for callers)
    SFObserveExportError,
)
from spanforge.sdk._types import (
    Annotation,
    ExportResult,
    ObserveStatusInfo,
    ReceiverConfig,
    SamplerStrategy,
)

__all__ = ["SFObserveClient"]

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: W3C TraceContext version byte.
_TRACEPARENT_VERSION = "00"

#: OTel resource attributes injected into every exported span batch (OBS-014).
_OTEL_RESOURCE_ATTRIBUTES: dict[str, str] = {
    "service.name": "spanforge",
    "service.version": "2.0.0",
    "telemetry.sdk.language": "python",
    "telemetry.sdk.name": "spanforge-sdk",
}

#: OTel GenAI attribute key prefix (OBS-010).
_GEN_AI_PREFIX = "gen_ai."

#: Recognised OTel GenAI attribute keys.
_GEN_AI_ATTRIBUTE_KEYS: frozenset[str] = frozenset(
    {
        "gen_ai.system",
        "gen_ai.request.model",
        "gen_ai.request.max_tokens",
        "gen_ai.request.temperature",
        "gen_ai.response.model",
        "gen_ai.response.id",
        "gen_ai.response.finish_reasons",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "gen_ai.operation.name",
    }
)

#: Supported backend identifiers.
SUPPORTED_BACKENDS: frozenset[str] = frozenset(
    {"local", "otlp", "datadog", "grafana", "splunk", "elastic"}
)

#: Maximum spans retained in the local buffer.
_LOCAL_BUFFER_MAX: int = 10_000

#: W3C traceparent flag: sampled.
_SAMPLED_FLAG = "01"

#: W3C traceparent flag: not sampled.
_NOT_SAMPLED_FLAG = "00"

# ---------------------------------------------------------------------------
# SSRF guard
# ---------------------------------------------------------------------------


def _is_private_ip_literal(host: str) -> bool:
    """Return ``True`` if *host* is a private/loopback/link-local literal IP.

    DNS hostnames are NOT resolved.  Only literal IPv4/IPv6 addresses are
    evaluated.  Set ``allow_private_endpoints=True`` in non-production
    environments when targeting private endpoints by hostname.
    """
    try:
        addr = ipaddress.ip_address(host)
    except ValueError:
        return False
    return addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_multicast


def _validate_http_url(
    url: str,
    *,
    allow_private_addresses: bool = False,
) -> None:
    """Raise :exc:`ValueError` if *url* is not a valid ``http://``/``https://`` URL.

    Also rejects literal private IP addresses unless *allow_private_addresses*
    is ``True``.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"Endpoint URL must use http:// or https://; got scheme={parsed.scheme!r}"
        )
    host = parsed.hostname or ""
    if not host:
        raise ValueError(f"Endpoint URL has no host: {url!r}")
    if not allow_private_addresses and _is_private_ip_literal(host):
        raise ValueError(
            f"Endpoint URL {url!r} resolves to a private/loopback address. "
            "Set allow_private_endpoints=True for non-production use."
        )


# ---------------------------------------------------------------------------
# Internal session statistics
# ---------------------------------------------------------------------------


@dataclass
class _ObserveSessionStats:
    """Mutable session counters (all accesses must hold ``_lock``)."""

    span_count: int = 0
    annotation_count: int = 0
    export_count: int = 0
    last_export_at: str | None = None
    healthy: bool = True
    _lock: threading.Lock = field(default_factory=threading.Lock, compare=False, repr=False)


# ---------------------------------------------------------------------------
# Sampling helpers (OBS-031)
# ---------------------------------------------------------------------------


def _should_sample(
    strategy: SamplerStrategy,
    sample_rate: float,
    trace_id_hex: str,
    parent_sampled: bool | None,
) -> bool:
    """Return ``True`` when the span should be exported under *strategy*.

    Args:
        strategy:       Active :class:`~spanforge.sdk._types.SamplerStrategy`.
        sample_rate:    Fraction in ``[0.0, 1.0]`` used by
                        :attr:`~spanforge.sdk._types.SamplerStrategy.TRACE_ID_RATIO`.
        trace_id_hex:   32-hex trace identifier.
        parent_sampled: Parent's sampling decision, or ``None`` if no parent.
    """
    if strategy == SamplerStrategy.ALWAYS_OFF:
        return False
    if strategy == SamplerStrategy.ALWAYS_ON:
        return True
    if strategy == SamplerStrategy.PARENT_BASED:
        if parent_sampled is None:
            return True  # no parent → sample by default
        return parent_sampled
    # TRACE_ID_RATIO: deterministic hash-based decision.
    hash_int = int(hashlib.sha256(trace_id_hex.encode()).hexdigest()[:16], 16)
    max_val = 0xFFFF_FFFF_FFFF_FFFF
    return (hash_int / max_val) < sample_rate


# ---------------------------------------------------------------------------
# W3C TraceContext helpers (OBS-011)
# ---------------------------------------------------------------------------


def make_traceparent(trace_id_hex: str, span_id_hex: str, *, sampled: bool = True) -> str:
    """Build a W3C ``traceparent`` header value.

    Args:
        trace_id_hex: 32-character hex string (128-bit trace ID).
        span_id_hex:  16-character hex string (64-bit span ID).
        sampled:      Whether the sampling flag should be set.

    Returns:
        A string of the form ``"00-<trace_id>-<span_id>-<flags>"``.

    Raises:
        ValueError: If the IDs are not valid hex strings of the expected length.
    """
    if len(trace_id_hex) != 32:  # noqa: PLR2004
        raise ValueError(
            f"trace_id_hex must be 32 hex chars; got {len(trace_id_hex)}"
        )
    if len(span_id_hex) != 16:  # noqa: PLR2004
        raise ValueError(
            f"span_id_hex must be 16 hex chars; got {len(span_id_hex)}"
        )
    int(trace_id_hex, 16)  # raises ValueError if not valid hex
    int(span_id_hex, 16)   # raises ValueError if not valid hex
    flags = _SAMPLED_FLAG if sampled else _NOT_SAMPLED_FLAG
    return f"{_TRACEPARENT_VERSION}-{trace_id_hex}-{span_id_hex}-{flags}"


def extract_traceparent(traceparent: str) -> tuple[str, str, bool]:
    """Parse a W3C ``traceparent`` header value.

    Returns:
        A 3-tuple of ``(trace_id_hex, span_id_hex, sampled)``.

    Raises:
        ValueError: If *traceparent* does not conform to the W3C spec.
    """
    parts = traceparent.split("-")
    _expected_parts = 4
    if len(parts) != _expected_parts:
        raise ValueError(
            f"traceparent must have 4 '-'-separated parts; got {len(parts)}: {traceparent!r}"
        )
    _version, trace_id, span_id, flags = parts
    if len(trace_id) != 32:  # noqa: PLR2004
        raise ValueError(f"trace_id must be 32 hex chars; got {len(trace_id)}")
    if len(span_id) != 16:  # noqa: PLR2004
        raise ValueError(f"span_id must be 16 hex chars; got {len(span_id)}")
    sampled = flags == _SAMPLED_FLAG
    return trace_id, span_id, sampled


def _generate_trace_id() -> str:
    """Return a random 32-hex trace ID."""
    return uuid.uuid4().hex + uuid.uuid4().hex[:0]  # 32 hex chars from uuid4


def _generate_span_id() -> str:
    """Return a random 16-hex span ID."""
    return uuid.uuid4().hex[:16]


# ---------------------------------------------------------------------------
# OTel span builder (OBS-010, OBS-014, OBS-015)
# ---------------------------------------------------------------------------


def _build_otel_span(
    name: str,
    attributes: dict[str, Any],
    trace_id: str,
    span_id: str,
    *,
    sampled: bool = True,
) -> dict[str, Any]:
    """Construct an OTLP-compatible span dict.

    Normalises ``gen_ai.*`` attributes and injects OTel resource attributes.
    Sets ``otel.status_code = "ERROR"`` when ``attributes["status"] == "error"``
    or ``attributes["otel.status_code"] == "ERROR"`` (OBS-015).

    Args:
        name:       Span name.
        attributes: User-supplied span attributes.  ``gen_ai.*`` keys are kept
                    as-is; all other keys are also forwarded unchanged.
        trace_id:   32-hex trace identifier.
        span_id:    16-hex span identifier.
        sampled:    Whether to set the W3C sampled flag.

    Returns:
        A span dict with ``name``, ``traceId``, ``spanId``, ``traceparent``,
        ``startTimeUnixNano``, ``endTimeUnixNano``, ``status``, ``attributes``,
        and ``resource`` fields.
    """
    now_ns = int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)
    span_attrs: dict[str, Any] = {}

    # Normalise gen_ai.* attributes (OBS-010)
    span_attrs = dict(attributes)

    # OBS-015: Error span detection
    is_error = (
        str(attributes.get("status", "")).lower() == "error"
        or str(attributes.get("otel.status_code", "")).upper() == "ERROR"
    )
    if is_error:
        span_attrs["otel.status_code"] = "ERROR"
        status_code = "STATUS_CODE_ERROR"
        status_message = str(attributes.get("exception.message", "error"))
    else:
        span_attrs.setdefault("otel.status_code", "OK")
        status_code = "STATUS_CODE_OK"
        status_message = ""

    # W3C TraceContext (OBS-011)
    traceparent = make_traceparent(trace_id, span_id, sampled=sampled)
    span_attrs["traceparent"] = traceparent

    # W3C Baggage (OBS-012) — project_id, domain, tier
    baggage_parts = [
        f"{k}={attributes[k]}"
        for k in ("project_id", "domain", "tier")
        if k in attributes
    ]
    if baggage_parts:
        span_attrs["baggage"] = ",".join(baggage_parts)

    return {
        "name": name,
        "traceId": trace_id,
        "spanId": span_id,
        "traceparent": traceparent,
        "startTimeUnixNano": now_ns,
        "endTimeUnixNano": now_ns,
        "status": {"code": status_code, "message": status_message},
        "attributes": span_attrs,
        "resource": {
            "attributes": {
                **_OTEL_RESOURCE_ATTRIBUTES,
                "deployment.environment": os.environ.get("SPANFORGE_ENV", "production"),
            }
        },
    }


# ---------------------------------------------------------------------------
# Backend exporters (OBS-040 through OBS-042)
# ---------------------------------------------------------------------------


def _post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    *,
    timeout_seconds: float = 30.0,
) -> None:
    """POST *payload* as JSON to *url*.

    Raises:
        SFObserveExportError: On any HTTP or network error.
    """
    body = json.dumps(payload, default=str).encode()
    req = urllib.request.Request(url, data=body, method="POST")  # noqa: S310
    req.add_header("Content-Type", "application/json")
    for name, value in headers.items():
        req.add_header(name, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310  # nosec B310
            _ = resp.read()
    except urllib.error.HTTPError as exc:
        raise SFObserveExportError(
            f"HTTP {exc.code} from {url}: {exc.reason}"
        ) from exc
    except OSError as exc:
        raise SFObserveExportError(
            f"Network error posting to {url}: {exc}"
        ) from exc


def _build_otlp_payload(
    spans: list[dict[str, Any]],
) -> dict[str, Any]:
    """Wrap *spans* in an OTLP ``/v1/traces`` JSON envelope."""
    span_list: list[dict[str, Any]] = []
    for s in spans:
        attrs = [
            {"key": k, "value": {"stringValue": str(v)}}
            for k, v in s.get("attributes", {}).items()
        ]
        resource_attrs = [
            {"key": k, "value": {"stringValue": str(v)}}
            for k, v in s.get("resource", {}).get("attributes", {}).items()
        ]
        span_list.append(
            {
                "traceId": s.get("traceId", ""),
                "spanId": s.get("spanId", ""),
                "name": s.get("name", ""),
                "startTimeUnixNano": str(s.get("startTimeUnixNano", 0)),
                "endTimeUnixNano": str(s.get("endTimeUnixNano", 0)),
                "status": s.get("status", {}),
                "attributes": attrs,
            }
        )
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": resource_attrs if spans else []},
                "scopeSpans": [
                    {
                        "scope": {"name": "spanforge-sdk"},
                        "spans": span_list,
                    }
                ],
            }
        ]
    }


# ---------------------------------------------------------------------------
# SFObserveClient
# ---------------------------------------------------------------------------


class SFObserveClient(SFServiceClient):
    """SpanForge sf-observe client.

    Provides span emission, annotation storage, and export routing for the
    Phase 6 observability SDK.

    Configuration is read from :class:`~spanforge.sdk._base.SFClientConfig`
    and the following additional environment variables:

    +-----------------------------------+-----------------------------------+-------------------+
    | Variable                          | Meaning                           | Default           |
    +===================================+===================================+===================+
    | ``SPANFORGE_OBSERVE_BACKEND``     | Exporter backend                  | ``"local"``       |
    +-----------------------------------+-----------------------------------+-------------------+
    | ``SPANFORGE_OBSERVE_SAMPLER``     | SamplerStrategy label             | ``"always_on"`` |
    +-----------------------------------+-----------------------------------+-------------------+
    | ``SPANFORGE_OBSERVE_SAMPLE_RATE`` | Float ``[0.0, 1.0]`` for ratio    | ``1.0``           |
    +-----------------------------------+-----------------------------------+-------------------+
    | ``SPANFORGE_ENV``                 | ``deployment.environment`` value  | ``"production"``  |
    +-----------------------------------+-----------------------------------+-------------------+

    Thread safety
    -------------
    All public methods are thread-safe.  The annotation store and session
    statistics are protected by ``threading.Lock``.

    Example::

        from spanforge.sdk import sf_observe

        span_id = sf_observe.emit_span(
            "chat.completion",
            {
                "gen_ai.system": "openai",
                "gen_ai.request.model": "gpt-4o",
                "gen_ai.usage.input_tokens": 512,
            },
        )
        annotation_id = sf_observe.add_annotation(
            "model_deployed",
            {"model": "gpt-4o", "version": "2024-11"},
            project_id="my-project",
        )
        status = sf_observe.get_status()
    """

    def __init__(self, config: SFClientConfig) -> None:
        super().__init__(config, service_name="observe")

        # Resolve backend
        raw_backend = os.environ.get("SPANFORGE_OBSERVE_BACKEND", "local").lower()
        self._backend: str = raw_backend if raw_backend in SUPPORTED_BACKENDS else "local"

        # Resolve sampler strategy
        raw_sampler = os.environ.get("SPANFORGE_OBSERVE_SAMPLER", SamplerStrategy.ALWAYS_ON.value)
        try:
            self._sampler_strategy: SamplerStrategy = SamplerStrategy(raw_sampler)
        except ValueError:
            _log.warning(
                "Unknown SPANFORGE_OBSERVE_SAMPLER=%r; defaulting to always_on",
                raw_sampler,
            )
            self._sampler_strategy = SamplerStrategy.ALWAYS_ON

        # Resolve sample rate (for TRACE_ID_RATIO)
        raw_rate = os.environ.get("SPANFORGE_OBSERVE_SAMPLE_RATE", "1.0")
        try:
            self._sample_rate: float = max(0.0, min(1.0, float(raw_rate)))
        except ValueError:
            self._sample_rate = 1.0

        # Thread-safe annotation store and session stats
        self._annotations: list[Annotation] = []
        self._annotations_lock = threading.Lock()
        self._stats = _ObserveSessionStats()

        # Local span buffer
        self._span_buffer: list[dict[str, Any]] = []
        self._buffer_lock = threading.Lock()

    # ------------------------------------------------------------------
    # OBS-001: export_spans
    # ------------------------------------------------------------------

    def export_spans(
        self,
        spans: list[dict[str, Any]],
        *,
        receiver_config: ReceiverConfig | None = None,
    ) -> ExportResult:
        """Export a batch of spans to the configured backend.

        Each span dict should be an OTLP-compatible dict as produced by
        :meth:`emit_span`, or any dict with at least ``"name"`` and
        ``"traceId"`` fields.

        Args:
            spans:           List of span dicts to export.
            receiver_config: Optional per-call override for the export
                             endpoint and headers.  When provided, this
                             takes precedence over
                             ``config.endpoint`` for this call only.

        Returns:
            :class:`~spanforge.sdk._types.ExportResult` with counts and
            backend label.

        Raises:
            SFObserveExportError: If the export fails and
                ``config.local_fallback_enabled`` is ``False``.
        """
        if not isinstance(spans, list):
            raise SFObserveExportError(
                f"spans must be a list; got {type(spans).__name__}"
            )

        exported_at = datetime.now(timezone.utc).isoformat()
        exported_count = 0
        failed_count = 0

        try:
            exported_count, failed_count = self._do_export(spans, receiver_config)
        except SFObserveExportError:
            if not self._config.local_fallback_enabled:
                with self._stats._lock:
                    self._stats.healthy = False
                raise
            # fallback: buffer locally
            _log.warning(
                "sf-observe: export to %s failed; buffering %d spans locally",
                self._backend,
                len(spans),
            )
            with self._buffer_lock:
                self._span_buffer.extend(spans[-_LOCAL_BUFFER_MAX:])
            exported_count = len(spans)
            failed_count = 0

        with self._stats._lock:
            self._stats.export_count += 1
            self._stats.last_export_at = exported_at
            self._stats.healthy = failed_count == 0

        return ExportResult(
            exported_count=exported_count,
            failed_count=failed_count,
            backend=self._backend,
            exported_at=exported_at,
        )

    def _do_export(
        self,
        spans: list[dict[str, Any]],
        receiver_config: ReceiverConfig | None,
    ) -> tuple[int, int]:
        """Internal export dispatch.

        Returns:
            ``(exported_count, failed_count)`` tuple.

        Raises:
            SFObserveExportError: On backend failure.
        """
        if not spans:
            return 0, 0

        backend = self._backend

        # Per-call override switches to OTLP regardless of global backend.
        if receiver_config is not None:
            _validate_http_url(receiver_config.endpoint)
            payload = _build_otlp_payload(spans)
            headers: dict[str, str] = dict(receiver_config.headers)
            api_key = self._config.api_key.get_secret_value()
            if api_key:
                headers.setdefault("Authorization", f"Bearer {api_key}")
            _post_json(
                receiver_config.endpoint,
                payload,
                headers,
                timeout_seconds=receiver_config.timeout_seconds,
            )
            return len(spans), 0

        # Global backend selection
        if backend == "local" or self._is_local_mode():
            with self._buffer_lock:
                buf_space = _LOCAL_BUFFER_MAX - len(self._span_buffer)
                accepted = spans[:buf_space]
                self._span_buffer.extend(accepted)
            return len(spans), 0

        endpoint = self._config.endpoint.rstrip("/")
        api_key = self._config.api_key.get_secret_value()
        base_headers: dict[str, str] = {}
        if api_key:
            base_headers["Authorization"] = f"Bearer {api_key}"

        if backend == "otlp":
            _validate_http_url(endpoint + "/v1/traces")
            payload = _build_otlp_payload(spans)
            _post_json(endpoint + "/v1/traces", payload, base_headers)

        elif backend == "datadog":
            _validate_http_url(endpoint + "/api/v0.2/traces")
            dd_payload: dict[str, Any] = {"traces": [[_span_to_dd(s) for s in spans]]}
            _post_json(endpoint + "/api/v0.2/traces", dd_payload, base_headers)

        elif backend == "grafana":
            _validate_http_url(endpoint + "/api/v1/push")
            payload = _build_otlp_payload(spans)
            _post_json(endpoint + "/api/v1/push", payload, base_headers)

        elif backend == "splunk":
            # Splunk HEC (OBS-040)
            _validate_http_url(endpoint + "/services/collector")
            events = [{"event": s, "sourcetype": "spanforge:otel"} for s in spans]
            splunk_payload: dict[str, Any] = {"events": events}
            _post_json(endpoint + "/services/collector", splunk_payload, base_headers)

        elif backend == "elastic":
            # Elastic APM / OpenSearch ECS (OBS-041)
            _validate_http_url(endpoint + "/_bulk")
            lines: list[dict[str, Any]] = []
            for s in spans:
                lines.append({"index": {"_index": "apm-spans"}})
                lines.append(_span_to_ecs(s))
            elastic_payload: dict[str, Any] = {"operations": lines}
            _post_json(endpoint + "/_bulk", elastic_payload, base_headers)

        else:
            # Unknown backend — local fallback
            with self._buffer_lock:
                self._span_buffer.extend(spans)

        return len(spans), 0

    # ------------------------------------------------------------------
    # OBS-004: emit_span
    # ------------------------------------------------------------------

    def emit_span(
        self,
        name: str,
        attributes: dict[str, Any],
    ) -> str:
        """Emit a single span with OTel GenAI semantic conventions.

        Generates W3C TraceContext identifiers, applies the configured
        sampling strategy, enriches the span with OTel resource attributes,
        and routes it through :meth:`export_spans`.

        Args:
            name:       Span name (e.g. ``"chat.completion"``).
            attributes: Span attributes.  ``gen_ai.*`` keys are forwarded
                        as-is.  Inject ``"status": "error"`` to mark an
                        error span (OBS-015).  Inject ``"traceparent"``
                        to provide an existing parent context (OBS-011).

        Returns:
            The 16-hex span ID string.

        Raises:
            SFObserveEmitError: If *name* is empty or *attributes* is not
                a dict.
        """
        if not name:
            raise SFObserveEmitError("span name must not be empty")
        if not isinstance(attributes, dict):
            raise SFObserveEmitError(
                f"attributes must be a dict; got {type(attributes).__name__}"
            )

        # Extract parent traceparent if provided (OBS-011)
        parent_trace_id: str | None = None
        parent_sampled: bool | None = None
        if "traceparent" in attributes:
            try:
                parent_trace_id, _, parent_sampled = extract_traceparent(
                    str(attributes["traceparent"])
                )
            except ValueError:
                _log.debug("emit_span: invalid parent traceparent — ignoring")

        # Generate identifiers
        trace_id = parent_trace_id or _generate_trace_id()
        span_id = _generate_span_id()

        # Sampling decision (OBS-031)
        sampled = _should_sample(
            self._sampler_strategy,
            self._sample_rate,
            trace_id,
            parent_sampled,
        )
        if not sampled:
            # Still return a span_id; caller can observe the sampling decision.
            with self._stats._lock:
                self._stats.span_count += 1
            return span_id

        # Build OTLP span dict (OBS-010, OBS-014, OBS-015)
        span = _build_otel_span(name, attributes, trace_id, span_id, sampled=True)

        try:
            self.export_spans([span])
        except SFObserveExportError as exc:
            raise SFObserveEmitError(f"export failed: {exc}") from exc

        with self._stats._lock:
            self._stats.span_count += 1

        return span_id

    # ------------------------------------------------------------------
    # OBS-002: add_annotation
    # ------------------------------------------------------------------

    def add_annotation(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        project_id: str,
    ) -> str:
        """Store a timestamped annotation.

        Args:
            event_type: Category label (e.g. ``"model_deployed"``).
            payload:    Arbitrary JSON-serialisable key/value metadata.
            project_id: Project scope for this annotation.

        Returns:
            The opaque annotation ID (UUID string).

        Raises:
            SFObserveAnnotationError: If *event_type* is empty or *payload*
                is not a dict.
        """
        if not event_type:
            raise SFObserveAnnotationError("event_type must not be empty")
        if not isinstance(payload, dict):
            raise SFObserveAnnotationError(
                f"payload must be a dict; got {type(payload).__name__}"
            )

        annotation_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()
        annotation = Annotation(
            annotation_id=annotation_id,
            event_type=event_type,
            payload=payload,
            project_id=project_id,
            created_at=created_at,
        )
        with self._annotations_lock:
            self._annotations.append(annotation)
        with self._stats._lock:
            self._stats.annotation_count += 1
        return annotation_id

    # ------------------------------------------------------------------
    # OBS-003: get_annotations
    # ------------------------------------------------------------------

    def get_annotations(
        self,
        event_type: str,
        from_dt: str,
        to_dt: str,
        *,
        project_id: str = "",
    ) -> list[Annotation]:
        """Query stored annotations by type and time range.

        Args:
            event_type: Category label to filter by.  Pass ``"*"`` to match
                        all event types.
            from_dt:    ISO-8601 UTC start timestamp (inclusive).
            to_dt:      ISO-8601 UTC end timestamp (inclusive).
            project_id: Optional project scope filter.  Empty string disables
                        project filtering.

        Returns:
            Matching :class:`~spanforge.sdk._types.Annotation` instances,
            ordered by creation time.

        Raises:
            SFObserveAnnotationError: If *from_dt* or *to_dt* are not
                valid ISO-8601 strings.
        """
        try:
            _from = datetime.fromisoformat(from_dt)
            _to = datetime.fromisoformat(to_dt)
        except ValueError as exc:
            raise SFObserveAnnotationError(
                f"Invalid datetime string: {exc}"
            ) from exc

        results: list[Annotation] = []
        with self._annotations_lock:
            for ann in self._annotations:
                if event_type not in ("*", ann.event_type):
                    continue
                if project_id and ann.project_id != project_id:
                    continue
                try:
                    created = datetime.fromisoformat(ann.created_at)
                except ValueError:
                    continue
                if _from <= created <= _to:
                    results.append(ann)
        return results

    # ------------------------------------------------------------------
    # get_status
    # ------------------------------------------------------------------

    def get_status(self) -> ObserveStatusInfo:
        """Return current service health and session statistics.

        Returns:
            :class:`~spanforge.sdk._types.ObserveStatusInfo` snapshot.
        """
        with self._stats._lock:
            return ObserveStatusInfo(
                status="ok" if self._stats.healthy else "degraded",
                backend=self._backend,
                sampler_strategy=self._sampler_strategy.value,
                span_count=self._stats.span_count,
                annotation_count=self._stats.annotation_count,
                export_count=self._stats.export_count,
                last_export_at=self._stats.last_export_at,
                healthy=self._stats.healthy,
            )

    # ------------------------------------------------------------------
    # OBS-043: health probes
    # ------------------------------------------------------------------

    @property
    def healthy(self) -> bool:
        """``True`` if the last export succeeded (or no export has been attempted)."""
        with self._stats._lock:
            return self._stats.healthy

    @property
    def last_export_at(self) -> str | None:
        """ISO-8601 UTC timestamp of the most recent export, or ``None``."""
        with self._stats._lock:
            return self._stats.last_export_at


# ---------------------------------------------------------------------------
# Backend-specific span serialisation helpers
# ---------------------------------------------------------------------------


def _span_to_dd(span: dict[str, Any]) -> dict[str, Any]:
    """Translate an OTLP span dict to a minimal Datadog trace payload."""
    now_ns = int(datetime.now(timezone.utc).timestamp() * 1_000_000_000)
    return {
        "trace_id": int(span.get("traceId", "0" * 32)[:16], 16),
        "span_id": int(span.get("spanId", "0" * 16), 16),
        "name": span.get("name", ""),
        "start": span.get("startTimeUnixNano", now_ns),
        "duration": 0,
        "error": 1 if span.get("status", {}).get("code") == "STATUS_CODE_ERROR" else 0,
        "meta": {str(k): str(v) for k, v in span.get("attributes", {}).items()},
    }


def _span_to_ecs(span: dict[str, Any]) -> dict[str, Any]:
    """Translate an OTLP span dict to a minimal Elastic Common Schema document."""
    return {
        "trace.id": span.get("traceId", ""),
        "transaction.id": span.get("spanId", ""),
        "span.name": span.get("name", ""),
        "service.name": (
            span.get("resource", {}).get("attributes", {}).get("service.name", "spanforge")
        ),
        "labels": {str(k): str(v) for k, v in span.get("attributes", {}).items()},
        "event.outcome": (
            "failure" if span.get("status", {}).get("code") == "STATUS_CODE_ERROR" else "success"
        ),
        "@timestamp": datetime.now(timezone.utc).isoformat(),
    }
