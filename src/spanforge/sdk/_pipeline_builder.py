"""spanforge.sdk._pipeline_builder — SFPipeline: composable middleware builder.

Usage::

    from spanforge.sdk import SFClientFactory, SFPipeline

    factory = SFClientFactory.from_env()

    result = (
        SFPipeline()
        .add_stage(factory.pii, name="pii-scan")
        .add_stage(factory.secrets, name="secrets-scan")
        .add_stage(factory.gate, name="gate-eval")
        .run({"text": "Hello, call me at 555-867-5309"})
    )
    print(result.success, result.details)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

__all__ = ["PipelineStageError", "SFPipeline"]

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PipelineStageError(Exception):
    """Raised when a pipeline stage fails and ``fail_fast=True``."""

    def __init__(self, stage: str, cause: Exception) -> None:
        super().__init__(f"Pipeline stage '{stage}' failed: {cause}")
        self.stage = stage
        self.cause = cause


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class SFPipelineResult:
    """Result of :meth:`SFPipeline.run`.

    Attributes:
        success:      ``True`` when every stage completed without error.
        stage_count:  Total number of stages executed.
        elapsed_ms:   Wall-clock duration in milliseconds.
        errors:       Mapping of ``stage_name → error_message`` for failures.
        outputs:      Ordered list of return values from each stage (or
                      ``None`` for stages that returned nothing).
        payload:      The final payload after all stages have processed it.
        details:      Arbitrary key/value metadata accumulated from stages.
    """

    success: bool
    stage_count: int
    elapsed_ms: float
    errors: dict[str, str] = field(default_factory=dict)
    outputs: list[Any] = field(default_factory=list)
    payload: Any = None
    details: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SFPipeline builder
# ---------------------------------------------------------------------------

# A stage callable receives the current payload and returns an updated payload.
# Returning None means "pass through unchanged".
_StageFn = Callable[[Any], Any]


class SFPipeline:
    """Composable middleware pipeline builder.

    Stages are added with :meth:`add_stage` and executed sequentially by
    :meth:`run`.  Each stage may be:

    * A plain **callable** ``(payload: Any) -> Any``.
    * A SpanForge **service client** with a ``__call__`` method, or with a
      conventional entry-point method (``scan``, ``check``, ``evaluate``,
      ``emit``, ``append``, ``publish``).

    The pipeline passes the *return value* of each stage as the input to the
    next stage.  If a stage returns ``None``, the original payload is forwarded
    unchanged.

    Args:
        fail_fast: When ``True`` (default ``False``), the first stage error
                   raises :class:`PipelineStageError` and execution stops.
                   When ``False``, errors are collected and execution continues
                   with the payload unchanged.

    Example::

        from spanforge.sdk import SFPipeline, SFClientFactory

        factory = SFClientFactory.from_env()

        def redact_pii(payload: dict) -> dict:
            result = factory.pii.scan(payload.get("text", ""))
            return {**payload, "has_pii": result.has_pii}

        result = SFPipeline(fail_fast=True).add_stage(redact_pii).run({"text": "Hi Alice"})
    """

    def __init__(self, *, fail_fast: bool = False) -> None:
        self._fail_fast = fail_fast
        self._stages: list[tuple[str, _StageFn]] = []  # (name, fn)

    # ------------------------------------------------------------------
    # Builder interface
    # ------------------------------------------------------------------

    def add_stage(
        self,
        fn_or_client: Any,
        *,
        name: str | None = None,
    ) -> SFPipeline:
        """Append a stage to the pipeline and return *self* for chaining.

        Args:
            fn_or_client: A callable or a SpanForge service client.  When a
                          client is supplied, the pipeline looks for a callable
                          entry point in this order: ``__call__``, ``scan``,
                          ``check``, ``evaluate``, ``emit``, ``append``,
                          ``publish``.
            name:         Optional human-readable stage name used in logs and
                          error reporting.  Defaults to the repr of the stage.

        Returns:
            *self* — allows method chaining.

        Raises:
            TypeError: If *fn_or_client* is not callable and has none of the
                       recognised entry-point methods.
        """
        fn = self._resolve_callable(fn_or_client)
        stage_name = name or getattr(fn_or_client, "__name__", None) or repr(fn_or_client)
        self._stages.append((stage_name, fn))
        return self

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def run(self, payload: Any) -> SFPipelineResult:
        """Execute all stages sequentially.

        Args:
            payload: Initial payload forwarded to the first stage.

        Returns:
            :class:`SFPipelineResult` summarising the run.

        Raises:
            PipelineStageError: If a stage fails and ``fail_fast=True``.
        """
        start = time.monotonic()
        errors: dict[str, str] = {}
        outputs: list[Any] = []
        details: dict[str, Any] = {}
        current_payload = payload

        for stage_name, fn in self._stages:
            try:
                result = fn(current_payload)
                if result is not None:
                    current_payload = result
                outputs.append(result)
                _log.debug("SFPipeline stage '%s' OK", stage_name)
            except Exception as exc:  # noqa: PERF203  # try-except in loop is intentional for pipeline fault isolation
                err_msg = str(exc)
                errors[stage_name] = err_msg
                outputs.append(None)
                _log.warning("SFPipeline stage '%s' failed: %s", stage_name, exc)
                if self._fail_fast:
                    raise PipelineStageError(stage_name, exc) from exc

        elapsed_ms = (time.monotonic() - start) * 1000

        return SFPipelineResult(
            success=not errors,
            stage_count=len(self._stages),
            elapsed_ms=elapsed_ms,
            errors=errors,
            outputs=outputs,
            payload=current_payload,
            details=details,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    _ENTRY_POINTS = ("scan", "check", "evaluate", "emit", "append", "publish")

    @classmethod
    def _resolve_callable(cls, obj: Any) -> _StageFn:
        """Return the best callable entry point for *obj*."""
        if callable(obj):
            return obj  # type: ignore[no-any-return]
        for attr in cls._ENTRY_POINTS:
            method = getattr(obj, attr, None)
            if callable(method):
                return method  # type: ignore[no-any-return]
        raise TypeError(
            f"Pipeline stage {obj!r} is not callable and has none of the "
            f"recognised entry-point methods: {cls._ENTRY_POINTS}"
        )
