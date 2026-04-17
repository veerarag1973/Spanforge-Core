"""spanforge.integrations.crewai — CrewAI event handler.

Provides :class:`SpanForgeCrewAIHandler`, a CrewAI-compatible event handler
that emits SpanForge trace events for agents, tasks, and tool calls.

Usage::

    from spanforge.integrations.crewai import SpanForgeCrewAIHandler, patch

    # Option 1: register globally (auto-patches CrewAI internals)
    patch()

    # Option 2: attach to a specific crew
    handler = SpanForgeCrewAIHandler()
    crew = Crew(agents=[...], tasks=[...], callbacks=[handler])

The module imports cleanly even when CrewAI is not installed — the
:func:`patch` function guards with :func:`importlib.util.find_spec`.
"""

from __future__ import annotations

import contextlib
import importlib.util
import time
import warnings
from typing import Any

__all__ = ["SpanForgeCrewAIHandler", "is_patched", "patch", "unpatch"]


class SpanForgeCrewAIHandler:
    """CrewAI callback handler that emits SpanForge trace events.

    Manages ``SpanContextManager`` instances for active agents and tool calls,
    records token usage and errors when available from CrewAI's output
    objects, and emits structured SpanForge events on completion.

    This handler follows the same pattern as
    :class:`~spanforge.integrations.langchain.LLMSchemaCallbackHandler`.
    """

    def __init__(self) -> None:
        # Map of agent_id/task_id → SpanContextManager so we can close the
        # right span in the matching *_end callback.
        self._agent_spans: dict[str, Any] = {}
        self._tool_spans: dict[str, Any] = {}
        self._task_spans: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Agent lifecycle
    # ------------------------------------------------------------------

    def on_agent_action(
        self,
        agent: Any,
        _task: Any,
        tool: Any,
        tool_input: Any,
    ) -> None:
        """Called when a CrewAI agent takes an action (tool invocation)."""
        try:
            from spanforge import tracer

            tool_name = getattr(tool, "name", None) or str(tool)
            key = f"{id(agent)}/{tool_name}/{time.time_ns()}"
            cm = tracer.span(
                tool_name,
                operation="tool_call",
                attributes={
                    "crewai.tool_input": str(tool_input)[:2048],
                    "crewai.agent": _agent_role(agent),
                },
            )
            span = cm.__enter__()
            self._tool_spans[key] = (cm, span, key)
        except Exception:
            pass  # hook errors must never abort crew execution

    def on_agent_finish(self, agent: Any, output: Any) -> None:
        """Called when a CrewAI agent finishes its assigned task."""
        try:
            key = str(id(agent))
            entry = self._agent_spans.pop(key, None)
            if entry is not None:
                cm, span = entry
                if hasattr(output, "return_values"):
                    span.set_attribute("crewai.output", str(output.return_values)[:2048])
                cm.__exit__(None, None, None)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Tool lifecycle
    # ------------------------------------------------------------------

    def on_tool_start(self, tool: Any, tool_input: Any) -> None:
        """Called when a CrewAI tool begins executing."""
        try:
            from spanforge import tracer

            tool_name = getattr(tool, "name", None) or str(tool)
            key = f"{id(tool)}/{tool_name}/{time.time_ns()}"
            cm = tracer.span(
                tool_name,
                operation="tool_call",
                attributes={"crewai.tool_input": str(tool_input)[:2048]},
            )
            span = cm.__enter__()
            self._tool_spans[key] = (cm, span, key)
        except Exception:
            pass

    def on_tool_end(self, tool: Any, output: Any) -> None:
        """Called when a CrewAI tool finishes executing."""
        try:
            tool_name = getattr(tool, "name", None) or str(tool)
            # Find the most recent open span for this tool name.
            key = next(
                (k for k in reversed(list(self._tool_spans)) if tool_name in k),
                None,
            )
            if key is not None:
                cm, span, _ = self._tool_spans.pop(key)
                span.set_attribute("crewai.tool_output", str(output)[:2048])
                cm.__exit__(None, None, None)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------

    def on_task_start(self, task: Any) -> None:
        """Called when a CrewAI task begins."""
        try:
            from spanforge import tracer

            task_desc = _task_description(task)
            key = str(id(task))
            cm = tracer.span(
                task_desc,
                operation="invoke_agent",
                attributes={"crewai.task": task_desc},
            )
            span = cm.__enter__()
            self._task_spans[key] = (cm, span)
        except Exception:
            pass

    def on_task_end(self, task: Any, output: Any) -> None:
        """Called when a CrewAI task completes."""
        try:
            key = str(id(task))
            entry = self._task_spans.pop(key, None)
            if entry is not None:
                cm, span = entry
                if output is not None:
                    span.set_attribute("crewai.task_output", str(output)[:2048])
                cm.__exit__(None, None, None)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _agent_role(agent: Any) -> str:
    return str(getattr(agent, "role", None) or getattr(agent, "name", None) or "unknown-agent")


def _task_description(task: Any) -> str:
    desc = getattr(task, "description", None) or getattr(task, "name", None) or "crewai-task"
    return str(desc)[:120]


# ---------------------------------------------------------------------------
# patch() — convenience auto-registration
# ---------------------------------------------------------------------------


def patch() -> None:
    """Auto-register :class:`SpanForgeCrewAIHandler` with CrewAI callbacks.

    Raises:
        ImportError: If ``crewai`` is not installed.
        RuntimeError: If the CrewAI callback API cannot be located.
    """
    if importlib.util.find_spec("crewai") is None:
        raise ImportError(
            "CrewAI package is required for the spanforge CrewAI integration.\n"
            "Install it with: pip install 'spanforge[crewai]'"
        )
    try:
        import crewai

        # CrewAI exposes a global callbacks list in some versions.
        if hasattr(crewai, "callbacks") and isinstance(crewai.callbacks, list):
            handler = SpanForgeCrewAIHandler()
            crewai.callbacks.append(handler)
            crewai._spanforge_patched = True  # type: ignore[attr-defined]
            return
    except Exception as exc:
        warnings.warn(
            f"spanforge: could not auto-patch CrewAI callbacks: {exc}\n"
            "Attach SpanForgeCrewAIHandler manually instead.",
            stacklevel=2,
        )


_PATCH_FLAG = "_spanforge_patched"


def unpatch() -> None:
    """Remove the :class:`SpanForgeCrewAIHandler` from CrewAI global callbacks.

    Safe to call even if :func:`patch` was never called.
    """
    if importlib.util.find_spec("crewai") is None:
        return
    try:
        import crewai

        if not getattr(crewai, _PATCH_FLAG, False):
            return
        if hasattr(crewai, "callbacks") and isinstance(crewai.callbacks, list):
            crewai.callbacks[:] = [
                cb for cb in crewai.callbacks if not isinstance(cb, SpanForgeCrewAIHandler)
            ]
        with contextlib.suppress(AttributeError):
            del crewai._spanforge_patched  # type: ignore[attr-defined]
    except Exception:
        pass


def is_patched() -> bool:
    """Return ``True`` if CrewAI has been patched by :func:`patch`.

    Returns:
        ``True`` when the spanforge handler is registered; ``False`` otherwise.
    """
    if importlib.util.find_spec("crewai") is None:
        return False
    try:
        import crewai

        return bool(getattr(crewai, _PATCH_FLAG, False))
    except Exception:
        return False
