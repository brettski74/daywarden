import { Archive, Folder, FolderPlus, MessageSquareText, Mic, Volume2, WholeWord } from "lucide-react";
import { createRef, useEffect, useMemo, useState, type RefObject } from "react";
import { ApiError, BASE, api } from "../api";
import { Dialog } from "../components/Dialog";
import { NameDialog } from "../components/NameDialog";
import { RecordDialog, sessionEnded, type Kept } from "../components/RecordDialog";
import { SelectOne } from "../components/SelectOne";
import { DIRECTORY_FIELDS, SPELLING_DIR, directoryChoices, directoryQuery } from "../directories";
import { label } from "../labels";
import type { Item, Kind } from "../review";
import { NEW_TASK, taskPath, type TaskRef } from "../taskRef";
import type { SetupInProgress } from "../words";

export type Pool = "current" | "revision" | "attic";
export type SpellingWord = { key: string; word: string; pool: Pool; clip: string; sentence: string | null };
export type SpellingData = {
  settings: Record<string, string>;
  /** Each directory field's path from the data directory, as the file sets it or by default. */
  directories: Record<string, string>;
  /** Every directory under the spelling directory, relative to it, in name order. */
  folders: string[];
  words: SpellingWord[];
  problems: string[];
  /** The setup of words in progress, or null. A new task has none. */
  setup?: SetupInProgress | null;
};
/** The words the list shows, or null while a directory change is unsaved and not yet refused. */
export type Listing = { words: SpellingWord[]; problems: string[] } | null;

export const SAVE_TO_SEE = "Save to see the words in the new directories.";
export const SAVE_MOVES_FIRST = "Save the word moves first.";
export const SAVE_DIRECTORIES_FIRST = "Save the directory change first.";

/** The pool filter's values, labels, and the pools each one lists. The empty value is the default. */
export const POOL_FILTERS: [string, string, Pool[]][] = [
  ["", "Current and revision", ["current", "revision"]],
  ["current", "Current", ["current"]],
  ["revision", "Revision", ["revision"]],
  ["attic", "Attic", ["attic"]],
];
// A current or revision word goes to the attic only through Retire, which asks first.
const POOLS: [Pool, string][] = [
  ["current", "Current"],
  ["revision", "Revision"],
  ["attic", "Attic"],
];
const PLACEHOLDERS: Record<string, string> = {
  timeout: "30s",
  maximum_replays: "3",
  maximum_sentence_plays: "2",
  letter_pause: "0ms",
  word_pause: "300ms",
};

export function listedPools(filter: string): Pool[] {
  return (POOL_FILTERS.find(([option]) => option === filter) ?? POOL_FILTERS[0])[2];
}

// The recording buttons in each row: what each re-records, its label, and its icon.
export const RECORDINGS: { kinds: Kind[]; label: string; icon: typeof Mic }[] = [
  { kinds: ["word", "sentence"], label: "Re-record word and sentence", icon: Mic },
  { kinds: ["word"], label: "Re-record word", icon: WholeWord },
  { kinds: ["sentence"], label: "Re-record sentence", icon: MessageSquareText },
];

/**
 * A recording in one of a task's pools. A task not written yet plays from the default pools.
 * ``directories`` names directories in place of the task's, as a page with unsaved ones lists them.
 */
export function audioAddress(task: TaskRef | null, pool: Pool, file: string, directories: Record<string, string> = {}): string {
  return `${BASE}/api${task ? taskPath(task) : NEW_TASK}/audio/${pool}/${encodeURIComponent(file)}${directoryQuery(directories)}`;
}

const NOT_WRITTEN = "Save the new task first.";

function recordingItems(key: string, kinds: Kind[]): Item[] {
  return kinds.map((kind) => ({ key, kind, line: kind === "word" ? key : `Sentence for ${key}` }));
}

type Props = {
  /** The task, or null for a new task not written yet, which cannot retire or record. */
  task: TaskRef | null;
  data: SpellingData;
  filter: string;
  settings: Record<string, string>;
  moves: Record<string, Pool>;
  /** Each directory field's path as chosen on the page. */
  chosen: Record<string, string>;
  /** The directory fields chosen on the page that differ from the file. */
  unsaved: Record<string, string>;
  /** The problem under each directory field, such as two on one directory. */
  directoryProblems: Record<string, string>;
  listing: Listing;
  /** Why the directory pull-downs are disabled, or null. */
  directoriesLocked: string | null;
  onSetting: (key: string, text: string) => void;
  onDirectory: (field: string, path: string) => void;
  onMove: (key: string, pool: Pool) => void;
  onRetire: (key: string) => void;
  onPlayFailed: (message: string) => void;
  /** A recording was kept, or the dialog closed saying why nothing changed. */
  onRecorded: (message: string, changed: boolean) => void;
  /** A new directory was made on the server. */
  onMade: (message: string) => void;
};

/** A spelling task's own settings, its directories, and its word list. */
export function SpellingAdmin(props: Props) {
  const { task, data, filter, settings, moves, unsaved, listing, onSetting, onMove, onRetire, onPlayFailed, onRecorded } = props;
  const [retiring, setRetiring] = useState<SpellingWord | null>(null);
  const [recording, setRecording] = useState<{ key: string; kinds: Kind[] } | null>(null);
  const listed = listedPools(filter);
  const words = listing?.words.filter((word) => listed.includes(word.pool)) ?? [];
  // Retire and recording act at once on the saved directories, so they wait for a directory change to be saved.
  const actsBlocked = Object.keys(unsaved).length > 0 ? SAVE_DIRECTORIES_FIRST : null;

  function play(pool: Pool, file: string) {
    new Audio(audioAddress(task, pool, file, unsaved)).play().catch(() => onPlayFailed(`${file} could not be played.`));
  }

  async function keep(take: string, kept: Kept[]): Promise<string> {
    if (task === null) throw new Error(NOT_WRITTEN);
    const clips = Object.fromEntries(kept.map(({ item, clip }) => [item.kind, clip]));
    const done = await api<{ message: string }>(`${taskPath(task)}/recordings`, {
      page: null,
      method: "POST",
      body: { take, word: kept[0].item.key, clips },
      signedOut: "refuse",
    });
    return done.message;
  }

  return (
    <section className="spelling" aria-label="Spelling">
      <div className="task-common">
        <fieldset>
          <legend>Spelling settings</legend>
          <div className="settings">
            {Object.entries(data.settings).map(([key, written]) => {
              const shown = settings[key] ?? written;
              return (
                <label key={key} className="setting">
                  <span title={key}>{label(key)}</span>
                  <input
                    type="text"
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
        <Directories {...props} />
      </div>

      {listing?.problems.map((problem) => (
        <p key={problem} className="problem">
          {problem}
        </p>
      ))}

      {listing === null ? (
        <p>{SAVE_TO_SEE}</p>
      ) : words.length === 0 ? (
        <p>No words in this pool.</p>
      ) : (
        <table className="records words">
          <thead>
            <tr>
              <th scope="col">Word</th>
              <th scope="col">Pool</th>
              <th scope="col">Sentence</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {words.map((word) => {
              const pool = moves[word.key] ?? word.pool;
              const moved = pool !== word.pool;
              return (
                <tr key={`${word.pool}/${word.key}`} data-changed={moved || undefined}>
                  <td>
                    <button type="button" className="button button-quiet" onClick={() => play(word.pool, word.clip)} title={`Play ${word.key}`}>
                      <Volume2 aria-hidden="true" />
                      {word.key}
                    </button>
                  </td>
                  <td>
                    <select aria-label={`Pool for ${word.key}`} value={pool} onChange={(event) => onMove(word.key, event.target.value as Pool)}>
                      {POOLS.filter(([value]) => value !== "attic" || word.pool === "attic").map(([value, label]) => (
                        <option key={value} value={value}>
                          {label}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td>
                    {word.sentence === null ? (
                      "No"
                    ) : (
                      <button
                        type="button"
                        className="button button-quiet"
                        onClick={() => play(word.pool, word.sentence!)}
                        aria-label={`Play the sentence for ${word.key}`}
                        title={`Play the sentence for ${word.key}`}
                      >
                        <MessageSquareText aria-hidden="true" />
                        Play
                      </button>
                    )}
                  </td>
                  <td>
                    <div className="word-actions">
                      {RECORDINGS.map(({ kinds, label: what, icon: Icon }) => (
                        <button
                          key={what}
                          type="button"
                          className="icon-button icon-button-quiet"
                          aria-label={`${what} for ${word.key}`}
                          title={!task ? NOT_WRITTEN : (actsBlocked ?? `${what} for ${word.key}`)}
                          disabled={task === null || actsBlocked !== null}
                          onClick={() => setRecording({ key: word.key, kinds })}
                        >
                          <Icon aria-hidden="true" />
                        </button>
                      ))}
                      {word.pool !== "attic" && (
                        <button
                          type="button"
                          className="button button-quiet"
                          disabled={task === null || actsBlocked !== null}
                          title={!task ? NOT_WRITTEN : (actsBlocked ?? undefined)}
                          onClick={() => setRetiring(word)}
                        >
                          <Archive aria-hidden="true" />
                          Retire
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      {retiring !== null && (
        <Dialog
          title="Retire this word?"
          message={`Retire ${retiring.key}? Its recordings move to the attic.`}
          confirm="Retire"
          cancel="Cancel"
          onConfirm={() => {
            onRetire(retiring.key);
            setRetiring(null);
          }}
          onCancel={() => setRetiring(null)}
        />
      )}
      {recording !== null && (
        <RecordDialog
          title={`Re-record ${recording.kinds.length === 2 ? "word and sentence" : recording.kinds[0]} for ${recording.key}`}
          items={recordingItems(recording.key, recording.kinds)}
          onKeep={keep}
          onClose={(confirmed) => {
            setRecording(null);
            if (confirmed) onRecorded(confirmed.message, confirmed.changed);
          }}
        />
      )}
    </section>
  );
}

type Made = { message: string; directory: string; folders: string[] };

/** The four directory pull-downs, each ending with New directory…, which makes a directory at once. */
function Directories({ task, data, chosen, directoryProblems, directoriesLocked, onDirectory, onMade }: Props) {
  const [folders, setFolders] = useState(data.folders);
  const [naming, setNaming] = useState<string | null>(null);
  const buttons = useMemo(
    () => Object.fromEntries(DIRECTORY_FIELDS.map((field) => [field, createRef<HTMLButtonElement>()])) as Record<string, RefObject<HTMLButtonElement | null>>,
    [],
  );
  useEffect(() => setFolders(data.folders), [data.folders]);

  async function make(field: string, name: string): Promise<string | null> {
    try {
      const done = await api<Made>(`${task ? taskPath(task) : NEW_TASK}/directories`, {
        page: null,
        method: "POST",
        body: { name },
        signedOut: "refuse",
      });
      setFolders(done.folders);
      setNaming(null);
      onDirectory(field, `${SPELLING_DIR}/${done.directory}`);
      onMade(done.message);
      return null;
    } catch (error) {
      if (error instanceof ApiError) return error.status === 401 ? sessionEnded("OK") : error.message;
      return "The directory could not be made. Check the connection, then press OK.";
    }
  }

  function cancel(field: string) {
    setNaming(null);
    buttons[field].current?.focus();
  }

  return (
    <fieldset>
      <legend>Directories</legend>
      <div className="settings">
        {DIRECTORY_FIELDS.map((field) => (
          <SelectOne
            key={field}
            label={label(field)}
            title={field}
            icon={Folder}
            options={directoryChoices(folders, [data.directories[field], chosen[field]])}
            value={chosen[field]}
            onChange={(path) => onDirectory(field, path)}
            extra={{ label: "New directory…", icon: FolderPlus, onChoose: () => setNaming(field) }}
            changed={chosen[field] !== data.directories[field]}
            disabled={directoriesLocked !== null}
            disabledTitle={directoriesLocked ?? undefined}
            problem={directoryProblems[field]}
            buttonRef={buttons[field]}
          />
        ))}
      </div>
      {naming !== null && (
        <NameDialog title="New directory" label={`Name, under ${SPELLING_DIR}/`} onSubmit={(name) => make(naming, name)} onCancel={() => cancel(naming)} />
      )}
    </fieldset>
  );
}
