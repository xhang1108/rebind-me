import assert from "node:assert/strict";
import { test } from "node:test";

import RebindMe, { name } from "../plugin/index.js";

test("plugin exposes its package name", () => {
  assert.equal(name, "@xhang98/rebind-me");
});

test("plugin default export is a factory", () => {
  assert.equal(typeof RebindMe, "function");
});
