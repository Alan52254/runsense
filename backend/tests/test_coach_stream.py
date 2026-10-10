"""What the AI 健康教練 streams back when an Athlete asks about their
training (POST /guidance/chat/stream): the steps it took, its answer, and a
suggestion the Athlete can send to their coach (ADR 0003)."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import text

from app.routes import guidance as guidance_routes
from conftest import requires_db


def _athlete(admin_engine) -> uuid.UUID:
    athlete_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(text("INSERT INTO users (id, email, password_hash) VALUES (:id, :e, 'x')"),
                     {"id": athlete_id, "e": f"{athlete_id}@example.test"})
    return athlete_id


def _events(body: str) -> list[dict]:
    out = []
    for line in body.splitlines():
        if line.startswith("data: ") and line != "data: [DONE]":
            out.append(json.loads(line[len("data: "):]))
    return out


@requires_db
def test_asking_to_plan_streams_the_steps_taken_and_a_suggestion_for_the_coach(
    make_client, admin_engine, monkeypatch
):
    athlete_id = _athlete(admin_engine)
    # the model: it heard "only 30 minutes", and answers in one piece
    monkeypatch.setattr(guidance_routes, "propose_scenario_override",
                        lambda messages, context=None: {"available_minutes": 30})
    monkeypatch.setattr(guidance_routes, "stream_coach_answer",
                        lambda messages, context=None: iter(["可以跑輕鬆一點。"]))

    response = make_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"}).post(
        "/guidance/chat/stream",
        json={"messages": [{"role": "user", "content": "我今天只有 30 分鐘，幫我排一下課表"}]},
    )

    assert response.status_code == 200, response.text
    events = _events(response.text)
    # the trace: what the coach did before answering, in order
    assert [e["step"] for e in events if "step" in e] == [
        "READ_TRAINING_LOAD", "REVIEWED_GUIDANCE", "CONSIDERED_OPTIONS"]
    assert "".join(e["delta"] for e in events if "delta" in e) == "可以跑輕鬆一點。"
    # the suggestion: the engine's candidates, which the athlete may apply
    # or send to the coach
    (proposal,) = [e["proposal"] for e in events if "proposal" in e]
    assert proposal["candidates"], proposal
    assert proposal["facts"]["available_minutes"] == 30
    assert proposal["self_apply_allowed"] is True
    assert proposal["coach_assigned"] == []
    shared = make_client(actor_id=str(athlete_id)).post(f"/guidance/proposals/{proposal['id']}/share")
    assert shared.status_code == 409  # no team yet: there is no coach to send it to
