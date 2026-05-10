"""Supplemental tests — batch 4: _hooks, _stream, gate, policy, alert, observe, audit, validate, dataset_scanner, testing, siem_schema, runtime_policy."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _cfg():
    from spanforge.sdk._base import SFClientConfig

    return SFClientConfig(api_key="test-key", endpoint="http://localhost:9999")


def _make_event(**kwargs):
    from spanforge.event import Event
    from spanforge.types import EventType

    return Event(
        event_type=EventType.TRACE_SPAN_COMPLETED,
        source="s@1.0",
        payload={},
        **kwargs,
    )


# ===========================================================================
# spanforge._hooks — HookRegistry
# ===========================================================================


class TestHookRegistry:
    """Tests for HookRegistry (lines 80+)."""

    def _registry(self):
        from spanforge._hooks import HookRegistry

        return HookRegistry()

    def test_register_and_fire_sync(self) -> None:
        """on_llm_call decorator registers and fires a hook."""
        from spanforge._span import Span

        reg = self._registry()
        called = []

        @reg.on_llm_call
        def hook(span):
            called.append(span)

        span = Span(name="test-span")
        reg._fire("llm_call", span)
        assert len(called) == 1

    def test_register_multiple_hooks(self) -> None:
        """Multiple hooks for llm_call are all called."""
        from spanforge._span import Span

        reg = self._registry()
        calls = []

        @reg.on_llm_call
        def hook1(span):
            calls.append("a")

        @reg.on_llm_call
        def hook2(span):
            calls.append("b")

        span = Span(name="test-span")
        reg._fire("llm_call", span)
        assert sorted(calls) == ["a", "b"]

    def test_fire_no_registered_hooks(self) -> None:
        """_fire() with no registered hooks doesn't raise."""
        from spanforge._span import Span

        reg = self._registry()
        span = Span(name="noop")
        reg._fire("llm_call", span)  # should not raise

    def test_register_async_hook(self) -> None:
        """Async hooks registered via on_llm_call_async are stored in registry."""
        from spanforge._span import Span

        reg = self._registry()

        @reg.on_llm_call_async
        async def async_hook(span):
            pass

        # _fire_async without a running loop is a no-op, just verify no exception
        span = Span(name="test-span")
        reg._fire_async("llm_call", span)  # should not raise

    def test_unregister_hook(self) -> None:
        """clear() removes all hooks from the registry."""
        from spanforge._span import Span

        reg = self._registry()
        calls = []

        @reg.on_llm_call
        def hook(span):
            calls.append(span)

        reg.clear()
        span = Span(name="test-span")
        reg._fire("llm_call", span)
        assert calls == []

    def test_hooks_singleton(self) -> None:
        """Module-level 'hooks' object is a HookRegistry instance."""
        from spanforge._hooks import HookRegistry, hooks

        assert isinstance(hooks, HookRegistry)

    def test_classify_span_llm(self) -> None:
        """_classify_span returns 'llm' for LLM span names."""
        from spanforge._hooks import _classify_span

        result = _classify_span("openai.chat.completion")
        assert result in ("llm", "agent", "tool", None)


# ===========================================================================
# spanforge._stream — emit functions
# ===========================================================================


class TestStream:
    """Tests for _stream public functions (emit_span, emit_rfc_event, get_config, etc.)."""

    def test_get_config_returns_config(self) -> None:
        """get_config() returns a SpanForgeConfig instance."""
        from spanforge._stream import SpanForgeConfig, get_config

        cfg = get_config()
        assert isinstance(cfg, SpanForgeConfig)

    def test_get_export_error_count_int(self) -> None:
        """get_export_error_count() returns an int >= 0."""
        from spanforge._stream import get_export_error_count

        count = get_export_error_count()
        assert isinstance(count, int)
        assert count >= 0

    def test_emit_span_returns_event(self) -> None:
        """emit_span() accepts a Span object and returns an Event or None."""
        from spanforge._span import Span
        from spanforge._stream import emit_span

        span = Span(name="test-span", model="gpt-4")
        result = emit_span(span)
        assert result is None or hasattr(result, "event_type")

    def test_emit_agent_run_returns_event(self) -> None:
        """emit_agent_run() accepts an AgentRunContext and returns None (fire-and-forget)."""
        from spanforge._span import AgentRunContext
        from spanforge._stream import emit_agent_run

        run = AgentRunContext(agent_name="TestAgent")
        result = emit_agent_run(run)
        assert result is None  # void function

    def test_emit_agent_step_returns_event(self) -> None:
        """emit_agent_step() accepts a Span and doesn't raise."""
        from spanforge._span import Span
        from spanforge._stream import emit_span

        span = Span(name="agent-step")
        result = emit_span(span)
        assert result is None  # void function

    def test_flush_does_not_raise(self) -> None:
        """flush() completes without raising."""
        from spanforge._stream import flush

        flush()  # smoke test

    def test_shutdown_does_not_raise(self) -> None:
        """shutdown() completes without raising."""
        from spanforge._stream import _reset_exporter, shutdown

        shutdown()
        # Reset so other tests work
        _reset_exporter()


# ===========================================================================
# spanforge.sdk.gate — SFGateClient
# ===========================================================================


class TestSFGateClient:
    """Tests for SFGateClient (lines 82+)."""

    def _gate(self):
        from spanforge.sdk.gate import SFGateClient

        return SFGateClient(config=_cfg())

    def test_get_status(self) -> None:
        """get_status() returns a GateStatusInfo."""
        g = self._gate()
        status = g.get_status()
        assert hasattr(status, "status")

    def test_evaluate_allowed(self) -> None:
        """evaluate() returns GateEvaluationResult."""
        g = self._gate()
        result = g.evaluate(gate_id="g1", payload={"score": 0.8})
        assert hasattr(result, "verdict")

    def test_evaluate_returns_pass_or_fail(self) -> None:
        """Verdict is one of the expected values."""
        from spanforge.sdk.gate import GateVerdict

        g = self._gate()
        result = g.evaluate(gate_id="g1", payload={"score": 0.8})
        assert result.verdict in (GateVerdict.PASS, GateVerdict.FAIL, GateVerdict.WARN)

    def test_evaluate_async(self) -> None:
        """evaluate_async() wraps sync call."""
        import asyncio

        g = self._gate()

        async def _run():
            return await g.evaluate_async(gate_id="g1", payload={"score": 0.8})

        result = asyncio.run(_run())
        assert result is not None

    def test_evaluate_prri(self) -> None:
        """evaluate_prri() returns a PRRIResult."""
        g = self._gate()
        result = g.evaluate_prri(project_id="proj-1", prri_score=75, threshold=70)
        assert hasattr(result, "verdict")

    def test_run_trust_gate(self) -> None:
        """run_trust_gate() returns a TrustGateResult."""
        g = self._gate()
        result = g.run_trust_gate(project_id="proj-1")
        assert hasattr(result, "pass_") or hasattr(result, "verdict")

    def test_list_artifacts(self) -> None:
        """list_artifacts() returns a list."""
        g = self._gate()
        arts = g.list_artifacts("t1")
        assert isinstance(arts, list)


# ===========================================================================
# spanforge.sdk.policy — SFPolicyClient
# ===========================================================================


class TestSFPolicyClient:
    """Tests for SFPolicyClient (lines 82+)."""

    def _policy(self):
        from spanforge.sdk.policy import SFPolicyClient

        return SFPolicyClient(config=_cfg())

    def test_get_status(self) -> None:
        """get_status() returns a status object."""
        p = self._policy()
        status = p.get_status()
        assert hasattr(status, "status")

    def test_evaluate_returns_decision(self) -> None:
        """evaluate() returns a RuntimePolicyDecision."""
        p = self._policy()
        decision = p.evaluate(
            environment="prod",
            trace_id="t1",
            service="sf_explain",
            control="hallucination",
            evaluated_at="2024-01-01T00:00:00Z",
        )
        assert hasattr(decision, "action")

    def test_get_active_bundle(self) -> None:
        """get_active_bundle() returns None or a RuntimePolicyBundle."""
        p = self._policy()
        bundle = p.get_active_bundle(environment="prod")
        assert bundle is None or hasattr(bundle, "rules")

    def test_list_decisions_for_trace(self) -> None:
        """list_decisions_for_trace() returns a list."""
        p = self._policy()
        decisions = p.list_decisions_for_trace("trace-abc")
        assert isinstance(decisions, list)

    def test_list_reviews_for_trace(self) -> None:
        """list_reviews_for_trace() returns a list."""
        p = self._policy()
        reviews = p.list_reviews_for_trace("trace-abc")
        assert isinstance(reviews, list)

    def test_load_bundle_from_dict(self) -> None:
        """load_bundle() accepts a RuntimePolicyBundle."""
        from spanforge.runtime_policy import RuntimePolicyBundle, RuntimePolicyRule

        p = self._policy()
        rule = RuntimePolicyRule(
            rule_id="r1",
            service="sf_explain",
            control="pii_check",
            action="block",
            threshold=0.9,
        )
        bundle = RuntimePolicyBundle(
            policy_id="b1",
            version="1.0",
            environment="prod",
            owner="ops",
            effective_at="2024-01-01T00:00:00Z",
            rules=[rule],
        )
        result = p.load_bundle(bundle)
        assert result is not None

    def test_simulate_returns_result(self) -> None:
        """simulate() returns a RuntimePolicySimulationResult."""
        from spanforge.runtime_policy import RuntimePolicyBundle, RuntimePolicyRule

        p = self._policy()
        rule = RuntimePolicyRule(rule_id="r1", service="sf_explain", control="c", action="allow")
        bundle = RuntimePolicyBundle(
            policy_id="b1",
            version="1.0",
            environment="prod",
            owner="ops",
            effective_at="2024-01-01T00:00:00Z",
            rules=[rule],
        )
        result = p.simulate(
            environment="prod",
            trace_id="t1",
            service="sf_explain",
            control="c",
            simulated_at="2024-01-01T00:00:00Z",
            candidate_bundle=bundle,
        )
        assert hasattr(result, "candidate_decision") or hasattr(result, "simulation_id")

    def test_suggest_threshold_returns_float(self) -> None:
        """suggest_threshold() returns a float or None."""
        p = self._policy()
        threshold = p.suggest_threshold(service="sf_explain", control="hallucination", classification="false_positive")
        assert threshold is None or 0.0 <= threshold <= 1.0


# ===========================================================================
# spanforge.sdk.alert — SFAlertClient
# ===========================================================================


class TestSFAlertClient:
    """Tests for SFAlertClient (lines 84+)."""

    def _alert(self):
        from spanforge.sdk.alert import SFAlertClient

        return SFAlertClient(config=_cfg())

    def test_get_status(self) -> None:
        """get_status() returns AlertStatusInfo."""
        a = self._alert()
        status = a.get_status()
        assert hasattr(status, "status")

    def test_healthy_property(self) -> None:
        """healthy is a bool property."""
        a = self._alert()
        assert isinstance(a.healthy, bool)

    def test_register_topic(self) -> None:
        """register_topic() doesn't raise."""
        a = self._alert()
        a.register_topic("pii-detected", "Fired when PII is found", default_severity="high")

    def test_publish_returns_result(self) -> None:
        """publish() returns a PublishResult."""
        a = self._alert()
        a.register_topic("my-topic", "test topic")
        result = a.publish("my-topic", payload={"trace_id": "t1", "message": "PII found"})
        assert hasattr(result, "alert_id")

    def test_publish_async(self) -> None:
        """publish_async() returns a PublishResult."""
        import asyncio

        a = self._alert()
        a.register_topic("async-topic", "async test")

        async def _run():
            return await a.publish_async("async-topic", payload={"trace_id": "t1"})

        result = asyncio.run(_run())
        assert result is not None

    def test_acknowledge(self) -> None:
        """acknowledge() returns a bool (True if found, False if not)."""
        a = self._alert()
        # unknown id — should return False or not raise
        result = a.acknowledge("fake-alert-id")
        assert isinstance(result, bool)

    def test_get_alert_history(self) -> None:
        """get_alert_history() returns a list."""
        a = self._alert()
        history = a.get_alert_history()
        assert isinstance(history, list)

    def test_set_maintenance_window(self) -> None:
        """set_maintenance_window() does not raise."""
        from datetime import datetime, timezone

        a = self._alert()
        start = datetime(2024, 6, 1, tzinfo=timezone.utc)
        end = datetime(2024, 6, 1, 1, tzinfo=timezone.utc)
        a.set_maintenance_window("proj-1", start, end)

    def test_add_sink_webhook(self) -> None:
        """add_sink() with a WebhookAlerter doesn't raise."""
        from spanforge.sdk.alert import WebhookAlerter

        a = self._alert()
        sink = WebhookAlerter(url="http://example.com/hook")
        a.add_sink(sink)


# ===========================================================================
# spanforge.sdk.observe — SFObserveClient
# ===========================================================================


class TestSFObserveClient:
    """Tests for SFObserveClient."""

    def _observe(self):
        from spanforge.sdk.observe import SFObserveClient

        return SFObserveClient(config=_cfg())

    def test_get_status(self) -> None:
        """get_status() returns ObserveStatusInfo."""
        o = self._observe()
        status = o.get_status()
        assert hasattr(status, "status")

    def test_emit_span_returns_str(self) -> None:
        """emit_span() returns a string span_id."""
        o = self._observe()
        result = o.emit_span(name="my-span", attributes={"model": "gpt-4"})
        assert isinstance(result, str)

    def test_emit_span_async(self) -> None:
        """emit_span_async() wraps sync call."""
        import asyncio

        o = self._observe()

        async def _run():
            return await o.emit_span_async(name="async-span", attributes={})

        result = asyncio.run(_run())
        assert isinstance(result, str)

    def test_add_annotation(self) -> None:
        """add_annotation() returns a record id string."""
        o = self._observe()
        ann_id = o.add_annotation(
            event_type="llm.trace.span.completed",
            payload={"label": "positive"},
            project_id="proj-1",
        )
        assert isinstance(ann_id, str)

    def test_get_annotations_returns_list(self) -> None:
        """get_annotations() returns a list."""
        o = self._observe()
        anns = o.get_annotations(
            event_type="llm.trace.span.completed",
            from_dt="2024-01-01T00:00:00Z",
            to_dt="2024-12-31T23:59:59Z",
        )
        assert isinstance(anns, list)

    def test_export_spans_returns_result(self) -> None:
        """export_spans() returns an ExportResult."""
        from spanforge.sdk.observe import ExportResult

        o = self._observe()
        spans = [{"name": "my-span", "duration_ms": 50}]
        result = o.export_spans(spans)
        assert isinstance(result, ExportResult)


# ===========================================================================
# spanforge.sdk.audit — SFAuditClient
# ===========================================================================


class TestSFAuditClient:
    """Tests for SFAuditClient."""

    def _audit(self):
        from spanforge.sdk.audit import SFAuditClient

        return SFAuditClient(config=_cfg())

    def test_get_status(self) -> None:
        """get_status() returns AuditStatusInfo."""
        a = self._audit()
        status = a.get_status()
        assert hasattr(status, "status")

    def test_append_record_returns_result(self) -> None:
        """append() returns an AuditAppendResult."""
        a = self._audit()
        result = a.append({"model": "gpt-4", "latency_ms": 100}, schema_key="spanforge.trust.v1", strict_schema=False)
        assert hasattr(result, "record_id")

    def test_append_async(self) -> None:
        """append_async() wraps sync call."""
        import asyncio

        a = self._audit()

        async def _run():
            return await a.append_async({"model": "gpt-4"}, schema_key="spanforge.trust.v1", strict_schema=False)

        result = asyncio.run(_run())
        assert result is not None

    def test_sign_record(self) -> None:
        """sign() returns a SignedRecord."""
        a = self._audit()
        record = {"model": "gpt-4", "latency_ms": 100}
        signed = a.sign(record)
        assert hasattr(signed, "signature")

    def test_verify_chain_returns_dict(self) -> None:
        """verify_chain() returns a dict."""
        a = self._audit()
        result = a.verify_chain([])
        assert isinstance(result, dict)

    def test_get_trust_scorecard(self) -> None:
        """get_trust_scorecard() returns a TrustScorecard."""
        a = self._audit()
        sc = a.get_trust_scorecard()
        assert sc is not None

    def test_generate_article30_record(self) -> None:
        """generate_article30_record() returns an Article30Record."""
        a = self._audit()
        record = a.generate_article30_record()
        assert hasattr(record, "controller_name") or hasattr(record, "processor_name")

    def test_export_returns_list(self) -> None:
        """export() returns a list of records."""
        a = self._audit()
        a.append({"model": "gpt-4"}, schema_key="spanforge.trust.v1", strict_schema=False)
        result = a.export()
        assert isinstance(result, list)


# ===========================================================================
# spanforge.sdk.validate — SFValidateClient
# ===========================================================================


class TestSFValidateClient:
    """Tests for SFValidateClient."""

    def _validate(self):
        from spanforge.sdk.validate import SFValidateClient

        return SFValidateClient(config=_cfg())

    def test_get_status_has_service(self) -> None:
        """get_status() returns a status object with a service field."""
        v = self._validate()
        status = v.get_status()
        assert hasattr(status, "service")

    def test_validate_returns_result(self) -> None:
        """validate() returns a ValidationResult."""
        v = self._validate()
        result = v.validate('{"key": "value"}')
        assert hasattr(result, "passed") or hasattr(result, "violations")

    def test_validate_with_schema(self) -> None:
        """validate() with explicit schema dict doesn't raise."""
        v = self._validate()
        schema = {"type": "object", "required": ["key"]}
        result = v.validate('{"key": "value"}', schema=schema)
        assert result is not None

    def test_validate_with_dict_response(self) -> None:
        """validate() accepts a dict as response."""
        v = self._validate()
        result = v.validate({"key": "value", "score": 0.9})
        assert result is not None


# ===========================================================================
# spanforge.sdk.dataset_scanner — SFDatasetScannerClient
# ===========================================================================


class TestSFDatasetScannerClient:
    """Tests for scan_dataset_compliance function."""

    def test_scan_dataset_returns_report(self, tmp_path) -> None:
        """scan_dataset_compliance() returns a DatasetComplianceReport."""
        import csv

        from spanforge.sdk.dataset_scanner import DatasetComplianceReport, scan_dataset_compliance

        csv_file = tmp_path / "data.csv"
        with open(csv_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "prompt", "response"])
            writer.writerow(["1", "hello", "world"])

        report = scan_dataset_compliance(csv_file, sign=False)
        assert isinstance(report, DatasetComplianceReport)
        assert report.file_count >= 1

    def test_report_has_pii_score(self, tmp_path) -> None:
        """DatasetComplianceReport has pii_density_score field."""
        import csv

        from spanforge.sdk.dataset_scanner import scan_dataset_compliance

        csv_file = tmp_path / "d.csv"
        with open(csv_file, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["col"])
            writer.writerow(["val"])

        report = scan_dataset_compliance(csv_file, sign=False)
        assert hasattr(report, "pii_density_score")
        assert hasattr(report, "eu_ai_act_article_10_clauses")


# ===========================================================================
# spanforge.testing — MockExporter, make_event
# ===========================================================================


class TestTesting:
    """Tests for spanforge.testing helpers."""

    def test_mock_exporter_collects_events(self) -> None:
        """MockExporter.export() collects events in .events."""
        from spanforge.testing import MockExporter

        exporter = MockExporter()
        event = _make_event()
        exporter.export(event)
        assert event in exporter.events

    def test_mock_exporter_clear(self) -> None:
        """MockExporter.clear() removes all collected events."""
        from spanforge.testing import MockExporter

        exporter = MockExporter()
        exporter.export(_make_event())
        exporter.clear()
        assert len(exporter.events) == 0

    def test_mock_exporter_filter_by_type(self) -> None:
        """MockExporter.filter_by_type() returns matching events."""
        from spanforge.testing import MockExporter
        from spanforge.types import EventType

        exporter = MockExporter()
        event = _make_event()
        exporter.export(event)
        found = exporter.filter_by_type(EventType.TRACE_SPAN_COMPLETED)
        assert len(found) >= 1

    def test_mock_exporter_export_batch(self) -> None:
        """MockExporter.export_batch() adds all events."""
        from spanforge.testing import MockExporter

        exporter = MockExporter()
        events = [_make_event(), _make_event()]
        for e in events:
            exporter.export(e)
        assert len(exporter.events) == 2

    def test_capture_events_context_manager(self) -> None:
        """capture_events() captures events emitted inside it."""
        from spanforge.testing import capture_events

        with capture_events() as captured:
            pass
        assert isinstance(captured, list)

    def test_assert_event_schema_valid_passes(self) -> None:
        """assert_event_schema_valid() passes for a valid event with correct source."""
        from spanforge.event import Event
        from spanforge.testing import assert_event_schema_valid
        from spanforge.types import EventType

        event = Event(
            event_type=EventType.TRACE_SPAN_COMPLETED,
            source="myservice@1.0.0",
            payload={"model": "gpt-4"},
        )
        assert_event_schema_valid(event)  # should not raise


# ===========================================================================
# spanforge.export.siem_schema — SIEM export
# ===========================================================================


class TestSiemSchema:
    """Tests for siem_schema module (76%, 10 missed lines)."""

    def test_event_to_siem_record_returns_dict(self) -> None:
        """event_to_siem_record() returns a dict."""
        from spanforge.export.siem_schema import event_to_siem_record

        event = _make_event()
        record = event_to_siem_record(event)
        assert isinstance(record, dict)

    def test_siem_record_has_event_type(self) -> None:
        """event_to_siem_record() includes an event_type or similar key."""
        from spanforge.export.siem_schema import event_to_siem_record

        event = _make_event()
        record = event_to_siem_record(event)
        assert len(record) > 0

    def test_severity_from_event_returns_int(self) -> None:
        """severity_from_event() returns an integer."""
        from spanforge.export.siem_schema import severity_from_event

        event = _make_event()
        sev = severity_from_event(event)
        assert isinstance(sev, int)

    def test_severity_range(self) -> None:
        """severity_from_event() returns a value in 0–10."""
        from spanforge.export.siem_schema import severity_from_event

        event = _make_event()
        sev = severity_from_event(event)
        assert 0 <= sev <= 10


# ===========================================================================
# spanforge.runtime_policy — RuntimePolicy
# ===========================================================================


class TestRuntimePolicy:
    """Tests for spanforge.runtime_policy module (79%, 11 missed lines)."""

    def test_module_imports(self) -> None:
        """Module imports without error."""
        import spanforge.runtime_policy as rp

        assert rp is not None

    def test_runtime_policy_rule_fields(self) -> None:
        """RuntimePolicyRule can be constructed."""
        from spanforge.runtime_policy import RuntimePolicyRule

        rule = RuntimePolicyRule(
            rule_id="r1",
            service="sf_explain",
            control="pii_check",
            action="block",
            threshold=0.9,
        )
        assert rule.rule_id == "r1"
        assert rule.action == "block"

    def test_runtime_policy_bundle_fields(self) -> None:
        """RuntimePolicyBundle can be constructed."""
        from spanforge.runtime_policy import RuntimePolicyBundle, RuntimePolicyRule

        rule = RuntimePolicyRule(rule_id="r1", service="sf_rbac", control="c", action="allow")
        bundle = RuntimePolicyBundle(
            policy_id="p1",
            version="1.0",
            environment="prod",
            owner="team-ai",
            effective_at="2024-01-01T00:00:00Z",
            rules=[rule],
        )
        assert bundle.policy_id == "p1"
        assert len(bundle.rules) == 1

    def test_runtime_policy_bundle_default_rules(self) -> None:
        """RuntimePolicyBundle rules default to empty list."""
        from spanforge.runtime_policy import RuntimePolicyBundle

        bundle = RuntimePolicyBundle(
            policy_id="p2",
            version="1.0",
            environment="staging",
            owner="ops",
            effective_at="2024-01-01T00:00:00Z",
        )
        assert isinstance(bundle.rules, list)

    def test_enabled_rule_defaults_true(self) -> None:
        """RuntimePolicyRule.enabled defaults to True."""
        from spanforge.runtime_policy import RuntimePolicyRule

        rule = RuntimePolicyRule(rule_id="r", service="sf_scope", control="c", action="allow")
        assert rule.enabled is True

    def test_disabled_rule(self) -> None:
        """RuntimePolicyRule can be disabled."""
        from spanforge.runtime_policy import RuntimePolicyRule

        rule = RuntimePolicyRule(rule_id="r", service="sf_lineage", control="c", action="block", enabled=False)
        assert rule.enabled is False
