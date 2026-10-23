import { useState } from "react";
import { Surface } from "../../../components/Surface.tsx";
import { Badge } from "../../../components/ui.tsx";
import { WorkoutStructureView, assignmentSegmentToDisplay } from "../../../components/workoutStructure.tsx";
import { estimateWorkoutTotals, formatEstimatedKmLabel } from "../../../lib/paceCalc.ts";
import type { AssignedWorkout } from "../../../lib/types.ts";
import type { TodayCopy } from "./todayCopy.ts";
import { Row, Stack } from "../../../components/Layout.tsx";
import { Text } from "../../../components/Text.tsx";

type Locale = "zh-TW" | "en";

/** One upcoming coach assignment, collapsed until asked for its blocks. */
function AssignedWorkoutRow({ workout, locale, statusLabel }: { workout: AssignedWorkout; locale: Locale; statusLabel: string }) {
  const [expanded, setExpanded] = useState(false);
  const en = locale === "en";
  const structure = workout.structure ?? [];
  const estimate = estimateWorkoutTotals(structure);

  return (
    <Stack gap={2} className="ath-assigned">
      <Row justify="between" align="start" gap={3}>
        <Stack gap={1}>
          <Text variant="label" as="div">{workout.title}</Text>
          <Text variant="caption" as="div">
            {workout.tracked === false
              ? <>{workout.localDate} · {workout.intensityLabel}</>
              : <>{workout.localDate} · {workout.durationMinutes} {en ? "min" : "分"} · {workout.intensityLabel}
                {estimate.totalMeters > 0 && ` · ${formatEstimatedKmLabel(estimate)}`}</>}
          </Text>
          {workout.notes && (
            <Text variant="caption" as="div" className="ath-assigned__notes">{workout.notes}</Text>
          )}
        </Stack>
        <Row gap={2}>
          {structure.length > 0 && (
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => setExpanded((v) => !v)}>
              {expanded ? (en ? "Hide" : "收合") : (en ? "Workout details" : "課表內容")}
            </button>
          )}
          <Badge tone={workout.tracked !== false && workout.status === "MISSED" ? "warning" : "neutral"}>
            {workout.tracked === false ? (en ? "Not tracked" : "不追蹤") : statusLabel}
          </Badge>
        </Row>
      </Row>
      {expanded && structure.length > 0 && (
        <WorkoutStructureView
          segments={structure.map((segment, index) => assignmentSegmentToDisplay(segment, index, locale))}
          heading={en ? "Workout structure" : "課表結構"}
        />
      )}
    </Stack>
  );
}

export function UpcomingAssignments({ workouts, c, locale }: { workouts: AssignedWorkout[]; c: TodayCopy; locale: Locale }) {
  if (workouts.length === 0) return null;
  const statusLabel = { SCHEDULED: c.assignedScheduled, COMPLETED: c.assignedCompleted, MISSED: c.assignedMissed } as const;
  return (
    <Surface as="details" className="ath-panel ath-disclosure">
      <summary className="ath-disclosure-summary">
        <span>{c.assigned}</span>
        <span className="ath-disclosure-hint">{workouts.length} {locale === "en" ? "scheduled" : "筆安排"}</span>
      </summary>
      <div className="ath-disclosure-content">
        <p className="ath-panel-sub">{c.assignedSub}</p>
        <div className="stack-sm">
          {workouts.map((w) => (
            <AssignedWorkoutRow key={w.id} workout={w} locale={locale} statusLabel={statusLabel[w.status]} />
          ))}
        </div>
      </div>
    </Surface>
  );
}
