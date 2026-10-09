"""Workout structure detection for one recorded run.

Given a run's 1 Hz telemetry (distance, speed, heart rate, cadence), its
laps and its timer pause/resume events, works out which stretches were the
workout's reps and which were warm-up / recovery / cool-down -- the thing
a coach reads off a lap sheet. On a track a watch usually auto-laps every
400 m regardless of the session, so the 400 m laps alone say nothing about
whether today was 10x400, 6x1000 or 5x1200; this reads the actual effort.

Method (every threshold is relative to this run or this athlete -- there is
no universal "interval pace"):

1. Speed is fitted as a piecewise-constant signal with PELT change-point
   detection (Killick, Fearnhead & Eckley 2012, L2 cost). Each rep and each
   recovery becomes one flat plateau however short, so eight 20 s strides
   are eight segments rather than 160 samples outvoted by an hour of easy
   running. A structured watch workout's laps (which already cut at every
   step) and a sparsely sampled sprint session's manual laps are used as
   the plateaus directly.
2. Two independent readings are built and the more workout-like one wins:
   "change_points" (work = the faster class of plateau levels; handles jog
   and float recoveries) and "stops" (work = each moving stretch between
   standing / paused recoveries), plus "continuous" as the default that a
   reading has to clearly beat.
3. Rep boundaries are snapped to the athlete's own manual lap presses and
   to the watch's pause / resume times -- GPS speed lags 10-30 s behind a
   standing start, the lap button does not.
4. Reps are matched to standard track distances (or round durations for
   time-based reps), set breaks are found from the recovery pattern, and a
   confidence with plain-language reasons is attached for the athlete to
   confirm or correct.

Validated against the 43 sessions in the demo athlete's own Garmin history
whose activity name records the prescribed workout (e.g. "400 x 10 組休1分鐘
84/圈"): 37 detected exactly; of the other 6, 4 are recordings that do not
contain what the name says (a rep stopped part-way, the watch ended early).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from typing import Any

MOVING_SPEED = 1.6          # m/s (~10:25 /km); slower is walking or standing
SMOOTH_WINDOW_S = 7
MIN_SEPARATION = 0.12       # work vs easy plateau levels must differ by >= 12%
MIN_WORK_BOUT_S = 12
MERGE_GAP_S = 6
LAP_SNAP_S = 20
TIMER_SNAP_S = 12
RESUME_LAG_S = 30
MAIN_SET_GAP_M = 600
MAIN_SET_GAP_S = 240
MIN_SEGMENT_S = 10
MIN_PLATEAU_S = 8
PELT_MIN_SIZE = 5
LEVEL_MERGE_RATIO = 0.04
EASY_MARGIN = 1.08          # a rep must be >= 8% faster than the athlete's easy pace

STANDARD_DISTANCES = [60, 80, 100, 120, 150, 200, 250, 300, 400, 500, 600, 800, 1000, 1200,
                      1500, 1600, 2000, 2400, 3000, 3200, 4000, 5000]
STANDARD_DURATIONS = [10, 15, 20, 30, 45, 60, 90, 120, 150, 180, 240, 300, 360, 420, 480, 600]

SEGMENT_ROLES = ("warmup", "work", "rest", "set_rest", "strides", "cooldown", "steady")


# --------------------------------------------------------------------------
# 1 Hz grid


@dataclass
class Grid:
    d: list[float]               # cumulative distance, m
    v: list[float]               # speed, m/s (0 while paused)
    vs: list[float]              # speed, 7 s centred mean
    hr: list[float | None]
    cad: list[float | None]
    paused: list[bool]
    # exact distances for (start, end) spans taken from the athlete's own
    # laps, which beat GPS interpolation on a sparsely sampled recording
    lap_distance: dict[tuple[int, int], float] = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.d)

    def dist(self, a: int, b: int) -> float:
        return self.d[min(b, self.n - 1)] - self.d[min(a, self.n - 1)]


def pause_intervals(timer_events: list) -> list[tuple[float, float]]:
    """(stop, resume) pairs from the watch's timer events."""
    pauses = []
    stop_at = None
    for at, kind in sorted((float(e[0]), str(e[1])) for e in timer_events):
        if "stop" in kind and stop_at is None:
            stop_at = at
        elif kind == "start" and stop_at is not None:
            pauses.append((stop_at, at))
            stop_at = None
    return pauses


def build_grid(samples: dict, timer_events: list) -> Grid:
    ts = samples["t"]
    n = (ts[-1] + 1) if ts else 0
    d = [math.nan] * n
    v = [math.nan] * n
    hr: list[float | None] = [None] * n
    cad: list[float | None] = [None] * n
    for t, dd, vv, h, c in zip(ts, samples["d"], samples["v"], samples["hr"], samples["cad"]):
        if 0 <= t < n:
            if dd is not None:
                d[t] = dd
            if vv is not None:
                v[t] = vv
            hr[t] = h
            cad[t] = c
    paused = [False] * n
    for a, b in pause_intervals(timer_events):
        for i in range(max(0, math.ceil(a)), min(n, int(b))):
            paused[i] = True
    _fill_linear(d)
    for i in range(n):
        if paused[i]:
            v[i] = 0.0
    _fill_linear(v)
    _fill_hold(hr)
    _fill_hold(cad)
    d = [0.0 if x != x else x for x in d]
    v = [0.0 if x != x else x for x in v]
    return Grid(d, v, _rolling_mean(v, SMOOTH_WINDOW_S), hr, cad, paused)


def _fill_linear(arr: list[float]) -> None:
    known = [i for i, x in enumerate(arr) if x == x]
    if not known:
        return
    for a, b in zip(known, known[1:]):
        if b - a > 1:
            for j in range(a + 1, b):
                arr[j] = arr[a] + (arr[b] - arr[a]) * (j - a) / (b - a)
    for j in range(known[0]):
        arr[j] = arr[known[0]]
    for j in range(known[-1] + 1, len(arr)):
        arr[j] = arr[known[-1]]


def _fill_hold(arr: list, max_gap: int = 10) -> None:
    last = None
    gap = 0
    for i, x in enumerate(arr):
        if x is None:
            gap += 1
            if last is not None and gap <= max_gap:
                arr[i] = last
        else:
            last = x
            gap = 0


def _rolling_mean(arr: list[float], w: int) -> list[float]:
    half = w // 2
    pref = [0.0]
    for x in arr:
        pref.append(pref[-1] + x)
    n = len(arr)
    return [(pref[min(n, i + half + 1)] - pref[max(0, i - half)]) / (min(n, i + half + 1) - max(0, i - half))
            for i in range(n)]


# --------------------------------------------------------------------------
# plateaus


@dataclass
class Plateau:
    start: int
    end: int
    level: float


def _median3(arr: list[float]) -> list[float]:
    n = len(arr)
    out = []
    for i in range(n):
        window = sorted(arr[max(0, i - 1):min(n, i + 2)])
        out.append(window[len(window) // 2])
    return out


def pelt_plateaus(g: Grid) -> list[Plateau]:
    """Piecewise-constant fit of speed via PELT with an L2 cost and a
    penalty scaled to this recording's own sample-to-sample noise."""
    x = _median3(g.v)
    n = len(x)
    if n == 0:
        return []
    s1 = [0.0]
    s2 = [0.0]
    for val in x:
        s1.append(s1[-1] + val)
        s2.append(s2[-1] + val * val)
    diffs = sorted(abs(x[i + 1] - x[i]) for i in range(n - 1))
    mad = diffs[len(diffs) // 2] if diffs else 0.0
    sigma2 = max((mad / 0.6745) ** 2 / 2, 0.01)
    beta = 4.0 * sigma2 * math.log(max(n, 2))

    def cost(a: int, b: int) -> float:
        t1 = s1[b] - s1[a]
        return (s2[b] - s2[a]) - t1 * t1 / (b - a)

    best_cost = [0.0] * (n + 1)
    best_cost[0] = -beta
    last_cp = [0] * (n + 1)
    candidates = [0]
    for t in range(PELT_MIN_SIZE, n + 1):
        best_val, best_s = math.inf, 0
        scored = []
        for s in candidates:
            if t - s < PELT_MIN_SIZE:
                scored.append((s, None))
                continue
            val = best_cost[s] + cost(s, t) + beta
            scored.append((s, val))
            if val < best_val:
                best_val, best_s = val, s
        best_cost[t] = best_val
        last_cp[t] = best_s
        candidates = [s for s, val in scored if val is None or val - beta <= best_val]
        candidates.append(t - PELT_MIN_SIZE + 1)
    cps = []
    t = n
    while t > 0:
        cps.append(t)
        t = last_cp[t]
    plateaus = []
    a = 0
    for b in sorted(cps):
        if b > a:
            plateaus.append(Plateau(a, b, (s1[b] - s1[a]) / (b - a)))
            a = b
    merged: list[Plateau] = []
    for p in plateaus:
        if merged:
            q = merged[-1]
            hi, lo = max(p.level, q.level), min(p.level, q.level)
            if hi < MOVING_SPEED or (lo >= MOVING_SPEED and (hi - lo) / lo < LEVEL_MERGE_RATIO):
                wq, wp = q.end - q.start, p.end - p.start
                merged[-1] = Plateau(q.start, p.end, (q.level * wq + p.level * wp) / (wq + wp))
                continue
        merged.append(p)
    return merged


def split_levels(levels: list[float]) -> tuple[float, float]:
    """Optimal two-class split (minimum within-class variance, every
    plateau weighted equally) of plateau speed levels into "easy/recovery"
    and "work". Returns the threshold and the relative separation of the
    two class means."""
    lv = sorted(levels)
    if len(lv) < 2:
        return (lv[0] if lv else MOVING_SPEED), 0.0
    best = (math.inf, lv[-1], 0.0)
    for k in range(1, len(lv)):
        lo, hi = lv[:k], lv[k:]
        mlo, mhi = statistics.fmean(lo), statistics.fmean(hi)
        within = sum((x - mlo) ** 2 for x in lo) + sum((x - mhi) ** 2 for x in hi)
        if within < best[0]:
            best = (within, (lv[k - 1] + lv[k]) / 2, (mhi - mlo) / mlo)
    return best[1], best[2]


# --------------------------------------------------------------------------
# laps


def lap_bounds(tele: dict) -> list[tuple[dict, float, float]]:
    """(lap, start_s, end_s) with end = the next lap's start. A FIT lap
    that contains a pause starts at the resume time but counts its elapsed
    time from the previous lap's end, so start + elapsed overshoots; the
    next lap's start never does."""
    laps = [lap for lap in tele.get("laps", []) if lap.get("start_offset_s") is not None]
    out = []
    for i, lap in enumerate(laps):
        start = lap["start_offset_s"]
        if i + 1 < len(laps):
            end = laps[i + 1]["start_offset_s"]
        else:
            end = start + (lap.get("timer_s") or lap.get("elapsed_s") or 0)
        out.append((lap, start, max(start, end)))
    return out


def _is_athlete_marked(lap: dict) -> bool:
    structured = lap.get("wkt_step") is not None and lap.get("trigger") in ("time", "distance", "manual")
    return lap.get("trigger") == "manual" or structured


def _is_structured_workout(tele: dict) -> bool:
    laps = tele.get("laps", [])
    stepped = sum(1 for lap in laps if lap.get("wkt_step") is not None)
    return bool(tele.get("workout_steps")) and len(laps) >= 4 and stepped >= 0.5 * len(laps)


def _longest_run(a: int, b: int, stopped) -> tuple[int, int] | None:
    best = None
    i = a
    while i < b:
        if stopped(i):
            i += 1
            continue
        j = i
        while j < b and not stopped(j):
            j += 1
        if best is None or j - i > best[1] - best[0]:
            best = (i, j)
        i = j
    return best


def _lap_plateaus(tele: dict, g: Grid) -> list[Plateau]:
    """Laps as plateaus. The paused parts of a lap are stops, not part of
    the step's effort; the longest unpaused stretch is the effort itself (a
    lap pressed just before pausing starts one second before the pause)."""
    out = []
    for lap, start, end in lap_bounds(tele):
        a, b = max(0, round(start)), min(g.n, round(end))
        if b <= a:
            continue
        run = _longest_run(a, b, lambda i: g.paused[i])
        if run is None:
            out.append(Plateau(a, b, 0.0))
            continue
        i0, i1 = run
        if i0 > a:
            out.append(Plateau(a, i0, 0.0))
        dist = lap.get("distance_m")
        if dist is not None:
            g.lap_distance[(i0, i1)] = dist
        else:
            dist = g.dist(i0, i1)
        out.append(Plateau(i0, i1, dist / (i1 - i0)))
        if b > i1:
            out.append(Plateau(i1, b, 0.0))
    return out


def _athlete_lap_marks(tele: dict) -> list[int]:
    marks = set()
    for lap, start, end in lap_bounds(tele):
        if _is_athlete_marked(lap):
            marks.add(round(start))
            marks.add(round(end))
    return sorted(marks)


def _athlete_lap_spans(tele: dict, g: Grid) -> list[tuple[int, int, float]]:
    """Moving part of every lap the athlete marked themselves. A lap
    pressed only at the end of each rep, with the watch paused through the
    recovery, spans "recovery + rep"; its longest unbroken moving stretch
    is the rep."""
    spans = []
    for lap, start, end in lap_bounds(tele):
        if not _is_athlete_marked(lap):
            continue
        a, b = max(0, round(start)), min(g.n, round(end))
        run = _longest_run(a, b, lambda i: g.paused[i] or g.v[i] < MOVING_SPEED)
        if run is not None:
            spans.append((run[0], run[1], g.dist(run[0], run[1]) / (run[1] - run[0])))
    return spans


# --------------------------------------------------------------------------
# bouts


@dataclass
class Bout:
    start: int
    end: int  # exclusive
    interruptions: list[tuple[int, int]] = field(default_factory=list)

    @property
    def duration(self) -> int:
        return self.end - self.start


def bout_distance(g: Grid, b: Bout) -> float:
    if (b.start, b.end) in g.lap_distance:
        return g.lap_distance[(b.start, b.end)]
    total = g.dist(b.start, b.end)
    for s, e in b.interruptions:
        total -= g.dist(s, e)
    return total


def bout_speed(g: Grid, b: Bout) -> float:
    moving = b.duration - sum(e - s for s, e in b.interruptions)
    return bout_distance(g, b) / max(1, moving)


def _runs(flags: list[bool]) -> list[Bout]:
    out = []
    i, n = 0, len(flags)
    while i < n:
        if flags[i]:
            j = i
            while j < n and flags[j]:
                j += 1
            out.append(Bout(i, j))
            i = j
        else:
            i += 1
    return out


def snap_distance(gps_m: float, tolerance_ratio: float) -> int | None:
    best = min(STANDARD_DISTANCES, key=lambda s: abs(s - gps_m))
    return best if abs(best - gps_m) <= max(15.0, best * tolerance_ratio) else None


def snap_duration(sec: float) -> int | None:
    best = min(STANDARD_DURATIONS, key=lambda s: abs(s - sec))
    return best if abs(best - sec) <= 3 else None


def _merge_short_gaps(bouts: list[Bout], g: Grid) -> list[Bout]:
    out: list[Bout] = []
    for b in bouts:
        if out and b.start - out[-1].end <= MERGE_GAP_S:
            if min(g.vs[out[-1].end:b.start] or [MOVING_SPEED]) >= MOVING_SPEED:
                out[-1] = Bout(out[-1].start, b.end)
                continue
        out.append(b)
    return out


def _snap_to_athlete_marks(b: Bout, marks: list[int], timer_marks: list[int], n: int,
                           lap_spans: list[tuple[int, int, float]], work_threshold: float) -> Bout:
    # a single lap the athlete marked that covers this bout is their own
    # record of the rep -- adopt its exact boundaries
    for ls, le, level in lap_spans:
        if level < work_threshold:
            continue
        inter = min(le, b.end) - max(ls, b.start)
        union = max(le, b.end) - min(ls, b.start)
        if union > 0 and inter / union >= 0.8:
            return Bout(max(0, ls), min(n, le))

    def nearest(x: int) -> int:
        best = min(marks, key=lambda m: abs(m - x), default=None)
        if best is not None and abs(best - x) <= LAP_SNAP_S:
            return best
        best = min(timer_marks, key=lambda m: abs(m - x), default=None)
        if best is not None and abs(best - x) <= TIMER_SNAP_S:
            return best
        return x

    s, e = nearest(b.start), nearest(b.end)
    if e - s < MIN_WORK_BOUT_S:
        return b
    return Bout(max(0, s), min(n, e))


def _extend_to_timer(b: Bout, timer_events: list, g: Grid) -> Bout:
    """GPS speed needs 10-30 s to recover after the watch resumes, so a rep
    that starts right at a resume is first seen late. If the watch was
    resumed shortly before the detected start (or paused shortly after the
    detected end) and the distance trace shows the athlete was already
    running in between, the resume / pause is the true boundary."""
    events = [(round(float(at)), str(kind)) for at, kind in timer_events]
    speed = bout_speed(g, b)
    start, end = b.start, b.end
    resumes = [at for at, kind in events if kind == "start" and b.start - RESUME_LAG_S <= at < b.start]
    if resumes:
        at = max(resumes)
        if g.dist(at, b.start) / max(1, b.start - at) >= 0.5 * speed:
            start = at
    stops = [at for at, kind in events if "stop" in kind and b.end < at <= b.end + RESUME_LAG_S]
    if stops:
        at = min(stops)
        if g.dist(b.end, at) / max(1, at - b.end) >= 0.5 * speed:
            end = at
    return Bout(start, end) if (start, end) != (b.start, b.end) else b


def _dedupe_overlaps(bouts: list[Bout]) -> list[Bout]:
    out: list[Bout] = []
    for b in sorted(bouts, key=lambda x: x.start):
        if out and b.start < out[-1].end:
            if out[-1].end - b.start <= 10 and b.end - out[-1].end >= MIN_WORK_BOUT_S:
                # boundary jitter between two genuine reps -- clip, don't merge
                out.append(Bout(out[-1].end, b.end))
                continue
            out[-1] = Bout(out[-1].start, max(out[-1].end, b.end))
        else:
            out.append(b)
    return out


def _main_set_groups(bouts: list[Bout], g: Grid) -> list[Bout]:
    """Bouts separated by a long stretch of continuous jogging (a surge in
    the warm-up, a stride before the session) are not part of the set."""
    if len(bouts) < 2:
        return bouts
    groups: list[list[Bout]] = [[bouts[0]]]
    for prev, b in zip(bouts, bouts[1:]):
        if g.dist(prev.end, b.start) > MAIN_SET_GAP_M and b.start - prev.end > MAIN_SET_GAP_S:
            groups.append([b])
        else:
            groups[-1].append(b)
    if len(groups) == 1:
        return bouts
    main = max(groups, key=lambda grp: sum(x.duration for x in grp))
    main_speed = statistics.median(bout_speed(g, x) for x in main)
    main_median_dur = statistics.median(x.duration for x in main)
    kept: list[Bout] = []
    for grp in groups:
        if grp is main or len(grp) >= 2:
            kept.extend(grp)
            continue
        b = grp[0]
        short_stride = b.duration < 30 and bout_distance(g, b) < 200
        comparable = b.duration >= 0.5 * main_median_dur and bout_speed(g, b) >= 0.95 * main_speed
        if short_stride or comparable or b.duration >= 8 * 60:
            kept.append(b)
    return sorted(kept, key=lambda x: x.start)


def _merge_interruptions(bouts: list[Bout], g: Grid, tol: float) -> list[Bout]:
    """A short stop inside a rep (auto-pause, someone on the track, a shoe)
    is not a recovery: merge the two halves when the gap is far shorter
    than this session's normal recovery and the halves together land on a
    standard distance that one half alone does not."""
    if len(bouts) < 3:
        return bouts
    median_gap = statistics.median(b.start - a.end for a, b in zip(bouts, bouts[1:]))
    known = [x for x in (snap_distance(bout_distance(g, b), tol) for b in bouts) if x]
    usual = statistics.mode(known) if known else None
    out = [bouts[0]]
    for b in bouts[1:]:
        a = out[-1]
        gap = b.start - a.end
        combined = snap_distance(bout_distance(g, a) + bout_distance(g, b), tol)
        snap_a = snap_distance(bout_distance(g, a), tol)
        snap_b = snap_distance(bout_distance(g, b), tol)
        # both halves can land on standard distances (a 1000 stopped at 600
        # m is 600 + 400): then the whole must be the session's usual rep
        # and neither half that rep on its own
        halves_odd = snap_a is None or snap_b is None
        whole_is_usual = combined == usual and usual not in (snap_a, snap_b)
        if (gap <= 45 and gap < 0.35 * median_gap and combined is not None
                and (halves_odd or whole_is_usual)):
            out[-1] = Bout(a.start, b.end, a.interruptions + [(a.end, b.start)] + b.interruptions)
        else:
            out.append(b)
    return out


def _use_lap_distances(bouts: list[Bout], tele: dict, g: Grid) -> None:
    """A rep that starts at one watch lap boundary and ends at another
    covers exactly those laps, and the watch's lap distance (corrected in
    track mode) beats the per-second GPS trace, which on a track can read a
    200 m rep as 170 m. Record it for the rep."""
    laps = [(round(s), round(e), lap.get("distance_m"), lap.get("timer_s")) for lap, s, e in lap_bounds(tele)]
    if not laps:
        return
    for b in bouts:
        if b.interruptions:
            continue
        # the rep's own start / end can sit a few seconds inside the lap
        # (GPS speed lags a standing start); the laps' timed duration must
        # still match the rep, so it is the same stretch of running
        starts = [k for k, lap in enumerate(laps) if b.start - 8 <= lap[0] <= b.start + 2]
        ends = [k for k, lap in enumerate(laps) if b.end - 2 <= lap[1] <= b.end + 8]
        if not starts or not ends or ends[0] < starts[-1]:
            continue
        i, j = starts[-1], ends[0]
        span = laps[i:j + 1]
        if any(lap[2] is None or lap[2] <= 0 or lap[3] is None for lap in span):
            continue
        timed = sum(lap[3] for lap in span)
        if abs(timed - b.duration) <= max(5.0, 0.15 * b.duration):
            g.lap_distance[(b.start, b.end)] = float(sum(lap[2] for lap in span))


def _trim_slow_edges(main: list[Bout], g: Grid) -> list[Bout]:
    """Stretches outside the session's main block of repeats (>= 3
    consecutive reps of one distance) that are clearly slower than that
    block -- a build-up in the warm-up, the start of the cool-down -- are
    not reps. Anything that is itself repeated (6x1000 + 8x300 keeps both
    blocks) or a sustained effort of >= 6 min (a 2000 m tempo before 4x200)
    is kept, and only a run reaching the session's edge is trimmed."""
    if len(main) < 4:
        return main
    noms = [snap_distance(bout_distance(g, b), 0.08) for b in main]
    best = None
    i = 0
    while i < len(main):
        j = i
        while j < len(main) and noms[j] is not None and noms[j] == noms[i]:
            j += 1
        if j - i >= 3 and (best is None or j - i > best[1] - best[0]):
            best = (i, j)
        i = max(j, i + 1)
    if best is None:
        return main
    lo, hi = best
    ref = statistics.median(bout_speed(g, b) for b in main[lo:hi])

    def repeated(k: int) -> bool:
        return noms[k] is not None and (
            (k > 0 and noms[k - 1] == noms[k]) or (k + 1 < len(main) and noms[k + 1] == noms[k]))

    def droppable(k: int) -> bool:
        b = main[k]
        return not repeated(k) and b.duration < 6 * 60 and bout_speed(g, b) < 0.95 * ref

    lead = lo if all(droppable(k) for k in range(lo)) else 0
    trail = hi if all(droppable(k) for k in range(hi, len(main))) else len(main)
    return main[lead:trail]


# --------------------------------------------------------------------------
# detection


def detect_workout(tele: dict, easy_speed: float | None = None) -> dict[str, Any]:
    """Detect the workout structure of one activity.

    `tele` is the stored telemetry (samples / laps / timer_events /
    sub_sport / workout_steps). `easy_speed` is the athlete's own easy
    running speed (m/s) from their history when known: a "rep" not clearly
    faster than that is not a rep (an easy run broken up by traffic lights
    is still an easy run).

    Returns {kind, method, segments, confidence, reasons, hints, signature}.
    kind is "intervals" | "tempo" | "continuous" | "insufficient". Each
    segment is {role, start_s, end_s, nominal_m?, nominal_s?,
    interruptions?}, start/end in seconds from the activity start."""
    timer_events = tele.get("timer_events") or []
    g = build_grid(tele["samples"], timer_events)
    structured = _is_structured_workout(tele)
    plateaus = _lap_plateaus(tele, g) if structured else pelt_plateaus(g)
    moving = [p for p in plateaus if p.level >= MOVING_SPEED and p.end - p.start >= MIN_PLATEAU_S]
    if sum(p.end - p.start for p in moving) < 60 and len(tele.get("laps", [])) >= 3:
        # "smart recording" can log a sprint session with a sample every
        # 10-30 s; the laps the athlete pressed are then the exact record
        structured = True
        plateaus = _lap_plateaus(tele, g)
        moving = [p for p in plateaus if p.level >= MOVING_SPEED and p.end - p.start >= MIN_PLATEAU_S]
    if sum(p.end - p.start for p in moving) < 60:
        return {"kind": "insufficient", "method": None, "segments": [], "confidence": 0.0,
                "reasons": ["移動時間不足，無法判讀課表"], "hints": [], "signature": None}
    thr, separation = split_levels([p.level for p in moving])
    high = [p for p in moving if p.level >= thr]
    meaningful_high = len(high) >= 2 or any(p.end - p.start >= 8 * 60 for p in high)

    continuous = _continuous(g, separation)
    readings = [(0.5, continuous)]
    if separation >= MIN_SEPARATION and meaningful_high:
        r = _read(tele, g, plateaus, "watch_steps" if structured else "change_points", thr, separation, easy_speed)
        readings.append((_structure_score(r), r))
        # three pace levels -- easy jogging around the session, "float"
        # recoveries, and the reps: the first split lumps floats in with the
        # reps, so also try splitting the fast class once more
        if len(high) >= 4:
            thr2, sep2 = split_levels([p.level for p in high])
            if sep2 >= MIN_SEPARATION:
                r = _read(tele, g, plateaus, "change_points", thr2, sep2, easy_speed)
                readings.append((_structure_score(r), r))
    r = _read(tele, g, plateaus, "stops", MOVING_SPEED, separation, easy_speed)
    readings.append((_structure_score(r), r))
    return max(readings, key=lambda x: x[0])[1]


def _structure_score(result: dict) -> float:
    """How workout-like a reading is: reps that land on a standard
    distance / round time count for it, reps that land on nothing count
    against it, scaled by confidence. "continuous" is the default at 0.5,
    so an irregular reading has to clearly beat it."""
    if result["kind"] == "tempo":
        return result["confidence"]
    works = [s for s in result["segments"] if s["role"] == "work"]
    if result["kind"] != "intervals" or not works:
        return 0.0
    snapped = sum(1 for s in works if s.get("nominal_m") or s.get("nominal_s"))
    base = snapped - 2 * (len(works) - snapped) + (0.5 if result["method"] != "stops" else 0.0)
    return base * result["confidence"] if base > 0 else base


def _read(tele: dict, g: Grid, plateaus: list[Plateau], method: str, thr: float, separation: float,
          easy_speed: float | None) -> dict[str, Any]:
    n = g.n
    track_like = tele.get("sub_sport") in ("track", "treadmill")
    tol = 0.05 if track_like else 0.08
    timer_events = tele.get("timer_events") or []
    level_floor = thr if method != "stops" else MOVING_SPEED
    work_flags = [False] * n
    for p in plateaus:
        if p.level >= level_floor:
            for i in range(p.start, p.end):
                work_flags[i] = True

    bouts = _merge_short_gaps(_runs(work_flags), g)
    bouts = [b for b in bouts if b.duration >= MIN_WORK_BOUT_S]
    marks = _athlete_lap_marks(tele)
    timer_marks = sorted({round(float(at)) for at, _k in timer_events})
    spans = _athlete_lap_spans(tele, g)
    bouts = [_snap_to_athlete_marks(b, marks, timer_marks, n, spans, thr) for b in bouts]
    bouts = [_extend_to_timer(b, timer_events, g) for b in bouts]
    bouts = _dedupe_overlaps(bouts)
    bouts = _main_set_groups(bouts, g)
    _use_lap_distances(bouts, tele, g)
    bouts = _merge_interruptions(bouts, g, tol)

    if easy_speed:
        bouts = [b for b in bouts if bout_speed(g, b) >= EASY_MARGIN * easy_speed]
    if method == "stops" and len(bouts) >= 3:
        # warm-up / cool-down jogs between stops are moving bouts too, but
        # far slower than the reps: peel them off the ends
        top = sorted((bout_speed(g, b) for b in bouts), reverse=True)
        ref = statistics.median(top[: max(2, len(top) // 2)])
        while bouts and bout_speed(g, bouts[0]) < 0.80 * ref:
            bouts = bouts[1:]
        while bouts and bout_speed(g, bouts[-1]) < 0.80 * ref:
            bouts = bouts[:-1]
    if not bouts or (method == "stops" and len(bouts) <= 1):
        return _continuous(g, separation)

    # strides around the main set
    durations = [b.duration for b in bouts]
    long_median = statistics.median([x for x in durations if x >= 30] or durations)
    main: list[Bout] = []
    strides: list[Bout] = []
    if long_median >= 45:
        first_main = next((i for i, b in enumerate(bouts) if b.duration >= 30), 0)
        last_main = max((i for i, b in enumerate(bouts) if b.duration >= 30), default=len(bouts) - 1)
        for i, b in enumerate(bouts):
            if b.duration < 30 and bout_distance(g, b) < 200 and (i < first_main or i > last_main):
                strides.append(b)
            else:
                main.append(b)
    else:
        main = bouts

    main = _trim_slow_edges(main, g)
    if len(main) == 1:
        b = main[0]
        # a tempo is one sustained effort clearly above easy pace with
        # easier running around it -- not simply the whole run
        faster = bout_speed(g, b) >= 1.10 * easy_speed if easy_speed else separation >= 0.15
        if b.duration >= 8 * 60 and faster and b.duration <= 0.85 * n:
            kind = "tempo"
        else:
            return _continuous(g, separation)
    else:
        kind = "intervals"

    reps = [{"gps_m": bout_distance(g, b), "dur": b.duration - sum(e - s for s, e in b.interruptions),
             "nominal_m": snap_distance(bout_distance(g, b), tol) if kind == "intervals" else None,
             "nominal_s": None} for b in main]
    time_based = kind == "intervals" and _assign_time_based(reps)

    segments: list[dict[str, Any]] = []

    def add(role: str, a: int, b: int, **extra: Any) -> None:
        if b - a <= 0 or (role in ("warmup", "cooldown") and b - a < MIN_SEGMENT_S):
            return
        segments.append({"role": role, "start_s": a, "end_s": b, **extra})

    timeline = sorted([(b, "work") for b in main] + [(b, "strides") for b in strides], key=lambda x: x[0].start)
    add("warmup", 0, timeline[0][0].start)
    rep_index = 0
    for k, (b, role) in enumerate(timeline):
        if role == "work":
            r = reps[rep_index]
            rep_index += 1
            extra: dict[str, Any] = {"nominal_m": r["nominal_m"], "nominal_s": r["nominal_s"]}
            if b.interruptions:
                extra["interruptions"] = [[s, e] for s, e in b.interruptions]
            add("work", b.start, b.end, **extra)
        else:
            add("strides", b.start, b.end)
        if k + 1 < len(timeline):
            add("rest", b.end, timeline[k + 1][0].start)
    add("cooldown", timeline[-1][0].end, n)

    _mark_sets(segments, time_based)
    confidence, reasons, hints = _confidence(g, segments, reps, separation, method, time_based, kind, easy_speed)
    return {
        "kind": kind,
        "method": method,
        "time_based": time_based,
        "segments": segments,
        "confidence": confidence,
        "reasons": reasons,
        "hints": hints,
        "signature": signature(segments, kind, g),
    }


def _assign_time_based(reps: list[dict]) -> bool:
    """Time-based reps (6x60 s): durations land on round times and are far
    more consistent than the distances covered in them. Otherwise, pull a
    stray rep onto the session's usual distance when within 10%."""
    if len(reps) >= 2:
        snapped_t = [snap_duration(r["dur"]) for r in reps]
        distance_snapped = sum(1 for r in reps if r["nominal_m"])
        if sum(1 for x in snapped_t if x) >= 0.8 * len(reps) and distance_snapped < 0.8 * len(reps):
            keys = [x or 0 for x in snapped_t]
            dist_cv = _grouped_cv([r["gps_m"] for r in reps], keys)
            dur_cv = _grouped_cv([r["dur"] for r in reps], keys)
            if dur_cv < 0.03 and dist_cv > 1.5 * dur_cv + 0.005:
                for r, s in zip(reps, snapped_t):
                    r["nominal_s"] = s
                    r["nominal_m"] = None
                return True
    noms = [r["nominal_m"] for r in reps if r["nominal_m"]]
    if noms:
        mode = statistics.mode(noms)
        for r in reps:
            if r["nominal_m"] is None and abs(r["gps_m"] - mode) <= mode * 0.1:
                r["nominal_m"] = mode
    return False


def _grouped_cv(values: list[float], keys: list) -> float:
    groups: dict = {}
    for v, k in zip(values, keys):
        groups.setdefault(k, []).append(v)
    parts = [statistics.pstdev(vs) / statistics.fmean(vs) for vs in groups.values()
             if len(vs) >= 2 and statistics.fmean(vs)]
    return statistics.fmean(parts) if parts else 0.0


def _between_work(segments: list[dict], i: int) -> bool:
    return 0 < i < len(segments) - 1 and segments[i - 1]["role"] == "work" and segments[i + 1]["role"] == "work"


def _mark_sets(segments: list[dict], time_based: bool) -> None:
    """A long recovery is a set break only when it is structural: the rep
    type changes across it (6x60 s -> 6x30 s), or the long recoveries split
    the reps into equal-sized groups (3x(4x400)). One long recovery in an
    otherwise uniform set is just a long recovery."""
    rest_idx = [i for i, s in enumerate(segments) if s["role"] == "rest" and _between_work(segments, i)]
    if len(rest_idx) < 2:
        return
    med = statistics.median(segments[i]["end_s"] - segments[i]["start_s"] for i in rest_idx)
    long_idx = [i for i in rest_idx if segments[i]["end_s"] - segments[i]["start_s"] >= max(1.8 * med, med + 90)]
    if not long_idx:
        return
    key = "nominal_s" if time_based else "nominal_m"
    structural = [i for i in long_idx if segments[i - 1].get(key) != segments[i + 1].get(key)]
    sizes, count = [], 0
    for i, s in enumerate(segments):
        if s["role"] == "work":
            count += 1
        elif i in long_idx:
            sizes.append(count)
            count = 0
    sizes.append(count)
    if len(set(sizes)) == 1 and sizes[0] >= 2:
        structural = long_idx
    for i in structural:
        segments[i]["role"] = "set_rest"


def _seg_speed(g: Grid, s: dict) -> float:
    t = s["end_s"] - s["start_s"]
    return g.dist(s["start_s"], s["end_s"]) / t if t > 0 else 0.0


def _confidence(g: Grid, segments: list[dict], reps: list[dict], separation: float, method: str,
                time_based: bool, kind: str, easy_speed: float | None) -> tuple[float, list[str], list[dict]]:
    """0-1 confidence in the detected structure, with every deduction
    explained in plain words -- the athlete reads these on the
    confirmation screen before anything is analysed."""
    reasons: list[str] = []
    hints: list[dict] = []
    c = 1.0
    if method == "stops":
        reasons.append("每趟之間都有停下或走路恢復，強度段與恢復段界線明確")
    elif method == "watch_steps":
        reasons.append("依手錶結構化課表的每一步驟分段")
    elif separation < 0.2:
        c -= 0.1
        reasons.append(f"強度段與恢復段速度只差 {separation * 100:.0f}%，界線較模糊")
    else:
        reasons.append(f"強度段與恢復段速度差 {separation * 100:.0f}%，區隔明確")
    works = [s for s in segments if s["role"] == "work"]
    if kind == "intervals" and reps:
        unsnapped = sum(1 for r in reps if not (r["nominal_m"] or r["nominal_s"]))
        if unsnapped:
            c -= 0.4 * unsnapped / len(reps)
            reasons.append(f"{unsnapped} 趟的距離對不上常見課表距離")
        else:
            reasons.append("每趟時間都對齊整數秒數" if time_based else "每趟距離都對齊常見課表距離")
        work_speed = statistics.fmean(_seg_speed(g, s) for s in works)
        if any(s["role"] in ("rest", "set_rest") and _seg_speed(g, s) > 0.85 * work_speed for s in segments):
            c -= 0.1
            reasons.append("有一段恢復的速度接近強度段（浮動恢復），請確認分段")
        if easy_speed and work_speed < 1.15 * easy_speed:
            c -= 0.15
            reasons.append("強度段配速接近你平常的輕鬆跑配速")
        # two neighbouring reps, close together, that add up to another
        # rep's distance: most likely one rep with a stop in the middle
        noms = [s.get("nominal_m") for s in works]
        gaps = [works[k + 1]["start_s"] - works[k]["end_s"] for k in range(len(works) - 1)]
        median_gap = statistics.median(gaps) if gaps else 0
        # in a ladder or pyramid (2000-1600-1200-800-400) neighbouring reps
        # adding up to another rep is the design, not a stop
        for k in ([] if _is_ladder(noms) else range(len(works) - 1)):
            a, b = works[k], works[k + 1]
            if not (a.get("nominal_m") and b.get("nominal_m")) or gaps[k] >= 0.75 * median_gap:
                continue
            total = snap_distance(_seg_dist(g, a) + _seg_dist(g, b), 0.05)
            if total and total in noms and total not in (a["nominal_m"], b["nominal_m"]):
                c -= 0.2
                reasons.append(f"第 {k + 1}、{k + 2} 趟加起來正好 {total}m，可能是同一趟中途停下")
                hints.append({"type": "merge", "work_index": k, "total_m": total})
        if len(works) < 3:
            c -= 0.15
            reasons.append("強度段少於 3 趟")
    return round(max(0.05, min(1.0, c)), 2), reasons, hints


def _is_ladder(noms: list[int | None]) -> bool:
    """Strictly rising, strictly falling, or rising then falling."""
    if len(noms) < 3 or any(x is None for x in noms):
        return False
    k = 0
    while k + 1 < len(noms) and noms[k + 1] > noms[k]:
        k += 1
    while k + 1 < len(noms) and noms[k + 1] < noms[k]:
        k += 1
    return k == len(noms) - 1 and len(set(noms)) > 1


def _seg_dist(g: Grid, s: dict) -> float:
    return bout_distance(g, Bout(s["start_s"], s["end_s"], [tuple(x) for x in s.get("interruptions", [])]))


def _continuous(g: Grid, separation: float) -> dict[str, Any]:
    return {
        "kind": "continuous",
        "method": "continuous",
        "time_based": False,
        "segments": [{"role": "steady", "start_s": 0, "end_s": g.n}],
        "confidence": 0.9 if separation < 0.1 else 0.7,
        "reasons": ["整段沒有可辨識的強度／恢復交替，判讀為連續跑"],
        "hints": [],
        "signature": "continuous",
    }


def signature(segments: list[dict], kind: str, g: Grid | None = None) -> str:
    """Compact workout label: "6x1000m", "3x(4x400m)", "6x60s + 6x30s",
    "2000m-1600m-1200m-800m-400m", "tempo:6.2km", "continuous"."""
    works = [s for s in segments if s["role"] == "work"]
    if kind == "continuous" or not works:
        return "continuous"
    if kind == "tempo":
        w = works[0]
        km = (g.dist(w["start_s"], w["end_s"]) if g else (w.get("nominal_m") or 0)) / 1000
        return f"tempo:{km:.1f}km"

    def label(s: dict) -> str:
        if s.get("nominal_s"):
            return f"{s['nominal_s']}s"
        if s.get("nominal_m"):
            return f"{s['nominal_m']}m"
        if g is not None:
            return f"{round(_seg_dist(g, s))}m"
        return f"{s['end_s'] - s['start_s']}s"

    sets: list[list[str]] = [[]]
    for s in segments:
        if s["role"] == "work":
            sets[-1].append(label(s))
        elif s["role"] == "set_rest" and sets[-1]:
            sets.append([])

    def fmt(seq: list[str]) -> str:
        runs: list[list] = []
        for x in seq:
            if runs and runs[-1][0] == x:
                runs[-1][1] += 1
            else:
                runs.append([x, 1])
        if all(c == 1 for _x, c in runs):
            return "-".join(seq)
        return " + ".join(f"{c}x{x}" if c > 1 else x for x, c in runs)

    sets = [x for x in sets if x]
    if len(sets) > 1 and len({tuple(x) for x in sets}) == 1:
        return f"{len(sets)}x({fmt(sets[0])})"
    return " + ".join(fmt(x) for x in sets)
