"""Repository guardrails against public-surface drift."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from spanforge._cli import main


REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_FILES = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "cli.md",
    REPO_ROOT / "docs" / "runbook.md",
    REPO_ROOT / "docs" / "user_guide" / "compliance.md",
]


def _run(argv: list[str]) -> int:
    with pytest.raises(SystemExit) as exc_info:
        main(argv)
    return int(exc_info.value.code)


def test_repo_version_matches_pyproject() -> None:
    import spanforge

    pyproject = REPO_ROOT / "pyproject.toml"
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"\s*$', pyproject.read_text(encoding="utf-8"))

    assert match is not None
    assert spanforge.__version__ == match.group(1)


def test_docs_do_not_use_known_stale_compliance_cli_patterns() -> None:
    stale_patterns = [
        "--model ",
        "spanforge compliance check evidence.json",
    ]
    docs_text = "\n".join(path.read_text(encoding="utf-8") for path in DOC_FILES)

    for pattern in stale_patterns:
        assert pattern not in docs_text

    assert "--model-id" in docs_text
    assert "--events-file" in docs_text


@pytest.mark.parametrize(
    ("argv", "expected_exit"),
    [
        (["compliance", "generate", "--help"], 0),
        (["compliance", "report", "--help"], 0),
        (["compliance", "check", "--help"], 0),
        (["compliance", "status", "--help"], 0),
        (["audit", "verify", "--help"], 0),
        (["cost", "brief", "submit", "--help"], 0),
        (["gate", "run", "--help"], 0),
        (["trust", "scorecard", "--help"], 0),
        (["enterprise", "status", "--help"], 0),
        (["security", "scan", "--help"], 0),
    ],
)
def test_documented_cli_entrypoints_still_parse(argv: list[str], expected_exit: int) -> None:
    assert _run(argv) == expected_exit
