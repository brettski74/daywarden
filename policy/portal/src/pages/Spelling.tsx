import { Archive, MessageSquareText, Mic, Volume2, WholeWord } from "lucide-react";
import { useState } from "react";
import { BASE, api } from "../api";
import { Dialog } from "../components/Dialog";
import { RecordDialog, type Kept } from "../components/RecordDialog";
import { label } from "../labels";
import type { Item, Kind } from "../review";
import { taskPath, type TaskRef } from "../taskRef";

export type Pool = "current" | "revision" | "attic";
export type SpellingWord = { key: string; word: string; pool: Pool; clip: string; sentence: string | null };
export type SpellingData = {
  settings: Record<string, string>;
  directories: Record<string, string>;
  words: SpellingWord[];
  problems: string[];
};

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

export function audioAddress(task: TaskRef, pool: Pool, file: string): string {
  return `${BASE}/api${taskPath(task)}/audio/${pool}/${encodeURIComponent(file)}`;
}

function recordingItems(key: string, kinds: Kind[]): Item[] {
  return kinds.map((kind) => ({ key, kind, line: kind === "word" ? key : `Sentence for ${key}` }));
}

type Props = {
  task: TaskRef;
  data: SpellingData;
  filter: string;
  settings: Record<string, string>;
  moves: Record<string, Pool>;
  onSetting: (key: string, text: string) => void;
  onMove: (key: string, pool: Pool) => void;
  onRetire: (key: string) => void;
  onPlayFailed: (message: string) => void;
  /** A recording was kept, or the dialog closed saying why nothing changed. */
  onRecorded: (message: string, changed: boolean) => void;
};

/** A spelling task's own settings and its word list. */
export function SpellingAdmin({ task, data, filter, settings, moves, onSetting, onMove, onRetire, onPlayFailed, onRecorded }: Props) {
  const [retiring, setRetiring] = useState<SpellingWord | null>(null);
  const [recording, setRecording] = useState<{ key: string; kinds: Kind[] } | null>(null);
  const listed = listedPools(filter);
  const words = data.words.filter((word) => listed.includes(word.pool));

  function play(pool: Pool, file: string) {
    new Audio(audioAddress(task, pool, file)).play().catch(() => onPlayFailed(`${file} could not be played.`));
  }

  async function keep(take: string, kept: Kept[]): Promise<string> {
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
        <fieldset>
          <legend>Directories</legend>
          <dl className="fields">
            {Object.entries(data.directories).map(([key, directory]) => (
              <div key={key}>
                <dt title={key}>{label(key)}</dt>
                <dd>{directory}</dd>
              </div>
            ))}
          </dl>
        </fieldset>
      </div>

      {data.problems.map((problem) => (
        <p key={problem} className="problem">
          {problem}
        </p>
      ))}

      {words.length === 0 ? (
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
                          title={`${what} for ${word.key}`}
                          onClick={() => setRecording({ key: word.key, kinds })}
                        >
                          <Icon aria-hidden="true" />
                        </button>
                      ))}
                      {word.pool !== "attic" && (
                        <button type="button" className="button button-quiet" onClick={() => setRetiring(word)}>
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
