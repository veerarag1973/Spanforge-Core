"""Tests for Phase 10 features: evaluators, Gemini/Bedrock, Presidio, CLI commands."""

from __future__ import annotations

import json
import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from spanforge import Event, EventType, Tags
from spanforge.eval import (
    EvalRunner,
    EvalScore,
    FaithfulnessScorer,
    PIILeakageScorer,
    RefusalDetectionScorer,
)


# ---------------------------------------------------------------------------
# Helper: create a minimal event for testing
# ---------------------------------------------------------------------------


def _simple_event(payload: dict[str, Any]) -> Event:
    return Event(
        event_type=EventType.TRACE_SPAN_COMPLETED,
        source="test",
        payload=payload,
        tags=Tags(env="test"),
    )


# ===========================================================================
# FaithfulnessScorer
# ===========================================================================


@pytest.mark.unit
class TestFaithfulnessScorer:
    def test_high_overlap_returns_high_score(self) -> None:
        scorer = FaithfulnessScorer()
        score = scorer.score({
            "output": "Paris is the capital of France.",
            "context": "France is a country in Europe. Its capital is Paris.",
        })
        assert score.metric == "faithfulness"
        assert score.value > 0.5
        assert score.label == "pass"

    def test_no_overlap_returns_low_score(self) -> None:
        scorer = FaithfulnessScorer()
        score = scorer.score({
            "output": "Bananas can photosynthesise underwater.",
            "context": "The capital of France is Paris.",
        })
        assert score.value < 0.5
        assert score.label == "fail"

    def test_missing_context_returns_skip(self) -> None:
        scorer = FaithfulnessScorer()
        score = scorer.score({"output": "Hello world"})
        assert score.value == 0.0
        assert score.label == "skip"

    def test_empty_output_returns_skip(self) -> None:
        scorer = FaithfulnessScorer()
        score = scorer.score({"output": "", "context": "Some context"})
        assert score.value == 0.0
        assert score.label == "skip"

    def test_span_ids_propagated(self) -> None:
        scorer = FaithfulnessScorer()
        score = scorer.score({
            "output": "Paris is capital",
            "context": "Capital is Paris",
            "span_id": "abcdef0123456789",
            "trace_id": "abcdef0123456789abcdef0123456789",
        })
        assert score.span_id == "abcdef0123456789"
        assert score.trace_id == "abcdef0123456789abcdef0123456789"

    def test_metric_name_attribute(self) -> None:
        assert FaithfulnessScorer().metric_name == "faithfulness"

    def test_perfect_overlap(self) -> None:
        scorer = FaithfulnessScorer()
        score = scorer.score({
            "output": "The quick brown fox",
            "context": "The quick brown fox jumps over the lazy dog",
        })
        assert score.value == 1.0
        assert score.label == "pass"


# ===========================================================================
# RefusalDetectionScorer
# ===========================================================================


@pytest.mark.unit
class TestRefusalDetectionScorer:
    def test_detects_apology_refusal(self) -> None:
        scorer = RefusalDetectionScorer()
        score = scorer.score({"output": "I'm sorry, but I can't help with that."})
        assert score.value == 1.0
        assert score.label == "refusal"

    def test_detects_ai_identity_refusal(self) -> None:
        scorer = RefusalDetectionScorer()
        score = scorer.score({"output": "As an AI, I must be transparent about my limitations."})
        assert score.value == 1.0
        assert score.label == "refusal"

    def test_no_refusal_for_normal_output(self) -> None:
        scorer = RefusalDetectionScorer()
        score = scorer.score({"output": "The capital of France is Paris."})
        assert score.value == 0.0
        assert score.label == "pass"

    def test_detects_cannot_refusal(self) -> None:
        scorer = RefusalDetectionScorer()
        score = scorer.score({"output": "I cannot assist with creating malware."})
        assert score.value == 1.0

    def test_case_insensitive_detection(self) -> None:
        scorer = RefusalDetectionScorer()
        score = scorer.score({"output": "I CANNOT help with that request."})
        assert score.value == 1.0

    def test_empty_output_is_not_refusal(self) -> None:
        scorer = RefusalDetectionScorer()
        score = scorer.score({"output": ""})
        assert score.value == 0.0

    def test_metric_name_attribute(self) -> None:
        assert RefusalDetectionScorer().metric_name == "refusal_detection"


# ===========================================================================
# PIILeakageScorer
# ===========================================================================


@pytest.mark.unit
class TestPIILeakageScorer:
    def test_detects_email_leak(self) -> None:
        scorer = PIILeakageScorer()
        score = scorer.score({"output": "Contact alice@example.com for help."})
        assert score.value == 1.0
        assert score.label == "leak"
        assert score.metadata is not None
        assert score.metadata["hit_count"] > 0

    def test_detects_ssn_leak(self) -> None:
        scorer = PIILeakageScorer()
        score = scorer.score({"output": "SSN is 123-45-6789."})
        assert score.value == 1.0

    def test_clean_output_passes(self) -> None:
        scorer = PIILeakageScorer()
        score = scorer.score({"output": "The weather is nice today."})
        assert score.value == 0.0
        assert score.label == "pass"
        assert score.metadata is None

    def test_empty_output_is_clean(self) -> None:
        scorer = PIILeakageScorer()
        score = scorer.score({"output": ""})
        assert score.value == 0.0

    def test_metric_name_attribute(self) -> None:
        assert PIILeakageScorer().metric_name == "pii_leakage"


# ===========================================================================
# EvalRunner with built-in scorers
# ===========================================================================


@pytest.mark.unit
class TestEvalRunnerBuiltinScorers:
    def test_run_all_scorers_over_dataset(self) -> None:
        runner = EvalRunner(
            scorers=[
                FaithfulnessScorer(),
                RefusalDetectionScorer(),
                PIILeakageScorer(),
            ],
            emit=False,
        )
        dataset = [
            {"output": "Paris is the capital", "context": "Capital of France is Paris"},
            {"output": "I'm sorry, but I can't help with that."},
            {"output": "Call me at alice@example.com"},
        ]
        report = runner.run(dataset)
        # 3 examples × 3 scorers = 9 scores
        assert len(report.scores) == 9
        summary = report.summary()
        assert "faithfulness" in summary
        assert "refusal_detection" in summary
        assert "pii_leakage" in summary

    def test_runner_handles_empty_dataset(self) -> None:
        runner = EvalRunner(scorers=[FaithfulnessScorer()], emit=False)
        report = runner.run([])
        assert len(report.scores) == 0
        assert report.summary() == {}


# ===========================================================================
# Gemini integration
# ===========================================================================


@pytest.mark.unit
class TestGeminiIntegration:
    def test_normalize_response(self) -> None:
        from spanforge.integrations.gemini import normalize_response

        # Mock response with usage_metadata
        response = MagicMock()
        response.usage_metadata.prompt_token_count = 50
        response.usage_metadata.candidates_token_count = 100
        response.usage_metadata.cached_content_token_count = None

        tok, model, cost = normalize_response(response, model_name="gemini-1.5-pro")
        assert tok.input_tokens == 50
        assert tok.output_tokens == 100
        assert tok.total_tokens == 150
        assert model.name == "gemini-1.5-pro"
        assert cost.total_cost_usd > 0

    def test_normalize_response_unknown_model(self) -> None:
        from spanforge.integrations.gemini import normalize_response

        response = MagicMock()
        response.usage_metadata.prompt_token_count = 10
        response.usage_metadata.candidates_token_count = 20
        response.usage_metadata.cached_content_token_count = None

        tok, model, cost = normalize_response(response, model_name="custom-model")
        assert tok.input_tokens == 10
        assert cost.total_cost_usd == 0.0

    def test_normalize_strips_models_prefix(self) -> None:
        from spanforge.integrations.gemini import normalize_response

        response = MagicMock()
        response.usage_metadata.prompt_token_count = 10
        response.usage_metadata.candidates_token_count = 20
        response.usage_metadata.cached_content_token_count = None

        _, model, _ = normalize_response(response, model_name="models/gemini-1.5-flash")
        assert model.name == "gemini-1.5-flash"

    def test_list_models(self) -> None:
        from spanforge.integrations.gemini import list_models

        models = list_models()
        assert "gemini-1.5-pro" in models
        assert "gemini-2.0-flash" in models

    def test_pricing_lookup(self) -> None:
        from spanforge.integrations.gemini import _get_pricing

        pricing = _get_pricing("gemini-1.5-pro")
        assert pricing is not None
        assert "input" in pricing
        assert "output" in pricing

    def test_pricing_unknown_model(self) -> None:
        from spanforge.integrations.gemini import _get_pricing

        assert _get_pricing("nonexistent-model") is None

    def test_is_patched_returns_false_by_default(self) -> None:
        from spanforge.integrations.gemini import is_patched

        # May raise ImportError or return False depending on environment
        try:
            assert is_patched() is False
        except (ImportError, AttributeError):
            pytest.skip("google-generativeai not properly installed")


# ===========================================================================
# Bedrock integration
# ===========================================================================


@pytest.mark.unit
class TestBedrockIntegration:
    def test_normalize_converse_response(self) -> None:
        from spanforge.integrations.bedrock import normalize_converse_response

        response = {
            "usage": {
                "inputTokens": 100,
                "outputTokens": 200,
            },
        }
        tok, model, cost = normalize_converse_response(
            response, model_id="anthropic.claude-3-sonnet-20240229-v1:0",
        )
        assert tok.input_tokens == 100
        assert tok.output_tokens == 200
        assert tok.total_tokens == 300
        assert model.name == "anthropic.claude-3-sonnet-20240229-v1:0"
        assert cost.total_cost_usd > 0

    def test_normalize_empty_usage(self) -> None:
        from spanforge.integrations.bedrock import normalize_converse_response

        tok, _, cost = normalize_converse_response({}, model_id="unknown")
        assert tok.input_tokens == 0
        assert tok.output_tokens == 0
        assert cost.total_cost_usd == 0.0

    def test_list_models(self) -> None:
        from spanforge.integrations.bedrock import list_models

        models = list_models()
        assert any("anthropic" in m for m in models)
        assert any("amazon" in m for m in models)

    def test_pricing_lookup(self) -> None:
        from spanforge.integrations.bedrock import _get_pricing

        pricing = _get_pricing("anthropic.claude-3-sonnet-20240229-v1:0")
        assert pricing is not None

    def test_pricing_prefix_match(self) -> None:
        from spanforge.integrations.bedrock import _get_pricing

        # Should match via prefix stripping
        pricing = _get_pricing("anthropic.claude-3-haiku-20240307-v1")
        assert pricing is not None

    def test_is_patched_initially_false(self) -> None:
        from spanforge.integrations.bedrock import is_patched

        assert is_patched() is False


# ===========================================================================
# Presidio backend
# ===========================================================================


@pytest.mark.unit
class TestPresidioBackend:
    def test_is_available_false_when_not_installed(self) -> None:
        from spanforge.presidio_backend import is_available

        # presidio-analyzer is not installed in dev, so this should be False
        # (unless test env has it, in which case we just verify the function works)
        result = is_available()
        assert isinstance(result, bool)

    def test_import_error_on_scan_without_package(self) -> None:
        from spanforge.presidio_backend import is_available, presidio_scan_payload

        if not is_available():
            with pytest.raises(ImportError, match="presidio-analyzer"):
                presidio_scan_payload({"test": "hello"})


# ===========================================================================
# CLI: eval save / eval run
# ===========================================================================


@pytest.mark.unit
class TestEvalCLI:
    def test_eval_save_creates_dataset(self, tmp_path: Any) -> None:
        from spanforge._cli import main

        # Create input JSONL
        events_file = tmp_path / "events.jsonl"
        events = [
            {"payload": {"output": "Paris", "context": "Capital is Paris"}, "span_id": "abc"},
            {"payload": {"response": "Hello", "input": "Hi"}},
        ]
        events_file.write_text(
            "\n".join(json.dumps(e) for e in events),
            encoding="utf-8",
        )

        output_file = tmp_path / "dataset.jsonl"
        with pytest.raises(SystemExit) as exc_info:
            main(["eval", "save", "--input", str(events_file), "--output", str(output_file)])
        assert exc_info.value.code == 0
        assert output_file.exists()

        lines = output_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert "output" in first

    def test_eval_run_produces_summary(self, tmp_path: Any) -> None:
        from spanforge._cli import main

        dataset_file = tmp_path / "dataset.jsonl"
        examples = [
            {"output": "Paris is the capital", "context": "Capital of France is Paris"},
            {"output": "I'm sorry, but I can't do that."},
        ]
        dataset_file.write_text(
            "\n".join(json.dumps(e) for e in examples),
            encoding="utf-8",
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["eval", "run", "--file", str(dataset_file)])
        assert exc_info.value.code == 0

    def test_eval_run_json_format(self, tmp_path: Any) -> None:
        from spanforge._cli import main

        dataset_file = tmp_path / "dataset.jsonl"
        dataset_file.write_text(
            json.dumps({"output": "Hello world"}),
            encoding="utf-8",
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["eval", "run", "--file", str(dataset_file), "--format", "json"])
        assert exc_info.value.code == 0

    def test_eval_run_specific_scorers(self, tmp_path: Any) -> None:
        from spanforge._cli import main

        dataset_file = tmp_path / "dataset.jsonl"
        dataset_file.write_text(
            json.dumps({"output": "Hello world"}),
            encoding="utf-8",
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["eval", "run", "--file", str(dataset_file), "--scorers", "refusal,pii_leakage"])
        assert exc_info.value.code == 0

    def test_eval_run_unknown_scorer(self, tmp_path: Any) -> None:
        from spanforge._cli import main

        dataset_file = tmp_path / "dataset.jsonl"
        dataset_file.write_text(
            json.dumps({"output": "Hello"}),
            encoding="utf-8",
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["eval", "run", "--file", str(dataset_file), "--scorers", "nonexistent"])
        assert exc_info.value.code == 1

    def test_eval_save_missing_input(self, tmp_path: Any) -> None:
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["eval", "save", "--input", str(tmp_path / "missing.jsonl")])
        assert exc_info.value.code == 1

    def test_eval_run_missing_file(self, tmp_path: Any) -> None:
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["eval", "run", "--file", str(tmp_path / "missing.jsonl")])
        assert exc_info.value.code == 1


# ===========================================================================
# CLI: compliance status
# ===========================================================================


@pytest.mark.unit
class TestComplianceStatusCLI:
    def test_compliance_status_output(self, tmp_path: Any) -> None:
        from spanforge._cli import main

        events_file = tmp_path / "events.jsonl"
        events = [
            {
                "event_id": "01TESTID000001",
                "event_type": "llm.compliance.attestation.generated",
                "source": "test",
                "schema_version": "2.0",
                "timestamp": "2025-01-01T00:00:00Z",
                "payload": {"key": "value"},
            },
        ]
        events_file.write_text(
            "\n".join(json.dumps(e) for e in events),
            encoding="utf-8",
        )

        with pytest.raises(SystemExit) as exc_info:
            main(["compliance", "status", "--events-file", str(events_file)])
        assert exc_info.value.code == 0

    def test_compliance_status_missing_file(self, tmp_path: Any) -> None:
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["compliance", "status", "--events-file", str(tmp_path / "missing.jsonl")])
        assert exc_info.value.code == 2


# ===========================================================================
# CLI: migrate-langsmith
# ===========================================================================


@pytest.mark.unit
class TestMigrateLangsmithCLI:
    def test_migrate_langsmith_jsonl(self, tmp_path: Any) -> None:
        from spanforge._cli import main

        # Create a fake LangSmith export
        runs = [
            {
                "id": "run-001",
                "name": "ChatModel",
                "run_type": "llm",
                "inputs": {"messages": [{"role": "user", "content": "Hi"}]},
                "outputs": {"generations": [{"text": "Hello!"}]},
                "start_time": "2025-01-01T00:00:00Z",
                "end_time": "2025-01-01T00:00:01Z",
                "total_tokens": 50,
                "prompt_tokens": 20,
                "completion_tokens": 30,
                "status": "success",
                "trace_id": "trace-001",
            },
            {
                "id": "run-002",
                "name": "ToolCall",
                "run_type": "tool",
                "inputs": {"query": "weather"},
                "outputs": {"result": "sunny"},
                "total_tokens": 0,
                "status": "success",
                "trace_id": "trace-001",
                "parent_run_id": "run-001",
            },
        ]
        export_file = tmp_path / "langsmith_export.jsonl"
        export_file.write_text(
            "\n".join(json.dumps(r) for r in runs),
            encoding="utf-8",
        )

        output_file = tmp_path / "output.jsonl"
        with pytest.raises(SystemExit) as exc_info:
            main(["migrate-langsmith", str(export_file), "--output", str(output_file)])
        assert exc_info.value.code == 0
        assert output_file.exists()

        lines = output_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["event_type"] == EventType.TRACE_SPAN_COMPLETED.value
        assert first["payload"]["span_name"] == "ChatModel"
        assert first["payload"]["token_usage"]["input_tokens"] == 20

    def test_migrate_langsmith_json_array(self, tmp_path: Any) -> None:
        from spanforge._cli import main

        runs = [{"id": "r1", "name": "test", "run_type": "chain", "status": "ok"}]
        export_file = tmp_path / "export.json"
        export_file.write_text(json.dumps(runs), encoding="utf-8")

        output_file = tmp_path / "output.jsonl"
        with pytest.raises(SystemExit) as exc_info:
            main(["migrate-langsmith", str(export_file), "--output", str(output_file)])
        assert exc_info.value.code == 0

        lines = output_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1

    def test_migrate_langsmith_missing_file(self, tmp_path: Any) -> None:
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["migrate-langsmith", str(tmp_path / "missing.jsonl")])
        assert exc_info.value.code == 2

    def test_migrate_langsmith_empty_file(self, tmp_path: Any) -> None:
        from spanforge._cli import main

        empty_file = tmp_path / "empty.jsonl"
        empty_file.write_text("", encoding="utf-8")

        with pytest.raises(SystemExit) as exc_info:
            main(["migrate-langsmith", str(empty_file)])
        assert exc_info.value.code == 1


# ===========================================================================
# scan_raw=True default
# ===========================================================================


@pytest.mark.unit
class TestScanRawDefault:
    def test_contains_pii_now_scans_raw_by_default(self) -> None:
        """Verify scan_raw=True catches raw PII strings."""
        from spanforge.redact import contains_pii

        event = _simple_event({"email": "alice@example.com"})
        # With the default now True, raw strings should be scanned
        assert contains_pii(event) is True

    def test_contains_pii_opt_out_scan_raw(self) -> None:
        """Verify explicit scan_raw=False disables raw scanning."""
        from spanforge.redact import contains_pii

        event = _simple_event({"email": "alice@example.com"})
        # Opting out should not scan raw strings
        assert contains_pii(event, scan_raw=False) is False

    def test_assert_redacted_now_scans_raw_by_default(self) -> None:
        from spanforge.redact import PIINotRedactedError, assert_redacted

        event = _simple_event({"ssn": "123-45-6789"})
        with pytest.raises(PIINotRedactedError):
            assert_redacted(event)

    def test_assert_redacted_opt_out(self) -> None:
        from spanforge.redact import assert_redacted

        event = _simple_event({"ssn": "123-45-6789"})
        # Should not raise with scan_raw=False (no Redactable wrappers)
        assert_redacted(event, scan_raw=False)


# ===========================================================================
# GenAISystem.GOOGLE enum value
# ===========================================================================


@pytest.mark.unit
class TestGenAISystemGoogle:
    def test_google_enum_exists(self) -> None:
        from spanforge.namespaces.trace import GenAISystem

        assert GenAISystem.GOOGLE.value == "google"
