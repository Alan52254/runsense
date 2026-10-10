"""Schedule Draft: one suggested week for one Athlete, for their Coach to
review (ADR 0004 -- one publish path for dynamic schedules).

Every place in RunSense that can suggest a workout feeds facts into ONE
Planning Snapshot, and the week is decided from it in one place:

  training load       the athlete's acute / chronic load
  injury              Injury Reports (self-reported, or confirmed in chat)
  weather             morning / evening temperature estimate per day and the
                      pace cost of the heat (app/weather_pace.py); a climate
                      estimate for future days, never labelled a forecast
  health coach        what the Athlete told the AI 健康教練 for a day
                      (available time, a niggle) -- the facts, not its pick
  workout analysis    the advice from the latest analysed session
  coach assignments   what the Coach already scheduled -- kept by default
  completed days      locked, never touched

The workout for a day always comes from the reviewed engine (ADR 0002): the
day's facts go through resolve_scenario / evaluate_scenario, and only its
ranked, bounded candidates are used. No language model sets a number here.

The result is not a schedule. It becomes a plan card that only the Coach
sees in their one-to-one room with the Athlete; the Coach edits it day by
day and confirms it through the existing confirm_plan, which is the one path
that writes Assigned Workouts. Nothing reaches the Athlete before that.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, text

from app.climate_normals import get_climate_normal
from app.diurnal_temperature import estimate_temperature_at_hour
from app.plan_scenario import AthleteFacts, ScenarioOverride, evaluate_scenario, resolve_scenario
from app.training_plan_candidates import INTENSITY_ORDINAL, WorkoutType
from app.weather_pace import speed_loss_pct_relative_to_normal

HORIZON_DAYS = 7
DRAFT_KIND = "schedule_draft"

# an Injury Report keeps shaping the plan for this many days after the day
# it was reported for, unless a newer report says otherwise
INJURY_CARRY_DAYS = 3
# the latest analysed session is only relevant this long
ANALYSIS_LOOKBACK_DAYS = 21

# coach-assigned sessions that count as a hard day for spacing
HARD_INTENSITIES = {"間歇", "節奏跑", "比賽", "長距離"}

_WINDOWS = (("morning", "早上", 6.0), ("midday", "中午", 12.0), ("evening", "傍晚", 18.5))
_REFERENCE_RUN_HOUR = 18.5  # routes/weather.py: paces assume an early-evening run
_FALLBACK_SUNRISE, _FALLBACK_SUNSET = 6.0, 18.0

_TYPE_LABEL = {
    "REST_AND_SEEK_CARE": "休息並尋求評估",
    "REST_DAY": "休息日",
    "RECOVERY_RUN": "恢復跑",
    "EASY_RUN": "輕鬆跑",
    "STEADY_RUN": "穩定跑",
}
_PLAN_KIND = {"RECOVERY_RUN": "recovery", "EASY_RUN": "easy", "STEADY_RUN": "steady"}
_SEVERITY_LABEL = {"MILD": "輕微", "MODERATE": "中等", "SEVERE": "嚴重"}
_WEEKDAY = "一二三四五六日"


# ---------------------------------------------------------------- snapshot


@dataclass(frozen=True)
class DayWeather:
    """Morning / midday / evening estimate for one day."""

    source: str  # "live" (today, anchored on a recent reading) | "climate"
    windows: tuple[tuple[str, str, int, float, float], ...]  # (key, label, hour, °C, speed loss %)
    reference_c: float

    def best(self) -> tuple[str, str, int, float, float]:
        """The cooler of morning and evening -- midday is never suggested."""
        return min((w for w in self.windows if w[0] != "midday"), key=lambda w: w[4])


@dataclass(frozen=True)
class InjuryFact:
    reported_on: date
    severity_band: str
    body_part: str | None


@dataclass(frozen=True)
class AthleteStatement:
    """What the Athlete told the health coach about one day."""

    local_date: date
    available_minutes: int | None
    severity_band: str | None
    body_part: str | None
    label: str | None


@dataclass(frozen=True)
class Assignment:
    local_date: date
    title: str
    intensity_label: str | None
    duration_minutes: int | None


@dataclass(frozen=True)
class AnalysisAdvice:
    local_date: date
    signature: str | None
    advice: tuple[str, ...]


@dataclass(frozen=True)
class PlanningSnapshot:
    athlete_id: str
    start: date
    days: int
    sex: str | None
    city: str | None
    acute_load: float | None
    chronic_load: float | None
    observation_days: int
    weather: dict[date, DayWeather]
    injuries: tuple[InjuryFact, ...]
    statements: dict[date, AthleteStatement]
    assignments: dict[date, tuple[Assignment, ...]]
    completed: frozenset[date]
    analysis: AnalysisAdvice | None = None
    captured_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def dates(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range(self.days)]


def day_weather(city: str | None, sex: str | None, day: date, *, today: date | None = None,
                live_c: float | None = None, live_hour: float | None = None) -> DayWeather | None:
    """Estimate morning / midday / evening for `day` from the city's climate
    normal (app/diurnal_temperature.py). For today, a recent live reading
    shifts the whole curve by how far off-normal right now is."""
    if not city:
        return None
    normal = get_climate_normal(city, day.month)
    if normal is None:
        return None
    reference_c = estimate_temperature_at_hour(_REFERENCE_RUN_HOUR, _FALLBACK_SUNRISE, _FALLBACK_SUNSET,
                                               normal.low_c, normal.high_c)
    anomaly, source = 0.0, "climate"
    if day == today and live_c is not None and live_hour is not None:
        now_normal = estimate_temperature_at_hour(live_hour % 24, _FALLBACK_SUNRISE, _FALLBACK_SUNSET,
                                                  normal.low_c, normal.high_c)
        anomaly, source = live_c - now_normal, "live"
    windows = []
    for key, label, hour in _WINDOWS:
        t = estimate_temperature_at_hour(hour, _FALLBACK_SUNRISE, _FALLBACK_SUNSET,
                                         normal.low_c, normal.high_c) + anomaly
        loss = speed_loss_pct_relative_to_normal(t, reference_c, sex)
        windows.append((key, label, int(hour), round(t, 1), round(loss, 1)))
    return DayWeather(source, tuple(windows), round(reference_c, 1))


# ---------------------------------------------------------------- the week


def _injury_for(day: date, injuries: tuple[InjuryFact, ...]) -> InjuryFact | None:
    """The latest report on or before `day`, while it still applies."""
    applicable = [i for i in injuries if i.reported_on <= day]
    if not applicable:
        return None
    latest = max(applicable, key=lambda i: i.reported_on)
    if latest.severity_band in (None, "NONE") or (day - latest.reported_on).days > INJURY_CARRY_DAYS:
        return None
    return latest


def _is_hard(assignments: tuple[Assignment, ...]) -> bool:
    return any(a.intensity_label in HARD_INTENSITIES for a in assignments)


def describe(candidate: dict[str, Any]) -> str:
    label = _TYPE_LABEL.get(candidate["workout_type"], candidate["workout_type"])
    if not candidate.get("running_allowed") or not candidate.get("duration_minutes"):
        return label
    out = f"{label} {candidate['duration_minutes']} 分鐘"
    if candidate.get("distance_km"):
        out += f" · {candidate['distance_km']:g} km"
    return out


def _md(d: date) -> str:
    return f"{d.month}/{d.day}（{_WEEKDAY[d.weekday()]}）"


def plan_week(snap: PlanningSnapshot) -> list[dict[str, Any]]:
    """One entry per day: what is there now, what is proposed, and why.

    action:
      locked  -- already run; never touched
      keep    -- the Coach's assignment stands
      adjust  -- the Coach's assignment conflicts with a reported injury;
                 a gentler engine option is proposed for the Coach to decide
      add     -- nothing scheduled; the engine's option for the day
      rest    -- nothing scheduled and the engine's best option is rest
      open    -- nothing scheduled and the engine abstained (too little
                 recent training data to recommend anything): left to the
                 Coach, never shown as a rest recommendation
    """
    out: list[dict[str, Any]] = []
    prev_hard = False
    for d in snap.dates():
        current = snap.assignments.get(d, ())
        reasons: list[dict[str, str]] = []
        weather = snap.weather.get(d)
        injury = _injury_for(d, snap.injuries)
        statement = snap.statements.get(d)
        next_hard = _is_hard(snap.assignments.get(d + timedelta(days=1), ()))

        if d in snap.completed:
            out.append({"date": d.isoformat(), "label": _md(d), "action": "locked",
                        "current": [a.title for a in current], "proposed": None,
                        "reasons": [{"kind": "completed", "text": "這天已經跑過，不會變動"}]})
            prev_hard = _is_hard(current)
            continue

        # ---- the day's facts, exactly as the engine reads them
        best = weather.best() if weather else None
        facts = AthleteFacts(
            local_date=d,
            observation_days=snap.observation_days,
            acute_load=snap.acute_load,
            chronic_load=snap.chronic_load,
            temperature_c=best[3] if best else None,
            weather_state="CACHED" if best else "UNAVAILABLE",
            reported_body_part=injury.body_part if injury else None,
            reported_severity_band=injury.severity_band if injury else None,
            city=snap.city,
            sex=snap.sex,
            climate_reference_c=weather.reference_c if weather else None,
        )
        override = None
        if statement is not None:
            override = ScenarioOverride(
                available_minutes=statement.available_minutes,
                reported_body_part=statement.body_part,
                reported_severity_band=statement.severity_band,
                label=statement.label,
            )
        evaluation = evaluate_scenario(resolve_scenario(facts, override))
        ranked = [
            {"candidate_id": c.candidate_id, "workout_type": c.workout_type.value,
             "duration_minutes": c.duration_minutes, "distance_km": c.distance_km,
             "running_allowed": c.running_allowed, "intensity": INTENSITY_ORDINAL[c.workout_type]}
            for c in evaluation.ranked_candidates
        ]
        # ---- week rules: no hard day right after or right before another
        spaced = ranked
        if prev_hard or next_hard:
            easy_cap = INTENSITY_ORDINAL[WorkoutType.EASY_RUN]
            spaced = [c for c in ranked if c["intensity"] <= easy_cap] or ranked
            if spaced[0]["candidate_id"] != ranked[0]["candidate_id"]:
                reasons.append({"kind": "load", "text": "前一天或隔天是強度課，這天降為輕鬆強度"})
        pick = spaced[0]

        # ---- why
        if snap.acute_load is not None and snap.chronic_load:
            ratio = snap.acute_load / snap.chronic_load
            if ratio >= 1.3:
                reasons.append({"kind": "load", "text": f"近期負荷偏高（急性／慢性 {ratio:.2f}）"})
        if injury:
            part = f"{injury.body_part} " if injury.body_part else ""
            reasons.append({"kind": "injury", "text": f"{injury.reported_on.month}/{injury.reported_on.day} 回報"
                                                      f"{part}{_SEVERITY_LABEL.get(injury.severity_band, injury.severity_band)}不適"})
        if statement is not None:
            said = []
            if statement.available_minutes:
                said.append(f"只有 {statement.available_minutes} 分鐘")
            if statement.severity_band and statement.severity_band != "NONE":
                said.append(f"{statement.body_part or ''}{_SEVERITY_LABEL.get(statement.severity_band, '')}不適")
            if said:
                reasons.append({"kind": "health_coach", "text": "選手跟健康教練說這天" + "、".join(said)})
        weather_note = None
        if weather and best:
            prefix = "" if weather.source == "live" else "氣候估計 "
            weather_note = f"建議{best[1]} {best[2]:02d}:00 跑（{prefix}{best[3]:g}°C"
            if best[4] >= 1:
                weather_note += f"，配速約放慢 {best[4]:g}%"
            weather_note += "）"
            midday = next(w for w in weather.windows if w[0] == "midday")
            if midday[4] - best[4] >= 2:
                weather_note += f"；避開中午（{prefix}{midday[3]:g}°C）"
            reasons.append({"kind": "weather", "text": weather_note})

        hard_today = _is_hard(current)
        if current:
            restricted = injury is not None or (statement is not None and statement.severity_band not in (None, "NONE"))
            if restricted and hard_today:
                action = "adjust"
                runs = pick["running_allowed"] and pick["duration_minutes"] > 0
                reasons.insert(0, {"kind": "assigned", "text": f"教練原本排了「{current[0].title}」，有不適回報，"
                                   + ("建議改輕；由教練決定" if runs else
                                      "建議改為休息；請教練到課表撤銷這天")})
                prev_hard = False
            else:
                action = "keep"
                reasons.insert(0, {"kind": "assigned", "text": "教練已排課，保留"})
                pick = None
                prev_hard = hard_today
        elif evaluation.abstained:
            action = "open"
            pick = None
            reasons.insert(0, {"kind": "load", "text": "近 28 天的訓練紀錄不足，系統不推薦強度，這天留給教練決定"})
            prev_hard = False
        elif not pick["running_allowed"] or pick["duration_minutes"] == 0:
            action = "rest"
            prev_hard = False
        else:
            action = "add"
            prev_hard = pick["workout_type"] == WorkoutType.STEADY_RUN.value

        # the latest analysis' advice belongs to the next hard session
        if snap.analysis and hard_today and action in ("keep", "adjust") and not any(
                r["kind"] == "analysis" for o in out for r in o["reasons"]):
            when = f"{snap.analysis.local_date.month}/{snap.analysis.local_date.day}"
            sig = f" {snap.analysis.signature}" if snap.analysis.signature else ""
            for adv in snap.analysis.advice[:2]:
                reasons.append({"kind": "analysis", "text": f"上次{sig}（{when}）分析：{adv}"})

        out.append({"date": d.isoformat(), "label": _md(d), "action": action,
                    "current": [a.title for a in current],
                    "proposed": pick, "proposed_text": describe(pick) if pick else None,
                    "weather_note": weather_note, "reasons": reasons,
                    "ranker_version": evaluation.ranker_version,
                    "shadow_top": evaluation.shadow_top_candidate_id})
    return out


# ---------------------------------------------------------------- plan card


def card_payload(snap: PlanningSnapshot, week: list[dict[str, Any]], athlete: dict[str, Any],
                 *, version: int, today: date) -> dict[str, Any]:
    """The plan card the Coach reviews: proposed days only, in the shape
    app/chat_plan produces, so editing / preview / confirm are the existing
    ones. The full week, with every reason, rides along for the Coach."""
    days = []
    for i, day in enumerate(week):
        pick = day["proposed"]
        if day["action"] not in ("add", "adjust") or not pick["running_allowed"] or not pick["duration_minutes"]:
            continue
        minutes = pick["duration_minutes"]
        km = pick["distance_km"] or 0
        block = {"reps": 1, "distance_m": round(km * 1000) if km else None, "duration_s": int(minutes * 60),
                 "target_s_per_km": None, "target_text": None, "target_mode": "exact",
                 "rest_s": None, "rest_after_s": None}
        notes = "；".join(r["text"] for r in day["reasons"] if r["kind"] != "assigned") or None
        days.append({
            "key": f"d{i}", "date": day["date"], "date_hint": None,
            "source": "\n".join(r["text"] for r in day["reasons"]) or day["proposed_text"],
            "items": [{"type": "run", "kind": _PLAN_KIND.get(pick["workout_type"], "easy"),
                       "title": day["proposed_text"], "notes": notes, "variants": {"all": [block]}}],
            "problems": [], "removed": False, "edited": False,
        })
    start, end = snap.dates()[0], snap.dates()[-1]
    return {
        "plan": {"days": days, "unparsed": []},
        "athletes": [{**athlete, "selected": True}],
        "source_text": f"整合建議課表 {start.isoformat()}–{end.isoformat()}",
        "today": today.isoformat(),
        DRAFT_KIND: {
            "version": version,
            "horizon": [start.isoformat(), end.isoformat()],
            "captured_at": snap.captured_at,
            "inputs": {
                "training_load": snap.acute_load is not None,
                "injury": bool(snap.injuries),
                "weather": "live" if any(w.source == "live" for w in snap.weather.values())
                else ("climate" if snap.weather else None),
                "health_coach": bool(snap.statements),
                "analysis": snap.analysis is not None,
                "assignments": sum(len(v) for v in snap.assignments.values()),
            },
            "week": [{k: v for k, v in day.items() if k != "proposed"} for day in week],
        },
    }


# ---------------------------------------------------------------- database


def assemble_snapshot(tx: Connection, athlete_id: uuid.UUID, room_id: uuid.UUID, start: date,
                      days: int = HORIZON_DAYS) -> PlanningSnapshot:
    """Read every input once, as the Coach (RLS and the Athlete's Consent
    Scopes decide what is visible; what is not visible is simply absent)."""
    end = start + timedelta(days=days - 1)
    profile = tx.execute(text("SELECT timezone, city, sex FROM athlete_profiles WHERE user_id = :a"),
                         {"a": athlete_id}).first()
    city = profile.city if profile else None
    sex = profile.sex if profile else None
    tz = ZoneInfo(profile.timezone) if profile and profile.timezone else UTC

    load = tx.execute(text(
        "SELECT acute_load, chronic_load, observation_days FROM training_load_daily "
        "WHERE athlete_id = :a AND unit = 'AU' AND date <= :d ORDER BY date DESC LIMIT 1"),
        {"a": athlete_id, "d": start}).first()

    now_local = datetime.now(UTC).astimezone(tz)
    live = tx.execute(text("SELECT temperature_c, fetched_at FROM weather_cache WHERE city = :c "
                           "ORDER BY fetched_at DESC LIMIT 1"), {"c": city}).first() if city else None
    live_c = live_hour = None
    if live is not None and live.temperature_c is not None:
        fetched = live.fetched_at if live.fetched_at.tzinfo else live.fetched_at.replace(tzinfo=UTC)
        if datetime.now(UTC) - fetched < timedelta(hours=3):
            local = fetched.astimezone(tz)
            live_c, live_hour = float(live.temperature_c), local.hour + local.minute / 60
    weather = {}
    for i in range(days):
        d = start + timedelta(days=i)
        w = day_weather(city, sex, d, today=now_local.date(), live_c=live_c, live_hour=live_hour)
        if w is not None:
            weather[d] = w

    injuries = tuple(
        InjuryFact(r.local_training_date, r.severity_band, r.body_part)
        for r in tx.execute(text(
            "SELECT DISTINCT ON (local_training_date) local_training_date, severity_band, body_part "
            "FROM injury_reports WHERE athlete_id = :a AND local_training_date BETWEEN :lo AND :hi "
            "ORDER BY local_training_date, reported_at DESC"),
            {"a": athlete_id, "lo": start - timedelta(days=INJURY_CARRY_DAYS), "hi": end}))

    statements: dict[date, AthleteStatement] = {}
    # what the Athlete told the health coach: proposals they accepted for
    # themselves, and suggestions they sent to this Coach
    for r in tx.execute(text(
            "SELECT local_training_date AS d, label, scenario_override AS facts FROM coach_proposals "
            "WHERE athlete_id = :a AND accepted_at IS NOT NULL AND local_training_date BETWEEN :lo AND :hi "
            "ORDER BY accepted_at"), {"a": athlete_id, "lo": start, "hi": end}):
        statements[r.d] = _statement(r.d, r.facts or {}, r.label)
    for r in tx.execute(text(
            "SELECT payload FROM chat_messages WHERE room_id = :r AND retracted_at IS NULL "
            "AND payload->>'kind' = 'coach_suggestion' AND (payload->>'date')::date BETWEEN :lo AND :hi "
            "ORDER BY created_at"), {"r": room_id, "lo": start, "hi": end}):
        d = date.fromisoformat(r.payload["date"])
        statements[d] = _statement(d, r.payload.get("facts") or {}, r.payload.get("label"))

    assignments: dict[date, list[Assignment]] = {}
    for r in tx.execute(text(
            "SELECT local_date, title, intensity_label, duration_minutes FROM assigned_workouts "
            "WHERE athlete_id = :a AND local_date BETWEEN :lo AND :hi ORDER BY local_date, title"),
            {"a": athlete_id, "lo": start - timedelta(days=1), "hi": end + timedelta(days=1)}):
        assignments.setdefault(r.local_date, []).append(
            Assignment(r.local_date, r.title, r.intensity_label, r.duration_minutes))

    completed = frozenset(tx.execute(text(
        "SELECT DISTINCT local_training_date FROM completed_activities WHERE athlete_id = :a "
        "AND deleted_at IS NULL AND local_training_date BETWEEN :lo AND :hi"),
        {"a": athlete_id, "lo": start, "hi": end}).scalars())

    analysis = None
    row = tx.execute(text(
        "SELECT a.local_training_date AS d, w.signature, w.metrics->'findings' AS findings "
        "FROM workout_analyses w JOIN completed_activities a ON a.id = w.activity_id "
        "WHERE w.athlete_id = :a AND a.local_training_date BETWEEN :lo AND :hi "
        "ORDER BY a.local_training_date DESC, w.updated_at DESC LIMIT 1"),
        {"a": athlete_id, "lo": start - timedelta(days=ANALYSIS_LOOKBACK_DAYS), "hi": start}).first()
    if row is not None:
        order = {"critical": 0, "warning": 1, "info": 2, "positive": 3}
        findings = sorted((f for f in (row.findings or []) if f.get("advice")),
                          key=lambda f: order.get(f.get("severity"), 9))
        if findings:
            analysis = AnalysisAdvice(row.d, row.signature, tuple(f["advice"] for f in findings))

    return PlanningSnapshot(
        athlete_id=str(athlete_id), start=start, days=days, sex=sex, city=city,
        acute_load=float(load.acute_load) if load and load.acute_load is not None else None,
        chronic_load=float(load.chronic_load) if load and load.chronic_load is not None else None,
        observation_days=int(load.observation_days) if load else 0,
        weather=weather, injuries=injuries, statements=statements,
        assignments={k: tuple(v) for k, v in assignments.items()},
        completed=completed, analysis=analysis,
    )


def _statement(d: date, facts: dict[str, Any], label: str | None) -> AthleteStatement:
    minutes = facts.get("available_minutes")
    return AthleteStatement(d, int(minutes) if minutes else None, facts.get("reported_severity_band"),
                            facts.get("reported_body_part"), label)


_PENDING_DRAFTS = text(
    "SELECT id, payload FROM chat_cards WHERE room_id = :r AND owner_id = :o AND kind = 'plan' "
    "AND payload ? 'schedule_draft'")


def next_version(tx: Connection, room_id: uuid.UUID, owner_id: uuid.UUID) -> int:
    return 1 + max((r.payload[DRAFT_KIND].get("version", 0)
                    for r in tx.execute(_PENDING_DRAFTS, {"r": room_id, "o": owner_id})), default=0)


def supersede_open_drafts(tx: Connection, room_id: uuid.UUID, owner_id: uuid.UUID) -> int:
    """A newer draft replaces the one under review; the old card stays in
    the record as dismissed rather than being edited."""
    return tx.execute(text(
        "UPDATE chat_cards SET status = 'dismissed', resolved_at = now() WHERE room_id = :r AND owner_id = :o "
        "AND kind = 'plan' AND status = 'pending' AND payload ? 'schedule_draft'"),
        {"r": room_id, "o": owner_id}).rowcount


def to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)
