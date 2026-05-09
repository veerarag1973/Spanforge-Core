"""spanforge.sdk.dataset_scanner — Training Data Compliance Scanner (CARD 1C-4).

Implements EU AI Act Article 10 compliance scanning for training datasets:

* **PII density score** — PII entities (email/phone/SSN) per 1 000 tokens.
* **Consent coverage** — fraction of rows containing a ``consent`` field.
* **Provenance coverage** — fraction of rows containing a ``source`` field.
* **Bias signal** — heuristic vocabulary-skew detection (``low``/``medium``/``high``).

The scanner is file-format agnostic: it reads ``.jsonl``, ``.json``, ``.csv``,
and ``.txt`` files.  ``.parquet`` files are supported when ``pyarrow`` or
``pandas`` is installed; otherwise they are skipped with a warning.

Usage::

    from spanforge.sdk.dataset_scanner import scan_dataset_compliance

    report = scan_dataset_compliance("./data/training/")
    print(report.to_markdown())          # readable markdown
    print(report.to_json())              # machine-readable JSON
    print(report.hmac_signature)         # HMAC-SHA256 of report body
"""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import logging
import os
import pathlib
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

__all__ = [
    "Article10Clause",
    "DatasetComplianceReport",
    "scan_dataset_compliance",
]

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex helpers (stdlib-only, same family as spanforge.validate)
# ---------------------------------------------------------------------------

_PII_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z]{2,}", re.ASCII)
_PII_PHONE_RE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b")
_PII_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")

#: Fields that indicate consent metadata.
_CONSENT_FIELDS: frozenset[str] = frozenset({"consent", "consented", "consent_given", "opt_in"})
#: Fields that indicate data provenance.
_PROVENANCE_FIELDS: frozenset[str] = frozenset({"source", "origin", "provenance", "data_source"})

#: Supported file extensions.
_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset(
    {".jsonl", ".json", ".csv", ".txt", ".parquet"}
)

# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class Article10Clause:
    """One EU AI Act Article 10 compliance clause result."""

    clause_id: str
    title: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "clause_id": self.clause_id,
            "title": self.title,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass
class DatasetComplianceReport:
    """Signed EU AI Act Article 10 compliance report for a training dataset.

    Fields mirror the CARD 1C-4 roadmap contract exactly.
    """

    scan_id: str
    scanned_at: str
    dataset_path: str
    file_count: int
    row_count: int
    token_estimate: int
    pii_density_score: float
    consent_coverage_pct: float
    provenance_coverage_pct: float
    bias_signal: str  # "low" | "medium" | "high"
    eu_ai_act_article_10_clauses: list[Article10Clause]
    hmac_signature: str = ""
    _report_body: str = field(default="", init=False, repr=False, compare=False)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def _body_dict(self) -> dict[str, Any]:
        return {
            "scan_id": self.scan_id,
            "scanned_at": self.scanned_at,
            "dataset_path": self.dataset_path,
            "file_count": self.file_count,
            "row_count": self.row_count,
            "token_estimate": self.token_estimate,
            "pii_density_score": round(self.pii_density_score, 4),
            "consent_coverage_pct": round(self.consent_coverage_pct, 2),
            "provenance_coverage_pct": round(self.provenance_coverage_pct, 2),
            "bias_signal": self.bias_signal,
            "eu_ai_act_article_10_clauses": [c.to_dict() for c in self.eu_ai_act_article_10_clauses],
        }

    def to_json(self, *, indent: int = 2) -> str:
        """Return the full report as a JSON string including the HMAC signature."""
        d = self._body_dict()
        d["hmac_signature"] = self.hmac_signature
        return json.dumps(d, indent=indent)

    def to_markdown(self) -> str:
        """Return the report as a human-readable Markdown string."""
        passed_clauses = [c for c in self.eu_ai_act_article_10_clauses if c.passed]
        failed_clauses = [c for c in self.eu_ai_act_article_10_clauses if not c.passed]
        overall = "PASS" if not failed_clauses else "FAIL"

        lines: list[str] = [
            "# SpanForge — EU AI Act Article 10 Training Data Compliance Report",
            "",
            f"**Scan ID**: `{self.scan_id}`  ",
            f"**Scanned at**: {self.scanned_at}  ",
            f"**Dataset path**: `{self.dataset_path}`  ",
            f"**Overall**: **{overall}**",
            "",
            "## Dataset Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Files scanned | {self.file_count} |",
            f"| Rows scanned | {self.row_count:,} |",
            f"| Token estimate | {self.token_estimate:,} |",
            f"| PII density score | {self.pii_density_score:.4f} per 1k tokens |",
            f"| Consent coverage | {self.consent_coverage_pct:.1f}% |",
            f"| Provenance coverage | {self.provenance_coverage_pct:.1f}% |",
            f"| Bias signal | {self.bias_signal.upper()} |",
            "",
            "## EU AI Act Article 10 Clause Results",
            "",
            "| Clause | Title | Status | Detail |",
            "|--------|-------|--------|--------|",
        ]
        for clause in self.eu_ai_act_article_10_clauses:
            status = "✓ PASS" if clause.passed else "✗ FAIL"
            lines.append(
                f"| `{clause.clause_id}` | {clause.title} | {status} | {clause.detail} |"
            )

        lines += [
            "",
            "## Signed Evidence",
            "",
            f"```",
            f"HMAC-SHA256: {self.hmac_signature}",
            f"```",
            "",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# File loaders
# ---------------------------------------------------------------------------


def _load_jsonl(path: pathlib.Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except json.JSONDecodeError:
            _log.warning("dataset_scanner: skipping invalid JSON at %s line %d", path.name, lineno)
    return rows


def _load_json(path: pathlib.Path) -> list[dict[str, Any]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return []
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _load_csv(path: pathlib.Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            rows.append(dict(row))
    except Exception:  # noqa: BLE001
        pass
    return rows


def _load_txt(path: pathlib.Path) -> list[dict[str, Any]]:
    """Load plain-text lines as single-field dicts: ``{"text": line}``."""
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if line:
            rows.append({"text": line})
    return rows


def _load_parquet(path: pathlib.Path) -> list[dict[str, Any]]:
    try:
        import pyarrow.parquet as pq  # type: ignore[import-untyped]
        table = pq.read_table(str(path))
        return table.to_pydict() and [  # type: ignore[return-value]
            dict(zip(table.column_names, row))
            for row in zip(*[table.column(c).to_pylist() for c in table.column_names])
        ]
    except ImportError:
        pass
    try:
        import pandas as pd  # type: ignore[import-untyped]
        df = pd.read_parquet(str(path))
        return df.to_dict(orient="records")  # type: ignore[return-value]
    except ImportError:
        _log.warning(
            "dataset_scanner: pyarrow/pandas not installed — skipping %s", path.name
        )
    except Exception as exc:  # noqa: BLE001
        _log.warning("dataset_scanner: could not read parquet %s: %s", path.name, exc)
    return []


def _load_file(path: pathlib.Path) -> list[dict[str, Any]]:
    ext = path.suffix.lower()
    if ext == ".jsonl":
        return _load_jsonl(path)
    if ext == ".json":
        return _load_json(path)
    if ext == ".csv":
        return _load_csv(path)
    if ext == ".txt":
        return _load_txt(path)
    if ext == ".parquet":
        return _load_parquet(path)
    return []


def _collect_files(root: pathlib.Path) -> list[pathlib.Path]:
    """Recursively collect all supported dataset files under *root*."""
    if root.is_file():
        return [root] if root.suffix.lower() in _SUPPORTED_EXTENSIONS else []
    files: list[pathlib.Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in _SUPPORTED_EXTENSIONS:
            files.append(p)
    return files


# ---------------------------------------------------------------------------
# Article 10 checks
# ---------------------------------------------------------------------------


def _estimate_tokens(rows: list[dict[str, Any]]) -> int:
    """Rough token estimate: ~4 chars per token across all string values."""
    total_chars = 0
    for row in rows:
        for val in row.values():
            if isinstance(val, str):
                total_chars += len(val)
    return max(1, total_chars // 4)


def _count_pii_entities(rows: list[dict[str, Any]]) -> int:
    """Count total PII entity hits across all string values in all rows."""
    count = 0
    for row in rows:
        for val in row.values():
            if not isinstance(val, str):
                continue
            if _PII_EMAIL_RE.search(val):
                count += 1
            if _PII_PHONE_RE.search(val):
                count += 1
            if _PII_SSN_RE.search(val):
                count += 1
    return count


def _compute_pii_density(rows: list[dict[str, Any]], token_estimate: int) -> float:
    """Return PII entity count per 1 000 tokens (0.0 if no tokens)."""
    if not rows or token_estimate == 0:
        return 0.0
    pii_count = _count_pii_entities(rows)
    return (pii_count / token_estimate) * 1000


def _check_consent_coverage(rows: list[dict[str, Any]]) -> float:
    """Return fraction of rows that have at least one consent field (0–100).

    Returns 100.0 for empty datasets (vacuously true — no rows violate the rule).
    """
    if not rows:
        return 100.0
    hits = sum(
        1 for row in rows if any(k.lower() in _CONSENT_FIELDS for k in row)
    )
    return (hits / len(rows)) * 100.0


def _check_provenance_coverage(rows: list[dict[str, Any]]) -> float:
    """Return fraction of rows that have at least one source/provenance field (0–100).

    Returns 100.0 for empty datasets (vacuously true — no rows violate the rule).
    """
    if not rows:
        return 100.0
    hits = sum(
        1 for row in rows if any(k.lower() in _PROVENANCE_FIELDS for k in row)
    )
    return (hits / len(rows)) * 100.0


def _detect_bias_signal(rows: list[dict[str, Any]]) -> str:
    """Estimate bias signal from vocabulary distribution skew.

    Uses a Zipf-skew heuristic: the top-1 token representing more than
    40% of total tokens indicates *high* skew; 20–40% is *medium*.

    Requires at least 30 total tokens to produce a meaningful signal;
    smaller datasets always return ``"low"``.

    Returns ``"low"``, ``"medium"``, or ``"high"``.
    """
    if not rows:
        return "low"

    token_freq: dict[str, int] = {}
    total = 0
    for row in rows:
        for val in row.values():
            if not isinstance(val, str):
                continue
            for word in re.split(r"[^a-z0-9]+", val.lower()):
                if len(word) >= 3:
                    token_freq[word] = token_freq.get(word, 0) + 1
                    total += 1

    # Not enough data for a meaningful skew signal
    if total < 30:
        return "low"

    top_freq = max(token_freq.values(), default=0)
    top_ratio = top_freq / total

    if top_ratio > 0.40:
        return "high"
    if top_ratio > 0.20:
        return "medium"
    return "low"


def _build_clauses(
    pii_density: float,
    consent_pct: float,
    provenance_pct: float,
    bias_signal: str,
) -> list[Article10Clause]:
    """Map scan metrics to EU AI Act Article 10 clauses."""
    clauses: list[Article10Clause] = []

    # Art. 10(2)(a) — Data quality: PII density
    pii_ok = pii_density < 1.0  # threshold: <1 PII entity per 1k tokens
    clauses.append(Article10Clause(
        clause_id="Art.10(2)(a)",
        title="Data quality — PII density",
        passed=pii_ok,
        detail=(
            f"PII density {pii_density:.4f} per 1k tokens — "
            + ("within threshold (<1.0)" if pii_ok else "EXCEEDS threshold (≥1.0)")
        ),
    ))

    # Art. 10(2)(b) — Consent documentation
    consent_ok = consent_pct >= 80.0
    clauses.append(Article10Clause(
        clause_id="Art.10(2)(b)",
        title="Data governance — consent documentation",
        passed=consent_ok,
        detail=(
            f"Consent metadata present in {consent_pct:.1f}% of rows — "
            + ("sufficient (≥80%)" if consent_ok else "INSUFFICIENT (<80%)")
        ),
    ))

    # Art. 10(2)(c) — Data provenance / source traceability
    provenance_ok = provenance_pct >= 80.0
    clauses.append(Article10Clause(
        clause_id="Art.10(2)(c)",
        title="Data collection — source provenance",
        passed=provenance_ok,
        detail=(
            f"Source field present in {provenance_pct:.1f}% of rows — "
            + ("sufficient (≥80%)" if provenance_ok else "INSUFFICIENT (<80%)")
        ),
    ))

    # Art. 10(2)(d) — Bias detection
    bias_ok = bias_signal == "low"
    clauses.append(Article10Clause(
        clause_id="Art.10(2)(d)",
        title="Bias detection — vocabulary distribution",
        passed=bias_ok,
        detail=(
            f"Vocabulary skew signal: {bias_signal.upper()} — "
            + ("acceptable" if bias_ok else "REVIEW RECOMMENDED")
        ),
    ))

    return clauses


# ---------------------------------------------------------------------------
# HMAC signing
# ---------------------------------------------------------------------------

def _sign_report(body_json: str) -> str:
    """HMAC-SHA256 sign the report body; key from SPANFORGE_SIGNING_KEY env var."""
    key_raw = os.environ.get("SPANFORGE_SIGNING_KEY", "spanforge-default")
    key_bytes = key_raw.encode("utf-8")
    sig = hmac.new(key_bytes, body_json.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"hmac-sha256:{sig}"


# ---------------------------------------------------------------------------
# PDF rendering (optional — requires reportlab)
# ---------------------------------------------------------------------------

def _render_pdf(report: "DatasetComplianceReport", out_path: pathlib.Path) -> None:  # pragma: no cover
    """Render *report* as a PDF at *out_path*.

    Requires ``reportlab``.  Called by the compliance CLI when ``--output pdf``
    is requested.  Raises ``ImportError`` if reportlab is not installed.
    """
    from reportlab.lib import colors  # type: ignore[import-untyped]
    from reportlab.lib.pagesizes import A4  # type: ignore[import-untyped]
    from reportlab.lib.styles import getSampleStyleSheet  # type: ignore[import-untyped]
    from reportlab.lib.units import cm  # type: ignore[import-untyped]
    from reportlab.platypus import (  # type: ignore[import-untyped]
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    overall = "PASS" if all(c.passed for c in report.eu_ai_act_article_10_clauses) else "FAIL"

    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()
    story: list[object] = []

    story.append(Paragraph(
        "SpanForge \u2014 EU AI Act Article 10 Training Data Compliance Report",
        styles["Title"],
    ))
    story.append(Spacer(1, 12))
    story.append(Paragraph(f"<b>Scan ID:</b> {report.scan_id}", styles["Normal"]))
    story.append(Paragraph(f"<b>Scanned at:</b> {report.scanned_at}", styles["Normal"]))
    story.append(Paragraph(f"<b>Dataset path:</b> {report.dataset_path}", styles["Normal"]))
    story.append(Paragraph(f"<b>Overall:</b> {overall}", styles["Normal"]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Dataset Summary", styles["Heading2"]))
    summary_data = [
        ["Metric", "Value"],
        ["Files scanned", str(report.file_count)],
        ["Rows scanned", f"{report.row_count:,}"],
        ["Token estimate", f"{report.token_estimate:,}"],
        ["PII density score", f"{report.pii_density_score:.4f} per 1k tokens"],
        ["Consent coverage", f"{report.consent_coverage_pct:.1f}%"],
        ["Provenance coverage", f"{report.provenance_coverage_pct:.1f}%"],
        ["Bias signal", report.bias_signal.upper()],
    ]
    summary_table = Table(summary_data, colWidths=[8 * cm, 9 * cm])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.lightgrey]),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 12))

    story.append(Paragraph("EU AI Act Article 10 Clause Results", styles["Heading2"]))
    clause_data: list[list[str]] = [["Clause ID", "Title", "Status", "Detail"]]
    for clause in report.eu_ai_act_article_10_clauses:
        clause_data.append([
            clause.clause_id,
            clause.title,
            "PASS" if clause.passed else "FAIL",
            clause.detail,
        ])
    clause_table = Table(clause_data, colWidths=[2.5 * cm, 5 * cm, 1.8 * cm, 9.2 * cm])
    clause_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("WORDWRAP", (3, 1), (3, -1), True),
    ]))
    story.append(clause_table)
    story.append(Spacer(1, 12))

    story.append(Paragraph("Signed Evidence", styles["Heading2"]))
    story.append(Paragraph(
        f"HMAC-SHA256: {report.hmac_signature}",
        styles.get("Code", styles["Normal"]),
    ))

    doc.build(story)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_dataset_compliance(
    path: str | pathlib.Path,
    *,
    sign: bool = True,
) -> DatasetComplianceReport:
    """Scan *path* (file or directory) and return a signed compliance report.

    Args:
        path: Path to a dataset file or directory to scan recursively.
        sign: If ``True`` (default), HMAC-sign the report body using the
            ``SPANFORGE_SIGNING_KEY`` environment variable.

    Returns:
        A :class:`DatasetComplianceReport` with all Article 10 clause results
        and an HMAC signature.

    Raises:
        FileNotFoundError: If *path* does not exist.
    """
    from spanforge.ulid import generate as _generate_ulid

    root = pathlib.Path(path)
    if not root.exists():
        raise FileNotFoundError(f"dataset path not found: {root}")

    scan_id: str = _generate_ulid()
    scanned_at: str = datetime.now(timezone.utc).isoformat(timespec="seconds")

    files = _collect_files(root)
    all_rows: list[dict[str, Any]] = []
    for fpath in files:
        all_rows.extend(_load_file(fpath))

    token_estimate = _estimate_tokens(all_rows)
    pii_density = _compute_pii_density(all_rows, token_estimate)
    consent_pct = _check_consent_coverage(all_rows)
    provenance_pct = _check_provenance_coverage(all_rows)
    bias_signal = _detect_bias_signal(all_rows)
    clauses = _build_clauses(pii_density, consent_pct, provenance_pct, bias_signal)

    report = DatasetComplianceReport(
        scan_id=scan_id,
        scanned_at=scanned_at,
        dataset_path=str(root.resolve()),
        file_count=len(files),
        row_count=len(all_rows),
        token_estimate=token_estimate,
        pii_density_score=pii_density,
        consent_coverage_pct=consent_pct,
        provenance_coverage_pct=provenance_pct,
        bias_signal=bias_signal,
        eu_ai_act_article_10_clauses=clauses,
    )

    if sign:
        body = json.dumps(report._body_dict(), sort_keys=True)
        report.hmac_signature = _sign_report(body)

    return report
