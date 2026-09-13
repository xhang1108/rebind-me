"""Record real DualSense input reports as decode fixtures.

Run with a controller connected over USB:

    python tools/record_fixture.py

For each checklist entry, hold the requested input and press Enter. The tool
samples live input reports and writes ``tests/fixtures/dualsense_input/
<id>.json``. The expected values come from the checklist (what you intend to
press), never from the decoder, so the fixtures catch decoder regressions
against reality.

Options:
    --outdir DIR   write fixtures elsewhere
    --only ID      record only the given entry id (repeatable)
    --force        overwrite existing fixtures
    --list         print the checklist and exit
    --check        report whether a controller is connected and exit
"""

from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rebind_me import hid, protocol  # noqa: E402

SAMPLE_SECONDS = 2.0

DEFAULT_OUTDIR = (
    Path(__file__).resolve().parent.parent
    / "tests"
    / "fixtures"
    / "dualsense_input"
)

# (id, instruction, expected, tolerance)
CHECKLIST: list[tuple[str, str, dict, float]] = [
    ("cross", "Hold cross (X); release the rest", {"buttons": ["cross"]}, 0.0),
    ("circle", "Hold circle (O)", {"buttons": ["circle"]}, 0.0),
    ("square", "Hold square", {"buttons": ["square"]}, 0.0),
    ("triangle", "Hold triangle", {"buttons": ["triangle"]}, 0.0),
    ("l1", "Hold L1", {"buttons": ["l1"]}, 0.0),
    ("r1", "Hold R1", {"buttons": ["r1"]}, 0.0),
    ("l2", "Press L2 all the way down", {"buttons": ["l2"], "leftTrigger": 1.0}, 0.05),
    ("r2", "Press R2 all the way down", {"buttons": ["r2"], "rightTrigger": 1.0}, 0.05),
    ("create", "Press Create", {"buttons": ["create"]}, 0.0),
    ("options", "Press Options", {"buttons": ["options"]}, 0.0),
    ("l3", "Press L3 (click the left stick)", {"buttons": ["l3"]}, 0.0),
    ("r3", "Press R3 (click the right stick)", {"buttons": ["r3"]}, 0.0),
    ("ps", "Press PS", {"buttons": ["ps"]}, 0.0),
    ("touchpad_click", "Press the touchpad", {"buttons": ["touchpad"]}, 0.0),
    ("mute", "Press mute", {"buttons": ["mute"]}, 0.0),
    ("dpad_up", "Press D-pad up", {"buttons": ["dpad_up"]}, 0.0),
    ("dpad_down", "Press D-pad down", {"buttons": ["dpad_down"]}, 0.0),
    ("dpad_left", "Press D-pad left", {"buttons": ["dpad_left"]}, 0.0),
    ("dpad_right", "Press D-pad right", {"buttons": ["dpad_right"]}, 0.0),
    ("stick_left", "Push the left stick fully left and hold", {"leftX": -1.0}, 0.08),
    ("stick_right", "Push the right stick fully right and hold", {"rightX": 1.0}, 0.08),
    (
        "touch_left",
        "Hold one finger on the left half of the touchpad",
        {"touchActive": True, "touchHalf": "left"},
        0.0,
    ),
    (
        "touch_right",
        "Hold one finger on the right half of the touchpad",
        {"touchActive": True, "touchHalf": "right"},
        0.0,
    ),
]

def _raw_button_bits(report: bytes) -> int:
    if len(report) < 11:
        return 0
    low = report[8] & 0x0F
    dpad_bits = 0 if low == 0x08 else low.bit_count()
    return (
        dpad_bits
        + (report[8] & 0xF0).bit_count()
        + report[9].bit_count()
        + report[10].bit_count()
    )


_AXIS_FIELDS = {
    "leftX": "left_x",
    "leftY": "left_y",
    "rightX": "right_x",
    "rightY": "right_y",
    "leftTrigger": "left_trigger",
    "rightTrigger": "right_trigger",
}


def _verify_expect(state: object, expect: dict, tolerance: float) -> list[str]:
    problems: list[str] = []
    expected_buttons = set(expect.get("buttons", []))
    actual_buttons = set(state.buttons)  # type: ignore[attr-defined]
    if expected_buttons and not expected_buttons.issubset(actual_buttons):
        missing = expected_buttons - actual_buttons
        problems.append("missing expected button(s): " + ", ".join(sorted(missing)))
    for key, field in _AXIS_FIELDS.items():
        if key not in expect:
            continue
        actual = getattr(state, field)
        if abs(actual - float(expect[key])) > max(tolerance, 0.02):
            problems.append(
                f"{key} read {actual:+.2f}, expected {float(expect[key]):+.2f}"
            )
    if "touchActive" in expect:
        has_touch = getattr(state, "touch", None) is not None
        if has_touch != expect["touchActive"]:
            problems.append("touch state does not match")
    return problems


def _record_one(
    handle: int, length: int, expect: dict, tolerance: float
) -> tuple[bytes, list[str]]:
    """Sample live reports and keep the one that best matches ``expect``.

    Button presets are selected by pressed-bit count; analog presets by how
    closely the axis matches the intended value, so a stick that is still
    moving to its limit is not captured mid-travel.
    """
    deadline = time.monotonic() + SAMPLE_SECONDS
    best = b""
    best_problems: list[str] | None = None
    best_bits = -1
    while time.monotonic() < deadline:
        report = hid.read_report(handle, length)
        try:
            problems = _verify_expect(
                protocol.decode_input_report(report), expect, tolerance
            )
        except ValueError:
            problems = ["report could not be parsed"]
        bits = _raw_button_bits(report)
        if (
            best_problems is None
            or len(problems) < len(best_problems)
            or (len(problems) == len(best_problems) and bits > best_bits)
        ):
            best, best_problems, best_bits = report, problems, bits
    return best, best_problems or []


def _write_fixture(
    outdir: Path,
    entry_id: str,
    instruction: str,
    expect: dict,
    tolerance: float,
    report: bytes,
) -> Path:
    outdir.mkdir(parents=True, exist_ok=True)
    path = outdir / f"{entry_id}.json"
    document = {
        "description": instruction,
        "hex": " ".join(f"{byte:02x}" for byte in report),
        "expect": expect,
    }
    if tolerance:
        document["tolerance"] = tolerance
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def _force_utf8() -> None:
    try:
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    except (AttributeError, OSError):
        pass
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--outdir", type=Path, default=DEFAULT_OUTDIR)
    parser.add_argument("--only", action="append", default=[])
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--list", action="store_true")
    parser.add_argument(
        "--check",
        action="store_true",
        help="only report whether a controller is connected",
    )
    args = parser.parse_args(argv)

    if args.check:
        interfaces = hid.enumerate_interfaces()
        if not interfaces:
            print("No DualSense found over USB. Connect it and press PS to wake it.")
            return 1
        for interface in interfaces:
            print(
                f"connected VID 0x{interface.vendor_id:04X} "
                f"PID 0x{interface.product_id:04X} "
                f"input={interface.input_report_length} "
                f"output={interface.output_report_length}"
            )
        return 0

    if args.list:
        for entry_id, instruction, _expect, _tol in CHECKLIST:
            print(f"{entry_id:16} {instruction}")
        return 0

    selected = [
        entry for entry in CHECKLIST if not args.only or entry[0] in args.only
    ]
    if args.only:
        unknown = set(args.only) - {entry[0] for entry in CHECKLIST}
        if unknown:
            print(f"unknown ids: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2

    interface = hid.find_dualsense()
    if interface is None:
        print(
            "No DualSense found over USB. Connect the controller and try again.",
            file=sys.stderr,
        )
        return 1

    print(
        f"found device VID 0x{interface.vendor_id:04X} "
        f"PID 0x{interface.product_id:04X} "
        f"input={interface.input_report_length} "
        f"output={interface.output_report_length}"
    )
    print("Flow: hold the requested input, then press Enter to capture (keep")
    print("holding during the sample). Type s then Enter to skip. Ctrl+C stops.\n")

    handle = hid.open_device(interface)
    saved = 0
    try:
        for entry_id, instruction, expect, tolerance in selected:
            path = args.outdir / f"{entry_id}.json"
            if path.exists() and not args.force:
                print(f"skip {entry_id} (exists; use --force to overwrite)")
                continue
            answer = input(
                f"[{entry_id}] {instruction}\n"
                "  Hold it, then press Enter (keep holding during capture); "
                "s to skip: "
            ).strip().lower()
            if answer == "s":
                print("  skipped\n")
                continue
            report, problems = _record_one(
                handle, interface.input_report_length, expect, tolerance
            )
            written = _write_fixture(
                args.outdir, entry_id, instruction, expect, tolerance, report
            )
            saved += 1

            try:
                state = protocol.decode_input_report(report)
                print(f"  captured: {', '.join(sorted(state.buttons)) or '(no buttons)'}")
            except ValueError:
                pass

            for problem in problems:
                print(f"  WARN {problem}")
            if problems:
                print(
                    f"    re-record with --only {entry_id} --force "
                    f"(sampling {SAMPLE_SECONDS:g}s)"
                )
            print(f"  saved {written}\n")
    except KeyboardInterrupt:
        print("\naborted.")
    finally:
        hid.close_device(handle)

    print(
        f"done, {saved} saved. Next: "
        "python -m unittest tests.test_protocol_fixtures -v"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
