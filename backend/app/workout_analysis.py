"""Coach-grade metrics and findings for one confirmed workout.

Input is the stored telemetry plus the segmentation the athlete confirmed
(warm-up / each rep / each recovery / cool-down). Everything here is
deterministic arithmetic on the recorded data -- the language model only
ever narrates these numbers (see workout_narrative.py), it never computes
or invents them.

Every threshold here has a source listed in WORKOUT_ANALYSIS_EVIDENCE.md:
a published number, a vendor document, a measurement error from the
literature, the athlete's own earlier sessions of the same workout
(usual_range), or a data-quality setting stated as such. A judgment with
none of these is not made -- the number is reported on its own.

Conventions:
- Pace is seconds per km. A rep with a confirmed nominal distance (a
  1000 m rep on a track) is paced over that distance, not over the GPS
  trace, which reads long on a track (0.9-4.1 % mean absolute error,
  Gilgen-Ammann et al. 2020); the GPS distance is reported next to it.
- Rep time excludes in-rep interruptions (auto-pause, a stop); recovery
  time is wall-clock, paused or not -- a coach times the recovery the
  athlete actually took.
- Heart-rate metrics for reps shorter than 60 s are reported but not
  interpreted (a data-quality setting).
"""

from __future__ import annotations

import copy
import math
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

# Zone tops as a fraction of heart-rate reserve, as Garmin watches set them
# in %HRR mode (recorded in the demo athlete's own FIT files; Garmin's
# manuals list the same percentages of maximum heart rate as the %max
# default) -- used only when no zone boundaries came from the watch.
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
        notes.append("最大心率以 Tanaka 公式（208 − 0.7 × 年齡）估算，是族群平均，個人可能差距很大")

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
        if moving >= STEADY_HR_MIN_S:
            steady = _hr_window(g, b - STEADY_HR_LAST_S, b)
            stats["hr_last60"] = round(statistics.fmean(steady), 1) if steady else None
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
        # HR recovery (HRR60): from the peak to 60 s after it. The peak is
        # searched from 3 s before to 30 s after the stop rather than taken
        # at the stop itself (data-quality settings, as are the 40 s
        # minimum window and the 60 % heart-rate coverage)
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


# ---------------------------------------------------------------- the athlete's own range

# 90 % confidence, the level Hopkins uses for inferences about an athlete's
# change (WORKOUT_ANALYSIS_EVIDENCE.md)
HOPKINS_Z = 1.645
# Bonato et al. 2018, PLOS ONE 13 (full text, Table 2): HRR60 typical error
# as a coefficient of variation
HRR60_CV_PCT = 10.9
# Lamberts et al. 2004, J Strength Cond Res 18:641 (abstract): standard
# error of measurement of submaximal heart rate 1.1-1.4 %; the upper bound
SUBMAX_HR_SEM_PCT = 1.4
# Buchheit 2014, Front Physiol 5:73 (full text): heart rate needs at least
# 3-4 min of exercise to reach a steady state, and the average of the last
# 30-60 s is what is compared; the lower bound of each
STEADY_HR_MIN_S = 180
STEADY_HR_LAST_S = 60
# Smallest worthwhile change in running performance: 0.3 of the typical
# race-to-race variation (Hopkins 2004, full text), 1.9 % for runners
# (Hopkins & Hewson 2001, abstract: 1.2-1.9 %, the upper bound) -- applied to
# a rep's pace against its target, an extension stated in
# WORKOUT_ANALYSIS_EVIDENCE.md
SWC_PCT = 0.3 * 1.9

# per-session numbers kept so later sessions of the same workout can be
# compared with this one (usual_range); stored with the import-time
# detection and with every confirmed analysis
HISTORY_METRICS = ("block_cv_pct", "block_fade_pct", "rep_end_hr_slope", "rep_start_hr_slope",
                   "within_rep_split_pct", "split_cv_pct", "second_half_vs_first_pct", "steady_rep_hr")


def history_summary(summary: dict[str, Any]) -> dict[str, Any]:
    """What a session contributes to the same-workout history."""
    out = {"mean_pace_s_per_km": summary.get("mean_work_pace_s_per_km") or summary.get("split_mean_pace_s_per_km"),
           "mean_rep_hr": summary.get("mean_rep_hr"),
           "rep_count": summary.get("rep_count"),
           "mean_hr_drop": summary.get("mean_hr_drop"),
           "recovery_jogging": summary.get("recovery_jogging")}
    out.update({k: summary.get(k) for k in HISTORY_METRICS})
    return out


def usual_range(past: list[Any]) -> dict[str, Any] | None:
    """The athlete's usual range for one number, from >= 2 earlier sessions
    of the same workout (two values are the least a standard deviation
    needs): mean +/- z x SD x sqrt(1 + 1/k), the spread a new session falls
    in 90 % of the time when nothing has changed."""
    vals = [float(v) for v in past if v is not None]
    if len(vals) < 2:
        return None
    k = len(vals)
    mean = statistics.fmean(vals)
    half = HOPKINS_Z * statistics.stdev(vals) * math.sqrt(1 + 1 / k)
    return {"mean": mean, "low": mean - half, "high": mean + half, "sessions": k}


def _pct(x: float) -> str:
    return f"{x:.1f}%"


def _bpm(x: float) -> str:
    return f"{x:.1f} bpm"


def _with_range(detail: str, value: float | None, history: list[dict] | None, key: str, fmt,
                above: str = "高於", below: str = "低於") -> str:
    """Append where today's value sits against the athlete's usual range --
    stated, not judged: which direction is "better" has no source."""
    if value is None:
        return detail
    rng = usual_range([h.get(key) for h in history or []])
    if rng is None:
        return detail
    span = f"（{fmt(rng['low'])} 至 {fmt(rng['high'])}）"
    if value > rng["high"]:
        return detail + f"；{above}你過去 {rng['sessions']} 次同課表的平常範圍{span}"
    if value < rng["low"]:
        return detail + f"；{below}你過去 {rng['sessions']} 次同課表的平常範圍{span}"
    return detail + f"；在你過去 {rng['sessions']} 次同課表的平常範圍{span}內"


def _signed(x: float, unit: str) -> str:
    return f"{'+' if x >= 0 else '−'}{abs(x):.1f}{unit}"


def range_status(value: float | None, history: list[dict] | None, key: str) -> str | None:
    """above / below / inside the athlete's usual range, or None without one."""
    if value is None:
        return None
    rng = usual_range([h.get(key) for h in history or []])
    if rng is None:
        return None
    return "above" if value > rng["high"] else "below" if value < rng["low"] else "inside"


def _vs_usual(status: str | None, what: str) -> str:
    """'；今天<what>比你平常大' -- a statement about the athlete's own range."""
    return {"above": f"；今天{what}比你平常大", "below": f"；今天{what}比你平常小",
            "inside": f"；今天{what}跟你平常差不多"}.get(status, "")


def _compare(*statuses: str | None) -> str | None:
    known = [x for x in statuses if x]
    if not known:
        return None
    return "different" if any(x != "inside" for x in known) else "usual"


def _explain(f: dict[str, Any], summary: dict[str, Any], history: list[dict] | None) -> None:
    """Plain words for what a finding's numbers say -- each metric's
    definition and today's direction, never a good / bad call (those come
    only from the finding's own source) -- and whether today sits outside
    the athlete's usual range."""
    code, ev = f["code"], f.get("evidence") or {}
    meaning, compare = None, None
    if code == "consistency":
        st = range_status(summary.get("block_cv_pct"), history, "block_cv_pct")
        what = "每趟之間的差異" if "sd_pct" not in ev else "每趟離目標遠近的差異"
        meaning = ("數字越小，每趟越平均地貼著各自的目標" if "sd_pct" in ev else "數字越小，每趟配速越平均") \
            + _vs_usual(st, what)
        compare = _compare(st)
    elif code == "first_rep":
        d = ev.get("delta_pct") or 0
        meaning = f"第 1 趟比其餘各趟{'快' if d > 0 else '慢'}" if d else "第 1 趟跟其餘各趟差不多"
    elif code == "pace_trend":
        st = range_status(summary.get("block_fade_pct"), history, "block_fade_pct")
        c = ev.get("change_pct") or 0
        meaning = (("後段比前段慢" if c > 0 else "後段比前段快") if c else "前段跟後段差不多") \
            + _vs_usual(st, "前後段的落差")
        compare = _compare(st)
    elif code == "within_rep_split":
        st = range_status(summary.get("within_rep_split_pct"), history, "within_rep_split_pct")
        sp = ev.get("split_pct") or 0
        meaning = f"每趟後半段比前半段{'慢' if sp > 0 else '快'}；這是 GPS 估算，誤差跟差距差不多大，不用在意" \
            + _vs_usual(st, "每趟前後半的落差")
        compare = _compare(st)
    elif code == "rep_hr":
        st_end = range_status(summary.get("rep_end_hr_slope"), history, "rep_end_hr_slope")
        st_start = range_status(summary.get("rep_start_hr_slope"), history, "rep_start_hr_slope")
        meaning = "每趟跑完時的心率，平均一趟比一趟高多少；研究沒有建立用這個數字判斷好壞的標準，不用在意" \
            + _vs_usual(st_end, "心率每趟上升的幅度")
        compare = _compare(st_end, st_start)
    elif code == "recovery":
        meaning = "休息開始後 60 秒內心率降了多少；單看這一項不能判斷好壞，累積疲勞時反而可能降得更快（Aubry 2015）"
    elif code == "recovery_trend":
        comp = summary.get("recovery_comparison") or {}
        change, margin = comp.get("change_pct"), comp.get("margin_pct")
        if change is not None and margin is not None:
            compare = "different" if abs(change) > margin else "usual"
            meaning = ({"different": f"休息時心率降得比你平常{'少' if change < 0 else '多'}，差距大過量測誤差",
                        "usual": "休息時心率下降跟你平常差不多，差距在量測誤差內"}[compare]
                       + "；單看這一項不能判斷好壞（Aubry 2015）")
    elif code == "rest":
        meaning = "每次休息實際用了多久" + ("，跟課表要求差多少" if "課表要求" in f["detail"] else "")
    elif code == "target":
        meaning = "每趟有沒有落在教練目標的容許範圍內"
    elif code == "km_splits":
        st_cv = range_status(summary.get("split_cv_pct"), history, "split_cv_pct")
        st_half = range_status(summary.get("second_half_vs_first_pct"), history, "second_half_vs_first_pct")
        sp = summary.get("second_half_vs_first_pct") or 0
        meaning = f"變異係數越小，每公里配速越平均；後半程比前半程{'慢' if sp > 0 else '快'}" \
            + _vs_usual(st_cv, "每公里之間的差異")
        compare = _compare(st_cv, st_half)
    elif code == "decoupling":
        meaning = "後半程同樣的心率能跑出的速度掉了多少；分級依 TrainingPeaks"
    elif code == "zone_time":
        meaning = "Garmin 把第 2 區描述為「舒適、還能交談、適合恢復的配速」；輕鬆跑的平均心率應該在這以內"
    elif code == "warmup":
        meaning = "強度課前的主動暖身有助於短、中距離的表現（Bishop 2003）"
    elif code == "cooldown":
        meaning = "收操長短對之後的表現和預防受傷幾乎沒有影響（Van Hooren & Peake 2018），不用在意"
    elif code == "pyramid_pair":
        meaning = "同樣距離的前後兩趟，配速差多少"
    elif code == "history":
        st = range_status(summary.get("mean_work_pace_s_per_km") or summary.get("split_mean_pace_s_per_km"),
                          history, "mean_pace_s_per_km")
        if f["severity"] == "positive":
            meaning = "同樣或更快的配速下心率較低，是有氧體能改善的方向（Buchheit 2014）"
        else:
            d = ev.get("delta_s_per_km") or 0
            meaning = f"跟上次同樣的課表比，今天平均配速{'快' if d < 0 else '慢'}了多少" + {
                "above": "；今天比你平常的配速慢", "below": "；今天比你平常的配速快",
                "inside": "；今天的配速跟你平常差不多"}.get(st, "")
        compare = _compare(st)
    elif code == "history_trend":
        meaning = "最近幾次同課表的平均配速與心率"
    if meaning:
        f["meaning"] = meaning
    f["compare"] = compare


_RANK = {"critical": 0, "warning": 1, "positive": 2, "dismiss": 6}
_COMPARE_RANK = {"different": 3, "usual": 4}


def _rank(f: dict[str, Any]) -> int:
    """What needs work first, then what was done well, then what is unusual
    for this athlete, the rest, and last what research says cannot be
    judged on its own."""
    return _RANK.get(f["severity"], _COMPARE_RANK.get(f.get("compare"), 5))


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
    {date, signature, mean_pace_s_per_km, mean_rep_hr, mean_hr_drop,
    recovery_jogging, rep_count} plus the HISTORY_METRICS.
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
        data_notes.append("非手錶操場模式：研究顯示田徑場上 GPS 距離多半偏長（平均誤差 0.9–4.1%），"
                          "已設定標準距離的趟次以標準距離計算配速")

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
        _interval_findings(g, stats, reps, rests, hr, prescription_meta, findings, summary, data_notes, history)
    if session_type in ("easy", "long", "tempo", "race") or not reps:
        _continuous_findings(g, stats, hr, session_type, findings, summary, target_pace_s_per_km, reps, history)
    _warmup_cooldown_findings(stats, reps, findings, linked)
    if history:
        _history_findings(summary, history, findings)
    if hr.max_hr is None:
        data_notes.append("沒有可用的最大心率設定，心率強度百分比無法計算")

    for f in findings:
        _explain(f, summary, history)
    findings.sort(key=_rank)
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
                if want.get("target_tolerance_s_per_km"):
                    tol = want["target_tolerance_s_per_km"]
                    r["target_low_s_per_km"] = round(want["target_pace_s_per_km"] - tol, 1)
                    r["target_high_s_per_km"] = round(want["target_pace_s_per_km"] + tol, 1)
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


def _prescribed_rest(summary: dict, meta: dict | None) -> float | None:
    """The one recovery length a real prescription set, if it set one."""
    if not (meta or {}).get("gradable"):
        return None
    values = {b.get("rest_s") for b in (summary.get("prescription") or {}).get("blocks", [])
              if b.get("rest_s") and (b.get("reps") or 1) > 1}
    return float(values.pop()) if len(values) == 1 else None


def _interval_findings(g: Grid, stats: list[dict], reps: list[dict], rests: list[dict], hr: HrProfile,
                       prescription_meta: dict | None, findings: list[dict], summary: dict,
                       notes: list[str], history: list[dict] | None) -> None:
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
        _target_relative_findings(block, findings, summary, prescription_meta or {}, history)
    else:
        block = _nominal_block_findings(paced, findings, summary, history)
        if block is None:
            return

    # within-rep pacing, from the GPS trace
    halves = [(r["first_half_pace"], r["second_half_pace"]) for r in block
              if r.get("first_half_pace") and r.get("second_half_pace")]
    if len(halves) >= 2:
        diffs = [(s - f) / ((s + f) / 2) * 100 for f, s in halves]  # + = second half slower
        mean_diff = statistics.fmean(diffs)
        summary["within_rep_split_pct"] = round(mean_diff, 1)
        findings.append(_finding(
            "within_rep_split", "dismiss", "趟內前後半配速",
            _with_range(f"每趟後半段平均比前半段{'慢' if mean_diff > 0 else '快'} {abs(mean_diff):.1f}%"
                        "（GPS 估算；田徑場上 GPS 距離的平均誤差約 0.9–4.1%）",
                        round(mean_diff, 1), history, "within_rep_split_pct", _pct),
            None, split_pct=round(mean_diff, 1)))

    # interruptions
    for r in reps:
        if r["interruptions_s"]:
            findings.append(_finding(
                "interruption", "info", f"第 {r['rep_number']} 趟中途停下",
                f"第 {r['rep_number']} 趟中途停了 {r['interruptions_s']} 秒，該趟配速已扣除停下時間計算",
                None, seconds=r["interruptions_s"]))

    # heart rate across reps (only reps of >= 60 s, a data-quality setting)
    long_reps = [r for r in block if r["moving_s"] >= 60 and r.get("hr_end")]
    if len(long_reps) >= 2:
        ends = [r["hr_end"] for r in long_reps]
        end_slope = _slope(ends)
        summary["rep_end_hr"] = ends
        summary["rep_end_hr_slope"] = round(end_slope, 1)
        detail = _with_range(
            f"每趟結束心率從第 {long_reps[0]['rep_number']} 趟的 {ends[0]} bpm 到第 {long_reps[-1]['rep_number']} 趟的 "
            f"{ends[-1]} bpm（平均每趟 {_signed(end_slope, ' bpm')}）",
            round(end_slope, 1), history, "rep_end_hr_slope", _bpm)
        starts = [r["hr_start"] for r in long_reps if r.get("hr_start")]
        if len(starts) >= 2:
            start_slope = _slope(starts)
            summary["rep_start_hr_slope"] = round(start_slope, 1)
            detail += _with_range(
                f"。每趟起跑心率從 {starts[0]} bpm 到 {starts[-1]} bpm（平均每趟 {_signed(start_slope, ' bpm')}）",
                round(start_slope, 1), history, "rep_start_hr_slope", _bpm)
        findings.append(_finding("rep_hr", "dismiss", "每趟心率", detail, None, slope_bpm_per_rep=round(end_slope, 1)))
        steady = [r["hr_last60"] for r in block if r.get("hr_last60")]
        if steady:
            summary["steady_rep_hr"] = round(statistics.fmean(steady), 1)
            summary["steady_rep_count"] = len(steady)
        peak = max((r["max_hr"] for r in long_reps if r["max_hr"]), default=None)
        pct = hr.pct_max(peak)
        if pct is not None:
            summary["peak_rep_hr"] = peak
            summary["peak_rep_hr_pct_max"] = pct
    elif block and block[0]["moving_s"] < 60:
        notes.append("每趟不到 60 秒，未達本系統判讀每趟心率的最短時間（資料品質設定），本次不判讀每趟心率")

    # recovery: reported here, compared with the athlete's own sessions in
    # _history_findings -- a 60 s drop has no published "good" value, and a
    # faster drop can also come with overreaching (Aubry et al. 2015)
    drops = [r for r in rests if r.get("hr_drop") is not None and r["role"] == "rest"]
    if drops:
        vals = [r["hr_drop"] for r in drops]
        mean_drop = statistics.fmean(vals)
        types = {r["rest_type"] for r in drops}
        summary["mean_hr_drop"] = round(mean_drop)
        jog = "jogging" in types
        summary["recovery_jogging"] = jog
        measured = f"（以 {len(drops)} 次手錶未暫停、可量測的休息計算）" if len(drops) < len(rests) else ""
        findings.append(_finding(
            "recovery", "dismiss", "休息時的心率下降",
            (f"休息時心率從峰值起 60 秒內平均下降 {mean_drop:.0f} bpm{measured}" if round(mean_drop) > 0 else
             f"休息時心率從峰值起 60 秒內沒有下降，反而平均上升 {abs(mean_drop):.0f} bpm{measured}")
            + "（峰值取休息開始前 3 秒到開始後 30 秒內的最高心率）",
            None, mean_drop=round(mean_drop)))
    if any(r.get("paused_during_rest") for r in rests) and not drops:
        notes.append("休息時手錶有暫停，暫停期間沒有心率紀錄，無法計算休息中的心率下降")

    # rest lengths: against the prescription when it set one
    rest_durs = [r["elapsed_s"] for r in rests if r["role"] == "rest"]
    if rest_durs:
        rmean = statistics.fmean(rest_durs)
        summary["rest_mean_s"] = round(rmean)
        span = f"最短 {fmt_duration(min(rest_durs))}、最長 {fmt_duration(max(rest_durs))}"
        prescribed = _prescribed_rest(summary, prescription_meta)
        if prescribed:
            diff = rmean - prescribed
            detail = (f"休息 {len(rest_durs)} 次，平均 {fmt_duration(rmean)}，課表要求 {fmt_duration(prescribed)}"
                      f"（{'長' if diff > 0 else '短'} {abs(diff):.0f} 秒）；{span}")
        else:
            detail = f"休息 {len(rest_durs)} 次，平均 {fmt_duration(rmean)}（{span}）"
        if prescribed and rmean - prescribed > 1:
            sev, title, adv = "warning", "休息比課表長", "休息長度是課表設計的一部分（Buchheit & Laursen 2013），下次照課表計時"
        elif prescribed:
            sev, title, adv = "positive", "休息沒有超過課表", None
        else:
            sev, title, adv = "info", "休息時間", None
        findings.append(_finding("rest", sev, title, detail, adv, mean_s=round(rmean)))

    # cadence, first vs last third of the reps -- a number, not a finding
    cads = [r["avg_cadence"] for r in block if r.get("avg_cadence")]
    if len(cads) >= 3:
        c1, c3 = _thirds(cads)
        summary["cadence_first_third"] = round(c1)
        summary["cadence_last_third"] = round(c3)


def _nominal_block_findings(paced: list[dict], findings: list[dict], summary: dict,
                            history: list[dict] | None) -> list[dict] | None:
    """No prescription: spread and trend over the largest block of reps of
    one distance. Returns that block, or None for a pyramid / mixed session
    (repeated distances are then compared pairwise)."""
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
                "pyramid_pair", "info", f"{rep_label(grp[0])} 前後對照",
                f"{_reps_phrase([r['rep_number'] for r in grp])} 的配速分別是 "
                + " / ".join(fmt_pace(x) for x in p)
                + (f"，同距離前後差 {_per_rep_seconds(spread, dist):.1f} 秒" if dist else ""),
                None, spread_s_per_km=round(spread, 1)))
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
    findings.append(_finding(
        "consistency", "info", "配速穩定度",
        _with_range(f"{n} 趟 {label} 平均 {fmt_pace(mean_p)}，變異係數 {cv:.1f}%；最快第 {fastest['rep_number']} 趟 "
                    f"{fmt_pace(fastest['pace_s_per_km'])}、最慢第 {slowest['rep_number']} 趟 "
                    f"{fmt_pace(slowest['pace_s_per_km'])}，每趟時間最多差 {spread_rep_s:.1f} 秒",
                    round(cv, 1), history, "block_cv_pct", _pct),
        None, cv_pct=round(cv, 1), spread_per_rep_s=round(spread_rep_s, 1)))

    # first rep against the rest
    others = statistics.fmean(paces[1:])
    delta = (others - paces[0]) / others * 100  # + = first rep faster
    findings.append(_finding(
        "first_rep", "info", "第一趟與其餘各趟",
        f"第 1 趟 {fmt_pace(paces[0])}，比其餘各趟平均 {fmt_pace(others)} {'快' if delta > 0 else '慢'} "
        f"{abs(delta):.1f}%（約 {abs(_per_rep_seconds(others - paces[0], distance_for_time)):.1f} 秒）",
        None, delta_pct=round(delta, 1)))

    # first third against last third (three thirds need three reps)
    if n >= 3:
        first_third, last_third = _thirds(paces)
        change = (last_third - first_third) / first_third * 100  # + = slower at the end
        summary["block_fade_pct"] = round(change, 1)
        summary["block_trend_s_per_km_per_rep"] = round(_slope(paces), 2)
        rest_mean = statistics.fmean(paces[:-1])
        kick = (rest_mean - paces[-1]) / rest_mean * 100  # + = last rep faster
        findings.append(_finding(
            "pace_trend", "info", "前後段配速",
            _with_range(f"前 1/3 趟數平均 {fmt_pace(first_third)}，後 1/3 平均 {fmt_pace(last_third)}"
                        f"（後段{'慢' if change > 0 else '快'} {abs(change):.1f}%）；最後一趟比前面各趟平均"
                        f"{'快' if kick > 0 else '慢'} {abs(kick):.1f}%",
                        round(change, 1), history, "block_fade_pct", _pct),
            None, change_pct=round(change, 1), kick_pct=round(kick, 1)))
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


def _rep_tolerance_pct(r: dict) -> float:
    """How far from its target a rep may be and still be on it: the coach's
    range when one was set, otherwise the larger of the smallest worthwhile
    change in running performance (SWC_PCT) and the watch's 1 s timing
    resolution over the rep."""
    target = r["target_pace_s_per_km"]
    if r.get("target_low_s_per_km"):
        return (r["target_high_s_per_km"] - r["target_low_s_per_km"]) / 2 / target * 100
    d = r.get("nominal_m") or r.get("distance_m")
    rep_time = target * d / 1000 if d else None
    return max(SWC_PCT, 100 / rep_time) if rep_time else SWC_PCT


def _on_target(r: dict) -> int:
    """-1 faster than the tolerance allows, 0 on target, +1 slower."""
    if r.get("target_low_s_per_km"):
        p = r["pace_s_per_km"]
        return -1 if p < r["target_low_s_per_km"] else 1 if p > r["target_high_s_per_km"] else 0
    dev, tol = r["target_dev_pct"], r["target_tolerance_pct"]
    return -1 if dev < -tol else 1 if dev > tol else 0


def _target_relative_findings(block: list[dict], findings: list[dict], summary: dict, meta: dict,
                              history: list[dict] | None) -> None:
    """Every rep against its own target; dev = % slower (+) or faster (-)
    than that target. A target is graded only when it is a real
    prescription (coach / athlete / activity name): an inferred one is
    derived from this very run and would grade it against itself. Graded
    targets are judged against the coach's range, or else the tolerance in
    _rep_tolerance_pct; an upper limit ("X 秒內") against the limit itself."""
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
    max_mode = all(r.get("target_mode") == "max" for r in block)
    judged = gradable and not max_mode
    tol = None
    if judged:
        for r in block:
            r["target_tolerance_pct"] = round(_rep_tolerance_pct(r), 2)
        tol = statistics.fmean(r["target_tolerance_pct"] for r in block)
        summary["target_tolerance_pct"] = round(tol, 2)
    summary.update({
        "target_dev_sd_pct": round(sd, 1),
        "target_mean_dev_pct": round(statistics.fmean(devs), 1),
        "block_cv_pct": round(sd, 1),
        "prescription_groups": [{"reps": [r["rep_number"] for r in g_], "target_label": g_[0].get("target_label"),
                                 "mean_dev_pct": round(statistics.fmean(r["target_dev_pct"] for r in g_), 1)}
                                for g_ in groups],
    })
    worst = max(block, key=lambda r: abs(r["target_dev_pct"]))
    detail = _with_range(f"{n} 趟相對各自目標的偏差，標準差 {sd:.1f}%；離目標最遠的是第 {worst['rep_number']} 趟"
                         f"（{fmt_pace(worst['pace_s_per_km'])}，目標 {worst.get('target_label')}，"
                         f"{_fast_slow(worst['target_dev_pct'])}）", round(sd, 1), history, "block_cv_pct", _pct)
    if judged:
        steady = sd <= tol
        findings.append(_finding(
            "consistency", "positive" if steady else "warning",
            "每趟都穩定貼著目標" if steady else "每趟離目標忽快忽慢",
            detail + f"（容許範圍約 ±{tol:.1f}%）",
            None if steady else "每趟都對著目標時間跑，不要憑感覺", sd_pct=round(sd, 1)))
    else:
        findings.append(_finding("consistency", "info", "相對目標的配速穩定度", detail, None, sd_pct=round(sd, 1)))

    if len(groups) > 1 and not gradable:
        findings.append(_finding(
            "progression_structure", "info", "分段漸速的結構",
            "這堂的配速分成 " + " → ".join(f"{_group_range(g_)}約 {g_[0].get('target_label')}" for g_ in groups)
            + "（系統依實際配速推估，不是教練實際設定）",
            "到「課表要求」填入教練實際開的課表，分析就能逐趟比對要求"))

    others = statistics.fmean(devs[1:])
    first_detail = (f"第 1 趟 {fmt_pace(block[0]['pace_s_per_km'])}，相對目標 {block[0].get('target_label')} "
                    f"{_fast_slow(devs[0])}；其餘各趟平均相對目標{_fast_slow(others)}")
    if judged:
        side = _on_target(block[0])
        findings.append(_finding(
            "first_rep", "positive" if side == 0 else "warning",
            {0: "第一趟貼著目標", -1: "第一趟太快", 1: "第一趟太慢"}[side], first_detail,
            None if side == 0 else "第一趟就對準目標時間", delta_pct=round(others - devs[0], 1)))
    else:
        findings.append(_finding("first_rep", "info", "第一趟與其餘各趟", first_detail, None,
                                 delta_pct=round(others - devs[0], 1)))
    if n >= 3:
        first_third, last_third = _thirds(devs)
        change = last_third - first_third  # + = falling behind the targets
        summary["block_fade_pct"] = round(change, 1)
        summary["block_trend_s_per_km_per_rep"] = round(
            _slope([r["pace_s_per_km"] - r["target_pace_s_per_km"] for r in block]), 2)
        trend_detail = _with_range(f"前 1/3 趟數平均相對目標{_fast_slow(first_third)}，後 1/3 {_fast_slow(last_third)}",
                                   round(change, 1), history, "block_fade_pct", _pct)
        if judged:
            issues = []
            if first_third < -tol:
                issues.append("前段太快")
            elif first_third > tol:
                issues.append("前段太慢")
            if last_third > tol:
                issues.append("後段掉速")
            elif last_third < -tol:
                issues.append("後段比目標快")
            if first_third < -tol or last_third > tol:
                trend_advice = "前段壓在目標上，把力氣平均分到每一趟"
            elif issues:
                trend_advice = "前段就跑到目標配速，不要把力氣留到後段"
            else:
                trend_advice = None
            findings.append(_finding(
                "pace_trend", "warning" if issues else "positive",
                "、".join(issues) if issues else "前後段都貼著目標",
                trend_detail + f"（容許範圍約 ±{tol:.1f}%）", trend_advice, change_pct=round(change, 1)))
        else:
            findings.append(_finding("pace_trend", "info", "前後段相對目標", trend_detail, None,
                                     change_pct=round(change, 1)))

    if not gradable:
        return
    lines = []
    for g_ in groups:
        mean_dev = statistics.fmean(r["target_dev_pct"] for r in g_)
        tvs = [_rep_time_vs_target(r) for r in g_]
        within_word = "內" if g_[0].get("target_mode") == "max" else ""
        if all(tvs) and (g_[0].get("nominal_m") or 0) <= 600 and g_[0].get("nominal_m"):
            actual = statistics.fmean(t[0] for t in tvs)
            target_s = tvs[0][1]
            lines.append(f"{_group_range(g_)}要求 {g_[0].get('target_label') or f'{target_s:.0f} 秒'}{within_word}，"
                         f"實際平均 {actual:.1f} 秒（{'慢' if actual > target_s else '快'} {abs(actual - target_s):.1f} 秒）")
        else:
            actual_p = statistics.fmean(r["pace_s_per_km"] for r in g_)
            lines.append(f"{_group_range(g_)}要求 {g_[0].get('target_label') or fmt_pace(g_[0]['target_pace_s_per_km'])}"
                         f"{within_word}，實際平均 {fmt_pace(actual_p)}（{_fast_slow(mean_dev)}）")
    incomplete = meta.get("completed", n) < meta.get("prescribed", n)
    done = f"（只完成 {meta.get('completed')}/{meta.get('prescribed')} 趟）" if incomplete else ""
    if max_mode:
        # an upper limit: the coach's number is the criterion itself, read
        # on the deviation as displayed (0.1 %) so the table and this agree
        missed = [r for r in block if r["target_dev_pct"] > 0]
        findings.append(_finding(
            "target", "warning" if missed else "positive",
            ("每趟都在要求以內" if not missed else f"{_reps_phrase([r['rep_number'] for r in missed])}超出要求") + done,
            "；".join(lines) + f"。{n} 趟中有 {n - len(missed)} 趟在要求以內（要求是上限，跑更快也算在要求以內）",
            None, within=n - len(missed)))
        return
    sides = [_on_target(r) for r in block]
    fast = [r["rep_number"] for r, x in zip(block, sides) if x < 0]
    slow = [r["rep_number"] for r, x in zip(block, sides) if x > 0]
    out = []
    if fast:
        out.append(f"{_reps_phrase(fast)}比目標快" if len(fast) == 1 else f"{len(fast)} 趟比目標快")
    if slow:
        out.append(f"{_reps_phrase(slow)}比目標慢" if len(slow) == 1 else f"{len(slow)} 趟比目標慢")
    listed = "".join(f"{label}：{_reps_phrase(nums)}。" for label, nums in (("比目標快", fast), ("比目標慢", slow))
                     if len(nums) > 1)
    inside = n - len(fast) - len(slow)
    coach_range = all(r.get("target_low_s_per_km") for r in block)
    basis = ("容許範圍是教練設定的範圍" if coach_range
             else f"容許範圍約 ±{tol:.1f}%，取「表現上最小有意義差距 0.6%」與「手錶 1 秒計時解析度」的較大者")
    advice = None
    if fast:
        advice = "課表的訓練效果取決於指定的強度（Buchheit & Laursen 2013），下次每趟都壓在目標範圍內"
    elif slow:
        advice = "下次每趟都拉回目標範圍內"
    findings.append(_finding(
        "target", "warning" if out else "positive",
        ("每趟都在目標的容許範圍內" if not out else "、".join(out)) + done,
        "；".join(lines) + f"。{n} 趟中有 {inside} 趟在範圍內（{basis}）。" + listed,
        advice, within=inside))


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
                         summary: dict, target: float | None, reps: list[dict], history: list[dict] | None) -> None:
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
    detail = _with_range(f"{len(splits)} 個完整公里平均 {fmt_pace(mean_p)}，變異係數 {cv:.1f}%",
                         round(cv, 1), history, "split_cv_pct", _pct)
    detail += _with_range(f"。後半程平均 {fmt_pace(second)}，比前半程 {fmt_pace(first)} "
                          f"{'慢' if split_pct > 0 else '快'} {abs(split_pct):.1f}%",
                          round(split_pct, 1), history, "second_half_vs_first_pct", _pct)
    findings.append(_finding("km_splits", "info", "每公里配速", detail, None, cv_pct=round(cv, 1),
                             split_pct=round(split_pct, 1)))

    # aerobic decoupling (Pa:HR) -- speed per heartbeat, first vs second
    # half; bands as TrainingPeaks publishes them (WORKOUT_ANALYSIS_EVIDENCE.md)
    hr_pairs = [(s["pace_s_per_km"], s["avg_hr"]) for s in splits if s["avg_hr"]]
    if len(hr_pairs) >= 2 and session_type in ("easy", "long", "tempo"):
        h = len(hr_pairs) // 2
        ef1 = statistics.fmean((1000 / p) / hr_ for p, hr_ in hr_pairs[:h])
        ef2 = statistics.fmean((1000 / p) / hr_ for p, hr_ in hr_pairs[h:])
        decoupling = (ef1 - ef2) / ef1 * 100
        summary["aerobic_decoupling_pct"] = round(decoupling, 1)
        if decoupling < 5:
            sev, band = "positive", "TrainingPeaks 的分級：< 5% 代表在這個強度下有氧耐力良好"
        elif decoupling <= 10:
            sev, band = "info", "TrainingPeaks 的分級：5–10% 代表耐力有限或有疲勞"
        else:
            sev, band = "warning", "TrainingPeaks 的分級：> 10% 代表強度可能高於有氧閾值，或耐力不足以撐完"
        findings.append(_finding(
            "decoupling", sev, f"心率脫鉤 {decoupling:.1f}%",
            f"後半程每單位心率能跑出的速度比前半程{'下降' if decoupling > 0 else '上升'} {abs(decoupling):.1f}%"
            f"（Pa:HR 脫鉤；{band}）",
            None if decoupling < 5 else "TrainingPeaks 指出核心體溫上升、脫水、肝醣耗盡與心血管疲勞都會讓脫鉤變大；"
            "跟其他次比較時，先看天氣與補給條件是否相近",
            pct=round(decoupling, 1)))

    # time above zone 2, zones as the watch set them
    if session_type in ("easy", "long") and hr.zone_tops:
        z2_top = hr.zone_tops[2]
        hrs = _hr_window(g, a, b)
        if hrs:
            above = sum(1 for x in hrs if x > z2_top) / len(hrs) * 100
            summary["pct_above_z2"] = round(above)
            mean_hr = statistics.fmean(hrs)
            easy_enough = mean_hr <= z2_top
            findings.append(_finding(
                "zone_time", "positive" if easy_enough else "warning",
                "輕鬆跑強度在第 2 區以內" if easy_enough else "輕鬆跑跑太快",
                f"平均心率 {mean_hr:.0f} bpm，第 2 區上限 {z2_top} bpm；有 {above:.0f}% 的時間高於第 2 區（區間依你的心率設定）",
                None if easy_enough else "放慢到還能交談的配速，讓平均心率回到第 2 區以內",
                pct=round(above)))
    if target and session_type in ("tempo", "race"):
        dev = (mean_p - target) / target * 100
        total_s = target * (len(splits))  # one sustained effort: 1 s over its whole length
        tol = max(SWC_PCT, 100 / total_s) if total_s else SWC_PCT
        on = abs(dev) <= tol
        findings.append(_finding(
            "target", "positive" if on else "warning",
            "貼著目標配速" if on else ("比目標配速快" if dev < 0 else "比目標配速慢"),
            f"目標 {fmt_pace(target)}，實際平均 {fmt_pace(mean_p)}（{'快' if dev < 0 else '慢'} {abs(dev):.1f}%；"
            f"容許範圍約 ±{tol:.1f}%）",
            None if on else "下次照目標配速跑", dev_pct=round(dev, 1)))


# ---------------------------------------------------------------- warm-up / cool-down


def _minutes_text(seconds: float) -> str:
    s = round(seconds)
    return f"{s // 60} 分 {s % 60} 秒" if s % 60 else f"{s // 60} 分鐘"


def _linked_text(rec: dict) -> str:
    parts = [f"{rec['start_local']} 開始", f"{rec['distance_km']:.2f} km", _minutes_text(rec["duration_s"])]
    if rec.get("avg_hr"):
        parts.append(f"平均心率 {rec['avg_hr']} bpm")
    return "，".join(parts)


def _warmup_cooldown_findings(stats: list[dict], reps: list[dict], findings: list[dict],
                              linked: dict | None) -> None:
    """Warm-up and cool-down, reported -- including ones the athlete
    recorded as a separate activity just before / after the session (a
    common habit: one file for the jog, one for the track work). There is
    no published length to judge either against (Bishop 2003; Van Hooren &
    Peake 2018)."""
    if not reps:
        return
    linked = linked or {}
    warm = [s for s in stats if s["role"] == "warmup"]
    cool = [s for s in stats if s["role"] == "cooldown"]
    lw, lc = linked.get("warmup"), linked.get("cooldown")
    if lw:
        findings.append(_finding(
            "linked_warmup", "info", "暖身另有紀錄",
            f"這堂課前另有一筆暖身紀錄（{_linked_text(lw)}），已一併計入",
            None, seconds=lw["duration_s"]))
    warm_moving = sum(s["moving_s"] for s in warm) + (lw["duration_s"] if lw else 0)
    warm_hr = (lw or {}).get("avg_hr") or (warm[0].get("avg_hr") if warm else None)
    findings.append(_finding(
        "warmup", "positive" if warm_moving > 0 else "warning",
        "有暖身" if warm_moving > 0 else "沒有暖身",
        f"第一趟之前的跑動（含當天前一筆紀錄）共 {fmt_duration(warm_moving)}"
        + (f"，平均心率 {warm_hr} bpm" if warm_hr else ""),
        None if warm_moving > 0 else "強度課前先慢跑暖身，最後加幾趟跟課表同配速的短加速（Bishop 2003）",
        seconds=warm_moving))
    if lc:
        findings.append(_finding(
            "linked_cooldown", "info", "收操另有紀錄",
            f"這堂課後另有一筆收操紀錄（{_linked_text(lc)}），已一併計入", None, seconds=lc["duration_s"]))
    cool_moving = sum(s["moving_s"] for s in cool) + (lc["duration_s"] if lc else 0)
    findings.append(_finding(
        "cooldown", "dismiss", "收操",
        f"最後一趟之後的跑動（含當天下一筆紀錄）共 {fmt_duration(cool_moving)}",
        None, seconds=cool_moving))


# ---------------------------------------------------------------- history


def _history_findings(summary: dict, history: list[dict], findings: list[dict]) -> None:
    """Against this athlete's own earlier sessions of the same workout
    (newest first): last time, the usual range across them, heart rate at
    the same pace, and how fast heart rate came down during the rests."""
    current = summary.get("mean_work_pace_s_per_km") or summary.get("split_mean_pace_s_per_km")
    if not current:
        return
    prev = history[0]
    prev_pace = prev.get("mean_pace_s_per_km")
    if not prev_pace:
        return
    delta = current - prev_pace  # + = slower today
    hr_now, hr_prev = summary.get("mean_rep_hr"), prev.get("mean_rep_hr")
    summary["history_comparison"] = {"date": prev["date"], "signature": prev["signature"],
                                     "prev_pace_s_per_km": prev_pace, "delta_s_per_km": round(delta, 1),
                                     "prev_mean_rep_hr": hr_prev}
    detail = (f"上次同樣的課表（{prev['date']}，{prev['signature']}）平均 {fmt_pace(prev_pace)}，今天 {fmt_pace(current)}"
              f"（{'快' if delta < 0 else '慢'} {abs(delta):.1f} 秒/km）")
    if hr_now and hr_prev:
        detail += f"，各趟平均心率 {hr_now} bpm（上次 {hr_prev} bpm）"
    detail = _with_range(detail, round(current, 1), history, "mean_pace_s_per_km",
                         lambda x: fmt_pace(x) or "", above="慢於", below="快於")
    title = "與上次同課表比較"

    # Heart rate in the last 60 s of reps of >= 3 min (Buchheit 2014), against
    # last time: no slower beyond the watch's 1 s timing resolution over one
    # rep, and lower beyond submaximal heart rate's day-to-day measurement
    # error (Lamberts et al. 2004) -- "the lower the HR, the fitter"
    # (Buchheit 2014). A higher heart rate is stated, not judged: it "should
    # not be used as a clear marker of fatigue" (Buchheit 2014).
    severity = "info"
    steady_now, steady_prev = summary.get("steady_rep_hr"), prev.get("steady_rep_hr")
    rep_count, work_m = summary.get("rep_count"), summary.get("work_distance_m")
    if steady_now and steady_prev and rep_count and work_m and summary.get("mean_work_pace_s_per_km"):
        resolution = 1000 / (work_m / rep_count)  # s/km for 1 s over one rep
        hr_gap = HOPKINS_Z * SUBMAX_HR_SEM_PCT / 100 * math.sqrt(2) * steady_prev
        gap = steady_prev - steady_now  # + = lower today
        summary["steady_hr_comparison"] = {"pace_resolution_s_per_km": round(resolution, 1),
                                           "hr_error_bpm": round(hr_gap, 1), "hr_change_bpm": round(-gap, 1)}
        basis = (f"。每趟最後 60 秒的平均心率 {steady_now:.0f} bpm（上次 {steady_prev:.0f} bpm），"
                 f"次最大心率的日間測量誤差約 {hr_gap:.1f} bpm")
        if delta <= resolution and gap > hr_gap:
            severity = "positive"
            title = f"配速{'相同' if abs(delta) <= resolution else '更快'}、心率更低：朝好的方向"
            detail += basis + "；同樣或更快的配速下心率較低，是有氧體能改善的方向（Buchheit 2014）"
        elif -gap > hr_gap:
            detail += basis + "；心率比上次高，但心率上升不能單獨當成疲勞的指標（Buchheit 2014）"
    findings.append(_finding("history", severity, title, detail, None, delta_s_per_km=round(delta, 1)))

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
        k = len(past_drops)
        # HRR60 typical error 10.9 % (Bonato et al. 2018); today vs the mean
        # of k sessions differs by chance within z x CV x sqrt(1 + 1/k)
        margin = HOPKINS_Z * HRR60_CV_PCT * math.sqrt(1 + 1 / k)
        change = (drop_now - past) / past * 100
        summary["recovery_comparison"] = {"past_mean_hr_drop": round(past), "sessions": k,
                                          "change_pct": round(change, 1), "margin_pct": round(margin, 1)}
        basis = (f"今天休息 60 秒內心率平均下降 {drop_now} bpm，過去 {k} 次同課表平均 {round(past)} bpm"
                 f"（差 {_signed(change, '%')}；這項量測的誤差範圍約 ±{margin:.1f}%）")
        if change < -margin:
            title = "休息時心率降得比過去慢，超出誤差範圍"
        elif change > margin:
            title = "休息時心率降得比過去快，超出誤差範圍"
        else:
            title = "休息時心率下降與過去的差距在誤差範圍內"
        findings.append(_finding(
            "recovery_trend", "dismiss", title, basis,
            "如果你同時覺得比平常累，告訴教練：恢復變快加上疲勞感，可能是過度訓練的早期訊號（Aubry 2015）"
            if change > margin else None, change_pct=round(change, 1)))
