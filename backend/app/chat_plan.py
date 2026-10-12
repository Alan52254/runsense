"""A coach's training plan, written in chat, turned into assignments.

The language model only reads the text and lays it out day by day; every
date is resolved here, deterministically, and every number it put into a
session must be written in that day's own text (the day's text must
itself appear verbatim in the coach's messages). Anything that fails these
checks is shown on the confirmation card as a problem, never silently
scheduled. Nothing is written until the coach confirms the card.

Plan shape (what the card holds):

    {"days": [{"key", "date" (YYYY-MM-DD | null), "date_hint", "source",
               "items": [ {"type": "run", "kind", "title",
                           "variants": {"all" | "male" | "female": [block, ...]}},
                          {"type": "strength" | "core", "title", "content"} ],
               "problems": [...], "removed": false}],
     "unparsed": [...]}

A block: {"reps", "distance_m", "duration_s", "target_s_per_km",
"target_mode": "exact" | "max", "target_text", "rest_s", "rest_after_s"}.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, timedelta
from typing import Any

from app import groq_client, personas
from app.workout_prescription import _NUM, _numbers_in

logger = logging.getLogger("app.chat_plan")

_MODELS = ("qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b")

_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}

# the coach's plan -> JSON; edit the wording in the persona file
PLAN_PROMPT = personas.system_prompt("team_assistant", "schedule", with_soul=False)


# ---------------------------------------------------------------- dates


def _resolve_md(month: int, day: int, today: date) -> date | None:
    """A month/day with no year: the nearest one on or after today."""
    for year in (today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            continue
        if d >= today:
            return d
    return None


def _parse_md(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None
    m = re.search(r"(\d{1,2})\s*[/／月.]\s*(\d{1,2})", text)
    return (int(m.group(1)), int(m.group(2))) if m else None


def resolve_date(day: dict[str, Any], today: date) -> tuple[date | None, str]:
    """(date or None, human hint of what the text said)."""
    md = _parse_md(day.get("date"))
    if md:
        return _resolve_md(md[0], md[1], today), f"{md[0]}/{md[1]}"
    weekday = _WEEKDAYS.get((day.get("weekday") or "").strip()[-1:] if day.get("weekday") else "", None)
    week = day.get("week_range")
    if weekday is not None and week:
        start = _parse_md(week)
        if start:
            start_date = _resolve_md(start[0], start[1], today)
            if start_date:
                for k in range(7):
                    d = start_date + timedelta(days=k)
                    if d.weekday() == weekday:
                        return d, f"{week} 週{day.get('weekday')}"
    rel = (day.get("relative") or "").strip()
    if rel:
        if rel.startswith("今天"):
            return today, rel
        if rel.startswith("明天"):
            return today + timedelta(days=1), rel
        if rel.startswith("後天"):
            return today + timedelta(days=2), rel
        m = re.match(r"(這|本|下|下下)?(週|周|星期|禮拜)([一二三四五六日天])", rel)
        if m:
            target = _WEEKDAYS[m.group(3)]
            monday = today - timedelta(days=today.weekday())
            shift = {None: 0, "這": 0, "本": 0, "下": 7, "下下": 14}[m.group(1)]
            d = monday + timedelta(days=shift + target)
            if m.group(1) in (None, "這", "本") and d < today:
                d += timedelta(days=7)
            return d, rel
    if weekday is not None:
        d = today + timedelta(days=(weekday - today.weekday()) % 7)
        return d, f"週{day.get('weekday')}（未寫日期，取最近的一天）"
    return None, "原文沒有寫日期"


# ---------------------------------------------------------------- blocks


def _target_to_pace(target: float | None, unit: str | None, distance: float | None) -> float | None:
    if target is None:
        return None
    if unit == "per_400_s":
        return target * 2.5
    if unit == "per_rep_s" and distance:
        return target / distance * 1000
    if unit == "per_km_s":
        return float(target)
    return None


def _target_text(target: float | None, unit: str | None, mode: str) -> str | None:
    if target is None:
        return None
    within = "內" if mode == "max" else ""
    if unit == "per_400_s":
        return f"每 400m {target:g} 秒{within}"
    if unit == "per_rep_s":
        return f"{target:g} 秒{within}"
    if unit == "per_km_s":
        return f"{int(target // 60)}:{target % 60:02.0f}/km{within}"
    return None


def _normalise_block(raw: dict[str, Any]) -> tuple[dict[str, Any] | None, list[float], str | None]:
    """-> (block, numbers it uses, problem)."""
    try:
        reps = int(raw.get("reps") or 1)
        dist = float(raw["distance_m"]) if raw.get("distance_m") not in (None, "") else None
        dur = float(raw["duration_s"]) if raw.get("duration_s") not in (None, "") else None
        target = float(raw["target"]) if raw.get("target") not in (None, "") else None
        rest = float(raw["rest_s"]) if raw.get("rest_s") not in (None, "") else None
        rest_after = float(raw["rest_after_s"]) if raw.get("rest_after_s") not in (None, "") else None
        sets = int(raw.get("sets") or 1)
    except (TypeError, ValueError, KeyError):
        return None, [], "課表格式無法判讀"
    unit = raw.get("target_unit")
    mode = "max" if raw.get("target_mode") == "max" else "exact"
    if not 1 <= reps <= 60 or not 1 <= sets <= 10 or (dist is None and dur is None):
        return None, [], "趟數或距離無法判讀"
    if dist is not None and not 50 <= dist <= 50000:
        return None, [], "距離不合理"
    pace = _target_to_pace(target, unit, dist)
    if target is not None and (pace is None or not 120 <= pace <= 900):
        return None, [], "目標配速不合理"
    numbers = [x for x in (dist, dur, target, rest, rest_after) if x is not None]
    if reps > 1:
        numbers.append(float(reps))
    if sets > 1:
        numbers.append(float(sets))
    block = {"reps": reps, "sets": sets, "distance_m": dist, "duration_s": dur,
             "target_s_per_km": round(pace, 1) if pace else None, "target_mode": mode,
             "target_text": _target_text(target, unit, mode), "rest_s": rest, "rest_after_s": rest_after}
    return block, numbers, None


_MALE = re.compile(r"男\s*(?:生)?\s*[:：]?\s*(?:第一組)?\s*\d")
_FEMALE = re.compile(r"女\s*(?:生)?\s*[:：]?\s*(?:第一組)?\s*\d")


def day_blocking_problems(day: dict[str, Any]) -> list[str]:
    """Problems that must be fixed (by editing or removing the day) before
    the plan can be confirmed -- re-checked at confirm time."""
    out = []
    if not day.get("date"):
        out.append("日期尚未確定")
    if _MALE.search(day.get("source") or "") and _FEMALE.search(day.get("source") or ""):
        for item in day.get("items") or []:
            v = item.get("variants") or {}
            if item.get("type") == "run" and not (v.get("male") and v.get("female")):
                out.append(f"{item.get('title') or '跑步'}：原文分男女目標，但沒有分開整理，請修正或刪除這一天")
    return out


def _grounded(numbers: list[float], text: str) -> list[float]:
    """Numbers not written in the text (a set count like "2組" may also be
    the reps of each block, written once)."""
    nums = _numbers_in(text)
    return [n for n in numbers if n not in nums]


# dates and week labels in a day's text are not training numbers
_DATE_LIKE = re.compile(r"\d{1,4}\s*[/／]\s*\d{1,2}(?:\s*[/／]\s*\d{1,2})?|\d{1,2}\s*月\s*\d{1,2}\s*[日號]?"
                        r"|[Ww]\s*\d+|第\s*\d+\s*[週周天]")


def _unused_numbers(source: str, used: set[float]) -> list[str]:
    """Numbers the coach wrote for this day that the parsed plan does not
    use (e.g. a rest the model dropped). A token counts as used when any
    reading of it ("2分鐘" = 2 or 120 s, "3:20" = 200 s) is in the plan."""
    out: list[str] = []
    for tok, unit in _NUM.findall(_DATE_LIKE.sub(" ", source)):
        if not _numbers_in(tok + (unit or "")) & used and tok not in out:
            out.append(tok)
    return out


def _verbatim(fragment: str, source: str) -> bool:
    squash = lambda s: re.sub(r"\s+", "", s)  # noqa: E731
    return bool(fragment) and squash(fragment) in squash(source)


# ---------------------------------------------------------------- parse


def parse_plan(messages_text: str, today: date, *, deadline_s: float = 90.0) -> dict[str, Any]:
    """Coach's text -> plan dict (see module docstring). Never raises."""
    if groq_client.api_key() is None:
        return {"days": [], "unparsed": [], "error": "未設定 GROQ_API_KEY", "error_kind": "unavailable"}
    deadline = time.monotonic() + deadline_s
    last_error = "AI 無法解析課表"
    # a model that answered "no workout here" outranks a later model failing:
    # the coach must hear "nothing found", not an HTTP error
    answered_empty = False
    for model in _MODELS:
        try:
            raw = groq_client.chat(model, [{"role": "system", "content": PLAN_PROMPT},
                                           {"role": "user", "content": messages_text}],
                                   deadline=deadline, max_tokens=4000, temperature=0.0, json_mode=True)
            data = json.loads(raw)
        except groq_client.GroqUnavailable as exc:
            last_error = str(exc)
            continue
        except (json.JSONDecodeError, TypeError):
            last_error = f"{model} 回覆格式錯誤"
            continue
        plan = _build(data, messages_text, today)
        if plan["days"]:
            plan["model"] = model
            return plan
        answered_empty = True
    if answered_empty:
        return {"days": [], "unparsed": [], "error": "訊息中找不到課表內容", "error_kind": "no_content"}
    logger.warning("plan_parse_unavailable last_error=%s", last_error)
    return {"days": [], "unparsed": [], "error": last_error, "error_kind": "unavailable"}


def _build(data: dict[str, Any], source_text: str, today: date) -> dict[str, Any]:
    days = []
    for k, raw_day in enumerate(data.get("days") or []):
        if not isinstance(raw_day, dict):
            continue
        source = str(raw_day.get("source") or "").strip()
        problems: list[str] = []
        if not _verbatim(source, source_text):
            problems.append("AI 標出的原文與訊息內容不一致，請確認這一天的內容")
        day_date, hint = resolve_date(raw_day, today)
        if day_date is None:
            problems.append("原文沒有寫出可判斷的日期，請在卡片上選擇日期")
        items = []
        used: set[float] = set()  # every number the parsed day relies on
        for raw_item in raw_day.get("items") or []:
            if not isinstance(raw_item, dict):
                continue
            kind_type = raw_item.get("type")
            title = str(raw_item.get("title") or "").strip()[:80]
            if kind_type in ("strength", "core"):
                content = str(raw_item.get("content") or "").strip()[:1500]
                items.append({"type": kind_type, "title": title or ("重訓" if kind_type == "strength" else "核心"),
                              "content": content})
                used |= _numbers_in(content)
                continue
            variants: dict[str, list[dict[str, Any]]] = {}
            for key in ("all", "male", "female"):
                raw_blocks = (raw_item.get("variants") or {}).get(key)
                if not raw_blocks:
                    continue
                blocks = []
                last_sets = 1
                for rb in raw_blocks:
                    block, numbers, problem = _normalise_block(rb if isinstance(rb, dict) else {})
                    if problem:
                        problems.append(f"{title or '跑步'}：{problem}")
                        continue
                    missing = _grounded(numbers, source)
                    if missing:
                        problems.append(f"{title or '跑步'}：數字 {', '.join(f'{m:g}' for m in missing)} 不在這一天的原文裡")
                        continue
                    used |= set(numbers)
                    # "200*10 2組": the sets are expanded here, not by the
                    # model -- a set count is a number in the text like any other
                    last_sets = block.pop("sets")
                    for _ in range(last_sets):
                        blocks.append(dict(block))
                if blocks and last_sets > 1:
                    # nothing follows the final set: its between-sets rest
                    # is not part of the session
                    blocks[-1]["rest_after_s"] = None
                elif blocks and blocks[-1].get("rest_after_s") and not blocks[-1].get("rest_s") \
                        and blocks[-1]["reps"] > 1:
                    # one set with a rest written after it has no next set
                    # to come before: "600*8 組休3.5min" is the rest between
                    # the eight reps
                    blocks[-1]["rest_s"] = blocks[-1].pop("rest_after_s")
                    blocks[-1]["rest_after_s"] = None
                if blocks:
                    variants[key] = blocks
            if not variants:
                problems.append(f"{title or '跑步'}：無法整理出課表內容")
                continue
            items.append({"type": "run", "kind": raw_item.get("kind") or "other",
                          "title": title or "跑步", "variants": variants})
        if not items:
            continue
        unused = _unused_numbers(source, used)
        if unused:
            problems.append(f"原文的數字 {'、'.join(unused)} 沒有出現在整理後的課表裡，請確認（修改或刪除這一天）")
        day = {"key": f"d{k}", "date": day_date.isoformat() if day_date else None, "date_hint": hint,
               "source": source, "items": items, "problems": problems, "removed": False, "edited": False}
        day["problems"] = problems + [p for p in day_blocking_problems(day) if p not in problems and p != "日期尚未確定"]
        days.append(day)
    days.sort(key=lambda d: d["date"] or "9999")
    return {"days": days, "unparsed": []}


# ---------------------------------------------------------------- assignments


def _pace_text(sec: float) -> str:
    mm, ss = divmod(sec, 60)
    return f"{int(mm)}:{ss:04.1f} /km" if round(ss, 1) != int(ss) else f"{int(mm)}:{int(ss):02d} /km"


def blocks_for(item: dict[str, Any], sex: str | None) -> list[dict[str, Any]] | None:
    v = item.get("variants") or {}
    if sex and v.get(sex):
        return v[sex]
    if v.get("all"):
        return v["all"]
    return None


def structure_for(item: dict[str, Any], blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Run item -> WorkoutAssignmentSegment list (what History / the
    prescription reader already understand)."""
    kind = item.get("kind")
    # recovery / steady only come from a Coach Suggestion (app/coach_handoff.py):
    # one continuous run, like an easy one
    if kind in ("easy", "recovery", "steady"):
        b = blocks[0]
        seg = {"kind": "jog", "label": item.get("title") or "easy run"}
        if b.get("duration_s"):
            seg["durationSeconds"] = int(b["duration_s"])
        if b.get("distance_m"):
            seg["distanceMeters"] = int(b["distance_m"])
        return [seg]
    out: list[dict[str, Any]] = []
    for i, b in enumerate(blocks):
        seg: dict[str, Any] = {"kind": "interval", "label": "節奏跑" if kind == "tempo" else "間歇",
                               "repetitions": b["reps"]}
        if b.get("distance_m"):
            seg["distanceMeters"] = int(b["distance_m"])
        if b.get("duration_s"):
            seg["durationSeconds"] = int(b["duration_s"])
        if b.get("target_s_per_km"):
            seg["pace"] = _pace_text(b["target_s_per_km"])
            if b.get("target_mode") == "max":
                seg["paceMode"] = "max"
        if b.get("rest_s"):
            seg["restSeconds"] = int(b["rest_s"])
        out.append(seg)
        if b.get("rest_after_s") and i + 1 < len(blocks):
            out.append({"kind": "rest", "label": "組休", "durationSeconds": int(b["rest_after_s"])})
    return out


def estimate_minutes(item: dict[str, Any], blocks: list[dict[str, Any]]) -> int:
    """Rough session length for the assignment list (the schema needs one).
    Uses the prescribed paces and rests; where the plan gives no pace the
    work is counted at 5:00 /km."""
    total = 0.0
    for b in blocks:
        if b.get("duration_s"):
            work = b["duration_s"] * b["reps"]
        else:
            work = (b.get("distance_m") or 0) / 1000 * (b.get("target_s_per_km") or 300) * b["reps"]
        total += work + (b.get("rest_s") or 0) * max(0, b["reps"] - 1) + (b.get("rest_after_s") or 0)
    return max(1, round(total / 60))


def summary_line(item: dict[str, Any], blocks: list[dict[str, Any]] | None) -> str:
    if not blocks:
        return item.get("title") or ""
    parts = []
    for b in blocks:
        d = b.get("distance_m")
        unit = ((f"{d / 1000:g} km" if d >= 5000 else f"{d:g}m") if d
                else f"{b.get('duration_s', 0) / 60:g} 分鐘")
        head = f"{b['reps']} × {unit}" if b["reps"] > 1 else unit
        if b.get("target_text"):
            head += f" @ {b['target_text']}"
        if b.get("rest_s"):
            head += f"（趟休 {b['rest_s']:g} 秒）"
        if b.get("rest_after_s"):
            head += f"，休 {b['rest_after_s'] / 60:g} 分"
        parts.append(head)
    return "；".join(parts)
