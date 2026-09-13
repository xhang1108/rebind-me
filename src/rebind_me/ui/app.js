import {
  ACTIONS, EFFECTS, INPUT_NAMES, MODES, MOUSE_CODES, SCROLL_CODES, STATUS_STATES,
  appendKeys, clamp, hexToRgb, mappingEntryFromForm, mappingFormFromEntry,
  mappingSummary, rgbToHex, stickOffset,
} from "./model.js";

let mapping = null;
let settings = null;
let working = null;
let selected = "cross";

const message = document.getElementById("message");
const VB = 128;

function showMessage(text, kind) {
  message.textContent = text;
  message.className = `message ${kind || ""}`;
  message.hidden = false;
  if (kind === "ok") setTimeout(() => { message.hidden = true; }, 2500);
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
  13: "circle",
  14: "mute",
  15: "dpad_down",
  16: "dpad_up",
  17: "dpad_left",
  18: "dpad_right",
  19: "options",
  20: "create",
  21: "ps",
  22: "ps",
};

// Thin glyphs get an invisible thicker stroke so they are easy to hit.
const THIN_INPUTS = new Set(["ps", "mute", "create", "options"]);

// The artwork has no stick-direction glyphs, so these small transparent
// targets around each stick remain (everything else uses the SVG shapes).
const DIRECTION_ZONES = [
  ["left_stick_up", 45.5, 52.5],
  ["left_stick_down", 45.5, 76.5],
  ["left_stick_left", 33.5, 64.5],
  ["left_stick_right", 57.5, 64.5],
  ["right_stick_up", 82.5, 52.5],
  ["right_stick_down", 82.5, 76.5],
  ["right_stick_left", 70.5, 64.5],
  ["right_stick_right", 94.5, 64.5],
];

const SVG_NS = "http://www.w3.org/2000/svg";

let svgMarkup = "";

function box(cx, cy, w, h) {
  return `left:${pct(cx - w / 2)};top:${pct(cy - h / 2)};width:${pct(w)};height:${pct(h)}`;
}

function selectInput(input) {
  selected = input;
  refreshMap();
  renderEditor();
}

function refreshMap() {
  document.querySelectorAll("[data-input]").forEach((node) => {
    const input = node.dataset.input;
    const mapped = working.mappings[input] || working.actions[input];
    node.classList.toggle("mapped", !!mapped);
    node.classList.toggle("selected", input === selected);
  });
}

function hoverPath(input, on) {
  document.querySelectorAll(`.pad-svg svg path[data-input="${input}"]`).forEach((path) => {
    path.classList.toggle("hover", on);
  });
}

// Transparent shape matching each glyph's footprint, so the interior (the hole
// of the outline) is clickable while still using the SVG geometry.
function addHitbox(svg, element, input) {
  const bounds = element.getBBox();
  let shape;
  if (input === "touchpad") {
    shape = document.createElementNS(SVG_NS, "rect");
    shape.setAttribute("x", bounds.x);
    shape.setAttribute("y", bounds.y);
    shape.setAttribute("width", bounds.width);
    shape.setAttribute("height", bounds.height);
  } else {
    shape = document.createElementNS(SVG_NS, "ellipse");
    shape.setAttribute("cx", bounds.x + bounds.width / 2);
    shape.setAttribute("cy", bounds.y + bounds.height / 2);
    shape.setAttribute("rx", Math.max(bounds.width / 2, 1.3));
    shape.setAttribute("ry", Math.max(bounds.height / 2, 1.3));
  }
  shape.setAttribute("class", "hitbox");
  shape.setAttribute("data-input", input);
  shape.setAttribute("fill", "transparent");
  shape.setAttribute("pointer-events", "all");
  shape.addEventListener("click", () => selectInput(input));
  shape.addEventListener("mouseenter", () => hoverPath(input, true));
  shape.addEventListener("mouseleave", () => hoverPath(input, false));
  const title = document.createElementNS(SVG_NS, "title");
  title.textContent = input;
  shape.appendChild(title);
  svg.appendChild(shape);
}

function tagSvg(container) {
  const svg = container.querySelector(".pad-svg svg");
  const paths = svg.querySelectorAll("path");
  paths.forEach((path, index) => {
    const input = PATH_INPUT[index];
    if (!input) return;
    path.dataset.input = input;
    path.classList.add("hit");
    if (THIN_INPUTS.has(input)) path.style.strokeWidth = "5";
    const hint = document.createElementNS(SVG_NS, "title");
    const summary = mappingSummary(working.mappings[input], working.actions[input]);
    hint.textContent = summary === "-" ? input : `${input}: ${summary}`;
    path.appendChild(hint);
    path.addEventListener("click", () => selectInput(input));
  });
  paths.forEach((path, index) => {
    const input = PATH_INPUT[index];
    if (input) addHitbox(svg, path, input);
  });
}

function renderDirs(wrap) {
  const html = DIRECTION_ZONES.map(([input, cx, cy]) =>
    `<button type="button" class="dir" data-input="${input}" style="${box(cx, cy, 9, 9)}" title="${input}"></button>`
  ).join("");
  wrap.insertAdjacentHTML("beforeend", html);
  wrap.querySelectorAll(".dir").forEach((node) => {
    node.addEventListener("click", () => selectInput(node.dataset.input));
  });
}

function drawTriggers(svg) {
  // L2/R2 are not in the artwork. Clone the L1/R1 glyphs and lift them above
  // the shoulders so the trigger keeps the same curvature and line style.
  const paths = svg.querySelectorAll("path");
  const clone = (source, input, dy) => {
    if (!source) return;
    const path = source.cloneNode(false);
    path.setAttribute("class", "hit");
    path.setAttribute("data-input", input);
    path.removeAttribute("transform");
    path.setAttribute("transform", `translate(0 ${dy})`);
    path.style.strokeWidth = "";
    path.addEventListener("click", () => selectInput(input));
    const title = document.createElementNS(SVG_NS, "title");
    title.textContent = input;
    path.appendChild(title);
    svg.appendChild(path);
    addHitbox(svg, path, input);
  };
  clone(paths[10], "l2", -8);
  clone(paths[9], "r2", -8);
}

function renderController() {
  const container = document.getElementById("controller");
  container.innerHTML = `<div class="pad-wrap"><div class="pad-svg">${svgMarkup}</div></div>`;
  const wrap = container.querySelector(".pad-wrap");
  tagSvg(container);
  drawTriggers(container.querySelector(".pad-svg svg"));
  renderDirs(wrap);
  refreshMap();
}

function updateSticks(axes) {
  const paths = document.querySelectorAll(".pad-svg svg path");
  const leftInner = paths[7];
  const rightInner = paths[8];
  if (leftInner) {
    const [x, y] = stickOffset(axes.leftX || 0, axes.leftY || 0);
    leftInner.setAttribute("transform", `translate(${x} ${y})`);
  }
  if (rightInner) {
    const [x, y] = stickOffset(axes.rightX || 0, axes.rightY || 0);
    rightInner.setAttribute("transform", `translate(${x} ${y})`);
  }
}

function renderEditor() {
  document.getElementById("editor-name").textContent = selected || "-";
  if (!selected) { document.getElementById("editor").innerHTML = "<p class='sub'>Select a button.</p>"; return; }

  const action = working.actions[selected];
  const entry = working.mappings[selected];
  let form;
  if (action) {
    form = { kind: "action", mode: "single", sequenceText: "", mouse: MOUSE_CODES[0], scroll: SCROLL_CODES[0], repeatDelay: 300, repeatInterval: 50, toggleInitial: "off" };
    form.action = action.action;
    form.process = (action.params || {}).process || "";
  } else {
    form = mappingFormFromEntry(entry);
    form.action = ACTIONS[0];
    form.process = "";
  }

  const editor = document.getElementById("editor");
  editor.innerHTML = `
    <div class="line">
      <label>Type <select data-role="type">
        <option value="none"${form.kind === "none" ? " selected" : ""}>none</option>
        <option value="sequence"${form.kind === "sequence" ? " selected" : ""}>keys</option>
        <option value="mouse"${form.kind === "mouse" ? " selected" : ""}>mouse</option>
        <option value="scroll"${form.kind === "scroll" ? " selected" : ""}>scroll</option>
        <option value="action"${form.kind === "action" ? " selected" : ""}>action</option>
      </select></label>
      <label>Mode <select data-role="mode">${options(MODES, form.mode)}</select></label>
      <span data-role="toggle-wrap" class="inline">Initial
        <select data-role="toggleInitial"><option value="off"${form.toggleInitial === "off" ? " selected" : ""}>off</option><option value="on"${form.toggleInitial === "on" ? " selected" : ""}>on</option></select>
      </span>
    </div>
    <div data-role="seq-wrap">
      <textarea data-role="sequence" placeholder="ControlLeft, KeyK; KeyL">${form.sequenceText}</textarea>
      <div class="line">
        <button type="button" id="record-key">Record key</button>
        <button type="button" id="record-segment" class="secondary">+ chord segment</button>
        <button type="button" id="clear-seq" class="secondary">Clear</button>
        <span class="sub">Chord: separate keys with commas, segments with semicolons.</span>
      </div>
    </div>
    <div class="line" data-role="mouse-wrap"><label>Mouse <select data-role="mouse">${options(MOUSE_CODES, form.mouse)}</select></label></div>
    <div class="line" data-role="scroll-wrap"><label>Scroll <select data-role="scroll">${options(SCROLL_CODES, form.scroll)}</select></label></div>
    <div class="line" data-role="action-wrap">
      <label>Action <select data-role="action">${options(ACTIONS, form.action)}</select></label>
      <label>Process <input data-role="process" placeholder="process.exe" value="${form.process}" /></label>
    </div>
    <div class="line" data-role="repeat-wrap">
      <label>Delay ms <input type="number" min="10" max="2000" data-role="repeatDelay" value="${form.repeatDelay}" /></label>
      <label>Interval ms <input type="number" min="10" max="2000" data-role="repeatInterval" value="${form.repeatInterval}" /></label>
    </div>`;

  editor.querySelector('[data-role="type"]').addEventListener("change", () => { syncEditor(); applyEditor(); });
  editor.querySelector('[data-role="mode"]').addEventListener("change", () => { syncEditor(); applyEditor(); });
  editor.querySelector('[data-role="toggleInitial"]').addEventListener("change", applyEditor);
  editor.querySelector('[data-role="sequence"]').addEventListener("input", applyEditor);
  editor.querySelector('[data-role="mouse"]').addEventListener("change", applyEditor);
  editor.querySelector('[data-role="scroll"]').addEventListener("change", applyEditor);
  editor.querySelector('[data-role="action"]').addEventListener("change", () => { syncEditor(); applyEditor(); });
  editor.querySelector('[data-role="process"]').addEventListener("input", applyEditor);
  editor.querySelector('[data-role="repeatDelay"]').addEventListener("input", applyEditor);
  editor.querySelector('[data-role="repeatInterval"]').addEventListener("input", applyEditor);
  document.getElementById("clear-seq").addEventListener("click", () => {
    editor.querySelector('[data-role="sequence"]').value = "";
    applyEditor();
  });
  document.getElementById("record-key").addEventListener("click", (event) => recordKey(event.target, false));
  document.getElementById("record-segment").addEventListener("click", (event) => recordKey(event.target, true));
  syncEditor();
}

function syncEditor() {
  const editor = document.getElementById("editor");
  const type = editor.querySelector('[data-role="type"]').value;
  const mode = editor.querySelector('[data-role="mode"]').value;
  const show = (selector, visible) => { const node = editor.querySelector(selector); if (node) node.classList.toggle("hidden", !visible); };
  show('[data-role="seq-wrap"]', type === "sequence");
  show('[data-role="mouse-wrap"]', type === "mouse");
  show('[data-role="scroll-wrap"]', type === "scroll");
  show('[data-role="action-wrap"]', type === "action");
  show('[data-role="repeat-wrap"]', type === "sequence" && mode === "repeat");
  show('[data-role="toggle-wrap"]', mode === "toggle");
  editor.querySelector('[data-role="mode"]').disabled = type === "action" || type === "none";
}

function applyEditor() {
  if (!selected) return;
  const editor = document.getElementById("editor");
  const type = editor.querySelector('[data-role="type"]').value;
  delete working.mappings[selected];
  delete working.actions[selected];
  if (type === "action") {
    const action = editor.querySelector('[data-role="action"]').value;
    const entry = { action };
    if (action === "switch-to-app") entry.params = { process: editor.querySelector('[data-role="process"]').value.trim() };
    working.actions[selected] = entry;
  } else if (type !== "none") {
    const result = mappingEntryFromForm({
      kind: type,
      mode: editor.querySelector('[data-role="mode"]').value,
      sequenceText: editor.querySelector('[data-role="sequence"]').value,
      mouse: editor.querySelector('[data-role="mouse"]').value,
      scroll: editor.querySelector('[data-role="scroll"]').value,
      repeatDelay: Number(editor.querySelector('[data-role="repeatDelay"]').value),
      repeatInterval: Number(editor.querySelector('[data-role="repeatInterval"]').value),
      toggleInitial: editor.querySelector('[data-role="toggleInitial"]').value,
    });
    if (result.entry) working.mappings[selected] = result.entry;
  }
  refreshMap();
}

async function recordKey(button, newSegment) {
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Press a key...";
  try {
    const data = await api("/api/key-capture", "POST");
    if (data.cancelled) {
      showMessage("Capture cancelled", "error");
    } else if (data.keys && data.keys.length) {
      const textarea = document.querySelector('#editor [data-role="sequence"]');
      textarea.value = appendKeys(textarea.value, data.keys, newSegment);
      applyEditor();
      showMessage(`Captured ${data.keys.join(" + ")}`, "ok");
    }
  } catch (error) {
    showMessage(error.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

async function saveMapping() {
  const documentBody = {
    version: working.version,
    enabled: document.getElementById("mapping-enabled").checked,
    mappings: working.mappings,
    actions: working.actions,
    touchpad: working.touchpad,
  };
  mapping = await api("/api/mapping", "PUT", { ...documentBody, baseVersion: mapping.baseVersion });
  working = JSON.parse(JSON.stringify(mapping));
  refreshMap();
  renderEditor();
  showMessage("Mappings saved", "ok");
}

// -- touchpad ----------------------------------------------------------
function renderTouchpad() {
  const tp = mapping.touchpad;
  document.getElementById("touchpad").innerHTML = `
    <div class="row"><span class="name">Mouse control</span><input type="checkbox" data-role="mouseControl"${tp.mouseControl ? " checked" : ""} /><span></span><span></span></div>
    <div class="row"><span class="name">Sensitivity</span><input type="number" step="0.1" min="0.1" max="5" data-role="sensitivity" value="${tp.sensitivity}" /><span></span><span></span></div>
    <div class="row"><span class="name">Split X</span><input type="number" min="0" max="1919" data-role="splitX" value="${tp.splitX}" /><span></span><span></span></div>
    <div class="row"><span class="name">Tap left / right</span><select data-role="tapLeft">${options([""].concat(MOUSE_CODES), tp.tap.left)}</select><select data-role="tapRight">${options([""].concat(MOUSE_CODES), tp.tap.right)}</select><span></span></div>
    <div class="row"><span class="name">Click left / right</span><select data-role="clickLeft">${options([""].concat(MOUSE_CODES), tp.click.left)}</select><select data-role="clickRight">${options([""].concat(MOUSE_CODES), tp.click.right)}</select><span></span></div>`;
}

async function saveTouchpad() {
  const root = document.getElementById("touchpad");
  const touchpad = {
    mouseControl: root.querySelector('[data-role="mouseControl"]').checked,
    sensitivity: Number(root.querySelector('[data-role="sensitivity"]').value),
    splitX: Number(root.querySelector('[data-role="splitX"]').value),
    tap: { left: root.querySelector('[data-role="tapLeft"]').value, right: root.querySelector('[data-role="tapRight"]').value },
    click: { left: root.querySelector('[data-role="clickLeft"]').value, right: root.querySelector('[data-role="clickRight"]').value },
  };
  mapping = await api("/api/mapping", "PUT", { ...mapping, touchpad, baseVersion: mapping.baseVersion });
  working = JSON.parse(JSON.stringify(mapping));
  renderTouchpad();
  showMessage("Touchpad saved", "ok");
}

// -- lighting ----------------------------------------------------------
function lightRow(state, light) {
  return `<div class="row" data-light="${state}">
    <span class="name">${state}</span>
    <input type="color" data-role="color" value="${rgbToHex(light.color)}" />
    <select data-role="effect">${options(EFFECTS, light.effect)}</select>
    <span class="inline">speed <input type="number" min="1" max="5" data-role="speed" value="${light.speed}" /></span>
  </div>`;
}

function renderLighting() {
  const light = settings.lighting;
  document.getElementById("lighting").innerHTML = `
    <div class="row"><span class="name">Mode</span><select data-role="mode">${options(["status", "manual"], light.mode)}</select><span></span><span></span></div>
    <div class="row"><span class="name">Brightness</span><input type="number" min="0" max="100" data-role="brightness" value="${light.brightness}" /><span></span><span></span></div>
    <div class="row"><span class="name">Player LEDs</span><input type="number" min="0" max="31" data-role="playerLeds" value="${light.playerLeds}" /><span></span><span></span></div>
    <div class="row"><span class="name">Mute LED invert</span><input type="checkbox" data-role="muteLedInvert"${light.muteLedInvert ? " checked" : ""} /><span></span><span></span></div>
    <div class="sub">Status colours</div>
    ${STATUS_STATES.map((state) => lightRow(state, light.status[state])).join("")}
    <div class="sub">Manual override</div>
    ${lightRow("manual", light.manual)}`;
}

function collectLight(key) {
  const row = document.querySelector(`[data-light="${key}"]`);
  return {
    color: hexToRgb(row.querySelector('[data-role="color"]').value),
    effect: row.querySelector('[data-role="effect"]').value,
    speed: clamp(row.querySelector('[data-role="speed"]').value, 1, 5),
  };
}

async function saveLighting() {
  const root = document.getElementById("lighting");
  const lighting = {
    mode: root.querySelector('[data-role="mode"]').value,
    brightness: Number(root.querySelector('[data-role="brightness"]').value),
    playerLeds: Number(root.querySelector('[data-role="playerLeds"]').value),
    muteLedInvert: root.querySelector('[data-role="muteLedInvert"]').checked,
    status: {},
    manual: collectLight("manual"),
  };
  for (const state of STATUS_STATES) lighting.status[state] = collectLight(state);
  const result = await api("/api/lighting", "PUT", { ...lighting, baseVersion: settings.baseVersion });
  settings.lighting = result;
  settings.baseVersion = result.baseVersion;
  renderLighting();
  showMessage("Lighting saved", "ok");
}

// -- triggers ----------------------------------------------------------
function triggerRow(side, trigger) {
  return `<div class="row" data-trigger="${side}">
    <span class="name">${side}</span>
    <select data-role="mode">${options(["off", "feedback", "weapon"], trigger.mode)}</select>
    <span class="inline">start <input type="number" min="0" max="9" data-role="start" value="${trigger.start}" /></span>
    <span class="inline">end <input type="number" min="1" max="9" data-role="end" value="${trigger.end}" /> strength <input type="number" min="1" max="8" data-role="strength" value="${trigger.strength}" /></span>
  </div>`;
}

function renderTriggers() {
  const triggers = settings.triggers;
  document.getElementById("triggers").innerHTML = triggerRow("left", triggers.left) + triggerRow("right", triggers.right);
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

async function saveTriggers() {
  const result = await api("/api/triggers", "PUT", {
    left: collectTrigger("left"),
    right: collectTrigger("right"),
    baseVersion: settings.baseVersion,
  });
  settings.triggers = { left: result.left, right: result.right };
  settings.baseVersion = result.baseVersion;
  renderTriggers();
  showMessage("Triggers saved", "ok");
}

// -- status / theme ----------------------------------------------------
async function pollStatus() {
  const deviceBadge = document.getElementById("status-device");
  try {
    const status = await api("/api/status");
    deviceBadge.textContent = `device: ${status.device}`;
    deviceBadge.classList.toggle("connected", status.device === "connected");
    document.getElementById("status-state").textContent = `state: ${status.status}`;
    const pressed = new Set(status.inputs || []);
    document.querySelectorAll("#controller [data-input]").forEach((node) => {
      node.classList.toggle("pressed", pressed.has(node.dataset.input));
    });
    updateSticks(status.axes || {});
  } catch (error) {
    deviceBadge.textContent = "device: offline";
    deviceBadge.classList.remove("connected");
  }
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  document.getElementById("theme").value = theme;
}

async function saveTheme(theme) {
  settings.ui.theme = theme;
  settings = await api("/api/settings", "PUT", { ...settings, baseVersion: settings.baseVersion });
  applyTheme(settings.ui.theme);
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
  renderEditor();
  renderTouchpad();
  renderLighting();
  renderTriggers();
  applyTheme(settings.ui.theme || "dark");
  await pollStatus();
}

function bind() {
  document.getElementById("mapping-enabled").addEventListener("change", (event) => {
    working.enabled = event.target.checked;
  });
  document.getElementById("save-mapping").addEventListener("click", () =>
    saveMapping().catch((error) => showMessage(error.message, "error")));
  document.getElementById("save-touchpad").addEventListener("click", () =>
    saveTouchpad().catch((error) => showMessage(error.message, "error")));
  document.getElementById("save-lighting").addEventListener("click", () =>
    saveLighting().catch((error) => showMessage(error.message, "error")));
  document.getElementById("save-triggers").addEventListener("click", () =>
    saveTriggers().catch((error) => showMessage(error.message, "error")));
  document.getElementById("theme").addEventListener("change", (event) =>
    saveTheme(event.target.value).catch((error) => showMessage(error.message, "error")));
}

bind();
load().catch((error) => showMessage(error.message, "error"));
setInterval(pollStatus, 120);
