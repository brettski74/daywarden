import { PencilLine, Save, TextCursorInput, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  Link,
  useBlocker,
  useFetcher,
  useLoaderData,
  useLocation,
  useNavigate,
  type ActionFunctionArgs,
  type LoaderFunctionArgs,
  type ShouldRevalidateFunctionArgs,
} from "react-router";
import { ApiError, api, pageOf } from "../api";
import { Dialog } from "../components/Dialog";
import { CapitalisationEditor } from "../components/CapitalisationEditor";
import { SentenceEditor } from "../components/SentenceEditor";
import * as capital from "../capitalisation";
import { label } from "../labels";
import { kindOf, poolData, type PoolKind, type PoolReport } from "../pools";
import {
  DEFAULT_LEVEL,
  FIX_FIRST,
  blocked,
  blocksChanged,
  countsText,
  levelProblem,
  loaded,
  toRequest,
  type Block,
  type PoolData,
} from "../sentences";
import { ContextBar, StatusBar, useTitle } from "../slots";
import { Outcome } from "./Task";

type Intent = "save" | "rename" | "delete";
type Result = {
  intent: Intent;
  ok: boolean;
  message?: string;
  warnings?: string[];
  error?: string;
  errors?: string[];
};

const SAVE_FIRST = "Save the changes on this page first.";
const NAME_NEEDED = "Give the pool a name.";

/** What differs between the pools' sentence editors: how the blocks are made, judged, sent, and drawn. */
type Editor = {
  loaded: (data: PoolData) => unknown[];
  changed: (data: PoolData, blocks: unknown[]) => boolean;
  blocked: (blocks: unknown[]) => boolean;
  request: (blocks: unknown[]) => unknown;
  counts: (blocks: unknown[]) => string;
  draw: (props: { data: PoolData; blocks: unknown[]; poolLevel: string; onBlocks: (change: (blocks: unknown[]) => unknown[]) => void }) => ReactNode;
};

const PARTS_EDITOR: Editor = {
  loaded: (data) => loaded(data),
  changed: (data, blocks) => blocksChanged(data, blocks as Block[]),
  blocked: (blocks) => blocked(blocks as Block[]),
  request: (blocks) => toRequest(blocks as Block[]),
  counts: (blocks) => countsText(blocks as Block[]),
  draw: ({ data, blocks, poolLevel, onBlocks }) => (
    <SentenceEditor data={data} blocks={blocks as Block[]} poolLevel={poolLevel} onBlocks={onBlocks as never} />
  ),
};
const CAPITALISATION_EDITOR: Editor = {
  loaded: (data) => capital.loaded(data as unknown as capital.CapPoolData),
  changed: (data, blocks) => capital.blocksChanged(data as unknown as capital.CapPoolData, blocks as capital.CapBlock[]),
  blocked: (blocks) => capital.blocked(blocks as capital.CapBlock[]),
  request: (blocks) => capital.toRequest(blocks as capital.CapBlock[]),
  counts: (blocks) => capital.countsText(blocks as capital.CapBlock[]),
  draw: ({ data, blocks, poolLevel, onBlocks }) => (
    <CapitalisationEditor data={data as unknown as capital.CapPoolData} blocks={blocks as capital.CapBlock[]} poolLevel={poolLevel} onBlocks={onBlocks as never} />
  ),
};

function editorOf(kind: PoolKind): Editor {
  return kind.list.includes("capitalisation") ? CAPITALISATION_EDITOR : PARTS_EDITOR;
}

export async function poolLoader({ request, params }: LoaderFunctionArgs): Promise<PoolData> {
  return api<PoolData>(poolData(params.id ?? "", kindOf(new URL(request.url).pathname)), { page: pageOf(request), signal: request.signal });
}

/** Save, rename, or delete the pool. Sent from the page on show, so a refusal returns to it. */
export async function poolAction({ request, params }: ActionFunctionArgs): Promise<Result> {
  const { intent, ...body } = (await request.json()) as { intent: Intent } & Record<string, unknown>;
  const suffix = intent === "save" ? "" : `/${intent}`;
  try {
    const done = await api<Omit<Result, "intent" | "ok">>(poolData(params.id ?? "", kindOf(new URL(request.url).pathname)) + suffix, { page: pageOf(request), method: "POST", body });
    return { intent, ok: true, ...done };
  } catch (error) {
    if (error instanceof ApiError) return { intent, ok: false, ...(error.data as Partial<Result>), error: error.message };
    throw error;
  }
}

/** A refused change keeps the page as it was, so a file changed on the server stays refused until the page is reloaded. */
export function poolShouldRevalidate({ actionResult, defaultShouldRevalidate }: ShouldRevalidateFunctionArgs) {
  const result = actionResult as Result | undefined;
  if (result?.ok === false) return false;
  if (result?.intent === "delete") return false;
  return defaultShouldRevalidate;
}

export function Pool() {
  const data = useLoaderData() as PoolData;
  return <PoolEditor key={data.id} data={data} />;
}

/** The pool's name and level of difficulty, then its sentences. */
function PoolEditor({ data }: { data: PoolData }) {
  const location = useLocation();
  const reported = location.state as PoolReport | null;
  const kind = kindOf(location.pathname);
  const editor = editorOf(kind);
  const navigate = useNavigate();
  const fetcher = useFetcher<Result>();
  const handled = useRef<Result | undefined>(undefined);
  const leaving = useRef(false);
  const nameBox = useRef<HTMLInputElement>(null);
  const [level, setLevel] = useState<string | null>(null);
  const [edited, setEdited] = useState<unknown[] | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [result, setResult] = useState<Result | null>(reported?.message ? { intent: "save", ok: true, ...reported } : null);
  useTitle(data.name);

  const shownBlocks = useMemo(() => editor.loaded(data), [data, editor]);
  const blocks = edited ?? shownBlocks;
  const poolLevel = level ?? data.level_of_difficulty;
  const levelTrouble = levelProblem(poolLevel);
  const name = renaming ?? data.name;
  const nameTrouble = renaming !== null && renaming.trim() === "" ? NAME_NEEDED : null;
  const changed = poolLevel.trim() !== data.level_of_difficulty.trim() || (edited !== null && editor.changed(data, edited));
  const dirty = renaming !== null ? renaming.trim() !== data.name : changed;
  const held = renaming !== null ? nameTrouble !== null : levelTrouble !== null || editor.blocked(blocks);
  const fixFirst = renaming !== null ? (nameTrouble ?? "") : (levelTrouble ?? FIX_FIRST);
  const busy = fetcher.state !== "idle";

  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && !leaving.current && currentLocation.pathname !== nextLocation.pathname);

  const post = useCallback(
    (body: Record<string, unknown>) => fetcher.submit(body as never, { method: "post", encType: "application/json" }),
    [fetcher],
  );

  const save = useCallback(() => {
    if (busy || !dirty) return;
    if (held) {
      setResult({ intent: "save", ok: false, error: fixFirst });
      return;
    }
    if (renaming !== null) {
      post({ intent: "rename", name: renaming, version: data.version });
      return;
    }
    post({ intent: "save", version: data.version, level_of_difficulty: poolLevel, sentences: editor.request(blocks) });
  }, [busy, dirty, held, fixFirst, renaming, post, data.version, poolLevel, blocks, editor]);

  useEffect(() => {
    const done = fetcher.data;
    if (fetcher.state !== "idle" || done === undefined || handled.current === done) return;
    handled.current = done;
    if (done.intent === "delete" && done.ok) {
      leaving.current = true;
      navigate(kind.list, { replace: true, state: { message: done.message ?? "", warnings: done.warnings ?? [] } satisfies PoolReport });
      return;
    }
    setResult(done);
    if (done.ok) {
      setLevel(null);
      setEdited(null);
      setRenaming(null);
    }
  }, [fetcher.state, fetcher.data, navigate, kind.list]);

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
    function unload(event: BeforeUnloadEvent) {
      event.preventDefault();
      event.returnValue = "";
    }
    window.addEventListener("beforeunload", unload);
    return () => window.removeEventListener("beforeunload", unload);
  }, [dirty]);

  const isRenaming = renaming !== null;
  useEffect(() => {
    if (!isRenaming) return;
    nameBox.current?.focus();
    nameBox.current?.select();
  }, [isRenaming]);

  const changeBlocks = useCallback(
    (change: (current: unknown[]) => unknown[]) => setEdited((current) => change(current ?? shownBlocks)),
    [shownBlocks],
  );

  const count = data.sentences.length;
  return (
    <>
      <ContextBar>
        <nav className="crumbs" aria-label="Where you are">
          <ol>
            <li>Asset Administration</li>
            <li>
              <Link to={kind.list}>{kind.title}</Link>
            </li>
            <li>
              <h1 className="bar-title">{data.name}</h1>
            </li>
          </ol>
        </nav>
        <div className="bar-end bar-actions">
          {dirty && (
            <span className="unsaved">
              <PencilLine aria-hidden="true" />
              Unsaved changes
            </span>
          )}
          <button
            type="button"
            className="button button-quiet"
            onClick={() => {
              setResult(null);
              setRenaming(renaming === null ? data.name : null);
            }}
            disabled={busy || (renaming === null && dirty)}
            title={renaming !== null ? "Put the old name back" : dirty ? SAVE_FIRST : "Rename this pool"}
          >
            {renaming === null ? <TextCursorInput aria-hidden="true" /> : <X aria-hidden="true" />}
            {renaming === null ? "Rename" : "Cancel rename"}
          </button>
          <button
            type="button"
            className="button button-quiet"
            onClick={() => setDeleting(true)}
            disabled={busy || renaming !== null}
            title="Delete this pool"
          >
            <Trash2 aria-hidden="true" />
            Delete
          </button>
          <button
            type="button"
            className="button"
            onClick={save}
            disabled={busy || !dirty || held}
            title={held ? fixFirst : dirty ? "Save (Ctrl+S)" : "Nothing to save"}
          >
            <Save aria-hidden="true" />
            Save
          </button>
        </div>
      </ContextBar>

      <div className="task-common">
        <fieldset>
          <legend>Pool</legend>
          <div className="settings">
            <label className="setting">
              <span title="name">{label("name")}</span>
              <input
                ref={nameBox}
                type="text"
                value={name}
                readOnly={renaming === null}
                aria-invalid={nameTrouble !== null || undefined}
                data-changed={(renaming !== null && renaming.trim() !== data.name) || undefined}
                onChange={(event) => setRenaming(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Escape" && renaming !== null) setRenaming(null);
                }}
              />
            </label>
            {nameTrouble && <p className="note note-problem setting-problem">{nameTrouble}</p>}
            <label className="setting">
              <span title="level_of_difficulty">{label("level_of_difficulty")}</span>
              <input
                type="number"
                min="0.5"
                max="10"
                step="any"
                value={poolLevel}
                placeholder={DEFAULT_LEVEL}
                disabled={renaming !== null}
                aria-invalid={levelTrouble !== null || undefined}
                data-changed={poolLevel.trim() !== data.level_of_difficulty.trim() || undefined}
                onChange={(event) => setLevel(event.target.value)}
              />
            </label>
            {levelTrouble && <p className="note note-problem setting-problem">{levelTrouble}</p>}
          </div>
        </fieldset>
      </div>

      <hr className="task-divider" />

      <fieldset className="lock-area" disabled={renaming !== null} inert={renaming !== null}>
        {editor.draw({ data, blocks, poolLevel: poolLevel.trim() || DEFAULT_LEVEL, onBlocks: changeBlocks })}
      </fieldset>

      <StatusBar>
        {result && <Outcome result={result} />}
        <span>{editor.counts(blocks)}</span>
      </StatusBar>

      {deleting && (
        <Dialog
          title="Delete this pool?"
          message={`"${data.name}" and its ${count} sentence${count === 1 ? "" : "s"} are removed. A pool that a task uses cannot be deleted.`}
          confirm="Delete"
          cancel="Cancel"
          onConfirm={() => {
            setDeleting(false);
            post({ intent: "delete", version: data.version });
          }}
          onCancel={() => setDeleting(false)}
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
