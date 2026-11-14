import { scaleLinear, type ScaleLinear } from "d3-scale";
import type { ReactNode, Ref } from "react";
import type { Size } from "./useSize";

/**
 * The parts every chart shares: the plot beside its legend, the axes, and the
 * readout that says what the pointer is on.
 *
 * Charts are SVG drawn by React. Every colour comes from a role property by
 * class, ``chart-series-1`` to ``chart-series-8`` for the series, and the
 * axis labels are text the service formatted in household-local time.
 */

/** Room around the plot for the axis labels, in pixels. */
export const MARGIN = { top: 14, right: 24, bottom: 30, left: 76 };
export const SERIES_COLOURS = 8;

/** A labelled mark along the horizontal axis. ``at`` is in the axis's own units, such as seconds from the start. */
export type Tick = { at: number; label: string };
/** A labelled mark up the vertical axis. */
export type AxisTick = { value: number; label: string };
export type LegendEntry = { name: string; total: string };
export type Scale = ScaleLinear<number, number>;

/** The class that colours series index. More series than colours reuse them, dashed. */
export function seriesClass(index: number): string {
  return `chart-series-${(index % SERIES_COLOURS) + 1}`;
}

export function dashed(index: number): boolean {
  return index >= SERIES_COLOURS;
}

/** Scales from 0 to xLength across and 0 to yMax up, inside the margins of a plot of size. */
export function plotScales(size: Size, xLength: number, yMax: number): { x: Scale; y: Scale } {
  const right = Math.max(MARGIN.left + 1, size.width - MARGIN.right);
  const bottom = Math.max(MARGIN.top + 1, size.height - MARGIN.bottom);
  return {
    x: scaleLinear().domain([0, Math.max(xLength, 1)]).range([MARGIN.left, right]),
    y: scaleLinear().domain([0, Math.max(yMax, 1)]).range([bottom, MARGIN.top]),
  };
}

/** The plot, which the chart measures and draws into, with its legend beside it. */
export function ChartFrame({ plotRef, legend, legendLabel, children }: { plotRef: Ref<HTMLDivElement>; legend: LegendEntry[]; legendLabel: string; children: ReactNode }) {
  return (
    <div className="chart">
      <div className="chart-plot" ref={plotRef}>
        {children}
      </div>
      {legend.length > 0 && (
        <ul className="chart-legend" aria-label={legendLabel}>
          {legend.map((entry, index) => (
            <li key={entry.name} className={seriesClass(index)} data-dashed={dashed(index) || undefined}>
              <svg className="chart-swatch" viewBox="0 0 24 12" aria-hidden="true">
                <line x1="1" y1="6" x2="23" y2="6" />
              </svg>
              <span className="chart-legend-name">{entry.name}</span>
              <span className="chart-legend-total">{entry.total}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** The horizontal and vertical axes, with a grid line across the plot at each vertical tick. */
export function Axes({ x, y, xTicks, yTicks }: { x: Scale; y: Scale; xTicks: Tick[]; yTicks: AxisTick[] }) {
  const [left, right] = x.range();
  const [bottom, top] = y.range();
  return (
    <g aria-hidden="true">
      <g className="chart-grid">
        {yTicks.map((tick) => (
          <line key={tick.value} x1={left} x2={right} y1={y(tick.value)} y2={y(tick.value)} />
        ))}
      </g>
      <g className="chart-axis">
        <line x1={left} x2={right} y1={bottom} y2={bottom} />
        {xTicks.map((tick) => (
          <g key={tick.at} transform={`translate(${x(tick.at)}, ${bottom})`}>
            <line y2={5} />
            <text y={19} textAnchor="middle">
              {tick.label}
            </text>
          </g>
        ))}
      </g>
      <g className="chart-axis">
        <line x1={left} x2={left} y1={top} y2={bottom} />
        {yTicks.map((tick) => (
          <g key={tick.value} transform={`translate(${left}, ${y(tick.value)})`}>
            <line x2={-5} />
            <text x={-9} dy="0.32em" textAnchor="end">
              {tick.label}
            </text>
          </g>
        ))}
      </g>
    </g>
  );
}

/** What the pointer or the keyboard is on, beside that spot in the plot. It turns to the left in the right of the plot. */
export function Readout({ left, top, flip, text }: { left: number; top: number; flip: boolean; text: string }) {
  return (
    <div className="chart-readout" aria-live="polite" data-flip={flip || undefined} style={{ left, top }}>
      {text}
    </div>
  );
}
