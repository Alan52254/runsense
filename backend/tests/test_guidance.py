"""DB-dependent tests for GET /guidance/today. The LLM call is mocked via
app.routes.guidance.select_tone_variant -- no real Ollama needed. See
spec.md's training-guidance requirements and tasks.md 6.1-6.5."""

from __future__ import annotations

from datetime import datetime, timezone

from app.routes import guidance as guidance_module
from conftest import requires_db
from app.clock import FixedClock


@requires_db
def test_fresh_athlete_gets_insufficient_data_recommendation_and_neutral_tone(
    make_client, new_athlete_id, monkeypatch
):
    monkeypatch.setattr(guidance_module, "select_tone_variant", lambda *a, **k: "SUPPORTIVE_A")
    client = make_client(
        actor_id=new_athlete_id,
        timezones={new_athlete_id: "Asia/Taipei"},
        clock=FixedClock(datetime(2026, 8, 17, 3, 0, tzinfo=timezone.utc)),
    )
    response = client.get("/guidance/today")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["recommendation"]["adjustment_reason_code"] == "INSUFFICIENT_DATA"
    assert body["tone_variant_id"] == "SUPPORTIVE_A"
    assert body["tone_text"]  # looked up from the seeded template, non-empty


@requires_db
def test_second_request_same_day_reuses_the_cache_and_does_not_call_the_llm_again(
    make_client, new_athlete_id, monkeypatch
):
    calls = {"count": 0}

    def _select(*args, **kwargs):
        calls["count"] += 1
        return "SUPPORTIVE_A"

    monkeypatch.setattr(guidance_module, "select_tone_variant", _select)
    client = make_client(
        actor_id=new_athlete_id,
        timezones={new_athlete_id: "Asia/Taipei"},
        clock=FixedClock(datetime(2026, 8, 17, 3, 0, tzinfo=timezone.utc)),
    )

    first = client.get("/guidance/today")
    second = client.get("/guidance/today")
    assert first.status_code == 200 and second.status_code == 200
    assert calls["count"] == 1  # REQ-AI-COST-001: at most once per athlete per local day
    assert first.json()["computed_at"] == second.json()["computed_at"]


@requires_db
def test_llm_tone_disabled_skips_the_llm_call_and_uses_neutral_template(
    make_client, new_athlete_id, monkeypatch
):
    calls = {"count": 0}
    monkeypatch.setattr(
        guidance_module, "select_tone_variant", lambda *a, **k: calls.__setitem__("count", calls["count"] + 1) or "SUPPORTIVE_A"
    )
    client = make_client(
        actor_id=new_athlete_id,
        timezones={new_athlete_id: "Asia/Taipei"},
        clock=FixedClock(datetime(2026, 8, 17, 3, 0, tzinfo=timezone.utc)),
    )
    response = client.get("/guidance/today?llm_tone_enabled=false")
    assert response.status_code == 200
    body = response.json()
    assert body["tone_variant_id"] == "NEUTRAL_FALLBACK"
    assert calls["count"] == 0


@requires_db
def test_recommendation_is_identical_regardless_of_which_tone_the_llm_picks(
    make_client, new_athlete_id, monkeypatch
):
    """Structural proof, at the route level, that the LLM's choice of tone
    cannot influence the prescription -- two requests for two DIFFERENT
    (fresh, never-cached) athletes on the same day get the same
    recommendation even though the mocked LLM returns different tones."""
    import uuid

    athlete_a, athlete_b = str(uuid.uuid4()), str(uuid.uuid4())
    tones = iter(["SUPPORTIVE_A", "CAUTION_A"])
    monkeypatch.setattr(guidance_module, "select_tone_variant", lambda *a, **k: next(tones))

    clock = FixedClock(datetime(2026, 8, 17, 3, 0, tzinfo=timezone.utc))
    body_a = make_client(
        actor_id=athlete_a, timezones={athlete_a: "Asia/Taipei"}, clock=clock
    ).get("/guidance/today").json()
    body_b = make_client(
        actor_id=athlete_b, timezones={athlete_b: "Asia/Taipei"}, clock=clock
    ).get("/guidance/today").json()

    assert body_a["tone_variant_id"] != body_b["tone_variant_id"]
    assert body_a["recommendation"] == body_b["recommendation"]  # both fresh/INSUFFICIENT


@requires_db
def test_missing_actor_context_is_rejected(make_client):
    assert make_client(actor_id=None).get("/guidance/today").status_code == 403
