# `spanforge.sdk.trust` — T.R.U.S.T. Scorecard

> **Module:** `spanforge.sdk.trust`  
> **Added in:** 2.0.9 (Phase 10 — T.R.U.S.T. Scorecard & HallucCheck Contract)  
> **Import:** `from spanforge.sdk import sf_trust` or `from spanforge.sdk.trust import SFTrustClient`

The trust module provides the `SFTrustClient` singleton for computing the
five-pillar T.R.U.S.T. scorecard (Transparency · Reliability · UserTrust ·
Security · Traceability), generating SVG badges, and querying trust history.

---

## Quick example

```python
from spanforge.sdk import sf_trust

scorecard = sf_trust.get_scorecard(project_id="my-agent")
print(scorecard.overall_score)   # 82.5
print(scorecard.colour_band)     # "green"
print(scorecard.reliability)     # TrustDimension(score=90.0, trend="up", ...)
```

---

## Singleton

`spanforge.sdk.sf_trust` is a module-level `SFTrustClient` instance constructed
from environment variables. For most use-cases, import and use the singleton:

```python
from spanforge.sdk import sf_trust

status = sf_trust.get_status()
print(status.dimension_count)          # 5
print(status.total_trust_records)      # 42
print(status.pipelines_registered)     # 5
```

---

## T.R.U.S.T. dimensions

| Pillar | What it measures | Source audit dimension |
|--------|------------------|-----------------------|
| **T**ransparency | Gate pass rate | `gate_pass_rate` |
| **R**eliability | Hallucination rate | `hallucination` |
| **U**serTrust | Bias disparity | `halluccheck.bias.v1` records |
| **S**ecurity | PII + secrets hygiene | `pii_hygiene`, `secrets_hygiene` |
| **T**raceability | Compliance posture | `compliance_posture` |

Colour bands: **green** ≥ 80, **amber** ≥ 60, **red** < 60.

---

## API reference

### `SFTrustClient(config, *, weights=None)`

Construct a trust client.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `config` | `SFClientConfig` | — | Client configuration |
| `weights` | `TrustDimensionWeights` | Equal (1.0 each) | Per-pillar weights for the weighted average |

---

### `get_scorecard(project_id=None, *, from_dt=None, to_dt=None, weights=None)`

Compute the T.R.U.S.T. scorecard for the given project and time range.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `project_id` | `str \| None` | `config.project_id` | Scoping project |
| `from_dt` | `str \| None` | `"1970-01-01T00:00:00.000000Z"` | ISO-8601 UTC start of reporting window |
| `to_dt` | `str \| None` | now | ISO-8601 UTC end of reporting window |
| `weights` | `TrustDimensionWeights \| None` | Instance default | Override dimension weights |

**Returns:** `TrustScorecardResponse`

**Raises:** `SFTrustComputeError` — if the underlying audit store is unreachable.

```python
scorecard = sf_trust.get_scorecard(
    project_id="my-agent",
    from_dt="2025-01-01T00:00:00Z",
    weights=TrustDimensionWeights(reliability=2.0, security=2.0),
)
print(scorecard.overall_score)       # weighted average
print(scorecard.colour_band)         # "green" | "amber" | "red"
print(scorecard.transparency.score)  # 0–100
print(scorecard.reliability.trend)   # "up" | "down" | "flat"
print(scorecard.record_count)        # number of trust records consumed
```

---

### `get_scorecard_async()` — async variant

> **Added in:** 2.0.14

```python
async def get_scorecard_async(
    self,
    project_id: str | None = None,
    *,
    from_dt: str | None = None,
    to_dt: str | None = None,
    weights=None,
) -> TrustScorecardResponse
```

Non-blocking async variant of `get_scorecard()`.  Delegates to the synchronous
method via `asyncio.get_event_loop().run_in_executor()` so it never blocks the
event loop.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `project_id` | `str \| None` | `config.project_id` | Scoping project |
| `from_dt` | `str \| None` | epoch | ISO-8601 UTC start |
| `to_dt` | `str \| None` | now | ISO-8601 UTC end |
| `weights` | `TrustDimensionWeights \| None` | `None` | Per-pillar weight override |

**Returns:** `TrustScorecardResponse`

**Example:**

```python
import asyncio
from spanforge.sdk import sf_trust

scorecard = asyncio.run(sf_trust.get_scorecard_async(project_id="my-agent"))
print(scorecard.overall_score)
print(scorecard.colour_band)
```

---

### `get_history(project_id=None, *, from_dt=None, to_dt=None, buckets=10)`

Return T.R.U.S.T. scorecard history as a time-series.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `project_id` | `str \| None` | `config.project_id` | Scoping project |
| `from_dt` | `str \| None` | epoch | ISO-8601 UTC start |
| `to_dt` | `str \| None` | now | ISO-8601 UTC end |
| `buckets` | `int` | `10` | Number of time buckets |

**Returns:** `list[TrustHistoryEntry]`

```python
history = sf_trust.get_history(project_id="my-agent", buckets=20)
for entry in history:
    print(entry.timestamp, entry.overall, entry.reliability)
```

---

### `get_badge(project_id=None)`

Generate an SVG badge for the project's T.R.U.S.T. score.

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `project_id` | `str \| None` | `config.project_id` | Scoping project |

**Returns:** `TrustBadgeResult` — with `.svg`, `.overall`, `.colour_band`, `.etag`

```python
badge = sf_trust.get_badge(project_id="my-agent")
with open("trust-badge.svg", "w") as f:
    f.write(badge.svg)
```

---

### `get_status()`

Return T.R.U.S.T. service health information.

**Returns:** `TrustStatusInfo`

| Field | Type | Description |
|-------|------|-------------|
| `status` | `str` | `"ok"` |
| `dimension_count` | `int` | Always `5` |
| `total_trust_records` | `int` | Records in the audit trust store |
| `pipelines_registered` | `int` | Always `5` |
| `last_scorecard_computed` | `str \| None` | ISO-8601 timestamp of the last computation |

---

## Types

| Type | Description |
|------|-------------|
| `TrustScorecardResponse` | Full scorecard: overall score, colour band, 5 dimensions, record count, weights |
| `TrustDimension` | Single dimension: `score`, `trend`, `last_updated` |
| `TrustDimensionWeights` | Configurable weights for each pillar (default 1.0 each) |
| `TrustHistoryEntry` | Time-series data point: `timestamp`, `overall`, 5 dimension scores |
| `TrustBadgeResult` | SVG badge: `svg`, `overall`, `colour_band`, `etag` |
| `TrustStatusInfo` | Service health: `status`, `dimension_count`, `total_trust_records`, `pipelines_registered` |

---

## Exceptions

| Exception | Raised when |
|-----------|-------------|
| `SFTrustComputeError` | The underlying audit store is unreachable or query fails |

---

## CLI commands

```bash
spanforge trust scorecard --project-id my-agent   # Five-pillar scorecard (text table)
spanforge trust badge --project-id my-agent        # SVG badge to stdout
spanforge trust gate --project-id my-agent         # Composite trust gate (exit 1 = below threshold)
```
