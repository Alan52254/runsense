from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import Connection, text

from app.db import actor_transaction, get_connection
from app.errors import EmptyProfileUpdateError
from app.providers import CurrentActorProvider
from app.routes.activities import get_current_actor_provider
from app.schemas import ProfileResponse, UpdateProfileRequest

router = APIRouter()

_UPDATE_SQL = text(
    "UPDATE athlete_profiles SET city = COALESCE(:city, city), "
    "timezone = COALESCE(:timezone, timezone), sex = COALESCE(:sex, sex), updated_at = now() "
    "WHERE user_id = :user_id RETURNING city, timezone, sex, max_hr_bpm, resting_hr_bpm, birth_year"
)

_HR_FIELDS = ("max_hr_bpm", "resting_hr_bpm", "birth_year")


@router.patch("/profile", response_model=ProfileResponse)
def update_profile(
    payload: UpdateProfileRequest,
    conn: Connection = Depends(get_connection),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
) -> ProfileResponse:
    hr_fields = [f for f in _HR_FIELDS if f in payload.model_fields_set]
    if payload.city is None and payload.timezone is None and payload.sex is None and not hr_fields:
        raise EmptyProfileUpdateError()

    actor_id_raw = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor_id_raw) as tx:
        actor_id = uuid.UUID(actor_id_raw)
        if hr_fields:
            # explicitly-sent fields only; an explicit null clears the value
            assignments = ", ".join(f"{f} = :{f}" for f in hr_fields)
            tx.execute(
                text(f"UPDATE athlete_profiles SET {assignments}, updated_at = now() WHERE user_id = :user_id"),
                {"user_id": actor_id, **{f: getattr(payload, f) for f in hr_fields}},
            )
        row = tx.execute(
            _UPDATE_SQL,
            {
                "city": payload.city,
                "timezone": payload.timezone,
                "sex": payload.sex,
                "user_id": actor_id,
            },
        ).first()

    return ProfileResponse(
        city=row.city, timezone=row.timezone, sex=row.sex,
        max_hr_bpm=row.max_hr_bpm, resting_hr_bpm=row.resting_hr_bpm, birth_year=row.birth_year,
    )
