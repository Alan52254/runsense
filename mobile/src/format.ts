// Pure formatting helpers. No react-native import on purpose -- this file
// runs under `node --test` (see src/format.test.ts) so the dashboard's
// number formatting is verified without a simulator.

export type Locale = 'zh-TW' | 'en';

// Seconds per km -> "m'ss\"" (e.g. 330 -> 5'30"). Negative or non-finite
// input is treated as unknown.
export function formatPace(secPerKm: number | null | undefined): string {
  if (secPerKm == null || !Number.isFinite(secPerKm) || secPerKm <= 0) {
    return '--';
  }
  const total = Math.round(secPerKm);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}'${String(s).padStart(2, '0')}"`;
}

// Training load: one decimal place, or an em dash when absent.
export function formatLoad(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '--';
  return value.toFixed(1);
}

// Acute/chronic ratio: two decimals, or a neutral "not enough data yet"
// label. Deliberately never returns a band/severity word (REQ-METRIC-001).
export function formatRatio(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return 'not enough data yet';
  return value.toFixed(2);
}

// "YYYY-MM-DD" -> short human label, locale-aware, always interpreted as a
// calendar date (UTC) so it does not shift across timezones.
export function formatLocalDate(iso: string, locale: Locale = 'zh-TW'): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso ?? '');
  if (!match) return iso ?? '';
  const [, y, m, d] = match;
  const date = new Date(Date.UTC(Number(y), Number(m) - 1, Number(d)));
  if (Number.isNaN(date.getTime())) return iso;
  const tag = locale === 'en' ? 'en-US' : 'zh-TW';
  return new Intl.DateTimeFormat(tag, {
    month: 'short',
    day: 'numeric',
    weekday: 'short',
    timeZone: 'UTC',
  }).format(date);
}

export function formatTemperature(celsius: number | null | undefined): string {
  if (celsius == null || !Number.isFinite(celsius)) return '--';
  return `${Math.round(celsius)}°C`;
}

// mm:ss for an elapsed-seconds counter (live run timer). Clamps negatives.
export function formatElapsed(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const mm = Math.floor(s / 60);
  const ss = s % 60;
  return `${String(mm).padStart(2, '0')}:${String(ss).padStart(2, '0')}`;
}
