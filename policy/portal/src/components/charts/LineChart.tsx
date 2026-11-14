import { line } from "d3-shape";
import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { Axes, ChartFrame, MARGIN, Readout, dashed, plotScales, seriesClass, type AxisTick, type Tick } from "./ChartFrame";
import { useSize } from "./useSize";

export type Point = { at: number; label: string };
export type Series = { name: string; values: number[] };

type Props = {
  /** What the chart shows, said to a screen reader. */
  label: string;
  /** The length of the horizontal axis, in the units of each point's and tick's ``at``. */
  length: number;
  ticks: Tick[];
  points: Point[];
  /** One value per point for each series. */
  series: Series[];
  /** The vertical axis to at least the largest value. */
  axis: (largest: number) => { max: number; ticks: AxisTick[] };
  format: (value: number) => string;
  /** Said in place of the lines when every value is zero. */
  empty: string;
};

type Focus = { line: number; point: number };

/** How far from a line, in pixels, the pointer is still on it. */
const REACH = 14;
/** With this many points or fewer, each point is marked with a dot. */
const DOTTED = 50;

/**
 * A line chart: one line per series across the points, a legend naming each
 * series with its total, and a readout of the point the pointer is on.
 *
 * Each line is focusable. Focused, the readout starts on its largest point,
 * and the left and right arrow keys, Home, and End move along it.
 */
export function LineChart({ label, length, ticks, points, series, axis, format, empty }: Props) {
  const [plotRef, size] = useSize<HTMLDivElement>();
  const svg = useRef<SVGSVGElement>(null);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [seen, setSeen] = useState(series);
  if (seen !== series) {
    setSeen(series);
    setFocus(null);
  }
  const largest = Math.max(0, ...series.flatMap((each) => each.values));
  const drawn = largest > 0 ? series : [];
  const yAxis = axis(largest);
  const { x, y } = plotScales(size, length, yAxis.max);
  const path = line<number>()
    .x((_value, index) => x(points[index].at))
    .y((value) => y(value));
  const totals = drawn.map((each) => each.values.reduce((sum, value) => sum + value, 0));
  const shown = focus !== null && drawn[focus.line] !== undefined && points[focus.point] !== undefined ? focus : null;

  function peak(index: number): number {
    const values = drawn[index].values;
    return values.indexOf(Math.max(...values));
  }

  function nearest(left: number, top: number): Focus | null {
    if (drawn.length === 0 || points.length === 0) return null;
    let point = 0;
    points.forEach((each, index) => {
      if (Math.abs(x(each.at) - left) < Math.abs(x(points[point].at) - left)) point = index;
    });
    const found = points.findIndex((each) => x(each.at) >= left);
    const after = found === -1 ? points.length - 1 : found;
    const before = Math.max(0, after - 1);
    const [x0, x1] = [x(points[before].at), x(points[after].at)];
    const along = x1 === x0 ? 0 : Math.min(Math.max((left - x0) / (x1 - x0), 0), 1);
    let best: number | null = null;
    let gap = REACH;
    drawn.forEach((each, index) => {
      const [y0, y1] = [y(each.values[before]), y(each.values[after])];
      const distance = Math.abs(y0 + (y1 - y0) * along - top);
      if (distance <= gap) {
        best = index;
        gap = distance;
      }
    });
    return best === null ? null : { line: best, point };
  }

  function pointed(event: PointerEvent<SVGRectElement>) {
    const box = svg.current?.getBoundingClientRect();
    if (!box) return;
    setFocus(nearest(event.clientX - box.left, event.clientY - box.top));
  }

  function key(index: number, event: KeyboardEvent<SVGPathElement>) {
    const last = points.length - 1;
    const at = focus?.line === index ? focus.point : peak(index);
    const moves: Record<string, number> = { ArrowLeft: at - 1, ArrowRight: at + 1, Home: 0, End: last };
    if (!(event.key in moves)) return;
    event.preventDefault();
    setFocus({ line: index, point: Math.min(Math.max(moves[event.key], 0), last) });
  }

  const [left, right] = x.range();
  const [bottom, top] = y.range();
  const marked = shown === null ? null : { left: x(points[shown.point].at), top: y(drawn[shown.line].values[shown.point]) };

  return (
    <ChartFrame plotRef={plotRef} legend={drawn.map((each, index) => ({ name: each.name, total: format(totals[index]) }))} legendLabel="Legend">
      <svg ref={svg} className="chart-svg" width={size.width} height={size.height} role="group" aria-label={label}>
        <Axes x={x} y={y} xTicks={ticks} yTicks={yAxis.ticks} />
        <rect className="chart-hit" x={left} y={top} width={right - left} height={bottom - top} onPointerMove={pointed} onPointerLeave={() => setFocus(null)} />
        {drawn.map((each, index) => (
          <g key={each.name} className={seriesClass(index)}>
            <path
              className="chart-line"
              data-dashed={dashed(index) || undefined}
              d={path(each.values) ?? ""}
              tabIndex={0}
              role="img"
              aria-label={`${each.name}, ${format(totals[index])}`}
              onFocus={() => setFocus({ line: index, point: peak(index) })}
              onBlur={() => setFocus(null)}
              onKeyDown={(event) => key(index, event)}
            />
            {points.length <= DOTTED &&
              each.values.map((value, point) => <circle key={point} className="chart-dot" cx={x(points[point].at)} cy={y(value)} r={2.5} />)}
          </g>
        ))}
        {shown !== null && marked !== null && <circle className={`chart-marker ${seriesClass(shown.line)}`} cx={marked.left} cy={marked.top} r={5} />}
      </svg>
      {shown !== null && marked !== null && (
        <Readout
          left={marked.left}
          top={marked.top}
          flip={marked.left > MARGIN.left + (size.width - MARGIN.left) * 0.6}
          text={`${points[shown.point].label}, ${drawn[shown.line].name}, ${format(drawn[shown.line].values[shown.point])}`}
        />
      )}
      {drawn.length === 0 && <p className="chart-empty">{empty}</p>}
    </ChartFrame>
  );
}
