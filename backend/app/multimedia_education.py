"""Deterministic multimedia health-education rendering and provider fallback."""

from __future__ import annotations

import base64
from collections import OrderedDict
from dataclasses import dataclass
import logging
import math
import os
import re
import reprlib
import shutil
import struct
import subprocess
import tempfile
import threading
from typing import Annotated, Any, Literal, Protocol
import uuid
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
import zlib

import httpx
import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.injury_guidance import DISCLAIMER
from app.safety_triage import TriageUrgency


logger = logging.getLogger(__name__)

MediaFormat = Literal["png", "mp4", "svg"]
GeneratorMode = Literal["external_api", "local_ffmpeg", "local_raster", "local_svg_fallback"]

_MIME_TYPES: dict[MediaFormat, str] = {
    "png": "image/png",
    "mp4": "video/mp4",
    "svg": "image/svg+xml",
}

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_PNG_IDAT_BYTES = 64 * 1024 * 1024
_SURROGATE_CHARS_RE = re.compile(r"[\ud800-\udfff]")
_XML_ILLEGAL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff\ufffe\uffff]")


def _strip_surrogates(text: str) -> str:
    return _SURROGATE_CHARS_RE.sub("", text)


def _sanitize_surrogates_value(value: Any) -> Any:
    """Iteratively strip lone UTF-16 surrogates and map non-finite floats to None."""
    if isinstance(value, str):
        return _strip_surrogates(value)
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if not isinstance(value, (dict, list, tuple)):
        return value

    root_holder: list[Any] = [None]
    active_ids: set[int] = set()
    memo: dict[int, Any] = {}
    # Keep input containers alive until traversal completes so Python cannot reuse id().
    keepalive: list[Any] = []
    # Explicit stack avoids Python recursion limits on >1000-level nested payloads.
    stack: list[tuple[str, Any, Any, Any]] = [("assign", value, root_holder, 0)]

    while stack:
        op, node, target, key = stack.pop()
        if op == "exit":
            active_ids.discard(node)
            memo[node] = target
            continue
        if op == "tuple":
            t_node_id, temp_list = node
            finalized = tuple(temp_list)
            active_ids.discard(t_node_id)
            memo[t_node_id] = finalized
            target[key] = finalized
            continue

        if isinstance(node, str):
            target[key] = _strip_surrogates(node)
        elif isinstance(node, float):
            target[key] = None if not math.isfinite(node) else node
        elif isinstance(node, dict):
            node_id = id(node)
            if node_id in active_ids:
                raise ValueError("cyclic container in input")
            if node_id in memo:
                target[key] = memo[node_id]
                continue
            active_ids.add(node_id)
            keepalive.append(node)
            out_dict: dict[Any, Any] = {}
            target[key] = out_dict
            stack.append(("exit", node_id, out_dict, None))
            for raw_k, raw_v in reversed(list(node.items())):
                if isinstance(raw_k, str):
                    clean_k: Any = _strip_surrogates(raw_k)
                elif isinstance(raw_k, float) and not math.isfinite(raw_k):
                    clean_k = None
                else:
                    clean_k = raw_k
                stack.append(("assign", raw_v, out_dict, clean_k))
        elif isinstance(node, list):
            node_id = id(node)
            if node_id in active_ids:
                raise ValueError("cyclic container in input")
            if node_id in memo:
                target[key] = memo[node_id]
                continue
            active_ids.add(node_id)
            keepalive.append(node)
            out_list = [None] * len(node)
            target[key] = out_list
            stack.append(("exit", node_id, out_list, None))
            for idx in range(len(node) - 1, -1, -1):
                stack.append(("assign", node[idx], out_list, idx))
        elif isinstance(node, tuple):
            node_id = id(node)
            if node_id in active_ids:
                raise ValueError("cyclic container in input")
            if node_id in memo:
                target[key] = memo[node_id]
                continue
            active_ids.add(node_id)
            keepalive.append(node)
            temp_list = [None] * len(node)
            stack.append(("tuple", (node_id, temp_list), target, key))
            for idx in range(len(node) - 1, -1, -1):
                stack.append(("assign", node[idx], temp_list, idx))
        else:
            target[key] = node

    return root_holder[0]

_CJK_TERM_MAP: tuple[tuple[str, str], ...] = (
    ("阿基里斯腱", "ACHILLES TENDON"),
    ("阿基里斯", "ACHILLES"),
    ("跟腱", "ACHILLES"),
    ("髂脛束", "IT BAND"),
    ("跑者膝", "RUNNER KNEE"),
    ("髕骨", "PATELLA"),
    ("膝蓋", "KNEE"),
    ("足底筋膜", "PLANTAR FASCIA"),
    ("足底", "PLANTAR FOOT"),
    ("腳底", "FOOT"),
    ("腳踝", "ANKLE"),
    ("小腿", "CALF"),
    ("脛骨", "TIBIA SHIN"),
    ("膕繩肌", "HAMSTRING"),
    ("股四頭肌", "QUADRICEPS"),
    ("髖關節", "HIP"),
    ("下背", "LOWER BACK"),
    ("胸痛", "CHEST PAIN"),
    ("胸悶", "CHEST TIGHTNESS"),
    ("呼吸困難", "BREATHING ISSUE"),
    ("中暑", "HEAT ILLNESS"),
    ("熱衰竭", "HEAT EXHAUSTION"),
    ("頭暈", "DIZZINESS"),
    ("昏倒", "COLLAPSE"),
    ("麻木", "NUMBNESS"),
    ("骨痛", "BONE PAIN"),
    ("腫脹", "SWELLING"),
    ("發燒", "FEVER"),
    ("負荷管理", "LOAD MGMT"),
    ("負荷", "LOAD"),
    ("訓練量", "TRAINING LOAD"),
    ("停止跑步", "STOP RUNNING"),
    ("暫停跑步", "PAUSE RUNNING"),
    ("立即就醫", "URGENT CARE"),
    ("就醫", "SEE CLINICIAN"),
    ("醫師", "CLINICIAN"),
    ("緊急", "EMERGENCY"),
    ("自我照護", "SELF CARE"),
    ("觀察", "MONITOR"),
    ("休息", "REST"),
    ("冰敷", "ICE"),
    ("伸展", "MOBILITY"),
    ("熱身", "WARMUP"),
    ("恢復", "RECOVERY"),
    ("補水", "HYDRATION"),
    ("階段", "PHASE"),
    ("跑者", "RUNNER"),
    ("衛教", "HEALTH GUIDE"),
)

# Compact 5x7 uppercase/ASCII bitmap glyphs (each row is a 5-bit mask, MSB on left).
_FONT_5X7: dict[str, tuple[int, int, int, int, int, int, int]] = {
    " ": (0, 0, 0, 0, 0, 0, 0),
    "A": (0b01110, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001),
    "B": (0b11110, 0b10001, 0b10001, 0b11110, 0b10001, 0b10001, 0b11110),
    "C": (0b01110, 0b10001, 0b10000, 0b10000, 0b10000, 0b10001, 0b01110),
    "D": (0b11100, 0b10010, 0b10001, 0b10001, 0b10001, 0b10010, 0b11100),
    "E": (0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b11111),
    "F": (0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b10000),
    "G": (0b01110, 0b10001, 0b10000, 0b10111, 0b10001, 0b10001, 0b01110),
    "H": (0b10001, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001),
    "I": (0b01110, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110),
    "J": (0b00111, 0b00010, 0b00010, 0b00010, 0b10010, 0b10010, 0b01100),
    "K": (0b10001, 0b10010, 0b10100, 0b11000, 0b10100, 0b10010, 0b10001),
    "L": (0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b11111),
    "M": (0b10001, 0b11011, 0b10101, 0b10101, 0b10001, 0b10001, 0b10001),
    "N": (0b10001, 0b11001, 0b10101, 0b10011, 0b10001, 0b10001, 0b10001),
    "O": (0b01110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110),
    "P": (0b11110, 0b10001, 0b10001, 0b11110, 0b10000, 0b10000, 0b10000),
    "Q": (0b01110, 0b10001, 0b10001, 0b10001, 0b10101, 0b10010, 0b01101),
    "R": (0b11110, 0b10001, 0b10001, 0b11110, 0b10100, 0b10010, 0b10001),
    "S": (0b01111, 0b10000, 0b10000, 0b01110, 0b00001, 0b00001, 0b11110),
    "T": (0b11111, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100),
    "U": (0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110),
    "V": (0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01010, 0b00100),
    "W": (0b10001, 0b10001, 0b10001, 0b10101, 0b10101, 0b11011, 0b10001),
    "X": (0b10001, 0b10001, 0b01010, 0b00100, 0b01010, 0b10001, 0b10001),
    "Y": (0b10001, 0b10001, 0b01010, 0b00100, 0b00100, 0b00100, 0b00100),
    "Z": (0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b10000, 0b11111),
    "0": (0b01110, 0b10011, 0b10101, 0b10101, 0b11001, 0b10001, 0b01110),
    "1": (0b00100, 0b01100, 0b00100, 0b00100, 0b00100, 0b00100, 0b01110),
    "2": (0b01110, 0b10001, 0b00001, 0b00110, 0b01000, 0b10000, 0b11111),
    "3": (0b11110, 0b00001, 0b00001, 0b01110, 0b00001, 0b00001, 0b11110),
    "4": (0b00010, 0b00110, 0b01010, 0b10010, 0b11111, 0b00010, 0b00010),
    "5": (0b11111, 0b10000, 0b10000, 0b11110, 0b00001, 0b00001, 0b11110),
    "6": (0b01110, 0b10000, 0b10000, 0b11110, 0b10001, 0b10001, 0b01110),
    "7": (0b11111, 0b00001, 0b00010, 0b00100, 0b01000, 0b01000, 0b01000),
    "8": (0b01110, 0b10001, 0b10001, 0b01110, 0b10001, 0b10001, 0b01110),
    "9": (0b01110, 0b10001, 0b10001, 0b01111, 0b00001, 0b00001, 0b01110),
    ":": (0b00000, 0b00100, 0b00100, 0b00000, 0b00100, 0b00100, 0b00000),
    "/": (0b00001, 0b00010, 0b00010, 0b00100, 0b01000, 0b01000, 0b10000),
    "-": (0b00000, 0b00000, 0b00000, 0b11111, 0b00000, 0b00000, 0b00000),
    ".": (0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b01100, 0b01100),
    "%": (0b11001, 0b11010, 0b00010, 0b00100, 0b01000, 0b01011, 0b10011),
    "+": (0b00000, 0b00100, 0b00100, 0b11111, 0b00100, 0b00100, 0b00000),
    "(": (0b00010, 0b00100, 0b01000, 0b01000, 0b01000, 0b00100, 0b00010),
    ")": (0b01000, 0b00100, 0b00010, 0b00010, 0b00010, 0b00100, 0b01000),
    "!": (0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00000, 0b00100),
    "?": (0b01110, 0b10001, 0b00001, 0b00110, 0b00100, 0b00000, 0b00100),
    ",": (0b00000, 0b00000, 0b00000, 0b00000, 0b00100, 0b00100, 0b01000),
    "_": (0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b00000, 0b11111),
    "=": (0b00000, 0b00000, 0b11111, 0b00000, 0b11111, 0b00000, 0b00000),
    "[": (0b01110, 0b01000, 0b01000, 0b01000, 0b01000, 0b01000, 0b01110),
    "]": (0b01110, 0b00010, 0b00010, 0b00010, 0b00010, 0b00010, 0b01110),
}


@dataclass(frozen=True)
class _TriageVisualTheme:
    banner_rgb: tuple[int, int, int]
    accent_rgb: tuple[int, int, int]
    banner_hex: str
    accent_hex: str
    pill_bg_hex: str
    ascii_label: str
    bilingual_label: str
    severity_level: int


_THEMES: dict[TriageUrgency | None, _TriageVisualTheme] = {
    TriageUrgency.EMERGENCY: _TriageVisualTheme(
        banner_rgb=(220, 38, 38),
        accent_rgb=(252, 165, 165),
        banner_hex="#DC2626",
        accent_hex="#FCA5A5",
        pill_bg_hex="#7F1D1D",
        ascii_label="EMERGENCY - STOP RUNNING",
        bilingual_label="緊急警示：立即停止跑步並就醫 / EMERGENCY",
        severity_level=3,
    ),
    TriageUrgency.PROMPT_CLINICIAN: _TriageVisualTheme(
        banner_rgb=(217, 119, 6),
        accent_rgb=(253, 230, 138),
        banner_hex="#D97706",
        accent_hex="#FDE68A",
        pill_bg_hex="#78350F",
        ascii_label="PROMPT CLINICIAN - PAUSE RUN",
        bilingual_label="建議就醫：暫停跑步並接受評估 / PROMPT CLINICIAN",
        severity_level=2,
    ),
    TriageUrgency.SELF_CARE_NEXT_STEP: _TriageVisualTheme(
        banner_rgb=(5, 150, 105),
        accent_rgb=(167, 243, 208),
        banner_hex="#059669",
        accent_hex="#A7F3D0",
        pill_bg_hex="#064E3B",
        ascii_label="SELF-CARE - MONITOR SYMPTOMS",
        bilingual_label="自我照護：觀察症狀與負荷調整 / SELF-CARE",
        severity_level=1,
    ),
    None: _TriageVisualTheme(
        banner_rgb=(2, 132, 199),
        accent_rgb=(186, 230, 253),
        banner_hex="#0284C7",
        accent_hex="#BAE6FD",
        pill_bg_hex="#0C4A6E",
        ascii_label="RUNSENCE HEALTH GUIDE",
        bilingual_label="RunSence 跑者衛教資訊 / HEALTH GUIDE",
        severity_level=0,
    ),
}


class HealthMediaRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic: str = Field(min_length=1, max_length=200)
    body_part: str | None = Field(default=None, max_length=100)
    triage_urgency: TriageUrgency | None = None
    running_allowed: bool | None = None
    guidance_summary: str = Field(min_length=1, max_length=2000)
    next_steps: list[Annotated[str, Field(max_length=500)]] = Field(
        default_factory=list, max_length=10
    )
    citations: list[Annotated[str, Field(max_length=500)]] = Field(
        default_factory=list, max_length=10
    )
    media_format: MediaFormat = "png"
    athlete_context: dict[str, Any] | None = None

    @model_validator(mode="before")
    @classmethod
    def _sanitize_raw_input(cls, data: Any) -> Any:
        return _sanitize_surrogates_value(data)

    @field_validator("topic", "guidance_summary")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("must not be empty or whitespace")
        return cleaned

    @field_validator("body_part")
    @classmethod
    def _strip_optional_body_part(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @field_validator("next_steps", "citations")
    @classmethod
    def _clean_string_list(cls, items: list[str]) -> list[str]:
        return [item.strip() for item in items if isinstance(item, str) and item.strip()]

    @field_validator("athlete_context")
    @classmethod
    def _sanitize_athlete_context(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        return _sanitize_surrogates_value(value)


@dataclass(frozen=True)
class HealthMediaArtifact:
    asset_id: str
    media_format: MediaFormat
    mime_type: str
    content_bytes: bytes
    file_size_bytes: int
    generator_mode: GeneratorMode
    triage_urgency: str | None


class MediaProvider(Protocol):
    provider_name: str

    def is_configured(self) -> bool: ...

    def generate(self, request: HealthMediaRequest) -> HealthMediaArtifact | None: ...


def effective_running_allowed(request: HealthMediaRequest) -> bool:
    """Enforce monotonic safety floor for running-allowed status.

    ``EMERGENCY`` and ``PROMPT_CLINICIAN`` unconditionally lock ``False`` regardless
    of any caller-supplied ``running_allowed`` flag. ``SELF_CARE_NEXT_STEP`` defaults
    to ``False`` when ``running_allowed`` is ``None`` (matching ``safety_triage.py``),
    while permitting an explicit caller override (e.g. M5 ``AgentSecurityEnvelope``
    when graded return-to-run monitoring is cleared).
    """
    if request.triage_urgency in (TriageUrgency.EMERGENCY, TriageUrgency.PROMPT_CLINICIAN):
        return False
    if request.running_allowed is not None:
        return bool(request.running_allowed)
    if request.triage_urgency == TriageUrgency.SELF_CARE_NEXT_STEP:
        return False
    return True


def _new_asset_id() -> str:
    return f"hm_{uuid.uuid4().hex[:12]}"


def _is_valid_png(raw: bytes) -> bool:
    if len(raw) < 33 or not raw.startswith(_PNG_SIGNATURE):
        return False
    offset = len(_PNG_SIGNATURE)
    saw_ihdr = False
    saw_idat = False
    saw_iend = False
    idat_chunks: list[bytes] = []
    while offset < len(raw):
        if offset + 12 > len(raw):
            return False
        (length,) = struct.unpack(">I", raw[offset : offset + 4])
        chunk_type = raw[offset + 4 : offset + 8]
        payload_start = offset + 8
        payload_end = payload_start + length
        if payload_end + 4 > len(raw):
            return False
        payload = raw[payload_start:payload_end]
        (crc_actual,) = struct.unpack(">I", raw[payload_end : payload_end + 4])
        crc_expected = zlib.crc32(chunk_type + payload) & 0xFFFFFFFF
        if crc_actual != crc_expected:
            return False
        if not saw_ihdr:
            if chunk_type != b"IHDR" or len(payload) != 13:
                return False
            width, height = struct.unpack(">II", payload[:8])
            if width <= 0 or height <= 0:
                return False
            saw_ihdr = True
        elif chunk_type == b"IDAT":
            if length > 0:
                saw_idat = True
                idat_chunks.append(payload)
        offset = payload_end + 4
        if chunk_type == b"IEND":
            if length != 0:
                return False
            saw_iend = True
            break
    if not (saw_ihdr and saw_idat and saw_iend and offset == len(raw)):
        return False
    try:
        decompressor = zlib.decompressobj()
        decompressor.decompress(b"".join(idat_chunks), max_length=_MAX_PNG_IDAT_BYTES)
        if decompressor.unconsumed_tail or decompressor.unused_data or not decompressor.eof:
            return False
        if decompressor.flush() or decompressor.unused_data:
            return False
    except zlib.error:
        return False
    return True


def _is_valid_mp4(raw: bytes) -> bool:
    if len(raw) < 24:
        return False
    offset = 0
    boxes: list[bytes] = []
    while offset < len(raw):
        if offset + 8 > len(raw):
            return False
        box_size, box_type = struct.unpack(">I4s", raw[offset : offset + 8])
        if box_size == 1:
            if offset + 16 > len(raw):
                return False
            (box_size,) = struct.unpack(">Q", raw[offset + 8 : offset + 16])
            if box_size < 16:
                return False
        elif box_size == 0:
            box_size = len(raw) - offset
        elif box_size < 8:
            return False
        if offset + box_size > len(raw):
            return False
        boxes.append(box_type)
        offset += box_size
    if offset != len(raw) or not boxes:
        return False
    return boxes[0] == b"ftyp" and b"moov" in boxes and b"mdat" in boxes


def _validate_media_bytes(media_format: MediaFormat, content_bytes: bytes) -> bool:
    if not isinstance(content_bytes, (bytes, bytearray)) or not content_bytes:
        return False
    raw = bytes(content_bytes)
    if media_format == "png":
        return _is_valid_png(raw)
    if media_format == "mp4":
        return _is_valid_mp4(raw)
    if media_format == "svg":
        try:
            text = raw.decode("utf-8")
            root = ET.fromstring(text)
        except (UnicodeDecodeError, ET.ParseError):
            return False
        return root.tag.rsplit("}", 1)[-1].lower() == "svg"
    return False


class HttpMediaProvider:
    """Optional external HTTP media generator gated by env credentials."""

    provider_name = "http-media-api"

    def __init__(
        self,
        *,
        api_key: str,
        api_url: str,
        timeout_seconds: float = 8.0,
        client: httpx.Client | None = None,
    ) -> None:
        self._api_key = api_key.strip()
        self._api_url = api_url.strip()
        parsed_timeout = float(timeout_seconds)
        self._timeout_seconds = max(0.5, parsed_timeout) if math.isfinite(parsed_timeout) else 8.0
        self._client = client

    def is_configured(self) -> bool:
        return bool(self._api_key and self._api_url)

    def generate(self, request: HealthMediaRequest) -> HealthMediaArtifact | None:
        if not self.is_configured():
            return None

        payload = _sanitize_surrogates_value(
            {
                "topic": request.topic,
                "body_part": request.body_part,
                "triage_urgency": request.triage_urgency.value if request.triage_urgency else None,
                "running_allowed": effective_running_allowed(request),
                "guidance_summary": request.guidance_summary,
                "next_steps": list(request.next_steps),
                "citations": list(request.citations),
                "media_format": request.media_format,
                "athlete_context": request.athlete_context,
            }
        )
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": f"{_MIME_TYPES[request.media_format]}, application/json",
        }

        close_client = self._client is None
        client = self._client or httpx.Client(timeout=self._timeout_seconds)
        try:
            response = client.post(self._api_url, json=payload, headers=headers)
            response.raise_for_status()
        finally:
            if close_client:
                client.close()

        content_type = response.headers.get("content-type", "").lower()
        target_format: MediaFormat = request.media_format
        raw_bytes: bytes

        if "application/json" in content_type:
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("content_base64"), str):
                return None
            fmt = data.get("media_format", request.media_format)
            if fmt != target_format:
                return None
            raw_bytes = base64.b64decode(data["content_base64"], validate=True)
        else:
            raw_bytes = response.content
            for fmt, mime in _MIME_TYPES.items():
                if mime in content_type:
                    if fmt != target_format:
                        return None
                    break

        if not _validate_media_bytes(target_format, raw_bytes):
            return None

        triage_value = request.triage_urgency.value if request.triage_urgency else None
        return HealthMediaArtifact(
            asset_id=_new_asset_id(),
            media_format=target_format,
            mime_type=_MIME_TYPES[target_format],
            content_bytes=raw_bytes,
            file_size_bytes=len(raw_bytes),
            generator_mode="external_api",
            triage_urgency=triage_value,
        )


def configured_media_provider() -> MediaProvider | None:
    """Return an external MediaProvider only when API URL and key are configured."""
    api_key = os.environ.get("RUNSENCE_MEDIA_API_KEY", "").strip()
    api_url = os.environ.get("RUNSENCE_MEDIA_API_URL", "").strip()
    if not api_key or not api_url:
        return None
    timeout_raw = os.environ.get("RUNSENCE_MEDIA_TIMEOUT_SECONDS", "8.0").strip()
    try:
        timeout_seconds = float(timeout_raw)
    except ValueError:
        timeout_seconds = 8.0
    if not math.isfinite(timeout_seconds):
        timeout_seconds = 8.0
    return HttpMediaProvider(
        api_key=api_key,
        api_url=api_url,
        timeout_seconds=timeout_seconds,
    )


def _to_raster_ascii(text: str, *, fallback: str = "HEALTH EDUCATION") -> str:
    """Map common CJK running/triage terms to ASCII for the 5x7 bitmap font."""
    mapped = text
    for zh, en in _CJK_TERM_MAP:
        if zh in mapped:
            mapped = mapped.replace(zh, f" {en} ")
    ascii_chars: list[str] = []
    for ch in mapped.upper():
        if ch in _FONT_5X7:
            ascii_chars.append(ch)
        elif ch in ("：", "；"):
            ascii_chars.append(":")
        elif ch in ("，", "、"):
            ascii_chars.append(",")
        elif ch in ("。",):
            ascii_chars.append(".")
        elif ch in ("（", "「", "『"):
            ascii_chars.append("(")
        elif ch in ("）", "」", "』"):
            ascii_chars.append(")")
        else:
            ascii_chars.append(" ")
    collapsed = re.sub(r"\s+", " ", "".join(ascii_chars)).strip()
    if not any(ch.isalnum() for ch in collapsed):
        return fallback
    return collapsed


def _wrap_ascii(text: str, max_chars: int, max_lines: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = ""
    for word in words:
        if len(word) > max_chars:
            if current:
                lines.append(current)
                current = ""
            while len(word) > max_chars and len(lines) < max_lines:
                lines.append(word[:max_chars])
                word = word[max_chars:]
            current = word
        elif not current:
            current = word
        elif len(current) + 1 + len(word) <= max_chars:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and len(lines[-1]) > max_chars - 3 and len(words) > 1:
        lines[-1] = lines[-1][: max(1, max_chars - 3)] + "..."
    return lines[:max_lines]


def _draw_rect(
    canvas: np.ndarray,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int],
) -> None:
    h, w, _ = canvas.shape
    cx0 = max(0, x0)
    cy0 = max(0, y0)
    cx1 = min(w, x1)
    cy1 = min(h, y1)
    if cx0 < cx1 and cy0 < cy1:
        canvas[cy0:cy1, cx0:cx1] = color


def _draw_rect_outline(
    canvas: np.ndarray,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int],
    thickness: int = 2,
) -> None:
    _draw_rect(canvas, x0, y0, x1, y0 + thickness, color)
    _draw_rect(canvas, x0, y1 - thickness, x1, y1, color)
    _draw_rect(canvas, x0, y0, x0 + thickness, y1, color)
    _draw_rect(canvas, x1 - thickness, y0, x1, y1, color)


def _draw_text(
    canvas: np.ndarray,
    x: int,
    y: int,
    text: str,
    color: tuple[int, int, int],
    *,
    scale: int = 2,
    max_width_px: int | None = None,
) -> None:
    h, w, _ = canvas.shape
    advance = 6 * scale
    cursor_x = x
    for ch in text.upper():
        glyph = _FONT_5X7.get(ch, _FONT_5X7[" "])
        if max_width_px is not None and cursor_x + 5 * scale > x + max_width_px:
            break
        if cursor_x + 5 * scale > w:
            break
        for row_idx, row_bits in enumerate(glyph):
            py0 = y + row_idx * scale
            py1 = py0 + scale
            if py0 < 0 or py1 > h:
                continue
            for col_idx in range(5):
                if (row_bits >> (4 - col_idx)) & 1:
                    px0 = cursor_x + col_idx * scale
                    px1 = px0 + scale
                    if 0 <= px0 and px1 <= w:
                        canvas[py0:py1, px0:px1] = color
        cursor_x += advance


def _draw_circle(
    canvas: np.ndarray,
    cx: int,
    cy: int,
    radius: int,
    color: tuple[int, int, int],
) -> None:
    h, w, _ = canvas.shape
    x0 = max(0, cx - radius)
    x1 = min(w, cx + radius + 1)
    y0 = max(0, cy - radius)
    y1 = min(h, cy + radius + 1)
    if x0 >= x1 or y0 >= y1:
        return
    yy, xx = np.ogrid[y0:y1, x0:x1]
    mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= radius**2
    canvas[y0:y1, x0:x1][mask] = color


def _draw_triage_glyph(
    canvas: np.ndarray,
    cx: int,
    cy: int,
    urgency: TriageUrgency | None,
    banner_rgb: tuple[int, int, int],
) -> None:
    if urgency == TriageUrgency.EMERGENCY:
        # High-contrast octagon stop badge with exclamation bar
        _draw_circle(canvas, cx, cy, 22, (255, 255, 255))
        _draw_circle(canvas, cx, cy, 18, banner_rgb)
        _draw_rect(canvas, cx - 3, cy - 11, cx + 3, cy + 3, (255, 255, 255))
        _draw_rect(canvas, cx - 3, cy + 6, cx + 3, cy + 11, (255, 255, 255))
    elif urgency == TriageUrgency.PROMPT_CLINICIAN:
        # Medical cross badge
        _draw_circle(canvas, cx, cy, 22, (255, 255, 255))
        _draw_circle(canvas, cx, cy, 18, banner_rgb)
        _draw_rect(canvas, cx - 4, cy - 11, cx + 4, cy + 11, (255, 255, 255))
        _draw_rect(canvas, cx - 11, cy - 4, cx + 11, cy + 4, (255, 255, 255))
    elif urgency == TriageUrgency.SELF_CARE_NEXT_STEP:
        # Shield / pulse check badge
        _draw_circle(canvas, cx, cy, 22, (255, 255, 255))
        _draw_circle(canvas, cx, cy, 18, banner_rgb)
        _draw_rect(canvas, cx - 10, cy - 2, cx - 2, cy + 4, (255, 255, 255))
        _draw_rect(canvas, cx - 2, cy - 8, cx + 10, cy + 2, (255, 255, 255))
    else:
        # Informational beacon badge
        _draw_circle(canvas, cx, cy, 22, (255, 255, 255))
        _draw_circle(canvas, cx, cy, 18, banner_rgb)
        _draw_rect(canvas, cx - 3, cy - 10, cx + 3, cy - 5, (255, 255, 255))
        _draw_rect(canvas, cx - 3, cy - 2, cx + 3, cy + 11, (255, 255, 255))


def _finite_float(val: Any) -> float | None:
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        fval = float(val)
        if math.isfinite(fval):
            return fval
    return None


def _extract_telemetry_bars(athlete_context: dict[str, Any] | None) -> list[tuple[str, str, float]]:
    if not athlete_context:
        return []
    bars: list[tuple[str, str, float]] = []
    if (acwr := _finite_float(athlete_context.get("acwr"))) is not None:
        bars.append(("ACWR", f"{acwr:.2f}", min(1.0, max(0.05, acwr / 2.0))))
    if (heat := _finite_float(athlete_context.get("heat_loss_pct"))) is not None:
        bars.append(("HEAT", f"{heat:.1f}%", min(1.0, max(0.05, abs(heat) / 15.0))))
    if (temp := _finite_float(athlete_context.get("temperature_c"))) is not None:
        bars.append(("TEMP", f"{temp:.1f}C", min(1.0, max(0.05, temp / 40.0))))
    if (rhr := _finite_float(athlete_context.get("resting_hr_delta"))) is not None:
        bars.append(("RHR+", f"{rhr:+.0f}", min(1.0, max(0.05, abs(rhr) / 15.0))))
    if (sleep := _finite_float(athlete_context.get("sleep_hours"))) is not None:
        bars.append(("SLEEP", f"{sleep:.1f}H", min(1.0, max(0.05, sleep / 10.0))))
    return bars[:3]


def _encode_png(rgb: np.ndarray) -> bytes:
    """Encode an (H, W, 3) uint8 RGB array into a valid PNG byte stream."""
    height, width, channels = rgb.shape
    if channels != 3:
        raise ValueError("PNG encoder requires RGB uint8 array")
    raw = np.empty((height, width * 3 + 1), dtype=np.uint8)
    raw[:, 0] = 0
    raw[:, 1:] = rgb.reshape(height, width * 3)
    compressed = zlib.compress(raw.tobytes(), level=6)

    def _chunk(tag: bytes, payload: bytes) -> bytes:
        crc = zlib.crc32(tag + payload) & 0xFFFFFFFF
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return _PNG_SIGNATURE + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", compressed) + _chunk(b"IEND", b"")


def _render_png_canvas(request: HealthMediaRequest) -> np.ndarray:
    width, height = 800, 500
    theme = _THEMES[request.triage_urgency]
    running_ok = effective_running_allowed(request)

    canvas = np.full((height, width, 3), (15, 23, 42), dtype=np.uint8)
    # Outer card
    _draw_rect(canvas, 18, 18, 782, 482, (30, 41, 59))
    _draw_rect_outline(canvas, 18, 18, 782, 482, (51, 65, 85), thickness=2)

    # Triage top banner
    _draw_rect(canvas, 18, 18, 782, 92, theme.banner_rgb)
    _draw_triage_glyph(canvas, 58, 55, request.triage_urgency, theme.banner_rgb)
    _draw_text(canvas, 96, 34, theme.ascii_label, (255, 255, 255), scale=2, max_width_px=520)
    _draw_text(canvas, 96, 60, "RUNSENCE HEALTH EDUCATION", theme.accent_rgb, scale=2, max_width_px=500)

    # Severity gauge blocks (top-right inside banner)
    for idx in range(3):
        bx = 664 + idx * 34
        color = (255, 255, 255) if idx < theme.severity_level else (30, 41, 59)
        _draw_rect(canvas, bx, 38, bx + 26, 70, color)
        _draw_rect_outline(canvas, bx, 38, bx + 26, 70, (226, 232, 240), thickness=1)

    # Status pills row
    run_color = (5, 150, 105) if running_ok else (185, 28, 28)
    run_text = "RUNNING: ALLOWED" if running_ok else "RUNNING: STOP / NO"
    _draw_rect(canvas, 36, 108, 300, 142, run_color)
    _draw_text(canvas, 48, 118, run_text, (255, 255, 255), scale=2, max_width_px=244)

    body_label = _to_raster_ascii(request.body_part or "GENERAL", fallback="GENERAL")
    _draw_rect(canvas, 316, 108, 560, 142, (51, 65, 85))
    _draw_text(canvas, 328, 118, f"PART: {body_label}", (226, 232, 240), scale=2, max_width_px=222)

    urgency_text = request.triage_urgency.value if request.triage_urgency else "GUIDE"
    _draw_rect(canvas, 576, 108, 764, 142, (30, 58, 138))
    _draw_text(canvas, 586, 118, urgency_text[:14], (191, 219, 254), scale=2, max_width_px=170)

    # Topic & Summary box
    _draw_rect(canvas, 36, 156, 764, 266, (15, 23, 42))
    _draw_rect_outline(canvas, 36, 156, 764, 266, (71, 85, 105), thickness=1)
    topic_ascii = _to_raster_ascii(request.topic, fallback="RUNNER HEALTH TOPIC")
    _draw_text(canvas, 50, 168, topic_ascii, theme.accent_rgb, scale=2, max_width_px=700)

    summary_ascii = _to_raster_ascii(request.guidance_summary, fallback="FOLLOW EVIDENCE GUIDANCE")
    for idx, line in enumerate(_wrap_ascii(summary_ascii, max_chars=58, max_lines=3)):
        _draw_text(canvas, 50, 198 + idx * 20, line, (226, 232, 240), scale=2, max_width_px=700)

    # Next steps & telemetry split
    _draw_rect(canvas, 36, 280, 510, 426, (15, 23, 42))
    _draw_rect_outline(canvas, 36, 280, 510, 426, (71, 85, 105), thickness=1)
    _draw_text(canvas, 50, 290, "NEXT STEPS", theme.accent_rgb, scale=2, max_width_px=200)
    steps = request.next_steps[:3] or ["STOP AND MONITOR SYMPTOMS"]
    for idx, step in enumerate(steps):
        sy = 318 + idx * 34
        _draw_circle(canvas, 62, sy + 7, 10, theme.banner_rgb)
        _draw_text(canvas, 57, sy, str(idx + 1), (255, 255, 255), scale=2)
        step_ascii = _to_raster_ascii(step, fallback=f"ACTION STEP {idx + 1}")
        _draw_text(canvas, 82, sy, step_ascii[:34], (241, 245, 249), scale=2, max_width_px=415)

    _draw_rect(canvas, 524, 280, 764, 426, (15, 23, 42))
    _draw_rect_outline(canvas, 524, 280, 764, 426, (71, 85, 105), thickness=1)
    _draw_text(canvas, 538, 290, "CONTEXT / TELEMETRY", theme.accent_rgb, scale=2, max_width_px=216)
    bars = _extract_telemetry_bars(request.athlete_context)
    if bars:
        for idx, (label, val_txt, ratio) in enumerate(bars):
            by = 320 + idx * 32
            _draw_text(canvas, 538, by, f"{label} {val_txt}", (226, 232, 240), scale=2, max_width_px=212)
            _draw_rect(canvas, 538, by + 18, 748, by + 26, (51, 65, 85))
            fill_w = int(210 * ratio)
            _draw_rect(canvas, 538, by + 18, 538 + max(8, fill_w), by + 26, theme.banner_rgb)
    else:
        _draw_text(canvas, 538, 326, f"CITATIONS: {len(request.citations)}", (203, 213, 225), scale=2)
        _draw_text(canvas, 538, 354, f"SEVERITY: {theme.severity_level}/3", (203, 213, 225), scale=2)
        _draw_text(canvas, 538, 382, "NON-DIAGNOSTIC GUIDE", (148, 163, 184), scale=2)

    # Footer
    _draw_rect(canvas, 36, 440, 764, 470, (15, 23, 42))
    cite_ascii = _to_raster_ascii(
        request.citations[0] if request.citations else "SPORTS MEDICINE EVIDENCE",
        fallback="EVIDENCE GROUNDED",
    )
    _draw_text(
        canvas,
        46,
        448,
        f"EVIDENCE ({len(request.citations)}): {cite_ascii[:26]}",
        (148, 163, 184),
        scale=2,
        max_width_px=455,
    )
    _draw_text(
        canvas,
        514,
        448,
        "NON-DIAGNOSTIC GUIDE",
        (148, 163, 184),
        scale=2,
        max_width_px=242,
    )
    return canvas


def _render_png_artifact(request: HealthMediaRequest) -> HealthMediaArtifact:
    rgb = _render_png_canvas(request)
    png_bytes = _encode_png(rgb)
    triage_value = request.triage_urgency.value if request.triage_urgency else None
    return HealthMediaArtifact(
        asset_id=_new_asset_id(),
        media_format="png",
        mime_type=_MIME_TYPES["png"],
        content_bytes=png_bytes,
        file_size_bytes=len(png_bytes),
        generator_mode="local_raster",
        triage_urgency=triage_value,
    )


def _sanitize_xml_text(text: str) -> str:
    cleaned = _XML_ILLEGAL_CHARS_RE.sub("", text)
    return xml_escape(cleaned, {'"': "&quot;", "'": "&apos;"})


def _char_display_width(ch: str) -> float:
    return 1.85 if ord(ch) > 127 else 1.0


def _wrap_bilingual_lines(text: str, max_units: float, max_lines: int) -> list[str]:
    cleaned = _XML_ILLEGAL_CHARS_RE.sub("", text).strip()
    if not cleaned:
        return []

    lines: list[str] = []
    current: list[str] = []
    width = 0.0

    for ch in cleaned:
        if ch in ("\n", "\r"):
            if current:
                lines.append("".join(current).strip())
                current = []
                width = 0.0
            if len(lines) >= max_lines:
                break
            continue
        cw = _char_display_width(ch)
        if width + cw > max_units and current:
            lines.append("".join(current).strip())
            current = [] if ch == " " else [ch]
            width = 0.0 if ch == " " else cw
            if len(lines) >= max_lines:
                break
        else:
            if current or ch != " ":
                current.append(ch)
                width += cw

    if current and len(lines) < max_lines:
        lines.append("".join(current).strip())
    return lines[:max_lines]


_CONTEXT_CHIP_REPR = reprlib.Repr(
    maxlevel=2,
    maxdict=3,
    maxlist=3,
    maxtuple=3,
    maxset=3,
    maxstring=30,
    maxother=30,
)


def _format_context_chip_val(val: Any) -> str:
    if isinstance(val, (str, int, float, bool)) or val is None:
        return str(val)
    return _CONTEXT_CHIP_REPR.repr(val)


def _render_svg_artifact(request: HealthMediaRequest) -> HealthMediaArtifact:
    theme = _THEMES[request.triage_urgency]
    running_ok = effective_running_allowed(request)

    topic_esc = _sanitize_xml_text(request.topic)
    body_part_esc = _sanitize_xml_text(request.body_part or "一般跑者衛教 / General")
    urgency_label_esc = _sanitize_xml_text(theme.bilingual_label)
    run_badge_text = (
        "可依建議監測活動 / RUNNING ALLOWED"
        if running_ok
        else "請勿跑步 / RUNNING NOT ALLOWED"
    )
    run_badge_color = "#059669" if running_ok else "#B91C1C"

    summary_lines = _wrap_bilingual_lines(request.guidance_summary, max_units=68.0, max_lines=4)
    summary_tspans = "\n".join(
        f'    <tspan x="44" dy="{0 if idx == 0 else 22}">{_sanitize_xml_text(line)}</tspan>'
        for idx, line in enumerate(summary_lines)
    )

    steps = request.next_steps[:4] or ["先停止本次跑步並持續觀察症狀。"]
    step_elements: list[str] = []
    for idx, step in enumerate(steps):
        sy = 304 + idx * 28
        step_lines = _wrap_bilingual_lines(step, max_units=44.0, max_lines=1)
        step_text = _sanitize_xml_text(step_lines[0] if step_lines else step[:44])
        step_elements.append(
            f'  <circle cx="56" cy="{sy - 5}" r="10" fill="{theme.banner_hex}"/>\n'
            f'  <text x="56" y="{sy}" text-anchor="middle" font-size="12" font-weight="700" fill="#FFFFFF">{idx + 1}</text>\n'
            f'  <text x="76" y="{sy}" font-size="13" fill="#F1F5F9">{step_text}</text>'
        )

    context_chips: list[str] = []
    if request.athlete_context:
        for idx, (key, val) in enumerate(list(request.athlete_context.items())[:4]):
            cy = 302 + idx * 28
            raw_chip = f"{key}: {_format_context_chip_val(val)}"
            chip_text = _sanitize_xml_text(_XML_ILLEGAL_CHARS_RE.sub("", raw_chip)[:30])
            context_chips.append(
                f'  <rect x="524" y="{cy - 16}" width="224" height="22" rx="6" fill="#1E293B" stroke="#475569"/>\n'
                f'  <text x="534" y="{cy}" font-size="12" fill="#CBD5E1">{chip_text}</text>'
            )
    else:
        triage_txt = request.triage_urgency.value if request.triage_urgency else "GUIDE"
        context_chips.append(
            f'  <text x="524" y="304" font-size="13" fill="#CBD5E1">Urgency: {_sanitize_xml_text(triage_txt)}</text>'
        )
        context_chips.append(
            f'  <text x="524" y="330" font-size="13" fill="#CBD5E1">Severity: {theme.severity_level}/3</text>'
        )

    citations_text = " | ".join(request.citations[:3]) if request.citations else "Sports Medicine Evidence Corpus"
    citations_esc = _sanitize_xml_text(citations_text[:110])
    disclaimer_esc = _sanitize_xml_text(DISCLAIMER)
    font_stack = "'Noto Sans TC', 'PingFang TC', 'Microsoft JhengHei', system-ui, sans-serif"

    svg_doc = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 500" width="800" height="500" role="img" aria-label="{topic_esc}">
  <rect width="800" height="500" fill="#0F172A"/>
  <rect x="16" y="16" width="768" height="468" rx="14" fill="#1E293B" stroke="#334155" stroke-width="2"/>
  <rect x="16" y="16" width="768" height="72" rx="14" fill="{theme.banner_hex}"/>
  <rect x="16" y="64" width="768" height="24" fill="{theme.banner_hex}"/>
  <text x="36" y="48" font-family="{font_stack}" font-size="20" font-weight="700" fill="#FFFFFF">{urgency_label_esc}</text>
  <text x="36" y="72" font-family="{font_stack}" font-size="13" fill="{theme.accent_hex}">RunSence Multimedia Health Education</text>

  <rect x="32" y="102" width="290" height="30" rx="8" fill="{run_badge_color}"/>
  <text x="44" y="122" font-family="{font_stack}" font-size="13" font-weight="700" fill="#FFFFFF">{_sanitize_xml_text(run_badge_text)}</text>

  <rect x="334" y="102" width="250" height="30" rx="8" fill="#334155"/>
  <text x="346" y="122" font-family="{font_stack}" font-size="13" fill="#E2E8F0">部位 / Body Part: {body_part_esc}</text>

  <rect x="596" y="102" width="172" height="30" rx="8" fill="{theme.pill_bg_hex}"/>
  <text x="682" y="122" text-anchor="middle" font-family="{font_stack}" font-size="12" font-weight="700" fill="{theme.accent_hex}">Severity {theme.severity_level}/3</text>

  <rect x="32" y="146" width="736" height="114" rx="10" fill="#0F172A" stroke="#475569"/>
  <text x="44" y="170" font-family="{font_stack}" font-size="17" font-weight="700" fill="{theme.accent_hex}">{topic_esc}</text>
  <text x="44" y="196" font-family="{font_stack}" font-size="14" fill="#E2E8F0">
{summary_tspans}
  </text>

  <rect x="32" y="272" width="464" height="148" rx="10" fill="#0F172A" stroke="#475569"/>
  <text x="44" y="288" font-family="{font_stack}" font-size="12" font-weight="700" fill="{theme.accent_hex}">下一步行動 / NEXT STEPS</text>
{chr(10).join(step_elements)}

  <rect x="508" y="272" width="260" height="148" rx="10" fill="#0F172A" stroke="#475569"/>
  <text x="524" y="288" font-family="{font_stack}" font-size="12" font-weight="700" fill="{theme.accent_hex}">跑者脈絡 / CONTEXT</text>
{chr(10).join(context_chips)}

  <text x="36" y="442" font-family="{font_stack}" font-size="12" fill="#94A3B8">參考依據 / Citations ({len(request.citations)}): {citations_esc}</text>
  <text x="36" y="466" font-family="{font_stack}" font-size="11" fill="#CBD5E1">{disclaimer_esc}</text>
</svg>
"""
    svg_bytes = svg_doc.encode("utf-8")
    triage_value = request.triage_urgency.value if request.triage_urgency else None
    return HealthMediaArtifact(
        asset_id=_new_asset_id(),
        media_format="svg",
        mime_type=_MIME_TYPES["svg"],
        content_bytes=svg_bytes,
        file_size_bytes=len(svg_bytes),
        generator_mode="local_svg_fallback",
        triage_urgency=triage_value,
    )


def _render_mp4_base_frame(request: HealthMediaRequest) -> np.ndarray:
    width, height = 640, 360
    theme = _THEMES[request.triage_urgency]
    running_ok = effective_running_allowed(request)

    canvas = np.full((height, width, 3), (15, 23, 42), dtype=np.uint8)
    _draw_rect(canvas, 12, 12, 628, 348, (30, 41, 59))
    _draw_rect_outline(canvas, 12, 12, 628, 348, (51, 65, 85), thickness=2)

    # Banner
    _draw_rect(canvas, 12, 12, 628, 68, theme.banner_rgb)
    _draw_triage_glyph(canvas, 44, 40, request.triage_urgency, theme.banner_rgb)
    _draw_text(canvas, 76, 22, theme.ascii_label, (255, 255, 255), scale=2, max_width_px=430)
    _draw_text(canvas, 76, 44, "RUNSENCE HEALTH VIDEO GUIDE", theme.accent_rgb, scale=1, max_width_px=400)

    # Run status & body part
    run_color = (5, 150, 105) if running_ok else (185, 28, 28)
    run_label = "RUN: ALLOWED" if running_ok else "RUN: STOP / NO"
    _draw_rect(canvas, 24, 80, 236, 108, run_color)
    _draw_text(canvas, 34, 88, run_label, (255, 255, 255), scale=2, max_width_px=196)

    body_label = _to_raster_ascii(request.body_part or "GENERAL", fallback="GENERAL")
    _draw_rect(canvas, 248, 80, 458, 108, (51, 65, 85))
    _draw_text(canvas, 258, 88, body_label[:15], (226, 232, 240), scale=2, max_width_px=194)

    urgency_label = request.triage_urgency.value[:12] if request.triage_urgency else "GUIDE"
    _draw_rect(canvas, 470, 80, 616, 108, (30, 58, 138))
    _draw_text(canvas, 478, 88, urgency_label, (191, 219, 254), scale=2, max_width_px=130)

    # Topic + Summary box
    _draw_rect(canvas, 24, 118, 616, 198, (15, 23, 42))
    _draw_rect_outline(canvas, 24, 118, 616, 198, (71, 85, 105), thickness=1)
    topic_ascii = _to_raster_ascii(request.topic, fallback="RUNNER HEALTH TOPIC")
    _draw_text(canvas, 34, 128, topic_ascii, theme.accent_rgb, scale=2, max_width_px=570)
    summary_ascii = _to_raster_ascii(request.guidance_summary, fallback="FOLLOW GUIDANCE")
    for idx, line in enumerate(_wrap_ascii(summary_ascii, max_chars=46, max_lines=2)):
        _draw_text(canvas, 34, 152 + idx * 18, line, (226, 232, 240), scale=2, max_width_px=570)

    # Next steps box (left) and telemetry box (right)
    _draw_rect(canvas, 24, 208, 408, 316, (15, 23, 42))
    _draw_rect_outline(canvas, 24, 208, 408, 316, (71, 85, 105), thickness=1)
    _draw_text(canvas, 34, 216, "ACTION PHASES", theme.accent_rgb, scale=2, max_width_px=200)

    _draw_rect(canvas, 418, 208, 616, 316, (15, 23, 42))
    _draw_rect_outline(canvas, 418, 208, 616, 316, (71, 85, 105), thickness=1)
    _draw_text(canvas, 428, 216, "TELEMETRY", theme.accent_rgb, scale=2, max_width_px=180)

    # Footer
    _draw_text(
        canvas,
        24,
        326,
        f"CITATIONS: {len(request.citations)} | NON-DIAGNOSTIC GUIDE",
        (148, 163, 184),
        scale=1,
        max_width_px=580,
    )
    return canvas


def _build_mp4_frames(request: HealthMediaRequest, *, num_frames: int = 36) -> np.ndarray:
    base = _render_mp4_base_frame(request)
    theme = _THEMES[request.triage_urgency]
    steps = request.next_steps[:3] or ["STOP AND MONITOR SYMPTOMS"]
    bars = _extract_telemetry_bars(request.athlete_context)

    h, w, c = base.shape
    frames = np.empty((num_frames, h, w, c), dtype=np.uint8)
    for frame_idx in range(num_frames):
        t = frame_idx / max(1, num_frames - 1)
        frame = base.copy()

        # 1. Animated top triage pulse bar
        pulse = 0.65 + 0.35 * math.sin(2.0 * math.pi * t * (3.0 if theme.severity_level == 3 else 1.5))
        pulse_color = tuple(min(255, int(ch * pulse)) for ch in theme.accent_rgb)
        _draw_rect(frame, 12, 64, 628, 70, pulse_color)

        # 2. Animated step phase progression
        active_step = min(len(steps) - 1, int(t * len(steps)))
        for idx, step in enumerate(steps):
            sy = 240 + idx * 24
            is_active = idx == active_step
            bullet_color = theme.banner_rgb if is_active else (51, 65, 85)
            txt_color = (255, 255, 255) if is_active else (148, 163, 184)
            _draw_circle(frame, 42, sy + 6, 8, bullet_color)
            _draw_text(frame, 38, sy, str(idx + 1), (255, 255, 255), scale=2)
            step_ascii = _to_raster_ascii(step, fallback=f"STEP {idx + 1}")
            _draw_text(frame, 58, sy, step_ascii[:28], txt_color, scale=2, max_width_px=342)

        # 3. Animated telemetry bars (fill over first 1.5s)
        ease = min(1.0, t / 0.5)
        if bars:
            for idx, (label, val_txt, ratio) in enumerate(bars[:2]):
                by = 242 + idx * 34
                _draw_text(frame, 428, by, f"{label} {val_txt}", (226, 232, 240), scale=2, max_width_px=180)
                _draw_rect(frame, 428, by + 18, 604, by + 26, (51, 65, 85))
                fill_w = int(176 * ratio * ease)
                _draw_rect(frame, 428, by + 18, 428 + max(6, fill_w), by + 26, theme.banner_rgb)
        else:
            _draw_text(frame, 428, 244, f"SEV: {theme.severity_level}/3", (226, 232, 240), scale=2)
            _draw_rect(frame, 428, 266, 604, 276, (51, 65, 85))
            ratio = max(0.15, theme.severity_level / 3.0)
            _draw_rect(frame, 428, 266, 428 + max(8, int(176 * ratio * ease)), 276, theme.banner_rgb)

        # 4. Timeline progress sweep at bottom
        _draw_rect(frame, 24, 338, 616, 343, (51, 65, 85))
        _draw_rect(frame, 24, 338, 24 + max(8, int(592 * t)), 343, theme.accent_rgb)
        frames[frame_idx] = frame

    return frames


def _render_mp4_artifact(request: HealthMediaRequest) -> HealthMediaArtifact:
    ffmpeg_cmd = os.environ.get("RUNSENCE_FFMPEG_BIN", "").strip() or "ffmpeg"
    ffmpeg_bin = shutil.which(ffmpeg_cmd)
    if not ffmpeg_bin:
        logger.warning("ffmpeg not found on PATH; falling back to local SVG card")
        return _render_svg_artifact(request)

    frames = _build_mp4_frames(request, num_frames=36)
    raw_rgb = frames.tobytes()
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    codec_profiles: tuple[list[str], ...] = (
        ["-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage", "-crf", "26"],
        ["-c:v", "mpeg4", "-q:v", "5"],
    )

    try:
        with tempfile.TemporaryDirectory(prefix="rs_media_") as tmpdir:
            out_path = os.path.join(tmpdir, "health_education.mp4")
            for codec_args in codec_profiles:
                cmd = [
                    ffmpeg_bin,
                    "-y",
                    "-loglevel",
                    "error",
                    "-f",
                    "rawvideo",
                    "-pix_fmt",
                    "rgb24",
                    "-s",
                    "640x360",
                    "-r",
                    "12",
                    "-i",
                    "-",
                    *codec_args,
                    "-pix_fmt",
                    "yuv420p",
                    "-movflags",
                    "+faststart",
                    out_path,
                ]
                proc = subprocess.run(
                    cmd,
                    input=raw_rgb,
                    capture_output=True,
                    timeout=15,
                    creationflags=creationflags,
                )
                if proc.returncode == 0 and os.path.exists(out_path):
                    with open(out_path, "rb") as f:
                        mp4_bytes = f.read()
                    if _validate_media_bytes("mp4", mp4_bytes):
                        triage_value = request.triage_urgency.value if request.triage_urgency else None
                        return HealthMediaArtifact(
                            asset_id=_new_asset_id(),
                            media_format="mp4",
                            mime_type=_MIME_TYPES["mp4"],
                            content_bytes=mp4_bytes,
                            file_size_bytes=len(mp4_bytes),
                            generator_mode="local_ffmpeg",
                            triage_urgency=triage_value,
                        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        logger.warning("local ffmpeg encoding failed (%s); falling back to SVG", type(exc).__name__)
        return _render_svg_artifact(request)

    logger.warning("local ffmpeg produced no valid MP4 output; falling back to SVG")
    return _render_svg_artifact(request)


_MEDIA_CACHE_MAXSIZE = 64
_MEDIA_CACHE_LOCK = threading.Lock()
_MEDIA_ASSET_CACHE: OrderedDict[str, tuple[uuid.UUID, HealthMediaArtifact]] = OrderedDict()


def store_media_asset(actor_id: uuid.UUID, artifact: HealthMediaArtifact) -> None:
    """Persist a generated media artifact in a bounded actor-scoped LRU cache."""
    with _MEDIA_CACHE_LOCK:
        _MEDIA_ASSET_CACHE[artifact.asset_id] = (actor_id, artifact)
        _MEDIA_ASSET_CACHE.move_to_end(artifact.asset_id)
        while len(_MEDIA_ASSET_CACHE) > _MEDIA_CACHE_MAXSIZE:
            _MEDIA_ASSET_CACHE.popitem(last=False)


def get_media_asset(actor_id: uuid.UUID, asset_id: str) -> HealthMediaArtifact | None:
    """Fetch a cached media artifact only if owned by `actor_id`."""
    with _MEDIA_CACHE_LOCK:
        entry = _MEDIA_ASSET_CACHE.get(asset_id)
        if entry is None:
            return None
        owner_id, artifact = entry
        if owner_id != actor_id:
            return None
        _MEDIA_ASSET_CACHE.move_to_end(asset_id)
        return artifact


class MultimediaEducationService:
    """Orchestrates optional external media provider with deterministic local rendering."""

    def __init__(self, provider: MediaProvider | None = None) -> None:
        self._provider = provider

    def store_asset(self, actor_id: uuid.UUID, artifact: HealthMediaArtifact) -> None:
        store_media_asset(actor_id, artifact)

    def get_asset(self, actor_id: uuid.UUID, asset_id: str) -> HealthMediaArtifact | None:
        return get_media_asset(actor_id, asset_id)

    def generate(self, request: HealthMediaRequest) -> HealthMediaArtifact:
        provider = self._provider if self._provider is not None else configured_media_provider()
        if provider is not None:
            try:
                if provider.is_configured():
                    external = provider.generate(request)
                    if (
                        external is not None
                        and external.media_format == request.media_format
                        and _validate_media_bytes(external.media_format, external.content_bytes)
                    ):
                        expected_mime = _MIME_TYPES[external.media_format]
                        triage_value = (
                            request.triage_urgency.value if request.triage_urgency else None
                        )
                        return HealthMediaArtifact(
                            asset_id=external.asset_id or _new_asset_id(),
                            media_format=external.media_format,
                            mime_type=expected_mime,
                            content_bytes=external.content_bytes,
                            file_size_bytes=len(external.content_bytes),
                            generator_mode="external_api",
                            triage_urgency=triage_value,
                        )
            except Exception as exc:
                logger.warning(
                    "external media provider failed (%s); falling back to local renderer",
                    type(exc).__name__,
                )

        if request.media_format == "png":
            return _render_png_artifact(request)
        if request.media_format == "mp4":
            return _render_mp4_artifact(request)
        return _render_svg_artifact(request)


def get_multimedia_education_service() -> MultimediaEducationService:
    return MultimediaEducationService()
