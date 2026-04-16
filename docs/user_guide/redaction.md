# PII Redaction

spanforge provides a field-level PII redaction framework that lets you mark
sensitive values at the point of creation and apply policies before the event
is stored, exported, or logged.

## Sensitivity levels

`Sensitivity` defines five ordered levels:

```python
from spanforge.redact import Sensitivity

Sensitivity.LOW          # "low" — non-sensitive metadata
Sensitivity.MEDIUM       # "medium" — pseudonymous or indirect identifiers
Sensitivity.HIGH         # "high" — directly identifying but non-regulated
Sensitivity.PII          # "pii" — personally identifiable information
Sensitivity.PHI          # "phi" — protected health information (strictest)
```

## Marking fields as redactable

Wrap any payload value in `Redactable` to mark it:

```python
from spanforge import Event, EventType
from spanforge.redact import Redactable, Sensitivity

event = Event(
    event_type=EventType.PROMPT_SAVED,
    source="promptlock@1.0.0",
    payload={
        "prompt_text": Redactable(
            value="User email: alice@example.com",
            sensitivity=Sensitivity.PII,
            pii_types={"email"},
        ),
        "model": "gpt-4o",           # plain value — not redactable
    },
)
```

## Applying a redaction policy

`RedactionPolicy` scrubs every `Redactable` field whose sensitivity is at or
above the policy's `min_sensitivity`:

```python
from spanforge.redact import RedactionPolicy, Sensitivity

policy = RedactionPolicy(
    min_sensitivity=Sensitivity.PII,
    redacted_by="policy:corp-v1",
)

result = policy.apply(event)
# result.event.payload["prompt_text"] == "[REDACTED]"
# result.event.payload["model"]       == "gpt-4o"  (unchanged)

print(result.redaction_count)          # 1
```

## Inspecting redaction results

```python
result = policy.apply(event)
print(f"{result.redaction_count} field(s) redacted")

# Check nothing was missed
from spanforge.redact import assert_redacted
assert_redacted(result.event)
# raises PIINotRedactedError if any PII field was left unredacted
```

## Detecting PII without redacting

```python
from spanforge.redact import contains_pii

if contains_pii(event):
    print("Event contains PII — apply policy before exporting")
```

## Built-in PII types

`PII_TYPES` provides the built-in set of PII type labels:

```python
from spanforge.redact import PII_TYPES
print(PII_TYPES)
# frozenset({'email', 'phone', 'name', 'address', 'ip', 'ssn', 'dob', ...})
```

## Policy-based workflow

The recommended workflow is:

1. Tools emit events with `Redactable` wrappers on all sensitive fields.
2. The event collector/exporter applies the appropriate `RedactionPolicy`
   before writing to storage or sending over the wire.
3. CI runs `assert_redacted()` or `contains_pii()` on sampled events to
   catch unannotated fields.

```python
from spanforge.redact import RedactionPolicy, Sensitivity, assert_redacted

# Strict policy — redact everything at PII or above
CORP_POLICY = RedactionPolicy(
    min_sensitivity=Sensitivity.PII,
    redacted_by="policy:corp-v1",
)

def export_event(event):
    result = CORP_POLICY.apply(event)
    assert_redacted(result.event)
    write_to_storage(result.event)
```
