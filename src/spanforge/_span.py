"""spanforge._span — Span, SpanContextManager, and agent context managers.

Provides the runtime tracing primitives that back ``tracer.span()``,
``tracer.agent_run()``, and ``tracer.agent_step()``.

Design notes
------------
* **Context-variable stacks** — uses :mod:`contextvars` so that context
  propagates correctly across asyncio tasks, thread-pool executors, and
  concurrent threads without manual ID management.
* **Immutable stack tuples** — each ``__enter__`` sets a *new* tuple on the
  ContextVar and saves the reset token; ``__exit__`` calls
  ``ContextVar.reset(token)`` so concurrent tasks each see their own stack
  slice and cannot bleed into each other.
* **OTel-compatible IDs** — ``span_id`` is 8 random bytes (16 hex chars),
  ``trace_id`` is 16 random bytes (32 hex chars), matching the OTel wire
  format expected by :class:`~spanforge.namespaces.trace.SpanPayload`.
* **Zero external dependencies** — stdlib only (``contextvars``, ``os``,
  ``time``, ``types``).
"""

from __future__ import annotations

import contextvars
import os
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from spanforge.namespaces.trace import (
    AgentRunPayload,
    AgentStepPayload,
    CostBreakdown,
    DecisionPoint,
    GenAIOperationName,
    GenAISystem,
    ModelInfo,
    ReasoningStep,
    SpanEvent,
    SpanKind,
    SpanPayload,
    TokenUsage,
    ToolCall,
)

if TYPE_CHECKING:
    import threading
    from types import TracebackType

__all__ = [
    "AgentRunContext",
    "AgentRunContextManager",
    "AgentStepContext",
    "AgentStepContextManager",
    "Span",
    "SpanContextManager",
    "copy_context",
    "extract_traceparent",
    "inject_traceparent",
]

# ---------------------------------------------------------------------------
# ID generation helpers
# ---------------------------------------------------------------------------


def _span_id() -> str:
    """Generate an OTel-compatible span ID: 8 random bytes → 16 lowercase hex chars."""
    return os.urandom(8).hex()


def _trace_id() -> str:
    """Generate an OTel-compatible trace ID: 16 random bytes → 32 lowercase hex chars."""
    return os.urandom(16).hex()


def _now_ns() -> int:
    """Current time as integer nanoseconds since the Unix epoch."""
    return time.time_ns()


# ---------------------------------------------------------------------------
# Context-variable stacks (asyncio-safe, thread-safe)
# ---------------------------------------------------------------------------

# Each ContextVar stores an *immutable tuple* so that asyncio tasks spawned
# inside a span inherit the parent's stack slice without mutating it.
_span_stack_var: contextvars.ContextVar[tuple[Span, ...]] = contextvars.ContextVar(
    "spanforge_span_stack", default=()
)
_run_stack_var: contextvars.ContextVar[tuple[AgentRunContext, ...]] = contextvars.ContextVar(
    "spanforge_run_stack", default=()
)


def _span_stack() -> tuple[Span, ...]:
    """Return the current context's span stack (immutable tuple)."""
    return _span_stack_var.get()


def _run_stack() -> tuple[AgentRunContext, ...]:
    """Return the current context's agent-run stack (immutable tuple)."""
    return _run_stack_var.get()


def copy_context() -> contextvars.Context:
    """Return a shallow copy of the current :mod:`contextvars` context.

    Pass this to :func:`contextvars.Context.run` when spawning threads or
    ``loop.run_in_executor`` tasks that should inherit the active span::

        ctx = spanforge.copy_context()
        loop.run_in_executor(None, ctx.run, my_blocking_fn)
    """
    return contextvars.copy_context()


# ---------------------------------------------------------------------------
# W3C Trace Context helpers (RFC-0001 §15)
# ---------------------------------------------------------------------------

_TRACEPARENT_PARTS = 4
_TRACEPARENT_VERSION = "00"


def _parse_traceparent(header: str) -> tuple[str, str] | None:
    """Parse a W3C ``traceparent`` header value.

    Format: ``{version}-{trace-id}-{parent-id}-{trace-flags}``

    Args:
        header: The raw ``traceparent`` header value (e.g. from an HTTP request).

    Returns:
        ``(trace_id, parent_span_id)`` if the header is valid, else ``None``.
    """
    parts = header.strip().split("-")
    if len(parts) != _TRACEPARENT_PARTS:
        return None
    version, trace_id, parent_id, _flags = parts
    if version != _TRACEPARENT_VERSION:
        return None
    if len(trace_id) != 32 or not all(c in "0123456789abcdef" for c in trace_id):
        return None
    if len(parent_id) != 16 or not all(c in "0123456789abcdef" for c in parent_id):
        return None
    if trace_id == "0" * 32 or parent_id == "0" * 16:
        return None  # invalid all-zeros IDs per spec
    return trace_id, parent_id


def extract_traceparent(headers: dict[str, str]) -> tuple[str, str] | None:
    """Extract ``(trace_id, parent_span_id)`` from W3C Trace Context headers.

    Looks for the ``traceparent`` key (case-insensitive) in *headers*.

    Args:
        headers: HTTP request headers dict.

    Returns:
        ``(trace_id, parent_span_id)`` if a valid ``traceparent`` header is
        present, else ``None``.

    Example::

        ctx = extract_traceparent(request.headers)
        if ctx:
            trace_id, parent_id = ctx
            with tracer.span("handle", incoming_traceparent=request.headers.get("traceparent")):
                ...
    """
    # Case-insensitive lookup — HTTP/1.1 headers are case-insensitive (RFC 7230 §3.2).
    raw = next((v for k, v in headers.items() if k.lower() == "traceparent"), "")
    return _parse_traceparent(raw) if raw else None


def inject_traceparent(span: "Span", headers: dict[str, str]) -> None:
    """Inject W3C Trace Context into *headers* for downstream propagation.

    Sets ``traceparent`` using the active trace and span IDs.

    Args:
        span:    The currently active :class:`Span`.
        headers: Mutable HTTP headers dict to inject into.

    Example::

        headers = {}
        inject_traceparent(span, headers)
        httpx.get(url, headers=headers)
    """
    span.inject(headers)


# ---------------------------------------------------------------------------
# Span helpers
# ---------------------------------------------------------------------------


def _default_span_events() -> "deque[SpanEvent]":
    """Return a deque with maxlen read from the global config (H2: configurable)."""
    try:
        from spanforge.config import get_config  # noqa: PLC0415
        maxlen = get_config().max_span_events
        return deque(maxlen=maxlen if maxlen > 0 else None)
    except Exception:  # config not yet initialised
        return deque(maxlen=1000)


# ---------------------------------------------------------------------------
# Span
# ---------------------------------------------------------------------------


@dataclass
class Span:
    """Mutable span record accumulated during a ``with tracer.span(...)`` block.

    Create via :class:`SpanContextManager` (i.e. ``tracer.span(...)``).
    Direct construction is supported for testing.

    Auto-populated fields
    ----------------------
    ``span_id``, ``trace_id``, and ``start_ns`` are assigned by
    :class:`SpanContextManager.__enter__`; do not set them manually unless
    you need custom IDs for testing.

    Attributes:
        name:            Human-readable span name.
        span_id:         16 lowercase hex chars (OTel span ID).
        trace_id:        32 lowercase hex chars (OTel trace ID).
        parent_span_id:  Parent span ID if nested; ``None`` for root spans.
        agent_run_id:    ULID of the enclosing agent run, if any.
        model:           Model name string (e.g. ``"gpt-4o"``).
        operation:       GenAI operation name (default ``"chat"``).
        attributes:      Arbitrary key-value metadata set by the user.
        start_ns:        Start time as nanoseconds since Unix epoch.
        end_ns:          End time (set on :meth:`end`).
        duration_ms:     Computed duration in milliseconds.
        status:          ``"ok"`` or ``"error"`` or ``"timeout"``.
        error:           Error message if ``status == "error"``.
        error_type:      Exception class name if ``status == "error"``.
        token_usage:     Optional token counts (set by provider integrations).
        cost:            Optional cost breakdown (set by provider integrations).
    """

    name: str
    span_id: str = field(default_factory=_span_id)
    trace_id: str = field(default_factory=_trace_id)
    parent_span_id: str | None = None
    agent_run_id: str | None = None
    model: str | None = None
    operation: str = "chat"
    attributes: dict[str, Any] = field(default_factory=dict)
    start_ns: int = field(default_factory=_now_ns)
    end_ns: int | None = None
    duration_ms: float | None = None
    status: str = "ok"
    error: str | None = None
    error_type: str | None = None
    token_usage: TokenUsage | None = None
    cost: CostBreakdown | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    events: deque[SpanEvent] = field(default_factory=_default_span_events)
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    error_category: str | None = None  # one of SpanErrorCategory literals
    session_id: str | None = None      # conversation / session identifier
    user_id: str | None = None         # end-user identifier
    traceparent: str | None = None    # incoming W3C traceparent (for propagation)
    _timeout_timer: "threading.Timer | None" = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------
    # Mutation methods (call from inside ``with tracer.span(...) as s:``)
    # ------------------------------------------------------------------

    def set_attribute(self, key: str, value: Any) -> None:  # noqa: ANN401
        """Add or update a key-value attribute on this span.

        Args:
            key:   Attribute name (non-empty string).
            value: Attribute value (any JSON-serialisable type).
        """
        if not isinstance(key, str) or not key:
            raise ValueError("set_attribute: key must be a non-empty string")
        self.attributes[key] = value

    def add_event(self, name: str, metadata: dict[str, Any] | None = None) -> None:
        """Record a named event at this point in time within the span.

        Args:
            name:     Event name (non-empty string).
            metadata: Optional key-value metadata for this event.
        """
        self.events.append(SpanEvent(name=name, metadata=metadata or {}))

    def inject(self, headers: dict[str, str]) -> None:
        """Inject W3C Trace Context headers for downstream propagation.

        Sets ``traceparent`` (and optionally ``tracestate``) on *headers* so
        that downstream services can correlate their spans with this one.

        Args:
            headers: Mutable dict-like object representing outgoing HTTP headers.
                     ``traceparent`` will be set (and ``tracestate`` cleared).

        Example::

            headers = {}
            span.inject(headers)
            requests.get(url, headers=headers)
        """
        flags = "01"  # sampled
        headers["traceparent"] = f"00-{self.trace_id}-{self.span_id}-{flags}"

    def record_error(
        self,
        exc: Exception,
        category: str | None = None,
    ) -> None:
        """Record an exception on this span, setting ``status = "error"``.

        Args:
            exc:      The exception that caused the failure.
            category: Optional error category — one of ``"agent_error"``,
                      ``"llm_error"``, ``"tool_error"``, ``"timeout_error"``,
                      ``"unknown_error"``.  When omitted, :class:`TimeoutError`
                      is automatically mapped to ``"timeout_error"``; all
                      others default to ``"unknown_error"``.
        """
        self.status = "error"
        self.error = str(exc)
        self.error_type = type(exc).__qualname__
        if category is not None:
            self.error_category = category
        elif isinstance(exc, TimeoutError):
            self.error_category = "timeout_error"
        else:
            self.error_category = "unknown_error"

    def set_token_usage(self, token_usage: TokenUsage) -> None:
        """Attach token usage data (called by provider integrations)."""
        self.token_usage = token_usage

    def set_cost(self, cost: CostBreakdown) -> None:
        """Attach cost breakdown data (called by provider integrations)."""
        self.cost = cost

    # ------------------------------------------------------------------
    # Internal lifecycle
    # ------------------------------------------------------------------

    def set_timeout_deadline(self, seconds: float) -> None:
        """Schedule this span to auto-timeout if not closed within *seconds*.

        If the span is still open when the deadline passes, its ``status``
        is set to ``"timeout"`` and ``error_category`` to ``"timeout_error"``.
        The background timer is automatically cancelled when the span closes
        normally via :meth:`end`.

        Args:
            seconds: Deadline in seconds (must be > 0).

        Raises:
            ValueError: If *seconds* is not greater than zero.
        """
        if seconds <= 0:
            raise ValueError(f"set_timeout_deadline: seconds must be > 0, got {seconds!r}")
        import threading  # noqa: PLC0415

        # Cancel any previously registered timer before installing a new one.
        # Without this guard, double-calling would orphan the first timer.
        if self._timeout_timer is not None:
            self._timeout_timer.cancel()
            self._timeout_timer = None

        def _timeout_fn() -> None:
            # Guard is evaluated on CPython under the GIL.  end_ns is set by
            # end() before cancel() is called; on CPython this sequence is
            # safe.  The double guard (end_ns + status) means a span that has
            # already errored or finished is never overwritten.
            if self.end_ns is None and self.status == "ok":
                self.status = "timeout"
                self.error = f"Span timed out after {seconds:.3f}s"
                self.error_category = "timeout_error"

        timer = threading.Timer(seconds, _timeout_fn)
        timer.daemon = True
        timer.start()
        self._timeout_timer = timer

    def end(self) -> None:
        """Finalise the span by recording the end time and computing duration."""
        if self.end_ns is None:
            self.end_ns = _now_ns()
            self.duration_ms = (self.end_ns - self.start_ns) / 1_000_000.0
            if self._timeout_timer is not None:
                self._timeout_timer.cancel()
                self._timeout_timer = None

    def to_span_payload(self) -> SpanPayload:
        """Serialise this span to a :class:`~spanforge.namespaces.trace.SpanPayload`.

        Called internally by :class:`SpanContextManager.__exit__` just before
        event emission.
        """
        end_ns = self.end_ns if self.end_ns is not None else _now_ns()
        duration_ms = (end_ns - self.start_ns) / 1_000_000.0

        # Resolve ModelInfo from the model name string.
        model_info: ModelInfo | None = None
        if self.model:
            model_info = _resolve_model_info(self.model)

        # Resolve operation enum.
        try:
            operation: GenAIOperationName | str = GenAIOperationName(self.operation)
        except ValueError:
            operation = self.operation

        return SpanPayload(
            span_id=self.span_id,
            trace_id=self.trace_id,
            span_name=self.name,
            operation=operation,
            span_kind=SpanKind.CLIENT,
            status=self.status,
            start_time_unix_nano=self.start_ns,
            end_time_unix_nano=end_ns,
            duration_ms=duration_ms,
            parent_span_id=self.parent_span_id,
            agent_run_id=self.agent_run_id,
            model=model_info,
            token_usage=self.token_usage,
            cost=self.cost,
            tool_calls=list(self.tool_calls),
            error=self.error,
            error_type=self.error_type,
            attributes=self.attributes if self.attributes else None,
            temperature=self.temperature,
            top_p=self.top_p,
            max_tokens=self.max_tokens,
            error_category=self.error_category,
            events=list(self.events),
            session_id=self.session_id,
            user_id=self.user_id,
            incoming_traceparent=self.traceparent,
        )


# ---------------------------------------------------------------------------
# SpanContextManager
# ---------------------------------------------------------------------------


class SpanContextManager:
    """Context manager returned by :meth:`~spanforge._tracer.Tracer.span`.

    Usage::

        with tracer.span("my-llm-call", model="gpt-4o") as span:
            span.set_attribute("prompt_length", 256)
            # ... call LLM ...
        # → SpanPayload event emitted on exit

    The :class:`Span` instance is bound to the ``as`` target and is also
    pushed onto the context-variable span stack so nested spans can inherit the
    ``trace_id``.
    """

    def __init__(
        self,
        name: str,
        model: str | None = None,
        operation: str = "chat",
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        attributes: dict[str, Any] | None = None,
        incoming_traceparent: str | None = None,
        session_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        self._name = name
        self._model = model
        self._operation = operation
        self._temperature = temperature
        self._top_p = top_p
        self._max_tokens = max_tokens
        self._initial_attributes = dict(attributes or {})
        self._incoming_traceparent = incoming_traceparent
        self._session_id = session_id
        self._user_id = user_id
        self._span: Span | None = None

    # ------------------------------------------------------------------
    # Context manager protocol
    # ------------------------------------------------------------------

    def __enter__(self) -> Span:
        stack = _span_stack()
        run_tuple = _run_stack()

        # Inherit trace_id and parent_span_id from the enclosing span.
        if stack:
            parent = stack[-1]
            trace_id = parent.trace_id
            parent_span_id = parent.span_id
        elif self._incoming_traceparent:
            # Extract W3C traceparent from incoming headers for distributed tracing.
            extracted = _parse_traceparent(self._incoming_traceparent)
            if extracted is not None:
                trace_id, parent_span_id = extracted
            else:
                trace_id = run_tuple[-1].trace_id if run_tuple else _trace_id()
                parent_span_id = None
        else:
            # Fall back to the enclosing run context's trace_id when available
            # so that all spans within a Trace share one trace_id.
            trace_id = run_tuple[-1].trace_id if run_tuple else _trace_id()
            parent_span_id = None

        # Inherit agent_run_id from the enclosing run context.
        agent_run_id = run_tuple[-1].agent_run_id if run_tuple else None

        # Resolve session_id and user_id from explicit arg or config defaults.
        try:
            from spanforge.config import get_config as _gc  # noqa: PLC0415
            _cfg = _gc()
            session_id = self._session_id or _cfg.default_session_id
            user_id = self._user_id or _cfg.default_user_id
        except Exception:  # NOSONAR
            session_id = self._session_id
            user_id = self._user_id

        self._span = Span(
            name=self._name,
            span_id=_span_id(),
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            agent_run_id=agent_run_id,
            model=self._model,
            operation=self._operation,
            temperature=self._temperature,
            top_p=self._top_p,
            max_tokens=self._max_tokens,
            attributes=dict(self._initial_attributes),
            start_ns=_now_ns(),
            session_id=session_id,
            user_id=user_id,
            traceparent=self._incoming_traceparent,
        )
        # Push onto an immutable tuple and save the reset token.
        self._stack_token: contextvars.Token[tuple[Span, ...]] = _span_stack_var.set(
            stack + (self._span,)
        )
        # Fire span processors on_start (errors suppressed).
        try:
            from spanforge.processor import _run_on_start  # noqa: PLC0415
            _run_on_start(self._span)
        except Exception:  # NOSONAR
            pass
        # Fire start hooks (errors suppressed — hooks must never abort user code).
        try:
            from spanforge._hooks import hooks as _hooks  # noqa: PLC0415
            _hooks._fire_start(self._span)
        except Exception:  # NOSONAR
            pass
        return self._span

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        assert self._span is not None, "SpanContextManager.__exit__ called before __enter__"

        # Record any unhandled exception on the span.
        # Exclude BaseException subclasses that are control-flow signals
        # (KeyboardInterrupt, SystemExit, GeneratorExit) — only true
        # application exceptions (Exception subclasses) are recorded.
        if exc_val is not None and isinstance(exc_val, Exception) and self._span.status == "ok":
            self._span.record_error(exc_val)

        self._span.end()

        # Restore the stack to its pre-enter state.
        _span_stack_var.reset(self._stack_token)

        # Fire span processors on_end (errors suppressed).
        try:
            from spanforge.processor import _run_on_end  # noqa: PLC0415
            _run_on_end(self._span)
        except Exception:  # NOSONAR
            pass
        # Fire end hooks before export (errors suppressed).
        try:
            from spanforge._hooks import hooks as _hooks  # noqa: PLC0415
            _hooks._fire_end(self._span)
        except Exception:  # NOSONAR
            pass

        # Emit the event.
        _s = None
        try:
            from spanforge import _stream as _s  # noqa: PLC0415
            _s.emit_span(self._span)
        except Exception as exc:
            if _s is not None:
                _s._handle_export_error(exc)

        # Auto-emit cost event when configured (Tool 2).
        if self._span.cost is not None:
            try:
                from spanforge.config import get_config as _gc  # noqa: PLC0415
                if _gc().auto_emit_cost:
                    from spanforge.cost import emit_cost_event  # noqa: PLC0415
                    emit_cost_event(self._span)
            except Exception:  # NOSONAR — cost emission must never affect user code
                pass

        # Do NOT suppress the original exception.
        return False

    # ------------------------------------------------------------------
    # Async context manager protocol (delegates to sync implementation)
    # ------------------------------------------------------------------

    async def __aenter__(self) -> Span:
        """Async entry — identical to ``__enter__``; safe for ``async with``."""
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Async exit — identical to ``__exit__``; safe for ``async with``."""
        return self.__exit__(exc_type, exc_val, exc_tb)


# ---------------------------------------------------------------------------
# Agent step context
# ---------------------------------------------------------------------------


@dataclass
class AgentStepContext:
    """Mutable record accumulated during ``with tracer.agent_step(...)``."""

    step_name: str
    agent_run_id: str
    step_index: int
    span_id: str = field(default_factory=_span_id)
    trace_id: str = field(default_factory=_trace_id)
    parent_span_id: str | None = None
    operation: str = "invoke_agent"
    start_ns: int = field(default_factory=_now_ns)
    end_ns: int | None = None
    duration_ms: float | None = None
    status: str = "ok"
    error: str | None = None
    error_type: str | None = None
    model: str | None = None
    token_usage: TokenUsage | None = None
    cost: CostBreakdown | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning_steps: list[ReasoningStep] = field(default_factory=list)
    decision_points: list[DecisionPoint] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)

    def set_attribute(self, key: str, value: Any) -> None:  # noqa: ANN401
        if not isinstance(key, str) or not key:
            raise ValueError("set_attribute: key must be a non-empty string")
        self.attributes[key] = value

    def record_error(self, exc: Exception) -> None:
        self.status = "error"
        self.error = str(exc)
        self.error_type = type(exc).__qualname__

    def end(self) -> None:
        if self.end_ns is None:
            self.end_ns = _now_ns()
            self.duration_ms = (self.end_ns - self.start_ns) / 1_000_000.0

    def to_agent_step_payload(self) -> AgentStepPayload:
        end_ns = self.end_ns if self.end_ns is not None else _now_ns()
        duration_ms = (end_ns - self.start_ns) / 1_000_000.0
        try:
            operation: GenAIOperationName | str = GenAIOperationName(self.operation)
        except ValueError:
            operation = self.operation
        return AgentStepPayload(
            agent_run_id=self.agent_run_id,
            step_index=self.step_index,
            span_id=self.span_id,
            trace_id=self.trace_id,
            operation=operation,
            tool_calls=list(self.tool_calls),
            reasoning_steps=list(self.reasoning_steps),
            decision_points=list(self.decision_points),
            status=self.status,
            start_time_unix_nano=self.start_ns,
            end_time_unix_nano=end_ns,
            duration_ms=duration_ms,
            parent_span_id=self.parent_span_id,
            model=_resolve_model_info(self.model) if self.model else None,
            token_usage=self.token_usage,
            cost=self.cost,
            error=self.error,
            error_type=self.error_type,
            step_name=self.step_name,
        )


class AgentStepContextManager:
    """Context manager returned by :meth:`~spanforge._tracer.Tracer.agent_step`."""

    def __init__(
        self,
        step_name: str,
        operation: str = "invoke_agent",
        attributes: dict[str, Any] | None = None,
    ) -> None:
        self._step_name = step_name
        self._operation = operation
        self._initial_attributes = dict(attributes or {})
        self._ctx: AgentStepContext | None = None

    def __enter__(self) -> AgentStepContext:
        run_tuple = _run_stack()
        if not run_tuple:
            raise RuntimeError(
                "tracer.agent_step() must be used inside a tracer.agent_run() context"
            )
        run = run_tuple[-1]

        # Inherit trace_id + parent from any enclosing span.
        span_tuple = _span_stack()
        if span_tuple:
            parent = span_tuple[-1]
            trace_id = parent.trace_id
            parent_span_id = parent.span_id
        else:
            trace_id = run.trace_id
            parent_span_id = None

        step_index = run.next_step_index()

        self._ctx = AgentStepContext(
            step_name=self._step_name,
            agent_run_id=run.agent_run_id,
            step_index=step_index,
            span_id=_span_id(),
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            operation=self._operation,
            start_ns=_now_ns(),
            attributes=dict(self._initial_attributes),
        )
        return self._ctx

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        assert self._ctx is not None

        if exc_val is not None and self._ctx.status == "ok":
            self._ctx.record_error(exc_val)
        self._ctx.end()

        # Register step with the parent run context.
        run_tuple = _run_stack()
        if run_tuple:
            run_tuple[-1].record_step(self._ctx)

        # Emit agent step event.
        _s = None
        try:
            from spanforge import _stream as _s  # noqa: PLC0415
            _s.emit_agent_step(self._ctx)
        except Exception as exc:
            if _s is not None:
                _s._handle_export_error(exc)

        return False

    # ------------------------------------------------------------------
    # Async context manager protocol
    # ------------------------------------------------------------------

    async def __aenter__(self) -> AgentStepContext:
        """Async entry — identical to ``__enter__``."""
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Async exit — identical to ``__exit__``."""
        return self.__exit__(exc_type, exc_val, exc_tb)


# ---------------------------------------------------------------------------
# Agent run context
# ---------------------------------------------------------------------------


@dataclass
class AgentRunContext:
    """Mutable record accumulated during ``with tracer.agent_run(...)``."""

    agent_name: str
    agent_run_id: str = field(default_factory=_span_id)  # 16 hex chars
    trace_id: str = field(default_factory=_trace_id)
    root_span_id: str = field(default_factory=_span_id)
    start_ns: int = field(default_factory=_now_ns)
    end_ns: int | None = None
    duration_ms: float | None = None
    status: str = "ok"
    error: str | None = None
    termination_reason: str | None = None
    _step_count: int = field(default=0, init=False, repr=False)
    _steps: list[AgentStepContext] = field(default_factory=list, init=False, repr=False)
    _child_run_costs: list[CostBreakdown] = field(default_factory=list, init=False, repr=False)

    def next_step_index(self) -> int:
        idx = self._step_count
        self._step_count += 1
        return idx

    def record_step(self, step: AgentStepContext) -> None:
        self._steps.append(step)

    def record_error(self, exc: Exception) -> None:
        self.status = "error"
        self.error = str(exc)

    def record_child_run_cost(self, cost: CostBreakdown) -> None:
        """Accumulate cost from a completed child agent run."""
        self._child_run_costs.append(cost)

    def end(self) -> None:
        if self.end_ns is None:
            self.end_ns = _now_ns()
            self.duration_ms = (self.end_ns - self.start_ns) / 1_000_000.0

    def to_agent_run_payload(self) -> AgentRunPayload:
        end_ns = self.end_ns if self.end_ns is not None else _now_ns()
        duration_ms = (end_ns - self.start_ns) / 1_000_000.0

        # Aggregate token usage and cost across all steps.
        total_input = 0
        total_output = 0
        total_tokens = 0
        total_in_cost = 0.0
        total_out_cost = 0.0
        total_model_calls = 0
        total_tool_calls = 0
        for step in self._steps:
            if step.token_usage:
                total_input += step.token_usage.input_tokens
                total_output += step.token_usage.output_tokens
                total_tokens += step.token_usage.total_tokens
                total_model_calls += 1
            total_tool_calls += len(step.tool_calls)
            if step.cost:
                total_in_cost += step.cost.input_cost_usd
                total_out_cost += step.cost.output_cost_usd

        # Include costs bubbled up from child agent runs.
        child_in_cost = 0.0
        child_out_cost = 0.0
        for child_cost in self._child_run_costs:
            child_in_cost += child_cost.input_cost_usd
            child_out_cost += child_cost.output_cost_usd

        total_in_cost += child_in_cost
        total_out_cost += child_out_cost

        total_token_usage = TokenUsage(
            input_tokens=total_input,
            output_tokens=total_output,
            total_tokens=total_tokens,
        )
        total_cost = CostBreakdown(
            input_cost_usd=total_in_cost,
            output_cost_usd=total_out_cost,
            total_cost_usd=total_in_cost + total_out_cost,
        )

        return AgentRunPayload(
            agent_run_id=self.agent_run_id,
            agent_name=self.agent_name,
            trace_id=self.trace_id,
            root_span_id=self.root_span_id,
            total_steps=len(self._steps),
            total_model_calls=total_model_calls,
            total_tool_calls=total_tool_calls,
            total_token_usage=total_token_usage,
            total_cost=total_cost,
            status=self.status,
            start_time_unix_nano=self.start_ns,
            end_time_unix_nano=end_ns,
            duration_ms=duration_ms,
            termination_reason=self.termination_reason,
        )


class AgentRunContextManager:
    """Context manager returned by :meth:`~spanforge._tracer.Tracer.agent_run`."""

    def __init__(self, agent_name: str) -> None:
        self._agent_name = agent_name
        self._ctx: AgentRunContext | None = None

    def __enter__(self) -> AgentRunContext:
        self._ctx = AgentRunContext(
            agent_name=self._agent_name,
            agent_run_id=_span_id(),
            trace_id=_trace_id(),
            root_span_id=_span_id(),
            start_ns=_now_ns(),
        )
        # Push onto the immutable run-stack tuple and save the reset token.
        self._run_token: contextvars.Token[tuple[AgentRunContext, ...]] = _run_stack_var.set(
            _run_stack() + (self._ctx,)
        )
        return self._ctx

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        assert self._ctx is not None

        if exc_val is not None and self._ctx.status == "ok":
            self._ctx.record_error(exc_val)
        self._ctx.end()

        # Restore the run-stack to its pre-enter state.
        _run_stack_var.reset(self._run_token)

        # Bubble this run's total cost up to the parent run (if any).
        parent_stack = _run_stack()
        if parent_stack:
            parent_run = parent_stack[-1]
            run_payload = self._ctx.to_agent_run_payload()
            parent_run.record_child_run_cost(run_payload.total_cost)

        _s = None
        try:
            from spanforge import _stream as _s  # noqa: PLC0415
            _s.emit_agent_run(self._ctx)
        except Exception as exc:
            if _s is not None:
                _s._handle_export_error(exc)

        return False

    # ------------------------------------------------------------------
    # Async context manager protocol
    # ------------------------------------------------------------------

    async def __aenter__(self) -> AgentRunContext:
        """Async entry — identical to ``__enter__``."""
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Async exit — identical to ``__exit__``."""
        return self.__exit__(exc_type, exc_val, exc_tb)


# ---------------------------------------------------------------------------
# Helper: model name → ModelInfo
# ---------------------------------------------------------------------------


def _resolve_model_info(model_name: str) -> ModelInfo:
    """Infer :class:`~spanforge.namespaces.trace.ModelInfo` from a model name string.

    Uses prefix heuristics (``"claude-"`` → Anthropic, etc.) with
    :attr:`~spanforge.namespaces.trace.GenAISystem.OPENAI` as the fallback.
    """
    name_lower = model_name.lower()
    if name_lower.startswith("claude"):
        system = GenAISystem.ANTHROPIC
    elif name_lower.startswith("gemini"):
        system = GenAISystem.VERTEX_AI
    elif name_lower.startswith("command"):
        system = GenAISystem.COHERE
    elif name_lower.startswith("mistral") or name_lower.startswith("mixtral"):
        system = GenAISystem.MISTRAL_AI
    elif name_lower.startswith("llama") or name_lower.startswith("phi") or name_lower.startswith("qwen"):  # noqa: E501
        system = GenAISystem.OLLAMA
    else:
        system = GenAISystem.OPENAI
    return ModelInfo(system=system, name=model_name)
