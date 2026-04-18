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
    eval               Evaluation dataset management and scorer execution
    migrate-langsmith  Convert a LangSmith export file to SpanForge events
    ui                 Open a local HTML trace viewer in your browser
    secrets            Secrets scanning commands (scan files for credentials)
    gate               CI/CD gate pipeline (run YAML pipelines, evaluate gates, trust-gate)
    config             Configuration management (validate .halluccheck.toml)
    trust              T.R.U.S.T. scorecard (scorecard, badge, gate)
    enterprise         Enterprise multi-tenancy, encryption, health
    security           OWASP audit, STRIDE threat model, dependency scan
    doctor             Environment diagnostics: config, sandbox, service health

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
spanforge 2.0.11 [spanforge-Enterprise-2.0]
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

### `compliance status`

Output a single JSON summary of compliance posture from an events file.
Includes chain integrity, PII scan results, per-clause coverage,
last attestation timestamp, and event count.

**Usage**

```bash
spanforge compliance status --events-file EVENTS.jsonl [--framework FRAMEWORK]
```

**Options**

| Option | Description |
|--------|-------------|
| `--events-file` | Path to a JSONL events file (required). |
| `--framework` | Compliance framework (default: `eu_ai_act`). |

**Example**

```bash
spanforge compliance status --events-file traces.jsonl --framework gdpr
```

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Status generated successfully. |
| `2` | File not found or read error. |

---

## `serve`

Start a local HTTP server that serves the SPA trace viewer at `/traces`.
Requires `enable_trace_store=True` in configuration.

The viewer includes a **compliance dashboard** (click the compliance chip
in the header) showing:

- **Chain integrity** — verified / not verified / tampered status
- **Overview stats** — total events, signed events, PII hits, explanation coverage
- **Clause pass/fail tables** — per-framework breakdown (SOC 2, HIPAA, GDPR, etc.)
- **Model registry** — all models observed in event payloads with counts and sources

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

**India PII (DPDP Act)**

For Indian data protection compliance, use `DPDP_PATTERNS` programmatically
with `scan_payload()`:

```python
from spanforge import scan_payload, DPDP_PATTERNS

result = scan_payload(event.payload, extra_patterns=DPDP_PATTERNS)
# Detects Aadhaar (with Verhoeff checksum) and PAN numbers
```

Built-in types: `email`, `phone`, `ssn`, `credit_card`, `ip_address`,
`uk_national_insurance`, `date_of_birth` (global formats: ISO, US, day-first
DMY, written-month), `address`. DPDP add-on types: `aadhaar` (high), `pan` (high).

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

---

## `eval`

Manage evaluation datasets and run built-in quality scorers.

### `eval save`

Extract evaluation examples from a JSONL events file into a reusable dataset.

**Usage**

```bash
spanforge eval save --input EVENTS.jsonl --output DATASET.jsonl
```

**Options**

| Option | Description |
|--------|-------------|
| `--input` | Path to JSONL events file (required). |
| `--output` | Output dataset path (default: `eval_dataset.jsonl`). |

### `eval run`

Run built-in scorers over a JSONL evaluation dataset.

**Usage**

```bash
spanforge eval run --file DATASET.jsonl [--scorers S1,S2,...] [--format text|json]
```

**Options**

| Option | Description |
|--------|-------------|
| `--file` | Path to JSONL dataset file (required). |
| `--scorers` | Comma-separated scorer names: `faithfulness`, `refusal`, `pii_leakage` (default: all). |
| `--format` | Output format: `text` (default) or `json`. |

**Example**

```bash
spanforge eval run --file dataset.jsonl --scorers faithfulness,pii_leakage --format json
```

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Evaluation completed successfully. |
| `1` | No data, unknown scorer, or error. |

---

## `migrate-langsmith`

Convert a LangSmith export file (JSONL or JSON array) to SpanForge events.

**Usage**

```bash
spanforge migrate-langsmith FILE [--output OUTPUT.jsonl] [--source NAME]
```

**Options**

| Option | Description |
|--------|-------------|
| `FILE` | Path to LangSmith export file (required). |
| `--output` | Output file (default: `<input>.spanforge.jsonl`). |
| `--source` | Source label for converted events (default: `langsmith-import`). |

**Example**

```bash
spanforge migrate-langsmith langsmith_export.jsonl --output traces.jsonl
```

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Migration completed successfully. |
| `1` | Empty or invalid input. |
| `2` | File not found. |

---

## `secrets`

Secrets scanning commands. Detects credentials, API keys, private keys, and
other sensitive material in source files before they are committed or deployed.

### `secrets scan`

Scan a file for secrets using the built-in 20-pattern registry. Suitable as a
CI gate, pre-commit hook step, or standalone audit tool.

**Usage**

```bash
spanforge secrets scan FILE [--format {text,json,sarif}] [--redact] [--confidence FLOAT]
```

**Positional arguments**

| Argument | Description |
|----------|-------------|
| `FILE` | Path to the file to scan. Accepts any text-based file. |

**Options**

| Option | Default | Description |
|--------|---------|-------------|
| `--format` | `text` | Output format: `text` (human-readable), `json`, or `sarif` (SARIF 2.1.0 for GitHub Code Scanning / VS Code). |
| `--redact` | off | Print a redacted copy of the file contents to stdout, replacing detected secrets with `[REDACTED:TYPE]`. |
| `--confidence` | `0.85` | Minimum confidence threshold (0.0–1.0). Lower values surface more candidates; raise to reduce false positives. |

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | No secrets detected at or above the confidence threshold. |
| `1` | One or more secrets detected. |
| `2` | Usage error or file not found. |

**Example — basic scan**

```bash
$ spanforge secrets scan config.env
[WARN] 2 secret(s) detected in config.env
  AWS_ACCESS_KEY  line 4   confidence=0.97  [auto-blocked]
  STRIPE_KEY      line 9   confidence=0.90
```

**Example — SARIF output for GitHub Code Scanning**

```bash
spanforge secrets scan src/config.py --format sarif > secrets.sarif
```

Upload `secrets.sarif` as a GitHub Code Scanning result to surface findings
directly in pull request reviews.

**Example — JSON output for CI pipelines**

```bash
spanforge secrets scan .env --format json
```

```json
{
  "detected": true,
  "auto_blocked": true,
  "hits": [
    {
      "secret_type": "AWS_ACCESS_KEY",
      "start": 42,
      "end": 62,
      "confidence": 0.97,
      "redacted_value": "[REDACTED:AWS_ACCESS_KEY]"
    }
  ]
}
```

**Example — redact mode**

```bash
spanforge secrets scan secrets.txt --redact
# Prints file contents with secrets replaced by [REDACTED:TYPE]
```

**Pre-commit hook**

Add to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: spanforge-secrets-scan
        name: SpanForge Secrets Scan
        entry: spanforge secrets scan
        language: python
        types: [text]
        stages: [pre-commit, pre-push]
```

Or use the built-in hook from `.pre-commit-hooks.yaml`:

```yaml
repos:
  - repo: https://github.com/veerarag1973/spanforge
    rev: v2.0.3
    hooks:
      - id: spanforge-secrets-scan
```

**Detected secret types**

| Type | Auto-blocked | Notes |
|------|:-----------:|-------|
| `BEARER_TOKEN` | ✅ | `Authorization: Bearer …` header values |
| `AWS_ACCESS_KEY` | ✅ | `AKIA…` 20-char keys |
| `GCP_SERVICE_ACCOUNT` | ✅ | `"type": "service_account"` JSON blobs |
| `PEM_PRIVATE_KEY` | ✅ | `-----BEGIN … PRIVATE KEY-----` blocks |
| `SSH_PRIVATE_KEY` | ✅ | `-----BEGIN OPENSSH PRIVATE KEY-----` blocks |
| `HC_API_KEY` | ✅ | HallucCheck API key pattern |
| `SF_API_KEY` | ✅ | SpanForge API key pattern |
| `GITHUB_PAT` | ✅ | `ghp_…` / `github_pat_…` tokens |
| `STRIPE_LIVE_KEY` | ✅ | `sk_live_…` keys |
| `NPM_TOKEN` | ✅ | `//registry.npmjs.org/:_authToken=…` |
| `GENERIC_JWT` | — | `eyJ…` base64-encoded JWT tokens |
| `GOOGLE_API_KEY` | — | `AIza…` keys |
| `SLACK_TOKEN` | — | `xox[bpoas]-…` tokens |
| `TWILIO_ACCOUNT_SID` | — | `AC…` SIDs |
| `SENDGRID_API_KEY` | — | `SG.…` keys |
| `AZURE_SAS_TOKEN` | — | `sig=…` URL parameters |
| `TERRAFORM_CLOUD_TOKEN` | — | `…atlasv1.…` tokens |
| `HASHICORP_VAULT_TOKEN` | — | `hvs.…` / `s.…` tokens |
| `GENERIC_SECRET` | — | `secret=`, `password=`, `api_key=` patterns |
| `OPENAI_API_KEY` | — | `sk-…` OpenAI keys |

---

## `gate`

CI/CD gate pipeline commands. Evaluate quality gates, run YAML pipelines, and
enforce release readiness checks before deployment.

### `gate run`

Parse and execute a YAML gate pipeline file. Gates with `on_fail: block`
that evaluate to `FAIL` exit with code `1`. Artifacts are written to the
configured artifact directory.

**Usage**

```bash
spanforge gate run GATE_YAML [--context KEY=VALUE ...] [--artifact-dir DIR] [--format {text,json}]
```

**Positional arguments**

| Argument | Description |
|----------|-------------|
| `GATE_YAML` | Path to the gate pipeline YAML file. |

**Options**

| Option | Default | Description |
|--------|---------|-------------|
| `--context` | *(none)* | One or more `KEY=VALUE` context variables for `${var}` substitution in gate commands. Repeatable. |
| `--artifact-dir` | `SPANFORGE_GATE_ARTIFACT_DIR` | Override the artifact storage directory. |
| `--format` | `text` | Output format: `text` (human-readable) or `json`. |

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | All gates passed (or warned). |
| `1` | One or more blocking gates failed. |
| `2` | Usage error, file not found, or invalid YAML schema. |

**Example — passing**

```bash
$ spanforge gate run gates/ci-pipeline.yaml
Running gate pipeline: gates/ci-pipeline.yaml
  [PASS] schema-validation   (4.7 ms)
  [PASS] secrets-scan        (12.3 ms)
  [WARN] dependency-audit    (45.1 ms)  cve_count=1 severity_max=MEDIUM
  [PASS] perf-regression     (8.9 ms)
  [PASS] prri-check          (2.1 ms)   prri_score=28.5 verdict=GREEN
  [PASS] trust-gate          (6.4 ms)
Result: 5 passed, 0 failed, 1 warned
```

**Example — with context variables**

```bash
spanforge gate run gates/ci-pipeline.yaml --context project_id=my-agent --context env=staging
```

**Example — JSON output for CI dashboards**

```bash
spanforge gate run gates/ci-pipeline.yaml --format json | python -m json.tool
```

**Using in CI (GitHub Actions)**

```yaml
- name: Run SpanForge gate pipeline
  env:
    SPANFORGE_GATE_ARTIFACT_DIR: .sf-gate/artifacts
    SPANFORGE_GATE_PRRI_RED_THRESHOLD: "65"
  run: spanforge gate run gates/ci-pipeline.yaml
```

---

### `gate evaluate`

Evaluate a single named gate against a payload file or standard input.

**Usage**

```bash
spanforge gate evaluate GATE_ID [--payload FILE] [--project-id ID] [--format {text,json}]
```

**Positional arguments**

| Argument | Description |
|----------|-------------|
| `GATE_ID` | Identifier for the gate to evaluate. |

**Options**

| Option | Description |
|--------|-------------|
| `--payload` | Path to a JSON file to evaluate (default: reads from stdin). |
| `--project-id` | Project scope for artifact isolation. |
| `--format` | Output format: `text` (default) or `json`. |

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Gate passed or warned. |
| `1` | Gate failed. |
| `2` | Usage error or gate ID not found. |

**Example**

```bash
$ spanforge gate evaluate schema-validation --payload event.json
[PASS] schema-validation  (4.2 ms)  valid=true violations=[]
```

---

### `gate trust-gate`

Run the composite trust gate check against live telemetry windows. Checks
HRI critical rate, PII detection count, and secrets detection count. Blocks
(exit code `1`) if any threshold is exceeded.

**Usage**

```bash
spanforge gate trust-gate [--project-id ID] [--format {text,json}]
```

**Options**

| Option | Description |
|--------|-------------|
| `--project-id` | Project scope for the trust gate check. |
| `--format` | Output format: `text` (default) or `json`. |

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Trust gate passed — all thresholds within bounds. |
| `1` | Trust gate blocked — one or more thresholds exceeded. |

**Example — passing**

```bash
$ spanforge gate trust-gate --project-id my-agent
[PASS] trust-gate
  HRI critical rate:    0.012  (threshold: 0.050)  OK
  PII detections (24h): 0                           OK
  Secrets detections:   0                           OK
```

**Example — blocked**

```bash
$ spanforge gate trust-gate --project-id my-agent
[FAIL] trust-gate
  HRI critical rate:    0.073  (threshold: 0.050)  EXCEEDED
  PII detections (24h): 3                           EXCEEDED
BLOCKED: 2 trust failure(s)
```

---

## `config`

Configuration management commands for `.halluccheck.toml` validation.

### `config validate`

Validate a `.halluccheck.toml` config file against the v6.0 schema.
Auto-discovers the file from the current directory (or parent directories)
when no explicit path is given.

**Usage**

```bash
spanforge config validate [--file PATH]
```

**Options**

| Option | Default | Description |
|--------|---------|-------------|
| `--file` | *(auto-discover)* | Path to a `.halluccheck.toml` file. When omitted, searches CWD and parent directories. |

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Config is valid (or no file found — defaults are valid). |
| `1` | Validation errors found (schema violations, invalid keys, bad types). |
| `2` | File could not be parsed (I/O error or TOML syntax error). |

**Example — valid config**

```bash
$ spanforge config validate
[✓] Config is valid: .halluccheck.toml
```

**Example — explicit path**

```bash
$ spanforge config validate --file config/staging.toml
[✓] Config is valid: config/staging.toml
```

**Example — validation errors**

```bash
$ spanforge config validate --file bad.toml
Config validation failed (2 error(s)):
  - Unknown key 'spanforge.foo' (not in v6.0 schema)
  - 'pii.threshold' must be a float between 0.0 and 1.0, got '2.5'
```

**Example — parse error**

```bash
$ spanforge config validate --file broken.toml
error: Failed to parse broken.toml: Invalid TOML at line 5
```

**Using in CI (GitHub Actions)**

```yaml
- name: Validate SpanForge config
  run: spanforge config validate --file .halluccheck.toml
```

---

## `trust`

T.R.U.S.T. scorecard and trust gate commands (Phase 10).

### `trust scorecard`

Display the five-pillar T.R.U.S.T. scorecard as a text table.

**Usage**

```bash
spanforge trust scorecard [--project-id PID]
```

**Options**

| Option | Default | Description |
|--------|---------|-------------|
| `--project-id` | `SPANFORGE_PROJECT_ID` or `"default"` | Project to compute the scorecard for. |

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Scorecard displayed successfully. |
| `1` | Error computing scorecard. |

**Example**

```bash
$ spanforge trust scorecard --project-id my-agent
╔══════════════════════════════════════════════════╗
║          T.R.U.S.T. Scorecard — my-agent         ║
╠══════════════╦═══════╦═══════╦═══════════════════╣
║ Dimension    ║ Score ║ Trend ║ Last Updated       ║
╠══════════════╬═══════╬═══════╬═══════════════════╣
║ Transparency ║  85.0 ║  up   ║ 2025-07-13T10:00Z ║
║ Reliability  ║  90.0 ║  up   ║ 2025-07-13T09:45Z ║
║ UserTrust    ║  78.0 ║ flat  ║ 2025-07-13T08:30Z ║
║ Security     ║  92.0 ║  up   ║ 2025-07-13T10:00Z ║
║ Traceability ║  88.0 ║  up   ║ 2025-07-13T09:00Z ║
╠══════════════╬═══════╩═══════╩═══════════════════╣
║ Overall      ║  86.6  [green]                     ║
╚══════════════╩═══════════════════════════════════╝
```

---

### `trust badge`

Write the T.R.U.S.T. SVG badge to stdout.

**Usage**

```bash
spanforge trust badge [--project-id PID]
```

**Options**

| Option | Default | Description |
|--------|---------|-------------|
| `--project-id` | `SPANFORGE_PROJECT_ID` or `"default"` | Project to generate the badge for. |

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Badge written to stdout. |
| `1` | Error computing badge. |

**Example**

```bash
$ spanforge trust badge --project-id my-agent > trust-badge.svg
```

---

### `trust gate`

Run the composite trust gate. Exits with code 1 if the overall T.R.U.S.T.
score falls in the red band (< 60).

**Usage**

```bash
spanforge trust gate [--project-id PID]
```

**Options**

| Option | Default | Description |
|--------|---------|-------------|
| `--project-id` | `SPANFORGE_PROJECT_ID` or `"default"` | Project to evaluate the trust gate for. |

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Trust gate passed (score ≥ 60). |
| `1` | Trust gate failed (score < 60 — red band). |

**Example — passing gate**

```bash
$ spanforge trust gate --project-id my-agent
T.R.U.S.T. gate PASSED: 86.6 [green]
```

**Example — failing gate**

```bash
$ spanforge trust gate --project-id my-agent
T.R.U.S.T. gate FAILED: 42.0 [red]
```

**Using in CI (GitHub Actions)**

```yaml
- name: T.R.U.S.T. gate check
  run: spanforge trust gate --project-id ${{ env.PROJECT_ID }}
```

---

## `enterprise`

Enterprise multi-tenancy and operations commands (Phase 11).

### `enterprise status`

Display the enterprise subsystem status including tenants, encryption, and air-gap configuration.

**Usage**

```bash
spanforge enterprise status [--json]
```

**Options**

| Option | Default | Description |
|--------|---------|-------------|
| `--json` | `false` | Output as JSON instead of text table. |

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Status displayed successfully. |
| `1` | Error retrieving status. |

---

### `enterprise register-tenant`

Register a new tenant for multi-tenant isolation.

**Usage**

```bash
spanforge enterprise register-tenant --org-id ORG --project-id PROJ [--region REGION]
```

**Options**

| Option | Default | Description |
|--------|---------|-------------|
| `--org-id` | *(required)* | Organisation identifier. |
| `--project-id` | *(required)* | Project identifier within the org. |
| `--region` | `"us"` | Data residency region. |

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Tenant registered successfully. |
| `1` | Registration error (duplicate, invalid config). |

---

### `enterprise list-tenants`

List all registered tenants.

**Usage**

```bash
spanforge enterprise list-tenants [--json]
```

---

### `enterprise encrypt-config`

Encrypt a configuration value using the enterprise encryption engine.

**Usage**

```bash
spanforge enterprise encrypt-config --value VALUE
```

---

### `enterprise health`

Run enterprise health probes (/healthz and /readyz).

**Usage**

```bash
spanforge enterprise health [--json]
```

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | All probes healthy. |
| `1` | One or more probes unhealthy. |

---

## `security`

Supply-chain security and OWASP audit commands (Phase 11).

### `security owasp`

Run an OWASP Top 10 for LLM Applications audit.

**Usage**

```bash
spanforge security owasp [--json]
```

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | Audit completed, results displayed. |
| `1` | Audit error. |

---

### `security threat-model`

Generate a STRIDE threat model for the current project.

**Usage**

```bash
spanforge security threat-model [--json]
```

---

### `security scan`

Run a full security scan (dependency vulnerabilities + static analysis).

**Usage**

```bash
spanforge security scan [--json]
```

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | No critical findings. |
| `1` | Critical or high findings detected. |

---

### `security audit-logs`

Check for secrets leaked in log files.

**Usage**

```bash
spanforge security audit-logs --path PATH [--json]
```

**Options**

| Option | Default | Description |
|--------|---------|-------------|
| `--path` | *(required)* | Path to log file or directory to scan. |

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | No secrets found in logs. |
| `1` | Secrets detected in log output. |

---

## `doctor`

Full environment diagnostic (Phase 12, DX-005).

**Usage**

```bash
spanforge doctor
```

Checks performed:

1. **Configuration validity** — Verifies `spanforge.toml` or default settings.
2. **Sandbox mode detection** — Warns if sandbox mode is active.
3. **Per-service health** — Pings each SDK client (`sf_pii`, `sf_audit`, `sf_observe`, `sf_cec`, `sf_gate`, `sf_identity`, `sf_secrets`, `sf_alert`, `sf_config`, `sf_trust`, `sf_security`).
4. **PII engine** — Confirms entity types are loaded.
5. **Connectivity** — Tests reachability of configured endpoints.

**Exit codes**

| Code | Meaning |
|------|---------|
| `0` | All checks passed. |
| `1` | One or more checks failed. |

**Example**

```bash
$ spanforge doctor
✔ Configuration valid (spanforge.toml)
⚠ Sandbox mode is ACTIVE — no production side effects
✔ sf_pii .............. healthy (local mode)
✔ sf_audit ............ healthy (local mode)
✔ sf_observe .......... healthy (local mode)
✔ sf_cec .............. healthy (local mode)
✔ sf_gate ............. healthy (local mode)
✔ sf_identity ......... healthy (local mode)
✔ sf_secrets .......... healthy (local mode)
✔ sf_alert ............ healthy (local mode)
✔ sf_config ........... healthy (local mode)
✔ sf_trust ............ healthy (local mode)
✔ sf_security ......... healthy (local mode)
✔ PII entity types loaded: 8
✔ Endpoint connectivity: ok

Result: 13 passed, 1 warning, 0 failed
```
