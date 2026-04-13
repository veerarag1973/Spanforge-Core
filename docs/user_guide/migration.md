# Migration Guide

`spanforge.migrate` provides helpers for upgrading stored event payloads
to use new namespace payload schemas, plus the Phase 9 v2 migration roadmap
so you can prepare for breaking changes before v2.0 ships.

## MigrationStats

Bulk migration operations return a `MigrationStats` dataclass:

```python
from spanforge.migrate import MigrationStats

stats: MigrationStats   # returned by migrate_file()
stats.total              # total events processed
stats.migrated           # events upgraded to target version
stats.skipped            # events already at target version
stats.errors             # events that failed to parse/migrate
stats.warnings           # list of non-fatal warning strings
stats.output_path        # path to the output file
stats.transformed_fields # {"payload.model→model_id": 5, "checksum.md5→sha256": 2, ...}
```

## Migrating v1.0 → v2.0

`v1_to_v2()` converts a single event from schema version 1.0 to 2.0.
It accepts both `Event` instances and plain `dict` objects (from JSONL):

```python
from spanforge.migrate import v1_to_v2

# Migrate an Event instance
v2_event = v1_to_v2(v1_event)
assert v2_event.schema_version == "2.0"

# Migrate a raw dict from JSONL
v2_dict = v1_to_v2({"schema_version": "1.0", "event_type": "llm.trace.span.completed", ...})
assert v2_dict["schema_version"] == "2.0"
```

**Changes applied:**
- `schema_version` set to `"2.0"`
- Missing `org_id` / `team_id` set to `None`
- Payload `model` normalised to `model_id`
- `tags` coerced: all values become strings, initialised to `{}` if missing
- `checksum` re-hashed from md5 to sha256 if applicable

The function is **idempotent** — events whose `schema_version` is already
`"2.0"` are returned unchanged.

## Bulk migration from JSONL

Use `migrate_file()` for bulk JSONL-to-JSONL migration:

```python
from spanforge.migrate import migrate_file

# Basic migration
stats = migrate_file("audit.jsonl")
print(f"Migrated {stats.migrated}/{stats.total} events → {stats.output_path}")
print(f"Skipped: {stats.skipped}, Errors: {stats.errors}")
print(f"Transformed fields: {stats.transformed_fields}")
```

### Re-signing the migrated chain

Pass `org_secret` to re-sign the entire output chain with HMAC:

```python
stats = migrate_file("audit.jsonl", output="audit_v2.jsonl", org_secret="my-signing-key")
```

### Dry run (preview without writing)

```python
stats = migrate_file("audit.jsonl", dry_run=True)
print(f"Would migrate {stats.migrated} events, skip {stats.skipped}")
```

### CLI migration

```bash
# Basic migration
spanforge migrate audit.jsonl

# With signing and explicit output
spanforge migrate audit.jsonl --sign --target-version 2.0 -o audit_v2.jsonl

# Preview only
spanforge migrate audit.jsonl --dry-run
```

## v2 Migration Roadmap

Phase 9 ships a structured roadmap of every event type that will change
in v2.0. Use `v2_migration_roadmap()` to audit your codebase:

```python
from spanforge.migrate import v2_migration_roadmap

for record in v2_migration_roadmap():
    print(record.summary())
```

Example output:

```
llm.cache.evicted → llm.cache.entry_evicted (since 1.0.0, sunset 2.0.0, NEXT_MAJOR)
llm.cost.estimate → llm.cost.estimated (since 1.0.0, sunset 2.0.0, NEXT_MAJOR)
llm.eval.regression → llm.eval.regression_failed (since 1.0.0, sunset 2.0.0, NEXT_MAJOR)
...
```

Each `DeprecationRecord` provides:

| Field | Description |
|-------|-------------|
| `event_type` | The deprecated event type string |
| `since` | Version deprecated (`"1.0.0"`) |
| `sunset` | Planned removal version (`"2.0.0"`) |
| `sunset_policy` | `SunsetPolicy.NEXT_MAJOR` for all roadmap entries |
| `replacement` | Recommended new event type |
| `migration_notes` | Guidance text |
| `field_renames` | `{old_field: new_field}` dict for payload field renames |

### CLI roadmap view

```bash
# Human-readable table
spanforge migration-roadmap

# JSON for tooling
spanforge migration-roadmap --json
```

## Sunset policy

| Policy | Meaning |
|--------|---------|
| `NEXT_MAJOR` | Removed in v2.0.0 |
| `NEXT_MINOR` | Removed in the next minor release |
| `LONG_TERM` | Removed in v3.0.0 or later |
| `UNSCHEDULED` | Advisory deprecation; no removal planned |

All Phase 9 roadmap entries use `NEXT_MAJOR` — they will be removed when v2.0
ships.

## Deprecation warnings

At import time, `spanforge.deprecations` auto-populates the global
`DeprecationRegistry` with every entry from `v2_migration_roadmap()`. Callers
can surface these warnings at runtime:

```python
from spanforge.deprecations import warn_if_deprecated

# Inside event processing loops, or at schema validation time:
warn_if_deprecated(event.event_type)
# → emits DeprecationWarning if this type is on the roadmap
```

### CLI deprecation list

```bash
spanforge list-deprecated
```

## Preparing for v2.0

1. Run `spanforge migration-roadmap` to see the full list.
2. Search your code for deprecated event type strings.
3. Replace with the recommended `replacement` type from each record.
4. Apply any `field_renames` to affected payload construction sites.
5. Update consumer registry entries with `schema_version="2.0"` once v2.0 ships.

```python
@dataclass
class MigrationResult:
    migrated: list[Event]   # successfully transformed events
    skipped:  list[Event]   # events that needed no change
    errors:   list[dict]       # {"event_id": str, "error": str}

@property
def success(self) -> bool:
    return len(self.errors) == 0
```

## Migrating v1 → v2 (scaffold)

The `v1_to_v2` scaffold converts events recorded with the `llm.trace.*`
payload from the frozen v1.0 schema to any updated v2 layout that ships in
Phase 9:

```python
from spanforge.migrate import v1_to_v2

result = v1_to_v2(events)

if result.success:
    save(result.migrated)
else:
    for err in result.errors:
        print(f"{err['event_id']}: {err['error']}")
```

The function is idempotent — events whose `schema_version` is already
`"2.0"` are placed in `result.skipped` unchanged.

## Batch migration from JSONL

Read a JSONL archive, migrate, and write the output:

```python
import json
from spanforge.event import Event
from spanforge.migrate import v1_to_v2

events = [Event(**json.loads(line)) for line in open("archive.jsonl")]
result = v1_to_v2(events)

with open("archive_v2.jsonl", "w") as f:
    for event in result.migrated + result.skipped:
        f.write(json.dumps(event.to_dict()) + "\n")

print(f"Migrated: {len(result.migrated)}")
print(f"Skipped:  {len(result.skipped)}")
print(f"Errors:   {len(result.errors)}")
```

## Phase 9 roadmap

Phase 9 will ship breaking-change namespace payload schemas alongside a
`migrate` sub-command for the CLI:

```bash
spanforge migrate --from v1 --to v2 archive.jsonl --out archive_v2.jsonl
```

Until Phase 9 ships, the `v1_to_v2` Python API is the primary migration path.
The function signature and `MigrationResult` dataclass fields are considered
**stable** and will not change in Phase 9.
