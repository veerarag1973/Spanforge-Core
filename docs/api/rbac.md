# spanforge.sdk.rbac

Runtime RBAC authorization for sensitive actions.

## `SFRBACClient`

```python
from spanforge.sdk import sf_rbac
```

## `STANDARD_ROLE_MATRIX`

```python
from spanforge.sdk.rbac import STANDARD_ROLE_MATRIX
```

Ten canonical actor configurations covering common deployment patterns:

| Key | Roles | Purpose |
|-----|-------|---------|
| `viewer` | `["viewer"]` | Read-only human or service identity |
| `editor` | `["viewer", "editor"]` | Read + write access |
| `admin` | `["viewer", "editor", "admin"]` | Full tenant control |
| `operator` | `["viewer", "operator"]` | Operational tasks without admin |
| `auditor` | `["viewer", "auditor"]` | Compliance / audit access |
| `developer` | `["viewer", "editor", "developer"]` | Developer access |
| `deployer` | `["viewer", "deployer"]` | Deployment pipeline identity |
| `reviewer` | `["viewer", "reviewer"]` | Approval / review identity |
| `service_account` | `["service_account"]` | Machine identity / CI token |
| `superadmin` | `["viewer", "editor", "admin", "superadmin"]` | Break-glass super-admin |

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

### `register_actor_from_yaml(yaml_str: str) -> RBACManifest`

Parse a YAML actor manifest string and register the actor in one step.

```python
manifest = sf_rbac.register_actor_from_yaml("""
actor_id: alice
roles:
  - admin
  - viewer
resource_roles:
  claims:
    - editor
""")
```

Requires `actor_id`. Validates that `roles` is a list when PyYAML is available; falls back to a minimal stdlib parser for flat manifests.

### `register_actor_from_jwt(token, *, verify=False, secret=None) -> RBACManifest`

Decode the JWT payload segment (base64url), extract `sub` → `actor_id`, `roles`, `resource_roles`, and remaining claims → `metadata`.

```python
manifest = sf_rbac.register_actor_from_jwt(
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJib3QtMSIsInJvbGVzIjpbInNlcnZpY2VfYWNjb3VudCJdfQ.sig"
)
```

- Raises `ValueError` if the token does not have exactly three dot-separated parts.
- Raises `ValueError` if `sub` is absent from the payload.
- When `verify=True`, supply a `secret` and the HMAC-SHA256 signature is verified before registration.

### `authorize(...)`

Checks whether the actor has the required roles for the resource action.

### `authorize_with_policy(...)`

Runs the authorization check and attaches the active runtime-policy metadata.

### `list_for_trace(trace_id)`

Returns all RBAC decisions for a trace.

## Signed Records

RBAC decisions are emitted to `sf_audit` under:

`spanforge.rbac.v1`
