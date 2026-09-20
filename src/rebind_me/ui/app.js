import {
  ACTIONS, EFFECTS, INPUT_GROUPS, MAX_CHORD_SEGMENTS, MODES, MOUSE_CODES, SCROLL_CODES,
  STATUS_STATES, TOUCHPAD_ZONE_INPUTS,
  clamp, formatSequence, hexToRgb, mappingEntryFromForm, mappingFormFromEntry,
  mappingSignature, mappingSummary, parseSequence, removeSegment, rgbToHex, setSegment, stickOffset,
} from "./model.js";

let mapping = null;
let settings = null;
let working = null;
let selected = null;

// The one capture the backend allows at a time. `recording` is the target the
// user is currently recording into; `inFlightCapture` is the open /api request
// so a new capture can wait for the old one to release the hook first.
let recording = null;
let inFlightCapture = null;

const POINTER_CODES = [...MOUSE_CODES, ...SCROLL_CODES];

// Bridge-owned inputs: shown in the mapping list as read-only, never recorded.
const FIXED_INPUTS = new Set(["mute"]);
const FIXED_SUMMARY = { mute: "hardware mic toggle" };

// Touchpad tap / click zones, edited in the Touchpad tab with the same editor
// as the mapping rows. Each one is a full mapping / action target.
const TOUCHPAD_ZONE_SET = new Set(TOUCHPAD_ZONE_INPUTS);
const TOUCHPAD_ZONE_ROWS = [
  ["touchpad_tap_left", "Touch left"],
  ["touchpad_tap_right", "Touch right"],
  ["touchpad_click_left", "Click left"],
  ["touchpad_click_right", "Click right"],
];

const message = document.getElementById("message");
const VB = 128;
const ART_SCALE = 0.16;

function showMessage(text, kind) {
  message.textContent = text;
  message.className = `message ${kind || ""}`;
  message.hidden = false;
  if (kind === "ok") setTimeout(() => { message.hidden = true; }, 2500);
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (ch) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]
  ));
}

async function api(path, method = "GET", body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  const envelope = await response.json();
  if (!envelope.ok) {
    const error = envelope.error || {};
    throw new Error(`${error.code || "ERROR"}: ${error.message || ""}`);
  }
  return envelope.data;
}

function options(values, selected_value) {
  return values.map((value) => `<option value="${value}"${value === selected_value ? " selected" : ""}>${value || "(none)"}</option>`).join("");
}

function pointerOptions(selected_value) {
  const group = (label, values) =>
    `<optgroup label="${label}">${options(values, selected_value)}</optgroup>`;
  return group("Mouse", MOUSE_CODES) + group("Scroll", SCROLL_CODES);
}

const pct = (value) => `${((value / VB) * 100).toFixed(3)}%`;

// SVG path index -> input name, from the measured path bounding boxes.
const PATH_INPUT = {
  0: "touchpad",
  2: "triangle",
  3: "cross",
  4: "square",
  5: "r3",
  6: "l3",
  7: "l3",
  8: "r3",
  9: "r1",
  10: "l1",
  11: "circle",
  12: "mute",
  13: "dpad_down",
  14: "dpad_up",
  15: "dpad_left",
  16: "dpad_right",
  17: "options",
  18: "create",
  19: "ps",
  20: "l2",
  21: "r2",
};

// Thin glyphs get an invisible thicker stroke so they are easy to hit.
const THIN_INPUTS = new Set(["ps", "mute", "create", "options"]);

// The artwork has no stick-direction glyphs, so a direction is resolved from
// where the pointer sits inside the stick's own footprint. Keeping this inside
// the stick radius means nearby buttons (PS between the sticks, mute below)
// can never be swallowed by stick proximity.
const STICK_ZONES = [
  {
    cx: 45.5, cy: 64.5, radius: 8,
    up: "left_stick_up", down: "left_stick_down",
    left: "left_stick_left", right: "left_stick_right",
  },
  {
    cx: 82.5, cy: 64.5, radius: 8,
    up: "right_stick_up", down: "right_stick_down",
    left: "right_stick_left", right: "right_stick_right",
  },
];

// Inside this radius the pointer means the stick press, not a direction.
const STICK_DEADZONE = 3;

const SVG_NS = "http://www.w3.org/2000/svg";

let svgMarkup = "";

function box(cx, cy, w, h) {
  return `left:${pct(cx - w / 2)};top:${pct(cy - h / 2)};width:${pct(w)};height:${pct(h)}`;
}

function selectInput(input, options = {}) {
  if (FIXED_INPUTS.has(input)) return;
  // A glyph press re-records rather than collapses, even when the input is
  // already selected; only a list row toggles selection off.
  if (selected === input && !options.record) {
    clearSelection();
    return;
  }
  selected = input;
  if (TOUCHPAD_ZONE_SET.has(input)) {
    activateTab("touchpad");
    refreshMap();
    renderEditor();
    return;
  }
  // Picking a controller glyph from any tab brings the Mappings tab forward so
  // the row being edited (and its recorder) is actually on screen.
  activateTab("mappings");
  stickLockedInput = ZONE_DIR[input] ? input : null;
  renderSticks();
  refreshMap();
  renderEditor();
  const node = document.querySelector(`#mappings .map-item[data-input="${input}"]`);
  if (node) node.scrollIntoView({ behavior: "smooth", block: "nearest" });
  // Clicking a controller glyph means "assign this button now": open its
  // editor and start capturing straight away. Cancel leaves the old mapping.
  if (options.record && working && working.enabled) {
    startRecording({ input, index: 0, replaceAll: true });
  }
}

function clearSelection() {
  selected = null;
  stickLockedInput = null;
  renderSticks();
  refreshMap();
  renderEditor();
}

// Stop any in-flight capture so it resolves as cancelled and the backend
// releases the keyboard hook before the next capture opens.
function abortCapture() {
  return fetch("/api/key-capture/cancel", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  }).catch(() => {});
}

function cancelRecording() {
  if (!recording) return;
  recording = null;
  renderRecorder();
  renderChords();
  abortCapture();
}

// Open the keyboard hook for one capture and apply the keys to `target`.
// Only one capture may run, so a new one cancels and waits for the old request
// to finish before asking the backend to start listening.
async function startRecording(target) {
  const myRecording = {
    input: target.input,
    index: target.index,
    replaceAll: !!target.replaceAll,
  };
  recording = myRecording;
  renderRecorder();
  renderChords();

  await abortCapture();
  if (inFlightCapture) {
    try { await inFlightCapture; } catch (error) { /* superseded */ }
  }
  if (recording !== myRecording) return;

  try {
    const request = api("/api/key-capture", "POST");
    inFlightCapture = request;
    let data;
    try {
      data = await request;
    } finally {
      if (inFlightCapture === request) inFlightCapture = null;
    }
    if (recording !== myRecording) return;
    if (data.cancelled) {
      showMessage("Capture cancelled", "error");
    } else if (data.keys && data.keys.length) {
      applyCaptured(myRecording, data.keys);
      showMessage(`Captured ${data.keys.join(" + ")}`, "ok");
    }
  } catch (error) {
    if (recording === myRecording) showMessage(error.message, "error");
  } finally {
    if (recording === myRecording) {
      recording = null;
      renderRecorder();
      renderChords();
    }
  }
}

// Fold a captured chord into the mapping. A glyph click replaces the whole
// sequence with this one step; "Add key" and per-step re-record keep the rest.
function applyCaptured(rec, keys) {
  const input = rec.input;
  const existing = working.mappings[input];
  const previousMode = existing && existing.sequence ? existing.mode || "single" : "single";
  const base = rec.replaceAll ? [] : (existing && existing.sequence) || [];
  const sequence = setSegment(base, rec.index, keys);
  const mode = sequence.length > 1 ? "single" : previousMode;
  delete working.actions[input];
  working.mappings[input] = { mode, sequence };
  if (selected === input) renderEditor();
  refreshMap();
  scheduleMappingSave();
}

function renderRecorder() {
  const root = document.getElementById("recorder");
  if (!root) return;
  root.hidden = !recording;
  if (!recording) return;
  const text = document.getElementById("recorder-text");
  if (text) {
    text.textContent = recording.replaceAll
      ? `Recording ${recording.input} — hold the keys together`
      : `Add key for ${recording.input} — hold the keys together`;
  }
}

function refreshMap() {
  document.querySelectorAll("[data-input]").forEach((node) => {
    const input = node.dataset.input;
    const mapped = working.mappings[input] || working.actions[input];
    node.classList.toggle("mapped", !!mapped);
    node.classList.toggle("selected", input === selected);
  });
  refreshSummaries();
  const tpSelected = selected === "touchpad";
  document.querySelectorAll('[data-input="touchpad_left"],[data-input="touchpad_right"]').forEach((node) => {
    node.classList.toggle("selected", tpSelected);
  });
}

// The right pane lists every input, grouped; each row shows what it resolves to.
// A fixed input (the mic button) is read-only: no editor, never recorded.
function mapItemMarkup(input, label = input) {
  if (FIXED_INPUTS.has(input)) {
    return `<div class="map-item fixed" data-input="${input}">
      <div class="map-head">
        <span class="map-name">${label}</span>
        <span class="map-summary" data-summary></span>
      </div>
    </div>`;
  }
  return `<div class="map-item" data-input="${input}">
      <button type="button" class="map-head">
        <span class="map-name">${label}</span>
        <span class="map-summary" data-summary></span>
      </button>
      <div class="editor hidden" data-editor></div>
    </div>`;
}

// Wire every mapping row in ``root`` to selection and controller preview.
function bindMapItems(root) {
  root.querySelectorAll("button.map-head").forEach((node) => {
    const input = node.closest(".map-item").dataset.input;
    node.addEventListener("click", () => selectInput(input));
    node.addEventListener("mouseenter", () => { hoverPath(input, true); hoverStick(input, true); });
    node.addEventListener("mouseleave", () => { hoverPath(input, false); hoverStick(input, false); });
  });
}

function renderMappings() {
  const root = document.getElementById("mappings");
  root.innerHTML = INPUT_GROUPS.map(([title, inputs]) => `
    <section class="map-group" data-group="${title}">
      <div class="map-group-title">${title}</div>
      <div class="map-items">${inputs.map((input) => mapItemMarkup(input)).join("")}</div>
    </section>`).join("");
  bindMapItems(root);
  refreshSummaries();
}

function refreshSummaries() {
  document.querySelectorAll("#mappings .map-item, #touchpad .map-item").forEach((node) => {
    const input = node.dataset.input;
    node.querySelector("[data-summary]").textContent = FIXED_INPUTS.has(input)
      ? FIXED_SUMMARY[input]
      : mappingSummary(working.mappings[input], working.actions[input]);
  });
}

function currentEditor() {
  if (!selected) return null;
  return document.querySelector(
    `#mappings .map-item[data-input="${selected}"] [data-editor], ` +
    `#touchpad .map-item[data-input="${selected}"] [data-editor]`,
  );
}

function hoverPath(input, on) {
  document.querySelectorAll(`.pad-svg svg path[data-input="${input}"]`).forEach((path) => {
    path.classList.toggle("hover", on);
  });
  document.querySelectorAll(`.dir[data-input="${input}"]`).forEach((dir) => {
    dir.classList.toggle("hover", on);
  });
}

// Transparent shape matching each glyph's footprint, so the interior (the hole
// of the outline) is clickable while still using the SVG geometry.
function addHitbox(svg, element, input) {
  if (input === "touchpad") {
    buildTouchpadHalves(svg, element);
    return;
  }
  const bounds = element.getBBox();
  const shape = document.createElementNS(SVG_NS, "ellipse");
  shape.setAttribute("cx", bounds.x + bounds.width / 2);
  shape.setAttribute("cy", bounds.y + bounds.height / 2);
  shape.setAttribute("rx", Math.max(bounds.width / 2, 1.3));
  shape.setAttribute("ry", Math.max(bounds.height / 2, 1.3));
  shape.setAttribute("class", "hitbox");
  shape.setAttribute("data-input", input);
  shape.setAttribute("fill", "transparent");
  shape.setAttribute("pointer-events", "all");
  shape.addEventListener("click", () => selectInput(input, { record: true }));
  shape.addEventListener("mouseenter", () => hoverPath(input, true));
  shape.addEventListener("mouseleave", () => hoverPath(input, false));
  const title = document.createElementNS(SVG_NS, "title");
  title.textContent = input;
  shape.appendChild(title);
  svg.appendChild(shape);
}

// One overlay traces the touchpad's own outline (so the glow never spills past
// the SVG shape) and is filled with a left/right linear gradient. The active
// side lights up and fades toward the other side; status.touchpadZone picks
// which gradient is shown.
function makeSvgEl(name, attrs) {
  const el = document.createElementNS(SVG_NS, name);
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value);
  return el;
}

function ensureTouchpadGradients(svg) {
  if (svg.querySelector("#tp-grad-left")) return;
  const defs = makeSvgEl("defs", {});
  const left = makeSvgEl("linearGradient", { id: "tp-grad-left", x1: "0", y1: "0", x2: "1", y2: "0" });
  left.appendChild(makeSvgEl("stop", { offset: "0", style: "stop-color:var(--pressed);stop-opacity:0.95" }));
  left.appendChild(makeSvgEl("stop", { offset: "0.55", style: "stop-color:var(--pressed);stop-opacity:0" }));
  const right = makeSvgEl("linearGradient", { id: "tp-grad-right", x1: "0", y1: "0", x2: "1", y2: "0" });
  right.appendChild(makeSvgEl("stop", { offset: "0.45", style: "stop-color:var(--pressed);stop-opacity:0" }));
  right.appendChild(makeSvgEl("stop", { offset: "1", style: "stop-color:var(--pressed);stop-opacity:0.95" }));
  defs.appendChild(left);
  defs.appendChild(right);
  svg.appendChild(defs);
}

function buildTouchpadHalves(svg, element) {
  ensureTouchpadGradients(svg);
  const d = element.getAttribute("d");
  // Status-driven side lighting; never a pointer target, so the whole pad can
  // share one hit area below.
  for (const [input, grad] of [["touchpad_left", "tp-grad-left"], ["touchpad_right", "tp-grad-right"]]) {
    const shape = makeSvgEl("path", { d, class: "touchpad-half", "data-input": input, fill: `url(#${grad})` });
    shape.setAttribute("pointer-events", "none");
    const title = document.createElementNS(SVG_NS, "title");
    title.textContent = input;
    shape.appendChild(title);
    svg.appendChild(shape);
  }
  // The artwork draws the pad as a hollow frame, so its blank middle would not
  // react to the pointer. Cover the whole pad footprint with one transparent
  // hit area: frame and middle then hover and click as a single input. The
  // pad's box clears every neighbouring button (the nearest is ~3 units away),
  // so it never swallows another glyph.
  const bounds = element.getBBox();
  const hit = makeSvgEl("rect", {
    x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height,
    class: "touchpad-hit", "data-input": "touchpad", fill: "transparent",
  });
  hit.setAttribute("pointer-events", "all");
  hit.addEventListener("click", () => selectInput("touchpad"));
  hit.addEventListener("mouseenter", () => element.classList.add("hover"));
  hit.addEventListener("mouseleave", () => element.classList.remove("hover"));
  const title = document.createElementNS(SVG_NS, "title");
  title.textContent = "touchpad";
  hit.appendChild(title);
  svg.appendChild(hit);
}

function tagSvg(container) {
  const svg = container.querySelector(".pad-svg svg");
  const art = svg.querySelector("g");
  const paths = [...svg.querySelectorAll("path")];
  paths.forEach((path, index) => {
    if (index === 7 || index === 8) path.classList.add("knob");
    const input = PATH_INPUT[index];
    if (!input) return;
    path.classList.add("hit");
    if (THIN_INPUTS.has(input)) path.style.strokeWidth = "31.25";
    const hint = document.createElementNS(SVG_NS, "title");
    const summary = FIXED_INPUTS.has(input)
      ? FIXED_SUMMARY[input]
      : mappingSummary(working.mappings[input], working.actions[input]);
    hint.textContent = summary === "-" ? input : `${input}: ${summary}`;
    path.appendChild(hint);
    path.addEventListener("click", () => selectInput(input, { record: true }));
    if (input === "touchpad") return;
    path.dataset.input = input;
  });
  const base = paths.filter((path, index) => !PATH_INPUT[index]);
  const bumpers = [paths[9], paths[10]];
  const rest = paths.filter((path, index) => PATH_INPUT[index] && !bumpers.includes(path));
  const ordered = [...bumpers, ...base, ...rest];
  ordered.forEach((path) => art.appendChild(path));
  ordered.forEach((path) => {
    const input = path.dataset.input;
    if (input) addHitbox(art, path, input);
  });
  const touchpadPath = paths.find((path, index) => PATH_INPUT[index] === "touchpad");
  if (touchpadPath) addHitbox(art, touchpadPath, "touchpad");
}

const STICK_MAX = 1.6;
const ZONE_DIR = {
  left_stick_up:    { stick: "l3", x: 0, y: -1 },
  left_stick_down:  { stick: "l3", x: 0, y: 1 },
  left_stick_left:  { stick: "l3", x: -1, y: 0 },
  left_stick_right: { stick: "l3", x: 1, y: 0 },
  right_stick_up:   { stick: "r3", x: 0, y: -1 },
  right_stick_down: { stick: "r3", x: 0, y: 1 },
  right_stick_left: { stick: "r3", x: -1, y: 0 },
  right_stick_right:{ stick: "r3", x: 1, y: 0 },
};

// Snapped stick preview state. `stickHoverInput` is the direction zone under
// the cursor (transient); `stickLockedInput` is the selected stick-direction
// mapping (persists). The locked input is shown whenever nothing is hovered,
// so a selected mapping keeps its knob held in place between polls.
let stickHoverInput = null;
let stickLockedInput = null;
let stickListPreview = null;
let padWrap = null;
let lastAxes = { leftX: 0, leftY: 0, rightX: 0, rightY: 0 };

function currentStickSnap() {
  return stickHoverInput || stickLockedInput || stickListPreview;
}

// Which stick-direction (if any) a point inside the pad maps to. Returns null
// when the point is outside every stick or within its centre deadzone.
function stickDirectionAt(x, y) {
  for (const zone of STICK_ZONES) {
    const dx = x - zone.cx;
    const dy = y - zone.cy;
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist > zone.radius || dist < STICK_DEADZONE) continue;
    if (Math.abs(dx) >= Math.abs(dy)) return dx >= 0 ? zone.right : zone.left;
    return dy >= 0 ? zone.down : zone.up;
  }
  return null;
}

// Redraw both stick knobs, letting a snapped input override that stick's real
// axis so the preview holds instead of snapping back to centre on the next poll.
function renderSticks() {
  const snap = currentStickSnap();
  const snappedStick = snap ? ZONE_DIR[snap].stick : null;
  const leftInner = document.querySelector('.pad-svg svg path.knob[data-input="l3"]');
  const rightInner = document.querySelector('.pad-svg svg path.knob[data-input="r3"]');
  if (leftInner) {
    if (snappedStick === "l3") {
      const z = ZONE_DIR[snap];
      leftInner.setAttribute("transform", `translate(${(z.x * STICK_MAX) / ART_SCALE} ${(z.y * STICK_MAX) / ART_SCALE})`);
      leftInner.classList.add("snapped");
    } else {
      const [x, y] = stickOffset(lastAxes.leftX || 0, lastAxes.leftY || 0);
      leftInner.setAttribute("transform", `translate(${x / ART_SCALE} ${y / ART_SCALE})`);
      leftInner.classList.remove("snapped");
    }
  }
  if (rightInner) {
    if (snappedStick === "r3") {
      const z = ZONE_DIR[snap];
      rightInner.setAttribute("transform", `translate(${(z.x * STICK_MAX) / ART_SCALE} ${(z.y * STICK_MAX) / ART_SCALE})`);
      rightInner.classList.add("snapped");
    } else {
      const [x, y] = stickOffset(lastAxes.rightX || 0, lastAxes.rightY || 0);
      rightInner.setAttribute("transform", `translate(${x / ART_SCALE} ${y / ART_SCALE})`);
      rightInner.classList.remove("snapped");
    }
  }
}

function initStickSnap(wrap) {
  padWrap = wrap;
  const svg = wrap.querySelector(".pad-svg svg");

  function toSVGCoords(e) {
    const pt = svg.createSVGPoint();
    pt.x = e.clientX;
    pt.y = e.clientY;
    const ctm = svg.getScreenCTM();
    if (!ctm) return null;
    return pt.matrixTransform(ctm.inverse());
  }

  wrap.addEventListener("mousemove", (e) => {
    const p = toSVGCoords(e);
    stickHoverInput = p ? stickDirectionAt(p.x, p.y) : null;
    renderSticks();
  });

  wrap.addEventListener("mouseleave", () => {
    stickHoverInput = null;
    renderSticks();
  });

  wrap.addEventListener("click", () => {
    // Only a hovered direction selects; the locked preview is for holding the
    // knob between polls and must never hijack a click on another glyph.
    if (stickHoverInput) selectInput(stickHoverInput, { record: true });
  });
}

function renderController() {
  const container = document.getElementById("controller");
  container.innerHTML = `<div class="pad-wrap"><div class="pad-svg">${svgMarkup}</div></div>`;
  const wrap = container.querySelector(".pad-wrap");
  tagSvg(container);
  initStickSnap(wrap);
  refreshMap();
}

// Grey out and disable the mapping UI while the controller toggle is off.
function applyEnabledState() {
  const on = !!(working && working.enabled);
  for (const node of [
    document.getElementById("controller"),
    document.getElementById("panel-mappings"),
    document.getElementById("tp-mappings"),
  ]) {
    if (!node) continue;
    node.classList.toggle("is-disabled", !on);
    node.querySelectorAll("input, select, textarea, button").forEach((el) => { el.disabled = !on; });
  }
}

// Keep the settings card level with the controller card; each tab's panel
// scrolls internally when it has more content than the controller is tall.
function syncPanelHeights() {
  const left = document.querySelector(".pane-left .card");
  const card = document.getElementById("settings-card");
  if (!left || !card) return;
  if (window.matchMedia("(max-width: 880px)").matches) {
    card.style.height = "";
    return;
  }
  card.style.height = `${left.offsetHeight}px`;
}

function activateTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.tab === name;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", active ? "true" : "false");
    tab.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("hidden", panel.dataset.panel !== name);
  });
  syncPanelHeights();
}

function updateSticks(axes) {
  lastAxes = axes || {};
  renderSticks();
}

// Hovering a stick-direction row in the mapping list previews that direction on
// the controller (mapping -> gui). `ZONE_DIR` only has the eight directions, so
// anything else is ignored.
function hoverStick(input, on) {
  if (!ZONE_DIR[input]) return;
  stickListPreview = on ? input : null;
  renderSticks();
}

function renderEditor() {
  document.getElementById("editor-name").textContent =
    selected && !TOUCHPAD_ZONE_SET.has(selected) ? selected : "-";
  document.querySelectorAll("#mappings .map-item, #touchpad .map-item").forEach((node) => {
    const isSel = node.dataset.input === selected;
    node.classList.toggle("expanded", isSel);
    const editorNode = node.querySelector("[data-editor]");
    if (editorNode) editorNode.classList.toggle("hidden", !isSel);
  });
  const editor = currentEditor();
  if (!editor) return;

  const action = working.actions[selected];
  const entry = working.mappings[selected];
  let form;
  if (action) {
    form = { kind: "action", mode: "single", sequenceText: "", mouse: MOUSE_CODES[0], scroll: SCROLL_CODES[0], repeatDelay: 300, repeatInterval: 50, toggleInitial: "off" };
    form.action = action.action;
    form.process = (action.params || {}).process || "";
  } else {
    form = mappingFormFromEntry(entry);
    if (form.kind === "none") form.kind = "sequence";
    if (form.kind === "scroll") { form.kind = "mouse"; form.pointer = entry.scroll; }
    form.action = ACTIONS[0];
    form.process = "";
  }
  if (!form.pointer) form.pointer = form.mouse || MOUSE_CODES[0];

  editor.innerHTML = `
    <div class="line">
      <label>Type <select id="ed-type" name="type" data-role="type">
        <option value="sequence"${form.kind === "sequence" ? " selected" : ""}>keys</option>
        <option value="mouse"${form.kind === "mouse" ? " selected" : ""}>mouse</option>
        <option value="action"${form.kind === "action" ? " selected" : ""}>action</option>
      </select></label>
      <label>Mode <select id="ed-mode" name="mode" data-role="mode">${options(MODES, form.mode)}</select></label>
      <span data-role="toggle-wrap" class="inline">Initial
        <select id="ed-toggleInitial" name="toggleInitial" data-role="toggleInitial"><option value="off"${form.toggleInitial === "off" ? " selected" : ""}>off</option><option value="on"${form.toggleInitial === "on" ? " selected" : ""}>on</option></select>
      </span>
    </div>
    <div data-role="seq-wrap">
      <div class="chords" data-role="chords"></div>
      <div class="line">
        <button type="button" id="add-key" class="secondary">+ Add key</button>
        <span class="sub">A step is whatever you hold together; Add key chains one more step (max 2).</span>
      </div>
      <label class="sr-only" for="ed-sequence">Key sequence</label>
      <textarea id="ed-sequence" name="sequence" data-role="sequence" class="hidden">${form.sequenceText}</textarea>
    </div>
    <div class="line" data-role="mouse-wrap"><label>Mouse / scroll <select id="ed-pointer" name="pointer" data-role="pointer">${pointerOptions(form.pointer)}</select></label></div>
    <div class="line" data-role="action-wrap">
      <label>Action <select id="ed-action" name="action" data-role="action">${options(ACTIONS, form.action)}</select></label>
      <label>Process <input id="ed-process" name="process" data-role="process" placeholder="process.exe" value="${form.process}" /></label>
    </div>
    <div class="line" data-role="repeat-wrap">
      <label>Delay ms <input id="ed-repeatDelay" name="repeatDelay" type="number" min="10" max="2000" data-role="repeatDelay" value="${form.repeatDelay}" /></label>
      <label>Interval ms <input id="ed-repeatInterval" name="repeatInterval" type="number" min="10" max="2000" data-role="repeatInterval" value="${form.repeatInterval}" /></label>
    </div>
    <div class="line"><button type="button" id="clear-seq" class="secondary">Clear mapping</button></div>`;

  editor.querySelector('[data-role="type"]').addEventListener("change", (event) => {
    // Mouse and action do not record keys, so choosing either must close the
    // keyboard hook: otherwise a captured chord would overwrite the new type.
    if (event.target.value !== "sequence") cancelRecording();
    syncEditor();
    applyEditor();
  });
  editor.querySelector('[data-role="mode"]').addEventListener("change", () => { syncEditor(); applyEditor(); });
    editor.querySelector('[data-role="toggleInitial"]').addEventListener("change", applyEditor);
    editor.querySelector('[data-role="pointer"]').addEventListener("change", applyEditor);
    editor.querySelector('[data-role="action"]').addEventListener("change", () => { syncEditor(); applyEditor(); });
    editor.querySelector('[data-role="process"]').addEventListener("input", applyEditor);
    editor.querySelector('[data-role="repeatDelay"]').addEventListener("input", applyEditor);
    editor.querySelector('[data-role="repeatInterval"]').addEventListener("input", applyEditor);
    editor.querySelector("#clear-seq").addEventListener("click", () => {
        const input = selected;
        cancelRecording();
        delete working.mappings[input];
        delete working.actions[input];
        refreshMap();
        renderEditor();
        scheduleMappingSave();
        showMessage(`${input} cleared`, "ok");
    });
    editor.querySelector("#add-key").addEventListener("click", () => {
        if (recording) return;
        const chords = getChords(editor);
        if (chords.length >= MAX_CHORD_SEGMENTS) return;
        startRecording({ input: selected, index: chords.length });
    });
  syncEditor();
  renderChords();
}

function getChords(editor = currentEditor()) {
  if (!editor) return [];
  const area = editor.querySelector('[data-role="sequence"]');
  return area ? parseSequence(area.value) : [];
}

// Write a sequence back into the hidden field, persist it and redraw.
function commitChords(editor, chords) {
  const area = editor.querySelector('[data-role="sequence"]');
  if (!area) return;
  area.value = formatSequence(chords);
  applyEditor();
  syncEditor();
  renderChords();
}

function renderChords() {
  const editor = currentEditor();
  if (!editor) return;
  const wrap = editor.querySelector('[data-role="chords"]');
  if (!wrap) return;
  const chords = getChords(editor);
  const addKey = editor.querySelector("#add-key");
  if (addKey) addKey.disabled = !!recording || chords.length >= MAX_CHORD_SEGMENTS;
  const target = recording && recording.input === selected ? recording.index : -1;

  if (chords.length === 0) {
    wrap.innerHTML = recording
      ? `<div class="chord recording"><span class="chord-empty">Listening for keys…</span></div>`
      : `<div class="chord-empty sub">No keys yet — click the button and press keys, or use Add key.</div>`;
    return;
  }

  wrap.innerHTML = chords.map((segment, index) => {
    const chip = (code) => `<span class="key-chip">${code}</span>`;
    const listening = target === index;
    return `<div class="chord${listening ? " recording" : ""}" data-index="${index}">
      <div class="chord-keys">${segment.map(chip).join("")}</div>
      <div class="chord-actions">
        <button type="button" class="ghost" data-act="record" data-index="${index}"${recording ? " disabled" : ""}>${listening ? "Listening…" : "Re-record"}</button>
        <button type="button" class="ghost danger" data-act="remove" data-index="${index}"${recording ? " disabled" : ""}>Remove</button>
      </div>
    </div>`;
  }).join("");

  wrap.querySelectorAll('[data-act="record"]').forEach((button) => {
    button.addEventListener("click", () => {
      if (recording) return;
      startRecording({ input: selected, index: Number(button.dataset.index) });
    });
  });
  wrap.querySelectorAll('[data-act="remove"]').forEach((button) => {
    button.addEventListener("click", () => {
      if (recording) return;
      commitChords(editor, removeSegment(getChords(editor), Number(button.dataset.index)));
    });
  });
}

function syncEditor() {
  const editor = currentEditor();
  if (!editor) return;
  const type = editor.querySelector('[data-role="type"]').value;
  const modeSelect = editor.querySelector('[data-role="mode"]');
  const multi = type === "sequence" && getChords(editor).length > 1;
  if (multi) modeSelect.value = "single";
  const mode = modeSelect.value;
  const show = (selector, visible) => { const node = editor.querySelector(selector); if (node) node.classList.toggle("hidden", !visible); };
  show('[data-role="seq-wrap"]', type === "sequence");
  show('[data-role="mouse-wrap"]', type === "mouse");
  show('[data-role="action-wrap"]', type === "action");
  show('[data-role="repeat-wrap"]', type === "sequence" && mode === "repeat" && !multi);
  show('[data-role="toggle-wrap"]', mode === "toggle" && !multi);
  modeSelect.disabled = type === "action" || multi;
}

function applyEditor() {
  const editor = currentEditor();
  if (!selected || !editor) return;
  const type = editor.querySelector('[data-role="type"]').value;
  delete working.mappings[selected];
  delete working.actions[selected];
  if (type === "action") {
    const action = editor.querySelector('[data-role="action"]').value;
    const entry = { action };
    if (action === "switch-to-app") entry.params = { process: editor.querySelector('[data-role="process"]').value.trim() };
    working.actions[selected] = entry;
  } else if (type === "mouse") {
    const mode = editor.querySelector('[data-role="mode"]').value;
    const pointer = editor.querySelector('[data-role="pointer"]').value;
    working.mappings[selected] = SCROLL_CODES.includes(pointer)
      ? { mode, scroll: pointer }
      : { mode, mouse: pointer };
  } else if (type === "sequence") {
    const modeSelect = editor.querySelector('[data-role="mode"]');
    if (getChords(editor).length > 1) modeSelect.value = "single";
    const result = mappingEntryFromForm({
      kind: "sequence",
      mode: modeSelect.value,
      sequenceText: editor.querySelector('[data-role="sequence"]').value,
      repeatDelay: Number(editor.querySelector('[data-role="repeatDelay"]').value),
      repeatInterval: Number(editor.querySelector('[data-role="repeatInterval"]').value),
      toggleInitial: editor.querySelector('[data-role="toggleInitial"]').value,
    });
    if (result.entry) working.mappings[selected] = result.entry;
  }
  refreshMap();
  scheduleMappingSave();
}

// -- auto-save ---------------------------------------------------------
let mappingSaveTimer = null;
let settingsSaveTimer = null;
let mappingSaving = false;
let settingsSaving = false;
let savedFadeTimer = null;

function setSaveState(state) {
  const node = document.getElementById("save-state");
  if (!node) return;
  node.dataset.state = state;
  node.textContent = state === "saving" ? "Saving…" : state === "saved" ? "Saved" : state === "error" ? "Save failed" : "";
}

function maybeSaved() {
  if (mappingSaveTimer || settingsSaveTimer || mappingSaving || settingsSaving) return;
  setSaveState("saved");
  clearTimeout(savedFadeTimer);
  savedFadeTimer = setTimeout(() => setSaveState("idle"), 1500);
}

function scheduleMappingSave() {
  setSaveState("saving");
  // The live mapping no longer matches the applied preset the moment it is
  // edited; update the preset dropdown right away.
  renderPresetSelect();
  clearTimeout(mappingSaveTimer);
  mappingSaveTimer = setTimeout(async () => {
    mappingSaveTimer = null;
    if (mappingSaving) { scheduleMappingSave(); return; }
    mappingSaving = true;
    let ok = true;
    try {
      await persistMapping();
    } catch (error) {
      ok = false;
      setSaveState("error");
      showMessage(error.message, "error");
    } finally {
      mappingSaving = false;
    }
    if (ok) maybeSaved();
  }, 400);
}

function scheduleSettingsSave() {
  setSaveState("saving");
  clearTimeout(settingsSaveTimer);
  settingsSaveTimer = setTimeout(async () => {
    settingsSaveTimer = null;
    if (settingsSaving) { scheduleSettingsSave(); return; }
    settingsSaving = true;
    let ok = true;
    try {
      await persistSettings();
    } catch (error) {
      ok = false;
      setSaveState("error");
      showMessage(error.message, "error");
    } finally {
      settingsSaving = false;
    }
    if (ok) maybeSaved();
  }, 400);
}

async function persistMapping() {
  const saved = await api("/api/mapping", "PUT", {
    version: working.version,
    enabled: working.enabled,
    mappings: working.mappings,
    actions: working.actions,
    touchpad: working.touchpad,
    baseVersion: mapping.baseVersion,
  });
  mapping = saved;
  working.version = saved.version;
  working.baseVersion = saved.baseVersion;
}

async function persistSettings() {
  const documentBody = { ...settings };
  delete documentBody.baseVersion;
  const saved = await api("/api/settings", "PUT", { ...documentBody, baseVersion: settings.baseVersion });
  settings.baseVersion = saved.baseVersion;
}

// -- touchpad ----------------------------------------------------------
// Mouse control and sensitivity are touchpad hardware settings; tap and click
// are full mapping targets edited with the same editor as the mapping rows.
function renderTouchpad() {
  const tp = working.touchpad;
  const root = document.getElementById("touchpad");
  root.innerHTML = `
    <div id="tp-basic">
      <div class="row"><span class="name" id="tp-mouseControl-label">Mouse control</span><label class="switch"><input type="checkbox" id="tp-mouseControl" name="mouseControl" data-role="mouseControl"${tp.mouseControl ? " checked" : ""} /><span class="switch-ui" aria-hidden="true"></span></label><span></span><span></span></div>
      <div id="tp-dependent">
        <div class="row"><span class="name" id="tp-sensitivity-label">Sensitivity</span><input type="number" id="tp-sensitivity" name="sensitivity" step="0.1" min="0.1" max="5" data-role="sensitivity" value="${tp.sensitivity}" /><span></span><span></span></div>
      </div>
    </div>
    <div class="sub">Touch and click map like any button — click a row to set keys, mouse, actions or a chord.</div>
    <div id="tp-mappings">
      <section class="map-group">
        <div class="map-items">${TOUCHPAD_ZONE_ROWS.map(([input, label]) => mapItemMarkup(input, label)).join("")}</div>
      </section>
    </div>`;
  bindAutoSave(document.getElementById("tp-basic"), () => {
    readTouchpad();
    applyTouchpadState();
    scheduleMappingSave();
  });
  bindMapItems(root);
  applyTouchpadState();
  applyEnabledState();
  refreshMap();
  renderEditor();
}

// Grey out and disable the settings that only apply when mouse control is on.
function applyTouchpadState() {
  const dep = document.getElementById("tp-dependent");
  if (!dep || !working.touchpad) return;
  const on = !!working.touchpad.mouseControl;
  dep.classList.toggle("is-disabled", !on);
  dep.querySelectorAll("input, select").forEach((el) => { el.disabled = !on; });
}

function readTouchpad() {
  const root = document.getElementById("touchpad");
  working.touchpad = {
    mouseControl: root.querySelector('[data-role="mouseControl"]').checked,
    sensitivity: Number(root.querySelector('[data-role="sensitivity"]').value),
  };
}

// -- presets -----------------------------------------------------------
// A preset is a named snapshot of the mapping document (enabled, mappings,
// actions, touchpad). The dropdown reflects the live mapping: it shows a
// preset only while the mapping still matches it, otherwise "(modified)".
// "New preset" asks the user for a name before saving the current mapping.
let presetNames = new Set();
let presetData = {};
let pendingSave = null;
let pendingDelete = null;

async function refreshPresets() {
  try {
    const info = await api("/api/presets");
    presetData = info.presets || {};
  } catch (error) {
    showMessage(error.message, "error");
    return;
  }
  presetNames = new Set(Object.keys(presetData));
  renderPresetSelect();
}

// The saved preset whose content equals the live mapping, else null.
function matchingPreset() {
  const signature = mappingSignature(working);
  return Object.keys(presetData).find(
    (name) => mappingSignature(presetData[name]) === signature,
  ) || null;
}

// Left pane: a quick switcher for the whole mapping set, reachable even while
// mappings are toggled off (applying a preset can turn them back on). Selecting
// a name only stages it — Apply is what swaps the live mapping.
function renderPresetSelect() {
  const select = document.getElementById("preset-select");
  if (!select) return;
  const names = Object.keys(presetData).sort((a, b) => a.localeCompare(b));
  const match = matchingPreset();

  if (names.length === 0) {
    select.innerHTML = `<option value="">(no presets)</option>`;
  } else {
    const options = names.map((name) => `<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`);
    if (!match) options.unshift(`<option value="">(modified)</option>`);
    select.innerHTML = options.join("");
  }
  select.value = match || "";
  resetPresetDelete();

  const hint = document.getElementById("preset-hint");
  if (hint) {
    // Only meaningful once a preset exists to have diverged from.
    hint.hidden = !!match || names.length === 0;
    hint.textContent = "Mapping changed since the last preset — save it as a new preset?";
  }
}

// Apply / Delete act on the staged selection, so they follow its value: while
// "(modified)" or "(no presets)" is selected there is nothing to act on.
function syncPresetButtons() {
  const select = document.getElementById("preset-select");
  const name = select ? select.value : "";
  const apply = document.getElementById("preset-apply");
  if (apply) apply.disabled = !name;
  const remove = document.getElementById("preset-delete");
  if (remove) remove.disabled = !name;
}

function resetPresetDelete() {
  pendingDelete = null;
  const button = document.getElementById("preset-delete");
  if (button) {
    button.textContent = "Delete";
    button.classList.remove("confirm");
  }
  syncPresetButtons();
}

async function deleteSelectedPreset() {
  const select = document.getElementById("preset-select");
  const name = select && select.value;
  if (!name) return;
  const button = document.getElementById("preset-delete");
  // Two-click confirmation instead of a native dialog (which blocks the page).
  if (pendingDelete !== name) {
    pendingDelete = name;
    if (button) {
      button.textContent = "Confirm?";
      button.classList.add("confirm");
    }
    showMessage(`Press Confirm? to delete '${name}'`, "error");
    return;
  }
  pendingDelete = null;
  try {
    await api("/api/presets", "POST", { action: "delete", name });
    showMessage(`Deleted '${name}'`, "ok");
    await refreshPresets();
  } catch (error) {
    showMessage(error.message, "error");
  }
}

async function applySelectedPreset() {
  const select = document.getElementById("preset-select");
  const name = select && select.value;
  if (!name) return;
  try {
    await api("/api/presets", "POST", { action: "apply", name });
    await reloadMapping();
    showMessage(`Applied '${name}'`, "ok");
    await refreshPresets();
  } catch (error) {
    showMessage(error.message, "error");
  }
}

// "New preset" reveals an inline name field (no blocking native prompt).
function showPresetCreate() {
  const row = document.getElementById("preset-create");
  const field = document.getElementById("preset-new-name");
  if (!row || !field) return;
  pendingSave = null;
  row.classList.remove("hidden");
  const save = document.getElementById("preset-new-save");
  if (save) save.textContent = "Save";
  field.focus();
  field.select();
}

function hidePresetCreate() {
  const row = document.getElementById("preset-create");
  const field = document.getElementById("preset-new-name");
  if (row) row.classList.add("hidden");
  if (field) field.value = "";
  pendingSave = null;
}

async function saveNewPreset() {
  const field = document.getElementById("preset-new-name");
  const name = (field.value || "").trim();
  if (!name) {
    showMessage("Enter a preset name", "error");
    return;
  }
  // Overwriting is a two-click action; never silent, never a blocking dialog.
  if (presetNames.has(name) && pendingSave !== name) {
    pendingSave = name;
    const save = document.getElementById("preset-new-save");
    if (save) save.textContent = "Replace?";
    showMessage(`'${name}' already exists — press Replace to overwrite it`, "error");
    return;
  }
  pendingSave = null;
  try {
    await api("/api/presets", "POST", { action: "save", name });
    showMessage(`Saved '${name}'`, "ok");
    hidePresetCreate();
    await refreshPresets();
  } catch (error) {
    showMessage(error.message, "error");
  }
}

// Pull the mapping back from the bridge (a preset apply changed it) and redraw.
async function reloadMapping() {
  mapping = await api("/api/mapping");
  working = JSON.parse(JSON.stringify(mapping));
  selected = null;
  stickLockedInput = null;
  document.getElementById("mapping-enabled").checked = !!working.enabled;
  applyEnabledState();
  renderController();
  renderMappings();
  renderTouchpad();
  renderEditor();
  renderPresetSelect();
}

// -- lighting ----------------------------------------------------------
function lightRow(state, light) {
  return `<div class="row" data-light="${state}">
    <span class="name">${state}</span>
    <input type="color" id="li-${state}-color" name="lighting-${state}-color" aria-label="${state} colour" data-role="color" value="${rgbToHex(light.color)}" />
    <select id="li-${state}-effect" name="lighting-${state}-effect" aria-label="${state} effect" data-role="effect">${options(EFFECTS, light.effect)}</select>
    <span class="inline">speed <input type="number" id="li-${state}-speed" name="lighting-${state}-speed" aria-label="${state} speed" min="1" max="5" data-role="speed" value="${light.speed}" /></span>
  </div>`;
}

function renderLighting() {
  const light = settings.lighting;
  const root = document.getElementById("lighting");
  root.innerHTML = `
    <div class="row"><span class="name">Mode</span><select id="li-mode" name="lighting-mode" aria-label="Lighting mode" data-role="mode">${options(["status", "manual"], light.mode)}</select><span></span><span></span></div>
    <div class="row"><span class="name">Brightness</span><input type="number" id="li-brightness" name="lighting-brightness" aria-label="Brightness" min="0" max="100" data-role="brightness" value="${light.brightness}" /><span></span><span></span></div>
    <div class="row"><span class="name">Player LEDs</span><input type="number" id="li-playerLeds" name="lighting-playerLeds" aria-label="Player LEDs" min="0" max="31" data-role="playerLeds" value="${light.playerLeds}" /><span></span><span></span></div>
    <div class="sub">Status colours</div>
    ${STATUS_STATES.map((state) => lightRow(state, light.status[state])).join("")}
    <div class="sub">Manual override</div>
    ${lightRow("manual", light.manual)}`;
  bindAutoSave(root, () => { readLighting(); scheduleSettingsSave(); });
}

function renderMic() {
  const light = settings.lighting;
  const autoMute = light.autoMuteSeconds ?? 60;
  const root = document.getElementById("mic");
  root.innerHTML = `
    <div class="row" data-mic-live><span class="name">Mic</span><span id="mic-state" class="badge">?</span><button type="button" id="mic-toggle" class="secondary">Mute</button><span></span></div>
    <p class="sub" id="mic-linked"></p>
    <div class="sub">Mic button</div>
    <div class="row"><span class="name">Button</span><select id="mi-micButton" name="lighting-micButton" aria-label="Mic button" data-role="micButton">${micButtonOptions(light.micButton)}</select><span></span><span></span></div>
    <div class="row"><span class="name">Mode</span><select id="mi-micButtonMode" name="lighting-micButtonMode" aria-label="Mic button mode" data-role="micButtonMode">${micButtonModeOptions(light.micButtonMode)}</select><span></span><span></span></div>
    <p class="sub">Push to talk keeps the mic live only while the button is held; tap to toggle flips it on each press. Leave the button unset to use the auto-mute timer below.</p>
    <div class="sub">LED</div>
    <div class="row"><span class="name">Mute LED invert</span><input type="checkbox" id="mi-muteLedInvert" name="lighting-muteLedInvert" aria-label="Mute LED invert" data-role="muteLedInvert"${light.muteLedInvert ? " checked" : ""} /><span></span><span></span></div>
    <div class="sub">Auto-mute</div>
    <div class="row"><span class="name">Mute mic after</span><select id="mi-autoMuteSeconds" name="lighting-autoMuteSeconds" aria-label="Mute mic after" data-role="autoMuteSeconds">${autoMuteOptions(autoMute)}</select><span></span><span></span></div>
    <p class="sub">The controller's Mute button always toggles the hardware mic and is not mappable.</p>`;
  bindAutoSave(root, () => { readMic(); scheduleSettingsSave(); });
  root.querySelector("#mic-toggle").addEventListener("click", toggleMic);
  const micButton = root.querySelector('[data-role="micButton"]');
  const syncMicFields = () => {
    const on = !!micButton.value;
    root.querySelector('[data-role="autoMuteSeconds"]').disabled = on;
    root.querySelector('[data-role="micButtonMode"]').disabled = !on;
  };
  micButton.addEventListener("change", syncMicFields);
  syncMicFields();
  refreshMic(root);
}

function micButtonOptions(selected) {
  const group = ([label, inputs]) =>
    `<optgroup label="${label}">${options(inputs.filter((input) => input !== "mute" && input !== "touchpad"), selected)}</optgroup>`;
  return `<option value=""${selected ? "" : " selected"}>(none)</option>` + INPUT_GROUPS.map(group).join("");
}

function micButtonModeOptions(selected) {
  const choices = [["push", "Push to talk (hold)"], ["toggle", "Tap to toggle"]];
  const current = selected || "push";
  return choices
    .map(([value, label]) => `<option value="${value}"${value === current ? " selected" : ""}>${label}</option>`)
    .join("");
}

function refreshMic(root = document.getElementById("mic")) {
  const badge = root && root.querySelector("#mic-state");
  if (!badge) return;
  const muted = !!lastMicMuted;
  badge.textContent = muted ? "muted" : "live";
  badge.classList.toggle("connected", !muted);
  badge.classList.toggle("error", muted);
  const button = root.querySelector("#mic-toggle");
  if (button) button.textContent = muted ? "Unmute" : "Mute";
  const linked = root.querySelector("#mic-linked");
  if (linked) {
    linked.textContent = lastMicButton
      ? `Linked to ${lastMicButton} — ${lastMicButtonMode === "toggle" ? "tap to toggle" : "push to talk"}.`
      : "No linked button — the auto-mute timer applies.";
  }
}

let lastMicMuted = false;
let lastMicButton = "";
let lastMicButtonMode = "push";

async function toggleMic() {
  try {
    const data = await api("/api/mic", "POST", {});
    lastMicMuted = !!data.muted;
    refreshMic();
  } catch (error) {
    showMessage(error.message, "error");
  }
}

// Install / remove the opencode plugin from the UI. The bridge writes the
// global opencode config (npm entry, or local copy as fallback).
async function renderIntegrations() {
  const root = document.getElementById("integrations");
  if (!root) return;
  let info;
  try {
    info = await api("/api/plugin");
  } catch (error) {
    root.innerHTML = `<p class="sub">Could not read plugin status: ${error.message}</p>`;
    return;
  }
  const badge = info.installed
    ? `<span class="badge connected">installed · ${info.mode}</span>`
    : `<span class="badge">not installed</span>`;
  root.innerHTML = `
    <div class="row"><span class="name">opencode plugin</span>${badge}<span></span><span></span></div>
    <p class="sub">Package <code>${info.package}</code> — reports session status to the light and drives the focus-terminal action. Installs from npm when published, otherwise copies from this checkout. Restart opencode after installing.</p>
    <div class="row"><span class="name"></span><button type="button" id="plugin-install" class="secondary">${info.installed ? "Reinstall" : "Install"}</button><button type="button" id="plugin-remove" class="secondary"${info.installed ? "" : " disabled"}>Remove</button><span></span></div>
    <p class="sub">Config: <code>${info.config}</code></p>`;
  root.querySelector("#plugin-install").addEventListener("click", () => pluginAction("install"));
  root.querySelector("#plugin-remove").addEventListener("click", () => pluginAction("uninstall"));
}

async function pluginAction(action) {
  try {
    const info = await api("/api/plugin", "POST", { action });
    const what = info.action === "install" ? `installed (${info.mode})` : "removed";
    showMessage(`Plugin ${info.changed ? what : "already up to date"}. Restart opencode.`, "ok");
  } catch (error) {
    showMessage(error.message, "error");
  }
  await renderIntegrations();
}

const AUTO_MUTE_CHOICES = [
  [0, "Never"],
  [30, "30 seconds"],
  [60, "1 minute"],
  [120, "2 minutes"],
  [300, "5 minutes"],
  [900, "15 minutes"],
  [1800, "30 minutes"],
  [3600, "60 minutes"],
];

function autoMuteOptions(selected) {
  return AUTO_MUTE_CHOICES
    .map(([value, label]) => `<option value="${value}"${Number(value) === Number(selected) ? " selected" : ""}>${label}</option>`)
    .join("");
}

function collectLight(key) {
  const row = document.querySelector(`[data-light="${key}"]`);
  return {
    color: hexToRgb(row.querySelector('[data-role="color"]').value),
    effect: row.querySelector('[data-role="effect"]').value,
    speed: clamp(row.querySelector('[data-role="speed"]').value, 1, 5),
  };
}

function readLighting() {
  const root = document.getElementById("lighting");
  const lighting = {
    ...settings.lighting,
    mode: root.querySelector('[data-role="mode"]').value,
    brightness: Number(root.querySelector('[data-role="brightness"]').value),
    playerLeds: Number(root.querySelector('[data-role="playerLeds"]').value),
    status: {},
    manual: collectLight("manual"),
  };
  for (const state of STATUS_STATES) lighting.status[state] = collectLight(state);
  settings.lighting = lighting;
}

function readMic() {
  const root = document.getElementById("mic");
  settings.lighting = {
    ...settings.lighting,
    muteLedInvert: root.querySelector('[data-role="muteLedInvert"]').checked,
    autoMuteSeconds: Number(root.querySelector('[data-role="autoMuteSeconds"]').value),
    micButton: root.querySelector('[data-role="micButton"]').value,
    micButtonMode: root.querySelector('[data-role="micButtonMode"]').value,
  };
}

// -- triggers ----------------------------------------------------------
function triggerRow(side, trigger) {
  return `<div class="row" data-trigger="${side}">
    <span class="name">${side}</span>
    <select id="tr-${side}-mode" name="trigger-${side}-mode" aria-label="${side} trigger mode" data-role="mode">${options(["off", "feedback", "weapon"], trigger.mode)}</select>
    <span class="inline">start <input type="number" id="tr-${side}-start" name="trigger-${side}-start" aria-label="${side} trigger start" min="0" max="9" data-role="start" value="${trigger.start}" /></span>
    <span class="inline">end <input type="number" id="tr-${side}-end" name="trigger-${side}-end" aria-label="${side} trigger end" min="1" max="9" data-role="end" value="${trigger.end}" /> strength <input type="number" id="tr-${side}-strength" name="trigger-${side}-strength" aria-label="${side} trigger strength" min="1" max="8" data-role="strength" value="${trigger.strength}" /></span>
  </div>`;
}

function renderTriggers() {
  const triggers = settings.triggers;
  const root = document.getElementById("triggers");
  root.innerHTML = triggerRow("left", triggers.left) + triggerRow("right", triggers.right);
  bindAutoSave(root, () => { readTriggers(); scheduleSettingsSave(); });
}

function collectTrigger(side) {
  const row = document.querySelector(`[data-trigger="${side}"]`);
  return {
    mode: row.querySelector('[data-role="mode"]').value,
    start: Number(row.querySelector('[data-role="start"]').value),
    end: Number(row.querySelector('[data-role="end"]').value),
    strength: Number(row.querySelector('[data-role="strength"]').value),
  };
}

function readTriggers() {
  settings.triggers = { left: collectTrigger("left"), right: collectTrigger("right") };
}

function bindAutoSave(root, save) {
  root.querySelectorAll("input, select").forEach((node) => {
    node.addEventListener("change", save);
    node.addEventListener("input", save);
  });
}

// -- status / theme ----------------------------------------------------
// Sticks glow while deflected (moving); a clicked stick (L3/R3) is brighter.
function setStickGlow(input, moving, clickedBtn) {
  document.querySelectorAll(`#controller [data-input="${input}"]`).forEach((node) => {
    node.classList.toggle("pressed", moving || clickedBtn);
    node.classList.toggle("clicked", clickedBtn);
  });
}

// Triggers brighten with the analog press depth (level: 0..1). Scoped to the
// controller so the mapping list rows never light up with the live state.
function setTriggerGlow(input, level) {
  const active = level > 0.02;
  document.querySelectorAll(`#controller [data-input="${input}"]`).forEach((node) => {
    node.classList.toggle("pressed", active);
    if (active) {
      node.style.opacity = String(0.25 + 0.75 * level);
      node.style.filter =
        `brightness(${(0.7 + 0.6 * level).toFixed(2)}) drop-shadow(0 0 ${(2 + level * 9).toFixed(1)}px var(--hover))`;
    } else {
      node.style.opacity = "";
      node.style.filter = "";
    }
  });
}

async function pollStatus() {
  const deviceBadge = document.getElementById("status-device");
  try {
    const status = await api("/api/status");
    deviceBadge.textContent = `device: ${status.device}`;
    deviceBadge.classList.toggle("connected", status.device === "connected");
    document.getElementById("status-state").textContent = `state: ${status.status}`;
    const pressed = new Set(status.inputs || []);
    document.querySelectorAll("#controller [data-input]").forEach((node) => {
      const input = node.dataset.input;
      if (
        input === "touchpad_left" || input === "touchpad_right" ||
        input === "l3" || input === "r3" || input === "l2" || input === "r2"
      ) return;
      node.classList.toggle("pressed", pressed.has(input));
    });
    const zone = status.touchpadZone || null;
    const clicked = !!status.touchpadClick;
    document.querySelectorAll('#controller [data-input="touchpad_left"],#controller [data-input="touchpad_right"]').forEach((node) => {
      const active = node.dataset.input === (zone === "left" ? "touchpad_left" : zone === "right" ? "touchpad_right" : null);
      node.classList.toggle("pressed", active);
      node.classList.toggle("clicked", active && clicked);
    });
    // Sticks: lit while deflected (moving), brighter when the stick is clicked.
    const axes = status.axes || {};
    const mag = (x, y) => Math.hypot(x || 0, y || 0);
    setStickGlow("l3", mag(axes.leftX, axes.leftY) > 0.05, pressed.has("l3"));
    setStickGlow("r3", mag(axes.rightX, axes.rightY) > 0.05, pressed.has("r3"));
    // Triggers: brightness follows the analog press depth (0..1).
    const tl = status.triggerLevel || { left: 0, right: 0 };
    setTriggerGlow("l2", tl.left);
    setTriggerGlow("r2", tl.right);
    updateSticks(axes);
    if ("micMuted" in status) {
      lastMicMuted = !!status.micMuted;
      lastMicButton = status.micButton || "";
      lastMicButtonMode = status.micButtonMode || "push";
      refreshMic();
    }
  } catch (error) {
    deviceBadge.textContent = "device: offline";
    deviceBadge.classList.remove("connected");
  }
}

// -- UI focus guard ----------------------------------------------------
// While this page holds focus the bridge suppresses controller mappings, so a
// mapped key (e.g. circle -> Backspace) cannot drive the page itself. Leaving
// the page reports false at once and the bridge resumes mapping. Focus is
// tracked from events, never re-read at blur time, so a lagging hasFocus()
// cannot leave the guard stuck on.
const UI_HEARTBEAT_MS = 1000;

function reportUiFocus(active) {
  fetch("/api/ui-active", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ active }),
    keepalive: true,
  }).catch(() => {});
}

function watchUiFocus() {
  let focused = document.hasFocus();
  let timer = null;

  const publish = () => {
    const active = focused && document.visibilityState === "visible";
    reportUiFocus(active);
    if (active && timer === null) {
      timer = setInterval(publish, UI_HEARTBEAT_MS);
    } else if (!active && timer !== null) {
      clearInterval(timer);
      timer = null;
    }
  };

  window.addEventListener("focus", () => { focused = true; publish(); });
  window.addEventListener("blur", () => { focused = false; publish(); });
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) focused = false;
    publish();
  });
  window.addEventListener("pagehide", () => reportUiFocus(false));

  publish();
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
}

// -- bootstrap ---------------------------------------------------------
async function load() {
  mapping = await api("/api/mapping");
  settings = await api("/api/settings");
  working = JSON.parse(JSON.stringify(mapping));
  if (!svgMarkup) {
    svgMarkup = await (await fetch("/assets/dualsense.svg")).text();
  }
  document.getElementById("mapping-enabled").checked = !!working.enabled;
  renderController();
  renderMappings();
  renderEditor();
  renderTouchpad();
  renderLighting();
  renderTriggers();
  renderMic();
  await refreshPresets();
  await renderIntegrations();
  applyTheme("dark");
  applyEnabledState();
  syncPanelHeights();
  await pollStatus();
}

function bind() {
  document.getElementById("mapping-enabled").addEventListener("change", (event) => {
    working.enabled = event.target.checked;
    applyEnabledState();
    scheduleMappingSave();
  });
  document.getElementById("recorder-cancel").addEventListener("click", cancelRecording);
  document.getElementById("preset-apply").addEventListener("click", applySelectedPreset);
  document.getElementById("preset-select").addEventListener("change", resetPresetDelete);
  document.getElementById("preset-delete").addEventListener("click", deleteSelectedPreset);
  document.getElementById("preset-new").addEventListener("click", showPresetCreate);
  document.getElementById("preset-new-save").addEventListener("click", saveNewPreset);
  document.getElementById("preset-new-cancel").addEventListener("click", hidePresetCreate);
  document.getElementById("preset-new-name").addEventListener("keydown", (event) => {
    if (event.key === "Enter") saveNewPreset();
    if (event.key === "Escape") hidePresetCreate();
  });
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => activateTab(tab.dataset.tab));
  });
  window.addEventListener("resize", syncPanelHeights);
  const leftCard = document.querySelector(".pane-left .card");
  if (leftCard && window.ResizeObserver) new ResizeObserver(syncPanelHeights).observe(leftCard);
  // The bridge injects whatever you map, so while this page happens to be
  // focused a mapping like circle -> Backspace would otherwise drive the page
  // itself. Swallow the browser's own navigation shortcuts here instead of
  // making the bridge guess whether this page is focused; real typing in a
  // field is never touched.
  document.addEventListener("keydown", (event) => {
    const target = event.target;
    if (target instanceof HTMLElement && (target.isContentEditable || /^(INPUT|SELECT|TEXTAREA)$/.test(target.tagName))) return;
    const combo = event.ctrlKey || event.metaKey;
    const nav = event.code === "Backspace" || event.code === "F5"
      || (event.altKey && (event.code === "ArrowLeft" || event.code === "ArrowRight"))
      || (combo && (event.code === "KeyR" || event.code === "KeyW" || event.code === "KeyT" || event.code === "Tab"));
    if (nav) event.preventDefault();
  });
}

bind();
watchUiFocus();
load().catch((error) => showMessage(error.message, "error"));
setInterval(pollStatus, 120);
