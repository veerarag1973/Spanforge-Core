"""Tests for spanforge.consent — Consent Boundary module."""

from __future__ import annotations

import pytest

from spanforge.consent import (
    ConsentBoundary,
    check_consent,
    grant_consent,
    revoke_consent,
)
from spanforge.namespaces.consent import ConsentPayload

# ---------------------------------------------------------------------------
# ConsentPayload tests
# ---------------------------------------------------------------------------


class TestConsentPayload:
    """ConsentPayload dataclass validation and serialization."""

    @pytest.mark.unit
    def test_valid_payload_creation(self):
        p = ConsentPayload(
            subject_id="user-1",
            scope="analytics",
            purpose="personalisation",
            status="granted",
            legal_basis="consent",
        )
        assert p.subject_id == "user-1"
        assert p.status == "granted"

    @pytest.mark.unit
    def test_round_trip(self):
        p = ConsentPayload(
            subject_id="user-2",
            scope="marketing",
            purpose="email campaigns",
            status="revoked",
            legal_basis="legitimate_interest",
            agent_id="agent-1",
        )
        d = p.to_dict()
        p2 = ConsentPayload.from_dict(d)
        assert p2.subject_id == p.subject_id
        assert p2.status == p.status
        assert p2.legal_basis == p.legal_basis
        assert p2.agent_id == p.agent_id

    @pytest.mark.unit
    def test_empty_subject_id_raises(self):
        with pytest.raises(ValueError, match="subject_id"):
            ConsentPayload(
                subject_id="",
                scope="analytics",
                purpose="test",
                status="granted",
                legal_basis="consent",
            )

    @pytest.mark.unit
    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="status"):
            ConsentPayload(
                subject_id="u1",
                scope="analytics",
                purpose="test",
                status="pending",
                legal_basis="consent",
            )

    @pytest.mark.unit
    def test_invalid_legal_basis_raises(self):
        with pytest.raises(ValueError, match="legal_basis"):
            ConsentPayload(
                subject_id="u1",
                scope="analytics",
                purpose="test",
                status="granted",
                legal_basis="unknown",
            )

    @pytest.mark.unit
    def test_data_categories_serialization(self):
        p = ConsentPayload(
            subject_id="u1",
            scope="s",
            purpose="p",
            status="granted",
            legal_basis="consent",
            data_categories=["name", "email"],
        )
        d = p.to_dict()
        assert d["data_categories"] == ["name", "email"]
        p2 = ConsentPayload.from_dict(d)
        assert p2.data_categories == ["name", "email"]


# ---------------------------------------------------------------------------
# ConsentBoundary runtime tests
# ---------------------------------------------------------------------------


class TestConsentBoundary:
    """ConsentBoundary thread-safe runtime class."""

    def setup_method(self):
        self.boundary = ConsentBoundary(auto_emit=False)

    @pytest.mark.unit
    def test_grant_and_check(self):
        self.boundary.grant("user-1", "analytics", purpose="test", legal_basis="consent")
        assert self.boundary.has_consent("user-1", "analytics") is True
        assert self.boundary.check("user-1", "analytics") is True

    @pytest.mark.unit
    def test_check_without_grant(self):
        assert self.boundary.has_consent("unknown", "analytics") is False
        assert self.boundary.check("unknown", "analytics") is False

    @pytest.mark.unit
    def test_revoke(self):
        self.boundary.grant("user-1", "analytics", purpose="test", legal_basis="consent")
        self.boundary.revoke("user-1", "analytics")
        assert self.boundary.has_consent("user-1", "analytics") is False

    @pytest.mark.unit
    def test_list_consents(self):
        self.boundary.grant("user-1", "analytics", purpose="a", legal_basis="consent")
        self.boundary.grant("user-1", "marketing", purpose="b", legal_basis="consent")
        consents = self.boundary.list_consents("user-1")
        assert len(consents) == 2

    @pytest.mark.unit
    def test_list_consents_empty(self):
        assert self.boundary.list_consents("ghost") == []

    @pytest.mark.unit
    def test_clear(self):
        self.boundary.grant("u1", "s", purpose="p", legal_basis="consent")
        self.boundary.clear()
        assert self.boundary.has_consent("u1", "s") is False

    @pytest.mark.unit
    def test_revoke_nonexistent_is_no_op(self):
        # Should not raise
        self.boundary.revoke("ghost", "scope")

    @pytest.mark.unit
    def test_grant_empty_subject_raises(self):
        with pytest.raises(ValueError, match="subject_id"):
            self.boundary.grant("", "scope", purpose="p", legal_basis="consent")

    @pytest.mark.unit
    def test_grant_empty_scope_raises(self):
        with pytest.raises(ValueError, match="scope"):
            self.boundary.grant("user", "", purpose="p", legal_basis="consent")


# ---------------------------------------------------------------------------
# Module-level convenience function tests
# ---------------------------------------------------------------------------


class TestConsentConvenienceFunctions:
    """Module-level grant_consent / revoke_consent / check_consent."""

    @pytest.mark.unit
    def test_grant_check_revoke_cycle(self):
        from spanforge.consent import _boundary
        _boundary.clear()

        grant_consent("u1", "scope1", purpose="test", legal_basis="consent")
        assert check_consent("u1", "scope1") is True
        revoke_consent("u1", "scope1")
        assert check_consent("u1", "scope1") is False
