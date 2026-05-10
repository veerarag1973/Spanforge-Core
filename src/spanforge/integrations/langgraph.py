"""spanforge.integrations.langgraph - LangGraph governance demo integration.

Implements a lightweight handler that records graph and node execution while
optionally invoking SpanForge runtime-governance services.  This is intended to
cover the GA demo path rather than deep framework auto-patching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from spanforge.event import Event
from spanforge.ulid import generate as gen_ulid

__all__ = [
    "LangGraphGovernanceHandler",
    "LangGraphNodeResult",
    "LangGraphRunRecord",
    "SpanForgeLangGraphCallback",
    "is_available",
]


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _require_langgraph() -> Any:
    try:
        import langgraph
    except ImportError as exc:
        raise ImportError(
            "LangGraph is required for this integration.\n"
            "Install it with: pip install 'spanforge[langgraph]'"
        ) from exc
    return langgraph


def is_available() -> bool:
    """Return ``True`` when LangGraph is importable."""
    try:
        _require_langgraph()
    except ImportError:
        return False
    return True


@dataclass
class LangGraphNodeResult:
    """Recorded result for one node in a LangGraph run."""

    node_id: str
    trace_id: str
    node_name: str
    node_type: str
    started_at: str
    completed_at: str | None = None
    status: str = "started"
    scope_result: Any | None = None
    rbac_result: Any | None = None
    lineage_result: Any | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "node_id": self.node_id,
            "trace_id": self.trace_id,
            "node_name": self.node_name,
            "node_type": self.node_type,
            "started_at": self.started_at,
            "status": self.status,
            "metadata": dict(self.metadata),
        }
        if self.completed_at is not None:
            data["completed_at"] = self.completed_at
        if self.scope_result is not None:
            data["scope_result"] = _to_dict(self.scope_result)
        if self.rbac_result is not None:
            data["rbac_result"] = _to_dict(self.rbac_result)
        if self.lineage_result is not None:
            data["lineage_result"] = _to_dict(self.lineage_result)
        return data


@dataclass
class LangGraphRunRecord:
    """High-level trace record for one governed LangGraph run."""

    run_id: str
    trace_id: str
    graph_name: str
    environment: str
    started_at: str
    completed_at: str | None = None
    status: str = "started"
    agent_id: str | None = None
    actor_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    nodes: list[LangGraphNodeResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = {
            "run_id": self.run_id,
            "trace_id": self.trace_id,
            "graph_name": self.graph_name,
            "environment": self.environment,
            "started_at": self.started_at,
            "status": self.status,
            "metadata": dict(self.metadata),
            "nodes": [node.to_dict() for node in self.nodes],
        }
        if self.completed_at is not None:
            data["completed_at"] = self.completed_at
        if self.agent_id is not None:
            data["agent_id"] = self.agent_id
        if self.actor_id is not None:
            data["actor_id"] = self.actor_id
        return data


def _to_dict(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return value.to_dict()
    return value


class LangGraphGovernanceHandler:
    """Record LangGraph execution and invoke runtime-governance controls."""

    def __init__(
        self,
        *,
        source: str = "spanforge.langgraph@1.0.0",
        environment: str = "prod",
        policy_client: Any | None = None,
        scope_client: Any | None = None,
        rbac_client: Any | None = None,
        lineage_client: Any | None = None,
    ) -> None:
        self._source = source
        self._environment = environment
        self._policy_client = policy_client
        self._scope_client = scope_client
        self._rbac_client = rbac_client
        self._lineage_client = lineage_client
        self.events: list[Event] = []
        self.runs: dict[str, LangGraphRunRecord] = {}
        self.nodes: dict[str, LangGraphNodeResult] = {}

    def on_graph_start(
        self,
        *,
        trace_id: str,
        graph_name: str,
        agent_id: str | None = None,
        actor_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LangGraphRunRecord:
        """Start recording one LangGraph run."""
        run = LangGraphRunRecord(
            run_id=gen_ulid(),
            trace_id=trace_id,
            graph_name=graph_name,
            environment=self._environment,
            started_at=_utc_now(),
            agent_id=agent_id,
            actor_id=actor_id,
            metadata=metadata or {},
        )
        self.runs[trace_id] = run
        self._emit_event(
            "llm.langgraph.run.started",
            trace_id=trace_id,
            payload=run.to_dict(),
        )
        return run

    def on_node_start(
        self,
        *,
        trace_id: str,
        node_name: str,
        node_type: str = "chain",
        agent_id: str | None = None,
        actor_id: str | None = None,
        resource: str | None = None,
        action_name: str | None = None,
        capability: str | None = None,
        required_roles: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LangGraphNodeResult:
        """Record node start and optionally run scope/RBAC checks."""
        started_at = _utc_now()
        result = LangGraphNodeResult(
            node_id=gen_ulid(),
            trace_id=trace_id,
            node_name=node_name,
            node_type=node_type,
            started_at=started_at,
            metadata=metadata or {},
        )
        if self._scope_client is not None and agent_id and resource and action_name:
            result.scope_result = self._scope_client.evaluate_with_policy(
                environment=self._environment,
                trace_id=trace_id,
                agent_id=agent_id,
                resource=resource,
                action_name=action_name,
                checked_at=started_at,
                capability=capability,
                policy_client=self._policy_client,
            )
        if self._rbac_client is not None and actor_id and resource and action_name:
            result.rbac_result = self._rbac_client.authorize_with_policy(
                environment=self._environment,
                trace_id=trace_id,
                actor_id=actor_id,
                resource=resource,
                action_name=action_name,
                checked_at=started_at,
                required_roles=required_roles,
                policy_client=self._policy_client,
            )
        self.nodes[result.node_id] = result
        run = self.runs.get(trace_id)
        if run is not None:
            run.nodes.append(result)
        self._emit_event(
            "llm.langgraph.node.started",
            trace_id=trace_id,
            payload=result.to_dict(),
        )
        return result

    def on_node_end(
        self,
        *,
        trace_id: str,
        node_id: str,
        decision_id: str,
        subject_type: str = "langgraph_node",
        output_refs: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> LangGraphNodeResult:
        """Complete one node and optionally capture lineage."""
        node = self.nodes[node_id]
        completed_at = _utc_now()
        node.completed_at = completed_at
        node.status = "completed"
        if self._lineage_client is not None:
            node.lineage_result = self._lineage_client.record_with_policy(
                environment=self._environment,
                trace_id=trace_id,
                decision_id=decision_id,
                subject_type=subject_type,
                subject_id=node.node_id,
                operation=node.node_name,
                recorded_at=completed_at,
                policy_client=self._policy_client,
                output_refs=output_refs,
                metadata=metadata,
            )
        self._emit_event(
            "llm.langgraph.node.completed",
            trace_id=trace_id,
            payload=node.to_dict(),
        )
        return node

    def on_node_error(self, *, trace_id: str, node_id: str, error: BaseException) -> LangGraphNodeResult:
        """Record node failure."""
        node = self.nodes[node_id]
        node.completed_at = _utc_now()
        node.status = "error"
        node.metadata["error"] = str(error)
        node.metadata["error_type"] = type(error).__name__
        self._emit_event(
            "llm.langgraph.node.error",
            trace_id=trace_id,
            payload=node.to_dict(),
        )
        return node

    def on_graph_end(self, *, trace_id: str, status: str = "completed") -> LangGraphRunRecord:
        """Complete one LangGraph run."""
        run = self.runs[trace_id]
        run.completed_at = _utc_now()
        run.status = status
        self._emit_event(
            "llm.langgraph.run.completed",
            trace_id=trace_id,
            payload=run.to_dict(),
        )
        return run

    def _emit_event(self, event_type: str, *, trace_id: str, payload: dict[str, Any]) -> Event:
        event = Event(
            event_type=event_type,
            source=self._source,
            payload=payload,
            trace_id=trace_id,
            event_id=gen_ulid(),
        )
        self.events.append(event)
        return event


# ---------------------------------------------------------------------------
# LangChain-compatible callback handler for LangGraph
# ---------------------------------------------------------------------------


class SpanForgeLangGraphCallback:
    """LangChain/LangGraph-compatible callback handler that emits SpanForge events.

    Implements the five lifecycle hooks used by LangGraph chains and tool
    calls — ``on_chain_start``, ``on_chain_end``, ``on_tool_start``,
    ``on_tool_end``, and ``on_agent_action`` — without requiring LangGraph
    to be installed.  Events are accumulated in :attr:`events`.

    Args:
        source:  Value for ``Event.source``.
        org_id:  Optional organisation identifier forwarded to every event.

    Usage::

        from spanforge.integrations.langgraph import SpanForgeLangGraphCallback

        cb = SpanForgeLangGraphCallback(source="my-langgraph-app@1.0.0")
        # Pass cb to your LangGraph / LangChain chain:
        #   chain.invoke(inputs, config={"callbacks": [cb]})

        for event in cb.events:
            print(event.to_json())
    """

    def __init__(
        self,
        source: str = "spanforge.langgraph@1.0.0",
        *,
        org_id: str | None = None,
    ) -> None:
        self._source = source
        self._org_id = org_id
        self.events: list[Event] = []

    # ------------------------------------------------------------------
    # Internal helper
    # ------------------------------------------------------------------

    def _emit(self, event_type: str, payload: dict[str, Any]) -> Event:
        event = Event(
            event_type=event_type,
            source=self._source,
            org_id=self._org_id,
            payload=payload,
            event_id=gen_ulid(),
        )
        self.events.append(event)
        return event

    # ------------------------------------------------------------------
    # Chain hooks
    # ------------------------------------------------------------------

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a LangGraph chain/graph starts executing.

        Args:
            serialized: Serialised chain config dict.
            inputs:     Input dict passed to the chain.
            run_id:     LangChain run identifier.
            **kwargs:   Additional keyword arguments (ignored).
        """
        chain_name = ""
        if serialized:
            ids = serialized.get("id", [])
            if ids:
                chain_name = str(ids[-1])
        self._emit(
            "llm.langgraph.chain.started",
            {
                "chain_name": chain_name,
                "input_keys": list(inputs.keys()) if isinstance(inputs, dict) else [],
                "run_id": str(run_id) if run_id is not None else None,
            },
        )

    def on_chain_end(
        self,
        outputs: dict[str, Any],
        *,
        run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a LangGraph chain/graph finishes executing.

        Args:
            outputs: Output dict returned by the chain.
            run_id:  LangChain run identifier.
            **kwargs: Additional keyword arguments (ignored).
        """
        self._emit(
            "llm.langgraph.chain.completed",
            {
                "output_keys": list(outputs.keys()) if isinstance(outputs, dict) else [],
                "run_id": str(run_id) if run_id is not None else None,
            },
        )

    # ------------------------------------------------------------------
    # Tool hooks
    # ------------------------------------------------------------------

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a LangGraph tool call starts.

        Args:
            serialized: Serialised tool config dict.
            input_str:  Input string passed to the tool.
            run_id:     LangChain run identifier.
            **kwargs:   Additional keyword arguments (ignored).
        """
        tool_name = ""
        if serialized:
            ids = serialized.get("id", [])
            if ids:
                tool_name = str(ids[-1])
            if not tool_name:
                tool_name = str(serialized.get("name", ""))
        self._emit(
            "llm.langgraph.tool.started",
            {
                "tool_name": tool_name,
                "input_length": len(input_str),
                "run_id": str(run_id) if run_id is not None else None,
            },
        )

    def on_tool_end(
        self,
        output: str,
        *,
        run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when a LangGraph tool call completes.

        Args:
            output:  Output string returned by the tool.
            run_id:  LangChain run identifier.
            **kwargs: Additional keyword arguments (ignored).
        """
        self._emit(
            "llm.langgraph.tool.completed",
            {
                "output_length": len(output),
                "run_id": str(run_id) if run_id is not None else None,
            },
        )

    # ------------------------------------------------------------------
    # Agent action hook
    # ------------------------------------------------------------------

    def on_agent_action(
        self,
        action: Any,
        *,
        run_id: Any | None = None,
        **kwargs: Any,
    ) -> None:
        """Called when an agent decides to take an action.

        Args:
            action:  The agent action object (expected to have ``tool``,
                     ``tool_input``, and ``log`` attributes, or be a dict).
            run_id:  LangChain run identifier.
            **kwargs: Additional keyword arguments (ignored).
        """
        if isinstance(action, dict):
            tool = str(action.get("tool", ""))
            tool_input = action.get("tool_input", "")
            log = str(action.get("log", ""))
        else:
            tool = str(getattr(action, "tool", ""))
            tool_input = getattr(action, "tool_input", "")
            log = str(getattr(action, "log", ""))
        self._emit(
            "llm.langgraph.agent.action",
            {
                "tool": tool,
                "tool_input": tool_input,
                "log": log,
                "run_id": str(run_id) if run_id is not None else None,
            },
        )
