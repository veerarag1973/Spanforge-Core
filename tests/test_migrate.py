"""Tests for spanforge.migrate — schema migration utilities.

Covers v1_to_v2 (Event and dict paths), _rehash_md5_to_sha256,
_coerce_tag_values, migrate_file (with org_secret, target_version, dry_run),
and MigrationStats.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from spanforge import Event, EventType
from spanforge.migrate import (
    MigrationStats,
    _coerce_tag_values,
    _rehash_md5_to_sha256,
    migrate_file,
    v1_to_v2,
)
from tests.conftest import FIXED_TIMESTAMP

_SOURCE = "migrate-test@1.0.0"


def _v1_event(**overrides) -> Event:
    """Create a v1 Event for migration tests."""
    defaults = {
        "schema_version": "1.0",
        "event_type": EventType.TRACE_SPAN_COMPLETED,
        "source": _SOURCE,
        "payload": {"model": "gpt-4", "prompt": "hello"},
        "timestamp": FIXED_TIMESTAMP,
        "org_id": "org-1",
        "tags": {"env": "prod", "count": "42"},
    }
    defaults.update(overrides)
    return Event(**defaults)


# ===========================================================================
# _rehash_md5_to_sha256
# ===========================================================================

@pytest.mark.unit
class TestRehashMd5ToSha256:
    def test_md5_checksum_is_recomputed(self):
        payload = {"key": "value"}
        result = _rehash_md5_to_sha256("md5:abc123", payload)
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        expected = f"sha256:{hashlib.sha256(canonical).hexdigest()}"
        assert result == expected

    def test_sha256_checksum_returned_as_is(self):
        result = _rehash_md5_to_sha256("sha256:existing", {"a": 1})
        assert result == "sha256:existing"

    def test_none_checksum_returns_none(self):
        assert _rehash_md5_to_sha256(None, {}) is None

    def test_empty_checksum_returns_empty(self):
        assert _rehash_md5_to_sha256("", {}) == ""


# ===========================================================================
# _coerce_tag_values
# ===========================================================================

@pytest.mark.unit
class TestCoerceTagValues:
    def test_string_values_unchanged(self):
        assert _coerce_tag_values({"a": "b"}) == {"a": "b"}

    def test_numeric_values_coerced_to_strings(self):
        result = _coerce_tag_values({"count": 42, "rate": 3.14})
        assert result == {"count": "42", "rate": "3.14"}

    def test_non_dict_returns_empty(self):
        assert _coerce_tag_values("not-a-dict") == {}
        assert _coerce_tag_values(None) == {}
        assert _coerce_tag_values([1, 2]) == {}


# ===========================================================================
# v1_to_v2 — Event-based migration
# ===========================================================================

@pytest.mark.unit
class TestV1ToV2Event:
    def test_basic_migration(self):
        v1 = _v1_event()
        v2 = v1_to_v2(v1)
        assert v2.schema_version == "2.0"
        assert v2.event_id == v1.event_id

    def test_model_normalised_to_model_id(self):
        v1 = _v1_event(payload={"model": "gpt-4", "prompt": "hi"})
        v2 = v1_to_v2(v1)
        assert "model_id" in v2.payload
        assert "model" not in v2.payload

    def test_already_v2_is_returned_unchanged(self):
        v2_evt = _v1_event(schema_version="2.0")
        result = v1_to_v2(v2_evt)
        assert result is v2_evt

    def test_md5_checksum_rehashed(self):
        v1 = _v1_event(checksum="md5:abc")
        v2 = v1_to_v2(v1)
        assert v2.checksum is not None
        assert v2.checksum.startswith("sha256:")

    def test_tags_coerced_to_strings(self):
        from spanforge import Tags
        v1 = _v1_event(tags=Tags(count="42", env="prod"))
        v2 = v1_to_v2(v1)
        for v in v2.tags.values():
            assert isinstance(v, str)

    def test_none_tags_become_empty_dict(self):
        v1 = _v1_event(tags=None)
        v2 = v1_to_v2(v1)
        assert v2.tags == {} or len(v2.tags) == 0

    def test_org_id_preserved(self):
        v1 = _v1_event(org_id="org-123")
        v2 = v1_to_v2(v1)
        assert v2.org_id == "org-123"

    def test_invalid_type_raises_type_error(self):
        with pytest.raises(TypeError, match="Cannot migrate"):
            v1_to_v2(42)


# ===========================================================================
# v1_to_v2 — dict-based migration
# ===========================================================================

@pytest.mark.unit
class TestV1ToV2Dict:
    def test_basic_dict_migration(self):
        d = {"schema_version": "1.0", "event_id": "e1", "payload": {}}
        result = v1_to_v2(d)
        assert result["schema_version"] == "2.0"
        assert result.get("org_id") is None
        assert result.get("team_id") is None

    def test_dict_already_v2(self):
        d = {"schema_version": "2.0", "event_id": "e1"}
        result = v1_to_v2(d)
        assert result is d

    def test_dict_model_normalised(self):
        d = {
            "schema_version": "1.0",
            "event_id": "e1",
            "payload": {"model": "gpt-4"},
        }
        result = v1_to_v2(d)
        assert result["payload"]["model_id"] == "gpt-4"
        assert "model" not in result["payload"]

    def test_dict_md5_checksum_rehashed(self):
        d = {
            "schema_version": "1.0",
            "event_id": "e1",
            "payload": {"key": "val"},
            "checksum": "md5:old",
        }
        result = v1_to_v2(d)
        assert result["checksum"].startswith("sha256:")

    def test_dict_tags_coerced(self):
        d = {
            "schema_version": "1.0",
            "event_id": "e1",
            "payload": {},
            "tags": {"num": 42, "ok": "yes"},
        }
        result = v1_to_v2(d)
        assert result["tags"]["num"] == "42"
        assert result["tags"]["ok"] == "yes"

    def test_dict_non_dict_tags_become_empty(self):
        d = {
            "schema_version": "1.0",
            "event_id": "e1",
            "payload": {},
            "tags": "not-a-dict",
        }
        result = v1_to_v2(d)
        assert result["tags"] == {}


# ===========================================================================
# migrate_file
# ===========================================================================

@pytest.mark.unit
class TestMigrateFile:
    def _write_jsonl(self, path: Path, events: list[dict]) -> None:
        with path.open("w", encoding="utf-8") as f:
            for e in events:
                f.write(json.dumps(e) + "\n")

    def test_basic_migration(self, tmp_path: Path):
        src = tmp_path / "input.jsonl"
        self._write_jsonl(src, [
            {"schema_version": "1.0", "event_id": "e1", "payload": {}},
            {"schema_version": "1.0", "event_id": "e2", "payload": {}},
        ])
        stats = migrate_file(src, output=tmp_path / "out.jsonl")
        assert stats.total == 2
        assert stats.migrated == 2
        assert stats.skipped == 0
        assert stats.errors == 0
        assert Path(stats.output_path).exists()

    def test_skip_already_v2(self, tmp_path: Path):
        src = tmp_path / "input.jsonl"
        self._write_jsonl(src, [
            {"schema_version": "2.0", "event_id": "e1", "payload": {}},
        ])
        stats = migrate_file(src, output=tmp_path / "out.jsonl")
        assert stats.skipped == 1
        assert stats.migrated == 0

    def test_json_parse_error_counted(self, tmp_path: Path):
        src = tmp_path / "input.jsonl"
        src.write_text("not-json\n", encoding="utf-8")
        stats = migrate_file(src, output=tmp_path / "out.jsonl")
        assert stats.errors == 1
        assert stats.total == 1

    def test_non_object_line_counted_as_error(self, tmp_path: Path):
        src = tmp_path / "input.jsonl"
        src.write_text('"just a string"\n', encoding="utf-8")
        stats = migrate_file(src, output=tmp_path / "out.jsonl")
        assert stats.errors == 1
        assert len(stats.warnings) == 1
        assert "not a JSON object" in stats.warnings[0]

    def test_empty_lines_skipped(self, tmp_path: Path):
        src = tmp_path / "input.jsonl"
        src.write_text('\n\n{"schema_version":"1.0","event_id":"e1","payload":{}}\n\n', encoding="utf-8")
        stats = migrate_file(src, output=tmp_path / "out.jsonl")
        assert stats.total == 1
        assert stats.migrated == 1

    def test_default_output_path(self, tmp_path: Path):
        src = tmp_path / "audit.jsonl"
        self._write_jsonl(src, [
            {"schema_version": "1.0", "event_id": "e1", "payload": {}},
        ])
        stats = migrate_file(src)
        assert stats.output_path.endswith("audit_v2.jsonl")
        assert Path(stats.output_path).exists()

    def test_dry_run_does_not_write(self, tmp_path: Path):
        src = tmp_path / "input.jsonl"
        out = tmp_path / "out.jsonl"
        self._write_jsonl(src, [
            {"schema_version": "1.0", "event_id": "e1", "payload": {}},
        ])
        stats = migrate_file(src, output=out, dry_run=True)
        assert stats.migrated == 1
        assert not out.exists()

    def test_transformed_fields_tracked(self, tmp_path: Path):
        src = tmp_path / "input.jsonl"
        self._write_jsonl(src, [
            {
                "schema_version": "1.0",
                "event_id": "e1",
                "payload": {"model": "gpt-4"},
                "checksum": "md5:abc",
                "tags": {"count": 42},
            },
        ])
        stats = migrate_file(src, output=tmp_path / "out.jsonl")
        assert "payload.model→model_id" in stats.transformed_fields
        assert "checksum.md5→sha256" in stats.transformed_fields
        assert "tags.value_coercion" in stats.transformed_fields

    def test_org_secret_re_signs(self, tmp_path: Path):
        src = tmp_path / "input.jsonl"
        # Use full event dicts so Event.from_dict() succeeds during re-signing
        self._write_jsonl(src, [
            {
                "schema_version": "1.0",
                "event_id": "evt-001",
                "event_type": "llm.trace.span_completed",
                "timestamp": "2026-03-01T12:00:00.000000Z",
                "source": "test@1.0.0",
                "payload": {"a": 1},
            },
            {
                "schema_version": "1.0",
                "event_id": "evt-002",
                "event_type": "llm.trace.span_completed",
                "timestamp": "2026-03-01T12:00:01.000000Z",
                "source": "test@1.0.0",
                "payload": {"b": 2},
            },
        ])
        out = tmp_path / "out.jsonl"
        stats = migrate_file(
            src,
            output=out,
            org_secret="test-secret-key-for-migration-v1234!",
        )
        assert stats.migrated == 2
        # Verify output events have signatures
        lines = out.read_text(encoding="utf-8").strip().split("\n")
        for line in lines:
            data = json.loads(line)
            assert data.get("signature") is not None
            assert data["signature"].startswith("hmac-sha256:")

    def test_target_version_custom(self, tmp_path: Path):
        src = tmp_path / "input.jsonl"
        self._write_jsonl(src, [
            {"schema_version": "1.0", "event_id": "e1", "payload": {}},
        ])
        # target_version "2.0" should proceed with migration
        stats = migrate_file(src, output=tmp_path / "out.jsonl", target_version="2.0")
        assert stats.migrated == 1

    def test_migration_stats_fields(self):
        stats = MigrationStats(
            total=10,
            migrated=5,
            skipped=3,
            errors=2,
            warnings=["w1", "w2"],
            output_path="/tmp/out.jsonl",
            transformed_fields={"checksum.md5→sha256": 3},
        )
        assert stats.total == 10
        assert stats.warnings == ["w1", "w2"]
        assert stats.transformed_fields == {"checksum.md5→sha256": 3}

    def test_migration_stats_defaults(self):
        stats = MigrationStats(total=0, migrated=0, skipped=0, errors=0)
        assert stats.warnings == []
        assert stats.output_path == ""
        assert stats.transformed_fields == {}
