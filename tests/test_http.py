"""Tests for spanforge.http — OpenAI-compatible HTTP client."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from spanforge.http import ChatCompletionResponse, chat_completion


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_response(body: dict, status: int = 200) -> MagicMock:
    """Create a mock urllib response context manager."""
    raw = json.dumps(body).encode()
    resp = MagicMock()
    resp.read.return_value = raw
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def _make_http_error(code: int, body: bytes = b"error") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="http://test/chat/completions",
        code=code,
        msg="error",
        hdrs=MagicMock(),  # type: ignore[arg-type]
        fp=BytesIO(body),
    )


# ---------------------------------------------------------------------------
# ChatCompletionResponse
# ---------------------------------------------------------------------------

class TestChatCompletionResponse:
    def test_ok_true_when_no_error(self):
        resp = ChatCompletionResponse(text="hello", latency_ms=10.0)
        assert resp.ok is True

    def test_ok_false_when_error(self):
        resp = ChatCompletionResponse(text="", latency_ms=5.0, error="HTTP 500")
        assert resp.ok is False

    def test_frozen(self):
        resp = ChatCompletionResponse(text="x", latency_ms=1.0)
        with pytest.raises(Exception):  # frozen dataclass
            resp.text = "y"  # type: ignore[misc]

    def test_defaults(self):
        resp = ChatCompletionResponse(text="hi", latency_ms=0.0)
        assert resp.prompt_tokens == 0
        assert resp.completion_tokens == 0
        assert resp.total_tokens == 0
        assert resp.error is None


# ---------------------------------------------------------------------------
# chat_completion — success path
# ---------------------------------------------------------------------------

class TestChatCompletionSuccess:
    GOOD_BODY = {
        "choices": [{"message": {"content": "Hello, world!"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }

    def test_basic_success(self):
        with patch("urllib.request.urlopen", return_value=_make_response(self.GOOD_BODY)):
            resp = chat_completion(
                endpoint="https://api.test.com/v1",
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
            )
        assert resp.ok
        assert resp.text == "Hello, world!"
        assert resp.prompt_tokens == 10
        assert resp.completion_tokens == 5
        assert resp.total_tokens == 15

    def test_url_constructed_correctly(self):
        captured: list[str] = []

        def _urlopen(req, timeout):
            captured.append(req.full_url)
            return _make_response(self.GOOD_BODY)

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            chat_completion(
                endpoint="https://api.test.com/v1/",  # trailing slash
                model="gpt-4o",
                messages=[],
            )
        assert captured[0] == "https://api.test.com/v1/chat/completions"

    def test_api_key_from_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-key-123")
        captured: list[str] = []

        def _urlopen(req, timeout):
            captured.append(req.get_header("Authorization"))
            return _make_response(self.GOOD_BODY)

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            chat_completion(
                endpoint="https://api.test.com/v1",
                model="gpt-4o",
                messages=[],
            )
        assert captured[0] == "Bearer env-key-123"

    def test_explicit_api_key_overrides_env(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "env-key")
        captured: list[str] = []

        def _urlopen(req, timeout):
            captured.append(req.get_header("Authorization"))
            return _make_response(self.GOOD_BODY)

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            chat_completion(
                endpoint="https://api.test.com/v1",
                model="gpt-4o",
                messages=[],
                api_key="explicit-key",
            )
        assert captured[0] == "Bearer explicit-key"

    def test_extra_body_merged(self):
        captured: list[dict] = []

        def _urlopen(req, timeout):
            captured.append(json.loads(req.data))
            return _make_response(self.GOOD_BODY)

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            chat_completion(
                endpoint="https://api.test.com/v1",
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
                extra_body={"temperature": 0.0, "stream": False},
            )
        body = captured[0]
        assert body["temperature"] == 0.0
        assert body["stream"] is False
        assert body["model"] == "gpt-4o"

    def test_latency_ms_positive(self):
        with patch("urllib.request.urlopen", return_value=_make_response(self.GOOD_BODY)):
            resp = chat_completion(
                endpoint="https://api.test.com/v1",
                model="gpt-4o",
                messages=[],
            )
        assert resp.latency_ms >= 0.0

    def test_missing_usage_returns_zeros(self):
        body = {"choices": [{"message": {"content": "ok"}}]}  # no "usage"
        with patch("urllib.request.urlopen", return_value=_make_response(body)):
            resp = chat_completion(
                endpoint="https://api.test.com/v1",
                model="gpt-4o",
                messages=[],
            )
        assert resp.total_tokens == 0
        assert resp.ok


# ---------------------------------------------------------------------------
# chat_completion — error paths
# ---------------------------------------------------------------------------

class TestChatCompletionErrors:
    def test_http_error_non_retryable(self):
        err = _make_http_error(400, b"bad request")
        with patch("urllib.request.urlopen", side_effect=err):
            resp = chat_completion(
                endpoint="https://api.test.com/v1",
                model="gpt-4o",
                messages=[],
            )
        assert not resp.ok
        assert "400" in resp.error

    def test_http_error_500_no_retry_when_max_retries_0(self):
        call_count = 0

        def _urlopen(req, timeout):
            nonlocal call_count
            call_count += 1
            raise _make_http_error(500)

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            with patch("time.sleep"):
                resp = chat_completion(
                    endpoint="https://api.test.com/v1",
                    model="gpt-4o",
                    messages=[],
                    max_retries=0,
                )
        assert call_count == 1
        assert not resp.ok

    def test_http_error_500_retries_and_succeeds(self):
        good_body = {"choices": [{"message": {"content": "ok"}}]}
        call_count = 0

        def _urlopen(req, timeout):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise _make_http_error(500)
            return _make_response(good_body)

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            with patch("time.sleep"):
                resp = chat_completion(
                    endpoint="https://api.test.com/v1",
                    model="gpt-4o",
                    messages=[],
                    max_retries=3,
                )
        assert call_count == 3
        assert resp.ok

    def test_http_429_retried(self):
        call_count = 0

        def _urlopen(req, timeout):
            nonlocal call_count
            call_count += 1
            raise _make_http_error(429)

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            with patch("time.sleep"):
                resp = chat_completion(
                    endpoint="https://api.test.com/v1",
                    model="gpt-4o",
                    messages=[],
                    max_retries=2,
                )
        assert call_count == 3  # 1 initial + 2 retries
        assert not resp.ok

    def test_network_error_retried(self):
        call_count = 0
        good_body = {"choices": [{"message": {"content": "ok"}}]}

        def _urlopen(req, timeout):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise OSError("network unreachable")
            return _make_response(good_body)

        with patch("urllib.request.urlopen", side_effect=_urlopen):
            with patch("time.sleep"):
                resp = chat_completion(
                    endpoint="https://api.test.com/v1",
                    model="gpt-4o",
                    messages=[],
                    max_retries=1,
                )
        assert call_count == 2
        assert resp.ok

    def test_malformed_response_shape(self):
        body = {"unexpected": "format"}
        with patch("urllib.request.urlopen", return_value=_make_response(body)):
            resp = chat_completion(
                endpoint="https://api.test.com/v1",
                model="gpt-4o",
                messages=[],
            )
        assert not resp.ok
        assert "unexpected response shape" in resp.error

    def test_url_error(self):
        with patch(
            "urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            resp = chat_completion(
                endpoint="https://api.test.com/v1",
                model="gpt-4o",
                messages=[],
            )
        assert not resp.ok
        assert "connection refused" in resp.error
