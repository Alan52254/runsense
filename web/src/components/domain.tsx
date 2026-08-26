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
import { useLocale } from "../state/LocaleContext.tsx";

const EN_LABELS = {
  sync: {
    LOCAL_ONLY: "Pending sync", SYNCING: "Syncing", SYNCED: "Synced",
    FAILED_RETRYABLE: "Sync failed; retrying", FAILED_TERMINAL: "Sync failed; action needed",
  } satisfies Record<SyncState, string>,
  quality: { OK: "Complete data", LOW: "Low data quality", INSUFFICIENT: "Insufficient data" } satisfies Record<DataQuality, string>,
  severity: { NONE: "No issue", MILD: "Mild", MODERATE: "Moderate", SEVERE: "Severe" } satisfies Record<SeverityBand, string>,
  weather: { LIVE: "Live data", CACHED: "Cached data", STALE: "Stale data", UNAVAILABLE: "Unavailable" } satisfies Record<WeatherState, string>,
};

const SYNC_TONE: Record<SyncState, Tone> = {
  LOCAL_ONLY: "neutral",
  SYNCING: "accent",
  SYNCED: "good",
  FAILED_RETRYABLE: "warning",
  FAILED_TERMINAL: "critical",
};

export function SyncChip({ state }: { state: SyncState }) {
  const { locale } = useLocale();
  return (
    <Badge tone={SYNC_TONE[state]} dot>
      {locale === "en" ? EN_LABELS.sync[state] : SYNC_LABEL[state]}
    </Badge>
  );
}

const QUALITY_TONE: Record<DataQuality, Tone> = {
  OK: "good",
  LOW: "warning",
  INSUFFICIENT: "neutral",
};

export function DataQualityBadge({ quality }: { quality: DataQuality }) {
  const { locale } = useLocale();
  return (
    <Badge tone={QUALITY_TONE[quality]} dot>
      {locale === "en" ? EN_LABELS.quality[quality] : DATA_QUALITY_LABEL[quality]}
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
  const { locale } = useLocale();
  return (
    <Badge tone={SEVERITY_TONE[band]} dot>
      {locale === "en" ? EN_LABELS.severity[band] : SEVERITY_LABEL[band]}
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
  const { locale } = useLocale();
  return (
    <Badge tone={WEATHER_TONE[state]} dot>
      {locale === "en" ? EN_LABELS.weather[state] : WEATHER_STATE_LABEL[state]}
    </Badge>
  );
}

/** Coach-side placeholder for a field this athlete has not granted.
 *  It says *which* scope is missing rather than showing a blank cell — a blank
 *  reads as "no data", which is a different and misleading claim. */
export function MaskedValue({ scopeLabel }: { scopeLabel: string }) {
  const { locale } = useLocale();
  return (
    <span className="masked" title={locale === "en" ? `No permission for “${scopeLabel}”` : `未取得「${scopeLabel}」授權`}>
      <Icon name="lock" size={12} />
      {locale === "en" ? "Not authorized" : "未授權"}
    </span>
  );
}

import { OtpInput } from "./OtpInput.tsx";

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
  const { locale } = useLocale();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit(overrideCode?: string) {
    const testCode = (overrideCode ?? code).trim();
    if (testCode !== DEMO_MFA_CODE) {
      setError(locale === "en" ? "Incorrect verification code" : "驗證碼不正確");
      return;
    }
    setCode("");
    setError(null);
    onVerified();
  }

  return (
    <Modal
      open={open}
      title={locale === "en" ? "Verify your identity again" : "需要再次驗證身分"}
      description={
        <>
          {locale === "en"
            ? `You are about to “${action}”. This sensitive action requires verification even while signed in.`
            : `你正在執行「${action}」。這類高風險操作即使已登入，也要重新驗證一次。`}
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
            {locale === "en" ? "Cancel" : "取消"}
          </Button>
          <Button variant="primary" onClick={() => submit()} disabled={code.length === 0}>
            {locale === "en" ? "Verify and continue" : "驗證並繼續"}
          </Button>
        </>
      }
    >
      <div className="stack">
        <Field
          label={locale === "en" ? "6-digit authenticator code" : "驗證應用程式的 6 位數驗證碼"}
          htmlFor="stepup-code"
          error={error}
          hint={locale === "en" ? `Demo code: ${DEMO_MFA_CODE}` : `示範環境固定為 ${DEMO_MFA_CODE}`}
        >
          <OtpInput
            id="stepup-code"
            value={code}
            onChange={(val) => {
              setCode(val);
              setError(null);
            }}
            onComplete={(fullCode) => {
              submit(fullCode);
            }}
            error={Boolean(error)}
          />
        </Field>
        <Notice tone="neutral" icon="shield">
          {locale === "en"
            ? "The verification event is written to the audit log, but the code itself is never recorded."
            : "驗證紀錄會寫入稽核日誌，但驗證碼本身不會被記錄。"}
        </Notice>
      </div>
    </Modal>
  );
}

/** A labelled section heading used inside long settings pages. */
export function SectionHeading({
  title,
  description,
  aside,
}: {
  title: string;
  description?: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className="row-between" style={{ alignItems: "flex-start" }}>
      <div>
        <div className="row" style={{ gap: 8, flexWrap: "wrap" }}>
          <h2 style={{ fontSize: 15 }}>{title}</h2>
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
