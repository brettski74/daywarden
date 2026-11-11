import { ListPlus, PencilLine, Save, TextCursorInput, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import {
  useBlocker,
  useFetcher,
  useLoaderData,
  useLocation,
  useNavigate,
  useRevalidator,
  useSearchParams,
  type ActionFunctionArgs,
  type LoaderFunctionArgs,
  type ShouldRevalidateFunctionArgs,
} from "react-router";
import { ApiError, api, pageOf } from "../api";
import { DateField } from "../components/DateField";
import { Dialog } from "../components/Dialog";
import { MenuLinks, type MenuLink } from "../components/MenuLinks";
import { MultiSelect } from "../components/MultiSelect";
import { dateProblem } from "../dates";
import { DIRECTORY_FIELDS, changedDirectories, directoryQuery, sameDirectoryProblems } from "../directories";
import { THROW_AWAY_TITLE, WORDS_MODES, throwAwayQuestion, wordsPath, type WordsMode } from "../words";
import { label } from "../labels";
import { arithmeticLists, problemsText, shownArithmetic, type ArithmeticData } from "../arithmetic";
import type { NumberRow, ServiceRow } from "../numberTable";
import { FIX_FIRST, blocked, blocksChanged, countsText, loaded, toRequest, type Block, type PosData } from "../sentences";
import {
  FIX_ON_PAGE,
  differenceProblems,
  differenceRequest,
  shownDifference,
  skipBlocked,
  skipCounts,
  type ListEdit,
  type ListEdits,
  type SkipData,
} from "../skipCounting";
import { ContextBar, StatusBar, useTitle } from "../slots";
import { PartsOfSpeechAdmin } from "./PartsOfSpeech";
import { ArithmeticAdmin } from "./Arithmetic";
import { SkipCountingAdmin } from "./SkipCounting";
import { POOL_FILTERS, SAVE_MOVES_FIRST, SpellingAdmin, listedPools, type Listing, type Pool, type SpellingData, type SpellingWord } from "./Spelling";
import { NEW_TASK, nameProblem, routeTask, taskPath, type TaskRef } from "../taskRef";

export type TaskData = {
  name: string;
  type: string;
  file: string;
  version: string;
  groups: string[];
  clients: string[];
  fields: Record<string, string>;
  /** The household's today, `yyyy-mm-dd`. */
  today: string;
  spelling?: SpellingData;
  parts_of_speech?: PosData;
  skip_counting?: SkipData;
  arithmetic?: ArithmeticData;
};

export type Result = {
  intent: "save" | "retire" | "record" | "lock" | "rename" | "discard";
  ok: boolean;
  message?: string;
  warnings?: string[];
  error?: string;
  errors?: string[];
  confirm?: string;
  /** A new task's page, once its name and type are locked in. */
  page?: TaskData;
  /** The task a create or a rename wrote, whose page opens next. */
  task?: TaskRef;
  /** The words in the directories a refused save chose. */
  spelling?: { words: SpellingWord[]; problems: string[] };
};

/** The words in the directories a refused save chose, and those directories. */
type Refused = { directories: Record<string, string>; words: SpellingWord[]; problems: string[] };

/** What the new task page has before its name and type are locked in. */
type Blank = { types: string[]; clients: string[]; fields: Record<string, string>; today: string };

type Edits = {
  fields: Record<string, string>;
  groups: string[] | null;
  settings: Record<string, string>;
  moves: Record<string, Pool>;
  /** A parts of speech task's sentences, once anything in them has been touched. */
  blocks: Block[] | null;
  /** Each weighted number list touched, such as a skip counting task's difference. */
  lists: ListEdits;
  /** A spelling task's directory fields chosen on the page, as paths from the data directory. */
  directories: Record<string, string>;
};

const NO_EDITS: Edits = { fields: {}, groups: null, settings: {}, moves: {}, blocks: null, lists: {}, directories: {} };
const ADD_WORDS = "Add words to the new directories from the Words menu. Its Apply saves the directories with the words.";
const ADD_WORDS_NEW = "Add words to the new directories from the Words menu, then save the new task.";

const DATES = ["available_from", "due_date"];

const GROUPS: { legend: string; keys: string[] }[] = [
  { legend: "Cooldowns and limits", keys: ["pass_cooldown", "failure_cooldown", "max_skips", "max_passes"] },
  { legend: "Dates", keys: DATES },
];
const PLACEHOLDERS: Record<string, string> = { pass_cooldown: "1" };
const NEW_TITLE = "New task";
const CHOOSE_TYPE = "Choose the task's type.";
const SAVE_FIRST = "Save the changes on this page first.";

/** What another page, such as the new week's words, reports on the task page it opens. */
export type Reported = { message: string; warnings: string[] };

export async function taskLoader({ request, params }: LoaderFunctionArgs): Promise<TaskData> {
  return api<TaskData>(taskPath(routeTask(params)), { page: pageOf(request), signal: request.signal });
}

/**
 * Choosing a pool filter changes only the query string, so the task is not fetched again.
 *
 * Nor is it after a refused save. A file changed on the server since the page
 * opened must stay refused until the parent reloads the page and sees it.
 * A kept recording fetches it again on the same address, to list the new clips.
 */
export function taskShouldRevalidate({ currentUrl, nextUrl, formMethod, actionResult, defaultShouldRevalidate }: ShouldRevalidateFunctionArgs) {
  if (!formMethod && currentUrl.pathname === nextUrl.pathname && currentUrl.search !== nextUrl.search) return false;
  const result = actionResult as Result | undefined;
  if (result?.ok === false) return false;
  // A renamed task's old address has no task. Its page opens at the new address instead.
  if (result?.intent === "rename" && result.task) return false;
  return defaultShouldRevalidate;
}

/** Save the page, retire one word, or rename the task. Sent from the page on show, so a refusal returns to it. */
export async function taskAction({ request, params }: ActionFunctionArgs): Promise<Result> {
  const { intent, ...body } = (await request.json()) as { intent: Result["intent"] } & Record<string, unknown>;
  const suffixes: Partial<Record<Result["intent"], string>> = { retire: "/retire", rename: "/rename", discard: "/week/cancel" };
  return send(intent, taskPath(routeTask(params)) + (suffixes[intent] ?? ""), request, body);
}

/**
 * The New task page. With ``name`` and ``type`` in the query string, as a setup of a new spelling task's words goes
 * back to it, the name and type are locked in again, and any directory fields there are chosen again.
 */
type NewTaskData = Blank & { draft: { name: string; type: string }; locked: TaskData | null; directories: Record<string, string>; refusal: string | null };

export async function newTaskLoader({ request }: LoaderFunctionArgs): Promise<NewTaskData> {
  const page = pageOf(request);
  const query = new URL(request.url).searchParams;
  const blank = await api<Blank>(NEW_TASK, { page, signal: request.signal });
  const draft = { name: query.get("name") ?? "", type: query.get("type") ?? "" };
  const directories = Object.fromEntries(DIRECTORY_FIELDS.flatMap((field) => (query.has(field) ? [[field, query.get(field) ?? ""]] : [])));
  if (!draft.name || !draft.type) return { ...blank, draft, locked: null, directories: {}, refusal: null };
  try {
    const locked = await api<TaskData>(`${NEW_TASK}/check`, { page, method: "POST", body: draft, signal: request.signal });
    return { ...blank, draft, locked, directories, refusal: null };
  } catch (error) {
    if (error instanceof ApiError) return { ...blank, draft, locked: null, directories: {}, refusal: error.message };
    throw error;
  }
}

/** Lock in a new task's name and type, which writes nothing, or write the new task. */
export async function newTaskAction({ request }: ActionFunctionArgs): Promise<Result> {
  const { intent, ...body } = (await request.json()) as { intent: Result["intent"] } & Record<string, unknown>;
  return send(intent, intent === "lock" ? `${NEW_TASK}/check` : NEW_TASK, request, body);
}

async function send(intent: Result["intent"], path: string, request: Request, body: unknown): Promise<Result> {
  try {
    const done = await api<Omit<Result, "intent" | "ok">>(path, { page: pageOf(request), method: "POST", body });
    if (intent === "lock") return { intent, ok: true, page: done as unknown as TaskData };
    return { intent, ok: true, ...done };
  } catch (error) {
    if (error instanceof ApiError) return { intent, ok: false, ...(error.data as Partial<Result>), error: error.message };
    throw error;
  }
}

export function Task() {
  const data = useLoaderData() as TaskData;
  return <TaskEditor key={`${data.type}/${data.name}`} data={data} />;
}

export function NewTask() {
  const blank = useLoaderData() as NewTaskData;
  const search = useLocation().search;
  const data = useMemo<TaskData>(
    () => ({ name: "", type: "", file: "", version: "", groups: [], clients: blank.clients, fields: blank.fields, today: blank.today }),
    [blank],
  );
  return <TaskEditor key={search} data={data} types={blank.types} restored={blank} />;
}

/** The word moves that change a listed word's pool. */
function pendingMoves(moves: Record<string, Pool>, words: SpellingWord[]): Record<string, Pool> {
  const pools = new Map(words.map((word) => [word.key, word.pool]));
  return Object.fromEntries(Object.entries(moves).filter(([key, pool]) => pools.has(key) && pools.get(key) !== pool));
}

/** Whether anything on the page differs from the file. ``words`` is the spelling word list on show. */
function changed(data: TaskData, edits: Edits, words: SpellingWord[]): boolean {
  const differs = (shown: Record<string, string>, edited: Record<string, string>) =>
    Object.entries(edited).some(([key, value]) => value.trim() !== (shown[key] ?? "").trim());
  const settings = (data.spelling ?? data.parts_of_speech ?? data.skip_counting ?? data.arithmetic)?.settings ?? {};
  if (differs(data.fields, edits.fields) || differs(settings, edits.settings)) return true;
  if (edits.groups !== null && edits.groups.join("\n") !== data.groups.join("\n")) return true;
  if (data.parts_of_speech && edits.blocks !== null && blocksChanged(data.parts_of_speech, edits.blocks)) return true;
  if (data.skip_counting && shownDifference(data.skip_counting, edits.settings, edits.lists.difference).changed) return true;
  if (data.arithmetic && Object.keys(arithmeticLists(shownArithmetic(data.arithmetic, edits.settings, edits.lists))).length > 0) return true;
  if (data.spelling && Object.keys(changedDirectories(data.spelling.directories, edits.directories)).length > 0) return true;
  return Object.keys(pendingMoves(edits.moves, words)).length > 0;
}

function sameDirectories(a: Record<string, string>, b: Record<string, string>): boolean {
  const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
  return [...keys].every((key) => a[key] === b[key]);
}

/**
 * A task's page. With ``types``, it is the new task page: Save first locks in
 * the name and type, then the type's own section opens, and the next Save
 * writes the task. A written task's page can be renamed.
 */
function TaskEditor({ data: given, types, restored }: { data: TaskData; types?: string[]; restored?: NewTaskData }) {
  const reported = useLocation().state as Reported | null;
  const navigate = useNavigate();
  const creating = types !== undefined;
  const [locked, setLocked] = useState<TaskData | null>(restored?.locked ?? null);
  const data = locked ?? given;
  const [draft, setDraft] = useState(restored?.draft ?? { name: "", type: "" });
  const [renaming, setRenaming] = useState<string | null>(null);
  const [edits, setEdits] = useState<Edits>({ ...NO_EDITS, directories: restored?.directories ?? {} });
  const [result, setResult] = useState<Result | null>(
    reported?.message
      ? { intent: "record", ok: true, ...reported }
      : restored?.refusal
        ? { intent: "lock", ok: false, error: restored.refusal }
        : null,
  );
  const [asking, setAsking] = useState<string | null>(null);
  const [refused, setRefused] = useState<Refused | null>(null);
  const [switching, setSwitching] = useState<{ to: string; mode: WordsMode } | null>(null);
  const discarded = useRef<string | null>(null);
  const sentDirectories = useRef<Record<string, string>>({});
  const [searchParams, setSearchParams] = useSearchParams();
  const fetcher = useFetcher<Result>();
  const revalidator = useRevalidator();
  const handled = useRef<Result | undefined>(undefined);
  // Set when a create or a rename opens the task's page, which loses nothing.
  const opening = useRef(false);
  const nameBox = useRef<HTMLInputElement>(null);
  useTitle(creating ? NEW_TITLE : data.name);
  const naming = creating && locked === null;
  const name = naming ? draft.name : (renaming ?? data.name);
  const problem = naming || renaming !== null ? nameProblem(name) : null;
  // The name's problem is shown as it stood when the box last lost focus, not while it is typed.
  const [checked, setChecked] = useState<string | null>(null);
  const shownProblem = (naming || renaming !== null) && checked !== null ? nameProblem(checked) : null;
  const frozen = naming || renaming !== null;
  const spelling = data.spelling;
  const chosen = spelling ? { ...spelling.directories, ...edits.directories } : {};
  const unsavedDirectories = spelling ? changedDirectories(spelling.directories, chosen) : {};
  const directoriesMoved = Object.keys(unsavedDirectories).length > 0;
  const directoryProblems = sameDirectoryProblems(chosen);
  const listing: Listing = !spelling
    ? null
    : !directoriesMoved
      ? spelling
      : refused !== null && sameDirectories(refused.directories, chosen)
        ? refused
        : null;
  const listedWords = listing?.words ?? [];
  const moving = pendingMoves(edits.moves, listedWords);
  const dirty = naming
    ? draft.name !== "" || draft.type !== ""
    : creating || (renaming !== null ? renaming !== data.name : changed(data, edits, listedWords));
  // Unsaved directories go with a Words link, so following one asks only when something else is unsaved too.
  // A new task's name and type go with the link too, once locked in.
  const otherDirty = dirty && (naming || renaming !== null || changed(data, { ...edits, directories: {} }, listedWords));
  const blocker = useBlocker(({ currentLocation, nextLocation }) => {
    if (!dirty || opening.current || currentLocation.pathname === nextLocation.pathname) return false;
    return otherDirty || !nextLocation.pathname.startsWith(`${taskPath(data)}/words/`);
  });
  const pos = data.parts_of_speech;
  const shownBlocks = useMemo(() => (pos ? loaded(pos) : []), [pos]);
  const blocks = edits.blocks ?? shownBlocks;
  const skip = data.skip_counting;
  const difference = skip ? shownDifference(skip, edits.settings, edits.lists.difference) : null;
  const differenceTrouble = skip && difference ? differenceProblems(difference.rows, skip, edits.settings) : [];
  const sums = data.arithmetic ? shownArithmetic(data.arithmetic, edits.settings, edits.lists) : null;
  const undated = DATES.some((key) => key in data.fields && dateProblem(edits.fields[key] ?? data.fields[key]) !== null);
  const held = frozen
    ? problem !== null || (naming && draft.type === "")
    : undated ||
      Object.keys(directoryProblems).length > 0 ||
      (pos !== undefined && blocked(blocks)) ||
      (difference !== null && skipBlocked(difference, differenceTrouble)) ||
      (sums !== null && sums.count > 0);
  const fixFirst = frozen ? (problem ?? CHOOSE_TYPE) : pos && !undated ? FIX_FIRST : FIX_ON_PAGE;

  const save = useCallback(
    (confirmed = false) => {
      if (fetcher.state !== "idle" || !dirty) return;
      if (frozen) setChecked(name);
      if (held) {
        setResult({ intent: "save", ok: false, error: fixFirst });
        return;
      }
      const post = { method: "post", encType: "application/json" } as const;
      if (naming) {
        fetcher.submit({ intent: "lock", ...draft }, post);
        return;
      }
      if (renaming !== null) {
        fetcher.submit({ intent: "rename", name: renaming, version: data.version }, post);
        return;
      }
      const lists: Record<string, ServiceRow[] | "default"> = {};
      const sentDifference = difference ? differenceRequest(difference) : undefined;
      if (sentDifference !== undefined) lists.difference = sentDifference;
      if (sums) Object.assign(lists, arithmeticLists(sums));
      const groups = edits.groups ?? data.groups;
      sentDirectories.current = chosen;
      fetcher.submit(
        {
          intent: "save",
          ...(creating ? { type: data.type, name: data.name } : { version: data.version }),
          fields: { ...data.fields, ...edits.fields },
          groups,
          ...(data.spelling
            ? {
                settings: { ...data.spelling.settings, ...edits.settings },
                moves: moving,
                ...(directoriesMoved ? { directories: unsavedDirectories } : {}),
              }
            : {}),
          ...(pos ? { settings: { ...pos.settings, ...edits.settings }, sentences: toRequest(blocks) } : {}),
          ...(skip ? { settings: { ...skip.settings, ...edits.settings }, lists } : {}),
          ...(data.arithmetic ? { settings: { ...data.arithmetic.settings, ...edits.settings }, lists } : {}),
          confirmed,
        },
        post,
      );
    },
    [fetcher, data, edits, dirty, held, fixFirst, pos, blocks, skip, difference, sums, naming, draft, renaming, creating, frozen, name, chosen, moving, directoriesMoved, unsavedDirectories],
  );

  const changeBlocks = useCallback(
    (change: (current: Block[]) => Block[]) => setEdits((current) => ({ ...current, blocks: change(current.blocks ?? shownBlocks) })),
    [shownBlocks],
  );

  /** Change a number list's rows. A list not yet touched, or the default list, starts from the rows on show. */
  const changeList = (field: string, shown: NumberRow[], change: (rows: NumberRow[]) => NumberRow[]) =>
    setEdits((current) => {
      const now = current.lists[field];
      return { ...current, lists: { ...current.lists, [field]: change(Array.isArray(now) ? now : shown) } };
    });
  const setList = (field: string, list: ListEdit) => setEdits((current) => ({ ...current, lists: { ...current.lists, [field]: list } }));
  const setSetting = (key: string, text: string) => setEdits((current) => ({ ...current, settings: { ...current.settings, [key]: text } }));

  const retire = useCallback(
    (key: string) => fetcher.submit({ intent: "retire", word: key }, { method: "post", encType: "application/json" }),
    [fetcher],
  );

  useEffect(() => {
    const done = fetcher.data;
    if (fetcher.state !== "idle" || done === undefined || handled.current === done) return;
    handled.current = done;
    if (done.intent === "save" && !done.ok && done.confirm) {
      setAsking(done.confirm);
      return;
    }
    if (done.intent === "lock" && done.ok && done.page) {
      setLocked(done.page);
      setResult(null);
      return;
    }
    if (done.ok && done.task && (done.intent === "rename" || creating)) {
      opening.current = true;
      navigate(taskPath(done.task), { replace: true, state: { message: done.message ?? "", warnings: done.warnings ?? [] } satisfies Reported });
      return;
    }
    if (done.intent === "discard" && done.ok && discarded.current !== null) {
      const to = discarded.current;
      discarded.current = null;
      navigate(to);
      return;
    }
    setResult(done);
    if (done.intent === "save" && !done.ok && done.spelling) setRefused({ directories: sentDirectories.current, ...done.spelling });
    if (done.intent === "save" && done.ok) {
      setEdits(NO_EDITS);
      setRefused(null);
    }
  }, [fetcher.state, fetcher.data, creating, navigate]);

  const isRenaming = renaming !== null;
  useEffect(() => {
    if (!isRenaming) return;
    nameBox.current?.focus();
    nameBox.current?.select();
  }, [isRenaming]);
  useEffect(() => {
    if (naming) nameBox.current?.focus();
  }, [naming]);

  const startRename = () => {
    setResult(null);
    setChecked(null);
    setRenaming(data.name);
  };
  const cancelRename = () => {
    setChecked(null);
    setRenaming(null);
  };

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
    function leaving(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", leaving);
    return () => window.removeEventListener("beforeunload", leaving);
  }, [dirty]);

  const value = (key: string) => edits.fields[key] ?? data.fields[key] ?? "";
  const setField = (key: string, text: string) => setEdits((current) => ({ ...current, fields: { ...current.fields, [key]: text } }));
  const groups = edits.groups ?? data.groups;
  const toggleGroup = (name: string) =>
    setEdits((current) => {
      const now = current.groups ?? data.groups;
      const next = now.includes(name) ? now.filter((group) => group !== name) : data.clients.filter((client) => client === name || now.includes(client));
      return { ...current, groups: next };
    });
  const asked = searchParams.get("pool") ?? "";
  const pool = POOL_FILTERS.some(([option]) => option === asked) ? asked : "";
  const query = directoryQuery(unsavedDirectories);
  const wordsLinks: (MenuLink & { mode: WordsMode })[] = WORDS_MODES.map(({ mode, label: text }) => ({ mode, label: text, to: wordsPath(data, mode) + query }));
  const followWords = (event: MouseEvent<HTMLAnchorElement>, link: MenuLink) => {
    const mode = wordsLinks.find((each) => each.to === link.to)?.mode;
    const setup = spelling?.setup;
    if (!mode || !setup || setup.mode === mode) return;
    event.preventDefault();
    setSwitching({ to: link.to, mode });
  };

  return (
    <>
      <ContextBar>
        <nav className="crumbs" aria-label="Where you are">
          <ol>
            <li>Tasks</li>
            <li>
              <h1 className="bar-title">{creating ? NEW_TITLE : data.name}</h1>
            </li>
          </ol>
        </nav>
        {data.spelling && (
          <label className="bar-field">
            Pool
            <select
              value={pool}
              disabled={frozen}
              onChange={(event) => setSearchParams(event.target.value ? { pool: event.target.value } : {})}
            >
              {POOL_FILTERS.map(([option, label]) => (
                <option key={option} value={option}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        )}
        {spelling && !naming && <MenuLinks label="Words" icon={ListPlus} links={wordsLinks} onFollow={followWords} />}
        <div className="bar-end bar-actions">
          {dirty && (
            <span className="unsaved">
              <PencilLine aria-hidden="true" />
              Unsaved changes
            </span>
          )}
          {!creating && (
            <button
              type="button"
              className="button button-quiet"
              onClick={renaming === null ? startRename : cancelRename}
              disabled={fetcher.state !== "idle" || (renaming === null && dirty)}
              title={renaming !== null ? "Put the old name back" : dirty ? SAVE_FIRST : "Rename this task"}
            >
              {renaming === null ? <TextCursorInput aria-hidden="true" /> : <X aria-hidden="true" />}
              {renaming === null ? "Rename" : "Cancel rename"}
            </button>
          )}
          <button
            type="button"
            className="button"
            onClick={() => save()}
            disabled={fetcher.state !== "idle" || !dirty || held}
            title={held ? fixFirst : dirty ? "Save (Ctrl+S)" : "Nothing to save"}
          >
            <Save aria-hidden="true" />
            Save
          </button>
        </div>
      </ContextBar>

      <div className="task-common">
        <fieldset>
          <legend>Task</legend>
          <div className="settings">
            <label className="setting">
              <span title="name">{label("name")}</span>
              <input
                ref={nameBox}
                type="text"
                value={name}
                readOnly={!frozen}
                aria-invalid={shownProblem !== null || undefined}
                data-changed={(renaming !== null && renaming !== data.name) || undefined}
                onChange={(event) => (naming ? setDraft({ ...draft, name: event.target.value }) : setRenaming(event.target.value))}
                onBlur={() => frozen && setChecked(name)}
                onKeyDown={(event) => {
                  if (event.key === "Escape" && renaming !== null) cancelRename();
                }}
              />
            </label>
            {shownProblem && <p className="note note-problem setting-problem">{shownProblem}</p>}
            {creating ? (
              <label className="setting">
                <span title="type">{label("type")}</span>
                <select value={data.type || draft.type} disabled={!naming} onChange={(event) => setDraft({ ...draft, type: event.target.value })}>
                  <option value="">Choose…</option>
                  {types.map((type) => (
                    <option key={type} value={type}>
                      {type}
                    </option>
                  ))}
                </select>
              </label>
            ) : (
              <>
                <span title="type">{label("type")}</span>
                <span>{data.type}</span>
              </>
            )}
          </div>
          <fieldset className="lock-area" disabled={frozen}>
            <MultiSelect
              label="Client Groups"
              options={data.clients}
              selected={groups}
              onToggle={toggleGroup}
              changed={groups.join("\n") !== data.groups.join("\n")}
            />
          </fieldset>
        </fieldset>
        {GROUPS.map(({ legend, keys }) => {
          const shown = keys.filter((key) => key in data.fields);
          if (shown.length === 0) return null;
          return (
            <fieldset key={legend} disabled={frozen}>
              <legend>{legend}</legend>
              <div className="settings">
                {shown.map((key) => {
                  const changed = value(key).trim() !== (data.fields[key] ?? "").trim();
                  return DATES.includes(key) ? (
                    <DateField
                      key={key}
                      name={key}
                      label={label(key)}
                      value={value(key)}
                      today={data.today}
                      changed={changed}
                      onChange={(text) => setField(key, text)}
                    />
                  ) : (
                    <label key={key} className="setting">
                      <span title={key}>{label(key)}</span>
                      <input
                        type="text"
                        inputMode="numeric"
                        value={value(key)}
                        placeholder={PLACEHOLDERS[key]}
                        data-changed={changed || undefined}
                        onChange={(event) => setField(key, event.target.value)}
                      />
                    </label>
                  );
                })}
              </div>
            </fieldset>
          );
        })}
      </div>

      <hr className="task-divider" />

      {!naming && (
        <fieldset className="lock-area" disabled={frozen} inert={frozen}>
          {spelling ? (
            <SpellingAdmin
              task={creating ? null : data}
              data={spelling}
              filter={pool}
              settings={edits.settings}
              moves={edits.moves}
              chosen={chosen}
              unsaved={unsavedDirectories}
              directoryProblems={directoryProblems}
              listing={listing}
              directoriesLocked={Object.keys(moving).length > 0 ? SAVE_MOVES_FIRST : null}
              onSetting={(key, text) => setEdits((current) => ({ ...current, settings: { ...current.settings, [key]: text } }))}
              onDirectory={(field, path) => setEdits((current) => ({ ...current, directories: { ...current.directories, [field]: path } }))}
              onMove={(key, to) => setEdits((current) => ({ ...current, moves: { ...current.moves, [key]: to } }))}
              onRetire={retire}
              onPlayFailed={(message) => setResult({ intent: "retire", ok: false, error: message })}
              onRecorded={(message, written) => {
                setResult({ intent: "record", ok: true, message, warnings: [] });
                if (written) void revalidator.revalidate();
              }}
              onMade={(message) => setResult({ intent: "record", ok: true, message, warnings: [] })}
            />
          ) : pos ? (
            <PartsOfSpeechAdmin
              data={pos}
              blocks={blocks}
              settings={edits.settings}
              onSetting={(key, text) => setEdits((current) => ({ ...current, settings: { ...current.settings, [key]: text } }))}
              onBlocks={changeBlocks}
            />
          ) : skip && difference ? (
            <SkipCountingAdmin
              data={skip}
              settings={edits.settings}
              shown={difference}
              problems={differenceTrouble}
              onSetting={setSetting}
              onRows={(change) => changeList("difference", difference.rows, change)}
              onDefault={() => setList("difference", "default")}
            />
          ) : data.arithmetic && sums ? (
            <ArithmeticAdmin
              data={data.arithmetic}
              settings={edits.settings}
              shown={sums}
              onSetting={setSetting}
              onRows={(field, change) => changeList(field, sums[field].rows, change)}
            />
          ) : (
            <p>Task-specific administration for {data.type} tasks is not built yet.</p>
          )}
        </fieldset>
      )}

      <StatusBar>
        {result && <Outcome result={result} />}
        {result && !result.ok && result.spelling && <span className="status-refused">{creating ? ADD_WORDS_NEW : ADD_WORDS}</span>}
        {listing && <span>{counts(listing.words, pool)}</span>}
        {pos && <span>{countsText(blocks)}</span>}
        {difference && <span>{skipCounts(difference, differenceTrouble)}</span>}
        {sums && <span>{problemsText(sums)}</span>}
      </StatusBar>

      {asking !== null && (
        <Dialog
          title="Save anyway?"
          message={asking}
          confirm="Save"
          cancel="Cancel"
          onConfirm={() => {
            setAsking(null);
            save(true);
          }}
          onCancel={() => setAsking(null)}
        />
      )}
      {switching !== null && spelling?.setup && (
        <Dialog
          title={THROW_AWAY_TITLE}
          message={throwAwayQuestion(spelling.setup, switching.mode)}
          confirm="Throw away"
          cancel="Keep it"
          onConfirm={() => {
            discarded.current = switching.to;
            setSwitching(null);
            fetcher.submit({ intent: "discard" }, { method: "post", encType: "application/json" });
          }}
          onCancel={() => setSwitching(null)}
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

/** The status bar's report of the last action: what it did, with any warnings, or why it was refused. */
export function Outcome({ result }: { result: Pick<Result, "ok" | "message" | "warnings" | "error" | "errors"> }) {
  if (result.ok) {
    return (
      <>
        <span className="status-done">{result.message}</span>
        {result.warnings?.map((warning) => (
          <span key={warning} className="status-refused">
            {warning}
          </span>
        ))}
      </>
    );
  }
  return (
    <>
      <span className="status-refused">{result.error}</span>
      {result.errors && result.errors.length > 0 && (
        <ul className="status-errors">
          {result.errors.map((problem) => (
            <li key={problem}>{problem}</li>
          ))}
        </ul>
      )}
    </>
  );
}

function counts(words: SpellingWord[], filter: string): string {
  const parts = listedPools(filter).map((pool) => {
    const count = words.filter((word) => word.pool === pool).length;
    return `${count} ${pool}`;
  });
  return `Words listed: ${parts.join(", ")}.`;
}
