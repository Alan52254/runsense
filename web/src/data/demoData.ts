/* Demo dataset.
 *
 * Everything here is fabricated seed data for a walkthrough — no real person,
 * no real team. It exists so every screen has something to show without a
 * Postgres instance. When the backend is reachable, `apiClient.ts` takes over
 * login and activity creation; the rest of the domain has no endpoints yet.
 *
 * The generator is seeded, so reloading gives the same 34 days rather than a
 * different chart every time.
 */

import { shiftLocalDate } from "../lib/trainingLoad.ts";
import type {
  Activity,
  AssignedWorkout,
  Athlete,
  AuditEntry,
  AuthSession,
  ConsentGrant,
  ConsentScope,
  InjuryReport,
  InjuryReportDetail,
  RecommendationObject,
  RestDay,
  TeamAthleteProjection,
  TeamMembership,
  ToneVariant,
  WeatherSnapshot,
} from "../lib/types.ts";

export const DEMO_TEAM_ID = "team_taipei_distance";
export const DEMO_TEAM_NAME = "臺北長跑訓練隊";

/** mulberry32 — small, deterministic, good enough for seed data. */
function seededRandom(seed: number): () => number {
  let a = seed;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function todayLocalDate(timezone: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

/** Builds the UTC instant for a local wall-clock time in the athlete's zone.
 *  Approximated by probing the zone's offset at that moment — enough for
 *  seed data, and it keeps local_training_date consistent with performed_at. */
function localToUtcIso(localDate: string, hour: number, timezone: string): string {
  const [y, m, d] = localDate.split("-").map(Number);
  const guess = Date.UTC(y, m - 1, d, hour, 0, 0);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    hour: "numeric",
    hour12: false,
  }).formatToParts(new Date(guess));
  const zoneHour = Number(parts.find((p) => p.type === "hour")?.value ?? hour);
  const offsetHours = ((zoneHour - hour + 36) % 24) - 12;
  return new Date(guess - offsetHours * 3_600_000).toISOString();
}

export const DEMO_ATHLETE: Athlete = {
  id: "ath_9f3c1b7a",
  name: "林哲宇",
  email: "runner.taipei@runsense.demo",
  timezone: "Asia/Taipei",
  city: "臺北市",
  ageDeclaredOver18: true,
  ageDeclaredAtUtc: "2026-05-02T03:12:00.000Z",
};

export const DEMO_COACH = {
  userId: "usr_coach_4a1e",
  name: "王士豪",
  email: "coach.wang@runsense.demo",
};

interface DaySpec {
  /** Days back from today. */
  back: number;
  kind: "run" | "rest" | "missing";
  durationMinutes?: number;
  rpe?: number;
  distanceKm?: number;
  note?: string;
  hour?: number;
}

/** A hand-shaped 34-day block: a build week, a down week, then a heavier
 *  stretch, with 5 confirmed rest days and 4 genuinely missing days so
 *  observation_days lands at 30/28-in-window — above the 21-day threshold,
 *  but visibly not a perfect record. */
const DAY_PLAN: DaySpec[] = [
  { back: 0, kind: "missing" },
  { back: 1, kind: "run", durationMinutes: 52, rpe: 6, distanceKm: 9.4, note: "河濱有氧跑，後段配速穩住", hour: 6 },
  { back: 2, kind: "rest" },
  { back: 3, kind: "run", durationMinutes: 78, rpe: 7, distanceKm: 15.2, note: "週末長跑，最後 3K 加速", hour: 6 },
  { back: 4, kind: "run", durationMinutes: 34, rpe: 3, distanceKm: 5.8, note: "恢復慢跑", hour: 19 },
  { back: 5, kind: "run", durationMinutes: 61, rpe: 8, distanceKm: 11.0, note: "節奏跑 5×1600m", hour: 6 },
  { back: 6, kind: "rest" },
  { back: 7, kind: "run", durationMinutes: 46, rpe: 5, distanceKm: 8.2, note: "輕鬆有氧", hour: 6 },
  { back: 8, kind: "run", durationMinutes: 55, rpe: 6, distanceKm: 10.1, hour: 6 },
  { back: 9, kind: "missing" },
  { back: 10, kind: "run", durationMinutes: 72, rpe: 7, distanceKm: 14.0, note: "山路長跑", hour: 6 },
  { back: 11, kind: "run", durationMinutes: 30, rpe: 3, distanceKm: 5.0, note: "慢跑放鬆", hour: 20 },
  { back: 12, kind: "rest" },
  { back: 13, kind: "run", durationMinutes: 58, rpe: 8, distanceKm: 10.6, note: "間歇 8×800m", hour: 6 },
  { back: 14, kind: "run", durationMinutes: 44, rpe: 5, distanceKm: 7.9, hour: 19 },
  { back: 15, kind: "run", durationMinutes: 66, rpe: 6, distanceKm: 12.3, hour: 6 },
  { back: 16, kind: "rest" },
  { back: 17, kind: "run", durationMinutes: 40, rpe: 4, distanceKm: 7.0, note: "下班後輕鬆跑", hour: 19 },
  { back: 18, kind: "run", durationMinutes: 85, rpe: 7, distanceKm: 17.1, note: "月中長跑", hour: 6 },
  { back: 19, kind: "missing" },
  { back: 20, kind: "run", durationMinutes: 50, rpe: 6, distanceKm: 9.0, hour: 6 },
  { back: 21, kind: "run", durationMinutes: 36, rpe: 4, distanceKm: 6.2, hour: 20 },
  { back: 22, kind: "rest" },
  { back: 23, kind: "run", durationMinutes: 62, rpe: 7, distanceKm: 11.5, note: "配速跑", hour: 6 },
  { back: 24, kind: "run", durationMinutes: 48, rpe: 5, distanceKm: 8.6, hour: 6 },
  { back: 25, kind: "run", durationMinutes: 33, rpe: 3, distanceKm: 5.5, hour: 19 },
  { back: 26, kind: "missing" },
  { back: 27, kind: "run", durationMinutes: 70, rpe: 6, distanceKm: 13.2, note: "長跑", hour: 6 },
  { back: 28, kind: "run", durationMinutes: 42, rpe: 5, distanceKm: 7.4, hour: 6 },
  { back: 29, kind: "rest" },
  { back: 30, kind: "run", durationMinutes: 56, rpe: 7, distanceKm: 10.2, hour: 6 },
  { back: 31, kind: "run", durationMinutes: 38, rpe: 4, distanceKm: 6.5, hour: 19 },
  { back: 32, kind: "run", durationMinutes: 64, rpe: 6, distanceKm: 12.0, hour: 6 },
  { back: 33, kind: "rest" },
];

export interface DemoWorkspace {
  athlete: Athlete;
  today: string;
  activities: Activity[];
  /** Only merged into the metric when the Garmin feature flag is on. */
  garminActivities: Activity[];
  restDays: RestDay[];
  injuryReports: InjuryReport[];
  injuryDetails: InjuryReportDetail[];
  memberships: TeamMembership[];
  consents: ConsentGrant[];
  sessions: AuthSession[];
  auditLog: AuditEntry[];
  weather: WeatherSnapshot;
  recommendation: RecommendationObject;
  toneVariants: ToneVariant[];
  selectedToneVariantId: string;
  emotionalContext: { adjustmentReasonCode: string; loadTrendDirection: string };
  coachRoster: TeamAthleteProjection[];
  departedNotice: { name: string; leftAtUtc: string };
  assignments: AssignedWorkout[];
}

export function buildDemoWorkspace(): DemoWorkspace {
  const tz = DEMO_ATHLETE.timezone;
  const today = todayLocalDate(tz);
  const rand = seededRandom(20260816);

  const activities: Activity[] = [];
  const restDays: RestDay[] = [];

  for (const spec of DAY_PLAN) {
    const localDate = shiftLocalDate(today, -spec.back);

    if (spec.kind === "rest") {
      restDays.push({
        localDate,
        restConfirmedByUser: true,
        confirmedAtUtc: localToUtcIso(localDate, 21, tz),
      });
      continue;
    }
    if (spec.kind === "missing") continue;

    const durationMinutes = spec.durationMinutes!;
    const rpe = spec.rpe!;
    const id = `act_${localDate.replace(/-/g, "")}_${Math.floor(rand() * 9000 + 1000)}`;

    activities.push({
      id,
      clientMutationId: id.replace("act_", "cmid_"),
      provider: "manual",
      providerActivityId: null,
      performedAtUtc: localToUtcIso(localDate, spec.hour ?? 6, tz),
      localTrainingDate: localDate,
      timezoneSnapshot: tz,
      durationMinutes,
      rpe,
      distanceKm: spec.distanceKm ?? null,
      sessionLoad: durationMinutes * rpe,
      unit: "AU",
      sourceMetric: "SESSION_RPE",
      note: spec.note ?? "",
      syncState: "SYNCED",
      syncAttempts: 1,
      lastErrorCode: null,
      serverVersion: 1,
      duplicateCandidateOf: null,
    });
  }

  // Three records that show the sync states off the happy path.
  const pendingDate = shiftLocalDate(today, -1);
  activities.unshift({
    id: "local_a71c4e29",
    clientMutationId: "local_a71c4e29",
    provider: "manual",
    providerActivityId: null,
    performedAtUtc: localToUtcIso(pendingDate, 20, tz),
    localTrainingDate: pendingDate,
    timezoneSnapshot: tz,
    durationMinutes: 28,
    rpe: 4,
    distanceKm: 4.8,
    sessionLoad: 112,
    unit: "AU",
    sourceMetric: "SESSION_RPE",
    note: "睡前補跑，當時在地下停車場沒有網路",
    syncState: "LOCAL_ONLY",
    syncAttempts: 0,
    lastErrorCode: null,
    serverVersion: null,
    duplicateCandidateOf: null,
  });

  const retryDate = shiftLocalDate(today, -4);
  activities.push({
    id: "local_c02f9d10",
    clientMutationId: "local_c02f9d10",
    provider: "manual",
    providerActivityId: null,
    performedAtUtc: localToUtcIso(retryDate, 21, tz),
    localTrainingDate: retryDate,
    timezoneSnapshot: tz,
    durationMinutes: 25,
    rpe: 3,
    distanceKm: 4.2,
    sessionLoad: 75,
    unit: "AU",
    sourceMetric: "SESSION_RPE",
    note: "課表外的補充慢跑",
    syncState: "FAILED_RETRYABLE",
    syncAttempts: 3,
    lastErrorCode: "HTTP_503",
    serverVersion: null,
    duplicateCandidateOf: null,
  });

  // REQ-DEDUP-002: near-identical to the day-3 long run. Flagged, never merged.
  const dupSource = activities.find((a) => a.localTrainingDate === shiftLocalDate(today, -3));
  if (dupSource) {
    activities.push({
      id: "act_dup_5b81",
      clientMutationId: "cmid_dup_5b81",
      provider: "manual",
      providerActivityId: null,
      performedAtUtc: localToUtcIso(shiftLocalDate(today, -3), 7, tz),
      localTrainingDate: shiftLocalDate(today, -3),
      timezoneSnapshot: tz,
      durationMinutes: 76,
      rpe: 7,
      distanceKm: 15.0,
      sessionLoad: 532,
      unit: "AU",
      sourceMetric: "SESSION_RPE",
      note: "手錶匯入的同一場長跑？",
      syncState: "SYNCED",
      syncAttempts: 1,
      lastErrorCode: null,
      serverVersion: 1,
      duplicateCandidateOf: dupSource.id,
    });
  }

  activities.sort((a, b) => (a.performedAtUtc < b.performedAtUtc ? 1 : -1));

  // Kept aside: only folded in when GARMIN_ACTIVITY_SYNC_ENABLED is turned on.
  const garminActivities: Activity[] = [2, 5, 8, 11, 15].map((back, i) => {
    const localDate = shiftLocalDate(today, -back);
    return {
      id: `act_garmin_${i}`,
      clientMutationId: `cmid_garmin_${i}`,
      provider: "garmin",
      providerActivityId: `9948${i}31207`,
      performedAtUtc: localToUtcIso(localDate, 18, tz),
      localTrainingDate: localDate,
      timezoneSnapshot: tz,
      durationMinutes: [45, 38, 52, 30, 61][i],
      rpe: null,
      distanceKm: [8.1, 6.6, 9.7, 5.2, 11.4][i],
      sessionLoad: [188, 141, 212, 96, 247][i],
      unit: "garmin_epoc",
      sourceMetric: "GARMIN_DEVICE_LOAD",
      note: "由 Garmin Connect 同步",
      syncState: "SYNCED",
      syncAttempts: 1,
      lastErrorCode: null,
      serverVersion: 1,
      duplicateCandidateOf: null,
    };
  });

  const injuryReports: InjuryReport[] = [
    {
      id: "inj_2f81",
      localDate: shiftLocalDate(today, -2),
      hasIssue: true,
      severityBand: "MILD",
      bodyPart: "右小腿",
      createdAtUtc: localToUtcIso(shiftLocalDate(today, -2), 22, tz),
    },
    {
      id: "inj_9c07",
      localDate: shiftLocalDate(today, -11),
      hasIssue: true,
      severityBand: "MODERATE",
      bodyPart: "左足底",
      createdAtUtc: localToUtcIso(shiftLocalDate(today, -11), 21, tz),
    },
    {
      id: "inj_4d55",
      localDate: shiftLocalDate(today, -20),
      hasIssue: false,
      severityBand: "NONE",
      bodyPart: "",
      createdAtUtc: localToUtcIso(shiftLocalDate(today, -20), 21, tz),
    },
  ];

  const injuryDetails: InjuryReportDetail[] = [
    {
      injuryReportId: "inj_2f81",
      freeText: "節奏跑隔天下樓梯時右小腿內側緊，走路不痛，跑起來前 10 分鐘會有感覺。",
    },
    {
      injuryReportId: "inj_9c07",
      freeText:
        "早上起床第一步足底刺痛，跑完反而比較鬆。已經換了新鞋，暫時把長跑距離降下來。",
    },
  ];

  const memberships: TeamMembership[] = [
    {
      teamId: DEMO_TEAM_ID,
      teamName: DEMO_TEAM_NAME,
      coachName: DEMO_COACH.name,
      status: "ACTIVE",
      invitedAtUtc: "2026-06-01T02:00:00.000Z",
      joinedAtUtc: "2026-06-02T13:24:00.000Z",
      leftAtUtc: null,
    },
    {
      teamId: "team_marathon_lab",
      teamName: "馬拉松實驗室",
      coachName: "周雅筑",
      status: "INVITED",
      invitedAtUtc: localToUtcIso(shiftLocalDate(today, -1), 15, tz),
      joinedAtUtc: null,
      leftAtUtc: null,
    },
  ];

  const consentScopes: ConsentScope[] = [
    "activity_summary",
    "training_load",
    "injury_status",
    "injury_detail",
  ];
  const consents: ConsentGrant[] = consentScopes.map((scope) => ({
    scope,
    teamId: DEMO_TEAM_ID,
    granted: scope !== "injury_detail",
    changedAtUtc: "2026-06-02T13:24:00.000Z",
  }));

  const sessions: AuthSession[] = [
    {
      id: "sess_current",
      device: "這個瀏覽器 · Chrome / Windows",
      ipMasked: "203.65.xxx.xxx",
      location: "臺北市",
      lastActiveAtUtc: new Date().toISOString(),
      isCurrent: true,
    },
    {
      id: "sess_phone",
      device: "RunSense App · iPhone 15",
      ipMasked: "111.82.xxx.xxx",
      location: "臺北市",
      lastActiveAtUtc: localToUtcIso(today, 7, tz),
      isCurrent: false,
    },
    {
      id: "sess_old",
      device: "Safari / macOS",
      ipMasked: "36.229.xxx.xxx",
      location: "新北市",
      lastActiveAtUtc: localToUtcIso(shiftLocalDate(today, -9), 22, tz),
      isCurrent: false,
    },
  ];

  const auditLog: AuditEntry[] = [
    { id: "aud_1", event: "AUTH_LOGIN", atUtc: new Date().toISOString(), summary: "從 Chrome / Windows 登入" },
    { id: "aud_2", event: "CONSENT_REVOKE", atUtc: localToUtcIso(shiftLocalDate(today, -3), 22, tz), summary: `撤銷「身體狀況自述原文」對 ${DEMO_TEAM_NAME} 的授權` },
    { id: "aud_3", event: "DATA_EXPORT", atUtc: localToUtcIso(shiftLocalDate(today, -6), 14, tz), summary: "匯出個人完整資料（已完成 step-up 驗證）" },
    { id: "aud_4", event: "AUTH_FAILURE", atUtc: localToUtcIso(shiftLocalDate(today, -6), 9, tz), summary: "密碼錯誤（連續第 1 次）" },
    { id: "aud_5", event: "CROSS_TENANT_DENIED", atUtc: localToUtcIso(shiftLocalDate(today, -8), 11, tz), summary: "馬拉松實驗室 嘗試讀取訓練負荷，因尚未加入該團隊而拒絕" },
    { id: "aud_6", event: "CONSENT_GRANT", atUtc: "2026-06-02T13:24:00.000Z", summary: `加入 ${DEMO_TEAM_NAME} 並授權訓練摘要、訓練負荷、身體狀況` },
    { id: "aud_7", event: "AUTH_LOGIN", atUtc: "2026-06-02T13:20:00.000Z", summary: "從 RunSense App / iPhone 登入" },
  ];

  const weather: WeatherSnapshot = {
    state: "LIVE",
    city: DEMO_ATHLETE.city,
    temperatureC: 31.4,
    humidityPct: 78,
    observedAtUtc: new Date(Date.now() - 12 * 60_000).toISOString(),
    paceAdjustmentSecPerKm: 14,
  };

  const recommendation: RecommendationObject = {
    id: "rec_today",
    localDate: today,
    workoutType: "輕鬆有氧跑",
    durationMinutes: 40,
    distanceKm: 7.0,
    targetPaceSecPerKm: 370,
    intensityLabel: "RPE 4–5",
    adjustmentReasonCode: "RECENT_LOAD_ELEVATED",
    algorithmVersion: "presc-2026.07.2",
  };

  const toneVariants: ToneVariant[] = [
    { id: "SUPPORTIVE_A", text: "最近幾週你把量堆起來了，今天照課表輕鬆跑就好，讓身體把訓練吸收進去。", reviewedBy: "運動科學顧問 · 李念真", reviewedAtUtc: "2026-07-14T02:00:00.000Z" },
    { id: "SUPPORTIVE_B", text: "穩定累積比單日突破更重要，今天維持節奏就是好的一天。", reviewedBy: "運動科學顧問 · 李念真", reviewedAtUtc: "2026-07-14T02:00:00.000Z" },
    { id: "STEADY_A", text: "課表照常，維持你目前的節奏。", reviewedBy: "產品 · 何宛庭", reviewedAtUtc: "2026-07-14T02:00:00.000Z" },
    { id: "CAUTION_A", text: "你回報了身體不適，今天請以能輕鬆對話的強度為上限。", reviewedBy: "運動科學顧問 · 李念真", reviewedAtUtc: "2026-07-14T02:00:00.000Z" },
    { id: "NEUTRAL_FALLBACK", text: "以下是今天的課表。", reviewedBy: "系統預設", reviewedAtUtc: "2026-07-14T02:00:00.000Z" },
  ];

  const coachRoster: TeamAthleteProjection[] = [
    {
      athleteId: DEMO_ATHLETE.id,
      name: DEMO_ATHLETE.name,
      joinedAtUtc: "2026-06-02T13:24:00.000Z",
      status: "ACTIVE",
      grantedScopes: ["activity_summary", "training_load", "injury_status"],
      acuteLoadAu: 1789,
      chronicLoadAu: 1642.5,
      loadRatio: 1.09,
      dataQuality: "OK",
      lastActivityLocalDate: shiftLocalDate(today, -1),
      last14DaysLoad: [312, 0, 546, 102, 488, 0, 230, 330, 0, 504, 90, 0, 464, 220],
      injuryHasIssue: true,
      injurySeverityBand: "MILD",
      injuryFreeText: null,
    },
    {
      athleteId: "ath_2c88d410",
      name: "陳品岑",
      joinedAtUtc: "2026-05-18T09:00:00.000Z",
      status: "ACTIVE",
      grantedScopes: ["activity_summary", "training_load", "injury_status", "injury_detail"],
      acuteLoadAu: 2140,
      chronicLoadAu: 1680,
      loadRatio: 1.27,
      dataQuality: "OK",
      lastActivityLocalDate: today,
      last14DaysLoad: [420, 180, 0, 560, 240, 300, 0, 480, 210, 350, 0, 520, 260, 400],
      injuryHasIssue: true,
      injurySeverityBand: "MODERATE",
      injuryFreeText: "左膝外側在下坡跑時會刺痛，平路沒事。這週先避開山路課表。",
    },
    {
      athleteId: "ath_71ab9e02",
      name: "黃柏睿",
      joinedAtUtc: "2026-06-20T04:30:00.000Z",
      status: "ACTIVE",
      grantedScopes: ["activity_summary"],
      acuteLoadAu: null,
      chronicLoadAu: null,
      loadRatio: null,
      dataQuality: "OK",
      lastActivityLocalDate: shiftLocalDate(today, -2),
      last14DaysLoad: [],
      injuryHasIssue: null,
      injurySeverityBand: null,
      injuryFreeText: null,
    },
    {
      athleteId: "ath_5e30c9f7",
      name: "吳采潔",
      joinedAtUtc: shiftLocalDate(today, -9) + "T01:00:00.000Z",
      status: "ACTIVE",
      grantedScopes: ["activity_summary", "training_load", "injury_status"],
      acuteLoadAu: 640,
      chronicLoadAu: 210,
      loadRatio: null,
      dataQuality: "INSUFFICIENT",
      lastActivityLocalDate: shiftLocalDate(today, -1),
      last14DaysLoad: [0, 0, 0, 0, 0, 240, 0, 180, 0, 0, 220, 0, 0, 200],
      injuryHasIssue: false,
      injurySeverityBand: "NONE",
      injuryFreeText: null,
    },
    {
      athleteId: "ath_a4470b19",
      name: "鄭宇翔",
      joinedAtUtc: "2026-04-11T02:00:00.000Z",
      status: "ACTIVE",
      grantedScopes: ["activity_summary", "training_load", "injury_status"],
      acuteLoadAu: 1420,
      chronicLoadAu: 1735,
      loadRatio: 0.82,
      dataQuality: "LOW",
      lastActivityLocalDate: shiftLocalDate(today, -1),
      last14DaysLoad: [280, 0, 340, 0, 410, 190, 0, 300, 220, 0, 380, 0, 260, 180],
      injuryHasIssue: false,
      injurySeverityBand: "NONE",
      injuryFreeText: null,
    },
  ];

  const assignments: AssignedWorkout[] = [
    { id: "asg_1", teamId: DEMO_TEAM_ID, athleteId: DEMO_ATHLETE.id, localDate: today, title: "輕鬆有氧 40 分", durationMinutes: 40, intensityLabel: "RPE 4–5", status: "SCHEDULED" },
    { id: "asg_2", teamId: DEMO_TEAM_ID, athleteId: "ath_2c88d410", localDate: today, title: "節奏跑 4×2000m", durationMinutes: 65, intensityLabel: "RPE 7", status: "SCHEDULED" },
    { id: "asg_3", teamId: DEMO_TEAM_ID, athleteId: "ath_5e30c9f7", localDate: today, title: "有氧 30 分", durationMinutes: 30, intensityLabel: "RPE 4", status: "SCHEDULED" },
    { id: "asg_4", teamId: DEMO_TEAM_ID, athleteId: DEMO_ATHLETE.id, localDate: shiftLocalDate(today, -1), title: "有氧 50 分", durationMinutes: 50, intensityLabel: "RPE 5–6", status: "COMPLETED" },
    { id: "asg_5", teamId: DEMO_TEAM_ID, athleteId: "ath_71ab9e02", localDate: shiftLocalDate(today, -1), title: "間歇 6×800m", durationMinutes: 55, intensityLabel: "RPE 8", status: "MISSED" },
  ];

  return {
    athlete: DEMO_ATHLETE,
    today,
    activities,
    garminActivities,
    restDays,
    injuryReports,
    injuryDetails,
    memberships,
    consents,
    sessions,
    auditLog,
    weather,
    recommendation,
    toneVariants,
    selectedToneVariantId: "SUPPORTIVE_A",
    emotionalContext: {
      adjustmentReasonCode: "RECENT_LOAD_ELEVATED",
      loadTrendDirection: "RISING",
    },
    coachRoster,
    departedNotice: {
      name: "蔡承翰",
      leftAtUtc: localToUtcIso(shiftLocalDate(today, -5), 20, tz),
    },
    assignments,
  };
}
