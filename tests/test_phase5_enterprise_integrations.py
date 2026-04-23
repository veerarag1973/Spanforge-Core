"""Phase 5 enterprise integration surface tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from spanforge.event import Event, Tags


def _make_openai_response(model: str = "gpt-4o", *, endpoint: str | None = None) -> Any:
    usage = SimpleNamespace(
        prompt_tokens=120,
        completion_tokens=30,
        total_tokens=150,
        prompt_tokens_details=SimpleNamespace(cached_tokens=20),
        completion_tokens_details=SimpleNamespace(reasoning_tokens=5),
    )
    response = SimpleNamespace(model=model, usage=usage)
    if endpoint is not None:
        response.endpoint = endpoint
    return response


class _DummySyncCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def create(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append({"args": args, "kwargs": kwargs})
        return _make_openai_response(model=kwargs.get("model", "deploy-gpt-4o"))


class _DummyAsyncCompletions:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def create(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append({"args": args, "kwargs": kwargs})
        return _make_openai_response(model=kwargs.get("model", "deploy-gpt-4o"))


class _DummyClient:
    def __init__(self, *, async_mode: bool = False) -> None:
        completions = _DummyAsyncCompletions() if async_mode else _DummySyncCompletions()
        self.chat = SimpleNamespace(completions=completions)
        self.azure_endpoint = "https://example-resource.openai.azure.com/"
        self.api_version = "2024-10-21"


class _DecisionResult:
    def __init__(self, status: str, **extra: Any) -> None:
        self.status = status
        self.extra = extra

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, **self.extra}


class _DummyScopeClient:
    def evaluate_with_policy(self, **kwargs: Any) -> _DecisionResult:
        return _DecisionResult("allow", **kwargs)


class _DummyRBACClient:
    def authorize_with_policy(self, **kwargs: Any) -> _DecisionResult:
        return _DecisionResult("allow", **kwargs)


class _DummyLineageClient:
    def record_with_policy(self, **kwargs: Any) -> _DecisionResult:
        return _DecisionResult("recorded", **kwargs)


@pytest.mark.unit
class TestAzureOpenAIIntegration:
    def test_instrument_client_populates_span(self) -> None:
        from spanforge._span import SpanContextManager
        from spanforge.integrations import azure_openai

        client = _DummyClient()
        azure_openai.instrument_client(client)

        with SpanContextManager("azure-call") as span:
            client.chat.completions.create(
                model="my-deployment",
                messages=[{"role": "user", "content": "hi"}],
            )

        assert span.token_usage is not None
        assert span.token_usage.input_tokens == 120
        assert span.attributes["llm.provider"] == "azure"
        assert span.attributes["llm.system"] == "openai"
        assert span.attributes["azure.openai.api_version"] == "2024-10-21"
        assert span.attributes["azure.openai.deployment"] == "my-deployment"
        assert azure_openai.is_instrumented(client) is True

        azure_openai.uninstrument_client(client)
        assert azure_openai.is_instrumented(client) is False

    def test_instrument_async_client_populates_span(self) -> None:
        from spanforge._span import SpanContextManager
        from spanforge.integrations import azure_openai

        client = _DummyClient(async_mode=True)
        azure_openai.instrument_async_client(client)

        async def _run() -> None:
            async with SpanContextManager("azure-async") as span:
                await client.chat.completions.create(model="async-deployment", messages=[])
                assert span.token_usage is not None
                assert span.attributes["azure.openai.deployment"] == "async-deployment"

        asyncio.run(_run())

    def test_invalid_client_shape_raises(self) -> None:
        from spanforge.integrations import azure_openai

        with pytest.raises(TypeError, match="client.chat.completions.create"):
            azure_openai.instrument_client(object())


@pytest.mark.unit
class TestLangGraphGovernanceHandler:
    def test_records_run_nodes_and_governance_results(self) -> None:
        from spanforge.integrations.langgraph import LangGraphGovernanceHandler

        handler = LangGraphGovernanceHandler(
            environment="prod",
            policy_client=object(),
            scope_client=_DummyScopeClient(),
            rbac_client=_DummyRBACClient(),
            lineage_client=_DummyLineageClient(),
        )

        run = handler.on_graph_start(
            trace_id="a" * 32,
            graph_name="triage-agent",
            agent_id="agent-1",
            actor_id="user-1",
            metadata={"team": "security"},
        )
        node = handler.on_node_start(
            trace_id=run.trace_id,
            node_name="approval-check",
            node_type="tool",
            agent_id="agent-1",
            actor_id="user-1",
            resource="vault://claims",
            action_name="read",
            capability="claims.read",
            required_roles=["auditor"],
        )
        handler.on_node_end(
            trace_id=run.trace_id,
            node_id=node.node_id,
            decision_id="decision-1",
            output_refs=["doc:1"],
            metadata={"outcome": "allowed"},
        )
        handler.on_graph_end(trace_id=run.trace_id)

        assert len(handler.events) == 4
        assert handler.events[0].event_type == "llm.langgraph.run.started"
        assert handler.events[-1].event_type == "llm.langgraph.run.completed"
        assert node.scope_result is not None
        assert node.rbac_result is not None
        assert node.lineage_result is not None
        assert handler.runs[run.trace_id].status == "completed"

    def test_records_node_error(self) -> None:
        from spanforge.integrations.langgraph import LangGraphGovernanceHandler

        handler = LangGraphGovernanceHandler()
        run = handler.on_graph_start(trace_id="b" * 32, graph_name="demo-graph")
        node = handler.on_node_start(trace_id=run.trace_id, node_name="planner")
        result = handler.on_node_error(trace_id=run.trace_id, node_id=node.node_id, error=ValueError("boom"))

        assert result.status == "error"
        assert result.metadata["error"] == "boom"
        assert handler.events[-1].event_type == "llm.langgraph.node.error"


@pytest.mark.unit
class TestOpenInferenceBridge:
    def test_translates_span_with_attribute_only_model_metadata(self) -> None:
        from spanforge._span import Span, _now_ns, _span_id, _trace_id
        from spanforge.export.openinference import span_to_openinference_dict

        span = Span(
            name="azure-llm",
            span_id=_span_id(),
            trace_id=_trace_id(),
            start_ns=_now_ns(),
            operation="chat",
            attributes={
                "llm.system": "openai",
                "llm.provider": "azure",
                "azure.openai.deployment": "prod-gpt-4o",
                "input.value": "hello",
                "output.value": "world",
            },
            session_id="sess-1",
        )
        span.end()

        data = span_to_openinference_dict(span)

        assert data["attributes"]["openinference.span.kind"] == "LLM"
        assert data["attributes"]["llm.system"] == "openai"
        assert data["attributes"]["llm.provider"] == "azure"
        assert data["attributes"]["input.value"] == "hello"
        assert data["attributes"]["output.value"] == "world"
        assert data["attributes"]["session.id"] == "sess-1"

    def test_bridge_to_trace_returns_span_list(self) -> None:
        from spanforge._span import Span, _now_ns, _span_id, _trace_id
        from spanforge.export.openinference import OpenInferenceSpanBridge

        span = Span(name="tool-step", span_id=_span_id(), trace_id=_trace_id(), start_ns=_now_ns())
        span.tool_calls.append(SimpleNamespace())
        span.end()

        trace = OpenInferenceSpanBridge().to_trace([span])
        assert len(trace["spans"]) == 1
        assert trace["spans"][0]["attributes"]["openinference.span.kind"] == "TOOL"


@pytest.mark.unit
class TestSIEMMapping:
    def test_event_to_siem_record_normalizes_core_fields(self) -> None:
        from spanforge.export.siem_schema import event_to_siem_record

        event = Event(
            event_type="llm.trace.span.completed",
            source="spanforge-tests@1.0.0",
            payload={"policy": "allow"},
            trace_id="a" * 32,
            span_id="b" * 16,
            actor_id="user-1",
            session_id="session-1",
            tags=Tags(env="prod"),
        )

        record = event_to_siem_record(event)

        assert record["event_type"] == "llm.trace.span.completed"
        assert record["trace_id"] == "a" * 32
        assert record["siem"]["category"] == "trace"
        assert record["siem"]["severity"] == 6
        assert record["tags"] == {"env": "prod"}

    def test_exporters_use_normalized_record(self) -> None:
        from spanforge.export.siem_splunk import SplunkHECExporter
        from spanforge.export.siem_syslog import SyslogExporter

        event = Event(
            event_type="llm.trace.tool_call.error",
            source="spanforge-tests@1.0.0",
            payload={"tool_name": "vault-read"},
            actor_id="svc-a",
        )
        splunk = SplunkHECExporter(hec_url="https://splunk.example/hec", token="token")
        syslog = SyslogExporter(host="siem.example", format="cef")

        hec_payload = splunk._build_hec_payload(event)
        cef_payload = syslog._format_cef(event)

        assert hec_payload["event"]["siem"]["severity"] == 6
        assert hec_payload["event"]["payload"]["tool_name"] == "vault-read"
        assert "deviceExternalId=" in cef_payload
        assert "event_type=llm.trace.tool_call.error" in cef_payload


@pytest.mark.unit
def test_phase5_modules_are_exported() -> None:
    import spanforge
    from spanforge.export import OpenInferenceSpanBridge, event_to_siem_record
    from spanforge.integrations import azure_openai, langgraph

    assert spanforge.OpenInferenceSpanBridge is OpenInferenceSpanBridge
    assert spanforge.event_to_siem_record is event_to_siem_record
    assert azure_openai is not None
    assert langgraph is not None
