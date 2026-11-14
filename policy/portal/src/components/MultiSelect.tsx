import { Check, ChevronDown } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { useExpander } from "../motion";

type Props = {
  label: string;
  options: string[];
  selected: string[];
  onToggle: (option: string) => void;
  changed?: boolean;
  /** What the closed pull-down says with nothing chosen, None unless given. */
  empty?: string;
  disabled?: boolean;
  /** Why the pull-down is disabled, shown as its title. */
  disabledTitle?: string;
};

/**
 * A pull-down list where any number of options can be chosen.
 *
 * Closed, it shows the chosen options as a comma-separated list. Open, the
 * chosen options are highlighted, and one click, Space, or Enter turns an
 * option on or off. The arrow keys move between options. Escape, Tab, or a
 * click elsewhere closes it.
 */
export function MultiSelect({ label, options, selected, onToggle, changed, empty = "None", disabled, disabledTitle }: Props) {
  const [open, setOpen] = useState(false);
  const { shown, moving, toggle } = useExpander(open, setOpen);
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLUListElement>(null);
  const labelId = useId();
  const summaryId = useId();
  const listId = useId();
  const chosen = options.filter((option) => selected.includes(option));

  const close = useCallback(
    (refocus: boolean) => {
      if (!open) return;
      toggle();
      if (refocus) button.current?.focus();
    },
    [open, toggle],
  );

  useEffect(() => {
    if (!open) return;
    list.current?.focus();
    function away(event: PointerEvent) {
      if (!root.current?.contains(event.target as Node)) close(false);
    }
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open, close]);

  function key(event: KeyboardEvent<HTMLUListElement>) {
    const last = options.length - 1;
    const moves: Record<string, number> = {
      ArrowDown: Math.min(active + 1, last),
      ArrowUp: Math.max(active - 1, 0),
      Home: 0,
      End: last,
    };
    if (event.key in moves) {
      event.preventDefault();
      setActive(moves[event.key]);
    } else if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      if (options[active] !== undefined) onToggle(options[active]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      close(true);
    } else if (event.key === "Tab") {
      close(false);
    }
  }

  return (
    <div className="multi-select" ref={root} data-open={open || undefined} data-moving={moving || undefined}>
      <span id={labelId} className="multi-select-label">
        {label}
      </span>
      <button
        type="button"
        ref={button}
        className="multi-select-button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-labelledby={`${labelId} ${summaryId}`}
        data-changed={changed || undefined}
        disabled={disabled}
        title={disabled ? disabledTitle : undefined}
        onClick={toggle}
      >
        <span id={summaryId} className="multi-select-summary">
          {chosen.length ? chosen.join(", ") : empty}
        </span>
        <ChevronDown className="multi-select-chevron" aria-hidden="true" />
      </button>
      {shown && (
        <div className="multi-select-panel" inert={!open}>
          <ul
            id={listId}
            ref={list}
            role="listbox"
            aria-multiselectable="true"
            aria-labelledby={labelId}
            aria-activedescendant={options.length ? `${listId}-${active}` : undefined}
            tabIndex={-1}
            onKeyDown={key}
          >
            {options.map((option, index) => (
              <li
                key={option}
                id={`${listId}-${index}`}
                role="option"
                aria-selected={selected.includes(option)}
                data-active={index === active || undefined}
                onClick={() => {
                  setActive(index);
                  onToggle(option);
                }}
              >
                <Check aria-hidden="true" />
                {option}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
