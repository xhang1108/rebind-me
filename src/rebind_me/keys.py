"""Key, mouse and scroll code names. See plan.md §7 and §14.

Code names follow ``KeyboardEvent.code`` (``KeyK``, ``ControlLeft``,
``ArrowUp``, ...). Mouse buttons use ``MouseLeft`` / ``MouseRight`` / ... and
scroll uses ``ScrollUp`` / ``ScrollDown`` / ``ScrollLeft`` / ``ScrollRight``.
Windows virtual-key codes live in :data:`VK_CODES`.
"""

from __future__ import annotations

SCROLL_CODES = frozenset({"ScrollUp", "ScrollDown", "ScrollLeft", "ScrollRight"})
MOUSE_BUTTON_CODES = frozenset(
    {"MouseLeft", "MouseRight", "MouseMiddle", "MouseBack", "MouseForward"}
)

VK_CODES: dict[str, int] = {
    "Backspace": 0x08,
    "Tab": 0x09,
    "Enter": 0x0D,
    "Pause": 0x13,
    "CapsLock": 0x14,
    "Escape": 0x1B,
    "Space": 0x20,
    "PageUp": 0x21,
    "PageDown": 0x22,
    "End": 0x23,
    "Home": 0x24,
    "ArrowLeft": 0x25,
    "ArrowUp": 0x26,
    "ArrowRight": 0x27,
    "ArrowDown": 0x28,
    "PrintScreen": 0x2C,
    "Insert": 0x2D,
    "Delete": 0x2E,
    "MetaLeft": 0x5B,
    "MetaRight": 0x5C,
    "ContextMenu": 0x5D,
    "NumLock": 0x90,
    "ScrollLock": 0x91,
    "ShiftLeft": 0xA0,
    "ShiftRight": 0xA1,
    "ControlLeft": 0xA2,
    "ControlRight": 0xA3,
    "AltLeft": 0xA4,
    "AltRight": 0xA5,
    "VolumeMute": 0xAD,
    "Semicolon": 0xBA,
    "Equal": 0xBB,
    "Comma": 0xBC,
    "Minus": 0xBD,
    "Period": 0xBE,
    "Slash": 0xBF,
    "Backquote": 0xC0,
    "BracketLeft": 0xDB,
    "Backslash": 0xDC,
    "BracketRight": 0xDD,
    "Quote": 0xDE,
    "NumpadMultiply": 0x6A,
    "NumpadAdd": 0x6B,
    "NumpadSubtract": 0x6D,
    "NumpadDecimal": 0x6E,
    "NumpadDivide": 0x6F,
    "NumpadEnter": 0x0D,
}
VK_CODES.update({f"Key{letter}": ord(letter) for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"})
VK_CODES.update({f"Digit{digit}": ord(digit) for digit in "0123456789"})
VK_CODES.update({f"F{number}": 0x6F + number for number in range(1, 13)})
VK_CODES.update({f"Numpad{digit}": 0x60 + digit for digit in range(10)})

# NumpadEnter and Enter share a VK; keep the ordinary key for reverse lookup.
HOOK_CODES_BY_VK: dict[int, str] = {
    value: key for key, value in VK_CODES.items() if key != "NumpadEnter"
}

MODIFIER_KEY_ORDER = (
    "ControlLeft",
    "ControlRight",
    "ShiftLeft",
    "ShiftRight",
    "AltLeft",
    "AltRight",
    "MetaLeft",
    "MetaRight",
)
MODIFIER_KEY_CODES = frozenset(MODIFIER_KEY_ORDER)

# Keys that need the KEYEVENTF_EXTENDEDKEY flag in SendInput.
EXTENDED_CODES = frozenset(
    {
        "ControlRight",
        "AltRight",
        "MetaLeft",
        "MetaRight",
        "ContextMenu",
        "Insert",
        "Delete",
        "Home",
        "End",
        "PageUp",
        "PageDown",
        "ArrowLeft",
        "ArrowUp",
        "ArrowRight",
        "ArrowDown",
        "NumLock",
        "PrintScreen",
        "NumpadEnter",
        "NumpadDivide",
        "VolumeMute",
    }
)


def is_keyboard_code(code: str) -> bool:
    return code in VK_CODES


def is_mouse_code(code: str) -> bool:
    return code in MOUSE_BUTTON_CODES


def is_scroll_code(code: str) -> bool:
    return code in SCROLL_CODES


def is_valid_code(code: str) -> bool:
    return is_keyboard_code(code) or is_mouse_code(code) or is_scroll_code(code)


__all__ = [
    "EXTENDED_CODES",
    "HOOK_CODES_BY_VK",
    "MODIFIER_KEY_CODES",
    "MODIFIER_KEY_ORDER",
    "MOUSE_BUTTON_CODES",
    "SCROLL_CODES",
    "VK_CODES",
    "is_keyboard_code",
    "is_mouse_code",
    "is_scroll_code",
    "is_valid_code",
]
