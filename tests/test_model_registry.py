"""Tests for spanforge.model_registry — Model lifecycle tracking."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from spanforge.model_registry import (
    ModelRegistry,
    ModelRegistryEntry,
    deprecate_model,
    get_model,
    list_models,
    register_model,
    retire_model,
)

# ---------------------------------------------------------------------------
# ModelRegistryEntry tests
# ---------------------------------------------------------------------------


class TestModelRegistryEntry:
    """ModelRegistryEntry dataclass validation and serialization."""

    @pytest.mark.unit
    def test_valid_entry_creation(self):
        e = ModelRegistryEntry(
            model_id="gpt-4o",
            name="GPT-4o",
            version="2024-05",
            risk_tier="high",
            owner="platform",
            purpose="customer support",
        )
        assert e.model_id == "gpt-4o"
        assert e.status == "active"

    @pytest.mark.unit
    def test_round_trip(self):
        e = ModelRegistryEntry(
            model_id="m1",
            name="Model-1",
            version="1.0",
            risk_tier="low",
            owner="team-a",
            purpose="classification",
            metadata={"framework": "pytorch"},
        )
        d = e.to_dict()
        e2 = ModelRegistryEntry.from_dict(d)
        assert e2.model_id == e.model_id
        assert e2.metadata == {"framework": "pytorch"}

    @pytest.mark.unit
    def test_empty_model_id_raises(self):
        with pytest.raises(ValueError, match="model_id"):
            ModelRegistryEntry(
                model_id="",
                name="X",
                version="1",
                risk_tier="low",
                owner="o",
                purpose="p",
            )

    @pytest.mark.unit
    def test_empty_name_raises(self):
        with pytest.raises(ValueError, match="name"):
            ModelRegistryEntry(
                model_id="m1",
                name="",
                version="1",
                risk_tier="low",
                owner="o",
                purpose="p",
            )

    @pytest.mark.unit
    def test_invalid_risk_tier_raises(self):
        with pytest.raises(ValueError, match="risk_tier"):
            ModelRegistryEntry(
                model_id="m1",
                name="X",
                version="1",
                risk_tier="extreme",
                owner="o",
                purpose="p",
            )

    @pytest.mark.unit
    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="status"):
            ModelRegistryEntry(
                model_id="m1",
                name="X",
                version="1",
                risk_tier="low",
                owner="o",
                purpose="p",
                status="suspended",
            )

    @pytest.mark.unit
    def test_empty_owner_raises(self):
        with pytest.raises(ValueError, match="owner"):
            ModelRegistryEntry(
                model_id="m1",
                name="X",
                version="1",
                risk_tier="low",
                owner="",
                purpose="p",
            )

    @pytest.mark.unit
    def test_empty_purpose_raises(self):
        with pytest.raises(ValueError, match="purpose"):
            ModelRegistryEntry(
                model_id="m1",
                name="X",
                version="1",
                risk_tier="low",
                owner="o",
                purpose="",
            )


# ---------------------------------------------------------------------------
# ModelRegistry tests
# ---------------------------------------------------------------------------


class TestModelRegistry:
    """ModelRegistry thread-safe lifecycle management."""

    def setup_method(self):
        self.registry = ModelRegistry(auto_emit=False)

    @pytest.mark.unit
    def test_register_and_get(self):
        entry = self.registry.register(
            "m1", "Model-1", "1.0", "low", "team-a", "classification"
        )
        assert entry.status == "active"
        assert self.registry.get("m1") is not None

    @pytest.mark.unit
    def test_register_duplicate_raises(self):
        self.registry.register("m1", "X", "1", "low", "o", "p")
        with pytest.raises(ValueError, match="already registered"):
            self.registry.register("m1", "X", "2", "low", "o", "p")

    @pytest.mark.unit
    def test_deprecate(self):
        self.registry.register("m1", "X", "1", "low", "o", "p")
        entry = self.registry.deprecate("m1", reason="replaced")
        assert entry.status == "deprecated"
        assert entry.metadata["deprecation_reason"] == "replaced"

    @pytest.mark.unit
    def test_deprecate_nonexistent_raises(self):
        with pytest.raises(KeyError, match="not found"):
            self.registry.deprecate("ghost")

    @pytest.mark.unit
    def test_deprecate_retired_raises(self):
        self.registry.register("m1", "X", "1", "low", "o", "p")
        self.registry.retire("m1")
        with pytest.raises(ValueError, match="already retired"):
            self.registry.deprecate("m1")

    @pytest.mark.unit
    def test_retire(self):
        self.registry.register("m1", "X", "1", "low", "o", "p")
        entry = self.registry.retire("m1")
        assert entry.status == "retired"
        assert entry.decommission_date is not None

    @pytest.mark.unit
    def test_retire_nonexistent_raises(self):
        with pytest.raises(KeyError, match="not found"):
            self.registry.retire("ghost")

    @pytest.mark.unit
    def test_list_all(self):
        self.registry.register("m1", "A", "1", "low", "o", "p")
        self.registry.register("m2", "B", "1", "high", "o", "p")
        assert len(self.registry.list_all()) == 2

    @pytest.mark.unit
    def test_list_active(self):
        self.registry.register("m1", "A", "1", "low", "o", "p")
        self.registry.register("m2", "B", "1", "high", "o", "p")
        self.registry.deprecate("m1")
        active = self.registry.list_active()
        assert len(active) == 1
        assert active[0].model_id == "m2"

    @pytest.mark.unit
    def test_clear(self):
        self.registry.register("m1", "A", "1", "low", "o", "p")
        self.registry.clear()
        assert self.registry.list_all() == []

    @pytest.mark.unit
    def test_get_nonexistent_returns_none(self):
        assert self.registry.get("ghost") is None

    @pytest.mark.unit
    def test_save_and_load(self):
        self.registry.register("m1", "A", "1", "low", "o", "p")
        self.registry.register("m2", "B", "2", "high", "o2", "p2")
        self.registry.deprecate("m1")

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "registry.json"
            self.registry.save(path)

            # Verify file is valid JSON
            data = json.loads(path.read_text(encoding="utf-8"))
            assert len(data) == 2

            # Load into a new registry
            new_reg = ModelRegistry(auto_emit=False)
            new_reg.load(path)
            assert len(new_reg.list_all()) == 2
            m1 = new_reg.get("m1")
            assert m1 is not None
            assert m1.status == "deprecated"

    @pytest.mark.unit
    def test_full_lifecycle(self):
        """Register → deprecate → retire full cycle."""
        self.registry.register("m1", "A", "1", "medium", "o", "p")
        assert self.registry.get("m1").status == "active"
        self.registry.deprecate("m1", reason="replaced by m2")
        assert self.registry.get("m1").status == "deprecated"
        self.registry.retire("m1")
        assert self.registry.get("m1").status == "retired"


# ---------------------------------------------------------------------------
# Module-level convenience function tests
# ---------------------------------------------------------------------------


class TestModelRegistryConvenienceFunctions:
    """Module-level register_model / deprecate_model / retire_model / etc."""

    @pytest.mark.unit
    def test_register_and_get_cycle(self):
        from spanforge.model_registry import _registry
        _registry.clear()

        register_model("conv-m1", "ConvModel", "1.0", "low", "team", "testing")
        m = get_model("conv-m1")
        assert m is not None
        assert m.status == "active"

        models = list_models()
        assert any(m.model_id == "conv-m1" for m in models)

        deprecate_model("conv-m1", reason="old")
        assert get_model("conv-m1").status == "deprecated"

        retire_model("conv-m1")
        assert get_model("conv-m1").status == "retired"
