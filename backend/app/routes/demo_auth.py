"""Competition-only demo login endpoint."""

from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, text

from app.db import actor_transaction, get_connection
from app.errors import DemoCredentialsRejectedError

router = APIRouter(prefix="/auth")
_DUMMY_PASSWORD_HASH = bcrypt.hashpw(b"demo-login-dummy-password", bcrypt.gensalt())


class DemoLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str
    password: str


class DemoLoginResponse(BaseModel):
    access_token: str
    expires_at: datetime


_INSERT_AUTH_SESSION = text(
    """
    INSERT INTO auth_sessions (id, user_id, device, ip_masked, location)
    VALUES (:id, :user_id, :device, :ip_masked, :location)
    """
)

_INSERT_AUTH_LOGIN_AUDIT = text(
    "INSERT INTO audit_log (actor_id, event, summary) "
    "VALUES (:actor_id, 'AUTH_LOGIN', 'Demo login succeeded')"
)


def _masked_client_ip(request: Request) -> str:
    # Demo-appropriate masking only (last octet/segment dropped) -- not a
    # real anonymization guarantee. See settings.py / README for scope.
    host = request.client.host if request.client else "unknown"
    if re.fullmatch(r"(\d{1,3}\.){3}\d{1,3}", host):
        return re.sub(r"\d{1,3}$", "xxx", host)
    return "***" if host != "unknown" else host


@router.post("/demo-login", response_model=DemoLoginResponse)
def demo_login(
    payload: DemoLoginRequest, request: Request, conn: Connection = Depends(get_connection)
) -> DemoLoginResponse:
    row = conn.execute(
        text("SELECT id, password_hash FROM users WHERE email = :email"),
        {"email": payload.email},
    ).first()
    # The SELECT above autobegins an implicit transaction on this connection
    # (SQLAlchemy future=True); actor_transaction() below calls conn.begin()
    # itself and requires no transaction already open, so close this one out
    # first (nothing was written, so commit/rollback are equivalent here).
    conn.commit()
    stored_hash = row.password_hash.encode("utf-8") if row is not None else _DUMMY_PASSWORD_HASH
    try:
        password_matches = bcrypt.checkpw(payload.password.encode("utf-8"), stored_hash)
    except ValueError:
        # bcrypt 5 rejects passwords longer than 72 bytes. Invalid input must
        # still follow the same generic credential-rejection path rather than
        # escaping as a 500 or revealing whether the email exists.
        password_matches = False
    if row is None or not password_matches:
        raise DemoCredentialsRejectedError()

    session_id = uuid.uuid4()
    # REQ-AUTH-005/REQ-AUDIT-001: every demo login gets a real auth_sessions
    # row and an AUTH_LOGIN audit entry -- see backend/app/routes/settings.py
    # for what reads these. Written under an actor_transaction scoped to the
    # user who just authenticated so the tables' self-only RLS is satisfied.
    with actor_transaction(conn, str(row.id)) as tx:
        tx.execute(
            _INSERT_AUTH_SESSION,
            {
                "id": session_id,
                "user_id": row.id,
                "device": request.headers.get("User-Agent", "Unknown device")[:200],
                "ip_masked": _masked_client_ip(request),
                "location": "Unknown",
            },
        )
        tx.execute(_INSERT_AUTH_LOGIN_AUDIT, {"actor_id": row.id})

    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    token = jwt.encode(
        {"sub": str(row.id), "sid": str(session_id), "exp": expires_at},
        os.environ["DEMO_JWT_SECRET"],
        algorithm="HS256",
    )
    return DemoLoginResponse(access_token=token, expires_at=expires_at)
