import { Check, ChevronDown, type LucideIcon } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState, type KeyboardEvent, type RefObject } from "react";
import { useExpander } from "../motion";

export type Choice = {
  value: string;
  label: string;
  /** Said after the label in brackets, such as "missing". */
  note?: string;
};

/** A last entry under a divider that does something other than choose, such as New directory…, which opens a dialog. */
export type Extra = { label: string; icon: LucideIcon; onChoose: () => void };

type Props = {
  label: string;
  /** The label's title, such as the policy file's field name. */
  title?: string;
  options: Choice[];
  value: string;
  onChange: (value: string) => void;
  icon: LucideIcon;
  extra?: Extra;
  changed?: boolean;
  disabled?: boolean;
  /** Why the pull-down is disabled, shown as its title. */
  disabledTitle?: string;
  problem?: string | null;
  buttonRef?: RefObject<HTMLButtonElement | null>;
};

/**
 * A pull-down list where one option is chosen, each option with an icon.
 *
 * It sits in a settings grid: its label, then the pull-down, then any
 * problem under both. Closed, it shows the chosen option. Open, the chosen
 * option is highlighted with a tick, and one click, Space, or Enter chooses
 * an option and closes it. The arrow keys move between options. Escape,
 * Tab, or a click elsewhere closes it.
 */
export function SelectOne({ label, title, options, value, onChange, icon: Icon, extra, changed, disabled, disabledTitle, problem, buttonRef }: Props) {
  const [open, setOpen] = useState(false);
  const { shown, moving, toggle } = useExpander(open, setOpen);
  const [active, setActive] = useState(0);
  const root = useRef<HTMLDivElement>(null);
  const ownButton = useRef<HTMLButtonElement>(null);
  const button = buttonRef ?? ownButton;
  const list = useRef<HTMLUListElement>(null);
  const labelId = useId();
  const summaryId = useId();
  const listId = useId();
  const chosen = options.find((option) => option.value === value);
  const count = options.length + (extra ? 1 : 0);

  const close = useCallback(
    (refocus: boolean) => {
      if (!open) return;
      toggle();
      if (refocus) button.current?.focus();
    },
    [open, toggle, button],
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

  function opening() {
    if (!open) setActive(Math.max(0, options.findIndex((option) => option.value === value)));
    toggle();
  }

  function choose(index: number) {
    setActive(index);
    if (index === options.length && extra) {
      close(false);
      extra.onChoose();
      return;
    }
    const option = options[index];
    if (option === undefined) return;
    close(true);
    if (option.value !== value) onChange(option.value);
  }

  function key(event: KeyboardEvent<HTMLUListElement>) {
    const last = count - 1;
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
      choose(active);
    } else if (event.key === "Escape") {
      event.preventDefault();
      close(true);
    } else if (event.key === "Tab") {
      close(false);
    }
  }

  return (
    <>
      <span id={labelId} className="select-one-label" title={title}>
        {label}
      </span>
      <div className="select-one" ref={root} data-open={open || undefined} data-moving={moving || undefined}>
        <button
          type="button"
          ref={button}
          className="select-one-button"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-controls={listId}
          aria-labelledby={`${labelId} ${summaryId}`}
          aria-invalid={problem ? true : undefined}
          data-changed={changed || undefined}
          disabled={disabled}
          title={disabled ? disabledTitle : undefined}
          onClick={opening}
        >
          <Icon className="select-one-icon" aria-hidden="true" />
          <span id={summaryId} className="select-one-summary">
            {chosen ? chosen.label : value}
            {chosen?.note && <span className="select-one-note"> ({chosen.note})</span>}
          </span>
          <ChevronDown className="select-one-chevron" aria-hidden="true" />
        </button>
        {shown && (
          <div className="select-one-panel" inert={!open}>
            <ul
              id={listId}
              ref={list}
              role="listbox"
              aria-labelledby={labelId}
              aria-activedescendant={count ? `${listId}-${active}` : undefined}
              tabIndex={-1}
              onKeyDown={key}
            >
              {options.map((option, index) => (
                <li
                  key={option.value}
                  id={`${listId}-${index}`}
                  role="option"
                  aria-selected={option.value === value}
                  data-active={index === active || undefined}
                  onClick={() => choose(index)}
                >
                  <Check className="select-one-tick" aria-hidden="true" />
                  <Icon aria-hidden="true" />
                  <span>
                    {option.label}
                    {option.note && <span className="select-one-note"> ({option.note})</span>}
                  </span>
                </li>
              ))}
              {extra && (
                <li
                  id={`${listId}-${options.length}`}
                  role="option"
                  aria-selected={false}
                  className="select-one-extra"
                  data-active={active === options.length || undefined}
                  onClick={() => choose(options.length)}
                >
                  <span className="select-one-tick" aria-hidden="true" />
                  <extra.icon aria-hidden="true" />
                  <span>{extra.label}</span>
                </li>
              )}
            </ul>
          </div>
        )}
      </div>
      {problem && <p className="note note-problem setting-problem">{problem}</p>}
    </>
  );
}
