/* Real Garmin lap table + the "AI 分析" flow for one activity.
 *
 * Flow: open -> the backend's proposed segmentation (which stretches were
 * reps, which were recoveries) is shown for the athlete to confirm or
 * correct -> only then is the session analysed. The judgement the whole
 * analysis rests on is never silently assumed. Every number shown here
 * comes from backend/app/workout_analysis.py; the write-up is either the
 * language model narrating those numbers (checked server-side to contain
 * no number that is not in the data) or, when the model is unavailable,
 * the same findings in a fixed template, labelled 離線分析. */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Badge, Button, Card, Modal, Notice, Segmented } from "./ui.tsx";
import type { Tone } from "./ui.tsx";
import { Icon } from "./Icon.tsx";
import { MarkdownMessage } from "./MarkdownMessage.tsx";
import { PrescriptionCard } from "./workoutPrescription.tsx";
import {
  ApiError,
  analyseWorkout,
  getWorkoutDetection,
  previewWorkoutSegments,
  updateHeartRateSettings,
} from "../data/apiClient.ts";
import type {
  ActivityTelemetryWire,
  SegmentRole,
  SegmentStatsWire,
  WorkoutAnalysisWire,
  WorkoutDetectionWire,
  WorkoutFindingWire,
  WorkoutSegmentWire,
  WorkoutSessionType,
} from "../data/apiClient.ts";

type Locale = "zh-TW" | "en";

/* ---------------- formatting ---------------- */

function paceText(secPerKm: number | null | undefined): string {
  if (!secPerKm || secPerKm <= 0 || secPerKm > 3600) return "—";
  const total = Math.round(secPerKm);
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

function clockText(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}

const ROLE_LABEL: Record<SegmentRole, { "zh-TW": string; en: string }> = {
  warmup: { "zh-TW": "暖身", en: "Warm-up" },
  work: { "zh-TW": "強度", en: "Work" },
  rest: { "zh-TW": "休息", en: "Recovery" },
  set_rest: { "zh-TW": "組間休息", en: "Set rest" },
  strides: { "zh-TW": "加速跑", en: "Strides" },
  cooldown: { "zh-TW": "收操", en: "Cool-down" },
  steady: { "zh-TW": "連續跑", en: "Steady" },
};

const ROLE_TONE: Record<SegmentRole, Tone> = {
  warmup: "neutral",
  work: "accent",
  rest: "good",
  set_rest: "good",
  strides: "warning",
  cooldown: "neutral",
  steady: "neutral",
};

const SESSION_LABEL: Record<WorkoutSessionType, { "zh-TW": string; en: string }> = {
  intervals: { "zh-TW": "間歇", en: "Intervals" },
  tempo: { "zh-TW": "節奏跑", en: "Tempo" },
  easy: { "zh-TW": "輕鬆跑", en: "Easy" },
  long: { "zh-TW": "長距離", en: "Long run" },
  race: { "zh-TW": "比賽", en: "Race" },
  other: { "zh-TW": "其他", en: "Other" },
};

const REST_TYPE_LABEL = { standing: "站著／暫停", walking: "走路", jogging: "慢跑" } as const;

const SEVERITY: Record<WorkoutFindingWire["severity"], { tone: Tone; icon: "alert" | "check" | "info"; label: string }> = {
  critical: { tone: "critical", icon: "alert", label: "需注意" },
  warning: { tone: "warning", icon: "alert", label: "待改進" },
  positive: { tone: "good", icon: "check", label: "做得好" },
  info: { tone: "neutral", icon: "info", label: "觀察" },
};

const HR_SOURCE_LABEL: Record<string, string> = {
  manual: "你的手動設定",
  device: "Garmin 手錶當天設定",
  history: "歷史紀錄推算",
  age_formula: "年齡公式估算",
};

const TRIGGER_LABEL: Record<string, string> = {
  manual: "手動",
  distance: "自動距離",
  time: "自動時間",
  session_end: "結束",
  position_start: "位置",
  position_lap: "位置",
};

/* ---------------- real lap table ---------------- */

export function RealLapTable({ telemetry, locale }: { telemetry: ActivityTelemetryWire; locale: Locale }) {
  const en = locale === "en";
  const deviceLabel = telemetry.sub_sport === "track" ? (en ? "track mode" : "操場模式")
    : telemetry.sub_sport === "treadmill" ? (en ? "treadmill" : "跑步機") : "GPS";
  return (
    <Card
      title={telemetry.source === "simulated"
        ? (en ? "Lap splits (simulated)" : "分圈紀錄（模擬資料）")
        : (en ? "Lap splits (recorded)" : "分圈紀錄（Garmin 實測）")}
      subtitle={
        en
          ? `${telemetry.laps.length} laps from the watch · ${deviceLabel} · role per lap from ${telemetry.roles_from === "analysis" ? "your confirmed analysis" : "automatic detection"}`
          : `手錶原始 ${telemetry.laps.length} 圈 · ${deviceLabel} · 每圈判讀來自${telemetry.roles_from === "analysis" ? "你確認過的分析" : "系統自動判讀"}`
      }
      flush
    >
      <div className="table-scroll">
        <table className="splits-table">
          <thead>
            <tr>
              <th>{en ? "Lap" : "圈"}</th>
              <th>{en ? "Read as" : "判讀"}</th>
              <th>{en ? "Distance" : "距離"}</th>
              <th>{en ? "Time" : "時間"}</th>
              <th>{en ? "Pace /km" : "配速 /km"}</th>
              <th>{en ? "Avg HR" : "平均心率"}</th>
              <th>{en ? "Max HR" : "最高心率"}</th>
              <th>{en ? "Cadence" : "步頻"}</th>
              <th>{en ? "Lap by" : "分圈方式"}</th>
            </tr>
          </thead>
          <tbody>
            {telemetry.laps.map((lap) => (
              <tr key={lap.lap_number} className={lap.role === "work" ? "lap-row-work" : undefined}>
                <td><strong>{lap.lap_number}</strong></td>
                <td>{lap.role ? <Badge tone={ROLE_TONE[lap.role]}>{ROLE_LABEL[lap.role][locale]}</Badge> : "—"}</td>
                <td>{lap.distance_m !== null ? `${Math.round(lap.distance_m)} m` : "—"}</td>
                <td>{clockText(lap.timer_s)}</td>
                <td>{paceText(lap.pace_s_per_km)}</td>
                <td>{lap.avg_hr ? `${lap.avg_hr} bpm` : "—"}</td>
                <td>{lap.max_hr ? `${lap.max_hr} bpm` : "—"}</td>
                <td>{lap.avg_cadence ? `${lap.avg_cadence} spm` : "—"}</td>
                <td className="field-hint">{lap.trigger ? (TRIGGER_LABEL[lap.trigger] ?? lap.trigger) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}

/* ---------------- segment editing ---------------- */

function mergeSegments(segs: WorkoutSegmentWire[], i: number): WorkoutSegmentWire[] {
  /* Merge segment i with segment i+1. A recovery swallowed by a rep becomes
   * that rep's in-rep stop (it is excluded from the rep's time and pace). */
  if (i < 0 || i + 1 >= segs.length) return segs;
  const a = segs[i];
  const b = segs[i + 1];
  const isWork = a.role === "work" || b.role === "work";
  const interruptions = [...(a.interruptions ?? []), ...(b.interruptions ?? [])];
  if (isWork) {
    for (const part of [a, b]) {
      if (part.role !== "work") interruptions.push([part.start_s, part.end_s]);
    }
  }
  const merged: WorkoutSegmentWire = {
    role: isWork ? "work" : a.role,
    start_s: a.start_s,
    end_s: b.end_s,
    ...(interruptions.length && isWork ? { interruptions: interruptions.sort((x, y) => x[0] - y[0]) } : {}),
  };
  return [...segs.slice(0, i), merged, ...segs.slice(i + 2)];
}

function workIndexToSegmentIndex(segs: WorkoutSegmentWire[], workIndex: number): number {
  let count = -1;
  for (let i = 0; i < segs.length; i++) {
    if (segs[i].role === "work") count++;
    if (count === workIndex) return i;
  }
  return -1;
}

function confidenceTone(c: number): Tone {
  return c >= 0.85 ? "good" : c >= 0.6 ? "warning" : "critical";
}

function confidenceText(c: number): string {
  return c >= 0.85 ? "高" : c >= 0.6 ? "中" : "低";
}

/* ---------------- modal ---------------- */

type Step = "loading" | "confirm" | "analysing" | "result" | "error";

export function WorkoutAnalysisModal({
  open,
  onClose,
  activityId,
  accessToken,
  locale,
  onAnalysed,
}: {
  open: boolean;
  onClose: () => void;
  activityId: string;
  accessToken: string;
  locale: Locale;
  onAnalysed?: () => void;
}) {
  const [step, setStep] = useState<Step>("loading");
  const [error, setError] = useState<string | null>(null);
  const [detection, setDetection] = useState<WorkoutDetectionWire | null>(null);
  const [segments, setSegments] = useState<WorkoutSegmentWire[]>([]);
  const [preview, setPreview] = useState<SegmentStatsWire[]>([]);
  const [signatureText, setSignatureText] = useState<string | null>(null);
  const [sessionType, setSessionType] = useState<WorkoutSessionType>("intervals");
  const [edited, setEdited] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [result, setResult] = useState<WorkoutAnalysisWire | null>(null);
  const previewSeq = useRef(0);

  const load = useCallback(async (stayOnConfirm = false) => {
    setStep("loading");
    setError(null);
    try {
      const d = await getWorkoutDetection(accessToken, activityId);
      setDetection(d);
      setSegments(d.detection.segments);
      setPreview(d.segments_preview);
      setSignatureText(d.detection.signature);
      setSessionType(d.saved_analysis?.session_type ?? d.suggested_session_type);
      setEdited(false);
      if (d.saved_analysis && !stayOnConfirm) {
        setResult(d.saved_analysis);
        setStep("result");
      } else {
        setStep("confirm");
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "無法讀取這筆紀錄的分段資料");
      setStep("error");
    }
  }, [accessToken, activityId]);

  useEffect(() => {
    if (open) void load();
  }, [open, load]);

  // live numbers for an edited segmentation
  useEffect(() => {
    if (!edited || segments.length === 0) return;
    const seq = ++previewSeq.current;
    const handle = window.setTimeout(async () => {
      try {
        const res = await previewWorkoutSegments(accessToken, activityId, segments);
        if (seq !== previewSeq.current) return;
        setPreview(res.segments_preview);
        setSignatureText(res.signature);
        setPreviewError(null);
      } catch (e) {
        if (seq === previewSeq.current) setPreviewError(e instanceof ApiError ? e.message : "無法更新分段數據");
      }
    }, 250);
    return () => window.clearTimeout(handle);
  }, [segments, edited, accessToken, activityId]);

  const edit = (next: WorkoutSegmentWire[]) => {
    setSegments(next);
    setEdited(true);
  };

  const runAnalysis = async () => {
    setStep("analysing");
    try {
      const res = await analyseWorkout(accessToken, activityId, {
        segments,
        session_type: sessionType,
        target_pace_s_per_km: null,
      });
      setResult(res);
      setStep("result");
      onAnalysed?.();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "分析失敗，請稍後再試");
      setStep("error");
    }
  };

  const title = step === "result" ? "課表分析" : "確認今天的課表分段";

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={title}
      size="xl"
      description={
        step === "confirm"
          ? "系統先依每秒的配速、你按的分圈與手錶暫停點，判讀哪些是強度、哪些是組間休息。請確認或修正後再分析。"
          : undefined
      }
      footer={
        step === "confirm" ? (
          <>
            <Button onClick={onClose}>取消</Button>
            <Button variant="primary" icon="check" onClick={() => void runAnalysis()} disabled={segments.length === 0}>
              確認分段並分析
            </Button>
          </>
        ) : step === "result" ? (
          <>
            <Button icon="refresh" onClick={() => setStep("confirm")}>重新確認分段</Button>
            <Button variant="primary" onClick={onClose}>完成</Button>
          </>
        ) : step === "error" ? (
          <>
            <Button onClick={onClose}>關閉</Button>
            <Button variant="primary" icon="refresh" onClick={() => void load()}>重試</Button>
          </>
        ) : undefined
      }
    >
      {step === "loading" && <LoadingBlock text="讀取每秒紀錄並判讀課表結構…" />}
      {step === "analysing" && <LoadingBlock text="計算每趟配速、心率與恢復，教練撰寫分析中…" />}
      {step === "error" && (
        <Notice tone="critical" icon="alert" title="無法完成">
          {error}
        </Notice>
      )}
      {step === "confirm" && detection && (
        <ConfirmStep
          detection={detection}
          segments={segments}
          preview={preview}
          signatureText={signatureText}
          sessionType={sessionType}
          setSessionType={setSessionType}
          previewError={previewError}
          edited={edited}
          onEdit={edit}
          onReset={() => {
            setSegments(detection.detection.segments);
            setPreview(detection.segments_preview);
            setSignatureText(detection.detection.signature);
            setEdited(false);
            setPreviewError(null);
          }}
          accessToken={accessToken}
          onHrSaved={() => void load(true)}
          onPrescriptionChanged={() => void load(true)}
          activityId={activityId}
          locale={locale}
        />
      )}
      {step === "result" && result && <ResultStep result={result} locale={locale} />}
    </Modal>
  );
}

function LoadingBlock({ text }: { text: string }) {
  return (
    <div className="analysis-loading">
      <span className="analysis-spinner" aria-hidden />
      <span>{text}</span>
    </div>
  );
}

/* ---------------- confirm step ---------------- */

const NOMINAL_CHOICES = [100, 150, 200, 300, 400, 500, 600, 800, 1000, 1200, 1500, 1600, 2000, 3000, 5000];

function ConfirmStep({
  detection,
  segments,
  preview,
  signatureText,
  sessionType,
  setSessionType,
  previewError,
  edited,
  onEdit,
  onReset,
  accessToken,
  onHrSaved,
  onPrescriptionChanged,
  activityId,
  locale,
}: {
  detection: WorkoutDetectionWire;
  segments: WorkoutSegmentWire[];
  preview: SegmentStatsWire[];
  signatureText: string | null;
  sessionType: WorkoutSessionType;
  setSessionType: (t: WorkoutSessionType) => void;
  previewError: string | null;
  edited: boolean;
  onEdit: (segs: WorkoutSegmentWire[]) => void;
  onReset: () => void;
  accessToken: string;
  onHrSaved: () => void;
  onPrescriptionChanged: () => void;
  activityId: string;
  locale: Locale;
}) {
  const d = detection.detection;
  const workCount = segments.filter((s) => s.role === "work").length;
  let repNo = 0;
  return (
    <div className="stack">
      <div className="analysis-detect-banner">
        <div className="row" style={{ gap: 10, flexWrap: "wrap", alignItems: "center" }}>
          <Icon name="runner" size={20} />
          <strong style={{ fontSize: 16 }}>
            {signatureText && signatureText !== "continuous" ? signatureText.replace(/x/g, " × ") : "連續跑（無強度／休息交替）"}
          </strong>
          {!edited && (
            <Badge tone={confidenceTone(d.confidence)}>
              判讀信心 {confidenceText(d.confidence)}（{Math.round(d.confidence * 100)}%）
            </Badge>
          )}
          {edited && <Badge tone="accent">已手動修正</Badge>}
        </div>
        {!edited && d.reasons.length > 0 && (
          <ul className="analysis-reasons">
            {d.reasons.map((r) => <li key={r}>{r}</li>)}
          </ul>
        )}
        {!edited && d.hints.map((h) => {
          const idx = workIndexToSegmentIndex(segments, h.work_index);
          return (
            <div key={`${h.type}-${h.work_index}`} className="row" style={{ gap: 8, marginTop: 6, flexWrap: "wrap" }}>
              <span className="field-hint">第 {h.work_index + 1}、{h.work_index + 2} 趟加起來正好 {h.total_m}m，可能是同一趟中途停下。</span>
              <Button
                size="sm"
                onClick={() => {
                  if (idx < 0) return;
                  let next = mergeSegments(segments, idx); // rep + recovery
                  next = mergeSegments(next, idx); // + next rep
                  next[idx] = { ...next[idx], nominal_m: h.total_m };
                  onEdit(next);
                }}
              >
                合併成一趟 {h.total_m}m
              </Button>
            </div>
          );
        })}
      </div>

      <div className="grid-2" style={{ gap: 14 }}>
        <div>
          <div className="field-label" style={{ marginBottom: 6 }}>課表類型</div>
          <Segmented
            value={sessionType}
            onChange={setSessionType}
            options={(Object.keys(SESSION_LABEL) as WorkoutSessionType[]).map((k) => ({ value: k, label: SESSION_LABEL[k][locale] }))}
          />
        </div>
      </div>
      {(sessionType === "intervals" || sessionType === "tempo" || sessionType === "race") && (
        <PrescriptionCard
          activityId={activityId}
          accessToken={accessToken}
          prescription={detection.prescription}
          activityName={detection.activity_name}
          linked={detection.linked}
          onChanged={onPrescriptionChanged}
          compact
        />
      )}

      {previewError && <Notice tone="warning" icon="alert">{previewError}</Notice>}

      <div className="table-scroll">
        <table className="splits-table analysis-seg-table">
          <thead>
            <tr>
              <th>#</th>
              <th>判讀</th>
              <th>時間點</th>
              <th>標準距離</th>
              <th>GPS 距離</th>
              <th>時間</th>
              <th>配速 /km</th>
              <th>平均心率</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {segments.map((seg, i) => {
              const st = preview[i];
              const isWork = seg.role === "work";
              if (isWork) repNo++;
              return (
                <tr key={`${seg.start_s}-${seg.end_s}-${i}`} className={isWork ? "lap-row-work" : undefined}>
                  <td className="field-hint">{isWork ? `第 ${repNo} 趟` : ""}</td>
                  <td>
                    <select
                      className="input input-sm"
                      value={seg.role}
                      onChange={(e) => {
                        const role = e.target.value as SegmentRole;
                        const next = segments.map((s, k) => {
                          if (k !== i) return s;
                          const { nominal_m: _m, nominal_s: _s, interruptions: _int, ...rest } = s;
                          return role === "work" ? { ...s, role } : { ...rest, role };
                        });
                        onEdit(next);
                      }}
                    >
                      {(Object.keys(ROLE_LABEL) as SegmentRole[]).map((r) => (
                        <option key={r} value={r}>{ROLE_LABEL[r][locale]}</option>
                      ))}
                    </select>
                  </td>
                  <td className="field-hint">{clockText(seg.start_s)}–{clockText(seg.end_s)}</td>
                  <td>
                    {isWork && !seg.nominal_s ? (
                      <select
                        className="input input-sm"
                        value={seg.nominal_m ?? ""}
                        onChange={(e) => {
                          const v = e.target.value ? Number(e.target.value) : null;
                          onEdit(segments.map((s, k) => (k === i ? { ...s, nominal_m: v } : s)));
                        }}
                      >
                        <option value="">依 GPS</option>
                        {[...new Set([...(seg.nominal_m ? [seg.nominal_m] : []), ...NOMINAL_CHOICES])]
                          .sort((a, b) => a - b)
                          .map((m) => <option key={m} value={m}>{m} m</option>)}
                      </select>
                    ) : isWork && seg.nominal_s ? (
                      <span>{seg.nominal_s} 秒</span>
                    ) : (
                      <span className="field-hint">—</span>
                    )}
                  </td>
                  <td>{st ? `${Math.round(st.gps_distance_m)} m` : "…"}</td>
                  <td>
                    {st ? clockText(isWork ? st.moving_s : st.elapsed_s) : "…"}
                    {st && st.interruptions_s > 0 && <div className="field-hint">含中途停 {st.interruptions_s} 秒（已扣除）</div>}
                  </td>
                  <td>{st && (isWork || seg.role === "warmup" || seg.role === "cooldown" || seg.role === "steady") ? paceText(st.pace_s_per_km) : st?.rest_type ? REST_TYPE_LABEL[st.rest_type] : "—"}</td>
                  <td>{st?.avg_hr ? `${st.avg_hr}` : "—"}</td>
                  <td>
                    {i + 1 < segments.length && (
                      <Button size="sm" variant="ghost" title="與下一段合併" onClick={() => onEdit(mergeSegments(segments, i))}>
                        合併↓
                      </Button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="row-between" style={{ flexWrap: "wrap", gap: 8 }}>
        <span className="field-hint">
          共 {workCount} 段強度。配速以「標準距離」計算（操場上 GPS 彎道常偏長 1–5%）；中途停下的時間不計入該趟。
        </span>
        {edited && <Button size="sm" variant="ghost" icon="refresh" onClick={onReset}>還原系統判讀</Button>}
      </div>

      <HrSettingsLine detection={detection} accessToken={accessToken} onSaved={onHrSaved} />
    </div>
  );
}

function HrSettingsLine({
  detection,
  accessToken,
  onSaved,
}: {
  detection: WorkoutDetectionWire;
  accessToken: string;
  onSaved: () => void;
}) {
  const hr = detection.hr_profile;
  const [editing, setEditing] = useState(false);
  const [maxHr, setMaxHr] = useState(detection.hr_manual.max_hr_bpm?.toString() ?? "");
  const [restHr, setRestHr] = useState(detection.hr_manual.resting_hr_bpm?.toString() ?? "");
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const save = async (clear: boolean) => {
    setSaving(true);
    setErr(null);
    try {
      await updateHeartRateSettings(accessToken, {
        max_hr_bpm: clear || !maxHr ? null : Number(maxHr),
        resting_hr_bpm: clear || !restHr ? null : Number(restHr),
        birth_year: detection.hr_manual.birth_year,
      });
      setEditing(false);
      onSaved();
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "儲存失敗");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="analysis-hr-line">
      <Icon name="heart" size={16} />
      {hr.max_hr ? (
        <span>
          最大心率 <strong>{hr.max_hr}</strong> bpm（{HR_SOURCE_LABEL[hr.max_hr_source ?? ""] ?? "—"}）
          {hr.resting_hr ? <> · 安靜心率 <strong>{hr.resting_hr}</strong> bpm</> : null}
          {" · "}區間：{hr.zone_method === "percent_hrr" ? "儲備心率法" : "最大心率百分比"}
          {hr.history_peak_30s ? <span className="field-hint">（歷史 30 秒最高 {hr.history_peak_30s} bpm）</span> : null}
        </span>
      ) : (
        <span>尚未有最大心率設定</span>
      )}
      {!editing && <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>修改</Button>}
      {editing && (
        <div className="row" style={{ gap: 8, flexWrap: "wrap", width: "100%", marginTop: 8 }}>
          <input className="input input-sm" style={{ width: 110 }} inputMode="numeric" placeholder="最大心率" value={maxHr} onChange={(e) => setMaxHr(e.target.value.replace(/\D/g, ""))} />
          <input className="input input-sm" style={{ width: 110 }} inputMode="numeric" placeholder="安靜心率" value={restHr} onChange={(e) => setRestHr(e.target.value.replace(/\D/g, ""))} />
          <Button size="sm" variant="primary" disabled={saving} onClick={() => void save(false)}>儲存</Button>
          <Button size="sm" disabled={saving} onClick={() => void save(true)}>改回手錶設定</Button>
          <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>取消</Button>
          <span className="field-hint" style={{ width: "100%" }}>
            優先順序：你的手動設定 → Garmin 手錶當天設定 → 歷史紀錄推算 → 年齡公式（Tanaka）。
          </span>
          {err && <span className="field-error">{err}</span>}
        </div>
      )}
      {hr.notes.map((n) => <div key={n} className="field-hint" style={{ width: "100%" }}>{n}</div>)}
    </div>
  );
}

/* ---------------- result step ---------------- */

function ResultStep({ result, locale }: { result: WorkoutAnalysisWire; locale: Locale }) {
  const s = result.summary;
  const stats = result.segment_stats;
  const reps = stats.filter((x) => x.role === "work");
  const byIndex = new Map(stats.map((x) => [x.index, x]));
  const hr = s.hr_profile;
  const num = (k: string) => (typeof s[k] === "number" ? (s[k] as number) : null);

  const tiles: { label: string; value: string; hint?: string }[] = [];
  if (reps.length) {
    tiles.push({ label: "各趟平均配速", value: `${paceText(num("mean_work_pace_s_per_km"))} /km`, hint: `${reps.length} 趟 · ${(num("work_distance_m") ?? 0) / 1000} km` });
    if (num("block_cv_pct") !== null) tiles.push({ label: "配速變異係數", value: `${num("block_cv_pct")}%`, hint: "≤1% 極穩定 · ≤2% 穩定" });
    if (num("block_spread_per_rep_s") !== null) tiles.push({ label: "每趟時間最大差距", value: `${num("block_spread_per_rep_s")} 秒` });
    if (num("rest_mean_s") !== null) tiles.push({ label: "平均休息", value: clockText(num("rest_mean_s")) });
  } else if (num("split_mean_pace_s_per_km") !== null) {
    tiles.push({ label: "平均配速", value: `${paceText(num("split_mean_pace_s_per_km"))} /km` });
    if (num("split_cv_pct") !== null) tiles.push({ label: "每公里配速變異", value: `${num("split_cv_pct")}%` });
    if (num("aerobic_decoupling_pct") !== null) tiles.push({ label: "心率脫鉤 Pa:HR", value: `${num("aerobic_decoupling_pct")}%`, hint: "< 5% 有氧耐力穩定" });
  }
  if (num("peak_rep_hr") !== null) tiles.push({ label: "趟中最高心率", value: `${num("peak_rep_hr")} bpm`, hint: num("peak_rep_hr_pct_max") ? `最大心率的 ${num("peak_rep_hr_pct_max")}%` : undefined });
  else if (s.max_hr) tiles.push({ label: "最高心率", value: `${s.max_hr} bpm` });

  return (
    <div className="stack">
      <div className="analysis-result-head">
        <div>
          <div className="field-hint">{SESSION_LABEL[result.session_type][locale]}</div>
          <div style={{ fontSize: 20, fontWeight: 750 }}>{result.signature_label}</div>
        </div>
      </div>

      {(() => {
        const p = s.prescription as { title?: string; source_label?: string; gradable?: boolean } | undefined;
        return p?.title ? (
          <div className="prescription-result-line">
            <Icon name="assignment" size={16} />
            <span>課表要求：<strong>{p.title}</strong></span>
            <Badge tone={p.gradable ? "good" : "warning"}>{p.source_label}{p.gradable ? "" : "（不評分）"}</Badge>
          </div>
        ) : null;
      })()}
      <div className="analysis-tiles">
        {tiles.map((t) => (
          <div key={t.label} className="analysis-tile">
            <div className="field-hint">{t.label}</div>
            <div className="tnum analysis-tile-value">{t.value}</div>
            {t.hint && <div className="field-hint" style={{ fontSize: 11 }}>{t.hint}</div>}
          </div>
        ))}
      </div>

      {reps.length >= 2 && <RepChart reps={reps} target={result.target_pace_s_per_km} />}

      {reps.length > 0 && (
        <div className="table-scroll">
          <table className="splits-table">
            <thead>
              <tr>
                <th>趟</th>
                <th>距離</th>
                <th>時間</th>
                <th>配速 /km</th>
                <th>要求</th>
                <th>與要求差距</th>
                <th>平均 / 結束心率</th>
                <th>前半 / 後半</th>
                <th>之後休息</th>
                <th>休息心率下降</th>
              </tr>
            </thead>
            <tbody>
              {reps.map((r) => {
                const rest = byIndex.get(r.index + 1);
                const isRest = rest && (rest.role === "rest" || rest.role === "set_rest");
                return (
                  <tr key={r.index}>
                    <td><strong>{r.rep_number}</strong></td>
                    <td>{r.nominal_m ? `${r.nominal_m} m` : r.nominal_s ? `${r.nominal_s} 秒` : `${Math.round(r.distance_m)} m`}</td>
                    <td>
                      {clockText(r.moving_s)}
                      {r.interruptions_s > 0 && <div className="field-hint">中途停 {r.interruptions_s} 秒</div>}
                    </td>
                    <td><strong>{paceText(r.pace_s_per_km)}</strong></td>
                    <td>{r.target_label ?? "—"}</td>
                    <td className={r.target_dev_pct !== undefined ? (Math.abs(r.target_dev_pct) <= 1.5 ? "dev-ok" : r.target_dev_pct < 0 ? "dev-fast" : "dev-slow") : undefined}>
                      {r.target_dev_s !== undefined && (r.nominal_m ?? 0) <= 600
                        ? `${r.target_dev_s > 0 ? "慢" : "快"} ${Math.abs(r.target_dev_s).toFixed(1)} 秒`
                        : r.target_dev_pct !== undefined
                          ? `${r.target_dev_pct > 0 ? "慢" : "快"} ${Math.abs(r.target_dev_pct).toFixed(1)}%`
                          : "—"}
                    </td>
                    <td>{r.avg_hr ?? "—"} / {r.hr_end ?? "—"}</td>
                    <td className="field-hint">
                      {r.first_half_pace && r.second_half_pace ? `${paceText(r.first_half_pace)} / ${paceText(r.second_half_pace)}` : "—"}
                    </td>
                    <td>
                      {isRest ? (
                        <>
                          {clockText(rest.elapsed_s)}
                          <div className="field-hint">
                            {rest.role === "set_rest" ? "組間 · " : ""}
                            {rest.rest_type ? REST_TYPE_LABEL[rest.rest_type] : ""}
                          </div>
                        </>
                      ) : "—"}
                    </td>
                    <td>{isRest && rest.hr_drop !== undefined ? (rest.hr_drop >= 0 ? `−${rest.hr_drop} bpm` : `↑${-rest.hr_drop} bpm`) : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <FindingsList findings={result.findings} />

      <Card title="教練講評">
        <MarkdownMessage content={result.narrative} />
      </Card>

      {(result.data_notes.length > 0 || hr.notes.length > 0) && (
        <Notice tone="neutral" icon="info" title="資料說明">
          <ul className="analysis-reasons">
            {[...result.data_notes, ...hr.notes].map((n) => <li key={n}>{n}</li>)}
          </ul>
        </Notice>
      )}
      <div className="field-hint">
        心率設定：最大 {hr.max_hr ?? "—"} bpm（{HR_SOURCE_LABEL[hr.max_hr_source ?? ""] ?? "—"}）
        {hr.resting_hr ? ` · 安靜 ${hr.resting_hr} bpm` : ""}
        {hr.zone_tops.length ? ` · 區間上限 ${hr.zone_tops.slice(0, 5).join(" / ")} bpm` : ""}
      </div>
      {/* how the write-up was produced: stated once, quietly, at the end */}
      <div className="field-hint" title={result.fallback_reason ?? undefined}>
        {result.narrative_source === "llm"
          ? `講評依上方數據撰寫，文中數字皆已對照你的紀錄（${result.narrative_model}）`
          : "講評依上方判讀結果整理"}
      </div>
    </div>
  );
}

function FindingsList({ findings }: { findings: WorkoutFindingWire[] }) {
  if (!findings.length) return null;
  return (
    <div className="analysis-findings">
      {findings.map((f, i) => {
        const sev = SEVERITY[f.severity];
        return (
          <div key={`${f.code}-${i}`} className={`analysis-finding analysis-finding-${sev.tone}`}>
            <div className="row" style={{ gap: 8, alignItems: "center" }}>
              <Icon name={sev.icon} size={16} />
              <strong>{f.title}</strong>
              <Badge tone={sev.tone}>{sev.label}</Badge>
            </div>
            <div className="analysis-finding-detail">{f.detail}</div>
            {f.advice && <div className="analysis-finding-advice">建議：{f.advice}</div>}
          </div>
        );
      })}
    </div>
  );
}

/* Rep-by-rep pace bars (taller = faster) with the set mean and, when set,
 * the target as reference lines, and rep-end heart rate as dots. */
function RepChart({ reps, target }: { reps: SegmentStatsWire[]; target: number | null }) {
  const paced = reps.filter((r) => r.pace_s_per_km);
  const geometry = useMemo(() => {
    const paces = paced.map((r) => r.pace_s_per_km as number);
    const repTargets = paced.map((r) => r.target_pace_s_per_km).filter((x): x is number => typeof x === "number");
    const all = [...paces, ...repTargets, ...(target ? [target] : [])];
    const fastest = Math.min(...all);
    const slowest = Math.max(...all);
    const pad = Math.max(3, (slowest - fastest) * 0.25);
    return { lo: fastest - pad, hi: slowest + pad, mean: paces.reduce((a, b) => a + b, 0) / paces.length };
  }, [paced, target]);
  if (paced.length < 2) return null;
  const W = 640;
  const H = 190;
  const left = 46;
  const right = 40;
  const top = 14;
  const bottom = 30;
  const plotW = W - left - right;
  const plotH = H - top - bottom;
  const slot = plotW / paced.length;
  // faster pace -> taller bar: the bar's top sits at barY(pace)
  const barY = (pace: number) => top + plotH - ((geometry.hi - pace) / (geometry.hi - geometry.lo)) * plotH;
  const hrs = paced.map((r) => r.hr_end ?? r.avg_hr).filter((x): x is number => typeof x === "number");
  const hrLo = hrs.length ? Math.min(...hrs) - 5 : 0;
  const hrHi = hrs.length ? Math.max(...hrs) + 5 : 1;
  const yHr = (h: number) => top + (1 - (h - hrLo) / (hrHi - hrLo)) * plotH;
  const hrPoints = paced
    .map((r, i) => ({ x: left + slot * i + slot / 2, h: r.hr_end ?? r.avg_hr }))
    .filter((p): p is { x: number; h: number } => typeof p.h === "number");

  return (
    <div className="analysis-chart">
      <div className="row-between" style={{ marginBottom: 4, flexWrap: "wrap", gap: 6 }}>
        <strong style={{ fontSize: 13 }}>每趟配速</strong>
        <span className="field-hint" style={{ fontSize: 11 }}>
          長條越高越快 · 虛線＝平均 {paceText(geometry.mean)}{paced.some((r) => r.target_pace_s_per_km) || target ? " · 綠線＝該趟要求" : ""} · 紅點＝每趟結束心率
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="每趟配速圖">
        {paced.map((r, i) => {
          const p = r.pace_s_per_km as number;
          const x = left + slot * i + slot * 0.18;
          const w = slot * 0.64;
          const yb = barY(p);
          return (
            <g key={r.index}>
              <rect x={x} y={yb} width={w} height={Math.max(2, top + plotH - yb)} rx={4}
                className={p <= geometry.mean ? "chart-bar-fast" : "chart-bar-slow"} />
              <text x={x + w / 2} y={yb - 4} textAnchor="middle" className="chart-label">{paceText(p)}</text>
              {r.target_pace_s_per_km && (
                <line x1={x - 3} x2={x + w + 3} y1={barY(r.target_pace_s_per_km)} y2={barY(r.target_pace_s_per_km)} className="chart-target-line" />
              )}
              <text x={x + w / 2} y={H - 10} textAnchor="middle" className="chart-axis">{r.rep_number}</text>
            </g>
          );
        })}
        <line x1={left} x2={W - right} y1={barY(geometry.mean)} y2={barY(geometry.mean)} className="chart-mean-line" />
        {target && (
          <line x1={left} x2={W - right} y1={barY(target)} y2={barY(target)} className="chart-target-line" />
        )}
        {hrPoints.length >= 2 && (
          <polyline points={hrPoints.map((pt) => `${pt.x},${yHr(pt.h)}`).join(" ")} className="chart-hr-line" />
        )}
        {hrPoints.map((pt) => (
          <g key={pt.x}>
            <circle cx={pt.x} cy={yHr(pt.h)} r={3.5} className="chart-hr-dot" />
            <text x={pt.x + 6} y={yHr(pt.h) - 5} className="chart-hr-label">{pt.h}</text>
          </g>
        ))}
        <text x={4} y={H - 10} className="chart-axis">趟</text>
      </svg>
    </div>
  );
}
