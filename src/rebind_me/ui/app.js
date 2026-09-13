import {
  ACTIONS, EFFECTS, INPUT_NAMES, MODES, MOUSE_CODES, SCROLL_CODES, STATUS_STATES,
  clamp, hexToRgb, mappingEntryFromForm, mappingFormFromEntry, rgbToHex,
} from "./model.js";

let mapping = null;
let settings = null;

const message = document.getElementById("message");

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

function options(values, selected) {
  return values.map((value) => `<option value="${value}"${value === selected ? " selected" : ""}>${value}</option>`).join("");
}

// -- mapping -----------------------------------------------------------
function optionRow(state, light) {
  const color = rgbToHex(light.color);
  return `<div class="row" data-light="${state}">
    <span class="name">${state}</span>
    <input type="color" data-role="color" value="${color}" />
    <select data-role="effect">${options(EFFECTS, light.effect)}</select>
    <span class="inline">speed <input type="number" min="1" max="5" data-role="speed" value="${light.speed}" /></span>
  </div>`;
}

function mappingRow(name) {
  const action = (mapping.actions || {})[name];
  const entry = (mapping.mappings || {})[name];
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
  return `<div class="row" data-input="${name}">
    <span class="name">${name}</span>
    <select data-role="type">
      <option value="none"${form.kind === "none" ? " selected" : ""}>none</option>
      <option value="sequence"${form.kind === "sequence" ? " selected" : ""}>keys</option>
      <option value="mouse"${form.kind === "mouse" ? " selected" : ""}>mouse</option>
      <option value="scroll"${form.kind === "scroll" ? " selected" : ""}>scroll</option>
      <option value="action"${form.kind === "action" ? " selected" : ""}>action</option>
    </select>
    <select data-role="mode">${options(MODES, form.mode)}</select>
    <span class="value">
      <input data-role="sequence" size="28" placeholder="ControlLeft, KeyK; KeyL" value="${form.sequenceText}" />
      <select data-role="mouse">${options(MOUSE_CODES, form.mouse)}</select>
      <select data-role="scroll">${options(SCROLL_CODES, form.scroll)}</select>
      <span data-role="action-wrap" class="inline">
        <select data-role="action">${options(ACTIONS, form.action)}</select>
        <input data-role="process" placeholder="process.exe" value="${form.process}" />
      </span>
      <span data-role="repeat-wrap" class="inline">delay <input type="number" data-role="repeatDelay" value="${form.repeatDelay}" /> interval <input type="number" data-role="repeatInterval" value="${form.repeatInterval}" /></span>
      <span data-role="toggle-wrap" class="inline">initial <select data-role="toggleInitial"><option value="off"${form.toggleInitial === "off" ? " selected" : ""}>off</option><option value="on"${form.toggleInitial === "on" ? " selected" : ""}>on</option></select></span>
    </span>
  </div>`;
}

function syncRow(row) {
  const kind = row.querySelector('[data-role="type"]').value;
  const mode = row.querySelector('[data-role="mode"]').value;
  const show = (selector, visible) => row.querySelector(selector).classList.toggle("hidden", !visible);
  show('[data-role="sequence"]', kind === "sequence");
  show('[data-role="mouse"]', kind === "mouse");
  show('[data-role="scroll"]', kind === "scroll");
  show('[data-role="action-wrap"]', kind === "action");
  show('[data-role="repeat-wrap"]', kind === "sequence" && mode === "repeat");
  show('[data-role="toggle-wrap"]', mode === "toggle");
  row.querySelector('[data-role="mode"]').disabled = kind === "action" || kind === "none";
}

function renderMappings() {
  document.getElementById("mapping-enabled").checked = !!mapping.enabled;
  document.getElementById("mappings").innerHTML = INPUT_NAMES.map(mappingRow).join("");
  document.querySelectorAll("#mappings .row").forEach(syncRow);
}

function collectMapping() {
  const mappings = {};
  const actions = {};
  for (const name of INPUT_NAMES) {
    const row = document.querySelector(`[data-input="${name}"]`);
    const kind = row.querySelector('[data-role="type"]').value;
    if (kind === "none") continue;
    if (kind === "action") {
      const action = row.querySelector('[data-role="action"]').value;
      const entry = { action };
      if (action === "switch-to-app") entry.params = { process: row.querySelector('[data-role="process"]').value.trim() };
      actions[name] = entry;
      continue;
    }
    const form = {
      kind,
      mode: row.querySelector('[data-role="mode"]').value,
      sequenceText: row.querySelector('[data-role="sequence"]').value,
      mouse: row.querySelector('[data-role="mouse"]').value,
      scroll: row.querySelector('[data-role="scroll"]').value,
      repeatDelay: Number(row.querySelector('[data-role="repeatDelay"]').value),
      repeatInterval: Number(row.querySelector('[data-role="repeatInterval"]').value),
      toggleInitial: row.querySelector('[data-role="toggleInitial"]').value,
    };
    const result = mappingEntryFromForm(form);
    if (result.error) throw new Error(`${name}: ${result.error}`);
    mappings[name] = result.entry;
  }
  return { mappings, actions };
}

async function saveMapping() {
  const { mappings, actions } = collectMapping();
  const document_ = {
    version: mapping.version,
    enabled: document.getElementById("mapping-enabled").checked,
    mappings,
    actions,
    touchpad: mapping.touchpad,
  };
  mapping = await api("/api/mapping", "PUT", { ...document_, baseVersion: mapping.baseVersion });
  renderMappings();
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
  renderTouchpad();
  showMessage("Touchpad saved", "ok");
}

// -- lighting ----------------------------------------------------------
function renderLighting() {
  const light = settings.lighting;
  const rows = STATUS_STATES.map((state) => optionRow(state, light.status[state])).join("");
  document.getElementById("lighting").innerHTML = `
    <div class="row"><span class="name">Mode</span><select data-role="mode">${options(["status", "manual"], light.mode)}</select><span></span><span></span></div>
    <div class="row"><span class="name">Brightness</span><input type="number" min="0" max="100" data-role="brightness" value="${light.brightness}" /><span></span><span></span></div>
    <div class="row"><span class="name">Player LEDs</span><input type="number" min="0" max="31" data-role="playerLeds" value="${light.playerLeds}" /><span></span><span></span></div>
    <div class="row"><span class="name">Mute LED invert</span><input type="checkbox" data-role="muteLedInvert"${light.muteLedInvert ? " checked" : ""} /><span></span><span></span></div>
    <div class="sub">Status colours</div>
    ${rows}
    <div class="sub">Manual override</div>
    ${optionRow("manual", light.manual)}`;
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
  try {
    const status = await api("/api/status");
    document.getElementById("status-device").textContent = `device: ${status.device}`;
    document.getElementById("status-state").textContent = `state: ${status.status}`;
  } catch (error) {
    document.getElementById("status-device").textContent = "device: offline";
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
  renderMappings();
  renderTouchpad();
  renderLighting();
  renderTriggers();
  applyTheme(settings.ui.theme || "dark");
  await pollStatus();
}

function bind() {
  document.getElementById("mappings").addEventListener("change", (event) => {
    const row = event.target.closest(".row");
    if (row) syncRow(row);
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
setInterval(pollStatus, 1500);
