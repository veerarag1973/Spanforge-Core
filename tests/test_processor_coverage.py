"""Tests for spanforge.processor — coverage for SpanProcessor, ProcessorChain, module-level helpers."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from spanforge.processor import (
    NoopSpanProcessor,
    ProcessorChain,
    SpanProcessor,
    _run_on_end,
    _run_on_start,
    add_processor,
    clear_processors,
)

if TYPE_CHECKING:
    import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _RecordingProcessor:
    """Processor that records calls for test assertions."""

    def __init__(self) -> None:
        self.starts: list[object] = []
        self.ends: list[object] = []

    def on_start(self, span: object) -> None:
        self.starts.append(span)

    def on_end(self, span: object) -> None:
        self.ends.append(span)


class _ErrorProcessor:
    """Processor that raises on every call."""

    def on_start(self, span: object) -> None:
        raise RuntimeError("start boom")

    def on_end(self, span: object) -> None:
        raise RuntimeError("end boom")


class _AttributeEnricher:
    """Processor that sets an attribute on the span."""

    def on_start(self, span: object) -> None:
        span.region = "us-east-1"  # type: ignore[attr-defined]

    def on_end(self, span: object) -> None:
        span.enriched = True  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Protocol conformance
# ---------------------------------------------------------------------------


class TestSpanProcessorProtocol:
    def test_recording_processor_is_a_span_processor(self) -> None:
        assert isinstance(_RecordingProcessor(), SpanProcessor)

    def test_noop_is_a_span_processor(self) -> None:
        assert isinstance(NoopSpanProcessor(), SpanProcessor)


# ---------------------------------------------------------------------------
# NoopSpanProcessor
# ---------------------------------------------------------------------------


class TestNoopSpanProcessor:
    def test_on_start_does_nothing(self) -> None:
        p = NoopSpanProcessor()
        p.on_start(MagicMock())  # should not raise

    def test_on_end_does_nothing(self) -> None:
        p = NoopSpanProcessor()
        p.on_end(MagicMock())  # should not raise


# ---------------------------------------------------------------------------
# ProcessorChain
# ---------------------------------------------------------------------------


class TestProcessorChain:
    def test_on_start_calls_all(self) -> None:
        p1, p2 = _RecordingProcessor(), _RecordingProcessor()
        chain = ProcessorChain([p1, p2])
        span = MagicMock()
        chain.on_start(span)
        assert p1.starts == [span]
        assert p2.starts == [span]

    def test_on_end_calls_all(self) -> None:
        p1, p2 = _RecordingProcessor(), _RecordingProcessor()
        chain = ProcessorChain([p1, p2])
        span = MagicMock()
        chain.on_end(span)
        assert p1.ends == [span]
        assert p2.ends == [span]

    def test_add_processor(self) -> None:
        chain = ProcessorChain()
        assert len(chain) == 0
        p = _RecordingProcessor()
        chain.add(p)
        assert len(chain) == 1

    def test_remove_processor(self) -> None:
        p = _RecordingProcessor()
        chain = ProcessorChain([p])
        chain.remove(p)
        assert len(chain) == 0

    def test_remove_missing_is_noop(self) -> None:
        chain = ProcessorChain()
        chain.remove(_RecordingProcessor())  # should not raise

    def test_clear(self) -> None:
        chain = ProcessorChain([_RecordingProcessor(), _RecordingProcessor()])
        assert len(chain) == 2
        chain.clear()
        assert len(chain) == 0

    def test_error_in_on_start_does_not_abort_chain(self, caplog: pytest.LogCaptureFixture) -> None:
        err = _ErrorProcessor()
        good = _RecordingProcessor()
        chain = ProcessorChain([err, good])
        span = MagicMock()
        with caplog.at_level(logging.WARNING, logger="spanforge.processor"):
            chain.on_start(span)
        assert good.starts == [span]
        assert "on_start error" in caplog.text

    def test_error_in_on_end_does_not_abort_chain(self, caplog: pytest.LogCaptureFixture) -> None:
        err = _ErrorProcessor()
        good = _RecordingProcessor()
        chain = ProcessorChain([err, good])
        span = MagicMock()
        with caplog.at_level(logging.WARNING, logger="spanforge.processor"):
            chain.on_end(span)
        assert good.ends == [span]
        assert "on_end error" in caplog.text

    def test_repr(self) -> None:
        chain = ProcessorChain([NoopSpanProcessor()])
        r = repr(chain)
        assert "ProcessorChain" in r
        assert "NoopSpanProcessor" in r

    def test_len(self) -> None:
        chain = ProcessorChain([_RecordingProcessor()])
        assert len(chain) == 1


# ---------------------------------------------------------------------------
# Module-level _run_on_start / _run_on_end
# ---------------------------------------------------------------------------


class TestModuleLevelHelpers:
    def test_run_on_start_calls_processors(self) -> None:
        p = _RecordingProcessor()
        mock_cfg = MagicMock()
        mock_cfg.span_processors = [p]
        span = MagicMock()
        with patch("spanforge.config.get_config", return_value=mock_cfg):
            _run_on_start(span)
        assert p.starts == [span]

    def test_run_on_end_calls_processors(self) -> None:
        p = _RecordingProcessor()
        mock_cfg = MagicMock()
        mock_cfg.span_processors = [p]
        span = MagicMock()
        with patch("spanforge.config.get_config", return_value=mock_cfg):
            _run_on_end(span)
        assert p.ends == [span]

    def test_run_on_start_handles_config_error(self) -> None:
        span = MagicMock()
        with patch("spanforge.config.get_config", side_effect=RuntimeError("no config")):
            _run_on_start(span)  # should not raise

    def test_run_on_end_handles_config_error(self) -> None:
        span = MagicMock()
        with patch("spanforge.config.get_config", side_effect=RuntimeError("no config")):
            _run_on_end(span)  # should not raise

    def test_run_on_start_error_in_processor(self, caplog: pytest.LogCaptureFixture) -> None:
        err = _ErrorProcessor()
        mock_cfg = MagicMock()
        mock_cfg.span_processors = [err]
        span = MagicMock()
        with (
            patch("spanforge.config.get_config", return_value=mock_cfg),
            caplog.at_level(logging.WARNING, logger="spanforge.processor"),
        ):
            _run_on_start(span)
        assert "on_start error" in caplog.text

    def test_run_on_end_error_in_processor(self, caplog: pytest.LogCaptureFixture) -> None:
        err = _ErrorProcessor()
        mock_cfg = MagicMock()
        mock_cfg.span_processors = [err]
        span = MagicMock()
        with (
            patch("spanforge.config.get_config", return_value=mock_cfg),
            caplog.at_level(logging.WARNING, logger="spanforge.processor"),
        ):
            _run_on_end(span)
        assert "on_end error" in caplog.text


# ---------------------------------------------------------------------------
# add_processor / clear_processors
# ---------------------------------------------------------------------------


class TestAddClearProcessors:
    def test_add_and_clear(self) -> None:
        mock_cfg = MagicMock()
        mock_cfg.span_processors = []
        p = _RecordingProcessor()
        with patch("spanforge.config.get_config", return_value=mock_cfg):
            add_processor(p)
            assert p in mock_cfg.span_processors
            clear_processors()
            assert len(mock_cfg.span_processors) == 0
