"""spanforge._ansi — ANSI terminal colour helpers.

Provides a single :func:`color` function that wraps text in ANSI escape codes
while honouring the ``NO_COLOR`` environment variable
(https://no-color.org/) and falling back to plain text when stdout is not a
TTY (e.g. in CI pipelines or when output is piped to a file).

Pre-defined colour codes are exported for convenience.

Usage::

    from spanforge._ansi import color, GREEN, RED, BOLD

    print(color("PASS", GREEN))
    print(color("FAIL", RED + BOLD))
"""

from __future__ import annotations

import os
import sys
from typing import IO, TextIO

__all__ = [
    "BOLD",
    "CYAN",
    "GREEN",
    "RED",
    "RESET",
    "YELLOW",
    "color",
    "strip_ansi",
]

# ---------------------------------------------------------------------------
# ANSI escape sequences
# ---------------------------------------------------------------------------

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"
RESET = "\033[0m"


def color(text: str, code: str, *, file: TextIO | None = None) -> str:
    """Return *text* wrapped in ANSI *code*, or plain *text* when colours are disabled.

    Colours are suppressed when **any** of the following is true:

    * The ``NO_COLOR`` environment variable is set (any value).
    * *file* (default: ``sys.stdout``) is not a TTY.

    Args:
        text:  The string to colourise.
        code:  An ANSI escape sequence (e.g. :data:`GREEN`, ``RED + BOLD``).
        file:  The stream to check for TTY status.  Defaults to
               ``sys.stdout``.

    Returns:
        ``f"{code}{text}{RESET}"`` when colours are enabled, otherwise
        plain *text*.

    Example::

        print(color("PASS", GREEN))
        print(color("WARN", YELLOW + BOLD))
    """
    stream: IO[str] = file if file is not None else sys.stdout
    if os.environ.get("NO_COLOR") or not getattr(stream, "isatty", lambda: False)():
        return text
    return f"{code}{text}{RESET}"


def strip_ansi(text: str) -> str:
    """Remove all ANSI escape sequences from *text*.

    Useful for testing output that was produced with :func:`color`.

    Args:
        text:  String potentially containing ANSI codes.

    Returns:
        The string with all ``ESC[...m`` sequences removed.

    Example::

        assert strip_ansi(color("hello", GREEN)) == "hello"
    """
    import re

    return re.sub(r"\033\[[0-9;]*m", "", text)
