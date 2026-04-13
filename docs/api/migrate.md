# spanforge.migrate

Migration helpers for upgrading events from one schema version to the next,
plus the Phase 9 v2 migration roadmap with structured deprecation records.

See the [Migration Guide](../user_guide/migration.md) for background and strategy.

---

## `MigrationStats`

```python
@dataclass(frozen=True)
class MigrationStats:
    total: int
    migrated: int
    skipped: int
    errors: int
    warnings: list[str] = field(default_factory=list)
    output_path: str = ""
    transformed_fields: dict[str, int] = field(default_factory=dict)
```

Result of a bulk migration operation (returned by `migrate_file()`).

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `total` | `int` | Total events processed. |
| `migrated` | `int` | Events that were upgraded to a new schema version. |
| `skipped` | `int` | Events already at the target version (not modified). |
| `errors` | `int` | Events that could not be parsed or migrated. |
| `warnings` | `list[str]` | Non-fatal warnings encountered during migration. |
| `output_path` | `str` | Path where the migrated events were written. |
| `transformed_fields` | `dict[str, int]` | Mapping of field names to the count of events where that field was transformed (e.g. `"payload.model→model_id"`, `"checksum.md5→sha256"`, `"tags.value_coercion"`). |

---

## `SunsetPolicy`

```python
class SunsetPolicy(str, Enum):
    NEXT_MAJOR    = "next_major"
    NEXT_MINOR    = "next_minor"
    LONG_TERM     = "long_term"
    UNSCHEDULED   = "unscheduled"
```

Describes how aggressively a deprecated item will be removed.

| Value | Meaning |
|-------|---------|
| `NEXT_MAJOR` | Removed in the next major release. |
| `NEXT_MINOR` | Removed in the next minor release. |
| `LONG_TERM` | Kept for at least two more major releases. |
| `UNSCHEDULED` | No removal planned; deprecation is advisory only. |

---

## `DeprecationRecord`

```python
@dataclass(frozen=True)
class DeprecationRecord:
    event_type: str
    since: str
    sunset: str
    sunset_policy: SunsetPolicy = SunsetPolicy.NEXT_MAJOR
    replacement: str | None = None
    migration_notes: str | None = None
    field_renames: Dict[str, str] = field(default_factory=dict)
```

Structured deprecation metadata for a single event type on the migration
roadmap.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `event_type` | `str` | The deprecated event type. |
| `since` | `str` | Version in which the type was marked deprecated. |
| `sunset` | `str` | Target version for removal. |
| `sunset_policy` | `SunsetPolicy` | `SunsetPolicy.NEXT_MAJOR` | Removal urgency. |
| `replacement` | `str \| None` | `None` | Recommended replacement event type. |
| `migration_notes` | `str \| None` | `None` | Free-form migration guidance. |
| `field_renames` | `Dict[str, str]` | `{}` | Payload field renames: `{old_name: new_name}`. |

### Methods

#### `summary() -> str`

Return a single-line summary of the deprecation record.

**Example:**

```
llm.eval.regression → llm.eval.regression_failed (since 1.0.0, sunset 2.0.0, NEXT_MAJOR)
```

---

## Module-level functions

### `v2_migration_roadmap() -> List[DeprecationRecord]`

Return the complete list of event types deprecated in v1.0.0 and scheduled for
removal in v2.0.0, sorted by `event_type`.

Each entry documents the recommended replacement, any relevant field renames,
and the `SunsetPolicy` governing its removal timeline.

**Returns:** `List[DeprecationRecord]` — 9 entries covering the `llm.trace.*`,
`llm.eval.*`, `llm.guard.*`, `llm.cost.*`, and `llm.cache.*` namespaces.

**Example:**

```python
from spanforge.migrate import v2_migration_roadmap

for record in v2_migration_roadmap():
    print(record.summary())
```

---

### `v1_to_v2(event) -> Event | dict`

```python
def v1_to_v2(event: Event | dict) -> Event | dict
```

Migrate a single event from schema version 1.0 to 2.0.

Accepts either an `Event` instance or a plain `dict` (as loaded from JSONL).
Returns the same type as the input. **Idempotent** — events already at version
`"2.0"` are returned unchanged.

**Changes applied:**
- `schema_version` set to `"2.0"`.
- Missing `org_id` / `team_id` set to `None`.
- Payload key `model` normalised to `model_id` if present.
- `tags` initialised to `{}` if missing; all values coerced to strings.
- `checksum` re-hashed from md5 to sha256 if applicable.

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `event` | `Event \| dict` | A v1.0 event (Event instance or dict from JSONL). |

**Returns:** The migrated event (same type as input).

**Raises:** `TypeError` — if the input is neither an `Event` nor a `dict`.

**Example:**

```python
from spanforge.migrate import v1_to_v2

# Migrate an Event
v2_event = v1_to_v2(v1_event)
assert v2_event.schema_version == "2.0"

# Migrate a dict from raw JSONL
v2_dict = v1_to_v2({"schema_version": "1.0", "event_type": "llm.trace.span.completed", ...})
assert v2_dict["schema_version"] == "2.0"
```

---

### `migrate_file(input_path, *, output=None, org_secret=None, target_version="2.0", dry_run=False) -> MigrationStats`

```python
def migrate_file(
    input_path: str | Path,
    *,
    output: str | Path | None = None,
    org_secret: str | None = None,
    target_version: str = "2.0",
    dry_run: bool = False,
) -> MigrationStats
```

Migrate all events in a JSONL file from v1 to v2.

Reads line-by-line, applies `v1_to_v2()` to each JSON object, and writes the
result to *output* (defaults to `<input>_v2.jsonl`).

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `input_path` | `str \| Path` | Path to the source JSONL file. |
| `output` | `str \| Path \| None` | Output file path. Default: `<stem>_v2.jsonl`. |
| `org_secret` | `str \| None` | When provided, re-signs the entire migrated chain using HMAC. |
| `target_version` | `str` | Target schema version (default `"2.0"`). |
| `dry_run` | `bool` | When `True`, report stats without writing output. |

**Returns:** `MigrationStats` — summary of the operation.

**Example:**

```python
from spanforge.migrate import migrate_file

# Basic migration
stats = migrate_file("audit.jsonl")
print(f"Migrated {stats.migrated}/{stats.total} events → {stats.output_path}")

# Re-sign with a new key
stats = migrate_file("audit.jsonl", output="audit_v2.jsonl", org_secret="my-key")

# Preview without writing
stats = migrate_file("audit.jsonl", dry_run=True)
print(f"Would migrate {stats.migrated} events, skip {stats.skipped}")
print(f"Transformed fields: {stats.transformed_fields}")
```
