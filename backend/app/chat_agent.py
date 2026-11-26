"""ReAct Agent for RunSense 助手 (Observation -> Thought -> Action).

Connects the team/direct chat assistant to RunSense's live athlete status
(ACWR, recent activities, injury reports) and the XGBoost / deterministic
plan ranker (`TrainingPlanService`).

Safety and privacy invariants preserved:
- In `team` rooms, individual athlete telemetry/injuries are never disclosed.
- In `direct` rooms, a coach may only inspect an athlete who granted
  `training_load` consent.
- Coaches can receive a one-click confirmation `plan` card built from the
  ranker's top candidate; athletes receive read-only explanations and are
  pointed to their coach to schedule.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, timedelta
import json
import uuid
from typing import Any, Callable, Mapping, Sequence

from sqlalchemy import Connection, text

from app.plan_scenario import urgency_from_severity_band
from app.react_coach import AgentSecurityEnvelope
from app.training_plan_service import TrainingPlanService


@dataclass(frozen=True)
class ReactStep:
    step: int
    thought: str
    action: str
    observation: str


@dataclass(frozen=True)
class AgentOutcome:
    reply_text: str
    trace: tuple[ReactStep, ...]
    plan_card_payload: dict[str, Any] | None = None


def observe_athlete_status(
    conn: Connection,
    athlete_id: uuid.UUID,
    *,
    today: date,
) -> dict[str, Any]:
    """Read bounded athlete load, recency, and latest self-report."""
    load = conn.execute(
        text(
            "SELECT date, acute_load, chronic_load, load_ratio, observation_days "
            "FROM training_load_daily WHERE athlete_id = :a AND unit = 'AU' "
            "AND date <= :d ORDER BY date DESC LIMIT 1"
        ),
        {"a": athlete_id, "d": today},
    ).first()
    activity = conn.execute(
        text(
            "SELECT MAX(local_training_date) AS last_date, "
            "COUNT(*) FILTER (WHERE local_training_date >= :w) AS count_7d "
            "FROM completed_activities WHERE athlete_id = :a AND deleted_at IS NULL "
            "AND local_training_date <= :d"
        ),
        {"a": athlete_id, "d": today, "w": today - timedelta(days=6)},
    ).first()
    injury = conn.execute(
        text(
            "SELECT body_part, severity_band, has_issue, local_training_date "
            "FROM injury_reports WHERE athlete_id = :a AND local_training_date <= :d "
            "ORDER BY reported_at DESC LIMIT 1"
        ),
        {"a": athlete_id, "d": today},
    ).first()

    return {
        "has_load": load is not None,
        "load_date": load.date.isoformat() if load and load.date else None,
        "acute_load": round(float(load.acute_load), 1) if load and load.acute_load is not None else None,
        "chronic_load": round(float(load.chronic_load), 1) if load and load.chronic_load is not None else None,
        "load_ratio": round(float(load.load_ratio), 2) if load and load.load_ratio is not None else None,
        "observation_days": int(load.observation_days) if load and load.observation_days is not None else 0,
        "sessions_7d": int(activity.count_7d) if activity and activity.count_7d is not None else 0,
        "last_activity_date": activity.last_date.isoformat() if activity and activity.last_date else None,
        "latest_injury": (
            {
                "has_issue": bool(injury.has_issue),
                "body_part": injury.body_part,
                "severity_band": injury.severity_band,
                "date": injury.local_training_date.isoformat(),
            }
            if injury
            else None
        ),
    }


def recommend_workout_plan(conn: Connection, athlete_id: uuid.UUID) -> dict[str, Any]:
    """Run TrainingPlanService (deterministic + XGBoost shadow/ML ranker)."""
    return TrainingPlanService(conn).get_today(athlete_id)


def _format_status_observation(status: Mapping[str, Any]) -> str:
    if not status.get("has_load"):
        load_part = "尚無訓練負荷紀錄"
    else:
        ratio = status.get("load_ratio")
        ratio_txt = f"{ratio:.2f}" if ratio is not None else "資料不足"
        load_part = (
            f"7天負荷 {status.get('acute_load')} AU、28天基準 {status.get('chronic_load')} AU、"
            f"ACWR {ratio_txt}（觀測 {status.get('observation_days')} 天）"
        )
    sessions = status.get("sessions_7d", 0)
    inj = status.get("latest_injury")
    inj_part = (
        f"最新身體回報：{inj['body_part'] or '部位未填'}（{inj['severity_band']}）"
        if inj and inj.get("has_issue")
        else "近期無不適回報"
    )
    return f"{load_part}；近 7 天完成 {sessions} 次訓練；{inj_part}。"


def _format_plan_observation(plan: Mapping[str, Any]) -> str:
    candidates = plan.get("candidates") or []
    if not candidates:
        return "目前沒有可用的候選課表。"
    top = candidates[0]
    shadow = plan.get("shadow_evaluation") or {}
    shadow_top = shadow.get("top_candidate_id")
    shadow_ver = shadow.get("ranker_version")
    title = top.get("title") or top.get("workout_type")
    dur = top.get("duration_minutes", 0)
    dist = top.get("distance_km", 0)
    reasons = "；".join(top.get("rationale") or ()) or "依目前負荷與安全規則排序"
    shadow_note = (
        f"（XGBoost 影子模型建議：{shadow_top}，版本 {shadow_ver}）"
        if shadow_top and shadow_ver
        else ""
    )
    return f"首選課表：{title}（{dur} 分鐘 / {dist} km）。依據：{reasons}{shadow_note}"


_WORKOUT_KIND_MAP = {
    "RECOVERY_RUN": "recovery",
    "EASY_RUN": "easy",
    "STEADY_RUN": "steady",
}


def build_plan_card_from_recommendation(
    plan: Mapping[str, Any],
    athletes: Sequence[dict[str, Any]],
    *,
    today: date,
    source_text: str,
) -> dict[str, Any] | None:
    """Convert the ranker's top running candidate into a coach confirmation card."""
    candidates = plan.get("candidates") or []
    if not candidates:
        return None
    top = candidates[0]
    wtype = str(top.get("workout_type") or "")
    if not top.get("running_allowed") or wtype in {"REST_DAY", "REST_AND_SEEK_CARE"}:
        return None

    dur = int(top.get("duration_minutes") or 30)
    dist_km = float(top.get("distance_km") or 5.0)
    pace_s = top.get("target_pace_s_per_km")
    pace_txt = f"{int(pace_s // 60)}:{int(pace_s % 60):02d}/km" if pace_s else None
    kind = _WORKOUT_KIND_MAP.get(wtype, "easy")
    title = str(top.get("title") or "系統建議課表")
    reasons = "；".join(top.get("rationale") or ())

    day_entry = {
        "key": "day_1",
        "date": today.isoformat(),
        "date_hint": f"{today.month}/{today.day}",
        "removed": False,
        "edited": True,
        "problems": [],
        "notes": f"由 RunSense 助手結合課表排序建議產生：{reasons}" if reasons else None,
        "items": [
            {
                "type": "run",
                "title": title,
                "kind": kind,
                "variants": {
                    "all": [
                        {
                            "reps": 1,
                            "distance_m": round(dist_km * 1000) if dist_km > 0 else None,
                            "duration_s": dur * 60 if dist_km <= 0 else None,
                            "target_s_per_km": float(pace_s) if pace_s else None,
                            "target_mode": "exact",
                            "target_text": pace_txt,
                            "rest_s": None,
                            "rest_after_s": None,
                        }
                    ]
                },
            }
        ],
    }

    return {
        "plan": {"days": [day_entry]},
        "athletes": list(athletes),
        "source_text": source_text,
        "today": today.isoformat(),
        "agent_recommendation": {
            "ranker_version": plan.get("ranker_version"),
            "top_candidate_id": top.get("candidate_id"),
            "shadow_top_candidate_id": (plan.get("shadow_evaluation") or {}).get("top_candidate_id"),
        },
    }


def _choose_action_with_llm(
    llm_fn: Callable[[list[dict[str, str]]], str],
    question: str,
    role_label: str,
    history_trace: Sequence[ReactStep],
    available_tools: Sequence[str],
) -> tuple[str, str]:
    """Ask the LLM for the next Thought + Action, falling back cleanly."""
    trace_txt = "\n".join(
        f"Step {s.step} | Thought: {s.thought} | Action: {s.action} | Observation: {s.observation}"
        for s in history_trace
    ) or "（尚未執行任何工具）"
    prompt = (
        "你是 RunSense ReAct 助理，請決定下一步行動並只輸出 JSON："
        '{"thought": "<簡短推理>", "action": "<tool_or_finish>"}\n'
        f"可用 action：{', '.join(available_tools)}, finish\n"
        f"提問者身分：{role_label}\n"
        f"問題：{question}\n"
        f"目前軌跡：\n{trace_txt}"
    )
    try:
        raw = llm_fn([{"role": "user", "content": prompt}])
        parsed = json.loads(raw)
        thought = str(parsed.get("thought") or "").strip()
        action = str(parsed.get("action") or "").strip()
        if action in (*available_tools, "finish"):
            return thought or "根據現有資訊選擇下一步工具。", action
    except Exception:
        pass
    return "", ""


def run_react_agent(
    *,
    question: str,
    is_coach_user: bool,
    room_kind: str,
    athlete_id: uuid.UUID | None,
    has_consent: bool,
    today: date,
    observe_status_fn: Callable[[uuid.UUID], dict[str, Any]],
    recommend_plan_fn: Callable[[uuid.UUID], dict[str, Any]],
    athletes_for_card: Sequence[dict[str, Any]] = (),
    llm_fn: Callable[[list[dict[str, str]]], str] | None = None,
    max_steps: int = 3,
) -> AgentOutcome:
    """Execute a bounded ReAct loop (Observation -> Thought -> Action)."""
    if room_kind == "team" or athlete_id is None:
        where = "選手詳情頁" if is_coach_user else "與教練的一對一聊天室或 AI 健康教練"
        step = ReactStep(
            step=1,
            thought="目前在公開群組聊天室，為保護個人隱私，不可查詢或揭露個人負荷與課表建議。",
            action="privacy_guard",
            observation="已阻擋群組個人數據查詢。",
        )
        return AgentOutcome(
            reply_text=f"群組裡不公開任何人的負荷、傷痛或個人課表建議，請到{where}查看。",
            trace=(step,),
        )

    if is_coach_user and not has_consent:
        step = ReactStep(
            step=1,
            thought="教練查詢選手狀況與建議課表前，需先確認訓練負荷授權。",
            action="consent_check",
            observation="該選手尚未授權教練查看訓練負荷。",
        )
        return AgentOutcome(
            reply_text="這位選手尚未授權教練查看訓練負荷與個人建議。",
            trace=(step,),
        )

    envelope = AgentSecurityEnvelope.from_inputs(message=question)
    trace: list[ReactStep] = []
    status_data: dict[str, Any] | None = None
    plan_data: dict[str, Any] | None = None
    role_label = "教練" if is_coach_user else "選手"
    want_draft = is_coach_user and any(k in question for k in ("排", "推薦", "建議", "課表", "安排"))

    for idx in range(1, max_steps + 1):
        available = [
            t
            for t in ("observe_athlete_status", "recommend_workout_plan")
            if (t == "observe_athlete_status" and status_data is None)
            or (t == "recommend_workout_plan" and plan_data is None)
        ]
        if not available:
            break

        llm_thought, llm_action = (
            _choose_action_with_llm(llm_fn, question, role_label, trace, available)
            if llm_fn is not None
            else ("", "")
        )

        # Deterministic policy order if LLM is unavailable or skipped
        action = llm_action if llm_action in available else available[0]
        if action == "observe_athlete_status":
            thought = llm_thought or "先觀測選手最近的訓練負荷（ACWR）、近 7 天訓練頻率與身體回報狀況。"
            status_data = observe_status_fn(athlete_id)
            inj = status_data.get("latest_injury") if isinstance(status_data, Mapping) else None
            if isinstance(inj, Mapping) and inj.get("has_issue"):
                envelope = envelope.escalate(
                    urgency_from_severity_band(inj.get("severity_band")),
                    reason="OBSERVED_INJURY",
                )
            obs = _format_status_observation(status_data)
            trace.append(ReactStep(step=idx, thought=thought, action=action, observation=obs))
        elif action == "recommend_workout_plan":
            thought = llm_thought or "結合選手目前狀態，呼叫訓練課表排序器（含 XGBoost 評估）取得今日最佳課表。"
            plan_data = recommend_plan_fn(athlete_id)
            obs = _format_plan_observation(plan_data)
            trace.append(ReactStep(step=idx, thought=thought, action=action, observation=obs))
        else:
            break

    status_summary = _format_status_observation(status_data or {})
    plan_summary = _format_plan_observation(plan_data or {})

    card_payload: dict[str, Any] | None = None
    if envelope.running_allowed and want_draft and plan_data is not None and athletes_for_card:
        card_payload = build_plan_card_from_recommendation(
            plan_data,
            athletes_for_card,
            today=today,
            source_text=question,
        )

    lines = [
        f"【狀態觀測】{status_summary}",
        f"【課表建議】{plan_summary}",
    ]
    if card_payload is not None:
        lines.append("已依上述 XGBoost / 排序結果為教練整理好今日確認卡，確認無誤後即可一鍵排入課表。")
    elif not is_coach_user:
        lines.append("若希望由教練將此建議排入正式課表，請與教練在對話中確認。")

    return AgentOutcome(
        reply_text=envelope.enforce_on_reply("\n".join(lines)),
        trace=tuple(trace),
        plan_card_payload=card_payload,
    )


def serialize_trace(trace: Sequence[ReactStep]) -> list[dict[str, Any]]:
    return [asdict(step) for step in trace]
