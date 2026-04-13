# spanforge.signing

HMAC-SHA256 event signing, chain verification, and the `AuditStream` class.

See the [Signing User Guide](../user_guide/signing.md) for full usage examples.

---

## `ChainVerificationResult`

```python
@dataclass(frozen=True)
class ChainVerificationResult:
    valid: bool
    first_tampered: Optional[str]
    gaps: List[str]
    tampered_count: int
    tombstone_count: int = 0
    tombstone_event_ids: List[str] = field(default_factory=list)
```

Result of a `verify_chain()` call.

**Attributes:**

| Attribute | Type | Description |
|-----------|------|-------------|
| `valid` | `bool` | `True` when the entire chain verified without gaps or tampered events. |
| `first_tampered` | `str \| None` | `event_id` of the first tampered event, or `None` if all verified. |
| `gaps` | `List[str]` | List of `event_id` strings where the chain has broken `prev_id` links. |
| `tampered_count` | `int` | Total number of events that failed HMAC verification. |
| `tombstone_count` | `int` | Number of `AUDIT_TOMBSTONE` events in the chain (GDPR erasure markers). |
| `tombstone_event_ids` | `List[str]` | Event IDs of all tombstone events. |

---

## Module-level functions

### `sign(event, org_secret, prev_event=None) -> Event`

```python
def sign(
    event: Event,
    org_secret: str,
    prev_event: Optional[Event] = None,
) -> Event
```

Sign an event with HMAC-SHA256 and return a **new** event with `checksum`,
`signature`, and (if `prev_event` is provided) `prev_id` set.

The original event is **not** mutated.

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `event` | `Event` | The event to sign. Must have a valid `event_id`. |
| `org_secret` | `str` | HMAC secret for the organisation. Never included in logs or exceptions. |
| `prev_event` | `Event \| None` | Preceding event in the audit chain. Sets `prev_id` on the returned event. |

**Returns:** `Event` — a new event with `checksum`, `signature`, and optionally `prev_id` populated.

**Raises:** `SigningError` — if `org_secret` is empty or the event has no `event_id`.

**Example:**

```python
from spanforge.signing import sign

signed = sign(event, org_secret="my-secret")
assert signed.signature is not None
```

---

### `verify(event, org_secret) -> bool`

```python
def verify(event: Event, org_secret: str) -> bool
```

Return `True` if the event's HMAC signature is valid.

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `event` | `Event` | A previously signed event. |
| `org_secret` | `str` | The secret used when signing. |

**Returns:** `bool` — `True` if the signature is valid, `False` otherwise.

**Raises:** `SigningError` — if `org_secret` is empty or whitespace-only.

---

### `assert_verified(event, org_secret) -> None`

```python
def assert_verified(event: Event, org_secret: str) -> None
```

Raise an exception if the event's signature is invalid.

Equivalent to: `if not verify(event, secret): raise VerificationError(event.event_id)`

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `event` | `Event` | A previously signed event. |
| `org_secret` | `str` | The secret used when signing. |

**Raises:** `VerificationError` — if the signature does not match. `SigningError` — if `org_secret` is empty or whitespace-only.

---

### `verify_chain(events, org_secret, key_map=None, *, key_resolver=None, default_key=None) -> ChainVerificationResult`

```python
def verify_chain(
    events: Sequence[Event],
    org_secret: str,
    key_map: Optional[Dict[str, str]] = None,
    *,
    key_resolver: Optional[KeyResolver] = None,
    default_key: Optional[str] = None,
) -> ChainVerificationResult
```

Verify an entire ordered sequence of signed events as a tamper-evident chain.

Checks each event's HMAC signature and validates that `prev_id` links are
continuous. Returns a `ChainVerificationResult` summarising any gaps or
tampered events.

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `events` | `Sequence[Event]` | Ordered list of events from oldest to newest. |
| `org_secret` | `str` | Default HMAC secret for all events. |
| `key_map` | `Dict[str, str] \| None` | Optional mapping of `event_id → secret` for per-event key rotation support. |
| `key_resolver` | `KeyResolver \| None` | Optional resolver for per-org key resolution in multi-tenant chains. |
| `default_key` | `str \| None` | Fallback key for events without `org_id` when using `key_resolver`. Defaults to `org_secret`. |

**Returns:** `ChainVerificationResult`

**Raises:** `SigningError` — if `org_secret` is empty.

**Example — multi-tenant verification:**

```python
from spanforge.signing import verify_chain, DictKeyResolver

resolver = DictKeyResolver({"org_acme": "acme-secret", "org_beta": "beta-secret"})
result = verify_chain(events, org_secret="fallback", key_resolver=resolver)
```

---

## `AuditStream`

```python
class AuditStream(
    org_secret: str,
    source: str,
    *,
    key_resolver: Optional[KeyResolver] = None,
    require_org_id: bool = False,
)
```

A stateful, append-only audit stream that automatically signs each event and
maintains a tamper-evident chain. Thread-safe via `threading.RLock`.

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `org_secret` | `str` | HMAC signing secret. Must be non-empty. |
| `source` | `str` | Source string for auto-generated audit events (e.g. `"my-service@1.0.0"`). |
| `key_resolver` | `KeyResolver \| None` | Optional resolver for per-org key resolution. When set and the event has an `org_id`, the resolver provides the signing key. |
| `require_org_id` | `bool` | When `True`, `append()` raises `SigningError` if `event.org_id` is `None` or empty. |

**Raises:** `SigningError` — if `org_secret` is empty.

**Example:**

```python
from spanforge.signing import AuditStream, DictKeyResolver

# Single-tenant
stream = AuditStream(org_secret="my-secret", source="my-service@1.0.0")
signed = stream.append(event)
result = stream.verify()

# Multi-tenant with org_id enforcement
resolver = DictKeyResolver({"org_acme": "acme-key", "org_beta": "beta-key"})
stream = AuditStream(
    org_secret="fallback",
    source="my-service@1.0.0",
    key_resolver=resolver,
    require_org_id=True,
)
```

### Properties

#### `events -> List[Event]`

A read-only copy of all signed events in the stream.

### Methods

#### `append(event: Event) -> Event`

Sign and append an event to the stream.

The event is signed with the current `org_secret`, with `prev_id` pointing to
the last event in the chain. Returns the signed event.

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `event` | `Event` | The event to append. |

**Returns:** `Event` — the signed event with `checksum`, `signature`, and `prev_id` set.

**Raises:** `SigningError` — if signing fails.

---

#### `rotate_key(new_secret: str, metadata: Optional[Dict[str, Any]] = None) -> Event`

Rotate the HMAC signing key.

Appends a signed `llm.audit.key.rotated` sentinel event (signed with the **old**
key), then switches to `new_secret` for subsequent events.

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `new_secret` | `str` | The new HMAC secret to use going forward. Must be non-empty. |
| `metadata` | `Dict[str, Any] \| None` | Optional metadata to include in the key-rotation event's payload. |

**Returns:** `Event` — the signed key-rotation sentinel event.

**Raises:** `SigningError` — if `new_secret` is empty.

---

#### `verify() -> ChainVerificationResult`

Verify the entire chain held by this stream.

Uses `verify_chain()` internally with the current `org_secret`.

**Returns:** `ChainVerificationResult`

---

## New in v1.0.0

### `validate_key_strength(org_secret, *, min_length=None) -> list[str]`

```python
def validate_key_strength(org_secret: str, *, min_length: int | None = None) -> list[str]
```

Check a signing key against strength requirements.

Returns a list of warning strings. An empty list means the key is strong.

**Checks performed:**
- Minimum length (default 32 chars / 256-bit, or `SPANFORGE_SIGNING_KEY_MIN_BITS / 8`)
- Not all-same character
- Not a well-known placeholder (`"secret"`, `"password"`, `"changeme"`, etc.)
- Mixed character classes (upper, lower, digit, special — at least 2 required)

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `org_secret` | `str` | The signing key to check. |
| `min_length` | `int \| None` | Minimum key length in characters. When `None`, uses `SPANFORGE_SIGNING_KEY_MIN_BITS / 8` or falls back to 32. |

**Returns:** `list[str]` — human-readable warnings. Empty if key is strong.

**Example:**

```python
from spanforge.signing import validate_key_strength

warnings = validate_key_strength("short")
# ['Key length 5 < minimum 32 characters', 'Key uses only 1 character class(es); ...']

warnings = validate_key_strength("Str0ng!K3y-F0r-Pr0duct10n-Us3-2026!!")
# []  — strong key
```

---

### `check_key_expiry(expires_at) -> tuple[str, int]`

```python
def check_key_expiry(expires_at: str | None) -> tuple[str, int]
```

Check the signing key expiry status.

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `expires_at` | `str \| None` | ISO-8601 datetime string, or `None` (no expiry). |

**Returns:** A tuple of `(status, days)`:

| Status | Meaning |
|--------|---------|
| `"no_expiry"` | No expiration configured (days=0). |
| `"expired"` | Key has expired (days = days since expiry). |
| `"expiring_soon"` | Key expires within 7 days (days = days remaining). |
| `"valid"` | Key is valid (days = days remaining). |

**Example:**

```python
from spanforge.signing import check_key_expiry

status, days = check_key_expiry("2026-12-31T00:00:00Z")
# ("valid", 290)

status, days = check_key_expiry(None)
# ("no_expiry", 0)
```

---

### `derive_key(passphrase, salt=None, iterations=600_000, *, context=None) -> tuple[str, bytes]`

```python
def derive_key(
    passphrase: str,
    salt: bytes | None = None,
    iterations: int = 600_000,
    *,
    context: str | None = None,
) -> tuple[str, bytes]
```

Derive a signing key from a passphrase using PBKDF2-HMAC-SHA256.

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `passphrase` | `str` | Human-memorable passphrase. |
| `salt` | `bytes \| None` | 16-byte salt. A random salt is generated if `None`. |
| `iterations` | `int` | PBKDF2 iteration count (default 600,000 per OWASP 2023). |
| `context` | `str \| None` | Optional context for environment isolation. When provided, appended as `passphrase + "\|" + context` before derivation. |

**Returns:** Tuple of `(derived_key_hex, salt_bytes)`.

**Example:**

```python
from spanforge.signing import derive_key

# Same passphrase, different environments → different keys
prod_key, prod_salt = derive_key("my-passphrase", context="production")
stg_key, stg_salt = derive_key("my-passphrase", context="staging")
assert prod_key != stg_key
```

---

## Key Resolver Classes

### `KeyResolver` (Protocol)

```python
@runtime_checkable
class KeyResolver(Protocol):
    def resolve(self, org_id: str) -> str: ...
```

Protocol for resolving signing keys per-org in multi-tenant setups. Implementations
must return a non-empty string secret for the given `org_id`.

---

### `StaticKeyResolver`

```python
class StaticKeyResolver(secret: str)
```

Returns the same key for every org. Useful for single-tenant or testing.

---

### `EnvKeyResolver`

```python
class EnvKeyResolver(prefix: str = "SPANFORGE_KEY_")
```

Resolves signing keys from environment variables. The env var name is
`{prefix}{org_id.upper().replace('-', '_')}`.

**Example:**

```python
# With SPANFORGE_KEY_ORG_ACME="acme-secret" in env
resolver = EnvKeyResolver()
secret = resolver.resolve("org-acme")  # reads SPANFORGE_KEY_ORG_ACME
```

---

### `DictKeyResolver`

```python
class DictKeyResolver(keys: Dict[str, str])
```

Resolves signing keys from an in-memory dictionary mapping `org_id → secret`.

**Example:**

```python
resolver = DictKeyResolver({"org_acme": "acme-secret", "org_beta": "beta-secret"})
secret = resolver.resolve("org_acme")  # "acme-secret"
```

---

## `AsyncAuditStream`

```python
class AsyncAuditStream(
    org_secret: str,
    source: str,
    *,
    key_resolver: Optional[KeyResolver] = None,
)
```

Asyncio-native tamper-evident HMAC-signed audit chain. Uses `asyncio.Lock`
instead of `threading.RLock`, making it safe for `async def` code paths
without blocking the event loop.

**Args:**

| Parameter | Type | Description |
|-----------|------|-------------|
| `org_secret` | `str` | HMAC signing key. |
| `source` | `str` | Source field for auto-generated audit events. |
| `key_resolver` | `KeyResolver \| None` | Optional per-org key resolver. |

### Methods

#### `await append(event) -> Event`

Sign and append an event to the chain.

#### `await rotate_key(new_secret, metadata=None) -> Event`

Rotate the signing key (async version).

#### `await verify() -> ChainVerificationResult`

Verify the full chain.

**Example:**

```python
import asyncio
from spanforge.signing import AsyncAuditStream

async def main():
    stream = AsyncAuditStream(org_secret="key", source="svc@1.0.0")
    signed = await stream.append(event)
    result = await stream.verify()
    assert result.valid

asyncio.run(main())
```
