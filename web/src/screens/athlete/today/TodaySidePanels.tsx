import { useState } from "react";
import { Surface } from "../../../components/Surface.tsx";
import { Button } from "../../../components/ui.tsx";
import { GlassPanel } from "../../../components/motion.tsx";
import { SeverityBadge, SyncChip } from "../../../components/domain.tsx";
import { Icon } from "../../../components/Icon.tsx";
import { formatDuration, formatNumber, UNIT_SHORT } from "../../../lib/format.ts";
import type { TodaySlot } from "../../../lib/todayViewModel.ts";
import type { Activity, InjuryReport } from "../../../lib/types.ts";
import { paceShapeText, type TodayCopy } from "./todayCopy.ts";
import { Row } from "../../../components/Layout.tsx";

type Locale = "zh-TW" | "en";

/** Morning / midday / evening temperature with the plan's climate-equivalent pace. */
export function TimeOfDaySlots({ slots, active, c }: { slots: TodaySlot[]; active?: TodaySlot | null; c: TodayCopy }) {
  return (
    <>
      {slots.map((slot) => {
        const pace = paceShapeText(slot.pace);
        return (
          <div key={slot.label} className={`ath-slot${slot === active ? " is-active" : ""}`}>
            <div className="ath-slot-label">{slot.label === "morning" ? c.morning : slot.label === "midday" ? c.midday : c.evening}</div>
            <div className="ath-slot-temp tnum">{slot.temperatureC.toFixed(0)}°C</div>
            {pace && <div className="ath-slot-pace tnum">{pace}</div>}
          </div>
        );
      })}
    </>
  );
}

export function SlotsPanel({ slots, active, c, locale }: { slots: TodaySlot[]; active: TodaySlot | null; c: TodayCopy; locale: Locale }) {
  const en = locale === "en";
  if (slots.length === 0) return null;
  return (
    <GlassPanel className="ath-panel" as="section" aria-labelledby="ath-slots-title">
      <h2 className="ath-panel-title" id="ath-slots-title">{en ? "Pace by time of day" : "時段配速"}</h2>
      <p className="ath-panel-sub">{en ? "Climate-equivalent pace; highlighted is closest to your run" : "同等強度的氣候換算配速，亮框為最接近你出發的時段"}</p>
      <div className="ath-slots">
        <TimeOfDaySlots slots={slots} active={active} c={c} />
      </div>
    </GlassPanel>
  );
}

export function bodyStatusLabel(latest: InjuryReport | undefined, locale: Locale): string {
  const en = locale === "en";
  if (!latest) return en ? "Not reported" : "尚未回報";
  if (latest.hasIssue && latest.severityBand === "SEVERE") return en ? "Severe discomfort reported" : "已回報嚴重不適";
  if (latest.hasIssue) return en ? "Discomfort reported" : "已回報身體不適";
  return en ? "Last report: no discomfort" : "上次回報無不適";
}

export function BodyStatusPanel({ latest, c, locale }: { latest: InjuryReport | undefined; c: TodayCopy; locale: Locale }) {
  const en = locale === "en";
  const redFlag = latest?.hasIssue === true && latest.severityBand === "SEVERE";
  return (
    <GlassPanel className={`ath-panel ath-triage${redFlag ? " is-red" : " is-unassessed"}`} as="section" aria-labelledby="ath-triage-title">
      <h2 className="ath-panel-title" id="ath-triage-title">{en ? "Body report" : "身體回報"}</h2>
      <Row gap={2} className="ath-triage-state" role="status">
        <Icon name={redFlag ? "alert" : "shield"} size={16} />
        <strong>{bodyStatusLabel(latest, locale)}</strong>
      </Row>
      <details className="ath-triage-details" open={redFlag || undefined}>
        <summary>{en ? "Latest body report" : "最近一次身體回報"}</summary>
        {latest ? (
          <dl className="ath-kv">
            <div><dt>{c.latest}</dt><dd><SeverityBadge band={latest.severityBand} /></dd></div>
            <div><dt>{c.bodyPart}</dt><dd>{latest.bodyPart || "—"}</dd></div>
            <div><dt>{en ? "Reported" : "回報日"}</dt><dd className="tnum">{latest.localDate}</dd></div>
          </dl>
        ) : (
          <p className="ath-panel-sub">{c.noInjury}</p>
        )}
      </details>
    </GlassPanel>
  );
}

export function CoachInsightPanel({ text, isRestDay, c, locale, onOpenLoad }: {
  /** Real guidance for today, or null when there is nothing beyond the plan itself. */
  text: string | null;
  isRestDay: boolean;
  c: TodayCopy;
  locale: Locale;
  onOpenLoad: () => void;
}) {
  const en = locale === "en";
  const [showExplain, setShowExplain] = useState(false);
  return (
    <GlassPanel className="ath-panel" as="section" aria-labelledby="ath-insight-title">
      <h2 className="ath-panel-title" id="ath-insight-title">{c.reminder}</h2>
      {isRestDay ? (
        <p className="ath-insight-text">
          {en ? "Today is a scheduled recovery day. Listen to your body and prioritize rest." : "今日建議完全休息，不強行進行高強度跑步，讓身體有充分時間修復。"}
        </p>
      ) : text && <p className="ath-insight-text">{text}</p>}
      <div className="ath-insight-actions">
        <Button size="sm" variant="secondary" icon="trend" onClick={onOpenLoad}>
          {en ? "7 / 28-day load" : "查看 7／28 天負荷"}
        </Button>
        <button type="button" className="btn btn-ghost btn-sm" aria-expanded={showExplain} onClick={() => setShowExplain((v) => !v)}>
          {showExplain ? c.collapse : c.explain}
        </button>
      </div>
      {showExplain && (
        <p className="ath-insight-explain">
          <strong>{c.explainTitle}：</strong>{c.explainBody}
        </p>
      )}
    </GlassPanel>
  );
}

export function RecentActivitiesPanel({ activities, c, locale }: { activities: Activity[]; c: TodayCopy; locale: Locale }) {
  return (
    <Surface as="details" className="ath-panel ath-disclosure">
      <summary className="ath-disclosure-summary"><span className="ath-panel-title">{c.recent}</span></summary>
      <div className="ath-disclosure-content">
        <ul className="ath-recent">
          {activities.map((activity) => (
            <li key={activity.id}>
              <div>
                <div className="ath-recent-main tnum">
                  {formatDuration(activity.durationMinutes, locale)}
                  {activity.distanceKm && ` · ${activity.distanceKm} km`}
                  {activity.rpe !== null && ` · RPE ${activity.rpe}`}
                </div>
                <div className="ath-recent-sub tnum">
                  {activity.localTrainingDate} · {c.sessionLoad} {formatNumber(activity.sessionLoad)} {UNIT_SHORT[activity.unit]}
                </div>
              </div>
              <SyncChip state={activity.syncState} />
            </li>
          ))}
        </ul>
      </div>
    </Surface>
  );
}
