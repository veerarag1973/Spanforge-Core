"""spanforge.sdk.registry - ServiceRegistry singleton (Phase 9, CFG-010-013).

Implements:

* CFG-010: Thread-safe :class:`ServiceRegistry` singleton holding references
  to all 8 service clients.  ``registry.get("sf_pii") -> SFPIIClient``.
* CFG-011: :meth:`ServiceRegistry.run_startup_check` — pings all enabled
  services on first use.  Status per service: ``up``, ``degraded``
  (latency > 2 s), or ``down`` (unreachable).  If any service is ``down``
  and ``local_fallback.enabled=False`` → raises
  :exc:`~spanforge.sdk._exceptions.SFStartupError`.
* CFG-012: :meth:`ServiceRegistry.status_response` — returns a dict
  matching the ``GET /v1/spanforge/status`` specification (per spec §6).
  Each service entry includes ``{status, latency_ms, last_checked_at}``.
* CFG-013: :meth:`ServiceRegistry.start_background_checker` — launches a
  daemon thread that re-checks all services every 60 s.  Status changes
  are logged at ``WARNING``; recovery (down → up) logged at ``INFO``.

Security requirements
---------------------
* Credentials are never included in health-check payloads or log messages.
* The background thread is a daemon thread and does not prevent process exit.
* Thread safety is guaranteed via :class:`threading.Lock` guards on all
  shared state.
"""

from __future__ import annotations

import logging
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from spanforge.sdk._exceptions import SFStartupError

__all__ = [
    "ServiceHealth",
    "ServiceRegistry",
    "ServiceStatus",
]

_log = logging.getLogger(__name__)

# The 8 canonical service names (ordered for consistent logging)
_SERVICE_NAMES: tuple[str, ...] = (
    "sf_pii",
    "sf_secrets",
    "sf_audit",
    "sf_observe",
    "sf_gate",
    "sf_cec",
    "sf_identity",
    "sf_alert",
)

# Latency threshold above which a service is reported as "degraded" (CFG-011)
_DEGRADED_LATENCY_MS: float = 2_000.0

# Default health-check path appended to the service endpoint
_HEALTH_PATH: str = "/health"

# HTTP 200 OK status code
_HTTP_OK: int = 200


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


class ServiceStatus(str, Enum):
    """Status of a single service endpoint."""

    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass
class ServiceHealth:
    """Point-in-time health snapshot for one service.

    Attributes:
        status: Current service status.
        latency_ms: Round-trip latency of the last health check in
            milliseconds.  ``-1`` when the service was not checked or
            is ``down``.
        last_checked_at: UTC timestamp of the last health check, or
            ``None`` if no check has been performed yet.
    """

    status: ServiceStatus = ServiceStatus.DOWN
    latency_ms: float = -1.0
    last_checked_at: datetime | None = None


# ---------------------------------------------------------------------------
# ServiceRegistry
# ---------------------------------------------------------------------------


class ServiceRegistry:
    """Thread-safe singleton registry of all 8 SpanForge service clients.

    Usage::

        registry = ServiceRegistry.get_instance()
        registry.register("sf_pii", sf_pii_client)
        client = registry.get("sf_pii")

        # Run connectivity checks (CFG-011)
        registry.run_startup_check()

        # GET /v1/spanforge/status payload (CFG-012)
        status = registry.status_response()

    Only one :class:`ServiceRegistry` instance exists per process; subsequent
    calls to :meth:`get_instance` return the same object.
    """

    _instance: ServiceRegistry | None = None
    _instance_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}
        self._health: dict[str, ServiceHealth] = {
            name: ServiceHealth() for name in _SERVICE_NAMES
        }
        self._health_lock = threading.RLock()
        self._bg_thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Singleton
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> ServiceRegistry:
        """Return the process-wide singleton.

        Creates it on first call.  Thread-safe via double-checked locking.
        """
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def _reset_for_testing(cls) -> None:
        """Reset the singleton — use only in tests."""
        with cls._instance_lock:
            if cls._instance is not None:
                cls._instance._stop_event.set()
            cls._instance = None

    # ------------------------------------------------------------------
    # Client management (CFG-010)
    # ------------------------------------------------------------------

    def register(self, name: str, client: Any) -> None:
        """Register a service client under ``name``.

        Args:
            name: Service name, e.g. ``"sf_pii"``.
            client: The instantiated service client.
        """
        self._clients[name] = client

    def get(self, name: str) -> Any:
        """Return the registered client for ``name``, or ``None``.

        Args:
            name: Service name, e.g. ``"sf_pii"``.

        Returns:
            The client object, or ``None`` if not registered.
        """
        return self._clients.get(name)

    def register_all(self, clients: dict[str, Any]) -> None:
        """Bulk-register multiple clients.

        Args:
            clients: Mapping of ``{service_name: client}``.
        """
        for name, client in clients.items():
            self._clients[name] = client

    # ------------------------------------------------------------------
    # Health management
    # ------------------------------------------------------------------

    def _check_service(self, name: str, endpoint: str, timeout_ms: int) -> ServiceHealth:
        """Ping one service health endpoint and return a :class:`ServiceHealth`.

        Args:
            name: Service name (for logging).
            endpoint: Base URL of the service.
            timeout_ms: Request timeout in milliseconds.

        Returns:
            :class:`ServiceHealth` with status/latency/timestamp populated.
        """
        if not endpoint:
            # No endpoint configured → local mode → treat as UP
            return ServiceHealth(
                status=ServiceStatus.UP,
                latency_ms=0.0,
                last_checked_at=datetime.now(timezone.utc),
            )

        url = endpoint.rstrip("/") + _HEALTH_PATH
        timeout_s = max(timeout_ms / 1000.0, 0.1)
        start = time.monotonic()
        try:
            with urllib.request.urlopen(url, timeout=timeout_s) as resp:  # noqa: S310  # nosec B310
                elapsed_ms = (time.monotonic() - start) * 1000
                if resp.status == _HTTP_OK:
                    status = (
                        ServiceStatus.DEGRADED
                        if elapsed_ms > _DEGRADED_LATENCY_MS
                        else ServiceStatus.UP
                    )
                    return ServiceHealth(
                        status=status,
                        latency_ms=elapsed_ms,
                        last_checked_at=datetime.now(timezone.utc),
                    )
                return ServiceHealth(
                    status=ServiceStatus.DOWN,
                    latency_ms=(time.monotonic() - start) * 1000,
                    last_checked_at=datetime.now(timezone.utc),
                )
        except Exception:
            elapsed_ms = (time.monotonic() - start) * 1000
            return ServiceHealth(
                status=ServiceStatus.DOWN,
                latency_ms=elapsed_ms,
                last_checked_at=datetime.now(timezone.utc),
            )

    # ------------------------------------------------------------------
    # CFG-011: Startup connectivity check
    # ------------------------------------------------------------------

    def run_startup_check(
        self,
        endpoint: str = "",
        *,
        enabled_services: set[str] | None = None,
        local_fallback_enabled: bool = True,
        timeout_ms: int = 2000,
    ) -> dict[str, ServiceHealth]:
        """Ping all enabled services and update the health registry.

        Logs a summary table at ``INFO`` level.  If any service is ``down``
        and ``local_fallback_enabled`` is ``False``, raises
        :exc:`~spanforge.sdk._exceptions.SFStartupError`.

        Args:
            endpoint: Base service URL (same endpoint for all services when
                using a single SpanForge gateway).
            enabled_services: Set of enabled service names.  ``None`` means
                all 8 services.
            local_fallback_enabled: If ``False``, a ``down`` service raises
                immediately.
            timeout_ms: Per-service health-check timeout in milliseconds.

        Returns:
            A ``{service_name: ServiceHealth}`` dict.

        Raises:
            :exc:`~spanforge.sdk._exceptions.SFStartupError`: When any
                enabled service is ``down`` and fallback is disabled.
        """
        active = set(enabled_services) if enabled_services is not None else set(_SERVICE_NAMES)
        results: dict[str, ServiceHealth] = {}

        for name in _SERVICE_NAMES:
            if name not in active:
                continue
            health = self._check_service(name, endpoint, timeout_ms)
            results[name] = health
            with self._health_lock:
                self._health[name] = health

        # Log summary table
        _log.info("SpanForge service health check:")
        for name, h in results.items():
            _log.info("  %-14s  %-8s  %.0f ms", name, h.status.value, max(h.latency_ms, 0))

        # Enterprise gate — raise on unreachable service if fallback disabled
        if not local_fallback_enabled:
            down = [n for n, h in results.items() if h.status == ServiceStatus.DOWN]
            if down:
                raise SFStartupError(down)

        return results

    # ------------------------------------------------------------------
    # CFG-012: /v1/spanforge/status payload
    # ------------------------------------------------------------------

    def status_response(self) -> dict[str, dict[str, Any]]:
        """Return a JSON-serialisable dict for ``GET /v1/spanforge/status``.

        Each service entry contains::

            {
              "status": "up" | "degraded" | "down",
              "latency_ms": <float>,
              "last_checked_at": "<ISO-8601 UTC>" | null,
            }

        Returns:
            A dict keyed by service name.
        """
        with self._health_lock:
            snapshot = dict(self._health)

        return {
            name: {
                "status": h.status.value,
                "latency_ms": h.latency_ms,
                "last_checked_at": (
                    h.last_checked_at.isoformat() if h.last_checked_at else None
                ),
            }
            for name, h in snapshot.items()
        }

    def get_health(self, name: str) -> ServiceHealth:
        """Return the latest :class:`ServiceHealth` for one service.

        Args:
            name: Service name, e.g. ``"sf_pii"``.

        Returns:
            The most recently recorded :class:`ServiceHealth`.
        """
        with self._health_lock:
            return self._health.get(name, ServiceHealth())

    def update_health(self, name: str, health: ServiceHealth) -> None:
        """Directly set the health for ``name`` (used by tests and fallbacks).

        Args:
            name: Service name.
            health: New :class:`ServiceHealth` value.
        """
        with self._health_lock:
            self._health[name] = health

    # ------------------------------------------------------------------
    # CFG-013: Background health re-check
    # ------------------------------------------------------------------

    def start_background_checker(
        self,
        endpoint: str = "",
        interval: float = 60.0,
        timeout_ms: int = 2000,
    ) -> None:
        """Start a daemon thread that re-checks all services every ``interval`` seconds.

        Status changes are logged at ``WARNING``.  Recovery (``down`` → ``up``)
        is logged at ``INFO``.  The thread stops automatically when the process
        exits (daemon=True) or when :meth:`stop_background_checker` is called.

        Args:
            endpoint: Service endpoint URL passed to each health check.
            interval: Seconds between checks (default: ``60``).
            timeout_ms: Per-service HTTP timeout in milliseconds.
        """
        if self._bg_thread is not None and self._bg_thread.is_alive():
            return  # already running

        self._stop_event.clear()

        def _loop() -> None:
            while not self._stop_event.wait(timeout=interval):
                self._run_background_check(endpoint, timeout_ms)

        self._bg_thread = threading.Thread(target=_loop, daemon=True, name="sf-health-checker")
        self._bg_thread.start()
        _log.debug("SpanForge background health checker started (interval=%.0fs)", interval)

    def stop_background_checker(self) -> None:
        """Signal the background health-check thread to stop."""
        self._stop_event.set()

    def _run_background_check(self, endpoint: str, timeout_ms: int) -> None:
        """Run one iteration of the background health check (CFG-013)."""
        for name in _SERVICE_NAMES:
            prev_health = self.get_health(name)
            new_health = self._check_service(name, endpoint, timeout_ms)

            prev_status = prev_health.status
            new_status = new_health.status

            with self._health_lock:
                self._health[name] = new_health

            if prev_status != new_status:
                if new_status == ServiceStatus.DOWN:
                    _log.warning(
                        "sf-%s status changed: %s → %s",
                        name,
                        prev_status.value,
                        new_status.value,
                    )
                elif prev_status == ServiceStatus.DOWN and new_status in (
                    ServiceStatus.UP,
                    ServiceStatus.DEGRADED,
                ):
                    _log.info(
                        "sf-%s recovered: %s → %s",
                        name,
                        prev_status.value,
                        new_status.value,
                    )
                else:
                    _log.warning(
                        "sf-%s status changed: %s → %s",
                        name,
                        prev_status.value,
                        new_status.value,
                    )
