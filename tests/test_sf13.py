"""SF-13 — Tamper-Evident Append-Only Export acceptance tests."""

from __future__ import annotations

import json

import pytest

from spanforge import Event, EventType
from spanforge.exceptions import AuditStorageError
from spanforge.export.append_only import (
    AppendOnlyJSONLExporter,
    WORMBackend,
)

_SOURCE = "test-sf13@1.0.0"


def _make_event(**kw):
    defaults = {
        "event_type": EventType.TRACE_SPAN_COMPLETED,
        "source": _SOURCE,
        "payload": {"span_name": "run", "status": "ok"},
    }
    defaults.update(kw)
    return Event(**defaults)


# ---- SF-13-A: write_exclusive + public rotate ----

class TestSF13A:
    """SF-13-A: ``write_exclusive()`` and public ``rotate()``."""

    @pytest.mark.unit
    def test_write_exclusive_allows_new_path(self, tmp_path):
        exporter = AppendOnlyJSONLExporter(
            str(tmp_path / "audit.jsonl"), org_secret="test-key", source=_SOURCE,
        )
        target = tmp_path / "exclusive.jsonl"
        # Should NOT raise when path does not exist
        exporter.write_exclusive(target)

    @pytest.mark.unit
    def test_write_exclusive_raises_on_existing(self, tmp_path):
        exporter = AppendOnlyJSONLExporter(
            str(tmp_path / "audit.jsonl"), org_secret="test-key", source=_SOURCE,
        )

        target = tmp_path / "existing.jsonl"
        target.write_text("occupied", encoding="utf-8")
        with pytest.raises(AuditStorageError):
            exporter.write_exclusive(target)

    @pytest.mark.unit
    def test_public_rotate(self, tmp_path):
        path = tmp_path / "audit.jsonl"
        exporter = AppendOnlyJSONLExporter(
            str(path), org_secret="test-key", source=_SOURCE,
        )
        event = _make_event()
        exporter.append(event)
        # Force rotation regardless of file size
        exporter.rotate(max_size_mb=0)


# ---- SF-13-B: WORMBackend protocol ----

class TestSF13B:
    """SF-13-B: ``WORMBackend`` protocol has required methods."""

    @pytest.mark.unit
    def test_worm_backend_has_required_methods(self):
        import typing
        typing.get_type_hints(WORMBackend)
        # The protocol must expose write, list_files, verify_chain
        for method_name in ("write", "list_files", "verify_chain"):
            assert hasattr(WORMBackend, method_name), \
                f"WORMBackend missing method: {method_name}"


# ---- SF-13-C: CLI audit verify ----

class TestSF13C:
    """SF-13-C: ``spanforge audit verify`` CLI sub-command."""

    @pytest.mark.unit
    def test_cli_audit_verify_help(self):
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["audit", "verify", "--help"])
        assert exc_info.value.code == 0

    @pytest.mark.unit
    def test_cli_audit_verify_valid_chain(self, tmp_path, monkeypatch):
        from spanforge.signing import AuditStream

        stream = AuditStream(org_secret="test-key", source=_SOURCE)
        for _ in range(3):
            stream.append(_make_event())

        jsonl = tmp_path / "chain.jsonl"
        jsonl.write_text(
            "\n".join(e.to_json() for e in stream.events) + "\n",
            encoding="utf-8",
        )

        monkeypatch.setenv("SPANFORGE_SIGNING_KEY", "test-key")

        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["audit", "verify", "--input", str(jsonl)])
        assert exc_info.value.code == 0

    @pytest.mark.unit
    def test_cli_audit_verify_tampered_chain(self, tmp_path, monkeypatch):
        from spanforge.signing import AuditStream

        stream = AuditStream(org_secret="test-key", source=_SOURCE)
        for _ in range(3):
            stream.append(_make_event())

        events = list(stream.events)
        # Tamper with middle event's signature
        tampered = events[1]
        tampered_dict = json.loads(tampered.to_json())
        tampered_dict["signature"] = "sha256:0000000000000000"
        events[1] = Event.from_dict(tampered_dict)

        jsonl = tmp_path / "chain.jsonl"
        jsonl.write_text(
            "\n".join(e.to_json() for e in events) + "\n",
            encoding="utf-8",
        )

        monkeypatch.setenv("SPANFORGE_SIGNING_KEY", "test-key")

        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["audit", "verify", "--input", str(jsonl)])
        assert exc_info.value.code == 1
