import { Ban, Check, Circle, Mic, Repeat, RotateCcw, SkipForward, Square, Trash2, Undo2, Upload } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState, type ComponentType } from "react";
import { ApiError, BASE, api } from "../api";
import { DEFAULT_TEXTS, cutSettings, type CutTexts } from "../cutSettings";
import { useExpander } from "../motion";
import { decide, leftOver, outcomes, reviewOver, startReview, undo, type Decision, type Item, type Outcome, type Review } from "../review";
import { AdvancedSettings } from "./AdvancedSettings";

export type Clip = { id: string; start: number; ms: number };
type Cut = { take: string; clips: Clip[]; ignored: number; loudness: string };
export type Kept = { item: Item; clip: string };

type Props = {
  title: string;
  items: Item[];
  /** Write the kept clips and return the message to show, or throw the ApiError that refused them. */
  onKeep: (take: string, kept: Kept[]) => Promise<string>;
  /** Close the dialog, with a message for the page and whether anything was written, when the review was confirmed. */
  onClose: (confirmed?: { message: string; changed: boolean }) => void;
};

type Phase =
  | "asking"
  | "no-mic"
  | "ready"
  | "starting"
  | "recording"
  | "uploading"
  | "not-uploaded"
  | "cutting"
  | "not-cut"
  | "none"
  | "review"
  | "summary"
  | "saving";

type Action = Decision | "replay" | "back";

const RECORDING_TYPES = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus", "audio/webm", "audio/ogg"];
/** How long after the start key the recorder starts, so the key's own clatter is not recorded. */
export const START_DELAY_MS = 500;
const CONTROLS: { action: Action; label: string; key: string; icon: ComponentType<{ "aria-hidden"?: boolean | "true" }>; title: string }[] = [
  { action: "keep", label: "Keep", key: "K", icon: Check, title: "This clip is the recording for this item" },
  { action: "junk", label: "Junk", key: "J", icon: Trash2, title: "This clip is noise or something else. Try the next clip for the same item" },
  { action: "discard", label: "Discard", key: "D", icon: Ban, title: "This clip is the item, but poor or badly cut. Move to the next item" },
  { action: "missing", label: "Missing", key: "M", icon: SkipForward, title: "This item was not said. Try this clip for the next item" },
  { action: "replay", label: "Replay", key: "R", icon: Repeat, title: "Play this clip again" },
  { action: "back", label: "Back", key: "B", icon: Undo2, title: "Undo the last decision" },
];
const ACTION_KEYS = new Map(CONTROLS.map((control) => [control.key.toLowerCase(), control.action]));
const MODIFIERS = new Set(["Shift", "Control", "Alt", "Meta", "AltGraph", "CapsLock", "Tab", "Escape", "Fn", "OS"]);

export function sessionEnded(button: string): string {
  return `Your session has ended. Sign in again in another tab, then press ${button}.`;
}

function microphoneProblem(error: unknown): string {
  const name = error instanceof DOMException || error instanceof Error ? error.name : "";
  if (name === "NotAllowedError" || name === "SecurityError") {
    return "The browser was not allowed to use the microphone, so nothing can be recorded. Allow the microphone for this site, then try again.";
  }
  if (name === "NotFoundError" || name === "OverconstrainedError") return "No microphone was found, so nothing can be recorded.";
  return `The microphone could not be opened, so nothing can be recorded. ${error instanceof Error ? error.message : ""}`.trim();
}

function takeType(type: string): string {
  if (type.startsWith("audio/webm") || type.startsWith("audio/ogg")) return type;
  return type.includes("ogg") ? "audio/ogg" : "audio/webm";
}

function clipAddress(take: string, clip: string): string {
  return `${BASE}/api/recordings/${encodeURIComponent(take)}/${encodeURIComponent(clip)}.opus`;
}

function minutes(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function outcomeText(outcome: Outcome): string {
  return { kept: "Kept", discarded: "Discarded", missing: "Missing" }[outcome.kind];
}

function itemName(item: Item): string {
  return `${item.key} (${item.kind})`;
}

/**
 * Record a take in the browser, cut it on the service, and review the clips against the items.
 *
 * Recording starts half a second after any key and stops on Enter, with
 * nothing to type in between. The take is uploaded once and can be cut again with other
 * Advanced settings. Nothing is written until Confirm.
 */
export function RecordDialog({ title, items, onKeep, onClose }: Props) {
  const heading = useId();
  const box = useRef<HTMLDivElement>(null);
  const [phase, setPhase] = useState<Phase>("asking");
  const [notice, setNotice] = useState<string | null>(null);
  const [uploadable, setUploadable] = useState(true);
  const [texts, setTexts] = useState<CutTexts>(DEFAULT_TEXTS);
  const [advanced, setAdvanced] = useState(false);
  const expander = { expanded: advanced, ...useExpander(advanced, setAdvanced) };
  const openAdvanced = useRef<() => void>(() => {});
  openAdvanced.current = () => {
    if (!advanced) expander.toggle();
  };
  const [take, setTake] = useState<string | null>(null);
  const [cut, setCut] = useState<Cut | null>(null);
  const [review, setReview] = useState<Review>(() => startReview(items.length));
  const [seconds, setSeconds] = useState(0);
  const stream = useRef<MediaStream | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const startTimer = useRef<number | undefined>(undefined);
  const recording = useRef<Blob | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);
  const closing = useRef(false);
  const latestTexts = useRef(texts);
  latestTexts.current = texts;
  const clips = cut?.clips ?? [];

  useEffect(() => {
    let cancelled = false;
    closing.current = false;
    const devices = typeof navigator === "undefined" ? undefined : navigator.mediaDevices;
    if (!devices?.getUserMedia || typeof MediaRecorder === "undefined") {
      setPhase("no-mic");
      setNotice("This browser cannot record here, so nothing can be recorded. Use a current Firefox or Chromium over HTTPS.");
      return;
    }
    devices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } }).then(
      (opened) => {
        if (cancelled) {
          opened.getTracks().forEach((track) => track.stop());
          return;
        }
        stream.current = opened;
        setPhase("ready");
      },
      (error) => {
        if (cancelled) return;
        setPhase("no-mic");
        setNotice(microphoneProblem(error));
      },
    );
    return () => {
      cancelled = true;
      closing.current = true;
      window.clearTimeout(startTimer.current);
      if (recorder.current?.state === "recording") recorder.current.stop();
      stream.current?.getTracks().forEach((track) => track.stop());
      audio.current?.pause();
    };
  }, []);

  useEffect(() => {
    box.current?.focus();
  }, [phase]);

  useEffect(() => {
    if (phase !== "recording") return;
    const started = Date.now();
    setSeconds(0);
    const timer = window.setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 250);
    return () => window.clearInterval(timer);
  }, [phase]);

  const play = useCallback(
    (clip: Clip | undefined) => {
      if (!clip || take === null) return;
      const player = audio.current ?? (audio.current = new Audio());
      player.pause();
      player.src = clipAddress(take, clip.id);
      player.play().catch(() => setNotice("The clip could not be played in this browser."));
    },
    [take],
  );

  useEffect(() => {
    // Each new step of the review plays its clip once, even when only the item moved on. Replay plays it again.
    if (phase === "review") play(clips[review.clip]);
  }, [phase, review.item, review.clip, cut]);

  function discard(id: string | null) {
    if (id === null) return;
    api(`/recordings/${encodeURIComponent(id)}/discard`, { page: null, method: "POST", body: {}, signedOut: "refuse" }).catch(() => undefined);
  }

  async function cutTake(id: string) {
    const settings = cutSettings(latestTexts.current);
    if (settings === null) {
      setPhase("not-cut");
      setNotice("Fix the Advanced settings, then press Cut.");
      openAdvanced.current();
      return;
    }
    audio.current?.pause();
    setPhase("cutting");
    setNotice(null);
    try {
      const result = await api<Cut>(`/recordings/${encodeURIComponent(id)}/cut`, { page: null, method: "POST", body: { settings }, signedOut: "refuse" });
      if (closing.current) return;
      setCut(result);
      setReview(startReview(items.length));
      setPhase(result.clips.length > 0 ? "review" : "none");
    } catch (error) {
      if (closing.current) return;
      setPhase("not-cut");
      setNotice(error instanceof ApiError ? (error.status === 401 ? sessionEnded("Cut") : error.message) : "The recording could not be cut. Check the connection, then press Cut.");
    }
  }

  async function upload() {
    const blob = recording.current;
    if (blob === null) return;
    setPhase("uploading");
    setNotice(null);
    try {
      const { take: id } = await api<{ take: string }>("/recordings", { page: null, method: "POST", audio: blob, signedOut: "refuse" });
      if (closing.current) {
        discard(id);
        return;
      }
      setTake(id);
      await cutTake(id);
    } catch (error) {
      if (closing.current) return;
      setPhase("not-uploaded");
      setUploadable(!(error instanceof ApiError && error.status === 413));
      if (error instanceof ApiError) setNotice(error.status === 401 ? sessionEnded("Upload") : error.message);
      else setNotice("The recording could not be uploaded. Check the connection, then press Upload.");
    }
  }

  function start() {
    if (stream.current === null || phase !== "ready") return;
    setNotice(null);
    setPhase("starting");
    startTimer.current = window.setTimeout(begin, START_DELAY_MS);
  }

  function begin() {
    startTimer.current = undefined;
    if (stream.current === null || closing.current) return;
    const supported = RECORDING_TYPES.find((type) => MediaRecorder.isTypeSupported?.(type));
    let started: MediaRecorder;
    try {
      started = new MediaRecorder(stream.current, supported ? { mimeType: supported } : undefined);
      started.start();
    } catch (error) {
      setNotice(`The recording could not start, so nothing was recorded. ${error instanceof Error ? error.message : ""}`.trim());
      setPhase("ready");
      return;
    }
    const chunks: Blob[] = [];
    started.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data);
    };
    started.onstop = () => {
      if (closing.current) return;
      recording.current = new Blob(chunks, { type: takeType(started.mimeType || supported || "") });
      void upload();
    };
    recorder.current = started;
    setPhase("recording");
  }

  function stop() {
    if (recorder.current?.state === "recording") recorder.current.stop();
  }

  function recordAgain() {
    discard(take);
    audio.current?.pause();
    recording.current = null;
    setTake(null);
    setCut(null);
    setNotice(null);
    setUploadable(true);
    setPhase(stream.current ? "ready" : "no-mic");
  }

  function cancel() {
    closing.current = true;
    window.clearTimeout(startTimer.current);
    stop();
    audio.current?.pause();
    discard(take);
    onClose();
  }

  function act(action: Action) {
    if (action === "replay") {
      if (phase === "review") play(clips[review.clip]);
      return;
    }
    if (action === "back") {
      if (phase !== "review" && phase !== "summary") return;
      const before = undo(review);
      if (before === review) return;
      setReview(before);
      setPhase("review");
      return;
    }
    if (phase !== "review") return;
    const next = decide(review, action, items.length, clips.length);
    setReview(next);
    if (reviewOver(next, items.length, clips.length)) {
      audio.current?.pause();
      setPhase("summary");
    }
  }

  async function confirm() {
    if (take === null || cut === null) return;
    const kept = outcomes(review).flatMap((outcome, index) =>
      outcome.kind === "kept" ? [{ item: items[index], clip: cut.clips[outcome.clip].id }] : [],
    );
    if (kept.length === 0) {
      closing.current = true;
      discard(take);
      onClose({ message: "Nothing was kept, so nothing changed.", changed: false });
      return;
    }
    setPhase("saving");
    setNotice(null);
    try {
      const message = await onKeep(take, kept);
      closing.current = true;
      onClose({ message, changed: true });
    } catch (error) {
      setPhase("summary");
      setNotice(error instanceof ApiError ? (error.status === 401 ? sessionEnded("Confirm") : error.message) : "The clips could not be saved. Check the connection, then press Confirm.");
    }
  }

  const handleKey = (event: KeyboardEvent) => {
    const target = event.target instanceof Element ? event.target : null;
    const plain = !event.ctrlKey && !event.altKey && !event.metaKey;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      event.stopPropagation();
      return;
    }
    if (phase === "starting" || phase === "recording") {
      event.preventDefault();
      event.stopPropagation();
      if (phase === "recording" && event.key === "Enter" && !event.repeat) stop();
      return;
    }
    if (event.key === "Escape") {
      if (phase === "asking" || phase === "no-mic" || phase === "ready") {
        event.preventDefault();
        cancel();
      }
      return;
    }
    const inField = target?.closest("input, select, textarea") != null;
    if (!plain || inField || MODIFIERS.has(event.key) || event.repeat) return;
    if (phase === "ready") {
      if (target?.closest("button") && (event.key === "Enter" || event.key === " ")) return;
      event.preventDefault();
      start();
      return;
    }
    const action = ACTION_KEYS.get(event.key.toLowerCase());
    if (action === undefined || (phase !== "review" && phase !== "summary") || target?.closest(".advanced")) return;
    if (phase === "summary" && action !== "back") return;
    event.preventDefault();
    act(action);
  };
  const latestKey = useRef(handleKey);
  latestKey.current = handleKey;
  useEffect(() => {
    const key = (event: KeyboardEvent) => latestKey.current(event);
    window.addEventListener("keydown", key, true);
    return () => window.removeEventListener("keydown", key, true);
  }, []);

  const item = items[review.item];
  const left = leftOver(review, items.length, clips.length);
  const canCut = take !== null && ["not-cut", "none", "review", "summary"].includes(phase);

  return (
    <div className="dialog-backdrop">
      <div className="dialog record-dialog" role="dialog" aria-modal="true" aria-labelledby={heading} tabIndex={-1} ref={box} data-phase={phase}>
        <h2 id={heading}>{title}</h2>

        {(phase === "asking" || phase === "ready" || phase === "starting" || phase === "recording") && (
          <>
            {phase === "asking" && <p>Asking the browser for the microphone…</p>}
            {phase === "ready" && <p className="record-prompt">Press any key to start recording.</p>}
            {phase === "starting" && (
              <p className="record-prompt" role="status">
                Get ready…
              </p>
            )}
            {phase === "recording" && (
              <p className="recording-indicator" role="status">
                <Circle className="recording-dot" aria-hidden="true" />
                Recording {minutes(seconds)}. Press Enter or Stop when you are done.
              </p>
            )}
            <p className="record-say">Say, with a pause after each:</p>
            <ol className="record-lines">
              {items.map((each) => (
                <li key={`${each.key}/${each.kind}`}>{each.line}</li>
              ))}
            </ol>
          </>
        )}
        {phase === "uploading" && <p role="status">Uploading the recording…</p>}
        {phase === "cutting" && <p role="status">Cutting the recording…</p>}
        {phase === "saving" && <p role="status">Saving the kept clips…</p>}
        {phase === "none" && <p>No clips were found in the recording. Record again, or change the Advanced settings and press Cut.</p>}

        {phase === "review" && item && (
          <div className="record-review">
            <p className="record-playing" aria-live="polite">
              Playing: {itemName(item)}
            </p>
            <p className="record-progress">
              {review.item + 1} of {items.length}: {itemName(item)}. Clip {review.clip + 1} of {clips.length}.
            </p>
            {item.line !== item.key && <p className="record-expected">{item.line}</p>}
            <div className="review-controls">
              {CONTROLS.map(({ action, label, key, icon: Icon, title: hint }) => (
                <button
                  key={action}
                  type="button"
                  className="button"
                  aria-keyshortcuts={key}
                  title={`${hint} (${key})`}
                  disabled={action === "back" && review.history.length === 0}
                  onClick={() => act(action)}
                >
                  <Icon aria-hidden="true" />
                  {label}
                  <kbd aria-hidden="true">{key}</kbd>
                </button>
              ))}
            </div>
          </div>
        )}

        {(phase === "summary" || (phase === "saving" && cut)) && (
          <div className="record-summary">
            <table>
              <tbody>
                {outcomes(review).map((outcome, index) => (
                  <tr key={`${items[index].key}/${items[index].kind}`}>
                    <th scope="row">{itemName(items[index])}</th>
                    <td>{outcomeText(outcome)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {left > 0 && (
              <p>
                {left} {left === 1 ? "clip was" : "clips were"} left over and will be ignored.
              </p>
            )}
          </div>
        )}

        {cut && (phase === "review" || phase === "summary" || phase === "none") && <p className="record-loudness">{cut.loudness}</p>}
        {notice && (
          <p className="problem" role="alert">
            {notice}
          </p>
        )}

        {phase !== "no-mic" && phase !== "asking" && (
          <AdvancedSettings texts={texts} onChange={setTexts} expander={expander} canCut={canCut} onCut={() => take && void cutTake(take)} />
        )}

        <div className="dialog-buttons">
          {phase === "ready" && (
            <button type="button" className="button" onClick={start}>
              <Mic aria-hidden="true" />
              Start
            </button>
          )}
          {phase === "recording" && (
            <button type="button" className="button" onClick={stop}>
              <Square aria-hidden="true" />
              Stop
            </button>
          )}
          {phase === "not-uploaded" && uploadable && (
            <button type="button" className="button" onClick={() => void upload()}>
              <Upload aria-hidden="true" />
              Upload
            </button>
          )}
          {phase === "none" && (
            <button type="button" className="button button-quiet" onClick={() => openAdvanced.current()} disabled={advanced}>
              Advanced
            </button>
          )}
          {(phase === "not-uploaded" || phase === "not-cut" || phase === "none" || phase === "summary") && (
            <button type="button" className="button button-quiet" onClick={recordAgain}>
              <RotateCcw aria-hidden="true" />
              Record again
            </button>
          )}
          {phase === "summary" && (
            <>
              <button type="button" className="button button-quiet" onClick={() => act("back")} aria-keyshortcuts="B" disabled={review.history.length === 0}>
                <Undo2 aria-hidden="true" />
                Back
                <kbd aria-hidden="true">B</kbd>
              </button>
              <button type="button" className="button" onClick={() => void confirm()}>
                <Check aria-hidden="true" />
                Confirm
              </button>
            </>
          )}
          <button type="button" className="button button-quiet" onClick={cancel} disabled={phase === "saving"}>
            Cancel
          </button>
        </div>
      </div>
    </div>
  );
}
