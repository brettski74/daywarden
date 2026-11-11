import { Note, WeightedTable } from "../components/WeightedTable";
import { label } from "../labels";
import type { NumberRow } from "../numberTable";
import { NO_FIRST, NO_OPERANDS, SETTINGS, USES, hasNumbers, type ArithmeticData, type ShownArithmetic } from "../arithmetic";

type Props = {
  data: ArithmeticData;
  settings: Record<string, string>;
  shown: ShownArithmetic;
  onSetting: (key: string, text: string) => void;
  onRows: (field: "first" | "operands", change: (rows: NumberRow[]) => NumberRow[]) => void;
};

/** An arithmetic task's operation, its timer and target, and the two lists its numbers are drawn from. */
export function ArithmeticAdmin({ data, settings, shown, onSetting, onRows }: Props) {
  const written = (key: string) => data.settings[key] ?? "";
  const value = (key: string) => settings[key] ?? written(key);
  const operations = data.operations.some((operation) => operation.name === shown.operation)
    ? data.operations
    : [...data.operations, { name: shown.operation, label: shown.operation }];

  return (
    <section className="arithmetic" aria-label="Arithmetic">
      <div className="task-common">
        <fieldset>
          <legend>Arithmetic settings</legend>
          <div className="settings">
            <label className="setting">
              <span title="operation">{label("operation")}</span>
              <select
                value={value("operation")}
                aria-invalid={shown.settingProblems.operation !== undefined || undefined}
                data-changed={value("operation") !== written("operation") || undefined}
                onChange={(event) => onSetting("operation", event.target.value)}
              >
                {operations.map((operation) => (
                  <option key={operation.name} value={operation.name}>
                    {operation.label}
                  </option>
                ))}
              </select>
            </label>
            {shown.settingProblems.operation && <p className="note note-problem setting-problem">{shown.settingProblems.operation}</p>}
            {SETTINGS.map((key) => (
              <Setting key={key} name={key} value={value(key)} written={written(key)} problem={shown.settingProblems[key]} onSetting={onSetting} />
            ))}
          </div>
        </fieldset>
      </div>

      {data.problems.map((problem) => (
        <p key={problem} className="problem">
          {problem}
        </p>
      ))}

      <div className="number-lists">
        <WeightedTable
          label="First"
          field="first"
          rows={shown.first.rows}
          originals={shown.first.originals}
          problems={shown.firstProblems}
          onRows={(change) => onRows("first", change)}
          below={!hasNumbers(shown.first.rows) && <Note>{NO_FIRST}</Note>}
        />
        <WeightedTable
          label="Operands"
          field="operands"
          rows={shown.operands.rows}
          originals={shown.operands.originals}
          problems={shown.operandProblems}
          onRows={(change) => onRows("operands", change)}
          below={!hasNumbers(shown.operands.rows) && <Note problem>{NO_OPERANDS}</Note>}
        />
      </div>
      {USES[shown.operation] && <p className="number-uses">Each question is {USES[shown.operation]}.</p>}
    </section>
  );
}

type SettingProps = { name: string; value: string; written: string; problem: string | undefined; onSetting: (key: string, text: string) => void };

function Setting({ name, value, written, problem, onSetting }: SettingProps) {
  return (
    <>
      <label className="setting">
        <span title={name}>{label(name)}</span>
        <input
          type="text"
          inputMode={name === "correct_answers_required" ? "numeric" : undefined}
          value={value}
          aria-invalid={problem !== undefined || undefined}
          data-changed={value.trim() !== written.trim() || undefined}
          onChange={(event) => onSetting(name, event.target.value)}
        />
      </label>
      {problem && (
        <p className="note note-problem setting-problem">
          {problem}
        </p>
      )}
    </>
  );
}
