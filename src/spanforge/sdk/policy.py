"""spanforge.sdk.policy - Runtime policy engine for GA governance controls."""

from __future__ import annotations

import copy
import threading
from dataclasses import dataclass, field
from typing import Any

from spanforge.runtime_policy import RuntimePolicyBundle, RuntimePolicyRule
from spanforge.sdk._base import SFClientConfig, SFServiceClient

__all__ = [
    "RuntimePolicyComparisonResult",
    "RuntimePolicyDecision",
    "RuntimePolicyReplayResult",
    "RuntimePolicyReviewRecord",
    "RuntimePolicySimulationResult",
    "RuntimePolicyStatusInfo",
    "SFPolicyClient",
]

_ALLOWED_DECISION_ACTIONS = frozenset({"allow", "allow+log", "redact", "block", "human_review"})
_ALLOWED_REVIEW_CLASSIFICATIONS = frozenset({"false_positive", "true_positive", "needs_tuning"})


@dataclass
class RuntimePolicyDecision:
    """Auditable result of one runtime policy evaluation."""

    decision_id: str
    policy_id: str
    policy_version: str
    environment: str
    service: str
    control: str
    action: str
    allowed: bool
    evaluated_at: str
    reason: str
    rule_id: str | None = None
    threshold: float | None = None
    observed_value: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.decision_id:
            raise ValueError("RuntimePolicyDecision.decision_id must be non-empty")
        if not self.policy_id:
            raise ValueError("RuntimePolicyDecision.policy_id must be non-empty")
        if not self.policy_version:
            raise ValueError("RuntimePolicyDecision.policy_version must be non-empty")
        if not self.environment:
            raise ValueError("RuntimePolicyDecision.environment must be non-empty")
        if not self.service:
            raise ValueError("RuntimePolicyDecision.service must be non-empty")
        if not self.control:
            raise ValueError("RuntimePolicyDecision.control must be non-empty")
        if self.action not in _ALLOWED_DECISION_ACTIONS:
            raise ValueError(
                f"RuntimePolicyDecision.action must be one of {sorted(_ALLOWED_DECISION_ACTIONS)}"
            )
        if not self.evaluated_at:
            raise ValueError("RuntimePolicyDecision.evaluated_at must be non-empty")
        if not self.reason:
            raise ValueError("RuntimePolicyDecision.reason must be non-empty")
        if self.threshold is not None and not (0.0 <= self.threshold <= 1.0):
            raise ValueError("RuntimePolicyDecision.threshold must be in [0.0, 1.0]")
        if self.observed_value is not None and not (0.0 <= self.observed_value <= 1.0):
            raise ValueError("RuntimePolicyDecision.observed_value must be in [0.0, 1.0]")

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "decision_id": self.decision_id,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "environment": self.environment,
            "service": self.service,
            "control": self.control,
            "action": self.action,
            "allowed": self.allowed,
            "evaluated_at": self.evaluated_at,
            "reason": self.reason,
        }
        if self.rule_id is not None:
            data["rule_id"] = self.rule_id
        if self.threshold is not None:
            data["threshold"] = self.threshold
        if self.observed_value is not None:
            data["observed_value"] = self.observed_value
        if self.metadata:
            data["metadata"] = self.metadata
        return data


@dataclass
class RuntimePolicySimulationResult:
    """One non-production policy simulation result."""

    simulation_id: str
    trace_id: str
    environment: str
    service: str
    control: str
    candidate_policy_id: str
    candidate_policy_version: str
    simulated_at: str
    candidate_decision: RuntimePolicyDecision
    production_decision: RuntimePolicyDecision | None = None
    changed: bool = False

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "simulation_id": self.simulation_id,
            "trace_id": self.trace_id,
            "environment": self.environment,
            "service": self.service,
            "control": self.control,
            "candidate_policy_id": self.candidate_policy_id,
            "candidate_policy_version": self.candidate_policy_version,
            "simulated_at": self.simulated_at,
            "changed": self.changed,
            "candidate_decision": self.candidate_decision.to_dict(),
        }
        if self.production_decision is not None:
            data["production_decision"] = self.production_decision.to_dict()
        return data


@dataclass
class RuntimePolicyReplayResult:
    """Summary of replaying historical events through a policy bundle."""

    replay_id: str
    environment: str
    policy_id: str
    policy_version: str
    replayed_at: str
    event_count: int
    changed_count: int
    blocked_count: int
    review_count: int
    simulations: list[RuntimePolicySimulationResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "replay_id": self.replay_id,
            "environment": self.environment,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "replayed_at": self.replayed_at,
            "event_count": self.event_count,
            "changed_count": self.changed_count,
            "blocked_count": self.blocked_count,
            "review_count": self.review_count,
            "simulations": [item.to_dict() for item in self.simulations],
        }


@dataclass
class RuntimePolicyComparisonResult:
    """Comparison summary between baseline and candidate policy outcomes."""

    comparison_id: str
    environment: str
    baseline_policy_id: str
    baseline_policy_version: str
    candidate_policy_id: str
    candidate_policy_version: str
    compared_at: str
    event_count: int
    changed_count: int
    action_changes: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "comparison_id": self.comparison_id,
            "environment": self.environment,
            "baseline_policy_id": self.baseline_policy_id,
            "baseline_policy_version": self.baseline_policy_version,
            "candidate_policy_id": self.candidate_policy_id,
            "candidate_policy_version": self.candidate_policy_version,
            "compared_at": self.compared_at,
            "event_count": self.event_count,
            "changed_count": self.changed_count,
            "action_changes": dict(self.action_changes),
        }


@dataclass
class RuntimePolicyReviewRecord:
    """Basic false-positive review loop record."""

    review_id: str
    decision_id: str
    trace_id: str
    environment: str
    service: str
    control: str
    action: str
    policy_id: str
    policy_version: str
    classification: str
    recorded_at: str
    notes: str = ""

    def __post_init__(self) -> None:
        if self.classification not in _ALLOWED_REVIEW_CLASSIFICATIONS:
            raise ValueError(
                "RuntimePolicyReviewRecord.classification must be one of "
                f"{sorted(_ALLOWED_REVIEW_CLASSIFICATIONS)}"
            )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "review_id": self.review_id,
            "decision_id": self.decision_id,
            "trace_id": self.trace_id,
            "environment": self.environment,
            "service": self.service,
            "control": self.control,
            "action": self.action,
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "classification": self.classification,
            "recorded_at": self.recorded_at,
        }
        if self.notes:
            data["notes"] = self.notes
        return data


@dataclass
class RuntimePolicyStatusInfo:
    """Runtime policy engine status."""

    status: str
    loaded_bundles: int
    active_environments: int
    decisions_emitted: int
    simulations_emitted: int = 0
    replays_emitted: int = 0
    reviews_recorded: int = 0


class SFPolicyClient(SFServiceClient):
    """Runtime policy loading, activation, evaluation, and promotion."""

    def __init__(self, config: SFClientConfig) -> None:
        super().__init__(config, service_name="policy")
        self._lock = threading.Lock()
        self._bundles: dict[tuple[str, str, str], RuntimePolicyBundle] = {}
        self._active_by_environment: dict[str, tuple[str, str]] = {}
        self._decision_records: dict[str, RuntimePolicyDecision] = {}
        self._decisions_by_trace: dict[str, list[str]] = {}
        self._simulation_records: dict[str, RuntimePolicySimulationResult] = {}
        self._simulations_by_trace: dict[str, list[str]] = {}
        self._replay_records: dict[str, RuntimePolicyReplayResult] = {}
        self._review_records: dict[str, RuntimePolicyReviewRecord] = {}
        self._reviews_by_trace: dict[str, list[str]] = {}
        self._decisions_emitted = 0
        self._simulations_emitted = 0
        self._replays_emitted = 0
        self._reviews_recorded = 0

    def load_bundle(self, bundle: RuntimePolicyBundle | dict[str, Any]) -> RuntimePolicyBundle:
        """Load and validate a bundle into the local policy registry."""
        parsed = bundle if isinstance(bundle, RuntimePolicyBundle) else RuntimePolicyBundle.from_dict(bundle)
        key = (parsed.environment, parsed.policy_id, parsed.version)
        with self._lock:
            self._bundles[key] = parsed
        return parsed

    def validate_bundle(self, bundle: RuntimePolicyBundle | dict[str, Any]) -> RuntimePolicyBundle:
        """Validate and return a parsed runtime policy bundle."""
        return bundle if isinstance(bundle, RuntimePolicyBundle) else RuntimePolicyBundle.from_dict(bundle)

    def activate(
        self,
        *,
        environment: str,
        policy_id: str,
        version: str,
        activated_at: str,
    ) -> RuntimePolicyBundle:
        """Activate one loaded bundle for an environment."""
        key = (environment, policy_id, version)
        with self._lock:
            bundle = self._bundles[key]
            self._active_by_environment[environment] = (policy_id, version)
        self._emit_policy_event(
            {
                "event_type": "policy_activated",
                "environment": environment,
                "policy_id": policy_id,
                "version": version,
                "activated_at": activated_at,
            }
        )
        return bundle

    def deactivate(self, *, environment: str, deactivated_at: str) -> None:
        """Deactivate the currently active policy for an environment."""
        with self._lock:
            policy_id, version = self._active_by_environment.pop(environment)
        self._emit_policy_event(
            {
                "event_type": "policy_deactivated",
                "environment": environment,
                "policy_id": policy_id,
                "version": version,
                "deactivated_at": deactivated_at,
            }
        )

    def get_active_bundle(self, environment: str) -> RuntimePolicyBundle | None:
        """Return the active bundle for an environment, if any."""
        with self._lock:
            active = self._active_by_environment.get(environment)
            if active is None:
                return None
            return self._bundles.get((environment, active[0], active[1]))

    def list_versions(self, *, environment: str, policy_id: str) -> list[RuntimePolicyBundle]:
        """List loaded versions for one policy in one environment."""
        with self._lock:
            bundles = [
                bundle
                for (env, pid, _version), bundle in self._bundles.items()
                if env == environment and pid == policy_id
            ]
        return sorted(bundles, key=lambda item: item.version)

    def promote(
        self,
        *,
        policy_id: str,
        from_environment: str,
        to_environment: str,
        version: str,
        new_version: str,
        owner: str,
        effective_at: str,
    ) -> RuntimePolicyBundle:
        """Clone one loaded policy version into another environment."""
        with self._lock:
            source = self._bundles[(from_environment, policy_id, version)]
        promoted = RuntimePolicyBundle(
            policy_id=source.policy_id,
            version=new_version,
            environment=to_environment,
            owner=owner,
            effective_at=effective_at,
            rules=[
                RuntimePolicyRule.from_dict(copy.deepcopy(rule.to_dict()))
                for rule in source.rules
            ],
            rationale=source.rationale,
            metadata=dict(source.metadata),
        )
        self.load_bundle(promoted)
        self._emit_policy_event(
            {
                "event_type": "policy_promoted",
                "policy_id": policy_id,
                "from_environment": from_environment,
                "to_environment": to_environment,
                "source_version": version,
                "new_version": new_version,
                "effective_at": effective_at,
            }
        )
        return promoted

    def evaluate(
        self,
        *,
        environment: str,
        trace_id: str,
        service: str,
        control: str,
        evaluated_at: str,
        observed_value: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> RuntimePolicyDecision:
        """Evaluate one service/control pair against the active environment bundle."""
        bundle = self.get_active_bundle(environment)
        decision = self._evaluate_bundle(
            bundle=bundle,
            environment=environment,
            service=service,
            control=control,
            evaluated_at=evaluated_at,
            observed_value=observed_value,
            metadata=metadata or {},
        )

        with self._lock:
            self._decision_records[decision.decision_id] = decision
            self._decisions_by_trace.setdefault(trace_id, []).append(decision.decision_id)
            self._decisions_emitted += 1

        self._emit_policy_decision(trace_id=trace_id, decision=decision)
        return decision

    def simulate(
        self,
        *,
        environment: str,
        trace_id: str,
        service: str,
        control: str,
        simulated_at: str,
        candidate_bundle: RuntimePolicyBundle | dict[str, Any],
        observed_value: float | None = None,
        metadata: dict[str, Any] | None = None,
        production_decision: RuntimePolicyDecision | None = None,
    ) -> RuntimePolicySimulationResult:
        """Simulate one candidate bundle without changing live policy state."""
        from spanforge.ulid import generate as _ulid

        parsed_bundle = self.validate_bundle(candidate_bundle)
        if parsed_bundle.environment != environment:
            raise ValueError("candidate_bundle.environment must match simulation environment")

        simulated_decision = self._evaluate_bundle(
            bundle=parsed_bundle,
            environment=environment,
            service=service,
            control=control,
            evaluated_at=simulated_at,
            observed_value=observed_value,
            metadata=metadata or {},
        )
        changed = self._decision_changed(production_decision, simulated_decision)
        result = RuntimePolicySimulationResult(
            simulation_id=_ulid(),
            trace_id=trace_id,
            environment=environment,
            service=service,
            control=control,
            candidate_policy_id=parsed_bundle.policy_id,
            candidate_policy_version=parsed_bundle.version,
            simulated_at=simulated_at,
            candidate_decision=simulated_decision,
            production_decision=production_decision,
            changed=changed,
        )

        with self._lock:
            self._simulation_records[result.simulation_id] = result
            self._simulations_by_trace.setdefault(trace_id, []).append(result.simulation_id)
            self._simulations_emitted += 1

        self._emit_policy_simulation(result)
        return result

    def replay(
        self,
        *,
        environment: str,
        replayed_at: str,
        events: list[dict[str, Any]],
        candidate_bundle: RuntimePolicyBundle | dict[str, Any],
    ) -> RuntimePolicyReplayResult:
        """Replay historical policy events through a candidate bundle."""
        from spanforge.ulid import generate as _ulid

        parsed_bundle = self.validate_bundle(candidate_bundle)
        if parsed_bundle.environment != environment:
            raise ValueError("candidate_bundle.environment must match replay environment")

        simulations: list[RuntimePolicySimulationResult] = []
        blocked_count = 0
        review_count = 0
        changed_count = 0
        for event in events:
            parsed_event = self._validated_historical_event(event, environment=environment)
            trace_id = str(parsed_event["trace_id"])
            production_decision = self._decision_from_event(event)
            simulation = self.simulate(
                environment=environment,
                trace_id=trace_id,
                service=str(parsed_event["service"]),
                control=str(parsed_event["control"]),
                simulated_at=replayed_at,
                candidate_bundle=parsed_bundle,
                observed_value=self._optional_float(parsed_event.get("observed_value")),
                metadata=dict(parsed_event.get("metadata", {})),
                production_decision=production_decision,
            )
            simulations.append(simulation)
            if simulation.candidate_decision.action == "block":
                blocked_count += 1
            if simulation.candidate_decision.action == "human_review":
                review_count += 1
            if simulation.changed:
                changed_count += 1

        result = RuntimePolicyReplayResult(
            replay_id=_ulid(),
            environment=environment,
            policy_id=parsed_bundle.policy_id,
            policy_version=parsed_bundle.version,
            replayed_at=replayed_at,
            event_count=len(events),
            changed_count=changed_count,
            blocked_count=blocked_count,
            review_count=review_count,
            simulations=simulations,
        )
        with self._lock:
            self._replay_records[result.replay_id] = result
            self._replays_emitted += 1
        self._emit_policy_replay(result)
        return result

    def compare_policies(
        self,
        *,
        environment: str,
        compared_at: str,
        events: list[dict[str, Any]],
        baseline_bundle: RuntimePolicyBundle | dict[str, Any],
        candidate_bundle: RuntimePolicyBundle | dict[str, Any],
    ) -> RuntimePolicyComparisonResult:
        """Compare baseline and candidate outcomes across historical events."""
        from spanforge.ulid import generate as _ulid

        baseline = self.validate_bundle(baseline_bundle)
        candidate = self.validate_bundle(candidate_bundle)
        if baseline.environment != environment or candidate.environment != environment:
            raise ValueError("baseline and candidate bundle environments must match comparison environment")

        changed_count = 0
        action_changes: dict[str, int] = {}
        for event in events:
            parsed_event = self._validated_historical_event(event, environment=environment)
            baseline_decision = self._evaluate_bundle(
                bundle=baseline,
                environment=environment,
                service=str(parsed_event["service"]),
                control=str(parsed_event["control"]),
                evaluated_at=compared_at,
                observed_value=self._optional_float(parsed_event.get("observed_value")),
                metadata=dict(parsed_event.get("metadata", {})),
            )
            candidate_decision = self._evaluate_bundle(
                bundle=candidate,
                environment=environment,
                service=str(parsed_event["service"]),
                control=str(parsed_event["control"]),
                evaluated_at=compared_at,
                observed_value=self._optional_float(parsed_event.get("observed_value")),
                metadata=dict(parsed_event.get("metadata", {})),
            )
            if self._decision_changed(baseline_decision, candidate_decision):
                changed_count += 1
                key = f"{baseline_decision.action}->{candidate_decision.action}"
                action_changes[key] = action_changes.get(key, 0) + 1

        result = RuntimePolicyComparisonResult(
            comparison_id=_ulid(),
            environment=environment,
            baseline_policy_id=baseline.policy_id,
            baseline_policy_version=baseline.version,
            candidate_policy_id=candidate.policy_id,
            candidate_policy_version=candidate.version,
            compared_at=compared_at,
            event_count=len(events),
            changed_count=changed_count,
            action_changes=action_changes,
        )
        self._emit_policy_comparison(result)
        return result

    def record_review(
        self,
        *,
        decision_id: str,
        trace_id: str,
        classification: str,
        recorded_at: str,
        notes: str = "",
    ) -> RuntimePolicyReviewRecord:
        """Record a basic false-positive review for a policy decision."""
        from spanforge.ulid import generate as _ulid

        decision = self.get_decision(decision_id)
        if decision is None:
            raise KeyError(decision_id)
        review = RuntimePolicyReviewRecord(
            review_id=_ulid(),
            decision_id=decision_id,
            trace_id=trace_id,
            environment=decision.environment,
            service=decision.service,
            control=decision.control,
            action=decision.action,
            policy_id=decision.policy_id,
            policy_version=decision.policy_version,
            classification=classification,
            recorded_at=recorded_at,
            notes=notes,
        )
        with self._lock:
            self._review_records[review.review_id] = review
            self._reviews_by_trace.setdefault(trace_id, []).append(review.review_id)
            self._reviews_recorded += 1
        self._emit_policy_review(review)
        return review

    def list_reviews_for_trace(self, trace_id: str) -> list[RuntimePolicyReviewRecord]:
        """Return review records recorded for a trace."""
        with self._lock:
            ids = list(self._reviews_by_trace.get(trace_id, []))
            return [self._review_records[item] for item in ids if item in self._review_records]

    def suggest_threshold(
        self,
        *,
        service: str,
        control: str,
        classification: str = "false_positive",
        comparator: str = "lt",
    ) -> float | None:
        """Suggest a threshold from reviewed decisions for one service/control."""
        if comparator not in {"lt", "lte", "gt", "gte"}:
            raise ValueError("comparator must be one of 'lt', 'lte', 'gt', 'gte'")

        observed_values: list[float] = []
        with self._lock:
            reviews = list(self._review_records.values())
        for review in reviews:
            if review.classification != classification:
                continue
            if review.service != service or review.control != control:
                continue
            decision = self.get_decision(review.decision_id)
            if decision is None or decision.observed_value is None:
                continue
            observed_values.append(decision.observed_value)

        if not observed_values:
            return None
        if comparator in {"lt", "lte"}:
            return max(observed_values)
        return min(observed_values)

    def get_decision(self, decision_id: str) -> RuntimePolicyDecision | None:
        """Return a previously emitted policy decision."""
        with self._lock:
            return self._decision_records.get(decision_id)

    def get_simulation(self, simulation_id: str) -> RuntimePolicySimulationResult | None:
        """Return a recorded simulation result."""
        with self._lock:
            return self._simulation_records.get(simulation_id)

    def get_replay(self, replay_id: str) -> RuntimePolicyReplayResult | None:
        """Return a recorded replay result."""
        with self._lock:
            return self._replay_records.get(replay_id)

    def list_decisions_for_trace(self, trace_id: str) -> list[RuntimePolicyDecision]:
        """Return all policy decisions recorded for a trace."""
        with self._lock:
            ids = list(self._decisions_by_trace.get(trace_id, []))
            return [self._decision_records[item] for item in ids if item in self._decision_records]

    def list_simulations_for_trace(self, trace_id: str) -> list[RuntimePolicySimulationResult]:
        """Return all simulations recorded for a trace."""
        with self._lock:
            ids = list(self._simulations_by_trace.get(trace_id, []))
            return [self._simulation_records[item] for item in ids if item in self._simulation_records]

    def get_status(self) -> RuntimePolicyStatusInfo:
        """Return policy engine status."""
        with self._lock:
            return RuntimePolicyStatusInfo(
                status="ok",
                loaded_bundles=len(self._bundles),
                active_environments=len(self._active_by_environment),
                decisions_emitted=self._decisions_emitted,
                simulations_emitted=self._simulations_emitted,
                replays_emitted=self._replays_emitted,
                reviews_recorded=self._reviews_recorded,
            )

    @staticmethod
    def _matching_rule(
        bundle: RuntimePolicyBundle,
        *,
        service: str,
        control: str,
    ) -> RuntimePolicyRule | None:
        for rule in bundle.rules:
            if rule.enabled and rule.service == service and rule.control == control:
                return rule
        return None

    def _evaluate_bundle(
        self,
        *,
        bundle: RuntimePolicyBundle | None,
        environment: str,
        service: str,
        control: str,
        evaluated_at: str,
        observed_value: float | None,
        metadata: dict[str, Any],
    ) -> RuntimePolicyDecision:
        if bundle is None:
            return self._implicit_allow_decision(
                environment=environment,
                service=service,
                control=control,
                evaluated_at=evaluated_at,
                observed_value=observed_value,
                metadata=metadata,
            )
        rule = self._matching_rule(bundle, service=service, control=control)
        return self._decision_from_rule(
            bundle=bundle,
            rule=rule,
            environment=environment,
            service=service,
            control=control,
            evaluated_at=evaluated_at,
            observed_value=observed_value,
            metadata=metadata,
        )

    def _implicit_allow_decision(
        self,
        *,
        environment: str,
        service: str,
        control: str,
        evaluated_at: str,
        observed_value: float | None,
        metadata: dict[str, Any],
    ) -> RuntimePolicyDecision:
        from spanforge.ulid import generate as _ulid

        return RuntimePolicyDecision(
            decision_id=_ulid(),
            policy_id="implicit-default",
            policy_version="none",
            environment=environment,
            service=service,
            control=control,
            action="allow",
            allowed=True,
            evaluated_at=evaluated_at,
            reason=f"no active runtime policy for environment '{environment}'",
            observed_value=observed_value,
            metadata=metadata,
        )

    def _decision_from_rule(
        self,
        *,
        bundle: RuntimePolicyBundle,
        rule: RuntimePolicyRule | None,
        environment: str,
        service: str,
        control: str,
        evaluated_at: str,
        observed_value: float | None,
        metadata: dict[str, Any],
    ) -> RuntimePolicyDecision:
        from spanforge.ulid import generate as _ulid

        if rule is None:
            return RuntimePolicyDecision(
                decision_id=_ulid(),
                policy_id=bundle.policy_id,
                policy_version=bundle.version,
                environment=environment,
                service=service,
                control=control,
                action="allow",
                allowed=True,
                evaluated_at=evaluated_at,
                reason=f"no enabled rule matched {service}.{control}",
                observed_value=observed_value,
                metadata=metadata,
            )

        triggered = self._rule_triggers(rule, observed_value)
        action = rule.action if triggered else "allow"
        reason = (
            rule.rationale
            or f"rule '{rule.rule_id}' triggered {service}.{control}"
            if triggered
            else f"rule '{rule.rule_id}' did not trigger"
        )
        return RuntimePolicyDecision(
            decision_id=_ulid(),
            policy_id=bundle.policy_id,
            policy_version=bundle.version,
            environment=environment,
            service=service,
            control=control,
            action=action,
            allowed=action in {"allow", "allow+log"},
            evaluated_at=evaluated_at,
            reason=reason,
            rule_id=rule.rule_id,
            threshold=rule.threshold,
            observed_value=observed_value,
            metadata=metadata,
        )

    @staticmethod
    def _decision_from_event(event: dict[str, Any]) -> RuntimePolicyDecision | None:
        action = event.get("production_action")
        if action is None:
            return None
        return RuntimePolicyDecision(
            decision_id=str(event.get("production_decision_id", "production-decision")),
            policy_id=str(event.get("production_policy_id", "production")),
            policy_version=str(event.get("production_policy_version", "current")),
            environment=str(event["environment"]),
            service=str(event["service"]),
            control=str(event["control"]),
            action=str(action),
            allowed=str(action) in {"allow", "allow+log"},
            evaluated_at=str(event.get("evaluated_at", event.get("replayed_at", ""))),
            reason=str(event.get("production_reason", "historical production decision")),
            rule_id=(
                str(event["production_rule_id"])
                if event.get("production_rule_id") is not None
                else None
            ),
            threshold=SFPolicyClient._optional_float(event.get("production_threshold")),
            observed_value=SFPolicyClient._optional_float(event.get("observed_value")),
            metadata=dict(event.get("metadata", {})),
        )

    @staticmethod
    def _decision_changed(
        baseline: RuntimePolicyDecision | None,
        candidate: RuntimePolicyDecision,
    ) -> bool:
        if baseline is None:
            return True
        return baseline.action != candidate.action or baseline.allowed != candidate.allowed

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value is None:
            return None
        return float(value)

    @staticmethod
    def _validated_historical_event(event: dict[str, Any], *, environment: str) -> dict[str, Any]:
        if not isinstance(event, dict):
            raise ValueError("historical policy event must be a dict")
        required_fields = ("trace_id", "environment", "service", "control")
        missing = [field for field in required_fields if field not in event]
        if missing:
            raise ValueError(
                "historical policy event is missing required fields: "
                + ", ".join(missing)
            )
        if str(event["environment"]) != environment:
            raise ValueError("historical policy event environment must match requested environment")
        metadata = event.get("metadata", {})
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("historical policy event metadata must be a dict when provided")
        observed_value = event.get("observed_value")
        if observed_value is not None:
            numeric = float(observed_value)
            if not (0.0 <= numeric <= 1.0):
                raise ValueError("historical policy event observed_value must be in [0.0, 1.0]")
        return event

    @staticmethod
    def _rule_triggers(rule: RuntimePolicyRule, observed_value: float | None) -> bool:
        if rule.threshold is None:
            return True
        if observed_value is None:
            return False
        comparator = str(rule.metadata.get("comparator", "lt"))
        if comparator == "lt":
            return observed_value < rule.threshold
        if comparator == "lte":
            return observed_value <= rule.threshold
        if comparator == "gt":
            return observed_value > rule.threshold
        if comparator == "gte":
            return observed_value >= rule.threshold
        if comparator == "eq":
            return observed_value == rule.threshold
        if comparator == "neq":
            return observed_value != rule.threshold
        raise ValueError(f"Unsupported runtime policy comparator: {comparator!r}")

    def _emit_policy_event(self, payload: dict[str, Any]) -> None:
        from spanforge.sdk import sf_audit

        sf_audit.append(payload, "spanforge.policy.lifecycle.v1")

    def _emit_policy_decision(self, *, trace_id: str, decision: RuntimePolicyDecision) -> None:
        from spanforge.sdk import sf_audit

        payload = {"trace_id": trace_id, **decision.to_dict()}
        sf_audit.append(payload, "spanforge.policy.decision.v1")

    def _emit_policy_simulation(self, result: RuntimePolicySimulationResult) -> None:
        from spanforge.sdk import sf_audit

        sf_audit.append(result.to_dict(), "spanforge.policy.simulation.v1")

    def _emit_policy_replay(self, result: RuntimePolicyReplayResult) -> None:
        from spanforge.sdk import sf_audit

        sf_audit.append(result.to_dict(), "spanforge.policy.replay.v1")

    def _emit_policy_comparison(self, result: RuntimePolicyComparisonResult) -> None:
        from spanforge.sdk import sf_audit

        sf_audit.append(result.to_dict(), "spanforge.policy.comparison.v1")

    def _emit_policy_review(self, result: RuntimePolicyReviewRecord) -> None:
        from spanforge.sdk import sf_audit

        sf_audit.append(result.to_dict(), "spanforge.policy.review.v1")
