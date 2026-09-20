// Bridge discovery and session reporting for the opencode plugin.
//
// Defaults: URL http://127.0.0.1:4173, token from
// %LOCALAPPDATA%\RebindMe\bridge.token. Both can be overridden with the
// REBIND_ME_URL / REBIND_ME_TOKEN environment variables. Every failure is
// silent so a missing or stopped bridge never disturbs opencode.

import { readFile } from "node:fs/promises";
import { join } from "node:path";

export const DEFAULT_URL = "http://127.0.0.1:4173";
export const RUNTIME_DIRNAME = "RebindMe";
export const TOKEN_FILENAME = "bridge.token";

/** Runtime directory holding settings and the token. */
export function runtimeDir(env = process.env) {
  const base = env.LOCALAPPDATA || "";
  return base ? join(base, RUNTIME_DIRNAME) : "";
}

/** Base URL of the bridge, without a trailing slash. */
export function baseUrl(env = process.env) {
  return (env.REBIND_ME_URL || DEFAULT_URL).replace(/\/+$/, "");
}

/** Read the bridge token, preferring the environment override. */
export async function readToken({ env = process.env, read = readFile } = {}) {
  if (env.REBIND_ME_TOKEN) return env.REBIND_ME_TOKEN;
  const dir = runtimeDir(env);
  if (!dir) return "";
  try {
    return (await read(join(dir, TOKEN_FILENAME), "utf8")).trim();
  } catch {
    return "";
  }
}

/**
 * POST one session report to `/api/sessions`. Resolves `true` on an ok
 * response and `false` on any missing token, network or HTTP error.
 */
export async function reportSession(
  session,
  { env = process.env, fetchImpl = fetch, read = readFile, timeoutMs = 1500 } = {},
) {
  const token = await readToken({ env, read });
  if (!token) return false;

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(`${baseUrl(env)}/api/sessions`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Bridge-Token": token,
      },
      body: JSON.stringify(session),
      signal: controller.signal,
    });
    return Boolean(response?.ok);
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}
