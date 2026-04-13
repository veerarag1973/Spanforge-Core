"""spanforge.model_registry — Model lifecycle tracking for AI compliance.

Provides a thread-safe in-memory registry of ML/AI models with lifecycle
transitions (active → deprecated → retired).  Each mutation emits an
auditable event into the HMAC chain.

Emits ``model_registry.registered``, ``model_registry.deprecated``,
``model_registry.retired`` events via :func:`emit_rfc_event`.

Usage::

    from spanforge.model_registry import ModelRegistry, ModelRegistryEntry

    registry = ModelRegistry()
    entry = registry.register(
        model_id="gpt-4o-2024-05",
        name="GPT-4o",
        version="2024-05",
        risk_tier="high",
        owner="platform-team",
        purpose="customer support agent",
    )
    registry.deprecate("gpt-4o-2024-05", reason="Replaced by gpt-4o-2024-08")
    registry.retire("gpt-4o-2024-05")
"""

from __future__ import annotations

import json
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

__all__ = [
    "ModelRegistry",
    "ModelRegistryEntry",
    "register_model",
    "deprecate_model",
    "retire_model",
    "list_models",
    "get_model",
]

_VALID_RISK_TIERS = frozenset({"low", "medium", "high", "critical"})
_VALID_STATUSES = frozenset({"active", "deprecated", "retired"})


@dataclass
class ModelRegistryEntry:
    """A single model registered for compliance tracking."""

    model_id: str
    name: str
    version: str
    risk_tier: Literal["low", "medium", "high", "critical"]
    owner: str
    purpose: str
    status: Literal["active", "deprecated", "retired"] = "active"
    deployment_date: str | None = None
    decommission_date: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.model_id:
            raise ValueError("ModelRegistryEntry.model_id must be non-empty")
        if not self.name:
            raise ValueError("ModelRegistryEntry.name must be non-empty")
        if not self.version:
            raise ValueError("ModelRegistryEntry.version must be non-empty")
        if self.risk_tier not in _VALID_RISK_TIERS:
            raise ValueError(
                f"ModelRegistryEntry.risk_tier must be one of {sorted(_VALID_RISK_TIERS)}"
            )
        if not self.owner:
            raise ValueError("ModelRegistryEntry.owner must be non-empty")
        if not self.purpose:
            raise ValueError("ModelRegistryEntry.purpose must be non-empty")
        if self.status not in _VALID_STATUSES:
            raise ValueError(
                f"ModelRegistryEntry.status must be one of {sorted(_VALID_STATUSES)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelRegistryEntry:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ModelRegistry:
    """Thread-safe in-memory model registry with lifecycle transitions.

    Each mutation emits an audit event into the HMAC chain.
    Optionally, the registry can persist to/from a JSON file.
    """

    def __init__(self, *, auto_emit: bool = True) -> None:
        self._lock = threading.Lock()
        self._models: dict[str, ModelRegistryEntry] = {}
        self._auto_emit = auto_emit

    def register(
        self,
        model_id: str,
        name: str,
        version: str,
        risk_tier: Literal["low", "medium", "high", "critical"],
        owner: str,
        purpose: str,
        *,
        deployment_date: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ModelRegistryEntry:
        """Register a new model and emit ``model_registry.registered``."""
        entry = ModelRegistryEntry(
            model_id=model_id,
            name=name,
            version=version,
            risk_tier=risk_tier,
            owner=owner,
            purpose=purpose,
            status="active",
            deployment_date=deployment_date or self._now(),
            metadata=metadata or {},
        )
        with self._lock:
            if model_id in self._models:
                raise ValueError(
                    f"Model {model_id!r} already registered. "
                    "Use a unique model_id or retire the existing entry first."
                )
            self._models[model_id] = entry

        if self._auto_emit:
            self._emit("registered", entry)
        return entry

    def deprecate(self, model_id: str, *, reason: str = "") -> ModelRegistryEntry:
        """Mark a model as deprecated and emit ``model_registry.deprecated``."""
        with self._lock:
            entry = self._models.get(model_id)
            if entry is None:
                raise KeyError(f"Model {model_id!r} not found in registry")
            if entry.status == "retired":
                raise ValueError(f"Model {model_id!r} is already retired")
            entry.status = "deprecated"
            if reason:
                entry.metadata["deprecation_reason"] = reason

        if self._auto_emit:
            self._emit("deprecated", entry)
        return entry

    def retire(self, model_id: str) -> ModelRegistryEntry:
        """Move a model to retired status and emit ``model_registry.retired``."""
        with self._lock:
            entry = self._models.get(model_id)
            if entry is None:
                raise KeyError(f"Model {model_id!r} not found in registry")
            entry.status = "retired"
            entry.decommission_date = self._now()

        if self._auto_emit:
            self._emit("retired", entry)
        return entry

    def get(self, model_id: str) -> ModelRegistryEntry | None:
        """Look up a model entry by ID."""
        with self._lock:
            return self._models.get(model_id)

    def list_all(self) -> list[ModelRegistryEntry]:
        """Return all registered models."""
        with self._lock:
            return list(self._models.values())

    def list_active(self) -> list[ModelRegistryEntry]:
        """Return only models with ``status == 'active'``."""
        with self._lock:
            return [m for m in self._models.values() if m.status == "active"]

    def clear(self) -> None:
        """Remove all entries (for testing)."""
        with self._lock:
            self._models.clear()

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def save(self, path: str | Path) -> None:
        """Persist registry to a JSON file."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            data = [e.to_dict() for e in self._models.values()]
        path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    def load(self, path: str | Path) -> None:
        """Load registry from a JSON file, replacing current entries."""
        path = Path(path)
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = [ModelRegistryEntry.from_dict(d) for d in raw]
        with self._lock:
            self._models = {e.model_id: e for e in entries}

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _now() -> str:
        import datetime  # noqa: PLC0415
        return datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )

    @staticmethod
    def _emit(action: str, entry: ModelRegistryEntry) -> None:
        """Emit a model registry event into the HMAC audit chain."""
        try:
            from spanforge._stream import emit_rfc_event  # noqa: PLC0415
            from spanforge.types import EventType  # noqa: PLC0415

            _action_to_event = {
                "registered": EventType.MODEL_REGISTERED,
                "deprecated": EventType.MODEL_DEPRECATED,
                "retired": EventType.MODEL_RETIRED,
            }
            et = _action_to_event.get(action)
            if et is None:
                return
            try:
                emit_rfc_event(et, entry.to_dict())
            except Exception:  # noqa: BLE001
                pass
        except ImportError:
            pass


# ---------------------------------------------------------------------------
# Module-level singleton & convenience functions
# ---------------------------------------------------------------------------

_registry = ModelRegistry()


def register_model(
    model_id: str,
    name: str,
    version: str,
    risk_tier: Literal["low", "medium", "high", "critical"],
    owner: str,
    purpose: str,
    **kwargs: Any,
) -> ModelRegistryEntry:
    """Register a model via the module-level :class:`ModelRegistry`."""
    return _registry.register(
        model_id, name, version, risk_tier, owner, purpose, **kwargs
    )


def deprecate_model(model_id: str, **kwargs: Any) -> ModelRegistryEntry:
    """Deprecate a model via the module-level :class:`ModelRegistry`."""
    return _registry.deprecate(model_id, **kwargs)


def retire_model(model_id: str) -> ModelRegistryEntry:
    """Retire a model via the module-level :class:`ModelRegistry`."""
    return _registry.retire(model_id)


def list_models() -> list[ModelRegistryEntry]:
    """List all models via the module-level :class:`ModelRegistry`."""
    return _registry.list_all()


def get_model(model_id: str) -> ModelRegistryEntry | None:
    """Get a model via the module-level :class:`ModelRegistry`."""
    return _registry.get(model_id)
