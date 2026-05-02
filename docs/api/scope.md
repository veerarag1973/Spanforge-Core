# spanforge.sdk.scope

Runtime scope enforcement for agent capabilities and resource access.

## `SFScopeClient`

```python
from spanforge.sdk import sf_scope
```

## `ACTION_CATEGORIES`

```python
from spanforge.sdk.scope import ACTION_CATEGORIES
```

Module-level dict mapping five canonical category names to frozensets of action strings:

| Category | Actions |
|----------|---------|
| `read` | `read`, `list`, `get`, `describe`, `view`, `query`, `fetch`, `download` |
| `write` | `write`, `create`, `update`, `delete`, `patch`, `put`, `append`, `insert`, `remove` |
| `execute` | `execute`, `run`, `invoke`, `trigger`, `call`, `dispatch`, `submit` |
| `admin` | `admin`, `configure`, `deploy`, `restart`, `scale`, `shutdown`, `grant`, `revoke`, `manage` |
| `stream` | `stream`, `subscribe`, `publish`, `consume`, `emit`, `broadcast` |

Use `resolve_action_category(action)` to look up a category by action name.

## Circuit Breaker

`SFScopeClient.__init__()` accepts two new parameters (1.0.1):

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `cb_threshold` | `int` | `5` | Number of consecutive emit failures before the circuit opens. |
| `cb_reset_seconds` | `float` | `30.0` | Seconds before the circuit automatically resets to closed. |

When the circuit is open, `evaluate()` returns `allowed=False` with `outcome="block"` and `reason="circuit breaker is open; failing secure"` immediately — no manifest lookup, no network call.

## Workflow

1. Register an agent manifest with allowed capabilities and resource actions.
2. Evaluate requested runtime actions.
3. Emit signed scope decision records.

### `register_agent(...)`

```python
sf_scope.register_agent(
    agent_id="claims-agent",
    capabilities=["claim.read", "decision.write"],
    resource_actions={"claims": ["read"], "decisions": ["write"]},
)
```

### `evaluate(...)`

Checks whether an agent may perform a resource action. Returns a fail-secure `block` decision immediately when the circuit breaker is open.

### `evaluate_with_policy(...)`

Runs the scope check and attaches the active policy decision metadata.

### `resolve_action_category(action: str) -> str | None`

Static method. Returns the category name (`"read"`, `"write"`, `"execute"`, `"admin"`, or `"stream"`) for a given action string, or `None` if the action is not in any category.

```python
from spanforge.sdk.scope import SFScopeClient

SFScopeClient.resolve_action_category("read")    # "read"
SFScopeClient.resolve_action_category("deploy")  # "admin"
SFScopeClient.resolve_action_category("unknown") # None
```

### `list_for_trace(trace_id)`

Returns all scope decisions recorded for a trace.

## Outcomes

The emitted scope decision outcome is one of:

- `allow`
- `block` (also returned by circuit-breaker fast path)
- `redact`
- `human_review`
- `escalate`

Signed records are written under:

`spanforge.scope.v1`
