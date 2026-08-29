import json

import httpx

from app.guidance_providers import GroqGuidanceProvider


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
