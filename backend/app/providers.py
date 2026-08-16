"""Actor and profile-timezone provider implementations.

See design.md (manual-workout-create-sync) Decision 10: CurrentActorProvider
and ProfileTimezoneProvider are the boundary this change defines toward the
future Auth and Profile changes. Only test-only / stub implementations exist
here. Production implementations must be supplied by those future changes.

DemoCurrentActorProvider is an explicitly competition-only access-token
adapter. It provides no refresh-token rotation, rate limiting, revocation, or
account lockout and must not be mistaken for a production authentication path.

CRITICAL: never wire a client-supplied header (e.g. X-User-Id) or any other
client-controlled value into a production CurrentActorProvider. Doing so
defeats REQ-RLS-006 (actor identity must be authenticated, not client-
asserted). See design.md Decision 10, "Explicitly rejected alternative".
"""

from __future__ import annotations

import os
from typing import Protocol

import jwt
from fastapi import Request
from sqlalchemy import Connection, text


class CurrentActorProvider(Protocol):
    """Supplies the authenticated actor's UUID (as a string) for the current request."""

    def get_current_actor_id(self) -> str | None:
        ...


class ProfileTimezoneProvider(Protocol):
    """Supplies the current actor's validated IANA timezone, or None if unset."""

    def get_profile_timezone(self, actor_id: str) -> str | None:
        ...


class NotImplementedCurrentActorProvider:
    """Default production wiring: fails loudly rather than silently granting access.

    This is intentional. Until the Auth change supplies a real
    CurrentActorProvider, the endpoint must not start serving requests as if
    an actor were authenticated. Raising here is preferable to defaulting to
    an empty/anonymous actor, which would silently defeat REQ-RLS-006.
    """

    def get_current_actor_id(self) -> str | None:
        raise NotImplementedError(
            "No production CurrentActorProvider has been wired up. "
            "This must be supplied by the Auth change, not invented here."
        )


class NotImplementedProfileTimezoneProvider:
    """Default production wiring: fails loudly rather than silently defaulting a timezone."""

    def get_profile_timezone(self, actor_id: str) -> str | None:
        raise NotImplementedError(
            "No production ProfileTimezoneProvider has been wired up. "
            "This must be supplied by the Profile change, not invented here."
        )


class DemoCurrentActorProvider:
    """Resolve an actor only from a verified, unexpired demo JWT."""

    def __init__(self, request: Request, secret: str | None = None) -> None:
        self._request = request
        self._secret = secret if secret is not None else os.environ.get("DEMO_JWT_SECRET")

    def get_current_actor_id(self) -> str | None:
        try:
            scheme, token = self._request.headers["Authorization"].split(" ", 1)
            if scheme.lower() != "bearer" or not token:
                return None
            claims = jwt.decode(token, self._secret, algorithms=["HS256"])
            subject = claims.get("sub")
            return subject if isinstance(subject, str) and subject else None
        except Exception:
            # This provider is a fail-closed adapter. Authentication failures
            # are deliberately normalized to no actor and never leak details.
            return None


class DbProfileTimezoneProvider:
    """Resolve an actor's timezone from the persisted demo profile."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def get_profile_timezone(self, actor_id: str) -> str | None:
        return self._conn.execute(
            text("SELECT timezone FROM athlete_profiles WHERE user_id = :actor_id"),
            {"actor_id": actor_id},
        ).scalar_one_or_none()


class StaticCurrentActorProvider:
    """Test-only: always returns a fixed actor id. Never use outside tests."""

    def __init__(self, actor_id: str | None) -> None:
        self._actor_id = actor_id

    def get_current_actor_id(self) -> str | None:
        return self._actor_id


class InMemoryProfileTimezoneProvider:
    """Test-only: looks up a timezone from an in-memory mapping. Never use outside tests."""

    def __init__(self, timezones_by_actor_id: dict[str, str] | None = None) -> None:
        self._timezones_by_actor_id = dict(timezones_by_actor_id or {})

    def get_profile_timezone(self, actor_id: str) -> str | None:
        return self._timezones_by_actor_id.get(actor_id)

    def set_profile_timezone(self, actor_id: str, timezone_name: str | None) -> None:
        if timezone_name is None:
            self._timezones_by_actor_id.pop(actor_id, None)
        else:
            self._timezones_by_actor_id[actor_id] = timezone_name
