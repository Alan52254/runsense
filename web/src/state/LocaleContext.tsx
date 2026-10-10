/* oxlint-disable react/only-export-components -- provider hook and locale types share context */
import { createContext, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

export type Locale = "zh-TW" | "en";
type Params = Record<string, string | number>;

const STORAGE_KEY = "runsense:locale";

const ZH = {
  language: "語言", zh: "繁體中文", en: "English", close: "關閉",
  athlete: "選手", coach: "教練", coachView: "教練視角",
  training: "訓練", account: "帳號", dashboard: "今日訓練", log: "手動補登",
  history: "歷程回顧", coachPlan: "教練課表", liveRun: "出發開跑！", load: "體能與疲勞", body: "身體感知", team: "跑團與隱私",
  settings: "個人偏好", method: "方法與依據", teamOverview: "團隊總覽", assignments: "課表排程",
  primaryNav: "主要導覽", more: "更多", openMore: "開啟更多功能",
  dashboardMeta: "今日課表、體能負荷與即時狀態", liveRunMeta: "跑步動態追蹤與數據儀表板", logMeta: "手動補登過去或離線完成的跑步",
  historyMeta: "所有跑步歷程與紀錄", coachPlanMeta: "教練安排的未來課表", loadMeta: "7 天／28 天體能與負荷趨勢",
  bodyMeta: "身體疲勞回報與傷痛感知", teamMeta: "跑團成員與教練授權管理",
  settingsMeta: "個人資料、安全、隱私與偏好", teamOverviewMeta: "選手體能與授權狀態彙整",
  methodMeta: "每個數字背後的演算法、門檻與實證來源",
  assignmentsMeta: "教練指派之訓練排程", athleteDetail: "選手詳情",
  athleteDetailMeta: "選手分享之訓練數據",
  themeLight: "切換為淺色佈景", themeDark: "切換為深色佈景", security: "安全設定", logout: "登出",
  online: "連線良好", offline: "離線狀態", live: "即時連線", demo: "展示模式",
  syncing: "同步中…", syncCount: "同步 {count} 筆",
  connectionHint: "切換連線狀態以測試離線佇列",
  moreTitle: "更多功能", moreDescription: "身體感知回報、跑團授權與個人設定。",
  moreLoad: "檢視體能與負荷趨勢", moreLog: "補登沒有手錶紀錄的訓練", moreBody: "回報今天身體狀態", moreTeam: "管理跑團與教練授權",
  moreSettings: "個人帳號與隱私設定", moreMethod: "查看演算法與實證依據", invites: "{count} 個跑團邀請",
  mfaError: "驗證失敗，請確認驗證碼", mfaTitle: "切換教練視角需要 MFA 驗證",
  mfaDescription: "切換至教練管理權限需完成身分驗證，確保隊伍資料安全。",
  cancel: "取消", verifying: "驗證中…", verifySwitch: "驗證並切換",
  mfaLabel: "請輸入 6 位數安全驗證碼", mfaHint: "示範環境固定為 {code}",
  mfaNotice: "此處使用示範驗證碼，模擬真實 TOTP / Passkey 流程。",
  loginHeadline: "為跑者打造的自主訓練數據中心",
  loginIntro: "你的每一次訓練、身體狀態與體能趨勢，都完整屬於你。由你自主決定與教練分享的數據範圍。",
  loginPointOffline: "無畏斷網：離線完成的訓練隨時補登，連線後自動安全同步。",
  loginPointLoad: "科學負荷：呈現真實 7 天與 28 天體能趨勢，不武斷標籤紅綠燈。",
  loginPointConsent: "隱私第一：身體狀況與自述文字獨立授權，尊重個人隱私。",
  loginTagline: "專注每一次邁步，掌管屬於你的訓練旅程。",
  loginTitle: "登入 RunSense", loginConnected: "已連接 RunSense 服務",
  loginDemo: "目前處於展示模式，點選下方帳號即可立即體驗：",
  email: "電子郵件", password: "密碼", passwordHint: "示範帳號密碼已預填",
  age: "我聲明已年滿 18 歲。",
  signingIn: "登入中…", signIn: "登入 RunSense", personas: "快速切換示範帳號",
  refreshLogin: "為保護隱私安全，重整頁面需重新登入。", teamName: "臺北長跑訓練隊",
  loginInvalid: "帳號或密碼不正確，可點下方示範帳號快速填入。",
  serverOffline: "無法連線至伺服器，請確認網路連線。",
  personaTaipei: "臺北教練（Asia/Taipei）", personaTokyo: "東京選手（Asia/Tokyo）", personaLondon: "倫敦選手（Europe/London）",
  coachAccounts: "教練帳號（Coach）", athleteAccounts: "選手帳號（Athletes）",
  coachAccountDesc: "管理跑團選手、指派課表與檢視訓練進度",
  athleteAccountDesc: "自主紀錄訓練、掌握個人體能與管理分享範圍",
  cadence: "即時步頻", calories: "估算消耗", splits: "公里分段", hrZone: "心率區間",
  hrZone1: "Z1 恢復", hrZone2: "Z2 有氧", hrZone3: "Z3 節奏", hrZone4: "Z4 閾值", hrZone5: "Z5 極限",
  lapDistance: "本公里進度", splitsPace: "分段配速", splitsDuration: "分段時間",
} as const;

const EN: Record<keyof typeof ZH, string> = {
  language: "Language", zh: "繁體中文", en: "English", close: "Close",
  athlete: "Athlete", coach: "Coach", coachView: "Coach View",
  training: "Training", account: "Account", dashboard: "Today's Run", log: "Log Workout",
  history: "Activity Log", coachPlan: "Coach Plan", liveRun: "Run Now!", load: "Fitness & Fatigue", body: "Body Status", team: "Team & Privacy",
  settings: "Settings", method: "Method & Evidence", teamOverview: "Team Overview", assignments: "Training Plan",
  primaryNav: "Primary Navigation", more: "More", openMore: "Open More Features",
  dashboardMeta: "Today's workout, fitness trends, and daily readiness", liveRunMeta: "Real-time running telemetry & HUD", logMeta: "Manually log a completed workout",
  historyMeta: "All past running records and sync status", coachPlanMeta: "Upcoming workouts from your coach", loadMeta: "7-day and 28-day fitness load trends",
  bodyMeta: "Discomfort reports and recovery radar", teamMeta: "Team members and coach sharing permissions",
  settingsMeta: "Profile, security, privacy, and preferences", teamOverviewMeta: "Athlete status and progress summary",
  methodMeta: "The algorithm, thresholds, and evidence behind every number",
  assignmentsMeta: "Coach-assigned workout schedule", athleteDetail: "Athlete Details",
  athleteDetailMeta: "Authorized training telemetry",
  themeLight: "Switch to light theme", themeDark: "Switch to dark theme", security: "Security Settings", logout: "Log out",
  online: "Online", offline: "Offline Mode", live: "Live Connected", demo: "Demo Mode",
  syncing: "Syncing…", syncCount: "Sync {count}",
  connectionHint: "Toggle connectivity to test offline queue behavior",
  moreTitle: "More Features", moreDescription: "Manage body status, team consent, and personal settings.",
  moreLoad: "Review fitness and load trends", moreLog: "Log a workout without a watch record", moreBody: "Report today's body status", moreTeam: "Manage team and coach permissions",
  moreSettings: "Account, privacy, and display preferences", moreMethod: "See the algorithms and evidence", invites: "{count} team invitations",
  mfaError: "Verification failed. Check the code.", mfaTitle: "MFA Required for Coach View",
  mfaDescription: "Elevating to coaching permissions requires multi-factor authentication.",
  cancel: "Cancel", verifying: "Verifying…", verifySwitch: "Verify & Switch",
  mfaLabel: "6-Digit Authenticator Code", mfaHint: "Demo code is {code}",
  mfaNotice: "Demo environment uses a fixed verification code.",
  loginHeadline: "Athlete-First Performance & Privacy",
  loginIntro: "Every workout, fitness metric, and body note belongs to you. You decide what your coach can see.",
  loginPointOffline: "Offline-First: Log runs anywhere without internet; syncs automatically once reconnected.",
  loginPointLoad: "Objective Load: Clear 7-day and 28-day trends without arbitrary traffic lights.",
  loginPointConsent: "Granular Privacy: Body status and private notes use independent sharing controls.",
  loginTagline: "Own your stride. Own your training data.",
  loginTitle: "Sign in to RunSense", loginConnected: "Connected to RunSense Service",
  loginDemo: "Demo mode active. Select an account below to explore:",
  email: "Email", password: "Password", passwordHint: "Demo password pre-filled",
  age: "I confirm that I am at least 18 years old.",
  signingIn: "Signing in…", signIn: "Sign In", personas: "Quick Select Demo Account",
  refreshLogin: "For security, refreshing requires signing in again.", teamName: "Taipei Distance Training Team",
  loginInvalid: "Incorrect email or password. Select a demo account below.",
  serverOffline: "Unable to reach the server. Please check your network.",
  personaTaipei: "Taipei Coach (Asia/Taipei)", personaTokyo: "Tokyo Athlete (Asia/Tokyo)", personaLondon: "London Athlete (Europe/London)",
  coachAccounts: "Coach Accounts", athleteAccounts: "Athlete Accounts",
  coachAccountDesc: "Manage team roster, assign workouts, and monitor authorized data",
  athleteAccountDesc: "Log runs, track fitness load, and manage granular consent",
  cadence: "Cadence", calories: "Est. Calories", splits: "Kilometer Splits", hrZone: "Heart Rate Zone",
  hrZone1: "Z1 Recovery", hrZone2: "Z2 Aerobic", hrZone3: "Z3 Tempo", hrZone4: "Z4 Threshold", hrZone5: "Z5 Anaerobic",
  lapDistance: "Current km lap", splitsPace: "Split Pace", splitsDuration: "Split Time",
};

export type MessageKey = keyof typeof ZH;

interface LocaleValue {
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: MessageKey, params?: Params) => string;
}

const LocaleContext = createContext<LocaleValue | null>(null);

function getInitialLocale(): Locale {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "zh-TW" || stored === "en") return stored;
  } catch { /* use browser preference */ }
  return navigator.language.toLowerCase().startsWith("zh") ? "zh-TW" : "en";
}

export function LocaleProvider({ children }: { children: ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(getInitialLocale);

  const setLocale = (next: Locale) => {
    setLocaleState(next);
    try { localStorage.setItem(STORAGE_KEY, next); } catch { /* session-only */ }
  };

  useEffect(() => { document.documentElement.lang = locale; }, [locale]);

  const value = useMemo<LocaleValue>(() => ({
    locale,
    setLocale,
    t: (key, params) => Object.entries(params ?? {}).reduce(
      (result, [name, replacement]) => result.replaceAll(`{${name}}`, String(replacement)),
      (locale === "en" ? EN : ZH)[key],
    ),
  }), [locale]);

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleValue {
  const value = useContext(LocaleContext);
  if (!value) throw new Error("useLocale must be used inside LocaleProvider");
  return value;
}
