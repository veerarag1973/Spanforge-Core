"""spanforge._stream — Internal synchronous event emitter.

This module is the bridge between the tracer's context managers and the
configured export backend.  It is intentionally private — user code should
interact with the tracer, not this module directly.

Flow
----
::

    Span.__exit__
      → _stream.emit_span(span)
        → build SpanPayload
        → build Event(event_type=TRACE_SPAN_COMPLETED, payload=span_payload.to_dict())
        → _active_exporter().export(event)   ← sync

The active exporter is resolved lazily on first use and cached until the
config changes (call :func:`_reset_exporter` after ``configure()``).
"""

from __future__ import annotations

import atexit
import logging
import re
import secrets
import threading
import time
import warnings

from spanforge.config import SpanForgeConfig, get_config
from spanforge.event import Event, Tags
from spanforge.exceptions import ExportError
from spanforge.types import RFC_SPANFORGE_NAMESPACES, EventType

__all__: list[str] = ["flush", "shutdown"]  # public helpers re-exported from spanforge root

_export_logger = logging.getLogger("spanforge.export")

# Thread-safe export error counter (useful for metrics / health checks).
_export_error_count: int = 0
_export_error_lock = threading.Lock()

# Ephemeral per-process signing key used to auto-sign RFC-0001 SPANFORGE
# namespace events when no org-level signing_key is configured.
# Generated once at import time with 256 bits of entropy.
_EPHEMERAL_SIGNING_KEY: str = secrets.token_hex(32)

# ---------------------------------------------------------------------------
# Source field sanitisation
# ---------------------------------------------------------------------------

_SOURCE_START_RE = re.compile(r"^[a-zA-Z]")
_SOURCE_BODY_RE = re.compile(r"[^a-zA-Z0-9._\-]")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+")


def _build_source(service_name: str, service_version: str) -> str:
    """Return a valid ``name@version`` source string.

    Sanitise ``service_name`` so it always starts with a letter and contains
    only ``[a-zA-Z0-9._-]``.  Ensures ``service_version`` looks like a semver.
    """
    name = _SOURCE_BODY_RE.sub("-", service_name)
    if not _SOURCE_START_RE.match(name):
        name = "s" + name  # prepend 's' if name starts with a digit/special char
    if not _VERSION_RE.match(service_version):
        service_version = "0.0.0"
    return f"{name}@{service_version}"


# ---------------------------------------------------------------------------
# Exporter resolution
# ---------------------------------------------------------------------------

_exporter_lock = threading.Lock()
_cached_exporter: object | None = None  # SyncExporter protocol instance

# ---------------------------------------------------------------------------
# Signing chain state
# ---------------------------------------------------------------------------

_sign_lock = threading.Lock()
_prev_signed_event: Event | None = None  # last event in the HMAC chain


def _handle_export_error(exc: Exception) -> None:
    """Apply the configured ``on_export_error`` policy for *exc*.

    Policies:

    - ``"drop"``  — silently discard the error (opt-in to original behaviour).
    - ``"warn"``  — emit a :mod:`warnings` ``UserWarning`` (default).
    - ``"raise"`` — re-raise the exception into caller code.

    Regardless of policy, the optional ``export_error_callback`` is always
    invoked first so callers can implement custom alerting or metrics.
    """
    global _export_error_count  # noqa: PLW0603
    with _export_error_lock:
        _export_error_count += 1

    _export_logger.warning(
        "spanforge export error (%s): %s",
        type(exc).__name__,
        exc,
    )

    try:
        cfg = get_config()
    except Exception:  # NOSONAR
        cfg = None  # type: ignore[assignment]

    # Invoke the optional error callback (never raises).
    if cfg is not None and cfg.export_error_callback is not None:
        try:
            cfg.export_error_callback(exc)
        except Exception as cb_exc:  # NOSONAR
            _export_logger.debug("export_error_callback raised: %s", cb_exc)

    policy = cfg.on_export_error if cfg is not None else "warn"

    if policy == "raise":
        raise exc
    if policy == "warn":
        warnings.warn(
            f"spanforge export error ({type(exc).__name__}): {exc}",
            stacklevel=3,
        )
    # "drop": discard silently


def _reset_exporter() -> None:
    """Invalidate the cached exporter and reset the HMAC signing chain."""
    global _cached_exporter, _prev_signed_event  # noqa: PLW0603
    with _exporter_lock:
        if _cached_exporter is not None:
            # Flush + close any open file handles before discarding the exporter.
            try:
                if hasattr(_cached_exporter, "close"):
                    _cached_exporter.close()  # type: ignore[union-attr]
            except Exception as exc:  # NOSONAR
                _handle_export_error(exc)
        _cached_exporter = None
    with _sign_lock:
        _prev_signed_event = None
    # Recreate the trace store with the (possibly updated) size from config.
    try:
        from spanforge._store import _reset_store  # noqa: PLC0415
        from spanforge.config import get_config as _gc  # noqa: PLC0415
        _reset_store(_gc().trace_store_size)
    except Exception:  # NOSONAR
        pass  # never let store reset failures affect the exporter reset


def _active_exporter() -> object:
    """Return the cached exporter, instantiating it from config if necessary."""
    global _cached_exporter  # noqa: PLW0603
    if _cached_exporter is not None:
        return _cached_exporter
    with _exporter_lock:
        if _cached_exporter is not None:
            return _cached_exporter
        _cached_exporter = _build_exporter()
    return _cached_exporter


def _build_exporter() -> object:
    """Instantiate the correct exporter based on the current config."""
    cfg = get_config()

    # SF-11-C: Dual-stream export support — if cfg.exporters has multiple
    # entries, build a _FanOutExporter that dispatches to all of them.
    if cfg.exporters and len(cfg.exporters) > 1:
        children = []
        for name in cfg.exporters:
            child = _build_single_exporter(name.lower(), cfg)
            if child is not None:
                children.append((name, child))
        if children:
            return _FanOutExporter(children)

    name = (cfg.exporter or "console").lower()
    return _build_single_exporter(name, cfg) or _build_single_exporter("console", cfg)


def _build_single_exporter(name: str, cfg: "SpanForgeConfig") -> object | None:
    """Instantiate a single exporter by *name*."""
    if name in ("otel_passthrough", "otel_bridge"):
        try:
            from spanforge.export.otel_bridge import OTelBridgeExporter  # noqa: PLC0415
            return OTelBridgeExporter()
        except ImportError:
            raise ImportError(
                "opentelemetry-sdk is required for otel_passthrough mode.  "
                "Install it with:  pip install 'spanforge[otel]'"
            ) from None

    if name == "jsonl":
        from spanforge.exporters.jsonl import SyncJSONLExporter  # noqa: PLC0415
        path = cfg.endpoint or "spanforge_events.jsonl"
        return SyncJSONLExporter(path)

    if name == "console":
        from spanforge.exporters.console import SyncConsoleExporter  # noqa: PLC0415
        return SyncConsoleExporter()

    # Named exporters that are only supported via EventStream (async path).
    _supported_via_eventstream = frozenset({"otlp", "webhook", "datadog", "grafana_loki"})
    if name in _supported_via_eventstream:
        warnings.warn(
            f"spanforge: exporter={name!r} is not supported by the synchronous tracer "
            f"(configure / start_trace).  Use spanforge.stream.EventStream with the "
            f"spanforge.export.{name} module instead.  Falling back to console output.",
            UserWarning,
            stacklevel=5,
        )

    # Default fallback: use the console exporter.
    from spanforge.exporters.console import SyncConsoleExporter  # noqa: PLC0415
    return SyncConsoleExporter()


class _FanOutExporter:
    """Dispatches events to multiple exporters independently (SF-11-C).

    Each child exporter receives the same event.  Failures in one exporter
    do not affect the others (circuit-breaker per exporter).
    """

    __slots__ = ("_children", "_failed")

    def __init__(self, children: list[tuple[str, object]]) -> None:
        self._children = children
        self._failed: set[str] = set()

    def export(self, event: "Event") -> None:
        for name, child in self._children:
            if name in self._failed:
                continue
            try:
                child.export(event)  # type: ignore[attr-defined]
            except Exception as exc:
                _export_logger.warning(
                    "spanforge fan-out exporter %r failed: %s — disabling",
                    name, exc,
                )
                self._failed.add(name)

    def close(self) -> None:
        for _name, child in self._children:
            if hasattr(child, "close"):
                try:
                    child.close()  # type: ignore[attr-defined]
                except Exception:  # NOSONAR
                    pass


# ---------------------------------------------------------------------------
# Event construction helpers
# ---------------------------------------------------------------------------


def _build_event(
    event_type: EventType,
    payload_dict: dict,
    span_id: str | None = None,
    trace_id: str | None = None,
    parent_span_id: str | None = None,
) -> Event:
    """Construct a fully-populated :class:`~spanforge.event.Event` envelope."""
    cfg = get_config()
    source = _build_source(cfg.service_name, cfg.service_version)

    kwargs: dict = {
        "event_type": event_type,
        "source": source,
        "payload": payload_dict,
    }
    if cfg.org_id:
        kwargs["org_id"] = cfg.org_id
    if span_id:
        kwargs["span_id"] = span_id
    if trace_id:
        kwargs["trace_id"] = trace_id
    if parent_span_id:
        kwargs["parent_span_id"] = parent_span_id

    tags_kwargs: dict = {"env": cfg.env}
    kwargs["tags"] = Tags(**tags_kwargs)

    return Event(**kwargs)


# ---------------------------------------------------------------------------
# Public emit functions (called by _span.py context managers)
# ---------------------------------------------------------------------------


def emit_span(span: object) -> None:
    """Build a ``SpanPayload`` event from *span* and export it.

    Also notifies the active :class:`~spanforge._trace.Trace` collector (if any)
    so it can accumulate spans for :meth:`~spanforge._trace.Trace.to_json`.

    Args:
        span: A :class:`~spanforge._span.Span` instance.
    """
    # Import here to avoid circular import at module load time.
    from spanforge._span import Span, _run_stack_var  # noqa: PLC0415

    assert isinstance(span, Span)
    payload = span.to_span_payload()
    event_type = (
        EventType.TRACE_SPAN_FAILED if span.status == "error"
        else EventType.TRACE_SPAN_COMPLETED
    )
    event = _build_event(
        event_type=event_type,
        payload_dict=payload.to_dict(),
        span_id=span.span_id,
        trace_id=span.trace_id,
        parent_span_id=span.parent_span_id,
    )
    _dispatch(event)

    # Notify the Trace collector (set by start_trace()) so it can accumulate spans.
    run_tuple = _run_stack_var.get()
    if run_tuple:
        collector = getattr(run_tuple[-1], "_trace_collector", None)
        if collector is not None:
            try:
                collector._record_span(span)
            except Exception:  # NOSONAR
                pass  # never let collection errors affect the main emit path


def emit_agent_step(step: object) -> None:
    """Build an ``AgentStepPayload`` event from *step* and export it."""
    from spanforge._span import AgentStepContext  # noqa: PLC0415

    assert isinstance(step, AgentStepContext)
    payload = step.to_agent_step_payload()
    event = _build_event(
        event_type=EventType.TRACE_AGENT_STEP,
        payload_dict=payload.to_dict(),
        span_id=step.span_id,
        trace_id=step.trace_id,
        parent_span_id=step.parent_span_id,
    )
    _dispatch(event)


def emit_agent_run(run: object) -> None:
    """Build an ``AgentRunPayload`` event from *run* and export it."""
    from spanforge._span import AgentRunContext  # noqa: PLC0415

    assert isinstance(run, AgentRunContext)
    payload = run.to_agent_run_payload()
    event = _build_event(
        event_type=EventType.TRACE_AGENT_COMPLETED,
        payload_dict=payload.to_dict(),
        trace_id=run.trace_id,
        span_id=run.root_span_id,
    )
    _dispatch(event)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def _is_error_or_timeout(event: "Event") -> bool:
    """Return True if the event payload status is 'error' or 'timeout'."""
    return event.payload.get("status", "") in ("error", "timeout")


def _passes_sample_rate(event: "Event", sample_rate: float) -> bool:
    """Deterministic per-trace sampling; returns True if the event should be kept."""
    trace_id: str = event.payload.get("trace_id", "")
    if trace_id:
        token = trace_id[:8]
        try:
            bucket = int(token, 16)
        except ValueError:
            bucket = 0
        return bucket / 0xFFFF_FFFF <= sample_rate
    # No trace_id — use cryptographically secure random fallback
    rand_token = secrets.token_hex(4)  # 8 hex chars = 32-bit random value
    bucket = int(rand_token, 16)
    return bucket / 0xFFFF_FFFF <= sample_rate


def _should_emit(event: "Event", cfg: "SpanForgeConfig") -> bool:
    """Return ``True`` if *event* should be exported under the current config.

    The sampling decision is made in this order:

    1. **Error pass-through** — when ``always_sample_errors=True`` (the
       default), spans with ``status="error"`` or ``status="timeout"`` are
       always emitted regardless of *sample_rate*.
    2. **Probabilistic sampling** — the decision is deterministic per
       ``trace_id``: all spans of a given trace are sampled or dropped
       together.  Uses the first 8 hex digits of the trace_id as a
       32-bit hash so the decision is reproducible.
    3. **Custom filters** — all ``trace_filters`` callables must return
       ``True`` for the event to be emitted.

    Args:
        event: The candidate event.
        cfg:   Live :class:`~spanforge.config.SpanForgeConfig` snapshot.

    Returns:
        ``True`` to emit, ``False`` to drop.
    """
    # Fast path: no sampling configured, no filters — always emit.
    if cfg.sample_rate >= 1.0 and not cfg.trace_filters:
        return True

    # Step 1: always emit errors when configured.
    if cfg.always_sample_errors and _is_error_or_timeout(event):
        return True

    # Step 2: probabilistic sampling keyed on trace_id.
    if cfg.sample_rate < 1.0 and not _passes_sample_rate(event, cfg.sample_rate):
        return False

    # Step 3: custom filters (all must pass).
    for f in cfg.trace_filters:
        try:
            if not f(event):
                return False
        except Exception:  # NOSONAR
            pass  # a failing filter never silently drops the event

    return True


def _dispatch(event: Event) -> None:
    """Export *event* through the active exporter, handling errors per policy.

    Pipeline (in order):
    0. **Redaction** — apply :class:`~spanforge.redact.RedactionPolicy` when
       ``config.redaction_policy`` is set.  PII is masked first so that
       sampling decisions are never made on un-redacted data.
    1. **Sampling** — apply probabilistic sampling and custom filters; drop
       the event immediately if it should not be emitted.
    2. **Signing** — sign with HMAC-SHA256 and chain to the previous event
       when ``config.signing_key`` is set.
    3. **Export** — hand the event to the active exporter.

    On failure the error is routed through :func:`_handle_export_error` which
    applies the ``on_export_error`` policy (``"warn"`` | ``"raise"`` | ``"drop"``).
    """
    global _prev_signed_event  # noqa: PLW0603
    try:
        cfg = get_config()

        # 0. Redaction FIRST — sampling must see the redacted payload so that
        #    raw PII never influences sampling decisions or propagates further.
        if cfg.redaction_policy is not None:
            event = cfg.redaction_policy.apply(event).event

        # 1. Sampling — drop early to avoid unnecessary work.
        if not _should_emit(event, cfg):
            return

        # 2. Signing — maintain the audit chain.
        #    RFC-0001 SPANFORGE namespaces are ALWAYS signed (auto-signed with
        #    the configured key if available, or the ephemeral per-process key).
        #    Legacy llm.* namespaces are signed only when signing_key is set.
        event_ns = event.event_type.split(".")[0]
        is_rfc_ns = event_ns in RFC_SPANFORGE_NAMESPACES
        signing_key = cfg.signing_key or (
            _EPHEMERAL_SIGNING_KEY if is_rfc_ns else None
        )
        if signing_key:
            from spanforge.signing import sign  # noqa: PLC0415
            with _sign_lock:
                event = sign(
                    event,
                    org_secret=signing_key,
                    prev_event=_prev_signed_event,
                )
                _prev_signed_event = event

        # 3. Export (with retry + exponential backoff on transient ExportError only).
        exporter = _active_exporter()
        max_retries: int = cfg.export_max_retries
        for attempt in range(max_retries + 1):
            try:
                exporter.export(event)  # type: ignore[attr-defined]
                break
            except ExportError as exc:
                if attempt < max_retries:
                    _export_logger.debug(
                        "spanforge export attempt %d/%d failed (%s): %s — retrying",
                        attempt + 1,
                        max_retries + 1,
                        type(exc).__name__,
                        exc,
                    )
                    time.sleep(0.5 * (2 ** attempt))  # 0.5 s, 1 s, 2 s …
                else:
                    raise  # exhausted — let outer except call _handle_export_error once

        # 4. Trace store (opt-in ring buffer for programmatic querying).
        if cfg.enable_trace_store:
            try:
                from spanforge._store import get_store  # noqa: PLC0415
                get_store().record(event)
            except Exception as exc:
                _handle_export_error(exc)
    except Exception as exc:
        _handle_export_error(exc)


def get_export_error_count() -> int:
    """Return the total number of export errors recorded since process start.

    Useful for health checks and instrumentation::

        from spanforge._stream import get_export_error_count
        assert get_export_error_count() == 0, "export errors detected"
    """
    with _export_error_lock:
        return _export_error_count


def emit_rfc_event(
    event_type: EventType,
    payload: dict,
    span_id: str | None = None,
    trace_id: str | None = None,
    parent_span_id: str | None = None,
) -> None:
    """Emit an RFC-0001 SPANFORGE namespace event (decision, tool_call, chain, etc.).

    Events emitted through this function are guaranteed to be HMAC-signed
    regardless of whether ``config.signing_key`` is set.  When no org-level
    key is configured an ephemeral per-process key is used so the audit chain
    remains intact within the current process lifetime.

    Args:
        event_type:      An :class:`~spanforge.types.EventType` from one of the
                         10 RFC-0001 SPANFORGE namespaces.
        payload:         Plain-dict representation of the namespace payload
                         (e.g. the output of ``DecisionPayload.to_dict()``).
        span_id:         Optional W3C-format span ID (16 hex chars).
        trace_id:        Optional W3C-format trace ID (32 hex chars).
        parent_span_id:  Optional parent span ID.

    Raises:
        ValueError: If *event_type* is not in an RFC-0001 SPANFORGE namespace.
    """
    event_ns = str(event_type).split(".")[0]
    if event_ns not in RFC_SPANFORGE_NAMESPACES:
        raise ValueError(
            f"emit_rfc_event requires an RFC-0001 SPANFORGE namespace event type "
            f"(got {event_type!r}; namespace {event_ns!r} is not in "
            f"RFC_SPANFORGE_NAMESPACES)."
        )
    event = _build_event(
        event_type=event_type,
        payload_dict=payload,
        span_id=span_id,
        trace_id=trace_id,
        parent_span_id=parent_span_id,
    )
    _dispatch(event)


# ---------------------------------------------------------------------------
# Graceful shutdown and flush
# ---------------------------------------------------------------------------

_shutdown_called = False
_shutdown_lock = threading.Lock()


def flush(timeout_seconds: float = 5.0) -> bool:
    """Flush any buffered events to the configured exporter.

    For synchronous exporters (console, JSONL) this is a no-op since every
    event is dispatched immediately.  For the asynchronous batch exporter it
    drains the in-memory queue and waits up to *timeout_seconds*.

    Args:
        timeout_seconds: Maximum time to wait for the flush to complete.

    Returns:
        ``True`` if all events were flushed within the timeout, ``False``
        if the queue still had items after *timeout_seconds*.
    """
    exporter = _cached_exporter
    if exporter is None:
        return True

    # Async batch exporter exposes flush().
    flush_fn = getattr(exporter, "flush", None)
    if callable(flush_fn):
        try:
            import inspect as _inspect
            sig = _inspect.signature(flush_fn)
            if "timeout_seconds" in sig.parameters:
                return flush_fn(timeout_seconds=timeout_seconds)
            else:
                flush_fn()
                return True
        except Exception as exc:  # NOSONAR
            _export_logger.warning("spanforge flush error: %s", exc)
            return False

    # For file-backed exporters, ensure data is flushed to disk.
    ffs = getattr(exporter, "_fh", None)
    if ffs is not None:
        try:
            ffs.flush()
        except Exception:  # NOSONAR
            pass

    return True


def shutdown(timeout_seconds: float = 5.0) -> None:
    """Flush and release resources for the active exporter.

    Safe to call multiple times — subsequent calls after the first are
    no-ops.  Registered with :mod:`atexit` at module import time so it is
    always invoked on clean process exit.

    Args:
        timeout_seconds: Maximum time to wait for in-flight events to drain.
    """
    global _shutdown_called  # noqa: PLW0603
    with _shutdown_lock:
        if _shutdown_called:
            return
        _shutdown_called = True

    try:
        flush(timeout_seconds=timeout_seconds)
    except Exception:  # NOSONAR
        pass

    try:
        _reset_exporter()
    except Exception:  # NOSONAR
        pass


# Register the shutdown hook so in-flight events are always flushed on exit.
atexit.register(shutdown)
