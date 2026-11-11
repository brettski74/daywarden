import { CalendarCheck, ListChecks, MessageSquareText, Mic, MicVocal, Pencil, PencilLine, Save, Volume2, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type KeyboardEvent as KeyEvent } from "react";
import {
  Link,
  redirect,
  useBlocker,
  useFetcher,
  useLoaderData,
  useNavigate,
  useRevalidator,
  type ActionFunctionArgs,
  type LoaderFunctionArgs,
} from "react-router";
import { ApiError, BASE, api, pageOf } from "../api";
import { Dialog } from "../components/Dialog";
import { RecordDialog, type Kept } from "../components/RecordDialog";
import { DIRECTORY_FIELDS, changedDirectories, shownDirectory } from "../directories";
import { label } from "../labels";
import type { Item, Kind } from "../review";
import { ContextBar, StatusBar, useTitle } from "../slots";
import { RECORDINGS, audioAddress, type Pool } from "./Spelling";
import { Outcome, type Reported } from "./Task";
import { routeTask, taskPath, type TaskRef } from "../taskRef";
import { THROW_AWAY_TITLE, modeLabel, newTaskAddress, throwAwayQuestion, wordsPath, type SetupInProgress, type WordsMode } from "../words";

export type WeekWord = {
  key: string;
  word: string;
  /** The pool the word is in now, or null for a new word. */
  pool: Pool | null;
  /** The number an existing plain word takes on Apply, beside a new numbered meaning of it. */
  becomes: string | null;
  /** The existing plain word this new numbered word gives a number on Apply, such as read becoming read.2. */
  renames: { from: string; to: string } | null;
  clip: string | null;
  sentence_clip: string | null;
  /** The clips kept for this word in the setup, written into the pools on Apply. */
  kept: Record<Kind, string | null>;
  sentence: string;
  /** For a new plain word whose numbered meanings are already in the pools, those meanings. */
  choices: { key: string; pool: Pool }[];
  new_key: string | null;
};

export type WeekData = {
  name: string;
  type: string;
  version: string;
  file: string;
  /** The mode this address sets up. */
  mode: WordsMode;
  /** The setup in progress, which may be in another mode, or null. */
  setup: SetupInProgress | null;
  /** The four directories the setup applies into, as paths from the data directory. */
  directories: Record<string, string>;
  /** The task's directories as the policy file has them. */
  saved_directories: Record<string, string>;
  /** False for a spelling task not written yet, set up from the New task page. Its Apply writes no policy file. */
  written: boolean;
  targets: Record<string, string>;
  words: WeekWord[];
  needs: string[];
  ambiguous: string[];
  current: number;
  problems: string[];
};

/** Cancel throws the setup away and opens the spelling page. Discard throws away a setup in another mode and stays. */
type Intent = "save" | "apply" | "cancel" | "discard";
type WeekResult = {
  intent: Intent | "record";
  ok: boolean;
  message?: string;
  warnings?: string[];
  error?: string;
  errors?: string[];
};

/** A word as it is on screen, with the key it was saved as, so its sentence and clips follow an edit. */
type Row = { from: string; key: string; sentence: string };

const TARGETS = ["current_required", "revision_required"];
const POOL_NAMES: Record<Pool, string> = { current: "Current", revision: "Revision", attic: "Attic" };

/** The setup's data address. Its page is at ``wordsPath``, one address for each mode. */
function weekPath(task: TaskRef): string {
  return `${taskPath(task)}/week`;
}

/** The page asks for its mode, with any unsaved directories the spelling page sent in its query string. */
export async function weekLoader({ request, params }: LoaderFunctionArgs): Promise<WeekData> {
  const asked = new URL(request.url).searchParams;
  const query = new URLSearchParams(DIRECTORY_FIELDS.flatMap((field) => (asked.has(field) ? [[field, asked.get(field) ?? ""]] : [])));
  query.set("mode", params.mode ?? "");
  return api<WeekData>(`${weekPath(routeTask(params))}?${query}`, { page: pageOf(request), signal: request.signal });
}

/** The S023.4 address of the new week's words, which is Replace Current. */
export function oldWeekLoader({ request, params }: LoaderFunctionArgs) {
  return redirect(wordsPath(routeTask(params), "replace-current") + new URL(request.url).search);
}

/** Save the list, apply it, or throw the setup away. Sent from the page on show, so a refusal returns to it. */
export async function weekAction({ request, params }: ActionFunctionArgs): Promise<WeekResult> {
  const { intent, ...body } = (await request.json()) as { intent: Intent } & Record<string, unknown>;
  const suffixes: Record<Intent, string> = { save: "", apply: "/apply", cancel: "/cancel", discard: "/cancel" };
  const path = weekPath(routeTask(params)) + suffixes[intent];
  try {
    const done = await api<{ message: string; warnings: string[] }>(path, { page: pageOf(request), method: "POST", body });
    return { intent, ok: true, ...done };
  } catch (error) {
    if (error instanceof ApiError) return { intent, ok: false, ...(error.data as Partial<WeekResult>), error: error.message };
    throw error;
  }
}

function savedRows(data: WeekData): Row[] {
  return data.words.map((word) => ({ from: word.key, key: word.key, sentence: word.sentence }));
}

/** A sentence as the service keeps it, with its spaces tidied. */
function tidy(text: string): string {
  return text.split(/\s+/).filter(Boolean).join(" ");
}

/** Enter in a sentence box moves to the next row's sentence box, with its text selected. */
function nextSentence(event: KeyEvent<HTMLInputElement>) {
  if (event.key !== "Enter" || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey || event.nativeEvent.isComposing) return;
  event.preventDefault();
  const boxes = [...(event.currentTarget.closest("tbody")?.querySelectorAll<HTMLInputElement>("input.week-sentence") ?? [])];
  const next = boxes[boxes.indexOf(event.currentTarget) + 1];
  next?.focus();
  next?.select();
}

function unsaved(data: WeekData, rows: Row[], add: string): boolean {
  if (add.trim() !== "" || rows.length !== data.words.length) return true;
  return rows.some((row, index) => {
    const word = data.words[index];
    return row.from !== word.key || row.key.trim() !== word.key || tidy(row.sentence) !== word.sentence;
  });
}

function wordItem(word: WeekWord): Item {
  return { key: word.key, kind: "word", line: word.key };
}

function sentenceItem(word: WeekWord): Item {
  return { key: word.key, kind: "sentence", line: word.sentence || `Sentence for ${word.key}` };
}

/** Every word, each followed by its sentence when one is typed. */
export function recordAllItems(words: WeekWord[]): Item[] {
  return words.flatMap((word) => [wordItem(word), ...(word.sentence ? [sentenceItem(word)] : [])]);
}

/** Only the pieces with no clip yet: a word with no word clip, and a typed sentence with no sentence clip. */
export function recordMissingItems(words: WeekWord[]): Item[] {
  return words.flatMap((word) => [
    ...(word.kept.word || word.clip ? [] : [wordItem(word)]),
    ...(word.sentence && !(word.kept.sentence || word.sentence_clip) ? [sentenceItem(word)] : []),
  ]);
}

function named(keys: string[]): string {
  return keys.length === 1 ? keys[0] : `${keys.slice(0, -1).join(", ")} and ${keys[keys.length - 1]}`;
}

export function Week() {
  const data = useLoaderData() as WeekData;
  return <WeekEditor key={`${data.type}/${data.name}/${data.mode}`} data={data} />;
}

function WeekEditor({ data }: { data: WeekData }) {
  const title = modeLabel(data.mode);
  useTitle(`${data.name}: ${title}`);
  const other = data.setup !== null && data.setup.mode !== data.mode ? data.setup : null;
  const moved = changedDirectories(data.saved_directories, data.directories);
  // The page the setup belongs to: the task's page, or the New task page with the name, type, and directories again.
  const home = data.written ? taskPath(data) : newTaskAddress(data, moved);
  const navigate = useNavigate();
  const fetcher = useFetcher<WeekResult>();
  const revalidator = useRevalidator();
  const [rows, setRows] = useState<Row[]>(() => savedRows(data));
  const [add, setAdd] = useState("");
  const [editing, setEditing] = useState<Set<string>>(() => new Set());
  const [targets, setTargets] = useState<Record<string, string>>({});
  const [result, setResult] = useState<WeekResult | null>(null);
  const [offerTargets, setOfferTargets] = useState(false);
  const [cancelling, setCancelling] = useState(false);
  const [recording, setRecording] = useState<{ title: string; items: Item[] } | null>(null);
  const handled = useRef<WeekResult | undefined>(undefined);
  const leaving = useRef(false);
  const latestData = useRef(data);
  latestData.current = data;
  const latestHome = useRef(home);
  latestHome.current = home;
  const dirty = unsaved(data, rows, add);
  const busy = fetcher.state !== "idle";
  const blocker = useBlocker(
    ({ currentLocation, nextLocation }) => dirty && !leaving.current && currentLocation.pathname !== nextLocation.pathname,
  );

  const save = useCallback(() => {
    if (fetcher.state !== "idle" || !dirty) return;
    fetcher.submit({ intent: "save", mode: data.mode, directories: moved, rows, add }, { method: "post", encType: "application/json" });
  }, [fetcher, rows, add, dirty, data.mode, moved]);

  const targetsChanged = TARGETS.some((key) => key in targets && targets[key].trim() !== (data.targets[key] ?? "").trim());
  const apply = () => {
    const settings = Object.fromEntries(TARGETS.map((key) => [key, targets[key] ?? data.targets[key] ?? ""]));
    fetcher.submit(
      { intent: "apply", mode: data.mode, version: data.version, ...(targetsChanged ? { settings } : {}) },
      { method: "post", encType: "application/json" },
    );
  };

  useEffect(() => {
    const done = fetcher.data;
    if (fetcher.state !== "idle" || done === undefined || handled.current === done) return;
    handled.current = done;
    if (done.ok && done.intent === "discard") {
      void revalidator.revalidate();
      return;
    }
    if (done.ok && (done.intent === "apply" || done.intent === "cancel")) {
      leaving.current = true;
      const reported: Reported = { message: done.message ?? "", warnings: done.warnings ?? [] };
      navigate(latestHome.current, { state: reported });
      return;
    }
    setResult(done);
    if (done.intent === "save" && done.ok) {
      setRows(savedRows(latestData.current));
      setAdd("");
      setEditing(new Set());
    }
    if (done.intent === "apply") setOfferTargets(TARGETS.some((key) => done.errors?.some((problem) => problem.includes(key))));
  }, [fetcher.state, fetcher.data, navigate, revalidator]);

  const latestSave = useRef(save);
  latestSave.current = save;
  useEffect(() => {
    function key(event: KeyboardEvent) {
      if ((event.ctrlKey || event.metaKey) && !event.altKey && event.key.toLowerCase() === "s") {
        event.preventDefault();
        latestSave.current();
      }
    }
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, []);

  useEffect(() => {
    if (!dirty) return;
    function leavingPage(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", leavingPage);
    return () => window.removeEventListener("beforeunload", leavingPage);
  }, [dirty]);

  function play(address: string, what: string) {
    new Audio(address).play().catch(() => setResult({ intent: "record", ok: false, error: `${what} could not be played.` }));
  }

  function pending(file: string): string {
    return `${BASE}/api${weekPath(data)}/clips/${encodeURIComponent(file)}`;
  }

  function wordAddress(word: WeekWord): string | null {
    if (word.kept.word) return pending(word.kept.word);
    return word.clip && word.pool ? audioAddress(data, word.pool, word.clip, moved) : null;
  }

  function sentenceAddress(word: WeekWord): string | null {
    if (word.kept.sentence) return pending(word.kept.sentence);
    return word.sentence_clip && word.pool ? audioAddress(data, word.pool, word.sentence_clip, moved) : null;
  }

  async function keep(take: string, kept: Kept[]): Promise<string> {
    const done = await api<{ message: string }>(`${weekPath(data)}/recordings`, {
      page: null,
      method: "POST",
      body: { mode: data.mode, take, clips: kept.map(({ item, clip }) => ({ word: item.key, kind: item.kind, clip })) },
      signedOut: "refuse",
    });
    return done.message;
  }

  const setRow = (index: number, change: Partial<Row>) =>
    setRows((current) => current.map((row, at) => (at === index ? { ...row, ...change } : row)));

  function choose(index: number, keys: string[]) {
    setRow(index, { key: keys[0] });
    if (keys.length > 1) setAdd((current) => [current.trimEnd(), ...keys.slice(1)].filter(Boolean).join("\n"));
  }

  let blocked: string | null = null;
  if (data.words.length === 0) blocked = "Add the week's words and press Check first.";
  else if (dirty) blocked = "Save the list before applying it.";
  else if (data.ambiguous.length > 0) blocked = `Choose which meaning of ${named(data.ambiguous)} belongs to the week.`;
  else if (data.needs.length > 0) blocked = `These words still need a word clip: ${data.needs.join(", ")}.`;
  const recordBlocked = data.words.length === 0 ? "Add the week's words and press Check first." : dirty ? "Save the list before recording." : null;
  const missing = recordMissingItems(data.words);
  const crumbs = (
    <nav className="crumbs" aria-label="Where you are">
      <ol>
        <li>Tasks</li>
        <li>
          <Link to={home}>{data.name}</Link>
        </li>
        <li>
          <h1 className="bar-title">{title}</h1>
        </li>
      </ol>
    </nav>
  );

  if (other !== null) {
    return (
      <>
        <ContextBar>{crumbs}</ContextBar>
        <StatusBar>{result && <Outcome result={result} />}</StatusBar>
        <Dialog
          title={THROW_AWAY_TITLE}
          message={throwAwayQuestion(other, data.mode)}
          confirm="Throw away"
          cancel="Keep it"
          onConfirm={() => fetcher.submit({ intent: "discard" }, { method: "post", encType: "application/json" })}
          onCancel={() => {
            leaving.current = true;
            navigate(home);
          }}
        />
      </>
    );
  }

  return (
    <>
      <ContextBar>
        {crumbs}
        <div className="bar-end bar-actions">
          {dirty && (
            <span className="unsaved">
              <PencilLine aria-hidden="true" />
              Unsaved changes
            </span>
          )}
          <button type="button" className="button button-quiet" onClick={() => setCancelling(true)} disabled={busy}>
            <X aria-hidden="true" />
            Cancel
          </button>
          <button type="button" className="button" onClick={save} disabled={busy || !dirty} title={dirty ? "Save (Ctrl+S)" : "Nothing to save"}>
            <Save aria-hidden="true" />
            Save
          </button>
          <button type="button" className="button" onClick={apply} disabled={busy || blocked !== null} title={blocked ?? "Make this list the current pool"}>
            <CalendarCheck aria-hidden="true" />
            Apply
          </button>
        </div>
      </ContextBar>

      <div className="task-common week-entry">
        <fieldset>
          <legend>Add words</legend>
          <label className="week-add">
            <span>Words, separated by commas, spaces, or new lines, such as rope, read.1, or don't. Paste a list as it is.</span>
            <textarea rows={6} value={add} spellCheck={false} onChange={(event) => setAdd(event.target.value)} />
          </label>
          <button type="button" className="button" onClick={save} disabled={busy || !dirty}>
            <ListChecks aria-hidden="true" />
            Check
          </button>
        </fieldset>
        {data.written && (
          <fieldset>
            <legend>Targets</legend>
            <p className="week-hint">
              The current pool has {data.current} word{data.current === 1 ? "" : "s"} now. A changed target is written to the policy file with Apply.
            </p>
            <div className="settings">
              {TARGETS.map((key) => {
                const shown = targets[key] ?? data.targets[key] ?? "";
                return (
                  <label key={key} className="setting">
                    <span title={key}>{label(key)}</span>
                    <input
                      type="text"
                      inputMode="numeric"
                      value={shown}
                      data-changed={shown.trim() !== (data.targets[key] ?? "").trim() || undefined}
                      onChange={(event) => setTargets((current) => ({ ...current, [key]: event.target.value }))}
                    />
                  </label>
                );
              })}
            </div>
            {offerTargets && <p className="problem">Change a target here, then press Apply again. The new target is saved in the same step.</p>}
          </fieldset>
        )}
        <fieldset>
          <legend>Directories</legend>
          <dl className="fields week-directories">
            {DIRECTORY_FIELDS.map((field) => (
              <div key={field}>
                <dt title={field}>{label(field)}</dt>
                <dd data-changed={field in moved || undefined}>{shownDirectory(data.directories[field])}</dd>
              </div>
            ))}
          </dl>
          {!data.written ? (
            <p className="week-hint">The task is not written yet. Apply puts the words in these directories, then the New task page saves the task.</p>
          ) : (
            Object.keys(moved).length > 0 && <p className="week-hint">Apply also makes the task use these directories.</p>
          )}
        </fieldset>
      </div>

      {data.problems.map((problem) => (
        <p key={problem} className="problem">
          {problem}
        </p>
      ))}

      <div className="week-toolbar">
        <button
          type="button"
          className="button"
          disabled={recordBlocked !== null}
          title={recordBlocked ?? "Record every word, each followed by its sentence"}
          onClick={() => setRecording({ title: "Record the week's words", items: recordAllItems(data.words) })}
        >
          <Mic aria-hidden="true" />
          Record all
        </button>
        <button
          type="button"
          className="button button-quiet"
          disabled={recordBlocked !== null || missing.length === 0}
          title={recordBlocked ?? (missing.length === 0 ? "Every word and typed sentence has a clip" : "Record only the pieces with no clip yet")}
          onClick={() => setRecording({ title: "Record the missing pieces", items: missing })}
        >
          <MicVocal aria-hidden="true" />
          Record missing
        </button>
        {blocked !== null && data.words.length > 0 && <p className="week-blocked">Apply is not ready. {blocked}</p>}
      </div>

      {rows.length === 0 ? (
        <p>No words on the week's list yet. Type them under Add words and press Check.</p>
      ) : (
        <table className="records words week-words">
          <thead>
            <tr>
              <th scope="col">Word</th>
              <th scope="col">Now</th>
              <th scope="col">Word clip</th>
              <th scope="col">Sentence clip</th>
              <th scope="col">Sentence</th>
              <th scope="col">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => {
              const word = data.words.find((each) => each.key === row.from);
              if (word === undefined) return null;
              const edited = row.key.trim() !== word.key;
              const changed = edited || tidy(row.sentence) !== word.sentence;
              const playWord = wordAddress(word);
              const playSentence = sentenceAddress(word);
              return (
                <tr key={row.from} data-changed={changed || undefined}>
                  <td>
                    {edited || editing.has(row.from) ? (
                      <input
                        type="text"
                        className="week-key"
                        aria-label={`Word in place of ${word.key}`}
                        value={row.key}
                        spellCheck={false}
                        data-changed={edited || undefined}
                        autoFocus
                        onChange={(event) => setRow(index, { key: event.target.value })}
                      />
                    ) : (
                      <span className="week-word">
                        {playWord ? (
                          <button type="button" className="button button-quiet" onClick={() => play(playWord, word.key)} title={`Play ${word.key}`}>
                            <Volume2 aria-hidden="true" />
                            {word.key}
                          </button>
                        ) : (
                          <span>{word.key}</span>
                        )}
                        <button
                          type="button"
                          className="icon-button icon-button-quiet"
                          aria-label={`Change ${word.key}`}
                          title={`Change ${word.key}`}
                          onClick={() => setEditing((current) => new Set(current).add(row.from))}
                        >
                          <Pencil aria-hidden="true" />
                        </button>
                      </span>
                    )}
                    {word.becomes && <p className="week-note">Becomes {word.becomes} on Apply.</p>}
                    {word.renames && !edited && (
                      <p className="week-note">
                        The existing {word.renames.from} becomes {word.renames.to} on Apply.
                      </p>
                    )}
                    {word.choices.length > 0 && !edited && <Choices word={word} onUse={(keys) => choose(index, keys)} />}
                  </td>
                  <td>{edited ? "Save to check" : word.pool ? POOL_NAMES[word.pool] : "New"}</td>
                  <td>{word.kept.word ? "New recording" : word.clip ? "Yes" : "No"}</td>
                  <td>
                    {playSentence ? (
                      <button
                        type="button"
                        className="button button-quiet"
                        onClick={() => play(playSentence, `The sentence for ${word.key}`)}
                        aria-label={`Play the sentence for ${word.key}`}
                        title={`Play the sentence for ${word.key}`}
                      >
                        <MessageSquareText aria-hidden="true" />
                        {word.kept.sentence ? "Play new" : "Play"}
                      </button>
                    ) : (
                      "No"
                    )}
                  </td>
                  <td>
                    <input
                      type="text"
                      className="week-sentence"
                      aria-label={`Sentence for ${word.key}`}
                      value={row.sentence}
                      maxLength={300}
                      placeholder="A sentence using the word"
                      data-changed={tidy(row.sentence) !== word.sentence || undefined}
                      onChange={(event) => setRow(index, { sentence: event.target.value })}
                      onKeyDown={nextSentence}
                    />
                  </td>
                  <td>
                    <div className="word-actions">
                      {RECORDINGS.map(({ kinds, label: what, icon: Icon }) => (
                        <button
                          key={what}
                          type="button"
                          className="icon-button icon-button-quiet"
                          aria-label={`${what} for ${word.key}`}
                          title={recordBlocked ?? `${what} for ${word.key}`}
                          disabled={recordBlocked !== null}
                          onClick={() =>
                            setRecording({
                              title: `${what} for ${word.key}`,
                              items: kinds.map((kind) => (kind === "word" ? wordItem(word) : sentenceItem(word))),
                            })
                          }
                        >
                          <Icon aria-hidden="true" />
                        </button>
                      ))}
                      <button
                        type="button"
                        className="icon-button icon-button-quiet"
                        aria-label={`Remove ${word.key} from the week`}
                        title={`Remove ${word.key} from the week`}
                        onClick={() => setRows((current) => current.filter((_row, at) => at !== index))}
                      >
                        <X aria-hidden="true" />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}

      <StatusBar>
        {result && <Outcome result={result} />}
        <span>{counts(data.words)}</span>
      </StatusBar>

      {recording !== null && (
        <RecordDialog
          title={recording.title}
          items={recording.items}
          onKeep={keep}
          onClose={(confirmed) => {
            setRecording(null);
            if (!confirmed) return;
            setResult({ intent: "record", ok: true, message: confirmed.message, warnings: [] });
            if (confirmed.changed) void revalidator.revalidate();
          }}
        />
      )}
      {cancelling && (
        <Dialog
          title="Throw away the new week?"
          message="This throws away the week's list, its sentences, and the clips kept for it. The pools do not change."
          confirm="Throw away"
          cancel="Keep it"
          onConfirm={() => {
            setCancelling(false);
            fetcher.submit({ intent: "cancel" }, { method: "post", encType: "application/json" });
          }}
          onCancel={() => setCancelling(false)}
        />
      )}
      {blocker.state === "blocked" && (
        <Dialog
          title="Leave this page?"
          message="The changes on this page have not been saved. Leaving loses them."
          confirm="Leave"
          cancel="Stay"
          onConfirm={() => blocker.proceed()}
          onCancel={() => blocker.reset()}
        />
      )}
    </>
  );
}

/** For a new plain word whose numbered meanings are in the pools: pick which belong to the week, or a new number. */
function Choices({ word, onUse }: { word: WeekWord; onUse: (keys: string[]) => void }) {
  const [picked, setPicked] = useState<string[]>([]);
  const options = [
    ...word.choices.map((choice) => ({ key: choice.key, text: `${choice.key} (${POOL_NAMES[choice.pool]})` })),
    ...(word.new_key ? [{ key: word.new_key, text: `${word.new_key} (a new meaning)` }] : []),
  ];
  return (
    <fieldset className="week-choices">
      <legend>The pools have more than one {word.key}. Which belong to this week?</legend>
      {options.map((option) => (
        <label key={option.key}>
          <input
            type="checkbox"
            checked={picked.includes(option.key)}
            onChange={() => setPicked((current) => (current.includes(option.key) ? current.filter((key) => key !== option.key) : [...current, option.key]))}
          />
          {option.text}
        </label>
      ))}
      <button
        type="button"
        className="button button-quiet"
        disabled={picked.length === 0}
        onClick={() => onUse(options.map((option) => option.key).filter((key) => picked.includes(key)))}
      >
        Use these
      </button>
    </fieldset>
  );
}

function counts(words: WeekWord[]): string {
  if (words.length === 0) return "The week's list is empty.";
  const found = (pool: Pool | null) => words.filter((word) => word.pool === pool).length;
  return `Week's list: ${words.length} word${words.length === 1 ? "" : "s"}, ${found(null)} new, ${found("current")} current, ${found("revision")} revision, ${found("attic")} attic.`;
}
