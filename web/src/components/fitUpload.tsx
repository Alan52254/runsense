/* Uploading a run's .fit file, and which coach assignment a run completed.
 * See backend/app/activity_upload.py for the matching rules. */

import { useEffect, useState } from "react";
import { Button, Modal, Notice } from "./ui.tsx";
import {
  ApiError,
  getActivityAssignment,
  setActivityAssignment,
  uploadFitFile,
} from "../data/apiClient.ts";
import type { ActivityAssignmentWire, FitUploadResultWire } from "../data/apiClient.ts";

const WEEKDAY = "日一二三四五六";

function dayLabel(iso: string): string {
  const d = new Date(`${iso}T00:00:00Z`);
  return `${d.getUTCMonth() + 1}/${d.getUTCDate()}（${WEEKDAY[d.getUTCDay()]}）`;
}

function toBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  }
  return btoa(binary);
}

function errorText(e: unknown): string {
  if (e instanceof ApiError) {
    const message = (e.detail as { message?: string } | undefined)?.message;
    if (message) return message;
    return e.message;
  }
  return "上傳失敗，請稍後再試";
}

const ROLE_LABEL: Record<FitUploadResultWire["day_role"], string> = {
  main: "訓練", run: "訓練", warmup: "暖身", cooldown: "收操",
};

export function FitUploadModal({ open, onClose, accessToken, onUploaded }: {
  open: boolean;
  onClose: () => void;
  accessToken: string;
  onUploaded: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [rpe, setRpe] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<FitUploadResultWire | null>(null);

  useEffect(() => {
    if (!open) {
      setFile(null);
      setRpe(null);
      setError(null);
      setResult(null);
    }
  }, [open]);

  async function submit() {
    if (!file || rpe === null) return;
    setBusy(true);
    setError(null);
    try {
      const uploaded = await uploadFitFile(accessToken, toBase64(await file.arrayBuffer()), rpe);
      setResult(uploaded);
      onUploaded();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="上傳手錶檔案"
      description="選擇手錶記錄的 .fit 檔，系統會讀取每秒資料、自動切分課表，並對應到教練的課表。"
      footer={result ? (
        <Button variant="primary" onClick={onClose}>完成</Button>
      ) : (
        <>
          <Button onClick={onClose}>取消</Button>
          <Button variant="primary" icon="plus" disabled={!file || rpe === null || busy} onClick={() => void submit()}>
            {busy ? "上傳中…" : "上傳"}
          </Button>
        </>
      )}
    >
      {result ? (
        <div className="stack-sm">
          <Notice tone="accent" icon="check">
            已上傳 {dayLabel(result.local_date)}的{ROLE_LABEL[result.day_role]}
            {result.distance_km ? `：${result.distance_km} km` : ""}
            {result.signature_label ? `（${result.signature_label}）` : ""}
          </Notice>
          {(result.day_role === "main" || result.day_role === "run") && (
            <div>
              {result.assignment
                ? result.assignment.date === result.local_date
                  ? `完成教練課表：${result.assignment.title}`
                  : `完成 ${dayLabel(result.assignment.date)}的教練課表：${result.assignment.title}（改在這天練）`
                : "沒有對應的教練課表，記為自主訓練。"}
              <div className="field-hint">對應錯了的話，可以在這筆紀錄的詳細資料裡更改。</div>
            </div>
          )}
          <div className="field-hint">
            {result.notified_teams > 0
              ? "RunSense 助手已在你跟教練的聊天室發出通知。"
              : "你沒有授權教練查看訓練摘要，所以沒有通知教練。"}
          </div>
        </div>
      ) : (
        <div className="stack">
          <label className="stack-sm">
            <span className="field-label">手錶檔案（.fit）</span>
            <input type="file" accept=".fit" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </label>
          <label className="stack-sm">
            <span className="field-label">這次訓練的自覺強度（RPE 1–10）</span>
            <select className="input" value={rpe ?? ""} onChange={(e) => setRpe(e.target.value ? Number(e.target.value) : null)}>
              <option value="">請選擇</option>
              {Array.from({ length: 10 }, (_, i) => i + 1).map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
            <span className="field-hint">訓練負荷是「時間 × RPE」，手錶檔案裡沒有這個值，所以需要你填。</span>
          </label>
          {error && <Notice tone="critical" icon="alert">{error}</Notice>}
        </div>
      )}
    </Modal>
  );
}

/** Which coach assignment this run completed -- the athlete corrects the
 *  automatic match here. */
export function AssignmentLinkRow({ activityId, accessToken }: { activityId: string; accessToken: string }) {
  const [data, setData] = useState<ActivityAssignmentWire | null>(null);
  const [choice, setChoice] = useState<string>("");
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getActivityAssignment(accessToken, activityId)
      .then((wire) => {
        if (cancelled) return;
        setData(wire);
        setChoice(wire.current?.id ?? "");
      })
      .catch(() => { if (!cancelled) setData(null); });
    return () => { cancelled = true; };
  }, [accessToken, activityId]);

  if (!data) return null;

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await setActivityAssignment(accessToken, activityId, choice || null);
      const wire = await getActivityAssignment(accessToken, activityId);
      setData(wire);
      setEditing(false);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const current = data.current;
  return (
    <div className="stack-sm" style={{ padding: "4px 2px" }}>
      <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <span className="field-hint">對應教練課表：</span>
        <strong>
          {current
            ? `${dayLabel(current.local_date)} ${current.title}${current.local_date !== data.activity_date ? "（改在這天練）" : ""}`
            : "沒有（自主訓練）"}
        </strong>
        {current && <span className="field-hint">{current.linked_by === "auto" ? "系統自動配對" : "你設定的"}</span>}
        {!editing && <Button size="sm" onClick={() => setEditing(true)}>更改</Button>}
      </div>
      {editing && (
        <div className="row" style={{ gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <select className="input" value={choice} onChange={(e) => setChoice(e.target.value)}>
            <option value="">不是教練課表（自主訓練）</option>
            {data.candidates.map((c) => (
              <option key={c.id} value={c.id}>{dayLabel(c.local_date)} {c.title}</option>
            ))}
          </select>
          <Button size="sm" variant="primary" disabled={busy} onClick={() => void save()}>儲存</Button>
          <Button size="sm" onClick={() => { setEditing(false); setChoice(current?.id ?? ""); }}>取消</Button>
          <span className="field-hint">只列出前後 {data.window_days} 天內還沒完成的課表</span>
        </div>
      )}
      {error && <Notice tone="critical" icon="alert">{error}</Notice>}
    </div>
  );
}
