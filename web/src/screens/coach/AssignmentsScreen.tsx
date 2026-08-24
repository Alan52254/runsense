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
import { formatLocalDate } from "../../lib/format.ts";

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
      title="新增課表指派"
      description="指派給團隊裡目前狀態為 ACTIVE 的選手。"
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>取消</Button>
          <Button
            variant="primary"
            onClick={submit}
            disabled={submitting || !athleteId || !title.trim()}
          >
            {submitting ? "新增中…" : "新增指派"}
          </Button>
        </>
      }
    >
      <div className="stack">
        <Field label="選手" htmlFor="assign-athlete">
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
        <Field label="日期" htmlFor="assign-date">
          <input
            id="assign-date"
            className="input"
            type="date"
            value={localDate}
            onChange={(e) => setLocalDate(e.target.value)}
          />
        </Field>
        <Field label="內容" htmlFor="assign-title">
          <input
            id="assign-title"
            className="input"
            value={title}
            placeholder="例如：輕鬆有氧跑"
            onChange={(e) => setTitle(e.target.value)}
          />
        </Field>
        <Field label="時長（分鐘）" htmlFor="assign-duration">
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
        <Field label="強度標籤" htmlFor="assign-intensity">
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
  const { assignments, coachRoster, today, liveTeamId } = useWorkspace();
  const [range, setRange] = useState<Range>("today");
  const [showNewAssignment, setShowNewAssignment] = useState(false);

  const rows =
    range === "today" ? assignments.filter((a) => a.localDate === today) : assignments;

  const nameFor = (athleteId: string) =>
    coachRoster.find((a) => a.athleteId === athleteId)?.name ?? "已離隊的選手";

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">課表指派</h1>
          <p className="page-desc">
            安排團隊課表並追蹤狀態；只有選手分享訓練摘要後，才會顯示完成狀況。
          </p>
        </div>
      </div>

      <Card
        title={`${rows.length} 筆指派`}
        actions={
          <Segmented
            value={range}
            onChange={setRange}
            options={[
              { value: "today", label: "今天" },
              { value: "all", label: "全部" },
            ]}
          />
        }
        flush
      >
        {rows.length === 0 ? (
          <EmptyState icon="assignment" title="今天沒有指派任何課表" />
        ) : (
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>選手</th>
                  <th>日期</th>
                  <th>內容</th>
                  <th className="num">時長</th>
                  <th>強度</th>
                  <th>狀態</th>
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
                    <td className="muted">{formatLocalDate(assignment.localDate)}</td>
                    <td style={{ fontWeight: 550 }}>{assignment.title}</td>
                    <td className="num">{assignment.durationMinutes} 分</td>
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
                          ? "已完成"
                          : assignment.status === "MISSED"
                            ? "未完成"
                            : "已排定"}
                      </Badge>
                    </td>
                    <td style={{ textAlign: "right" }}>
                      <Link
                        className="btn btn-ghost btn-sm"
                        to={`/coach/athletes/${assignment.athleteId}`}
                      >
                        查看選手
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Notice tone="neutral" icon="info" title="指派課表不等於取得資料存取權">
        你可以指派課表給團隊裡的任何有效成員，但能不能看到他的訓練負荷或身體狀況，
        取決於該名選手當下的授權設定，兩者互不影響。
      </Notice>

      <Card title="Phase 2 才會有的功能">
        <div className="stack-sm">
          <p style={{ fontSize: 13, lineHeight: 1.75 }}>
            把結構化課表推送到選手的手錶上，目前不在範圍內。啟動自訂 Connect IQ App 之前，
            必須先做架構驗證，確認 Garmin 官方 Training API 是否已經足以滿足課表推送需求；
            如果足夠，就不開發自訂 App。
          </p>
          <div className="row" style={{ gap: 6, flexWrap: "wrap" }}>
            <Badge>手錶／BLE 功能：Phase 2</Badge>
            <Badge>即時 GPS 錄跑：Phase 2</Badge>
          </div>
        </div>
      </Card>

      <div className="row">
        {apiConfigured && liveTeamId ? (
          <Button size="sm" variant="primary" onClick={() => setShowNewAssignment(true)}>
            新增指派
          </Button>
        ) : (
          <Button size="sm" variant="secondary" disabled>
            新增指派（示範資料不開放編輯）
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
