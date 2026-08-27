/* Wraps lib/runTimer.ts's pure state machine in React state, and mounts it
 * once at AppShell level so an in-progress run survives navigating between
 * screens. Deliberately separate from WorkspaceContext: a live run is
 * ephemeral, single-device UI state with a one-second tick, not server-synced
 * athlete-owned data -- mixing the two would make an already-large context
 * (900+ lines) also own a setInterval it doesn't otherwise need. */

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import * as runTimer from "../lib/runTimer.ts";
import type {
  FinishedRun,
  HrReading,
  Lap,
  RaceProjection,
  RunTimerMode,
  RunTimerPhase,
  Split,
} from "../lib/runTimer.ts";

interface LiveRunContextValue {
  phase: RunTimerPhase;
  mode: RunTimerMode;
  elapsedSec: number;
  distanceKm: number;
  currentPaceSecPerKm: number | null;
  currentHrBpm: number | null;
  cadenceSpm: number | null;
  caloriesKcal: number;
  splits: Split[];
  hrZone: { zone: number; label: string; min: number; max: number };
  hrLog: HrReading[];
  targetPaceSecPerKm: number;
  raceModeEnabled: boolean;
  raceDistanceKm: number | null;
  raceTargetFinishSec: number | null;
  raceProjection: RaceProjection | null;
  /** Garmin-style manual laps -- see runTimer.ts's calculateLaps. */
  laps: Lap[];
  /** Live-ticking time since the last lap press (or since start, if none
   *  yet) -- the in-progress lap a Lap button UI would show next to the
   *  completed ones in `laps`. */
  currentLapElapsedSec: number;
  setMode: (mode: RunTimerMode) => void;
  setTargetPace: (paceSecPerKm: number) => void;
  setRaceModeEnabled: (enabled: boolean) => void;
  setRaceDistanceKm: (km: number | null) => void;
  setRaceTargetFinishSec: (sec: number | null) => void;
  start: () => void;
  pause: () => void;
  resume: () => void;
  addDistance: (deltaKm: number) => void;
  logHeartRate: (bpm: number) => void;
  recordLap: () => void;
  finish: () => FinishedRun;
  reset: () => void;
}

const LiveRunContext = createContext<LiveRunContextValue | null>(null);

/** Auto mode only needs a redraw once a second (elapsed/pace/HR are all
 *  computed from timestamps); manual-mode HR entries are stored directly by
 *  logHeartRate and need no extra ticking to show up. */
export function LiveRunProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<runTimer.RunTimerState>(runTimer.initialRunTimerState);
  const stateRef = useRef(state);
  stateRef.current = state;
  const [, tick] = useState(0);

  useEffect(() => {
    if (state.phase !== "running") return;
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [state.phase]);

  const now = Date.now();
  const elapsed = Math.floor(runTimer.elapsedMs(state, now) / 1000);
  const distance = runTimer.currentDistanceKm(state, now);
  const hr = runTimer.currentHrBpm(state, now);

  const start = useCallback(() => setState((s) => runTimer.start(s, Date.now())), []);
  const pause = useCallback(() => setState((s) => runTimer.pause(s, Date.now())), []);
  const setMode = useCallback((mode: RunTimerMode) => setState((s) => runTimer.setMode(s, mode)), []);
  const setTargetPace = useCallback(
    (pace: number) => setState((s) => runTimer.setTargetPace(s, pace)),
    [],
  );
  const setRaceModeEnabled = useCallback(
    (enabled: boolean) => setState((s) => runTimer.setRaceModeEnabled(s, enabled)),
    [],
  );
  const setRaceDistanceKm = useCallback(
    (km: number | null) => setState((s) => runTimer.setRaceDistanceKm(s, km)),
    [],
  );
  const setRaceTargetFinishSec = useCallback(
    (sec: number | null) => setState((s) => runTimer.setRaceTargetFinishSec(s, sec)),
    [],
  );
  const addDistance = useCallback(
    (deltaKm: number) => setState((s) => runTimer.addDistance(s, deltaKm)),
    [],
  );
  const logHeartRate = useCallback(
    (bpm: number) => setState((s) => runTimer.logHeartRate(s, Date.now(), bpm)),
    [],
  );
  const recordLap = useCallback(() => setState((s) => runTimer.recordLap(s, Date.now())), []);
  const finish = useCallback((): FinishedRun => {
    const { state: nextState, result } = runTimer.finish(stateRef.current, Date.now());
    setState(nextState);
    return result;
  }, []);
  const reset = useCallback(() => setState(runTimer.initialRunTimerState), []);

  const value: LiveRunContextValue = {
    phase: state.phase,
    mode: state.mode,
    elapsedSec: elapsed,
    distanceKm: distance,
    currentPaceSecPerKm: runTimer.currentPaceSecPerKm(state, now),
    currentHrBpm: hr,
    cadenceSpm: runTimer.currentCadenceSpm(state, now),
    caloriesKcal: runTimer.estimatedCaloriesKcal(distance, elapsed),
    splits: runTimer.calculateSplits(state, now),
    hrZone: runTimer.getHrZone(hr),
    hrLog: state.mode === "auto" ? [] : state.manualHrLog,
    targetPaceSecPerKm: state.targetPaceSecPerKm,
    raceModeEnabled: state.raceModeEnabled,
    raceDistanceKm: state.raceDistanceKm,
    raceTargetFinishSec: state.raceTargetFinishSec,
    raceProjection: runTimer.calculateRaceProjection(state, now),
    laps: runTimer.calculateLaps(state),
    currentLapElapsedSec: Math.max(
      0,
      elapsed - (state.lapMarks.length > 0 ? state.lapMarks[state.lapMarks.length - 1].atElapsedSec : 0),
    ),
    setMode,
    setTargetPace,
    setRaceModeEnabled,
    setRaceDistanceKm,
    setRaceTargetFinishSec,
    start,
    pause,
    resume: start,
    addDistance,
    logHeartRate,
    recordLap,
    finish,
    reset,
  };

  return <LiveRunContext.Provider value={value}>{children}</LiveRunContext.Provider>;
}

export function useLiveRun(): LiveRunContextValue {
  const ctx = useContext(LiveRunContext);
  if (!ctx) throw new Error("useLiveRun must be used within LiveRunProvider");
  return ctx;
}
