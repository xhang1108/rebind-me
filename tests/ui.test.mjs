import assert from "node:assert/strict";
import { test } from "node:test";

import {
  INPUT_GROUPS, INPUT_NAMES, MAX_CHORD_SEGMENTS, MOUSE_CODES, SCROLL_CODES, TOUCHPAD_ZONE_INPUTS,
  clamp, formatSequence, hexToRgb, mappingEntryFromForm,
  mappingFormFromEntry, mappingSignature, mappingSummary, parseSequence, removeSegment, rgbToHex,
  setSegment, stickOffset,
} from "../src/rebind_me/ui/model.js";

test("input names match the bridge contract", () => {
  assert.equal(INPUT_NAMES.length, 27);
  assert.equal(new Set(INPUT_NAMES).size, 27);
  assert.ok(INPUT_NAMES.includes("cross"));
  assert.ok(INPUT_NAMES.includes("right_stick_up"));
  assert.ok(INPUT_NAMES.includes("touchpad"));
});

test("mapping groups cover every input exactly once", () => {
  const flat = INPUT_GROUPS.flatMap(([, inputs]) => inputs);
  assert.equal(flat.length, INPUT_NAMES.length);
  assert.equal(new Set(flat).size, INPUT_NAMES.length);
  assert.deepEqual([...flat].sort(), [...INPUT_NAMES].sort());
});

test("touchpad zones are mapping targets", () => {
  assert.deepEqual(TOUCHPAD_ZONE_INPUTS, [
    "touchpad_tap_left", "touchpad_tap_right",
    "touchpad_click_left", "touchpad_click_right",
  ]);
  for (const zone of TOUCHPAD_ZONE_INPUTS) {
    assert.ok(!INPUT_NAMES.includes(zone));
  }
});

test("sequence parse/format round trip", () => {
  const text = "ControlLeft, KeyK; KeyL";
  assert.deepEqual(parseSequence(text), [["ControlLeft", "KeyK"], ["KeyL"]]);
  assert.equal(formatSequence(parseSequence(text)), text);
});

test("empty sequence is rejected", () => {
  const result = mappingEntryFromForm({ kind: "sequence", mode: "single", sequenceText: " , ; " });
  assert.ok(result.error);
});

test("mapping serialization by mode", () => {
  assert.deepEqual(
    mappingEntryFromForm({ kind: "sequence", mode: "single", sequenceText: "KeyK" }),
    { entry: { mode: "single", sequence: [["KeyK"]] } },
  );
  assert.deepEqual(
    mappingEntryFromForm({ kind: "mouse", mode: "hold", mouse: "MouseLeft" }),
    { entry: { mode: "hold", mouse: "MouseLeft" } },
  );
  assert.deepEqual(
    mappingEntryFromForm({ kind: "scroll", mode: "single", scroll: "ScrollUp" }),
    { entry: { mode: "single", scroll: "ScrollUp" } },
  );
  const repeat = mappingEntryFromForm({
    kind: "sequence", mode: "repeat", sequenceText: "Delete", repeatDelay: 300, repeatInterval: 50,
  });
  assert.deepEqual(repeat.entry.repeat, { delayMs: 300, intervalMs: 50 });
  const toggle = mappingEntryFromForm({
    kind: "sequence", mode: "toggle", sequenceText: "ControlLeft", toggleInitial: "on",
  });
  assert.equal(toggle.entry.toggleInitial, "on");
  assert.equal(mappingEntryFromForm({ kind: "none" }).entry, null);
});

test("mapping form round trip", () => {
  const entry = { mode: "single", sequence: [["ControlLeft", "KeyK"], ["KeyL"]] };
  const form = mappingFormFromEntry(entry);
  const rebuilt = mappingEntryFromForm(form);
  assert.deepEqual(rebuilt.entry, entry);
});

test("clamp and colour helpers", () => {
  assert.equal(clamp(500, 0, 255), 255);
  assert.equal(clamp(-5, 0, 255), 0);
  assert.deepEqual(hexToRgb("#00ff00"), [0, 255, 0]);
  assert.equal(rgbToHex([0, 255, 0]), "#00ff00");
  assert.equal(rgbToHex(hexToRgb("#4c8bf5")), "#4c8bf5");
});

test("mapping summary", () => {
  assert.equal(mappingSummary(null, null), "-");
  assert.equal(mappingSummary({ sequence: [["ControlLeft", "KeyK"], ["KeyL"]] }, null), "ControlLeft+KeyK / KeyL");
  assert.equal(mappingSummary({ mouse: "MouseLeft" }, null), "MouseLeft");
  assert.equal(mappingSummary(null, { action: "focus-terminal" }), "focus-terminal");
});

test("mapping signature ignores key order and unrelated fields", () => {
  const preset = {
    enabled: true,
    mappings: { cross: { mode: "single", sequence: [["Enter"]] }, circle: { mode: "single", sequence: [["Backspace"]] } },
    actions: { triangle: { action: "switch-to-app", params: { process: "OpenChamber" } } },
    touchpad: { mouseControl: true, sensitivity: 1.0 },
  };
  const live = {
    version: 1,
    baseVersion: 7,
    mappings: { circle: { mode: "single", sequence: [["Backspace"]] }, cross: { mode: "single", sequence: [["Enter"]] } },
    actions: { triangle: { action: "switch-to-app", params: { process: "OpenChamber" } } },
    touchpad: { sensitivity: 1.0, mouseControl: true },
    enabled: true,
  };
  assert.equal(mappingSignature(preset), mappingSignature(live));

  const changed = { ...live, mappings: { ...live.mappings, cross: { mode: "single", sequence: [["KeyK"]] } } };
  assert.notEqual(mappingSignature(preset), mappingSignature(changed));
});

test("mapping signature treats a missing enabled flag as enabled", () => {
  assert.equal(
    mappingSignature({ mappings: {}, actions: {}, touchpad: {} }),
    mappingSignature({ enabled: true, mappings: {}, actions: {}, touchpad: {} }),
  );
  assert.notEqual(
    mappingSignature({ enabled: false, mappings: {}, actions: {}, touchpad: {} }),
    mappingSignature({ enabled: true, mappings: {}, actions: {}, touchpad: {} }),
  );
  assert.equal(mappingSignature(null), "");
});

test("replace a chord segment", () => {
  const base = [["ControlLeft", "KeyK"]];
  assert.deepEqual(setSegment(base, 0, ["KeyJ"]), [["KeyJ"]]);
  assert.deepEqual(base, [["ControlLeft", "KeyK"]]);
});

test("append a chord segment", () => {
  const base = [["KeyK"]];
  assert.deepEqual(setSegment(base, 1, ["KeyL"]), [["KeyK"], ["KeyL"]]);
  assert.deepEqual(setSegment(base, 99, ["KeyL"]), [["KeyK"], ["KeyL"]]);
});

test("set segment ignores an empty capture and caps at the max", () => {
  assert.deepEqual(setSegment([["KeyK"]], 0, []), [["KeyK"]]);
  const full = [["KeyA"], ["KeyB"]];
  assert.equal(MAX_CHORD_SEGMENTS, 2);
  assert.deepEqual(setSegment(full, 2, ["KeyC"]), full);
});

test("remove a chord segment", () => {
  assert.deepEqual(removeSegment([["KeyA"], ["KeyB"]], 0), [["KeyB"]]);
  assert.deepEqual(removeSegment([["KeyA"], ["KeyB"]], 1), [["KeyA"]]);
  assert.deepEqual(removeSegment([["KeyA"]], 5), [["KeyA"]]);
});

test("stick offset scales and clamps", () => {
  assert.deepEqual(stickOffset(0, 0), [0, 0]);
  assert.deepEqual(stickOffset(1, -1, 2), [2, -2]);
  assert.deepEqual(stickOffset(2, 2, 2), [2, 2]);
  assert.deepEqual(stickOffset(-5, 0.5, 2), [-2, 1]);
});

test("code lists are non-empty", () => {
  assert.ok(MOUSE_CODES.length >= 3);
  assert.ok(SCROLL_CODES.includes("ScrollUp"));
});
