# rebind-me

The [OpenCode 2](https://github.com/xhang1108/rebind-me) plugin for **Rebind Me**.
It forwards the public OpenCode 2 session event stream to the local Rebind Me
bridge, so the DualSense light — and the bridge's focus-terminal action — follow
what the agent is doing.

Requires **OpenCode 2.0.15 or newer** and a running Rebind Me bridge. OpenCode
1.x hooks are not supported.

## Install

The bridge owns the installation; you do not add this package by hand:

```bat
python -m rebind_me plugin install
```

The installer adds `rebind-me` to the `plugins` array in your OpenCode 2
configuration once this package is published, and copies it locally otherwise.
`python -m rebind_me plugin status` reports which route is active, and
`uninstall-plugin.cmd` removes it. Reload OpenCode 2 / OpenChamber 2 afterwards.

## What it reports

One status per session, driven to the bridge as `idle`, `working`, `approval`
or `error`. Several approval prompts stay visible until all of them settle, and
a session that goes away is reported as deleted.

## Bridge discovery

| | Default | Override |
|---|---|---|
| URL | `http://127.0.0.1:4173` | `REBIND_ME_URL` |
| Token | `%LOCALAPPDATA%\RebindMe\bridge.token` | `REBIND_ME_TOKEN` |

Every failure is silent: a missing or stopped bridge never disturbs a coding
session.
