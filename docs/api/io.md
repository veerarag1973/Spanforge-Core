# spanforge.io — Synchronous JSONL utilities

> **Module:** `spanforge.io`  
> **Added in:** 2.0.3

`spanforge.io` provides reliable, synchronous JSONL read/write helpers.
They are a simpler, dependency-free alternative to the async `JSONLExporter`
and `EventStream.from_file()` pattern — ideal for scripts, tests, and
offline pipelines.

---

## Quick example

```python
from spanforge.io import write_events, read_events

# Write eval results as event envelopes
write_events(
    [{"case_id": "tc-001", "score": 0.95}, {"case_id": "tc-002", "score": 0.72}],
    "results.jsonl",
    event_type="llm.eval.done",
    source="my-eval-runner@1.0",
)

# Read them back, filtered by event type
payloads = read_events("results.jsonl", event_type="llm.eval.done")
# → [{"case_id": "tc-001", "score": 0.95}, ...]
```

---

## API

### `write_jsonl()`

```python
def write_jsonl(
    records: Iterable[dict],
    path: str | Path,
    *,
    mode: str = "w",
) -> int: ...
```

Serialise each record as a JSON line and write to *path*.  Parent directories
are created automatically.

| Parameter | Description |
|-----------|-------------|
| `records` | Any iterable of `dict` objects (including generators). |
| `path` | Destination file path. |
| `mode` | `"w"` (overwrite, default) or `"a"` (append). |

**Returns:** Number of records written.

---

### `read_jsonl()`

```python
def read_jsonl(
    path: str | Path,
    *,
    event_type: str | None = None,
    skip_errors: bool = True,
) -> list[dict]: ...
```

Read a JSONL file and return a list of `dict` records.

| Parameter | Description |
|-----------|-------------|
| `path` | Source file path. Raises `FileNotFoundError` if absent. |
| `event_type` | If set, only records with `"event_type" == event_type` are returned. |
| `skip_errors` | When `True` (default), malformed lines are silently skipped. Set to `False` to raise `json.JSONDecodeError` on the first bad line. |

Non-`dict` JSON values (arrays, scalars) are always skipped.

---

### `append_jsonl()`

```python
def append_jsonl(record: dict, path: str | Path) -> None: ...
```

Append a single record to *path*, creating the file if it does not exist.
Equivalent to `write_jsonl([record], path, mode="a")`.

---

### `write_events()`

```python
def write_events(
    payloads: Iterable[dict],
    path: str | Path,
    *,
    event_type: str,
    source: str = "spanforge",
    mode: str = "w",
) -> int: ...
```

Wrap each payload in a spanforge event envelope and write to *path*.

Envelope format:

```json
{"event_type": "<event_type>", "source": "<source>", "payload": { ... }}
```

---

### `read_events()`

```python
def read_events(
    path: str | Path,
    *,
    event_type: str,
) -> list[dict]: ...
```

Read event envelopes from *path* and return the unwrapped `payload` objects
where `"event_type"` matches.  Lines that do not carry a `"payload"` field
are silently skipped.
