import { Badge, Button, Card, SwitchRow } from "../../../components/ui.tsx";
import { useWorkspace } from "../../../state/WorkspaceContext.tsx";
import { useLocale } from "../../../state/LocaleContext.tsx";
import { Row, Stack } from "../../../components/Layout.tsx";
import { Text } from "../../../components/Text.tsx";

export function IntegrationSettings() {
  const { locale } = useLocale();
  const en = locale === "en";
  const { preferences, setPreference, garminActivities } = useWorkspace();

  return (
    <>
      <Card title={en ? "Device data" : "裝置資料"}>
        <SwitchRow
          title={en ? "Include device data" : "納入裝置資料"}
          description={en
            ? `Turning this on shows ${garminActivities.length} device-sourced records alongside your manual entries -- device load and manual load use different units, so they're always shown separately, never added together.`
            : `打開後會顯示 ${garminActivities.length} 筆裝置來源的紀錄，跟你的手動紀錄並列——裝置負荷跟手動負荷的單位不同，永遠分開呈現，不會相加。`}
          checked={preferences.garminSyncEnabled}
          onChange={(next) => setPreference("garminSyncEnabled", next)}
        />
      </Card>

      <Card
        title={en ? "LINE notifications" : "LINE 通知"}
        subtitle={en ? "Daily workout reminders are sent through LINE Push Message." : "每日課表提醒透過 LINE Push Message 發送。"}
      >
        <Row justify="between">
          <Stack gap={1}>
            <Text variant="label" as="div">{en ? "Connection status" : "連結狀態"}</Text>
            <Text variant="caption" as="div">{en ? "A LINE account is connected and can be disconnected at any time." : "已綁定 LINE 帳號，可隨時解除。"}</Text>
          </Stack>
          <Row gap={2}>
            <Badge tone="good" dot>
              {en ? "Connected" : "已連結"}
            </Badge>
            <Button size="sm">{en ? "Disconnect" : "解除連結"}</Button>
          </Row>
        </Row>
      </Card>
    </>
  );
}
