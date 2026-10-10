from __future__ import annotations

import os
import threading

from app.runtime_env import load_runtime_environment

if "PYTEST_CURRENT_TEST" not in os.environ:
    load_runtime_environment()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.coach_providers import warm_up_local_model
from app.errors import (
    ActivityNotFoundError,
    AssignmentAthleteNotEligibleError,
    AssignmentNotFoundError,
    AuthorizationError,
    DemoCredentialsRejectedError,
    EmptyProfileUpdateError,
    IdempotencyKeyReusedWithDifferentPayloadError,
    InvalidMfaCodeError,
    InvalidWorkoutSegmentsError,
    ProfileTimezoneNotSetError,
    RestDayConflictsWithActivityError,
    SessionNotFoundError,
    TeamAthleteNotFoundError,
    TelemetryNotFoundError,
    WorkoutAnalysisNotFoundError,
)
from app.routes.activities import router as activities_router
from app.routes.assignments import router as assignments_router
from app.routes.chat import router as chat_router
from app.routes.guidance import router as guidance_router
from app.routes.injury_reports import router as injury_reports_router
from app.routes.injury_guidance import router as injury_guidance_router
from app.routes.me import router as me_router
from app.routes.profile import router as profile_router
from app.routes.settings import router as settings_router
from app.routes.teams import router as teams_router
from app.routes.training_load import router as training_load_router
from app.routes.training_plan import router as training_plan_router
from app.routes.weather import router as weather_router
from app.routes.workout_analysis import router as workout_analysis_router

app = FastAPI(title="RunSense Phase 1A - manual-workout-create-sync")


@app.on_event("startup")
def _warm_up_local_coach_model() -> None:
    # loading a local model takes ~1 minute: do it now, in the background,
    # rather than on the first question (no-op unless GUIDANCE_PROVIDER names ollama)
    if "PYTEST_CURRENT_TEST" not in os.environ:
        threading.Thread(target=warm_up_local_model, daemon=True).start()


app.include_router(activities_router)
app.include_router(training_load_router)
app.include_router(training_plan_router)
app.include_router(profile_router)
app.include_router(weather_router)
app.include_router(guidance_router)
app.include_router(teams_router)
app.include_router(me_router)
app.include_router(injury_reports_router)
app.include_router(injury_guidance_router)
app.include_router(settings_router)
app.include_router(assignments_router)
app.include_router(workout_analysis_router)
app.include_router(chat_router)

_cors_origins = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ALLOWED_ORIGINS",
        "http://localhost:5173,http://localhost:5174,"
        "http://127.0.0.1:5173,http://127.0.0.1:5174",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

_competition_demo_only = os.environ.get("COMPETITION_DEMO_ONLY", "").lower() == "true"
if _competition_demo_only:
    if not os.environ.get("DEMO_JWT_SECRET"):
        raise RuntimeError(
            "DEMO_JWT_SECRET must be set when COMPETITION_DEMO_ONLY=true; "
            "the demo identity mechanism has no default secret"
        )
    from app.routes.demo_auth import router as demo_auth_router

    app.include_router(demo_auth_router)


@app.exception_handler(AuthorizationError)
def handle_authorization_error(request: Request, exc: AuthorizationError) -> JSONResponse:
    return JSONResponse(status_code=403, content={"error": "NOT_AUTHORIZED"})


@app.exception_handler(ProfileTimezoneNotSetError)
def handle_profile_timezone_not_set(
    request: Request, exc: ProfileTimezoneNotSetError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"error": "PROFILE_TIMEZONE_NOT_SET"},
    )


@app.exception_handler(DemoCredentialsRejectedError)
def handle_demo_credentials_rejected(
    request: Request, exc: DemoCredentialsRejectedError
) -> JSONResponse:
    return JSONResponse(status_code=401, content={"error": "INVALID_CREDENTIALS"})


@app.exception_handler(IdempotencyKeyReusedWithDifferentPayloadError)
def handle_idempotency_key_reused(
    request: Request, exc: IdempotencyKeyReusedWithDifferentPayloadError
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={
            "error": "IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_PAYLOAD",
            "client_mutation_id": exc.client_mutation_id,
            "existing_id": exc.existing_id,
        },
    )


@app.exception_handler(RestDayConflictsWithActivityError)
def handle_rest_day_conflict(
    request: Request, exc: RestDayConflictsWithActivityError
) -> JSONResponse:
    return JSONResponse(
        status_code=409,
        content={"error": "REST_DAY_CONFLICTS_WITH_ACTIVITY"},
    )


@app.exception_handler(EmptyProfileUpdateError)
def handle_empty_profile_update(
    request: Request, exc: EmptyProfileUpdateError
) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": "EMPTY_PROFILE_UPDATE"})


@app.exception_handler(TeamAthleteNotFoundError)
def handle_team_athlete_not_found(
    request: Request, exc: TeamAthleteNotFoundError
) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "TEAM_ATHLETE_NOT_FOUND"})


@app.exception_handler(SessionNotFoundError)
def handle_session_not_found(request: Request, exc: SessionNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "SESSION_NOT_FOUND"})


@app.exception_handler(InvalidMfaCodeError)
def handle_invalid_mfa_code(request: Request, exc: InvalidMfaCodeError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": "INVALID_MFA_CODE"})


@app.exception_handler(AssignmentAthleteNotEligibleError)
def handle_assignment_athlete_not_eligible(
    request: Request, exc: AssignmentAthleteNotEligibleError
) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "ASSIGNMENT_ATHLETE_NOT_ELIGIBLE"})


@app.exception_handler(AssignmentNotFoundError)
def handle_assignment_not_found(request: Request, exc: AssignmentNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "ASSIGNMENT_NOT_FOUND"})


@app.exception_handler(ActivityNotFoundError)
def handle_activity_not_found(request: Request, exc: ActivityNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "ACTIVITY_NOT_FOUND"})


@app.exception_handler(TelemetryNotFoundError)
def handle_telemetry_not_found(request: Request, exc: TelemetryNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "TELEMETRY_NOT_FOUND"})


@app.exception_handler(WorkoutAnalysisNotFoundError)
def handle_workout_analysis_not_found(request: Request, exc: WorkoutAnalysisNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "WORKOUT_ANALYSIS_NOT_FOUND"})


@app.exception_handler(InvalidWorkoutSegmentsError)
def handle_invalid_workout_segments(request: Request, exc: InvalidWorkoutSegmentsError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": "INVALID_WORKOUT_SEGMENTS", "reason": exc.reason})
