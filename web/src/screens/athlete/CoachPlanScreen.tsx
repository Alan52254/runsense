/* The athlete's upcoming coach-assigned workouts, day by day (today
 * onwards). Read-only: the coach schedules through the team chat or the
 * coach workspace; the list refreshes on its own when that happens (see
 * refreshAssignments in WorkspaceContext). */

import { Badge, Card, EmptyState } from "../../components/ui.tsx";
import { WorkoutStructureView, assignmentSegmentToDisplay } from "../../components/workoutStructure.tsx";
import { estimateWorkoutTotals, formatEstimatedKmLabel } from "../../lib/paceCalc.ts";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import { useLocale } from "../../state/LocaleContext.tsx";
import type { AssignedWorkout } from "../../lib/types.ts";

const WEEKDAY_ZH = "日一二三四五六";
const WEEKDAY_EN = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function dateLabel(iso: string, en: boolean): string {
  const d = new Date(`${iso}T00:00:00`);
  return en
    ? `${d.getMonth() + 1}/${d.getDate()} (${WEEKDAY_EN[d.getDay()]})`
    : `${d.getMonth() + 1}/${d.getDate()}（${WEEKDAY_ZH[d.getDay()]}）`;
}

function WorkoutBlock({ workout, en }: { workout: AssignedWorkout; en: boolean }) {
  const structure = workout.structure ?? [];
  const estimate = estimateWorkoutTotals(structure);
  const untracked = workout.tracked === false;
  const status = untracked
    ? { text: en ? "Not tracked" : "不追蹤", tone: "neutral" as const }
    : workout.status === "COMPLETED"
      ? { text: en ? "Completed" : "已完成", tone: "good" as const }
      : workout.status === "MISSED"
        ? { text: en ? "Missed" : "未完成", tone: "warning" as const }
        : { text: en ? "Scheduled" : "已排定", tone: "neutral" as const };
  return (
    <div className="coach-plan-workout">
      <div className="row-between" style={{ alignItems: "flex-start", gap: 10 }}>
        <div style={{ minWidth: 0 }}>
          <div className="coach-plan-title">{workout.title}</div>
          <div className="field-hint">
            {workout.intensityLabel}
            {!untracked && ` · ${en ? "about" : "約"} ${workout.durationMinutes} ${en ? "min" : "分鐘"}`}
            {!untracked && estimate.totalMeters > 0 && ` · ${formatEstimatedKmLabel(estimate)}`}
          </div>
        </div>
        <Badge tone={status.tone}>{status.text}</Badge>
      </div>
      {/* untracked: the session itself; a run: the coach's reasons for it (weather window, a niggle, ...) */}
      {workout.notes && <pre className="coach-plan-notes">{workout.notes}</pre>}
      {structure.length > 0 && (
        <WorkoutStructureView
          segments={structure.map((segment, index) => assignmentSegmentToDisplay(segment, index, en ? "en" : "zh-TW"))}
          heading={en ? "Workout structure" : "課表結構"}
        />
      )}
    </div>
  );
}

export function CoachPlanScreen() {
  const { myAssignedWorkouts, today } = useWorkspace();
  const { locale } = useLocale();
  const en = locale === "en";

  const upcoming = myAssignedWorkouts
    .filter((w) => w.localDate >= today)
    .sort((a, b) => a.localDate.localeCompare(b.localDate));
  const byDate = new Map<string, AssignedWorkout[]>();
  for (const w of upcoming) byDate.set(w.localDate, [...(byDate.get(w.localDate) ?? []), w]);

  return (
    <div className="stack">
      <div className="page-head">
        <div>
          <h1 className="page-title">{en ? "Coach plan" : "教練課表"}</h1>
          <p className="page-desc">
            {en
              ? "Workouts your coach has scheduled for you, from today on. New ones appear here as soon as your coach confirms them."
              : "教練幫你安排的課表（今天起）。教練在聊天室確認排課後，這裡會自動出現。"}
          </p>
        </div>
      </div>

      {byDate.size === 0 ? (
        <Card>
          <EmptyState
            icon="assignment"
            title={en ? "No upcoming workouts from your coach" : "教練還沒有安排之後的課表"}
            description={en ? "When your coach schedules training, it shows up here." : "教練排好課表後會出現在這裡。"}
          />
        </Card>
      ) : (
        [...byDate.entries()].map(([date, workouts]) => (
          <Card
            key={date}
            title={dateLabel(date, en)}
            actions={date === today ? <Badge tone="accent">{en ? "Today" : "今天"}</Badge> : undefined}
          >
            <div className="stack-sm">
              {workouts.map((w) => <WorkoutBlock key={w.id} workout={w} en={en} />)}
            </div>
          </Card>
        ))
      )}
    </div>
  );
}
