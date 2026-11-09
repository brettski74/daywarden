import { afterEach, beforeEach, vi } from "vitest";

/** Stands in for MediaRecorder: a take of a few bytes, sent when it stops. */
export class FakeRecorder {
  static isTypeSupported = (type: string) => type === "audio/webm;codecs=opus";
  static last: FakeRecorder | null = null;
  state: "inactive" | "recording" = "inactive";
  mimeType: string;
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;

  constructor(_stream: unknown, options?: { mimeType?: string }) {
    this.mimeType = options?.mimeType ?? "";
    FakeRecorder.last = this;
  }

  start() {
    this.state = "recording";
  }

  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["the take"], { type: this.mimeType }) });
    this.onstop?.();
  }
}

/** What the browser plays, by path, and the microphone it opens. A test may replace the microphone. */
export const media: { played: string[]; microphone: () => Promise<unknown> } = {
  played: [],
  microphone: async () => undefined,
};

/** Give each test in the file a microphone, a recorder, and audio that records what it plays. */
export function useFakeMedia() {
  beforeEach(() => {
    media.played = [];
    FakeRecorder.last = null;
    media.microphone = async () => ({ getTracks: () => [{ stop: () => undefined }] });
    vi.stubGlobal("MediaRecorder", FakeRecorder);
    Object.defineProperty(window.navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: () => media.microphone() },
    });
    vi.spyOn(window.HTMLMediaElement.prototype, "play").mockImplementation(function (this: HTMLMediaElement) {
      media.played.push(new URL(this.src).pathname);
      return Promise.resolve();
    });
    vi.spyOn(window.HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
  });

  afterEach(() => {
    delete (window.navigator as { mediaDevices?: unknown }).mediaDevices;
  });
}
