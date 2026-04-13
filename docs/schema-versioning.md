# Schema Versioning Guide

spanforge events carry a `schema_version` field (semver) that governs backward and forward compatibility.

---

## Version field

Every event envelope includes:

```json
{
  "schema_version": "2.0",
  ...
}
```

The current stable schema version is **2.0**.

---

## Compatibility rules

| Change type | Version bump | Producer | Consumer |
|---|---|---|---|
| Add optional field to envelope | MINOR | MAY add | MUST ignore unknown fields |
| Add optional field to namespace payload | MINOR | MAY add | MUST ignore unknown fields |
| Add new namespace | MINOR | MAY emit | MUST accept (payload opaque) |
| Rename or remove field | MAJOR | MUST bump | MUST handle both until old major is sunset |
| Change field type | MAJOR | MUST bump | — |
| Add required field | MAJOR | MUST bump | — |

**Rule of thumb**: Consumers must be written to tolerate new fields (forward-compatible reads). Producers must never remove or rename fields within the same major version.

---

## Migration between major versions

### v1 → v2

The v2 schema has shipped (`SCHEMA_VERSION = "2.0"`):
1. Both `schema_version: "1.x"` and `schema_version: "2.x"` events will be valid during the transition window (minimum 6 months)
2. The `spanforge migrate` CLI command will convert v1 JSONL archives to v2
3. A `compat` shim module will be provided in the SDK

---

## Checking schema version at runtime

```python
import spanforge

event = spanforge.Event.from_dict(raw_event_dict)

major, minor, patch = map(int, event.schema_version.split("."))
if major > spanforge.SCHEMA_VERSION_MAJOR:
    raise ValueError(f"Unsupported schema major version: {major}")
```

Or use the CLI:

```sh
spanforge check-compat events.json
```

---

## Namespace versioning

Namespaces themselves are versioned independently via the RFC amendment process (see [RFC-0001](rfc/rfc-0001.md#backward-compatibility)):

- New namespaces are added in MINOR schema bumps
- Existing namespace payload shapes only change in MAJOR bumps

---

## Pinning to a schema version

If your consumer must only process events from a specific schema version range:

```python
import spanforge
from spanforge import Event

def process(raw: dict) -> None:
    event = Event.from_dict(raw)
    if not event.schema_version.startswith("1."):
        raise ValueError("Only schema v1.x supported")
    # ... process
```

---

## See also

- [RFC-0001](rfc/rfc-0001.md) — full schema specification
- [CLI reference](cli.md) — `check-compat`, `validate`, `migration-roadmap`
- [CHANGELOG](changelog.md) — version history
