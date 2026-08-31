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


def test_coach_connection_failure_uses_one_fast_safe_fallback(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    calls = []

    def _raise(*args, **kwargs):
        calls.append(kwargs)
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _raise)

    response = llm_client.ask_ai_health_coach(
        [{"role": "user", "content": "依我最近的負荷，今天適合跑什麼？"}],
        {"acute_load": None, "chronic_load": None, "load_ratio": None},
    )

    assert len(calls) == 1
    assert calls[0]["timeout"] == llm_client._TIMEOUT_SECONDS
    assert "目前無法回覆" in response
    assert "分鐘" not in response
    assert "配速" not in response
    assert " AU" not in response


def test_coach_stream_connection_failure_does_not_retry_through_sync_path(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    calls = []

    class _FailingStream:
        def __enter__(self):
            calls.append(1)
            raise httpx.ConnectError("connection refused")

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(httpx, "stream", lambda *args, **kwargs: _FailingStream())

    response = "".join(
        llm_client.stream_ai_health_coach(
            [{"role": "user", "content": "今天適合跑什麼？"}],
            {"temperature": None},
        )
    )

    assert len(calls) == 1
    assert "目前無法回覆" in response
    assert "分鐘" not in response


def test_coach_success_returns_provider_text(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *args, **kwargs: _FakeResponse(
            {"choices": [{"message": {"content": "這是有資料依據的說明。"}}]}
        ),
    )

    assert llm_client.ask_ai_health_coach(
        [{"role": "user", "content": "請解釋今天的負荷"}], {}
    ) == "這是有資料依據的說明。"


def test_coach_prompt_only_explains_fixed_triage_and_never_authors_a_plan():
    provider_messages = llm_client._build_coach_messages(
        [{"role": "user", "content": "我的小腿不舒服"}],
        {"triage_urgency": "PROMPT_CLINICIAN", "has_injury_issue": True},
    )

    system_prompt = provider_messages[0]["content"]
    assert "固定安全分流結果: PROMPT_CLINICIAN" in system_prompt
    assert "不得診斷、判定或改變醫療緊急程度" in system_prompt
    assert "不得自行設定課表種類、距離、時長、配速或強度" in system_prompt


# ---------------------------------------------------------------------------
# A fallback must never be mistaken for an answer
#
# Diagnosing why the coach "said nothing useful" took an hour because the
# unavailable message and a real answer had the same type. These pin that shut.
# ---------------------------------------------------------------------------


def test_a_model_answer_reports_that_a_model_produced_it(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "x" * 20)
    monkeypatch.setattr(
        httpx,
        "post",
        lambda *a, **k: _FakeResponse(
            {"choices": [{"message": {"content": "今天建議輕鬆跑。"}}]}
        ),
    )

    answer = llm_client.answer_as_coach([{"role": "user", "content": "今天跑什麼"}])

    assert answer.source == "MODEL"
    assert answer.text == "今天建議輕鬆跑。"
    assert answer.is_fallback is False


def test_an_unreachable_provider_is_reported_as_unavailable_not_as_an_answer(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "x" * 20)

    def _refuse(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _refuse)

    answer = llm_client.answer_as_coach([{"role": "user", "content": "今天跑什麼"}])

    assert answer.source == "UNAVAILABLE"
    assert answer.is_fallback is True
    assert answer.text == llm_client.COACH_UNAVAILABLE_MESSAGE


def test_a_missing_key_is_reported_as_unconfigured_rather_than_as_a_failure(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    answer = llm_client.answer_as_coach([{"role": "user", "content": "今天跑什麼"}])

    assert answer.source == "NOT_CONFIGURED"
    assert answer.is_fallback is True


def test_a_rejected_request_reports_the_status_so_the_cause_is_visible(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "x" * 20)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: _FakeResponse({}, status_code=401))

    answer = llm_client.answer_as_coach([{"role": "user", "content": "今天跑什麼"}])

    assert answer.source == "UNAVAILABLE"
    assert answer.detail is not None and "401" in answer.detail


# ---------------------------------------------------------------------------
# One unreachable provider must cost one timeout, not two
# ---------------------------------------------------------------------------


def test_a_scenario_proposal_is_skipped_once_the_provider_is_known_unreachable(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "x" * 20)
    calls: list[str] = []

    def _refuse(*args, **kwargs):
        calls.append("post")
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "post", _refuse)

    turn = llm_client.coach_turn(
        [{"role": "user", "content": "我今天只有 30 分鐘"}], local_date="2026-08-31"
    )

    assert turn.answer.source == "UNAVAILABLE"
    assert turn.scenario_override is None
    # The second provider call must not be attempted after the first proved
    # the provider unreachable: two 8s timeouts is a 16s wait for nothing.
    assert len(calls) == 1


def test_a_reachable_provider_is_still_asked_for_a_scenario_override(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "x" * 20)
    calls: list[dict] = []

    def _post(url, **kwargs):
        calls.append(kwargs.get("json", {}))
        if len(calls) == 1:
            return _FakeResponse({"choices": [{"message": {"content": "好的。"}}]})
        return _FakeResponse(
            {"choices": [{"message": {"content": json.dumps({"available_minutes": 30})}}]}
        )

    monkeypatch.setattr(httpx, "post", _post)

    turn = llm_client.coach_turn(
        [{"role": "user", "content": "我今天只有 30 分鐘"}], local_date="2026-08-31"
    )

    assert turn.answer.source == "MODEL"
    assert turn.scenario_override == {"available_minutes": 30}
    assert len(calls) == 2


def test_provider_reachability_can_be_checked_without_asking_a_question(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "x" * 20)
    monkeypatch.setattr(
        httpx, "get", lambda *a, **k: _FakeResponse({"data": [{"id": "m"}]})
    )

    status = llm_client.provider_status()

    assert status.configured is True
    assert status.reachable is True


def test_provider_reachability_reports_the_reason_it_is_unreachable(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "x" * 20)

    def _refuse(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", _refuse)

    status = llm_client.provider_status()

    assert status.configured is True
    assert status.reachable is False
    assert status.detail and "ConnectError" in status.detail


def test_provider_status_never_exposes_the_key(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "s" * 40)
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResponse({"data": []}))

    rendered = repr(llm_client.provider_status())

    assert "s" * 40 not in rendered


# ---------------------------------------------------------------------------
# Streaming: never blend a real answer with a failure notice
# ---------------------------------------------------------------------------


class _FakeStream:
    def __init__(self, lines, status_code=200):
        self._lines = lines
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self):
        yield from self._lines


def _delta_line(text: str) -> str:
    return "data: " + json.dumps({"choices": [{"delta": {"content": text}}]})


def test_streaming_yields_only_what_the_model_produced(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "x" * 20)
    monkeypatch.setattr(
        httpx,
        "stream",
        lambda *a, **k: _FakeStream([_delta_line("今天"), _delta_line("輕鬆跑")]),
    )

    assert list(llm_client.stream_coach_answer([{"role": "user", "content": "?"}])) == [
        "今天",
        "輕鬆跑",
    ]


def test_a_stream_that_breaks_midway_keeps_what_arrived_and_appends_nothing(monkeypatch):
    """The Athlete must never read half an answer welded to a failure notice."""
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "x" * 20)

    def _lines():
        yield _delta_line("前半段")
        raise httpx.ReadError("stream broke")

    monkeypatch.setattr(httpx, "stream", lambda *a, **k: _FakeStream(_lines()))

    produced = list(llm_client.stream_coach_answer([{"role": "user", "content": "?"}]))

    assert produced == ["前半段"]
    assert llm_client.COACH_UNAVAILABLE_MESSAGE not in "".join(produced)


def test_an_unreachable_provider_streams_nothing_at_all(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_" + "x" * 20)

    def _refuse(*args, **kwargs):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "stream", _refuse)

    assert list(llm_client.stream_coach_answer([{"role": "user", "content": "?"}])) == []


def test_an_unconfigured_provider_streams_nothing_at_all(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    assert list(llm_client.stream_coach_answer([{"role": "user", "content": "?"}])) == []
