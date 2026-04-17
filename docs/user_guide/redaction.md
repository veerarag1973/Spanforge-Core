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

---

## PII service SDK (Phase 3)

`spanforge.sdk.pii` adds a full-featured, regulation-aware PII engine on top of
the field-level `Redactable` / `RedactionPolicy` layer.  Use it when you need:

- structured entity recognition (Presidio + regex fallback)
- text anonymisation with stable pseudonyms
- pipeline actions (flag / redact / block) integrated with spanforge events
- GDPR Art.17, CCPA DSAR, HIPAA safe harbor, DPDP consent gate, PIPL support

Import the singleton client:

```python
from spanforge.sdk import sf_pii
```

### Scanning text

```python
result = sf_pii.scan_text("Contact alice@example.com or call +1 555-867-5309")
# PIITextScanResult
print(result.detected)         # True
print(result.entity_count)     # 2
for entity in result.entities:
    print(entity.entity_type, entity.start, entity.end, entity.score)
```

### Anonymisation

Replace detected entities with stable pseudonyms (counters reset per call):

```python
anon = sf_pii.anonymise(result)
print(anon.anonymised_text)
# "Contact <EMAIL_ADDRESS_1> or call <PHONE_NUMBER_1>"
print(anon.mapping)
# {"EMAIL_ADDRESS_1": (8, 27), "PHONE_NUMBER_1": (38, 54)}
```

### Pipeline actions

`apply_pipeline_action()` applies a *pipeline action* to a `PIITextScanResult`:

| Action | Effect |
|--------|--------|
| `"flag"` | Annotates the result; raises nothing. |
| `"redact"` | Returns text with PII tokens replaced by type labels. |
| `"block"` | Raises `SFPIIBlockedError` if any entities exceed the threshold. |

```python
from spanforge.sdk._exceptions import SFPIIBlockedError

# Redact mode — no exception raised
redacted = sf_pii.apply_pipeline_action(result, action="redact")
print(redacted)  # "Contact <EMAIL_ADDRESS> or call <PHONE_NUMBER>"

# Block mode
try:
    sf_pii.apply_pipeline_action(result, action="block", threshold=0.85)
except SFPIIBlockedError as exc:
    print(exc.entity_types)  # ["EMAIL_ADDRESS", "PHONE_NUMBER"]
    print(exc.count)         # 2
```

The default action and threshold are read from `SPANFORGE_PII_ACTION` and
`SPANFORGE_PII_THRESHOLD` (see [configuration](../configuration.md)).

### Scanning structured payloads

Scan a nested dict up to `max_depth` levels:

```python
pipe = sf_pii.scan_payload(
    {"user": {"email": "alice@example.com", "dob": "1980-01-15"}},
    max_depth=5,
)
# PIIPipelineResult
for entry in pipe.manifest:
    print(entry.field_path, entry.entity_type, entry.score)
# user.email  EMAIL_ADDRESS  0.95
# user.dob    DATE_OF_BIRTH  0.90
```

### Scanning a spanforge event

```python
from spanforge import Event, EventType

event = Event(
    event_type=EventType.TOOL_CALL,
    source="chatbot@1.0.0",
    payload={"prompt": "Call me at +1 555-867-5309"},
)
pipe = sf_pii.scan_event(event)
if pipe.detected:
    sf_pii.apply_pipeline_action(
        sf_pii.scan_text(event.payload["prompt"]),
        action="redact",
    )
```

### GDPR Art.17 — right to erasure

```python
receipt = sf_pii.erase_subject(subject_id="user-42")
print(receipt.receipt_id)        # "erase-20260417-…"
print(receipt.fields_erased)     # 12
print(receipt.audit_log_entry)   # structured dict for your compliance log
```

### CCPA DSAR — data subject access request

```python
export = sf_pii.export_subject_data(subject_id="user-42")
print(export.subject_id_hash)    # SHA-256 of "user-42"
for field in export.fields:
    print(field.field_path, field.pii_type)
```

### HIPAA safe harbor de-identification

The 18 HIPAA safe harbor identifiers are redacted in one call:

```python
safe = sf_pii.safe_harbor_deidentify(
    {"dob": "1980-01-15", "zip": "02139", "name": "Alice Smith"}
)
print(safe.original_field_count)  # 3
print(safe.redacted_field_count)  # 3
print(safe.method)                # "HIPAA_SAFE_HARBOR"
```

### Training data audit

```python
report = sf_pii.audit_training_data(
    [{"text": "SSN 078-05-1120"}, {"text": "Normal text"}]
)
print(report.pii_row_count)    # 1
print(report.total_row_count)  # 2
print(report.risk_score)       # 0.5
```

### PII heatmap

Frequency heat map over a batch of records — useful for dashboards:

```python
heatmap = sf_pii.generate_pii_heatmap(
    [{"prompt": "alice@example.com"}, {"prompt": "no PII here"}]
)
for entry in heatmap:
    print(entry.entity_type, entry.frequency, entry.average_score)
```

### Service status

```python
status = sf_pii.get_service_status()
print(status.status)               # "ok"
print(status.presidio_available)   # True
print(status.entity_types_loaded)  # ["EMAIL_ADDRESS", ...]
```

### DPDP consent gate

When DPDP-regulated entities are detected without a consent record, the client
raises `SFPIIDPDPConsentMissingError`:

```python
from spanforge.sdk._exceptions import SFPIIDPDPConsentMissingError

try:
    result = sf_pii.scan_text("Aadhaar: 2950 7148 9635")
except SFPIIDPDPConsentMissingError as exc:
    print(exc.subject_id_hash)  # SHA-256 of subject id
    print(exc.entity_types)     # ["IN_AADHAAR"]
```

### PIPL (China) entity types

```python
result = sf_pii.scan_text("身份证: 110101199003077516", language="zh")
for entity in result.entities:
    print(entity.entity_type)  # PIPL_NATIONAL_ID
```

Recognised PIPL types: `PIPL_NATIONAL_ID`, `PIPL_PASSPORT`, `PIPL_MOBILE`,
`PIPL_BANK_CARD`, `PIPL_SOCIAL_CREDIT`.

---

## See also

- [spanforge.sdk.pii](../api/pii.md) — full API reference
- [configuration](../configuration.md#pii-service-settings-phase-3) — env vars
- [compliance user guide](compliance.md) — GDPR/HIPAA/CCPA/DPDP/PIPL workflows
