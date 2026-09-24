import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";

import {
  createEventMapper,
  eventData,
  eventProperties,
  isFormAsk,
  isFormReply,
  isPermissionAsk,
  isPermissionReply,
  mapEvent,
  sessionTitle,
  statusFor,
} from "../plugin/events.mjs";
import {
  baseUrl,
  readToken,
  reportSession,
  runtimeDir,
} from "../plugin/bridge.mjs";

const execution = (type, data = {}) => ({
  type,
  data: { sessionID: "s", ...data },
});

test("package metadata targets the OpenCode 2 plugin API", async () => {
  const pkg = JSON.parse(
    await readFile(new URL("../plugin/package.json", import.meta.url), "utf8"),
  );
  assert.equal(pkg.name, "rebind-me");
  assert.equal(pkg.version, "0.2.0");
  assert.equal(pkg.main, "index.ts");
  assert.equal(pkg.devDependencies["@opencode/plugin"], "2.0.15");
  assert.equal(pkg.devDependencies["@opencode-ai/plugin"], undefined);
  assert.ok(pkg.files.includes("events.mjs"));
});

test("eventData reads the OpenCode 2 data shape safely", () => {
  assert.deepEqual(eventData({ data: { sessionID: "s" } }), { sessionID: "s" });
  assert.deepEqual(eventProperties({ data: { sessionID: "s" } }), { sessionID: "s" });
  assert.deepEqual(eventData(null), {});
  assert.deepEqual(eventData({ data: [] }), {});
});

test("statusFor maps V2 status values", () => {
  assert.equal(statusFor({ type: "busy" }), "working");
  assert.equal(statusFor({ type: "retry" }), "working");
  assert.equal(statusFor({ type: "working" }), "working");
  assert.equal(statusFor({ type: "idle" }), "idle");
  assert.equal(statusFor({ type: "unknown" }), null);
  assert.equal(statusFor("busy"), "working");
});

test("mapEvent covers the OpenCode 2 execution lifecycle", () => {
  assert.deepEqual(mapEvent(execution("session.execution.started")), {
    sessionID: "s",
    status: "working",
  });
  assert.deepEqual(mapEvent(execution("session.execution.succeeded")), {
    sessionID: "s",
    status: "idle",
  });
  assert.deepEqual(mapEvent(execution("session.execution.interrupted", { reason: "user" })), {
    sessionID: "s",
    status: "idle",
  });
  assert.equal(
    mapEvent(execution("session.execution.interrupted", { reason: "shutdown" })),
    null,
  );
  assert.deepEqual(mapEvent(execution("session.execution.failed", { error: { message: "boom" } })), {
    sessionID: "s",
    status: "error",
  });
});

test("mapEvent covers V2 fallback status and metadata events", () => {
  assert.deepEqual(mapEvent({
    type: "session.status",
    data: { sessionID: "s", status: { type: "busy" } },
  }), { sessionID: "s", status: "working" });
  assert.deepEqual(mapEvent(execution("session.idle")), { sessionID: "s", status: "idle" });
  assert.deepEqual(mapEvent({ type: "session.created", data: { sessionID: "s", title: "Fix" } }), {
    sessionID: "s",
  });
  assert.deepEqual(mapEvent({ type: "session.renamed", data: { sessionID: "s", title: "Renamed" } }), {
    sessionID: "s",
  });
  assert.deepEqual(mapEvent(execution("session.deleted")), { sessionID: "s", deleted: true });
});

test("mapEvent covers V2 permission and form requests", () => {
  assert.deepEqual(mapEvent({
    type: "permission.asked",
    data: { id: "p1", sessionID: "s", action: "bash" },
  }), { sessionID: "s", status: "approval" });
  assert.deepEqual(mapEvent({
    type: "permission.replied",
    data: { requestID: "p1", sessionID: "s" },
  }), { sessionID: "s", status: "working" });

  assert.deepEqual(mapEvent({
    type: "form.created",
    data: { form: { id: "f1", sessionID: "s", title: "Pick" } },
  }), { sessionID: "s", status: "approval" });
  assert.deepEqual(mapEvent({
    type: "form.replied",
    data: { id: "f1", sessionID: "s" },
  }), { sessionID: "s", status: "working" });
  assert.deepEqual(mapEvent({
    type: "form.cancelled",
    data: { id: "f1", sessionID: "s" },
  }), { sessionID: "s", status: "working" });
});

test("mapEvent ignores irrelevant, malformed, and ID-less events", () => {
  assert.equal(mapEvent({ type: "message.updated", data: { sessionID: "s" } }), null);
  assert.equal(mapEvent({ type: "session.updated", data: { sessionID: "s" } }), null);
  assert.equal(mapEvent({ type: "permission.asked", data: { sessionID: "s" } }), null);
  assert.equal(mapEvent({ type: "form.created", data: { form: { sessionID: "s" } } }), null);
  assert.equal(mapEvent({ type: "session.execution.started", data: {} }), null);
  assert.equal(mapEvent(null), null);
});

test("permission and form predicates recognize only V2 request events", () => {
  assert.ok(isPermissionAsk({ type: "permission.asked" }));
  assert.ok(isPermissionReply({ type: "permission.replied" }));
  assert.ok(isFormAsk({ type: "form.created" }));
  assert.ok(isFormReply({ type: "form.replied" }));
  assert.ok(isFormReply({ type: "form.cancelled" }));
  assert.ok(!isPermissionAsk({ type: "permission.replied" }));
  assert.ok(!isPermissionReply({ type: "permission.v2.replied" }));
  assert.ok(!isFormAsk({ type: "form.replied" }));
});

test("mapper keeps execution state and approval sticky until requests settle", () => {
  const map = createEventMapper();
  assert.deepEqual(map(execution("session.execution.started")), {
    sessionID: "s",
    status: "working",
  });
  assert.deepEqual(map({
    type: "permission.asked",
    data: { id: "p1", sessionID: "s" },
  }), { sessionID: "s", status: "approval" });

  // A terminal execution event must not clear an outstanding request.
  assert.deepEqual(map(execution("session.execution.succeeded")), {
    sessionID: "s",
    status: "approval",
  });
  assert.deepEqual(map({
    type: "permission.replied",
    data: { requestID: "p1", sessionID: "s" },
  }), { sessionID: "s", status: "idle" });
});

test("mapper keeps approval while multiple requests remain", () => {
  const map = createEventMapper();
  map(execution("session.execution.started"));
  map({ type: "permission.asked", data: { id: "p1", sessionID: "s" } });
  map({ type: "permission.asked", data: { id: "p2", sessionID: "s" } });
  assert.deepEqual(map({
    type: "permission.replied",
    data: { requestID: "p1", sessionID: "s" },
  }), { sessionID: "s", status: "approval" });
  assert.deepEqual(map({
    type: "permission.replied",
    data: { requestID: "p2", sessionID: "s" },
  }), { sessionID: "s", status: "working" });
});

test("mapper handles nested form lifecycle and multiple request types", () => {
  const map = createEventMapper();
  map(execution("session.execution.started"));
  map({ type: "form.created", data: { form: { id: "f1", sessionID: "s" } } });
  map({ type: "permission.asked", data: { id: "p1", sessionID: "s" } });
  assert.deepEqual(map({
    type: "form.cancelled",
    data: { id: "f1", sessionID: "s" },
  }), { sessionID: "s", status: "approval" });
  assert.deepEqual(map({
    type: "permission.replied",
    data: { requestID: "p1", sessionID: "s" },
  }), { sessionID: "s", status: "working" });
});

test("shutdown interruption leaves the working phase untouched", () => {
  const map = createEventMapper();
  assert.deepEqual(map(execution("session.execution.started")), {
    sessionID: "s",
    status: "working",
  });
  assert.equal(map(execution("session.execution.interrupted", { reason: "shutdown" })), null);
  assert.deepEqual(map(execution("session.execution.succeeded")), {
    sessionID: "s",
    status: "idle",
  });
});

test("error wins over approval until a new execution starts", () => {
  const map = createEventMapper();
  map(execution("session.execution.started"));
  map({ type: "permission.asked", data: { id: "p1", sessionID: "s" } });
  assert.deepEqual(map(execution("session.execution.failed")), {
    sessionID: "s",
    status: "error",
  });
  assert.deepEqual(map({
    type: "permission.replied",
    data: { requestID: "p1", sessionID: "s" },
  }), { sessionID: "s", status: "error" });
  assert.deepEqual(map(execution("session.execution.started")), {
    sessionID: "s",
    status: "working",
  });
});

test("defensive status events do not clear a V2 execution error", () => {
  const map = createEventMapper();
  map(execution("session.execution.started"));
  assert.deepEqual(map(execution("session.execution.failed")), {
    sessionID: "s",
    status: "error",
  });
  assert.deepEqual(map({
    type: "session.status",
    data: { sessionID: "s", status: "busy" },
  }), { sessionID: "s", status: "error" });
  assert.deepEqual(map(execution("session.idle")), {
    sessionID: "s",
    status: "error",
  });
  assert.deepEqual(map(execution("session.execution.started")), {
    sessionID: "s",
    status: "working",
  });
});

test("mapper clears pending state when a session is deleted", () => {
  const map = createEventMapper();
  map(execution("session.execution.started"));
  map({ type: "permission.asked", data: { id: "p1", sessionID: "s" } });
  assert.deepEqual(map(execution("session.deleted")), { sessionID: "s", deleted: true });
  assert.deepEqual(map(execution("session.execution.started")), {
    sessionID: "s",
    status: "working",
  });
});

test("sessionTitle reads V2 title fields", () => {
  assert.equal(sessionTitle({ data: { title: "Fix bug" } }), "Fix bug");
  assert.equal(sessionTitle({ data: { info: { title: "Nested" } } }), "Nested");
  assert.equal(sessionTitle({ data: {} }), "");
});

test("runtimeDir and baseUrl honour the environment", () => {
  assert.equal(runtimeDir({ LOCALAPPDATA: "C:\\Users\\me\\AppData\\Local" }), "C:\\Users\\me\\AppData\\Local\\RebindMe");
  assert.equal(runtimeDir({}), "");
  assert.equal(baseUrl({}), "http://127.0.0.1:4173");
  assert.equal(baseUrl({ REBIND_ME_URL: "http://127.0.0.1:9000/" }), "http://127.0.0.1:9000");
});

test("readToken prefers the environment override", async () => {
  assert.equal(await readToken({ env: { REBIND_ME_TOKEN: "env-token" } }), "env-token");
});

test("readToken reads the token file", async () => {
  assert.equal(
    await readToken({
      env: { LOCALAPPDATA: "C:\\data" },
      read: async () => "file-token\n",
    }),
    "file-token",
  );
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

test("reportSession is silent on network and HTTP errors", async () => {
  assert.equal(await reportSession({ id: "s" }, {
    env: { REBIND_ME_TOKEN: "tok" },
    fetchImpl: async () => { throw new Error("offline"); },
  }), false);
  assert.equal(await reportSession({ id: "s" }, {
    env: { REBIND_ME_TOKEN: "tok" },
    fetchImpl: async () => ({ ok: false }),
  }), false);
});
