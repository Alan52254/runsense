import { useState } from "react";
import { Badge, Button, Card, Field, Notice } from "../../../components/ui.tsx";
import { useWorkspace } from "../../../state/WorkspaceContext.tsx";
import { formatInstant } from "../../../lib/format.ts";

const TIMEZONES = [
  "Asia/Taipei",
  "Asia/Tokyo",
  "Asia/Singapore",
  "Europe/London",
  "America/Los_Angeles",
];

const CITIES = ["臺北市", "新北市", "臺中市", "高雄市", "東京", "倫敦"];

export function ProfileSettings() {
  const { athlete, updateProfile, today } = useWorkspace();

  const [timezone, setTimezone] = useState(athlete.timezone);
  const [city, setCity] = useState(athlete.city);

  const dirty = timezone !== athlete.timezone || city !== athlete.city;

  return (
    <>
      <Card
        title="基本資料"
        subtitle="你可以隨時更正自己的個人資料。"
        reqTags={["REQ-PRIV-002"]}
      >
        <div className="stack">
          <div className="grid-2">
            <Field label="姓名" htmlFor="p-name">
              <input id="p-name" className="input" defaultValue={athlete.name} />
            </Field>
            <Field
              label="電子郵件"
              htmlFor="p-email"
              hint="更換 email 需要重新完成驗證才能生效。"
            >
              <input id="p-email" className="input" defaultValue={athlete.email} />
            </Field>
          </div>

          <div className="grid-2">
            <Field
              label="時區"
              htmlFor="p-tz"
              hint="決定「今天」的邊界，用於訓練負荷分日與排程推播。"
            >
              <select
                id="p-tz"
                className="input"
                value={timezone}
                onChange={(e) => setTimezone(e.target.value)}
              >
                {TIMEZONES.map((tz) => (
                  <option key={tz}>{tz}</option>
                ))}
              </select>
            </Field>

            <Field
              label="所在城市"
              htmlFor="p-city"
              hint="氣候等效配速的資料來源。系統不使用即時定位。"
            >
              <select
                id="p-city"
                className="input"
                value={city}
                onChange={(e) => setCity(e.target.value)}
              >
                {CITIES.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
            </Field>
          </div>

          <div className="row-between">
            <span className="field-hint">
              目前「今天」是 {today}（依 {athlete.timezone} 換算，不是伺服器時區）。
            </span>
            <Button
              variant="primary"
              disabled={!dirty}
              onClick={() => void updateProfile({ timezone, city })}
            >
              儲存變更
            </Button>
          </div>
        </div>
      </Card>

      <Card title="時區與日期邊界" reqTags={["REQ-TZ-001"]}>
        <div className="stack-sm">
          <p style={{ fontSize: 13, lineHeight: 1.75 }}>
            事件時間一律以 UTC 儲存，你的時區獨立記錄。「今天」是由 UTC 加上你的時區換算出來的，
            不會直接拿伺服器所在時區判斷。
          </p>
          <Notice tone="neutral" icon="info">
            變更時區只影響之後建立的紀錄。既有紀錄保留當時的 timezone_snapshot，
            所以歷史的日期歸屬不會因為你搬家而被改寫。
          </Notice>
        </div>
      </Card>

      <Card title="年齡聲明" reqTags={["REQ-AGE-001"]}>
        <div className="row-between">
          <div>
            <div className="row" style={{ gap: 8 }}>
              <Badge tone="good" dot>
                已聲明年滿 18 歲
              </Badge>
            </div>
            <p className="field-hint" style={{ marginTop: 6 }}>
              聲明時間 {formatInstant(athlete.ageDeclaredAtUtc, athlete.timezone)}
            </p>
          </div>
          <p className="field-hint" style={{ maxWidth: "44ch", textAlign: "right" }}>
            系統只保存這個勾選與時間戳，不保存完整出生年月日。Phase 1 僅開放年滿 18 歲的使用者註冊。
          </p>
        </div>
      </Card>
    </>
  );
}
