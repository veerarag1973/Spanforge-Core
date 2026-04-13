"""Tests for spanforge.actor.ActorContext."""

from __future__ import annotations

import pytest

from spanforge.actor import ActorContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _round_trip(obj: ActorContext) -> ActorContext:
    return ActorContext.from_dict(obj.to_dict())


# ===========================================================================
# ActorContext
# ===========================================================================


class TestActorContext:
    def test_required_only(self):
        actor = ActorContext(user_id="usr_abc")
        assert actor.user_id == "usr_abc"
        assert actor.org_id is None
        assert actor.team_id is None
        assert actor.email is None
        assert actor.ip_address is None
        assert actor.service_account is False

    def test_all_fields(self):
        actor = ActorContext(
            user_id="usr_abc",
            org_id="org_123",
            team_id="team_456",
            email="priya@acme.com",
            ip_address="203.0.113.5",
            service_account=False,
        )
        assert actor.org_id == "org_123"
        assert actor.team_id == "team_456"
        assert actor.email == "priya@acme.com"
        assert actor.ip_address == "203.0.113.5"

    def test_service_account_flag(self):
        actor = ActorContext(user_id="svc_ci_deploy", service_account=True)
        assert actor.service_account is True
        d = actor.to_dict()
        assert d["service_account"] is True

    def test_to_dict_required_only(self):
        actor = ActorContext(user_id="usr_abc")
        d = actor.to_dict()
        assert d == {"user_id": "usr_abc"}
        assert "org_id" not in d
        assert "service_account" not in d  # False is omitted

    def test_to_dict_full(self):
        actor = ActorContext(
            user_id="usr_abc",
            org_id="org_123",
            team_id="team_456",
            email="priya@acme.com",
            ip_address="203.0.113.5",
            service_account=True,
        )
        d = actor.to_dict()
        assert d["user_id"] == "usr_abc"
        assert d["org_id"] == "org_123"
        assert d["team_id"] == "team_456"
        assert d["email"] == "priya@acme.com"
        assert d["ip_address"] == "203.0.113.5"
        assert d["service_account"] is True

    def test_round_trip_minimal(self):
        actor = ActorContext(user_id="usr_abc")
        assert _round_trip(actor) == actor

    def test_round_trip_full(self):
        actor = ActorContext(
            user_id="usr_abc",
            org_id="org_123",
            team_id="team_456",
            email="priya@acme.com",
            ip_address="203.0.113.5",
            service_account=True,
        )
        assert _round_trip(actor) == actor

    def test_empty_user_id_raises(self):
        with pytest.raises(ValueError, match="user_id"):
            ActorContext(user_id="")

    def test_non_string_user_id_raises(self):
        with pytest.raises(ValueError, match="user_id"):
            ActorContext(user_id=None)  # type: ignore

    def test_non_string_org_id_raises(self):
        with pytest.raises(TypeError, match="org_id"):
            ActorContext(user_id="usr_abc", org_id=123)  # type: ignore

    def test_non_string_email_raises(self):
        with pytest.raises(TypeError, match="email"):
            ActorContext(user_id="usr_abc", email=42)  # type: ignore

    def test_non_string_ip_address_raises(self):
        with pytest.raises(TypeError, match="ip_address"):
            ActorContext(user_id="usr_abc", ip_address=True)  # type: ignore

    def test_non_bool_service_account_raises(self):
        with pytest.raises(TypeError, match="service_account"):
            ActorContext(user_id="usr_abc", service_account="yes")  # type: ignore

    def test_frozen(self):
        actor = ActorContext(user_id="usr_abc")
        with pytest.raises((AttributeError, TypeError)):
            actor.user_id = "other"  # type: ignore

    def test_from_dict_service_account_default_false(self):
        actor = ActorContext.from_dict({"user_id": "usr_abc", "org_id": "org_1"})
        assert actor.service_account is False

    def test_embed_in_event_payload(self):
        """ActorContext.to_dict() can be seamlessly embedded in an event payload."""
        from spanforge import Event  # noqa: PLC0415
        from spanforge.namespaces.prompt import PromptVersionChangedPayload  # noqa: PLC0415
        from spanforge.types import EventType  # noqa: PLC0415

        actor = ActorContext(
            user_id="usr_abc",
            org_id="org_123",
            email="priya@acme.com",
        )
        changed = PromptVersionChangedPayload(
            template_id="pmt_xyz",
            previous_version="v6",
            new_version="v7",
            change_reason="Production release",
        )
        event = Event(
            event_type=EventType.PROMPT_VERSION_CHANGED,
            source="promptlock@1.0.0",
            payload={**changed.to_dict(), "actor": actor.to_dict()},
        )
        assert event.payload["actor"]["user_id"] == "usr_abc"
        assert event.payload["actor"]["org_id"] == "org_123"


class TestActorContextTopLevelExport:
    def test_accessible_from_package_root(self):
        import spanforge  # noqa: PLC0415
        assert hasattr(spanforge, "ActorContext")
        assert spanforge.ActorContext is ActorContext
