"""spanforge.sdk._base — Infrastructure base classes for the SpanForge service SDK.

Provides:
*  :class:`_CircuitBreaker` — thread-safe circuit breaker (5 failures → OPEN, 30 s reset).
*  :class:`_SlidingWindowRateLimiter` — per-key sliding window rate limiter.
*  :class:`SFClientConfig` — configuration dataclass loaded from env vars.
*  :class:`SFServiceClient` — abstract base with HTTP retry + circuit breaker.

Security requirements
---------------------
*  ``SFClientConfig.api_key`` is a :class:`~spanforge.sdk._types.SecretStr`.
*  HTTP request bodies are sent as application/json; no credentials are ever
   logged.
*  Retry jitter uses :mod:`random` (not :mod:`secrets`) — non-secret values
   only.  Cryptographic randomness is reserved for key generation.
*  TLS verification is enabled by default and only disabled explicitly.
"""

from __future__ import annotations

import abc
import json
import logging
import os
import random
import ssl
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from spanforge.sdk._exceptions import (
    SFAuthError,
    SFRateLimitError,
    SFServiceUnavailableError,
)
from spanforge.sdk._types import RateLimitInfo, SecretStr

__all__ = [
    "SFClientConfig",
    "SFServiceClient",
    "_CircuitBreaker",
    "_SlidingWindowRateLimiter",
]

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------

_CB_THRESHOLD_DEFAULT: int = 5
_CB_RESET_DEFAULT: float = 30.0


class _CircuitBreaker:
    """Thread-safe circuit breaker.

    Transitions:
    * CLOSED → OPEN after *threshold* consecutive failures.
    * OPEN → CLOSED automatically after *reset_seconds* have elapsed.
    * Any call to :meth:`record_success` while OPEN also resets to CLOSED.

    This matches the pattern established in
    :mod:`spanforge._batch_exporter`.
    """

    CLOSED = "closed"
    OPEN = "open"

    def __init__(
        self,
        threshold: int = _CB_THRESHOLD_DEFAULT,
        reset_seconds: float = _CB_RESET_DEFAULT,
    ) -> None:
        self._threshold = threshold
        self._reset_seconds = reset_seconds
        self._failures: int = 0
        self._state: str = self.CLOSED
        self._opened_at: float = 0.0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def state(self) -> str:
        """Return the *current* state, auto-resetting if the reset window has elapsed."""
        with self._lock:
            return self._state_unlocked

    @property
    def _state_unlocked(self) -> str:
        """Inner state check; MUST be called with ``self._lock`` held."""
        if self._state == self.OPEN and time.monotonic() - self._opened_at >= self._reset_seconds:
            self._state = self.CLOSED
            self._failures = 0
        return self._state

    def is_open(self) -> bool:
        """Return ``True`` when the circuit is open (requests should be blocked)."""
        with self._lock:
            return self._state_unlocked == self.OPEN

    def record_success(self) -> None:
        """Reset failure counter and close the circuit."""
        with self._lock:
            self._failures = 0
            self._state = self.CLOSED

    def record_failure(self) -> None:
        """Increment failure counter and open the circuit if the threshold is reached."""
        with self._lock:
            self._failures += 1
            if self._failures >= self._threshold:
                self._state = self.OPEN
                self._opened_at = time.monotonic()

    def reset(self) -> None:
        """Forcibly reset the circuit to CLOSED with zero failures."""
        with self._lock:
            self._failures = 0
            self._state = self.CLOSED
            self._opened_at = 0.0


# ---------------------------------------------------------------------------
# Sliding window rate limiter
# ---------------------------------------------------------------------------


class _SlidingWindowRateLimiter:
    """Thread-safe per-key sliding window rate limiter.

    Args:
        limit: Maximum requests allowed per window.
        window_seconds: Duration of the sliding window in seconds.

    Example::

        limiter = _SlidingWindowRateLimiter(limit=600, window_seconds=60)
        ok = limiter.record("my_key")   # True if within limit
        info = limiter.check("my_key")  # inspect without counting
    """

    def __init__(
        self,
        limit: int = 600,
        window_seconds: float = 60.0,
    ) -> None:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        self._limit = limit
        self._window = window_seconds
        self._windows: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _evict(self, timestamps: deque[float], now: float) -> None:
        """Remove timestamps outside the current window.  NOT thread-safe alone."""
        while timestamps and now - timestamps[0] >= self._window:
            timestamps.popleft()

    def check(self, key_id: str) -> RateLimitInfo:
        """Return rate-limit state without counting the call as a request."""
        with self._lock:
            now = time.monotonic()
            timestamps = self._windows.setdefault(key_id, deque())
            self._evict(timestamps, now)
            remaining = max(0, self._limit - len(timestamps))
            reset_at = datetime.now(timezone.utc)
            return RateLimitInfo(
                limit=self._limit,
                remaining=remaining,
                reset_at=reset_at,
            )

    def record(self, key_id: str) -> bool:
        """Count a request.

        Returns:
            ``True`` if the request is within the limit (allowed).
            ``False`` if the limit has been reached (caller should 429).
        """
        with self._lock:
            now = time.monotonic()
            timestamps = self._windows.setdefault(key_id, deque())
            self._evict(timestamps, now)
            if len(timestamps) >= self._limit:
                return False
            timestamps.append(now)
            return True

    def remaining(self, key_id: str) -> int:
        """Return remaining requests in the current window without counting."""
        info = self.check(key_id)
        return info.remaining

    def clear(self, key_id: str) -> None:
        """Remove all recorded timestamps for *key_id* (e.g. for testing)."""
        with self._lock:
            self._windows.pop(key_id, None)


# ---------------------------------------------------------------------------
# Token-expiry warning threshold (seconds)
# ---------------------------------------------------------------------------

#: Warn / trigger refresh when token TTL drops below this many seconds.
_TOKEN_EXPIRY_WARN_SECS: int = 60

# ---------------------------------------------------------------------------
# Known SPANFORGE_ environment variable names
# ---------------------------------------------------------------------------

_KNOWN_SPANFORGE_VARS: frozenset[str] = frozenset(
    {
        "SPANFORGE_ENDPOINT",
        "SPANFORGE_API_KEY",
        "SPANFORGE_PROJECT_ID",
        "SPANFORGE_TIMEOUT_MS",
        "SPANFORGE_MAX_RETRIES",
        "SPANFORGE_LOCAL_FALLBACK",
        "SPANFORGE_TLS_VERIFY",
        "SPANFORGE_PROXY",
        "SPANFORGE_SIGNING_KEY",
        "SPANFORGE_MAGIC_SECRET",
    }
)

_cfg_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Client configuration
# ---------------------------------------------------------------------------


@dataclass
class SFClientConfig:
    """Configuration for a SpanForge service client.

    All fields have sensible defaults.  When ``endpoint`` is empty the client
    operates in *local mode* — all logic is executed in-process with no
    network calls.

    Attributes:
        endpoint: Base URL of the SpanForge service
            (e.g. ``"https://api.spanforge.dev"``).
            **Empty string** enables local/fallback mode.
        api_key: SpanForge API key.  Must be :class:`~spanforge.sdk._types.SecretStr`.
        project_id: Default project scope for new keys.
        timeout_ms: HTTP timeout in milliseconds (default: 2 000 ms).
        max_retries: Number of additional attempts after the first failure
            (default: 3; so 4 total attempts).
        local_fallback_enabled: If ``True`` (default), fall back to local
            logic when the remote service is unreachable.
        tls_verify: Verify TLS certificates (default: ``True``).
            **Never set to ``False`` in production.**
        proxy: Optional HTTP/HTTPS proxy URL.
        signing_key: Secret used for local HS256 JWT signing.  Loaded from
            ``SPANFORGE_SIGNING_KEY`` env var if not set here.
        magic_secret: Secret for HMAC magic-link tokens.  Loaded from
            ``SPANFORGE_MAGIC_SECRET`` env var if not set here.
    """

    endpoint: str = ""
    api_key: SecretStr = field(default_factory=lambda: SecretStr(""))
    project_id: str = ""
    timeout_ms: int = 2_000
    max_retries: int = 3
    local_fallback_enabled: bool = True
    tls_verify: bool = True
    proxy: str | None = None
    signing_key: str = ""
    magic_secret: str = ""

    @classmethod
    def from_env(cls) -> SFClientConfig:
        """Build a config from environment variables.

        Variable mapping::

            SPANFORGE_ENDPOINT            → endpoint
            SPANFORGE_API_KEY             → api_key
            SPANFORGE_PROJECT_ID          → project_id
            SPANFORGE_TIMEOUT_MS          → timeout_ms
            SPANFORGE_MAX_RETRIES         → max_retries
            SPANFORGE_LOCAL_FALLBACK      → local_fallback_enabled
            SPANFORGE_TLS_VERIFY          → tls_verify
            SPANFORGE_PROXY               → proxy
            SPANFORGE_SIGNING_KEY         → signing_key
            SPANFORGE_MAGIC_SECRET        → magic_secret
        """
        raw_fallback = os.environ.get("SPANFORGE_LOCAL_FALLBACK", "true").lower()
        local_fallback = raw_fallback not in ("false", "0", "no")

        raw_tls = os.environ.get("SPANFORGE_TLS_VERIFY", "true").lower()
        tls_verify = raw_tls not in ("false", "0", "no")

        # ID-005: Warn on unknown SPANFORGE_* env vars
        for env_key in os.environ:
            if env_key.startswith("SPANFORGE_") and env_key not in _KNOWN_SPANFORGE_VARS:
                _cfg_log.warning(
                    "Unknown SPANFORGE_ environment variable: %r — this variable "
                    "is not recognised by the SpanForge SDK and will be ignored.",
                    env_key,
                )

        return cls(
            endpoint=os.environ.get("SPANFORGE_ENDPOINT", ""),
            api_key=SecretStr(os.environ.get("SPANFORGE_API_KEY", "")),
            project_id=os.environ.get("SPANFORGE_PROJECT_ID", ""),
            timeout_ms=int(os.environ.get("SPANFORGE_TIMEOUT_MS", "2000")),
            max_retries=int(os.environ.get("SPANFORGE_MAX_RETRIES", "3")),
            local_fallback_enabled=local_fallback,
            tls_verify=tls_verify,
            proxy=os.environ.get("SPANFORGE_PROXY"),
            signing_key=os.environ.get("SPANFORGE_SIGNING_KEY", ""),
            magic_secret=os.environ.get("SPANFORGE_MAGIC_SECRET", ""),
        )


# ---------------------------------------------------------------------------
# Abstract service client base
# ---------------------------------------------------------------------------


_HTTP_429: int = 429
_HTTP_401_403: frozenset[int] = frozenset({401, 403})


class SFServiceClient(abc.ABC):
    """Abstract base class for SpanForge service clients.

    Provides:
    *  Circuit breaker (5-failure threshold, 30 s reset).
    *  Retry with exponential back-off and random jitter.
    *  Structured error translation (429 → :exc:`~spanforge.sdk._exceptions.SFRateLimitError`,
       401/403 → :exc:`~spanforge.sdk._exceptions.SFAuthError`).
    *  Local-mode detection via :meth:`_is_local_mode`.

    Concrete subclasses implement service-specific methods; they call
    :meth:`_request` for remote operations and fall back to local in-process
    logic when :meth:`_is_local_mode` returns ``True``.
    """

    def __init__(
        self,
        config: SFClientConfig,
        service_name: str,
    ) -> None:
        self._config = config
        self._service_name = service_name
        self._circuit_breaker = _CircuitBreaker(
            threshold=_CB_THRESHOLD_DEFAULT,
            reset_seconds=_CB_RESET_DEFAULT,
        )
        # Install proxy handler if configured
        if config.proxy:
            proxy_handler = urllib.request.ProxyHandler(
                {"http": config.proxy, "https": config.proxy}
            )
            opener = urllib.request.build_opener(proxy_handler)
            urllib.request.install_opener(opener)

    # ------------------------------------------------------------------
    # ID-003: Token refresh hook (subclasses override)
    # ------------------------------------------------------------------

    def _on_token_near_expiry(self, seconds_remaining: int) -> None:
        """Called when the auth token is about to expire.

        Triggered when the ``X-SF-Token-Expires`` response header reports fewer
        than ``_TOKEN_EXPIRY_WARN_SECS`` seconds until expiry.  The default
        implementation emits a warning log.  :class:`SFIdentityClient` overrides
        this to perform an inline token refresh (ID-003).

        Args:
            seconds_remaining: Seconds until token expiry per the response header.
        """
        _log.warning(
            "sf-%s auth token expires in %ds; consider calling refresh_token()",
            self._service_name,
            seconds_remaining,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_local_mode(self) -> bool:
        """Return ``True`` when no service endpoint is configured."""
        return not self._config.endpoint.strip()

    def _build_opener(self) -> urllib.request.OpenerDirector:
        """Build a URL opener, optionally with proxy support."""
        handlers: list[urllib.request.BaseHandler] = []
        if not self._config.tls_verify:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            handlers.append(urllib.request.HTTPSHandler(context=ctx))
        if self._config.proxy:
            handlers.append(
                urllib.request.ProxyHandler(
                    {"http": self._config.proxy, "https": self._config.proxy}
                )
            )
        return urllib.request.build_opener(*handlers) if handlers else urllib.request.build_opener()

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Make an authenticated JSON request to the remote service.

        Behaviour:
        * If the circuit breaker is OPEN, raises
          :exc:`~spanforge.sdk._exceptions.SFServiceUnavailableError`
          immediately without making a network call.
        * On ``429`` responses, raises
          :exc:`~spanforge.sdk._exceptions.SFRateLimitError` with
          ``Retry-After`` seconds.
        * On ``401``/``403`` responses, raises
          :exc:`~spanforge.sdk._exceptions.SFAuthError`.
        * On other failures, retries up to ``config.max_retries`` times with
          exponential back-off + jitter, then raises
          :exc:`~spanforge.sdk._exceptions.SFServiceUnavailableError` (if
          ``local_fallback_enabled=False``) or re-raises the last exception.

        Security:
        * The ``X-SF-API-Key`` header carries the raw key value only.  The
          value is never logged here.
        * Request bodies are JSON-serialised; no sensitive fields should
          appear in ``body`` (callers are responsible for that).
        """
        if self._circuit_breaker.is_open():
            raise SFServiceUnavailableError(self._service_name)

        url = f"{self._config.endpoint.rstrip('/')}{path}"
        api_key_value = self._config.api_key.get_secret_value()
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-SF-API-Key": api_key_value,
        }
        encoded_body: bytes | None = (
            json.dumps(body, separators=(",", ":")).encode() if body else None
        )

        last_exc: Exception | None = None
        total_attempts = self._config.max_retries + 1

        opener = self._build_opener()

        for attempt in range(total_attempts):
            if attempt > 0:
                # Exponential back-off: 0.5, 1.0, 2.0, … up to 10 s + jitter
                delay = min(0.5 * (2**attempt), 10.0) + random.uniform(0.0, 0.1)  # nosec B311 -- timing jitter only, not crypto
                time.sleep(delay)

            try:
                req = urllib.request.Request(
                    url,
                    data=encoded_body,
                    headers=headers,
                    method=method.upper(),
                )
                timeout_s = self._config.timeout_ms / 1_000.0
                with opener.open(req, timeout=timeout_s) as resp:
                    # ID-003: Check token expiry header and call refresh hook
                    token_expires_header = resp.headers.get("X-SF-Token-Expires")
                    if token_expires_header:
                        try:
                            token_ttl = int(token_expires_header)
                            if token_ttl < _TOKEN_EXPIRY_WARN_SECS:
                                self._on_token_near_expiry(token_ttl)
                        except (ValueError, TypeError):
                            pass
                    raw = resp.read()
                    self._circuit_breaker.record_success()
                    return json.loads(raw) if raw else {}

            except urllib.error.HTTPError as exc:
                if exc.code == _HTTP_429:
                    retry_after = int(exc.headers.get("Retry-After", "60"))
                    raise SFRateLimitError(retry_after) from exc
                if exc.code in _HTTP_401_403:
                    raise SFAuthError(f"HTTP {exc.code} from sf-{self._service_name}") from exc
                _log.debug(
                    "sf-%s request failed (attempt %d/%d): HTTP %s",
                    self._service_name,
                    attempt + 1,
                    total_attempts,
                    exc.code,
                )
                self._circuit_breaker.record_failure()
                last_exc = exc

            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                _log.debug(
                    "sf-%s request failed (attempt %d/%d): %s",
                    self._service_name,
                    attempt + 1,
                    total_attempts,
                    type(exc).__name__,
                )
                self._circuit_breaker.record_failure()
                last_exc = exc

        # All retries exhausted
        if not self._config.local_fallback_enabled:
            raise SFServiceUnavailableError(self._service_name)

        # Caller should handle the fallback in local mode
        _log.warning(
            "sf-%s unreachable after %d attempt(s); falling back to local mode",
            self._service_name,
            total_attempts,
        )
        if last_exc is not None:
            raise last_exc
        raise SFServiceUnavailableError(self._service_name)  # pragma: no cover
