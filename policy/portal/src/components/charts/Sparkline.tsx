import { scaleLinear } from "d3-scale";
import { line } from "d3-shape";
import { seriesClass } from "./ChartFrame";

const WIDTH = 120;
const HEIGHT = 28;
const PAD = 3;

/**
 * A small inline line of each attempt's points and pass mark, oldest to newest, with no interaction.
 * A screen reader hears ``label`` in its place.
 */
export function Sparkline({ values, label }: { values: { points: number; pass_mark: number | null }[]; label: string }) {
  const largest = Math.max(1, ...values.flatMap((each) => [each.points, each.pass_mark ?? 0]));
  const x = scaleLinear()
    .domain([0, Math.max(values.length - 1, 1)])
    .range(values.length === 1 ? [WIDTH / 2, WIDTH / 2] : [PAD, WIDTH - PAD]);
  const y = scaleLinear().domain([0, largest]).range([HEIGHT - PAD, PAD]);
  const path = line<number | null>()
    .defined((value) => value !== null)
    .x((_value, index) => x(index))
    .y((value) => y(value as number));
  const points = values.map((each) => each.points);
  const marks = values.map((each) => each.pass_mark);
  return (
    <svg className="sparkline" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} width={WIDTH} height={HEIGHT} role="img" aria-label={label}>
      <path className={`sparkline-mark ${seriesClass(1)}`} d={path(marks) ?? ""} />
      <path className={`sparkline-points ${seriesClass(0)}`} d={path(points) ?? ""} />
      {values.length === 1 && <circle className={seriesClass(0)} cx={x(0)} cy={y(points[0])} r={2} />}
    </svg>
  );
}
