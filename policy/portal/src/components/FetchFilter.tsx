import { FETCH_LEVELS, type FetchLevel } from "../usage";

type Props = {
  level: FetchLevel;
  hideHops: boolean;
  /** Called with the level and checkbox to show. Choosing a documents level from All requests checks Hide redirect hops. */
  onChange: (level: FetchLevel, hideHops: boolean) => void;
};

/** The Fetch pull-down and, at a documents level, the Hide redirect hops checkbox. */
export function FetchFilter({ level, hideHops, onChange }: Props) {
  return (
    <>
      <label className="bar-field">
        Fetch
        <select
          value={level}
          onChange={(event) => {
            const next = event.target.value as FetchLevel;
            onChange(next, level === "all" ? true : hideHops);
          }}
        >
          {FETCH_LEVELS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {level !== "all" && (
        <label className="bar-field">
          <input type="checkbox" checked={hideHops} onChange={(event) => onChange(level, event.target.checked)} />
          Hide redirect hops
        </label>
      )}
    </>
  );
}
