/* "課表要求" -- what was prescribed for one session, rep by rep, and where
 * that came from. The source is always shown: only a real prescription
 * (coach's assignment / typed by the athlete / written in the Garmin
 * activity name) is used to grade a session; an inferred one is
 * reconstructed from the run itself and only describes its structure.
 *
 * The athlete can type the workout in plain words ("400x15 90 85 80 間休60");
 * the backend turns it into structure and refuses any number that is not
 * in the text, and the parsed result is shown for confirmation before it
 * is saved. */

import { useState } from "react";
import { Badge, Button, Notice } from "./ui.tsx";
import type { Tone } from "./ui.tsx";
import { Icon } from "./Icon.tsx";
import { ApiError, deletePrescription, parsePrescription, savePrescription } from "../data/apiClient.ts";
import type {
  LinkedRecordsWire,
  PrescriptionBlockWire,
  PrescriptionSource,
  PrescriptionWire,
} from "../data/apiClient.ts";

const SOURCE_TONE: Record<PrescriptionSource, Tone> = {
  coach_assignment: "accent",
  athlete_text: "good",
  activity_name: "good",
  inferred: "good",
};

const SOURCE_LABEL: Record<PrescriptionSource, string> = {
  coach_assignment: "教練指派",
  athlete_text: "你填寫的課表",
  activity_name: "Garmin 活動名稱",
  inferred: "課表結構",
};

function mmss(sec: number): string {
  const s = Math.round(sec);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function targetText(block: PrescriptionBlockWire): string {
  const t = block.targets_s_per_km;
  if (!t.length) return "—";
  const fmt = (pace: number) =>
    block.distance_m && block.distance_m <= 600 ? `${Math.round((pace * block.distance_m) / 1000)} 秒` : `${mmss(pace)}/km`;
  const uniq = [...new Set(t.map((x) => Math.round(x * 10)))];
  return uniq.length === 1 ? fmt(t[0]) : t.map(fmt).join(" → ");
}

function blockUnit(block: PrescriptionBlockWire): string {
  return block.distance_m ? `${block.distance_m} m` : block.duration_s ? `${block.duration_s} 秒` : "—";
}

export function PrescriptionBlocks({ prescription }: { prescription: PrescriptionWire }) {
  return (
    <div className="table-scroll">
      <table className="splits-table">
        <thead>
          <tr>
            <th>組</th>
            <th>趟數</th>
            <th>每趟</th>
            <th>要求</th>
            <th>休息</th>
          </tr>
        </thead>
        <tbody>
          {prescription.blocks.map((b, i) => (
            <tr key={i}>
              <td>{i + 1}</td>
              <td>{b.reps}</td>
              <td>{blockUnit(b)}</td>
              <td>
                <strong>{targetText(b)}</strong>
                {b.targets_inferred && <div className="field-hint">（原課表沒寫配速，依實際配速推估）</div>}
              </td>
              <td>{b.rest_s ? `${b.rest_s} 秒` : "—"}{b.rest_after_s && b.rest_after_s !== b.rest_s ? <div className="field-hint">組後 {b.rest_after_s} 秒</div> : null}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function LinkedRecordsLine({ linked }: { linked: LinkedRecordsWire }) {
  if (!linked.warmup && !linked.cooldown) return null;
  const item = (label: string, r: NonNullable<LinkedRecordsWire["warmup"]>) => (
    <span className="prescription-linked">
      <Icon name="link" size={14} />
      {label}另有紀錄：{r.start_local} 開始，{r.distance_km.toFixed(2)} km，{mmss(r.duration_s)}
      {r.avg_hr ? `，平均心率 ${r.avg_hr}` : ""}
    </span>
  );
  return (
    <div className="row" style={{ gap: 12, flexWrap: "wrap" }}>
      {linked.warmup && item("暖身", linked.warmup)}
      {linked.cooldown && item("收操", linked.cooldown)}
    </div>
  );
}

export function PrescriptionCard({
  activityId,
  accessToken,
  prescription,
  activityName,
  linked,
  onChanged,
  compact,
  control,
}: {
  activityId: string;
  accessToken: string;
  prescription: PrescriptionWire | null;
  activityName: string | null;
  linked?: LinkedRecordsWire;
  onChanged: () => void;
  compact?: boolean;
  /** Only the pace-source line and the editor -- the paces themselves are
   *  shown in the workout structure above it. */
  control?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [parsed, setParsed] = useState<PrescriptionWire | null>(null);
  const [problems, setProblems] = useState<string[]>([]);
  const [alignIssues, setAlignIssues] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);

  const startEdit = () => {
    setText(prescription?.source === "athlete_text" ? prescription.raw_text ?? "" : "");
    setParsed(null);
    setProblems([]);
    setAlignIssues([]);
    setError(null);
    setEditing(true);
  };

  const parse = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await parsePrescription(accessToken, activityId, text);
      setParsed(res.prescription);
      setProblems(res.problems);
      setAlignIssues(res.alignment_issues);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "無法解析課表");
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    if (!parsed) return;
    setBusy(true);
    try {
      await savePrescription(accessToken, activityId, text, parsed.blocks);
      setEditing(false);
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "儲存失敗");
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    setBusy(true);
    try {
      await deletePrescription(accessToken, activityId);
      setEditing(false);
      onChanged();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "清除失敗");
    } finally {
      setBusy(false);
    }
  };

  const source = prescription?.source;
  return (
    <div className={control ? "prescription-control" : compact ? "prescription-card prescription-card-compact" : "prescription-card"}>
      <div className="row-between" style={{ gap: 10, flexWrap: "wrap" }}>
        {control ? <span /> : (
          <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <Icon name="assignment" size={18} />
            <strong>課表要求</strong>
            {source && source !== "inferred" && <Badge tone={SOURCE_TONE[source]}>{SOURCE_LABEL[source]}</Badge>}
          </div>
        )}
        {!editing && (
          <Button size="sm" onClick={startEdit}>
            {source === "athlete_text" ? "修改課表" : "輸入教練開的課表"}
          </Button>
        )}
      </div>

      {control ? (
        (prescription?.issues?.length ?? 0) > 0 ? (
          <Notice tone="warning" icon="alert">{prescription!.issues!.join("；")}</Notice>
        ) : null
      ) : prescription ? (
        <div className="stack-sm" style={{ marginTop: 8 }}>
          <div className="prescription-title">{prescription.title}</div>
          {source === "activity_name" && activityName && <div className="field-hint">來自活動名稱：「{activityName}」</div>}
          {source === "athlete_text" && prescription.raw_text && <div className="field-hint">你輸入的：「{prescription.raw_text}」</div>}
          {(prescription.issues?.length ?? 0) > 0 && (
            <Notice tone="warning" icon="alert">{prescription.issues!.join("；")}</Notice>
          )}
          {!compact && <PrescriptionBlocks prescription={prescription} />}
        </div>
      ) : (
        <div className="field-hint" style={{ marginTop: 6 }}>這筆紀錄沒有判讀出強度課表。</div>
      )}

      {linked && !control && <div style={{ marginTop: 8 }}><LinkedRecordsLine linked={linked} /></div>}

      {editing && (
        <div className="stack-sm prescription-editor">
          <label className="field-label" htmlFor={`presc-${activityId}`}>用一般寫法輸入課表</label>
          <textarea
            id={`presc-${activityId}`}
            className="input"
            rows={2}
            placeholder="例如：400x15 90 85 80 間休60　／　2000 1000 800 @3:50 3:40 3:30 r2min　／　1000x6 3:40/km 組休60"
            value={text}
            onChange={(e) => { setText(e.target.value); setParsed(null); }}
          />
          <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
            <Button size="sm" variant="primary" disabled={busy || !text.trim()} onClick={() => void parse()}>
              {busy && !parsed ? "解析中…" : "解析"}
            </Button>
            {source === "athlete_text" && (
              <Button size="sm" disabled={busy} onClick={() => void clear()}>清除我輸入的課表</Button>
            )}
            <Button size="sm" variant="ghost" onClick={() => setEditing(false)}>取消</Button>
          </div>
          {error && <Notice tone="critical" icon="alert">{error}</Notice>}
          {problems.length > 0 && <Notice tone="warning" icon="alert">{problems.join("；")}</Notice>}
          {parsed && (
            <div className="stack-sm">
              <div className="field-hint">解析結果，確認無誤再儲存：</div>
              <div className="prescription-title">{parsed.title}</div>
              <PrescriptionBlocks prescription={parsed} />
              {alignIssues.length > 0 && (
                <Notice tone="warning" icon="alert">
                  和實際紀錄對不起來：{alignIssues.join("；")}。仍可儲存，但分析時不會以這份要求評分。
                </Notice>
              )}
              <div>
                <Button size="sm" variant="primary" icon="check" disabled={busy} onClick={() => void save()}>
                  儲存課表
                </Button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
