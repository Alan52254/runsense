/* Real Garmin lap table + the workout analysis flow for one activity.
 *
 * Flow: open -> the backend's proposed segmentation (which stretches were
 * reps, which were recoveries) is shown for the athlete to confirm or
 * correct -> only then is the session analysed. The judgement the whole
 * analysis rests on is never silently assumed. Every number shown here
 * comes from backend/app/workout_analysis.py; the write-up is either the
 * language model narrating those numbers (checked server-side to contain
 * no number that is not in the data) or, when the model is unavailable,
 * the same findings in a fixed template, labelled 離線分析. */

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Badge, Button, HairlineList, HairlineRow, ModuleHead, Notice, Plate, Segmented } from "./ui.tsx";
import type { Tone } from "./ui.tsx";
import { Icon } from "./Icon.tsx";
import { Figure } from "./Figure.tsx";
import { SlideOver } from "./motion.tsx";
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
import { TOLERANCE_PCT, workoutVerdict } from "../lib/workoutVerdict.ts";
import { REP_CHART, repSeries } from "../lib/repSeries.ts";
import type { RepSeries } from "../lib/repSeries.ts";
import { Surface } from "./Surface.tsx";
import { formatDurationSec } from "../lib/figureFormat.ts";
import { Text } from "./Text.tsx";
import { Cluster, Row, Stack } from "./Layout.tsx";

type Locale = "zh-TW" | "en";

/* ---------------- formatting ---------------- */

const clockText = formatDurationSec;

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

const SEVERITY: Record<WorkoutFindingWire["severity"], { label: string }> = {
  critical: { label: "需注意" },
  warning: { label: "待改進" },
  positive: { label: "做得好" },
  info: { label: "觀察" },
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
    <section className="lap-module" aria-label={en ? "Lap splits" : "分圈紀錄"}>
      <ModuleHead
        title={telemetry.source === "simulated"
          ? (en ? "Lap splits (Garmin)" : "分圈紀錄（Garmin）")
          : (en ? "Lap splits (recorded)" : "分圈紀錄（Garmin 實測）")}
      />
      <p className="lap-module-note">
        {en
          ? `${telemetry.laps.length} laps from the watch · ${deviceLabel} · role per lap from ${telemetry.roles_from === "analysis" ? "your confirmed analysis" : "automatic detection"}`
          : `手錶原始 ${telemetry.laps.length} 圈 · ${deviceLabel} · 每圈判讀來自${telemetry.roles_from === "analysis" ? "你確認過的分析" : "系統自動判讀"}`}
      </p>
      <div className="table-scroll">
        <table className="splits-table">
          <thead>
            <tr>
              <th>{en ? "Lap" : "圈"}</th>
              <th>{en ? "Read as" : "判讀"}</th>
              <th>{en ? "Distance" : "距離"}</th>
              <th>{en ? "Time" : "時間"}</th>
              <th>{en ? "Pace" : "配速"}</th>
              <th>{en ? "Avg HR" : "平均心率"}</th>
              <th>{en ? "Max HR" : "最高心率"}</th>
              <th>{en ? "Cadence" : "步頻"}</th>
              <th>{en ? "Lap by" : "分圈方式"}</th>
            </tr>
          </thead>
          <tbody>
            {telemetry.laps.map((lap) => (
              <tr key={lap.lap_number}>
                <td><strong>{lap.lap_number}</strong></td>
                <td>{lap.role ? <Badge tone={ROLE_TONE[lap.role]}>{ROLE_LABEL[lap.role][locale]}</Badge> : "—"}</td>
                <td><Figure kind="distance" meters={lap.distance_m} /></td>
                <td><Figure kind="duration" seconds={lap.timer_s} /></td>
                <td><Figure kind="pace" secPerKm={lap.pace_s_per_km} /></td>
                <td>{lap.avg_hr ? `${lap.avg_hr} bpm` : "—"}</td>
                <td>{lap.max_hr ? `${lap.max_hr} bpm` : "—"}</td>
                <td>{lap.avg_cadence ? `${lap.avg_cadence} spm` : "—"}</td>
                <td className="field-hint">{lap.trigger ? (TRIGGER_LABEL[lap.trigger] ?? lap.trigger) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
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

function AnalysisDrawer({ open, onClose, title, description, footer, children }: {
  open: boolean; onClose: () => void; title: string;
  description?: ReactNode; footer?: ReactNode; children: ReactNode;
}) {
  const titleId = useId();
  const descriptionId = useId();
  return (
    <SlideOver open={open} onClose={onClose} size="lg" className="analysis-drawer"
      labelledBy={titleId} describedBy={description ? descriptionId : undefined}>
      <header className="analysis-drawer-header">
        <div className="row-between"><h2 id={titleId}>{title}</h2>
          <Button variant="ghost" icon="x" onClick={onClose} aria-label="關閉課表分析" />
        </div>
        {description && <p id={descriptionId}>{description}</p>}
      </header>
      <div className="analysis-drawer-body">{children}</div>
      {footer && <footer className="analysis-drawer-footer">{footer}</footer>}
    </SlideOver>
  );
}

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
    <AnalysisDrawer
      open={open}
      onClose={onClose}
      title={title}
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
            <Button variant="secondary" onClick={onClose}>完成</Button>
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
    </AnalysisDrawer>
  );
}

function LoadingBlock({ text }: { text: string }) {
  return (
    <div className="analysis-loading" role="status" aria-live="polite">
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
        <Cluster gap={3}>
          <Icon name="runner" size={20} />
          <strong className="analysis-detect-title">
            {signatureText && signatureText !== "continuous" ? signatureText.replace(/x/g, " × ") : "連續跑（無強度／休息交替）"}
          </strong>
          {!edited && (
            <Badge tone={confidenceTone(d.confidence)}>
              判讀信心 {confidenceText(d.confidence)}（{Math.round(d.confidence * 100)}%）
            </Badge>
          )}
          {edited && <Badge tone="accent">已手動修正</Badge>}
        </Cluster>
        {!edited && d.reasons.length > 0 && (
          <ul className="analysis-reasons">
            {d.reasons.map((r) => <li key={r}>{r}</li>)}
          </ul>
        )}
        {!edited && d.hints.map((h) => {
          const idx = workIndexToSegmentIndex(segments, h.work_index);
          return (
            <Cluster key={`${h.type}-${h.work_index}`} gap={2}>
              <Text variant="caption">第 {h.work_index + 1}、{h.work_index + 2} 趟加起來正好 {h.total_m}m，可能是同一趟中途停下。</Text>
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
            </Cluster>
          );
        })}
      </div>

      <div className="grid-2 analysis-type-grid">
        <Stack gap={2}>
          <div className="field-label">課表類型</div>
          <Segmented
            value={sessionType}
            onChange={setSessionType}
            options={(Object.keys(SESSION_LABEL) as WorkoutSessionType[]).map((k) => ({ value: k, label: SESSION_LABEL[k][locale] }))}
          />
        </Stack>
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
              <th>配速</th>
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
                      aria-label={`第 ${i + 1} 段類型`}
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
                        aria-label={`第 ${i + 1} 段標準距離`}
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
                      <Text variant="caption">—</Text>
                    )}
                  </td>
                  <td>{st ? <Figure kind="distance" meters={st.gps_distance_m} /> : "…"}</td>
                  <td>
                    {st ? clockText(isWork ? st.moving_s : st.elapsed_s) : "…"}
                    {st && st.interruptions_s > 0 && <Text variant="caption" as="div">含中途停 {st.interruptions_s} 秒（已扣除）</Text>}
                  </td>
                  <td>{st && (isWork || seg.role === "warmup" || seg.role === "cooldown" || seg.role === "steady") ? <Figure kind="pace" secPerKm={st.pace_s_per_km} /> : st?.rest_type ? REST_TYPE_LABEL[st.rest_type] : "—"}</td>
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
      <Row justify="between" wrap gap={2}>
        <span className="field-hint">
          共 {workCount} 段強度。配速以「標準距離」計算（操場上 GPS 彎道常偏長 1–5%）；中途停下的時間不計入該趟。
        </span>
        {edited && <Button size="sm" variant="ghost" icon="refresh" onClick={onReset}>還原系統判讀</Button>}
      </Row>

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
          {hr.history_peak_30s ? <Text variant="caption">（歷史 30 秒最高 {hr.history_peak_30s} bpm）</Text> : null}
        </span>
      ) : (
        <span>尚未有最大心率設定</span>
      )}
      {!editing && <Button size="sm" variant="ghost" onClick={() => setEditing(true)}>修改</Button>}
      {editing && (
        <Cluster gap={2} className="analysis-hr-editor">
          <input className="input input-sm analysis-hr-input" inputMode="numeric" aria-label="最大心率" placeholder="最大心率" value={maxHr} onChange={(e) => setMaxHr(e.target.value.replace(/\D/g, ""))} />
          <input className="input input-sm analysis-hr-input" inputMode="numeric" aria-label="安靜心率" placeholder="安靜心率" value={restHr} onChange={(e) => setRestHr(e.target.value.replace(/\D/g, ""))} />
          <Button size="sm" variant="primary" disabled={saving} onClick={() => void save(false)}>儲存</Button>
          <Button size="sm" disabled={saving} onClick={() => void save(true)}>改回手錶設定</Button>
          <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>取消</Button>
          <Text variant="caption" className="analysis-hr-note">
            優先順序：你的手動設定 → Garmin 手錶當天設定 → 歷史紀錄推算 → 年齡公式（Tanaka）。
          </Text>
          {err && <span className="field-error">{err}</span>}
        </Cluster>
      )}
      {hr.notes.map((n) => <Text key={n} variant="caption" as="div" className="analysis-hr-note">{n}</Text>)}
    </div>
  );
}

/* ---------------- result step ---------------- */

type Finding = WorkoutFindingWire | ReturnType<typeof workoutVerdict>["notes"][number];

/* Verdict first: the plate says how many reps met the prescription and the
 * one thing to change. Below it, rep by rep: the pace chart with each rep's
 * end-of-rep heart rate, then the full rep table. Both read one repSeries,
 * so the chart and the table cannot disagree. */
function ResultStep({ result, locale }: { result: WorkoutAnalysisWire; locale: Locale }) {
  const verdict = useMemo(() => workoutVerdict(result), [result]);
  const prescription = result.summary.prescription as { title?: string; source_label?: string; gradable?: boolean } | undefined;
  const series = useMemo(() => repSeries(result, 640), [result]);
  const hr = result.summary.hr_profile;
  const notes = [...result.data_notes, ...hr.notes];

  return (
    <div className="analysis-result">
      <section className="analysis-verdict" aria-label="結論">
        <Plate
          variant="statement"
          className="analysis-plate"
          label={`${SESSION_LABEL[result.session_type][locale]} · ${result.signature_label}`}
          value={verdict.headline}
          caption={verdict.next ? <span><span className="analysis-next-tag">下次</span>{verdict.next}</span> : undefined}
        />
        {prescription?.title && (
          <p className="analysis-prescription">
            課表要求 <strong>{prescription.title}</strong>
            <span className="analysis-prescription-source">
              {prescription.source_label}{prescription.gradable ? "" : "（不評分）"}
            </span>
          </p>
        )}
        {verdict.narrative && (
          <section className="analysis-coach" aria-label="AI 教練講評">
            <ModuleHead title="AI 教練講評" />
            <div className="analysis-narrative">
              <MarkdownMessage content={verdict.narrative} />
            </div>
            <p className="analysis-narrative-source" title={result.fallback_reason ?? undefined}>
              {result.narrative_source === "llm"
                ? `講評依上方數據撰寫，文中數字皆已對照你的紀錄（${result.narrative_model}）`
                : "講評依上方判讀結果整理"}
            </p>
          </section>
        )}
        {verdict.notes.length > 0 && <FindingRows findings={verdict.notes} label="其他觀察" />}
      </section>

      {series.reps.length > 0 && <RepFigures result={result} series={series} />}
      {series.reps.filter((r) => r.bar).length >= 2 && <RepChart result={result} />}
      {series.reps.length > 0 && <RepTable series={series} />}

      {(verdict.recovery.length > 0 || notes.length > 0) && (
        <section className="analysis-recovery" aria-label="心率與恢復的觀察">
          {verdict.recovery.length > 0 && <FindingRows findings={verdict.recovery} label="心率與恢復的觀察" />}
          {notes.length > 0 && (
            <ul className="analysis-notes">
              {notes.map((n) => <li key={n}>{n}</li>)}
            </ul>
          )}
        </section>
      )}
      <p className="analysis-hr-settings">
        心率設定：最大 {hr.max_hr ?? "—"} bpm（{HR_SOURCE_LABEL[hr.max_hr_source ?? ""] ?? "—"}）
        {hr.resting_hr ? ` · 安靜 ${hr.resting_hr} bpm` : ""}
        {hr.zone_tops.length ? ` · 區間上限 ${hr.zone_tops.slice(0, 5).join(" / ")} bpm` : ""}
      </p>
    </div>
  );
}

/** the four figures the session is read by: 各趟平均配速, 配速變異係數,
 *  平均休息, 最高心率 */
function RepFigures({ result, series }: { result: WorkoutAnalysisWire; series: RepSeries }) {
  const s = result.summary;
  const cv = typeof s.block_cv_pct === "number" ? s.block_cv_pct : null;
  const maxHr = typeof s.max_hr === "number" ? s.max_hr : typeof s.peak_rep_hr === "number" ? s.peak_rep_hr : null;
  const workKm = typeof s.work_distance_m === "number" ? s.work_distance_m / 1000 : null;
  return (
    <dl className="analysis-figures">
      <div className="analysis-figure">
        <dt>各趟平均配速</dt>
        <dd><Figure kind="pace" secPerKm={series.mean.sec} /></dd>
        <dd className="analysis-figure-note">{series.reps.length} 趟{workKm ? ` · ${Number(workKm.toFixed(2))} km` : ""}</dd>
      </div>
      {cv !== null && (
        <div className="analysis-figure">
          <dt>配速變異係數</dt>
          <dd><span className="rs-figure"><span className="rs-figure__val">{cv}</span><span className="rs-figure__unit">%</span></span></dd>
          <dd className="analysis-figure-note">≤1% 極穩定 · ≤2% 穩定</dd>
        </div>
      )}
      {series.restMeanSec !== null && (
        <div className="analysis-figure">
          <dt>平均休息</dt>
          <dd><Figure kind="duration" seconds={series.restMeanSec} /></dd>
        </div>
      )}
      {maxHr !== null && (
        <div className="analysis-figure">
          <dt>最高心率</dt>
          <dd><span className="rs-figure"><span className="rs-figure__val">{maxHr}</span><span className="rs-figure__unit">bpm</span></span></dd>
        </div>
      )}
    </dl>
  );
}

/* One table, open, every rep: what was asked, what was run, the gap, heart
 * rate and the rest after it. It scrolls sideways inside its panel on a
 * phone, with the rep number pinned. */
function RepTable({ series }: { series: RepSeries }) {
  return (
    <Surface as="section" depth="inner" padding="md" className="analysis-reps" aria-label="每趟對照">
      <ModuleHead title="每趟對照" />
      <div className="analysis-rep-scroll" tabIndex={0} role="region" aria-label="每趟對照表，可左右捲動">
        <table className="analysis-rep-table">
          <caption className="sr-only">每趟的距離、時間、配速、要求、差距、心率與休息</caption>
          <thead>
            <tr>
              <th scope="col">趟</th>
              <th scope="col">距離</th>
              <th scope="col">時間</th>
              <th scope="col">配速</th>
              <th scope="col">要求</th>
              <th scope="col">與要求差距</th>
              <th scope="col">平均 / 結束心率</th>
              <th scope="col">前半 / 後半</th>
              <th scope="col">之後休息</th>
              <th scope="col">休息心率下降</th>
            </tr>
          </thead>
          <tbody>
            {series.reps.map((r) => (
              <tr key={r.index}>
                <th scope="row">{r.repNumber}</th>
                <td>{r.distanceText}</td>
                <td>
                  <Figure kind="duration" seconds={r.timeSec} />
                  {r.interruptionsSec > 0 && <span className="analysis-cell-note">含中途停 {r.interruptionsSec} 秒，已扣除</span>}
                </td>
                <td className="analysis-rep-pace"><Figure kind="pace" secPerKm={r.paceSec} /></td>
                <td>{r.targetText}</td>
                <td>
                  <span className={r.gap.within === false ? "analysis-gap is-out" : "analysis-gap"}>
                    {r.gap.text}
                    {r.gap.within === false && <span className="analysis-gap-flag">超出 ±{TOLERANCE_PCT}%</span>}
                  </span>
                </td>
                <td className="analysis-rep-num">{r.hrText}</td>
                <td className="analysis-rep-num">{r.halvesText}</td>
                <td>
                  {r.restSec !== null ? <Figure kind="duration" seconds={r.restSec} /> : "—"}
                  {r.restKind && <span className="analysis-cell-note">{r.restKind}</span>}
                </td>
                <td className="analysis-rep-num">{r.hrDropText}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Surface>
  );
}

/** findings as hairline rows; the severity is a word, its colour only
 *  repeats it */
function FindingRows({ findings, label }: { findings: Finding[]; label: string }) {
  return (
    <HairlineList label={label}>
      {findings.map((f, i) => (
        <HairlineRow
          key={`${f.code}-${i}`}
          title={f.title}
          detail={
            <>
              {f.detail}
              {f.advice && <span className="analysis-finding-advice">建議：{f.advice}</span>}
            </>
          }
          aside={<span className={`analysis-severity is-${f.severity}`}>{SEVERITY[f.severity].label}</span>}
        />
      ))}
    </HairlineList>
  );
}

/* Rep-by-rep pace on one scale: taller = faster, each rep's required pace a
 * tick across its bar, the set mean a dashed line. Heart rate at the end of
 * each rep rides in its own band above, one dot per rep on the bar's centre.
 * A rep slow beyond the tolerance is a dimmed bar and is also named in the
 * table, so colour is never the only signal. */
function RepChart({ result }: { result: WorkoutAnalysisWire }) {
  // drawn at its real width so labels keep their size on a phone
  const frame = useRef<HTMLDivElement | null>(null);
  const [width, setWidth] = useState(640);
  useEffect(() => {
    const el = frame.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.max(240, Math.floor(entry.contentRect.width))));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const s = useMemo(() => repSeries(result, width), [result, width]);
  const { left, right } = REP_CHART;
  const W = s.width;
  const hasTargets = s.reps.some((r) => r.bar?.targetY != null);
  const hasDim = s.reps.some((r) => r.dimmed);
  const label = s.reps
    .map((r) => `第 ${r.repNumber} 趟 ${r.paceText}${r.endHr !== null ? `，結束心率 ${r.endHr}` : ""}`)
    .join("；");

  return (
    <Surface as="section" depth="inner" padding="md" className="analysis-chart" aria-label="每趟配速">
      <ModuleHead
        title="每趟配速"
        action={
          <span className="analysis-legend">
            <span className="analysis-legend-item"><i className="analysis-key-bar" aria-hidden="true" />長條越高越快</span>
            <span className="analysis-legend-item"><i className="analysis-key-mean" aria-hidden="true" />虛線＝平均 {s.mean.label}</span>
            {hasTargets && <span className="analysis-legend-item"><i className="analysis-key-target" aria-hidden="true" />標線＝該趟要求</span>}
            {s.hasHr && <span className="analysis-legend-item"><i className="analysis-key-hr" aria-hidden="true" />點＝每趟結束心率</span>}
            {hasDim && <span className="analysis-legend-item"><i className="analysis-key-bar is-dim" aria-hidden="true" />淡色＝慢於要求 ±{TOLERANCE_PCT}% 外</span>}
          </span>
        }
      />
      <div ref={frame} className="rep-chart-frame">
        <svg viewBox={`0 0 ${W} ${s.height}`} width={W} height={s.height} role="img" aria-label={label} className="rep-chart">
          {s.hasHr && (
            <text x={left - 10} y={(s.hrBandTop + s.hrBandBottom) / 2 + 4} textAnchor="end" className="rep-chart-axis">心率</text>
          )}
          {s.reps.map((r) => r.bar && (
            <g key={r.index}>
              <rect x={r.bar.x} y={r.bar.y} width={r.bar.w} height={r.bar.h} rx={3}
                className={r.dimmed ? "rep-chart-bar is-dim" : "rep-chart-bar"} />
              {r.bar.targetY !== null && r.bar.tick.map((seg) => (
                <line key={seg.x1} x1={seg.x1} x2={seg.x2} y1={r.bar!.targetY!} y2={r.bar!.targetY!} className="rep-chart-target" />
              ))}
            </g>
          ))}
          {s.mean.y !== null && (
            <>
              <line x1={left} x2={W - right} y1={s.mean.y} y2={s.mean.y} className="rep-chart-mean" />
              <text x={left - 10} y={s.mean.y - 4} textAnchor="end" className="rep-chart-axis">平均</text>
              <text x={left - 10} y={s.mean.y + 14} textAnchor="end" className="rep-chart-mean-value">{s.mean.label}</text>
            </>
          )}
          <line x1={left} x2={W - right} y1={s.base} y2={s.base} className="rep-chart-base" />
          {/* after the mean line, so each label's halo clears the line behind it */}
          {s.reps.map((r) => r.bar && (
            <text key={`v-${r.index}`} x={r.bar.cx} y={r.bar.labelY} textAnchor="middle" className="rep-chart-value">{r.bar.label}</text>
          ))}
          {s.hrLine && <polyline points={s.hrLine} className="rep-chart-hr-line" />}
          {s.reps.map((r) => r.hr && (
            <g key={`hr-${r.index}`}>
              <circle cx={r.hr.x} cy={r.hr.y} r={REP_CHART.hrDot} className="rep-chart-hr-dot" />
              <text x={r.hr.x} y={r.hr.labelY} textAnchor="middle" className="rep-chart-hr-label">{r.hr.label}</text>
            </g>
          ))}
          <text x={left - 10} y={s.base + 20} textAnchor="end" className="rep-chart-axis">趟</text>
          {s.reps.map((r) => (
            <text key={`n-${r.index}`} x={r.axisX} y={s.base + 20} textAnchor="middle" className="rep-chart-rep-no">{r.repNumber}</text>
          ))}
        </svg>
      </div>
    </Surface>
  );
}
