/* Charts, drawn as plain SVG.
 *
 * Specs follow the data-viz rules used across this app: bars capped at 24px
 * with a 4px rounded cap and a square baseline, 2px lines, markers ≥8px with a
 * 2px surface ring, hairline solid gridlines, and a hover tooltip on every
 * plotted form. Series colors come from the validated palette (blue / orange),
 * and every chart has a table view so nothing is gated behind color.
 */

import { useCallback, useLayoutEffect, useRef, useState } from "react";
import type { DailyLoadPoint, TrendPoint } from "../lib/trainingLoad.ts";
import { formatLocalDate, formatNumber } from "../lib/format.ts";
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

interface TooltipState {
  x: number;
  y: number;
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
        chart: `Daily session load (${unitLabel})`,
        rest: "Confirmed rest day",
        missing: "No record (missing data)",
        restLegend: "Confirmed rest day (counts as observed)",
        missingLegend: "Missing data (excluded from denominator)",
      }
    : {
        chart: `每日 session load（${unitLabel}）`,
        rest: "已確認休息日",
        missing: "沒有紀錄（缺漏）",
        restLegend: "已確認休息日（計入觀測天數）",
        missingLegend: "缺漏資料（不計入分母）",
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
      const box = event.currentTarget.ownerSVGElement!.getBoundingClientRect();
      setTooltip({
        x: event.clientX - box.left,
        y: Math.max(event.clientY - box.top - 12, 40),
        index,
      });
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
              {/* Days with no session: a marker under the axis, so "confirmed
                  rest" and "no data" are distinguishable without color. */}
              {total === 0 &&
                (point.restConfirmed ? (
                  <circle cx={x + barW / 2} cy={yFor(0) + 11} r={3.2} fill="var(--text-muted)" />
                ) : (
                  <circle
                    cx={x + barW / 2}
                    cy={yFor(0) + 11}
                    r={3.2}
                    fill="none"
                    stroke="var(--text-muted)"
                    strokeWidth={1.3}
                  />
                ))}
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
        <div className="chart-tooltip" style={{ left: tooltip.x, top: tooltip.y }}>
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
                  session load
                </span>
                <span className="chart-tooltip-val">
                  {formatNumber(load ?? 0)} {unit}
                </span>
              </div>
            ))
          ) : (
            <div className="chart-tooltip-row">
              <span>{active.restConfirmed ? labels.rest : labels.missing}</span>
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
          <span className="legend-swatch-dot" />
          {labels.restLegend}
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
        acuteLegend: "7-day acute load (acute_load)",
        chronicLegend: "28-day weekly-equivalent load (chronic_load)",
      }
    : {
        aria: "7 天負荷與 28 天週等效負荷趨勢",
        acuteShort: "7 天", chronicShort: "28 天", acute: "7 天負荷",
        chronic: "28 天週等效", ratio: "比值",
        acuteLegend: "7 天急性負荷（acute_load）",
        chronicLegend: "28 天週等效負荷（chronic_load）",
      };
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

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

      {hoverIndex !== null && active && (
        <div
          className="chart-tooltip"
          style={{ left: xFor(hoverIndex), top: Math.max(yFor(active.acuteLoad) - 10, 40) }}
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
          {labels.acuteLegend}
        </span>
        <span className="legend-item">
          <span className="legend-swatch" style={{ background: "var(--series-2)" }} />
          {labels.chronicLegend}
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
