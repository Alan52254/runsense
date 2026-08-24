import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Avatar,
  Badge,
  Button,
  Card,
  EmptyState,
  Field,
  Modal,
  Notice,
  Segmented,
} from "../../components/ui.tsx";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import { apiConfigured } from "../../data/apiClient.ts";
import { useLocale } from "../../state/LocaleContext.tsx";

type Range = "today" | "all";

function NewAssignmentModal({
  open,
  onClose,
  teamId,
  activeAthletes,
  today,
}: {
  open: boolean;
  onClose: () => void;
  teamId: string;
  activeAthletes: { athleteId: string; name: string }[];
  today: string;
}) {
  const { locale } = useLocale();
  const en = locale === "en";
  const { createAssignment } = useWorkspace();
  const [athleteId, setAthleteId] = useState(activeAthletes[0]?.athleteId ?? "");
  const [localDate, setLocalDate] = useState(today);
  const [title, setTitle] = useState("");
  const [durationMinutes, setDurationMinutes] = useState(30);
  const [intensityLabel, setIntensityLabel] = useState("RPE 3-4");
  const [submitting, setSubmitting] = useState(false);

  async function submit() {
    if (!athleteId || !title.trim()) return;
    setSubmitting(true);
    const ok = await createAssignment({
      teamId,
      athleteId,
      localDate,
      title: title.trim(),
      durationMinutes,
      intensityLabel,
    });
    setSubmitting(false);
    if (ok) {
      setTitle("");
      onClose();
    }
  }

  return (
    <Modal
      open={open}
      title={en ? "New workout assignment" : "新增課表指派"}
      description={en ? "Assign a workout to an athlete whose team status is ACTIVE." : "指派給團隊裡目前狀態為 ACTIVE 的選手。"}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>{en ? "Cancel" : "取消"}</Button>
          <Button
            variant="primary"
            onClick={submit}
            disabled={submitting || !athleteId || !title.trim()}
          >
            {submitting ? (en ? "Adding…" : "新增中…") : (en ? "Add assignment" : "新增指派")}
          </Button>
        </>
      }
    >
      <div className="stack">
        <Field label={en ? "Athlete" : "選手"} htmlFor="assign-athlete">
          <select
            id="assign-athlete"
            className="input"
            value={athleteId}
            onChange={(e) => setAthleteId(e.target.value)}
          >
            {activeAthletes.map((a) => (
              <option key={a.athleteId} value={a.athleteId}>
                {a.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label={en ? "Date" : "日期"} htmlFor="assign-date">
          <input
            id="assign-date"
            className="input"
            type="date"
            value={localDate}
            onChange={(e) => setLocalDate(e.target.value)}
          />
        </Field>
        <Field label={en ? "Workout" : "內容"} htmlFor="assign-title">
          <input
            id="assign-title"
            className="input"
            value={title}
            placeholder={en ? "e.g. Easy aerobic run" : "例如：輕鬆有氧跑"}
            onChange={(e) => setTitle(e.target.value)}
          />
        </Field>
        <Field label={en ? "Duration (minutes)" : "時長（分鐘）"} htmlFor="assign-duration">
          <input
            id="assign-duration"
            className="input"
            type="number"
            min={1}
            max={600}
            value={durationMinutes}
            onChange={(e) => setDurationMinutes(Number(e.target.value))}
          />
        </Field>
        <Field label={en ? "Intensity label" : "強度標籤"} htmlFor="assign-intensity">
          <input
            id="assign-intensity"
            className="input"
            value={intensityLabel}
            onChange={(e) => setIntensityLabel(e.target.value)}
          />
        </Field>
      </div>
    </Modal>
  );
}

export function AssignmentsScreen() {
  const { locale } = useLocale();
  const en = locale === "en";
  const { assignments, coachRoster, today, liveTeamId } = useWorkspace();
  const [range, setRange] = useState<Range>("today");
  const [showNewAssignment, setShowNewAssignment] = useState(false);

  const rows =
    range === "today" ? assignments.filter((a) => a.localDate === today) : assignments;

  const nameFor = (athleteId: string) =>
    coachRoster.find((a) => a.athleteId === athleteId)?.name ?? (en ? "Former team member" : "已離隊的選手");

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">{en ? "Workout assignments" : "課表指派"}</h1>
          <p className="page-desc">
            {en ? "Plan team workouts and track their status. Completion is shown only when the athlete shares training summaries." : "安排團隊課表並追蹤狀態；只有選手分享訓練摘要後，才會顯示完成狀況。"}
          </p>
        </div>
      </div>

      <Card
        title={en ? `${rows.length} assignments` : `${rows.length} 筆指派`}
        actions={
          <Segmented
            value={range}
            onChange={setRange}
            options={[
              { value: "today", label: en ? "Today" : "今天" },
              { value: "all", label: en ? "All" : "全部" },
            ]}
          />
        }
        flush
      >
        {rows.length === 0 ? (
          <EmptyState icon="assignment" title={range === "today" ? (en ? "No workouts assigned today" : "今天沒有指派任何課表") : (en ? "No assignments" : "沒有課表指派")} />
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>{en ? "Athlete" : "選手"}</th>
                  <th>{en ? "Date" : "日期"}</th>
                  <th>{en ? "Workout" : "內容"}</th>
                  <th className="num">{en ? "Duration" : "時長"}</th>
                  <th>{en ? "Intensity" : "強度"}</th>
                  <th>{en ? "Status" : "狀態"}</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {rows.map((assignment) => (
                  <tr key={assignment.id}>
                    <td>
                      <div className="row" style={{ gap: 10 }}>
                        <Avatar name={nameFor(assignment.athleteId)} />
                        <span style={{ fontWeight: 560 }}>
                          {nameFor(assignment.athleteId)}
                        </span>
                      </div>
                    </td>
                    <td className="muted">{new Intl.DateTimeFormat(locale, { timeZone: "UTC", month: "numeric", day: "numeric", weekday: "short" }).format(new Date(`${assignment.localDate}T00:00:00Z`))}</td>
                    <td style={{ fontWeight: 550 }}>{assignment.title}</td>
                    <td className="num">{assignment.durationMinutes} {en ? "min" : "分"}</td>
                    <td className="muted">{assignment.intensityLabel}</td>
                    <td>
                      <Badge
                        tone={
                          assignment.status === "COMPLETED"
                            ? "good"
                            : assignment.status === "MISSED"
                              ? "warning"
                              : "neutral"
                        }
                        dot
                      >
                        {assignment.status === "COMPLETED"
                          ? (en ? "Completed" : "已完成")
                          : assignment.status === "MISSED"
                            ? (en ? "Missed" : "未完成")
                            : (en ? "Scheduled" : "已排定")}
                      </Badge>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <Link
                        className="btn btn-ghost btn-sm"
                        to={`/coach/athletes/${assignment.athleteId}`}
                      >
                        {en ? "View athlete" : "查看選手"}
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Notice tone="neutral" icon="info" title={en ? "Assigning a workout does not grant data access" : "指派課表不等於取得資料存取權"}>
        {en ? "You can assign workouts to any active team member, but access to training load or body status still follows that athlete's current consent. The two permissions are independent." : "你可以指派課表給團隊裡的任何有效成員，但能不能看到他的訓練負荷或身體狀況，取決於該名選手當下的授權設定，兩者互不影響。"}
      </Notice>

      <Card title={en ? "Planned for Phase 2" : "Phase 2 才會有的功能"}>
        <div className="stack-sm">
          <p style={{ fontSize: 13, lineHeight: 1.75 }}>
            {en ? "Pushing structured workouts to an athlete's watch is currently out of scope. Before starting a custom Connect IQ app, the team must verify whether Garmin's official Training API already supports the required workflow. If it does, no custom app will be built." : "把結構化課表推送到選手的手錶上，目前不在範圍內。啟動自訂 Connect IQ App 之前，必須先做架構驗證，確認 Garmin 官方 Training API 是否已經足以滿足課表推送需求；如果足夠，就不開發自訂 App。"}
          </p>
          <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
            <Badge>{en ? "Watch / BLE features: Phase 2" : "手錶／BLE 功能：Phase 2"}</Badge>
            <Badge>{en ? "Live GPS recording: Phase 2" : "即時 GPS 錄跑：Phase 2"}</Badge>
          </div>
        </div>
      </Card>

      <div className="row">
        {apiConfigured && liveTeamId ? (
          <Button size="sm" variant="primary" onClick={() => setShowNewAssignment(true)}>
            {en ? "Add assignment" : "新增指派"}
          </Button>
        ) : (
          <Button size="sm" variant="secondary" disabled>
            {en ? "Add assignment (demo data is read-only)" : "新增指派（示範資料不開放編輯）"}
          </Button>
        )}
      </div>

      {apiConfigured && liveTeamId && (
        <NewAssignmentModal
          open={showNewAssignment}
          onClose={() => setShowNewAssignment(false)}
          teamId={liveTeamId}
          activeAthletes={coachRoster
            .filter((a) => a.status === "ACTIVE")
            .map((a) => ({ athleteId: a.athleteId, name: a.name }))}
          today={today}
        />
      )}
    </>
  );
}
