import { acwrValueText } from "../../../lib/acwr.ts";
import { useEffect, useId, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Button, DateRangePicker, InfoTip, Notice, StatTile } from "../../../components/ui.tsx";
import type { DateRange } from "../../../components/ui.tsx";
import { SlideOver } from "../../../components/motion.tsx";
import { DailyDistancePaceChart, DailyLoadChart } from "../../../components/charts.tsx";
import { DataQualityBadge, WeatherStateBadge } from "../../../components/domain.tsx";
import { ConditionsExplorer } from "../../../components/ConditionsExplorer.tsx";
import { formatNumber, UNIT_SHORT } from "../../../lib/format.ts";
import { dailyDistancePointsForRange, dailyLoadPointsForRange, daysBetween, shiftLocalDate } from "../../../lib/trainingLoad.ts";
import type { resolveDisplayedTrainingLoad } from "../../../lib/trainingLoadDisplay.ts";
import type { TodayViewModel } from "../../../lib/todayViewModel.ts";
import type { Activity } from "../../../lib/types.ts";
import { TimeOfDaySlots } from "./TodaySidePanels.tsx";
import { climateShiftLabel, interpolate, paceShapeText, type TodayCopy } from "./todayCopy.ts";
import { Row, Stack } from "../../../components/Layout.tsx";

type Locale = "zh-TW" | "en";
type DisplayedLoad = ReturnType<typeof resolveDisplayedTrainingLoad>;

/** Charts stay browsable but not unbounded -- past a year the SVG gets
 *  unreadably dense, so widening `to` past `maxDate` or `from` past this
 *  many days back both clamp instead of silently no-op. */
const MAX_CHART_RANGE_DAYS = 366;

function clampChartRange(range: DateRange, maxDate: string): DateRange {
  const to = range.to > maxDate ? maxDate : range.to;
  const from =
    daysBetween(range.from, to) > MAX_CHART_RANGE_DAYS - 1 ? shiftLocalDate(to, -(MAX_CHART_RANGE_DAYS - 1)) : range.from;
  return { from, to };
}

export function LoadDrawer({ open, onClose, displayedLoad, activities, today, c, locale }: {
  open: boolean;
  onClose: () => void;
  displayedLoad: DisplayedLoad;
  activities: Activity[];
  today: string;
  c: TodayCopy;
  locale: Locale;
}) {
  const en = locale === "en";
  const titleId = useId();
  const primaryUnit = displayedLoad.trainingLoad.units[0] ?? null;
  // Keep the read-only cards and charts on one visible as-of date. This
  // display fallback never feeds historical values back into today's plan.
  const defaultRange = displayedLoad.range;
  const [loadRange, setLoadRange] = useState<DateRange>(defaultRange);
  const [runRange, setRunRange] = useState<DateRange>(defaultRange);
  // Activities arrive after the shell renders: follow the resolved window.
  useEffect(() => {
    setLoadRange(defaultRange);
    setRunRange(defaultRange);
  }, [defaultRange]);
  const loadPoints = useMemo(() => dailyLoadPointsForRange(activities, loadRange.from, loadRange.to), [activities, loadRange]);
  const runPoints = useMemo(() => dailyDistancePointsForRange(activities, runRange.from, runRange.to), [activities, runRange]);

  return (
    <SlideOver open={open} onClose={onClose} size="lg" labelledBy={titleId} className="analysis-drawer">
      <header className="analysis-drawer-header">
        <div className="row-between">
          <h2 id={titleId}>{en ? "7 / 28-day load" : "7／28 天負荷"}</h2>
          <Button variant="ghost" icon="x" onClick={onClose} aria-label={en ? "Close" : "關閉"} />
        </div>
      </header>
      <div className="analysis-drawer-body ath-drawer-body">
        {displayedLoad.isHistorical && (
          <Notice tone="neutral" icon="history">
            {en
              ? `No workouts were recorded in the current 28-day window. The metrics and charts below use the latest recorded period (${displayedLoad.range.from} to ${displayedLoad.range.to}); today's recommendation still uses today's current state.`
              : `最近 28 天沒有訓練紀錄；下方負荷指標與圖表改顯示最近有資料的區間（${displayedLoad.range.from} 至 ${displayedLoad.range.to}），今日課表仍依今天的狀態判斷。`}
          </Notice>
        )}
        <div className="ath-stat-grid">
          <StatTile
            label={<Row as="span" gap={1}>{c.acute}<InfoTip text={c.acuteFoot} /></Row>}
            value={primaryUnit ? formatNumber(primaryUnit.acuteLoad) : "—"}
            unit={primaryUnit ? UNIT_SHORT[primaryUnit.unit] : undefined}
          />
          <StatTile
            label={<Row as="span" gap={1}>{c.chronic}<InfoTip text={c.chronicFoot} /></Row>}
            value={primaryUnit ? formatNumber(primaryUnit.chronicLoad) : "—"}
            unit={primaryUnit ? UNIT_SHORT[primaryUnit.unit] : undefined}
          />
          <StatTile
            label={<Row as="span" gap={1}>{c.ratio}{primaryUnit?.loadRatio !== null && <InfoTip text={c.ratioFoot} />}</Row>}
            value={primaryUnit?.loadRatio === null || primaryUnit === null ? c.noCalc : acwrValueText(primaryUnit.loadRatio, locale)}
            foot={primaryUnit?.loadRatio === null ? c.ratioLow : undefined}
          />
          <StatTile
            label={c.observations}
            value={`${displayedLoad.trainingLoad.observationDays}`}
            unit={c.days28}
            foot={<DataQualityBadge quality={displayedLoad.trainingLoad.dataQuality} />}
          />
        </div>

        <section className="ath-drawer-section">
          <div className="row-between">
            <h3>{c.chart}</h3>
            <Link className="btn btn-secondary btn-sm" to="/app/load">{c.trend}</Link>
          </div>
          <div className="chart-toolbar">
            <DateRangePicker range={loadRange} maxDate={today} defaultRange={defaultRange} onChange={(next) => setLoadRange(clampChartRange(next, today))} />
          </div>
          <DailyLoadChart points={loadPoints} unitLabel={primaryUnit?.unit ?? "AU"} height={230} />
        </section>

        <section className="ath-drawer-section">
          <h3>{c.runChart}</h3>
          <div className="chart-toolbar">
            <DateRangePicker range={runRange} maxDate={today} defaultRange={defaultRange} onChange={(next) => setRunRange(clampChartRange(next, today))} />
          </div>
          <DailyDistancePaceChart points={runPoints} height={230} />
        </section>
      </div>
    </SlideOver>
  );
}

export function ConditionsDrawer({ open, onClose, vm, loading, c, locale }: {
  open: boolean;
  onClose: () => void;
  vm: TodayViewModel;
  loading: boolean;
  c: TodayCopy;
  locale: Locale;
}) {
  const titleId = useId();
  const w = vm.weather;
  const pace = paceShapeText(vm.climate.nowPace);
  return (
    <SlideOver open={open} onClose={onClose} size="md" labelledBy={titleId} className="analysis-drawer">
      <header className="analysis-drawer-header">
        <div className="row-between">
          <h2 id={titleId}>{c.weather}</h2>
          <Button variant="ghost" icon="x" onClick={onClose} aria-label={locale === "en" ? "Close" : "關閉"} />
        </div>
        <p>
          {interpolate(c.weatherCity, { city: w.city })} <WeatherStateBadge state={w.state} />
        </p>
      </header>
      <div className="analysis-drawer-body ath-drawer-body">
        {loading ? (
          <Notice tone="neutral" icon="info">{c.weatherLoading}</Notice>
        ) : w.state === "UNAVAILABLE" ? (
          <Notice tone="neutral" icon="cloud">{c.weatherUnavailable}</Notice>
        ) : (
          <div className="stack-sm">
            <div className="grid-2">
              <StatTile
                small
                label={c.temperature}
                value={
                  w.climateNormalReferenceC !== null && w.temperatureC !== null ? (
                    <InfoTip
                      text={interpolate(c.vsNormal, {
                        normal: w.climateNormalReferenceC.toFixed(1),
                        sign: w.temperatureC >= w.climateNormalReferenceC ? "+" : "",
                        diff: (w.temperatureC - w.climateNormalReferenceC).toFixed(1),
                      })}
                    >
                      <span>{w.temperatureC.toFixed(1)}</span>
                    </InfoTip>
                  ) : (
                    (w.temperatureC?.toFixed(1) ?? "—")
                  )
                }
                unit="°C"
              />
              <StatTile small label={c.humidity} value={`${w.humidityPct ?? "—"}`} unit="%" />
            </div>
            <div className="ath-env-row">
              <span>{c.paceAdjust}</span>
              <strong className="tnum">{climateShiftLabel(vm.climate.speedLossPct, null, c, locale)}</strong>
            </div>
            {pace && (
              <div className="ath-env-row is-climate">
                <Row as="span" gap={1}>
                  {c.adjustedPace}
                  <InfoTip text={c.adjustedPaceHint} />
                </Row>
                <strong className="tnum">{pace}</strong>
              </div>
            )}
            {vm.climate.slots.length > 0 && (
              <Stack gap={2}>
                <div className="field-label">{c.timeOfDay}</div>
                <div className="grid-3 ath-slot-grid">
                  <TimeOfDaySlots slots={vm.climate.slots} c={c} />
                </div>
              </Stack>
            )}
          </div>
        )}
        <ConditionsExplorer actualTemperatureC={w.temperatureC} actualHumidityPct={w.humidityPct} />
      </div>
    </SlideOver>
  );
}
