from __future__ import annotations

import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.errors import (
    AuthorizationError,
    DemoCredentialsRejectedError,
    EmptyProfileUpdateError,
    IdempotencyKeyReusedWithDifferentPayloadError,
    ProfileTimezoneNotSetError,
    RestDayConflictsWithActivityError,
)
from app.routes.activities import router as activities_router
from app.routes.guidance import router as guidance_router
from app.routes.profile import router as profile_router
from app.routes.training_load import router as training_load_router
from app.routes.weather import router as weather_router

app = FastAPI(title="RunSense Phase 1A - manual-workout-create-sync")
app.include_router(activities_router)
app.include_router(training_load_router)
app.include_router(profile_router)
app.include_router(weather_router)
app.include_router(guidance_router)

# web/ runs on a different origin (Vite dev server) than this API, so the
# browser preflights every request. Without this, every fetch from web/
# fails at the OPTIONS step before the app's own auth even runs -- not an
# auth failure, a CORS failure, which looks identical to "server is down"
# from the browser's perspective. Defaults cover the two Vite dev ports;
# override for a real deployed frontend origin.
_cors_origins = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:5174"
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,  # bearer token in a header, not a cookie
    allow_methods=["GET", "POST", "PUT", "PATCH"],
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
    # Generic authorization error only -- never leak the underlying reason
    # (missing vs malformed actor context, driver-level detail, etc).
    # See design.md Decision 9.
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
