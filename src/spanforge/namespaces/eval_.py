"""spanforge.namespaces.eval_ — Evaluation payload types (RFC-0001).

Classes
-------
EvalScoreRecordedPayload        llm.eval.score.recorded
EvalRegressionDetectedPayload   llm.eval.regression.detected
EvalScenarioStartedPayload      llm.eval.scenario.started
EvalScenarioCompletedPayload    llm.eval.scenario.completed
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from spanforge.namespaces.trace import ModelInfo

__all__ = [
    "EvalRegressionDetectedPayload",
    "EvalScenarioCompletedPayload",
    "EvalScenarioStartedPayload",
    "EvalScoreRecordedPayload",
]

_VALID_SEVERITIES = frozenset({"low", "medium", "high", "critical"})
_VALID_STATUSES = frozenset({"passed", "failed", "error", "cancelled"})


@dataclass
class EvalScoreRecordedPayload:
    """RFC-0001 — A single evaluation score recorded for a subject event."""

    evaluator: str
    metric_name: str
    score: float
    score_min: float | None = None
    score_max: float | None = None
    threshold: float | None = None
    passed: bool | None = None
    subject_event_id: str | None = None
    subject_type: str | None = None
    eval_run_id: str | None = None
    rationale: str | None = None
    model: ModelInfo | None = None  # judge model

    def __post_init__(self) -> None:
        if not isinstance(self.evaluator, str) or not self.evaluator:
            raise ValueError("EvalScoreRecordedPayload.evaluator must be non-empty")
        if not isinstance(self.metric_name, str) or not self.metric_name:
            raise ValueError("EvalScoreRecordedPayload.metric_name must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "evaluator": self.evaluator,
            "metric_name": self.metric_name,
            "score": self.score,
        }
        for f in ("score_min", "score_max", "threshold", "passed",
                  "subject_event_id", "subject_type", "eval_run_id", "rationale"):
            v = getattr(self, f)
            if v is not None:
                d[f] = v
        if self.model is not None:
            d["model"] = self.model.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalScoreRecordedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            evaluator=data["evaluator"],
            metric_name=data["metric_name"],
            score=float(data["score"]),
            score_min=float(data["score_min"]) if "score_min" in data else None,
            score_max=float(data["score_max"]) if "score_max" in data else None,
            threshold=float(data["threshold"]) if "threshold" in data else None,
            passed=bool(data["passed"]) if "passed" in data else None,
            subject_event_id=data.get("subject_event_id"),
            subject_type=data.get("subject_type"),
            eval_run_id=data.get("eval_run_id"),
            rationale=data.get("rationale"),
            model=ModelInfo.from_dict(data["model"]) if "model" in data else None,
        )


@dataclass
class EvalRegressionDetectedPayload:
    """RFC-0001 — A metric regression detected between baseline and current."""

    metric_name: str
    baseline_score: float
    current_score: float
    delta: float
    regression_pct: float
    severity: str | None = None  # "low"|"medium"|"high"|"critical"
    affected_model: ModelInfo | None = None
    eval_run_id: str | None = None
    sample_count: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.metric_name, str) or not self.metric_name:
            raise ValueError("EvalRegressionDetectedPayload.metric_name must be non-empty")
        if self.severity is not None and self.severity not in _VALID_SEVERITIES:
            raise ValueError(f"EvalRegressionDetectedPayload.severity must be one of {sorted(_VALID_SEVERITIES)}")  # noqa: E501

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "metric_name": self.metric_name,
            "baseline_score": self.baseline_score,
            "current_score": self.current_score,
            "delta": self.delta,
            "regression_pct": self.regression_pct,
        }
        if self.severity is not None:
            d["severity"] = self.severity
        if self.affected_model is not None:
            d["affected_model"] = self.affected_model.to_dict()
        if self.eval_run_id is not None:
            d["eval_run_id"] = self.eval_run_id
        if self.sample_count is not None:
            d["sample_count"] = self.sample_count
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalRegressionDetectedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            metric_name=data["metric_name"],
            baseline_score=float(data["baseline_score"]),
            current_score=float(data["current_score"]),
            delta=float(data["delta"]),
            regression_pct=float(data["regression_pct"]),
            severity=data.get("severity"),
            affected_model=ModelInfo.from_dict(data["affected_model"]) if "affected_model" in data else None,  # noqa: E501
            eval_run_id=data.get("eval_run_id"),
            sample_count=int(data["sample_count"]) if "sample_count" in data else None,
        )


@dataclass
class EvalScenarioStartedPayload:
    """RFC-0001 — An evaluation scenario has started."""

    scenario_id: str
    scenario_name: str
    evaluator: str
    dataset_id: str | None = None
    expected_sample_count: int | None = None
    metrics: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("EvalScenarioStartedPayload.scenario_id must be non-empty")
        if not self.scenario_name:
            raise ValueError("EvalScenarioStartedPayload.scenario_name must be non-empty")
        if not self.evaluator:
            raise ValueError("EvalScenarioStartedPayload.evaluator must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "scenario_id": self.scenario_id,
            "scenario_name": self.scenario_name,
            "evaluator": self.evaluator,
        }
        if self.dataset_id is not None:
            d["dataset_id"] = self.dataset_id
        if self.expected_sample_count is not None:
            d["expected_sample_count"] = self.expected_sample_count
        if self.metrics:
            d["metrics"] = list(self.metrics)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalScenarioStartedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            scenario_id=data["scenario_id"],
            scenario_name=data["scenario_name"],
            evaluator=data["evaluator"],
            dataset_id=data.get("dataset_id"),
            expected_sample_count=int(data["expected_sample_count"]) if "expected_sample_count" in data else None,  # noqa: E501
            metrics=list(data.get("metrics", [])),
        )


@dataclass
class EvalScenarioCompletedPayload:
    """RFC-0001 — An evaluation scenario has completed."""

    scenario_id: str
    status: str  # "passed"|"failed"|"error"|"cancelled"
    duration_ms: float
    completed_sample_count: int | None = None
    scores_summary: dict[str, float] | None = None
    errors: list[str] | None = None

    def __post_init__(self) -> None:
        if not self.scenario_id:
            raise ValueError("EvalScenarioCompletedPayload.scenario_id must be non-empty")
        if self.status not in _VALID_STATUSES:
            raise ValueError(f"EvalScenarioCompletedPayload.status must be one of {sorted(_VALID_STATUSES)}")  # noqa: E501
        if self.duration_ms < 0:
            raise ValueError("EvalScenarioCompletedPayload.duration_ms must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        """Serialise the payload to a plain ``dict``."""
        d: dict[str, Any] = {
            "scenario_id": self.scenario_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
        }
        if self.completed_sample_count is not None:
            d["completed_sample_count"] = self.completed_sample_count
        if self.scores_summary is not None:
            d["scores_summary"] = dict(self.scores_summary)
        if self.errors is not None:
            d["errors"] = list(self.errors)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalScenarioCompletedPayload:
        """Deserialise from a plain ``dict``."""
        return cls(
            scenario_id=data["scenario_id"],
            status=data["status"],
            duration_ms=float(data["duration_ms"]),
            completed_sample_count=int(data["completed_sample_count"]) if "completed_sample_count" in data else None,  # noqa: E501
            scores_summary=dict(data["scores_summary"]) if "scores_summary" in data else None,
            errors=list(data["errors"]) if "errors" in data else None,
        )
