"""Coach-voice write-up of an analysed workout.

The language model is a narrator, not an analyst: it receives only the
numbers and findings workout_analysis.py already computed and is told to
use nothing else. Every number in its reply is then checked against those
facts; a reply containing a number that is not in the data is rejected and
rewritten once, and if that also fails (or Groq is unreachable / rate
limited / slow), the same findings are rendered by a fixed template and
the result is labelled as the offline analysis. The athlete never sees a
spinner that ends in an error, and never sees an invented number.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from app import groq_client
from app.workout_analysis import fmt_duration, fmt_pace, rep_label

logger = logging.getLogger("app.workout_narrative")

_DEFAULT_MODELS = ("qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b")
# a rate-limited model is waited out (Groq says for how long), so the
# budget covers roughly one per-minute quota window
_TOTAL_BUDGET_S = 75.0

SESSION_TYPE_LABEL = {
    "intervals": "間歇課表",
    "tempo": "節奏跑",
    "easy": "輕鬆跑",
    "long": "長距離",
    "race": "比賽",
    "other": "其他訓練",
}

_ROLE_LABEL = {"warmup": "暖身", "work": "強度", "rest": "休息", "set_rest": "組間休息",
               "strides": "加速跑", "cooldown": "收操", "steady": "連續跑"}
_REST_TYPE_LABEL = {"standing": "站著／暫停", "walking": "走路", "jogging": "慢跑"}
_ZONE_METHOD_LABEL = {"percent_hrr": "儲備心率法", "percent_max_hr": "最大心率百分比"}
_SOURCE_LABEL = {"manual": "你的手動設定", "device": "Garmin 手錶當天設定",
                 "history": "你的歷史紀錄推算", "age_formula": "年齡公式估算"}

SYSTEM_PROMPT = """你是一位帶過許多中長跑選手的田徑教練，跑完課後在跑道邊跟選手講兩三句話。教練不會寫報告，只講今天最重要的事和下次怎麼跑。

【硬性規則】
1. 只能使用「訓練資料」裡出現過的數字。不要自己計算新的數字（例如自己相減算差距），需要的差距資料裡都已經算好。
2. 不要編造資料裡沒有的資訊：天氣、睡眠、飲食、傷痛、比賽目標等一律不要提。
3. 「課表要求」若標明本次不評比，就不要說選手達成或沒達成要求。
4. 「判讀結果」是已經用演算法確認過的結論。你寫的每一個判斷都必須出自判讀結果，不可推翻、誇大，也不要自行加上原因或結論。severity=warning 的項目一定要提到。
5. 提到某一趟時用「第 N 趟」，並附上該趟的實際數字。
6. 「資料限制」中的項目要誠實地用一句話帶過。
7. 不做醫療診斷。

【格式】繁體中文，約 120–220 字，不要用任何標題或 # 符號，不要條列超過 2 點：
- 第一段（一到兩句）：今天最重要的一件事。有 severity=warning 的判讀就講它，沒有就講最突出的一項；直接帶數字。
- 第二段（一到兩句，可省略）：跟課表要求或上次同課表比，只講有差異的地方；資料裡沒有比較對象就整段省略。
- 最後一行以「下次：」開頭，給一件具體可執行的事（例如第一趟壓在多少配速、休息延長幾秒）。

【禁用】不要用空泛的稱讚或客套話，例如「做得很好」「表現不錯」「繼續保持」「加油」「值得肯定」「整體而言」「總結來說」；也不要逐條重述資料表。好的地方用數字說，例如「六趟差距只有 2 秒」。"""


# ---------------------------------------------------------------- facts


def build_facts(*, signature_label: str, session_type: str, activity_date: str, analysis: dict,
                sub_sport: str | None) -> dict[str, Any]:
    s = analysis["summary"]
    hr = s["hr_profile"]
    reps = analysis["reps"]
    stats = analysis["segments"]
    facts: dict[str, Any] = {
        "課表": signature_label,
        "類型": SESSION_TYPE_LABEL.get(session_type, session_type),
        "日期": activity_date,
        "紀錄方式": {"track": "手錶操場模式", "treadmill": "跑步機"}.get(sub_sport or "", "一般 GPS 跑步"),
        "整體": {
            "總距離": f"{s['total_distance_m'] / 1000:.2f} km",
            "總時間": fmt_duration(s["total_elapsed_s"]),
            "平均心率": f"{s['avg_hr']} bpm" if s.get("avg_hr") else "無資料",
            "最高心率": f"{s['max_hr']} bpm" if s.get("max_hr") else "無資料",
        },
        "心率設定": {
            "最大心率": f"{hr['max_hr']} bpm（來源：{_SOURCE_LABEL.get(hr['max_hr_source'], '未知')}）"
            if hr.get("max_hr") else "未設定",
            "安靜心率": f"{hr['resting_hr']} bpm" if hr.get("resting_hr") else "未設定",
            "區間算法": _ZONE_METHOD_LABEL.get(hr.get("zone_method"), hr.get("zone_method")),
            "第2區上限": f"{hr['zone_tops'][2]} bpm" if hr.get("zone_tops") else "未設定",
        },
    }
    presc = s.get("prescription")
    if presc:
        facts["課表要求"] = {
            "內容": presc.get("title"),
            "來源": presc.get("source_label"),
            "說明": "教練開的課表，逐趟評比" if presc.get("gradable")
            else "課表與實際紀錄的趟數對不起來，本次不評比要求",
        }
    if reps:
        rows = []
        by_index = {x["index"]: x for x in stats}
        for r in reps:
            nxt = by_index.get(r["index"] + 1)
            row: dict[str, Any] = {
                "趟": r["rep_number"],
                "距離": rep_label(r) if (r.get("nominal_m") or r.get("nominal_s")) else f"{round(r['distance_m'])}m",
                "時間": fmt_duration(r["moving_s"]),
                "配速": fmt_pace(r["pace_s_per_km"]),
            }
            if r.get("nominal_m") and r["nominal_m"] <= 1600 and r.get("pace_s_per_km"):
                row["每400m"] = f"{r['pace_s_per_km'] * 0.4:.1f} 秒"
            if r.get("nominal_m") and r["nominal_m"] <= 600 and r.get("pace_s_per_km"):
                row["本趟秒數"] = f"{r['pace_s_per_km'] * r['nominal_m'] / 1000:.1f} 秒"
            if r.get("target_label"):
                row["要求"] = r["target_label"]
                if r.get("target_dev_s") is not None and (r.get("nominal_m") or 0) <= 600:
                    row["與要求差距"] = f"{'慢' if r['target_dev_s'] > 0 else '快'} {abs(r['target_dev_s']):.1f} 秒"
                elif r.get("target_dev_pct") is not None:
                    row["與要求差距"] = f"{'慢' if r['target_dev_pct'] > 0 else '快'} {abs(r['target_dev_pct']):.1f}%"
            if r.get("avg_hr"):
                row["平均心率"] = f"{r['avg_hr']} bpm"
            if r.get("hr_end"):
                row["結束心率"] = f"{r['hr_end']} bpm"
            if r.get("interruptions_s"):
                row["中途停下"] = f"{r['interruptions_s']} 秒"
            if nxt and nxt["role"] in ("rest", "set_rest"):
                rest = f"{fmt_duration(nxt['elapsed_s'])}（{_REST_TYPE_LABEL.get(nxt.get('rest_type'), '')}）"
                if nxt["role"] == "set_rest":
                    rest = "組間 " + rest
                row["後接休息"] = rest
                if nxt.get("hr_drop") is not None:
                    row["休息60秒心率下降"] = f"{nxt['hr_drop']} bpm"
            rows.append(row)
        facts["每趟"] = rows
        if s.get("mean_work_pace_s_per_km"):
            facts["各趟平均配速"] = fmt_pace(s["mean_work_pace_s_per_km"])
    if s.get("km_splits") and not reps:
        facts["每公里"] = [{"公里": k["km"], "配速": fmt_pace(k["pace_s_per_km"]),
                          "平均心率": f"{k['avg_hr']} bpm" if k.get("avg_hr") else "無"} for k in s["km_splits"]]
    warm = [x for x in stats if x["role"] == "warmup"]
    if warm and reps:
        facts["暖身"] = f"{fmt_duration(warm[0]['moving_s'])}，平均心率 {warm[0]['avg_hr']} bpm" \
            if warm[0].get("avg_hr") else fmt_duration(warm[0]["moving_s"])
    facts["判讀結果"] = [
        {"code": f["code"], "severity": f["severity"], "標題": f["title"], "內容": f["detail"],
         **({"建議": f["advice"]} if f.get("advice") else {})}
        for f in analysis["findings"]
    ]
    facts["資料限制"] = analysis["data_notes"] or ["無"]
    return facts


# ---------------------------------------------------------------- number check

_NUM = re.compile(r"\d+(?:[.:]\d+)*")


def _numbers(text: str) -> set[str]:
    return set(_NUM.findall(text))


def unverified_numbers(text: str, facts: dict[str, Any], rep_count: int) -> list[str]:
    """Numbers in the model's reply that do not appear anywhere in the facts
    it was given. Small ordinals (第 3 趟, 3 點建議) and the section
    structure's own numbers are allowed."""
    allowed = _numbers(json.dumps(facts, ensure_ascii=False))
    # rounding a number from the data to a whole number ("84.6 秒" ->
    # "85 秒") is not inventing one
    allowed |= {str(round(float(x))) for x in allowed if "." in x and ":" not in x}
    allowed |= {str(i) for i in range(0, max(10, rep_count + 2) + 1)}
    allowed |= {"400", "200", "100", "60", "30", "1", "2"}
    bad = []
    for token in _NUM.findall(text):
        if token in allowed:
            continue
        # "4:24" inside "4:24/km" already matched; also accept 1-decimal
        # forms of allowed integers ("15.0") and integer forms of decimals
        if token.endswith(".0") and token[:-2] in allowed:
            continue
        bad.append(token)
    return sorted(set(bad))


# ---------------------------------------------------------------- style check

_GENERIC = ("做得很好", "表現不錯", "表現很好", "繼續保持", "加油", "值得肯定", "整體而言", "總結來說", "總的來說",
            "非常棒", "很棒")


def style_problems(text: str) -> list[str]:
    """What makes a reply read like a generated report rather than a coach:
    section headings, empty praise, and no concrete next step."""
    problems = []
    if re.search(r"^\s*#", text, re.M):
        problems.append("用了標題")
    problems += [f"空泛用語「{p}」" for p in _GENERIC if p in text]
    if "下次：" not in text:
        problems.append("缺少「下次：」那一行")
    return problems


# ---------------------------------------------------------------- LLM call


def _models() -> list[str]:
    configured = os.environ.get("WORKOUT_ANALYSIS_MODELS")
    if configured:
        return [m.strip() for m in configured.split(",") if m.strip()]
    return list(_DEFAULT_MODELS)


def write_narrative(facts: dict[str, Any], *, rep_count: int) -> dict[str, Any]:
    """{text, source: "llm" | "offline", model, fallback_reason}. Never raises."""
    if groq_client.api_key() is None:
        return _offline(facts, ["未設定 GROQ_API_KEY"])
    reasons: list[str] = []
    deadline = time.monotonic() + _TOTAL_BUDGET_S
    # compact JSON: the token count is what Groq's per-minute quota meters
    data = "訓練資料（JSON）：" + chr(10) + json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
    for model in _models():
        correction = ""
        for _attempt in range(2):
            messages = [{"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": data + correction}]
            try:
                text = groq_client.chat(model, messages, deadline=deadline)
            except groq_client.GroqUnavailable as exc:
                logger.warning("workout_narrative_llm_error model=%s err=%s", model, exc)
                reasons.append(str(exc))
                break
            bad = unverified_numbers(text, facts, rep_count)
            style = style_problems(text)
            if not bad and not style:
                return {"text": text, "source": "llm", "model": model, "fallback_reason": None}
            correction = chr(10) * 2 + "注意：上一次的回覆"
            if bad:
                logger.warning("workout_narrative_unverified model=%s numbers=%s", model, bad)
                reasons.append(f"{model} 回覆含資料中沒有的數字（{', '.join(bad[:5])}）")
                correction += "用了訓練資料裡沒有的數字（" + "、".join(bad) + "），這次只能使用訓練資料中出現的數字；"
            if style:
                logger.warning("workout_narrative_style model=%s problems=%s", model, style)
                reasons.append(f"{model} 回覆不符合格式（{'、'.join(style[:3])}）")
                correction += "不符合格式：" + "、".join(style) + "。請照【格式】重寫，不要標題，最後一行以「下次：」開頭。"
        if time.monotonic() > deadline - 5:
            break
    return _offline(facts, reasons)


def _offline(facts: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    return {"text": offline_narrative(facts), "source": "offline", "model": None,
            "fallback_reason": "；".join(reasons[-3:]) or None}


# ---------------------------------------------------------------- offline template

_SEVERITY_ORDER = {"critical": 0, "warning": 1, "positive": 2, "info": 3}
_COMPARISON_CODES = {"history", "history_trend", "target", "recovery_trend"}


def offline_narrative(facts: dict[str, Any]) -> str:
    """The same shape the model is asked for: the one thing that mattered
    most today, how it compares, and one thing to do next time."""
    findings = facts["判讀結果"]
    ranked = sorted((f for f in findings if f.get("code") not in _COMPARISON_CODES),
                    key=lambda f: _SEVERITY_ORDER.get(f["severity"], 9))
    paragraphs = []
    if ranked:
        lead = ranked[0]
        paragraphs.append(f"{lead['標題']}：{lead['內容']}。")
    else:
        line = f"今天跑了 {facts['課表']}，總距離 {facts['整體']['總距離']}、總時間 {facts['整體']['總時間']}"
        if facts.get("各趟平均配速"):
            line += f"，各趟平均配速 {facts['各趟平均配速']}"
        paragraphs.append(line + "。")
    compare = [f for f in findings if f.get("code") in _COMPARISON_CODES]
    if compare:
        paragraphs.append("".join(f"{f['內容']}。" for f in compare[:2]))
    limits = [x for x in facts.get("資料限制", []) if x != "無"]
    if limits:
        paragraphs.append("資料限制：" + "；".join(limits) + "。")
    advice = next((f["建議"] for f in sorted(findings, key=lambda f: _SEVERITY_ORDER.get(f["severity"], 9))
                   if f.get("建議")), None)
    paragraphs.append("下次：" + (advice or "照今天的配速與休息再跑一次，對照每趟結束心率有沒有更低。"))
    return "\n\n".join(p.replace("。。", "。") for p in paragraphs)


def signature_label(signature: str | None, session_type: str) -> str:
    """"6x1000m" -> "6 × 1000m"; "3x(4x400m)" -> "3 組 × (4 × 400m)";
    "tempo:6.2km" -> "6.2 公里節奏跑"."""
    if not signature or signature == "continuous":
        return SESSION_TYPE_LABEL.get(session_type, "連續跑")
    if signature.startswith("tempo:"):
        return f"{signature[6:].replace('km', '')} 公里節奏跑"
    out = re.sub(r"^(\d+)x\((.*)\)$", r"\1 組 × (\2)", signature)
    out = re.sub(r"(\d+)x(\d+)", r"\1 × \2", out)
    return out.replace("s", " 秒") if re.search(r"\d+s\b", out) else out
