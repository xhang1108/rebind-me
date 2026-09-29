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
// How the gap between two repeat fires is picked. "fixed" always waits
// intervalMs; "random" waits a fresh value inside the min/max window.
export const REPEAT_TIMINGS = ["fixed", "random"];
export const REPEAT_MIN_MS = 10;
export const REPEAT_MAX_MS = 2000;
// Mirrors store.DEFAULT_REPEAT plus a +/-20% random window, so the editor
// opens on the same unhurried cadence the store would fall back to.
export const DEFAULT_REPEAT_DELAY_MS = 1000;
export const DEFAULT_REPEAT_INTERVAL_MS = 1000;
export const DEFAULT_REPEAT_MIN_MS = 800;
export const DEFAULT_REPEAT_MAX_MS = 1200;
export const MAX_CHORD_SEGMENTS = 2;
export const MOUSE_CODES = ["MouseLeft", "MouseRight", "MouseMiddle", "MouseBack", "MouseForward"];
export const SCROLL_CODES = ["ScrollUp", "ScrollDown", "ScrollLeft", "ScrollRight"];
export const ACTIONS = ["focus-terminal", "switch-to-app", "toggle-mouse-mode", "open-config-ui", "webhook"];
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
  const entry = { mode };
  if (form.kind === "mouse") entry.mouse = form.mouse;
  else if (form.kind === "scroll") entry.scroll = form.scroll;
  else {
    const sequence = parseSequence(form.sequenceText);
    if (sequence.length === 0) return { error: "sequence is empty" };
    entry.sequence = sequence;
  }
  if (mode === "repeat") entry.repeat = repeatFromForm(form);

  if (mode === "toggle") entry.toggleInitial = form.toggleInitial === "on" ? "on" : "off";
  return { entry };
}

// Repeat timings apply to every output kind, so a mouse mapping can auto-click
// just like a key sequence. The window is ordered here so the editor can never
// hand the store a minMs larger than maxMs.
function repeatFromForm(form) {
  const repeat = {
    delayMs: clamp(form.repeatDelay, REPEAT_MIN_MS, REPEAT_MAX_MS),
    intervalMs: clamp(form.repeatInterval, REPEAT_MIN_MS, REPEAT_MAX_MS),
  };
  if (form.repeatTiming === "random") {
    const low = clamp(form.repeatMin, REPEAT_MIN_MS, REPEAT_MAX_MS);
    const high = clamp(form.repeatMax, REPEAT_MIN_MS, REPEAT_MAX_MS);
    repeat.random = { minMs: Math.min(low, high), maxMs: Math.max(low, high) };
  }
  // Opt-in only: the key is left out entirely when off, so a stored mapping
  // keeps meaning "repeat while held" without anyone having to set it.
  if (form.repeatLatch) repeat.latch = true;
  return repeat;
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
    scroll: SCROLL_CODES[0],
    repeatDelay: DEFAULT_REPEAT_DELAY_MS, repeatInterval: DEFAULT_REPEAT_INTERVAL_MS,
    repeatTiming: "fixed", repeatMin: DEFAULT_REPEAT_MIN_MS,
    repeatMax: DEFAULT_REPEAT_MAX_MS, repeatLatch: false, toggleInitial: "off",
  };
  if (!entry) { form.kind = "none"; return form; }
  form.mode = entry.mode || "single";
  if (entry.mouse) { form.kind = "mouse"; form.mouse = entry.mouse; }
  else if (entry.scroll) { form.kind = "scroll"; form.scroll = entry.scroll; }
  else { form.kind = "sequence"; form.sequenceText = formatSequence(entry.sequence); }
  if (entry.repeat) {
    form.repeatDelay = entry.repeat.delayMs;
    form.repeatInterval = entry.repeat.intervalMs;
    form.repeatLatch = !!entry.repeat.latch;
    if (entry.repeat.random) {
      form.repeatTiming = "random";
      form.repeatMin = entry.repeat.random.minMs;
      form.repeatMax = entry.repeat.random.maxMs;
    }
  }
  if (entry.toggleInitial) form.toggleInitial = entry.toggleInitial;
  return form;
}
