import { Link } from "react-router-dom";
import { Badge, Button, InfoTip, Segmented } from "../../../components/ui.tsx";
import { TiltCard } from "../../../components/motion.tsx";
import { Icon } from "../../../components/Icon.tsx";
import { estimateWorkoutTotals, formatEstimatedKmLabel } from "../../../lib/paceCalc.ts";
import { formatDuration } from "../../../lib/format.ts";
import type { AssignedWorkout } from "../../../lib/types.ts";
import type { TodayViewModel } from "../../../lib/todayViewModel.ts";
import { paceShapeText, type TodayCopy } from "./todayCopy.ts";
import { climateMomentLabel, paceShiftText } from "../../../lib/climateShift.ts";
import { Figure } from "../../../components/Figure.tsx";
import { acwrChipText } from "../../../lib/acwr.ts";
import { RoutePreview } from "../../../components/RoutePreview.tsx";

type Locale = "zh-TW" | "en";
type TrainingSource = "system" | "coach";

function ClimatePill({ label, pace, extra }: { label: string; pace: string | null; extra?: string }) {
  if (!pace && !extra) return null;
  return (
    <span className="ath-climate-pill">
      <Icon name="thermometer" size={15} />
      <span className="ath-climate-pill-label">{label}</span>
      {pace && <strong className="tnum">{pace}</strong>}
      {extra && <span className="ath-climate-pill-extra tnum">{extra}</span>}
    </span>
  );
}

function CoachHeroBody({ assignments, c, locale, onUseSystem }: {
  assignments: AssignedWorkout[];
  c: TodayCopy;
  locale: Locale;
  onUseSystem: () => void;
}) {
  if (assignments.length === 0) {
    return (
      <div className="ath-hero-empty tilt-layer">
        <h2 className="ath-hero-title">{c.noCoachPlanTitle}</h2>
        <p>{c.noCoachPlanDesc}</p>
        <Button size="sm" onClick={onUseSystem}>{c.useSystemInstead}</Button>
      </div>
    );
  }
  return (
    <>
      {assignments.map((assignment, index) => {
        const estimate = estimateWorkoutTotals(assignment.structure ?? []);
        return (
          <div key={assignment.id} className={index > 0 ? "ath-hero-extra" : undefined}>
            <h2 className="ath-hero-title tilt-layer">{assignment.title}</h2>
            <dl className="ath-metrics tilt-layer">
              <div><dt>{c.duration}</dt><dd className="tnum">{formatDuration(assignment.durationMinutes, locale)}</dd></div>
              <div><dt>{c.distance}</dt><dd className="tnum">{estimate.totalMeters > 0 ? formatEstimatedKmLabel(estimate) : "—"}</dd></div>
              <div><dt>{c.intensity}</dt><dd>{assignment.intensityLabel}</dd></div>
            </dl>
          </div>
        );
      })}
    </>
  );
}

function RestHeroBody({ locale }: { locale: Locale }) {
  const en = locale === "en";
  return (
    <div className="ath-hero-rest tilt-layer">
      <Badge tone="good" dot>{en ? "Active Recovery / Rest" : "建議模式：完全休息與主動恢復"}</Badge>
      <h2 className="ath-hero-title">
        {en ? "Take a rest day to allow muscle and tendon recovery" : "今日不排定跑步訓練，讓肌肉組織與結締組織充份修復"}
      </h2>
      <p>
        {en
          ? "Based on your recent acute-to-chronic training load (ACWR) and physical feedback, your body requires restorative rest today. Recommended activities: 15-min light foam rolling, mobility stretching, hydration, and quality sleep."
          : "依據你的 ACWR 負荷比與身體回報，今日建議以完全休息為主。建議進行 15 分鐘筋膜滾筒放鬆、輕度伸展，並維持充足水分與睡眠，為下一次高品質訓練做好準備。"}
      </p>
    </div>
  );
}

/** The plan's pace cell. A pace from the server's per-type rule (not yet the
 *  Athlete's own easy runs) quietly says so (系統規則配速); a plan with no
 *  server pace says plainly that there is no figure yet. */
function PaceCell({ vm, c }: { vm: TodayViewModel; c: TodayCopy }) {
  if (vm.paceSource === "none") {
    return (
      <div>
        <dt>{c.pace}</dt>
        <dd className="ath-pace-pending">{c.paceAwaiting}</dd>
      </div>
    );
  }
  return (
    <div>
      <dt>
        {c.pace}
        {vm.paceSource === "rule-default" && (
          <span className="ath-pace-source">
            {c.rulePace}
            <InfoTip text={c.rulePaceHint} />
          </span>
        )}
      </dt>
      <dd><Figure kind="pace" secPerKm={vm.workout.targetPaceSecPerKm} /></dd>
    </div>
  );
}

function SystemHeroBody({ vm, c, locale }: { vm: TodayViewModel; c: TodayCopy; locale: Locale }) {
  return (
    <div key={vm.activeCandidateId ?? "workout"} className="animate-card-float">
      <h2 className="ath-hero-title tilt-layer">{vm.workout.title}</h2>
      <dl className="ath-metrics tilt-layer">
        <div><dt>{c.duration}</dt><dd className="tnum">{formatDuration(vm.workout.durationMinutes, locale)}</dd></div>
        <div><dt>{c.distance}</dt><dd><Figure kind="distance" meters={vm.workout.distanceKm ? vm.workout.distanceKm * 1000 : null} /></dd></div>
        <PaceCell vm={vm} c={c} />
      </dl>
    </div>
  );
}

function AcwrZoneGauge({ ratio, zone, locale }: { ratio: number | null; zone: string | null; locale: Locale }) {
  const en = locale === "en";
  // Map 0.0 -> 2.0 onto 0% -> 100% across the Garmin-style 4-band bar:
  // [0..0.8] = 40%, [0.8..1.3] = 25%, [1.3..1.5] = 10%, [1.5..2.0] = 25%
  const pct = ratio !== null && ratio > 0 ? Math.min(Math.max((ratio / 2.0) * 100, 3), 97) : null;
  return (
    <div className={`ath-acwr-gauge is-${zone ?? "none"}`}>
      <div className="ath-acwr-gauge-head">
        <span className="ath-acwr-gauge-label">
          <Icon name="gauge" size={14} />
          {acwrChipText(ratio, locale)}
        </span>
        <span className="ath-acwr-gauge-scale tnum">
          {en ? "Optimal 0.8–1.3" : "甜蜜區 0.8–1.3"}
        </span>
      </div>
      <div className="ath-acwr-track" role="img" aria-label={acwrChipText(ratio, locale)}>
        <span className="ath-acwr-seg is-low" />
        <span className="ath-acwr-seg is-safe" />
        <span className="ath-acwr-seg is-high" />
        <span className="ath-acwr-seg is-alert" />
        {pct !== null && (
          <span
            className="ath-acwr-pin"
            style={{ "--pin-left": `${pct}%` } as React.CSSProperties}
          />
        )}
      </div>
    </div>
  );
}

export interface TodayHeroProps {
  vm: TodayViewModel;
  c: TodayCopy;
  locale: Locale;
  trainingSource: TrainingSource;
  onTrainingSource: (next: TrainingSource) => void;
  todaysAssignments: AssignedWorkout[];
  coachPaceLossPct: number;
  todayHasRecord: boolean;
  onOpenFeedback?: () => void;
}

export function TodayHero({
  vm,
  c,
  locale,
  trainingSource,
  onTrainingSource,
  todaysAssignments,
  coachPaceLossPct,
  todayHasRecord,
  onOpenFeedback,
}: TodayHeroProps) {
  const en = locale === "en";
  const coach = trainingSource === "coach";
  const { ratio, zone } = vm.acwr;

  return (
    <TiltCard className="ath-hero">
      {!vm.isRestDay && (
        <RoutePreview
          seedId={vm.activeCandidateId ?? vm.workout.title}
          structure={vm.workout.segments}
          distanceKm={vm.workout.distanceKm}
          locale={locale}
          variant="watermark"
        />
      )}
      <div className="ath-hero-top tilt-layer">
        <span className={`ath-hero-date-pill${coach ? " is-coach" : ""}`}>
          <Icon name={coach ? "assignment" : "activity"} size={14} />
          {coach ? c.assigned : c.plan}
        </span>

        <div className="ath-hero-source-switch">
          <Segmented
            value={trainingSource}
            onChange={onTrainingSource}
            options={[
              { value: "system" as const, label: c.systemSuggested },
              { value: "coach" as const, label: c.coachArranged },
            ]}
          />
        </div>
      </div>

      {coach ? (
        <CoachHeroBody assignments={todaysAssignments} c={c} locale={locale} onUseSystem={() => onTrainingSource("system")} />
      ) : vm.isRestDay ? (
        <RestHeroBody locale={locale} />
      ) : (
        <SystemHeroBody vm={vm} c={c} locale={locale} />
      )}

      <div className="ath-hero-chips tilt-layer">
        {coach
          ? coachPaceLossPct !== 0 && (
              <ClimatePill label={`${climateMomentLabel(null, locale)} ${c.weatherAdjustedPace}`} pace={null} extra={paceShiftText(coachPaceLossPct, locale)} />
            )
          : !vm.isRestDay && (
              <ClimatePill
                label={`${climateMomentLabel(vm.climate.heroSlot, locale)} ${c.weatherAdjustedPace}`}
                pace={paceShapeText(vm.climate.heroPace)}
                extra={paceShiftText(vm.climate.heroPct, locale)}
              />
            )}
      </div>

      <div className="tilt-layer">
        <AcwrZoneGauge ratio={ratio} zone={zone} locale={locale} />
      </div>

      <div className="ath-hero-actions tilt-layer">
        <Link className="ath-cta" to="/app/run">
          <Icon name="runner" size={18} />
          {c.liveRun}
        </Link>
        <Link className="btn btn-secondary" to="/app/log">
          <Icon name="shoe" size={17} />
          {c.log}
        </Link>
        <Link className="btn btn-secondary" to="/app/body">
          <Icon name="body-status" size={17} />
          {en ? "Body report" : "身體回報"}
        </Link>
        {onOpenFeedback && (
          <button type="button" className="btn btn-secondary" onClick={onOpenFeedback}>
            <Icon name="coach-note" size={17} />
            {en ? "Feedback" : "跑者回饋"}
          </button>
        )}
      </div>

      <p className="ath-hero-foot tilt-layer">{todayHasRecord ? c.recorded : c.missing}</p>
    </TiltCard>
  );
}
