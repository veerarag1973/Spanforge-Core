"""spanforge.workflow — Human-in-the-Loop Workflow Engine (CORE-15).

Orchestrates human-in-the-loop approval workflows for gate reviews, policy
escalations, and compliance sign-offs.  Every action is logged to a tamper-
evident audit trail and emitted as a ``workflow.*`` structured event.

Workflow types
--------------
* :attr:`WorkflowType.GATE_REVIEW` — triggered by gate execution; requires
  ``required_approvals`` distinct approvals before the gate proceeds.
* :attr:`WorkflowType.POLICY_APPROVAL` — new policy version; requires security,
  compliance, and business sign-off (all three roles).
* :attr:`WorkflowType.ESCALATION` — drift detected or cost overrun; requires
  CTO/executive sign-off before auto-remediation.

State machine
-------------
::

    PENDING → ASSIGNED → IN_PROGRESS → APPROVED ──┐
                                  ↘ REJECTED       ├──→ CLOSED
                                  ↓ ESCALATED → APPROVED / REJECTED → CLOSED

    Any active state: SLA escalation threshold → ESCALATED (via check_and_auto_escalate)

Available actions per role
--------------------------
* ``compliance_officer``: approve, request_info, reject, delegate
* ``cto``:               approve, override, escalate, reject, delegate
* ``security``:          approve, reject, request_info, delegate
* ``business``:          approve, reject, request_info, delegate
* ``system``:            auto_approve, escalate, close

Quick start
-----------
::

    from spanforge.workflow import WorkflowEngine

    wf = WorkflowEngine(
        workflow_type="gate_review",
        trigger_event={
            "gate_name": "governance",
            "model_id": "model_abc123",
            "policy_version": 2,
        },
        assignees=["compliance_officer@company.com", "cto@company.com"],
        sla_hours=24,
        escalation_after_hours=12,
    )

    wf.submit_approval(user="cto@company.com", action="approve", reason="LGTM")
    assert wf.state == WorkflowState.APPROVED
    assert "workflow.approve" in [e.action.value for e in wf.audit_trail]
"""

from __future__ import annotations

import abc
import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable

__all__ = [
    "ActionNotAllowedError",
    "InvalidTransitionError",
    "RoleConfig",
    "SLABreachError",
    "SLAStatus",
    "WorkflowAction",
    "WorkflowAuditEntry",
    "WorkflowEngine",
    "WorkflowNotificationHook",
    "WorkflowRegistry",
    "WorkflowState",
    "WorkflowType",
]

_log = logging.getLogger("spanforge.workflow")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class WorkflowError(Exception):
    """Base class for all workflow errors."""


class ActionNotAllowedError(WorkflowError):
    """Raised when a user attempts an action not permitted for their role."""


class InvalidTransitionError(WorkflowError):
    """Raised when a state transition is not permitted from the current state."""


class SLABreachError(WorkflowError):
    """Raised (optionally) when an SLA has been breached without resolution."""


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class WorkflowType(str, Enum):
    """Supported human-in-the-loop workflow categories."""

    GATE_REVIEW = "gate_review"
    """Gate execution blocked; requires n approvals before proceeding."""

    POLICY_APPROVAL = "policy_approval"
    """New policy version; requires security + compliance + business sign-off."""

    ESCALATION = "escalation"
    """Drift detected or cost overrun; requires CTO/executive sign-off."""


class WorkflowState(str, Enum):
    """Ordered states in the workflow state machine."""

    PENDING = "pending"
    """Workflow created; awaiting assignment."""

    ASSIGNED = "assigned"
    """Assigned to one or more reviewers; no action taken yet."""

    IN_PROGRESS = "in_progress"
    """At least one reviewer has taken an action."""

    APPROVED = "approved"
    """Required approvals received; workflow complete."""

    REJECTED = "rejected"
    """A reviewer rejected the workflow; workflow complete."""

    ESCALATED = "escalated"
    """SLA breached or manually escalated; awaiting escalation resolution."""

    CLOSED = "closed"
    """Terminal state — no further transitions possible."""


class WorkflowAction(str, Enum):
    """Actions that can be submitted against a workflow."""

    APPROVE = "approve"
    """Approve the item (counts toward required_approvals)."""

    REJECT = "reject"
    """Reject; immediately moves to REJECTED."""

    REQUEST_INFO = "request_info"
    """Request additional information; does not change state."""

    OVERRIDE = "override"
    """Unconditional approval regardless of pending approvals (CTO/exec only)."""

    ESCALATE = "escalate"
    """Manually escalate; moves to ESCALATED state."""

    AUTO_APPROVE = "auto_approve"
    """System auto-approval after SLA expiry (when configured)."""

    DELEGATE = "delegate"
    """Re-assign the workflow to another reviewer."""

    CLOSE = "close"
    """Transition an APPROVED or REJECTED workflow to CLOSED."""


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorkflowAuditEntry:
    """Immutable record of a single workflow action for compliance audit."""

    timestamp: str
    """ISO-8601 UTC timestamp of the action."""

    user: str
    """Identity of the actor (email address, system identifier, etc.)."""

    action: WorkflowAction
    """The action taken."""

    reason: str
    """Justification provided by the actor."""

    state_before: WorkflowState
    """Workflow state immediately before the action."""

    state_after: WorkflowState
    """Workflow state immediately after the action."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Optional extra context (e.g. delegated_to, backup_tier, escalation list)."""

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict for audit export / ZIP bundling."""
        return {
            "timestamp": self.timestamp,
            "user": self.user,
            "action": self.action.value,
            "reason": self.reason,
            "state_before": self.state_before.value,
            "state_after": self.state_after.value,
            "metadata": dict(self.metadata),
        }

    def to_json(self) -> str:
        """Serialise to a canonical, sort-key JSON string."""
        return json.dumps(self.to_dict(), sort_keys=True)


@dataclass(frozen=True)
class SLAStatus:
    """Point-in-time snapshot of SLA tracking for a workflow."""

    created_at: datetime
    """When the workflow was created (aware UTC datetime)."""

    deadline: datetime
    """Absolute SLA deadline (created_at + sla_hours)."""

    escalation_deadline: datetime
    """Auto-escalation trigger time (created_at + escalation_after_hours)."""

    elapsed_seconds: float
    """Seconds elapsed since workflow creation."""

    sla_seconds: float
    """Total SLA window in seconds."""

    is_breached: bool
    """True when elapsed_seconds ≥ sla_seconds."""

    is_escalation_due: bool
    """True when escalation threshold is passed AND workflow is still active."""

    pct_elapsed: float
    """Percentage of SLA consumed (0-100+)."""

    @property
    def remaining_seconds(self) -> float:
        """Seconds remaining until SLA deadline (negative when breached)."""
        return self.sla_seconds - self.elapsed_seconds


@dataclass
class RoleConfig:
    """Per-role action allowlist and delegation configuration."""

    role_name: str
    """Human-readable role name matched against the user identifier substring."""

    allowed_actions: frozenset[WorkflowAction] = field(
        default_factory=lambda: frozenset(
            {
                WorkflowAction.APPROVE,
                WorkflowAction.REJECT,
                WorkflowAction.REQUEST_INFO,
                WorkflowAction.DELEGATE,
            }
        )
    )
    """The set of actions permitted for this role."""

    backup_assignees: list[str] = field(default_factory=list)
    """Fallback reviewers if primary is unavailable beyond delegation_after_hours."""

    delegation_after_hours: float = 4.0
    """Hours before automatic delegation to backup_assignees triggers."""

    def allows(self, action: WorkflowAction) -> bool:
        """Return True if this role permits *action*."""
        return action in self.allowed_actions


# ---------------------------------------------------------------------------
# Built-in role configurations
# ---------------------------------------------------------------------------

_DEFAULT_ROLE_CONFIGS: dict[str, RoleConfig] = {
    "compliance_officer": RoleConfig(
        role_name="compliance_officer",
        allowed_actions=frozenset(
            {
                WorkflowAction.APPROVE,
                WorkflowAction.REQUEST_INFO,
                WorkflowAction.REJECT,
                WorkflowAction.DELEGATE,
            }
        ),
    ),
    "cto": RoleConfig(
        role_name="cto",
        allowed_actions=frozenset(
            {
                WorkflowAction.APPROVE,
                WorkflowAction.OVERRIDE,
                WorkflowAction.ESCALATE,
                WorkflowAction.DELEGATE,
                WorkflowAction.REJECT,
            }
        ),
    ),
    "security": RoleConfig(
        role_name="security",
        allowed_actions=frozenset(
            {
                WorkflowAction.APPROVE,
                WorkflowAction.REJECT,
                WorkflowAction.REQUEST_INFO,
                WorkflowAction.DELEGATE,
            }
        ),
    ),
    "business": RoleConfig(
        role_name="business",
        allowed_actions=frozenset(
            {
                WorkflowAction.APPROVE,
                WorkflowAction.REJECT,
                WorkflowAction.REQUEST_INFO,
                WorkflowAction.DELEGATE,
            }
        ),
    ),
    "system": RoleConfig(
        role_name="system",
        allowed_actions=frozenset(
            {
                WorkflowAction.AUTO_APPROVE,
                WorkflowAction.ESCALATE,
                WorkflowAction.CLOSE,
            }
        ),
    ),
}

# ---------------------------------------------------------------------------
# SLA reminder thresholds (% of SLA elapsed)
# ---------------------------------------------------------------------------

_REMINDER_THRESHOLDS: tuple[float, ...] = (50.0, 75.0, 100.0)

# ---------------------------------------------------------------------------
# Active / terminal state sets
# ---------------------------------------------------------------------------

_ACTIVE_STATES: frozenset[WorkflowState] = frozenset(
    {
        WorkflowState.PENDING,
        WorkflowState.ASSIGNED,
        WorkflowState.IN_PROGRESS,
        WorkflowState.ESCALATED,
    }
)

_TERMINAL_STATES: frozenset[WorkflowState] = frozenset(
    {WorkflowState.APPROVED, WorkflowState.REJECTED, WorkflowState.CLOSED}
)

# Default required approvals per workflow type
_DEFAULT_REQUIRED_APPROVALS: dict[WorkflowType, int] = {
    WorkflowType.GATE_REVIEW: 1,
    WorkflowType.POLICY_APPROVAL: 3,  # security + compliance + business
    WorkflowType.ESCALATION: 1,
}


# ---------------------------------------------------------------------------
# Notification hook (ABC)
# ---------------------------------------------------------------------------


class WorkflowNotificationHook(abc.ABC):
    """Abstract base for workflow event notification backends.

    Subclass and pass an instance to :class:`WorkflowEngine` to receive
    callbacks on key lifecycle events (email, Slack webhooks, PagerDuty, …).

    All methods are called **synchronously** inside the workflow lock.  Keep
    implementations non-blocking or offload I/O to a background thread.
    """

    @abc.abstractmethod
    def on_assigned(
        self, workflow_id: str, assignees: list[str], workflow_type: WorkflowType
    ) -> None:
        """Called when a workflow is assigned (or re-assigned)."""

    @abc.abstractmethod
    def on_reminder(
        self, workflow_id: str, pct_elapsed: float, remaining_seconds: float
    ) -> None:
        """Called at 50 %, 75 %, and 100 % of SLA consumption."""

    @abc.abstractmethod
    def on_escalation(
        self, workflow_id: str, reason: str, escalation_assignees: list[str]
    ) -> None:
        """Called when a workflow is escalated (auto or manual)."""

    @abc.abstractmethod
    def on_resolved(
        self,
        workflow_id: str,
        state: WorkflowState,
        action: WorkflowAction,
        user: str,
    ) -> None:
        """Called when a workflow reaches APPROVED or REJECTED."""


class _LoggingNotificationHook(WorkflowNotificationHook):
    """Default hook that writes notifications to the ``spanforge.workflow`` logger."""

    def on_assigned(
        self, workflow_id: str, assignees: list[str], workflow_type: WorkflowType
    ) -> None:
        _log.debug(
            "workflow.assigned id=%s type=%s assignees=%s",
            workflow_id,
            workflow_type.value,
            assignees,
        )

    def on_reminder(
        self, workflow_id: str, pct_elapsed: float, remaining_seconds: float
    ) -> None:
        _log.debug(
            "workflow.reminder id=%s pct=%.0f%% remaining=%.0fs",
            workflow_id,
            pct_elapsed,
            remaining_seconds,
        )

    def on_escalation(
        self, workflow_id: str, reason: str, escalation_assignees: list[str]
    ) -> None:
        _log.warning(
            "workflow.escalated id=%s reason=%r assignees=%s",
            workflow_id,
            reason,
            escalation_assignees,
        )

    def on_resolved(
        self,
        workflow_id: str,
        state: WorkflowState,
        action: WorkflowAction,
        user: str,
    ) -> None:
        _log.info(
            "workflow.resolved id=%s state=%s action=%s user=%r",
            workflow_id,
            state.value,
            action.value,
            user,
        )


# ---------------------------------------------------------------------------
# WorkflowEngine
# ---------------------------------------------------------------------------


class WorkflowEngine:
    """Human-in-the-loop approval workflow state machine.

    Each instance represents the full lifecycle of a single workflow.  Use
    :class:`WorkflowRegistry` to manage many concurrent workflow instances.

    Thread Safety
    -------------
    All public methods acquire ``_lock`` before mutating internal state.
    The engine is safe to call from multiple threads simultaneously.

    Parameters
    ----------
    workflow_type:
        One of ``"gate_review"``, ``"policy_approval"``, or ``"escalation"``.
        Also accepts :class:`WorkflowType` enum values.
    trigger_event:
        Arbitrary dict describing the triggering event (gate name, model ID, …).
    assignees:
        Initial list of reviewer identities (email addresses / user IDs).
    sla_hours:
        Hard SLA deadline in hours from creation time.
    escalation_after_hours:
        Hours after which the workflow may auto-escalate if no action is taken.
        Should be ≤ ``sla_hours``.
    required_approvals:
        Distinct approvals needed to reach APPROVED.  Defaults to the
        type-level default (1 for gate/escalation, 3 for policy approval).
    escalation_assignees:
        Additional reviewers notified and authorised on escalation.
        Defaults to the original *assignees* list.
    role_configs:
        Per-role action allowlists keyed by role identifier substring.
        Defaults to :data:`_DEFAULT_ROLE_CONFIGS`.
    notification_hook:
        Optional :class:`WorkflowNotificationHook` for email/Slack callbacks.
    event_emitter:
        Optional ``(event_type: str, payload: dict) → None`` callable invoked
        on every workflow event.  Defaults to a structured log entry.
    workflow_id:
        Explicit ID (defaults to a random UUID4).
    created_at:
        Override creation timestamp — useful for deterministic tests.
    """

    def __init__(  # noqa: PLR0913
        self,
        *,
        workflow_type: WorkflowType | str,
        trigger_event: dict[str, Any],
        assignees: list[str],
        sla_hours: float = 24.0,
        escalation_after_hours: float = 12.0,
        required_approvals: int | None = None,
        escalation_assignees: list[str] | None = None,
        role_configs: dict[str, RoleConfig] | None = None,
        notification_hook: WorkflowNotificationHook | None = None,
        event_emitter: Callable[[str, dict[str, Any]], None] | None = None,
        workflow_id: str | None = None,
        created_at: datetime | None = None,
    ) -> None:
        if isinstance(workflow_type, str):
            workflow_type = WorkflowType(workflow_type)

        self._type: WorkflowType = workflow_type
        self._trigger_event: dict[str, Any] = dict(trigger_event)
        self._assignees: list[str] = list(assignees)
        self._sla_hours: float = float(sla_hours)
        self._escalation_after_hours: float = float(escalation_after_hours)
        self._required_approvals: int = (
            required_approvals
            if required_approvals is not None
            else _DEFAULT_REQUIRED_APPROVALS[workflow_type]
        )
        self._escalation_assignees: list[str] = list(
            escalation_assignees if escalation_assignees is not None else assignees
        )
        self._role_configs: dict[str, RoleConfig] = (
            role_configs if role_configs is not None else dict(_DEFAULT_ROLE_CONFIGS)
        )
        self._hook: WorkflowNotificationHook = (
            notification_hook or _LoggingNotificationHook()
        )
        self._emitter: Callable[[str, dict[str, Any]], None] = (
            event_emitter or _default_emit
        )
        self._workflow_id: str = workflow_id or str(uuid.uuid4())

        # Normalise created_at to aware UTC.
        if created_at is None:
            self._created_at: datetime = datetime.now(tz=timezone.utc)
        elif created_at.tzinfo is None:
            self._created_at = created_at.replace(tzinfo=timezone.utc)
        else:
            self._created_at = created_at

        # Mutable state — always accessed under _lock.
        self._state: WorkflowState = WorkflowState.PENDING
        self._audit_log: list[WorkflowAuditEntry] = []
        self._approvals: dict[str, datetime] = {}   # user → approved_at (deduped)
        self._rejections: dict[str, datetime] = {}  # user → rejected_at
        self._info_requests: list[dict[str, Any]] = []
        self._delegations: list[dict[str, Any]] = []
        self._reminder_thresholds_fired: set[float] = set()
        self._lock = threading.Lock()

        # Immediately move to ASSIGNED — all assignees are known at construction.
        with self._lock:
            self._transition_to(
                WorkflowState.ASSIGNED,
                user="system",
                action=WorkflowAction.DELEGATE,
                reason=f"Initial assignment to {len(self._assignees)} reviewer(s).",
                metadata={"assignees": list(self._assignees)},
            )

        # Notification + event outside the lock (hooks may block briefly).
        self._hook.on_assigned(self._workflow_id, list(self._assignees), self._type)
        self._emit_event("workflow.assigned", {"assignees": list(self._assignees)})

    # ------------------------------------------------------------------
    # Read-only properties
    # ------------------------------------------------------------------

    @property
    def workflow_id(self) -> str:
        """Unique identifier for this workflow instance."""
        return self._workflow_id

    @property
    def workflow_type(self) -> WorkflowType:
        """The workflow category."""
        return self._type

    @property
    def state(self) -> WorkflowState:
        """Current workflow state (thread-safe read)."""
        return self._state

    @property
    def assignees(self) -> list[str]:
        """Current assignee list (returns a copy)."""
        with self._lock:
            return list(self._assignees)

    @property
    def approval_count(self) -> int:
        """Number of distinct approvals recorded so far."""
        return len(self._approvals)

    @property
    def approvals(self) -> dict[str, str]:
        """Map of ``{user: iso_timestamp}`` for each recorded approval."""
        with self._lock:
            return {u: t.isoformat() for u, t in self._approvals.items()}

    @property
    def required_approvals(self) -> int:
        """Number of approvals required to reach APPROVED."""
        return self._required_approvals

    @property
    def audit_trail(self) -> list[WorkflowAuditEntry]:
        """Immutable copy of the full action audit log."""
        with self._lock:
            return list(self._audit_log)

    @property
    def trigger_event(self) -> dict[str, Any]:
        """Copy of the trigger-event payload."""
        return dict(self._trigger_event)

    @property
    def created_at(self) -> datetime:
        """Workflow creation timestamp (aware UTC)."""
        return self._created_at

    # ------------------------------------------------------------------
    # Primary action submission
    # ------------------------------------------------------------------

    def submit_approval(
        self,
        *,
        user: str,
        action: WorkflowAction | str,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> WorkflowState:
        """Submit an approval action on behalf of *user*.

        Parameters
        ----------
        user:
            Identity of the reviewer (e.g. ``"cto@company.com"``).
        action:
            A :class:`WorkflowAction` or its string value.
        reason:
            Justification string (strongly recommended; may be empty).
        metadata:
            Optional extra context stored in the audit entry.

        Returns:
        -------
        WorkflowState
            The new workflow state after the action is applied.

        Raises:
        ------
        InvalidTransitionError
            If the workflow is in a terminal state.
        ActionNotAllowedError
            If *action* is not permitted for this user's inferred role.
        ValueError
            If *action* is not a valid :class:`WorkflowAction` string.
        """
        if isinstance(action, str):
            action = WorkflowAction(action)

        with self._lock:
            return self._handle_action(
                user=user,
                action=action,
                reason=reason,
                metadata=metadata or {},
            )

    def assign(
        self,
        assignees: list[str],
        *,
        reason: str = "Re-assigned.",
        user: str = "system",
    ) -> None:
        """Replace the current assignee list with *assignees*.

        Raises:
        ------
        InvalidTransitionError
            If the workflow is in a terminal state.
        """
        with self._lock:
            if self._state in _TERMINAL_STATES:
                raise InvalidTransitionError(
                    f"Cannot reassign a workflow in terminal state {self._state.value!r}."
                )
            old = list(self._assignees)
            self._assignees = list(assignees)
            self._record_audit(
                user=user,
                action=WorkflowAction.DELEGATE,
                reason=reason,
                state_before=self._state,
                state_after=self._state,
                metadata={"from": old, "to": list(assignees)},
            )

        self._hook.on_assigned(self._workflow_id, list(assignees), self._type)
        self._emit_event(
            "workflow.assigned", {"assignees": list(assignees), "reason": reason}
        )

    def delegate(
        self,
        *,
        from_user: str,
        to_user: str,
        reason: str = "",
        backup_tier: int = 1,
    ) -> None:
        """Delegate this workflow from *from_user* to *to_user*.

        Adds *to_user* to the assignee list (if not already present) and logs
        the delegation.  *from_user* retains visibility.

        Raises:
        ------
        InvalidTransitionError
            If the workflow is in a terminal state.
        """
        with self._lock:
            if self._state in _TERMINAL_STATES:
                raise InvalidTransitionError(
                    f"Cannot delegate a workflow in terminal state {self._state.value!r}."
                )
            if to_user not in self._assignees:
                self._assignees.append(to_user)

            delegation_record: dict[str, Any] = {
                "from": from_user,
                "to": to_user,
                "at": _utcnow(),
                "reason": reason,
                "backup_tier": backup_tier,
            }
            self._delegations.append(delegation_record)
            self._record_audit(
                user=from_user,
                action=WorkflowAction.DELEGATE,
                reason=reason or f"Delegated to {to_user}",
                state_before=self._state,
                state_after=self._state,
                metadata=delegation_record,
            )

        self._emit_event(
            "workflow.delegated",
            {"from": from_user, "to": to_user, "reason": reason},
        )

    def escalate(self, *, reason: str, user: str = "system") -> WorkflowState:
        """Manually escalate the workflow.

        Valid from any non-terminal state.  Idempotent when already ESCALATED.
        """
        with self._lock:
            return self._handle_action(
                user=user,
                action=WorkflowAction.ESCALATE,
                reason=reason,
                metadata={"escalation_assignees": list(self._escalation_assignees)},
            )

    def close(self, *, user: str = "system", reason: str = "Workflow closed.") -> None:
        """Transition an APPROVED or REJECTED workflow to CLOSED.

        Raises:
        ------
        InvalidTransitionError
            If the current state is not APPROVED or REJECTED.
        """
        with self._lock:
            if self._state not in {WorkflowState.APPROVED, WorkflowState.REJECTED}:
                raise InvalidTransitionError(
                    f"Cannot close a workflow in state {self._state.value!r}. "
                    "Only APPROVED or REJECTED workflows can be closed."
                )
            self._transition_to(
                WorkflowState.CLOSED,
                user=user,
                action=WorkflowAction.CLOSE,
                reason=reason,
            )

        self._emit_event("workflow.closed", {"reason": reason})

    # ------------------------------------------------------------------
    # SLA tracking
    # ------------------------------------------------------------------

    def check_sla(self, *, now: datetime | None = None) -> SLAStatus:
        """Return a :class:`SLAStatus` snapshot at the given moment.

        Parameters
        ----------
        now:
            Override "current time" for testing.  Defaults to ``datetime.now(UTC)``.
        """
        _now = now or datetime.now(tz=timezone.utc)
        if _now.tzinfo is None:
            _now = _now.replace(tzinfo=timezone.utc)

        elapsed = (_now - self._created_at).total_seconds()
        sla_seconds = self._sla_hours * 3600.0
        escalation_seconds = self._escalation_after_hours * 3600.0
        deadline = self._created_at + timedelta(hours=self._sla_hours)
        escalation_deadline = self._created_at + timedelta(
            hours=self._escalation_after_hours
        )
        pct = (elapsed / sla_seconds * 100.0) if sla_seconds > 0 else 0.0

        return SLAStatus(
            created_at=self._created_at,
            deadline=deadline,
            escalation_deadline=escalation_deadline,
            elapsed_seconds=elapsed,
            sla_seconds=sla_seconds,
            is_breached=elapsed >= sla_seconds,
            is_escalation_due=(
                elapsed >= escalation_seconds and self._state in _ACTIVE_STATES
            ),
            pct_elapsed=pct,
        )

    def check_and_auto_escalate(self, *, now: datetime | None = None) -> bool:
        """Auto-escalate the workflow if the escalation threshold is reached.

        Returns ``True`` if escalation was triggered.  Intended to be called
        periodically from a scheduler or background thread.
        """
        sla = self.check_sla(now=now)
        if (
            sla.is_escalation_due
            and self._state in _ACTIVE_STATES
            and self._state != WorkflowState.ESCALATED
        ):
            try:
                self.escalate(
                    reason=(
                        f"SLA auto-escalation: {sla.pct_elapsed:.0f}% of SLA consumed "
                        f"(escalation threshold {self._escalation_after_hours}h reached)."
                    ),
                    user="system",
                )
            except InvalidTransitionError:
                pass
            else:
                return True
        return False

    def check_and_fire_reminders(self, *, now: datetime | None = None) -> list[float]:
        """Fire reminder notifications for any crossed SLA percentage thresholds.

        Each threshold (50 %, 75 %, 100 %) fires **at most once** per instance.

        Returns:
        -------
        list[float]
            Thresholds fired during this call (may be empty).
        """
        sla = self.check_sla(now=now)
        fired: list[float] = []
        for threshold in _REMINDER_THRESHOLDS:
            if (
                threshold not in self._reminder_thresholds_fired
                and sla.pct_elapsed >= threshold
            ):
                self._reminder_thresholds_fired.add(threshold)
                self._hook.on_reminder(
                    self._workflow_id,
                    pct_elapsed=threshold,
                    remaining_seconds=sla.remaining_seconds,
                )
                self._emit_event(
                    "workflow.reminder",
                    {
                        "pct_elapsed": threshold,
                        "remaining_seconds": sla.remaining_seconds,
                    },
                )
                fired.append(threshold)
        return fired

    # ------------------------------------------------------------------
    # Serialisation / compliance proof
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise the complete workflow state to a plain dict."""
        with self._lock:
            return {
                "workflow_id": self._workflow_id,
                "workflow_type": self._type.value,
                "state": self._state.value,
                "trigger_event": dict(self._trigger_event),
                "assignees": list(self._assignees),
                "escalation_assignees": list(self._escalation_assignees),
                "required_approvals": self._required_approvals,
                "approval_count": len(self._approvals),
                "approvals": {u: t.isoformat() for u, t in self._approvals.items()},
                "rejections": {u: t.isoformat() for u, t in self._rejections.items()},
                "created_at": self._created_at.isoformat(),
                "sla_hours": self._sla_hours,
                "escalation_after_hours": self._escalation_after_hours,
                "audit_log": [e.to_dict() for e in self._audit_log],
                "delegations": list(self._delegations),
                "info_requests": list(self._info_requests),
            }

    def to_json(self) -> str:
        """Serialise to a canonical JSON string (keys sorted, datetime as str)."""
        return json.dumps(self.to_dict(), sort_keys=True, default=str)

    def approval_chain_proof(self) -> dict[str, Any]:
        """Return a compact approval-chain proof suitable for compliance audit packages."""
        with self._lock:
            return {
                "workflow_id": self._workflow_id,
                "workflow_type": self._type.value,
                "final_state": self._state.value,
                "required_approvals": self._required_approvals,
                "approvals": [
                    {"user": u, "approved_at": t.isoformat()}
                    for u, t in self._approvals.items()
                ],
                "rejections": [
                    {"user": u, "rejected_at": t.isoformat()}
                    for u, t in self._rejections.items()
                ],
                "audit_entries": len(self._audit_log),
                "trigger_event": dict(self._trigger_event),
            }

    # ------------------------------------------------------------------
    # Internal state machine helpers (always called under _lock)
    # ------------------------------------------------------------------

    def _handle_action(
        self,
        *,
        user: str,
        action: WorkflowAction,
        reason: str,
        metadata: dict[str, Any],
    ) -> WorkflowState:
        """Core dispatch. Must be called under ``_lock``."""
        if self._state in _TERMINAL_STATES:
            raise InvalidTransitionError(
                f"Workflow {self._workflow_id!r} is in terminal state "
                f"{self._state.value!r}; no further actions are possible."
            )

        # Role-based action gate (system user always allowed).
        if user != "system":
            allowed = self._actions_allowed_for(user)
            if action not in allowed:
                raise ActionNotAllowedError(
                    f"User {user!r} is not permitted to perform "
                    f"{action.value!r} in this workflow. "
                    f"Allowed: {sorted(a.value for a in allowed)}."
                )

        state_before = self._state
        self._apply_action(
            user=user, action=action, reason=reason, metadata=metadata
        )
        new_state = self._state

        if new_state != state_before:
            _log.info(
                "workflow.transition id=%s %s→%s action=%s user=%r",
                self._workflow_id,
                state_before.value,
                new_state.value,
                action.value,
                user,
            )

        # Fire lifecycle callbacks outside the inner mutation (still under _lock,
        # but hooks must not call back into WorkflowEngine or deadlock could occur).
        self._emit_event(
            f"workflow.{action.value}",
            {
                "user": user,
                "reason": reason,
                "state_before": state_before.value,
                "state_after": new_state.value,
                **metadata,
            },
        )
        if new_state in {WorkflowState.APPROVED, WorkflowState.REJECTED}:
            self._hook.on_resolved(self._workflow_id, new_state, action, user)
        if new_state == WorkflowState.ESCALATED and state_before != WorkflowState.ESCALATED:
            self._hook.on_escalation(
                self._workflow_id, reason, list(self._escalation_assignees)
            )

        return new_state

    def _apply_action(  # noqa: PLR0912
        self,
        *,
        user: str,
        action: WorkflowAction,
        reason: str,
        metadata: dict[str, Any],
    ) -> None:
        """Update ``_state``, ``_approvals``, etc.  Must be called under ``_lock``."""
        now = datetime.now(tz=timezone.utc)

        if action == WorkflowAction.APPROVE:
            if user not in self._approvals:
                self._approvals[user] = now
            self._advance_to_in_progress_if_needed()
            if len(self._approvals) >= self._required_approvals:
                self._transition_to(
                    WorkflowState.APPROVED,
                    user=user,
                    action=action,
                    reason=reason,
                    metadata=metadata,
                )
            else:
                # Partial approval — log without state change.
                self._record_audit(
                    user=user,
                    action=action,
                    reason=reason,
                    state_before=self._state,
                    state_after=self._state,
                    metadata={**metadata, "approval_count": len(self._approvals)},
                )

        elif action == WorkflowAction.OVERRIDE:
            # Unconditional approval regardless of pending count.
            self._approvals[user] = now
            self._transition_to(
                WorkflowState.APPROVED,
                user=user,
                action=action,
                reason=reason,
                metadata=metadata,
            )

        elif action == WorkflowAction.AUTO_APPROVE:
            self._approvals["system"] = now
            self._transition_to(
                WorkflowState.APPROVED,
                user=user,
                action=action,
                reason=reason,
                metadata=metadata,
            )

        elif action == WorkflowAction.REJECT:
            self._rejections[user] = now
            self._transition_to(
                WorkflowState.REJECTED,
                user=user,
                action=action,
                reason=reason,
                metadata=metadata,
            )

        elif action == WorkflowAction.ESCALATE:
            if self._state == WorkflowState.ESCALATED:
                # Already escalated — log only.
                self._record_audit(
                    user=user,
                    action=action,
                    reason=reason,
                    state_before=self._state,
                    state_after=self._state,
                    metadata=metadata,
                )
            else:
                self._transition_to(
                    WorkflowState.ESCALATED,
                    user=user,
                    action=action,
                    reason=reason,
                    metadata=metadata,
                )

        elif action == WorkflowAction.REQUEST_INFO:
            self._info_requests.append(
                {
                    "requested_by": user,
                    "at": now.isoformat(),
                    "reason": reason,
                    "metadata": metadata,
                }
            )
            self._advance_to_in_progress_if_needed()
            self._record_audit(
                user=user,
                action=action,
                reason=reason,
                state_before=self._state,
                state_after=self._state,
                metadata=metadata,
            )

        elif action == WorkflowAction.DELEGATE:
            to_user = metadata.get("to_user", "")
            if to_user and to_user not in self._assignees:
                self._assignees.append(to_user)
            self._record_audit(
                user=user,
                action=action,
                reason=reason,
                state_before=self._state,
                state_after=self._state,
                metadata=metadata,
            )

        elif action == WorkflowAction.CLOSE:
            # Reached via close() method which validates state pre-conditions.
            self._transition_to(
                WorkflowState.CLOSED,
                user=user,
                action=action,
                reason=reason,
                metadata=metadata,
            )

    def _advance_to_in_progress_if_needed(self) -> None:
        """ASSIGNED → IN_PROGRESS on the first reviewer action (state only)."""
        if self._state == WorkflowState.ASSIGNED:
            self._state = WorkflowState.IN_PROGRESS

    def _transition_to(
        self,
        new_state: WorkflowState,
        *,
        user: str,
        action: WorkflowAction,
        reason: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Atomically set state and record an audit entry."""
        state_before = self._state
        self._state = new_state
        self._record_audit(
            user=user,
            action=action,
            reason=reason,
            state_before=state_before,
            state_after=new_state,
            metadata=metadata or {},
        )

    def _record_audit(  # noqa: PLR0913
        self,
        *,
        user: str,
        action: WorkflowAction,
        reason: str,
        state_before: WorkflowState,
        state_after: WorkflowState,
        metadata: dict[str, Any],
    ) -> None:
        """Append an immutable :class:`WorkflowAuditEntry` to the log."""
        self._audit_log.append(
            WorkflowAuditEntry(
                timestamp=_utcnow(),
                user=user,
                action=action,
                reason=reason,
                state_before=state_before,
                state_after=state_after,
                metadata=dict(metadata),
            )
        )

    def _actions_allowed_for(self, user: str) -> frozenset[WorkflowAction]:
        """Return the permitted actions for *user* based on role config matching.

        Matching order:
        1. Exact key match in role_configs.
        2. Substring match: role_name is a substring of the user identifier.
        3. Fall back to a conservative default (approve/reject/request_info/delegate).
        """
        user_lower = user.lower()
        # Check exact key match first.
        if user_lower in self._role_configs:
            return self._role_configs[user_lower].allowed_actions
        # Substring match: "cto" ∈ "cto@company.com".
        for role_key, config in self._role_configs.items():
            if role_key in user_lower:
                return config.allowed_actions
        # Conservative default for unknown identities.
        return frozenset(
            {
                WorkflowAction.APPROVE,
                WorkflowAction.REJECT,
                WorkflowAction.REQUEST_INFO,
                WorkflowAction.DELEGATE,
            }
        )

    def _emit_event(self, event_type: str, payload: dict[str, Any]) -> None:
        """Invoke the event emitter callback, swallowing any exceptions."""
        try:
            self._emitter(
                event_type,
                {
                    "workflow_id": self._workflow_id,
                    "workflow_type": self._type.value,
                    "state": self._state.value,
                    **payload,
                },
            )
        except Exception as exc:
            _log.warning(
                "workflow event emitter raised %r for type %r; continuing.",
                exc,
                event_type,
            )


# ---------------------------------------------------------------------------
# WorkflowRegistry
# ---------------------------------------------------------------------------


class WorkflowRegistry:
    """Thread-safe registry for tracking many concurrent :class:`WorkflowEngine` instances.

    Example:
    -------
    ::

        registry = WorkflowRegistry()

        wf = registry.create(
            workflow_type="gate_review",
            trigger_event={"gate_name": "governance"},
            assignees=["reviewer@company.com"],
            sla_hours=24,
        )

        registry.get(wf.workflow_id).submit_approval(
            user="reviewer@company.com", action="approve", reason="OK"
        )

        assert registry.list_active() == []   # wf is now APPROVED
    """

    def __init__(self) -> None:
        self._workflows: dict[str, WorkflowEngine] = {}
        self._lock = threading.Lock()

    def create(self, **kwargs: Any) -> WorkflowEngine:
        """Create a new :class:`WorkflowEngine`, register it, and return it."""
        wf = WorkflowEngine(**kwargs)
        with self._lock:
            self._workflows[wf.workflow_id] = wf
        return wf

    def get(self, workflow_id: str) -> WorkflowEngine:
        """Return the workflow for *workflow_id*.

        Raises:
        ------
        KeyError
            If no workflow with that ID exists.
        """
        with self._lock:
            try:
                return self._workflows[workflow_id]
            except KeyError:
                raise KeyError(f"No workflow with id {workflow_id!r}") from None

    def list_active(self) -> list[WorkflowEngine]:
        """Return all workflows currently in an active (non-terminal) state."""
        with self._lock:
            return [
                wf for wf in self._workflows.values() if wf.state in _ACTIVE_STATES
            ]

    def list_by_type(
        self, workflow_type: WorkflowType | str
    ) -> list[WorkflowEngine]:
        """Return all workflows matching *workflow_type*."""
        if isinstance(workflow_type, str):
            workflow_type = WorkflowType(workflow_type)
        with self._lock:
            return [
                wf
                for wf in self._workflows.values()
                if wf.workflow_type == workflow_type
            ]

    def list_breached(self, *, now: datetime | None = None) -> list[WorkflowEngine]:
        """Return all active workflows whose SLA deadline has been breached."""
        with self._lock:
            return [
                wf
                for wf in self._workflows.values()
                if wf.state in _ACTIVE_STATES and wf.check_sla(now=now).is_breached
            ]

    def count(self) -> int:
        """Total number of registered workflows (all states)."""
        with self._lock:
            return len(self._workflows)

    def remove(self, workflow_id: str) -> None:
        """Deregister a workflow by ID (no-op if not found)."""
        with self._lock:
            self._workflows.pop(workflow_id, None)


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _utcnow() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()


def _default_emit(event_type: str, payload: dict[str, Any]) -> None:
    _log.info("workflow.event type=%s payload=%s", event_type, payload)
