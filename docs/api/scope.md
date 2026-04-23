# spanforge.sdk.scope

Runtime scope enforcement for agent capabilities and resource access.

## `SFScopeClient`

```python
from spanforge.sdk import sf_scope
```

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

Checks whether an agent may perform a resource action.

### `evaluate_with_policy(...)`

Runs the scope check and attaches the active policy decision metadata.

### `list_for_trace(trace_id)`

Returns all scope decisions recorded for a trace.

## Outcomes

The emitted scope decision outcome is one of:

- `allow`
- `block`
- `redact`
- `human_review`
- `escalate`

Signed records are written under:

`spanforge.scope.v1`
