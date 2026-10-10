"""GUIDANCE_PROVIDER as an ordered chain: the cloud model answers while it
can, and the local Ollama model takes over when it cannot (quota, outage)."""

from __future__ import annotations

import json

import httpx

from app.llm_client import answer_as_coach, stream_coach_answer

_ASK = [{"role": "user", "content": "我今天只有 30 分鐘"}]


class _Response:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload, self.status_code = payload, status_code

    def json(self) -> dict:
        return self._payload


class _Stream:
    def __init__(self, lines: list[str], status_code: int = 200) -> None:
        self._lines, self.status_code = lines, status_code

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def iter_lines(self):
        yield from self._lines


def _chain(monkeypatch) -> None:
    monkeypatch.setenv("GUIDANCE_PROVIDER", "groq,ollama")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("OLLAMA_COACH_MODEL", "qwen2.5:7b")


def test_the_local_model_answers_when_the_cloud_is_out_of_quota(monkeypatch):
    _chain(monkeypatch)
    asked = []

    def post(url, **kwargs):
        asked.append((url, kwargs["json"]["model"]))
        if "groq" in url:
            return _Response({}, status_code=429)
        return _Response({"message": {"content": "本機模型的回答"}})

    monkeypatch.setattr(httpx, "post", post)
    answer = answer_as_coach(_ASK)

    assert (answer.text, answer.source) == ("本機模型的回答", "MODEL")
    assert asked[-1] == ("http://localhost:11434/api/chat", "qwen2.5:7b")


def test_the_cloud_answers_while_it_can(monkeypatch):
    _chain(monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _Response(
        {"choices": [{"message": {"content": "雲端的回答"}}]}) if "groq" in url
        else (_ for _ in ()).throw(AssertionError("local model must not be asked")))

    assert answer_as_coach(_ASK).text == "雲端的回答"


def test_a_stream_moves_to_the_local_model_when_the_cloud_refuses(monkeypatch):
    _chain(monkeypatch)

    def stream(method, url, **kwargs):
        if "groq" in url:
            return _Stream([], status_code=429)
        return _Stream([json.dumps({"message": {"content": c}, "done": False}) for c in ("先", "休息")]
                       + [json.dumps({"done": True})])

    monkeypatch.setattr(httpx, "stream", stream)
    assert "".join(stream_coach_answer(_ASK)) == "先休息"


def test_the_answer_names_the_provider_that_actually_answered(monkeypatch):
    _chain(monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _Response({}, status_code=429) if "groq" in url
                        else _Response({"message": {"content": "本機"}}))
    assert answer_as_coach(_ASK).provider == "ollama"


def test_warming_up_loads_the_local_model_only_when_it_is_in_the_chain(monkeypatch):
    from app.coach_providers import warm_up_local_model

    posted = []
    monkeypatch.setattr(httpx, "post", lambda url, **kw: posted.append((url, kw["json"])) or _Response({}))
    monkeypatch.setenv("GUIDANCE_PROVIDER", "groq")
    warm_up_local_model()
    assert posted == []

    _chain(monkeypatch)
    warm_up_local_model()
    ((url, body),) = posted
    assert url == "http://localhost:11434/api/chat"
    assert body["model"] == "qwen2.5:7b" and body["keep_alive"] == "30m"


def test_warming_up_never_raises(monkeypatch):
    from app.coach_providers import warm_up_local_model

    _chain(monkeypatch)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("down")))
    warm_up_local_model()


def test_injury_guidance_still_uses_the_cloud_provider_named_first_in_the_chain(monkeypatch):
    from app.guidance_providers import GroqGuidanceProvider
    from app.health_guidance_service import configured_guidance_provider

    _chain(monkeypatch)
    assert isinstance(configured_guidance_provider(), GroqGuidanceProvider)
