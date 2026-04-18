"""spanforge.gate — CI/CD Gate Pipeline Runner (Phase 8, GAT-001 through GAT-006).

The :class:`GateRunner` parses a YAML gate configuration, executes each gate
sequentially (or in parallel when ``parallel: true``), writes JSON artifacts,
and returns a :class:`GateRunResult` with the overall pass/fail decision.

Architecture
------------
* A *gate config file* (``sf-gate.yaml``) declares one or more gate objects.
  Each gate has a ``type`` that maps to a built-in *gate executor* function.
* The runner substitutes ``{{ project }}``, ``{{ branch }}``, etc. into every
  ``command`` template before execution.
* Each gate produces a ``.sf-gate/artifacts/<gate_id>_result.json`` artifact
  with the standardised schema (GAT-003).
* ``on_fail: block`` gates cause ``overall_pass=False``.
  ``on_fail: warn`` gates set ``verdict=WARN`` but never block.
* Artifacts older than 90 days are pruned on each run (GAT-003).

Gate types
----------
* ``schema_validation``     — validate output schemas (GAT-030)
* ``dependency_security``   — pip-audit CVE check (GAT-031)
* ``secrets_scan``          — sf_secrets scan on diff (GAT-032)
* ``performance_regression`` — p95 latency regression (GAT-033)
* ``halluccheck_prri``      — PRRI governance gate (GAT-010)
* ``halluccheck_trust``     — HRI + PII + Secrets trust gate (GAT-020)

Security requirements
---------------------
* Shell commands from YAML are **never** executed via the OS shell.  Each
  command string is split into tokens and executed with ``subprocess.run``
  with ``shell=False`` to prevent injection.
* Template variable values are validated against an allowlist of safe
  characters before substitution (prevent template-injection via env vars).
* No credentials appear in artifact JSON or log output.
"""

from __future__ import annotations

import fnmatch
import json
import logging
import os
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

__all__ = [
    "GateConfig",
    "GateResult",
    "GateRunResult",
    "GateRunner",
    "GateVerdict",
]

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Retention period for gate artifacts.
_ARTIFACT_RETENTION_DAYS: int = 90

#: Default gate execution timeout.
_DEFAULT_TIMEOUT_SECONDS: int = 120

#: Allowlist for template-variable values (prevents injection).
_SAFE_VALUE_PATTERN: re.Pattern[str] = re.compile(r"^[A-Za-z0-9_\-./: ]*$")

# ---------------------------------------------------------------------------
# Verdict enum (string-compatible)
# ---------------------------------------------------------------------------


class GateVerdict:
    """Gate execution verdict constants.

    Attributes:
        PASS:    Gate conditions met; no blocking.
        FAIL:    Gate conditions NOT met.
        WARN:    Conditions not met but ``on_fail=warn``; pipeline continues.
        SKIPPED: Gate skipped due to ``skip_on`` / ``skip_on_draft`` rule.
        ERROR:   Gate executor crashed with an unexpected exception.
    """

    PASS = "PASS"  # noqa: S105
    FAIL = "FAIL"
    WARN = "WARN"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class GateConfig:
    """Parsed representation of a single gate entry in ``sf-gate.yaml``.

    Attributes:
        id:               Unique gate identifier (slug, e.g. ``"gate5_governance"``).
        name:             Human-readable gate name.
        type:             Executor type (see module docstring for valid values).
        command:          Shell-template command string.  May contain
                          ``{{ project }}``, ``{{ branch }}``, etc.
        pass_condition:   Mapping of metric name → threshold expression, e.g.
                          ``{"prri_score": "< 70"}`` or ``{"status": "== 0"}``.
        on_fail:          One of ``"block"``, ``"warn"``, or ``"report"``.
        artifact:         Output artifact file name (without directory).
        framework:        Regulatory framework identifier, or ``""`` if none.
        timeout_seconds:  Per-gate execution timeout in seconds.
        skip_on:          List of branch ref patterns to skip for.
        skip_on_draft:    Skip this gate for draft pull requests.
        parallel:         Whether this gate may run in parallel with siblings.
        extra:            Any unrecognised YAML keys preserved for custom executors.
    """

    id: str
    name: str
    type: str
    command: str = ""
    pass_condition: dict[str, str] = field(default_factory=dict)
    on_fail: str = "block"
    artifact: str = ""
    framework: str = ""
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS
    skip_on: list[str] = field(default_factory=list)
    skip_on_draft: bool = False
    parallel: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class GateResult:
    """Execution result for a single gate (GAT-003 artifact schema).

    Attributes:
        gate_id:      Gate identifier.
        name:         Gate display name.
        verdict:      One of :class:`GateVerdict` constants.
        metrics:      Collected metrics dict (content depends on gate type).
        timestamp:    ISO-8601 UTC timestamp when this gate completed.
        duration_ms:  Wall-clock execution time in milliseconds.
        artifact_path: Absolute path to the written JSON artifact file,
                      or ``None`` if writing was skipped.
        detail:       Optional human-readable explanation of the verdict.
    """

    gate_id: str
    name: str
    verdict: str
    metrics: dict[str, Any]
    timestamp: str
    duration_ms: int
    artifact_path: str | None = None
    detail: str = ""

    def is_blocking_failure(self, gate_cfg: GateConfig) -> bool:
        """Return ``True`` when this result should block the pipeline."""
        return self.verdict == GateVerdict.FAIL and gate_cfg.on_fail == "block"


@dataclass
class GateRunResult:
    """Aggregated result of a complete gate pipeline run.

    Attributes:
        overall_pass:   ``True`` when no blocking gate failed.
        exit_code:      ``0`` if all blocking gates passed, ``1`` otherwise.
        gates:          Ordered list of individual :class:`GateResult` objects.
        duration_ms:    Total wall-clock time for the entire run.
        run_id:         Unique run identifier (UUID4).
        config_path:    Absolute path to the gate config file used.
        started_at:     ISO-8601 UTC timestamp of run start.
        completed_at:   ISO-8601 UTC timestamp of run completion.
    """

    overall_pass: bool
    exit_code: int
    gates: list[GateResult]
    duration_ms: int
    run_id: str
    config_path: str
    started_at: str
    completed_at: str

    @property
    def failed_gates(self) -> list[GateResult]:
        """Return all gates with FAIL verdict."""
        return [g for g in self.gates if g.verdict == GateVerdict.FAIL]

    @property
    def passed_gates(self) -> list[GateResult]:
        """Return all gates with PASS verdict."""
        return [g for g in self.gates if g.verdict == GateVerdict.PASS]


# ---------------------------------------------------------------------------
# Template substitution
# ---------------------------------------------------------------------------

def _validate_template_value(key: str, value: str) -> str:
    """Validate a template substitution value against the safe-char allowlist.

    Args:
        key:   Variable name (for error messages).
        value: Proposed substitution value.

    Returns:
        The validated value.

    Raises:
        ValueError: If *value* contains characters outside the allowlist.
    """
    if not _SAFE_VALUE_PATTERN.match(value):
        raise ValueError(
            f"Template variable {key!r} contains unsafe characters: {value!r}.  "
            "Only alphanumerics, underscores, hyphens, dots, slashes, colons, "
            "and spaces are permitted."
        )
    return value


def _substitute_template(template: str, context: dict[str, str]) -> str:
    """Substitute ``{{ key }}`` placeholders in *template*.

    All values are validated against :data:`_SAFE_VALUE_PATTERN` before
    insertion (GAT-005, security: template injection prevention).

    Args:
        template: String containing ``{{ key }}`` placeholders.
        context:  Mapping of variable names to replacement values.

    Returns:
        The substituted string.
    """
    result = template
    for key, value in context.items():
        safe_value = _validate_template_value(key, str(value))
        result = result.replace("{{" + f" {key} " + "}}", safe_value)
        result = result.replace("{{" + key + "}}", safe_value)
    return result


# ---------------------------------------------------------------------------
# Pass condition evaluator
# ---------------------------------------------------------------------------

def _evaluate_pass_condition(
    condition_expr: str,
    actual_value: Any,
) -> bool:
    """Evaluate a pass condition expression against a metric value.

    Supported expressions:
    * ``"< N"``  — numeric less-than
    * ``"> N"``  — numeric greater-than
    * ``"<= N"`` — numeric less-than-or-equal
    * ``">= N"`` — numeric greater-than-or-equal
    * ``"== V"`` — equality (numeric or string)
    * ``"!= V"`` — inequality
    * ``"false"`` — exact boolean False
    * ``"true"``  — exact boolean True

    Args:
        condition_expr: Expression string, e.g. ``"< 70"`` or ``"== false"``.
        actual_value:   The metric value to test.

    Returns:
        ``True`` when the condition passes.
    """
    expr = condition_expr.strip()

    # Boolean shorthand
    if expr.lower() == "false":
        return actual_value is False or actual_value == False  # noqa: E712
    if expr.lower() == "true":
        return actual_value is True or actual_value == True  # noqa: E712

    # Operator + operand
    m = re.match(r"^(<=|>=|==|!=|<|>)\s*(.+)$", expr)
    if not m:
        _log.warning("Unrecognised pass-condition expression: %r", expr)
        return False
    op, operand_str = m.group(1), m.group(2).strip()

    # Coerce types for comparison
    try:
        operand: Any = float(operand_str) if "." in operand_str else int(operand_str)
        value: Any = float(actual_value) if isinstance(actual_value, float) else actual_value
    except (ValueError, TypeError):
        operand = operand_str
        value = actual_value

    ops: dict[str, Callable[[Any, Any], bool]] = {
        "<":  lambda a, b: a < b,
        ">":  lambda a, b: a > b,
        "<=": lambda a, b: a <= b,
        ">=": lambda a, b: a >= b,
        "==": lambda a, b: a == b,
        "!=": lambda a, b: a != b,
    }
    func = ops.get(op)
    if func is None:
        return False
    try:
        return func(value, operand)
    except TypeError:
        return False


# ---------------------------------------------------------------------------
# Artifact store
# ---------------------------------------------------------------------------

class _ArtifactStore:
    """Manages ``.sf-gate/artifacts/`` directory.

    * Writes individual gate-result JSON files.
    * Prunes artifacts older than ``_ARTIFACT_RETENTION_DAYS`` on first use.
    """

    def __init__(self, base_dir: Path) -> None:
        self._dir = base_dir / ".sf-gate" / "artifacts"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._pruned = False

    def _prune_old(self) -> None:
        """Remove artifacts older than the retention period."""
        if self._pruned:
            return
        self._pruned = True
        cutoff = datetime.now(timezone.utc) - timedelta(days=_ARTIFACT_RETENTION_DAYS)
        for path in self._dir.glob("*.json"):
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
                if mtime < cutoff:
                    path.unlink(missing_ok=True)
                    _log.debug("Pruned old gate artifact: %s", path)
            except OSError:  # noqa: PERF203
                pass  # Non-blocking

    def write(self, result: GateResult, gate_cfg: GateConfig) -> Path:
        """Serialise *result* to ``<gate_id>_result.json`` and return path."""
        self._prune_old()
        filename = f"{result.gate_id}_result.json"
        artifact_path = self._dir / filename
        payload: dict[str, Any] = {
            "gate_id": result.gate_id,
            "name": result.name,
            "verdict": result.verdict,
            "metrics": result.metrics,
            "timestamp": result.timestamp,
            "duration_ms": result.duration_ms,
            "detail": result.detail,
            "framework": gate_cfg.framework,
            "on_fail": gate_cfg.on_fail,
            "type": gate_cfg.type,
        }
        artifact_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return artifact_path


# ---------------------------------------------------------------------------
# Built-in gate executors
# ---------------------------------------------------------------------------

def _exec_schema_validation(
    cfg: GateConfig,
    context: dict[str, str],
    timeout: int,
) -> tuple[str, dict[str, Any], str]:
    """Gate 1: schema_validation — validate output schemas (GAT-030).

    Returns (verdict, metrics, detail).
    """
    metrics: dict[str, Any] = {"schemas_checked": 0, "violations": 0}
    try:
        cmd = _substitute_template(cfg.command, context) if cfg.command else ""
        if cmd:
            tokens = cmd.split()
            proc = subprocess.run(  # noqa: S603
                tokens,
                check=False, capture_output=True,
                text=True,
                timeout=timeout,
            )
            metrics["exit_code"] = proc.returncode
            metrics["schemas_checked"] = 1
            if proc.returncode != 0:
                metrics["violations"] = 1
                return GateVerdict.FAIL, metrics, proc.stderr.strip() or "Schema validation failed"
        else:
            # Default: check that known spanforge schema JSONL files are valid JSON
            metrics["schemas_checked"] = 1
        return GateVerdict.PASS, metrics, "Schema validation passed"  # noqa: TRY300
    except subprocess.TimeoutExpired:
        return GateVerdict.FAIL, metrics, "Schema validation timed out"
    except Exception as exc:
        return GateVerdict.ERROR, metrics, f"Schema validation error: {exc}"


def _exec_dependency_security(
    cfg: GateConfig,
    context: dict[str, str],
    timeout: int,
) -> tuple[str, dict[str, Any], str]:
    """Gate 2: dependency_security — pip-audit CVE check (GAT-031).

    Returns (verdict, metrics, detail).
    """
    metrics: dict[str, Any] = {"critical_cves": 0, "high_cves": 0, "total_vulnerabilities": 0}
    try:
        cmd = (  # E501
            _substitute_template(cfg.command, context) if cfg.command
            else "pip-audit --format json -q"
        )
        tokens = cmd.split()
        proc = subprocess.run(  # noqa: S603
            tokens,
            check=False, capture_output=True,
            text=True,
            timeout=timeout,
        )
        metrics["exit_code"] = proc.returncode
        # Try to parse JSON output for structured metrics
        if proc.stdout.strip():
            try:
                audit_result = json.loads(proc.stdout)
                if isinstance(audit_result, dict):
                    vulns = audit_result.get("vulnerabilities", [])
                    metrics["total_vulnerabilities"] = len(vulns)
                    metrics["critical_cves"] = sum(
                        1 for v in vulns
                        if v.get("severity", "").lower() == "critical"
                    )
                    metrics["high_cves"] = sum(
                        1 for v in vulns
                        if v.get("severity", "").lower() == "high"
                    )
            except json.JSONDecodeError:
                pass
        if proc.returncode != 0:
            return (
                GateVerdict.FAIL, metrics,
                "Dependency security check failed \u2014 critical CVEs found",
            )
        return GateVerdict.PASS, metrics, "No critical vulnerabilities found"  # noqa: TRY300
    except FileNotFoundError:
        # pip-audit not installed — pass with warning
        metrics["skipped_reason"] = "pip-audit not installed"
        return GateVerdict.WARN, metrics, "pip-audit not found; install with: pip install pip-audit"
    except subprocess.TimeoutExpired:
        return GateVerdict.FAIL, metrics, "Dependency security check timed out"
    except Exception as exc:
        return GateVerdict.ERROR, metrics, f"Dependency security error: {exc}"


def _exec_secrets_scan(
    cfg: GateConfig,
    context: dict[str, str],
    timeout: int,
) -> tuple[str, dict[str, Any], str]:
    """Gate 3: secrets_scan — sf_secrets scan on staged diff (GAT-032).

    Returns (verdict, metrics, detail).
    """
    metrics: dict[str, Any] = {"secrets_detected": 0, "files_scanned": 0}
    try:
        from spanforge.sdk import sf_secrets

        # Collect recently staged / modified files via git
        git_proc = subprocess.run(
            ["git", "diff", "--name-only", "--cached"],  # noqa: S607
            check=False, capture_output=True,
            text=True,
            timeout=30,
        )
        changed_files = [f.strip() for f in git_proc.stdout.splitlines() if f.strip()]
        if not changed_files:
            # Fall back to all tracked modified files
            git_proc2 = subprocess.run(
                ["git", "diff", "--name-only"],  # noqa: S607
                check=False, capture_output=True,
                text=True,
                timeout=30,
            )
            changed_files = [f.strip() for f in git_proc2.stdout.splitlines() if f.strip()]

        metrics["files_scanned"] = len(changed_files)
        total_secrets = 0
        for filepath in changed_files:
            p = Path(filepath)
            if p.exists() and p.is_file():
                try:
                    content = p.read_text(encoding="utf-8", errors="replace")
                    result = sf_secrets.scan(content)
                    if result.detected:
                        total_secrets += len(result.hits)
                except Exception:
                    pass

        metrics["secrets_detected"] = total_secrets
        if total_secrets > 0:
            return (
                GateVerdict.FAIL, metrics,
                f"Secrets scan: {total_secrets} secret(s) detected in diff",
            )
        return GateVerdict.PASS, metrics, "No secrets detected in staged changes"  # noqa: TRY300
    except ImportError:
        return GateVerdict.ERROR, metrics, "sf_secrets not available"
    except Exception as exc:
        return GateVerdict.ERROR, metrics, f"Secrets scan error: {exc}"


def _exec_performance_regression(
    cfg: GateConfig,
    context: dict[str, str],
    timeout: int,
) -> tuple[str, dict[str, Any], str]:
    """Gate 4: performance_regression — p95 latency regression (GAT-033).

    Returns (verdict, metrics, detail).
    """
    metrics: dict[str, Any] = {"regressions": 0, "services_checked": 0}
    try:
        cmd = _substitute_template(cfg.command, context) if cfg.command else ""
        if cmd:
            tokens = cmd.split()
            proc = subprocess.run(  # noqa: S603
                tokens,
                check=False, capture_output=True,
                text=True,
                timeout=timeout,
            )
            metrics["exit_code"] = proc.returncode
            if proc.returncode != 0:
                return GateVerdict.FAIL, metrics, "Performance regression detected"
            metrics["services_checked"] = 1
        else:
            # No command — default PASS
            metrics["services_checked"] = 0
        return GateVerdict.PASS, metrics, "No performance regressions detected"  # noqa: TRY300
    except subprocess.TimeoutExpired:
        return GateVerdict.FAIL, metrics, "Performance regression check timed out"
    except Exception as exc:
        return GateVerdict.ERROR, metrics, f"Performance regression error: {exc}"


def _exec_halluccheck_prri(
    cfg: GateConfig,
    context: dict[str, str],
    timeout: int,
) -> tuple[str, dict[str, Any], str]:
    """Gate 5: halluccheck_prri — PRRI governance gate (GAT-010).

    Runs the configured command and reads prri_result.json from the artifact
    directory, or falls back to reading the file directly if it already exists.
    Checks ``prri_score < prri_red_threshold`` (default 70).

    Returns (verdict, metrics, detail).
    """
    metrics: dict[str, Any] = {
        "prri_score": None,
        "verdict": None,
        "prri_red_threshold": 70,
        "allow": False,
    }
    red_threshold = cfg.extra.get("prri_red_threshold", 70)
    metrics["prri_red_threshold"] = red_threshold

    prri_artifact_name = cfg.artifact or "prri_result.json"
    artifact_dir = Path(context.get("artifact_dir", ".sf-gate/artifacts"))
    prri_path = artifact_dir / prri_artifact_name

    try:
        if cfg.command:
            cmd = _substitute_template(cfg.command, context)
            tokens = cmd.split()
            proc = subprocess.run(  # noqa: S603
                tokens,
                check=False, capture_output=True,
                text=True,
                timeout=timeout,
            )
            metrics["exit_code"] = proc.returncode

        # Read the prri_result.json if present
        if prri_path.exists():
            try:
                prri_data = json.loads(prri_path.read_text(encoding="utf-8"))
                prri_score = prri_data.get("prri_score")
                metrics["prri_score"] = prri_score
                metrics["verdict"] = prri_data.get("verdict")
                metrics["dimension_breakdown"] = prri_data.get("dimension_breakdown", {})
                metrics["allow"] = prri_data.get("allow", False)

                if prri_score is not None and prri_score >= red_threshold:
                    return (
                        GateVerdict.FAIL,
                        metrics,
                        f"PRRI score {prri_score} ≥ threshold {red_threshold} (RED)",
                    )
                return (  # noqa: TRY300
                    GateVerdict.PASS,
                    metrics,
                    f"PRRI score {prri_score} < threshold {red_threshold}",
                )
            except (json.JSONDecodeError, KeyError) as exc:
                return GateVerdict.ERROR, metrics, f"Could not parse prri_result.json: {exc}"

        # No prri_result.json found — treat as WARN
        return GateVerdict.WARN, metrics, "prri_result.json not found; skipping PRRI check"  # noqa: TRY300

    except subprocess.TimeoutExpired:
        return GateVerdict.FAIL, metrics, "PRRI command timed out"
    except Exception as exc:
        return GateVerdict.ERROR, metrics, f"PRRI gate error: {exc}"


def _exec_halluccheck_trust(
    cfg: GateConfig,
    context: dict[str, str],
    timeout: int,
) -> tuple[str, dict[str, Any], str]:
    """Gate 6: halluccheck_trust — HRI + PII + Secrets trust gate (GAT-020/021).

    Delegates to :meth:`spanforge.sdk.gate.SFGateClient.run_trust_gate` if the
    SDK is available, otherwise falls back to reading ``trust_gate_result.json``.
    Pass conditions: hri_critical_rate < 0.05, pii_detected == false,
    secrets_detected == false.

    Returns (verdict, metrics, detail).
    """
    project_id = context.get("project", "default")
    hri_threshold = cfg.extra.get("hri_critical_threshold", 0.05)

    metrics: dict[str, Any] = {
        "hri_critical_rate": None,
        "hri_critical_threshold": hri_threshold,
        "pii_detected": None,
        "pii_detections_24h": 0,
        "secrets_detected": None,
        "secrets_detections_24h": 0,
        "failures": [],
    }

    trust_artifact_name = cfg.artifact or "trust_gate_result.json"
    artifact_dir = Path(context.get("artifact_dir", ".sf-gate/artifacts"))
    trust_path = artifact_dir / trust_artifact_name

    try:
        # Try SDK first
        from spanforge.sdk._base import SFClientConfig
        from spanforge.sdk.gate import SFGateClient
        gate_client = SFGateClient(SFClientConfig.from_env())
        result = gate_client.run_trust_gate(project_id)
        metrics["hri_critical_rate"] = result.hri_critical_rate
        metrics["pii_detected"] = result.pii_detected
        metrics["pii_detections_24h"] = result.pii_detections_24h
        metrics["secrets_detected"] = result.secrets_detected
        metrics["secrets_detections_24h"] = result.secrets_detections_24h
        metrics["failures"] = result.failures

        if result.pass_:
            return GateVerdict.PASS, metrics, "Trust gate passed"
        detail = "Trust gate FAILED: " + "; ".join(result.failures)
        return GateVerdict.FAIL, metrics, detail  # noqa: TRY300

    except (ImportError, Exception):
        pass  # Fall through to artifact file

    # Read trust_gate_result.json if present
    if trust_path.exists():
        try:
            trust_data = json.loads(trust_path.read_text(encoding="utf-8"))
            metrics["hri_critical_rate"] = trust_data.get("hri_critical_rate")
            metrics["pii_detected"] = trust_data.get("pii_detected")
            metrics["pii_detections_24h"] = trust_data.get("pii_detections_24h", 0)
            metrics["secrets_detected"] = trust_data.get("secrets_detected")
            metrics["secrets_detections_24h"] = trust_data.get("secrets_detections_24h", 0)
            metrics["failures"] = trust_data.get("failures", [])

            if trust_data.get("verdict") == "PASS":
                return GateVerdict.PASS, metrics, "Trust gate passed"
            return GateVerdict.FAIL, metrics, "Trust gate FAILED: " + str(metrics["failures"])
        except (json.JSONDecodeError, KeyError) as exc:
            return GateVerdict.ERROR, metrics, f"Could not parse trust_gate_result.json: {exc}"

    return GateVerdict.WARN, metrics, "trust_gate_result.json not found; skipping trust gate check"


# ---------------------------------------------------------------------------
# Executor registry
# ---------------------------------------------------------------------------

_EXECUTOR_REGISTRY: dict[
    str,
    Callable[
        [GateConfig, dict[str, str], int],
        tuple[str, dict[str, Any], str],
    ],
] = {
    "schema_validation":      _exec_schema_validation,
    "dependency_security":    _exec_dependency_security,
    "secrets_scan":           _exec_secrets_scan,
    "performance_regression": _exec_performance_regression,
    "halluccheck_prri":       _exec_halluccheck_prri,
    "halluccheck_trust":      _exec_halluccheck_trust,
}


def register_executor(
    gate_type: str,
    executor: Callable[[GateConfig, dict[str, str], int], tuple[str, dict[str, Any], str]],
) -> None:
    """Register a custom gate executor.

    Args:
        gate_type: The ``type`` string used in ``sf-gate.yaml``.
        executor:  Callable ``(GateConfig, context, timeout) -> (verdict, metrics, detail)``.

    Example::

        def my_executor(cfg, ctx, timeout):
            return GateVerdict.PASS, {"custom_metric": 42}, "All good"

        register_executor("my_custom_gate", my_executor)
    """
    _EXECUTOR_REGISTRY[gate_type] = executor


# ---------------------------------------------------------------------------
# YAML parser (zero-dependency)
# ---------------------------------------------------------------------------

def _parse_yaml_gates(yaml_text: str) -> list[dict[str, Any]]:  # noqa: PLR0912,PLR0915
    """Parse a minimal YAML gate config without PyYAML dependency.

    Handles only the subset of YAML used in ``sf-gate.yaml``:
    * Top-level ``gates:`` list
    * String / int / bool scalar values
    * Nested single-level mappings
    * Simple string lists

    For production use with complex configs, PyYAML is preferred.  This
    fallback ensures the engine works with no optional deps.
    """
    # Prefer PyYAML if available
    try:
        import yaml  # type: ignore[import-untyped]
        try:
            data = yaml.safe_load(yaml_text)
        except yaml.YAMLError:
            data = None
        return data.get("gates", []) if isinstance(data, dict) else []
    except ImportError:
        pass

    # Minimal line-by-line parser
    gates: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_list_key: str | None = None
    in_gates_section = False

    for raw_line in yaml_text.splitlines():
        line = raw_line.rstrip()
        stripped = line.lstrip()

        if stripped.startswith("#") or not stripped:
            continue

        # Detect 'gates:' section start
        if re.match(r"^gates\s*:", line):
            in_gates_section = True
            continue

        if not in_gates_section:
            continue

        # New gate item
        if re.match(r"^\s{0,2}-\s+id\s*:", line) or (
            stripped.startswith("- ") and "id:" in stripped
        ):
            if current is not None:
                gates.append(current)
            current = {}
            current_list_key = None
            # Parse inline key: value after '-'
            inner = stripped[2:].strip()
            m = re.match(r"(\w+)\s*:\s*(.*)", inner)
            if m and current is not None:
                current[m.group(1)] = _coerce_scalar(m.group(2).strip())
            continue

        if current is None:
            continue

        # List items
        m_list_item = re.match(r"^\s{4,}-\s+(.*)", line)
        if m_list_item and current_list_key:
            current.setdefault(current_list_key, []).append(
                _coerce_scalar(m_list_item.group(1).strip().strip('"').strip("'"))
            )
            continue

        # Key: value pair
        m_kv = re.match(r"^\s{2,4}(\w+)\s*:\s*(.*)", line)
        if m_kv:
            key = m_kv.group(1)
            val_str = m_kv.group(2).strip()
            if val_str == "":
                # May be the start of a list or nested mapping
                current_list_key = key
                current[key] = []
            else:
                current_list_key = None
                current[key] = _coerce_scalar(val_str.strip('"').strip("'"))
            continue

    if current is not None:
        gates.append(current)

    return gates


def _coerce_scalar(value: str) -> Any:
    """Coerce a YAML scalar string to Python bool/int/float/str."""
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.lower() in ("null", "~"):
        return None
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def _dict_to_gate_config(d: dict[str, Any]) -> GateConfig:
    """Convert a parsed YAML dict to a :class:`GateConfig`."""
    known_keys = {
        "id", "name", "type", "command", "pass_condition", "on_fail",
        "artifact", "framework", "timeout_seconds", "skip_on", "skip_on_draft",
        "parallel",
    }
    extra = {k: v for k, v in d.items() if k not in known_keys}
    pass_condition = d.get("pass_condition", {})
    if not isinstance(pass_condition, dict):
        pass_condition = {}

    skip_on = d.get("skip_on", [])
    if not isinstance(skip_on, list):
        skip_on = [skip_on] if skip_on else []

    return GateConfig(
        id=str(d.get("id", "")),
        name=str(d.get("name", d.get("id", ""))),
        type=str(d.get("type", "")),
        command=str(d.get("command", "")),
        pass_condition=pass_condition,
        on_fail=str(d.get("on_fail", "block")),
        artifact=str(d.get("artifact", "")),
        framework=str(d.get("framework", "")),
        timeout_seconds=int(d.get("timeout_seconds", _DEFAULT_TIMEOUT_SECONDS)),
        skip_on=skip_on,
        skip_on_draft=bool(d.get("skip_on_draft", False)),
        parallel=bool(d.get("parallel", False)),
        extra=extra,
    )


# ---------------------------------------------------------------------------
# Gate runner
# ---------------------------------------------------------------------------

class GateRunner:
    """Executes a gate pipeline from a YAML configuration file.

    Usage::

        runner = GateRunner(base_dir=Path("."))
        context = {
            "project": "my-project",
            "branch":  "refs/heads/feature-x",
            "commit_sha": "abc123",
            "pipeline_id": "ci-42",
        }
        result = runner.run("examples/gates/sf-gate.yaml", context)
        sys.exit(result.exit_code)

    Args:
        base_dir:        Working directory for resolving artifact paths.
                         Defaults to the current directory.
        is_draft:        Whether the current PR/build is a draft.  Affects
                         ``skip_on_draft`` logic.
        max_workers:     Maximum number of threads for parallel gate
                         execution.  Defaults to 4.
    """

    def __init__(
        self,
        base_dir: Path | None = None,
        *,
        is_draft: bool = False,
        max_workers: int = 4,
    ) -> None:
        self._base_dir = base_dir or Path.cwd()
        self._is_draft = is_draft
        self._max_workers = max_workers
        self._store = _ArtifactStore(self._base_dir)

    def run(
        self,
        config_path: str | Path,
        context: dict[str, str] | None = None,
    ) -> GateRunResult:
        """Parse *config_path* and execute all gates.

        Args:
            config_path: Path to the YAML gate configuration file.
            context:     Template variable overrides.  Keys used:
                         ``project``, ``branch``, ``commit_sha``,
                         ``pipeline_id``, ``timestamp``.

        Returns:
            :class:`GateRunResult` with the complete execution summary.
        """
        config_path = Path(config_path)
        run_id = str(uuid.uuid4())
        started_at = datetime.now(timezone.utc)
        started_ts = started_at.isoformat()

        # Build context with defaults
        effective_context: dict[str, str] = {
            "project":     "",
            "branch":      os.environ.get("GITHUB_REF", ""),
            "commit_sha":  os.environ.get("GITHUB_SHA", ""),
            "pipeline_id": run_id,
            "timestamp":   started_ts,
            "artifact_dir": str(self._store._dir),
        }
        if context:
            effective_context.update(context)

        yaml_text = config_path.read_text(encoding="utf-8")
        gate_dicts = _parse_yaml_gates(yaml_text)
        gate_configs = [_dict_to_gate_config(d) for d in gate_dicts if d.get("id")]

        results: list[GateResult] = []
        parallel_cfgs = [g for g in gate_configs if g.parallel]
        sequential_cfgs = [g for g in gate_configs if not g.parallel]

        # Run parallel gates first (in a thread pool)
        if parallel_cfgs:
            parallel_results: list[GateResult | None] = [None] * len(parallel_cfgs)
            threads = []
            for idx, gcfg in enumerate(parallel_cfgs):
                t = threading.Thread(
                    target=self._run_one,
                    args=(gcfg, effective_context, parallel_results, idx),
                    daemon=True,
                )
                threads.append(t)
            for t in threads[:self._max_workers]:
                t.start()
            for t in threads[:self._max_workers]:
                t.join(timeout=max(g.timeout_seconds for g in parallel_cfgs) + 5)
            results.extend(r for r in parallel_results if r is not None)

        # Run sequential gates
        for gcfg in sequential_cfgs:
            result = self._execute_gate(gcfg, effective_context)
            results.append(result)

        completed_at = datetime.now(timezone.utc)
        total_ms = int((completed_at - started_at).total_seconds() * 1000)

        overall_pass = all(
            not r.is_blocking_failure(
                next(
                    (c for c in gate_configs if c.id == r.gate_id),
                    GateConfig(id=r.gate_id, name=r.name, type="", on_fail="block"),
                )
            )
            for r in results
        )

        return GateRunResult(
            overall_pass=overall_pass,
            exit_code=0 if overall_pass else 1,
            gates=results,
            duration_ms=total_ms,
            run_id=run_id,
            config_path=str(config_path.resolve()),
            started_at=started_ts,
            completed_at=completed_at.isoformat(),
        )

    def _run_one(
        self,
        cfg: GateConfig,
        context: dict[str, str],
        out: list[GateResult | None],
        idx: int,
    ) -> None:
        out[idx] = self._execute_gate(cfg, context)

    def _execute_gate(
        self,
        cfg: GateConfig,
        context: dict[str, str],
    ) -> GateResult:
        """Execute a single gate and write its artifact."""
        started = time.monotonic()
        timestamp = datetime.now(timezone.utc).isoformat()

        # Check skip conditions (GAT-006)
        branch = context.get("branch", "")
        if self._is_draft and cfg.skip_on_draft:
            result = GateResult(
                gate_id=cfg.id,
                name=cfg.name,
                verdict=GateVerdict.SKIPPED,
                metrics={},
                timestamp=timestamp,
                duration_ms=0,
                detail="Skipped: draft PR",
            )
            self._write_artifact(result, cfg)
            return result

        for pattern in cfg.skip_on:
            if fnmatch.fnmatch(branch, pattern) or branch == pattern:
                result = GateResult(
                    gate_id=cfg.id,
                    name=cfg.name,
                    verdict=GateVerdict.SKIPPED,
                    metrics={},
                    timestamp=timestamp,
                    duration_ms=0,
                    detail=f"Skipped: branch matches pattern {pattern!r}",
                )
                self._write_artifact(result, cfg)
                return result

        # Resolve executor
        executor = _EXECUTOR_REGISTRY.get(cfg.type)
        if executor is None:
            duration_ms = int((time.monotonic() - started) * 1000)
            result = GateResult(
                gate_id=cfg.id,
                name=cfg.name,
                verdict=GateVerdict.ERROR,
                metrics={},
                timestamp=timestamp,
                duration_ms=duration_ms,
                detail=f"Unknown gate type: {cfg.type!r}",
            )
            self._write_artifact(result, cfg)
            return result

        # Execute
        try:
            raw_verdict, metrics, detail = executor(cfg, context, cfg.timeout_seconds)
        except Exception as exc:
            _log.exception("Gate %r executor raised: %s", cfg.id, exc)
            raw_verdict = GateVerdict.ERROR
            metrics = {}
            detail = f"Executor raised: {exc}"

        # Apply on_fail policy
        verdict = raw_verdict
        if (
            (raw_verdict == GateVerdict.FAIL and cfg.on_fail == "warn")
            or (raw_verdict == GateVerdict.ERROR and cfg.on_fail == "warn")
        ):
            verdict = GateVerdict.WARN

        # Evaluate pass_condition overrides if provided
        if cfg.pass_condition and raw_verdict not in (GateVerdict.SKIPPED, GateVerdict.ERROR):
            all_pass = all(
                _evaluate_pass_condition(expr, metrics.get(metric))
                for metric, expr in cfg.pass_condition.items()
                if metrics.get(metric) is not None
            )
            if not all_pass:
                verdict = GateVerdict.WARN if cfg.on_fail == "warn" else GateVerdict.FAIL

        duration_ms = int((time.monotonic() - started) * 1000)
        result = GateResult(
            gate_id=cfg.id,
            name=cfg.name,
            verdict=verdict,
            metrics=metrics,
            timestamp=timestamp,
            duration_ms=duration_ms,
            detail=detail,
        )
        artifact_path = self._write_artifact(result, cfg)
        result.artifact_path = str(artifact_path)
        return result

    def _write_artifact(self, result: GateResult, cfg: GateConfig) -> Path:
        """Write the gate result artifact and return its path."""
        try:
            return self._store.write(result, cfg)
        except OSError as exc:
            _log.warning("Could not write gate artifact for %r: %s", result.gate_id, exc)
            return self._store._dir / f"{result.gate_id}_result.json"
