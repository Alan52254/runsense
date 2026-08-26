/* Pure state-transition core for the Live Run Monitor (screens/athlete/LiveRunScreen.tsx).
 * Every function here takes the current timestamp as a parameter rather than
 * reading Date.now() itself, so elapsed-time/distance/pace/HR math is
 * testable with fixed clock values -- no real waiting, no timer mocking.
 * LiveRunContext is the only thing that touches Date.now() or setInterval.
 *
 * There is no GPS or heart-rate sensor anywhere in this app (deliberate --
 * see REQ-WEATHER-LOCATION-001, manual-entry-only). "Auto" mode below is a
 * declared simulation driven by a target pace the athlete sets, computed by
 * a pure formula from elapsed time -- not sensor data pretending to be real.
 * "Manual" mode is the athlete typing their own numbers, unchanged from
 * before. The screen must always be honest about which mode is active. */

export type RunTimerPhase = "idle" | "running" | "paused" | "finished";
export type RunTimerMode = "auto" | "manual";

export interface HrReading {
  atSec: number;
  bpm: number;
}

export interface RunTimerState {
  phase: RunTimerPhase;
  mode: RunTimerMode;
  accumulatedMs: number;
  runningSinceMs: number | null;
  targetPaceSecPerKm: number;
  /** Only meaningful in "manual" mode -- ignored while mode is "auto". */
  manualDistanceKm: number;
  manualHrLog: HrReading[];
}

const DEFAULT_TARGET_PACE_SEC_PER_KM = 330; // 5:30 /km, a moderate easy-run pace

export const initialRunTimerState: RunTimerState = {
  phase: "idle",
  mode: "auto",
  accumulatedMs: 0,
  runningSinceMs: null,
  targetPaceSecPerKm: DEFAULT_TARGET_PACE_SEC_PER_KM,
  manualDistanceKm: 0,
  manualHrLog: [],
};

export function elapsedMs(state: RunTimerState, nowMs: number): number {
  if (state.runningSinceMs === null) return state.accumulatedMs;
  return state.accumulatedMs + Math.max(0, nowMs - state.runningSinceMs);
}

export function start(state: RunTimerState, nowMs: number): RunTimerState {
  if (state.phase === "running") return state;
  return { ...state, phase: "running", runningSinceMs: nowMs };
}

export function pause(state: RunTimerState, nowMs: number): RunTimerState {
  if (state.phase !== "running") return state;
  return {
    ...state,
    phase: "paused",
    accumulatedMs: elapsedMs(state, nowMs),
    runningSinceMs: null,
  };
}

export function setMode(state: RunTimerState, mode: RunTimerMode): RunTimerState {
  return { ...state, mode };
}

export function setTargetPace(state: RunTimerState, paceSecPerKm: number): RunTimerState {
  return { ...state, targetPaceSecPerKm: Math.max(120, Math.min(1200, paceSecPerKm)) };
}

export function addDistance(state: RunTimerState, deltaKm: number): RunTimerState {
  return { ...state, manualDistanceKm: round2(Math.max(0, state.manualDistanceKm + deltaKm)) };
}

export function logHeartRate(state: RunTimerState, nowMs: number, bpm: number): RunTimerState {
  const atSec = Math.round(elapsedMs(state, nowMs) / 1000);
  return { ...state, manualHrLog: [...state.manualHrLog, { atSec, bpm }] };
}

/** Live-feeling auto-mode pace: a short settle-in ramp (starts a touch
 *  slower, like the first few hundred meters of any real run) plus
 *  continuous stride-to-stride wobble, layered sine waves at different
 *  periods so it doesn't repeat in an obviously mechanical way. Deterministic
 *  on purpose, same as simulatedHrBpm/simulatedCadenceSpm above -- same
 *  elapsedSec always produces the same reading. */
export function instantaneousPaceSecPerKm(elapsedSec: number, targetPaceSecPerKm: number): number {
  const settleInSec = 150;
  const settleInOffset = 22 * Math.pow(Math.max(0, 1 - elapsedSec / settleInSec), 2);
  const wobble = Math.sin(elapsedSec / 37) * 8 + Math.sin(elapsedSec / 13) * 4 + Math.sin(elapsedSec / 5) * 2;
  return Math.round(clamp(targetPaceSecPerKm + settleInOffset + wobble, 120, 1200));
}

/** One pass over the live-pace curve above, in 1-second steps (matching the
 *  UI's own tick rate -- see LiveRunContext's setInterval), accumulating
 *  both the real distance that pace curve implies and the elapsed-time/pace
 *  of each completed kilometer. Distance and splits come from this single
 *  walk so they can never disagree with each other or with the pace number
 *  actually shown on screen -- three separate approximations of the same
 *  run would be easy to let drift apart. */
function simulateAutoRun(
  elapsedSec: number,
  targetPaceSecPerKm: number,
): { distanceKm: number; splits: Split[] } {
  const wholeSeconds = Math.floor(elapsedSec);
  const fractionSec = elapsedSec - wholeSeconds;
  let distanceKm = 0;
  let splitStartSec = 0;
  let splitStartKm = 0;
  const splits: Split[] = [];

  for (let s = 0; s < wholeSeconds; s++) {
    distanceKm += 1 / instantaneousPaceSecPerKm(s + 0.5, targetPaceSecPerKm);
    if (distanceKm - splitStartKm >= 1) {
      const km = Math.floor(distanceKm);
      const atSec = s + 1;
      const durationSec = atSec - splitStartSec;
      splits.push({ km, durationSec, paceSecPerKm: durationSec });
      splitStartSec = atSec;
      splitStartKm = km;
    }
  }
  if (fractionSec > 0) {
    distanceKm += fractionSec / instantaneousPaceSecPerKm(wholeSeconds + fractionSec / 2, targetPaceSecPerKm);
  }
  return { distanceKm, splits };
}

/** Distance in auto mode is the integral of the live-pace curve above --
 *  not a flat "held target pace the whole way" multiplication -- so it
 *  stays consistent with the fluctuating pace actually shown on screen.
 *  In manual mode it's whatever the athlete has entered. */
export function currentDistanceKm(state: RunTimerState, nowMs: number): number {
  if (state.mode === "manual") return state.manualDistanceKm;
  const elapsedSec = elapsedMs(state, nowMs) / 1000;
  return round2(simulateAutoRun(elapsedSec, state.targetPaceSecPerKm).distanceKm);
}

/** The pace number the live screen highlights as "current pace": in auto
 *  mode this is the fluctuating instantaneous curve (not a frozen copy of
 *  the target pace the athlete typed in), so it actually moves the way a
 *  real run's pace does. Manual mode has no simulated curve to read from --
 *  the screen derives its own value from the athlete's entered distance. */
export function currentPaceSecPerKm(state: RunTimerState, nowMs: number): number | null {
  if (state.mode === "manual") return null;
  if (state.phase === "idle") return state.targetPaceSecPerKm;
  const elapsedSec = elapsedMs(state, nowMs) / 1000;
  return instantaneousPaceSecPerKm(elapsedSec, state.targetPaceSecPerKm);
}

/** Auto-mode heart rate: a deterministic ramp from a resting baseline up to
 *  a working rate implied by the chosen pace (faster pace -> higher rate),
 *  plus a gentle deterministic wobble so it doesn't look like a flat line.
 *  Deterministic on purpose -- same inputs always produce the same reading,
 *  which is what makes this testable and what makes a recorded demo replay
 *  identically every time. */
export function simulatedHrBpm(elapsedSec: number, targetPaceSecPerKm: number): number {
  const intensity = clamp(1 - (targetPaceSecPerKm - 240) / 300, 0.1, 1);
  const restingBpm = 92;
  const workingBpm = 116 + intensity * 66; // ~122 (easy) .. 182 (hard)
  const rampSec = 240;
  const ramp = 1 - Math.pow(1 - Math.min(1, elapsedSec / rampSec), 2); // ease-out
  const base = restingBpm + (workingBpm - restingBpm) * ramp;
  const wobble = Math.sin(elapsedSec / 45) * 3 + Math.sin(elapsedSec / 17) * 1.4;
  return Math.round(clamp(base + wobble, 60, 200));
}

export function currentHrBpm(state: RunTimerState, nowMs: number): number | null {
  if (state.mode === "auto") {
    if (state.phase === "idle") return null;
    return simulatedHrBpm(elapsedMs(state, nowMs) / 1000, state.targetPaceSecPerKm);
  }
  const log = state.manualHrLog;
  return log.length > 0 ? log[log.length - 1].bpm : null;
}

/** Simulated running cadence (steps per minute). Faster paces naturally yield higher cadence (~165-188 spm). */
export function simulatedCadenceSpm(elapsedSec: number, targetPaceSecPerKm: number): number {
  if (elapsedSec <= 0) return 0;
  // Base cadence: ~170 at 6:00/km (360s), ~180 at 5:00/km (300s), ~188 at 4:00/km (240s)
  const paceFactor = clamp((420 - targetPaceSecPerKm) / 180, 0, 1);
  const baseCadence = 166 + paceFactor * 22;
  const wobble = Math.sin(elapsedSec / 19) * 2.5 + Math.sin(elapsedSec / 7) * 1.2;
  return Math.round(clamp(baseCadence + wobble, 140, 210));
}

export function currentCadenceSpm(state: RunTimerState, nowMs: number): number | null {
  if (state.phase === "idle") return null;
  const elapsedSec = elapsedMs(state, nowMs) / 1000;
  if (elapsedSec < 3) return null;
  return simulatedCadenceSpm(elapsedSec, state.targetPaceSecPerKm);
}

/** Calories estimated from distance and time for an average runner (~65-70kg). */
export function estimatedCaloriesKcal(distanceKm: number, elapsedSec: number): number {
  if (distanceKm <= 0 && elapsedSec <= 0) return 0;
  // ~68 kcal per km, or time-based minimum of ~9 kcal/min during running
  const distCalories = distanceKm * 68;
  const timeCalories = (elapsedSec / 60) * 9.5;
  return Math.round(Math.max(distCalories, timeCalories));
}

export interface Split {
  km: number;
  durationSec: number;
  paceSecPerKm: number;
}

/** Compute splits for each completed 1.0 km. Auto mode reads them straight
 *  off the same live-pace curve driving distanceKm and currentPaceSecPerKm
 *  above, so a split's pace always matches what the screen showed while
 *  that kilometer was in progress. Manual mode has no live curve to read
 *  from -- kept as its own lightweight per-km variance so a manually
 *  logged run still gets a plausible-looking splits table. */
export function calculateSplits(state: RunTimerState, nowMs: number): Split[] {
  const elapsedSec = elapsedMs(state, nowMs) / 1000;
  if (state.mode === "auto") {
    return simulateAutoRun(elapsedSec, state.targetPaceSecPerKm).splits;
  }

  const totalDist = currentDistanceKm(state, nowMs);
  const fullKmCount = Math.floor(totalDist);
  if (fullKmCount <= 0) return [];

  const splits: Split[] = [];
  const basePace = state.targetPaceSecPerKm;

  for (let k = 1; k <= fullKmCount; k++) {
    // Subtle realistic pace variance per kilometer
    const variance = (Math.sin(k * 2.4) * 6) - (k > 3 ? 3 : 0);
    const splitPace = Math.round(clamp(basePace + variance, 150, 900));
    splits.push({
      km: k,
      durationSec: splitPace,
      paceSecPerKm: splitPace,
    });
  }

  return splits;
}

export function getHrZone(bpm: number | null): { zone: number; label: string; min: number; max: number } {
  if (!bpm) return { zone: 0, label: "—", min: 0, max: 0 };
  if (bpm < 120) return { zone: 1, label: "Z1 恢復 (Recovery)", min: 60, max: 119 };
  if (bpm < 142) return { zone: 2, label: "Z2 有氧 (Aerobic)", min: 120, max: 141 };
  if (bpm < 158) return { zone: 3, label: "Z3 節奏 (Tempo)", min: 142, max: 157 };
  if (bpm < 174) return { zone: 4, label: "Z4 閾值 (Threshold)", min: 158, max: 173 };
  return { zone: 5, label: "Z5 無氧極限 (Anaerobic)", min: 174, max: 210 };
}

export interface FinishedRun {
  durationMinutes: number;
  distanceKm: number;
  avgPaceSecPerKm: number | null;
  hrLog: HrReading[];
  mode: RunTimerMode;
  caloriesKcal?: number;
  avgCadenceSpm?: number | null;
  splits?: Split[];
}

export function finish(
  state: RunTimerState,
  nowMs: number,
): { state: RunTimerState; result: FinishedRun } {
  const totalMs = elapsedMs(state, nowMs);
  const durationMinutes = round2(totalMs / 60_000);
  const distanceKm = currentDistanceKm(state, nowMs);
  const avgPaceSecPerKm = distanceKm > 0 ? Math.round(totalMs / 1000 / distanceKm) : null;
  const hrLog =
    state.mode === "auto"
      ? sampleAutoHrLog(totalMs / 1000, state.targetPaceSecPerKm)
      : state.manualHrLog;
  const caloriesKcal = estimatedCaloriesKcal(distanceKm, totalMs / 1000);
  const avgCadenceSpm = currentCadenceSpm(state, nowMs);
  const splits = calculateSplits(state, nowMs);

  return {
    state: {
      ...state,
      phase: "finished",
      runningSinceMs: null,
      accumulatedMs: totalMs,
      manualDistanceKm: distanceKm,
    },
    result: {
      durationMinutes,
      distanceKm,
      avgPaceSecPerKm,
      hrLog,
      mode: state.mode,
      caloriesKcal,
      avgCadenceSpm,
      splits,
    },
  };
}

/** Reconstructs a readable HR history for the summary/sparkline in auto mode
 *  without having stored a reading every second -- sampled every 15s from
 *  the same deterministic formula the live view used. */
function sampleAutoHrLog(totalElapsedSec: number, targetPaceSecPerKm: number): HrReading[] {
  const stepSec = 15;
  const readings: HrReading[] = [];
  for (let atSec = stepSec; atSec <= totalElapsedSec; atSec += stepSec) {
    readings.push({ atSec, bpm: simulatedHrBpm(atSec, targetPaceSecPerKm) });
  }
  return readings;
}

function clamp(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n));
}

function round2(n: number): number {
  return Math.round(n * 100) / 100;
}
