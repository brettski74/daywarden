import { directoryQuery } from "./directories";
import { NEW_TASK, taskPath, type TaskRef } from "./taskRef";

/** How a setup of a spelling task's words applies them. */
export type WordsMode = "add-current" | "add-revision" | "replace-current";

/** The Words menu's entries, in order. */
export const WORDS_MODES: { mode: WordsMode; label: string }[] = [
  { mode: "add-current", label: "Add to Current" },
  { mode: "add-revision", label: "Add to Revision" },
  { mode: "replace-current", label: "Replace Current" },
];

export function modeLabel(mode: string): string {
  return WORDS_MODES.find((each) => each.mode === mode)?.label ?? mode;
}

export function isWordsMode(mode: string | undefined): mode is WordsMode {
  return WORDS_MODES.some((each) => each.mode === mode);
}

/** The setup page's address for one mode. */
export function wordsPath(task: TaskRef, mode: WordsMode): string {
  return `${taskPath(task)}/words/${mode}`;
}

/**
 * The New task page for a spelling task not written yet, with its name and type locked in again and
 * ``directories``, the ones that differ from the defaults, chosen again. A setup goes back to it.
 */
export function newTaskAddress(task: TaskRef, directories: Record<string, string>): string {
  const query = new URLSearchParams({ name: task.name, type: task.type });
  const chosen = directoryQuery(directories).slice(1);
  return `${NEW_TASK}?${query}${chosen ? `&${chosen}` : ""}`;
}

/** The setup in progress, as the spelling page and the setup page are told it. */
export type SetupInProgress = { mode: WordsMode; count: number };

/** What is asked before a setup in progress in another mode is thrown away. */
export function throwAwayQuestion(setup: SetupInProgress, mode: WordsMode): string {
  const words = `${setup.count} word${setup.count === 1 ? "" : "s"}`;
  return `Throw away the ${modeLabel(setup.mode)} setup in progress, with ${words}, and start ${modeLabel(mode)}?`;
}

export const THROW_AWAY_TITLE = "Throw away the setup in progress?";
