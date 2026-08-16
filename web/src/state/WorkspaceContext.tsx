/* The athlete's working set: activities, rest days, injury reports, consent,
 * team memberships, sessions, audit log, and the handful of preferences the
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
  getActivityHistory,
  getTrainingLoadTrend,
  getWeather,
  getTodaysGuidance,
  setRestDay as apiSetRestDay,
  updateProfile as apiUpdateProfile,
  ApiError,
} from "../data/apiClient.ts";
import type {
  CreateActivityWireResponse,
  GuidanceWireResponse,
  TrainingLoadTrendWireResponse,
  WeatherWireResponse,
} from "../data/apiClient.ts";
import { computeTrainingLoad } from "../lib/trainingLoad.ts";
import type { TrainingLoadResult } from "../lib/trainingLoad.ts";
import { adaptTrainingLoadSummary } from "../lib/liveTrainingLoad.ts";
import type {
  Activity,
  ActivityProvider,
  AuditEvent,
  ConsentScope,
  InjuryReport,
  InjuryReportDetail,
  LoadUnit,
  SeverityBand,
  SourceMetric,
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
  confirmRestDay: (localDate: string, confirmed?: boolean) => void;
  resolveDuplicate: (activityId: string, action: "keep_both" | "mark_duplicate") => void;

  /** wire-live-training-data: real when apiConfigured, otherwise unused. */
  historyStatus: "idle" | "loading" | "error";
  hasMoreHistory: boolean;
  loadMoreHistory: () => Promise<void>;
  refetchHistory: () => Promise<void>;
  liveTrend: TrainingLoadTrendWireResponse | null;
  trendStatus: "idle" | "loading" | "error";
  refetchTrend: () => Promise<void>;
  /** Rest-day confirmations made this session when apiConfigured — see
   *  liveTrainingLoad.ts for why this can't be a full history yet. */
  confirmedRestDatesThisSession: Set<string>;
  liveWeather: WeatherWireResponse | null;
  weatherStatus: "idle" | "loading" | "error";
  refetchWeather: () => Promise<void>;
  liveGuidance: GuidanceWireResponse | null;
  guidanceStatus: "idle" | "loading" | "error";
  refetchGuidance: () => Promise<void>;

  addInjuryReport: (input: {
    localDate: string;
    hasIssue: boolean;
    severityBand: SeverityBand;
    bodyPart: string;
    freeText: string;
  }) => void;

  setConsent: (scope: ConsentScope, granted: boolean) => void;
  acceptInvitation: (teamId: string) => void;
  declineInvitation: (teamId: string) => void;
  leaveTeam: (teamId: string) => void;
  revokeSession: (sessionId: string) => void;
  revokeOtherSessions: () => void;
  updateProfile: (patch: { timezone?: string; city?: string }) => void;
  exportData: () => void;
  requestAccountDeletion: () => void;
  cancelAccountDeletion: () => void;
  appendAudit: (event: AuditEvent, summary: string) => void;
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

/** Server activities carry no `note`/`distanceKm`/duplicate-flag today —
 *  backend/app/schemas.py's CreateActivityRequest/ActivityResponse simply
 *  don't have those fields yet (REQ-DEDUP-002 is genuinely unimplemented,
 *  not just unfetched). Mapping to `null`/`""` here is honest, not lossy. */
function activityFromWire(wire: CreateActivityWireResponse): Activity {
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
    distanceKm: null,
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
  // No GET /rest-days list endpoint exists (see liveTrainingLoad.ts) — this is
  // session-local, not a full history, and is documented as such there.
  const [confirmedRestDatesThisSession, setConfirmedRestDatesThisSession] = useState<
    Set<string>
  >(new Set());

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

  useEffect(() => {
    if (apiConfigured && auth?.accessToken) {
      setConfirmedRestDatesThisSession(new Set());
      void fetchHistory(null);
      void fetchTrend();
      void fetchWeather();
      void fetchGuidance(preferences.llmToneEnabled);
    } else {
      setLiveActivities([]);
      setLiveTrend(null);
      setHistoryNextCursor(null);
      setLiveWeather(null);
      setLiveGuidance(null);
    }
    // Intentionally keyed on the token, not the fetch callbacks: those are
    // recreated whenever `auth` changes, which would otherwise refetch on
    // every render that touches auth rather than only on login/logout.
    // preferences.llmToneEnabled is read at fetch time, not watched here --
    // toggling it re-fetches via the dedicated effect below instead.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auth?.accessToken]);

  useEffect(() => {
    if (apiConfigured && auth?.accessToken) void fetchGuidance(preferences.llmToneEnabled);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preferences.llmToneEnabled]);

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
            },
            auth.accessToken,
          );
          applySyncResult(record.id, {
            syncState: "SYNCED",
            serverVersion: body.server_version,
            localTrainingDate: body.local_training_date,
            timezoneSnapshot: body.timezone_snapshot,
            sessionLoad: body.session_load,
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
        // design.md Decision 3: the record's own local id doubles as the
        // idempotency key, so a retry can never create a second row.
        clientMutationId: localId,
        provider: "manual",
        providerActivityId: null,
        performedAtUtc: input.performedAtUtc,
        localTrainingDate: input.localTrainingDate,
        timezoneSnapshot: auth?.athlete.timezone ?? "Asia/Taipei",
        durationMinutes: input.durationMinutes,
        rpe: input.rpe,
        distanceKm: input.distanceKm,
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

  const confirmRestDay = useCallback(
    async (localDate: string, confirmed: boolean = true) => {
      if (apiConfigured && auth?.accessToken) {
        try {
          const result = await apiSetRestDay(auth.accessToken, localDate, confirmed);
          setConfirmedRestDatesThisSession((current) => {
            const next = new Set(current);
            if (result.confirmed) next.add(result.date);
            else next.delete(result.date);
            return next;
          });
          void fetchTrend();
          push(
            "success",
            result.confirmed ? "已標記為休息日" : "已取消休息日標記",
            result.confirmed ? "只有你主動確認的休息日會計入觀測天數。" : undefined,
          );
        } catch (err) {
          if (err instanceof ApiError && err.code === "REST_DAY_CONFLICTS_WITH_ACTIVITY") {
            push("warning", "這天已經有訓練紀錄", "不能同時標記為休息日。");
          } else {
            push("critical", confirmed ? "標記休息日失敗" : "取消休息日標記失敗", "請稍後再試。");
          }
        }
        return;
      }

      setData((current) => {
        if (confirmed) {
          if (current.restDays.some((r) => r.localDate === localDate)) return current;
          return {
            ...current,
            restDays: [
              ...current.restDays,
              { localDate, restConfirmedByUser: true, confirmedAtUtc: new Date().toISOString() },
            ],
          };
        }
        return {
          ...current,
          restDays: current.restDays.filter((r) => r.localDate !== localDate),
        };
      });
      push(
        confirmed ? "success" : "info",
        confirmed ? "已標記為休息日" : "已取消休息日標記",
        confirmed ? "只有你主動確認的休息日會計入觀測天數。" : undefined,
      );
    },
    [auth, push, fetchTrend],
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
    (input: {
      localDate: string;
      hasIssue: boolean;
      severityBand: SeverityBand;
      bodyPart: string;
      freeText: string;
    }) => {
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
    },
    [push],
  );

  /* ---------------- consent & team ---------------- */

  const setConsent = useCallback(
    (scope: ConsentScope, granted: boolean) => {
      const now = new Date().toISOString();
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
    [appendAudit, data.memberships],
  );

  const acceptInvitation = useCallback(
    (teamId: string) => {
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
    [appendAudit, push],
  );

  const declineInvitation = useCallback(
    (teamId: string) => {
      setData((current) => ({
        ...current,
        memberships: current.memberships.filter((m) => m.teamId !== teamId),
      }));
      push("info", "已婉拒邀請");
    },
    [push],
  );

  const leaveTeam = useCallback(
    (teamId: string) => {
      const now = new Date().toISOString();
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
    [appendAudit, push],
  );

  /* ---------------- account ---------------- */

  const revokeSession = useCallback(
    (sessionId: string) => {
      setData((current) => ({
        ...current,
        sessions: current.sessions.filter((s) => s.id !== sessionId),
      }));
      push("success", "已登出該裝置");
    },
    [push],
  );

  const revokeOtherSessions = useCallback(() => {
    setData((current) => ({
      ...current,
      sessions: current.sessions.filter((s) => s.isCurrent),
    }));
    push("success", "已登出其他所有裝置");
  }, [push]);

  const updateProfile = useCallback(
    async (patch: { timezone?: string; city?: string }) => {
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
          if (patch.city) void fetchWeather();
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

  const exportData = useCallback(() => {
    const payload = {
      exported_at: new Date().toISOString(),
      scope: "athlete-owned",
      athlete: data.athlete,
      completed_activities: data.activities,
      rest_days: data.restDays,
      injury_reports: data.injuryReports,
      injury_report_details: data.injuryDetails,
      consents: data.consents,
      memberships: data.memberships,
      audit_log: data.auditLog,
    };
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
    appendAudit("DATA_EXPORT", "匯出個人完整資料（已完成 step-up 驗證）");
    push("success", "已匯出資料", "已下載的檔案無法技術性追回，請自行妥善保管。");
  }, [appendAudit, data, push]);

  const requestAccountDeletion = useCallback(() => {
    const now = new Date();
    const purge = new Date(now.getTime() + 30 * 86_400_000);
    setDeletionRequest({
      requestedAtUtc: now.toISOString(),
      purgeAfterUtc: purge.toISOString(),
      retainedForLegalReasons: ["訂閱與付款紀錄（依稅務法規保存 5 年）"],
    });
    appendAudit("ROLE_CHANGE", "提出帳號刪除申請（已完成 step-up 驗證）");
    push("warning", "已受理刪除申請", "30 天內可以取消，期滿後資料將被刪除或去識別化。");
  }, [appendAudit, push]);

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
      // Only genuinely-pending local writes overlay the server fetch — the
      // demo-seeded rows in `data.activities` are never shown once a real
      // backend is configured (spec.md "History Reads Real Activity Data").
      const pending = data.activities.filter(
        (a) => a.syncState !== "SYNCED" && a.serverVersion === null,
      );
      const liveIds = new Set(liveActivities.map((a) => a.clientMutationId));
      const dedupedPending = pending.filter((a) => !liveIds.has(a.clientMutationId));
      return [...dedupedPending, ...liveActivities].sort((a, b) =>
        a.performedAtUtc < b.performedAtUtc ? 1 : -1,
      );
    }
    return preferences.garminSyncEnabled
      ? [...data.activities, ...data.garminActivities].sort((a, b) =>
          a.performedAtUtc < b.performedAtUtc ? 1 : -1,
        )
      : data.activities;
  }, [data.activities, data.garminActivities, liveActivities, preferences.garminSyncEnabled]);

  const trainingLoad = useMemo(() => {
    if (apiConfigured) {
      if (!liveTrend) return computeTrainingLoad([], [], data.today);
      return adaptTrainingLoadSummary(liveTrend, confirmedRestDatesThisSession);
    }
    return computeTrainingLoad(allActivities, data.restDays, data.today);
  }, [allActivities, confirmedRestDatesThisSession, data.restDays, data.today, liveTrend]);

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

  const value: WorkspaceContextValue = {
    ...data,
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
    confirmRestDay,
    resolveDuplicate,
    historyStatus,
    hasMoreHistory: historyNextCursor !== null,
    loadMoreHistory,
    refetchHistory: () => fetchHistory(null),
    liveTrend,
    trendStatus,
    refetchTrend: fetchTrend,
    confirmedRestDatesThisSession,
    liveWeather,
    weatherStatus,
    refetchWeather: fetchWeather,
    liveGuidance,
    guidanceStatus,
    refetchGuidance: () => fetchGuidance(preferences.llmToneEnabled),
    addInjuryReport,
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
