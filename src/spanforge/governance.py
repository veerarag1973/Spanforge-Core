"""spanforge.governance — Policy-based event governance.

Block prohibited event types, warn on deprecated usage, and enforce custom
domain rules before events are emitted.

Public API
----------
EventGovernancePolicy     Mutable policy dataclass.
GovernanceViolationError  Raised when a policy blocked an event.
GovernanceWarning         Warning issued for deprecated event types.
get_global_policy()       Return the global policy singleton.
set_global_policy()       Replace (or reset) the global policy.
check_event()             Apply the global policy to an event.
governed                  Decorator — wraps a callable in the sf-explain
                          control loop so every response is automatically
                          explained and HMAC-signed.
"""

from __future__ import annotations

import functools
import logging
import warnings
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from spanforge.event import Event

_gov_log = logging.getLogger(__name__)

__all__ = [
    "EventGovernancePolicy",
    "GovernanceViolationError",
    "GovernanceWarning",
    "check_event",
    "get_global_policy",
    "governed",
    "set_global_policy",
]


# ---------------------------------------------------------------------------
# Exceptions / Warnings
# ---------------------------------------------------------------------------


class GovernanceViolationError(Exception):
    """Raised when an event is blocked by a governance policy.

    Attributes:
        event_type: The ``event_type`` string of the blocked event.
        reason:     Human-readable description of why the event was blocked.
    """

    def __init__(self, event_type: str, reason: str) -> None:
        super().__init__(f"Event '{event_type}' blocked: {reason}")
        self.event_type = event_type
        self.reason = reason


class GovernanceWarning(UserWarning):
    """Warning issued via :func:`warnings.warn` when a deprecated event type is seen.

    In pytest with ``filterwarnings = ["error"]`` this is automatically promoted
    to an exception.  Use ``pytest.warns(GovernanceWarning)`` to assert on it.
    """


# ---------------------------------------------------------------------------
# Policy dataclass
# ---------------------------------------------------------------------------


@dataclass
class EventGovernancePolicy:
    """Mutable policy controlling which events are blocked or warned about.

    Attributes:
        blocked_types:   Event type strings rejected unconditionally.
        warn_deprecated: Event type strings that emit a :class:`GovernanceWarning`.
        custom_rules:    Callables ``rule(event) -> str | None``; returning a
                         non-empty string blocks the event with that reason.
        strict_unknown:  When ``True``, any event whose type is not a registered
                         ``EventType`` value is blocked.
    """

    blocked_types: set[str] = field(default_factory=set)
    warn_deprecated: set[str] = field(default_factory=set)
    custom_rules: list[Callable[[Event], str | None]] = field(default_factory=list)
    strict_unknown: bool = False

    def check_event(self, event: Event) -> None:
        """Evaluate all rules in this policy against *event*.

        Evaluation order:

        1. **blocked_types** — raises :class:`GovernanceViolationError` immediately.
        2. **warn_deprecated** — issues :class:`GovernanceWarning`.
        3. **custom_rules** — first non-empty return value raises
           :class:`GovernanceViolationError`.
        4. **strict_unknown** — blocks event types not in ``EventType`` registry.

        Args:
            event: The event to evaluate.

        Raises:
            GovernanceViolationError: If the event is blocked.
        """
        event_type: str = getattr(event, "event_type", "")

        # Step 1 — explicit block list
        if event_type in self.blocked_types:
            raise GovernanceViolationError(
                event_type,
                f"event type '{event_type}' is in the blocked_types list",
            )

        # Step 2 — deprecated warning
        if event_type in self.warn_deprecated:
            warnings.warn(
                f"Event type '{event_type}' is deprecated. Update your instrumentation.",
                GovernanceWarning,
                stacklevel=3,
            )

        # Step 3 — custom rules
        for rule in self.custom_rules:
            reason = rule(event)
            if reason:
                raise GovernanceViolationError(event_type, reason)

        # Step 4 — strict unknown check
        if self.strict_unknown:
            try:
                from spanforge.types import EventType as _EventType

                # EventType members are string values
                valid_values = {m.value for m in _EventType}
                if event_type not in valid_values:
                    raise GovernanceViolationError(
                        event_type,
                        f"strict_unknown=True and '{event_type}' is not a registered EventType",
                    )
            except ImportError:
                pass  # If types module unavailable, skip strict check


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------

_global_policy: EventGovernancePolicy = EventGovernancePolicy()


def get_global_policy() -> EventGovernancePolicy:
    """Return the global :class:`EventGovernancePolicy` singleton.

    The default policy has no blocked types, no deprecated types, no custom
    rules, and ``strict_unknown=False``.
    """
    return _global_policy


def set_global_policy(policy: EventGovernancePolicy | None) -> None:
    """Replace the global policy.  Pass ``None`` to reset to the default.

    Args:
        policy: New policy, or ``None`` to restore defaults.
    """
    global _global_policy
    _global_policy = policy if policy is not None else EventGovernancePolicy()


def check_event(event: Event) -> None:
    """Apply the global policy to *event*.

    Equivalent to ``get_global_policy().check_event(event)``.

    Args:
        event: The event to check against the global policy.

    Raises:
        GovernanceViolationError: If the event is blocked.
        GovernanceWarning: (via warnings) if the event type is deprecated.
    """
    _global_policy.check_event(event)


# ---------------------------------------------------------------------------
# @governed — sf-explain control loop decorator (CARD 1B-1)
# ---------------------------------------------------------------------------


def governed(
    fn: Callable[..., Any] | None = None,
    *,
    agent_id: str = "governed",
    confidence_threshold: float = 0.7,
) -> Any:
    """Decorator that wraps a callable in the ``@spanforge.governed`` control loop.

    After the wrapped callable returns, its response is passed to
    :meth:`~spanforge.sdk.explain.SFExplainClient.explain` so that every
    model response is automatically explained, EU AI Act clauses are mapped,
    and an HMAC-signed record is appended to sf-audit.

    The decorator **never blocks or raises** on explain/audit failures; it
    logs a warning and returns the original response unchanged.

    Usage::

        @spanforge.governed
        def generate(prompt: str) -> str:
            return llm.invoke(prompt)

        # Or with options:
        @spanforge.governed(agent_id="billing-agent", confidence_threshold=0.8)
        def classify(text: str) -> str:
            return classifier.predict(text)

    Args:
        fn:                   The callable to wrap (provided when used as
                              ``@governed`` without parentheses).
        agent_id:             Agent identifier written into the ExplainRecord.
        confidence_threshold: Confidence score below which human oversight is
                              flagged in the EU AI Act Article 14 clause.
    """

    def _decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def _wrapper(*args: Any, **kwargs: Any) -> Any:
            result = func(*args, **kwargs)
            try:
                from spanforge.sdk import sf_explain

                context: dict[str, Any] = {
                    "agent_id": agent_id,
                    "model_output_type": kwargs.get("model_output_type", ""),
                    "confidence_score": float(kwargs.get("confidence_score", 0.0)),
                }
                sf_explain.explain(result, context)
            except Exception:  # noqa: BLE001
                _gov_log.warning(
                    "governed: sf_explain.explain() failed for %s; continuing.",
                    func.__qualname__,
                    exc_info=True,
                )
            return result

        return _wrapper

    if fn is not None:
        # Used as @governed (no parentheses)
        return _decorator(fn)
    # Used as @governed(...) with keyword arguments
    return _decorator
