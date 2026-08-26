"""Pure unit tests with httpx mocked -- no DB, no real Ollama needed.
Covers spec.md's LLM requirements (TC-AI-STRUCT-001/002/003/005 equivalents,
tasks.md 5.5-5.9)."""

from __future__ import annotations

import json

import httpx
import pytest

from app import llm_client


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)  # type: ignore[arg-type]

    def json(self) -> dict:
        return self._payload


def test_valid_whitelisted_response_is_used(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: _FakeResponse({"response": json.dumps({"tone_variant_id": "SUPPORTIVE_A"})}),
    )
    assert llm_client.select_tone_variant("STEADY_STATE", "STABLE") == "SUPPORTIVE_A"


def test_id_outside_whitelist_falls_back_to_neutral(monkeypatch):
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: _FakeResponse({"response": json.dumps({"tone_variant_id": "ANGRY_DRILL_SERGEANT"})}),
    )
    assert llm_client.select_tone_variant("STEADY_STATE", "STABLE") == llm_client.FALLBACK_TONE_VARIANT_ID


def test_extra_field_discards_the_entire_response_not_just_the_extra_field(monkeypatch):
    """TC-AI-STRUCT-002 equivalent: {"tone_variant_id": "SUPPORTIVE_A", "distance_km": 999}
    must fall back entirely -- the otherwise-valid tone_variant_id is not used either."""
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: _FakeResponse(
            {"response": json.dumps({"tone_variant_id": "SUPPORTIVE_A", "distance_km": 999})}
        ),
    )
    assert llm_client.select_tone_variant("STEADY_STATE", "STABLE") == llm_client.FALLBACK_TONE_VARIANT_ID


def test_prescription_shaped_adversarial_payload_cannot_leak_through(monkeypatch):
    """TC-AI-STRUCT-001 equivalent: even if the LLM tries to smuggle
    prescription-looking fields, select_tone_variant's return type is just
    a tone id string -- there is no field on it a caller could misuse as a
    prescription value."""
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: _FakeResponse(
            {
                "response": json.dumps(
                    {
                        "tone_variant_id": "SUPPORTIVE_A",
                        "distance_km": 999,
                        "duration_minutes": 999,
                        "target_pace_sec_per_km": 1,
                    }
                )
            }
        ),
    )
    result = llm_client.select_tone_variant("STEADY_STATE", "STABLE")
    assert result == llm_client.FALLBACK_TONE_VARIANT_ID  # rejected wholesale, per above


def test_malformed_json_falls_back(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse({"response": "not json"}))
    assert llm_client.select_tone_variant("STEADY_STATE", "STABLE") == llm_client.FALLBACK_TONE_VARIANT_ID


def test_connection_failure_falls_back_without_raising(monkeypatch):
    def _raise(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _raise)
    assert llm_client.select_tone_variant("STEADY_STATE", "STABLE") == llm_client.FALLBACK_TONE_VARIANT_ID


def test_request_payload_is_minimized_to_reason_code_and_trend_only(monkeypatch):
    """TC-AI-STRUCT-003 equivalent: only adjustment_reason_code and
    load_trend_direction ever leave this process -- no name, injury text,
    or GPS, because there is no parameter on the function to pass them."""
    captured = {}

    def _capture(url, json, timeout):  # noqa: A002 - matches httpx.post's kwarg name
        captured["prompt"] = json["prompt"]
        return _FakeResponse({"response": '{"tone_variant_id": "NEUTRAL_FALLBACK"}'})

    monkeypatch.setattr(httpx, "post", _capture)
    llm_client.select_tone_variant("RECENT_LOAD_ELEVATED", "RISING")

    assert "RECENT_LOAD_ELEVATED" in captured["prompt"]
    assert "RISING" in captured["prompt"]
    for forbidden in ("name", "injury", "gps", "lat", "lon"):
        assert forbidden not in captured["prompt"].lower()


@pytest.mark.parametrize("bad_id", ["supportive_a", "SUPPORTIVE_C", "", None, 123])
def test_every_non_whitelisted_shape_falls_back(monkeypatch, bad_id):
    monkeypatch.setattr(
        httpx, "post", lambda *a, **k: _FakeResponse({"response": json.dumps({"tone_variant_id": bad_id})})
    )
    assert llm_client.select_tone_variant("STEADY_STATE", "STABLE") == llm_client.FALLBACK_TONE_VARIANT_ID
