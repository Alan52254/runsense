"""Schedule Draft: one suggested week for one Athlete, for their Coach to
review (ADR 0004 -- one publish path for dynamic schedules).

Every place in RunSense that can suggest a workout feeds facts into ONE
Planning Snapshot, and the week is decided from it in one place:

  training load       the athlete's acute / chronic load
  injury              Injury Reports (self-reported, or confirmed in chat)
  weather             morning / midday / evening per day from a real forecast
                      (app/weather_forecast.py), the climate estimate only
                      when there is none -- each labelled with its source --
                      and the pace cost of the heat (app/weather_pace.py)
  easy pace           the athlete's own easy pace (app/athlete_pace.py): a
                      suggested run carries a pace range from it, slowed for
                      heat; no baseline, no pace
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
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, text

from app import athlete_pace, weather_forecast
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
    """Morning / midday / evening for one day, and where it came from."""

    # "forecast" | "observation" (today, the curve anchored on a recent
    # reading) | "climate_estimate" (city normals; never called a forecast)
    source: str
    # key, label, hour, temperature C, speed loss %, humidity %, wind km/h
    windows: tuple[tuple[str, str, int, float, float, float | None, float | None], ...]
    reference_c: float
    valid_on: date
    provider: str | None = None
    fetched_at: str | None = None

    def prefix(self) -> str:
        return {"forecast": "預報 ", "observation": "", "climate_estimate": "氣候估計 "}[self.source]

    def as_dict(self) -> dict[str, Any]:
        return {"source": self.source, "provider": self.provider, "fetched_at": self.fetched_at,
                "reference_c": self.reference_c,
                "windows": [{"key": w[0], "hour": w[2],
                             "valid_at": f"{self.valid_on.isoformat()}T{w[2]:02d}:00:00",
                             "temperature_c": w[3], "speed_loss_pct": w[4],
                             "humidity_pct": w[5], "wind_kph": w[6]}
                            for w in self.windows]}

    def best(self) -> tuple[str, str, int, float, float, float | None, float | None]:
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
    structure: Any = None


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
    easy_pace_s_per_km: int | None = None
    # a draft for dates already past: built only from what was known before
    # its start date, reviewed but never published
    retrospective: bool = False
    captured_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def dates(self) -> list[date]:
        return [self.start + timedelta(days=i) for i in range(self.days)]


def day_weather(city: str | None, sex: str | None, day: date, *, today: date | None = None,
                live_c: float | None = None, live_hour: float | None = None,
                forecast: weather_forecast.HourlyForecast | None = None) -> DayWeather | None:
    """Morning / midday / evening for `day`: from the hourly forecast when it
    covers all three hours; otherwise the city's climate normal on a diurnal
    curve (app/diurnal_temperature.py), which for today a recent live
    reading shifts by how far off-normal right now is."""
    if not city:
        return None
    normal = get_climate_normal(city, day.month)
    if normal is None:
        return None
    reference_c = estimate_temperature_at_hour(_REFERENCE_RUN_HOUR, _FALLBACK_SUNRISE, _FALLBACK_SUNSET,
                                               normal.low_c, normal.high_c)
    if forecast is not None:
        readings = [forecast.at(day, int(hour)) for _, _, hour in _WINDOWS]
        if all(readings):
            windows = tuple(
                (key, label, int(hour), round(r[0], 1),
                 round(speed_loss_pct_relative_to_normal(r[0], reference_c, sex), 1), r[1], r[2])
                for (key, label, hour), r in zip(_WINDOWS, readings))
            return DayWeather("forecast", windows, round(reference_c, 1), day,
                              forecast.provider, forecast.fetched_at)
    anomaly, source = 0.0, "climate_estimate"
    if day == today and live_c is not None and live_hour is not None:
        now_normal = estimate_temperature_at_hour(live_hour % 24, _FALLBACK_SUNRISE, _FALLBACK_SUNSET,
                                                  normal.low_c, normal.high_c)
        anomaly, source = live_c - now_normal, "observation"
    windows = []
    for key, label, hour in _WINDOWS:
        t = estimate_temperature_at_hour(hour, _FALLBACK_SUNRISE, _FALLBACK_SUNSET,
                                         normal.low_c, normal.high_c) + anomaly
        loss = speed_loss_pct_relative_to_normal(t, reference_c, sex)
        windows.append((key, label, int(hour), round(t, 1), round(loss, 1), None, None))
    return DayWeather(source, tuple(windows), round(reference_c, 1), day)


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


def _pace(s_per_km: float | None) -> str:
    s = round(s_per_km or 0)
    return f"{s // 60}:{s % 60:02d}"


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
            prefix = weather.prefix()
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

        # ---- pace: the athlete's own easy pace, slowed for the day's heat
        if pick is not None and pick["running_allowed"] and pick["duration_minutes"]:
            loss = best[4] if best else None
            rng = athlete_pace.pace_range(pick["workout_type"], snap.easy_pace_s_per_km, loss)
            pick = {**pick, "pace_range": rng}
            if rng is None:
                reasons.append({"kind": "pace", "text": "個人輕鬆跑紀錄不足，無法估算目標配速"})
            else:
                base = f"以輕鬆跑 {_pace(snap.easy_pace_s_per_km)}/km 為基準"
                heat = f"，熱天放慢 {loss:g}%" if loss and loss >= 1 else ""
                reasons.append({"kind": "pace", "text": f"目標配速 {athlete_pace.pace_text(rng)}（{base}{heat}）"})

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
        rng = pick.get("pace_range")
        block = {"reps": 1, "distance_m": round(km * 1000) if km else None, "duration_s": int(minutes * 60),
                 "target_s_per_km": round(sum(rng) / 2) if rng else None,
                 "target_text": athlete_pace.pace_text(rng) if rng else None, "target_mode": "exact",
                 "rest_s": None, "rest_after_s": None}
        notes = "；".join(r["text"] for r in day["reasons"] if r["kind"] != "assigned") or None
        item = {"type": "run", "kind": _PLAN_KIND.get(pick["workout_type"], "easy"),
                "title": day["proposed_text"], "notes": notes, "variants": {"all": [block]}}
        days.append({
            "key": f"d{i}", "date": day["date"], "date_hint": None,
            "source": "\n".join(r["text"] for r in day["reasons"]) or day["proposed_text"],
            "items": [item],
            # what the system suggested, kept to tell accepted from edited
            "suggested": {"date": day["date"], "kind": item["kind"], "title": item["title"], "block": dict(block)},
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
            "review_only": snap.retrospective,
            "snapshot": fingerprint(snap),
            "horizon": [start.isoformat(), end.isoformat()],
            "captured_at": snap.captured_at,
            "inputs": {
                "training_load": snap.acute_load is not None,
                "injury": bool(snap.injuries),
                "weather": _weather_input(snap),
                "easy_pace": snap.easy_pace_s_per_km is not None,
                "health_coach": bool(snap.statements),
                "analysis": snap.analysis is not None,
                "assignments": sum(len(v) for v in snap.assignments.values()),
            },
            "week": [{k: v for k, v in day.items() if k != "proposed"} for day in week],
            # The editable plan is the coach's working copy. Keep the engine's
            # original proposal separately so an audit can reconstruct what
            # was reviewed even after micro-tuning.
            "original_plan": deepcopy({"days": days, "unparsed": []}),
        },
    }


def _weather_input(snap: PlanningSnapshot) -> str | None:
    """The most reliable source the week used: forecast > observation > climate."""
    sources = {w.source for w in snap.weather.values()}
    for s in ("forecast", "observation", "climate_estimate"):
        if s in sources:
            return s
    return None


def _load_band(acute: float | None, chronic: float | None) -> str | None:
    if acute is None or not chronic:
        return None
    ratio = acute / chronic
    return "low" if ratio < 0.8 else "normal" if ratio < 1.3 else "high" if ratio < 1.5 else "very_high"


def fingerprint(snap: PlanningSnapshot) -> dict[str, Any]:
    """What the draft was decided from, kept on the card so confirming can
    tell whether the world moved underneath it (revalidate)."""
    return {
        "start": snap.start.isoformat(), "days": snap.days,
        "injuries": sorted([i.reported_on.isoformat(), i.severity_band] for i in snap.injuries),
        "completed": sorted(d.isoformat() for d in snap.completed),
        "assignments": {d.isoformat(): sorted(({
            "title": a.title,
            "intensity_label": a.intensity_label,
            "duration_minutes": a.duration_minutes,
            "structure": a.structure,
        } for a in v), key=lambda a: json.dumps(a, ensure_ascii=False, sort_keys=True))
                        for d, v in snap.assignments.items()
                        if snap.start <= d < snap.start + timedelta(days=snap.days)},
        "load_band": _load_band(snap.acute_load, snap.chronic_load),
        "easy_pace": snap.easy_pace_s_per_km,
        "weather": {d.isoformat(): w.as_dict() for d, w in snap.weather.items()},
    }


# ---------------------------------------------------------------- confirm: re-check and decide

_SEVERITY_RANK = {None: 0, "NONE": 0, "MILD": 1, "MODERATE": 2, "SEVERE": 3}


def revalidate(old: dict[str, Any], new: dict[str, Any], plan_days: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare the fingerprint a draft was built from with the inputs now.

    blocking: the draft is stale and must be rebuilt -- a new or worse
      injury report, a horizon day completed, the coach's assignments
      changed, load crossed a band, or the easy-pace baseline changed or
      appeared / disappeared.
    weather: only the forecast moved; per proposed day, the pace it gives
      now against the pace on the card. The coach updates or keeps it.
    """
    blocking: list[dict[str, str]] = []
    old_inj = {d: b for d, b in old.get("injuries", [])}
    for d, band in new.get("injuries", []):
        if _SEVERITY_RANK.get(band, 0) > _SEVERITY_RANK.get(old_inj.get(d), 0):
            blocking.append({"kind": "injury", "text": f"{_md_iso(d)} 有新的或更嚴重的不適回報"})
    for d in sorted(set(new.get("completed", [])) - set(old.get("completed", []))):
        blocking.append({"kind": "completed", "text": f"{_md_iso(d)} 選手已經跑完"})
    if new.get("assignments", {}) != old.get("assignments", {}):
        blocking.append({"kind": "assigned", "text": "這週的教練課表在別處被修改過"})
    if new.get("load_band") != old.get("load_band"):
        blocking.append({"kind": "load", "text": "近期負荷跨入不同區間"})
    a, b = old.get("easy_pace"), new.get("easy_pace")
    if a != b:
        blocking.append({"kind": "pace", "text": "選手的輕鬆跑配速基準已變動"})

    weather: list[dict[str, Any]] = []
    easy = old.get("easy_pace")
    kind_to_type = {v: k for k, v in _PLAN_KIND.items()}
    for day in plan_days:
        if day.get("removed") or not day.get("suggested") or not day.get("items"):
            continue
        item = day["items"][0]
        block = ((item.get("variants") or {}).get("all") or [None])[0]
        was, now = old.get("weather", {}).get(day["date"]), new.get("weather", {}).get(day["date"])
        if not block or not block.get("target_s_per_km") or not was or not now:
            continue
        loss_was, loss_now = _best_loss(was), _best_loss(now)
        provenance_changed = (was.get("source"), was.get("provider")) != (now.get("source"), now.get("provider"))
        if abs(loss_now - loss_was) < 1 and not provenance_changed:
            continue
        rng = athlete_pace.pace_range(kind_to_type.get(item.get("kind"), "EASY_RUN"), easy, loss_now)
        if rng is None:
            continue
        weather.append({"key": day["key"], "date": day["date"],
                        "was": {"pace": block.get("target_text"), "speed_loss_pct": loss_was,
                                "fetched_at": was.get("fetched_at"), "source": was.get("source")},
                        "now": {"pace": athlete_pace.pace_text(rng), "target_s_per_km": round(sum(rng) / 2),
                                "speed_loss_pct": loss_now, "fetched_at": now.get("fetched_at"),
                                "source": now.get("source")}})
    return {"blocking": blocking, "weather": weather}


def _md_iso(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.month}/{d.day}"


def _best_loss(day_weather_dict: dict[str, Any]) -> float:
    return min(w["speed_loss_pct"] for w in day_weather_dict["windows"] if w["key"] != "midday")


def apply_weather_update(plan_days: list[dict[str, Any]], changes: list[dict[str, Any]]) -> None:
    """The coach chose the latest forecast: move each day's target pace."""
    by_key = {c["key"]: c for c in changes}
    for day in plan_days:
        c = by_key.get(day["key"])
        if c is None:
            continue
        block = day["items"][0]["variants"]["all"][0]
        block["target_s_per_km"] = c["now"]["target_s_per_km"]
        block["target_text"] = c["now"]["pace"]


_CHANGED = (("date", "日期"), ("kind", "訓練類型"), ("duration_s", "時長"), ("distance_m", "距離"),
            ("target_s_per_km", "配速"))


def decide(week: list[dict[str, Any]], plan_days: list[dict[str, Any]], *,
           reason: str | None = None) -> list[dict[str, Any]]:
    """The coach's decision on every day the system had a say on, from the
    week it suggested and the card as confirmed (pure).

    Days the coach had already scheduled (keep) or the athlete had already
    run (locked) were never the system's suggestion and are not recorded.
    """
    by_date: dict[str, dict[str, Any]] = {}
    for d in plan_days:
        by_date[(d.get("suggested") or {}).get("date") or d.get("date")] = d
    out = []
    for w in week:
        if w["action"] in ("locked", "keep"):
            continue
        day = by_date.get(w["date"])
        day_reason = ((day or {}).get("review_reason") or reason)
        kept = day is not None and not day.get("removed")
        final = _final(day) if kept else None
        if w["action"] == "open":
            out.append({"date": w["date"], "outcome": "coach_authored" if kept else "insufficient_data",
                        "suggested": None, "final": final, "changed": [], "reason": day_reason if kept else None})
            continue
        sug = (day or {}).get("suggested")
        if sug is None:
            # the system suggested no session (rest, or rest instead of an
            # assigned hard day); the coach left it or added one
            out.append({"date": w["date"], "outcome": "edited" if kept else "accepted",
                        "suggested": {"title": w.get("proposed_text")}, "final": final,
                        "changed": ["訓練類型"] if kept else [], "reason": day_reason if kept else None})
            continue
        if not kept:
            out.append({"date": w["date"], "outcome": "removed", "suggested": sug, "final": None,
                        "changed": [], "reason": day_reason})
            continue
        changed = [label for k, label in _CHANGED if _field(sug, k) != final.get(k)]
        out.append({"date": w["date"], "outcome": "edited" if changed else "accepted", "suggested": sug,
                    "final": final, "changed": changed, "reason": day_reason if changed else None})
    return out


def _field(sug: dict[str, Any], key: str) -> Any:
    return sug.get(key) if key in ("date", "kind") else sug["block"].get(key)


def _final(day: dict[str, Any]) -> dict[str, Any]:
    item = day["items"][0] if day.get("items") else {}
    block = ((item.get("variants") or {}).get("all") or [{}])[0]
    return {"date": day.get("date"), "kind": item.get("kind"), "title": item.get("title"),
            "duration_s": block.get("duration_s"), "distance_m": block.get("distance_m"),
            "target_s_per_km": block.get("target_s_per_km")}


# ---------------------------------------------------------------- database


def assemble_snapshot(tx: Connection, athlete_id: uuid.UUID, room_id: uuid.UUID, start: date,
                      days: int = HORIZON_DAYS, *, retrospective: bool = False,
                      forecast: weather_forecast.HourlyForecast | None | bool = True) -> PlanningSnapshot:
    """Read every input once, as the Coach (RLS and the Athlete's Consent
    Scopes decide what is visible; what is not visible is simply absent).

    retrospective: the week is in the past, so only what existed before
    `start` is read -- no run, report, analysis, proposal or assignment
    from inside the week leaks into the draft -- and weather is the climate
    estimate (there is no stored historical forecast). `forecast=True`
    fetches one; pass a HourlyForecast or None to supply / skip it."""
    end = start + timedelta(days=days - 1)
    # everything is read as of the start of `start` in a retrospective
    cutoff = datetime.combine(start, datetime.min.time(), tzinfo=UTC) if retrospective else None
    known = "" if cutoff is None else " AND {col} < :cutoff"
    profile = tx.execute(text("SELECT timezone, city, sex FROM athlete_profiles WHERE user_id = :a"),
                         {"a": athlete_id}).first()
    city = profile.city if profile else None
    sex = profile.sex if profile else None
    tz = ZoneInfo(profile.timezone) if profile and profile.timezone else UTC

    load = tx.execute(text(
        "SELECT acute_load, chronic_load, observation_days FROM training_load_daily "
        "WHERE athlete_id = :a AND unit = 'AU' AND date <= :d ORDER BY date DESC LIMIT 1"),
        {"a": athlete_id, "d": start - timedelta(days=1) if retrospective else start}).first()

    now_local = datetime.now(UTC).astimezone(tz)
    live_c = live_hour = None
    hourly = None
    if not retrospective:
        live = tx.execute(text("SELECT temperature_c, fetched_at FROM weather_cache WHERE city = :c "
                               "ORDER BY fetched_at DESC LIMIT 1"), {"c": city}).first() if city else None
        if live is not None and live.temperature_c is not None:
            fetched = live.fetched_at if live.fetched_at.tzinfo else live.fetched_at.replace(tzinfo=UTC)
            if datetime.now(UTC) - fetched < timedelta(hours=3):
                local = fetched.astimezone(tz)
                live_c, live_hour = float(live.temperature_c), local.hour + local.minute / 60
        hourly = weather_forecast.fetch(city) if forecast is True else (forecast or None)
    weather = {}
    for i in range(days):
        d = start + timedelta(days=i)
        w = day_weather(city, sex, d, today=now_local.date(), live_c=live_c, live_hour=live_hour,
                        forecast=hourly)
        if w is not None:
            weather[d] = w

    inj_params = {"a": athlete_id, "lo": start - timedelta(days=INJURY_CARRY_DAYS),
                  "hi": start - timedelta(days=1) if retrospective else end, "cutoff": cutoff}
    injuries = tuple(
        InjuryFact(r.local_training_date, r.severity_band, r.body_part)
        for r in tx.execute(text(
            "SELECT DISTINCT ON (local_training_date) local_training_date, severity_band, body_part "
            "FROM injury_reports WHERE athlete_id = :a AND local_training_date BETWEEN :lo AND :hi"
            + known.format(col="reported_at") + " ORDER BY local_training_date, reported_at DESC"), inj_params))

    statements: dict[date, AthleteStatement] = {}
    # what the Athlete told the health coach: proposals they accepted for
    # themselves, and suggestions they sent to this Coach
    for r in tx.execute(text(
            "SELECT local_training_date AS d, label, scenario_override AS facts FROM coach_proposals "
            "WHERE athlete_id = :a AND accepted_at IS NOT NULL AND local_training_date BETWEEN :lo AND :hi"
            + known.format(col="accepted_at") + " ORDER BY accepted_at"),
            {"a": athlete_id, "lo": start, "hi": end, "cutoff": cutoff}):
        statements[r.d] = _statement(r.d, r.facts or {}, r.label)
    for r in tx.execute(text(
            "SELECT payload FROM chat_messages WHERE room_id = :r AND retracted_at IS NULL "
            "AND payload->>'kind' = 'coach_suggestion' AND (payload->>'date')::date BETWEEN :lo AND :hi"
            + known.format(col="created_at") + " ORDER BY created_at"),
            {"r": room_id, "lo": start, "hi": end, "cutoff": cutoff}):
        d = date.fromisoformat(r.payload["date"])
        statements[d] = _statement(d, r.payload.get("facts") or {}, r.payload.get("label"))

    assignments: dict[date, list[Assignment]] = {}
    for r in tx.execute(text(
            "SELECT local_date, title, intensity_label, duration_minutes, structure FROM assigned_workouts "
            "WHERE athlete_id = :a AND local_date BETWEEN :lo AND :hi" + known.format(col="created_at")
            + " ORDER BY local_date, title"),
            {"a": athlete_id, "lo": start - timedelta(days=1), "hi": end + timedelta(days=1), "cutoff": cutoff}):
        assignments.setdefault(r.local_date, []).append(
            Assignment(r.local_date, r.title, r.intensity_label, r.duration_minutes, r.structure))

    # in a retrospective nothing inside the week has happened yet
    completed = frozenset() if retrospective else frozenset(tx.execute(text(
        "SELECT DISTINCT local_training_date FROM completed_activities WHERE athlete_id = :a "
        "AND deleted_at IS NULL AND local_training_date BETWEEN :lo AND :hi"),
        {"a": athlete_id, "lo": start, "hi": end}).scalars())

    analysis = None
    row = tx.execute(text(
        "SELECT a.local_training_date AS d, w.signature, w.metrics->'findings' AS findings "
        "FROM workout_analyses w JOIN completed_activities a ON a.id = w.activity_id "
        "WHERE w.athlete_id = :a AND a.local_training_date BETWEEN :lo AND :hi "
        "ORDER BY a.local_training_date DESC, w.updated_at DESC LIMIT 1"),
        {"a": athlete_id, "lo": start - timedelta(days=ANALYSIS_LOOKBACK_DAYS),
         "hi": start - timedelta(days=1) if retrospective else start}).first()
    if row is not None:
        order = {"critical": 0, "warning": 1, "info": 2, "positive": 3}
        findings = sorted((f for f in (row.findings or []) if f.get("advice")),
                          key=lambda f: order.get(f.get("severity"), 9))
        if findings:
            analysis = AnalysisAdvice(row.d, row.signature, tuple(f["advice"] for f in findings))

    easy = athlete_pace.easy_pace(tx, athlete_id, start - timedelta(days=1))

    return PlanningSnapshot(
        athlete_id=str(athlete_id), start=start, days=days, sex=sex, city=city,
        acute_load=float(load.acute_load) if load and load.acute_load is not None else None,
        chronic_load=float(load.chronic_load) if load and load.chronic_load is not None else None,
        observation_days=int(load.observation_days) if load else 0,
        weather=weather, injuries=injuries, statements=statements,
        assignments={k: tuple(v) for k, v in assignments.items()},
        completed=completed, analysis=analysis,
        easy_pace_s_per_km=easy["s_per_km"] if easy else None,
        retrospective=retrospective,
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
