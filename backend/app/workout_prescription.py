"""The workout as it was prescribed ("課表要求"): what the coach asked for,
rep by rep -- distance, target pace (which can differ per rep: a 15x400
progression at 90/85/80 s, a 2000-1000-800 at three different paces) and
recovery.

Where a prescription comes from, in priority order -- and it is always
labelled with its source, because only a real prescription can be used to
grade the athlete:

  coach_assignment  the coach's assigned workout for that date (assignments)
  athlete_text      what the athlete typed ("400x15 90 85 80 間休60")
  activity_name     the workout the athlete wrote into the Garmin activity
                    name ("400 x 10 組休1分鐘 84/圈")
  inferred          reconstructed from what was actually run: reps grouped
                    into same-target blocks (incl. progressions, which only
                    ever get faster -- a coach does not prescribe a fade),
                    each target rounded the way coaches write them (per-km
                    paces on 5 s, lap times on whole even / 5-second values).
                    Because it is derived from the run itself it is used to
                    understand the session's structure, never to grade it.

Free text is turned into structure by the language model, and the result is
checked: every rep count, distance and target in it must appear in the text
(a target may also lie between two that do -- "4:10~3:50" over four reps).
"""

from __future__ import annotations

import itertools
import json
import logging
import re
import statistics
import time
from typing import Any

from app import groq_client

logger = logging.getLogger("app.workout_prescription")

SOURCES = ("coach_assignment", "athlete_text", "activity_name", "inferred")
# The athlete's decision (2026-10): sessions recorded before prescriptions
# were kept have their workout structure completed from the run itself,
# and that completed structure is treated as the session's prescription
# and graded like one. New sessions get the coach's / athlete's real one.
GRADABLE_SOURCES = ("coach_assignment", "athlete_text", "activity_name", "inferred")
SOURCE_LABEL = {
    "coach_assignment": "教練指派",
    "athlete_text": "你填寫的課表",
    "activity_name": "Garmin 活動名稱",
    "inferred": "課表結構",
}
_LAP_UNIT_MAX_M = 600   # reps up to this distance are prescribed as a time per rep


# ---------------------------------------------------------------- formatting


def fmt_mmss(seconds: float) -> str:
    s = round(seconds)
    return f"{s // 60}:{s % 60:02d}"


def target_label(distance_m: float | None, pace_s_per_km: float | None) -> str | None:
    if pace_s_per_km is None:
        return None
    if distance_m and distance_m <= _LAP_UNIT_MAX_M:
        return f"{pace_s_per_km * distance_m / 1000:.0f} 秒"
    return f"{fmt_mmss(pace_s_per_km)}/km"


def coach_round(value: float, *, lap: bool) -> int:
    """Round a target the way coaches write it: per-km paces on 5 s
    (4:00, 4:05), lap times on whole seconds that are even or a multiple
    of 5 (80, 84, 85, 86, 90). Ties go to the slower value."""
    if lap:
        candidates = [x for x in range(int(value) - 3, int(value) + 4) if x % 2 == 0 or x % 5 == 0]
    else:
        base = int(value // 5) * 5
        candidates = [base - 5, base, base + 5, base + 10]
    return min(candidates, key=lambda c: (abs(c - value), -c))


# ---------------------------------------------------------------- shape


def expand(prescription: dict[str, Any]) -> list[dict[str, Any]]:
    """Blocks -> one entry per prescribed rep:
    {distance_m, duration_s, target_pace_s_per_km, target_label, rest_s}."""
    reps = []
    for block in prescription.get("blocks", []):
        n = int(block.get("reps") or 1)
        targets = block.get("targets_s_per_km") or []
        for i in range(n):
            pace = None
            if len(targets) == n:
                pace = targets[i]
            elif len(targets) == 1:
                pace = targets[0]
            reps.append({
                "distance_m": block.get("distance_m"),
                "duration_s": block.get("duration_s"),
                "target_pace_s_per_km": pace,
                "target_label": (target_label(block.get("distance_m"), pace) or "")
                + ("內" if pace is not None and block.get("target_mode") == "max" else "") or None,
                "target_mode": block.get("target_mode", "exact"),
                "rest_s": block.get("rest_s") if i < n - 1 else block.get("rest_after_s", block.get("rest_s")),
            })
    return reps


def describe(prescription: dict[str, Any]) -> str:
    """"15 × 400m（5 趟 90 秒 → 5 趟 85 秒 → 5 趟 80 秒），休息 60 秒"."""
    parts = []
    for block in prescription.get("blocks", []):
        n = block.get("reps") or 1
        unit = f"{block['distance_m']}m" if block.get("distance_m") else f"{block.get('duration_s')} 秒"
        targets = block.get("targets_s_per_km") or []
        label = ""
        within = "內" if block.get("target_mode") == "max" else ""
        if len(set(targets)) == 1:
            label = f" @ {target_label(block.get('distance_m'), targets[0])}{within}"
        elif targets:
            label = "（" + " → ".join(target_label(block.get("distance_m"), t) or "" for t in targets) + "）"
        rest = f"，休 {block['rest_s']} 秒" if block.get("rest_s") else ""
        parts.append(f"{n} × {unit}{label}{rest}" if n > 1 else f"{unit}{label}{rest}")
    return " ＋ ".join(parts)


def _distance_matches(want: float, rep: dict[str, Any]) -> bool:
    if rep.get("nominal_m"):
        return rep["nominal_m"] == want
    # not on a standard distance by GPS (a 200 m rep read as 177 m on the
    # bends): the prescribed distance is what was run if it is close
    gps = rep.get("gps_distance_m") or rep.get("distance_m") or 0
    return abs(gps - want) <= 0.2 * want


def align(prescription: dict[str, Any], reps: list[dict[str, Any]]) -> dict[str, Any]:
    """Match prescribed reps to the reps actually run, in order.

    Returns {per_rep, issues, blocking, completed, prescribed}. A session
    stopped early (fewer reps than prescribed) is still graded on the reps
    that were run -- "只完成 11/12 趟" is a note, not a reason to skip the
    analysis. A rep whose distance does not match its prescription means
    the two cannot be lined up, and blocks grading."""
    wanted = expand(prescription)
    issues: list[str] = []
    blocking = False
    if len(reps) < len(wanted):
        issues.append(f"只完成 {len(reps)}/{len(wanted)} 趟")
    elif len(reps) > len(wanted):
        issues.append(f"課表 {len(wanted)} 趟，實際多跑了 {len(reps) - len(wanted)} 趟")
    per_rep: list[dict[str, Any] | None] = []
    for k, rep in enumerate(reps):
        w = wanted[k] if k < len(wanted) else None
        if w and w.get("distance_m") and not _distance_matches(w["distance_m"], rep):
            got = rep.get("nominal_m") or round(rep.get("gps_distance_m") or rep.get("distance_m") or 0)
            issues.append(f"第 {k + 1} 趟要求 {w['distance_m']}m，實際判讀為 {got}m")
            blocking = True
        per_rep.append(w)
    return {"per_rep": per_rep, "issues": issues, "blocking": blocking,
            "completed": len(reps), "prescribed": len(wanted)}


# ---------------------------------------------------------------- inference


def _partition_cost(values: list[float], cuts: tuple[int, ...]) -> float:
    bounds = (0, *cuts, len(values))
    total = 0.0
    for a, b in zip(bounds, bounds[1:]):
        seg = values[a:b]
        m = statistics.fmean(seg)
        total += sum((x - m) ** 2 for x in seg)
    return total


def _progression_groups(values: list[float], step: float) -> list[tuple[int, int]]:
    """Split a run of same-distance reps into up to 3 contiguous groups of
    >= 2 reps whose (rounded) targets get strictly faster -- the 90/85/80
    progression -- when that explains the reps far better than one target.
    Never splits into slower groups: a fade is a result, not a prescription."""
    n = len(values)
    best = [(0, n)]
    best_cost = _partition_cost(values, ())
    penalty = n * (step / 2) ** 2
    for k in (1, 2):
        for cuts in itertools.combinations(range(2, n - 1), k):
            bounds = (0, *cuts, n)
            if any(b - a < 2 for a, b in zip(bounds, bounds[1:])):
                continue
            means = [statistics.fmean(values[a:b]) for a, b in zip(bounds, bounds[1:])]
            if any(later > earlier - step for earlier, later in zip(means, means[1:])):
                continue
            cost = _partition_cost(values, cuts) + penalty * k
            if cost < best_cost:
                best_cost, best = cost, list(zip(bounds, bounds[1:]))
    return best


def infer(reps: list[dict[str, Any]], rests: list[dict[str, Any]], kind: str) -> dict[str, Any] | None:
    """Reconstruct the prescription from the reps actually run."""
    paced = [r for r in reps if r.get("pace_s_per_km")]
    if not paced:
        return None
    rest_after = {}
    for r in rests:
        rest_after[r["index"] - 1] = r
    blocks: list[dict[str, Any]] = []
    # runs of consecutive reps with the same prescribed distance / duration
    runs: list[list[dict[str, Any]]] = []
    for r in paced:
        key = (r.get("nominal_m"), r.get("nominal_s"))
        if runs and (runs[-1][0].get("nominal_m"), runs[-1][0].get("nominal_s")) == key and key != (None, None):
            runs[-1].append(r)
        else:
            runs.append([r])
    for run in runs:
        dist = run[0].get("nominal_m")
        dur = run[0].get("nominal_s")
        lap = bool(dist and dist <= _LAP_UNIT_MAX_M)
        # lap reps are reasoned about in seconds per rep, longer reps per km
        values = [r["pace_s_per_km"] * dist / 1000 if lap else r["pace_s_per_km"] for r in run]
        groups = _progression_groups(values, 2.0 if lap else 5.0) if len(run) >= 4 else [(0, len(run))]
        for a, b in groups:
            seg = run[a:b]
            target_value = coach_round(statistics.fmean(values[a:b]), lap=lap)
            pace = target_value / dist * 1000 if lap else float(target_value)
            rest_values = [rest_after[r["index"]]["elapsed_s"] for r in seg[:-1] if r["index"] in rest_after]
            rest_s = round(statistics.median(rest_values) / 15) * 15 if rest_values else None
            block: dict[str, Any] = {
                "reps": len(seg),
                "distance_m": dist if dist else (None if dur else round(seg[0]["distance_m"], -1)),
                "duration_s": dur,
                "targets_s_per_km": [round(pace, 1)],
                "rest_s": rest_s,
            }
            after = rest_after.get(seg[-1]["index"])
            if after is not None:
                block["rest_after_s"] = round(after["elapsed_s"] / 15) * 15
            blocks.append(block)
    # adjacent single-rep blocks of one distance with the same target belong together
    merged: list[dict[str, Any]] = []
    for b in blocks:
        if merged and merged[-1]["distance_m"] == b["distance_m"] and merged[-1]["duration_s"] == b["duration_s"] \
                and merged[-1]["targets_s_per_km"] == b["targets_s_per_km"]:
            merged[-1]["reps"] += b["reps"]
            merged[-1]["rest_after_s"] = b.get("rest_after_s")
            merged[-1]["rest_s"] = merged[-1]["rest_s"] or b["rest_s"]
        else:
            merged.append(dict(b))
    prescription = {"source": "inferred", "raw_text": None, "blocks": merged}
    prescription["title"] = describe(prescription)
    if kind == "tempo" and len(merged) == 1:
        prescription["title"] = f"{(merged[0]['distance_m'] or 0) / 1000:.1f} km 節奏跑 @ {fmt_mmss(merged[0]['targets_s_per_km'][0])}/km"
    return prescription


# ---------------------------------------------------------------- assignments


def _pace_text_to_s(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"(\d{1,2}):(\d{2}(?:\.\d+)?)", text)
    return int(m.group(1)) * 60 + float(m.group(2)) if m else None


def from_assignment(structure: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
    """The coach's assigned workout (WorkoutAssignmentSegment list) -> blocks."""
    blocks: list[dict[str, Any]] = []
    for seg in structure:
        if seg.get("kind") == "rest" and blocks and seg.get("durationSeconds"):
            blocks[-1]["rest_after_s"] = seg["durationSeconds"]
            continue
        if seg.get("kind") != "interval":
            continue
        mode = "max" if seg.get("paceMode") == "max" else "exact"
        dists = seg.get("distancesMeters") or ([seg["distanceMeters"]] * int(seg.get("repetitions") or 1)
                                               if seg.get("distanceMeters") else [])
        per_rep = [_pace_text_to_s(p) for p in (seg.get("pacesPerRep") or [])]
        overall = _pace_text_to_s(seg.get("pace"))
        if dists and len(set(dists)) == 1:
            targets = per_rep if per_rep and all(per_rep) else ([overall] if overall else [])
            blocks.append({"reps": len(dists), "distance_m": dists[0], "duration_s": seg.get("durationSeconds"),
                           "targets_s_per_km": targets, "rest_s": seg.get("restSeconds"), "target_mode": mode})
        else:
            for i, d in enumerate(dists):
                t = per_rep[i] if i < len(per_rep) and per_rep[i] else overall
                blocks.append({"reps": 1, "distance_m": d, "duration_s": None,
                               "targets_s_per_km": [t] if t else [], "rest_s": seg.get("restSeconds"),
                               "target_mode": mode})
    if not blocks:
        return None
    p = {"source": "coach_assignment", "raw_text": title, "blocks": blocks}
    p["title"] = describe(p)
    return p


# ---------------------------------------------------------------- free text

_PARSE_PROMPT = """你把跑步選手寫的「課表」文字轉成 JSON。只輸出 JSON 物件，格式：
{"is_workout": true/false,
 "blocks": [{"reps": 整數趟數, "distance_m": 每趟距離公尺或 null, "duration_s": 每趟時間秒數或 null,
             "targets": [目標，每趟一個或全部共用一個；沒寫就空陣列],
             "target_unit": "per_rep_s"（每趟秒數，例如 400 跑 86 秒）或 "per_km_s"（每公里配速秒數，例如 3:40/km = 220）,
             "rest_s": 每趟之間休息秒數或 null,
             "target_mode": "max"（寫「X內」「X以內」「不超過X」代表上限，跑更快也算達標）或 "exact"}],
 "warmup": "暖身描述或 null", "cooldown": "收操描述或 null"}

規則：
- 只能使用文字裡寫出來的數字，不可以自己補或猜。沒寫目標配速就 targets 留空。
- 「400 x 10」「400*10」「10 趟 400」都是 10 趟 400m。「2000 1600 1200 800」是 4 個各 1 趟的 block。
- 「90 85 80」接在 15 趟後面代表分三段漸速：拆成 3 個 block（各 5 趟），每個 block 一個目標。
- 「4:10～3:50」這種範圍：targets 依序列出每一趟（從第一個值平均過渡到最後一個值，四捨五入到整數秒）。
- 「組休60」「r60」「r'2min」「間休1分鐘」是 rest_s（60、60、120、60）。「X 秒/趟」「X/圈」是 per_rep_s。
- 「200 150 100 2趟」「(400-300-200) x3」：一串距離後面接「N趟／N組／xN」代表整串依序重複 N 輪，要依實際順序展開成 block（200、150、100、200、150、100），不要把同距離併在一起。
- 選手常把「跑完的結果」也寫進去：前面有「平均」「實際」「結果」「跑到」的數字，或是在課表後面逐趟列出的成績（例如「1000x4 組休2分鐘 3:48 / 3:46 / 3:48 / 3:49」），都是實際成績，不是要求，不可放進 targets。只有「配速X」「@X」「X秒/趟」「X/圈」這類寫在課表本身的才是要求；同時出現時以要求為準（「配速4:30（實際上跑到4:10）」的要求是 4:30）。
- 「熱身 1km」「放鬆跑 3km」放在 warmup / cooldown，不是 block。
- 如果文字只是地名、心情或沒有課表內容（例如「大安區 跑步」），is_workout=false、blocks=[]。"""

_NUM = re.compile(r"(\d+(?:[.:]\d+)?)\s*(km|k|公里|min|分鐘|分)?", re.I)


def _numbers_in(text: str) -> set[float]:
    """Every number written in the text, in the units the structure uses:
    m:ss -> seconds, "1.5km" -> 1500 m, "2min" -> 120 s."""
    out: set[float] = set()
    for tok, unit in _NUM.findall(text):
        if ":" in tok:
            m, sec = tok.split(":")
            out.add(int(m) * 60 + float(sec))
            continue
        v = float(tok)
        out.add(v)
        unit = (unit or "").lower()
        if unit in ("km", "k", "公里"):
            out.add(v * 1000)
        elif unit in ("min", "分鐘", "分"):
            out.add(v * 60)
    return out


def _check_against_text(blocks: list[dict[str, Any]], text: str) -> list[str]:
    """Every number the model put in the structure must come from the text.
    Exceptions that are still grounded in it: a rep count that splits a
    written total ("15 趟 ... 90 85 80" -> 5+5+5), and targets interpolated
    between two written values ("4:10~3:50" over four reps)."""
    nums = _numbers_in(text)
    total_reps = float(sum(b["reps"] for b in blocks))
    problems = []
    for b in blocks:
        if b["reps"] > 1 and float(b["reps"]) not in nums and total_reps not in nums:
            problems.append(f"趟數 {b['reps']}")
        for key in ("distance_m", "duration_s", "rest_s"):
            v = b.get(key)
            if v is not None and float(v) not in nums:
                problems.append(f"{key} {v}")
        raw = b.get("_raw_targets") or []
        for t in raw:
            if t in nums:
                continue
            if len(raw) > 1 and any(min(a, c) < t < max(a, c) for a in nums for c in nums):
                continue
            problems.append(f"目標 {t:g}")
    return problems


def parse_text(text: str, *, deadline_s: float = 40.0) -> dict[str, Any]:
    """Free-text workout -> {"prescription": {...} | None, "problems": [...],
    "is_workout": bool}. Never raises; problems explain any rejection."""
    text = (text or "").strip()
    if not text:
        return {"prescription": None, "problems": ["沒有輸入課表內容"], "is_workout": False}
    if groq_client.api_key() is None:
        return {"prescription": None, "problems": ["未設定 GROQ_API_KEY，無法解析文字課表"], "is_workout": False}
    deadline = time.monotonic() + deadline_s
    last_problem = "AI 無法解析"
    for model in ("qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"):
        try:
            raw = groq_client.chat(model, [{"role": "system", "content": _PARSE_PROMPT},
                                           {"role": "user", "content": text}],
                                   deadline=deadline, max_tokens=800, temperature=0.0, json_mode=True)
            data = json.loads(raw)
        except groq_client.GroqUnavailable as exc:
            last_problem = str(exc)
            continue
        except (json.JSONDecodeError, TypeError):
            last_problem = f"{model} 回覆格式錯誤"
            continue
        if not data.get("is_workout") or not data.get("blocks"):
            return {"prescription": None, "problems": ["這段文字看不出課表內容"], "is_workout": False}
        blocks, problems = _normalise_blocks(data["blocks"])
        problems += _check_against_text(blocks, text)
        if problems:
            last_problem = "解析結果與原文不符：" + "、".join(problems[:4])
            logger.warning("prescription_parse_rejected model=%s text=%r problems=%s", model, text, problems)
            continue
        for b in blocks:
            b.pop("_raw_targets", None)
        p = {"source": "athlete_text", "raw_text": text, "blocks": blocks,
             "warmup": data.get("warmup"), "cooldown": data.get("cooldown")}
        p["title"] = describe(p)
        return {"prescription": p, "problems": [], "is_workout": True}
    return {"prescription": None, "problems": [last_problem], "is_workout": True}


def _normalise_blocks(raw_blocks: list[Any]) -> tuple[list[dict[str, Any]], list[str]]:
    blocks, problems = [], []
    for raw in raw_blocks:
        if not isinstance(raw, dict):
            problems.append("格式錯誤")
            continue
        try:
            reps = int(raw.get("reps") or 1)
            dist = raw.get("distance_m")
            dist = int(dist) if dist not in (None, "") else None
            dur = raw.get("duration_s")
            dur = int(dur) if dur not in (None, "") else None
            rest = raw.get("rest_s")
            rest = int(rest) if rest not in (None, "") else None
            targets = [float(t) for t in (raw.get("targets") or [])]
        except (TypeError, ValueError):
            problems.append("數值格式錯誤")
            continue
        if not (1 <= reps <= 60) or (dist is not None and not 50 <= dist <= 42195) or (dist is None and dur is None):
            problems.append("趟數或距離不合理")
            continue
        unit = raw.get("target_unit")
        paces = []
        for t in targets:
            if unit == "per_rep_s" and dist:
                paces.append(round(t / dist * 1000, 1))
            else:
                paces.append(t)
        if any(not 120 <= p <= 900 for p in paces):
            problems.append("目標配速不合理")
            continue
        if paces and len(paces) not in (1, reps):
            problems.append("目標數量與趟數不符")
            continue
        blocks.append({"reps": reps, "distance_m": dist, "duration_s": dur, "targets_s_per_km": paces,
                       "rest_s": rest, "_raw_targets": targets,
                       "target_mode": "max" if raw.get("target_mode") == "max" else "exact"})
    return blocks, problems


def fill_missing_targets(prescription: dict[str, Any], inferred: dict[str, Any] | None) -> dict[str, Any]:
    """A real prescription without paces ("400 x 10") keeps its structure;
    the per-rep targets are marked as estimated, not invented as the coach's."""
    if not inferred:
        return prescription
    inferred_reps = expand(inferred)
    k = 0
    for block in prescription["blocks"]:
        n = block.get("reps") or 1
        if not block.get("targets_s_per_km"):
            vals = [inferred_reps[i]["target_pace_s_per_km"] for i in range(k, min(k + n, len(inferred_reps)))]
            if vals:
                block["targets_s_per_km"] = vals if len(set(vals)) > 1 else vals[:1]
                block["targets_inferred"] = True
        k += n
    prescription["title"] = describe(prescription)
    return prescription


def looks_like_workout(name: str | None) -> bool:
    """Garmin's default names are "<district> 跑步" / "<district> 田徑跑步";
    an athlete-written workout has rep / distance notation in it."""
    if not name:
        return False
    return bool(re.search(r"\d+\s*[x×*]\s*\d+|\d+\s*[x×*]|[x×]\s*\d+|\d{3,4}(\s+\d{3,4}){2,}|間歇|組休|r\s*['’]?\d", name, re.I))
