# llm.template — Template Registry

> **Auto-documented module:** `spanforge.namespaces.template`

The `llm.template.*` namespace records when prompt templates are registered,
modified, or validated in the template registry (RFC-0001 §3).

## Payload classes

| Class | Event type | Description |
|-------|-----------|-------------|
| `TemplateRegisteredPayload` | `llm.template.registered` | A template was added to the registry |
| `TemplateVariableBoundPayload` | `llm.template.variable.bound` | A variable was bound in a template |
| `TemplateValidationFailedPayload` | `llm.template.validation.failed` | Template validation failed |

---

## `TemplateRegisteredPayload` — key fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `template_id` | `str` | ✓ | Registry identifier for the template |
| `version` | `str` | ✓ | Semantic version of the template |
| `template_hash` | `str` | ✓ | SHA-256 of the template source (64 lowercase hex chars) |
| `variable_names` | `list[str]` | — | Names of declared template variables |
| `variable_count` | `int \| None` | — | Count of declared variables |
| `language` | `str \| None` | — | Template language (e.g. `"jinja2"`, `"mustache"`) |
| `char_count` | `int \| None` | — | Character length of the template source |
| `registered_by` | `str \| None` | — | Identity of the registrant |
| `is_active` | `bool \| None` | — | Whether this is the active version |
| `tags` | `dict[str, str] \| None` | — | Metadata tags (key-value pairs) |

---

## Example

```python
import hashlib
from spanforge import Event, EventType
from spanforge.namespaces.template import TemplateRegisteredPayload

source = "Dear {{ customer_name }}, thank you for contacting support."
template_hash = hashlib.sha256(source.encode()).hexdigest()

payload = TemplateRegisteredPayload(
    template_id="support-reply-v3",
    version="3.0.0",
    template_hash=template_hash,
    variable_names=["customer_name", "product"],
    variable_count=2,
    language="jinja2",
    registered_by="eng@company.com",
    is_active=True,
    tags={"team": "support", "env": "prod"},
)

event = Event(
    event_type=EventType.TEMPLATE_REGISTERED,
    source="template-svc@1.0.0",
    org_id="org_01HX",
    payload=payload.to_dict(),
)
```
