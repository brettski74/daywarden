"use strict";
// Runs a quiz page's script on a fake clock, with a stub DOM, audio, and fetch.
//
// Reads {html, replies, clip_ms, run_ms, steps} as JSON on stdin. `replies` maps
// each ?do= action to the list of JSON replies it gets, in order. Every clip with
// an `onended` handler ends `clip_ms` after it starts. Without `steps`, the run
// presses Start, waits for the word to finish, types an answer and presses
// Enter, then lets `run_ms` pass. `steps` replaces that with a list of
// {click: id}, {wait: ms}, {type: [id, text]}, {key: [id, key]}, and
// {snap: [id, ...], label}. A snap records whether each element is hidden,
// disabled, and focused, and its text. Prints the posts, plays, and snaps it
// saw, each with the fake time it happened. With `bodies`, each post also
// carries the JSON it sent. `calls` is a list of [name, ...args] run after the
// steps against the functions a page exposes as `window.partsOfSpeech`, each
// printed with its result.

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
    this.dataset = {};
    const classes = new Set();
    this.classList = {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
      contains: (name) => classes.has(name),
      toggle: (name, on) => ((on === undefined ? !classes.has(name) : on) ? classes.add(name) : classes.delete(name)),
    };
  }
  addEventListener(type, fn) {
    (this.listeners[type] = this.listeners[type] || []).push(fn);
  }
  dispatch(type, fields = {}) {
    const event = {
      type, target: this, repeat: false, ctrlKey: false, metaKey: false, altKey: false, shiftKey: false, ...fields,
    };
    event.preventDefault = () => {};
    for (const fn of this.listeners[type] || []) fn(event);
    if (type === "keydown") for (const fn of documentListeners[type] || []) fn(event);
  }
  click() {
    if (!this.disabled) this.dispatch("click");
  }
  focus() {
    document.activeElement = this;
  }
  blur() {
    if (document.activeElement === this) document.activeElement = null;
  }
  contains(other) {
    return other === this;
  }
  querySelectorAll() {
    return [];
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
const documentListeners = {};
const document = {
  activeElement: null,
  getElementById(id) {
    if (!elements.has(id)) {
      const element = new Element(id, id === "answer" ? "INPUT" : "DIV");
      if (id === "quiz-config") element.textContent = config;
      const tag = input.html.match(new RegExp('<[a-z]+[^>]*\\sid="' + id + '"[^>]*>'));
      if (tag) {
        element.hidden = /\shidden[\s>]/.test(tag[0]);
        element.disabled = /\sdisabled[\s>]/.test(tag[0]);
      }
      elements.set(id, element);
    }
    return elements.get(id);
  },
  querySelectorAll: () => [],
  createElement: (tag) => new Element(null, tag.toUpperCase()),
  createTextNode: (text) => ({ textContent: text }),
  documentElement: new Element(null, "HTML"),
  addEventListener(type, fn) {
    (documentListeners[type] = documentListeners[type] || []).push(fn);
  },
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

async function fetch(url, options) {
  const action = new URL(url, "http://page").searchParams.get("do");
  const event = { at: now, kind: "post", what: action };
  if (input.bodies) event.body = options && options.body ? JSON.parse(options.body) : null;
  events.push(event);
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

const window = { location: { reload: () => events.push({ at: now, kind: "reload" }) } };

vm.runInNewContext(code, {
  document,
  window,
  performance: { now: () => now },
  requestAnimationFrame: () => 0,
  setTimeout,
  clearTimeout,
  Audio,
  fetch,
  URL,
  console,
});

const steps = input.steps || [
  { click: "start-button" },
  { wait: input.clip_ms },
  { type: ["answer", "answer"] },
  { key: ["answer", "Enter"] },
  { wait: input.run_ms },
];

function snap(ids) {
  const found = {};
  for (const id of ids) {
    const element = document.getElementById(id);
    found[id] = {
      hidden: element.hidden,
      disabled: element.disabled,
      focused: document.activeElement === element,
      text: element.textContent,
    };
  }
  return found;
}

(async () => {
  await settle();
  for (const step of steps) {
    if (step.click) document.getElementById(step.click).click();
    if (step.type) document.getElementById(step.type[0]).value = step.type[1];
    if (step.key) document.getElementById(step.key[0]).dispatch("keydown", { key: step.key[1] });
    if (step.snap) events.push({ at: now, kind: "snap", what: step.label || "", elements: snap(step.snap) });
    await settle();
    if (step.wait) await advance(step.wait);
  }
  for (const [name, ...args] of input.calls || []) {
    events.push({ kind: "call", what: name, result: window.partsOfSpeech[name](...args) });
  }
  process.stdout.write(JSON.stringify(events));
})();
