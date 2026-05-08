# spanforge.governance

Policy-based event governance — block prohibited event types, warn on deprecated
usage, and enforce custom domain rules.

See the [Governance & Consumer Registry](../user_guide/governance.md) user guide
for usage patterns.

---

## `EventGovernancePolicy`

```python
@dataclass
class EventGovernancePolicy:
    blocked_types: Set[str] = field(default_factory=set)
    warn_deprecated: Set[str] = field(default_factory=set)
    custom_rules: List[Callable[[Event], str | None]] = field(default_factory=list)
    strict_unknown: bool = False
```

A mutable policy object that describes which event types are blocked, which
trigger deprecation warnings, and any custom rule callbacks.

**Attributes:**

| Attribute | Type | Default | Description |
|-----------|------|---------|-------------|
| `blocked_types` | `Set[str]` | `set()` | Event type strings that are unconditionally rejected. |
| `warn_deprecated` | `Set[str]` | `set()` | Event type strings that emit a `GovernanceWarning` when seen. |
| `custom_rules` | `List[Callable[[Event], str \| None]]` | `[]` | Callables `rule(event) -> str | None` — return a non-empty string to block the event with that reason, or `None` to allow. |
| `strict_unknown` | `bool` | `False` | When `True`, any event whose type is not registered with `EventType` is blocked. |

**Example:**

```python
from spanforge.governance import EventGovernancePolicy

policy = EventGovernancePolicy(
    blocked_types={"llm.internal.debug"},
    warn_deprecated={"llm.legacy.trace"},
    strict_unknown=True,
)
```

### Methods

#### `check_event(event: Event) -> None`

Evaluate all rules in this policy against `event`.

The evaluation order is:

1. **blocked_types** — raises `GovernanceViolationError` immediately.
2. **warn_deprecated** — issues `GovernanceWarning` (a `UserWarning` subclass).
3. **custom_rules** — calls each rule; the first non-empty string raises `GovernanceViolationError`.

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `event` | `Event` | The event to evaluate. |

**Raises:**
- `GovernanceViolationError` — if the event is blocked by a type rule or a custom rule.
- `GovernanceWarning` *(warning, not exception)* — if the event type is in `warn_deprecated`.

---

## `GovernanceViolationError`

```python
class GovernanceViolationError(Exception):
    event_type: str
    reason: str
```

Raised when an event is blocked by a governance policy.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `event_type` | `str` | The `event_type` string of the blocked event. |
| `reason` | `str` | Human-readable description of why the event was blocked. |

---

## `GovernanceWarning`

```python
class GovernanceWarning(UserWarning)
```

Issued via `warnings.warn()` when an event type appears in
`EventGovernancePolicy.warn_deprecated`.

> **Note:** In pytest with `filterwarnings = ["error"]`, this warning is
> automatically promoted to an exception. Use
> `pytest.warns(GovernanceWarning)` to assert on it in tests.

---

## Module-level helpers

A **global policy singleton** is provided so most callers do not need to manage
`EventGovernancePolicy` instances directly.

### `get_global_policy() -> EventGovernancePolicy`

Return the global `EventGovernancePolicy` singleton.

The default policy has no blocked types, no deprecated types, no custom rules,
and `strict_unknown=False`.

---

### `set_global_policy(policy: Optional[EventGovernancePolicy]) -> None`

Replace the global policy. Pass `None` to reset to the default.

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `policy` | `EventGovernancePolicy \| None` | New policy, or `None` to reset. |

---

### `check_event(event: Event) -> None`

Apply the global policy to `event`.

Equivalent to `get_global_policy().check_event(event)`.

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `event` | `Event` | The event to check against the global policy. |

**Raises:** `GovernanceViolationError` | `GovernanceWarning`

**Example:**

```python
from spanforge.governance import (
    EventGovernancePolicy, GovernanceViolationError,
    set_global_policy, check_event,
)

policy = EventGovernancePolicy(blocked_types={"llm.internal.debug"})
set_global_policy(policy)

try:
    check_event(my_event)
except GovernanceViolationError as exc:
    print(f"Blocked: {exc.event_type} — {exc.reason}")
```

---

## `@governed` — sf_explain control loop decorator *(CARD 1B-1)*

```python
import spanforge

@spanforge.governed
def my_agent_fn(prompt: str) -> str: ...
```

Wraps a callable in the `sf_explain` control loop. After the wrapped function returns, its response is passed to `sf_explain.explain()` so that every model response is automatically explained, EU AI Act clauses are mapped, and an HMAC-signed `ExplainRecord` is appended to `sf_audit`.

The decorator **never blocks or raises** on explain/audit failures — it logs a warning and returns the original response unchanged.

### Signatures

```python
# Form 1 — bare decorator (no parentheses)
@spanforge.governed
def generate(prompt: str) -> str:
    return llm.invoke(prompt)

# Form 2 — parameterised decorator
@spanforge.governed(agent_id="billing-agent", confidence_threshold=0.8)
def classify(text: str) -> str:
    return classifier.predict(text)
```

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `fn` | `Callable \| None` | `None` | The callable to wrap (populated automatically when used without parentheses). |
| `agent_id` | `str` | `"governed"` | Agent identifier written into the `ExplainRecord`. |
| `confidence_threshold` | `float` | `0.7` | Confidence score below which EU AI Act Article 14 (human oversight) is flagged as unsatisfied. |

### Behaviour

1. Calls the wrapped function with its original `*args` and `**kwargs`.
2. Passes the return value to `sf_explain.explain(result, context)` where `context` is built from `agent_id`, `kwargs.get("model_output_type")`, and `kwargs.get("confidence_score")`.
3. If `sf_explain.explain()` raises for any reason, logs a `WARNING` and continues — the original return value is **always** returned to the caller.
4. Preserves the original function's `__name__`, `__doc__`, and `__wrapped__` via `functools.wraps`.

