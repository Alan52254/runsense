import json

import httpx

from app.guidance_providers import GeminiGuidanceProvider, GroqGuidanceProvider
from app.health_guidance_service import configured_guidance_provider


def test_groq_adapter_uses_structured_json_and_returns_only_message_content():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "停止跑步並尋求評估。",
                                    "next_steps": ["停止跑步"],
                                    "citation_ids": ["source-1"],
                                },
                                ensure_ascii=False,
                            )
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GroqGuidanceProvider(api_key="test-key", client=client)

    result = provider.generate({"triage": {"urgency": "EMERGENCY"}})

    assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert captured["authorization"] == "Bearer test-key"
    assert captured["body"]["response_format"] == {"type": "json_object"}
    assert result == {
        "summary": "停止跑步並尋求評估。",
        "next_steps": ["停止跑步"],
        "citation_ids": ["source-1"],
    }


def test_gemini_adapter_requests_json_and_parses_candidate_content():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "summary": "先停止跑步。",
                                            "next_steps": ["安排評估"],
                                            "citation_ids": ["source-1"],
                                        },
                                        ensure_ascii=False,
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GeminiGuidanceProvider(api_key="gemini-test-key", client=client)

    result = provider.generate({"triage": {"urgency": "PROMPT_CLINICIAN"}})

    assert "gemini-2.5-flash:generateContent" in captured["url"]
    assert "key=gemini-test-key" in captured["url"]
    assert captured["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert result["citation_ids"] == ["source-1"]


def test_missing_hosted_provider_key_uses_safe_fallback(monkeypatch):
    monkeypatch.setenv("GUIDANCE_PROVIDER", "gemini")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)

    provider = configured_guidance_provider()

    assert provider.provider_name == "static-fallback"
