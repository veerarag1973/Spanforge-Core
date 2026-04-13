# HMAC Signing & Audit Chains

spanforge provides a cryptographic audit trail based on HMAC-SHA256. Every
signed event carries a payload checksum and a chain signature that links it to
its predecessor, forming a tamper-evident sequence that can detect deletions,
reorderings, and payload modifications.

## How signing works

```text
checksum  = sha256(canonical_payload_json)
sig_input = event_id + "|" + checksum + "|" + (prev_id or "")
signature = HMAC-SHA256(sig_input, org_secret)
```

The canonical payload JSON is compact (no whitespace) with sorted keys for
determinism. The resulting `checksum` and `signature` values are stored
directly on the event.

## Signing a single event

```python
from spanforge import Event, EventType
from spanforge.signing import sign, verify, assert_verified

event = Event(
    event_type=EventType.TRACE_SPAN_COMPLETED,
    source="my-tool@1.0.0",
    payload={"span_name": "chat"},
)

signed = sign(event, org_secret="my-org-secret")

assert signed.checksum is not None      # "sha256:..."
assert signed.signature is not None     # "hmac-sha256:..."
assert signed.prev_id is None           # first in chain

# Verify
assert verify(signed, org_secret="my-org-secret") is True

# Strict variant — raises VerificationError on failure
assert_verified(signed, org_secret="my-org-secret")
```

## Building an audit chain

Use `AuditStream` to build a chain where each event is linked to the previous
one via `prev_id`:

```python
from spanforge import Event, EventType
from spanforge.signing import AuditStream

stream = AuditStream(org_secret="my-org-secret", source="my-tool@1.0.0")

events_to_sign = [
    Event(event_type=EventType.TRACE_SPAN_COMPLETED,
          source="my-tool@1.0.0",
          payload={"index": i})
    for i in range(10)
]

for evt in events_to_sign:
    signed = stream.append(evt)     # returns signed event with prev_id set

print(len(stream))                  # 10
print(stream.events[0].prev_id)     # None — first event
print(stream.events[1].prev_id)     # == stream.events[0].event_id
```

## Verifying a chain

```python
from spanforge.signing import verify_chain

result = stream.verify()             # or: verify_chain(events, org_secret="...")

assert result.valid                  # True if no tampering or gaps
assert result.tampered_count == 0    # number of events with bad signatures
assert result.gaps == []             # event_ids where prev_id linkage broke
assert result.first_tampered is None # first tampered event_id, or None
```

### Detecting tampering

```python
from spanforge.signing import verify_chain

# Tamper with an event's payload after signing
signed_events = list(stream.events)
object.__setattr__(signed_events[3], "_payload", {"hacked": True})

result = verify_chain(signed_events, org_secret="my-org-secret")
assert not result.valid
assert result.tampered_count >= 1
assert result.first_tampered == signed_events[3].event_id
```

### Detecting deletions (gaps)

```python
# Remove event index 2 from the chain
events_with_gap = [e for i, e in enumerate(stream.events) if i != 2]

result = verify_chain(events_with_gap, org_secret="my-org-secret")
assert not result.valid
assert stream.events[3].event_id in result.gaps
```

## Key rotation

For long-lived audit streams, rotate the signing key periodically. The
rotation event itself is signed with the **old** key, providing continuity:

```python
stream = AuditStream(org_secret="old-secret", source="my-tool@1.0.0")

# ... append events ...

rotation_event = stream.rotate_key(
    "new-secret-v2",
    metadata={"reason": "scheduled", "rotated_by": "ops-team"},
)

# Subsequent events are signed with "new-secret-v2"
# Verification still works across the rotation boundary:
result = stream.verify()
assert result.valid
```

## Higher-level compliance wrapper

The `spanforge.compliance` module provides a richer wrapper over
`verify_chain()` that includes gap reporting, violation objects, and
timestamp monotonicity checks:

```python
from spanforge.compliance import verify_chain_integrity

result = verify_chain_integrity(events, org_secret="my-org-secret")
if not result:
    for v in result.violations:
        print(f"[{v.violation_type}] {v.event_id}: {v.detail}")
```

See [compliance.md](compliance.md) for the full compliance API.

---

## Key strength validation (new in v1.0.0)

Before using a key in production, validate it against security requirements:

```python
from spanforge.signing import validate_key_strength

warnings = validate_key_strength("my-secret")
if warnings:
    for w in warnings:
        print(f"⚠ {w}")
    # Key length 9 < minimum 32 characters
    # Key uses only 2 character class(es); recommend at least 2 (upper, lower, digit, special)
```

`validate_key_strength()` is also called automatically by `spanforge.configure()`
when a `signing_key` is set — warnings are logged via the `spanforge.config` logger.

You can control the minimum key length via the `SPANFORGE_SIGNING_KEY_MIN_BITS`
environment variable (value in bits, divided by 8 for character count):

```bash
export SPANFORGE_SIGNING_KEY_MIN_BITS=512   # requires 64-character key
```

---

## Key expiry checking (new in v1.0.0)

Configure a key expiry date to prevent use of stale keys:

```bash
export SPANFORGE_SIGNING_KEY_EXPIRES_AT="2026-12-31T00:00:00Z"
```

Once configured, `sign()` will raise `SigningError` if the key has expired.
Check key status programmatically:

```python
from spanforge.signing import check_key_expiry

status, days = check_key_expiry("2026-12-31T00:00:00Z")
# status: "valid", "expiring_soon" (≤7 days), "expired", or "no_expiry"
# days:   days remaining (or days since expiry)
```

---

## Environment-isolated key derivation (new in v1.0.0)

Use the `context` parameter on `derive_key()` to ensure the same passphrase
produces different keys for different environments:

```python
from spanforge.signing import derive_key

prod_key, prod_salt = derive_key("my-passphrase", context="production")
stg_key, stg_salt = derive_key("my-passphrase", context="staging")

assert prod_key != stg_key  # different environments → different keys
```

Or set via environment variable:

```bash
export SPANFORGE_SIGNING_KEY_CONTEXT="production"
```

---

## Multi-tenant key resolution (new in v1.0.0)

In multi-tenant deployments, different organisations may use different signing
keys. Use a `KeyResolver` to resolve the correct key per event:

```python
from spanforge.signing import AuditStream, DictKeyResolver

resolver = DictKeyResolver({
    "org_acme": "acme-secret-key-that-is-long-enough",
    "org_beta": "beta-secret-key-that-is-long-enough",
})

stream = AuditStream(
    org_secret="fallback-key-for-events-without-org",
    source="multi-tenant-svc@1.0.0",
    key_resolver=resolver,
    require_org_id=True,  # enforce that every event has an org_id
)

# Each event is signed with its org's key
stream.append(event_for_acme)   # signed with "acme-secret-key..."
stream.append(event_for_beta)   # signed with "beta-secret-key..."
```

Three resolvers are provided:

| Resolver | Description |
|----------|-------------|
| `StaticKeyResolver(secret)` | Same key for all orgs (single-tenant / testing). |
| `EnvKeyResolver(prefix)` | Reads `{prefix}{ORG_ID}` from environment variables. |
| `DictKeyResolver(keys)` | In-memory `{org_id: secret}` dictionary. |

You can also implement the `KeyResolver` protocol for custom resolution
(e.g. from a secrets manager):

```python
from spanforge.signing import KeyResolver

class VaultKeyResolver:
    def resolve(self, org_id: str) -> str:
        return vault_client.get_secret(f"signing-key/{org_id}")
```

---

## Async audit streams (new in v1.0.0)

For asyncio-based applications, use `AsyncAuditStream` which uses
`asyncio.Lock` instead of `threading.RLock`:

```python
import asyncio
from spanforge.signing import AsyncAuditStream

async def main():
    stream = AsyncAuditStream(org_secret="my-key", source="async-svc@1.0.0")

    signed = await stream.append(event)
    await stream.rotate_key("new-key", metadata={"reason": "scheduled"})

    result = await stream.verify()
    assert result.valid

asyncio.run(main())
```
