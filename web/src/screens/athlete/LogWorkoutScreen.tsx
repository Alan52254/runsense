import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, Field, Notice, StatTile } from "../../components/ui.tsx";
import { Icon } from "../../components/Icon.tsx";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import { useAuth } from "../../state/AuthContext.tsx";
import { useLocale } from "../../state/LocaleContext.tsx";
import { formatNumber, rpeDescription } from "../../lib/format.ts";
import { localDateTimeToUtcIso } from "../../lib/dateTime.ts";
import type { Activity } from "../../lib/types.ts";

export function LogWorkoutScreen() {
  const { locale } = useLocale();
  const en = locale === "en";
  const { auth } = useAuth();
  const { today, logActivity, confirmRestDay, restDays, activities } =
    useWorkspace();

  const timezone = auth?.athlete.timezone ?? "Asia/Taipei";

  const [localDate, setLocalDate] = useState(today);
  const [localTime, setLocalTime] = useState("06:30");
  const [duration, setDuration] = useState("45");
  const [rpe, setRpe] = useState(5);
  const [distance, setDistance] = useState("");
  const [note, setNote] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [savedId, setSavedId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Read the live row rather than the snapshot returned at save time, so the
  // sync chip below tracks LOCAL_ONLY -> SYNCING -> SYNCED as it happens.
  const saved: Activity | null =
    savedId === null ? null : (activities.find((a) => a.id === savedId) ?? null);

  const durationValue = Number(duration);
  const sessionLoad = useMemo(
    () => (Number.isFinite(durationValue) && durationValue > 0 ? durationValue * rpe : 0),
    [durationValue, rpe],
  );

  const alreadyRest = restDays.some((r) => r.localDate === localDate);

  function validate(): boolean {
    const next: Record<string, string> = {};

    if (!Number.isFinite(durationValue) || durationValue <= 0) {
      next.duration = en ? "Duration must be a finite number greater than 0" : "時長必須是大於 0 的有限數值";
    } else if (durationValue > 1440) {
      next.duration = en ? "A workout cannot exceed 24 hours" : "單次訓練時長不可超過 24 小時";
    }
    if (rpe < 1 || rpe > 10) next.rpe = en ? "RPE must be between 1 and 10" : "RPE 必須介於 1 到 10";
    if (localDate > today) next.localDate = en ? "Future dates cannot be logged" : "不能記錄未來的日期";
    if (distance.trim() && (!Number.isFinite(Number(distance)) || Number(distance) < 0)) {
      next.distance = en ? "Distance must be a non-negative number" : "距離必須是非負數值";
    }

    setErrors(next);
    return Object.keys(next).length === 0;
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!validate()) return;

    setSaving(true);
    try {
      // Resolves only after the record is durably committed locally — the
      // success panel below is what "已儲存" means (REQ-SYNC-001).
      const record = await logActivity({
        durationMinutes: durationValue,
        rpe,
        performedAtUtc: localDateTimeToUtcIso(localDate, localTime, timezone),
        localTrainingDate: localDate,
        distanceKm: distance.trim() ? Number(distance) : null,
        note: note.trim(),
      });
      setSavedId(record.id);
    } finally {
      setSaving(false);
    }
  }

  function resetForm() {
    setSavedId(null);
    setDuration("45");
    setRpe(5);
    setDistance("");
    setNote("");
    setErrors({});
  }

  if (saved) {
    return (
      <>
        <div className="page-head">
          <div>
            <h1 className="page-title">{en ? "Saved" : "已儲存"}</h1>
            <p className="page-desc">
              {en ? "This record has been saved to your account." : "這筆紀錄已經存入你的帳號。"}
            </p>
          </div>
        </div>

        <Card title={en ? "New record" : "剛剛建立的紀錄"}>
          <div className="grid-4">
            <StatTile small label={en ? "Date" : "日期"} value={saved.localTrainingDate} />
            <StatTile
              small
              label={en ? "Duration" : "時長"}
              value={formatNumber(saved.durationMinutes)}
              unit={en ? "min" : "分"}
            />
            <StatTile small label="RPE" value={`${saved.rpe}`} />
            <StatTile
              small
              label="session_load"
              value={formatNumber(saved.sessionLoad)}
              unit="AU"
              foot="duration × RPE"
            />
          </div>
        </Card>

        <div className="row">
          <Button variant="primary" icon="shoe" onClick={resetForm}>
            {en ? "Log another" : "再記錄一筆"}
          </Button>
          <Link className="btn btn-secondary" to="/app/history">
            {en ? "View history" : "查看訓練紀錄"}
          </Link>
          <Link className="btn btn-ghost" to="/app">
            {en ? "Back to overview" : "回總覽"}
          </Link>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">{en ? "Log Workout" : "手動補登"}</h1>
          <p className="page-desc">
            {en ? "Enter the duration, perceived exertion (RPE), and optional distance to update your fitness load." : "記下運動時長、自覺強度 (RPE) 與里程，系統將自動推算本次訓練負荷。"}
          </p>
        </div>
        <Link className="btn btn-primary" to="/app/run">
          <Icon name="runner" size={17} />
          {en ? "Start Run" : "出發開跑！"}
        </Link>
      </div>

      <div className="dashboard-split">
        <Card title={en ? "Workout Details" : "填寫訓練日誌"}>
          <form className="stack" onSubmit={submit}>
            <div className="grid-2">
              <Field label={en ? "Workout Date" : "訓練日期"} htmlFor="f-date" error={errors.localDate}>
                <input
                  id="f-date"
                  className="input"
                  type="date"
                  max={today}
                  value={localDate}
                  onChange={(e) => setLocalDate(e.target.value)}
                />
              </Field>
              <Field
                label={en ? "Start Time" : "開始時間"}
                htmlFor="f-time"
              >
                <input
                  id="f-time"
                  className="input"
                  type="time"
                  value={localTime}
                  onChange={(e) => setLocalTime(e.target.value)}
                />
              </Field>
            </div>

            <div className="grid-2">
              <Field
                label={en ? "Duration (minutes)" : "時長（分鐘）"}
                htmlFor="f-duration"
                error={errors.duration}
              >
                <input
                  id="f-duration"
                  className="input"
                  type="number"
                  inputMode="decimal"
                  min={1}
                  max={1440}
                  value={duration}
                  onChange={(e) => setDuration(e.target.value)}
                />
              </Field>
              <Field
                label={en ? "Distance (km)" : "距離（公里）"}
                htmlFor="f-distance"
                error={errors.distance}
                hint={en ? "Optional" : "選填"}
              >
                <input
                  id="f-distance"
                  className="input"
                  type="number"
                  inputMode="decimal"
                  min={0}
                  step="0.1"
                  placeholder={en ? "e.g. 8.5" : "例如 8.5"}
                  value={distance}
                  onChange={(e) => setDistance(e.target.value)}
                />
              </Field>
            </div>

            <Field
              label={en ? "Rate of perceived exertion (RPE)" : "自覺強度 RPE"}
              error={errors.rpe}
              hint={`${rpe} — ${en ? (["", "Very easy", "Very easy", "Easy", "Easy", "Moderate", "Moderate", "Hard", "Hard", "Near maximal", "Near maximal"])[rpe] : rpeDescription(rpe)}`}
            >
              <div className="rpe-scale" role="radiogroup" aria-label={en ? "Rate of perceived exertion" : "自覺強度 RPE"}>
                {Array.from({ length: 10 }, (_, i) => i + 1).map((value) => (
                  <button
                    key={value}
                    type="button"
                    role="radio"
                    aria-checked={rpe === value}
                    className="rpe-step"
                    data-selected={rpe === value}
                    onClick={() => setRpe(value)}
                  >
                    {value}
                  </button>
                ))}
              </div>
            </Field>

            <Field label={en ? "Note" : "備註"} htmlFor="f-note" hint={en ? "Optional. Only you can see this text." : "選填。這段文字只有你看得到。"}>
              <textarea
                id="f-note"
                className="input"
                value={note}
                placeholder={en ? "Example: Easy riverside run; pace settled in the second half" : "例如：河濱有氧跑，後段配速穩住"}
                onChange={(e) => setNote(e.target.value)}
              />
            </Field>

            <hr className="divider" />

            <div className="row-between">
              <div>
                <div className="stat-label">{en ? "Calculated session_load" : "計算出的 session_load"}</div>
                <div className="stat-value" style={{ fontSize: 26 }}>
                  {formatNumber(sessionLoad)}
                  <span className="stat-unit">AU</span>
                </div>
                <div className="field-hint">
                  {formatNumber(Number.isFinite(durationValue) ? durationValue : 0)} {en ? "min" : "分"} × RPE {rpe}
                </div>
              </div>
              <Button type="submit" variant="primary" size="lg" disabled={saving}>
                {saving ? (en ? "Saving…" : "儲存中…") : (en ? "Save workout" : "儲存訓練")}
              </Button>
            </div>
          </form>
        </Card>

        <div className="stack">
          <Card title={en ? "No workout today?" : "今天沒有訓練？"}>
            <div className="stack-sm">
              <p className="field-hint">
                {en ? "No data does not prove a rest day. Device silence is treated as missing and excluded from observed-day counts." : "系統不會因為「沒有資料」就推論你在休息。裝置沉默一律視為缺漏，不計入觀測天數的分母。"}
              </p>
              {alreadyRest ? (
                <Notice tone="accent" icon="check">
                  {localDate} {en ? "is marked as a rest day." : "已標記為休息日。"}
                </Notice>
              ) : (
                <Button icon="check" onClick={() => confirmRestDay(localDate)}>
                  {en ? `Mark ${localDate} as a rest day` : `把 ${localDate} 標記為休息日`}
                </Button>
              )}
            </div>
          </Card>

          <Card title={en ? "About load units" : "單位說明"}>
            <div className="stack-sm">
              <div className="row" style={{ gap: 8 }}>
                <Badge tone="accent">AU</Badge>
                <span className="field-hint">{en ? "Manual: duration × RPE" : "手動輸入：duration × RPE"}</span>
              </div>
              <div className="row" style={{ gap: 8 }}>
                <Badge>garmin_epoc</Badge>
                <span className="field-hint">{en ? "Device-provided load used as supplied" : "裝置提供的負荷數值，直接採用"}</span>
              </div>
              <p className="field-hint" style={{ marginTop: 4 }}>
                <Icon name="info" size={13} /> {en ? "These units are never summed. When both occur in one period, data quality is LOW and trends remain separate." : "兩者不會被加成同一個數字。同一期間同時存在時，資料品質降為 LOW 並分開呈現趨勢。"}
              </p>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
