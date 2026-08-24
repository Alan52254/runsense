import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Badge, Button, Card, Modal, Notice, StatTile, SwitchRow } from "../../components/ui.tsx";
import { Sparkline } from "../../components/charts.tsx";
import { Icon } from "../../components/Icon.tsx";
import { useLiveRun } from "../../state/LiveRunContext.tsx";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import { useAuth } from "../../state/AuthContext.tsx";
import { useToast } from "../../state/ToastContext.tsx";
import { useLocale } from "../../state/LocaleContext.tsx";
import { formatNumber, formatPace, rpeDescription } from "../../lib/format.ts";
import { utcInstantToLocalDate } from "../../lib/dateTime.ts";
import type { FinishedRun } from "../../lib/runTimer.ts";

function formatDuration(totalSec: number): string {
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  const mm = String(m).padStart(2, "0");
  const ss = String(s).padStart(2, "0");
  return h > 0 ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

function paceToMmSs(secPerKm: number): string {
  const m = Math.floor(secPerKm / 60);
  const s = Math.round(secPerKm % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function mmSsToPace(text: string): number | null {
  const match = /^(\d{1,2}):([0-5]?\d)$/.exec(text.trim());
  if (!match) return null;
  return Number(match[1]) * 60 + Number(match[2]);
}

export function LiveRunScreen() {
  const { locale, t } = useLocale();
  const en = locale === "en";
  const { auth } = useAuth();
  const { logActivity, online } = useWorkspace();
  const run = useLiveRun();
  const navigate = useNavigate();
  const { push } = useToast();

  const timezone = auth?.athlete.timezone ?? "Asia/Taipei";
  const [paceText, setPaceText] = useState(paceToMmSs(run.targetPaceSecPerKm));
  const [heartRateInput, setHeartRateInput] = useState("");
  const [finished, setFinished] = useState<FinishedRun | null>(null);
  const [endConfirmationOpen, setEndConfirmationOpen] = useState(false);
  const [overallRpe, setOverallRpe] = useState(5);
  const [saving, setSaving] = useState(false);

  const [autoHrSamples, setAutoHrSamples] = useState<number[]>([]);
  useEffect(() => {
    if (run.mode !== "auto" || run.phase !== "running") return;
    if (run.elapsedSec > 0 && run.elapsedSec % 15 === 0 && run.currentHrBpm !== null) {
      setAutoHrSamples((prev) =>
        prev[prev.length - 1] === run.currentHrBpm ? prev : [...prev, run.currentHrBpm as number],
      );
    }
  }, [run.elapsedSec, run.mode, run.phase, run.currentHrBpm]);

  const paceSecPerKm =
    run.mode === "auto"
      ? run.targetPaceSecPerKm
      : run.distanceKm > 0.05
        ? Math.round(run.elapsedSec / run.distanceKm)
        : null;
  const hrSparkline = run.mode === "auto" ? autoHrSamples : run.hrLog.map((r) => r.bpm);

  function logHeartRate() {
    const bpm = Number(heartRateInput);
    if (!Number.isFinite(bpm) || bpm <= 0 || bpm > 260) return;
    run.logHeartRate(bpm);
    setHeartRateInput("");
  }

  function applyPace() {
    const parsed = mmSsToPace(paceText);
    if (parsed !== null) run.setTargetPace(parsed);
    else setPaceText(paceToMmSs(run.targetPaceSecPerKm));
  }

  function finishRun() {
    setFinished(run.finish());
    setEndConfirmationOpen(false);
  }

  async function saveFinishedRun() {
    if (!finished) return;
    setSaving(true);
    try {
      const startedAtMs = Date.now() - finished.durationMinutes * 60_000;
      const lastHr =
        finished.hrLog.length > 0 ? finished.hrLog[finished.hrLog.length - 1].bpm : null;
      await logActivity({
        durationMinutes: Math.max(1, Math.round(finished.durationMinutes)),
        rpe: overallRpe,
        performedAtUtc: new Date(startedAtMs).toISOString(),
        localTrainingDate: utcInstantToLocalDate(startedAtMs, timezone),
        distanceKm: finished.distanceKm > 0 ? finished.distanceKm : null,
        note:
          finished.mode === "auto"
            ? en
              ? `Live Run Monitor (auto mode, target pace ${paceToMmSs(run.targetPaceSecPerKm)} /km used to estimate distance, cadence and heart rate).`
              : `即時監控記錄（自動模式，設定配速 ${paceToMmSs(run.targetPaceSecPerKm)} /km 推算距離、步頻與心率）。`
            : lastHr !== null
              ? en
                ? `Live Run Monitor (manual mode): heart rate logged ${finished.hrLog.length} time(s), last reading ${lastHr} bpm.`
                : `即時監控記錄（手動模式）：心率共記錄 ${finished.hrLog.length} 次，最後一次 ${lastHr} bpm。`
              : en
                ? "Live Run Monitor (manual mode)."
                : "即時監控記錄（手動模式）。",
      });
      run.reset();
      setAutoHrSamples([]);
      setFinished(null);
      push(
        "success",
        en ? "Training record created" : "已建立訓練紀錄",
        en
          ? "This live-monitored run has been saved to your training record."
          : "這次即時監控的結果已經寫入訓練紀錄。",
      );
      navigate("/app/history");
    } finally {
      setSaving(false);
    }
  }

  // Calculate current lap fraction
  const currentLapProgress = (run.distanceKm % 1).toFixed(2);

  if (finished) {
    return (
      <>
        <div className="page-head">
          <div>
            <h1 className="page-title">{en ? "Workout Completed!" : "本次跑步結算"}</h1>
            <p className="page-desc">
              {en
                ? "Rate your perceived exertion (RPE) to save this run to your personal log."
                : "為本次跑步評定自覺疲勞強度 (RPE)，即可存入個人跑步手帳。"}
            </p>
          </div>
        </div>
        <Card title={en ? "Workout Summary" : "跑步數據摘要"}>
          <div className="grid-3">
            <StatTile
              label={en ? "Duration" : "時長"}
              value={formatNumber(finished.durationMinutes, 1)}
              unit={en ? "min" : "分"}
            />
            <StatTile
              label={en ? "Distance" : "距離"}
              value={formatNumber(finished.distanceKm, 2)}
              unit="km"
            />
            <StatTile
              label={en ? "Average pace" : "平均配速"}
              value={finished.avgPaceSecPerKm ? formatPace(finished.avgPaceSecPerKm) : "—"}
            />
          </div>
          <div className="grid-3" style={{ marginTop: 14 }}>
            <StatTile
              label={t("calories")}
              value={finished.caloriesKcal ?? 0}
              unit="kcal"
            />
            <StatTile
              label={t("cadence")}
              value={finished.avgCadenceSpm ?? "—"}
              unit={finished.avgCadenceSpm ? "spm" : undefined}
            />
            <StatTile
              label={t("splits")}
              value={`${finished.splits?.length ?? 0} km`}
            />
          </div>
        </Card>

        {finished.splits && finished.splits.length > 0 && (
          <Card title={t("splits")}>
            <div className="table-scroll">
              <table className="splits-table">
                <thead>
                  <tr>
                    <th>{en ? "KM" : "公里"}</th>
                    <th>{t("splitsPace")}</th>
                    <th>{t("splitsDuration")}</th>
                  </tr>
                </thead>
                <tbody>
                  {finished.splits.map((s) => (
                    <tr key={s.km}>
                      <td><strong>{s.km} km</strong></td>
                      <td>{formatPace(s.paceSecPerKm)}</td>
                      <td>{formatDuration(s.durationSec)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        <Card
          title={en ? "Perceived exertion (RPE)" : "自覺強度 RPE"}
          subtitle={en ? "Used to calculate session_load (duration × RPE)" : "用來計算 session_load（時長 × RPE）"}
        >
          <div className="rpe-scale" role="radiogroup" aria-label={en ? "Perceived exertion (RPE)" : "自覺強度 RPE"}>
            {Array.from({ length: 10 }, (_, i) => i + 1).map((value) => (
              <button
                key={value}
                type="button"
                role="radio"
                aria-checked={overallRpe === value}
                className="rpe-step"
                data-selected={overallRpe === value}
                onClick={() => setOverallRpe(value)}
              >
                {value}
              </button>
            ))}
          </div>
          <p className="field-hint" style={{ marginTop: 8 }}>
            {overallRpe} — {rpeDescription(overallRpe)}
          </p>
        </Card>

        <div className="row" style={{ gap: 10 }}>
          <Button variant="primary" size="lg" disabled={saving} onClick={() => void saveFinishedRun()}>
            {saving ? (en ? "Saving…" : "儲存中…") : (en ? "Save this run" : "儲存這次訓練")}
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              setFinished(null);
              run.reset();
              setAutoHrSamples([]);
            }}
          >
            {en ? "Discard, don't save" : "捨棄，不儲存"}
          </Button>
        </div>
      </>
    );
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">{en ? "Run Now!" : "出發開跑！"}</h1>
          <p className="page-desc">
            {run.mode === "auto"
              ? en
                ? "Live telemetry: dynamic pace, distance, cadence, and heart rate zones."
                : "即時動態追蹤：動態配速、距離、步頻與心率區間。"
              : en
                ? "Manual mode: duration timed automatically; update distance and heart rate manually."
                : "手動模式：時長自動計時，手動調整里程與心率。"}
          </p>
        </div>
        <Badge tone={run.phase === "running" ? "good" : "neutral"} dot>
          {run.phase === "idle" && (en ? "Ready" : "準備出發")}
          {run.phase === "running" && (en ? "Running" : "跑步中")}
          {run.phase === "paused" && (en ? "Paused" : "已暫停")}
        </Badge>
      </div>

      {run.phase === "idle" && (
        <Card title={en ? "Mode" : "模式"} subtitle={en ? "Can still be switched after starting" : "開始後仍可以切換"}>
          <SwitchRow
            title={en ? "Auto-estimate distance, cadence & heart rate" : "自動推算距離、步頻與心率"}
            description={
              en
                ? "Distance, cadence, and heart rate increase automatically based on your target pace. Turn off for manual input."
                : "依你設定的目標配速，隨時間自動計算距離、步頻與動態心率。關閉則改為手動輸入。"
            }
            checked={run.mode === "auto"}
            onChange={(next) => run.setMode(next ? "auto" : "manual")}
          />
        </Card>
      )}

      {/* Main Dynamic Monitor Display */}
      <div className="live-monitor-hero">
        <div className={`live-status-pill ${run.phase === "running" ? "running" : ""}`}>
          {run.phase === "running" && <span className="pulse-dot" />}
          <span>
            {run.phase === "idle" && (en ? "LACE UP & GO" : "穿好跑鞋，隨時出發")}
            {run.phase === "running" && (en ? "RUNNING · PACE ON TARGET" : "跑步進行時 · 配速穩定")}
            {run.phase === "paused" && (en ? "PAUSED · CATCH YOUR BREATH" : "暫停中 · 調節呼吸")}
          </span>
        </div>
        <div className="live-hero-timer">{formatDuration(run.elapsedSec)}</div>
        <span className="stat-label" style={{ marginTop: 4 }}>
          {en ? "ELAPSED TIME" : "經過時間"}
        </span>
      </div>

      {/* Primary Metrics HUD */}
      <div className="grid-3">
        <Card>
          <StatTile
            label={en ? "Distance" : "距離"}
            value={formatNumber(run.distanceKm, 2)}
            unit="km"
            foot={
              run.mode === "manual" ? (
                <div className="row" style={{ gap: 6, marginTop: 6 }}>
                  <Button size="sm" variant="secondary" onClick={() => run.addDistance(-0.1)}>
                    −0.1
                  </Button>
                  <Button size="sm" variant="secondary" onClick={() => run.addDistance(0.1)}>
                    +0.1
                  </Button>
                </div>
              ) : (
                <span className="field-hint">{en ? `Lap Progress: ${currentLapProgress} km` : `本公里進度: ${currentLapProgress} km`}</span>
              )
            }
          />
        </Card>
        <Card>
          <StatTile
            label={en ? "Current Pace" : "即時配速"}
            value={paceSecPerKm ? formatPace(paceSecPerKm) : "—"}
            foot={run.mode === "auto" ? (en ? "From target pace" : "依設定目標配速") : undefined}
          />
        </Card>
        <Card>
          <StatTile
            label={en ? "Heart rate" : "即時心率"}
            value={run.currentHrBpm ?? "—"}
            unit={run.currentHrBpm ? "bpm" : undefined}
            foot={
              <div>
                <div className="hr-zone-container">
                  <div className="hr-zone-bars">
                    {[1, 2, 3, 4, 5].map((z) => (
                      <div
                        key={z}
                        className={`hr-zone-bar ${run.hrZone.zone >= z ? "active" : ""}`}
                        title={`Zone ${z}`}
                      />
                    ))}
                  </div>
                  <div className="hr-zone-label">
                    <span>{run.hrZone.label}</span>
                  </div>
                </div>
                {hrSparkline.length > 1 && (
                  <div style={{ marginTop: 6 }}>
                    <Sparkline values={hrSparkline} />
                  </div>
                )}
              </div>
            }
          />
        </Card>
      </div>

      {/* Secondary Metrics Ribbon */}
      <div className="live-secondary-grid">
        <div className="live-secondary-tile">
          <span className="live-secondary-label">
            <Icon name="runner" size={14} />
            {t("cadence")}
          </span>
          <span className="live-secondary-value">
            {run.cadenceSpm ? `${run.cadenceSpm} ` : "—"}
            <span style={{ fontSize: 12, fontWeight: 500, color: "var(--text-muted)" }}>spm</span>
          </span>
        </div>
        <div className="live-secondary-tile">
          <span className="live-secondary-label">
            <Icon name="trend" size={14} />
            {t("calories")}
          </span>
          <span className="live-secondary-value">
            {run.caloriesKcal}{" "}
            <span style={{ fontSize: 12, fontWeight: 500, color: "var(--text-muted)" }}>kcal</span>
          </span>
        </div>
        <div className="live-secondary-tile">
          <span className="live-secondary-label">
            <Icon name="history" size={14} />
            {en ? "Completed Laps" : "完成公里數"}
          </span>
          <span className="live-secondary-value">
            {run.splits.length}{" "}
            <span style={{ fontSize: 12, fontWeight: 500, color: "var(--text-muted)" }}>km</span>
          </span>
        </div>
      </div>

      {/* Live Splits List if completed >= 1km */}
      {run.splits.length > 0 && (
        <Card title={t("splits")}>
          <div className="table-scroll">
            <table className="splits-table">
              <thead>
                <tr>
                  <th>{en ? "Lap" : "分段"}</th>
                  <th>{t("splitsPace")}</th>
                  <th>{t("splitsDuration")}</th>
                </tr>
              </thead>
              <tbody>
                {run.splits.map((s) => (
                  <tr key={s.km}>
                    <td><strong>{s.km} km</strong></td>
                    <td>{formatPace(s.paceSecPerKm)}</td>
                    <td>{formatDuration(s.durationSec)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {/* Controls & Configuration */}
      {run.mode === "auto" ? (
        <Card
          title={en ? "Target pace" : "目標配速"}
          subtitle={en ? "Distance, cadence and heart rate are computed dynamically from this pace" : "距離、步頻與心率都依這個配速即時計算"}
        >
          <div className="row" style={{ gap: 8 }}>
            <input
              className="input"
              style={{ maxWidth: 120 }}
              inputMode="numeric"
              placeholder="5:30"
              value={paceText}
              onChange={(e) => setPaceText(e.target.value)}
              onBlur={applyPace}
              onKeyDown={(e) => e.key === "Enter" && applyPace()}
            />
            <span className="field-hint">{en ? "min:sec / km" : "分:秒 / km"}</span>
          </div>
        </Card>
      ) : (
        <Card title={en ? "Update heart rate" : "更新心率"} subtitle={en ? "Optional — enter what you're feeling right now" : "手動輸入你當下感受到的心率，選填"}>
          <div className="row" style={{ gap: 8 }}>
            <input
              className="input"
              style={{ maxWidth: 140 }}
              type="number"
              inputMode="numeric"
              min={30}
              max={260}
              placeholder={en ? "e.g. 158" : "例如 158"}
              value={heartRateInput}
              onChange={(e) => setHeartRateInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && logHeartRate()}
            />
            <Button icon="heart" onClick={logHeartRate} disabled={!heartRateInput}>
              {en ? "Log heart rate" : "記錄心率"}
            </Button>
          </div>
        </Card>
      )}

      <div className="stack" style={{ marginTop: 16 }}>
        {run.phase === "idle" && (
          <Button variant="primary" size="lg" icon="runner" onClick={run.start}>
            {en ? "Start monitoring" : "開始監控"}
          </Button>
        )}
        {run.phase === "running" && (
          <div className="grid-2">
            <Button size="lg" onClick={run.pause}>
              {en ? "Pause" : "暫停"}
            </Button>
            <Button variant="danger" size="lg" onClick={() => setEndConfirmationOpen(true)}>
              {en ? "End run" : "結束跑步"}
            </Button>
          </div>
        )}
        {run.phase === "paused" && (
          <div className="grid-2">
            <Button variant="primary" size="lg" onClick={run.resume}>
              {en ? "Resume" : "繼續"}
            </Button>
            <Button variant="danger" size="lg" onClick={() => setEndConfirmationOpen(true)}>
              {en ? "End run" : "結束跑步"}
            </Button>
          </div>
        )}
      </div>

      {!online && (
        <Notice tone="warning" icon="wifi-off">
          {en
            ? "You're offline. Once you finish, the run will still save locally and sync automatically after reconnecting."
            : "目前是離線模式。結束後儲存的訓練一樣會先寫入本機，恢復連線後自動同步。"}
        </Notice>
      )}

      <Modal
        open={endConfirmationOpen}
        title={en ? "End this run?" : "要結束這次跑步嗎？"}
        description={
          en
            ? "The timer will stop and you can review the summary before saving."
            : "計時會停止，接著可以先檢查摘要，再決定是否儲存。"
        }
        onClose={() => setEndConfirmationOpen(false)}
        footer={
          <>
            <Button onClick={() => setEndConfirmationOpen(false)}>
              {en ? "Keep running" : "繼續跑步"}
            </Button>
            <Button variant="danger" onClick={finishRun}>
              {en ? "End and review" : "結束並查看摘要"}
            </Button>
          </>
        }
      >
        <Notice tone="neutral" icon="activity">
          {en ? `Current duration: ${formatDuration(run.elapsedSec)}` : `目前時長：${formatDuration(run.elapsedSec)}`}
        </Notice>
      </Modal>
    </>
  );
}
