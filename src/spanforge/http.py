"""spanforge.http — OpenAI-compatible HTTP client with retry and backoff.

Provides a single high-level function :func:`chat_completion` that calls any
OpenAI-compatible ``/chat/completions`` endpoint, with configurable retry,
exponential backoff, timeout, and usage extraction.  Uses only the standard
library (``urllib``) so it adds zero dependencies to the framework.

Usage::

    from spanforge.http import chat_completion

    resp = chat_completion(
        endpoint="https://api.openai.com/v1",
        model="gpt-4o",
        messages=[{"role": "user", "content": "Hello!"}],
        api_key="sk-...",
        max_retries=2,
    )
    if resp.error:
        print("Error:", resp.error)
    else:
        print(resp.text)
        print(f"Tokens used: {resp.total_tokens}")
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "ChatCompletionResponse",
    "chat_completion",
]

# HTTP status codes that are safe to retry.
_RETRYABLE_CODES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class ChatCompletionResponse:
    """Result of a single ``/chat/completions`` call.

    Attributes:
        text:               The assistant message content, or ``""`` on error.
        latency_ms:         Round-trip time in milliseconds.
        error:              Human-readable error string, or ``None`` on success.
        prompt_tokens:      Tokens consumed by the prompt (0 when unavailable).
        completion_tokens:  Tokens in the completion (0 when unavailable).
        total_tokens:       Total tokens for the request (0 when unavailable).

    Example::

        resp = chat_completion(endpoint=..., model=..., messages=...)
        if resp.error is None:
            print(resp.text)
    """

    text: str
    latency_ms: float
    error: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @property
    def ok(self) -> bool:
        """``True`` when the call succeeded (``error is None``)."""
        return self.error is None


def chat_completion(
    endpoint: str,
    model: str,
    messages: list[dict[str, str]],
    *,
    api_key: str = "",
    timeout: int = 30,
    max_retries: int = 0,
    extra_body: dict[str, Any] | None = None,
) -> ChatCompletionResponse:
    """Call an OpenAI-compatible ``/chat/completions`` endpoint.

    On transient HTTP errors (429, 5xx) and network errors the call is retried
    up to *max_retries* times with exponential back-off (``min(2**attempt, 8)``
    seconds between attempts).

    Args:
        endpoint:     Base URL of the API (e.g. ``"https://api.openai.com/v1"``).
                      The path ``/chat/completions`` is appended automatically.
        model:        Model identifier to pass in the request body.
        messages:     List of ``{"role": ..., "content": ...}`` dicts.
        api_key:      Bearer token.  Falls back to ``$OPENAI_API_KEY`` when empty.
        timeout:      Per-attempt timeout in seconds (default 30).
        max_retries:  Number of additional attempts after the first failure
                      (default 0 = no retries).
        extra_body:   Additional top-level keys to merge into the request body
                      (e.g. ``{"temperature": 0.0}``).

    Returns:
        A :class:`ChatCompletionResponse` describing the result.  Check
        :attr:`~ChatCompletionResponse.ok` or
        :attr:`~ChatCompletionResponse.error` before using
        :attr:`~ChatCompletionResponse.text`.

    Example::

        from spanforge.http import chat_completion

        resp = chat_completion(
            endpoint="https://api.openai.com/v1",
            model="gpt-4o",
            messages=[{"role": "user", "content": "Say hello."}],
            api_key="sk-...",
            max_retries=2,
        )
        assert resp.ok
        print(resp.text)
    """
    import os  # noqa: PLC0415 — keep stdlib import local for testability

    resolved_key = api_key or os.environ.get("OPENAI_API_KEY", "")
    url = endpoint.rstrip("/") + "/chat/completions"

    payload: dict[str, Any] = {"model": model, "messages": messages}
    if extra_body:
        payload.update(extra_body)
    data = json.dumps(payload).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {resolved_key}",
    }

    last_error = ""
    for attempt in range(max(0, max_retries) + 1):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body: dict[str, Any] = json.loads(resp.read().decode("utf-8"))
            latency_ms = (time.perf_counter() - t0) * 1000.0
        except urllib.error.HTTPError as exc:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            try:
                detail = exc.read(8192).decode("utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                detail = str(exc)
            last_error = f"HTTP {exc.code}: {detail[:300]}"
            if exc.code in _RETRYABLE_CODES and attempt < max_retries:
                time.sleep(min(2**attempt, 8))
                continue
            return ChatCompletionResponse(text="", latency_ms=latency_ms, error=last_error)
        except (OSError, urllib.error.URLError) as exc:
            latency_ms = (time.perf_counter() - t0) * 1000.0
            last_error = str(exc)
            if attempt < max_retries:
                time.sleep(min(2**attempt, 8))
                continue
            return ChatCompletionResponse(text="", latency_ms=latency_ms, error=last_error)

        usage = body.get("usage") or {}
        try:
            text: str = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            return ChatCompletionResponse(
                text="",
                latency_ms=latency_ms,
                error=f"unexpected response shape: {exc}",
            )

        return ChatCompletionResponse(
            text=text,
            latency_ms=latency_ms,
            error=None,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            total_tokens=int(usage.get("total_tokens", 0)),
        )

    # Exhausted retries without returning (defensive; loop always returns or
    # hits a 'continue' that leads back here)
    return ChatCompletionResponse(text="", latency_ms=0.0, error=last_error)  # pragma: no cover
