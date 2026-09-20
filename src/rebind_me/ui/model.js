// Pure UI model helpers (no DOM), shared with node --test.

export const INPUT_NAMES = [
  "square", "cross", "circle", "triangle",
  "dpad_up", "dpad_right", "dpad_down", "dpad_left",
  "l1", "r1", "l2", "r2", "create", "options", "l3", "r3",
  "ps", "touchpad", "mute",
  "left_stick_up", "left_stick_right", "left_stick_down", "left_stick_left",
  "right_stick_up", "right_stick_right", "right_stick_down", "right_stick_left",
];

// Touchpad tap / click zones. The bridge drives these from touch gestures but
// they are ordinary mapping targets, so the Touchpad tab edits them with the
// same editor as the Mappings tab.
export const TOUCHPAD_ZONE_INPUTS = [
  "touchpad_tap_left", "touchpad_tap_right",
  "touchpad_click_left", "touchpad_click_right",
];

// Grouped for the Mappings list. The union of the groups is exactly
// INPUT_NAMES, including `touchpad`; the test enforces that so neither list
// can drift away from the other or from the bridge's input contract.
export const INPUT_GROUPS = [
  ["Face", ["square", "cross", "circle", "triangle"]],
  ["D-pad", ["dpad_up", "dpad_right", "dpad_down", "dpad_left"]],
  ["Shoulders", ["l1", "r1", "l2", "r2"]],
  ["Sticks", [
    "l3", "r3",
    "left_stick_up", "left_stick_right", "left_stick_down", "left_stick_left",
    "right_stick_up", "right_stick_right", "right_stick_down", "right_stick_left",
  ]],
  ["System", ["create", "options", "ps", "touchpad", "mute"]],
];

export const MODES = ["single", "repeat", "hold", "toggle"];
export const MAX_CHORD_SEGMENTS = 2;
export const MOUSE_CODES = ["MouseLeft", "MouseRight", "MouseMiddle", "MouseBack", "MouseForward"];
export const SCROLL_CODES = ["ScrollUp", "ScrollDown", "ScrollLeft", "ScrollRight"];
export const ACTIONS = ["focus-terminal", "switch-to-app", "toggle-mouse-mode", "open-config-ui"];
export const EFFECTS = ["static", "breathe", "blink"];
export const STATUS_STATES = ["idle", "working", "approval", "error"];
export const MAX_PRESET_NAME = 40;

export function clamp(value, low, high) {
  return Math.max(low, Math.min(high, Number(value)));
}

export function stickOffset(x, y, max = 1.6) {
  return [clamp(x, -1, 1) * max, clamp(y, -1, 1) * max];
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

// Stable string for comparing a live mapping document with a saved preset.
// Keys are sorted so object insertion order never affects the comparison.
function sortedValue(value) {
  if (Array.isArray(value)) return value.map(sortedValue);
  if (value && typeof value === "object") {
    return Object.keys(value).sort().reduce((acc, key) => {
      acc[key] = sortedValue(value[key]);
      return acc;
    }, {});
  }
  return value;
}

export function mappingSignature(document) {
  if (!document) return "";
  return JSON.stringify(sortedValue({
    enabled: document.enabled !== false,
    mappings: document.mappings || {},
    actions: document.actions || {},
    touchpad: document.touchpad || {},
  }));
}

// Replace the segment at ``index`` with ``keys``, or append it when the index
// is at (or past) the end. Returns a new sequence; never mutates the input.
export function setSegment(sequence, index, keys) {
  const next = (sequence || []).map((segment) => [...segment]);
  const segment = [...(keys || [])];
  if (segment.length === 0) return next;
  if (index >= next.length) next.push(segment);
  else next[index] = segment;
  return next.slice(0, MAX_CHORD_SEGMENTS);
}

// Drop the segment at ``index``. Returns a new sequence.
export function removeSegment(sequence, index) {
  return (sequence || []).filter((_, position) => position !== index);
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
