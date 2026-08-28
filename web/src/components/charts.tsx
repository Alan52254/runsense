/* Charts, drawn as plain SVG.
 *
 * Specs follow the data-viz rules used across this app: bars capped at 24px
 * with a 4px rounded cap and a square baseline, 2px lines, markers ≥8px with a
 * 2px surface ring, hairline solid gridlines, and a hover tooltip on every
 * plotted form. Series colors come from the validated palette (blue / orange),
 * and every chart has a table view so nothing is gated behind color.
 */

import { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { DailyLoadPoint, DailyRunPoint, TrendPoint } from "../lib/trainingLoad.ts";
import { formatLocalDate, formatNumber, formatPace } from "../lib/format.ts";
import { tooltipTransform } from "../lib/tooltipPosition.ts";
import { useLocale } from "../state/LocaleContext.tsx";

function useElementWidth<T extends HTMLElement>(fallback = 720) {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(fallback);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const observer = new ResizeObserver((entries) => {
      setWidth(entries[0].contentRect.width);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return [ref, width] as const;
}

/** Picks a round tick interval first, then derives the axis top from it —
 *  so every tick label is a clean number (0 / 1,000 / 2,000) instead of the
 *  fractions you get from dividing an arbitrary max into N parts. */
function niceScale(dataMax: number, targetIntervals = 4): { max: number; ticks: number[] } {
  if (dataMax <= 0) return { max: 10, ticks: [0, 5, 10] };

  const rawStep = dataMax / targetIntervals;
  const magnitude = 10 ** Math.floor(Math.log10(rawStep));
  const normalized = rawStep / magnitude;
  const step = ([1, 2, 2.5, 5, 10].find((s) => normalized <= s) ?? 10) * magnitude;

  const max = Math.ceil(dataMax / step) * step;
  const ticks: number[] = [];
  for (let value = 0; value <= max + step / 2; value += step) {
    ticks.push(Math.round(value * 100) / 100);
  }
  return { max, ticks };
}

/** Viewport coordinates (event.clientX/Y), not chart-relative -- paired with
 *  .chart-tooltip's `position: fixed` so the tooltip is positioned and
 *  flipped against the real page edges, not against whichever card happens
 *  to contain this particular chart. A hover near a card's own edge with
 *  open space just past it (a left-column chart, say) must NOT flip just
 *  because it's near *that card's* edge -- only the actual viewport edge
 *  matters. */
interface TooltipState {
  clientX: number;
  clientY: number;
  index: number;
}

/* ---------------------------------------------------------------- */
/* Daily session load — one bar per day                              */
/* ---------------------------------------------------------------- */

export function DailyLoadChart({
  points,
  unitLabel,
  height = 240,
}: {
  points: DailyLoadPoint[];
  unitLabel: string;
  height?: number;
}) {
  const { locale } = useLocale();
  const labels = locale === "en"
    ? {
        chart: `Daily training load (${unitLabel})`,
        missing: "No record",
        missingLegend: "No record that day",
      }
    : {
        chart: `每日訓練負荷（${unitLabel}）`,
        missing: "沒有紀錄",
        missingLegend: "當日沒有紀錄",
      };
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  const pad = { top: 14, right: 8, bottom: 42, left: 46 };
  const plotW = Math.max(width - pad.left - pad.right, 80);
  const plotH = height - pad.top - pad.bottom;

  const dayTotals = points.map((p) =>
    Object.values(p.loadByUnit).reduce((sum, v) => sum + (v ?? 0), 0),
  );
  const { max: maxY, ticks: yTicks } = niceScale(Math.max(...dayTotals, 1));
  const band = plotW / Math.max(points.length, 1);
  const barW = Math.min(24, Math.max(band - 2, 3));

  const yFor = (value: number) => pad.top + plotH - (value / maxY) * plotH;

  const handleMove = useCallback(
    (event: React.MouseEvent<SVGRectElement>, index: number) => {
      setTooltip({ clientX: event.clientX, clientY: event.clientY, index });
    },
    [],
  );

  const active = tooltip ? points[tooltip.index] : null;
  const activeTotal = tooltip ? dayTotals[tooltip.index] : 0;

  // Label every 4th day so ticks never collide at narrow widths.
  const tickEvery = Math.max(1, Math.ceil(points.length / Math.floor(plotW / 58)));

  return (
    <div className="chart" ref={ref}>
      <svg width={width} height={height} role="img" aria-label={labels.chart}>
        {yTicks.map((tick) => (
          <g key={tick}>
            <line
              className="chart-grid"
              x1={pad.left}
              x2={pad.left + plotW}
              y1={yFor(tick)}
              y2={yFor(tick)}
            />
            <text className="chart-tick chart-tick-end" x={pad.left - 10} y={yFor(tick) + 4}>
              {formatNumber(tick)}
            </text>
          </g>
        ))}

        <line
          className="chart-axis"
          x1={pad.left}
          x2={pad.left + plotW}
          y1={yFor(0)}
          y2={yFor(0)}
        />

        {points.map((point, i) => {
          const total = dayTotals[i];
          const x = pad.left + band * i + (band - barW) / 2;
          const barH = (total / maxY) * plotH;
          return (
            <g key={point.localDate}>
              {total > 0 && (
                <path
                  className="chart-bar"
                  d={roundedTopBar(x, yFor(total), barW, barH, 4)}
                />
              )}
              {/* Days with no session: a hollow marker under the axis. */}
              {total === 0 && (
                <circle
                  cx={x + barW / 2}
                  cy={yFor(0) + 11}
                  r={3.2}
                  fill="none"
                  stroke="var(--text-muted)"
                  strokeWidth={1.3}
                />
              )}
              {i % tickEvery === 0 && (
                <text
                  className="chart-tick chart-tick-mid"
                  x={x + barW / 2}
                  y={height - 12}
                >
                  {point.localDate.slice(5).replace("-", "/")}
                </text>
              )}
              <rect
                className="chart-band"
                x={pad.left + band * i}
                y={pad.top}
                width={band}
                height={plotH + 18}
                onMouseMove={(e) => handleMove(e, i)}
                onMouseLeave={() => setTooltip(null)}
              />
            </g>
          );
        })}
      </svg>

      {tooltip && active && (
        <div
          className="chart-tooltip"
          style={{
            left: tooltip.clientX,
            top: tooltip.clientY,
            transform: tooltipTransform(tooltip.clientX, tooltip.clientY),
          }}
        >
          <div className="chart-tooltip-date">
            {locale === "en" ? active.localDate : formatLocalDate(active.localDate)}
          </div>
          {activeTotal > 0 ? (
            Object.entries(active.loadByUnit).map(([unit, load]) => (
              <div className="chart-tooltip-row" key={unit}>
                <span className="chart-tooltip-key">
                  <span
                    className="legend-swatch legend-swatch-square"
                    style={{ background: "var(--series-1)" }}
                  />
                  {locale === "en" ? "Load" : "負荷"}
                </span>
                <span className="chart-tooltip-val">
                  {formatNumber(load ?? 0)} {unit}
                </span>
              </div>
            ))
          ) : (
            <div className="chart-tooltip-row">
              <span>{labels.missing}</span>
            </div>
          )}
        </div>
      )}

      <div className="legend">
        <span className="legend-item">
          <span
            className="legend-swatch legend-swatch-square"
            style={{ background: "var(--series-1)" }}
          />
          {labels.chart}
        </span>
        <span className="legend-item">
          <span className="legend-swatch-ring" />
          {labels.missingLegend}
        </span>
      </div>
    </div>
  );
}

/** A bar with a 4px rounded cap and a square foot on the baseline. */
function roundedTopBar(x: number, y: number, w: number, h: number, r: number): string {
  const radius = Math.min(r, h, w / 2);
  return [
    `M${x},${y + h}`,
    `L${x},${y + radius}`,
    `Q${x},${y} ${x + radius},${y}`,
    `L${x + w - radius},${y}`,
    `Q${x + w},${y} ${x + w},${y + radius}`,
    `L${x + w},${y + h}`,
    "Z",
  ].join(" ");
}

/* ---------------------------------------------------------------- */
/* Daily distance + average pace — bars on a km axis, a pace line on a  */
/* second axis, same no-record marker as DailyLoadChart                  */
/* ---------------------------------------------------------------- */

export function DailyDistancePaceChart({
  points,
  height = 240,
}: {
  points: DailyRunPoint[];
  height?: number;
}) {
  const { locale } = useLocale();
  const labels = locale === "en"
    ? {
        chart: "Daily distance (km)",
        pace: "Average pace",
        missing: "No distance recorded",
        missingLegend: "No distance recorded",
        aria: "Daily distance and average pace",
      }
    : {
        chart: "每日跑量（km）",
        pace: "平均配速",
        missing: "當日無跑步紀錄",
        missingLegend: "當日無跑步紀錄",
        aria: "每日跑量與平均配速",
      };
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  const pad = { top: 14, right: 14, bottom: 42, left: 46 };
  const plotW = Math.max(width - pad.left - pad.right, 80);
  const plotH = height - pad.top - pad.bottom;

  const distances = points.map((p) => p.distanceKm);
  const { max: maxDist, ticks: distTicks } = niceScale(Math.max(...distances, 1));

  const paceValues = points
    .map((p) => p.avgPaceSecPerKm)
    .filter((v): v is number => v !== null);
  const hasPace = paceValues.length > 0;
  const paceMin = hasPace ? Math.min(...paceValues) : 0;
  const paceMax = hasPace ? Math.max(...paceValues) : 0;
  const paceSpan = Math.max(paceMax - paceMin, 30);
  const paceAxisMin = Math.max(0, paceMin - paceSpan * 0.15);
  const paceAxisMax = paceMax + paceSpan * 0.15;

  const band = plotW / Math.max(points.length, 1);
  const barW = Math.min(24, Math.max(band - 2, 3));

  const yForDist = (v: number) => pad.top + plotH - (v / maxDist) * plotH;
  const yForPace = (v: number) =>
    pad.top + plotH - ((v - paceAxisMin) / (paceAxisMax - paceAxisMin)) * plotH;

  const handleMove = useCallback(
    (event: React.MouseEvent<SVGRectElement>, index: number) => {
      setTooltip({ clientX: event.clientX, clientY: event.clientY, index });
    },
    [],
  );

  const active = tooltip ? points[tooltip.index] : null;

  // Label every 4th day so ticks never collide at narrow widths.
  const tickEvery = Math.max(1, Math.ceil(points.length / Math.floor(plotW / 58)));

  return (
    <div className="chart" ref={ref}>
      <svg width={width} height={height} role="img" aria-label={labels.aria}>
        {distTicks.map((tick) => (
          <g key={tick}>
            <line
              className="chart-grid"
              x1={pad.left}
              x2={pad.left + plotW}
              y1={yForDist(tick)}
              y2={yForDist(tick)}
            />
            <text className="chart-tick chart-tick-end" x={pad.left - 10} y={yForDist(tick) + 4}>
              {formatNumber(tick)}
            </text>
          </g>
        ))}

        <line
          className="chart-axis"
          x1={pad.left}
          x2={pad.left + plotW}
          y1={yForDist(0)}
          y2={yForDist(0)}
        />

        {points.map((point, i) => {
          const x = pad.left + band * i + (band - barW) / 2;
          const barH = (point.distanceKm / maxDist) * plotH;
          return (
            <g key={point.localDate}>
              {point.distanceKm > 0 && (
                <path
                  className="chart-bar"
                  d={roundedTopBar(x, yForDist(point.distanceKm), barW, barH, 4)}
                />
              )}
              {point.distanceKm === 0 && (
                <circle
                  cx={x + barW / 2}
                  cy={yForDist(0) + 11}
                  r={3.2}
                  fill="none"
                  stroke="var(--text-muted)"
                  strokeWidth={1.3}
                />
              )}
              {i % tickEvery === 0 && (
                <text className="chart-tick chart-tick-mid" x={x + barW / 2} y={height - 12}>
                  {point.localDate.slice(5).replace("-", "/")}
                </text>
              )}
              <rect
                className="chart-band"
                x={pad.left + band * i}
                y={pad.top}
                width={band}
                height={plotH + 18}
                onMouseMove={(e) => handleMove(e, i)}
                onMouseLeave={() => setTooltip(null)}
              />
            </g>
          );
        })}

        {/* The pace line/marker stays hidden until a day is hovered -- with a
            bar for every day already on screen, drawing it permanently made
            the chart busy for little extra information (the exact figure is
            already in the tooltip on hover). */}
        {tooltip && active && active.avgPaceSecPerKm !== null && (
          <circle
            className="chart-marker-ring"
            cx={pad.left + band * tooltip.index + band / 2}
            cy={yForPace(active.avgPaceSecPerKm)}
            r={4.5}
            fill="var(--series-2)"
          />
        )}
      </svg>

      {tooltip && active && (
        <div
          className="chart-tooltip"
          style={{
            left: tooltip.clientX,
            top: tooltip.clientY,
            transform: tooltipTransform(tooltip.clientX, tooltip.clientY),
          }}
        >
          <div className="chart-tooltip-date">
            {locale === "en" ? active.localDate : formatLocalDate(active.localDate)}
          </div>
          {active.distanceKm > 0 ? (
            <>
              <div className="chart-tooltip-row">
                <span className="chart-tooltip-key">
                  <span
                    className="legend-swatch legend-swatch-square"
                    style={{ background: "var(--series-1)" }}
                  />
                  {labels.chart}
                </span>
                <span className="chart-tooltip-val">{active.distanceKm} km</span>
              </div>
              <div className="chart-tooltip-row">
                <span className="chart-tooltip-key">
                  <span className="legend-swatch" style={{ background: "var(--series-2)" }} />
                  {labels.pace}
                </span>
                <span className="chart-tooltip-val">{formatPace(active.avgPaceSecPerKm)}</span>
              </div>
            </>
          ) : (
            <div className="chart-tooltip-row">
              <span>{labels.missing}</span>
            </div>
          )}
        </div>
      )}

      <div className="legend">
        <span className="legend-item">
          <span
            className="legend-swatch legend-swatch-square"
            style={{ background: "var(--series-1)" }}
          />
          {labels.chart}
        </span>
        {hasPace && (
          <span className="legend-item">
            <span className="legend-swatch" style={{ background: "var(--series-2)" }} />
            {labels.pace}
          </span>
        )}
        <span className="legend-item">
          <span className="legend-swatch-ring" />
          {labels.missingLegend}
        </span>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- */
/* Acute vs chronic — two lines, one y-scale                         */
/* ---------------------------------------------------------------- */

export function LoadTrendChart({
  points,
  height = 260,
}: {
  points: TrendPoint[];
  height?: number;
}) {
  const { locale } = useLocale();
  const labels = locale === "en"
    ? {
        aria: "7-day load and 28-day weekly-equivalent load trend",
        acuteShort: "7d", chronicShort: "28d", acute: "7-day load",
        chronic: "28-day weekly equivalent", ratio: "Ratio",
      }
    : {
        aria: "7 天負荷與 28 天週等效負荷趨勢",
        acuteShort: "7 天", chronicShort: "28 天", acute: "7 天負荷",
        chronic: "28 天週等效", ratio: "比值",
      };
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const [mousePos, setMousePos] = useState<{ x: number; y: number } | null>(null);

  const pad = { top: 16, right: 72, bottom: 34, left: 46 };
  const plotW = Math.max(width - pad.left - pad.right, 80);
  const plotH = height - pad.top - pad.bottom;

  const { max: maxY, ticks: yTicks } = niceScale(
    Math.max(...points.flatMap((p) => [p.acuteLoad, p.chronicLoad]), 1),
  );
  const stepX = plotW / Math.max(points.length - 1, 1);
  const xFor = (i: number) => pad.left + stepX * i;
  const yFor = (v: number) => pad.top + plotH - (v / maxY) * plotH;

  const linePath = (pick: (p: TrendPoint) => number) =>
    points.map((p, i) => `${i === 0 ? "M" : "L"}${xFor(i)},${yFor(pick(p))}`).join(" ");

  const areaPath = `${linePath((p) => p.acuteLoad)} L${xFor(points.length - 1)},${yFor(0)} L${xFor(0)},${yFor(0)} Z`;

  const last = points[points.length - 1];
  const active = hoverIndex === null ? null : points[hoverIndex];
  const tickEvery = Math.max(1, Math.ceil(points.length / Math.floor(plotW / 62)));

  return (
    <div className="chart" ref={ref}>
      <svg
        width={width}
        height={height}
        role="img"
        aria-label={labels.aria}
        onMouseLeave={() => setHoverIndex(null)}
        onMouseMove={(e) => {
          const box = e.currentTarget.getBoundingClientRect();
          const relX = e.clientX - box.left - pad.left;
          const index = Math.round(relX / stepX);
          setHoverIndex(Math.min(Math.max(index, 0), points.length - 1));
          setMousePos({ x: e.clientX, y: e.clientY });
        }}
      >
        {yTicks.map((tick) => (
          <g key={tick}>
            <line
              className="chart-grid"
              x1={pad.left}
              x2={pad.left + plotW}
              y1={yFor(tick)}
              y2={yFor(tick)}
            />
            <text className="chart-tick chart-tick-end" x={pad.left - 10} y={yFor(tick) + 4}>
              {formatNumber(tick)}
            </text>
          </g>
        ))}

        <path className="chart-area-1" d={areaPath} />
        <path className="chart-line-2" d={linePath((p) => p.chronicLoad)} />
        <path className="chart-line-1" d={linePath((p) => p.acuteLoad)} />

        {points.map((p, i) =>
          i % tickEvery === 0 ? (
            <text
              key={p.localDate}
              className="chart-tick chart-tick-mid"
              x={xFor(i)}
              y={height - 12}
            >
              {p.localDate.slice(5).replace("-", "/")}
            </text>
          ) : null,
        )}

        {hoverIndex !== null && active && (
          <>
            <line
              className="chart-crosshair"
              x1={xFor(hoverIndex)}
              x2={xFor(hoverIndex)}
              y1={pad.top}
              y2={pad.top + plotH}
            />
            <circle
              className="chart-marker-ring"
              cx={xFor(hoverIndex)}
              cy={yFor(active.chronicLoad)}
              r={4.5}
              fill="var(--series-2)"
            />
            <circle
              className="chart-marker-ring"
              cx={xFor(hoverIndex)}
              cy={yFor(active.acuteLoad)}
              r={4.5}
              fill="var(--series-1)"
            />
          </>
        )}

        {/* End markers + direct labels: identity without color-matching. */}
        <circle
          className="chart-marker-ring"
          cx={xFor(points.length - 1)}
          cy={yFor(last.chronicLoad)}
          r={4.5}
          fill="var(--series-2)"
        />
        <circle
          className="chart-marker-ring"
          cx={xFor(points.length - 1)}
          cy={yFor(last.acuteLoad)}
          r={4.5}
          fill="var(--series-1)"
        />
        <text
          className="chart-label"
          x={xFor(points.length - 1) + 10}
          y={yFor(last.acuteLoad) + 4}
        >
          {labels.acuteShort} {formatNumber(last.acuteLoad)}
        </text>
        <text
          className="chart-label"
          x={xFor(points.length - 1) + 10}
          y={yFor(last.chronicLoad) + 4}
        >
          {labels.chronicShort} {formatNumber(last.chronicLoad)}
        </text>
      </svg>

      {hoverIndex !== null && active && mousePos && (
        <div
          className="chart-tooltip"
          style={{
            left: mousePos.x,
            top: mousePos.y,
            transform: tooltipTransform(mousePos.x, mousePos.y),
          }}
        >
          <div className="chart-tooltip-date">
            {locale === "en" ? active.localDate : formatLocalDate(active.localDate)}
          </div>
          <div className="chart-tooltip-row">
            <span className="chart-tooltip-key">
              <span className="legend-swatch" style={{ background: "var(--series-1)" }} />
              {labels.acute}
            </span>
            <span className="chart-tooltip-val">{formatNumber(active.acuteLoad)}</span>
          </div>
          <div className="chart-tooltip-row">
            <span className="chart-tooltip-key">
              <span className="legend-swatch" style={{ background: "var(--series-2)" }} />
              {labels.chronic}
            </span>
            <span className="chart-tooltip-val">{formatNumber(active.chronicLoad)}</span>
          </div>
          <div className="chart-tooltip-row">
            <span>{labels.ratio}</span>
            <span className="chart-tooltip-val">
              {active.loadRatio === null ? "—" : active.loadRatio.toFixed(2)}
            </span>
          </div>
        </div>
      )}

      <div className="legend">
        <span className="legend-item">
          <span className="legend-swatch" style={{ background: "var(--series-1)" }} />
          {labels.acute}
        </span>
        <span className="legend-item">
          <span className="legend-swatch" style={{ background: "var(--series-2)" }} />
          {labels.chronic}
        </span>
      </div>
    </div>
  );
}

/* ---------------------------------------------------------------- */
/* Sparkline — 14 days of load in a table cell                        */
/* ---------------------------------------------------------------- */

export function Sparkline({
  values,
  width = 108,
  height = 28,
}: {
  values: number[];
  width?: number;
  height?: number;
}) {
  if (values.length < 2) {
    return <span className="dim" style={{ fontSize: 12 }}>—</span>;
  }

  const max = Math.max(...values, 1);
  const stepX = width / (values.length - 1);
  const path = values
    .map((v, i) => `${i === 0 ? "M" : "L"}${i * stepX},${height - 3 - (v / max) * (height - 6)}`)
    .join(" ");
  const lastY = height - 3 - (values[values.length - 1] / max) * (height - 6);

  return (
    <svg className="sparkline" width={width} height={height} aria-hidden="true">
      <path className="sparkline-line" d={path} />
      <circle cx={width} cy={lastY} r={2.6} fill="var(--series-1)" />
    </svg>
  );
}
