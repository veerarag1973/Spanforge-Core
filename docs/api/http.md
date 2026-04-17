# spanforge.http — OpenAI-compatible HTTP client

> **Module:** `spanforge.http`  
> **Added in:** 2.0.3

`spanforge.http` provides a zero-dependency, synchronous HTTP client for
OpenAI-compatible chat-completion APIs.  It is intentionally minimal — no
`httpx`, no `requests`, no `aiohttp` — just the stdlib `urllib.request`.

---

## Quick example

```python
from spanforge.http import chat_completion

resp = chat_completion(
    endpoint="https://api.openai.com/v1",
    model="gpt-4o",
    messages=[{"role": "user", "content": "What is the capital of France?"}],
    api_key="sk-...",
)

if resp.ok:
    print(resp.text)          # "Paris"
    print(resp.total_tokens)  # 23
else:
    print("Error:", resp.error)
```

---

## API

### `chat_completion()`

```python
def chat_completion(
    endpoint: str,
    model: str,
    messages: list[dict],
    *,
    api_key: str | None = None,
    timeout: float = 30.0,
    max_retries: int = 3,
    extra_body: dict | None = None,
) -> ChatCompletionResponse: ...
```

Send a single chat-completion request and return a `ChatCompletionResponse`.

| Parameter | Description |
|-----------|-------------|
| `endpoint` | Base URL, e.g. `"https://api.openai.com/v1"`. The path `/chat/completions` is appended automatically. |
| `model` | Model name, e.g. `"gpt-4o"`. |
| `messages` | List of chat message dicts (`role` + `content`). |
| `api_key` | Bearer token. Falls back to the `OPENAI_API_KEY` environment variable. |
| `timeout` | Socket timeout in seconds (default 30). |
| `max_retries` | Maximum number of retry attempts on `429 / 5xx` or network errors. Exponential back-off: `min(2**attempt, 8)` seconds. Default 3. |
| `extra_body` | Additional fields merged into the request JSON body (e.g. `temperature`, `stream`). |

**Returns:** `ChatCompletionResponse`

---

### `ChatCompletionResponse`

```python
@dataclass(frozen=True)
class ChatCompletionResponse:
    text: str
    latency_ms: float
    error: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
```

| Field | Description |
|-------|-------------|
| `text` | The generated text from the first choice, or `""` on error. |
| `latency_ms` | Wall-clock round-trip time in milliseconds. |
| `error` | Error description string, or `None` on success. |
| `prompt_tokens` | Tokens used in the prompt (from the `usage` field). |
| `completion_tokens` | Tokens generated in the completion. |
| `total_tokens` | `prompt_tokens + completion_tokens`. |
| `ok` *(property)* | `True` when `error is None`. |

---

## Retry behaviour

Retries are performed on:
- HTTP status codes `429`, `500`, `502`, `503`, `504`
- `urllib.error.URLError` (network-level failures)
- `OSError` (connection refused, timeouts)

Back-off delay: `min(2**attempt, 8)` seconds (max 8 s).  Non-retryable
status codes (e.g. `400`, `401`, `404`) are returned immediately as an
error response.

---

## Environment variables

| Variable | Effect |
|----------|--------|
| `OPENAI_API_KEY` | Default API key when `api_key` is not supplied. |

---

## SpanForge HTTP server endpoints (Phase 3)

The embedded SpanForge HTTP server (`_server.py`, started via `TraceViewerServer`)
exposes the following additional endpoints added in Phase 3.

### `POST /v1/scan/pii`

> **Added in:** 2.0.3 (Phase 3) — requires API tier or above.

Scan arbitrary text for PII entities using the local sf-pii engine.

**Request body** (JSON):

```json
{
  "text": "Contact alice@example.com or call +1 555-867-5309",
  "language": "en"
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `text` | `string` | *(required)* | The text to scan. Maximum 1 MiB. |
| `language` | `string` | `"en"` | ISO 639-1 language code. |

**Response** (200 OK):

```json
{
  "detected": true,
  "entities": [
    {"type": "EMAIL_ADDRESS", "start": 8, "end": 27, "score": 0.95},
    {"type": "PHONE_NUMBER",  "start": 38, "end": 54, "score": 0.90}
  ],
  "redacted_text": "Contact <EMAIL_ADDRESS> or call <PHONE_NUMBER>"
}
```

**Error responses:**

| Status | Body `error` field | Cause |
|--------|--------------------|-------|
| `400` | `"missing_field: text"` | `text` field absent or empty. |
| `413` | `"request_too_large"` | Body exceeds 1 MiB. |
| `422` | `"PII_DETECTED"` | Pipeline action is `"block"` and PII was found. |
| `500` | `"scan_error: …"` | Engine failure. |

**CLI equivalent:**

```bash
curl -s -X POST http://localhost:8888/v1/scan/pii \
  -H 'Content-Type: application/json' \
  -d '{"text": "alice@example.com"}'
```

---

### `GET /v1/spanforge/status`

> **Added in:** 2.0.3 (Phase 3)

Return the current SpanForge service status, including the `sf_pii` block added
in Phase 3.

**Response** (200 OK):

```json
{
  "status": "ok",
  "version": "2.0.3",
  "sf_pii": {
    "status": "ok",
    "presidio_available": true,
    "entity_types_loaded": ["EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN", "PIPL_NATIONAL_ID"],
    "last_scan_at": "2026-04-17T12:00:00Z"
  }
}
```

The `sf_pii.status` field is `"ok"` when the scan engine is healthy and
`"degraded"` when Presidio is unavailable but the regex fallback is active.

**CLI equivalent:**

```bash
curl -s http://localhost:8888/v1/spanforge/status | python -m json.tool
```
