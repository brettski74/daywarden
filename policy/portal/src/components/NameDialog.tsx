import { useId, useState, type FormEvent, type KeyboardEvent } from "react";

type Props = {
  title: string;
  /** The text box's label, such as "Name, under spelling/". */
  label: string;
  /** Send the name. Resolve to null when it was accepted, or to why it was refused, shown under the box. */
  onSubmit: (name: string) => Promise<string | null>;
  onCancel: () => void;
};

/** Ask for a name, such as a new directory's, with OK and Cancel. The box has the focus, so Enter is OK and Escape is Cancel. */
export function NameDialog({ title, label, onSubmit, onCancel }: Props) {
  const heading = useId();
  const box = useId();
  const why = useId();
  const [name, setName] = useState("");
  const [refused, setRefused] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    const problem = await onSubmit(name);
    setBusy(false);
    setRefused(problem);
  }

  function key(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onCancel();
    }
  }

  return (
    <div className="dialog-backdrop">
      <div className="dialog name-dialog" role="dialog" aria-modal="true" aria-labelledby={heading} onKeyDown={key}>
        <h2 id={heading}>{title}</h2>
        <form onSubmit={submit}>
          <label htmlFor={box}>{label}</label>
          <input
            id={box}
            type="text"
            value={name}
            spellCheck={false}
            autoFocus
            aria-invalid={refused !== null || undefined}
            aria-describedby={refused !== null ? why : undefined}
            onChange={(event) => setName(event.target.value)}
          />
          {refused !== null && (
            <p id={why} className="note note-problem" role="alert">
              {refused}
            </p>
          )}
          <div className="dialog-buttons">
            <button type="button" className="button button-quiet" onClick={onCancel}>
              Cancel
            </button>
            <button type="submit" className="button" disabled={busy}>
              OK
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
