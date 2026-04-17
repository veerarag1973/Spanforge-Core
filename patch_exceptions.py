import pathlib

SDK_SECTION = """
---

## SDK exceptions — `spanforge.sdk._exceptions`

The SDK uses its own exception hierarchy rooted at `SFError`.  All SDK
exceptions are safe to log: they never embed raw PII, HMAC keys, or secret
values.

### Hierarchy

```
SFError
├── SFAuthError
│   ├── SFTokenInvalidError
│   ├── SFScopeError
│   ├── SFIPDeniedError
│   ├── SFMFARequiredError
│   └── SFBruteForceLockedError
├── SFQuotaExceededError
├── SFRateLimitError
├── SFServiceUnavailableError
├── SFStartupError
├── SFKeyFormatError
├── SFPIIError                         # Phase 3
│   ├── SFPIIScanError
│   ├── SFPIINotRedactedError
│   ├── SFPIIPolicyError
│   ├── SFPIIBlockedError              # pipeline action="block"
│   └── SFPIIDPDPConsentMissingError   # DPDP consent gate
└── SFSecretsError
    ├── SFSecretsBlockedError
    └── SFSecretsScanError
```

---

### `SFPIIError` {#sfpii-exceptions}

```python
class SFPIIError(SFError)
```

Base class for all sf-pii SDK errors.  Catch this to handle any PII-related
failure in a single `except` clause.

---

### `SFPIIBlockedError`

```python
class SFPIIBlockedError(SFPIIError)
SFPIIBlockedError(entity_types: list[str], count: int)
```

Raised by `SFPIIClient.apply_pipeline_action(action="block")` when PII above
the confidence threshold is detected.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `entity_types` | `list[str]` | Entity type labels that triggered the block (e.g. `["US_SSN", "EMAIL_ADDRESS"]`). |
| `count` | `int` | Number of entities that exceeded the threshold. |

**HTTP status equivalent:** `422 Unprocessable Entity` (`PII_DETECTED`).

**Security:** Entity type *labels* are included; matched text is **never** embedded.

**Example:**

```python
from spanforge.sdk import sf_pii
from spanforge.sdk._exceptions import SFPIIBlockedError

scan = sf_pii.scan_text("SSN: 078-05-1120")
try:
    sf_pii.apply_pipeline_action(scan, action="block")
except SFPIIBlockedError as exc:
    # exc.entity_types == ["US_SSN"]
    # exc.count == 1
    return http_422("PII_DETECTED", exc.entity_types)
```

---

### `SFPIIDPDPConsentMissingError`

```python
class SFPIIDPDPConsentMissingError(SFPIIError)
SFPIIDPDPConsentMissingError(subject_id_hash: str, entity_types: list[str])
```

Raised when a DPDP-regulated entity is detected but no valid consent record
exists for the current processing purpose.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `subject_id_hash` | `str` | SHA-256 hex digest of the subject identifier (never the raw ID). |
| `entity_types` | `list[str]` | DPDP entity types that triggered the consent check. |

**Security:** The raw subject ID is **never** stored in this exception —
only its SHA-256 hash.

**Example:**

```python
from spanforge.sdk._exceptions import SFPIIDPDPConsentMissingError

try:
    result = sf_pii.scan_text(user_text)
except SFPIIDPDPConsentMissingError as exc:
    logger.warning(
        "DPDP consent missing for subject=%s types=%s",
        exc.subject_id_hash,
        exc.entity_types,
    )
```

---

### `SFPIIScanError`

```python
class SFPIIScanError(SFPIIError)
SFPIIScanError(reason: str)
```

Wraps unexpected failures from the underlying PII scan engine (Presidio or
regex fallback).

---

### `SFPIINotRedactedError`

```python
class SFPIINotRedactedError(SFPIIError)
SFPIINotRedactedError(field_path: str, pii_type: str)
```

Raised by `assert_redacted()` when an event contains an unredacted
`Redactable` field.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `field_path` | `str` | Dotted path to the unredacted field. |
| `pii_type` | `str` | The PII type label of the unredacted value. |

---

### `SFPIIPolicyError`

```python
class SFPIIPolicyError(SFPIIError)
SFPIIPolicyError(reason: str)
```

Raised when a `RedactionPolicy` or pipeline-action configuration is invalid
(e.g. unknown action string).

---

## See also

- [spanforge.sdk.pii](pii.md) — full PII service client reference
- [spanforge.sdk.secrets](secrets.md) — secrets scanning exceptions
"""

path = pathlib.Path("docs/api/exceptions.md")
path.write_text(path.read_text(encoding="utf-8") + SDK_SECTION, encoding="utf-8")
print("Done")
