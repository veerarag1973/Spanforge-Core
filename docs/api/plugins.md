# spanforge.plugins — Entry-point plugin discovery

> **Module:** `spanforge.plugins`  
> **Added in:** 2.0.3

`spanforge.plugins` provides a single `discover()` helper that loads
third-party plugins registered via Python packaging entry-points.  It
handles the API split across Python 3.9, 3.10, and 3.12+ transparently
and silently skips broken plugins.

---

## Quick example

```python
from spanforge.plugins import discover

# Load all scorers registered under the "spanforge.scorers" group
scorers = discover("spanforge.scorers")

for scorer_cls in scorers:
    scorer = scorer_cls()
    print(scorer.name)
```

---

## API

### `discover()`

```python
def discover(group: str) -> list[Any]: ...
```

Return a list of objects (classes, functions, or instances) loaded from all
entry points registered under *group*.

| Parameter | Description |
|-----------|-------------|
| `group` | The entry-point group name, e.g. `"spanforge.scorers"`. |

**Returns:** A list of loaded objects.  Broken entry points (those whose
`ep.load()` raises) are silently omitted.  An empty list is returned if the
group has no registered entry points or if `importlib.metadata` is
unavailable.

---

## Registering a plugin

Add an entry point to your package's `pyproject.toml`:

```toml
[project.entry-points."spanforge.scorers"]
my_scorer = "my_package.scorers:MyScorer"
```

After `pip install`-ing your package, `discover("spanforge.scorers")` will
include `MyScorer` in the returned list.

---

## Python version compatibility

| Python | `entry_points()` API used |
|--------|--------------------------|
| 3.12+ | `entry_points(group=group)` |
| 3.10–3.11 | `entry_points().select(group=group)` |
| 3.9 | `entry_points().get(group, [])` (dict style) |
