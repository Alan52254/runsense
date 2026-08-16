import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, Field, Notice, StatTile } from "../../components/ui.tsx";
import { SyncChip } from "../../components/domain.tsx";
import { Icon } from "../../components/Icon.tsx";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import { useAuth } from "../../state/AuthContext.tsx";
import { formatNumber, rpeDescription } from "../../lib/format.ts";
import type { Activity } from "../../lib/types.ts";

/** The performed-at instant is built from a local date + time in the athlete's
 *  own timezone, then stored as UTC — the browser's zone is not consulted for
 *  the date boundary (REQ-TZ-001). */
function toUtcIso(localDate: string, localTime: string, timezone: string): string {
  const [hour, minute] = localTime.split(":").map(Number);
  const [y, m, d] = localDate.split("-").map(Number);
  const guess = Date.UTC(y, m - 1, d, hour, minute);
  const zoneHour = Number(
    new Intl.DateTimeFormat("en-US", { timeZone: timezone, hour: "numeric", hour12: false })
      .formatToParts(new Date(guess))
      .find((p) => p.type === "hour")?.value ?? hour,
  );
  const offsetHours = ((zoneHour - hour + 36) % 24) - 12;
  return new Date(guess - offsetHours * 3_600_000).toISOString();
}

export function LogWorkoutScreen() {
  const { auth } = useAuth();
  const { today, logActivity, online, confirmRestDay, restDays, activities } =
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
      next.duration = "時長必須是大於 0 的有限數值";
    } else if (durationValue > 1440) {
      next.duration = "單次訓練時長不可超過 24 小時";
    }
    if (rpe < 1 || rpe > 10) next.rpe = "RPE 必須介於 1 到 10";
    if (localDate > today) next.localDate = "不能記錄未來的日期";
    if (distance.trim() && (!Number.isFinite(Number(distance)) || Number(distance) < 0)) {
      next.distance = "距離必須是非負數值";
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
        performedAtUtc: toUtcIso(localDate, localTime, timezone),
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
            <h1 className="page-title">已儲存</h1>
            <p className="page-desc">
              這筆紀錄已經寫入本機資料庫並完成提交，之後不論是否斷線都不會消失。
            </p>
          </div>
        </div>

        <Card
          title="剛剛建立的紀錄"
          actions={<SyncChip state={saved.syncState} />}
          footer={
            <>
              冪等鍵 <code className="mono">{saved.clientMutationId}</code> 就是這筆紀錄自己的本地 ID，
              重試同一筆不會在伺服器建立第二筆。
            </>
          }
        >
          <div className="grid-4">
            <StatTile small label="日期" value={saved.localTrainingDate} />
            <StatTile
              small
              label="時長"
              value={formatNumber(saved.durationMinutes)}
              unit="分"
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

        <Notice tone={online ? "accent" : "warning"} icon={online ? "cloud" : "wifi-off"}>
          {online
            ? "正在送往伺服器。若中途失敗，這筆紀錄會留在同步佇列並自動重試。"
            : "目前是離線模式，紀錄已排入同步佇列，恢復連線後會自動送出。"}
        </Notice>

        <div className="row">
          <Button variant="primary" icon="shoe" onClick={resetForm}>
            再記錄一筆
          </Button>
          <Link className="btn btn-secondary" to="/app/history">
            查看訓練紀錄
          </Link>
          <Link className="btn btn-ghost" to="/app">
            回總覽
          </Link>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">記錄訓練</h1>
          <p className="page-desc">
            Phase 1A 的訓練來源是你手動輸入的摘要。session_load 以 session-RPE 法計算，單位是 AU，
            與裝置提供的負荷數值不可互相比較。
          </p>
        </div>
      </div>

      <div className="dashboard-split">
        <Card title="訓練摘要">
          <form className="stack" onSubmit={submit}>
            <div className="grid-2">
              <Field label="訓練日期" htmlFor="f-date" error={errors.localDate}>
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
                label="開始時間"
                htmlFor="f-time"
                hint={`以 ${timezone} 判定日期歸屬`}
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
                label="時長（分鐘）"
                htmlFor="f-duration"
                error={errors.duration}
                hint="必填，必須是大於 0 的有限數值"
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
                label="距離（公里）"
                htmlFor="f-distance"
                error={errors.distance}
                hint="選填，不影響 session_load 計算"
              >
                <input
                  id="f-distance"
                  className="input"
                  type="number"
                  inputMode="decimal"
                  min={0}
                  step="0.1"
                  placeholder="例如 8.5"
                  value={distance}
                  onChange={(e) => setDistance(e.target.value)}
                />
              </Field>
            </div>

            <Field
              label="自覺強度 RPE"
              error={errors.rpe}
              hint={`${rpe} — ${rpeDescription(rpe)}`}
            >
              <div className="rpe-scale" role="radiogroup" aria-label="自覺強度 RPE">
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

            <Field label="備註" htmlFor="f-note" hint="選填。這段文字只有你看得到。">
              <textarea
                id="f-note"
                className="input"
                value={note}
                placeholder="例如：河濱有氧跑，後段配速穩住"
                onChange={(e) => setNote(e.target.value)}
              />
            </Field>

            <hr className="divider" />

            <div className="row-between">
              <div>
                <div className="stat-label">計算出的 session_load</div>
                <div className="stat-value" style={{ fontSize: 26 }}>
                  {formatNumber(sessionLoad)}
                  <span className="stat-unit">AU</span>
                </div>
                <div className="field-hint">
                  {formatNumber(Number.isFinite(durationValue) ? durationValue : 0)} 分 × RPE {rpe}
                </div>
              </div>
              <Button type="submit" variant="primary" size="lg" disabled={saving}>
                {saving ? "儲存中…" : "儲存訓練"}
              </Button>
            </div>
          </form>
        </Card>

        <div className="stack">
          <Card title="這筆紀錄會怎麼被處理">
            <ol className="stack-sm" style={{ fontSize: 13, lineHeight: 1.7 }}>
              <li>
                <strong>1. 本地持久化</strong>
                <div className="field-hint">
                  先寫入本機並完成提交，之後才會顯示「已儲存」。這個順序不可以顛倒。
                </div>
              </li>
              <li>
                <strong>2. 進入同步佇列</strong>
                <div className="field-hint">
                  狀態為 LOCAL_ONLY，等待送往伺服器；離線時就停在這一步。
                </div>
              </li>
              <li>
                <strong>3. 送出並比對版本</strong>
                <div className="field-hint">
                  衝突以 server_version／base_version 判定，不用裝置時間戳。
                </div>
              </li>
            </ol>
          </Card>

          <Card title="今天沒有訓練？">
            <div className="stack-sm">
              <p className="field-hint">
                系統不會因為「沒有資料」就推論你在休息。裝置沉默一律視為缺漏，不計入觀測天數的分母。
              </p>
              {alreadyRest ? (
                <Notice tone="accent" icon="check">
                  {localDate} 已標記為休息日。
                </Notice>
              ) : (
                <Button icon="check" onClick={() => confirmRestDay(localDate)}>
                  把 {localDate} 標記為休息日
                </Button>
              )}
            </div>
          </Card>

          <Card title="單位說明">
            <div className="stack-sm">
              <div className="row" style={{ gap: 8 }}>
                <Badge tone="accent">AU</Badge>
                <span className="field-hint">手動輸入：duration × RPE</span>
              </div>
              <div className="row" style={{ gap: 8 }}>
                <Badge>garmin_epoc</Badge>
                <span className="field-hint">裝置提供的負荷數值，直接採用</span>
              </div>
              <p className="field-hint" style={{ marginTop: 4 }}>
                <Icon name="info" size={13} /> 兩者不會被加成同一個數字。同一期間同時存在時，
                資料品質降為 LOW 並分開呈現趨勢。
              </p>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
