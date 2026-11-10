// Sorting the words of a sentence into the rows of a table by dragging them.
//
// The one piece of code the child's parts of speech page and the parent
// portal share. The portal imports it as a module. The child's page inlines
// it into its own script with each line-leading "export " taken out, so
// every export stays at the start of a line and nothing else here may start
// a line with that word.
//
// It holds the sorting model and the drag itself: the press-and-move
// threshold, the copy that follows the pointer, pointer capture, the drop
// target under the pointer, the flight back, highlighting a word with its
// twin, and blocking the browser's text selection and drag image. Each page
// says which elements can be picked up, which take a drop, what a drop does,
// and how long a flight takes.
//
// It marks elements only with data- attributes, which a page styles with its
// own palette: data-held on a word being dragged, data-lit on a word and its
// twin under the pointer, data-over on the drop target under the pointer,
// data-dragging on the body during a drag, and data-ghost and data-flying on
// the copy. React replaces an element's whole class list when it renders, but
// leaves attributes it does not manage alone.

export const sortModel = {
  empty(parts) {
    const cells = {};
    for (const part of parts) cells[part] = [];
    return cells;
  },
  partOf(cells, id) {
    for (const part of Object.keys(cells)) if (cells[part].includes(id)) return part;
    return null;
  },
  place(cells, id, part) {
    if (sortModel.partOf(cells, id) === part) return cells;
    const next = sortModel.remove(cells, id);
    next[part] = [...next[part], id];
    return next;
  },
  remove(cells, id) {
    const next = {};
    for (const part of Object.keys(cells)) next[part] = cells[part].filter((other) => other !== id);
    return next;
  },
  count(cells) {
    return Object.values(cells).reduce((sum, ids) => sum + ids.length, 0);
  },
  // What dropping a word from its row (null for the sentence) on a row (null for anywhere else) does.
  drop(origin, target) {
    if (target === null) return origin === null ? "back" : "unsort";
    return target === origin ? "stay" : "place";
  },
};

export const PRESS_THRESHOLD = 4;

// Start sorting with the mouse on the given elements. Returns the controls a page needs while it runs.
//
// options.sources        elements a press can start on, and where hovering lights a word and its twin
// options.flightMs       how long the copy takes to fly back
// options.canPress()     whether a press may start now
// options.pickable(t)    the word element a press on t picks up, or null
// options.originOf(id)   the row the word is in, or null for the sentence
// options.sentenceWord(id), options.cellWord(id)   the word in the sentence, and in its cell or null
// options.targetAt(e, id)  the row key a drop on element e lands in, and the element to mark, as {key, element}, or null
// options.hoverable(t)   the sorted word element hovering t lights, or null
// options.hoverOn()      whether hovering lights it now
// options.ghost(copy, source)  dress the copy that follows the pointer
// options.onPlace(id, key), options.onUnsort(id)   change the table and show it
// options.onBusy()       a drag started, or a flight started
// options.onArrive(id)   a flight ended
// options.noSelect(t), options.noDragImage(t)   whether to block text selection, or the browser's drag, starting at t
export function wordSort(options) {
  const yes = () => true;
  const no = () => null;
  const canPress = options.canPress || yes;
  const hoverable = options.hoverable || no;
  const hoverOn = options.hoverOn || yes;
  const noSelect = options.noSelect || yes;
  const noDragImage = options.noDragImage || yes;
  const notify = (name, ...args) => {
    if (options[name]) options[name](...args);
  };
  let press = null;
  let drag = null;
  let flight = null;
  let marked = null;

  function wordOf(element) {
    return Number(element.dataset.word);
  }

  function mark(element, name, on) {
    if (!element) return;
    if (on) element.dataset[name] = "";
    else delete element.dataset[name];
  }

  function lit(id, on) {
    mark(options.sentenceWord(id), "lit", on);
    mark(options.cellWord(id), "lit", on);
  }

  function clearShading(id) {
    lit(id, false);
    mark(options.sentenceWord(id), "held", false);
    mark(options.cellWord(id), "held", false);
  }

  function under(x, y) {
    if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) return null;
    return document.elementFromPoint(x, y);
  }

  function hover(target) {
    const element = target ? target.element : null;
    if (marked && marked !== element) mark(marked, "over", false);
    marked = element;
    mark(element, "over", true);
  }

  function pressed(event) {
    if (drag || flight || event.button !== 0 || !canPress(event)) return;
    const source = options.pickable(event.target);
    if (!source) return;
    event.preventDefault();
    press = { id: wordOf(source), source, x: event.clientX, y: event.clientY };
  }

  function begin(event) {
    const source = press.source;
    const box = source.getBoundingClientRect();
    const ghost = document.createElement("span");
    ghost.dataset.ghost = "";
    if (options.ghost) options.ghost(ghost, source);
    ghost.textContent = source.textContent;
    const style = getComputedStyle(source);
    Object.assign(ghost.style, {
      position: "fixed",
      zIndex: "10",
      pointerEvents: "none",
      whiteSpace: "pre",
      margin: "0",
      font: style.font,
      padding: style.padding,
      left: box.left + "px",
      top: box.top + "px",
    });
    document.body.appendChild(ghost);
    const origin = options.originOf(press.id);
    drag = { id: press.id, origin, ghost, dx: press.x - box.left, dy: press.y - box.top };
    try {
      source.setPointerCapture(event.pointerId);
    } catch (error) {}
    mark(options.sentenceWord(drag.id), "held", true);
    if (origin !== null) mark(source, "held", true);
    document.body.dataset.dragging = "";
    press = null;
    notify("onBusy");
  }

  function moved(event) {
    if (press && !drag) {
      if (Math.abs(event.clientX - press.x) + Math.abs(event.clientY - press.y) < PRESS_THRESHOLD) return;
      begin(event);
    }
    if (!drag) return;
    drag.ghost.style.left = event.clientX - drag.dx + "px";
    drag.ghost.style.top = event.clientY - drag.dy + "px";
    const found = under(event.clientX, event.clientY);
    hover(found ? options.targetAt(found, drag.id) : null);
  }

  function released(event, outside) {
    press = null;
    if (!drag) return;
    const found = outside ? null : under(event.clientX, event.clientY);
    const target = found ? options.targetAt(found, drag.id) : null;
    const { id, origin, ghost } = drag;
    drag = null;
    hover(null);
    delete document.body.dataset.dragging;
    const key = target ? target.key : null;
    const action = sortModel.drop(origin, key);
    if (action === "place") {
      ghost.remove();
      clearShading(id);
      options.onPlace(id, key);
      return;
    }
    if (action === "stay") {
      clearShading(id);
      fly(ghost, options.cellWord(id), id);
      return;
    }
    if (action === "unsort") {
      clearShading(id);
      options.onUnsort(id);
    }
    fly(ghost, options.sentenceWord(id), id);
  }

  function fly(ghost, home, id) {
    const box = home.getBoundingClientRect();
    flight = { ghost, id, timer: setTimeout(arrive, options.flightMs) };
    ghost.getBoundingClientRect();
    ghost.style.transition = "left " + options.flightMs + "ms ease-out, top " + options.flightMs + "ms ease-out";
    ghost.dataset.flying = "";
    ghost.style.left = box.left + "px";
    ghost.style.top = box.top + "px";
    notify("onBusy");
  }

  function arrive() {
    if (!flight) return;
    clearTimeout(flight.timer);
    flight.ghost.remove();
    const id = flight.id;
    mark(options.sentenceWord(id), "held", false);
    flight = null;
    notify("onArrive", id);
  }

  function cancel() {
    press = null;
    if (!drag) return;
    drag.ghost.remove();
    clearShading(drag.id);
    hover(null);
    delete document.body.dataset.dragging;
    drag = null;
  }

  function over(event) {
    if (drag || flight) return;
    const target = hoverable(event.target);
    if (target) lit(wordOf(target), hoverOn());
  }

  function out(event) {
    if (drag) return;
    const target = hoverable(event.target);
    if (target && !target.contains(event.relatedTarget)) lit(wordOf(target), false);
  }

  const up = (event) => released(event, false);
  const lost = (event) => released(event, true);
  const dragStarted = (event) => {
    if (noDragImage(event.target)) event.preventDefault();
  };
  const selecting = (event) => {
    if (noSelect(event.target)) event.preventDefault();
  };
  for (const source of options.sources) {
    source.addEventListener("pointerdown", pressed);
    source.addEventListener("pointerover", over);
    source.addEventListener("pointerout", out);
  }
  document.addEventListener("pointermove", moved);
  document.addEventListener("pointerup", up);
  document.addEventListener("pointercancel", lost);
  document.addEventListener("dragstart", dragStarted);
  document.addEventListener("selectstart", selecting);

  return {
    dragging: () => drag !== null,
    flying: () => flight !== null,
    cancel,
    arrive,
    destroy() {
      cancel();
      if (flight) {
        clearTimeout(flight.timer);
        flight.ghost.remove();
        flight = null;
      }
      for (const source of options.sources) {
        source.removeEventListener("pointerdown", pressed);
        source.removeEventListener("pointerover", over);
        source.removeEventListener("pointerout", out);
      }
      document.removeEventListener("pointermove", moved);
      document.removeEventListener("pointerup", up);
      document.removeEventListener("pointercancel", lost);
      document.removeEventListener("dragstart", dragStarted);
      document.removeEventListener("selectstart", selecting);
    },
  };
}
