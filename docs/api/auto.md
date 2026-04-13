# spanforge.auto

Integration auto-discovery. Detects and patches every installed LLM
integration in one call — no per-library import required.

---

## Overview

`spanforge.auto` inspects `sys.modules` and the installed package set to find
all LLM client libraries supported by spanforge integrations, then calls
`patch()` on each one that is present.

> **Important:** `import spanforge.auto` alone does **not** patch anything.
> You must call `spanforge.auto.setup()` explicitly.

---

## `setup()`

```python
def setup(*, verbose: bool = False) -> set[str]:
```

Auto-patch every installed and importable LLM integration.

Currently supports: `openai`, `anthropic`, `groq`, `ollama`, `together`.

Returns the set of integration names that were successfully patched.

```python
import spanforge
import spanforge.auto

spanforge.configure(exporter="console", service_name="my-agent")
patched = spanforge.auto.setup()
# patched == {"openai", "anthropic"}  (whichever are installed)
```

**Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `verbose` | `bool` | `False` | If `True`, logs each patched integration to `logging.getLogger("spanforge.auto")` at `INFO` level. |

**Returns:** `set[str]` — names of successfully patched integrations.

---

## `teardown()`

```python
def teardown(*, verbose: bool = False) -> set[str]:
```

Unpatch all integrations that were patched by `setup()`. Safe to call even
if `setup()` was not called.

Returns the set of integration names that were successfully unpatched.

```python
spanforge.auto.teardown()
# All patched integrations restored to their original state
```

**Parameters**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `verbose` | `bool` | `False` | If `True`, logs each unpatched integration at `INFO` level. |

**Returns:** `set[str]` — names of successfully unpatched integrations.

---

## Typical usage pattern

```python
import spanforge
import spanforge.auto

# --- application startup ---
spanforge.configure(
    exporter="console",
    service_name="my-agent",
    schema_version="2.0",
)
spanforge.auto.setup(verbose=True)

# All LLM calls from this point forward are automatically instrumented

# --- application shutdown (optional) ---
spanforge.auto.teardown()
```

### Test isolation

```python
import spanforge.auto

def setup_method(self):
    spanforge.auto.setup()

def teardown_method(self):
    spanforge.auto.teardown()
```

---

## Re-exports

```python
import spanforge.auto

spanforge.auto.setup
spanforge.auto.teardown
```
