"""Shared team authorization checks for coach-owned routes."""

from __future__ import annotations

import uuid

from sqlalchemy import Connection, text

from app.errors import AuthorizationError


_SELECT_COACH_MEMBERSHIP = text(
    """
    SELECT 1 FROM team_memberships
     WHERE team_id = :team_id
       AND user_id = :actor_id
       AND role IN ('coach', 'head_coach', 'owner')
       AND status = 'ACTIVE'
    """
)


def require_coach_role(tx: Connection, team_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    """Fail with the same non-leaking response for missing teams and memberships."""

    found = tx.execute(
        _SELECT_COACH_MEMBERSHIP,
        {"team_id": team_id, "actor_id": actor_id},
    ).first()
    if found is None:
        raise AuthorizationError("actor is not a coach-ish member of this team")
