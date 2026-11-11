import { CircleX, Plus, SquareMinus, SquarePen, SquarePlus, Trash2, TriangleAlert } from "lucide-react";
import {
  Fragment,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import { Dialog } from "../components/Dialog";
import { label } from "../labels";
import { useExpander } from "../motion";
import {
  DEFAULT_TIMEOUT,
  LONGEST_NAME,
  NO_SENTENCES,
  defaultRequired,
  newId,
  newRow,
  place,
  problems,
  retext,
  rowChanged,
  rowOf,
  segments,
  unsort,
  warnings,
  type Block,
  type PosData,
  type PosSentence,
  type Row,
} from "../sentences";
import { wordSort } from "../wordSort";

const FLIGHT_MS = 600;
const SETTINGS = ["timeout", "correct_answers_required"];
export const ADD_TITLE = "Add sentence (Alt+N)";

type Props = {
  data: PosData;
  blocks: Block[];
  settings: Record<string, string>;
  onSetting: (key: string, text: string) => void;
  onBlocks: (change: (blocks: Block[]) => Block[]) => void;
};

type Editing = { id: string; before: string; draft: string };
type Asking = { kind: "cleared"; block: string; before: string } | { kind: "delete"; block: string } | { kind: "row"; block: string; row: string };
type Focus = { key: string; select?: boolean; end?: boolean; scroll?: boolean };
/** How edit mode is left: Enter, the focus going elsewhere, Escape, or the edit button. */
type Leaving = "enter" | "blur" | "escape" | "button";

function update(blocks: Block[], id: string, change: (block: Block) => Block): Block[] {
  return blocks.map((block) => (block.id === id ? change(block) : block));
}

/** A parts of speech task's own settings and its sentences, each sorted as on the child's page. */
export function PartsOfSpeechAdmin({ data, blocks, settings, onSetting, onBlocks }: Props) {
  const [editing, setEditing] = useState<Editing | null>(null);
  const [asking, setAsking] = useState<Asking | null>(null);
  const [, setTick] = useState(0);
  const root = useRef<HTMLElement>(null);
  const focusing = useRef<Focus | null>(null);
  const closed = useRef<string | null>(null);
  const latest = useRef({ blocks, editing });
  latest.current = { blocks, editing };

  const focusOn = useCallback((key: string, options: Omit<Focus, "key"> = {}) => {
    focusing.current = { key, ...options };
    setTick((tick) => tick + 1);
  }, []);

  useLayoutEffect(() => {
    const want = focusing.current;
    const element = want && root.current?.querySelector<HTMLElement>(`[data-focus="${want.key}"]`);
    if (!want || !element) return;
    focusing.current = null;
    element.focus();
    if (element instanceof HTMLInputElement) {
      if (want.select) element.select();
      else if (want.end) element.setSelectionRange(element.value.length, element.value.length);
    }
    if (want.scroll) element.scrollIntoView?.({ block: "nearest" });
  });

  const removeBlock = useCallback(
    (id: string) => {
      onBlocks((current) => current.filter((block) => block.id !== id));
      focusOn("add-sentence");
    },
    [onBlocks, focusOn],
  );

  const startEdit = (block: Block) => {
    closed.current = null;
    setEditing({ id: block.id, before: block.text, draft: block.text });
    focusOn(`text:${block.id}`, { end: true });
  };

  /** Leave a sentence's edit mode. Says whether it asked to delete the sentence. */
  const leave = useCallback(
    (id: string, how: Leaving): boolean => {
      const edit = latest.current.editing;
      if (!edit || edit.id !== id || closed.current === id) return false;
      closed.current = id;
      const block = latest.current.blocks.find((found) => found.id === id);
      const text = how === "escape" ? edit.before : edit.draft;
      if (!block) {
        setEditing(null);
        return false;
      }
      if (text.trim() === "") {
        if (edit.before.trim() !== "") {
          setAsking({ kind: "cleared", block: id, before: edit.before });
          return true;
        }
        setEditing(null);
        removeBlock(id);
        return false;
      }
      setEditing(null);
      onBlocks((current) => update(current, id, (found) => retext(found, text)));
      if (how === "escape" || how === "button") focusOn(`edit:${id}`);
      if (how === "enter") {
        const first = block.rows[0];
        if (first) {
          focusOn(`name:${first.id}`, { select: true });
        } else {
          const row = newRow();
          onBlocks((current) => update(current, id, (found) => ({ ...found, rows: [row] })));
          focusOn(`name:${row.id}`);
        }
      }
      return false;
    },
    [onBlocks, focusOn, removeBlock],
  );

  const addBlock = useCallback(() => {
    if (document.querySelector('[role="alertdialog"]')) return;
    const edit = latest.current.editing;
    if (edit && leave(edit.id, "blur")) return;
    const id = newId("s");
    onBlocks((current) => {
      const above = current[current.length - 1];
      const rows = above ? above.rows.map((row) => newRow(row.name)) : [newRow()];
      return [...current, { id, origin: null, text: "", timeout: "", rows, removed: [] }];
    });
    closed.current = null;
    setEditing({ id, before: "", draft: "" });
    focusOn(`text:${id}`, { scroll: true });
  }, [leave, onBlocks, focusOn]);

  const latestAdd = useRef(addBlock);
  latestAdd.current = addBlock;
  useEffect(() => {
    function key(event: globalThis.KeyboardEvent) {
      if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      if (event.code !== "KeyN" && event.key.toLowerCase() !== "n") return;
      if (root.current?.closest("[inert]")) return;
      event.preventDefault();
      latestAdd.current();
    }
    window.addEventListener("keydown", key, true);
    return () => window.removeEventListener("keydown", key, true);
  }, []);

  const addRow = (blockId: string) => {
    const row = newRow();
    onBlocks((current) => update(current, blockId, (block) => ({ ...block, rows: [...block.rows, row] })));
    focusOn(`name:${row.id}`);
  };

  /** Remove a row, then focus the row that took its place, or Add row when it was the last. */
  const removeRow = (blockId: string, rowId: string) => {
    const block = latest.current.blocks.find((found) => found.id === blockId);
    const index = block?.rows.findIndex((row) => row.id === rowId) ?? -1;
    const next = block?.rows[index + 1];
    onBlocks((current) => update(current, blockId, (found) => ({ ...found, rows: found.rows.filter((row) => row.id !== rowId) })));
    if (next) focusOn(`name:${next.id}`, { select: true });
    else focusOn(`addrow:${blockId}`);
  };

  const nameKey = (block: Block, row: Row, index: number, event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    if (row.name.trim() !== "") {
      const next = block.rows[index + 1];
      if (next) focusOn(`name:${next.id}`, { select: true });
      else addRow(block.id);
    } else if (row.words.length > 0) {
      setAsking({ kind: "row", block: block.id, row: row.id });
    } else {
      removeRow(block.id, row.id);
    }
  };

  const choose = (blockId: string, id: number, rowId: string | null) => {
    onBlocks((current) => update(current, blockId, (block) => (rowId === null ? unsort(block, id) : place(block, id, rowId))));
    focusOn(`word:${blockId}:${id}`);
  };

  const taskTimeout = (settings.timeout ?? data.settings.timeout ?? "").trim() || DEFAULT_TIMEOUT;
  const asked = asking && blocks.find((block) => block.id === asking.block);

  return (
    <section className="parts-of-speech" aria-label="Parts of speech" ref={root}>
      <div className="task-common">
        <fieldset>
          <legend>Parts of speech settings</legend>
          <div className="settings">
            {SETTINGS.map((key) => {
              const written = data.settings[key] ?? "";
              const shown = settings[key] ?? written;
              const placeholder = key === "timeout" ? DEFAULT_TIMEOUT : String(defaultRequired(blocks.length));
              return (
                <label key={key} className="setting">
                  <span title={key}>{label(key)}</span>
                  <input
                    type="text"
                    inputMode={key === "timeout" ? undefined : "numeric"}
                    value={shown}
                    placeholder={placeholder}
                    data-changed={shown.trim() !== written.trim() || undefined}
                    onChange={(event) => onSetting(key, event.target.value)}
                  />
                </label>
              );
            })}
          </div>
        </fieldset>
      </div>

      {data.problems.map((problem) => (
        <p key={problem} className="problem">
          {problem}
        </p>
      ))}

      {blocks.map((block, index) => (
        <SentenceBlock
          key={block.id}
          block={block}
          number={index + 1}
          original={block.origin === null ? undefined : data.sentences[block.origin]}
          editing={editing?.id === block.id ? editing : null}
          taskTimeout={taskTimeout}
          onEdit={() => startEdit(block)}
          onDraft={(draft) => setEditing((current) => (current && current.id === block.id ? { ...current, draft } : current))}
          onLeave={(how) => leave(block.id, how)}
          onDelete={() => setAsking({ kind: "delete", block: block.id })}
          onChange={(change) => onBlocks((current) => update(current, block.id, change))}
          onAddRow={() => addRow(block.id)}
          onRemoveRow={(rowId) => removeRow(block.id, rowId)}
          onNameKey={(row, rowIndex, event) => nameKey(block, row, rowIndex, event)}
          onChoose={(id, rowId) => choose(block.id, id, rowId)}
        />
      ))}

      <div className="pos-add">
        <button type="button" className="button" data-focus="add-sentence" title={ADD_TITLE} onClick={addBlock}>
          <Plus aria-hidden="true" />
          Add sentence
        </button>
        {blocks.length === 0 && (
          <p className="pos-note pos-problem">
            <CircleX aria-hidden="true" />
            {NO_SENTENCES}
          </p>
        )}
      </div>

      {asking?.kind === "cleared" && (
        <Dialog
          title="Delete this sentence?"
          message={`"${asking.before}"`}
          confirm="Delete"
          cancel="Cancel"
          onConfirm={() => {
            setAsking(null);
            setEditing(null);
            removeBlock(asking.block);
          }}
          onCancel={() => {
            setAsking(null);
            setEditing(null);
            focusOn(`edit:${asking.block}`);
          }}
        />
      )}
      {asking?.kind === "delete" && asked && (
        <Dialog
          title="Delete this sentence?"
          message={`"${asked.text}"`}
          confirm="Delete"
          cancel="Cancel"
          onConfirm={() => {
            setAsking(null);
            removeBlock(asking.block);
          }}
          onCancel={() => {
            setAsking(null);
            focusOn(`delete:${asking.block}`);
          }}
        />
      )}
      {asking?.kind === "row" && (
        <Dialog
          title="Remove this row?"
          message="Its words go back to the sentence."
          confirm="Remove"
          cancel="Cancel"
          onConfirm={() => {
            setAsking(null);
            removeRow(asking.block, asking.row);
          }}
          onCancel={() => {
            setAsking(null);
            focusOn(`name:${asking.row}`);
          }}
        />
      )}
    </section>
  );
}

type BlockProps = {
  block: Block;
  number: number;
  original: PosSentence | undefined;
  editing: Editing | null;
  taskTimeout: string;
  onEdit: () => void;
  onDraft: (text: string) => void;
  onLeave: (how: Leaving) => boolean;
  onDelete: () => void;
  onChange: (change: (block: Block) => Block) => void;
  onAddRow: () => void;
  onRemoveRow: (rowId: string) => void;
  onNameKey: (row: Row, index: number, event: KeyboardEvent<HTMLInputElement>) => void;
  onChoose: (id: number, rowId: string | null) => void;
};

/** One sentence: its text above a two-column table of its rows, laid out like the child's. */
function SentenceBlock(props: BlockProps) {
  const { block, number, original, editing, taskTimeout } = props;
  const rootRef = useRef<HTMLElement>(null);
  const latest = useRef(props);
  latest.current = props;

  useEffect(() => {
    const root = rootRef.current as HTMLElement;
    const inside = (target: EventTarget | null): HTMLElement | null => {
      const element = target instanceof Element ? target : target instanceof Node ? target.parentElement : null;
      return element && root.contains(element) ? (element as HTMLElement) : null;
    };
    const sorter = wordSort({
      sources: [root],
      flightMs: FLIGHT_MS,
      canPress: () => latest.current.editing === null,
      pickable: (target) => inside(target)?.closest<HTMLElement>("[data-pick]") ?? null,
      originOf: (id) => rowOf(latest.current.block, id)?.id ?? null,
      sentenceWord: (id) => root.querySelector<HTMLElement>(`.pos-text [data-word="${id}"]`) as HTMLElement,
      cellWord: (id) => root.querySelector<HTMLElement>(`td[data-row] [data-word="${id}"]`),
      targetAt(found) {
        const cell = inside(found)?.closest<HTMLElement>("td[data-row]");
        return cell ? { key: cell.dataset.row as string, element: cell } : null;
      },
      hoverable: (target) =>
        latest.current.editing === null ? (inside(target)?.closest<HTMLElement>(".pos-text [data-sorted], td[data-row] [data-word]") ?? null) : null,
      ghost(copy) {
        copy.className = "pos-ghost";
      },
      onPlace: (id, rowId) => latest.current.onChange((found) => place(found, id, rowId)),
      onUnsort: (id) => latest.current.onChange((found) => unsort(found, id)),
      noSelect: (target) => {
        const element = inside(target);
        return element !== null && element.closest("input") === null;
      },
      noDragImage: (target) => inside(target) !== null,
    });
    return () => sorter.destroy();
  }, []);

  const textChanged = original !== undefined && block.text !== original.text;
  const timeoutChanged = original !== undefined && block.timeout.trim() !== original.timeout.trim();
  const found = problems(block);
  const notes = warnings(block);
  const choicesFor = (row: Row | null) => [
    ...block.rows.filter((other) => other !== row).map((other) => ({ key: other.id as string | null, label: other.name.trim() || "(no name)" })),
    ...(row ? [{ key: null, label: "Not sorted" }] : []),
  ];

  const word = (id: number, text: string, row: Row | null) => (
    <WordPick
      key={`${row?.id ?? "sentence"}:${id}`}
      id={id}
      text={text}
      focusKey={`word:${block.id}:${id}`}
      choices={choicesFor(row)}
      onChoose={(rowId) => props.onChoose(id, rowId)}
    />
  );
  const pieces = segments(block.text);
  const texts = pieces.filter((piece) => piece.word !== undefined).map((piece) => piece.text);

  return (
    <section
      ref={rootRef}
      className="pos-block"
      aria-label={`Sentence ${number}`}
      data-changed={block.origin === null || undefined}
      data-editing={editing !== null || undefined}
    >
      <table className="pos-table">
        <tbody>
          <tr>
            <td colSpan={2} className="pos-sentence" data-changed={textChanged || undefined}>
              <div className="pos-sentence-line">
                {editing ? (
                  <input
                    type="text"
                    className="pos-text-input"
                    aria-label="Sentence"
                    data-focus={`text:${block.id}`}
                    value={editing.draft}
                    onChange={(event) => props.onDraft(event.target.value)}
                    onBlur={() => props.onLeave("blur")}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === "Escape") {
                        event.preventDefault();
                        props.onLeave(event.key === "Enter" ? "enter" : "escape");
                      }
                    }}
                  />
                ) : (
                  <p className="pos-text">
                    {pieces.map((piece, index) => {
                      if (piece.word === undefined) return <Fragment key={index}>{piece.text}</Fragment>;
                      if (rowOf(block, piece.word))
                        return (
                          <span key={index} data-word={piece.word} data-sorted="">
                            {piece.text}
                          </span>
                        );
                      return word(piece.word, piece.text, null);
                    })}
                  </p>
                )}
                <span className="pos-actions">
                  <IconButton
                    label="Edit sentence"
                    focus={`edit:${block.id}`}
                    onMouseDown={(event) => editing && event.preventDefault()}
                    onClick={() => (editing ? props.onLeave("button") : props.onEdit())}
                  >
                    <SquarePen aria-hidden="true" />
                  </IconButton>
                  <IconButton label="Delete sentence" focus={`delete:${block.id}`} onClick={props.onDelete}>
                    <Trash2 aria-hidden="true" />
                  </IconButton>
                </span>
              </div>
            </td>
          </tr>
          {block.rows.map((row, index) => {
            const changed = rowChanged(original, block, row);
            const known = row.origin !== null && original !== undefined;
            return (
              <tr key={row.id} data-changed={!known || undefined}>
                <th scope="row">
                  <span className="pos-name">
                    <input
                      type="text"
                      aria-label="Part of speech"
                      value={row.name}
                      maxLength={LONGEST_NAME}
                      data-focus={`name:${row.id}`}
                      data-changed={(known && changed.name) || undefined}
                      aria-invalid={row.name.trim() === "" || undefined}
                      onChange={(event) => {
                        const name = event.target.value;
                        props.onChange((current) => ({ ...current, rows: current.rows.map((other) => (other.id === row.id ? { ...other, name } : other)) }));
                      }}
                      onKeyDown={(event) => props.onNameKey(row, index, event)}
                    />
                    <IconButton label="Remove row" onClick={() => props.onRemoveRow(row.id)}>
                      <SquareMinus aria-hidden="true" />
                    </IconButton>
                  </span>
                </th>
                <td data-row={row.id} data-changed={(known && changed.words) || undefined}>
                  {row.words.map((id, place) => (
                    <Fragment key={id}>
                      {place > 0 && ", "}
                      {word(id, texts[id] ?? "", row)}
                    </Fragment>
                  ))}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div className="pos-under">
        <IconButton label="Add row" focus={`addrow:${block.id}`} onClick={props.onAddRow}>
          <SquarePlus aria-hidden="true" />
        </IconButton>
        <label className="pos-timeout">
          <span title="timeout">{label("timeout")}</span>
          <input
            type="text"
            value={block.timeout}
            placeholder={taskTimeout}
            data-changed={timeoutChanged || undefined}
            onChange={(event) => {
              const timeout = event.target.value;
              props.onChange((current) => ({ ...current, timeout }));
            }}
          />
        </label>
      </div>
      {(found.length > 0 || notes.length > 0) && (
        <ul className="pos-notes">
          {found.map((problem) => (
            <li key={problem} className="pos-note pos-problem">
              <CircleX aria-hidden="true" />
              {problem}
            </li>
          ))}
          {notes.map((note) => (
            <li key={note} className="pos-note pos-warning">
              <TriangleAlert aria-hidden="true" />
              {note}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function IconButton({
  label: name,
  focus,
  children,
  onClick,
  onMouseDown,
}: {
  label: string;
  focus?: string;
  children: ReactNode;
  onClick: () => void;
  onMouseDown?: (event: MouseEvent) => void;
}) {
  return (
    <button type="button" className="icon-button icon-button-quiet" aria-label={name} title={name} data-focus={focus} onClick={onClick} onMouseDown={onMouseDown}>
      {children}
    </button>
  );
}

type Choice = { key: string | null; label: string };

/** A word that can be picked up. Enter or Space opens a menu of where it can go, as a drop would. */
function WordPick({ id, text, focusKey, choices, onChoose }: { id: number; text: string; focusKey: string; choices: Choice[]; onChoose: (rowId: string | null) => void }) {
  const [open, setOpen] = useState(false);
  const { shown, moving, toggle } = useExpander(open, setOpen);
  const [active, setActive] = useState(0);
  const wrap = useRef<HTMLSpanElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLSpanElement>(null);
  const menuId = useId();

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
    menu.current?.focus();
    function away(event: PointerEvent) {
      if (!wrap.current?.contains(event.target as Node)) close(false);
    }
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open, close]);

  function pick(choice: Choice) {
    toggle();
    onChoose(choice.key);
  }

  function wordKey(event: KeyboardEvent<HTMLButtonElement>) {
    if (event.key !== "Enter" && event.key !== " ") return;
    event.preventDefault();
    if (!open && choices.length > 0) {
      setActive(0);
      toggle();
    }
  }

  function menuKey(event: KeyboardEvent<HTMLSpanElement>) {
    const last = choices.length - 1;
    const moves: Record<string, number> = { ArrowDown: Math.min(active + 1, last), ArrowUp: Math.max(active - 1, 0), Home: 0, End: last };
    if (event.key in moves) {
      event.preventDefault();
      setActive(moves[event.key]);
    } else if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      if (choices[active]) pick(choices[active]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      close(true);
    } else if (event.key === "Tab") {
      close(false);
    }
  }

  return (
    <span className="pos-pick" ref={wrap} data-open={open || undefined} data-moving={moving || undefined}>
      <button
        type="button"
        ref={button}
        className="pos-word"
        data-word={id}
        data-pick=""
        data-focus={focusKey}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={shown ? menuId : undefined}
        onKeyDown={wordKey}
      >
        {text}
      </button>
      {shown && (
        <span className="pos-menu" inert={!open}>
          <span
            id={menuId}
            ref={menu}
            role="menu"
            aria-label={`Sort ${text}`}
            tabIndex={-1}
            aria-activedescendant={`${menuId}-${active}`}
            onKeyDown={menuKey}
          >
            {choices.map((choice, index) => (
              <span
                key={choice.key ?? ""}
                id={`${menuId}-${index}`}
                role="menuitem"
                data-active={index === active || undefined}
                onClick={() => pick(choice)}
              >
                {choice.label}
              </span>
            ))}
          </span>
        </span>
      )}
    </span>
  );
}
