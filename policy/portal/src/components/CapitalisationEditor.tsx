import { CircleX, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ClipboardEvent } from "react";
import { label } from "../labels";
import { NO_SENTENCES, blockChanged, newBlock, pasteInto, problems, type CapBlock, type CapPoolData } from "../capitalisation";
import { levelProblem } from "../sentences";

export const ADD_TITLE = "Add sentence (Alt+N)";

type Props = {
  /** The pool as saved: each block's ``origin`` names one of its sentences. */
  data: Pick<CapPoolData, "sentences" | "problems">;
  blocks: CapBlock[];
  /** The pool's level of difficulty as the page shows it, the placeholder of each sentence's own. */
  poolLevel: string;
  onBlocks: (change: (blocks: CapBlock[]) => CapBlock[]) => void;
};

/** A capitalisation pool's sentences: a row each with its text, its own level of difficulty, and a delete button. */
export function CapitalisationEditor({ data, blocks, poolLevel, onBlocks }: Props) {
  const root = useRef<HTMLElement>(null);
  const [wanted, setWanted] = useState<{ key: string; end?: boolean } | null>(null);

  useLayoutEffect(() => {
    if (!wanted) return;
    const element = root.current?.querySelector<HTMLElement>(`[data-focus="${wanted.key}"]`);
    if (!element) return;
    setWanted(null);
    element.focus();
    if (element instanceof HTMLInputElement) element.setSelectionRange(element.value.length, element.value.length);
    element.scrollIntoView?.({ block: "nearest" });
  }, [wanted, blocks]);

  const add = useCallback(() => {
    const block = newBlock();
    onBlocks((current) => [...current, block]);
    setWanted({ key: `text:${block.id}` });
  }, [onBlocks]);

  const latestAdd = useRef(add);
  latestAdd.current = add;
  useEffect(() => {
    function key(event: KeyboardEvent) {
      if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
      if (event.code !== "KeyN" && event.key.toLowerCase() !== "n") return;
      if (root.current?.closest("[inert]")) return;
      event.preventDefault();
      latestAdd.current();
    }
    window.addEventListener("keydown", key, true);
    return () => window.removeEventListener("keydown", key, true);
  }, []);

  function paste(block: CapBlock, event: ClipboardEvent<HTMLInputElement>) {
    const box = event.currentTarget;
    const found = pasteInto(block, box.selectionStart ?? box.value.length, box.selectionEnd ?? box.value.length, event.clipboardData.getData("text"));
    if (found === null) return;
    event.preventDefault();
    const added = found.more.map((text) => newBlock(text));
    onBlocks((current) => {
      const at = current.findIndex((each) => each.id === block.id);
      const next = current.map((each) => (each.id === block.id ? { ...each, text: found.first } : each));
      next.splice(at + 1, 0, ...added);
      return next;
    });
    setWanted({ key: `text:${(added[added.length - 1] ?? block).id}` });
  }

  return (
    <section className="parts-of-speech" aria-label="Sentences" ref={root}>
      {data.problems.map((problem) => (
        <p key={problem} className="problem">
          {problem}
        </p>
      ))}

      {blocks.map((block, index) => {
        const original = block.origin === null ? undefined : data.sentences[block.origin];
        const found = problems(blocks, index);
        const levelChanged = original !== undefined && block.level.trim() !== original.level_of_difficulty.trim();
        return (
          <section key={block.id} className="pos-block cap-row" aria-label={`Sentence ${index + 1}`} data-changed={blockChanged(original, block) || undefined}>
            <div className="cap-line">
              <input
                type="text"
                className="cap-text"
                aria-label="Sentence"
                data-focus={`text:${block.id}`}
                value={block.text}
                aria-invalid={found.length > 0 || undefined}
                onPaste={(event) => paste(block, event)}
                onChange={(event) => {
                  const text = event.target.value;
                  onBlocks((current) => current.map((each) => (each.id === block.id ? { ...each, text } : each)));
                }}
              />
              <label className="pos-level">
                <span title="level_of_difficulty">{label("level_of_difficulty")}</span>
                <input
                  type="number"
                  min="0.5"
                  max="10"
                  step="any"
                  value={block.level}
                  placeholder={poolLevel}
                  data-changed={levelChanged || undefined}
                  aria-invalid={levelProblem(block.level) !== null || undefined}
                  onChange={(event) => {
                    const level = event.target.value;
                    onBlocks((current) => current.map((each) => (each.id === block.id ? { ...each, level } : each)));
                  }}
                />
              </label>
              <button
                type="button"
                className="icon-button icon-button-quiet"
                aria-label="Delete sentence"
                title="Delete sentence"
                onClick={() => {
                  onBlocks((current) => current.filter((each) => each.id !== block.id));
                  setWanted({ key: "add-sentence" });
                }}
              >
                <Trash2 aria-hidden="true" />
              </button>
            </div>
            {found.length > 0 && (
              <ul className="pos-notes">
                {found.map((problem) => (
                  <li key={problem} className="pos-note pos-problem">
                    <CircleX aria-hidden="true" />
                    {problem}
                  </li>
                ))}
              </ul>
            )}
          </section>
        );
      })}

      <div className="pos-add">
        <button type="button" className="button" data-focus="add-sentence" title={ADD_TITLE} onClick={add}>
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
    </section>
  );
}
