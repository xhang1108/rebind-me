// Pure UI model helpers (no DOM), shared with node --test.

export const INPUT_NAMES = [
  "square", "cross", "circle", "triangle",
  "dpad_up", "dpad_right", "dpad_down", "dpad_left",
  "l1", "r1", "l2", "r2", "create", "options", "l3", "r3",
  "ps", "touchpad", "mute",
  "left_stick_up", "left_stick_right", "left_stick_down", "left_stick_left",
  "right_stick_up", "right_stick_right", "right_stick_down", "right_stick_left",
];

export const MODES = ["single", "repeat", "hold", "toggle"];
export const MOUSE_CODES = ["MouseLeft", "MouseRight", "MouseMiddle", "MouseBack", "MouseForward"];
export const SCROLL_CODES = ["ScrollUp", "ScrollDown", "ScrollLeft", "ScrollRight"];
export const ACTIONS = ["focus-terminal", "switch-to-app", "toggle-mouse-mode", "open-config-ui"];
export const EFFECTS = ["static", "breathe", "blink"];
export const STATUS_STATES = ["idle", "working", "approval", "error"];

export function clamp(value, low, high) {
  return Math.max(low, Math.min(high, Number(value)));
}

export function parseSequence(text) {
  return String(text || "")
    .split(";")
    .map((segment) => segment.split(",").map((code) => code.trim()).filter(Boolean))
    .filter((segment) => segment.length > 0);
}

export function formatSequence(sequence) {
  return (sequence || []).map((segment) => segment.join(", ")).join("; ");
}

export function hexToRgb(hex) {
  const value = String(hex || "").replace("#", "");
  if (value.length !== 6) return [0, 0, 0];
  return [0, 2, 4].map((offset) => parseInt(value.slice(offset, offset + 2), 16) || 0);
}

export function rgbToHex(rgb) {
  return "#" + (rgb || [0, 0, 0]).map((channel) => clamp(channel, 0, 255).toString(16).padStart(2, "0")).join("");
}

// Form -> mapping entry. Returns { entry } or { error }.
export function mappingEntryFromForm(form) {
  if (form.kind === "none") return { entry: null };
  const mode = form.mode;
  if (form.kind === "mouse") return { entry: { mode, mouse: form.mouse } };
  if (form.kind === "scroll") return { entry: { mode, scroll: form.scroll } };
  const sequence = parseSequence(form.sequenceText);
  if (sequence.length === 0) return { error: "sequence is empty" };
  const entry = { mode, sequence };
  if (mode === "repeat") {
    entry.repeat = { delayMs: clamp(form.repeatDelay, 10, 2000), intervalMs: clamp(form.repeatInterval, 10, 2000) };
  }
  if (mode === "toggle") entry.toggleInitial = form.toggleInitial === "on" ? "on" : "off";
  return { entry };
}

export function mappingSummary(entry, action) {
  if (action) return action.action;
  if (!entry) return "-";
  if (entry.mouse) return entry.mouse;
  if (entry.scroll) return entry.scroll;
  return (entry.sequence || []).map((segment) => segment.join("+")).join(" / ") || "-";
}

// Append a captured chord segment to a sequence text field.
export function appendKeys(text, codes, newSegment = false) {
  const joined = (codes || []).join(", ");
  if (!joined) return String(text || "");
  const current = String(text || "").trim();
  if (!current) return joined;
  if (newSegment) return `${current.replace(/;\s*$/, "")}; ${joined}`;
  return `${current}, ${joined}`;
}

export function appendKey(text, code, newSegment = false) {
  return appendKeys(text, [code], newSegment);
}

// Entry -> form fields for editing.
export function mappingFormFromEntry(entry) {
  const form = {
    kind: "sequence", mode: "single", sequenceText: "", mouse: MOUSE_CODES[0],
    scroll: SCROLL_CODES[0], repeatDelay: 300, repeatInterval: 50, toggleInitial: "off",
  };
  if (!entry) { form.kind = "none"; return form; }
  form.mode = entry.mode || "single";
  if (entry.mouse) { form.kind = "mouse"; form.mouse = entry.mouse; }
  else if (entry.scroll) { form.kind = "scroll"; form.scroll = entry.scroll; }
  else { form.kind = "sequence"; form.sequenceText = formatSequence(entry.sequence); }
  if (entry.repeat) { form.repeatDelay = entry.repeat.delayMs; form.repeatInterval = entry.repeat.intervalMs; }
  if (entry.toggleInitial) form.toggleInitial = entry.toggleInitial;
  return form;
}
