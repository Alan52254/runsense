"""Coach Suggestion: an AI 健康教練 proposal the Athlete hands to the coach.

Who decides what (ADR 0003):

  AI 健康教練  suggests. A Coach Proposal is the reviewed engine's ranked
              candidates for a day (ADR 0002) -- never a workout a model
              wrote. The Athlete may apply it to their own guidance, except
              on a day the coach has scheduled: that day is the coach's.
  Athlete     chooses whether to send a suggestion to the coach. It lands
              in their one-to-one room with the coach as a message both
              can see; nothing is scheduled by sending it.
  Coach       decides. A suggestion becomes an ordinary plan card owned by
              the coach, checked and confirmed through the same flow as a
              plan the coach wrote (app/chat_service.confirm_plan).

Nothing in this module writes an Assigned Workout.
"""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

from sqlalchemy import Connection, text

from app import chat_service

SUGGESTION_KIND = "coach_suggestion"

_TYPE_LABEL = {
    "REST_AND_SEEK_CARE": "休息並尋求評估",
    "REST_DAY": "休息日",
    "RECOVERY_RUN": "恢復跑",
    "EASY_RUN": "輕鬆跑",
    "STEADY_RUN": "穩定跑",
}
# engine workout type -> plan item kind (app/chat_plan.structure_for)
_PLAN_KIND = {"RECOVERY_RUN": "recovery", "EASY_RUN": "easy", "STEADY_RUN": "steady"}


class SuggestionNotSchedulable(ValueError):
    """A rest suggestion: there is no session for the coach to schedule."""


def coach_assigned_titles(tx: Connection, athlete_id: uuid.UUID, day: date) -> list[str]:
    """The tracked sessions a coach has scheduled for this athlete on this
    day. Strength / core work (untracked) does not lock a day's running."""
    return list(tx.execute(text(
        """SELECT title FROM assigned_workouts
            WHERE athlete_id = :a AND local_date = :d AND tracked ORDER BY title"""),
        {"a": athlete_id, "d": day}).scalars())


def can_send_to_coach(tx: Connection, user_id: uuid.UUID) -> bool:
    """Whether share_proposal has a coach to send to: the user is an active
    athlete of some team. A coach trying the health coach has none."""
    return tx.execute(_ACTIVE_TEAMS, {"a": user_id}).first() is not None


def describe(candidate: dict[str, Any]) -> str:
    """'輕鬆跑 40 分鐘 · 6.5 km' -- the engine's numbers, as stored."""
    label = _TYPE_LABEL.get(candidate.get("workout_type"), str(candidate.get("workout_type")))
    if not candidate.get("running_allowed") or not candidate.get("duration_minutes"):
        return label
    out = f"{label} {candidate['duration_minutes']} 分鐘"
    if candidate.get("distance_km"):
        out += f" · {candidate['distance_km']:g} km"
    return out


_SELECT_PROPOSAL = text(
    """SELECT id, local_training_date, label, scenario_override, plan_summary
         FROM coach_proposals WHERE id = :id AND athlete_id = :a""")
_ACTIVE_TEAMS = text(
    """SELECT team_id FROM team_memberships
        WHERE user_id = :a AND role = 'athlete' AND status = 'ACTIVE'""")
_ALREADY_SHARED = text(
    """SELECT 1 FROM chat_messages
        WHERE room_id = :r AND retracted_at IS NULL
          AND payload->>'kind' = :kind AND payload->>'proposal_id' = :p""")
_POST = text(
    """INSERT INTO chat_messages (room_id, sender_kind, sender_id, body, payload)
       VALUES (:r, 'user', :a, :b, CAST(:p AS jsonb)) RETURNING id""")


def share_proposal(tx: Connection, athlete_id: uuid.UUID, proposal_id: uuid.UUID) -> list[str] | None:
    """Send one of the athlete's own proposals to each of their coaches.

    Posts it, as the athlete, in every one-to-one room they have with a
    team's coaches; sharing the same proposal twice posts nothing new.
    Returns the room ids, or None when the proposal is not this athlete's.
    """
    row = tx.execute(_SELECT_PROPOSAL, {"id": proposal_id, "a": athlete_id}).first()
    if row is None:
        return None
    candidates = (row.plan_summary or {}).get("candidates") or []
    if not candidates:
        return None
    top = candidates[0]
    day = row.local_training_date
    payload = {
        "kind": SUGGESTION_KIND,
        "proposal_id": str(row.id),
        "date": day.isoformat(),
        "label": row.label,
        "candidate": top,
        "facts": row.scenario_override or {},
        "coach_assigned": coach_assigned_titles(tx, athlete_id, day),
    }
    body = (f"想請教練看一下 AI 健康教練給我的 {day.month}/{day.day} 建議：{describe(top)}"
            + (f"（{row.label}）" if row.label else ""))
    rooms = []
    for team_id in tx.execute(_ACTIVE_TEAMS, {"a": athlete_id}).scalars():
        room_id = chat_service.ensure_room(tx, team_id, athlete_id)
        if tx.execute(_ALREADY_SHARED, {"r": room_id, "kind": SUGGESTION_KIND, "p": str(row.id)}).first() is None:
            tx.execute(_POST, {"r": room_id, "a": athlete_id, "b": body,
                               "p": json.dumps(payload, ensure_ascii=False)})
        rooms.append(str(room_id))
    return rooms


def plan_payload_from_suggestion(suggestion: dict[str, Any], athlete: dict[str, Any],
                                 source_text: str, today: date) -> dict[str, Any]:
    """The plan card a coach gets from a suggestion: one day, one athlete,
    one continuous run at the engine's duration and distance.

    Built in the same shape app/chat_plan.parse_plan produces, so the card,
    its preview, editing, confirming and revoking are the existing ones. No
    model is involved, so there is nothing to ground against the source and
    the day starts with no problems -- the coach still checks and confirms.
    """
    candidate = suggestion.get("candidate") or {}
    kind = _PLAN_KIND.get(candidate.get("workout_type"))
    minutes = candidate.get("duration_minutes") or 0
    if kind is None or not candidate.get("running_allowed") or minutes <= 0:
        raise SuggestionNotSchedulable("這是休息建議，不需要排課")
    km = candidate.get("distance_km") or 0
    block = {"reps": 1, "distance_m": round(km * 1000) if km else None, "duration_s": int(minutes * 60),
             "target_s_per_km": None, "target_text": None, "target_mode": "exact",
             "rest_s": None, "rest_after_s": None}
    day = {"key": "d0", "date": suggestion["date"], "date_hint": None,
           "source": f"AI 健康教練建議：{describe(candidate)}",
           "items": [{"type": "run", "kind": kind, "title": describe(candidate), "variants": {"all": [block]}}],
           "problems": [], "removed": False, "edited": False}
    return {"plan": {"days": [day], "unparsed": []},
            "athletes": [{**athlete, "selected": True}],
            "source_text": source_text,
            "today": today.isoformat(),
            "from_suggestion": suggestion.get("proposal_id")}
