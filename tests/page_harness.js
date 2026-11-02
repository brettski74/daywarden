"use strict";
// Runs a quiz page's script on a fake clock, with a stub DOM, audio, and fetch.
//
// Reads {html, replies, clip_ms, run_ms} as JSON on stdin. `replies` maps each
// ?do= action to the list of JSON replies it gets, in order. Every clip with an
// `onended` handler ends `clip_ms` after it starts. The run presses Start, waits
// for the word to finish, types an answer and presses Enter, then lets `run_ms`
// pass. Prints the posts and plays it saw, each with the fake time it happened.

const fs = require("fs");
const vm = require("vm");

const input = JSON.parse(fs.readFileSync(0, "utf8"));
const config = input.html.match(/<script type="application\/json" id="quiz-config">([\s\S]*?)<\/script>/)[1];
const code = input.html.match(/<script>\n([\s\S]*?)<\/script>/)[1];

let now = 0;
let timers = [];
let timerIds = 0;
const events = [];

function setTimeout(fn, ms) {
  const id = ++timerIds;
  timers.push({ id, at: now + (ms || 0), fn });
  return id;
}

function clearTimeout(id) {
  timers = timers.filter((timer) => timer.id !== id);
}

async function settle() {
  for (let i = 0; i < 20; i++) await new Promise((done) => setImmediate(done));
}

async function advance(ms) {
  const until = now + ms;
  for (;;) {
    const due = timers.filter((timer) => timer.at <= until).sort((a, b) => a.at - b.at || a.id - b.id)[0];
    if (!due) break;
    clearTimeout(due.id);
    now = due.at;
    due.fn();
    await settle();
  }
  now = until;
}

class Element {
  constructor(id, tagName = "DIV") {
    this.id = id;
    this.tagName = tagName;
    this.hidden = false;
    this.disabled = false;
    this.readOnly = false;
    this.value = "";
    this.textContent = "";
    this.className = "";
    this.href = "";
    this.tabIndex = 0;
    this.style = { setProperty() {} };
    this.listeners = {};
  }
  addEventListener(type, fn) {
    (this.listeners[type] = this.listeners[type] || []).push(fn);
  }
  dispatch(type, fields = {}) {
    const event = { type, repeat: false, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...fields };
    event.preventDefault = () => {};
    for (const fn of this.listeners[type] || []) fn(event);
  }
  click() {
    this.dispatch("click");
  }
  focus() {
    document.activeElement = this;
  }
  select() {}
  setSelectionRange() {}
  submit() {}
  appendChild() {}
  querySelector() {
    return new Element(null);
  }
  getClientRects() {
    return this.hidden ? [] : [{}];
  }
}

const elements = new Map();
const document = {
  activeElement: null,
  getElementById(id) {
    if (!elements.has(id)) {
      const element = new Element(id, id === "answer" ? "INPUT" : "DIV");
      if (id === "quiz-config") element.textContent = config;
      elements.set(id, element);
    }
    return elements.get(id);
  },
  querySelectorAll: () => [],
  createElement: (tag) => new Element(null, tag.toUpperCase()),
  addEventListener() {},
};

class Audio {
  constructor() {
    this.src = "";
    this.onended = null;
    this.onerror = null;
  }
  play() {
    events.push({ at: now, kind: "play", what: this.src });
    if (this.onended) {
      const ended = this.onended;
      setTimeout(() => ended(), input.clip_ms);
    }
    return Promise.resolve();
  }
  pause() {}
}

async function fetch(url) {
  const action = new URL(url, "http://page").searchParams.get("do");
  events.push({ at: now, kind: "post", what: action });
  const reply = (input.replies[action] || []).shift();
  if (reply === undefined) return new Promise(() => {});
  return {
    redirected: false,
    status: 200,
    ok: true,
    headers: { get: () => "application/json" },
    json: async () => reply,
  };
}

vm.runInNewContext(code, {
  document,
  window: { location: { reload: () => events.push({ at: now, kind: "reload" }) } },
  performance: { now: () => now },
  requestAnimationFrame: () => 0,
  setTimeout,
  clearTimeout,
  Audio,
  fetch,
  URL,
  console,
});

(async () => {
  await settle();
  document.getElementById("start-button").click();
  await settle();
  await advance(input.clip_ms);
  const box = document.getElementById("answer");
  box.value = "answer";
  box.dispatch("keydown", { key: "Enter" });
  await settle();
  await advance(input.run_ms);
  process.stdout.write(JSON.stringify(events));
})();
