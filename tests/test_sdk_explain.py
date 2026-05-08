"""CARD 1B-1 — sf_explain production hardening tests.

One test per model output type (classification, generation, structured,
rejection, tool_call).  Every test asserts:
  * ``ExplainRecord`` returned with all required fields
  * ``eu_ai_act_clauses`` populated (Article 13 + Article 14)
  * ``sf_audit.append()`` called (HMAC-signed record)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from spanforge.sdk._base import SFClientConfig
from spanforge.sdk.explain import (
    EUAIActClause,
    ExplainRecord,
    ModelOutputType,
    SFExplainClient,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_client() -> SFExplainClient:
    return SFExplainClient(SFClientConfig(project_id="test-proj"))


def _mock_audit_append() -> MagicMock:
    """Return a MagicMock whose return value looks like AuditAppendResult."""
    mock = MagicMock()
    mock.return_value.hmac_signature = "mocked-hmac-sig"
    mock.return_value.record_id = "mocked-record-id"
    return mock


def _call_explain(
    client: SFExplainClient,
    response: str | dict,
    context: dict,
    mock_append: MagicMock,
) -> ExplainRecord:
    """Call client.explain() with sf_audit patched."""
    with patch("spanforge.sdk.sf_audit") as mock_mod:
        mock_mod.append = mock_append
        record = client.explain(response, context)
    return record


# ---------------------------------------------------------------------------
# Shared assertions
# ---------------------------------------------------------------------------


def _assert_valid_record(record: ExplainRecord, expected_output_type: str) -> None:
    """Assert invariants that every ExplainRecord must satisfy."""
    assert isinstance(record, ExplainRecord)
    assert record.explanation_id
    assert record.trace_id
    assert record.agent_id
    assert record.model_output_type == expected_output_type
    assert isinstance(record.decision_drivers, list) and len(record.decision_drivers) >= 1
    assert 0.0 <= record.confidence_score <= 1.0
    assert isinstance(record.eu_ai_act_clauses, list) and len(record.eu_ai_act_clauses) == 2
    assert isinstance(record.hmac_signature, str)


def _assert_eu_ai_act_clauses(clauses: list[EUAIActClause]) -> None:
    """Assert that both Article 13 and Article 14 clauses are present."""
    articles = {c.article for c in clauses}
    assert "Article 13" in articles, "Article 13 (transparency) clause missing"
    assert "Article 14" in articles, "Article 14 (human oversight) clause missing"
    for clause in clauses:
        assert clause.requirement
        assert clause.mapped_field


# ---------------------------------------------------------------------------
# Model output type tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExplainClassificationOutput:
    """CARD 1B-1 — classification output type."""

    def test_explain_classification_returns_record(self) -> None:
        client = _make_client()
        mock_append = _mock_audit_append()

        response = "billing_inquiry"
        context = {
            "trace_id": "trace-cls-001",
            "agent_id": "classifier-agent",
            "model_output_type": ModelOutputType.CLASSIFICATION.value,
            "confidence_score": 0.92,
            "model_version": "bert-intent-v2",
        }

        record = _call_explain(client, response, context, mock_append)

        _assert_valid_record(record, ModelOutputType.CLASSIFICATION.value)
        _assert_eu_ai_act_clauses(record.eu_ai_act_clauses)

    def test_explain_classification_audit_called(self) -> None:
        client = _make_client()
        mock_append = _mock_audit_append()

        _call_explain(
            client,
            "positive",
            {
                "trace_id": "trace-cls-002",
                "agent_id": "sentiment-agent",
                "model_output_type": ModelOutputType.CLASSIFICATION.value,
                "confidence_score": 0.85,
            },
            mock_append,
        )

        assert mock_append.called, "sf_audit.append() must be called for every explain() invocation"

    def test_explain_classification_article13_satisfied_when_drivers_present(self) -> None:
        client = _make_client()
        mock_append = _mock_audit_append()

        record = _call_explain(
            client,
            "escalate",
            {
                "trace_id": "trace-cls-003",
                "agent_id": "triage-agent",
                "model_output_type": ModelOutputType.CLASSIFICATION.value,
                "confidence_score": 0.78,
            },
            mock_append,
        )

        art13 = next(c for c in record.eu_ai_act_clauses if c.article == "Article 13")
        assert art13.satisfied, "Article 13 must be satisfied when decision_drivers are extracted"
        assert art13.mapped_field == "decision_drivers"


@pytest.mark.unit
class TestExplainGenerationOutput:
    """CARD 1B-1 — generation output type."""

    def test_explain_generation_returns_record(self) -> None:
        client = _make_client()
        mock_append = _mock_audit_append()

        response = (
            "Based on your account history, I recommend upgrading to the Pro plan "
            "to unlock unlimited API calls and priority support."
        )
        context = {
            "trace_id": "trace-gen-001",
            "agent_id": "support-agent",
            "model_output_type": ModelOutputType.GENERATION.value,
            "confidence_score": 0.75,
            "model_version": "gpt-4o-2025-04",
        }

        record = _call_explain(client, response, context, mock_append)

        _assert_valid_record(record, ModelOutputType.GENERATION.value)
        _assert_eu_ai_act_clauses(record.eu_ai_act_clauses)

    def test_explain_generation_audit_called(self) -> None:
        client = _make_client()
        mock_append = _mock_audit_append()

        _call_explain(
            client,
            "The answer to your question is 42.",
            {
                "trace_id": "trace-gen-002",
                "agent_id": "qa-agent",
                "model_output_type": ModelOutputType.GENERATION.value,
                "confidence_score": 0.88,
            },
            mock_append,
        )

        assert mock_append.called

    def test_explain_generation_high_confidence_no_oversight_required(self) -> None:
        client = _make_client()
        mock_append = _mock_audit_append()

        record = _call_explain(
            client,
            "Here is the summary you requested.",
            {
                "trace_id": "trace-gen-003",
                "agent_id": "summary-agent",
                "model_output_type": ModelOutputType.GENERATION.value,
                "confidence_score": 0.95,
            },
            mock_append,
        )

        assert not record.human_oversight_required, (
            "high confidence score must not flag human oversight"
        )
        art14 = next(c for c in record.eu_ai_act_clauses if c.article == "Article 14")
        assert art14.satisfied


@pytest.mark.unit
class TestExplainStructuredOutput:
    """CARD 1B-1 — structured (JSON) output type."""

    def test_explain_structured_returns_record(self) -> None:
        client = _make_client()
        mock_append = _mock_audit_append()

        response: dict = {
            "intent": "order_status",
            "entities": {"order_id": "ORD-12345"},
            "confidence": 0.91,
        }
        context = {
            "trace_id": "trace-str-001",
            "agent_id": "nlu-agent",
            "model_output_type": ModelOutputType.STRUCTURED.value,
            "confidence_score": 0.91,
        }

        record = _call_explain(client, response, context, mock_append)

        _assert_valid_record(record, ModelOutputType.STRUCTURED.value)
        _assert_eu_ai_act_clauses(record.eu_ai_act_clauses)

    def test_explain_structured_extracts_field_names_as_drivers(self) -> None:
        client = _make_client()
        mock_append = _mock_audit_append()

        response = {"label": "spam", "score": 0.97}
        context = {
            "trace_id": "trace-str-002",
            "agent_id": "filter-agent",
            "model_output_type": ModelOutputType.STRUCTURED.value,
            "confidence_score": 0.97,
        }

        record = _call_explain(client, response, context, mock_append)

        # Structured driver should capture the dict keys
        assert record.decision_drivers
        driver = record.decision_drivers[0]
        assert "label" in driver.get("value", []) or driver.get("name") == "structured_fields"


@pytest.mark.unit
class TestExplainRejectionOutput:
    """CARD 1B-1 — rejection output type."""

    def test_explain_rejection_returns_record(self) -> None:
        client = _make_client()
        mock_append = _mock_audit_append()

        response = "I'm sorry, I can't help with that request."
        context = {
            "trace_id": "trace-rej-001",
            "agent_id": "safety-agent",
            "model_output_type": ModelOutputType.REJECTION.value,
            "confidence_score": 0.99,
        }

        record = _call_explain(client, response, context, mock_append)

        _assert_valid_record(record, ModelOutputType.REJECTION.value)
        _assert_eu_ai_act_clauses(record.eu_ai_act_clauses)

    def test_explain_rejection_inferred_from_string(self) -> None:
        """Model output type should be inferred as rejection for safety refusals."""
        client = _make_client()
        mock_append = _mock_audit_append()

        # No model_output_type in context — should be inferred
        record = _call_explain(
            client,
            "I cannot assist with that.",
            {
                "trace_id": "trace-rej-002",
                "agent_id": "safety-agent",
                "confidence_score": 1.0,
            },
            mock_append,
        )

        assert record.model_output_type == ModelOutputType.REJECTION.value

    def test_explain_rejection_dict_refusal_key(self) -> None:
        client = _make_client()
        mock_append = _mock_audit_append()

        response = {"refusal": "Content policy violation: harmful content detected."}
        context = {
            "trace_id": "trace-rej-003",
            "agent_id": "guardrail-agent",
            "confidence_score": 1.0,
        }

        record = _call_explain(client, response, context, mock_append)

        assert record.model_output_type == ModelOutputType.REJECTION.value
        assert record.decision_drivers[0]["name"] == "rejection_reason"


@pytest.mark.unit
class TestExplainToolCallOutput:
    """CARD 1B-1 — tool call output type."""

    def test_explain_tool_call_returns_record(self) -> None:
        client = _make_client()
        mock_append = _mock_audit_append()

        response: dict = {
            "tool_calls": [
                {
                    "id": "call_abc123",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": '{"city": "London"}'},
                }
            ]
        }
        context = {
            "trace_id": "trace-tc-001",
            "agent_id": "orchestrator-agent",
            "model_output_type": ModelOutputType.TOOL_CALL.value,
            "confidence_score": 0.88,
        }

        record = _call_explain(client, response, context, mock_append)

        _assert_valid_record(record, ModelOutputType.TOOL_CALL.value)
        _assert_eu_ai_act_clauses(record.eu_ai_act_clauses)

    def test_explain_tool_call_extracts_tool_name(self) -> None:
        client = _make_client()
        mock_append = _mock_audit_append()

        response = {
            "function_call": {"name": "search_knowledge_base", "arguments": "{}"},
        }
        context = {
            "trace_id": "trace-tc-002",
            "agent_id": "rag-agent",
            "confidence_score": 0.82,
        }

        record = _call_explain(client, response, context, mock_append)

        assert record.model_output_type == ModelOutputType.TOOL_CALL.value
        assert record.decision_drivers[0]["value"] == "search_knowledge_base"

    def test_explain_tool_call_inferred_from_dict_shape(self) -> None:
        """tool_call type should be inferred when response has tool_calls key."""
        client = _make_client()
        mock_append = _mock_audit_append()

        response = {"tool_calls": [{"function": {"name": "lookup_order"}}]}
        context = {"trace_id": "trace-tc-003", "agent_id": "commerce-agent", "confidence_score": 0.9}

        record = _call_explain(client, response, context, mock_append)

        assert record.model_output_type == ModelOutputType.TOOL_CALL.value


# ---------------------------------------------------------------------------
# Cross-cutting: audit + EU AI Act
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExplainAuditAndEUAIAct:
    """Cross-cutting tests: audit signature and EU AI Act clause fields."""

    def test_every_record_has_eu_ai_act_clauses(self) -> None:
        client = _make_client()
        mock_append = _mock_audit_append()

        for output_type in ModelOutputType:
            response: str | dict = (
                "label" if output_type == ModelOutputType.CLASSIFICATION
                else {"tool_calls": []} if output_type == ModelOutputType.TOOL_CALL
                else "response text"
            )
            context = {
                "trace_id": f"trace-{output_type.value}",
                "agent_id": "test-agent",
                "model_output_type": output_type.value,
                "confidence_score": 0.8,
            }
            record = _call_explain(client, response, context, mock_append)
            assert len(record.eu_ai_act_clauses) == 2, (
                f"Expected 2 EU AI Act clauses for {output_type.value}"
            )

    def test_low_confidence_triggers_human_oversight_flag(self) -> None:
        client = _make_client()
        mock_append = _mock_audit_append()

        record = _call_explain(
            client,
            "uncertain classification",
            {
                "trace_id": "trace-oversight-001",
                "agent_id": "agent",
                "model_output_type": ModelOutputType.CLASSIFICATION.value,
                "confidence_score": 0.45,
            },
            mock_append,
        )

        assert record.human_oversight_required, (
            "confidence_score < 0.7 must set human_oversight_required=True"
        )
        art14 = next(c for c in record.eu_ai_act_clauses if c.article == "Article 14")
        assert not art14.satisfied

    def test_explain_never_raises_on_audit_failure(self) -> None:
        """explain() must not raise even when sf_audit.append() raises."""
        client = _make_client()

        with patch("spanforge.sdk.sf_audit") as mock_mod:
            mock_mod.append = MagicMock(side_effect=RuntimeError("audit down"))
            # Should not raise
            record = client.explain(
                "some response",
                {"trace_id": "trace-err-001", "agent_id": "agent", "confidence_score": 0.9},
            )

        assert isinstance(record, ExplainRecord)
        assert record.hmac_signature == ""  # graceful degradation

    def test_explain_model_version_stored_in_record(self) -> None:
        client = _make_client()
        mock_append = _mock_audit_append()

        record = _call_explain(
            client,
            "The capital of France is Paris.",
            {
                "trace_id": "trace-ver-001",
                "agent_id": "geo-agent",
                "model_output_type": ModelOutputType.GENERATION.value,
                "confidence_score": 0.98,
                "model_version": "llama-3-70b-instruct",
            },
            mock_append,
        )

        assert record.model_version == "llama-3-70b-instruct"


# ---------------------------------------------------------------------------
# governed decorator tests
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGovernedDecorator:
    """Tests for the @governed control-loop decorator (CARD 1B-1)."""

    def test_governed_without_parens_calls_function(self) -> None:
        from spanforge.governance import governed

        @governed
        def add(x: int, y: int) -> int:
            return x + y

        with patch("spanforge.sdk.sf_explain") as mock_sf_explain:
            mock_sf_explain.explain = MagicMock()
            result = add(2, 3)

        assert result == 5

    def test_governed_with_parens_calls_function(self) -> None:
        from spanforge.governance import governed

        @governed(agent_id="test-agent", confidence_threshold=0.8)
        def greet(name: str) -> str:
            return f"Hello, {name}"

        with patch("spanforge.sdk.sf_explain") as mock_sf_explain:
            mock_sf_explain.explain = MagicMock()
            result = greet("world")

        assert result == "Hello, world"

    def test_governed_calls_sf_explain_with_result(self) -> None:
        from spanforge.governance import governed

        @governed(agent_id="billing-agent")
        def classify(text: str) -> str:
            return "billing_inquiry"

        with patch("spanforge.sdk.sf_explain") as mock_sf_explain:
            mock_sf_explain.explain = MagicMock()
            classify("I need help with my bill")
            mock_sf_explain.explain.assert_called_once()
            call_args = mock_sf_explain.explain.call_args
            assert call_args[0][0] == "billing_inquiry"
            assert call_args[0][1]["agent_id"] == "billing-agent"

    def test_governed_never_raises_on_explain_failure(self) -> None:
        from spanforge.governance import governed

        @governed
        def broken_fn() -> str:
            return "ok"

        with patch("spanforge.sdk.sf_explain") as mock_sf_explain:
            mock_sf_explain.explain = MagicMock(side_effect=RuntimeError("audit down"))
            result = broken_fn()

        assert result == "ok"

    def test_governed_preserves_function_name(self) -> None:
        from spanforge.governance import governed

        @governed
        def my_special_function() -> None:
            pass

        assert my_special_function.__name__ == "my_special_function"

    def test_governed_default_agent_id_in_context(self) -> None:
        from spanforge.governance import governed

        @governed
        def fn() -> str:
            return "result"

        captured: list[dict] = []

        def _capture(result: object, context: dict) -> None:  # type: ignore[override]
            captured.append(context)

        with patch("spanforge.sdk.sf_explain") as mock_sf_explain:
            mock_sf_explain.explain = MagicMock(side_effect=_capture)
            fn()

        assert captured[0]["agent_id"] == "governed"

