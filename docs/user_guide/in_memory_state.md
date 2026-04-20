# In-Memory State Behaviour

## Overview

SpanForge services can run in **local mode** (no remote endpoint configured) or
**sandbox mode** (`SPANFORGE_SANDBOX=1`).  Both modes store state in-memory or
in local files rather than a remote backend.

> **Warning:** In-memory state is **ephemeral**.  All data stored in local or
> sandbox mode is lost when the Python process exits.  Do **not** rely on
> in-memory state for production audit trails, compliance records, or alert
> history.

---

## Which Services Use In-Memory State

| Service | Local / Sandbox Behaviour | Data at Risk |
|---|---|---|
| `sf_observe` | Spans written to an in-memory ring buffer | All spans lost on restart |
| `sf_alert` | Alerts queued in-memory; no delivery to webhooks or email | Alerts silently discarded |
| `sf_audit` | Records written to a local SQLite file or in-memory DB | Lost if `db_path` not set |
| `sf_pii` | Scan results held in-memory; no remote logging | No persistence impact |
| `sf_secrets` | Scan results returned to caller; nothing persisted | No persistence impact |
| `sf_gate` | Gate verdicts written to local YAML; not shipped to CI | No remote reporting |

---

## Risks and Mitigations

### 1 — Silent data loss on process restart

In local mode, `sf_observe` spans and `sf_alert` queued alerts are discarded
when the process exits.  There is no replay mechanism.

**Mitigation:** Configure a real endpoint:

```toml
# spanforge.toml
[spanforge]
endpoint = "https://ingest.example.com"
```

Or configure `sf_audit` with a persistent file-based backend:

```python
import spanforge.sdk as sf
sf.sf_audit = sf.SFAuditClient(db_path="/var/log/spanforge/audit.db")
```

### 2 — Multi-process inconsistency

Multiple worker processes (e.g. gunicorn, Celery) each maintain **separate**
in-memory states.  Spans from one worker are invisible to another.

**Mitigation:** Use a shared backend (PostgreSQL, S3-backed JSONL, Redis) and
configure `endpoint` pointing to a running SpanForge server.

### 3 — Sandbox mode silently discards audit records

`SPANFORGE_SANDBOX=1` is intended for development only.  Enabling it in
production causes audit records to be silently discarded with no error.

**Mitigation:** `spanforge doctor` emits a `[SANDBOX ACTIVE]` warning when
sandbox mode is detected.  Add a startup check to CI:

```bash
spanforge doctor --fail-on sandbox
```

---

## Detecting Local / Sandbox Mode at Runtime

```python
from spanforge.sdk import sf_audit

status = sf_audit.get_status()
if status.get("mode") in ("local", "sandbox"):
    import warnings
    warnings.warn(
        "sf_audit is running in local/sandbox mode — "
        "audit records will not be persisted remotely.",
        stacklevel=2,
    )
```

---

## Production Checklist

Before deploying to production, verify:

- [ ] `SPANFORGE_SANDBOX` is **not** set (or is `0` / `false`).
- [ ] `[spanforge] endpoint` is set to a live ingestion URL.
- [ ] `sf_audit` is configured with a persistent `db_path` or remote endpoint.
- [ ] `spanforge doctor` reports no warnings about local or sandbox mode.

---

## See Also

- [ADR-004: Local-First Architecture](../adr/ADR-004-local-first-architecture.md)
- [ADR-005: Sandbox Mode](../adr/ADR-005-sandbox-mode.md)
- [Configuration Reference](../configuration.md)
- [Runbook](../runbook.md)
