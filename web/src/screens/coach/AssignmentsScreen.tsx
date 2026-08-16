import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Avatar,
  Badge,
  Button,
  Card,
  EmptyState,
  Notice,
  Segmented,
} from "../../components/ui.tsx";
import { useWorkspace } from "../../state/WorkspaceContext.tsx";
import { formatLocalDate } from "../../lib/format.ts";

type Range = "today" | "all";

export function AssignmentsScreen() {
  const { assignments, coachRoster, today } = useWorkspace();
  const [range, setRange] = useState<Range>("today");

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
            assigned_workouts 是團隊擁有的資料。指派紀錄不需要選手的資料分享授權，
            但完成狀況要靠選手的訓練摘要授權才看得到。
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
        <Button size="sm" variant="secondary" disabled>
          新增指派（示範資料不開放編輯）
        </Button>
      </div>
    </>
  );
}
