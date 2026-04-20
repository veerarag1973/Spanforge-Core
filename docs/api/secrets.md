# spanforge.secrets — Secrets scanning engine

> **Module:** `spanforge.secrets`  
> **Added in:** 2.0.3 (Phase 2: sf-secrets)

`spanforge.secrets` provides a standalone, zero-network-call secrets detection
engine with a 20-pattern registry, Shannon entropy scoring, and SARIF 2.1.0
output. The SDK client (`spanforge.sdk.secrets.SFSecretsClient`) wraps the
engine with auto-block policy and optional remote service support.

---

## Quick example

```python
from spanforge.secrets import SecretsScanner

scanner = SecretsScanner()
result = scanner.scan(open("config.env").read())

if result.detected:
    print(f"{len(result.hits)} secret(s) found")
    for hit in result.hits:
        print(f"  {hit.secret_type}  confidence={hit.confidence:.2f}")

# SARIF for GitHub Code Scanning
if result.detected:
    import json
    print(json.dumps(result.to_sarif(), indent=2))
```

---

## API

### `SecretsScanner`

```python
class SecretsScanner:
    def __init__(
        self,
        confidence_threshold: float = 0.85,
        allowlist: list[str] | None = None,
    ) -> None: ...
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `confidence_threshold` | `0.85` | Minimum score for a hit to be included in results. |
| `allowlist` | `None` | List of known-safe placeholder strings to suppress. Case-insensitive. |

#### `scan()`

```python
def scan(self, text: str, *, confidence_threshold: float | None = None) -> SecretsScanResult
```

Scan `text` for secrets. Returns a `SecretsScanResult`. Thread-safe. The
optional `confidence_threshold` override applies to this call only.

#### `scan_batch()`

```python
async def scan_batch(self, texts: list[str]) -> list[SecretsScanResult]
```

Scan multiple texts in parallel using `asyncio.gather`. Falls back to
sequential execution when the event loop is not running.

---

### `SecretsScanResult`

```python
@dataclass
class SecretsScanResult:
    detected: bool
    hits: list[SecretHit]
    auto_blocked: bool
    redacted_text: str

    def to_dict(self) -> dict: ...
    def to_sarif(self) -> dict: ...
```

| Field | Type | Description |
|-------|------|-------------|
| `detected` | `bool` | `True` if at least one hit meets the confidence threshold. |
| `hits` | `list[SecretHit]` | All matches at or above the threshold. |
| `auto_blocked` | `bool` | `True` if any hit is a zero-tolerance type. |
| `redacted_text` | `str` | Input text with all detected secrets replaced by `[REDACTED:TYPE]`. |

**`to_dict()`** — Returns a JSON-serialisable `dict` suitable for logging or
`--format json` CLI output.

**`to_sarif()`** — Returns a SARIF 2.1.0 log object (as a `dict`) that can be
uploaded to GitHub Code Scanning or consumed by VS Code's SARIF viewer.

---

### `SecretHit`

```python
@dataclass(frozen=True)
class SecretHit:
    secret_type: str
    start: int
    end: int
    confidence: float
    redacted_value: str
```

| Field | Description |
|-------|-------------|
| `secret_type` | One of the 20 registered type names (e.g. `AWS_ACCESS_KEY`). |
| `start` | Byte offset of the match start in the input text. |
| `end` | Byte offset of the match end (exclusive). |
| `confidence` | Score in [0.75, 0.97]: 0.75 = pattern only, 0.90 = + entropy, 0.97 = + context. |
| `redacted_value` | Replacement string used in `redacted_text` (e.g. `[REDACTED:AWS_ACCESS_KEY]`). |

---

### `entropy_score()`

```python
def entropy_score(s: str) -> float
```

Compute the Shannon entropy of `s` in bits per character. A score ≥ 3.5 for a
string of ≥ 32 characters is used as a secondary confidence booster inside the
scanner. Available as a standalone utility for custom scoring logic.

```python
from spanforge.secrets import entropy_score

print(entropy_score("AKIAIOSFODNN7EXAMPLE"))   # ~3.8 — high entropy
print(entropy_score("YOUR_KEY_HERE"))           # ~2.1 — low entropy (placeholder)
```

---

## Confidence model

| Score | Conditions |
|-------|------------|
| `0.75` | Pattern match only |
| `0.90` | Pattern match + entropy ≥ 3.5 bits/char (string ≥ 32 chars) |
| `0.97` | Pattern match + entropy + adjacent context keyword (`secret`, `key`, `token`, `credential`, `password`, `api`, etc.) |

---

## Registered secret types

| Type | Auto-blocked | Pattern basis |
|------|:-----------:|---------------|
| `BEARER_TOKEN` | ✅ | `Authorization: Bearer …` |
| `AWS_ACCESS_KEY` | ✅ | `AKIA…` 20-char uppercase alphanumeric |
| `GCP_SERVICE_ACCOUNT` | ✅ | `"type": "service_account"` JSON |
| `PEM_PRIVATE_KEY` | ✅ | `-----BEGIN … PRIVATE KEY-----` |
| `SSH_PRIVATE_KEY` | ✅ | `-----BEGIN OPENSSH PRIVATE KEY-----` |
| `HC_API_KEY` | ✅ | HallucCheck API key pattern |
| `SF_API_KEY` | ✅ | SpanForge API key pattern |
| `GITHUB_PAT` | ✅ | `ghp_…` / `github_pat_…` |
| `STRIPE_LIVE_KEY` | ✅ | `sk_live_…` |
| `NPM_TOKEN` | ✅ | `//registry.npmjs.org/:_authToken=…` |
| `GENERIC_JWT` | — | `eyJ…` base64-encoded header |
| `GOOGLE_API_KEY` | — | `AIza…` 39-char keys |
| `SLACK_TOKEN` | — | `xox[bpoas]-…` |
| `TWILIO_ACCOUNT_SID` | — | `AC…` 32-char hex |
| `SENDGRID_API_KEY` | — | `SG.…` keys |
| `AZURE_SAS_TOKEN` | — | `sig=…` URL parameters |
| `TERRAFORM_CLOUD_TOKEN` | — | `…atlasv1.…` tokens |
| `HASHICORP_VAULT_TOKEN` | — | `hvs.…` / `s.…` tokens |
| `GENERIC_SECRET` | — | `secret=`, `password=`, `api_key=` |
| `OPENAI_API_KEY` | — | `sk-…` OpenAI keys |

---

## SDK client — `spanforge.sdk.secrets`

```python
from spanforge.sdk.secrets import SFSecretsClient
from spanforge.sdk import sf_secrets  # singleton
```

`SFSecretsClient` wraps `SecretsScanner` with:

- **Auto-block policy** — raises `SFSecretsBlockedError` when a zero-tolerance
  type is detected and `SPANFORGE_SECRETS_AUTO_BLOCK=true`
- **Remote forwarding** — POST `/v1/scan/secrets` when
  `SPANFORGE_SF_SECRETS_ENDPOINT` is set; falls back to local scan on error
- Inherits retry logic and circuit breaker from `SFServiceClient`

```python
from spanforge.sdk import sf_secrets
from spanforge.sdk._exceptions import SFSecretsBlockedError

try:
    result = sf_secrets.scan(open("deploy.sh").read())
    print("Clean:", not result.detected)
except SFSecretsBlockedError as exc:
    print(f"Blocked — detected: {exc.secret_types}")
```

### Exceptions

| Exception | Description |
|-----------|-------------|
| `SFSecretsError` | Base class for all sf-secrets SDK errors |
| `SFSecretsBlockedError(secret_types, count)` | Raised when auto-block policy fires; `secret_types` is the list of detected zero-tolerance types |
| `SFSecretsScanError` | Wraps unexpected scanner failures |

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SPANFORGE_SECRETS_CONFIDENCE_THRESHOLD` | `0.85` | Default threshold for `SecretsScanner` instances created without an explicit value. |
| `SPANFORGE_SECRETS_AUTO_BLOCK` | `true` | Enable/disable zero-tolerance auto-block in `SFSecretsClient`. |
| `SPANFORGE_SECRETS_ALLOWLIST` | *(none)* | Comma-separated safe placeholder values to suppress. |
| `SPANFORGE_SF_SECRETS_ENDPOINT` | *(none)* | Remote service URL for centralised policy enforcement. |

---

### `scan_async(text, *, threshold=None) → Coroutine[SecretsScanResult]`

Async variant of `scan()`. Runs the scan in a thread-pool executor so it does
not block the event loop. Suitable for use inside `async def` handlers.

```python
import asyncio
from spanforge.sdk import sf_secrets

async def check_output(text: str):
    result = await sf_secrets.scan_async(text)
    if result.detected:
        print(f"Found secrets: {[h.secret_type for h in result.hits]}")

asyncio.run(check_output(response_text))
```

Accepts the same parameters and returns the same `SecretsScanResult` as `scan()`.

---

## See also

- [Configuration reference](../configuration.md#secrets-scanning-settings)
- [CLI reference — `secrets scan`](../cli.md#secrets)
- [Runbook — Secrets Scanning](../runbook.md)
- [`spanforge.identity`](identity.md) — identity and JWT audit events
- [`spanforge.redact`](redact.md) — PII detection and redaction
