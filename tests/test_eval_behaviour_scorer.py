"""Tests for BehaviourScorer ABC added to spanforge.eval."""
from __future__ import annotations

from typing import Any

import pytest

from spanforge.eval import BehaviourScorer


class TestBehaviourScorerIsABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            BehaviourScorer()  # type: ignore[abstract]

    def test_subclass_without_score_raises(self):
        class Incomplete(BehaviourScorer):
            name = "incomplete"
            # score() not implemented

        with pytest.raises(TypeError):
            Incomplete()  # type: ignore[abstract]


class TestBehaviourScorerConcrete:
    def test_minimal_implementation(self):
        class ExactMatch(BehaviourScorer):
            name = "exact_match"

            def score(self, case: Any, response: str) -> tuple[float, str]:
                expected = case.get("expected", "")
                match = response.strip() == expected.strip()
                return (1.0 if match else 0.0, "match" if match else "no match")

        scorer = ExactMatch()
        assert scorer.name == "exact_match"
        score, reason = scorer.score({"expected": "Paris"}, "Paris")
        assert score == 1.0
        assert reason == "match"

    def test_returns_tuple_of_float_and_str(self):
        class AlwaysPasses(BehaviourScorer):
            name = "always_passes"

            def score(self, case: Any, response: str) -> tuple[float, str]:
                return (1.0, "always passes")

        scorer = AlwaysPasses()
        result = scorer.score({}, "any response")
        assert isinstance(result, tuple)
        assert len(result) == 2
        score, reason = result
        assert isinstance(score, float)
        assert isinstance(reason, str)

    def test_zero_score_for_failure(self):
        class AlwaysFails(BehaviourScorer):
            name = "always_fails"

            def score(self, case: Any, response: str) -> tuple[float, str]:
                return (0.0, "always fails")

        scorer = AlwaysFails()
        score, reason = scorer.score({}, "")
        assert score == 0.0
        assert reason == "always fails"

    def test_name_class_attribute_can_be_overridden(self):
        class CustomNamed(BehaviourScorer):
            name = "my-custom-scorer"

            def score(self, case: Any, response: str) -> tuple[float, str]:
                return (0.5, "partial")

        scorer = CustomNamed()
        assert scorer.name == "my-custom-scorer"

    def test_multiple_subclasses_independent(self):
        class ScorerA(BehaviourScorer):
            name = "scorer_a"

            def score(self, case: Any, response: str) -> tuple[float, str]:
                return (1.0, "a")

        class ScorerB(BehaviourScorer):
            name = "scorer_b"

            def score(self, case: Any, response: str) -> tuple[float, str]:
                return (0.0, "b")

        a = ScorerA()
        b = ScorerB()
        assert a.name != b.name
        assert a.score({}, "x") != b.score({}, "x")

    def test_scorer_accepts_complex_case(self):
        class ContainsScorer(BehaviourScorer):
            name = "contains"

            def score(self, case: Any, response: str) -> tuple[float, str]:
                keywords = case.get("keywords", [])
                hits = sum(1 for kw in keywords if kw.lower() in response.lower())
                ratio = hits / len(keywords) if keywords else 1.0
                return (ratio, f"{hits}/{len(keywords)} keywords found")

        scorer = ContainsScorer()
        case = {"keywords": ["Paris", "France", "capital"]}
        response = "Paris is the capital city of France."
        score, reason = scorer.score(case, response)
        assert score == pytest.approx(1.0)
        assert "3/3" in reason
