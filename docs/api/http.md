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
