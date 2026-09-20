// Pure mapping from opencode plugin events to bridge session status.
//
// Kept as plain ESM so it can be unit-tested with `node --test`, while the
// typed hook adapter lives in index.ts.
//
// The bridge understands four statuses: "idle", "working", "approval", "error".

/**
 * @typedef {object} MappedEvent
 * @property {string} sessionID
 * @property {string} [status]  bridge status; absent when `deleted`
 * @property {boolean} [deleted]  true removes the session instead of upserting
 */

/** Event object properties, tolerating both `properties` and older `data`. */
export function eventProperties(event) {
  if (!event || typeof event !== "object") return {};
  return event.properties ?? event.data ?? {};
}

/** Map an opencode session status to a bridge status (or null to ignore). */
export function statusFor(status) {
  const type = typeof status === "string" ? status : status?.type;
  switch (type) {
    case "busy":
    case "retry":
      return "working";
    case "idle":
      return "idle";
    default:
      return null;
  }
}

/**
 * Translate an opencode event into `{ sessionID, status }`, or `null` when the
 * event is irrelevant. Unknown events are silently ignored.
 *
 * @param {any} event
 * @returns {MappedEvent | null}
 */
export function mapEvent(event) {
  const type = event?.type;
  const props = eventProperties(event);
  const withSession = (status) =>
    props.sessionID ? { sessionID: props.sessionID, status } : null;

  switch (type) {
    case "session.status": {
      const status = statusFor(props.status);
      return status ? withSession(status) : null;
    }
    case "session.idle":
      return withSession("idle");
    // NOTE: `session.updated` is deliberately ignored. opencode emits it for
    // every session-info change (and even after `session.idle`), so treating it
    // as "working" both sticks the light on working and clobbers "idle" and
    // "approval". `session.status` (busy/idle) is the reliable work signal.
    case "permission.asked":
    case "permission.v2.asked":
    case "permission.updated": // defensive: older SDK naming
      return withSession("approval");
    case "permission.replied":
    case "permission.v2.replied":
      return withSession("working");
    case "session.error":
      return withSession("error");
    case "session.deleted":
      return props.sessionID ? { sessionID: props.sessionID, deleted: true } : null;
    default:
      return null;
  }
}

const PERMISSION_ASK = new Set([
  "permission.asked",
  "permission.v2.asked",
  "permission.updated", // defensive: older SDK naming
]);
const PERMISSION_REPLY = new Set(["permission.replied", "permission.v2.replied"]);

/** True for the events that open a pending permission request. */
export function isPermissionAsk(event) {
  return PERMISSION_ASK.has(event?.type);
}

/** True for the events that resolve a pending permission request. */
export function isPermissionReply(event) {
  return PERMISSION_REPLY.has(event?.type);
}

/**
 * Stateful wrapper around `mapEvent` that keeps "approval" sticky: while a
 * session has an unanswered permission request, every report for it becomes
 * "approval", so a later `session.status` (busy/idle) cannot clear it. An error,
 * the reply, or deletion ends it.
 *
 * @returns {(event: any) => MappedEvent | null}
 */
export function createEventMapper() {
  const pending = new Set();
  return function map(event) {
    const sessionID = eventProperties(event).sessionID;
    if (!sessionID) return null;

    if (isPermissionAsk(event)) pending.add(sessionID);
    if (isPermissionReply(event) || event?.type === "session.deleted") pending.delete(sessionID);

    const mapped = mapEvent(event);
    if (mapped && pending.has(sessionID) && mapped.status !== "error") {
      return { ...mapped, status: "approval" };
    }
    return mapped;
  };
}

const QUESTION_TOOL = "question";

/**
 * Bridge status for a `question`-tool phase, or null for any other tool.
 *
 * The question tool blocks on the user's answer but is not a permission, so it
 * emits no `permission.asked` event; report approval for its whole run and go
 * back to working once it returns.
 */
export function questionToolStatus(tool, phase) {
  if (tool !== QUESTION_TOOL) return null;
  if (phase === "before") return "approval";
  if (phase === "after") return "working";
  return null;
}

/**
 * Bridge status for an opencode permission evaluation, or null when it does not
 * wait on the user. `permission.ask` fires for every evaluation (including
 * `allow`/`deny`), so only the `ask` action means a pending approval.
 */
export function permissionAskStatus(action) {
  return action === "ask" ? "approval" : null;
}

/** Best-effort session title carried by the event, if any. */
export function sessionTitle(event) {
  const props = eventProperties(event);
  return props.info?.title ?? props.title ?? "";
}
