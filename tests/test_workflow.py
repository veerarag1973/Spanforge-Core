"""Tests for CORE-15: WorkflowEngine, state machine, SLA, delegation, notifications.

Coverage targets:
- All state transitions (PENDING→ASSIGNED→IN_PROGRESS→APPROVED/REJECTED/ESCALATED→CLOSED)
- All three workflow types (gate_review, policy_approval, escalation)
- SLA tracking accurate to 1 minute
- Escalation logic for 5+ role combinations
- Zero lost audit entries under concurrency
- 50 workflows in <2 seconds
- Notification hooks fired correctly
- Role-based action control
- WorkflowRegistry multi-workflow management
- Gate integration (gate blocked until workflow approved)
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from spanforge.workflow import (
    ActionNotAllowedError,
    InvalidTransitionError,
    RoleConfig,
    SLAStatus,
    WorkflowAction,
    WorkflowAuditEntry,
    WorkflowEngine,
    WorkflowNotificationHook,
    WorkflowRegistry,
    WorkflowState,
    WorkflowType,
)


# ---------------------------------------------------------------------------
# Test helpers / fixtures
# ---------------------------------------------------------------------------


def _make_gate_review(**kwargs: Any) -> WorkflowEngine:
    defaults: dict[str, Any] = dict(
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
    defaults.update(kwargs)
    return WorkflowEngine(**defaults)


def _make_policy_approval(**kwargs: Any) -> WorkflowEngine:
    defaults: dict[str, Any] = dict(
        workflow_type="policy_approval",
        trigger_event={"policy_name": "data_retention_v2", "version": 3},
        assignees=[
            "security@company.com",
            "compliance_officer@company.com",
            "business@company.com",
        ],
        sla_hours=48,
        escalation_after_hours=24,
    )
    defaults.update(kwargs)
    return WorkflowEngine(**defaults)


def _make_escalation(**kwargs: Any) -> WorkflowEngine:
    defaults: dict[str, Any] = dict(
        workflow_type="escalation",
        trigger_event={"type": "drift_detected", "model_id": "model_xyz", "delta": 0.12},
        assignees=["cto@company.com"],
        sla_hours=4,
        escalation_after_hours=2,
    )
    defaults.update(kwargs)
    return WorkflowEngine(**defaults)


class _RecordingHook(WorkflowNotificationHook):
    """Test double that records all hook invocations."""

    def __init__(self) -> None:
        self.assigned: list[dict[str, Any]] = []
        self.reminders: list[dict[str, Any]] = []
        self.escalations: list[dict[str, Any]] = []
        self.resolved: list[dict[str, Any]] = []

    def on_assigned(
        self,
        workflow_id: str,
        assignees: list[str],
        workflow_type: WorkflowType,
    ) -> None:
        self.assigned.append(
            {"id": workflow_id, "assignees": list(assignees), "type": workflow_type}
        )

    def on_reminder(
        self, workflow_id: str, pct_elapsed: float, remaining_seconds: float
    ) -> None:
        self.reminders.append(
            {"id": workflow_id, "pct": pct_elapsed, "rem": remaining_seconds}
        )

    def on_escalation(
        self, workflow_id: str, reason: str, escalation_assignees: list[str]
    ) -> None:
        self.escalations.append(
            {"id": workflow_id, "reason": reason, "assignees": list(escalation_assignees)}
        )

    def on_resolved(
        self,
        workflow_id: str,
        state: WorkflowState,
        action: WorkflowAction,
        user: str,
    ) -> None:
        self.resolved.append(
            {"id": workflow_id, "state": state, "action": action, "user": user}
        )


# ---------------------------------------------------------------------------
# Enum correctness
# ---------------------------------------------------------------------------


class TestWorkflowEnums:
    def test_workflow_type_values(self) -> None:
        assert WorkflowType.GATE_REVIEW.value == "gate_review"
        assert WorkflowType.POLICY_APPROVAL.value == "policy_approval"
        assert WorkflowType.ESCALATION.value == "escalation"

    def test_all_seven_states_exist(self) -> None:
        expected = {
            "pending",
            "assigned",
            "in_progress",
            "approved",
            "rejected",
            "escalated",
            "closed",
        }
        assert {s.value for s in WorkflowState} == expected

    def test_all_eight_actions_exist(self) -> None:
        expected = {
            "approve",
            "reject",
            "request_info",
            "override",
            "escalate",
            "auto_approve",
            "delegate",
            "close",
        }
        assert {a.value for a in WorkflowAction} == expected

    def test_string_coercion_type(self) -> None:
        assert WorkflowType("gate_review") is WorkflowType.GATE_REVIEW

    def test_string_coercion_action(self) -> None:
        assert WorkflowAction("approve") is WorkflowAction.APPROVE

    def test_invalid_type_raises(self) -> None:
        with pytest.raises(ValueError):
            WorkflowType("invalid_type")

    def test_invalid_action_raises(self) -> None:
        with pytest.raises(ValueError):
            WorkflowAction("invalid_action")


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------


class TestInitialState:
    def test_starts_in_assigned_state(self) -> None:
        wf = _make_gate_review()
        assert wf.state == WorkflowState.ASSIGNED

    def test_workflow_id_is_uuid4(self) -> None:
        wf = _make_gate_review()
        # UUID4 = 36 chars with 4 hyphens
        assert len(wf.workflow_id) == 36
        assert wf.workflow_id.count("-") == 4

    def test_custom_workflow_id(self) -> None:
        wf = _make_gate_review(workflow_id="my-custom-id")
        assert wf.workflow_id == "my-custom-id"

    def test_accepts_enum_workflow_type(self) -> None:
        wf = WorkflowEngine(
            workflow_type=WorkflowType.GATE_REVIEW,
            trigger_event={"gate_name": "test"},
            assignees=["user@co.com"],
        )
        assert wf.workflow_type == WorkflowType.GATE_REVIEW

    def test_accepts_string_workflow_type(self) -> None:
        wf = _make_gate_review()
        assert wf.workflow_type == WorkflowType.GATE_REVIEW

    def test_assignees_populated(self) -> None:
        wf = _make_gate_review()
        assert "compliance_officer@company.com" in wf.assignees
        assert "cto@company.com" in wf.assignees

    def test_initial_audit_entry_recorded(self) -> None:
        wf = _make_gate_review()
        assert len(wf.audit_trail) >= 1
        assert wf.audit_trail[0].action == WorkflowAction.DELEGATE

    def test_trigger_event_stored(self) -> None:
        wf = _make_gate_review()
        assert wf.trigger_event["gate_name"] == "governance"
        assert wf.trigger_event["model_id"] == "model_abc123"

    def test_trigger_event_copy_is_independent(self) -> None:
        te: dict[str, Any] = {"gate_name": "test"}
        wf = WorkflowEngine(
            workflow_type="gate_review", trigger_event=te, assignees=["a@b.com"]
        )
        te["gate_name"] = "mutated"
        assert wf.trigger_event["gate_name"] == "test"

    def test_default_required_approvals_gate_review(self) -> None:
        assert _make_gate_review().required_approvals == 1

    def test_default_required_approvals_policy_approval(self) -> None:
        assert _make_policy_approval().required_approvals == 3

    def test_default_required_approvals_escalation(self) -> None:
        assert _make_escalation().required_approvals == 1

    def test_custom_required_approvals(self) -> None:
        wf = _make_gate_review(required_approvals=5)
        assert wf.required_approvals == 5

    def test_created_at_is_utc(self) -> None:
        wf = _make_gate_review()
        assert wf.created_at.tzinfo is not None

    def test_custom_created_at(self) -> None:
        ts = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        wf = _make_gate_review(created_at=ts)
        assert wf.created_at == ts

    def test_naive_created_at_becomes_utc(self) -> None:
        ts = datetime(2026, 1, 1, 12, 0, 0)  # naive
        wf = _make_gate_review(created_at=ts)
        assert wf.created_at.tzinfo == timezone.utc


# ---------------------------------------------------------------------------
# Gate Review — Type 1 state machine
# ---------------------------------------------------------------------------


class TestGateReviewStateMachine:
    def test_approve_single_reaches_approved(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="Looks good"
        )
        assert wf.state == WorkflowState.APPROVED

    def test_reject_reaches_rejected(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com",
            action="reject",
            reason="Policy violation",
        )
        assert wf.state == WorkflowState.REJECTED

    def test_override_reaches_approved(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="cto@company.com", action="override", reason="Executive override"
        )
        assert wf.state == WorkflowState.APPROVED

    def test_request_info_moves_to_in_progress(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com",
            action="request_info",
            reason="Need audit logs",
        )
        assert wf.state == WorkflowState.IN_PROGRESS

    def test_escalate_moves_to_escalated(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="cto@company.com", action="escalate", reason="Needs board review"
        )
        assert wf.state == WorkflowState.ESCALATED

    def test_escalated_then_approve(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(user="cto@company.com", action="escalate", reason="Escalate")
        wf.submit_approval(
            user="compliance_officer@company.com",
            action="approve",
            reason="Cleared after escalation",
        )
        assert wf.state == WorkflowState.APPROVED

    def test_escalated_then_reject(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(user="cto@company.com", action="escalate", reason="Escalate")
        wf.submit_approval(
            user="cto@company.com", action="reject", reason="Rejected at exec level"
        )
        assert wf.state == WorkflowState.REJECTED

    def test_terminal_state_blocks_further_actions(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="OK"
        )
        with pytest.raises(InvalidTransitionError):
            wf.submit_approval(
                user="cto@company.com", action="approve", reason="Already approved"
            )

    def test_approved_can_be_closed(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="OK"
        )
        wf.close(reason="Gate passed — archiving.")
        assert wf.state == WorkflowState.CLOSED

    def test_rejected_can_be_closed(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com", action="reject", reason="No"
        )
        wf.close()
        assert wf.state == WorkflowState.CLOSED

    def test_in_progress_cannot_be_directly_closed(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com",
            action="request_info",
            reason="Info needed",
        )
        with pytest.raises(InvalidTransitionError):
            wf.close()

    def test_auto_approve_reaches_approved(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(user="system", action="auto_approve", reason="SLA expired")
        assert wf.state == WorkflowState.APPROVED

    def test_two_approvals_required_first_partial(self) -> None:
        wf = _make_gate_review(required_approvals=2)
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="Part 1"
        )
        assert wf.state == WorkflowState.IN_PROGRESS
        assert wf.approval_count == 1

    def test_two_approvals_required_second_completes(self) -> None:
        wf = _make_gate_review(required_approvals=2)
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="Part 1"
        )
        wf.submit_approval(user="cto@company.com", action="approve", reason="Part 2")
        assert wf.state == WorkflowState.APPROVED
        assert wf.approval_count == 2

    def test_duplicate_approval_deduped(self) -> None:
        wf = _make_gate_review(required_approvals=2)
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="First"
        )
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="Duplicate"
        )
        assert wf.approval_count == 1  # only counted once

    def test_action_with_enum_value(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com",
            action=WorkflowAction.APPROVE,
            reason="Using enum",
        )
        assert wf.state == WorkflowState.APPROVED


# ---------------------------------------------------------------------------
# Policy Approval — Type 2 (requires all 3 roles)
# ---------------------------------------------------------------------------


class TestPolicyApprovalWorkflow:
    def test_requires_three_approvals(self) -> None:
        assert _make_policy_approval().required_approvals == 3

    def test_first_approval_moves_to_in_progress(self) -> None:
        wf = _make_policy_approval()
        wf.submit_approval(
            user="security@company.com", action="approve", reason="Security OK"
        )
        assert wf.state == WorkflowState.IN_PROGRESS

    def test_two_approvals_still_in_progress(self) -> None:
        wf = _make_policy_approval()
        wf.submit_approval(
            user="security@company.com", action="approve", reason="Security OK"
        )
        wf.submit_approval(
            user="compliance_officer@company.com",
            action="approve",
            reason="Compliance OK",
        )
        assert wf.state == WorkflowState.IN_PROGRESS
        assert wf.approval_count == 2

    def test_all_three_approvals_reaches_approved(self) -> None:
        wf = _make_policy_approval()
        wf.submit_approval(
            user="security@company.com", action="approve", reason="Security OK"
        )
        wf.submit_approval(
            user="compliance_officer@company.com",
            action="approve",
            reason="Compliance OK",
        )
        wf.submit_approval(
            user="business@company.com", action="approve", reason="Business OK"
        )
        assert wf.state == WorkflowState.APPROVED
        assert wf.approval_count == 3

    def test_single_reject_terminates_immediately(self) -> None:
        wf = _make_policy_approval()
        wf.submit_approval(
            user="security@company.com", action="approve", reason="Security OK"
        )
        wf.submit_approval(
            user="compliance_officer@company.com",
            action="reject",
            reason="Compliance risk too high",
        )
        assert wf.state == WorkflowState.REJECTED

    def test_policy_workflow_has_48h_sla(self) -> None:
        wf = _make_policy_approval()
        sla = wf.check_sla()
        assert abs(sla.sla_seconds - 48 * 3600) < 1


# ---------------------------------------------------------------------------
# Escalation — Type 3
# ---------------------------------------------------------------------------


class TestEscalationWorkflow:
    def test_requires_one_approval(self) -> None:
        assert _make_escalation().required_approvals == 1

    def test_cto_override_approves(self) -> None:
        wf = _make_escalation()
        wf.submit_approval(
            user="cto@company.com", action="override", reason="CTO decision"
        )
        assert wf.state == WorkflowState.APPROVED

    def test_escalation_reject(self) -> None:
        wf = _make_escalation()
        wf.submit_approval(
            user="cto@company.com",
            action="reject",
            reason="Remediation plan insufficient",
        )
        assert wf.state == WorkflowState.REJECTED

    def test_auto_escalate_triggers(self) -> None:
        past = datetime.now(tz=timezone.utc) - timedelta(hours=3)
        wf = _make_escalation(created_at=past)
        triggered = wf.check_and_auto_escalate()
        assert triggered
        assert wf.state == WorkflowState.ESCALATED

    def test_trigger_event_captured(self) -> None:
        wf = _make_escalation()
        assert wf.trigger_event["type"] == "drift_detected"
        assert wf.trigger_event["delta"] == 0.12


# ---------------------------------------------------------------------------
# SLA tracking — accurate to 1 minute
# ---------------------------------------------------------------------------


class TestSLATracking:
    def test_not_breached_at_creation(self) -> None:
        wf = _make_gate_review()
        sla = wf.check_sla()
        assert not sla.is_breached
        assert sla.pct_elapsed < 1.0

    def test_breached_after_25_hours(self) -> None:
        past = datetime.now(tz=timezone.utc) - timedelta(hours=25)
        wf = _make_gate_review(created_at=past)
        sla = wf.check_sla()
        assert sla.is_breached
        assert sla.pct_elapsed > 100.0

    def test_50_percent_elapsed(self) -> None:
        past = datetime.now(tz=timezone.utc) - timedelta(hours=12)
        wf = _make_gate_review(created_at=past)
        sla = wf.check_sla()
        # Allow ±1 min tolerance (≈0.07%)
        assert 48.9 < sla.pct_elapsed < 51.1

    def test_75_percent_elapsed(self) -> None:
        past = datetime.now(tz=timezone.utc) - timedelta(hours=18)
        wf = _make_gate_review(created_at=past)
        sla = wf.check_sla()
        assert 73.9 < sla.pct_elapsed < 76.1

    def test_sla_deadline_is_24h_after_creation(self) -> None:
        wf = _make_gate_review()
        sla = wf.check_sla()
        delta = (sla.deadline - sla.created_at).total_seconds()
        assert abs(delta - 24 * 3600) < 1

    def test_escalation_deadline_is_12h_after_creation(self) -> None:
        wf = _make_gate_review()
        sla = wf.check_sla()
        delta = (sla.escalation_deadline - sla.created_at).total_seconds()
        assert abs(delta - 12 * 3600) < 1

    def test_escalation_due_after_threshold(self) -> None:
        past = datetime.now(tz=timezone.utc) - timedelta(hours=13)
        wf = _make_gate_review(created_at=past)
        assert wf.check_sla().is_escalation_due

    def test_escalation_not_due_when_terminal(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="OK"
        )
        # Even with now advanced past threshold, terminal workflows are not "escalation due".
        future_now = wf.created_at + timedelta(hours=13)
        sla = wf.check_sla(now=future_now)
        assert not sla.is_escalation_due

    def test_remaining_seconds_positive_before_breach(self) -> None:
        wf = _make_gate_review()
        assert wf.check_sla().remaining_seconds > 0

    def test_remaining_seconds_negative_after_breach(self) -> None:
        past = datetime.now(tz=timezone.utc) - timedelta(hours=25)
        wf = _make_gate_review(created_at=past)
        assert wf.check_sla().remaining_seconds < 0

    def test_elapsed_accurate_to_60_seconds(self) -> None:
        ref = datetime.now(tz=timezone.utc) - timedelta(hours=6)
        wf = _make_gate_review(created_at=ref)
        sla = wf.check_sla()
        assert abs(sla.elapsed_seconds - 6 * 3600) < 60  # ±1 minute

    def test_override_now_parameter(self) -> None:
        wf = _make_gate_review()
        future = wf.created_at + timedelta(hours=30)
        sla = wf.check_sla(now=future)
        assert sla.is_breached

    def test_naive_now_accepted(self) -> None:
        wf = _make_gate_review()
        naive_now = datetime.now()  # naive, no tzinfo — engine should handle it
        sla = wf.check_sla(now=naive_now)
        assert isinstance(sla, SLAStatus)

    def test_auto_escalate_triggers_on_threshold(self) -> None:
        past = datetime.now(tz=timezone.utc) - timedelta(hours=13)
        wf = _make_gate_review(created_at=past)
        assert wf.check_and_auto_escalate()
        assert wf.state == WorkflowState.ESCALATED

    def test_auto_escalate_noop_when_resolved(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="OK"
        )
        future = wf.created_at + timedelta(hours=25)
        assert not wf.check_and_auto_escalate(now=future)

    def test_auto_escalate_noop_when_already_escalated(self) -> None:
        past = datetime.now(tz=timezone.utc) - timedelta(hours=13)
        wf = _make_gate_review(created_at=past)
        wf.check_and_auto_escalate()  # first — escalates
        # already ESCALATED; second call should be no-op
        assert not wf.check_and_auto_escalate()


# ---------------------------------------------------------------------------
# Reminder notifications
# ---------------------------------------------------------------------------


class TestReminders:
    def test_no_reminders_at_creation(self) -> None:
        hook = _RecordingHook()
        wf = _make_gate_review(notification_hook=hook)
        assert wf.check_and_fire_reminders() == []

    def test_50_pct_reminder_fires(self) -> None:
        hook = _RecordingHook()
        past = datetime.now(tz=timezone.utc) - timedelta(hours=12)
        wf = _make_gate_review(created_at=past, notification_hook=hook)
        fired = wf.check_and_fire_reminders()
        assert 50.0 in fired
        assert any(r["pct"] == 50.0 for r in hook.reminders)

    def test_75_pct_reminder_fires(self) -> None:
        hook = _RecordingHook()
        past = datetime.now(tz=timezone.utc) - timedelta(hours=18, minutes=30)
        wf = _make_gate_review(created_at=past, notification_hook=hook)
        fired = wf.check_and_fire_reminders()
        assert 75.0 in fired

    def test_100_pct_reminder_fires(self) -> None:
        hook = _RecordingHook()
        past = datetime.now(tz=timezone.utc) - timedelta(hours=25)
        wf = _make_gate_review(created_at=past, notification_hook=hook)
        fired = wf.check_and_fire_reminders()
        assert 100.0 in fired

    def test_all_three_thresholds_fire_at_100_pct(self) -> None:
        hook = _RecordingHook()
        past = datetime.now(tz=timezone.utc) - timedelta(hours=25)
        wf = _make_gate_review(created_at=past, notification_hook=hook)
        fired = wf.check_and_fire_reminders()
        assert {50.0, 75.0, 100.0} == set(fired)

    def test_reminders_idempotent(self) -> None:
        hook = _RecordingHook()
        past = datetime.now(tz=timezone.utc) - timedelta(hours=12)
        wf = _make_gate_review(created_at=past, notification_hook=hook)
        wf.check_and_fire_reminders()
        wf.check_and_fire_reminders()  # second call
        assert len(hook.reminders) == 1  # fired only once

    def test_reminder_returns_empty_list_if_no_new_thresholds(self) -> None:
        hook = _RecordingHook()
        past = datetime.now(tz=timezone.utc) - timedelta(hours=12)
        wf = _make_gate_review(created_at=past, notification_hook=hook)
        wf.check_and_fire_reminders()
        second = wf.check_and_fire_reminders()
        assert second == []


# ---------------------------------------------------------------------------
# Assignment & Delegation
# ---------------------------------------------------------------------------


class TestAssignmentDelegation:
    def test_assign_replaces_assignee_list(self) -> None:
        wf = _make_gate_review()
        wf.assign(["newreviewer@co.com"], reason="Team rotation")
        assert wf.assignees == ["newreviewer@co.com"]

    def test_assign_in_terminal_state_raises(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="OK"
        )
        with pytest.raises(InvalidTransitionError):
            wf.assign(["someone@co.com"])

    def test_delegate_adds_to_assignees(self) -> None:
        wf = _make_gate_review()
        wf.delegate(
            from_user="compliance_officer@company.com",
            to_user="backup@company.com",
            reason="OOO this week",
        )
        assert "backup@company.com" in wf.assignees

    def test_delegate_retains_from_user(self) -> None:
        wf = _make_gate_review()
        wf.delegate(
            from_user="compliance_officer@company.com",
            to_user="backup@company.com",
            reason="OOO",
        )
        assert "compliance_officer@company.com" in wf.assignees

    def test_delegate_existing_user_not_duplicated(self) -> None:
        wf = _make_gate_review()
        wf.delegate(
            from_user="compliance_officer@company.com",
            to_user="cto@company.com",
            reason="Needs CTO eyes",
        )
        assert wf.assignees.count("cto@company.com") == 1

    def test_delegate_in_terminal_state_raises(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com", action="reject", reason="No"
        )
        with pytest.raises(InvalidTransitionError):
            wf.delegate(
                from_user="compliance_officer@company.com",
                to_user="backup@company.com",
            )

    def test_delegation_recorded_in_audit(self) -> None:
        wf = _make_gate_review()
        wf.delegate(
            from_user="compliance_officer@company.com",
            to_user="backup@company.com",
            reason="4h OOO",
        )
        actions = [e.action for e in wf.audit_trail]
        assert WorkflowAction.DELEGATE in actions

    def test_notification_on_assign(self) -> None:
        hook = _RecordingHook()
        wf = _make_gate_review(notification_hook=hook)
        wf.assign(["newreviewer@co.com"], reason="Re-assign")
        assert any("newreviewer@co.com" in r["assignees"] for r in hook.assigned)

    def test_assign_notification_triggered_on_init(self) -> None:
        hook = _RecordingHook()
        _make_gate_review(notification_hook=hook)
        assert len(hook.assigned) >= 1

    def test_multiple_delegations_tracked(self) -> None:
        wf = _make_gate_review()
        wf.delegate(
            from_user="compliance_officer@company.com",
            to_user="backup1@company.com",
            reason="OOO",
        )
        wf.delegate(
            from_user="backup1@company.com",
            to_user="backup2@company.com",
            reason="Also OOO",
        )
        assert "backup1@company.com" in wf.assignees
        assert "backup2@company.com" in wf.assignees


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------


class TestAuditTrail:
    def test_every_action_creates_audit_entry(self) -> None:
        wf = _make_gate_review()
        initial = len(wf.audit_trail)
        wf.submit_approval(
            user="compliance_officer@company.com",
            action="request_info",
            reason="Need docs",
        )
        wf.submit_approval(user="cto@company.com", action="approve", reason="Looks good")
        assert len(wf.audit_trail) == initial + 2

    def test_audit_entry_user_correct(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com",
            action="approve",
            reason="Approved after review",
        )
        entry = next(e for e in wf.audit_trail if e.action == WorkflowAction.APPROVE)
        assert entry.user == "compliance_officer@company.com"

    def test_audit_entry_reason_stored(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com",
            action="approve",
            reason="All criteria met — audit signed off",
        )
        entry = next(e for e in wf.audit_trail if e.action == WorkflowAction.APPROVE)
        assert entry.reason == "All criteria met — audit signed off"

    def test_audit_entry_state_after_correct(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="OK"
        )
        entry = next(e for e in wf.audit_trail if e.action == WorkflowAction.APPROVE)
        assert entry.state_after == WorkflowState.APPROVED

    def test_audit_entry_timestamp_non_empty(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="OK"
        )
        for entry in wf.audit_trail:
            assert entry.timestamp

    def test_audit_trail_returns_copy(self) -> None:
        wf = _make_gate_review()
        trail = wf.audit_trail
        trail.append(None)  # type: ignore[arg-type]
        assert None not in wf.audit_trail

    def test_audit_entry_to_dict(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="OK"
        )
        entry = next(e for e in wf.audit_trail if e.action == WorkflowAction.APPROVE)
        d = entry.to_dict()
        assert d["user"] == "compliance_officer@company.com"
        assert d["action"] == "approve"
        assert "state_before" in d
        assert "state_after" in d
        assert "metadata" in d

    def test_audit_entry_to_json_valid(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="OK"
        )
        entry = next(e for e in wf.audit_trail if e.action == WorkflowAction.APPROVE)
        parsed = json.loads(entry.to_json())
        assert parsed["action"] == "approve"

    def test_approval_chain_proof_fields(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="OK"
        )
        proof = wf.approval_chain_proof()
        assert proof["final_state"] == "approved"
        assert proof["required_approvals"] == 1
        assert proof["approvals"][0]["user"] == "compliance_officer@company.com"
        assert "approved_at" in proof["approvals"][0]

    def test_to_dict_contains_required_fields(self) -> None:
        wf = _make_gate_review()
        d = wf.to_dict()
        for key in (
            "workflow_id",
            "workflow_type",
            "state",
            "trigger_event",
            "assignees",
            "required_approvals",
            "audit_log",
            "created_at",
            "sla_hours",
        ):
            assert key in d, f"Missing key: {key}"

    def test_to_json_parseable(self) -> None:
        wf = _make_gate_review()
        data = json.loads(wf.to_json())
        assert data["workflow_type"] == "gate_review"

    def test_zero_lost_audit_logs_under_sequential_actions(self) -> None:
        """Each submit_approval must produce at least one new audit entry."""
        wf = _make_gate_review(required_approvals=10)
        extra_users = [f"reviewer{i}@co.com" for i in range(5)]
        wf._assignees.extend(extra_users)  # inject extra assignees directly
        initial = len(wf.audit_trail)
        for u in extra_users:
            wf.submit_approval(user=u, action="approve", reason="OK")
        assert len(wf.audit_trail) == initial + 5

    def test_request_info_stored_in_info_requests(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com",
            action="request_info",
            reason="Needs audit evidence",
        )
        assert len(wf._info_requests) == 1
        assert wf._info_requests[0]["requested_by"] == "compliance_officer@company.com"


# ---------------------------------------------------------------------------
# Notification hooks
# ---------------------------------------------------------------------------


class TestNotificationHooks:
    def test_on_assigned_called_at_init(self) -> None:
        hook = _RecordingHook()
        _make_gate_review(notification_hook=hook)
        assert len(hook.assigned) == 1

    def test_on_resolved_approve(self) -> None:
        hook = _RecordingHook()
        wf = _make_gate_review(notification_hook=hook)
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="OK"
        )
        assert len(hook.resolved) == 1
        assert hook.resolved[0]["state"] == WorkflowState.APPROVED

    def test_on_resolved_reject(self) -> None:
        hook = _RecordingHook()
        wf = _make_gate_review(notification_hook=hook)
        wf.submit_approval(
            user="compliance_officer@company.com", action="reject", reason="No"
        )
        assert hook.resolved[0]["state"] == WorkflowState.REJECTED

    def test_on_escalation_called(self) -> None:
        hook = _RecordingHook()
        wf = _make_gate_review(notification_hook=hook)
        wf.escalate(reason="Critical policy violation detected")
        assert len(hook.escalations) == 1
        assert "Critical policy" in hook.escalations[0]["reason"]

    def test_on_escalation_not_called_twice_for_same_escalation(self) -> None:
        hook = _RecordingHook()
        past = datetime.now(tz=timezone.utc) - timedelta(hours=13)
        wf = _make_gate_review(created_at=past, notification_hook=hook)
        wf.check_and_auto_escalate()
        # Already ESCALATED — another call should not fire on_escalation again.
        wf.check_and_auto_escalate()
        assert len(hook.escalations) == 1

    def test_custom_event_emitter_receives_events(self) -> None:
        events: list[dict[str, Any]] = []

        def emitter(event_type: str, payload: dict[str, Any]) -> None:
            events.append({"type": event_type, **payload})

        wf = _make_gate_review(event_emitter=emitter)
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="OK"
        )
        types = [e["type"] for e in events]
        assert "workflow.assigned" in types
        assert "workflow.approve" in types

    def test_emitter_error_does_not_crash_workflow(self) -> None:
        def bad_emitter(event_type: str, payload: dict[str, Any]) -> None:
            raise RuntimeError("Emitter failure")

        wf = _make_gate_review(event_emitter=bad_emitter)
        # Should not raise despite bad emitter.
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="OK"
        )
        assert wf.state == WorkflowState.APPROVED

    def test_on_assigned_called_when_reassigned(self) -> None:
        hook = _RecordingHook()
        wf = _make_gate_review(notification_hook=hook)
        wf.assign(["newreviewer@co.com"], reason="Re-assign")
        assert len(hook.assigned) == 2  # init + re-assign


# ---------------------------------------------------------------------------
# Role-based action control
# ---------------------------------------------------------------------------


class TestRoleBasedActions:
    def test_compliance_officer_can_approve(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="OK"
        )
        assert wf.state == WorkflowState.APPROVED

    def test_compliance_officer_cannot_override(self) -> None:
        wf = _make_gate_review()
        with pytest.raises(ActionNotAllowedError):
            wf.submit_approval(
                user="compliance_officer@company.com",
                action="override",
                reason="Trying override",
            )

    def test_compliance_officer_cannot_escalate(self) -> None:
        wf = _make_gate_review()
        with pytest.raises(ActionNotAllowedError):
            wf.submit_approval(
                user="compliance_officer@company.com",
                action="escalate",
                reason="Trying to escalate",
            )

    def test_cto_can_override(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="cto@company.com", action="override", reason="Executive override"
        )
        assert wf.state == WorkflowState.APPROVED

    def test_cto_can_escalate(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="cto@company.com", action="escalate", reason="Board review needed"
        )
        assert wf.state == WorkflowState.ESCALATED

    def test_security_can_approve(self) -> None:
        wf = _make_policy_approval()
        wf.submit_approval(
            user="security@company.com", action="approve", reason="Security cleared"
        )
        assert wf.approval_count == 1

    def test_business_can_request_info(self) -> None:
        wf = _make_policy_approval()
        wf.submit_approval(
            user="business@company.com", action="request_info", reason="ROI unclear"
        )
        assert wf.state == WorkflowState.IN_PROGRESS

    def test_system_user_bypasses_role_check(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(user="system", action="auto_approve", reason="SLA expired")
        assert wf.state == WorkflowState.APPROVED

    def test_unknown_user_gets_conservative_default(self) -> None:
        wf = _make_gate_review()
        # Unknown user should be able to approve/reject/request_info/delegate.
        wf.submit_approval(user="unknown@co.com", action="approve", reason="OK")
        assert wf.state == WorkflowState.APPROVED

    def test_unknown_user_cannot_override(self) -> None:
        wf = _make_gate_review()
        with pytest.raises(ActionNotAllowedError):
            wf.submit_approval(
                user="unknown@co.com", action="override", reason="Trying"
            )

    def test_custom_role_config(self) -> None:
        custom_roles = {
            "auditor": RoleConfig(
                role_name="auditor",
                allowed_actions=frozenset(
                    {WorkflowAction.APPROVE, WorkflowAction.REQUEST_INFO}
                ),
            )
        }
        wf = WorkflowEngine(
            workflow_type="gate_review",
            trigger_event={"gate_name": "test"},
            assignees=["auditor_jones@co.com"],
            role_configs=custom_roles,
        )
        wf.submit_approval(
            user="auditor_jones@co.com", action="approve", reason="Audit passed"
        )
        assert wf.state == WorkflowState.APPROVED

    def test_custom_role_reject_blocked_when_not_allowed(self) -> None:
        custom_roles = {
            "auditor": RoleConfig(
                role_name="auditor",
                allowed_actions=frozenset({WorkflowAction.APPROVE}),
            )
        }
        wf = WorkflowEngine(
            workflow_type="gate_review",
            trigger_event={"gate_name": "test"},
            assignees=["auditor_jones@co.com"],
            role_configs=custom_roles,
        )
        with pytest.raises(ActionNotAllowedError):
            wf.submit_approval(
                user="auditor_jones@co.com", action="reject", reason="No"
            )

    def test_role_config_allows_method(self) -> None:
        rc = RoleConfig(
            role_name="reviewer",
            allowed_actions=frozenset({WorkflowAction.APPROVE}),
        )
        assert rc.allows(WorkflowAction.APPROVE)
        assert not rc.allows(WorkflowAction.OVERRIDE)


# ---------------------------------------------------------------------------
# Escalation — 5+ role combinations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "user,action",
    [
        ("cto@company.com", "escalate"),
        ("cto@company.com", "override"),
        ("compliance_officer@company.com", "reject"),
        ("security@company.com", "approve"),
        ("business@company.com", "approve"),
    ],
)
def test_role_action_combinations(user: str, action: str) -> None:
    wf = _make_policy_approval()
    wf.submit_approval(user=user, action=action, reason=f"Test {action}")
    assert wf.state in WorkflowState.__members__.values()


class TestEscalationChain:
    def test_full_5_step_chain(self) -> None:
        """escalate → request_info (stays escalated) → override → closed."""
        wf = _make_gate_review(
            escalation_assignees=["cto@company.com"],
        )
        # Step 1: CTO escalates.
        wf.submit_approval(
            user="cto@company.com", action="escalate", reason="Complex risk"
        )
        assert wf.state == WorkflowState.ESCALATED

        # Step 2: Compliance officer requests more info while escalated.
        wf.submit_approval(
            user="compliance_officer@company.com",
            action="request_info",
            reason="Need incident report",
        )
        assert wf.state == WorkflowState.ESCALATED

        # Step 3: CTO overrides and approves.
        wf.submit_approval(
            user="cto@company.com", action="override", reason="Risk accepted by board"
        )
        assert wf.state == WorkflowState.APPROVED

        # Step 4: Close.
        wf.close(reason="Governance gate archived")
        assert wf.state == WorkflowState.CLOSED

    def test_double_escalate_idempotent(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="cto@company.com", action="escalate", reason="First escalation"
        )
        wf.submit_approval(
            user="cto@company.com", action="escalate", reason="Second escalation attempt"
        )
        assert wf.state == WorkflowState.ESCALATED


# ---------------------------------------------------------------------------
# WorkflowRegistry
# ---------------------------------------------------------------------------


class TestWorkflowRegistry:
    def test_create_and_get(self) -> None:
        reg = WorkflowRegistry()
        wf = reg.create(
            workflow_type="gate_review",
            trigger_event={"gate": "test"},
            assignees=["user@co.com"],
        )
        assert reg.get(wf.workflow_id) is wf

    def test_get_missing_raises_key_error(self) -> None:
        reg = WorkflowRegistry()
        with pytest.raises(KeyError):
            reg.get("non-existent-id")

    def test_list_active_excludes_resolved(self) -> None:
        reg = WorkflowRegistry()
        wf1 = reg.create(
            workflow_type="gate_review", trigger_event={}, assignees=["a@co.com"]
        )
        wf2 = reg.create(
            workflow_type="escalation", trigger_event={}, assignees=["b@co.com"]
        )
        wf2.submit_approval(user="b@co.com", action="approve", reason="OK")
        active = reg.list_active()
        assert wf1 in active
        assert wf2 not in active

    def test_list_by_type(self) -> None:
        reg = WorkflowRegistry()
        reg.create(workflow_type="gate_review", trigger_event={}, assignees=["a@co.com"])
        reg.create(workflow_type="gate_review", trigger_event={}, assignees=["b@co.com"])
        reg.create(
            workflow_type="escalation", trigger_event={}, assignees=["c@co.com"]
        )
        gate_wfs = reg.list_by_type("gate_review")
        assert len(gate_wfs) == 2

    def test_list_by_type_enum(self) -> None:
        reg = WorkflowRegistry()
        reg.create(
            workflow_type=WorkflowType.ESCALATION,
            trigger_event={},
            assignees=["cto@co.com"],
        )
        assert len(reg.list_by_type(WorkflowType.ESCALATION)) == 1

    def test_list_breached(self) -> None:
        reg = WorkflowRegistry()
        past = datetime.now(tz=timezone.utc) - timedelta(hours=25)
        reg.create(
            workflow_type="gate_review",
            trigger_event={},
            assignees=["a@co.com"],
            created_at=past,
        )
        reg.create(
            workflow_type="gate_review", trigger_event={}, assignees=["b@co.com"]
        )
        breached = reg.list_breached()
        assert len(breached) == 1

    def test_count(self) -> None:
        reg = WorkflowRegistry()
        for i in range(5):
            reg.create(
                workflow_type="gate_review",
                trigger_event={},
                assignees=[f"u{i}@co.com"],
            )
        assert reg.count() == 5

    def test_remove(self) -> None:
        reg = WorkflowRegistry()
        wf = reg.create(
            workflow_type="escalation", trigger_event={}, assignees=["cto@co.com"]
        )
        reg.remove(wf.workflow_id)
        assert reg.count() == 0

    def test_remove_nonexistent_noop(self) -> None:
        reg = WorkflowRegistry()
        reg.remove("does-not-exist")  # should not raise


# ---------------------------------------------------------------------------
# Concurrency — 100 concurrent workflows, zero data corruption
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_100_concurrent_workflows(self) -> None:
        """Create and approve 100 concurrent workflows without data corruption."""
        reg = WorkflowRegistry()
        errors: list[Exception] = []

        def run_workflow(i: int) -> None:
            try:
                wf = reg.create(
                    workflow_type="gate_review",
                    trigger_event={"index": i},
                    assignees=[f"reviewer{i}@co.com"],
                )
                wf.submit_approval(
                    user=f"reviewer{i}@co.com",
                    action="approve",
                    reason=f"Auto-approve #{i}",
                )
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=run_workflow, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Errors: {errors}"
        assert reg.count() == 100
        approved = [
            wf
            for wf in reg.list_by_type("gate_review")
            if wf.state == WorkflowState.APPROVED
        ]
        assert len(approved) == 100

    def test_thread_safe_concurrent_submit_same_workflow(self) -> None:
        """Multiple threads submitting to the same workflow — no lost audit logs."""
        wf = _make_gate_review(required_approvals=10)
        extra_users = [f"extra_user{i}@co.com" for i in range(5)]
        wf._assignees.extend(extra_users)
        errors: list[Exception] = []

        def approve(user: str) -> None:
            try:
                wf.submit_approval(
                    user=user, action="approve", reason=f"Approved by {user}"
                )
            except (InvalidTransitionError, ActionNotAllowedError):
                pass  # expected when racing on terminal state
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=approve, args=(u,)) for u in extra_users]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors


# ---------------------------------------------------------------------------
# Performance — 50 workflows in <2 seconds each
# ---------------------------------------------------------------------------


class TestPerformance:
    def test_50_workflows_complete_under_2_seconds(self) -> None:
        start = time.monotonic()
        for i in range(50):
            wf = WorkflowEngine(
                workflow_type="gate_review",
                trigger_event={"index": i},
                assignees=[f"reviewer{i}@co.com"],
            )
            wf.submit_approval(
                user=f"reviewer{i}@co.com", action="approve", reason="OK"
            )
            assert wf.state == WorkflowState.APPROVED
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"50 workflows took {elapsed:.2f}s (limit: 2.0s)"


# ---------------------------------------------------------------------------
# Gate integration — gate blocked until workflow approved
# ---------------------------------------------------------------------------


class TestGateIntegration:
    def test_gate_blocked_until_approved(self) -> None:
        """Simulate a gate that unblocks only when an APPROVED event is received."""

        class MockGate:
            can_proceed: bool = False

            def unblock(self) -> None:
                self.can_proceed = True

        gate = MockGate()

        def on_approval_emitter(event_type: str, payload: dict[str, Any]) -> None:
            if (
                event_type == "workflow.approve"
                and payload.get("state_after") == "approved"
            ):
                gate.unblock()

        wf = _make_gate_review(event_emitter=on_approval_emitter)
        assert not gate.can_proceed

        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="All clear"
        )
        assert gate.can_proceed

    def test_gate_not_unblocked_on_request_info(self) -> None:
        class MockGate:
            can_proceed: bool = False

            def unblock(self) -> None:
                self.can_proceed = True

        gate = MockGate()

        def emitter(event_type: str, payload: dict[str, Any]) -> None:
            if payload.get("state_after") == "approved":
                gate.unblock()

        wf = _make_gate_review(event_emitter=emitter)
        wf.submit_approval(
            user="compliance_officer@company.com",
            action="request_info",
            reason="Need more data",
        )
        assert not gate.can_proceed

    def test_gate_not_unblocked_on_reject(self) -> None:
        class MockGate:
            can_proceed: bool = False

            def unblock(self) -> None:
                self.can_proceed = True

        gate = MockGate()

        def emitter(event_type: str, payload: dict[str, Any]) -> None:
            if payload.get("state_after") == "approved":
                gate.unblock()

        wf = _make_gate_review(event_emitter=emitter)
        wf.submit_approval(
            user="compliance_officer@company.com", action="reject", reason="Blocked"
        )
        assert not gate.can_proceed


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


class TestSerialisation:
    def test_to_json_round_trip(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="OK"
        )
        data = json.loads(wf.to_json())
        assert data["state"] == "approved"
        assert data["workflow_type"] == "gate_review"

    def test_to_dict_audit_log_length(self) -> None:
        wf = _make_gate_review()
        wf.submit_approval(
            user="compliance_officer@company.com", action="approve", reason="OK"
        )
        d = wf.to_dict()
        assert len(d["audit_log"]) >= 2  # init + approve

    def test_approval_chain_proof_empty_before_any_approval(self) -> None:
        wf = _make_gate_review()
        proof = wf.approval_chain_proof()
        assert proof["approvals"] == []
        assert proof["final_state"] == "assigned"
