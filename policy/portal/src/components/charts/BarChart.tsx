import { scaleLinear } from "d3-scale";
import { stack } from "d3-shape";
import { useLayoutEffect, useRef, useState } from "react";
import { ChartFrame, seriesClass } from "./ChartFrame";
import { useSize } from "./useSize";

/** One bar: its name down the left, and one value per segment, stacked left to right. */
export type Bar = { name: string; values: number[] };

type Props = {
  /** What the chart shows, said to a screen reader. */
  label: string;
  bars: Bar[];
  /** The segments' names, in stacking order. A key names them when there are two or more. */
  segments: string[];
  /** The text at the end of a bar, such as 1.2 GB down, 40 MB up. */
  format: (bar: Bar) => string;
  /** Said in place of the bars when there are none. */
  empty: string;
};

/** The height of one bar's row, and the room above and below the bars, in pixels. */
const ROW = 26;
const PAD = { top: 4, bottom: 4, gap: 10 };
/** A guess at a character's width, until the browser has measured the labels. */
const CHARACTER = 7.2;

type Widths = { names: number; values: number };

function guess(texts: string[]): number {
  return Math.max(0, ...texts.map((text) => text.length)) * CHARACTER;
}

/** The widest of the text elements matching selector, or null when the browser cannot measure text. */
function widest(root: SVGSVGElement, selector: string): number | null {
  const found = [...root.querySelectorAll<SVGTextElement>(selector)];
  if (found.length === 0 || typeof found[0].getComputedTextLength !== "function") return null;
  return Math.max(...found.map((text) => text.getComputedTextLength()));
}

/**
 * A horizontal bar chart: a name down the left for each bar, the bar to its
 * right with its segments stacked by ``d3-shape``, and the bar's value at its
 * end. Each segment is coloured by its series class, and a key beside the
 * chart names the segments when there is more than one.
 */
export function BarChart({ label, bars, segments, format, empty }: Props) {
  const [plotRef, size] = useSize<HTMLDivElement>();
  const svg = useRef<SVGSVGElement>(null);
  const [measured, setMeasured] = useState<Widths | null>(null);
  const ends = bars.map(format);
  const widths: Widths = measured ?? { names: guess(bars.map((bar) => bar.name)), values: guess(ends) };

  useLayoutEffect(() => {
    if (!svg.current) return;
    const names = widest(svg.current, ".bar-name");
    const values = widest(svg.current, ".bar-value");
    if (names === null || values === null) return;
    setMeasured((before) => (before && Math.abs(before.names - names) < 1 && Math.abs(before.values - values) < 1 ? before : { names, values }));
  }, [bars, format]);

  const left = Math.ceil(widths.names) + PAD.gap;
  const right = Math.max(left + 1, size.width - Math.ceil(widths.values) - PAD.gap);
  const height = PAD.top + bars.length * ROW + PAD.bottom;
  const largest = Math.max(0, ...bars.map((bar) => bar.values.reduce((sum, value) => sum + value, 0)));
  const x = scaleLinear()
    .domain([0, Math.max(largest, 1)])
    .range([left, right]);
  const keys = segments.map((_name, index) => index);
  const stacked = stack<Bar, number>()
    .keys(keys)
    .value((bar, key) => bar.values[key] ?? 0)(bars);

  return (
    <ChartFrame plotRef={plotRef} legend={segments.length > 1 ? segments.map((name) => ({ name })) : []} legendLabel="Key" swatch="box" kind="bars">
      {bars.length === 0 ? (
        <p className="chart-empty">{empty}</p>
      ) : (
        <svg ref={svg} className="chart-svg bar-chart" width={size.width} height={height} style={{ height }} role="list" aria-label={label}>
          {bars.map((bar, row) => {
            const top = PAD.top + row * ROW;
            const end = x(stacked[stacked.length - 1][row][1]);
            return (
              <g key={bar.name} role="listitem" aria-label={`${bar.name}, ${ends[row]}`}>
                <text className="bar-name" x={left - PAD.gap} y={top + ROW / 2} dy="0.32em" textAnchor="end" aria-hidden="true">
                  {bar.name}
                </text>
                {stacked.map((series, segment) => {
                  const [from, to] = series[row];
                  return to > from ? (
                    <rect key={segment} className={`chart-bar ${seriesClass(segment)}`} x={x(from)} y={top + 4} width={Math.max(x(to) - x(from), 1)} height={ROW - 8} />
                  ) : null;
                })}
                <text className="bar-value" x={end + PAD.gap / 2} y={top + ROW / 2} dy="0.32em" aria-hidden="true">
                  {ends[row]}
                </text>
              </g>
            );
          })}
        </svg>
      )}
    </ChartFrame>
  );
}
