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

SYSTEM_PROMPT = """你是一位帶過許多中長跑選手的田徑教練，正在看選手今天的訓練紀錄，要給他一份精準、具體、像真人教練說話的分析。

【硬性規則】
1. 只能使用「訓練資料」裡出現過的數字。不要自己計算新的數字（例如自己相減算差距），需要的差距資料裡都已經算好。
2. 不要編造資料裡沒有的資訊：天氣、睡眠、飲食、傷痛、比賽目標等一律不要提。
3. 「課表要求」若標明本次不評比，就不要說選手達成或沒達成要求。
4. 「判讀結果」是已經用演算法確認過的結論。你寫的每一個判斷（例如衝太快、掉速、疲勞累積、恢復不足）都必須出自判讀結果，不可推翻、誇大，也不要自行加上判讀結果沒有的原因或結論；資料表裡的數字可以引用來佐證。severity=warning 的項目一定要提到。
5. 提到某一趟時用「第 N 趟」，並附上該趟的實際數字。
6. 「資料限制」中的項目要誠實地用一句話帶過，不要假裝有資料。
7. 不做醫療診斷。

【格式】使用繁體中文 Markdown，依序輸出以下五個段落標題（用 ###），總長約 300–450 字：
### 今日課表判讀
（一到兩句：這是什麼課表、結構與主要數據）
### 表現總評
（兩到三句：整體做得好的地方與最大的問題）
### 配速控制
（條列 2–4 點，具體到第幾趟、配速多少）
### 心率與恢復
（條列 1–3 點；資料不足就說明）
### 下次訓練建議
（條列 2–3 點，具體可執行，例如第一趟要壓在多少配速）

語氣：直接、專業、帶鼓勵，像教練在跑道邊跟選手講話，不要客套話，不要重複資料表。"""


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
            facts["強度段平均配速"] = fmt_pace(s["mean_work_pace_s_per_km"])
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
            if not bad:
                return {"text": text, "source": "llm", "model": model, "fallback_reason": None}
            logger.warning("workout_narrative_unverified model=%s numbers=%s", model, bad)
            reasons.append(f"{model} 回覆含資料中沒有的數字（{', '.join(bad[:5])}）")
            correction = (chr(10) * 2 + "注意：上一次的回覆用了訓練資料裡沒有的數字（" + "、".join(bad)
                          + "）。這次只能使用訓練資料中出現的數字，不要自行計算或估計。")
        if time.monotonic() > deadline - 5:
            break
    return _offline(facts, reasons)


def _offline(facts: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    return {"text": offline_narrative(facts), "source": "offline", "model": None,
            "fallback_reason": "；".join(reasons[-3:]) or None}


# ---------------------------------------------------------------- offline template

_PACING_CODES = {"consistency", "first_rep_fast", "fade", "progression", "held", "last_rep_kick", "target",
                 "progression_structure",
                 "within_rep_fade", "within_rep_negative", "interruption", "pyramid_pair", "km_consistency",
                 "negative_split", "positive_split"}
_HR_CODES = {"hr_drift", "near_max", "recovery", "incomplete_recovery", "decoupling", "easy_too_hard", "easy_ok",
             "hard_warmup"}


def offline_narrative(facts: dict[str, Any]) -> str:
    findings = facts["判讀結果"]
    lines = ["### 今日課表判讀"]
    intro = f"這是一堂{facts['類型']}（{facts['課表']}），{facts['紀錄方式']}，總距離 {facts['整體']['總距離']}、總時間 {facts['整體']['總時間']}"
    if facts.get("課表要求"):
        intro += f"；課表要求：{facts['課表要求']['內容']}（{facts['課表要求']['來源']}）"
    if facts.get("強度段平均配速"):
        intro += f"，強度段平均配速 {facts['強度段平均配速']}"
    lines.append(intro + "。")

    good = [f["標題"] for f in findings if f["severity"] == "positive"]
    bad = [f["標題"] for f in findings if f["severity"] in ("warning", "critical")]
    lines.append("\n### 表現總評")
    summary = []
    if good:
        summary.append("做得好的地方：" + "、".join(good[:3]) + "。")
    if bad:
        summary.append("需要調整的地方：" + "、".join(bad[:3]) + "。")
    if not summary:
        summary.append("整體表現平穩，沒有明顯的問題。")
    lines.append("".join(summary))

    def section(title: str, codes: set[str]) -> None:
        items = [f for f in findings if f.get("code") in codes]
        if not items:
            return
        lines.append(f"\n### {title}")
        for f in items:
            lines.append(f"- **{f['標題']}**：{f['內容']}")

    section("配速控制", _PACING_CODES)
    section("心率與恢復", _HR_CODES)
    others = [f for f in findings if f.get("code") not in _PACING_CODES | _HR_CODES]
    if others:
        lines.append("\n### 其他觀察")
        for f in others:
            lines.append(f"- **{f['標題']}**：{f['內容']}")

    advice = [f["建議"] for f in findings if f.get("建議") and f["severity"] in ("warning", "critical")]
    advice += [f["建議"] for f in findings if f.get("建議") and f["severity"] == "info"]
    lines.append("\n### 下次訓練建議")
    if advice:
        for a in advice[:3]:
            lines.append(f"- {a}")
    else:
        lines.append("- 維持目前的配速分配與休息節奏，下次可視狀況把強度或趟數小幅往上加。")
    limits = [x for x in facts.get("資料限制", []) if x != "無"]
    if limits:
        lines.append("\n> 資料限制：" + "；".join(limits))
    return "\n".join(lines)


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
