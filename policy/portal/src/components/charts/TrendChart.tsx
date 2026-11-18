import { scaleLinear } from "d3-scale";
import { line } from "d3-shape";
import { useRef, useState, type KeyboardEvent, type MouseEvent } from "react";
import { useNavigate } from "react-router";
import { BASE } from "../../api";
import { Axes, ChartFrame, Readout, seriesClass, type AxisTick, type Tick } from "./ChartFrame";
import { useSize } from "./useSize";

/** One attempt across the chart. ``to`` is the router address its marker opens. */
export type Marked = { id: number; at: number; outcome: string; hollow: boolean; label: string; readout: string[]; to: string };
/** One line. ``values`` has one value per marked attempt, null where the attempt has none. */
export type TrendSeries = { key: string; name: string; colour: number; values: (number | null)[]; shown: boolean; right?: boolean };
type Axis = (largest: number) => { max: number; ticks: AxisTick[] };

type Props = {
  /** What the chart shows, said to a screen reader. */
  label: string;
  length: number;
  ticks: Tick[];
  marked: Marked[];
  series: TrendSeries[];
  axis: Axis;
  /** The axis on the right, for the lines marked ``right``. */
  rightAxis?: Axis;
  onToggle: (key: string) => void;
  /** Said in place of the lines when none is shown. */
  empty: string;
};

/** The same room around the plot on every trend chart, so charts stacked one above the other share their time axis. */
const MARGIN = { top: 14, right: 64, bottom: 30, left: 76 };
const SIZE = 5;

/** The marker for an outcome, centred on 0, 0. Each outcome has its own shape, so nothing relies on colour. */
export function Shape({ outcome }: { outcome: string }) {
  const r = SIZE;
  switch (outcome) {
    case "pass":
      return <circle r={r} />;
    case "failure":
      return <rect x={-r + 0.5} y={-r + 0.5} width={2 * r - 1} height={2 * r - 1} />;
    case "abandoned":
      return <path d={`M0 ${-r - 1} L${r + 1} ${r} L${-r - 1} ${r} Z`} />;
    case "unfinished":
      return <path d={`M0 ${r + 1} L${r + 1} ${-r} L${-r - 1} ${-r} Z`} />;
    default:
      return <path d={`M0 ${-r - 1.5} L${r + 1.5} 0 L0 ${r + 1.5} L${-r - 1.5} 0 Z`} />;
  }
}

/**
 * A trend across a period: a line for each shown series through the attempts in order, and at each
 * attempt a marker whose shape tells its outcome, hollow for practice.
 *
 * Each attempt's markers are one real link to its page. Pointing at it or focusing it shows the
 * readout of every figure. Only one attempt is in the Tab order. The left and right arrow keys, Home,
 * and End move between attempts. The legend's entries show and hide the lines.
 */
export function TrendChart({ label, length, ticks, marked, series, axis, rightAxis, onToggle, empty }: Props) {
  const [plotRef, size] = useSize<HTMLDivElement>();
  const navigate = useNavigate();
  const [focused, setFocused] = useState<number | null>(null);
  const [pointed, setPointed] = useState<number | null>(null);
  const [current, setCurrent] = useState(Math.max(0, marked.length - 1));
  const links = useRef<(SVGAElement | null)[]>([]);
  const drawn = series.filter((each) => each.shown);
  const largest = (right: boolean) =>
    Math.max(0, ...drawn.filter((each) => Boolean(each.right) === right).flatMap((each) => each.values.filter((value): value is number => value !== null)));
  const leftAxis = axis(largest(false));
  const otherAxis = rightAxis ? rightAxis(largest(true)) : null;
  const right = Math.max(MARGIN.left + 1, size.width - MARGIN.right);
  const bottom = Math.max(MARGIN.top + 1, size.height - MARGIN.bottom);
  const x = scaleLinear().domain([0, Math.max(length, 1)]).range([MARGIN.left, right]);
  const y = scaleLinear().domain([0, Math.max(leftAxis.max, 1)]).range([bottom, MARGIN.top]);
  const yRight = scaleLinear().domain([0, Math.max(otherAxis?.max ?? 1, 1)]).range([bottom, MARGIN.top]);
  const scaleOf = (each: TrendSeries) => (each.right ? yRight : y);
  const active = Math.min(current, Math.max(0, marked.length - 1));
  const showing = pointed ?? focused;

  function tops(index: number): number[] {
    return drawn.flatMap((each) => (each.values[index] === null ? [] : [scaleOf(each)(each.values[index] as number)]));
  }

  function move(index: number, event: KeyboardEvent<SVGAElement>) {
    const last = marked.length - 1;
    const moves: Record<string, number> = { ArrowLeft: index - 1, ArrowRight: index + 1, Home: 0, End: last };
    if (event.key === "Enter") {
      event.preventDefault();
      navigate(marked[index].to);
      return;
    }
    if (!(event.key in moves)) return;
    event.preventDefault();
    const next = Math.min(Math.max(moves[event.key], 0), last);
    setCurrent(next);
    links.current[next]?.focus();
  }

  function open(index: number, event: MouseEvent<SVGAElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    navigate(marked[index].to);
  }

  const reading = showing !== null && marked[showing] !== undefined && tops(showing).length > 0 ? showing : null;

  return (
    <ChartFrame
      plotRef={plotRef}
      legend={series.map((each) => ({ name: each.name, colour: each.colour, pressed: each.shown }))}
      legendLabel="Lines"
      onPick={(name) => {
        const found = series.find((each) => each.name === name);
        if (found) onToggle(found.key);
      }}
      pickTitle={(name) => (series.find((each) => each.name === name)?.shown ? `Hide ${name}` : `Show ${name}`)}
    >
      <svg className="chart-svg" width={size.width} height={size.height} role="group" aria-label={label}>
        <Axes x={x} y={y} xTicks={ticks} yTicks={leftAxis.ticks} />
        {otherAxis && drawn.some((each) => each.right) && (
          <g className="chart-axis" aria-hidden="true">
            <line x1={right} x2={right} y1={MARGIN.top} y2={bottom} />
            {otherAxis.ticks.map((tick) => (
              <g key={tick.value} transform={`translate(${right}, ${yRight(tick.value)})`}>
                <line x2={5} />
                <text x={9} dy="0.32em" textAnchor="start">
                  {tick.label}
                </text>
              </g>
            ))}
          </g>
        )}
        {drawn.map((each) => {
          const scale = scaleOf(each);
          const path = line<number | null>()
            .defined((value) => value !== null)
            .x((_value, index) => x(marked[index].at))
            .y((value) => scale(value as number));
          return (
            <path key={each.key} className={`chart-line ${seriesClass(each.colour)}`} data-dashed={each.right || undefined} d={path(each.values) ?? ""} />
          );
        })}
        {drawn.length > 0 &&
          marked.map((point, index) => {
            const left = x(point.at);
            const shapes = drawn.filter((each) => each.values[index] !== null);
            if (shapes.length === 0) return null;
            return (
              <a
                key={point.id}
                ref={(element) => {
                  links.current[index] = element as unknown as SVGAElement | null;
                }}
                href={BASE + point.to}
                className="trend-attempt"
                tabIndex={index === active ? 0 : -1}
                aria-label={point.label}
                onFocus={() => {
                  setCurrent(index);
                  setFocused(index);
                }}
                onBlur={() => setFocused(null)}
                onPointerEnter={() => setPointed(index)}
                onPointerLeave={() => setPointed(null)}
                onKeyDown={(event) => move(index, event as unknown as KeyboardEvent<SVGAElement>)}
                onClick={(event) => open(index, event as unknown as MouseEvent<SVGAElement>)}
              >
                {shapes.map((each) => (
                  <g
                    key={each.key}
                    className={`trend-marker ${seriesClass(each.colour)}`}
                    data-outcome={point.outcome}
                    data-hollow={point.hollow || undefined}
                    data-on={index === reading || undefined}
                    transform={`translate(${left}, ${scaleOf(each)(each.values[index] as number)})`}
                  >
                    <Shape outcome={point.outcome} />
                  </g>
                ))}
              </a>
            );
          })}
      </svg>
      {reading !== null && (
        <Readout
          left={x(marked[reading].at)}
          top={Math.min(...tops(reading))}
          flip={x(marked[reading].at) > MARGIN.left + (size.width - MARGIN.left) * 0.6}
          text={marked[reading].readout}
        />
      )}
      {drawn.length === 0 && <p className="chart-empty">{empty}</p>}
    </ChartFrame>
  );
}
