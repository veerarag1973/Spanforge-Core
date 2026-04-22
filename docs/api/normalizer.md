# spanforge.normalizer

Provider normalizer protocol and generic fallback implementation.

This module defines the structural interface that provider-specific integration
modules must satisfy, plus a zero-dependency `GenericNormalizer` that handles
the most common LLM response shapes without requiring any vendored SDK.

See the [Integrations guide](../integrations/) for per-provider usage.

---

## Overview

```
raw LLM response
       │
       ▼
ProviderNormalizer.normalize_response()
       │
       ▼
(TokenUsage, ModelInfo, CostBreakdown | None)
```

---

## `ProviderNormalizer`

```python
@runtime_checkable
class ProviderNormalizer(Protocol):
    def normalize_response(
        self,
        response: object,
    ) -> tuple[TokenUsage, ModelInfo, CostBreakdown | None]: ...
```

Structural `Protocol` (RFC-0001 §10.4) for provider-specific response
normalizers.  Any object that implements `normalize_response()` satisfies this
interface — no base class is required.

Because the class is decorated with `@runtime_checkable`, you can use
`isinstance(obj, ProviderNormalizer)` at runtime:

```python
from spanforge import ProviderNormalizer, GenericNormalizer

assert isinstance(GenericNormalizer(), ProviderNormalizer)  # True
```

### `normalize_response(response: object) -> tuple[TokenUsage, ModelInfo, CostBreakdown | None]`

Extract typed spanforge value objects from a raw provider response.

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `response` | `object` | Raw response from a provider SDK call — may be a dataclass, SDK object, or plain `dict`. |

**Returns:** `tuple[TokenUsage, ModelInfo, CostBreakdown | None]`

A 3-tuple of typed value objects:

| Position | Type | Notes |
|----------|------|-------|
| 0 | `TokenUsage` | Token counts (input, output, total; optional cached/reasoning). |
| 1 | `ModelInfo` | Provider identity and model name. |
| 2 | `CostBreakdown \| None` | Cost data, or `None` when pricing is unavailable. |

---

## `GenericNormalizer`

```python
class GenericNormalizer:
    def normalize_response(
        self,
        response: object,
    ) -> tuple[TokenUsage, ModelInfo, CostBreakdown | None]: ...
```

Zero-dependency fallback that handles the three most common response shapes:

| Layout | Token fields | Model field |
|--------|-------------|-------------|
| **OpenAI-compatible** | `response.usage.prompt_tokens`, `.completion_tokens`, `.total_tokens` | `response.model` |
| **Anthropic-compatible** | `response.usage.input_tokens`, `.output_tokens` | `response.model` |
| **Raw dict** | Same keys as above, accessed via `dict[key]` | `response["model"]` |

The normalizer falls back gracefully when any field is missing — it always
returns a valid `TokenUsage` with zeros rather than raising.

`CostBreakdown` is always `None` — cost calculation requires a
`PricingTier` snapshot which `GenericNormalizer` does not possess.  Pass a
provider-specific normalizer for cost attribution.

### Example

```python
from spanforge import GenericNormalizer

normalizer = GenericNormalizer()

# Works with OpenAI-style objects, Anthropic-style objects, or raw dicts
token_usage, model_info, cost = normalizer.normalize_response(raw_response)

print(token_usage.input_tokens)   # e.g. 512
print(model_info.name)            # e.g. "gpt-4o"
print(cost)                       # None
```

`GenericNormalizer` does not perform pricing lookup, so `CostBreakdown` remains `None` unless you provide a provider-specific normalizer with pricing context.

When `ModelInfo.system` is `"_custom"`, SpanForge expects a non-empty `custom_system_name`. `GenericNormalizer` now supplies that automatically in its fallback path, and custom normalizers should do the same.

### Implementing your own normalizer

```python
from spanforge import ProviderNormalizer
from spanforge.namespaces.trace import CostBreakdown, ModelInfo, TokenUsage


class MyProviderNormalizer:
    """Custom normalizer for MyProvider's response format."""

    def normalize_response(
        self,
        response: object,
    ) -> tuple[TokenUsage, ModelInfo, CostBreakdown | None]:
        usage = response.usage  # type: ignore[attr-defined]
        return (
            TokenUsage(
                input_tokens=usage.input,
                output_tokens=usage.output,
                total_tokens=usage.input + usage.output,
            ),
            ModelInfo(
                system="_custom",
                name=response.model,  # type: ignore[attr-defined]
                custom_system_name="myprovider",
            ),
            None,
        )


# isinstance check works at runtime
assert isinstance(MyProviderNormalizer(), ProviderNormalizer)
```

---

## Top-level exports

Both symbols are exported at the top-level `spanforge` namespace:

```python
from spanforge import GenericNormalizer, ProviderNormalizer
```
