"""spanforge.actor — Actor identity context for audit-trail events.

Provides :class:`ActorContext`, a lightweight carrier for the user, org,
and team identity that SOC 2 Type II and enterprise compliance audits
require on every operation that mutates system state.

Typical usage
-------------
Embed an ``ActorContext`` directly inside an event payload to satisfy audit
trail requirements::

    from spanforge.actor import ActorContext
    from spanforge import Event
    from spanforge.types import EventType
    from spanforge.namespaces.prompt import PromptPromotedPayload

    actor = ActorContext(
        user_id="usr_abc",
        org_id="org_123",
        team_id="team_456",
        email="priya@acme.com",
        ip_address="203.0.113.5",
    )
    payload = PromptPromotedPayload(
        prompt_id="pmt_xyz",
        version="v7",
        from_environment="staging",
        to_environment="production",
        promoted_by=actor.user_id,
    )
    event = Event(
        event_type=EventType.PROMPT_PROMOTED,
        source="promptlock@1.0.0",
        payload={**payload.to_dict(), "actor": actor.to_dict()},
    )

OTel span attributes
---------------------
When emitting to an OTel-compatible back-end, the actor dict maps to
custom resource/span attributes::

    span.set_attribute("enduser.id",   actor.user_id)
    span.set_attribute("org.id",       actor.org_id)
    span.set_attribute("team.id",      actor.team_id)

These supplement the ``gen_ai.*`` semantic conventions without conflicting
with them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = ["ActorContext"]


@dataclass(frozen=True)
class ActorContext:
    """Identity and audit context for an actor performing an operation.

    Satisfies SOC 2 audit trail requirements: every state-mutating operation
    must record *who* did it, *from where*, and with what organisational
    scope.  All fields except ``user_id`` are optional to accommodate both
    human users and CI/CD service accounts.

    Parameters
    ----------
    user_id:
        Opaque user identifier — stable across sessions and required for
        audit compliance.
    org_id:
        Optional organisation identifier corresponding to the top-level
        tenant in a multi-tenant system.
    team_id:
        Optional team identifier within the organisation.
    email:
        Optional email address of the actor.  May be omitted or replaced
        with a placeholder in high-privacy contexts.
    ip_address:
        Optional IP address from which the action originated.
    service_account:
        ``True`` if this action was performed by an automated CI/CD service
        account rather than a human user.  Defaults to ``False``.
    """

    user_id: str
    org_id: str | None = None
    team_id: str | None = None
    email: str | None = None
    ip_address: str | None = None
    service_account: bool = False

    # -----------------------------------------------------------------
    # Validation
    # -----------------------------------------------------------------

    def __post_init__(self) -> None:
        if not self.user_id or not isinstance(self.user_id, str):
            raise ValueError("ActorContext.user_id must be a non-empty string")
        for attr in ("org_id", "team_id", "email", "ip_address"):
            value = getattr(self, attr)
            if value is not None and not isinstance(value, str):
                raise TypeError(f"ActorContext.{attr} must be a string or None")
        if not isinstance(self.service_account, bool):
            raise TypeError("ActorContext.service_account must be a bool")

    # -----------------------------------------------------------------
    # Serialisation
    # -----------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for embedding in ``Event.payload``.

        Only non-``None`` optional fields are included so that the
        serialised form stays compact.
        """
        result: dict[str, Any] = {"user_id": self.user_id}
        if self.org_id is not None:
            result["org_id"] = self.org_id
        if self.team_id is not None:
            result["team_id"] = self.team_id
        if self.email is not None:
            result["email"] = self.email
        if self.ip_address is not None:
            result["ip_address"] = self.ip_address
        if self.service_account:
            result["service_account"] = True
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActorContext:
        """Reconstruct an :class:`ActorContext` from a plain dict."""
        return cls(
            user_id=str(data["user_id"]),
            org_id=data.get("org_id"),
            team_id=data.get("team_id"),
            email=data.get("email"),
            ip_address=data.get("ip_address"),
            service_account=bool(data.get("service_account", False)),
        )
