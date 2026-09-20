// Rebind Me opencode plugin (typed adapter).
//
// Forwards session events to the local bridge so the controller light reflects
// the agent state, and reports terminal identity via POST /api/sessions for
// the focus-terminal action. Bun runs this TypeScript directly (no build); the
// testable logic lives in events.mjs and bridge.mjs.

import type { Plugin } from "@opencode-ai/plugin";

import { createEventMapper, permissionAskStatus, questionToolStatus, sessionTitle } from "./events.mjs";
import { reportSession } from "./bridge.mjs";

const RebindMe: Plugin = async () => {
  const titles = new Map<string, string>();
  const mapEvent = createEventMapper();

  const report = async (sessionID: string, status: string) => {
    await reportSession({
      id: sessionID,
      status,
      pid: process.pid,
      title: titles.get(sessionID) ?? "",
      lastActive: Date.now() / 1000,
    });
  };

  return {
    event: async ({ event }) => {
      const mapped = mapEvent(event);
      if (!mapped?.sessionID) return;

      if (mapped.deleted) {
        titles.delete(mapped.sessionID);
        await reportSession({
          id: mapped.sessionID,
          deleted: true,
          lastActive: Date.now() / 1000,
        });
        return;
      }

      const title = sessionTitle(event);
      if (title) titles.set(mapped.sessionID, title);

      if (mapped.status) await report(mapped.sessionID, mapped.status);
    },
    // The question tool waits on the user but emits no permission event.
    "tool.execute.before": async (input) => {
      const status = questionToolStatus(input.tool, "before");
      if (status) await report(input.sessionID, status);
    },
    "tool.execute.after": async (input) => {
      const status = questionToolStatus(input.tool, "after");
      if (status) await report(input.sessionID, status);
    },
    // Fires for every permission evaluation; only "ask" is an approval.
    "permission.ask": async (input, output) => {
      const status = permissionAskStatus(output.status);
      if (status) await report(input.sessionID, status);
    },
  };
};

export default RebindMe;
