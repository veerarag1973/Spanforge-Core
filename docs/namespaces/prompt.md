# llm.prompt — Prompt Rendering

> **Auto-documented module:** `spanforge.namespaces.prompt`

The `llm.prompt.*` namespace records prompt rendering events, template
version changes, and template load operations (RFC-0001 §3).

## Payload classes

| Class | Event type | Description |
|-------|-----------|-------------|
| `PromptRenderedPayload` | `llm.prompt.rendered` | A prompt template was rendered |
| `PromptTemplateLoadedPayload` | `llm.prompt.template.loaded` | A template was loaded into the registry |
| `PromptVersionChangedPayload` | `llm.prompt.version.changed` | The active template version changed |

---

## `PromptRenderedPayload` — key fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `template_id` | `str` | ✓ | Registry identifier of the template |
| `version` | `str` | ✓ | Semantic version of the template used |
| `rendered_hash` | `str` | ✓ | SHA-256 of the rendered prompt text (64 lowercase hex chars) |
| `variable_count` | `int \| None` | — | Number of variables substituted |
| `variable_names` | `list[str]` | — | Names of substituted variables |
| `char_count` | `int \| None` | — | Character count of the rendered prompt |
| `token_estimate` | `int \| None` | — | Estimated token count |
| `language` | `str \| None` | — | Template language hint (e.g. `"jinja2"`) |
| `span_id` | `str \| None` | — | Parent span identifier |

---

## Example

```python
import hashlib
from spanforge import Event, EventType
from spanforge.namespaces.prompt import PromptRenderedPayload

rendered = "You are a helpful assistant. User: Hello!"
rendered_hash = hashlib.sha256(rendered.encode()).hexdigest()

payload = PromptRenderedPayload(
    template_id="support-reply-v3",
    version="3.1.0",
    rendered_hash=rendered_hash,
    variable_names=["customer_name", "product"],
    variable_count=2,
    char_count=len(rendered),
    token_estimate=12,
)

event = Event(
    event_type=EventType.PROMPT_RENDERED,
    source="my-app@1.0.0",
    org_id="org_01HX",
    payload=payload.to_dict(),
)
```
