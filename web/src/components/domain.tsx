/* Domain chips and the step-up dialog — the small pieces that show up on more
 * than one screen and must read identically everywhere. */

import { useState } from "react";
import type { ReactNode } from "react";
import { Badge, Button, Field, Modal, Notice } from "./ui.tsx";
import { Icon } from "./Icon.tsx";
import type { Tone } from "./ui.tsx";
import {
  DATA_QUALITY_LABEL,
  SEVERITY_LABEL,
  SYNC_LABEL,
  WEATHER_STATE_LABEL,
} from "../lib/format.ts";
import type {
  DataQuality,
  SeverityBand,
  SyncState,
  WeatherState,
} from "../lib/types.ts";
import { DEMO_MFA_CODE } from "../state/AuthContext.tsx";

const SYNC_TONE: Record<SyncState, Tone> = {
  LOCAL_ONLY: "neutral",
  SYNCING: "accent",
  SYNCED: "good",
  FAILED_RETRYABLE: "warning",
  FAILED_TERMINAL: "critical",
};

export function SyncChip({ state }: { state: SyncState }) {
  return (
    <Badge tone={SYNC_TONE[state]} dot>
      {SYNC_LABEL[state]}
    </Badge>
  );
}

const QUALITY_TONE: Record<DataQuality, Tone> = {
  OK: "good",
  LOW: "warning",
  INSUFFICIENT: "neutral",
};

export function DataQualityBadge({ quality }: { quality: DataQuality }) {
  return (
    <Badge tone={QUALITY_TONE[quality]} dot>
      {DATA_QUALITY_LABEL[quality]}
    </Badge>
  );
}

const SEVERITY_TONE: Record<SeverityBand, Tone> = {
  NONE: "good",
  MILD: "warning",
  MODERATE: "serious",
  SEVERE: "critical",
};

export function SeverityBadge({ band }: { band: SeverityBand }) {
  return (
    <Badge tone={SEVERITY_TONE[band]} dot>
      {SEVERITY_LABEL[band]}
    </Badge>
  );
}

const WEATHER_TONE: Record<WeatherState, Tone> = {
  LIVE: "good",
  CACHED: "accent",
  STALE: "warning",
  UNAVAILABLE: "neutral",
};

export function WeatherStateBadge({ state }: { state: WeatherState }) {
  return (
    <Badge tone={WEATHER_TONE[state]} dot>
      {WEATHER_STATE_LABEL[state]}
    </Badge>
  );
}

/** Coach-side placeholder for a field this athlete has not granted.
 *  It says *which* scope is missing rather than showing a blank cell — a blank
 *  reads as "no data", which is a different and misleading claim. */
export function MaskedValue({ scopeLabel }: { scopeLabel: string }) {
  return (
    <span className="masked" title={`未取得「${scopeLabel}」授權`}>
      <Icon name="lock" size={12} />
      未授權
    </span>
  );
}

/** REQ-AUTH-008: export, role change and billing changes re-verify identity
 *  even though the session is already authenticated. */
export function StepUpModal({
  open,
  action,
  onCancel,
  onVerified,
}: {
  open: boolean;
  action: string;
  onCancel: () => void;
  onVerified: () => void;
}) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit() {
    if (code.trim() !== DEMO_MFA_CODE) {
      setError("驗證碼不正確");
      return;
    }
    setCode("");
    setError(null);
    onVerified();
  }

  return (
    <Modal
      open={open}
      title="需要再次驗證身分"
      description={
        <>
          你正在執行「{action}」。這類高風險操作即使已登入，也要重新驗證一次。
        </>
      }
      onClose={() => {
        setCode("");
        setError(null);
        onCancel();
      }}
      footer={
        <>
          <Button
            onClick={() => {
              setCode("");
              setError(null);
              onCancel();
            }}
          >
            取消
          </Button>
          <Button variant="primary" onClick={submit} disabled={code.length === 0}>
            驗證並繼續
          </Button>
        </>
      }
    >
      <div className="stack">
        <Field
          label="驗證應用程式的 6 位數驗證碼"
          htmlFor="stepup-code"
          error={error}
          hint={`示範環境固定為 ${DEMO_MFA_CODE}`}
        >
          <input
            id="stepup-code"
            className="input"
            inputMode="numeric"
            maxLength={6}
            autoComplete="one-time-code"
            value={code}
            placeholder="000000"
            onChange={(e) => {
              setCode(e.target.value.replace(/\D/g, ""));
              setError(null);
            }}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
        </Field>
        <Notice tone="neutral" icon="shield">
          驗證紀錄會寫入稽核日誌，但驗證碼本身不會被記錄。
        </Notice>
      </div>
    </Modal>
  );
}

/** A labelled section heading used inside long settings pages. */
export function SectionHeading({
  title,
  description,
  reqTags,
  aside,
}: {
  title: string;
  description?: ReactNode;
  reqTags?: string[];
  aside?: ReactNode;
}) {
  return (
    <div className="row-between" style={{ alignItems: "flex-start" }}>
      <div>
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <h2 style={{ fontSize: 15 }}>{title}</h2>
          {reqTags?.map((t) => (
            <span key={t} className="req-tag">
              {t}
            </span>
          ))}
        </div>
        {description && (
          <p className="card-subtitle" style={{ maxWidth: "76ch" }}>
            {description}
          </p>
        )}
      </div>
      {aside}
    </div>
  );
}
