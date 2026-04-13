# model_registry — Model Lifecycle Events

> **Auto-documented module:** `spanforge.model_registry`

The `model_registry.*` namespace tracks model lifecycle governance — registration,
deprecation, and retirement. Three canonical event types:

- `model_registry.registered`
- `model_registry.deprecated`
- `model_registry.retired`

## Regulatory mapping

| Framework | Clause | Role of `model_registry.*` events |
|-----------|--------|-----------------------------------|
| **SOC 2** | CC6.1 | Logical access controls — model governance |
| **NIST AI RMF** | MAP 1.1 | Risk identification — model inventory and risk-tier tracking |

## Payload fields

`ModelRegistryEntry` is emitted as the event payload.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `model_id` | `str` | ✓ | Unique model identifier |
| `name` | `str` | ✓ | Human-readable model name |
| `version` | `str` | ✓ | Model version string |
| `risk_tier` | `str` | ✓ | One of `"low"`, `"medium"`, `"high"`, `"critical"` |
| `owner` | `str` | ✓ | Team or individual responsible |
| `purpose` | `str` | ✓ | Intended use of the model |
| `status` | `str` | — | One of `"active"`, `"deprecated"`, `"retired"`. Default `"active"` |
| `deployment_date` | `str \| None` | — | ISO 8601 deployment timestamp |
| `decommission_date` | `str \| None` | — | ISO 8601 decommission timestamp (set on retire) |
| `metadata` | `dict` | — | Arbitrary metadata (e.g. `deprecation_reason`) |

## Example

```python
from spanforge.model_registry import ModelRegistry

registry = ModelRegistry()

# Register
entry = registry.register(
    model_id="gpt-4o-2024-05",
    name="GPT-4o",
    version="2024-05",
    risk_tier="high",
    owner="ml-platform",
    purpose="customer support agent",
)

# Deprecate
registry.deprecate("gpt-4o-2024-05", reason="Replaced by gpt-4o-2024-08")

# Retire
registry.retire("gpt-4o-2024-05")
```

## Integration with compliance attestations

The `ComplianceMappingEngine` automatically queries the model registry when
generating evidence packages. Attestations include:

- `model_owner` — who owns the model
- `model_risk_tier` — `"low"` / `"medium"` / `"high"` / `"critical"`
- `model_status` — `"active"` / `"deprecated"` / `"retired"`
- `model_warnings` — e.g. `["model 'gpt-3.5-turbo' is deprecated"]`

## Persistence

```python
registry.save("models.json")   # persist to disk
registry.load("models.json")   # reload from disk
```

## Convenience functions

```python
from spanforge.model_registry import register_model, deprecate_model, retire_model

register_model("gpt-4o", "GPT-4o", "2024-05", "high", "ml-platform", "chat agent")
deprecate_model("gpt-4o", reason="Successor available")
retire_model("gpt-4o")
```
