import { Info, ListRestart } from "lucide-react";
import { Note, WeightedTable } from "../components/WeightedTable";
import { label } from "../labels";
import { isEmpty, type NumberRow } from "../numberTable";
import {
  DEFAULT_NOTE,
  FLAGS,
  NO_DIFFERENCES,
  QUESTION_SETTINGS,
  SESSION_SETTINGS,
  flagEdit,
  flagOf,
  placeholderOf,
  taskBounds,
  type ShownDifference,
  type SkipData,
} from "../skipCounting";

type Props = {
  data: SkipData;
  settings: Record<string, string>;
  shown: ShownDifference;
  problems: string[][];
  onSetting: (key: string, text: string) => void;
  /** Change the rows on show. A default list shown becomes the task's own list. */
  onRows: (change: (rows: NumberRow[]) => NumberRow[]) => void;
  onDefault: () => void;
};

const GROUPS = [
  { legend: "Questions", keys: QUESTION_SETTINGS },
  { legend: "Session", keys: SESSION_SETTINGS },
];

/** A skip counting task's own settings and its differences. */
export function SkipCountingAdmin({ data, settings, shown, problems, onSetting, onRows, onDefault }: Props) {
  return (
    <section className="skip-counting" aria-label="Skip counting">
      <div className="task-common">
        {GROUPS.map(({ legend, keys }) => (
          <fieldset key={legend}>
            <legend>{legend}</legend>
            <div className="settings">
              {keys.map((key) => (FLAGS.includes(key) ? <Flag key={key} name={key} {...{ data, settings, onSetting }} /> : <Setting key={key} name={key} {...{ data, settings, onSetting }} />))}
            </div>
          </fieldset>
        ))}
      </div>

      {data.problems.map((problem) => (
        <p key={problem} className="problem">
          {problem}
        </p>
      ))}

      <WeightedTable
        label="Differences"
        field="difference"
        rows={shown.rows}
        originals={shown.originals}
        problems={problems}
        bounds
        placeholders={taskBounds(data, settings)}
        onRows={onRows}
        above={
          shown.isDefault && (
            <p className="note">
              <Info aria-hidden="true" />
              {DEFAULT_NOTE}
            </p>
          )
        }
        beside={
          !shown.isDefault && (
            <button type="button" className="button button-quiet" onClick={onDefault}>
              <ListRestart aria-hidden="true" />
              Use the default list
            </button>
          )
        }
        below={shown.rows.every(isEmpty) && <Note problem>{NO_DIFFERENCES}</Note>}
      />
    </section>
  );
}

type SettingProps = { name: string; data: SkipData; settings: Record<string, string>; onSetting: (key: string, text: string) => void };

function Setting({ name, data, settings, onSetting }: SettingProps) {
  const written = data.settings[name] ?? "";
  const shown = settings[name] ?? written;
  return (
    <label className="setting">
      <span title={name}>{label(name)}</span>
      <input
        type="text"
        inputMode={name === "timeout" ? undefined : "numeric"}
        value={shown}
        placeholder={placeholderOf(data, settings, name)}
        data-changed={shown.trim() !== written.trim() || undefined}
        onChange={(event) => onSetting(name, event.target.value)}
      />
    </label>
  );
}

function Flag({ name, data, settings, onSetting }: SettingProps) {
  const ticked = flagOf(data, settings, name);
  return (
    <label className="setting">
      <span title={name}>{label(name)}</span>
      <span className="setting-flag" data-changed={ticked !== data.flags[name] || undefined}>
        <input type="checkbox" checked={ticked} onChange={(event) => onSetting(name, flagEdit(data, name, event.target.checked))} />
      </span>
    </label>
  );
}
