"""Team chat: one room per team, one direct room per (team, athlete), the
@AI helper's confirmation cards, and revoking a scheduled plan.

GET  /chat/rooms                          my rooms (created on first use) with unread counts
GET  /chat/rooms/{id}/messages            the latest 300 messages (+ my cards in the room)
POST /chat/rooms/{id}/messages            send (an @AI is processed in the background)
POST /chat/rooms/{id}/read                mark read
POST /chat/messages/{id}/retract          retract my own message (its pending cards go too)
PUT  /chat/cards/{id}                     edit my pending card
POST /chat/cards/{id}/confirm-plan        coach: schedule the plan (needs the coach view's MFA)
POST /chat/cards/{id}/confirm-report      athlete: file the body-status report
POST /chat/cards/{id}/dismiss             discard my card
POST /chat/batches/{id}/revoke            coach: revoke a scheduled plan (done days are kept)

Membership is checked on every call (the RLS policies in migration 0024
are the second line). A card is only ever returned to its owner.
"""

from __future__ import annotations

import json
import uuid
import datetime as dt
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, text

from app import chat_service, coach_handoff
from app.chat_plan import _pace_text
from app.db import actor_transaction, get_connection, get_engine
from app.errors import AuthorizationError
from app.providers import CurrentActorProvider
from app.routes.activities import get_current_actor_provider
from app.routes.settings import require_demo_mfa

router = APIRouter(tags=["chat"])


# ---------------------------------------------------------------- schemas


class SendMessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=4000)


class PlanBlockEdit(BaseModel):
    model_config = ConfigDict(extra="ignore")
    reps: int = Field(ge=1, le=60)
    distance_m: float | None = Field(default=None, ge=50, le=50000)
    duration_s: float | None = Field(default=None, ge=5, le=14400)
    target_s_per_km: float | None = Field(default=None, ge=120, le=900)
    target_mode: Literal["exact", "max"] = "exact"
    target_text: str | None = None
    rest_s: float | None = Field(default=None, ge=0, le=3600)
    rest_after_s: float | None = Field(default=None, ge=0, le=7200)


class PlanItemEdit(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["run", "strength", "core"]
    title: str = Field(max_length=200)
    kind: str | None = None
    content: str | None = Field(default=None, max_length=2000)
    variants: dict[Literal["all", "male", "female"], list[PlanBlockEdit]] | None = None


class PlanDayEdit(BaseModel):
    model_config = ConfigDict(extra="ignore")
    key: str
    date: dt.date | None = None
    removed: bool = False
    items: list[PlanItemEdit]


class PlanAthleteEdit(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: uuid.UUID
    selected: bool


class EditCardRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: list[PlanDayEdit] | None = None
    athletes: list[PlanAthleteEdit] | None = None
    body_part: str | None = Field(default=None, max_length=80)
    severity_band: Literal["NONE", "MILD", "MODERATE", "SEVERE"] | None = None
    description: str | None = Field(default=None, max_length=1000)
    red_flags: dict[str, bool] | None = None


# ---------------------------------------------------------------- rooms


def _ensure_rooms(tx: Connection, actor_id: uuid.UUID) -> None:
    teams = tx.execute(text("SELECT team_id, role FROM team_memberships WHERE user_id=:u AND status='ACTIVE'"),
                       {"u": actor_id}).all()
    for t in teams:
        chat_service.ensure_room(tx, t.team_id)
        athletes = tx.execute(text("SELECT user_id FROM team_memberships WHERE team_id=:t AND role='athlete' "
                                   "AND status='ACTIVE' AND (:coach OR user_id=:u)"),
                              {"t": t.team_id, "coach": chat_service.is_coach(t.role), "u": actor_id}).scalars().all()
        for a in athletes:
            chat_service.ensure_room(tx, t.team_id, a)


def _room_for(tx: Connection, room_id: uuid.UUID, actor_id: uuid.UUID) -> Any:
    room = tx.execute(text(
        """SELECT r.*, tm.role AS my_role FROM chat_rooms r
             JOIN team_memberships tm ON tm.team_id = r.team_id AND tm.user_id = :u AND tm.status = 'ACTIVE'
            WHERE r.id = :id AND (r.kind = 'team' OR r.athlete_id = :u
                                  OR tm.role IN ('coach', 'head_coach', 'owner'))"""),
        {"id": room_id, "u": actor_id}).first()
    if room is None:
        raise HTTPException(status_code=404, detail={"error": "CHAT_ROOM_NOT_FOUND"})
    return room


@router.get("/chat/rooms")
def list_rooms(conn: Connection = Depends(get_connection),
               actor_provider: CurrentActorProvider = Depends(get_current_actor_provider)) -> dict[str, Any]:
    actor = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor) as tx:
        me = uuid.UUID(actor)
        _ensure_rooms(tx, me)
        rows = tx.execute(text(
            f"""SELECT r.id, r.kind, r.team_id, r.athlete_id, t.name AS team_name, tm.role AS my_role,
                      au.display_name AS athlete_name,
                      (SELECT u.display_name FROM team_memberships c JOIN users u ON u.id = c.user_id
                        WHERE c.team_id = r.team_id AND c.status='ACTIVE' AND c.role IN ('head_coach','coach','owner')
                        ORDER BY c.role = 'head_coach' DESC LIMIT 1) AS coach_name,
                      (SELECT count(*) FROM chat_messages m
                        WHERE m.room_id = r.id AND {_VISIBLE} AND m.sender_id IS DISTINCT FROM :u
                          AND m.created_at > COALESCE((SELECT last_read_at FROM chat_reads cr
                                                        WHERE cr.room_id = r.id AND cr.user_id = :u),
                                                       '-infinity'::timestamptz)) AS unread,
                      (SELECT row_to_json(x) FROM (SELECT m.body, m.created_at, m.sender_kind, m.retracted_at
                                                      FROM chat_messages m WHERE m.room_id = r.id AND {_VISIBLE}
                                                     ORDER BY m.created_at DESC LIMIT 1) x) AS last
                 FROM chat_rooms r
                 JOIN teams t ON t.id = r.team_id
                 JOIN team_memberships tm ON tm.team_id = r.team_id AND tm.user_id = :u AND tm.status = 'ACTIVE'
                 LEFT JOIN users au ON au.id = r.athlete_id
                WHERE r.kind = 'team' OR r.athlete_id = :u OR tm.role IN ('coach', 'head_coach', 'owner')
                ORDER BY r.kind DESC, au.display_name"""),
            {"u": me}).all()
    rooms = []
    for r in rows:
        coach = chat_service.is_coach(r.my_role)
        title = (f"{r.team_name}（全隊）" if r.kind == "team"
                 else (f"{r.athlete_name}" if coach else f"{r.coach_name or '教練'}（一對一）"))
        last = r.last or {}
        rooms.append({"id": str(r.id), "kind": r.kind, "team_id": str(r.team_id), "title": title,
                      "athlete_id": str(r.athlete_id) if r.athlete_id else None, "my_role": r.my_role,
                      "unread": int(r.unread or 0),
                      "last_message": None if not last else (last.get("body") or "")[:60],
                      "last_at": last.get("created_at")})
    return {"rooms": rooms, "unread_total": sum(r["unread"] for r in rooms)}


# A retracted message leaves no trace: it is not listed, not counted as
# unread, not shown as a room's last message -- and neither is the AI's
# reply to it.
_VISIBLE = """m.retracted_at IS NULL
  AND NOT (m.sender_kind = 'ai' AND EXISTS (
        SELECT 1 FROM chat_messages s
         WHERE s.id::text = m.payload->>'reply_to' AND s.retracted_at IS NOT NULL))"""


def _message_dict(m: Any, me: uuid.UUID) -> dict[str, Any]:
    retracted = m.retracted_at is not None
    return {"id": str(m.id), "sender_kind": m.sender_kind, "sender_id": str(m.sender_id) if m.sender_id else None,
            "sender_name": "RunSense助手" if m.sender_kind == "ai" else ("系統" if m.sender_kind == "system"
                                                                    else (m.display_name or "成員")),
            "sender_is_coach": chat_service.is_coach(m.role), "mine": m.sender_id == me,
            "body": "" if retracted else m.body, "retracted": retracted, "mentions_ai": m.mentions_ai,
            "ai_state": m.ai_state, "payload": {} if retracted else (m.payload or {}),
            "created_at": m.created_at.isoformat()}


def _card_dict(tx: Connection, c: Any) -> dict[str, Any]:
    out = {"id": str(c.id), "kind": c.kind, "status": c.status, "source_message_id": str(c.source_message_id),
           "payload": c.payload, "created_at": c.created_at.isoformat()}
    if c.kind == "plan" and c.status == "pending":
        out["preview"] = chat_service.plan_preview(tx, c.payload)
    return out


@router.get("/chat/rooms/{room_id}/messages")
def list_messages(room_id: uuid.UUID,
                  conn: Connection = Depends(get_connection),
                  actor_provider: CurrentActorProvider = Depends(get_current_actor_provider)) -> dict[str, Any]:
    actor = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor) as tx:
        me = uuid.UUID(actor)
        room = _room_for(tx, room_id, me)
        rows = tx.execute(text(
            f"""SELECT m.*, u.display_name, tm.role FROM chat_messages m
                 LEFT JOIN users u ON u.id = m.sender_id
                 LEFT JOIN team_memberships tm ON tm.team_id = :t AND tm.user_id = m.sender_id
                WHERE m.room_id = :r AND {_VISIBLE} ORDER BY m.created_at DESC LIMIT 300"""),
            {"r": room_id, "t": room.team_id}).all()
        cards = tx.execute(text(
            """SELECT * FROM chat_cards WHERE room_id=:r AND owner_id=:u
                 AND (status='pending' OR (status='confirmed' AND resolved_at > now() - interval '1 day'))
               ORDER BY created_at"""),
            {"r": room_id, "u": me}).all()
        card_list = [_card_dict(tx, c) for c in cards]
        # where "unread" starts (the client jumps there, like LINE); reading
        # this list does not move it -- POST .../read does
        last_read = tx.execute(text("SELECT last_read_at FROM chat_reads WHERE room_id=:r AND user_id=:u"),
                               {"r": room_id, "u": me}).scalar()
    messages = [_message_dict(m, me) for m in reversed(rows)]
    return {"room_id": str(room_id), "messages": messages, "cards": card_list,
            "last_read_at": last_read.isoformat() if last_read else None,
            "my_role": room.my_role, "is_coach": chat_service.is_coach(room.my_role)}


@router.post("/chat/rooms/{room_id}/messages", status_code=201)
def send_message(room_id: uuid.UUID, payload: SendMessageRequest, background: BackgroundTasks,
                 conn: Connection = Depends(get_connection),
                 actor_provider: CurrentActorProvider = Depends(get_current_actor_provider)) -> dict[str, Any]:
    actor = actor_provider.get_current_actor_id()
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail={"error": "EMPTY_MESSAGE"})
    mentions = bool(chat_service.AI_MENTION.search(body))
    with actor_transaction(conn, actor) as tx:
        me = uuid.UUID(actor)
        _room_for(tx, room_id, me)
        message_id = tx.execute(text(
            """INSERT INTO chat_messages (room_id, sender_kind, sender_id, body, mentions_ai, ai_state)
               VALUES (:r, 'user', :u, :b, :m, :s) RETURNING id"""),
            {"r": room_id, "u": me, "b": body, "m": mentions, "s": "pending" if mentions else None}).scalar_one()
        tx.execute(text("""INSERT INTO chat_reads (room_id, user_id, last_read_at) VALUES (:r, :u, now())
                           ON CONFLICT (room_id, user_id) DO UPDATE SET last_read_at = now()"""),
                   {"r": room_id, "u": me})
    if mentions:
        background.add_task(chat_service.process_ai_message, get_engine(), message_id)
    return {"id": str(message_id), "ai_pending": mentions}


@router.post("/chat/rooms/{room_id}/read", status_code=204)
def mark_read(room_id: uuid.UUID, conn: Connection = Depends(get_connection),
              actor_provider: CurrentActorProvider = Depends(get_current_actor_provider)) -> None:
    actor = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor) as tx:
        me = uuid.UUID(actor)
        _room_for(tx, room_id, me)
        tx.execute(text("""INSERT INTO chat_reads (room_id, user_id, last_read_at) VALUES (:r, :u, now())
                           ON CONFLICT (room_id, user_id) DO UPDATE SET last_read_at = now()"""),
                   {"r": room_id, "u": me})


@router.post("/chat/messages/{message_id}/retract", status_code=204)
def retract_message(message_id: uuid.UUID, conn: Connection = Depends(get_connection),
                    actor_provider: CurrentActorProvider = Depends(get_current_actor_provider)) -> None:
    actor = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor) as tx:
        me = uuid.UUID(actor)
        msg = tx.execute(text("SELECT * FROM chat_messages WHERE id=:id"), {"id": message_id}).first()
        if msg is None:
            raise HTTPException(status_code=404, detail={"error": "MESSAGE_NOT_FOUND"})
        _room_for(tx, msg.room_id, me)
        if msg.sender_id != me:
            raise AuthorizationError("only the sender can retract a message")
        tx.execute(text("UPDATE chat_messages SET retracted_at = now() WHERE id=:id AND retracted_at IS NULL"),
                   {"id": message_id})
        # a card prepared from this message and not yet confirmed goes with it
        tx.execute(text("UPDATE chat_cards SET status='cancelled', resolved_at=now() "
                        "WHERE source_message_id=:id AND status='pending'"), {"id": message_id})


# ---------------------------------------------------------------- cards


def _my_pending_card(tx: Connection, card_id: uuid.UUID, me: uuid.UUID, kind: str | None = None) -> Any:
    card = tx.execute(text("SELECT * FROM chat_cards WHERE id=:id AND owner_id=:u"), {"id": card_id, "u": me}).first()
    if card is None or (kind and card.kind != kind):
        raise HTTPException(status_code=404, detail={"error": "CARD_NOT_FOUND"})
    if card.status != "pending":
        raise HTTPException(status_code=409, detail={"error": "CARD_NOT_PENDING"})
    return card


def _apply_plan_edit(payload: dict[str, Any], edit: EditCardRequest) -> dict[str, Any]:
    if edit.days is not None:
        by_key = {d.key: d for d in edit.days}
        for day in payload["plan"]["days"]:
            e = by_key.get(day["key"])
            if e is None:
                continue
            day["date"] = e.date.isoformat() if e.date else None
            day["removed"] = e.removed
            day["edited"] = True
            items = []
            for it in e.items:
                if it.type == "run":
                    variants = {}
                    for k, blocks in (it.variants or {}).items():
                        vb = []
                        for b in blocks:
                            bd = b.model_dump()
                            if bd["target_s_per_km"]:
                                within = "內" if bd["target_mode"] == "max" else ""
                                d_m = bd.get("distance_m")
                                bd["target_text"] = (f"{bd['target_s_per_km'] * d_m / 1000:.0f} 秒{within}"
                                                     if d_m and d_m <= 600 else
                                                     f"{_pace_text(bd['target_s_per_km']).replace(' /km', '/km')}{within}")
                            else:
                                bd["target_text"] = None
                            vb.append(bd)
                        if vb:
                            variants[k] = vb
                    items.append({"type": "run", "kind": it.kind or "other", "title": it.title, "variants": variants})
                else:
                    items.append({"type": it.type, "title": it.title, "content": it.content or ""})
            day["items"] = items
    if edit.athletes is not None:
        chosen = {str(a.id): a.selected for a in edit.athletes}
        for a in payload["athletes"]:
            if a["id"] in chosen:
                a["selected"] = chosen[a["id"]]
    return payload


@router.put("/chat/cards/{card_id}")
def edit_card(card_id: uuid.UUID, edit: EditCardRequest, conn: Connection = Depends(get_connection),
              actor_provider: CurrentActorProvider = Depends(get_current_actor_provider)) -> dict[str, Any]:
    actor = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor) as tx:
        me = uuid.UUID(actor)
        card = _my_pending_card(tx, card_id, me)
        payload = dict(card.payload)
        if card.kind == "plan":
            payload = _apply_plan_edit(payload, edit)
        else:
            if edit.body_part is not None:
                payload["body_part"] = edit.body_part.strip() or None
            if edit.severity_band is not None:
                payload["severity_band"] = edit.severity_band
            if edit.description is not None:
                payload["description"] = edit.description
            if edit.red_flags is not None:
                payload["red_flags"] = {k: bool(edit.red_flags.get(k, False)) for k in payload["red_flags"]}
            payload["triage"] = chat_service.triage_for(payload.get("severity_band"), payload.get("body_part"),
                                                        payload["red_flags"])
        tx.execute(text("UPDATE chat_cards SET payload = CAST(:p AS jsonb) WHERE id=:id"),
                   {"p": json.dumps(payload, ensure_ascii=False), "id": card_id})
        card = tx.execute(text("SELECT * FROM chat_cards WHERE id=:id"), {"id": card_id}).first()
        return _card_dict(tx, card)


@router.post("/chat/cards/{card_id}/confirm-plan", dependencies=[Depends(require_demo_mfa)])
def confirm_plan_card(card_id: uuid.UUID, conn: Connection = Depends(get_connection),
                      actor_provider: CurrentActorProvider = Depends(get_current_actor_provider)) -> dict[str, Any]:
    actor = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor) as tx:
        me = uuid.UUID(actor)
        card = _my_pending_card(tx, card_id, me, "plan")
        room = _room_for(tx, card.room_id, me)
        if not chat_service.is_coach(room.my_role):
            raise AuthorizationError("only a coach can schedule")
        # the message the card came from was retracted -- possibly by its
        # athlete, who cannot touch the coach's card -- so it goes with it
        retracted = tx.execute(text("SELECT retracted_at IS NOT NULL FROM chat_messages WHERE id=:m"),
                               {"m": card.source_message_id}).scalar()
        if retracted:
            tx.execute(text("UPDATE chat_cards SET status='cancelled', resolved_at=now() WHERE id=:id"),
                       {"id": card.id})
        else:
            try:
                result = chat_service.confirm_plan(tx, card, room.team_id, me)
                if card.payload.get("from_suggestion"):
                    coach_handoff.record_decision(tx, card.source_message_id,
                                                  coach_handoff.adopted_decision(card.payload),
                                                  batch_id=result["batch_id"], dates=result["dates"])
                return result
            except ValueError as exc:
                raise HTTPException(status_code=422,
                                    detail={"error": "PLAN_NOT_READY", "reason": str(exc)}) from exc
    raise HTTPException(status_code=409, detail={"error": "SOURCE_RETRACTED",
                                                 "reason": "原始訊息已收回，這張確認卡已取消"})


def _suggestion_for_coach(tx: Connection, message_id: uuid.UUID, me: uuid.UUID) -> tuple[Any, Any]:
    """An athlete's live Coach Suggestion in their one-to-one room, for that
    room's coach -- anyone else gets 403 / 404."""
    msg = tx.execute(text("SELECT * FROM chat_messages WHERE id=:id AND retracted_at IS NULL"),
                     {"id": message_id}).first()
    if msg is None or (msg.payload or {}).get("kind") != coach_handoff.SUGGESTION_KIND:
        raise HTTPException(status_code=404, detail={"error": "SUGGESTION_NOT_FOUND"})
    room = _room_for(tx, msg.room_id, me)
    if not chat_service.is_coach(room.my_role):
        raise AuthorizationError("only a coach can decide on a suggestion")
    if room.kind != "direct" or msg.sender_id != room.athlete_id:
        raise HTTPException(status_code=404, detail={"error": "SUGGESTION_NOT_FOUND"})
    return msg, room


class DeclineSuggestionRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=300)


@router.post("/chat/messages/{message_id}/decline-suggestion")
def decline_suggestion(message_id: uuid.UUID, decline: DeclineSuggestionRequest,
                       conn: Connection = Depends(get_connection),
                       actor_provider: CurrentActorProvider = Depends(get_current_actor_provider)) -> dict[str, Any]:
    """The coach turns a suggestion down, saying why; the athlete -- and the
    health coach, next time they talk -- hear the reason."""
    reason = decline.reason.strip()
    if not reason:
        raise HTTPException(status_code=422, detail={"error": "REASON_REQUIRED"})
    actor = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor) as tx:
        me = uuid.UUID(actor)
        msg, room = _suggestion_for_coach(tx, message_id, me)
        coach_handoff.record_decision(tx, msg.id, coach_handoff.DECLINED, reason=reason)
        tx.execute(text("UPDATE chat_cards SET status='cancelled', resolved_at=now() "
                        "WHERE source_message_id=:m AND status='pending'"), {"m": msg.id})
        chat_service.post_message(tx, room.id, "system", f"教練婉拒了這份建議：{reason}",
                                  payload={"kind": "suggestion_declined", "suggestion_id": str(msg.id)})
    return {"decision": coach_handoff.DECLINED, "reason": reason}


@router.post("/chat/messages/{message_id}/schedule-suggestion", status_code=201)
def schedule_suggestion(message_id: uuid.UUID, conn: Connection = Depends(get_connection),
                        actor_provider: CurrentActorProvider = Depends(get_current_actor_provider)) -> dict[str, Any]:
    """A coach turns an athlete's Coach Suggestion into a plan card of their
    own. Nothing is scheduled here: the card is confirmed like any plan."""
    actor = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor) as tx:
        me = uuid.UUID(actor)
        msg, room = _suggestion_for_coach(tx, message_id, me)
        existing = tx.execute(text("SELECT * FROM chat_cards WHERE source_message_id=:m AND owner_id=:u "
                                   "AND kind='plan' AND status='pending'"), {"m": message_id, "u": me}).first()
        if existing is not None:
            return _card_dict(tx, existing)
        athlete = tx.execute(text(
            """SELECT u.id, u.display_name, u.email, p.sex FROM users u
                 LEFT JOIN athlete_profiles p ON p.user_id = u.id WHERE u.id = :a"""),
            {"a": room.athlete_id}).first()
        try:
            payload = coach_handoff.plan_payload_from_suggestion(
                msg.payload,
                {"id": str(athlete.id), "name": athlete.display_name or athlete.email.split("@")[0],
                 "sex": athlete.sex},
                msg.body, chat_service.local_today(tx, me))
        except coach_handoff.SuggestionNotSchedulable as exc:
            raise HTTPException(status_code=422, detail={"error": "NOT_SCHEDULABLE", "reason": str(exc)}) from exc
        card_id = tx.execute(text(
            """INSERT INTO chat_cards (room_id, source_message_id, owner_id, kind, payload)
               VALUES (:r, :m, :o, 'plan', CAST(:p AS jsonb)) RETURNING id"""),
            {"r": msg.room_id, "m": message_id, "o": me, "p": json.dumps(payload, ensure_ascii=False)}).scalar_one()
        card = tx.execute(text("SELECT * FROM chat_cards WHERE id=:id"), {"id": card_id}).first()
        return _card_dict(tx, card)


@router.post("/chat/cards/{card_id}/confirm-report")
def confirm_report_card(card_id: uuid.UUID, conn: Connection = Depends(get_connection),
                        actor_provider: CurrentActorProvider = Depends(get_current_actor_provider)) -> dict[str, Any]:
    actor = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor) as tx:
        me = uuid.UUID(actor)
        card = _my_pending_card(tx, card_id, me, "body_report")
        p = card.payload
        if not p.get("severity_band"):
            raise HTTPException(status_code=422, detail={"error": "SEVERITY_REQUIRED", "reason": "請先選擇嚴重程度"})
        tz = tx.execute(text("SELECT timezone FROM athlete_profiles WHERE user_id=:u"), {"u": me}).scalar_one()
        now = chat_service.now_utc()
        report_id = tx.execute(text(
            """INSERT INTO injury_reports (athlete_id, client_mutation_id, request_fingerprint, has_issue,
                 severity_band, body_part, reported_at, timezone_snapshot, local_training_date)
               VALUES (:a, :c, :f, :h, :s, :b, :at, :tz, :d)
               ON CONFLICT (athlete_id, client_mutation_id) DO NOTHING RETURNING id"""),
            {"a": me, "c": card.id, "f": f"chat-card:{card.id}", "h": p["severity_band"] != "NONE",
             "s": p["severity_band"], "b": p.get("body_part"), "at": now, "tz": tz,
             "d": now.astimezone(ZoneInfo(tz)).date()}).scalar_one_or_none()
        if report_id is not None and p.get("description"):
            tx.execute(text("INSERT INTO injury_report_details (injury_report_id, free_text) VALUES (:r, :t)"),
                       {"r": report_id, "t": p["description"][:2000]})
        tx.execute(text("UPDATE chat_cards SET status='confirmed', resolved_at=now() WHERE id=:id"), {"id": card_id})
    return {"injury_report_id": str(report_id) if report_id else None, "triage": p.get("triage")}


@router.post("/chat/cards/{card_id}/dismiss", status_code=204)
def dismiss_card(card_id: uuid.UUID, conn: Connection = Depends(get_connection),
                 actor_provider: CurrentActorProvider = Depends(get_current_actor_provider)) -> None:
    actor = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor) as tx:
        _my_pending_card(tx, card_id, uuid.UUID(actor))
        tx.execute(text("UPDATE chat_cards SET status='dismissed', resolved_at=now() WHERE id=:id"), {"id": card_id})


@router.post("/chat/batches/{batch_id}/revoke", dependencies=[Depends(require_demo_mfa)])
def revoke_plan(batch_id: uuid.UUID, conn: Connection = Depends(get_connection),
                actor_provider: CurrentActorProvider = Depends(get_current_actor_provider)) -> dict[str, Any]:
    actor = actor_provider.get_current_actor_id()
    with actor_transaction(conn, actor) as tx:
        me = uuid.UUID(actor)
        batch = tx.execute(text("SELECT * FROM assignment_batches WHERE id=:id"), {"id": batch_id}).first()
        if batch is None:
            raise HTTPException(status_code=404, detail={"error": "BATCH_NOT_FOUND"})
        if not chat_service.is_coach(chat_service.member_role(tx, batch.team_id, me)):
            raise AuthorizationError("only a coach can revoke")
        if batch.revoked_at is not None:
            raise HTTPException(status_code=409, detail={"error": "ALREADY_REVOKED"})
        room_id = tx.execute(text("SELECT room_id FROM chat_cards WHERE id=:c"), {"c": batch.card_id}).scalar_one()
        return chat_service.revoke_batch(tx, batch, room_id)
