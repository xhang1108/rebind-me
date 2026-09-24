// Rebind Me OpenCode 2 plugin.
//
// Forwards the public OpenCode 2 event stream to the local bridge so the
// controller light reflects the current agent state. The mapper stays in
// events.mjs so its state machine can be tested without an OpenCode runtime.

import type { Plugin as PluginApi } from "@opencode/plugin";

import { createEventMapper, sessionTitle } from "./events.mjs";
import { reportSession } from "./bridge.mjs";

const RebindMe = {
  id: "rebind-me",

  setup(ctx) {
    const titles = new Map<string, string>();
    const mapEvent = createEventMapper();
    const controller = new AbortController();

    const report = async (sessionID: string, status: string) => {
      await reportSession({
        id: sessionID,
        status,
        pid: process.pid,
        title: titles.get(sessionID) ?? "",
        lastActive: Date.now() / 1000,
      });
    };

    const consume = async () => {
      try {
        for await (const event of ctx.event.subscribe({ signal: controller.signal })) {
          const mapped = mapEvent(event);
          if (!mapped?.sessionID) continue;

          if (mapped.deleted) {
            titles.delete(mapped.sessionID);
            await reportSession({
              id: mapped.sessionID,
              deleted: true,
              lastActive: Date.now() / 1000,
            });
            continue;
          }

          const title = sessionTitle(event);
          if (title) titles.set(mapped.sessionID, title);

          // Title/metadata-only events deliberately do not report an empty
          // status, because that would erase the current bridge state.
          if (mapped.status) await report(mapped.sessionID, mapped.status);
        }
      } catch {
        // A disconnected event stream or an aborted subscription must never
        // become an unhandled rejection that disturbs the coding session.
      }
    };

    void consume();

    return () => controller.abort();
  },
} satisfies PluginApi.Plugin;

export default RebindMe;
