"""The team chat's @AI helper and its confirmation cards.

The helper only acts when a message mentions @AI. It then reads that room's
messages since the previous @AI (at most the last 50) and does one of the
following -- which ones are open to the sender is fixed by their role
(route()), not chosen by the model:

  schedule     a coach's training plan -> a plan card only that coach sees
               (app/chat_plan.py); nothing is scheduled until confirmed
  body_report  an athlete describing how their body feels -> a body-status
               card only that athlete sees; confirmed, it becomes a normal
               injury report, shared with the coach only as far as the
               athlete's consent allows. The public reply never repeats it.
  data         a question about someone's load / injuries -> never answered
               in the team room; in a direct room only within the asker's
               own access (the athlete themself, or a coach the athlete has
               granted training-load access)
  question     general training knowledge -> a short public answer; pace
               arithmetic in it is computed here, not by the model

Red-flag symptoms go through the existing deterministic safety triage
(app/safety_triage.py); its advice appears only on the athlete's own card.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, text
from sqlalchemy.exc import IntegrityError

from app import groq_client, personas
from app.load_projection import planned_load, project
from app.chat_plan import blocks_for, day_blocking_problems, estimate_minutes, parse_plan, structure_for, summary_line
from app.safety_triage import SafetyTriageInput, assess_safety_triage

logger = logging.getLogger("app.chat_service")

AI_MENTION = re.compile(r"@\s*AI\b", re.I)
CONTEXT_LIMIT = 50
_MODELS = ("qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b")
_COACH_ROLES = ("coach", "head_coach", "owner")

_RED_FLAG_FIELDS = (
    "chest_pain_or_breathing_difficulty", "collapse_confusion_or_extreme_heat_illness",
    "head_injury_with_neurological_symptoms", "uncontrolled_bleeding",
    "localized_bone_pain_worse_with_weight_bearing", "unable_to_bear_weight", "new_numbness_or_weakness",
    "hot_swollen_joint_with_fever", "visible_deformity",
)
_RED_FLAG_LABEL = {
    "chest_pain_or_breathing_difficulty": "胸痛或呼吸困難",
    "collapse_confusion_or_extreme_heat_illness": "昏倒、意識混亂或疑似中暑",
    "head_injury_with_neurological_symptoms": "頭部撞擊並有神經症狀",
    "uncontrolled_bleeding": "流血不止",
    "localized_bone_pain_worse_with_weight_bearing": "局部骨頭痛、踩地更痛",
    "unable_to_bear_weight": "無法承重行走",
    "new_numbness_or_weakness": "新出現的麻木或無力",
    "hot_swollen_joint_with_fever": "關節紅腫熱痛並發燒",
    "visible_deformity": "明顯變形",
}
# deterministic backstop for the model: any of these words flags the symptom
_RED_FLAG_WORDS = {
    "chest_pain_or_breathing_difficulty": ("胸痛", "胸悶", "胸口痛", "呼吸困難", "喘不過氣", "吸不到氣"),
    "collapse_confusion_or_extreme_heat_illness": ("昏倒", "暈倒", "失去意識", "意識不清", "中暑", "熱衰竭"),
    "head_injury_with_neurological_symptoms": ("撞到頭", "頭部撞擊", "腦震盪"),
    "uncontrolled_bleeding": ("流血不止", "血流不止"),
    "localized_bone_pain_worse_with_weight_bearing": ("骨頭痛", "壓痛點", "踩地更痛", "疲勞性骨折"),
    "unable_to_bear_weight": ("不能走", "無法走路", "無法承重", "不能踩"),
    "new_numbness_or_weakness": ("麻木", "發麻", "使不上力"),
    "hot_swollen_joint_with_fever": ("發燒",),
    "visible_deformity": ("變形",),
}


# ---------------------------------------------------------------- helpers


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def member_role(conn: Connection, team_id: uuid.UUID, user_id: uuid.UUID) -> str | None:
    return conn.execute(text("SELECT role FROM team_memberships WHERE team_id=:t AND user_id=:u AND status='ACTIVE'"),
                        {"t": team_id, "u": user_id}).scalar_one_or_none()


def is_coach(role: str | None) -> bool:
    return role in _COACH_ROLES


def post_message(conn: Connection, room_id: uuid.UUID, sender_kind: str, body: str,
                 sender_id: uuid.UUID | None = None, payload: dict | None = None) -> uuid.UUID:
    return conn.execute(text(
        """INSERT INTO chat_messages (room_id, sender_kind, sender_id, body, payload)
           VALUES (:r, :k, :s, :b, CAST(:p AS jsonb)) RETURNING id"""),
        {"r": room_id, "k": sender_kind, "s": sender_id, "b": body[:4000],
         "p": json.dumps(payload or {}, ensure_ascii=False)}).scalar_one()


def ensure_room(conn: Connection, team_id: uuid.UUID, athlete_id: uuid.UUID | None = None) -> uuid.UUID:
    """The team's room (athlete_id None) or that athlete's direct room,
    created on first use.

    Not INSERT ... ON CONFLICT: under row-level security that also checks
    the new row against the room's read policy, which asks whether the room
    already exists -- so it always fails for the runtime role. A concurrent
    first use loses the unique index race inside a savepoint instead."""
    kind = "team" if athlete_id is None else "direct"
    find = text("SELECT id FROM chat_rooms WHERE team_id = :t AND kind = :k "
                "AND athlete_id IS NOT DISTINCT FROM :a")
    params = {"t": team_id, "k": kind, "a": athlete_id}
    room_id = conn.execute(find, params).scalar_one_or_none()
    if room_id is None:
        try:
            with conn.begin_nested():
                conn.execute(text("INSERT INTO chat_rooms (team_id, kind, athlete_id) VALUES (:t, :k, :a)"), params)
        except IntegrityError:
            pass
        room_id = conn.execute(find, params).scalar_one()
    return room_id


def local_today(conn: Connection, user_id: uuid.UUID) -> date:
    tz = conn.execute(text("SELECT timezone FROM athlete_profiles WHERE user_id=:u"), {"u": user_id}).scalar_one_or_none()
    return datetime.now(ZoneInfo(tz or "Asia/Taipei")).date()


def _context(conn: Connection, room_id: uuid.UUID, message: Any) -> list[Any]:
    """Messages since the previous @AI in this room (exclusive), up to and
    including this one, at most CONTEXT_LIMIT, retracted ones excluded."""
    previous = conn.execute(text(
        """SELECT max(created_at) FROM chat_messages
            WHERE room_id=:r AND mentions_ai AND created_at < :at AND retracted_at IS NULL"""),
        {"r": room_id, "at": message.created_at}).scalar_one_or_none()
    rows = conn.execute(text(
        """SELECT m.id, m.sender_kind, m.sender_id, m.body, m.created_at, u.display_name,
                  tm.role
             FROM chat_messages m
             JOIN chat_rooms r ON r.id = m.room_id
             LEFT JOIN users u ON u.id = m.sender_id
             LEFT JOIN team_memberships tm ON tm.team_id = r.team_id AND tm.user_id = m.sender_id
            WHERE m.room_id=:r AND m.retracted_at IS NULL AND m.sender_kind = 'user'
              AND m.created_at > COALESCE(:prev, '-infinity'::timestamptz) AND m.created_at <= :at
            ORDER BY m.created_at DESC LIMIT :lim"""),
        {"r": room_id, "prev": previous, "at": message.created_at, "lim": CONTEXT_LIMIT}).all()
    return list(reversed(rows))


def _strip_mention(body: str) -> str:
    return AI_MENTION.sub("", body).strip()


# ---------------------------------------------------------------- intent

# Hard routing: what the helper may do for someone is fixed by their role,
# not by what a model thinks they meant. Only a coach schedules (an athlete
# who wants a different day takes an AI 健康教練 suggestion to the coach --
# app/coach_handoff.py); only an athlete files a body report.
COACH_INTENTS = ("schedule", "data", "question", "other")
ATHLETE_INTENTS = ("body_report", "data", "question", "other")
# an athlete asking the helper to schedule is pointed to the coach instead
REDIRECT_TO_COACH = "redirect_to_coach"


def allowed_intents(role: str | None) -> tuple[str, ...]:
    return COACH_INTENTS if is_coach(role) else ATHLETE_INTENTS


def route(own_text: str, role: str | None, classify_fn) -> str:
    """The handler for one @AI message.

    An athlete whose own words name a red-flag symptom goes straight to a
    body report: Safety Triage must not depend on a model choosing it, nor
    on a model being reachable (ADR 0001). Otherwise the model picks, but
    only among what this role may do."""
    if not is_coach(role) and any(keyword_red_flags(own_text).values()):
        return "body_report"
    intent = classify_fn()
    if intent in allowed_intents(role):
        return intent
    if intent == "schedule":
        return REDIRECT_TO_COACH
    return "question"


def classify(text_for_ai: str, sender_role: str | None, deadline: float) -> str:
    who = "教練" if is_coach(sender_role) else "選手"
    allowed = allowed_intents(sender_role)
    system = (personas.system_prompt("team_assistant", "router", with_soul=False)
              + f"\n\n這次允許的 intent：{'、'.join(allowed)}")
    for model in _MODELS:
        try:
            raw = groq_client.chat(model, [{"role": "system", "content": system},
                                           {"role": "user", "content": f"發訊息的人是{who}。\n\n{text_for_ai}"}],
                                   deadline=deadline, max_tokens=200, temperature=0.0, json_mode=True)
            intent = json.loads(raw).get("intent")
            if intent in ("schedule", "body_report", "data", "question", "other"):
                return intent
        except groq_client.GroqUnavailable:
            continue
        except (json.JSONDecodeError, AttributeError):
            continue
    raise groq_client.GroqUnavailable("AI 無法判斷這則訊息")


# ---------------------------------------------------------------- processing


def process_ai_message(engine, message_id: uuid.UUID) -> None:
    """Background job for one @AI message. Never raises."""
    try:
        with engine.begin() as conn:
            msg = conn.execute(text(
                """SELECT m.*, r.team_id, r.kind AS room_kind, r.athlete_id AS room_athlete
                     FROM chat_messages m JOIN chat_rooms r ON r.id = m.room_id WHERE m.id=:id"""),
                {"id": message_id}).first()
            if msg is None or msg.retracted_at is not None:
                return
            role = member_role(conn, msg.team_id, msg.sender_id)
            context = _context(conn, msg.room_id, msg)
        deadline = time.monotonic() + 100
        transcript = "\n".join(
            f"{'教練' if is_coach(r.role) else '選手'}{r.display_name or ''}：{_strip_mention(r.body)}" for r in context)
        own = "\n".join(_strip_mention(r.body) for r in context if r.sender_id == msg.sender_id)
        intent = route(own, role, lambda: classify(transcript, role, deadline))
        if intent == REDIRECT_TO_COACH:
            _reply(engine, msg, "課表由教練安排。想調整自己的課表，可以先問「AI 健康教練」取得建議，"
                                "再按「傳給教練」，由教練決定要不要排進去。")
        elif intent == "schedule":
            _handle_schedule(engine, msg, role, context, deadline)
        elif intent == "body_report":
            _handle_body_report(engine, msg, role, context, deadline)
        elif intent == "data":
            _handle_data(engine, msg, role)
        elif intent == "question":
            _handle_question(engine, msg, deadline)
        else:
            _reply(engine, msg, "我可以幫教練排課（@AI 加上課表）、幫選手記錄身體狀況，或回答一般訓練問題。")
        with engine.begin() as conn:
            conn.execute(text("UPDATE chat_messages SET ai_state='done' WHERE id=:id"), {"id": message_id})
    except Exception as exc:  # noqa: BLE001 -- the room must hear back either way
        logger.warning("chat_ai_failed message=%s err=%r", message_id, exc)
        with engine.begin() as conn:
            conn.execute(text("UPDATE chat_messages SET ai_state='failed' WHERE id=:id"), {"id": message_id})
            room = conn.execute(text("SELECT room_id FROM chat_messages WHERE id=:id"), {"id": message_id}).scalar_one()
            busy = isinstance(exc, groq_client.GroqUnavailable)
            post_message(conn, room, "ai",
                         "AI 目前使用量已滿，請稍後再 @AI 一次。" if busy else "AI 這次處理失敗，請稍後再 @AI 一次。",
                         payload={"reply_to": str(message_id)})


def _reply(engine, msg: Any, body: str, payload: dict | None = None) -> None:
    with engine.begin() as conn:
        post_message(conn, msg.room_id, "ai", body, payload={"reply_to": str(msg.id), **(payload or {})})


def _athletes_for(conn: Connection, msg: Any) -> list[dict[str, Any]]:
    """Team room: every active athlete; direct room: that athlete."""
    rows = conn.execute(text(
        """SELECT u.id, u.display_name, u.email, p.sex FROM team_memberships tm
             JOIN users u ON u.id = tm.user_id LEFT JOIN athlete_profiles p ON p.user_id = u.id
            WHERE tm.team_id=:t AND tm.status='ACTIVE' AND tm.role='athlete'
              AND (CAST(:a AS uuid) IS NULL OR u.id = CAST(:a AS uuid)) ORDER BY u.display_name"""),
        {"t": msg.team_id, "a": msg.room_athlete}).all()
    return [{"id": str(r.id), "name": r.display_name or r.email.split("@")[0], "sex": r.sex, "selected": True}
            for r in rows]


def _handle_schedule(engine, msg: Any, role: str | None, context: list[Any], deadline: float) -> None:
    if not is_coach(role):
        _reply(engine, msg, "排課需要由教練 @AI。選手要回報身體狀況，可以直接 @AI 描述。")
        return
    # the plan is taken from coaches' own messages only: an athlete's chat
    # in between is never scheduled as training
    plan_text = "\n".join(_strip_mention(r.body) for r in context if is_coach(r.role))
    with engine.begin() as conn:
        today = local_today(conn, msg.sender_id)
        athletes = _athletes_for(conn, msg)
    plan = parse_plan(plan_text, today, deadline_s=max(10.0, deadline - time.monotonic()))
    if not plan["days"]:
        if plan.get("error_kind") == "no_content":
            _reply(engine, msg, "這次 @AI 之前的新訊息裡沒有找到課表內容（我只讀上一次 @AI 之後的訊息）。"
                                "請把日期和課表寫在同一則，例如：「@AI 10/12 400*8 配速 3:20 休 90 秒」。")
        else:
            _reply(engine, msg, "AI 服務暫時忙碌，這次沒能整理課表，請稍等一下再 @AI 一次。")
        return
    payload = {"plan": plan, "athletes": athletes, "source_text": plan_text, "today": today.isoformat()}
    with engine.begin() as conn:
        card_id = conn.execute(text(
            """INSERT INTO chat_cards (room_id, source_message_id, owner_id, kind, payload)
               VALUES (:r, :m, :o, 'plan', CAST(:p AS jsonb)) RETURNING id"""),
            {"r": msg.room_id, "m": msg.id, "o": msg.sender_id, "p": json.dumps(payload, ensure_ascii=False)}).scalar_one()
    dated = [d["date"] for d in plan["days"] if d["date"]]
    span = f"（{_md(min(dated))}–{_md(max(dated))}）" if dated else ""
    flagged = sum(1 for d in plan["days"] if d["problems"])
    note = f"，其中 {flagged} 天有需要確認的地方" if flagged else ""
    _reply(engine, msg, f"已整理出 {len(plan['days'])} 天課表{span}{note}，請教練在確認卡上檢查後排入。",
           {"card_id": str(card_id)})


def _md(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.month}/{d.day}"


# ---------------------------------------------------------------- body report

_BODY_PROMPT = personas.system_prompt("team_assistant", "body_report", with_soul=False)


def severity_from_score(score: float | None) -> str | None:
    if score is None:
        return None
    if score <= 0:
        return "NONE"
    if score <= 3:
        return "MILD"
    if score <= 6:
        return "MODERATE"
    return "SEVERE"


def keyword_red_flags(text_: str) -> dict[str, bool]:
    return {k: any(w in text_ for w in words) for k, words in _RED_FLAG_WORDS.items()}


def triage_for(severity: str | None, body_part: str | None, flags: dict[str, bool]) -> dict[str, Any]:
    decision = assess_safety_triage(SafetyTriageInput(
        severity_band=severity, body_part=body_part,
        **{k: bool(flags.get(k)) for k in _RED_FLAG_FIELDS}))
    return {"urgency": decision.urgency.value, "running_allowed": decision.running_allowed,
            "next_step": decision.immediate_next_step, "rule_ids": list(decision.matched_rule_ids),
            "flags": [_RED_FLAG_LABEL[k] for k in _RED_FLAG_FIELDS if flags.get(k)]}


def _handle_body_report(engine, msg: Any, role: str | None, context: list[Any], deadline: float) -> None:
    if is_coach(role):
        _reply(engine, msg, "身體狀況回報是給選手記錄自己的狀況使用的。")
        return
    own = "\n".join(_strip_mention(r.body) for r in context if r.sender_id == msg.sender_id)
    data: dict[str, Any] = {}
    for model in _MODELS:
        try:
            data = json.loads(groq_client.chat(model, [{"role": "system", "content": _BODY_PROMPT},
                                                        {"role": "user", "content": own}],
                                               deadline=deadline, max_tokens=500, temperature=0.0, json_mode=True))
            break
        except groq_client.GroqUnavailable:
            continue
        except json.JSONDecodeError:
            continue
    # no model: the card is still made from the athlete's own words and the
    # keyword red flags, so triage never waits on the model (ADR 0001); the
    # athlete picks the pain level on the card
    body_part = data.get("body_part") if data.get("body_part") and str(data["body_part"]) in own else None
    score = data.get("pain_score")
    try:
        score = float(score) if score is not None else None
    except (TypeError, ValueError):
        score = None
    # a pain score is only taken when the athlete wrote that number
    if score is not None and not re.search(rf"(?<![\d.]){score:g}(?![\d.])", own):
        score = None
    if score is not None and not 0 <= score <= 10:
        score = None
    model_flags = data.get("red_flags") or {}
    words = keyword_red_flags(own)
    flags = {k: bool(model_flags.get(k)) or words[k] for k in _RED_FLAG_FIELDS}
    severity = severity_from_score(score)
    payload = {"body_part": body_part, "pain_score": score, "severity_band": severity,
               "description": str(data.get("description") or own)[:500], "red_flags": flags,
               "triage": triage_for(severity, body_part, flags), "quote": own[:1000]}
    with engine.begin() as conn:
        conn.execute(text(
            """INSERT INTO chat_cards (room_id, source_message_id, owner_id, kind, payload)
               VALUES (:r, :m, :o, 'body_report', CAST(:p AS jsonb))"""),
            {"r": msg.room_id, "m": msg.id, "o": msg.sender_id, "p": json.dumps(payload, ensure_ascii=False)})
    _reply(engine, msg, "已幫你建立私人回報，請在只有你看得到的卡片上確認。")


# ---------------------------------------------------------------- data / questions


def _handle_data(engine, msg: Any, role: str | None) -> None:
    if msg.room_kind == "team":
        where = "選手詳情頁" if is_coach(role) else "與教練的一對一聊天室或 AI 健康教練"
        _reply(engine, msg, f"群組裡不公開任何人的負荷或傷痛數據，請到{where}查看。")
        return
    athlete_id = msg.room_athlete
    with engine.begin() as conn:
        if is_coach(role):
            granted = conn.execute(text(
                "SELECT 1 FROM consent_grants WHERE team_id=:t AND athlete_id=:a AND scope='training_load' AND granted"),
                {"t": msg.team_id, "a": athlete_id}).first()
            if granted is None:
                _reply(engine, msg, "這位選手沒有授權教練查看訓練負荷。")
                return
        load = conn.execute(text(
            """SELECT date, acute_load, chronic_load, load_ratio FROM training_load_daily
                WHERE athlete_id=:a AND unit='AU' AND date <= CURRENT_DATE ORDER BY date DESC LIMIT 1"""),
            {"a": athlete_id}).first()
    if load is None:
        _reply(engine, msg, "目前還沒有訓練負荷資料。")
        return
    ratio = f"{float(load.load_ratio):.2f}" if load.load_ratio is not None else "資料不足"
    _reply(engine, msg, f"截至 {load.date.month}/{load.date.day}：近 7 天負荷 {float(load.acute_load):.0f} AU，"
                        f"28 天基準 {float(load.chronic_load):.0f} AU，短長期負荷比 {ratio}。")


_PACE_PAIR = re.compile(r"(\d{2,5})\s*(?:m|公尺|米)?\s*(?:跑|要|在|用)?\s*(\d{2,3}(?:\.\d)?)\s*秒")
_PACE_KM = re.compile(r"(\d{1,2}):(\d{2})\s*(?:/\s*km|/公里|配速)")


def _mmss(sec: float) -> str:
    whole = round(sec, 1)
    m, s = divmod(whole, 60)
    return f"{int(m)}:{s:04.1f}" if s != int(s) else f"{int(m)}:{int(s):02d}"


def pace_facts(question: str) -> list[str]:
    """Pace arithmetic the answer may need, computed here."""
    facts = []
    for dist, sec in _PACE_PAIR.findall(question):
        d, s = float(dist), float(sec)
        if 50 <= d <= 10000 and s > 0:
            per_km = s / d * 1000
            if 120 <= per_km <= 900:
                facts.append(f"{d:g}m 跑 {s:g} 秒 = 每公里 {_mmss(per_km)}"
                             f"（每 400m {per_km * 0.4:g} 秒）")
    for mm, ss in _PACE_KM.findall(question):
        p = int(mm) * 60 + int(ss)
        if 120 <= p <= 900:
            facts.append(f"配速 {mm}:{ss}/km = 每 400m {p * 0.4:.1f} 秒、每 200m {p * 0.2:.1f} 秒、每 1000m {p:.0f} 秒")
    return facts


_QA_PROMPT = personas.system_prompt("team_assistant", "qa")


def _handle_question(engine, msg: Any, deadline: float) -> None:
    question = _strip_mention(msg.body)
    facts = pace_facts(question)
    user = question + (("\n\n已計算的換算：\n" + "\n".join(facts)) if facts else "")
    for model in _MODELS:
        try:
            answer = groq_client.chat(model, [{"role": "system", "content": _QA_PROMPT},
                                              {"role": "user", "content": user}], deadline=deadline, max_tokens=600)
        except groq_client.GroqUnavailable:
            continue
        if facts:
            allowed = set(re.findall(r"\d+(?:[.:]\d+)?", user))
            stray = [n for n in re.findall(r"\d+(?:[.:]\d+)?", answer) if n not in allowed]
            if stray:
                # numeric answers must come from the computed conversions
                answer = "換算結果：\n" + "\n".join(f"- {f}" for f in facts)
        _reply(engine, msg, answer)
        return
    if facts:
        _reply(engine, msg, "換算結果：\n" + "\n".join(f"- {f}" for f in facts))
        return
    raise groq_client.GroqUnavailable("AI 無法回答")


# ---------------------------------------------------------------- plan card: preview & confirm


def _day_completed(conn: Connection, athlete_id: uuid.UUID, day: date) -> bool:
    """A day is done when its tracked assignment is marked completed, or the
    athlete has a recorded run that day."""
    if day > now_utc().date() + timedelta(days=1):
        return False
    marked = conn.execute(text("SELECT 1 FROM assigned_workouts WHERE athlete_id=:a AND local_date=:d "
                               "AND tracked AND status='COMPLETED' LIMIT 1"), {"a": athlete_id, "d": day}).first()
    ran = conn.execute(text("SELECT 1 FROM completed_activities WHERE athlete_id=:a AND local_training_date=:d "
                            "AND deleted_at IS NULL LIMIT 1"), {"a": athlete_id, "d": day}).first()
    return bool(marked or ran)


def plan_preview(conn: Connection, payload: dict[str, Any], team_id: uuid.UUID | None = None) -> dict[str, Any]:
    """For the card: per day and athlete, what will be written and whether
    it creates, overwrites or (already done) skips -- and, given the team,
    what it would do to each athlete's load ratio (app/load_projection.py),
    shown only where the athlete lets the coach see their training load."""
    rows = []
    for day in payload["plan"]["days"]:
        if day.get("removed"):
            continue
        entries = []
        for ath in payload["athletes"]:
            if not ath.get("selected"):
                continue
            items = []
            for item in day["items"]:
                record = assignment_record(item, ath.get("sex"))
                if item["type"] == "run":
                    blocks = blocks_for(item, ath.get("sex"))
                    items.append({"title": item["title"], "summary": summary_line(item, blocks) if blocks else None,
                                  "missing_variant": blocks is None,
                                  # exactly what confirming writes for this athlete
                                  "blocks": blocks or [], "record": record})
                else:
                    items.append({"title": item["title"], "summary": "不追蹤完成", "missing_variant": False,
                                  "blocks": [], "record": record})
            status = "need_date"
            if day.get("date"):
                d = date.fromisoformat(day["date"])
                aid = uuid.UUID(ath["id"])
                if _day_completed(conn, aid, d):
                    status = "skip_completed"
                elif conn.execute(text("SELECT 1 FROM assigned_workouts WHERE athlete_id=:a AND local_date=:d LIMIT 1"),
                                  {"a": aid, "d": d}).first():
                    status = "overwrite"
                else:
                    status = "new"
            entries.append({"athlete_id": ath["id"], "name": ath["name"], "status": status, "items": items})
        rows.append({"key": day["key"], "date": day.get("date"), "entries": entries})
    if team_id is not None:
        _attach_load_projection(conn, team_id, rows)
    return {"rows": rows}


def _attach_load_projection(conn: Connection, team_id: uuid.UUID, rows: list[dict[str, Any]]) -> None:
    planned: dict[str, dict[date, float]] = {}
    for row in rows:
        for entry in row["entries"]:
            if row["date"] and entry["status"] in ("new", "overwrite"):
                day = planned.setdefault(entry["athlete_id"], {})
                d = date.fromisoformat(row["date"])
                for item in entry["items"]:
                    record = item.get("record")
                    if record and record["tracked"]:
                        day[d] = day.get(d, 0.0) + planned_load(record["duration_minutes"],
                                                                record["intensity_label"])
    projections: dict[str, tuple[bool, dict[str, Any] | None]] = {}
    for row in rows:
        for entry in row["entries"]:
            aid = entry["athlete_id"]
            if aid not in projections:
                athlete = uuid.UUID(aid)
                consent = conn.execute(text(
                    "SELECT 1 FROM consent_grants WHERE team_id=:t AND athlete_id=:a "
                    "AND scope='training_load' AND granted"), {"t": team_id, "a": athlete}).first() is not None
                projections[aid] = (consent, project(conn, athlete, local_today(conn, athlete),
                                                     planned.get(aid, {})) if consent else None)
            entry["load_consent"], entry["projected_load"] = projections[aid]


_INTENSITY = {"intervals": "間歇", "tempo": "節奏跑", "easy": "輕鬆跑", "long": "長距離", "race": "比賽", "other": "跑步",
              "recovery": "恢復跑", "steady": "穩定跑"}


def assignment_record(item: dict[str, Any], sex: str | None) -> dict[str, Any] | None:
    """The assigned_workouts row one plan item becomes for an athlete of this
    sex -- shared by the card preview and confirm_plan, so what the coach
    checks on the card is exactly what gets written. None: no variant for
    this athlete (nothing is written)."""
    if item["type"] != "run":
        return {"title": item["title"], "duration_minutes": 1,
                "intensity_label": "重訓" if item["type"] == "strength" else "核心",
                "structure": [], "tracked": False, "notes": item.get("content")}
    blocks = blocks_for(item, sex)
    if not blocks:
        return None
    return {"title": (summary_line(item, blocks) if any(b.get("target_text") for b in blocks)
                      else item["title"])[:200],
            "duration_minutes": estimate_minutes(item, blocks),
            "intensity_label": _INTENSITY.get(item.get("kind"), "跑步"),
            "structure": structure_for(item, blocks), "tracked": True, "notes": None}


def confirm_plan(conn: Connection, card: Any, team_id: uuid.UUID, actor_id: uuid.UUID) -> dict[str, Any]:
    payload = card.payload
    days = [d for d in payload["plan"]["days"] if not d.get("removed")]
    for d in days:
        # what the AI could not read cleanly must be looked at: a flagged
        # day is confirmed only after the coach edited it; a date and a
        # men / women split are re-checked regardless
        blocking = day_blocking_problems(d) + ([] if d.get("edited") else d.get("problems") or [])
        if blocking:
            label = d.get("date") or d.get("date_hint") or "某一天"
            raise ValueError(f"{label}：{blocking[0]}（請修改或刪除這一天）")
    athletes = [a for a in payload["athletes"] if a.get("selected")]
    if not athletes or not days:
        raise ValueError("沒有選擇任何選手或課表")
    batch_id = conn.execute(text(
        "INSERT INTO assignment_batches (team_id, created_by, card_id) VALUES (:t, :u, :c) RETURNING id"),
        {"t": team_id, "u": actor_id, "c": card.id}).scalar_one()
    created, skipped = 0, []
    scheduled_dates: set[str] = set()
    for day in days:
        d = date.fromisoformat(day["date"])
        for ath in athletes:
            aid = uuid.UUID(ath["id"])
            eligible = conn.execute(text("SELECT 1 FROM team_memberships WHERE team_id=:t AND user_id=:a "
                                         "AND role='athlete' AND status='ACTIVE'"), {"t": team_id, "a": aid}).first()
            if eligible is None:
                continue
            if _day_completed(conn, aid, d):
                skipped.append(f"{ath['name']} {d.month}/{d.day}")
                continue
            # overwrite: everything already scheduled that day that was not done
            conn.execute(text("DELETE FROM assigned_workouts WHERE athlete_id=:a AND local_date=:d AND team_id=:t"),
                         {"a": aid, "d": d, "t": team_id})
            for item in day["items"]:
                record = assignment_record(item, ath.get("sex"))
                if record is None:
                    continue
                conn.execute(text(
                    """INSERT INTO assigned_workouts (team_id, athlete_id, local_date, title, duration_minutes,
                         intensity_label, structure, batch_id, tracked, notes)
                       VALUES (:t, :a, :d, :title, :m, :l, CAST(:s AS json), :b, :tracked, :n)"""),
                    {"t": team_id, "a": aid, "d": d, "title": record["title"], "m": record["duration_minutes"],
                     "l": record["intensity_label"], "s": json.dumps(record["structure"], ensure_ascii=False),
                     "b": batch_id, "tracked": record["tracked"], "n": record["notes"]})
                created += 1
            scheduled_dates.add(day["date"])
    summary = {"dates": sorted(scheduled_dates), "athletes": [a["name"] for a in athletes],
               "created": created, "skipped": skipped}
    conn.execute(text("UPDATE assignment_batches SET summary=CAST(:s AS jsonb) WHERE id=:id"),
                 {"s": json.dumps(summary, ensure_ascii=False), "id": batch_id})
    conn.execute(text("UPDATE chat_cards SET status='confirmed', resolved_at=now() WHERE id=:id"), {"id": card.id})
    dates = summary["dates"]
    span = f"{_md(dates[0])}–{_md(dates[-1])} " if dates else ""
    body = f"已排入 {span}課表（{len(dates)} 天，{len(athletes)} 位選手）"
    if skipped:
        body += f"；已完成、未覆蓋：{'、'.join(skipped)}"
    post_message(conn, card.room_id, "system", body, payload={"batch_id": str(batch_id), "kind": "plan_scheduled"})
    return {"batch_id": str(batch_id), **summary}


def revoke_batch(conn: Connection, batch: Any, room_id: uuid.UUID) -> dict[str, Any]:
    rows = conn.execute(text("SELECT id, athlete_id, local_date, tracked FROM assigned_workouts WHERE batch_id=:b"),
                        {"b": batch.id}).all()
    kept, removed = [], 0
    for r in rows:
        if r.tracked and _day_completed(conn, r.athlete_id, r.local_date):
            kept.append(r)
            continue
        conn.execute(text("DELETE FROM assigned_workouts WHERE id=:id"), {"id": r.id})
        removed += 1
    conn.execute(text("UPDATE assignment_batches SET revoked_at=now() WHERE id=:id"), {"id": batch.id})
    conn.execute(text("UPDATE chat_messages SET payload = payload || '{\"revoked\": true}'::jsonb "
                      "WHERE payload->>'batch_id' = :b"), {"b": str(batch.id)})
    body = f"已撤銷這次排入的課表（{removed} 筆）"
    if kept:
        body += f"，保留已完成的 {len(kept)} 筆"
    post_message(conn, room_id, "system", body, payload={"kind": "plan_revoked", "batch_id": str(batch.id)})
    return {"removed": removed, "kept": len(kept)}
