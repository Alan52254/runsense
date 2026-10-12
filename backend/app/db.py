from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Connection, create_engine, text
from sqlalchemy.engine import Engine

from app.errors import AuthorizationError

_engine: Engine | None = None

_LOCAL_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/runsense"


def database_url() -> str:
    """DATABASE_URL, falling back to a hosting platform's plain postgres URL.

    Platforms (e.g. Zeabur's POSTGRES_CONNECTION_STRING) hand out
    `postgresql://` / `postgres://` URLs; SQLAlchemy needs the psycopg 3
    driver named explicitly.
    """
    url = (
        os.environ.get("DATABASE_URL")
        or os.environ.get("POSTGRES_CONNECTION_STRING")
        or _LOCAL_DATABASE_URL
    )
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(database_url(), future=True, pool_pre_ping=True)
    return _engine


def get_connection() -> Iterator[Connection]:
    engine = get_engine()
    with engine.connect() as conn:
        yield conn


@contextmanager
def actor_transaction(conn: Connection, actor_id_raw: str | None) -> Iterator[Connection]:
    """Begin a transaction with the RLS actor context set for its duration.

    See design.md Decision 2: identity is set via set_config(..., true), the
    parameterized equivalent of SET LOCAL, scoped to this transaction only —
    never a session-level or pooled-connection setting (REQ-RLS-004).

    See design.md Decision 9: a malformed (non-UUID) actor id is rejected
    here, before it ever reaches the database, so a bad value fails as a
    clean AuthorizationError instead of a Postgres cast error.
    """
    if actor_id_raw is None:
        raise AuthorizationError("missing actor context")
    try:
        actor_id = uuid.UUID(actor_id_raw)
    except (ValueError, AttributeError, TypeError) as exc:
        raise AuthorizationError("malformed actor context") from exc

    with conn.begin():
        conn.execute(
            text("SELECT set_config('app.actor_user_id', :actor_id, true)"),
            {"actor_id": str(actor_id)},
        )
        yield conn
