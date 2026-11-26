from __future__ import annotations

import base64
import json
import math
import shutil
import struct
import subprocess
import time
import uuid
import xml.etree.ElementTree as ET
import zlib

from fastapi.testclient import TestClient
import httpx
from pydantic import ValidationError
import pytest

from app.main import app
from app.multimedia_education import (
    HealthMediaArtifact,
    HealthMediaRequest,
    HttpMediaProvider,
    MultimediaEducationService,
    _is_valid_png,
    _render_png_canvas,
    _sanitize_surrogates_value,
    _validate_media_bytes,
    configured_media_provider,
    effective_running_allowed,
    get_multimedia_education_service,
)
from app.providers import StaticCurrentActorProvider
from app.routes.activities import get_current_actor_provider
from app.safety_triage import TriageUrgency


def _parse_png_chunks(data: bytes) -> list[tuple[bytes, bytes]]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    offset = 8
    chunks: list[tuple[bytes, bytes]] = []
    while offset < len(data):
        length, chunk_type = struct.unpack(">I4s", data[offset : offset + 8])
        payload_start = offset + 8
        payload_end = payload_start + length
        payload = data[payload_start:payload_end]
        (crc_actual,) = struct.unpack(">I", data[payload_end : payload_end + 4])
        crc_expected = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
        assert crc_actual == crc_expected, f"CRC mismatch for chunk {chunk_type!r}"
        chunks.append((chunk_type, payload))
        offset = payload_end + 4
        if chunk_type == b"IEND":
            break
    assert offset == len(data)
    return chunks


@pytest.fixture()
def authed_client():
    actor_id = str(uuid.uuid4())
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_actor_provider] = lambda: StaticCurrentActorProvider(
        actor_id
    )
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_png_binary_integrity_and_optional_ffprobe(tmp_path) -> None:
    service = MultimediaEducationService()
    req = HealthMediaRequest(
        topic="Achilles Tendon Load Management",
        body_part="Achilles",
        triage_urgency=TriageUrgency.PROMPT_CLINICIAN,
        running_allowed=False,
        guidance_summary="Pause high-impact running and consult a sports clinician before progressing.",
        next_steps=["Pause speed sessions", "Track morning stiffness", "Consult clinician"],
        citations=["ACSM Tendinopathy Guide 2024"],
        media_format="png",
        athlete_context={"acwr": 1.48, "resting_hr_delta": 5, "sleep_hours": 6.2},
    )

    artifact = service.generate(req)

    assert artifact.media_format == "png"
    assert artifact.mime_type == "image/png"
    assert artifact.generator_mode == "local_raster"
    assert artifact.triage_urgency == "PROMPT_CLINICIAN"
    assert artifact.file_size_bytes == len(artifact.content_bytes)

    chunks = _parse_png_chunks(artifact.content_bytes)
    assert chunks[0][0] == b"IHDR"
    assert chunks[-1][0] == b"IEND"
    width, height, bit_depth, color_type, *_ = struct.unpack(">IIBBBBB", chunks[0][1])
    assert width == 800
    assert height == 500
    assert bit_depth == 8
    assert color_type == 2

    idat_payload = b"".join(payload for ctype, payload in chunks if ctype == b"IDAT")
    assert idat_payload
    decompressed = zlib.decompress(idat_payload)
    assert len(decompressed) == height * (width * 3 + 1)

    ffprobe_bin = shutil.which("ffprobe")
    if ffprobe_bin:
        png_file = tmp_path / "card.png"
        png_file.write_bytes(artifact.content_bytes)
        probe = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,width,height",
                "-of",
                "json",
                str(png_file),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        info = json.loads(probe.stdout)
        assert info["streams"][0]["codec_name"] == "png"
        assert info["streams"][0]["width"] == 800
        assert info["streams"][0]["height"] == 500


def test_mp4_binary_faststart_and_ffprobe_when_available(tmp_path) -> None:
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed on host")

    service = MultimediaEducationService()
    req = HealthMediaRequest(
        topic="Exertional Heat Illness Recovery",
        body_part="Systemic",
        triage_urgency=TriageUrgency.EMERGENCY,
        running_allowed=False,
        guidance_summary="Stop running immediately, cool down, and seek urgent medical care.",
        next_steps=["Stop running immediately", "Active cooling", "Seek emergency evaluation"],
        citations=["ACSM Exertional Heat Consensus"],
        media_format="mp4",
        athlete_context={"temperature_c": 34.5, "heat_loss_pct": 8.4},
    )

    artifact = service.generate(req)

    assert artifact.media_format == "mp4"
    assert artifact.mime_type == "video/mp4"
    assert artifact.generator_mode == "local_ffmpeg"
    assert artifact.file_size_bytes == len(artifact.content_bytes)
    assert len(artifact.content_bytes) > 100
    assert artifact.content_bytes[4:8] == b"ftyp"

    moov_idx = artifact.content_bytes.find(b"moov")
    mdat_idx = artifact.content_bytes.find(b"mdat")
    assert moov_idx != -1 and mdat_idx != -1
    assert moov_idx < mdat_idx

    ffprobe_bin = shutil.which("ffprobe")
    if ffprobe_bin:
        mp4_file = tmp_path / "card.mp4"
        mp4_file.write_bytes(artifact.content_bytes)
        probe = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_name,width,height,pix_fmt",
                "-of",
                "json",
                str(mp4_file),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        info = json.loads(probe.stdout)
        stream = info["streams"][0]
        assert stream["width"] > 0
        assert stream["height"] > 0
        assert stream["pix_fmt"] == "yuv420p"


def test_svg_well_formedness_xss_escaping_and_bilingual_text() -> None:
    service = MultimediaEducationService()
    req = HealthMediaRequest(
        topic='阿基里斯腱負荷管理：第1階段 <script>alert("xss")</script> & "Loading"',
        body_part="阿基里斯腱 / Achilles",
        triage_urgency=TriageUrgency.SELF_CARE_NEXT_STEP,
        running_allowed=False,
        guidance_summary='請先「停止跑步」並觀察晨間僵硬變化\x00\x07；避免突然增加坡度衝刺。',
        next_steps=["「停止跑步」並冰敷觀察", "記錄晨間疼痛 0-10 分", "48 小時後評估"],
        citations=["Sports Med Evidence v1 & <Clinical Note>"],
        media_format="svg",
        athlete_context={"acwr": 1.32, "sleep_hours": 7.1},
    )

    artifact = service.generate(req)

    assert artifact.media_format == "svg"
    assert artifact.mime_type == "image/svg+xml"
    assert artifact.generator_mode == "local_svg_fallback"
    assert artifact.file_size_bytes == len(artifact.content_bytes)

    svg_text = artifact.content_bytes.decode("utf-8")
    assert "<script>" not in svg_text
    assert "\x00" not in svg_text
    assert "\x07" not in svg_text
    assert "阿基里斯腱負荷管理" in svg_text
    assert "Sports Med Evidence v1" in svg_text

    root = ET.fromstring(svg_text)
    assert root.tag.endswith("svg")
    assert int(root.attrib["width"]) > 0
    assert int(root.attrib["height"]) > 0
    assert root.attrib["viewBox"] == "0 0 800 500"


def test_zero_api_key_and_failing_external_provider_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    for env_var in (
        "RUNSENCE_MEDIA_API_KEY",
        "RUNSENCE_MEDIA_API_URL",
        "GROQ_API_KEY",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "MEDIA_API_KEY",
        "HEALTH_MEDIA_API_KEY",
        "GUIDANCE_PROVIDER",
    ):
        monkeypatch.delenv(env_var, raising=False)

    assert configured_media_provider() is None

    req = HealthMediaRequest(
        topic="Runner Knee Load Control",
        body_part="Knee",
        triage_urgency=TriageUrgency.SELF_CARE_NEXT_STEP,
        guidance_summary="Reduce weekly volume and monitor patellofemoral symptoms.",
        next_steps=["Reduce mileage", "Monitor next 48h"],
        citations=["JOSPT Knee Guidelines"],
        media_format="png",
    )

    # 1. Default service with zero API keys
    local_artifact = MultimediaEducationService().generate(req)
    assert local_artifact.generator_mode == "local_raster"
    assert local_artifact.content_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    # 2. Stub provider that raises
    class RaisingProvider:
        provider_name = "broken"

        def is_configured(self) -> bool:
            return True

        def generate(self, request: HealthMediaRequest) -> HealthMediaArtifact | None:
            raise httpx.TimeoutException("upstream timed out")

    fallback_from_error = MultimediaEducationService(provider=RaisingProvider()).generate(req)
    assert fallback_from_error.generator_mode == "local_raster"
    assert fallback_from_error.content_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    # 3. Stub provider that returns corrupt non-PNG bytes
    class CorruptProvider:
        provider_name = "corrupt"

        def is_configured(self) -> bool:
            return True

        def generate(self, request: HealthMediaRequest) -> HealthMediaArtifact | None:
            return HealthMediaArtifact(
                asset_id="bad_1",
                media_format="png",
                mime_type="image/png",
                content_bytes=b"NOT_A_PNG_PAYLOAD",
                file_size_bytes=17,
                generator_mode="external_api",
                triage_urgency=None,
            )

    fallback_from_corrupt = MultimediaEducationService(provider=CorruptProvider()).generate(req)
    assert fallback_from_corrupt.generator_mode == "local_raster"
    assert fallback_from_corrupt.content_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    # 4. Real HttpMediaProvider against mocked httpx transport (error -> fallback, valid -> external_api)
    def error_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    http_fail_provider = HttpMediaProvider(
        api_key="test-key",
        api_url="https://media.example.invalid/render",
        client=httpx.Client(transport=httpx.MockTransport(error_handler)),
    )
    fallback_http = MultimediaEducationService(provider=http_fail_provider).generate(req)
    assert fallback_http.generator_mode == "local_raster"

    valid_png = local_artifact.content_bytes

    def ok_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=valid_png, headers={"content-type": "image/png"})

    http_ok_provider = HttpMediaProvider(
        api_key="test-key",
        api_url="https://media.example.invalid/render",
        client=httpx.Client(transport=httpx.MockTransport(ok_handler)),
    )
    external_ok = MultimediaEducationService(provider=http_ok_provider).generate(req)
    assert external_ok.generator_mode == "external_api"
    assert external_ok.media_format == "png"
    assert external_ok.mime_type == "image/png"
    assert external_ok.content_bytes == valid_png


def test_ffmpeg_unavailable_resilience(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    service = MultimediaEducationService()

    png_req = HealthMediaRequest(
        topic="Plantar Fasciitis Morning Care",
        body_part="Foot",
        triage_urgency=TriageUrgency.SELF_CARE_NEXT_STEP,
        guidance_summary="Avoid barefoot hard-floor impact and perform gentle calf stretches.",
        media_format="png",
    )
    png_artifact = service.generate(png_req)
    assert png_artifact.media_format == "png"
    assert png_artifact.mime_type == "image/png"
    assert png_artifact.generator_mode == "local_raster"
    assert png_artifact.content_bytes.startswith(b"\x89PNG\r\n\x1a\n")

    svg_req = png_req.model_copy(update={"media_format": "svg"})
    svg_artifact = service.generate(svg_req)
    assert svg_artifact.media_format == "svg"
    assert svg_artifact.mime_type == "image/svg+xml"
    assert svg_artifact.generator_mode == "local_svg_fallback"
    assert ET.fromstring(svg_artifact.content_bytes.decode("utf-8")).tag.endswith("svg")

    mp4_req = png_req.model_copy(update={"media_format": "mp4"})
    mp4_fallback = service.generate(mp4_req)
    assert mp4_fallback.media_format == "svg"
    assert mp4_fallback.mime_type == "image/svg+xml"
    assert mp4_fallback.generator_mode == "local_svg_fallback"
    assert mp4_fallback.file_size_bytes == len(mp4_fallback.content_bytes)
    assert ET.fromstring(mp4_fallback.content_bytes.decode("utf-8")).tag.endswith("svg")


def test_ffmpeg_subprocess_failure_falls_back_to_svg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: "fake-ffmpeg")

    def _fail_run(*_args, **_kwargs):
        return subprocess.CompletedProcess(args=["fake-ffmpeg"], returncode=1, stdout=b"", stderr=b"err")

    monkeypatch.setattr(subprocess, "run", _fail_run)

    service = MultimediaEducationService()
    artifact = service.generate(
        HealthMediaRequest(
            topic="Shin Splint Load Check",
            triage_urgency=TriageUrgency.PROMPT_CLINICIAN,
            guidance_summary="Localized tibial tenderness requires clinician assessment.",
            media_format="mp4",
        )
    )
    assert artifact.media_format == "svg"
    assert artifact.mime_type == "image/svg+xml"
    assert artifact.generator_mode == "local_svg_fallback"
    assert ET.fromstring(artifact.content_bytes.decode("utf-8")).tag.endswith("svg")


@pytest.mark.parametrize(
    ("urgency", "requested_running", "expected_effective"),
    [
        (TriageUrgency.EMERGENCY, True, False),
        (TriageUrgency.PROMPT_CLINICIAN, True, False),
        (TriageUrgency.SELF_CARE_NEXT_STEP, None, False),
        (None, True, True),
    ],
)
def test_triage_urgency_monotonic_safety_and_distinct_outputs(
    urgency: TriageUrgency | None,
    requested_running: bool | None,
    expected_effective: bool,
) -> None:
    req = HealthMediaRequest(
        topic="Safety Triage Check",
        body_part="Chest" if urgency == TriageUrgency.EMERGENCY else "Knee",
        triage_urgency=urgency,
        running_allowed=requested_running,
        guidance_summary="Follow deterministic safety triage guidance.",
        media_format="svg",
    )
    assert effective_running_allowed(req) is expected_effective

    service = MultimediaEducationService()
    svg_artifact = service.generate(req)
    svg_text = svg_artifact.content_bytes.decode("utf-8")
    if expected_effective:
        assert "RUNNING ALLOWED" in svg_text
    else:
        assert "RUNNING NOT ALLOWED" in svg_text

    png_artifact = service.generate(req.model_copy(update={"media_format": "png"}))
    assert png_artifact.content_bytes.startswith(b"\x89PNG\r\n\x1a\n")


def test_distinct_rendering_across_triage_urgencies() -> None:
    service = MultimediaEducationService()
    outputs = {}
    for urgency in (
        TriageUrgency.EMERGENCY,
        TriageUrgency.PROMPT_CLINICIAN,
        TriageUrgency.SELF_CARE_NEXT_STEP,
        None,
    ):
        req = HealthMediaRequest(
            topic="Triage Rendering Comparison",
            body_part="Calf",
            triage_urgency=urgency,
            guidance_summary="Compare visual triage cues.",
            media_format="png",
        )
        outputs[urgency] = service.generate(req).content_bytes

    assert len(set(outputs.values())) == 4


def test_bilingual_cjk_punctuation_in_png_and_mp4() -> None:
    service = MultimediaEducationService()
    req = HealthMediaRequest(
        topic="阿基里斯腱負荷管理：第1階段 (Loading)",
        body_part="阿基里斯腱",
        triage_urgency=TriageUrgency.SELF_CARE_NEXT_STEP,
        guidance_summary="請「停止跑步」並觀察疼痛變化：48小時後再評估。",
        next_steps=["「停止跑步」並冰敷", "觀察晨間僵硬"],
        citations=["運動醫學實證指引 v1"],
        media_format="png",
    )
    png_artifact = service.generate(req)
    _parse_png_chunks(png_artifact.content_bytes)

    if shutil.which("ffmpeg"):
        mp4_artifact = service.generate(req.model_copy(update={"media_format": "mp4"}))
        assert mp4_artifact.media_format == "mp4"
        assert mp4_artifact.content_bytes[4:8] == b"ftyp"


@pytest.mark.parametrize("actor_id", [None, "not-a-uuid"])
def test_http_routes_reject_missing_or_malformed_actor_with_403(actor_id: str | None) -> None:
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_actor_provider] = lambda: StaticCurrentActorProvider(
        actor_id
    )
    try:
        client = TestClient(app)
        payload = {
            "topic": "Knee Pain",
            "guidance_summary": "Rest and monitor symptoms.",
            "media_format": "png",
        }
        for path in ("/guidance/media", "/guidance/media/render"):
            resp = client.post(path, json=payload)
            assert resp.status_code == 403
            assert resp.json() == {"error": "NOT_AUTHORIZED"}
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_http_routes_reject_invalid_payloads_with_422(authed_client: TestClient) -> None:
    rejected_extra = authed_client.post(
        "/guidance/media",
        json={
            "topic": "Knee Pain",
            "guidance_summary": "Rest and monitor.",
            "athlete_id": str(uuid.uuid4()),
        },
    )
    assert rejected_extra.status_code == 422

    rejected_format = authed_client.post(
        "/guidance/media",
        json={
            "topic": "Knee Pain",
            "guidance_summary": "Rest and monitor.",
            "media_format": "avi",
        },
    )
    assert rejected_format.status_code == 422

    rejected_blank = authed_client.post(
        "/guidance/media",
        json={
            "topic": "   ",
            "guidance_summary": "Rest and monitor.",
        },
    )
    assert rejected_blank.status_code == 422


def test_http_routes_return_200_json_and_binary_modes(authed_client: TestClient) -> None:
    payload = {
        "topic": "Chest Pain During Run",
        "body_part": "Chest",
        "triage_urgency": "EMERGENCY",
        "running_allowed": True,
        "guidance_summary": "Stop running immediately and seek emergency care.",
        "next_steps": ["Stop running", "Call emergency medical help"],
        "citations": ["ACSM Cardiorespiratory Red Flags"],
        "media_format": "png",
    }

    # 1. Default JSON mode
    json_resp = authed_client.post("/guidance/media", json=payload)
    assert json_resp.status_code == 200
    body = json_resp.json()
    assert body["media_format"] == "png"
    assert body["mime_type"] == "image/png"
    assert body["generator_mode"] == "local_raster"
    assert body["triage_urgency"] == "EMERGENCY"
    decoded = base64.b64decode(body["content_base64"], validate=True)
    assert len(decoded) == body["file_size_bytes"]
    _parse_png_chunks(decoded)

    # 2. Binary query mode on /guidance/media?response_mode=binary
    bin_resp = authed_client.post("/guidance/media?response_mode=binary", json=payload)
    assert bin_resp.status_code == 200
    assert bin_resp.headers["content-type"] == "image/png"
    assert "attachment;" in bin_resp.headers["content-disposition"]
    assert bin_resp.headers["x-asset-id"]
    assert bin_resp.headers["x-media-format"] == "png"
    assert bin_resp.headers["x-generator-mode"] == "local_raster"
    assert bin_resp.headers["x-triage-urgency"] == "EMERGENCY"
    _parse_png_chunks(bin_resp.content)

    # 3. Dedicated /guidance/media/render binary route with SVG
    svg_payload = dict(payload, media_format="svg")
    render_resp = authed_client.post("/guidance/media/render", json=svg_payload)
    assert render_resp.status_code == 200
    assert render_resp.headers["content-type"].startswith("image/svg+xml")
    assert render_resp.headers["x-media-format"] == "svg"
    assert render_resp.headers["x-generator-mode"] == "local_svg_fallback"
    assert render_resp.headers["x-triage-urgency"] == "EMERGENCY"
    svg_text = render_resp.content.decode("utf-8")
    assert "RUNNING NOT ALLOWED" in svg_text
    assert ET.fromstring(svg_text).tag.endswith("svg")


def test_http_mp4_render_and_ffmpeg_missing_header_consistency(
    authed_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "topic": "Heat Pace Safety",
        "body_part": "Systemic",
        "triage_urgency": "PROMPT_CLINICIAN",
        "guidance_summary": "Slow down and hydrate in hot conditions.",
        "media_format": "mp4",
    }

    if shutil.which("ffmpeg"):
        mp4_resp = authed_client.post("/guidance/media/render", json=payload)
        assert mp4_resp.status_code == 200
        assert mp4_resp.headers["content-type"] == "video/mp4"
        assert mp4_resp.headers["x-media-format"] == "mp4"
        assert mp4_resp.headers["x-generator-mode"] == "local_ffmpeg"
        assert mp4_resp.content[4:8] == b"ftyp"

    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    fallback_resp = authed_client.post("/guidance/media/render", json=payload)
    assert fallback_resp.status_code == 200
    assert fallback_resp.headers["content-type"].startswith("image/svg+xml")
    assert fallback_resp.headers["x-media-format"] == "svg"
    assert fallback_resp.headers["x-generator-mode"] == "local_svg_fallback"
    assert ".svg" in fallback_resp.headers["content-disposition"]
    assert ET.fromstring(fallback_resp.content.decode("utf-8")).tag.endswith("svg")


@pytest.mark.parametrize("special_char", ["&", "<", ">", '"', "'"])
def test_svg_athlete_context_xml_entities_straddling_index_30(
    authed_client: TestClient,
    special_char: str,
) -> None:
    context = {
        "note_a": "123456789012345678901" + special_char + "tail",
        "k" + "x" * 24: special_char + "suffix",
        "k" + "y" * 25: special_char + "suffix",
        "k" + "z" * 26: special_char + "suffix",
    }
    req = HealthMediaRequest(
        topic="XML Entity Boundary Check",
        guidance_summary="Ensure athlete_context chips never split XML entities.",
        media_format="svg",
        athlete_context=context,
    )
    artifact = MultimediaEducationService().generate(req)
    svg_text = artifact.content_bytes.decode("utf-8")
    root = ET.fromstring(svg_text)
    assert root.tag.endswith("svg")

    resp = authed_client.post(
        "/guidance/media/render",
        json={
            "topic": "XML Entity HTTP Boundary",
            "guidance_summary": "Ensure /guidance/media/render emits well-formed SVG.",
            "media_format": "svg",
            "athlete_context": context,
        },
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("image/svg+xml")
    http_root = ET.fromstring(resp.content.decode("utf-8"))
    assert http_root.tag.endswith("svg")


def test_svg_strips_xml_illegal_non_characters(authed_client: TestClient) -> None:
    req = HealthMediaRequest(
        topic="Knee \ufffe pain \uffff check",
        body_part="Knee\ufffe",
        guidance_summary="Summary with \ufffe and \uffff non-characters.",
        next_steps=["Rest \ufffe 24h", "Ice \uffff gently"],
        citations=["Evidence \ufffe v1 \uffff"],
        media_format="svg",
        athlete_context={"tag\ufffe": "val\uffff"},
    )
    artifact = MultimediaEducationService().generate(req)
    svg_text = artifact.content_bytes.decode("utf-8")
    assert "\ufffe" not in svg_text
    assert "\uffff" not in svg_text
    assert ET.fromstring(svg_text).tag.endswith("svg")

    resp = authed_client.post(
        "/guidance/media/render",
        json={
            "topic": "Knee \ufffe pain",
            "guidance_summary": "Summary \uffff",
            "media_format": "svg",
        },
    )
    assert resp.status_code == 200
    resp_text = resp.content.decode("utf-8")
    assert "\ufffe" not in resp_text
    assert "\uffff" not in resp_text
    assert ET.fromstring(resp_text).tag.endswith("svg")


def test_external_provider_format_mismatch_falls_back_to_requested_format() -> None:
    svg_bytes = b'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'
    png_req = HealthMediaRequest(
        topic="Format Fidelity Check",
        guidance_summary="PNG request must never accept SVG from external provider.",
        media_format="png",
    )

    # 1. Stub provider returning mismatched format ("svg" for "png" request)
    class MismatchedStubProvider:
        provider_name = "mismatched-stub"

        def is_configured(self) -> bool:
            return True

        def generate(self, request: HealthMediaRequest) -> HealthMediaArtifact | None:
            return HealthMediaArtifact(
                asset_id="ext_svg_1",
                media_format="svg",
                mime_type="image/svg+xml",
                content_bytes=svg_bytes,
                file_size_bytes=len(svg_bytes),
                generator_mode="external_api",
                triage_urgency=None,
            )

    stub_art = MultimediaEducationService(provider=MismatchedStubProvider()).generate(png_req)
    assert stub_art.media_format == "png"
    assert stub_art.mime_type == "image/png"
    assert stub_art.generator_mode == "local_raster"
    _parse_png_chunks(stub_art.content_bytes)

    # 2. HttpMediaProvider returning binary SVG content-type for PNG request
    binary_svg_provider = HttpMediaProvider(
        api_key="test-key",
        api_url="https://media.example.invalid/render",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _r: httpx.Response(
                    200,
                    content=svg_bytes,
                    headers={"content-type": "image/svg+xml"},
                )
            )
        ),
    )
    assert binary_svg_provider.generate(png_req) is None
    http_bin_art = MultimediaEducationService(provider=binary_svg_provider).generate(png_req)
    assert http_bin_art.media_format == "png"
    assert http_bin_art.generator_mode == "local_raster"
    _parse_png_chunks(http_bin_art.content_bytes)

    # 3. HttpMediaProvider returning JSON with media_format="svg" for PNG request
    json_svg_provider = HttpMediaProvider(
        api_key="test-key",
        api_url="https://media.example.invalid/render",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _r: httpx.Response(
                    200,
                    json={
                        "media_format": "svg",
                        "content_base64": base64.b64encode(svg_bytes).decode("ascii"),
                    },
                )
            )
        ),
    )
    assert json_svg_provider.generate(png_req) is None
    http_json_art = MultimediaEducationService(provider=json_svg_provider).generate(png_req)
    assert http_json_art.media_format == "png"
    assert http_json_art.generator_mode == "local_raster"
    _parse_png_chunks(http_json_art.content_bytes)


def test_validate_media_bytes_rejects_truncated_png_and_mp4_and_falls_back() -> None:
    truncated_24b_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    assert not _validate_media_bytes("png", truncated_24b_png)

    # Valid IHDR chunk alone (missing IDAT and IEND) must also be rejected
    ihdr_payload = struct.pack(">IIBBBBB", 10, 10, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_payload) & 0xFFFFFFFF
    ihdr_only_png = (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", len(ihdr_payload))
        + b"IHDR"
        + ihdr_payload
        + struct.pack(">I", ihdr_crc)
    )
    assert not _validate_media_bytes("png", ihdr_only_png)

    # 12-byte and 16-byte ftyp-only MP4 stubs must be rejected
    truncated_12b_mp4 = b"\x00\x00\x00\x10ftypisom"
    ftyp_only_16b_mp4 = b"\x00\x00\x00\x10ftypisom\x00\x00\x00\x00"
    assert not _validate_media_bytes("mp4", truncated_12b_mp4)
    assert not _validate_media_bytes("mp4", ftyp_only_16b_mp4)

    # Valid 64-bit largesize box MP4 layout (ftyp + moov + 64-bit mdat) must be accepted
    ftyp_box = struct.pack(">I4s", 16, b"ftyp") + b"isom" + b"\x00" * 4
    moov_box = struct.pack(">I4s", 16, b"moov") + b"\x00" * 8
    mdat_body = b"\x00" * 8
    mdat_64_box = struct.pack(">I4sQ", 1, b"mdat", 16 + len(mdat_body)) + mdat_body
    assert _validate_media_bytes("mp4", ftyp_box + moov_box + mdat_64_box)

    # Verify external provider returning truncated 24B PNG falls back locally
    class TruncatedPngProvider:
        provider_name = "truncated-png"

        def is_configured(self) -> bool:
            return True

        def generate(self, request: HealthMediaRequest) -> HealthMediaArtifact | None:
            return HealthMediaArtifact(
                asset_id="trunc_1",
                media_format="png",
                mime_type="image/png",
                content_bytes=truncated_24b_png,
                file_size_bytes=len(truncated_24b_png),
                generator_mode="external_api",
                triage_urgency=None,
            )

    png_req = HealthMediaRequest(
        topic="Truncated PNG Check",
        guidance_summary="Ensure truncated external PNG falls back to local raster.",
        media_format="png",
    )
    png_art = MultimediaEducationService(provider=TruncatedPngProvider()).generate(png_req)
    assert png_art.generator_mode == "local_raster"
    _parse_png_chunks(png_art.content_bytes)

    # Verify external provider returning 12B ftyp-only MP4 falls back locally
    class TruncatedMp4Provider:
        provider_name = "truncated-mp4"

        def is_configured(self) -> bool:
            return True

        def generate(self, request: HealthMediaRequest) -> HealthMediaArtifact | None:
            return HealthMediaArtifact(
                asset_id="trunc_mp4",
                media_format="mp4",
                mime_type="video/mp4",
                content_bytes=truncated_12b_mp4,
                file_size_bytes=len(truncated_12b_mp4),
                generator_mode="external_api",
                triage_urgency=None,
            )

    mp4_req = png_req.model_copy(update={"media_format": "mp4"})
    mp4_art = MultimediaEducationService(provider=TruncatedMp4Provider()).generate(mp4_req)
    assert mp4_art.generator_mode in ("local_ffmpeg", "local_svg_fallback")
    assert _validate_media_bytes(mp4_art.media_format, mp4_art.content_bytes)


@pytest.mark.parametrize("raw_timeout", ["inf", "-inf", "nan", "NaN", "not-a-float"])
def test_non_finite_media_timeout_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
    raw_timeout: str,
) -> None:
    monkeypatch.setenv("RUNSENCE_MEDIA_API_KEY", "test-key")
    monkeypatch.setenv("RUNSENCE_MEDIA_API_URL", "https://media.example.invalid/render")
    monkeypatch.setenv("RUNSENCE_MEDIA_TIMEOUT_SECONDS", raw_timeout)

    provider = configured_media_provider()
    assert isinstance(provider, HttpMediaProvider)
    assert math.isfinite(provider._timeout_seconds)
    assert provider._timeout_seconds == 8.0

    direct = HttpMediaProvider(
        api_key="test-key",
        api_url="https://media.example.invalid/render",
        timeout_seconds=float("inf"),
    )
    assert direct._timeout_seconds == 8.0


def test_self_care_running_allowed_override_and_item_bounds() -> None:
    default_req = HealthMediaRequest(
        topic="Self-Care Default",
        triage_urgency=TriageUrgency.SELF_CARE_NEXT_STEP,
        guidance_summary="Default SELF_CARE blocks running unless caller overrides.",
    )
    assert effective_running_allowed(default_req) is False

    override_req = default_req.model_copy(update={"running_allowed": True})
    assert effective_running_allowed(override_req) is True

    with pytest.raises(ValidationError):
        HealthMediaRequest(
            topic="Oversized Step",
            guidance_summary="Valid summary",
            next_steps=["x" * 501],
        )

    with pytest.raises(ValidationError):
        HealthMediaRequest(
            topic="Oversized Citation",
            guidance_summary="Valid summary",
            citations=["c" * 501],
        )


def test_athlete_context_lone_surrogates_service_all_formats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    surrogate_context = {
        "note\ud800": "val\ud83d",
        "emoji": "ok🏃",
        "nested": {"deep\udfff": ["item\ud800", {"inner": "x\ud83dy"}]},
        "acwr": 1.45,
    }

    req = HealthMediaRequest(
        topic="Surrogate Resilience Check",
        guidance_summary="Ensure lone UTF-16 surrogates in athlete_context never fail.",
        media_format="svg",
        athlete_context=surrogate_context,
    )
    # Validated request serializes cleanly to UTF-8 JSON
    dumped = req.model_dump_json()
    assert json.loads(dumped)["athlete_context"]["note"] == "val"
    assert json.loads(dumped)["athlete_context"]["emoji"] == "ok🏃"

    service = MultimediaEducationService()

    # 1. SVG (both validated and model_copy bypassing validator)
    svg_art = service.generate(req)
    assert svg_art.media_format == "svg"
    svg_text = svg_art.content_bytes.decode("utf-8")
    assert "ok🏃" in svg_text
    assert ET.fromstring(svg_text).tag.endswith("svg")

    bypass_svg_req = req.model_copy(update={"athlete_context": surrogate_context})
    bypass_svg_art = service.generate(bypass_svg_req)
    assert ET.fromstring(bypass_svg_art.content_bytes.decode("utf-8")).tag.endswith("svg")

    # 2. PNG (including model_copy bypass)
    png_req = req.model_copy(update={"media_format": "png", "athlete_context": surrogate_context})
    png_art = service.generate(png_req)
    assert png_art.media_format == "png"
    _parse_png_chunks(png_art.content_bytes)

    # 3. MP4 with ffmpeg present (when installed)
    mp4_req = req.model_copy(update={"media_format": "mp4", "athlete_context": surrogate_context})
    if shutil.which("ffmpeg"):
        mp4_art = service.generate(mp4_req)
        assert mp4_art.media_format == "mp4"
        assert _validate_media_bytes("mp4", mp4_art.content_bytes)

    # 4. MP4 with ffmpeg missing -> falls back cleanly to valid SVG
    monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
    mp4_fallback = service.generate(mp4_req)
    assert mp4_fallback.media_format == "svg"
    assert mp4_fallback.generator_mode == "local_svg_fallback"
    assert ET.fromstring(mp4_fallback.content_bytes.decode("utf-8")).tag.endswith("svg")


def test_http_media_provider_strips_surrogates_in_athlete_context() -> None:
    valid_png = MultimediaEducationService().generate(
        HealthMediaRequest(
            topic="Valid PNG",
            guidance_summary="Generate reference PNG.",
            media_format="png",
        )
    ).content_bytes

    captured_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        decoded_body = request.content.decode("utf-8")
        captured_payloads.append(json.loads(decoded_body))
        return httpx.Response(200, content=valid_png, headers={"content-type": "image/png"})

    provider = HttpMediaProvider(
        api_key="test-key",
        api_url="https://media.example.invalid/render",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    surrogate_context = {
        "k\ud800": "v\ud83d",
        "nested": [{"inner\udfff": "x\ud800y"}, "plain\ud83d"],
        "emoji": "🏃",
    }
    # Use model_copy to bypass Pydantic validator and exercise HttpMediaProvider directly
    base_req = HealthMediaRequest(
        topic="External Provider Surrogate Check",
        guidance_summary="Provider must sanitize surrogates before JSON encoding.",
        media_format="png",
    )
    req = base_req.model_copy(update={"athlete_context": surrogate_context})

    direct_art = provider.generate(req)
    assert direct_art is not None
    assert direct_art.generator_mode == "external_api"
    assert direct_art.content_bytes == valid_png

    svc_art = MultimediaEducationService(provider=provider).generate(req)
    assert svc_art.generator_mode == "external_api"
    assert svc_art.content_bytes == valid_png

    assert len(captured_payloads) == 2
    sent_ctx = captured_payloads[0]["athlete_context"]
    assert sent_ctx == {
        "k": "v",
        "nested": [{"inner": "xy"}, "plain"],
        "emoji": "🏃",
    }


@pytest.mark.parametrize("media_format", ["svg", "png", "mp4"])
def test_http_routes_accept_raw_json_surrogates_in_athlete_context(
    authed_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    media_format: str,
) -> None:
    raw_json = (
        '{"topic": "Knee Pain", '
        '"guidance_summary": "Monitor pain and rest.", '
        f'"media_format": "{media_format}", '
        '"athlete_context": {'
        '"key\\uD800": "val\\uD83D", '
        '"tail\\uDFFF": "ok\\uD83D\\uDE00", '
        '"nested": {"sub\\uD800": ["a\\uD83D", "b\\uDFFF"]}, '
        '"acwr": 1.35'
        "}}"
    ).encode("utf-8")
    headers = {"content-type": "application/json"}

    def _assert_artifact_bytes(fmt: str, raw_bytes: bytes) -> None:
        if fmt == "svg":
            svg_text = raw_bytes.decode("utf-8")
            assert "😀" in svg_text
            assert ET.fromstring(svg_text).tag.endswith("svg")
        elif fmt == "png":
            _parse_png_chunks(raw_bytes)
        else:
            assert _validate_media_bytes("mp4", raw_bytes)

    # Run against current host ffmpeg availability (or SVG fallback if absent)
    json_resp = authed_client.post("/guidance/media?response_mode=json", content=raw_json, headers=headers)
    assert json_resp.status_code == 200
    body = json_resp.json()
    decoded = base64.b64decode(body["content_base64"], validate=True)
    _assert_artifact_bytes(body["media_format"], decoded)

    bin_resp = authed_client.post(
        "/guidance/media?response_mode=binary", content=raw_json, headers=headers
    )
    assert bin_resp.status_code == 200
    _assert_artifact_bytes(bin_resp.headers["x-media-format"], bin_resp.content)

    render_resp = authed_client.post("/guidance/media/render", content=raw_json, headers=headers)
    assert render_resp.status_code == 200
    _assert_artifact_bytes(render_resp.headers["x-media-format"], render_resp.content)

    # Also explicitly test mp4 -> svg fallback when ffmpeg is unavailable
    if media_format == "mp4":
        monkeypatch.setattr(shutil, "which", lambda *_a, **_k: None)
        fb_json = authed_client.post(
            "/guidance/media?response_mode=json", content=raw_json, headers=headers
        )
        assert fb_json.status_code == 200
        fb_body = fb_json.json()
        assert fb_body["media_format"] == "svg"
        assert fb_body["generator_mode"] == "local_svg_fallback"
        _assert_artifact_bytes("svg", base64.b64decode(fb_body["content_base64"], validate=True))

        fb_bin = authed_client.post(
            "/guidance/media?response_mode=binary", content=raw_json, headers=headers
        )
        assert fb_bin.status_code == 200
        assert fb_bin.headers["x-media-format"] == "svg"
        _assert_artifact_bytes("svg", fb_bin.content)

        fb_render = authed_client.post("/guidance/media/render", content=raw_json, headers=headers)
        assert fb_render.status_code == 200
        assert fb_render.headers["x-media-format"] == "svg"
        _assert_artifact_bytes("svg", fb_render.content)


def test_http_media_provider_normalizes_nan_inf_in_athlete_context_and_http_route(
    authed_client: TestClient,
) -> None:
    valid_png = MultimediaEducationService().generate(
        HealthMediaRequest(
            topic="Valid PNG",
            guidance_summary="Reference PNG bytes.",
            media_format="png",
        )
    ).content_bytes

    captured_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured_payloads.append(json.loads(request.content.decode("utf-8")))
        return httpx.Response(200, content=valid_png, headers={"content-type": "image/png"})

    provider = HttpMediaProvider(
        api_key="test-key",
        api_url="https://media.example.invalid/render",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    nan_context = {
        "acwr": float("nan"),
        "heat_loss_pct": float("inf"),
        "resting_hr_delta": float("-inf"),
        "nested": [float("nan"), {"peak": float("inf")}],
        "sleep_hours": 7.5,
    }
    base_req = HealthMediaRequest(
        topic="NaN Inf Provider Check",
        guidance_summary="Non-finite floats must normalize to null before httpx JSON encoding.",
        media_format="png",
        athlete_context=nan_context,
    )
    assert base_req.athlete_context == {
        "acwr": None,
        "heat_loss_pct": None,
        "resting_hr_delta": None,
        "nested": [None, {"peak": None}],
        "sleep_hours": 7.5,
    }

    # Direct provider + service via model_copy bypass
    bypass_req = base_req.model_copy(update={"athlete_context": nan_context})
    direct_art = provider.generate(bypass_req)
    assert direct_art is not None
    assert direct_art.generator_mode == "external_api"

    svc_art = MultimediaEducationService(provider=provider).generate(bypass_req)
    assert svc_art.generator_mode == "external_api"
    assert len(captured_payloads) == 2
    assert captured_payloads[0]["athlete_context"] == base_req.athlete_context

    # HTTP route with JSON overflow 1e500 -> float('inf') must invoke provider (calls += 1)
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_multimedia_education_service] = lambda: MultimediaEducationService(
        provider=provider
    )
    try:
        raw_json = (
            b'{"topic": "Inf Test", "guidance_summary": "Check 1e500 overflow", '
            b'"media_format": "png", '
            b'"athlete_context": {"acwr": 1e500, "neg": -1e500, "ok": 1.25}}'
        )
        resp = authed_client.post(
            "/guidance/media?response_mode=json",
            content=raw_json,
            headers={"content-type": "application/json"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["generator_mode"] == "external_api"
        assert len(captured_payloads) == 3
        assert captured_payloads[2]["athlete_context"] == {
            "acwr": None,
            "neg": None,
            "ok": 1.25,
        }
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_deep_nested_athlete_context_1500_levels_without_recursion_error() -> None:
    leaf: dict = {"bad\ud800": "x\ud83dy", "nan_val": float("nan"), "emoji": "🏃"}
    deep_ctx: dict = leaf
    for idx in range(1500):
        if idx % 3 == 0:
            deep_ctx = {"wrap\udfff": [deep_ctx]}
        elif idx % 3 == 1:
            deep_ctx = {"tuple_wrap": (deep_ctx,)}
        else:
            deep_ctx = {"dict_wrap": deep_ctx}

    req = HealthMediaRequest(
        topic="Deep Nesting Resilience",
        guidance_summary="1500+ nested containers must sanitize without RecursionError.",
        media_format="svg",
        athlete_context=deep_ctx,
    )

    cursor: object = req.athlete_context
    for idx in range(1499, -1, -1):
        assert isinstance(cursor, dict)
        if idx % 3 == 0:
            cursor = cursor["wrap"][0]
        elif idx % 3 == 1:
            assert isinstance(cursor["tuple_wrap"], tuple)
            cursor = cursor["tuple_wrap"][0]
        else:
            cursor = cursor["dict_wrap"]
    assert cursor == {"bad": "xy", "nan_val": None, "emoji": "🏃"}

    svg_art = MultimediaEducationService().generate(req)
    assert ET.fromstring(svg_art.content_bytes.decode("utf-8")).tag.endswith("svg")

    valid_png = MultimediaEducationService().generate(
        req.model_copy(update={"media_format": "png", "athlete_context": None})
    ).content_bytes
    provider = HttpMediaProvider(
        api_key="test-key",
        api_url="https://media.example.invalid/render",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _r: httpx.Response(200, content=valid_png, headers={"content-type": "image/png"})
            )
        ),
    )
    png_req = req.model_copy(update={"media_format": "png", "athlete_context": deep_ctx})
    assert provider.generate(png_req) is not None


def test_http_routes_handle_top_level_lone_surrogates_without_500(
    authed_client: TestClient,
) -> None:
    headers = {"content-type": "application/json"}

    # 1. Non-empty after surrogate stripping -> 200 OK
    valid_raw = (
        '{"topic": "Knee \\uD800 Pain", '
        '"body_part": "Patella\\uD83D", '
        '"guidance_summary": "Rest \\uDFFF and monitor.", '
        '"next_steps": ["Ice \\uD800 gently", "\\uD800"], '
        '"citations": ["ACSM \\uD83D Guide"], '
        '"media_format": "svg"}'
    ).encode("utf-8")
    ok_resp = authed_client.post("/guidance/media/render", content=valid_raw, headers=headers)
    assert ok_resp.status_code == 200
    svg_text = ok_resp.content.decode("utf-8")
    assert "Knee  Pain" in svg_text
    assert "Patella" in svg_text
    assert "Rest  and monitor." in svg_text
    assert "Ice  gently" in svg_text
    assert "ACSM  Guide" in svg_text
    assert ET.fromstring(svg_text).tag.endswith("svg")

    # 2. Empty or whitespace-only after surrogate stripping -> clean 422 (never 500)
    for bad_raw in (
        b'{"topic": "\\uD800", "guidance_summary": "Rest"}',
        b'{"topic": "  \\uD800  ", "guidance_summary": "Rest"}',
        b'{"topic": "Knee", "guidance_summary": "\\uD83D"}',
    ):
        err_resp = authed_client.post("/guidance/media", content=bad_raw, headers=headers)
        assert err_resp.status_code == 422
        err_json = err_resp.json()
        assert "detail" in err_json


def test_validate_media_bytes_rejects_png_with_non_zlib_idat_and_valid_crc() -> None:
    def _chunk(tag: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)

    ihdr_payload = struct.pack(">IIBBBBB", 10, 10, 8, 2, 0, 0, 0)
    fake_png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr_payload)
        + _chunk(b"IDAT", b"NOT_ZLIB")
        + _chunk(b"IEND", b"")
    )
    assert not _validate_media_bytes("png", fake_png)

    class FakeIdatProvider:
        provider_name = "fake-idat"

        def is_configured(self) -> bool:
            return True

        def generate(self, request: HealthMediaRequest) -> HealthMediaArtifact | None:
            return HealthMediaArtifact(
                asset_id="fake_idat_1",
                media_format="png",
                mime_type="image/png",
                content_bytes=fake_png,
                file_size_bytes=len(fake_png),
                generator_mode="external_api",
                triage_urgency=None,
            )

    fallback_art = MultimediaEducationService(provider=FakeIdatProvider()).generate(
        HealthMediaRequest(
            topic="Fake IDAT Fallback",
            guidance_summary="Reject PNG with valid CRC32 on non-zlib IDAT.",
            media_format="png",
        )
    )
    assert fallback_art.generator_mode == "local_raster"
    _parse_png_chunks(fallback_art.content_bytes)


@pytest.mark.parametrize(
    "raw_body",
    [
        b'"\\uD800"',
        b'"hello\\uD83D"',
        b'["\\uD800"]',
        b'["a", "\\uDFFF"]',
        b"1e500",
        b"[1e500]",
        b"[-1e500]",
        b"NaN",
    ],
)
@pytest.mark.parametrize(
    "path",
    [
        "/guidance/media?response_mode=json",
        "/guidance/media?response_mode=binary",
        "/guidance/media/render",
    ],
)
def test_http_routes_reject_non_dict_json_with_surrogates_or_non_finite_floats_as_422(
    authed_client: TestClient,
    path: str,
    raw_body: bytes,
) -> None:
    resp = authed_client.post(
        path,
        content=raw_body,
        headers={"content-type": "application/json"},
    )
    assert resp.status_code == 422
    payload = resp.json()
    assert "detail" in payload
    assert isinstance(payload["detail"], list)


def test_sanitize_surrogates_allows_shared_dag_and_rejects_cycles() -> None:
    # Shared-reference DAG (non-cyclic) must succeed and sanitize every branch.
    shared_leaf = {"note": "ice\ud800", "metric": float("nan")}
    shared_list = ["step\udfff", shared_leaf]
    dag_context = {
        "left": shared_leaf,
        "right": shared_list,
        "tuple_branch": (shared_leaf, shared_list),
    }
    req = HealthMediaRequest(
        topic="DAG Athlete Context",
        guidance_summary="Shared references in a DAG must sanitize without false cycle errors.",
        media_format="svg",
        athlete_context=dag_context,
    )
    expected_leaf = {"note": "ice", "metric": None}
    assert req.athlete_context == {
        "left": expected_leaf,
        "right": ["step", expected_leaf],
        "tuple_branch": (expected_leaf, ["step", expected_leaf]),
    }

    # Self-referential cyclic dict, cyclic list, and tuple->list cycle must raise ValueError cleanly.
    cyclic_dict: dict = {}
    cyclic_dict["self"] = cyclic_dict
    with pytest.raises(ValueError, match="cyclic container in input"):
        _sanitize_surrogates_value(cyclic_dict)
    with pytest.raises(ValidationError, match="cyclic container in input"):
        HealthMediaRequest(
            topic="Cyclic Dict",
            guidance_summary="Reject cyclic dict.",
            athlete_context=cyclic_dict,
        )

    cyclic_list: list = []
    cyclic_list.append(cyclic_list)
    with pytest.raises(ValueError, match="cyclic container in input"):
        _sanitize_surrogates_value(cyclic_list)
    with pytest.raises(ValidationError, match="cyclic container in input"):
        HealthMediaRequest(
            topic="Cyclic List",
            guidance_summary="Reject cyclic list.",
            athlete_context={"items": cyclic_list},
        )

    inner_list: list = []
    cyclic_tuple = (inner_list,)
    inner_list.append(cyclic_tuple)
    with pytest.raises(ValueError, match="cyclic container in input"):
        _sanitize_surrogates_value(cyclic_tuple)


def test_validate_media_bytes_rejects_truncated_and_oversized_png_idat() -> None:
    def _chunk(tag: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)

    ihdr_payload = struct.pack(">IIBBBBB", 10, 10, 8, 2, 0, 0, 0)

    truncated_zlib = zlib.compress(b"\x00" * 310)[:-4]
    truncated_png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr_payload)
        + _chunk(b"IDAT", truncated_zlib)
        + _chunk(b"IEND", b"")
    )
    assert not _validate_media_bytes("png", truncated_png)

    oversized_zlib = zlib.compress(b"\x00" * (65 * 1024 * 1024))
    oversized_png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr_payload)
        + _chunk(b"IDAT", oversized_zlib)
        + _chunk(b"IEND", b"")
    )
    assert not _validate_media_bytes("png", oversized_png)


def test_validate_media_bytes_rejects_png_with_trailing_garbage_inside_idat() -> None:
    def _chunk(tag: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)

    ihdr_payload = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    trailing_idat_png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr_payload)
        + _chunk(b"IDAT", zlib.compress(b"\x00\x01\x02\x03") + b"TRAILING_GARBAGE_INSIDE_IDAT")
        + _chunk(b"IEND", b"")
    )
    assert not _is_valid_png(trailing_idat_png)
    assert not _validate_media_bytes("png", trailing_idat_png)

    concatenated_zlib_png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr_payload)
        + _chunk(b"IDAT", zlib.compress(b"\x00\x01\x02\x03") + zlib.compress(b"\x00"))
        + _chunk(b"IEND", b"")
    )
    assert not _is_valid_png(concatenated_zlib_png)
    assert not _validate_media_bytes("png", concatenated_zlib_png)

    class TrailingIdatProvider:
        provider_name = "trailing-idat"

        def is_configured(self) -> bool:
            return True

        def generate(self, request: HealthMediaRequest) -> HealthMediaArtifact | None:
            return HealthMediaArtifact(
                asset_id="trailing_idat_1",
                media_format="png",
                mime_type="image/png",
                content_bytes=trailing_idat_png,
                file_size_bytes=len(trailing_idat_png),
                generator_mode="external_api",
                triage_urgency=None,
            )

    fallback_art = MultimediaEducationService(provider=TrailingIdatProvider()).generate(
        HealthMediaRequest(
            topic="Trailing IDAT Fallback",
            guidance_summary="Reject PNG with trailing garbage inside IDAT and fall back.",
            media_format="png",
        )
    )
    assert fallback_art.generator_mode == "local_raster"
    _parse_png_chunks(fallback_art.content_bytes)


def test_sanitize_surrogates_handles_deep_diamond_dag_linearly_and_preserves_tuples() -> None:
    depth = 35
    list_dag: list = ["\ud800", float("nan")]
    for _ in range(depth):
        list_dag = [list_dag, list_dag]

    mixed_dag: dict = {"msg\udfff": ("step\ud800", float("inf")), "metric": float("nan")}
    for _ in range(depth):
        mixed_dag = {"a": mixed_dag, "b": (mixed_dag, mixed_dag)}

    started = time.perf_counter()
    sanitized_list = _sanitize_surrogates_value(list_dag)
    req = HealthMediaRequest(
        topic="Deep Diamond DAG",
        guidance_summary="Diamond DAG sanitization must run in linear time.",
        media_format="svg",
        athlete_context={"list_dag": list_dag, "mixed_dag": mixed_dag},
    )
    elapsed = time.perf_counter() - started
    assert elapsed < 0.2

    cursor_list = sanitized_list
    for _ in range(depth):
        assert isinstance(cursor_list, list)
        assert cursor_list[0] is cursor_list[1]
        cursor_list = cursor_list[0]
    assert cursor_list == ["", None]

    cursor_mixed = req.athlete_context["mixed_dag"]
    for _ in range(depth):
        assert isinstance(cursor_mixed, dict)
        assert isinstance(cursor_mixed["b"], tuple)
        assert cursor_mixed["a"] is cursor_mixed["b"][0]
        assert cursor_mixed["b"][0] is cursor_mixed["b"][1]
        cursor_mixed = cursor_mixed["b"][1]
    assert cursor_mixed == {"msg": ("step", None), "metric": None}
    assert isinstance(cursor_mixed["msg"], tuple)

    # Active-ancestor cycle detection must remain intact after memoization changes.
    cyclic_list: list = []
    cyclic_list.append(cyclic_list)
    with pytest.raises(ValueError, match="cyclic container in input"):
        _sanitize_surrogates_value(cyclic_list)

    inner_list: list = []
    cyclic_tuple = (inner_list,)
    inner_list.append(cyclic_tuple)
    with pytest.raises(ValidationError, match="cyclic container in input"):
        HealthMediaRequest(
            topic="Cyclic Tuple",
            guidance_summary="Reject tuple->list->tuple cycle.",
            athlete_context={"cycle": cyclic_tuple},
        )

    svg_art = MultimediaEducationService().generate(req)
    assert svg_art.generator_mode == "local_svg_fallback"
    assert _validate_media_bytes("svg", svg_art.content_bytes)


def test_health_media_get_retrieval_and_cross_actor_isolation() -> None:
    actor_a = str(uuid.uuid4())
    actor_b = str(uuid.uuid4())
    current_actor = [actor_a]
    previous = dict(app.dependency_overrides)
    app.dependency_overrides[get_current_actor_provider] = (
        lambda: StaticCurrentActorProvider(current_actor[0])
    )
    try:
        client = TestClient(app)
        created = client.post(
            "/guidance/media",
            json={
                "topic": "Shin Splint Guard",
                "guidance_summary": "Stop impact drills when localized bone pain worsens.",
                "media_format": "png",
            },
        )
        assert created.status_code == 200
        body = created.json()
        asset_id = body["asset_id"]
        expected_bytes = base64.b64decode(body["content_base64"])

        fetched = client.get(f"/guidance/media/{asset_id}")
        assert fetched.status_code == 200
        assert fetched.headers["content-type"] == "image/png"
        assert fetched.content == expected_bytes

        current_actor[0] = actor_b
        denied = client.get(f"/guidance/media/{asset_id}")
        assert denied.status_code == 404
        assert client.get("/guidance/media/nonexistent-asset").status_code == 404
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def test_png_with_telemetry_bars_retains_valid_footer_and_disclaimer_layout() -> None:
    req = HealthMediaRequest(
        topic="Heat & ACWR Readiness",
        guidance_summary="Dial back interval intensity under heat strain.",
        media_format="png",
        citations=["ACSM Heat Exertion Consensus"],
        athlete_context={"acwr": 1.25, "temperature_c": 32.0, "sleep_hours": 6.0},
    )
    canvas = _render_png_canvas(req)
    assert canvas.shape == (500, 800, 3)
    # Right-side footer disclaimer region must contain non-background text pixels.
    footer_right = canvas[448:462, 514:756, :]
    assert int((footer_right != (15, 23, 42)).sum()) > 100

    png_art = MultimediaEducationService().generate(req)
    assert _is_valid_png(png_art.content_bytes)
