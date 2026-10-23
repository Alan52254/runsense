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

export function TodayHero({
  vm, c, locale, trainingSource, onTrainingSource, todaysAssignments, coachPaceLossPct, todayHasRecord,
}: {
  vm: TodayViewModel;
  c: TodayCopy;
  locale: Locale;
  trainingSource: TrainingSource;
  onTrainingSource: (next: TrainingSource) => void;
  todaysAssignments: AssignedWorkout[];
  coachPaceLossPct: number;
  todayHasRecord: boolean;
}) {
  const en = locale === "en";
  const coach = trainingSource === "coach";
  const { ratio, zone } = vm.acwr;

  return (
    <TiltCard className="ath-hero">
      <div className="ath-hero-top tilt-layer">
        <span className="ath-eyebrow">
          <Icon name="activity" size={15} />
          {c.plan}
        </span>
        <Segmented
          value={trainingSource}
          onChange={onTrainingSource}
          options={[
            { value: "system" as const, label: c.systemSuggested },
            { value: "coach" as const, label: c.coachArranged },
          ]}
        />
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
        <span className={`ath-acwr-chip is-${zone ?? "none"}`}>
          <Icon name="gauge" size={14} />
          {acwrChipText(ratio, locale)}
        </span>
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
      </div>

      <p className="ath-hero-foot tilt-layer">{todayHasRecord ? c.recorded : c.missing}</p>
    </TiltCard>
  );
}
