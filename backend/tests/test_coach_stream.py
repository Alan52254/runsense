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
    monkeypatch.setattr(guidance_routes, "stream_grounded_coach_answer",
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


def _member(admin_engine, user_id, role) -> None:
    team_id, coach_id = uuid.uuid4(), uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(text("INSERT INTO teams (id, name) VALUES (:id, :n)"), {"id": team_id, "n": f"t-{team_id}"})
        conn.execute(text("INSERT INTO users (id, email, password_hash) VALUES (:id, :e, 'x')"),
                     {"id": coach_id, "e": f"{coach_id}@example.test"})
        for uid, r in ((user_id, role), (coach_id, "coach")):
            conn.execute(text("INSERT INTO team_memberships (team_id, user_id, role, status, joined_at) "
                              "VALUES (:t, :u, :r, 'ACTIVE', now())"), {"t": team_id, "u": uid, "r": r})


def _stream_proposal(make_client, user_id) -> dict:
    response = make_client(actor_id=str(user_id), timezones={str(user_id): "Asia/Taipei"}).post(
        "/guidance/chat/stream", json={"messages": [{"role": "user", "content": "我今天只有 30 分鐘"}]})
    (proposal,) = [e["proposal"] for e in _events(response.text) if "proposal" in e]
    return proposal


@requires_db
def test_only_someone_with_a_coach_is_offered_sending_to_the_coach(make_client, admin_engine, monkeypatch):
    """A coach trying the health coach has no coach above them: the card must
    say so up front instead of failing when they press 「傳給教練」."""
    monkeypatch.setattr(guidance_routes, "propose_scenario_override",
                        lambda messages, context=None: {"available_minutes": 30})
    monkeypatch.setattr(guidance_routes, "stream_grounded_coach_answer", lambda messages, context=None: iter(["好"]))
    athlete, head_coach = _athlete(admin_engine), _athlete(admin_engine)
    _member(admin_engine, athlete, "athlete")
    _member(admin_engine, head_coach, "head_coach")

    assert _stream_proposal(make_client, athlete)["can_send_to_coach"] is True
    assert _stream_proposal(make_client, head_coach)["can_send_to_coach"] is False


class _ScriptedModel:
    """A coach model that answers from a script, one answer per call."""

    name, model = "scripted", "scripted"

    def __init__(self, *answers: str) -> None:
        self._answers = list(answers)
        self.calls = 0

    def is_configured(self) -> bool:
        return True

    def complete(self, messages, *, temperature, as_json=False, timeout_seconds=8.0):
        self.calls += 1
        return self._answers.pop(0)


def _answer_with(make_client, admin_engine, monkeypatch, model) -> str:
    from app import llm_client

    athlete_id = _athlete(admin_engine)
    monkeypatch.setattr(llm_client, "configured_coach_provider", lambda: model)
    monkeypatch.setattr(guidance_routes, "propose_scenario_override", lambda messages, context=None: {})
    response = make_client(actor_id=str(athlete_id), timezones={str(athlete_id): "Asia/Taipei"}).post(
        "/guidance/chat/stream", json={"messages": [{"role": "user", "content": "我今天只有 30 分鐘，怎麼跑？"}]})
    return "".join(e["delta"] for e in _events(response.text) if "delta" in e)


@requires_db
def test_an_answer_with_a_number_the_athlete_never_had_is_asked_for_again(make_client, admin_engine, monkeypatch):
    model = _ScriptedModel("你的負荷比是 1.2，今天跑 30 分鐘輕鬆跑。", "用你有的 30 分鐘輕鬆跑就好。")
    answer = _answer_with(make_client, admin_engine, monkeypatch, model)

    assert answer == "用你有的 30 分鐘輕鬆跑就好。"
    assert model.calls == 2


@requires_db
def test_a_number_still_unfounded_after_asking_again_is_removed_and_said_so(make_client, admin_engine, monkeypatch):
    model = _ScriptedModel("你的負荷比是 1.2。用 30 分鐘輕鬆跑。", "負荷比 1.2 偏高。用 30 分鐘輕鬆跑。")
    answer = _answer_with(make_client, admin_engine, monkeypatch, model)

    assert "1.2" not in answer
    assert "用 30 分鐘輕鬆跑。" in answer
    assert "已移除" in answer


@requires_db
def test_list_numbering_is_not_mistaken_for_a_made_up_number(make_client, admin_engine, monkeypatch):
    model = _ScriptedModel("1. 先熱身\n2. 用 30 分鐘輕鬆跑")
    answer = _answer_with(make_client, admin_engine, monkeypatch, model)

    assert answer == "1. 先熱身\n2. 用 30 分鐘輕鬆跑"
    assert model.calls == 1
