import { useState } from "react";
import { Badge, Button, Card, Field, Notice } from "../../../components/ui.tsx";
import { useWorkspace } from "../../../state/WorkspaceContext.tsx";
import { useLocale } from "../../../state/LocaleContext.tsx";

const TIMEZONES = [
  "Asia/Taipei",
  "Asia/Tokyo",
  "Asia/Singapore",
  "Europe/London",
  "America/Los_Angeles",
];

export function ProfileSettings() {
  const { locale } = useLocale();
  const en = locale === "en";
  const { athlete, updateProfile, today } = useWorkspace();

  const [timezone, setTimezone] = useState(athlete.timezone);
  const [city, setCity] = useState(athlete.city);
  const [sex, setSex] = useState<"male" | "female" | "">(athlete.sex ?? "");

  const sexDirty = sex !== "" && sex !== athlete.sex;
  const dirty = timezone !== athlete.timezone || city !== athlete.city || sexDirty;

  return (
    <>
      <Card
        title={en ? "Basic information" : "基本資料"}
        subtitle={en ? "You can correct your personal information at any time." : "你可以隨時更正自己的個人資料。"}
      >
        <div className="stack">
          <div className="grid-2">
            <Field label={en ? "Name" : "姓名"} htmlFor="p-name">
              <input id="p-name" className="input" defaultValue={athlete.name} />
            </Field>
            <Field
              label={en ? "Email" : "電子郵件"}
              htmlFor="p-email"
              hint={en ? "Changing your email requires verification before it takes effect." : "更換 email 需要重新完成驗證才能生效。"}
            >
              <input id="p-email" className="input" defaultValue={athlete.email} />
            </Field>
          </div>

          <div className="grid-2">
            <Field
              label={en ? "Time zone" : "時區"}
              htmlFor="p-tz"
              hint={en ? "Defines the boundary of today for daily training load and scheduled notifications." : "決定「今天」的邊界，用於訓練負荷分日與排程推播。"}
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
              label={en ? "City" : "所在城市"}
              htmlFor="p-city"
              hint={en ? "Used for climate-adjusted pace. RunSense does not use live location -- type the city you actually run in." : "氣候等效配速的資料來源。系統不使用即時定位，請直接輸入你實際所在的城市。"}
            >
              <input
                id="p-city"
                className="input"
                value={city}
                placeholder={en ? "e.g. Tokyo" : "例如：臺北市"}
                onChange={(e) => setCity(e.target.value)}
              />
            </Field>
          </div>

          <Field
            label={en ? "Sex" : "性別"}
            htmlFor="p-sex"
            hint={
              en
                ? "Used for the climate-equivalent pace estimate (El Helou et al. 2012, PLOS ONE -- men and women have separately fitted curves). Left unset, that estimate averages both curves instead of guessing."
                : "用於氣候等效配速估算（採用 El Helou et al. 2012, PLOS ONE 男女分開回歸的曲線）。未設定時，估算會取男女曲線的平均值，而不是隨意猜測。"
            }
          >
            <select id="p-sex" className="input" value={sex} onChange={(e) => setSex(e.target.value as "male" | "female" | "")}>
              {sex === "" && <option value="">{en ? "Not set" : "未設定"}</option>}
              <option value="male">{en ? "Male" : "男"}</option>
              <option value="female">{en ? "Female" : "女"}</option>
            </select>
          </Field>

          <div className="row-between">
            <span className="field-hint">
              {en
                ? `Today is ${today} in ${athlete.timezone}, independent of the server time zone.`
                : `目前「今天」是 ${today}（依 ${athlete.timezone} 換算，不是伺服器時區）。`}
            </span>
            <Button
              variant="primary"
              disabled={!dirty}
              onClick={() => void updateProfile({ timezone, city, ...(sex !== "" && sexDirty ? { sex } : {}) })}
            >
              {en ? "Save changes" : "儲存變更"}
            </Button>
          </div>
        </div>
      </Card>

      <Card title={en ? "Time zones and date boundaries" : "時區與日期邊界"}>
        <div className="stack-sm">
          <p style={{ fontSize: 13, lineHeight: 1.75 }}>
            {en
              ? "Event timestamps are stored in UTC while your time zone is recorded separately. Today is derived from UTC and your time zone, never from the server's time zone."
              : "事件時間一律以 UTC 儲存，你的時區獨立記錄。「今天」是由 UTC 加上你的時區換算出來的，不會直接拿伺服器所在時區判斷。"}
          </p>
          <Notice tone="neutral" icon="info">
            {en
              ? "Changing your time zone affects only new records. Existing records keep their original timezone_snapshot, so moving does not rewrite historical training dates."
              : "變更時區只影響之後建立的紀錄。既有紀錄保留當時的 timezone_snapshot，所以歷史的日期歸屬不會因為你搬家而被改寫。"}
          </Notice>
        </div>
      </Card>

      <Card title={en ? "Age declaration" : "年齡聲明"}>
        <div className="row-between">
          <div>
            <div className="row" style={{ gap: 8 }}>
              <Badge tone="good" dot>
                {en ? "Declared age 18 or older" : "已聲明年滿 18 歲"}
              </Badge>
            </div>
            <p className="field-hint" style={{ marginTop: 6 }}>
              {en ? "Declared " : "聲明時間 "}
              {new Intl.DateTimeFormat(locale, { timeZone: athlete.timezone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(athlete.ageDeclaredAtUtc))}
            </p>
          </div>
          <p className="field-hint" style={{ maxWidth: "44ch", textAlign: "right" }}>
            {en
              ? "The system stores only this declaration and timestamp, not your full date of birth. Phase 1 registration is available only to users age 18 or older."
              : "系統只保存這個勾選與時間戳，不保存完整出生年月日。Phase 1 僅開放年滿 18 歲的使用者註冊。"}
          </p>
        </div>
      </Card>
    </>
  );
}
