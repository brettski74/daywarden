import { Link } from "react-router";
import { label } from "../labels";
import { POOLS } from "../pools";

const SETTINGS = ["timeout", "correct_answers_required"];
const PLACEHOLDERS: Record<string, string> = { timeout: "90s" };

/** A parts of speech task's settings as the task page has them. Its sentences are in the pools it names. */
export type PosData = { settings: Record<string, string> };

type Props = {
  data: PosData;
  settings: Record<string, string>;
  onSetting: (key: string, text: string) => void;
};

/** A parts of speech task's own settings. Its sentences are edited in their pools under Asset Administration. */
export function PartsOfSpeechAdmin({ data, settings, onSetting }: Props) {
  return (
    <section className="parts-of-speech" aria-label="Parts of speech">
      <div className="task-common">
        <fieldset>
          <legend>Parts of speech settings</legend>
          <div className="settings">
            {SETTINGS.map((key) => {
              const written = data.settings[key] ?? "";
              const shown = settings[key] ?? written;
              return (
                <label key={key} className="setting">
                  <span title={key}>{label(key)}</span>
                  <input
                    type="text"
                    inputMode={key === "timeout" ? undefined : "numeric"}
                    value={shown}
                    placeholder={PLACEHOLDERS[key]}
                    data-changed={shown.trim() !== written.trim() || undefined}
                    onChange={(event) => onSetting(key, event.target.value)}
                  />
                </label>
              );
            })}
          </div>
        </fieldset>
      </div>
      <p>
        The sentences are in the pools this task names. Edit them under Asset Administration ›{" "}
        <Link to={POOLS}>Parts of Speech Pools</Link>.
      </p>
    </section>
  );
}
