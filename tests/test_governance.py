"""Tests for spanforge.governance — EventGovernancePolicy, helpers, errors."""

from __future__ import annotations

import warnings
from typing import Any
from unittest.mock import MagicMock

import pytest

import spanforge.governance as gov_module
from spanforge.governance import (
    EventGovernancePolicy,
    GovernanceViolationError,
    GovernanceWarning,
    check_event,
    get_global_policy,
    set_global_policy,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_global_policy() -> None:
    """Restore the default global policy after every test."""
    yield
    set_global_policy(None)


def _make_event(event_type: str = "llm.trace.span.completed") -> MagicMock:
    ev = MagicMock()
    ev.event_type = event_type
    return ev


# ---------------------------------------------------------------------------
# GovernanceViolationError
# ---------------------------------------------------------------------------


class TestGovernanceViolationError:
    def test_attributes(self) -> None:
        err = GovernanceViolationError("llm.bad.type", "explicitly blocked")
        assert err.event_type == "llm.bad.type"
        assert err.reason == "explicitly blocked"

    def test_str_contains_event_type_and_reason(self) -> None:
        err = GovernanceViolationError("bad.type", "test reason")
        s = str(err)
        assert "bad.type" in s
        assert "test reason" in s

    def test_is_exception(self) -> None:
        assert isinstance(GovernanceViolationError("t", "r"), Exception)


# ---------------------------------------------------------------------------
# GovernanceWarning
# ---------------------------------------------------------------------------


class TestGovernanceWarning:
    def test_is_user_warning_subclass(self) -> None:
        assert issubclass(GovernanceWarning, UserWarning)

    def test_can_be_caught_as_warning(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            warnings.warn("test", GovernanceWarning)
        assert len(w) == 1
        assert issubclass(w[0].category, GovernanceWarning)


# ---------------------------------------------------------------------------
# EventGovernancePolicy — defaults
# ---------------------------------------------------------------------------


class TestPolicyDefaults:
    def test_empty_policy_allows_all_events(self) -> None:
        policy = EventGovernancePolicy()
        ev = _make_event()
        policy.check_event(ev)  # should not raise

    def test_default_no_blocked_types(self) -> None:
        policy = EventGovernancePolicy()
        assert len(policy.blocked_types) == 0

    def test_default_no_deprecated_types(self) -> None:
        policy = EventGovernancePolicy()
        assert len(policy.warn_deprecated) == 0

    def test_default_no_custom_rules(self) -> None:
        policy = EventGovernancePolicy()
        assert len(policy.custom_rules) == 0

    def test_default_strict_unknown_false(self) -> None:
        policy = EventGovernancePolicy()
        assert policy.strict_unknown is False


# ---------------------------------------------------------------------------
# blocked_types
# ---------------------------------------------------------------------------


class TestBlockedTypes:
    def test_blocked_type_raises_violation_error(self) -> None:
        policy = EventGovernancePolicy(blocked_types={"llm.bad.call"})
        ev = _make_event("llm.bad.call")
        with pytest.raises(GovernanceViolationError) as exc_info:
            policy.check_event(ev)
        assert exc_info.value.event_type == "llm.bad.call"

    def test_non_blocked_type_passes(self) -> None:
        policy = EventGovernancePolicy(blocked_types={"llm.bad.call"})
        ev = _make_event("llm.trace.span.completed")
        policy.check_event(ev)  # should not raise

    def test_multiple_blocked_types(self) -> None:
        policy = EventGovernancePolicy(blocked_types={"type.a", "type.b"})
        with pytest.raises(GovernanceViolationError):
            policy.check_event(_make_event("type.a"))
        with pytest.raises(GovernanceViolationError):
            policy.check_event(_make_event("type.b"))
        policy.check_event(_make_event("type.c"))  # should pass

    def test_violation_error_contains_reason(self) -> None:
        policy = EventGovernancePolicy(blocked_types={"blocked.type"})
        with pytest.raises(GovernanceViolationError) as exc_info:
            policy.check_event(_make_event("blocked.type"))
        assert "blocked_types" in exc_info.value.reason


# ---------------------------------------------------------------------------
# warn_deprecated
# ---------------------------------------------------------------------------


class TestWarnDeprecated:
    def test_deprecated_type_issues_governance_warning(self) -> None:
        policy = EventGovernancePolicy(warn_deprecated={"old.event"})
        ev = _make_event("old.event")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            policy.check_event(ev)
        assert len(w) == 1
        assert issubclass(w[0].category, GovernanceWarning)

    def test_non_deprecated_type_no_warning(self) -> None:
        policy = EventGovernancePolicy(warn_deprecated={"old.event"})
        ev = _make_event("new.event")
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            policy.check_event(ev)
        assert len(w) == 0

    def test_deprecated_type_passes_check_no_block(self) -> None:
        """Deprecated types issue a warning but are NOT blocked."""
        policy = EventGovernancePolicy(warn_deprecated={"old.event"})
        ev = _make_event("old.event")
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            policy.check_event(ev)  # must not raise


# ---------------------------------------------------------------------------
# custom_rules
# ---------------------------------------------------------------------------


class TestCustomRules:
    def test_custom_rule_returning_reason_blocks_event(self) -> None:
        def always_block(ev: Any) -> str | None:
            return "blocked by custom rule"

        policy = EventGovernancePolicy(custom_rules=[always_block])
        with pytest.raises(GovernanceViolationError) as exc_info:
            policy.check_event(_make_event())
        assert "blocked by custom rule" in exc_info.value.reason

    def test_custom_rule_returning_none_passes_event(self) -> None:
        def allow_all(ev: Any) -> str | None:
            return None

        policy = EventGovernancePolicy(custom_rules=[allow_all])
        policy.check_event(_make_event())  # should not raise

    def test_custom_rule_returning_empty_string_passes(self) -> None:
        def empty_reason(ev: Any) -> str | None:
            return ""

        policy = EventGovernancePolicy(custom_rules=[empty_reason])
        policy.check_event(_make_event())  # empty string = no block

    def test_multiple_custom_rules_first_block_wins(self) -> None:
        def rule1(ev: Any) -> str | None:
            return "rule1 blocked"

        def rule2(ev: Any) -> str | None:
            return "rule2 blocked"

        policy = EventGovernancePolicy(custom_rules=[rule1, rule2])
        with pytest.raises(GovernanceViolationError) as exc_info:
            policy.check_event(_make_event())
        assert "rule1 blocked" in exc_info.value.reason

    def test_custom_rule_receives_event_object(self) -> None:
        received_events: list[Any] = []

        def capture(ev: Any) -> str | None:
            received_events.append(ev)
            return None

        policy = EventGovernancePolicy(custom_rules=[capture])
        ev = _make_event("captured.type")
        policy.check_event(ev)
        assert len(received_events) == 1
        assert received_events[0] is ev


# ---------------------------------------------------------------------------
# Evaluation order: blocked > deprecated > custom_rules
# ---------------------------------------------------------------------------


class TestEvaluationOrder:
    def test_blocked_beats_deprecated(self) -> None:
        policy = EventGovernancePolicy(
            blocked_types={"t"},
            warn_deprecated={"t"},
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            with pytest.raises(GovernanceViolationError):
                policy.check_event(_make_event("t"))
        # Violation is raised before warning is issued
        assert len(w) == 0

    def test_deprecated_warning_before_custom_rules(self) -> None:
        """Deprecated warning is issued even when custom rules would also block."""
        issued_warnings: list[Any] = []

        def blocking_rule(ev: Any) -> str | None:
            return "custom block"

        policy = EventGovernancePolicy(
            warn_deprecated={"t"},
            custom_rules=[blocking_rule],
        )
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            with pytest.raises(GovernanceViolationError):
                policy.check_event(_make_event("t"))
        # Deprecated warning should have been issued before rule blocked
        assert len(w) == 1


# ---------------------------------------------------------------------------
# strict_unknown
# ---------------------------------------------------------------------------


class TestStrictUnknown:
    def test_strict_unknown_registered_type_passes(self) -> None:
        """When strict_unknown=True, registered EventType values should pass."""
        policy = EventGovernancePolicy(strict_unknown=True)
        # Use a known registered event type
        from spanforge import EventType
        ev = _make_event(list(EventType)[0].value)  # type: ignore[attr-defined]
        policy.check_event(ev)  # should not raise

    def test_strict_unknown_unregistered_type_blocked(self) -> None:
        policy = EventGovernancePolicy(strict_unknown=True)
        ev = _make_event("totally.unknown.event.type.xyz.abc")
        with pytest.raises(GovernanceViolationError) as exc_info:
            policy.check_event(ev)
        assert "strict_unknown" in exc_info.value.reason

    def test_strict_unknown_false_unknown_type_passes(self) -> None:
        policy = EventGovernancePolicy(strict_unknown=False)
        ev = _make_event("any.unregistered.type")
        policy.check_event(ev)  # should not raise


# ---------------------------------------------------------------------------
# Global policy helpers
# ---------------------------------------------------------------------------


class TestGlobalPolicy:
    def test_get_global_policy_returns_policy(self) -> None:
        p = get_global_policy()
        assert isinstance(p, EventGovernancePolicy)

    def test_set_global_policy_replaces_policy(self) -> None:
        new_policy = EventGovernancePolicy(blocked_types={"bad.t"})
        set_global_policy(new_policy)
        assert get_global_policy() is new_policy

    def test_set_global_policy_none_resets_to_default(self) -> None:
        set_global_policy(EventGovernancePolicy(blocked_types={"some.type"}))
        set_global_policy(None)
        p = get_global_policy()
        assert len(p.blocked_types) == 0

    def test_check_event_delegates_to_global_policy(self) -> None:
        set_global_policy(EventGovernancePolicy(blocked_types={"blocked.globally"}))
        with pytest.raises(GovernanceViolationError):
            check_event(_make_event("blocked.globally"))

    def test_check_event_passes_when_global_allows(self) -> None:
        set_global_policy(EventGovernancePolicy())
        check_event(_make_event("any.type"))  # should not raise

    def test_get_global_policy_same_instance_per_call(self) -> None:
        p1 = get_global_policy()
        p2 = get_global_policy()
        assert p1 is p2
