"""spanforge.sdk.trust — T.R.U.S.T. Scorecard service (Phase 10).

Implements TRS-001 through TRS-006: the five-pillar T.R.U.S.T. dimension
model (Transparency, Reliability, UserTrust, Security, Traceability) with
configurable weights, weighted scoring, badge generation, and scorecard API.

Architecture
------------
* Reads from the existing T.R.U.S.T. store written by
  :meth:`~spanforge.sdk.audit.SFAuditClient.append`.
* Maps the existing 5 audit dimensions to the T.R.U.S.T. acronym pillars:
    - ``hallucination``      → Reliability
    - ``pii_hygiene``        → Security
    - ``secrets_hygiene``    → Security (merged)
    - ``gate_pass_rate``     → Transparency
    - ``compliance_posture`` → Traceability
* UserTrust is derived from bias audit records.
* Each dimension scored 0–100.  Overall = weighted average.
* Colour bands: green ≥ 80, amber ≥ 60, red < 60.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

from spanforge.sdk._base import SFClientConfig, SFServiceClient
from spanforge.sdk._exceptions import SFTrustComputeError
from spanforge.sdk._types import (
    TrustBadgeResult,
    TrustDimension,
    TrustDimensionWeights,
    TrustHistoryEntry,
    TrustScorecardResponse,
    TrustStatusInfo,
)

__all__ = ["SFTrustClient"]

_log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Colour-band logic
# ---------------------------------------------------------------------------

def _colour_band(score: float) -> str:
    """Return the colour band for a T.R.U.S.T. score."""
    if score >= 80.0:
        return "green"
    if score >= 60.0:
        return "amber"
    return "red"


def _weighted_average(
    dimensions: dict[str, float],
    weights: TrustDimensionWeights,
) -> float:
    """Compute the weighted average of five dimension scores."""
    w = {
        "transparency": weights.transparency,
        "reliability": weights.reliability,
        "user_trust": weights.user_trust,
        "security": weights.security,
        "traceability": weights.traceability,
    }
    total_weight = sum(w.values())
    if total_weight == 0:
        return 0.0
    weighted_sum = sum(dimensions[k] * w[k] for k in dimensions)
    return round(weighted_sum / total_weight, 2)


# ---------------------------------------------------------------------------
# Dimension mapping from existing audit trust records
# ---------------------------------------------------------------------------

# Existing audit dimension → T.R.U.S.T. pillar
_AUDIT_DIM_TO_TRUST: dict[str, str] = {
    "hallucination": "reliability",
    "pii_hygiene": "security",
    "secrets_hygiene": "security",
    "gate_pass_rate": "transparency",
    "compliance_posture": "traceability",
}


def _compute_dim_score(records: list[dict[str, Any]]) -> tuple[float, str]:
    """Compute score and trend from trust records (same logic as audit.py)."""
    if not records:
        return 50.0, "flat"

    raw_scores: list[float] = []
    for r in records:
        s = r.get("score")
        try:
            v = float(s)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            v = 0.5
        raw_scores.append(v * 100 if v <= 1.0 else min(v, 100.0))

    if not raw_scores:
        return 50.0, "flat"

    avg = sum(raw_scores) / len(raw_scores)

    # Trend: compare first half vs second half
    mid = max(1, len(raw_scores) // 2)
    first_half = sum(raw_scores[:mid]) / mid
    second_half = sum(raw_scores[mid:]) / max(1, len(raw_scores) - mid)

    delta = second_half - first_half
    if delta > 2.0:
        trend = "up"
    elif delta < -2.0:
        trend = "down"
    else:
        trend = "flat"

    return round(avg, 2), trend


# ---------------------------------------------------------------------------
# SVG badge template (TRS-006)
# ---------------------------------------------------------------------------

_SVG_BADGE_TEMPLATE = """\
<svg xmlns="http://www.w3.org/2000/svg" width="140" height="20">
  <linearGradient id="b" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <mask id="a"><rect width="140" height="20" rx="3" fill="#fff"/></mask>
  <g mask="url(#a)">
    <rect width="80" height="20" fill="#555"/>
    <rect x="80" width="60" height="20" fill="{colour}"/>
    <rect width="140" height="20" fill="url(#b)"/>
  </g>
  <g fill="#fff" text-anchor="middle" font-family="DejaVu Sans,Verdana,sans-serif" font-size="11">
    <text x="40" y="14">T.R.U.S.T.</text>
    <text x="110" y="14">{score}</text>
  </g>
</svg>"""

_COLOUR_MAP = {"green": "#4c1", "amber": "#dfb317", "red": "#e05d44"}


def _generate_badge_svg(score: float, band: str) -> str:
    """Return an SVG badge string for the given score and colour band."""
    colour = _COLOUR_MAP.get(band, "#9f9f9f")
    return _SVG_BADGE_TEMPLATE.format(colour=colour, score=int(round(score)))


# ---------------------------------------------------------------------------
# SFTrustClient
# ---------------------------------------------------------------------------


class SFTrustClient(SFServiceClient):
    """T.R.U.S.T. scorecard service client (Phase 10).

    Reads trust records from sf-audit and computes the five T.R.U.S.T.
    dimensions with configurable weights.

    Args:
        config:  Client configuration.
        weights: Dimension weights for the weighted average computation.
                 Defaults to equal weights (1.0 each).
    """

    def __init__(
        self,
        config: SFClientConfig,
        *,
        weights: TrustDimensionWeights | None = None,
    ) -> None:
        super().__init__(config, service_name="trust")
        self._weights = weights or TrustDimensionWeights()
        self._last_computed: str | None = None

    # ------------------------------------------------------------------
    # TRS-001 / TRS-005: get_scorecard
    # ------------------------------------------------------------------

    def get_scorecard(
        self,
        project_id: str | None = None,
        *,
        from_dt: str | None = None,
        to_dt: str | None = None,
        weights: TrustDimensionWeights | None = None,
    ) -> TrustScorecardResponse:
        """Return the T.R.U.S.T. scorecard for *project_id* (TRS-005).

        Aggregates trust records from sf-audit and maps to the five
        T.R.U.S.T. dimensions.

        Args:
            project_id: Scoping project.  Defaults to ``config.project_id``.
            from_dt:    ISO-8601 UTC start of reporting window.
            to_dt:      ISO-8601 UTC end of reporting window.
            weights:    Override the instance default weights.

        Returns:
            :class:`~spanforge.sdk._types.TrustScorecardResponse`

        Raises:
            SFTrustComputeError: If the underlying audit store is unreachable.
        """
        from spanforge.sdk import sf_audit

        effective_project = project_id or self._config.project_id
        effective_weights = weights or self._weights
        now_iso = self._utc_now_iso()
        from_iso = from_dt or "1970-01-01T00:00:00.000000Z"
        to_iso = to_dt or now_iso

        try:
            trust_records = sf_audit._store.query_trust(
                effective_project or None, from_iso, to_iso
            )
        except Exception as exc:
            raise SFTrustComputeError(f"Failed to query trust store: {exc}") from exc

        # Bucket records by T.R.U.S.T. pillar
        by_pillar: dict[str, list[dict[str, Any]]] = {
            "transparency": [],
            "reliability": [],
            "user_trust": [],
            "security": [],
            "traceability": [],
        }

        for rec in trust_records:
            audit_dim = rec.get("trust_dimension", "compliance_posture")
            pillar = _AUDIT_DIM_TO_TRUST.get(audit_dim)
            if pillar and pillar in by_pillar:
                by_pillar[pillar].append(rec)

        # Derive UserTrust from bias records
        for rec in trust_records:
            if rec.get("record_type") == "halluccheck.bias.v1":
                by_pillar["user_trust"].append(rec)

        def _dim(name: str) -> TrustDimension:
            recs = by_pillar[name]
            score, trend = _compute_dim_score(recs)
            last_rec = recs[-1] if recs else None
            last_ts = last_rec["timestamp"] if last_rec else now_iso
            return TrustDimension(score=score, trend=trend, last_updated=last_ts)

        dims = {k: _dim(k) for k in by_pillar}
        dim_scores = {k: dims[k].score for k in dims}
        overall = _weighted_average(dim_scores, effective_weights)
        band = _colour_band(overall)

        self._last_computed = now_iso

        return TrustScorecardResponse(
            project_id=effective_project,
            overall_score=overall,
            colour_band=band,
            transparency=dims["transparency"],
            reliability=dims["reliability"],
            user_trust=dims["user_trust"],
            security=dims["security"],
            traceability=dims["traceability"],
            from_dt=from_iso,
            to_dt=to_iso,
            record_count=len(trust_records),
            weights=effective_weights,
        )

    # ------------------------------------------------------------------
    # TRS-005: get_history
    # ------------------------------------------------------------------

    def get_history(
        self,
        project_id: str | None = None,
        *,
        from_dt: str | None = None,
        to_dt: str | None = None,
        buckets: int = 10,
    ) -> list[TrustHistoryEntry]:
        """Return T.R.U.S.T. scorecard history time series.

        Divides the time range into *buckets* equal intervals and computes
        a scorecard snapshot for each.

        Args:
            project_id: Scoping project.
            from_dt:    ISO-8601 UTC start.
            to_dt:      ISO-8601 UTC end.
            buckets:    Number of time buckets (default 10).

        Returns:
            List of :class:`~spanforge.sdk._types.TrustHistoryEntry`.
        """
        from spanforge.sdk import sf_audit

        effective_project = project_id or self._config.project_id
        now_iso = self._utc_now_iso()
        from_iso = from_dt or "1970-01-01T00:00:00.000000Z"
        to_iso = to_dt or now_iso

        # Parse range into bucket boundaries
        try:
            t_start = datetime.fromisoformat(from_iso.replace("Z", "+00:00"))
            t_end = datetime.fromisoformat(to_iso.replace("Z", "+00:00"))
        except ValueError:
            t_start = datetime(1970, 1, 1, tzinfo=timezone.utc)
            t_end = datetime.now(tz=timezone.utc)

        if t_end <= t_start:
            return []

        delta = (t_end - t_start) / max(buckets, 1)
        entries: list[TrustHistoryEntry] = []

        for i in range(buckets):
            bucket_end = t_start + delta * (i + 1)
            bucket_iso = (
                bucket_end.isoformat(timespec="microseconds")
                .replace("+00:00", "Z")
            )

            try:
                trust_records = sf_audit._store.query_trust(
                    effective_project or None, from_iso, bucket_iso
                )
            except Exception:
                continue

            by_pillar: dict[str, list[dict[str, Any]]] = {
                "transparency": [],
                "reliability": [],
                "user_trust": [],
                "security": [],
                "traceability": [],
            }
            for rec in trust_records:
                audit_dim = rec.get("trust_dimension", "compliance_posture")
                pillar = _AUDIT_DIM_TO_TRUST.get(audit_dim)
                if pillar and pillar in by_pillar:
                    by_pillar[pillar].append(rec)
            for rec in trust_records:
                if rec.get("record_type") == "halluccheck.bias.v1":
                    by_pillar["user_trust"].append(rec)

            dim_scores: dict[str, float] = {}
            for k in by_pillar:
                score, _ = _compute_dim_score(by_pillar[k])
                dim_scores[k] = score

            overall = _weighted_average(dim_scores, self._weights)

            entries.append(
                TrustHistoryEntry(
                    timestamp=bucket_iso,
                    overall=overall,
                    transparency=dim_scores["transparency"],
                    reliability=dim_scores["reliability"],
                    user_trust=dim_scores["user_trust"],
                    security=dim_scores["security"],
                    traceability=dim_scores["traceability"],
                )
            )

        return entries

    # ------------------------------------------------------------------
    # TRS-006: get_badge
    # ------------------------------------------------------------------

    def get_badge(
        self,
        project_id: str | None = None,
    ) -> TrustBadgeResult:
        """Return a T.R.U.S.T. badge SVG for *project_id* (TRS-006).

        Args:
            project_id: Scoping project.

        Returns:
            :class:`~spanforge.sdk._types.TrustBadgeResult`
        """
        scorecard = self.get_scorecard(project_id=project_id)
        svg = _generate_badge_svg(scorecard.overall_score, scorecard.colour_band)
        etag = hashlib.md5(svg.encode(), usedforsecurity=False).hexdigest()  # noqa: S324

        return TrustBadgeResult(
            svg=svg,
            overall=scorecard.overall_score,
            colour_band=scorecard.colour_band,
            etag=etag,
        )

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> TrustStatusInfo:
        """Return T.R.U.S.T. service health information."""
        from spanforge.sdk import sf_audit

        try:
            total = len(sf_audit._store._trust_records)
        except Exception:
            total = 0

        return TrustStatusInfo(
            status="ok",
            dimension_count=5,
            total_trust_records=total,
            pipelines_registered=5,
            last_scorecard_computed=self._last_computed,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _utc_now_iso() -> str:
        return (
            datetime.now(tz=timezone.utc)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
