"""Tests for spanforge.types — EventType enum and namespace helpers.

100% coverage target.
"""

from __future__ import annotations

import pytest

from spanforge.exceptions import EventTypeError
from spanforge.types import (
    _RESERVED_NAMESPACES,
    EVENT_TYPE_PATTERN,
    EventType,
    get_by_value,
    is_registered,
    namespace_of,
    validate_custom,
)

# ---------------------------------------------------------------------------
# EventType enum membership
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEventTypeValues:
    def test_all_values_are_strings(self) -> None:
        for et in EventType:
            assert isinstance(et.value, str), f"{et.name} value is not a string"

    def test_all_values_match_pattern(self) -> None:
        import re  # noqa: PLC0415
        pattern = re.compile(EVENT_TYPE_PATTERN)
        for et in EventType:
            assert pattern.match(et.value), (
                f"{et.name} value {et.value!r} does not match pattern"
            )

    def test_no_duplicate_values(self) -> None:
        values = [et.value for et in EventType]
        assert len(values) == len(set(values)), "Duplicate EventType values detected"

    def test_enum_is_str_subclass(self) -> None:
        assert isinstance(EventType.TRACE_SPAN_COMPLETED, str)
        assert EventType.TRACE_SPAN_COMPLETED == "llm.trace.span.completed"

    def test_string_comparison(self) -> None:
        assert EventType.TRACE_SPAN_COMPLETED == "llm.trace.span.completed"
        assert EventType.TRACE_SPAN_COMPLETED == "llm.trace.span.completed"

    def test_total_count(self) -> None:
        """Ensure all 23 namespaces are represented (11 legacy llm.* + 12 RFC-0001 SPANFORGE)."""
        namespaces = {et.namespace for et in EventType}
        assert len(namespaces) == 23


# ---------------------------------------------------------------------------
# EventType.namespace property
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEventTypeNamespace:
    def test_trace_namespace(self) -> None:
        assert EventType.TRACE_SPAN_COMPLETED.namespace == "llm.trace"

    def test_diff_namespace(self) -> None:
        assert EventType.DIFF_COMPUTED.namespace == "llm.diff"

    def test_prompt_namespace(self) -> None:
        assert EventType.PROMPT_VERSION_CHANGED.namespace == "llm.prompt"

    def test_cost_namespace(self) -> None:
        assert EventType.COST_TOKEN_RECORDED.namespace == "llm.cost"

    def test_eval_namespace(self) -> None:
        assert EventType.EVAL_SCENARIO_COMPLETED.namespace == "llm.eval"

    def test_guard_namespace(self) -> None:
        assert EventType.GUARD_INPUT_BLOCKED.namespace == "llm.guard"

    def test_redact_namespace(self) -> None:
        assert EventType.REDACT_PII_DETECTED.namespace == "llm.redact"

    def test_fence_namespace(self) -> None:
        assert EventType.FENCE_VALIDATED.namespace == "llm.fence"

    def test_cache_namespace(self) -> None:
        assert EventType.CACHE_HIT.namespace == "llm.cache"

    def test_template_namespace(self) -> None:
        assert EventType.TEMPLATE_REGISTERED.namespace == "llm.template"


# ---------------------------------------------------------------------------
# EventType.tool property
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.skip(reason="et.tool property removed in v2.0; use et.description instead")
class TestEventTypeTool:
    def test_trace_tool(self) -> None:
        assert EventType.TRACE_SPAN_COMPLETED.tool == "llm-trace"

    def test_diff_tool(self) -> None:
        assert EventType.DIFF_COMPARISON_COMPLETED.tool == "llm-diff"

    def test_prompt_tool(self) -> None:
        assert EventType.PROMPT_SAVED.tool == "promptlock"

    def test_cost_tool(self) -> None:
        assert EventType.COST_BUDGET_EXCEEDED.tool == "llm-cost"

    def test_eval_tool(self) -> None:
        assert EventType.EVAL_REGRESSION_FAILED.tool == "evalkit"

    def test_guard_tool(self) -> None:
        assert EventType.GUARD_OUTPUT_FLAGGED.tool == "promptguard"

    def test_redact_tool(self) -> None:
        assert EventType.REDACT_SCAN_COMPLETED.tool == "llm-redact"

    def test_fence_tool(self) -> None:
        assert EventType.FENCE_RETRY_TRIGGERED.tool == "llm-fence"

    def test_cache_tool(self) -> None:
        assert EventType.CACHE_EVICTED.tool == "llm-cache"

    def test_template_tool(self) -> None:
        assert EventType.TEMPLATE_VARIABLE_MISSING.tool == "promptblock"


# ---------------------------------------------------------------------------
# EventType.description property
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEventTypeDescription:
    def test_all_have_non_empty_description(self) -> None:
        for et in EventType:
            assert et.description, f"{et.name} has an empty description"

    def test_description_is_string(self) -> None:
        for et in EventType:
            assert isinstance(et.description, str)


# ---------------------------------------------------------------------------
# __str__ / __eq__ / __hash__ — explicit overrides for Python 3.12+ compat
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEventTypeDunderMethods:
    def test_str_returns_value(self) -> None:
        """str() must return the canonical dot-separated string value."""
        assert str(EventType.TRACE_SPAN_COMPLETED) == "llm.trace.span.completed"
        assert str(EventType.CACHE_HIT) == "llm.cache.hit"

    def test_eq_with_non_string_returns_not_implemented(self) -> None:
        """__eq__ with a non-string must return NotImplemented (not False)."""
        result = EventType.__eq__(EventType.TRACE_SPAN_COMPLETED, 42)
        assert result is NotImplemented

    def test_eq_with_dict_returns_not_implemented(self) -> None:
        result = EventType.__eq__(EventType.CACHE_HIT, {"key": "value"})
        assert result is NotImplemented

    def test_hashable_in_set(self) -> None:
        """EventType instances must be usable as set members."""
        s = {EventType.TRACE_SPAN_COMPLETED, EventType.CACHE_HIT}
        assert len(s) == 2
        assert EventType.TRACE_SPAN_COMPLETED in s

    def test_hashable_as_dict_key(self) -> None:
        d = {EventType.TRACE_SPAN_COMPLETED: "value"}
        assert d[EventType.TRACE_SPAN_COMPLETED] == "value"

    def test_hash_consistent_with_string(self) -> None:
        """hash(EventType.X) must equal hash(EventType.X.value)."""
        et = EventType.TRACE_SPAN_COMPLETED
        assert hash(et) == hash(et.value)




@pytest.mark.unit
class TestKnownValues:
    """Hardcoded expected values — if these change, breaking change in schema."""

    def test_trace_span_completed(self) -> None:
        assert EventType.TRACE_SPAN_COMPLETED.value == "llm.trace.span.completed"

    def test_prompt_version_changed(self) -> None:
        assert EventType.PROMPT_VERSION_CHANGED.value == "llm.prompt.version.changed"

    def test_guard_input_blocked(self) -> None:
        assert EventType.GUARD_INPUT_BLOCKED.value == "llm.guard.input.blocked"

    def test_cache_hit(self) -> None:
        assert EventType.CACHE_HIT.value == "llm.cache.hit"

    def test_cost_token_recorded(self) -> None:
        assert EventType.COST_TOKEN_RECORDED.value == "llm.cost.token.recorded"


# ---------------------------------------------------------------------------
# is_registered
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsRegistered:
    def test_true_for_known_type(self) -> None:
        assert is_registered("llm.trace.span.completed") is True

    def test_false_for_unknown(self) -> None:
        assert is_registered("llm.unknown.thing.happened") is False

    def test_false_for_custom_prefix(self) -> None:
        assert is_registered("x.myco.trace.started") is False

    def test_all_event_types_registered(self) -> None:
        for et in EventType:
            assert is_registered(et.value), f"{et.name} not found by is_registered"

    def test_case_sensitive(self) -> None:
        assert is_registered("LLM.TRACE.SPAN.COMPLETED") is False


# ---------------------------------------------------------------------------
# namespace_of
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNamespaceOf:
    def test_known_type(self) -> None:
        assert namespace_of("llm.trace.span.completed") == "llm.trace"

    def test_custom_type(self) -> None:
        assert namespace_of("x.myco.inference.completed") == "x.myco"

    def test_raises_on_malformed(self) -> None:
        with pytest.raises(EventTypeError, match="does not match"):
            namespace_of("not-a-valid-type")

    def test_raises_on_too_short(self) -> None:
        with pytest.raises(EventTypeError):
            namespace_of("llm.trace")  # missing entity.action

    def test_all_event_types(self) -> None:
        from spanforge.types import RFC_SPANFORGE_NAMESPACES
        for et in EventType:
            ns = namespace_of(et.value)
            is_llm = ns.startswith("llm.")
            is_rfc = ns in RFC_SPANFORGE_NAMESPACES
            assert is_llm or is_rfc, f"{et.name} has unexpected namespace {ns!r}"

    def test_reserved_namespaces_set(self) -> None:
        # Legacy llm.* namespaces
        assert "llm.trace" in _RESERVED_NAMESPACES
        assert "llm.guard" in _RESERVED_NAMESPACES
        assert "llm.audit" in _RESERVED_NAMESPACES
        assert "llm.inspect" not in _RESERVED_NAMESPACES  # removed in v2.0
        # RFC-0001 SPANFORGE new namespaces
        assert "decision" in _RESERVED_NAMESPACES
        assert "tool_call" in _RESERVED_NAMESPACES
        assert "drift" in _RESERVED_NAMESPACES
        assert "hitl" in _RESERVED_NAMESPACES
        assert len(_RESERVED_NAMESPACES) == 23


# ---------------------------------------------------------------------------
# validate_custom
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateCustom:
    def test_valid_custom_type(self) -> None:
        validate_custom("x.mycompany.inference.completed")  # must not raise

    def test_valid_custom_type_with_numbers(self) -> None:
        validate_custom("x.acme2.tool3.started")

    def test_raises_on_reserved_namespace(self) -> None:
        with pytest.raises(EventTypeError, match="reserved"):
            validate_custom("llm.trace.custom.event")  # llm.trace is reserved

    def test_raises_on_unregistered_reserved_ns(self) -> None:
        """An unknown event type in a reserved namespace must be rejected."""
        with pytest.raises(EventTypeError, match="reserved"):
            validate_custom("llm.guard.new_unknown.event")

    def test_raises_on_malformed(self) -> None:
        with pytest.raises(EventTypeError, match="does not match"):
            validate_custom("INVALID TYPE")

    def test_raises_on_bare_x_prefix(self) -> None:
        """'x.event' without company qualifier is rejected."""
        with pytest.raises(EventTypeError):
            validate_custom("x.event")

    def test_allows_registered_first_party(self) -> None:
        """First-party registered types pass even though they're in reserved ns."""
        validate_custom("llm.trace.span.completed")

    def test_uppercase_first_party(self) -> None:
        """Uppercase reserved types are rejected (event types are lowercase)."""
        with pytest.raises(EventTypeError):
            validate_custom("LLM.trace.span.completed")


# ---------------------------------------------------------------------------
# get_by_value
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetByValue:
    def test_known_value(self) -> None:
        et = get_by_value("llm.trace.span.completed")
        assert et is EventType.TRACE_SPAN_COMPLETED

    def test_unknown_returns_none(self) -> None:
        assert get_by_value("llm.unknown.entity.action") is None

    def test_all_registered_types_found(self) -> None:
        for et in EventType:
            found = get_by_value(et.value)
            assert found is et, f"get_by_value failed for {et.name}"

    def test_empty_string_returns_none(self) -> None:
        assert get_by_value("") is None

    def test_custom_type_returns_none(self) -> None:
        assert get_by_value("x.myco.thing.happened") is None
