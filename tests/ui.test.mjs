import assert from "node:assert/strict";
import { test } from "node:test";

import {
  INPUT_NAMES, MOUSE_CODES, SCROLL_CODES,
  appendKey, appendKeys, clamp, formatSequence, hexToRgb, mappingEntryFromForm,
  mappingFormFromEntry, mappingSummary, parseSequence, rgbToHex, stickOffset,
} from "../src/rebind_me/ui/model.js";

test("input names match the bridge contract", () => {
  assert.equal(INPUT_NAMES.length, 27);
  assert.equal(new Set(INPUT_NAMES).size, 27);
  assert.ok(INPUT_NAMES.includes("cross"));
  assert.ok(INPUT_NAMES.includes("right_stick_up"));
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

test("append captured key", () => {
  assert.equal(appendKey("", "KeyK"), "KeyK");
  assert.equal(appendKey("ControlLeft", "KeyK"), "ControlLeft, KeyK");
  assert.equal(appendKey("ControlLeft, KeyK", "KeyL", true), "ControlLeft, KeyK; KeyL");
  assert.equal(appendKey("", "KeyL", true), "KeyL");
});

test("append captured chord segment", () => {
  assert.equal(appendKeys("", ["ControlLeft", "Tab"]), "ControlLeft, Tab");
  assert.equal(appendKeys("KeyK", ["ControlLeft", "Tab"]), "KeyK, ControlLeft, Tab");
  assert.equal(appendKeys("KeyK", ["ControlLeft", "Tab"], true), "KeyK; ControlLeft, Tab");
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
