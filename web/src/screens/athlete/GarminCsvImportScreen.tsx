import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, Card, EmptyState } from "../../components/ui.tsx";
import { Icon } from "../../components/Icon.tsx";
import { useLocale } from "../../state/LocaleContext.tsx";

interface GarminLap {
  number: string;
  time: string;
  distance: number;
  pace: string;
  heartRate: string;
  power: string;
  cadence: string;
  movingTime: string;
  kind: "work" | "recovery";
}

interface ImportedActivity {
  fileName: string;
  laps: GarminLap[];
}

function parseCsvLine(line: string): string[] {
  const values: string[] = [];
  let value = "";
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (character === '"') {
      if (quoted && line[index + 1] === '"') {
        value += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (character === "," && !quoted) {
      values.push(value.trim());
      value = "";
    } else {
      value += character;
    }
  }
  values.push(value.trim());
  return values;
}

function parseGarminCsv(text: string): GarminLap[] {
  const lines = text.replace(/^\uFEFF/, "").split(/\r?\n/).filter(Boolean);
  if (lines.length < 2) throw new Error("CSV has no lap rows");
  const headers = parseCsvLine(lines[0]);
  const column = (name: string) => headers.indexOf(name);
  const lapColumn = column("計圈");
  const timeColumn = column("時間");
  const distanceColumn = column("距離 公尺");
  const paceColumn = column("平均配速 分/公里");
  const heartRateColumn = column("平均心率 bpm");
  const powerColumn = column("平均功率 瓦");
  const cadenceColumn = column("平均步頻 每分鐘步數");
  const movingTimeColumn = column("移動時間");
  if ([lapColumn, timeColumn, distanceColumn].some((value) => value < 0)) {
    throw new Error("Unsupported Garmin CSV columns");
  }

  return lines.slice(1).flatMap((line) => {
    const values = parseCsvLine(line);
    const number = values[lapColumn];
    const distance = Number(values[distanceColumn]);
    if (!number || !Number.isFinite(distance) || number === "摘要資訊") return [];
    return [{
      number,
      time: values[timeColumn] ?? "--",
      distance,
      pace: values[paceColumn] ?? "--",
      heartRate: values[heartRateColumn] ?? "--",
      power: values[powerColumn] ?? "--",
      cadence: values[cadenceColumn] ?? "--",
      movingTime: values[movingTimeColumn] ?? "--",
      kind: distance >= 350 ? "work" : "recovery",
    }];
  });
}

export function GarminCsvImportScreen() {
  const { locale } = useLocale();
  const en = locale === "en";
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [activities, setActivities] = useState<ImportedActivity[]>([]);
  const [error, setError] = useState<string | null>(null);

  async function importFiles(files: FileList | null) {
    if (!files?.length) return;
    setError(null);
    const imported: ImportedActivity[] = [];
    for (const file of Array.from(files)) {
      try {
        imported.push({ fileName: file.name, laps: parseGarminCsv(await file.text()) });
      } catch (reason) {
        setError(`${file.name}: ${reason instanceof Error ? reason.message : "Unable to parse CSV"}`);
      }
    }
    setActivities((current) => [...current, ...imported]);
  }

  return (
    <>
      <div className="page-head">
        <div>
          <h1 className="page-title">{en ? "Garmin CSV Import" : "Garmin CSV 匯入"}</h1>
          <p className="page-desc">
            {en ? "Review every work and recovery lap before saving it to your training history." : "先確認每個工作段與恢復段，再寫入你的訓練歷程。"}
          </p>
        </div>
        <Link className="btn btn-secondary" to="/app/history">
          <Icon name="history" size={16} />
          {en ? "Back to history" : "返回歷程"}
        </Link>
      </div>

      <Card title={en ? "Choose Garmin CSV files" : "選擇 Garmin CSV 檔案"} subtitle={en ? "Multiple files can be selected at once. Files stay in this browser for now." : "可以一次選取多個檔案。目前資料只留在這個瀏覽器頁面。"}>
        <input ref={inputRef} type="file" accept=".csv,text/csv" multiple hidden onChange={(event) => void importFiles(event.target.files)} />
        <Button variant="primary" icon="download" onClick={() => inputRef.current?.click()}>
          {en ? "Select CSV files" : "選擇 CSV 檔案"}
        </Button>
        {error && <p className="field-error" style={{ marginTop: 12 }}>{error}</p>}
      </Card>

      {activities.length === 0 ? (
        <EmptyState icon="activity" title={en ? "No CSV imported" : "尚未匯入 CSV"} description={en ? "Export the activity CSV from Garmin Connect, then choose it here." : "先從 Garmin Connect 匯出活動 CSV，再從這裡選取。"} />
      ) : activities.map((activity) => (
        <Card key={`${activity.fileName}-${activity.laps.length}`} title={activity.fileName} subtitle={en ? `${activity.laps.length} laps` : `${activity.laps.length} 個計圈`} flush>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr>
                  <th>{en ? "Lap" : "計圈"}</th>
                  <th>{en ? "Type" : "類型"}</th>
                  <th className="num">{en ? "Distance" : "距離"}</th>
                  <th className="num">{en ? "Time" : "秒數"}</th>
                  <th className="num">{en ? "Pace" : "配速"}</th>
                  <th className="num">HR</th>
                  <th className="num">{en ? "Power" : "功率"}</th>
                  <th className="num">{en ? "Cadence" : "步頻"}</th>
                </tr>
              </thead>
              <tbody>
                {activity.laps.map((lap) => (
                  <tr key={`${activity.fileName}-${lap.number}`}>
                    <td>{lap.number}</td>
                    <td><Badge tone={lap.kind === "work" ? "accent" : "neutral"}>{lap.kind === "work" ? (en ? "Work" : "工作段") : (en ? "Recovery" : "恢復段")}</Badge></td>
                    <td className="num">{lap.distance} m</td>
                    <td className="num">{lap.time}</td>
                    <td className="num">{lap.pace}</td>
                    <td className="num">{lap.heartRate}</td>
                    <td className="num">{lap.power} W</td>
                    <td className="num">{lap.cadence}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      ))}
    </>
  );
}