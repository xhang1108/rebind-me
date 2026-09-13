# Third-Party Notices

Rebind Me is an independent implementation. It bundles **no** third-party
source code. The projects below were consulted to establish the DualSense HID
protocol **facts** (report IDs, byte offsets and bit meanings). Only those
facts were used; no source code was copied or adapted.

Where a project is named below, its own license continues to govern that
project. Refer to the upstream repository for the authoritative license text.

## Protocol references

| Project | Upstream | Notes |
|---|---|---|
| Linux kernel `hid-playstation.c` | torvalds/linux | GPL-2.0; consulted for report layout facts only |
| `nondebug/dualsense` | github.com/nondebug/dualsense | Rust; consulted for protocol facts only |
| `flok/pydualsense` | github.com/flok/pydualsense | Python; consulted for protocol facts only |
| `DS5W` | github.com/Ohjurot/DS5W | C++; consulted for protocol facts only |
| `dualsense-ts` | github.com/nsfm/dualsense-ts | Node; consulted for protocol facts only |
| SDL `SDL_hidapi_ps5.c` | libsdl-org/SDL | zlib license (SDL); consulted for protocol facts only |

## Trademarks

"DualSense" and "PlayStation" are trademarks of Sony Interactive Entertainment
Inc. This project is not affiliated with, sponsored by or endorsed by Sony.
The names are used only to describe compatibility.

## Python standard library

Rebind Me uses only the Python standard library at runtime, which is covered
by the Python Software Foundation License.
