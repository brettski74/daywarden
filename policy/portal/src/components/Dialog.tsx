import { useId, type KeyboardEvent } from "react";

type Props = {
  title: string;
  message: string;
  /** The button that does the thing, such as Leave or Retire. */
  confirm: string;
  /** The button that changes nothing, such as Stay or Cancel. It has the focus, so Enter and Escape choose it. */
  cancel: string;
  onConfirm: () => void;
  onCancel: () => void;
};

/** Ask before something that cannot be taken back. Changing nothing is the default. */
export function Dialog({ title, message, confirm, cancel, onConfirm, onCancel }: Props) {
  const heading = useId();
  const text = useId();

  function key(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onCancel();
    }
  }

  return (
    <div className="dialog-backdrop">
      <div className="dialog" role="alertdialog" aria-modal="true" aria-labelledby={heading} aria-describedby={text} onKeyDown={key}>
        <h2 id={heading}>{title}</h2>
        <p id={text}>{message}</p>
        <div className="dialog-buttons">
          <button type="button" className="button button-quiet" onClick={onConfirm}>
            {confirm}
          </button>
          <button type="button" className="button" autoFocus onClick={onCancel}>
            {cancel}
          </button>
        </div>
      </div>
    </div>
  );
}
