import type {
  ConsentScope,
  DataQuality,
  LoadUnit,
  SeverityBand,
  SyncState,
  WeatherState,
} from "./types.ts";

export function formatNumber(n: number, digits = 0): string {
  return n.toLocaleString("zh-TW", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatCompact(n: number): string {
  if (Math.abs(n) >= 10_000) return `${round1(n / 1000)}K`;
  return formatNumber(n, Number.isInteger(n) ? 0 : 1);
}

export function round1(n: number): number {
  return Math.round(n * 10) / 10;
}

/** "2026-08-16" -> "8/16（六）" */
export function formatLocalDate(localDate: string): string {
  const [y, m, d] = localDate.split("-").map(Number);
  const weekday = "日一二三四五六"[new Date(Date.UTC(y, m - 1, d)).getUTCDay()];
  return `${m}/${d}（${weekday}）`;
}

export function formatLocalDateLong(localDate: string, locale: "zh-TW" | "en" = "zh-TW"): string {
  const [y, m, d] = localDate.split("-").map(Number);
  return new Intl.DateTimeFormat(locale, {
    timeZone: "UTC",
    year: "numeric",
    month: locale === "en" ? "long" : "numeric",
    day: "numeric",
  }).format(new Date(Date.UTC(y, m - 1, d)));
}

/** Renders a UTC instant in the athlete's own timezone (REQ-TZ-001). */
export function formatInstant(utcIso: string, timezone: string): string {
  return new Intl.DateTimeFormat("zh-TW", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(utcIso));
}

export function formatTimeOnly(utcIso: string, timezone: string): string {
  return new Intl.DateTimeFormat("zh-TW", {
    timeZone: timezone,
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(utcIso));
}

export function formatRelative(
  utcIso: string,
  nowMs = Date.now(),
  locale: "zh-TW" | "en" = "zh-TW",
): string {
  const diffMin = Math.round((nowMs - new Date(utcIso).getTime()) / 60_000);
  if (diffMin < 1) return locale === "en" ? "just now" : "剛剛";
  if (diffMin < 60) return locale === "en" ? `${diffMin} min ago` : `${diffMin} 分鐘前`;
  const diffHr = Math.round(diffMin / 60);
  if (diffHr < 24) return locale === "en" ? `${diffHr} hr ago` : `${diffHr} 小時前`;
  const diffDays = Math.round(diffHr / 24);
  return locale === "en" ? `${diffDays} days ago` : `${diffDays} 天前`;
}

/** 320 sec/km -> "5:20 /km" */
export function formatPace(secPerKm: number | null): string {
  if (secPerKm === null) return "—";
  const mins = Math.floor(secPerKm / 60);
  const secs = Math.round(secPerKm % 60);
  return `${mins}:${String(secs).padStart(2, "0")} /km`;
}

export function formatDuration(minutes: number, locale: "zh-TW" | "en" = "zh-TW"): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  if (locale === "en") return h > 0 ? `${h} hr ${m} min` : `${m} min`;
  return h > 0 ? `${h} 小時 ${m} 分` : `${m} 分`;
}

export const UNIT_LABEL: Record<LoadUnit, string> = {
  AU: "AU（手動 session-RPE）",
  garmin_epoc: "garmin_epoc（裝置負荷）",
};

export const UNIT_SHORT: Record<LoadUnit, string> = {
  AU: "AU",
  garmin_epoc: "EPOC",
};

export const SYNC_LABEL: Record<SyncState, string> = {
  LOCAL_ONLY: "待同步",
  SYNCING: "同步中",
  SYNCED: "已同步",
  FAILED_RETRYABLE: "同步失敗，會重試",
  FAILED_TERMINAL: "同步失敗，需處理",
};

export const DATA_QUALITY_LABEL: Record<DataQuality, string> = {
  OK: "資料完整",
  LOW: "資料品質偏低",
  INSUFFICIENT: "資料不足",
};

export const SEVERITY_LABEL: Record<SeverityBand, string> = {
  NONE: "無不適",
  MILD: "輕微",
  MODERATE: "中等",
  SEVERE: "嚴重",
};

export const CONSENT_LABEL: Record<ConsentScope, string> = {
  activity_summary: "訓練摘要",
  training_load: "訓練負荷趨勢",
  injury_status: "身體狀況（有無不適／程度）",
  injury_detail: "身體狀況自述原文",
};

export const CONSENT_DESCRIPTION: Record<ConsentScope, string> = {
  activity_summary: "教練可看到每次訓練的日期、時長、RPE 與 session load。",
  training_load: "教練可看到 7 天／28 天負荷與比值，以及資料品質標籤。",
  injury_status:
    "教練只看到「有無不適」與程度分級，看不到你寫的文字內容。",
  injury_detail:
    "教練可讀取你填寫的完整自述文字。這是獨立授權，不是「身體狀況」的附屬項目。",
};

export const WEATHER_STATE_LABEL: Record<WeatherState, string> = {
  LIVE: "即時資料",
  CACHED: "快取資料",
  STALE: "過期資料",
  UNAVAILABLE: "無法取得",
};

export const AUDIT_LABEL: Record<string, string> = {
  AUTH_LOGIN: "登入成功",
  AUTH_FAILURE: "登入失敗",
  ROLE_CHANGE: "角色變更",
  CONSENT_GRANT: "授權開啟",
  CONSENT_REVOKE: "授權撤銷",
  DATA_EXPORT: "資料匯出",
  CROSS_TENANT_DENIED: "跨團隊存取被拒",
  BILLING_CHANGE: "訂閱異動",
};

export function rpeDescription(rpe: number): string {
  if (rpe <= 2) return "非常輕鬆";
  if (rpe <= 4) return "輕鬆";
  if (rpe <= 6) return "中等";
  if (rpe <= 8) return "偏吃力";
  return "接近極限";
}
