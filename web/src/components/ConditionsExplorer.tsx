import { useEffect, useRef, useState } from "react";
import { Card, Badge, Button, Notice } from "./ui.tsx";
import { evaluateTrainingPlan } from "../data/apiClient.ts";
import type { TrainingPlanWireResponse } from "../data/apiClient.ts";
import { useAuth } from "../state/AuthContext.tsx";
import { useLocale } from "../state/LocaleContext.tsx";
import { conditionsCostLabel, personalisationLabel, planTypeLabel } from "../lib/planLabels.ts";

/** Explore a different day's conditions.
 *
 *  The Athlete states conditions; RunSense works the day out against them
 *  using exactly the same evaluation that produces today's plan. What comes
 *  back is never presented as an instruction -- it is clearly a different
 *  day, and one action returns to the real one.
 */

const TEMPERATURE_MIN = 5;
const TEMPERATURE_MAX = 40;
const HUMIDITY_MIN = 30;
const HUMIDITY_MAX = 95;

export function ConditionsExplorer({
  actualTemperatureC,
  actualHumidityPct,
}: {
  actualTemperatureC: number | null;
  actualHumidityPct: number | null;
}) {
  const { auth } = useAuth();
  const { locale } = useLocale();
  const en = locale === "en";

  const startingTemperature = clamp(
    actualTemperatureC ?? 24,
    TEMPERATURE_MIN,
    TEMPERATURE_MAX,
  );
  const startingHumidity = clamp(actualHumidityPct ?? 70, HUMIDITY_MIN, HUMIDITY_MAX);

  const [temperature, setTemperature] = useState(startingTemperature);
  const [humidity, setHumidity] = useState(startingHumidity);
  const [exploring, setExploring] = useState(false);
  const [result, setResult] = useState<TrainingPlanWireResponse | null>(null);
  const [status, setStatus] = useState<"idle" | "working" | "error">("idle");

  // Only the most recent request may land: dragging a slider fires many.
  const requestSeq = useRef(0);

  useEffect(() => {
    if (!exploring || !auth?.accessToken) return;

    const seq = ++requestSeq.current;
    const token = auth.accessToken;
    setStatus("working");

    const timer = window.setTimeout(() => {
      evaluateTrainingPlan(token, {
        temperature_c: temperature,
        humidity_pct: humidity,
        label: en ? "Stated conditions" : "指定條件",
      })
        .then((response) => {
          if (seq !== requestSeq.current) return;
          setResult(response);
          setStatus("idle");
        })
        .catch(() => {
          if (seq !== requestSeq.current) return;
          setStatus("error");
        });
    }, 250);

    return () => window.clearTimeout(timer);
  }, [exploring, temperature, humidity, auth?.accessToken, en]);

  function backToToday() {
    requestSeq.current += 1;
    setExploring(false);
    setResult(null);
    setStatus("idle");
    setTemperature(startingTemperature);
    setHumidity(startingHumidity);
  }

  const scenario = result?.scenario;
  const costText = conditionsCostLabel(scenario?.speed_loss_pct ?? null, locale);
  const personalisation = result
    ? personalisationLabel(result.confidence, result.abstained, locale)
    : null;

  return (
    <Card
      title={en ? "Try different conditions" : "換個天氣看看"}
      subtitle={
        en
          ? "See how a hotter or cooler day would change your pace and your options."
          : "看看更熱或更涼的一天，會怎麼改變你的配速與可選課表。"
      }
      actions={
        exploring ? (
          <Button size="sm" variant="secondary" onClick={backToToday}>
            {en ? "Back to today" : "回到今天"}
          </Button>
        ) : undefined
      }
    >
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <SliderRow
          label={en ? "Temperature" : "氣溫"}
          value={temperature}
          min={TEMPERATURE_MIN}
          max={TEMPERATURE_MAX}
          step={1}
          suffix="°C"
          onChange={(next) => {
            setTemperature(next);
            setExploring(true);
          }}
        />
        <SliderRow
          label={en ? "Humidity" : "濕度"}
          value={humidity}
          min={HUMIDITY_MIN}
          max={HUMIDITY_MAX}
          step={5}
          suffix="%"
          onChange={(next) => {
            setHumidity(next);
            setExploring(true);
          }}
        />

        {!exploring && (
          <div style={{ fontSize: 13, color: "var(--text-muted)" }}>
            {en
              ? "Move a slider to explore. Nothing here changes your actual plan."
              : "拖動上面的滑桿開始試算。這裡的內容不會更動你今天真正的課表。"}
          </div>
        )}

        {exploring && (
          <>
            <Notice tone="accent" icon="info" title={en ? "Different conditions" : "這是假設的條件"}>
              {en
                ? `Worked out for ${Math.round(temperature)}°C and ${Math.round(humidity)}% humidity — not for today's actual conditions.`
                : `以 ${Math.round(temperature)}°C、濕度 ${Math.round(humidity)}% 推算，不是今天的實際天候。`}
            </Notice>

            {status === "error" && (
              <Notice tone="warning" icon="alert">
                {en
                  ? "Could not work that out just now. Your actual plan is unaffected."
                  : "目前無法完成試算，你今天的課表不受影響。"}
              </Notice>
            )}

            {scenario?.pacing_is_extrapolated && (
              <Notice tone="warning" icon="alert">
                {en
                  ? "These conditions are beyond what the underlying research measured, so treat the pace figure as a rough estimate."
                  : "這個條件超出了原始研究實測的範圍，配速數字請當作粗略估計。"}
              </Notice>
            )}

            {costText && (
              <div
                style={{
                  padding: "12px 14px",
                  borderRadius: 12,
                  backgroundColor: "var(--surface-sunken)",
                  border: "1px solid var(--border)",
                }}
              >
                <div style={{ fontSize: 12, color: "var(--text-muted)", marginBottom: 4 }}>
                  {en ? "Expected pace" : "預期配速"}
                </div>
                <div style={{ fontSize: 15, fontWeight: 700 }}>{costText}</div>
              </div>
            )}

            {result && (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "space-between",
                    gap: 8,
                    flexWrap: "wrap",
                  }}
                >
                  <div style={{ fontSize: 13, fontWeight: 700 }}>
                    {en ? "Options for that day" : "那一天的可選課表"}
                  </div>
                  {personalisation && (
                    <Badge tone={personalisation.isConservative ? "warning" : "good"}>
                      {personalisation.text}
                    </Badge>
                  )}
                </div>

                {result.candidates.map((candidate, index) => (
                  <div
                    key={candidate.candidate_id}
                    style={{
                      display: "flex",
                      alignItems: "baseline",
                      justifyContent: "space-between",
                      gap: 10,
                      padding: "10px 12px",
                      borderRadius: 10,
                      border:
                        index === 0 ? "1px solid var(--accent-ring)" : "1px solid var(--border)",
                      backgroundColor:
                        index === 0 ? "var(--accent-soft)" : "var(--surface-sunken)",
                    }}
                  >
                    <div style={{ fontWeight: index === 0 ? 750 : 600, fontSize: 13.5 }}>
                      {planTypeLabel(candidate.workout_type, locale)}
                    </div>
                    <div style={{ fontSize: 12.5, color: "var(--text-muted)" }}>
                      {candidate.duration_minutes > 0
                        ? `${candidate.duration_minutes} ${en ? "min" : "分鐘"}`
                        : en
                          ? "No run"
                          : "不跑"}
                      {candidate.distance_km > 0 ? ` · ${candidate.distance_km} km` : ""}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </Card>
  );
}

function SliderRow({
  label,
  value,
  min,
  max,
  step,
  suffix,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix: string;
  onChange: (next: number) => void;
}) {
  return (
    <label style={{ display: "block" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          marginBottom: 6,
        }}
      >
        <span style={{ fontSize: 13, fontWeight: 600 }}>{label}</span>
        <span className="tnum" style={{ fontSize: 15, fontWeight: 750, color: "var(--accent)" }}>
          {Math.round(value)}
          {suffix}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
        style={{ width: "100%", accentColor: "var(--accent)" }}
      />
    </label>
  );
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
