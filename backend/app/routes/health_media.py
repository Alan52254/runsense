"""FastAPI routes for multimedia runner health-education rendering."""

from __future__ import annotations

import base64
from typing import Literal, Protocol
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from app.errors import AuthorizationError
from app.multimedia_education import (
    GeneratorMode,
    HealthMediaArtifact,
    HealthMediaRequest,
    MediaFormat,
    get_media_asset,
    get_multimedia_education_service,
    store_media_asset,
)
from app.providers import CurrentActorProvider
from app.routes.activities import get_current_actor_provider


router = APIRouter(tags=["health-media"])


class HealthMediaGenerator(Protocol):
    def generate(self, request: HealthMediaRequest) -> HealthMediaArtifact: ...


class HealthMediaResponse(BaseModel):
    asset_id: str
    media_format: MediaFormat
    mime_type: str
    file_size_bytes: int
    generator_mode: GeneratorMode
    triage_urgency: str | None = None
    content_base64: str


def _require_actor_id(actor_provider: CurrentActorProvider) -> uuid.UUID:
    actor_id_raw = actor_provider.get_current_actor_id()
    if not actor_id_raw:
        raise AuthorizationError("missing actor context")
    try:
        return uuid.UUID(actor_id_raw)
    except (ValueError, TypeError, AttributeError) as exc:
        raise AuthorizationError("malformed actor context") from exc


def _media_headers(artifact: HealthMediaArtifact) -> dict[str, str]:
    return {
        "Content-Disposition": (
            f'attachment; filename="health-education-{artifact.asset_id}.{artifact.media_format}"'
        ),
        "X-Asset-Id": artifact.asset_id,
        "X-Media-Format": artifact.media_format,
        "X-Generator-Mode": artifact.generator_mode,
        "X-Triage-Urgency": artifact.triage_urgency or "",
    }


def _binary_response(artifact: HealthMediaArtifact) -> Response:
    return Response(
        content=artifact.content_bytes,
        media_type=artifact.mime_type,
        headers=_media_headers(artifact),
    )


def _cache_asset(
    service: HealthMediaGenerator, actor_id: uuid.UUID, artifact: HealthMediaArtifact
) -> None:
    store_fn = getattr(service, "store_asset", None)
    if callable(store_fn):
        store_fn(actor_id, artifact)
    else:
        store_media_asset(actor_id, artifact)


def _lookup_asset(
    service: HealthMediaGenerator, actor_id: uuid.UUID, asset_id: str
) -> HealthMediaArtifact | None:
    get_fn = getattr(service, "get_asset", None)
    if callable(get_fn):
        return get_fn(actor_id, asset_id)
    return get_media_asset(actor_id, asset_id)


@router.post("/guidance/media", response_model=HealthMediaResponse)
def create_health_media(
    payload: HealthMediaRequest,
    response_mode: Literal["json", "binary"] = Query("json"),
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    service: HealthMediaGenerator = Depends(get_multimedia_education_service),
) -> HealthMediaResponse | Response:
    actor_id = _require_actor_id(actor_provider)
    artifact = service.generate(payload)
    _cache_asset(service, actor_id, artifact)
    if response_mode == "binary":
        return _binary_response(artifact)
    return HealthMediaResponse(
        asset_id=artifact.asset_id,
        media_format=artifact.media_format,
        mime_type=artifact.mime_type,
        file_size_bytes=artifact.file_size_bytes,
        generator_mode=artifact.generator_mode,
        triage_urgency=artifact.triage_urgency,
        content_base64=base64.b64encode(artifact.content_bytes).decode("ascii"),
    )


@router.post("/guidance/media/render")
def render_health_media_binary(
    payload: HealthMediaRequest,
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    service: HealthMediaGenerator = Depends(get_multimedia_education_service),
) -> Response:
    actor_id = _require_actor_id(actor_provider)
    artifact = service.generate(payload)
    _cache_asset(service, actor_id, artifact)
    return _binary_response(artifact)


@router.get("/guidance/media/{asset_id}")
def fetch_health_media_asset(
    asset_id: str,
    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider),
    service: HealthMediaGenerator = Depends(get_multimedia_education_service),
) -> Response:
    actor_id = _require_actor_id(actor_provider)
    artifact = _lookup_asset(service, actor_id, asset_id)
    if artifact is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "MEDIA_ASSET_NOT_FOUND", "asset_id": asset_id},
        )
    return _binary_response(artifact)
