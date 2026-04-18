"""Tests for spanforge._ansi — ANSI colour helpers."""
from __future__ import annotations

import io

from spanforge._ansi import (
    BOLD,
    CYAN,
    GREEN,
    RED,
    RESET,
    YELLOW,
    color,
    strip_ansi,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeTTY(io.StringIO):
    """StringIO that pretends to be a TTY."""
    def isatty(self) -> bool:
        return True


class _FakeNonTTY(io.StringIO):
    """StringIO that is not a TTY."""
    def isatty(self) -> bool:
        return False


# ---------------------------------------------------------------------------
# color()
# ---------------------------------------------------------------------------

class TestColor:
    def test_returns_plain_text_to_non_tty(self):
        out = _FakeNonTTY()
        result = color("hello", GREEN, file=out)
        assert result == "hello"

    def test_wraps_with_codes_for_tty(self):
        out = _FakeTTY()
        result = color("hello", GREEN, file=out)
        assert GREEN in result
        assert RESET in result
        assert "hello" in result

    def test_no_color_env_suppresses_codes(self, monkeypatch):
        monkeypatch.setenv("NO_COLOR", "1")
        out = _FakeTTY()
        result = color("hello", RED, file=out)
        assert result == "hello"

    def test_strip_ansi_recovers_plain_text(self):
        out = _FakeTTY()
        coloured = color("world", CYAN, file=out)
        assert strip_ansi(coloured) == "world"

    def test_default_file_is_stdout(self, monkeypatch):
        # Should not raise; just check it returns a string
        result = color("test", BOLD)
        assert "test" in result

    def test_all_color_constants_are_strings(self):
        for const in (GREEN, RED, YELLOW, CYAN, BOLD, RESET):
            assert isinstance(const, str)


# ---------------------------------------------------------------------------
# strip_ansi()
# ---------------------------------------------------------------------------

class TestStripAnsi:
    def test_plain_text_unchanged(self):
        assert strip_ansi("hello world") == "hello world"

    def test_removes_escape_sequences(self):
        raw = "\033[32mGreen text\033[0m"
        assert strip_ansi(raw) == "Green text"

    def test_removes_bold(self):
        raw = "\033[1mBold\033[0m"
        assert strip_ansi(raw) == "Bold"

    def test_handles_multiple_codes(self):
        raw = "\033[1m\033[32mBold green\033[0m"
        assert strip_ansi(raw) == "Bold green"

    def test_empty_string(self):
        assert strip_ansi("") == ""

    def test_no_partial_removal(self):
        # A bracket without escape should be left intact
        result = strip_ansi("[not an escape]")
        assert result == "[not an escape]"
