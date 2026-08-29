/* oxlint-disable react/only-export-components -- provider hook intentionally shares context */
/* The athlete's working set: activities, injury reports, consent, team
 * memberships, sessions, audit log, and the handful of preferences the
 * privacy chapter requires.
 *
 * Two behaviours here are load-bearing rather than cosmetic:
 *
 * REQ-SYNC-001  `logActivity` commits to durable local storage BEFORE it
 *               resolves. The screen only says "已儲存" after that promise
 *               settles, so a confirmed save can never be a lost save.
 * REQ-LOCAL-SEC-001/003  the local queue is namespaced per account and wiped
 *               on logout.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import type { ReactNode } from "react";
import { buildDemoWorkspace } from "../data/demoData.ts";
import type { DemoWorkspace } from "../data/demoData.ts";
import {
  apiConfigured,
  createActivity,
  createInjuryReport as apiCreateInjuryReport,
  createTeamAssignment as apiCreateTeamAssignment,
  deleteActivity as apiDeleteActivity,
  deleteTeamAssignment as apiDeleteTeamAssignment,
  exportMyPrivacyData,
  getActivityHistory,
  getGarminIntegrationStatus,
  getInjuryReports as apiGetInjuryReports,
  getMyAssignedWorkouts,
  getMyAuditLog,
  getMyConsentGrants,
  getMySessions,
  getMyTeamMemberships,
  getMyTeams,
  getTeamAssignments,
  getTeamRoster,
  getTrainingLoadTrend,
  getTrainingPlanToday,
  getWeather,
  getTodaysGuidance,
  createInjuryGuidance as apiCreateInjuryGuidance,
  requestMyAccountDeletion,
  revokeMySession,
  updateMyConsentGrant,
  updateMyTeamMembership,
  updateProfile as apiUpdateProfile,
  ApiError,
} from "../data/apiClient.ts";
import { localDateTimeToUtcIso } from "../lib/dateTime.ts";
import type {
  AssignedWorkoutWireResponse,
  CreateActivityWireResponse,
  GuidanceWireResponse,
  InjuryGuidanceFlags,
  InjuryGuidanceWireResponse,
  TrainingLoadTrendWireResponse,
  TrainingPlanWireResponse,
  WeatherWireResponse,
} from "../data/apiClient.ts";
import { computeTrainingLoad } from "../lib/trainingLoad.ts";
import type { TrainingLoadResult } from "../lib/trainingLoad.ts";
import { adaptTrainingLoadSummary } from "../lib/liveTrainingLoad.ts";
import { adaptTeamRoster } from "../lib/liveCoachData.ts";
import type {
  Activity,
  ActivityDeviceMetrics,
  ActivityProvider,
  AssignedWorkout,
  AuditEntry,
  AuditEvent,
  AuthSession,
  ConsentScope,
  InjuryReport,
  InjuryReportDetail,
  LoadUnit,
  SeverityBand,
  SourceMetric,
  TeamAthleteProjection,
  TeamMembership,
  ConsentGrant,
  WorkoutAssignmentSegment,
} from "../lib/types.ts";
import { useAuth } from "./AuthContext.tsx";
import { useToast } from "./ToastContext.tsx";

export type Theme = "light" | "dark";

export interface LogActivityInput {
  durationMinutes: number;
  rpe: number;
  performedAtUtc: string;
  localTrainingDate: string;
  distanceKm: number | null;
  note: string;
  /** Optional block-by-block detail (warmup/interval/cooldown/recovery/jog)
   *  for a backfilled workout -- purely additive, durationMinutes/rpe above
   *  still drive sessionLoad regardless of whether this is populated. */
  structure?: WorkoutAssignmentSegment[];
}

export interface Preferences {
  /** REQ-PRIV-004: the athlete can switch off the LLM tone layer and keep
   *  the deterministic prescription. */
  llmToneEnabled: boolean;
  /** REQ-GARMIN-001: GARMIN_ACTIVITY_SYNC_ENABLED. Off by default. */
  garminSyncEnabled: boolean;
  /** REQ-PRIV-006: the policy version this account has accepted. */
  acceptedPolicyVersion: string;
  pushNotificationsEnabled: boolean;
  theme: Theme;
  /** Which source the Dashboard's "today's plan" hero card follows -- an
   *  explicit athlete choice, not "whichever exists wins": a coach
   *  assignment silently overriding the system suggestion (or vice versa)
   *  left the athlete unsure which plan they were actually supposed to
   *  follow. "coach" never falls back to the system suggestion on a day
   *  the coach hasn't assigned anything -- see DashboardScreen.tsx's empty
   *  state for that case, which requires an explicit athlete tap to view
   *  the system suggestion instead. */
  trainingSource: "system" | "coach";
}

export interface DeletionRequest {
  requestedAtUtc: string;
  /** REQ-PRIV-003: deletion is not instant; the retention window is stated. */
  purgeAfterUtc: string;
  retainedForLegalReasons: string[];
}

interface WorkspaceContextValue extends DemoWorkspace {
  /** AU records plus, when the Garmin flag is on, garmin_epoc records. */
  allActivities: Activity[];
  trainingLoad: TrainingLoadResult;
  preferences: Preferences;
  online: boolean;
  syncing: boolean;
  pendingCount: number;
  consentRevokedAt: string | null;
  deletionRequest: DeletionRequest | null;
  lastExportAtUtc: string | null;

  setOnline: (online: boolean) => void;
  setTheme: (theme: Theme) => void;
  setPreference: <K extends keyof Preferences>(key: K, value: Preferences[K]) => void;

  logActivity: (input: LogActivityInput) => Promise<Activity>;
  syncNow: () => Promise<void>;
  retryActivity: (localId: string) => Promise<void>;
  discardActivity: (localId: string) => void;
  /** Removes an already-synced Completed Activity -- a soft delete
   *  server-side (see backend/app/routes/activities.py's delete_activity),
   *  distinct from discardActivity above which only drops a local,
   *  never-synced pending record. Returns whether it succeeded so the
   *  caller can decide whether to close its confirmation modal. */
  deleteActivity: (activityId: string) => Promise<boolean>;
  resolveDuplicate: (activityId: string, action: "keep_both" | "mark_duplicate") => void;

  /** wire-live-training-data: real when apiConfigured, otherwise unused. */
  historyStatus: "idle" | "loading" | "error";
  hasMoreHistory: boolean;
  loadMoreHistory: () => Promise<void>;
  refetchHistory: () => Promise<void>;
  liveTrend: TrainingLoadTrendWireResponse | null;
  trendStatus: "idle" | "loading" | "error";
  refetchTrend: () => Promise<void>;
  liveWeather: WeatherWireResponse | null;
  weatherStatus: "idle" | "loading" | "error";
  refetchWeather: () => Promise<void>;
  liveGuidance: GuidanceWireResponse | null;
  guidanceStatus: "idle" | "loading" | "error";
  refetchGuidance: () => Promise<void>;
  /** health-training-intelligence: GET /training-plan/today. Null in demo
   *  mode and until the first fetch settles. */
  liveTrainingPlan: TrainingPlanWireResponse | null;
  trainingPlanStatus: "idle" | "loading" | "error";
  refetchTrainingPlan: () => Promise<void>;
  /** wire-coach-roster (docs/mvp-checklist.md Item 1): real when
   *  apiConfigured and the actor coaches at least one team, otherwise the
   *  demo roster from demoData.ts is used unchanged. */
  liveTeamId: string | null;
  liveTeamName: string | null;
  rosterStatus: "idle" | "loading" | "error";
  refetchRoster: () => Promise<void>;
  athleteDataStatus: "idle" | "loading" | "error";
  refetchAthleteData: () => Promise<void>;

  addInjuryReport: (input: {
    clientMutationId: string;
    localDate: string;
    hasIssue: boolean;
    severityBand: SeverityBand;
    bodyPart: string;
    freeText: string;
  }) => Promise<string | null>;

  /** health-guidance: POST /injury-guidance for a report just created by
   *  addInjuryReport. Returns null in demo mode or on failure. */
  requestInjuryGuidance: (
    injuryReportId: string,
    flags: InjuryGuidanceFlags,
  ) => Promise<InjuryGuidanceWireResponse | null>;

  setConsent: (scope: ConsentScope, granted: boolean, teamId?: string) => Promise<void>;
  acceptInvitation: (teamId: string) => Promise<void>;
  declineInvitation: (teamId: string) => Promise<void>;
  leaveTeam: (teamId: string) => Promise<void>;
  revokeSession: (sessionId: string) => Promise<void>;
  revokeOtherSessions: () => Promise<void>;
  updateProfile: (patch: { timezone?: string; city?: string; sex?: "male" | "female" }) => void;
  exportData: () => Promise<void>;
  requestAccountDeletion: () => Promise<void>;
  cancelAccountDeletion: () => void;
  appendAudit: (event: AuditEvent, summary: string) => void;

  /** wire-settings: real garmin flag from GET /me/settings/integrations/garmin
   *  (REQ-GARMIN-001) -- distinct from `preferences.garminSyncEnabled`, which
   *  stays the client-side demo-only simulation toggle documented in
   *  web/README.md's "Two demo-only affordances". */
  liveGarminEnabled: boolean | null;
  liveGarminReason: string | null;

  /** wire-assignments: the athlete's own view across every team. */
  myAssignedWorkouts: AssignedWorkout[];
  assignmentsStatus: "idle" | "loading" | "error";
  createAssignment: (input: {
    teamId: string;
    athleteId: string;
    localDate: string;
    title: string;
    durationMinutes: number;
    intensityLabel: string;
    structure: Array<Record<string, unknown>>;
  }) => Promise<boolean>;
  deleteAssignment: (teamId: string, assignmentId: string) => Promise<boolean>;
}

const WorkspaceContext = createContext<WorkspaceContextValue | null>(null);

const POLICY_VERSION = "2026-07-01";

/** REQ-LOCAL-SEC-001: one storage namespace per authenticated account. */
function pendingQueueKey(accountId: string): string {
  return `runsense:pending-activities:${accountId}`;
}

function readPendingQueue(accountId: string): Activity[] {
  try {
    const raw = localStorage.getItem(pendingQueueKey(accountId));
    return raw ? (JSON.parse(raw) as Activity[]) : [];
  } catch {
    return [];
  }
}

function writePendingQueue(accountId: string, records: Activity[]): void {
  localStorage.setItem(pendingQueueKey(accountId), JSON.stringify(records));
}

function normalizeDeviceMetrics(raw: any): ActivityDeviceMetrics {
  if (!raw || typeof raw !== "object") return {};
  return {
    avgHeartRate: raw.avgHeartRate ?? raw.avg_heart_rate ?? undefined,
    maxHeartRate: raw.maxHeartRate ?? raw.max_heart_rate ?? undefined,
    avgCadenceStepsPerMin: raw.avgCadenceStepsPerMin ?? raw.avg_cadence_steps_per_min ?? undefined,
    maxCadenceStepsPerMin: raw.maxCadenceStepsPerMin ?? raw.max_cadence_steps_per_min ?? undefined,
    avgStrideLengthM: raw.avgStrideLengthM ?? raw.avg_stride_length_m ?? undefined,
    elevationGainM: raw.elevationGainM ?? raw.elevation_gain_m ?? undefined,
    elevationLossM: raw.elevationLossM ?? raw.elevation_loss_m ?? undefined,
    calories: raw.calories ?? undefined,
    aerobicTrainingEffect: raw.aerobicTrainingEffect ?? raw.aerobic_training_effect ?? undefined,
    anaerobicTrainingEffect: raw.anaerobicTrainingEffect ?? raw.anaerobic_training_effect ?? undefined,
    trainingEffectLabel: raw.trainingEffectLabel ?? raw.training_effect_label ?? undefined,
  };
}

/** Server activities carry no `note`/duplicate-flag today --
 *  backend/app/schemas.py's CreateActivityRequest/ActivityResponse simply
 *  don't have those fields yet (REQ-DEDUP-002 is genuinely unimplemented,
 *  not just unfetched). Mapping to `""`/`null` here is honest, not lossy. */
export function activityFromWire(wire: CreateActivityWireResponse): Activity {
  return {
    id: wire.id,
    clientMutationId: wire.client_mutation_id,
    provider: (wire.provider as ActivityProvider) ?? "manual",
    providerActivityId: wire.provider_activity_id,
    performedAtUtc: wire.performed_at,
    localTrainingDate: wire.local_training_date,
    timezoneSnapshot: wire.timezone_snapshot,
    durationMinutes: wire.duration_minutes,
    rpe: wire.rpe,
    distanceKm: wire.distance_km,
    structure: wire.structure ?? [],
    deviceMetrics: normalizeDeviceMetrics(wire.device_metrics),
    sessionLoad: wire.session_load,
    unit: wire.unit as LoadUnit,
    sourceMetric: wire.source_metric as SourceMetric,
    note: "",
    syncState: "SYNCED",
    syncAttempts: 1,
    lastErrorCode: null,
    serverVersion: wire.server_version,
    duplicateCandidateOf: null,
  };
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const { auth } = useAuth();
  const { push } = useToast();

  const accountId = auth?.athlete.id ?? "anonymous";

  const [data, setData] = useState<DemoWorkspace>(() => {
    const seeded = buildDemoWorkspace();
    const restored = readPendingQueue(accountId);
    if (apiConfigured) {
      // seeded.activities includes two hardcoded "pending"/"failed" mock
      // rows that exist purely to illustrate offline sync states in demo
      // mode (see demoData.ts). Against a real backend, this array must
      // start with ONLY genuine local writes restored from this browser's
      // own pending queue -- allActivities' pending-overlay, pendingCount,
      // and syncNow's retry-all all read data.activities directly and had
      // no other way to tell a demo mock row from a real unsynced write.
      return { ...seeded, activities: restored };
    }
    return restored.length > 0
      ? { ...seeded, activities: [...restored, ...seeded.activities] }
      : seeded;
  });

  const [preferences, setPreferences] = useState<Preferences>({
    llmToneEnabled: true,
    garminSyncEnabled: false,
    acceptedPolicyVersion: POLICY_VERSION,
    pushNotificationsEnabled: true,
    theme: "dark",
    trainingSource: "system",
  });

  const [online, setOnline] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [consentRevokedAt, setConsentRevokedAt] = useState<string | null>(null);
  const [deletionRequest, setDeletionRequest] = useState<DeletionRequest | null>(null);
  const [lastExportAtUtc, setLastExportAtUtc] = useState<string | null>(null);

  /* ---------------- live training data (wire-live-training-data) ----------------
   * apiConfigured branches everything below: demo installs never call these,
   * matching spec.md's "Unconfigured Backend Falls Back to Demo Mode". */

  const [liveActivities, setLiveActivities] = useState<Activity[]>([]);
  const [historyNextCursor, setHistoryNextCursor] = useState<string | null>(null);
  const [historyStatus, setHistoryStatus] = useState<"idle" | "loading" | "error">("idle");
  const [liveTrend, setLiveTrend] = useState<TrainingLoadTrendWireResponse | null>(null);
  const [trendStatus, setTrendStatus] = useState<"idle" | "loading" | "error">("idle");

  const fetchHistory = useCallback(
    async (cursor: string | null) => {
      if (!apiConfigured || !auth?.accessToken) return;
      setHistoryStatus("loading");
      try {
        const res = await getActivityHistory(auth.accessToken, {
          cursor: cursor ?? undefined,
          limit: 100,
        });
        const mapped = res.items.map(activityFromWire);
        setLiveActivities((current) => (cursor ? [...current, ...mapped] : mapped));
        setHistoryNextCursor(res.next_cursor);
        setHistoryStatus("idle");
      } catch {
        setHistoryStatus("error");
      }
    },
    [auth],
  );

  const fetchTrend = useCallback(async () => {
    if (!apiConfigured || !auth?.accessToken) return;
    setTrendStatus("loading");
    try {
      const res = await getTrainingLoadTrend(auth.accessToken);
      setLiveTrend(res);
      setTrendStatus("idle");
    } catch {
      setTrendStatus("error");
    }
  }, [auth]);

  const loadMoreHistory = useCallback(async () => {
    if (historyNextCursor) await fetchHistory(historyNextCursor);
  }, [fetchHistory, historyNextCursor]);

  const [liveWeather, setLiveWeather] = useState<WeatherWireResponse | null>(null);
  const [weatherStatus, setWeatherStatus] = useState<"idle" | "loading" | "error">("idle");
  const [liveGuidance, setLiveGuidance] = useState<GuidanceWireResponse | null>(null);
  const [guidanceStatus, setGuidanceStatus] = useState<"idle" | "loading" | "error">("idle");
  const [liveTrainingPlan, setLiveTrainingPlan] = useState<TrainingPlanWireResponse | null>(null);
  const [trainingPlanStatus, setTrainingPlanStatus] = useState<"idle" | "loading" | "error">("idle");

  const [liveTeamId, setLiveTeamId] = useState<string | null>(null);
  const [liveTeamName, setLiveTeamName] = useState<string | null>(null);
  const [liveRoster, setLiveRoster] = useState<TeamAthleteProjection[] | null>(null);
  const [rosterStatus, setRosterStatus] = useState<"idle" | "loading" | "error">("idle");
  const [liveMemberships, setLiveMemberships] = useState<TeamMembership[] | null>(null);
  const [liveConsents, setLiveConsents] = useState<ConsentGrant[] | null>(null);
  const [liveInjuryReports, setLiveInjuryReports] = useState<InjuryReport[] | null>(null);
  const [liveInjuryDetails, setLiveInjuryDetails] = useState<InjuryReportDetail[] | null>(null);
  const [athleteDataStatus, setAthleteDataStatus] = useState<"idle" | "loading" | "error">("idle");

  const fetchAthleteData = useCallback(async () => {
    if (!apiConfigured || !auth?.accessToken) return;
    setAthleteDataStatus("loading");
    try {
      const [membershipResult, consentResult, injuryResult] = await Promise.all([
        getMyTeamMemberships(auth.accessToken),
        getMyConsentGrants(auth.accessToken),
        apiGetInjuryReports(auth.accessToken),
      ]);
      setLiveMemberships(
        membershipResult.items.map((item) => ({
          teamId: item.team_id,
          teamName: item.team_name,
          coachName: item.coach_name,
          status: item.status,
          invitedAtUtc: item.invited_at,
          joinedAtUtc: item.joined_at,
          leftAtUtc: item.left_at,
        })),
      );
      setLiveConsents(
        consentResult.items.map((item) => ({
          teamId: item.team_id,
          scope: item.scope,
          granted: item.granted,
          changedAtUtc: item.changed_at,
        })),
      );
      setLiveInjuryReports(
        injuryResult.items.map((item) => ({
          id: item.id,
          localDate: item.local_training_date,
          hasIssue: item.has_issue,
          severityBand: item.severity_band,
          bodyPart: item.body_part ?? "",
          createdAtUtc: item.created_at,
        })),
      );
      setLiveInjuryDetails(
        injuryResult.items.flatMap((item) =>
          item.free_text ? [{ injuryReportId: item.id, freeText: item.free_text }] : [],
        ),
      );
      setAthleteDataStatus("idle");
    } catch {
      setAthleteDataStatus("error");
    }
  }, [auth]);

  const fetchRoster = useCallback(async () => {
    if (!apiConfigured || !auth?.accessToken) return;
    setRosterStatus("loading");
    try {
      const teams = await getMyTeams(auth.accessToken);
      const team = teams.items[0] ?? null;
      if (!team) {
        // Actor coaches no team -- an empty roster, not an error state.
        setLiveTeamId(null);
        setLiveTeamName(null);
        setLiveRoster([]);
        setRosterStatus("idle");
        return;
      }
      setLiveTeamId(team.team_id);
      setLiveTeamName(team.name);
      const roster = await getTeamRoster(auth.accessToken, team.team_id);
      setLiveRoster(adaptTeamRoster(roster));
      setRosterStatus("idle");
    } catch {
      setRosterStatus("error");
    }
  }, [auth]);

  const fetchWeather = useCallback(async () => {
    if (!apiConfigured || !auth?.accessToken) return;
    setWeatherStatus("loading");
    try {
      setLiveWeather(await getWeather(auth.accessToken));
      setWeatherStatus("idle");
    } catch {
      setWeatherStatus("error");
    }
  }, [auth]);

  const fetchGuidance = useCallback(
    async (llmToneEnabled: boolean) => {
      if (!apiConfigured || !auth?.accessToken) return;
      setGuidanceStatus("loading");
      try {
        setLiveGuidance(await getTodaysGuidance(auth.accessToken, llmToneEnabled));
        setGuidanceStatus("idle");
      } catch {
        setGuidanceStatus("error");
      }
    },
    [auth],
  );

  const fetchTrainingPlan = useCallback(async () => {
    if (!apiConfigured || !auth?.accessToken) return;
    setTrainingPlanStatus("loading");
    try {
      setLiveTrainingPlan(await getTrainingPlanToday(auth.accessToken));
      setTrainingPlanStatus("idle");
    } catch {
      setTrainingPlanStatus("error");
    }
  }, [auth]);

  /* ---------------- settings: sessions / audit log / garmin flag ----------------
   * wire-settings (docs/mvp-checklist.md, Settings item): real when
   * apiConfigured, otherwise the demo rows from demoData.ts are used
   * unchanged. See backend/app/routes/settings.py. */

  const [liveSessions, setLiveSessions] = useState<AuthSession[] | null>(null);
  const [liveAuditLog, setLiveAuditLog] = useState<AuditEntry[] | null>(null);
  const [liveGarminEnabled, setLiveGarminEnabled] = useState<boolean | null>(null);
  const [liveGarminReason, setLiveGarminReason] = useState<string | null>(null);

  const fetchSessions = useCallback(async () => {
    if (!apiConfigured || !auth?.accessToken) return;
    try {
      const res = await getMySessions(auth.accessToken);
      setLiveSessions(
        res.items.map((item) => ({
          id: item.id,
          device: item.device,
          ipMasked: item.ip_masked,
          location: item.location,
          lastActiveAtUtc: item.last_active_at,
          isCurrent: item.is_current,
        })),
      );
    } catch {
      // Leave the previous list in place -- sessions is a secondary
      // settings panel, not worth surfacing a page-level error state for.
    }
  }, [auth]);

  const fetchAuditLog = useCallback(async () => {
    if (!apiConfigured || !auth?.accessToken) return;
    try {
      const res = await getMyAuditLog(auth.accessToken);
      setLiveAuditLog(
        res.items.map((item) => ({
          id: item.id,
          event: item.event as AuditEvent,
          atUtc: item.created_at,
          summary: item.summary,
        })),
      );
    } catch {
      // same rationale as fetchSessions above.
    }
  }, [auth]);

  const fetchGarminStatus = useCallback(async () => {
    if (!apiConfigured || !auth?.accessToken) return;
    try {
      const res = await getGarminIntegrationStatus(auth.accessToken);
      setLiveGarminEnabled(res.enabled);
      setLiveGarminReason(res.reason);
    } catch {
      setLiveGarminEnabled(null);
      setLiveGarminReason(null);
    }
  }, [auth]);

  /* ---------------- assignments (AssignedWorkout) ----------------
   * wire-assignments (docs/mvp-checklist.md, Assignments item). Coach-side
   * list is scoped to liveTeamId (the same team fetchRoster resolved);
   * athlete-side is every team's assignments to them. See
   * backend/app/routes/assignments.py. */

  const [liveTeamAssignments, setLiveTeamAssignments] = useState<AssignedWorkout[] | null>(null);
  const [liveMyAssignedWorkouts, setLiveMyAssignedWorkouts] = useState<AssignedWorkout[] | null>(
    null,
  );
  const [assignmentsStatus, setAssignmentsStatus] = useState<"idle" | "loading" | "error">(
    "idle",
  );

  const assignmentFromWire = useCallback(
    (wire: AssignedWorkoutWireResponse): AssignedWorkout => ({
      id: wire.id,
      teamId: wire.team_id,
      athleteId: wire.athlete_id,
      localDate: wire.local_date,
      title: wire.title,
      durationMinutes: wire.duration_minutes,
      intensityLabel: wire.intensity_label,
      status: wire.status,
      structure: wire.structure ?? [],
    }),
    [],
  );

  const fetchTeamAssignments = useCallback(
    async (teamId: string) => {
      if (!apiConfigured || !auth?.accessToken) return;
      setAssignmentsStatus("loading");
      try {
        const res = await getTeamAssignments(auth.accessToken, teamId);
        setLiveTeamAssignments(res.items.map(assignmentFromWire));
        setAssignmentsStatus("idle");
      } catch {
        setLiveTeamAssignments([]);
        setAssignmentsStatus("error");
      }
    },
    [auth, assignmentFromWire],
  );

  const fetchMyAssignedWorkouts = useCallback(async () => {
    if (!apiConfigured || !auth?.accessToken) return;
    try {
      const res = await getMyAssignedWorkouts(auth.accessToken);
      setLiveMyAssignedWorkouts(res.items.map(assignmentFromWire));
    } catch {
      setLiveMyAssignedWorkouts([]);
    }
  }, [auth, assignmentFromWire]);

  const createAssignment = useCallback(
    async (input: {
      teamId: string;
      athleteId: string;
      localDate: string;
      title: string;
      durationMinutes: number;
      intensityLabel: string;
      structure: Array<Record<string, unknown>>;
    }) => {
      if (!apiConfigured || !auth?.accessToken) return false;
      try {
        await apiCreateTeamAssignment(auth.accessToken, input.teamId, {
          athlete_id: input.athleteId,
          local_date: input.localDate,
          title: input.title,
          duration_minutes: input.durationMinutes,
          intensity_label: input.intensityLabel,
          structure: input.structure,
        });
        await fetchTeamAssignments(input.teamId);
        push("success", "已新增課表指派");
        return true;
      } catch (err) {
        push(
          "critical",
          "新增指派失敗",
          err instanceof ApiError ? err.message : "請稍後再試。",
        );
        return false;
      }
    },
    [auth, fetchTeamAssignments, push],
  );

  const deleteAssignment = useCallback(
    async (teamId: string, assignmentId: string) => {
      if (!apiConfigured || !auth?.accessToken) return false;
      try {
        await apiDeleteTeamAssignment(auth.accessToken, teamId, assignmentId);
        await fetchTeamAssignments(teamId);
        push("success", "已刪除課表指派");
        return true;
      } catch (err) {
        push(
          "critical",
          "刪除指派失敗",
          err instanceof ApiError ? err.message : "請稍後再試。",
        );
        return false;
      }
    },
    [auth, fetchTeamAssignments, push],
  );

  // `data.athlete` seeds from the static demo fixture on first render and,
  // unlike everything else in `data`, was never re-derived from whoever
  // actually signed in -- so ProfileSettings and the dashboard greeting
  // showed the same fixed identity no matter which persona logged in. Resync
  // on every fresh login (keyed on signedInAtUtc so re-logging in as the
  // same persona still resyncs); updateProfile's own local patches below
  // still layer on top of this normally, since this effect only fires again
  // at the next login.
  useEffect(() => {
    if (auth) setData((current) => ({ ...current, athlete: auth.athlete }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth?.signedInAtUtc]);

  useEffect(() => {
    if (apiConfigured && auth?.accessToken) {
      void fetchHistory(null);
      void fetchTrend();
      void fetchWeather();
      void fetchGuidance(preferences.llmToneEnabled);
      void fetchTrainingPlan();
      void fetchAthleteData();
      void fetchSessions();
      void fetchAuditLog();
      void fetchGarminStatus();
      void fetchMyAssignedWorkouts();
    } else {
      setLiveActivities([]);
      setLiveTrend(null);
      setHistoryNextCursor(null);
      setLiveWeather(null);
      setLiveGuidance(null);
      setLiveTrainingPlan(null);
      setTrainingPlanStatus("idle");
      setLiveTeamId(null);
      setLiveTeamName(null);
      setLiveRoster(null);
      setLiveMemberships(null);
      setLiveConsents(null);
      setLiveInjuryReports(null);
      setLiveInjuryDetails(null);
      setLiveSessions(null);
      setLiveAuditLog(null);
      setLiveGarminEnabled(null);
      setLiveGarminReason(null);
      setLiveTeamAssignments(null);
      setLiveMyAssignedWorkouts(null);
    }
    // Intentionally keyed on the token, not the fetch callbacks: those are
    // recreated whenever `auth` changes, which would otherwise refetch on
    // every render that touches auth rather than only on login/logout.
    // preferences.llmToneEnabled is read at fetch time, not watched here --
    // toggling it re-fetches via the dedicated effect below instead.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth?.accessToken]);

  useEffect(() => {
    if (apiConfigured && auth?.accessToken && auth.actor.mfaSatisfied) {
      void fetchRoster();
    } else {
      setLiveTeamId(null);
      setLiveRoster([]);
      setRosterStatus("idle");
    }
    // fetchRoster is stable for the current access token. The MFA flag is the
    // authority transition that makes coach resources reachable.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth?.accessToken, auth?.actor.mfaSatisfied]);

  useEffect(() => {
    if (apiConfigured && auth?.accessToken) void fetchGuidance(preferences.llmToneEnabled);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preferences.llmToneEnabled]);

  // fetchRoster resolves liveTeamId asynchronously (a second network call
  // after GET /teams/mine), so team-scoped assignments are fetched once it
  // settles rather than in the same effect as the rest of login-time data.
  useEffect(() => {
    if (apiConfigured && auth?.accessToken && liveTeamId) void fetchTeamAssignments(liveTeamId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveTeamId]);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", preferences.theme);
  }, [preferences.theme]);

  const appendAudit = useCallback((event: AuditEvent, summary: string) => {
    setData((current) => ({
      ...current,
      auditLog: [
        { id: `aud_${Date.now()}`, event, atUtc: new Date().toISOString(), summary },
        ...current.auditLog,
      ],
    }));
  }, []);

  /* ---------------- activities ---------------- */

  const persistPending = useCallback(
    (activities: Activity[]) => {
      const pending = activities.filter(
        (a) => a.syncState !== "SYNCED" && a.serverVersion === null,
      );
      writePendingQueue(accountId, pending);
    },
    [accountId],
  );

  const applySyncResult = useCallback(
    (localId: string, patch: Partial<Activity>) => {
      setData((current) => {
        const activities = current.activities.map((a) =>
          a.id === localId ? { ...a, ...patch } : a,
        );
        persistPending(activities);
        return { ...current, activities };
      });
    },
    [persistPending],
  );

  const syncOne = useCallback(
    async (record: Activity): Promise<void> => {
      applySyncResult(record.id, {
        syncState: "SYNCING",
        syncAttempts: record.syncAttempts + 1,
      });

      if (!online) {
        applySyncResult(record.id, {
          syncState: "FAILED_RETRYABLE",
          lastErrorCode: "NETWORK_ERROR",
        });
        return;
      }

      // With a backend configured the real POST /activities decides the
      // outcome; without one the transition is simulated so the queue
      // mechanics are still demonstrable.
      if (apiConfigured && auth?.accessToken) {
        try {
          const { status, body } = await createActivity(
            {
              client_mutation_id: record.clientMutationId,
              duration_minutes: record.durationMinutes,
              rpe: record.rpe ?? 0,
              performed_at: record.performedAtUtc,
              distance_km: record.distanceKm,
              structure: record.structure,
            },
            auth.accessToken,
          );
          applySyncResult(record.id, {
            syncState: "SYNCED",
            serverVersion: body.server_version,
            localTrainingDate: body.local_training_date,
            timezoneSnapshot: body.timezone_snapshot,
            sessionLoad: body.session_load,
            structure: body.structure,
            distanceKm: body.distance_km,
            deviceMetrics: body.device_metrics,
            lastErrorCode: null,
          });
          if (status === 200) {
            push("info", "這筆紀錄伺服器上已存在", "冪等鍵比對相符，沒有重複建立。");
          }
          // task 5.1: History/Training Load are server-sourced now, so a
          // successful sync needs an explicit refetch to show up there —
          // the local `data.activities` write above only feeds the
          // pending-queue overlay (spec.md "A New Activity Refreshes
          // Dependent Views").
          void fetchHistory(null);
          void fetchTrend();
        } catch (err) {
          const isRetryable = !(err instanceof ApiError) || err.status >= 500;
          applySyncResult(record.id, {
            syncState: isRetryable ? "FAILED_RETRYABLE" : "FAILED_TERMINAL",
            lastErrorCode:
              err instanceof ApiError ? err.code : "NETWORK_ERROR",
          });
        }
        return;
      }

      await new Promise((resolve) => setTimeout(resolve, 550));
      applySyncResult(record.id, {
        syncState: "SYNCED",
        serverVersion: 1,
        lastErrorCode: null,
      });
    },
    [applySyncResult, auth, online, push, fetchHistory, fetchTrend],
  );

  const logActivity = useCallback(
    async (input: LogActivityInput): Promise<Activity> => {
      const localId = `local_${crypto.randomUUID().slice(0, 8)}`;
      const record: Activity = {
        id: localId,
        // A real UUID, not localId -- the server's client_mutation_id
        // column is UUID-typed (design.md Decision 3: it's the idempotency
        // key, so a retry can never create a second row), while localId is
        // only ever a display-friendly local React/queue key and was never
        // a valid UUID itself.
        clientMutationId: crypto.randomUUID(),
        provider: "manual",
        providerActivityId: null,
        performedAtUtc: input.performedAtUtc,
        localTrainingDate: input.localTrainingDate,
        timezoneSnapshot: auth?.athlete.timezone ?? "Asia/Taipei",
        durationMinutes: input.durationMinutes,
        rpe: input.rpe,
        distanceKm: input.distanceKm,
        structure: input.structure ?? [],
        deviceMetrics: {},
        sessionLoad: input.durationMinutes * input.rpe,
        unit: "AU",
        sourceMetric: "SESSION_RPE",
        note: input.note,
        syncState: "LOCAL_ONLY",
        syncAttempts: 0,
        lastErrorCode: null,
        serverVersion: null,
        duplicateCandidateOf: null,
      };

      // Durable commit happens here, before this function resolves. The caller
      // may only render a "已儲存" confirmation once this has settled.
      setData((current) => {
        const activities = [record, ...current.activities];
        persistPending(activities);
        return { ...current, activities };
      });
      writePendingQueue(accountId, [record, ...readPendingQueue(accountId)]);

      // Hand the record straight to the sync path. Passing the object rather
      // than its id matters: a lookup by id would race the state update this
      // function just queued and find nothing.
      void syncOne(record);

      return record;
    },
    [accountId, auth, persistPending, syncOne],
  );

  const syncNow = useCallback(async () => {
    const pending = data.activities.filter(
      (a) => a.syncState === "LOCAL_ONLY" || a.syncState === "FAILED_RETRYABLE",
    );
    if (pending.length === 0) return;

    setSyncing(true);
    try {
      for (const record of pending) {
        await syncOne(record);
      }
    } finally {
      setSyncing(false);
    }
  }, [data.activities, syncOne]);

  const retryActivity = useCallback(
    async (localId: string) => {
      const record = data.activities.find((a) => a.id === localId);
      if (!record) return;
      setSyncing(true);
      try {
        await syncOne(record);
      } finally {
        setSyncing(false);
      }
    },
    [data.activities, syncOne],
  );

  const discardActivity = useCallback(
    (localId: string) => {
      setData((current) => {
        const activities = current.activities.filter((a) => a.id !== localId);
        persistPending(activities);
        return { ...current, activities };
      });
      push("info", "已刪除這筆本地紀錄");
    },
    [persistPending, push],
  );

  const deleteActivity = useCallback(
    async (activityId: string): Promise<boolean> => {
      if (apiConfigured) {
        if (!auth?.accessToken) return false;
        try {
          await apiDeleteActivity(auth.accessToken, activityId);
          setLiveActivities((current) => current.filter((a) => a.id !== activityId));
          void fetchTrend();
          push("success", "已刪除這筆訓練紀錄");
          return true;
        } catch (err) {
          push(
            "critical",
            "刪除失敗",
            err instanceof ApiError ? err.message : "請稍後再試。",
          );
          return false;
        }
      }
      setData((current) => {
        const activities = current.activities.filter((a) => a.id !== activityId);
        persistPending(activities);
        return {
          ...current,
          activities,
          garminActivities: current.garminActivities.filter((a) => a.id !== activityId),
        };
      });
      push("success", "已刪除這筆訓練紀錄");
      return true;
    },
    [auth, fetchTrend, persistPending, push],
  );

  const resolveDuplicate = useCallback(
    (activityId: string, action: "keep_both" | "mark_duplicate") => {
      setData((current) => ({
        ...current,
        activities: current.activities.map((a) =>
          a.id === activityId
            ? {
                ...a,
                duplicateCandidateOf: action === "keep_both" ? null : a.duplicateCandidateOf,
                note:
                  action === "mark_duplicate"
                    ? `${a.note}（已由你確認為重複，原始版本保留於 athlete_annotations）`
                    : a.note,
              }
            : a,
        ),
      }));
      push(
        "success",
        action === "keep_both" ? "已確認為兩場不同的訓練" : "已標記為重複紀錄",
        "系統不會自動刪除或合併紀錄，原始版本一律保留。",
      );
    },
    [push],
  );

  /* ---------------- injury ---------------- */

  const addInjuryReport = useCallback(
    async (input: {
      clientMutationId: string;
      localDate: string;
      hasIssue: boolean;
      severityBand: SeverityBand;
      bodyPart: string;
      freeText: string;
    }) => {
      if (apiConfigured && auth?.accessToken) {
        try {
          const created = await apiCreateInjuryReport(auth.accessToken, {
            client_mutation_id: input.clientMutationId,
            has_issue: input.hasIssue,
            severity_band: input.hasIssue ? input.severityBand : "NONE",
            body_part: input.hasIssue ? input.bodyPart : null,
            free_text: input.freeText.trim() || null,
            reported_at: localDateTimeToUtcIso(
              input.localDate,
              "12:00",
              auth.athlete.timezone,
            ),
          });
          await fetchAthleteData();
          push("success", "已記錄身體狀況");
          return created.id;
        } catch {
          push("critical", "身體狀況儲存失敗", "請確認連線後再試一次。");
          return null;
        }
      }
      const id = `inj_${crypto.randomUUID().slice(0, 4)}`;
      const report: InjuryReport = {
        id,
        localDate: input.localDate,
        hasIssue: input.hasIssue,
        severityBand: input.hasIssue ? input.severityBand : "NONE",
        bodyPart: input.hasIssue ? input.bodyPart : "",
        createdAtUtc: new Date().toISOString(),
      };
      // The free text goes to its own table with its own consent scope —
      // never as a column on the summary row (REQ-RLS-007).
      const detail: InjuryReportDetail | null = input.freeText.trim()
        ? { injuryReportId: id, freeText: input.freeText.trim() }
        : null;

      setData((current) => ({
        ...current,
        injuryReports: [report, ...current.injuryReports],
        injuryDetails: detail ? [detail, ...current.injuryDetails] : current.injuryDetails,
      }));
      push("success", "已記錄身體狀況");
      return id;
    },
    [auth, fetchAthleteData, push],
  );

  const requestInjuryGuidance = useCallback(
    async (injuryReportId: string, flags: InjuryGuidanceFlags) => {
      if (!apiConfigured || !auth?.accessToken) return null;
      try {
        return await apiCreateInjuryGuidance(auth.accessToken, injuryReportId, flags);
      } catch {
        push("critical", "健康教練資訊載入失敗", "回報已送出，稍後可再試一次。");
        return null;
      }
    },
    [auth, push],
  );

  /* ---------------- consent & team ---------------- */

  const setConsent = useCallback(
    async (scope: ConsentScope, granted: boolean, requestedTeamId?: string) => {
      const now = new Date().toISOString();
      if (apiConfigured && auth?.accessToken) {
        const teamId = requestedTeamId ?? liveMemberships?.find((m) => m.status === "ACTIVE")?.teamId;
        if (!teamId) {
          push("warning", "目前沒有可調整授權的有效團隊");
          return;
        }
        try {
          const updated = await updateMyConsentGrant(
            auth.accessToken,
            teamId,
            scope,
            granted,
          );
          setLiveConsents((current) => {
            const next: ConsentGrant = {
              teamId: updated.team_id,
              scope: updated.scope,
              granted: updated.granted,
              changedAtUtc: updated.changed_at,
            };
            const without = (current ?? []).filter(
              (item) => !(item.teamId === next.teamId && item.scope === next.scope),
            );
            return [...without, next];
          });
          if (!granted) {
            setConsentRevokedAt(now);
            setTimeout(() => setConsentRevokedAt(null), 5000);
          }
          push("success", granted ? "已開啟分享範圍" : "已撤銷分享範圍");
        } catch {
          push("critical", "授權變更失敗", "伺服器沒有套用這次變更。");
        }
        return;
      }
      setData((current) => ({
        ...current,
        consents: current.consents.map((c) =>
          c.scope === scope ? { ...c, granted, changedAtUtc: now } : c,
        ),
      }));
      appendAudit(
        granted ? "CONSENT_GRANT" : "CONSENT_REVOKE",
        `${granted ? "開啟" : "撤銷"}「${scope}」對 ${data.memberships[0]?.teamName ?? "團隊"} 的授權`,
      );
      if (!granted) {
        // REQ-CONSENT-003: the projection cache has ≤5s to drop it; the API
        // path itself is already denied on the next request.
        setConsentRevokedAt(now);
        setTimeout(() => setConsentRevokedAt(null), 5000);
      }
    },
    [appendAudit, auth, data.memberships, liveMemberships, push],
  );

  const acceptInvitation = useCallback(
    async (teamId: string) => {
      if (apiConfigured && auth?.accessToken) {
        try {
          await updateMyTeamMembership(auth.accessToken, teamId, "accept");
          await fetchAthleteData();
          push("success", "已加入團隊", "接下來請逐項選擇要分享哪些範圍。");
        } catch {
          push("critical", "無法接受邀請", "邀請可能已失效，請重新整理。");
        }
        return;
      }
      const now = new Date().toISOString();
      setData((current) => ({
        ...current,
        memberships: current.memberships.map((m) =>
          m.teamId === teamId ? { ...m, status: "ACTIVE" as const, joinedAtUtc: now } : m,
        ),
      }));
      appendAudit("CONSENT_GRANT", "接受團隊邀請並完成同意流程");
      push("success", "已加入團隊", "接下來請逐項選擇要分享哪些範圍。");
    },
    [appendAudit, auth, fetchAthleteData, push],
  );

  const declineInvitation = useCallback(
    async (teamId: string) => {
      if (apiConfigured && auth?.accessToken) {
        try {
          await updateMyTeamMembership(auth.accessToken, teamId, "decline");
          await fetchAthleteData();
          push("info", "已婉拒邀請");
        } catch {
          push("critical", "無法處理邀請", "請重新整理後再試。");
        }
        return;
      }
      setData((current) => ({
        ...current,
        memberships: current.memberships.filter((m) => m.teamId !== teamId),
      }));
      push("info", "已婉拒邀請");
    },
    [auth, fetchAthleteData, push],
  );

  const leaveTeam = useCallback(
    async (teamId: string) => {
      const now = new Date().toISOString();
      if (apiConfigured && auth?.accessToken) {
        try {
          await updateMyTeamMembership(auth.accessToken, teamId, "leave");
          await fetchAthleteData();
          setConsentRevokedAt(now);
          setTimeout(() => setConsentRevokedAt(null), 5000);
          push("success", "已離開團隊", "教練儀表板已即時移除你的個人資料。");
        } catch {
          push("critical", "無法離開團隊", "伺服器沒有套用這次變更。");
        }
        return;
      }
      setData((current) => ({
        ...current,
        memberships: current.memberships.map((m) =>
          m.teamId === teamId
            ? { ...m, status: "LEFT" as const, leftAtUtc: now }
            : m,
        ),
        // REQ-CONSENT-004: leaving revokes every scope. Rejoining starts over.
        consents: current.consents.map((c) =>
          c.teamId === teamId ? { ...c, granted: false, changedAtUtc: now } : c,
        ),
      }));
      appendAudit("CONSENT_REVOKE", "離開團隊，所有授權範圍同時撤銷");
      setConsentRevokedAt(now);
      setTimeout(() => setConsentRevokedAt(null), 5000);
      push("success", "已離開團隊", "教練儀表板已即時移除你的個人資料。");
    },
    [appendAudit, auth, fetchAthleteData, push],
  );

  /* ---------------- account ---------------- */

  const revokeSession = useCallback(
    async (sessionId: string) => {
      if (apiConfigured && auth?.accessToken) {
        try {
          await revokeMySession(auth.accessToken, sessionId);
          await fetchSessions();
          push("success", "已登出該裝置");
        } catch {
          push("critical", "撤銷 session 失敗", "請稍後再試。");
        }
        return;
      }
      setData((current) => ({
        ...current,
        sessions: current.sessions.filter((s) => s.id !== sessionId),
      }));
      push("success", "已登出該裝置");
    },
    [auth, fetchSessions, push],
  );

  const revokeOtherSessions = useCallback(async () => {
    if (apiConfigured && auth?.accessToken) {
      const others = (liveSessions ?? []).filter((s) => !s.isCurrent);
      try {
        await Promise.all(others.map((s) => revokeMySession(auth.accessToken as string, s.id)));
        await fetchSessions();
        push("success", "已登出其他所有裝置");
      } catch {
        push("critical", "登出其他裝置失敗", "請稍後再試。");
      }
      return;
    }
    setData((current) => ({
      ...current,
      sessions: current.sessions.filter((s) => s.isCurrent),
    }));
    push("success", "已登出其他所有裝置");
  }, [auth, fetchSessions, liveSessions, push]);

  const updateProfile = useCallback(
    async (patch: { timezone?: string; city?: string; sex?: "male" | "female" }) => {
      if (apiConfigured && auth?.accessToken) {
        try {
          await apiUpdateProfile(auth.accessToken, patch);
          setData((current) => ({ ...current, athlete: { ...current.athlete, ...patch } }));
          push(
            "success",
            "已更新個人設定",
            patch.timezone
              ? "時區變更只影響之後的紀錄；既有紀錄保留當時的 timezone_snapshot。"
              : undefined,
          );
          if (patch.city || patch.sex) void fetchWeather();
        } catch {
          push("critical", "更新個人設定失敗", "請稍後再試。");
        }
        return;
      }

      setData((current) => ({
        ...current,
        athlete: { ...current.athlete, ...patch },
      }));
      push(
        "success",
        "已更新個人設定",
        patch.timezone
          ? "時區變更只影響之後的紀錄；既有紀錄保留當時的 timezone_snapshot。"
          : undefined,
      );
    },
    [auth, push, fetchWeather],
  );

  const exportData = useCallback(async () => {
    let payload: Record<string, unknown> = {
      exported_at: new Date().toISOString(),
      scope: "athlete-owned",
      athlete: data.athlete,
      completed_activities: data.activities,
      injury_reports: data.injuryReports,
      injury_report_details: data.injuryDetails,
      consents: data.consents,
      memberships: data.memberships,
      audit_log: data.auditLog,
    };
    if (apiConfigured && auth?.accessToken) {
      try {
        // REQ-PRIV-001: this is the server's own athlete-owned data, not the
        // client-assembled payload used in demo mode -- the server also
        // records the DATA_EXPORT audit entry for us (see settings.py).
        payload = await exportMyPrivacyData(auth.accessToken);
      } catch {
        push("critical", "匯出資料失敗", "請稍後再試。");
        return;
      }
    }
    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `runsense-export-${data.today}.json`;
    a.click();
    URL.revokeObjectURL(url);

    setLastExportAtUtc(new Date().toISOString());
    if (apiConfigured && auth?.accessToken) {
      await fetchAuditLog();
    } else {
      appendAudit("DATA_EXPORT", "匯出個人完整資料（已完成 step-up 驗證）");
    }
    push("success", "已匯出資料", "已下載的檔案無法技術性追回，請自行妥善保管。");
  }, [appendAudit, auth, data, fetchAuditLog, push]);

  const requestAccountDeletion = useCallback(async () => {
    if (apiConfigured && auth?.accessToken) {
      try {
        const result = await requestMyAccountDeletion(auth.accessToken);
        setDeletionRequest({
          requestedAtUtc: result.deletion_requested_at,
          // REQ-PRIV-003/005's actual retention-period deletion pipeline is
          // out of scope for this MVP (server only records the request --
          // see backend/app/routes/settings.py) -- this 30-day figure is
          // illustrative UI copy only, not a server-enforced schedule.
          purgeAfterUtc: new Date(
            new Date(result.deletion_requested_at).getTime() + 30 * 86_400_000,
          ).toISOString(),
          retainedForLegalReasons: ["訂閱與付款紀錄（依稅務法規保存 5 年）"],
        });
        push("warning", "已受理刪除申請", "已記錄申請時間；實際刪除排程不在本次示範範圍內。");
      } catch {
        push("critical", "刪除申請失敗", "請稍後再試。");
      }
      return;
    }
    const now = new Date();
    const purge = new Date(now.getTime() + 30 * 86_400_000);
    setDeletionRequest({
      requestedAtUtc: now.toISOString(),
      purgeAfterUtc: purge.toISOString(),
      retainedForLegalReasons: ["訂閱與付款紀錄（依稅務法規保存 5 年）"],
    });
    appendAudit("ROLE_CHANGE", "提出帳號刪除申請（已完成 step-up 驗證）");
    push("warning", "已受理刪除申請", "30 天內可以取消，期滿後資料將被刪除或去識別化。");
  }, [appendAudit, auth, push]);

  const cancelAccountDeletion = useCallback(() => {
    setDeletionRequest(null);
    push("success", "已取消刪除申請");
  }, [push]);

  const setPreference = useCallback(
    <K extends keyof Preferences>(key: K, value: Preferences[K]) => {
      setPreferences((current) => ({ ...current, [key]: value }));
    },
    [],
  );

  const setTheme = useCallback((theme: Theme) => {
    setPreferences((current) => ({ ...current, theme }));
  }, []);

  /* ---------------- derived ---------------- */

  const allActivities = useMemo(() => {
    if (apiConfigured) {
      const pending = data.activities.filter(
        (a) => a.syncState !== "SYNCED" && a.serverVersion === null,
      );
      const liveIds = new Set(liveActivities.map((a) => a.clientMutationId));
      const dedupedPending = pending.filter((a) => !liveIds.has(a.clientMutationId));
      const combined = [...dedupedPending, ...liveActivities].sort((a, b) =>
        a.performedAtUtc < b.performedAtUtc ? 1 : -1,
      );
      // If live backend has 0 activities (e.g. fresh demo account), fallback to rich demo activities
      if (combined.length === 0) {
        return data.activities;
      }
      return combined;
    }
    return preferences.garminSyncEnabled
      ? [...data.activities, ...data.garminActivities].sort((a, b) =>
          a.performedAtUtc < b.performedAtUtc ? 1 : -1,
        )
      : data.activities;
  }, [data.activities, data.garminActivities, liveActivities, preferences.garminSyncEnabled]);

  const trainingLoad = useMemo(() => {
    if (apiConfigured) {
      if (!liveTrend) return computeTrainingLoad(data.activities, data.today);
      const adapted = adaptTrainingLoadSummary(liveTrend);
      // If server returned empty observation window, fallback to rich demo calculations
      if (adapted.observationDays === 0 || adapted.units.length === 0) {
        return computeTrainingLoad(data.activities, data.today);
      }
      return adapted;
    }
    return computeTrainingLoad(allActivities, data.today);
  }, [allActivities, data.today, data.activities, liveTrend]);

  const pendingCount = useMemo(
    () =>
      data.activities.filter(
        (a) => a.syncState === "LOCAL_ONLY" || a.syncState === "FAILED_RETRYABLE",
      ).length,
    [data.activities],
  );

  // REQ-LOCAL-SEC-003: dropping the account also drops its local cache.
  useEffect(() => {
    if (!auth) localStorage.removeItem(pendingQueueKey(accountId));
  }, [auth, accountId]);

  const coachRoster = apiConfigured ? (liveRoster ?? []) : data.coachRoster;
  const memberships = apiConfigured ? (liveMemberships ?? []) : data.memberships;
  const consents = apiConfigured ? (liveConsents ?? []) : data.consents;
  const injuryReports = apiConfigured ? (liveInjuryReports ?? []) : data.injuryReports;
  const injuryDetails = apiConfigured ? (liveInjuryDetails ?? []) : data.injuryDetails;
  const sessions = apiConfigured ? (liveSessions ?? []) : data.sessions;
  const auditLog = apiConfigured ? (liveAuditLog ?? []) : data.auditLog;
  const assignments = apiConfigured ? (liveTeamAssignments ?? []) : data.assignments;
  // demoData.ts's assignments span several fictional athletes (so the coach
  // table above has a realistic multi-athlete roster to show) -- an
  // athlete's own view must still be scoped to just their own id.
  const myAssignedWorkouts = apiConfigured
    ? (liveMyAssignedWorkouts ?? [])
    : data.assignments.filter((a) => a.athleteId === data.athlete.id);

  const value: WorkspaceContextValue = {
    ...data,
    coachRoster,
    memberships,
    consents,
    injuryReports,
    injuryDetails,
    sessions,
    auditLog,
    assignments,
    myAssignedWorkouts,
    assignmentsStatus,
    createAssignment,
    deleteAssignment,
    liveGarminEnabled,
    liveGarminReason,
    allActivities,
    trainingLoad,
    preferences,
    online,
    syncing,
    pendingCount,
    consentRevokedAt,
    deletionRequest,
    lastExportAtUtc,
    setOnline,
    setTheme,
    setPreference,
    logActivity,
    syncNow,
    retryActivity,
    discardActivity,
    deleteActivity,
    resolveDuplicate,
    historyStatus,
    hasMoreHistory: historyNextCursor !== null,
    loadMoreHistory,
    refetchHistory: () => fetchHistory(null),
    liveTrend,
    trendStatus,
    refetchTrend: fetchTrend,
    liveWeather,
    weatherStatus,
    refetchWeather: fetchWeather,
    liveGuidance,
    guidanceStatus,
    refetchGuidance: () => fetchGuidance(preferences.llmToneEnabled),
    liveTrainingPlan,
    trainingPlanStatus,
    refetchTrainingPlan: fetchTrainingPlan,
    liveTeamId,
    liveTeamName,
    rosterStatus,
    refetchRoster: fetchRoster,
    athleteDataStatus,
    refetchAthleteData: fetchAthleteData,
    addInjuryReport,
    requestInjuryGuidance,
    setConsent,
    acceptInvitation,
    declineInvitation,
    leaveTeam,
    revokeSession,
    revokeOtherSessions,
    updateProfile,
    exportData,
    requestAccountDeletion,
    cancelAccountDeletion,
    appendAudit,
  };

  return (
    <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>
  );
}

export function useWorkspace(): WorkspaceContextValue {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used inside <WorkspaceProvider>");
  return ctx;
}
