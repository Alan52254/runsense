"""Competition-only demo login endpoint."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import Connection, text

from app.db import get_connection
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


@router.post("/demo-login", response_model=DemoLoginResponse)
def demo_login(payload: DemoLoginRequest, conn: Connection = Depends(get_connection)) -> DemoLoginResponse:
    row = conn.execute(
        text("SELECT id, password_hash FROM users WHERE email = :email"),
        {"email": payload.email},
    ).first()
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

    expires_at = datetime.now(timezone.utc) + timedelta(hours=24)
    token = jwt.encode(
        {"sub": str(row.id), "exp": expires_at},
        os.environ["DEMO_JWT_SECRET"],
        algorithm="HS256",
    )
    return DemoLoginResponse(access_token=token, expires_at=expires_at)
