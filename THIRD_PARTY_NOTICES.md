# Third-Party Notices

Rebind Me uses only the Python standard library at runtime and bundles no
third-party runtime packages. Parts of its mapping, lighting and store logic
are adapted from the project below and are used under the MIT License. Protocol
facts (report layout, button bits, trigger effect encodings) are sourced in
[PROTOCOL.md](PROTOCOL.md).

## Adapted code

The mapping engine (stick direction hysteresis, trigger normalization and
effect encoding), the output report construction and the mapping-store schema
were adapted from the `PS5 DualSense` project in:

LYiHub, `pub-ai-inputs` — <https://github.com/LYiHub/pub-ai-inputs>

### MIT License

Copyright (c) 2026 深圳市有亦网络科技有限公司下属的 LYiHub

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## Bundled assets

| Asset | Source | License |
|---|---|---|
| `src/rebind_me/ui/assets/dualsense.svg` | SVG Repo (svgrepo.com) | CC0 1.0 (public domain dedication) |

The controller artwork is dedicated to the public domain under CC0 1.0. It is
used to draw the mapping diagram and is recoloured via CSS (`currentColor`).

`src/rebind_me/ui/assets/tray.ico` is generated locally by
`tools/make_tray_icon.py` and carries no third-party license.

## Trademarks

"DualSense" and "PlayStation" are trademarks of Sony Interactive Entertainment
Inc. This project is not affiliated with, sponsored by or endorsed by Sony.
The names are used only to describe compatibility.

## Python standard library

Rebind Me uses only the Python standard library at runtime, which is covered
by the Python Software Foundation License.
