import { useCallback, useId, useRef, useState } from "react";
import { Eye } from "@phosphor-icons/react";
import { usableAcwr } from "../lib/acwr.ts";
import { paceShiftText } from "../lib/climateShift.ts";
import { figureSources, litFigures } from "../lib/coachChatUi.ts";
import type { FigureId } from "../lib/coachChatUi.ts";
import type { CoachPhase } from "../lib/coachConversation.ts";
import { shiftLocalDate } from "../lib/trainingLoad.ts";
import type { TrainingLoadResult } from "../lib/trainingLoad.ts";
import type { WeatherWireResponse } from "../data/apiClient.ts";
import { CountUp } from "./CountUp.tsx";
import { escapeClose, useDismiss } from "./useDismiss.ts";

/** 教練正在看: a chip in the header that opens the four figures the coach
 *  reads from, each with where it comes from. A finished step that read a
 *  figure lights a dot on the chip and glows the figure. Every figure is the
 *  signed-in Athlete's own; without enough observation they see an em dash
 *  and a reason, never an invented number. */
export function CoachContextChip({
  phase,
  en,
  locale,
  trainingLoad,
  liveWeather,
}: {
  phase: CoachPhase;
  en: boolean;
  locale: "zh-TW" | "en";
  trainingLoad: TrainingLoadResult;
  liveWeather: WeatherWireResponse | null;
}) {
  const [open, setOpen] = useState(false);
  const popId = useId();
  const scope = useRef<HTMLDivElement | null>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, scope, close);

  const unit = trainingLoad.units[0] ?? null;
  const unitSuffix = unit?.unit === "AU" ? "AU" : "";
  const acute = unit ? Math.round(unit.acuteLoad) : null;
  const chronic = unit ? Math.round(unit.chronicLoad) : null;
  const ratio = usableAcwr(unit?.loadRatio);
  const temperatureC =
    liveWeather && liveWeather.state !== "UNAVAILABLE" ? liveWeather.temperature_c : null;
  const speedLossPct = liveWeather?.speed_loss_pct_relative_to_normal ?? null;

  const since7 = shiftLocalDate(trainingLoad.asOfLocalDate, -6);
  const trainingDays7 = trainingLoad.daily.filter((d) => d.hasActivity && d.localDate >= since7).length;
  const trainingDays28 = trainingLoad.daily.filter((d) => d.hasActivity).length;
  const sources = figureSources(
    { acuteLoad: acute, chronicLoad: chronic, loadRatio: ratio, trainingDays7, trainingDays28, temperatureC },
    en,
  );

  // the step that just finished lights what it read; the key restarts the glow
  const stepCount =
    phase.kind === "thinking" || phase.kind === "streaming" || phase.kind === "proposal" || phase.kind === "answered"
      ? phase.steps.length
      : 0;
  const lit = litFigures(phase);
  const glow = (id: FigureId) =>
    lit.has(id) ? <span className="cc-figure-lit" key={`${id}-${stepCount}`} aria-hidden="true" /> : null;
  const label = en ? "Your coach is looking at" : "教練正在看";

  return (
    <div className="cc-ctx" ref={scope} onKeyDown={escapeClose(close, opener)}>
      <button
        ref={opener}
        type="button"
        className="cc-ctx-chip"
        aria-expanded={open}
        aria-controls={popId}
        onClick={() => setOpen((value) => !value)}
      >
        <Eye size={16} weight="bold" aria-hidden="true" />
        <span className="cc-ctx-label">{label}</span>
        {lit.size > 0 && <span className="cc-ctx-dot" key={stepCount} aria-hidden="true" />}
      </button>
      {open && (
        <div className="cc-ctx-pop" id={popId} role="group" aria-label={label}>
          <dl className="cc-figures">
            <div className="cc-figure">
              <dt>{en ? "Recent load" : "近期負荷"}</dt>
              <dd>
                <span className="digits"><CountUp id="acute" value={acute} /></span>
                {unit && unitSuffix && <span className="cc-figure-unit">{unitSuffix}</span>}
              </dd>
              <dd className="cc-figure-src">{sources.acute}</dd>
              {glow("acute")}
            </div>
            <div className="cc-figure">
              <dt>{en ? "Baseline" : "基準"}</dt>
              <dd>
                <span className="digits"><CountUp id="chronic" value={chronic} /></span>
                {unit && unitSuffix && <span className="cc-figure-unit">{unitSuffix}</span>}
              </dd>
              <dd className="cc-figure-src">{sources.chronic}</dd>
              {glow("chronic")}
            </div>
            <div className="cc-figure">
              <dt>{en ? "ACWR load ratio" : "ACWR 負荷比"}</dt>
              <dd>
                <span className="digits"><CountUp id="ratio" value={ratio} decimals={2} /></span>
              </dd>
              <dd className="cc-figure-src">{sources.ratio}</dd>
              {glow("ratio")}
            </div>
            <div className="cc-figure">
              <dt>{en ? "Conditions" : "天候"}</dt>
              <dd>
                {temperatureC === null ? (
                  <span className="cc-figure-none">{en ? "Unavailable" : "暫無"}</span>
                ) : (
                  <>
                    <span className="digits"><CountUp id="weather" value={Math.round(temperatureC)} />°C</span>
                    {speedLossPct !== null && (
                      <span className="cc-figure-unit">
                        {en ? `pace ${paceShiftText(speedLossPct, locale)}` : `配速${paceShiftText(speedLossPct, locale)}`}
                      </span>
                    )}
                  </>
                )}
              </dd>
              <dd className="cc-figure-src">{sources.weather}</dd>
              {glow("weather")}
            </div>
          </dl>
        </div>
      )}
    </div>
  );
}
