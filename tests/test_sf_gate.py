"""tests/test_sf_gate.py — Phase 8 CI/CD Gate Pipeline (sf-gate) test suite.

Coverage target: ≥90 % of src/spanforge/gate.py and src/spanforge/sdk/gate.py.

All tests are pure unit tests using stdlib mocks only.  No external services,
no filesystem side effects (temporary directories are used where needed).
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from spanforge.gate import (
    GateConfig,
    GateResult,
    GateRunner,
    GateRunResult,
    GateVerdict,
    _evaluate_pass_condition,
    _substitute_template,
    _validate_template_value,
    register_executor,
)
from spanforge.sdk._base import SFClientConfig
from spanforge.sdk._exceptions import (
    SFError,
    SFGateError,
    SFGateEvaluationError,
    SFGatePipelineError,
    SFGateSchemaError,
    SFGateTrustFailedError,
)
from spanforge.sdk._types import (
    GateArtifact,
    GateEvaluationResult,
    GateStatusInfo,
    PRRIResult,
    PRRIVerdict,
    TrustGateResult,
)
from spanforge.sdk._types import (
    GateVerdict as TypesGateVerdict,
)
from spanforge.sdk.gate import (
    _HRI_CRITICAL_THRESHOLD,
    _PRRI_AMBER_THRESHOLD,
    _PRRI_RED_THRESHOLD,
    GATE_KNOWN_TOPICS,
    SFGateClient,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(**kwargs: Any) -> SFClientConfig:
    return SFClientConfig(
        project_id=kwargs.get("project_id", "test-proj"),
        local_fallback_enabled=kwargs.get("local_fallback_enabled", True),
    )


def _make_client(tmp_dir: str | None = None, **kwargs: Any) -> SFGateClient:
    """Return an SFGateClient pointed at a temp artifact dir."""
    config = _make_config(**kwargs)
    client = SFGateClient(config)
    if tmp_dir:
        client._artifact_dir = Path(tmp_dir)
        client._artifact_dir.mkdir(parents=True, exist_ok=True)
    return client


# ===========================================================================
# Section 1 — GateVerdict constants
# ===========================================================================

class TestGateVerdict(unittest.TestCase):
    """Tests for GateVerdict string constants."""

    def test_pass_constant(self):
        self.assertEqual(GateVerdict.PASS, "PASS")

    def test_fail_constant(self):
        self.assertEqual(GateVerdict.FAIL, "FAIL")

    def test_warn_constant(self):
        self.assertEqual(GateVerdict.WARN, "WARN")

    def test_skipped_constant(self):
        self.assertEqual(GateVerdict.SKIPPED, "SKIPPED")

    def test_error_constant(self):
        self.assertEqual(GateVerdict.ERROR, "ERROR")

    def test_all_verdicts_are_strings(self):
        for attr in ("PASS", "FAIL", "WARN", "SKIPPED", "ERROR"):
            self.assertIsInstance(getattr(GateVerdict, attr), str)


class TestTypesGateVerdict(unittest.TestCase):
    """GateVerdict exported from _types matches gate.py constants."""

    def test_identical_pass(self):
        self.assertEqual(TypesGateVerdict.PASS, GateVerdict.PASS)

    def test_identical_fail(self):
        self.assertEqual(TypesGateVerdict.FAIL, GateVerdict.FAIL)

    def test_identical_warn(self):
        self.assertEqual(TypesGateVerdict.WARN, GateVerdict.WARN)

    def test_identical_skipped(self):
        self.assertEqual(TypesGateVerdict.SKIPPED, GateVerdict.SKIPPED)

    def test_identical_error(self):
        self.assertEqual(TypesGateVerdict.ERROR, GateVerdict.ERROR)


class TestPRRIVerdict(unittest.TestCase):
    """Tests for PRRIVerdict string constants."""

    def test_green_constant(self):
        self.assertEqual(PRRIVerdict.GREEN, "GREEN")

    def test_amber_constant(self):
        self.assertEqual(PRRIVerdict.AMBER, "AMBER")

    def test_red_constant(self):
        self.assertEqual(PRRIVerdict.RED, "RED")


# ===========================================================================
# Section 2 — Template substitution
# ===========================================================================

class TestValidateTemplateValue(unittest.TestCase):
    """_validate_template_value safe-char allowlist."""

    def test_safe_value_returned(self):
        self.assertEqual(_validate_template_value("branch", "refs/heads/main"), "refs/heads/main")

    def test_alphanumeric_ok(self):
        self.assertEqual(_validate_template_value("project", "my-project123"), "my-project123")

    def test_dots_and_slashes_ok(self):
        _validate_template_value("sha", "abc123/def456.xyz")

    def test_colon_ok(self):
        _validate_template_value("ts", "2024-01-01T00:00:00Z")

    def test_unsafe_semicolon_raises(self):
        with self.assertRaises(ValueError):
            _validate_template_value("bad", "val;rm -rf /")

    def test_unsafe_dollar_raises(self):
        with self.assertRaises(ValueError):
            _validate_template_value("bad", "$HARMFUL")

    def test_unsafe_backtick_raises(self):
        with self.assertRaises(ValueError):
            _validate_template_value("bad", "`whoami`")

    def test_unsafe_pipe_raises(self):
        with self.assertRaises(ValueError):
            _validate_template_value("bad", "foo|bar")


class TestSubstituteTemplate(unittest.TestCase):
    """_substitute_template placeholder expansion."""

    def test_single_variable(self):
        result = _substitute_template("hc risk --project {{ project }}", {"project": "myproj"})
        self.assertEqual(result, "hc risk --project myproj")

    def test_multiple_variables(self):
        tmpl = "hc run --project {{ project }} --sha {{ commit_sha }}"
        ctx = {"project": "myproj", "commit_sha": "abc123"}
        self.assertEqual(result := _substitute_template(tmpl, ctx),
                         "hc run --project myproj --sha abc123"), result

    def test_unknown_variable_left_in_place(self):
        result = _substitute_template("cmd {{ unknown_var }}", {})
        self.assertIn("{{ unknown_var }}", result)

    def test_no_substitution_needed(self):
        result = _substitute_template("plain command", {"project": "x"})
        self.assertEqual(result, "plain command")

    def test_injection_blocked_at_validate(self):
        """Unsafe value raises ValueError before substitution occurs."""
        with self.assertRaises(ValueError):
            _substitute_template("cmd {{ project }}", {"project": "x;rm -rf /"})

    def test_all_five_template_vars(self):
        tmpl = "{{ project }} {{ branch }} {{ commit_sha }} {{ pipeline_id }} {{ timestamp }}"
        ctx = {
            "project": "proj",
            "branch": "refs/heads/main",
            "commit_sha": "abc123",
            "pipeline_id": "ci-42",
            "timestamp": "2024-01-01T00:00:00",
        }
        result = _substitute_template(tmpl, ctx)
        self.assertEqual(result, "proj refs/heads/main abc123 ci-42 2024-01-01T00:00:00")


# ===========================================================================
# Section 3 — Pass condition evaluator
# ===========================================================================

class TestPassConditionEvaluator(unittest.TestCase):
    """_evaluate_pass_condition operator coverage."""

    # --- numeric comparisons ---
    def test_less_than_pass(self):
        self.assertTrue(_evaluate_pass_condition("< 70", 42))

    def test_less_than_fail(self):
        self.assertFalse(_evaluate_pass_condition("< 70", 70))

    def test_less_than_equal_pass(self):
        self.assertTrue(_evaluate_pass_condition("<= 70", 70))

    def test_greater_than_pass(self):
        self.assertTrue(_evaluate_pass_condition("> 0", 1))

    def test_greater_than_fail(self):
        self.assertFalse(_evaluate_pass_condition("> 5", 5))

    def test_greater_than_equal_pass(self):
        self.assertTrue(_evaluate_pass_condition(">= 5", 5))

    def test_equality_numeric(self):
        self.assertTrue(_evaluate_pass_condition("== 0", 0))

    def test_equality_numeric_fail(self):
        self.assertFalse(_evaluate_pass_condition("== 0", 1))

    def test_inequality_numeric(self):
        self.assertTrue(_evaluate_pass_condition("!= 0", 1))

    def test_inequality_fail(self):
        self.assertFalse(_evaluate_pass_condition("!= 0", 0))

    # --- string comparisons ---
    def test_equality_string(self):
        self.assertTrue(_evaluate_pass_condition("== passing", "passing"))

    def test_inequality_string(self):
        self.assertTrue(_evaluate_pass_condition("!= failing", "passing"))

    # --- boolean shorthands ---
    def test_bool_false_pass(self):
        self.assertTrue(_evaluate_pass_condition("false", False))

    def test_bool_false_fail_when_true(self):
        self.assertFalse(_evaluate_pass_condition("false", True))

    def test_bool_true_pass(self):
        self.assertTrue(_evaluate_pass_condition("true", True))

    def test_bool_true_fail_when_false(self):
        self.assertFalse(_evaluate_pass_condition("true", False))

    def test_bool_case_insensitive(self):
        self.assertTrue(_evaluate_pass_condition("FALSE", False))
        self.assertTrue(_evaluate_pass_condition("TRUE", True))

    def test_float_comparison(self):
        self.assertTrue(_evaluate_pass_condition("< 0.05", 0.04))
        self.assertFalse(_evaluate_pass_condition("< 0.05", 0.06))

    def test_unrecognised_expr_returns_false(self):
        self.assertFalse(_evaluate_pass_condition("SOME GARBAGE", 42))

    def test_type_mismatch_returns_false(self):
        self.assertFalse(_evaluate_pass_condition("< 10", "notanumber"))


# ===========================================================================
# Section 4 — GateConfig & GateResult dataclasses
# ===========================================================================

class TestGateConfigDefaults(unittest.TestCase):
    """GateConfig default field values."""

    def setUp(self):
        self.cfg = GateConfig(id="g1", name="Test Gate", type="schema_validation")

    def test_defaults_on_fail(self):
        self.assertEqual(self.cfg.on_fail, "block")

    def test_defaults_timeout(self):
        self.assertGreater(self.cfg.timeout_seconds, 0)

    def test_defaults_skip_on_empty(self):
        self.assertEqual(self.cfg.skip_on, [])

    def test_defaults_skip_on_draft_false(self):
        self.assertFalse(self.cfg.skip_on_draft)

    def test_defaults_parallel_false(self):
        self.assertFalse(self.cfg.parallel)

    def test_defaults_extra_empty_dict(self):
        self.assertEqual(self.cfg.extra, {})


class TestGateResultIsBlockingFailure(unittest.TestCase):
    """GateResult.is_blocking_failure() logic."""

    def _make_result(self, verdict: str) -> GateResult:
        return GateResult(
            gate_id="g1",
            name="Test",
            verdict=verdict,
            metrics={},
            timestamp="2024-01-01T00:00:00",
            duration_ms=100,
        )

    def _block_cfg(self) -> GateConfig:
        return GateConfig(id="g1", name="Test", type="schema_validation", on_fail="block")

    def _warn_cfg(self) -> GateConfig:
        return GateConfig(id="g1", name="Test", type="schema_validation", on_fail="warn")

    def test_fail_block_is_blocking(self):
        self.assertTrue(self._make_result(GateVerdict.FAIL).is_blocking_failure(self._block_cfg()))

    def test_fail_warn_not_blocking(self):
        self.assertFalse(self._make_result(GateVerdict.FAIL).is_blocking_failure(self._warn_cfg()))

    def test_pass_block_not_blocking(self):
        self.assertFalse(self._make_result(GateVerdict.PASS).is_blocking_failure(self._block_cfg()))

    def test_warn_block_not_blocking(self):
        self.assertFalse(self._make_result(GateVerdict.WARN).is_blocking_failure(self._block_cfg()))

    def test_error_block_not_blocking(self):
        self.assertFalse(self._make_result(GateVerdict.ERROR).is_blocking_failure(self._block_cfg()))


class TestGateRunResultProperties(unittest.TestCase):
    """GateRunResult.failed_gates and .passed_gates properties."""

    def _make_run(self, verdicts: list[str]) -> GateRunResult:
        gates = [
            GateResult(
                gate_id=f"g{i}",
                name=f"Gate {i}",
                verdict=v,
                metrics={},
                timestamp="2024-01-01T00:00:00",
                duration_ms=10,
            )
            for i, v in enumerate(verdicts)
        ]
        return GateRunResult(
            overall_pass=True,
            exit_code=0,
            gates=gates,
            duration_ms=100,
            run_id="test-run",
            config_path="sf-gate.yaml",
            started_at="2024-01-01T00:00:00",
            completed_at="2024-01-01T00:00:01",
        )

    def test_failed_gates_filters_fail(self):
        run = self._make_run(["PASS", "FAIL", "WARN"])
        self.assertEqual(len(run.failed_gates), 1)
        self.assertEqual(run.failed_gates[0].verdict, GateVerdict.FAIL)

    def test_passed_gates_filters_pass(self):
        run = self._make_run(["PASS", "FAIL", "PASS"])
        self.assertEqual(len(run.passed_gates), 2)

    def test_no_failures_empty_list(self):
        run = self._make_run(["PASS", "WARN"])
        self.assertEqual(run.failed_gates, [])


# ===========================================================================
# Section 5 — Artifact store
# ===========================================================================

class TestArtifactStoreWrite(unittest.TestCase):
    """_ArtifactStore write and prune."""

    def setUp(self):
        from spanforge.gate import _ArtifactStore
        self.tmp = tempfile.mkdtemp()
        self.store = _ArtifactStore(Path(self.tmp))

    def test_write_creates_file(self):
        cfg = GateConfig(id="g1", name="Gate 1", type="schema_validation")
        result = GateResult(
            gate_id="g1",
            name="Gate 1",
            verdict=GateVerdict.PASS,
            metrics={"schemas_checked": 1},
            timestamp="2024-01-01T00:00:00",
            duration_ms=50,
        )
        path = self.store.write(result, cfg)
        self.assertTrue(path.exists())

    def test_written_json_is_valid(self):
        cfg = GateConfig(id="g2", name="Gate 2", type="dependency_security")
        result = GateResult(
            gate_id="g2",
            name="Gate 2",
            verdict=GateVerdict.FAIL,
            metrics={"critical_cves": 2},
            timestamp="2024-01-01T00:00:00",
            duration_ms=80,
        )
        path = self.store.write(result, cfg)
        data = json.loads(path.read_text())
        self.assertEqual(data["gate_id"], "g2")
        self.assertEqual(data["verdict"], GateVerdict.FAIL)
        self.assertEqual(data["metrics"]["critical_cves"], 2)

    def test_prune_removes_old_artifacts(self):
        """Files older than 90 days should be removed on next write."""
        old_file = self.store._dir / "old_gate_result.json"
        old_file.write_text('{"gate_id": "old"}', encoding="utf-8")
        # Backdate the file to 91 days ago
        old_time = time.time() - (91 * 24 * 3600)
        os.utime(old_file, (old_time, old_time))

        cfg = GateConfig(id="g3", name="Gate 3", type="secrets_scan")
        result = GateResult(
            gate_id="g3",
            name="Gate 3",
            verdict=GateVerdict.PASS,
            metrics={},
            timestamp="2024-01-01T00:00:00",
            duration_ms=20,
        )
        self.store.write(result, cfg)
        self.assertFalse(old_file.exists(), "Old artifact should be pruned")

    def test_recent_artifacts_not_pruned(self):
        recent_file = self.store._dir / "recent_gate_result.json"
        recent_file.write_text('{"gate_id": "recent"}', encoding="utf-8")

        cfg = GateConfig(id="g4", name="Gate 4", type="schema_validation")
        result = GateResult(
            gate_id="g4",
            name="Gate 4",
            verdict=GateVerdict.PASS,
            metrics={},
            timestamp="2024-01-01T00:00:00",
            duration_ms=20,
        )
        self.store._pruned = False  # Reset so prune runs again
        self.store.write(result, cfg)
        self.assertTrue(recent_file.exists(), "Recent artifact should NOT be pruned")


# ===========================================================================
# Section 6 — GateRunner YAML parsing
# ===========================================================================

class TestGateRunnerYAMLParsing(unittest.TestCase):
    """_parse_yaml_gates handles valid and invalid YAML."""

    def setUp(self):
        from spanforge.gate import _parse_yaml_gates
        self._parse = _parse_yaml_gates

    def test_parses_single_gate(self):
        yaml_text = """
gates:
  - id: gate1_schema
    name: "Schema Validation"
    type: schema_validation
    on_fail: block
"""
        result = self._parse(yaml_text)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "gate1_schema")

    def test_parses_multiple_gates(self):
        yaml_text = """
gates:
  - id: g1
    name: "Gate 1"
    type: schema_validation
  - id: g2
    name: "Gate 2"
    type: dependency_security
"""
        result = self._parse(yaml_text)
        self.assertEqual(len(result), 2)

    def test_empty_gates_list(self):
        yaml_text = "gates: []\n"
        result = self._parse(yaml_text)
        self.assertEqual(result, [])

    def test_returns_list_for_invalid_top_level(self):
        result = self._parse("not: yaml: mapping")
        self.assertIsInstance(result, list)


class TestGateRunnerSequential(unittest.TestCase):
    """GateRunner.run() with sequential (non-parallel) gates."""

    def _write_gate_config(self, tmp_dir: str, content: str) -> str:
        path = os.path.join(tmp_dir, "sf-gate.yaml")
        Path(path).write_text(content, encoding="utf-8")
        return path

    def test_all_pass_returns_pass(self):
        yaml_content = """
gates:
  - id: gate1_schema
    name: "Schema Validation"
    type: schema_validation
    on_fail: block
    command: ""
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_gate_config(tmp, yaml_content)
            runner = GateRunner(base_dir=Path(tmp))
            result = runner.run(path, context={
                "project": "testproj",
                "branch": "refs/heads/main",
                "commit_sha": "abc123",
                "pipeline_id": "ci-1",
                "timestamp": "2024-01-01T00:00:00",
            })
            self.assertTrue(result.overall_pass)
            self.assertEqual(result.exit_code, 0)
            self.assertEqual(len(result.gates), 1)

    def test_blocking_fail_sets_exit_code_one(self):
        """A gate executor returning FAIL with on_fail=block → exit_code 1."""
        yaml_content = """
gates:
  - id: failing_gate
    name: "Always Fail"
    type: schema_validation
    on_fail: block
"""
        def _always_fail(cfg, context, timeout):
            return GateVerdict.FAIL, {"exit_code": 1}, "mocked fail"

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_gate_config(tmp, yaml_content)
            runner = GateRunner(base_dir=Path(tmp))
            with patch.dict("spanforge.gate._EXECUTOR_REGISTRY",
                            {"schema_validation": _always_fail}):
                result = runner.run(path, context={
                    "project": "testproj",
                    "branch": "refs/heads/main",
                    "commit_sha": "abc123",
                    "pipeline_id": "ci-1",
                    "timestamp": "2024-01-01T00:00:00",
                })
        self.assertFalse(result.overall_pass)
        self.assertEqual(result.exit_code, 1)

    def test_warn_gate_does_not_fail_pipeline(self):
        """A gate with on_fail=warn produces WARN verdict; pipeline still passes."""
        yaml_content = """
gates:
  - id: warn_gate
    name: "Warn Gate"
    type: schema_validation
    on_fail: warn
"""
        def _always_fail(cfg, context, timeout):
            return GateVerdict.FAIL, {"exit_code": 1}, "mocked fail"

        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_gate_config(tmp, yaml_content)
            runner = GateRunner(base_dir=Path(tmp))
            with patch.dict("spanforge.gate._EXECUTOR_REGISTRY",
                            {"schema_validation": _always_fail}):
                result = runner.run(path, context={
                    "project": "testproj",
                    "branch": "refs/heads/main",
                    "commit_sha": "abc123",
                    "pipeline_id": "ci-2",
                    "timestamp": "2024-01-01T00:00:00",
                })
        self.assertTrue(result.overall_pass)
        self.assertEqual(result.exit_code, 0)
        # warn gate should have WARN verdict
        gate_verdicts = {g.gate_id: g.verdict for g in result.gates}
        self.assertEqual(gate_verdicts["warn_gate"], GateVerdict.WARN)


class TestSkipConditions(unittest.TestCase):
    """GateRunner skip_on and skip_on_draft logic."""

    def _write_gate_config(self, tmp_dir: str, content: str) -> str:
        path = os.path.join(tmp_dir, "sf-gate.yaml")
        Path(path).write_text(content, encoding="utf-8")
        return path

    def test_skip_on_matching_branch(self):
        """Gate with skip_on matching branch produces SKIPPED verdict."""
        yaml_content = """
gates:
  - id: skippable
    name: "Skippable Gate"
    type: schema_validation
    on_fail: block
    skip_on:
      - "refs/heads/dependabot/*"
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_gate_config(tmp, yaml_content)
            runner = GateRunner(base_dir=Path(tmp))
            result = runner.run(path, context={
                "project": "testproj",
                "branch": "refs/heads/dependabot/pip/requests-3.0",
                "commit_sha": "abc123",
                "pipeline_id": "ci-3",
                "timestamp": "2024-01-01T00:00:00",
            })
            self.assertTrue(result.overall_pass)
            self.assertEqual(result.gates[0].verdict, GateVerdict.SKIPPED)

    def test_skip_on_non_matching_branch_runs_gate(self):
        """Gate skip_on NOT matching branch — gate executes normally."""
        yaml_content = """
gates:
  - id: runnable
    name: "Runnable Gate"
    type: schema_validation
    command: ""
    on_fail: block
    skip_on:
      - "refs/heads/dependabot/*"
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_gate_config(tmp, yaml_content)
            runner = GateRunner(base_dir=Path(tmp))
            result = runner.run(path, context={
                "project": "testproj",
                "branch": "refs/heads/main",
                "commit_sha": "abc123",
                "pipeline_id": "ci-4",
                "timestamp": "2024-01-01T00:00:00",
            })
            # Gate should not be SKIPPED
            self.assertNotEqual(result.gates[0].verdict, GateVerdict.SKIPPED)

    def test_skip_on_draft(self):
        """Gate with skip_on_draft=true skips when draft=true in context."""
        yaml_content = """
gates:
  - id: skip_draft
    name: "Skip Draft Gate"
    type: schema_validation
    on_fail: block
    skip_on_draft: true
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_gate_config(tmp, yaml_content)
            runner = GateRunner(base_dir=Path(tmp), is_draft=True)
            result = runner.run(path, context={
                "project": "testproj",
                "branch": "refs/heads/main",
                "commit_sha": "abc123",
                "pipeline_id": "ci-5",
                "timestamp": "2024-01-01T00:00:00",
            })
            self.assertEqual(result.gates[0].verdict, GateVerdict.SKIPPED)


class TestGateRunnerParallel(unittest.TestCase):
    """Parallel gate execution (parallel: true)."""

    def test_parallel_gates_all_complete(self):
        yaml_content = """
gates:
  - id: parallel_gate_1
    name: "Parallel 1"
    type: schema_validation
    command: ""
    on_fail: block
    parallel: true
  - id: parallel_gate_2
    name: "Parallel 2"
    type: schema_validation
    command: ""
    on_fail: block
    parallel: true
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sf-gate.yaml")
            Path(path).write_text(yaml_content, encoding="utf-8")
            runner = GateRunner(base_dir=Path(tmp))
            result = runner.run(path, context={
                "project": "testproj",
                "branch": "refs/heads/main",
                "commit_sha": "abc123",
                "pipeline_id": "ci-6",
                "timestamp": "2024-01-01T00:00:00",
            })
            self.assertEqual(len(result.gates), 2)
            ids = {g.gate_id for g in result.gates}
            self.assertIn("parallel_gate_1", ids)
            self.assertIn("parallel_gate_2", ids)


# ===========================================================================
# Section 7 — GateRunner run_id, timestamps, config_path
# ===========================================================================

class TestGateRunnerMetadata(unittest.TestCase):
    """GateRunResult metadata fields are populated."""

    def test_run_id_is_uuid_format(self):
        import re
        yaml_content = """
gates:
  - id: g1
    name: "Gate 1"
    type: schema_validation
    command: ""
    on_fail: block
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sf-gate.yaml")
            Path(path).write_text(yaml_content, encoding="utf-8")
            runner = GateRunner(base_dir=Path(tmp))
            result = runner.run(path, context={"project": "p"})
            uuid_pattern = re.compile(
                r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
                re.IGNORECASE,
            )
            self.assertRegex(result.run_id, uuid_pattern)

    def test_config_path_is_absolute(self):
        yaml_content = """
gates:
  - id: g1
    name: "Gate 1"
    type: schema_validation
    command: ""
    on_fail: block
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sf-gate.yaml")
            Path(path).write_text(yaml_content, encoding="utf-8")
            runner = GateRunner(base_dir=Path(tmp))
            result = runner.run(path, context={"project": "p"})
            self.assertTrue(os.path.isabs(result.config_path))

    def test_duration_ms_positive(self):
        yaml_content = """
gates:
  - id: g1
    name: "Gate 1"
    type: schema_validation
    command: ""
    on_fail: block
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sf-gate.yaml")
            Path(path).write_text(yaml_content, encoding="utf-8")
            runner = GateRunner(base_dir=Path(tmp))
            result = runner.run(path, context={"project": "p"})
            self.assertGreaterEqual(result.duration_ms, 0)


# ===========================================================================
# Section 8 — Custom executor registration
# ===========================================================================

class TestRegisterExecutor(unittest.TestCase):
    """register_executor() extension point."""

    def test_custom_executor_invoked(self):
        custom_called = []

        def my_executor(cfg, context, timeout):
            custom_called.append(True)
            return (GateVerdict.PASS, {"custom": True}, "custom passed")

        register_executor("my_custom_gate_type_unique_test", my_executor)

        yaml_content = """
gates:
  - id: custom_gate_test
    name: "Custom Gate"
    type: my_custom_gate_type_unique_test
    on_fail: block
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sf-gate.yaml")
            Path(path).write_text(yaml_content, encoding="utf-8")
            runner = GateRunner(base_dir=Path(tmp))
            result = runner.run(path, context={"project": "p"})
            self.assertTrue(custom_called, "Custom executor should have been invoked")
            self.assertEqual(result.gates[0].verdict, GateVerdict.PASS)


# ===========================================================================
# Section 9 — SFGateClient.evaluate()
# ===========================================================================

class TestSFGateClientEvaluate(unittest.TestCase):
    """SFGateClient.evaluate() — happy paths and error handling."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.client = _make_client(tmp_dir=self.tmp)

    def test_evaluate_pass_verdict_from_payload(self):
        result = self.client.evaluate(
            "gate5_governance",
            {"verdict": "PASS", "prri_score": 30},
            project_id="proj-a",
            pipeline_id="ci-1",
        )
        self.assertIsInstance(result, GateEvaluationResult)
        self.assertEqual(result.verdict, GateVerdict.PASS)
        self.assertEqual(result.gate_id, "gate5_governance")

    def test_evaluate_fail_verdict_from_payload(self):
        result = self.client.evaluate(
            "gate5_governance",
            {"verdict": "FAIL", "prri_score": 80},
            project_id="proj-a",
            pipeline_id="ci-1",
        )
        self.assertEqual(result.verdict, GateVerdict.FAIL)

    def test_evaluate_verdict_inferred_from_pass_key(self):
        """When 'pass': True in payload, verdict should be PASS."""
        result = self.client.evaluate(
            "gate1_schema",
            {"pass": True, "schemas_checked": 1},
            project_id="proj-a",
        )
        self.assertEqual(result.verdict, GateVerdict.PASS)

    def test_evaluate_verdict_inferred_from_failed_key(self):
        """When 'failed': True in payload, verdict should be FAIL."""
        result = self.client.evaluate(
            "gate2_deps",
            {"failed": True, "critical_cves": 2},
            project_id="proj-a",
        )
        self.assertEqual(result.verdict, GateVerdict.FAIL)

    def test_evaluate_artifact_written(self):
        gate_id = "gate_artifact_test"
        self.client.evaluate(gate_id, {"verdict": "PASS"}, project_id="p")
        artifact_path = self.client._artifact_path(gate_id)
        self.assertTrue(artifact_path.exists())

    def test_evaluate_artifact_contains_gate_id(self):
        gate_id = "gate_artifact_content_test"
        self.client.evaluate(gate_id, {"verdict": "PASS", "score": 42}, project_id="p")
        artifact_path = self.client._artifact_path(gate_id)
        data = json.loads(artifact_path.read_text())
        self.assertEqual(data["gate_id"], gate_id)

    def test_evaluate_increments_counter(self):
        initial = self.client._evaluate_count
        self.client.evaluate("gate_counter", {"verdict": "PASS"}, project_id="p")
        self.assertEqual(self.client._evaluate_count, initial + 1)

    def test_evaluate_updates_last_evaluate_at(self):
        self.assertIsNone(self.client._last_evaluate_at)
        self.client.evaluate("gate_ts", {"verdict": "PASS"}, project_id="p")
        self.assertIsNotNone(self.client._last_evaluate_at)

    def test_evaluate_empty_gate_id_raises(self):
        with self.assertRaises(SFGateEvaluationError):
            self.client.evaluate("", {"verdict": "PASS"}, project_id="p")

    def test_evaluate_returns_duration_ms(self):
        result = self.client.evaluate("gate_dur", {"verdict": "PASS"}, project_id="p")
        self.assertGreaterEqual(result.duration_ms, 0)

    def test_evaluate_artifact_url_has_file_scheme(self):
        result = self.client.evaluate("gate_url", {"verdict": "PASS"}, project_id="p")
        self.assertTrue(result.artifact_url.startswith("file://"))


# ===========================================================================
# Section 10 — SFGateClient path traversal prevention
# ===========================================================================

class TestSFGateClientPathTraversal(unittest.TestCase):
    """Artifact path traversal prevention."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.client = _make_client(tmp_dir=self.tmp)

    def test_dotdot_in_gate_id_sanitised(self):
        """gate_id with '..' characters should not escape the artifact dir."""
        # Should not raise; path traversal should be sanitised
        try:
            path = self.client._artifact_path("../../etc/passwd")
        except SFGateError:
            pass  # Expected if strict path validation
        else:
            # If it doesn't raise, verify path is within artifact dir
            self.assertTrue(
                str(path).startswith(str(self.client._artifact_dir.resolve()))
            )

    def test_slash_in_gate_id_sanitised(self):
        """gate_id with '/' characters should be safe-substituted."""
        path = self.client._artifact_path("gate/subdir")
        self.assertTrue(
            str(path.resolve()).startswith(str(self.client._artifact_dir.resolve()))
        )


# ===========================================================================
# Section 11 — SFGateClient.evaluate_prri()
# ===========================================================================

class TestEvaluatePRRI(unittest.TestCase):
    """SFGateClient.evaluate_prri() — GREEN / AMBER / RED thresholds."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.client = _make_client(tmp_dir=self.tmp)

    def _call(self, score: int, **kwargs: Any) -> PRRIResult:
        return self.client.evaluate_prri(
            "proj-a",
            prri_score=score,
            framework=kwargs.get("framework", "eu-ai-act"),
            policy_file=kwargs.get("policy_file", "policy.yaml"),
            dimension_breakdown=kwargs.get("dimension_breakdown", {}),
        )

    def test_green_below_amber_threshold(self):
        result = self._call(30)
        self.assertEqual(result.verdict, PRRIVerdict.GREEN)
        self.assertTrue(result.allow)

    def test_amber_at_amber_threshold(self):
        result = self._call(_PRRI_AMBER_THRESHOLD)
        self.assertEqual(result.verdict, PRRIVerdict.AMBER)
        self.assertTrue(result.allow)

    def test_amber_between_thresholds(self):
        result = self._call(55)
        self.assertEqual(result.verdict, PRRIVerdict.AMBER)
        self.assertTrue(result.allow)

    def test_red_at_red_threshold(self):
        result = self._call(_PRRI_RED_THRESHOLD)
        self.assertEqual(result.verdict, PRRIVerdict.RED)
        self.assertFalse(result.allow)

    def test_red_above_red_threshold(self):
        result = self._call(90)
        self.assertEqual(result.verdict, PRRIVerdict.RED)
        self.assertFalse(result.allow)

    def test_green_score_zero(self):
        result = self._call(0)
        self.assertEqual(result.verdict, PRRIVerdict.GREEN)
        self.assertTrue(result.allow)

    def test_result_has_correct_fields(self):
        result = self._call(25)
        self.assertEqual(result.gate_id, "gate5_governance")
        self.assertEqual(result.prri_score, 25)
        self.assertEqual(result.framework, "eu-ai-act")
        self.assertEqual(result.project_id, "proj-a")

    def test_prri_red_publishes_alert(self):
        """RED verdict attempts to publish sf-alert (best-effort, lazy)."""
        with patch("spanforge.sdk.gate.SFGateClient._publish_prri_alert") as mock_alert:
            self._call(_PRRI_RED_THRESHOLD)
            mock_alert.assert_called_once()

    def test_prri_amber_publishes_alert(self):
        with patch("spanforge.sdk.gate.SFGateClient._publish_prri_alert") as mock_alert:
            self._call(55)
            mock_alert.assert_called_once()

    def test_prri_green_no_alert(self):
        with patch("spanforge.sdk.gate.SFGateClient._publish_prri_alert") as mock_alert:
            self._call(20)
            mock_alert.assert_not_called()


# ===========================================================================
# Section 12 — SFGateClient.run_trust_gate()
# ===========================================================================

class TestSFGateClientRunTrustGate(unittest.TestCase):
    """SFGateClient.run_trust_gate() — HRI, PII, Secrets checks."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.client = _make_client(tmp_dir=self.tmp)

    def _make_mock_audit(
        self,
        hri_records: list[dict],
        pii_records: list[dict],
        secrets_records: list[dict],
    ) -> MagicMock:
        mock_audit = MagicMock()
        mock_audit.export = MagicMock(side_effect=[
            MagicMock(records=hri_records),
            MagicMock(records=pii_records),
            MagicMock(records=secrets_records),
        ])
        return mock_audit

    def test_trust_gate_passes_all_clean(self):
        """All checks clean → TrustGateResult with pass_=True."""
        with patch.object(self.client, "_compute_hri_critical_rate", return_value=(0.0, 100)), \
             patch.object(self.client, "_check_pii_window", return_value=(False, 0)), \
             patch.object(self.client, "_check_secrets_window", return_value=(False, 0)):
            result = self.client.run_trust_gate(
                "proj-a",
                pipeline_id="ci-10",
                hri_window=100,
                pii_window_hours=24,
                secrets_window_hours=24,
            )
        self.assertIsInstance(result, TrustGateResult)
        self.assertTrue(result.pass_)
        self.assertEqual(result.verdict, GateVerdict.PASS)
        self.assertEqual(result.failures, [])

    def test_trust_gate_fails_hri(self):
        """HRI critical rate above threshold → trust gate FAIL."""
        with patch.object(self.client, "_compute_hri_critical_rate", return_value=(0.10, 100)), \
             patch.object(self.client, "_check_pii_window", return_value=(False, 0)), \
             patch.object(self.client, "_check_secrets_window", return_value=(False, 0)), \
             patch.object(self.client, "_send_trust_gate_alert"):
            result = self.client.run_trust_gate(
                "proj-b",
                pipeline_id="ci-11",
                hri_window=100,
                pii_window_hours=24,
                secrets_window_hours=24,
            )
        self.assertFalse(result.pass_)
        self.assertEqual(result.verdict, GateVerdict.FAIL)
        self.assertTrue(any("HRI" in f or "hri" in f.lower() for f in result.failures))

    def test_trust_gate_fails_pii(self):
        """PII detected → trust gate FAIL."""
        with patch.object(self.client, "_compute_hri_critical_rate", return_value=(0.0, 100)), \
             patch.object(self.client, "_check_pii_window", return_value=(True, 3)), \
             patch.object(self.client, "_check_secrets_window", return_value=(False, 0)), \
             patch.object(self.client, "_send_trust_gate_alert"):
            result = self.client.run_trust_gate(
                "proj-c",
                pipeline_id="ci-12",
                hri_window=100,
                pii_window_hours=24,
                secrets_window_hours=24,
            )
        self.assertFalse(result.pass_)
        self.assertTrue(result.pii_detected)
        self.assertEqual(result.pii_detections_24h, 3)

    def test_trust_gate_fails_secrets(self):
        """Secrets detected → trust gate FAIL."""
        with patch.object(self.client, "_compute_hri_critical_rate", return_value=(0.0, 100)), \
             patch.object(self.client, "_check_pii_window", return_value=(False, 0)), \
             patch.object(self.client, "_check_secrets_window", return_value=(True, 1)), \
             patch.object(self.client, "_send_trust_gate_alert"):
            result = self.client.run_trust_gate(
                "proj-d",
                pipeline_id="ci-13",
                hri_window=100,
                pii_window_hours=24,
                secrets_window_hours=24,
            )
        self.assertFalse(result.pass_)
        self.assertTrue(result.secrets_detected)

    def test_trust_gate_increments_counter(self):
        initial = self.client._trust_gate_count
        with patch.object(self.client, "_compute_hri_critical_rate", return_value=(0.0, 100)), \
             patch.object(self.client, "_check_pii_window", return_value=(False, 0)), \
             patch.object(self.client, "_check_secrets_window", return_value=(False, 0)):
            self.client.run_trust_gate(
                "proj-e", pipeline_id="ci-14",
                hri_window=100, pii_window_hours=24, secrets_window_hours=24,
            )
        self.assertEqual(self.client._trust_gate_count, initial + 1)

    def test_trust_gate_has_timestamp(self):
        with patch.object(self.client, "_compute_hri_critical_rate", return_value=(0.0, 100)), \
             patch.object(self.client, "_check_pii_window", return_value=(False, 0)), \
             patch.object(self.client, "_check_secrets_window", return_value=(False, 0)):
            result = self.client.run_trust_gate(
                "proj-f", pipeline_id="ci-15",
                hri_window=100, pii_window_hours=24, secrets_window_hours=24,
            )
        self.assertIsNotNone(result.timestamp)

    def test_trust_gate_critical_rate_at_threshold_fails(self):
        """HRI rate exactly at threshold should FAIL."""
        with patch.object(self.client, "_compute_hri_critical_rate",
                          return_value=(_HRI_CRITICAL_THRESHOLD, 100)), \
             patch.object(self.client, "_check_pii_window", return_value=(False, 0)), \
             patch.object(self.client, "_check_secrets_window", return_value=(False, 0)), \
             patch.object(self.client, "_send_trust_gate_alert"):
            result = self.client.run_trust_gate(
                "proj-g", pipeline_id="ci-16",
                hri_window=100, pii_window_hours=24, secrets_window_hours=24,
            )
        self.assertFalse(result.pass_)


# ===========================================================================
# Section 13 — Trust gate alert deduplication
# ===========================================================================

class TestTrustGateAlertDedup(unittest.TestCase):
    """_send_trust_gate_alert is deduplicated within the 5-minute window."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.client = _make_client(tmp_dir=self.tmp)

    def test_alert_sent_on_first_failure(self):
        with patch("spanforge.sdk.gate.SFGateClient._send_trust_gate_alert") as mock_alert:
            with patch.object(self.client, "_compute_hri_critical_rate", return_value=(0.10, 100)), \
                 patch.object(self.client, "_check_pii_window", return_value=(False, 0)), \
                 patch.object(self.client, "_check_secrets_window", return_value=(False, 0)):
                self.client.run_trust_gate(
                    "proj-ded", pipeline_id="ci-ded",
                    hri_window=10, pii_window_hours=24, secrets_window_hours=24,
                )
            mock_alert.assert_called_once()

    def test_alert_dedup_key_format(self):
        """The dedup key should combine project_id and pipeline_id."""
        sent_keys = []

        def capture_dedup(project_id, pipeline_id, failures, **kwargs):
            key = f"{project_id}:{pipeline_id}"
            sent_keys.append(key)

        self.client._send_trust_gate_alert = capture_dedup

        with patch.object(self.client, "_compute_hri_critical_rate", return_value=(0.10, 100)), \
             patch.object(self.client, "_check_pii_window", return_value=(False, 0)), \
             patch.object(self.client, "_check_secrets_window", return_value=(False, 0)):
            self.client.run_trust_gate(
                "proj-key", pipeline_id="pipe-key",
                hri_window=10, pii_window_hours=24, secrets_window_hours=24,
            )

        self.assertIn("proj-key:pipe-key", sent_keys)


# ===========================================================================
# Section 14 — SFGateClient.list_artifacts() and get_status()
# ===========================================================================

class TestSFGateClientListArtifacts(unittest.TestCase):
    """SFGateClient.list_artifacts()."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.client = _make_client(tmp_dir=self.tmp)

    def _write_artifact(self, gate_id: str, verdict: str) -> None:
        data = {
            "gate_id": gate_id,
            "name": gate_id,
            "verdict": verdict,
            "metrics": {},
            "timestamp": "2024-01-01T00:00:00+00:00",
            "duration_ms": 100,
        }
        path = self.client._artifact_path(gate_id)
        path.write_text(json.dumps(data), encoding="utf-8")

    def test_empty_list_when_no_artifacts(self):
        results = self.client.list_artifacts("nonexistent_gate")
        self.assertEqual(results, [])

    def test_returns_artifact_for_written_gate(self):
        gate_id = "gate_list_test"
        self._write_artifact(gate_id, "PASS")
        results = self.client.list_artifacts(gate_id)
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], GateArtifact)
        self.assertEqual(results[0].gate_id, gate_id)

    def test_limit_respected(self):
        gate_id = "gate_limit_test"
        self._write_artifact(gate_id, "PASS")
        results = self.client.list_artifacts(gate_id, limit=1)
        self.assertLessEqual(len(results), 1)


class TestSFGateClientGetStatus(unittest.TestCase):
    """SFGateClient.get_status()."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.client = _make_client(tmp_dir=self.tmp)

    def test_returns_gate_status_info(self):
        status = self.client.get_status()
        self.assertIsInstance(status, GateStatusInfo)

    def test_status_ok_initially(self):
        status = self.client.get_status()
        self.assertEqual(status.status, "ok")

    def test_evaluate_count_zero_initially(self):
        status = self.client.get_status()
        self.assertEqual(status.evaluate_count, 0)

    def test_trust_gate_count_zero_initially(self):
        status = self.client.get_status()
        self.assertEqual(status.trust_gate_count, 0)

    def test_last_evaluate_at_none_initially(self):
        status = self.client.get_status()
        self.assertIsNone(status.last_evaluate_at)

    def test_artifact_dir_in_status(self):
        status = self.client.get_status()
        self.assertIsInstance(status.artifact_dir, str)

    def test_open_circuit_breakers_empty_initially(self):
        status = self.client.get_status()
        self.assertIsInstance(status.open_circuit_breakers, list)
        self.assertEqual(status.open_circuit_breakers, [])

    def test_evaluate_count_increments_after_call(self):
        self.client.evaluate("status_gate", {"verdict": "PASS"}, project_id="p")
        status = self.client.get_status()
        self.assertEqual(status.evaluate_count, 1)


# ===========================================================================
# Section 15 — Phase 8 exceptions hierarchy
# ===========================================================================

class TestGateExceptions(unittest.TestCase):
    """SFGate exception hierarchy and field storage."""

    def test_sfgate_error_is_sferror(self):
        self.assertTrue(issubclass(SFGateError, SFError))

    def test_sfgate_evaluation_error_is_sfgate_error(self):
        self.assertTrue(issubclass(SFGateEvaluationError, SFGateError))

    def test_sfgate_pipeline_error_is_sfgate_error(self):
        self.assertTrue(issubclass(SFGatePipelineError, SFGateError))

    def test_sfgate_trust_failed_error_is_sfgate_error(self):
        self.assertTrue(issubclass(SFGateTrustFailedError, SFGateError))

    def test_sfgate_schema_error_is_sfgate_error(self):
        self.assertTrue(issubclass(SFGateSchemaError, SFGateError))

    def test_evaluation_error_stores_detail(self):
        exc = SFGateEvaluationError("bad payload")
        self.assertEqual(exc.detail, "bad payload")
        self.assertIn("bad payload", str(exc))

    def test_pipeline_error_stores_failed_gates(self):
        exc = SFGatePipelineError(["gate1", "gate2"])
        self.assertEqual(exc.failed_gates, ["gate1", "gate2"])
        self.assertIn("gate1", str(exc))

    def test_trust_failed_error_stores_failures(self):
        exc = SFGateTrustFailedError(["HRI rate too high", "PII detected"])
        self.assertEqual(exc.failures, ["HRI rate too high", "PII detected"])
        self.assertIn("HRI rate too high", str(exc))

    def test_schema_error_stores_detail(self):
        exc = SFGateSchemaError("unknown gate type: foo")
        self.assertEqual(exc.detail, "unknown gate type: foo")
        self.assertIn("foo", str(exc))

    def test_exceptions_are_catchable_as_sferror(self):
        for exc_cls in (
            SFGateError,
            SFGateEvaluationError,
            SFGatePipelineError,
            SFGateTrustFailedError,
            SFGateSchemaError,
        ):
            with self.subTest(exc_cls=exc_cls.__name__):
                try:
                    if exc_cls == SFGateError:
                        raise exc_cls("test")
                    elif exc_cls == SFGatePipelineError:
                        raise exc_cls(["g1"])
                    elif exc_cls == SFGateTrustFailedError:
                        raise exc_cls(["failure"])
                    else:
                        raise exc_cls("test detail")
                except SFError:
                    pass  # Expected


# ===========================================================================
# Section 16 — Phase 8 types structure
# ===========================================================================

class TestGateTypeStructures(unittest.TestCase):
    """Phase 8 dataclass / type structures."""

    def test_gate_artifact_creation(self):
        artifact = GateArtifact(
            gate_id="g1",
            name="Gate 1",
            verdict=GateVerdict.PASS,
            metrics={"score": 42},
            timestamp="2024-01-01T00:00:00",
            duration_ms=100,
            artifact_path="/tmp/g1_result.json",
        )
        self.assertEqual(artifact.gate_id, "g1")
        self.assertEqual(artifact.verdict, GateVerdict.PASS)

    def test_gate_evaluation_result_creation(self):
        result = GateEvaluationResult(
            gate_id="g1",
            verdict=GateVerdict.FAIL,
            metrics={"prri_score": 80},
            artifact_url="file:///tmp/g1_result.json",
            duration_ms=50,
        )
        self.assertEqual(result.verdict, GateVerdict.FAIL)

    def test_prri_result_allow_false_on_red(self):
        result = PRRIResult(
            gate_id="gate5_governance",
            prri_score=75,
            verdict=PRRIVerdict.RED,
            dimension_breakdown={},
            framework="eu-ai-act",
            policy_file="policy.yaml",
            timestamp="2024-01-01T00:00:00",
            allow=False,
        )
        self.assertFalse(result.allow)
        self.assertEqual(result.verdict, PRRIVerdict.RED)

    def test_trust_gate_result_defaults_pass_true(self):
        result = TrustGateResult(
            gate_id="gate6_trust",
            verdict=GateVerdict.PASS,
            hri_critical_rate=0.01,
            hri_critical_threshold=0.05,
            pii_detected=False,
            pii_detections_24h=0,
            secrets_detected=False,
            secrets_detections_24h=0,
            failures=[],
            timestamp="2024-01-01T00:00:00",
            pipeline_id="ci-1",
            project_id="proj-a",
        )
        self.assertTrue(result.pass_)

    def test_gate_status_info_structure(self):
        status = GateStatusInfo(
            status="ok",
            evaluate_count=5,
            trust_gate_count=2,
            last_evaluate_at="2024-01-01T00:00:00",
            artifact_count=10,
            artifact_dir="/tmp/.sf-gate/artifacts",
            open_circuit_breakers=[],
        )
        self.assertEqual(status.status, "ok")
        self.assertEqual(status.evaluate_count, 5)


# ===========================================================================
# Section 17 — GATE_KNOWN_TOPICS
# ===========================================================================

class TestGateKnownTopics(unittest.TestCase):
    """GATE_KNOWN_TOPICS constant."""

    def test_is_frozenset(self):
        self.assertIsInstance(GATE_KNOWN_TOPICS, frozenset)

    def test_contains_trust_gate_failed(self):
        self.assertIn("halluccheck.trust_gate.failed", GATE_KNOWN_TOPICS)

    def test_contains_prri_red(self):
        self.assertIn("halluccheck.prri.red", GATE_KNOWN_TOPICS)

    def test_contains_prri_amber(self):
        self.assertIn("halluccheck.prri.amber", GATE_KNOWN_TOPICS)

    def test_contains_gate_blocked(self):
        self.assertIn("halluccheck.gate.blocked", GATE_KNOWN_TOPICS)

    def test_contains_secrets_leak(self):
        self.assertIn("halluccheck.secrets.leak", GATE_KNOWN_TOPICS)

    def test_contains_dependency_critical(self):
        self.assertIn("halluccheck.dependency.critical", GATE_KNOWN_TOPICS)

    def test_exactly_eight_topics(self):
        self.assertEqual(len(GATE_KNOWN_TOPICS), 8)


# ===========================================================================
# Section 18 — SDK exports (__init__.py)
# ===========================================================================

class TestSDKExports(unittest.TestCase):
    """Phase 8 symbols are accessible via spanforge.sdk.*"""

    def test_sf_gate_singleton_accessible(self):
        from spanforge.sdk import sf_gate
        self.assertIsInstance(sf_gate, SFGateClient)

    def test_sf_gate_client_in_all(self):
        from spanforge import sdk
        self.assertIn("SFGateClient", sdk.__all__)

    def test_gate_verdict_in_all(self):
        from spanforge import sdk
        self.assertIn("GateVerdict", sdk.__all__)

    def test_prri_verdict_in_all(self):
        from spanforge import sdk
        self.assertIn("PRRIVerdict", sdk.__all__)

    def test_gate_evaluation_result_in_all(self):
        from spanforge import sdk
        self.assertIn("GateEvaluationResult", sdk.__all__)

    def test_trust_gate_result_in_all(self):
        from spanforge import sdk
        self.assertIn("TrustGateResult", sdk.__all__)

    def test_prri_result_in_all(self):
        from spanforge import sdk
        self.assertIn("PRRIResult", sdk.__all__)

    def test_gate_status_info_in_all(self):
        from spanforge import sdk
        self.assertIn("GateStatusInfo", sdk.__all__)

    def test_gate_artifact_in_all(self):
        from spanforge import sdk
        self.assertIn("GateArtifact", sdk.__all__)

    def test_sfgate_error_in_all(self):
        from spanforge import sdk
        self.assertIn("SFGateError", sdk.__all__)

    def test_sfgate_evaluation_error_in_all(self):
        from spanforge import sdk
        self.assertIn("SFGateEvaluationError", sdk.__all__)

    def test_sfgate_pipeline_error_in_all(self):
        from spanforge import sdk
        self.assertIn("SFGatePipelineError", sdk.__all__)

    def test_sfgate_trust_failed_error_in_all(self):
        from spanforge import sdk
        self.assertIn("SFGateTrustFailedError", sdk.__all__)

    def test_sfgate_schema_error_in_all(self):
        from spanforge import sdk
        self.assertIn("SFGateSchemaError", sdk.__all__)

    def test_configure_rewires_sf_gate(self):
        from spanforge.sdk import configure
        config = _make_config()
        configure(config)
        from spanforge.sdk import sf_gate
        self.assertIsInstance(sf_gate, SFGateClient)


# ===========================================================================
# Section 19 — PRRI threshold constants
# ===========================================================================

class TestPRRIThresholdConstants(unittest.TestCase):
    """PRRI threshold constants have expected values."""

    def test_prri_red_threshold(self):
        self.assertEqual(_PRRI_RED_THRESHOLD, 70)

    def test_prri_amber_threshold(self):
        self.assertEqual(_PRRI_AMBER_THRESHOLD, 40)

    def test_hri_critical_threshold(self):
        self.assertAlmostEqual(_HRI_CRITICAL_THRESHOLD, 0.05)


# ===========================================================================
# Section 20 — Circuit breaker per gate sink
# ===========================================================================

class TestGateCircuitBreaker(unittest.TestCase):
    """Per-sink circuit breakers are created and tracked."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.client = _make_client(tmp_dir=self.tmp)

    def test_get_cb_creates_new_entry(self):
        cb = self.client._get_cb("my_sink")
        self.assertIsNotNone(cb)

    def test_get_cb_returns_same_instance(self):
        cb1 = self.client._get_cb("my_sink_2")
        cb2 = self.client._get_cb("my_sink_2")
        self.assertIs(cb1, cb2)

    def test_get_status_reports_open_cbs(self):
        import time as _time
        cb = self.client._get_cb("open_sink")
        # Open the circuit breaker by tripping it via its internal state
        cb._failures = 99
        cb._state = cb.OPEN
        cb._opened_at = _time.monotonic()  # prevent auto-reset
        status = self.client.get_status()
        self.assertIn("open_sink", status.open_circuit_breakers)


# ===========================================================================
# Section 21 — Audit integration schema
# ===========================================================================

class TestAuditIntegration(unittest.TestCase):
    """evaluate() appends audit record with halluccheck.gate.v1 schema."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.client = _make_client(tmp_dir=self.tmp)

    def test_audit_append_called_on_evaluate(self):
        audit_calls = []

        def fake_post_hooks(**kwargs):
            audit_calls.append(kwargs)

        with patch.object(self.client, "_post_evaluate_hooks", side_effect=fake_post_hooks):
            self.client.evaluate("gate_audit_test", {"verdict": "PASS"}, project_id="p")

        self.assertEqual(len(audit_calls), 1)
        self.assertEqual(audit_calls[0]["gate_id"], "gate_audit_test")


# ===========================================================================
# Section 22 — Observe integration
# ===========================================================================

class TestObserveIntegration(unittest.TestCase):
    """evaluate() emits hc.gate.evaluated span (best-effort)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.client = _make_client(tmp_dir=self.tmp)

    def test_post_evaluate_hooks_called(self):
        """_post_evaluate_hooks is invoked on successful evaluate()."""
        with patch.object(self.client, "_post_evaluate_hooks") as mock_hooks:
            self.client.evaluate("gate_obs_test", {"verdict": "PASS"}, project_id="proj")
            mock_hooks.assert_called_once()

    def test_post_evaluate_hooks_receives_gate_id(self):
        captured = {}

        def capture(**kwargs):
            captured.update(kwargs)

        with patch.object(self.client, "_post_evaluate_hooks", side_effect=capture):
            self.client.evaluate("gate_obs_capture", {"verdict": "WARN"}, project_id="p")

        self.assertEqual(captured.get("gate_id"), "gate_obs_capture")


# ===========================================================================
# Section 23 — Exit codes
# ===========================================================================

class TestExitCodes(unittest.TestCase):
    """GateRunResult exit_code is 0 on all-pass, 1 on blocking failure."""

    def _run_yaml(self, yaml_text: str, mock_fail: bool = False) -> GateRunResult:
        def _always_fail(cfg, context, timeout):
            return GateVerdict.FAIL, {"exit_code": 1}, "mocked fail"

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sf-gate.yaml")
            Path(path).write_text(yaml_text, encoding="utf-8")
            runner = GateRunner(base_dir=Path(tmp))
            if mock_fail:
                with patch.dict("spanforge.gate._EXECUTOR_REGISTRY",
                                {"schema_validation": _always_fail}):
                    return runner.run(path, context={"project": "p"})
            return runner.run(path, context={"project": "p"})

    def test_exit_code_zero_when_all_pass(self):
        yaml_text = """
gates:
  - id: pass_gate
    name: "Pass Gate"
    type: schema_validation
    command: ""
    on_fail: block
"""
        result = self._run_yaml(yaml_text)
        self.assertEqual(result.exit_code, 0)

    def test_exit_code_one_when_blocking_fail(self):
        yaml_text = """
gates:
  - id: fail_gate
    name: "Fail Gate"
    type: schema_validation
    on_fail: block
"""
        result = self._run_yaml(yaml_text, mock_fail=True)
        self.assertEqual(result.exit_code, 1)

    def test_exit_code_zero_warn_only(self):
        yaml_text = """
gates:
  - id: warn_gate
    name: "Warn Gate"
    type: schema_validation
    on_fail: warn
"""
        result = self._run_yaml(yaml_text, mock_fail=True)
        self.assertEqual(result.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
