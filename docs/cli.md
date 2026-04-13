# Command-Line Interface

spanforge ships a command-line tool, `spanforge`, for operational tasks.
The entry-point is installed automatically when you `pip install spanforge`.

```bash
spanforge --help
```

```text
usage: spanforge [-h] [-V] <command> ...

spanforge command-line utilities

positional arguments:
  <command>
    check              End-to-end health check: validates config, emits a test
                       event, confirms export pipeline
    check-compat       Check a JSON file of events against the v1.0
                       compatibility checklist
    list-deprecated    Print all deprecated event types from the global
                       deprecation registry
    migration-roadmap  Print the planned v1 → v2 migration roadmap
    check-consumers    Assert all registered consumers are compatible with the
                       installed schema
    validate           Validate every event in a JSONL file against the
                       published schema
    audit-chain        Verify HMAC signing chain integrity of events in a
                       JSONL file
    audit              Audit chain management (erase, rotate-key, check-health,
                       verify)
    scan               Scan a JSONL file for PII using regex detectors
    migrate            Migrate a JSONL file from schema v1 to v2
    inspect            Pretty-print a single event by event_id from a JSONL
                       file
    stats              Print a summary of events in a JSONL file (counts,
                       tokens, cost, timestamps)
    compliance         Compliance evidence generation and attestation
                       validation
    cost               Cost brief management
    dev                Local development environment lifecycle
    module             SpanForge plugin module scaffolding
    serve              Start a local HTTP trace viewer at /traces (default
                       port 8888)
    init               Scaffold a spanforge.toml config file in the current
                       directory
    quickstart         Interactive setup wizard: configure exporter, service
                       name, and signing
    report             Generate a static HTML trace report from a JSONL events
                       file
    ui                 Open a local HTML trace viewer in your browser

options:
  -h, --help           show this help message and exit
  -V, --version        show program's version number and exit
```

## `--version`

Print the installed version and conformance profile label, then exit.

```bash
spanforge --version
spanforge -V
```

**Example output**

```
spanforge 1.0.0 [spanforge-Enterprise-2.0]
```

The bracketed label is `CONFORMANCE_PROFILE` from `spanforge.CONFORMANCE_PROFILE`
(RFC §1.5). Use this to verify that your installed SDK declares the correct
conformance class.

---

## `check`

Runs a five-step end-to-end health check of the spanforge installation:

1. Configuration loaded and valid
2. An `Event` can be created with required fields
3. The event passes JSON Schema validation
4. The export pipeline initialises and accepts the test event
5. The `TraceStore` is accessible

**Usage**

```bash
spanforge check
```

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | All five steps passed. |
| `1` | One or more steps failed (details printed to stdout). |

**Example — passing**

```bash
$ spanforge check
[1/5] Config ............. OK
[2/5] Event creation ..... OK
[3/5] Schema validation .. OK
[4/5] Export pipeline .... OK
[5/5] Trace store ........ OK
All checks passed.
```

## `check-compat`

Validate a batch of serialised events against the spanforge v1.0 compatibility
checklist (CHK-1 through CHK-5). Useful in CI pipelines, pre-commit hooks,
and onboarding audits for third-party tool authors.

**Usage**

```bash
spanforge check-compat EVENTS_JSON
```

`EVENTS_JSON`
: Path to a JSON file containing a top-level array of serialised
`Event` objects (the output of `[evt.to_dict() for evt in events]`).

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | All events passed every compatibility check. |
| `1` | One or more compatibility violations were found (details printed to stdout). |
| `2` | Usage error, file not found, or invalid JSON. |

**Example — passing**

```bash
$ spanforge check-compat events.json
OK — 42 event(s) passed all compatibility checks.
```

**Example — violations found**

```bash
$ spanforge check-compat events.json
FAIL — 2 violation(s) found in 42 event(s):

  [01JPXXX...] CHK-3 (Source identifier format): source 'MyTool/1.0' does not match ...
  [01JPYYY...] CHK-5 (Event ID is a valid ULID): event_id 'not-a-ulid' is not a valid ULID
```

**Example — generating an events file**

```python
import json
from spanforge import Event, EventType

events = [
    Event(
        event_type=EventType.TRACE_SPAN_COMPLETED,
        source="my-tool@1.0.0",
        payload={"span_name": "chat"},
    )
    for _ in range(5)
]

with open("events.json", "w") as f:
    json.dump([evt.to_dict() for evt in events], f, indent=2)
```

**Using in CI (GitHub Actions)**

```yaml
- name: Validate event compatibility
  run: |
    python -c "
    import json
    from spanforge import Event, EventType
    events = [Event(event_type=EventType.TRACE_SPAN_COMPLETED,
                    source='my-tool@1.0.0', payload={'ok': True})]
    with open('/tmp/events.json', 'w') as f:
        json.dump([e.to_dict() for e in events], f)
    "
    spanforge check-compat /tmp/events.json
```

## Compatibility checks

The `check-compat` command applies these checks to every event:

| Check ID | Rule | Details |
|----------|------|---------|
| CHK-1 | Required fields present | `schema_version`, `source`, and `payload` must be non-empty. |
| CHK-2 | Event type is registered or valid custom | Must be a first-party `EventType` value, or pass `validate_custom` (`x.<company>.<…>` format). |
| CHK-3 | Source identifier format | Must match `^[a-z][a-z0-9-]*@\d+\.\d+(\.\d+)?([.-][a-z0-9]+)*$` (e.g. `my-tool@1.2.3`). |
| CHK-5 | Event ID is a valid ULID | `event_id` must be a well-formed 26-character ULID string. |

## Programmatic usage (no CLI required)

The same checks are available directly in Python:

```python
from spanforge.compliance import test_compatibility

result = test_compatibility(events)
if not result:
    for v in result.violations:
        print(f"[{v.check_id}] {v.rule}: {v.detail}")
```

See [spanforge.compliance](api/compliance.md) for the full compliance API.

---

## `list-deprecated`

Print all deprecation notices from the global `DeprecationRegistry`.

**Usage**

```bash
spanforge list-deprecated
```

**Example output**

```
Deprecated event types (4 total):
  llm.cache.evicted → llm.cache.entry_evicted (since 1.0.0, sunset 2.0.0)
  llm.cost.estimate → llm.cost.estimated (since 1.0.0, sunset 2.0.0)
  llm.eval.regression → llm.eval.regression_failed (since 1.0.0, sunset 2.0.0)
  ...
```

The registry is pre-populated at startup with all entries from
`v2_migration_roadmap()`. Additional notices registered at runtime via
`mark_deprecated()` are also included.

---

## `migration-roadmap`

Print the structured Phase 9 v2 migration roadmap.

**Usage**

```bash
spanforge migration-roadmap [--json]
```

**Options**

| Option | Description |
|--------|-------------|
| `--json` | Output the roadmap as a JSON array instead of a human-readable table. |

**Example — table output**

```
v2 Migration Roadmap (9 entries)
===================================
llm.cache.evicted
  Since:       1.0.0
  Sunset:      2.0.0
  Policy:      NEXT_MAJOR
  Replacement: llm.cache.entry_evicted
  Notes:       Rename for namespace consistency.

...
```

**Example — JSON output**

```bash
spanforge migration-roadmap --json | python -m json.tool
```

---

## `check-consumers`

Print all consumers registered in the global `ConsumerRegistry` and check
their compatibility with the installed schema version.

**Usage**

```bash
spanforge check-consumers
```

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | All consumers are compatible. |
| `1` | One or more consumers require a newer schema version. |

**Example output — all compatible**

```
Registered consumers (2 total):
  billing-agent    namespaces=(llm.cost.*,)          requires=1.0  [OK]
  analytics-agent  namespaces=(llm.trace.*, llm.eval.*)  requires=1.1  [OK]

All consumers are compatible with installed schema version 1.0.0.
```

**Example output — incompatible**

```
Registered consumers (1 total):
  future-tool  namespaces=(llm.trace.*,)  requires=2.0  [INCOMPATIBLE]

ERROR: 1 consumer(s) require a schema version not satisfied by 1.0.0.
```

---

## `validate`

Validate every event in a JSONL file against the published v2.0 JSON Schema.
Useful for checking that events emitted by third-party integrations conform to
the canonical schema before ingestion.

**Usage**

```bash
spanforge validate EVENTS_JSONL
```

`EVENTS_JSONL`
: Path to a JSONL file (one serialised `Event` JSON object per line).

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | All events are schema-valid. |
| `1` | One or more events failed validation (details printed to stdout). |
| `2` | Usage error, file not found, or malformed JSON. |

**Example — all valid**

```bash
$ spanforge validate events.jsonl
OK — 128 event(s) are all schema-valid.
```

**Example — validation errors**

```bash
$ spanforge validate events.jsonl
FAIL — 2 event(s) failed schema validation:

  Line 14: missing required field 'source'
  Line 37: 'event_type' value 'foo.bar' is not a registered EventType
```

---

## `audit-chain`

Verify the HMAC-SHA256 signing chain of a JSONL file produced when
`signing_key` was set via `configure()`. Detects tampering, deletions, and
out-of-order events.

The signing secret is read from the `spanforge_SIGNING_KEY` environment variable.

**Usage**

```bash
spanforge_SIGNING_KEY=my-secret spanforge audit-chain EVENTS_JSONL
```

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Chain is intact — all signatures verify and no gaps detected. |
| `1` | Chain is broken — at least one tampered event or missing link. |
| `2` | Usage error, file not found, or `spanforge_SIGNING_KEY` not set. |

**Example — intact chain**

```bash
$ spanforge_SIGNING_KEY=secret spanforge audit-chain events.jsonl
OK — chain of 50 event(s) is intact. No tampering or gaps detected.
```

**Example — tampered chain**

```bash
FAIL — chain verification failed:
  Event 01JPXXX... signature mismatch (tampered or wrong key)
  Gap detected: event 01JPYYY... has no prev_id link to prior event
```

---

## `inspect`

Look up a single event by its `event_id` in a JSONL file and pretty-print it
as indented JSON. Useful for debugging a specific event without loading the
whole file.

**Usage**

```bash
spanforge inspect EVENT_ID EVENTS_JSONL
```

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Event found and printed. |
| `1` | Event ID not found in file. |
| `2` | Usage error or file not found. |

**Example**

```bash
$ spanforge inspect 01JPXXXXXXXXXXXXXXXXXXX events.jsonl
{
  "event_id": "01JPXXXXXXXXXXXXXXXXXXX",
  "schema_version": "2.0",
  "event_type": "llm.trace.span.completed",
  "source": "my-app@1.0.0",
  ...
}
```

---

## `stats`

Print a human-readable summary of all events in a JSONL file: total count,
breakdown by event type, total input/output tokens, estimated cost, and the
timestamp range of the events.

**Usage**

```bash
spanforge stats EVENTS_JSONL
```

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Summary printed successfully. |
| `2` | Usage error or file not found. |

**Example**

```bash
$ spanforge stats events.jsonl
Events:  342 total
Types:
  llm.trace.span.completed  : 300
  llm.cost.token_recorded   :  42
Tokens:  input=48 200  output=12 300  total=60 500
Cost:    $0.1820 USD
Range:   2026-03-04T08:00:00Z → 2026-03-04T09:15:33Z
```

---

## `compliance`

Generate compliance evidence packages and validate attestations against
regulatory frameworks. Supports EU AI Act, ISO 42001, NIST AI RMF, GDPR,
and SOC 2.

### `compliance generate`

Generate a full compliance evidence package (JSON) including clause mappings,
gap analysis, and HMAC-signed attestations. Attestations are automatically
enriched with model registry metadata (`model_owner`, `model_risk_tier`,
`model_status`, `model_warnings`) and `explanation_coverage_pct` when
corresponding telemetry events are present.

The engine maps event prefixes to regulatory clauses including:
- `consent.*` / `hitl.*` → GDPR Art. 22, EU AI Act Art. 14
- `explanation.*` → EU AI Act Art. 13, NIST MAP 1.1
- `model_registry.*` → SOC 2 CC6.1, NIST MAP 1.1

**Usage**

```bash
spanforge compliance generate --model MODEL_ID --framework FRAMEWORK --from FROM_DATE --to TO_DATE [EVENTS_JSONL]
```

**Options**

| Option | Description |
|--------|-------------|
| `--model` | AI model identifier (e.g. `gpt-4o`). |
| `--framework` | Compliance framework: `eu_ai_act`, `iso_42001`, `nist_ai_rmf`, `gdpr`, `soc2`. |
| `--from` | Start of audit period (ISO-8601 date). |
| `--to` | End of audit period (ISO-8601 date). |

**Example**

```bash
spanforge compliance generate --model gpt-4o --framework eu_ai_act --from 2026-01-01 --to 2026-03-31 events.jsonl
```

### `compliance check`

Validate a previously generated evidence package (JSON) and verify its HMAC
attestation signatures.

**Usage**

```bash
spanforge compliance check EVIDENCE_JSON
```

### `compliance validate-attestation`

Verify the HMAC-SHA256 attestation signature inside an evidence package.

**Usage**

```bash
spanforge compliance validate-attestation EVIDENCE_JSON
```

---

## `serve`

Start a local HTTP server that serves the SPA trace viewer at `/traces`.
Requires `enable_trace_store=True` in configuration.

**Usage**

```bash
spanforge serve [--port PORT]
```

**Options**

| Option | Description |
|--------|-------------|
| `--port` | HTTP port (default: `8888`). |

**Example**

```bash
spanforge serve --port 9000
```

---

## `ui`

Open a self-contained HTML trace viewer in your default browser.

**Usage**

```bash
spanforge ui [EVENTS_JSONL]
```

---

## `cost`

Cost tracking and analysis commands.

### `cost brief submit`

Submit a cost brief JSON file to the local brief store.

**Usage**

```bash
spanforge cost brief submit --file BRIEF_JSON [--store STORE_JSON]
```

**Options**

| Option | Default | Description |
|--------|---------|-------------|
| `--file` | *(required)* | Path to a cost brief JSON file. |
| `--store` | `.spanforge-cost-briefs.json` | Path to the local cost brief store. |

### `cost run`

Show a per-run cost breakdown for a single agent run. Reads a JSONL events
file, filters `llm.cost.*` and `llm.trace.agent.completed` events by run ID,
and prints a per-model cost table.

**Usage**

```bash
spanforge cost run --run-id RUN_ID --input EVENTS_JSONL
```

**Options**

| Option | Description |
|--------|-------------|
| `--run-id` | Agent run identifier (from `llm.trace.agent.completed` payload). |
| `--input` | Path to a JSONL events file to search. |

**Example**

```bash
$ spanforge cost run --run-id 01JPXXXXXXXX --input events.jsonl
==============================================================
  SpanForge Per-Run Cost Report
==============================================================
  Run ID         : 01JPXXXXXXXX
  Agent          : research-agent
  Status         : ok
  Duration       : 2,340.0 ms
  Total cost     : $0.005200
  Input tokens   : 1,024
  Output tokens  : 384
  LLM calls      : 3
--------------------------------------------------------------
  Cost by model:
  Model                          Calls  Input $   Output $    Total $
  ------------------------------ ----- --------- --------- ----------
  gpt-4o                             2 $0.002560 $0.001920  $0.004480
  gpt-4o-mini                        1 $0.000077 $0.000115  $0.000192
==============================================================
```

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Cost breakdown printed successfully. |
| `1` | No events found for the given run ID. |
| `2` | Usage error or file not found. |

---

## `dev`

Local development environment lifecycle commands (start, stop, status).

**Usage**

```bash
spanforge dev [start|stop|status]
```

---

## `module`

Scaffold a new spanforge plugin module with boilerplate files.

**Usage**

```bash
spanforge module MODULE_NAME
```

---

## `init`

Scaffold a `spanforge.toml` configuration file in the current directory.

**Usage**

```bash
spanforge init
```

---

## `quickstart`

Interactive setup wizard that walks you through configuring an exporter,
service name, and signing key.

**Usage**

```bash
spanforge quickstart
```

---

## `scan`

Scan a JSONL audit file for PII using built-in regex detectors (SSN, credit
card, email, phone, etc.). Useful as a CI gate or pre-export validation step.

**Usage**

```bash
spanforge scan FILE [--format {text,json}] [--types TYPES] [--fail-on-match]
```

**Positional arguments**

| Argument | Description |
|----------|-------------|
| `FILE` | Path to the JSONL file to scan. |

**Options**

| Option | Description |
|--------|-------------|
| `--format` | Output format: `text` (default) or `json`. |
| `--types` | Comma-separated PII types to filter (e.g. `ssn,credit_card`). When omitted, all detectors run. |
| `--fail-on-match` | Exit with code `1` if any PII is detected. Useful for CI gate mode. |

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | No PII detected (or `--fail-on-match` not set). |
| `1` | PII detected and `--fail-on-match` was set. |

**Example — basic scan**

```bash
$ spanforge scan audit.jsonl
Scanned 128 event(s): 3 PII hit(s) found.
  ssn          payload.user_info.id     (2 matches, sensitivity=high)
  credit_card  payload.payment.card_no  (1 match,  sensitivity=high)
```

**Example — CI gate with type filter**

```bash
spanforge scan audit.jsonl --types ssn,credit_card --fail-on-match --format json
```

---

## `migrate`

Migrate a JSONL file from schema v1.0 to v2.0. Applies field renames
(`model` → `model_id`), tag coercion, and md5 → sha256 checksum re-hashing.

**Usage**

```bash
spanforge migrate FILE [--output FILE] [--target-version VER] [--sign] [--dry-run]
```

**Positional arguments**

| Argument | Description |
|----------|-------------|
| `FILE` | Path to the input JSONL file. |

**Options**

| Option | Description |
|--------|-------------|
| `--output` | Output file path (default: `<input>_v2.jsonl`). |
| `--target-version` | Target schema version (default: `2.0`). |
| `--sign` | Re-sign the migrated chain using `SPANFORGE_SIGNING_KEY`. |
| `--dry-run` | Preview migration stats without writing output. |

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Migration completed successfully. |
| `1` | Errors occurred during migration. |

**Example**

```bash
$ spanforge migrate audit.jsonl --sign
Migrated 120/128 events → audit_v2.jsonl
Skipped: 8 (already v2.0), Errors: 0
Transformed: payload.model→model_id (45), checksum.md5→sha256 (12)
```

**Example — dry run**

```bash
$ spanforge migrate audit.jsonl --dry-run
[DRY RUN] Would migrate 120/128 events, skip 8
```

---

## `audit`

The `audit` command groups audit chain management sub-commands for GDPR
erasure, key rotation, health checks, and chain verification.

### `audit erase`

GDPR subject erasure: replaces events mentioning a subject with tombstone
records while preserving chain integrity.

**Usage**

```bash
spanforge audit erase EVENTS_JSONL --subject-id ID [--erased-by WHO] [--reason TEXT] [--request-ref REF] [--output FILE]
```

**Options**

| Option | Description |
|--------|-------------|
| `--subject-id` | **(required)** The data-subject identifier to erase. |
| `--erased-by` | Identity of the operator performing erasure (default: `cli`). |
| `--reason` | Reason for erasure (default: `GDPR Art.17 right to erasure`). |
| `--request-ref` | External erasure request reference (e.g. ticket ID). |
| `--output` | Output file (required — must differ from input to prevent overwrite). |

### `audit rotate-key`

Rotate the HMAC signing key in a JSONL audit file. Re-signs the entire chain
with the new key and verifies the result.

**Usage**

```bash
spanforge audit rotate-key EVENTS_JSONL [--new-key-env VAR] [--output FILE] [--reason TEXT]
```

**Options**

| Option | Description |
|--------|-------------|
| `--new-key-env` | Environment variable holding the new signing key (default: `SPANFORGE_NEW_SIGNING_KEY`). |
| `--output` | Output file (default: `<input>.rotated.jsonl`). |
| `--reason` | Reason for key rotation (default: `scheduled rotation`). |

**Example**

```bash
$ SPANFORGE_SIGNING_KEY=old-key SPANFORGE_NEW_SIGNING_KEY=new-key \
    spanforge audit rotate-key audit.jsonl --output audit_rotated.jsonl
Rotated 128 event(s) → audit_rotated.jsonl
Chain re-verified: OK
```

### `audit check-health`

Run health checks on a JSONL audit file: PII scan, chain integrity,
egress configuration, and configuration validation.

**Usage**

```bash
spanforge audit check-health EVENTS_JSONL [--output {text,json}]
```

**Options**

| Option | Description |
|--------|-------------|
| `--output` | Output format: `text` (default) or `json`. |

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | All health checks passed. |
| `1` | One or more checks failed (details printed). |

**Example**

```bash
$ spanforge audit check-health audit.jsonl --output json
{
  "config": "OK",
  "chain_integrity": "OK",
  "pii_scan": "WARN: 2 PII hits",
  "egress": "OK"
}
```

### `audit verify`

Verify HMAC chain integrity of one or more JSONL audit files. Supports
glob patterns for multi-file verification.

**Usage**

```bash
spanforge audit verify --input FILE_OR_GLOB [--key KEY]
```

**Options**

| Option | Description |
|--------|-------------|
| `--input` | Path to JSONL audit file (supports glob: `audit-*.jsonl`). |
| `--key` | HMAC signing key (default: reads `$SPANFORGE_SIGNING_KEY`). |

**Example**

```bash
$ spanforge audit verify --input "audit-*.jsonl"
audit-2026-01.jsonl: OK (1200 events, chain intact)
audit-2026-02.jsonl: OK (980 events, chain intact)
```

---

## `report`

Generate a static HTML trace report from a JSONL events file.

**Usage**

```bash
spanforge report EVENTS_JSONL [-o OUTPUT_PATH]
```
