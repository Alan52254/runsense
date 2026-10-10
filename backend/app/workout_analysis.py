"""Coach-grade metrics and findings for one confirmed workout.

Input is the stored telemetry plus the segmentation the athlete confirmed
(warm-up / each rep / each recovery / cool-down). Everything here is
deterministic arithmetic on the recorded data -- the language model only
ever narrates these numbers (see workout_narrative.py), it never computes
or invents them.

Conventions:
- Pace is seconds per km. A rep with a confirmed nominal distance (a
  1000 m rep on a track) is paced over that distance, not over the GPS
  trace, which reads 1-5 % long on a track's bends; the GPS distance is
  reported next to it.
- Rep time excludes in-rep interruptions (auto-pause, a stop); recovery
  time is wall-clock, paused or not -- a coach times the recovery the
  athlete actually took.
- Heart-rate metrics for reps shorter than 60 s are reported but not
  interpreted: heart rate lags 20-40 s behind effort, so a 200 m rep never
  reaches its steady state.
"""

from __future__ import annotations

import copy
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Any

from app import workout_prescription
from app.workout_segmentation import Grid, MOVING_SPEED, build_grid

# ---------------------------------------------------------------- formatting


def fmt_pace(sec_per_km: float | None) -> str | None:
    if sec_per_km is None or sec_per_km <= 0 or sec_per_km > 3600:
        return None
    total = round(sec_per_km)
    return f"{total // 60}:{total % 60:02d}/km"


def fmt_duration(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    s = round(seconds)
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    if s >= 60:
        return f"{s // 60}:{s % 60:02d}"
    return f"{s} 秒"


def rep_label(seg: dict) -> str:
    if seg.get("nominal_s"):
        return f"{seg['nominal_s']} 秒"
    if seg.get("nominal_m"):
        return f"{seg['nominal_m']}m"
    return "自由距離"


# ---------------------------------------------------------------- heart rate profile

# Garmin's default heart-rate-reserve zone floors (fraction of HRR) -- used
# only when no zone boundaries came from the watch.
_DEFAULT_HRR_ZONE_TOPS = [0.50, 0.60, 0.70, 0.80, 0.90, 1.00]


@dataclass
class HrProfile:
    max_hr: int | None
    max_hr_source: str | None        # manual | device | history | age_formula
    resting_hr: int | None
    resting_hr_source: str | None    # manual | device
    zone_method: str                 # percent_hrr | percent_max_hr
    zone_tops: list[int]             # upper bound of zone 0..5 (bpm)
    history_peak_30s: int | None
    notes: list[str]

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_hr": self.max_hr,
            "max_hr_source": self.max_hr_source,
            "resting_hr": self.resting_hr,
            "resting_hr_source": self.resting_hr_source,
            "zone_method": self.zone_method,
            "zone_tops": self.zone_tops,
            "history_peak_30s": self.history_peak_30s,
            "notes": self.notes,
        }

    def zone_of(self, hr: float | None) -> int | None:
        """Garmin numbering: 0 = below zone 1, 1..5."""
        if hr is None or not self.zone_tops:
            return None
        for zone, top in enumerate(self.zone_tops):
            if hr <= top:
                return zone
        return 5

    def pct_max(self, hr: float | None) -> float | None:
        return round(hr / self.max_hr * 100, 1) if hr and self.max_hr else None

    def pct_hrr(self, hr: float | None) -> float | None:
        if not hr or not self.max_hr or not self.resting_hr or self.max_hr <= self.resting_hr:
            return None
        return round((hr - self.resting_hr) / (self.max_hr - self.resting_hr) * 100, 1)


def resolve_hr_profile(
    *,
    manual_max_hr: int | None,
    manual_resting_hr: int | None,
    device: dict[str, Any] | None,
    history_peak_30s: int | None,
    birth_year: int | None,
    on_date: date,
) -> HrProfile:
    """Max HR by the agreed priority -- the athlete's / coach's own setting,
    then the watch's setting on the day of this activity, then a robust
    peak from the athlete's own recorded history, then the Tanaka age
    formula (208 - 0.7 x age) as a labelled last resort. Zones follow the
    watch's own zone boundaries whenever the max HR came from the watch, so
    "zone 4" here means what it meant on the athlete's wrist that day."""
    device = device or {}
    notes: list[str] = []
    max_hr, max_src = None, None
    if manual_max_hr:
        max_hr, max_src = manual_max_hr, "manual"
    elif device.get("max_hr"):
        max_hr, max_src = int(device["max_hr"]), "device"
    elif history_peak_30s:
        max_hr, max_src = history_peak_30s, "history"
        notes.append("最大心率取自你歷史紀錄中 30 秒平均心率的最高值（非實驗室測量）")
    elif birth_year:
        age = on_date.year - birth_year
        max_hr, max_src = round(208 - 0.7 * age), "age_formula"
        notes.append("最大心率以 Tanaka 公式（208 − 0.7 × 年齡）估算，個體誤差約 ±10 bpm")

    resting, rest_src = None, None
    if manual_resting_hr:
        resting, rest_src = manual_resting_hr, "manual"
    elif device.get("resting_hr"):
        resting, rest_src = int(device["resting_hr"]), "device"

    method = str(device.get("hr_calc_type") or ("percent_hrr" if resting else "percent_max_hr"))
    if method not in ("percent_hrr", "percent_max_hr"):
        method = "percent_hrr" if resting else "percent_max_hr"
    device_tops = [int(x) for x in (device.get("zone_high_bounds") or [])]
    zone_tops: list[int] = []
    if max_hr:
        if device_tops and len(device_tops) == 6 and max_src == "device" and rest_src in ("device", None):
            zone_tops = device_tops
        elif device_tops and len(device_tops) == 6 and device.get("max_hr") and device.get("resting_hr") \
                and method == "percent_hrr" and resting:
            # keep the watch's own zone percentages, re-applied to the
            # overridden max / resting values
            d_max, d_rest = float(device["max_hr"]), float(device["resting_hr"])
            fracs = [(t - d_rest) / (d_max - d_rest) for t in device_tops]
            zone_tops = [round(resting + f * (max_hr - resting)) for f in fracs]
        elif method == "percent_hrr" and resting:
            zone_tops = [round(resting + f * (max_hr - resting)) for f in _DEFAULT_HRR_ZONE_TOPS]
        else:
            zone_tops = [round(f * max_hr) for f in _DEFAULT_HRR_ZONE_TOPS]
    if history_peak_30s and max_hr and history_peak_30s > max_hr + 3:
        notes.append(f"你曾記錄到 30 秒平均 {history_peak_30s} bpm，高於目前設定的最大心率 {max_hr}，建議更新設定")
    return HrProfile(max_hr, max_src, resting, rest_src, method, zone_tops, history_peak_30s, notes)


# ---------------------------------------------------------------- per-segment stats


def _mean(values: list[float]) -> float | None:
    vals = [v for v in values if v is not None]
    return statistics.fmean(vals) if vals else None


def _hr_window(g: Grid, a: int, b: int) -> list[float]:
    return [h for h in g.hr[max(0, a):min(g.n, b)] if h]


def _hr_coverage(g: Grid, a: int, b: int) -> float:
    """Share of the un-paused seconds in [a, b) that have a heart rate --
    a paused watch records nothing, which is not a sensor dropout."""
    live = [i for i in range(max(0, a), min(g.n, b)) if not g.paused[i]]
    if not live:
        return 0.0
    return sum(1 for i in live if g.hr[i]) / len(live)


def _time_at_distance(g: Grid, a: int, b: int, target: float) -> int:
    """First second in [a, b) at which cumulative distance reaches target."""
    for i in range(a, b):
        if g.d[i] >= target:
            return i
    return b


def segment_stats(g: Grid, seg: dict, index: int) -> dict[str, Any]:
    a, b = int(seg["start_s"]), int(min(seg["end_s"], g.n))
    elapsed = max(0, b - a)
    interruptions = [(int(s), int(e)) for s, e in seg.get("interruptions", []) or []]
    paused = sum(1 for i in range(a, b) if g.paused[i])
    interrupted = sum(e - s for s, e in interruptions)
    gps_m = g.dist(a, b) - sum(g.dist(s, e) for s, e in interruptions)
    role = seg["role"]
    if role == "work":
        in_interruption = {i for s, e in interruptions for i in range(s, e)}
        stray_pause = sum(1 for i in range(a, b) if g.paused[i] and i not in in_interruption)
        moving = max(1, elapsed - interrupted - stray_pause)
    else:
        moving = max(0, elapsed - paused)
    distance = float(seg["nominal_m"]) if role == "work" and seg.get("nominal_m") else gps_m
    pace = moving / (distance / 1000) if distance > 20 and moving > 0 else None

    hrs = _hr_window(g, a, b)
    coverage = _hr_coverage(g, a, b)
    stats: dict[str, Any] = {
        "index": index,
        "role": role,
        "start_s": a,
        "end_s": b,
        "elapsed_s": elapsed,
        "moving_s": moving,
        "gps_distance_m": round(gps_m, 1),
        "distance_m": round(distance, 1),
        "nominal_m": seg.get("nominal_m"),
        "nominal_s": seg.get("nominal_s"),
        "pace_s_per_km": round(pace, 1) if pace else None,
        "avg_hr": round(statistics.fmean(hrs)) if hrs and coverage >= 0.5 else None,
        "max_hr": max(hrs) if hrs and coverage >= 0.5 else None,
        "hr_coverage": round(coverage, 2),
        "avg_cadence": None,
        "interruptions_s": interrupted,
    }
    cads = [c for c in g.cad[a:b] if c and c > 100]
    if cads:
        stats["avg_cadence"] = round(statistics.fmean(cads))

    if role == "work":
        end_hrs = _hr_window(g, b - 10, b)
        start_hrs = _hr_window(g, a, a + 5)
        stats["hr_end"] = round(statistics.fmean(end_hrs)) if end_hrs else None
        stats["hr_start"] = round(statistics.fmean(start_hrs)) if start_hrs else None
        # within-rep pacing: time for the first vs second half of the GPS
        # distance, only for reps long enough for GPS to resolve halves
        if elapsed >= 60 and gps_m >= 300 and not interruptions:
            mid = _time_at_distance(g, a, b, g.d[a] + gps_m / 2)
            t1, t2 = mid - a, b - mid
            if t1 > 0 and t2 > 0:
                half_m = gps_m / 2 / 1000
                stats["first_half_pace"] = round(t1 / half_m, 1)
                stats["second_half_pace"] = round(t2 / half_m, 1)
    if role in ("rest", "set_rest"):
        moving_speed = gps_m / elapsed if elapsed else 0
        stats["rest_type"] = ("standing" if moving_speed < 0.6 else "walking" if moving_speed < MOVING_SPEED
                              else "jogging")
        # HR recovery (HRR60): from the peak to 60 s after it. A wrist
        # optical sensor often lags or jumps for 10-25 s after the athlete
        # stops, so the peak is searched over the first 30 s of the
        # recovery, not taken at the stop itself
        window = [i for i in range(max(0, a - 3), min(b, a + 30)) if g.hr[i] and not g.paused[i]]
        if window:
            peak_t = max(window, key=lambda i: g.hr[i])
            end_t = min(peak_t + 60, b - 1)
            span = range(peak_t, end_t + 1)
            if (end_t - peak_t >= 40 and not any(g.paused[i] for i in span)
                    and _hr_coverage(g, peak_t, end_t + 1) >= 0.6):
                later = _hr_window(g, end_t - 2, end_t + 1)
                if later:
                    stats["hr_peak_into_rest"] = g.hr[peak_t]
                    stats["hr_drop"] = round(g.hr[peak_t] - statistics.fmean(later))
                    stats["hr_drop_window_s"] = end_t - peak_t
        end_hrs = _hr_window(g, b - 5, b)
        stats["hr_end"] = round(statistics.fmean(end_hrs)) if end_hrs else None
    return stats


# ---------------------------------------------------------------- helpers


def _slope(ys: list[float]) -> float:
    """Least-squares slope of ys against 0..n-1."""
    n = len(ys)
    if n < 2:
        return 0.0
    mx = (n - 1) / 2
    my = statistics.fmean(ys)
    num = sum((i - mx) * (y - my) for i, y in enumerate(ys))
    den = sum((i - mx) ** 2 for i in range(n))
    return num / den if den else 0.0


def _thirds(values: list[float]) -> tuple[float, float]:
    k = max(1, len(values) // 3)
    return statistics.fmean(values[:k]), statistics.fmean(values[-k:])


def _per_rep_seconds(pace_delta_s_per_km: float, distance_m: float) -> float:
    return pace_delta_s_per_km * distance_m / 1000


def _finding(code: str, severity: str, title: str, detail: str, advice: str | None = None,
             **evidence: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, "title": title, "detail": detail,
            "advice": advice, "evidence": evidence}


def _reps_phrase(indices: list[int]) -> str:
    return "、".join(f"第 {i} 趟" for i in indices)


# ---------------------------------------------------------------- main entry


def analyse_workout(
    tele: dict,
    segments: list[dict],
    *,
    session_type: str,
    target_pace_s_per_km: float | None,
    hr: HrProfile,
    easy_speed: float | None,
    history: list[dict] | None = None,
    prescription: dict | None = None,
    linked: dict | None = None,
) -> dict[str, Any]:
    """Return {segments, reps, rests, summary, findings, data_notes}.

    session_type: intervals | tempo | easy | long | race | other.
    history: earlier sessions of the same structure, newest first, each
    {date, signature, mean_pace_s_per_km, mean_rep_hr, rep_count}.
    prescription: what was prescribed (app/workout_prescription.py); when
    None one is inferred from the run -- for structure only, never graded.
    linked: {"warmup": {...}, "cooldown": {...}} separately recorded
    activities just before / after this one."""
    g = build_grid(tele["samples"], tele.get("timer_events") or [])
    stats = [segment_stats(g, s, i) for i, s in enumerate(segments)]
    reps = [s for s in stats if s["role"] == "work"]
    for k, r in enumerate(reps, 1):
        r["rep_number"] = k
    rests = [s for s in stats if s["role"] in ("rest", "set_rest")]
    findings: list[dict[str, Any]] = []
    data_notes: list[str] = []

    total_elapsed = g.n
    total_distance = g.d[-1] if g.n else 0.0
    moving_s = sum(1 for i in range(g.n) if not g.paused[i] and g.v[i] >= MOVING_SPEED)
    all_hr = [h for h in g.hr if h]
    hr_cov = _hr_coverage(g, 0, g.n)
    if hr_cov < 0.8:
        data_notes.append(f"這次紀錄只有 {round(hr_cov * 100)}% 的時間有心率訊號，心率相關判讀僅供參考")
    if tele.get("sub_sport") not in ("track", "treadmill"):
        data_notes.append("非手錶操場模式：GPS 距離在彎道多會偏長 1–5%，已設定標準距離的趟次以標準距離計算配速")

    zone_seconds = [0] * 6
    for h in all_hr:
        z = hr.zone_of(h)
        if z is not None:
            zone_seconds[z] += 1

    summary: dict[str, Any] = {
        "session_type": session_type,
        "total_distance_m": round(total_distance),
        "total_elapsed_s": total_elapsed,
        "moving_s": moving_s,
        "avg_hr": round(statistics.fmean(all_hr)) if all_hr else None,
        "max_hr": max(all_hr) if all_hr else None,
        "zone_seconds": zone_seconds,
        "hr_profile": hr.as_dict(),
        "target_pace_s_per_km": target_pace_s_per_km,
        "sub_sport": tele.get("sub_sport"),
    }

    prescription_meta = None
    if reps and session_type in ("intervals", "tempo", "race", "other"):
        prescription_meta = _apply_prescription(reps, rests, session_type, prescription,
                                                target_pace_s_per_km, summary, data_notes)
        _interval_findings(g, stats, reps, rests, hr, prescription_meta, findings, summary, data_notes)
    if session_type in ("easy", "long", "tempo", "race") or not reps:
        _continuous_findings(g, stats, hr, session_type, findings, summary, target_pace_s_per_km, reps)
    _warmup_cooldown_findings(stats, reps, hr, findings, linked)
    if history:
        _history_findings(summary, history, findings)
    if hr.max_hr is None:
        data_notes.append("沒有可用的最大心率設定，心率強度百分比無法計算")

    order = {"critical": 0, "warning": 1, "positive": 2, "info": 3}
    findings.sort(key=lambda f: order.get(f["severity"], 9))
    return {"segments": stats, "reps": reps, "rests": rests, "summary": summary,
            "findings": findings, "data_notes": data_notes}


# ---------------------------------------------------------------- prescription


def _apply_prescription(reps: list[dict], rests: list[dict], session_type: str, prescription: dict | None,
                        single_target: float | None, summary: dict, notes: list[str]) -> dict:
    """Attach each rep's prescribed target (target_pace_s_per_km /
    target_label) and record where the prescription came from."""
    inferred = workout_prescription.infer(reps, rests, "tempo" if session_type == "tempo" else "intervals")
    if prescription is None and single_target:
        prescription = {"source": "athlete_text", "raw_text": None,
                        "blocks": [{"reps": len(reps), "distance_m": None, "duration_s": None,
                                    "targets_s_per_km": [single_target], "rest_s": None}]}
    if prescription is None:
        prescription = inferred
    else:
        prescription = workout_prescription.fill_missing_targets(copy.deepcopy(prescription), inferred)
    if not prescription:
        return {"gradable": False}
    alignment = workout_prescription.align(prescription, reps)
    source = prescription.get("source", "inferred")
    gradable = source in workout_prescription.GRADABLE_SOURCES and not alignment["blocking"]
    if alignment["blocking"]:
        notes.append("課表要求與實際紀錄對不起來：" + "；".join(alignment["issues"]) + "，本次不以要求評分")
    else:
        for r, want in zip(reps, alignment["per_rep"]):
            if not want:
                continue
            # a rep GPS measured off a standard distance (200 m read as
            # 177 m on a track's bends) is paced over the prescribed one
            if want.get("distance_m") and not r.get("nominal_m") and r["moving_s"]:
                notes.append(f"第 {r['rep_number']} 趟 GPS 量到 {round(r['gps_distance_m'])} m，"
                             f"依課表以 {want['distance_m']} m 計算配速")
                r["nominal_m"] = want["distance_m"]
                r["distance_m"] = float(want["distance_m"])
                r["pace_s_per_km"] = round(r["moving_s"] / (want["distance_m"] / 1000), 1)
            if want.get("target_pace_s_per_km"):
                r["target_pace_s_per_km"] = want["target_pace_s_per_km"]
                r["target_label"] = want["target_label"]
                r["target_mode"] = want.get("target_mode", "exact")
        if alignment["completed"] < alignment["prescribed"]:
            notes.append(f"這堂只完成 {alignment['completed']}/{alignment['prescribed']} 趟，已完成的趟次照要求評分")
    summary["prescription"] = {
        **prescription,
        "source_label": workout_prescription.SOURCE_LABEL.get(source, source),
        "gradable": gradable,
        "issues": alignment["issues"],
        "completed": alignment["completed"],
        "prescribed": alignment["prescribed"],
    }
    return {"gradable": gradable, "source": source, "completed": alignment["completed"],
            "prescribed": alignment["prescribed"]}


# ---------------------------------------------------------------- intervals


def _interval_findings(g: Grid, stats: list[dict], reps: list[dict], rests: list[dict], hr: HrProfile,
                       prescription_meta: dict | None, findings: list[dict], summary: dict,
                       notes: list[str]) -> None:
    paced = [r for r in reps if r["pace_s_per_km"]]
    work_time = sum(r["moving_s"] for r in reps)
    work_dist = sum(r["distance_m"] for r in reps)
    summary.update({
        "rep_count": len(reps),
        "work_distance_m": round(work_dist),
        "work_time_s": work_time,
        "mean_work_pace_s_per_km": round(work_time / (work_dist / 1000), 1) if work_dist > 0 else None,
        "mean_rep_hr": round(statistics.fmean([r["avg_hr"] for r in reps if r["avg_hr"]]))
        if any(r["avg_hr"] for r in reps) else None,
    })
    if len(paced) < 2:
        return

    # with a prescription every rep is judged against its own target, which
    # makes a 90/85/80 progression or a 2000-1000-800 at three paces one
    # comparable series; without one, the largest block of one distance is
    # the series
    if all(r.get("target_pace_s_per_km") for r in paced):
        block = paced
        _target_relative_findings(block, findings, summary, prescription_meta or {})
    else:
        block = _nominal_block_findings(paced, findings, summary)
        if block is None:
            return

    # within-rep pacing
    halves = [(r["first_half_pace"], r["second_half_pace"]) for r in block
              if r.get("first_half_pace") and r.get("second_half_pace")]
    if len(halves) >= 2:
        diffs = [(s - f) / ((s + f) / 2) * 100 for f, s in halves]  # + = second half slower
        mean_diff = statistics.fmean(diffs)
        summary["within_rep_split_pct"] = round(mean_diff, 1)
        if mean_diff >= 3.0:
            findings.append(_finding(
                "within_rep_fade", "warning", "每趟前半段太快",
                f"每趟後半段平均比前半段慢 {mean_diff:.1f}%（GPS 估算），出發太衝、後段撐著跑",
                "起跑後前 100m 刻意放鬆，用前半段建立節奏，後半段再加壓；在操場可以用 200m 分段時間檢查",
                split_pct=round(mean_diff, 1)))
        elif mean_diff <= -2.0:
            findings.append(_finding(
                "within_rep_negative", "positive", "每趟後半段更快",
                f"每趟後半段平均比前半段快 {abs(mean_diff):.1f}%（GPS 估算），趟內配速分配成熟",
                None, split_pct=round(mean_diff, 1)))

    # interruptions
    for r in reps:
        if r["interruptions_s"]:
            findings.append(_finding(
                "interruption", "info", f"第 {r['rep_number']} 趟中途停下",
                f"第 {r['rep_number']} 趟中途停了 {r['interruptions_s']} 秒，該趟配速已扣除停下時間計算",
                None, seconds=r["interruptions_s"]))

    # heart rate across reps (only reps long enough to reach steady state)
    long_reps = [r for r in block if r["moving_s"] >= 60 and r.get("hr_end")]
    if len(long_reps) >= 3:
        ends = [r["hr_end"] for r in long_reps]
        hr_slope = _slope(ends)
        pace_slope = _slope([r["pace_s_per_km"] for r in long_reps])
        summary["rep_end_hr"] = ends
        if hr_slope >= 1.0 and pace_slope >= -0.3:
            findings.append(_finding(
                "hr_drift", "info" if hr_slope < 2.0 else "warning", "同樣配速下心率逐趟上升",
                f"每趟結束心率從第 {long_reps[0]['rep_number']} 趟的 {ends[0]} bpm 上升到第 {long_reps[-1]['rep_number']} 趟的 "
                f"{ends[-1]} bpm（平均每趟 +{hr_slope:.1f} bpm），配速並沒有變快，代表疲勞在累積"
                "；間歇中心率逐趟上升是正常反應，重點在幅度",
                None if hr_slope < 2.0 else "上升幅度偏大：下次同課表可把休息延長 15–30 秒，"
                "並回頭檢查前幾天的訓練量與睡眠是否足夠",
                slope_bpm_per_rep=round(hr_slope, 1)))
        peak = max(r["max_hr"] for r in long_reps if r["max_hr"])
        pct = hr.pct_max(peak)
        if pct is not None:
            summary["peak_rep_hr"] = peak
            summary["peak_rep_hr_pct_max"] = pct
            if pct >= 95:
                findings.append(_finding(
                    "near_max", "info", "強度接近最大心率",
                    f"趟中最高心率 {peak} bpm，達最大心率 {hr.max_hr} 的 {pct:.0f}%",
                    None, peak=peak, pct=pct))
    elif block and block[0]["moving_s"] < 60:
        notes.append("每趟不到 60 秒，心率來不及反應到該強度的穩定值，本次不以每趟心率判斷強度")

    # recovery
    drops = [r for r in rests if r.get("hr_drop") is not None and r["role"] == "rest"]
    if len(drops) >= 2:
        vals = [r["hr_drop"] for r in drops]
        mean_drop = statistics.fmean(vals)
        types = {r["rest_type"] for r in drops}
        summary["mean_hr_drop"] = round(mean_drop)
        jog = "jogging" in types
        summary["recovery_jogging"] = jog
        # No fixed "good / slow" cut-off: a 60 s heart-rate drop carries ~25%
        # typical error and differs widely between athletes, and a faster drop
        # can also come with overreaching (docs/research/
        # interval-analysis-evidence-2026.md). It is only judged against this
        # athlete's own earlier sessions of the same workout, in
        # _history_findings.
        sev, title = "info", "休息時的心率下降"
        measured = f"（以 {len(drops)} 次手錶未暫停、可量測的休息計算）" if len(drops) < len(rests) else ""
        findings.append(_finding(
            "recovery", sev, title,
            (f"休息時心率從峰值起 60 秒內平均下降 {mean_drop:.0f} bpm{measured}" if round(mean_drop) > 0 else
             f"休息時心率從峰值起 60 秒內沒有下降，反而平均上升 {abs(mean_drop):.0f} bpm{measured}")
            + "（手腕光學心率在停下後常延遲或跳動，已從休息前 30 秒內的最高值起算）"
            + ("；慢跑恢復時心率本來就降得比較少" if jog else ""),
            None, mean_drop=round(mean_drop)))
    if any(r.get("paused_during_rest") for r in rests) and len(drops) < 2:
        notes.append("休息時手錶有暫停，暫停期間沒有心率紀錄，無法計算休息中的心率下降")
    starts = [r["hr_start"] for r in block if r.get("hr_start")]
    if len(starts) >= 4 and _slope(starts) >= 1.5:
        findings.append(_finding(
            "incomplete_recovery", "info", "起跑心率逐趟升高",
            f"每趟起跑時的心率從 {starts[0]} bpm 升到 {starts[-1]} bpm，休息越到後面越不夠",
            "如果後段配速也掉了，代表休息長度不足以支撐這個強度", slope=round(_slope(starts), 1)))

    # rest discipline
    rest_durs = [r["elapsed_s"] for r in rests if r["role"] == "rest"]
    if len(rest_durs) >= 3:
        rmean = statistics.fmean(rest_durs)
        rcv = statistics.pstdev(rest_durs) / rmean * 100 if rmean else 0
        rslope = _slope(rest_durs)
        summary["rest_mean_s"] = round(rmean)
        summary["rest_cv_pct"] = round(rcv)
        if rslope >= 10 and rest_durs[-1] - rest_durs[0] >= 30:
            fade_p = summary.get("block_trend_s_per_km_per_rep", 0)
            findings.append(_finding(
                "rest_creep", "warning" if fade_p <= 0.5 else "info", "休息時間越拉越長",
                f"休息從 {fmt_duration(rest_durs[0])} 拉長到 {fmt_duration(rest_durs[-1])}"
                + ("，配速是靠延長休息才撐住的" if fade_p <= 0.5 else ""),
                "間歇的訓練效果有一部分來自固定的休息長度；休息請計時，跟課表一致",
                first=rest_durs[0], last=rest_durs[-1]))
        elif rcv >= 25:
            findings.append(_finding(
                "rest_irregular", "info", "休息長度不一致",
                f"休息時間平均 {fmt_duration(rmean)}，但長短差異達 {rcv:.0f}%",
                "固定休息長度，比較得出每趟真實的表現差異", cv=round(rcv)))

    # cadence fatigue
    cads = [r["avg_cadence"] for r in block if r.get("avg_cadence")]
    if len(cads) >= 4:
        c1, c3 = _thirds(cads)
        drop = (c1 - c3) / c1 * 100
        if drop >= 3:
            findings.append(_finding(
                "cadence_drop", "info", "後段步頻下降",
                f"步頻從前段平均 {c1:.0f} 步/分降到後段 {c3:.0f} 步/分（-{drop:.1f}%），疲勞時步幅撐不住、步頻也掉",
                "後段專注在擺臂與快速觸地，維持步頻", drop_pct=round(drop, 1)))


def _nominal_block_findings(paced: list[dict], findings: list[dict], summary: dict) -> list[dict] | None:
    """No prescription: consistency and trend over the largest block of
    reps of one distance. Returns that block, or None for a pyramid /
    mixed session (repeated distances are then compared pairwise)."""
    # the consistency / trend analysis runs on the largest block of reps of
    # one prescribed distance (a pyramid's 800 up and 800 down are compared
    # with each other, never with its 400s)
    groups: dict[Any, list[dict]] = {}
    for r in paced:
        key = r.get("nominal_m") or (f"{r['nominal_s']}s" if r.get("nominal_s") else None)
        groups.setdefault(key, []).append(r)
    main_key, block = max(groups.items(), key=lambda kv: (len(kv[1]), kv[0] is not None))
    label = rep_label(block[0]) if main_key is not None else "各趟"
    summary["main_block"] = {"label": label, "rep_numbers": [r["rep_number"] for r in block]}
    distance_for_time = block[0]["nominal_m"] or statistics.fmean(r["distance_m"] for r in block)

    if len(groups) > 1 and len(block) < 3:
        # pyramid / mixed session: compare repeated distances pairwise
        for key, grp in groups.items():
            if key is None or len(grp) < 2:
                continue
            p = [r["pace_s_per_km"] for r in grp]
            spread = max(p) - min(p)
            dist = grp[0]["nominal_m"] or 0
            findings.append(_finding(
                "pyramid_pair", "positive" if spread / statistics.fmean(p) <= 0.02 else "info",
                f"{rep_label(grp[0])} 前後對照",
                f"{_reps_phrase([r['rep_number'] for r in grp])} 的配速分別是 "
                + " / ".join(fmt_pace(x) for x in p)
                + (f"，同距離前後差 {_per_rep_seconds(spread, dist):.1f} 秒" if dist else ""),
                spread_s_per_km=round(spread, 1)))
        return None

    paces = [r["pace_s_per_km"] for r in block]
    n = len(paces)
    mean_p = statistics.fmean(paces)
    cv = statistics.pstdev(paces) / mean_p * 100
    fastest = min(block, key=lambda r: r["pace_s_per_km"])
    slowest = max(block, key=lambda r: r["pace_s_per_km"])
    spread = slowest["pace_s_per_km"] - fastest["pace_s_per_km"]
    spread_rep_s = _per_rep_seconds(spread, distance_for_time)
    summary.update({
        "block_mean_pace_s_per_km": round(mean_p, 1),
        "block_cv_pct": round(cv, 1),
        "block_spread_s_per_km": round(spread, 1),
        "block_spread_per_rep_s": round(spread_rep_s, 1),
    })

    if n >= 3:
        if cv <= 1.0:
            sev, title = "positive", "配速控制極穩定"
        elif cv <= 2.0:
            sev, title = "positive", "配速穩定"
        elif cv <= 3.5:
            sev, title = "info", "配速有起伏"
        else:
            sev, title = "warning", "每趟配速差異太大"
        findings.append(_finding(
            "consistency", sev, title,
            f"{n} 趟 {label} 平均 {fmt_pace(mean_p)}，變異係數 {cv:.1f}%；最快第 {fastest['rep_number']} 趟 "
            f"{fmt_pace(fastest['pace_s_per_km'])}、最慢第 {slowest['rep_number']} 趟 {fmt_pace(slowest['pace_s_per_km'])}，"
            f"每趟時間最多差 {spread_rep_s:.1f} 秒",
            None if sev == "positive" else "把每趟的目標分段時間（例如每 200m 或每圈）先算好，跑的時候按圈對時間，比憑感覺穩定得多",
            cv_pct=round(cv, 1), spread_per_rep_s=round(spread_rep_s, 1)))

    # first rep
    if n >= 3:
        others = statistics.fmean(paces[1:])
        delta = (others - paces[0]) / others * 100  # + = first rep faster
        later_fade = _thirds(paces[1:])[1] - _thirds(paces[1:])[0] if n >= 4 else 0
        if delta >= 2.0:
            findings.append(_finding(
                "first_rep_fast", "warning" if (delta >= 3.0 or later_fade > 0) else "info", "第一趟衝太快",
                f"第 1 趟 {fmt_pace(paces[0])}，比其餘各趟平均 {fmt_pace(others)} 快 {delta:.1f}%"
                f"（約 {_per_rep_seconds(others - paces[0], distance_for_time):.1f} 秒）",
                "第一趟刻意壓在目標配速或稍慢 1–2 秒，讓身體進入狀態；第一趟衝快通常會讓後段付出更多代價",
                delta_pct=round(delta, 1)))

    # trend: fade / progression
    if n >= 4:
        first_third, last_third = _thirds(paces)
        change = (last_third - first_third) / first_third * 100  # + = slower at the end
        slope = _slope(paces)
        summary["block_trend_s_per_km_per_rep"] = round(slope, 2)
        if change >= 2.0:
            findings.append(_finding(
                "fade", "warning", "後段掉速",
                f"後 1/3 趟數平均 {fmt_pace(last_third)}，比前 1/3 的 {fmt_pace(first_third)} 慢 {change:.1f}%",
                "下次前段每趟收 1–2 秒，把力氣留到後段；如果最後幾趟無法維持，可把趟數減 1–2 趟換取品質",
                change_pct=round(change, 1)))
        elif change <= -1.5:
            findings.append(_finding(
                "progression", "positive", "後段越跑越快",
                f"後 1/3 趟數平均 {fmt_pace(last_third)}，比前 1/3 的 {fmt_pace(first_third)} 快 {abs(change):.1f}%，"
                "配速分配由保守到積極",
                None, change_pct=round(change, 1)))
        elif abs(change) < 1.0 and cv <= 2.0:
            findings.append(_finding(
                "held", "positive", "從頭到尾維持住配速",
                f"前 1/3 平均 {fmt_pace(first_third)}，後 1/3 平均 {fmt_pace(last_third)}，差距不到 1%",
                None, change_pct=round(change, 1)))
        # last rep kick
        if n >= 4:
            rest_mean = statistics.fmean(paces[:-1])
            kick = (rest_mean - paces[-1]) / rest_mean * 100
            if kick >= 2.0:
                findings.append(_finding(
                    "last_rep_kick", "info", "最後一趟明顯加速",
                    f"最後一趟 {fmt_pace(paces[-1])}，比前面平均快 {kick:.1f}%，代表前面幾趟其實還有餘力",
                    "若課表目的是穩定配速，前面幾趟可以再積極一點；若目的是練後段加速，這樣的安排是對的",
                    kick_pct=round(kick, 1)))

    return block


def _groups_by_target(block: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    for r in block:
        if (groups and round(groups[-1][0]["target_pace_s_per_km"], 1) == round(r["target_pace_s_per_km"], 1)
                and groups[-1][0].get("nominal_m") == r.get("nominal_m")):
            groups[-1].append(r)
        else:
            groups.append([r])
    return groups


def _rep_time_vs_target(r: dict) -> tuple[float, float] | None:
    """(actual, target) seconds over the rep's distance."""
    d = r.get("nominal_m") or r.get("distance_m")
    if not d:
        return None
    return r["pace_s_per_km"] * d / 1000, r["target_pace_s_per_km"] * d / 1000


def _group_range(g: list[dict]) -> str:
    a, b = g[0]["rep_number"], g[-1]["rep_number"]
    return f"第 {a} 趟" if a == b else f"第 {a}–{b} 趟"


def _fast_slow(dev: float) -> str:
    return f"{'慢' if dev > 0 else '快'} {abs(dev):.1f}%"


def _target_relative_findings(block: list[dict], findings: list[dict], summary: dict, meta: dict) -> None:
    """Every rep against its own prescribed target; dev = % slower (+) or
    faster (-) than that target. Grading against the target happens only
    for a real prescription (coach / athlete / activity name): an inferred
    one is derived from this very run and would grade it against itself."""
    gradable = bool(meta.get("gradable"))
    devs = [(r["pace_s_per_km"] - r["target_pace_s_per_km"]) / r["target_pace_s_per_km"] * 100 for r in block]
    for r, d in zip(block, devs):
        r["target_dev_pct"] = round(d, 1)
        tv = _rep_time_vs_target(r)
        if tv:
            r["target_dev_s"] = round(tv[0] - tv[1], 1)
    n = len(block)
    groups = _groups_by_target(block)
    sd = statistics.pstdev(devs)
    summary.update({
        "target_dev_sd_pct": round(sd, 1),
        "target_mean_dev_pct": round(statistics.fmean(devs), 1),
        "block_cv_pct": round(sd, 1),
        "prescription_groups": [{"reps": [r["rep_number"] for r in g_], "target_label": g_[0].get("target_label"),
                                 "mean_dev_pct": round(statistics.fmean(r["target_dev_pct"] for r in g_), 1)}
                                for g_ in groups],
    })
    worst = max(block, key=lambda r: abs(r["target_dev_pct"]))

    if n >= 3:
        if sd <= 1.0:
            sev, title = "positive", "每趟都穩穩貼著自己的目標"
        elif sd <= 2.0:
            sev, title = "positive", "相對目標的配速穩定"
        elif sd <= 3.5:
            sev, title = "info", "相對目標的配速有起伏"
        else:
            sev, title = "warning", "每趟離目標的差距忽大忽小"
        findings.append(_finding(
            "consistency", sev, title,
            f"{n} 趟相對各自目標的偏差，標準差 {sd:.1f}%；離目標最遠的是第 {worst['rep_number']} 趟"
            f"（{fmt_pace(worst['pace_s_per_km'])}，目標 {worst.get('target_label')}，{_fast_slow(worst['target_dev_pct'])}）",
            None if sev == "positive" else "把每趟的目標分段時間（例如每 200m）先算好，按圈對時間跑",
            sd_pct=round(sd, 1)))

    if len(groups) > 1 and not gradable:
        findings.append(_finding(
            "progression_structure", "info", "分段漸速的結構",
            "這堂的配速分成 " + " → ".join(f"{_group_range(g_)}約 {g_[0].get('target_label')}" for g_ in groups)
            + "（系統依實際配速推估，不是教練實際設定；若當天不是刻意漸速，代表你越跑越快）",
            "到「課表要求」填入教練實際開的課表，分析就能逐趟比對要求"))

    if n >= 3:
        others = statistics.fmean(devs[1:])
        delta = others - devs[0]  # + = first rep further ahead of its target than the rest
        if delta >= 2.0:
            findings.append(_finding(
                "first_rep_fast", "warning" if delta >= 3.0 else "info", "第一趟衝太快",
                f"第 1 趟 {fmt_pace(block[0]['pace_s_per_km'])}，相對目標 {block[0].get('target_label')} "
                f"{_fast_slow(devs[0])}；其餘各趟平均相對目標{_fast_slow(others)}",
                "第一趟刻意壓在目標配速或稍慢 1–2 秒，讓身體進入狀態；第一趟衝快通常會讓後段付出更多代價",
                delta_pct=round(delta, 1)))
    if n >= 4:
        first_third, last_third = _thirds(devs)
        change = last_third - first_third  # + = falling behind the targets
        summary["block_trend_s_per_km_per_rep"] = round(
            _slope([r["pace_s_per_km"] - r["target_pace_s_per_km"] for r in block]), 2)
        if change >= 2.0:
            findings.append(_finding(
                "fade", "warning", "後段跟不上目標",
                f"前 1/3 趟數平均相對目標{_fast_slow(first_third)}，後 1/3 變成{_fast_slow(last_third)}",
                "下次前段每趟收 1–2 秒，把力氣留到後段；若最後幾趟無法維持，可把趟數減 1–2 趟換取品質",
                change_pct=round(change, 1)))
        elif change <= -1.5:
            findings.append(_finding(
                "progression", "positive" if gradable else "info", "越到後段越超前目標",
                f"前 1/3 趟數平均相對目標{_fast_slow(first_third)}，後 1/3 變成{_fast_slow(last_third)}",
                "代表前面幾趟還有餘力；若課表要的是穩定配速，前段可以再積極一點" if gradable else None,
                change_pct=round(change, 1)))
        elif abs(change) < 1.0 and sd <= 2.0:
            findings.append(_finding(
                "held", "positive", "從頭到尾維持住目標節奏",
                f"前 1/3 與後 1/3 相對目標的差距只差 {abs(change):.1f}%", None, change_pct=round(change, 1)))

    if not gradable:
        return
    lines, within_total = [], 0
    max_mode = all(r.get("target_mode") == "max" for r in block)

    def met(r: dict) -> bool:
        return r["target_dev_pct"] <= 1.5 if r.get("target_mode") == "max" else abs(r["target_dev_pct"]) <= 1.5

    for g_ in groups:
        within_total += sum(1 for r in g_ if met(r))
        mean_dev = statistics.fmean(r["target_dev_pct"] for r in g_)
        tvs = [_rep_time_vs_target(r) for r in g_]
        if all(tvs) and (g_[0].get("nominal_m") or 0) <= 600 and g_[0].get("nominal_m"):
            actual = statistics.fmean(t[0] for t in tvs)
            target_s = tvs[0][1]
            within_word = "內" if g_[0].get("target_mode") == "max" else ""
            lines.append(f"{_group_range(g_)}要求 {target_s:.0f} 秒{within_word}，實際平均 {actual:.1f} 秒"
                         f"（{'慢' if actual > target_s else '快'} {abs(actual - target_s):.1f} 秒）")
        else:
            actual_p = statistics.fmean(r["pace_s_per_km"] for r in g_)
            lines.append(f"{_group_range(g_)}要求 {fmt_pace(g_[0]['target_pace_s_per_km'])}"
                         f"{'內' if g_[0].get('target_mode') == 'max' else ''}，"
                         f"實際平均 {fmt_pace(actual_p)}（{_fast_slow(mean_dev)}）")
    mean_dev = statistics.fmean(devs)
    incomplete = meta.get("completed", n) < meta.get("prescribed", n)
    done = f"（只完成 {meta.get('completed')}/{meta.get('prescribed')} 趟）" if incomplete else ""
    if max_mode:
        slow = [r for r in block if not met(r)]
        if not slow:
            sev, title, adv = "positive", "每趟都在要求以內", None
        elif len(slow) <= max(1, n // 4):
            sev, title, adv = ("info", "大多在要求以內",
                               f"{_reps_phrase([r['rep_number'] for r in slow])}超出要求，留意是哪個階段開始撐不住")
        else:
            sev, title, adv = ("warning", "多趟超出要求",
                               "要求是上限，超出的趟數偏多；先確認休息是否照課表，若連續幾次都超出，跟教練討論調整")
        findings.append(_finding(
            "target", sev, title + done,
            "；".join(lines) + f"。{n} 趟中有 {within_total} 趟在要求以內（要求是上限，跑更快也算達標）",
            adv, mean_dev_pct=round(mean_dev, 1), within=within_total))
        return
    if mean_dev <= -2.0:
        sev, title, adv = ("warning", "比課表要求快太多",
                           "課表的訓練目的建立在要求的配速上，跑太快會變成另一種刺激、累積額外疲勞，下次請貼著要求跑")
    elif mean_dev >= 2.0:
        sev, title, adv = ("warning", "未達課表要求",
                           "先檢查睡眠與前幾天的訓練量；若連續幾次都達不到，要求的配速可能需要跟教練討論下修")
    else:
        sev, title, adv = "positive", "貼近課表要求", None
    findings.append(_finding(
        "target", sev, title + done,
        "；".join(lines) + f"。{n} 趟中有 {within_total} 趟落在要求 ±1.5% 以內",
        adv, mean_dev_pct=round(mean_dev, 1), within=within_total))


# ---------------------------------------------------------------- continuous


def _km_splits(g: Grid, a: int, b: int) -> list[dict[str, Any]]:
    splits = []
    start_d = g.d[a]
    next_mark = start_d + 1000
    last_t = a
    moving_since = 0
    for i in range(a, b):
        if not g.paused[i]:
            moving_since += 1
        if g.d[i] >= next_mark:
            hrs = _hr_window(g, last_t, i)
            splits.append({"km": len(splits) + 1, "time_s": moving_since,
                           "pace_s_per_km": float(moving_since),
                           "avg_hr": round(statistics.fmean(hrs)) if hrs else None})
            next_mark += 1000
            last_t = i
            moving_since = 0
    return splits


def _continuous_findings(g: Grid, stats: list[dict], hr: HrProfile, session_type: str, findings: list[dict],
                         summary: dict, target: float | None, reps: list[dict]) -> None:
    # the stretch to analyse: the tempo rep, or the whole run
    if reps and session_type == "tempo" and len(reps) == 1:
        a, b = reps[0]["start_s"], reps[0]["end_s"]
    else:
        a, b = 0, g.n
    splits = _km_splits(g, a, b)
    summary["km_splits"] = splits
    if len(splits) < 2:
        return
    paces = [s["pace_s_per_km"] for s in splits]
    mean_p = statistics.fmean(paces)
    cv = statistics.pstdev(paces) / mean_p * 100
    half = len(paces) // 2
    first, second = statistics.fmean(paces[:half]), statistics.fmean(paces[half:])
    split_pct = (second - first) / first * 100
    summary.update({"split_mean_pace_s_per_km": round(mean_p, 1), "split_cv_pct": round(cv, 1),
                    "second_half_vs_first_pct": round(split_pct, 1)})
    findings.append(_finding(
        "km_consistency", "positive" if cv <= 2.5 else "info" if cv <= 5 else "warning",
        "每公里配速穩定" if cv <= 2.5 else "每公里配速有起伏",
        f"{len(splits)} 個完整公里平均 {fmt_pace(mean_p)}，變異係數 {cv:.1f}%",
        None if cv <= 2.5 else "連續跑的配速起伏常來自起步太快或路線起伏；試著讓前 2 公里比目標慢 5–10 秒",
        cv_pct=round(cv, 1)))
    if split_pct <= -1.0:
        findings.append(_finding(
            "negative_split", "positive", "後半程比前半程快（負分段）",
            f"後半程平均 {fmt_pace(second)}，比前半程 {fmt_pace(first)} 快 {abs(split_pct):.1f}%", None,
            pct=round(split_pct, 1)))
    elif split_pct >= 3.0:
        findings.append(_finding(
            "positive_split", "warning" if session_type in ("tempo", "race") else "info", "後半程明顯變慢",
            f"後半程平均 {fmt_pace(second)}，比前半程 {fmt_pace(first)} 慢 {split_pct:.1f}%",
            "前半程保守一點，把力氣留到後半", pct=round(split_pct, 1)))

    # aerobic decoupling (Pa:HR) -- speed per heartbeat, first vs second half
    hr_pairs = [(s["pace_s_per_km"], s["avg_hr"]) for s in splits if s["avg_hr"]]
    if len(hr_pairs) >= 4 and session_type in ("easy", "long", "tempo"):
        h = len(hr_pairs) // 2
        ef1 = statistics.fmean((1000 / p) / hr_ for p, hr_ in hr_pairs[:h])
        ef2 = statistics.fmean((1000 / p) / hr_ for p, hr_ in hr_pairs[h:])
        decoupling = (ef1 - ef2) / ef1 * 100
        summary["aerobic_decoupling_pct"] = round(decoupling, 1)
        findings.append(_finding(
            "decoupling", "positive" if decoupling < 5 else "info",
            "有氧耐力穩定（心率脫鉤 < 5%）" if decoupling < 5 else "後半程心率漂移",
            f"後半程每單位心率能跑出的速度比前半程{'下降' if decoupling > 0 else '上升'} {abs(decoupling):.1f}%"
            "（Pa:HR 脫鉤指標，< 5% 代表有氧基礎足以支撐這個配速與時間）",
            None if decoupling < 5 else "長距離或天氣熱時常見；持續偏高代表有氧基礎還不足以支撐這個配速長時間進行",
            pct=round(decoupling, 1)))

    # easy days should be easy
    if session_type in ("easy", "long") and hr.zone_tops:
        z2_top = hr.zone_tops[2]
        hrs = _hr_window(g, a, b)
        if hrs:
            above = sum(1 for x in hrs if x > z2_top) / len(hrs) * 100
            summary["pct_above_z2"] = round(above)
            if above >= 30:
                findings.append(_finding(
                    "easy_too_hard", "warning", "輕鬆跑心率偏高",
                    f"這趟有 {above:.0f}% 的時間心率高於第 2 區上限 {z2_top} bpm",
                    "輕鬆跑的目的是恢復與累積有氧基礎；配速再放慢，讓心率留在第 1–2 區，強度留給課表日",
                    pct=round(above)))
            else:
                findings.append(_finding(
                    "easy_ok", "positive", "強度控制得當",
                    f"{100 - above:.0f}% 的時間心率在第 2 區上限 {z2_top} bpm 以下，符合輕鬆跑的目的",
                    None, pct=round(100 - above)))
    if target and session_type in ("tempo", "race"):
        dev = (mean_p - target) / target * 100
        findings.append(_finding(
            "target", "positive" if abs(dev) <= 1.5 else "warning",
            "貼近目標配速" if abs(dev) <= 1.5 else ("比目標配速快" if dev < 0 else "未達目標配速"),
            f"目標 {fmt_pace(target)}，實際平均 {fmt_pace(mean_p)}（{'快' if dev < 0 else '慢'} {abs(dev):.1f}%）",
            None, dev_pct=round(dev, 1)))


# ---------------------------------------------------------------- warm-up / cool-down


def _minutes_text(seconds: float) -> str:
    s = round(seconds)
    return f"{s // 60} 分 {s % 60} 秒" if s % 60 else f"{s // 60} 分鐘"


def _linked_text(rec: dict) -> str:
    parts = [f"{rec['start_local']} 開始", f"{rec['distance_km']:.2f} km", _minutes_text(rec["duration_s"])]
    if rec.get("avg_hr"):
        parts.append(f"平均心率 {rec['avg_hr']} bpm")
    return "，".join(parts)


def _warmup_cooldown_findings(stats: list[dict], reps: list[dict], hr: HrProfile, findings: list[dict],
                              linked: dict | None) -> None:
    """Warm-up and cool-down -- including ones the athlete recorded as a
    separate activity just before / after the session (a common habit: one
    file for the jog, one for the track work)."""
    if not reps:
        return
    linked = linked or {}
    warm = [s for s in stats if s["role"] == "warmup"]
    cool = [s for s in stats if s["role"] == "cooldown"]
    lw, lc = linked.get("warmup"), linked.get("cooldown")
    warm_moving = sum(s["moving_s"] for s in warm) + (lw["duration_s"] if lw else 0)
    if lw:
        findings.append(_finding(
            "linked_warmup", "info", "暖身另有紀錄",
            f"這堂課前另有一筆暖身紀錄（{_linked_text(lw)}），已一併計入",
            None, seconds=lw["duration_s"]))
    if warm_moving < 8 * 60:
        findings.append(_finding(
            "short_warmup", "warning" if warm_moving < 4 * 60 else "info",
            "暖身不足" if warm_moving < 4 * 60 else "暖身偏短",
            f"第一趟之前的跑動（含當天前一筆紀錄）只有 {fmt_duration(warm_moving)}",
            "強度課前建議 10–15 分鐘慢跑加上 3–4 趟加速跑，讓心率與肌肉溫度先上來，第一趟也比較不會衝過頭",
            seconds=warm_moving))
    else:
        warm_hr = (lw or {}).get("avg_hr") or (warm[0].get("avg_hr") if warm else None)
        if hr.zone_tops and warm_hr and warm_hr > hr.zone_tops[2]:
            findings.append(_finding(
                "hard_warmup", "info", "暖身強度偏高",
                f"暖身平均心率 {warm_hr} bpm，已高於第 2 區上限 {hr.zone_tops[2]} bpm",
                "暖身用輕鬆配速就好，心率留在第 1–2 區；天氣熱時更要放慢", avg_hr=warm_hr))
    cool_moving = sum(s["moving_s"] for s in cool) + (lc["duration_s"] if lc else 0)
    if lc:
        findings.append(_finding(
            "linked_cooldown", "info", "收操另有紀錄",
            f"這堂課後另有一筆收操紀錄（{_linked_text(lc)}），已一併計入", None, seconds=lc["duration_s"]))
    if cool_moving < 5 * 60:
        findings.append(_finding(
            "short_cooldown", "info", "收操偏短",
            f"最後一趟之後的跑動（含當天下一筆紀錄）只有 {fmt_duration(cool_moving)}",
            "強度課後慢跑 10 分鐘左右，幫助身體回到平靜狀態", seconds=cool_moving))


# ---------------------------------------------------------------- history


def _history_findings(summary: dict, history: list[dict], findings: list[dict]) -> None:
    """Against this athlete's own earlier sessions of the same workout
    (newest first): last time, the trend across them, heart rate at a
    similar pace, and how fast heart rate came down during the rests."""
    current = summary.get("mean_work_pace_s_per_km") or summary.get("split_mean_pace_s_per_km")
    if not current:
        return
    prev = history[0]
    prev_pace = prev.get("mean_pace_s_per_km")
    if not prev_pace:
        return
    delta = current - prev_pace  # + = slower today
    hr_now, hr_prev = summary.get("mean_rep_hr"), prev.get("mean_rep_hr")
    hr_txt = ""
    if hr_now and hr_prev:
        hr_txt = f"，各趟平均心率 {hr_now} bpm（上次 {hr_prev} bpm）"
    better_engine = delta < 0 and hr_now and hr_prev and hr_now <= hr_prev
    # within the ~3 bpm a heart rate drifts between days, a lower heart rate
    # at the same pace is a real change
    same_pace_lower_hr = abs(delta) < 2 and hr_now and hr_prev and hr_prev - hr_now >= 3
    summary["history_comparison"] = {"date": prev["date"], "signature": prev["signature"],
                                     "prev_pace_s_per_km": prev_pace, "delta_s_per_km": round(delta, 1),
                                     "prev_mean_rep_hr": hr_prev}
    if same_pace_lower_hr:
        title = "同樣配速，心率比上次低"
    elif delta <= -1:
        title = "比上次同課表更快"
    elif delta >= 1:
        title = "比上次同課表慢"
    else:
        title = "與上次同課表相當"
    findings.append(_finding(
        "history", "positive" if delta <= -1 or same_pace_lower_hr else "info", title,
        f"上次同樣的課表（{prev['date']}，{prev['signature']}）平均 {fmt_pace(prev_pace)}，今天 {fmt_pace(current)}"
        f"（{'快' if delta < 0 else '慢'} {abs(delta):.1f} 秒/km）{hr_txt}"
        + ("：跑更快、心率沒有更高，是體能進步的訊號" if better_engine else "")
        + (f"：配速差不多，心率低了 {hr_prev - hr_now} bpm，是體能進步的訊號" if same_pace_lower_hr else ""),
        None, delta_s_per_km=round(delta, 1)))

    paced = [h for h in history if h.get("mean_pace_s_per_km")]
    if len(paced) >= 2:
        trend = list(reversed(paced)) + [{"date": "今天", "mean_pace_s_per_km": current, "mean_rep_hr": hr_now}]
        summary["history_trend"] = [{"date": h["date"], "pace_s_per_km": round(h["mean_pace_s_per_km"], 1),
                                     "mean_rep_hr": h.get("mean_rep_hr")} for h in trend]
        steps = "、".join(f"{h['date']} {fmt_pace(h['mean_pace_s_per_km'])}"
                         + (f"（{h['mean_rep_hr']} bpm）" if h.get("mean_rep_hr") else "") for h in trend)
        findings.append(_finding("history_trend", "info", f"近 {len(trend)} 次同課表", steps, None))

    drop_now = summary.get("mean_hr_drop")
    # heart rate barely falls during a jogging recovery: only standing or
    # walking recoveries are compared with each other
    past_drops = [h["mean_hr_drop"] for h in history
                  if h.get("mean_hr_drop") and h["mean_hr_drop"] > 0 and not h.get("recovery_jogging")]
    if drop_now and drop_now > 0 and not summary.get("recovery_jogging") and past_drops:
        past = statistics.fmean(past_drops)
        summary["recovery_comparison"] = {"past_mean_hr_drop": round(past), "sessions": len(past_drops)}
        basis = f"今天休息 60 秒內心率平均下降 {drop_now} bpm，過去 {len(past_drops)} 次同課表平均 {round(past)} bpm"
        # ~25% typical error on a 60 s drop: only a gap larger than that is
        # read as a change; a faster drop is reported, not praised
        if drop_now <= past * 0.75:
            findings.append(_finding(
                "recovery_trend", "warning", "休息時心率降得比過去慢", basis,
                "恢復變慢常見於疲勞累積；下次同課表前多排一天輕鬆跑，或把休息延長 15–30 秒"))
        elif drop_now >= past * 1.25:
            findings.append(_finding("recovery_trend", "info", "休息時心率降得比過去快", basis, None))
        else:
            findings.append(_finding("recovery_trend", "info", "休息時心率下降與過去相當", basis, None))
