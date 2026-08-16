import uuid

import pytest
from pydantic import ValidationError

from app.schemas import CreateActivityRequest


def _valid_kwargs(**overrides):
    kwargs = dict(
        client_mutation_id=str(uuid.uuid4()),
        duration_minutes=45.0,
        rpe=6,
        performed_at="2026-08-07T09:15:00Z",
    )
    kwargs.update(overrides)
    return kwargs


def test_valid_request_accepted():
    req = CreateActivityRequest(**_valid_kwargs())
    assert req.duration_minutes == 45.0
    assert req.rpe == 6


@pytest.mark.parametrize("rpe", [0, 11, -1])
def test_invalid_rpe_rejected(rpe):
    with pytest.raises(ValidationError):
        CreateActivityRequest(**_valid_kwargs(rpe=rpe))


@pytest.mark.parametrize("duration_minutes", [0, -1, -45.0, float("inf"), float("nan")])
def test_non_positive_or_non_finite_duration_rejected(duration_minutes):
    with pytest.raises(ValidationError):
        CreateActivityRequest(**_valid_kwargs(duration_minutes=duration_minutes))


def test_unknown_field_rejected():
    with pytest.raises(ValidationError):
        CreateActivityRequest(**_valid_kwargs(athlete_id=str(uuid.uuid4())))


def test_naive_performed_at_rejected():
    with pytest.raises(ValidationError):
        CreateActivityRequest(**_valid_kwargs(performed_at="2026-08-07T09:15:00"))


def test_performed_at_normalized_to_utc():
    req = CreateActivityRequest(**_valid_kwargs(performed_at="2026-08-07T17:15:00+08:00"))
    assert req.performed_at.hour == 9
    assert req.performed_at.utcoffset().total_seconds() == 0
