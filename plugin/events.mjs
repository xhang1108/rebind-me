// Pure mapping from OpenCode 2 events to bridge session state.
//
// The OpenCode 2 public stream carries raw events with a `data` object. The
// bridge understands four statuses: "idle", "working", "approval", "error".

/**
 * @typedef {object} MappedEvent
 * @property {string} sessionID
 * @property {string} [status] bridge status; absent for metadata-only events
 * @property {boolean} [deleted] true removes the session instead of upserting
 */

const asRecord = (value) =>
  value !== null && typeof value === "object" && !Array.isArray(value) ? value : {};

const trimmed = (value) => (typeof value === "string" ? value.trim() : "");

/** Return the canonical OpenCode 2 event data object. */
export function eventData(event) {
  return asRecord(asRecord(event).data);
}

// Kept as a small compatibility alias for callers that used the old helper;
// the plugin itself consumes only the V2 `data` shape.
export function eventProperties(event) {
  return eventData(event);
}

function sessionID(event, data = eventData(event)) {
  const type = event?.type;
  if (type === "form.created") return trimmed(asRecord(data.form).sessionID);
  return trimmed(data.sessionID);
}

function requestID(event, kind, data = eventData(event)) {
  if (kind === "permission") {
    return trimmed(data.requestID) || trimmed(data.id);
  }
  if (kind === "form") {
    if (event?.type === "form.created") return trimmed(asRecord(data.form).id);
    return trimmed(data.id) || trimmed(data.requestID);
  }
  return "";
}

/** Map an OpenCode session status to a bridge status. */
export function statusFor(status) {
  const type = typeof status === "string" ? status : asRecord(status).type;
  switch (type) {
    case "busy":
    case "retry":
    case "working":
    case "running":
      return "working";
    case "idle":
      return "idle";
    default:
      return null;
  }
}

const withSession = (id, status) => ({ sessionID: id, status });

/**
 * Translate one raw OpenCode 2 event into a bridge update.
 *
 * This function is intentionally stateless. `createEventMapper()` layers the
 * per-session phase and pending-request state on top of it.
 *
 * @param {any} event
 * @returns {MappedEvent | null}
 */
export function mapEvent(event) {
  const type = event?.type;
  const data = eventData(event);
  const id = sessionID(event, data);
  if (!id) return null;

  switch (type) {
    case "session.execution.started":
      return withSession(id, "working");
    case "session.execution.succeeded":
      return withSession(id, "idle");
    case "session.execution.interrupted":
      // OpenCode keeps the execution claim across a shutdown. The resumed
      // drain will emit the real terminal outcome after restart.
      return trimmed(data.reason) === "shutdown" ? null : withSession(id, "idle");
    case "session.execution.failed":
      return withSession(id, "error");

    // These two are retained as defensive fallbacks for V2 servers that emit
    // the legacy status events alongside execution events.
    case "session.status": {
      const status = statusFor(data.status);
      return status ? withSession(id, status) : null;
    }
    case "session.idle":
      return withSession(id, "idle");

    case "permission.asked":
      return requestID(event, "permission", data) ? withSession(id, "approval") : null;
    case "permission.replied":
      return requestID(event, "permission", data) ? withSession(id, "working") : null;

    case "form.created":
      return requestID(event, "form", data) ? withSession(id, "approval") : null;
    case "form.replied":
    case "form.cancelled":
      return requestID(event, "form", data) ? withSession(id, "working") : null;

    // Keep a defensive V2 error alias for servers that publish the translated
    // name directly. The normal V2 source is session.execution.failed.
    case "session.error":
      return withSession(id, "error");

    case "session.deleted":
      return { sessionID: id, deleted: true };

    case "session.created":
    case "session.renamed":
      // Metadata only. The adapter stores the title and deliberately does not
      // send an empty status that could erase the current light state.
      return { sessionID: id };

    default:
      return null;
  }
}

const PERMISSION_ASK = new Set(["permission.asked"]);
const PERMISSION_REPLY = new Set(["permission.replied"]);
const FORM_ASK = new Set(["form.created"]);
const FORM_REPLY = new Set(["form.replied", "form.cancelled"]);

/** True for the event that opens a pending permission request. */
export function isPermissionAsk(event) {
  return PERMISSION_ASK.has(event?.type);
}

/** True for the event that resolves a pending permission request. */
export function isPermissionReply(event) {
  return PERMISSION_REPLY.has(event?.type);
}

/** True for the event that opens a pending form request. */
export function isFormAsk(event) {
  return FORM_ASK.has(event?.type);
}

/** True for the event that resolves a pending form request. */
export function isFormReply(event) {
  return FORM_REPLY.has(event?.type);
}

/**
 * Add the per-session state machine around the pure V2 event mapping.
 *
 * `phase` represents execution state; `pending` contains namespaced request
 * IDs so multiple permission/form prompts can be outstanding at once.
 */
export function createEventMapper() {
  const sessions = new Map();

  const getSession = (id) => {
    let state = sessions.get(id);
    if (!state) {
      state = { phase: "idle", pending: new Set() };
      sessions.set(id, state);
    }
    return state;
  };

  const resolvedStatus = (state) => {
    if (state.phase === "error") return "error";
    if (state.pending.size > 0) return "approval";
    return state.phase;
  };

  return function map(event) {
    const mapped = mapEvent(event);
    if (!mapped?.sessionID) return null;

    const id = mapped.sessionID;
    if (mapped.deleted) {
      sessions.delete(id);
      return mapped;
    }

    // A title event has no status and must not create execution state.
    if (mapped.status === undefined) return mapped;

    const state = getSession(id);
    const type = event?.type;
    const data = eventData(event);

    switch (type) {
      case "session.execution.started":
        state.phase = "working";
        break;
      case "session.status":
        // Defensive status/idle events must not erase a V2 execution error;
        // only a new execution terminal event or start may recover from it.
        if (state.phase !== "error") {
          state.phase = mapped.status === "working" ? "working" : "idle";
        }
        break;
      case "session.execution.succeeded":
      case "session.execution.interrupted":
        state.phase = "idle";
        break;
      case "session.idle":
        if (state.phase !== "error") state.phase = "idle";
        break;
      case "session.execution.failed":
      case "session.error":
        state.phase = "error";
        break;
      case "permission.asked":
        state.pending.add(`permission:${requestID(event, "permission", data)}`);
        break;
      case "permission.replied":
        state.pending.delete(`permission:${requestID(event, "permission", data)}`);
        break;
      case "form.created":
        state.pending.add(`form:${requestID(event, "form", data)}`);
        break;
      case "form.replied":
      case "form.cancelled":
        state.pending.delete(`form:${requestID(event, "form", data)}`);
        break;
      default:
        break;
    }

    return { ...mapped, status: resolvedStatus(state) };
  };
}

/** Best-effort session title carried by a V2 event, if any. */
export function sessionTitle(event) {
  const data = eventData(event);
  return trimmed(data.title) || trimmed(asRecord(data.info).title);
}
