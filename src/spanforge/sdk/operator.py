"""spanforge.sdk.operator - Operator workflow aggregation for runtime governance."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spanforge.sdk._base import SFClientConfig, SFServiceClient

__all__ = ["OperatorEvidencePackage", "OperatorWorkflowView", "SFOperatorClient"]

_TRACE_AUDIT_SCHEMAS: tuple[str, ...] = (
    "spanforge.policy.decision.v1",
    "spanforge.policy.review.v1",
    "spanforge.explanation.v1",
    "spanforge.grounding.v1",
    "spanforge.scope.v1",
    "spanforge.rbac.v1",
    "spanforge.lineage.v1",
)
_OUTCOME_PRIORITY: dict[str, int] = {
    "block": 5,
    "human_review": 4,
    "escalate": 4,
    "redact": 3,
    "allow+log": 2,
    "allow": 1,
}


def _serialize(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


@dataclass
class OperatorWorkflowView:
    """Aggregated operator-facing view of one runtime trace."""

    trace_id: str
    outcome: str
    summary: str
    policy_decisions: list[Any] = field(default_factory=list)
    explanations: list[Any] = field(default_factory=list)
    grounding_results: list[Any] = field(default_factory=list)
    scope_decisions: list[Any] = field(default_factory=list)
    rbac_decisions: list[Any] = field(default_factory=list)
    lineage_records: list[Any] = field(default_factory=list)
    review_records: list[Any] = field(default_factory=list)
    audit_records: list[dict[str, Any]] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "outcome": self.outcome,
            "summary": self.summary,
            "policy_decisions": [_serialize(item) for item in self.policy_decisions],
            "explanations": [_serialize(item) for item in self.explanations],
            "grounding_results": [_serialize(item) for item in self.grounding_results],
            "scope_decisions": [_serialize(item) for item in self.scope_decisions],
            "rbac_decisions": [_serialize(item) for item in self.rbac_decisions],
            "lineage_records": [_serialize(item) for item in self.lineage_records],
            "review_records": [_serialize(item) for item in self.review_records],
            "audit_records": list(self.audit_records),
            "timeline": list(self.timeline),
        }


@dataclass
class OperatorEvidencePackage:
    """Exportable signed evidence package for one operator workflow trace."""

    package_id: str
    trace_id: str
    generated_at: str
    outcome: str
    summary: str
    exported_records: int
    chain_verification: dict[str, Any]
    workflow: OperatorWorkflowView
    checksum: str
    signature: str
    output_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = {
            "package_id": self.package_id,
            "trace_id": self.trace_id,
            "generated_at": self.generated_at,
            "outcome": self.outcome,
            "summary": self.summary,
            "exported_records": self.exported_records,
            "chain_verification": dict(self.chain_verification),
            "workflow": self.workflow.to_dict(),
            "checksum": self.checksum,
            "signature": self.signature,
        }
        if self.output_path:
            data["output_path"] = self.output_path
        return data


class SFOperatorClient(SFServiceClient):
    """Aggregate trace-linked governance records into one operator workflow."""

    def __init__(self, config: SFClientConfig) -> None:
        super().__init__(config, service_name="operator")

    def inspect_trace(self, trace_id: str) -> OperatorWorkflowView:
        """Return the operator workflow view for one trace."""
        from spanforge.sdk import (
            sf_audit,
            sf_explain,
            sf_lineage,
            sf_policy,
            sf_rag,
            sf_rbac,
            sf_scope,
        )

        policy_decisions = sf_policy.list_decisions_for_trace(trace_id)
        explanations = sf_explain.list_for_trace(trace_id)
        grounding_results = sf_rag.list_grounding_for_trace(trace_id)
        scope_decisions = sf_scope.list_for_trace(trace_id)
        rbac_decisions = sf_rbac.list_for_trace(trace_id)
        lineage_records = sf_lineage.list_for_trace(trace_id)
        review_records = sf_policy.list_reviews_for_trace(trace_id)
        audit_records = self._audit_records_for_trace(sf_audit, trace_id)

        view = OperatorWorkflowView(
            trace_id=trace_id,
            outcome=self._resolve_outcome(
                policy_decisions=policy_decisions,
                explanations=explanations,
                grounding_results=grounding_results,
                scope_decisions=scope_decisions,
                rbac_decisions=rbac_decisions,
            ),
            summary="",
            policy_decisions=policy_decisions,
            explanations=explanations,
            grounding_results=grounding_results,
            scope_decisions=scope_decisions,
            rbac_decisions=rbac_decisions,
            lineage_records=lineage_records,
            review_records=review_records,
            audit_records=audit_records,
            timeline=self._timeline(
                policy_decisions=policy_decisions,
                explanations=explanations,
                grounding_results=grounding_results,
                scope_decisions=scope_decisions,
                rbac_decisions=rbac_decisions,
                lineage_records=lineage_records,
            ),
        )
        view.summary = self._build_summary(view)
        return view

    def export_package(
        self,
        trace_id: str,
        *,
        output_path: str | None = None,
    ) -> OperatorEvidencePackage:
        """Build a signed export package for one operator workflow trace."""
        from spanforge.sdk import sf_audit

        view = self.inspect_trace(trace_id)
        generated_at = self._utc_now()
        package_payload = {
            "trace_id": trace_id,
            "generated_at": generated_at,
            "outcome": view.outcome,
            "summary": view.summary,
            "exported_records": len(view.audit_records),
            "chain_verification": sf_audit.verify_chain(view.audit_records),
            "workflow": view.to_dict(),
        }
        signed = sf_audit.sign(package_payload)
        result = OperatorEvidencePackage(
            package_id=signed.record_id,
            trace_id=trace_id,
            generated_at=generated_at,
            outcome=view.outcome,
            summary=view.summary,
            exported_records=len(view.audit_records),
            chain_verification=package_payload["chain_verification"],
            workflow=view,
            checksum=signed.checksum,
            signature=signed.signature,
            output_path=output_path,
        )

        if output_path:
            target = Path(output_path)
            target.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")

        return result

    def _audit_records_for_trace(self, audit_client: Any, trace_id: str) -> list[dict[str, Any]]:
        seen: set[str] = set()
        records: list[dict[str, Any]] = []
        for schema_key in _TRACE_AUDIT_SCHEMAS:
            for record in audit_client.export(schema_key=schema_key, project_id=self._config.project_id or None):
                if record.get("trace_id") != trace_id:
                    continue
                record_id = str(record.get("record_id", ""))
                if record_id in seen:
                    continue
                seen.add(record_id)
                records.append(record)
        return sorted(records, key=lambda item: str(item.get("timestamp", "")))

    def _resolve_outcome(
        self,
        *,
        policy_decisions: list[Any],
        explanations: list[Any],
        grounding_results: list[Any],
        scope_decisions: list[Any],
        rbac_decisions: list[Any],
    ) -> str:
        outcomes: list[str] = []
        outcomes.extend(str(getattr(item, "action", "")) for item in policy_decisions)
        outcomes.extend(str(getattr(item, "policy_action", "")) for item in explanations)
        outcomes.extend(str(getattr(item, "policy_action", "")) for item in grounding_results)
        outcomes.extend(str(getattr(item, "outcome", "")) for item in scope_decisions)
        outcomes.extend(str(getattr(item, "outcome", "")) for item in rbac_decisions)
        filtered = [item for item in outcomes if item]
        if not filtered:
            return "allow"
        return max(filtered, key=lambda item: _OUTCOME_PRIORITY.get(item, 0))

    def _build_summary(self, view: OperatorWorkflowView) -> str:
        clauses: list[str] = []
        if view.outcome == "block":
            clauses.append("Blocked by runtime governance controls.")
        elif view.outcome in {"human_review", "escalate"}:
            clauses.append("Escalated for human review.")
        elif view.outcome == "redact":
            clauses.append("Allowed with redaction requirements.")
        elif view.outcome == "allow+log":
            clauses.append("Allowed with signed audit logging.")
        else:
            clauses.append("Allowed by runtime governance policy.")

        primary = self._primary_policy_decision(view.policy_decisions)
        if primary is not None:
            clauses.append(str(getattr(primary, "reason", "")))

        scope_violations = [item for item in view.scope_decisions if not bool(getattr(item, "allowed", True))]
        if scope_violations:
            clauses.append(str(getattr(scope_violations[-1], "reason", "")))

        rbac_violations = [item for item in view.rbac_decisions if not bool(getattr(item, "allowed", True))]
        if rbac_violations:
            clauses.append(str(getattr(rbac_violations[-1], "reason", "")))

        grounding = self._latest(view.grounding_results, "assessed_at")
        if grounding is not None:
            clauses.append(
                "Grounding "
                f"{getattr(grounding, 'status', 'unknown')} "
                f"(avg={getattr(grounding, 'average_score', 0.0):.2f}, "
                f"threshold={getattr(grounding, 'threshold', 0.0):.2f})."
            )

        explanation = self._latest(view.explanations, "generated_at")
        if explanation is not None and getattr(explanation, "summary", ""):
            clauses.append(f"Explanation: {getattr(explanation, 'summary')}")

        lineage = self._latest(view.lineage_records, "recorded_at")
        if lineage is not None:
            clauses.append(
                "Lineage captured for "
                f"{getattr(lineage, 'subject_type', 'subject')}:{getattr(lineage, 'subject_id', '')}."
            )

        return " ".join(part.strip() for part in clauses if part and str(part).strip())

    def _timeline(
        self,
        *,
        policy_decisions: list[Any],
        explanations: list[Any],
        grounding_results: list[Any],
        scope_decisions: list[Any],
        rbac_decisions: list[Any],
        lineage_records: list[Any],
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        items.extend(self._timeline_items(policy_decisions, category="policy", ts_field="evaluated_at"))
        items.extend(self._timeline_items(explanations, category="explanation", ts_field="generated_at"))
        items.extend(self._timeline_items(grounding_results, category="grounding", ts_field="assessed_at"))
        items.extend(self._timeline_items(scope_decisions, category="scope", ts_field="checked_at"))
        items.extend(self._timeline_items(rbac_decisions, category="rbac", ts_field="checked_at"))
        items.extend(self._timeline_items(lineage_records, category="lineage", ts_field="recorded_at"))
        return sorted(items, key=lambda item: str(item.get("timestamp", "")))

    def _timeline_items(self, records: list[Any], *, category: str, ts_field: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for record in records:
            items.append(
                {
                    "category": category,
                    "timestamp": str(getattr(record, ts_field, "")),
                    "record": _serialize(record),
                }
            )
        return items

    @staticmethod
    def _latest(records: list[Any], field_name: str) -> Any | None:
        if not records:
            return None
        return max(records, key=lambda item: str(getattr(item, field_name, "")))

    def _primary_policy_decision(self, records: list[Any]) -> Any | None:
        if not records:
            return None
        return max(
            records,
            key=lambda item: (
                _OUTCOME_PRIORITY.get(str(getattr(item, "action", "")), 0),
                str(getattr(item, "evaluated_at", "")),
            ),
        )

    @staticmethod
    def _utc_now() -> str:
        from datetime import datetime, timezone

        return datetime.now(tz=timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
