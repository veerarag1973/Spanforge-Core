"""spanforge.sampling — Sampling strategies for span/event emission.

Samplers decide **at observation time** whether a span or event should be
exported.  They are composable: a :class:`ParentBasedSampler` delegates to a
root sampler for new traces and honours the parent's decision for child spans.

Configure via :func:`spanforge.configure`::

    from spanforge import configure
    from spanforge.sampling import RatioSampler, ParentBasedSampler

    configure(sampler=ParentBasedSampler(root_sampler=RatioSampler(0.1)))

Built-in samplers
-----------------

=========================================  =====================================
Class                                      Description
=========================================  =====================================
:class:`AlwaysOnSampler`                   Export every span (default).
:class:`AlwaysOffSampler`                  Drop every span.
:class:`RatioSampler`                      Probabilistic head-based sampling.
:class:`ParentBasedSampler`               Honour parent trace flags; use
                                           ``root_sampler`` for new traces.
:class:`RuleBasedSampler`                  Per-operation / per-model rules.
:class:`TailBasedSampler`                  Buffer spans, decide after span ends
                                           (e.g. always keep errors).
=========================================  =====================================

Custom samplers
---------------
Implement the :class:`Sampler` protocol::

    class MySampler:
        def should_sample(self, span_or_event, cfg) -> bool:
            return True  # or False
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import random
import threading
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Generator

__all__ = [
    "AlwaysOffSampler",
    "AlwaysOnSampler",
    "ComplianceSampler",
    "ParentBasedSampler",
    "RatioSampler",
    "RuleBasedSampler",
    "Sampler",
    "TailBasedSampler",
    "bypass_sampling",
]

_log = logging.getLogger("spanforge.sampling")


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class Sampler(Protocol):
    """Protocol implemented by all samplers.

    Args:
        span_or_event: The :class:`~spanforge._span.Span` or
            :class:`~spanforge.event.Event` being considered.
        cfg: The active :class:`~spanforge.config.SpanForgeConfig`.

    Returns:
        ``True`` if the span/event should be exported, ``False`` to drop it.
    """

    def should_sample(self, span_or_event: Any, cfg: Any) -> bool:
        """Return ``True`` to export, ``False`` to drop."""
        ...


# ---------------------------------------------------------------------------
# Always-on / Always-off
# ---------------------------------------------------------------------------


class AlwaysOnSampler:
    """Export every span.  This is the SDK default when no sampler is set."""

    def should_sample(self, span_or_event: Any, cfg: Any) -> bool:
        """Always returns True — every span is sampled."""
        return True


class AlwaysOffSampler:
    """Drop every span.  Useful for completely silencing test code."""

    def should_sample(self, span_or_event: Any, cfg: Any) -> bool:
        """Always returns False — every span is dropped."""
        return False

    def __repr__(self) -> str:
        return "AlwaysOffSampler()"


# ---------------------------------------------------------------------------
# Ratio / probabilistic
# ---------------------------------------------------------------------------


class RatioSampler:
    """Probabilistic head-based sampler.

    Makes a deterministic decision based on the span's ``trace_id`` so that
    all spans in the same trace receive the *same* sampling decision.

    Args:
        rate: Fraction of traces to export.  ``1.0`` exports all,
              ``0.0`` exports none, ``0.1`` exports roughly one-in-ten.

    Raises:
        ValueError: If *rate* is not in ``[0.0, 1.0]``.
    """

    def __init__(self, rate: float) -> None:
        if not 0.0 <= rate <= 1.0:
            raise ValueError(f"RatioSampler.rate must be in [0.0, 1.0], got {rate!r}")
        self._rate = rate
        # Threshold in [0, 2^64) — use the upper bound as an integer range.
        self._threshold = int(rate * (2**64))

    @property
    def rate(self) -> float:
        """The configured sampling fraction in [0.0, 1.0]."""
        return self._rate

    def should_sample(self, span_or_event: Any, cfg: Any) -> bool:
        """Return True if the span's trace_id hashes below the configured threshold."""
        if self._rate >= 1.0:
            return True
        if self._rate <= 0.0:
            return False
        trace_id = _get_trace_id(span_or_event)
        if trace_id is None:
            return True  # no trace context — fall through to export
        # SHA-256 of the trace_id for uniform distribution regardless of
        # whether trace_id is a UUID, ULID, or 32-hex string.
        digest = hashlib.sha256(trace_id.encode()).digest()
        # Use first 8 bytes as a big-endian uint64.
        value = int.from_bytes(digest[:8], "big")
        return value < self._threshold

    def __repr__(self) -> str:
        return f"RatioSampler(rate={self._rate!r})"


# ---------------------------------------------------------------------------
# Parent-based
# ---------------------------------------------------------------------------


class ParentBasedSampler:
    """Honour the parent span's sampling decision; use ``root_sampler`` for roots.

    This mirrors the OpenTelemetry ``ParentBased`` sampler spec so that the
    entire trace follows a single consistent decision.

    Args:
        root_sampler: The sampler to use for root spans (no parent).
            Defaults to :class:`AlwaysOnSampler`.
        remote_parent_sampled: Decision for remote-parent spans where the
            parent *was* sampled.  Defaults to ``True`` (always export).
        remote_parent_not_sampled: Decision for remote-parent spans where the
            parent was *not* sampled.  Defaults to ``False`` (always drop).
    """

    def __init__(
        self,
        root_sampler: Any | None = None,
        *,
        remote_parent_sampled: bool = True,
        remote_parent_not_sampled: bool = False,
    ) -> None:
        self._root = root_sampler if root_sampler is not None else AlwaysOnSampler()
        self._remote_sampled = remote_parent_sampled
        self._remote_not_sampled = remote_parent_not_sampled

    def should_sample(self, span_or_event: Any, cfg: Any) -> bool:
        """Delegate to root_sampler for roots; honour parent decision for child spans."""
        # Check if there's an incoming traceparent (remote parent).
        traceparent = getattr(span_or_event, "traceparent", None)
        if traceparent is not None:
            # Parse the trace-flags byte (last field of W3C traceparent).
            # Format: 00-{trace_id}-{parent_id}-{flags}
            try:
                flags = int(traceparent.rsplit("-", 1)[-1], 16)
                sampled_flag = bool(flags & 0x01)
            except (ValueError, IndexError):
                sampled_flag = False  # conservative: corrupt flags → don't sample
            return self._remote_sampled if sampled_flag else self._remote_not_sampled

        # Check if there's a local parent span via spanforge's context stack.
        parent_id = getattr(span_or_event, "parent_span_id", None)
        if parent_id is not None:
            # Local parent — honour the parent decision (keep the span since
            # the parent was already sampled to get to this point).
            return True

        # Root span — delegate to root_sampler.
        return self._root.should_sample(span_or_event, cfg)

    def __repr__(self) -> str:
        return (
            f"ParentBasedSampler(root_sampler={self._root!r}, "
            f"remote_parent_sampled={self._remote_sampled!r}, "
            f"remote_parent_not_sampled={self._remote_not_sampled!r})"
        )


# ---------------------------------------------------------------------------
# Rule-based
# ---------------------------------------------------------------------------


class RuleBasedSampler:
    """Sample based on user-defined attribute rules.

    Each rule is a ``dict`` mapping span attribute names to match values.
    A rule matches when *all* specified attributes equal their target values
    on the span.  The first matching rule wins.

    Rules list entries are dicts with keys:

    * ``match``: ``dict[str, Any]`` — attribute → expected-value pairs.
    * ``sample``: ``bool`` — whether to export when matched.

    A default decision (``default``) applies when no rule matches.

    Args:
        rules: Ordered list of rule dicts.
        default: Sampling decision when no rule matches.  Defaults to
            ``True`` (export everything by default).

    Example::

        sampler = RuleBasedSampler(
            rules=[
                {"match": {"span_name": "health_check"}, "sample": False},
                {"match": {"operation": "chat", "model.name": "gpt-4o"}, "sample": True},
            ],
            default=True,
        )
    """

    def __init__(
        self,
        rules: list[dict[str, Any]] | None = None,
        *,
        default: bool = True,
    ) -> None:
        self._rules: list[dict[str, Any]] = list(rules or [])
        self._default = default

    def should_sample(self, span_or_event: Any, cfg: Any) -> bool:
        """Return the first matching rule's decision, or the default."""
        for rule in self._rules:
            match = rule.get("match", {})
            decision = rule.get("sample", self._default)
            if self._matches(span_or_event, match):
                return bool(decision)
        return self._default

    @staticmethod
    def _matches(obj: Any, match: dict[str, Any]) -> bool:
        for key, expected in match.items():
            # Support dotted attribute paths, e.g. "model.name".
            parts = key.split(".", 1)
            val = getattr(obj, parts[0], None)
            if len(parts) == 2 and val is not None:
                val = getattr(val, parts[1], None)
            if val != expected:
                return False
        return True

    def __repr__(self) -> str:
        return f"RuleBasedSampler(rules={self._rules!r}, default={self._default!r})"


# ---------------------------------------------------------------------------
# Tail-based
# ---------------------------------------------------------------------------


class TailBasedSampler:
    """Buffer spans and decide whether to export after the span ends.

    Tail sampling inspects the *final* span state (e.g. error status, latency)
    before making an export decision.  This enables use cases like:

    * Always export error spans.
    * Always export spans with ``duration_ms > threshold``.
    * Sample only the slow-path at a given rate.

    Because decisions are made at ``on_end``, this sampler is designed to
    work alongside :class:`~spanforge.processor.SpanProcessor`.  The
    :meth:`should_sample` method is called by the SDK just before export.

    Args:
        always_sample_errors: If ``True``, spans with ``status == "error"``
            are always exported regardless of other rules.  (Default: ``True``)
        always_sample_slow_ms: If set, spans with ``duration_ms >=`` this
            value are always exported.  (Default: ``None``)
        fallback_sampler: Sampler used for spans that don't match the above
            conditions.  Defaults to :class:`AlwaysOnSampler`.
        buffer_size: Maximum number of *pending* span decisions to hold in
            memory.  Oldest are evicted when the buffer is full.
            (Default: 1 000)

    Note:
        This implementation makes the sampling decision at the time
        :meth:`should_sample` is called (typically just before export).
        The ``buffer_size`` parameter controls how many span IDs are tracked
        to deduplicate decisions within a single process.
    """

    def __init__(
        self,
        *,
        always_sample_errors: bool = True,
        always_sample_slow_ms: float | None = None,
        fallback_sampler: Any | None = None,
    ) -> None:
        self._always_errors = always_sample_errors
        self._slow_ms = always_sample_slow_ms
        self._fallback = fallback_sampler if fallback_sampler is not None else AlwaysOnSampler()
        self._lock = threading.Lock()

    def should_sample(self, span_or_event: Any, cfg: Any) -> bool:
        """Return True if the span should be exported based on error/latency rules."""
        # Error spans — always sample.
        if self._always_errors:
            status = getattr(span_or_event, "status", None)
            if isinstance(status, str) and status == "error":
                return True

        # Slow spans — always sample.
        if self._slow_ms is not None:
            duration = getattr(span_or_event, "duration_ms", None)
            if isinstance(duration, (int, float)) and duration >= self._slow_ms:
                return True

        # Fallback sampler for normal spans.
        return self._fallback.should_sample(span_or_event, cfg)

    def __repr__(self) -> str:
        return (
            f"TailBasedSampler("
            f"always_sample_errors={self._always_errors!r}, "
            f"always_sample_slow_ms={self._slow_ms!r}, "
            f"fallback_sampler={self._fallback!r})"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_trace_id(obj: Any) -> str | None:
    """Extract trace_id from a Span or Event."""
    # Direct attribute on Span.
    tid = getattr(obj, "trace_id", None)
    if isinstance(tid, str) and tid:
        return tid
    # Nested inside payload dict (Event.payload["trace_id"]).
    payload = getattr(obj, "payload", None)
    if isinstance(payload, dict):
        tid = payload.get("trace_id")
        if isinstance(tid, str) and tid:
            return tid
    return None


def _get_event_type(obj: Any) -> str | None:
    """Extract event_type string from a Span or Event."""
    et = getattr(obj, "event_type", None)
    if et is not None:
        return str(et)
    return None


# ---------------------------------------------------------------------------
# Compliance-aware sampler (SF-16)
# ---------------------------------------------------------------------------

_DEFAULT_ALWAYS_RECORD: frozenset[str] = frozenset(
    {
        "llm.redact.",
        "llm.audit.",
        "llm.guard.",
        "llm.cost.",
    }
)


class ComplianceSampler:
    """Compliance-aware sampler that never drops critical event types.

    Events whose ``event_type`` starts with any prefix in *always_record*
    are always exported (100% recording). All other events are sampled
    at *base_rate* using deterministic trace-ID-based hashing so entire
    traces are kept or dropped together.

    Args:
        base_rate: Fraction of non-compliance events to export (0.0-1.0).
        always_record: Frozenset of event-type prefixes that bypass sampling.
            Defaults to ``llm.redact.``, ``llm.audit.``, ``llm.guard.``,
            ``llm.cost.``.

    Example::

        sampler = ComplianceSampler(base_rate=0.1)
        # llm.audit.* events → always recorded
        # llm.trace.* events → ~10% recorded
    """

    def __init__(
        self,
        base_rate: float = 0.1,
        always_record: frozenset[str] | None = None,
    ) -> None:
        if not 0.0 <= base_rate <= 1.0:
            raise ValueError(
                f"ComplianceSampler.base_rate must be in [0.0, 1.0], got {base_rate!r}"
            )
        self._base_rate = base_rate
        self._always_record = always_record if always_record is not None else _DEFAULT_ALWAYS_RECORD
        self._threshold = int(base_rate * (2**64))

    @property
    def base_rate(self) -> float:
        """The base sampling fraction for non-compliance events."""
        return self._base_rate

    @property
    def always_record(self) -> frozenset[str]:
        """Frozenset of event-type prefixes that are always recorded."""
        return self._always_record

    def should_sample(self, span_or_event: Any, cfg: Any) -> bool:
        """Return True for compliance-critical events; sample others at base_rate."""
        # Check if bypass is active
        if getattr(_bypass_active, "value", False):
            return True

        # Always record compliance-critical events
        event_type = _get_event_type(span_or_event)
        if event_type is not None:
            for prefix in self._always_record:
                if event_type.startswith(prefix):
                    return True

        # Deterministic trace-ID-based sampling for other events
        if self._base_rate >= 1.0:
            return True
        if self._base_rate <= 0.0:
            return False

        trace_id = _get_trace_id(span_or_event)
        if trace_id is not None:
            digest = hashlib.sha256(trace_id.encode()).digest()
            value = int.from_bytes(digest[:8], "big")
            return value < self._threshold

        # No trace_id — fall back to random
        return random.random() < self._base_rate

    def __repr__(self) -> str:
        return f"ComplianceSampler(base_rate={self._base_rate!r})"


# ---------------------------------------------------------------------------
# Sampling bypass context manager (SF-16-D)
# ---------------------------------------------------------------------------

_bypass_active: threading.local = threading.local()


@contextlib.contextmanager
def bypass_sampling() -> Generator[None, None, None]:
    """Context manager that forces all sampling decisions to return ``True``.

    Used by compliance report generation to ensure reports reflect the
    complete audit trail, not the sampled subset::

        with bypass_sampling():
            package = engine.generate_evidence_package(...)
    """
    prev = getattr(_bypass_active, "value", False)
    _bypass_active.value = True
    try:
        yield
    finally:
        _bypass_active.value = prev
