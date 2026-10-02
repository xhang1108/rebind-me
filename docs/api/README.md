# API Schema

All endpoints return a JSON envelope:

```json
{
  "ok": true,
  "error": null,
  "data": { ... }
}
```

Or on error:

```json
{
  "ok": false,
  "error": {
    "code": "CODE",
    "message": "Human-readable message"
  },
  "data": null
}
```

## Endpoints

| Method | Path | Auth | Description |
| :--- | :--- | :--- | :--- |
| GET | `/api/status` | UI | Get application status |
| POST | `/api/ui-active` | UI | Report whether the config UI holds focus |
| GET/PUT | `/api/mapping` | UI | Manage key mappings |
| GET/POST | `/api/presets` | UI | List / save presets |
| GET/POST | `/api/mic` | UI | Read mic state / toggle mute |
| GET/PUT | `/api/settings` | UI | Manage all settings (lighting, triggers, port, autostart) |
| POST | `/api/autostart` | Token | Configure autostart |
| GET/POST | `/api/plugin` | UI | Read / install / remove the OpenCode 2 plugin |
| POST | `/api/key-capture` | UI | Initiate key capture |
| POST | `/api/key-capture/cancel` | UI | Cancel key capture |
| POST | `/api/focus-terminal` | UI | Focus terminal |
| POST | `/api/scan-windows` | UI | Scan for windows |
| POST | `/api/sessions` | Token | Manage sessions |
| POST | `/api/shutdown` | Token | Shutdown application |

*Note: PUT requests require `baseVersion` in the body.*
