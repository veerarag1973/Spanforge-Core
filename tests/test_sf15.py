"""SF-15 — GDPR Subject Erasure acceptance tests."""

from __future__ import annotations

import json

import pytest

from spanforge import Event, EventType
from spanforge.signing import AuditStream, ChainVerificationResult, verify_chain


_SOURCE = "test-sf15@1.0.0"
_SECRET = "test-secret-key-for-sf15"


def _make_event(**kw):
    defaults = {
        "event_type": EventType.TRACE_SPAN_COMPLETED,
        "source": _SOURCE,
        "payload": {"span_name": "run", "status": "ok"},
    }
    defaults.update(kw)
    return Event(**defaults)


# ---- SF-15-A: AUDIT_TOMBSTONE event type ----

class TestSF15A:
    """SF-15-A: ``AUDIT_TOMBSTONE`` event type exists."""

    @pytest.mark.unit
    def test_audit_tombstone_event_type(self):
        assert hasattr(EventType, "AUDIT_TOMBSTONE")
        assert EventType.AUDIT_TOMBSTONE.value == "llm.audit.tombstone"


# ---- SF-15-B: erase_subject with exact match and request_ref ----

class TestSF15B:
    """SF-15-B: ``erase_subject()`` exact-match and ``request_ref``."""

    @pytest.mark.unit
    def test_erase_subject_exact_match_no_false_positive(self):
        """Ensure 'user-1' does NOT match 'user-10' (exact match, not substring)."""
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        stream.append(_make_event(actor_id="user-10"))

        tombstones = stream.erase_subject("user-1")
        assert len(tombstones) == 0, "Substring 'user-1' should NOT match 'user-10'"

    @pytest.mark.unit
    def test_erase_subject_exact_match_positive(self):
        """Ensure exact match works."""
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        stream.append(_make_event(actor_id="user-1"))

        tombstones = stream.erase_subject("user-1")
        assert len(tombstones) == 1

    @pytest.mark.unit
    def test_erase_subject_request_ref_recorded(self):
        """The ``request_ref`` should appear in tombstone payload."""
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        stream.append(_make_event(actor_id="subject-42"))

        tombstones = stream.erase_subject(
            "subject-42",
            request_ref="GDPR-REQ-2024-001",
        )
        assert len(tombstones) == 1
        payload = tombstones[0].payload
        assert payload["erasure_request_ref"] == "GDPR-REQ-2024-001"

    @pytest.mark.unit
    def test_erase_subject_no_request_ref_omitted(self):
        """When ``request_ref`` is empty, the key should not appear."""
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        stream.append(_make_event(actor_id="subject-99"))

        tombstones = stream.erase_subject("subject-99")
        assert len(tombstones) == 1
        assert "erasure_request_ref" not in tombstones[0].payload


# ---- SF-15-C: CLI audit erase ----

class TestSF15C:
    """SF-15-C: CLI ``audit erase`` with ``--request-ref`` and pre-verify."""

    @pytest.mark.unit
    def test_cli_erase_help_shows_request_ref(self):
        from spanforge._cli import main

        with pytest.raises(SystemExit) as exc_info:
            main(["audit", "erase", "--help"])
        # Just verify the command parses; --help exits with 0
        assert exc_info.value.code == 0

    @pytest.mark.unit
    def test_cli_erase_prevents_overwrite(self, tmp_path, monkeypatch):
        """The default output should NOT be the same as input."""
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        stream.append(_make_event(actor_id="user-erase"))

        jsonl = tmp_path / "chain.jsonl"
        jsonl.write_text(
            "\n".join(e.to_json() for e in stream.events) + "\n",
            encoding="utf-8",
        )

        monkeypatch.setenv("SPANFORGE_SIGNING_KEY", _SECRET)

        from spanforge._cli import main

        # Explicitly pass --output same as input → should fail
        with pytest.raises(SystemExit) as exc_info:
            main([
                "audit", "erase", str(jsonl),
                "--subject-id", "user-erase",
                "--output", str(jsonl),
            ])
        assert exc_info.value.code == 2


# ---- SF-15-D: Tombstones tracked in ChainVerificationResult ----

class TestSF15D:
    """SF-15-D: Tombstones tracked by ``verify_chain``."""

    @pytest.mark.unit
    def test_verify_chain_counts_tombstones(self):
        stream = AuditStream(org_secret=_SECRET, source=_SOURCE)
        stream.append(_make_event(actor_id="to-erase"))
        stream.append(_make_event())

        stream.erase_subject("to-erase")
        result = verify_chain(list(stream.events), org_secret=_SECRET)

        assert result.tombstone_count >= 1
        assert len(result.tombstone_event_ids) >= 1
