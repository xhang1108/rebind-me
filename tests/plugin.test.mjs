import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import {
  createEventMapper,
  eventProperties,
  isPermissionAsk,
  isPermissionReply,
  mapEvent,
  permissionAskStatus,
  questionToolStatus,
  sessionTitle,
  statusFor,
} from "../plugin/events.mjs";
import {
  baseUrl,
  readToken,
  reportSession,
  runtimeDir,
} from "../plugin/bridge.mjs";

test("package metadata points at the TypeScript entry", async () => {
  const pkg = JSON.parse(
    await readFile(new URL("../plugin/package.json", import.meta.url), "utf8"),
  );
  assert.equal(pkg.name, "rebind-me");
  assert.equal(pkg.main, "index.ts");
  assert.ok(pkg.files.includes("events.mjs"));
});

test("statusFor maps opencode statuses", () => {
  assert.equal(statusFor({ type: "busy" }), "working");
  assert.equal(statusFor({ type: "retry" }), "working");
  assert.equal(statusFor({ type: "idle" }), "idle");
  assert.equal(statusFor({ type: "unknown" }), null);
  assert.equal(statusFor("busy"), "working");
});

test("eventProperties falls back to data", () => {
  assert.deepEqual(eventProperties({ properties: { a: 1 } }), { a: 1 });
  assert.deepEqual(eventProperties({ data: { b: 2 } }), { b: 2 });
  assert.deepEqual(eventProperties(null), {});
});

test("mapEvent covers every documented event", () => {
  assert.deepEqual(mapEvent({ type: "session.status", properties: { sessionID: "s", status: { type: "busy" } } }),
    { sessionID: "s", status: "working" });
  assert.deepEqual(mapEvent({ type: "session.status", properties: { sessionID: "s", status: { type: "idle" } } }),
    { sessionID: "s", status: "idle" });
  assert.deepEqual(mapEvent({ type: "session.idle", properties: { sessionID: "s" } }),
    { sessionID: "s", status: "idle" });
  assert.deepEqual(mapEvent({ type: "permission.asked", properties: { sessionID: "s" } }),
    { sessionID: "s", status: "approval" });
  assert.deepEqual(mapEvent({ type: "permission.replied", properties: { sessionID: "s" } }),
    { sessionID: "s", status: "working" });
  assert.deepEqual(mapEvent({ type: "session.error", properties: { sessionID: "s" } }),
    { sessionID: "s", status: "error" });
  assert.deepEqual(mapEvent({ type: "session.deleted", properties: { sessionID: "s" } }),
    { sessionID: "s", deleted: true });
});

test("mapEvent ignores irrelevant or session-less events", () => {
  assert.equal(mapEvent({ type: "message.updated", properties: { sessionID: "s" } }), null);
  // session.updated fires for every info change (even after idle), never a status.
  assert.equal(mapEvent({ type: "session.updated", properties: { sessionID: "s" } }), null);
  assert.equal(mapEvent({ type: "session.idle", properties: {} }), null);
  assert.equal(mapEvent({ type: "session.deleted", properties: {} }), null);
  assert.equal(mapEvent(null), null);
});

test("permission ask/reply predicates", () => {
  assert.ok(isPermissionAsk({ type: "permission.asked" }));
  assert.ok(isPermissionAsk({ type: "permission.v2.asked" }));
  assert.ok(isPermissionReply({ type: "permission.replied" }));
  assert.ok(!isPermissionAsk({ type: "permission.replied" }));
  assert.ok(!isPermissionReply({ type: "session.idle" }));
});

test("mapper keeps approval sticky until the permission is answered", () => {
  const map = createEventMapper();
  const asked = { type: "permission.asked", properties: { sessionID: "s" } };
  assert.deepEqual(map(asked), { sessionID: "s", status: "approval" });

  // A busy/idle status while the prompt is open must not clear approval.
  assert.deepEqual(
    map({ type: "session.status", properties: { sessionID: "s", status: { type: "busy" } } }),
    { sessionID: "s", status: "approval" },
  );
  assert.deepEqual(map({ type: "session.idle", properties: { sessionID: "s" } }),
    { sessionID: "s", status: "approval" });

  // An error still wins over approval.
  assert.deepEqual(map({ type: "session.error", properties: { sessionID: "s" } }),
    { sessionID: "s", status: "error" });

  // Replying clears it; later statuses drive the light again.
  assert.deepEqual(map({ type: "permission.replied", properties: { sessionID: "s" } }),
    { sessionID: "s", status: "working" });
  assert.deepEqual(map({ type: "session.idle", properties: { sessionID: "s" } }),
    { sessionID: "s", status: "idle" });
});

test("the question tool reports approval for its whole run", () => {
  assert.equal(questionToolStatus("question", "before"), "approval");
  assert.equal(questionToolStatus("question", "after"), "working");
  assert.equal(questionToolStatus("bash", "before"), null);
  assert.equal(questionToolStatus("question", "sideways"), null);
});

test("only an 'ask' permission evaluation is an approval", () => {
  assert.equal(permissionAskStatus("ask"), "approval");
  assert.equal(permissionAskStatus("allow"), null);
  assert.equal(permissionAskStatus("deny"), null);
  assert.equal(permissionAskStatus(undefined), null);
});

test("mapper clears a pending approval when the session is deleted", () => {
  const map = createEventMapper();
  map({ type: "permission.asked", properties: { sessionID: "s" } });
  assert.deepEqual(map({ type: "session.deleted", properties: { sessionID: "s" } }),
    { sessionID: "s", deleted: true });
  assert.deepEqual(map({ type: "session.idle", properties: { sessionID: "s" } }),
    { sessionID: "s", status: "idle" });
});

test("sessionTitle reads info.title", () => {
  assert.equal(sessionTitle({ properties: { info: { title: "Fix bug" } } }), "Fix bug");
  assert.equal(sessionTitle({ properties: {} }), "");
});

test("runtimeDir and baseUrl honour the environment", () => {
  assert.equal(runtimeDir({ LOCALAPPDATA: "C:\\Users\\me\\AppData\\Local" }), "C:\\Users\\me\\AppData\\Local\\RebindMe");
  assert.equal(runtimeDir({}), "");
  assert.equal(baseUrl({}), "http://127.0.0.1:4173");
  assert.equal(baseUrl({ REBIND_ME_URL: "http://127.0.0.1:9000/" }), "http://127.0.0.1:9000");
});

test("readToken prefers the environment override", async () => {
  const token = await readToken({ env: { REBIND_ME_TOKEN: "env-token" } });
  assert.equal(token, "env-token");
});

test("readToken reads the token file", async () => {
  const token = await readToken({
    env: { LOCALAPPDATA: "C:\\data" },
    read: async () => "file-token\n",
  });
  assert.equal(token, "file-token");
});

test("readToken returns empty when unavailable", async () => {
  assert.equal(await readToken({ env: {} }), "");
  assert.equal(
    await readToken({ env: { LOCALAPPDATA: "C:\\data" }, read: async () => { throw new Error("nope"); } }),
    "",
  );
});

test("reportSession posts the session with the token", async () => {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, options });
    return { ok: true };
  };
  const session = { id: "s", status: "working", pid: 1, title: "t", lastActive: 2 };
  const ok = await reportSession(session, {
    env: { REBIND_ME_TOKEN: "tok" },
    fetchImpl,
  });
  assert.equal(ok, true);
  assert.equal(calls[0].url, "http://127.0.0.1:4173/api/sessions");
  assert.equal(calls[0].options.headers["X-Bridge-Token"], "tok");
  assert.deepEqual(JSON.parse(calls[0].options.body), session);
});

test("reportSession is silent without a token", async () => {
  let called = false;
  const ok = await reportSession({ id: "s" }, {
    env: {},
    fetchImpl: async () => { called = true; return { ok: true }; },
  });
  assert.equal(ok, false);
  assert.equal(called, false);
});

test("reportSession is silent on network errors", async () => {
  const ok = await reportSession({ id: "s" }, {
    env: { REBIND_ME_TOKEN: "tok" },
    fetchImpl: async () => { throw new Error("offline"); },
  });
  assert.equal(ok, false);
});
