# spanforge.sdk.rbac

Runtime RBAC authorization for sensitive actions.

## `SFRBACClient`

```python
from spanforge.sdk import sf_rbac
```

## Workflow

1. Register an actor role manifest.
2. Evaluate access to a resource action.
3. Emit signed authorization evidence.

### `register_actor(...)`

```python
sf_rbac.register_actor(
    actor_id="case-worker-7",
    roles=["claims_reviewer"],
    resource_roles={"claims": ["claims_writer"]},
)
```

### `authorize(...)`

Checks whether the actor has the required roles for the resource action.

### `authorize_with_policy(...)`

Runs the authorization check and attaches the active runtime-policy metadata.

### `list_for_trace(trace_id)`

Returns all RBAC decisions for a trace.

## Signed Records

RBAC decisions are emitted to `sf_audit` under:

`spanforge.rbac.v1`
