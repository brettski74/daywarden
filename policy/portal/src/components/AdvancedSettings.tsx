import { ChevronRight, RotateCcw, Scissors } from "lucide-react";
import { useId, useRef, type KeyboardEvent } from "react";
import {
  CUT_FIELDS,
  DEFAULT_TEXTS,
  cutSettings,
  cutValue,
  defaultText,
  differsFromDefault,
  sliderValue,
  type CutField,
  type CutTexts,
} from "../cutSettings";
import { useExpander } from "../motion";

type Props = {
  texts: CutTexts;
  onChange: (texts: CutTexts) => void;
  /** The section's expander from ``useExpander``, so the dialog can open it too. */
  expander: { expanded: boolean } & ReturnType<typeof useExpander>;
  /** Whether there is a take to cut and nothing else is under way. */
  canCut: boolean;
  onCut: () => void;
};

function isReset(event: KeyboardEvent) {
  return event.altKey && !event.ctrlKey && !event.metaKey && (event.code === "KeyR" || event.key.toLowerCase() === "r");
}

/** The cut settings, collapsed until opened, each with a way back to its bin/cut-clips default. */
export function AdvancedSettings({ texts, onChange, expander, canCut, onCut }: Props) {
  const { expanded, shown, moving, toggle } = expander;
  const heading = useId();
  const panel = useId();
  const anyDiffers = CUT_FIELDS.some((field) => differsFromDefault(field, texts[field.key]));
  const valid = cutSettings(texts) !== null;

  function sectionKey(event: KeyboardEvent<HTMLElement>) {
    if (isReset(event) && event.shiftKey) {
      event.preventDefault();
      onChange(DEFAULT_TEXTS);
    }
  }

  return (
    <section className="advanced" aria-labelledby={heading} data-open={expanded || undefined} data-moving={moving || undefined} onKeyDown={sectionKey}>
      <div className="advanced-heading">
        <button type="button" className="advanced-toggle" aria-expanded={expanded} aria-controls={panel} onClick={toggle}>
          <ChevronRight className="advanced-chevron" aria-hidden="true" />
          <span id={heading}>Advanced</span>
        </button>
        {anyDiffers && (
          <button
            type="button"
            className="button button-quiet"
            title="Put every setting back to its bin/cut-clips default (Alt+Shift+R)"
            onClick={() => onChange(DEFAULT_TEXTS)}
          >
            <RotateCcw aria-hidden="true" />
            Reset all
          </button>
        )}
      </div>
      {shown && (
        <div className="advanced-panel" id={panel} inert={!expanded}>
          <div className="advanced-body">
            {CUT_FIELDS.map((field) => (
              <CutFieldRow key={field.key} field={field} text={texts[field.key]} onText={(text) => onChange({ ...texts, [field.key]: text })} />
            ))}
            <div className="advanced-cut">
              <button type="button" className="button" disabled={!canCut || !valid} onClick={onCut} title={valid ? "Cut the same recording again with these settings" : "Fix the settings first"}>
                <Scissors aria-hidden="true" />
                Cut
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function CutFieldRow({ field, text, onText }: { field: CutField; text: string; onText: (text: string) => void }) {
  const box = useId();
  const error = useId();
  const number = useRef<HTMLInputElement>(null);
  const invalid = cutValue(field, text) === null;
  const differs = differsFromDefault(field, text);
  const resetLabel = `Reset ${field.label.toLowerCase()} to ${defaultText(field)}`;

  function reset() {
    onText(String(field.defaultValue));
    number.current?.focus();
  }

  function key(event: KeyboardEvent<HTMLDivElement>) {
    if (isReset(event) && !event.shiftKey) {
      event.preventDefault();
      reset();
    }
  }

  return (
    <div className="cut-field" onKeyDown={key}>
      <label htmlFor={box} title={`bin/cut-clips --${field.key.replace("_", "-")}`}>
        {field.label}
      </label>
      <div className="cut-controls">
        {field.slider ? (
          <input
            type="range"
            aria-label={field.label}
            min={field.slider.min}
            max={field.slider.max}
            step={field.slider.step}
            value={sliderValue(field, text)}
            onChange={(event) => onText(event.target.value)}
            onDoubleClick={reset}
            title="Double-click to reset"
          />
        ) : (
          <span />
        )}
        <input
          id={box}
          ref={number}
          type="text"
          inputMode="decimal"
          className="cut-number"
          value={text}
          aria-invalid={invalid || undefined}
          aria-describedby={invalid ? error : undefined}
          data-changed={differs || undefined}
          onChange={(event) => onText(event.target.value)}
        />
        <span>{field.unit}</span>
        <span>
          {differs && (
            <button type="button" className="icon-button icon-button-quiet" aria-label={resetLabel} title={resetLabel} onClick={reset}>
              <RotateCcw aria-hidden="true" />
            </button>
          )}
        </span>
      </div>
      {invalid && (
        <span className="field-error" id={error}>
          {field.message}
        </span>
      )}
    </div>
  );
}
